"""Read-only Revit view/sheet lookup for supervised navigation."""

from __future__ import annotations

import json
from pathlib import Path

from .bridge import RevitBridgeClient
from .journal import TaskJournal
from .safety import validate_output_path


def find_views(
    journal: TaskJournal,
    bridge: RevitBridgeClient,
    *,
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
    view_type: str = "",
    limit: int = 20,
) -> dict:
    metadata_path = _metadata_path(journal, bridge)
    if not metadata_path:
        return {
            "success": False,
            "error": "No metadata snapshot available. Run export-metadata or qa-workflow first.",
        }
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    matches = find_view_matches(
        metadata,
        query=query,
        view_name=view_name,
        sheet_number=sheet_number,
        view_type=view_type,
        limit=max(0, limit),
    )

    output = journal.run_dir / "view_matches.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}
    result = {
        "success": True,
        "metadata_source": str(metadata_path),
        "query": {
            "query": query,
            "view_name": view_name,
            "sheet_number": sheet_number,
            "view_type": view_type,
            "limit": limit,
        },
        "count": len(matches),
        "ambiguous": len(matches) > 1,
        "matches": matches,
        "activation": _activation_hint(matches),
        "path": str(output),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def find_view_matches(
    metadata: dict,
    *,
    query: str = "",
    view_name: str = "",
    sheet_number: str = "",
    view_type: str = "",
    limit: int = 20,
) -> list[dict]:
    if limit == 0:
        return []
    query_norm = _norm(query)
    view_name_norm = _norm(view_name)
    sheet_number_norm = _norm(sheet_number)
    view_type_norm = _norm(view_type)
    matches: list[dict] = []

    def add(kind: str, item: dict) -> None:
        if len(matches) >= limit:
            return
        matches.append(
            {
                "kind": kind,
                "id": item.get("id"),
                "name": item.get("name"),
                "view_type": item.get("view_type") or ("DrawingSheet" if kind == "sheet" else None),
                "sheet_number": item.get("sheet_number"),
                "is_placeholder": item.get("is_placeholder"),
            }
        )

    for sheet in metadata.get("sheets") or []:
        haystack = " ".join(str(sheet.get(key) or "") for key in ["sheet_number", "name"])
        if _item_matches(
            haystack,
            query_norm=query_norm,
            name_norm=view_name_norm,
            sheet_number_norm=sheet_number_norm,
            item_name=str(sheet.get("name") or ""),
            item_sheet=str(sheet.get("sheet_number") or ""),
        ):
            add("sheet", sheet)

    for view in metadata.get("views") or []:
        haystack = " ".join(str(view.get(key) or "") for key in ["name", "view_type"])
        if view_type_norm and view_type_norm not in _norm(str(view.get("view_type") or "")):
            continue
        if _item_matches(
            haystack,
            query_norm=query_norm,
            name_norm=view_name_norm,
            sheet_number_norm=sheet_number_norm,
            item_name=str(view.get("name") or ""),
            item_sheet="",
        ):
            add("view", view)

    return matches


def _metadata_path(journal: TaskJournal, bridge: RevitBridgeClient) -> Path | None:
    if bridge.metadata_snapshot_path.exists():
        return bridge.metadata_snapshot_path
    candidates = sorted(journal.metadata_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def _activation_hint(matches: list[dict]) -> dict:
    if len(matches) != 1:
        return {
            "available": False,
            "reason": "Activation hint requires exactly one match.",
        }
    match = matches[0]
    if match.get("kind") == "sheet" and match.get("is_placeholder"):
        return {
            "available": False,
            "reason": "Placeholder sheets cannot be activated.",
        }
    args = {"id": match.get("id")}
    if match.get("kind") == "sheet":
        args["sheet_number"] = match.get("sheet_number")
    else:
        args["view_name"] = match.get("name")
    return {
        "available": True,
        "operation": "activate-view",
        "args": args,
        "approval_required": True,
        "next_step": "Dry-run request-operation --operation activate-view with this args-json, then execute only with the exact approval token.",
    }


def _item_matches(
    haystack: str,
    *,
    query_norm: str,
    name_norm: str,
    sheet_number_norm: str,
    item_name: str,
    item_sheet: str,
) -> bool:
    if query_norm and query_norm not in _norm(haystack):
        return False
    if name_norm and name_norm not in _norm(item_name):
        return False
    if sheet_number_norm and sheet_number_norm != _norm(item_sheet):
        return False
    return bool(query_norm or name_norm or sheet_number_norm)


def _norm(value: object) -> str:
    return str(value or "").strip().lower()
