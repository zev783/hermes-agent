"""Read-only Revit palette observation helpers."""

from __future__ import annotations

import json

from .journal import TaskJournal, utc_now
from .ocr import ocr_screenshot
from .safety import validate_output_path
from .uia import uia_tree
from .windows import RevitWindowObserver


def capture_properties_palette_snapshot(
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
    """Locate and capture the visible Properties palette without interacting."""

    matches = observer.find_controls(
        text="Properties",
        max_depth=max(0, search_depth),
        limit=20,
    )
    if matches.get("error"):
        return {"success": False, "error": matches["error"], "matches": matches}

    candidates = [match for match in matches.get("matches", []) if match.get("hwnd")]
    if not candidates:
        return {
            "success": False,
            "error": "No visible Properties palette control was found.",
            "matches": matches,
        }

    selected = _select_properties_palette_candidate(candidates)
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

    output = journal.run_dir / "properties_palette_snapshot.json"
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
            "Properties palette was observed only; no selection, parameter edit, "
            "typing, click, focus change, or model modification was performed."
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
        "match_count": len(candidates),
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
        "read_only": True,
    }


def _select_properties_palette_candidate(candidates: list[dict]) -> dict:
    exact_title = [
        candidate
        for candidate in candidates
        if str(candidate.get("title") or "").strip().casefold() == "properties"
    ]
    pool = exact_title or candidates
    return sorted(
        pool,
        key=lambda candidate: (
            int(candidate.get("depth", 99)),
            -int((candidate.get("rect") or {}).get("width", 0) or 0),
            -int((candidate.get("rect") or {}).get("height", 0) or 0),
        ),
    )[0]


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
