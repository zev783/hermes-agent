"""Helpers shared by the tests/tools/test_revit_operator_*.py files.

North-star artifact writers for the approval, handoff, completion-gate and
stable-scan tests, and the per-process bridge session files for the
operation, targeting, workflow and agent-session tests.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import tools.revit_operator.bridge as bridge_module
import tools.revit_operator.north_star as north_star
from tools.revit_operator.safety import classify_action


def _test_preflight_freshness(*, generated_offset_seconds=0, ttl_seconds=900):
    generated_at = datetime.now(timezone.utc).timestamp() + generated_offset_seconds
    expires_at = generated_at + ttl_seconds
    return {
        "generated_at_utc": datetime.fromtimestamp(generated_at, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "generated_at_unix": generated_at,
        "ttl_seconds": ttl_seconds,
        "expires_at_utc": datetime.fromtimestamp(expires_at, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "expires_at_unix": expires_at,
        "freshness_rule": "test freshness metadata",
    }


def _write_watch_artifact(tmp_path, payload):
    run_dir = tmp_path / "revit_operator_runs" / "watch"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "north_star_watch.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_resume_artifact(tmp_path, payload):
    run_dir = tmp_path / "revit_operator_runs" / "resume"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "north_star_resume_check.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_stable_scan_current(tmp_path, payload):
    path = tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_unblock_readiness_current(tmp_path, payload):
    path = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    payload = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "may_execute_from_this_result": False,
        **payload,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    required = [
        "completion_allowed",
        "may_call_update_goal",
        "audit_completion_authorized",
        "may_execute_from_this_result",
    ]
    if all(key in payload for key in required):
        markdown = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
        markdown.write_text(
            "\n".join(
                f"- {key}: `{str(payload.get(key)).lower()}`" for key in required
            ),
            encoding="utf-8",
        )
    return path


def _read_only_refresh_fields():
    command = [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
    ]
    return {
        "safe_supervision_refresh_command": command,
        "safe_supervision_refresh_powershell": north_star._powershell_command(command),
        "safe_supervision_refresh_read_only": True,
    }


def _write_clean_restart_checklist_for_freshness(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
                "",
                "## Add-In Startup Prompt Preflight",
                "addin_security_status: `verified`",
                "expected_local_hermes_addin: `True`",
                "needs_trust_addin: `False`",
                "can_consider_always_load_after_human_approval: `True`",
                "allowed_dialog_button_after_human_approval: `Always Load`",
                "blocked_dialog_buttons: `Load Once`, `Do Not Load`",
                "signature_status: `Valid`",
                "signer_subject: `CN=Hermes Revit Operator Local Code Signing`",
                "Hermes must not click it from this checklist",
                "require an exact approval token before any `Always Load` click",
                "",
                "`north-star-completion-gate`",
                "`north-star-resume-check.completion_gate`",
                "`completion_allowed: true`",
                "`may_call_update_goal: true`",
                "`audit_completion_authorized: true`",
                "Status and audit summaries are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )


def _write_restart_freshness_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    _write_clean_restart_checklist_for_freshness(stable_checklist)
    source_dir = tmp_path / "revit_operator_runs" / "bridge-plan-freshness"
    source_dir.mkdir(parents=True)
    source_checklist = source_dir / "bridge_restart_no_save_checklist.md"
    _write_clean_restart_checklist_for_freshness(source_checklist)
    source_plan = source_dir / "bridge_restart_validation_plan.json"
    source_plan.write_text(
        json.dumps(
            {
                "success": True,
                "status": "human_restart_required",
                "human_handoff_required": True,
                "restart_or_reload_required": True,
                "no_save_checklist_path": str(source_checklist),
                "addin_security_preflight": {
                    "status": "verified",
                    "expected_local_hermes_addin": True,
                    "needs_trust_addin": False,
                    "can_consider_always_load_after_human_approval": True,
                    "allowed_dialog_button": "Always Load",
                    "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
                    "signature": {
                        "status": "Valid",
                        "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(source_checklist),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
            ]
        ),
        encoding="utf-8",
    )
    os.utime(stable_checklist, (1_000, 1_000))
    os.utime(source_checklist, (2_000, 2_000))
    os.utime(source_plan, (2_001, 2_001))
    return stable_checklist, source_checklist, source_plan


def _write_bridge_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _current_bridge_addin(pid: int, *, started: str = "2026-10-02T12:00:00.1234567Z") -> dict:
    return {
        "bridge_protocol_version": "0.2",
        "source_capability_stamp": "continuous-idling-status-file-retry-v2",
        "supports_continuous_idling": True,
        "uses_idling_set_raise_without_delay": True,
        "process_id": pid,
        "process_start_utc": started,
        "session_id": f"session-{pid}",
    }


# When _current_bridge_addin says its process started, in the add-in's format and as the live process reports it.
_SESSION_STARTED = "2026-10-02T12:00:00.1234567Z"
_SESSION_STARTED_AT = datetime(2026, 10, 2, 12, 0, 0, 123456, tzinfo=timezone.utc)


def _start_bridge_session(
    sandbox: Path,
    pid: int,
    *,
    title: str = "Target Model",
    honors_targets: bool = True,
    status: str = "started",
    started: str = _SESSION_STARTED,
) -> None:
    """Write the per-process status files that a running add-in keeps for one Revit process."""
    addin = _current_bridge_addin(pid, started=started)
    if honors_targets:
        addin["supports_command_targets"] = True
    bridge_dir = sandbox / "bridge"
    _write_bridge_payload(bridge_dir / f"addin_status.{pid}.json", {"status": status, "addin": addin})
    _write_bridge_payload(bridge_dir / f"addin_heartbeat.{pid}.json", {"status": "idling", "addin": addin})
    _write_bridge_payload(
        bridge_dir / f"active_document.{pid}.json",
        {
            "available": True,
            "status": "connected",
            "document": {"title": title, "path": f"C:/models/{title}.rvt"},
            "addin": addin,
        },
    )


def _live_revit_processes(monkeypatch, *pids: int) -> None:
    """Treat these process ids as running, started when _current_bridge_addin says, and every other id as exited."""
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: _SESSION_STARTED_AT if pid in pids else None)


def _targeted_token(payload: dict, pid: int, started: str = _SESSION_STARTED) -> str:
    target = {"process_id": pid, "process_start_utc": started}
    return classify_action("request-operation", {**payload, "target": target}).approval_token
