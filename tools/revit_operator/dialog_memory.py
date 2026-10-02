"""Sandboxed learned dialog rules for Revit prompt recognition."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from .dialogs import KnownDialogRule, list_known_dialog_rules
from .journal import utc_now
from .safety import validate_output_path

CONSERVATIVE_RISKS = {"medium", "high", "critical"}


def list_dialog_rule_library(sandbox: Path) -> dict:
    learned = load_learned_dialog_rules(sandbox)
    return {
        "success": True,
        "built_in_count": len(list_known_dialog_rules()),
        "learned_count": len(learned),
        "built_in_rules": list_known_dialog_rules(),
        "learned_rules": [rule.to_dict() for rule in learned],
        "learned_library": str(_library_dir(sandbox)),
    }


def record_dialog_rule(
    sandbox: Path,
    *,
    rule_id: str,
    title_terms: Iterable[str] = (),
    text_terms: Iterable[str] = (),
    button_terms: Iterable[str] = (),
    risk: str = "high",
    recommended_action: str = "ask_human",
    reason: str = "",
) -> dict:
    safe_id = _safe_id(rule_id)
    if not safe_id:
        return {"success": False, "error": "Rule id is required."}
    risk_norm = risk.strip().lower()
    if risk_norm not in CONSERVATIVE_RISKS:
        return {
            "success": False,
            "error": "Learned dialog rules must be conservative: medium, high, or critical.",
        }
    title = _clean_terms(title_terms)
    text = _clean_terms(text_terms)
    buttons = _clean_terms(button_terms)
    if not (title or text or buttons):
        return {"success": False, "error": "At least one title/text/button term is required."}

    rule = {
        "id": safe_id,
        "title_terms": title,
        "text_terms": text,
        "button_terms": buttons,
        "risk": risk_norm,
        "recommended_action": recommended_action.strip() or "ask_human",
        "reason": reason.strip() or "Learned Revit dialog rule; escalate conservatively.",
        "created_at": utc_now(),
        "schema": "hermes-revit-learned-dialog-rule/v1",
    }
    target = _library_dir(sandbox) / f"{safe_id}.json"
    error = validate_output_path(target, sandbox)
    if error:
        return {"success": False, "error": error}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rule, indent=2, sort_keys=True), encoding="utf-8")
    return {"success": True, "path": str(target), "rule": rule}


def load_learned_dialog_rules(sandbox: Path) -> list[KnownDialogRule]:
    library = _library_dir(sandbox)
    if not library.exists():
        return []
    rules: list[KnownDialogRule] = []
    for path in sorted(library.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rule = _rule_from_dict(data)
        if rule:
            rules.append(rule)
    return rules


def _rule_from_dict(data: dict) -> KnownDialogRule | None:
    risk = str(data.get("risk") or "high").strip().lower()
    if risk not in CONSERVATIVE_RISKS:
        return None
    rule_id = _safe_id(str(data.get("id") or ""))
    if not rule_id:
        return None
    return KnownDialogRule(
        id=rule_id,
        title_terms=tuple(_clean_terms(data.get("title_terms") or [])),
        text_terms=tuple(_clean_terms(data.get("text_terms") or [])),
        button_terms=tuple(_clean_terms(data.get("button_terms") or [])),
        risk=risk,
        recommended_action=str(data.get("recommended_action") or "ask_human"),
        reason=str(data.get("reason") or "Learned Revit dialog rule; escalate conservatively."),
    )


def _library_dir(sandbox: Path) -> Path:
    return sandbox / "revit_operator_dialog_rules"


def _clean_terms(values: Iterable[object]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
