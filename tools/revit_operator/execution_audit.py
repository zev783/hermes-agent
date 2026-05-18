"""Read-only audits for approved live UI execution coverage."""

from __future__ import annotations

import json
from pathlib import Path

from .journal import TaskJournal
from .safety import classify_action, validate_output_path


DEFAULT_REQUIRED_SURFACES = [
    "focus",
    "escape-key",
    "dialog-click",
    "type-text",
    "uia-invoke",
    "visual-click",
    "ribbon-action",
    "context-menu-action",
    "context-menu-item",
    "approved-ui-workflow-step",
]


def audit_ui_execution_coverage(
    journal: TaskJournal,
    *,
    required_surfaces: list[str] | None = None,
    require_live_evidence: bool = True,
) -> dict:
    """Audit existing task journals for real authorized UI execution coverage."""

    required = list(required_surfaces or DEFAULT_REQUIRED_SURFACES)
    journal_paths = _journal_paths(journal.sandbox)
    records = []
    excluded_records = []

    for path in journal_paths:
        for entry in _read_jsonl(path):
            record = _execution_record(path, entry)
            if not record:
                continue
            excluded_reasons = _exclusion_reasons(record, require_live_evidence=require_live_evidence)
            if excluded_reasons:
                record["qualifies"] = False
                record["excluded_reasons"] = excluded_reasons
                excluded_records.append(record)
                continue
            record["qualifies"] = True
            records.append(record)

    surface_counts = {surface: 0 for surface in required}
    for record in records:
        for surface in record["surfaces"]:
            surface_counts[surface] = surface_counts.get(surface, 0) + 1

    covered_required = [surface for surface in required if surface_counts.get(surface, 0) > 0]
    missing_required = [surface for surface in required if surface_counts.get(surface, 0) == 0]
    target_met = not missing_required

    output = journal.run_dir / "ui_execution_coverage_audit.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": True,
        "read_only": True,
        "live_ui_touched": False,
        "status": "target_met" if target_met else "insufficient_evidence",
        "target_met": target_met,
        "required_surfaces": required,
        "covered_required_surfaces": covered_required,
        "missing_required_surfaces": missing_required,
        "surface_counts": surface_counts,
        "qualifying_execution_count": len(records),
        "excluded_execution_count": len(excluded_records),
        "journal_count": len(journal_paths),
        "require_live_evidence": bool(require_live_evidence),
        "qualifying_executions": records,
        "excluded_executions": excluded_records,
        "path": str(output),
        "note": (
            "Read-only coverage audit only. This command scans sandboxed task "
            "journals and does not poll, focus, click, type, invoke UIA, queue "
            "bridge operations, save, sync, reload, close, detach, upgrade, or "
            "modify Revit."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "ui-execution-coverage-audit",
            "requested_action": {
                "required_surfaces": required,
                "require_live_evidence": require_live_evidence,
            },
            "risk_classification": classify_action("ui-execution-coverage-audit", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only UI execution coverage audit."},
            "result": {
                "status": result["status"],
                "target_met": target_met,
                "missing_required_surfaces": missing_required,
                "qualifying_execution_count": len(records),
            },
            "output_files": [str(output)],
        }
    )
    return result


def _journal_paths(sandbox: Path) -> list[Path]:
    root = sandbox / "revit_operator_runs"
    if not root.exists():
        return []
    return sorted(root.glob("*/journal.jsonl"))


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _execution_record(path: Path, entry: dict) -> dict | None:
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    command = str(entry.get("command") or "")
    executed = result.get("executed") is True or result.get("status") == "executed"
    executed_steps = result.get("executed_steps") if isinstance(result.get("executed_steps"), list) else []
    if not executed and not executed_steps:
        return None

    task_id = str(entry.get("task_id") or path.parent.name)
    requested = entry.get("requested_action") if isinstance(entry.get("requested_action"), dict) else {}
    surfaces = _surfaces_for_execution(command, requested, result, task_id, executed_steps)
    approval_status = entry.get("approval_status") if isinstance(entry.get("approval_status"), dict) else {}
    risk = entry.get("risk_classification") if isinstance(entry.get("risk_classification"), dict) else {}
    before = entry.get("observed_ui_state_before_action")
    after = entry.get("observed_ui_state_after_action")
    return {
        "task_id": task_id,
        "journal": str(path),
        "timestamp": entry.get("timestamp"),
        "command": command,
        "requested_action": requested,
        "result": result,
        "risk_classification": risk,
        "approval_status": approval_status,
        "authorized": approval_status.get("allowed") is True or risk.get("decision") == "allow",
        "surfaces": surfaces,
        "has_live_evidence": _has_live_evidence(before) or _has_live_evidence(after),
        "before_state": before.get("state") if isinstance(before, dict) else None,
        "after_state": after.get("state") if isinstance(after, dict) else None,
        "executed_steps": executed_steps,
    }


def _surfaces_for_execution(
    command: str,
    requested: dict,
    result: dict,
    task_id: str,
    executed_steps: list,
) -> list[str]:
    surfaces = []
    task = task_id.lower()
    if command == "focus":
        surfaces.append("focus")
    elif command == "press-key":
        key = str(requested.get("key") or "").strip().lower()
        surfaces.append("escape-key" if key in {"escape", "esc"} else "keyboard-key")
    elif command == "click":
        surfaces.append("dialog-click")
    elif command == "type-text":
        surfaces.append("type-text")
    elif command == "visual-click":
        surfaces.append("visual-click")
    elif command == "uia-invoke":
        surfaces.append("uia-invoke")
        method = str(requested.get("method") or "").strip().lower()
        control_type = str(requested.get("control_type") or "").strip().lower()
        if method:
            surfaces.append(f"uia-method:{method}")
        if requested.get("ribbon_action") or "ribbon" in task:
            surfaces.append("ribbon-action")
        if requested.get("context_menu_item") or control_type == "menuitem":
            surfaces.append("context-menu-item")
        if requested.get("context_menu_action") or requested.get("context_menu_item") or "context-menu" in task:
            if control_type == "menuitem" or requested.get("context_menu_item"):
                surfaces.append("context-menu-item")
            elif method == "right_click_input":
                surfaces.append("context-menu-action")
            else:
                surfaces.append("context-menu-action")
    elif command in {"run-ui-workflow", "replay-workflow"} and result.get("approved_executed_steps"):
        surfaces.append("approved-ui-workflow-step")
    return sorted(set(surfaces))


def _exclusion_reasons(record: dict, *, require_live_evidence: bool) -> list[str]:
    reasons = []
    task = str(record.get("task_id") or "").lower()
    requested = record.get("requested_action") if isinstance(record.get("requested_action"), dict) else {}
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    if "test" in task or "matrix" in task or "audit" in task:
        reasons.append("test/matrix/audit task")
    if requested.get("dry_run") is True or result.get("dry_run") is True or result.get("status") == "dry_run":
        reasons.append("dry-run execution record")
    if not record.get("authorized"):
        reasons.append("not authorized")
    if not record.get("surfaces"):
        reasons.append("no tracked UI execution surface")
    if require_live_evidence and not record.get("has_live_evidence"):
        reasons.append("no before/after live UI observation")
    return reasons


def _has_live_evidence(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("main_window"):
        return True
    dialogs = value.get("active_dialogs")
    if isinstance(dialogs, list) and dialogs:
        return True
    return bool(value.get("revit_running"))
