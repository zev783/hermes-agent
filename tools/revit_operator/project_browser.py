"""Read-only Project Browser observation helpers."""

from __future__ import annotations

import json

from .bridge import RevitBridgeClient
from .actions import ActionRequest, SafeActionExecutor
from .journal import TaskJournal, utc_now
from .navigation import find_views
from .ocr import ocr_screenshot
from .safety import BLOCK, classify_action, validate_output_path
from .uia import uia_find_controls, uia_tree
from .windows import RevitWindowObserver


def capture_project_browser_snapshot(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    search_depth: int = 8,
    tree_depth: int = 4,
    include_uia: bool = False,
    uia_limit: int = 300,
    include_ocr: bool = False,
    ocr_backend: str = "auto",
    ocr_func=ocr_screenshot,
    uia_tree_func=uia_tree,
) -> dict:
    """Locate and capture the visible Project Browser without interacting."""

    matches = observer.find_controls(
        text="Project Browser",
        max_depth=max(0, search_depth),
        limit=10,
    )
    if matches.get("error"):
        return {"success": False, "error": matches["error"], "matches": matches}

    project_browser_matches = [
        match for match in matches.get("matches", []) if match.get("hwnd")
    ]
    if not project_browser_matches:
        return {
            "success": False,
            "error": "No visible Project Browser control was found.",
            "matches": matches,
        }

    selected = project_browser_matches[0]
    hwnd = int(selected["hwnd"])
    ui_tree = observer.ui_tree(hwnd=hwnd, max_depth=max(0, tree_depth))
    uia = (
        uia_tree_func(hwnd=hwnd, max_depth=max(0, tree_depth), limit=max(0, uia_limit), observer=observer)
        if include_uia
        else {"skipped": True}
    )
    screenshot = observer.screenshot(journal.default_screenshot_path("bmp"), hwnd=hwnd)
    ocr = (
        ocr_func(journal, observer, hwnd=hwnd, backend=ocr_backend)
        if include_ocr
        else {"skipped": True}
    )

    output = journal.run_dir / "project_browser_snapshot.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    payload = {
        "captured_at": utc_now(),
        "selected_control": selected,
        "matches": matches,
        "ui_tree": ui_tree,
        "uia_tree": uia,
        "screenshot": screenshot,
        "ocr": ocr,
        "read_only": True,
        "note": (
            "Project Browser was observed only; no view activation, selection, "
            "coordinate clicking, or navigation was performed."
        ),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    output_files = [str(output)]
    if screenshot.get("path"):
        output_files.append(str(screenshot["path"]))
    if isinstance(ocr, dict) and ocr.get("path"):
        output_files.append(str(ocr["path"]))
    if isinstance(ocr, dict) and isinstance(ocr.get("screenshot"), dict) and ocr["screenshot"].get("path"):
        output_files.append(str(ocr["screenshot"]["path"]))
    ocr_lines = _ocr_lines(ocr)
    ocr_items = _ocr_items(ocr)

    return {
        "success": bool(screenshot.get("success")) and not bool(ui_tree.get("error")),
        "path": str(output),
        "selected_hwnd": hwnd,
        "match_count": len(project_browser_matches),
        "screenshot": screenshot,
        "ui_tree_supported": ui_tree.get("supported"),
        "uia_tree_supported": uia.get("supported") if isinstance(uia, dict) else None,
        "uia_node_count": uia.get("node_count") if isinstance(uia, dict) else None,
        "ocr_enabled": include_ocr,
        "ocr_success": ocr.get("success") if isinstance(ocr, dict) else None,
        "ocr_line_count": ocr.get("line_count") if isinstance(ocr, dict) else None,
        "ocr_lines": ocr_lines,
        "ocr_item_count": len(ocr_items),
        "ocr_items": ocr_items[:100],
        "output_files": sorted(set(output_files)),
    }


def plan_project_browser_navigation(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
    view_type: str = "",
    limit: int = 20,
    search_depth: int = 8,
    tree_depth: int = 4,
    include_uia: bool = False,
    uia_limit: int = 300,
    include_ocr: bool = False,
    ocr_backend: str = "auto",
    ocr_func=ocr_screenshot,
    uia_tree_func=uia_tree,
) -> dict:
    """Plan supervised Project Browser navigation without changing Revit state."""

    snapshot = capture_project_browser_snapshot(
        journal,
        observer,
        search_depth=search_depth,
        tree_depth=tree_depth,
        include_uia=include_uia,
        uia_limit=uia_limit,
        include_ocr=include_ocr,
        ocr_backend=ocr_backend,
        ocr_func=ocr_func,
        uia_tree_func=uia_tree_func,
    )
    view_lookup = find_views(
        journal,
        bridge,
        query=query,
        view_name=view_name,
        sheet_number=sheet_number,
        view_type=view_type,
        limit=max(0, limit),
    )
    visual_evidence = _project_browser_visual_evidence(
        snapshot,
        query=query,
        view_name=view_name,
        sheet_number=sheet_number,
    )
    route = _navigation_route(view_lookup, visual_evidence)

    output = journal.run_dir / "project_browser_navigation_plan.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    payload = {
        "captured_at": utc_now(),
        "read_only": True,
        "query": {
            "query": query,
            "view_name": view_name,
            "sheet_number": sheet_number,
            "view_type": view_type,
            "limit": limit,
        },
        "project_browser_snapshot": snapshot,
        "view_lookup": view_lookup,
        "visual_evidence": visual_evidence,
        "route": route,
        "note": (
            "This command plans navigation only. It does not click the Project "
            "Browser, change selection, activate a view, or modify the model."
        ),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    output_files = [str(output)]
    for result in [snapshot, view_lookup]:
        if isinstance(result, dict):
            for key in ["path"]:
                if result.get(key):
                    output_files.append(str(result[key]))
            for item in result.get("output_files") or []:
                output_files.append(str(item))

    return {
        "success": bool(snapshot.get("success")) or bool(view_lookup.get("success")),
        "path": str(output),
        "read_only": True,
        "route": route,
        "visual_evidence": visual_evidence,
        "project_browser_observed": bool(snapshot.get("success")),
        "view_lookup_count": view_lookup.get("count", 0) if isinstance(view_lookup, dict) else 0,
        "output_files": sorted(set(output_files)),
    }


def _navigation_route(view_lookup: dict, visual_evidence: dict | None = None) -> dict:
    visual_evidence = visual_evidence or {}
    if not view_lookup.get("success"):
        if visual_evidence.get("ocr_match_count", 0) > 0:
            return {
                "recommended_method": "ask_human",
                "reason": (
                    "OCR found possible visible Project Browser matches, but no metadata-backed "
                    "activation route was available."
                ),
                "next_step": "Review the Project Browser screenshot/OCR evidence before any UI action.",
                "visual_evidence": visual_evidence,
            }
        return {
            "recommended_method": "ask_human",
            "reason": view_lookup.get("error") or "No metadata-backed view lookup was available.",
            "next_step": "Export metadata, then rerun project-browser-plan-navigation.",
        }

    activation = view_lookup.get("activation") or {}
    if activation.get("available"):
        return {
            "recommended_method": "request-operation activate-view",
            "reason": (
                "A single metadata-backed sheet/view match exists. The guarded "
                "add-in route is more deterministic than clicking Project Browser rows."
            ),
            "operation": activation.get("operation"),
            "args": activation.get("args"),
            "approval_required": True,
            "next_step": activation.get("next_step"),
            "project_browser_clicking": "not_used_for_this_plan",
        }

    if view_lookup.get("ambiguous"):
        return {
            "recommended_method": "refine_query",
            "reason": "Multiple metadata-backed matches were found.",
            "next_step": "Rerun with a more specific sheet number, view name, or view type.",
        }

    if view_lookup.get("count", 0) == 0:
        if visual_evidence.get("ocr_match_count", 0) > 0:
            return {
                "recommended_method": "ask_human",
                "reason": (
                    "OCR found possible visible Project Browser matches, but metadata did not "
                    "produce a single safe activation target."
                ),
                "next_step": "Review OCR/screenshot evidence or refresh metadata before navigation.",
                "visual_evidence": visual_evidence,
            }
        return {
            "recommended_method": "ask_human",
            "reason": "No matching sheet/view was found in the metadata snapshot.",
            "next_step": "Inspect Project Browser evidence or refresh metadata before navigation.",
        }

    return {
        "recommended_method": "ask_human",
        "reason": activation.get("reason") or "The matched item is not safely activatable.",
        "next_step": "Review the metadata match and Project Browser evidence before any UI action.",
    }


def plan_project_browser_item_activation(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    exact: bool = False,
    search_depth: int = 8,
    max_depth: int = 8,
    limit: int = 50,
    method: str = "auto",
    uia_find_func=None,
) -> dict:
    """Plan direct Project Browser UIA activation without clicking."""

    browser = _project_browser_target(observer, search_depth=search_depth)
    output = journal.run_dir / "project_browser_item_activation_plan.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    if not browser.get("success"):
        result = {
            "success": False,
            "read_only": True,
            "error": browser.get("error"),
            "project_browser": browser,
            "path": str(output),
        }
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    payload = {
        "name": name,
        "control_type": control_type,
        "automation_id": automation_id,
        "class_name": class_name,
        "hwnd": browser["hwnd"],
        "max_depth": max_depth,
        "limit": limit,
        "exact": exact,
        "method": method,
        "project_browser_direct_activation": True,
    }
    payload = {key: value for key, value in payload.items() if value not in {"", None}}
    decision = classify_action("uia-invoke", payload)
    finder = uia_find_func or uia_find_controls
    matches = finder(
        name=payload.get("name", ""),
        control_type=payload.get("control_type", ""),
        automation_id=payload.get("automation_id", ""),
        class_name=payload.get("class_name", ""),
        hwnd=payload.get("hwnd"),
        max_depth=max(0, int(payload.get("max_depth", max_depth))),
        limit=max(0, int(payload.get("limit", limit))),
        exact=bool(payload.get("exact")),
        observer=observer,
    )
    executable = (
        decision.decision != BLOCK
        and matches.get("success", False)
        and matches.get("count") == 1
        and not matches.get("ambiguous")
        and _match_visible_enabled(matches.get("matches", [])[0])
    )
    result = {
        "success": bool(matches.get("success", False)),
        "read_only": True,
        "project_browser": browser,
        "query": {
            "name": name,
            "control_type": control_type,
            "automation_id": automation_id,
            "class_name": class_name,
            "exact": exact,
            "max_depth": max_depth,
            "limit": limit,
            "method": method,
        },
        "payload": payload,
        "policy": decision.to_dict(),
        "matches": matches.get("matches", []),
        "match_count": matches.get("count", 0),
        "ambiguous": matches.get("ambiguous", False),
        "executable": executable,
        "reason": (
            "Direct Project Browser activation requires exactly one visible enabled UIA target."
        ),
        "next_step": (
            "Run project-browser-activate-item with --execute and the exact approval token."
            if executable
            else "Refine the query or use metadata-backed project-browser-plan-navigation."
        ),
        "path": str(output),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "project-browser-plan-activation",
            "requested_action": payload,
            "risk_classification": result["policy"],
            "result": {
                "status": "planned",
                "success": result["success"],
                "executable": executable,
                "match_count": result["match_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def run_project_browser_item_activation(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    name: str = "",
    control_type: str = "",
    automation_id: str = "",
    class_name: str = "",
    exact: bool = False,
    search_depth: int = 8,
    max_depth: int = 8,
    limit: int = 50,
    method: str = "auto",
    dry_run: bool = True,
    approval_token: str | None = None,
    uia_find_func=None,
) -> dict:
    """Dry-run or execute direct Project Browser UIA activation."""

    plan = plan_project_browser_item_activation(
        journal,
        observer,
        name=name,
        control_type=control_type,
        automation_id=automation_id,
        class_name=class_name,
        exact=exact,
        search_depth=search_depth,
        max_depth=max_depth,
        limit=limit,
        method=method,
        uia_find_func=uia_find_func,
    )
    if not plan.get("success"):
        return {**plan, "dry_run": dry_run, "executed": False}
    if not plan.get("executable") and not dry_run:
        return {
            **plan,
            "dry_run": dry_run,
            "executed": False,
            "error": "Project Browser item activation must resolve to exactly one visible enabled target.",
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


def plan_project_browser_visual_activation(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    target_text: str = "",
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
    search_depth: int = 8,
    tree_depth: int = 4,
    include_uia: bool = False,
    uia_limit: int = 300,
    ocr_backend: str = "auto",
    ocr_func=ocr_screenshot,
    uia_tree_func=uia_tree,
) -> dict:
    """Plan one approval-gated visual click from Project Browser OCR geometry."""

    terms = [term for term in [target_text, sheet_number, view_name, query] if term and term.strip()]
    snapshot = capture_project_browser_snapshot(
        journal,
        observer,
        search_depth=search_depth,
        tree_depth=tree_depth,
        include_uia=include_uia,
        uia_limit=uia_limit,
        include_ocr=True,
        ocr_backend=ocr_backend,
        ocr_func=ocr_func,
        uia_tree_func=uia_tree_func,
    )
    visual_evidence = _project_browser_visual_evidence(
        snapshot,
        query=query or target_text,
        view_name=view_name,
        sheet_number=sheet_number,
    )
    matches = [
        match
        for match in visual_evidence.get("ocr_matches", [])
        if match.get("bounds") and match.get("source") == "ocr_item"
    ]
    payload = None
    reason = "Visual activation requires exactly one OCR item match with bounds."
    if not terms:
        reason = "Supply target text, sheet number, view name, or query before planning a visual click."
    elif not snapshot.get("success"):
        reason = snapshot.get("error") or "Project Browser could not be observed."
    elif len(matches) == 1:
        payload = _visual_click_payload(snapshot, matches[0])
        if payload:
            reason = (
                "A single OCR item match has screen coordinates. Execution remains "
                "approval-gated and should be used only when metadata/UIA routes are unavailable."
            )
        else:
            reason = "OCR item match exists, but screenshot window rect was unavailable."
    elif len(matches) > 1:
        reason = "Multiple OCR item matches have bounds; refine the target text before clicking."

    decision = classify_action("visual-click", payload or {"target_text": " ".join(terms)})
    executable = bool(payload) and len(matches) == 1 and decision.decision != BLOCK
    output = journal.run_dir / "project_browser_visual_activation_plan.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": bool(snapshot.get("success")) and bool(terms),
        "read_only": True,
        "project_browser_snapshot": snapshot,
        "visual_evidence": visual_evidence,
        "matches": matches,
        "match_count": len(matches),
        "payload": payload,
        "policy": decision.to_dict(),
        "executable": executable,
        "reason": reason,
        "next_step": (
            "Run project-browser-visual-activate with --execute and the exact approval token only if a human accepts the visual click."
            if executable
            else "Refine the target or use metadata-backed project-browser-plan-navigation."
        ),
        "path": str(output),
        "note": (
            "This is a visual fallback plan. OCR coordinates are evidence for a supervised "
            "mouse click; they are not an automatic Project Browser navigation route."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "project-browser-plan-visual-activation",
            "requested_action": {"terms": terms, "payload": payload},
            "risk_classification": result["policy"],
            "result": {
                "status": "planned",
                "success": result["success"],
                "executable": executable,
                "match_count": result["match_count"],
            },
            "output_files": [str(output), *snapshot.get("output_files", [])],
        }
    )
    return result


def run_project_browser_visual_activation(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    target_text: str = "",
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
    search_depth: int = 8,
    tree_depth: int = 4,
    include_uia: bool = False,
    uia_limit: int = 300,
    ocr_backend: str = "auto",
    dry_run: bool = True,
    approval_token: str | None = None,
    ocr_func=ocr_screenshot,
    uia_tree_func=uia_tree,
) -> dict:
    """Dry-run or execute an approval-gated Project Browser visual click."""

    plan = plan_project_browser_visual_activation(
        journal,
        observer,
        target_text=target_text,
        query=query,
        view_name=view_name,
        sheet_number=sheet_number,
        search_depth=search_depth,
        tree_depth=tree_depth,
        include_uia=include_uia,
        uia_limit=uia_limit,
        ocr_backend=ocr_backend,
        ocr_func=ocr_func,
        uia_tree_func=uia_tree_func,
    )
    payload = plan.get("payload")
    if not plan.get("executable") or not isinstance(payload, dict):
        return {**plan, "dry_run": dry_run, "executed": False}
    execution = SafeActionExecutor(observer, journal).run(
        ActionRequest(
            action="visual-click",
            payload=payload,
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


def _project_browser_target(observer: RevitWindowObserver, *, search_depth: int) -> dict:
    matches = observer.find_controls(
        text="Project Browser",
        max_depth=max(0, search_depth),
        limit=10,
    )
    if matches.get("error"):
        return {"success": False, "error": matches["error"], "matches": matches}
    project_browser_matches = [
        match for match in matches.get("matches", []) if match.get("hwnd")
    ]
    if not project_browser_matches:
        return {
            "success": False,
            "error": "No visible Project Browser control was found.",
            "matches": matches,
        }
    selected = project_browser_matches[0]
    return {"success": True, "hwnd": int(selected["hwnd"]), "selected_control": selected, "matches": matches}


def _visual_click_payload(snapshot: dict, match: dict) -> dict | None:
    screenshot = snapshot.get("screenshot") if isinstance(snapshot, dict) else None
    rect = screenshot.get("rect") if isinstance(screenshot, dict) else None
    bounds = match.get("bounds") if isinstance(match, dict) else None
    if not isinstance(rect, dict) or not isinstance(bounds, dict):
        return None
    left = _number_or_none(rect.get("left"))
    top = _number_or_none(rect.get("top"))
    center_x = _number_or_none(bounds.get("center_x"))
    center_y = _number_or_none(bounds.get("center_y"))
    if None in {left, top, center_x, center_y}:
        return None
    return {
        "hwnd": snapshot.get("selected_hwnd"),
        "target_text": match.get("text"),
        "coordinate_source": "project-browser-ocr",
        "window_x": center_x,
        "window_y": center_y,
        "screen_x": left + center_x,
        "screen_y": top + center_y,
        "match_source": match.get("source"),
    }


def _match_visible_enabled(match: dict) -> bool:
    return match.get("visible") is not False and match.get("enabled") is not False


def _ocr_lines(ocr: dict | None) -> list[str]:
    if not isinstance(ocr, dict):
        return []
    text = ocr.get("text")
    if not isinstance(text, str):
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _ocr_items(ocr: dict | None) -> list[dict]:
    if not isinstance(ocr, dict):
        return []
    items = ocr.get("items")
    if not isinstance(items, list):
        return []
    normalized = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        normalized_item = {
            "line_number": item.get("line_number") or index,
            "text": text.strip(),
        }
        for key in ("confidence", "bounds", "box"):
            if item.get(key) is not None:
                normalized_item[key] = item[key]
        normalized.append(normalized_item)
    return normalized


def _project_browser_visual_evidence(
    snapshot: dict,
    *,
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
) -> dict:
    lines = [line for line in snapshot.get("ocr_lines") or [] if isinstance(line, str) and line.strip()]
    items = [item for item in snapshot.get("ocr_items") or [] if isinstance(item, dict) and item.get("text")]
    terms = [term for term in [sheet_number, view_name, query] if term and term.strip()]
    matches = []
    for index, item in enumerate(items, start=1):
        text = str(item.get("text") or "")
        matched_terms = [term for term in terms if _text_contains_term(text, term)]
        if matched_terms:
            match = {
                "line_number": item.get("line_number") or index,
                "text": text,
                "matched_terms": matched_terms,
                "source": "ocr_item",
            }
            for key in ("confidence", "bounds", "box"):
                if item.get(key) is not None:
                    match[key] = item[key]
            matches.append(match)
    if not matches:
        for index, line in enumerate(lines, start=1):
            matched_terms = [term for term in terms if _text_contains_term(line, term)]
            if matched_terms:
                matches.append(
                    {
                        "line_number": index,
                        "text": line,
                        "matched_terms": matched_terms,
                        "source": "ocr_line",
                    }
                )
    return {
        "ocr_available": bool(lines or items),
        "ocr_line_count": len(lines),
        "ocr_item_count": len(items),
        "query_terms": terms,
        "ocr_match_count": len(matches),
        "ocr_matches": matches[:20],
        "read_only": True,
        "note": (
            "OCR evidence is for human-readable fallback inspection only; it is not "
            "a coordinate-click or direct activation route."
        ),
    }


def _text_contains_term(text: str, term: str) -> bool:
    haystack = _normalize_ocr_text(text)
    needle = _normalize_ocr_text(term)
    if not needle:
        return False
    if needle in haystack:
        return True
    return needle.replace(" ", "") in haystack.replace(" ", "")


def _normalize_ocr_text(value: str) -> str:
    return " ".join(str(value).casefold().replace("_", " ").replace("-", " ").split())


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
