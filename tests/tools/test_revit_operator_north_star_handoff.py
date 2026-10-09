"""North-star handoff: status, watch, resume check, human gate cards, ledger, unblock readiness."""

import json
import os
from pathlib import Path

from tests.tools.revit_operator_helpers import (
    _read_only_refresh_fields,
    _test_preflight_freshness,
)
from tools.revit_operator import cli
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.north_star as north_star


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
