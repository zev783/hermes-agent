"""Guarded context-menu action descriptors for Revit UI workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .actions import ActionRequest, SafeActionExecutor
from .journal import TaskJournal
from .safety import APPROVAL_REQUIRED, BLOCK, classify_action, validate_output_path
from .uia import uia_find_controls
from .windows import RevitWindowObserver


@dataclass(frozen=True)
class ContextMenuAction:
    name: str
    description: str
    target_name: str = ""
    control_type: str = ""
    automation_id: str = ""
    class_name: str = ""
    exact: bool = True
    max_depth: int = 8
    limit: int = 50
    method: str = "right_click_input"
    blocked: bool = False
    requires_target: bool = True
    reason: str = ""

    def payload(
        self,
        *,
        target_name: str = "",
        control_type: str = "",
        automation_id: str = "",
        class_name: str = "",
        hwnd: int | None = None,
        max_depth: int | None = None,
        limit: int | None = None,
        exact: bool | None = None,
    ) -> dict:
        payload = {
            "name": target_name or self.target_name,
            "control_type": control_type or self.control_type,
            "automation_id": automation_id or self.automation_id,
            "class_name": class_name or self.class_name,
            "max_depth": max_depth if max_depth is not None else self.max_depth,
            "limit": limit if limit is not None else self.limit,
            "exact": self.exact if exact is None else exact,
            "method": self.method,
            "context_menu_action": self.name,
        }
        if hwnd:
            payload["hwnd"] = hwnd
        return {key: value for key, value in payload.items() if value not in {"", None}}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "target_name": self.target_name,
            "control_type": self.control_type,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "exact": self.exact,
            "max_depth": self.max_depth,
            "limit": self.limit,
            "method": self.method,
            "blocked": self.blocked,
            "requires_target": self.requires_target,
            "reason": self.reason,
        }


CONTEXT_MENU_ACTIONS: dict[str, ContextMenuAction] = {
    "project-browser-item-menu": ContextMenuAction(
        name="project-browser-item-menu",
        description="Open the context menu for one exact Project Browser item target.",
        control_type="TreeItem",
        max_depth=10,
        reason=(
            "Opening a context menu can change UI selection, so execution is "
            "approval-gated and must be followed by fresh observation."
        ),
    ),
    "visible-control-menu": ContextMenuAction(
        name="visible-control-menu",
        description="Open a context menu for one exact visible UIA target.",
        reason=(
            "Generic context-menu opening is high-risk because menu semantics "
            "depend on the active Revit state."
        ),
    ),
    "save-control-menu": ContextMenuAction(
        name="save-control-menu",
        description="Blocked descriptor for the Revit Save control context surface.",
        automation_id="ID_Save_RibbonItemControl",
        blocked=True,
        requires_target=False,
        reason="Save-related context surfaces are blocked by default.",
    ),
}


def list_context_menu_actions() -> dict:
    return {
        "success": True,
        "count": len(CONTEXT_MENU_ACTIONS),
        "actions": [action.to_dict() for action in CONTEXT_MENU_ACTIONS.values()],
    }


def validate_context_menu_action_matrix(journal: TaskJournal) -> dict:
    """Validate context-menu descriptors and representative item policies without live UI."""

    descriptor_cases = []
    for name, action in CONTEXT_MENU_ACTIONS.items():
        sample_target = "S2.0" if action.requires_target and not action.target_name else ""
        payload = action.payload(target_name=sample_target)
        decision = classify_action("uia-invoke", payload)
        has_locator = bool(
            payload.get("name")
            or payload.get("automation_id")
            or payload.get("class_name")
            or payload.get("control_type")
        )
        checks = [
            _matrix_check(
                "locator_present",
                has_locator,
                "Descriptor has a target locator or representative target binding.",
                "Descriptor has no target locator.",
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
            _matrix_check(
                "uses_right_click_input",
                action.method == "right_click_input",
                "Descriptor opens context menus through right_click_input.",
                f"Descriptor uses unexpected method {action.method!r}.",
            ),
        ]
        if action.blocked:
            checks.extend(
                [
                    _matrix_check(
                        "blocked_descriptor_flagged",
                        action.blocked,
                        "Descriptor is explicitly blocked.",
                        "Blocked descriptor is not marked blocked.",
                    ),
                    _matrix_check(
                        "blocked_descriptor_not_executable",
                        True,
                        "Blocked descriptor remains non-executable even if UIA later finds a target.",
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
                        "Non-blocked descriptor still requires exact UI approval.",
                        f"Expected approval_required, observed {decision.decision!r}.",
                    ),
                    _matrix_check(
                        "nonblocked_descriptor_requires_target",
                        action.requires_target,
                        "Descriptor requires an explicit target before live planning.",
                        "Generic non-blocked context-menu descriptor does not require a target.",
                    ),
                ]
            )

        descriptor_cases.append(
            {
                "name": name,
                "success": all(check["passed"] for check in checks),
                "blocked": action.blocked,
                "payload": payload,
                "policy": decision.to_dict(),
                "checks": checks,
            }
        )

    item_cases = []
    for item in ("Properties", "Delete", "Save", "Hide in View"):
        payload = {
            "name": item,
            "control_type": "MenuItem",
            "exact": True,
            "method": "invoke",
            "context_menu_item": item,
        }
        decision = classify_action("uia-invoke", payload)
        should_block = item in {"Delete", "Save"}
        checks = [
            _matrix_check(
                "item_policy_expected",
                (decision.decision == BLOCK) if should_block else (decision.decision == APPROVAL_REQUIRED),
                "Representative menu item has the expected safety policy.",
                f"Unexpected policy {decision.decision!r} for item {item!r}.",
            )
        ]
        item_cases.append(
            {
                "item": item,
                "success": all(check["passed"] for check in checks),
                "payload": payload,
                "policy": decision.to_dict(),
                "checks": checks,
            }
        )

    output = journal.run_dir / "context_menu_action_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in descriptor_cases + item_cases),
        "read_only": True,
        "descriptor_count": len(descriptor_cases),
        "item_case_count": len(item_cases),
        "failed_descriptors": [case["name"] for case in descriptor_cases if not case["success"]],
        "failed_items": [case["item"] for case in item_cases if not case["success"]],
        "blocked_descriptor_count": sum(1 for case in descriptor_cases if case["blocked"]),
        "approval_gated_descriptor_count": sum(
            1 for case in descriptor_cases if case["policy"].get("decision") == APPROVAL_REQUIRED
        ),
        "descriptor_cases": descriptor_cases,
        "item_cases": item_cases,
        "path": str(output),
        "note": "Static matrix only. No context menu was opened and no menu item was selected.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "context-menu-action-matrix",
            "requested_action": {
                "descriptor_count": len(descriptor_cases),
                "item_case_count": len(item_cases),
            },
            "risk_classification": classify_action("context-menu-action-matrix").to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only context-menu policy validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_descriptors": result["failed_descriptors"],
                "failed_items": result["failed_items"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def snapshot_context_menu(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 100,
) -> dict:
    """Capture visible UIA menu/menu-item evidence without choosing an item."""

    menu_items = uia_find_controls(
        control_type="MenuItem",
        hwnd=hwnd,
        max_depth=max(0, max_depth),
        limit=max(0, limit),
        exact=True,
        observer=observer,
    )
    menus = uia_find_controls(
        control_type="Menu",
        hwnd=hwnd,
        max_depth=max(0, max_depth),
        limit=max(0, limit),
        exact=True,
        observer=observer,
    )
    result = {
        "success": bool(menu_items.get("success") or menus.get("success")),
        "hwnd": hwnd,
        "menu_item_count": menu_items.get("count", 0),
        "menu_items": menu_items.get("matches", []),
        "menu_count": menus.get("count", 0),
        "menus": menus.get("matches", []),
        "item_query": _json_safe_query(menu_items.get("query")),
        "menu_query": _json_safe_query(menus.get("query")),
        "path": str(journal.run_dir / "context_menu_snapshot.json"),
        "note": (
            "Snapshot only. Selecting a menu item is a separate UIA action that "
            "must be classified and approved after this evidence is reviewed."
        ),
    }
    if not result["success"]:
        result["error"] = menu_items.get("error") or menus.get("error") or "No UIA menu evidence found."
    output = journal.run_dir / "context_menu_snapshot.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "context-menu-snapshot",
            "requested_action": {"hwnd": hwnd, "max_depth": max_depth, "limit": limit},
            "risk_classification": classify_action("context-menu-snapshot", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Observation command."},
            "result": {
                "success": result["success"],
                "menu_item_count": result["menu_item_count"],
                "menu_count": result["menu_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def plan_context_menu_action(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str,
    target_name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    hwnd: int | None = None,
    max_depth: int | None = None,
    limit: int | None = None,
    exact: bool | None = None,
) -> dict:
    action = _resolve_action(name)
    if not action:
        return {"success": False, "error": f"Unknown context-menu action: {name}"}

    payload = action.payload(
        target_name=target_name,
        control_type=control_type,
        automation_id=automation_id,
        class_name=class_name,
        hwnd=hwnd,
        max_depth=max_depth,
        limit=limit,
        exact=exact,
    )
    if action.requires_target and not _has_target_query(payload):
        return {
            "success": False,
            "action": action.to_dict(),
            "payload": payload,
            "error": "Context-menu actions require an exact target name, AutomationId, or class.",
        }

    decision = classify_action("uia-invoke", payload)
    matches = uia_find_controls(
        name=str(payload.get("name") or ""),
        control_type=str(payload.get("control_type") or ""),
        automation_id=str(payload.get("automation_id") or ""),
        class_name=str(payload.get("class_name") or ""),
        hwnd=payload.get("hwnd"),
        max_depth=int(payload.get("max_depth", action.max_depth)),
        limit=int(payload.get("limit", action.limit)),
        exact=bool(payload.get("exact", True)),
        observer=observer,
    )
    executable = (
        not action.blocked
        and decision.decision != BLOCK
        and matches.get("success", False)
        and matches.get("count") == 1
        and _match_is_enabled(matches.get("matches", [None])[0])
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
        "executable": executable,
        "reason": action.reason,
        "post_open_observation": [
            "status",
            "list-dialogs",
            "uia-tree or ui-tree for the active popup/menu",
        ],
        "note": (
            "This only plans opening a context menu. Selecting a menu item is a "
            "separate action that must be observed, classified, and approved."
        ),
    }
    journal.write_entry(
        {
            "command": "plan-context-menu-action",
            "requested_action": {"name": name, "payload": payload},
            "risk_classification": result["policy"],
            "approval_status": {"allowed": True, "reason": "Planning only."},
            "result": {
                "success": result["success"],
                "executable": result["executable"],
                "match_count": result["match_count"],
            },
        }
    )
    return result


def run_context_menu_action(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str,
    target_name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    hwnd: int | None = None,
    max_depth: int | None = None,
    limit: int | None = None,
    exact: bool | None = None,
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict:
    plan = plan_context_menu_action(
        journal,
        observer,
        name=name,
        target_name=target_name,
        control_type=control_type,
        automation_id=automation_id,
        class_name=class_name,
        hwnd=hwnd,
        max_depth=max_depth,
        limit=limit,
        exact=exact,
    )
    if not plan.get("success"):
        return plan
    if plan.get("blocked_by_descriptor") or plan.get("policy", {}).get("decision") == BLOCK:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Context-menu action is blocked by policy or descriptor.",
        }
    if not plan.get("executable") and not dry_run:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Context-menu action must resolve to exactly one enabled target before execution.",
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


def plan_context_menu_item(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    item: str,
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 50,
    method: str = "invoke",
) -> dict:
    item = item.strip()
    if not item:
        return {"success": False, "error": "Context-menu item name is required."}

    payload = {
        "name": item,
        "control_type": "MenuItem",
        "exact": True,
        "max_depth": max_depth,
        "limit": limit,
        "method": method,
        "context_menu_item": item,
    }
    if hwnd:
        payload["hwnd"] = hwnd

    decision = classify_action("uia-invoke", payload)
    matches = uia_find_controls(
        name=item,
        control_type="MenuItem",
        hwnd=hwnd,
        max_depth=max(0, max_depth),
        limit=max(0, limit),
        exact=True,
        observer=observer,
    )
    executable = (
        decision.decision != BLOCK
        and matches.get("success", False)
        and matches.get("count") == 1
        and _match_is_enabled(matches.get("matches", [None])[0])
    )
    result = {
        "success": matches.get("success", False),
        "payload": payload,
        "policy": decision.to_dict(),
        "matches": matches.get("matches", []),
        "match_count": matches.get("count", 0),
        "ambiguous": matches.get("ambiguous", False),
        "executable": executable,
        "note": (
            "Selecting a context-menu item may run a Revit command. Execute only "
            "after reviewing a fresh context-menu-snapshot and the exact approval token."
        ),
    }
    journal.write_entry(
        {
            "command": "plan-context-menu-item",
            "requested_action": payload,
            "risk_classification": result["policy"],
            "approval_status": {"allowed": True, "reason": "Planning only."},
            "result": {
                "success": result["success"],
                "executable": result["executable"],
                "match_count": result["match_count"],
            },
        }
    )
    return result


def run_context_menu_item(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    item: str,
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 50,
    method: str = "invoke",
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict:
    plan = plan_context_menu_item(
        journal,
        observer,
        item=item,
        hwnd=hwnd,
        max_depth=max_depth,
        limit=limit,
        method=method,
    )
    if not plan.get("success"):
        return plan
    if plan.get("policy", {}).get("decision") == BLOCK:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Context-menu item is blocked by policy.",
        }
    if not plan.get("executable") and not dry_run:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Context-menu item must resolve to exactly one enabled target before execution.",
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


def _resolve_action(name: str) -> ContextMenuAction | None:
    return CONTEXT_MENU_ACTIONS.get(name.strip().lower())


def _has_target_query(payload: dict) -> bool:
    return any(str(payload.get(key) or "").strip() for key in ("name", "automation_id", "class_name"))


def _match_is_enabled(match: object) -> bool:
    if not isinstance(match, dict):
        return False
    return match.get("enabled") is not False and match.get("visible") is not False


def _json_safe_query(query: object) -> dict | None:
    if not isinstance(query, dict):
        return None
    safe = {}
    for key, value in query.items():
        if key in {"desktop_factory", "observer"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
