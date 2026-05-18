"""Optional Microsoft UI Automation inspection through pywinauto."""

from __future__ import annotations

import json
from collections.abc import Callable

from .journal import TaskJournal
from .safety import APPROVAL_REQUIRED, BLOCK, classify_action, validate_output_path
from .windows import RevitWindowObserver, is_windows


ALLOWED_UIA_ACTION_METHODS = {
    "auto",
    "invoke",
    "select",
    "expand",
    "collapse",
    "toggle",
    "click_input",
    "double_click_input",
    "right_click_input",
    "set_focus",
}


def validate_uia_method_matrix(journal: TaskJournal) -> dict:
    """Validate UIA invocation method policy without touching live UI."""

    cases = []
    for method in sorted(ALLOWED_UIA_ACTION_METHODS):
        safe_payload = {
            "name": "Synthetic non-destructive UIA control",
            "control_type": "Button",
            "exact": True,
            "method": method,
        }
        safe_policy = classify_action("uia-invoke", safe_payload).to_dict()
        safe_checks = [
            _uia_matrix_check(
                "method_allowlisted",
                method in ALLOWED_UIA_ACTION_METHODS,
                "Method is present in the UIA executor allowlist.",
                "Method is not present in the UIA executor allowlist.",
            ),
            _uia_matrix_check(
                "approval_required",
                safe_policy.get("decision") == APPROVAL_REQUIRED,
                "Safe synthetic UIA invocation requires explicit approval.",
                f"Expected approval_required, observed {safe_policy.get('decision')!r}.",
            ),
            _uia_matrix_check(
                "approval_token_present",
                str(safe_policy.get("approval_token") or "").startswith("APPROVE:"),
                "Approval-required UIA invocation exposes an exact token.",
                "Approval-required UIA invocation did not expose an exact token.",
            ),
            _uia_matrix_check(
                "nothing_executed",
                True,
                "Case is policy-only; no UIA control lookup or invocation was performed.",
                "Case unexpectedly executed.",
            ),
        ]
        cases.append(
            {
                "name": f"method-{method}-approval",
                "kind": "supported-method-policy",
                "success": all(check["passed"] for check in safe_checks),
                "action": "uia-invoke",
                "method": method,
                "payload": safe_payload,
                "policy": safe_policy,
                "executed": False,
                "checks": safe_checks,
            }
        )

        blocked_payload = {
            "name": "Save",
            "automation_id": "ID_Save_RibbonItemControl",
            "control_type": "Button",
            "exact": True,
            "method": method,
        }
        blocked_policy = classify_action("uia-invoke", blocked_payload).to_dict()
        blocked_checks = [
            _uia_matrix_check(
                "blocked_destructive_target",
                blocked_policy.get("decision") == BLOCK,
                "Destructive Save target is blocked before UIA invocation.",
                f"Expected block, observed {blocked_policy.get('decision')!r}.",
            ),
            _uia_matrix_check(
                "no_approval_token_for_blocked_target",
                blocked_policy.get("approval_token") is None,
                "Blocked UIA target does not expose an approval token.",
                "Blocked UIA target unexpectedly exposed an approval token.",
            ),
            _uia_matrix_check(
                "nothing_executed",
                True,
                "Case is policy-only; no UIA control lookup or invocation was performed.",
                "Case unexpectedly executed.",
            ),
        ]
        cases.append(
            {
                "name": f"method-{method}-save-blocked",
                "kind": "blocked-target-policy",
                "success": all(check["passed"] for check in blocked_checks),
                "action": "uia-invoke",
                "method": method,
                "payload": blocked_payload,
                "policy": blocked_policy,
                "executed": False,
                "checks": blocked_checks,
            }
        )

    unsupported_method = "__unsupported_uia_method__"
    unsupported_payload = {
        "name": "Synthetic non-destructive UIA control",
        "control_type": "Button",
        "exact": True,
        "method": unsupported_method,
    }
    unsupported_policy = classify_action("uia-invoke", unsupported_payload).to_dict()
    unsupported_checks = [
        _uia_matrix_check(
            "method_not_allowlisted",
            unsupported_method not in ALLOWED_UIA_ACTION_METHODS,
            "Unsupported method is not in the UIA executor allowlist.",
            "Unsupported method unexpectedly appears in the UIA executor allowlist.",
        ),
        _uia_matrix_check(
            "policy_still_requires_approval",
            unsupported_policy.get("decision") == APPROVAL_REQUIRED,
            "Unknown UIA method payload still requires approval before executor validation.",
            f"Expected approval_required, observed {unsupported_policy.get('decision')!r}.",
        ),
        _uia_matrix_check(
            "executor_rejects_before_uia_lookup",
            unsupported_method not in ALLOWED_UIA_ACTION_METHODS,
            "uia_invoke_control rejects unsupported methods before locating or invoking controls.",
            "Unsupported method would reach UIA lookup.",
        ),
        _uia_matrix_check(
            "nothing_executed",
            True,
            "Case is static/policy-only; no UIA control lookup or invocation was performed.",
            "Case unexpectedly executed.",
        ),
    ]
    cases.append(
        {
            "name": "unsupported-method-rejected",
            "kind": "unsupported-method-static-gate",
            "success": all(check["passed"] for check in unsupported_checks),
            "action": "uia-invoke",
            "method": unsupported_method,
            "payload": unsupported_payload,
            "policy": unsupported_policy,
            "executed": False,
            "checks": unsupported_checks,
        }
    )

    output = journal.run_dir / "uia_method_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "synthetic": True,
        "live_ui_touched": False,
        "method_count": len(ALLOWED_UIA_ACTION_METHODS),
        "supported_methods": sorted(ALLOWED_UIA_ACTION_METHODS),
        "case_count": len(cases),
        "approval_required_count": sum(
            1 for case in cases if case["policy"].get("decision") == APPROVAL_REQUIRED
        ),
        "blocked_count": sum(1 for case in cases if case["policy"].get("decision") == BLOCK),
        "executed_count": sum(1 for case in cases if case.get("executed")),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": (
            "Synthetic UIA method policy coverage only. No window was focused, "
            "no UIA tree was searched, and no UI control was invoked."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "uia-method-matrix",
            "requested_action": {"method_count": result["method_count"], "case_count": result["case_count"]},
            "risk_classification": classify_action("uia-method-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only synthetic UIA method policy validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
                "executed_count": result["executed_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def uia_tree(
    *,
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 500,
    desktop_factory: Callable[[], object] | None = None,
    observer: RevitWindowObserver | None = None,
) -> dict:
    """Return a UIA tree when optional pywinauto is available."""

    if not is_windows():
        return {
            "success": False,
            "supported": False,
            "dependency_missing": False,
            "error": "Microsoft UI Automation inspection is only available on win32.",
        }

    if desktop_factory is None:
        try:
            from pywinauto import Desktop
        except Exception as exc:
            return {
                "success": False,
                "supported": False,
                "dependency_missing": True,
                "dependency": "pywinauto",
                "error": f"pywinauto is required for UIA inspection: {exc}",
                "install_hint": "Install pywinauto in the Hermes environment to enable uia-tree.",
            }

        desktop_factory = lambda: Desktop(backend="uia")

    target_hwnd = hwnd or _default_revit_hwnd(observer)
    if not target_hwnd:
        return {
            "success": False,
            "supported": True,
            "dependency_missing": False,
            "error": "No visible Revit window found.",
        }

    try:
        root = desktop_factory().window(handle=target_hwnd)
        counter = {"count": 0}
        return {
            "success": True,
            "supported": True,
            "dependency_missing": False,
            "backend": "uia",
            "hwnd": target_hwnd,
            "max_depth": max_depth,
            "limit": limit,
            "tree": _control_node(root, depth=0, max_depth=max(0, max_depth), limit=max(0, limit), counter=counter),
            "node_count": counter["count"],
        }
    except Exception as exc:
        return {
            "success": False,
            "supported": True,
            "dependency_missing": False,
            "hwnd": target_hwnd,
            "error": f"UIA inspection failed: {type(exc).__name__}: {exc}",
        }


def uia_find_controls(
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 100,
    exact: bool = False,
    desktop_factory: Callable[[], object] | None = None,
    observer: RevitWindowObserver | None = None,
) -> dict:
    tree_result = uia_tree(
        hwnd=hwnd,
        max_depth=max_depth,
        limit=max(1, limit * 10),
        desktop_factory=desktop_factory,
        observer=observer,
    )
    if not tree_result.get("success"):
        return {**tree_result, "matches": [], "count": 0}

    matches = find_controls_in_uia_tree(
        tree_result.get("tree"),
        name=name,
        control_type=control_type,
        automation_id=automation_id,
        class_name=class_name,
        limit=max(0, limit),
        exact=exact,
    )
    return {
        "success": True,
        "supported": True,
        "backend": "uia",
        "hwnd": tree_result.get("hwnd"),
        "query": {
            "name": name,
            "control_type": control_type,
            "automation_id": automation_id,
            "class_name": class_name,
            "max_depth": max_depth,
            "limit": limit,
            "exact": exact,
        },
        "count": len(matches),
        "ambiguous": len(matches) > 1,
        "matches": matches,
    }


def uia_control_details(
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 100,
    exact: bool = False,
    desktop_factory: Callable[[], object] | None = None,
    observer: RevitWindowObserver | None = None,
) -> dict:
    """Return wrapper-level details for matching UIA controls without action."""

    if not is_windows():
        return {
            "success": False,
            "supported": False,
            "error": "Microsoft UI Automation details are only available on win32.",
        }

    desktop_result = _desktop_factory(desktop_factory)
    if desktop_result.get("error"):
        return desktop_result

    target_hwnd = hwnd or _default_revit_hwnd(observer)
    if not target_hwnd:
        return {"success": False, "supported": True, "error": "No visible Revit window found."}

    try:
        root = desktop_result["factory"]().window(handle=target_hwnd)
        matches = _find_wrapper_matches(
            root,
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            max_depth=max(0, max_depth),
            limit=max(0, limit),
            exact=exact,
        )
        summaries = [_wrapper_summary(match["control"], match["depth"], match["path"]) for match in matches]
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "hwnd": target_hwnd,
            "query": {
                "name": name,
                "control_type": control_type,
                "automation_id": automation_id,
                "class_name": class_name,
                "max_depth": max_depth,
                "limit": limit,
                "exact": exact,
            },
            "count": len(summaries),
            "ambiguous": len(summaries) > 1,
            "matches": summaries,
        }
    except Exception as exc:
        return {
            "success": False,
            "supported": True,
            "hwnd": target_hwnd,
            "error": f"UIA detail inspection failed: {type(exc).__name__}: {exc}",
        }


def uia_invoke_control(
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    hwnd: int | None = None,
    max_depth: int = 4,
    limit: int = 100,
    exact: bool = False,
    method: str = "auto",
    desktop_factory: Callable[[], object] | None = None,
    observer: RevitWindowObserver | None = None,
) -> dict:
    """Invoke one visible enabled UIA control with an approved method."""

    if not is_windows():
        return {
            "success": False,
            "supported": False,
            "error": "Microsoft UI Automation invocation is only available on win32.",
        }
    method = str(method or "auto").strip().lower()
    if method not in ALLOWED_UIA_ACTION_METHODS:
        return {
            "success": False,
            "supported": True,
            "error": f"Unsupported UIA action method {method!r}.",
            "allowed_methods": sorted(ALLOWED_UIA_ACTION_METHODS),
        }

    desktop_result = _desktop_factory(desktop_factory)
    if desktop_result.get("error"):
        return desktop_result

    target_hwnd = hwnd or _default_revit_hwnd(observer)
    if not target_hwnd:
        return {"success": False, "supported": True, "error": "No visible Revit window found."}

    try:
        root = desktop_result["factory"]().window(handle=target_hwnd)
        matches = _find_wrapper_matches(
            root,
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            max_depth=max(0, max_depth),
            limit=max(0, limit),
            exact=exact,
        )
        summaries = [_wrapper_summary(match["control"], match["depth"], match["path"]) for match in matches]
        if not summaries:
            return {
                "success": False,
                "supported": True,
                "hwnd": target_hwnd,
                "matches": [],
                "error": "No matching UIA control found.",
            }
        if len(summaries) > 1:
            return {
                "success": False,
                "supported": True,
                "hwnd": target_hwnd,
                "matches": summaries,
                "error": "Ambiguous UIA target; refine the query before invoking.",
            }
        selected = summaries[0]
        if selected.get("visible") is False or selected.get("enabled") is False:
            return {
                "success": False,
                "supported": True,
                "hwnd": target_hwnd,
                "matches": summaries,
                "error": "Matched UIA control is not visible and enabled.",
            }
        control = matches[0]["control"]
        execution = _run_uia_action_method(control, method)
        if not execution.get("success"):
            return {
                "success": False,
                "supported": True,
                "hwnd": target_hwnd,
                "matches": summaries,
                **execution,
            }
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "hwnd": target_hwnd,
            "method": execution.get("method"),
            "selected": selected,
        }
    except Exception as exc:
        return {
            "success": False,
            "supported": True,
            "hwnd": target_hwnd,
            "error": f"UIA invocation failed: {type(exc).__name__}: {exc}",
        }


def find_controls_in_uia_tree(
    tree: dict | None,
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    limit: int = 100,
    exact: bool = False,
) -> list[dict]:
    if not tree or limit == 0:
        return []

    queries = {
        "name": _norm(name),
        "control_type": _norm(control_type),
        "automation_id": _norm(automation_id),
        "class_name": _norm(class_name),
    }
    if not any(queries.values()):
        return []

    matches: list[dict] = []

    def visit(node: dict, depth: int, path: list[str]) -> None:
        if len(matches) >= limit:
            return
        next_path = [*path, str(node.get("name") or node.get("automation_id") or node.get("control_type") or "")]
        if all(
            _field_matches(str(node.get(field) or ""), query, exact)
            for field, query in queries.items()
            if query
        ):
            matches.append(
                {
                    "name": node.get("name"),
                    "control_type": node.get("control_type"),
                    "automation_id": node.get("automation_id"),
                    "class_name": node.get("class_name"),
                    "handle": node.get("handle"),
                    "enabled": node.get("enabled"),
                    "visible": node.get("visible"),
                    "depth": depth,
                    "path": " > ".join(part for part in next_path if part),
                }
            )
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, depth + 1, next_path)

    visit(tree, 0, [])
    return matches


def _desktop_factory(desktop_factory: Callable[[], object] | None) -> dict:
    if desktop_factory is not None:
        return {"factory": desktop_factory}
    try:
        from pywinauto import Desktop
    except Exception as exc:
        return {
            "success": False,
            "supported": False,
            "dependency_missing": True,
            "dependency": "pywinauto",
            "error": f"pywinauto is required for UIA operations: {exc}",
            "install_hint": "Install pywinauto in the Hermes environment to enable UIA actions.",
        }
    return {"factory": lambda: Desktop(backend="uia")}


def _find_wrapper_matches(
    control: object,
    *,
    name: str,
    control_type: str,
    automation_id: str,
    class_name: str,
    max_depth: int,
    limit: int,
    exact: bool,
) -> list[dict]:
    queries = {
        "name": _norm(name),
        "control_type": _norm(control_type),
        "automation_id": _norm(automation_id),
        "class_name": _norm(class_name),
    }
    if not any(queries.values()) or limit == 0:
        return []
    matches: list[dict] = []

    def visit(node: object, depth: int, path: list[str]) -> None:
        if len(matches) >= limit:
            return
        info = getattr(node, "element_info", None)
        values = {
            "name": str(_attr(info, "name") or ""),
            "control_type": str(_attr(info, "control_type") or ""),
            "automation_id": str(_attr(info, "automation_id") or ""),
            "class_name": str(_attr(info, "class_name") or ""),
        }
        next_path = [*path, values["name"] or values["automation_id"] or values["control_type"]]
        if all(
            _field_matches(values[field], query, exact)
            for field, query in queries.items()
            if query
        ):
            matches.append({"control": node, "depth": depth, "path": next_path})
        if depth >= max_depth:
            return
        try:
            children = node.children()
        except Exception:
            children = []
        for child in children:
            visit(child, depth + 1, next_path)

    visit(control, 0, [])
    return matches


def _wrapper_summary(control: object, depth: int, path: list[str]) -> dict:
    info = getattr(control, "element_info", None)
    return {
        "name": _attr(info, "name"),
        "control_type": _attr(info, "control_type"),
        "automation_id": _attr(info, "automation_id"),
        "class_name": _attr(info, "class_name"),
        "handle": _attr(info, "handle"),
        "enabled": _safe_call(control, "is_enabled"),
        "visible": _safe_call(control, "is_visible"),
        "available_methods": _available_uia_methods(control),
        "depth": depth,
        "path": " > ".join(part for part in path if part),
    }


def _available_uia_methods(control: object) -> list[str]:
    methods = []
    for name in sorted(ALLOWED_UIA_ACTION_METHODS - {"auto"}):
        if callable(getattr(control, name, None)):
            methods.append(name)
    return methods


def _run_uia_action_method(control: object, method: str) -> dict:
    methods = (
        ["invoke", "select", "click_input"]
        if method == "auto"
        else [method]
    )
    failures = []
    for candidate in methods:
        action = getattr(control, candidate, None)
        if not callable(action):
            failures.append({"method": candidate, "error": "Method is not available."})
            continue
        try:
            action()
            return {"success": True, "method": candidate}
        except Exception as exc:
            failures.append({"method": candidate, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "success": False,
        "method": method,
        "attempts": failures,
        "available_methods": _available_uia_methods(control),
        "error": "No UIA action method succeeded.",
    }


def _default_revit_hwnd(observer: RevitWindowObserver | None) -> int | None:
    observer = observer or RevitWindowObserver()
    status = observer.status()
    main = status.get("main_window") or {}
    if main.get("hwnd"):
        return int(main["hwnd"])
    dialogs = status.get("active_dialogs") or []
    if dialogs and dialogs[0].get("hwnd"):
        return int(dialogs[0]["hwnd"])
    return None


def _control_node(control: object, *, depth: int, max_depth: int, limit: int, counter: dict) -> dict:
    counter["count"] += 1
    info = getattr(control, "element_info", None)
    node = {
        "name": _attr(info, "name"),
        "control_type": _attr(info, "control_type"),
        "automation_id": _attr(info, "automation_id"),
        "class_name": _attr(info, "class_name"),
        "handle": _attr(info, "handle"),
        "enabled": _safe_call(control, "is_enabled"),
        "visible": _safe_call(control, "is_visible"),
        "children": [],
    }
    if depth >= max_depth or counter["count"] >= limit:
        return node
    try:
        children = control.children()
    except Exception:
        children = []
    for child in children:
        if counter["count"] >= limit:
            break
        node["children"].append(
            _control_node(child, depth=depth + 1, max_depth=max_depth, limit=limit, counter=counter)
        )
    return node


def _attr(obj: object, name: str) -> object:
    return getattr(obj, name, None) if obj is not None else None


def _safe_call(obj: object, name: str) -> object:
    method = getattr(obj, name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("&", "")


def _uia_matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }


def _field_matches(value: str, query: str, exact: bool) -> bool:
    value_norm = _norm(value)
    return value_norm == query if exact else query in value_norm
