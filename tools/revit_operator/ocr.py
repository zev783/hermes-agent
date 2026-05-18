"""Optional screenshot OCR fallback for inaccessible Revit UI surfaces."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .journal import TaskJournal, utc_now
from .safety import validate_output_path
from .windows import RevitWindowObserver


def ocr_screenshot(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    hwnd: int | None = None,
    backend: str = "auto",
    ocr_runner=None,
) -> dict:
    """Capture a screenshot and OCR it when optional dependencies are available."""

    screenshot = observer.screenshot(journal.default_screenshot_path("bmp"), hwnd=hwnd)
    output = journal.run_dir / "ocr_screenshot.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": False,
        "captured_at": utc_now(),
        "screenshot": screenshot,
        "text": "",
        "items": [],
        "item_count": 0,
        "backend": backend,
        "dependency_missing": False,
        "read_only": True,
        "path": str(output),
    }

    if not screenshot.get("success"):
        result["error"] = screenshot.get("error") or "Screenshot capture failed."
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    if ocr_runner is None:
        resolved = _resolve_ocr_runner(backend)
        dependency_error = resolved.get("error")
        if dependency_error:
            result.update(resolved)
            output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            return result
        ocr_runner = resolved["runner"]
        result["backend"] = resolved["backend"]
    else:
        result["backend"] = "injected"

    try:
        payload = _ocr_payload(ocr_runner(screenshot["path"]))
    except Exception as exc:
        result["error"] = f"OCR failed: {type(exc).__name__}: {exc}"
    else:
        text = payload["text"]
        items = payload["items"]
        result.update(
            {
                "success": True,
                "text": text,
                "items": items,
                "item_count": len(items),
                "text_length": len(text),
                "line_count": len([line for line in text.splitlines() if line.strip()]),
            }
        )

    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def ocr_health() -> dict:
    """Report OCR dependency readiness without capturing or OCRing anything."""

    rapidocr_package = "rapidocr_onnxruntime" if _has_module("rapidocr_onnxruntime") else "rapidocr"
    python_packages = {
        "Pillow": _has_module("PIL"),
        "pytesseract": _has_module("pytesseract"),
        "rapidocr_onnxruntime": _has_module("rapidocr_onnxruntime"),
        "rapidocr": _has_module("rapidocr"),
    }
    executable = _tesseract_executable()
    tesseract_missing = [
        name
        for name, present in {
            "Pillow": python_packages["Pillow"],
            "pytesseract": python_packages["pytesseract"],
        }.items()
        if not present
    ]
    if executable is None:
        tesseract_missing.append("Tesseract executable")
    rapidocr_ready = python_packages["rapidocr_onnxruntime"] or python_packages["rapidocr"]
    rapidocr_missing = [] if rapidocr_ready else ["rapidocr-onnxruntime or rapidocr"]
    backends = {
        "tesseract": {
            "ready": not tesseract_missing,
            "python_packages": {
                "Pillow": python_packages["Pillow"],
                "pytesseract": python_packages["pytesseract"],
            },
            "tesseract_executable": str(executable) if executable else None,
            "missing": tesseract_missing,
        },
        "rapidocr": {
            "ready": rapidocr_ready,
            "python_packages": {
                "rapidocr_onnxruntime": python_packages["rapidocr_onnxruntime"],
                "rapidocr": python_packages["rapidocr"],
            },
            "selected_package": rapidocr_package if rapidocr_ready else None,
            "missing": rapidocr_missing,
        },
    }
    ready = backends["tesseract"]["ready"] or backends["rapidocr"]["ready"]
    missing = [] if ready else sorted(set(tesseract_missing + rapidocr_missing))
    return {
        "success": True,
        "ready": ready,
        "preferred_backend": _preferred_backend(backends),
        "backends": backends,
        "python_packages": python_packages,
        "tesseract_executable": str(executable) if executable else None,
        "missing": missing,
        "install_hint": (
            "Install the revit-ocr Python extra. For the tesseract backend, also "
            "install a local Tesseract OCR executable and set HERMES_TESSERACT_CMD "
            "if tesseract.exe is not on PATH. The rapidocr backend is Python-package "
            "based and does not need a separate Tesseract executable."
        ),
    }


def _resolve_ocr_runner(backend: str) -> dict:
    backend = (backend or "auto").strip().lower()
    health = ocr_health()
    if backend not in {"auto", "tesseract", "rapidocr"}:
        return {
            "dependency_missing": False,
            "error": f"Unknown OCR backend: {backend}",
            "ocr_health": health,
        }

    if backend in {"auto", "tesseract"} and health["backends"]["tesseract"]["ready"]:
        from PIL import Image
        import pytesseract

        executable = health["backends"]["tesseract"].get("tesseract_executable")
        if executable:
            pytesseract.pytesseract.tesseract_cmd = executable
        return {
            "backend": "tesseract",
            "runner": lambda path: pytesseract.image_to_string(Image.open(path)),
        }

    if backend in {"auto", "rapidocr"} and health["backends"]["rapidocr"]["ready"]:
        return {
            "backend": "rapidocr",
            "runner": _rapidocr_result,
        }

    return _dependency_error(backend, health)


def _dependency_error(backend: str, health: dict) -> dict:
    requested = "any OCR backend" if backend == "auto" else f"{backend} OCR backend"
    missing = (
        list(health["missing"])
        if backend == "auto"
        else list(health["backends"].get(backend, {}).get("missing", health["missing"]))
    )
    return {
        "dependency_missing": True,
        "backend": backend,
        "dependencies": missing,
        "ocr_health": health,
        "error": f"OCR requires {requested} dependencies.",
        "install_hint": health["install_hint"],
    }


def _preferred_backend(backends: dict) -> str | None:
    if backends["tesseract"]["ready"]:
        return "tesseract"
    if backends["rapidocr"]["ready"]:
        return "rapidocr"
    return None


def _rapidocr_result(path: str | Path) -> object:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        from rapidocr import RapidOCR

    engine = RapidOCR()
    return engine(str(path))


def _rapidocr_text(path: str | Path) -> str:
    return _rapidocr_result_to_text(_rapidocr_result(path))


def _ocr_payload(result: object) -> dict:
    items = _ocr_result_to_items(result)
    text = _rapidocr_result_to_text(result)
    if not text and items:
        text = "\n".join(item["text"] for item in items if item.get("text"))
    return {
        "text": text,
        "items": _number_ocr_items(items),
    }


def _rapidocr_result_to_text(result: object) -> str:
    if result is None:
        return ""
    if hasattr(result, "txts"):
        return "\n".join(str(text) for text in getattr(result, "txts") or [])
    if isinstance(result, dict):
        for key in ("txts", "texts", "text", "items", "results", "data", "result"):
            if key in result:
                return _rapidocr_result_to_text(result[key])
        return ""
    if isinstance(result, tuple) and result:
        return _rapidocr_result_to_text(result[0])
    if isinstance(result, list):
        lines = []
        for item in result:
            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("txt") or item.get("content")
                if text:
                    lines.append(str(text))
            elif isinstance(item, (list, tuple)):
                if len(item) >= 2 and isinstance(item[1], str):
                    lines.append(item[1])
                elif len(item) >= 2 and isinstance(item[1], (list, tuple, dict)):
                    text = _rapidocr_result_to_text(item[1])
                    if text:
                        lines.extend(text.splitlines())
        return "\n".join(line for line in lines if line.strip())
    return str(result)


def _ocr_result_to_items(result: object) -> list[dict]:
    if result is None:
        return []
    if isinstance(result, str):
        return []
    if hasattr(result, "txts"):
        txts = getattr(result, "txts") or []
        boxes = getattr(result, "boxes", None) or getattr(result, "dt_boxes", None) or []
        scores = getattr(result, "scores", None) or getattr(result, "rec_scores", None) or []
        return _items_from_parallel(boxes, txts, scores)
    if isinstance(result, dict):
        direct = _item_from_mapping(result)
        if direct:
            return [direct]
        for key in ("items", "results", "data", "result", "txts", "texts"):
            if key in result:
                return _ocr_result_to_items(result[key])
        return []
    if isinstance(result, tuple) and result:
        return _ocr_result_to_items(result[0])
    if isinstance(result, list):
        items: list[dict] = []
        for entry in result:
            item = _item_from_entry(entry)
            if item:
                items.append(item)
                continue
            nested = _ocr_result_to_items(entry)
            items.extend(nested)
        return items
    return []


def _item_from_entry(entry: object) -> dict | None:
    if isinstance(entry, str):
        text = entry.strip()
        return {"text": text} if text else None
    if isinstance(entry, dict):
        return _item_from_mapping(entry)
    if not isinstance(entry, (list, tuple)) or not entry:
        return None
    if _looks_like_box(entry):
        return None

    if isinstance(entry[0], str):
        text = entry[0].strip()
        confidence = _number_or_none(entry[1]) if len(entry) > 1 else None
        return _clean_item({"text": text, "confidence": confidence})

    if len(entry) >= 2 and isinstance(entry[1], str):
        box = entry[0]
        confidence = _number_or_none(entry[2]) if len(entry) > 2 else None
        return _clean_item({"text": entry[1], "confidence": confidence, **_box_fields(box)})

    if len(entry) >= 2 and isinstance(entry[1], dict):
        nested = _item_from_mapping(entry[1])
        if nested:
            nested.update({key: value for key, value in _box_fields(entry[0]).items() if key not in nested})
            return _clean_item(nested)

    if len(entry) >= 2 and isinstance(entry[1], (list, tuple)):
        nested_text = _rapidocr_result_to_text(entry[1]).strip()
        confidence = _number_or_none(entry[2]) if len(entry) > 2 else None
        if nested_text:
            return _clean_item({"text": nested_text, "confidence": confidence, **_box_fields(entry[0])})
    return None


def _item_from_mapping(entry: dict) -> dict | None:
    text = entry.get("text") or entry.get("txt") or entry.get("content") or entry.get("label")
    if isinstance(text, (list, tuple)):
        text = "\n".join(str(item) for item in text if str(item).strip())
    if text is None:
        return None
    box = (
        entry.get("box")
        or entry.get("bbox")
        or entry.get("bounds")
        or entry.get("points")
        or entry.get("polygon")
    )
    confidence = (
        entry.get("confidence")
        if "confidence" in entry
        else entry.get("score", entry.get("probability", entry.get("prob")))
    )
    item = {
        "text": str(text),
        "confidence": _number_or_none(confidence),
        **_box_fields(box),
    }
    return _clean_item(item)


def _items_from_parallel(boxes: object, texts: object, scores: object) -> list[dict]:
    if not isinstance(texts, (list, tuple)):
        return []
    boxes_list = boxes if isinstance(boxes, (list, tuple)) else []
    scores_list = scores if isinstance(scores, (list, tuple)) else []
    items = []
    for index, text in enumerate(texts):
        box = boxes_list[index] if index < len(boxes_list) else None
        score = scores_list[index] if index < len(scores_list) else None
        items.append(_clean_item({"text": str(text), "confidence": _number_or_none(score), **_box_fields(box)}))
    return [item for item in items if item]


def _number_ocr_items(items: list[dict]) -> list[dict]:
    numbered = []
    for index, item in enumerate(items, start=1):
        clean = _clean_item(item)
        if not clean:
            continue
        clean.setdefault("line_number", index)
        numbered.append(clean)
    return numbered


def _clean_item(item: dict | None) -> dict | None:
    if not item:
        return None
    clean = {}
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    clean["text"] = text
    if item.get("confidence") is not None:
        clean["confidence"] = _number_or_none(item.get("confidence"))
    if item.get("box") is not None:
        clean["box"] = item["box"]
    if item.get("bounds") is not None:
        clean["bounds"] = item["bounds"]
    if item.get("line_number") is not None:
        clean["line_number"] = int(item["line_number"])
    return clean


def _box_fields(box: object) -> dict:
    normalized = _normalize_box(box)
    if not normalized:
        return {}
    bounds = _bounds_from_box(normalized)
    return {"box": normalized, "bounds": bounds} if bounds else {"box": normalized}


def _normalize_box(box: object) -> object | None:
    if box is None:
        return None
    if isinstance(box, dict):
        return {str(key): _json_number(value) for key, value in box.items()}
    if isinstance(box, (list, tuple)):
        return [_normalize_box(item) if isinstance(item, (list, tuple, dict)) else _json_number(item) for item in box]
    return None


def _bounds_from_box(box: object) -> dict | None:
    if isinstance(box, dict):
        if {"left", "top", "right", "bottom"}.issubset(box):
            left, top, right, bottom = (
                _number_or_none(box.get("left")),
                _number_or_none(box.get("top")),
                _number_or_none(box.get("right")),
                _number_or_none(box.get("bottom")),
            )
            return _bounds(left, top, right, bottom)
        if {"x", "y", "width", "height"}.issubset(box):
            left = _number_or_none(box.get("x"))
            top = _number_or_none(box.get("y"))
            width = _number_or_none(box.get("width"))
            height = _number_or_none(box.get("height"))
            if None in {left, top, width, height}:
                return None
            return _bounds(left, top, left + width, top + height)
        return None
    if not isinstance(box, list):
        return None
    points = []
    if _looks_like_box(box):
        for point in box:
            points.append((_number_or_none(point[0]), _number_or_none(point[1])))
    elif len(box) == 4 and all(_number_or_none(value) is not None for value in box):
        left, top, right, bottom = (_number_or_none(value) for value in box)
        if right < left or bottom < top:
            right = left + right
            bottom = top + bottom
        return _bounds(left, top, right, bottom)
    if not points:
        return None
    xs = [point[0] for point in points if point[0] is not None]
    ys = [point[1] for point in points if point[1] is not None]
    if not xs or not ys:
        return None
    return _bounds(min(xs), min(ys), max(xs), max(ys))


def _bounds(left: float | None, top: float | None, right: float | None, bottom: float | None) -> dict | None:
    if None in {left, top, right, bottom}:
        return None
    width = right - left
    height = bottom - top
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": width,
        "height": height,
        "center_x": left + width / 2,
        "center_y": top + height / 2,
    }


def _looks_like_box(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and _number_or_none(point[0]) is not None
            and _number_or_none(point[1]) is not None
            for point in value
        )
    )


def _json_number(value: object) -> object:
    number = _number_or_none(value)
    return number if number is not None else value


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_module(name: str) -> bool:
    try:
        __import__(name)
    except Exception:
        return False
    return True


def _tesseract_executable() -> Path | None:
    configured = os.environ.get("HERMES_TESSERACT_CMD")
    if configured and Path(configured).exists():
        return Path(configured)
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    for candidate in [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]:
        if candidate.exists():
            return candidate
    return None
