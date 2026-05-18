import asyncio
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.revit_operator import cli, mcp_server
from tools.revit_operator.actions import ActionRequest, SafeActionExecutor, validate_action_approval_matrix
import tools.revit_operator.agent_session as agent_session
from tools.revit_operator.agent_session import plan_agent_session, run_agent_session
import tools.revit_operator.agent_task as agent_task
from tools.revit_operator.agent_task import plan_agent_task, run_agent_task
import tools.revit_operator.addin_installer as addin_installer
from tools.revit_operator.addin_installer import addin_manifest_text
from tools.revit_operator.addin_security import addin_security_preflight
import tools.revit_operator.bridge as bridge_module
import tools.revit_operator.context_menu as context_menu
import tools.revit_operator.workflows as workflows
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.bridge_validation import bridge_post_restart_validation, bridge_restart_validation_plan
from tools.revit_operator.constants import DRAFT_LABEL
from tools.revit_operator.dialog_memory import record_dialog_rule
from tools.revit_operator.dialog_workflows import (
    plan_current_dialog_response,
    plan_dialog_response,
    validate_dialog_workflow_matrix,
)
from tools.revit_operator.execution_audit import audit_ui_execution_coverage
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.model_open_choreography as model_open_choreography
from tools.revit_operator.navigation import find_view_matches
import tools.revit_operator.north_star as north_star
from tools.revit_operator.north_star import run_north_star_audit
from tools.revit_operator.ocr import ocr_health, ocr_screenshot
import tools.revit_operator.ocr as ocr_module
import tools.revit_operator.operations as operations
from tools.revit_operator.palettes import capture_properties_palette_snapshot
from tools.revit_operator.project_browser import (
    capture_project_browser_snapshot,
    plan_project_browser_item_activation,
    plan_project_browser_navigation,
    plan_project_browser_visual_activation,
    run_project_browser_item_activation,
    run_project_browser_visual_activation,
)
from tools.revit_operator.readiness import wait_model_ready
import tools.revit_operator.revit_locator as revit_locator
from tools.revit_operator.revit_locator import infer_revit_version_from_model
from tools.revit_operator.recovery import capture_recovery_snapshot, validate_recovery_drill_matrix
import tools.revit_operator.ribbon as ribbon
from tools.revit_operator.server import (
    ALLOW_EXTERNAL_SANDBOX_ENV as HTTP_ALLOW_EXTERNAL_SANDBOX_ENV,
    list_control_commands,
    make_control_server,
    run_control_command,
)
from tools.revit_operator.safety import (
    ALLOW,
    APPROVAL_REQUIRED,
    BLOCK,
    HIGH,
    approval_token_for,
    authorize,
    classify_action,
    classify_dialog,
    validate_output_path,
    validate_sandbox_root,
)
import tools.revit_operator.session_checkpoint as session_checkpoint
from tools.revit_operator.supervision import (
    audit_supervision_endurance,
    supervise_session,
    validate_supervision_endurance_matrix,
)
from tools.revit_operator.supervised_ops import run_supervised_ops_audit
from tools.revit_operator.transport_safety import (
    PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV,
    build_transport_safety_matrix,
)
from tools.revit_operator.ui_workflows import (
    list_ui_workflows,
    plan_ui_workflow,
    run_ui_workflow,
    run_ui_workflow_smoke_matrix,
    validate_ui_workflow_matrix,
)
from tools.revit_operator.uia import (
    find_controls_in_uia_tree,
    uia_control_details,
    uia_invoke_control,
    uia_tree,
    validate_uia_method_matrix,
)
from tools.revit_operator.version_support import (
    REVIT_TARGET_FRAMEWORK_BY_VERSION,
    SUPPORTED_REVIT_VERSIONS,
    assembly_subdir_for_revit_version,
    version_support_matrix,
)
from tools.revit_operator.windows import Rect, RevitWindowObserver, WindowInfo, find_controls_in_tree
from tools.revit_operator.workflow_memory import plan_workflow_approvals, record_workflow, replay_workflow
from tools.revit_operator.workflows import run_readonly_qa_workflow


def _satisfied_required_completion_checklist() -> list[dict]:
    return [
        {
            "id": item_id,
            "category": "test",
            "requirement": item_id,
            "status": "satisfied",
            "satisfied": True,
            "evidence": {},
        }
        for item_id in north_star._required_completion_checklist_ids()
    ]


def _complete_audit_completion_actions() -> dict:
    return {
        "autonomous_completion_possible_now": True,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": False,
        "may_call_update_goal": True,
        "autonomous_actions": [],
        "human_actions": [],
        "real_condition_actions": [],
        "note": "test completion authority",
    }


def _test_preflight_freshness(*, generated_offset_seconds=0, ttl_seconds=900):
    generated_at = datetime.now(timezone.utc).timestamp() + generated_offset_seconds
    expires_at = generated_at + ttl_seconds
    return {
        "generated_at_utc": datetime.fromtimestamp(generated_at, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "generated_at_unix": generated_at,
        "ttl_seconds": ttl_seconds,
        "expires_at_utc": datetime.fromtimestamp(expires_at, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "expires_at_unix": expires_at,
        "freshness_rule": "test freshness metadata",
    }


def _fake_revit_window(
    *,
    hwnd: int,
    title: str,
    rect: Rect,
    owner_hwnd: int = 0,
    is_dialog_like: bool = False,
    enabled: bool = True,
    foreground: bool | None = None,
) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        pid=30012,
        title=title,
        class_name="HwndWrapper[DefaultDomain;;test]",
        rect=rect,
        visible=True,
        enabled=enabled,
        foreground=(owner_hwnd == 0 if foreground is None else foreground),
        owner_hwnd=owner_hwnd,
        process_path="C:\\Program Files\\Autodesk\\Revit 2025\\Revit.exe",
        process_name="Revit.exe",
        revit_version="2025",
        is_revit_related=True,
        is_dialog_like=is_dialog_like,
        is_hung=False,
    )


def test_dialog_windows_ignore_contentless_zero_area_owned_windows(monkeypatch):
    observer = object.__new__(RevitWindowObserver)
    main = _fake_revit_window(
        hwnd=1,
        title="Autodesk Revit 2025 - [Model]",
        rect=Rect(0, 0, 1200, 900),
    )
    phantom = _fake_revit_window(
        hwnd=2,
        title="",
        rect=Rect(0, 0, 0, 0),
        owner_hwnd=main.hwnd,
        is_dialog_like=True,
    )
    monkeypatch.setattr(
        observer,
        "_extract_dialog_content",
        lambda _hwnd: {"dialog_text": "", "buttons": [], "controls": []},
    )

    assert observer._dialog_windows([main, phantom]) == []


def test_dialog_windows_ignore_contentless_background_owned_shell(monkeypatch):
    observer = object.__new__(RevitWindowObserver)
    main = _fake_revit_window(
        hwnd=1,
        title="Autodesk Revit 2025 - [Model]",
        rect=Rect(0, 0, 1200, 900),
        enabled=True,
        foreground=True,
    )
    shell = _fake_revit_window(
        hwnd=2,
        title="",
        rect=Rect(100, 100, 500, 500),
        owner_hwnd=main.hwnd,
        is_dialog_like=True,
        foreground=False,
    )
    monkeypatch.setattr(
        observer,
        "_extract_dialog_content",
        lambda _hwnd: {"dialog_text": "", "buttons": [], "controls": []},
    )

    assert observer._dialog_windows([main, shell]) == []


def test_dialog_windows_keep_contentless_foreground_owned_shell_when_main_disabled(monkeypatch):
    observer = object.__new__(RevitWindowObserver)
    main = _fake_revit_window(
        hwnd=1,
        title="Autodesk Revit 2025 - [Model]",
        rect=Rect(0, 0, 1200, 900),
        enabled=False,
        foreground=False,
    )
    shell = _fake_revit_window(
        hwnd=2,
        title="",
        rect=Rect(100, 100, 500, 500),
        owner_hwnd=main.hwnd,
        is_dialog_like=True,
        foreground=True,
    )
    monkeypatch.setattr(
        observer,
        "_extract_dialog_content",
        lambda _hwnd: {"dialog_text": "", "buttons": [], "controls": []},
    )

    assert observer._dialog_windows([main, shell]) == [shell]


def test_supervised_ops_audit_rejects_zero_area_false_modal_recovery(tmp_path):
    journal = TaskJournal(tmp_path, "supervised-audit-test")
    run_dir = journal.run_dir
    (run_dir / "metadata").mkdir(exist_ok=True)
    (run_dir / "screenshots").mkdir(exist_ok=True)
    (run_dir / "metadata" / "metadata-20260518T000000Z.json").write_text("{}", encoding="utf-8")
    (run_dir / "screenshots" / "screenshot.bmp").write_bytes(b"BM")
    (run_dir / "qa_report.md").write_text("DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW", encoding="utf-8")
    (run_dir / "model_ready_status.json").write_text(
        json.dumps({"success": True, "ready": True, "path": str(run_dir / "model_ready_status.json")}),
        encoding="utf-8",
    )
    (run_dir / "project_browser_navigation_plan.json").write_text(
        json.dumps(
            {
                "success": True,
                "view_lookup_count": 1,
                "path": str(run_dir / "project_browser_navigation_plan.json"),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "dialog_workflow_matrix.json").write_text(
        json.dumps({"success": True, "failed_cases": [], "case_count": 1, "path": "dialog.json"}),
        encoding="utf-8",
    )
    (run_dir / "action_approval_matrix.json").write_text(
        json.dumps(
            {
                "path": "actions.json",
                "cases": [
                    {"name": "click-save-blocked", "policy": {"decision": "block"}},
                    {"name": "uia-save-blocked", "policy": {"decision": "block"}},
                    {
                        "name": "request-save-critical-approval",
                        "policy": {"decision": "approval_required", "risk": "critical"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "metadata" / "transport_safety_matrix.json").write_text(
        json.dumps({"path": "transport.json", "status": "clean", "success": True, "failed_check_ids": []}),
        encoding="utf-8",
    )
    (run_dir / "ui_execution_coverage_audit.json").write_text(
        json.dumps(
            {
                "path": "coverage.json",
                "target_met": True,
                "missing_required_surfaces": [],
                "qualifying_executions": [
                    {"task_id": journal.task_id, "surfaces": ["focus"]},
                    {"task_id": journal.task_id, "surfaces": ["ribbon-action"]},
                    {"task_id": journal.task_id, "surfaces": ["ribbon-action"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    journal.write_entry(
        {
            "command": "wait-bridge-result",
            "result": {
                "bridge_result": {
                    "id": "activate_view-20260518T000000Z-test",
                    "success": False,
                    "error": "Setting active view is temporarily disabled.",
                }
            },
        }
    )
    (run_dir / "recovery_snapshot.json").write_text(
        json.dumps(
            {
                "path": str(run_dir / "recovery_snapshot.json"),
                "status": {"state": "modal", "active_dialogs": []},
                "dialogs": {
                    "dialogs": [
                        {
                            "title": "",
                            "dialog_text": "",
                            "buttons": [],
                            "controls": [],
                            "rect": {"width": 0, "height": 0},
                        }
                    ]
                },
                "validated_live_recovery_drill": True,
            }
        ),
        encoding="utf-8",
    )

    result = run_supervised_ops_audit(journal)

    assert result["success"] is True
    assert result["goal_complete"] is False
    assert "live-modal-or-stuck-recovery" in result["unsatisfied_ids"]
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in Path(result["markdown_path"]).read_text(
        encoding="utf-8"
    )


def test_revit_operator_runbook_requires_sequential_north_star_artifact_refresh():
    runbook_path = Path(__file__).resolve().parents[2] / "REVIT_OPERATOR_RUNBOOK.md"
    text = runbook_path.read_text(encoding="utf-8")
    start = text.index(
        "Prefer `north-star-refresh-sequence` for dependent north-star artifact refreshes."
    )
    end = text.index("Review:", start)
    block = text[start:end]
    normalized = " ".join(block.split())

    assert (
        "It runs current handoff, stable scan, hard gate, final stable scan, "
        "and final hard gate as one read-only operation"
    ) in normalized
    assert (
        "Do not run `north-star-current-handoff`, "
        "`north-star-stable-artifact-scan`, and "
        "`north-star-completion-gate` in parallel"
    ) in normalized
    assert "transient blocker-ID mismatch" in block
    assert (
        "Never treat the intermediate stable scan or status output as completion authority."
        in normalized
    )

    commands = [
        line.strip()
        for line in block.splitlines()
        if line.strip().startswith("revit-operator ")
    ]
    assert commands == [
        'revit-operator north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet',
        "revit-operator north-star-stable-artifact-scan",
        "revit-operator north-star-completion-gate",
        "revit-operator north-star-stable-artifact-scan",
        "revit-operator north-star-completion-gate",
    ]


def test_upgrade_dialog_classifies_as_high_risk():
    result = classify_dialog(
        title="Upgrade model",
        text="This model must be upgraded before it can be opened.",
        buttons=["Cancel", "Upgrade"],
    )

    assert result["risk"] == HIGH
    assert result["recommended_action"] == "ask_human"
    assert "upgrade" in result["reason"].lower()


def test_unknown_dialog_classifies_as_high_risk():
    result = classify_dialog(title="Autodesk Revit", text="Unexpected prompt", buttons=["OK"])

    assert result["risk"] == HIGH
    assert result["recommended_action"] == "ask_human"
    assert "unknown" in result["reason"].lower()


def test_unsigned_hermes_addin_dialog_gets_specific_recommendation():
    result = classify_dialog(
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )

    assert result["risk"] == HIGH
    assert result["recommended_action"] == "approve_if_expected_hermes_addin_after_signature_check"
    assert "trust-addin" in result["reason"]


def test_unverified_publisher_hermes_addin_dialog_gets_specific_recommendation():
    result = classify_dialog(
        title="Autodesk Revit",
        text=(
            "The publisher of this add-in could not be verified. "
            "HermesRevitOperator.dll wants to load."
        ),
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )

    assert result["known_dialog_id"] == "unsigned-addin"
    assert result["risk"] == HIGH
    assert result["recommended_action"] == "approve_if_expected_hermes_addin_after_signature_check"


def test_unknown_unverified_addin_dialog_blocks_loading_buttons():
    result = plan_dialog_response(
        title="Autodesk Revit",
        text="The publisher of this add-in could not be verified. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )

    assert result["known_dialog_id"] == "unsigned-addin-unknown"
    assert result["planned_action"] is None
    assert "Always Load" in result["blocked_buttons"]
    assert "Load Once" in result["blocked_buttons"]
    assert "Do Not Load" in result["blocked_buttons"]


def test_plan_dialog_response_unsigned_addin_requires_preflight_and_approval():
    result = plan_dialog_response(
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )

    assert result["known_dialog_id"] == "unsigned-addin"
    assert result["planned_action"]["command"] == "click"
    assert result["planned_action"]["payload"]["target"] == "Always Load"
    assert result["planned_action"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert "revit-operator addin-security-preflight" in result["safe_preflight_commands"]
    assert "Load Once" in result["blocked_buttons"]
    assert "Always Load" not in result["blocked_buttons"]


def test_revit_addin_bridge_writes_are_retrying_and_reader_tolerant():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    assert "RetryFileOperation" in source
    assert "FileShare.ReadWrite | FileShare.Delete" in source
    assert 'Guid.NewGuid().ToString("N") + ".tmp"' in source
    assert "File.Replace(temp, path, null, true)" in source
    assert "AppendLineWithRetry(CommandResultsPath" in source


def test_transmitted_model_dialog_matches_known_rule():
    result = classify_dialog(
        title="Transmitted model",
        text="This model has been transmitted.",
        buttons=["Save this model as a Central Model", "Work with this model temporarily"],
    )

    assert result["known_dialog_id"] == "transmitted-model"
    assert result["risk"] == HIGH
    assert "temporary" in result["recommended_action"]


def test_unresolved_references_dialog_matches_known_rule():
    result = classify_dialog(
        title="Unresolved References",
        text="Revit cannot locate one or more external references.",
        buttons=["Manage Links", "Ignore and continue opening the project"],
    )

    assert result["known_dialog_id"] == "unresolved-references"
    assert result["risk"] == HIGH
    assert "Reloading links" in result["reason"]


def test_cli_known_dialogs_lists_reusable_rules(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "known-dialogs-test",
            "known-dialogs",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["count"] >= 5
    assert any(rule["id"] == "transmitted-model" for rule in output["rules"])


def test_cli_records_and_uses_learned_dialog_rule(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "record-dialog-rule-test",
            "record-dialog-rule",
            "--rule-id",
            "custom-link-warning",
            "--title-term",
            "Custom Link Warning",
            "--button-term",
            "Review",
            "--risk",
            "high",
            "--recommended-action",
            "ask_human_review_without_reload",
            "--reason",
            "Custom link prompt requires supervised review.",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert Path(output["path"]).is_relative_to(tmp_path)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "classify-learned-dialog-test",
            "classify-dialog",
            "--title",
            "Custom Link Warning",
            "--button",
            "Review",
        ]
    )

    assert code == 0
    learned = json.loads(capsys.readouterr().out)
    assert learned["known_dialog_id"] == "custom-link-warning"
    assert learned["risk"] == "high"
    assert learned["recommended_action"] == "ask_human_review_without_reload"


def test_cli_rejects_low_risk_learned_dialog_rule(tmp_path):
    result = record_dialog_rule(
        tmp_path,
        rule_id="too-low",
        title_terms=["Informational"],
        risk="low",
    )

    assert result["success"] is False
    assert "conservative" in result["error"]


def test_cli_dialog_rule_library_lists_learned_rules(tmp_path, capsys):
    rules = tmp_path / "revit_operator_dialog_rules"
    rules.mkdir()
    (rules / "custom.json").write_text(
        json.dumps(
            {
                "id": "custom",
                "title_terms": ["Custom"],
                "text_terms": [],
                "button_terms": ["OK"],
                "risk": "high",
                "recommended_action": "ask_human",
                "reason": "test",
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "dialog-rule-library-test",
            "dialog-rule-library",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["built_in_count"] >= 5
    assert output["learned_count"] == 1
    assert output["learned_rules"][0]["id"] == "custom"


def test_plan_dialog_response_suggests_approval_gated_known_button():
    result = plan_dialog_response(
        title="Transmitted model",
        text="This model has been transmitted.",
        buttons=["Save this model as a Central Model", "Work with this model temporarily"],
    )

    assert result["success"] is True
    assert result["known_dialog_id"] == "transmitted-model"
    assert result["requires_human"] is True
    assert result["planned_action"]["command"] == "click"
    assert result["planned_action"]["payload"]["target"] == "Work with this model temporarily"
    assert result["planned_action"]["policy"]["decision"] == APPROVAL_REQUIRED


def test_plan_dialog_response_keeps_upgrade_as_human_decision():
    result = plan_dialog_response(
        title="Upgrade model",
        text="This model must be upgraded.",
        buttons=["Cancel", "Upgrade"],
    )

    assert result["known_dialog_id"] == "upgrade-model"
    assert result["planned_action"] is None
    assert result["requires_human"] is True
    assert "Upgrade" in result["blocked_buttons"]
    assert "copied local" in result["approval_conditions"]
    assert "revit-operator screenshot" in result["safe_preflight_commands"]


def test_plan_dialog_response_marks_reload_links_as_blocked_preflight():
    result = plan_dialog_response(
        title="Reload Links",
        text="One or more Revit links need to be reloaded.",
        buttons=["Cancel", "Reload", "Manage Links"],
    )

    assert result["known_dialog_id"] == "reload-links"
    assert result["planned_action"] is None
    assert "Reload" in result["blocked_buttons"]
    assert "Autodesk Docs" in result["approval_conditions"]


def test_plan_dialog_response_marks_manage_links_as_human_only():
    result = plan_dialog_response(
        title="Manage Links",
        text="",
        buttons=["Reload From", "Unload", "OK", "Cancel"],
    )

    assert result["known_dialog_id"] == "manage-links"
    assert result["planned_action"] is None
    assert "Reload From" in result["blocked_buttons"]
    assert "exact link" in result["approval_conditions"]


def test_plan_dialog_response_marks_type_catalog_as_human_only():
    result = plan_dialog_response(
        title="Type Catalog",
        text="Select types to load.",
        buttons=["Select All", "OK", "Cancel"],
    )

    assert result["known_dialog_id"] == "type-catalog"
    assert result["planned_action"] is None
    assert "Select All" in result["blocked_buttons"]
    assert "exact type names" in result["approval_conditions"]


def test_plan_dialog_response_marks_visibility_and_templates_as_human_only():
    visibility = plan_dialog_response(
        title="Visibility/Graphics Overrides",
        text="Model Categories",
        buttons=["OK", "Apply", "Cancel"],
    )
    template = plan_dialog_response(
        title="View Template",
        text="Assign view template.",
        buttons=["OK", "Apply", "Cancel"],
    )

    assert visibility["known_dialog_id"] == "visibility-graphics"
    assert visibility["planned_action"] is None
    assert "Apply" in visibility["blocked_buttons"]
    assert template["known_dialog_id"] == "view-template"
    assert template["planned_action"] is None
    assert "target view set" in template["approval_conditions"]


def test_plan_dialog_response_marks_expanded_prompt_surfaces_human_only():
    open_worksets = plan_dialog_response(
        title="Open Worksets",
        text="Specify worksets to open.",
        buttons=["OK", "Cancel"],
    )
    worksharing = plan_dialog_response(
        title="Autodesk Revit",
        text="This central model requires a worksharing decision.",
        buttons=["Create New Local", "Detach", "Cancel"],
    )
    missing_links = plan_dialog_response(
        title="Autodesk Revit",
        text="The Revit link was not found.",
        buttons=["Browse", "Manage Links", "Ignore"],
    )
    warnings = plan_dialog_response(
        title="Review Warnings",
        text="Warnings require review.",
        buttons=["Show", "Export", "Close"],
    )
    failure = plan_dialog_response(
        title="Autodesk Revit",
        text="Failure processing requires a resolution.",
        buttons=["Delete Elements", "Cancel"],
    )
    save_changes = plan_dialog_response(
        title="Autodesk Revit",
        text="Do you want to save changes?",
        buttons=["Save", "Don't Save", "Cancel"],
    )
    export_path = plan_dialog_response(
        title="DWG Export",
        text="Choose output settings.",
        buttons=["Save", "Cancel"],
    )

    assert open_worksets["known_dialog_id"] == "open-worksets"
    assert "Check All" in open_worksets["blocked_buttons"]
    assert worksharing["known_dialog_id"] == "worksharing-central"
    assert "Autodesk Docs" in worksharing["approval_conditions"]
    assert missing_links["known_dialog_id"] == "missing-links"
    assert "Browse" in missing_links["blocked_buttons"]
    assert warnings["known_dialog_id"] == "warning-review"
    assert "Delete Elements" in warnings["blocked_buttons"]
    assert failure["known_dialog_id"] == "failure-processing"
    assert failure["planned_action"] is None
    assert save_changes["known_dialog_id"] == "save-changes"
    assert save_changes["classification"]["risk"] == "critical"
    assert "Don't Save" in save_changes["blocked_buttons"]
    assert export_path["known_dialog_id"] == "export-output-path"
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in export_path["approval_conditions"]


def test_cli_dialog_workflows_lists_playbooks(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "dialog-workflows-test",
            "dialog-workflows",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert any(workflow["dialog_id"] == "transmitted-model" for workflow in output["workflows"])
    assert any(workflow["dialog_id"] == "manage-links" for workflow in output["workflows"])
    assert any(workflow["dialog_id"] == "view-template" for workflow in output["workflows"])
    assert any(workflow["dialog_id"] == "failure-processing" for workflow in output["workflows"])
    assert any(workflow["dialog_id"] == "save-changes" for workflow in output["workflows"])


def test_dialog_workflow_matrix_validates_all_known_prompt_playbooks(tmp_path):
    result = validate_dialog_workflow_matrix(TaskJournal(tmp_path, "dialog-matrix-test"))

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["case_count"] >= 21
    assert result["failed_cases"] == []
    unsigned = next(case for case in result["cases"] if case["dialog_id"] == "unsigned-addin")
    assert unsigned["planned_action"]["payload"]["target"] == "Always Load"
    assert unsigned["planned_action"]["policy"]["decision"] == APPROVAL_REQUIRED
    save_changes = next(case for case in result["cases"] if case["dialog_id"] == "save-changes")
    assert save_changes["planned_action"] is None


def test_cli_dialog_workflow_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "dialog-matrix-cli-test",
            "dialog-workflow-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["failed_cases"] == []
    assert Path(output["path"]).exists()


def test_cli_plan_dialog_response_returns_click_dry_run_plan(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "plan-dialog-response-test",
            "plan-dialog-response",
            "--title",
            "Unresolved References",
            "--button",
            "Manage Links",
            "--button",
            "Ignore and continue opening the project",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["known_dialog_id"] == "unresolved-references"
    assert output["planned_action"]["payload"]["target"] == "Ignore and continue opening the project"


def test_plan_current_dialog_response_uses_visible_dialog(tmp_path):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "title": "Unresolved References",
                        "dialog_text": "Revit could not find one or more external references.",
                        "buttons": ["Manage Links", "Ignore and continue opening the project"],
                    }
                ],
            }

    result = plan_current_dialog_response(
        TaskJournal(tmp_path, "current-dialog-plan-test"),
        FakeObserver(),
    )

    assert result["success"] is True
    assert result["has_dialog"] is True
    assert result["plan"]["known_dialog_id"] == "unresolved-references"
    assert result["plan"]["planned_action"]["payload"]["target"] == "Ignore and continue opening the project"
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_plan_current_dialog_response_uses_ocr_when_dialog_text_is_missing(tmp_path):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "hwnd": 42,
                        "title": "Autodesk Revit",
                        "dialog_text": "",
                        "buttons": ["Overwrite", "Cancel"],
                    }
                ],
            }

    def fake_ocr(_journal, _observer, *, hwnd=None, backend="auto"):
        return {
            "success": True,
            "hwnd": hwnd,
            "backend": backend,
            "text": "Family Load Options\nThe family already exists. Overwrite parameter values?",
            "line_count": 2,
            "read_only": True,
        }

    result = plan_current_dialog_response(
        TaskJournal(tmp_path, "current-dialog-ocr-plan-test"),
        FakeObserver(),
        use_ocr=True,
        ocr_backend="rapidocr",
        ocr_func=fake_ocr,
    )

    assert result["success"] is True
    assert result["ocr_fallback"]["hwnd"] == 42
    assert result["ocr_fallback"]["backend"] == "rapidocr"
    assert result["plan"]["known_dialog_id"] == "family-load-options"
    assert result["plan"]["planned_action"] is None
    assert "Overwrite" in result["plan"]["blocked_buttons"]


def test_plan_current_dialog_response_can_classify_ocr_when_no_accessible_dialog(tmp_path):
    class FakeObserver:
        def list_dialogs(self):
            return {"success": True, "dialogs": []}

        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": ""}]}

    def fake_ocr(_journal, _observer, *, hwnd=None, backend="auto"):
        return {
            "success": True,
            "hwnd": hwnd,
            "backend": backend,
            "text": "This model must be upgraded before it can be opened. Upgrade Cancel",
            "line_count": 1,
            "read_only": True,
        }

    result = plan_current_dialog_response(
        TaskJournal(tmp_path, "current-dialog-no-accessible-ocr-test"),
        FakeObserver(),
        use_ocr=True,
        ocr_func=fake_ocr,
    )

    assert result["success"] is True
    assert result["has_dialog"] is False
    assert result["ocr_fallback"]["success"] is True
    assert result["plan"]["known_dialog_id"] == "upgrade-model"
    assert result["plan"]["planned_action"] is None


def test_plan_current_dialog_response_does_not_classify_ocr_when_not_modal(tmp_path):
    class FakeObserver:
        def list_dialogs(self):
            return {"success": True, "dialogs": []}

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    def fake_ocr(_journal, _observer, *, hwnd=None, backend="auto"):
        return {
            "success": True,
            "hwnd": hwnd,
            "backend": backend,
            "text": "Visibility/Graphics\nApply",
            "line_count": 2,
            "read_only": True,
        }

    result = plan_current_dialog_response(
        TaskJournal(tmp_path, "current-dialog-idle-ocr-test"),
        FakeObserver(),
        use_ocr=True,
        ocr_func=fake_ocr,
    )

    assert result["success"] is True
    assert result["has_dialog"] is False
    assert result["ocr_fallback"]["success"] is True
    assert result["plan"] is None
    assert "not classified" in result["reason"]


def test_cli_plan_current_dialog_response_writes_plan(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "title": "Transmitted model",
                        "dialog_text": "This model has been transmitted.",
                        "buttons": ["Save this model as a Central Model", "Work with this model temporarily"],
                    }
                ],
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "current-dialog-plan-cli-test",
            "plan-current-dialog-response",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["plan"]["known_dialog_id"] == "transmitted-model"
    assert output["plan"]["planned_action"]["payload"]["target"] == "Work with this model temporarily"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_plan_current_dialog_response_use_ocr_flag(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def list_dialogs(self):
            return {"success": True, "dialogs": []}

        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": ""}]}

    def fake_ocr_screenshot(_journal, _observer, *, hwnd=None, backend="auto"):
        return {
            "success": True,
            "hwnd": hwnd,
            "backend": backend,
            "text": "View Template\nAssign view template\nOK Apply Cancel",
            "line_count": 3,
            "read_only": True,
        }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(ocr_module, "ocr_screenshot", fake_ocr_screenshot)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "current-dialog-ocr-cli-test",
            "plan-current-dialog-response",
            "--use-ocr",
            "--ocr-backend",
            "rapidocr",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["ocr_fallback"]["backend"] == "rapidocr"
    assert output["plan"]["known_dialog_id"] == "view-template"
    assert output["plan"]["planned_action"] is None


def test_cli_ribbon_actions_lists_blocked_descriptors(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ribbon-actions-test",
            "ribbon-actions",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert any(action["name"] == "view-tab" for action in output["actions"])
    assert any(action["name"] == "annotate-tab" for action in output["actions"])
    assert any(action["name"] == "manage-links-command" for action in output["actions"])
    save = next(action for action in output["actions"] if action["name"] == "save")
    assert save["blocked"] is True
    file_menu = next(action for action in output["actions"] if action["name"] == "file-menu")
    assert file_menu["blocked"] is True
    print_action = next(action for action in output["actions"] if action["name"] == "print")
    assert print_action["blocked"] is True


def test_ribbon_action_matrix_validates_blocked_and_approval_gated_descriptors(tmp_path):
    result = ribbon.validate_ribbon_action_matrix(TaskJournal(tmp_path, "ribbon-matrix-test"))

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["case_count"] >= 24
    assert result["blocked_count"] >= 7
    assert result["approval_gated_count"] >= 1
    assert result["failed_cases"] == []
    save = next(case for case in result["cases"] if case["name"] == "save")
    assert save["blocked"] is True
    assert any(check["name"] == "blocked_descriptor_not_executable" and check["passed"] for check in save["checks"])
    manage_links = next(case for case in result["cases"] if case["name"] == "manage-links-command")
    assert manage_links["policy"]["decision"] == APPROVAL_REQUIRED


def test_cli_ribbon_action_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ribbon-matrix-cli-test",
            "ribbon-action-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["failed_cases"] == []
    assert Path(output["path"]).exists()


def test_plan_ribbon_action_uses_name_based_command_descriptor(tmp_path, monkeypatch):
    seen = {}

    def fake_find_controls(**kwargs):
        seen.update(kwargs)
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "Manage Links", "control_type": "Button", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(ribbon, "uia_find_controls", fake_find_controls)

    result = ribbon.plan_ribbon_action(
        TaskJournal(tmp_path, "ribbon-manage-links-test"),
        FakeObserver(),
        name="manage-links-command",
    )

    assert seen["name"] == "Manage Links"
    assert seen["control_type"] == "Button"
    assert result["payload"]["name"] == "Manage Links"
    assert result["success"] is True
    assert result["blocked_by_descriptor"] is False
    assert result["executable"] is True
    assert result["policy"]["decision"] == APPROVAL_REQUIRED


def test_plan_ribbon_action_blocks_save_even_if_uia_finds_it(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"automation_id": "ID_Save_RibbonItemControl", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(ribbon, "uia_find_controls", fake_find_controls)

    result = ribbon.plan_ribbon_action(
        TaskJournal(tmp_path, "ribbon-save-test"),
        FakeObserver(),
        name="save",
    )

    assert result["success"] is True
    assert result["blocked_by_descriptor"] is True
    assert result["executable"] is False
    assert result["policy"]["decision"] == BLOCK


def test_plan_ribbon_action_blocks_file_menu_even_if_uia_finds_it(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"automation_id": "File", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(ribbon, "uia_find_controls", fake_find_controls)

    result = ribbon.plan_ribbon_action(
        TaskJournal(tmp_path, "ribbon-file-menu-test"),
        FakeObserver(),
        name="file-menu",
    )

    assert result["success"] is True
    assert result["blocked_by_descriptor"] is True
    assert result["executable"] is False
    assert "Save" in result["reason"]


def test_plan_ribbon_action_blocks_print_even_if_uia_finds_it(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "Print", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(ribbon, "uia_find_controls", fake_find_controls)

    result = ribbon.plan_ribbon_action(
        TaskJournal(tmp_path, "ribbon-print-test"),
        FakeObserver(),
        name="print",
    )

    assert result["success"] is True
    assert result["blocked_by_descriptor"] is True
    assert result["executable"] is False
    assert "Print" in result["reason"]


def test_ribbon_action_dry_run_requires_approval_for_safe_named_target(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"automation_id": "Annotate", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(ribbon, "uia_find_controls", fake_find_controls)

    result = ribbon.run_ribbon_action(
        TaskJournal(tmp_path, "ribbon-annotate-test"),
        FakeObserver(),
        name="annotate-tab",
        dry_run=True,
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["execution"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["executed"] is False


def test_context_menu_actions_list_blocked_descriptors():
    result = context_menu.list_context_menu_actions()

    assert result["success"] is True
    assert any(action["name"] == "project-browser-item-menu" for action in result["actions"])
    save = next(action for action in result["actions"] if action["name"] == "save-control-menu")
    assert save["blocked"] is True


def test_context_menu_action_matrix_validates_descriptors_and_item_policies(tmp_path):
    result = context_menu.validate_context_menu_action_matrix(
        TaskJournal(tmp_path, "context-menu-matrix-test")
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["descriptor_count"] >= 3
    assert result["item_case_count"] >= 4
    assert result["failed_descriptors"] == []
    assert result["failed_items"] == []
    assert result["blocked_descriptor_count"] >= 1
    assert result["approval_gated_descriptor_count"] >= 1
    delete_case = next(case for case in result["item_cases"] if case["item"] == "Delete")
    assert delete_case["policy"]["decision"] == BLOCK
    properties_case = next(case for case in result["item_cases"] if case["item"] == "Properties")
    assert properties_case["policy"]["decision"] == APPROVAL_REQUIRED
    assert Path(result["path"]).exists()


def test_cli_context_menu_action_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "context-menu-matrix-cli-test",
            "context-menu-action-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["descriptor_count"] >= 3
    assert Path(output["path"]).exists()


def test_plan_context_menu_action_requires_exact_target(tmp_path):
    class FakeObserver:
        pass

    result = context_menu.plan_context_menu_action(
        TaskJournal(tmp_path, "context-menu-missing-target-test"),
        FakeObserver(),
        name="project-browser-item-menu",
    )

    assert result["success"] is False
    assert "exact target" in result["error"]


def test_plan_context_menu_action_blocks_save_even_if_uia_finds_it(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"automation_id": "ID_Save_RibbonItemControl", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)

    result = context_menu.plan_context_menu_action(
        TaskJournal(tmp_path, "context-menu-save-test"),
        FakeObserver(),
        name="save-control-menu",
    )

    assert result["success"] is True
    assert result["blocked_by_descriptor"] is True
    assert result["executable"] is False
    assert result["policy"]["decision"] == BLOCK


def test_context_menu_action_dry_run_requires_approval_for_exact_target(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S2.0", "control_type": "TreeItem", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)

    result = context_menu.run_context_menu_action(
        TaskJournal(tmp_path, "context-menu-dry-run-test"),
        FakeObserver(),
        name="project-browser-item-menu",
        target_name="S2.0",
        dry_run=True,
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["payload"]["method"] == "right_click_input"
    assert result["execution"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["executed"] is False


def test_context_menu_snapshot_writes_menu_item_evidence(tmp_path, monkeypatch):
    def fake_find_controls(**kwargs):
        if kwargs.get("control_type") == "MenuItem":
            return {
                "success": True,
                "count": 2,
                "query": kwargs,
                "matches": [{"name": "Open"}, {"name": "Properties"}],
            }
        return {
            "success": True,
            "count": 1,
            "query": kwargs,
            "matches": [{"name": "Context"}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)

    result = context_menu.snapshot_context_menu(
        TaskJournal(tmp_path, "context-menu-snapshot-test"),
        FakeObserver(),
        hwnd=123,
    )

    assert result["success"] is True
    assert result["menu_item_count"] == 2
    assert result["menu_count"] == 1
    assert Path(result["path"]).is_relative_to(tmp_path)
    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["menu_items"][0]["name"] == "Open"


def test_cli_context_menu_action_dry_run_uses_guarded_right_click(tmp_path, capsys, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S2.0", "control_type": "TreeItem", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)
    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "context-menu-cli-test",
            "context-menu-action",
            "--name",
            "project-browser-item-menu",
            "--target-name",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["payload"]["method"] == "right_click_input"
    assert output["execution"]["policy"]["decision"] == APPROVAL_REQUIRED


def test_cli_context_menu_snapshot_is_observation(tmp_path, capsys, monkeypatch):
    def fake_find_controls(**kwargs):
        return {
            "success": True,
            "count": 1 if kwargs.get("control_type") == "MenuItem" else 0,
            "query": kwargs,
            "matches": [{"name": "Properties"}] if kwargs.get("control_type") == "MenuItem" else [],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)
    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "context-menu-snapshot-cli-test",
            "context-menu-snapshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["menu_item_count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_plan_context_menu_item_blocks_destructive_item(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "Delete", "control_type": "MenuItem", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        pass

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)

    result = context_menu.plan_context_menu_item(
        TaskJournal(tmp_path, "context-menu-delete-item-test"),
        FakeObserver(),
        item="Delete",
    )

    assert result["success"] is True
    assert result["policy"]["decision"] == BLOCK
    assert result["executable"] is False


def test_context_menu_select_item_dry_run_requires_approval(tmp_path, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "Properties", "control_type": "MenuItem", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)

    result = context_menu.run_context_menu_item(
        TaskJournal(tmp_path, "context-menu-select-item-test"),
        FakeObserver(),
        item="Properties",
        dry_run=True,
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["payload"]["control_type"] == "MenuItem"
    assert result["execution"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["executed"] is False


def test_cli_context_menu_select_item_dry_run(tmp_path, capsys, monkeypatch):
    def fake_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "Properties", "control_type": "MenuItem", "enabled": True, "visible": True}],
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(context_menu, "uia_find_controls", fake_find_controls)
    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "context-menu-select-item-cli-test",
            "context-menu-select-item",
            "--item",
            "Properties",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["decision"] == APPROVAL_REQUIRED


def test_blocked_action_terms_cannot_be_approved():
    decision = classify_action("click", {"target": "Save"})

    assert decision.decision == BLOCK
    allowed, reason = authorize(decision, supplied_token="APPROVE:anything")
    assert allowed is False
    assert "blocked" in reason.lower()


def test_uia_invoke_save_target_is_blocked_by_policy():
    decision = classify_action("uia-invoke", {"automation_id": "ID_Save_RibbonItemControl"})

    assert decision.decision == BLOCK


def test_high_risk_action_requires_exact_approval_token():
    decision = classify_action("click", {"target": "Cancel"})

    assert decision.decision == APPROVAL_REQUIRED
    assert decision.approval_token
    assert authorize(decision, supplied_token=None)[0] is False
    assert authorize(decision, supplied_token="APPROVE:wrong")[0] is False
    assert authorize(decision, supplied_token=decision.approval_token)[0] is True


def test_action_approval_matrix_dry_runs_and_blocks_expected_cases(tmp_path):
    class FakeObserver:
        supported = True

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    journal = TaskJournal(tmp_path, "action-approval-matrix-test")
    result = validate_action_approval_matrix(journal, FakeObserver())

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["dry_run_only"] is True
    assert result["case_count"] >= 10
    assert result["failed_cases"] == []
    assert result["approval_required_count"] >= 1
    assert result["blocked_count"] >= 1
    assert result["allowed_count"] >= 1
    assert result["executed_count"] == 0
    assert Path(result["path"]).exists()

    cases = {case["name"]: case for case in result["cases"]}
    assert cases["click-save-blocked"]["policy"]["decision"] == BLOCK
    assert cases["uia-save-blocked"]["policy"]["decision"] == BLOCK
    assert cases["request-save-critical-approval"]["policy"]["risk"] == "critical"
    assert cases["visual-click-approval"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert all(case.get("executed") is False for case in result["cases"])


def test_cli_action_approval_matrix_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        supported = True

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "action-approval-matrix-cli-test",
            "action-approval-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["executed_count"] == 0
    assert Path(output["path"]).exists()


def test_uia_method_matrix_covers_allowed_methods_and_blocks_save(tmp_path):
    journal = TaskJournal(tmp_path, "uia-method-matrix-test")
    result = validate_uia_method_matrix(journal)

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["synthetic"] is True
    assert result["live_ui_touched"] is False
    assert result["method_count"] >= 10
    assert result["failed_cases"] == []
    assert result["approval_required_count"] == result["method_count"] + 1
    assert result["blocked_count"] == result["method_count"]
    assert result["executed_count"] == 0
    cases = {case["name"]: case for case in result["cases"]}
    assert cases["method-auto-approval"]["policy"]["decision"] == APPROVAL_REQUIRED
    assert cases["method-invoke-save-blocked"]["policy"]["decision"] == BLOCK
    assert cases["unsupported-method-rejected"]["success"] is True
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_cli_uia_method_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-method-matrix-cli-test",
            "uia-method-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["live_ui_touched"] is False
    assert output["executed_count"] == 0
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_ui_execution_coverage_audit_reports_covered_and_missing_surfaces(tmp_path):
    live_state = {"state": "idle", "revit_running": True, "main_window": {"hwnd": 100}}
    source = TaskJournal(tmp_path, "live-execution-coverage-source")
    source.write_entry(
        {
            "command": "focus",
            "requested_action": {"hwnd": 100},
            "observed_ui_state_before_action": live_state,
            "observed_ui_state_after_action": live_state,
            "risk_classification": {"decision": APPROVAL_REQUIRED},
            "approval_status": {"allowed": True, "reason": "Allowed by safety policy."},
            "result": {"status": "executed", "executed": True},
        }
    )
    source.write_entry(
        {
            "command": "click",
            "requested_action": {"target": "Close"},
            "observed_ui_state_before_action": {"state": "modal", "active_dialogs": [{"title": "Info"}]},
            "observed_ui_state_after_action": live_state,
            "risk_classification": {"decision": APPROVAL_REQUIRED},
            "approval_status": {"allowed": True, "reason": "Allowed by safety policy."},
            "result": {"status": "executed", "executed": True},
        }
    )

    result = audit_ui_execution_coverage(
        TaskJournal(tmp_path, "ui-execution-coverage-audit-test"),
        required_surfaces=["focus", "dialog-click", "uia-invoke"],
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["target_met"] is False
    assert result["covered_required_surfaces"] == ["focus", "dialog-click"]
    assert result["missing_required_surfaces"] == ["uia-invoke"]
    assert result["surface_counts"]["focus"] == 1
    assert result["surface_counts"]["dialog-click"] == 1
    assert result["qualifying_execution_count"] == 2
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_ui_execution_coverage_audit_detects_payload_marked_ribbon_and_context_surfaces(tmp_path):
    live_state = {"state": "idle", "revit_running": True, "main_window": {"hwnd": 100}}
    source = TaskJournal(tmp_path, "live-payload-marked-ui-execution")
    for payload in [
        {"automation_id": "View", "method": "select", "ribbon_action": "view-tab"},
        {
            "name": "S2.0",
            "control_type": "TreeItem",
            "method": "right_click_input",
            "context_menu_action": "project-browser-item-menu",
        },
        {
            "name": "Properties",
            "control_type": "MenuItem",
            "method": "invoke",
            "context_menu_item": "Properties",
        },
    ]:
        source.write_entry(
            {
                "command": "uia-invoke",
                "requested_action": payload,
                "observed_ui_state_before_action": live_state,
                "observed_ui_state_after_action": live_state,
                "risk_classification": {"decision": APPROVAL_REQUIRED},
                "approval_status": {"allowed": True, "reason": "Approved live execution."},
                "result": {"status": "executed", "executed": True},
            }
        )

    result = audit_ui_execution_coverage(
        TaskJournal(tmp_path, "ui-execution-coverage-payload-markers-test"),
        required_surfaces=[
            "uia-invoke",
            "ribbon-action",
            "context-menu-action",
            "context-menu-item",
        ],
    )

    assert result["target_met"] is True
    assert result["surface_counts"]["uia-invoke"] == 3
    assert result["surface_counts"]["ribbon-action"] == 1
    assert result["surface_counts"]["context-menu-action"] == 1
    assert result["surface_counts"]["context-menu-item"] == 1


def test_ui_execution_coverage_audit_excludes_dry_run_and_synthetic_tasks(tmp_path):
    live_state = {"state": "idle", "revit_running": True, "main_window": {"hwnd": 100}}
    matrix = TaskJournal(tmp_path, "live-action-approval-matrix")
    matrix.write_entry(
        {
            "command": "click",
            "requested_action": {"target": "Close"},
            "observed_ui_state_before_action": live_state,
            "observed_ui_state_after_action": live_state,
            "risk_classification": {"decision": APPROVAL_REQUIRED},
            "approval_status": {"allowed": True},
            "result": {"status": "executed", "executed": True},
        }
    )
    dry_run = TaskJournal(tmp_path, "live-dry-run")
    dry_run.write_entry(
        {
            "command": "run-ui-workflow",
            "requested_action": {"name": "project-browser-open-sheet", "dry_run": True},
            "observed_ui_state_before_action": live_state,
            "observed_ui_state_after_action": live_state,
            "risk_classification": {"decision": APPROVAL_REQUIRED},
            "approval_status": {"allowed": True},
            "result": {"status": "dry_run", "executed_steps": [0]},
        }
    )

    result = audit_ui_execution_coverage(
        TaskJournal(tmp_path, "ui-execution-coverage-audit-excluded-test"),
        required_surfaces=["dialog-click"],
    )

    assert result["target_met"] is False
    assert result["qualifying_execution_count"] == 0
    assert result["excluded_execution_count"] == 2
    excluded = {record["task_id"]: record["excluded_reasons"] for record in result["excluded_executions"]}
    assert excluded["live-action-approval-matrix"] == ["test/matrix/audit task"]
    assert excluded["live-dry-run"] == [
        "dry-run execution record",
        "no tracked UI execution surface",
    ]


def test_cli_ui_execution_coverage_audit_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ui-execution-coverage-audit-cli-test",
            "ui-execution-coverage-audit",
            "--required-surfaces",
            "focus,dialog-click",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["live_ui_touched"] is False
    assert output["target_met"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_process_and_wait_observation_actions_are_allowed():
    assert classify_action("list-processes").decision == "allow"
    assert classify_action("north-star-status").decision == "allow"
    assert classify_action("north-star-audit").decision == "allow"
    assert classify_action("north-star-approval-plan").decision == "allow"
    assert classify_action("north-star-approval-preflight").decision == "allow"
    assert classify_action("north-star-ready-approvals").decision == "allow"
    assert classify_action("north-star-next-approval").decision == "allow"
    assert classify_action("north-star-waiting-state").decision == "allow"
    assert classify_action("north-star-approval-phrase-verify").decision == "allow"
    assert classify_action("north-star-approved-execution-preview").decision == "allow"
    assert classify_action("north-star-approval-verify").decision == "allow"
    assert classify_action("north-star-watch").decision == "allow"
    assert classify_action("north-star-resume-check").decision == "allow"
    assert classify_action("north-star-human-gate-packet").decision == "allow"
    assert classify_action("north-star-completion-gate").decision == "allow"
    assert classify_action("north-star-blocked-ledger").decision == "allow"
    assert classify_action("north-star-current-handoff").decision == "allow"
    assert classify_action("north-star-human-unblock-brief").decision == "allow"
    assert classify_action("north-star-agent-stop-status").decision == "allow"
    assert classify_action("north-star-refresh-sequence").decision == "allow"
    assert classify_action("north-star-stable-artifact-scan").decision == "allow"
    assert classify_action("north-star-unblock-readiness").decision == "allow"
    assert classify_action("transport-safety-matrix").decision == "allow"
    assert classify_action("list-revit-installs").decision == "allow"
    assert classify_action("wait-for-window").decision == "allow"
    assert classify_action("wait-for-dialog").decision == "allow"
    assert classify_action("wait-model-ready").decision == "allow"
    assert classify_action("ocr-screenshot").decision == "allow"
    assert classify_action("addin-security-preflight").decision == "allow"
    assert classify_action("uia-tree").decision == "allow"
    assert classify_action("uia-find-control").decision == "allow"
    assert classify_action("uia-control-details").decision == "allow"
    assert classify_action("uia-method-matrix").decision == "allow"
    assert classify_action("find-control").decision == "allow"
    assert classify_action("context-menu-actions").decision == "allow"
    assert classify_action("context-menu-action-matrix").decision == "allow"
    assert classify_action("context-menu-snapshot").decision == "allow"
    assert classify_action("plan-context-menu-action").decision == "allow"
    assert classify_action("plan-context-menu-item").decision == "allow"
    assert classify_action("action-approval-matrix").decision == "allow"
    assert classify_action("ui-execution-coverage-audit").decision == "allow"
    assert classify_action("bridge-restart-validation-plan").decision == "allow"
    assert classify_action("bridge-post-restart-validation").decision == "allow"
    assert classify_action("ui-workflows").decision == "allow"
    assert classify_action("ui-workflow-matrix").decision == "allow"
    assert classify_action("ui-workflow-smoke-matrix").decision == "allow"
    assert classify_action("plan-ui-workflow").decision == "allow"
    assert classify_action("supervise-session").decision == "allow"
    assert classify_action("supervision-endurance-matrix").decision == "allow"
    assert classify_action("supervision-endurance-audit").decision == "allow"
    assert classify_action("recovery-drill-matrix").decision == "allow"
    assert classify_action("workflow-approval-plan").decision == "allow"
    assert classify_action(
        "run-safe-command", {"name": "active-document"}
    ).decision == "allow"
    assert classify_action("run-safe-command", {"name": "save"}).decision == BLOCK


def test_north_star_audit_reports_not_complete_and_writes_artifact(tmp_path):
    result = run_north_star_audit(
        TaskJournal(tmp_path, "north-star-audit-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["objective_restatement"].startswith("Build the first version")
    assert result["north_star_complete"] is False
    assert result["completion_allowed"] is False
    assert result["completion_gate_required"] is True
    assert result["completion_gate_command"] == ["north-star-completion-gate"]
    assert result["status"] == "not_complete"
    assert result["remaining_gaps"]
    assert result["remaining_gap_count"] == len(result["remaining_gaps"])
    assert any("human-approved Revit restart" in gap for gap in result["remaining_gaps"])
    assert result["prompt_to_artifact_checklist_total_count"] == len(
        result["prompt_to_artifact_checklist"]
    )
    assert result["unverified_or_blocked_requirement_count"] == len(
        result["unverified_or_blocked_requirements"]
    )
    assert result["unsatisfied_count"] == result["unverified_or_blocked_requirement_count"]
    assert result["prompt_to_artifact_checklist_unsatisfied_count"] == result[
        "unverified_or_blocked_requirement_count"
    ]
    assert (
        result["prompt_to_artifact_checklist_satisfied_count"]
        + result["prompt_to_artifact_checklist_unsatisfied_count"]
        == result["prompt_to_artifact_checklist_total_count"]
    )
    checklist = {item["id"]: item for item in result["prompt_to_artifact_checklist"]}
    assert checklist["deliverable:REVIT_HUMAN_OPERATOR_LAYER_INSTRUCTIONS.md"]["satisfied"] is True
    assert checklist["deliverable:REVIT_HUMAN_OPERATOR_LAYER.md"]["satisfied"] is True
    assert checklist["deliverable:REVIT_OPERATOR_NEXT_GOAL_PROMPT.md"]["satisfied"] is True
    assert checklist["command:status"]["satisfied"] is True
    assert checklist["command:health"]["satisfied"] is True
    assert checklist["command:run-safe-command"]["satisfied"] is True
    assert checklist["command:request-operation"]["satisfied"] is True
    assert checklist["command:transport-safety-matrix"]["satisfied"] is True
    assert checklist["gate:bridge_restart_validation"]["status"] == "blocked"
    assert checklist["gate:bridge_restart_validation"]["satisfied"] is False
    assert checklist["gate:bridge_restart_validation"]["blocker"]["type"] == "human_action_required"
    assert checklist["gate:bridge_restart_validation"]["blocker"]["gap_id"] == "bridge_restart_validation"
    assert checklist["requirement:prototype-source-ui-window-observer"]["satisfied"] is True
    assert checklist["requirement:prototype-source-dialog-lister-classifier"]["satisfied"] is True
    assert checklist["requirement:prototype-source-screenshot-capture"]["satisfied"] is True
    assert checklist["requirement:prototype-source-safe-action-executor"]["satisfied"] is True
    assert checklist["requirement:prototype-source-local-command-interface"]["satisfied"] is True
    assert checklist["requirement:prototype-source-optional-revit-addin-bridge"]["satisfied"] is True
    assert checklist["requirement:prototype-source-optional-metadata-exporter"]["satisfied"] is True
    assert checklist["requirement:architecture-revit-ui-operator"]["status"] == "missing_evidence"
    assert "live_ui_workflow_execution" in checklist[
        "requirement:architecture-revit-ui-operator"
    ]["evidence"]["blocked_gaps"]
    assert checklist["requirement:architecture-agent-control-server"]["satisfied"] is True
    assert checklist["requirement:architecture-safety-governor"]["status"] == "missing_evidence"
    assert checklist["requirement:aspirational-recover-from-problems"]["status"] == "missing_evidence"
    assert "live_recovery_drills" in checklist[
        "requirement:aspirational-recover-from-problems"
    ]["evidence"]["blocked_gaps"]
    assert checklist["requirement:aspirational-reusable-ui-workflow-memory"]["status"] == "missing_evidence"
    assert checklist["requirement:core-human-style-ui-operation"]["status"] == "blocked"
    assert "live_ui_workflow_execution" in checklist["requirement:core-human-style-ui-operation"]["evidence"]["blocked_gaps"]
    assert "live_ui_workflow_execution" in checklist["requirement:core-human-style-ui-operation"]["blocked_gaps"]
    assert checklist["requirement:core-human-style-ui-operation"]["blocked_by_gap_ids"] == checklist[
        "requirement:core-human-style-ui-operation"
    ]["blocked_gaps"]
    assert checklist["requirement:core-human-style-ui-operation"]["blocker"]["type"] == "gate_or_missing_evidence"
    assert {
        item["gap_id"]
        for item in checklist["requirement:core-human-style-ui-operation"]["blockers"]
    } == {
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    }
    raw_unsatisfied = {item["id"]: item for item in result["unverified_or_blocked_requirements"]}
    assert all(
        isinstance(item.get("blocker"), dict) and item["blocker"].get("type")
        for item in raw_unsatisfied.values()
    )
    assert "live_ui_workflow_execution" in raw_unsatisfied[
        "requirement:core-human-style-ui-operation"
    ]["blocked_gaps"]
    assert result["unverified_or_blocked_requirements"]
    blockers = {item["id"]: item["blocker"] for item in result["gap_evidence"]}
    assert blockers["bridge_restart_validation"]["type"] == "human_action_required"
    assert blockers["supervision_endurance"]["type"] == "time_gated"
    assert blockers["live_recovery_drills"]["type"] == "real_condition_required"
    assert blockers["live_uia_ribbon_context_execution"]["type"] == "human_approval_required"
    blocker_summary = result["blocker_summary"]
    assert blocker_summary["completion_blocked"] is True
    assert blocker_summary["blocked_gap_count"] == 5
    assert blocker_summary["cleared_gap_count"] == 0
    assert result["blocked_gap_count"] == blocker_summary["blocked_gap_count"]
    assert result["blocked_gate_count"] == result["blocked_gap_count"]
    assert result["blocked_gap_ids"] == blocker_summary["blocked_gap_ids"]
    assert result["cleared_gap_count"] == blocker_summary["cleared_gap_count"]
    assert result["cleared_gap_ids"] == blocker_summary["cleared_gap_ids"]
    assert blocker_summary["human_required"] is True
    assert blocker_summary["blocker_types"] == {
        "human_action_required": 1,
        "human_approval_required": 2,
        "real_condition_required": 1,
        "time_gated": 1,
    }
    actions = result["completion_actions"]
    assert actions["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert actions["autonomous_progress_available"] is True
    assert actions["human_or_real_condition_required"] is True
    assert result["may_call_update_goal"] is False
    assert result["autonomous_progress_available"] is True
    assert result["human_or_real_condition_required"] is True
    assert result["blocked_waiting_for_human_or_real_condition"] is False
    assert [item["gap_id"] for item in actions["autonomous_actions"]] == ["supervision_endurance"]
    assert "live-north-star-resume-check-current" in result["missing"]["live_evidence_tasks"]
    assert {item["gap_id"] for item in actions["human_actions"]} == {
        "bridge_restart_validation",
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    }
    assert [item["gap_id"] for item in actions["real_condition_actions"]] == ["live_recovery_drills"]
    assert Path(result["path"]).exists()
    assert Path(result["markdown_path"]).exists()
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Completion Audit" in markdown_text
    assert "Prompt To Artifact Checklist" in markdown_text
    assert "deliverable:REVIT_HUMAN_OPERATOR_LAYER.md" in markdown_text
    assert "requirement:core-human-style-ui-operation" in markdown_text
    assert "gate:bridge_restart_validation" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "completion_allowed: `false`" in markdown_text
    assert "audit_completion_authorized: `false`" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `false`" in markdown_text
    assert "unsatisfied_count:" in markdown_text
    assert "prompt_to_artifact_checklist_unsatisfied_count:" in markdown_text


def test_north_star_live_task_check_accepts_one_level_nested_sandbox_evidence(tmp_path):
    nested_run = (
        tmp_path
        / "live_readonly_bridge_20260512"
        / "revit_operator_runs"
        / "live-status-current"
    )
    nested_run.mkdir(parents=True)
    (nested_run / "journal.jsonl").write_text("{}", encoding="utf-8")

    result = north_star._live_task_check(tmp_path, "live-status-current")

    assert result["present"] is True
    assert result["journal_present"] is True
    assert result["source"] == "nested_sandbox"
    assert result["resolved_from_nested_sandbox"] is True
    assert Path(result["run_dir"]) == nested_run
    assert Path(result["expected_root_run_dir"]) == (
        tmp_path / "revit_operator_runs" / "live-status-current"
    )


def test_north_star_live_task_check_prefers_root_sandbox_evidence(tmp_path):
    root_run = tmp_path / "revit_operator_runs" / "live-status-current"
    root_run.mkdir(parents=True)
    (root_run / "journal.jsonl").write_text("{}", encoding="utf-8")
    nested_run = (
        tmp_path
        / "live_readonly_bridge_20260512"
        / "revit_operator_runs"
        / "live-status-current"
    )
    nested_run.mkdir(parents=True)
    (nested_run / "journal.jsonl").write_text("{}", encoding="utf-8")

    result = north_star._live_task_check(tmp_path, "live-status-current")

    assert result["present"] is True
    assert result["journal_present"] is True
    assert result["source"] == "root_sandbox"
    assert result["resolved_from_nested_sandbox"] is False
    assert Path(result["run_dir"]) == root_run


def test_bridge_readiness_evidence_includes_restart_no_save_checklist(tmp_path, monkeypatch):
    checklist = (
        tmp_path
        / "revit_operator_runs"
        / "bridge-restart-plan"
        / "bridge_restart_no_save_checklist.md"
    )
    checklist.parent.mkdir(parents=True)
    checklist.write_text("DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW", encoding="utf-8")
    plan = checklist.parent / "bridge_restart_validation_plan.json"
    plan.write_text(
        json.dumps(
            {
                "status": "human_restart_required",
                "no_save_checklist_path": str(checklist),
                "active_document": {
                    "available": True,
                    "document": {
                        "document": {
                            "title": "24522 detached",
                            "path": "24522 detached.rvt",
                            "revit_version": "2025",
                            "dirty": True,
                            "worksharing": "enabled",
                            "central_path": "",
                            "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                        },
                        "written_at": "2026-05-13T12:00:00Z",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeBridge:
        def __init__(self, sandbox):
            self.sandbox = sandbox

        def bridge_readiness(self):
            return {
                "ready_for_continuous_bridge": False,
                "requires_revit_restart_or_reload": True,
                "status": "not_ready",
                "checks": [
                    {"name": "source_project_present", "passed": True},
                    {"name": "loaded_build_current", "passed": False},
                ],
            }

    monkeypatch.setattr(north_star, "RevitBridgeClient", FakeBridge)

    evidence = north_star._bridge_readiness_evidence(tmp_path)

    assert evidence["available"] is True
    assert evidence["ready_for_continuous_bridge"] is False
    assert evidence["requires_revit_restart_or_reload"] is True
    assert evidence["restart_plan_artifact"] == str(plan)
    assert evidence["no_save_checklist_path"] == str(checklist)
    assert evidence["no_save_checklist_present"] is True
    assert evidence["failed_checks"] == ["loaded_build_current"]
    assert evidence["restart_context"]["available"] is True
    assert evidence["restart_context"]["title"] == "24522 detached"
    assert evidence["restart_context"]["dirty"] is True
    assert evidence["restart_context"]["active_view_name"] == "STARTING VIEW"


def test_north_star_audit_removes_gaps_when_required_evidence_is_present(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": True,
            "requires_revit_restart_or_reload": False,
        },
    )
    coverage_dir = tmp_path / "revit_operator_runs" / "live-ui-execution-coverage-audit"
    coverage_dir.mkdir(parents=True)
    (coverage_dir / "ui_execution_coverage_audit.json").write_text(
        json.dumps(
            {
                "target_met": True,
                "surface_counts": {
                    "approved-ui-workflow-step": 2,
                    "uia-invoke": 1,
                    "ribbon-action": 1,
                    "context-menu-action": 1,
                    "context-menu-item": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    endurance_dir = tmp_path / "revit_operator_runs" / "live-supervision-endurance-audit"
    endurance_dir.mkdir(parents=True)
    (endurance_dir / "supervision_endurance_audit.json").write_text(
        json.dumps(
            {
                "target_met": True,
                "total_live_seconds": 7300,
                "check_count": 26,
                "target_hours": 2.0,
                "min_checks": 24,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.run_north_star_audit(
        TaskJournal(tmp_path, "north-star-evidence-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert "hours-long live supervision endurance" not in result["remaining_gaps"]
    assert not any("human-approved Revit restart" in gap for gap in result["remaining_gaps"])
    assert not any("broad approved live UI workflow execution" in gap for gap in result["remaining_gaps"])
    assert not any("approved live UIA/ribbon/context-menu" in gap for gap in result["remaining_gaps"])
    assert result["remaining_gaps"] == ["live recovery drills against real stuck/frozen/modal failure states"]
    cleared = {
        item["id"]: item["blocker"]
        for item in result["gap_evidence"]
        if item["id"] != "live_recovery_drills"
    }
    assert all(blocker["blocked"] is False for blocker in cleared.values())
    assert all(blocker["autonomy_status"] == "cleared" for blocker in cleared.values())
    assert result["blocker_summary"]["blocked_gap_count"] == 1
    assert result["blocker_summary"]["cleared_gap_count"] == 4
    assert result["blocker_summary"]["blocked_gap_ids"] == ["live_recovery_drills"]
    assert result["blocker_summary"]["real_condition_required"] is True
    assert result["completion_actions"]["may_call_update_goal"] is False
    assert result["completion_actions"]["autonomous_progress_available"] is False
    assert result["completion_actions"]["human_or_real_condition_required"] is True


def test_north_star_audit_clears_recovery_gap_with_valid_live_recovery_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(north_star, "_bridge_readiness_evidence", lambda _sandbox: {"available": False})
    recovery_dir = tmp_path / "revit_operator_runs" / "live-real-modal-recovery"
    recovery_dir.mkdir(parents=True)
    (recovery_dir / "recovery_snapshot.json").write_text(
        json.dumps(
            {
                "status": {
                    "state": "modal",
                    "main_window": {
                        "is_revit_related": True,
                        "process_name": "Revit.exe",
                        "is_hung": False,
                    },
                    "active_dialogs": [{"title": "Upgrade model"}],
                },
                "dialogs": {"dialogs": [{"title": "Upgrade model"}]},
                "dialog_recovery_plans": [{"known_dialog_id": "upgrade-model", "planned_action": None}],
                "recommendation": {"classification": "human_decision_required"},
            }
        ),
        encoding="utf-8",
    )

    result = north_star.run_north_star_audit(
        TaskJournal(tmp_path, "north-star-live-recovery-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    recovery_gap = next(item for item in result["gap_evidence"] if item["id"] == "live_recovery_drills")
    assert recovery_gap["satisfied"] is True
    assert recovery_gap["blocker"]["blocked"] is False
    assert recovery_gap["blocker"]["autonomy_status"] == "cleared"
    assert recovery_gap["evidence"]["validated_live_recovery_drill"] is True
    assert recovery_gap["evidence"]["task_id"] == "live-real-modal-recovery"
    assert result["blocker_summary"]["cleared_gap_ids"] == ["live_recovery_drills"]


def test_north_star_audit_does_not_count_synthetic_recovery_matrix_as_live(tmp_path, monkeypatch):
    monkeypatch.setattr(north_star, "_bridge_readiness_evidence", lambda _sandbox: {"available": False})
    recovery_dir = tmp_path / "revit_operator_runs" / "live-recovery-drill-matrix"
    recovery_dir.mkdir(parents=True)
    (recovery_dir / "recovery_snapshot.json").write_text(
        json.dumps(
            {
                "status": {
                    "state": "busy",
                    "main_window": {
                        "is_revit_related": True,
                        "process_name": "Revit.exe",
                        "is_hung": True,
                    },
                },
                "dialogs": {"dialogs": []},
                "recommendation": {"classification": "wait_or_human_intervention"},
            }
        ),
        encoding="utf-8",
    )

    result = north_star.run_north_star_audit(
        TaskJournal(tmp_path, "north-star-synthetic-recovery-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    recovery_gap = next(item for item in result["gap_evidence"] if item["id"] == "live_recovery_drills")
    assert recovery_gap["satisfied"] is False
    assert recovery_gap["evidence"]["validated_live_recovery_drill"] is False
    excluded = recovery_gap["evidence"]["excluded_artifacts"][0]
    assert "synthetic or matrix recovery artifact" in excluded["excluded_reasons"]


def test_north_star_audit_reports_in_progress_endurance_details(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {"available": False},
    )
    endurance_dir = tmp_path / "revit_operator_runs" / "live-supervision-endurance-audit"
    endurance_dir.mkdir(parents=True)
    (endurance_dir / "supervision_endurance_audit.json").write_text(
        json.dumps(
            {
                "target_met": False,
                "duration_met": False,
                "checks_met": False,
                "total_live_seconds": 54.2,
                "total_live_hours": 0.015,
                "raw_total_live_seconds": 55.1,
                "overlap_adjusted": True,
                "audit_timestamp": "2026-05-12T10:10:00Z",
                "active_checkpoint_grace_seconds": 900,
                "active_interval_extended_log_count": 1,
                "active_interval_extension_seconds": 120.5,
                "check_count": 18,
                "duration_remaining_seconds": 7145.8,
                "check_count_remaining": 6,
                "estimated_duration_target_at": "2026-05-12T12:09:05Z",
                "estimated_duration_target_reason": "active supervisor pid confirmed running",
                "target_hours": 2.0,
                "min_checks": 24,
                "qualifying_log_count": 5,
                "excluded_log_count": 4,
                "in_progress_log_count": 2,
                "active_in_progress_log_count": 1,
                "stale_in_progress_log_count": 0,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.run_north_star_audit(
        TaskJournal(tmp_path, "north-star-endurance-details-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    endurance_gap = next(
        item for item in result["gap_evidence"] if item["id"] == "supervision_endurance"
    )
    evidence = endurance_gap["evidence"]
    assert endurance_gap["satisfied"] is False
    assert evidence["total_live_seconds"] == 54.2
    assert evidence["raw_total_live_seconds"] == 55.1
    assert evidence["overlap_adjusted"] is True
    assert evidence["audit_timestamp"] == "2026-05-12T10:10:00Z"
    assert evidence["active_checkpoint_grace_seconds"] == 900
    assert evidence["active_interval_extended_log_count"] == 1
    assert evidence["active_interval_extension_seconds"] == 120.5
    assert evidence["duration_remaining_seconds"] == 7145.8
    assert evidence["check_count_remaining"] == 6
    assert evidence["estimated_duration_target_at"] == "2026-05-12T12:09:05Z"
    assert evidence["estimated_duration_target_reason"] == "active supervisor pid confirmed running"
    assert evidence["active_in_progress_log_count"] == 1
    assert evidence["stale_in_progress_log_count"] == 0
    assert endurance_gap["blocker"]["type"] == "time_gated"
    assert endurance_gap["blocker"]["autonomy_status"] == "waiting_for_elapsed_supervision"


def test_north_star_approval_plan_writes_exact_tokens_without_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    runs_root = tmp_path / "revit_operator_runs"
    ribbon_dir = runs_root / "live-ribbon-view-tab-plan"
    ribbon_dir.mkdir(parents=True)
    (ribbon_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "command": "plan-ribbon-action",
                "task_id": "live-ribbon-view-tab-plan",
                "timestamp": "2026-05-13T02:48:01Z",
                "result": {"success": True, "executable": True, "match_count": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workflow_dir = runs_root / "live-project-browser-open-sheet-plan"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ui_workflow_run.json").write_text(
        json.dumps(
            {
                "dry_run": True,
                "planned_only": True,
                "captured_at": "2026-05-13T02:47:19Z",
                "journal": {"task_id": "live-project-browser-open-sheet-plan"},
                "stop_reason": "Missing or incorrect approval token for this recipe step.",
                "step_results": [
                    {"status": "ran"},
                    {"status": "ran"},
                    {
                        "status": "ran",
                        "command_result": {
                            "route": {
                                "approval_required": True,
                                "operation": "activate-view",
                                "recommended_method": "request-operation activate-view",
                            }
                        },
                    },
                    {"status": "stopped_approval_required"},
                ],
            }
        ),
        encoding="utf-8",
    )
    context_dir = runs_root / "live-context-menu-s20-plan"
    context_dir.mkdir(parents=True)
    (context_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "command": "plan-context-menu-action",
                "task_id": "live-context-menu-s20-plan",
                "timestamp": "2026-05-13T02:48:09Z",
                "result": {"success": True, "executable": False, "match_count": 0},
            }
        )
        + "\n"
        + json.dumps(
            {
                "command": "plan-context-menu-action",
                "task_id": "live-context-menu-s20-plan",
                "timestamp": "2026-05-13T02:48:10Z",
                "requested_action": {"type": "observation"},
                "result": {"success": True, "status": "observed"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
                {
                    "status": "preflighted",
                    "approval_preflight_freshness": _test_preflight_freshness(),
                    "ready_for_human_approval_count": 1,
                    "requires_state_change_count": 1,
                    "requires_prevalidation_count": 0,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in approval-plan test.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Target not visible in approval-plan test.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow ready in approval-plan test.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-plan-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["approval_items"]
    ribbon_item = next(item for item in result["approval_items"] if item["id"] == "safe-ribbon-view-tab")
    assert ribbon_item["approval_token"].startswith("APPROVE:")
    assert "--execute" in ribbon_item["command"]
    assert ribbon_item["expected_effect"] == "Select the Revit View ribbon tab only."
    assert ribbon_item["prevalidation"]["status"] == "prevalidated_one_exact_target"
    assert ribbon_item["approval_freshness"]["approval_token"] == ribbon_item["approval_token"]
    assert ribbon_item["approval_freshness"]["bound_payload_digest"]
    assert ribbon_item["approval_freshness"]["prevalidation_status"] == "prevalidated_one_exact_target"
    assert "Do not reuse this token" in ribbon_item["approval_freshness"]["freshness_rule"]
    workflow_item = next(item for item in result["approval_items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow_item["prevalidation"]["status"] == "prevalidated_stopped_at_approval_gate"
    assert workflow_item["prevalidation"]["approval_still_required"] is True
    assert workflow_item["dry_run_command"] == [
        "run-ui-workflow",
        "--name",
        "project-browser-open-sheet",
        "--sheet-number",
        "S2.0",
    ]
    assert workflow_item["dry_run_powershell"].endswith("--sheet-number S2.0")
    assert "--approval-tokens-json" in workflow_item["execute_powershell"]
    context_action = next(item for item in result["approval_items"] if item["id"] == "context-menu-project-browser-target")
    assert context_action["prevalidation"]["status"] == "not_currently_executable"
    assert context_action["prevalidation"]["match_count"] == 0
    item = next(item for item in result["approval_items"] if item["id"] == "context-menu-select-properties-item")
    assert item["approval_token"] is None
    assert item["approval_token_withheld"] is True
    assert item["currently_executable"] is False
    assert "plan-context-menu-item" in item["precondition"]
    assert any(item["id"] == "human-restart-reload-revit" for item in result["manual_items"])
    assert "does not focus, click, type, invoke UIA" in result["safety_note"]
    assert result["blocker_summary"]["blocked_gap_count"] == 5
    assert result["blocked_gap_count"] == result["blocker_summary"]["blocked_gap_count"]
    assert result["blocked_gate_count"] == result["blocked_gap_count"]
    assert result["blocked_gap_ids"] == sorted(result["blocker_summary"]["blocked_gap_ids"])
    assert result["cleared_gap_count"] == result["blocker_summary"]["cleared_gap_count"]
    assert result["cleared_gap_ids"] == result["blocker_summary"]["cleared_gap_ids"]
    assert result["blocker_summary"]["human_required"] is True
    assert result["completion_actions"]["may_call_update_goal"] is False
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] is False
    assert result["completion_actions"]["autonomous_actions"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in markdown_text
    assert "blocked_gap_count:" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `false`" in markdown_text
    assert "Approval Preflight Readiness" in markdown_text
    assert "ready_for_human_approval_count: `1`" in markdown_text
    assert "Dry run before approval" in markdown_text
    assert "Execute only after explicit approval" in markdown_text
    assert "Approval readiness: `requires_ui_state_change`" in markdown_text
    assert "Execute withheld" in markdown_text
    assert "north-star-approval-verify" in markdown_text
    assert "Bound payload digest" in markdown_text
    assert "Freshness rule" in markdown_text
    assert "--approval-tokens-json" in markdown_text


def test_north_star_ready_approvals_lists_only_preflight_ready_items(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "ready_for_human_approval_count": 2,
                "requires_state_change_count": 1,
                "requires_prevalidation_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow dry-run passed.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Project Browser target is not visible.",
                        },
                    },
                    {
                        "id": "context-menu-select-properties-item",
                        "status": "planned_only",
                        "preflight_success": False,
                        "approval_readiness": {
                            "status": "requires_prevalidation",
                            "ready_for_human_approval": False,
                            "reason": "Context menu is not open.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_ready_approvals(
        TaskJournal(tmp_path, "north-star-ready-approvals-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "ready_items_available"
    assert result["may_execute_from_this_result"] is False
    ready_ids = {item["id"] for item in result["ready_items"]}
    withheld_ids = {item["id"] for item in result["withheld_items"]}
    assert {"safe-ribbon-view-tab", "approved-workflow-open-sheet"}.issubset(ready_ids)
    assert "context-menu-project-browser-target" in withheld_ids
    assert "context-menu-select-properties-item" in withheld_ids
    assert result["ready_approval_count"] == len(result["ready_items"])
    assert all(item["approval_token"].startswith("APPROVE:") for item in result["ready_items"])
    assert all(item["execute_powershell"] for item in result["ready_items"])
    ready_ribbon = next(item for item in result["ready_items"] if item["id"] == "safe-ribbon-view-tab")
    assert ready_ribbon["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert ready_ribbon["token_verification_summary"]["token_matches_ready_item"] is True
    assert ready_ribbon["token_verification_summary"]["approval_ready_now"] is True
    assert ready_ribbon["token_verification_summary"]["may_execute_from_this_summary"] is False
    assert ready_ribbon["token_verification_summary"]["bound_payload_digest"]
    assert all("execute_powershell" not in item for item in result["withheld_items"])
    assert all(item["withheld_execute_command"] for item in result["withheld_items"])
    assert "Ask the human to review only ready_items" in result["approval_request_rule"]
    assert "does not approve, focus, click, type, invoke UIA" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Revit Operator Ready North-Star Approvals" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "Ready Items" in markdown_text
    assert "Withheld Items" in markdown_text
    assert "Execute only after explicit approval" in markdown_text
    assert "  gap_ids: `live_uia_ribbon_context_execution`" in markdown_text
    assert "  gap_ids: `live_ui_workflow_execution`" in markdown_text
    assert "may_execute_from_this_summary=false" in markdown_text
    assert "Bound payload digest" in markdown_text
    assert "Execute command withheld until latest preflight marks this item ready" in markdown_text
    assert "north-star-approval-verify" in markdown_text


def test_north_star_ready_approvals_withholds_when_preflight_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-1800,
                    ttl_seconds=60,
                ),
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_ready_approvals(
        TaskJournal(tmp_path, "north-star-ready-approvals-stale-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["status"] == "no_ready_items"
    assert result["may_execute_from_this_result"] is False
    assert result["ready_approval_count"] == 0
    assert result["withheld_approval_count"] == 5
    assert result["preflight_freshness_guard"]["status"] == "preflight_stale"
    safe = next(item for item in result["withheld_items"] if item["id"] == "safe-ribbon-view-tab")
    assert safe["approval_readiness"]["status"] == "preflight_stale"
    assert "expired" in safe["withheld_reason"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Preflight Freshness Guard" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "preflight_stale" in markdown_text


def test_north_star_next_approval_selects_one_ready_item_without_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "ready_for_human_approval_count": 2,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow dry-run passed.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Project Browser target is not visible.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_next_approval(
        TaskJournal(tmp_path, "north-star-next-approval-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "approval_ready"
    assert result["may_execute_from_this_result"] is False
    selected = result["selected_item"]
    assert selected["id"] == "safe-ribbon-view-tab"
    assert selected["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert selected["approval_token"].startswith("APPROVE:")
    assert selected["verify_powershell"]
    assert selected["dry_run_powershell"]
    assert selected["execute_powershell"]
    assert selected["may_execute_from_this_item"] is False
    assert selected["token_verification_summary"]["may_execute_from_this_summary"] is False
    assert result["deferred_ready_items"]
    assert all("execute_powershell" not in item for item in result["deferred_ready_items"])
    assert "Ask the human to approve only selected_item" in result["approval_request_rule"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Revit Operator Next North-Star Approval" in markdown_text
    assert "Selected Item" in markdown_text
    assert "Deferred Ready Items" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "may_execute_from_this_item: `false`" in markdown_text
    assert "  gap_ids: `live_uia_ribbon_context_execution`" in markdown_text
    assert "Execute only after explicit approval" in markdown_text


def test_north_star_approval_plan_uses_latest_matching_prevalidation_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    runs_root = tmp_path / "revit_operator_runs"

    def write_journal(task_id, command, timestamp, result):
        run_dir = runs_root / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "journal.jsonl").write_text(
            json.dumps(
                {
                    "command": command,
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "result": result,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_workflow(task_id, captured_at):
        run_dir = runs_root / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "ui_workflow_run.json").write_text(
            json.dumps(
                {
                    "dry_run": True,
                    "planned_only": True,
                    "captured_at": captured_at,
                    "journal": {"task_id": task_id},
                    "stop_reason": "Missing or incorrect approval token for this recipe step.",
                    "step_results": [
                        {"status": "ran"},
                        {
                            "status": "ran",
                            "command_result": {
                                "route": {
                                    "approval_required": True,
                                    "operation": "activate-view",
                                    "recommended_method": "request-operation activate-view",
                                }
                            },
                        },
                        {"status": "stopped_approval_required"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_journal(
        "live-ribbon-view-tab-plan",
        "plan-ribbon-action",
        "2026-05-13T02:48:01Z",
        {"success": True, "executable": False, "match_count": 0},
    )
    write_journal(
        "live-ribbon-view-tab-plan-refresh",
        "plan-ribbon-action",
        "2026-05-13T03:50:39Z",
        {"success": True, "executable": True, "match_count": 1},
    )
    write_workflow("live-project-browser-open-sheet-plan", "2026-05-13T02:47:19Z")
    write_workflow("live-project-browser-open-sheet-plan-refresh", "2026-05-13T03:50:45.802250Z")
    write_journal(
        "live-context-menu-s20-plan",
        "plan-context-menu-action",
        "2026-05-13T02:48:09Z",
        {"success": True, "executable": True, "match_count": 1},
    )
    write_journal(
        "live-context-menu-s20-plan-refresh",
        "plan-context-menu-action",
        "2026-05-13T03:50:50Z",
        {"success": True, "executable": False, "match_count": 0},
    )

    result = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-plan-refresh-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    items = {item["id"]: item for item in result["approval_items"]}

    ribbon_prevalidation = items["safe-ribbon-view-tab"]["prevalidation"]
    assert ribbon_prevalidation["source_task_id"] == "live-ribbon-view-tab-plan-refresh"
    assert ribbon_prevalidation["observed_at"] == "2026-05-13T03:50:39Z"
    assert ribbon_prevalidation["status"] == "prevalidated_one_exact_target"
    assert Path(ribbon_prevalidation["artifact"]).parent.name == "live-ribbon-view-tab-plan-refresh"

    direct_uia_prevalidation = items["direct-uia-view-tab-select"]["prevalidation"]
    assert direct_uia_prevalidation["source_task_id"] == "live-ribbon-view-tab-plan-refresh"

    workflow_prevalidation = items["approved-workflow-open-sheet"]["prevalidation"]
    assert workflow_prevalidation["source_task_id"] == "live-project-browser-open-sheet-plan-refresh"
    assert workflow_prevalidation["captured_at"] == "2026-05-13T03:50:45.802250Z"
    assert workflow_prevalidation["status"] == "prevalidated_stopped_at_approval_gate"
    assert Path(workflow_prevalidation["artifact"]).parent.name == "live-project-browser-open-sheet-plan-refresh"

    context_prevalidation = items["context-menu-project-browser-target"]["prevalidation"]
    assert context_prevalidation["source_task_id"] == "live-context-menu-s20-plan-refresh"
    assert context_prevalidation["observed_at"] == "2026-05-13T03:50:50Z"
    assert context_prevalidation["status"] == "not_currently_executable"
    assert Path(context_prevalidation["artifact"]).parent.name == "live-context-menu-s20-plan-refresh"


def test_north_star_approval_preflight_runs_dry_run_commands_without_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    monkeypatch.setattr(
        north_star,
        "_approval_prevalidation",
        lambda _sandbox, _sheet_number: {
            "safe-ribbon-view-tab": {"status": "prevalidated_one_exact_target", "executable": True},
            "direct-uia-view-tab-select": {
                "status": "target_prevalidated_by_ribbon_plan",
                "executable": True,
            },
            "approved-workflow-open-sheet": {"status": "prevalidated_stopped_at_approval_gate"},
            "context-menu-project-browser-target": {
                "status": "not_currently_executable",
                "executable": False,
            },
            "context-menu-select-properties-item": {"status": "not_prevalidated"},
        },
    )
    seen: list[tuple[str, list[str]]] = []

    def fake_runner(argv, item_id):
        seen.append((item_id, argv))
        assert "--execute" not in argv
        assert "--approval-token" not in argv
        assert "--approval-tokens-json" not in argv
        return {
            "success": True,
            "status": "dry_run",
            "dry_run": True,
            "executable": item_id in {"safe-ribbon-view-tab", "direct-uia-view-tab-select"},
            "match_count": 1 if item_id == "safe-ribbon-view-tab" else 0,
        }

    result = north_star.build_north_star_approval_preflight(
        TaskJournal(tmp_path, "north-star-approval-preflight-test"),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        run_preflight=fake_runner,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "preflighted"
    assert result["approval_item_count"] == 5
    assert result["preflight_passed_count"] == 5
    assert result["unsafe_preflight_count"] == 0
    assert all(item["approval_token"] is None for item in result["items"])
    assert all(item["approval_token_withheld"] is True for item in result["items"])
    assert all("APPROVE:" not in json.dumps(item) for item in result["items"])
    assert result["ready_for_human_approval_count"] == 3
    assert result["requires_state_change_count"] == 1
    assert result["requires_prevalidation_count"] == 1
    assert result["expected_context"]["revit_version"] == "2025"
    assert result["expected_context"]["expected_title_contains"] == "24522 St John XXIII"
    assert result["expected_context"]["expected_view_name"] == "STARTING VIEW"
    assert result["expected_context"]["expected_view_type"] == "DrawingSheet"
    assert result["approval_preflight_freshness"]["ttl_seconds"] == 900
    assert result["approval_preflight_freshness"]["expires_at_unix"] > result[
        "approval_preflight_freshness"
    ]["generated_at_unix"]
    refresh = result["post_preflight_handoff_refresh"]
    assert refresh["required"] is True
    assert refresh["read_only"] is True
    assert refresh["execution_command_included"] is False
    assert refresh["approval_token_included"] is False
    assert refresh["command"] == [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-view-name",
        "STARTING VIEW",
        "--expected-view-type",
        "DrawingSheet",
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
    ]
    assert "APPROVE:" not in refresh["powershell"]
    assert len(seen) == 5
    ribbon = next(item for item in result["items"] if item["id"] == "safe-ribbon-view-tab")
    assert ribbon["approval_readiness"]["status"] == "ready_for_human_approval"
    workflow = next(item for item in result["items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow["dry_run_command"] == [
        "run-ui-workflow",
        "--name",
        "project-browser-open-sheet",
        "--sheet-number",
        "S2.0",
    ]
    assert "--approval-tokens-json" not in workflow["dry_run_command"]
    assert workflow["preflight_summary"]["dry_run"] is True
    assert workflow["approval_readiness"]["ready_for_human_approval"] is True
    context_action = next(item for item in result["items"] if item["id"] == "context-menu-project-browser-target")
    assert context_action["approval_readiness"]["status"] == "requires_ui_state_change"
    context_item = next(item for item in result["items"] if item["id"] == "context-menu-select-properties-item")
    assert context_item["approval_readiness"]["status"] == "requires_prevalidation"
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    assert Path(result["stable_files"]["preflight_json"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    assert Path(result["stable_files"]["preflight_markdown"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    markdown_text = Path(result["stable_files"]["preflight_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Approval Preflight" in markdown_text
    assert "ready_for_human_approval_count: `3`" in markdown_text
    assert "Expected title contains: `24522 St John XXIII`" in markdown_text
    assert "Expected view name: `STARTING VIEW`" in markdown_text
    assert "Approval Preflight Freshness" in markdown_text
    assert "Post-Preflight Handoff Refresh" in markdown_text
    assert "--publish-current-handoff" in markdown_text
    assert "Approval readiness: `requires_ui_state_change`" in markdown_text
    assert "Approval readiness: `requires_prevalidation`" in markdown_text
    assert "Execute only after explicit approval" not in markdown_text
    assert "Execute withheld" in markdown_text
    assert "APPROVE:" not in markdown_text


def test_north_star_approval_preflight_treats_approval_gate_dry_runs_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    monkeypatch.setattr(
        north_star,
        "_approval_prevalidation",
        lambda _sandbox, _sheet_number: {
            "safe-ribbon-view-tab": {"status": "prevalidated_one_exact_target", "executable": True},
            "direct-uia-view-tab-select": {
                "status": "target_prevalidated_by_ribbon_plan",
                "executable": True,
            },
            "approved-workflow-open-sheet": {"status": "prevalidated_stopped_at_approval_gate"},
            "context-menu-project-browser-target": {
                "status": "not_currently_executable",
                "executable": False,
            },
            "context-menu-select-properties-item": {"status": "not_prevalidated"},
        },
    )

    def fake_runner(argv, item_id):
        if item_id == "approved-workflow-open-sheet":
            return {
                "success": False,
                "dry_run": True,
                "planned_only": True,
                "stop_reason": "Missing or incorrect approval token for this recipe step.",
            }
        if item_id == "direct-uia-view-tab-select":
            return {"status": "dry_run", "dry_run": True}
        return {"success": True, "dry_run": True}

    result = north_star.build_north_star_approval_preflight(
        TaskJournal(tmp_path, "north-star-approval-preflight-dry-run-success-test"),
        default_sheet_number="S2.0",
        run_preflight=fake_runner,
    )

    assert result["success"] is True
    assert result["preflight_passed_count"] == result["approval_item_count"]
    assert result["preflight_failed_count"] == 0
    workflow = next(item for item in result["items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow["status"] == "preflight_passed"
    assert workflow["preflight_success"] is True
    assert workflow["approval_readiness"]["status"] == "ready_for_human_approval"


def test_north_star_approval_verify_matches_current_token_without_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")
    plan = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-verify-plan-test"),
        default_sheet_number="S2.0",
    )
    token = next(
        item["approval_token"]
        for item in plan["approval_items"]
        if item["id"] == "safe-ribbon-view-tab"
    )

    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-test"),
        default_sheet_number="S2.0",
        approval_token=token,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "matched"
    assert result["token_matches_current_approval_item"] is True
    assert result["execution_by_this_command"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["approval_ready_now"] is True
    assert result["readiness_result"]["status"] == "ready_for_human_approval"
    assert result["matched_items"][0]["id"] == "safe-ribbon-view-tab"
    assert result["matched_items"][0]["approval_ready_now"] is True
    assert result["matched_items"][0]["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert result["matched_items"][0]["blocked_effects"]
    assert result["matched_items"][0]["post_checks"]
    assert result["matched_items"][0]["approval_freshness"]["bound_payload_digest"]
    assert result["freshness_result"]["token_matches_current_approval_item"] is True
    assert result["freshness_result"]["matched_item_ids"] == ["safe-ribbon-view-tab"]
    assert result["freshness_result"]["approval_ready_now"] is True
    assert "Re-run dry-run preflight" in result["freshness_result"]["freshness_rule"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_north_star_approval_verify_reports_not_ready_preflight_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "requires_state_change_count": 1,
                "items": [
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Target is not currently executable.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-verify-not-ready-plan-test"),
        default_sheet_number="S2.0",
    )
    item = next(
        item
        for item in plan["approval_items"]
        if item["id"] == "context-menu-project-browser-target"
    )
    assert item["approval_token"] is None
    assert item["approval_token_withheld"] is True
    assert item["required_human_approval_phrase"] is None
    assert item["execute_powershell"] == ""

    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-not-ready-test"),
        default_sheet_number="S2.0",
        approval_token="APPROVE:not-ready-withheld",
    )

    assert result["status"] == "no_match"
    assert result["token_matches_current_approval_item"] is False
    assert result["approval_ready_now"] is False
    assert result["matched_items"] == []
    assert result["may_execute_from_this_result"] is False


def test_north_star_approval_verify_rejects_unknown_token(tmp_path):
    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-no-match-test"),
        default_sheet_number="S2.0",
        approval_token="APPROVE:not-current",
    )

    assert result["success"] is True
    assert result["status"] == "no_match"
    assert result["token_matches_current_approval_item"] is False
    assert result["match_count"] == 0
    assert result["matched_items"] == []
    assert result["execution_by_this_command"] is False


def test_north_star_approval_phrase_verify_matches_current_waiting_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in phrase verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-phrase-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )
    assert waiting["audit_completion_authorized"] is False
    assert waiting["next_approval_gap_ids"] == [
        "live_uia_ribbon_context_execution"
    ]
    waiting_markdown = Path(waiting["markdown_path"]).read_text(encoding="utf-8")
    assert "audit_completion_authorized: `false`" in waiting_markdown
    assert "- next_approval_gap_ids: `live_uia_ribbon_context_execution`" in waiting_markdown

    result = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-verify-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        phrase_source="human_active_conversation",
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "matched"
    assert result["phrase_matches_waiting_state"] is True
    assert result["phrase_source"] == "human_active_conversation"
    assert result["phrase_source_attested"] is True
    assert result["artifact_phrase_is_not_approval_provenance"] is True
    assert result["token_matches_current_approval_item"] is True
    assert result["approval_ready_now"] is True
    assert result["approval_validated_for_current_waiting_state"] is True
    assert result["matched_item_id"] == "safe-ribbon-view-tab"
    assert result["execution_by_this_command"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["approval_verify"]["may_execute_from_this_result"] is False
    assert result["required_human_approval_phrase"].startswith("I approve safe-ribbon-view-tab")
    assert result["supplied_phrase_sha256"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown = Path(result["markdown_path"])
    assert markdown.is_relative_to(tmp_path)
    assert "not execution authority" in markdown.read_text(encoding="utf-8")
    assert "phrase_source_attested: `true`" in markdown.read_text(encoding="utf-8")

    untrusted_source = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-untrusted-source-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        default_sheet_number="S2.0",
        revit_version="2025",
    )
    assert untrusted_source["status"] == "phrase_source_unverified"
    assert untrusted_source["phrase_matches_waiting_state"] is True
    assert untrusted_source["phrase_source_attested"] is False
    assert untrusted_source["token_matches_current_approval_item"] is True
    assert untrusted_source["approval_validated_for_current_waiting_state"] is False
    assert untrusted_source["may_execute_from_this_result"] is False


def test_north_star_approval_phrase_verify_rejects_wrong_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in phrase verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-verify-no-match-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase="I approve the wrong item with token APPROVE:not-current",
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    assert result["success"] is True
    assert result["status"] == "no_match"
    assert result["phrase_matches_waiting_state"] is False
    assert result["approval_validated_for_current_waiting_state"] is False
    assert result["may_execute_from_this_result"] is False


def test_north_star_approved_execution_preview_shows_command_after_phrase_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in preview test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-execution-preview-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    result = north_star.build_north_star_approved_execution_preview(
        TaskJournal(tmp_path, "north-star-approved-execution-preview-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        phrase_source="human_active_conversation",
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "preview_ready"
    assert result["approval_validated_for_current_waiting_state"] is True
    assert result["phrase_verification"]["phrase_source_attested"] is True
    assert result["selection_matches_verified_phrase"] is True
    assert result["preflight_freshness_guard"]["status"] == "fresh"
    assert result["preflight_freshness_guard"]["matched"] is True
    assert result["context_guard"]["status"] == "context_matched"
    assert result["context_guard"]["matched"] is True
    assert result["selected_item_id"] == "safe-ribbon-view-tab"
    assert result["matched_item_id"] == "safe-ribbon-view-tab"
    assert result["execute_command_preview"][:2] == ["ribbon-action", "--name"]
    assert "--execute" in result["execute_command_preview"]
    assert result["execute_powershell_preview"]
    assert result["execution_by_this_command"] is False
    assert result["may_execute_from_this_result"] is False
    assert "separate execution command" in result["completion_rule"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "not execution authority" in markdown_text
    assert "Context Guard" in markdown_text
    assert "context_matched" in markdown_text


def test_north_star_approved_execution_preview_withholds_command_on_context_mismatch(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "Different Project",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in preview mismatch test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-execution-preview-mismatch-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    result = north_star.build_north_star_approved_execution_preview(
        TaskJournal(tmp_path, "north-star-approved-execution-preview-context-mismatch-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        phrase_source="human_active_conversation",
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["status"] == "context_mismatch"
    assert result["approval_validated_for_current_waiting_state"] is True
    assert result["selection_matches_verified_phrase"] is True
    assert result["context_guard"]["matched"] is False
    assert result["preflight_freshness_guard"]["matched"] is True
    assert result["context_guard"]["status"] == "context_mismatch"
    assert result["context_guard"]["mismatch_fields"] == [
        {
            "field": "expected_title_contains",
            "requested": "24522 St John XXIII",
            "preflight": "Different Project",
        }
    ]
    assert result["execute_command_preview"] == []
    assert result["execute_powershell_preview"] == ""
    assert result["may_execute_from_this_result"] is False
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Context Guard" in markdown_text
    assert "context_mismatch" in markdown_text
    assert "Different Project" in markdown_text


def test_north_star_approved_execution_preview_withholds_command_on_stale_preflight(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    preflight_payload = {
        "status": "preflighted",
        "approval_preflight_freshness": _test_preflight_freshness(),
        "expected_context": {
            "revit_version": "2025",
            "expected_title_contains": "24522 St John XXIII",
            "expected_path_contains": "",
            "expected_view_name": "STARTING VIEW",
            "expected_view_type": "DrawingSheet",
        },
        "ready_for_human_approval_count": 1,
        "items": [
            {
                "id": "safe-ribbon-view-tab",
                "status": "preflight_passed",
                "preflight_success": True,
                "approval_readiness": {
                    "status": "ready_for_human_approval",
                    "ready_for_human_approval": True,
                    "reason": "Ready in stale preview test.",
                },
            }
        ],
    }
    preflight_path = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight_path.write_text(json.dumps(preflight_payload), encoding="utf-8")
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-execution-preview-stale-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )
    preflight_payload["approval_preflight_freshness"] = _test_preflight_freshness(
        generated_offset_seconds=-1800,
        ttl_seconds=60,
    )
    preflight_path.write_text(json.dumps(preflight_payload), encoding="utf-8")

    result = north_star.build_north_star_approved_execution_preview(
        TaskJournal(tmp_path, "north-star-approved-execution-preview-stale-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        phrase_source="human_active_conversation",
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["status"] == "approval_not_validated"
    assert result["approval_validated_for_current_waiting_state"] is False
    assert result["selection_matches_verified_phrase"] is False
    assert result["preflight_freshness_guard"]["matched"] is False
    assert result["preflight_freshness_guard"]["status"] == "preflight_stale"
    assert result["context_guard"]["matched"] is True
    assert result["execute_command_preview"] == []
    assert result["execute_powershell_preview"] == ""
    assert result["may_execute_from_this_result"] is False
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Preflight Freshness Guard" in markdown_text
    assert "preflight_stale" in markdown_text


def test_north_star_approved_execution_preview_withholds_without_phrase_source(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in missing source preview test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-execution-preview-source-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    result = north_star.build_north_star_approved_execution_preview(
        TaskJournal(tmp_path, "north-star-approved-execution-preview-source-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["status"] == "approval_not_validated"
    assert result["phrase_verification"]["status"] == "phrase_source_unverified"
    assert result["phrase_verification"]["phrase_source_attested"] is False
    assert result["approval_validated_for_current_waiting_state"] is False
    assert result["execute_command_preview"] == []
    assert result["execute_powershell_preview"] == ""
    assert result["may_execute_from_this_result"] is False


def test_north_star_approved_execution_preview_withholds_command_without_phrase_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in preview test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_approved_execution_preview(
        TaskJournal(tmp_path, "north-star-approved-execution-preview-no-match-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase="READ ONLY PROBE - NOT APPROVAL",
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    assert result["success"] is True
    assert result["status"] == "approval_not_validated"
    assert result["approval_validated_for_current_waiting_state"] is False
    assert result["selected_item"] is None
    assert result["execute_command_preview"] == []
    assert result["execute_powershell_preview"] == ""
    assert result["may_execute_from_this_result"] is False


def test_north_star_status_writes_compact_blocker_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )

    result = north_star.build_north_star_status(
        TaskJournal(tmp_path, "north-star-status-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["north_star_complete"] is False
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["completion_gate_required"] is True
    assert result["completion_gate_command"] == ["north-star-completion-gate"]
    assert result["status_completion_candidate"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["agent_stop_status"] == "autonomous_progress_available"
    assert result["should_stop_agent"] is False
    assert result["agent_stop_reason"] is None
    assert (
        result["recommended_agent_action"]
        == "continue_with_read_only_safe_next_step"
    )
    assert result["completion_rule"].startswith("Do not call update_goal from north-star-status alone")
    assert result["remaining_gaps"]
    assert result["remaining_gap_count"] == len(result["remaining_gaps"])
    assert result["blocked_gap_count"] == result["blocker_summary"]["blocked_gap_count"]
    assert result["blocked_gate_count"] == result["blocked_gap_count"]
    assert result["blocked_gap_ids"] == result["blocker_summary"]["blocked_gap_ids"]
    assert result["cleared_gap_count"] == result["blocker_summary"]["cleared_gap_count"]
    assert result["cleared_gap_ids"] == result["blocker_summary"]["cleared_gap_ids"]
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] is False
    assert any(item["id"] == "safe-ribbon-view-tab" for item in result["approval_candidates"])
    assert any(item["gap_id"] == "bridge_restart_validation" for item in result["manual_gates"])
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "agent_stop_status: `autonomous_progress_available`" in markdown_text
    assert "should_stop_agent: `false`" in markdown_text
    assert "agent_stop_reason: `None`" in markdown_text
    assert (
        "recommended_agent_action: `continue_with_read_only_safe_next_step`"
        in markdown_text
    )
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `false`" in markdown_text


def test_north_star_watch_stops_on_bridge_ready_without_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": True,
            "requires_revit_restart_or_reload": False,
        },
    )

    class Observer:
        def status(self):
            return {
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {
                    "hwnd": 123,
                    "title": "Autodesk Revit 2025",
                    "is_hung": False,
                },
            }

        def list_dialogs(self):
            return {"count": 0, "dialogs": []}

    class Bridge:
        def bridge_readiness(self):
            return {
                "ready_for_continuous_bridge": True,
                "requires_revit_restart_or_reload": False,
                "checks": [{"name": "loaded_build_current", "passed": True}],
            }

    result = north_star.run_north_star_watch(
        TaskJournal(tmp_path, "north-star-watch-test"),
        Observer(),
        Bridge(),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        checks=3,
        poll_seconds=0,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "changed"
    assert result["stop_reason"] == "bridge_ready"
    assert result["check_count"] == 1
    assert result["observations"][0]["ready_for_continuous_bridge"] is True
    assert result["north_star_status"]["may_call_update_goal"] is False
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["blocked_gap_count"] >= 1
    assert result["safety_guard_violation_count"] == 0
    assert result["completion_gate"]["completion_allowed"] is False
    assert result["completion_gate"]["may_call_update_goal"] is False
    assert result["completion_gate"]["blocked_gap_count"] >= 1
    assert result["stable_current_files"]["files"]["completion_gate"]
    assert result["unblock_readiness"]["status"] == "blocked"
    assert result["unblock_readiness"]["may_execute_from_this_result"] is False
    assert "does not focus, click, type" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_north_star_watch_stops_on_recovery_condition_without_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )

    class Observer:
        def status(self):
            return {
                "revit_running": True,
                "state": "modal",
                "active_dialogs": [{"title": "Warning"}],
                "main_window": {
                    "hwnd": 123,
                    "title": "Autodesk Revit 2025",
                    "is_hung": False,
                },
            }

        def list_dialogs(self):
            return {"count": 1, "dialogs": [{"title": "Warning", "buttons": ["OK"]}]}

    class Bridge:
        def bridge_readiness(self):
            return {
                "ready_for_continuous_bridge": False,
                "requires_revit_restart_or_reload": True,
                "checks": [{"name": "loaded_build_current", "passed": False}],
            }

    result = north_star.run_north_star_watch(
        TaskJournal(tmp_path, "north-star-watch-recovery-test"),
        Observer(),
        Bridge(),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        checks=3,
        poll_seconds=0,
    )

    assert result["success"] is True
    assert result["status"] == "changed"
    assert result["stop_reason"] == "recovery_condition_detected"
    assert result["check_count"] == 1
    assert result["observations"][0]["requires_recovery_attention"] is True
    assert result["observations"][0]["dialog_count"] == 1
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["completion_gate"]["completion_allowed"] is False
    assert result["completion_gate"]["may_call_update_goal"] is False
    assert result["unblock_readiness"]["may_call_update_goal"] is False


def test_north_star_watch_can_refresh_approval_preflight_before_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    captured = {}

    def fake_preflight(
        journal,
        *,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
        run_preflight,
    ):
        captured.update(
            {
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
                "run_preflight_present": run_preflight is not None,
            }
        )
        path = journal.run_dir / "north_star_approval_preflight.json"
        markdown = journal.run_dir / "north_star_approval_preflight.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# preflight", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "preflighted",
            "path": str(path),
            "markdown_path": str(markdown),
            "ready_for_human_approval_count": 3,
            "unsafe_preflight_count": 0,
            "approval_preflight_freshness": {
                "expires_at_utc": "2026-05-13T17:00:00Z",
            },
        }

    monkeypatch.setattr(north_star, "build_north_star_approval_preflight", fake_preflight)

    class Observer:
        def status(self):
            return {
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {
                    "hwnd": 123,
                    "title": "Autodesk Revit 2025",
                    "is_hung": False,
                },
            }

        def list_dialogs(self):
            return {"count": 0, "dialogs": []}

    class Bridge:
        def bridge_readiness(self):
            return {
                "ready_for_continuous_bridge": False,
                "requires_revit_restart_or_reload": True,
                "checks": [{"name": "loaded_build_current", "passed": False}],
            }

    result = north_star.run_north_star_watch(
        TaskJournal(tmp_path, "north-star-watch-preflight-refresh-test"),
        Observer(),
        Bridge(),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        refresh_approval_preflight=True,
        run_preflight=lambda _argv, _item_id: {"success": True},
        checks=1,
        poll_seconds=0,
    )

    assert captured == {
        "default_sheet_number": "S2.0",
        "revit_version": "2025",
        "expected_title_contains": "24522 St John XXIII",
        "expected_path_contains": "",
        "expected_view_name": "STARTING VIEW",
        "expected_view_type": "DrawingSheet",
        "run_preflight_present": True,
    }
    refresh = result["approval_preflight_refresh"]
    assert refresh["requested"] is True
    assert refresh["ran"] is True
    assert refresh["status"] == "preflighted"
    assert refresh["ready_for_human_approval_count"] == 3
    assert refresh["unsafe_preflight_count"] == 0
    assert refresh["expires_at_utc"] == "2026-05-13T17:00:00Z"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["completion_gate"]["completion_allowed"] is False


def test_north_star_watch_can_publish_current_handoff_after_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    events = []
    captured = {}

    def fake_preflight(
        journal,
        *,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
        run_preflight,
    ):
        events.append("preflight")
        path = journal.run_dir / "north_star_approval_preflight.json"
        markdown = journal.run_dir / "north_star_approval_preflight.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# preflight", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "preflighted",
            "path": str(path),
            "markdown_path": str(markdown),
            "ready_for_human_approval_count": 3,
            "unsafe_preflight_count": 0,
            "approval_preflight_freshness": {
                "expires_at_utc": "2026-05-13T17:00:00Z",
            },
        }

    def fake_handoff(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        events.append("handoff")
        captured.update(
            {
                "repo_root": repo_root,
                "command_names": command_names,
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            }
        )
        path = journal.run_dir / "north_star_current_handoff.json"
        markdown = journal.run_dir / "north_star_current_handoff.md"
        stable = journal.sandbox / "NORTH_STAR_HANDOFF_CURRENT.json"
        stable_markdown = journal.sandbox / "NORTH_STAR_HANDOFF_CURRENT.md"
        stable_files = {
            "handoff_json": str(stable),
            "handoff_markdown": str(stable_markdown),
        }
        stable_unblock = journal.sandbox / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
        stable_unblock_markdown = journal.sandbox / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
        if stable_unblock.exists():
            stable_files["unblock_readiness"] = str(stable_unblock)
        if stable_unblock_markdown.exists():
            stable_files["unblock_readiness_markdown"] = str(stable_unblock_markdown)
        for artifact, text in [
            (path, "{}"),
            (markdown, "# handoff"),
            (stable, "{}"),
            (stable_markdown, "# handoff"),
        ]:
            artifact.write_text(text, encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "path": str(path),
            "markdown_path": str(markdown),
            "stable_files": stable_files,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
        }

    def fake_unblock_readiness(journal):
        events.append("unblock_readiness")
        path = journal.run_dir / "north_star_unblock_readiness.json"
        markdown = journal.run_dir / "north_star_unblock_readiness.md"
        stable = journal.sandbox / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
        stable_markdown = journal.sandbox / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
        for artifact, text in [
            (path, "{}"),
            (markdown, "# unblock"),
            (stable, "{}"),
            (stable_markdown, "# unblock"),
        ]:
            artifact.write_text(text, encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "path": str(path),
            "markdown_path": str(markdown),
            "stable_path": str(stable),
            "stable_markdown_path": str(stable_markdown),
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "may_execute_from_this_result": False,
        }

    def fake_completion_gate(journal, *, repo_root, command_names):
        events.append("completion_gate")
        path = journal.run_dir / "north_star_completion_gate.json"
        markdown = journal.run_dir / "north_star_completion_gate.md"
        audit = journal.run_dir / "north_star_audit.json"
        audit_markdown = journal.run_dir / "north_star_audit.md"
        for artifact, text in [
            (path, "{}"),
            (markdown, "# gate"),
            (audit, "{}"),
            (audit_markdown, "# audit"),
        ]:
            artifact.write_text(text, encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "path": str(path),
            "markdown_path": str(markdown),
            "audit_path": str(audit),
            "audit_markdown_path": str(audit_markdown),
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "unsatisfied_count": 1,
            "safety_guard_violations": [],
        }

    monkeypatch.setattr(north_star, "build_north_star_approval_preflight", fake_preflight)
    monkeypatch.setattr(north_star, "build_north_star_current_handoff", fake_handoff)
    monkeypatch.setattr(north_star, "build_north_star_unblock_readiness", fake_unblock_readiness)
    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    class Observer:
        def status(self):
            return {
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {
                    "hwnd": 123,
                    "title": "Autodesk Revit 2025",
                    "is_hung": False,
                },
            }

        def list_dialogs(self):
            return {"count": 0, "dialogs": []}

    class Bridge:
        def bridge_readiness(self):
            return {
                "ready_for_continuous_bridge": False,
                "requires_revit_restart_or_reload": True,
                "checks": [{"name": "loaded_build_current", "passed": False}],
            }

    result = north_star.run_north_star_watch(
        TaskJournal(tmp_path, "north-star-watch-current-handoff-refresh-test"),
        Observer(),
        Bridge(),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_path_contains="Working Drawings",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        refresh_approval_preflight=True,
        publish_current_handoff=True,
        run_preflight=lambda _argv, _item_id: {"success": True},
        checks=1,
        poll_seconds=0,
    )

    assert events == [
        "preflight",
        "handoff",
        "unblock_readiness",
        "handoff",
        "completion_gate",
        "completion_gate",
    ]
    assert captured["default_sheet_number"] == "S2.0"
    assert captured["revit_version"] == "2025"
    assert captured["expected_title_contains"] == "24522 St John XXIII"
    assert captured["expected_path_contains"] == "Working Drawings"
    assert captured["expected_view_name"] == "STARTING VIEW"
    assert captured["expected_view_type"] == "DrawingSheet"
    handoff = result["current_handoff_refresh"]
    assert handoff["requested"] is True
    assert handoff["ran"] is True
    assert handoff["status"] == "blocked"
    assert handoff["completion_allowed"] is False
    assert handoff["may_call_update_goal"] is False
    assert handoff["audit_completion_authorized"] is False
    assert handoff["blocked_gap_ids"] == ["bridge_restart_validation"]
    assert handoff["may_execute_from_this_result"] is False
    assert handoff["refresh_count"] == 2
    assert handoff["post_unblock_refresh_ran"] is True
    assert Path(handoff["stable_files"]["handoff_json"]).exists()
    assert Path(handoff["stable_files"]["unblock_readiness"]).exists()
    assert Path(handoff["stable_files"]["unblock_readiness_markdown"]).exists()
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is None
    assert result["blocked_gap_ids"] == ["bridge_restart_validation"]
    assert result["blocked_gap_count"] == 1
    assert result["blocked_gate_count"] == 1
    assert result["unsatisfied_count"] == 1
    assert result["safety_guard_violation_count"] == 0
    assert result["completion_gate"]["completion_allowed"] is False
    assert result["unblock_readiness"]["may_execute_from_this_result"] is False
    assert result["agent_stop_status_refresh"]["ran"] is True
    assert result["agent_stop_status_refresh"]["may_execute_from_this_result"] is False
    assert result["final_agent_stop_status_refresh"]["ran"] is True
    assert result["final_agent_stop_status_refresh"]["completion_allowed"] is False
    assert (
        result["final_agent_stop_status_refresh"]["may_execute_from_this_result"]
        is False
    )
    final_stop_path = Path(result["final_agent_stop_status_refresh"]["path"])
    assert final_stop_path.exists()
    stable_stop_path = Path(
        result["final_agent_stop_status_refresh"]["stable_files"]["agent_stop_status"]
    )
    assert stable_stop_path.exists()


def test_north_star_resume_check_runs_readonly_post_restart_validation(tmp_path, monkeypatch):
    status_calls = []

    def fake_status(journal, *, repo_root, command_names, default_sheet_number):
        status_calls.append(default_sheet_number)
        return {
            "success": True,
            "read_only": True,
            "status": "not_complete",
            "north_star_complete": False,
            "may_call_update_goal": False,
            "path": str(journal.run_dir / "north_star_status.json"),
            "remaining_gaps": [
                {
                    "id": "bridge_restart_validation",
                    "description": "human-approved Revit restart/reload and post-restart bridge validation",
                }
            ],
            "blocker_summary": {"completion_blocked": True, "blocked_gap_count": 1},
            "completion_actions": {
                "may_call_update_goal": False,
                "human_actions": [{"gap_id": "bridge_restart_validation"}],
                "real_condition_actions": [],
                "autonomous_actions": [],
            },
        }

    def fake_approval_plan(journal, *, default_sheet_number):
        return {
            "success": True,
            "read_only": True,
            "path": str(journal.run_dir / "north_star_approval_plan.json"),
            "approval_items": [{"id": "safe-ribbon-view-tab"}],
            "manual_items": [{"id": "human-restart-reload-revit"}],
            "safety_note": "read-only",
        }

    def fake_audit(journal, *, repo_root, command_names):
        return {
            "success": True,
            "read_only": True,
            "status": "not_complete",
            "north_star_complete": False,
            "path": str(journal.run_dir / "north_star_audit.json"),
            "remaining_gaps": ["human-approved Revit restart/reload"],
            "blocker_summary": {"completion_blocked": True, "blocked_gap_count": 1},
            "gap_evidence": [
                {
                    "id": "bridge_restart_validation",
                    "description": "human-approved Revit restart/reload and post-restart bridge validation",
                    "blocker": {
                        "blocked": True,
                        "type": "human_action_required",
                        "autonomy_status": "requires_human_restart_or_reload",
                        "next_step": "Human must safely restart or reload Revit without save/sync.",
                    },
                    "evidence": {"failed_checks": ["loaded_build_current"]},
                }
            ],
        }

    validation_calls = []

    def fake_bridge_validation(*args, **kwargs):
        validation_calls.append(kwargs)
        return {
            "success": False,
            "read_only": True,
            "status": "failed",
            "validation_passed": False,
            "path": str(tmp_path / "bridge_post_restart_validation.json"),
            "checks": [
                {"name": "loaded_build_current", "passed": False},
                {"name": "model_ready", "passed": True},
            ],
        }

    monkeypatch.setattr(north_star, "build_north_star_status", fake_status)
    monkeypatch.setattr(north_star, "build_north_star_approval_plan", fake_approval_plan)
    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)

    class Observer:
        def status(self):
            return {"revit_running": True, "state": "idle", "active_dialogs": []}

    class Bridge:
        pass

    result = north_star.run_north_star_resume_check(
        TaskJournal(tmp_path, "north-star-resume-check-test"),
        Observer(),
        Bridge(),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        bridge_post_restart_validation_fn=fake_bridge_validation,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked_human_or_real_condition"
    assert result["bridge_validation_ran"] is True
    assert result["bridge_validation"]["failed_checks"] == ["loaded_build_current"]
    assert result["may_call_update_goal"] is False
    assert result["completion_allowed"] is False
    assert result["completion_gate"]["status"] == "blocked"
    assert result["completion_gate"]["may_call_update_goal"] is False
    assert result["completion_gate"]["blocked_gate_details"]
    assert result["completion_gate"]["followup_actions"]
    assert result["completion_gate"]["stable_artifact_hints"]
    assert result["agent_stop_status_refresh"]["ran"] is True
    assert result["agent_stop_status_refresh"]["may_execute_from_this_result"] is False
    assert result["final_agent_stop_status_refresh"]["ran"] is True
    assert result["final_agent_stop_status_refresh"]["completion_allowed"] is False
    assert (
        result["final_agent_stop_status_refresh"]["may_execute_from_this_result"]
        is False
    )
    for field in [
        "north_star_complete",
        "completion_allowed",
        "may_call_update_goal",
        "audit_completion_authorized",
        "blocked_gap_ids",
        "blocked_gap_count",
        "blocked_gate_count",
        "unsatisfied_count",
        "safety_guard_violation_count",
    ]:
        assert field in result
        assert result[field] == result["completion_gate"][field]
    resume_mirror = north_star._latest_resume_completion_mirror_report(tmp_path)
    assert resume_mirror["status"] == "clean"
    assert Path(result["completion_gate"]["path"]).is_relative_to(tmp_path)
    assert Path(result["completion_gate"]["markdown_path"]).is_relative_to(tmp_path)
    assert result["stable_current_files"]["success"] is True
    assert (
        Path(result["stable_current_files"]["files"]["completion_gate"])
        == tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    )
    assert (
        Path(result["stable_current_files"]["files"]["completion_gate_markdown"])
        == tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md"
    )
    assert "does not focus, click, type" in result["safety_note"]
    assert "publish stable current audit/completion-gate files" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert len(status_calls) == 2
    assert validation_calls[0]["expected_title_contains"] == "24522 St John XXIII"


def test_north_star_human_gate_packet_writes_json_and_markdown(tmp_path, monkeypatch):
    checklist = tmp_path / "revit_operator_runs" / "bridge-plan" / "bridge_restart_no_save_checklist.md"
    checklist.parent.mkdir(parents=True)
    checklist.write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge metadata.",
                "Failed bridge checks: `loaded_build_current`",
                "restart_or_reload_required: `True`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "",
                "Do not mark the north-star goal complete unless a fresh "
                "`north-star-completion-gate` or `north-star-resume-check.completion_gate` "
                "reports `completion_allowed: true`, `may_call_update_goal: true`, "
                "and `audit_completion_authorized: true`. Status and audit summaries "
                "are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )
    endurance = tmp_path / "revit_operator_runs" / "supervision-audit" / "supervision_endurance_audit.json"
    endurance.parent.mkdir(parents=True)
    endurance.write_text(json.dumps({"target_met": True}), encoding="utf-8")
    preflight_path = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight_markdown = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    preflight_path.write_text(
        json.dumps(
                {
                    "status": "preflighted",
                    "approval_preflight_freshness": _test_preflight_freshness(),
                    "approval_item_count": 2,
                    "ready_for_human_approval_count": 1,
                "requires_state_change_count": 1,
                "requires_prevalidation_count": 0,
                "unsafe_preflight_count": 0,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "prevalidation_status": "prevalidated_one_exact_target",
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in test fixture.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "prevalidation_status": "not_currently_executable",
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Target not visible in test fixture.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    preflight_markdown.write_text("# preflight", encoding="utf-8")
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
        },
    )

    result = north_star.build_north_star_human_gate_packet(
        TaskJournal(tmp_path, "north-star-human-gate-packet-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked_human_or_real_condition"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["may_execute_from_this_result"] is False
    assert "not completion authority" in result["completion_authority_note"]
    assert result["completion_gate_required"] is True
    assert result["completion_gate_command"] == ["north-star-completion-gate"]
    assert "north-star-status" not in result["completion_rule"]
    assert result["remaining_gap_count"] == len(result["remaining_gaps"])
    assert result["blocked_gap_count"] == result["blocker_summary"]["blocked_gap_count"]
    assert result["blocked_gap_ids"] == result["blocker_summary"]["blocked_gap_ids"]
    assert result["cleared_gap_count"] == result["blocker_summary"]["cleared_gap_count"]
    assert result["cleared_gap_ids"] == result["blocker_summary"]["cleared_gap_ids"]
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] is True
    assert result["approval_items"]
    assert any(item["recommended"] for item in result["approval_items"])
    assert result["approval_preflight_readiness"]["available"] is True
    assert result["approval_preflight_readiness"]["ready_for_human_approval_count"] == 1
    first_approval = result["approval_items"][0]
    assert first_approval["approval_ready_now"] is True
    assert first_approval["approval_readiness"]["status"] == "ready_for_human_approval"
    context_approval = next(
        item for item in result["approval_items"] if item["id"] == "context-menu-project-browser-target"
    )
    assert context_approval["approval_ready_now"] is False
    assert context_approval["approval_readiness"]["status"] == "requires_ui_state_change"
    assert first_approval["verify_command"][0] == "north-star-approval-verify"
    assert first_approval["verify_powershell"].startswith(
        "revit-operator north-star-approval-verify"
    )
    assert first_approval["required_human_approval_phrase"].startswith(
        f"I approve {first_approval['id']} with token APPROVE:"
    )
    assert first_approval["approval_phrase_expires_at_utc"]
    assert first_approval["approval_preflight_remaining_seconds"] is not None
    assert first_approval["approval_phrase_execution_authority"] is False
    assert "not execution authority" in first_approval["approval_phrase_safety_note"]
    assert first_approval["phrase_verify_command"][0] == "north-star-approval-phrase-verify"
    assert first_approval["phrase_verify_powershell"].startswith(
        "revit-operator north-star-approval-phrase-verify"
    )
    assert first_approval["execution_preview_command"][0] == "north-star-approved-execution-preview"
    assert first_approval["execution_preview_powershell"].startswith(
        "revit-operator north-star-approved-execution-preview"
    )
    assert first_approval["approval_freshness"]["freshness_rule"].startswith(
        "Regenerate north-star-approval-plan"
    )
    assert result["manual_artifacts"]
    assert result["manual_artifacts"][0]["id"] == "bridge-restart-no-save-checklist"
    assert result["manual_artifacts"][0]["present"] is True
    completion_steps = {item["id"]: item for item in result["manual_completion_checklist"]}
    assert "complete-bridge-restart-validation" in completion_steps
    assert completion_steps["complete-bridge-restart-validation"]["manual_artifacts"][0]["path"] == str(checklist)
    assert "complete-real-recovery-drill" in completion_steps
    assert "complete-approved-ui-workflow-execution" in completion_steps
    assert "approved-workflow-open-sheet" in completion_steps[
        "complete-approved-ui-workflow-execution"
    ]["approval_item_ids"]
    assert "complete-approved-uia-ribbon-context-execution" in completion_steps
    assert "safe-ribbon-view-tab" in completion_steps[
        "complete-approved-uia-ribbon-context-execution"
    ]["approval_item_ids"]
    assert not any(item.get("gap_id") == "supervision_endurance" for item in result["manual_completion_checklist"])
    assert "supervision_endurance" in result["blocker_summary"]["cleared_gap_ids"]
    assert not any(item["id"] == "supervision-endurance-wait" for item in result["manual_items"])
    assert result["post_human_gate_resume_command"][:4] == [
        "north-star-resume-check",
        "--sheet-number",
        "S2.0",
        "--revit-version",
    ]
    assert result["post_human_gate_resume_powershell"].startswith(
        "revit-operator north-star-resume-check"
    )
    assert "--expected-title-contains '24522 St John XXIII'" in result[
        "post_human_gate_resume_powershell"
    ]
    assert "--expected-view-name 'STARTING VIEW'" in result["post_human_gate_resume_powershell"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown = Path(result["markdown_path"])
    assert markdown.is_relative_to(tmp_path)
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in markdown_text
    assert "completion_allowed: `false`" in markdown_text
    assert "audit_completion_authorized: `false`" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "blocked_gap_count:" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "remaining_gap_count:" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `true`" in markdown_text
    assert "Blocked Gap IDs" in markdown_text
    assert "Manual Completion Checklist" in markdown_text
    assert "Approval Preflight Readiness" in markdown_text
    assert "ready_for_human_approval_count: `1`" in markdown_text
    assert "complete-bridge-restart-validation" in markdown_text
    assert "bridge-restart-no-save-checklist" in markdown_text
    assert str(checklist) in markdown_text
    assert "Bound payload digest" in markdown_text
    assert "Freshness rule:" in markdown_text
    assert "Verify token before execute" in markdown_text
    assert "Required human approval phrase" in markdown_text
    assert "Approval phrase expires at:" in markdown_text
    assert "Approval phrase execution authority: `false`" in markdown_text
    assert "not execution authority" in markdown_text
    assert "Verify phrase before execute" in markdown_text
    assert "Preview separate execution command" in markdown_text
    assert "Approval readiness: `ready_for_human_approval`" in markdown_text
    approval_gap_lines = [
        f"  gap_ids: `{', '.join(map(str, item['gap_ids']))}`"
        for item in result["approval_items"]
        if isinstance(item.get("gap_ids"), list)
    ]
    assert approval_gap_lines
    for line in approval_gap_lines:
        assert line in markdown_text
    assert "Completion authority:" in markdown_text
    assert "Approval gate: Do not request or execute this approval until readiness is cleared." in markdown_text
    assert "--expected-title-contains '24522 St John XXIII'" in markdown_text
    assert "--expected-view-name 'STARTING VIEW'" in markdown_text
    assert "Do not mark the goal complete" in markdown.read_text(encoding="utf-8")
    assert "north-star-completion-gate" in markdown_text


def test_north_star_human_gate_packet_does_not_label_autonomous_work_as_human_blocked(
    tmp_path,
    monkeypatch,
):
    def fake_status(journal, *, repo_root, command_names, default_sheet_number):
        status_path = journal.run_dir / "north_star_status.json"
        status_markdown = journal.run_dir / "north_star_status.md"
        payload = {
            "success": True,
            "read_only": True,
            "status": "not_complete",
            "north_star_complete": False,
            "may_call_update_goal": False,
            "completion_allowed": False,
            "audit_completion_authorized": False,
            "blocked_gap_ids": ["supervision_endurance"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "cleared_gap_ids": [],
            "cleared_gap_count": 0,
            "remaining_gap_count": 1,
            "remaining_gaps": [
                {
                    "id": "supervision_endurance",
                    "description": "supervision endurance evidence still needed",
                }
            ],
            "blocker_summary": {
                "blocked_gap_ids": ["supervision_endurance"],
                "blocked_gap_count": 1,
                "cleared_gap_ids": [],
                "cleared_gap_count": 0,
            },
            "completion_actions": {
                "autonomous_progress_available": True,
                "human_or_real_condition_required": False,
                "may_call_update_goal": False,
                "autonomous_actions": [
                    {
                        "gap_id": "supervision_endurance",
                        "next_step": "Run read-only supervision endurance audit.",
                    }
                ],
                "human_actions": [],
                "real_condition_actions": [],
            },
            "autonomous_progress_available": True,
            "human_or_real_condition_required": False,
            "blocked_waiting_for_human_or_real_condition": False,
            "path": str(status_path),
            "markdown_path": str(status_markdown),
        }
        status_path.write_text(json.dumps(payload), encoding="utf-8")
        status_markdown.write_text("# status", encoding="utf-8")
        return payload

    def fake_approval_plan(journal, *, default_sheet_number):
        path = journal.run_dir / "north_star_approval_plan.json"
        markdown = journal.run_dir / "north_star_approval_plan.md"
        payload = {
            "success": True,
            "read_only": True,
            "approval_items": [],
            "manual_items": [],
            "path": str(path),
            "markdown_path": str(markdown),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        markdown.write_text("# approval plan", encoding="utf-8")
        return payload

    monkeypatch.setattr(north_star, "build_north_star_status", fake_status)
    monkeypatch.setattr(north_star, "build_north_star_approval_plan", fake_approval_plan)

    result = north_star.build_north_star_human_gate_packet(
        TaskJournal(tmp_path, "north-star-human-gate-packet-autonomous-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["status"] == "autonomous_progress_available"
    assert result["autonomous_progress_available"] is True
    assert result["human_or_real_condition_required"] is False
    assert result["blocked_waiting_for_human_or_real_condition"] is False
    assert result["may_call_update_goal"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["blocked_gate_count"] == result["blocked_gap_count"] == 1
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Status: `autonomous_progress_available`" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `false`" in markdown_text


def test_north_star_next_human_action_card_writes_stable_unblock_summary(tmp_path, monkeypatch):
    checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    checklist.write_text("no-save checklist", encoding="utf-8")
    source_checklist = (
        tmp_path
        / "revit_operator_runs"
        / "bridge-plan"
        / "bridge_restart_no_save_checklist.md"
    )
    source_checklist.parent.mkdir(parents=True)
    source_checklist.write_text("source no-save checklist", encoding="utf-8")
    resume_script = tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    resume_script.write_text("# resume", encoding="utf-8")
    supervised_script = tmp_path / "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1"
    supervised_script.write_text("# supervised", encoding="utf-8")

    def fake_completion_gate(journal, *, repo_root, command_names):
        gate_path = journal.run_dir / "north_star_completion_gate.json"
        gate_markdown = journal.run_dir / "north_star_completion_gate.md"
        gate = {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "unsatisfied_count": 4,
            "blocked_gap_ids": [
                "bridge_restart_validation",
                "live_ui_workflow_execution",
                "live_recovery_drills",
                "live_uia_ribbon_context_execution",
            ],
            "blocked_gap_count": 4,
            "blocked_gate_count": 4,
            "blocked_gate_details": [
                {
                    "id": "bridge_restart_validation",
                    "next_step": "Human restart/reload required.",
                    "no_save_checklist_path": str(source_checklist),
                    "failed_checks": ["loaded_build_current"],
                    "requires_revit_restart_or_reload": True,
                    "no_save_checklist_present": True,
                    "restart_context": {
                        "available": True,
                        "title": "24522 detached",
                        "path": "24522 detached.rvt",
                        "revit_version": "2025",
                        "dirty": True,
                        "worksharing": "enabled",
                        "active_view_name": "STARTING VIEW",
                        "active_view_type": "DrawingSheet",
                    },
                },
                {"id": "live_ui_workflow_execution"},
                {
                    "id": "live_recovery_drills",
                    "reason": "No real stuck state exists.",
                },
                {"id": "live_uia_ribbon_context_execution"},
            ],
            "waiting_state_summary": {
                "available": True,
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:abc123"
                ),
                "preflight_freshness_guard": {
                    "status": "fresh",
                    "matched": True,
                    "expires_at_utc": "2026-05-13T14:00:00Z",
                    "remaining_seconds": 600,
                },
            },
            "next_approval_summary": {
                "available": True,
                "selected_item_id": "safe-ribbon-view-tab",
                "selected_expected_effect": "Select the Revit View ribbon tab only.",
                "selected_gap_ids": ["live_uia_ribbon_context_execution"],
            },
            "supervised_command_packet": {
                "available": True,
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:abc123"
                ),
                "phrase_must_be_supplied_by_human": True,
                "auto_supplied_phrase_in_commands": False,
            },
            "stable_artifact_hints": [
                {
                    "id": "restart-no-save-checklist",
                    "path": str(checklist),
                    "present": True,
                },
                {
                    "id": "post-human-resume-script",
                    "path": str(resume_script),
                    "present": True,
                },
                {
                    "id": "supervised-readonly-script",
                    "path": str(supervised_script),
                    "present": True,
                },
            ],
            "path": str(gate_path),
            "markdown_path": str(gate_markdown),
        }
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        gate_markdown.write_text("# gate", encoding="utf-8")
        return gate

    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_next_human_action_card(
        TaskJournal(tmp_path, "north-star-next-human-action-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked_waiting_for_human_or_real_condition"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["blocked_gap_count"] == len(result["blocked_gap_ids"])
    assert result["blocked_gate_count"] == len(result["blocked_gap_ids"])
    assert result["completion_gate"]["blocked_gap_count"] == len(result["blocked_gap_ids"])
    assert result["completion_gate"]["blocked_gate_count"] == len(result["blocked_gap_ids"])
    assert result["completion_gate"]["audit_completion_authorized"] is False
    options = {item["id"]: item for item in result["next_human_options"]}
    assert result["option_count"] == 3
    assert result["option_ids"] == [
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
        "wait-for-real-recovery-condition",
    ]
    summaries = {item["id"]: item for item in result["option_summaries"]}
    assert summaries["human-restart-or-reload-revit"]["failed_bridge_checks"] == [
        "loaded_build_current"
    ]
    assert summaries["human-restart-or-reload-revit"]["post_action_resume_script"] == str(
        resume_script
    )
    assert summaries["human-restart-or-reload-revit"][
        "post_action_resume_command"
    ][0] == "north-star-resume-check"
    assert summaries["human-restart-or-reload-revit"][
        "post_action_resume_command_present"
    ] is True
    assert "north-star-resume-check" in summaries["human-restart-or-reload-revit"][
        "post_action_resume_powershell"
    ]
    assert "--execute" not in summaries["human-restart-or-reload-revit"][
        "post_action_resume_powershell"
    ]
    assert "--approval-token" not in summaries["human-restart-or-reload-revit"][
        "post_action_resume_powershell"
    ]
    assert summaries["provide-exact-human-approval-phrase"][
        "selected_item_covers_all_approval_blockers"
    ] is False
    assert "required_human_approval_phrase" not in summaries[
        "provide-exact-human-approval-phrase"
    ]
    assert options["human-restart-or-reload-revit"]["checklist_path"] == str(checklist)
    assert options["human-restart-or-reload-revit"]["source_checklist_path"] == str(
        source_checklist
    )
    assert options["human-restart-or-reload-revit"]["post_action_resume_script"] == str(resume_script)
    assert options["human-restart-or-reload-revit"]["restart_context"]["dirty"] is True
    assert options["human-restart-or-reload-revit"]["failed_bridge_checks"] == [
        "loaded_build_current"
    ]
    assert (
        options["human-restart-or-reload-revit"]["bridge_technical_cause"]
        == "Loaded Revit add-in is stale or lacks current bridge metadata."
    )
    assert options["human-restart-or-reload-revit"]["requires_revit_restart_or_reload"] is True
    assert options["human-restart-or-reload-revit"]["no_save_checklist_present"] is True
    assert "Active copied model is dirty" in options["human-restart-or-reload-revit"]["dirty_state_warning"]
    assert options["provide-exact-human-approval-phrase"]["selected_item_id"] == "safe-ribbon-view-tab"
    assert options["provide-exact-human-approval-phrase"]["approval_blocker_gap_ids"] == [
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    ]
    assert options["provide-exact-human-approval-phrase"]["selected_item_gap_ids"] == [
        "live_uia_ribbon_context_execution"
    ]
    assert options["provide-exact-human-approval-phrase"][
        "remaining_approval_gap_ids_after_selected_item"
    ] == ["live_ui_workflow_execution"]
    assert (
        options["provide-exact-human-approval-phrase"][
            "selected_item_covers_all_approval_blockers"
        ]
        is False
    )
    assert options["provide-exact-human-approval-phrase"]["required_human_approval_phrase"] == (
        "I approve safe-ribbon-view-tab with token APPROVE:abc123"
    )
    assert (
        options["provide-exact-human-approval-phrase"][
            "required_human_approval_phrase_withheld"
        ]
        is False
    )
    assert options["provide-exact-human-approval-phrase"]["auto_supplied_phrase_in_commands"] is False
    assert options["provide-exact-human-approval-phrase"]["may_execute_from_this_option"] is False
    assert options["provide-exact-human-approval-phrase"]["preflight_fresh_now"] is True
    assert (
        options["provide-exact-human-approval-phrase"]["approval_preflight_status"]
        == "fresh"
    )
    assert (
        options["provide-exact-human-approval-phrase"]["approval_preflight_expires_at_utc"]
        == "2026-05-13T14:00:00Z"
    )
    assert (
        options["provide-exact-human-approval-phrase"]["preflight_guard_source"]
        == "handoff_artifact"
    )
    assert options["wait-for-real-recovery-condition"]["may_execute_from_this_option"] is False
    assert Path(result["stable_files"]["next_human_action"]) == (
        tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
    )
    assert Path(result["stable_files"]["next_human_action"]).exists()
    assert Path(result["stable_files"]["completion_gate"]) == (
        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    )
    assert Path(result["stable_files"]["completion_gate"]).exists()
    markdown = Path(result["stable_files"]["next_human_action_markdown"]).read_text(
        encoding="utf-8"
    )
    assert "Revit Operator Next Human Action" in markdown
    assert "audit_completion_authorized: `false`" in markdown
    assert "may_execute_from_this_result: `false`" in markdown
    assert "blocked_gap_count: `4`" in markdown
    assert "blocked_gate_count: `4`" in markdown
    assert "option_count: `3`" in markdown
    assert "option_ids:" in markdown
    assert "bridge_restart_validation" in markdown
    assert "human-restart-or-reload-revit" in markdown
    assert "Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata." in markdown
    assert "Failed bridge checks: `loaded_build_current`" in markdown
    assert "requires_revit_restart_or_reload: `true`" in markdown
    assert "no_save_checklist_present: `true`" in markdown
    assert "Active document: `24522 detached`" in markdown
    assert "Dirty: `true`" in markdown
    assert "Dirty warning:" in markdown
    assert "provide-exact-human-approval-phrase" in markdown
    assert "wait-for-real-recovery-condition" in markdown
    assert "I approve safe-ribbon-view-tab with token APPROVE:abc123" in markdown
    assert "Approval preflight status: `fresh`" in markdown
    assert "Approval preflight source: `handoff_artifact`" in markdown
    assert "Approval blocker gaps: `live_ui_workflow_execution, live_uia_ribbon_context_execution`" in markdown
    assert "Selected item gaps: `live_uia_ribbon_context_execution`" in markdown
    assert "Remaining approval gaps after selected item: `live_ui_workflow_execution`" in markdown
    assert "selected_item_covers_all_approval_blockers: `false`" in markdown
    assert "approval_coverage_fields_present: `true`" in markdown
    assert "Preflight fresh now: `true`" in markdown
    assert "Do not call update_goal" in markdown


def test_north_star_human_unblock_brief_redacts_approval_material(
    tmp_path, monkeypatch
):
    source_path = tmp_path / "revit_operator_runs" / "source" / "north_star_next_human_action.json"
    source_markdown = (
        tmp_path / "revit_operator_runs" / "source" / "north_star_next_human_action.md"
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text("{}", encoding="utf-8")
    source_markdown.write_text("# source", encoding="utf-8")
    checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    checklist.write_text("# checklist", encoding="utf-8")
    resume = tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    resume.write_text("# resume", encoding="utf-8")

    def fake_next_human(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        return {
            "success": True,
            "read_only": True,
            "status": "blocked_waiting_for_human_or_real_condition",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "autonomous_progress_available": False,
            "human_or_real_condition_required": True,
            "blocked_waiting_for_human_or_real_condition": True,
            "blocked_gap_ids": [
                "bridge_restart_validation",
                "live_ui_workflow_execution",
            ],
            "blocked_gap_count": 2,
            "blocked_gate_count": 2,
            "path": str(source_path),
            "markdown_path": str(source_markdown),
            "stable_files": {
                "next_human_action": str(tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"),
                "next_human_action_markdown": str(
                    tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md"
                ),
            },
            "completion_gate": {"path": str(tmp_path / "gate.json")},
            "next_human_options": [
                {
                    "id": "human-restart-or-reload-revit",
                    "kind": "human_action",
                    "gap_id": "bridge_restart_validation",
                    "may_execute_from_this_option": False,
                    "checklist_path": str(checklist),
                    "post_action_resume_script": str(resume),
                    "human_action": "Human performs restart/reload only.",
                },
                {
                    "id": "provide-exact-human-approval-phrase",
                    "kind": "human_approval",
                    "gap_ids": ["live_ui_workflow_execution"],
                    "selected_item_id": "safe-ui-workflow",
                    "required_human_approval_phrase": (
                        "I approve safe-ui-workflow with token APPROVE:abc123"
                    ),
                    "approval_token": "APPROVE:abc123",
                    "preflight_fresh_now": True,
                    "approval_preflight_status": "fresh",
                    "selected_item_covers_all_approval_blockers": True,
                    "remaining_approval_gap_ids_after_selected_item": [],
                    "may_execute_from_this_option": False,
                },
            ],
        }

    monkeypatch.setattr(
        north_star,
        "build_north_star_next_human_action_card",
        fake_next_human,
    )

    result = north_star.build_north_star_human_unblock_brief(
        TaskJournal(tmp_path, "human-unblock-brief-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["may_execute_from_this_result"] is False
    assert result["approval_material_present_in_source"] is True
    assert result["approval_material_included"] is False
    assert result["approval_material_withheld"] is True
    assert result["autonomous_progress_available"] is False
    assert result["human_or_real_condition_required"] is True
    assert result["blocked_waiting_for_human_or_real_condition"] is True
    assert (
        result["agent_stop_reason"]
        == "human_or_real_condition_required_no_autonomous_progress"
    )
    assert result["option_ids"] == [
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
    ]
    approval = {
        item["id"]: item for item in result["sanitized_options"]
    }["provide-exact-human-approval-phrase"]
    assert approval["approval_phrase_available_in_source"] is True
    assert approval["approval_material_available_in_source"] is True
    assert approval["approval_material_included"] is False
    assert approval["approval_material_withheld"] is True
    assert approval["required_human_approval_phrase_withheld"] is True
    assert "required_human_approval_phrase" not in approval
    payload = Path(result["path"]).read_text(encoding="utf-8")
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "APPROVE:" not in payload
    assert "I approve " not in payload
    assert "APPROVE:" not in markdown
    assert "I approve " not in markdown
    assert (
        "- agent_stop_reason: `human_or_real_condition_required_no_autonomous_progress`"
        in markdown
    )
    assert "approval_material_withheld: `true`" in markdown
    assert "required_human_approval_phrase_withheld: `true`" in markdown
    assert Path(result["stable_files"]["human_unblock_brief"]).exists()
    assert Path(result["stable_files"]["human_unblock_brief_markdown"]).exists()


def test_north_star_stable_artifact_scan_flags_human_unblock_withheld_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json").write_text(
        json.dumps(
            {
                "success": True,
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "approval_material_present_in_source": True,
                "approval_material_included": False,
                "approval_material_withheld": True,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "sanitized_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "approval_phrase_available_in_source": True,
                        "approval_material_available_in_source": True,
                        "approval_material_included": False,
                        "approval_material_withheld": False,
                        "required_human_approval_phrase_withheld": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Human Unblock Brief",
                "",
                "- approval_material_included: `false`",
                "- approval_material_withheld: `true`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-human-unblock-redaction-drift-test")
    )

    ids = {item["id"] for item in result["violations"]}
    assert result["status"] == "violations"
    assert result["human_unblock_brief_redaction_violation_count"] >= 1
    assert "human-unblock-option-approval-material-withheld-drift" in ids
    assert "human-unblock-option-phrase-withheld-drift" in ids


def test_north_star_agent_stop_status_publishes_credential_free_stop_artifact(
    tmp_path, monkeypatch
):
    def fake_human_unblock_brief(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        path = journal.run_dir / "north_star_human_unblock_brief.json"
        markdown = journal.run_dir / "north_star_human_unblock_brief.md"
        stable_path = journal.sandbox / "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json"
        stable_markdown = journal.sandbox / "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.md"
        checklist = journal.sandbox / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
        resume_script = journal.sandbox / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# brief", encoding="utf-8")
        stable_path.write_text("{}", encoding="utf-8")
        stable_markdown.write_text("# stable brief", encoding="utf-8")
        checklist.write_text("DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW", encoding="utf-8")
        resume_script.write_text("Write-Host 'resume'", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked_waiting_for_human_or_real_condition",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "autonomous_progress_available": False,
            "human_or_real_condition_required": True,
            "blocked_waiting_for_human_or_real_condition": True,
            "agent_stop_reason": "human_or_real_condition_required_no_autonomous_progress",
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "option_ids": [
                "human-restart-or-reload-revit",
                "provide-exact-human-approval-phrase",
            ],
            "sanitized_options": [
                {
                    "id": "human-restart-or-reload-revit",
                    "kind": "human_action",
                    "gap_ids": ["bridge_restart_validation"],
                    "checklist_path": str(checklist),
                    "post_action_resume_script": str(resume_script),
                    "approval_material_included": False,
                    "required_human_approval_phrase_withheld": None,
                },
                {
                    "id": "provide-exact-human-approval-phrase",
                    "kind": "human_approval",
                    "gap_ids": ["live_ui_workflow_execution"],
                    "approval_material_included": False,
                    "required_human_approval_phrase_withheld": True,
                },
            ],
            "approval_material_included": False,
            "approval_material_withheld": True,
            "source_artifacts": {
                "next_human_action": str(journal.run_dir / "north_star_next_human_action.json"),
                "stable_next_human_action": str(
                    journal.sandbox / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
                ),
            },
            "stable_files": {
                "human_unblock_brief": str(stable_path),
                "human_unblock_brief_markdown": str(stable_markdown),
            },
            "path": str(path),
            "markdown_path": str(markdown),
        }

    def fake_completion_gate(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_completion_gate.json"
        markdown = journal.run_dir / "north_star_completion_gate.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# gate", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "autonomous_progress_available": False,
            "human_or_real_condition_required": True,
            "completion_actions": {
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
            },
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "unsatisfied_count": 7,
            "safety_guard_violation_count": 0,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(
        north_star,
        "build_north_star_human_unblock_brief",
        fake_human_unblock_brief,
    )
    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_agent_stop_status(
        TaskJournal(tmp_path, "north-star-agent-stop-status-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "stop_for_human_or_real_condition"
    assert result["should_stop_agent"] is True
    assert result["recommended_agent_action"] == "wait_for_human_or_real_condition"
    assert result["may_execute_from_this_result"] is False
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["agent_stop_reason"] == (
        "human_or_real_condition_required_no_autonomous_progress"
    )
    assert result["option_ids"] == [
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
    ]
    assert result["human_unblock_paths"]["stable_human_unblock_brief"].endswith(
        "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json"
    )
    assert result["human_unblock_paths"]["restart_checklist"].endswith(
        "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    )
    assert result["human_unblock_paths"]["post_human_resume_script"].endswith(
        "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    )
    assert result["source_artifacts"]["stable_next_human_action"].endswith(
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
    )
    assert {
        item["id"] for item in result["sanitized_options"] if isinstance(item, dict)
    } == {
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
    }
    approval_option = {
        item["id"]: item
        for item in result["sanitized_options"]
        if isinstance(item, dict) and item.get("id")
    }["provide-exact-human-approval-phrase"]
    assert approval_option["approval_material_included"] is False
    assert approval_option["approval_material_withheld"] is True
    assert approval_option["required_human_approval_phrase_withheld"] is True
    payload = Path(result["path"]).read_text(encoding="utf-8")
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "APPROVE:" not in payload
    assert "I approve " not in payload
    assert "APPROVE:" not in markdown
    assert "I approve " not in markdown
    assert "should_stop_agent: `true`" in markdown
    assert "Human Unblock Paths" in markdown
    assert "Sanitized Options" in markdown
    assert "- approval_material_withheld: `true`" in markdown
    assert "approval_material_withheld: `true`" in markdown
    assert "required_human_approval_phrase_withheld: `true`" in markdown
    assert "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md" in markdown
    assert "NORTH_STAR_AGENT_STOP_STATUS_CURRENT" in payload
    assert Path(result["stable_files"]["agent_stop_status"]).exists()
    assert Path(result["stable_files"]["agent_stop_status_markdown"]).exists()
    assert Path(result["stable_files"]["human_unblock_brief"]).exists()
    assert Path(result["stable_files"]["human_unblock_brief_markdown"]).exists()


def test_north_star_next_human_action_requires_audit_completion_authority(
    tmp_path, monkeypatch
):
    def fake_completion_gate(journal, *, repo_root, command_names):
        gate_path = journal.run_dir / "north_star_completion_gate.json"
        gate_markdown = journal.run_dir / "north_star_completion_gate.md"
        gate = {
            "success": True,
            "read_only": True,
            "status": "ready_to_complete",
            "north_star_complete": True,
            "completion_allowed": True,
            "may_call_update_goal": True,
            "audit_completion_authorized": False,
            "unsatisfied_count": 0,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "blocked_gate_details": [],
            "path": str(gate_path),
            "markdown_path": str(gate_markdown),
        }
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        gate_markdown.write_text("# gate", encoding="utf-8")
        return gate

    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_next_human_action_card(
        TaskJournal(tmp_path, "north-star-next-human-action-audit-authority-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
    )

    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["completion_gate"]["completion_allowed"] is True
    assert result["completion_gate"]["may_call_update_goal"] is True
    assert result["audit_completion_authorized"] is False
    assert result["status"] == "blocked_waiting_for_human_or_real_condition"
    assert result["completion_gate"]["audit_completion_authorized"] is False
    assert result["next_human_options"][0]["id"] != "completion-gate-passed"


def test_north_star_next_human_action_summarizes_completion_without_granting_authority(
    tmp_path, monkeypatch
):
    def fake_completion_gate(journal, *, repo_root, command_names):
        gate_path = journal.run_dir / "north_star_completion_gate.json"
        gate_markdown = journal.run_dir / "north_star_completion_gate.md"
        gate = {
            "success": True,
            "read_only": True,
            "status": "ready_to_complete",
            "north_star_complete": True,
            "completion_allowed": True,
            "may_call_update_goal": True,
            "audit_completion_authorized": True,
            "unsatisfied_count": 0,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "blocked_gate_details": [],
            "path": str(gate_path),
            "markdown_path": str(gate_markdown),
        }
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        gate_markdown.write_text("# gate", encoding="utf-8")
        return gate

    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_next_human_action_card(
        TaskJournal(tmp_path, "north-star-next-human-action-completion-summary-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
    )

    assert result["status"] == "completion_gate_ready"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["completion_gate_allows_completion"] is True
    assert result["completion_gate"]["completion_allowed"] is True
    assert result["completion_gate"]["may_call_update_goal"] is True
    assert result["next_human_options"][0]["id"] == "completion-gate-passed"


def test_north_star_next_human_action_derives_resume_context_from_latest_preflight(
    tmp_path, monkeypatch
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
            }
        ),
        encoding="utf-8",
    )
    checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    checklist.write_text("no save checklist", encoding="utf-8")

    def fake_completion_gate(journal, *, repo_root, command_names):
        gate_path = journal.run_dir / "north_star_completion_gate.json"
        gate_markdown = journal.run_dir / "north_star_completion_gate.md"
        gate = {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "unsatisfied_count": 1,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "blocked_gate_details": [
                {
                    "id": "bridge_restart_validation",
                    "failed_checks": ["loaded_build_current"],
                    "requires_revit_restart_or_reload": True,
                    "no_save_checklist_present": True,
                    "no_save_checklist_path": str(checklist),
                    "restart_context": {"dirty": False},
                    "next_step": "Human restarts or reloads Revit.",
                }
            ],
            "stable_artifact_hints": [
                {
                    "id": "restart-no-save-checklist",
                    "path": str(checklist),
                    "present": True,
                }
            ],
            "path": str(gate_path),
            "markdown_path": str(gate_markdown),
        }
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        gate_markdown.write_text("# gate", encoding="utf-8")
        return gate

    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_next_human_action_card(
        TaskJournal(tmp_path, "north-star-next-human-action-derived-context-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
    )

    command = result["post_human_gate_resume_command"]
    assert "--expected-title-contains" in command
    assert "24522 St John XXIII" in command
    assert "--expected-path-contains" in command
    assert "Structural_Current Working-R25-BIM" in command
    assert "--expected-view-name" in command
    assert "STARTING VIEW" in command
    assert "--expected-view-type" in command
    assert "DrawingSheet" in command
    assert result["post_human_gate_resume_context"]["context_source_available"] is True

    report = north_star._next_human_action_resume_command_report(tmp_path)
    assert report["missing_context_option_count"] == 0
    assert report["context_mismatch_count"] == 0
    assert report["violations"] == []


def test_north_star_next_human_action_marks_stale_approval_phrase_unsafe(tmp_path):
    gate = {
        "blocked_gate_details": [
            {"id": "live_ui_workflow_execution"},
            {"id": "live_uia_ribbon_context_execution"},
        ],
        "waiting_state_summary": {
            "available": True,
            "required_human_approval_phrase": "I approve safe-ribbon-view-tab with token APPROVE:abc123",
            "preflight_freshness_guard": {
                "status": "preflight_stale",
                "matched": False,
                "expires_at_utc": "2026-05-13T13:00:00Z",
                "remaining_seconds": 0,
            },
        },
        "next_approval_summary": {
            "available": True,
            "selected_item_id": "safe-ribbon-view-tab",
            "selected_expected_effect": "Select the Revit View ribbon tab only.",
        },
        "supervised_command_packet": {
            "available": True,
            "required_human_approval_phrase": "I approve safe-ribbon-view-tab with token APPROVE:abc123",
            "phrase_must_be_supplied_by_human": True,
            "auto_supplied_phrase_in_commands": False,
        },
        "stable_artifact_hints": [],
    }

    options = {
        item["id"]: item
        for item in north_star._next_human_action_options(gate, sandbox=tmp_path, resume_command=[])
    }

    approval = options["provide-exact-human-approval-phrase"]
    assert approval["preflight_fresh_now"] is False
    assert approval["approval_preflight_status"] == "preflight_stale"
    assert approval["preflight_guard_source"] == "handoff_artifact"
    assert approval["required_human_approval_phrase"] is None
    assert approval["required_human_approval_phrase_withheld"] is True
    assert "Latest approval preflight is not fresh" in approval[
        "withheld_required_human_approval_phrase_reason"
    ]
    assert approval["approval_preflight_command"] == ["north-star-approval-preflight"]
    assert "must not be used" in approval["approval_phrase_safety_note"]


def test_north_star_next_human_action_uses_latest_preflight_freshness_over_snapshot(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": {
                    "generated_at_unix": 1,
                    "expires_at_unix": 2,
                    "expires_at_utc": "1970-01-01T00:00:02Z",
                    "ttl_seconds": 1,
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    gate = {
        "blocked_gate_details": [
            {"id": "live_ui_workflow_execution"},
            {"id": "live_uia_ribbon_context_execution"},
        ],
        "waiting_state_summary": {
            "available": True,
            "required_human_approval_phrase": "I approve safe-ribbon-view-tab with token APPROVE:abc123",
            "preflight_freshness_guard": {
                "status": "fresh",
                "matched": True,
                "expires_at_utc": "2999-01-01T00:00:00Z",
                "remaining_seconds": 600,
            },
        },
        "next_approval_summary": {
            "available": True,
            "selected_item_id": "safe-ribbon-view-tab",
            "selected_expected_effect": "Select the Revit View ribbon tab only.",
        },
        "supervised_command_packet": {
            "available": True,
            "required_human_approval_phrase": "I approve safe-ribbon-view-tab with token APPROVE:abc123",
            "phrase_must_be_supplied_by_human": True,
            "auto_supplied_phrase_in_commands": False,
        },
        "stable_artifact_hints": [],
    }

    options = {
        item["id"]: item
        for item in north_star._next_human_action_options(gate, sandbox=tmp_path, resume_command=[])
    }

    approval = options["provide-exact-human-approval-phrase"]
    assert approval["preflight_guard_source"] == "latest_preflight_artifact"
    assert approval["preflight_fresh_now"] is False
    assert approval["approval_preflight_status"] == "preflight_stale"
    assert approval["required_human_approval_phrase"] is None
    assert approval["required_human_approval_phrase_withheld"] is True


def test_north_star_next_human_action_keeps_stale_approval_path_visible(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": {
                    "generated_at_unix": 1,
                    "expires_at_unix": 2,
                    "expires_at_utc": "1970-01-01T00:00:02Z",
                    "ttl_seconds": 1,
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    gate = {
        "blocked_gate_details": [
            {"id": "live_ui_workflow_execution"},
            {"id": "live_uia_ribbon_context_execution"},
        ],
        "waiting_state_summary": {
            "available": True,
            "required_human_approval_phrase": None,
            "preflight_freshness_guard": {
                "status": "preflight_stale",
                "matched": False,
                "remaining_seconds": 0,
            },
        },
        "next_approval_summary": {
            "available": True,
            "status": "no_ready_approval",
            "selected_item_id": None,
        },
        "supervised_command_packet": {
            "available": False,
            "reason": "Waiting-state phrase or selected next-approval item is missing.",
        },
        "stable_artifact_hints": [],
    }

    options = {
        item["id"]: item
        for item in north_star._next_human_action_options(gate, sandbox=tmp_path, resume_command=[])
    }

    approval = options["provide-exact-human-approval-phrase"]
    assert approval["gap_ids"] == [
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    ]
    assert approval["selected_item_id"] is None
    assert approval["required_human_approval_phrase"] is None
    assert approval["required_human_approval_phrase_withheld"] is True
    assert approval["approval_preflight_status"] == "preflight_stale"
    assert approval["preflight_guard_source"] == "latest_preflight_artifact"
    assert approval["approval_preflight_command"] == ["north-star-approval-preflight"]
    assert "Rerun north-star-approval-preflight" in approval["next_step"]


def test_completion_gate_next_human_summary_recomputes_latest_preflight(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": {
                    "generated_at_unix": 1,
                    "expires_at_unix": 2,
                    "expires_at_utc": "1970-01-01T00:00:02Z",
                    "ttl_seconds": 1,
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "may_execute_from_this_option": False,
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [
                            "live_ui_workflow_execution",
                        ],
                        "selected_item_covers_all_approval_blockers": False,
                        "approval_coverage_note": (
                            "The selected approval phrase covers only the selected item gaps."
                        ),
                        "selected_item_id": "safe-ribbon-view-tab",
                        "preflight_guard_source": "handoff_artifact",
                        "approval_preflight_status": "fresh",
                        "preflight_fresh_now": True,
                        "required_human_approval_phrase_withheld": False,
                        "approval_preflight_command": ["north-star-approval-preflight"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star._completion_gate_next_human_action_summary(tmp_path)

    approval = result["option_summaries"][0]
    assert result["approval_coverage_status"] == "clean"
    assert result["approval_coverage_violation_count"] == 0
    assert approval["approval_coverage_fields_present"] is True
    assert approval["approval_blocker_gap_ids"] == [
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    ]
    assert approval["selected_item_gap_ids"] == [
        "live_uia_ribbon_context_execution",
    ]
    assert approval["remaining_approval_gap_ids_after_selected_item"] == [
        "live_ui_workflow_execution",
    ]
    assert approval["selected_item_covers_all_approval_blockers"] is False
    assert approval["approval_coverage_note_present"] is True
    assert approval["preflight_guard_source"] == "latest_preflight_artifact"
    assert approval["approval_preflight_status"] == "preflight_stale"
    assert approval["preflight_fresh_now"] is False
    assert approval["required_human_approval_phrase_withheld"] is True
    assert "must not be used" in approval["approval_phrase_safety_note"]


def test_completion_gate_waiting_summary_withholds_phrase_when_latest_preflight_stale(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": {
                    "generated_at_unix": 1,
                    "expires_at_unix": 2,
                    "expires_at_utc": "1970-01-01T00:00:02Z",
                    "ttl_seconds": 1,
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json").write_text(
        json.dumps(
                {
                    "read_only": True,
                    "generated_at_utc": "2026-05-14T00:00:00Z",
                    "status": "waiting_for_human_or_real_condition",
                "blocked_waiting_for_human_or_real_condition": True,
                "human_or_real_condition_required": True,
                "autonomous_progress_available": False,
                "next_approval_item_id": "safe-ribbon-view-tab",
                "next_approval_token": "APPROVE:abc123",
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:abc123"
                ),
                "preflight_freshness_guard": {
                    "status": "fresh",
                    "matched": True,
                    "expires_at_utc": "2999-01-01T00:00:00Z",
                    "remaining_seconds": 600,
                },
                "may_execute_from_waiting_state": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star._completion_gate_waiting_state_summary(tmp_path)

    assert result["available"] is True
    assert result["preflight_guard_source"] == "latest_preflight_artifact"
    assert result["preflight_fresh_now"] is False
    assert result["required_human_approval_phrase"] is None
    assert result["required_human_approval_phrase_withheld"] is True
    assert "not fresh" in result["withheld_required_human_approval_phrase_reason"]


def test_completion_gate_waiting_summary_preserves_withheld_without_phrase(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": {
                    "generated_at_unix": 1,
                    "expires_at_unix": 2,
                    "expires_at_utc": "1970-01-01T00:00:02Z",
                    "ttl_seconds": 1,
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json").write_text(
        json.dumps(
            {
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "status": "waiting_for_human_or_real_condition",
                "required_human_approval_phrase": None,
                "required_human_approval_phrase_withheld": True,
                "withheld_required_human_approval_phrase_reason": (
                    "Approval preflight is not fresh for this waiting-state handoff."
                ),
                "may_execute_from_waiting_state": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star._completion_gate_waiting_state_summary(tmp_path)

    assert result["required_human_approval_phrase"] is None
    assert result["required_human_approval_phrase_withheld"] is True
    assert result["withheld_required_human_approval_phrase_reason"] == (
        "Approval preflight is not fresh for this waiting-state handoff."
    )


def test_north_star_blocked_ledger_writes_current_gate_entries(tmp_path, monkeypatch):
    checklist = tmp_path / "revit_operator_runs" / "bridge-plan" / "bridge_restart_no_save_checklist.md"
    checklist.parent.mkdir(parents=True)
    checklist.write_text("no-save checklist", encoding="utf-8")
    endurance = tmp_path / "revit_operator_runs" / "supervision-audit" / "supervision_endurance_audit.json"
    endurance.parent.mkdir(parents=True)
    endurance.write_text(json.dumps({"target_met": True}), encoding="utf-8")
    preflight_json = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight_md = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    preflight_json.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "ready_for_human_approval_count": 1,
                "requires_state_change_count": 1,
                "requires_prevalidation_count": 0,
                "unsafe_preflight_count": 0,
                "items": [
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow approval is ready in test fixture.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Context target is not visible in test fixture.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    preflight_md.write_text("# preflight", encoding="utf-8")
    stale_unblock = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    stale_unblock_md = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
    stale_unblock.write_text(
        json.dumps(
            {
                "success": True,
                "read_only": True,
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_option_ids": ["stale-option"],
                "next_human_option_summaries": [{"id": "stale-option"}],
            }
        ),
        encoding="utf-8",
    )
    stale_unblock_md.write_text("# stale unblock readiness", encoding="utf-8")
    stale_time = preflight_json.stat().st_mtime - 30
    os.utime(stale_unblock, (stale_time, stale_time))
    os.utime(stale_unblock_md, (stale_time, stale_time))
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
            "failed_checks": ["loaded_build_current"],
        },
    )

    result = north_star.build_north_star_blocked_ledger(
        TaskJournal(tmp_path, "north-star-blocked-ledger-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["audit_completion_authorized"] is False
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] == (
        not north_star._completion_gate_allows_goal_update(result)
        and not result["autonomous_progress_available"]
        and result["human_or_real_condition_required"]
    )
    assert result["blocked_gap_count"] == result["entry_count"]
    assert result["blocked_gate_count"] == result["entry_count"]
    assert sorted(result["blocked_gap_ids"]) == sorted(entry["gap_id"] for entry in result["entries"])
    assert result["approval_preflight_readiness"]["available"] is True
    assert result["approval_preflight_readiness"]["ready_for_human_approval_count"] == 1
    assert {entry["gap_id"] for entry in result["entries"]} == {
        "bridge_restart_validation",
        "live_ui_workflow_execution",
        "live_recovery_drills",
        "live_uia_ribbon_context_execution",
    }
    bridge_entry = next(entry for entry in result["entries"] if entry["gap_id"] == "bridge_restart_validation")
    assert bridge_entry["failed_checks"] == ["loaded_build_current"]
    assert bridge_entry["manual_completion_step"]["id"] == "complete-bridge-restart-validation"
    workflow_entry = next(entry for entry in result["entries"] if entry["gap_id"] == "live_ui_workflow_execution")
    assert workflow_entry["approval_items"][0]["verify_command"][0] == "north-star-approval-verify"
    assert workflow_entry["approval_items"][0]["verify_powershell"].startswith("revit-operator north-star-approval-verify")
    assert workflow_entry["approval_items"][0]["phrase_verify_command"][0] == "north-star-approval-phrase-verify"
    assert workflow_entry["approval_items"][0]["phrase_verify_powershell"].startswith(
        "revit-operator north-star-approval-phrase-verify"
    )
    assert workflow_entry["approval_items"][0]["execution_preview_command"][0] == "north-star-approved-execution-preview"
    assert workflow_entry["approval_items"][0]["execution_preview_powershell"].startswith(
        "revit-operator north-star-approved-execution-preview"
    )
    assert "--execute" not in workflow_entry["approval_items"][0]["dry_run_command"]
    assert "--approval-tokens-json" not in workflow_entry["approval_items"][0]["dry_run_command"]
    assert workflow_entry["approval_items"][0]["dry_run_powershell"].startswith("revit-operator run-ui-workflow")
    assert workflow_entry["approval_items"][0]["execute_command"]
    assert workflow_entry["approval_items"][0]["execute_command"][0] == "run-ui-workflow"
    assert "--approval-tokens-json" in workflow_entry["approval_items"][0]["execute_powershell"]
    assert "'{\"3\":\"" in workflow_entry["approval_items"][0]["execute_powershell"]
    uia_entry = next(entry for entry in result["entries"] if entry["gap_id"] == "live_uia_ribbon_context_execution")
    context_item = next(
        item for item in uia_entry["approval_items"] if item["id"] == "context-menu-project-browser-target"
    )
    assert context_item["approval_ready_now"] is False
    assert context_item["approval_readiness"]["status"] == "requires_ui_state_change"
    assert context_item["execute_command"] == []
    assert context_item["withheld_execute_command"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown = Path(result["markdown_path"])
    assert markdown.is_relative_to(tmp_path)
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in markdown_text
    assert "blocked_gap_count:" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "autonomous_progress_available: `false`" in markdown_text
    assert "human_or_real_condition_required: `true`" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `true`" in markdown_text
    assert "Blocked Gap IDs" in markdown_text
    assert "bridge_restart_validation" in markdown_text
    assert "Approval Preflight Readiness" in markdown_text
    assert "north-star-approval-verify" in markdown_text
    assert "Dry run `approved-workflow-open-sheet` before approval" in markdown_text
    assert "Execute `approved-workflow-open-sheet` only after explicit approval" in markdown_text
    assert "Approval readiness `context-menu-project-browser-target`: `requires_ui_state_change`" in markdown_text
    assert "Execute `context-menu-project-browser-target` withheld" in markdown_text
    assert "Do not call update_goal" in markdown_text


def test_north_star_current_handoff_withholds_stale_approval_credentials_in_stable_files(
    tmp_path, monkeypatch
):
    checklist = tmp_path / "revit_operator_runs" / "bridge-plan" / "bridge_restart_no_save_checklist.md"
    checklist.parent.mkdir(parents=True)
    checklist.write_text("no-save checklist", encoding="utf-8")
    endurance = tmp_path / "revit_operator_runs" / "supervision-audit" / "supervision_endurance_audit.json"
    endurance.parent.mkdir(parents=True)
    endurance.write_text(json.dumps({"target_met": True}), encoding="utf-8")
    preflight_json = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight_md = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    preflight_json.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
                "ready_for_human_approval_count": 2,
                "requires_state_change_count": 0,
                "requires_prevalidation_count": 0,
                "unsafe_preflight_count": 0,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Was ready before the preflight expired.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Was ready before the preflight expired.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    preflight_md.write_text("# stale preflight", encoding="utf-8")
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({"approval_token": "APPROVE:legacy-json-leak"}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md").write_text(
        "Legacy token APPROVE:legacy-md-leak\n"
        "Execute only after explicit approval: `revit-operator ribbon-action --execute`\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
            "failed_checks": ["loaded_build_current"],
        },
    )

    result = north_star.build_north_star_current_handoff(
        TaskJournal(tmp_path, "north-star-current-handoff-stale-credentials-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    stable = result["stable_files"]
    approval_plan = json.loads(Path(stable["approval_plan"]).read_text(encoding="utf-8"))
    workflow = next(
        item for item in approval_plan["approval_items"] if item["id"] == "approved-workflow-open-sheet"
    )
    assert approval_plan["preflight_freshness_guard"]["status"] == "preflight_stale"
    assert workflow["approval_token"] is None
    assert workflow["approval_token_withheld"] is True
    assert workflow["required_human_approval_phrase"] is None
    assert workflow["required_human_approval_phrase_withheld"] is True
    assert workflow["command"] == []
    assert workflow["execute_powershell"] == ""
    assert "<withheld>" in workflow["withheld_execute_command"]
    assert "--execute" not in workflow["withheld_execute_command"]
    assert "--approval-token" not in workflow["withheld_execute_command"]
    assert workflow["approval_freshness"]["approval_token"] is None
    assert workflow["approval_freshness"]["verify_command"] == []
    assert workflow["approval_freshness"]["verify_command_withheld"] is True

    human_packet = json.loads(Path(stable["human_gate_packet"]).read_text(encoding="utf-8"))
    assert human_packet["blocked_gap_count"] == result["blocked_gap_count"]
    assert human_packet["blocked_gap_ids"] == result["blocked_gap_ids"]
    assert all(not item.get("required_human_approval_phrase") for item in human_packet["approval_items"])
    assert all(not item.get("execute_powershell") for item in human_packet["approval_items"])
    ledger = json.loads(Path(stable["ledger_json"]).read_text(encoding="utf-8"))
    for entry in ledger["entries"]:
        for item in entry.get("approval_items") or []:
            assert not item.get("required_human_approval_phrase")
            assert not item.get("execute_powershell")
    legacy_handoff = json.loads(Path(stable["legacy_blocked_handoff"]).read_text(encoding="utf-8"))
    assert legacy_handoff["deprecated"] is True
    assert legacy_handoff["redacted"] is True
    assert legacy_handoff["may_execute_from_this_result"] is False
    assert legacy_handoff["completion_allowed"] is False
    assert legacy_handoff["blocked_gap_count"] == result["blocked_gap_count"]
    legacy_handoff_markdown = Path(stable["legacy_blocked_handoff_markdown"]).read_text(
        encoding="utf-8"
    )
    assert "- audit_completion_authorized: `false`" in legacy_handoff_markdown

    for key in [
        "approval_plan_markdown",
        "human_gate_packet_markdown",
        "ledger_markdown",
        "legacy_blocked_handoff_markdown",
    ]:
        markdown_text = Path(stable[key]).read_text(encoding="utf-8")
        assert "Required human approval phrase:" not in markdown_text
        assert "Execute only after explicit approval" not in markdown_text
        assert "APPROVE:" not in markdown_text
        assert "withheld" in markdown_text.lower()

    for key in [
        "status_json",
        "status_markdown",
        "approval_plan",
        "approval_plan_markdown",
        "ready_approvals",
        "ready_approvals_markdown",
        "next_approval",
        "next_approval_markdown",
        "waiting_state",
        "waiting_state_markdown",
        "next_human_action",
        "next_human_action_markdown",
        "ledger_json",
        "ledger_markdown",
        "legacy_blocked_handoff",
        "legacy_blocked_handoff_markdown",
        "completion_gate",
        "completion_gate_markdown",
        "human_gate_packet",
        "human_gate_packet_markdown",
        "handoff_json",
        "handoff_markdown",
    ]:
        stable_text = Path(stable[key]).read_text(encoding="utf-8")
        assert "APPROVE:" not in stable_text
        assert "I approve " not in stable_text
        assert "--execute" not in stable_text
        assert "--approval-token" not in stable_text
        assert "Execute only after explicit approval" not in stable_text

    supervised_script = Path(stable["supervised_readonly_script"]).read_text(encoding="utf-8")
    assert "north-star-approval-preflight" in supervised_script
    assert "north-star-approval-phrase-verify" in supervised_script
    assert "north-star-approved-execution-preview" in supervised_script
    assert "north-star-completion-gate" in supervised_script
    assert "--phrase-source" in supervised_script
    assert "human_active_conversation" in supervised_script
    assert "$Gate.completion_allowed -eq $true" in supervised_script
    assert "do not call update_goal" in supervised_script
    assert "--execute" not in supervised_script
    assert "--approval-token" not in supervised_script


def test_north_star_current_handoff_publishes_stable_sandbox_files(tmp_path, monkeypatch):
    checklist = tmp_path / "revit_operator_runs" / "bridge-plan" / "bridge_restart_no_save_checklist.md"
    checklist.parent.mkdir(parents=True)
    checklist.write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge metadata.",
                "Failed bridge checks: `loaded_build_current`",
                "restart_or_reload_required: `True`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "",
                "Do not mark the north-star goal complete unless a fresh "
                "`north-star-completion-gate` or `north-star-resume-check.completion_gate` "
                "reports `completion_allowed: true`, `may_call_update_goal: true`, "
                "and `audit_completion_authorized: true`. Status and audit summaries "
                "are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )
    preflight_json = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight_md = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    preflight_json.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow ready in current handoff test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    preflight_md.write_text("# preflight", encoding="utf-8")
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
        },
    )

    result = north_star.build_north_star_current_handoff(
        TaskJournal(tmp_path, "north-star-current-handoff-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    stable = result["stable_files"]
    assert Path(stable["status_json"]) == tmp_path / "NORTH_STAR_STATUS_CURRENT.json"
    assert Path(stable["status_markdown"]) == tmp_path / "NORTH_STAR_STATUS_CURRENT.md"
    assert Path(stable["approval_plan"]) == tmp_path / "NORTH_STAR_APPROVAL_PLAN_CURRENT.json"
    assert Path(stable["approval_plan_markdown"]) == tmp_path / "NORTH_STAR_APPROVAL_PLAN_CURRENT.md"
    assert Path(stable["approval_preflight"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    assert Path(stable["approval_preflight_markdown"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    assert Path(stable["ready_approvals"]) == tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.json"
    assert (
        Path(stable["ready_approvals_markdown"])
        == tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md"
    )
    assert Path(stable["next_approval"]) == tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json"
    assert (
        Path(stable["next_approval_markdown"])
        == tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.md"
    )
    assert Path(stable["waiting_state"]) == tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json"
    assert (
        Path(stable["waiting_state_markdown"])
        == tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md"
    )
    assert Path(stable["next_human_action"]) == tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
    assert (
        Path(stable["next_human_action_markdown"])
        == tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md"
    )
    assert Path(stable["ledger_json"]) == tmp_path / "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json"
    assert Path(stable["ledger_markdown"]) == tmp_path / "NORTH_STAR_BLOCKED_LEDGER_CURRENT.md"
    assert (
        Path(stable["legacy_blocked_handoff"])
        == tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json"
    )
    assert (
        Path(stable["legacy_blocked_handoff_markdown"])
        == tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md"
    )
    assert Path(stable["audit_json"]) == tmp_path / "NORTH_STAR_AUDIT_CURRENT.json"
    assert Path(stable["audit_markdown"]) == tmp_path / "NORTH_STAR_AUDIT_CURRENT.md"
    assert Path(stable["completion_gate"]) == tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    assert (
        Path(stable["completion_gate_markdown"])
        == tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md"
    )
    assert (
        Path(stable["bridge_restart_no_save_checklist"])
        == tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    )
    assert Path(stable["human_gate_packet"]) == tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json"
    assert (
        Path(stable["human_gate_packet_markdown"])
        == tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md"
    )
    assert (
        Path(stable["post_human_resume_script"])
        == tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    )
    assert (
        Path(stable["supervised_readonly_script"])
        == tmp_path / "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1"
    )
    assert (
        Path(stable["unblock_readiness"])
        == tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    )
    assert (
        Path(stable["unblock_readiness_markdown"])
        == tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
    )
    assert Path(stable["handoff_json"]) == tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json"
    assert Path(stable["handoff_markdown"]) == tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md"
    for path in stable.values():
        assert Path(path).exists()
    assert "Bridge Restart / Reload No-Save Checklist" in Path(
        stable["bridge_restart_no_save_checklist"]
    ).read_text(encoding="utf-8")
    status_summary = json.loads(Path(stable["status_json"]).read_text(encoding="utf-8"))
    assert status_summary["blocked_gap_count"] == result["blocked_gap_count"]
    assert status_summary["blocked_gate_count"] == status_summary["blocked_gap_count"]
    assert status_summary["blocked_gap_ids"] == result["blocked_gap_ids"]
    assert status_summary["may_call_update_goal"] is False
    assert all(item["approval_token"] is None for item in status_summary["approval_candidates"])
    assert all(item["approval_token_withheld"] is True for item in status_summary["approval_candidates"])
    assert all("--execute" not in item["command"] for item in status_summary["approval_candidates"])
    assert all(
        "--approval-token" not in item["command"]
        for item in status_summary["approval_candidates"]
    )
    assert all(
        "--approval-tokens-json" not in item["command"]
        for item in status_summary["approval_candidates"]
    )
    status_markdown = Path(stable["status_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Status" in status_markdown
    assert "approval_token_withheld" in status_markdown
    assert "APPROVE:" not in status_markdown
    assert "--execute" not in status_markdown
    approval_plan = json.loads(Path(stable["approval_plan"]).read_text(encoding="utf-8"))
    assert approval_plan["approval_items"]
    stable_workflow = next(
        item for item in approval_plan["approval_items"] if item["id"] == "approved-workflow-open-sheet"
    )
    assert stable_workflow["dry_run_command"]
    assert "--approval-tokens-json" not in stable_workflow["dry_run_command"]
    approval_markdown = Path(stable["approval_plan_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Approval Plan" in approval_markdown
    assert "Dry run before approval" in approval_markdown
    assert "Execute only after explicit approval" in approval_markdown
    handoff = json.loads(Path(stable["handoff_json"]).read_text(encoding="utf-8"))
    ledger = json.loads(Path(stable["ledger_json"]).read_text(encoding="utf-8"))
    expected_blocked_gap_ids = [
        entry["gap_id"] for entry in ledger["entries"] if entry.get("gap_id")
    ]
    assert handoff["autonomous_progress_available"] is result["autonomous_progress_available"]
    assert handoff["completion_allowed"] is False
    assert handoff["may_call_update_goal"] is False
    assert handoff["audit_completion_authorized"] is False
    assert handoff["may_execute_from_this_result"] is False
    assert handoff["human_or_real_condition_required"] is result["human_or_real_condition_required"]
    assert handoff["blocked_waiting_for_human_or_real_condition"] == result[
        "blocked_waiting_for_human_or_real_condition"
    ]
    assert handoff["completion_actions"] == result["completion_actions"]
    assert handoff["blocked_gap_ids"] == expected_blocked_gap_ids

    assert handoff["blocked_gap_count"] == len(expected_blocked_gap_ids)
    assert handoff["blocked_gate_count"] == len(expected_blocked_gap_ids)
    assert handoff["waiting_state"] == result["waiting_state"]
    assert handoff["waiting_state"]["blocked_gap_ids"] == expected_blocked_gap_ids
    assert handoff["waiting_state"]["blocked_gap_count"] == len(expected_blocked_gap_ids)
    assert handoff["waiting_state"]["blocked_gate_count"] == len(expected_blocked_gap_ids)
    assert handoff["waiting_state"]["may_execute_from_waiting_state"] is False
    assert handoff["waiting_state"]["preflight_freshness_guard"]["status"] == "fresh"
    assert handoff["waiting_state"]["preflight_freshness_guard"]["matched"] is True
    assert handoff["waiting_state"]["required_human_approval_phrase"].startswith(
        "I approve approved-workflow-open-sheet with token APPROVE:"
    )
    assert handoff["waiting_state"]["required_human_approval_phrase_withheld"] is False
    assert handoff["waiting_state"]["approval_phrase_preflight_fresh_now"] is True
    assert handoff["waiting_state"]["approval_phrase_expires_at_utc"]
    assert "valid only while this preflight freshness guard is fresh" in handoff[
        "waiting_state"
    ]["approval_phrase_safety_note"]
    assert handoff["waiting_state"]["required_human_actions"]
    assert handoff["waiting_state"]["required_real_condition_actions"]
    assert handoff["stable_files"]["handoff_json"] == stable["handoff_json"]
    assert handoff["stable_files"]["handoff_markdown"] == stable["handoff_markdown"]
    assert handoff["source_artifacts"]["status_json"]
    assert handoff["source_artifacts"]["status_markdown"]
    assert handoff["source_artifacts"]["approval_plan"]
    assert handoff["source_artifacts"]["approval_plan_markdown"]
    assert handoff["source_artifacts"]["approval_preflight"]
    assert handoff["source_artifacts"]["approval_preflight_markdown"]
    assert handoff["source_artifacts"]["ready_approvals"]
    assert handoff["source_artifacts"]["ready_approvals_markdown"]
    assert handoff["source_artifacts"]["next_approval"]
    assert handoff["source_artifacts"]["next_approval_markdown"]
    assert handoff["source_artifacts"]["waiting_state"]
    assert handoff["source_artifacts"]["waiting_state_markdown"]
    assert handoff["source_artifacts"]["next_human_action"]
    assert handoff["source_artifacts"]["next_human_action_markdown"]
    assert handoff["source_artifacts"]["audit_json"]
    assert handoff["source_artifacts"]["audit_markdown"]
    assert handoff["source_artifacts"]["completion_gate_markdown"]
    assert handoff["source_artifacts"]["bridge_restart_no_save_checklist"] == str(checklist)
    assert handoff["source_artifacts"]["human_gate_packet"]
    assert handoff["source_artifacts"]["human_gate_packet_markdown"]
    assert handoff["source_artifacts"]["post_human_resume_script"]
    assert handoff["source_artifacts"]["supervised_readonly_script"]
    assert handoff["source_artifacts"]["unblock_readiness"]
    assert handoff["source_artifacts"]["unblock_readiness_markdown"]
    assert handoff["unblock_readiness_refreshed_after_handoff"]["status"] == "blocked"
    assert (
        handoff["unblock_readiness_refreshed_after_handoff"][
            "stable_handoff_guard_violation_count"
        ]
        == 0
    )
    assert (
        handoff["completion_gate_refreshed_after_unblock_readiness"][
            "safety_guard_violation_count"
        ]
        == 0
    )
    assert handoff["supervised_readonly_check"]["packet_available"] is True
    assert handoff["supervised_readonly_check"]["execution_command_included"] is False
    assert handoff["supervised_readonly_check"]["may_execute_from_this_packet"] is False
    assert handoff["next_human_action"]["status"] == "blocked_waiting_for_human_or_real_condition"
    assert handoff["next_human_action"]["audit_completion_authorized"] is False
    assert handoff["next_human_action"]["may_execute_from_this_result"] is False
    next_human_action = json.loads(Path(stable["next_human_action"]).read_text(encoding="utf-8"))
    assert next_human_action["may_execute_from_this_result"] is False
    assert next_human_action["next_human_options"]
    expected_option_ids = [
        item["id"] for item in next_human_action["next_human_options"] if item.get("id")
    ]
    assert handoff["next_human_action"]["option_ids"] == expected_option_ids
    assert [item["id"] for item in handoff["next_human_action"]["option_summaries"]] == expected_option_ids
    assert all(
        item["may_execute_from_this_option"] is False
        for item in handoff["next_human_action"]["option_summaries"]
    )
    assert handoff["next_human_action_summary"] == handoff["next_human_action"]
    assert handoff["next_human_restart_or_reload"]["id"] == "human-restart-or-reload-revit"
    assert handoff["next_human_restart_or_reload"]["post_action_resume_script"] == str(
        stable["post_human_resume_script"]
    )
    assert handoff["post_human_resume_script"] == str(stable["post_human_resume_script"])
    assert handoff["post_human_resume_command"] == handoff["next_human_restart_or_reload"][
        "post_action_resume_command"
    ]
    assert handoff["next_human_approval_summary"]["id"] == "provide-exact-human-approval-phrase"
    assert handoff["next_required_real_condition"]["id"] == "wait-for-real-recovery-condition"
    assert handoff["next_required_real_condition"]["may_execute_from_this_option"] is False
    assert handoff["agent_stop_status"]["completion_allowed"] is False
    assert handoff["agent_stop_status"]["may_call_update_goal"] is False
    assert handoff["agent_stop_status"]["audit_completion_authorized"] is False
    assert handoff["agent_stop_status"]["hard_gate_allows_completion"] is False
    assert handoff["agent_stop_status"]["approval_material_included"] is False
    assert handoff["agent_stop_status"]["approval_material_withheld"] is True
    next_human_markdown = Path(stable["next_human_action_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator Next Human Action" in next_human_markdown
    assert "provide-exact-human-approval-phrase" in next_human_markdown
    assert handoff["completion_gate_refreshed_after_supervised_script"]["status"] == "blocked"
    assert (
        handoff["completion_gate_refreshed_after_supervised_script"][
            "audit_completion_authorized"
        ]
        is False
    )
    assert (
        handoff["completion_gate_refreshed_after_supervised_script"][
            "supervised_script_hint_present"
        ]
        is True
    )
    completion_gate = json.loads(Path(stable["completion_gate"]).read_text(encoding="utf-8"))
    completion_hints = {item["id"]: item for item in completion_gate["stable_artifact_hints"]}
    assert completion_hints["supervised-readonly-script"]["present"] is True
    assert completion_hints["next-human-action"]["present"] is True
    ready_approvals = json.loads(Path(stable["ready_approvals"]).read_text(encoding="utf-8"))
    assert ready_approvals["ready_items"]
    assert all(item["execute_powershell"] for item in ready_approvals["ready_items"])
    ready_markdown = Path(stable["ready_approvals_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator Ready North-Star Approvals" in ready_markdown
    assert "Withheld Items" in ready_markdown
    unblock_readiness = json.loads(Path(stable["unblock_readiness"]).read_text(encoding="utf-8"))
    assert unblock_readiness["next_human_option_ids"] != ["stale-option"]
    assert (
        unblock_readiness["artifact_readiness"]["stable_handoff_guard_violation_count"]
        == 0
    )
    next_approval = json.loads(Path(stable["next_approval"]).read_text(encoding="utf-8"))
    assert next_approval["selected_item"]["id"] == "approved-workflow-open-sheet"
    assert next_approval["may_execute_from_this_result"] is False
    next_markdown = Path(stable["next_approval_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator Next North-Star Approval" in next_markdown
    assert "may_execute_from_this_result: `false`" in next_markdown
    handoff_markdown = Path(stable["handoff_markdown"]).read_text(encoding="utf-8")
    assert "completion_allowed: `false`" in handoff_markdown
    assert "may_call_update_goal: `false`" in handoff_markdown
    assert "audit_completion_authorized: `false`" in handoff_markdown
    assert "may_execute_from_this_result: `false`" in handoff_markdown
    assert "post_human_resume_script:" in handoff_markdown
    assert "Human Unblock Brief" in handoff_markdown
    assert "approval_material_included: `false`" in handoff_markdown
    assert "NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.md" in handoff_markdown
    assert "Agent Stop Status" in handoff_markdown
    assert "may_execute_from_this_result: `false`" in handoff_markdown
    assert "hard_gate_allows_completion: `false`" in handoff_markdown
    assert "approval_material_withheld: `true`" in handoff_markdown
    assert "NORTH_STAR_AGENT_STOP_STATUS_CURRENT.md" in handoff_markdown
    assert "Next Required Real Condition" in handoff_markdown
    agent_stop = json.loads(Path(stable["agent_stop_status"]).read_text(encoding="utf-8"))
    assert agent_stop["status"] == "autonomous_progress_available"
    assert agent_stop["should_stop_agent"] is False
    assert agent_stop["may_execute_from_this_result"] is False
    assert agent_stop["recommended_agent_action"] == "continue_with_read_only_safe_next_step"
    assert agent_stop["approval_material_included"] is False
    assert agent_stop["approval_material_withheld"] is True
    agent_stop_markdown = Path(stable["agent_stop_status_markdown"]).read_text(
        encoding="utf-8"
    )
    assert "Revit Operator Agent Stop Status" in agent_stop_markdown
    assert "APPROVE:" not in agent_stop_markdown
    assert "I approve " not in agent_stop_markdown
    waiting_state = json.loads(Path(stable["waiting_state"]).read_text(encoding="utf-8"))
    assert waiting_state["status"] == result["waiting_state"]["status"]
    assert waiting_state["may_execute_from_this_result"] is False
    assert waiting_state["may_execute_from_waiting_state"] is False
    assert waiting_state["blocked_gap_ids"] == expected_blocked_gap_ids
    assert waiting_state["blocked_gap_count"] == len(expected_blocked_gap_ids)
    assert waiting_state["blocked_gate_count"] == len(expected_blocked_gap_ids)
    assert waiting_state["preflight_freshness_guard"]["status"] == "fresh"
    assert waiting_state["preflight_freshness_guard"]["matched"] is True
    assert waiting_state["required_human_approval_phrase"].startswith(
        "I approve approved-workflow-open-sheet with token APPROVE:"
    )
    assert waiting_state["required_human_approval_phrase_withheld"] is False
    assert waiting_state["approval_phrase_preflight_fresh_now"] is True
    assert waiting_state["approval_phrase_expires_at_utc"]
    waiting_state_markdown = Path(stable["waiting_state_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Waiting State" in waiting_state_markdown
    assert "may_execute_from_waiting_state: `false`" in waiting_state_markdown
    assert "blocked_gap_count:" in waiting_state_markdown
    assert "Preflight Freshness Guard" in waiting_state_markdown
    assert "Approval Phrase Freshness" in waiting_state_markdown
    assert "phrase_withheld: `false`" in waiting_state_markdown
    assert "I approve approved-workflow-open-sheet with token APPROVE:" in waiting_state_markdown
    human_packet = json.loads(Path(stable["human_gate_packet"]).read_text(encoding="utf-8"))
    assert human_packet["status"] == "autonomous_progress_available"
    assert human_packet["autonomous_progress_available"] is True
    assert human_packet["blocked_waiting_for_human_or_real_condition"] is False
    assert "post_human_gate_resume_command" in human_packet
    assert "post_human_gate_resume_powershell" in human_packet
    human_packet_markdown = Path(stable["human_gate_packet_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator Human Gate Packet" in human_packet_markdown
    assert "After Human Action" in human_packet_markdown
    assert "--expected-title-contains" in human_packet_markdown
    resume_script = Path(stable["post_human_resume_script"]).read_text(encoding="utf-8")
    assert "Read-only post-human gate validation" in resume_script
    assert "must not save, sync, detach, upgrade, close, restart, or modify Revit" in resume_script
    assert "Push-Location -LiteralPath" in resume_script
    assert ".venv\\Scripts\\python.exe" in resume_script
    assert "venv\\Scripts\\python.exe" in resume_script
    assert "$ResumeArgs = @(" in resume_script
    assert "$RefreshArgs = @(" in resume_script
    assert "'-m'," in resume_script
    assert "'tools.revit_operator.cli'," in resume_script
    assert "'--sandbox'," in resume_script
    assert "'--task-id'," in resume_script
    assert "'post-human-resume-check-current'," in resume_script
    assert "'post-human-refresh-sequence-current'," in resume_script
    assert "'north-star-refresh-sequence'," in resume_script
    assert "'--expected-title-contains'," in resume_script
    assert "'24522 St John XXIII'," in resume_script
    assert "'--expected-view-name'," in resume_script
    assert "'STARTING VIEW'," in resume_script
    assert "$OutputText = & $Python @ResumeArgs" in resume_script
    assert "$RefreshOutputText = & $Python @RefreshArgs" in resume_script
    assert "$Result = $JsonText | ConvertFrom-Json -ErrorAction Stop" in resume_script
    assert "$RefreshResult = $RefreshJsonText | ConvertFrom-Json -ErrorAction Stop" in resume_script
    assert "$BridgeValidation = $Result.bridge_validation" in resume_script
    assert "BRIDGE VALIDATION: status=$($BridgeValidation.status)" in resume_script
    assert "failed_checks=$FailedBridgeChecks" in resume_script
    assert "SEQUENTIAL REFRESH: status=$($RefreshResult.status)" in resume_script
    assert "$Gate = $RefreshResult" in resume_script
    assert "NORTH STAR STILL BLOCKED: do not call update_goal." in resume_script
    assert "$Gate.audit_completion_authorized -eq $true" in resume_script
    assert "audit_completion_authorized=$($Gate.audit_completion_authorized)" in resume_script
    assert "COMPLETION GATE PASSED: completion_allowed" in resume_script
    assert "$Gate.blocked_gap_ids" in resume_script
    assert "blocked_gate_details" in resume_script
    assert "elseif ($_.id)" in resume_script
    assert "blocked_gates=$BlockedGates" in resume_script
    assert ",\n  )" not in resume_script
    supervised_script = Path(stable["supervised_readonly_script"]).read_text(encoding="utf-8")
    assert "Read-only supervised approval checker" in supervised_script
    assert "does not run the previewed execute command" in supervised_script
    assert "May execute from this packet: False" in supervised_script
    assert "expected approval phrase is not embedded" in supervised_script
    assert "[Parameter(Mandatory = $true)][string]$HumanApprovalPhrase" in supervised_script
    assert "$ExpectedHumanApprovalPhrase =" not in supervised_script
    assert "HumanApprovalPhrase does not match" not in supervised_script
    assert "APPROVE:" not in supervised_script
    assert "I approve " not in supervised_script
    assert "<HUMAN_APPROVAL_PHRASE>" in supervised_script
    assert "Resolve-HumanApprovalPhraseArgument" in supervised_script
    assert "$ApprovalPreflightArgs = @(" in supervised_script
    assert "$ApprovalPhraseVerifyArgs = @(" in supervised_script
    assert "$ApprovedExecutionPreviewArgs = @(" in supervised_script
    assert "$ResumeCheckArgs = @(" in supervised_script
    assert "$CompletionGateArgs = @(" in supervised_script
    assert "'north-star-approval-preflight'," in supervised_script
    assert "'north-star-approval-phrase-verify'," in supervised_script
    assert "'north-star-approved-execution-preview'," in supervised_script
    assert "'north-star-resume-check'," in supervised_script
    assert "'north-star-completion-gate'" in supervised_script
    assert "'--expected-title-contains'," in supervised_script
    assert "'24522 St John XXIII'," in supervised_script
    assert "'--phrase'," in supervised_script
    assert "'<HUMAN_APPROVAL_PHRASE>'" in supervised_script
    assert "execution_by_this_command" in supervised_script
    assert "may_execute_from_this_result" in supervised_script
    assert "Approval phrase was not validated for the current waiting state" in supervised_script
    assert "Approved execution preview is not ready" in supervised_script
    assert "NORTH STAR STILL BLOCKED: do not call update_goal." in supervised_script
    assert "$Gate.audit_completion_authorized -eq $true" in supervised_script
    assert "audit_completion_authorized=$($Gate.audit_completion_authorized)" in supervised_script
    assert "COMPLETION GATE PASSED: completion_allowed" in supervised_script
    handoff_markdown = Path(stable["handoff_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator Current North-Star Handoff" in handoff_markdown
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in handoff_markdown
    assert "NORTH_STAR_AUDIT_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_COMPLETION_GATE_CURRENT.json" in handoff_markdown
    assert "NORTH_STAR_COMPLETION_GATE_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_READY_APPROVALS_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_NEXT_APPROVAL_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_WAITING_STATE_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md" in handoff_markdown
    assert "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1" in handoff_markdown
    assert "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1" in handoff_markdown
    assert "-HumanApprovalPhrase" in handoff_markdown
    assert "autonomous_progress_available:" in handoff_markdown
    assert "human_or_real_condition_required:" in handoff_markdown
    assert "blocked_waiting_for_human_or_real_condition:" in handoff_markdown
    assert "blocked_gate_count:" in handoff_markdown
    assert "blocked_gap_count:" in handoff_markdown
    assert "Blocked Gap IDs" in handoff_markdown
    assert "Waiting State" in handoff_markdown
    assert "Next Human Action" in handoff_markdown
    assert "option_ids:" in handoff_markdown
    assert "provide-exact-human-approval-phrase" in handoff_markdown
    assert "may_execute_from_waiting_state: `false`" in handoff_markdown
    assert "approval_phrase_preflight_fresh_now:" in handoff_markdown
    assert "I approve approved-workflow-open-sheet with token APPROVE:" in handoff_markdown
    assert "human-readable completion gate" in handoff_markdown
    assert "machine-readable source before claiming completion" in handoff_markdown
    assert "supervised human-gate checklist" in handoff_markdown
    assert "before any Revit restart/reload gate" in handoff_markdown
    assert "After the human completes the required gate" in handoff_markdown
    assert "verify the current approval phrase and preview without executing" in handoff_markdown
    assert "only approval items latest preflight marks ready" in handoff_markdown
    assert "single next approval candidate" in handoff_markdown
    assert "Do not call update_goal" in handoff_markdown


def test_north_star_current_handoff_publishes_latest_restart_checklist_when_bridge_gap_cleared(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "revit_operator_runs" / "bridge-plan-current"
    source_dir.mkdir(parents=True)
    checklist = source_dir / "bridge_restart_no_save_checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Add-In Startup Prompt Preflight",
                "addin_security_status: `verified`",
                "expected_local_hermes_addin: `True`",
                "needs_trust_addin: `False`",
                "can_consider_always_load_after_human_approval: `True`",
                "allowed_dialog_button_after_human_approval: `Always Load`",
                "blocked_dialog_buttons: `Load Once`, `Do Not Load`",
                "signature_status: `Valid`",
                "signer_subject: `CN=Hermes Revit Operator Local Code Signing`",
                "Hermes must not click it from this checklist",
                "require an exact approval token before any `Always Load` click",
            ]
        ),
        encoding="utf-8",
    )
    (source_dir / "bridge_restart_validation_plan.json").write_text(
        json.dumps(
            {
                "status": "bridge_current",
                "no_save_checklist_path": str(checklist),
                "addin_security_preflight": {"status": "verified"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {"revit_version": "2025"},
                "ready_for_human_approval_count": 0,
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text(
        "# preflight", encoding="utf-8"
    )
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": True,
            "requires_revit_restart_or_reload": False,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
        },
    )

    result = north_star.build_north_star_current_handoff(
        TaskJournal(tmp_path, "north-star-current-handoff-cleared-bridge-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    stable_checklist = Path(result["stable_files"]["bridge_restart_no_save_checklist"])
    stable_text = stable_checklist.read_text(encoding="utf-8")
    assert stable_checklist == tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    assert "## Add-In Startup Prompt Preflight" in stable_text
    assert result["source_artifacts"]["bridge_restart_no_save_checklist"] == str(checklist)


def test_north_star_current_handoff_links_existing_safety_artifacts(
    tmp_path, monkeypatch
):
    checklist = tmp_path / "revit_operator_runs" / "bridge-plan" / "bridge_restart_no_save_checklist.md"
    checklist.parent.mkdir(parents=True)
    checklist.write_text("no-save checklist", encoding="utf-8")
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text(
        "# stale preflight",
        encoding="utf-8",
    )
    existing_safety_artifacts = {
        "stable_artifact_scan": (
            "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json",
            {
                "success": True,
                "read_only": True,
                "status": "clean",
                "violation_count": 0,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
            },
        ),
        "unblock_readiness": (
            "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json",
            {
                "success": True,
                "read_only": True,
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "blocked_gate_count": 4,
            },
        ),
    }
    for _, (filename, payload) in existing_safety_artifacts.items():
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.md").write_text(
        "# stable artifact scan",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md").write_text(
        "# unblock readiness",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
            "no_save_checklist_path": str(checklist),
            "no_save_checklist_present": True,
        },
    )

    result = north_star.build_north_star_current_handoff(
        TaskJournal(tmp_path, "north-star-current-handoff-safety-artifact-links-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    stable = result["stable_files"]
    expected_paths = {
        "stable_artifact_scan": tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json",
        "stable_artifact_scan_markdown": tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.md",
        "unblock_readiness": tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json",
        "unblock_readiness_markdown": tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md",
    }
    for key, expected in expected_paths.items():
        assert Path(stable[key]) == expected
        assert expected.exists()
        assert result["source_artifacts"][key] == str(expected)

    handoff = json.loads(Path(stable["handoff_json"]).read_text(encoding="utf-8"))
    for key, expected in expected_paths.items():
        assert Path(handoff["stable_files"][key]) == expected
        assert handoff["source_artifacts"][key] == str(expected)


def test_cli_north_star_audit_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-audit-cli-test",
            "north-star-audit",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["north_star_complete"] is False
    assert output["completion_allowed"] is False
    assert output["remaining_gaps"]
    assert output["blocked_gap_count"] == output["blocker_summary"]["blocked_gap_count"]
    assert output["blocked_gate_count"] == output["blocked_gap_count"]
    assert output["blocked_gap_ids"] == output["blocker_summary"]["blocked_gap_ids"]
    assert output["cleared_gap_count"] == output["blocker_summary"]["cleared_gap_count"]
    assert output["cleared_gap_ids"] == output["blocker_summary"]["cleared_gap_ids"]
    assert output["may_call_update_goal"] is False
    assert output["completion_gate_required"] is True
    assert output["completion_gate_command"] == ["north-star-completion-gate"]
    assert output["blocker_summary"]["completion_blocked"] is True
    assert output["completion_actions"]["may_call_update_goal"] is False
    assert Path(output["path"]).exists()
    assert Path(output["markdown_path"]).exists()
    audit_markdown = Path(output["markdown_path"]).read_text(encoding="utf-8")
    assert "Prompt To Artifact Checklist" in audit_markdown
    assert "completion_allowed: `false`" in audit_markdown


def test_north_star_refresh_sequence_runs_steps_in_order_and_preserves_child_artifacts(
    tmp_path, monkeypatch
):
    events = []
    captured = {}
    gate_calls = []

    def write_artifacts(journal, stem, title):
        path = journal.run_dir / f"{stem}.json"
        markdown = journal.run_dir / f"{stem}.md"
        path.write_text(json.dumps({"title": title}), encoding="utf-8")
        markdown.write_text(f"# {title}", encoding="utf-8")
        return path, markdown

    def fake_handoff(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        events.append("current-handoff")
        captured.update(
            {
                "repo_root": repo_root,
                "command_names": command_names,
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            }
        )
        path, markdown = write_artifacts(journal, "north_star_current_handoff", "handoff")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    def fake_stable_scan(journal):
        events.append("stable-artifact-scan")
        path, markdown = write_artifacts(
            journal,
            "north_star_stable_artifact_scan",
            "stable scan",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "clean",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "may_execute_from_this_result": False,
            "violation_count": 0,
            "path": str(path),
            "markdown_path": str(markdown),
            "stable_path": str(tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"),
            "stable_markdown_path": str(
                tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.md"
            ),
        }

    def fake_completion_gate(journal, *, repo_root, command_names):
        events.append("completion-gate")
        gate_calls.append((repo_root, command_names))
        path, markdown = write_artifacts(
            journal,
            "north_star_completion_gate",
            "completion gate",
        )
        final = len(gate_calls) == 2
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "blocked_reasons": ["fresh audit reports north_star_complete is not true"],
            "blocked_gap_ids": ["bridge_restart_validation", "live_ui_workflow_execution"]
            if final
            else ["bridge_restart_validation"],
            "blocked_gap_count": 2 if final else 1,
            "blocked_gate_count": 2 if final else 1,
            "unsatisfied_count": 17 if final else 3,
            "autonomous_progress_available": False,
            "human_or_real_condition_required": True,
            "blocked_waiting_for_human_or_real_condition": True,
            "safety_guard_violation_count": 0,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(north_star, "build_north_star_current_handoff", fake_handoff)
    monkeypatch.setattr(north_star, "build_north_star_stable_artifact_scan", fake_stable_scan)
    monkeypatch.setattr(north_star, "build_north_star_completion_gate", fake_completion_gate)

    result = north_star.build_north_star_refresh_sequence(
        TaskJournal(tmp_path, "north-star-refresh-sequence-test"),
        repo_root=Path.cwd(),
        command_names=["north-star-current-handoff", "north-star-completion-gate"],
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_path_contains="Structural_Current Working-R25-BIM",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert events == [
        "current-handoff",
        "stable-artifact-scan",
        "completion-gate",
        "stable-artifact-scan",
        "completion-gate",
    ]
    assert result["sequence_order"] == [
        "north-star-current-handoff",
        "north-star-stable-artifact-scan",
        "north-star-completion-gate",
        "north-star-stable-artifact-scan",
        "north-star-completion-gate",
    ]
    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["blocked_gap_ids"] == [
        "bridge_restart_validation",
        "live_ui_workflow_execution",
    ]
    assert result["blocked_gap_count"] == 2
    assert result["blocked_gate_count"] == 2
    assert result["unsatisfied_count"] == 17
    assert result["safety_guard_violation_count"] == 0
    assert result["child_task_ids"] == [
        "north-star-refresh-sequence-test-01-current-handoff",
        "north-star-refresh-sequence-test-02-stable-artifact-scan",
        "north-star-refresh-sequence-test-03-completion-gate",
        "north-star-refresh-sequence-test-04-final-stable-artifact-scan",
        "north-star-refresh-sequence-test-05-final-completion-gate",
    ]
    assert captured["default_sheet_number"] == "S2.0"
    assert captured["revit_version"] == "2025"
    assert captured["expected_title_contains"] == "24522 St John XXIII"
    assert captured["expected_path_contains"] == "Structural_Current Working-R25-BIM"
    assert captured["expected_view_name"] == "STARTING VIEW"
    assert captured["expected_view_type"] == "DrawingSheet"
    assert all(Path(step["path"]).is_relative_to(tmp_path) for step in result["steps"])
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    assert Path(result["path"]).exists()
    assert "north-star-completion-gate" in Path(result["markdown_path"]).read_text(
        encoding="utf-8"
    )
    journal_lines = (
        tmp_path
        / "revit_operator_runs"
        / "north-star-refresh-sequence-test"
        / "journal.jsonl"
    ).read_text(encoding="utf-8")
    assert "north-star-refresh-sequence" in journal_lines


def test_north_star_completion_gate_blocks_when_fresh_audit_has_gaps(tmp_path):
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json").write_text(
        json.dumps(
            {
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "status": "waiting_for_human_or_real_condition",
                "blocked_waiting_for_human_or_real_condition": True,
                "human_or_real_condition_required": True,
                "autonomous_progress_available": False,
                "next_approval_item_id": "safe-ribbon-view-tab",
                "next_approval_gap_ids": ["live_uia_ribbon_context_execution"],
                "next_approval_token": "APPROVE:1034e0c7e0e97b4f",
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:1034e0c7e0e97b4f"
                ),
                "approval_phrase_expires_at_utc": "2099-01-01T00:00:00Z",
                "approval_phrase_execution_authority": False,
                "artifact_phrase_is_not_approval_provenance": True,
                "approval_phrase_provenance_note": (
                    "Generated artifacts may display the exact phrase for the human to read, "
                    "but they are not approval provenance or execution authority."
                ),
                "may_execute_from_this_result": False,
                "may_execute_from_waiting_state": False,
                "resume_script": str(tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Waiting State",
                "",
                "- status: `waiting_for_human_or_real_condition`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Required Human Approval Phrase",
                "- next_approval_item_id: `safe-ribbon-view-tab`",
                "- next_approval_gap_ids: `live_uia_ribbon_context_execution`",
                "Required human approval phrase: `I approve safe-ribbon-view-tab with token APPROVE:1034e0c7e0e97b4f`",
                "",
                "## Approval Phrase Freshness",
                "- expires_at_utc: `2099-01-01T00:00:00Z`",
                "- approval_phrase_execution_authority: `false`",
                "- artifact_phrase_is_not_approval_provenance: `true`",
                (
                    "- note: generated artifacts may display the exact phrase for the human "
                    "to read, but they are not approval provenance or execution authority."
                ),
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "approval_ready",
                "ready_approval_count": 3,
                "withheld_approval_count": 2,
                "may_execute_from_this_result": False,
                "selected_item": {
                    "id": "safe-ribbon-view-tab",
                    "gap_ids": ["live_uia_ribbon_context_execution"],
                    "approval_token": "APPROVE:1034e0c7e0e97b4f",
                    "expected_effect": "Select the Revit View ribbon tab only.",
                    "verify_command": [
                        "north-star-approval-verify",
                        "--approval-token",
                        "APPROVE:1034e0c7e0e97b4f",
                    ],
                    "dry_run_command": ["ribbon-action", "--name", "view-tab", "--limit", "50"],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next North-Star Approval",
                "",
                "- may_execute_from_this_result: `false`",
                "",
                "## Selected Item",
                "- `safe-ribbon-view-tab`: Select the Revit View ribbon tab only.",
                "  gap_ids: `live_uia_ribbon_context_execution`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                        "checklist_path": str(
                            tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
                        ),
                        "post_action_resume_command": [
                            "north-star-resume-check",
                            "--sheet-number",
                            "S2.0",
                            "--revit-version",
                            "2025",
                            "--expected-title-contains",
                            "24522 St John XXIII",
                            "--expected-view-name",
                            "STARTING VIEW",
                            "--expected-view-type",
                            "DrawingSheet",
                        ],
                        "post_action_resume_powershell": (
                            "revit-operator north-star-resume-check "
                            "--sheet-number S2.0 --revit-version 2025 "
                            "--expected-title-contains '24522 St John XXIII' "
                            "--expected-view-name 'STARTING VIEW' "
                            "--expected-view-type DrawingSheet"
                        ),
                        "dirty_state_warning": "Dirty copied model.",
                        "restart_context": {
                            "title": "24522 detached",
                            "dirty": True,
                            "active_view_name": "STARTING VIEW",
                            "active_view_type": "DrawingSheet",
                        },
                    },
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "may_execute_from_this_option": False,
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [
                            "live_ui_workflow_execution",
                        ],
                        "selected_item_covers_all_approval_blockers": False,
                        "approval_coverage_note": (
                            "The selected approval phrase covers only the selected item gaps; "
                            "remaining approval blockers require their own fresh preflight and "
                            "exact human approval phrase."
                        ),
                        "selected_item_id": "safe-ribbon-view-tab",
                        "preflight_guard_source": "latest_preflight_artifact",
                        "approval_preflight_status": "preflight_stale",
                        "preflight_fresh_now": False,
                        "required_human_approval_phrase_withheld": True,
                        "approval_preflight_command": ["north-star-approval-preflight"],
                        "approval_preflight_expires_at_utc": "2026-05-13T13:12:00Z",
                        "approval_phrase_safety_note": "Approval phrase must not be used.",
                    },
                    {
                        "id": "wait-for-real-recovery-condition",
                        "kind": "real_condition",
                        "may_execute_from_this_option": False,
                        "safe_observation_commands": ["recovery-snapshot"],
                    },
                ],
                "option_summaries": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                        "post_action_resume_command": [
                            "north-star-resume-check",
                            "--sheet-number",
                            "S2.0",
                            "--revit-version",
                            "2025",
                            "--expected-title-contains",
                            "24522 St John XXIII",
                            "--expected-view-name",
                            "STARTING VIEW",
                            "--expected-view-type",
                            "DrawingSheet",
                        ],
                        "post_action_resume_powershell": (
                            "revit-operator north-star-resume-check "
                            "--sheet-number S2.0 --revit-version 2025 "
                            "--expected-title-contains '24522 St John XXIII' "
                            "--expected-view-name 'STARTING VIEW' "
                            "--expected-view-type DrawingSheet"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                    "- may_call_update_goal: `false`",
                    "- audit_completion_authorized: `false`",
                    "- may_execute_from_this_result: `false`",
                    (
                        "  Resume command: `revit-operator north-star-resume-check "
                        "--sheet-number S2.0 --revit-version 2025 "
                        "--expected-title-contains '24522 St John XXIII' "
                        "--expected-view-name 'STARTING VIEW' "
                        "--expected-view-type DrawingSheet`"
                    ),
                    f"  Checklist: `{tmp_path / 'NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md'}`",
                    "  approval_blocker_gap_ids: `live_ui_workflow_execution, live_uia_ribbon_context_execution`",
                    "  selected_item_gap_ids: `live_uia_ribbon_context_execution`",
                    "  remaining_approval_gap_ids_after_selected_item: `live_ui_workflow_execution`",
                    "  selected_item_covers_all_approval_blockers: `false`",
                    "  approval_coverage_fields_present: `true`",
                ]
            ),
            encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "Do not mark the north-star goal complete unless a fresh "
                "`north-star-completion-gate` or `north-star-resume-check.completion_gate` "
                "reports `completion_allowed: true`, `may_call_update_goal: true`, "
                "and `audit_completion_authorized: true`. Status and audit summaries "
                "are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "approval_preflight_freshness": _test_preflight_freshness(),
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["unsatisfied_count"] > 0
    assert result["blocked_gap_count"] == len(result["blocked_gate_details"])
    assert result["blocked_gate_count"] == len(result["blocked_gate_details"])
    assert result["blocked_gap_count"] == result["blocked_gate_count"]
    assert result["blocked_gate_count"] >= 1
    assert result["completion_actions"]["may_call_update_goal"] is False
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] == (
        not result["completion_allowed"]
        and not result["autonomous_progress_available"]
        and result["human_or_real_condition_required"]
    )
    assert result["safety_guard_violation_count"] == 0
    assert result["autonomous_actions"] == result["completion_actions"]["autonomous_actions"]
    assert result["human_actions"] == result["completion_actions"]["human_actions"]
    assert result["real_condition_actions"] == result["completion_actions"]["real_condition_actions"]
    assert result["completion_audit_summary"]["objective_restatement"]
    assert result["completion_audit_summary"][
        "prompt_to_artifact_checklist_total_count"
    ] >= result["completion_audit_summary"]["prompt_to_artifact_checklist_satisfied_count"]
    assert (
        result["completion_audit_summary"][
            "prompt_to_artifact_checklist_unsatisfied_count"
        ]
        == result["completion_audit_summary"]["unverified_or_blocked_requirement_count"]
    )
    assert result["completion_audit_summary"]["blocked_gap_count"] == result["blocked_gap_count"]
    assert result["completion_audit_summary"]["blocked_gate_count"] == result["blocked_gate_count"]
    assert result["completion_audit_summary"]["autonomous_progress_available"] is result[
        "autonomous_progress_available"
    ]
    assert result["completion_audit_summary"]["human_or_real_condition_required"] is result[
        "human_or_real_condition_required"
    ]
    assert result["completion_audit_summary"]["safety_guard_violation_count"] == 0
    assert result["completion_audit_summary"]["autonomous_action_count"] == len(
        result["autonomous_actions"]
    )
    assert result["completion_audit_summary"]["human_action_count"] == len(result["human_actions"])
    assert result["completion_audit_summary"]["real_condition_action_count"] == len(
        result["real_condition_actions"]
    )
    unsatisfied = {item["id"]: item for item in result["unsatisfied_requirement_summaries"]}
    assert "gate:bridge_restart_validation" in unsatisfied
    assert unsatisfied["gate:bridge_restart_validation"]["blocker_type"] == "human_action_required"
    assert "human_action_required gate is still open" in unsatisfied[
        "gate:bridge_restart_validation"
    ]["reason"]
    assert "Human must safely restart or reload Revit" in unsatisfied[
        "gate:bridge_restart_validation"
    ]["reason"]
    assert "requirement:core-human-style-ui-operation" in unsatisfied
    assert "live_ui_workflow_execution" in unsatisfied[
        "requirement:core-human-style-ui-operation"
    ]["blocked_gaps"]
    assert unsatisfied["requirement:core-human-style-ui-operation"][
        "blocked_by_gap_ids"
    ] == unsatisfied["requirement:core-human-style-ui-operation"]["blocked_gaps"]
    assert "Blocked by unresolved north-star gap(s)" in unsatisfied[
        "requirement:core-human-style-ui-operation"
    ]["reason"]
    assert "live_ui_workflow_execution" in unsatisfied[
        "requirement:core-human-style-ui-operation"
    ]["reason"]
    details = {item["id"]: item for item in result["blocked_gate_details"]}
    assert "bridge_restart_validation" in details
    assert details["bridge_restart_validation"]["blocker_type"] == "human_action_required"
    assert "Human must safely restart or reload Revit" in details["bridge_restart_validation"]["next_step"]
    followups = {item["gap_id"]: item for item in result["followup_actions"]}
    assert "bridge_restart_validation" in followups
    assert "north-star-completion-gate" in followups["bridge_restart_validation"]["commands"]
    assert "live_ui_workflow_execution" in followups
    assert "north-star-approval-phrase-verify" in followups["live_ui_workflow_execution"]["commands"]
    assert "north-star-approved-execution-preview" in followups["live_ui_workflow_execution"]["commands"]
    assert "Do not reuse stale approval tokens" in followups["live_ui_workflow_execution"]["freshness_rule"]
    assert result["waiting_state_summary"]["available"] is True
    assert result["waiting_state_summary"]["next_approval_item_id"] == "safe-ribbon-view-tab"
    assert (
        result["waiting_state_summary"]["required_human_approval_phrase"]
        == "I approve safe-ribbon-view-tab with token APPROVE:1034e0c7e0e97b4f"
    )
    assert result["waiting_state_summary"]["may_execute_from_waiting_state"] is False
    assert result["next_approval_summary"]["available"] is True
    assert result["next_approval_summary"]["selected_item_id"] == "safe-ribbon-view-tab"
    assert result["next_approval_summary"]["may_execute_from_this_result"] is False
    assert result["next_human_action_summary"]["available"] is True
    assert result["next_human_action_summary"]["status"] == "blocked_waiting_for_human_or_real_condition"
    assert result["next_human_action_summary"]["may_execute_from_this_result"] is False
    assert result["next_human_action_summary"]["execution_authority_violation"] is False
    assert result["next_human_action_summary"]["option_ids"] == [
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
        "wait-for-real-recovery-condition",
    ]
    option_summaries = {
        item["id"]: item for item in result["next_human_action_summary"]["option_summaries"]
    }
    assert option_summaries["human-restart-or-reload-revit"]["dirty"] is True
    assert option_summaries["human-restart-or-reload-revit"]["title"] == "24522 detached"
    assert (
        option_summaries["human-restart-or-reload-revit"]["dirty_state_warning_present"]
        is True
    )
    assert option_summaries["human-restart-or-reload-revit"][
        "post_action_resume_command_present"
    ] is True
    assert option_summaries["human-restart-or-reload-revit"][
        "post_action_resume_command"
    ][0] == "north-star-resume-check"
    assert "north-star-resume-check" in option_summaries[
        "human-restart-or-reload-revit"
    ]["post_action_resume_powershell"]
    assert "--execute" not in option_summaries["human-restart-or-reload-revit"][
        "post_action_resume_powershell"
    ]
    assert "--approval-token" not in option_summaries["human-restart-or-reload-revit"][
        "post_action_resume_powershell"
    ]
    assert (
        option_summaries["provide-exact-human-approval-phrase"][
            "approval_preflight_status"
        ]
        == "fresh"
    )
    assert option_summaries["provide-exact-human-approval-phrase"]["preflight_fresh_now"] is True
    assert result["next_human_action_summary"]["approval_coverage_status"] == "clean"
    assert result["next_human_action_summary"]["approval_coverage_violation_count"] == 0
    assert (
        option_summaries["provide-exact-human-approval-phrase"][
            "approval_coverage_fields_present"
        ]
        is True
    )
    assert option_summaries["provide-exact-human-approval-phrase"][
        "approval_blocker_gap_ids"
    ] == [
        "live_ui_workflow_execution",
        "live_uia_ribbon_context_execution",
    ]
    assert option_summaries["provide-exact-human-approval-phrase"][
        "selected_item_gap_ids"
    ] == ["live_uia_ribbon_context_execution"]
    assert option_summaries["provide-exact-human-approval-phrase"][
        "remaining_approval_gap_ids_after_selected_item"
    ] == ["live_ui_workflow_execution"]
    assert (
        option_summaries["provide-exact-human-approval-phrase"][
            "selected_item_covers_all_approval_blockers"
        ]
        is False
    )
    assert (
        option_summaries["provide-exact-human-approval-phrase"][
            "required_human_approval_phrase_withheld"
        ]
        is False
    )
    assert (
        option_summaries["provide-exact-human-approval-phrase"][
            "approval_preflight_command_present"
        ]
        is True
    )
    assert result["safety_guard_violations"] == []
    assert result["safety_guard_followup_actions"] == []
    gate_markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "approval_preflight_status: `fresh`" in gate_markdown
    assert "approval_coverage_status: `clean`" in gate_markdown
    assert "approval_coverage_violation_count: `0`" in gate_markdown
    assert (
        "approval_blocker_gap_ids: "
        "`live_ui_workflow_execution, live_uia_ribbon_context_execution`"
        in gate_markdown
    )
    assert "selected_item_gap_ids: `live_uia_ribbon_context_execution`" in gate_markdown
    assert (
        "remaining_approval_gap_ids_after_selected_item: "
        "`live_ui_workflow_execution`"
        in gate_markdown
    )
    assert "selected_item_covers_all_approval_blockers: `false`" in gate_markdown
    assert "approval_coverage_fields_present: `true`" in gate_markdown
    assert "required_human_approval_phrase_withheld: `false`" in gate_markdown
    assert "approval_preflight_command_present: `true`" in gate_markdown
    assert "approval_phrase_expires_at_utc:" in gate_markdown
    assert "approval_phrase_execution_authority: `false`" in gate_markdown
    assert "safety_guard_violation_count: `0`" in gate_markdown
    assert "Count: `0`" in gate_markdown
    assert "Approval phrase expires at:" in gate_markdown
    assert "Approval phrase execution authority: `false`" in gate_markdown
    assert "Run the read-only preflight immediately before phrase verification" in gate_markdown
    assert "dirty: `true`" in gate_markdown
    assert "Latest approval preflight is fresh" in gate_markdown
    packet = result["supervised_command_packet"]
    assert packet["available"] is True
    assert packet["selected_item_id"] == "safe-ribbon-view-tab"
    assert packet["required_human_approval_phrase"] == (
        "I approve safe-ribbon-view-tab with token APPROVE:1034e0c7e0e97b4f"
    )
    assert packet["execution_command_included"] is False
    assert packet["may_execute_from_this_packet"] is False
    assert packet["phrase_must_be_supplied_by_human"] is True
    assert packet["auto_supplied_phrase_in_commands"] is False
    assert packet["human_phrase_placeholder"] == "<HUMAN_APPROVAL_PHRASE>"
    assert packet["approval_phrase_expires_at_utc"]
    assert packet["approval_preflight_remaining_seconds"] is not None
    assert packet["expected_context"]["expected_title_contains"] == "24522 St John XXIII"
    assert packet["read_only_commands"]["approval_preflight"] == [
        "north-star-approval-preflight",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-view-name",
        "STARTING VIEW",
        "--expected-view-type",
        "DrawingSheet",
    ]
    assert packet["read_only_commands"]["approval_phrase_verify"][-4:] == [
        "--phrase",
        "<HUMAN_APPROVAL_PHRASE>",
        "--phrase-source",
        "human_active_conversation",
    ]
    assert packet["read_only_commands"]["approved_execution_preview"][-4:] == [
        "--phrase",
        "<HUMAN_APPROVAL_PHRASE>",
        "--phrase-source",
        "human_active_conversation",
    ]
    assert "north-star-approved-execution-preview" in packet["read_only_powershell"][
        "approved_execution_preview"
    ]
    hints = {item["id"]: item for item in result["stable_artifact_hints"]}
    assert hints["human-gate-packet"]["filename"] == "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md"
    assert hints["completion-gate"]["filename"] == "NORTH_STAR_COMPLETION_GATE_CURRENT.md"
    assert hints["ready-approvals"]["filename"] == "NORTH_STAR_READY_APPROVALS_CURRENT.md"
    assert hints["next-approval"]["filename"] == "NORTH_STAR_NEXT_APPROVAL_CURRENT.md"
    assert hints["waiting-state"]["filename"] == "NORTH_STAR_WAITING_STATE_CURRENT.md"
    assert hints["post-human-resume-script"]["filename"] == "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    assert hints["supervised-readonly-script"]["filename"] == "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1"
    assert hints["completion-gate"]["present"] is True
    assert hints["audit-checklist"]["present"] is True
    assert "fresh audit has unverified_or_blocked_requirements" in result["blocked_reasons"]
    assert Path(result["audit_path"]).exists()
    assert Path(result["audit_markdown_path"]).exists()
    assert Path(result["path"]).exists()
    stable_current = result["stable_current_files"]
    assert stable_current["success"] is True
    assert Path(stable_current["files"]["completion_gate"]) == (
        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    )
    assert Path(stable_current["files"]["completion_gate_markdown"]) == (
        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md"
    )
    assert Path(stable_current["files"]["audit_json"]) == (
        tmp_path / "NORTH_STAR_AUDIT_CURRENT.json"
    )
    assert Path(stable_current["files"]["audit_markdown"]) == (
        tmp_path / "NORTH_STAR_AUDIT_CURRENT.md"
    )
    stable_gate = json.loads(
        Path(stable_current["files"]["completion_gate"]).read_text(encoding="utf-8")
    )
    assert stable_gate["path"] == result["path"]
    assert stable_gate["safety_guard_violation_count"] == 0
    assert stable_gate["stable_current_files"]["files"]["completion_gate"] == str(
        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    )
    markdown = Path(result["markdown_path"])
    assert markdown.exists()
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "Revit Operator North-Star Completion Gate" in markdown_text
    assert "completion_allowed: `false`" in markdown_text
    assert "blocked_gap_count:" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "autonomous_progress_available:" in markdown_text
    assert "human_or_real_condition_required:" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition:" in markdown_text
    assert "Completion Audit Summary" in markdown_text
    assert "prompt_to_artifact_checklist_unsatisfied_count" in markdown_text
    assert "autonomous_action_count" in markdown_text
    assert "human_action_count" in markdown_text
    assert "real_condition_action_count" in markdown_text
    assert "Unsatisfied Requirement Summaries" in markdown_text
    assert "gate:bridge_restart_validation" in markdown_text
    assert "Reason:" in markdown_text
    assert "Blocked by unresolved north-star gap(s)" in markdown_text
    assert "requirement:core-human-style-ui-operation" in markdown_text
    assert "Blocked Gate Details" in markdown_text
    assert "Follow-Up Actions" in markdown_text
    assert "Stable Artifacts To Open" in markdown_text
    assert "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md" in markdown_text
    assert "Current Waiting State" in markdown_text
    assert "I approve safe-ribbon-view-tab with token APPROVE:1034e0c7e0e97b4f" in markdown_text
    assert "Current Next Approval" in markdown_text
    assert "Current Next Human Action" in markdown_text
    assert "provide-exact-human-approval-phrase" in markdown_text
    assert "Supervised Read-Only Command Packet" in markdown_text
    assert "Safety Guard Violations" in markdown_text
    assert "north-star-approved-execution-preview" in markdown_text
    assert "bridge_restart_validation" in markdown_text
    assert "Human must safely restart or reload Revit" in markdown_text
    assert "Do not reuse stale approval tokens" in markdown_text
    assert "Only call update_goal" in markdown_text


def test_north_star_completion_gate_allows_only_clean_fresh_audit(tmp_path, monkeypatch):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        markdown_path = journal.run_dir / "north_star_audit.md"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        markdown_path.write_text("# Clean audit\n", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
            "markdown_path": str(markdown_path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-clean-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["status"] == "ready_to_complete"
    assert result["completion_allowed"] is True
    assert result["may_call_update_goal"] is True
    assert result["audit_completion_authorized"] is True
    assert result["safety_guard_violation_count"] == 0
    assert result["completion_audit_summary"]["safety_guard_violation_count"] == 0
    assert result["blocked_reasons"] == []
    assert result["blocked_gap_count"] == 0
    assert result["blocked_gate_count"] == 0
    assert result["completion_audit_summary"]["blocked_gap_count"] == 0
    assert result["completion_audit_summary"]["blocked_gate_count"] == 0
    assert result["completion_audit_summary"]["audit_completion_authorized"] is True
    assert result["completion_audit_summary"][
        "prompt_to_artifact_checklist_required_missing_count"
    ] == 0
    assert result["completion_audit_summary"][
        "prompt_to_artifact_checklist_required_count"
    ] == result["completion_audit_summary"][
        "prompt_to_artifact_checklist_required_present_count"
    ]
    assert result["unsatisfied_requirement_summaries"] == []
    assert Path(result["markdown_path"]).exists()
    assert Path(result["stable_current_files"]["files"]["completion_gate"]).exists()
    hints = {item["id"]: item for item in result["stable_artifact_hints"]}
    assert hints["completion-gate"]["present"] is True
    assert hints["audit-checklist"]["present"] is True


def test_north_star_completion_gate_blocks_complete_audit_without_update_goal_authority(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = {
            **_complete_audit_completion_actions(),
            "may_call_update_goal": False,
        }
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-audit-authority-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["completion_audit_summary"]["audit_completion_authorized"] is False
    assert "fresh audit does not authorize update_goal" in result["blocked_reasons"]
    assert result["safety_guard_violations"] == []
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "audit_completion_authorized: `false`" in markdown_text


def test_north_star_completion_gate_blocks_complete_audit_missing_required_checklist_items(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": [],
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": [],
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-coverage-guard-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    assert result["completion_audit_summary"][
        "prompt_to_artifact_checklist_required_missing_count"
    ] > 0
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "completion-audit-missing-required-checklist-items" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-completion-audit-coverage" in followup_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "prompt_to_artifact_checklist_required_missing_count" in markdown_text
    assert "repair-completion-audit-coverage" in markdown_text


def test_north_star_completion_gate_blocks_audit_missing_unsatisfied_blocker_metadata(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        row = {
            "id": "gate:bridge_restart_validation",
            "category": "north_star_gate",
            "requirement": "human-approved restart validation",
            "satisfied": False,
            "status": "blocked",
            "blocker_type": "human_action_required",
        }
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": False,
                    "prompt_to_artifact_checklist": [row],
                    "unverified_or_blocked_requirements": [row],
                    "completion_actions": {
                        "may_call_update_goal": False,
                        "autonomous_progress_available": False,
                        "human_or_real_condition_required": True,
                        "human_actions": [{"gap_id": "bridge_restart_validation"}],
                        "real_condition_actions": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "not_complete",
            "north_star_complete": False,
            "unverified_or_blocked_requirements": [row],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {
                "completion_blocked": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
            },
            "prompt_to_artifact_checklist": [row],
            "completion_actions": {
                "may_call_update_goal": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "human_actions": [{"gap_id": "bridge_restart_validation"}],
                "real_condition_actions": [],
            },
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-blocker-metadata-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["completion_audit_summary"][
        "prompt_to_artifact_checklist_missing_blocker_count"
    ] == 1
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "completion-audit-unsatisfied-blocker-metadata-missing" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-completion-audit-coverage" in followup_ids


def test_north_star_completion_gate_blocks_execution_authority_in_handoff_artifact(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": True,
                "next_human_options": [{"id": "provide-exact-human-approval-phrase"}],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-safety-violation-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["success"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "next-human-action-execution-authority" in violation_ids
    assert "stable-artifact-execution-authority" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-execution-authority-artifacts" in followup_ids
    assert "repair-stable-handoff-artifacts" in followup_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Safety Guard Violations" in markdown_text
    assert "Safety Guard Follow-Up Actions" in markdown_text
    assert "repair-execution-authority-artifacts" in markdown_text
    assert "next-human-action-execution-authority" in markdown_text


def test_north_star_completion_gate_blocks_broken_stable_handoff_references(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "stable_files": {
                    "missing": str(tmp_path / "NORTH_STAR_MISSING_CURRENT.json"),
                },
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-stable-reference-guard-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "stable-handoff-reference-missing" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-stable-handoff-artifacts" in followup_ids


def test_north_star_completion_gate_blocks_latest_watch_completion_mirror_drift(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)
    _write_watch_artifact(
        tmp_path,
        {
            "status": "no_change",
            "north_star_complete": False,
            "completion_allowed": True,
            "may_call_update_goal": True,
            "audit_completion_authorized": False,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "unsatisfied_count": 0,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-watch-mirror-guard-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "latest-watch-top-level-completion-field-mismatch" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-stable-handoff-artifacts" in followup_ids


def test_north_star_completion_gate_blocks_latest_resume_completion_mirror_drift(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)
    _write_resume_artifact(
        tmp_path,
        {
            "status": "blocked_human_or_real_condition",
            "north_star_complete": False,
            "completion_allowed": True,
            "may_call_update_goal": True,
            "audit_completion_authorized": False,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "unsatisfied_count": 0,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-resume-mirror-guard-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "latest-resume-top-level-completion-field-mismatch" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-stable-handoff-artifacts" in followup_ids


def test_north_star_completion_gate_blocks_unblock_stable_scan_mirror_drift(
    tmp_path, monkeypatch
):
    def fake_audit(journal, *, repo_root, command_names):
        path = journal.run_dir / "north_star_audit.json"
        checklist = _satisfied_required_completion_checklist()
        completion_actions = _complete_audit_completion_actions()
        path.write_text(
            json.dumps(
                {
                    "north_star_complete": True,
                    "prompt_to_artifact_checklist": checklist,
                    "completion_actions": completion_actions,
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "read_only": True,
            "status": "complete",
            "north_star_complete": True,
            "unverified_or_blocked_requirements": [],
            "missing": {
                "deliverables": [],
                "prototype_paths": [],
                "commands": [],
                "live_evidence_tasks": [],
                "live_evidence_journals": [],
            },
            "blocker_summary": {"completion_blocked": False, "blocked_gap_ids": []},
            "prompt_to_artifact_checklist": checklist,
            "completion_actions": completion_actions,
            "path": str(path),
        }

    monkeypatch.setattr(north_star, "run_north_star_audit", fake_audit)
    _write_stable_scan_current(
        tmp_path,
        {
            "status": "violations",
            "violation_count": 2,
        },
    )
    _write_unblock_readiness_current(
        tmp_path,
        {
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "artifact_readiness": {
                "stable_artifact_scan_present": True,
                "stable_artifact_scan_clean": True,
                **_read_only_refresh_fields(),
            },
            "current_artifacts": {
                "stable_artifact_scan": {
                    "available": True,
                    "status": "clean",
                    "violation_count": 0,
                }
            },
        },
    )

    result = north_star.build_north_star_completion_gate(
        TaskJournal(tmp_path, "north-star-completion-gate-unblock-scan-mirror-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
    )

    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert "completion gate safety guard violations present" in result["blocked_reasons"]
    violation_ids = {item["id"] for item in result["safety_guard_violations"]}
    assert "unblock-readiness-stable-scan-optimistic-mirror-drift" in violation_ids
    followup_ids = {item["id"] for item in result["safety_guard_followup_actions"]}
    assert "repair-stable-handoff-artifacts" in followup_ids


@pytest.mark.parametrize(
    ("artifact_key", "override", "expected_id"),
    [
        (
            "waiting_state_summary",
            {"may_execute_from_waiting_state": True},
            "waiting-state-execution-authority",
        ),
        (
            "next_approval_summary",
            {"may_execute_from_this_result": True},
            "next-approval-execution-authority",
        ),
        (
            "next_human_action_summary",
            {"may_execute_from_this_result": True},
            "next-human-action-execution-authority",
        ),
        (
            "next_human_action_summary",
            {"execution_authority_violation": True},
            "next-human-action-execution-authority",
        ),
        (
            "supervised_command_packet",
            {"may_execute_from_this_packet": True},
            "supervised-packet-execution-authority",
        ),
        (
            "supervised_command_packet",
            {"execution_command_included": True},
            "supervised-packet-execution-command",
        ),
        (
            "supervised_command_packet",
            {"auto_supplied_phrase_in_commands": True},
            "supervised-packet-auto-supplied-phrase",
        ),
        (
            "supervised_command_packet",
            {"phrase_must_be_supplied_by_human": False},
            "supervised-packet-missing-human-phrase-gate",
        ),
    ],
)
def test_north_star_completion_gate_safety_guard_covers_execution_authority_sources(
    tmp_path, artifact_key, override, expected_id
):
    artifacts = {
        "waiting_state_summary": {
            "available": True,
            "may_execute_from_waiting_state": False,
        },
        "next_approval_summary": {
            "available": True,
            "may_execute_from_this_result": False,
        },
        "next_human_action_summary": {
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        "supervised_command_packet": {
            "available": True,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
            "auto_supplied_phrase_in_commands": False,
            "phrase_must_be_supplied_by_human": True,
        },
    }
    artifacts[artifact_key].update(override)

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        **artifacts,
    )

    assert [item["id"] for item in violations] == [expected_id]


def test_north_star_completion_gate_flags_stale_approval_credential_leaks(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PLAN_CURRENT.md").write_text(
        "Required human approval phrase: `I approve safe-ribbon-view-tab with token APPROVE:leaked`\n"
        "Execute only after explicit approval: `revit-operator ribbon-action --execute`\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md").write_text(
        "Stale command fragment: `revit-operator ribbon-action --execute --approval-token`\n",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    stale = [item for item in violations if item["id"] == "stale-approval-credential-leak"]
    assert stale
    assert {item["pattern"] for item in stale} >= {
        "approval-token",
        "execute-flag",
        "approval-token-flag",
        "execute-instruction",
    }
    assert any(item["artifact"] == "NORTH_STAR_APPROVAL_PLAN_CURRENT.md" for item in stale)
    assert any(item["artifact"] == "NORTH_STAR_READY_APPROVALS_CURRENT.md" for item in stale)
    stale_json = json.dumps(stale)
    assert "APPROVE:" not in stale_json
    assert "I approve " not in stale_json
    assert "Execute only after explicit approval" not in stale_json
    assert "--execute" not in stale_json
    assert "--approval-token" not in stale_json
    assert all(
        all("line" not in sample for sample in item["sample_lines"])
        for item in stale
    )
    followups = north_star._completion_gate_safety_guard_followup_actions(violations)
    assert followups == [
        {
            "id": "refresh-stale-approval-handoff",
            "action": (
                "Run the read-only north-star watch refresh so stale approval tokens, "
                "phrases, previews, and execute commands are replaced by a fresh "
                "preflight-bound handoff or withheld from stable artifacts."
            ),
            "commands": [
                "north-star-watch --refresh-approval-preflight --publish-current-handoff --checks 1 --poll 0",
                "north-star-stable-artifact-scan",
                "north-star-completion-gate",
            ],
            "refresh_command_source": (
                "Use NORTH_STAR_UNBLOCK_READINESS_CURRENT.json "
                "safe_supervision_refresh_command/safe_supervision_refresh_powershell "
                "for the exact context-matched command."
            ),
            "freshness_rule": (
                "Do not use any approval phrase or approval token until a fresh "
                "north-star-approval-preflight has been run, north-star-stable-artifact-scan "
                "reports no stale approval violations, and the hard completion gate "
                "reports no safety guard violations."
            ),
        }
    ]


def test_north_star_completion_gate_flags_near_expiry_approval_material(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-650,
                    ttl_seconds=900,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PLAN_CURRENT.md").write_text(
        "Required human approval phrase: `I approve safe-ribbon-view-tab with token APPROVE:nearly-stale`\n",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    near_expiry = [
        item
        for item in violations
        if item["id"] == "preflight-refresh-advisory-credential-risk"
    ]
    assert near_expiry
    assert {item["pattern"] for item in near_expiry} >= {
        "approval-token",
        "exact-approval-phrase",
    }
    assert all(item["preflight_refresh_status"] == "refresh_soon" for item in near_expiry)
    near_expiry_json = json.dumps(near_expiry)
    assert "APPROVE:" not in near_expiry_json
    assert "I approve " not in near_expiry_json
    assert all(
        all("line" not in sample for sample in item["sample_lines"])
        for item in near_expiry
    )
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(violations)
    }
    assert "refresh-near-expiry-approval-handoff" in followup_ids


def test_north_star_completion_gate_flags_stale_credentials_in_top_level_stable_artifacts(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md").write_text(
        "Required human approval phrase: `I approve safe-ribbon-view-tab with token APPROVE:gate`\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:handoff"
                )
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1").write_text(
        "$ExpectedHumanApprovalPhrase = 'I approve safe-ribbon-view-tab with token APPROVE:script'\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md").write_text(
        "Legacy handoff token APPROVE:legacy\n",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    stale_artifacts = {
        item["artifact"]
        for item in violations
        if item["id"] == "stale-approval-credential-leak"
    }
    assert "NORTH_STAR_COMPLETION_GATE_CURRENT.md" in stale_artifacts
    assert "NORTH_STAR_HANDOFF_CURRENT.json" in stale_artifacts
    assert "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1" in stale_artifacts
    assert "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md" in stale_artifacts


def test_north_star_stable_artifact_scan_reports_clean_current_artifacts(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_count": 4,
        "blocked_gate_count": 4,
        "may_execute_from_this_result": False,
    }
    stable_json_names = [
        "NORTH_STAR_STATUS_CURRENT.json",
        "NORTH_STAR_AUDIT_CURRENT.json",
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
    ]
    for name in stable_json_names:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    (tmp_path / "NORTH_STAR_AUDIT_CURRENT.json").write_text(
        json.dumps({**stable_false, "prompt_to_artifact_checklist": []}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Status",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "deprecated": True, "redacted": True}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Legacy Blocked Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    transport_payload = {
        **stable_false,
        "status": "clean",
        "live_revit_touched": False,
        "check_count": 3,
        "passed_count": 3,
        "failed_count": 0,
        "failed_check_ids": [],
        "direct_approval_marker_count": 0,
        "checks": [
            {
                "id": "cli-stdout-redaction",
                "status": "pass",
                "passed": True,
                "direct_approval_marker_count": 0,
            },
            {
                "id": "http-control-redaction",
                "status": "pass",
                "passed": True,
                "direct_approval_marker_count": 0,
            },
            {
                "id": "mcp-json-redaction",
                "status": "pass",
                "passed": True,
                "direct_approval_marker_count": 0,
            },
        ],
    }
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json").write_text(
        json.dumps(transport_payload),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Transport Safety Matrix",
                "",
                "- status: `clean`",
                "- read_only: `true`",
                "- live_revit_touched: `false`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- check_count: `3`",
                "- passed_count: `3`",
                "- failed_count: `0`",
                "- direct_approval_marker_count: `0`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-clean-test")
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "clean"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["violation_count"] == 0
    assert result["handoff_reference_violation_count"] == 0
    assert result["stable_current_metadata_violation_count"] == 0
    assert result["transport_safety_matrix_violation_count"] == 0
    assert result["recovery_snapshot_qualification_violation_count"] == 0
    assert result["credential_scan_mode"] == "status_always_and_stale_preflight_current_artifacts"
    assert Path(result["stable_path"]) == tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"
    assert Path(result["stable_markdown_path"]).exists()
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Stable Artifact Scan" in markdown_text
    assert "Violations" in markdown_text
    assert "- None." in markdown_text


def test_north_star_stable_artifact_scan_flags_failing_transport_safety_matrix(
    tmp_path,
):
    matrix_payload = {
        "success": True,
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "may_execute_from_this_result": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "live_revit_touched": False,
        "status": "violations",
        "check_count": 1,
        "passed_count": 0,
        "failed_count": 1,
        "failed_check_ids": ["cli-stdout-redaction"],
        "direct_approval_marker_count": 0,
        "checks": [
            {
                "id": "cli-stdout-redaction",
                "status": "fail",
                "passed": False,
                "direct_approval_marker_count": 0,
            }
        ],
    }
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json").write_text(
        json.dumps(matrix_payload),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Transport Safety Matrix",
                "",
                "- status: `violations`",
                "- read_only: `true`",
                "- live_revit_touched: `false`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- check_count: `1`",
                "- passed_count: `0`",
                "- failed_count: `1`",
                "- direct_approval_marker_count: `0`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-transport-matrix-block-test")
    )

    ids = {item["id"] for item in result["violations"]}
    assert result["status"] == "violations"
    assert result["transport_safety_matrix_violation_count"] >= 1
    assert "transport-safety-matrix-not-clean" in ids
    assert "transport-safety-matrix-failed-count-drift" in ids
    assert "transport-safety-matrix-failed-checks-present" in ids


def test_north_star_completion_gate_safety_guard_covers_transport_safety_matrix(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json").write_text(
        json.dumps(
            {
                "success": True,
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "may_execute_from_this_result": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "live_revit_touched": False,
                "status": "violations",
                "check_count": 1,
                "passed_count": 0,
                "failed_count": 1,
                "failed_check_ids": ["http-blocks-recursive-serve"],
                "direct_approval_marker_count": 0,
                "checks": [
                    {
                        "id": "http-blocks-recursive-serve",
                        "status": "fail",
                        "passed": False,
                        "direct_approval_marker_count": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Transport Safety Matrix",
                "",
                "- status: `violations`",
                "- read_only: `true`",
                "- live_revit_touched: `false`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- check_count: `1`",
                "- passed_count: `0`",
                "- failed_count: `1`",
                "- direct_approval_marker_count: `0`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={
            "available": True,
            "may_execute_from_waiting_state": False,
        },
        next_approval_summary={
            "available": True,
            "may_execute_from_this_result": False,
        },
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
        },
        supervised_command_packet={
            "available": True,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
            "auto_supplied_phrase_in_commands": False,
            "phrase_must_be_supplied_by_human": True,
        },
    )

    ids = {item["id"] for item in violations}
    assert "transport-safety-matrix-not-clean" in ids
    assert "transport-safety-matrix-failed-count-drift" in ids


def test_north_star_stable_artifact_scan_flags_missing_stable_current_metadata(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "read_only": True,
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-current-metadata-test")
    )

    assert result["success"] is True
    assert result["status"] == "violations"
    assert result["stable_current_metadata_violation_count"] == 1
    metadata = result["stable_current_metadata"]
    assert metadata["missing_generated_at_count"] == 1
    assert metadata["read_only_drift_count"] == 0
    assert metadata["execution_authority_violation_count"] == 0
    assert [item["id"] for item in metadata["violations"]] == [
        "stable-current-generated-at-missing"
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Stable Current Metadata" in markdown_text
    assert "stable_current_metadata_violation_count: `1`" in markdown_text


def test_north_star_completion_gate_routes_stable_current_metadata_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "read_only": True,
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    assert "stable-current-generated-at-missing" in {
        item["id"] for item in violations
    }
    followups = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followups


def test_north_star_completion_gate_routes_unblock_autonomous_stop_drift_to_stable_handoff_repair(
    tmp_path,
):
    gate = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "may_execute_from_this_result": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(gate),
        encoding="utf-8",
    )
    refresh_fields = _read_only_refresh_fields()
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(
            {
                **gate,
                "artifact_readiness": refresh_fields,
                "autonomous_stop": {
                    "active": False,
                    "status": "not_active",
                    "may_call_update_goal": False,
                    "audit_completion_authorized": False,
                    "may_execute_from_this_result": False,
                    "credential_material_included": False,
                    "allowed_next_command_kinds": ["observation", "read_only_refresh"],
                    "safe_refresh_command": refresh_fields[
                        "safe_supervision_refresh_command"
                    ],
                    "safe_refresh_powershell": refresh_fields[
                        "safe_supervision_refresh_powershell"
                    ],
                    "safe_refresh_read_only": True,
                },
            }
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    assert "unblock-readiness-autonomous-stop-drift" in {
        item["id"] for item in violations
    }
    followups = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followups


def _write_stable_readonly_scripts(
    tmp_path,
    supervised_extra="",
    include_resume_bridge_terms=True,
    include_supervised_phrase_source_terms=True,
):
    completion_guard = "\n".join(
        [
            "$Gate.completion_allowed -eq $true",
            "$Gate.may_call_update_goal -eq $true",
            "$Gate.audit_completion_authorized -eq $true",
            "NORTH STAR STILL BLOCKED: do not call update_goal.",
        ]
    )
    resume_bridge_terms = (
        [
            "$BridgeValidation = $Result.bridge_validation",
            "BRIDGE VALIDATION: status=$($BridgeValidation.status)",
            "failed_checks=$FailedBridgeChecks",
        ]
        if include_resume_bridge_terms
        else []
    )
    supervised_phrase_source_terms = (
        [
            "'--phrase-source',",
            "'human_active_conversation',",
        ]
        if include_supervised_phrase_source_terms
        else []
    )
    (tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1").write_text(
        "\n".join(
            [
                "# Read-only post-human gate validation",
                "'--sandbox',",
                str(tmp_path),
                "'north-star-resume-check',",
                "'north-star-refresh-sequence',",
                *resume_bridge_terms,
                "SEQUENTIAL REFRESH: status=$($RefreshResult.status)",
                completion_guard,
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1").write_text(
        "\n".join(
            [
                "# Read-only supervised approval checker",
                "'--sandbox',",
                str(tmp_path),
                "'north-star-approval-preflight',",
                "'north-star-approval-phrase-verify',",
                "'north-star-approved-execution-preview',",
                *supervised_phrase_source_terms,
                "'north-star-resume-check',",
                "'north-star-completion-gate',",
                completion_guard,
                supervised_extra,
            ]
        ),
        encoding="utf-8",
    )


def test_north_star_stable_artifact_scan_guards_readonly_scripts(tmp_path):
    _write_stable_readonly_scripts(tmp_path)

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-guard-clean-test")
    )

    assert result["status"] == "clean"
    assert result["stable_readonly_script_guard_violation_count"] == 0
    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "clean"
    assert guard["checked_script_count"] == 2
    assert guard["forbidden_match_count"] == 0
    assert guard["unsafe_goal_update_reference_count"] == 0
    assert guard["missing_sandbox_binding_count"] == 0
    assert guard["missing_required_command_count"] == 0
    assert guard["missing_required_term_count"] == 0
    assert guard["missing_completion_guard_count"] == 0
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Stable Read-Only Script Guard" in markdown_text
    assert "- Status: `clean`" in markdown_text


def test_north_star_stable_artifact_scan_flags_forbidden_readonly_script_commands(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=0,
                    ttl_seconds=900,
                ),
            }
        ),
        encoding="utf-8",
    )
    _write_stable_readonly_scripts(
        tmp_path,
        supervised_extra="\n".join(["'--execute',", "'ribbon-action',"]),
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-guard-block-test")
    )

    assert result["status"] == "violations"
    assert result["stable_readonly_script_guard_violation_count"] == 1
    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "violations"
    assert guard["forbidden_match_count"] == 2
    ids = {item["id"] for item in result["violations"]}
    assert "stable-readonly-script-forbidden-command" in ids

    safety_violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={},
        next_approval_summary={},
        next_human_action_summary={},
        supervised_command_packet={},
    )
    assert any(
        item["id"] == "stable-readonly-script-forbidden-command"
        for item in safety_violations
    )


def test_north_star_stable_artifact_scan_flags_readonly_script_approval_leaks(
    tmp_path,
):
    _write_stable_readonly_scripts(
        tmp_path,
        supervised_extra="\n".join(
            [
                "'APPROVE:leaked-token',",
                "'I approve leaked-item with token APPROVE:leaked-token',",
            ]
        ),
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-approval-leak-test")
    )

    assert result["status"] == "violations"
    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "violations"
    assert guard["forbidden_match_count"] >= 2
    supervised_summary = next(
        item
        for item in guard["script_summaries"]
        if item["artifact"] == "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1"
    )
    patterns = {item["pattern"] for item in supervised_summary["forbidden_matches"]}
    assert "approval-token-literal" in patterns
    assert "exact-approval-phrase" in patterns
    ids = {item["id"] for item in result["violations"]}
    assert "stable-readonly-script-forbidden-command" in ids

    safety_violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={},
        next_approval_summary={},
        next_human_action_summary={},
        supervised_command_packet={},
    )
    assert any(
        item["id"] == "stable-readonly-script-forbidden-command"
        for item in safety_violations
    )


def test_north_star_stable_artifact_scan_flags_missing_phrase_source_guard(
    tmp_path,
):
    _write_stable_readonly_scripts(
        tmp_path,
        include_supervised_phrase_source_terms=False,
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-phrase-source-drift-test")
    )

    assert result["status"] == "violations"
    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "violations"
    assert guard["missing_required_term_count"] >= 2
    supervised_summary = next(
        item
        for item in guard["script_summaries"]
        if item["artifact"] == "NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1"
    )
    assert "--phrase-source" in supervised_summary["missing_required_terms"]
    assert "human_active_conversation" in supervised_summary["missing_required_terms"]
    ids = {item["id"] for item in result["violations"]}
    assert "stable-readonly-script-required-term-missing" in ids

    safety_violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={},
        next_approval_summary={},
        next_human_action_summary={},
        supervised_command_packet={},
    )
    assert any(
        item["id"] == "stable-readonly-script-required-term-missing"
        for item in safety_violations
    )


def test_north_star_stable_artifact_scan_flags_resume_bridge_summary_drift(
    tmp_path,
):
    _write_stable_readonly_scripts(tmp_path, include_resume_bridge_terms=False)

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-bridge-summary-drift-test")
    )

    assert result["status"] == "violations"
    assert result["stable_readonly_script_guard_violation_count"] == 1
    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "violations"
    assert guard["missing_required_term_count"] == 3
    resume_summary = next(
        item
        for item in guard["script_summaries"]
        if item["artifact"] == "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    )
    assert "$BridgeValidation = $Result.bridge_validation" in resume_summary[
        "missing_required_terms"
    ]
    assert "BRIDGE VALIDATION: status=$($BridgeValidation.status)" in resume_summary[
        "missing_required_terms"
    ]
    assert "failed_checks=$FailedBridgeChecks" in resume_summary[
        "missing_required_terms"
    ]
    ids = {item["id"] for item in result["violations"]}
    assert "stable-readonly-script-required-term-missing" in ids

    safety_violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={},
        next_approval_summary={},
        next_human_action_summary={},
        supervised_command_packet={},
    )
    assert any(
        item["id"] == "stable-readonly-script-required-term-missing"
        for item in safety_violations
    )
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            safety_violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_script_goal_update_and_sandbox_drift(
    tmp_path,
):
    completion_guard = "\n".join(
        [
            "$Gate.completion_allowed -eq $true",
            "$Gate.may_call_update_goal -eq $true",
            "$Gate.audit_completion_authorized -eq $true",
            "NORTH STAR STILL BLOCKED: do not call update_goal.",
        ]
    )
    (tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1").write_text(
        "\n".join(
            [
                "# Read-only post-human gate validation",
                "'north-star-resume-check',",
                "'north-star-refresh-sequence',",
                "SEQUENTIAL REFRESH: status=$($RefreshResult.status)",
                "update_goal complete",
                completion_guard,
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-script-sandbox-drift-test")
    )

    guard = result["stable_readonly_script_guard"]
    assert guard["status"] == "violations"
    assert guard["unsafe_goal_update_reference_count"] == 1
    assert guard["missing_sandbox_binding_count"] == 2
    ids = {item["id"] for item in result["violations"]}
    assert "stable-readonly-script-goal-update-reference" in ids
    assert "stable-readonly-script-sandbox-binding-missing" in ids


def _write_watch_artifact(tmp_path, payload):
    run_dir = tmp_path / "revit_operator_runs" / "watch"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "north_star_watch.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_resume_artifact(tmp_path, payload):
    run_dir = tmp_path / "revit_operator_runs" / "resume"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "north_star_resume_check.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_stable_scan_current(tmp_path, payload):
    path = tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_unblock_readiness_current(tmp_path, payload):
    path = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    payload = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "may_execute_from_this_result": False,
        **payload,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    required = [
        "completion_allowed",
        "may_call_update_goal",
        "audit_completion_authorized",
        "may_execute_from_this_result",
    ]
    if all(key in payload for key in required):
        markdown = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
        markdown.write_text(
            "\n".join(
                f"- {key}: `{str(payload.get(key)).lower()}`" for key in required
            ),
            encoding="utf-8",
        )
    return path


def _read_only_refresh_fields():
    command = [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
    ]
    return {
        "safe_supervision_refresh_command": command,
        "safe_supervision_refresh_powershell": north_star._powershell_command(command),
        "safe_supervision_refresh_read_only": True,
    }


def test_north_star_stable_artifact_scan_verifies_latest_watch_completion_mirror(
    tmp_path,
):
    _write_watch_artifact(
        tmp_path,
        {
            "status": "no_change",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "unsatisfied_count": 7,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-watch-mirror-clean-test")
    )

    assert result["status"] == "clean"
    assert result["latest_watch_completion_mirror_violation_count"] == 0
    mirror = result["latest_watch_completion_mirror"]
    assert mirror["status"] == "clean"
    assert mirror["available"] is True
    assert mirror["missing_top_level_field_count"] == 0
    assert mirror["mismatch_count"] == 0
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Latest Watch Completion Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_latest_watch_completion_drift(
    tmp_path,
):
    _write_watch_artifact(
        tmp_path,
        {
            "status": "no_change",
            "north_star_complete": False,
            "completion_allowed": True,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "unsatisfied_count": 0,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-watch-mirror-drift-test")
    )

    assert result["status"] == "violations"
    assert result["latest_watch_completion_mirror_violation_count"] == 1
    mirror = result["latest_watch_completion_mirror"]
    assert mirror["status"] == "violations"
    assert mirror["mismatch_count"] >= 1
    ids = {item["id"] for item in result["violations"]}
    assert "latest-watch-top-level-completion-field-mismatch" in ids


def test_north_star_stable_artifact_scan_verifies_latest_resume_completion_mirror(
    tmp_path,
):
    _write_resume_artifact(
        tmp_path,
        {
            "status": "blocked_human_or_real_condition",
            "north_star_complete": False,
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "blocked_gap_ids": ["bridge_restart_validation"],
            "blocked_gap_count": 1,
            "blocked_gate_count": 1,
            "unsatisfied_count": 7,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-resume-mirror-clean-test")
    )

    assert result["status"] == "clean"
    assert result["latest_resume_completion_mirror_violation_count"] == 0
    mirror = result["latest_resume_completion_mirror"]
    assert mirror["status"] == "clean"
    assert mirror["available"] is True
    assert mirror["missing_top_level_field_count"] == 0
    assert mirror["mismatch_count"] == 0
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Latest Resume Completion Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_latest_resume_completion_drift(
    tmp_path,
):
    _write_resume_artifact(
        tmp_path,
        {
            "status": "blocked_human_or_real_condition",
            "north_star_complete": False,
            "completion_allowed": True,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "blocked_gap_ids": [],
            "blocked_gap_count": 0,
            "blocked_gate_count": 0,
            "unsatisfied_count": 0,
            "safety_guard_violation_count": 0,
            "completion_gate": {
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "unsatisfied_count": 7,
                "safety_guard_violations": [],
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-resume-mirror-drift-test")
    )

    assert result["status"] == "violations"
    assert result["latest_resume_completion_mirror_violation_count"] == 1
    mirror = result["latest_resume_completion_mirror"]
    assert mirror["status"] == "violations"
    assert mirror["mismatch_count"] >= 1
    ids = {item["id"] for item in result["violations"]}
    assert "latest-resume-top-level-completion-field-mismatch" in ids


def test_north_star_stable_artifact_scan_verifies_unblock_stable_scan_mirror(
    tmp_path,
):
    _write_stable_scan_current(
        tmp_path,
        {
            "status": "clean",
            "violation_count": 0,
        },
    )
    _write_unblock_readiness_current(
        tmp_path,
        {
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "artifact_readiness": {
                "stable_artifact_scan_present": True,
                "stable_artifact_scan_clean": True,
                **_read_only_refresh_fields(),
            },
            "current_artifacts": {
                "stable_artifact_scan": {
                    "available": True,
                    "status": "clean",
                    "violation_count": 0,
                }
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-unblock-scan-mirror-clean-test")
    )

    assert result["status"] == "clean"
    assert result["unblock_stable_scan_mirror_violation_count"] == 0
    mirror = result["unblock_stable_scan_mirror"]
    assert mirror["status"] == "ok"
    assert mirror["unblock_available"] is True
    assert mirror["stable_scan_available"] is True
    assert mirror["mismatch_count"] == 0
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Stable Scan Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_unblock_stable_scan_mirror_drift(
    tmp_path,
):
    _write_stable_scan_current(
        tmp_path,
        {
            "status": "violations",
            "violation_count": 2,
        },
    )
    _write_unblock_readiness_current(
        tmp_path,
        {
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "artifact_readiness": {
                "stable_artifact_scan_present": True,
                "stable_artifact_scan_clean": True,
                **_read_only_refresh_fields(),
            },
            "current_artifacts": {
                "stable_artifact_scan": {
                    "available": True,
                    "status": "clean",
                    "violation_count": 0,
                }
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-unblock-scan-mirror-drift-test")
    )

    assert result["status"] == "violations"
    assert result["unblock_stable_scan_mirror_violation_count"] == 1
    mirror = result["unblock_stable_scan_mirror"]
    assert mirror["status"] == "violations"
    assert mirror["mismatch_count"] >= 1
    assert mirror["optimistic_mismatch_count"] >= 1
    ids = {item["id"] for item in result["violations"]}
    assert "unblock-readiness-stable-scan-optimistic-mirror-drift" in ids


def test_north_star_stable_artifact_scan_reports_pessimistic_unblock_scan_drift_without_violation(
    tmp_path,
):
    _write_stable_scan_current(
        tmp_path,
        {
            "status": "clean",
            "violation_count": 0,
        },
    )
    _write_unblock_readiness_current(
        tmp_path,
        {
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "artifact_readiness": {
                "stable_artifact_scan_present": True,
                "stable_artifact_scan_clean": False,
                **_read_only_refresh_fields(),
            },
            "current_artifacts": {
                "stable_artifact_scan": {
                    "available": True,
                    "status": "violations",
                    "violation_count": 66,
                }
            },
        },
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-unblock-scan-pessimistic-test")
    )

    assert result["status"] == "clean"
    assert result["unblock_stable_scan_mirror_violation_count"] == 0
    mirror = result["unblock_stable_scan_mirror"]
    assert mirror["status"] == "ok_with_pessimistic_drift"
    assert mirror["mismatch_count"] >= 1
    assert mirror["optimistic_mismatch_count"] == 0
    assert mirror["pessimistic_mismatch_count"] >= 1


def test_north_star_stable_artifact_scan_recommends_preflight_refresh_before_expiry(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-650,
                    ttl_seconds=900,
                ),
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-preflight-refresh-advisory-test",
        )
    )

    assert result["status"] == "clean"
    advisory = result["preflight_refresh_advisory"]
    assert advisory["status"] == "refresh_soon"
    assert advisory["refresh_recommended"] is True
    assert advisory["threshold_seconds"] == 300
    assert advisory["read_only"] is True
    assert advisory["execution_command_included"] is False
    assert advisory["approval_token_included"] is False
    assert advisory["command"][:1] == ["north-star-watch"]
    assert advisory["refresh_command"] == advisory["command"]
    assert advisory["refresh_powershell"] == advisory["powershell"]
    assert "--refresh-approval-preflight" in advisory["command"]
    assert "--publish-current-handoff" in advisory["command"]
    assert "--checks" in advisory["command"]
    assert "1" in advisory["command"]
    assert "--poll" in advisory["command"]
    assert "0" in advisory["command"]
    assert "--execute" not in advisory["command"]
    assert "--approval-token" not in advisory["command"]
    assert advisory["expected_context"]["revit_version"] == "2025"
    assert advisory["expected_context"]["expected_view_name"] == "STARTING VIEW"
    assert advisory["post_refresh_commands"] == [
        "north-star-stable-artifact-scan",
        "north-star-completion-gate",
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Preflight Refresh Advisory" in markdown_text
    assert "- Status: `refresh_soon`" in markdown_text
    assert "Refresh command:" in markdown_text
    assert "north-star-watch" in markdown_text
    assert "--refresh-approval-preflight" in markdown_text
    assert "--publish-current-handoff" in markdown_text
    assert "Expected context:" in markdown_text
    assert "After refresh:" in markdown_text
    assert "north-star-stable-artifact-scan" in markdown_text
    assert "north-star-completion-gate" in markdown_text
    assert "--execute" not in markdown_text
    assert "--approval-token" not in markdown_text
    assert "APPROVE:" not in markdown_text
    assert "I approve" not in markdown_text


def test_north_star_stable_artifact_scan_flags_near_expiry_approval_material(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-650,
                    ttl_seconds=900,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md").write_text(
        "Required human approval phrase: "
        "`I approve safe-ribbon-view-tab with token APPROVE:near-expiry`\n",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-near-expiry-approval-material-test",
        )
    )

    assert result["status"] == "violations"
    assert result["preflight_refresh_advisory"]["status"] == "refresh_soon"
    assert result["preflight_refresh_advisory_credential_violation_count"] >= 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "preflight-refresh-advisory-credential-risk" in violation_ids
    near_expiry = result["preflight_refresh_advisory_credential_violations"]
    assert {item["pattern"] for item in near_expiry} >= {
        "approval-token",
        "exact-approval-phrase",
    }
    result_text = json.dumps(result)
    assert "APPROVE:near-expiry" not in result_text
    assert "I approve safe-ribbon-view-tab" not in result_text
    assert all(
        all("line" not in sample for sample in item.get("sample_lines", []))
        for item in near_expiry
    )
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "preflight_refresh_advisory_credential_violation_count" in markdown_text


def test_north_star_stable_artifact_scan_stale_preflight_gives_exact_safe_refresh_command(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-950,
                    ttl_seconds=900,
                ),
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-stale-preflight-refresh-command-test",
        )
    )

    advisory = result["preflight_refresh_advisory"]
    assert advisory["status"] == "refresh_required"
    assert advisory["refresh_recommended"] is True
    assert advisory["preflight_status"] == "preflight_stale"
    assert advisory["read_only"] is True
    assert advisory["execution_command_included"] is False
    assert advisory["approval_token_included"] is False
    assert advisory["command"][0] == "north-star-watch"
    assert "--revit-version" in advisory["command"]
    assert "2025" in advisory["command"]
    assert "--expected-title-contains" in advisory["command"]
    assert "24522 St John XXIII" in advisory["command"]
    assert "--expected-path-contains" in advisory["command"]
    assert "Structural_Current Working-R25-BIM.rvt" in advisory["command"]
    assert "--expected-view-name" in advisory["command"]
    assert "STARTING VIEW" in advisory["command"]
    assert "--expected-view-type" in advisory["command"]
    assert "DrawingSheet" in advisory["command"]
    assert "--refresh-approval-preflight" in advisory["command"]
    assert "--publish-current-handoff" in advisory["command"]
    assert "--checks" in advisory["command"]
    assert "1" in advisory["command"]
    assert "--poll" in advisory["command"]
    assert "0" in advisory["command"]
    assert "--execute" not in advisory["command"]
    assert "--approval-token" not in advisory["command"]
    assert "APPROVE:" not in advisory["powershell"]
    assert "I approve" not in advisory["powershell"]
    assert advisory["post_refresh_powershell"] == [
        "revit-operator north-star-stable-artifact-scan",
        "revit-operator north-star-completion-gate",
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "- Status: `refresh_required`" in markdown_text
    assert "Refresh command:" in markdown_text
    assert "--refresh-approval-preflight" in markdown_text
    assert "--publish-current-handoff" in markdown_text
    assert "Expected context:" in markdown_text
    assert "After refresh:" in markdown_text
    assert "--execute" not in markdown_text
    assert "--approval-token" not in markdown_text
    assert "APPROVE:" not in markdown_text
    assert "I approve" not in markdown_text


def test_north_star_stable_artifact_scan_flags_completion_gate_without_audit_authority(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "ready_to_complete",
                "north_star_complete": True,
                "completion_allowed": True,
                "may_call_update_goal": True,
                "audit_completion_authorized": False,
                "blocked_gap_ids": [],
                "blocked_gap_count": 0,
                "blocked_gate_count": 0,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-audit-authority-test",
        )
    )

    assert result["status"] == "violations"
    assert result["consistency_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "completion-gate-allowed-without-audit-authority" in violation_ids
    violation = next(
        item
        for item in result["violations"]
        if item["id"] == "completion-gate-allowed-without-audit-authority"
    )
    assert violation["artifact"] == "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    assert violation["completion_allowed"] is True
    assert violation["may_call_update_goal"] is True
    assert violation["audit_completion_authorized"] is False
    summaries = {
        item["artifact"]: item
        for item in result["consistency_summaries"]
        if item.get("present")
    }
    assert summaries["NORTH_STAR_COMPLETION_GATE_CURRENT.json"][
        "audit_completion_authorized"
    ] is False


def test_north_star_stable_scan_allows_audit_authority_without_update_goal_flag(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_AUDIT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "north_star_complete": True,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": True,
                "blocked_gap_ids": [],
                "blocked_gap_count": 0,
                "blocked_gate_count": 0,
            }
        ),
        encoding="utf-8",
    )

    report = north_star._stable_artifact_consistency_report(tmp_path)

    assert "goal-update-without-completion-allowed" not in {
        item["id"] for item in report["violations"]
    }
    audit_summary = next(
        item
        for item in report["summaries"]
        if item["artifact"] == "NORTH_STAR_AUDIT_CURRENT.json"
    )
    assert audit_summary["may_call_update_goal"] is False
    assert audit_summary["audit_completion_authorized"] is True


def test_north_star_stable_artifact_scan_flags_safety_guard_count_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": [],
                "blocked_gap_count": 0,
                "blocked_gate_count": 0,
                "safety_guard_violation_count": 2,
                "safety_guard_violations": [
                    {
                        "id": "example-violation",
                        "reason": "Only one violation is present.",
                    }
                ],
                "completion_audit_summary": {
                    "safety_guard_violation_count": 3,
                },
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-safety-guard-count-test",
        )
    )

    assert result["status"] == "violations"
    violation_ids = {item["id"] for item in result["violations"]}
    assert "stable-safety-guard-count-mismatch" in violation_ids
    assert "completion-gate-summary-safety-count-mismatch" in violation_ids
    summaries = {
        item["artifact"]: item
        for item in result["consistency_summaries"]
        if item.get("present")
    }
    gate_summary = summaries["NORTH_STAR_COMPLETION_GATE_CURRENT.json"]
    assert gate_summary["safety_guard_violation_count"] == 2
    assert gate_summary["safety_guard_violation_list_count"] == 1
    assert gate_summary[
        "completion_audit_summary_safety_guard_violation_count"
    ] == 3
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "safety_guard_violation_list_count" in markdown_text


def test_north_star_stable_artifact_scan_flags_completion_gate_markdown_safety_count_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": [],
                "blocked_gap_count": 0,
                "blocked_gate_count": 0,
                "safety_guard_violation_count": 0,
                "safety_guard_violations": [],
                "completion_audit_summary": {
                    "safety_guard_violation_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md").write_text(
        "# Gate\n\n## Safety Guard Violations\n- None.\n",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-markdown-safety-count-test",
        )
    )

    assert result["status"] == "violations"
    assert result["completion_gate_markdown_safety_count_violation_count"] == 1
    safety_count = result["completion_gate_markdown_safety_count"]
    assert safety_count["status"] == "violations"
    assert safety_count["expected_line_count"] == 2
    assert safety_count["missing_line_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "completion-gate-markdown-safety-count-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Completion Gate Markdown Safety Count" in markdown_text


def test_north_star_stable_artifact_scan_flags_approval_coverage_mismatch(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "next_human_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [],
                        "selected_item_covers_all_approval_blockers": True,
                        "approval_coverage_note": (
                            "The selected approval phrase covers all currently "
                            "blocked approval gaps."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-approval-coverage-test",
        )
    )

    assert result["status"] == "violations"
    assert result["approval_coverage_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-approval-remaining-gap-mismatch" in violation_ids
    assert "next-human-approval-cover-all-flag-mismatch" in violation_ids
    coverage = result["approval_coverage"]
    assert coverage["status"] == "violations"
    assert coverage["human_approval_option_count"] == 1
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Approval Coverage" in markdown_text


def test_north_star_stable_artifact_scan_flags_completion_gate_markdown_coverage_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "next_human_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [
                            "live_ui_workflow_execution",
                        ],
                        "selected_item_covers_all_approval_blockers": False,
                        "approval_coverage_note": (
                            "The selected approval phrase covers only the selected item gaps."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md").write_text(
        "# Gate\n\n- approval_coverage_status: `clean`\n",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-markdown-approval-coverage-test",
        )
    )

    assert result["status"] == "violations"
    assert result["approval_coverage_violation_count"] == 0
    assert result["completion_gate_markdown_approval_coverage_violation_count"] == 1
    markdown_coverage = result["completion_gate_markdown_approval_coverage"]
    assert markdown_coverage["status"] == "violations"
    assert markdown_coverage["missing_line_count"] >= 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "completion-gate-markdown-approval-coverage-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Completion Gate Markdown Approval Coverage" in markdown_text


def test_north_star_stable_artifact_scan_flags_next_human_markdown_coverage_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "next_human_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [
                            "live_ui_workflow_execution",
                        ],
                        "selected_item_covers_all_approval_blockers": False,
                        "approval_coverage_note": (
                            "The selected approval phrase covers only the selected item gaps."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "# Next\n\n  Approval blocker gaps: `live_ui_workflow_execution, live_uia_ribbon_context_execution`\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md").write_text(
        "\n".join(
            [
                "# Gate",
                "- approval_coverage_status: `clean`",
                "  - approval_blocker_gap_ids: `live_ui_workflow_execution, live_uia_ribbon_context_execution`",
                "  - selected_item_gap_ids: `live_uia_ribbon_context_execution`",
                "  - remaining_approval_gap_ids_after_selected_item: `live_ui_workflow_execution`",
                "  - selected_item_covers_all_approval_blockers: `false`",
                "  - approval_coverage_fields_present: `true`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-markdown-coverage-test",
        )
    )

    assert result["status"] == "violations"
    assert result["approval_coverage_violation_count"] == 0
    assert result["completion_gate_markdown_approval_coverage_violation_count"] == 0
    assert result["next_human_action_markdown_approval_coverage_violation_count"] == 1
    markdown_coverage = result["next_human_action_markdown_approval_coverage"]
    assert markdown_coverage["status"] == "violations"
    assert markdown_coverage["missing_line_count"] >= 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-markdown-approval-coverage-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Markdown Approval Coverage" in markdown_text


def test_north_star_stable_artifact_scan_flags_human_gate_markdown_approval_gap_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_human_or_real_condition",
                "approval_items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "gap_ids": ["live_uia_ribbon_context_execution"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md").write_text(
        "# Revit Operator Human Gate Packet\n\n- `safe-ribbon-view-tab`\n",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-human-gate-approval-gap-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_gate_packet_markdown_approval_gap_violation_count"] == 1
    approval_gap = result["human_gate_packet_markdown_approval_gap"]
    assert approval_gap["status"] == "violations"
    assert approval_gap["missing_lines"] == [
        "  gap_ids: `live_uia_ribbon_context_execution`"
    ]
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-gate-packet-markdown-approval-gap-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Human Gate Markdown Approval Gaps" in markdown_text


def test_north_star_stable_artifact_scan_flags_unblock_readiness_markdown_guard_drift(
    tmp_path,
):
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(stable_false),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(stable_false),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Unblock Readiness",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-unblock-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert (
        result["unblock_readiness_markdown_completion_guard_violation_count"] == 1
    )
    violation_ids = {item["id"] for item in result["violations"]}
    assert "unblock-readiness-markdown-completion-guard-drift" in violation_ids
    guard = result["unblock_readiness_markdown_completion_guard"]
    assert guard["missing_lines"] == ["- audit_completion_authorized: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Readiness Markdown Completion Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_unblock_next_human_option_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json").write_text(
        json.dumps({"status": "clean", "violation_count": 0}),
        encoding="utf-8",
    )
    source_summary = {
        "option_count": 2,
        "option_ids": [
            "human-restart-or-reload-revit",
            "provide-exact-human-approval-phrase",
        ],
        "option_summaries": [
            {
                "id": "human-restart-or-reload-revit",
                "kind": "human_action",
                "may_execute_from_this_option": False,
            },
            {
                "id": "provide-exact-human-approval-phrase",
                "kind": "human_approval",
                "may_execute_from_this_option": False,
                "selected_item_id": "safe-ribbon-view-tab",
            },
        ],
    }
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                **source_summary,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "artifact_readiness": {
                    "stable_artifact_scan_present": True,
                    "stable_artifact_scan_clean": True,
                },
                "current_artifacts": {
                    "stable_artifact_scan": {
                        "available": True,
                        "status": "clean",
                        "violation_count": 0,
                    }
                },
                "next_human_option_count": 1,
                "next_human_option_ids": ["human-restart-or-reload-revit"],
                "next_human_option_summaries": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                    },
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "may_execute_from_this_option": False,
                        "required_human_approval_phrase": (
                            "I approve safe-ribbon-view-tab with token APPROVE:leaked"
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Unblock Readiness",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-unblock-next-human-option-drift-test",
        )
    )

    report = result["unblock_next_human_options_mirror"]
    assert result["unblock_next_human_options_mirror_violation_count"] == 2
    assert report["status"] == "violations"
    assert report["mismatch_count"] >= 1
    assert report["credential_leak_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "unblock-readiness-next-human-options-mirror-drift" in violation_ids
    assert "unblock-readiness-next-human-options-credential-leak" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Next-Human Options Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_handoff_next_human_option_drift(
    tmp_path,
):
    source_summary = {
        "option_count": 2,
        "option_ids": [
            "human-restart-or-reload-revit",
            "provide-exact-human-approval-phrase",
        ],
        "option_summaries": [
            {
                "id": "human-restart-or-reload-revit",
                "kind": "human_action",
                "may_execute_from_this_option": False,
            },
            {
                "id": "provide-exact-human-approval-phrase",
                "kind": "human_approval",
                "may_execute_from_this_option": False,
                "selected_item_id": "safe-ribbon-view-tab",
            },
        ],
    }
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                **source_summary,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "stable_files": {
                    "next_human_action": str(
                        tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
                    )
                },
                "next_human_action": {
                    "option_count": 1,
                    "option_ids": ["human-restart-or-reload-revit"],
                    "option_summaries": [
                        {
                            "id": "human-restart-or-reload-revit",
                            "kind": "human_action",
                            "may_execute_from_this_option": False,
                        },
                        {
                            "id": "provide-exact-human-approval-phrase",
                            "kind": "human_approval",
                            "may_execute_from_this_option": False,
                            "required_human_approval_phrase": (
                                "I approve safe-ribbon-view-tab with token APPROVE:leaked"
                            ),
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-handoff-next-human-option-drift-test",
        )
    )

    report = result["handoff_next_human_options_mirror"]
    assert result["handoff_next_human_options_mirror_violation_count"] == 2
    assert report["status"] == "violations"
    assert report["mismatch_count"] >= 1
    assert report["credential_leak_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "handoff-next-human-options-mirror-drift" in violation_ids
    assert "handoff-next-human-options-credential-leak" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Handoff Next-Human Options Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_human_gate_packet_markdown_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Human Gate Packet",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-human-gate-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_gate_packet_markdown_completion_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-gate-packet-markdown-completion-guard-drift" in violation_ids
    guard = result["human_gate_packet_markdown_completion_guard"]
    assert guard["missing_lines"] == ["- audit_completion_authorized: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Human Gate Packet Markdown Completion Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_handoff_markdown_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-handoff-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert result["handoff_markdown_completion_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "handoff-markdown-completion-guard-drift" in violation_ids
    guard = result["handoff_markdown_completion_guard"]
    assert guard["missing_lines"] == ["- audit_completion_authorized: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Current Handoff Markdown Completion Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_handoff_agent_stop_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "agent_stop_status": {
                    "status": "stop_for_human_or_real_condition",
                    "should_stop_agent": True,
                    "agent_stop_reason": (
                        "human_or_real_condition_required_no_autonomous_progress"
                    ),
                    "recommended_agent_action": "wait_for_human_or_real_condition",
                    "completion_allowed": False,
                    "may_call_update_goal": False,
                    "audit_completion_authorized": False,
                    "hard_gate_allows_completion": False,
                    "may_execute_from_this_result": False,
                    "blocked_gap_count": 1,
                    "unsatisfied_count": 7,
                    "safety_guard_violation_count": 0,
                    "option_count": 3,
                    "approval_material_included": False,
                    "approval_material_withheld": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Agent Stop Status",
                "- status: `stop_for_human_or_real_condition`",
                "- should_stop_agent: `true`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-handoff-agent-stop-markdown-test",
        )
    )

    assert result["status"] == "violations"
    assert result["handoff_markdown_completion_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "handoff-agent-stop-markdown-guard-drift" in violation_ids
    guard = result["handoff_markdown_completion_guard"]
    assert guard["agent_stop_status_missing_line_count"] >= 1
    assert "- approval_material_withheld: `true`" in guard[
        "agent_stop_status_missing_lines"
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "agent_stop_status_missing_line_count" in markdown_text


def test_north_star_stable_artifact_scan_flags_legacy_blocked_handoff_markdown_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "deprecated": True,
                "redacted": True,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Legacy Blocked Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-legacy-handoff-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert (
        result["legacy_blocked_handoff_markdown_completion_guard_violation_count"]
        == 1
    )
    violation_ids = {item["id"] for item in result["violations"]}
    assert "legacy-blocked-handoff-markdown-completion-guard-drift" in violation_ids
    guard = result["legacy_blocked_handoff_markdown_completion_guard"]
    assert guard["missing_lines"] == ["- audit_completion_authorized: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Legacy Blocked Handoff Markdown Completion Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_next_human_action_markdown_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_markdown_completion_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-action-markdown-completion-guard-drift" in violation_ids
    guard = result["next_human_action_markdown_completion_guard"]
    assert guard["missing_lines"] == ["- audit_completion_authorized: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Action Markdown Completion Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_human_real_boundary_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-human-real-boundary-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_real_condition_boundary_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-real-boundary-json-missing" in violation_ids
    assert "human-real-boundary-markdown-drift" in violation_ids
    boundary = result["human_real_condition_boundary"]
    assert boundary["missing_source_key_count"] == 3
    assert boundary["missing_markdown_line_count"] == 3
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Human Or Real Condition Boundary" in markdown_text


def test_north_star_stable_artifact_scan_flags_human_gate_packet_boundary_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Human Gate Packet",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- autonomous_progress_available: `false`",
                "- human_or_real_condition_required: `true`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-human-gate-boundary-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_real_condition_boundary_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-real-boundary-json-missing" in violation_ids
    assert "human-real-boundary-markdown-drift" in violation_ids
    boundary = result["human_real_condition_boundary"]
    assert boundary["missing_source_key_count"] == 1
    assert boundary["missing_markdown_line_count"] == 1
    summary = next(
        item
        for item in boundary["artifact_summaries"]
        if item["artifact"] == "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json"
    )
    assert summary["missing_source_keys"] == [
        "blocked_waiting_for_human_or_real_condition"
    ]
    assert summary["missing_markdown_lines"] == [
        "- blocked_waiting_for_human_or_real_condition: `true`"
    ]


def test_north_star_stable_artifact_scan_flags_blocked_ledger_boundary_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_LEDGER_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Blocked North-Star Ledger",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-blocked-ledger-boundary-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_real_condition_boundary_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-real-boundary-markdown-drift" in violation_ids
    boundary = result["human_real_condition_boundary"]
    assert boundary["missing_source_key_count"] == 0
    assert boundary["missing_markdown_line_count"] == 3
    summary = next(
        item
        for item in boundary["artifact_summaries"]
        if item["artifact"] == "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json"
    )
    assert summary["missing_source_keys"] == []
    assert summary["missing_markdown_lines"] == [
        "- autonomous_progress_available: `false`",
        "- human_or_real_condition_required: `true`",
        "- blocked_waiting_for_human_or_real_condition: `true`",
    ]


def test_north_star_stable_artifact_scan_flags_status_audit_approval_boundary_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    for artifact in [
        "NORTH_STAR_STATUS_CURRENT",
        "NORTH_STAR_AUDIT_CURRENT",
        "NORTH_STAR_APPROVAL_PLAN_CURRENT",
    ]:
        (tmp_path / f"{artifact}.json").write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "north_star_complete": False,
                    "completion_allowed": False,
                    "may_call_update_goal": False,
                    "audit_completion_authorized": False,
                    "may_execute_from_this_result": False,
                    "autonomous_progress_available": False,
                    "human_or_real_condition_required": True,
                    "blocked_waiting_for_human_or_real_condition": True,
                    "blocked_gap_ids": ["bridge_restart_validation"],
                    "blocked_gap_count": 1,
                    "blocked_gate_count": 1,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / f"{artifact}.md").write_text(
            "\n".join(
                [
                    f"# {artifact}",
                    "",
                    "- completion_allowed: `false`",
                    "- may_call_update_goal: `false`",
                    "- audit_completion_authorized: `false`",
                    "- may_execute_from_this_result: `false`",
                ]
            ),
            encoding="utf-8",
        )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-status-audit-plan-boundary-test",
        )
    )

    assert result["status"] == "violations"
    assert result["human_real_condition_boundary_violation_count"] == 3
    violation_ids = {item["id"] for item in result["violations"]}
    assert "human-real-boundary-markdown-drift" in violation_ids
    boundary = result["human_real_condition_boundary"]
    assert boundary["checked_artifact_count"] == 3
    assert boundary["missing_source_key_count"] == 0
    assert boundary["missing_markdown_line_count"] == 9
    drift_artifacts = {
        item["artifact"]
        for item in boundary["artifact_summaries"]
        if item["missing_markdown_lines"]
    }
    assert drift_artifacts == {
        "NORTH_STAR_STATUS_CURRENT.json",
        "NORTH_STAR_AUDIT_CURRENT.json",
        "NORTH_STAR_APPROVAL_PLAN_CURRENT.json",
    }


def test_north_star_completion_gate_routes_human_real_boundary_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "autonomous_progress_available": False,
                "human_or_real_condition_required": True,
                "blocked_waiting_for_human_or_real_condition": True,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "human-real-boundary-json-missing" in violation_ids
    assert "human-real-boundary-markdown-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_next_human_bridge_cause_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "blocked_gap_ids": ["bridge_restart_validation"],
                "blocked_gap_count": 1,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-bridge-cause-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_markdown_bridge_cause_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-markdown-bridge-cause-drift" in violation_ids
    bridge_cause = result["next_human_action_markdown_bridge_cause"]
    assert bridge_cause["missing_lines"] == [
        "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
        "  Failed bridge checks: `loaded_build_current`",
        "  requires_revit_restart_or_reload: `true`",
        "  no_save_checklist_present: `true`",
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Markdown Bridge Cause" in markdown_text


def test_north_star_completion_gate_routes_next_human_bridge_cause_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-human-markdown-bridge-cause-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_next_human_restart_checklist_path_drift(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    run_checklist = (
        tmp_path
        / "revit_operator_runs"
        / "bridge-plan"
        / "bridge_restart_no_save_checklist.md"
    )
    run_checklist.parent.mkdir(parents=True)
    run_checklist.write_text("run checklist", encoding="utf-8")
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(run_checklist),
                        "source_checklist_path": str(run_checklist),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{run_checklist}`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-restart-checklist-path-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_restart_checklist_path_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-restart-checklist-path-drift" in violation_ids
    assert "next-human-restart-checklist-markdown-drift" in violation_ids
    path_report = result["next_human_action_restart_checklist_path"]
    assert path_report["expected_path"] == str(stable_checklist)
    assert path_report["actual_path"] == str(run_checklist)
    assert path_report["markdown_line_present"] is False
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Restart Checklist Path" in markdown_text


def test_north_star_completion_gate_routes_next_human_restart_checklist_path_drift_to_stable_handoff_repair(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    run_checklist = (
        tmp_path
        / "revit_operator_runs"
        / "bridge-plan"
        / "bridge_restart_no_save_checklist.md"
    )
    run_checklist.parent.mkdir(parents=True)
    run_checklist.write_text("run checklist", encoding="utf-8")
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(run_checklist),
                        "source_checklist_path": str(run_checklist),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{run_checklist}`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-human-restart-checklist-path-drift" in violation_ids
    assert "next-human-restart-checklist-markdown-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_next_human_resume_script_path_drift(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    stable_resume = tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    stable_resume.write_text("# stable resume", encoding="utf-8")
    run_resume = tmp_path / "revit_operator_runs" / "handoff" / "resume.ps1"
    run_resume.parent.mkdir(parents=True)
    run_resume.write_text("# run resume", encoding="utf-8")
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_script": str(run_resume),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume script: `{run_resume}`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-resume-script-path-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_resume_script_path_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-resume-script-path-drift" in violation_ids
    assert "next-human-resume-script-markdown-drift" in violation_ids
    path_report = result["next_human_action_resume_script_path"]
    assert path_report["expected_path"] == str(stable_resume)
    assert path_report["actual_path"] == str(run_resume)
    assert path_report["markdown_line_present"] is False
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Resume Script Path" in markdown_text


def test_north_star_completion_gate_routes_next_human_resume_script_path_drift_to_stable_handoff_repair(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    stable_resume = tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    stable_resume.write_text("# stable resume", encoding="utf-8")
    run_resume = tmp_path / "revit_operator_runs" / "handoff" / "resume.ps1"
    run_resume.parent.mkdir(parents=True)
    run_resume.write_text("# run resume", encoding="utf-8")
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_script": str(run_resume),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume script: `{run_resume}`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-human-resume-script-path-drift" in violation_ids
    assert "next-human-resume-script-markdown-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_next_human_resume_command_drift(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    bad_command = [
        "click",
        "--target",
        "OK",
        "--execute",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
    ]
    bad_powershell = north_star._powershell_command(bad_command)
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_command": bad_command,
                        "post_action_resume_powershell": bad_powershell,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume command: `{bad_powershell}`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-resume-command-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_resume_command_violation_count"] >= 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-resume-command-not-readonly" in violation_ids
    assert "next-human-resume-command-forbidden-token" in violation_ids
    command_report = result["next_human_action_resume_command"]
    assert command_report["actual_command"] == bad_powershell
    assert command_report["markdown_line_present"] is True
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Human Resume Command" in markdown_text


def test_north_star_resume_command_report_flags_summary_drift(tmp_path):
    safe_command = [
        "north-star-resume-check",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
    ]
    safe_powershell = north_star._powershell_command(safe_command)
    bad_summary_command = [
        "click",
        "--target",
        "OK",
        "--execute",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
    ]
    bad_summary_powershell = north_star._powershell_command(bad_summary_command)
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "post_action_resume_command": safe_command,
                        "post_action_resume_powershell": safe_powershell,
                    }
                ],
                "option_summaries": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                        "post_action_resume_command": bad_summary_command,
                        "post_action_resume_powershell": bad_summary_powershell,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                f"  Resume command: `{safe_powershell}`",
            ]
        ),
        encoding="utf-8",
    )

    report = north_star._next_human_action_resume_command_report(tmp_path)

    assert report["status"] == "violations"
    assert report["summary_present"] is True
    assert report["summary_command_present"] is True
    assert report["summary_powershell_present"] is True
    assert report["summary_command_matches_option"] is False
    assert report["summary_powershell_matches_option"] is False
    assert report["summary_forbidden_match_count"] == 2
    violation_ids = {item["id"] for item in report["violations"]}
    assert "next-human-resume-command-summary-drift" in violation_ids
    assert "next-human-resume-command-summary-forbidden-token" in violation_ids
    assert "next-human-resume-command-not-readonly" not in violation_ids


def test_north_star_completion_gate_routes_next_human_resume_command_drift_to_stable_handoff_repair(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    bad_command = [
        "revit-operator",
        "click",
        "--target",
        "OK",
        "--execute",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
    ]
    bad_powershell = "revit-operator click --target OK --execute --sheet-number S2.0 --revit-version 2025"
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_command": bad_command,
                        "post_action_resume_powershell": bad_powershell,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume command: `{bad_powershell}`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-human-resume-command-not-readonly" in violation_ids
    assert "next-human-resume-command-forbidden-token" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_next_human_resume_command_context_drift(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "Do not mark the north-star goal complete unless a fresh "
                "`north-star-completion-gate` or `north-star-resume-check.completion_gate` "
                "reports `completion_allowed: true`, `may_call_update_goal: true`, "
                "and `audit_completion_authorized: true`. Status and audit summaries "
                "are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
            }
        ),
        encoding="utf-8",
    )
    drift_command = [
        "north-star-resume-check",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-path-contains",
        "Structural_Current Working-R25-BIM",
        "--expected-view-name",
        "WRONG VIEW",
    ]
    drift_powershell = north_star._powershell_command(drift_command)
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_command": drift_command,
                        "post_action_resume_powershell": drift_powershell,
                    }
                ],
                "option_summaries": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                        "post_action_resume_command": drift_command,
                        "post_action_resume_powershell": drift_powershell,
                    }
                ],
                "option_summaries": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "may_execute_from_this_option": False,
                        "post_action_resume_command": drift_command,
                        "post_action_resume_powershell": drift_powershell,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume command: `{drift_powershell}`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-human-resume-command-context-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_human_action_resume_command_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-human-resume-command-required-option-missing" in violation_ids
    assert "next-human-resume-command-context-mismatch" in violation_ids
    command_report = result["next_human_action_resume_command"]
    assert command_report["missing_context_option_count"] == 1
    assert command_report["context_mismatch_count"] == 1
    assert command_report["expected_context"]["expected_view_type"] == "DrawingSheet"


def test_north_star_completion_gate_routes_next_human_resume_command_context_drift_to_stable_handoff_repair(
    tmp_path,
):
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    stable_checklist.write_text(
        "\n".join(
            [
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge build metadata.",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
            }
        ),
        encoding="utf-8",
    )
    drift_command = [
        "north-star-resume-check",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-path-contains",
        "Structural_Current Working-R25-BIM",
        "--expected-view-name",
        "WRONG VIEW",
    ]
    drift_powershell = north_star._powershell_command(drift_command)
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(stable_checklist),
                        "post_action_resume_command": drift_command,
                        "post_action_resume_powershell": drift_powershell,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
                f"  Resume command: `{drift_powershell}`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-human-resume-command-required-option-missing" in violation_ids
    assert "next-human-resume-command-context-mismatch" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_restart_checklist_bridge_cause_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW\n\nDo not save or sync.",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-restart-checklist-bridge-cause-test",
        )
    )

    assert result["status"] == "violations"
    assert result["restart_no_save_checklist_bridge_cause_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "restart-checklist-bridge-cause-drift" in violation_ids
    bridge_cause = result["restart_no_save_checklist_bridge_cause"]
    assert bridge_cause["missing_lines"] == [
        "## Bridge Reload Cause",
        "Loaded Revit add-in is stale or lacks current bridge",
        "restart_or_reload_required: `True`",
        "failed_readiness_checks: `loaded_build_current`",
        "failed_loaded_build_checks:",
        "bridge_protocol_version=`0.2`",
        "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
        "supports_continuous_idling=`True`",
        "uses_idling_set_raise_without_delay=`True`",
        "observed_loaded_metadata:",
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Restart No-Save Checklist Bridge Cause" in markdown_text


def test_north_star_completion_gate_routes_restart_checklist_bridge_cause_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW\n\nDo not save or sync.",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "restart-checklist-bridge-cause-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def _write_clean_restart_checklist_for_freshness(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge",
                "restart_or_reload_required: `True`",
                "failed_readiness_checks: `loaded_build_current`",
                "failed_loaded_build_checks:",
                "bridge_protocol_version=`0.2`",
                "source_capability_stamp=`continuous-idling-status-file-retry-v2`",
                "supports_continuous_idling=`True`",
                "uses_idling_set_raise_without_delay=`True`",
                "observed_loaded_metadata:",
                "",
                "## Add-In Startup Prompt Preflight",
                "addin_security_status: `verified`",
                "expected_local_hermes_addin: `True`",
                "needs_trust_addin: `False`",
                "can_consider_always_load_after_human_approval: `True`",
                "allowed_dialog_button_after_human_approval: `Always Load`",
                "blocked_dialog_buttons: `Load Once`, `Do Not Load`",
                "signature_status: `Valid`",
                "signer_subject: `CN=Hermes Revit Operator Local Code Signing`",
                "Hermes must not click it from this checklist",
                "require an exact approval token before any `Always Load` click",
                "",
                "`north-star-completion-gate`",
                "`north-star-resume-check.completion_gate`",
                "`completion_allowed: true`",
                "`may_call_update_goal: true`",
                "`audit_completion_authorized: true`",
                "Status and audit summaries are diagnostic only.",
            ]
        ),
        encoding="utf-8",
    )


def _write_restart_freshness_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    stable_checklist = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    _write_clean_restart_checklist_for_freshness(stable_checklist)
    source_dir = tmp_path / "revit_operator_runs" / "bridge-plan-freshness"
    source_dir.mkdir(parents=True)
    source_checklist = source_dir / "bridge_restart_no_save_checklist.md"
    _write_clean_restart_checklist_for_freshness(source_checklist)
    source_plan = source_dir / "bridge_restart_validation_plan.json"
    source_plan.write_text(
        json.dumps(
            {
                "success": True,
                "status": "human_restart_required",
                "human_handoff_required": True,
                "restart_or_reload_required": True,
                "no_save_checklist_path": str(source_checklist),
                "addin_security_preflight": {
                    "status": "verified",
                    "expected_local_hermes_addin": True,
                    "needs_trust_addin": False,
                    "can_consider_always_load_after_human_approval": True,
                    "allowed_dialog_button": "Always Load",
                    "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
                    "signature": {
                        "status": "Valid",
                        "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                        "bridge_technical_cause": (
                            "Loaded Revit add-in is stale or lacks current bridge metadata."
                        ),
                        "failed_bridge_checks": ["loaded_build_current"],
                        "requires_revit_restart_or_reload": True,
                        "no_save_checklist_present": True,
                        "checklist_path": str(stable_checklist),
                        "source_checklist_path": str(source_checklist),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Current Human Unblock Options",
                "- `human-restart-or-reload-revit` / `human_action`",
                "  Gap: `bridge_restart_validation`",
                "  may_execute_from_this_option: `false`",
                "  Technical cause: Loaded Revit add-in is stale or lacks current bridge metadata.",
                "  Failed bridge checks: `loaded_build_current`",
                "  requires_revit_restart_or_reload: `true`",
                "  no_save_checklist_present: `true`",
                f"  Checklist: `{stable_checklist}`",
            ]
        ),
        encoding="utf-8",
    )
    os.utime(stable_checklist, (1_000, 1_000))
    os.utime(source_checklist, (2_000, 2_000))
    os.utime(source_plan, (2_001, 2_001))
    return stable_checklist, source_checklist, source_plan


def test_north_star_stable_artifact_scan_flags_restart_checklist_freshness_drift(
    tmp_path,
):
    stable_checklist, source_checklist, _source_plan = _write_restart_freshness_fixture(
        tmp_path
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-restart-checklist-freshness-test",
        )
    )

    assert result["status"] == "violations"
    assert result["restart_no_save_checklist_freshness_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "restart-checklist-freshness-stale" in violation_ids
    freshness = result["restart_no_save_checklist_freshness"]
    assert freshness["path"] == str(stable_checklist)
    assert freshness["source_checklist_path"] == str(source_checklist)
    assert freshness["stable_checklist_mtime_utc"] < freshness["latest_source_mtime_utc"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Restart No-Save Checklist Freshness" in markdown_text


def test_north_star_completion_gate_routes_restart_checklist_freshness_drift_to_stable_handoff_repair(
    tmp_path,
):
    _write_restart_freshness_fixture(tmp_path)

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "restart-checklist-freshness-stale" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_restart_checklist_addin_preflight_drift(
    tmp_path,
):
    plan_dir = tmp_path / "revit_operator_runs" / "bridge-plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "bridge_restart_validation_plan.json").write_text(
        json.dumps(
            {
                "success": True,
                "status": "human_restart_required",
                "addin_security_preflight": {
                    "status": "verified",
                    "expected_local_hermes_addin": True,
                    "needs_trust_addin": False,
                    "can_consider_always_load_after_human_approval": True,
                    "allowed_dialog_button": "Always Load",
                    "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
                    "signature": {
                        "status": "Valid",
                        "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "\n".join(
            [
                "# Bridge Restart / Reload No-Save Checklist",
                "",
                "## Bridge Reload Cause",
                "Loaded Revit add-in is stale or lacks current bridge",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-restart-checklist-addin-preflight-test",
        )
    )

    assert result["status"] == "violations"
    assert result["restart_no_save_checklist_addin_preflight_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "restart-checklist-addin-preflight-drift" in violation_ids
    addin_preflight = result["restart_no_save_checklist_addin_preflight"]
    assert "## Add-In Startup Prompt Preflight" in addin_preflight["missing_lines"]
    assert "addin_security_status: `verified`" in addin_preflight["missing_lines"]
    assert (
        "allowed_dialog_button_after_human_approval: `Always Load`"
        in addin_preflight["missing_lines"]
    )
    assert "signature_status: `Valid`" in addin_preflight["missing_lines"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Restart No-Save Checklist Add-In Preflight" in markdown_text


def test_north_star_completion_gate_routes_restart_checklist_addin_preflight_drift_to_stable_handoff_repair(
    tmp_path,
):
    plan_dir = tmp_path / "revit_operator_runs" / "bridge-plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "bridge_restart_validation_plan.json").write_text(
        json.dumps(
            {
                "success": True,
                "status": "human_restart_required",
                "addin_security_preflight": {
                    "status": "verified",
                    "expected_local_hermes_addin": True,
                    "needs_trust_addin": False,
                    "can_consider_always_load_after_human_approval": True,
                    "allowed_dialog_button": "Always Load",
                    "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
                    "signature": {
                        "status": "Valid",
                        "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW\n\nDo not save or sync.",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "restart-checklist-addin-preflight-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_restart_checklist_completion_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW\n\n"
        "Do not mark the north-star goal complete until a fresh status or audit artifact reports both "
        "`north_star_complete: true` and `may_call_update_goal: true`.",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-restart-checklist-completion-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert result["restart_no_save_checklist_completion_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "restart-checklist-completion-guard-drift" in violation_ids
    completion_guard = result["restart_no_save_checklist_completion_guard"]
    assert completion_guard["missing_lines"] == [
        "`north-star-completion-gate`",
        "`north-star-resume-check.completion_gate`",
        "`completion_allowed: true`",
        "`audit_completion_authorized: true`",
        "Status and audit summaries are diagnostic only.",
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Restart No-Save Checklist Completion Guard" in markdown_text


def test_north_star_completion_gate_routes_restart_checklist_completion_guard_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "next_human_options": [
                    {
                        "id": "human-restart-or-reload-revit",
                        "kind": "human_action",
                        "gap_id": "bridge_restart_validation",
                        "may_execute_from_this_option": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md").write_text(
        "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW\n\nDo not save or sync.",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "restart-checklist-completion-guard-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(
            violations
        )
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_stable_artifact_scan_flags_ready_approvals_markdown_guard_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "ready_items_available",
                "read_only": True,
                "ready_approval_count": 1,
                "withheld_approval_count": 0,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Ready North-Star Approvals",
                "",
                "- Status: `ready_items_available`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-ready-approvals-markdown-guard-test",
        )
    )

    assert result["status"] == "violations"
    assert result["ready_approvals_markdown_execution_guard_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "ready-approvals-markdown-execution-guard-drift" in violation_ids
    guard = result["ready_approvals_markdown_execution_guard"]
    assert guard["missing_lines"] == ["- may_execute_from_this_result: `false`"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Ready Approvals Markdown Execution Guard" in markdown_text


def test_north_star_stable_artifact_scan_flags_ready_approvals_markdown_approval_gap_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "ready_items_available",
                "read_only": True,
                "ready_approval_count": 1,
                "withheld_approval_count": 0,
                "may_execute_from_this_result": False,
                "ready_items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "gap_ids": ["live_uia_ribbon_context_execution"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Ready North-Star Approvals",
                "",
                "- Status: `ready_items_available`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Ready Items",
                "- `safe-ribbon-view-tab`: Select the Revit View ribbon tab only.",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-ready-approval-gap-test",
        )
    )

    assert result["status"] == "violations"
    assert result["ready_approvals_markdown_execution_guard_violation_count"] == 0
    assert result["ready_approvals_markdown_approval_gap_violation_count"] == 1
    approval_gap = result["ready_approvals_markdown_approval_gap"]
    assert approval_gap["status"] == "violations"
    assert approval_gap["missing_lines"] == [
        "- `safe-ribbon-view-tab` -> gap_ids: `live_uia_ribbon_context_execution`"
    ]
    violation_ids = {item["id"] for item in result["violations"]}
    assert "ready-approvals-markdown-approval-gap-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Ready Approvals Markdown Approval Gaps" in markdown_text


def test_north_star_stable_artifact_scan_flags_next_approval_markdown_approval_gap_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "approval_ready",
                "read_only": True,
                "may_execute_from_this_result": False,
                "selected_item": {
                    "id": "safe-ribbon-view-tab",
                    "gap_ids": ["live_uia_ribbon_context_execution"],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next North-Star Approval",
                "",
                "- may_execute_from_this_result: `false`",
                "",
                "## Selected Item",
                "- `safe-ribbon-view-tab`: Select the Revit View ribbon tab only.",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-next-approval-gap-test",
        )
    )

    assert result["status"] == "violations"
    assert result["next_approval_markdown_approval_gap_violation_count"] == 1
    approval_gap = result["next_approval_markdown_approval_gap"]
    assert approval_gap["status"] == "violations"
    assert approval_gap["missing_lines"] == [
        "- `safe-ribbon-view-tab` -> gap_ids: `live_uia_ribbon_context_execution`"
    ]
    violation_ids = {item["id"] for item in result["violations"]}
    assert "next-approval-markdown-approval-gap-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Next Approval Markdown Approval Gaps" in markdown_text


def test_north_star_stable_artifact_scan_flags_waiting_state_approval_gap_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "approval_ready",
                "read_only": True,
                "may_execute_from_this_result": False,
                "selected_item": {
                    "id": "safe-ribbon-view-tab",
                    "gap_ids": ["live_uia_ribbon_context_execution"],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "waiting_for_human_or_real_condition",
                "next_approval_item_id": "safe-ribbon-view-tab",
                "next_approval_gap_ids": ["live_uia_ribbon_context_execution"],
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:test"
                ),
                "may_execute_from_waiting_state": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Waiting State",
                "",
                "- may_execute_from_waiting_state: `false`",
                "",
                "## Required Human Approval Phrase",
                "`I approve safe-ribbon-view-tab with token APPROVE:test`",
                "- next_approval_item_id: `safe-ribbon-view-tab`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-waiting-state-gap-test",
        )
    )

    assert result["status"] == "violations"
    assert result["waiting_state_approval_gap_violation_count"] == 1
    approval_gap = result["waiting_state_approval_gap"]
    assert approval_gap["status"] == "violations"
    assert approval_gap["missing_lines"] == [
        "- next_approval_gap_ids: `live_uia_ribbon_context_execution`"
    ]
    violation_ids = {item["id"] for item in result["violations"]}
    assert "waiting-state-approval-gap-markdown-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Waiting State Approval Gaps" in markdown_text


def test_north_star_stable_artifact_scan_flags_generic_authority_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_CUSTOM_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_CUSTOM_CURRENT.md").write_text(
        "\n".join(
            [
                "# Custom Current Artifact",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-generic-authority-markdown-test",
        )
    )

    assert result["status"] == "violations"
    assert result["authority_markdown_mirror_violation_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "stable-authority-markdown-mirror-drift" in violation_ids
    mirror = result["authority_markdown_mirror"]
    assert mirror["checked_artifact_count"] == 1
    assert mirror["checked_key_count"] == 4
    assert mirror["violations"][0]["missing_lines"] == [
        "- audit_completion_authorized: `false`"
    ]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Authority Markdown Mirror" in markdown_text


def test_north_star_stable_artifact_scan_flags_recovery_snapshot_claim_drift(
    tmp_path,
):
    recovery_dir = tmp_path / "revit_operator_runs" / "live-idle-claim"
    recovery_dir.mkdir(parents=True)
    (recovery_dir / "recovery_snapshot.json").write_text(
        json.dumps(
            {
                "status": {
                    "state": "idle",
                    "main_window": {
                        "process_name": "Revit.exe",
                        "is_revit_related": True,
                        "is_hung": False,
                    },
                    "active_dialogs": [],
                },
                "dialogs": {"dialogs": []},
                "recommendation": {"classification": "safe_to_continue_read_only"},
                "validated_live_recovery_drill": True,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-recovery-qualification-test",
        )
    )

    assert result["status"] == "violations"
    assert result["recovery_snapshot_qualification_violation_count"] == 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "recovery-snapshot-claimed-without-qualifying-gate" in violation_ids
    assert "recovery-snapshot-claimed-but-classifier-rejects" in violation_ids
    recovery_report = result["recovery_snapshot_qualification"]
    assert recovery_report["checked_snapshot_count"] == 1
    assert recovery_report["claimed_valid_count"] == 1
    assert recovery_report["embedded_qualifying_gate_count"] == 0
    assert recovery_report["computed_qualifying_count"] == 0
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Recovery Snapshot Qualification" in markdown_text


def test_north_star_stable_artifact_scan_flags_approval_phrase_metadata_gaps(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "waiting_state_summary": {
                    "required_human_approval_phrase": (
                        "I approve safe-ribbon-view-tab with token APPROVE:fresh"
                    ),
                    "approval_phrase_execution_authority": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "approval_items": [
                    {
                        "required_human_approval_phrase": (
                            "I approve approved-workflow-open-sheet with token APPROVE:fresh2"
                        ),
                        "approval_phrase_expires_at_utc": "2099-01-01T00:00:00Z",
                        "approval_phrase_execution_authority": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md").write_text(
        "Required human approval phrase: "
        "`I approve direct-uia-view-tab-select with token APPROVE:fresh3`\n"
        "approval_phrase_expires_at_utc: `2099-01-01T00:00:00Z`\n",
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-phrase-metadata-test")
    )

    assert result["status"] == "violations"
    assert result["approval_phrase_metadata_violation_count"] == 6
    assert result["approval_phrase_metadata"]["status"] == "violations"
    violation_ids = {item["id"] for item in result["violations"]}
    assert "approval-phrase-expiry-missing" in violation_ids
    assert "approval-phrase-execution-authority-unsafe" in violation_ids
    assert "approval-phrase-execution-authority-missing" in violation_ids
    assert "approval-phrase-provenance-note-missing" in violation_ids
    assert "APPROVE:fresh" not in json.dumps(result)


def test_north_star_completion_gate_safety_guard_covers_approval_phrase_metadata(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
                {
                    "read_only": True,
                    "generated_at_utc": "2026-05-14T00:00:00Z",
                    "status": "blocked",
                    "completion_allowed": False,
                    "may_call_update_goal": False,
                    "may_execute_from_this_result": False,
                    "supervised_command_packet": {
                    "required_human_approval_phrase": (
                        "I approve safe-ribbon-view-tab with token APPROVE:fresh"
                    ),
                    "approval_phrase_execution_authority": False,
                },
            }
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    assert [item["id"] for item in violations] == [
        "approval-phrase-expiry-missing",
        "approval-phrase-provenance-note-missing",
    ]


def test_north_star_stable_artifact_scan_flags_unexpected_stale_credentials(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-3600,
                    ttl_seconds=1,
                ),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "not_complete",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_EXTRA_CURRENT.md").write_text(
        "Unexpected approval token APPROVE:unexpected-leak",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "deprecated": False,
                "redacted": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-violation-test")
    )

    assert result["status"] == "violations"
    assert result["violation_count"] >= 2
    violation_ids = {item["id"] for item in result["violations"]}
    assert "stale-approval-credential-leak" in violation_ids
    assert "legacy-blocked-handoff-not-redacted" in violation_ids
    leaked = [
        item
        for item in result["violations"]
        if item["id"] == "stale-approval-credential-leak"
    ]
    assert any(item["artifact"] == "NORTH_STAR_EXTRA_CURRENT.md" for item in leaked)
    result_text = json.dumps(result)
    assert "APPROVE:unexpected-leak" not in result_text
    assert all(
        all("line" not in sample for sample in item.get("sample_lines", []))
        for item in leaked
    )


def test_north_star_stable_artifact_scan_flags_blocker_id_drift(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["bridge_restart_validation", "live_ui_workflow_execution"],
                "blocked_gap_count": 2,
                "blocked_gate_count": 2,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["bridge_restart_validation", "live_recovery_drills"],
                "blocked_gap_count": 2,
                "blocked_gate_count": 2,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": [
                    "bridge_restart_validation",
                    "live_ui_workflow_execution",
                    "live_recovery_drills",
                ],
                "blocked_gap_count": 2,
                "blocked_gate_count": 2,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "blocked_gap_ids": [
                    "bridge_restart_validation",
                    "live_ui_workflow_execution",
                ],
                "blocked_gap_count": 2,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "deprecated": True,
                "redacted": True,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-blocker-drift-test")
    )

    assert result["status"] == "violations"
    violation_ids = {item["id"] for item in result["violations"]}
    assert "stable-blocker-id-mismatch" in violation_ids
    assert "stable-blocker-count-id-mismatch" in violation_ids
    assert "stable-blocker-count-missing" in violation_ids
    id_mismatches = [
        item for item in result["violations"] if item["id"] == "stable-blocker-id-mismatch"
    ]
    assert any(item["artifact"] == "NORTH_STAR_HANDOFF_CURRENT.json" for item in id_mismatches)
    count_mismatches = [
        item
        for item in result["violations"]
        if item["id"] == "stable-blocker-count-id-mismatch"
    ]
    assert any(item["artifact"] == "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json" for item in count_mismatches)
    missing_counts = [
        item
        for item in result["violations"]
        if item["id"] == "stable-blocker-count-missing"
    ]
    assert any(
        item["artifact"] == "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json"
        and item["json_path"] == "blocked_gate_count"
        for item in missing_counts
    )


def test_north_star_stable_artifact_scan_flags_unsatisfied_audit_rows_without_blocker(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_AUDIT_CURRENT.json").write_text(
        json.dumps(
            {
                "prompt_to_artifact_checklist": [
                    {
                        "id": "gate:bridge_restart_validation",
                        "category": "north_star_gate",
                        "requirement": "human-approved restart validation",
                        "satisfied": False,
                        "status": "blocked",
                        "blocker_type": "human_action_required",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(
            tmp_path,
            "north-star-stable-artifact-scan-audit-blocker-metadata-test",
        )
    )

    assert result["status"] == "violations"
    assert result["completion_audit_blocker_metadata_violation_count"] == 1
    assert result["completion_audit_blocker_metadata"]["missing_blocker_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "completion-audit-unsatisfied-blocker-metadata-missing" in violation_ids


def test_north_star_stable_artifact_scan_flags_stale_handoff_after_fresh_preflight(tmp_path):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    handoff = tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json"
    handoff.write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    gate = tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    gate.write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
            }
        ),
        encoding="utf-8",
    )
    legacy = tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json"
    legacy.write_text(
        json.dumps(
            {
                "deprecated": True,
                "redacted": True,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    old_time = 1_770_000_000
    new_time = old_time + 60
    os.utime(handoff, (old_time, old_time))
    os.utime(preflight, (new_time, new_time))
    os.utime(gate, (new_time + 1, new_time + 1))
    os.utime(legacy, (new_time + 1, new_time + 1))

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-fresh-preflight-stale-handoff-test")
    )

    assert result["status"] == "violations"
    assert result["preflight_alignment"]["status"] == "violations"
    assert result["preflight_alignment_violation_count"] >= 1
    alignment_violations = [
        item
        for item in result["violations"]
        if item["id"] == "fresh-preflight-stale-handoff-artifact"
    ]
    assert any(item["artifact"] == "NORTH_STAR_HANDOFF_CURRENT.json" for item in alignment_violations)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Preflight Handoff Alignment" in markdown_text


def test_north_star_stable_artifact_scan_flags_stale_unblock_readiness_after_fresh_preflight(
    tmp_path,
):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_HANDOFF_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
    ]:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "deprecated": True, "redacted": True}),
        encoding="utf-8",
    )
    old_unblock = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    old_unblock.write_text(
        json.dumps(
            {
                **stable_false,
                "artifact_readiness": {
                    "safe_supervision_refresh_command": [
                        "north-star-watch",
                        "--sheet-number",
                        "S2.0",
                        "--revit-version",
                        "2025",
                        "--refresh-approval-preflight",
                        "--publish-current-handoff",
                        "--checks",
                        "1",
                        "--poll",
                        "0",
                    ],
                    "safe_supervision_refresh_powershell": (
                        "revit-operator north-star-watch --sheet-number S2.0 "
                        "--revit-version 2025 --refresh-approval-preflight "
                        "--publish-current-handoff --checks 1 --poll 0"
                    ),
                    "safe_supervision_refresh_read_only": True,
                },
                "blocker_readiness": [],
            }
        ),
        encoding="utf-8",
    )
    old_unblock_md = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
    old_unblock_md.write_text("# stale unblock readiness", encoding="utf-8")
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    preflight_time = 1_770_000_000
    stale_time = preflight_time - 60
    current_time = preflight_time + 10
    os.utime(preflight, (preflight_time, preflight_time))
    for path in tmp_path.glob("NORTH_STAR_*CURRENT*"):
        if path.name == "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json":
            continue
        os.utime(path, (current_time, current_time))
    os.utime(old_unblock, (stale_time, stale_time))
    os.utime(old_unblock_md, (stale_time, stale_time))

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-stale-unblock-test")
    )

    assert result["status"] == "violations"
    stale = [
        item
        for item in result["violations"]
        if item["id"] == "fresh-preflight-stale-handoff-artifact"
    ]
    assert any(item["artifact"] == "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json" for item in stale)
    assert any(item["artifact"] == "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md" for item in stale)


def test_north_star_stable_artifact_scan_flags_future_current_handoff_after_fresh_preflight(
    tmp_path,
):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "blocked_gap_ids": ["live_ui_workflow_execution"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(stable_false),
        encoding="utf-8",
    )
    future = tmp_path / "NORTH_STAR_FUTURE_APPROVAL_CURRENT.json"
    future.write_text(json.dumps(stable_false), encoding="utf-8")
    preflight_time = 1_770_000_000
    os.utime(preflight, (preflight_time, preflight_time))
    os.utime(future, (preflight_time - 60, preflight_time - 60))
    os.utime(
        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        (preflight_time + 10, preflight_time + 10),
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-dynamic-preflight-alignment-test")
    )

    assert result["status"] == "violations"
    assert result["preflight_alignment"]["status"] == "violations"
    stale = [
        item
        for item in result["violations"]
        if item["id"] == "fresh-preflight-stale-handoff-artifact"
    ]
    assert any(item["artifact"] == "NORTH_STAR_FUTURE_APPROVAL_CURRENT.json" for item in stale)


def test_north_star_stable_artifact_scan_does_not_align_known_diagnostic_artifacts(
    tmp_path,
):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "blocked_gap_ids": ["live_ui_workflow_execution"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    gate = tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    gate.write_text(json.dumps(stable_false), encoding="utf-8")
    status = tmp_path / "NORTH_STAR_STATUS_CURRENT.json"
    status.write_text(json.dumps(stable_false), encoding="utf-8")
    scan = tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"
    scan.write_text(
        json.dumps(
            {
                "status": "clean",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )
    preflight_time = 1_770_000_000
    os.utime(preflight, (preflight_time, preflight_time))
    os.utime(status, (preflight_time - 60, preflight_time - 60))
    os.utime(scan, (preflight_time - 60, preflight_time - 60))
    os.utime(gate, (preflight_time + 10, preflight_time + 10))

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-diagnostic-alignment-test")
    )

    assert result["status"] == "clean"
    assert result["preflight_alignment"]["status"] == "aligned"
    stale_artifacts = {
        item["artifact"]
        for item in result["violations"]
        if item["id"] == "fresh-preflight-stale-handoff-artifact"
    }
    assert "NORTH_STAR_STATUS_CURRENT.json" not in stale_artifacts
    assert "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json" not in stale_artifacts


def test_north_star_stable_artifact_scan_accepts_handoff_newer_than_fresh_preflight(tmp_path):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_HANDOFF_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
    ]:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "deprecated": True, "redacted": True}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Legacy Blocked Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
            ]
        ),
        encoding="utf-8",
    )
    preflight_time = 1_770_000_000
    os.utime(preflight, (preflight_time, preflight_time))
    for path in tmp_path.glob("NORTH_STAR_*CURRENT.json"):
        if path.name != "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json":
            os.utime(path, (preflight_time + 10, preflight_time + 10))

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-fresh-preflight-aligned-test")
    )

    assert result["status"] == "clean"
    assert result["preflight_alignment"]["status"] == "aligned"
    assert result["preflight_alignment"]["stale_artifact_count"] == 0
    assert result["preflight_alignment_violation_count"] == 0
    assert result["handoff_reference_violation_count"] == 0


def test_north_star_stable_artifact_scan_flags_broken_handoff_file_references(tmp_path):
    good = tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
    good.write_text(
        json.dumps(
            {
                "status": "blocked",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
            }
        ),
        encoding="utf-8",
    )
    bad_json = tmp_path / "NORTH_STAR_BAD_CURRENT.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    handoff = tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json"
    handoff.write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "stable_files": {
                    "good_gate": str(good),
                    "missing": str(tmp_path / "NORTH_STAR_MISSING_CURRENT.json"),
                    "outside": str(tmp_path.parent / "NORTH_STAR_OUTSIDE_CURRENT.json"),
                    "bad_json": str(bad_json),
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "deprecated": True,
                "redacted": True,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-broken-handoff-refs-test")
    )

    assert result["status"] == "violations"
    assert result["handoff_reference_violation_count"] >= 3
    refs = result["handoff_file_references"]
    assert refs["status"] == "violations"
    assert refs["missing_count"] == 1
    assert refs["outside_sandbox_count"] == 1
    assert refs["unreadable_json_count"] == 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "stable-handoff-reference-missing" in violation_ids
    assert "stable-handoff-reference-outside-sandbox" in violation_ids
    assert "stable-handoff-reference-json-unreadable" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Handoff File References" in markdown_text


def test_north_star_stable_artifact_scan_flags_new_execution_authority_keys(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_waiting_for_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "next_human_options": [
                    {
                        "id": "unsafe-future-option",
                        "may_execute_from_this_option": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    handoff = tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json"
    handoff.write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "stable_files": {
                    "completion_gate": str(
                        tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json"
                    ),
                    "next_human_action": str(
                        tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-broad-exec-key-test")
    )

    assert result["status"] == "violations"
    execution_violations = [
        item
        for item in result["violations"]
        if item["id"] == "stable-artifact-execution-authority"
    ]
    assert execution_violations
    assert any(
        item["artifact"] == "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
        and item["json_path"] == "next_human_options.0.may_execute_from_this_option"
        for item in execution_violations
    )


def test_north_star_stable_artifact_scan_flags_execution_authority_in_new_current_artifact(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_FUTURE_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "future_summary": {
                    "may_execute_from_this_summary": True,
                },
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-dynamic-exec-artifact-test")
    )

    assert result["status"] == "violations"
    execution_violations = [
        item
        for item in result["violations"]
        if item["id"] == "stable-artifact-execution-authority"
    ]
    assert any(
        item["artifact"] == "NORTH_STAR_FUTURE_HANDOFF_CURRENT.json"
        and item["json_path"] == "future_summary.may_execute_from_this_summary"
        and item["value_type"] == "bool"
        for item in execution_violations
    )
    assert any(
        item["artifact"] == "NORTH_STAR_FUTURE_HANDOFF_CURRENT.json"
        for item in result["consistency_summaries"]
    )


def test_north_star_stable_artifact_scan_flags_non_boolean_execution_authority_values(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_FUTURE_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "blocked_gap_ids": ["live_ui_workflow_execution"],
                "blocked_gap_count": 1,
                "blocked_gate_count": 1,
                "may_execute_from_this_result": "false",
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-string-exec-value-test")
    )

    assert result["status"] == "violations"
    execution_violations = [
        item
        for item in result["violations"]
        if item["id"] == "stable-artifact-execution-authority"
    ]
    assert any(
        item["artifact"] == "NORTH_STAR_FUTURE_HANDOFF_CURRENT.json"
        and item["json_path"] == "may_execute_from_this_result"
        and item["value_type"] == "str"
        and "explicitly false or null" in item["reason"]
        for item in execution_violations
    )


def test_north_star_stable_artifact_scan_flags_unsafe_unblock_refresh_command(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json",
    ]:
        payload = (
            {**stable_false, "deprecated": True, "redacted": True}
            if name == "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json"
            else stable_false
        )
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    unsafe_command = [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-path-contains",
        "Structural_Current Working-R25-BIM.rvt",
        "--expected-view-name",
        "STARTING VIEW",
        "--expected-view-type",
        "DrawingSheet",
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
        "--execute",
    ]
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(
            {
                **stable_false,
                "artifact_readiness": {
                    "safe_supervision_refresh_command": unsafe_command,
                    "safe_supervision_refresh_powershell": north_star._powershell_command(
                        unsafe_command
                    ),
                    "safe_supervision_refresh_read_only": True,
                },
                "autonomous_stop": {
                    "active": False,
                    "safe_refresh_command": unsafe_command,
                    "safe_refresh_powershell": north_star._powershell_command(
                        unsafe_command
                    ),
                    "safe_refresh_read_only": True,
                },
                "blocker_readiness": [
                    {
                        "gap_id": "bridge_restart_validation",
                        "safe_supervision_refresh_command": unsafe_command,
                        "safe_supervision_refresh_powershell": north_star._powershell_command(
                            unsafe_command
                        ),
                        "safe_supervision_refresh_read_only": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-stable-artifact-scan-unsafe-refresh-test")
    )

    assert result["status"] == "violations"
    assert result["unblock_refresh_command"]["status"] == "violations"
    assert result["unblock_refresh_command_violation_count"] >= 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "unblock-readiness-refresh-command-forbidden-flag" in violation_ids
    assert "unblock-readiness-refresh-command-powershell-forbidden" in violation_ids
    assert any(
        item.get("json_path") == "autonomous_stop.safe_refresh_command"
        for item in result["violations"]
    )
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Refresh Command" in markdown_text


def test_north_star_stable_artifact_scan_flags_unblock_autonomous_stop_drift(
    tmp_path,
):
    gate = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "may_execute_from_this_result": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(gate),
        encoding="utf-8",
    )
    refresh_fields = _read_only_refresh_fields()
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(
            {
                **gate,
                "artifact_readiness": refresh_fields,
                "blocker_readiness": [],
                "next_human_option_count": 0,
                "next_human_option_ids": [],
                "next_human_option_summaries": [],
                "autonomous_stop": {
                    "active": False,
                    "status": "not_active",
                    "autonomous_progress_available": False,
                    "human_or_real_condition_required": True,
                    "blocked_waiting_for_human_or_real_condition": True,
                    "may_call_update_goal": False,
                    "audit_completion_authorized": False,
                    "may_execute_from_this_result": False,
                    "credential_material_included": False,
                    "completion_gate_required_for_goal_update": True,
                    "allowed_next_command_kinds": ["observation", "read_only_refresh"],
                    "blocked_gap_ids": ["bridge_restart_validation"],
                    "blocked_gap_count": 1,
                    "safe_refresh_command": refresh_fields[
                        "safe_supervision_refresh_command"
                    ],
                    "safe_refresh_powershell": refresh_fields[
                        "safe_supervision_refresh_powershell"
                    ],
                    "safe_refresh_read_only": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Unblock Readiness",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- autonomous_progress_available: `false`",
                "- human_or_real_condition_required: `true`",
                "- blocked_waiting_for_human_or_real_condition: `true`",
                "",
                "## Autonomous Stop",
                "- active: `false`",
                "- status: `not_active`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "- credential_material_included: `false`",
                "- allowed_next_command_kinds: `observation, read_only_refresh`",
                "- safe_refresh_read_only: `true`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-unblock-autonomous-stop-drift-test")
    )

    assert result["status"] == "violations"
    assert result["unblock_autonomous_stop_violation_count"] >= 1
    assert result["unblock_autonomous_stop"]["status"] == "violations"
    violation_ids = {item["id"] for item in result["violations"]}
    assert "unblock-readiness-autonomous-stop-drift" in violation_ids
    assert "unblock-readiness-autonomous-stop-markdown-drift" in violation_ids
    assert result["unblock_autonomous_stop"]["expected_active"] is True
    assert result["unblock_autonomous_stop"]["mismatch_count"] >= 1
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Autonomous Stop" in markdown_text
    assert "unblock_autonomous_stop_violation_count" in markdown_text


def test_north_star_stable_artifact_scan_flags_agent_stop_status_drift(
    tmp_path,
):
    gate = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "may_execute_from_this_result": False,
        "hard_gate_allows_completion": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "unsatisfied_count": 7,
        "safety_guard_violation_count": 0,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(gate),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json").write_text(
        json.dumps(
            {
                **gate,
                "status": "autonomous_progress_available",
                "should_stop_agent": False,
                "agent_stop_reason": None,
                "recommended_agent_action": "continue_with_read_only_safe_next_step",
                "approval_material_included": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_AGENT_STOP_STATUS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Agent Stop Status",
                "",
                "- status: `autonomous_progress_available`",
                "- should_stop_agent: `false`",
                "- agent_stop_reason: `None`",
                "- recommended_agent_action: `continue_with_read_only_safe_next_step`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- hard_gate_allows_completion: `false`",
                "- may_execute_from_this_result: `false`",
                "- blocked_gap_count: `1`",
                "- unsatisfied_count: `7`",
                "- safety_guard_violation_count: `0`",
                "- approval_material_included: `false`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-agent-stop-status-drift-test")
    )

    assert result["status"] == "violations"
    assert result["agent_stop_status_boundary_violation_count"] >= 1
    assert result["agent_stop_status_boundary"]["status"] == "violations"
    assert result["agent_stop_status_boundary"]["expected_status"] == (
        "stop_for_human_or_real_condition"
    )
    assert result["agent_stop_status_boundary"]["expected_should_stop_agent"] is True
    violation_ids = {item["id"] for item in result["violations"]}
    assert "agent-stop-status-boundary-drift" in violation_ids
    assert "agent-stop-status-boundary-markdown-drift" in violation_ids
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Agent Stop Status Boundary" in markdown_text
    assert "agent_stop_status_boundary_violation_count" in markdown_text


def test_north_star_stable_artifact_scan_flags_agent_stop_option_redaction_drift(
    tmp_path,
):
    gate = {
        "read_only": True,
        "generated_at_utc": "2026-05-14T00:00:00Z",
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "may_execute_from_this_result": False,
        "hard_gate_allows_completion": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
        "blocked_gap_ids": ["live_ui_workflow_execution"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "unsatisfied_count": 7,
        "safety_guard_violation_count": 0,
        "completion_actions": {
            "autonomous_progress_available": False,
            "human_or_real_condition_required": True,
        },
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(gate),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json").write_text(
        json.dumps(
            {
                **gate,
                "status": "stop_for_human_or_real_condition",
                "should_stop_agent": True,
                "agent_stop_reason": "human_or_real_condition_required_no_autonomous_progress",
                "recommended_agent_action": "wait_for_human_or_real_condition",
                "approval_material_included": False,
                "approval_material_withheld": True,
                "sanitized_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "gap_ids": ["live_ui_workflow_execution"],
                        "approval_phrase_available_in_source": True,
                        "approval_material_available_in_source": True,
                        "approval_material_included": False,
                        "approval_material_withheld": False,
                        "required_human_approval_phrase_withheld": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_AGENT_STOP_STATUS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Agent Stop Status",
                "",
                "- status: `stop_for_human_or_real_condition`",
                "- should_stop_agent: `true`",
                "- agent_stop_reason: `human_or_real_condition_required_no_autonomous_progress`",
                "- recommended_agent_action: `wait_for_human_or_real_condition`",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- hard_gate_allows_completion: `false`",
                "- may_execute_from_this_result: `false`",
                "- blocked_gap_count: `1`",
                "- unsatisfied_count: `7`",
                "- safety_guard_violation_count: `0`",
                "- approval_material_included: `false`",
                "- approval_material_withheld: `true`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-agent-stop-option-redaction-drift-test")
    )

    assert result["status"] == "violations"
    assert result["agent_stop_status_boundary_violation_count"] >= 1
    assert result["agent_stop_status_boundary"]["inconsistent_withheld_count"] >= 1
    violation_ids = {item["id"] for item in result["violations"]}
    assert "agent-stop-status-option-approval-material-withheld-drift" in violation_ids
    assert "agent-stop-status-option-phrase-withheld-drift" in violation_ids


def test_north_star_unblock_readiness_writes_blocker_packets(tmp_path, monkeypatch):
    stale_preflight = {
        "status": "preflighted",
        "default_sheet_number": "S2.0",
        "expected_context": {
            "revit_version": "2025",
            "expected_title_contains": "24522 St John XXIII",
            "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
            "expected_view_name": "STARTING VIEW",
            "expected_view_type": "DrawingSheet",
        },
        "approval_preflight_freshness": _test_preflight_freshness(
            generated_offset_seconds=-3600,
            ttl_seconds=1,
        ),
    }
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(stale_preflight),
        encoding="utf-8",
    )
    stable_false = {
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_ids": ["bridge_restart_validation", "live_ui_workflow_execution"],
        "blocked_gap_count": 2,
        "blocked_gate_count": 2,
        "may_execute_from_this_result": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
    ]:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    next_human_artifact = {
        **stable_false,
        "option_count": 3,
        "option_ids": [
            "human-restart-or-reload-revit",
            "provide-exact-human-approval-phrase",
            "wait-for-real-recovery-condition",
        ],
        "option_summaries": [
            {
                "id": "human-restart-or-reload-revit",
                "kind": "human_action",
                "may_execute_from_this_option": False,
                "gap_id": "bridge_restart_validation",
                "failed_bridge_checks": ["needs_restart"],
            },
            {
                "id": "provide-exact-human-approval-phrase",
                "kind": "human_approval",
                "may_execute_from_this_option": False,
                "approval_blocker_gap_ids": ["live_ui_workflow_execution"],
                "selected_item_id": "safe-ribbon-view-tab",
                "preflight_fresh_now": False,
                "required_human_approval_phrase_withheld": True,
            },
            {
                "id": "wait-for-real-recovery-condition",
                "kind": "real_condition",
                "may_execute_from_this_option": False,
                "gap_id": "live_recovery_drills",
                "safe_observation_commands": ["recovery-snapshot"],
            },
        ],
    }
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(next_human_artifact),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json").write_text(
        json.dumps({"status": "clean", "violation_count": 0}),
        encoding="utf-8",
    )
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    human_boundary_lines = [
        "- autonomous_progress_available: `false`",
        "- human_or_real_condition_required: `true`",
        "- blocked_waiting_for_human_or_real_condition: `true`",
    ]
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Current North-Star Handoff",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                *human_boundary_lines,
            ]
        ),
        encoding="utf-8",
    )
    for markdown_name, heading in [
        ("NORTH_STAR_WAITING_STATE_CURRENT.md", "# Revit Operator Waiting State"),
        ("NORTH_STAR_BLOCKED_LEDGER_CURRENT.md", "# Revit Operator Blocked Ledger"),
    ]:
        (tmp_path / markdown_name).write_text(
            "\n".join(
                [
                    heading,
                    "",
                    "- completion_allowed: `false`",
                    "- may_call_update_goal: `false`",
                    "- audit_completion_authorized: `false`",
                    "- may_execute_from_this_result: `false`",
                    *human_boundary_lines,
                ]
            ),
            encoding="utf-8",
        )
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next Human Action",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                *human_boundary_lines,
            ]
        ),
        encoding="utf-8",
    )
    no_save = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    no_save.write_text("No save or sync before human restart/reload.", encoding="utf-8")
    coverage = tmp_path / "revit_operator_runs" / "live-coverage" / "ui_execution_coverage_audit.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_text(
        json.dumps({"target_met": False, "surface_counts": {"approved-ui-workflow-step": 0}}),
        encoding="utf-8",
    )

    def fake_gap_evidence(_sandbox):
        return [
            north_star._gap_item(
                id="bridge_restart_validation",
                description=north_star.GAP_DESCRIPTIONS["bridge_restart_validation"],
                satisfied=False,
                evidence={
                    "available": True,
                    "ready_for_continuous_bridge": False,
                    "requires_revit_restart_or_reload": True,
                    "failed_checks": ["needs_restart"],
                    "no_save_checklist_path": str(no_save),
                    "no_save_checklist_present": True,
                },
            ),
            north_star._gap_item(
                id="live_ui_workflow_execution",
                description=north_star.GAP_DESCRIPTIONS["live_ui_workflow_execution"],
                satisfied=False,
                evidence={
                    "artifact": str(coverage),
                    "approved_ui_workflow_step_count": 0,
                    "target_met": False,
                },
            ),
            north_star._gap_item(
                id="supervision_endurance",
                description=north_star.GAP_DESCRIPTIONS["supervision_endurance"],
                satisfied=True,
                evidence={"target_met": True, "total_live_seconds": 14400},
            ),
        ]

    monkeypatch.setattr(north_star, "evaluate_gap_evidence", fake_gap_evidence)

    result = north_star.build_north_star_unblock_readiness(
        TaskJournal(tmp_path, "north-star-unblock-readiness-test")
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked"
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["audit_completion_authorized"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["autonomous_progress_available"] is False
    assert result["human_or_real_condition_required"] is True
    assert result["blocked_waiting_for_human_or_real_condition"] is True
    autonomous_stop = result["autonomous_stop"]
    assert autonomous_stop["active"] is True
    assert autonomous_stop["status"] == "stop_autonomous_progress"
    assert autonomous_stop["allowed_next_command_kinds"] == [
        "observation",
        "read_only_refresh",
    ]
    assert autonomous_stop["may_call_update_goal"] is False
    assert autonomous_stop["audit_completion_authorized"] is False
    assert autonomous_stop["may_execute_from_this_result"] is False
    assert autonomous_stop["credential_material_included"] is False
    assert autonomous_stop["completion_gate_required_for_goal_update"] is True
    assert autonomous_stop["safe_refresh_read_only"] is True
    assert autonomous_stop["blocked_gap_ids"] == [
        "bridge_restart_validation",
        "live_ui_workflow_execution",
    ]
    assert "--execute" not in autonomous_stop["safe_refresh_command"]
    assert "--approval-token" not in autonomous_stop["safe_refresh_command"]
    assert "--approval-tokens-json" not in autonomous_stop["safe_refresh_command"]
    assert "APPROVE:" not in json.dumps(autonomous_stop)
    assert result["blocked_gap_ids"] == [
        "bridge_restart_validation",
        "live_ui_workflow_execution",
    ]
    assert result["next_human_option_count"] == 3
    assert result["next_human_option_ids"] == [
        "human-restart-or-reload-revit",
        "provide-exact-human-approval-phrase",
        "wait-for-real-recovery-condition",
    ]
    option_summaries = {item["id"]: item for item in result["next_human_option_summaries"]}
    assert option_summaries["provide-exact-human-approval-phrase"][
        "selected_item_id"
    ] == "safe-ribbon-view-tab"
    assert "required_human_approval_phrase" not in option_summaries[
        "provide-exact-human-approval-phrase"
    ]
    assert result["artifact_readiness"]["stable_artifact_scan_clean"] is True
    assert result["artifact_readiness"]["stable_handoff_guard_clean"] is True
    assert result["artifact_readiness"]["stable_handoff_guard_violation_count"] == 0
    assert result["artifact_readiness"]["completion_gate_completion_allowed"] is False
    assert result["artifact_readiness"]["completion_gate_may_call_update_goal"] is False
    assert (
        result["artifact_readiness"]["completion_gate_audit_completion_authorized"]
        is False
    )
    assert result["artifact_readiness"]["completion_gate_allows_completion"] is False
    refresh_command = result["artifact_readiness"]["safe_supervision_refresh_command"]
    assert refresh_command[:5] == [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
    ]
    assert "--expected-title-contains" in refresh_command
    assert "24522 St John XXIII" in refresh_command
    assert "--expected-path-contains" in refresh_command
    assert "Structural_Current Working-R25-BIM.rvt" in refresh_command
    assert "--expected-view-name" in refresh_command
    assert "STARTING VIEW" in refresh_command
    assert "--expected-view-type" in refresh_command
    assert "DrawingSheet" in refresh_command
    assert "--refresh-approval-preflight" in refresh_command
    assert "--publish-current-handoff" in refresh_command
    assert "--execute" not in refresh_command
    assert "--approval-token" not in refresh_command
    assert "--approval-tokens-json" not in refresh_command
    assert "north-star-watch" in result["artifact_readiness"]["safe_supervision_refresh_powershell"]
    packets = {item["gap_id"]: item for item in result["blocker_readiness"]}
    bridge = packets["bridge_restart_validation"]
    assert bridge["restart_no_save_checklist_present"] is True
    assert bridge["human_or_real_condition_required"] is True
    assert "bridge-readiness" in bridge["safe_next_commands"]
    assert "ready_for_continuous_bridge" in bridge["completion_evidence_needed"]
    assert bridge["safe_supervision_refresh_command"] == refresh_command
    assert bridge["safe_supervision_refresh_read_only"] is True
    workflow = packets["live_ui_workflow_execution"]
    assert workflow["approval_preflight_status"] == "preflight_stale"
    assert workflow["latest_ui_execution_coverage_present"] is True
    assert "north-star-approval-preflight" in workflow["safe_next_commands"]
    assert "ui_execution_coverage_audit.json" in workflow["completion_evidence_needed"]
    assert workflow["safe_supervision_refresh_command"] == refresh_command
    assert Path(result["stable_path"]) == tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    assert Path(result["stable_markdown_path"]).exists()
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Unblock Readiness" in markdown_text
    assert "- audit_completion_authorized: `false`" in markdown_text
    assert "next_human_option_count: `3`" in markdown_text
    assert "Autonomous Stop" in markdown_text
    assert "active: `true`" in markdown_text
    assert "allowed_next_command_kinds: `observation, read_only_refresh`" in markdown_text
    assert "safe_refresh_read_only: `true`" in markdown_text
    assert "Next Human Options" in markdown_text
    assert "safe-ribbon-view-tab" in markdown_text
    assert "bridge_restart_validation" in markdown_text
    assert "APPROVE:" not in json.dumps(result)


def test_north_star_unblock_readiness_reports_dynamic_handoff_guard_violations(
    tmp_path, monkeypatch
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
    }
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.json").write_text(
        json.dumps(stable_false),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                **stable_false,
                "stable_files": {
                    "missing": str(tmp_path / "NORTH_STAR_MISSING_CURRENT.json"),
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps(
            {
                **stable_false,
                "deprecated": True,
                "redacted": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json").write_text(
        json.dumps({"status": "clean", "violation_count": 0}),
        encoding="utf-8",
    )
    no_save = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    no_save.write_text("No save or sync before human restart/reload.", encoding="utf-8")

    def fake_gap_evidence(_sandbox):
        return [
            north_star._gap_item(
                id="bridge_restart_validation",
                description=north_star.GAP_DESCRIPTIONS["bridge_restart_validation"],
                satisfied=False,
                evidence={
                    "available": True,
                    "ready_for_continuous_bridge": False,
                    "requires_revit_restart_or_reload": True,
                    "no_save_checklist_path": str(no_save),
                    "no_save_checklist_present": True,
                },
            )
        ]

    monkeypatch.setattr(north_star, "evaluate_gap_evidence", fake_gap_evidence)

    result = north_star.build_north_star_unblock_readiness(
        TaskJournal(tmp_path, "north-star-unblock-readiness-handoff-guard-test")
    )

    assert result["status"] == "blocked"
    readiness = result["artifact_readiness"]
    assert readiness["stable_artifact_scan_clean"] is True
    assert readiness["stable_handoff_guard_clean"] is False
    assert readiness["stable_handoff_guard_violation_count"] >= 1
    assert "stable-handoff-reference-missing" in readiness["stable_handoff_guard_violation_ids"]


def test_north_star_unblock_readiness_filters_own_stale_outputs_while_rewriting(
    tmp_path, monkeypatch
):
    preflight = tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "blocked_gap_ids": ["bridge_restart_validation"],
        "blocked_gap_count": 1,
        "blocked_gate_count": 1,
        "may_execute_from_this_result": False,
        "autonomous_progress_available": False,
        "human_or_real_condition_required": True,
        "blocked_waiting_for_human_or_real_condition": True,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
        "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
    ]:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "deprecated": True, "redacted": True}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json").write_text(
        json.dumps({"status": "clean", "violation_count": 0}),
        encoding="utf-8",
    )
    old_unblock = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json"
    old_unblock.write_text(
        json.dumps(
            {
                **stable_false,
                "artifact_readiness": _read_only_refresh_fields(),
                "blocker_readiness": [],
            }
        ),
        encoding="utf-8",
    )
    old_unblock_md = tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.md"
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    human_boundary_lines = [
        "- autonomous_progress_available: `false`",
        "- human_or_real_condition_required: `true`",
        "- blocked_waiting_for_human_or_real_condition: `true`",
    ]
    old_unblock_md.write_text(
        "\n".join(
            [
                "# stale unblock readiness",
                "",
                *human_boundary_lines,
            ]
        ),
        encoding="utf-8",
    )
    for markdown_name, heading in [
        ("NORTH_STAR_HANDOFF_CURRENT.md", "# Revit Operator Current North-Star Handoff"),
        ("NORTH_STAR_WAITING_STATE_CURRENT.md", "# Revit Operator Waiting State"),
        ("NORTH_STAR_BLOCKED_LEDGER_CURRENT.md", "# Revit Operator Blocked Ledger"),
        ("NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md", "# Revit Operator Next Human Action"),
    ]:
        (tmp_path / markdown_name).write_text(
            "\n".join(
                [
                    heading,
                    "",
                    "- completion_allowed: `false`",
                    "- may_call_update_goal: `false`",
                    "- audit_completion_authorized: `false`",
                    "- may_execute_from_this_result: `false`",
                    *human_boundary_lines,
                ]
            ),
            encoding="utf-8",
        )
    no_save = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    no_save.write_text("No save or sync before human restart/reload.", encoding="utf-8")

    preflight_time = 1_770_000_000
    stale_time = preflight_time - 60
    current_time = preflight_time + 10
    os.utime(preflight, (preflight_time, preflight_time))
    for path in tmp_path.glob("NORTH_STAR_*CURRENT*"):
        if path.name == "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json":
            continue
        os.utime(path, (current_time, current_time))
    os.utime(old_unblock, (stale_time, stale_time))
    os.utime(old_unblock_md, (stale_time, stale_time))

    def fake_gap_evidence(_sandbox):
        return [
            north_star._gap_item(
                id="bridge_restart_validation",
                description=north_star.GAP_DESCRIPTIONS["bridge_restart_validation"],
                satisfied=False,
                evidence={
                    "available": True,
                    "ready_for_continuous_bridge": False,
                    "requires_revit_restart_or_reload": True,
                    "no_save_checklist_path": str(no_save),
                    "no_save_checklist_present": True,
                },
            )
        ]

    monkeypatch.setattr(north_star, "evaluate_gap_evidence", fake_gap_evidence)

    result = north_star.build_north_star_unblock_readiness(
        TaskJournal(tmp_path, "north-star-unblock-readiness-self-refresh-test")
    )

    readiness = result["artifact_readiness"]
    assert readiness["approval_preflight_fresh"] is True
    assert readiness["stable_artifact_scan_clean"] is True
    assert readiness["stable_handoff_guard_clean"] is True
    assert readiness["stable_handoff_guard_violation_count"] == 0
    assert (
        "fresh-preflight-stale-handoff-artifact"
        not in readiness["stable_handoff_guard_violation_ids"]
    )
    assert Path(result["stable_path"]) == old_unblock
    assert old_unblock.stat().st_mtime > preflight_time
    saved = json.loads(old_unblock.read_text(encoding="utf-8"))
    assert saved["artifact_readiness"]["stable_handoff_guard_violation_count"] == 0


def test_north_star_unblock_readiness_reports_markdown_coverage_guard_violations(
    tmp_path, monkeypatch
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    stable_false = {
        "status": "blocked",
        "north_star_complete": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "blocked_gap_ids": [
            "bridge_restart_validation",
            "live_ui_workflow_execution",
            "live_uia_ribbon_context_execution",
        ],
        "blocked_gap_count": 3,
        "blocked_gate_count": 3,
        "may_execute_from_this_result": False,
    }
    for name in [
        "NORTH_STAR_COMPLETION_GATE_CURRENT.json",
        "NORTH_STAR_BLOCKED_LEDGER_CURRENT.json",
        "NORTH_STAR_WAITING_STATE_CURRENT.json",
    ]:
        (tmp_path / name).write_text(json.dumps(stable_false), encoding="utf-8")
    (tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json").write_text(
        json.dumps(
            {
                **stable_false,
                "next_human_options": [
                    {
                        "id": "provide-exact-human-approval-phrase",
                        "kind": "human_approval",
                        "may_execute_from_this_option": False,
                        "gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "approval_blocker_gap_ids": [
                            "live_ui_workflow_execution",
                            "live_uia_ribbon_context_execution",
                        ],
                        "selected_item_gap_ids": [
                            "live_uia_ribbon_context_execution",
                        ],
                        "remaining_approval_gap_ids_after_selected_item": [
                            "live_ui_workflow_execution",
                        ],
                        "selected_item_covers_all_approval_blockers": False,
                        "approval_coverage_note": (
                            "The selected approval phrase covers only the selected item gaps."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md").write_text(
        "# Gate\n\n- approval_coverage_status: `clean`\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "deprecated": True, "redacted": True}),
        encoding="utf-8",
    )
    stable_refs = {
        path.stem.lower(): str(path)
        for path in sorted(tmp_path.glob("NORTH_STAR_*CURRENT*"))
        if path.is_file()
    }
    (tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json").write_text(
        json.dumps({**stable_false, "stable_files": stable_refs}),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json").write_text(
        json.dumps({"status": "clean", "violation_count": 0}),
        encoding="utf-8",
    )
    no_save = tmp_path / "NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md"
    no_save.write_text("No save or sync before human restart/reload.", encoding="utf-8")

    def fake_gap_evidence(_sandbox):
        return [
            north_star._gap_item(
                id="bridge_restart_validation",
                description=north_star.GAP_DESCRIPTIONS["bridge_restart_validation"],
                satisfied=False,
                evidence={
                    "available": True,
                    "ready_for_continuous_bridge": False,
                    "requires_revit_restart_or_reload": True,
                    "no_save_checklist_path": str(no_save),
                    "no_save_checklist_present": True,
                },
            )
        ]

    monkeypatch.setattr(north_star, "evaluate_gap_evidence", fake_gap_evidence)

    result = north_star.build_north_star_unblock_readiness(
        TaskJournal(
            tmp_path,
            "north-star-unblock-readiness-markdown-coverage-guard-test",
        )
    )

    readiness = result["artifact_readiness"]
    assert readiness["stable_artifact_scan_clean"] is True
    assert readiness["stable_handoff_guard_clean"] is False
    assert (
        "completion-gate-markdown-approval-coverage-drift"
        in readiness["stable_handoff_guard_violation_ids"]
    )


def test_cli_north_star_unblock_readiness_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-unblock-readiness-cli-test",
            "north-star-unblock-readiness",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["completion_allowed"] is False
    assert output["may_call_update_goal"] is False
    assert output["may_execute_from_this_result"] is False
    assert output["autonomous_stop"]["may_execute_from_this_result"] is False
    assert output["autonomous_stop"]["allowed_next_command_kinds"] == [
        "observation",
        "read_only_refresh",
    ]
    assert Path(output["stable_path"]).is_relative_to(tmp_path)


def test_north_star_completion_gate_flags_status_summary_execution_leaks_even_when_fresh(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.json").write_text(
        json.dumps(
            {
                "approval_candidates": [
                    {
                        "id": "unsafe-status-candidate",
                        "command": ["ribbon-action", "--execute", "--approval-token"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.md").write_text(
        "dry_run_command: `ribbon-action --execute --approval-token APPROVE:leaked`\n",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "status-summary-execute-flag-leak" in violation_ids
    assert "status-summary-approval-token-flag-leak" in violation_ids
    assert "status-summary-approval-token-leak" in violation_ids
    assert "stale-approval-credential-leak" not in violation_ids
    followups = north_star._completion_gate_safety_guard_followup_actions(violations)
    assert followups == [
        {
            "id": "repair-execution-authority-artifacts",
            "action": (
                "Regenerate the current handoff and inspect the named artifact; no "
                "stable handoff artifact may claim execution authority."
            ),
            "commands": [
                "north-star-current-handoff",
                "north-star-completion-gate",
            ],
            "freshness_rule": (
                "Do not execute UI/model actions while any completion-gate safety "
                "violation is present."
            ),
        }
    ]


def test_north_star_stable_artifact_scan_flags_status_stop_markdown_drift(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.json").write_text(
        json.dumps(
            {
                "success": True,
                "read_only": True,
                "generated_at_utc": "2026-05-14T00:00:00Z",
                "status": "not_complete",
                "north_star_complete": False,
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "agent_stop_status": "stop_for_human_or_real_condition",
                "should_stop_agent": True,
                "agent_stop_reason": (
                    "human_or_real_condition_required_no_autonomous_progress"
                ),
                "recommended_agent_action": "wait_for_human_or_real_condition",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_STATUS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Status",
                "",
                "- may_execute_from_this_result: `false`",
                "- agent_stop_status: `stop_for_human_or_real_condition`",
                "- agent_stop_reason: "
                "`human_or_real_condition_required_no_autonomous_progress`",
                "- recommended_agent_action: `wait_for_human_or_real_condition`",
            ]
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_stable_artifact_scan(
        TaskJournal(tmp_path, "north-star-status-stop-markdown-drift-test")
    )

    ids = {item["id"] for item in result["violations"]}
    assert result["status"] == "violations"
    assert result["status_summary_violation_count"] >= 1
    assert "status-summary-stop-boundary-markdown-drift" in ids
    followups = north_star._completion_gate_safety_guard_followup_actions(
        result["violations"]
    )
    assert any(item["id"] == "repair-stable-handoff-artifacts" for item in followups)


def test_north_star_completion_gate_routes_human_gate_approval_gap_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked_human_or_real_condition",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "audit_completion_authorized": False,
                "may_execute_from_this_result": False,
                "approval_items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "gap_ids": ["live_uia_ribbon_context_execution"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Human Gate Packet",
                "",
                "- completion_allowed: `false`",
                "- may_call_update_goal: `false`",
                "- audit_completion_authorized: `false`",
                "- may_execute_from_this_result: `false`",
                "",
                "## Approval Items",
                "- `safe-ribbon-view-tab`: `approved` / `low`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "human-gate-packet-markdown-approval-gap-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(violations)
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_completion_gate_routes_ready_approvals_approval_gap_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "ready_items_available",
                "read_only": True,
                "ready_approval_count": 1,
                "withheld_approval_count": 0,
                "may_execute_from_this_result": False,
                "ready_items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "gap_ids": ["live_uia_ribbon_context_execution"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Ready North-Star Approvals",
                "",
                "- may_execute_from_this_result: `false`",
                "",
                "## Ready Items",
                "- `safe-ribbon-view-tab`: Select the Revit View ribbon tab only.",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "ready-approvals-markdown-approval-gap-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(violations)
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_completion_gate_routes_next_approval_approval_gap_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "approval_ready",
                "read_only": True,
                "may_execute_from_this_result": False,
                "selected_item": {
                    "id": "safe-ribbon-view-tab",
                    "gap_ids": ["live_uia_ribbon_context_execution"],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator Next North-Star Approval",
                "",
                "- may_execute_from_this_result: `false`",
                "",
                "## Selected Item",
                "- `safe-ribbon-view-tab`: Select the Revit View ribbon tab only.",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "next-approval-markdown-approval-gap-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(violations)
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_completion_gate_routes_waiting_state_approval_gap_drift_to_stable_handoff_repair(
    tmp_path,
):
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "approval_ready",
                "read_only": True,
                "may_execute_from_this_result": False,
                "selected_item": {
                    "id": "safe-ribbon-view-tab",
                    "gap_ids": ["live_uia_ribbon_context_execution"],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "waiting_for_human_or_real_condition",
                "next_approval_item_id": "safe-ribbon-view-tab",
                "next_approval_gap_ids": ["live_uia_ribbon_context_execution"],
                "required_human_approval_phrase": (
                    "I approve safe-ribbon-view-tab with token APPROVE:test"
                ),
                "may_execute_from_waiting_state": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_WAITING_STATE_CURRENT.md").write_text(
        "\n".join(
            [
                "# Revit Operator North-Star Waiting State",
                "",
                "- may_execute_from_waiting_state: `false`",
                "",
                "## Required Human Approval Phrase",
                "`I approve safe-ribbon-view-tab with token APPROVE:test`",
                "- next_approval_item_id: `safe-ribbon-view-tab`",
            ]
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "waiting-state-approval-gap-markdown-drift" in violation_ids
    followup_ids = {
        item["id"]
        for item in north_star._completion_gate_safety_guard_followup_actions(violations)
    }
    assert "repair-stable-handoff-artifacts" in followup_ids
    assert "repair-execution-authority-artifacts" not in followup_ids


def test_north_star_completion_gate_allows_approval_credentials_when_preflight_fresh(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_NEXT_APPROVAL_CURRENT.md").write_text(
        "Required human approval phrase: `I approve safe-ribbon-view-tab with token APPROVE:fresh`\n"
        "Execute only after explicit approval: `revit-operator ribbon-action --execute`\n",
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    assert not [item for item in violations if item["id"] == "stale-approval-credential-leak"]


def test_north_star_completion_gate_flags_unsafe_unblock_refresh_command(tmp_path):
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "preflighted",
                "default_sheet_number": "S2.0",
                "expected_context": {
                    "revit_version": "2025",
                    "expected_title_contains": "24522 St John XXIII",
                    "expected_path_contains": "Structural_Current Working-R25-BIM.rvt",
                    "expected_view_name": "STARTING VIEW",
                    "expected_view_type": "DrawingSheet",
                },
                "approval_preflight_freshness": _test_preflight_freshness(),
            }
        ),
        encoding="utf-8",
    )
    unsafe_command = [
        "north-star-watch",
        "--sheet-number",
        "S2.0",
        "--revit-version",
        "2025",
        "--expected-title-contains",
        "24522 St John XXIII",
        "--expected-path-contains",
        "Structural_Current Working-R25-BIM.rvt",
        "--expected-view-name",
        "STARTING VIEW",
        "--expected-view-type",
        "DrawingSheet",
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
        "--approval-token",
        "APPROVE:unsafe",
    ]
    (tmp_path / "NORTH_STAR_UNBLOCK_READINESS_CURRENT.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "completion_allowed": False,
                "may_call_update_goal": False,
                "may_execute_from_this_result": False,
                "artifact_readiness": {
                    "safe_supervision_refresh_command": unsafe_command,
                    "safe_supervision_refresh_powershell": north_star._powershell_command(
                        unsafe_command
                    ),
                    "safe_supervision_refresh_read_only": True,
                },
                "blocker_readiness": [],
            }
        ),
        encoding="utf-8",
    )

    violations = north_star._completion_gate_safety_guard_violations(
        sandbox=tmp_path,
        waiting_state_summary={"available": True, "may_execute_from_waiting_state": False},
        next_approval_summary={"available": True, "may_execute_from_this_result": False},
        next_human_action_summary={
            "available": True,
            "may_execute_from_this_result": False,
            "execution_authority_violation": False,
        },
        supervised_command_packet={
            "available": False,
            "may_execute_from_this_packet": False,
            "execution_command_included": False,
        },
    )

    violation_ids = {item["id"] for item in violations}
    assert "unblock-readiness-refresh-command-forbidden-flag" in violation_ids
    assert "unblock-readiness-refresh-command-token-leak" in violation_ids
    assert "unblock-readiness-refresh-command-powershell-forbidden" in violation_ids


def test_cli_north_star_completion_gate_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-completion-gate-cli-test",
            "north-star-completion-gate",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["completion_allowed"] is False
    assert output["may_call_update_goal"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


@pytest.mark.parametrize(
    "command",
    [
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
    ],
)
def test_cli_approval_sensitive_stdout_redacts_approval_material(command):
    class Args:
        pass

    args = Args()
    args.command = command

    result = {
        "success": True,
        "waiting_state_summary": {
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:secret"
            ),
            "next_approval_token": "APPROVE:secret",
        },
        "next_approval_summary": {
            "verify_command": ["north-star-approval-verify", "--approval-token", "APPROVE:secret"],
            "approval_token_present": True,
        },
    }

    redacted = cli._stdout_result(args, result)
    redacted_text = json.dumps(redacted)
    original_text = json.dumps(result)

    assert "APPROVE:secret" in original_text
    assert "I approve" in original_text
    assert "APPROVE:secret" not in redacted_text
    assert "I approve" not in redacted_text
    assert redacted["next_approval_summary"]["approval_token_present"] is True


@pytest.mark.parametrize("command", ["run-ui-workflow", "replay-workflow"])
def test_cli_help_does_not_emit_token_shaped_approval_examples(command, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--approval-tokens-json" in help_text
    assert "<approval-token>" in help_text
    assert "APPROVE:" not in help_text


def test_cli_exception_output_redacts_approval_material(monkeypatch, capsys):
    def fail_dispatch(_args):
        raise ValueError(
            "Bad phrase I approve safe-ribbon-view-tab with token APPROVE:secret"
        )

    monkeypatch.setattr(cli, "dispatch", fail_dispatch)

    code = cli.main(["health"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "APPROVE:secret" not in captured.err
    assert "I approve" not in captured.err
    assert "<redacted approval phrase>" in captured.err
    assert "<redacted approval token>" in captured.err


def test_cli_north_star_stable_artifact_scan_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-stable-artifact-scan-cli-test",
            "north-star-stable-artifact-scan",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "clean"
    assert output["completion_allowed"] is False
    assert output["may_call_update_goal"] is False
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).exists()
    assert Path(output["markdown_path"]).exists()
    assert Path(output["stable_path"]) == tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json"
    assert Path(output["stable_markdown_path"]) == (
        tmp_path / "NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.md"
    )
    assert Path(output["stable_path"]).exists()
    assert "Stable Artifact Scan" in Path(output["markdown_path"]).read_text(encoding="utf-8")


def test_cli_north_star_refresh_sequence_dispatches_readonly_builder(
    tmp_path, capsys, monkeypatch
):
    captured = {}

    def fake_refresh_sequence(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        captured.update(
            {
                "task_id": journal.task_id,
                "repo_root": repo_root,
                "command_names": command_names,
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            }
        )
        path = journal.run_dir / "north_star_refresh_sequence.json"
        markdown = journal.run_dir / "north_star_refresh_sequence.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# refresh sequence", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "sequence_order": [
                "north-star-current-handoff",
                "north-star-stable-artifact-scan",
                "north-star-completion-gate",
                "north-star-stable-artifact-scan",
                "north-star-completion-gate",
            ],
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_refresh_sequence", fake_refresh_sequence)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-refresh-sequence-cli-test",
            "north-star-refresh-sequence",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-path-contains",
            "Structural_Current Working-R25-BIM",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["may_execute_from_this_result"] is False
    assert output["sequence_order"] == [
        "north-star-current-handoff",
        "north-star-stable-artifact-scan",
        "north-star-completion-gate",
        "north-star-stable-artifact-scan",
        "north-star-completion-gate",
    ]
    assert captured["task_id"] == "north-star-refresh-sequence-cli-test"
    assert captured["default_sheet_number"] == "S2.0"
    assert captured["revit_version"] == "2025"
    assert captured["expected_title_contains"] == "24522 St John XXIII"
    assert captured["expected_path_contains"] == "Structural_Current Working-R25-BIM"
    assert captured["expected_view_name"] == "STARTING VIEW"
    assert captured["expected_view_type"] == "DrawingSheet"
    assert "north-star-refresh-sequence" in captured["command_names"]
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_blocked_ledger_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-blocked-ledger-cli-test",
            "north-star-blocked-ledger",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "blocked"
    assert output["entry_count"] > 0
    assert output["may_call_update_goal"] is False
    assert output["audit_completion_authorized"] is False
    assert output["blocked_gap_count"] == output["entry_count"]
    assert output["blocked_gate_count"] == output["entry_count"]
    assert sorted(output["blocked_gap_ids"]) == sorted(entry["gap_id"] for entry in output["entries"])
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_next_human_action_writes_readonly_stable_card(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-next-human-action-cli-test",
            "north-star-next-human-action",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["may_execute_from_this_result"] is False
    assert output["completion_allowed"] is False
    assert output["may_call_update_goal"] is False
    assert output["audit_completion_authorized"] is False
    assert output["blocked_gap_count"] == len(output["blocked_gap_ids"])
    assert output["blocked_gate_count"] == output["blocked_gap_count"]
    assert output["completion_gate"]["blocked_gap_count"] == output["blocked_gap_count"]
    assert output["completion_gate"]["blocked_gate_count"] == output["blocked_gate_count"]
    assert output["completion_gate"]["audit_completion_authorized"] is False
    assert output["option_count"] == len(output["next_human_options"])
    assert output["option_ids"] == [
        item["id"] for item in output["next_human_options"] if item.get("id")
    ]
    assert [item["id"] for item in output["option_summaries"]] == output["option_ids"]
    summaries = {item["id"]: item for item in output["option_summaries"]}
    restart_summary = summaries.get("human-restart-or-reload-revit")
    if restart_summary:
        assert restart_summary["post_action_resume_command_present"] is True
        assert restart_summary["post_action_resume_command"][0] == (
            "north-star-resume-check"
        )
        assert "north-star-resume-check" in restart_summary[
            "post_action_resume_powershell"
        ]
        assert "--execute" not in restart_summary["post_action_resume_powershell"]
        assert "--approval-token" not in restart_summary[
            "post_action_resume_powershell"
        ]
    assert Path(output["stable_files"]["next_human_action"]) == (
        tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
    )
    assert Path(output["stable_files"]["next_human_action"]).exists()
    assert Path(output["stable_files"]["next_human_action_markdown"]) == (
        tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md"
    )
    assert Path(output["stable_files"]["next_human_action_markdown"]).exists()


def test_cli_north_star_human_unblock_brief_dispatches_sanitized_builder(
    tmp_path, capsys, monkeypatch
):
    captured = {}

    def fake_unblock_brief(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        captured.update(
            {
                "task_id": journal.task_id,
                "command_names": command_names,
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            }
        )
        path = journal.run_dir / "north_star_human_unblock_brief.json"
        markdown = journal.run_dir / "north_star_human_unblock_brief.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# brief", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "blocked_waiting_for_human_or_real_condition",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "approval_material_included": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_human_unblock_brief", fake_unblock_brief)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-human-unblock-brief-cli-test",
            "north-star-human-unblock-brief",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-path-contains",
            "Structural_Current Working-R25-BIM",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["approval_material_included"] is False
    assert output["may_execute_from_this_result"] is False
    assert captured["task_id"] == "north-star-human-unblock-brief-cli-test"
    assert captured["default_sheet_number"] == "S2.0"
    assert captured["revit_version"] == "2025"
    assert captured["expected_title_contains"] == "24522 St John XXIII"
    assert captured["expected_path_contains"] == "Structural_Current Working-R25-BIM"
    assert captured["expected_view_name"] == "STARTING VIEW"
    assert captured["expected_view_type"] == "DrawingSheet"
    assert "north-star-human-unblock-brief" in captured["command_names"]
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_agent_stop_status_dispatches_readonly_builder(
    tmp_path, capsys, monkeypatch
):
    captured = {}

    def fake_agent_stop_status(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        captured.update(
            {
                "task_id": journal.task_id,
                "command_names": command_names,
                "default_sheet_number": default_sheet_number,
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            }
        )
        path = journal.run_dir / "north_star_agent_stop_status.json"
        markdown = journal.run_dir / "north_star_agent_stop_status.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# stop", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "stop_for_human_or_real_condition",
            "should_stop_agent": True,
            "agent_stop_reason": "human_or_real_condition_required_no_autonomous_progress",
            "completion_allowed": False,
            "may_call_update_goal": False,
            "audit_completion_authorized": False,
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_agent_stop_status", fake_agent_stop_status)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-agent-stop-status-cli-test",
            "north-star-agent-stop-status",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-path-contains",
            "Structural_Current Working-R25-BIM",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["should_stop_agent"] is True
    assert output["may_execute_from_this_result"] is False
    assert captured["task_id"] == "north-star-agent-stop-status-cli-test"
    assert captured["default_sheet_number"] == "S2.0"
    assert captured["revit_version"] == "2025"
    assert captured["expected_title_contains"] == "24522 St John XXIII"
    assert captured["expected_path_contains"] == "Structural_Current Working-R25-BIM"
    assert captured["expected_view_name"] == "STARTING VIEW"
    assert captured["expected_view_type"] == "DrawingSheet"
    assert "north-star-agent-stop-status" in captured["command_names"]
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_current_handoff_writes_stable_files(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-current-handoff-cli-test",
            "north-star-current-handoff",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "blocked"
    assert output["may_call_update_goal"] is False
    assert output["audit_completion_authorized"] is False
    assert output["blocked_gap_count"] == len(output["blocked_gap_ids"])
    assert output["waiting_state"]["blocked_gap_count"] == len(output["blocked_gap_ids"])
    assert Path(output["stable_files"]["status_json"]) == tmp_path / "NORTH_STAR_STATUS_CURRENT.json"
    assert Path(output["stable_files"]["status_json"]).exists()
    assert (
        Path(output["stable_files"]["status_markdown"])
        == tmp_path / "NORTH_STAR_STATUS_CURRENT.md"
    )
    assert Path(output["stable_files"]["status_markdown"]).exists()
    status_summary = json.loads(Path(output["stable_files"]["status_json"]).read_text(encoding="utf-8"))
    assert status_summary["blocked_gap_count"] == output["blocked_gap_count"]
    assert status_summary["audit_completion_authorized"] is False
    assert all(item["approval_token"] is None for item in status_summary["approval_candidates"])
    assert all("--execute" not in item["command"] for item in status_summary["approval_candidates"])
    assert (
        Path(output["stable_files"]["completion_gate_markdown"])
        == tmp_path / "NORTH_STAR_COMPLETION_GATE_CURRENT.md"
    )
    assert Path(output["stable_files"]["completion_gate_markdown"]).exists()
    assert Path(output["stable_files"]["audit_json"]) == tmp_path / "NORTH_STAR_AUDIT_CURRENT.json"
    assert Path(output["stable_files"]["audit_json"]).exists()
    audit_summary = json.loads(Path(output["stable_files"]["audit_json"]).read_text(encoding="utf-8"))
    assert audit_summary["audit_completion_authorized"] is False
    assert Path(output["stable_files"]["audit_markdown"]) == tmp_path / "NORTH_STAR_AUDIT_CURRENT.md"
    assert Path(output["stable_files"]["audit_markdown"]).exists()
    assert Path(output["stable_files"]["handoff_json"]) == tmp_path / "NORTH_STAR_HANDOFF_CURRENT.json"
    assert Path(output["stable_files"]["handoff_json"]).exists()
    assert Path(output["stable_files"]["handoff_markdown"]) == tmp_path / "NORTH_STAR_HANDOFF_CURRENT.md"
    assert Path(output["stable_files"]["handoff_markdown"]).exists()
    assert (
        Path(output["stable_files"]["next_human_action"])
        == tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json"
    )
    assert Path(output["stable_files"]["next_human_action"]).exists()
    assert (
        Path(output["stable_files"]["next_human_action_markdown"])
        == tmp_path / "NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md"
    )
    assert Path(output["stable_files"]["next_human_action_markdown"]).exists()
    assert Path(output["stable_files"]["human_gate_packet"]) == tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json"
    assert Path(output["stable_files"]["human_gate_packet"]).exists()
    assert (
        Path(output["stable_files"]["human_gate_packet_markdown"])
        == tmp_path / "NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md"
    )
    assert Path(output["stable_files"]["human_gate_packet_markdown"]).exists()
    assert (
        Path(output["stable_files"]["post_human_resume_script"])
        == tmp_path / "NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1"
    )
    assert Path(output["stable_files"]["post_human_resume_script"]).exists()
    assert (
        Path(output["stable_files"]["ready_approvals_markdown"])
        == tmp_path / "NORTH_STAR_READY_APPROVALS_CURRENT.md"
    )
    assert Path(output["stable_files"]["ready_approvals_markdown"]).exists()
    assert (
        Path(output["stable_files"]["transport_safety_matrix"])
        == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    )
    assert Path(output["stable_files"]["transport_safety_matrix"]).exists()
    assert (
        Path(output["stable_files"]["transport_safety_matrix_markdown"])
        == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md"
    )
    assert Path(output["stable_files"]["transport_safety_matrix_markdown"]).exists()
    transport_matrix = json.loads(
        Path(output["stable_files"]["transport_safety_matrix"]).read_text(
            encoding="utf-8"
        )
    )
    assert transport_matrix["status"] == "clean"
    assert transport_matrix["direct_approval_marker_count"] == 0


def test_cli_north_star_status_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-status-cli-test",
            "north-star-status",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["north_star_complete"] is False
    assert output["completion_allowed"] is False
    assert output["may_call_update_goal"] is False
    assert output["completion_gate_required"] is True
    assert output["completion_gate_command"] == ["north-star-completion-gate"]
    assert output["may_execute_from_this_result"] is False
    assert output["agent_stop_status"] == "autonomous_progress_available"
    assert output["should_stop_agent"] is False
    assert output["agent_stop_reason"] is None
    assert (
        output["recommended_agent_action"]
        == "continue_with_read_only_safe_next_step"
    )
    assert output["completion_rule"].startswith("Do not call update_goal from north-star-status alone")
    assert output["remaining_gap_count"] == len(output["remaining_gaps"])
    assert output["blocked_gap_count"] == output["blocker_summary"]["blocked_gap_count"]
    assert output["blocked_gap_ids"] == output["blocker_summary"]["blocked_gap_ids"]
    assert output["autonomous_progress_available"] is output["completion_actions"][
        "autonomous_progress_available"
    ]
    assert output["human_or_real_condition_required"] is output["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert all(item["approval_token"] is None for item in output["approval_candidates"])
    assert all(item["approval_token_withheld"] is True for item in output["approval_candidates"])
    assert all("--execute" not in item["command"] for item in output["approval_candidates"])
    assert all("--approval-token" not in item["command"] for item in output["approval_candidates"])
    assert all(
        "--approval-tokens-json" not in item["command"]
        for item in output["approval_candidates"]
    )
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()
    status_text = Path(output["path"]).read_text(encoding="utf-8")
    status_markdown = Path(output["markdown_path"]).read_text(encoding="utf-8")
    assert "APPROVE:" not in status_text
    assert "I approve " not in status_text
    assert "Execute only after explicit approval" not in status_text
    assert "APPROVE:" not in status_markdown
    assert "--execute" not in status_markdown
    assert "blocked_gate_count:" in status_markdown
    assert "completion_allowed: `false`" in status_markdown
    assert "audit_completion_authorized: `false`" in status_markdown
    assert "may_execute_from_this_result: `false`" in status_markdown
    assert "agent_stop_status: `autonomous_progress_available`" in status_markdown
    assert "should_stop_agent: `false`" in status_markdown
    assert (
        "recommended_agent_action: `continue_with_read_only_safe_next_step`"
        in status_markdown
    )


def test_cli_north_star_approval_plan_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-plan-cli-test",
            "north-star-approval-plan",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["default_sheet_number"] == "S2.0"
    assert output["blocker_summary"]["blocked_gap_count"] == 5
    assert output["blocked_gap_count"] == output["blocker_summary"]["blocked_gap_count"]
    assert output["blocked_gate_count"] == output["blocked_gap_count"]
    assert output["blocked_gap_ids"] == sorted(output["blocker_summary"]["blocked_gap_ids"])
    assert output["completion_actions"]["human_or_real_condition_required"] is True
    assert output["human_or_real_condition_required"] is True
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_preflight_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_preflight(
        journal,
        *,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
        run_preflight,
    ):
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        assert callable(run_preflight)
        path = journal.run_dir / "north_star_approval_preflight.json"
        path.write_text("{}", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "preflighted",
            "approval_item_count": 1,
            "preflight_passed_count": 1,
            "unsafe_preflight_count": 0,
            "path": str(path),
        }

    monkeypatch.setattr(cli, "build_north_star_approval_preflight", fake_preflight)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-preflight-cli-test",
            "north-star-approval-preflight",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "preflighted"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_ready_approvals_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_ready_approvals(journal, *, default_sheet_number):
        assert default_sheet_number == "S2.0"
        path = journal.run_dir / "north_star_ready_approvals.json"
        markdown = journal.run_dir / "north_star_ready_approvals.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# ready", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "ready_items_available",
            "ready_approval_count": 1,
            "withheld_approval_count": 1,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_ready_approvals", fake_ready_approvals)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-ready-approvals-cli-test",
            "north-star-ready-approvals",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "ready_items_available"
    assert output["ready_approval_count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_next_approval_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_next_approval(journal, *, default_sheet_number):
        assert default_sheet_number == "S2.0"
        path = journal.run_dir / "north_star_next_approval.json"
        markdown = journal.run_dir / "north_star_next_approval.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# next", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "approval_ready",
            "selected_item": {"id": "safe-ribbon-view-tab"},
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_next_approval", fake_next_approval)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-next-approval-cli-test",
            "north-star-next-approval",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "approval_ready"
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_waiting_state_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_waiting_state(
        journal,
        *,
        repo_root,
        command_names,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        assert repo_root.exists()
        assert "north-star-waiting-state" in command_names
        path = journal.run_dir / "north_star_waiting_state.json"
        markdown = journal.run_dir / "north_star_waiting_state.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# waiting", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "waiting_for_human_or_real_condition",
            "may_execute_from_this_result": False,
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:test"
            ),
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_waiting_state", fake_waiting_state)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-waiting-state-cli-test",
            "north-star-waiting-state",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "waiting_for_human_or_real_condition"
    assert output["may_execute_from_this_result"] is False
    assert output["required_human_approval_phrase"] == "<redacted approval material>"
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_phrase_verify_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_phrase_verify(
        journal,
        *,
        repo_root,
        command_names,
        phrase,
        phrase_source,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        assert repo_root.exists()
        assert "north-star-approval-phrase-verify" in command_names
        assert phrase == "I approve safe-ribbon-view-tab with token APPROVE:test"
        assert phrase_source == "human_active_conversation"
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        path = journal.run_dir / "north_star_approval_phrase_verify.json"
        markdown = journal.run_dir / "north_star_approval_phrase_verify.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# phrase verify", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "matched",
            "phrase_matches_waiting_state": True,
            "execution_by_this_command": False,
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_approval_phrase_verify", fake_phrase_verify)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-phrase-verify-cli-test",
            "north-star-approval-phrase-verify",
            "--phrase",
            "I approve safe-ribbon-view-tab with token APPROVE:test",
            "--phrase-source",
            "human_active_conversation",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "matched"
    assert output["phrase_matches_waiting_state"] is True
    assert output["execution_by_this_command"] is False
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approved_execution_preview_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_execution_preview(
        journal,
        *,
        repo_root,
        command_names,
        phrase,
        phrase_source,
        default_sheet_number,
        revit_version,
        expected_title_contains,
        expected_path_contains,
        expected_view_name,
        expected_view_type,
    ):
        assert repo_root.exists()
        assert "north-star-approved-execution-preview" in command_names
        assert phrase == "I approve safe-ribbon-view-tab with token APPROVE:test"
        assert phrase_source == "human_active_conversation"
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        path = journal.run_dir / "north_star_approved_execution_preview.json"
        markdown = journal.run_dir / "north_star_approved_execution_preview.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# execution preview", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "preview_ready",
            "execution_by_this_command": False,
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_approved_execution_preview", fake_execution_preview)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approved-execution-preview-cli-test",
            "north-star-approved-execution-preview",
            "--phrase",
            "I approve safe-ribbon-view-tab with token APPROVE:test",
            "--phrase-source",
            "human_active_conversation",
            "--sheet-number",
            "S2.0",
            "--revit-version",
            "2025",
            "--expected-title-contains",
            "24522 St John XXIII",
            "--expected-view-name",
            "STARTING VIEW",
            "--expected-view-type",
            "DrawingSheet",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "preview_ready"
    assert output["execution_by_this_command"] is False
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_verify_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-verify-cli-test",
            "north-star-approval-verify",
            "--approval-token",
            "APPROVE:not-current",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "no_match"
    assert output["execution_by_this_command"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_r25_filename_infers_revit_2025():
    assert infer_revit_version_from_model(Path("Example-Structural_Current-R25-BIM.rvt")) == "2025"


@pytest.mark.parametrize(
    ("marker", "version"),
    [("R22", "2022"), ("R23", "2023"), ("R24", "2024"), ("R25", "2025"), ("R26", "2026"), ("R27", "2027")],
)
def test_revit_filename_markers_infer_supported_versions(marker, version):
    assert infer_revit_version_from_model(Path(f"Example-Structural_Current-{marker}-BIM.rvt")) == version


def test_resolve_revit_exe_specific_version_does_not_fallback(monkeypatch, tmp_path):
    latest_exe = tmp_path / "Revit 2027" / "Revit.exe"
    latest_exe.parent.mkdir(parents=True)
    latest_exe.write_text("fake exe", encoding="utf-8")

    monkeypatch.setattr(revit_locator, "default_revit_install_dir", lambda version: tmp_path / f"Revit {version}")
    monkeypatch.setattr(revit_locator, "installed_revit_versions", lambda root=revit_locator.DEFAULT_AUTODESK_ROOT: {"2027": str(latest_exe)})

    assert revit_locator.resolve_revit_exe("2026") is None
    assert revit_locator.resolve_revit_exe(None) == latest_exe


def test_revit_version_support_matrix_covers_2022_to_2027():
    matrix = version_support_matrix({"2025": r"C:\Program Files\Autodesk\Revit 2025\Revit.exe"})

    assert matrix["supported_versions"] == ["2022", "2023", "2024", "2025", "2026", "2027"]
    assert matrix["min_version"] == "2022"
    assert matrix["max_version"] == "2027"
    assert matrix["version_count"] == 6
    assert matrix["target_frameworks"] == {
        "2022": "net48",
        "2023": "net48",
        "2024": "net48",
        "2025": "net8.0-windows",
        "2026": "net8.0-windows",
        "2027": "net10.0-windows",
    }
    assert next(row for row in matrix["rows"] if row["revit_version"] == "2025")["installed"] is True


def test_revit_addin_project_declares_all_supported_version_targets():
    project = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperator.csproj"
    ).read_text(encoding="utf-8")
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    assert "REVIT$(RevitVersion)" in project
    for version in SUPPORTED_REVIT_VERSIONS:
        assert version in project
        assert f"REVIT{version}" in source
    for framework in set(REVIT_TARGET_FRAMEWORK_BY_VERSION.values()):
        assert framework in project
    assert "System.Text.Json" in project
    assert "ElementIdValue(ElementId id)" in source
    assert "IntegerValue" in source
    assert "supported_revit_versions" in source


def test_cli_version_support_reports_all_supported_versions(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "version-support-cli-test",
            "version-support",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["support"]["supported_versions"] == list(SUPPORTED_REVIT_VERSIONS)
    assert output["support"]["target_frameworks"]["2027"] == "net10.0-windows"


def test_sandbox_validation_defaults_to_known_safe_project(tmp_path):
    error = validate_sandbox_root(tmp_path, allow_outside_safe_root=False)
    assert error is not None

    assert validate_sandbox_root(tmp_path, allow_outside_safe_root=True) is None
    assert validate_output_path(tmp_path / "ok.json", tmp_path) is None
    assert validate_output_path(tmp_path.parent / "escape.json", tmp_path) is not None


def test_find_controls_in_tree_matches_text_and_class():
    tree = {
        "hwnd": 1,
        "title": "Autodesk Revit",
        "class_name": "MainWindow",
        "enabled": True,
        "visible": True,
        "children": [
            {
                "hwnd": 2,
                "title": "&Manage Links",
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10},
                "children": [],
            },
            {
                "hwnd": 3,
                "title": "Project Browser",
                "class_name": "TreeView",
                "enabled": True,
                "visible": True,
                "children": [],
            },
        ],
    }

    matches = find_controls_in_tree(tree, text="Manage Links", class_name="Button")

    assert len(matches) == 1
    assert matches[0]["hwnd"] == 2
    assert "Autodesk Revit" in matches[0]["path"]


def test_uia_tree_uses_injected_desktop_factory():
    class Info:
        name = "Root"
        control_type = "Window"
        automation_id = "RootId"
        class_name = "RootClass"
        handle = 100

    class ChildInfo:
        name = "Ribbon"
        control_type = "Tab"
        automation_id = "RibbonId"
        class_name = "RibbonClass"
        handle = 101

    class Control:
        def __init__(self, info, children=None):
            self.element_info = info
            self._children = children or []

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return self._children

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return Control(Info(), [Control(ChildInfo())])

    result = uia_tree(hwnd=100, desktop_factory=lambda: Desktop())

    assert result["success"] is True
    assert result["tree"]["automation_id"] == "RootId"
    assert result["tree"]["children"][0]["name"] == "Ribbon"


def test_find_controls_in_uia_tree_matches_automation_id():
    tree = {
        "name": "Autodesk Revit",
        "control_type": "Window",
        "automation_id": "",
        "class_name": "Window",
        "children": [
            {
                "name": "Save",
                "control_type": "Custom",
                "automation_id": "ID_Save_RibbonItemControl",
                "class_name": "",
                "enabled": True,
                "visible": True,
                "children": [],
            }
        ],
    }

    matches = find_controls_in_uia_tree(tree, automation_id="ID_Save_RibbonItemControl")

    assert len(matches) == 1
    assert matches[0]["name"] == "Save"
    assert matches[0]["path"] == "Autodesk Revit > Save"


def test_uia_invoke_control_invokes_exact_fake_match():
    class Info:
        name = "View"
        control_type = "Button"
        automation_id = "View"
        class_name = "Button"
        handle = None

    class Control:
        def __init__(self):
            self.element_info = Info()
            self.invoked = False

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def invoke(self):
            self.invoked = True

    control = Control()

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return control

    result = uia_invoke_control(
        hwnd=100,
        automation_id="View",
        desktop_factory=lambda: Desktop(),
    )

    assert result["success"] is True
    assert result["method"] == "invoke"
    assert control.invoked is True


def test_uia_control_details_reports_available_methods():
    class Info:
        name = "Sheet S2.0"
        control_type = "TreeItem"
        automation_id = ""
        class_name = "TreeItem"
        handle = None

    class Control:
        element_info = Info()

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def select(self):
            return None

        def double_click_input(self):
            return None

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return Control()

    result = uia_control_details(
        hwnd=100,
        name="Sheet S2.0",
        desktop_factory=lambda: Desktop(),
        exact=True,
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert "select" in result["matches"][0]["available_methods"]
    assert "double_click_input" in result["matches"][0]["available_methods"]


def test_uia_invoke_control_uses_explicit_select_method():
    class Info:
        name = "Sheet S2.0"
        control_type = "TreeItem"
        automation_id = ""
        class_name = "TreeItem"
        handle = None

    class Control:
        def __init__(self):
            self.element_info = Info()
            self.selected = False

        def is_enabled(self):
            return True

        def is_visible(self):
            return True

        def children(self):
            return []

        def select(self):
            self.selected = True

    control = Control()

    class Desktop:
        def window(self, handle):
            assert handle == 100
            return control

    result = uia_invoke_control(
        hwnd=100,
        name="Sheet S2.0",
        method="select",
        desktop_factory=lambda: Desktop(),
        exact=True,
    )

    assert result["success"] is True
    assert result["method"] == "select"
    assert control.selected is True


def test_cli_uia_tree_writes_missing_dependency_result(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-tree-test",
            "uia-tree",
            "--hwnd",
            "1",
        ]
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert output["success"] in {True, False}


def test_cli_uia_find_control_writes_matches(tmp_path, capsys, monkeypatch):
    def fake_uia_find_controls(**kwargs):
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "query": {"automation_id": kwargs.get("automation_id")},
            "count": 1,
            "matches": [
                {
                    "name": "Save",
                    "automation_id": "ID_Save_RibbonItemControl",
                    "control_type": "Custom",
                }
            ],
        }

    monkeypatch.setattr(cli, "uia_find_controls", fake_uia_find_controls)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-find-control-test",
            "uia-find-control",
            "--automation-id",
            "ID_Save_RibbonItemControl",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_uia_control_details_writes_available_methods(tmp_path, capsys, monkeypatch):
    def fake_uia_control_details(**_kwargs):
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "count": 1,
            "matches": [{"name": "S2.0", "available_methods": ["select", "double_click_input"]}],
        }

    monkeypatch.setattr(cli, "uia_control_details", fake_uia_control_details)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-control-details-test",
            "uia-control-details",
            "--name",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["matches"][0]["available_methods"] == ["select", "double_click_input"]
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_uia_invoke_dry_run_returns_approval_token(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-invoke-dry-run-test",
            "uia-invoke",
            "--automation-id",
            "View",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_uia_invoke_save_target_remains_blocked(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "uia-invoke-save-test",
            "uia-invoke",
            "--automation-id",
            "ID_Save_RibbonItemControl",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["policy"]["decision"] == BLOCK
    assert output["executed"] is False
    assert output["status"] == "blocked"
    assert "--execute" not in output["next_step"]


def test_cli_find_control_writes_matches(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **kwargs):
            return {
                "success": True,
                "supported": True,
                "query": kwargs,
                "count": 1,
                "ambiguous": False,
                "matches": [{"hwnd": 10, "title": "Project Browser", "class_name": "TreeView"}],
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "find-control-test",
            "find-control",
            "--text",
            "Project Browser",
            "--class-name",
            "TreeView",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_ocr_screenshot_uses_injected_runner(tmp_path):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = ocr_screenshot(
        TaskJournal(tmp_path, "ocr-test"),
        FakeObserver(),
        hwnd=123,
        ocr_runner=lambda _path: "Hello\nRevit",
    )

    assert result["success"] is True
    assert result["backend"] == "injected"
    assert result["text_length"] == len("Hello\nRevit")
    assert result["line_count"] == 2
    assert result["item_count"] == 0
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_ocr_screenshot_extracts_rapidocr_geometry_from_runner(tmp_path):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    rapidocr_shape = (
        [
            [
                [[133.0, 193.0], [354.0, 194.0], [354.0, 214.0], [133.0, 213.0]],
                "S2.0_1_FOUNDATION PLAN",
                0.98,
            ],
        ],
        [0.01, 0.02, 0.03],
    )

    result = ocr_screenshot(
        TaskJournal(tmp_path, "ocr-geometry-test"),
        FakeObserver(),
        hwnd=123,
        ocr_runner=lambda _path: rapidocr_shape,
    )

    assert result["success"] is True
    assert result["text"] == "S2.0_1_FOUNDATION PLAN"
    assert result["item_count"] == 1
    assert result["items"][0]["confidence"] == 0.98
    assert result["items"][0]["bounds"]["left"] == 133.0
    assert result["items"][0]["bounds"]["right"] == 354.0
    assert result["items"][0]["bounds"]["center_x"] == 243.5
    artifact = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert artifact["items"][0]["text"] == "S2.0_1_FOUNDATION PLAN"


def test_ocr_health_reports_dependency_shape(monkeypatch):
    monkeypatch.delenv("HERMES_TESSERACT_CMD", raising=False)

    result = ocr_health()

    assert result["success"] is True
    assert "Pillow" in result["python_packages"]
    assert "pytesseract" in result["python_packages"]
    assert "rapidocr" in result["backends"]
    assert isinstance(result["missing"], list)
    assert "install_hint" in result


def test_rapidocr_result_parser_handles_common_shapes():
    old_shape = (
        [
            [[[0, 0], [1, 0], [1, 1], [0, 1]], "Sheet S2.0", 0.99],
            [[[0, 2], [1, 2], [1, 3], [0, 3]], "FOUNDATION PLAN", 0.98],
        ],
        0.12,
    )
    dict_shape = {"txts": ["Warnings", "Review"]}

    assert ocr_module._rapidocr_result_to_text(old_shape) == "Sheet S2.0\nFOUNDATION PLAN"
    assert ocr_module._rapidocr_result_to_text(dict_shape) == "Warnings\nReview"
    payload = ocr_module._ocr_payload(old_shape)
    assert payload["items"][0]["text"] == "Sheet S2.0"
    assert payload["items"][0]["bounds"] == {
        "left": 0.0,
        "top": 0.0,
        "right": 1.0,
        "bottom": 1.0,
        "width": 1.0,
        "height": 1.0,
        "center_x": 0.5,
        "center_y": 0.5,
    }


def test_ocr_health_can_report_rapidocr_ready_without_tesseract(monkeypatch):
    def fake_has_module(name):
        return name in {"rapidocr_onnxruntime"}

    monkeypatch.setattr(ocr_module, "_has_module", fake_has_module)
    monkeypatch.setattr(ocr_module, "_tesseract_executable", lambda: None)

    result = ocr_module.ocr_health()

    assert result["ready"] is True
    assert result["preferred_backend"] == "rapidocr"
    assert result["backends"]["tesseract"]["ready"] is False
    assert result["backends"]["rapidocr"]["ready"] is True
    assert result["missing"] == []


def test_cli_ocr_health_is_read_only(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ocr-health-test",
            "ocr-health",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert "ready" in output
    assert "tesseract_executable" in output
    assert "backends" in output


def test_control_server_health_and_command(tmp_path, monkeypatch):
    monkeypatch.setenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    server = make_control_server(
        "127.0.0.1",
        0,
        sandbox=tmp_path,
        allow_sandbox_outside_safe_root=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["success"] is True
        assert health["service"] == "revit-operator"
        assert "/commands" in health["endpoints"]

        with urllib.request.urlopen(base + "/commands", timeout=5) as response:
            commands = json.loads(response.read().decode("utf-8"))
        assert commands["success"] is True
        assert commands["service"] == "revit-operator"
        assert commands["transport"] == "local-http"
        assert "run-safe-command" in commands["commands"]
        assert "north-star-completion-gate" in commands["commands"]
        assert "serve" in commands["blocked_commands"]

        body = json.dumps(
            {
                "command": "known-dialogs",
                "task_id": "server-known-dialogs-test",
                "args": [],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["success"] is True
        assert result["count"] >= 5
        assert Path(result["journal"]["journal"]).is_relative_to(tmp_path)

        body = json.dumps(
            {
                "command": "run-safe-command",
                "task_id": "server-safe-command-test",
                "args": ["--name", "active-document"],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            safe_result = json.loads(response.read().decode("utf-8"))
        assert safe_result["success"] is True
        assert safe_result["dry_run"] is True
        assert safe_result["safe_command"]["delegates_to"] == "request-operation"
        assert safe_result["wrapper_policy"]["decision"] == "allow"
        assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()

        body = json.dumps(
            {
                "command": "run-safe-command",
                "task_id": "server-safe-command-block-test",
                "args": ["--name", "save", "--execute"],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)
        blocked_result = json.loads(exc_info.value.read().decode("utf-8"))
        assert blocked_result["success"] is False
        assert blocked_result["wrapper_policy"]["decision"] == BLOCK
        assert blocked_result["safe_command"]["delegates_to"] is None
        assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_transport_safety_matrix_is_read_only_and_clean(tmp_path, monkeypatch):
    monkeypatch.delenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)

    result = build_transport_safety_matrix(
        TaskJournal(tmp_path, "transport-safety-matrix-test"),
        repo_root=Path.cwd(),
    )
    result_text = json.dumps(result)

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["live_revit_touched"] is False
    assert result["status"] == "clean"
    assert result["failed_count"] == 0
    assert result["direct_approval_marker_count"] == 0
    assert result["redaction_marker_count"] > 0
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    assert Path(result["stable_path"]) == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    assert Path(result["stable_path"]).exists()
    assert (
        Path(result["stable_markdown_path"])
        == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md"
    )
    assert Path(result["stable_markdown_path"]).exists()
    stable_markdown = Path(result["stable_markdown_path"]).read_text(encoding="utf-8")
    assert "- completion_allowed: `false`" in stable_markdown
    assert "- may_call_update_goal: `false`" in stable_markdown
    assert "- audit_completion_authorized: `false`" in stable_markdown
    assert "- may_execute_from_this_result: `false`" in stable_markdown
    assert "APPROVE:" not in result_text
    assert "i approve" not in result_text.lower()
    check_ids = {check["id"] for check in result["checks"]}
    assert {
        "cli-stdout-redaction",
        "http-control-redaction",
        "mcp-json-redaction",
        "plugin-redaction",
        "http-blocks-external-sandbox-override",
        "mcp-blocks-external-sandbox-override",
        "plugin-blocks-external-sandbox-override",
        "http-blocks-model-root-override",
        "mcp-blocks-model-root-override",
        "plugin-blocks-model-root-override",
    }.issubset(check_ids)


def test_cli_transport_safety_matrix_writes_readonly_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "transport-safety-matrix-cli-test",
            "transport-safety-matrix",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    output_text = json.dumps(output)

    assert code == 0
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["live_revit_touched"] is False
    assert output["status"] == "clean"
    assert output["direct_approval_marker_count"] == 0
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["stable_path"]) == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    assert Path(output["stable_markdown_path"]).exists()
    assert "APPROVE:" not in output_text
    assert "i approve" not in output_text.lower()


def test_control_command_redacts_approval_material_in_results(monkeypatch):
    def fake_dispatch(_args):
        return {
            "success": True,
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:server-secret"
            ),
            "approval_token": "APPROVE:server-secret",
        }

    monkeypatch.setattr(cli, "dispatch", fake_dispatch)

    result = run_control_command({"command": "health"})
    result_text = json.dumps(result)

    assert result["success"] is True
    assert "APPROVE:server-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval material>" in result_text


def test_control_command_redacts_approval_material_in_parse_errors(capsys):
    result = run_control_command(
        {
            "argv": [
                "north-star-approval-verify",
                "--approval-token",
                "APPROVE:server-secret",
                "--bad-flag",
            ]
        }
    )
    capsys.readouterr()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:server-secret" not in result_text
    assert "<redacted approval token>" in result_text


def test_control_commands_list_redacts_approval_material_in_errors(monkeypatch):
    def fail_available_commands():
        raise ValueError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:server-secret"
        )

    monkeypatch.setattr(cli, "_available_commands", fail_available_commands)

    result = list_control_commands()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:server-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval token>" in result_text
    assert "<redacted approval phrase>" in result_text


def test_cli_approval_stdout_redacts_phrase_case_insensitively():
    result = cli._redact_approval_stdout(
        "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:case-secret"
    )

    assert "APPROVE:case-secret" not in result
    assert "i approve" not in result.lower()
    assert "<redacted approval token>" in result
    assert "<redacted approval phrase>" in result


def test_mcp_command_redacts_approval_material_in_results(monkeypatch):
    def fake_control_command(*_args, **_kwargs):
        return {
            "success": True,
            "required_human_approval_phrase": (
                "i approve safe-ribbon-view-tab with token APPROVE:mcp-secret"
            ),
            "approval_token": "APPROVE:mcp-secret",
        }

    monkeypatch.setattr(mcp_server, "run_control_command", fake_control_command)

    result = mcp_server.run_mcp_command(command="health")
    result_text = json.dumps(result)

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval material>" in result_text


def test_mcp_command_redacts_approval_material_in_exceptions(monkeypatch):
    def fail_control_command(*_args, **_kwargs):
        raise ValueError(
            "Bad phrase I approve safe-ribbon-view-tab with token APPROVE:mcp-secret"
        )

    monkeypatch.setattr(mcp_server, "run_control_command", fail_control_command)

    result = mcp_server.run_mcp_command(command="health")
    result_text = json.dumps(result)

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval token>" in result_text


def test_mcp_list_commands_redacts_approval_material_in_errors(monkeypatch):
    def fail_build_parser():
        raise ValueError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:mcp-list-secret"
        )

    monkeypatch.setattr(cli, "build_parser", fail_build_parser)

    result = mcp_server.list_mcp_commands()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-list-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval token>" in result_text
    assert "<redacted approval phrase>" in result_text


def test_mcp_json_result_redacts_approval_material():
    result_text = mcp_server._json_result(
        {
            "success": True,
            "required_human_approval_phrase": (
                "i approve safe-ribbon-view-tab with token APPROVE:mcp-json-secret"
            ),
            "approval_token": "APPROVE:mcp-json-secret",
        }
    )

    assert "APPROVE:mcp-json-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval material>" in result_text


def test_mcp_main_redacts_approval_material_in_import_errors(monkeypatch, capsys):
    def fail_run_mcp_server(*, verbose):
        raise ImportError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:mcp-main-secret"
        )

    monkeypatch.setattr(mcp_server, "run_mcp_server", fail_run_mcp_server)

    code = mcp_server.main([])
    captured = capsys.readouterr()

    assert code == 2
    assert "APPROVE:mcp-main-secret" not in captured.out
    assert "i approve" not in captured.out.lower()
    assert "<redacted approval token>" in captured.out
    assert "<redacted approval phrase>" in captured.out


def test_control_server_blocks_external_sandbox_escape_without_test_env(tmp_path):
    result = run_control_command(
        {
            "command": "known-dialogs",
            "allow_sandbox_outside_safe_root": True,
        },
        default_sandbox=tmp_path,
    )

    assert result["success"] is False
    assert "allow_sandbox_outside_safe_root" in result["error"]
    assert HTTP_ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_control_server_blocks_argv_external_sandbox_escape_without_test_env(tmp_path):
    result = run_control_command(
        {
            "argv": [
                "--sandbox",
                str(tmp_path),
                "--allow-sandbox-outside-safe-root",
                "known-dialogs",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-sandbox-outside-safe-root" in result["error"]
    assert HTTP_ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_control_server_blocks_model_outside_safe_root_flag(tmp_path):
    result = run_control_command(
        {
            "command": "open-model",
            "args": [
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_argv_model_outside_safe_root_flag(tmp_path):
    result = run_control_command(
        {
            "argv": [
                "open-model",
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_nested_model_outside_safe_root_override(tmp_path):
    result = run_control_command(
        {
            "command": "request-operation",
            "args": [
                "--operation",
                "open-model",
                "--args-json",
                json.dumps(
                    {
                        "path": str(tmp_path / "outside.rvt"),
                        "allow_model_outside_safe_root": True,
                    }
                ),
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_recursive_serve(tmp_path, monkeypatch):
    monkeypatch.setenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = run_control_command(
        {"command": "serve"},
        default_sandbox=tmp_path,
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert "cannot be called" in result["error"]


def test_mcp_wrapper_runs_known_dialogs(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="known-dialogs",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-known-dialogs-test",
    )

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert result["count"] >= 5
    assert Path(result["journal"]["journal"]).is_relative_to(tmp_path)


def test_mcp_wrapper_blocks_external_sandbox_escape_without_test_env(tmp_path):
    result = mcp_server.run_mcp_command(
        command="known-dialogs",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-known-dialogs-blocked-test",
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "allow_sandbox_outside_safe_root" in result["error"]
    assert mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_mcp_wrapper_blocks_argv_external_sandbox_escape_without_test_env(tmp_path):
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "known-dialogs",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-sandbox-outside-safe-root" in result["error"]
    assert mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_mcp_wrapper_blocks_model_outside_safe_root_flag(tmp_path):
    result = mcp_server.run_mcp_command(
        command="open-model",
        args=[
            "--model",
            str(tmp_path / "outside.rvt"),
            "--allow-model-outside-safe-root",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_argv_model_outside_safe_root_flag(tmp_path):
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "open-model",
            "--model",
            str(tmp_path / "outside.rvt"),
            "--allow-model-outside-safe-root",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_nested_model_outside_safe_root_override(tmp_path):
    result = mcp_server.run_mcp_command(
        command="request-operation",
        args=[
            "--operation",
            "open-model",
            "--args-json",
            json.dumps(
                {
                    "path": str(tmp_path / "outside.rvt"),
                    "allow_model_outside_safe_root": True,
                }
            ),
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_server_commands(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="serve",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "blocked" in result["error"].lower()


def test_mcp_wrapper_blocks_server_commands_in_argv(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "serve",
        ],
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "blocked" in result["error"].lower()


def test_mcp_wrapper_runs_safe_command_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="run-safe-command",
        args=["--name", "active-document"],
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-safe-command-test",
    )

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert result["dry_run"] is True
    assert result["safe_command"]["delegates_to"] == "request-operation"
    assert result["wrapper_policy"]["decision"] == "allow"
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_mcp_wrapper_blocks_unsafe_safe_command(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="run-safe-command",
        args=["--name", "save", "--execute"],
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-safe-command-block-test",
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert result["wrapper_policy"]["decision"] == BLOCK
    assert result["safe_command"]["delegates_to"] is None
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


class _FakeMcpToolManager:
    def __init__(self):
        self.tools = {}

    def add_tool(self, fn):
        self.tools[fn.__name__] = fn


class _FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self._tool_manager = _FakeMcpToolManager()

    def tool(self):
        def decorator(fn):
            self._tool_manager.add_tool(fn)
            return fn

        return decorator


def test_mcp_server_registers_thin_wrapper_tools(monkeypatch, tmp_path):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    monkeypatch.setattr(mcp_server, "_MCP_SERVER_AVAILABLE", True)
    monkeypatch.setattr(mcp_server, "FastMCP", _FakeFastMCP)

    server = mcp_server.create_mcp_server()

    assert {"revit_operator_health", "revit_operator_commands", "revit_operator_command"}.issubset(
        server._tool_manager.tools
    )
    assert (
        "allow_sandbox_outside_safe_root"
        not in server._tool_manager.tools["revit_operator_command"].__code__.co_varnames
    )
    raw = server._tool_manager.tools["revit_operator_command"](
        command="known-dialogs",
        sandbox=str(tmp_path),
        task_id="mcp-server-tool-test",
    )
    result = json.loads(raw)
    assert result["success"] is True
    assert result["called_via"] == "mcp"


def test_mcp_stdio_server_serves_read_only_command(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run_smoke():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tools.revit_operator.mcp_server"],
            cwd=str(Path.cwd()),
            env={
                **os.environ,
                "PYTHONPATH": str(Path.cwd()),
                mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV: "1",
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                listed = await asyncio.wait_for(session.list_tools(), timeout=15)
                result = await asyncio.wait_for(
                    session.call_tool(
                        "revit_operator_command",
                        arguments={
                            "command": "known-dialogs",
                            "sandbox": str(tmp_path),
                            "task_id": "mcp-stdio-known-dialogs-test",
                        },
                    ),
                    timeout=30,
                )
        return listed, result

    listed, result = asyncio.run(run_smoke())
    tool_names = {tool.name for tool in listed.tools}
    payload = json.loads(result.content[0].text)

    assert {"revit_operator_health", "revit_operator_commands", "revit_operator_command"}.issubset(
        tool_names
    )
    assert payload["success"] is True
    assert payload["called_via"] == "mcp"
    assert Path(payload["journal"]["journal"]).is_relative_to(tmp_path)


def test_cli_ocr_screenshot_writes_artifact(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ocr-cli-test",
            "ocr-screenshot",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code in {0, 2}
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert "screenshot" in output


def test_project_browser_snapshot_captures_selected_control(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {
                "supported": True,
                "hwnd": hwnd,
                "max_depth": max_depth,
                "tree": {"title": "Project Browser"},
            }

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = capture_project_browser_snapshot(
        TaskJournal(tmp_path, "project-browser-test"),
        FakeObserver(),
        include_uia=True,
        include_ocr=True,
        ocr_backend="rapidocr",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Sheets\nS2.0\nFOUNDATION PLAN",
            "line_count": 3,
            "path": str(tmp_path / "ocr.json"),
            "screenshot": {"path": str(tmp_path / "ocr.bmp")},
            "read_only": True,
        },
        uia_tree_func=lambda **_kwargs: {"supported": True, "node_count": 2, "tree": {}},
    )

    assert result["success"] is True
    assert result["uia_node_count"] == 2
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["selected_control"]["hwnd"] == 42
    assert snapshot["uia_tree"]["node_count"] == 2
    assert snapshot["ocr"]["line_count"] == 3
    assert result["ocr_enabled"] is True
    assert result["ocr_success"] is True
    assert snapshot["note"].startswith("Project Browser was observed")


def test_cli_project_browser_snapshot_writes_bundle(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-cli-test",
            "project-browser-snapshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["selected_hwnd"] == 42


def test_properties_palette_snapshot_captures_selected_control(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {
                        "hwnd": 101,
                        "title": "Properties",
                        "class_name": "Afx:ControlBar",
                        "depth": 1,
                        "rect": {"width": 250, "height": 400},
                    },
                    {
                        "hwnd": 102,
                        "title": "Properties",
                        "class_name": "#32770",
                        "depth": 3,
                        "rect": {"width": 250, "height": 400},
                    },
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {
                "supported": True,
                "hwnd": hwnd,
                "max_depth": max_depth,
                "tree": {"title": "Properties"},
            }

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = capture_properties_palette_snapshot(
        TaskJournal(tmp_path, "properties-palette-test"),
        FakeObserver(),
        include_uia=True,
        include_ocr=True,
        ocr_backend="rapidocr",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Properties\nConstraints\nDimensions",
            "line_count": 3,
            "items": [{"text": "Constraints", "confidence": 0.99}],
            "path": str(tmp_path / "ocr.json"),
            "screenshot": {"path": str(tmp_path / "ocr.bmp")},
            "read_only": True,
        },
        uia_tree_func=lambda **_kwargs: {"supported": True, "node_count": 4, "tree": {}},
    )

    assert result["success"] is True
    assert result["selected_hwnd"] == 101
    assert result["uia_node_count"] == 4
    assert result["ocr_line_count"] == 3
    assert result["ocr_items"][0]["text"] == "Constraints"
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["selected_control"]["hwnd"] == 101
    assert snapshot["note"].startswith("Properties palette was observed")


def test_cli_properties_palette_snapshot_writes_bundle(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 101, "title": "Properties", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Properties"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "properties-palette-cli-test",
            "properties-palette-snapshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["selected_hwnd"] == 101


def test_project_browser_navigation_plan_prefers_guarded_activate_view(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 101,
                        "sheet_number": "S101",
                        "name": "Framing Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S101",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S101\nFOUNDATION PLAN",
            "line_count": 2,
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["project_browser_observed"] is True
    assert result["route"]["recommended_method"] == "request-operation activate-view"
    assert result["route"]["args"] == {"id": 101, "sheet_number": "S101"}
    assert result["visual_evidence"]["ocr_match_count"] == 1
    assert result["visual_evidence"]["ocr_matches"][0]["text"] == "S101"
    plan = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert plan["project_browser_snapshot"]["ocr_line_count"] == 2
    assert plan["visual_evidence"]["ocr_match_count"] == 1
    assert plan["note"].startswith("This command plans navigation only")


def test_project_browser_navigation_uses_ocr_evidence_when_metadata_has_no_match(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps({"sheets": [], "views": []}),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-ocr-fallback-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S2.0",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Views\nSheet Views\nS2.0_1_FOUNDATION PLAN",
            "line_count": 3,
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["route"]["recommended_method"] == "ask_human"
    assert "OCR found possible visible Project Browser matches" in result["route"]["reason"]
    assert result["visual_evidence"]["ocr_match_count"] == 1
    assert result["visual_evidence"]["ocr_matches"][0]["matched_terms"] == ["S2.0"]


def test_project_browser_navigation_keeps_ocr_match_geometry(tmp_path):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps({"sheets": [], "views": []}),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    result = plan_project_browser_navigation(
        TaskJournal(tmp_path, "project-browser-navigation-ocr-geometry-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        sheet_number="S2.0",
        include_ocr=True,
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "Views\nS2.0_1_FOUNDATION PLAN",
            "line_count": 2,
            "items": [
                {
                    "line_number": 2,
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "confidence": 0.979,
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "width": 221.0,
                        "height": 21.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "path": str(tmp_path / "project-browser-ocr.json"),
            "read_only": True,
        },
    )

    match = result["visual_evidence"]["ocr_matches"][0]
    assert result["visual_evidence"]["ocr_item_count"] == 1
    assert match["source"] == "ocr_item"
    assert match["confidence"] == 0.979
    assert match["bounds"]["left"] == 133.0
    assert match["bounds"]["center_y"] == 203.5
    plan = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert plan["project_browser_snapshot"]["ocr_items"][0]["bounds"]["right"] == 354.0


def test_project_browser_visual_activation_plans_ocr_coordinate_click(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {
                "success": True,
                "path": str(output),
                "hwnd": hwnd,
                "rect": {"left": 100.0, "top": 200.0, "right": 500.0, "bottom": 800.0},
            }

    result = plan_project_browser_visual_activation(
        TaskJournal(tmp_path, "project-browser-visual-plan-test"),
        FakeObserver(),
        sheet_number="S2.0",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S2.0_1_FOUNDATION PLAN",
            "line_count": 1,
            "items": [
                {
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "width": 221.0,
                        "height": 21.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "read_only": True,
        },
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["policy"]["action"] == "visual-click"
    assert result["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["payload"]["coordinate_source"] == "project-browser-ocr"
    assert result["payload"]["screen_x"] == 343.5
    assert result["payload"]["screen_y"] == 403.5
    assert result["read_only"] is True


def test_project_browser_visual_activation_dry_run_returns_token(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 42, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {
                "success": True,
                "path": str(output),
                "hwnd": hwnd,
                "rect": {"left": 100.0, "top": 200.0, "right": 500.0, "bottom": 800.0},
            }

        def status(self):
            return {"state": "idle"}

    result = run_project_browser_visual_activation(
        TaskJournal(tmp_path, "project-browser-visual-run-test"),
        FakeObserver(),
        sheet_number="S2.0",
        ocr_func=lambda *_args, **_kwargs: {
            "success": True,
            "text": "S2.0_1_FOUNDATION PLAN",
            "line_count": 1,
            "items": [
                {
                    "text": "S2.0_1_FOUNDATION PLAN",
                    "bounds": {
                        "left": 133.0,
                        "top": 193.0,
                        "right": 354.0,
                        "bottom": 214.0,
                        "center_x": 243.5,
                        "center_y": 203.5,
                    },
                }
            ],
            "read_only": True,
        },
    )

    assert result["dry_run"] is True
    assert result["execution"]["status"] == "dry_run"
    assert result["execution"]["policy"]["approval_token"].startswith("APPROVE:")
    assert result["executed"] is False


def test_visual_click_executor_uses_screen_coordinates_after_approval(tmp_path):
    calls = []

    class FakeUser32:
        def SetForegroundWindow(self, hwnd):
            calls.append(("focus", hwnd))
            return True

        def SetCursorPos(self, x, y):
            calls.append(("cursor", x, y))
            return True

        def mouse_event(self, event, dx, dy, data, extra):
            calls.append(("mouse", event, dx, dy, data, extra))
            return None

    class FakeObserver:
        supported = True
        user32 = FakeUser32()

        def status(self):
            return {"state": "idle"}

        def _default_target_hwnd(self):
            return 42

    payload = {
        "hwnd": 42,
        "screen_x": 344,
        "screen_y": 404,
        "target_text": "S2.0_1_FOUNDATION PLAN",
        "coordinate_source": "project-browser-ocr",
    }
    result = SafeActionExecutor(FakeObserver(), TaskJournal(tmp_path, "visual-click-test")).run(
        ActionRequest(
            action="visual-click",
            payload=payload,
            dry_run=False,
            approval_token=approval_token_for("visual-click", payload),
        )
    )

    assert result["executed"] is True
    assert ("focus", 42) in calls
    assert ("cursor", 344, 404) in calls
    assert [call[0] for call in calls].count("mouse") == 2


def test_cli_project_browser_plan_navigation_writes_plan(tmp_path, capsys, monkeypatch):
    (tmp_path / "bridge").mkdir()
    (tmp_path / "bridge" / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 202,
                        "sheet_number": "S202",
                        "name": "Enlarged Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [
                    {"hwnd": 7, "title": "Project Browser", "class_name": "Afx:ControlBar"}
                ],
            }

        def ui_tree(self, hwnd, max_depth=4):
            return {"supported": True, "hwnd": hwnd, "tree": {"title": "Project Browser"}}

        def screenshot(self, output, hwnd=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "hwnd": hwnd}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-plan-cli-test",
            "project-browser-plan-navigation",
            "--sheet-number",
            "S202",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["route"]["recommended_method"] == "request-operation activate-view"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_project_browser_item_activation_plan_requires_single_uia_target(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 99, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

    def fake_uia_find(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [
                {
                    "name": "S2.0 - FOUNDATION PLAN",
                    "control_type": "TreeItem",
                    "enabled": True,
                    "visible": True,
                }
            ],
        }

    result = plan_project_browser_item_activation(
        TaskJournal(tmp_path, "project-browser-activation-plan-test"),
        FakeObserver(),
        name="S2.0",
        uia_find_func=fake_uia_find,
    )

    assert result["success"] is True
    assert result["executable"] is True
    assert result["policy"]["decision"] == APPROVAL_REQUIRED
    assert result["payload"]["hwnd"] == 99
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_project_browser_activate_item_dry_run_returns_approval_token(tmp_path):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 99, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    def fake_uia_find(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S2.0", "enabled": True, "visible": True}],
        }

    result = run_project_browser_item_activation(
        TaskJournal(tmp_path, "project-browser-activation-dry-run-test"),
        FakeObserver(),
        name="S2.0",
        dry_run=True,
        uia_find_func=fake_uia_find,
    )

    assert result["executed"] is False
    assert result["execution"]["dry_run"] is True
    assert result["execution"]["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_project_browser_plan_activation_writes_plan(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def find_controls(self, **_kwargs):
            return {
                "success": True,
                "matches": [{"hwnd": 77, "title": "Project Browser", "class_name": "Afx:ControlBar"}],
            }

    def fake_uia_find_controls(**_kwargs):
        return {
            "success": True,
            "count": 1,
            "ambiguous": False,
            "matches": [{"name": "S3.0", "enabled": True, "visible": True}],
        }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr("tools.revit_operator.project_browser.uia_find_controls", fake_uia_find_controls)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "project-browser-plan-activation-cli-test",
            "project-browser-plan-activation",
            "--name",
            "S3.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["executable"] is True
    assert output["payload"]["hwnd"] == 77


def test_cli_classify_dialog_writes_journal(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "classify-test",
            "classify-dialog",
            "--title",
            "Reload Links",
            "--text",
            "One or more links need to be reloaded.",
            "--button",
            "Cancel",
            "--button",
            "Reload",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["risk"] == HIGH
    journal = tmp_path / "revit_operator_runs" / "classify-test" / "journal.jsonl"
    assert journal.exists()
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["command"] == "classify-dialog"
    assert records[-1]["risk_classification"]["decision"] == "allow"


def test_cli_click_dry_run_returns_approval_token_and_does_not_execute(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "click-test",
            "click",
            "--target",
            "Cancel",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"].startswith("APPROVE:")


def test_cli_visual_click_dry_run_returns_coordinate_payload(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "visual-click-cli-test",
            "visual-click",
            "--screen-x",
            "245",
            "--screen-y",
            "134",
            "--target-text",
            "Visibility/Graphics",
            "--coordinate-source",
            "test-screenshot",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["executed"] is False
    assert output["policy"]["action"] == "visual-click"
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["policy"]["approval_token"] == approval_token_for(
        "visual-click",
        {
            "screen_x": 245,
            "screen_y": 134,
            "target_text": "Visibility/Graphics",
            "coordinate_source": "test-screenshot",
        },
    )


def test_cli_export_metadata_writes_stub_inside_sandbox(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "metadata-test",
            "export-metadata",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    metadata_path = Path(output["path"])
    assert metadata_path.is_relative_to(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["label"] == DRAFT_LABEL
    assert metadata["read_only"] is True


def test_find_view_matches_supports_sheet_and_view_queries():
    metadata = {
        "sheets": [
            {
                "id": 101,
                "sheet_number": "S101",
                "name": "Framing Plan",
                "is_placeholder": False,
            }
        ],
        "views": [
            {
                "id": 202,
                "name": "Level 1 Framing",
                "view_type": "FloorPlan",
            }
        ],
    }

    sheet_matches = find_view_matches(metadata, sheet_number="S101")
    view_matches = find_view_matches(metadata, query="framing", view_type="FloorPlan")

    assert sheet_matches == [
        {
            "kind": "sheet",
            "id": 101,
            "name": "Framing Plan",
            "view_type": "DrawingSheet",
            "sheet_number": "S101",
            "is_placeholder": False,
        }
    ]
    view_match = next(match for match in view_matches if match["kind"] == "view")
    assert view_match["id"] == 202


def test_cli_find_view_uses_bridge_metadata_and_writes_activation_hint(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 101,
                        "sheet_number": "S101",
                        "name": "Framing Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "find-view-test",
            "find-view",
            "--sheet-number",
            "S101",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert output["activation"]["available"] is True
    assert output["activation"]["operation"] == "activate-view"
    assert output["activation"]["args"] == {"id": 101, "sheet_number": "S101"}
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_open_model_dry_run_uses_explicit_revit_exe_and_requires_approval(tmp_path, capsys):
    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    revit = tmp_path / "Revit.exe"
    revit.write_text("not a real executable", encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "open-test",
            "open-model",
            "--model",
            str(model),
            "--revit-exe",
            str(revit),
            "--allow-model-outside-safe-root",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["operation_plan"]["launch"] == [str(revit), str(model)]
    assert output["operation_plan"]["expected_prompts"] == []


def test_request_operation_save_requires_write_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "save-test",
            "request-operation",
            "--operation",
            "save",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert "--allow-model-write" in output["error"]
    assert output["policy"]["risk"] == "critical"


def test_run_safe_command_dry_run_wraps_readonly_bridge_operation(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-dry-run-test",
            "run-safe-command",
            "--name",
            "active-document",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["safe_command"]["delegates_to"] == "request-operation"
    assert output["safe_command"]["delegated_operation"] == "active-document"
    assert output["wrapper_policy"]["decision"] == "allow"
    assert output["policy"]["decision"] == "allow"
    assert output["command"]["operation"] == "active-document"
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_run_safe_command_execute_queues_only_readonly_wrapper(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-queue-test",
            "run-safe-command",
            "--name",
            "qa-snapshot",
            "--args-json",
            '{"sheet_number":"S2.0"}',
            "--execute",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["queued"] is True
    assert output["wrapper_policy"]["decision"] == "allow"
    assert output["command"]["guards"]["allow_model_write"] is False
    assert output["command"]["guards"]["allow_sync"] is False
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "qa-snapshot"
    assert command["args"]["sheet_number"] == "S2.0"
    assert command["guards"]["allow_model_write"] is False
    assert command["guards"]["allow_sync"] is False


def test_run_safe_command_blocks_unsupported_operations(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-block-test",
            "run-safe-command",
            "--name",
            "save",
            "--execute",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "read-only command wrappers" in output["error"]
    assert output["wrapper_policy"]["decision"] == BLOCK
    assert output["safe_command"]["delegates_to"] is None
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_request_operation_sync_requires_sync_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "sync-test",
            "request-operation",
            "--operation",
            "sync",
            "--allow-model-write",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert "--allow-sync" in output["error"]


def test_request_operation_activate_view_dry_run_requires_approval_without_write_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "activate-view-dry-run-test",
            "request-operation",
            "--operation",
            "activate-view",
            "--sheet-number",
            "S101",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["risk"] == "critical"
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["command"]["args"]["sheet_number"] == "S101"
    assert output["command"]["guards"]["allow_model_write"] is False
    assert "--allow-model-write" not in output["next_step"]


def test_request_operation_activate_view_execute_writes_bridge_queue_with_exact_token(tmp_path, capsys):
    payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S101"},
        "allow_model_write": False,
        "allow_sync": False,
    }
    decision = classify_action("request-operation", payload)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "activate-view-queue-test",
            "request-operation",
            "--operation",
            "activate-view",
            "--sheet-number",
            "S101",
            "--execute",
            "--approval-token",
            decision.approval_token,
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "activate-view"
    assert command["args"]["sheet_number"] == "S101"
    assert command["guards"]["allow_model_write"] is False


def test_request_operation_execute_writes_bridge_queue_with_exact_token(tmp_path, capsys):
    payload = {
        "operation": "set-project-info-parameter",
        "args": {"name": "Project Status", "value": "QA Draft"},
        "allow_model_write": True,
        "allow_sync": False,
    }
    decision = classify_action("request-operation", payload)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "queue-test",
            "request-operation",
            "--operation",
            "set-project-info-parameter",
            "--name",
            "Project Status",
            "--value",
            "QA Draft",
            "--allow-model-write",
            "--execute",
            "--approval-token",
            decision.approval_token,
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "set-project-info-parameter"
    assert command["args"]["name"] == "Project Status"
    assert command["guards"]["allow_model_write"] is True


def test_bridge_queue_append_retries_transient_permission_error(tmp_path, monkeypatch):
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    queue_path.parent.mkdir()
    original_open = Path.open
    calls = {"count": 0}

    def flaky_open(self, *args, **kwargs):
        if self == queue_path and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError("bridge queue is temporarily locked")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    result = operations._append_command_jsonl(
        queue_path,
        {"id": "retry-test", "operation": "active-document"},
        attempts=2,
        base_delay=0,
    )

    assert result["success"] is True
    assert result["attempts"] == 2
    assert json.loads(queue_path.read_text(encoding="utf-8"))["id"] == "retry-test"


def test_request_operation_open_model_validates_and_queues_model_path(tmp_path, capsys):
    model = tmp_path / "bridge-open-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    args = {
        "path": str(model),
        "detach": True,
        "allow_model_outside_safe_root": True,
    }
    payload = {
        "operation": "open-model",
        "args": args,
        "allow_model_write": False,
        "allow_sync": False,
    }
    decision = classify_action("request-operation", payload)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-open-test",
            "request-operation",
            "--operation",
            "open-model",
            "--args-json",
            json.dumps(args),
            "--execute",
            "--approval-token",
            decision.approval_token,
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "sandbox" / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "open-model"
    assert command["args"]["detach"] is True


def test_install_addin_dry_run_reports_build_prerequisite(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "addin-test",
            "install-addin",
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["source_project"].endswith("HermesRevitOperator.csproj")
    assert "NET SDK" in output["build_prerequisite"]


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_install_addin_dry_run_supports_revit_2022_to_2027(tmp_path, capsys, version):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            f"addin-test-{version}",
            "install-addin",
            "--revit-version",
            version,
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert f"Addins\\{version}\\HermesRevitOperator.addin" in output["target_manifest"]
    assert str(assembly_subdir_for_revit_version(version)) in output["assembly_path"]


def test_install_addin_rejects_unsupported_revit_version(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "addin-unsupported-version-test",
            "install-addin",
            "--revit-version",
            "2021",
            "--addins-root",
            str(tmp_path / "Addins"),
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "Unsupported Revit version" in output["error"]


def test_default_assembly_path_prefers_newest_local_hermes_build(tmp_path, monkeypatch):
    monkeypatch.setattr(addin_installer, "addin_source_dir", lambda: tmp_path)
    legacy = tmp_path / "bin" / "Release" / "net8.0-windows" / "HermesRevitOperator.dll"
    current = (
        tmp_path
        / "bin"
        / "Release"
        / "net8.0-windows-current"
        / "HermesRevitOperator.dll"
    )
    legacy.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    current.write_bytes(b"current")
    os.utime(legacy, (1_770_000_000, 1_770_000_000))
    os.utime(current, (1_770_000_100, 1_770_000_100))

    assert addin_installer.default_assembly_path() == current
    assert addin_installer.is_default_local_assembly_path(current) is True
    assert addin_installer.is_default_local_assembly_path(tmp_path / "other.dll") is False


def test_default_assembly_path_prefers_version_specific_build(tmp_path, monkeypatch):
    monkeypatch.setattr(addin_installer, "addin_source_dir", lambda: tmp_path)
    versioned = tmp_path / assembly_subdir_for_revit_version("2024") / "HermesRevitOperator.dll"
    legacy = tmp_path / "bin" / "Release" / "net8.0-windows-current" / "HermesRevitOperator.dll"
    versioned.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    versioned.write_bytes(b"versioned")
    legacy.write_bytes(b"legacy")
    os.utime(versioned, (1_770_000_000, 1_770_000_000))
    os.utime(legacy, (1_770_000_100, 1_770_000_100))

    assert addin_installer.default_assembly_path("2024") == versioned
    assert versioned in addin_installer.default_assembly_candidates("2024")
    assert addin_installer.is_default_local_assembly_path(versioned, "2024") is True


def test_trust_addin_dry_run_reports_cert_store_impact(tmp_path, capsys):
    dll = tmp_path / "HermesRevitOperator.dll"
    dll.write_bytes(b"not a real dll")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "trust-test",
            "trust-addin",
            "--assembly",
            str(dll),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert "TrustedPublisher" in output["impact"]


def test_addin_security_preflight_verifies_expected_manifest_before_load(tmp_path):
    addins_root = tmp_path / "Addins"
    assembly = tmp_path / "build" / "HermesRevitOperator.dll"
    assembly.parent.mkdir()
    assembly.write_bytes(b"test dll")
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = addin_security_preflight(
        TaskJournal(tmp_path / "sandbox", "addin-security-test"),
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        signature_probe=lambda path: {
            "available": True,
            "path": str(path),
            "status": "NotSigned",
            "status_message": "The file is not signed.",
            "signer_subject": None,
            "signer_thumbprint": None,
        },
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["policy"]["decision"] == "allow"
    assert result["expected_local_hermes_addin"] is True
    assert result["needs_trust_addin"] is True
    assert result["can_consider_always_load_after_human_approval"] is True
    assert result["allowed_dialog_button"] == "Always Load"
    assert "trust-addin" in result["recommended_action"]


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_addin_security_preflight_accepts_supported_revit_versions(tmp_path, version):
    addins_root = tmp_path / "Addins"
    assembly = tmp_path / assembly_subdir_for_revit_version(version) / "HermesRevitOperator.dll"
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"test dll")
    manifest = addins_root / version / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = addin_security_preflight(
        TaskJournal(tmp_path / "sandbox", f"addin-security-test-{version}"),
        revit_version=version,
        addins_root=addins_root,
        assembly_path=assembly,
        signature_probe=lambda path: {
            "available": True,
            "path": str(path),
            "status": "NotSigned",
            "status_message": "The file is not signed.",
            "signer_subject": None,
            "signer_thumbprint": None,
        },
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["revit_version_supported"] is True
    assert result["revit_version"] == version
    assert result["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert result["expected_local_hermes_addin"] is True


def test_addin_source_reports_loaded_build_and_continuous_idling_capabilities():
    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")

    for marker in [
        "SetRaiseWithoutDelay()",
        "bridge_protocol_version",
        "source_capability_stamp",
        "supports_continuous_idling",
        "uses_idling_set_raise_without_delay",
        "assembly_last_write_utc",
    ]:
        assert marker in source


def test_qa_report_uses_bridge_metadata_and_labels_draft(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "document": {"title": "Test", "path": "model.rvt", "revit_version": "2025"},
                "levels": [{"name": "Level 1"}],
                "grids": [],
                "views": [],
                "sheets": [],
                "titleblocks": [],
                "links": [],
                "warnings": [{"description": "warning"}],
                "families": [],
                "types": [],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "qa-test",
            "qa-report",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    report = Path(output["path"])
    text = report.read_text(encoding="utf-8")
    assert DRAFT_LABEL in text
    assert "Revit warnings require review" in text


def test_cli_wait_for_window_times_out_cleanly(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "wait-test",
            "wait-for-window",
            "--title-contains",
            "__definitely_not_a_revit_window__",
            "--timeout",
            "0",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "Timed out" in output["error"]


def test_wait_model_ready_matches_idle_bridge_document(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "revit_running": True,
                "active_dialogs": [],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def active_document_status(self):
            return {
                "available": True,
                "document": {
                    "document": {
                        "title": "24522 Test Model",
                        "path": "C:/safe/model.rvt",
                        "revit_version": "2025",
                        "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                    }
                },
            }

    result = wait_model_ready(
        TaskJournal(tmp_path, "model-ready-test"),
        FakeObserver(),
        FakeBridge(),
        timeout=0,
        expected_title_contains="24522",
        expected_revit_version="2025",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["ready"] is True
    assert result["stop_reason"] == "model_ready"
    assert result["final_evaluation"]["document"]["title"] == "24522 Test Model"
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_wait_model_ready_stops_on_modal(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "modal",
                "revit_running": True,
                "active_dialogs": [{"title": "Unresolved References"}],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def active_document_status(self):
            return {"available": False, "status": "stub"}

    result = wait_model_ready(
        TaskJournal(tmp_path, "model-ready-modal-test"),
        FakeObserver(),
        FakeBridge(),
        timeout=10,
        poll=0.1,
    )

    assert result["success"] is False
    assert result["ready"] is False
    assert result["stop_reason"] == "modal_state_detected"
    assert result["final_check"]["active_dialog_count"] == 1


def test_cli_wait_model_ready_writes_status(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "revit_running": True,
                "active_dialogs": [],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def __init__(self, _sandbox):
            pass

        def active_document_status(self):
            return {
                "available": True,
                "document": {
                    "document": {
                        "title": "24522 Test Model",
                        "path": "C:/safe/model.rvt",
                        "revit_version": "2025",
                        "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                    }
                },
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(cli, "RevitBridgeClient", FakeBridge)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "model-ready-cli-test",
            "wait-model-ready",
            "--timeout",
            "0",
            "--expected-revit-version",
            "2025",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is True
    assert output["stop_reason"] == "model_ready"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_refuses_sandbox_outside_safe_root_without_override(tmp_path, capsys):
    code = cli.main(["--sandbox", str(tmp_path), "health"])

    assert code == 2
    err = json.loads(capsys.readouterr().err)
    assert "Sandbox must stay inside" in err["error"]


def test_bridge_wait_for_command_result_reads_jsonl(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.command_results_path.write_text(
        json.dumps({"id": "cmd-1", "success": True, "message": "ok"}) + "\n",
        encoding="utf-8",
    )

    result = bridge.wait_for_command_result("cmd-1", timeout=0, poll=0.1)

    assert result["success"] is True
    assert result["found"] is True
    assert result["result"]["message"] == "ok"


def test_bridge_status_reads_addin_build_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                    "assembly_last_write_utc": "2026-05-12T00:00:00Z",
                    "session_id": "abc",
                },
            }
        ),
        encoding="utf-8",
    )
    bridge.heartbeat_path.write_text(
        json.dumps({"status": "idling", "addin": {"session_id": "abc"}}),
        encoding="utf-8",
    )

    result = bridge.bridge_status()

    assert result["available"] is True
    assert result["status"] == "connected"
    addin = result["addin_status"]["payload"]["addin"]
    assert addin["supports_continuous_idling"] is True
    assert addin["uses_idling_set_raise_without_delay"] is True
    assert addin["assembly_last_write_utc"] == "2026-05-12T00:00:00Z"


def test_bridge_status_retries_temporarily_locked_json_payload(tmp_path, monkeypatch):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps({"status": "started", "addin": {"source_capability_stamp": "current"}}),
        encoding="utf-8",
    )
    bridge.heartbeat_path.write_text(
        json.dumps({"status": "idling", "addin": {"session_id": "abc"}}),
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    calls = {"heartbeat": 0}

    def flaky_read_text(path, *args, **kwargs):
        if Path(path) == bridge.heartbeat_path and calls["heartbeat"] < 2:
            calls["heartbeat"] += 1
            raise PermissionError("simulated writer lock")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    result = bridge.bridge_status()

    assert calls["heartbeat"] == 2
    assert result["available"] is True
    assert result["heartbeat"]["available"] is True
    assert result["heartbeat"]["payload"]["addin"]["session_id"] == "abc"


def test_verify_bridge_build_passes_for_expected_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                    "assembly_last_write_utc": "2026-05-12T00:00:00Z",
                    "session_id": "abc",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.verify_loaded_build()

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "current"
    assert result["recommendation"] == "loaded_build_verified"
    assert all(check["passed"] for check in result["checks"])


def test_verify_bridge_build_flags_stale_loaded_payload(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "session_id": "old-session",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.verify_loaded_build()

    assert result["success"] is False
    assert result["read_only"] is True
    assert result["status"] == "stale_or_unverified"
    assert "restart or reload Revit" in result["recommendation"]
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert "bridge_protocol_version" in failed
    assert "source_capability_stamp" in failed
    assert "supports_continuous_idling" in failed


def test_bridge_readiness_requires_restart_when_installed_but_loaded_stale(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
    )

    assert result["success"] is False
    assert result["read_only"] is True
    assert result["status"] == "not_ready"
    assert result["ready_for_continuous_bridge"] is False
    assert result["requires_revit_restart_or_reload"] is True
    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["built_assembly_present"] is True
    assert checks["manifest_present"] is True
    assert checks["manifest_points_to_expected_assembly"] is True
    assert checks["loaded_build_current"] is False
    assert result["check_count"] == len(result["checks"])
    assert result["failed_check_count"] == 1
    assert result["failed_checks"] == ["loaded_build_current"]
    assert "loaded_build_current" not in result["passed_checks"]
    assert any("restart or reload Revit" in step for step in result["next_steps"])


@pytest.mark.parametrize("version", SUPPORTED_REVIT_VERSIONS)
def test_bridge_readiness_uses_revit_version_specific_manifest_and_framework(tmp_path, version):
    bridge = RevitBridgeClient(tmp_path)
    assembly = tmp_path / assembly_subdir_for_revit_version(version) / "HermesRevitOperator.dll"
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / version / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version=version,
        addins_root=addins_root,
        assembly_path=assembly,
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["revit_version_supported"] is True
    assert result["revit_version"] == version
    assert result["target_framework"] == REVIT_TARGET_FRAMEWORK_BY_VERSION[version]
    assert result["paths"]["manifest"].endswith(f"Addins\\{version}\\HermesRevitOperator.addin")
    assert result["supported_revit_versions"] == list(SUPPORTED_REVIT_VERSIONS)


def test_bridge_readiness_rejects_unsupported_revit_version(tmp_path):
    bridge = RevitBridgeClient(tmp_path)

    result = bridge.bridge_readiness(revit_version="2021", addins_root=tmp_path / "Addins")

    assert result["success"] is False
    assert result["target_framework"] is None
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["revit_version_supported"]["passed"] is False
    assert "Unsupported Revit version" in checks["revit_version_supported"]["reason"]


def test_bridge_readiness_default_accepts_current_unlocked_build_path(tmp_path, monkeypatch):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = (
        tmp_path
        / "source"
        / "bin"
        / "Release"
        / "net8.0-windows-current"
        / "HermesRevitOperator.dll"
    )
    assembly.parent.mkdir(parents=True)
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    monkeypatch.setattr(bridge_module, "default_assembly_path", lambda *_args: assembly)

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
    )

    checks = {check["name"]: check["passed"] for check in result["checks"]}
    assert checks["manifest_points_to_expected_assembly"] is True
    assert checks["built_assembly_present"] is True
    assert result["failed_checks"] == ["loaded_build_current"]
    assert result["requires_revit_restart_or_reload"] is True


def test_bridge_readiness_passes_when_installed_and_loaded_current(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "session_id": "current-session",
                },
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    result = bridge.bridge_readiness(
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
    )

    assert result["success"] is True
    assert result["status"] == "ready"
    assert result["ready_for_continuous_bridge"] is True
    assert result["requires_revit_restart_or_reload"] is False
    assert all(check["passed"] for check in result["checks"])
    assert result["failed_check_count"] == 0
    assert result["failed_checks"] == []
    assert set(result["passed_checks"]) == {check["name"] for check in result["checks"]}


def test_cli_bridge_readiness_reports_restart_gate(tmp_path, capsys):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-readiness-test",
            "bridge-readiness",
            "--addins-root",
            str(addins_root),
            "--assembly",
            str(assembly),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["read_only"] is True
    assert output["requires_revit_restart_or_reload"] is True
    assert output["failed_checks"] == ["loaded_build_current"]


def test_bridge_restart_validation_plan_requires_human_for_stale_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    bridge.active_document_path.write_text(
        json.dumps(
            {
                "title": "24522 detached",
                "path": "24522 detached.rvt",
                "revit_version": "2025",
                "dirty": True,
                "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
            }
        ),
        encoding="utf-8",
    )

    def security_stub(*_args, **_kwargs):
        return {
            "status": "verified",
            "expected_local_hermes_addin": True,
            "needs_trust_addin": False,
            "can_consider_always_load_after_human_approval": True,
            "allowed_dialog_button": "Always Load",
            "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
            "paths": {
                "manifest": str(manifest),
                "expected_assembly": str(assembly),
            },
            "signature": {
                "status": "Valid",
                "signer_subject": "CN=Hermes Revit Operator Local Code Signing",
            },
            "recommended_action": "Click Always Load only with exact human approval.",
        }

    result = bridge_restart_validation_plan(
        TaskJournal(tmp_path, "bridge-restart-validation-plan-test"),
        bridge,
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        expected_title_contains="24522",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        security_preflight_fn=security_stub,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "human_restart_required"
    assert result["pre_restart_files_ready"] is True
    assert result["restart_or_reload_required"] is True
    assert result["human_handoff_required"] is True
    assert any("must not close or restart Revit" in item for item in result["blocked_automation"])
    assert any("verify-bridge-build" in command for command in result["post_restart_validation_commands"])
    assert any("wait-model-ready" in command for command in result["post_restart_validation_commands"])
    assert Path(result["path"]).exists()
    checklist = Path(result["no_save_checklist_path"])
    assert checklist.exists()
    checklist_text = checklist.read_text(encoding="utf-8")
    assert "dirty: `True`" in checklist_text
    assert "Save/discard decisions are human-only" in checklist_text
    assert "Hermes must not answer" in checklist_text
    assert "Bridge Reload Cause" in checklist_text
    assert "Loaded Revit add-in is stale or lacks current bridge build metadata" in checklist_text
    assert "failed_readiness_checks: `loaded_build_current`" in checklist_text
    assert "bridge_protocol_version=`0.2`" in checklist_text
    assert "source_capability_stamp=`continuous-idling-status-file-retry-v2`" in checklist_text
    assert "supports_continuous_idling=`True`" in checklist_text
    assert "uses_idling_set_raise_without_delay=`True`" in checklist_text
    assert result["addin_security_preflight"]["status"] == "verified"
    assert "Add-In Startup Prompt Preflight" in checklist_text
    assert "addin_security_status: `verified`" in checklist_text
    assert "allowed_dialog_button_after_human_approval: `Always Load`" in checklist_text
    assert "blocked_dialog_buttons: `Load Once`, `Do Not Load`" in checklist_text
    assert "signature_status: `Valid`" in checklist_text
    assert "Hermes must not click it from this checklist" in checklist_text
    assert "`north-star-completion-gate`" in checklist_text
    assert "`north-star-resume-check.completion_gate`" in checklist_text
    assert "`completion_allowed: true`" in checklist_text
    assert "`may_call_update_goal: true`" in checklist_text
    assert "`audit_completion_authorized: true`" in checklist_text
    assert "Status and audit summaries are diagnostic only." in checklist_text
    assert "fresh status or audit artifact reports" not in checklist_text
    assert result["active_document"]["document"]["dirty"] is True


def test_bridge_restart_validation_plan_checklist_handles_nested_document_status(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")
    bridge.active_document_path.write_text(
        json.dumps(
            {
                "available": True,
                "status": "connected",
                "document": {
                    "title": "24522 nested detached",
                    "path": "24522 nested detached.rvt",
                    "revit_version": "2025",
                    "dirty": True,
                    "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                },
            }
        ),
        encoding="utf-8",
    )

    def security_stub(*_args, **_kwargs):
        return {
            "status": "needs_attention",
            "expected_local_hermes_addin": True,
            "needs_trust_addin": True,
            "can_consider_always_load_after_human_approval": True,
            "allowed_dialog_button": "Always Load",
            "blocked_dialog_buttons": ["Load Once", "Do Not Load"],
            "paths": {
                "manifest": str(manifest),
                "expected_assembly": str(assembly),
            },
            "signature": {"status": "NotSigned", "signer_subject": None},
            "recommended_action": "Sign/trust the local add-in before restarting.",
        }

    result = bridge_restart_validation_plan(
        TaskJournal(tmp_path, "bridge-restart-validation-plan-nested-doc-test"),
        bridge,
        revit_version="2025",
        addins_root=addins_root,
        assembly_path=assembly,
        expected_title_contains="24522",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        security_preflight_fn=security_stub,
    )

    checklist_text = Path(result["no_save_checklist_path"]).read_text(encoding="utf-8")
    assert "title: `24522 nested detached`" in checklist_text
    assert "path: `24522 nested detached.rvt`" in checklist_text
    assert "active_view: `STARTING VIEW`" in checklist_text
    assert "dirty: `True`" in checklist_text
    assert "Save/discard decisions are human-only" in checklist_text
    assert "failed_readiness_checks: `loaded_build_current`" in checklist_text
    assert "addin_security_status: `needs_attention`" in checklist_text
    assert "needs_trust_addin: `True`" in checklist_text


def test_cli_bridge_restart_validation_plan_writes_readonly_artifact(tmp_path, capsys):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-restart-validation-plan-cli-test",
            "bridge-restart-validation-plan",
            "--addins-root",
            str(addins_root),
            "--assembly",
            str(assembly),
            "--expected-title-contains",
            "24522",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "human_restart_required"
    assert output["restart_or_reload_required"] is True
    assert Path(output["path"]).exists()
    assert Path(output["no_save_checklist_path"]).exists()


def test_bridge_post_restart_validation_passes_for_current_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                    "supports_continuous_idling": True,
                    "uses_idling_set_raise_without_delay": True,
                    "session_id": "current-session",
                },
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    class Observer:
        def status(self):
            return {
                "supported": True,
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025", "is_hung": False},
            }

    def security_stub(*_args, **_kwargs):
        return {"success": True, "read_only": True, "status": "verified"}

    def ready_stub(*_args, **_kwargs):
        return {"success": True, "read_only": True, "ready": True, "path": str(tmp_path / "ready.json")}

    def audit_stub(*_args, **_kwargs):
        return {
            "success": True,
            "status": "not_complete",
            "north_star_complete": False,
            "implementation_package_complete": True,
            "blocker_summary": {"blocked_gap_count": 3},
            "remaining_gaps": [],
            "path": str(tmp_path / "audit.json"),
        }

    result = bridge_post_restart_validation(
        TaskJournal(tmp_path, "bridge-post-restart-validation-test"),
        Observer(),
        bridge,
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        addins_root=addins_root,
        assembly_path=assembly,
        security_preflight_fn=security_stub,
        wait_model_ready_fn=ready_stub,
        north_star_audit_fn=audit_stub,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "passed"
    assert result["validation_passed"] is True
    assert result["failed_checks"] == []
    assert result["failed_check_count"] == 0
    assert all(check["passed"] for check in result["checks"])
    assert result["verify_bridge_build"]["status"] == "current"
    assert result["verify_bridge_build_status"] == "current"
    assert result["verify_bridge_build_success"] is True
    assert result["verify_bridge_build_failed_checks"] == []
    assert result["bridge_readiness"]["ready_for_continuous_bridge"] is True
    assert result["ready_for_continuous_bridge"] is True
    assert result["requires_revit_restart_or_reload"] is False
    assert result["bridge_readiness_failed_checks"] == []
    assert result["model_ready_ready"] is True
    assert "does not close, restart" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_bridge_post_restart_validation_fails_for_stale_loaded_bridge(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )
    assembly = tmp_path / "HermesRevitOperator.dll"
    assembly.write_bytes(b"fake-dll")
    addins_root = tmp_path / "Addins"
    manifest = addins_root / "2025" / "HermesRevitOperator.addin"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(addin_manifest_text(assembly), encoding="utf-8")

    class Observer:
        def status(self):
            return {
                "supported": True,
                "revit_running": True,
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025", "is_hung": False},
            }

    result = bridge_post_restart_validation(
        TaskJournal(tmp_path, "bridge-post-restart-validation-stale-test"),
        Observer(),
        bridge,
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        addins_root=addins_root,
        assembly_path=assembly,
        security_preflight_fn=lambda *_args, **_kwargs: {"status": "verified"},
        wait_model_ready_fn=lambda *_args, **_kwargs: {"ready": True, "path": str(tmp_path / "ready.json")},
        north_star_audit_fn=lambda *_args, **_kwargs: {"success": True, "path": str(tmp_path / "audit.json")},
    )

    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["failed_check_count"] == len(result["failed_checks"])
    assert "loaded_build_current" in failed
    assert "bridge_readiness_ready" in failed
    assert result["failed_checks"] == [
        check["name"] for check in result["checks"] if not check["passed"]
    ]
    assert result["bridge_readiness"]["requires_revit_restart_or_reload"] is True
    assert result["requires_revit_restart_or_reload"] is True
    assert result["ready_for_continuous_bridge"] is False
    assert result["verify_bridge_build_status"] == "stale_or_unverified"
    assert "bridge_protocol_version" in result["verify_bridge_build_failed_checks"]
    assert "loaded_build_current" in result["bridge_readiness_failed_checks"]
    assert result["model_ready_ready"] is True


def test_active_document_status_includes_bridge_status_metadata(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    bridge.bridge_dir.mkdir()
    bridge.active_document_path.write_text(
        json.dumps({"available": True, "document": {"title": "Sample"}}),
        encoding="utf-8",
    )
    bridge.addin_status_path.write_text(
        json.dumps(
            {
                "status": "started",
                "addin": {
                    "bridge_protocol_version": "0.2",
                    "source_capability_stamp": "continuous-idling-status-file-retry-v2",
                },
            }
        ),
        encoding="utf-8",
    )

    result = bridge.active_document_status()

    assert result["available"] is True
    assert result["bridge"]["available"] is True
    addin = result["bridge"]["addin_status"]["payload"]["addin"]
    assert addin["source_capability_stamp"] == "continuous-idling-status-file-retry-v2"


def test_cli_bridge_status_reads_addin_status(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {
                    "supports_continuous_idling": True,
                    "assembly_path": "C:/temp/HermesRevitOperator.dll",
                },
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-status-test",
            "bridge-status",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["available"] is True
    assert output["addin_status"]["payload"]["addin"]["supports_continuous_idling"] is True


def test_cli_verify_bridge_build_reports_stale_payload(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "addin_status.json").write_text(
        json.dumps(
            {
                "status": "started",
                "revit_version": "2025",
                "addin": {"session_id": "old-session"},
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "verify-bridge-build-test",
            "verify-bridge-build",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["read_only"] is True
    assert output["status"] == "stale_or_unverified"
    assert "restart or reload Revit" in output["recommendation"]


def test_cli_bridge_results_lists_recent_results(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "command_results.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "cmd-1", "success": True}),
                json.dumps({"id": "cmd-2", "success": False, "error": "failed"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-results-test",
            "bridge-results",
            "--limit",
            "1",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert output["results"][0]["id"] == "cmd-2"


def test_cli_wait_bridge_result_returns_matching_result(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "command_results.jsonl").write_text(
        json.dumps({"id": "cmd-1", "success": True, "message": "done"}) + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "wait-bridge-test",
            "wait-bridge-result",
            "--command-id",
            "cmd-1",
            "--timeout",
            "0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["found"] is True
    assert output["result"]["message"] == "done"


def test_cli_record_workflow_writes_sandbox_template_without_tokens(tmp_path, capsys):
    journal = TaskJournal(tmp_path, "source-run")
    journal.write_entry(
        {
            "command": "click",
            "requested_action": {"target": "Cancel"},
            "risk_classification": {
                "action": "click",
                "risk": "high",
                "decision": "approval_required",
                "reason": "test",
                "approval_token": "APPROVE:do-not-reuse",
            },
            "approval_status": {"allowed": True, "reason": "test"},
            "result": {"status": "clicked", "success": True},
            "observed_ui_state_before_action": {
                "state": "modal",
                "main_window": {
                    "title": "Autodesk Revit 2025 - 24522 St John XXIII Youth Pavilion",
                    "revit_version": "2025",
                },
                "active_dialogs": [{"title": "Family Load Options"}],
                "dialog_details": {
                    "dialogs": [
                        {
                            "title": "Family Load Options",
                            "dialog_text": "The family already exists in the project.",
                            "buttons": ["Overwrite", "Cancel"],
                        }
                    ]
                },
                "active_document": {
                    "document": {
                        "document": {
                            "title": "24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM",
                            "path": (
                                r"C:\sandbox\24522 St John XXIII Youth Pavilion-Structural_"
                                r"Current Working-R25-BIM.rvt"
                            ),
                            "revit_version": "2025",
                            "active_view": {"name": "S101", "type": "DrawingSheet"},
                        }
                    }
                },
            },
        }
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "record-workflow-test",
            "record-workflow",
            "--source-task-id",
            "source-run",
            "--name",
            "Cancel Dialog",
            "--description",
            "test workflow",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    workflow = json.loads(Path(output["path"]).read_text(encoding="utf-8"))
    assert workflow["replay_policy"]["requires_fresh_safety_classification"] is True
    assert workflow["replay_policy"]["parameter_overrides_are_reclassified"] is True
    assert workflow["parameters"][0]["name"] == "step_0_target"
    assert workflow["parameters"][0]["default"] == "Cancel"
    assert workflow["steps"][0]["parameter_bindings"][0]["path"] == ["target"]
    assert workflow["steps"][0]["risk_classification"].get("approval_token") is None
    predicates = workflow["steps"][0]["state_predicates"]
    assert predicates["schema"] == "hermes-revit-replay-state-predicates/v2"
    assert predicates["allowed_states"] == ["modal"]
    assert predicates["reject_modal"] is False
    assert predicates["dialog"]["title"] == "Family Load Options"
    assert predicates["dialog"]["buttons"] == ["Overwrite", "Cancel"]
    assert predicates["document"]["revit_version"] == "2025"
    assert predicates["document"]["active_view"]["name"] == "S101"


def test_cli_workflow_library_lists_recorded_templates(tmp_path, capsys):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    (library / "sample.json").write_text(
        json.dumps({"name": "Sample", "source_task_id": "source", "step_count": 1}),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "workflow-library-test",
            "workflow-library",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["workflows"][0]["name"] == "Sample"


def test_workflow_approval_plan_generates_fresh_tokens_and_blocks_overrides(tmp_path):
    source = TaskJournal(tmp_path, "workflow-approval-source")
    source.write_entry(
        {
            "command": "click",
            "requested_action": {"target": "Cancel"},
            "risk_classification": {
                "action": "click",
                "risk": "high",
                "decision": "approval_required",
                "reason": "recorded",
                "approval_token": "APPROVE:do-not-reuse",
            },
            "approval_status": {"allowed": True, "reason": "recorded"},
            "result": {"status": "clicked", "success": True},
            "observed_ui_state_before_action": {
                "state": "modal",
                "active_dialogs": [{"title": "Family Load Options"}],
                "dialog_details": {"dialogs": [{"title": "Family Load Options", "buttons": ["Cancel"]}]},
            },
        }
    )
    recorded = record_workflow(
        tmp_path,
        source_task_id="workflow-approval-source",
        name="Approval Replay",
    )

    assert recorded["success"] is True
    result = plan_workflow_approvals(
        tmp_path,
        TaskJournal(tmp_path, "workflow-approval-plan-test"),
        name="Approval Replay",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["dry_run_only"] is True
    assert result["template_contains_approval_tokens"] is False
    assert result["stale_approval_tokens_reused"] is False
    assert result["approval_required_count"] == 1
    assert result["blocked_count"] == 0
    token = result["approval_steps"][0]["approval_token"]
    assert token.startswith("APPROVE:")
    assert token != "APPROVE:do-not-reuse"
    assert result["approval_tokens_json"] == {"0": token}
    assert "replay-workflow" in result["replay_execute_command_requires_human"]
    assert Path(result["path"]).exists()

    blocked = plan_workflow_approvals(
        tmp_path,
        TaskJournal(tmp_path, "workflow-approval-blocked-plan-test"),
        name="Approval Replay",
        parameters={"step_0_target": "Save"},
    )

    assert blocked["success"] is True
    assert blocked["approval_required_count"] == 0
    assert blocked["blocked_count"] == 1
    assert blocked["replay_execute_command_requires_human"] is None


def test_cli_workflow_approval_plan_writes_readonly_artifact(tmp_path, capsys):
    source = TaskJournal(tmp_path, "workflow-approval-cli-source")
    source.write_entry(
        {
            "command": "click",
            "requested_action": {"target": "Cancel"},
            "risk_classification": {
                "action": "click",
                "risk": "high",
                "decision": "approval_required",
                "reason": "recorded",
                "approval_token": "APPROVE:do-not-reuse",
            },
            "approval_status": {"allowed": True, "reason": "recorded"},
            "result": {"status": "clicked", "success": True},
            "observed_ui_state_before_action": {"state": "modal"},
        }
    )
    record_workflow(
        tmp_path,
        source_task_id="workflow-approval-cli-source",
        name="Approval CLI Replay",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "workflow-approval-plan-cli-test",
            "workflow-approval-plan",
            "--name",
            "Approval CLI Replay",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["approval_required_count"] == 1
    assert output["stale_approval_tokens_reused"] is False
    assert Path(output["path"]).exists()


def test_ui_workflows_list_contains_guarded_recipes():
    result = list_ui_workflows()

    names = {workflow["name"] for workflow in result["workflows"]}
    assert result["success"] is True
    assert "manage-links-inspection" in names
    assert "project-browser-open-sheet" in names
    assert "modal-dialog-recovery" in names
    modal = next(workflow for workflow in result["workflows"] if workflow["name"] == "modal-dialog-recovery")
    assert len(modal["approval_gates"]) == 1


def test_ui_workflow_matrix_validates_all_recipes(tmp_path):
    result = validate_ui_workflow_matrix(TaskJournal(tmp_path, "ui-workflow-matrix-test"))

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["recipe_count"] >= 10
    assert result["step_count"] >= 30
    assert result["approval_gated_step_count"] >= 1
    assert result["manual_placeholder_count"] >= 1
    assert result["blocked_step_count"] == 0
    assert result["failed_cases"] == []
    assert Path(result["path"]).exists()
    project_browser = next(case for case in result["cases"] if case["name"] == "project-browser-open-sheet")
    assert project_browser["parameters"]["sheet_number"] == "S2.0"
    assert project_browser["approval_step_indexes"]


def test_cli_ui_workflow_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ui-workflow-matrix-cli-test",
            "ui-workflow-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["recipe_count"] >= 10
    assert Path(output["path"]).exists()


def test_ui_workflow_smoke_matrix_runs_only_smoke_safe_steps(tmp_path):
    calls = []

    def fake_runner(argv, recipe_name, step_index):
        calls.append((recipe_name, step_index, argv))
        return {"success": True, "recipe_name": recipe_name, "step_index": step_index, "argv": argv}

    result = run_ui_workflow_smoke_matrix(
        TaskJournal(tmp_path, "ui-workflow-smoke-matrix-test"),
        observe_func=lambda: {"state": "idle", "active_dialogs": []},
        command_runner=fake_runner,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["recipe_count"] >= 10
    assert result["ran_step_count"] >= 10
    assert result["failed_cases"] == []
    forbidden = {"click", "ribbon-action", "request-operation", "context-menu-action", "qa-workflow"}
    assert not any(call[2][0] in forbidden for call in calls)
    assert any(case["stop_reason"] == "Smoke matrix does not supply approval tokens." for case in result["cases"])
    assert Path(result["path"]).exists()


def test_ui_workflow_smoke_matrix_treats_stale_bridge_as_diagnostic(tmp_path):
    def fake_runner(argv, recipe_name, _step_index):
        if recipe_name == "bridge-readiness-gate" and argv[0] == "bridge-readiness":
            return {
                "success": False,
                "read_only": True,
                "status": "not_ready",
                "ready_for_continuous_bridge": False,
            }
        if recipe_name == "bridge-readiness-gate" and argv[0] == "verify-bridge-build":
            return {
                "success": False,
                "read_only": True,
                "status": "stale_or_unverified",
            }
        return {"success": True, "argv": argv}

    result = run_ui_workflow_smoke_matrix(
        TaskJournal(tmp_path, "ui-workflow-smoke-bridge-diagnostic-test"),
        observe_func=lambda: {"state": "idle", "active_dialogs": []},
        command_runner=fake_runner,
    )

    assert result["success"] is True
    bridge_case = next(case for case in result["cases"] if case["name"] == "bridge-readiness-gate")
    assert bridge_case["success"] is True
    assert [step["status"] for step in bridge_case["step_results"][:2]] == [
        "ran_diagnostic_false",
        "ran_diagnostic_false",
    ]


def test_cli_ui_workflow_smoke_matrix_uses_smoke_runner(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    def fake_runner_factory(*_args, **_kwargs):
        def fake_runner(argv, recipe_name, step_index):
            return {"success": True, "recipe_name": recipe_name, "step_index": step_index, "argv": argv}

        return fake_runner

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(cli, "_ui_workflow_smoke_command_runner", fake_runner_factory)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "ui-workflow-smoke-matrix-cli-test",
            "ui-workflow-smoke-matrix",
            "--max-steps-per-recipe",
            "2",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["recipe_count"] >= 10
    assert Path(output["path"]).exists()


def test_plan_ui_workflow_reports_missing_parameters(tmp_path):
    result = plan_ui_workflow(
        TaskJournal(tmp_path, "ui-workflow-missing-param-test"),
        name="project-browser-open-sheet",
    )

    assert result["success"] is False
    assert result["planned_only"] is True
    assert result["missing_parameters"] == ["sheet_number"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_plan_ui_workflow_renders_safe_project_browser_recipe(tmp_path):
    result = plan_ui_workflow(
        TaskJournal(tmp_path, "ui-workflow-project-browser-test"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["step_count"] == 4
    assert result["steps"][1]["command"] == "wait-model-ready"
    assert result["steps"][2]["command"] == "project-browser-plan-navigation"
    assert "S2.0" in result["steps"][2]["args"]
    assert result["steps"][3]["requires_approval"] is True
    assert result["steps"][3]["executable_by_plan"] is False


def test_plan_ui_workflow_renders_unsigned_addin_startup_preflight(tmp_path):
    result = plan_ui_workflow(
        TaskJournal(tmp_path, "ui-workflow-unsigned-addin-test"),
        name="unsigned-addin-startup-preflight",
    )

    assert result["success"] is True
    assert result["step_count"] == 4
    assert result["steps"][0]["command"] == "list-dialogs"
    assert result["steps"][1]["command"] == "plan-current-dialog-response"
    assert result["steps"][2]["command"] == "addin-security-preflight"
    assert result["steps"][3]["command"] == "click"
    assert "Always Load" in result["steps"][3]["args"]
    assert result["steps"][3]["requires_approval"] is True


def test_cli_plan_ui_workflow_accepts_convenience_parameters(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "plan-ui-workflow-test",
            "plan-ui-workflow",
            "--name",
            "project-browser-open-sheet",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["parameters"]["sheet_number"] == "S2.0"
    assert output["note"].startswith("Planning only")


def test_run_ui_workflow_runs_low_risk_steps_then_stops_for_missing_token(tmp_path):
    calls = []

    def fake_runner(argv, index):
        calls.append((index, argv))
        return {"success": True, "argv": argv}

    result = run_ui_workflow(
        TaskJournal(tmp_path, "run-ui-workflow-token-gate-test"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
        observe_func=lambda: {"state": "idle", "active_dialogs": []},
        command_runner=fake_runner,
    )

    assert result["success"] is False
    assert result["executed_steps"] == [0, 1, 2]
    assert result["skipped_steps"] == [3]
    assert "approval token" in result["stop_reason"].lower()
    assert calls[0][1][0] == "status"
    assert calls[1][1][0] == "wait-model-ready"
    assert calls[2][1][0] == "project-browser-plan-navigation"


def test_run_ui_workflow_execute_uses_fresh_step_token(tmp_path):
    plan = plan_ui_workflow(
        TaskJournal(tmp_path, "run-ui-workflow-token-plan-test"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
    )
    token = plan["steps"][3]["policy"]["approval_token"]
    calls = []

    def fake_runner(argv, index):
        calls.append((index, argv))
        return {"success": True, "argv": argv}

    live_state = {"state": "idle", "revit_running": True, "active_dialogs": [], "main_window": {"hwnd": 100}}
    journal = TaskJournal(tmp_path, "live-workflow-execute-token-unit")
    result = run_ui_workflow(
        journal,
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
        dry_run=False,
        approval_tokens={3: token},
        observe_func=lambda: live_state,
        command_runner=fake_runner,
    )

    assert result["success"] is True
    assert result["executed_steps"] == [0, 1, 2, 3]
    assert result["approved_executed_steps"] == [3]
    assert calls[3][1][:3] == ["request-operation", "--operation", "activate-view"]
    assert "--execute" in calls[3][1]
    assert token in calls[3][1]
    entry = json.loads(journal.journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["command"] == "run-ui-workflow"
    assert entry["observed_ui_state_before_action"]["main_window"]["hwnd"] == 100
    assert entry["observed_ui_state_after_action"]["main_window"]["hwnd"] == 100
    assert entry["result"]["approved_executed_steps"] == [3]
    coverage = audit_ui_execution_coverage(
        TaskJournal(tmp_path, "workflow-execution-coverage-check"),
        required_surfaces=["approved-ui-workflow-step"],
    )
    assert coverage["target_met"] is True
    assert coverage["surface_counts"]["approved-ui-workflow-step"] == 1


def test_ui_execution_coverage_does_not_count_low_risk_workflow_steps_without_approval(tmp_path):
    live_state = {"state": "idle", "revit_running": True, "active_dialogs": [], "main_window": {"hwnd": 100}}
    journal = TaskJournal(tmp_path, "live-workflow-low-risk-only-unit")
    result = run_ui_workflow(
        journal,
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
        dry_run=False,
        max_steps=3,
        observe_func=lambda: live_state,
        command_runner=lambda argv, index: {"success": True, "argv": argv, "index": index},
    )

    assert result["success"] is True
    assert result["executed_steps"] == [0, 1, 2]
    assert result["approved_executed_steps"] == []
    coverage = audit_ui_execution_coverage(
        TaskJournal(tmp_path, "workflow-low-risk-coverage-check"),
        required_surfaces=["approved-ui-workflow-step"],
    )
    assert coverage["target_met"] is False
    assert coverage["surface_counts"]["approved-ui-workflow-step"] == 0


def test_run_ui_workflow_stops_non_modal_recipe_on_modal_state(tmp_path):
    calls = []

    result = run_ui_workflow(
        TaskJournal(tmp_path, "run-ui-workflow-modal-gate-test"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
        observe_func=lambda: {"state": "modal", "active_dialogs": [{"title": "Upgrade"}]},
        command_runner=lambda argv, index: calls.append((index, argv)) or {"success": True},
    )

    assert result["success"] is False
    assert result["executed_steps"] == [0, 1]
    assert result["skipped_steps"] == [2]
    assert "modal" in result["stop_reason"].lower()
    assert calls == [(0, ["status"]), (1, ["wait-model-ready", "--expected-revit-version", "2025"])]


def test_cli_run_ui_workflow_executes_observation_steps_and_stops_without_token(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "run-ui-workflow-cli-test",
            "run-ui-workflow",
            "--name",
            "project-browser-open-sheet",
            "--sheet-number",
            "S2.0",
            "--max-steps",
            "1",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["executed_steps"] == [0]
    assert output["step_results"][0]["command_result"]["state"] == "idle"


def test_cli_plan_workflow_reclassifies_steps_without_execution(tmp_path, capsys):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "replay_policy": {"requires_fresh_safety_classification": True},
                "steps": [
                    {"command": "status", "requested_action": {}},
                    {
                        "command": "click",
                        "requested_action": {"target": "Cancel"},
                        "parameter_bindings": [
                            {
                                "name": "step_1_target",
                                "path": ["target"],
                                "default": "Cancel",
                            }
                        ],
                    },
                    {"command": "click", "requested_action": {"target": "Save"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "plan-workflow-test",
            "plan-workflow",
            "--name",
            "sample.json",
            "--parameters-json",
            '{"step_1_target":"OK"}',
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["planned_steps"][0]["will_execute"] is False
    assert output["parameter_overrides"] == {"step_1_target": "OK"}
    assert output["planned_steps"][1]["payload"]["target"] == "OK"
    assert output["approval_required_steps"] == [1]
    assert output["blocked_steps"] == [2]


def test_cli_replay_workflow_dry_run_uses_fresh_observation(tmp_path, capsys, monkeypatch):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "replay_policy": {"requires_fresh_observation": True},
                "steps": [
                    {"command": "press-key", "requested_action": {"key": "Escape"}},
                    {
                        "command": "click",
                        "requested_action": {"target": "Cancel"},
                        "parameter_bindings": [
                            {
                                "name": "step_1_target",
                                "path": ["target"],
                                "default": "Cancel",
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "replay-workflow-test",
            "replay-workflow",
            "--name",
            "sample.json",
            "--parameters-json",
            '{"step_1_target":"OK"}',
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["steps"][0]["fresh_observation"]["state"] == "idle"
    assert output["steps"][0]["status"] == "dry_run"
    assert output["parameter_overrides"] == {"step_1_target": "OK"}
    assert output["steps"][1]["payload"]["target"] == "OK"
    assert output["steps"][1]["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["steps"][1]["executed"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_replay_workflow_stops_on_active_document_predicate_mismatch(tmp_path):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "steps": [
                    {
                        "command": "press-key",
                        "requested_action": {"key": "Escape"},
                        "state_predicates": {
                            "schema": "hermes-revit-replay-state-predicates/v2",
                            "recorded_pre_state": "idle",
                            "allowed_states": ["idle"],
                            "recorded_state_replayable": True,
                            "reject_modal": True,
                            "requires_no_active_dialogs": True,
                            "document": {
                                "title": "Expected Model",
                                "path_basename": "Expected Model.rvt",
                                "revit_version": "2025",
                                "active_view": {"name": "S101", "type": "DrawingSheet"},
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "active_document": {
                    "document": {
                        "document": {
                            "title": "Different Model",
                            "path": r"C:\sandbox\Different Model.rvt",
                            "revit_version": "2025",
                            "active_view": {"name": "S101", "type": "DrawingSheet"},
                        }
                    }
                },
            }

    result = replay_workflow(
        tmp_path,
        TaskJournal(tmp_path, "replay-document-gate-test"),
        FakeObserver(),
        name="sample.json",
    )

    assert result["success"] is False
    assert result["steps"][0]["status"] == "stopped_state_gate"
    assert "active document title" in result["stop_reason"].lower()
    assert result["steps"][0]["state_gate"]["checks"][-1]["passed"] is False


def test_replay_workflow_modal_predicate_requires_matching_dialog(tmp_path):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "steps": [
                    {
                        "command": "click",
                        "requested_action": {"target": "Cancel"},
                        "state_predicates": {
                            "schema": "hermes-revit-replay-state-predicates/v2",
                            "recorded_pre_state": "modal",
                            "allowed_states": ["modal"],
                            "recorded_state_replayable": True,
                            "reject_modal": False,
                            "requires_modal_dialog": True,
                            "dialog": {
                                "title": "Family Load Options",
                                "buttons": ["Cancel"],
                                "text_terms": ["family", "already", "exists"],
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Upgrade Model"}]}

        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "title": "Upgrade Model",
                        "dialog_text": "This model must be upgraded.",
                        "buttons": ["Upgrade", "Cancel"],
                    }
                ],
            }

    result = replay_workflow(
        tmp_path,
        TaskJournal(tmp_path, "replay-dialog-gate-test"),
        FakeObserver(),
        name="sample.json",
    )

    assert result["success"] is False
    assert result["steps"][0]["status"] == "stopped_state_gate"
    assert "dialog" in result["stop_reason"].lower()


def test_safe_action_executor_records_bridge_active_document_context(tmp_path):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "active_document.json").write_text(
        json.dumps(
            {
                "available": True,
                "status": "connected",
                "document": {
                    "title": "Bridge Model",
                    "path": r"C:\sandbox\Bridge Model.rvt",
                    "revit_version": "2025",
                    "active_view": {"name": "S102", "type": "DrawingSheet"},
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        supported = False

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    journal = TaskJournal(tmp_path, "action-bridge-context-test")
    result = SafeActionExecutor(FakeObserver(), journal).run(
        ActionRequest(action="press-key", payload={"key": "Escape"}, dry_run=True)
    )

    assert result["before"]["active_document"]["available"] is True
    record = json.loads(journal.journal_path.read_text(encoding="utf-8").splitlines()[-1])
    before = record["observed_ui_state_before_action"]
    assert before["active_document"]["document"]["document"]["title"] == "Bridge Model"


def test_replay_workflow_execute_queues_request_operation_with_fresh_token(tmp_path):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S2.0"},
        "allow_model_write": False,
        "allow_sync": False,
    }
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "steps": [{"command": "request-operation", "requested_action": payload}],
            }
        ),
        encoding="utf-8",
    )
    decision = classify_action("request-operation", payload)

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    result = replay_workflow(
        tmp_path,
        TaskJournal(tmp_path, "replay-execute-test"),
        FakeObserver(),
        name="sample.json",
        dry_run=False,
        approval_tokens={0: decision.approval_token},
    )

    assert result["success"] is True
    assert result["executed_steps"] == [0]
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "activate-view"
    assert command["args"]["sheet_number"] == "S2.0"


def test_replay_workflow_execute_stops_without_fresh_token(tmp_path):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S2.0"},
        "allow_model_write": False,
        "allow_sync": False,
    }
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "steps": [{"command": "request-operation", "requested_action": payload}],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

    result = replay_workflow(
        tmp_path,
        TaskJournal(tmp_path, "replay-missing-token-test"),
        FakeObserver(),
        name="sample.json",
        dry_run=False,
    )

    assert result["success"] is False
    assert result["executed_steps"] == []
    assert "approval token" in result["stop_reason"].lower()
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_replay_workflow_stop_captures_recovery_snapshot(tmp_path):
    library = tmp_path / "revit_operator_workflows"
    library.mkdir()
    payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S2.0"},
        "allow_model_write": False,
        "allow_sync": False,
    }
    (library / "sample.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "steps": [{"command": "request-operation", "requested_action": payload}],
            }
        ),
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "revit_running": True}

        def list_dialogs(self):
            return {"success": True, "dialogs": []}

        def ui_tree(self, max_depth=2):
            return {"success": True, "tree": {"title": "Revit"}, "max_depth": max_depth}

        def screenshot(self, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output)}

    result = replay_workflow(
        tmp_path,
        TaskJournal(tmp_path, "replay-recovery-test"),
        FakeObserver(),
        name="sample.json",
        dry_run=False,
    )

    assert result["success"] is False
    assert result["recovery_snapshot"]["success"] is True
    assert Path(result["recovery_snapshot"]["path"]).is_relative_to(tmp_path)
    assert Path(result["recovery_snapshot"]["path"]).exists()


def test_recovery_snapshot_writes_readonly_evidence_bundle(tmp_path):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "command_results.jsonl").write_text(
        json.dumps({"id": "cmd-1", "operation": "active-document", "success": True}) + "\n",
        encoding="utf-8",
    )

    class FakeObserver:
        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Upgrade"}]}

        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "title": "Upgrade model",
                        "dialog_text": "This model must be upgraded.",
                        "buttons": ["Cancel", "Upgrade"],
                    }
                ],
            }

        def ui_tree(self, max_depth=2):
            return {"supported": True, "max_depth": max_depth, "tree": {"title": "Dialog"}}

        def screenshot(self, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output)}

    result = capture_recovery_snapshot(
        TaskJournal(tmp_path, "recovery-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        max_depth=1,
    )

    assert result["success"] is True
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["status"]["state"] == "modal"
    assert snapshot["recommendation"]["classification"] == "human_decision_required"
    assert snapshot["recommendation"]["known_dialog_ids"] == ["upgrade-model"]
    assert snapshot["validated_live_recovery_drill"] is False
    assert snapshot["north_star_recovery_gate"]["qualifies"] is False
    assert "synthetic or matrix recovery artifact" in snapshot["north_star_recovery_gate"]["excluded_reasons"]
    assert "no live Revit main-window evidence" in snapshot["north_star_recovery_gate"]["excluded_reasons"]
    assert snapshot["dialog_recovery_plans"][0]["known_dialog_id"] == "upgrade-model"
    assert snapshot["dialog_recovery_plans"][0]["planned_action"] is None
    assert "Upgrade" in snapshot["dialog_recovery_plans"][0]["blocked_buttons"]
    assert snapshot["recent_bridge_results"][0]["id"] == "cmd-1"
    assert result["validated_live_recovery_drill"] is False


def test_recovery_snapshot_marks_live_modal_recovery_as_qualifying(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "modal",
                "main_window": {
                    "is_revit_related": True,
                    "process_name": "Revit.exe",
                    "is_hung": False,
                },
                "active_dialogs": [{"title": "Upgrade"}],
            }

        def list_dialogs(self):
            return {
                "success": True,
                "dialogs": [
                    {
                        "title": "Upgrade model",
                        "dialog_text": "This model must be upgraded.",
                        "buttons": ["Cancel", "Upgrade"],
                    }
                ],
            }

        def ui_tree(self, max_depth=2):
            return {"skipped": True, "max_depth": max_depth}

        def screenshot(self, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output)}

    result = capture_recovery_snapshot(
        TaskJournal(tmp_path, "live-real-modal-recovery"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        capture_screenshot=False,
        capture_ui_tree=False,
    )

    assert result["success"] is True
    assert result["validated_live_recovery_drill"] is True
    snapshot = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert snapshot["validated_live_recovery_drill"] is True
    gate = snapshot["north_star_recovery_gate"]
    assert gate["qualifies"] is True
    assert gate["excluded_reasons"] == []
    assert gate["state"] == "modal"
    assert gate["active_dialog_count"] == 1
    assert gate["recommendation_classification"] == "human_decision_required"


def test_recovery_drill_matrix_validates_conservative_recommendations(tmp_path):
    result = validate_recovery_drill_matrix(TaskJournal(tmp_path, "recovery-drill-matrix-test"))

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["case_count"] >= 5
    assert result["failed_cases"] == []
    modal = next(case for case in result["cases"] if case["name"] == "modal-upgrade-dialog")
    assert modal["recommendation"]["classification"] == "human_decision_required"
    assert modal["recommendation"]["known_dialog_ids"] == ["upgrade-model"]
    assert modal["dialog_recovery_plans"][0]["planned_action"] is None
    busy = next(case for case in result["cases"] if case["name"] == "busy-no-dialog")
    assert busy["recommendation"]["classification"] == "wait_or_human_intervention"
    assert Path(result["path"]).exists()


def test_cli_recovery_drill_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "recovery-drill-matrix-cli-test",
            "recovery-drill-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["case_count"] >= 5
    assert Path(output["path"]).exists()


def test_supervision_endurance_matrix_validates_resume_and_stalls(tmp_path):
    result = validate_supervision_endurance_matrix(
        TaskJournal(tmp_path, "supervision-endurance-matrix-test")
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["synthetic"] is True
    assert result["case_count"] >= 4
    assert result["failed_cases"] == []
    assert Path(result["path"]).exists()

    cases = {case["name"]: case for case in result["cases"]}
    assert cases["resume-segments"]["evidence"]["second"]["segment_count"] == 2
    assert cases["busy-stall-recovery"]["evidence"]["stop_reason"] == "stalled_state_detected"
    assert cases["busy-stall-recovery"]["evidence"]["recovery_snapshot"]["success"] is True
    assert cases["unknown-stall-no-recovery"]["evidence"]["recovery_snapshot"] is None


def test_cli_supervision_endurance_matrix_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "supervision-endurance-matrix-cli-test",
            "supervision-endurance-matrix",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["failed_cases"] == []
    assert Path(output["path"]).exists()


def test_supervision_endurance_audit_reports_target_met_from_live_window_logs(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "live-supervise-example"
    run_dir.mkdir(parents=True)
    (run_dir / "supervision_log.json").write_text(
        json.dumps(
            {
                "success": True,
                "final_state": "idle",
                "final_active_dialog_count": 0,
                "segments": [
                    {
                        "started_at": "2026-05-12T10:00:00Z",
                        "finished_at": "2026-05-12T10:45:00Z",
                        "stop_reason": "duration_elapsed",
                    },
                    {
                        "started_at": "2026-05-12T11:00:00Z",
                        "finished_at": "2026-05-12T11:45:00Z",
                        "stop_reason": "duration_elapsed",
                    },
                ],
                "checks": [
                    {
                        "checked_at": "2026-05-12T10:00:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                    {
                        "checked_at": "2026-05-12T10:45:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                    {
                        "checked_at": "2026-05-12T11:45:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = audit_supervision_endurance(
        TaskJournal(tmp_path, "supervision-endurance-audit-test"),
        target_hours=1.5,
        min_checks=3,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["target_met"] is True
    assert result["status"] == "target_met"
    assert result["qualifying_log_count"] == 1
    assert result["check_count"] == 3
    assert result["total_live_seconds"] == 5400
    assert result["raw_total_live_seconds"] == 5400
    assert result["overlap_adjusted"] is True
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_supervision_endurance_audit_does_not_double_count_overlapping_logs(tmp_path):
    runs_root = tmp_path / "revit_operator_runs"
    for name, start, finish in [
        ("live-supervise-a", "2026-05-12T10:00:00Z", "2026-05-12T11:00:00Z"),
        ("live-supervise-b", "2026-05-12T10:30:00Z", "2026-05-12T11:30:00Z"),
    ]:
        run_dir = runs_root / name
        run_dir.mkdir(parents=True)
        (run_dir / "supervision_log.json").write_text(
            json.dumps(
                {
                    "success": True,
                    "final_state": "idle",
                    "final_active_dialog_count": 0,
                    "segments": [
                        {
                            "started_at": start,
                            "finished_at": finish,
                            "stop_reason": "duration_elapsed",
                        }
                    ],
                    "checks": [
                        {
                            "checked_at": start,
                            "state": "idle",
                            "main_window": {"hwnd": 100},
                        },
                        {
                            "checked_at": finish,
                            "state": "idle",
                            "main_window": {"hwnd": 100},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    result = audit_supervision_endurance(
        TaskJournal(tmp_path, "supervision-endurance-audit-overlap-test"),
        target_hours=2.0,
        min_checks=4,
    )

    assert result["success"] is True
    assert result["target_met"] is False
    assert result["duration_met"] is False
    assert result["checks_met"] is True
    assert result["qualifying_log_count"] == 2
    assert result["check_count"] == 4
    assert result["raw_total_live_seconds"] == 7200
    assert result["total_live_seconds"] == 5400
    assert result["merged_interval_count"] == 1


def test_supervision_endurance_audit_reports_in_progress_supervisor_pid(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "live-supervise-running"
    run_dir.mkdir(parents=True)
    (run_dir / "supervision_log.json").write_text(
        json.dumps(
            {
                "success": True,
                "checkpoint_status": "running",
                "in_progress": True,
                "supervisor_pid": os.getpid(),
                "segments": [
                    {
                        "started_at": "2026-05-12T10:00:00Z",
                        "finished_at": "2026-05-12T10:05:00Z",
                        "stop_reason": "running",
                    }
                ],
                "checks": [
                    {
                        "checked_at": "2026-05-12T10:00:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                    {
                        "checked_at": "2026-05-12T10:05:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = audit_supervision_endurance(
        TaskJournal(tmp_path, "supervision-endurance-audit-running-test"),
        target_hours=1.0,
        min_checks=2,
    )

    assert result["success"] is True
    assert result["target_met"] is False
    assert result["in_progress_log_count"] == 1
    assert result["active_in_progress_log_count"] == 1
    assert result["stale_in_progress_log_count"] == 0
    assert result["qualifying_logs"][0]["supervisor_pid"] == os.getpid()
    assert result["qualifying_logs"][0]["supervisor_pid_running"] is True


def test_supervision_endurance_audit_extends_active_running_pid_interval(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "live-supervise-active-running"
    run_dir.mkdir(parents=True)
    (run_dir / "supervision_log.json").write_text(
        json.dumps(
            {
                "success": True,
                "checkpoint_status": "running",
                "in_progress": True,
                "supervisor_pid": os.getpid(),
                "segments": [
                    {
                        "started_at": "2026-05-12T10:00:00Z",
                        "finished_at": "2026-05-12T10:05:00Z",
                        "stop_reason": "running",
                    }
                ],
                "checks": [
                    {
                        "checked_at": "2026-05-12T10:00:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                    {
                        "checked_at": "2026-05-12T10:05:00Z",
                        "state": "idle",
                        "main_window": {"hwnd": 100},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = audit_supervision_endurance(
        TaskJournal(tmp_path, "supervision-endurance-active-running-test"),
        target_hours=1.0,
        min_checks=2,
        audit_now=datetime(2026, 5, 12, 10, 10, tzinfo=timezone.utc),
    )

    assert result["success"] is True
    assert result["active_interval_extended_log_count"] == 1
    assert result["active_interval_extension_seconds"] == 300
    assert result["total_live_seconds"] == 600
    assert result["duration_remaining_seconds"] == 3000
    assert result["check_count_remaining"] == 0
    assert result["estimated_duration_target_at"] == "2026-05-12T11:00:00Z"
    assert result["estimated_duration_target_reason"] == "active supervisor pid confirmed running"
    assert result["qualifying_logs"][0]["active_interval_extended"] is True


def test_supervision_endurance_audit_excludes_synthetic_and_insufficient_logs(tmp_path):
    synthetic_dir = tmp_path / "revit_operator_runs" / "live-supervision-endurance-matrix-resume-segments"
    synthetic_dir.mkdir(parents=True)
    (synthetic_dir / "supervision_log.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "started_at": "2026-05-12T10:00:00Z",
                        "finished_at": "2026-05-12T12:30:00Z",
                        "stop_reason": "duration_elapsed",
                    }
                ],
                "checks": [{"checked_at": "2026-05-12T10:00:00Z", "state": "idle"}],
            }
        ),
        encoding="utf-8",
    )

    result = audit_supervision_endurance(
        TaskJournal(tmp_path, "supervision-endurance-audit-insufficient-test"),
        target_hours=2.0,
        min_checks=24,
    )

    assert result["success"] is True
    assert result["target_met"] is False
    assert result["status"] == "insufficient_evidence"
    assert result["qualifying_log_count"] == 0
    assert result["excluded_log_count"] >= 1
    assert result["excluded_logs"][0]["excluded_reasons"]


def test_cli_supervision_endurance_audit_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "supervision-endurance-audit-cli-test",
            "supervision-endurance-audit",
            "--target-hours",
            "0.1",
            "--min-checks",
            "1",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["target_met"] is False
    assert output["live_ui_touched"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_supervise_session_records_transitions_and_stops_on_modal(tmp_path):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "command_results.jsonl").write_text(
        json.dumps({"id": "cmd-1", "operation": "active-document", "success": True}) + "\n",
        encoding="utf-8",
    )

    class FakeObserver:
        def __init__(self):
            self.states = iter(
                [
                    {"state": "idle", "revit_running": True, "active_dialogs": []},
                    {"state": "modal", "revit_running": True, "active_dialogs": [{"title": "Prompt"}]},
                ]
            )

        def status(self):
            return next(self.states)

    journal = TaskJournal(tmp_path, "supervision-test")
    result = supervise_session(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        duration=10,
        poll=0,
        max_checks=5,
    )

    assert result["success"] is True
    assert result["stop_reason"] == "modal_state_detected"
    assert result["check_count"] == 2
    assert [transition["to"] for transition in result["transitions"]] == ["idle", "modal"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    entries = [json.loads(line) for line in journal.journal_path.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["command"] == "supervise-session"
    assert entries[-1]["approval_status"]["allowed"] is True
    assert entries[-1]["result"]["status"] == "modal_state_detected"
    assert entries[-1]["result"]["check_count"] == 2


def test_supervise_session_resume_appends_existing_log(tmp_path):
    class FakeObserver:
        def __init__(self, state):
            self.state = state

        def status(self):
            return {"state": self.state, "revit_running": True, "active_dialogs": []}

    journal = TaskJournal(tmp_path, "supervision-resume-test")
    first = supervise_session(
        journal,
        FakeObserver("idle"),
        RevitBridgeClient(tmp_path),
        duration=10,
        poll=0,
        max_checks=1,
    )
    second = supervise_session(
        journal,
        FakeObserver("busy"),
        RevitBridgeClient(tmp_path),
        duration=10,
        poll=0,
        max_checks=1,
        resume=True,
    )

    assert first["check_count"] == 1
    assert second["resumed"] is True
    assert second["previous_check_count"] == 1
    assert second["new_check_count"] == 1
    assert second["check_count"] == 2
    assert [check["index"] for check in second["checks"]] == [0, 1]
    assert second["checks"][0]["state"] == "idle"
    assert second["checks"][1]["state"] == "busy"
    assert second["transitions"][-1]["from"] == "idle"
    assert second["transitions"][-1]["to"] == "busy"


def test_supervise_session_writes_incremental_checkpoint(tmp_path):
    journal = TaskJournal(tmp_path, "supervision-checkpoint-test")
    output = journal.run_dir / "supervision_log.json"

    class FakeObserver:
        def __init__(self):
            self.calls = 0

        def status(self):
            self.calls += 1
            if self.calls == 2:
                checkpoint = json.loads(output.read_text(encoding="utf-8"))
                assert checkpoint["checkpoint_status"] == "running"
                assert checkpoint["in_progress"] is True
                assert checkpoint["check_count"] == 1
                assert checkpoint["segments"][-1]["stop_reason"] == "running"
            return {"state": "idle", "revit_running": True, "active_dialogs": []}

    result = supervise_session(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        duration=10,
        poll=0,
        max_checks=2,
    )

    assert result["success"] is True
    assert result["checkpoint_status"] == "complete"
    assert result["in_progress"] is False
    assert result["supervisor_pid"] == os.getpid()
    assert result["check_count"] == 2
    final_log = json.loads(output.read_text(encoding="utf-8"))
    assert final_log["checkpoint_status"] == "complete"
    assert final_log["segments"][-1]["stop_reason"] == "max_checks_reached"


def test_supervise_session_detects_stalled_busy_state_and_captures_recovery(tmp_path):
    class FakeObserver:
        def __init__(self):
            self.statuses = [
                {
                    "state": "busy",
                    "revit_running": True,
                    "active_dialogs": [],
                    "windows": [{"title": "Autodesk Revit", "is_hung": True}],
                },
                {
                    "state": "busy",
                    "revit_running": True,
                    "active_dialogs": [],
                    "windows": [{"title": "Autodesk Revit", "is_hung": True}],
                },
            ]

        def status(self):
            return self.statuses.pop(0) if self.statuses else {
                "state": "busy",
                "revit_running": True,
                "active_dialogs": [],
                "windows": [{"title": "Autodesk Revit", "is_hung": True}],
            }

        def list_dialogs(self):
            return {"success": True, "dialogs": []}

        def ui_tree(self, max_depth=2):
            return {"success": True, "supported": True, "max_depth": max_depth, "tree": {}}

        def screenshot(self, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output)}

    result = supervise_session(
        TaskJournal(tmp_path, "supervision-stall-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        duration=10,
        poll=0,
        max_checks=5,
        stall_after_checks=2,
    )

    assert result["success"] is True
    assert result["stop_reason"] == "stalled_state_detected"
    assert result["stall_analysis"]["stalled"] is True
    assert result["stall_analysis"]["hung_window_count"] == 1
    assert result["recovery_snapshot"]["success"] is True
    assert Path(result["recovery_snapshot"]["path"]).is_relative_to(tmp_path)


def test_cli_supervise_session_writes_log(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "revit_running": True, "active_dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "supervision-cli-test",
            "supervise-session",
            "--max-checks",
            "1",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["check_count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_recovery_snapshot_is_observation_command(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "recovery-cli-test",
            "recovery-snapshot",
            "--no-screenshot",
            "--no-ui-tree",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_readonly_qa_workflow_runs_from_bridge_metadata(tmp_path, monkeypatch):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "command_results.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "active-id", "success": True}),
                json.dumps({"id": "metadata-id", "success": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bridge_dir / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "label": DRAFT_LABEL,
                "read_only": True,
                "document": {"title": "Live Model", "path": "model.rvt", "revit_version": "2025"},
                "levels": [{"name": "Level 1"}],
                "grids": [],
                "views": [],
                "sheets": [{"sheet_number": "S1"}],
                "titleblocks": [],
                "links": [],
                "warnings": [{"description": "warning"}],
                "families": [],
                "types": [],
            }
        ),
        encoding="utf-8",
    )

    command_ids = iter(["active-id", "metadata-id"])

    def fake_queue_operation(_journal, request):
        return {
            "success": True,
            "command": {"id": next(command_ids), "operation": request.operation},
        }

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

        def ui_tree(self, max_depth=2):
            return {"supported": True, "tree": {"title": "Revit"}}

        def screenshot(self, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "format": "bmp"}

    monkeypatch.setattr(workflows, "queue_operation", fake_queue_operation)

    result = run_readonly_qa_workflow(
        TaskJournal(tmp_path, "workflow-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        timeout=0,
    )

    assert result["success"] is True
    assert result["metadata_path"].endswith(".json")
    assert result["qa_report_path"].endswith("qa_report.md")
    assert "23" not in "\n".join(result["findings"])


def test_agent_task_plan_blocks_save_sync_and_model_changes():
    result = plan_agent_task("Check warnings, then save and sync the central model")

    assert result["success"] is True
    assert result["decision"]["decision"] == BLOCK
    assert "save" in result["blocked_intents"]
    assert "sync" in result["blocked_intents"]


def test_agent_task_plan_allows_readonly_qa_scope():
    result = plan_agent_task(
        "Inspect the copied structural drawings, check warnings and links, and produce a draft QA report",
        expected_revit_version="2025",
        expected_title_contains="detached",
    )

    assert result["decision"]["decision"] == ALLOW
    assert result["task_type"] == "read_only_qa"
    assert {"qa", "inspect", "warnings", "links", "report"}.issubset(set(result["supported_intents"]))


def test_agent_task_stops_on_active_dialog_and_writes_human_packet(tmp_path, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "modal",
                "active_dialogs": [{"title": "Upgrade Model"}],
                "main_window": {"hwnd": 1},
            }

        def list_dialogs(self):
            return {
                "dialogs": [
                    {
                        "title": "Upgrade Model",
                        "dialog_text": "This model must be upgraded.",
                        "buttons": ["Upgrade", "Cancel"],
                    }
                ]
            }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("QA workflow must not run while a dialog is active.")

    monkeypatch.setattr(agent_task, "run_readonly_qa_workflow", fail_if_called)

    journal = TaskJournal(tmp_path, "agent-task-dialog-test")
    result = run_agent_task(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        task_text="Inspect sheets and produce a draft QA report",
        expected_revit_version="2025",
    )

    assert result["status"] == "needs_human_approval"
    assert result["task_complete"] is False
    assert (journal.run_dir / "agent_task_human_packet.json").exists()
    assert "Upgrade Model" in (journal.run_dir / "current_dialog_response_plan.json").read_text(encoding="utf-8")


def test_agent_task_broad_approval_scope_writes_session_plan(tmp_path, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("QA workflow must not run for broad approval-gated objectives.")

    monkeypatch.setattr(agent_task, "run_readonly_qa_workflow", fail_if_called)

    journal = TaskJournal(tmp_path, "agent-task-session-plan-test")
    result = run_agent_task(
        journal,
        RevitWindowObserver(),
        RevitBridgeClient(tmp_path),
        task_text="Open the copied model, use Manage Links, reload links if approved, and supervise for hours",
        expected_revit_version="2025",
    )

    assert result["status"] == "needs_human_approval"
    assert result["task_complete"] is False
    assert result["session_plan"]["goal_complete"] is False
    assert (journal.run_dir / "agent_session_plan.json").exists()
    assert "APPROVE:" not in (journal.run_dir / "agent_session_plan.json").read_text(encoding="utf-8")


def test_agent_task_runs_readonly_qa_after_readiness(tmp_path, monkeypatch):
    class FakeObserver:
        def __init__(self):
            self.calls = 0

        def status(self):
            self.calls += 1
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1},
                "revit_running": True,
            }

    def fake_wait_model_ready(journal, *_args, **_kwargs):
        output = journal.run_dir / "model_ready_status.json"
        output.write_text(json.dumps({"success": True, "ready": True, "path": str(output)}), encoding="utf-8")
        return {"success": True, "ready": True, "path": str(output)}

    def fake_workflow(journal, *_args, **_kwargs):
        report = journal.run_dir / "qa_report.md"
        report.write_text(DRAFT_LABEL, encoding="utf-8")
        metadata = journal.metadata_dir / "metadata-test.json"
        metadata.write_text("{}", encoding="utf-8")
        return {
            "success": True,
            "workflow": "readonly-qa",
            "qa_report_path": str(report),
            "metadata_path": str(metadata),
            "findings": ["1 Revit warning requires review."],
            "output_files": [str(report), str(metadata)],
        }

    monkeypatch.setattr(agent_task, "wait_model_ready", fake_wait_model_ready)
    monkeypatch.setattr(agent_task, "run_readonly_qa_workflow", fake_workflow)

    journal = TaskJournal(tmp_path, "agent-task-run-test")
    result = run_agent_task(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        task_text="Inspect the structural drawings, check warnings, and produce a draft QA report",
        expected_revit_version="2025",
    )

    assert result["status"] == "completed"
    assert result["task_complete"] is True
    assert result["may_tell_user_done"] is True
    assert (journal.run_dir / "agent_task_plan.json").exists()
    assert (journal.run_dir / "agent_task_report.md").exists()
    assert "save_sync_publish_performed: `false`" in (journal.run_dir / "agent_task_report.md").read_text(
        encoding="utf-8"
    )


def test_cli_exposes_agent_task_command(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "main_window": {"hwnd": 1}}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-task-cli-test",
            "agent-task",
            "--task",
            "Inspect warnings and produce a draft QA report",
            "--plan-only",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "planned"
    assert output["task_complete"] is False
    assert output["plan"]["task_type"] == "read_only_qa"


def test_agent_session_plan_maps_general_agent_goal_and_refuses_completion(tmp_path):
    journal = TaskJournal(tmp_path, "agent-session-plan-test")

    result = plan_agent_session(
        journal,
        objective=(
            "Open the copied model, handle upgrade and detach prompts, use Manage Links, "
            "reload links with approval, update project info parameters, and supervise for hours."
        ),
        model_path=r"C:\safe\copied-local-R25.rvt",
        expected_revit_version="2025",
        expected_title_contains="detached",
        max_hours=2,
        parameters={
            "parameter_name": "Project Status",
            "parameter_value": "QA Draft",
            "sheet_number": "S2.0",
        },
    )

    requirement_ids = {row["id"] for row in result["requirements"]}
    phase_ids = {row["id"] for row in result["phases"]}
    workflow_names = {row["name"] for row in result["candidate_ui_workflows"]}
    operation_names = {row["operation"] for row in result["model_change_requests"]}

    assert result["success"] is True
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert {
        "arbitrary-ui-flows",
        "approved-model-changing-work",
        "model-open-prompt-choreography",
        "multi-hour-task-planning",
    }.issubset(requirement_ids)
    assert "model-open-prompt-choreography" in phase_ids
    assert "approved-model-changing-work" in phase_ids
    assert "multi-hour-supervision" in phase_ids
    assert "manage-links-inspection" in workflow_names
    assert {"reload-links", "set-project-info-parameter"}.issubset(operation_names)
    assert result["completion_blockers"]
    assert (journal.run_dir / "agent_session_plan.json").exists()
    assert (journal.run_dir / "agent_session_checklist.json").exists()
    assert (journal.run_dir / "agent_session_plan.md").exists()
    assert "APPROVE:" not in (journal.run_dir / "agent_session_plan.json").read_text(encoding="utf-8")


def test_cli_exposes_agent_session_plan_command(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-session-cli-test",
            "agent-session-plan",
            "--objective",
            "Use Review Warnings and Visibility/Graphics while supervising for hours.",
            "--expected-revit-version",
            "2025",
            "--max-hours",
            "1",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["goal_complete"] is False
    assert output["may_call_update_goal"] is False
    workflow_names = {row["name"] for row in output["candidate_ui_workflows"]}
    assert "review-warnings-inspection" in workflow_names
    assert "visibility-graphics-inspection" in workflow_names
    assert "APPROVE:" not in stdout


def test_agent_session_run_executes_readonly_preflight_and_refuses_completion(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    journal = TaskJournal(tmp_path, "agent-session-run-test")
    result = run_agent_session(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        objective="Use Manage Links and supervise for hours without unsafe writes.",
        expected_revit_version="2025",
        run_open_dry_run=False,
        bridge_refresh_timeout=0,
        supervision_duration=0,
    )

    step_names = {step["step"] for step in result["steps"]}
    assert result["success"] is True
    assert result["status"] == "stopped_at_approval_gates"
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert {"observe-status", "list-dialogs", "bridge-status", "wait-model-ready-check"}.issubset(step_names)
    assert (journal.run_dir / "agent_session_run.json").exists()
    assert "APPROVE:" not in (journal.run_dir / "agent_session_run.json").read_text(encoding="utf-8")


def test_agent_session_run_redacts_approval_tokens_from_open_model_dry_run(tmp_path, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    def fake_open_model(*_args, **_kwargs):
        return {
            "success": True,
            "dry_run": True,
            "policy": {"decision": APPROVAL_REQUIRED, "approval_token": "APPROVE:secret"},
            "next_step": "Re-run with --approval-token APPROVE:secret",
        }

    monkeypatch.setattr(agent_session, "open_model", fake_open_model)

    journal = TaskJournal(tmp_path, "agent-session-open-redaction-test")
    result = run_agent_session(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        objective="Open the copied model and handle prompts.",
        model_path=str(tmp_path / "model-R25.rvt"),
        expected_revit_version="2025",
        bridge_refresh_timeout=0,
        supervision_duration=0,
    )

    result_text = json.dumps(result)
    artifact_text = (journal.run_dir / "agent_session_run.json").read_text(encoding="utf-8")
    assert "APPROVE:secret" not in result_text
    assert "APPROVE:secret" not in artifact_text
    assert "<withheld approval token>" in artifact_text


def test_cli_exposes_agent_session_run_command(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-session-run-cli-test",
            "agent-session-run",
            "--objective",
            "Use Review Warnings and supervise for hours.",
            "--expected-revit-version",
            "2025",
            "--no-open-dry-run",
            "--bridge-refresh-timeout",
            "0",
            "--supervision-duration",
            "0",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["status"] == "stopped_at_approval_gates"
    assert output["goal_complete"] is False
    assert "APPROVE:" not in stdout


def test_agent_session_approval_plan_keeps_tokens_private(tmp_path):
    journal = TaskJournal(tmp_path, "agent-session-approval-plan-test")
    result = agent_session.build_agent_session_approval_plan(
        journal,
        objective="Use Manage Links, reload links if approved, and update project info parameters.",
        parameters={"parameter_name": "Project Status", "parameter_value": "QA Draft"},
    )

    public_text = (journal.run_dir / "agent_session_approval_plan.json").read_text(encoding="utf-8")
    private_text = (journal.run_dir / "agent_session_approval_private_material.json").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["approval_required_count"] >= 2
    assert result["private_material_contains_approval_tokens"] is True
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in public_text
    assert "APPROVE:" in private_text
    assert "model-change:reload-links" in private_text


def test_cli_exposes_agent_session_approval_plan_with_redacted_stdout(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-session-approval-cli-test",
            "agent-session-approval-plan",
            "--objective",
            "Use Manage Links and reload links if approved.",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    private_path = Path(output["private_material_path"])
    assert output["success"] is True
    assert output["approval_required_count"] >= 1
    assert "APPROVE:" not in stdout
    assert "APPROVE:" in private_path.read_text(encoding="utf-8")


def test_agent_session_execute_approved_model_change_dry_run_redacts_tokens(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    approval_journal = TaskJournal(tmp_path, "approval-source")
    approval = agent_session.build_agent_session_approval_plan(
        approval_journal,
        objective="Reload links if approved.",
    )
    run_journal = TaskJournal(tmp_path, "approved-item-dry-run")
    result = agent_session.execute_agent_session_approved_item(
        run_journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="model-change:reload-links",
        execute=False,
        bridge_refresh_timeout=0,
    )

    assert result["success"] is True
    assert result["status"] == "ready_for_approval_execution"
    assert result["execution"]["executed"] is False
    assert result["execution"]["pre_action_active_document"]["available"] is False
    assert result["execution"]["post_action_refresh"] is None
    assert result["execution"]["receipt"]["post_action_refresh_requested"] is False
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in (run_journal.run_dir / "agent_session_approved_item_result.json").read_text(
        encoding="utf-8"
    )


def test_agent_session_execute_approved_model_change_requires_exact_confirmation(tmp_path, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    approval_journal = TaskJournal(tmp_path, "approval-source-confirm")
    approval = agent_session.build_agent_session_approval_plan(
        approval_journal,
        objective="Reload links if approved.",
    )
    calls = []

    def fake_queue_operation(_journal, request):
        calls.append(request)
        return {
            "success": True,
            "dry_run": request.dry_run,
            "command": {"operation": request.operation},
        }

    monkeypatch.setattr(agent_session, "queue_operation", fake_queue_operation)

    wrong = agent_session.execute_agent_session_approved_item(
        TaskJournal(tmp_path, "approved-item-wrong-confirm"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="model-change:reload-links",
        execute=True,
        confirmation="I approve the wrong thing",
        bridge_refresh_timeout=0,
    )
    assert wrong["status"] == "stopped_confirmation_required"
    assert all(call.operation == "active-document" for call in calls)

    calls.clear()
    executed = agent_session.execute_agent_session_approved_item(
        TaskJournal(tmp_path, "approved-item-execute-confirm"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="model-change:reload-links",
        execute=True,
        confirmation="I approve model-change:reload-links",
        bridge_refresh_timeout=0,
    )
    model_calls = [call for call in calls if call.operation == "reload-links"]
    refresh_calls = [call for call in calls if call.operation == "active-document"]
    assert executed["status"] == "executed"
    assert executed["execution"]["executed"] is True
    assert model_calls
    assert refresh_calls
    assert model_calls[-1].approval_token.startswith("APPROVE:")
    assert executed["execution"]["receipt"]["post_action_refresh_requested"] is True
    assert executed["execution"]["post_action_refresh"]["command"]["operation"] == "active-document"
    assert "APPROVE:" not in json.dumps(executed)


def test_cli_exposes_agent_session_execute_approved_item_dry_run(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "approval-source-cli"),
        objective="Reload links if approved.",
    )
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "approved-item-cli-test",
            "agent-session-execute-approved-item",
            "--approval-material",
            approval["private_material_path"],
            "--item-id",
            "model-change:reload-links",
            "--bridge-refresh-timeout",
            "0",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["status"] == "ready_for_approval_execution"
    assert output["execution"]["executed"] is False
    assert "APPROVE:" not in stdout


def _fake_agent_ui_tree():
    return {
        "supported": True,
        "hwnd": 101,
        "tree": {
            "hwnd": 101,
            "title": "Autodesk Revit 2025 - [Model]",
            "class_name": "HwndWrapper[DefaultDomain;;test]",
            "enabled": True,
            "visible": True,
            "children": [
                {
                    "hwnd": 201,
                    "title": "Manage Links",
                    "class_name": "Button",
                    "enabled": True,
                    "visible": True,
                    "rect": {"left": 10, "top": 10, "right": 110, "bottom": 40},
                    "children": [],
                },
                {
                    "hwnd": 202,
                    "title": "Review Warnings",
                    "class_name": "Button",
                    "enabled": True,
                    "visible": True,
                    "rect": {"left": 120, "top": 10, "right": 240, "bottom": 40},
                    "children": [],
                },
            ],
        },
    }


def test_agent_ui_flow_scout_finds_candidate_controls_without_execution(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "main_window": {"hwnd": 101}}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

        def ui_tree(self, max_depth=4):
            return _fake_agent_ui_tree()

    journal = TaskJournal(tmp_path, "agent-ui-flow-scout-test")
    result = agent_session.scout_agent_ui_flow(
        journal,
        FakeObserver(),
        objective="Find Manage Links or Review Warnings in the current Revit UI.",
    )

    targets = {candidate["target"] for candidate in result["candidates"]}
    assert result["success"] is True
    assert result["status"] == "candidates_found"
    assert result["read_only"] is True
    assert result["ui_action_executed"] is False
    assert {"Manage Links", "Review Warnings"}.issubset(targets)
    assert all(action["recommended_action"] != "click" for action in result["next_actions"])
    assert "APPROVE:" not in json.dumps(result)
    assert (journal.run_dir / "agent_ui_flow_scout.json").exists()
    assert (journal.run_dir / "agent_ui_flow_scout_ui_tree.json").exists()


def test_agent_ui_flow_scout_can_include_uia_candidates(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "main_window": {"hwnd": 101}}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

        def ui_tree(self, max_depth=4):
            return {"supported": True, "hwnd": 101, "tree": {"name": "root", "children": []}}

    def fake_uia_tree(**_kwargs):
        return {
            "success": True,
            "supported": True,
            "backend": "uia",
            "hwnd": 101,
            "node_count": 2,
            "tree": {
                "name": "Autodesk Revit",
                "control_type": "Window",
                "children": [
                    {
                        "name": "Manage Links",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "handle": 303,
                        "enabled": True,
                        "visible": True,
                        "children": [],
                    }
                ],
            },
        }

    journal = TaskJournal(tmp_path, "agent-ui-flow-uia-scout-test")
    result = agent_session.scout_agent_ui_flow(
        journal,
        FakeObserver(),
        objective="Find Manage Links.",
        include_uia=True,
        uia_tree_func=fake_uia_tree,
    )

    assert result["success"] is True
    assert result["observation"]["uia_tree"]["success"] is True
    assert result["candidates"][0]["source"] == "uia"
    assert result["candidates"][0]["target"] == "Manage Links"
    assert (journal.run_dir / "agent_ui_flow_scout_uia_tree.json").exists()


def test_agent_ui_flow_scout_stops_on_modal_dialog(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "modal",
                "active_dialogs": [{"title": "Upgrade Model", "dialog_text": "This model will be upgraded."}],
                "main_window": {"hwnd": 101},
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

        def ui_tree(self, max_depth=4):
            return _fake_agent_ui_tree()

    result = agent_session.scout_agent_ui_flow(
        TaskJournal(tmp_path, "agent-ui-flow-modal-test"),
        FakeObserver(),
        objective="Find Manage Links.",
    )

    assert result["success"] is True
    assert result["status"] == "stopped_on_modal"
    assert result["candidate_count"] == 0
    assert result["next_actions"][0]["recommended_action"] == "plan-current-dialog-response"
    assert result["next_actions"][0]["command"].startswith("plan-current-dialog-response")
    assert result["ui_action_executed"] is False


def test_cli_exposes_agent_ui_flow_scout_command(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "main_window": {"hwnd": 101}}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

        def ui_tree(self, max_depth=4):
            return _fake_agent_ui_tree()

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-ui-flow-scout-cli-test",
            "agent-ui-flow-scout",
            "--objective",
            "Find Manage Links in the current UI.",
            "--max-depth",
            "4",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["status"] == "candidates_found"
    assert output["candidate_count"] >= 1
    assert "APPROVE:" not in stdout


def test_agent_ui_flow_approval_plan_keeps_candidate_tokens_private(tmp_path):
    source = TaskJournal(tmp_path, "agent-ui-flow-approval-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Manage Links",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "hwnd": 303,
                        "matched_terms": ["manage", "manage links"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > Manage > Manage Links",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    journal = TaskJournal(tmp_path, "agent-ui-flow-approval-plan-test")
    result = agent_session.build_ui_flow_candidate_approval_plan(journal, scout_path=scout_path)
    public_text = (journal.run_dir / "agent_ui_flow_approval_plan.json").read_text(encoding="utf-8")
    private_text = (journal.run_dir / "agent_ui_flow_approval_private_material.json").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["approval_required_count"] == 1
    assert result["blocked_count"] == 0
    assert result["approval_items"][0]["kind"] == "ui-candidate-control"
    assert result["approval_items"][0]["approval_token_withheld"] is True
    assert result["approval_items"][0]["execute_command_withheld"] is True
    assert "uia-invoke" in private_text
    assert "--execute" in private_text
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in public_text
    assert "APPROVE:" in private_text


def test_agent_ui_flow_approval_plan_blocks_destructive_candidate(tmp_path):
    source = TaskJournal(tmp_path, "agent-ui-flow-blocked-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Save",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_SAVE",
                        "class_name": "Button",
                        "matched_terms": ["save"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > File > Save",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    journal = TaskJournal(tmp_path, "agent-ui-flow-blocked-approval-test")
    result = agent_session.build_ui_flow_candidate_approval_plan(journal, scout_path=scout_path)
    private_text = (journal.run_dir / "agent_ui_flow_approval_private_material.json").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["approval_required_count"] == 0
    assert result["blocked_count"] == 1
    assert result["blocked_items"][0]["id"].startswith("ui-candidate:0:save")
    assert result["blocked_items"][0]["blocked"] is True
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in private_text


def test_cli_exposes_agent_ui_flow_approval_plan_with_redacted_stdout(tmp_path, capsys):
    source = TaskJournal(tmp_path, "agent-ui-flow-approval-cli-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Manage Links",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "matched_terms": ["manage"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > Manage Links",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-ui-flow-approval-cli-test",
            "agent-ui-flow-approval-plan",
            "--scout",
            str(scout_path),
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    private_path = Path(output["private_material_path"])
    assert output["success"] is True
    assert output["approval_required_count"] == 1
    assert "APPROVE:" not in stdout
    assert "APPROVE:" in private_path.read_text(encoding="utf-8")


def test_agent_ui_flow_execute_approved_candidate_dry_run_redacts_tokens(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 101, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    source = TaskJournal(tmp_path, "agent-ui-flow-execute-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Manage Links",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "matched_terms": ["manage"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > Manage Links",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    approval = agent_session.build_ui_flow_candidate_approval_plan(
        TaskJournal(tmp_path, "agent-ui-flow-execute-approval"),
        scout_path=scout_path,
    )

    journal = TaskJournal(tmp_path, "agent-ui-flow-execute-dry-run")
    result = agent_session.execute_ui_flow_approved_candidate(
        journal,
        FakeObserver(),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="ui-candidate:0:manage-links",
    )

    assert result["success"] is True
    assert result["status"] == "ready_for_approval_execution"
    assert result["action_result"]["status"] == "dry_run"
    assert result["receipt"]["ui_action_executed"] is False
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in (journal.run_dir / "agent_ui_flow_approved_candidate_result.json").read_text(
        encoding="utf-8"
    )


def test_agent_ui_flow_execute_approved_candidate_requires_exact_confirmation(tmp_path, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 101, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    source = TaskJournal(tmp_path, "agent-ui-flow-execute-confirm-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Manage Links",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "matched_terms": ["manage"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > Manage Links",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    approval = agent_session.build_ui_flow_candidate_approval_plan(
        TaskJournal(tmp_path, "agent-ui-flow-execute-confirm-approval"),
        scout_path=scout_path,
    )
    calls = []

    class FakeExecutor:
        def __init__(self, observer, journal):
            self.observer = observer
            self.journal = journal

        def run(self, request):
            calls.append(request)
            return {
                "status": "executed",
                "executed": True,
                "dry_run": request.dry_run,
                "policy": {"approval_token": request.approval_token},
                "authorization": {"allowed": True},
            }

    monkeypatch.setattr(agent_session, "SafeActionExecutor", FakeExecutor)
    material_path = Path(approval["private_material_path"])

    wrong = agent_session.execute_ui_flow_approved_candidate(
        TaskJournal(tmp_path, "agent-ui-flow-execute-wrong-confirm"),
        FakeObserver(),
        approval_material_path=material_path,
        item_id="ui-candidate:0:manage-links",
        execute=True,
        confirmation="I approve the wrong item",
    )
    assert wrong["status"] == "stopped_confirmation_required"
    assert calls == []

    executed = agent_session.execute_ui_flow_approved_candidate(
        TaskJournal(tmp_path, "agent-ui-flow-execute-right-confirm"),
        FakeObserver(),
        approval_material_path=material_path,
        item_id="ui-candidate:0:manage-links",
        execute=True,
        confirmation="I approve ui-candidate:0:manage-links",
    )

    assert executed["status"] == "executed"
    assert executed["receipt"]["ui_action_executed"] is True
    assert calls[-1].action == "uia-invoke"
    assert calls[-1].dry_run is False
    assert calls[-1].approval_token.startswith("APPROVE:")
    assert "APPROVE:" not in json.dumps(executed)


def test_cli_exposes_agent_ui_flow_execute_approved_candidate_dry_run(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "active_dialogs": [],
                "main_window": {"hwnd": 101, "title": "Autodesk Revit 2025"},
                "revit_running": True,
            }

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    source = TaskJournal(tmp_path, "agent-ui-flow-execute-cli-source")
    scout_path = source.run_dir / "agent_ui_flow_scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "status": "candidates_found",
                "candidates": [
                    {
                        "target": "Manage Links",
                        "source": "uia",
                        "control_type": "Button",
                        "automation_id": "ID_MANAGE_LINKS",
                        "class_name": "Button",
                        "matched_terms": ["manage"],
                        "confidence": "medium",
                        "path": "Autodesk Revit > Manage Links",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    approval = agent_session.build_ui_flow_candidate_approval_plan(
        TaskJournal(tmp_path, "agent-ui-flow-execute-cli-approval"),
        scout_path=scout_path,
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-ui-flow-execute-cli-test",
            "agent-ui-flow-execute-approved-candidate",
            "--approval-material",
            approval["private_material_path"],
            "--item-id",
            "ui-candidate:0:manage-links",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["status"] == "ready_for_approval_execution"
    assert output["action_result"]["status"] == "dry_run"
    assert "APPROVE:" not in stdout


def _write_model_open_prompt_choreography(
    tmp_path,
    task_id,
    *,
    title,
    text,
    buttons,
):
    journal = TaskJournal(tmp_path, task_id)
    path = journal.run_dir / "model_open_choreography.json"
    plan = plan_dialog_response(title=title, text=text, buttons=buttons)
    path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-model-open-choreography/v1",
                "status": "stopped_on_prompt",
                "prompt_events": [
                    {
                        "index": 0,
                        "source": "post_launch_dialog",
                        "plans": [
                            {
                                "dialog_index": 0,
                                "dialog": {
                                    "title": title,
                                    "dialog_text": text,
                                    "buttons": buttons,
                                },
                                "plan": plan,
                                "requires_human": plan.get("requires_human", True),
                                "known_dialog_id": plan.get("known_dialog_id"),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_model_open_prompt_approval_plan_keeps_prompt_tokens_private(tmp_path):
    choreography_path = _write_model_open_prompt_choreography(
        tmp_path,
        "model-open-prompt-approval-source",
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )

    journal = TaskJournal(tmp_path, "model-open-prompt-approval-plan-test")
    result = model_open_choreography.build_model_open_prompt_approval_plan(
        journal,
        choreography_path=choreography_path,
    )
    public_text = (journal.run_dir / "model_open_prompt_approval_plan.json").read_text(encoding="utf-8")
    private_text = (journal.run_dir / "model_open_prompt_approval_private_material.json").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["approval_required_count"] == 1
    assert result["manual_or_blocked_count"] == 0
    assert result["approval_items"][0]["id"] == "model-open-prompt:0:0:unsigned-addin"
    assert result["approval_items"][0]["target"] == "Always Load"
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in public_text
    assert "APPROVE:" in private_text


def test_model_open_prompt_approval_plan_keeps_upgrade_manual(tmp_path):
    choreography_path = _write_model_open_prompt_choreography(
        tmp_path,
        "model-open-prompt-upgrade-source",
        title="Upgrade model",
        text="This model must be upgraded.",
        buttons=["Cancel", "Upgrade"],
    )

    journal = TaskJournal(tmp_path, "model-open-prompt-upgrade-plan-test")
    result = model_open_choreography.build_model_open_prompt_approval_plan(
        journal,
        choreography_path=choreography_path,
    )
    private_text = (journal.run_dir / "model_open_prompt_approval_private_material.json").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["approval_required_count"] == 0
    assert result["manual_or_blocked_count"] == 1
    assert result["manual_or_blocked_items"][0]["known_dialog_id"] == "upgrade-model"
    assert "Upgrade" in result["manual_or_blocked_items"][0]["blocked_buttons"]
    assert "APPROVE:" not in private_text


def test_model_open_execute_approved_prompt_dry_run_redacts_tokens(tmp_path):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "supported": True,
                "dialogs": [
                    {
                        "title": "Security - Unsigned Add-in",
                        "dialog_text": "Hermes Revit Operator is unsigned. Do you want to load this add-in?",
                        "buttons": ["Always Load", "Load Once", "Do Not Load"],
                    }
                ],
            }

        def status(self):
            return {"state": "modal", "active_dialogs": []}

    choreography_path = _write_model_open_prompt_choreography(
        tmp_path,
        "model-open-prompt-execute-source",
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )
    approval = model_open_choreography.build_model_open_prompt_approval_plan(
        TaskJournal(tmp_path, "model-open-prompt-execute-approval"),
        choreography_path=choreography_path,
    )
    journal = TaskJournal(tmp_path, "model-open-prompt-execute-dry-run")
    result = model_open_choreography.execute_model_open_prompt_approved_step(
        journal,
        FakeObserver(),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="model-open-prompt:0:0:unsigned-addin",
    )

    assert result["success"] is True
    assert result["status"] == "ready_for_approval_execution"
    assert result["fresh_prompt_match"]["matched"] is True
    assert result["action_result"]["status"] == "dry_run"
    assert result["receipt"]["prompt_button_clicked"] is False
    assert "APPROVE:" not in json.dumps(result)
    assert "APPROVE:" not in (journal.run_dir / "model_open_prompt_approved_step_result.json").read_text(
        encoding="utf-8"
    )


def test_model_open_execute_approved_prompt_requires_exact_confirmation(tmp_path, monkeypatch):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "supported": True,
                "dialogs": [
                    {
                        "title": "Security - Unsigned Add-in",
                        "dialog_text": "Hermes Revit Operator is unsigned. Do you want to load this add-in?",
                        "buttons": ["Always Load", "Load Once", "Do Not Load"],
                    }
                ],
            }

        def status(self):
            return {"state": "modal", "active_dialogs": []}

    choreography_path = _write_model_open_prompt_choreography(
        tmp_path,
        "model-open-prompt-confirm-source",
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )
    approval = model_open_choreography.build_model_open_prompt_approval_plan(
        TaskJournal(tmp_path, "model-open-prompt-confirm-approval"),
        choreography_path=choreography_path,
    )
    calls = []

    class FakeExecutor:
        def __init__(self, observer, journal):
            self.observer = observer
            self.journal = journal

        def run(self, request):
            calls.append(request)
            return {
                "status": "executed",
                "executed": True,
                "dry_run": request.dry_run,
                "policy": {"approval_token": request.approval_token},
                "authorization": {"allowed": True},
            }

    monkeypatch.setattr(model_open_choreography, "SafeActionExecutor", FakeExecutor)
    material_path = Path(approval["private_material_path"])

    wrong = model_open_choreography.execute_model_open_prompt_approved_step(
        TaskJournal(tmp_path, "model-open-prompt-wrong-confirm"),
        FakeObserver(),
        approval_material_path=material_path,
        item_id="model-open-prompt:0:0:unsigned-addin",
        execute=True,
        confirmation="I approve the wrong prompt",
    )
    assert wrong["status"] == "stopped_confirmation_required"
    assert calls == []

    executed = model_open_choreography.execute_model_open_prompt_approved_step(
        TaskJournal(tmp_path, "model-open-prompt-right-confirm"),
        FakeObserver(),
        approval_material_path=material_path,
        item_id="model-open-prompt:0:0:unsigned-addin",
        execute=True,
        confirmation="I approve model-open-prompt:0:0:unsigned-addin",
    )

    assert executed["status"] == "executed"
    assert executed["receipt"]["prompt_button_clicked"] is True
    assert calls[-1].action == "click"
    assert calls[-1].payload == {"target": "Always Load"}
    assert calls[-1].approval_token.startswith("APPROVE:")
    assert "APPROVE:" not in json.dumps(executed)


def test_cli_exposes_model_open_prompt_approval_and_execute_dry_run(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def list_dialogs(self):
            return {
                "supported": True,
                "dialogs": [
                    {
                        "title": "Security - Unsigned Add-in",
                        "dialog_text": "Hermes Revit Operator is unsigned. Do you want to load this add-in?",
                        "buttons": ["Always Load", "Load Once", "Do Not Load"],
                    }
                ],
            }

        def status(self):
            return {"state": "modal", "active_dialogs": []}

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    choreography_path = _write_model_open_prompt_choreography(
        tmp_path,
        "model-open-prompt-cli-source",
        title="Security - Unsigned Add-in",
        text="Hermes Revit Operator is unsigned. Do you want to load this add-in?",
        buttons=["Always Load", "Load Once", "Do Not Load"],
    )
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "model-open-prompt-approval-cli-test",
            "agent-model-open-prompt-approval-plan",
            "--choreography",
            str(choreography_path),
        ]
    )
    assert code == 0
    approval_stdout = capsys.readouterr().out
    approval = json.loads(approval_stdout)
    assert approval["approval_required_count"] == 1
    assert "APPROVE:" not in approval_stdout

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "model-open-prompt-execute-cli-test",
            "agent-model-open-execute-approved-prompt",
            "--approval-material",
            approval["private_material_path"],
            "--item-id",
            "model-open-prompt:0:0:unsigned-addin",
        ]
    )
    assert code == 0
    execute_stdout = capsys.readouterr().out
    output = json.loads(execute_stdout)
    assert output["status"] == "ready_for_approval_execution"
    assert output["action_result"]["status"] == "dry_run"
    assert "APPROVE:" not in execute_stdout


def test_model_open_choreography_dry_run_redacts_open_approval(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "revit_running": True}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")

    def fake_open_model(*_args, **_kwargs):
        return {
            "success": True,
            "dry_run": True,
            "policy": {"decision": APPROVAL_REQUIRED, "approval_token": "APPROVE:open-secret"},
            "next_step": "Re-run with --approval-token APPROVE:open-secret",
            "operation_plan": {"expected_prompts": ["upgrade-model"]},
        }

    journal = TaskJournal(tmp_path, "model-open-choreography-dry-run-test")
    result = model_open_choreography.run_model_open_choreography(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        model_path=model,
        revit_version="2025",
        allow_model_outside_safe_root=True,
        open_model_func=fake_open_model,
    )

    assert result["success"] is True
    assert result["status"] == "planned_open"
    assert result["planned_only"] is True
    assert result["safety_summary"]["open_executed"] is False
    assert "APPROVE:open-secret" not in json.dumps(result)
    assert (journal.run_dir / "model_open_choreography.json").exists()


def test_model_open_choreography_stops_on_existing_prompt(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Upgrade model"}], "revit_running": True}

        def list_dialogs(self):
            return {
                "supported": True,
                "dialogs": [
                    {
                        "hwnd": 42,
                        "title": "Upgrade model",
                        "dialog_text": "This model must be upgraded before it can be opened.",
                        "buttons": ["Cancel", "Upgrade"],
                    }
                ],
            }

    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    called = False

    def fake_open_model(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"success": True}

    result = model_open_choreography.run_model_open_choreography(
        TaskJournal(tmp_path, "model-open-existing-prompt-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        model_path=model,
        allow_model_outside_safe_root=True,
        open_model_func=fake_open_model,
    )

    assert result["success"] is True
    assert result["status"] == "blocked_existing_prompt"
    assert called is False
    assert result["prompt_events"][0]["plans"][0]["known_dialog_id"] == "upgrade-model"
    assert result["safety_summary"]["prompt_button_clicked"] is False


def test_model_open_choreography_execute_stops_on_post_launch_prompt(tmp_path):
    class FakeObserver:
        def __init__(self):
            self.dialog_calls = 0

        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Open Worksets"}], "revit_running": True}

        def list_dialogs(self):
            self.dialog_calls += 1
            if self.dialog_calls == 1:
                return {"supported": True, "dialogs": []}
            return {
                "supported": True,
                "dialogs": [
                    {
                        "hwnd": 77,
                        "title": "Open Worksets",
                        "dialog_text": "Specify worksets to open.",
                        "buttons": ["OK", "Cancel"],
                    }
                ],
            }

    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")

    def fake_open_model(*_args, **_kwargs):
        return {"success": True, "dry_run": False, "launched": True, "pid": 1234}

    result = model_open_choreography.run_model_open_choreography(
        TaskJournal(tmp_path, "model-open-post-prompt-test"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        model_path=model,
        execute_open=True,
        approval_token="APPROVE:test",
        allow_model_outside_safe_root=True,
        timeout=1,
        poll=0.1,
        open_model_func=fake_open_model,
    )

    assert result["success"] is True
    assert result["status"] == "stopped_on_prompt"
    assert result["prompt_events"][0]["plans"][0]["known_dialog_id"] == "open-worksets"
    assert result["safety_summary"]["open_executed"] is True
    assert result["safety_summary"]["prompt_button_clicked"] is False


def test_cli_exposes_model_open_choreography_command(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "revit_running": True}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")

    def fake_open_model(*_args, **_kwargs):
        return {
            "success": True,
            "dry_run": True,
            "policy": {"decision": APPROVAL_REQUIRED, "approval_token": "APPROVE:cli-secret"},
            "next_step": "Re-run with --approval-token APPROVE:cli-secret",
        }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(model_open_choreography, "open_model", fake_open_model)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "model-open-choreography-cli-test",
            "agent-model-open-choreography",
            "--model",
            str(model),
            "--revit-version",
            "2025",
            "--allow-model-outside-safe-root",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["status"] == "planned_open"
    assert "APPROVE:cli-secret" not in stdout


def test_agent_session_checkpoint_resume_ready_when_idle(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "revit_running": True, "main_window": {"hwnd": 1}}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    class FakeBridge:
        def bridge_status(self):
            return {"available": True, "status": "connected"}

        def active_document_status(self):
            return {"available": True, "document": {"title": "Model"}}

        def read_command_results(self):
            return [{"id": "latest", "success": True}]

    journal = TaskJournal(tmp_path, "agent-session-checkpoint-ready-test")
    result = session_checkpoint.write_agent_session_checkpoint(
        journal,
        FakeObserver(),
        FakeBridge(),
        objective="Inspect sheets for hours.",
        expected_revit_version="2025",
    )

    assert result["success"] is True
    assert result["status"] == "resume_ready"
    assert result["blockers"] == []
    assert any(command["id"] == "session-preflight" for command in result["resume_commands"])
    assert all("--execute" not in command["command"] for command in result["resume_commands"])
    assert (journal.run_dir / "agent_session_checkpoint.json").exists()
    assert (journal.run_dir / "agent_session_checkpoints.jsonl").exists()


def test_agent_session_checkpoint_blocks_on_modal_dialog(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Upgrade model"}], "revit_running": True}

        def list_dialogs(self):
            return {"supported": True, "dialogs": [{"title": "Upgrade model", "buttons": ["Cancel", "Upgrade"]}]}

    class FakeBridge:
        def bridge_status(self):
            return {"available": False, "status": "stub"}

        def active_document_status(self):
            return {"available": False}

        def read_command_results(self):
            return []

    result = session_checkpoint.write_agent_session_checkpoint(
        TaskJournal(tmp_path, "agent-session-checkpoint-modal-test"),
        FakeObserver(),
        FakeBridge(),
        objective="Open the model.",
    )

    blocker_ids = {blocker["id"] for blocker in result["blockers"]}
    resume_ids = {command["id"] for command in result["resume_commands"]}
    assert result["status"] == "blocked"
    assert {"revit-state-modal", "active-dialog", "bridge-unavailable", "active-document-unavailable"}.issubset(blocker_ids)
    assert "classify-current-dialog" in resume_ids
    assert result["resume_safety"]["contains_approval_token"] is False


def test_cli_exposes_agent_session_checkpoint_command(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": [], "revit_running": True, "main_window": {"hwnd": 1}}

        def list_dialogs(self):
            return {"supported": True, "dialogs": []}

    class FakeBridge:
        def __init__(self, _sandbox):
            pass

        def bridge_status(self):
            return {"available": True, "status": "connected"}

        def active_document_status(self):
            return {"available": True, "document": {"title": "Model"}}

        def read_command_results(self):
            return []

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(cli, "RevitBridgeClient", FakeBridge)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-session-checkpoint-cli-test",
            "agent-session-checkpoint",
            "--objective",
            "Inspect sheets for hours.",
            "--expected-revit-version",
            "2025",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["status"] == "resume_ready"
    assert output["goal_complete"] is False
    assert "APPROVE:" not in stdout
