"""Natural-language Revit task runner built on the guarded operator substrate."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .agent_session import plan_agent_session
from .bridge import RevitBridgeClient
from .constants import DRAFT_LABEL
from .dialog_workflows import plan_current_dialog_response
from .journal import TaskJournal, utc_now
from .readiness import wait_model_ready
from .recovery import capture_recovery_snapshot
from .safety import (
    ALLOW,
    APPROVAL_REQUIRED,
    BLOCK,
    HIGH,
    LOW,
    classify_action,
    validate_output_path,
)
from .windows import RevitWindowObserver
from .workflows import run_readonly_qa_workflow


SUPPORTED_QA_PATTERNS = {
    "qa": r"\bqa\b|\bquality\b|\bqc\b",
    "inspect": r"\binspect\b|\bcheck\b|\breview\b|\banalyze\b",
    "report": r"\breport\b|\bsummary\b|\bfindings\b",
    "metadata": r"\bmetadata\b|\bmodel state\b|\bmodel data\b",
    "sheets": r"\bsheets?\b|\bdrawings?\b|\bviews?\b",
    "warnings": r"\bwarnings?\b|\bissues?\b",
    "links": r"\blinks?\b|\bimports?\b",
    "grids": r"\bgrids?\b|\blevels?\b",
    "families": r"\bfamil(?:y|ies)\b|\btypes?\b|\btitleblocks?\b",
}

BLOCKED_INTENT_PATTERNS = {
    "save": r"\bsave\b|\bsave as\b",
    "sync": r"\bsync\b|\bsynchronize\b|\bsynchroni[sz]e with central\b",
    "publish": r"\bpublish\b",
    "overwrite": r"\boverwrite\b",
    "delete": r"\bdelete\b|\berase\b|\bremove model elements?\b",
    "production-write": r"\blucidlink\b|\bautodesk docs\b|\bcentral model\b|\bcloud\b",
    "model-modification": (
        r"\bmodify\b|\bchange\b|\bupdate parameters?\b|\bplace\b|\bcreate views?\b|"
        r"\bcreate sheets?\b|\bmove\b|\bcopy elements?\b"
    ),
}

APPROVAL_INTENT_PATTERNS = {
    "open-model": r"\bopen\b.*\bmodel\b",
    "upgrade": r"\bupgrade\b",
    "detach": r"\bdetach\b",
    "worksets": r"\bworksets?\b|\bopen worksets?\b|\bpreserve worksets?\b|\bdiscard worksets?\b",
    "reload-links": r"\breload\b.*\blinks?\b|\brepath\b.*\blinks?\b|\bmanage links\b",
    "close-model": r"\bclose\b.*\bmodel\b",
    "deliverable-export": r"\bexport\b.*\b(pdf|dwg|sheets?|prints?)\b|\bprint\b",
    "ui-dialog-editing": r"\bvisibility/graphics\b|\bview templates?\b|\bfamily load\b|\btype catalog\b",
    "manual-ui": r"\bclick\b|\bmouse\b|\bribbon\b|\bcontext menu\b",
}


def plan_agent_task(
    task_text: str,
    *,
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    sheet_number: str = "",
) -> dict:
    """Classify a plain-English Revit task and create a conservative plan."""

    task = " ".join(str(task_text or "").split())
    normalized = task.lower()
    blocked = _pattern_hits(normalized, BLOCKED_INTENT_PATTERNS)
    approvals = _pattern_hits(normalized, APPROVAL_INTENT_PATTERNS)
    supported = _pattern_hits(normalized, SUPPORTED_QA_PATTERNS)

    if not task:
        decision = {
            "risk": HIGH,
            "decision": APPROVAL_REQUIRED,
            "status": "needs_clarification",
            "reason": "No Revit task text was supplied.",
        }
    elif blocked:
        decision = {
            "risk": "blocked",
            "decision": BLOCK,
            "status": "blocked",
            "reason": "The task asks for blocked production-write or model-changing behavior.",
        }
    elif approvals:
        decision = {
            "risk": HIGH,
            "decision": APPROVAL_REQUIRED,
            "status": "needs_human_approval",
            "reason": "The task includes Revit operations that require human approval before execution.",
        }
    elif not supported:
        decision = {
            "risk": HIGH,
            "decision": APPROVAL_REQUIRED,
            "status": "needs_clarification",
            "reason": "The task is outside the current read-only QA agent scope.",
        }
    else:
        decision = {
            "risk": LOW,
            "decision": ALLOW,
            "status": "ready",
            "reason": "The task fits the supported read-only Revit QA scope.",
        }

    steps = [
        {
            "id": "observe-current-state",
            "command": "status",
            "purpose": "Attach to the current Revit session and detect dialogs before acting.",
            "mode": "read_only",
        },
        {
            "id": "stop-on-dialog",
            "command": "plan-current-dialog-response",
            "purpose": "If Revit is asking a question, classify it and stop for human approval.",
            "mode": "read_only",
        },
        {
            "id": "verify-model-ready",
            "command": "wait-model-ready",
            "purpose": "Verify idle Revit, no modal dialogs, active document, and expected version/path.",
            "mode": "read_only",
        },
        {
            "id": "run-readonly-qa",
            "command": "qa-workflow",
            "purpose": "Queue read-only bridge operations, export metadata, capture UI evidence, and draft report.",
            "mode": "read_only",
        },
        {
            "id": "write-agent-report",
            "command": "agent-task-report",
            "purpose": "Summarize plan, actions, blockers, outputs, and final state.",
            "mode": "sandbox_write",
        },
    ]

    return {
        "success": True,
        "task_text": task,
        "task_type": "read_only_qa" if decision["status"] == "ready" else "unapproved_or_unsupported",
        "decision": decision,
        "supported_intents": supported,
        "approval_required_intents": approvals,
        "blocked_intents": blocked,
        "expectations": {
            "expected_revit_version": expected_revit_version,
            "expected_title_contains": expected_title_contains,
            "expected_path_contains": expected_path_contains,
            "sheet_number": sheet_number,
        },
        "steps": steps,
        "safety_rules": [
            "No save, sync, publish, overwrite, central/cloud/LucidLink write, or model modification.",
            "Stop before risky or unknown dialogs.",
            "Write outputs only inside the configured sandbox.",
            f"Label engineering output: {DRAFT_LABEL}",
        ],
    }


def run_agent_task(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    task_text: str,
    timeout: float = 120.0,
    poll: float = 1.0,
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    sheet_number: str = "",
    capture_screenshot: bool = True,
    capture_ui_tree: bool = True,
    plan_only: bool = False,
) -> dict:
    """Run one supported natural-language Revit task with fail-closed gates."""

    started_at = utc_now()
    output_files: list[str] = []
    plan = plan_agent_task(
        task_text,
        expected_revit_version=expected_revit_version,
        expected_title_contains=expected_title_contains,
        expected_path_contains=expected_path_contains,
        sheet_number=sheet_number,
    )
    plan_paths = _write_plan(journal, plan)
    output_files.extend(plan_paths)

    if plan_only:
        result = _final_result(
            journal,
            started_at=started_at,
            status="planned",
            task_complete=False,
            plan=plan,
            output_files=output_files,
            reason="Plan-only mode did not execute Revit operations.",
        )
        _log_agent_task(journal, result)
        return result

    decision = plan["decision"]
    if decision["decision"] != ALLOW:
        session_plan = plan_agent_session(
            journal,
            objective=task_text,
            expected_revit_version=expected_revit_version,
            expected_title_contains=expected_title_contains,
            parameters={"sheet_number": sheet_number} if sheet_number else {},
        )
        output_files.extend(str(path) for path in session_plan.get("output_files") or [])
        packet_paths = _write_human_packet(
            journal,
            plan,
            reason=decision["reason"],
            current_state=None,
            dialog_plan=None,
        )
        output_files.extend(packet_paths)
        result = _final_result(
            journal,
            started_at=started_at,
            status=decision["status"],
            task_complete=False,
            plan=plan,
            output_files=output_files,
            reason=decision["reason"],
            session_plan=session_plan,
        )
        _log_agent_task(journal, result)
        return result

    initial_status = observer.status()
    if initial_status.get("active_dialogs") or initial_status.get("state") == "modal":
        dialog_plan = plan_current_dialog_response(journal, observer, use_ocr=True)
        packet_paths = _write_human_packet(
            journal,
            plan,
            reason="Revit has an active dialog; the agent stopped before acting.",
            current_state=initial_status,
            dialog_plan=dialog_plan,
        )
        output_files.extend(packet_paths)
        result = _final_result(
            journal,
            started_at=started_at,
            status="needs_human_approval",
            task_complete=False,
            plan=plan,
            output_files=output_files,
            reason="Active dialog requires human approval.",
            initial_status=initial_status,
            dialog_plan=dialog_plan,
        )
        _log_agent_task(journal, result)
        return result

    readiness = wait_model_ready(
        journal,
        observer,
        bridge,
        timeout=timeout,
        poll=poll,
        expected_title_contains=expected_title_contains,
        expected_path_contains=expected_path_contains,
        expected_revit_version=expected_revit_version,
    )
    if readiness.get("path"):
        output_files.append(str(readiness["path"]))
    if not readiness.get("ready"):
        recovery = capture_recovery_snapshot(journal, observer)
        if recovery.get("output_files"):
            output_files.extend(str(path) for path in recovery["output_files"])
        result = _final_result(
            journal,
            started_at=started_at,
            status="blocked_not_ready",
            task_complete=False,
            plan=plan,
            output_files=output_files,
            reason="Revit/model readiness check did not pass.",
            initial_status=initial_status,
            readiness=readiness,
            recovery=recovery,
        )
        _log_agent_task(journal, result)
        return result

    workflow = run_readonly_qa_workflow(
        journal,
        observer,
        bridge,
        timeout=timeout,
        poll=poll,
        capture_screenshot=capture_screenshot,
        capture_ui_tree=capture_ui_tree,
    )
    output_files.extend(str(path) for path in workflow.get("output_files") or [])
    final_status = observer.status()
    task_complete = bool(
        workflow.get("success")
        and final_status.get("state") == "idle"
        and not final_status.get("active_dialogs")
    )
    status = "completed" if task_complete else "incomplete"
    reason = (
        "Natural-language read-only QA task completed."
        if task_complete
        else "QA workflow ran but the final completion gate did not pass."
    )
    result = _final_result(
        journal,
        started_at=started_at,
        status=status,
        task_complete=task_complete,
        plan=plan,
        output_files=output_files,
        reason=reason,
        initial_status=initial_status,
        readiness=readiness,
        workflow=workflow,
        final_status=final_status,
    )
    _log_agent_task(journal, result)
    return result


def _pattern_hits(text: str, patterns: dict[str, str]) -> list[str]:
    hits = []
    for name, pattern in patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(name)
    return hits


def _write_plan(journal: TaskJournal, plan: dict) -> list[str]:
    json_path = journal.run_dir / "agent_task_plan.json"
    md_path = journal.run_dir / "agent_task_plan.md"
    _write_json_sandboxed(json_path, journal.sandbox, plan)
    _write_text_sandboxed(md_path, journal.sandbox, _plan_markdown(plan))
    return [str(json_path), str(md_path)]


def _write_human_packet(
    journal: TaskJournal,
    plan: dict,
    *,
    reason: str,
    current_state: dict | None,
    dialog_plan: dict | None,
) -> list[str]:
    packet = {
        "success": True,
        "created_at_utc": utc_now(),
        "label": DRAFT_LABEL,
        "status": "needs_human_approval",
        "reason": reason,
        "task_text": plan.get("task_text"),
        "decision": plan.get("decision"),
        "blocked_intents": plan.get("blocked_intents", []),
        "approval_required_intents": plan.get("approval_required_intents", []),
        "current_state": _state_summary(current_state),
        "dialog_plan": dialog_plan,
        "allowed_agent_next_steps": ["observe", "screenshot", "ui-tree", "plan-current-dialog-response"],
        "blocked_without_approval": [
            "save",
            "sync",
            "publish",
            "reload links",
            "modify model contents",
            "click ambiguous dialog buttons",
        ],
    }
    json_path = journal.run_dir / "agent_task_human_packet.json"
    md_path = journal.run_dir / "agent_task_human_packet.md"
    _write_json_sandboxed(json_path, journal.sandbox, packet)
    _write_text_sandboxed(md_path, journal.sandbox, _human_packet_markdown(packet))
    return [str(json_path), str(md_path)]


def _final_result(
    journal: TaskJournal,
    *,
    started_at: str,
    status: str,
    task_complete: bool,
    plan: dict,
    output_files: list[str],
    reason: str,
    **extra,
) -> dict:
    result = {
        "success": True,
        "read_only": True,
        "label": DRAFT_LABEL,
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "task_complete": bool(task_complete),
        "may_tell_user_done": bool(task_complete),
        "reason": reason,
        "task_text": plan.get("task_text"),
        "task_type": plan.get("task_type"),
        "plan": plan,
        "output_files": _dedupe(output_files),
        "safety_summary": {
            "model_write_performed": False,
            "save_sync_publish_performed": False,
            "production_write_performed": False,
            "approval_required_actions_executed": False,
        },
        "journal": journal.describe(),
    }
    result.update(extra)
    result["path"] = str(journal.run_dir / "agent_task_result.json")
    result["output_files"] = _dedupe(
        [*result["output_files"], str(journal.run_dir / "agent_task_report.md"), result["path"]]
    )
    _write_report(journal, result)
    _write_json_sandboxed(Path(result["path"]), journal.sandbox, result)
    return result


def _write_report(journal: TaskJournal, result: dict) -> list[str]:
    md_path = journal.run_dir / "agent_task_report.md"
    _write_text_sandboxed(md_path, journal.sandbox, _report_markdown(result))
    return [str(md_path)]


def _log_agent_task(journal: TaskJournal, result: dict) -> None:
    journal.write_entry(
        {
            "command": "agent-task",
            "requested_action": {
                "task_text": result.get("task_text"),
                "task_type": result.get("task_type"),
            },
            "risk_classification": classify_action("agent-task", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only natural-language task runner."},
            "result": {
                "status": result.get("status"),
                "success": result.get("success"),
                "task_complete": result.get("task_complete"),
                "may_tell_user_done": result.get("may_tell_user_done"),
            },
            "output_files": result.get("output_files", []),
        }
    )


def _write_json_sandboxed(path: Path, sandbox: Path, payload: dict) -> None:
    _validate(path, sandbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text_sandboxed(path: Path, sandbox: Path, text: str) -> None:
    _validate(path, sandbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _validate(path: Path, sandbox: Path) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)


def _plan_markdown(plan: dict) -> str:
    lines = [
        "# Revit Agent Task Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Task: {plan.get('task_text') or ''}",
        f"Status: `{plan['decision']['status']}`",
        f"Decision: `{plan['decision']['decision']}`",
        f"Reason: {plan['decision']['reason']}",
        "",
        "## Steps",
        "",
    ]
    for step in plan.get("steps", []):
        lines.append(f"- `{step['id']}` via `{step['command']}`: {step['purpose']}")
    lines.extend(["", "## Safety", ""])
    lines.extend(f"- {rule}" for rule in plan.get("safety_rules", []))
    return "\n".join(lines) + "\n"


def _human_packet_markdown(packet: dict) -> str:
    lines = [
        "# Revit Agent Human Approval Packet",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{packet['status']}`",
        f"Reason: {packet['reason']}",
        f"Task: {packet.get('task_text') or ''}",
        "",
        "## Blocked Without Approval",
        "",
    ]
    lines.extend(f"- {item}" for item in packet["blocked_without_approval"])
    return "\n".join(lines) + "\n"


def _report_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Task Report",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result['status']}`",
        f"Task complete: `{str(result['task_complete']).lower()}`",
        f"Reason: {result['reason']}",
        f"Task: {result.get('task_text') or ''}",
        "",
        "## Outputs",
        "",
    ]
    outputs = result.get("output_files") or []
    if outputs:
        lines.extend(f"- {path}" for path in outputs)
    else:
        lines.append("- None.")
    workflow = result.get("workflow") if isinstance(result.get("workflow"), dict) else {}
    findings = workflow.get("findings") or []
    lines.extend(["", "## Findings", ""])
    if findings:
        lines.extend(f"- {finding}" for finding in findings)
    else:
        lines.append("- No QA findings were produced by the automated workflow.")
    lines.extend(["", "## Safety", ""])
    for key, value in result.get("safety_summary", {}).items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines) + "\n"


def _state_summary(state: dict | None) -> dict | None:
    if not isinstance(state, dict):
        return None
    return {
        "state": state.get("state"),
        "active_dialog_count": len(state.get("active_dialogs") or []),
        "main_window": state.get("main_window"),
        "active_document": state.get("active_document"),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
