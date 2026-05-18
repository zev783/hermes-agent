"""Conservative safety policy for Revit UI/API operations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tools.path_security import validate_within_dir

from .constants import SAFE_PROJECT_ROOT
from .dialogs import match_known_dialog

Risk = str
Decision = str

LOW: Risk = "low"
MEDIUM: Risk = "medium"
HIGH: Risk = "high"
BLOCKED_RISK: Risk = "blocked"
CRITICAL: Risk = "critical"

ALLOW: Decision = "allow"
APPROVAL_REQUIRED: Decision = "approval_required"
BLOCK: Decision = "block"

OBSERVATION_ACTIONS = {
    "health",
    "north-star-status",
    "north-star-audit",
    "north-star-approval-plan",
    "north-star-approval-preflight",
    "north-star-ready-approvals",
    "north-star-next-approval",
    "north-star-waiting-state",
    "north-star-approval-phrase-verify",
    "north-star-approved-execution-preview",
    "north-star-approval-verify",
    "north-star-watch",
    "north-star-resume-check",
    "north-star-human-gate-packet",
    "north-star-next-human-action",
    "north-star-human-unblock-brief",
    "north-star-agent-stop-status",
    "north-star-completion-gate",
    "north-star-blocked-ledger",
    "north-star-current-handoff",
    "north-star-refresh-sequence",
    "north-star-stable-artifact-scan",
    "north-star-unblock-readiness",
    "transport-safety-matrix",
    "serve",
    "status",
    "list-processes",
    "list-revit-installs",
    "list-windows",
    "list-dialogs",
    "known-dialogs",
    "classify-dialog",
    "dialog-rule-library",
    "record-dialog-rule",
    "dialog-workflows",
    "dialog-workflow-matrix",
    "plan-dialog-response",
    "plan-current-dialog-response",
    "screenshot",
    "ocr-screenshot",
    "ocr-health",
    "addin-security-preflight",
    "ui-tree",
    "uia-tree",
    "uia-find-control",
    "uia-control-details",
    "uia-method-matrix",
    "find-control",
    "project-browser-snapshot",
    "project-browser-plan-navigation",
    "project-browser-plan-activation",
    "project-browser-plan-visual-activation",
    "properties-palette-snapshot",
    "find-view",
    "ribbon-actions",
    "ribbon-action-matrix",
    "plan-ribbon-action",
    "context-menu-actions",
    "context-menu-action-matrix",
    "context-menu-snapshot",
    "plan-context-menu-action",
    "plan-context-menu-item",
    "action-approval-matrix",
    "ui-execution-coverage-audit",
    "wait-for-window",
    "wait-for-dialog",
    "wait-until-idle",
    "wait-model-ready",
    "task-log",
    "bridge-status",
    "bridge-readiness",
    "bridge-restart-validation-plan",
    "bridge-post-restart-validation",
    "bridge-results",
    "wait-bridge-result",
    "recovery-snapshot",
    "recovery-drill-matrix",
    "agent-task",
    "agent-session-plan",
    "agent-session-run",
    "agent-session-checkpoint",
    "agent-session-resume-plan",
    "agent-session-completion-audit",
    "agent-session-real-gate-ledger",
    "agent-session-evidence-refresh",
    "agent-session-supervision-status",
    "agent-ui-flow-scout",
    "agent-ui-flow-approval-plan",
    "agent-model-open-prompt-approval-plan",
    "agent-session-approval-plan",
    "agent-session-execute-approved-item",
    "supervise-session",
    "supervision-endurance-matrix",
    "supervision-endurance-audit",
    "workflow-library",
    "ui-workflows",
    "ui-workflow-matrix",
    "ui-workflow-smoke-matrix",
    "plan-ui-workflow",
    "record-workflow",
    "plan-workflow",
    "workflow-approval-plan",
    "export-metadata",
    "qa-report",
    "qa-workflow",
    "verify-bridge-build",
}

CRITICAL_OPERATIONS = {
    "open-model",
    "save",
    "sync",
    "synchronize-with-central",
    "detach",
    "upgrade",
    "reload-links",
    "close-model",
    "modify-model",
    "set-project-info-parameter",
    "activate-view",
}

READ_ONLY_BRIDGE_OPERATIONS = {
    "active-document",
    "export-metadata",
    "qa-snapshot",
}

READ_ONLY_SAFE_COMMANDS = READ_ONLY_BRIDGE_OPERATIONS

BLOCKED_TERMS = [
    "save",
    "save as",
    "synchronize",
    "sync with central",
    "synchronize with central",
    "relinquish",
    "publish",
    "overwrite",
    "delete",
    "discard changes",
    "autodesk docs",
    "lucidlink",
    "central model",
]

APPROVAL_TERMS = [
    "upgrade",
    "detach",
    "workset",
    "central",
    "reload",
    "link",
    "family",
    "type catalog",
    "warning",
    "failure",
    "manage links",
    "visibility/graphics",
    "view template",
    "print",
    "export",
    "close",
    "modify",
    "selection",
    "macro",
    "add-in",
]

INFORMATIONAL_TERMS = [
    "information",
    "completed",
    "finished",
    "nothing to do",
    "already up to date",
]

UNSIGNED_ADDIN_MARKERS = [
    "unsigned",
    "publisher could not be verified",
    "publisher cannot be verified",
    "cannot verify the publisher",
    "unknown publisher",
]

ADDIN_PROMPT_MARKERS = [
    "add-in",
    "addin",
    "external application",
]

ADDIN_LOAD_BUTTON_MARKERS = [
    "always load",
    "load once",
    "do not load",
]

HERMES_ADDIN_MARKERS = [
    "hermes revit operator",
    "hermesrevitoperator",
    "hermesrevitoperator.dll",
]


@dataclass(frozen=True)
class SafetyDecision:
    action: str
    risk: Risk
    decision: Decision
    reason: str
    approval_token: str | None = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "risk": self.risk,
            "decision": self.decision,
            "reason": self.reason,
            "approval_token": self.approval_token,
        }


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _contains_any(haystack: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in haystack]


def _looks_like_unsigned_addin_prompt(combined: str) -> bool:
    addin_context = bool(_contains_any(combined, ADDIN_PROMPT_MARKERS))
    unsigned_context = bool(_contains_any(combined, UNSIGNED_ADDIN_MARKERS))
    load_prompt_context = "load" in combined and bool(
        _contains_any(combined, ADDIN_LOAD_BUTTON_MARKERS)
    )
    return addin_context and (unsigned_context or load_prompt_context)


def _is_expected_hermes_addin_prompt(combined: str) -> bool:
    return bool(_contains_any(combined, HERMES_ADDIN_MARKERS))


def approval_token_for(action: str, payload: dict | None = None) -> str:
    """Create an exact-action approval token for supervised execution.

    This is not a security boundary.  It is a guardrail that binds a human
    approval to a concrete action payload and prevents accidental execution of
    a different click/key/type command.
    """

    canonical = json.dumps(
        {"action": action, "payload": payload or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"APPROVE:{digest}"


def classify_dialog(
    title: str = "",
    text: str = "",
    buttons: Iterable[str] | None = None,
    extra_rules: Iterable | None = None,
) -> dict:
    """Classify a Revit dialog from its visible title, text, and buttons."""

    button_list = [str(button) for button in (buttons or []) if str(button)]
    combined = " ".join([title, text, " ".join(button_list)]).lower()

    if _looks_like_unsigned_addin_prompt(combined):
        expected = _is_expected_hermes_addin_prompt(combined)
        return {
            "known_dialog_id": "unsigned-addin" if expected else "unsigned-addin-unknown",
            "has_modal_dialog": True,
            "dialog_title": title,
            "dialog_text": text,
            "buttons": button_list,
            "risk": HIGH,
            "recommended_action": (
                "approve_if_expected_hermes_addin_after_signature_check"
                if expected
                else "ask_human"
            ),
            "reason": (
                "Unsigned Revit add-in security prompt for Hermes; prefer running "
                "trust-addin and restarting Revit, or approve only if the manifest "
                "path and DLL match the local Hermes operator."
                if expected
                else (
                    "Unsigned or unverified Revit add-in security prompt for an "
                    "unknown add-in; do not load it without human review."
                )
            ),
        }

    known = match_known_dialog(title, text, button_list, extra_rules=extra_rules)
    if known:
        return {
            "has_modal_dialog": True,
            "dialog_title": title,
            "dialog_text": text,
            "buttons": button_list,
            **known,
        }

    blocked_hits = _contains_any(combined, BLOCKED_TERMS)
    if blocked_hits:
        return {
            "has_modal_dialog": True,
            "dialog_title": title,
            "dialog_text": text,
            "buttons": button_list,
            "risk": HIGH,
            "recommended_action": "ask_human",
            "reason": (
                "Dialog includes blocked/destructive terms: "
                + ", ".join(sorted(set(blocked_hits)))
            ),
        }

    approval_hits = _contains_any(combined, APPROVAL_TERMS)
    if approval_hits:
        return {
            "has_modal_dialog": True,
            "dialog_title": title,
            "dialog_text": text,
            "buttons": button_list,
            "risk": HIGH,
            "recommended_action": "ask_human",
            "reason": (
                "Dialog appears to require a supervised Revit decision: "
                + ", ".join(sorted(set(approval_hits)))
            ),
        }

    if re.search(r"\b(ok|close)\b", combined) and _contains_any(
        combined, INFORMATIONAL_TERMS
    ):
        return {
            "has_modal_dialog": True,
            "dialog_title": title,
            "dialog_text": text,
            "buttons": button_list,
            "risk": LOW,
            "recommended_action": "observe_or_close_if_configured",
            "reason": "Dialog appears informational, but automatic closing remains opt-in.",
        }

    return {
        "has_modal_dialog": bool(title or text or button_list),
        "dialog_title": title,
        "dialog_text": text,
        "buttons": button_list,
        "risk": HIGH if title or text or button_list else LOW,
        "recommended_action": "ask_human" if title or text or button_list else "observe",
        "reason": (
            "Unknown dialog semantics; treat as approval-required."
            if title or text or button_list
            else "No visible dialog content supplied."
        ),
    }


def classify_action(action: str, payload: dict | None = None) -> SafetyDecision:
    """Classify an operator command before execution."""

    payload = payload or {}
    action_norm = _norm(action)
    target_text = _norm(json.dumps(payload, sort_keys=True))

    if action_norm == "agent-model-open-choreography":
        if bool(payload.get("execute_open")):
            token = approval_token_for(action_norm, payload)
            return SafetyDecision(
                action=action_norm,
                risk=HIGH,
                decision=APPROVAL_REQUIRED,
                reason=(
                    "Model-open choreography may launch Revit; the wrapped "
                    "open-model call must also authorize the exact launch payload."
                ),
                approval_token=token,
            )
        return SafetyDecision(
            action=action_norm,
            risk=LOW,
            decision=ALLOW,
            reason="Observation/read-only model-open choreography planning.",
        )

    if action_norm in OBSERVATION_ACTIONS:
        return SafetyDecision(
            action=action_norm,
            risk=LOW,
            decision=ALLOW,
            reason="Observation/read-only command.",
        )

    if action_norm in {"open-model", "install-addin", "trust-addin"}:
        token = approval_token_for(action_norm, payload)
        return SafetyDecision(
            action=action_norm,
            risk=HIGH,
            decision=APPROVAL_REQUIRED,
            reason=f"{action_norm} changes Revit/session state and requires approval.",
            approval_token=token,
        )

    if action_norm == "request-operation":
        operation = _norm(payload.get("operation"))
        if operation in READ_ONLY_BRIDGE_OPERATIONS:
            return SafetyDecision(
                action=action_norm,
                risk=LOW,
                decision=ALLOW,
                reason=f"Read-only bridge operation: {operation}.",
            )
        if operation in CRITICAL_OPERATIONS:
            token = approval_token_for(action_norm, payload)
            return SafetyDecision(
                action=action_norm,
                risk=CRITICAL,
                decision=APPROVAL_REQUIRED,
                reason=(
                    f"Critical Revit operation {operation!r} requires exact human "
                    "approval and operation-specific guard flags."
                ),
                approval_token=token,
            )
        token = approval_token_for(action_norm, payload)
        return SafetyDecision(
            action=action_norm,
            risk=HIGH,
            decision=APPROVAL_REQUIRED,
            reason=f"Unknown bridge operation {operation!r} requires approval.",
            approval_token=token,
        )

    if action_norm == "run-safe-command":
        command_name = _norm(
            payload.get("name") or payload.get("command") or payload.get("operation")
        )
        if command_name in READ_ONLY_SAFE_COMMANDS:
            return SafetyDecision(
                action=action_norm,
                risk=LOW,
                decision=ALLOW,
                reason=f"Read-only safe command wrapper: {command_name}.",
            )
        return SafetyDecision(
            action=action_norm,
            risk=BLOCKED_RISK,
            decision=BLOCK,
            reason=(
                "run-safe-command only accepts read-only command wrappers: "
                + ", ".join(sorted(READ_ONLY_SAFE_COMMANDS))
            ),
        )

    blocked_hits = _contains_any(f"{action_norm} {target_text}", BLOCKED_TERMS)
    if blocked_hits:
        return SafetyDecision(
            action=action_norm,
            risk=BLOCKED_RISK,
            decision=BLOCK,
            reason="Blocked by default: " + ", ".join(sorted(set(blocked_hits))),
        )

    if action_norm == "press-key" and _norm(payload.get("key")) == "escape":
        return SafetyDecision(
            action=action_norm,
            risk=LOW,
            decision=ALLOW,
            reason="Escape is the only low-risk key primitive; execution is still logged.",
        )

    if action_norm in {"focus", "click", "type-text", "press-key", "uia-invoke", "visual-click", "run-safe-command"}:
        token = approval_token_for(action_norm, payload)
        return SafetyDecision(
            action=action_norm,
            risk=HIGH,
            decision=APPROVAL_REQUIRED,
            reason="Human-style UI action requires explicit approval token.",
            approval_token=token,
        )

    token = approval_token_for(action_norm, payload)
    return SafetyDecision(
        action=action_norm,
        risk=HIGH,
        decision=APPROVAL_REQUIRED,
        reason="Unknown action requires explicit approval token.",
        approval_token=token,
    )


def authorize(decision: SafetyDecision, supplied_token: str | None) -> tuple[bool, str]:
    if decision.decision == BLOCK:
        return False, decision.reason
    if decision.decision == APPROVAL_REQUIRED and supplied_token != decision.approval_token:
        return False, "Missing or incorrect approval token for this exact action."
    return True, "Allowed by safety policy."


def validate_sandbox_root(sandbox: Path, allow_outside_safe_root: bool = False) -> str | None:
    """Validate that a sandbox is under the known safe project unless overridden."""

    if allow_outside_safe_root:
        return None
    return validate_within_dir(sandbox, SAFE_PROJECT_ROOT)


def validate_output_path(path: Path, sandbox: Path) -> str | None:
    """Ensure output writes remain inside the selected sandbox."""

    return validate_within_dir(path, sandbox)
