"""North-star completion gate: audit and authority checks, safety guards, drift repair routing."""

import json
from pathlib import Path

import pytest

from tests.tools.revit_operator_helpers import (
    _read_only_refresh_fields,
    _test_preflight_freshness,
    _write_restart_freshness_fixture,
    _write_resume_artifact,
    _write_stable_scan_current,
    _write_unblock_readiness_current,
    _write_watch_artifact,
)
from tools.revit_operator import cli
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.north_star as north_star


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
