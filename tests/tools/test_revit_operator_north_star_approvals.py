"""North-star approvals: plan, preflight, ready and next approvals, waiting state, verification."""

import json
from pathlib import Path

from tests.tools.revit_operator_helpers import _test_preflight_freshness
from tools.revit_operator import cli
from tools.revit_operator.journal import TaskJournal
import tools.revit_operator.north_star as north_star


def test_north_star_approval_plan_writes_exact_tokens_without_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    runs_root = tmp_path / "revit_operator_runs"
    ribbon_dir = runs_root / "live-ribbon-view-tab-plan"
    ribbon_dir.mkdir(parents=True)
    (ribbon_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "command": "plan-ribbon-action",
                "task_id": "live-ribbon-view-tab-plan",
                "timestamp": "2026-05-13T02:48:01Z",
                "result": {"success": True, "executable": True, "match_count": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workflow_dir = runs_root / "live-project-browser-open-sheet-plan"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ui_workflow_run.json").write_text(
        json.dumps(
            {
                "dry_run": True,
                "planned_only": True,
                "captured_at": "2026-05-13T02:47:19Z",
                "journal": {"task_id": "live-project-browser-open-sheet-plan"},
                "stop_reason": "Missing or incorrect approval token for this recipe step.",
                "step_results": [
                    {"status": "ran"},
                    {"status": "ran"},
                    {
                        "status": "ran",
                        "command_result": {
                            "route": {
                                "approval_required": True,
                                "operation": "activate-view",
                                "recommended_method": "request-operation activate-view",
                            }
                        },
                    },
                    {"status": "stopped_approval_required"},
                ],
            }
        ),
        encoding="utf-8",
    )
    context_dir = runs_root / "live-context-menu-s20-plan"
    context_dir.mkdir(parents=True)
    (context_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "command": "plan-context-menu-action",
                "task_id": "live-context-menu-s20-plan",
                "timestamp": "2026-05-13T02:48:09Z",
                "result": {"success": True, "executable": False, "match_count": 0},
            }
        )
        + "\n"
        + json.dumps(
            {
                "command": "plan-context-menu-action",
                "task_id": "live-context-menu-s20-plan",
                "timestamp": "2026-05-13T02:48:10Z",
                "requested_action": {"type": "observation"},
                "result": {"success": True, "status": "observed"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json").write_text(
        json.dumps(
                {
                    "status": "preflighted",
                    "approval_preflight_freshness": _test_preflight_freshness(),
                    "ready_for_human_approval_count": 1,
                    "requires_state_change_count": 1,
                    "requires_prevalidation_count": 0,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in approval-plan test.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Target not visible in approval-plan test.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow ready in approval-plan test.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-plan-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["approval_items"]
    ribbon_item = next(item for item in result["approval_items"] if item["id"] == "safe-ribbon-view-tab")
    assert ribbon_item["approval_token"].startswith("APPROVE:")
    assert "--execute" in ribbon_item["command"]
    assert ribbon_item["expected_effect"] == "Select the Revit View ribbon tab only."
    assert ribbon_item["prevalidation"]["status"] == "prevalidated_one_exact_target"
    assert ribbon_item["approval_freshness"]["approval_token"] == ribbon_item["approval_token"]
    assert ribbon_item["approval_freshness"]["bound_payload_digest"]
    assert ribbon_item["approval_freshness"]["prevalidation_status"] == "prevalidated_one_exact_target"
    assert "Do not reuse this token" in ribbon_item["approval_freshness"]["freshness_rule"]
    workflow_item = next(item for item in result["approval_items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow_item["prevalidation"]["status"] == "prevalidated_stopped_at_approval_gate"
    assert workflow_item["prevalidation"]["approval_still_required"] is True
    assert workflow_item["dry_run_command"] == [
        "run-ui-workflow",
        "--name",
        "project-browser-open-sheet",
        "--sheet-number",
        "S2.0",
    ]
    assert workflow_item["dry_run_powershell"].endswith("--sheet-number S2.0")
    assert "--approval-tokens-json" in workflow_item["execute_powershell"]
    context_action = next(item for item in result["approval_items"] if item["id"] == "context-menu-project-browser-target")
    assert context_action["prevalidation"]["status"] == "not_currently_executable"
    assert context_action["prevalidation"]["match_count"] == 0
    item = next(item for item in result["approval_items"] if item["id"] == "context-menu-select-properties-item")
    assert item["approval_token"] is None
    assert item["approval_token_withheld"] is True
    assert item["currently_executable"] is False
    assert "plan-context-menu-item" in item["precondition"]
    assert any(item["id"] == "human-restart-reload-revit" for item in result["manual_items"])
    assert "does not focus, click, type, invoke UIA" in result["safety_note"]
    assert result["blocker_summary"]["blocked_gap_count"] == 5
    assert result["blocked_gap_count"] == result["blocker_summary"]["blocked_gap_count"]
    assert result["blocked_gate_count"] == result["blocked_gap_count"]
    assert result["blocked_gap_ids"] == sorted(result["blocker_summary"]["blocked_gap_ids"])
    assert result["cleared_gap_count"] == result["blocker_summary"]["cleared_gap_count"]
    assert result["cleared_gap_ids"] == result["blocker_summary"]["cleared_gap_ids"]
    assert result["blocker_summary"]["human_required"] is True
    assert result["completion_actions"]["may_call_update_goal"] is False
    assert result["autonomous_progress_available"] is result["completion_actions"][
        "autonomous_progress_available"
    ]
    assert result["human_or_real_condition_required"] is result["completion_actions"][
        "human_or_real_condition_required"
    ]
    assert result["blocked_waiting_for_human_or_real_condition"] is False
    assert result["completion_actions"]["autonomous_actions"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW" in markdown_text
    assert "blocked_gap_count:" in markdown_text
    assert "blocked_gate_count:" in markdown_text
    assert "blocked_waiting_for_human_or_real_condition: `false`" in markdown_text
    assert "Approval Preflight Readiness" in markdown_text
    assert "ready_for_human_approval_count: `1`" in markdown_text
    assert "Dry run before approval" in markdown_text
    assert "Execute only after explicit approval" in markdown_text
    assert "Approval readiness: `requires_ui_state_change`" in markdown_text
    assert "Execute withheld" in markdown_text
    assert "north-star-approval-verify" in markdown_text
    assert "Bound payload digest" in markdown_text
    assert "Freshness rule" in markdown_text
    assert "--approval-tokens-json" in markdown_text


def test_north_star_ready_approvals_lists_only_preflight_ready_items(tmp_path, monkeypatch):
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
                "ready_for_human_approval_count": 2,
                "requires_state_change_count": 1,
                "requires_prevalidation_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow dry-run passed.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Project Browser target is not visible.",
                        },
                    },
                    {
                        "id": "context-menu-select-properties-item",
                        "status": "planned_only",
                        "preflight_success": False,
                        "approval_readiness": {
                            "status": "requires_prevalidation",
                            "ready_for_human_approval": False,
                            "reason": "Context menu is not open.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_ready_approvals(
        TaskJournal(tmp_path, "north-star-ready-approvals-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "ready_items_available"
    assert result["may_execute_from_this_result"] is False
    ready_ids = {item["id"] for item in result["ready_items"]}
    withheld_ids = {item["id"] for item in result["withheld_items"]}
    assert {"safe-ribbon-view-tab", "approved-workflow-open-sheet"}.issubset(ready_ids)
    assert "context-menu-project-browser-target" in withheld_ids
    assert "context-menu-select-properties-item" in withheld_ids
    assert result["ready_approval_count"] == len(result["ready_items"])
    assert all(item["approval_token"].startswith("APPROVE:") for item in result["ready_items"])
    assert all(item["execute_powershell"] for item in result["ready_items"])
    ready_ribbon = next(item for item in result["ready_items"] if item["id"] == "safe-ribbon-view-tab")
    assert ready_ribbon["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert ready_ribbon["token_verification_summary"]["token_matches_ready_item"] is True
    assert ready_ribbon["token_verification_summary"]["approval_ready_now"] is True
    assert ready_ribbon["token_verification_summary"]["may_execute_from_this_summary"] is False
    assert ready_ribbon["token_verification_summary"]["bound_payload_digest"]
    assert all("execute_powershell" not in item for item in result["withheld_items"])
    assert all(item["withheld_execute_command"] for item in result["withheld_items"])
    assert "Ask the human to review only ready_items" in result["approval_request_rule"]
    assert "does not approve, focus, click, type, invoke UIA" in result["safety_note"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Revit Operator Ready North-Star Approvals" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "Ready Items" in markdown_text
    assert "Withheld Items" in markdown_text
    assert "Execute only after explicit approval" in markdown_text
    assert "  gap_ids: `live_uia_ribbon_context_execution`" in markdown_text
    assert "  gap_ids: `live_ui_workflow_execution`" in markdown_text
    assert "may_execute_from_this_summary=false" in markdown_text
    assert "Bound payload digest" in markdown_text
    assert "Execute command withheld until latest preflight marks this item ready" in markdown_text
    assert "north-star-approval-verify" in markdown_text


def test_north_star_ready_approvals_withholds_when_preflight_is_stale(tmp_path, monkeypatch):
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
                "approval_preflight_freshness": _test_preflight_freshness(
                    generated_offset_seconds=-1800,
                    ttl_seconds=60,
                ),
                "ready_for_human_approval_count": 1,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_ready_approvals(
        TaskJournal(tmp_path, "north-star-ready-approvals-stale-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["status"] == "no_ready_items"
    assert result["may_execute_from_this_result"] is False
    assert result["ready_approval_count"] == 0
    assert result["withheld_approval_count"] == 5
    assert result["preflight_freshness_guard"]["status"] == "preflight_stale"
    safe = next(item for item in result["withheld_items"] if item["id"] == "safe-ribbon-view-tab")
    assert safe["approval_readiness"]["status"] == "preflight_stale"
    assert "expired" in safe["withheld_reason"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Preflight Freshness Guard" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "preflight_stale" in markdown_text


def test_north_star_next_approval_selects_one_ready_item_without_execution(tmp_path, monkeypatch):
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
                "ready_for_human_approval_count": 2,
                "items": [
                    {
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ribbon tab dry-run passed.",
                        },
                    },
                    {
                        "id": "approved-workflow-open-sheet",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Workflow dry-run passed.",
                        },
                    },
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Project Browser target is not visible.",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")

    result = north_star.build_north_star_next_approval(
        TaskJournal(tmp_path, "north-star-next-approval-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "approval_ready"
    assert result["may_execute_from_this_result"] is False
    selected = result["selected_item"]
    assert selected["id"] == "safe-ribbon-view-tab"
    assert selected["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert selected["approval_token"].startswith("APPROVE:")
    assert selected["verify_powershell"]
    assert selected["dry_run_powershell"]
    assert selected["execute_powershell"]
    assert selected["may_execute_from_this_item"] is False
    assert selected["token_verification_summary"]["may_execute_from_this_summary"] is False
    assert result["deferred_ready_items"]
    assert all("execute_powershell" not in item for item in result["deferred_ready_items"])
    assert "Ask the human to approve only selected_item" in result["approval_request_rule"]
    markdown_text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "Revit Operator Next North-Star Approval" in markdown_text
    assert "Selected Item" in markdown_text
    assert "Deferred Ready Items" in markdown_text
    assert "may_execute_from_this_result: `false`" in markdown_text
    assert "may_execute_from_this_item: `false`" in markdown_text
    assert "  gap_ids: `live_uia_ribbon_context_execution`" in markdown_text
    assert "Execute only after explicit approval" in markdown_text


def test_north_star_approval_plan_uses_latest_matching_prevalidation_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    runs_root = tmp_path / "revit_operator_runs"

    def write_journal(task_id, command, timestamp, result):
        run_dir = runs_root / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "journal.jsonl").write_text(
            json.dumps(
                {
                    "command": command,
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "result": result,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_workflow(task_id, captured_at):
        run_dir = runs_root / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "ui_workflow_run.json").write_text(
            json.dumps(
                {
                    "dry_run": True,
                    "planned_only": True,
                    "captured_at": captured_at,
                    "journal": {"task_id": task_id},
                    "stop_reason": "Missing or incorrect approval token for this recipe step.",
                    "step_results": [
                        {"status": "ran"},
                        {
                            "status": "ran",
                            "command_result": {
                                "route": {
                                    "approval_required": True,
                                    "operation": "activate-view",
                                    "recommended_method": "request-operation activate-view",
                                }
                            },
                        },
                        {"status": "stopped_approval_required"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_journal(
        "live-ribbon-view-tab-plan",
        "plan-ribbon-action",
        "2026-05-13T02:48:01Z",
        {"success": True, "executable": False, "match_count": 0},
    )
    write_journal(
        "live-ribbon-view-tab-plan-refresh",
        "plan-ribbon-action",
        "2026-05-13T03:50:39Z",
        {"success": True, "executable": True, "match_count": 1},
    )
    write_workflow("live-project-browser-open-sheet-plan", "2026-05-13T02:47:19Z")
    write_workflow("live-project-browser-open-sheet-plan-refresh", "2026-05-13T03:50:45.802250Z")
    write_journal(
        "live-context-menu-s20-plan",
        "plan-context-menu-action",
        "2026-05-13T02:48:09Z",
        {"success": True, "executable": True, "match_count": 1},
    )
    write_journal(
        "live-context-menu-s20-plan-refresh",
        "plan-context-menu-action",
        "2026-05-13T03:50:50Z",
        {"success": True, "executable": False, "match_count": 0},
    )

    result = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-plan-refresh-test"),
        default_sheet_number="S2.0",
    )

    assert result["success"] is True
    items = {item["id"]: item for item in result["approval_items"]}

    ribbon_prevalidation = items["safe-ribbon-view-tab"]["prevalidation"]
    assert ribbon_prevalidation["source_task_id"] == "live-ribbon-view-tab-plan-refresh"
    assert ribbon_prevalidation["observed_at"] == "2026-05-13T03:50:39Z"
    assert ribbon_prevalidation["status"] == "prevalidated_one_exact_target"
    assert Path(ribbon_prevalidation["artifact"]).parent.name == "live-ribbon-view-tab-plan-refresh"

    direct_uia_prevalidation = items["direct-uia-view-tab-select"]["prevalidation"]
    assert direct_uia_prevalidation["source_task_id"] == "live-ribbon-view-tab-plan-refresh"

    workflow_prevalidation = items["approved-workflow-open-sheet"]["prevalidation"]
    assert workflow_prevalidation["source_task_id"] == "live-project-browser-open-sheet-plan-refresh"
    assert workflow_prevalidation["captured_at"] == "2026-05-13T03:50:45.802250Z"
    assert workflow_prevalidation["status"] == "prevalidated_stopped_at_approval_gate"
    assert Path(workflow_prevalidation["artifact"]).parent.name == "live-project-browser-open-sheet-plan-refresh"

    context_prevalidation = items["context-menu-project-browser-target"]["prevalidation"]
    assert context_prevalidation["source_task_id"] == "live-context-menu-s20-plan-refresh"
    assert context_prevalidation["observed_at"] == "2026-05-13T03:50:50Z"
    assert context_prevalidation["status"] == "not_currently_executable"
    assert Path(context_prevalidation["artifact"]).parent.name == "live-context-menu-s20-plan-refresh"


def test_north_star_approval_preflight_runs_dry_run_commands_without_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    monkeypatch.setattr(
        north_star,
        "_approval_prevalidation",
        lambda _sandbox, _sheet_number: {
            "safe-ribbon-view-tab": {"status": "prevalidated_one_exact_target", "executable": True},
            "direct-uia-view-tab-select": {
                "status": "target_prevalidated_by_ribbon_plan",
                "executable": True,
            },
            "approved-workflow-open-sheet": {"status": "prevalidated_stopped_at_approval_gate"},
            "context-menu-project-browser-target": {
                "status": "not_currently_executable",
                "executable": False,
            },
            "context-menu-select-properties-item": {"status": "not_prevalidated"},
        },
    )
    seen: list[tuple[str, list[str]]] = []

    def fake_runner(argv, item_id):
        seen.append((item_id, argv))
        assert "--execute" not in argv
        assert "--approval-token" not in argv
        assert "--approval-tokens-json" not in argv
        return {
            "success": True,
            "status": "dry_run",
            "dry_run": True,
            "executable": item_id in {"safe-ribbon-view-tab", "direct-uia-view-tab-select"},
            "match_count": 1 if item_id == "safe-ribbon-view-tab" else 0,
        }

    result = north_star.build_north_star_approval_preflight(
        TaskJournal(tmp_path, "north-star-approval-preflight-test"),
        default_sheet_number="S2.0",
        revit_version="2025",
        expected_title_contains="24522 St John XXIII",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
        run_preflight=fake_runner,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "preflighted"
    assert result["approval_item_count"] == 5
    assert result["preflight_passed_count"] == 5
    assert result["unsafe_preflight_count"] == 0
    assert all(item["approval_token"] is None for item in result["items"])
    assert all(item["approval_token_withheld"] is True for item in result["items"])
    assert all("APPROVE:" not in json.dumps(item) for item in result["items"])
    assert result["ready_for_human_approval_count"] == 3
    assert result["requires_state_change_count"] == 1
    assert result["requires_prevalidation_count"] == 1
    assert result["expected_context"]["revit_version"] == "2025"
    assert result["expected_context"]["expected_title_contains"] == "24522 St John XXIII"
    assert result["expected_context"]["expected_view_name"] == "STARTING VIEW"
    assert result["expected_context"]["expected_view_type"] == "DrawingSheet"
    assert result["approval_preflight_freshness"]["ttl_seconds"] == 900
    assert result["approval_preflight_freshness"]["expires_at_unix"] > result[
        "approval_preflight_freshness"
    ]["generated_at_unix"]
    refresh = result["post_preflight_handoff_refresh"]
    assert refresh["required"] is True
    assert refresh["read_only"] is True
    assert refresh["execution_command_included"] is False
    assert refresh["approval_token_included"] is False
    assert refresh["command"] == [
        "north-star-watch",
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
        "--refresh-approval-preflight",
        "--publish-current-handoff",
        "--checks",
        "1",
        "--poll",
        "0",
    ]
    assert "APPROVE:" not in refresh["powershell"]
    assert len(seen) == 5
    ribbon = next(item for item in result["items"] if item["id"] == "safe-ribbon-view-tab")
    assert ribbon["approval_readiness"]["status"] == "ready_for_human_approval"
    workflow = next(item for item in result["items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow["dry_run_command"] == [
        "run-ui-workflow",
        "--name",
        "project-browser-open-sheet",
        "--sheet-number",
        "S2.0",
    ]
    assert "--approval-tokens-json" not in workflow["dry_run_command"]
    assert workflow["preflight_summary"]["dry_run"] is True
    assert workflow["approval_readiness"]["ready_for_human_approval"] is True
    context_action = next(item for item in result["items"] if item["id"] == "context-menu-project-browser-target")
    assert context_action["approval_readiness"]["status"] == "requires_ui_state_change"
    context_item = next(item for item in result["items"] if item["id"] == "context-menu-select-properties-item")
    assert context_item["approval_readiness"]["status"] == "requires_prevalidation"
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    assert Path(result["stable_files"]["preflight_json"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json"
    assert Path(result["stable_files"]["preflight_markdown"]) == tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md"
    markdown_text = Path(result["stable_files"]["preflight_markdown"]).read_text(encoding="utf-8")
    assert "Revit Operator North-Star Approval Preflight" in markdown_text
    assert "ready_for_human_approval_count: `3`" in markdown_text
    assert "Expected title contains: `24522 St John XXIII`" in markdown_text
    assert "Expected view name: `STARTING VIEW`" in markdown_text
    assert "Approval Preflight Freshness" in markdown_text
    assert "Post-Preflight Handoff Refresh" in markdown_text
    assert "--publish-current-handoff" in markdown_text
    assert "Approval readiness: `requires_ui_state_change`" in markdown_text
    assert "Approval readiness: `requires_prevalidation`" in markdown_text
    assert "Execute only after explicit approval" not in markdown_text
    assert "Execute withheld" in markdown_text
    assert "APPROVE:" not in markdown_text


def test_north_star_approval_preflight_treats_approval_gate_dry_runs_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    monkeypatch.setattr(
        north_star,
        "_approval_prevalidation",
        lambda _sandbox, _sheet_number: {
            "safe-ribbon-view-tab": {"status": "prevalidated_one_exact_target", "executable": True},
            "direct-uia-view-tab-select": {
                "status": "target_prevalidated_by_ribbon_plan",
                "executable": True,
            },
            "approved-workflow-open-sheet": {"status": "prevalidated_stopped_at_approval_gate"},
            "context-menu-project-browser-target": {
                "status": "not_currently_executable",
                "executable": False,
            },
            "context-menu-select-properties-item": {"status": "not_prevalidated"},
        },
    )

    def fake_runner(argv, item_id):
        if item_id == "approved-workflow-open-sheet":
            return {
                "success": False,
                "dry_run": True,
                "planned_only": True,
                "stop_reason": "Missing or incorrect approval token for this recipe step.",
            }
        if item_id == "direct-uia-view-tab-select":
            return {"status": "dry_run", "dry_run": True}
        return {"success": True, "dry_run": True}

    result = north_star.build_north_star_approval_preflight(
        TaskJournal(tmp_path, "north-star-approval-preflight-dry-run-success-test"),
        default_sheet_number="S2.0",
        run_preflight=fake_runner,
    )

    assert result["success"] is True
    assert result["preflight_passed_count"] == result["approval_item_count"]
    assert result["preflight_failed_count"] == 0
    workflow = next(item for item in result["items"] if item["id"] == "approved-workflow-open-sheet")
    assert workflow["status"] == "preflight_passed"
    assert workflow["preflight_success"] is True
    assert workflow["approval_readiness"]["status"] == "ready_for_human_approval"


def test_north_star_approval_verify_matches_current_token_without_execution(tmp_path, monkeypatch):
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
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")
    plan = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-verify-plan-test"),
        default_sheet_number="S2.0",
    )
    token = next(
        item["approval_token"]
        for item in plan["approval_items"]
        if item["id"] == "safe-ribbon-view-tab"
    )

    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-test"),
        default_sheet_number="S2.0",
        approval_token=token,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "matched"
    assert result["token_matches_current_approval_item"] is True
    assert result["execution_by_this_command"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["approval_ready_now"] is True
    assert result["readiness_result"]["status"] == "ready_for_human_approval"
    assert result["matched_items"][0]["id"] == "safe-ribbon-view-tab"
    assert result["matched_items"][0]["approval_ready_now"] is True
    assert result["matched_items"][0]["gap_ids"] == ["live_uia_ribbon_context_execution"]
    assert result["matched_items"][0]["blocked_effects"]
    assert result["matched_items"][0]["post_checks"]
    assert result["matched_items"][0]["approval_freshness"]["bound_payload_digest"]
    assert result["freshness_result"]["token_matches_current_approval_item"] is True
    assert result["freshness_result"]["matched_item_ids"] == ["safe-ribbon-view-tab"]
    assert result["freshness_result"]["approval_ready_now"] is True
    assert "Re-run dry-run preflight" in result["freshness_result"]["freshness_rule"]
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_north_star_approval_verify_reports_not_ready_preflight_match(tmp_path, monkeypatch):
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
                "requires_state_change_count": 1,
                "items": [
                    {
                        "id": "context-menu-project-browser-target",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "requires_ui_state_change",
                            "ready_for_human_approval": False,
                            "reason": "Target is not currently executable.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = north_star.build_north_star_approval_plan(
        TaskJournal(tmp_path, "north-star-approval-verify-not-ready-plan-test"),
        default_sheet_number="S2.0",
    )
    item = next(
        item
        for item in plan["approval_items"]
        if item["id"] == "context-menu-project-browser-target"
    )
    assert item["approval_token"] is None
    assert item["approval_token_withheld"] is True
    assert item["required_human_approval_phrase"] is None
    assert item["execute_powershell"] == ""

    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-not-ready-test"),
        default_sheet_number="S2.0",
        approval_token="APPROVE:not-ready-withheld",
    )

    assert result["status"] == "no_match"
    assert result["token_matches_current_approval_item"] is False
    assert result["approval_ready_now"] is False
    assert result["matched_items"] == []
    assert result["may_execute_from_this_result"] is False


def test_north_star_approval_verify_rejects_unknown_token(tmp_path):
    result = north_star.build_north_star_approval_verify(
        TaskJournal(tmp_path, "north-star-approval-verify-no-match-test"),
        default_sheet_number="S2.0",
        approval_token="APPROVE:not-current",
    )

    assert result["success"] is True
    assert result["status"] == "no_match"
    assert result["token_matches_current_approval_item"] is False
    assert result["match_count"] == 0
    assert result["matched_items"] == []
    assert result["execution_by_this_command"] is False


def test_north_star_approval_phrase_verify_matches_current_waiting_phrase(tmp_path, monkeypatch):
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
                        "id": "safe-ribbon-view-tab",
                        "status": "preflight_passed",
                        "preflight_success": True,
                        "approval_readiness": {
                            "status": "ready_for_human_approval",
                            "ready_for_human_approval": True,
                            "reason": "Ready in phrase verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md").write_text("# preflight", encoding="utf-8")
    waiting = north_star.build_north_star_waiting_state(
        TaskJournal(tmp_path, "north-star-phrase-waiting-state-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        default_sheet_number="S2.0",
        revit_version="2025",
    )
    assert waiting["audit_completion_authorized"] is False
    assert waiting["next_approval_gap_ids"] == [
        "live_uia_ribbon_context_execution"
    ]
    waiting_markdown = Path(waiting["markdown_path"]).read_text(encoding="utf-8")
    assert "audit_completion_authorized: `false`" in waiting_markdown
    assert "- next_approval_gap_ids: `live_uia_ribbon_context_execution`" in waiting_markdown

    result = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-verify-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        phrase_source="human_active_conversation",
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["status"] == "matched"
    assert result["phrase_matches_waiting_state"] is True
    assert result["phrase_source"] == "human_active_conversation"
    assert result["phrase_source_attested"] is True
    assert result["artifact_phrase_is_not_approval_provenance"] is True
    assert result["token_matches_current_approval_item"] is True
    assert result["approval_ready_now"] is True
    assert result["approval_validated_for_current_waiting_state"] is True
    assert result["matched_item_id"] == "safe-ribbon-view-tab"
    assert result["execution_by_this_command"] is False
    assert result["may_execute_from_this_result"] is False
    assert result["approval_verify"]["may_execute_from_this_result"] is False
    assert result["required_human_approval_phrase"].startswith("I approve safe-ribbon-view-tab")
    assert result["supplied_phrase_sha256"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    markdown = Path(result["markdown_path"])
    assert markdown.is_relative_to(tmp_path)
    assert "not execution authority" in markdown.read_text(encoding="utf-8")
    assert "phrase_source_attested: `true`" in markdown.read_text(encoding="utf-8")

    untrusted_source = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-untrusted-source-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase=waiting["required_human_approval_phrase"],
        default_sheet_number="S2.0",
        revit_version="2025",
    )
    assert untrusted_source["status"] == "phrase_source_unverified"
    assert untrusted_source["phrase_matches_waiting_state"] is True
    assert untrusted_source["phrase_source_attested"] is False
    assert untrusted_source["token_matches_current_approval_item"] is True
    assert untrusted_source["approval_validated_for_current_waiting_state"] is False
    assert untrusted_source["may_execute_from_this_result"] is False


def test_north_star_approval_phrase_verify_rejects_wrong_phrase(tmp_path, monkeypatch):
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
                            "reason": "Ready in phrase verification test.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = north_star.build_north_star_approval_phrase_verify(
        TaskJournal(tmp_path, "north-star-approval-phrase-verify-no-match-test"),
        repo_root=Path.cwd(),
        command_names=cli._available_commands(),
        phrase="I approve the wrong item with token APPROVE:not-current",
        default_sheet_number="S2.0",
        revit_version="2025",
    )

    assert result["success"] is True
    assert result["status"] == "no_match"
    assert result["phrase_matches_waiting_state"] is False
    assert result["approval_validated_for_current_waiting_state"] is False
    assert result["may_execute_from_this_result"] is False


def test_cli_north_star_approval_plan_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        north_star,
        "_bridge_readiness_evidence",
        lambda _sandbox: {
            "available": True,
            "ready_for_continuous_bridge": False,
            "requires_revit_restart_or_reload": True,
        },
    )
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-plan-cli-test",
            "north-star-approval-plan",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["default_sheet_number"] == "S2.0"
    assert output["blocker_summary"]["blocked_gap_count"] == 5
    assert output["blocked_gap_count"] == output["blocker_summary"]["blocked_gap_count"]
    assert output["blocked_gate_count"] == output["blocked_gap_count"]
    assert output["blocked_gap_ids"] == sorted(output["blocker_summary"]["blocked_gap_ids"])
    assert output["completion_actions"]["human_or_real_condition_required"] is True
    assert output["human_or_real_condition_required"] is True
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_preflight_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
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
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        assert callable(run_preflight)
        path = journal.run_dir / "north_star_approval_preflight.json"
        path.write_text("{}", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "preflighted",
            "approval_item_count": 1,
            "preflight_passed_count": 1,
            "unsafe_preflight_count": 0,
            "path": str(path),
        }

    monkeypatch.setattr(cli, "build_north_star_approval_preflight", fake_preflight)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-preflight-cli-test",
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
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "preflighted"
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_cli_north_star_ready_approvals_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_ready_approvals(journal, *, default_sheet_number):
        assert default_sheet_number == "S2.0"
        path = journal.run_dir / "north_star_ready_approvals.json"
        markdown = journal.run_dir / "north_star_ready_approvals.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# ready", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "ready_items_available",
            "ready_approval_count": 1,
            "withheld_approval_count": 1,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_ready_approvals", fake_ready_approvals)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-ready-approvals-cli-test",
            "north-star-ready-approvals",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "ready_items_available"
    assert output["ready_approval_count"] == 1
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_next_approval_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_next_approval(journal, *, default_sheet_number):
        assert default_sheet_number == "S2.0"
        path = journal.run_dir / "north_star_next_approval.json"
        markdown = journal.run_dir / "north_star_next_approval.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# next", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "approval_ready",
            "selected_item": {"id": "safe-ribbon-view-tab"},
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_next_approval", fake_next_approval)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-next-approval-cli-test",
            "north-star-next-approval",
            "--sheet-number",
            "S2.0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "approval_ready"
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_waiting_state_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_waiting_state(
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
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        assert repo_root.exists()
        assert "north-star-waiting-state" in command_names
        path = journal.run_dir / "north_star_waiting_state.json"
        markdown = journal.run_dir / "north_star_waiting_state.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# waiting", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "waiting_for_human_or_real_condition",
            "may_execute_from_this_result": False,
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:test"
            ),
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_waiting_state", fake_waiting_state)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-waiting-state-cli-test",
            "north-star-waiting-state",
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
    assert output["status"] == "waiting_for_human_or_real_condition"
    assert output["may_execute_from_this_result"] is False
    assert output["required_human_approval_phrase"] == "<redacted approval material>"
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_phrase_verify_writes_readonly_artifact(tmp_path, capsys, monkeypatch):
    def fake_phrase_verify(
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
        assert "north-star-approval-phrase-verify" in command_names
        assert phrase == "I approve safe-ribbon-view-tab with token APPROVE:test"
        assert phrase_source == "human_active_conversation"
        assert default_sheet_number == "S2.0"
        assert revit_version == "2025"
        assert expected_title_contains == "24522 St John XXIII"
        assert expected_path_contains == ""
        assert expected_view_name == "STARTING VIEW"
        assert expected_view_type == "DrawingSheet"
        path = journal.run_dir / "north_star_approval_phrase_verify.json"
        markdown = journal.run_dir / "north_star_approval_phrase_verify.md"
        path.write_text("{}", encoding="utf-8")
        markdown.write_text("# phrase verify", encoding="utf-8")
        return {
            "success": True,
            "read_only": True,
            "status": "matched",
            "phrase_matches_waiting_state": True,
            "execution_by_this_command": False,
            "may_execute_from_this_result": False,
            "path": str(path),
            "markdown_path": str(markdown),
        }

    monkeypatch.setattr(cli, "build_north_star_approval_phrase_verify", fake_phrase_verify)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-phrase-verify-cli-test",
            "north-star-approval-phrase-verify",
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
    assert output["status"] == "matched"
    assert output["phrase_matches_waiting_state"] is True
    assert output["execution_by_this_command"] is False
    assert output["may_execute_from_this_result"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["markdown_path"]).exists()


def test_cli_north_star_approval_verify_writes_readonly_artifact(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "north-star-approval-verify-cli-test",
            "north-star-approval-verify",
            "--approval-token",
            "APPROVE:not-current",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["status"] == "no_match"
    assert output["execution_by_this_command"] is False
    assert Path(output["path"]).is_relative_to(tmp_path)
