"""Read-only model/session readiness predicates for supervised Revit work."""

from __future__ import annotations

import json
import time

from .bridge import RevitBridgeClient
from .journal import TaskJournal, utc_now
from .safety import validate_output_path
from .windows import RevitWindowObserver


def wait_model_ready(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    timeout: float = 120.0,
    poll: float = 2.0,
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    expected_revit_version: str = "",
    expected_view_name: str = "",
    expected_view_type: str = "",
    require_bridge: bool = True,
    stop_on_modal: bool = True,
) -> dict:
    """Wait until Revit is idle, non-modal, and the active document matches expectations."""

    output = journal.run_dir / "model_ready_status.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    deadline = time.monotonic() + max(0.0, timeout)
    checks: list[dict] = []
    stop_reason = "timeout"
    final_evaluation: dict | None = None
    while True:
        status = _safe_status(observer)
        active_document = _safe_active_document(bridge)
        evaluation = _evaluate_model_ready(
            status,
            active_document,
            expected_title_contains=expected_title_contains,
            expected_path_contains=expected_path_contains,
            expected_revit_version=expected_revit_version,
            expected_view_name=expected_view_name,
            expected_view_type=expected_view_type,
            require_bridge=require_bridge,
        )
        check = {
            "checked_at": utc_now(),
            "index": len(checks),
            "state": status.get("state"),
            "active_dialog_count": len(status.get("active_dialogs") or []),
            "ready": evaluation["ready"],
            "evaluation": evaluation,
            "main_window": status.get("main_window"),
            "active_document": _bridge_document_payload(active_document),
        }
        checks.append(check)
        final_evaluation = evaluation

        if evaluation["ready"]:
            stop_reason = "model_ready"
            break
        if stop_on_modal and (status.get("state") == "modal" or status.get("active_dialogs")):
            stop_reason = "modal_state_detected"
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.1, poll))

    result = {
        "success": bool(final_evaluation and final_evaluation.get("ready")),
        "ready": bool(final_evaluation and final_evaluation.get("ready")),
        "read_only": True,
        "stop_reason": stop_reason,
        "checked_at": utc_now(),
        "check_count": len(checks),
        "final_evaluation": final_evaluation or {},
        "final_check": checks[-1] if checks else None,
        "checks": checks,
        "expectations": {
            "expected_title_contains": expected_title_contains,
            "expected_path_contains": expected_path_contains,
            "expected_revit_version": expected_revit_version,
            "expected_view_name": expected_view_name,
            "expected_view_type": expected_view_type,
            "require_bridge": require_bridge,
            "stop_on_modal": stop_on_modal,
        },
        "path": str(output),
        "note": (
            "This command only observes readiness. It does not click dialogs, "
            "open models, activate views, save, sync, or modify Revit."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "wait-model-ready",
            "requested_action": result["expectations"],
            "result": {
                "status": stop_reason,
                "success": result["success"],
                "ready": result["ready"],
                "check_count": result["check_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def _evaluate_model_ready(
    status: dict,
    active_document: dict,
    *,
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    expected_revit_version: str = "",
    expected_view_name: str = "",
    expected_view_type: str = "",
    require_bridge: bool = True,
) -> dict:
    document = _bridge_document_payload(active_document)
    checks = [
        _check("revit_running", bool(status.get("revit_running")), "Revit process is running."),
        _check("main_window_present", bool(status.get("main_window")), "A Revit main window is visible."),
        _check("state_idle", status.get("state") == "idle", "Revit observer state is idle."),
        _check(
            "no_active_dialogs",
            not bool(status.get("active_dialogs")),
            "No active/modal dialogs are visible.",
        ),
    ]
    if require_bridge:
        checks.append(
            _check(
                "active_document_bridge_available",
                bool(active_document.get("available")),
                "Bridge active-document payload is available.",
            )
        )
    else:
        checks.append(
            _check(
                "active_document_bridge_optional",
                True,
                "Bridge active-document payload was optional for this readiness check.",
            )
        )
    if active_document.get("available") or document:
        checks.extend(
            [
                _contains_check(
                    "title_contains_expected",
                    document.get("title"),
                    expected_title_contains,
                    "Document title contains the expected text.",
                ),
                _contains_check(
                    "path_contains_expected",
                    document.get("path"),
                    expected_path_contains,
                    "Document path contains the expected text.",
                ),
                _equals_check(
                    "revit_version_expected",
                    document.get("revit_version") or _nested_value(active_document, ["document", "revit_version"]),
                    expected_revit_version,
                    "Document reports the expected Revit version.",
                ),
                _equals_check(
                    "active_view_name_expected",
                    _nested_value(document, ["active_view", "name"]),
                    expected_view_name,
                    "Active view name matches expected value.",
                ),
                _equals_check(
                    "active_view_type_expected",
                    _nested_value(document, ["active_view", "type"]),
                    expected_view_type,
                    "Active view type matches expected value.",
                ),
            ]
        )
    ready = all(check["passed"] for check in checks)
    return {
        "ready": ready,
        "checks": checks,
        "document": document,
        "state": status.get("state"),
        "reason": "Model is ready for supervised work." if ready else _first_failed_reason(checks),
    }


def _safe_status(observer: RevitWindowObserver) -> dict:
    try:
        status = observer.status()
    except Exception as exc:
        return {"state": "unknown", "revit_running": False, "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"state": "unknown", "raw_status": status}


def _safe_active_document(bridge: RevitBridgeClient) -> dict:
    try:
        status = bridge.active_document_status()
    except Exception as exc:
        return {"available": False, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"available": False, "status": "invalid", "raw_status": status}


def _bridge_document_payload(active_document: dict) -> dict:
    data = active_document.get("document") if isinstance(active_document, dict) else None
    if not isinstance(data, dict):
        return {}
    nested = data.get("document")
    if isinstance(nested, dict):
        return nested
    return data


def _check(name: str, passed: bool, passed_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": passed_reason if passed else f"Readiness check failed: {name}.",
    }


def _contains_check(name: str, actual: object, expected: str, passed_reason: str) -> dict:
    expected = str(expected or "").strip()
    if not expected:
        return {"name": name, "passed": True, "skipped": True, "reason": "No expectation supplied."}
    actual_text = str(actual or "")
    passed = expected.casefold() in actual_text.casefold()
    return {
        "name": name,
        "passed": passed,
        "expected_contains": expected,
        "actual": actual_text,
        "reason": passed_reason if passed else f"Expected {actual_text!r} to contain {expected!r}.",
    }


def _equals_check(name: str, actual: object, expected: str, passed_reason: str) -> dict:
    expected = str(expected or "").strip()
    if not expected:
        return {"name": name, "passed": True, "skipped": True, "reason": "No expectation supplied."}
    actual_text = str(actual or "").strip()
    passed = actual_text.casefold() == expected.casefold()
    return {
        "name": name,
        "passed": passed,
        "expected": expected,
        "actual": actual_text,
        "reason": passed_reason if passed else f"Expected {expected!r}, observed {actual_text!r}.",
    }


def _nested_value(payload: dict, path: list[str]) -> object:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_failed_reason(checks: list[dict]) -> str:
    for check in checks:
        if not check.get("passed"):
            return str(check.get("reason") or f"Readiness check failed: {check.get('name')}")
    return "No failed checks."
