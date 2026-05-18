"""Guarded model-open choreography for Revit startup and prompt handling."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .bridge import RevitBridgeClient
from .constants import DRAFT_LABEL
from .dialog_workflows import plan_dialog_response
from .journal import TaskJournal, utc_now
from .operations import open_model
from .readiness import wait_model_ready
from .safety import classify_action, validate_output_path
from .windows import RevitWindowObserver


MODEL_OPEN_PROMPT_CLASSES = [
    "unsigned-addin",
    "unsigned-addin-unknown",
    "pyrevit-loader-error",
    "transmitted-model",
    "unresolved-references",
    "missing-links",
    "upgrade-model",
    "detach-worksets",
    "open-worksets",
    "worksharing-central",
    "reload-links",
    "save-changes",
]


def run_model_open_choreography(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    model_path: Path,
    revit_version: str = "",
    revit_exe: str = "",
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    detach: bool = False,
    allow_upgrade: bool = False,
    worksets: str | None = None,
    execute_open: bool = False,
    approval_token: str | None = None,
    allow_model_outside_safe_root: bool = False,
    timeout: float = 120.0,
    poll: float = 2.0,
    max_prompt_checks: int = 12,
    open_model_func=None,
    wait_ready_func=None,
) -> dict:
    """Plan or run the safe portions of opening a copied local model."""

    started_at = utc_now()
    opener = open_model_func or open_model
    ready_waiter = wait_ready_func or wait_model_ready
    model_path = Path(model_path)
    status_before = _safe_status(observer)
    dialogs_before = _safe_dialogs(observer)
    prompt_events: list[dict] = []
    readiness_checks: list[dict] = []
    output_files: list[str] = []
    open_result: dict | None = None
    status = "planned_open"
    reason = "Open-model dry-run completed; no Revit process or UI prompt was changed."

    if dialogs_before:
        prompt_events.append(_prompt_event(dialogs_before, source="pre_open_dialog", index=0))
        status = "blocked_existing_prompt"
        reason = "A visible Revit prompt already blocks model-open choreography."
    else:
        try:
            open_result = opener(
                model_path,
                journal,
                revit_version=revit_version or None,
                revit_exe=revit_exe or None,
                detach=detach,
                allow_upgrade=allow_upgrade,
                worksets=worksets,
                dry_run=not execute_open,
                approval_token=approval_token,
                allow_outside_safe_root=allow_model_outside_safe_root,
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            open_result = {
                "success": False,
                "dry_run": not execute_open,
                "error": f"{type(exc).__name__}: {exc}",
            }
        if not open_result.get("success"):
            status = "open_preflight_failed" if not execute_open else "open_launch_failed"
            reason = open_result.get("error") or "open-model did not succeed."
        elif not execute_open:
            status = "planned_open"
        else:
            status, reason = _observe_after_launch(
                journal,
                observer,
                bridge,
                ready_waiter,
                prompt_events,
                readiness_checks,
                output_files,
                timeout=timeout,
                poll=poll,
                max_prompt_checks=max_prompt_checks,
                expected_title_contains=expected_title_contains,
                expected_path_contains=expected_path_contains or str(model_path),
                expected_revit_version=revit_version,
            )

    coverage = _prompt_coverage(prompt_events)
    result = {
        "success": status in {"planned_open", "model_ready", "stopped_on_prompt", "blocked_existing_prompt"},
        "read_only": not execute_open,
        "planned_only": not execute_open,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-model-open-choreography/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "reason": reason,
        "model_path": str(model_path),
        "revit_version": revit_version,
        "expectations": {
            "expected_title_contains": expected_title_contains,
            "expected_path_contains": expected_path_contains,
            "expected_revit_version": revit_version,
            "detach": detach,
            "allow_upgrade": allow_upgrade,
            "worksets": worksets,
            "execute_open": execute_open,
        },
        "status_before": status_before,
        "dialogs_before": dialogs_before,
        "open_model_result": _without_approval_tokens(open_result),
        "prompt_events": _without_approval_tokens(prompt_events),
        "readiness_checks": readiness_checks,
        "prompt_coverage": coverage,
        "safety_summary": {
            "open_executed": bool(execute_open and open_result and open_result.get("success")),
            "prompt_button_clicked": False,
            "model_write_performed": False,
            "save_sync_publish_performed": False,
            "stopped_at_approval_gate": status in {"stopped_on_prompt", "blocked_existing_prompt"},
        },
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "model_open_choreography.json"
    md_path = journal.run_dir / "model_open_choreography.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = _dedupe([*output_files, str(output), str(md_path)])
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _model_open_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-model-open-choreography",
            "requested_action": {
                "model_path": str(model_path),
                "revit_version": revit_version,
                "execute_open": execute_open,
            },
            "risk_classification": classify_action(
                "agent-model-open-choreography",
                {"execute_open": execute_open, "model_path": str(model_path), "revit_version": revit_version},
            ).to_dict(),
            "approval_status": {
                "allowed": True,
                "reason": "Wrapper performed only open-model dry-run or delegated launch authorization to open-model.",
            },
            "result": {
                "status": status,
                "success": sanitized["success"],
                "prompt_event_count": len(prompt_events),
                "goal_complete": False,
            },
            "output_files": sanitized["output_files"],
        }
    )
    return sanitized


def _observe_after_launch(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    ready_waiter,
    prompt_events: list[dict],
    readiness_checks: list[dict],
    output_files: list[str],
    *,
    timeout: float,
    poll: float,
    max_prompt_checks: int,
    expected_title_contains: str,
    expected_path_contains: str,
    expected_revit_version: str,
) -> tuple[str, str]:
    deadline = time.monotonic() + max(0.0, timeout)
    checks = 0
    while checks < max(1, max_prompt_checks):
        dialogs = _safe_dialogs(observer)
        if dialogs:
            prompt_events.append(_prompt_event(dialogs, source="post_launch_dialog", index=checks))
            return "stopped_on_prompt", "A model-open/startup dialog is visible; no prompt action was executed."
        readiness = ready_waiter(
            journal,
            observer,
            bridge,
            timeout=0,
            poll=1,
            expected_title_contains=expected_title_contains,
            expected_path_contains=expected_path_contains,
            expected_revit_version=expected_revit_version,
            require_bridge=False,
            stop_on_modal=True,
        )
        readiness_checks.append(readiness)
        if readiness.get("path"):
            output_files.append(str(readiness["path"]))
        if readiness.get("ready"):
            return "model_ready", "Opened model reached an idle, non-modal readiness state."
        checks += 1
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.1, poll))
    return "open_wait_timeout", "Timed out waiting for model readiness or a visible prompt."


def _safe_status(observer: RevitWindowObserver) -> dict:
    try:
        status = observer.status()
    except Exception as exc:
        return {"state": "unknown", "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"state": "unknown", "raw_status": status}


def _safe_dialogs(observer: RevitWindowObserver) -> list[dict]:
    try:
        listing = observer.list_dialogs()
    except Exception as exc:
        return [{"title": "Dialog observation failed", "dialog_text": f"{type(exc).__name__}: {exc}", "buttons": []}]
    return [dialog for dialog in (listing.get("dialogs") or []) if isinstance(dialog, dict)] if isinstance(listing, dict) else []


def _prompt_event(dialogs: list[dict], *, source: str, index: int) -> dict:
    planned = []
    for dialog_index, dialog in enumerate(dialogs):
        plan = plan_dialog_response(
            title=str(dialog.get("title") or ""),
            text=str(dialog.get("dialog_text") or ""),
            buttons=[str(button) for button in (dialog.get("buttons") or [])],
        )
        planned.append(
            {
                "dialog_index": dialog_index,
                "dialog": {
                    "hwnd": dialog.get("hwnd"),
                    "title": dialog.get("title") or "",
                    "dialog_text": dialog.get("dialog_text") or "",
                    "buttons": dialog.get("buttons") or [],
                    "classification": dialog.get("classification"),
                },
                "plan": plan,
                "requires_human": plan.get("requires_human", True),
                "known_dialog_id": plan.get("known_dialog_id"),
            }
        )
    return {
        "index": index,
        "source": source,
        "captured_at": utc_now(),
        "dialog_count": len(dialogs),
        "plans": planned,
        "recommended_next_command": "plan-current-dialog-response",
        "executed": False,
    }


def _prompt_coverage(prompt_events: list[dict]) -> list[dict]:
    observed = {
        str(plan.get("known_dialog_id") or "")
        for event in prompt_events
        for plan in event.get("plans", [])
        if plan.get("known_dialog_id")
    }
    return [
        {
            "prompt_class": prompt_class,
            "observed_in_this_run": prompt_class in observed,
            "covered_by_classifier": True,
            "requires_approval_or_human_review": True,
        }
        for prompt_class in MODEL_OPEN_PROMPT_CLASSES
    ]


def _model_open_markdown(result: dict) -> str:
    lines = [
        "# Revit Model-Open Choreography",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Prompt Events",
        "",
    ]
    for event in result.get("prompt_events", []):
        ids = [
            str(plan.get("known_dialog_id") or "unknown")
            for plan in event.get("plans", [])
        ]
        lines.append(f"- `{event.get('source')}`: {', '.join(ids) or 'none'}")
    if not result.get("prompt_events"):
        lines.append("- None observed.")
    lines.extend(["", "## Safety", ""])
    for key, value in result.get("safety_summary", {}).items():
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


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _without_approval_tokens(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            if str(key).lower() == "approval_token" and child:
                sanitized[key] = "<withheld; regenerate from fresh dry run>"
            else:
                sanitized[key] = _without_approval_tokens(child)
        return sanitized
    if isinstance(value, list):
        return [_without_approval_tokens(child) for child in value]
    if isinstance(value, str):
        redacted = re.sub(r"\bAPPROVE:[A-Za-z0-9_.:-]+\b", "<withheld approval token>", value)
        return re.sub(r"\bI approve\b", "<withheld approval phrase>", redacted, flags=re.IGNORECASE)
    return value
