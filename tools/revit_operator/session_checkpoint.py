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
