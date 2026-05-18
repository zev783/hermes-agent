"""Guarded model-open choreography for Revit startup and prompt handling."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .actions import ActionRequest, SafeActionExecutor
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


def build_model_open_prompt_approval_plan(
    journal: TaskJournal,
    *,
    choreography_path: Path,
    limit: int = 10,
) -> dict:
    """Create redacted approval material for observed model-open prompt steps."""

    path_error = validate_output_path(choreography_path, journal.sandbox)
    if path_error:
        return {"success": False, "error": path_error, "goal_complete": False, "may_call_update_goal": False}
    if not choreography_path.exists():
        return {
            "success": False,
            "error": f"Model-open choreography artifact not found: {choreography_path}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    try:
        choreography = json.loads(choreography_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid model-open choreography JSON: {exc}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    if not isinstance(choreography, dict):
        return {"success": False, "error": "Model-open choreography artifact must be a JSON object."}

    approval_items: list[dict] = []
    private_items: list[dict] = []
    manual_items: list[dict] = []
    for event_index, event in enumerate(choreography.get("prompt_events") or []):
        if not isinstance(event, dict):
            continue
        for plan_index, prompt_plan in enumerate(event.get("plans") or []):
            if not isinstance(prompt_plan, dict):
                continue
            item = _model_open_prompt_approval_item(event_index, plan_index, prompt_plan)
            if item.get("private"):
                approval_items.append(_without_approval_tokens(item["public"]))
                private_items.append(item["private"])
            else:
                manual_items.append(_without_approval_tokens(item["public"]))
            if len(approval_items) + len(manual_items) >= max(0, limit):
                break
        if len(approval_items) + len(manual_items) >= max(0, limit):
            break

    private_material = {
        "label": DRAFT_LABEL,
        "created_at": utc_now(),
        "schema": "hermes-revit-model-open-prompt-approval-material/v1",
        "source_choreography_path": str(choreography_path),
        "source_choreography_status": choreography.get("status"),
        "approval_items": private_items,
        "warning": (
            "Private model-open prompt approval material. Use only while the same "
            "prompt is visible and after fresh dialog verification still matches."
        ),
    }
    public = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-model-open-prompt-approval-plan/v1",
        "created_at": utc_now(),
        "source_choreography_path": str(choreography_path),
        "source_choreography_status": choreography.get("status"),
        "approval_required_count": len(approval_items),
        "manual_or_blocked_count": len(manual_items),
        "approval_material_withheld_from_public": True,
        "approval_items": approval_items,
        "manual_or_blocked_items": manual_items,
        "private_material_contains_approval_tokens": bool(private_items),
        "goal_complete": False,
        "may_call_update_goal": False,
        "safety_note": (
            "This command creates prompt approval material only. It does not click, "
            "type, save, sync, publish, upgrade, detach, or modify Revit."
        ),
        "journal": journal.describe(),
    }
    public_path = journal.run_dir / "model_open_prompt_approval_plan.json"
    private_path = journal.run_dir / "model_open_prompt_approval_private_material.json"
    md_path = journal.run_dir / "model_open_prompt_approval_plan.md"
    public["path"] = str(public_path)
    public["private_material_path"] = str(private_path)
    public["markdown_path"] = str(md_path)
    public["output_files"] = [str(public_path), str(private_path), str(md_path)]
    _write_json(public_path, journal.sandbox, _without_approval_tokens(public))
    _write_json(private_path, journal.sandbox, private_material)
    _write_text(md_path, journal.sandbox, _prompt_approval_markdown(public))
    journal.write_entry(
        {
            "command": "agent-model-open-prompt-approval-plan",
            "requested_action": {"choreography_path": str(choreography_path), "limit": limit},
            "risk_classification": classify_action("agent-model-open-prompt-approval-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Approval planning only; no prompt action executed."},
            "result": {
                "status": "planned",
                "approval_required_count": len(approval_items),
                "manual_or_blocked_count": len(manual_items),
                "goal_complete": False,
            },
            "output_files": public["output_files"],
        }
    )
    return _without_approval_tokens(public)


def execute_model_open_prompt_approved_step(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    approval_material_path: Path,
    item_id: str,
    execute: bool = False,
    confirmation: str = "",
) -> dict:
    """Dry-run or execute one approved model-open/startup prompt response."""

    started_at = utc_now()
    path_error = validate_output_path(approval_material_path, journal.sandbox)
    if path_error:
        return {"success": False, "error": path_error, "goal_complete": False, "may_call_update_goal": False}
    if not approval_material_path.exists():
        return {
            "success": False,
            "error": f"Approval material not found: {approval_material_path}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    try:
        material = json.loads(approval_material_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid approval material JSON: {exc}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    item = _find_private_prompt_item(material if isinstance(material, dict) else {}, item_id)
    if item is None:
        return {"success": False, "error": f"Approval item not found: {item_id}", "goal_complete": False}

    expected_confirmation = f"I approve {item_id}"
    confirmation_ok = str(confirmation or "").strip() == expected_confirmation
    dialogs = _safe_dialogs(observer)
    prompt_match = _matching_live_prompt(dialogs, item)
    payload = item.get("action_payload") if isinstance(item.get("action_payload"), dict) else {"target": item.get("target")}
    action_result = None
    if not dialogs:
        status = "stopped_prompt_missing"
        reason = "No visible Revit prompt is present for the approved model-open prompt action."
    elif not prompt_match.get("matched"):
        status = "stopped_prompt_mismatch"
        reason = "Visible prompt does not match the approved prompt item."
    elif execute and not confirmation_ok:
        status = "stopped_confirmation_required"
        reason = "Execution requires the exact human confirmation phrase for this model-open prompt."
    else:
        action_result = SafeActionExecutor(observer, journal).run(
            ActionRequest(
                action="click",
                payload=payload,
                dry_run=not execute,
                approval_token=str(item.get("approval_token") or ""),
            )
        )
        if execute:
            status = "executed" if action_result.get("executed") else "failed"
            reason = (
                "Approved model-open prompt step executed."
                if action_result.get("executed")
                else "Approved model-open prompt step failed or was blocked by verification."
            )
        else:
            status = "ready_for_approval_execution"
            reason = "Approved model-open prompt step dry-run completed; no prompt button was clicked."

    result = {
        "success": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-model-open-prompt-approved-step/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "reason": reason,
        "item_id": item_id,
        "item_kind": item.get("kind"),
        "known_dialog_id": item.get("known_dialog_id"),
        "target": item.get("target"),
        "execute_requested": bool(execute),
        "confirmation_required": bool(execute),
        "confirmation_ok": confirmation_ok,
        "expected_confirmation_phrase": expected_confirmation,
        "fresh_prompt_match": prompt_match,
        "visible_dialog_count": len(dialogs),
        "action_payload": payload,
        "action_result": _without_approval_tokens(action_result) if action_result else None,
        "receipt": {
            "approval_bound_to_private_item": bool(item.get("approval_token")),
            "private_material_schema": material.get("schema") if isinstance(material, dict) else None,
            "source_choreography_path": material.get("source_choreography_path") if isinstance(material, dict) else None,
            "prompt_button_clicked": bool(action_result and action_result.get("executed")),
            "model_write_performed": False,
            "save_sync_publish_performed": False,
        },
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "model_open_prompt_approved_step_result.json"
    md_path = journal.run_dir / "model_open_prompt_approved_step_result.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = [str(output), str(md_path)]
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _prompt_approved_step_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-model-open-execute-approved-prompt",
            "requested_action": {"item_id": item_id, "execute": bool(execute)},
            "risk_classification": _without_approval_tokens(classify_action("click", payload).to_dict()),
            "approval_status": {
                "allowed": not execute or confirmation_ok,
                "reason": "Exact confirmation supplied." if confirmation_ok else "Dry-run or missing confirmation.",
            },
            "result": {
                "status": status,
                "executed": bool(action_result and action_result.get("executed")),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
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


def _model_open_prompt_approval_item(event_index: int, plan_index: int, prompt_plan: dict) -> dict:
    dialog = prompt_plan.get("dialog") if isinstance(prompt_plan.get("dialog"), dict) else {}
    plan = prompt_plan.get("plan") if isinstance(prompt_plan.get("plan"), dict) else {}
    planned_action = plan.get("planned_action") if isinstance(plan.get("planned_action"), dict) else None
    known_id = str(prompt_plan.get("known_dialog_id") or plan.get("known_dialog_id") or "unknown")
    title = str(dialog.get("title") or "")
    item_id = f"model-open-prompt:{event_index}:{plan_index}:{_prompt_slug(known_id or title)}"
    base_public = {
        "id": item_id,
        "kind": "model-open-prompt-step",
        "known_dialog_id": known_id,
        "dialog_index": prompt_plan.get("dialog_index", plan_index),
        "dialog": {
            "title": title,
            "dialog_text": dialog.get("dialog_text") or "",
            "buttons": dialog.get("buttons") or [],
        },
        "requires_human": plan.get("requires_human", True),
        "reason": plan.get("reason") or "Prompt requires human review.",
        "safe_preflight_commands": plan.get("safe_preflight_commands") or [],
        "blocked_buttons": plan.get("blocked_buttons") or [],
        "approval_conditions": plan.get("approval_conditions") or "",
        "verify_before_execution": [
            "list-dialogs",
            "plan-current-dialog-response",
            "click dry-run",
            "agent-session-checkpoint",
        ],
    }
    if not planned_action:
        return {
            "public": {
                **base_public,
                "status": "manual_or_blocked",
                "target": None,
                "risk": plan.get("classification", {}).get("risk"),
                "approval_token_withheld": False,
                "execute_command_withheld": False,
            },
            "private": None,
        }

    command = str(planned_action.get("command") or "click")
    payload = planned_action.get("payload") if isinstance(planned_action.get("payload"), dict) else {}
    policy = planned_action.get("policy") if isinstance(planned_action.get("policy"), dict) else classify_action(command, payload).to_dict()
    token = str(policy.get("approval_token") or "")
    target = str(payload.get("target") or "")
    public = {
        **base_public,
        "status": "approval_required" if token else "manual_or_blocked",
        "command": command,
        "target": target,
        "action_payload": payload,
        "risk": policy.get("risk"),
        "policy": _without_approval_tokens(policy),
        "approval_token_withheld": bool(token),
        "execute_command_withheld": bool(token),
        "dry_run_command": _command(["click", "--target", target]),
    }
    if not token:
        return {"public": public, "private": None}
    private = {
        **public,
        "approval_token": token,
        "execute_command": _command(["click", "--target", target, "--execute", "--approval-token", token]),
    }
    return {"public": public, "private": private}


def _find_private_prompt_item(material: dict, item_id: str) -> dict | None:
    for item in material.get("approval_items") or []:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def _matching_live_prompt(dialogs: list[dict], item: dict) -> dict:
    expected_id = str(item.get("known_dialog_id") or "")
    expected_target = str(item.get("target") or "")
    checked: list[dict] = []
    for index, dialog in enumerate(dialogs):
        plan = plan_dialog_response(
            title=str(dialog.get("title") or ""),
            text=str(dialog.get("dialog_text") or ""),
            buttons=[str(button) for button in (dialog.get("buttons") or [])],
        )
        action = plan.get("planned_action") if isinstance(plan.get("planned_action"), dict) else {}
        target = str((action.get("payload") or {}).get("target") or "")
        known_id = str(plan.get("known_dialog_id") or "")
        matched = known_id == expected_id and target == expected_target
        checked.append(
            {
                "index": index,
                "title": dialog.get("title") or "",
                "known_dialog_id": known_id,
                "target": target,
                "matched": matched,
            }
        )
        if matched:
            return {
                "matched": True,
                "dialog_index": index,
                "known_dialog_id": known_id,
                "target": target,
                "checked_dialogs": checked,
            }
    return {
        "matched": False,
        "expected_known_dialog_id": expected_id,
        "expected_target": expected_target,
        "checked_dialogs": checked,
    }


def _command(parts: list[object]) -> str:
    return " ".join(_quote(part) for part in parts if str(part) != "")


def _quote(value: object) -> str:
    text = str(value)
    if not text:
        return "''"
    if re.search(r"\s|[{}\"']", text):
        return "'" + text.replace("'", "''") + "'"
    return text


def _prompt_slug(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    return slug[:48].strip("-") or "prompt"


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


def _prompt_approval_markdown(result: dict) -> str:
    lines = [
        "# Revit Model-Open Prompt Approval Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Source choreography: `{result.get('source_choreography_path')}`",
        "Goal complete: `false`",
        f"Approval items: `{result.get('approval_required_count', 0)}`",
        f"Manual/blocked items: `{result.get('manual_or_blocked_count', 0)}`",
        "Approval material withheld from public plan: `true`",
        "",
        "## Approval Items",
        "",
    ]
    for item in result.get("approval_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('known_dialog_id')} -> {item.get('target')}")
    if not result.get("approval_items"):
        lines.append("- None.")
    lines.extend(["", "## Manual Or Blocked Items", ""])
    for item in result.get("manual_or_blocked_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('known_dialog_id')} ({item.get('reason')})")
    if not result.get("manual_or_blocked_items"):
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _prompt_approved_step_markdown(result: dict) -> str:
    lines = [
        "# Revit Model-Open Prompt Approved Step Result",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Item: `{result.get('item_id')}`",
        f"Dialog: `{result.get('known_dialog_id')}`",
        f"Target: `{result.get('target')}`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Execution",
        "",
        f"- execute_requested: `{str(result.get('execute_requested')).lower()}`",
        f"- confirmation_required: `{str(result.get('confirmation_required')).lower()}`",
        f"- confirmation_ok: `{str(result.get('confirmation_ok')).lower()}`",
        f"- prompt_button_clicked: `{str(result.get('receipt', {}).get('prompt_button_clicked')).lower()}`",
        f"- model_write_performed: `{str(result.get('receipt', {}).get('model_write_performed')).lower()}`",
    ]
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
