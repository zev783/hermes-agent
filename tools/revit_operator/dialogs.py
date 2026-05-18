"""Reusable known-dialog rules for conservative Revit prompt handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class KnownDialogRule:
    id: str
    title_terms: tuple[str, ...]
    text_terms: tuple[str, ...]
    button_terms: tuple[str, ...]
    risk: str
    recommended_action: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title_terms": list(self.title_terms),
            "text_terms": list(self.text_terms),
            "button_terms": list(self.button_terms),
            "risk": self.risk,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
        }


KNOWN_DIALOG_RULES: tuple[KnownDialogRule, ...] = (
    KnownDialogRule(
        id="unsigned-addin",
        title_terms=("security", "unsigned"),
        text_terms=("add-in",),
        button_terms=(),
        risk="high",
        recommended_action="approve_if_expected_hermes_addin_after_signature_check",
        reason=(
            "Unsigned add-in prompt. Prefer signing/trusting the local Hermes add-in; "
            "approve only after the manifest and DLL path are verified."
        ),
    ),
    KnownDialogRule(
        id="pyrevit-loader-error",
        title_terms=("pyrevitloader", "error loading pyrevit"),
        text_terms=(),
        button_terms=("close",),
        risk="high",
        recommended_action="ask_human_close_if_pyRevit_is_not_needed_for_this_run",
        reason=(
            "pyRevit startup error blocks Revit. Closing the prompt is usually non-model-writing, "
            "but it changes startup state and should be approval-gated."
        ),
    ),
    KnownDialogRule(
        id="transmitted-model",
        title_terms=("transmitted model",),
        text_terms=(),
        button_terms=("temporarily",),
        risk="high",
        recommended_action="ask_human_choose_temporary_for_copied_local_model_only",
        reason=(
            "Transmitted model prompt can lead to central-model/save-as decisions. "
            "Use temporary mode only for copied local validation unless a human approves otherwise."
        ),
    ),
    KnownDialogRule(
        id="unresolved-references",
        title_terms=("unresolved references",),
        text_terms=(),
        button_terms=("manage links", "ignore"),
        risk="high",
        recommended_action="ask_human_ignore_or_review_links_without_reloading",
        reason=(
            "Unresolved references can lead to Manage Links and reload actions. "
            "Reloading links requires explicit approval."
        ),
    ),
    KnownDialogRule(
        id="missing-links",
        title_terms=(),
        text_terms=("link", "not found"),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason=(
            "Missing link prompts can lead to Manage Links, Browse, or reload/repath actions. "
            "Capture evidence and ask before changing link state."
        ),
    ),
    KnownDialogRule(
        id="upgrade-model",
        title_terms=(),
        text_terms=("upgrade", "model"),
        button_terms=("upgrade",),
        risk="high",
        recommended_action="ask_human",
        reason="Model upgrade is high risk and must be explicitly approved for copied local files only.",
    ),
    KnownDialogRule(
        id="detach-worksets",
        title_terms=(),
        text_terms=("detach", "workset"),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Detach and workset preservation choices affect model state and require human approval.",
    ),
    KnownDialogRule(
        id="open-worksets",
        title_terms=("open worksets",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Open Worksets choices can affect model load scope and require human approval.",
    ),
    KnownDialogRule(
        id="worksharing-central",
        title_terms=(),
        text_terms=("central model",),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Central/worksharing prompts can change local/central relationships and require human approval.",
    ),
    KnownDialogRule(
        id="manage-links",
        title_terms=("manage links",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Manage Links can reload, unload, repath, or otherwise affect linked resources.",
    ),
    KnownDialogRule(
        id="reload-links",
        title_terms=(),
        text_terms=("reload", "link"),
        button_terms=("reload",),
        risk="high",
        recommended_action="ask_human",
        reason="Link reloads can touch external files and require explicit approval.",
    ),
    KnownDialogRule(
        id="family-load-options",
        title_terms=(),
        text_terms=("family", "overwrite"),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Family load options can overwrite types or parameters and require human approval.",
    ),
    KnownDialogRule(
        id="type-catalog",
        title_terms=("type catalog",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Type catalog choices can load or change family types and require human approval.",
    ),
    KnownDialogRule(
        id="warning-review",
        title_terms=("warnings",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Warning review dialogs require human interpretation before accepting or dismissing actions.",
    ),
    KnownDialogRule(
        id="failure-processing",
        title_terms=(),
        text_terms=("failure",),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Failure processing dialogs can contain destructive resolution options and require human approval.",
    ),
    KnownDialogRule(
        id="warning-or-failure",
        title_terms=(),
        text_terms=("warning",),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Warnings and failure processing can hide destructive choices; treat as approval-required.",
    ),
    KnownDialogRule(
        id="visibility-graphics",
        title_terms=("visibility/graphics",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="Visibility/Graphics changes alter view presentation and require human approval.",
    ),
    KnownDialogRule(
        id="view-template",
        title_terms=("view template",),
        text_terms=(),
        button_terms=(),
        risk="high",
        recommended_action="ask_human",
        reason="View Template changes can affect many views and require human approval.",
    ),
    KnownDialogRule(
        id="save-changes",
        title_terms=(),
        text_terms=("save changes",),
        button_terms=(),
        risk="critical",
        recommended_action="ask_human",
        reason="Save/discard prompts are production-write or data-loss decisions and are blocked by default.",
    ),
    KnownDialogRule(
        id="export-output-path",
        title_terms=("export",),
        text_terms=(),
        button_terms=("save",),
        risk="high",
        recommended_action="ask_human",
        reason="Export dialogs can write files and must be constrained to the Hermes sandbox.",
    ),
    KnownDialogRule(
        id="print-export",
        title_terms=(),
        text_terms=("print",),
        button_terms=("export",),
        risk="high",
        recommended_action="ask_human",
        reason="Print/export workflows can write files and must stay inside the sandbox.",
    ),
)


def list_known_dialog_rules() -> list[dict]:
    return [rule.to_dict() for rule in KNOWN_DIALOG_RULES]


def match_known_dialog(
    title: str = "",
    text: str = "",
    buttons: Iterable[str] | None = None,
    extra_rules: Iterable[KnownDialogRule] | None = None,
) -> dict | None:
    title_norm = _norm(title)
    text_norm = _norm(text)
    buttons_norm = " ".join(_norm(button) for button in (buttons or []))
    combined = " ".join([title_norm, text_norm, buttons_norm])

    for rule in (*tuple(extra_rules or ()), *KNOWN_DIALOG_RULES):
        title_ok = _all_terms(rule.title_terms, title_norm or combined)
        text_ok = _all_terms(rule.text_terms, text_norm or combined)
        button_ok = _all_terms(rule.button_terms, buttons_norm or combined)
        if title_ok and text_ok and button_ok:
            return {
                "known_dialog_id": rule.id,
                "risk": rule.risk,
                "recommended_action": rule.recommended_action,
                "reason": rule.reason,
            }
    return None


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("&", "")


def _all_terms(terms: tuple[str, ...], haystack: str) -> bool:
    return all(_norm(term) in haystack for term in terms)
