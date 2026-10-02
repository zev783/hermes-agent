"""Named, guarded Revit ribbon/menu action descriptors."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .actions import ActionRequest, SafeActionExecutor
from .journal import TaskJournal
from .safety import APPROVAL_REQUIRED, BLOCK, classify_action, validate_output_path
from .uia import uia_find_controls
from .windows import RevitWindowObserver


@dataclass(frozen=True)
class RibbonAction:
    name: str
    description: str
    control_name: str = ""
    automation_id: str = ""
    control_type: str = ""
    class_name: str = ""
    exact: bool = True
    max_depth: int = 5
    limit: int = 20
    blocked: bool = False
    reason: str = ""

    def payload(self, *, hwnd: int | None = None, max_depth: int | None = None, limit: int | None = None) -> dict:
        payload = {
            "name": self.control_name,
            "automation_id": self.automation_id,
            "control_type": self.control_type,
            "class_name": self.class_name,
            "max_depth": max_depth if max_depth is not None else self.max_depth,
            "limit": limit if limit is not None else self.limit,
            "exact": self.exact,
            "ribbon_action": self.name,
        }
        if hwnd:
            payload["hwnd"] = hwnd
        return {key: value for key, value in payload.items() if value not in {"", None}}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "control_name": self.control_name,
            "automation_id": self.automation_id,
            "control_type": self.control_type,
            "class_name": self.class_name,
            "exact": self.exact,
            "max_depth": self.max_depth,
            "limit": self.limit,
            "blocked": self.blocked,
            "reason": self.reason,
        }


RIBBON_ACTIONS: dict[str, RibbonAction] = {
    "architecture-tab": RibbonAction(
        name="architecture-tab",
        description="Activate the Revit Architecture ribbon tab for supervised visual/navigation workflows.",
        automation_id="Architecture",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "structure-tab": RibbonAction(
        name="structure-tab",
        description="Activate the Revit Structure ribbon tab for supervised structural workflows.",
        automation_id="Structure",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "systems-tab": RibbonAction(
        name="systems-tab",
        description="Activate the Revit Systems ribbon tab for supervised MEP/link inspection workflows.",
        automation_id="Systems",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "insert-tab": RibbonAction(
        name="insert-tab",
        description="Activate the Revit Insert ribbon tab for supervised link/import inspection workflows.",
        automation_id="Insert",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "annotate-tab": RibbonAction(
        name="annotate-tab",
        description="Activate the Revit Annotate ribbon tab for supervised tag/dimension/detail inspection workflows.",
        automation_id="Annotate",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "analyze-tab": RibbonAction(
        name="analyze-tab",
        description="Activate the Revit Analyze ribbon tab for supervised analysis-model inspection workflows.",
        automation_id="Analyze",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "collaborate-tab": RibbonAction(
        name="collaborate-tab",
        description="Activate the Revit Collaborate ribbon tab for supervised worksharing-state inspection.",
        automation_id="Collaborate",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "view-tab": RibbonAction(
        name="view-tab",
        description="Activate the Revit View ribbon tab for supervised visual/navigation workflows.",
        automation_id="View",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "manage-tab": RibbonAction(
        name="manage-tab",
        description="Activate the Revit Manage ribbon tab for supervised inspection workflows.",
        automation_id="Manage",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "add-ins-tab": RibbonAction(
        name="add-ins-tab",
        description="Activate the Revit Add-Ins ribbon tab for supervised add-in panel inspection.",
        automation_id="Add-Ins",
        reason="Changes UI focus only; still requires approval because add-in panels can expose model-changing commands.",
    ),
    "rtm-tab": RibbonAction(
        name="rtm-tab",
        description="Activate the RTM add-in ribbon tab for supervised local tool inspection.",
        automation_id="RTM",
        reason="Changes UI focus only; still requires approval because add-in panels can expose model-changing commands.",
    ),
    "modify-tab": RibbonAction(
        name="modify-tab",
        description="Activate the Revit Modify ribbon tab for supervised current-command inspection.",
        automation_id="Modify",
        reason="Changes UI focus only; still requires approval because it uses the visible UI.",
    ),
    "manage-links-command": RibbonAction(
        name="manage-links-command",
        description="Open the Manage Links command for supervised link inspection.",
        control_name="Manage Links",
        control_type="Button",
        exact=False,
        max_depth=8,
        limit=50,
        reason="Opens a high-risk link-management dialog; use only with approval and do not reload/repath/remove links by default.",
    ),
    "visibility-graphics-command": RibbonAction(
        name="visibility-graphics-command",
        description="Open Visibility/Graphics for supervised view-state inspection.",
        control_name="Visibility/Graphics",
        control_type="Button",
        exact=False,
        max_depth=8,
        limit=50,
        reason="Opens a view-graphics dialog; applying changes requires separate human approval.",
    ),
    "view-templates-command": RibbonAction(
        name="view-templates-command",
        description="Open View Templates for supervised template inspection.",
        control_name="View Templates",
        control_type="Button",
        exact=False,
        max_depth=8,
        limit=50,
        reason="Opens view-template tooling; assigning or modifying templates requires separate human approval.",
    ),
    "review-warnings-command": RibbonAction(
        name="review-warnings-command",
        description="Open Review Warnings for supervised warning inspection.",
        control_name="Review Warnings",
        control_type="Button",
        exact=False,
        max_depth=8,
        limit=50,
        reason="Opens warning review UI; resolving warnings remains human-only.",
    ),
    "project-information-command": RibbonAction(
        name="project-information-command",
        description="Open Project Information for supervised read-only inspection.",
        control_name="Project Information",
        control_type="Button",
        exact=False,
        max_depth=8,
        limit=50,
        reason="Opens project information UI; parameter edits remain blocked/approval-gated.",
    ),
    "file-menu": RibbonAction(
        name="file-menu",
        description="Revit File/backstage entry. Listed only so agents see that it is blocked.",
        automation_id="File",
        blocked=True,
        reason="File/backstage exposes Save, Print, Export, Publish, and other production-write surfaces.",
    ),
    "save": RibbonAction(
        name="save",
        description="Revit Save ribbon item. Listed only so agents see that it is blocked.",
        automation_id="ID_Save_RibbonItemControl",
        blocked=True,
        reason="Save is blocked by default. Use explicit request-operation guards only if ever approved.",
    ),
    "save-as": RibbonAction(
        name="save-as",
        description="Revit Save As command. Listed only so agents see that it is blocked.",
        control_name="Save As",
        blocked=True,
        reason="Save As is blocked by default because it can overwrite or create production files.",
    ),
    "synchronize-with-central": RibbonAction(
        name="synchronize-with-central",
        description="Synchronize with Central ribbon/menu command. Listed only so agents see that it is blocked.",
        automation_id="SynchronizeWithCentral",
        blocked=True,
        reason="Synchronize with Central is blocked by default and requires explicit guarded bridge operations.",
    ),
    "print": RibbonAction(
        name="print",
        description="Revit Print command. Listed only so agents see that it is blocked.",
        control_name="Print",
        blocked=True,
        reason="Print can write deliverables and must stay inside explicit sandboxed export workflows.",
    ),
    "export": RibbonAction(
        name="export",
        description="Revit Export command. Listed only so agents see that it is blocked.",
        control_name="Export",
        blocked=True,
        reason="Export can write files and must stay inside explicit sandboxed export workflows.",
    ),
    "publish": RibbonAction(
        name="publish",
        description="Revit Publish command. Listed only so agents see that it is blocked.",
        control_name="Publish",
        blocked=True,
        reason="Publish is blocked by default because it can write to cloud or production destinations.",
    ),
}


def list_ribbon_actions() -> dict:
    return {
        "success": True,
        "count": len(RIBBON_ACTIONS),
        "actions": [action.to_dict() for action in RIBBON_ACTIONS.values()],
    }


def validate_ribbon_action_matrix(journal: TaskJournal) -> dict:
    """Validate every named ribbon descriptor without touching the live UI."""

    cases = []
    for name, action in RIBBON_ACTIONS.items():
        payload = action.payload()
        decision = classify_action("uia-invoke", payload)
        has_locator = bool(
            action.control_name
            or action.automation_id
            or action.control_type
            or action.class_name
        )
        checks = [
            _matrix_check(
                "locator_present",
                has_locator,
                "Descriptor has at least one UIA locator field.",
                "Descriptor has no UIA locator field.",
            ),
            _matrix_check(
                "description_present",
                bool(action.description),
                "Descriptor has a description.",
                "Descriptor is missing a description.",
            ),
            _matrix_check(
                "reason_present",
                bool(action.reason),
                "Descriptor has a safety reason.",
                "Descriptor is missing a safety reason.",
            ),
        ]
        if action.blocked:
            checks.extend(
                [
                    _matrix_check(
                        "blocked_descriptor_flagged",
                        action.blocked,
                        "Descriptor is explicitly blocked.",
                        "Blocked descriptor is not flagged as blocked.",
                    ),
                    _matrix_check(
                        "blocked_descriptor_not_executable",
                        True,
                        "Blocked descriptors are non-executable even if UIA later finds a matching control.",
                        "Blocked descriptor could be executable.",
                    ),
                ]
            )
        else:
            checks.extend(
                [
                    _matrix_check(
                        "nonblocked_descriptor_requires_approval",
                        decision.decision == APPROVAL_REQUIRED,
                        "Non-blocked ribbon descriptor still requires exact UI approval.",
                        f"Expected approval_required, observed {decision.decision!r}.",
                    ),
                    _matrix_check(
                        "nonblocked_descriptor_not_policy_blocked",
                        decision.decision != BLOCK,
                        "Non-blocked descriptor is not blocked by generic policy terms.",
                        "Non-blocked descriptor is blocked by generic policy terms.",
                    ),
                ]
            )

        cases.append(
            {
                "name": name,
                "success": all(check["passed"] for check in checks),
                "blocked": action.blocked,
                "payload": payload,
                "policy": decision.to_dict(),
                "checks": checks,
                "note": (
                    "Static descriptor matrix only; live UIA resolution remains plan-ribbon-action/ribbon-action."
                ),
            }
        )

    output = journal.run_dir / "ribbon_action_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "case_count": len(cases),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "blocked_count": sum(1 for case in cases if case["blocked"]),
        "approval_gated_count": sum(
            1 for case in cases if case["policy"].get("decision") == APPROVAL_REQUIRED
        ),
        "cases": cases,
        "path": str(output),
        "note": "Descriptor matrix only. No ribbon control was located, clicked, invoked, or focused.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "ribbon-action-matrix",
            "requested_action": {"case_count": len(cases)},
            "risk_classification": classify_action("ribbon-action-matrix").to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only ribbon descriptor validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
                "blocked_count": result["blocked_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def plan_ribbon_action(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str,
    hwnd: int | None = None,
    max_depth: int | None = None,
    limit: int | None = None,
) -> dict:
    action = _resolve_action(name)
    if not action:
        return {"success": False, "error": f"Unknown ribbon action: {name}"}

    payload = action.payload(hwnd=hwnd, max_depth=max_depth, limit=limit)
    decision = classify_action("uia-invoke", payload)
    matches = uia_find_controls(
        name=payload.get("name", ""),
        automation_id=payload.get("automation_id", ""),
        control_type=payload.get("control_type", ""),
        class_name=payload.get("class_name", ""),
        hwnd=payload.get("hwnd"),
        max_depth=int(payload.get("max_depth", action.max_depth)),
        limit=int(payload.get("limit", action.limit)),
        exact=bool(payload.get("exact")),
        observer=observer,
    )
    result = {
        "success": matches.get("success", False),
        "action": action.to_dict(),
        "payload": payload,
        "policy": decision.to_dict(),
        "matches": matches.get("matches", []),
        "match_count": matches.get("count", 0),
        "ambiguous": matches.get("ambiguous", False),
        "blocked_by_descriptor": action.blocked,
        "executable": (
            not action.blocked
            and decision.decision != BLOCK
            and matches.get("success", False)
            and matches.get("count") == 1
        ),
        "reason": action.reason,
    }
    journal.write_entry(
        {
            "command": "plan-ribbon-action",
            "requested_action": {"name": name, "payload": payload},
            "risk_classification": result["policy"],
            "result": {
                "success": result["success"],
                "executable": result["executable"],
                "match_count": result["match_count"],
            },
        }
    )
    return result


def run_ribbon_action(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str,
    hwnd: int | None = None,
    max_depth: int | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict:
    plan = plan_ribbon_action(
        journal,
        observer,
        name=name,
        hwnd=hwnd,
        max_depth=max_depth,
        limit=limit,
    )
    if not plan.get("success"):
        return plan
    if plan.get("blocked_by_descriptor") or plan.get("policy", {}).get("decision") == BLOCK:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Ribbon action is blocked by policy or descriptor.",
        }
    if not plan.get("executable") and not dry_run:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Ribbon action must resolve to exactly one enabled target before execution.",
        }

    execution = SafeActionExecutor(observer, journal).run(
        ActionRequest(
            action="uia-invoke",
            payload=plan["payload"],
            dry_run=dry_run,
            approval_token=approval_token,
        )
    )
    return {
        **plan,
        "dry_run": dry_run,
        "execution": execution,
        "executed": bool(execution.get("executed")),
    }


def _resolve_action(name: str) -> RibbonAction | None:
    return RIBBON_ACTIONS.get(name.strip().lower())


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
