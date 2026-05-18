"""Recovery and stuck-state evidence capture for the Revit operator."""

from __future__ import annotations

import json
from pathlib import Path

from .bridge import RevitBridgeClient
from .dialog_workflows import plan_dialog_response
from .journal import TaskJournal, utc_now
from .safety import classify_action, validate_output_path
from .windows import RevitWindowObserver


def capture_recovery_snapshot(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    capture_screenshot: bool = True,
    capture_ui_tree: bool = True,
    max_depth: int = 2,
    bridge_result_limit: int = 10,
) -> dict:
    """Capture a read-only evidence bundle for recovery decisions."""

    output = journal.run_dir / "recovery_snapshot.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    status = observer.status()
    dialogs = observer.list_dialogs()
    dialog_plans = _dialog_recovery_plans(dialogs)
    ui_tree = (
        observer.ui_tree(max_depth=max(0, max_depth))
        if capture_ui_tree
        else {"skipped": True}
    )
    screenshot = {"skipped": True}
    if capture_screenshot:
        screenshot = observer.screenshot(journal.default_screenshot_path("bmp"))

    bridge_results = bridge.read_command_results()
    if bridge_result_limit >= 0:
        bridge_results = bridge_results[-bridge_result_limit:] if bridge_result_limit else []

    snapshot = {
        "label": "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW",
        "captured_at": utc_now(),
        "status": status,
        "dialogs": dialogs,
        "dialog_recovery_plans": dialog_plans,
        "ui_tree": ui_tree,
        "screenshot": screenshot,
        "active_document": bridge.active_document_status(),
        "recent_bridge_results": bridge_results,
        "recommendation": _recommendation(status, dialogs, dialog_plans),
    }
    recovery_gate = classify_recovery_snapshot_for_north_star(
        journal.task_id,
        output,
        snapshot,
    )
    snapshot["north_star_recovery_gate"] = recovery_gate
    snapshot["validated_live_recovery_drill"] = recovery_gate["qualifies"]
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

    output_files = [str(output)]
    if isinstance(screenshot, dict) and screenshot.get("path"):
        output_files.append(str(screenshot["path"]))

    return {
        "success": True,
        "path": str(output),
        "output_files": output_files,
        "state": status.get("state"),
        "active_dialog_count": len(dialogs.get("dialogs") or []),
        "recommendation": snapshot["recommendation"],
        "validated_live_recovery_drill": recovery_gate["qualifies"],
        "north_star_recovery_gate": recovery_gate,
    }


def classify_recovery_snapshot_for_north_star(
    task_id: str,
    path: Path,
    payload: dict,
) -> dict:
    """Classify whether a recovery snapshot can satisfy the live north-star gate."""

    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    dialogs = payload.get("dialogs") if isinstance(payload.get("dialogs"), dict) else {}
    recommendation = (
        payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else {}
    )
    main_window = status.get("main_window") if isinstance(status.get("main_window"), dict) else {}
    active_dialogs = status.get("active_dialogs") if isinstance(status.get("active_dialogs"), list) else []
    dialog_items = dialogs.get("dialogs") if isinstance(dialogs.get("dialogs"), list) else []
    dialog_count = len(dialog_items) or len(active_dialogs)
    state = str(status.get("state") or "")
    hung_window = bool(main_window.get("is_hung"))
    is_revit_window = bool(main_window.get("is_revit_related")) or str(
        main_window.get("process_name") or ""
    ).lower() == "revit.exe"

    excluded_reasons: list[str] = []
    task_lower = str(task_id or "").lower()
    if "matrix" in task_lower or "synthetic" in task_lower or task_lower.endswith("-test"):
        excluded_reasons.append("synthetic or matrix recovery artifact")
    if not is_revit_window:
        excluded_reasons.append("no live Revit main-window evidence")
    if not (state in {"modal", "busy", "unknown"} or dialog_count > 0 or hung_window):
        excluded_reasons.append("snapshot does not show a live recovery condition")

    classification = str(recommendation.get("classification") or "")
    if dialog_count > 0 or state == "modal":
        if classification != "human_decision_required":
            excluded_reasons.append("modal/dialog recovery did not require a human decision")
        plans = payload.get("dialog_recovery_plans")
        if isinstance(plans, list) and any(
            isinstance(plan, dict) and plan.get("planned_action") for plan in plans
        ):
            excluded_reasons.append("dialog recovery planned an automatic action")
    elif state == "busy" and classification != "wait_or_human_intervention":
        excluded_reasons.append("busy recovery did not recommend wait or human intervention")
    elif state == "unknown" and classification != "unknown_state":
        excluded_reasons.append("unknown recovery did not preserve the unknown-state classification")

    return {
        "artifact": str(path),
        "task_id": task_id,
        "qualifies": not excluded_reasons,
        "excluded_reasons": excluded_reasons,
        "state": state or None,
        "active_dialog_count": dialog_count,
        "hung_window": hung_window,
        "is_revit_window": is_revit_window,
        "recommendation_classification": classification or None,
    }


def validate_recovery_drill_matrix(journal: TaskJournal) -> dict:
    """Validate recovery recommendations with synthetic states, without touching Revit."""

    drill_cases = [
        {
            "name": "modal-upgrade-dialog",
            "status": {"state": "modal"},
            "dialogs": {
                "dialogs": [
                    {
                        "title": "Upgrade model",
                        "text": "This model must be upgraded before it can be opened.",
                        "buttons": ["Upgrade", "Cancel"],
                    }
                ]
            },
            "expected_classification": "human_decision_required",
            "expected_known_dialog_id": "upgrade-model",
            "expected_safe_command": "revit-operator plan-current-dialog-response",
        },
        {
            "name": "busy-no-dialog",
            "status": {"state": "busy"},
            "dialogs": {"dialogs": []},
            "expected_classification": "wait_or_human_intervention",
            "expected_safe_command": "revit-operator wait-until-idle --timeout 120 --poll 2",
        },
        {
            "name": "idle-no-dialog",
            "status": {"state": "idle"},
            "dialogs": {"dialogs": []},
            "expected_classification": "safe_to_continue_read_only",
            "expected_safe_command": "revit-operator request-operation --operation active-document",
        },
        {
            "name": "revit-not-running",
            "status": {"state": "not_running"},
            "dialogs": {"dialogs": []},
            "expected_classification": "revit_not_running",
            "expected_safe_command": "revit-operator open-model --model <copied-local-model.rvt>",
        },
        {
            "name": "unknown-state",
            "status": {"state": "unknown"},
            "dialogs": {"dialogs": []},
            "expected_classification": "unknown_state",
            "expected_safe_command": "revit-operator status",
        },
    ]
    cases = []
    for case in drill_cases:
        dialog_plans = _dialog_recovery_plans(case["dialogs"])
        recommendation = _recommendation(case["status"], case["dialogs"], dialog_plans)
        safe_commands = [str(command) for command in recommendation.get("safe_commands") or []]
        known_dialog_ids = [str(value) for value in recommendation.get("known_dialog_ids") or []]
        checks = [
            _matrix_check(
                "classification_expected",
                recommendation.get("classification") == case["expected_classification"],
                "Recovery classification matched the expected conservative outcome.",
                (
                    "Expected classification "
                    f"{case['expected_classification']!r}, observed {recommendation.get('classification')!r}."
                ),
            ),
            _matrix_check(
                "safe_command_present",
                case["expected_safe_command"] in safe_commands,
                "Recovery recommendation includes the expected safe command.",
                f"Expected safe command {case['expected_safe_command']!r} was missing.",
            ),
            _matrix_check(
                "recommendation_has_next_step",
                bool(str(recommendation.get("next_step") or "").strip()),
                "Recovery recommendation includes a next step.",
                "Recovery recommendation is missing a next step.",
            ),
        ]
        expected_known = case.get("expected_known_dialog_id")
        if expected_known:
            checks.append(
                _matrix_check(
                    "known_dialog_id_expected",
                    expected_known in known_dialog_ids,
                    "Recovery recommendation preserves the expected known dialog id.",
                    f"Expected known dialog id {expected_known!r} was not preserved.",
                )
            )
            checks.append(
                _matrix_check(
                    "no_planned_action_for_high_risk_dialog",
                    all(plan.get("planned_action") is None for plan in dialog_plans),
                    "High-risk dialog drill produced no automatic planned action.",
                    "High-risk dialog drill produced an automatic planned action.",
                )
            )
        cases.append(
            {
                "name": case["name"],
                "success": all(check["passed"] for check in checks),
                "status": case["status"],
                "dialogs": case["dialogs"],
                "dialog_recovery_plans": dialog_plans,
                "recommendation": recommendation,
                "checks": checks,
            }
        )

    output = journal.run_dir / "recovery_drill_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "case_count": len(cases),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": "Synthetic recovery drill matrix only. No live Revit state was changed and no recovery action was executed.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "recovery-drill-matrix",
            "requested_action": {"case_count": len(cases)},
            "risk_classification": classify_action("recovery-drill-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only synthetic recovery validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def _dialog_recovery_plans(dialogs: dict) -> list[dict]:
    plans: list[dict] = []
    for index, dialog in enumerate(dialogs.get("dialogs") or []):
        if not isinstance(dialog, dict):
            continue
        plan = plan_dialog_response(
            title=str(dialog.get("title") or ""),
            text=str(dialog.get("dialog_text") or dialog.get("text") or ""),
            buttons=[str(button) for button in (dialog.get("buttons") or [])],
        )
        plans.append(
            {
                "index": index,
                "title": dialog.get("title"),
                "known_dialog_id": plan.get("known_dialog_id"),
                "risk": plan.get("classification", {}).get("risk"),
                "requires_human": plan.get("requires_human"),
                "planned_action": plan.get("planned_action"),
                "blocked_buttons": plan.get("blocked_buttons"),
                "approval_conditions": plan.get("approval_conditions"),
                "safe_preflight_commands": plan.get("safe_preflight_commands"),
                "reason": plan.get("reason"),
            }
        )
    return plans


def _recommendation(status: dict, dialogs: dict, dialog_plans: list[dict] | None = None) -> dict:
    state = status.get("state")
    dialog_count = len(dialogs.get("dialogs") or [])

    if dialog_count or state == "modal":
        known_ids = [
            str(plan.get("known_dialog_id"))
            for plan in (dialog_plans or [])
            if plan.get("known_dialog_id")
        ]
        return {
            "classification": "human_decision_required",
            "known_dialog_ids": known_ids,
            "next_step": "Inspect dialog_recovery_plans and ask the human before clicking or typing.",
            "safe_commands": [
                "revit-operator list-dialogs",
                "revit-operator plan-current-dialog-response",
                "revit-operator ui-tree",
                "revit-operator screenshot",
            ],
            "avoid": [
                "Do not click ambiguous dialog buttons.",
                "Do not save, sync, reload links, or close the model from a recovery state.",
            ],
        }

    if state == "busy":
        return {
            "classification": "wait_or_human_intervention",
            "next_step": "Wait briefly, capture another recovery snapshot, and escalate if the busy state persists.",
            "safe_commands": [
                "revit-operator wait-until-idle --timeout 120 --poll 2",
                "revit-operator recovery-snapshot",
            ],
            "avoid": ["Do not repeat failed clicks blindly."],
        }

    if state == "idle":
        return {
            "classification": "safe_to_continue_read_only",
            "next_step": "Continue with read-only bridge commands or a supervised workflow.",
            "safe_commands": [
                "revit-operator request-operation --operation active-document",
                "revit-operator qa-workflow",
            ],
            "avoid": ["Model writes still require explicit operation guards and approval."],
        }

    if state == "not_running":
        return {
            "classification": "revit_not_running",
            "next_step": "Open or attach to a copied local model before continuing.",
            "safe_commands": ["revit-operator open-model --model <copied-local-model.rvt>"],
            "avoid": ["Do not open production, cloud, central, or LucidLink paths."],
        }

    return {
        "classification": "unknown_state",
        "next_step": "Preserve evidence and ask the human to inspect Revit before further action.",
        "safe_commands": [
            "revit-operator status",
            "revit-operator list-windows",
            "revit-operator screenshot",
        ],
        "avoid": ["Do not perform model-changing actions from an unknown state."],
    }


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
