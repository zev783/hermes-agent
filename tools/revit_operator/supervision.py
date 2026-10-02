"""Read-only long-running Revit supervision loops."""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bridge import RevitBridgeClient
from .journal import TaskJournal, utc_now
from .recovery import capture_recovery_snapshot
from .safety import classify_action, validate_output_path
from .windows import RevitWindowObserver


ACTIVE_SUPERVISION_CHECKPOINT_GRACE_SECONDS = 15 * 60


def supervise_session(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    duration: float = 300.0,
    poll: float = 5.0,
    max_checks: int | None = None,
    stop_on_modal: bool = True,
    bridge_result_limit: int = 10,
    resume: bool = False,
    stall_after_checks: int = 12,
    recovery_on_stall: bool = True,
) -> dict:
    """Poll Revit state and write a read-only supervision log."""

    output = journal.run_dir / "supervision_log.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    existing = _load_existing_log(output) if resume else {}
    previous_checks = list(existing.get("checks") or [])
    previous_transitions = list(existing.get("transitions") or [])
    previous_segments = list(existing.get("segments") or [])
    previous_count = len(previous_checks)

    started = time.monotonic()
    deadline = started + max(0.0, duration)
    new_checks: list[dict] = []
    new_transitions: list[dict] = []
    previous_state: str | None = (
        str(previous_checks[-1].get("state") or "unknown") if previous_checks else None
    )
    stop_reason = "duration_elapsed"
    segment_started_at = utc_now()
    state_streak = 0
    stall_analysis: dict | None = None
    recovery_snapshot: dict | None = None

    while True:
        status = observer.status()
        dialogs = status.get("active_dialogs") or []
        state = str(status.get("state") or "unknown")
        bridge_results = bridge.read_command_results()
        if bridge_result_limit >= 0:
            bridge_results = bridge_results[-bridge_result_limit:] if bridge_result_limit else []
        check = {
            "checked_at": utc_now(),
            "index": previous_count + len(new_checks),
            "state": state,
            "revit_running": bool(status.get("revit_running")),
            "active_dialog_count": len(dialogs),
            "main_window": status.get("main_window"),
            "recent_bridge_results": bridge_results,
        }
        new_checks.append(check)

        if previous_state is None or previous_state != state:
            new_transitions.append(
                {
                    "checked_at": check["checked_at"],
                    "from": previous_state,
                    "to": state,
                    "index": check["index"],
                }
            )
            previous_state = state
            state_streak = 1
        else:
            state_streak += 1

        check["state_streak"] = state_streak
        stall_analysis = _stall_analysis(
            state=state,
            state_streak=state_streak,
            stall_after_checks=stall_after_checks,
            active_dialog_count=len(dialogs),
            status=status,
        )

        checkpoint_segment = {
            "started_at": segment_started_at,
            "finished_at": utc_now(),
            "start_index": previous_count,
            "check_count": len(new_checks),
            "stop_reason": "running",
            "resumed": bool(previous_checks),
        }
        _write_supervision_result(
            output,
            existing=existing,
            checks=previous_checks + new_checks,
            transitions=previous_transitions + new_transitions,
            segments=previous_segments + [checkpoint_segment],
            previous_count=previous_count,
            new_checks=new_checks,
            stop_reason="running",
            stall_analysis=stall_analysis,
            recovery_snapshot=recovery_snapshot,
            in_progress=True,
        )

        if stop_on_modal and (state == "modal" or dialogs):
            stop_reason = "modal_state_detected"
            break
        if stall_analysis.get("stalled"):
            stop_reason = "stalled_state_detected"
            if recovery_on_stall:
                recovery_snapshot = _capture_supervision_recovery_snapshot(
                    journal,
                    observer,
                    bridge,
                    bridge_result_limit=bridge_result_limit,
                )
            break
        if max_checks is not None and len(new_checks) >= max_checks:
            stop_reason = "max_checks_reached"
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.1, poll))

    checks = previous_checks + new_checks
    transitions = previous_transitions + new_transitions
    segment = {
        "started_at": segment_started_at,
        "finished_at": utc_now(),
        "start_index": previous_count,
        "check_count": len(new_checks),
        "stop_reason": stop_reason,
        "resumed": bool(previous_checks),
    }
    segments = previous_segments + [segment]

    result = _write_supervision_result(
        output,
        existing=existing,
        checks=checks,
        transitions=transitions,
        segments=segments,
        previous_count=previous_count,
        new_checks=new_checks,
        stop_reason=stop_reason,
        stall_analysis=stall_analysis,
        recovery_snapshot=recovery_snapshot,
        in_progress=False,
    )
    journal.write_entry(
        {
            "command": "supervise-session",
            "requested_action": {
                "duration": duration,
                "poll": poll,
                "max_checks": max_checks,
                "stop_on_modal": stop_on_modal,
                "bridge_result_limit": bridge_result_limit,
                "resume": resume,
                "stall_after_checks": stall_after_checks,
                "recovery_on_stall": recovery_on_stall,
            },
            "risk_classification": classify_action("supervise-session", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only supervision loop."},
            "result": {
                "status": result["stop_reason"],
                "check_count": result["check_count"],
                "new_check_count": result["new_check_count"],
                "resumed": result["resumed"],
                "final_state": result["final_state"],
                "final_active_dialog_count": result["final_active_dialog_count"],
                "recovery_snapshot_captured": bool(result["recovery_snapshot"]),
            },
            "output_files": [str(output)],
        }
    )
    return result


def _write_supervision_result(
    output: Path,
    *,
    existing: dict,
    checks: list[dict],
    transitions: list[dict],
    segments: list[dict],
    previous_count: int,
    new_checks: list[dict],
    stop_reason: str,
    stall_analysis: dict | None,
    recovery_snapshot: dict | None,
    in_progress: bool,
) -> dict:
    result = {
        "success": True,
        "started_at": existing.get("started_at") or (
            checks[0]["checked_at"] if checks else utc_now()
        ),
        "finished_at": utc_now(),
        "stop_reason": stop_reason,
        "checkpoint_status": "running" if in_progress else "complete",
        "in_progress": bool(in_progress),
        "supervisor_pid": os.getpid(),
        "check_count": len(checks),
        "previous_check_count": previous_count,
        "new_check_count": len(new_checks),
        "resumed": bool(previous_count),
        "segments": segments,
        "transitions": transitions,
        "final_state": checks[-1]["state"] if checks else "unknown",
        "final_active_dialog_count": checks[-1]["active_dialog_count"] if checks else 0,
        "stall_analysis": stall_analysis or {"stalled": False, "reason": "No checks were recorded."},
        "recovery_snapshot": recovery_snapshot,
        "checks": checks,
        "read_only": True,
        "path": str(output),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def audit_supervision_endurance(
    journal: TaskJournal,
    *,
    target_hours: float = 2.0,
    min_checks: int = 24,
    require_live_window: bool = True,
    audit_now: datetime | None = None,
) -> dict:
    """Audit accumulated live supervision logs against an hours-long target."""

    audit_now = (audit_now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    runs_root = journal.sandbox / "revit_operator_runs"
    log_paths = sorted(runs_root.glob("*/supervision_log.json")) if runs_root.exists() else []
    records = [
        _supervision_log_record(path, require_live_window=require_live_window, audit_now=audit_now)
        for path in log_paths
    ]
    qualifying = [record for record in records if record.get("qualifies")]
    raw_total_seconds = sum(float(record.get("duration_seconds") or 0.0) for record in qualifying)
    merged_intervals = _merge_supervision_intervals(qualifying)
    total_seconds = sum(
        (finish - start).total_seconds()
        for start, finish in merged_intervals
    )
    check_count = sum(int(record.get("check_count") or 0) for record in qualifying)
    segment_count = sum(int(record.get("segment_count") or 0) for record in qualifying)
    longest_segment_seconds = max(
        (float(record.get("longest_segment_seconds") or 0.0) for record in qualifying),
        default=0.0,
    )
    target_seconds = max(0.0, float(target_hours) * 3600.0)
    duration_met = total_seconds >= target_seconds
    checks_met = check_count >= max(0, int(min_checks))
    target_met = duration_met and checks_met
    duration_remaining_seconds = max(0.0, target_seconds - total_seconds)
    check_count_remaining = max(0, int(min_checks) - check_count)
    active_interval_extended_log_count = sum(
        1 for record in qualifying if record.get("active_interval_extended")
    )
    active_interval_extension_seconds = sum(
        float(record.get("active_interval_extension_seconds") or 0.0)
        for record in qualifying
    )
    estimated_duration_target_at = None
    if duration_remaining_seconds > 0 and active_interval_extended_log_count:
        estimated_duration_target_at = _format_utc_timestamp(
            audit_now + timedelta(seconds=duration_remaining_seconds)
        )
    if duration_met:
        estimate_reason = "duration target already met"
    elif active_interval_extended_log_count:
        estimate_reason = "active supervisor pid confirmed running"
    else:
        estimate_reason = "no active pid-confirmed supervisor interval to project"

    output = journal.run_dir / "supervision_endurance_audit.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": True,
        "read_only": True,
        "live_ui_touched": False,
        "status": "target_met" if target_met else "insufficient_evidence",
        "target_met": target_met,
        "target_hours": float(target_hours),
        "target_seconds": target_seconds,
        "min_checks": int(min_checks),
        "require_live_window": bool(require_live_window),
        "duration_met": duration_met,
        "checks_met": checks_met,
        "duration_remaining_seconds": duration_remaining_seconds,
        "check_count_remaining": check_count_remaining,
        "estimated_duration_target_at": estimated_duration_target_at,
        "estimated_duration_target_reason": estimate_reason,
        "total_live_seconds": total_seconds,
        "total_live_hours": total_seconds / 3600.0,
        "raw_total_live_seconds": raw_total_seconds,
        "overlap_adjusted": True,
        "audit_timestamp": _format_utc_timestamp(audit_now),
        "active_checkpoint_grace_seconds": ACTIVE_SUPERVISION_CHECKPOINT_GRACE_SECONDS,
        "active_interval_extended_log_count": active_interval_extended_log_count,
        "active_interval_extension_seconds": active_interval_extension_seconds,
        "merged_interval_count": len(merged_intervals),
        "merged_intervals": [
            {
                "started_at": _format_utc_timestamp(start),
                "finished_at": _format_utc_timestamp(finish),
                "duration_seconds": (finish - start).total_seconds(),
            }
            for start, finish in merged_intervals
        ],
        "check_count": check_count,
        "segment_count": segment_count,
        "longest_segment_seconds": longest_segment_seconds,
        "log_count": len(records),
        "qualifying_log_count": len(qualifying),
        "excluded_log_count": len(records) - len(qualifying),
        "in_progress_log_count": sum(
            1 for record in qualifying if record.get("in_progress")
        ),
        "active_in_progress_log_count": sum(
            1
            for record in qualifying
            if record.get("in_progress") and record.get("supervisor_pid_running") is True
        ),
        "stale_in_progress_log_count": sum(
            1
            for record in qualifying
            if record.get("in_progress") and record.get("supervisor_pid_running") is False
        ),
        "qualifying_logs": qualifying,
        "excluded_logs": [record for record in records if not record.get("qualifies")],
        "path": str(output),
        "note": (
            "Read-only evidence audit only. This command scans supervision logs "
            "under the sandbox and does not poll, focus, click, type, queue bridge "
            "commands, or touch live Revit UI."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "supervision-endurance-audit",
            "requested_action": {
                "target_hours": target_hours,
                "min_checks": min_checks,
                "require_live_window": require_live_window,
            },
            "risk_classification": classify_action("supervision-endurance-audit", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only supervision evidence audit."},
            "result": {
                "status": result["status"],
                "target_met": target_met,
                "total_live_hours": result["total_live_hours"],
                "check_count": check_count,
            },
            "output_files": [str(output)],
        }
    )
    return result


def build_supervision_status(
    journal: TaskJournal,
    *,
    target_hours: float = 4.0,
    require_live_window: bool = True,
    audit_now: datetime | None = None,
) -> dict:
    """Summarize active supervision logs and the current endurance target."""

    audit_now = (audit_now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    runs_root = journal.sandbox / "revit_operator_runs"
    log_paths = sorted(runs_root.glob("*/supervision_log.json")) if runs_root.exists() else []
    records = [
        _supervision_log_record(path, require_live_window=require_live_window, audit_now=audit_now)
        for path in log_paths
    ]
    active = [
        record
        for record in records
        if record.get("in_progress") and record.get("supervisor_pid_running") is True
    ]
    endurance = audit_supervision_endurance(
        journal,
        target_hours=target_hours,
        require_live_window=require_live_window,
        audit_now=audit_now,
    )
    status = "target_met" if endurance.get("target_met") else "active" if active else "insufficient_evidence"
    result = {
        "success": True,
        "read_only": True,
        "live_ui_touched": False,
        "schema": "hermes-revit-agent-session-supervision-status/v1",
        "created_at": _format_utc_timestamp(audit_now),
        "status": status,
        "reason": _supervision_status_reason(status, active, endurance),
        "target_hours": float(target_hours),
        "log_count": len(records),
        "active_supervision_count": len(active),
        "active_supervision_logs": active[:10],
        "recent_supervision_logs": sorted(
            records,
            key=lambda item: str(item.get("last_check_at") or item.get("path") or ""),
            reverse=True,
        )[:10],
        "endurance_audit": {
            "path": endurance.get("path"),
            "status": endurance.get("status"),
            "target_met": endurance.get("target_met"),
            "total_live_hours": endurance.get("total_live_hours"),
            "qualifying_log_count": endurance.get("qualifying_log_count"),
            "excluded_log_count": endurance.get("excluded_log_count"),
        },
        "goal_complete": False,
        "may_call_update_goal": False,
        "note": (
            "Read-only status only. This command scans sandbox supervision logs "
            "and process liveness; it does not focus, click, type, or modify Revit."
        ),
    }
    output = journal.run_dir / "agent_session_supervision_status.json"
    markdown = journal.run_dir / "agent_session_supervision_status.md"
    error = validate_output_path(output, journal.sandbox) or validate_output_path(markdown, journal.sandbox)
    if error:
        return {"success": False, "error": error, "goal_complete": False, "may_call_update_goal": False}
    result["path"] = str(output)
    result["markdown_path"] = str(markdown)
    result["output_files"] = [str(output), str(markdown), endurance.get("path")]
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    markdown.write_text(_supervision_status_markdown(result), encoding="utf-8")
    journal.write_entry(
        {
            "command": "agent-session-supervision-status",
            "requested_action": {
                "target_hours": target_hours,
                "require_live_window": require_live_window,
            },
            "risk_classification": classify_action("agent-session-supervision-status", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only supervision status scan."},
            "result": {
                "status": status,
                "active_supervision_count": len(active),
                "target_met": endurance.get("target_met"),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
        }
    )
    return result


def _supervision_status_reason(status: str, active: list[dict], endurance: dict) -> str:
    if status == "target_met":
        return "The configured supervision endurance target has current qualifying evidence."
    if status == "active":
        return f"{len(active)} supervision process/log appears active, but the endurance target is not met yet."
    if endurance.get("log_count"):
        return "Supervision logs exist, but they do not yet satisfy the endurance target."
    return "No qualifying live supervision log evidence was found."


def _supervision_status_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Supervision Status",
        "",
        f"Status: `{result.get('status')}`",
        f"Goal complete: `{str(result.get('goal_complete')).lower()}`",
        f"May call update_goal: `{str(result.get('may_call_update_goal')).lower()}`",
        f"Reason: {result.get('reason')}",
        "",
        "## Endurance",
        "",
    ]
    audit = result.get("endurance_audit") if isinstance(result.get("endurance_audit"), dict) else {}
    lines.extend(
        [
            f"- target_hours: `{result.get('target_hours')}`",
            f"- target_met: `{str(audit.get('target_met')).lower()}`",
            f"- total_live_hours: `{audit.get('total_live_hours')}`",
            f"- active_supervision_count: `{result.get('active_supervision_count')}`",
            f"- audit_path: `{audit.get('path')}`",
            "",
            "## Active Logs",
            "",
        ]
    )
    for record in result.get("active_supervision_logs", []):
        lines.append(
            f"- `{record.get('task_id')}`: checks=`{record.get('check_count')}` "
            f"pid=`{record.get('supervisor_pid')}`"
        )
    if not result.get("active_supervision_logs"):
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def validate_supervision_endurance_matrix(journal: TaskJournal) -> dict:
    """Run synthetic supervision drills that exercise resume/stall behavior.

    This is a bounded stand-in for multi-hour supervision validation. It uses
    the real supervision loop with fake observers/bridge clients, writes normal
    supervision logs, and verifies that long-run safety properties hold without
    touching live Revit.
    """

    cases = [
        _endurance_resume_case(journal),
        _endurance_modal_case(journal),
        _endurance_busy_stall_case(journal),
        _endurance_unknown_stall_case(journal),
    ]

    output = journal.run_dir / "supervision_endurance_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "synthetic": True,
        "case_count": len(cases),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": (
            "Synthetic supervision endurance rehearsal only. It exercises the "
            "real supervision loop against fake observers; no live Revit state, "
            "UI, bridge queue, or model data was changed."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "supervision-endurance-matrix",
            "requested_action": {"case_count": len(cases)},
            "risk_classification": classify_action("supervision-endurance-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only synthetic supervision validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def _endurance_resume_case(journal: TaskJournal) -> dict:
    case_journal = _case_journal(journal, "resume-segments")
    bridge = _SyntheticBridge()
    first = supervise_session(
        case_journal,
        _SyntheticObserver(
            [
                {"state": "idle", "revit_running": True, "active_dialogs": []},
                {"state": "idle", "revit_running": True, "active_dialogs": []},
            ]
        ),
        bridge,
        duration=10,
        poll=0,
        max_checks=2,
        stall_after_checks=0,
    )
    second = supervise_session(
        case_journal,
        _SyntheticObserver(
            [
                {"state": "busy", "revit_running": True, "active_dialogs": []},
                {"state": "idle", "revit_running": True, "active_dialogs": []},
            ]
        ),
        bridge,
        duration=10,
        poll=0,
        max_checks=2,
        stall_after_checks=0,
        resume=True,
    )
    transition_pairs = [
        (transition.get("from"), transition.get("to"))
        for transition in second.get("transitions") or []
    ]
    checks = [
        _matrix_check(
            "first_segment_recorded",
            first.get("check_count") == 2 and len(first.get("segments") or []) == 1,
            "First segment recorded two checks.",
            "First segment did not record the expected checks.",
        ),
        _matrix_check(
            "resume_appended",
            second.get("resumed") is True and second.get("previous_check_count") == 2,
            "Resume preserved the previous checks.",
            "Resume did not preserve the previous checks.",
        ),
        _matrix_check(
            "two_segments_present",
            second.get("check_count") == 4 and len(second.get("segments") or []) == 2,
            "Two supervision segments are present after resume.",
            "Expected two supervision segments after resume.",
        ),
        _matrix_check(
            "transition_across_resume",
            ("idle", "busy") in transition_pairs and ("busy", "idle") in transition_pairs,
            "Transitions across the resumed segment were recorded.",
            "Expected idle/busy transitions were missing after resume.",
        ),
    ]
    return _endurance_case_result(
        "resume-segments",
        checks,
        {
            "first": _supervision_summary(first),
            "second": _supervision_summary(second),
            "path": second.get("path"),
        },
    )


def _endurance_modal_case(journal: TaskJournal) -> dict:
    case_journal = _case_journal(journal, "modal-stop")
    result = supervise_session(
        case_journal,
        _SyntheticObserver(
            [
                {"state": "idle", "revit_running": True, "active_dialogs": []},
                {
                    "state": "modal",
                    "revit_running": True,
                    "active_dialogs": [{"title": "Upgrade model"}],
                },
            ]
        ),
        _SyntheticBridge(),
        duration=10,
        poll=0,
        max_checks=5,
    )
    checks = [
        _matrix_check(
            "modal_stop",
            result.get("stop_reason") == "modal_state_detected",
            "Supervision stopped on modal state.",
            "Supervision did not stop on modal state.",
        ),
        _matrix_check(
            "dialog_count_recorded",
            result.get("final_active_dialog_count") == 1,
            "Final modal dialog count was recorded.",
            "Final modal dialog count was not recorded.",
        ),
        _matrix_check(
            "no_recovery_for_modal_stop",
            result.get("recovery_snapshot") is None,
            "Modal stop did not run blind recovery actions.",
            "Modal stop unexpectedly captured a recovery snapshot.",
        ),
    ]
    return _endurance_case_result("modal-stop", checks, _supervision_summary(result))


def _endurance_busy_stall_case(journal: TaskJournal) -> dict:
    case_journal = _case_journal(journal, "busy-stall-recovery")
    result = supervise_session(
        case_journal,
        _SyntheticObserver(
            [
                {
                    "state": "busy",
                    "revit_running": True,
                    "active_dialogs": [],
                    "windows": [{"title": "Autodesk Revit", "is_hung": True}],
                },
                {
                    "state": "busy",
                    "revit_running": True,
                    "active_dialogs": [],
                    "windows": [{"title": "Autodesk Revit", "is_hung": True}],
                },
            ]
        ),
        _SyntheticBridge(),
        duration=10,
        poll=0,
        max_checks=5,
        stall_after_checks=2,
        recovery_on_stall=True,
    )
    recovery = result.get("recovery_snapshot") or {}
    checks = [
        _matrix_check(
            "busy_stall_detected",
            result.get("stop_reason") == "stalled_state_detected"
            and result.get("stall_analysis", {}).get("stalled") is True,
            "Repeated busy state was detected as a stall.",
            "Repeated busy state did not trigger stall detection.",
        ),
        _matrix_check(
            "hung_window_recorded",
            result.get("stall_analysis", {}).get("hung_window_count") == 1,
            "Hung-window evidence was recorded.",
            "Hung-window evidence was not recorded.",
        ),
        _matrix_check(
            "recovery_snapshot_captured",
            recovery.get("success") is True and bool(recovery.get("path")),
            "Recovery snapshot was captured on stall.",
            "Recovery snapshot was not captured on stall.",
        ),
    ]
    return _endurance_case_result("busy-stall-recovery", checks, _supervision_summary(result))


def _endurance_unknown_stall_case(journal: TaskJournal) -> dict:
    case_journal = _case_journal(journal, "unknown-stall-no-recovery")
    result = supervise_session(
        case_journal,
        _SyntheticObserver(
            [
                {"state": "unknown", "revit_running": True, "active_dialogs": []},
                {"state": "unknown", "revit_running": True, "active_dialogs": []},
            ]
        ),
        _SyntheticBridge(),
        duration=10,
        poll=0,
        max_checks=5,
        stall_after_checks=2,
        recovery_on_stall=False,
    )
    checks = [
        _matrix_check(
            "unknown_stall_detected",
            result.get("stop_reason") == "stalled_state_detected"
            and result.get("stall_analysis", {}).get("state") == "unknown",
            "Repeated unknown state was detected as a stall.",
            "Repeated unknown state did not trigger stall detection.",
        ),
        _matrix_check(
            "recovery_can_be_disabled",
            result.get("recovery_snapshot") is None,
            "Recovery snapshot can be disabled for bounded endurance rehearsal.",
            "Recovery snapshot was captured despite recovery_on_stall=False.",
        ),
        _matrix_check(
            "no_dialog_assumption",
            result.get("final_active_dialog_count") == 0,
            "Unknown-state stall kept dialog count explicit at zero.",
            "Unknown-state stall did not preserve dialog count.",
        ),
    ]
    return _endurance_case_result("unknown-stall-no-recovery", checks, _supervision_summary(result))


def _case_journal(parent: TaskJournal, slug: str) -> TaskJournal:
    safe_slug = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in slug).strip("-")
    return TaskJournal(parent.sandbox, f"{parent.task_id}-{safe_slug}")


def _endurance_case_result(name: str, checks: list[dict], evidence: dict) -> dict:
    return {
        "name": name,
        "success": all(check["passed"] for check in checks),
        "checks": checks,
        "evidence": evidence,
    }


def _supervision_summary(result: dict) -> dict:
    return {
        "success": result.get("success"),
        "stop_reason": result.get("stop_reason"),
        "check_count": result.get("check_count"),
        "previous_check_count": result.get("previous_check_count"),
        "new_check_count": result.get("new_check_count"),
        "resumed": result.get("resumed"),
        "segment_count": len(result.get("segments") or []),
        "transition_count": len(result.get("transitions") or []),
        "final_state": result.get("final_state"),
        "final_active_dialog_count": result.get("final_active_dialog_count"),
        "stall_analysis": result.get("stall_analysis"),
        "recovery_snapshot": result.get("recovery_snapshot"),
        "path": result.get("path"),
    }


class _SyntheticBridge:
    def read_command_results(self) -> list[dict]:
        return [{"id": "synthetic-active-document", "operation": "active-document", "success": True}]

    def active_document_status(self) -> dict:
        return {
            "status": "synthetic",
            "read_only": True,
            "title": "Synthetic supervision document",
            "revit_version": "2025",
        }


class _SyntheticObserver:
    supported = True

    def __init__(self, statuses: list[dict]):
        self._statuses = [deepcopy(status) for status in statuses]
        self._last = deepcopy(self._statuses[-1]) if self._statuses else {"state": "unknown"}

    def status(self) -> dict:
        if self._statuses:
            self._last = deepcopy(self._statuses.pop(0))
        return deepcopy(self._last)

    def list_dialogs(self) -> dict:
        dialogs = []
        for dialog in self._last.get("active_dialogs") or []:
            if isinstance(dialog, dict):
                dialogs.append(deepcopy(dialog))
        return {"success": True, "dialogs": dialogs}

    def ui_tree(self, max_depth: int = 2) -> dict:
        return {"success": True, "supported": True, "max_depth": max_depth, "tree": {}}

    def screenshot(self, output) -> dict:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"BM")
        return {"success": True, "path": str(output)}


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }


def _load_existing_log(path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _supervision_log_record(
    path: Path,
    *,
    require_live_window: bool,
    audit_now: datetime | None = None,
) -> dict:
    payload = _load_existing_log(path)
    audit_now = (audit_now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    task_id = path.parent.name
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
    live_window_checks = [
        check for check in checks if isinstance(check, dict) and bool(check.get("main_window"))
    ]
    excluded_reasons = []
    if "supervision-endurance-matrix" in task_id:
        excluded_reasons.append("synthetic endurance matrix run")
    if "test" in task_id.lower():
        excluded_reasons.append("test run name")
    if require_live_window and not live_window_checks:
        excluded_reasons.append("no live main_window evidence")
    checkpoint_status = str(payload.get("checkpoint_status") or "")
    in_progress = bool(payload.get("in_progress")) or checkpoint_status == "running"
    supervisor_pid = _coerce_pid(payload.get("supervisor_pid"))
    supervisor_pid_running = (
        _pid_is_running(supervisor_pid) if supervisor_pid is not None else None
    )
    intervals = _supervision_intervals(segments, checks)
    (
        intervals,
        active_interval_extended,
        active_interval_extension_seconds,
        active_interval_extension_reason,
    ) = _extend_active_supervision_interval(
        intervals,
        in_progress=in_progress,
        supervisor_pid_running=supervisor_pid_running,
        audit_now=audit_now,
    )
    duration_seconds, longest_segment_seconds = _supervision_durations(intervals)
    if duration_seconds <= 0 and len(checks) > 1:
        excluded_reasons.append("no positive observed duration")
    qualifies = not excluded_reasons
    return {
        "task_id": task_id,
        "path": str(path),
        "qualifies": qualifies,
        "excluded_reasons": excluded_reasons,
        "duration_seconds": duration_seconds if qualifies else 0.0,
        "raw_duration_seconds": duration_seconds,
        "checkpoint_status": checkpoint_status or None,
        "in_progress": in_progress,
        "supervisor_pid": supervisor_pid,
        "supervisor_pid_running": supervisor_pid_running,
        "active_interval_extended": active_interval_extended,
        "active_interval_extension_seconds": active_interval_extension_seconds,
        "active_interval_extension_reason": active_interval_extension_reason,
        "intervals": [
            {
                "started_at": _format_utc_timestamp(start),
                "finished_at": _format_utc_timestamp(finish),
                "duration_seconds": (finish - start).total_seconds(),
            }
            for start, finish in intervals
        ],
        "longest_segment_seconds": longest_segment_seconds if qualifies else 0.0,
        "check_count": len(checks) if qualifies else 0,
        "raw_check_count": len(checks),
        "segment_count": len(segments) if qualifies else 0,
        "raw_segment_count": len(segments),
        "live_window_check_count": len(live_window_checks),
        "stop_reasons": sorted(
            {
                str(segment.get("stop_reason"))
                for segment in segments
                if isinstance(segment, dict) and segment.get("stop_reason")
            }
        ),
        "final_state": payload.get("final_state"),
        "final_active_dialog_count": payload.get("final_active_dialog_count"),
        "stall_analysis": payload.get("stall_analysis"),
    }


def _supervision_intervals(segments: list, checks: list) -> list[tuple[datetime, datetime]]:
    intervals = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _parse_utc_timestamp(segment.get("started_at"))
        finish = _parse_utc_timestamp(segment.get("finished_at"))
        if start and finish and finish >= start:
            intervals.append((start, finish))
    if intervals:
        return intervals

    check_times = [
        parsed
        for check in checks
        if isinstance(check, dict)
        for parsed in [_parse_utc_timestamp(check.get("checked_at"))]
        if parsed
    ]
    if len(check_times) < 2:
        return []
    start = min(check_times)
    finish = max(check_times)
    return [(start, finish)] if finish >= start else []


def _extend_active_supervision_interval(
    intervals: list[tuple[datetime, datetime]],
    *,
    in_progress: bool,
    supervisor_pid_running: bool | None,
    audit_now: datetime,
) -> tuple[list[tuple[datetime, datetime]], bool, float, str | None]:
    if not intervals:
        return intervals, False, 0.0, "no interval to extend"
    if not in_progress:
        return intervals, False, 0.0, "log is not in progress"
    if supervisor_pid_running is not True:
        return intervals, False, 0.0, "supervisor pid is not confirmed running"

    start, finish = intervals[-1]
    if audit_now <= finish:
        return intervals, False, 0.0, "checkpoint is not older than audit timestamp"
    checkpoint_age = (audit_now - finish).total_seconds()
    if checkpoint_age > ACTIVE_SUPERVISION_CHECKPOINT_GRACE_SECONDS:
        return intervals, False, 0.0, "last checkpoint is outside active grace window"

    extended = list(intervals)
    extended[-1] = (start, audit_now)
    return extended, True, checkpoint_age, "active supervisor pid confirmed running"


def _supervision_durations(intervals: list[tuple[datetime, datetime]]) -> tuple[float, float]:
    durations = [
        (finish - start).total_seconds()
        for start, finish in intervals
        if finish >= start
    ]
    if not durations:
        return 0.0, 0.0
    return sum(durations), max(durations)


def _merge_supervision_intervals(records: list[dict]) -> list[tuple[datetime, datetime]]:
    intervals = []
    for record in records:
        for interval in record.get("intervals") or []:
            if not isinstance(interval, dict):
                continue
            start = _parse_utc_timestamp(interval.get("started_at"))
            finish = _parse_utc_timestamp(interval.get("finished_at"))
            if start and finish and finish >= start:
                intervals.append((start, finish))
    intervals.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, finish in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, finish))
            continue
        previous_start, previous_finish = merged[-1]
        if finish > previous_finish:
            merged[-1] = (previous_start, finish)
    return merged


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_pid(value: object) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
        except Exception:
            return False
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stall_analysis(
    *,
    state: str,
    state_streak: int,
    stall_after_checks: int,
    active_dialog_count: int,
    status: dict,
) -> dict:
    if stall_after_checks <= 0:
        return {
            "stalled": False,
            "state": state,
            "state_streak": state_streak,
            "enabled": False,
            "reason": "Stall detection disabled.",
        }

    stalled_state = state in {"busy", "unknown"} and active_dialog_count == 0
    hung_windows = [
        window
        for window in status.get("windows") or []
        if isinstance(window, dict) and window.get("is_hung")
    ]
    stalled = stalled_state and state_streak >= stall_after_checks
    reason = (
        f"State {state!r} repeated for {state_streak} checks with no active dialog."
        if stalled
        else "No repeated busy/unknown stall threshold reached."
    )
    return {
        "stalled": stalled,
        "state": state,
        "state_streak": state_streak,
        "stall_after_checks": stall_after_checks,
        "active_dialog_count": active_dialog_count,
        "hung_window_count": len(hung_windows),
        "hung_windows": hung_windows,
        "recommendation": (
            "Capture evidence, stop automation, and ask the human before retrying UI actions."
            if stalled
            else "Continue observing."
        ),
        "reason": reason,
    }


def _capture_supervision_recovery_snapshot(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    bridge_result_limit: int,
) -> dict:
    try:
        return capture_recovery_snapshot(
            journal,
            observer,
            bridge,
            max_depth=2,
            bridge_result_limit=bridge_result_limit,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "reason": "Supervision detected a stall but recovery snapshot capture failed.",
        }
