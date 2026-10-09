"""Revit operator operations: request-operation guards, command queue, lookups, readiness waits."""

import json
from pathlib import Path

from tests.tools.revit_operator_helpers import (
    _SESSION_STARTED,
    _live_revit_processes,
    _start_bridge_session,
    _targeted_token,
)
from tools.revit_operator import cli
from tools.revit_operator.constants import DRAFT_LABEL
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.navigation import find_view_matches
import tools.revit_operator.operations as operations
from tools.revit_operator.readiness import wait_model_ready
import tools.revit_operator.revit_locator as revit_locator
from tools.revit_operator.safety import (
    APPROVAL_REQUIRED,
    BLOCK,
    classify_action,
)


def test_list_safe_project_models_marks_current_model_and_skips_sandbox(tmp_path):
    project = tmp_path / "copied-project"
    sandbox = project / "_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT"
    current = project / "Drawings" / "Working Drawings" / "Structural_Current Working-R25-BIM.rvt"
    other = project / "Drawings" / "Archive" / "Old-R22.rvt"
    sandbox_model = sandbox / "scratch-R25.rvt"
    current.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    sandbox_model.parent.mkdir(parents=True)
    current.write_bytes(b"current model placeholder")
    other.write_bytes(b"old model placeholder")
    sandbox_model.write_bytes(b"sandbox placeholder")

    result = revit_locator.list_safe_project_models(
        project,
        current_model=current,
    )

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["project_root"] == str(project)
    assert result["current_test_model"]["listed"] is True
    assert result["model_count"] == 2
    paths = {item["path"] for item in result["models"]}
    assert str(current) in paths
    assert str(other) in paths
    assert str(sandbox_model) not in paths
    current_item = next(item for item in result["models"] if item["is_current_test_model"])
    assert current_item["inferred_revit_version"] == "2025"
    assert current_item["example_role"] == "current_structural_r25_test_model"
    assert current_item["safe_dry_run_argv"] == [
        "agent-model-open-choreography",
        "--model",
        str(current),
        "--revit-version",
        "2025",
    ]
    assert "--execute" not in current_item["safe_dry_run_command"]
    assert "approval-token" not in current_item["safe_dry_run_command"]


def test_cli_exposes_list_safe_models(tmp_path, capsys, monkeypatch):
    project = tmp_path / "copied-project"
    current = project / "Drawings" / "Working Drawings" / "sample-R25.rvt"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"sample")

    def fake_list_safe_project_models(**kwargs):
        return revit_locator.list_safe_project_models(
            project,
            current_model=current,
            **kwargs,
        )

    monkeypatch.setattr(cli, "list_safe_project_models", fake_list_safe_project_models)
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-model-list-cli-test",
            "list-safe-models",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["model_count"] == 1
    assert output["models"][0]["path"] == str(current)
    assert output["models"][0]["inferred_revit_version"] == "2025"


def test_cli_export_metadata_writes_stub_inside_sandbox(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "metadata-test",
            "export-metadata",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    metadata_path = Path(output["path"])
    assert metadata_path.is_relative_to(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["label"] == DRAFT_LABEL
    assert metadata["read_only"] is True


def test_find_view_matches_supports_sheet_and_view_queries():
    metadata = {
        "sheets": [
            {
                "id": 101,
                "sheet_number": "S101",
                "name": "Framing Plan",
                "is_placeholder": False,
            }
        ],
        "views": [
            {
                "id": 202,
                "name": "Level 1 Framing",
                "view_type": "FloorPlan",
            }
        ],
    }

    sheet_matches = find_view_matches(metadata, sheet_number="S101")
    view_matches = find_view_matches(metadata, query="framing", view_type="FloorPlan")

    assert sheet_matches == [
        {
            "kind": "sheet",
            "id": 101,
            "name": "Framing Plan",
            "view_type": "DrawingSheet",
            "sheet_number": "S101",
            "is_placeholder": False,
        }
    ]
    view_match = next(match for match in view_matches if match["kind"] == "view")
    assert view_match["id"] == 202


def test_cli_find_view_uses_bridge_metadata_and_writes_activation_hint(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "id": 101,
                        "sheet_number": "S101",
                        "name": "Framing Plan",
                        "is_placeholder": False,
                    }
                ],
                "views": [],
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
            "find-view-test",
            "find-view",
            "--sheet-number",
            "S101",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["count"] == 1
    assert output["activation"]["available"] is True
    assert output["activation"]["operation"] == "activate-view"
    assert output["activation"]["args"] == {"id": 101, "sheet_number": "S101"}
    assert Path(output["path"]).is_relative_to(tmp_path)


def test_open_model_dry_run_uses_explicit_revit_exe_and_requires_approval(tmp_path, capsys):
    model = tmp_path / "sample-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    revit = tmp_path / "Revit.exe"
    revit.write_text("not a real executable", encoding="utf-8")

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "open-test",
            "open-model",
            "--model",
            str(model),
            "--revit-exe",
            str(revit),
            "--allow-model-outside-safe-root",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["operation_plan"]["launch"] == [str(revit), str(model)]
    assert output["operation_plan"]["expected_prompts"] == []


def test_request_operation_save_requires_write_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "save-test",
            "request-operation",
            "--operation",
            "save",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert "--allow-model-write" in output["error"]
    assert output["policy"]["risk"] == "critical"


def test_run_safe_command_dry_run_wraps_readonly_bridge_operation(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-dry-run-test",
            "run-safe-command",
            "--name",
            "active-document",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["safe_command"]["delegates_to"] == "request-operation"
    assert output["safe_command"]["delegated_operation"] == "active-document"
    assert output["wrapper_policy"]["decision"] == "allow"
    assert output["policy"]["decision"] == "allow"
    assert output["command"]["operation"] == "active-document"
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_run_safe_command_execute_queues_only_readonly_wrapper(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-queue-test",
            "run-safe-command",
            "--name",
            "qa-snapshot",
            "--args-json",
            '{"sheet_number":"S2.0"}',
            "--execute",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["queued"] is True
    assert output["wrapper_policy"]["decision"] == "allow"
    assert output["command"]["guards"]["allow_model_write"] is False
    assert output["command"]["guards"]["allow_sync"] is False
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "qa-snapshot"
    assert command["args"]["sheet_number"] == "S2.0"
    assert command["guards"]["allow_model_write"] is False
    assert command["guards"]["allow_sync"] is False


def test_run_safe_command_blocks_unsupported_operations(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "safe-command-block-test",
            "run-safe-command",
            "--name",
            "save",
            "--execute",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "read-only command wrappers" in output["error"]
    assert output["wrapper_policy"]["decision"] == BLOCK
    assert output["safe_command"]["delegates_to"] is None
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_request_operation_sync_requires_sync_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "sync-test",
            "request-operation",
            "--operation",
            "sync",
            "--allow-model-write",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert "--allow-sync" in output["error"]


def test_request_operation_activate_view_dry_run_requires_approval_without_write_guard(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "activate-view-dry-run-test",
            "request-operation",
            "--operation",
            "activate-view",
            "--sheet-number",
            "S101",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["policy"]["risk"] == "critical"
    assert output["policy"]["decision"] == APPROVAL_REQUIRED
    assert output["command"]["args"]["sheet_number"] == "S101"
    assert output["command"]["guards"]["allow_model_write"] is False
    assert "--allow-model-write" not in output["next_step"]


def test_request_operation_activate_view_execute_writes_bridge_queue_with_exact_token(tmp_path, capsys):
    payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S101"},
        "allow_model_write": False,
        "allow_sync": False,
    }
    decision = classify_action("request-operation", payload)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "activate-view-queue-test",
            "request-operation",
            "--operation",
            "activate-view",
            "--sheet-number",
            "S101",
            "--execute",
            "--approval-token",
            decision.approval_token,
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "activate-view"
    assert command["args"]["sheet_number"] == "S101"
    assert command["guards"]["allow_model_write"] is False


def test_queue_operation_activate_view_id_arg_is_not_the_command_id(tmp_path):
    args = {"id": 123}
    payload = {"operation": "activate-view", "args": args, "allow_model_write": False, "allow_sync": False}
    token = classify_action("request-operation", payload).approval_token
    journal = TaskJournal(tmp_path, "activate-view-command-id-test")

    results = [
        operations.queue_operation(
            journal,
            operations.OperationRequest(operation="activate-view", args=args, dry_run=False, approval_token=token),
        )
        for _ in range(2)
    ]

    assert [result["success"] for result in results] == [True, True]
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    queued = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    command_ids = [command["id"] for command in queued]
    assert command_ids == [result["command"]["id"] for result in results]
    # The add-in keys a non-string id by queue line and skips an id it has already processed.
    assert all(isinstance(command_id, str) for command_id in command_ids)
    assert command_ids[0] != command_ids[1]
    assert [command["args"] for command in queued] == [{"id": 123}, {"id": 123}]


def test_queue_operation_uses_explicit_command_id_field(tmp_path):
    args = {"id": 123}
    payload = {"operation": "activate-view", "args": args, "allow_model_write": False, "allow_sync": False}
    token = classify_action("request-operation", payload).approval_token

    result = operations.queue_operation(
        TaskJournal(tmp_path, "explicit-command-id-test"),
        operations.OperationRequest(
            operation="activate-view",
            args=args,
            dry_run=False,
            approval_token=token,
            command_id="open-view-123",
        ),
    )

    assert result["success"] is True
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["id"] == result["command"]["id"] == "open-view-123"
    assert command["args"] == {"id": 123}


def test_request_operation_execute_writes_bridge_queue_with_exact_token(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    payload = {
        "operation": "set-project-info-parameter",
        "args": {"name": "Project Status", "value": "QA Draft"},
        "allow_model_write": True,
        "allow_sync": False,
    }

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "queue-test",
            "request-operation",
            "--operation",
            "set-project-info-parameter",
            "--name",
            "Project Status",
            "--value",
            "QA Draft",
            "--allow-model-write",
            "--pid",
            "222",
            "--execute",
            "--approval-token",
            _targeted_token(payload, 222),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "set-project-info-parameter"
    assert command["args"]["name"] == "Project Status"
    assert command["guards"]["allow_model_write"] is True
    assert command["target"] == {"process_id": 222, "process_start_utc": _SESSION_STARTED}


def test_bridge_queue_append_retries_transient_permission_error(tmp_path, monkeypatch):
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"
    queue_path.parent.mkdir()
    original_open = Path.open
    calls = {"count": 0}

    def flaky_open(self, *args, **kwargs):
        if self == queue_path and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError("bridge queue is temporarily locked")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    result = operations._append_command_jsonl(
        queue_path,
        {"id": "retry-test", "operation": "active-document"},
        attempts=2,
        base_delay=0,
    )

    assert result["success"] is True
    assert result["attempts"] == 2
    assert json.loads(queue_path.read_text(encoding="utf-8"))["id"] == "retry-test"


def test_request_operation_open_model_validates_and_queues_model_path(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path / "sandbox", 222)
    model = tmp_path / "bridge-open-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    args = {
        "path": str(model),
        "detach": True,
        "allow_model_outside_safe_root": True,
    }
    payload = {
        "operation": "open-model",
        "args": args,
        "allow_model_write": False,
        "allow_sync": False,
    }

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "bridge-open-test",
            "request-operation",
            "--operation",
            "open-model",
            "--args-json",
            json.dumps(args),
            "--pid",
            "222",
            "--execute",
            "--approval-token",
            _targeted_token(payload, 222),
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    queue_path = tmp_path / "sandbox" / "bridge" / "command_queue.jsonl"
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["operation"] == "open-model"
    assert command["args"]["detach"] is True
    assert command["target"]["process_id"] == 222


def test_qa_report_uses_bridge_metadata_and_labels_draft(tmp_path, capsys):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "metadata_snapshot.json").write_text(
        json.dumps(
            {
                "document": {"title": "Test", "path": "model.rvt", "revit_version": "2025"},
                "levels": [{"name": "Level 1"}],
                "grids": [],
                "views": [],
                "sheets": [],
                "titleblocks": [],
                "links": [],
                "warnings": [{"description": "warning"}],
                "families": [],
                "types": [],
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
            "qa-test",
            "qa-report",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    report = Path(output["path"])
    text = report.read_text(encoding="utf-8")
    assert DRAFT_LABEL in text
    assert "Revit warnings require review" in text


def test_cli_wait_for_window_times_out_cleanly(tmp_path, capsys):
    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "wait-test",
            "wait-for-window",
            "--title-contains",
            "__definitely_not_a_revit_window__",
            "--timeout",
            "0",
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "Timed out" in output["error"]


def test_wait_model_ready_matches_idle_bridge_document(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "revit_running": True,
                "active_dialogs": [],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def active_document_status(self):
            return {
                "available": True,
                "document": {
                    "document": {
                        "title": "24522 Test Model",
                        "path": "C:/safe/model.rvt",
                        "revit_version": "2025",
                        "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                    }
                },
            }

    result = wait_model_ready(
        TaskJournal(tmp_path, "model-ready-test"),
        FakeObserver(),
        FakeBridge(),
        timeout=0,
        expected_title_contains="24522",
        expected_revit_version="2025",
        expected_view_name="STARTING VIEW",
        expected_view_type="DrawingSheet",
    )

    assert result["success"] is True
    assert result["ready"] is True
    assert result["stop_reason"] == "model_ready"
    assert result["final_evaluation"]["document"]["title"] == "24522 Test Model"
    assert Path(result["path"]).is_relative_to(tmp_path)


def test_wait_model_ready_stops_on_modal(tmp_path):
    class FakeObserver:
        def status(self):
            return {
                "state": "modal",
                "revit_running": True,
                "active_dialogs": [{"title": "Unresolved References"}],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def active_document_status(self):
            return {"available": False, "status": "stub"}

    result = wait_model_ready(
        TaskJournal(tmp_path, "model-ready-modal-test"),
        FakeObserver(),
        FakeBridge(),
        timeout=10,
        poll=0.1,
    )

    assert result["success"] is False
    assert result["ready"] is False
    assert result["stop_reason"] == "modal_state_detected"
    assert result["final_check"]["active_dialog_count"] == 1


def test_cli_wait_model_ready_writes_status(tmp_path, capsys, monkeypatch):
    class FakeObserver:
        def status(self):
            return {
                "state": "idle",
                "revit_running": True,
                "active_dialogs": [],
                "main_window": {"title": "Autodesk Revit 2025"},
            }

    class FakeBridge:
        def __init__(self, _sandbox):
            pass

        def active_document_status(self):
            return {
                "available": True,
                "document": {
                    "document": {
                        "title": "24522 Test Model",
                        "path": "C:/safe/model.rvt",
                        "revit_version": "2025",
                        "active_view": {"name": "STARTING VIEW", "type": "DrawingSheet"},
                    }
                },
            }

    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())
    monkeypatch.setattr(cli, "RevitBridgeClient", FakeBridge)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "model-ready-cli-test",
            "wait-model-ready",
            "--timeout",
            "0",
            "--expected-revit-version",
            "2025",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is True
    assert output["stop_reason"] == "model_ready"
    assert Path(output["path"]).is_relative_to(tmp_path)
