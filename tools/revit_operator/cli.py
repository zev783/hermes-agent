"""Command-line interface for the Revit human-operator prototype."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .actions import ActionRequest, SafeActionExecutor, validate_action_approval_matrix
from .agent_session import (
    build_agent_session_approval_plan,
    build_agent_session_completion_audit,
    build_ui_flow_candidate_approval_plan,
    execute_agent_session_approved_item,
    execute_ui_flow_approved_candidate,
    plan_agent_session,
    refresh_agent_session_evidence,
    run_agent_session,
    scout_agent_ui_flow,
)
from .agent_task import run_agent_task
from .addin_installer import install_addin
from .addin_security import addin_security_preflight
from .addin_trust import trust_addin
from .bridge import RevitBridgeClient
from .bridge_validation import bridge_post_restart_validation, bridge_restart_validation_plan
from .constants import (
    APP_NAME,
    ENV_ALLOW_EXTERNAL_SANDBOX,
    default_sandbox_root,
    truthy_env,
)
from .context_menu import (
    list_context_menu_actions,
    plan_context_menu_action,
    plan_context_menu_item,
    run_context_menu_action,
    run_context_menu_item,
    snapshot_context_menu,
    validate_context_menu_action_matrix,
)
from .dialogs import list_known_dialog_rules
from .dialog_memory import (
    list_dialog_rule_library,
    load_learned_dialog_rules,
    record_dialog_rule,
)
from .dialog_workflows import (
    list_dialog_workflows,
    plan_current_dialog_response,
    plan_dialog_response,
    validate_dialog_workflow_matrix,
)
from .execution_audit import audit_ui_execution_coverage
from .journal import TaskJournal
from .model_open_choreography import (
    build_model_open_prompt_approval_plan,
    execute_model_open_prompt_approved_step,
    run_model_open_choreography,
)
from .navigation import find_views
from .north_star import (
    build_north_star_blocked_ledger,
    build_north_star_current_handoff,
    build_north_star_human_gate_packet,
    build_north_star_next_human_action_card,
    build_north_star_human_unblock_brief,
    build_north_star_agent_stop_status,
    build_north_star_refresh_sequence,
    build_north_star_approval_plan,
    build_north_star_approval_preflight,
    build_north_star_ready_approvals,
    build_north_star_next_approval,
    build_north_star_waiting_state,
    build_north_star_approval_phrase_verify,
    build_north_star_approved_execution_preview,
    build_north_star_approval_verify,
    build_north_star_completion_gate,
    build_north_star_stable_artifact_scan,
    build_north_star_unblock_readiness,
    build_north_star_status,
    run_north_star_audit,
    run_north_star_resume_check,
    run_north_star_watch,
)
from .ocr import ocr_health, ocr_screenshot
from .operations import OperationRequest, open_model, queue_operation
from .palettes import capture_properties_palette_snapshot
from .project_browser import (
    capture_project_browser_snapshot,
    plan_project_browser_visual_activation,
    plan_project_browser_item_activation,
    plan_project_browser_navigation,
    run_project_browser_visual_activation,
    run_project_browser_item_activation,
)
from .qa import generate_qa_report
from .readiness import wait_model_ready
from .recovery import capture_recovery_snapshot, validate_recovery_drill_matrix
from .revit_locator import default_test_model_info, installed_revit_versions
from .ribbon import list_ribbon_actions, plan_ribbon_action, run_ribbon_action, validate_ribbon_action_matrix
from .safety import classify_action, classify_dialog, validate_output_path, validate_sandbox_root
from .session_checkpoint import build_agent_session_resume_plan, write_agent_session_checkpoint
from .supervision import audit_supervision_endurance, supervise_session, validate_supervision_endurance_matrix
from .supervised_ops import run_supervised_ops_audit
from .transport_safety import build_transport_safety_matrix
from .ui_workflows import (
    list_ui_workflows,
    plan_ui_workflow,
    run_ui_workflow,
    run_ui_workflow_smoke_matrix,
    validate_ui_workflow_matrix,
)
from .version_support import version_support_matrix
from .uia import uia_control_details, uia_find_controls, uia_tree, validate_uia_method_matrix
from .windows import RevitWindowObserver
from .workflow_memory import (
    list_workflows,
    plan_workflow_approvals,
    plan_workflow_replay,
    record_workflow,
    replay_workflow,
)
from .workflows import run_readonly_qa_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--sandbox", help="Sandbox root for logs, screenshots, and metadata.")
    parser.add_argument("--task-id", help="Reuse an existing task journal id.")
    parser.add_argument(
        "--allow-sandbox-outside-safe-root",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the local HTTP control server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    sub.add_parser("health", help="Report operator dependencies and platform support.")
    sub.add_parser("version-support", help="Report supported Revit versions and add-in target frameworks.")
    north_star_status = sub.add_parser(
        "north-star-status",
        help="Write a compact read-only north-star blocker/status handoff.",
    )
    north_star_status.add_argument("--sheet-number", default="S2.0")
    sub.add_parser("north-star-audit", help="Write a read-only prompt-to-artifact north-star completion audit.")
    north_star_approval = sub.add_parser(
        "north-star-approval-plan",
        help="Write a read-only approval handoff for remaining north-star gates.",
    )
    north_star_approval.add_argument("--sheet-number", default="S2.0")
    north_star_approval_preflight = sub.add_parser(
        "north-star-approval-preflight",
        help="Run read-only dry-run/preflight commands for current north-star approval items.",
    )
    north_star_approval_preflight.add_argument("--sheet-number", default="S2.0")
    north_star_approval_preflight.add_argument("--revit-version", default="2025")
    north_star_approval_preflight.add_argument("--expected-title-contains", default="")
    north_star_approval_preflight.add_argument("--expected-path-contains", default="")
    north_star_approval_preflight.add_argument("--expected-view-name", default="")
    north_star_approval_preflight.add_argument("--expected-view-type", default="")
    north_star_ready_approvals = sub.add_parser(
        "north-star-ready-approvals",
        help="Write a read-only handoff containing only approval items ready for human approval.",
    )
    north_star_ready_approvals.add_argument("--sheet-number", default="S2.0")
    north_star_next_approval = sub.add_parser(
        "north-star-next-approval",
        help="Write a read-only single-item approval handoff for the next safest ready action.",
    )
    north_star_next_approval.add_argument("--sheet-number", default="S2.0")
    north_star_waiting_state = sub.add_parser(
        "north-star-waiting-state",
        help="Write a read-only waiting-state handoff for human/real-condition gates.",
    )
    north_star_waiting_state.add_argument("--sheet-number", default="S2.0")
    north_star_waiting_state.add_argument("--revit-version", default="2025")
    north_star_waiting_state.add_argument("--expected-title-contains", default="")
    north_star_waiting_state.add_argument("--expected-path-contains", default="")
    north_star_waiting_state.add_argument("--expected-view-name", default="")
    north_star_waiting_state.add_argument("--expected-view-type", default="")
    north_star_approval_phrase_verify = sub.add_parser(
        "north-star-approval-phrase-verify",
        help="Verify an exact human approval phrase against the current waiting state without executing it.",
    )
    north_star_approval_phrase_verify.add_argument("--phrase", required=True)
    north_star_approval_phrase_verify.add_argument(
        "--phrase-source",
        default="",
        help=(
            "Phrase provenance attestation. Use human_active_conversation only "
            "when the phrase was supplied by the human in the active conversation."
        ),
    )
    north_star_approval_phrase_verify.add_argument("--sheet-number", default="S2.0")
    north_star_approval_phrase_verify.add_argument("--revit-version", default="2025")
    north_star_approval_phrase_verify.add_argument("--expected-title-contains", default="")
    north_star_approval_phrase_verify.add_argument("--expected-path-contains", default="")
    north_star_approval_phrase_verify.add_argument("--expected-view-name", default="")
    north_star_approval_phrase_verify.add_argument("--expected-view-type", default="")
    north_star_approved_execution_preview = sub.add_parser(
        "north-star-approved-execution-preview",
        help="Preview the exact next command after phrase validation without executing it.",
    )
    north_star_approved_execution_preview.add_argument("--phrase", required=True)
    north_star_approved_execution_preview.add_argument(
        "--phrase-source",
        default="",
        help=(
            "Phrase provenance attestation. Use human_active_conversation only "
            "when the phrase was supplied by the human in the active conversation."
        ),
    )
    north_star_approved_execution_preview.add_argument("--sheet-number", default="S2.0")
    north_star_approved_execution_preview.add_argument("--revit-version", default="2025")
    north_star_approved_execution_preview.add_argument("--expected-title-contains", default="")
    north_star_approved_execution_preview.add_argument("--expected-path-contains", default="")
    north_star_approved_execution_preview.add_argument("--expected-view-name", default="")
    north_star_approved_execution_preview.add_argument("--expected-view-type", default="")
    north_star_approval_verify = sub.add_parser(
        "north-star-approval-verify",
        help="Verify what a supplied approval token matches without executing it.",
    )
    north_star_approval_verify.add_argument("--sheet-number", default="S2.0")
    north_star_approval_verify.add_argument("--approval-token", required=True)
    north_star_watch = sub.add_parser(
        "north-star-watch",
        help="Poll read-only north-star gates for restart/reload or recovery state changes.",
    )
    north_star_watch.add_argument("--sheet-number", default="S2.0")
    north_star_watch.add_argument("--revit-version", default="2025")
    north_star_watch.add_argument("--expected-title-contains", default="")
    north_star_watch.add_argument("--expected-path-contains", default="")
    north_star_watch.add_argument("--expected-view-name", default="")
    north_star_watch.add_argument("--expected-view-type", default="")
    north_star_watch.add_argument(
        "--refresh-approval-preflight",
        action="store_true",
        help="After polling, rerun read-only approval dry-run preflight before the hard gate.",
    )
    north_star_watch.add_argument(
        "--publish-current-handoff",
        action="store_true",
        help="After optional preflight, republish stable read-only current handoff artifacts.",
    )
    north_star_watch.add_argument("--checks", type=int, default=6)
    north_star_watch.add_argument("--poll", type=float, default=20.0)
    north_star_resume = sub.add_parser(
        "north-star-resume-check",
        help="Run read-only resume validation after a human-gated north-star state changes.",
    )
    north_star_resume.add_argument("--sheet-number", default="S2.0")
    north_star_resume.add_argument("--revit-version", default="2025")
    north_star_resume.add_argument("--expected-title-contains", default="")
    north_star_resume.add_argument("--expected-path-contains", default="")
    north_star_resume.add_argument("--expected-view-name", default="")
    north_star_resume.add_argument("--expected-view-type", default="")
    north_star_resume.add_argument("--timeout", type=float, default=120.0)
    north_star_resume.add_argument("--poll", type=float, default=2.0)
    north_star_gate_packet = sub.add_parser(
        "north-star-human-gate-packet",
        help="Write a concise read-only human handoff packet for remaining north-star gates.",
    )
    north_star_gate_packet.add_argument("--sheet-number", default="S2.0")
    north_star_gate_packet.add_argument("--revit-version", default="2025")
    north_star_gate_packet.add_argument("--expected-title-contains", default="")
    north_star_gate_packet.add_argument("--expected-path-contains", default="")
    north_star_gate_packet.add_argument("--expected-view-name", default="")
    north_star_gate_packet.add_argument("--expected-view-type", default="")
    north_star_next_human = sub.add_parser(
        "north-star-next-human-action",
        help="Write a one-screen read-only card for the next human unblock choices.",
    )
    north_star_next_human.add_argument("--sheet-number", default="S2.0")
    north_star_next_human.add_argument("--revit-version", default="2025")
    north_star_next_human.add_argument("--expected-title-contains", default="")
    north_star_next_human.add_argument("--expected-path-contains", default="")
    north_star_next_human.add_argument("--expected-view-name", default="")
    north_star_next_human.add_argument("--expected-view-type", default="")
    north_star_unblock_brief = sub.add_parser(
        "north-star-human-unblock-brief",
        help="Write a sanitized no-token human unblock brief for the remaining gates.",
    )
    north_star_unblock_brief.add_argument("--sheet-number", default="S2.0")
    north_star_unblock_brief.add_argument("--revit-version", default="2025")
    north_star_unblock_brief.add_argument("--expected-title-contains", default="")
    north_star_unblock_brief.add_argument("--expected-path-contains", default="")
    north_star_unblock_brief.add_argument("--expected-view-name", default="")
    north_star_unblock_brief.add_argument("--expected-view-type", default="")
    north_star_agent_stop = sub.add_parser(
        "north-star-agent-stop-status",
        help="Write the current read-only north-star agent stop status.",
    )
    north_star_agent_stop.add_argument("--sheet-number", default="S2.0")
    north_star_agent_stop.add_argument("--revit-version", default="2025")
    north_star_agent_stop.add_argument("--expected-title-contains", default="")
    north_star_agent_stop.add_argument("--expected-path-contains", default="")
    north_star_agent_stop.add_argument("--expected-view-name", default="")
    north_star_agent_stop.add_argument("--expected-view-type", default="")
    north_star_blocked_ledger = sub.add_parser(
        "north-star-blocked-ledger",
        help="Write a read-only ledger of unresolved north-star gates and recheck commands.",
    )
    north_star_blocked_ledger.add_argument("--sheet-number", default="S2.0")
    north_star_blocked_ledger.add_argument("--revit-version", default="2025")
    north_star_blocked_ledger.add_argument("--expected-title-contains", default="")
    north_star_blocked_ledger.add_argument("--expected-path-contains", default="")
    north_star_blocked_ledger.add_argument("--expected-view-name", default="")
    north_star_blocked_ledger.add_argument("--expected-view-type", default="")
    north_star_current_handoff = sub.add_parser(
        "north-star-current-handoff",
        help="Publish stable sandbox-root copies of the current north-star handoff state.",
    )
    north_star_current_handoff.add_argument("--sheet-number", default="S2.0")
    north_star_current_handoff.add_argument("--revit-version", default="2025")
    north_star_current_handoff.add_argument("--expected-title-contains", default="")
    north_star_current_handoff.add_argument("--expected-path-contains", default="")
    north_star_current_handoff.add_argument("--expected-view-name", default="")
    north_star_current_handoff.add_argument("--expected-view-type", default="")
    north_star_refresh_sequence = sub.add_parser(
        "north-star-refresh-sequence",
        help="Run current handoff, stable scans, and completion gates in the required read-only order.",
    )
    north_star_refresh_sequence.add_argument("--sheet-number", default="S2.0")
    north_star_refresh_sequence.add_argument("--revit-version", default="2025")
    north_star_refresh_sequence.add_argument("--expected-title-contains", default="")
    north_star_refresh_sequence.add_argument("--expected-path-contains", default="")
    north_star_refresh_sequence.add_argument("--expected-view-name", default="")
    north_star_refresh_sequence.add_argument("--expected-view-type", default="")
    sub.add_parser(
        "north-star-completion-gate",
        help="Run a fresh read-only north-star audit and refuse completion while any requirement is blocked.",
    )
    sub.add_parser(
        "north-star-stable-artifact-scan",
        help="Scan stable north-star current artifacts for credential leaks and consistency drift.",
    )
    sub.add_parser(
        "north-star-unblock-readiness",
        help="Write read-only per-blocker packets for the remaining north-star gates.",
    )
    sub.add_parser(
        "transport-safety-matrix",
        help="Validate agent-facing transport redaction and fail-closed wrapper gates.",
    )
    sub.add_parser("status", help="Summarize Revit process/window/dialog/document state.")
    sub.add_parser("list-processes", help="List running Revit processes.")
    sub.add_parser("list-revit-installs", help="List installed Revit executables.")

    windows = sub.add_parser("list-windows", help="List visible Revit-related windows.")
    windows.add_argument("--all", action="store_true", help="Include all top-level windows.")

    sub.add_parser("list-dialogs", help="List and classify visible Revit dialogs.")
    sub.add_parser("known-dialogs", help="List built-in known Revit dialog rules.")
    sub.add_parser("dialog-rule-library", help="List built-in and sandbox-learned dialog rules.")
    sub.add_parser("dialog-workflows", help="List conservative known-dialog response playbooks.")
    sub.add_parser("dialog-workflow-matrix", help="Validate all known-dialog playbooks against representative prompts.")

    record_dialog = sub.add_parser("record-dialog-rule", help="Record a conservative learned dialog classifier.")
    record_dialog.add_argument("--rule-id", required=True)
    record_dialog.add_argument("--title-term", action="append", default=[])
    record_dialog.add_argument("--text-term", action="append", default=[])
    record_dialog.add_argument("--button-term", action="append", default=[])
    record_dialog.add_argument("--risk", choices=["medium", "high", "critical"], default="high")
    record_dialog.add_argument("--recommended-action", default="ask_human")
    record_dialog.add_argument("--reason", default="")

    classify = sub.add_parser("classify-dialog", help="Classify supplied dialog text.")
    classify.add_argument("--title", default="")
    classify.add_argument("--text", default="")
    classify.add_argument("--button", action="append", default=[])

    plan_dialog = sub.add_parser("plan-dialog-response", help="Plan a conservative response for known dialog text.")
    plan_dialog.add_argument("--title", default="")
    plan_dialog.add_argument("--text", default="")
    plan_dialog.add_argument("--button", action="append", default=[])

    plan_current_dialog = sub.add_parser(
        "plan-current-dialog-response",
        help="Plan a conservative response for the currently visible Revit dialog.",
    )
    plan_current_dialog.add_argument("--title-contains", default="")
    plan_current_dialog.add_argument("--index", type=int, default=0)
    plan_current_dialog.add_argument(
        "--use-ocr",
        action="store_true",
        help="Use OCR as a read-only fallback when dialog text is inaccessible.",
    )
    plan_current_dialog.add_argument(
        "--ocr-backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
        help="OCR backend for --use-ocr.",
    )

    screenshot = sub.add_parser("screenshot", help="Capture the active Revit window as BMP.")
    screenshot.add_argument("--output", help="Output path under the selected sandbox.")
    screenshot.add_argument("--hwnd", type=int, help="Specific window handle to capture.")

    ocr = sub.add_parser("ocr-screenshot", help="Capture screenshot and run optional OCR fallback.")
    ocr.add_argument("--hwnd", type=int, help="Specific window handle to OCR.")
    ocr.add_argument(
        "--backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
        help="OCR backend to use when dependencies are available.",
    )
    sub.add_parser("ocr-health", help="Report OCR dependency readiness.")

    tree = sub.add_parser("ui-tree", help="Export a shallow Win32 UI tree.")
    tree.add_argument("--output", help="Output path under the selected sandbox.")
    tree.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    tree.add_argument("--max-depth", type=int, default=4)

    uia = sub.add_parser("uia-tree", help="Export a Microsoft UI Automation tree when pywinauto is installed.")
    uia.add_argument("--output", help="Output path under the selected sandbox.")
    uia.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    uia.add_argument("--max-depth", type=int, default=4)
    uia.add_argument("--limit", type=int, default=500)

    uia_find = sub.add_parser("uia-find-control", help="Find controls by UIA name/type/AutomationId/class.")
    uia_find.add_argument("--name", default="")
    uia_find.add_argument("--control-type", default="")
    uia_find.add_argument("--automation-id", default="")
    uia_find.add_argument("--class-name", default="")
    uia_find.add_argument("--output", help="Output path under the selected sandbox.")
    uia_find.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    uia_find.add_argument("--max-depth", type=int, default=4)
    uia_find.add_argument("--limit", type=int, default=100)
    uia_find.add_argument("--exact", action="store_true")

    uia_details = sub.add_parser("uia-control-details", help="Inspect matching UIA controls and supported action methods.")
    uia_details.add_argument("--name", default="")
    uia_details.add_argument("--control-type", default="")
    uia_details.add_argument("--automation-id", default="")
    uia_details.add_argument("--class-name", default="")
    uia_details.add_argument("--output", help="Output path under the selected sandbox.")
    uia_details.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    uia_details.add_argument("--max-depth", type=int, default=4)
    uia_details.add_argument("--limit", type=int, default=100)
    uia_details.add_argument("--exact", action="store_true")

    uia_invoke = sub.add_parser("uia-invoke", help="Invoke exactly one UIA control after approval.")
    _add_action_flags(uia_invoke)
    uia_invoke.add_argument("--name", default="")
    uia_invoke.add_argument("--control-type", default="")
    uia_invoke.add_argument("--automation-id", default="")
    uia_invoke.add_argument("--class-name", default="")
    uia_invoke.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    uia_invoke.add_argument("--max-depth", type=int, default=4)
    uia_invoke.add_argument("--limit", type=int, default=100)
    uia_invoke.add_argument("--exact", action="store_true")
    uia_invoke.add_argument(
        "--method",
        default="auto",
        choices=[
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
        ],
        help="Approved UIA method to use when executing.",
    )

    sub.add_parser("uia-method-matrix", help="Validate UIA method safety coverage without touching live UI.")

    sub.add_parser("ribbon-actions", help="List named guarded ribbon/menu action descriptors.")
    sub.add_parser("ribbon-action-matrix", help="Validate named ribbon descriptors without touching live UI.")
    plan_ribbon = sub.add_parser("plan-ribbon-action", help="Resolve a named ribbon/menu action to a UIA target.")
    plan_ribbon.add_argument("--name", required=True)
    plan_ribbon.add_argument("--hwnd", type=int)
    plan_ribbon.add_argument("--max-depth", type=int)
    plan_ribbon.add_argument("--limit", type=int)

    ribbon_action = sub.add_parser("ribbon-action", help="Dry-run or execute a named guarded ribbon/menu action.")
    _add_action_flags(ribbon_action)
    ribbon_action.add_argument("--name", required=True)
    ribbon_action.add_argument("--hwnd", type=int)
    ribbon_action.add_argument("--max-depth", type=int)
    ribbon_action.add_argument("--limit", type=int)

    sub.add_parser("context-menu-actions", help="List named guarded context-menu action descriptors.")
    sub.add_parser("context-menu-action-matrix", help="Validate context-menu descriptors and item policies without touching live UI.")
    context_snapshot = sub.add_parser("context-menu-snapshot", help="Capture visible UIA menu/menu-item evidence.")
    context_snapshot.add_argument("--hwnd", type=int)
    context_snapshot.add_argument("--max-depth", type=int, default=4)
    context_snapshot.add_argument("--limit", type=int, default=100)

    plan_context_menu = sub.add_parser(
        "plan-context-menu-action",
        help="Resolve a named context-menu action to one UIA target.",
    )
    _add_context_menu_args(plan_context_menu)

    context_menu_action = sub.add_parser(
        "context-menu-action",
        help="Dry-run or execute opening a context menu for one guarded UIA target.",
    )
    _add_action_flags(context_menu_action)
    _add_context_menu_args(context_menu_action)

    plan_context_item = sub.add_parser(
        "plan-context-menu-item",
        help="Resolve one visible context-menu item without selecting it.",
    )
    _add_context_menu_item_args(plan_context_item)

    context_item = sub.add_parser(
        "context-menu-select-item",
        help="Dry-run or execute selecting one exact context-menu item.",
    )
    _add_action_flags(context_item)
    _add_context_menu_item_args(context_item)

    sub.add_parser(
        "action-approval-matrix",
        help="Dry-run representative action approvals and blocked policies without executing UI actions.",
    )

    find_control = sub.add_parser("find-control", help="Find visible controls by text/class in the Revit UI tree.")
    find_control.add_argument("--text", default="", help="Visible control text/title to search for.")
    find_control.add_argument("--class-name", default="", help="Win32 class name to search for.")
    find_control.add_argument("--output", help="Output path under the selected sandbox.")
    find_control.add_argument("--hwnd", type=int, help="Specific window handle to inspect.")
    find_control.add_argument("--max-depth", type=int, default=6)
    find_control.add_argument("--limit", type=int, default=50)
    find_control.add_argument("--exact", action="store_true")

    project_browser = sub.add_parser("project-browser-snapshot", help="Capture read-only Project Browser evidence.")
    project_browser.add_argument("--search-depth", type=int, default=8)
    project_browser.add_argument("--tree-depth", type=int, default=4)
    project_browser.add_argument("--include-uia", action="store_true")
    project_browser.add_argument("--uia-limit", type=int, default=300)
    project_browser.add_argument("--include-ocr", action="store_true")
    project_browser.add_argument(
        "--ocr-backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
    )

    project_browser_nav = sub.add_parser(
        "project-browser-plan-navigation",
        help="Plan safe Project Browser/view navigation without changing Revit state.",
    )
    project_browser_nav.add_argument("--query", default="")
    project_browser_nav.add_argument("--view-name", default="")
    project_browser_nav.add_argument("--sheet-number", default="")
    project_browser_nav.add_argument("--view-type", default="")
    project_browser_nav.add_argument("--limit", type=int, default=20)
    project_browser_nav.add_argument("--search-depth", type=int, default=8)
    project_browser_nav.add_argument("--tree-depth", type=int, default=4)
    project_browser_nav.add_argument("--include-uia", action="store_true")
    project_browser_nav.add_argument("--uia-limit", type=int, default=300)
    project_browser_nav.add_argument("--include-ocr", action="store_true")
    project_browser_nav.add_argument(
        "--ocr-backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
    )

    project_browser_visual_plan = sub.add_parser(
        "project-browser-plan-visual-activation",
        help="Plan an approval-gated OCR-geometry Project Browser click without changing Revit state.",
    )
    _add_project_browser_visual_args(project_browser_visual_plan)

    project_browser_visual_activate = sub.add_parser(
        "project-browser-visual-activate",
        help="Dry-run or execute an approval-gated OCR-geometry Project Browser click.",
    )
    _add_action_flags(project_browser_visual_activate)
    _add_project_browser_visual_args(project_browser_visual_activate)

    project_browser_plan_activation = sub.add_parser(
        "project-browser-plan-activation",
        help="Plan direct Project Browser UIA item activation without changing Revit state.",
    )
    _add_project_browser_item_args(project_browser_plan_activation)

    project_browser_activate = sub.add_parser(
        "project-browser-activate-item",
        help="Dry-run or execute direct Project Browser UIA item activation.",
    )
    _add_action_flags(project_browser_activate)
    _add_project_browser_item_args(project_browser_activate)

    properties_palette = sub.add_parser("properties-palette-snapshot", help="Capture read-only Properties palette evidence.")
    properties_palette.add_argument("--search-depth", type=int, default=8)
    properties_palette.add_argument("--tree-depth", type=int, default=4)
    properties_palette.add_argument("--include-uia", action="store_true")
    properties_palette.add_argument("--uia-limit", type=int, default=300)
    properties_palette.add_argument("--include-ocr", action="store_true")
    properties_palette.add_argument(
        "--ocr-backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
    )

    wait = sub.add_parser("wait-until-idle", help="Wait until Revit appears idle.")
    wait.add_argument("--timeout", type=float, default=30.0)
    wait.add_argument("--poll", type=float, default=1.0)

    wait_window = sub.add_parser("wait-for-window", help="Wait for a Revit window.")
    wait_window.add_argument("--title-contains", default="")
    wait_window.add_argument("--timeout", type=float, default=30.0)
    wait_window.add_argument("--poll", type=float, default=1.0)

    wait_dialog = sub.add_parser("wait-for-dialog", help="Wait for a Revit dialog.")
    wait_dialog.add_argument("--title-contains", default="")
    wait_dialog.add_argument("--timeout", type=float, default=30.0)
    wait_dialog.add_argument("--poll", type=float, default=1.0)

    wait_ready = sub.add_parser("wait-model-ready", help="Wait for idle, non-modal Revit active-document readiness.")
    wait_ready.add_argument("--timeout", type=float, default=120.0)
    wait_ready.add_argument("--poll", type=float, default=2.0)
    wait_ready.add_argument("--expected-title-contains", default="")
    wait_ready.add_argument("--expected-path-contains", default="")
    wait_ready.add_argument("--expected-revit-version", default="")
    wait_ready.add_argument("--expected-view-name", default="")
    wait_ready.add_argument("--expected-view-type", default="")
    wait_ready.add_argument("--no-require-bridge", action="store_true")
    wait_ready.add_argument("--no-stop-on-modal", action="store_true")

    metadata = sub.add_parser("export-metadata", help="Export read-only metadata to sandbox.")
    metadata.add_argument("--output", help="Output path under the selected sandbox.")

    find_view = sub.add_parser("find-view", help="Find views/sheets in metadata for supervised navigation.")
    find_view.add_argument("--query", default="")
    find_view.add_argument("--view-name", default="")
    find_view.add_argument("--sheet-number", default="")
    find_view.add_argument("--view-type", default="")
    find_view.add_argument("--limit", type=int, default=20)

    bridge_results = sub.add_parser("bridge-results", help="List add-in bridge command results.")
    bridge_results.add_argument("--command-id", help="Filter to one command id.")
    bridge_results.add_argument("--limit", type=int, default=20, help="Maximum recent results to return.")

    sub.add_parser("bridge-status", help="Read add-in status and heartbeat bridge metadata.")
    sub.add_parser("verify-bridge-build", help="Verify the loaded add-in reports the current bridge build stamp.")
    bridge_readiness = sub.add_parser(
        "bridge-readiness",
        help="Read-only audit of add-in manifest, DLL, and loaded bridge readiness.",
    )
    bridge_readiness.add_argument("--revit-version", default="2025")
    bridge_readiness.add_argument("--addins-root")
    bridge_readiness.add_argument("--assembly")
    bridge_restart = sub.add_parser(
        "bridge-restart-validation-plan",
        help="Write a read-only human restart/reload handoff and post-restart bridge validation checklist.",
    )
    bridge_restart.add_argument("--revit-version", default="2025")
    bridge_restart.add_argument("--addins-root")
    bridge_restart.add_argument("--assembly")
    bridge_restart.add_argument("--expected-title-contains", default="")
    bridge_restart.add_argument("--expected-path-contains", default="")
    bridge_restart.add_argument("--expected-view-name", default="")
    bridge_restart.add_argument("--expected-view-type", default="")
    bridge_post_restart = sub.add_parser(
        "bridge-post-restart-validation",
        help="Run the read-only post-human-restart bridge validation checklist.",
    )
    bridge_post_restart.add_argument("--revit-version", default="2025")
    bridge_post_restart.add_argument("--addins-root")
    bridge_post_restart.add_argument("--assembly")
    bridge_post_restart.add_argument("--expected-title-contains", default="")
    bridge_post_restart.add_argument("--expected-path-contains", default="")
    bridge_post_restart.add_argument("--expected-view-name", default="")
    bridge_post_restart.add_argument("--expected-view-type", default="")
    bridge_post_restart.add_argument("--timeout", type=float, default=120.0)
    bridge_post_restart.add_argument("--poll", type=float, default=2.0)

    wait_bridge = sub.add_parser("wait-bridge-result", help="Wait for one add-in bridge command result.")
    wait_bridge.add_argument("--command-id", required=True)
    wait_bridge.add_argument("--timeout", type=float, default=60.0)
    wait_bridge.add_argument("--poll", type=float, default=1.0)

    recovery = sub.add_parser("recovery-snapshot", help="Capture stuck-state evidence and recovery guidance.")
    recovery.add_argument("--no-screenshot", action="store_true")
    recovery.add_argument("--no-ui-tree", action="store_true")
    recovery.add_argument("--max-depth", type=int, default=2)
    recovery.add_argument("--bridge-result-limit", type=int, default=10)
    sub.add_parser("recovery-drill-matrix", help="Validate synthetic recovery recommendations without touching live Revit.")

    supervise = sub.add_parser("supervise-session", help="Poll Revit state and write a read-only supervision log.")
    supervise.add_argument("--duration", type=float, default=300.0)
    supervise.add_argument("--poll", type=float, default=5.0)
    supervise.add_argument("--max-checks", type=int)
    supervise.add_argument("--continue-on-modal", action="store_true")
    supervise.add_argument("--bridge-result-limit", type=int, default=10)
    supervise.add_argument("--resume", action="store_true")
    supervise.add_argument(
        "--stall-after-checks",
        type=int,
        default=12,
        help="Stop and capture recovery evidence after repeated busy/unknown checks; 0 disables.",
    )
    supervise.add_argument(
        "--no-recovery-on-stall",
        action="store_true",
        help="Do not capture a recovery snapshot when a repeated busy/unknown stall is detected.",
    )
    sub.add_parser(
        "supervision-endurance-matrix",
        help="Validate synthetic long-run supervision resume/stall behavior without touching live Revit.",
    )
    supervision_audit = sub.add_parser(
        "supervision-endurance-audit",
        help="Audit accumulated live supervision logs against an hours-long target.",
    )
    supervision_audit.add_argument("--target-hours", type=float, default=2.0)
    supervision_audit.add_argument("--min-checks", type=int, default=24)
    supervision_audit.add_argument(
        "--allow-logs-without-live-window",
        action="store_true",
        help="Include supervision logs that do not contain main-window evidence.",
    )

    ui_exec_audit = sub.add_parser(
        "ui-execution-coverage-audit",
        help="Audit authorized live UI execution coverage from sandboxed journals.",
    )
    ui_exec_audit.add_argument(
        "--required-surfaces",
        help="Comma-separated required surfaces; defaults to the north-star UI execution coverage set.",
    )
    ui_exec_audit.add_argument(
        "--allow-without-live-evidence",
        action="store_true",
        help="Include executed entries without before/after live UI observation evidence.",
    )

    sub.add_parser(
        "supervised-ops-audit",
        help="Write an expanded supervised Revit operation audit/report for the active goal.",
    )
    sub.add_parser("workflow-library", help="List sandboxed recorded Revit workflow templates.")
    sub.add_parser("ui-workflows", help="List guarded reusable Revit UI workflow recipes.")
    sub.add_parser("ui-workflow-matrix", help="Validate guarded UI workflow recipes without running live Revit commands.")
    ui_smoke = sub.add_parser("ui-workflow-smoke-matrix", help="Run smoke-safe observation/planning prefixes for all UI workflow recipes.")
    ui_smoke.add_argument("--max-steps-per-recipe", type=int)
    ui_plan = sub.add_parser("plan-ui-workflow", help="Plan one guarded Revit UI workflow recipe.")
    ui_plan.add_argument("--name", required=True)
    ui_plan.add_argument("--parameters-json", default="{}", help="JSON object of workflow recipe parameters.")
    ui_plan.add_argument("--sheet-number")
    ui_plan.add_argument("--view-name")
    ui_plan.add_argument("--target-name")
    ui_plan.add_argument("--target-control-type")
    ui_plan.add_argument("--workflow-name")

    ui_run = sub.add_parser("run-ui-workflow", help="Run one guarded Revit UI workflow recipe with step gates.")
    ui_run.add_argument("--name", required=True)
    ui_run.add_argument("--parameters-json", default="{}", help="JSON object of workflow recipe parameters.")
    ui_run.add_argument("--sheet-number")
    ui_run.add_argument("--view-name")
    ui_run.add_argument("--target-name")
    ui_run.add_argument("--target-control-type")
    ui_run.add_argument("--workflow-name")
    ui_run.add_argument("--execute", action="store_true")
    ui_run.add_argument(
        "--approval-tokens-json",
        default="{}",
        help='JSON object mapping step indexes to exact approval tokens, e.g. {"2":"<approval-token>"}',
    )
    ui_run.add_argument("--max-steps", type=int)
    ui_run.add_argument("--continue-on-error", action="store_true")

    record = sub.add_parser("record-workflow", help="Record a task journal as a reusable workflow template.")
    record.add_argument("--source-task-id", required=True)
    record.add_argument("--name", required=True)
    record.add_argument("--description", default="")

    plan_workflow = sub.add_parser("plan-workflow", help="Dry-run a recorded workflow replay plan.")
    plan_workflow.add_argument("--name")
    plan_workflow.add_argument("--path")
    plan_workflow.add_argument("--parameters-json", default="{}", help="JSON object of workflow parameter overrides.")

    workflow_approval = sub.add_parser(
        "workflow-approval-plan",
        help="Write a fresh approval-token package for a recorded workflow replay without executing it.",
    )
    workflow_approval.add_argument("--name")
    workflow_approval.add_argument("--path")
    workflow_approval.add_argument("--parameters-json", default="{}", help="JSON object of workflow parameter overrides.")

    replay = sub.add_parser("replay-workflow", help="Replay a recorded workflow with fresh observation and approvals.")
    replay.add_argument("--name")
    replay.add_argument("--path")
    replay.add_argument("--execute", action="store_true", help="Execute guarded replay steps instead of dry-run.")
    replay.add_argument(
        "--approval-tokens-json",
        default="{}",
        help='JSON object mapping step indexes to exact approval tokens, e.g. {"2":"<approval-token>"}',
    )
    replay.add_argument("--parameters-json", default="{}", help="JSON object of workflow parameter overrides.")
    replay.add_argument("--max-steps", type=int)
    replay.add_argument("--continue-on-modal", action="store_true")
    replay.add_argument("--no-recovery-snapshot", action="store_true")

    open_cmd = sub.add_parser("open-model", help="Launch Revit with a copied local model.")
    _add_action_flags(open_cmd)
    open_cmd.add_argument("--model", required=True)
    open_cmd.add_argument("--revit-version")
    open_cmd.add_argument("--revit-exe")
    open_cmd.add_argument("--detach", action="store_true")
    open_cmd.add_argument("--allow-upgrade", action="store_true")
    open_cmd.add_argument("--worksets", choices=["all", "none", "prompt"], default=None)
    open_cmd.add_argument("--allow-model-outside-safe-root", action="store_true")

    open_choreography = sub.add_parser(
        "agent-model-open-choreography",
        help="Plan or run guarded copied-model open choreography without answering prompts.",
    )
    open_choreography.add_argument("--model", required=True)
    open_choreography.add_argument("--revit-version", default="")
    open_choreography.add_argument("--revit-exe", default="")
    open_choreography.add_argument("--expected-title-contains", default="")
    open_choreography.add_argument("--expected-path-contains", default="")
    open_choreography.add_argument("--detach", action="store_true")
    open_choreography.add_argument("--allow-upgrade", action="store_true")
    open_choreography.add_argument("--worksets", choices=["all", "none", "prompt"], default=None)
    open_choreography.add_argument("--execute-open", action="store_true")
    open_choreography.add_argument("--approval-token")
    open_choreography.add_argument("--allow-model-outside-safe-root", action="store_true")
    open_choreography.add_argument("--timeout", type=float, default=120.0)
    open_choreography.add_argument("--poll", type=float, default=2.0)
    open_choreography.add_argument("--max-prompt-checks", type=int, default=12)

    open_prompt_approval = sub.add_parser(
        "agent-model-open-prompt-approval-plan",
        help="Create approval material from model-open/startup prompt choreography without clicking.",
    )
    open_prompt_approval.add_argument("--choreography", required=True)
    open_prompt_approval.add_argument("--limit", type=int, default=10)

    open_prompt_execute = sub.add_parser(
        "agent-model-open-execute-approved-prompt",
        help="Dry-run or execute one item from private model-open prompt approval material.",
    )
    open_prompt_execute.add_argument("--approval-material", required=True)
    open_prompt_execute.add_argument("--item-id", required=True)
    open_prompt_execute.add_argument("--execute", action="store_true")
    open_prompt_execute.add_argument("--confirmation", default="")

    operation = sub.add_parser("request-operation", help="Queue an in-Revit add-in operation.")
    _add_action_flags(operation)
    operation.add_argument(
        "--operation",
        required=True,
        choices=[
            "active-document",
            "open-model",
            "export-metadata",
            "qa-snapshot",
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
        ],
    )
    operation.add_argument("--args-json", default="{}")
    operation.add_argument("--name", help="Project information parameter name.")
    operation.add_argument("--value", help="Project information parameter value.")
    operation.add_argument("--view-id", type=int)
    operation.add_argument("--view-name")
    operation.add_argument("--sheet-number")
    operation.add_argument("--save-before-close", action="store_true")
    operation.add_argument("--allow-model-write", action="store_true")
    operation.add_argument("--allow-sync", action="store_true")

    safe_command = sub.add_parser(
        "run-safe-command",
        help="Run a guarded read-only Revit bridge command wrapper.",
    )
    _add_action_flags(safe_command)
    safe_command.add_argument(
        "--name",
        required=True,
        help="Read-only safe command name: active-document, export-metadata, or qa-snapshot.",
    )
    safe_command.add_argument("--args-json", default="{}")

    addin = sub.add_parser("install-addin", help="Install the Revit add-in manifest.")
    _add_action_flags(addin)
    addin.add_argument("--revit-version", default="2025")
    addin.add_argument("--addins-root")
    addin.add_argument("--assembly")

    trust = sub.add_parser("trust-addin", help="Create a local signing cert and sign the add-in DLL.")
    _add_action_flags(trust)
    trust.add_argument("--assembly")

    addin_security = sub.add_parser(
        "addin-security-preflight",
        help="Verify Hermes add-in manifest/DLL/signature before answering unsigned-add-in prompts.",
    )
    addin_security.add_argument("--revit-version", default="2025")
    addin_security.add_argument("--addins-root")
    addin_security.add_argument("--assembly")

    qa = sub.add_parser("qa-report", help="Generate a draft QA report from metadata.")
    qa.add_argument("--output", help="Output path under the selected sandbox.")

    qa_workflow = sub.add_parser("qa-workflow", help="Run a supervised read-only QA workflow.")
    qa_workflow.add_argument("--timeout", type=float, default=120.0)
    qa_workflow.add_argument("--poll", type=float, default=1.0)
    qa_workflow.add_argument("--no-screenshot", action="store_true")
    qa_workflow.add_argument("--no-ui-tree", action="store_true")
    qa_workflow.add_argument("--focus-hwnd", type=int, help="Approved Revit window handle to focus before bridge waits.")
    qa_workflow.add_argument("--focus-approval-token", help="Exact focus approval token for --focus-hwnd.")
    qa_workflow.add_argument("--idle-nudge", action="store_true", help="Press Escape after focusing to prompt Revit Idling.")

    agent_task = sub.add_parser(
        "agent-task",
        help="Run one supported natural-language Revit QA task through guarded UI/API steps.",
    )
    agent_task.add_argument("--task", required=True, help="Plain-English Revit task request.")
    agent_task.add_argument("--timeout", type=float, default=120.0)
    agent_task.add_argument("--poll", type=float, default=1.0)
    agent_task.add_argument("--expected-revit-version", default="")
    agent_task.add_argument("--expected-title-contains", default="")
    agent_task.add_argument("--expected-path-contains", default="")
    agent_task.add_argument("--sheet-number", default="")
    agent_task.add_argument("--no-screenshot", action="store_true")
    agent_task.add_argument("--no-ui-tree", action="store_true")
    agent_task.add_argument("--plan-only", action="store_true")

    agent_session = sub.add_parser(
        "agent-session-plan",
        help="Plan a broad checkpointed Revit agent session without executing Revit actions.",
    )
    agent_session.add_argument("--objective", required=True, help="Plain-English Revit agent objective.")
    agent_session.add_argument("--model", default="", help="Copied local RVT path for model-open choreography.")
    agent_session.add_argument("--expected-revit-version", default="")
    agent_session.add_argument("--expected-title-contains", default="")
    agent_session.add_argument("--max-hours", type=float, default=4.0)
    agent_session.add_argument("--parameters-json", default="{}", help="JSON object of workflow/model parameters.")

    agent_session_run = sub.add_parser(
        "agent-session-run",
        help="Run only safe/read-only phases of a broad Revit agent session plan.",
    )
    agent_session_run.add_argument("--objective", required=True, help="Plain-English Revit agent objective.")
    agent_session_run.add_argument("--model", default="", help="Copied local RVT path for model-open dry-run.")
    agent_session_run.add_argument("--expected-revit-version", default="")
    agent_session_run.add_argument("--expected-title-contains", default="")
    agent_session_run.add_argument("--max-hours", type=float, default=4.0)
    agent_session_run.add_argument("--parameters-json", default="{}", help="JSON object of workflow/model parameters.")
    agent_session_run.add_argument("--no-open-dry-run", action="store_true")
    agent_session_run.add_argument("--bridge-refresh-timeout", type=float, default=10.0)
    agent_session_run.add_argument("--supervision-duration", type=float, default=0.0)
    agent_session_run.add_argument("--supervision-poll", type=float, default=5.0)
    agent_session_run.add_argument("--supervision-max-checks", type=int)

    agent_session_checkpoint = sub.add_parser(
        "agent-session-checkpoint",
        help="Write a read-only resumability checkpoint for a long-running Revit agent session.",
    )
    agent_session_checkpoint.add_argument("--objective", default="")
    agent_session_checkpoint.add_argument("--expected-revit-version", default="")
    agent_session_checkpoint.add_argument("--expected-title-contains", default="")
    agent_session_checkpoint.add_argument("--expected-path-contains", default="")
    agent_session_checkpoint.add_argument("--bridge-result-limit", type=int, default=10)

    agent_session_resume = sub.add_parser(
        "agent-session-resume-plan",
        help="Build a read-only resume plan from an agent-session-checkpoint artifact.",
    )
    agent_session_resume.add_argument("--checkpoint", default="")
    agent_session_resume.add_argument("--supervision-log", default="")
    agent_session_resume.add_argument("--resume-minutes", type=float, default=30.0)

    agent_session_completion = sub.add_parser(
        "agent-session-completion-audit",
        help="Audit current sandbox artifacts against the broad Revit-agent objective before any done/complete claim.",
    )
    agent_session_completion.add_argument(
        "--objective",
        default="",
        help="Plain-English Revit agent objective; defaults to the current broad agent objective.",
    )
    agent_session_completion.add_argument("--artifact-root", default="")
    agent_session_completion.add_argument("--max-artifacts", type=int, default=500)
    agent_session_completion.add_argument("--target-hours", type=float, default=4.0)

    agent_session_refresh = sub.add_parser(
        "agent-session-evidence-refresh",
        help="Run all read-only evidence collectors for the broad Revit-agent goal and write a fresh completion audit.",
    )
    agent_session_refresh.add_argument(
        "--objective",
        default="",
        help="Plain-English Revit agent objective; defaults to the current broad agent objective.",
    )
    agent_session_refresh.add_argument("--model", default="", help="Copied local RVT path for dry-run model-open choreography.")
    agent_session_refresh.add_argument("--expected-revit-version", default="")
    agent_session_refresh.add_argument("--expected-title-contains", default="")
    agent_session_refresh.add_argument("--expected-path-contains", default="")
    agent_session_refresh.add_argument("--max-hours", type=float, default=4.0)
    agent_session_refresh.add_argument("--parameters-json", default="{}", help="JSON object of workflow/model parameters.")
    agent_session_refresh.add_argument("--include-uia", action="store_true")
    agent_session_refresh.add_argument("--ui-limit", type=int, default=20)
    agent_session_refresh.add_argument("--max-artifacts", type=int, default=500)

    agent_ui_scout = sub.add_parser(
        "agent-ui-flow-scout",
        help="Observe current Revit UI and propose approval-gated candidates for an arbitrary UI objective.",
    )
    agent_ui_scout.add_argument("--objective", required=True, help="Plain-English Revit UI objective.")
    agent_ui_scout.add_argument("--max-depth", type=int, default=4)
    agent_ui_scout.add_argument("--limit", type=int, default=20)
    agent_ui_scout.add_argument("--screenshot", action="store_true")
    agent_ui_scout.add_argument("--include-uia", action="store_true")
    agent_ui_scout.add_argument("--uia-limit", type=int, default=500)

    agent_ui_approval = sub.add_parser(
        "agent-ui-flow-approval-plan",
        help="Create a redacted approval packet from an agent-ui-flow-scout artifact without executing UI.",
    )
    agent_ui_approval.add_argument("--scout", required=True, help="Path to agent_ui_flow_scout.json under the sandbox.")
    agent_ui_approval.add_argument("--limit", type=int, default=10)

    agent_ui_execute = sub.add_parser(
        "agent-ui-flow-execute-approved-candidate",
        help="Dry-run or execute one item from private agent-ui-flow approval material.",
    )
    agent_ui_execute.add_argument("--approval-material", required=True)
    agent_ui_execute.add_argument("--item-id", required=True)
    agent_ui_execute.add_argument("--execute", action="store_true")
    agent_ui_execute.add_argument("--confirmation", default="")

    agent_session_approval = sub.add_parser(
        "agent-session-approval-plan",
        help="Create a fresh approval packet for gated Revit agent session phases without executing them.",
    )
    agent_session_approval.add_argument("--objective", required=True, help="Plain-English Revit agent objective.")
    agent_session_approval.add_argument("--model", default="")
    agent_session_approval.add_argument("--expected-revit-version", default="")
    agent_session_approval.add_argument("--expected-title-contains", default="")
    agent_session_approval.add_argument("--max-hours", type=float, default=4.0)
    agent_session_approval.add_argument(
        "--parameters-json",
        default="{}",
        help="JSON object of workflow/model parameters.",
    )

    agent_session_execute = sub.add_parser(
        "agent-session-execute-approved-item",
        help="Dry-run or execute one item from private agent-session approval material.",
    )
    agent_session_execute.add_argument("--approval-material", required=True)
    agent_session_execute.add_argument("--item-id", required=True)
    agent_session_execute.add_argument("--execute", action="store_true")
    agent_session_execute.add_argument(
        "--confirmation",
        default="",
        help="Exact human phrase required when --execute is supplied: I approve <item-id>",
    )
    agent_session_execute.add_argument("--bridge-refresh-timeout", type=float, default=10.0)

    focus = sub.add_parser("focus", help="Focus Revit or a specific Revit window.")
    _add_action_flags(focus)
    focus.add_argument("--hwnd", type=int)

    press = sub.add_parser("press-key", help="Press a guarded key primitive.")
    _add_action_flags(press)
    press.add_argument("--key", required=True)

    click = sub.add_parser("click", help="Click a named button in the active dialog.")
    _add_action_flags(click)
    click.add_argument("--target", required=True)
    click.add_argument("--hwnd", type=int)

    type_text = sub.add_parser("type-text", help="Type guarded text via optional pywinauto.")
    _add_action_flags(type_text)
    type_text.add_argument("--text", required=True)

    visual_click = sub.add_parser(
        "visual-click",
        help="Click exact screen coordinates through the guarded visual fallback primitive.",
    )
    _add_action_flags(visual_click)
    visual_click.add_argument("--screen-x", type=int, required=True)
    visual_click.add_argument("--screen-y", type=int, required=True)
    visual_click.add_argument("--hwnd", type=int)
    visual_click.add_argument("--target-text", default="")
    visual_click.add_argument("--coordinate-source", default="manual")

    logs = sub.add_parser("task-log", help="List or show task journal paths.")
    logs.add_argument("--latest", action="store_true")

    return parser


def _available_commands() -> list[str]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    return []


def _csv_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _add_action_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execute", action="store_true", help="Execute instead of dry-run.")
    parser.add_argument("--approval-token", help="Exact-action approval token.")
    parser.add_argument("--expect-state", help="Verify Revit reaches this state after execution.")


def _add_project_browser_item_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", default="")
    parser.add_argument("--control-type", default="")
    parser.add_argument("--automation-id", default="")
    parser.add_argument("--class-name", default="")
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--search-depth", type=int, default=8)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--method",
        default="auto",
        choices=[
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
        ],
        help="Approved UIA method to use if activation is executed.",
    )


def _add_project_browser_visual_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-text", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--view-name", default="")
    parser.add_argument("--sheet-number", default="")
    parser.add_argument("--search-depth", type=int, default=8)
    parser.add_argument("--tree-depth", type=int, default=4)
    parser.add_argument("--include-uia", action="store_true")
    parser.add_argument("--uia-limit", type=int, default=300)
    parser.add_argument(
        "--ocr-backend",
        choices=["auto", "tesseract", "rapidocr"],
        default="auto",
    )


def _add_context_menu_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--target-name", default="")
    parser.add_argument("--control-type", default="")
    parser.add_argument("--automation-id", default="")
    parser.add_argument("--class-name", default="")
    parser.add_argument("--hwnd", type=int)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--exact", action="store_true")


def _add_context_menu_item_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True)
    parser.add_argument("--hwnd", type=int)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--method",
        default="invoke",
        choices=["invoke", "select", "click_input"],
        help="Approved UIA method to use if the menu item is executed.",
    )


_STDOUT_REDACTED_APPROVAL_COMMANDS = {
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
    "north-star-current-handoff",
    "north-star-completion-gate",
    "north-star-unblock-readiness",
    "agent-session-plan",
    "agent-session-run",
    "agent-session-checkpoint",
    "agent-session-resume-plan",
    "agent-session-completion-audit",
    "agent-session-evidence-refresh",
    "agent-ui-flow-scout",
    "agent-ui-flow-approval-plan",
    "agent-ui-flow-execute-approved-candidate",
    "agent-model-open-choreography",
    "agent-model-open-prompt-approval-plan",
    "agent-model-open-execute-approved-prompt",
    "agent-session-approval-plan",
    "agent-session-execute-approved-item",
}
_APPROVAL_TOKEN_RE = re.compile(r"\bAPPROVE:[A-Za-z0-9_.:-]+\b")


def _redact_approval_stdout(value):
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {
                "approval_token",
                "next_approval_token",
                "required_human_approval_phrase",
            }:
                redacted[key] = "<redacted approval material>" if child else child
            else:
                redacted[key] = _redact_approval_stdout(child)
        return redacted
    if isinstance(value, list):
        return [_redact_approval_stdout(child) for child in value]
    if isinstance(value, str):
        if "APPROVE:" in value or re.search(r"\bI approve\b", value, re.IGNORECASE):
            redacted = _APPROVAL_TOKEN_RE.sub("<redacted approval token>", value)
            return re.sub(
                r"\bI approve\b",
                "<redacted approval phrase>",
                redacted,
                flags=re.IGNORECASE,
            )
        return value
    return value


def _stdout_result(args: argparse.Namespace, result: dict) -> dict:
    if getattr(args, "command", None) in _STDOUT_REDACTED_APPROVAL_COMMANDS:
        return _redact_approval_stdout(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(_stdout_result(args, result), indent=2, sort_keys=True))
        return 0 if not result.get("error") else 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": _redact_approval_stdout(f"{type(exc).__name__}: {exc}"),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


def _nested_preflight_runner(args: argparse.Namespace, sandbox: Path, parent_task_id: str):
    def run(command_argv: list[str], item_id: str) -> dict:
        unsafe_flags = [
            flag
            for flag in ["--execute", "--approval-token", "--approval-tokens-json"]
            if flag in command_argv
        ]
        if unsafe_flags:
            return {
                "success": False,
                "status": "blocked_unsafe_preflight",
                "unsafe_flags": unsafe_flags,
                "reason": "Nested preflight command contains execution or approval-token flags.",
            }
        safe_item_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", item_id).strip("-") or "approval-item"
        child_argv = ["--sandbox", str(sandbox)]
        if getattr(args, "allow_sandbox_outside_safe_root", False):
            child_argv.append("--allow-sandbox-outside-safe-root")
        child_argv.extend(["--task-id", f"{parent_task_id}-preflight-{safe_item_id}"])
        child_argv.extend(command_argv)
        child_args = build_parser().parse_args(child_argv)
        return dispatch(child_args)

    return run


def dispatch(args: argparse.Namespace) -> dict:
    sandbox = _resolve_sandbox(args)
    journal = TaskJournal(sandbox, args.task_id)
    observer = RevitWindowObserver()
    bridge = RevitBridgeClient(sandbox)

    command = args.command
    if command == "serve":
        from .server import serve_control_server

        journal.write_entry(
            {
                "command": command,
                "requested_action": {"host": args.host, "port": args.port},
                "risk_classification": {
                    "risk": "low",
                    "reason": "Local HTTP control server; routed commands still use normal CLI safety gates.",
                },
                "approval_status": {"allowed": True, "reason": "Local command interface startup."},
                "result": {"status": "starting", "success": True},
                "output_files": [],
            }
        )
        return serve_control_server(
            host=args.host,
            port=args.port,
            sandbox=sandbox,
            allow_sandbox_outside_safe_root=(
                args.allow_sandbox_outside_safe_root or truthy_env(ENV_ALLOW_EXTERNAL_SANDBOX)
            ),
        )
    if command == "health":
        result = observer.health()
        result["revit_installs"] = installed_revit_versions()
        result["default_test_model"] = default_test_model_info()
    elif command == "version-support":
        result = {
            "success": True,
            "read_only": True,
            "support": version_support_matrix(installed_revit_versions()),
        }
    elif command == "north-star-status":
        result = build_north_star_status(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
        )
    elif command == "north-star-audit":
        result = run_north_star_audit(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
        )
    elif command == "north-star-approval-plan":
        result = build_north_star_approval_plan(
            journal,
            default_sheet_number=args.sheet_number,
        )
    elif command == "north-star-approval-preflight":
        result = build_north_star_approval_preflight(
            journal,
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
            run_preflight=_nested_preflight_runner(args, sandbox, journal.task_id),
        )
    elif command == "north-star-ready-approvals":
        result = build_north_star_ready_approvals(
            journal,
            default_sheet_number=args.sheet_number,
        )
    elif command == "north-star-next-approval":
        result = build_north_star_next_approval(
            journal,
            default_sheet_number=args.sheet_number,
        )
    elif command == "north-star-waiting-state":
        result = build_north_star_waiting_state(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-approval-phrase-verify":
        result = build_north_star_approval_phrase_verify(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            phrase=args.phrase,
            phrase_source=args.phrase_source,
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-approved-execution-preview":
        result = build_north_star_approved_execution_preview(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            phrase=args.phrase,
            phrase_source=args.phrase_source,
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-approval-verify":
        result = build_north_star_approval_verify(
            journal,
            default_sheet_number=args.sheet_number,
            approval_token=args.approval_token,
        )
    elif command == "north-star-watch":
        result = run_north_star_watch(
            journal,
            observer,
            bridge,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
            refresh_approval_preflight=args.refresh_approval_preflight,
            publish_current_handoff=args.publish_current_handoff,
            run_preflight=_nested_preflight_runner(args, sandbox, journal.task_id)
            if args.refresh_approval_preflight
            else None,
            checks=args.checks,
            poll_seconds=args.poll,
        )
    elif command == "north-star-resume-check":
        result = run_north_star_resume_check(
            journal,
            observer,
            bridge,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
            timeout=args.timeout,
            poll=args.poll,
        )
    elif command == "north-star-human-gate-packet":
        result = build_north_star_human_gate_packet(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-next-human-action":
        result = build_north_star_next_human_action_card(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-human-unblock-brief":
        result = build_north_star_human_unblock_brief(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-agent-stop-status":
        result = build_north_star_agent_stop_status(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-blocked-ledger":
        result = build_north_star_blocked_ledger(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-current-handoff":
        result = build_north_star_current_handoff(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-refresh-sequence":
        result = build_north_star_refresh_sequence(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            default_sheet_number=args.sheet_number,
            revit_version=args.revit_version,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "north-star-completion-gate":
        result = build_north_star_completion_gate(
            journal,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
        )
    elif command == "north-star-stable-artifact-scan":
        result = build_north_star_stable_artifact_scan(journal)
    elif command == "north-star-unblock-readiness":
        result = build_north_star_unblock_readiness(journal)
    elif command == "transport-safety-matrix":
        result = build_transport_safety_matrix(journal, repo_root=Path.cwd())
    elif command == "status":
        result = observer.status()
        result["active_document"] = bridge.active_document_status()
    elif command == "list-processes":
        result = observer.list_processes()
    elif command == "list-revit-installs":
        result = {
            "success": True,
            "installs": installed_revit_versions(),
            "default_test_model": default_test_model_info(),
        }
    elif command == "list-windows":
        result = observer.list_windows(include_all=args.all)
    elif command == "list-dialogs":
        result = observer.list_dialogs()
    elif command == "known-dialogs":
        rules = list_known_dialog_rules()
        result = {"success": True, "count": len(rules), "rules": rules}
    elif command == "dialog-rule-library":
        result = list_dialog_rule_library(sandbox)
    elif command == "dialog-workflows":
        result = list_dialog_workflows()
    elif command == "dialog-workflow-matrix":
        result = validate_dialog_workflow_matrix(journal)
    elif command == "record-dialog-rule":
        result = record_dialog_rule(
            sandbox,
            rule_id=args.rule_id,
            title_terms=args.title_term,
            text_terms=args.text_term,
            button_terms=args.button_term,
            risk=args.risk,
            recommended_action=args.recommended_action,
            reason=args.reason,
        )
    elif command == "classify-dialog":
        result = classify_dialog(
            args.title,
            args.text,
            args.button,
            extra_rules=load_learned_dialog_rules(sandbox),
        )
    elif command == "plan-dialog-response":
        result = plan_dialog_response(title=args.title, text=args.text, buttons=args.button)
    elif command == "plan-current-dialog-response":
        result = plan_current_dialog_response(
            journal,
            observer,
            title_contains=args.title_contains,
            index=args.index,
            use_ocr=args.use_ocr,
            ocr_backend=args.ocr_backend,
        )
    elif command == "screenshot":
        output = _output_path(journal, args.output, journal.default_screenshot_path("bmp"))
        result = observer.screenshot(output, hwnd=args.hwnd)
    elif command == "ocr-screenshot":
        result = ocr_screenshot(journal, observer, hwnd=args.hwnd, backend=args.backend)
    elif command == "ocr-health":
        result = ocr_health()
    elif command == "ui-tree":
        result = observer.ui_tree(hwnd=args.hwnd, max_depth=max(0, args.max_depth))
        output = _output_path(journal, args.output, journal.run_dir / "ui_tree.json")
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(output)
    elif command == "uia-tree":
        result = uia_tree(
            hwnd=args.hwnd,
            max_depth=max(0, args.max_depth),
            limit=max(0, args.limit),
            observer=observer,
        )
        output = _output_path(journal, args.output, journal.run_dir / "uia_tree.json")
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(output)
    elif command == "uia-find-control":
        result = uia_find_controls(
            name=args.name,
            control_type=args.control_type,
            automation_id=args.automation_id,
            class_name=args.class_name,
            hwnd=args.hwnd,
            max_depth=max(0, args.max_depth),
            limit=max(0, args.limit),
            exact=args.exact,
            observer=observer,
        )
        output = _output_path(journal, args.output, journal.run_dir / "uia_control_matches.json")
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(output)
    elif command == "uia-control-details":
        result = uia_control_details(
            name=args.name,
            control_type=args.control_type,
            automation_id=args.automation_id,
            class_name=args.class_name,
            hwnd=args.hwnd,
            max_depth=max(0, args.max_depth),
            limit=max(0, args.limit),
            exact=args.exact,
            observer=observer,
        )
        output = _output_path(journal, args.output, journal.run_dir / "uia_control_details.json")
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(output)
    elif command == "uia-method-matrix":
        result = validate_uia_method_matrix(journal)
    elif command == "ribbon-actions":
        result = list_ribbon_actions()
    elif command == "ribbon-action-matrix":
        result = validate_ribbon_action_matrix(journal)
    elif command == "plan-ribbon-action":
        result = plan_ribbon_action(
            journal,
            observer,
            name=args.name,
            hwnd=args.hwnd,
            max_depth=args.max_depth,
            limit=args.limit,
        )
    elif command == "ribbon-action":
        return {
            **run_ribbon_action(
                journal,
                observer,
                name=args.name,
                hwnd=args.hwnd,
                max_depth=args.max_depth,
                limit=args.limit,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "context-menu-actions":
        result = list_context_menu_actions()
    elif command == "context-menu-action-matrix":
        result = validate_context_menu_action_matrix(journal)
    elif command == "context-menu-snapshot":
        result = snapshot_context_menu(
            journal,
            observer,
            hwnd=args.hwnd,
            max_depth=args.max_depth,
            limit=args.limit,
        )
    elif command == "plan-context-menu-action":
        result = plan_context_menu_action(
            journal,
            observer,
            name=args.name,
            target_name=args.target_name,
            control_type=args.control_type,
            automation_id=args.automation_id,
            class_name=args.class_name,
            hwnd=args.hwnd,
            max_depth=args.max_depth,
            limit=args.limit,
            exact=True if args.exact else None,
        )
    elif command == "context-menu-action":
        return {
            **run_context_menu_action(
                journal,
                observer,
                name=args.name,
                target_name=args.target_name,
                control_type=args.control_type,
                automation_id=args.automation_id,
                class_name=args.class_name,
                hwnd=args.hwnd,
                max_depth=args.max_depth,
                limit=args.limit,
                exact=True if args.exact else None,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "plan-context-menu-item":
        result = plan_context_menu_item(
            journal,
            observer,
            item=args.item,
            hwnd=args.hwnd,
            max_depth=args.max_depth,
            limit=args.limit,
            method=args.method,
        )
    elif command == "context-menu-select-item":
        return {
            **run_context_menu_item(
                journal,
                observer,
                item=args.item,
                hwnd=args.hwnd,
                max_depth=args.max_depth,
                limit=args.limit,
                method=args.method,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "action-approval-matrix":
        result = validate_action_approval_matrix(journal, observer)
    elif command == "find-control":
        result = observer.find_controls(
            text=args.text,
            class_name=args.class_name,
            hwnd=args.hwnd,
            max_depth=max(0, args.max_depth),
            limit=max(0, args.limit),
            exact=args.exact,
        )
        output = _output_path(journal, args.output, journal.run_dir / "control_matches.json")
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(output)
    elif command == "project-browser-snapshot":
        result = capture_project_browser_snapshot(
            journal,
            observer,
            search_depth=args.search_depth,
            tree_depth=args.tree_depth,
            include_uia=args.include_uia,
            uia_limit=args.uia_limit,
            include_ocr=args.include_ocr,
            ocr_backend=args.ocr_backend,
        )
    elif command == "project-browser-plan-navigation":
        result = plan_project_browser_navigation(
            journal,
            observer,
            bridge,
            query=args.query,
            view_name=args.view_name,
            sheet_number=args.sheet_number,
            view_type=args.view_type,
            limit=args.limit,
            search_depth=args.search_depth,
            tree_depth=args.tree_depth,
            include_uia=args.include_uia,
            uia_limit=args.uia_limit,
            include_ocr=args.include_ocr,
            ocr_backend=args.ocr_backend,
        )
    elif command == "project-browser-plan-visual-activation":
        result = plan_project_browser_visual_activation(
            journal,
            observer,
            target_text=args.target_text,
            query=args.query,
            view_name=args.view_name,
            sheet_number=args.sheet_number,
            search_depth=args.search_depth,
            tree_depth=args.tree_depth,
            include_uia=args.include_uia,
            uia_limit=args.uia_limit,
            ocr_backend=args.ocr_backend,
        )
    elif command == "project-browser-visual-activate":
        return {
            **run_project_browser_visual_activation(
                journal,
                observer,
                target_text=args.target_text,
                query=args.query,
                view_name=args.view_name,
                sheet_number=args.sheet_number,
                search_depth=args.search_depth,
                tree_depth=args.tree_depth,
                include_uia=args.include_uia,
                uia_limit=args.uia_limit,
                ocr_backend=args.ocr_backend,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "project-browser-plan-activation":
        result = plan_project_browser_item_activation(
            journal,
            observer,
            name=args.name,
            control_type=args.control_type,
            automation_id=args.automation_id,
            class_name=args.class_name,
            exact=args.exact,
            search_depth=args.search_depth,
            max_depth=args.max_depth,
            limit=args.limit,
            method=args.method,
        )
    elif command == "project-browser-activate-item":
        return {
            **run_project_browser_item_activation(
                journal,
                observer,
                name=args.name,
                control_type=args.control_type,
                automation_id=args.automation_id,
                class_name=args.class_name,
                exact=args.exact,
                search_depth=args.search_depth,
                max_depth=args.max_depth,
                limit=args.limit,
                method=args.method,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "properties-palette-snapshot":
        result = capture_properties_palette_snapshot(
            journal,
            observer,
            search_depth=args.search_depth,
            tree_depth=args.tree_depth,
            include_uia=args.include_uia,
            uia_limit=args.uia_limit,
            include_ocr=args.include_ocr,
            ocr_backend=args.ocr_backend,
        )
    elif command == "wait-until-idle":
        result = _wait_until_idle(observer, args.timeout, args.poll)
    elif command == "wait-for-window":
        result = _wait_for_window(observer, args.title_contains, args.timeout, args.poll)
    elif command == "wait-for-dialog":
        result = _wait_for_dialog(observer, args.title_contains, args.timeout, args.poll)
    elif command == "wait-model-ready":
        result = wait_model_ready(
            journal,
            observer,
            bridge,
            timeout=args.timeout,
            poll=args.poll,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_revit_version=args.expected_revit_version,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
            require_bridge=not args.no_require_bridge,
            stop_on_modal=not args.no_stop_on_modal,
        )
    elif command == "export-metadata":
        output = _output_path(journal, args.output, journal.default_metadata_path("json"))
        result = bridge.export_metadata(output)
    elif command == "find-view":
        result = find_views(
            journal,
            bridge,
            query=args.query,
            view_name=args.view_name,
            sheet_number=args.sheet_number,
            view_type=args.view_type,
            limit=args.limit,
        )
    elif command == "bridge-results":
        result = _bridge_results(bridge, command_id=args.command_id, limit=args.limit)
    elif command == "bridge-status":
        result = bridge.bridge_status()
    elif command == "verify-bridge-build":
        result = bridge.verify_loaded_build()
    elif command == "bridge-readiness":
        result = bridge.bridge_readiness(
            revit_version=args.revit_version,
            addins_root=Path(args.addins_root) if args.addins_root else None,
            assembly_path=Path(args.assembly) if args.assembly else None,
        )
    elif command == "bridge-restart-validation-plan":
        result = bridge_restart_validation_plan(
            journal,
            bridge,
            revit_version=args.revit_version,
            addins_root=Path(args.addins_root) if args.addins_root else None,
            assembly_path=Path(args.assembly) if args.assembly else None,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
        )
    elif command == "bridge-post-restart-validation":
        result = bridge_post_restart_validation(
            journal,
            observer,
            bridge,
            repo_root=Path.cwd(),
            command_names=_available_commands(),
            revit_version=args.revit_version,
            addins_root=Path(args.addins_root) if args.addins_root else None,
            assembly_path=Path(args.assembly) if args.assembly else None,
            expected_title_contains=args.expected_title_contains,
            expected_path_contains=args.expected_path_contains,
            expected_view_name=args.expected_view_name,
            expected_view_type=args.expected_view_type,
            timeout=args.timeout,
            poll=args.poll,
        )
    elif command == "wait-bridge-result":
        result = bridge.wait_for_command_result(
            args.command_id,
            timeout=args.timeout,
            poll=args.poll,
        )
    elif command == "recovery-snapshot":
        result = capture_recovery_snapshot(
            journal,
            observer,
            bridge,
            capture_screenshot=not args.no_screenshot,
            capture_ui_tree=not args.no_ui_tree,
            max_depth=args.max_depth,
            bridge_result_limit=args.bridge_result_limit,
        )
    elif command == "recovery-drill-matrix":
        result = validate_recovery_drill_matrix(journal)
    elif command == "supervise-session":
        result = supervise_session(
            journal,
            observer,
            bridge,
            duration=args.duration,
            poll=args.poll,
            max_checks=args.max_checks,
            stop_on_modal=not args.continue_on_modal,
            bridge_result_limit=args.bridge_result_limit,
            resume=args.resume,
            stall_after_checks=args.stall_after_checks,
            recovery_on_stall=not args.no_recovery_on_stall,
        )
    elif command == "supervision-endurance-matrix":
        result = validate_supervision_endurance_matrix(journal)
    elif command == "supervision-endurance-audit":
        result = audit_supervision_endurance(
            journal,
            target_hours=args.target_hours,
            min_checks=args.min_checks,
            require_live_window=not args.allow_logs_without_live_window,
        )
    elif command == "ui-execution-coverage-audit":
        result = audit_ui_execution_coverage(
            journal,
            required_surfaces=_csv_list(args.required_surfaces),
            require_live_evidence=not args.allow_without_live_evidence,
        )
    elif command == "supervised-ops-audit":
        result = run_supervised_ops_audit(journal)
    elif command == "workflow-library":
        result = list_workflows(sandbox)
    elif command == "ui-workflows":
        result = list_ui_workflows()
    elif command == "ui-workflow-matrix":
        result = validate_ui_workflow_matrix(journal)
    elif command == "ui-workflow-smoke-matrix":
        result = run_ui_workflow_smoke_matrix(
            journal,
            observe_func=observer.status,
            command_runner=_ui_workflow_smoke_command_runner(
                sandbox,
                parent_task_id=journal.task_id,
                allow_sandbox_outside_safe_root=args.allow_sandbox_outside_safe_root,
            ),
            max_steps_per_recipe=args.max_steps_per_recipe,
        )
    elif command == "plan-ui-workflow":
        parameters = _json_object_arg(args.parameters_json, "parameters-json")
        for key in ("sheet_number", "view_name", "target_name", "target_control_type", "workflow_name"):
            value = getattr(args, key, None)
            if value:
                parameters[key] = value
        result = plan_ui_workflow(journal, name=args.name, parameters=parameters)
    elif command == "run-ui-workflow":
        parameters = _json_object_arg(args.parameters_json, "parameters-json")
        for key in ("sheet_number", "view_name", "target_name", "target_control_type", "workflow_name"):
            value = getattr(args, key, None)
            if value:
                parameters[key] = value
        result = run_ui_workflow(
            journal,
            name=args.name,
            parameters=parameters,
            dry_run=not args.execute,
            approval_tokens=_approval_tokens(args.approval_tokens_json),
            max_steps=args.max_steps,
            stop_on_error=not args.continue_on_error,
            observe_func=observer.status,
            command_runner=_ui_workflow_command_runner(
                sandbox,
                parent_task_id=journal.task_id,
                allow_sandbox_outside_safe_root=args.allow_sandbox_outside_safe_root,
            ),
        )
    elif command == "record-workflow":
        result = record_workflow(
            sandbox,
            source_task_id=args.source_task_id,
            name=args.name,
            description=args.description,
        )
    elif command == "plan-workflow":
        result = plan_workflow_replay(
            sandbox,
            name=args.name,
            path=Path(args.path) if args.path else None,
            parameters=_json_object_arg(args.parameters_json, "parameters-json"),
        )
    elif command == "workflow-approval-plan":
        result = plan_workflow_approvals(
            sandbox,
            journal,
            name=args.name,
            path=Path(args.path) if args.path else None,
            parameters=_json_object_arg(args.parameters_json, "parameters-json"),
        )
    elif command == "replay-workflow":
        result = replay_workflow(
            sandbox,
            journal,
            observer,
            name=args.name,
            path=Path(args.path) if args.path else None,
            dry_run=not args.execute,
            approval_tokens=_approval_tokens(args.approval_tokens_json),
            parameters=_json_object_arg(args.parameters_json, "parameters-json"),
            stop_on_modal=not args.continue_on_modal,
            max_steps=args.max_steps,
            recovery_snapshot_on_stop=not args.no_recovery_snapshot,
        )
    elif command == "open-model":
        return {
            **open_model(
                Path(args.model),
                journal,
                revit_version=args.revit_version,
                revit_exe=args.revit_exe,
                detach=args.detach,
                allow_upgrade=args.allow_upgrade,
                worksets=args.worksets,
                dry_run=not args.execute,
                approval_token=args.approval_token,
                allow_outside_safe_root=args.allow_model_outside_safe_root,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-model-open-choreography":
        return {
            **run_model_open_choreography(
                journal,
                observer,
                bridge,
                model_path=Path(args.model),
                revit_version=args.revit_version,
                revit_exe=args.revit_exe,
                expected_title_contains=args.expected_title_contains,
                expected_path_contains=args.expected_path_contains,
                detach=args.detach,
                allow_upgrade=args.allow_upgrade,
                worksets=args.worksets,
                execute_open=args.execute_open,
                approval_token=args.approval_token,
                allow_model_outside_safe_root=args.allow_model_outside_safe_root,
                timeout=args.timeout,
                poll=args.poll,
                max_prompt_checks=args.max_prompt_checks,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-model-open-prompt-approval-plan":
        return {
            **build_model_open_prompt_approval_plan(
                journal,
                choreography_path=Path(args.choreography),
                limit=args.limit,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-model-open-execute-approved-prompt":
        return {
            **execute_model_open_prompt_approved_step(
                journal,
                observer,
                approval_material_path=Path(args.approval_material),
                item_id=args.item_id,
                execute=args.execute,
                confirmation=args.confirmation,
            ),
            "journal": journal.describe(),
        }
    elif command == "request-operation":
        op_args = _operation_args(args)
        return {
            **queue_operation(
                journal,
                OperationRequest(
                    operation=args.operation,
                    args=op_args,
                    dry_run=not args.execute,
                    approval_token=args.approval_token,
                    allow_model_write=args.allow_model_write,
                    allow_sync=args.allow_sync,
                ),
            ),
            "journal": journal.describe(),
        }
    elif command == "run-safe-command":
        safe_args = _json_object_arg(args.args_json, "args-json")
        safe_name = args.name.strip().lower()
        wrapper_payload = {"name": safe_name, "args": safe_args}
        wrapper_decision = classify_action("run-safe-command", wrapper_payload)
        if wrapper_decision.decision != "allow":
            result = {
                "success": False,
                "error": wrapper_decision.reason,
                "safe_command": {
                    "name": safe_name,
                    "args": safe_args,
                    "delegates_to": None,
                },
                "wrapper_policy": wrapper_decision.to_dict(),
            }
        else:
            result = queue_operation(
                journal,
                OperationRequest(
                    operation=safe_name,
                    args=safe_args,
                    dry_run=not args.execute,
                    approval_token=args.approval_token,
                    allow_model_write=False,
                    allow_sync=False,
                ),
            )
            result["safe_command"] = {
                "name": safe_name,
                "args": safe_args,
                "delegates_to": "request-operation",
                "delegated_operation": safe_name,
            }
            result["wrapper_policy"] = wrapper_decision.to_dict()
        return {**result, "journal": journal.describe()}
    elif command == "install-addin":
        return {
            **install_addin(
                journal,
                revit_version=args.revit_version,
                addins_root=Path(args.addins_root) if args.addins_root else None,
                assembly_path=Path(args.assembly) if args.assembly else None,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "trust-addin":
        return {
            **trust_addin(
                journal,
                assembly_path=Path(args.assembly) if args.assembly else None,
                dry_run=not args.execute,
                approval_token=args.approval_token,
            ),
            "journal": journal.describe(),
        }
    elif command == "addin-security-preflight":
        return {
            **addin_security_preflight(
                journal,
                revit_version=args.revit_version,
                addins_root=Path(args.addins_root) if args.addins_root else None,
                assembly_path=Path(args.assembly) if args.assembly else None,
            ),
            "journal": journal.describe(),
        }
    elif command == "qa-report":
        output = _output_path(journal, args.output, journal.run_dir / "qa_report.md") if args.output else None
        return {**generate_qa_report(journal, output), "journal": journal.describe()}
    elif command == "qa-workflow":
        return {
            **run_readonly_qa_workflow(
                journal,
                observer,
                bridge,
                timeout=args.timeout,
                poll=args.poll,
                capture_screenshot=not args.no_screenshot,
                capture_ui_tree=not args.no_ui_tree,
                focus_hwnd=args.focus_hwnd,
                focus_approval_token=args.focus_approval_token,
                idle_nudge=args.idle_nudge,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-task":
        return {
            **run_agent_task(
                journal,
                observer,
                bridge,
                task_text=args.task,
                timeout=args.timeout,
                poll=args.poll,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                expected_path_contains=args.expected_path_contains,
                sheet_number=args.sheet_number,
                capture_screenshot=not args.no_screenshot,
                capture_ui_tree=not args.no_ui_tree,
                plan_only=args.plan_only,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-plan":
        return {
            **plan_agent_session(
                journal,
                objective=args.objective,
                model_path=args.model,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                max_hours=args.max_hours,
                parameters=_json_object_arg(args.parameters_json, "parameters-json"),
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-run":
        return {
            **run_agent_session(
                journal,
                observer,
                bridge,
                objective=args.objective,
                model_path=args.model,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                max_hours=args.max_hours,
                parameters=_json_object_arg(args.parameters_json, "parameters-json"),
                run_open_dry_run=not args.no_open_dry_run,
                bridge_refresh_timeout=args.bridge_refresh_timeout,
                supervision_duration=args.supervision_duration,
                supervision_poll=args.supervision_poll,
                supervision_max_checks=args.supervision_max_checks,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-checkpoint":
        return {
            **write_agent_session_checkpoint(
                journal,
                observer,
                bridge,
                objective=args.objective,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                expected_path_contains=args.expected_path_contains,
                bridge_result_limit=args.bridge_result_limit,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-resume-plan":
        return {
            **build_agent_session_resume_plan(
                journal,
                checkpoint_path=Path(args.checkpoint) if args.checkpoint else None,
                supervision_log_path=Path(args.supervision_log) if args.supervision_log else None,
                resume_minutes=args.resume_minutes,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-completion-audit":
        return {
            **build_agent_session_completion_audit(
                journal,
                objective=args.objective,
                artifact_root=Path(args.artifact_root) if args.artifact_root else None,
                max_artifacts=args.max_artifacts,
                target_hours=args.target_hours,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-evidence-refresh":
        return {
            **refresh_agent_session_evidence(
                journal,
                observer,
                bridge,
                objective=args.objective,
                model_path=args.model,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                expected_path_contains=args.expected_path_contains,
                max_hours=args.max_hours,
                parameters=_json_object_arg(args.parameters_json, "parameters-json"),
                include_uia=args.include_uia,
                ui_limit=args.ui_limit,
                max_artifacts=args.max_artifacts,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-ui-flow-scout":
        return {
            **scout_agent_ui_flow(
                journal,
                observer,
                objective=args.objective,
                max_depth=args.max_depth,
                limit=args.limit,
                capture_screenshot=args.screenshot,
                include_uia=args.include_uia,
                uia_limit=args.uia_limit,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-ui-flow-approval-plan":
        return {
            **build_ui_flow_candidate_approval_plan(
                journal,
                scout_path=Path(args.scout),
                limit=args.limit,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-ui-flow-execute-approved-candidate":
        return {
            **execute_ui_flow_approved_candidate(
                journal,
                observer,
                approval_material_path=Path(args.approval_material),
                item_id=args.item_id,
                execute=args.execute,
                confirmation=args.confirmation,
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-approval-plan":
        return {
            **build_agent_session_approval_plan(
                journal,
                objective=args.objective,
                model_path=args.model,
                expected_revit_version=args.expected_revit_version,
                expected_title_contains=args.expected_title_contains,
                max_hours=args.max_hours,
                parameters=_json_object_arg(args.parameters_json, "parameters-json"),
            ),
            "journal": journal.describe(),
        }
    elif command == "agent-session-execute-approved-item":
        return {
            **execute_agent_session_approved_item(
                journal,
                observer,
                bridge,
                approval_material_path=Path(args.approval_material),
                item_id=args.item_id,
                execute=args.execute,
                confirmation=args.confirmation,
                bridge_refresh_timeout=args.bridge_refresh_timeout,
                ui_command_runner=_ui_workflow_command_runner(
                    sandbox,
                    parent_task_id=journal.task_id,
                    allow_sandbox_outside_safe_root=args.allow_sandbox_outside_safe_root,
                ),
            ),
            "journal": journal.describe(),
        }
    elif command in {"focus", "press-key", "click", "type-text", "uia-invoke", "visual-click"}:
        executor = SafeActionExecutor(observer, journal)
        payload = _action_payload(args)
        return {
            **executor.run(
                ActionRequest(
                    action=command,
                    payload=payload,
                    dry_run=not args.execute,
                    approval_token=args.approval_token,
                )
            ),
            "journal": journal.describe(),
        }
    elif command == "task-log":
        result = _task_log(sandbox, latest=args.latest)
    else:
        result = {"success": False, "error": f"Unknown command: {command}"}

    _log_observation(journal, command, result)
    result["journal"] = journal.describe()
    return result


def _resolve_sandbox(args: argparse.Namespace) -> Path:
    sandbox = Path(args.sandbox) if args.sandbox else default_sandbox_root()
    allow_outside = args.allow_sandbox_outside_safe_root or truthy_env(
        ENV_ALLOW_EXTERNAL_SANDBOX
    )
    error = validate_sandbox_root(sandbox, allow_outside_safe_root=allow_outside)
    if error:
        raise ValueError(
            "Sandbox must stay inside the known safe copied project area unless "
            "--allow-sandbox-outside-safe-root is supplied for tests/local development: "
            + error
        )
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def _output_path(journal: TaskJournal, raw: str | None, default: Path) -> Path:
    output = Path(raw) if raw else default
    if not output.is_absolute():
        output = journal.run_dir / output
    error = validate_output_path(output, journal.sandbox)
    if error:
        raise ValueError(error)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _action_payload(args: argparse.Namespace) -> dict:
    payload: dict = {}
    if getattr(args, "hwnd", None):
        payload["hwnd"] = args.hwnd
    if getattr(args, "key", None):
        payload["key"] = args.key
    if getattr(args, "target", None):
        payload["target"] = args.target
    if getattr(args, "text", None):
        payload["text"] = args.text
    if getattr(args, "screen_x", None) is not None:
        payload["screen_x"] = args.screen_x
    if getattr(args, "screen_y", None) is not None:
        payload["screen_y"] = args.screen_y
    if getattr(args, "target_text", None):
        payload["target_text"] = args.target_text
    if getattr(args, "coordinate_source", None):
        payload["coordinate_source"] = args.coordinate_source
    if getattr(args, "name", None):
        payload["name"] = args.name
    if getattr(args, "control_type", None):
        payload["control_type"] = args.control_type
    if getattr(args, "automation_id", None):
        payload["automation_id"] = args.automation_id
    if getattr(args, "class_name", None):
        payload["class_name"] = args.class_name
    if getattr(args, "max_depth", None) is not None:
        payload["max_depth"] = args.max_depth
    if getattr(args, "limit", None) is not None:
        payload["limit"] = args.limit
    if getattr(args, "exact", False):
        payload["exact"] = True
    if getattr(args, "method", None):
        payload["method"] = args.method
    if getattr(args, "expect_state", None):
        payload["expect_state"] = args.expect_state
    return payload


def _operation_args(args: argparse.Namespace) -> dict:
    data = _json_object_arg(args.args_json, "args-json")
    if args.name:
        data["name"] = args.name
    if args.value is not None:
        data["value"] = args.value
    if getattr(args, "view_id", None) is not None:
        data["view_id"] = args.view_id
    if getattr(args, "view_name", None):
        data["view_name"] = args.view_name
    if getattr(args, "sheet_number", None):
        data["sheet_number"] = args.sheet_number
    if args.save_before_close:
        data["save_before_close"] = True
    return data


def _approval_tokens(raw: str) -> dict[int, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --approval-tokens-json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("--approval-tokens-json must decode to an object.")
    tokens: dict[int, str] = {}
    for key, value in data.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Approval token key must be a step index: {key!r}") from exc
        if not isinstance(value, str):
            raise ValueError(f"Approval token for step {index} must be a string.")
        tokens[index] = value
    return tokens


def _ui_workflow_command_runner(
    sandbox: Path,
    *,
    parent_task_id: str,
    allow_sandbox_outside_safe_root: bool,
):
    def runner(step_argv: list[str], step_index: int) -> dict:
        from .server import run_control_command

        argv = ["--sandbox", str(sandbox)]
        if allow_sandbox_outside_safe_root:
            argv.append("--allow-sandbox-outside-safe-root")
        argv.extend(["--task-id", f"{parent_task_id}-step-{step_index}"])
        argv.extend(step_argv)
        return run_control_command(
            {"argv": argv},
            allow_sandbox_outside_safe_root=allow_sandbox_outside_safe_root,
        )

    return runner


def _ui_workflow_smoke_command_runner(
    sandbox: Path,
    *,
    parent_task_id: str,
    allow_sandbox_outside_safe_root: bool,
):
    def runner(step_argv: list[str], recipe_name: str, step_index: int) -> dict:
        from .server import run_control_command

        recipe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", recipe_name).strip("-") or "recipe"
        argv = ["--sandbox", str(sandbox)]
        if allow_sandbox_outside_safe_root:
            argv.append("--allow-sandbox-outside-safe-root")
        argv.extend(["--task-id", f"{parent_task_id}-{recipe_slug}-step-{step_index}"])
        argv.extend(step_argv)
        return run_control_command(
            {"argv": argv},
            allow_sandbox_outside_safe_root=allow_sandbox_outside_safe_root,
        )

    return runner


def _json_object_arg(raw: str, arg_name: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --{arg_name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"--{arg_name} must decode to an object.")
    return data


def _wait_until_idle(observer: RevitWindowObserver, timeout: float, poll: float) -> dict:
    deadline = time.monotonic() + max(0.0, timeout)
    observations = []
    while True:
        status = observer.status()
        observations.append(
            {
                "timestamp_index": len(observations),
                "state": status.get("state"),
                "revit_running": status.get("revit_running"),
                "active_dialog_count": len(status.get("active_dialogs") or []),
            }
        )
        if status.get("state") in {"idle", "not_running", "unsupported"}:
            return {
                "success": status.get("state") == "idle",
                "state": status.get("state"),
                "observations": observations,
                "final_status": status,
            }
        if time.monotonic() >= deadline:
            return {
                "success": False,
                "state": status.get("state"),
                "observations": observations,
                "final_status": status,
                "error": "Timed out waiting for idle Revit state.",
            }
        time.sleep(max(0.1, poll))


def _wait_for_window(
    observer: RevitWindowObserver,
    title_contains: str,
    timeout: float,
    poll: float,
) -> dict:
    needle = title_contains.lower()
    deadline = time.monotonic() + max(0.0, timeout)
    observations = []
    while True:
        listing = observer.list_windows()
        windows = listing.get("windows") or []
        matches = [
            window
            for window in windows
            if not needle or needle in str(window.get("title", "")).lower()
        ]
        observations.append({"window_count": len(windows), "match_count": len(matches)})
        if matches:
            return {"success": True, "matches": matches, "observations": observations}
        if time.monotonic() >= deadline:
            return {
                "success": False,
                "matches": [],
                "observations": observations,
                "error": "Timed out waiting for Revit window.",
            }
        time.sleep(max(0.1, poll))


def _wait_for_dialog(
    observer: RevitWindowObserver,
    title_contains: str,
    timeout: float,
    poll: float,
) -> dict:
    needle = title_contains.lower()
    deadline = time.monotonic() + max(0.0, timeout)
    observations = []
    while True:
        listing = observer.list_dialogs()
        dialogs = listing.get("dialogs") or []
        matches = [
            dialog
            for dialog in dialogs
            if not needle or needle in str(dialog.get("title", "")).lower()
        ]
        observations.append({"dialog_count": len(dialogs), "match_count": len(matches)})
        if matches:
            return {"success": True, "matches": matches, "observations": observations}
        if time.monotonic() >= deadline:
            return {
                "success": False,
                "matches": [],
                "observations": observations,
                "error": "Timed out waiting for Revit dialog.",
            }
        time.sleep(max(0.1, poll))


def _task_log(sandbox: Path, latest: bool = False) -> dict:
    root = sandbox / "revit_operator_runs"
    if not root.exists():
        return {"success": True, "runs": []}
    runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    data = [
        {
            "task_id": path.name,
            "run_dir": str(path),
            "journal": str(path / "journal.jsonl"),
            "summary": str(path / "summary.md"),
        }
        for path in runs
    ]
    if latest:
        data = data[-1:] if data else []
    return {"success": True, "runs": data}


def _bridge_results(
    bridge: RevitBridgeClient,
    *,
    command_id: str | None,
    limit: int,
) -> dict:
    results = bridge.read_command_results()
    if command_id:
        results = [result for result in results if result.get("id") == command_id]
    if limit >= 0:
        results = results[-limit:] if limit else []
    return {
        "success": True,
        "command_results_path": str(bridge.command_results_path),
        "count": len(results),
        "results": results,
    }


def _log_observation(journal: TaskJournal, command: str, result: dict) -> None:
    decision = classify_action(command, {})
    journal.write_entry(
        {
            "command": command,
            "requested_action": {"type": "observation"},
            "risk_classification": decision.to_dict(),
            "approval_status": {"allowed": True, "reason": "Observation command."},
            "result": {
                "status": "observed" if not result.get("error") else "failed",
                "success": result.get("success", not bool(result.get("error"))),
            },
            "output_files": [
                value
                for key, value in result.items()
                if key in {"path"} and isinstance(value, str)
            ],
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
