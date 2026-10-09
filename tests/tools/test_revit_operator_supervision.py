"""Revit operator supervision: recovery snapshots and drills, endurance, supervise-session."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tools.revit_operator import cli
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.recovery import capture_recovery_snapshot, validate_recovery_drill_matrix
from tools.revit_operator.supervision import (
    audit_supervision_endurance,
    build_supervision_status,
    supervise_session,
    validate_supervision_endurance_matrix,
)
from tools.revit_operator.supervised_ops import run_supervised_ops_audit


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


def test_agent_session_supervision_status_reports_active_pid(tmp_path):
    run_dir = tmp_path / "revit_operator_runs" / "live-supervise-status-running"
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

    result = build_supervision_status(
        TaskJournal(tmp_path, "agent-session-supervision-status-test"),
        target_hours=1.0,
        audit_now=datetime(2026, 5, 12, 10, 10, tzinfo=timezone.utc),
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "active"
    assert result["active_supervision_count"] == 1
    assert result["endurance_audit"]["target_met"] is False
    assert result["goal_complete"] is False
    assert result["may_call_update_goal"] is False
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert (TaskJournal(tmp_path, "agent-session-supervision-status-test").run_dir).exists()


def test_cli_exposes_agent_session_supervision_status(tmp_path, capsys):
    run_dir = tmp_path / "revit_operator_runs" / "live-supervise-status-cli"
    run_dir.mkdir(parents=True)
    (run_dir / "supervision_log.json").write_text(
        json.dumps(
            {
                "success": True,
                "checkpoint_status": "complete",
                "in_progress": False,
                "segments": [
                    {
                        "started_at": "2026-05-12T10:00:00Z",
                        "finished_at": "2026-05-12T10:05:00Z",
                        "stop_reason": "duration_elapsed",
                    }
                ],
                "checks": [
                    {"checked_at": "2026-05-12T10:00:00Z", "state": "idle"},
                    {"checked_at": "2026-05-12T10:05:00Z", "state": "idle"},
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
            "agent-session-supervision-status-cli-test",
            "agent-session-supervision-status",
            "--target-hours",
            "1",
            "--allow-logs-without-live-window",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["success"] is True
    assert output["goal_complete"] is False
    assert output["may_call_update_goal"] is False
    assert "APPROVE:" not in stdout


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
