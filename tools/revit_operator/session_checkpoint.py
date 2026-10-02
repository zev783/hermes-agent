"""Read-only resumability checkpoints for long-running Revit agent sessions."""

from __future__ import annotations

import json
from pathlib import Path

from .bridge import RevitBridgeClient
from .constants import DRAFT_LABEL
from .journal import TaskJournal, utc_now
from .safety import classify_action, validate_output_path
from .windows import RevitWindowObserver


def write_agent_session_checkpoint(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    objective: str = "",
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    bridge_result_limit: int = 10,
) -> dict:
    """Write a compact checkpoint that a later run can resume from safely."""

    status = _safe_status(observer)
    dialogs = _safe_dialogs(observer)
    bridge_status = _safe_bridge_status(bridge)
    active_document = _safe_active_document(bridge)
    recent_bridge_results = _safe_bridge_results(bridge, limit=bridge_result_limit)
    blockers = _checkpoint_blockers(status, dialogs, bridge_status, active_document)
    resume_commands = _resume_commands(
        objective=objective,
        status=status,
        dialogs=dialogs,
        expected_revit_version=expected_revit_version,
        expected_title_contains=expected_title_contains,
        expected_path_contains=expected_path_contains,
    )
    result = {
        "success": True,
        "read_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-checkpoint/v1",
        "created_at": utc_now(),
        "objective": objective,
        "status": "blocked" if blockers else "resume_ready",
        "state": status.get("state"),
        "status_snapshot": status,
        "dialogs": dialogs,
        "bridge_status": bridge_status,
        "active_document": active_document,
        "recent_bridge_results": recent_bridge_results,
        "blockers": blockers,
        "resume_commands": resume_commands,
        "resume_safety": {
            "commands_are_read_only": True,
            "contains_execute_flag": False,
            "contains_approval_token": False,
            "resume_requires_fresh_observation": True,
        },
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_session_checkpoint.json"
    markdown = journal.run_dir / "agent_session_checkpoint.md"
    history = journal.run_dir / "agent_session_checkpoints.jsonl"
    result["path"] = str(output)
    result["markdown_path"] = str(markdown)
    result["history_path"] = str(history)
    result["output_files"] = [str(output), str(markdown), str(history)]
    _write_json(output, journal.sandbox, result)
    _write_text(markdown, journal.sandbox, _checkpoint_markdown(result))
    _append_jsonl(history, journal.sandbox, result)
    journal.write_entry(
        {
            "command": "agent-session-checkpoint",
            "requested_action": {"objective": objective},
            "risk_classification": classify_action("agent-session-checkpoint", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only checkpoint capture."},
            "result": {
                "status": result["status"],
                "blocker_count": len(blockers),
                "resume_command_count": len(resume_commands),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
        }
    )
    return result


def build_agent_session_resume_plan(
    journal: TaskJournal,
    *,
    checkpoint_path: Path | None = None,
    supervision_log_path: Path | None = None,
    resume_minutes: float = 30.0,
) -> dict:
    """Build a read-only resume plan from a checkpoint and optional supervision log."""

    checkpoint_path = checkpoint_path or _latest_checkpoint_path(journal.sandbox)
    if checkpoint_path is None:
        return {
            "success": False,
            "status": "needs_checkpoint",
            "reason": "No agent_session_checkpoint.json artifact was found under the sandbox.",
            "goal_complete": False,
            "may_call_update_goal": False,
            "journal": journal.describe(),
        }
    path_error = validate_output_path(checkpoint_path, journal.sandbox)
    if path_error:
        return {"success": False, "error": path_error, "goal_complete": False, "may_call_update_goal": False}
    if not checkpoint_path.exists():
        return {
            "success": False,
            "error": f"Checkpoint artifact not found: {checkpoint_path}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid checkpoint JSON: {exc}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    if not isinstance(checkpoint, dict):
        return {"success": False, "error": "Checkpoint artifact must contain a JSON object."}

    supervision = _load_optional_supervision_log(supervision_log_path, journal.sandbox)
    blockers = [blocker for blocker in checkpoint.get("blockers") or [] if isinstance(blocker, dict)]
    resume_sequence = _resume_sequence_from_checkpoint(
        checkpoint,
        blockers=blockers,
        resume_minutes=resume_minutes,
    )
    read_only_checks = [_resume_command_check(step) for step in resume_sequence]
    blocked = bool(blockers)
    status = "blocked" if blocked else "resume_ready"
    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-resume-plan/v1",
        "created_at": utc_now(),
        "status": status,
        "reason": _resume_reason(blockers, supervision),
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_status": checkpoint.get("status"),
        "checkpoint_created_at": checkpoint.get("created_at"),
        "objective": checkpoint.get("objective") or "",
        "state": checkpoint.get("state"),
        "blockers": blockers,
        "supervision": supervision,
        "resume_sequence": resume_sequence,
        "resume_command_checks": read_only_checks,
        "resume_safety": {
            "commands_are_read_only": all(check["read_only"] for check in read_only_checks),
            "contains_execute_flag": any(check["contains_execute_flag"] for check in read_only_checks),
            "contains_approval_token": any(check["contains_approval_token"] for check in read_only_checks),
            "requires_fresh_checkpoint_before_execution": True,
            "executes_revit_action": False,
        },
        "recommended_next_action": _recommended_resume_action(blockers),
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_session_resume_plan.json"
    markdown = journal.run_dir / "agent_session_resume_plan.md"
    result["path"] = str(output)
    result["markdown_path"] = str(markdown)
    result["output_files"] = [str(output), str(markdown)]
    _write_json(output, journal.sandbox, result)
    _write_text(markdown, journal.sandbox, _resume_plan_markdown(result))
    journal.write_entry(
        {
            "command": "agent-session-resume-plan",
            "requested_action": {"checkpoint_path": str(checkpoint_path)},
            "risk_classification": classify_action("agent-session-resume-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only resume planning."},
            "result": {
                "status": status,
                "blocker_count": len(blockers),
                "resume_step_count": len(resume_sequence),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
        }
    )
    return result


def _checkpoint_blockers(
    status: dict,
    dialogs: list[dict],
    bridge_status: dict,
    active_document: dict,
) -> list[dict]:
    blockers = []
    state = str(status.get("state") or "unknown")
    if not status.get("revit_running"):
        blockers.append({"id": "revit-not-running", "reason": "No running Revit process/window is observable."})
    if state in {"modal", "busy", "unknown", "unsupported"}:
        blockers.append({"id": f"revit-state-{state}", "reason": f"Revit observer state is {state}."})
    if dialogs:
        blockers.append({"id": "active-dialog", "reason": "Visible Revit dialog must be classified before resuming."})
    if not bridge_status.get("available"):
        blockers.append({"id": "bridge-unavailable", "reason": "In-process bridge status is not available."})
    if not active_document.get("available"):
        blockers.append({"id": "active-document-unavailable", "reason": "Active document payload is not available."})
    return blockers


def _resume_commands(
    *,
    objective: str,
    status: dict,
    dialogs: list[dict],
    expected_revit_version: str,
    expected_title_contains: str,
    expected_path_contains: str,
) -> list[dict]:
    commands = []
    if dialogs or status.get("state") == "modal":
        commands.append(
            {
                "id": "classify-current-dialog",
                "command": "plan-current-dialog-response",
                "reason": "A modal/prompt state must be classified before any resume action.",
            }
        )
    commands.append(
        {
            "id": "fresh-status",
            "command": "status",
            "reason": "Refresh the live UI/window state before resuming.",
        }
    )
    wait_parts = ["wait-model-ready", "--timeout", "0", "--no-require-bridge"]
    if expected_revit_version:
        wait_parts.extend(["--expected-revit-version", expected_revit_version])
    if expected_title_contains:
        wait_parts.extend(["--expected-title-contains", expected_title_contains])
    if expected_path_contains:
        wait_parts.extend(["--expected-path-contains", expected_path_contains])
    commands.append(
        {
            "id": "readiness-check",
            "command": _command(wait_parts),
            "reason": "Confirm idle/non-modal readiness with current expectations.",
        }
    )
    if objective:
        commands.append(
            {
                "id": "session-preflight",
                "command": _command(["agent-session-run", "--objective", objective, "--no-open-dry-run", "--bridge-refresh-timeout", "0"]),
                "reason": "Rerun safe session preflight before approval-gated work.",
            }
        )
    commands.append(
        {
            "id": "supervision-resume",
            "command": "supervise-session --resume --duration 300 --poll 5 --stop-on-modal",
            "reason": "Continue read-only supervision from existing log checkpoints.",
        }
    )
    return commands


def _safe_status(observer: RevitWindowObserver) -> dict:
    try:
        status = observer.status()
    except Exception as exc:
        return {"state": "unknown", "revit_running": False, "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"state": "unknown", "raw_status": status}


def _safe_dialogs(observer: RevitWindowObserver) -> list[dict]:
    try:
        listing = observer.list_dialogs()
    except Exception as exc:
        return [{"title": "Dialog observation failed", "dialog_text": f"{type(exc).__name__}: {exc}", "buttons": []}]
    return [dialog for dialog in (listing.get("dialogs") or []) if isinstance(dialog, dict)] if isinstance(listing, dict) else []


def _safe_bridge_status(bridge: RevitBridgeClient) -> dict:
    try:
        status = bridge.bridge_status()
    except Exception as exc:
        return {"available": False, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"available": False, "status": "invalid", "raw_status": status}


def _safe_active_document(bridge: RevitBridgeClient) -> dict:
    try:
        status = bridge.active_document_status()
    except Exception as exc:
        return {"available": False, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"available": False, "status": "invalid", "raw_status": status}


def _safe_bridge_results(bridge: RevitBridgeClient, *, limit: int) -> list[dict]:
    try:
        results = bridge.read_command_results()
    except Exception:
        return []
    if not isinstance(results, list):
        return []
    return results[-max(0, limit) :] if limit else []


def _latest_checkpoint_path(sandbox: Path) -> Path | None:
    runs_root = sandbox / "revit_operator_runs"
    if not runs_root.exists():
        return None
    candidates = sorted(
        runs_root.glob("*/agent_session_checkpoint.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_optional_supervision_log(path: Path | None, sandbox: Path) -> dict:
    if path is None:
        return {"provided": False}
    path_error = validate_output_path(path, sandbox)
    if path_error:
        return {"provided": True, "available": False, "error": path_error}
    if not path.exists():
        return {"provided": True, "available": False, "error": f"Supervision log not found: {path}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"provided": True, "available": False, "error": f"Invalid supervision log JSON: {exc}"}
    if not isinstance(data, dict):
        return {"provided": True, "available": False, "error": "Supervision log must contain a JSON object."}
    return {
        "provided": True,
        "available": True,
        "path": str(path),
        "checkpoint_status": data.get("checkpoint_status"),
        "stop_reason": data.get("stop_reason"),
        "check_count": data.get("check_count"),
        "final_state": data.get("final_state"),
        "final_active_dialog_count": data.get("final_active_dialog_count"),
        "stalled": bool((data.get("stall_analysis") or {}).get("stalled")),
        "resumed": bool(data.get("resumed")),
    }


def _resume_sequence_from_checkpoint(checkpoint: dict, *, blockers: list[dict], resume_minutes: float) -> list[dict]:
    if blockers:
        return _blocked_resume_sequence(blockers, checkpoint)
    sequence = []
    for command in checkpoint.get("resume_commands") or []:
        if not isinstance(command, dict):
            continue
        sequence.append(
            {
                "id": command.get("id") or f"resume-step-{len(sequence)}",
                "command": command.get("command") or "",
                "reason": command.get("reason") or "Checkpoint-provided safe resume command.",
                "requires_approval": False,
            }
        )
    if not any(step.get("id") == "checkpoint-after-resume" for step in sequence):
        checkpoint_command = ["agent-session-checkpoint"]
        if checkpoint.get("objective"):
            checkpoint_command.extend(["--objective", checkpoint.get("objective") or ""])
        sequence.append(
            {
                "id": "checkpoint-after-resume",
                "command": _command(checkpoint_command),
                "reason": "Write a fresh checkpoint after the resume preflight or supervision segment.",
                "requires_approval": False,
            }
        )
    if not any(step.get("id") == "timed-supervision-resume" for step in sequence):
        duration = str(int(max(1.0, resume_minutes) * 60))
        sequence.append(
            {
                "id": "timed-supervision-resume",
                "command": _command(["supervise-session", "--resume", "--duration", duration, "--poll", "30", "--stop-on-modal"]),
                "reason": "Resume read-only supervision for the requested planning interval.",
                "requires_approval": False,
            }
        )
    return sequence


def _blocked_resume_sequence(blockers: list[dict], checkpoint: dict) -> list[dict]:
    blocker_ids = {str(blocker.get("id") or "") for blocker in blockers}
    sequence = [
        {
            "id": "fresh-status",
            "command": "status",
            "reason": "Refresh live state before acting on checkpoint blockers.",
            "requires_approval": False,
        }
    ]
    if "active-dialog" in blocker_ids or any(blocker_id.startswith("revit-state-modal") for blocker_id in blocker_ids):
        sequence.append(
            {
                "id": "classify-current-dialog",
                "command": "plan-current-dialog-response",
                "reason": "Classify the visible prompt before any resume action.",
                "requires_approval": False,
            }
        )
        sequence.append(
            {
                "id": "model-open-prompt-approval-plan",
                "command": "agent-model-open-prompt-approval-plan --choreography <model_open_choreography.json>",
                "reason": "If the blocker is part of model open, convert the prompt event into approval material.",
                "requires_approval": False,
            }
        )
    if "bridge-unavailable" in blocker_ids or "active-document-unavailable" in blocker_ids:
        sequence.append(
            {
                "id": "bridge-readiness",
                "command": "bridge-readiness",
                "reason": "Verify the in-process bridge before resuming API-backed work.",
                "requires_approval": False,
            }
        )
    if "revit-not-running" in blocker_ids:
        sequence.append(
            {
                "id": "model-open-choreography",
                "command": "agent-model-open-choreography --model <copied-local-model>",
                "reason": "Revit must be opened or attached through guarded model-open choreography.",
                "requires_approval": True,
            }
        )
    checkpoint_command = ["agent-session-checkpoint"]
    if checkpoint.get("objective"):
        checkpoint_command.extend(["--objective", checkpoint.get("objective") or ""])
    sequence.append(
        {
            "id": "checkpoint-after-blocker-resolution",
            "command": _command(checkpoint_command),
            "reason": "After a human or approved step changes state, capture a fresh checkpoint before continuing.",
            "requires_approval": False,
        }
    )
    return sequence


def _resume_command_check(step: dict) -> dict:
    command = str(step.get("command") or "")
    contains_execute = "--execute" in command
    contains_token = "APPROVE:" in command or "--approval-token" in command
    return {
        "id": step.get("id"),
        "command": command,
        "contains_execute_flag": contains_execute,
        "contains_approval_token": contains_token,
        "read_only": not contains_execute and not contains_token,
    }


def _resume_reason(blockers: list[dict], supervision: dict) -> str:
    if blockers:
        return "Checkpoint has blockers; resolve them and write a fresh checkpoint before resuming."
    if supervision.get("available") and supervision.get("stop_reason") in {"modal_state_detected", "stalled_state_detected"}:
        return f"Checkpoint is resume-ready, but last supervision stopped for {supervision.get('stop_reason')}."
    return "Checkpoint is resume-ready; run read-only preflight and supervision before approval-gated work."


def _recommended_resume_action(blockers: list[dict]) -> str:
    blocker_ids = {str(blocker.get("id") or "") for blocker in blockers}
    if "active-dialog" in blocker_ids or any(blocker_id.startswith("revit-state-modal") for blocker_id in blocker_ids):
        return "classify_prompt"
    if "bridge-unavailable" in blocker_ids or "active-document-unavailable" in blocker_ids:
        return "restore_bridge_or_document_awareness"
    if "revit-not-running" in blocker_ids:
        return "open_or_attach_revit"
    if blockers:
        return "resolve_blockers"
    return "resume_readonly_preflight"


def _checkpoint_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Checkpoint",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"State: `{result.get('state')}`",
        "Goal complete: `false`",
        "",
        "## Blockers",
        "",
    ]
    for blocker in result.get("blockers", []):
        lines.append(f"- `{blocker.get('id')}`: {blocker.get('reason')}")
    if not result.get("blockers"):
        lines.append("- None.")
    lines.extend(["", "## Resume Commands", ""])
    for command in result.get("resume_commands", []):
        lines.append(f"- `{command.get('id')}`: {command.get('command')}")
    return "\n".join(lines) + "\n"


def _resume_plan_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Resume Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Recommended next action: `{result.get('recommended_next_action')}`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Blockers",
        "",
    ]
    for blocker in result.get("blockers", []):
        lines.append(f"- `{blocker.get('id')}`: {blocker.get('reason')}")
    if not result.get("blockers"):
        lines.append("- None.")
    lines.extend(["", "## Resume Sequence", ""])
    for step in result.get("resume_sequence", []):
        lines.append(f"- `{step.get('id')}`: {step.get('command')}")
    lines.extend(["", "## Safety", ""])
    for key, value in result.get("resume_safety", {}).items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, sandbox: Path, payload: dict) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, sandbox: Path, text: str) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, sandbox: Path, payload: dict) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _command(parts: list[str]) -> str:
    return " ".join(_quote(part) for part in parts if str(part) != "")


def _quote(value: object) -> str:
    text = str(value)
    if not text:
        return "''"
    if any(char.isspace() for char in text) or any(char in text for char in "{}\"'"):
        return "'" + text.replace("'", "''") + "'"
    return text
