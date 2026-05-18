"""Safe execution wrapper for Revit human-style action primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .bridge import RevitBridgeClient
from .journal import TaskJournal
from .safety import ALLOW, APPROVAL_REQUIRED, BLOCK, authorize, classify_action, validate_output_path
from .uia import uia_invoke_control
from .windows import RevitWindowObserver


@dataclass
class ActionRequest:
    action: str
    payload: dict
    dry_run: bool = True
    approval_token: str | None = None


class SafeActionExecutor:
    """Execute UI primitives only after policy classification and logging."""

    def __init__(self, observer: RevitWindowObserver, journal: TaskJournal):
        self.observer = observer
        self.journal = journal

    def run(self, request: ActionRequest) -> dict:
        before = self._status()
        decision = classify_action(request.action, request.payload)
        allowed, auth_reason = authorize(decision, request.approval_token)

        result = {
            "status": "dry_run" if request.dry_run else "blocked",
            "executed": False,
            "dry_run": request.dry_run,
            "policy": decision.to_dict(),
            "authorization": {"allowed": allowed, "reason": auth_reason},
            "before": before,
        }

        if request.dry_run:
            if decision.decision == BLOCK:
                result["status"] = "blocked"
                result["next_step"] = "No execution path; this action is blocked by policy."
            else:
                result["status"] = "dry_run"
                result["next_step"] = (
                    "Re-run with --execute"
                    + (
                        f" --approval-token {decision.approval_token}"
                        if decision.approval_token
                        else ""
                    )
                )
            self._log(request, result, before=before, after=None)
            return result

        if not allowed:
            self._log(request, result, before=before, after=None)
            return result

        action = request.action
        try:
            if action == "focus":
                execution = self._focus(request.payload)
            elif action == "press-key":
                execution = self._press_key(request.payload)
            elif action == "click":
                execution = self._click_named_button(request.payload)
            elif action == "type-text":
                execution = self._type_text(request.payload)
            elif action == "uia-invoke":
                execution = self._uia_invoke(request.payload)
            elif action == "visual-click":
                execution = self._visual_click(request.payload)
            else:
                execution = {
                    "success": False,
                    "error": f"No executor implemented for action {action!r}.",
                }
        except Exception as exc:
            execution = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        after = self._status()
        verification = self._verify_expected_state(request.payload, after)
        executed = bool(execution.get("success")) and verification["success"]
        result.update(
            {
                "status": "executed" if executed else "failed",
                "executed": executed,
                "execution": execution,
                "verification": verification,
                "after": after,
            }
        )
        self._log(request, result, before=before, after=after)
        return result

    def _status(self) -> dict:
        status = self.observer.status()
        if not isinstance(status, dict):
            return {"state": "unknown", "raw_status": status}
        if status.get("state") == "modal" and "dialog_details" not in status:
            try:
                status = {**status, "dialog_details": self.observer.list_dialogs()}
            except Exception as exc:
                status = {
                    **status,
                    "dialog_details": {
                        "supported": False,
                        "error": f"Dialog detail observation failed: {type(exc).__name__}: {exc}",
                        "dialogs": [],
                    },
                }
        if "active_document" in status:
            return status
        return {
            **status,
            "active_document": RevitBridgeClient(self.journal.sandbox).active_document_status(),
        }

    def _focus(self, payload: dict) -> dict:
        if not self.observer.supported:
            return {"success": False, "error": "Unsupported platform."}
        hwnd = int(payload.get("hwnd") or self.observer._default_target_hwnd() or 0)
        if not hwnd:
            return {"success": False, "error": "No target Revit window."}
        ok = bool(self.observer.user32.SetForegroundWindow(hwnd))
        return {"success": ok, "hwnd": hwnd}

    def _press_key(self, payload: dict) -> dict:
        if not self.observer.supported:
            return {"success": False, "error": "Unsupported platform."}
        key = str(payload.get("key") or "").lower()
        vk_map = {"escape": 0x1B, "esc": 0x1B, "enter": 0x0D, "tab": 0x09}
        if key not in vk_map:
            return {"success": False, "error": f"Key {key!r} is not in the safe prototype map."}
        KEYEVENTF_KEYUP = 0x0002
        vk = vk_map[key]
        self.observer.user32.keybd_event(vk, 0, 0, 0)
        self.observer.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return {"success": True, "key": key}

    def _click_named_button(self, payload: dict) -> dict:
        if not self.observer.supported:
            return {"success": False, "error": "Unsupported platform."}
        target = _button_label(str(payload.get("target") or ""))
        if not target:
            return {"success": False, "error": "Missing button target."}
        hwnd = int(payload.get("hwnd") or self.observer._default_target_hwnd() or 0)
        if not hwnd:
            return {"success": False, "error": "No target Revit window/dialog."}
        for child in self.observer._flat_children(hwnd):
            if _button_label(child.title) == target and "button" in child.class_name.lower():
                BM_CLICK = 0x00F5
                self.observer.user32.SendMessageW(child.hwnd, BM_CLICK, 0, 0)
                return {"success": True, "button": child.title, "hwnd": child.hwnd}
        return {"success": False, "error": f"Button {target!r} not found."}

    def _type_text(self, payload: dict) -> dict:
        text = str(payload.get("text") or "")
        if not text:
            return {"success": False, "error": "Missing text."}
        try:
            from pywinauto import keyboard
        except Exception:
            return {
                "success": False,
                "error": "Typing execution requires optional dependency pywinauto.",
            }
        keyboard.send_keys(text, with_spaces=True, pause=0.01)
        return {"success": True, "chars": len(text)}

    def _uia_invoke(self, payload: dict) -> dict:
        return uia_invoke_control(
            name=str(payload.get("name") or ""),
            control_type=str(payload.get("control_type") or ""),
            automation_id=str(payload.get("automation_id") or ""),
            class_name=str(payload.get("class_name") or ""),
            hwnd=int(payload.get("hwnd") or 0) or None,
            max_depth=int(payload.get("max_depth") or 4),
            limit=int(payload.get("limit") or 100),
            exact=bool(payload.get("exact")),
            method=str(payload.get("method") or "auto"),
            observer=self.observer,
        )

    def _visual_click(self, payload: dict) -> dict:
        if not self.observer.supported:
            return {"success": False, "error": "Unsupported platform."}
        hwnd = int(payload.get("hwnd") or self.observer._default_target_hwnd() or 0)
        screen_x = _int_or_none(payload.get("screen_x"))
        screen_y = _int_or_none(payload.get("screen_y"))
        if not hwnd:
            return {"success": False, "error": "Missing visual-click hwnd."}
        if screen_x is None or screen_y is None:
            return {"success": False, "error": "Missing visual-click screen coordinates."}
        self.observer.user32.SetForegroundWindow(hwnd)
        if hasattr(self.observer.user32, "SetCursorPos"):
            self.observer.user32.SetCursorPos(screen_x, screen_y)
        else:
            return {"success": False, "error": "SetCursorPos is unavailable."}
        if not hasattr(self.observer.user32, "mouse_event"):
            return {"success": False, "error": "mouse_event is unavailable."}
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        self.observer.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self.observer.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return {
            "success": True,
            "hwnd": hwnd,
            "screen_x": screen_x,
            "screen_y": screen_y,
            "target_text": payload.get("target_text"),
            "coordinate_source": payload.get("coordinate_source"),
        }

    def _verify_expected_state(self, payload: dict, after: dict) -> dict:
        expected = str(payload.get("expect_state") or "").strip()
        if not expected:
            return {"success": True, "checked": False, "reason": "No expected state supplied."}
        actual = str(after.get("state") or "")
        return {
            "success": actual.lower() == expected.lower(),
            "checked": True,
            "expected_state": expected,
            "actual_state": actual,
        }

    def _log(
        self,
        request: ActionRequest,
        result: dict,
        before: dict | None,
        after: dict | None,
    ) -> None:
        self.journal.write_entry(
            {
                "command": request.action,
                "requested_action": request.payload,
                "observed_ui_state_before_action": before,
                "observed_ui_state_after_action": after,
                "risk_classification": result["policy"],
                "approval_status": result["authorization"],
                "result": {
                    "status": result["status"],
                    "executed": result["executed"],
                },
            }
        )


def validate_action_approval_matrix(journal: TaskJournal, observer: RevitWindowObserver) -> dict:
    """Dry-run representative actions to verify approval/blocking behavior."""

    primitive_cases = [
        {
            "name": "focus-main-window",
            "action": "focus",
            "payload": {},
            "expected_decision": APPROVAL_REQUIRED,
        },
        {
            "name": "press-escape-low-risk",
            "action": "press-key",
            "payload": {"key": "Escape"},
            "expected_decision": ALLOW,
        },
        {
            "name": "press-enter-approval",
            "action": "press-key",
            "payload": {"key": "Enter"},
            "expected_decision": APPROVAL_REQUIRED,
        },
        {
            "name": "click-known-non-destructive-button",
            "action": "click",
            "payload": {"target": "Always Load"},
            "expected_decision": APPROVAL_REQUIRED,
        },
        {
            "name": "click-save-blocked",
            "action": "click",
            "payload": {"target": "Save"},
            "expected_decision": BLOCK,
        },
        {
            "name": "type-text-approval",
            "action": "type-text",
            "payload": {"text": "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW"},
            "expected_decision": APPROVAL_REQUIRED,
        },
        {
            "name": "uia-view-tab-approval",
            "action": "uia-invoke",
            "payload": {"automation_id": "View", "exact": True, "method": "select"},
            "expected_decision": APPROVAL_REQUIRED,
        },
        {
            "name": "uia-save-blocked",
            "action": "uia-invoke",
            "payload": {"automation_id": "ID_Save_RibbonItemControl", "exact": True},
            "expected_decision": BLOCK,
        },
        {
            "name": "visual-click-approval",
            "action": "visual-click",
            "payload": {
                "hwnd": 1,
                "screen_x": 10,
                "screen_y": 10,
                "target_text": "Synthetic OCR row",
                "coordinate_source": "synthetic-matrix",
            },
            "expected_decision": APPROVAL_REQUIRED,
        },
    ]
    classification_cases = [
        {
            "name": "request-active-document-allowed",
            "action": "request-operation",
            "payload": {"operation": "active-document"},
            "expected_decision": ALLOW,
        },
        {
            "name": "request-activate-view-critical-approval",
            "action": "request-operation",
            "payload": {"operation": "activate-view", "sheet_number": "S2.0"},
            "expected_decision": APPROVAL_REQUIRED,
            "expected_risk": "critical",
        },
        {
            "name": "request-save-critical-approval",
            "action": "request-operation",
            "payload": {"operation": "save"},
            "expected_decision": APPROVAL_REQUIRED,
            "expected_risk": "critical",
        },
        {
            "name": "unknown-operation-approval",
            "action": "request-operation",
            "payload": {"operation": "mystery"},
            "expected_decision": APPROVAL_REQUIRED,
        },
    ]

    executor = SafeActionExecutor(observer, journal)
    cases = []
    for case in primitive_cases:
        result = executor.run(
            ActionRequest(
                action=case["action"],
                payload=case["payload"],
                dry_run=True,
            )
        )
        policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
        checks = _approval_matrix_checks(
            expected_decision=case["expected_decision"],
            policy=policy,
            executed=bool(result.get("executed")),
            dry_run=bool(result.get("dry_run")),
            expected_risk=case.get("expected_risk"),
        )
        cases.append(
            {
                "name": case["name"],
                "kind": "executor-dry-run",
                "success": all(check["passed"] for check in checks),
                "action": case["action"],
                "payload": case["payload"],
                "policy": policy,
                "result_status": result.get("status"),
                "executed": result.get("executed"),
                "checks": checks,
            }
        )

    for case in classification_cases:
        decision = classify_action(case["action"], case["payload"])
        policy = decision.to_dict()
        checks = _approval_matrix_checks(
            expected_decision=case["expected_decision"],
            policy=policy,
            executed=False,
            dry_run=True,
            expected_risk=case.get("expected_risk"),
        )
        cases.append(
            {
                "name": case["name"],
                "kind": "classification-only",
                "success": all(check["passed"] for check in checks),
                "action": case["action"],
                "payload": case["payload"],
                "policy": policy,
                "executed": False,
                "checks": checks,
            }
        )

    output = journal.run_dir / "action_approval_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "dry_run_only": True,
        "case_count": len(cases),
        "approval_required_count": sum(
            1 for case in cases if case["policy"].get("decision") == APPROVAL_REQUIRED
        ),
        "blocked_count": sum(1 for case in cases if case["policy"].get("decision") == BLOCK),
        "allowed_count": sum(1 for case in cases if case["policy"].get("decision") == ALLOW),
        "executed_count": sum(1 for case in cases if case.get("executed")),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": "Approval rehearsal only. UI primitives were dry-run and bridge operation cases were classified only; no UI or model action was executed.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "action-approval-matrix",
            "requested_action": {"case_count": len(cases)},
            "risk_classification": classify_action("action-approval-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only/dry-run approval gate validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
                "executed_count": result["executed_count"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def _approval_matrix_checks(
    *,
    expected_decision: str,
    policy: dict,
    executed: bool,
    dry_run: bool,
    expected_risk: str | None = None,
) -> list[dict]:
    decision = str(policy.get("decision") or "")
    token = policy.get("approval_token")
    checks = [
        _matrix_check(
            "decision_expected",
            decision == expected_decision,
            "Safety decision matched expectation.",
            f"Expected decision {expected_decision!r}, observed {decision!r}.",
        ),
        _matrix_check(
            "nothing_executed",
            not executed,
            "No action executed.",
            "An action executed during approval rehearsal.",
        ),
        _matrix_check(
            "dry_run_or_classification_only",
            dry_run,
            "Case used dry-run/classification-only evaluation.",
            "Case was not marked dry-run/classification-only.",
        ),
    ]
    if expected_decision == APPROVAL_REQUIRED:
        checks.append(
            _matrix_check(
                "approval_token_present",
                isinstance(token, str) and token.startswith("APPROVE:"),
                "Approval-required case exposes an exact approval token.",
                "Approval-required case lacks an exact approval token.",
            )
        )
    else:
        checks.append(
            _matrix_check(
                "approval_token_absent_when_not_required",
                token is None,
                "Non-approval case does not expose an approval token.",
                "Non-approval case unexpectedly exposes an approval token.",
            )
        )
    if expected_risk:
        checks.append(
            _matrix_check(
                "risk_expected",
                str(policy.get("risk") or "") == expected_risk,
                "Risk matched expectation.",
                f"Expected risk {expected_risk!r}, observed {policy.get('risk')!r}.",
            )
        )
    return checks


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }


def _button_label(value: str) -> str:
    return value.replace("&", "").strip().lower()


def _int_or_none(value: object) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
