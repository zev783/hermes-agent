"""Supervised higher-level Revit operator workflows."""

from __future__ import annotations

import json

from .bridge import RevitBridgeClient
from .actions import ActionRequest, SafeActionExecutor
from .journal import TaskJournal, utc_now
from .operations import OperationRequest, queue_operation
from .qa import generate_qa_report
from .windows import RevitWindowObserver


def run_readonly_qa_workflow(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    timeout: float = 120.0,
    poll: float = 1.0,
    capture_screenshot: bool = True,
    capture_ui_tree: bool = True,
    focus_hwnd: int | None = None,
    focus_approval_token: str | None = None,
    idle_nudge: bool = False,
) -> dict:
    """Run a cautious read-only QA sequence against the active Revit document."""

    started_at = utc_now()
    steps: list[dict] = []
    output_files: list[str] = []

    initial_status = observer.status()
    steps.append(
        {
            "step": "observe-initial-status",
            "success": True,
            "state": initial_status.get("state"),
            "active_dialog_count": len(initial_status.get("active_dialogs") or []),
        }
    )
    if initial_status.get("active_dialogs"):
        result = {
            "success": False,
            "started_at": started_at,
            "finished_at": utc_now(),
            "steps": steps,
            "initial_status": initial_status,
            "error": "Active Revit dialogs are present; resolve/classify dialogs before running the QA workflow.",
        }
        _log_workflow(journal, result, output_files)
        return result

    active_result = _queue_and_wait(
        journal,
        observer,
        bridge,
        operation="active-document",
        timeout=timeout,
        poll=poll,
        focus_hwnd=focus_hwnd,
        focus_approval_token=focus_approval_token,
        idle_nudge=idle_nudge,
    )
    steps.append(active_result)
    if not active_result.get("success"):
        result = _workflow_result(False, started_at, steps, output_files, active_result.get("error"))
        _log_workflow(journal, result, output_files)
        return result

    metadata_result = _queue_and_wait(
        journal,
        observer,
        bridge,
        operation="export-metadata",
        timeout=timeout,
        poll=poll,
        focus_hwnd=focus_hwnd,
        focus_approval_token=focus_approval_token,
        idle_nudge=idle_nudge,
    )
    steps.append(metadata_result)
    if not metadata_result.get("success"):
        result = _workflow_result(False, started_at, steps, output_files, metadata_result.get("error"))
        _log_workflow(journal, result, output_files)
        return result

    metadata_copy = bridge.export_metadata(journal.default_metadata_path("json"))
    steps.append({"step": "copy-metadata", **metadata_copy})
    if metadata_copy.get("path"):
        output_files.append(str(metadata_copy["path"]))
    if not metadata_copy.get("success"):
        result = _workflow_result(False, started_at, steps, output_files, metadata_copy.get("error"))
        _log_workflow(journal, result, output_files)
        return result

    if capture_ui_tree:
        ui_tree_path = journal.run_dir / "ui_tree.json"
        ui_tree = observer.ui_tree(max_depth=2)
        ui_tree_path.write_text(json.dumps(ui_tree, indent=2, sort_keys=True), encoding="utf-8")
        ui_tree["path"] = str(ui_tree_path)
        steps.append({"step": "capture-ui-tree", **ui_tree})
        output_files.append(str(ui_tree_path))

    if capture_screenshot:
        screenshot = observer.screenshot(journal.default_screenshot_path("bmp"))
        steps.append({"step": "capture-screenshot", **screenshot})
        if screenshot.get("path"):
            output_files.append(str(screenshot["path"]))

    report = generate_qa_report(journal)
    steps.append({"step": "generate-qa-report", **report})
    if report.get("path"):
        output_files.append(str(report["path"]))

    final_status = observer.status()
    result = {
        "success": bool(report.get("success")),
        "started_at": started_at,
        "finished_at": utc_now(),
        "workflow": "readonly-qa",
        "initial_state": initial_status.get("state"),
        "final_state": final_status.get("state"),
        "active_document": bridge.active_document_status(),
        "metadata_path": metadata_copy.get("path"),
        "qa_report_path": report.get("path"),
        "findings": report.get("findings", []),
        "steps": steps,
        "output_files": output_files,
    }
    _log_workflow(journal, result, output_files)
    return result


def _queue_and_wait(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    operation: str,
    timeout: float,
    poll: float,
    focus_hwnd: int | None,
    focus_approval_token: str | None,
    idle_nudge: bool,
) -> dict:
    queued = queue_operation(
        journal,
        OperationRequest(operation=operation, args={}, dry_run=False),
    )
    command_id = queued.get("command", {}).get("id")
    step = {
        "step": f"bridge-{operation}",
        "operation": operation,
        "queued": queued.get("success"),
        "command_id": command_id,
        "queue_result": queued,
        "nudge": None,
    }
    if not queued.get("success") or not command_id:
        return {**step, "success": False, "error": queued.get("error") or "Bridge command was not queued."}

    if focus_hwnd or idle_nudge:
        step["nudge"] = _nudge_revit_idle(
            journal,
            observer,
            focus_hwnd=focus_hwnd,
            focus_approval_token=focus_approval_token,
            idle_nudge=idle_nudge,
        )
    wait = bridge.wait_for_command_result(command_id, timeout=timeout, poll=poll)
    if not wait.get("found") and step.get("nudge") is None and idle_nudge:
        step["nudge"] = _nudge_revit_idle(
            journal,
            observer,
            focus_hwnd=focus_hwnd,
            focus_approval_token=focus_approval_token,
            idle_nudge=idle_nudge,
        )
        wait = bridge.wait_for_command_result(command_id, timeout=timeout, poll=poll)
    return {**step, "success": bool(wait.get("success")), "wait_result": wait, "error": wait.get("error")}


def _nudge_revit_idle(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    focus_hwnd: int | None,
    focus_approval_token: str | None,
    idle_nudge: bool,
) -> dict:
    executor = SafeActionExecutor(observer, journal)
    actions: list[dict] = []
    if focus_hwnd:
        actions.append(
            executor.run(
                ActionRequest(
                    action="focus",
                    payload={"hwnd": focus_hwnd},
                    dry_run=False,
                    approval_token=focus_approval_token,
                )
            )
        )
    if idle_nudge:
        actions.append(
            executor.run(
                ActionRequest(
                    action="press-key",
                    payload={"key": "Escape"},
                    dry_run=False,
                )
            )
        )
    return {
        "success": all(action.get("executed") for action in actions),
        "actions": actions,
    }


def _workflow_result(
    success: bool,
    started_at: str,
    steps: list[dict],
    output_files: list[str],
    error: str | None,
) -> dict:
    result = {
        "success": success,
        "started_at": started_at,
        "finished_at": utc_now(),
        "workflow": "readonly-qa",
        "steps": steps,
        "output_files": output_files,
    }
    if error:
        result["error"] = error
    return result


def _log_workflow(journal: TaskJournal, result: dict, output_files: list[str]) -> None:
    journal.write_entry(
        {
            "command": "qa-workflow",
            "requested_action": {"workflow": "readonly-qa"},
            "risk_classification": {
                "action": "qa-workflow",
                "risk": "low",
                "decision": "allow",
                "reason": "Supervised read-only QA workflow.",
                "approval_token": None,
            },
            "approval_status": {"allowed": True, "reason": "Read-only workflow."},
            "result": {"status": "completed" if result.get("success") else "failed", "success": result.get("success")},
            "output_files": output_files,
        }
    )
