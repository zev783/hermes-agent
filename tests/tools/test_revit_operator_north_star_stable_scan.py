"""North-star stable artifact scan: drift, stale credentials, authority leaks in stable files."""

import json
import os
from pathlib import Path

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
