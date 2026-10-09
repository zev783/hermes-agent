"""North-star approved-execution preview.

Each test rebuilds the full waiting state (about 10 s apiece), so these sit
apart from the approval tests to keep either file well under the test
runner's per-file timeout.
"""

import json
from pathlib import Path

from tests.tools.revit_operator_helpers import _test_preflight_freshness
from tools.revit_operator import cli
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.north_star as north_star


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
