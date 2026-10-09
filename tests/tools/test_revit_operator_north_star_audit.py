"""North-star audit: gap detection, evidence checks, refresh sequence and its runbook procedure."""

import json
from pathlib import Path

from tools.revit_operator import cli
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.north_star as north_star
from tools.revit_operator.north_star import run_north_star_audit


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
