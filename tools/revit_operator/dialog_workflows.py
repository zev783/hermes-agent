"""Conservative response playbooks for known Revit dialogs."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .journal import TaskJournal, utc_now
from .safety import APPROVAL_REQUIRED, classify_action, classify_dialog
from .safety import validate_output_path


@dataclass(frozen=True)
class DialogWorkflow:
    dialog_id: str
    summary: str
    recommended_action: str
    allowed_button: str | None = None
    requires_human_reason: str = ""
    safe_preflight_commands: tuple[str, ...] = (
        "revit-operator list-dialogs",
        "revit-operator screenshot",
        "revit-operator ui-tree",
    )
    blocked_buttons: tuple[str, ...] = ()
    approval_conditions: str = ""

    def to_dict(self) -> dict:
        return {
            "dialog_id": self.dialog_id,
            "summary": self.summary,
            "recommended_action": self.recommended_action,
            "allowed_button": self.allowed_button,
            "requires_human_reason": self.requires_human_reason,
            "safe_preflight_commands": list(self.safe_preflight_commands),
            "blocked_buttons": list(self.blocked_buttons),
            "approval_conditions": self.approval_conditions,
        }


DIALOG_WORKFLOWS: dict[str, DialogWorkflow] = {
    "unsigned-addin": DialogWorkflow(
        dialog_id="unsigned-addin",
        summary="Unsigned add-in prompt.",
        recommended_action="Prefer trust-addin and restart Revit. Click Load/Always Load only after verifying the Hermes DLL and manifest path.",
        allowed_button="Always Load",
        requires_human_reason="Unsigned add-in prompts can load arbitrary code.",
        safe_preflight_commands=(
            "revit-operator list-dialogs",
            "revit-operator screenshot",
            "revit-operator ui-tree",
            "revit-operator addin-security-preflight",
            "revit-operator trust-addin",
        ),
        blocked_buttons=("Load Once", "Do Not Load"),
        approval_conditions="Only approve Always Load after addin-security-preflight verifies the manifest and DLL path match the local Hermes operator add-in.",
    ),
    "unsigned-addin-unknown": DialogWorkflow(
        dialog_id="unsigned-addin-unknown",
        summary="Unsigned or unverified add-in prompt for an unknown add-in.",
        recommended_action="Do not load the add-in. Capture the dialog and ask the human to verify the publisher, DLL, and manifest path.",
        requires_human_reason="Unknown add-in prompts can load arbitrary code into Revit.",
        safe_preflight_commands=(
            "revit-operator list-dialogs",
            "revit-operator screenshot",
            "revit-operator ui-tree",
            "revit-operator addin-security-preflight",
        ),
        blocked_buttons=("Always Load", "Load Once", "Do Not Load"),
        approval_conditions="Only a human can decide whether an unknown add-in should load; no button is planned automatically.",
    ),
    "pyrevit-loader-error": DialogWorkflow(
        dialog_id="pyrevit-loader-error",
        summary="pyRevit loader error blocks startup.",
        recommended_action="If pyRevit is not needed for this run, dry-run click Close and execute only with approval.",
        allowed_button="Close",
        requires_human_reason="Closing changes startup state but should not modify model contents.",
        blocked_buttons=("Debug", "Open add-ins folder"),
    ),
    "transmitted-model": DialogWorkflow(
        dialog_id="transmitted-model",
        summary="Transmitted model prompt.",
        recommended_action="For copied local sandbox models, dry-run Work with this model temporarily and execute only with approval.",
        allowed_button="Work with this model temporarily",
        requires_human_reason="Other options may create/save a central model.",
        blocked_buttons=("Save this model as a Central Model",),
        approval_conditions="Only for the copied local sandbox model; never choose the central-model save option.",
    ),
    "unresolved-references": DialogWorkflow(
        dialog_id="unresolved-references",
        summary="Unresolved references prompt.",
        recommended_action="Prefer Ignore and continue opening the project unless the human explicitly approves link review/reload.",
        allowed_button="Ignore and continue opening the project",
        requires_human_reason="Manage Links or reload actions may touch external files.",
        blocked_buttons=("Manage Links", "Reload", "Browse"),
        approval_conditions="Ignore is acceptable only when the human agrees link reload/review is not needed for this read-only run.",
    ),
    "missing-links": DialogWorkflow(
        dialog_id="missing-links",
        summary="Missing link prompt.",
        recommended_action="Ask the human. Capture evidence and do not browse, reload, or repath links by default.",
        requires_human_reason="Missing link prompts can lead to external path changes or link reloads.",
        blocked_buttons=("Browse", "Reload", "Reload From", "Manage Links", "OK"),
        approval_conditions="Only approve a specific link action after the exact link name, source path, and sandbox/local boundary are confirmed.",
    ),
    "upgrade-model": DialogWorkflow(
        dialog_id="upgrade-model",
        summary="Model upgrade prompt.",
        recommended_action="Ask the human. Upgrade only copied local models with explicit approval.",
        requires_human_reason="Upgrade changes model format and can make files unusable in older Revit versions.",
        blocked_buttons=("Upgrade", "OK", "Continue"),
        approval_conditions="Only approve upgrade on copied local files inside the safe project area; never upgrade production, central, cloud, or LucidLink files.",
    ),
    "detach-worksets": DialogWorkflow(
        dialog_id="detach-worksets",
        summary="Detach/workset prompt.",
        recommended_action="Ask the human for detach/preserve/discard decision.",
        requires_human_reason="Detach/workset choices affect central relationship and model state.",
        blocked_buttons=("Detach", "Preserve Worksets", "Discard Worksets", "Open Worksets"),
        approval_conditions="Only proceed after the human states the intended detach/workset option for the copied local model.",
    ),
    "open-worksets": DialogWorkflow(
        dialog_id="open-worksets",
        summary="Open Worksets dialog.",
        recommended_action="Ask the human which worksets to open. Do not change workset load choices automatically.",
        requires_human_reason="Open Worksets choices affect model load scope and can hide or reveal production content.",
        blocked_buttons=("OK", "Open", "Close", "Check All", "Uncheck All"),
        approval_conditions="Only approve after the human gives the exact workset option or named worksets for this copied local model.",
    ),
    "worksharing-central": DialogWorkflow(
        dialog_id="worksharing-central",
        summary="Worksharing/central-model prompt.",
        recommended_action="Ask the human. Do not create, save, detach, or reconnect central/local relationships automatically.",
        requires_human_reason="Central/worksharing prompts can change model ownership, central relationship, or write destination.",
        blocked_buttons=("Create New Local", "Detach", "Save", "Save As", "OK", "Relinquish"),
        approval_conditions="Only proceed for copied local files after the human states the intended central/local action; never write to central, cloud, Autodesk Docs, LucidLink, or production paths.",
    ),
    "reload-links": DialogWorkflow(
        dialog_id="reload-links",
        summary="Reload links prompt.",
        recommended_action="Ask the human. Do not reload links by default.",
        requires_human_reason="Reloading can read/write external or production-linked resources.",
        blocked_buttons=("Reload", "Reload From", "Manage Links", "Browse"),
        approval_conditions="Only reload approved links from approved local/sandbox paths; never write to LucidLink, Autodesk Docs, cloud, central, or production paths.",
    ),
    "manage-links": DialogWorkflow(
        dialog_id="manage-links",
        summary="Manage Links dialog.",
        recommended_action="Ask the human. Capture dialog evidence and do not reload, unload, repath, or remove links by default.",
        requires_human_reason="Manage Links can touch external linked resources and can change project link state.",
        blocked_buttons=("Reload", "Reload From", "Unload", "Remove", "Add", "OK", "Apply", "Browse"),
        approval_conditions="Only approve a specific link action after the human identifies the exact link, source path, and copied/local safety boundary.",
    ),
    "family-load-options": DialogWorkflow(
        dialog_id="family-load-options",
        summary="Family load options prompt.",
        recommended_action="Ask the human. Do not overwrite family/type parameters by default.",
        requires_human_reason="Family load options can overwrite project content.",
        blocked_buttons=("Overwrite", "Overwrite existing version", "Overwrite parameter values"),
        approval_conditions="Only approve when the human has reviewed the family source and overwrite option.",
    ),
    "type-catalog": DialogWorkflow(
        dialog_id="type-catalog",
        summary="Type catalog selection dialog.",
        recommended_action="Ask the human to choose the exact family types. Do not select or load types automatically.",
        requires_human_reason="Type catalog choices can add or change families/types in the model.",
        blocked_buttons=("OK", "Load", "Open", "Select All"),
        approval_conditions="Only approve after the human provides the exact type names to load and confirms the family source is safe.",
    ),
    "warning-review": DialogWorkflow(
        dialog_id="warning-review",
        summary="Review Warnings dialog.",
        recommended_action="Capture warnings as evidence and ask the human before closing or exporting decisions.",
        requires_human_reason="Warnings need engineering judgment and can lead to model-changing cleanup actions.",
        blocked_buttons=("OK", "Close", "Show", "Export", "Delete Elements"),
        approval_conditions="Only close or act after the human confirms the warnings were reviewed or exported to a sandboxed draft report.",
    ),
    "failure-processing": DialogWorkflow(
        dialog_id="failure-processing",
        summary="Failure processing dialog.",
        recommended_action="Stop and ask the human. Capture screenshot, UI tree, and recovery snapshot before any button.",
        requires_human_reason="Failure dialogs can offer destructive automatic repairs.",
        blocked_buttons=("Delete Elements", "Remove Constraints", "Accept", "Continue", "OK"),
        approval_conditions="Only proceed after the human identifies the exact failure resolution and confirms it is safe for the copied local model.",
    ),
    "warning-or-failure": DialogWorkflow(
        dialog_id="warning-or-failure",
        summary="Warning/failure processing prompt.",
        recommended_action="Ask the human. Capture screenshot and UI tree before action.",
        requires_human_reason="Failure dialogs can hide destructive choices.",
        blocked_buttons=("Delete Elements", "Remove Constraints", "Accept", "OK", "Continue"),
        approval_conditions="Only continue after the human reviews the warning/failure text and the exact consequence of the selected button.",
    ),
    "visibility-graphics": DialogWorkflow(
        dialog_id="visibility-graphics",
        summary="Visibility/Graphics dialog.",
        recommended_action="Ask the human. Do not apply view graphics changes automatically.",
        requires_human_reason="Visibility/Graphics changes can alter view presentation and downstream sheet output.",
        blocked_buttons=("OK", "Apply", "Import", "Export"),
        approval_conditions="Only approve a specific change after the target view, category/filter, and intended display effect are identified.",
    ),
    "view-template": DialogWorkflow(
        dialog_id="view-template",
        summary="View Template dialog.",
        recommended_action="Ask the human. Do not assign, modify, or apply view templates automatically.",
        requires_human_reason="View Template changes can affect many views and sheet outputs.",
        blocked_buttons=("OK", "Apply", "Duplicate", "Delete", "Assign", "Manage"),
        approval_conditions="Only approve after the human identifies the exact template, target view set, and expected effect.",
    ),
    "save-changes": DialogWorkflow(
        dialog_id="save-changes",
        summary="Save changes prompt.",
        recommended_action="Stop and ask the human. Do not save, discard, or close automatically.",
        requires_human_reason="Save/discard choices can write production files or lose human/model changes.",
        blocked_buttons=("Save", "Save As", "Don't Save", "Discard", "Close without saving", "OK"),
        approval_conditions="Only approve a close/save/discard decision after the human confirms file path, model state, and whether data loss or production writes are acceptable.",
    ),
    "export-output-path": DialogWorkflow(
        dialog_id="export-output-path",
        summary="Export output path prompt.",
        recommended_action="Ask the human and verify every output path is inside the Hermes sandbox before continuing.",
        requires_human_reason="Export can overwrite or create deliverables outside the sandbox.",
        blocked_buttons=("Save", "Export", "OK", "Browse", "Options"),
        approval_conditions="Only approve when all output files are inside the sandbox and engineering output is labeled DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW.",
    ),
    "print-export": DialogWorkflow(
        dialog_id="print-export",
        summary="Print/export prompt.",
        recommended_action="Ask the human and verify output path is inside the sandbox.",
        requires_human_reason="Print/export can write files outside the sandbox.",
        blocked_buttons=("Print", "Export", "OK", "Save"),
        approval_conditions="Only approve if every output path is inside the Hermes sandbox and labeled draft/not for permit where applicable.",
    ),
}

DIALOG_WORKFLOW_SCENARIOS: dict[str, dict] = {
    "unsigned-addin": {
        "title": "Security - Unsigned Add-in",
        "text": "Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        "buttons": ["Always Load", "Load Once", "Do Not Load"],
    },
    "unsigned-addin-unknown": {
        "title": "Autodesk Revit",
        "text": "The publisher of this add-in could not be verified. Do you want to load this add-in?",
        "buttons": ["Always Load", "Load Once", "Do Not Load"],
    },
    "pyrevit-loader-error": {
        "title": "pyRevitLoader - Error Loading pyRevit",
        "text": "Error loading pyRevit.",
        "buttons": ["Close", "Debug"],
    },
    "transmitted-model": {
        "title": "Transmitted model",
        "text": "This model has been transmitted.",
        "buttons": ["Save this model as a Central Model", "Work with this model temporarily"],
    },
    "unresolved-references": {
        "title": "Unresolved References",
        "text": "One or more external references cannot be found.",
        "buttons": ["Manage Links", "Ignore and continue opening the project"],
    },
    "missing-links": {
        "title": "Autodesk Revit",
        "text": "The Revit link was not found.",
        "buttons": ["Browse", "Manage Links", "Ignore"],
    },
    "upgrade-model": {
        "title": "Upgrade model",
        "text": "This model must be upgraded before it can be opened.",
        "buttons": ["Cancel", "Upgrade"],
    },
    "detach-worksets": {
        "title": "Autodesk Revit",
        "text": "Detach this model from central and preserve worksets?",
        "buttons": ["Detach", "Preserve Worksets", "Discard Worksets", "Cancel"],
    },
    "open-worksets": {
        "title": "Open Worksets",
        "text": "Specify worksets to open.",
        "buttons": ["OK", "Check All", "Cancel"],
    },
    "worksharing-central": {
        "title": "Autodesk Revit",
        "text": "This central model requires a worksharing decision.",
        "buttons": ["Create New Local", "Detach", "Cancel"],
    },
    "reload-links": {
        "title": "Autodesk Revit",
        "text": "Reload this Revit link?",
        "buttons": ["Reload", "Cancel"],
    },
    "manage-links": {
        "title": "Manage Links",
        "text": "",
        "buttons": ["Reload From", "Unload", "OK", "Cancel"],
    },
    "family-load-options": {
        "title": "Autodesk Revit",
        "text": "Family already exists. Overwrite the existing version?",
        "buttons": ["Overwrite", "Cancel"],
    },
    "type-catalog": {
        "title": "Type Catalog",
        "text": "Select types to load.",
        "buttons": ["Select All", "OK", "Cancel"],
    },
    "warning-review": {
        "title": "Review Warnings",
        "text": "Warnings require review.",
        "buttons": ["Show", "Export", "Delete Elements", "Close"],
    },
    "failure-processing": {
        "title": "Autodesk Revit",
        "text": "Failure processing requires a resolution.",
        "buttons": ["Delete Elements", "Continue", "Cancel"],
    },
    "warning-or-failure": {
        "title": "Autodesk Revit",
        "text": "A warning requires a decision before continuing.",
        "buttons": ["OK", "Cancel"],
    },
    "visibility-graphics": {
        "title": "Visibility/Graphics Overrides",
        "text": "Model Categories",
        "buttons": ["OK", "Apply", "Cancel"],
    },
    "view-template": {
        "title": "View Template",
        "text": "Assign view template.",
        "buttons": ["OK", "Apply", "Cancel"],
    },
    "save-changes": {
        "title": "Autodesk Revit",
        "text": "Do you want to save changes?",
        "buttons": ["Save", "Don't Save", "Cancel"],
    },
    "export-output-path": {
        "title": "DWG Export",
        "text": "Choose output settings.",
        "buttons": ["Save", "Cancel"],
    },
    "print-export": {
        "title": "Autodesk Revit",
        "text": "Print selected sheets to file.",
        "buttons": ["Export", "Cancel"],
    },
}


def list_dialog_workflows() -> dict:
    return {
        "success": True,
        "count": len(DIALOG_WORKFLOWS),
        "workflows": [workflow.to_dict() for workflow in DIALOG_WORKFLOWS.values()],
    }


def validate_dialog_workflow_matrix(journal: TaskJournal) -> dict:
    """Exercise every known dialog workflow against a representative prompt."""

    cases = []
    for dialog_id, workflow in DIALOG_WORKFLOWS.items():
        scenario = DIALOG_WORKFLOW_SCENARIOS.get(dialog_id)
        if not scenario:
            cases.append(
                {
                    "dialog_id": dialog_id,
                    "success": False,
                    "checks": [
                        {
                            "name": "scenario_present",
                            "passed": False,
                            "reason": "No representative scenario is defined for this workflow.",
                        }
                    ],
                }
            )
            continue

        plan = plan_dialog_response(
            title=scenario.get("title", ""),
            text=scenario.get("text", ""),
            buttons=list(scenario.get("buttons") or []),
        )
        planned_action = plan.get("planned_action")
        planned_target = ""
        if isinstance(planned_action, dict):
            planned_target = str((planned_action.get("payload") or {}).get("target") or "")
        blocked_buttons = set(plan.get("blocked_buttons") or [])
        checks = [
            _matrix_check(
                "classified_expected_dialog",
                plan.get("known_dialog_id") == dialog_id,
                f"Scenario classified as {dialog_id}.",
                f"Scenario classified as {plan.get('known_dialog_id')!r}, expected {dialog_id!r}.",
            ),
            _matrix_check(
                "safe_preflight_present",
                bool(plan.get("safe_preflight_commands")),
                "Safe preflight commands are present.",
                "No safe preflight commands were returned.",
            ),
            _matrix_check(
                "planned_target_not_blocked",
                not planned_target or planned_target not in blocked_buttons,
                "No planned click targets a blocked button.",
                f"Planned click targets blocked button {planned_target!r}.",
            ),
        ]
        if workflow.allowed_button:
            checks.extend(
                [
                    _matrix_check(
                        "allowed_button_planned_when_available",
                        planned_target == workflow.allowed_button,
                        f"Allowed button {workflow.allowed_button!r} is planned.",
                        f"Expected allowed button {workflow.allowed_button!r}, observed {planned_target!r}.",
                    ),
                    _matrix_check(
                        "planned_click_requires_approval",
                        (planned_action or {}).get("policy", {}).get("decision") == APPROVAL_REQUIRED,
                        "Planned click requires exact approval.",
                        "Planned click does not require exact approval.",
                    ),
                ]
            )
        else:
            checks.append(
                _matrix_check(
                    "human_only_has_no_planned_action",
                    planned_action is None,
                    "Human-only workflow did not plan a click.",
                    "Human-only workflow unexpectedly planned an action.",
                )
            )

        cases.append(
            {
                "dialog_id": dialog_id,
                "success": all(check["passed"] for check in checks),
                "scenario": scenario,
                "checks": checks,
                "classification": plan.get("classification"),
                "planned_action": planned_action,
                "blocked_buttons": plan.get("blocked_buttons"),
                "approval_conditions": plan.get("approval_conditions"),
                "safe_preflight_commands": plan.get("safe_preflight_commands"),
            }
        )

    output = journal.run_dir / "dialog_workflow_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case.get("success") for case in cases),
        "read_only": True,
        "case_count": len(cases),
        "failed_cases": [case["dialog_id"] for case in cases if not case.get("success")],
        "cases": cases,
        "path": str(output),
        "note": "Representative prompt workflow matrix only; no live Revit dialog button was clicked.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "dialog-workflow-matrix",
            "requested_action": {"case_count": len(cases)},
            "risk_classification": classify_action("dialog-workflow-matrix").to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only representative prompt workflow validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def plan_dialog_response(
    *,
    title: str = "",
    text: str = "",
    buttons: list[str] | None = None,
) -> dict:
    classification = classify_dialog(title=title, text=text, buttons=buttons)
    dialog_id = classification.get("known_dialog_id")
    workflow = DIALOG_WORKFLOWS.get(str(dialog_id or ""))
    result = {
        "success": True,
        "classification": classification,
        "known_dialog_id": dialog_id,
        "workflow": workflow.to_dict() if workflow else None,
        "requires_human": True,
        "planned_action": None,
        "reason": "Unknown or unplanned dialog; ask human before interacting.",
        "safe_preflight_commands": [
            "revit-operator list-dialogs",
            "revit-operator screenshot",
            "revit-operator ui-tree",
        ],
        "blocked_buttons": [],
        "approval_conditions": "",
    }
    if not workflow:
        return result

    result["reason"] = workflow.requires_human_reason
    result["safe_preflight_commands"] = list(workflow.safe_preflight_commands)
    result["blocked_buttons"] = list(workflow.blocked_buttons)
    result["approval_conditions"] = workflow.approval_conditions
    if workflow.allowed_button and _button_available(workflow.allowed_button, buttons or []):
        payload = {"target": workflow.allowed_button}
        decision = classify_action("click", payload)
        result["planned_action"] = {
            "command": "click",
            "payload": payload,
            "dry_run_first": True,
            "policy": decision.to_dict(),
            "next_step": "Run click as a dry-run, then execute only with the exact approval token.",
        }
    return result


def plan_current_dialog_response(
    journal: TaskJournal,
    observer,
    *,
    title_contains: str = "",
    index: int = 0,
    use_ocr: bool = False,
    ocr_backend: str = "auto",
    ocr_func=None,
) -> dict:
    """Plan a response for the currently visible Revit dialog without clicking."""

    listing = observer.list_dialogs()
    dialogs = list(listing.get("dialogs") or [])
    title_filter = _norm(title_contains)
    matches = [
        dialog
        for dialog in dialogs
        if not title_filter or title_filter in _norm(dialog.get("title"))
    ]

    output = journal.run_dir / "current_dialog_response_plan.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    if not matches:
        modal_state = _observer_has_modal_state(observer)
        ocr = _ocr_fallback(
            journal,
            observer,
            hwnd=None,
            backend=ocr_backend,
            enabled=use_ocr,
            ocr_func=ocr_func,
        )
        plan = None
        reason = "No visible Revit dialog matched the request."
        if ocr and ocr.get("text") and modal_state:
            plan = plan_dialog_response(title=title_contains, text=str(ocr.get("text") or ""), buttons=[])
            reason = "No accessible Revit dialog matched, but modal state is active; OCR text was classified conservatively."
        elif ocr and ocr.get("text"):
            reason = "No modal Revit dialog matched; OCR evidence was captured but not classified as a prompt."
        result = {
            "success": True,
            "captured_at": utc_now(),
            "has_dialog": False,
            "dialog_count": len(dialogs),
            "title_filter": title_contains,
            "selected_dialog": None,
            "plan": plan,
            "ocr_fallback": ocr,
            "reason": reason,
            "path": str(output),
            "read_only": True,
        }
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    selected_index = max(0, min(index, len(matches) - 1))
    selected = matches[selected_index]
    ocr = _ocr_fallback(
        journal,
        observer,
        hwnd=int(selected.get("hwnd") or 0) or None,
        backend=ocr_backend,
        enabled=use_ocr and not str(selected.get("dialog_text") or "").strip(),
        ocr_func=ocr_func,
    )
    dialog_text = str(selected.get("dialog_text") or "")
    if not dialog_text.strip() and ocr:
        dialog_text = str(ocr.get("text") or "")
    plan = plan_dialog_response(
        title=str(selected.get("title") or ""),
        text=dialog_text,
        buttons=[str(button) for button in (selected.get("buttons") or [])],
    )
    result = {
        "success": True,
        "captured_at": utc_now(),
        "has_dialog": True,
        "dialog_count": len(dialogs),
        "match_count": len(matches),
        "selected_index": selected_index,
        "title_filter": title_contains,
        "selected_dialog": selected,
        "plan": plan,
        "ocr_fallback": ocr,
        "path": str(output),
        "read_only": True,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _observer_has_modal_state(observer) -> bool:
    try:
        status = observer.status()
    except Exception:
        return False
    if not isinstance(status, dict):
        return False
    state = str(status.get("state") or "").strip().lower()
    dialogs = status.get("active_dialogs") if isinstance(status.get("active_dialogs"), list) else []
    return state == "modal" or bool(dialogs)


def _ocr_fallback(
    journal: TaskJournal,
    observer,
    *,
    hwnd: int | None,
    backend: str,
    enabled: bool,
    ocr_func=None,
) -> dict | None:
    if not enabled:
        return None
    if ocr_func is not None:
        return ocr_func(journal, observer, hwnd=hwnd, backend=backend)
    from .ocr import ocr_screenshot

    return ocr_screenshot(journal, observer, hwnd=hwnd, backend=backend)


def _button_available(target: str, buttons: list[str]) -> bool:
    target_norm = _norm(target)
    return any(target_norm in _norm(button) or _norm(button) in target_norm for button in buttons)


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("&", "")


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
