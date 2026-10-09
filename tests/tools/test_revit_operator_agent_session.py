"""Revit operator agent commands: task, session, UI flow, model-open prompts, checkpoints."""

import json
from datetime import datetime, timezone
from pathlib import Path

from tests.tools.revit_operator_helpers import (
    _live_revit_processes,
    _start_bridge_session,
)
from tools.revit_operator import cli
import tools.revit_operator.agent_session as agent_session
from tools.revit_operator.agent_session import plan_agent_session, run_agent_session
import tools.revit_operator.agent_task as agent_task
from tools.revit_operator.agent_task import plan_agent_task, run_agent_task
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.constants import DRAFT_LABEL
from tools.revit_operator.dialog_workflows import plan_dialog_response
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.model_open_choreography as model_open_choreography
from tools.revit_operator.safety import (
    ALLOW,
    APPROVAL_REQUIRED,
    BLOCK,
)
import tools.revit_operator.session_checkpoint as session_checkpoint
from tools.revit_operator.windows import RevitWindowObserver


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


def test_agent_session_completion_audit_refuses_without_live_evidence(tmp_path):
    journal = TaskJournal(tmp_path, "agent-session-completion-audit-empty-test")

    result = agent_session.build_agent_session_completion_audit(
        journal,
        objective="have revit autonomously handle arbitrary ui flows and multi-hour task planning",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "incomplete"
    assert result["goal_complete"] is False
    assert result["completion_allowed"] is False
    assert result["may_call_update_goal"] is False
    assert result["blocked_count"] > 0
    assert len(result["prompt_to_artifact_checklist"]) == sum(
        len(requirement["success_criteria"]) for requirement in agent_session.AGENT_REQUIREMENTS
    )
    assert all("--execute" not in command for command in result["next_recommended_commands"])
    assert all("APPROVE:" not in command for command in result["next_recommended_commands"])
    assert result["next_commands_are_read_only"] is True
    assert (journal.run_dir / "agent_session_completion_audit.json").exists()


def test_agent_session_completion_audit_maps_artifacts_and_withholds_private_tokens(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "evidence"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_ui_flow_scout.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-scout/v1",
                "success": True,
                "status": "candidates_ready",
                "candidates": [{"target": "Manage Links"}],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_ui_flow_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-approval-material/v1",
                "approval_items": [{"id": "candidate-1", "approval_token": "APPROVE:secret-token"}],
            }
        ),
        encoding="utf-8",
    )

    result = agent_session.build_agent_session_completion_audit(
        TaskJournal(tmp_path, "agent-session-completion-audit-token-test"),
        objective="have revit autonomously handle arbitrary ui flows",
    )

    assert result["status"] == "incomplete"
    scout_rows = [
        row
        for row in result["prompt_to_artifact_checklist"]
        if row["id"] == "arbitrary-ui-flows:criterion-1"
    ]
    assert scout_rows and scout_rows[0]["satisfied"] is True
    private_summaries = [
        item
        for item in result["artifact_inventory"]["artifacts"]
        if item["schema"] == "hermes-revit-agent-ui-flow-approval-material/v1"
    ]
    assert private_summaries
    assert private_summaries[0]["private_payload_withheld"] is True
    result_text = json.dumps(result)
    artifact_text = Path(result["path"]).read_text(encoding="utf-8")
    assert "APPROVE:secret-token" not in result_text
    assert "APPROVE:secret-token" not in artifact_text


def test_agent_session_completion_audit_reports_readiness_evidence_without_completion(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "readiness-evidence"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_ui_flow_approved_candidate_result.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-approved-candidate/v1",
                "success": True,
                "status": "ready_for_approval_execution",
                "execute_requested": False,
                "target": "Worksets",
                "receipt": {
                    "ui_action_executed": False,
                    "model_write_performed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_session_approved_item_result.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approved-item/v1",
                "success": True,
                "status": "ready_for_approval_execution",
                "item_kind": "model-change-operation",
                "execute_requested": False,
                "execution": {
                    "operation": "reload-links",
                    "executed": False,
                    "receipt": {
                        "queued_operation": "reload-links",
                        "model_write_guard": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_session_supervision_status.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-supervision-status/v1",
                "success": True,
                "status": "active",
                "active_supervision_count": 1,
                "goal_complete": False,
                "may_call_update_goal": False,
            }
        ),
        encoding="utf-8",
    )

    result = agent_session.build_agent_session_completion_audit(
        TaskJournal(tmp_path, "agent-session-completion-audit-readiness-test"),
        objective="have revit autonomously handle arbitrary ui flows and approved model-changing work",
    )

    gates = {gate["id"]: gate for gate in result["hard_completion_gates"]}
    assert gates["arbitrary-ui-live-execution"]["passed"] is False
    assert gates["arbitrary-ui-live-execution"]["readiness_evidence"]
    assert gates["approved-model-change-live-execution"]["passed"] is False
    assert gates["approved-model-change-live-execution"]["readiness_evidence"]
    assert gates["multi-hour-live-supervision-target"]["passed"] is False
    assert gates["multi-hour-live-supervision-target"]["readiness_evidence"]
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False


def test_agent_session_real_gate_ledger_summarizes_readiness_without_execution(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "readiness-evidence"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_ui_flow_approved_candidate_result.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-approved-candidate/v1",
                "success": True,
                "status": "ready_for_approval_execution",
                "item_id": "ui-candidate:7:worksets",
                "execute_requested": False,
                "receipt": {
                    "ui_action_executed": False,
                    "model_write_performed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_session_approved_item_result.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approved-item/v1",
                "success": True,
                "status": "ready_for_approval_execution",
                "item_id": "model-change:reload-links",
                "item_kind": "model-change-operation",
                "execute_requested": False,
                "execution": {
                    "operation": "reload-links",
                    "executed": False,
                    "receipt": {
                        "queued_operation": "reload-links",
                        "model_write_guard": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = agent_session.build_agent_session_real_gate_ledger(
        TaskJournal(tmp_path, "agent-session-real-gate-ledger-test"),
        objective="have revit autonomously handle arbitrary ui flows and approved model-changing work",
        refresh_supervision_status=False,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "waiting_on_human_or_real_conditions"
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert result["execution_guard"]["may_execute_from_this_result"] is False
    assert result["execution_guard"]["approval_tokens_included"] is False
    assert result["execution_guard"]["approval_phrases_included"] is False
    assert result["gate_summary"]["ready_for_human_or_real_condition"] >= 2
    assert any(gate["id"] == "arbitrary-ui-live-execution" for gate in result["real_gates"])
    assert all(action["read_only"] for action in result["next_read_only_actions"])
    assert all("--execute" not in action["command"] for action in result["next_read_only_actions"])
    assert "APPROVE:" not in json.dumps(result)
    assert (TaskJournal(tmp_path, "agent-session-real-gate-ledger-test").run_dir / "agent_session_real_gate_ledger.json").exists()


def test_cli_exposes_agent_session_completion_audit_with_redacted_stdout(tmp_path, capsys):
    run_dir = tmp_path / "revit_operator_runs" / "cli-evidence"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_session_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approval-material/v1",
                "approval_items": [{"id": "reload-links", "approval_token": "APPROVE:cli-secret"}],
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
            "agent-session-completion-audit-cli-test",
            "agent-session-completion-audit",
            "--objective",
            "have revit autonomously handle arbitrary ui flows",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["goal_complete"] is False
    assert output["may_call_update_goal"] is False
    assert "APPROVE:cli-secret" not in stdout


def test_cli_exposes_agent_session_real_gate_ledger_with_redacted_stdout(tmp_path, capsys):
    run_dir = tmp_path / "revit_operator_runs" / "cli-evidence"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_session_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approval-material/v1",
                "approval_items": [{"id": "reload-links", "approval_token": "APPROVE:cli-secret"}],
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
            "agent-session-real-gate-ledger-cli-test",
            "agent-session-real-gate-ledger",
            "--objective",
            "have revit autonomously handle arbitrary ui flows",
            "--no-refresh-supervision-status",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["goal_complete"] is False
    assert output["may_call_update_goal"] is False
    assert output["execution_guard"]["may_execute_from_this_result"] is False
    assert "APPROVE:cli-secret" not in stdout


def test_agent_session_approval_readiness_queue_lists_items_without_tokens(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "approval-materials"
    run_dir.mkdir(parents=True)
    fresh_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (run_dir / "agent_ui_flow_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-ui-flow-approval-material/v1",
                "created_at": fresh_now,
                "source_scout_path": str(run_dir / "agent_ui_flow_scout.json"),
                "approval_items": [
                    {
                        "id": "ui-candidate:7:worksets",
                        "kind": "ui-candidate-control",
                        "target": "Worksets",
                        "risk": "high",
                        "approval_token": "APPROVE:ui-secret",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_session_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approval-material/v1",
                "created_at": fresh_now,
                "objective": "reload links",
                "approval_items": [
                    {
                        "id": "model-change:reload-links",
                        "kind": "model-change-operation",
                        "operation": "reload-links",
                        "approval_token": "APPROVE:model-secret",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "model_open_prompt_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-model-open-prompt-approval-material/v1",
                "created_at": fresh_now,
                "source_choreography_path": str(run_dir / "model_open_choreography.json"),
                "approval_items": [
                    {
                        "id": "prompt:0:0:ok",
                        "kind": "model-open-prompt",
                        "target": "OK",
                        "approval_token": "APPROVE:prompt-secret",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = agent_session.build_agent_session_approval_readiness_queue(
        TaskJournal(tmp_path, "agent-session-approval-readiness-queue-test")
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "ready_items_found"
    assert result["ready_item_count"] == 3
    assert result["fresh_item_count"] == 3
    assert result["recommended_item_count"] == 3
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert result["execution_guard"]["may_execute_from_this_result"] is False
    assert result["execution_guard"]["approval_tokens_included"] is False
    assert result["execution_guard"]["approval_phrases_included"] is False
    commands = [item["dry_run_command"] for item in result["ready_items"]]
    assert any(command.startswith("agent-ui-flow-execute-approved-candidate") for command in commands)
    assert any(command.startswith("agent-session-execute-approved-item") for command in commands)
    assert any(command.startswith("agent-model-open-execute-approved-prompt") for command in commands)
    assert all("--execute" not in command for command in commands)
    assert all("APPROVE:" not in command for command in commands)
    ui_item = next(item for item in result["ready_items"] if item["id"] == "ui-candidate:7:worksets")
    model_item = next(item for item in result["ready_items"] if item["id"] == "model-change:reload-links")
    prompt_item = next(item for item in result["ready_items"] if item["id"] == "prompt:0:0:ok")
    assert ui_item["approved_ui_operator_consent_supported"] is True
    assert "--allow-approved-ui" in ui_item["approved_ui_execute_command"]
    assert "--execute" in ui_item["approved_ui_execute_command"]
    assert model_item["approved_ui_operator_consent_supported"] is False
    assert model_item["approved_ui_execute_command"] is None
    assert prompt_item["approved_ui_operator_consent_supported"] is False
    assert all(item["fresh"] is True for item in result["recommended_items"])
    assert all(item["source_context"] == "live_or_user_generated" for item in result["recommended_items"])
    assert "APPROVE:" not in json.dumps(result)
    assert "I approve" not in json.dumps(result)
    assert (TaskJournal(tmp_path, "agent-session-approval-readiness-queue-test").run_dir / "agent_session_approval_readiness_queue.json").exists()


def test_agent_session_approval_readiness_queue_prefers_fresh_live_material(tmp_path):
    live_dir = tmp_path / "revit_operator_runs" / "agent-session-approval-live"
    smoke_dir = tmp_path / "revit_operator_runs" / "agent-session-approval-smoke"
    live_dir.mkdir(parents=True)
    smoke_dir.mkdir(parents=True)
    fresh_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for directory, created_at, token in (
        (live_dir, fresh_now, "APPROVE:live-secret"),
        (smoke_dir, "2020-01-01T00:00:00Z", "APPROVE:stale-secret"),
    ):
        (directory / "agent_session_approval_private_material.json").write_text(
            json.dumps(
                {
                    "schema": "hermes-revit-agent-session-approval-material/v1",
                    "created_at": created_at,
                    "objective": "reload links",
                    "approval_items": [
                        {
                            "id": "model-change:reload-links",
                            "kind": "model-change-operation",
                            "operation": "reload-links",
                            "approval_token": token,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    result = agent_session.build_agent_session_approval_readiness_queue(
        TaskJournal(tmp_path, "agent-session-approval-readiness-fresh-test"),
        fresh_minutes=60,
    )

    assert result["ready_item_count"] == 2
    assert result["fresh_item_count"] == 1
    assert result["stale_item_count"] == 1
    assert result["recommended_items"][0]["operation"] == "reload-links"
    assert "agent-session-approval-live" in result["recommended_items"][0]["material_path"]
    assert result["recommended_items"][0]["fresh"] is True
    assert result["recommended_items"][0]["source_context"] == "live_or_user_generated"
    assert any(item["source_context"] == "synthetic_or_smoke" for item in result["ready_items"])
    assert "APPROVE:" not in json.dumps(result)


def test_cli_exposes_agent_session_approval_readiness_queue_with_redacted_stdout(tmp_path, capsys):
    run_dir = tmp_path / "revit_operator_runs" / "cli-approval-materials"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_session_approval_private_material.json").write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-approval-material/v1",
                "approval_items": [
                    {
                        "id": "model-change:reload-links",
                        "kind": "model-change-operation",
                        "operation": "reload-links",
                        "approval_token": "APPROVE:cli-secret",
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
            "agent-session-approval-readiness-queue-cli-test",
            "agent-session-approval-readiness-queue",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["ready_item_count"] == 1
    assert output["goal_complete"] is False
    assert output["may_call_update_goal"] is False
    assert output["execution_guard"]["may_execute_from_this_result"] is False
    assert "APPROVE:cli-secret" not in stdout
    assert "I approve" not in stdout


def test_agent_session_evidence_refresh_runs_readonly_collectors(tmp_path):
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

        def ui_tree(self, max_depth=4):
            return _fake_agent_ui_tree()

    journal = TaskJournal(tmp_path, "agent-session-evidence-refresh-test")

    result = agent_session.refresh_agent_session_evidence(
        journal,
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        objective="Use Manage Links, reload links if approved, and supervise for hours.",
        expected_revit_version="2025",
        max_hours=1,
        ui_limit=5,
    )

    step_ids = {step["id"] for step in result["steps"]}
    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "blocked_at_completion_gates"
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert result["safety_summary"]["clicked_or_typed"] is False
    assert result["safety_summary"]["model_write_performed"] is False
    assert {
        "agent-session-checkpoint",
        "agent-session-resume-plan",
        "agent-ui-flow-scout",
        "agent-ui-flow-approval-plan",
        "agent-session-approval-plan",
        "supervision-endurance-audit",
        "agent-session-completion-audit",
    }.issubset(step_ids)
    assert result["completion_audit"]["blocked_count"] > 0
    assert "APPROVE:" not in json.dumps(result)
    assert (journal.run_dir / "agent_session_evidence_refresh.json").exists()


def test_cli_exposes_agent_session_evidence_refresh_with_redacted_stdout(tmp_path, capsys, monkeypatch):
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

        def ui_tree(self, max_depth=4):
            return _fake_agent_ui_tree()

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-session-evidence-refresh-cli-test",
            "agent-session-evidence-refresh",
            "--objective",
            "Use Manage Links, reload links if approved, and supervise for hours.",
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
    assert output["safety_summary"]["commands_are_read_only"] is True
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


def test_agent_session_approval_plan_keeps_tokens_private(tmp_path, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    journal = TaskJournal(tmp_path, "agent-session-approval-plan-test")
    result = agent_session.build_agent_session_approval_plan(
        journal,
        objective="Use Manage Links, reload links if approved, and update project info parameters.",
        parameters={"parameter_name": "Project Status", "parameter_value": "QA Draft"},
        target_pid=222,
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


def test_agent_session_execute_approved_model_change_dry_run_redacts_tokens(tmp_path, monkeypatch):
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

    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    approval_journal = TaskJournal(tmp_path, "approval-source")
    approval = agent_session.build_agent_session_approval_plan(
        approval_journal,
        objective="Reload links if approved.",
        target_pid=222,
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
    # The approved Revit's own document, not whichever session wrote the shared file last.
    assert result["execution"]["pre_action_active_document"]["status_source"] == "process"
    assert result["execution"]["pre_action_active_document"]["document"]["document"]["title"] == "Target Model"
    assert result["execution"]["dry_run_result"]["authorization"]["allowed"] is True
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

    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    approval_journal = TaskJournal(tmp_path, "approval-source-confirm")
    approval = agent_session.build_agent_session_approval_plan(
        approval_journal,
        objective="Reload links if approved.",
        target_pid=222,
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
    ui_consent_wrong = agent_session.execute_agent_session_approved_item(
        TaskJournal(tmp_path, "approved-item-ui-consent-does-not-bypass-model-change"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="model-change:reload-links",
        execute=True,
        allow_approved_ui=True,
        bridge_refresh_timeout=0,
    )
    assert ui_consent_wrong["status"] == "stopped_confirmation_required"
    assert ui_consent_wrong["execution"]["allow_approved_ui"] is True
    assert ui_consent_wrong["execution"]["ui_operator_consent_ok"] is False
    assert ui_consent_wrong["execution"]["confirmation_bypassed_for_ui_only"] is False
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
    # The change and its refresh go to the Revit process the item was approved for.
    assert model_calls[-1].target_pid == refresh_calls[-1].target_pid == 222
    assert executed["execution"]["receipt"]["post_action_refresh_requested"] is True
    assert executed["execution"]["post_action_refresh"]["command"]["operation"] == "active-document"
    assert "APPROVE:" not in json.dumps(executed)


def test_agent_session_execute_approved_ui_workflow_allows_operator_consent(tmp_path):
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

    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "approval-source-ui-consent"),
        objective="Open Manage Links for inspection if approved.",
    )
    calls = []

    def fake_runner(argv, index):
        calls.append((index, argv))
        return {"success": True, "argv": argv}

    result = agent_session.execute_agent_session_approved_item(
        TaskJournal(tmp_path, "approved-ui-workflow-consent"),
        FakeObserver(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id="ui:manage-links-inspection:step:2",
        execute=True,
        allow_approved_ui=True,
        bridge_refresh_timeout=0,
        ui_command_runner=fake_runner,
    )

    assert result["status"] == "executed"
    assert result["execution"]["executed"] is True
    assert result["execution"]["confirmation_required"] is False
    assert result["execution"]["confirmation_ok"] is False
    assert result["execution"]["ui_operator_consent_ok"] is True
    assert result["execution"]["confirmation_bypassed_for_ui_only"] is True
    assert result["execution"]["approval_relaxation_policy"] == "approved-ui-only-private-material-operator-consent"
    assert result["execution"]["model_write_performed"] is False
    assert calls[-1][1][:2] == ["ribbon-action", "--name"]
    assert "--execute" in calls[-1][1]
    assert "--approval-token" in calls[-1][1]
    assert "APPROVE:" not in json.dumps(result)


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
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "approval-source-cli"),
        objective="Reload links if approved.",
        target_pid=222,
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

    allowed_by_ui_consent = agent_session.execute_ui_flow_approved_candidate(
        TaskJournal(tmp_path, "agent-ui-flow-execute-allow-approved-ui"),
        FakeObserver(),
        approval_material_path=material_path,
        item_id="ui-candidate:0:manage-links",
        execute=True,
        allow_approved_ui=True,
    )

    assert allowed_by_ui_consent["status"] == "executed"
    assert allowed_by_ui_consent["confirmation_required"] is False
    assert allowed_by_ui_consent["confirmation_ok"] is False
    assert allowed_by_ui_consent["allow_approved_ui"] is True
    assert allowed_by_ui_consent["ui_operator_consent_ok"] is True
    assert allowed_by_ui_consent["confirmation_bypassed_for_ui_only"] is True
    assert allowed_by_ui_consent["approval_relaxation_policy"] == "approved-ui-only-private-material-operator-consent"
    assert allowed_by_ui_consent["receipt"]["approved_ui_operator_consent"] is True
    assert allowed_by_ui_consent["receipt"]["model_write_performed"] is False
    assert calls[-1].action == "uia-invoke"
    assert calls[-1].dry_run is False
    assert calls[-1].approval_token.startswith("APPROVE:")
    assert "APPROVE:" not in json.dumps(allowed_by_ui_consent)

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


def test_cli_exposes_agent_ui_flow_execute_approved_candidate_allow_approved_ui(tmp_path, capsys, monkeypatch):
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

    class FakeExecutor:
        def __init__(self, observer, journal):
            self.observer = observer
            self.journal = journal

        def run(self, request):
            return {
                "status": "executed",
                "executed": True,
                "dry_run": request.dry_run,
                "policy": {"approval_token": request.approval_token},
                "authorization": {"allowed": True},
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(agent_session, "SafeActionExecutor", FakeExecutor)
    source = TaskJournal(tmp_path, "agent-ui-flow-execute-cli-consent-source")
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
        TaskJournal(tmp_path, "agent-ui-flow-execute-cli-consent-approval"),
        scout_path=scout_path,
    )

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "agent-ui-flow-execute-cli-consent-test",
            "agent-ui-flow-execute-approved-candidate",
            "--approval-material",
            approval["private_material_path"],
            "--item-id",
            "ui-candidate:0:manage-links",
            "--execute",
            "--allow-approved-ui",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["status"] == "executed"
    assert output["allow_approved_ui"] is True
    assert output["ui_operator_consent_ok"] is True
    assert output["confirmation_bypassed_for_ui_only"] is True
    assert output["receipt"]["model_write_performed"] is False
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


def test_agent_session_resume_plan_uses_resume_ready_checkpoint(tmp_path):
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
            return []

    checkpoint_journal = TaskJournal(tmp_path, "agent-session-resume-checkpoint-ready")
    checkpoint = session_checkpoint.write_agent_session_checkpoint(
        checkpoint_journal,
        FakeObserver(),
        FakeBridge(),
        objective="Inspect sheets for hours.",
        expected_revit_version="2025",
    )
    result = session_checkpoint.build_agent_session_resume_plan(
        TaskJournal(tmp_path, "agent-session-resume-plan-ready"),
        checkpoint_path=Path(checkpoint["path"]),
        resume_minutes=15,
    )

    assert result["success"] is True
    assert result["status"] == "resume_ready"
    assert result["recommended_next_action"] == "resume_readonly_preflight"
    commands = {step["id"]: step["command"] for step in result["resume_sequence"]}
    assert "session-preflight" in commands
    assert "timed-supervision-resume" in commands
    assert result["resume_safety"]["commands_are_read_only"] is True
    assert result["resume_safety"]["contains_execute_flag"] is False
    assert result["resume_safety"]["contains_approval_token"] is False


def test_agent_session_resume_plan_blocks_on_modal_checkpoint(tmp_path):
    class FakeObserver:
        def status(self):
            return {"state": "modal", "active_dialogs": [{"title": "Upgrade model"}], "revit_running": True}

        def list_dialogs(self):
            return {
                "supported": True,
                "dialogs": [{"title": "Upgrade model", "dialog_text": "Upgrade required.", "buttons": ["Cancel", "Upgrade"]}],
            }

    class FakeBridge:
        def bridge_status(self):
            return {"available": True, "status": "connected"}

        def active_document_status(self):
            return {"available": True, "document": {"title": "Model"}}

        def read_command_results(self):
            return []

    checkpoint = session_checkpoint.write_agent_session_checkpoint(
        TaskJournal(tmp_path, "agent-session-resume-checkpoint-modal"),
        FakeObserver(),
        FakeBridge(),
        objective="Open copied model.",
    )
    result = session_checkpoint.build_agent_session_resume_plan(
        TaskJournal(tmp_path, "agent-session-resume-plan-modal"),
        checkpoint_path=Path(checkpoint["path"]),
    )

    assert result["success"] is True
    assert result["status"] == "blocked"
    assert result["recommended_next_action"] == "classify_prompt"
    commands = {step["id"]: step["command"] for step in result["resume_sequence"]}
    assert commands["classify-current-dialog"] == "plan-current-dialog-response"
    assert "agent-model-open-prompt-approval-plan" in commands["model-open-prompt-approval-plan"]
    assert result["resume_safety"]["contains_execute_flag"] is False
    assert result["resume_safety"]["contains_approval_token"] is False


def test_agent_session_resume_plan_finds_latest_checkpoint(tmp_path):
    checkpoint_dir = tmp_path / "revit_operator_runs" / "manual-checkpoint"
    checkpoint_dir.mkdir(parents=True)
    checkpoint_path = checkpoint_dir / "agent_session_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-checkpoint/v1",
                "created_at": "2026-05-18T00:00:00Z",
                "objective": "Inspect sheets.",
                "status": "resume_ready",
                "state": "idle",
                "blockers": [],
                "resume_commands": [{"id": "fresh-status", "command": "status", "reason": "Refresh."}],
            }
        ),
        encoding="utf-8",
    )

    result = session_checkpoint.build_agent_session_resume_plan(
        TaskJournal(tmp_path, "agent-session-resume-plan-latest"),
    )

    assert result["success"] is True
    assert result["checkpoint_path"] == str(checkpoint_path)
    assert result["status"] == "resume_ready"


def test_cli_exposes_agent_session_resume_plan_command(tmp_path, capsys):
    checkpoint_dir = tmp_path / "revit_operator_runs" / "cli-checkpoint"
    checkpoint_dir.mkdir(parents=True)
    checkpoint_path = checkpoint_dir / "agent_session_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "schema": "hermes-revit-agent-session-checkpoint/v1",
                "created_at": "2026-05-18T00:00:00Z",
                "objective": "Inspect sheets.",
                "status": "resume_ready",
                "state": "idle",
                "blockers": [],
                "resume_commands": [{"id": "fresh-status", "command": "status", "reason": "Refresh."}],
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
            "agent-session-resume-plan-cli-test",
            "agent-session-resume-plan",
            "--checkpoint",
            str(checkpoint_path),
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["status"] == "resume_ready"
    assert "APPROVE:" not in stdout
    assert "--execute" not in stdout
