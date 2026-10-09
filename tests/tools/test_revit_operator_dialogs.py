"""Revit operator dialogs: window detection, risk classification, learned rules, response plans."""

import json
from pathlib import Path

from tools.revit_operator import cli
from tools.revit_operator.dialog_memory import record_dialog_rule
from tools.revit_operator.dialog_workflows import (
    plan_current_dialog_response,
    plan_dialog_response,
    validate_dialog_workflow_matrix,
)
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.ocr as ocr_module
from tools.revit_operator.safety import (
    APPROVAL_REQUIRED,
    HIGH,
    classify_dialog,
)
from tools.revit_operator.windows import Rect, RevitWindowObserver, WindowInfo


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
