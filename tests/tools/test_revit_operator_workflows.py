"""Revit operator workflows: recorded workflows, UI workflow recipes, replay, read-only QA."""

import json
from pathlib import Path

from tests.tools.revit_operator_helpers import (
    _current_bridge_addin,
    _write_bridge_payload,
)
from tools.revit_operator import cli
from tools.revit_operator.actions import ActionRequest, SafeActionExecutor
import tools.revit_operator.bridge as bridge_module
import tools.revit_operator.workflows as workflows
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.constants import DRAFT_LABEL
from tools.revit_operator.execution_audit import audit_ui_execution_coverage
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.safety import (
    APPROVAL_REQUIRED,
    classify_action,
)
from tools.revit_operator.ui_workflows import (
    list_ui_workflows,
    plan_ui_workflow,
    run_ui_workflow,
    run_ui_workflow_smoke_matrix,
    validate_ui_workflow_matrix,
)
from tools.revit_operator.workflow_memory import plan_workflow_approvals, record_workflow, replay_workflow
from tools.revit_operator.workflows import run_readonly_qa_workflow


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


def test_safe_action_executor_records_target_window_process_document(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {9001: 222}.get(hwnd))
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge_dir = tmp_path / "bridge"
    _write_bridge_payload(bridge_dir / "active_document.json", {"available": True, "document": {"title": "Other"}})
    _write_bridge_payload(bridge_dir / "addin_heartbeat.222.json", {"status": "idling", "addin": _current_bridge_addin(222)})
    _write_bridge_payload(
        bridge_dir / "active_document.222.json",
        {"available": True, "document": {"title": "Target"}, "addin": _current_bridge_addin(222)},
    )

    class FakeObserver:
        supported = False

        def status(self):
            return {"state": "idle", "active_dialogs": []}

    journal = TaskJournal(tmp_path, "action-target-context-test")
    result = SafeActionExecutor(FakeObserver(), journal).run(
        ActionRequest(action="press-key", payload={"key": "Escape", "hwnd": 9001}, dry_run=True)
    )

    document = result["before"]["active_document"]
    assert document["status_source"] == "process"
    assert document["document"]["document"]["title"] == "Target"


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

        def ui_tree(self, hwnd=None, max_depth=2):
            return {"supported": True, "tree": {"title": "Revit"}}

        def screenshot(self, output, hwnd=None):
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
