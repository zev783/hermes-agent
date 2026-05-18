"""Expanded supervised Revit operation audit/report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .constants import DRAFT_LABEL
from .journal import TaskJournal
from .safety import classify_action, validate_output_path


def run_supervised_ops_audit(journal: TaskJournal) -> dict:
    """Write an evidence-backed audit for the expanded supervised operation goal."""

    run_dir = journal.run_dir
    coverage = _read_json(run_dir / "ui_execution_coverage_audit.json")
    model_ready = _read_json(run_dir / "model_ready_status.json")
    browser_plan = _read_json(run_dir / "project_browser_navigation_plan.json")
    dialog_matrix = _read_json(run_dir / "dialog_workflow_matrix.json")
    action_matrix = _read_json(run_dir / "action_approval_matrix.json")
    transport_matrix = _read_json(run_dir / "metadata" / "transport_safety_matrix.json")
    recovery = _read_json(run_dir / "recovery_snapshot.json")

    metadata_files = sorted((run_dir / "metadata").glob("metadata-*.json"))
    screenshots = sorted((run_dir / "screenshots").glob("*.bmp"))
    qa_report = run_dir / "qa_report.md"
    journal_path = journal.journal_path
    journal_entries = _read_jsonl(journal_path)
    bridge_results = _read_jsonl(journal.sandbox / "bridge" / "command_results.jsonl")

    current_task_coverage = _current_task_surface_counts(coverage, journal.task_id)
    recovery_quality = _recovery_quality(recovery)
    activate_view = _latest_activate_view_result(journal_entries, bridge_results)
    view_lookup = browser_plan.get("view_lookup") if isinstance(browser_plan.get("view_lookup"), dict) else {}
    view_lookup_count = int(browser_plan.get("view_lookup_count") or view_lookup.get("count") or 0)
    browser_plan_path = browser_plan.get("path") or str(run_dir / "project_browser_navigation_plan.json")

    checklist = [
        _item(
            "live-model-readiness",
            "Live Revit is attached, idle, on the copied Revit 2025 detached model.",
            bool(model_ready.get("ready") is True and model_ready.get("success") is True),
            [model_ready.get("path")],
            "" if model_ready else "No model readiness artifact found.",
        ),
        _item(
            "approved-nondestructive-ui-actions",
            "Multiple approved non-destructive UI actions ran with before/after live evidence.",
            coverage.get("target_met") is True
            and not coverage.get("missing_required_surfaces")
            and sum(current_task_coverage.values()) >= 3
            and current_task_coverage.get("ribbon-action", 0) >= 2
            and current_task_coverage.get("focus", 0) >= 1,
            [coverage.get("path")],
            f"Current run surfaces: {current_task_coverage}",
        ),
        _item(
            "project-browser-sheet-planning",
            "Sheet/view navigation is planned through Project Browser evidence and metadata-backed route selection.",
            bool((browser_plan.get("success") is True or view_lookup.get("success") is True) and view_lookup_count >= 1),
            [browser_plan_path],
            "Execution is still incomplete if activate-view or UI selection fails.",
        ),
        _item(
            "guarded-view-activation",
            "A guarded sheet/view activation succeeds or fails safely with logged Revit API result.",
            bool(activate_view and activate_view.get("observed") and activate_view.get("failed_safely")),
            [str(journal_path)],
            activate_view.get("summary", "No activate-view result found.") if activate_view else "No activate-view result found.",
        ),
        _item(
            "dialog-classification-policy",
            "Representative Revit prompts are classified conservatively with blocked buttons and approval gates.",
            bool(dialog_matrix.get("success") is True and not dialog_matrix.get("failed_cases")),
            [dialog_matrix.get("path")],
            f"Dialog cases: {dialog_matrix.get('case_count', 0)}.",
        ),
        _item(
            "blocked-save-sync-destructive-actions",
            "Save/sync/destructive surfaces are blocked or critical approval-gated by policy.",
            _action_matrix_blocks_danger(action_matrix, transport_matrix),
            [action_matrix.get("path"), transport_matrix.get("path")],
            "Requires both action policy and transport fail-closed evidence.",
        ),
        _item(
            "api-backed-readonly-export",
            "Read-only Revit bridge exported metadata and a draft QA report to the sandbox.",
            bool(metadata_files and qa_report.exists()),
            [str(path) for path in metadata_files[:3]] + [str(qa_report)],
            "No save/sync/model modification is needed for this evidence.",
        ),
        _item(
            "live-modal-or-stuck-recovery",
            "Recovery was proven against a real modal, stuck, busy, or hung Revit state.",
            recovery_quality["qualifies"],
            [recovery.get("path") or str(run_dir / "recovery_snapshot.json")],
            recovery_quality["reason"],
        ),
        _item(
            "structured-journal-screenshots",
            "Every operation is journaled and the run has screenshot/UI/metadata artifacts.",
            bool(journal_path.exists() and journal_entries and screenshots and metadata_files),
            [str(journal_path)] + [str(path) for path in screenshots[:3]],
            f"Journal entries: {len(journal_entries)}; screenshots: {len(screenshots)}.",
        ),
    ]

    unsatisfied = [item for item in checklist if item["status"] != "satisfied"]
    result = {
        "success": True,
        "read_only": True,
        "label": DRAFT_LABEL,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "objective_restatement": (
            "Expand Hermes from a read-only Revit human-operator substrate into a supervised "
            "programmatic operation layer with guarded UI actions, Revit API bridge operations, "
            "prompt handling, recovery, sandboxed outputs, and audit trails."
        ),
        "goal_complete": not unsatisfied,
        "may_call_update_goal": False if unsatisfied else True,
        "status": "incomplete" if unsatisfied else "complete",
        "checklist": checklist,
        "unsatisfied_ids": [item["id"] for item in unsatisfied],
        "capabilities_proven": [item["id"] for item in checklist if item["status"] == "satisfied"],
        "gaps_remaining": [item["id"] for item in unsatisfied],
        "workflow_approval_note": (
            "Exact approval tokens in journals show policy authorization for the tested payloads. "
            "Future model-changing, save/sync, reload, destructive, or ambiguous UI actions still "
            "require fresh human approval and fresh preflight evidence."
        ),
        "journal": journal.describe(),
    }

    json_path = run_dir / "supervised_ops_audit.json"
    md_path = run_dir / "SUPERVISED_PROGRAMMATIC_REVIT_OPERATION_REPORT.md"
    for output in (json_path, md_path):
        error = validate_output_path(output, journal.sandbox)
        if error:
            return {"success": False, "error": error}

    result["path"] = str(json_path)
    result["markdown_path"] = str(md_path)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(result), encoding="utf-8")

    journal.write_entry(
        {
            "command": "supervised-ops-audit",
            "requested_action": {"type": "completion-audit"},
            "risk_classification": classify_action("supervised-ops-audit", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only expanded goal audit."},
            "result": {
                "status": result["status"],
                "goal_complete": result["goal_complete"],
                "unsatisfied_ids": result["unsatisfied_ids"],
            },
            "output_files": [str(json_path), str(md_path)],
        }
    )
    return result


def _item(
    item_id: str,
    requirement: str,
    satisfied: bool,
    evidence: list[str | None],
    note: str,
) -> dict:
    return {
        "id": item_id,
        "requirement": requirement,
        "status": "satisfied" if satisfied else "incomplete",
        "satisfied": bool(satisfied),
        "evidence": [str(path) for path in evidence if path],
        "note": note,
    }


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _current_task_surface_counts(coverage: dict, task_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in coverage.get("qualifying_executions") or []:
        if not isinstance(record, dict) or record.get("task_id") != task_id:
            continue
        for surface in record.get("surfaces") or []:
            counts[str(surface)] = counts.get(str(surface), 0) + 1
    return counts


def _action_matrix_blocks_danger(action_matrix: dict, transport_matrix: dict) -> bool:
    cases = action_matrix.get("cases") if isinstance(action_matrix.get("cases"), list) else []
    by_name = {case.get("name"): case for case in cases if isinstance(case, dict)}
    save_click = by_name.get("click-save-blocked", {}).get("policy", {})
    save_uia = by_name.get("uia-save-blocked", {}).get("policy", {})
    save_bridge = by_name.get("request-save-critical-approval", {}).get("policy", {})
    transport_clean = (
        transport_matrix.get("success") is True
        and transport_matrix.get("status") == "clean"
        and not transport_matrix.get("failed_check_ids")
    )
    return (
        transport_clean
        and save_click.get("decision") == "block"
        and save_uia.get("decision") == "block"
        and save_bridge.get("decision") == "approval_required"
        and save_bridge.get("risk") == "critical"
    )


def _latest_activate_view_result(entries: list[dict], bridge_results: list[dict]) -> dict:
    latest: dict = {}
    for bridge_result in bridge_results:
        if not isinstance(bridge_result, dict):
            continue
        command_id = str(bridge_result.get("id") or "")
        if not command_id.startswith("activate_view-"):
            continue
        success = bridge_result.get("success") is True
        error = str(bridge_result.get("error") or "")
        latest = {
            "observed": True,
            "success": success,
            "failed_safely": not success and bool(error),
            "summary": "activate-view succeeded." if success else f"activate-view failed safely: {error}",
        }
    for entry in entries:
        if entry.get("command") != "wait-bridge-result":
            continue
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        bridge_result = result.get("bridge_result") or result.get("result") or {}
        if not isinstance(bridge_result, dict):
            continue
        command_id = str(bridge_result.get("id") or "")
        if not command_id.startswith("activate_view-"):
            continue
        success = bridge_result.get("success") is True
        error = str(bridge_result.get("error") or "")
        latest = {
            "observed": True,
            "success": success,
            "failed_safely": not success and bool(error),
            "summary": "activate-view succeeded." if success else f"activate-view failed safely: {error}",
        }
    return latest


def _recovery_quality(recovery: dict) -> dict:
    if not recovery:
        return {"qualifies": False, "reason": "No recovery snapshot artifact found."}
    status = recovery.get("status") if isinstance(recovery.get("status"), dict) else {}
    dialogs = recovery.get("dialogs") if isinstance(recovery.get("dialogs"), dict) else {}
    dialog_items = dialogs.get("dialogs") if isinstance(dialogs.get("dialogs"), list) else []
    for dialog in dialog_items:
        if not isinstance(dialog, dict):
            continue
        rect = dialog.get("rect") if isinstance(dialog.get("rect"), dict) else {}
        has_area = int(rect.get("width") or 0) > 0 and int(rect.get("height") or 0) > 0
        has_content = bool(
            dialog.get("title")
            or dialog.get("dialog_text")
            or dialog.get("buttons")
            or dialog.get("controls")
        )
        if has_area and has_content:
            return {"qualifies": True, "reason": "Recovery snapshot contains a visible contentful dialog."}
    if status.get("state") in {"busy", "unknown"} or any(
        bool(dialog.get("is_hung")) for dialog in status.get("active_dialogs", []) if isinstance(dialog, dict)
    ):
        return {"qualifies": True, "reason": "Recovery snapshot captured busy/unknown/hung Revit evidence."}
    return {
        "qualifies": False,
        "reason": (
            "Existing recovery snapshot was a contentless zero-area owner window, which is now "
            "classified as a false modal and does not prove live stuck/modal recovery."
        ),
    }


def _markdown(result: dict) -> str:
    lines = [
        "# Supervised Programmatic Revit Operation Report",
        "",
        DRAFT_LABEL,
        "",
        f"Generated: {result['generated_at_utc']}",
        "",
        "## Objective",
        "",
        result["objective_restatement"],
        "",
        "## Result",
        "",
        f"Status: `{result['status']}`",
        f"Goal complete: `{str(result['goal_complete']).lower()}`",
        "",
        "## Checklist",
        "",
    ]
    for item in result["checklist"]:
        lines.append(f"- `{item['status']}` {item['id']}: {item['requirement']}")
        if item["note"]:
            lines.append(f"  Note: {item['note']}")
    lines.extend(
        [
            "",
            "## Remaining Gaps",
            "",
        ]
    )
    if result["gaps_remaining"]:
        lines.extend(f"- {gap}" for gap in result["gaps_remaining"])
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Approval Boundary",
            "",
            result["workflow_approval_note"],
            "",
        ]
    )
    return "\n".join(lines)
