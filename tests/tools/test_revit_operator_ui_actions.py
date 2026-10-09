"""Revit operator UI actions: ribbon and context-menu actions, approval policy, coverage audit."""

import json
from pathlib import Path

from tools.revit_operator import cli
from tools.revit_operator.actions import validate_action_approval_matrix
import tools.revit_operator.context_menu as context_menu
from tools.revit_operator.execution_audit import audit_ui_execution_coverage
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.ribbon as ribbon
from tools.revit_operator.safety import (
    APPROVAL_REQUIRED,
    BLOCK,
    authorize,
    classify_action,
)
from tools.revit_operator.uia import validate_uia_method_matrix


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
    assert classify_action("list-safe-models").decision == "allow"
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
    assert classify_action("agent-session-supervision-status").decision == "allow"
    assert classify_action("agent-session-real-gate-ledger").decision == "allow"
    assert classify_action("agent-session-approval-readiness-queue").decision == "allow"
    assert classify_action("recovery-drill-matrix").decision == "allow"
    assert classify_action("workflow-approval-plan").decision == "allow"
    assert classify_action(
        "run-safe-command", {"name": "active-document"}
    ).decision == "allow"
    assert classify_action("run-safe-command", {"name": "save"}).decision == BLOCK
