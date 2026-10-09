"""Revit operator commands, results, metadata and approvals aimed at one Revit process."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.tools.revit_operator_helpers import (
    _SESSION_STARTED,
    _current_bridge_addin,
    _live_revit_processes,
    _start_bridge_session,
    _targeted_token,
    _write_bridge_payload,
)
from tools.revit_operator import cli
import tools.revit_operator.agent_session as agent_session
import tools.revit_operator.bridge as bridge_module
import tools.revit_operator.workflows as workflows
from tools.revit_operator.bridge import RevitBridgeClient
from tools.revit_operator.constants import DRAFT_LABEL
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.navigation import find_views
import tools.revit_operator.operations as operations
from tools.revit_operator.qa import generate_qa_report
from tools.revit_operator.safety import classify_action
from tools.revit_operator.ui_workflows import (
    BRIDGE_TARGET_COMMANDS,
    UI_WORKFLOWS,
    plan_ui_workflow,
    run_ui_workflow,
)
from tools.revit_operator.workflow_memory import record_workflow


def test_bridge_status_prefers_target_process_files_over_shared_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bridge_module,
        "_process_start_utc",
        lambda pid: datetime(2026, 10, 2, 12, 0, 0, 123456, tzinfo=timezone.utc),
    )
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    # Another tandem session wrote the shared files last.
    _write_bridge_payload(bridge.addin_status_path, {"status": "started", "addin": _current_bridge_addin(111)})
    _write_bridge_payload(
        bridge.active_document_path,
        {"available": True, "document": {"title": "Other Session"}, "addin": _current_bridge_addin(111)},
    )
    paths = bridge.process_status_paths(222)
    _write_bridge_payload(paths["heartbeat"], {"status": "idling", "addin": _current_bridge_addin(222)})
    _write_bridge_payload(
        paths["active_document"],
        {"available": True, "document": {"title": "Target Session"}, "addin": _current_bridge_addin(222)},
    )

    status = bridge.bridge_status()
    verified = bridge.verify_loaded_build()
    document = bridge.active_document_status()

    assert status["status_source"] == "process"
    assert status["heartbeat_path"] == str(paths["heartbeat"])
    assert status["writer_process_id"] == 222
    assert verified["success"] is True
    assert {check["name"]: check["passed"] for check in verified["checks"]}["status_from_target_process"] is True
    assert document["status_source"] == "process"
    assert document["document"]["document"]["title"] == "Target Session"


def test_bridge_status_without_target_keeps_reading_shared_files(tmp_path):
    bridge = RevitBridgeClient(tmp_path)
    _write_bridge_payload(bridge.addin_status_path, {"status": "started", "addin": _current_bridge_addin(111)})
    _write_bridge_payload(
        bridge.process_status_paths(222)["addin_status"],
        {"status": "started", "addin": _current_bridge_addin(222)},
    )

    status = bridge.bridge_status()
    verified = bridge.verify_loaded_build()

    assert status["status_source"] == "shared"
    assert status["writer_process_id"] == 111
    assert verified["success"] is True
    assert "status_from_target_process" not in {check["name"] for check in verified["checks"]}


def test_verify_bridge_build_rejects_shared_status_for_target_without_process_files(tmp_path):
    bridge = RevitBridgeClient(tmp_path, target_pid=333)
    _write_bridge_payload(bridge.addin_status_path, {"status": "started", "addin": _current_bridge_addin(111)})
    _write_bridge_payload(
        bridge.active_document_path,
        {"available": True, "document": {"title": "Other Session"}, "addin": _current_bridge_addin(111)},
    )

    verified = bridge.verify_loaded_build()
    document = bridge.active_document_status()

    failed = {check["name"]: check for check in verified["checks"] if not check["passed"]}
    assert verified["status"] == "stale_or_unverified"
    assert verified["status_source"] == "shared_fallback"
    assert set(failed) == {"status_from_target_process"}
    assert "older add-in build" in failed["status_from_target_process"]["reason"]
    assert document["available"] is False
    assert document["status"] == "other_process_document"
    assert document["writer_process_id"] == 111


def test_bridge_status_ignores_process_files_left_by_earlier_process_with_same_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bridge_module,
        "_process_start_utc",
        lambda pid: datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc),
    )
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    _write_bridge_payload(
        bridge.process_status_paths(222)["heartbeat"],
        {"status": "idling", "addin": _current_bridge_addin(222, started="2026-09-30T08:00:00.1234567Z")},
    )

    status = bridge.bridge_status()

    assert status["status_source"] == "shared_fallback"
    assert "earlier process" in status["fallback_reason"]
    assert status["heartbeat_path"] == str(bridge.heartbeat_path)


def test_cli_verify_bridge_build_reads_target_window_process_files(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {4242: 222}.get(hwnd))
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge_dir = tmp_path / "bridge"
    _write_bridge_payload(bridge_dir / "addin_status.json", {"status": "started", "addin": {"session_id": "old"}})
    _write_bridge_payload(bridge_dir / "addin_status.222.json", {"status": "started", "addin": _current_bridge_addin(222)})

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "verify-bridge-build-target-test",
            "verify-bridge-build",
            "--hwnd",
            "4242",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "current"
    assert output["status_source"] == "process"
    assert output["target"] == {"hwnd": 4242, "pid": 222}


def _set_parameter_payload() -> dict:
    return {
        "operation": "set-project-info-parameter",
        "args": {"name": "Project Status", "value": "QA Draft"},
        "allow_model_write": True,
        "allow_sync": False,
    }


def _set_parameter_argv(sandbox: Path, task_id: str, *extra: str) -> list[str]:
    return [
        "--sandbox",
        str(sandbox),
        "--allow-sandbox-outside-safe-root",
        "--task-id",
        task_id,
        "request-operation",
        "--operation",
        "set-project-info-parameter",
        "--name",
        "Project Status",
        "--value",
        "QA Draft",
        "--allow-model-write",
        *extra,
    ]


def test_request_operation_targets_one_process_and_binds_the_approval_to_it(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222, 333)
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {4242: 222}.get(hwnd))
    _start_bridge_session(tmp_path, 222, title="Target Model")
    _start_bridge_session(tmp_path, 333, title="Other Agent Model")
    payload = _set_parameter_payload()
    token = _targeted_token(payload, 222)
    queue_path = tmp_path / "bridge" / "command_queue.jsonl"

    assert cli.main(_set_parameter_argv(tmp_path, "target-dry-run", "--hwnd", "4242")) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["success"] is True
    assert dry_run["target"] == {"process_id": 222, "process_start_utc": _SESSION_STARTED}
    assert dry_run["target_session"]["document"]["title"] == "Target Model"
    assert dry_run["policy"]["approval_token"] == token
    assert "--hwnd 4242" in dry_run["next_step"]
    # An approval for this operation without a target, or for another Revit, does not cover this target.
    assert token != classify_action("request-operation", payload).approval_token
    assert token != _targeted_token(payload, 333)

    stale_token = classify_action("request-operation", payload).approval_token
    assert cli.main(_set_parameter_argv(tmp_path, "target-stale", "--pid", "222", "--execute", "--approval-token", stale_token)) == 2
    assert "approval token" in json.loads(capsys.readouterr().out)["error"]
    assert not queue_path.exists()

    assert cli.main(_set_parameter_argv(tmp_path, "target-execute", "--pid", "222", "--execute", "--approval-token", token)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["queued"] is True
    command = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[-1])
    assert command["target"] == {"process_id": 222, "process_start_utc": _SESSION_STARTED}
    journal_entry = json.loads(
        (tmp_path / "revit_operator_runs" / "target-execute" / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert journal_entry["target"] == command["target"]
    # Recorded workflows replay requested_action, which never names a process that has since exited.
    assert "target" not in journal_entry["requested_action"]


@pytest.mark.parametrize("operation", sorted(operations.TARGET_REQUIRED_OPERATIONS))
def test_request_operation_refuses_untargeted_model_and_document_changes(tmp_path, monkeypatch, operation):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path / "sandbox", 222, title="Target Model")
    model = tmp_path / "copy-R25.rvt"
    model.write_text("not a real model", encoding="utf-8")
    args = {
        "open-model": {"path": str(model), "allow_model_outside_safe_root": True},
        "set-project-info-parameter": {"name": "Project Status", "value": "QA Draft"},
    }.get(operation, {})
    payload = {"operation": operation, "args": args, "allow_model_write": True, "allow_sync": True}
    journal = TaskJournal(tmp_path / "sandbox", f"untargeted-{operation}")

    # Every other guard is satisfied, so only the missing target stops the line.
    result = operations.queue_operation(
        journal,
        operations.OperationRequest(
            operation=operation,
            args=args,
            dry_run=False,
            approval_token=classify_action("request-operation", payload).approval_token,
            allow_model_write=True,
            allow_sync=True,
        ),
    )

    assert result["success"] is False
    assert "pass --hwnd or --pid" in result["error"]
    assert "pid 222 (Target Model)" in result["error"]
    assert [session["process_id"] for session in result["live_sessions"]] == [222]
    assert not (tmp_path / "sandbox" / "bridge" / "command_queue.jsonl").exists()


def test_request_operation_still_queues_untargeted_read_only_and_view_requests(tmp_path):
    journal = TaskJournal(tmp_path, "untargeted-compatible")
    view_payload = {
        "operation": "activate-view",
        "args": {"sheet_number": "S2.0"},
        "allow_model_write": False,
        "allow_sync": False,
    }

    active = operations.queue_operation(
        journal,
        operations.OperationRequest(operation="active-document", args={}, dry_run=False),
    )
    view = operations.queue_operation(
        journal,
        operations.OperationRequest(
            operation="activate-view",
            args={"sheet_number": "S2.0"},
            dry_run=False,
            approval_token=classify_action("request-operation", view_payload).approval_token,
        ),
    )

    assert active["queued"] is True and view["queued"] is True
    assert active["target"] is None
    lines = (tmp_path / "bridge" / "command_queue.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["operation"] for line in lines] == ["active-document", "activate-view"]
    assert all("target" not in json.loads(line) for line in lines)


def test_request_operation_refuses_targets_it_cannot_honor(tmp_path, monkeypatch):
    _live_revit_processes(monkeypatch, 222, 555, 666)
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {4242: 222}.get(hwnd))
    _start_bridge_session(tmp_path, 222)
    _start_bridge_session(tmp_path, 444)
    _start_bridge_session(tmp_path, 666, status="stopped")
    journal = TaskJournal(tmp_path, "unusable-targets")

    def queue(**target):
        return operations.queue_operation(
            journal,
            operations.OperationRequest(operation="active-document", args={}, dry_run=False, **target),
        )

    assert "is not running" in queue(target_pid=444)["error"]
    assert "wrote no per-process status files" in queue(target_pid=555)["error"]
    assert "has stopped" in queue(target_pid=666)["error"]
    assert "does not exist" in queue(target_hwnd=9999)["error"]
    assert "belongs to process 222, not process 555" in queue(target_hwnd=4242, target_pid=555)["error"]
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_request_operation_refuses_target_whose_process_id_was_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc))
    bridge_dir = tmp_path / "bridge"
    addin = _current_bridge_addin(222, started="2026-09-30T08:00:00.1234567Z")
    _write_bridge_payload(bridge_dir / "addin_status.222.json", {"status": "started", "addin": addin})

    result = operations.queue_operation(
        TaskJournal(tmp_path, "reused-pid"),
        operations.OperationRequest(operation="active-document", args={}, dry_run=False, target_pid=222),
    )

    assert result["success"] is False
    assert "earlier process" in result["error"]
    assert not (bridge_dir / "command_queue.jsonl").exists()


def test_request_operation_refuses_targeted_change_while_a_session_ignores_targets(tmp_path, monkeypatch):
    _live_revit_processes(monkeypatch, 222, 333)
    _start_bridge_session(tmp_path, 222)
    # 333 runs the build before command targets, which runs every queued line; 444 runs it too but has exited.
    _start_bridge_session(tmp_path, 333, honors_targets=False)
    _start_bridge_session(tmp_path, 444, honors_targets=False)
    journal = TaskJournal(tmp_path, "ignoring-session")
    payload = _set_parameter_payload()

    change = operations.queue_operation(
        journal,
        operations.OperationRequest(
            operation="set-project-info-parameter",
            args=payload["args"],
            dry_run=False,
            approval_token=_targeted_token(payload, 222),
            allow_model_write=True,
            target_pid=222,
        ),
    )
    export = operations.queue_operation(
        journal,
        operations.OperationRequest(operation="export-metadata", args={}, dry_run=False, target_pid=222),
    )

    assert change["success"] is False
    assert "Revit process 333 runs an add-in build that ignores command targets" in change["error"]
    assert change["sessions_ignoring_target"] == [333]
    assert export["queued"] is True
    assert export["sessions_ignoring_target"] == [333]
    assert "333" in export["target_warning"]
    lines = (tmp_path / "bridge" / "command_queue.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["operation"] for line in lines] == ["export-metadata"]


def _queue_bridge_lines(sandbox: Path, *lines: dict) -> None:
    queue = sandbox / "bridge" / "command_queue.jsonl"
    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")


def _write_bridge_results(sandbox: Path, *results: dict) -> None:
    path = sandbox / "bridge" / "command_results.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(result) + "\n" for result in results), encoding="utf-8")


def test_wait_bridge_result_accepts_only_the_target_processes_answer(tmp_path):
    target = {"process_id": 222, "process_start_utc": _SESSION_STARTED}
    _queue_bridge_lines(
        tmp_path,
        {"id": "cmd-targeted", "operation": "active-document", "target": target},
        {"id": "cmd-untargeted", "operation": "active-document"},
        {"id": "cmd-older-build", "operation": "active-document", "target": target},
    )
    _write_bridge_results(
        tmp_path,
        {"id": "cmd-targeted", "success": True, "message": "from target", "process_id": 222},
        # A session on a build that ignores targets answered later.
        {"id": "cmd-targeted", "success": False, "error": "No active Revit document.", "process_id": 333},
        {"id": "cmd-untargeted", "success": True, "message": "first", "process_id": 222},
        {"id": "cmd-untargeted", "success": True, "message": "last", "process_id": 333},
        # Builds before command targets report their process only in the addin block.
        {"id": "cmd-older-build", "success": True, "message": "addin block", "addin": {"process_id": 222}},
    )
    bridge = RevitBridgeClient(tmp_path)

    targeted = bridge.wait_for_command_result("cmd-targeted", timeout=0)
    untargeted = bridge.wait_for_command_result("cmd-untargeted", timeout=0)
    one_answer = RevitBridgeClient(tmp_path, target_pid=222).wait_for_command_result("cmd-untargeted", timeout=0)
    older_build = bridge.wait_for_command_result("cmd-older-build", timeout=0)
    conflict = RevitBridgeClient(tmp_path, target_pid=333).wait_for_command_result("cmd-targeted", timeout=0)

    assert targeted["success"] is True
    assert targeted["result"]["message"] == "from target"
    assert targeted["target_process_id"] == 222
    assert [other["process_id"] for other in targeted["other_process_results"]] == [333]
    assert "ignores command targets" in targeted["warning"]
    assert untargeted["result"]["message"] == "last"
    assert untargeted["reporting_process_ids"] == [222, 333]
    # Every session runs an untargeted line, so another session's answer to it is expected.
    assert one_answer["result"]["message"] == "first"
    assert [other["process_id"] for other in one_answer["other_process_results"]] == [333]
    assert "warning" not in one_answer
    assert older_build["result"]["message"] == "addin block"
    assert conflict["found"] is False
    assert "targets Revit process 222, not process 333" in conflict["error"]


def test_cli_wait_bridge_result_matches_queued_target_and_pid(tmp_path, capsys):
    target = {"process_id": 222, "process_start_utc": _SESSION_STARTED}
    _queue_bridge_lines(tmp_path, {"id": "cmd-1", "operation": "active-document", "target": target})
    _write_bridge_results(
        tmp_path,
        {"id": "cmd-1", "success": True, "message": "from target", "process_id": 222},
        {"id": "cmd-1", "success": False, "error": "from other session", "process_id": 333},
    )
    argv = ["--sandbox", str(tmp_path), "--allow-sandbox-outside-safe-root", "--task-id", "wait-target-test"]

    assert cli.main([*argv, "wait-bridge-result", "--command-id", "cmd-1", "--timeout", "0"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["message"] == "from target"
    assert output["target_process_id"] == 222

    assert cli.main([*argv, "wait-bridge-result", "--command-id", "cmd-1", "--pid", "222", "--timeout", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["message"] == "from target"


def test_revit_addin_command_targets_follow_the_operator_contract():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "revit_operator"
        / "addin"
        / "HermesRevitOperatorApp.cs"
    ).read_text(encoding="utf-8")
    required = re.search(r"TargetRequiredOperations = new\(StringComparer\.Ordinal\)\s*\{(.*?)\}", source, re.DOTALL)
    tolerance = re.search(r"ProcessStartToleranceSeconds = ([0-9.]+);", source)

    # The add-in refuses untargeted lines for exactly the operations request-operation will not queue untargeted.
    assert set(re.findall(r'"([^"]+)"', required.group(1))) == operations.TARGET_REQUIRED_OPERATIONS
    assert float(tolerance.group(1)) == bridge_module.PROCESS_START_TOLERANCE_SECONDS
    assert '["supports_command_targets"] = true' in source
    assert 'payload["process_id"] = ProcessId;' in source
    # The loaded-build contract that verify_loaded_build checks is unchanged.
    assert f'OperatorProtocolVersion = "{bridge_module.EXPECTED_BRIDGE_PROTOCOL_VERSION}"' in source
    assert f'SourceCapabilityStamp = "{bridge_module.EXPECTED_SOURCE_CAPABILITY_STAMP}"' in source


def _metadata_snapshot(title: str, *, addin: dict | None = None, sheets: list[dict] | None = None) -> dict:
    snapshot = {
        "label": DRAFT_LABEL,
        "read_only": True,
        "document": {"title": title, "path": f"C:/safe/{title}.rvt", "revit_version": "2025"},
        "levels": [{"name": "Level 1"}],
        "grids": [],
        "views": [],
        "sheets": sheets or [],
        "titleblocks": [],
        "links": [],
        "warnings": [],
        "families": [],
        "types": [],
    }
    if addin is not None:
        snapshot["addin"] = addin
    return snapshot


def test_export_metadata_copies_target_process_snapshot_not_later_shared_export(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    _write_bridge_payload(
        bridge.process_metadata_snapshot_path(222),
        _metadata_snapshot("Target Model", addin=_current_bridge_addin(222)),
    )
    # A tandem session's export replaced the shared snapshot before the copy.
    _write_bridge_payload(
        bridge.metadata_snapshot_path,
        _metadata_snapshot("Other Model", addin=_current_bridge_addin(111)),
    )

    result = bridge.export_metadata(tmp_path / "copies" / "target.json")
    untargeted = RevitBridgeClient(tmp_path).export_metadata(tmp_path / "copies" / "shared.json")

    assert result["success"] is True
    assert result["mode"] == "bridge_snapshot_copy"
    assert result["snapshot_source"] == "process"
    assert result["source"] == str(bridge.process_metadata_snapshot_path(222))
    assert result["target"] == {"hwnd": None, "pid": 222}
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))["document"]["title"] == "Target Model"
    # Without a target, the shared snapshot is read as before.
    assert untargeted["snapshot_source"] == "shared"
    assert json.loads(Path(untargeted["path"]).read_text(encoding="utf-8"))["document"]["title"] == "Other Model"


def test_export_metadata_falls_back_to_shared_snapshot_that_names_no_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    # Builds older than per-process snapshots write only the shared snapshot, without naming the writer.
    _write_bridge_payload(bridge.metadata_snapshot_path, _metadata_snapshot("Older Build Model"))

    result = bridge.export_metadata(tmp_path / "metadata.json")

    assert result["success"] is True
    assert result["mode"] == "bridge_snapshot_copy"
    assert result["snapshot_source"] == "shared_fallback"
    assert result["source"] == str(bridge.metadata_snapshot_path)
    assert "wrote no per-process metadata snapshot" in result["fallback_reason"]
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))["document"]["title"] == "Older Build Model"


@pytest.mark.parametrize("bom", [False, True])
def test_metadata_readers_accept_bom_without_changing_document_identity(tmp_path, monkeypatch, bom):
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    source = bridge.process_metadata_snapshot_path(222)
    source.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_metadata_snapshot("Target Model", addin=_current_bridge_addin(222))).encode("utf-8")
    source.write_bytes((b"\xef\xbb\xbf" if bom else b"") + payload)
    journal = TaskJournal(tmp_path, "bom-metadata")

    exported = bridge.export_metadata(tmp_path / "copies" / "metadata.json")
    report = generate_qa_report(journal, bridge=bridge)

    assert exported["success"] is True
    assert exported["source"] == str(source)
    assert "Target Model" in Path(report["path"]).read_text(encoding="utf-8-sig")
    assert report["metadata_source"] == str(source)


def test_metadata_readers_refuse_shared_snapshot_another_process_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    _write_bridge_payload(
        bridge.metadata_snapshot_path,
        _metadata_snapshot(
            "Other Model",
            addin=_current_bridge_addin(111),
            sheets=[{"id": 101, "sheet_number": "S101", "name": "Other Plan", "is_placeholder": False}],
        ),
    )
    journal = TaskJournal(tmp_path, "metadata-other-process-test")
    output = journal.default_metadata_path("json")

    exported = bridge.export_metadata(output)
    views = find_views(journal, bridge, sheet_number="S101")
    report = generate_qa_report(journal, bridge=bridge)

    assert exported["success"] is False
    assert exported["status"] == "other_process_snapshot"
    assert exported["writer_process_id"] == 111
    assert "written by process 111" in exported["error"]
    assert not output.exists()
    assert views["success"] is False
    assert views["error"] == exported["error"]
    assert report["metadata_source"] is None
    assert report["snapshot_source"] == "shared_fallback"
    assert report["writer_process_id"] == 111
    assert "Other Model" not in Path(report["path"]).read_text(encoding="utf-8")


def test_metadata_snapshot_ignores_process_snapshot_left_by_earlier_process_with_same_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bridge_module,
        "_process_start_utc",
        lambda pid: datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc),
    )
    bridge = RevitBridgeClient(tmp_path, target_pid=222)
    _write_bridge_payload(
        bridge.process_metadata_snapshot_path(222),
        _metadata_snapshot("Exited Session", addin=_current_bridge_addin(222, started="2026-09-30T08:00:00.1234567Z")),
    )

    selection = bridge.metadata_snapshot_selection()

    assert selection["source"] == "shared_fallback"
    assert selection["path"] == bridge.metadata_snapshot_path
    assert "earlier process" in selection["fallback_reason"]


@pytest.mark.parametrize("command", ["export-metadata", "find-view", "qa-report"])
def test_cli_metadata_readers_read_target_window_snapshot(tmp_path, capsys, monkeypatch, command):
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {4242: 222}.get(hwnd))
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge_dir = tmp_path / "bridge"
    _write_bridge_payload(
        bridge_dir / "metadata_snapshot.json",
        _metadata_snapshot("Other Model", addin=_current_bridge_addin(111)),
    )
    _write_bridge_payload(
        bridge_dir / "metadata_snapshot.222.json",
        _metadata_snapshot(
            "Target Model",
            addin=_current_bridge_addin(222),
            sheets=[{"id": 202, "sheet_number": "S101", "name": "Target Plan", "is_placeholder": False}],
        ),
    )
    query = ["--sheet-number", "S101"] if command == "find-view" else []

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            f"{command}-target-window-test",
            command,
            *query,
            "--hwnd",
            "4242",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["snapshot_source"] == "process"
    assert output["target"] == {"hwnd": 4242, "pid": 222}
    assert Path(output.get("metadata_source") or output["source"]).name == "metadata_snapshot.222.json"


def test_cli_qa_workflow_runs_against_target_window(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bridge_module, "process_id_for_hwnd", lambda hwnd: {4242: 222}.get(hwnd))
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda pid: None)
    bridge_dir = tmp_path / "bridge"
    _write_bridge_payload(
        bridge_dir / "metadata_snapshot.222.json",
        _metadata_snapshot("Target Model", addin=_current_bridge_addin(222)),
    )
    _write_bridge_payload(
        bridge_dir / "metadata_snapshot.json",
        _metadata_snapshot("Other Model", addin=_current_bridge_addin(111)),
    )
    # Another session's results land after the target's; the waits still take the target's.
    (bridge_dir / "command_results.jsonl").write_text(
        "".join(
            json.dumps({"id": command_id, "success": True, "process_id": pid}) + "\n"
            for pid in (222, 111)
            for command_id in ("active-id", "metadata-id")
        ),
        encoding="utf-8",
    )
    command_ids = iter(["active-id", "metadata-id"])
    queued = []
    captured = []

    def fake_queue_operation(_journal, request):
        queued.append(request)
        return {"success": True, "command": {"id": next(command_ids), "operation": request.operation}}

    class FakeObserver:
        def status(self):
            return {"state": "idle", "active_dialogs": []}

        def ui_tree(self, hwnd=None, max_depth=4):
            captured.append(("ui_tree", hwnd))
            return {"supported": True, "tree": {"title": "Revit"}}

        def screenshot(self, output, hwnd=None):
            captured.append(("screenshot", hwnd))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"BM")
            return {"success": True, "path": str(output), "format": "bmp"}

    monkeypatch.setattr(workflows, "queue_operation", fake_queue_operation)
    monkeypatch.setattr(cli, "RevitWindowObserver", lambda: FakeObserver())

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "qa-workflow-target-window-test",
            "qa-workflow",
            "--hwnd",
            "4242",
            "--timeout",
            "0",
        ]
    )

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert [(request.operation, request.target_hwnd, request.target_pid) for request in queued] == [
        ("active-document", 4242, 222),
        ("export-metadata", 4242, 222),
    ]
    waits = [step["wait_result"] for step in output["steps"] if step["step"].startswith("bridge-")]
    assert [wait["result"]["process_id"] for wait in waits] == [222, 222]
    assert captured == [("ui_tree", 4242), ("screenshot", 4242)]
    assert json.loads(Path(output["metadata_path"]).read_text(encoding="utf-8"))["document"]["title"] == "Target Model"
    assert "- Title: Target Model" in Path(output["qa_report_path"]).read_text(encoding="utf-8")


_TARGET_222 = {"process_id": 222, "process_start_utc": _SESSION_STARTED}
_ACTIVATE_SHEET_PAYLOAD = {
    "operation": "activate-view",
    "args": {"sheet_number": "S2.0"},
    "allow_model_write": False,
    "allow_sync": False,
}


class _IdleRevit:
    def status(self):
        return {
            "state": "idle",
            "active_dialogs": [],
            "main_window": {"hwnd": 1, "title": "Autodesk Revit 2025"},
            "revit_running": True,
        }

    def list_dialogs(self):
        return {"supported": True, "dialogs": []}


def _restart_bridge_session(monkeypatch, sandbox: Path, pid: int) -> None:
    """Replace a Revit process with a later one that reuses its id; every other process has exited."""
    restarted_at = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bridge_module, "_process_start_utc", lambda live: restarted_at if live == pid else None)
    _start_bridge_session(sandbox, pid, started="2026-10-02T13:00:00.0000000Z")


def _queued_lines(sandbox: Path) -> list[dict]:
    queue = sandbox / "bridge" / "command_queue.jsonl"
    return [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines()] if queue.exists() else []


def _answer_bridge_waits(monkeypatch) -> list[tuple]:
    """Answer every bridge wait at once, recording the command and the Revit process whose results it reads."""
    waits = []

    def wait(self, command_id, *, timeout=60.0, poll=1.0):
        waits.append((command_id, self.target_pid))
        return {"success": True, "found": True, "checks": 1, "result": {"id": command_id, "success": True}}

    monkeypatch.setattr(RevitBridgeClient, "wait_for_command_result", wait)
    return waits


def _open_sheet_runner(sandbox: Path):
    """Run the recipe's request-operation step through the CLI, as run-ui-workflow does, and answer the others."""
    run_command = cli._ui_workflow_command_runner(
        sandbox,
        parent_task_id="open-sheet",
        allow_sandbox_outside_safe_root=True,
    )
    return lambda argv, index: run_command(argv, index) if argv[0] == "request-operation" else {"success": True}


def _execute_session_item_argv(sandbox: Path, task_id: str, material: str, item_id: str, *extra: str) -> list[str]:
    return [
        "--sandbox",
        str(sandbox),
        "--allow-sandbox-outside-safe-root",
        "--task-id",
        task_id,
        "agent-session-execute-approved-item",
        "--approval-material",
        material,
        "--item-id",
        item_id,
        "--execute",
        "--confirmation",
        f"I approve {item_id}",
        "--bridge-refresh-timeout",
        "0",
        *extra,
    ]


def test_agent_session_approval_plan_binds_model_change_tokens_to_the_target(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222, title="Target Model")
    objective = "Reload links and update project info parameters."
    parameters = {"parameter_name": "Project Status", "parameter_value": "QA Draft"}
    argv = ["--sandbox", str(tmp_path), "--allow-sandbox-outside-safe-root", "--task-id"]
    plan_argv = ["agent-session-approval-plan", "--objective", objective, "--parameters-json", json.dumps(parameters)]

    untargeted = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "session-approval-untargeted"),
        objective=objective,
        parameters=parameters,
    )
    # request-operation refuses these untargeted, so the packet lists the live sessions instead of unusable tokens.
    blocked = {item["id"]: item for item in untargeted["blocked_items"]}
    for item_id in ("model-change:reload-links", "model-change:set-project-info-parameter"):
        assert blocked[item_id]["target_required"] is True
        assert "pass --hwnd or --pid" in blocked[item_id]["reason"]
        assert "pid 222 (Target Model)" in blocked[item_id]["reason"]
    untargeted_material = json.loads(Path(untargeted["private_material_path"]).read_text(encoding="utf-8"))
    assert not [item for item in untargeted_material["approval_items"] if item["kind"] == "model-change-operation"]

    assert cli.main([*argv, "session-approval-targeted", *plan_argv, "--pid", "222"]) == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert "APPROVE:" not in stdout
    assert output["target"] == _TARGET_222
    assert output["target_session"]["document"]["title"] == "Target Model"
    material = json.loads(Path(output["private_material_path"]).read_text(encoding="utf-8"))
    items = {item["id"]: item for item in material["approval_items"]}
    for operation, args in (
        ("reload-links", {}),
        ("set-project-info-parameter", {"name": "Project Status", "value": "QA Draft"}),
    ):
        item = items[f"model-change:{operation}"]
        payload = {"operation": operation, "args": args, "allow_model_write": True, "allow_sync": False}
        # The token is the one request-operation expects in this Revit process, and the command names the process.
        assert item["revit_target"] == _TARGET_222
        assert item["approval_token"] == _targeted_token(payload, 222)
        assert item["execute_command"].endswith("--pid 222")
    # A UI step's token does not cover a Revit process, so it carries none.
    assert items["ui:manage-links-inspection:step:2"]["revit_target"] is None

    assert cli.main([*argv, "session-approval-exited", *plan_argv, "--pid", "444"]) == 2
    assert "Process 444 is not running" in json.loads(capsys.readouterr().out)["error"]


def test_agent_session_executes_an_approved_change_in_the_revit_it_was_approved_for(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222, 333)
    _start_bridge_session(tmp_path, 222, title="Target Model")
    _start_bridge_session(tmp_path, 333, title="Other Agent Model")
    monkeypatch.setattr(cli, "RevitWindowObserver", _IdleRevit)
    waits = _answer_bridge_waits(monkeypatch)
    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "session-approval-source"),
        objective="Reload links if approved.",
        target_pid=222,
    )

    # Without --hwnd/--pid, the item runs in the Revit process it was approved for.
    code = cli.main(
        _execute_session_item_argv(
            tmp_path, "session-execute", approval["private_material_path"], "model-change:reload-links"
        )
    )

    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert code == 0
    assert "APPROVE:" not in stdout
    assert output["status"] == "executed"
    receipt = output["execution"]["receipt"]
    assert receipt["approved_target"] == receipt["queued_target"] == _TARGET_222
    # The preflight refresh, the change and the post-action refresh all go to the approved process.
    assert [(line["operation"], line.get("target")) for line in _queued_lines(tmp_path)] == [
        ("active-document", _TARGET_222),
        ("reload-links", _TARGET_222),
        ("active-document", _TARGET_222),
    ]
    # Every wait read the approved process's results only.
    assert {pid for _command_id, pid in waits} == {222}


@pytest.mark.parametrize("change", ["other process", "same pid restarted"])
def test_agent_session_refuses_an_approved_change_once_its_revit_changed(tmp_path, capsys, monkeypatch, change):
    _live_revit_processes(monkeypatch, 222, 333)
    _start_bridge_session(tmp_path, 222)
    _start_bridge_session(tmp_path, 333, title="Other Agent Model")
    monkeypatch.setattr(cli, "RevitWindowObserver", _IdleRevit)
    _answer_bridge_waits(monkeypatch)
    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "session-approval-source"),
        objective="Reload links if approved.",
        target_pid=222,
    )
    if change == "other process":
        extra = ["--pid", "333"]
    else:
        _restart_bridge_session(monkeypatch, tmp_path, 222)
        extra = []

    cli.main(
        _execute_session_item_argv(
            tmp_path, "session-execute-changed", approval["private_material_path"], "model-change:reload-links", *extra
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "stopped_refused"
    assert output["execution"]["executed"] is False
    assert "approval token" in output["execution"]["dry_run_result"]["error"]
    assert "approved for Revit process 222" in output["reason"]
    assert [line["operation"] for line in _queued_lines(tmp_path)] == ["active-document"]


def test_workflow_replay_queues_recorded_changes_for_the_planned_revit(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222, 333)
    _start_bridge_session(tmp_path, 222)
    _start_bridge_session(tmp_path, 333, title="Other Agent Model")
    monkeypatch.setattr(cli, "RevitWindowObserver", _IdleRevit)
    payload = _set_parameter_payload()
    recorded_token = _targeted_token(payload, 333)
    # Record the workflow from a run that changed the model in Revit process 333.
    recorded_argv = _set_parameter_argv(
        tmp_path, "recorded-change", "--pid", "333", "--execute", "--approval-token", recorded_token
    )
    assert cli.main(recorded_argv) == 0
    capsys.readouterr()
    assert record_workflow(tmp_path, source_task_id="recorded-change", name="Set Status")["success"] is True
    argv = ["--sandbox", str(tmp_path), "--allow-sandbox-outside-safe-root", "--task-id"]

    # Untargeted, the change cannot be approved at all: request-operation would refuse to queue it.
    assert cli.main([*argv, "plan-untargeted", "workflow-approval-plan", "--name", "Set Status"]) == 0
    untargeted = json.loads(capsys.readouterr().out)
    assert untargeted["approval_tokens_json"] == {}
    assert untargeted["blocked_steps"][0]["target_required"] is True
    assert "pass --hwnd or --pid" in untargeted["blocked_steps"][0]["reason"]
    assert untargeted["replay_execute_command_requires_human"] is None

    assert cli.main([*argv, "plan-targeted", "workflow-approval-plan", "--name", "Set Status", "--pid", "222"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["target"] == _TARGET_222
    assert plan["approval_tokens_json"] == {"0": _targeted_token(payload, 222)}
    assert "--pid 222 --execute" in plan["replay_execute_command_requires_human"]

    def replay(task_id: str, pid: str) -> dict:
        tokens = json.dumps(plan["approval_tokens_json"])
        cli.main(
            [
                *argv,
                task_id,
                "replay-workflow",
                "--name",
                "Set Status",
                "--execute",
                "--approval-tokens-json",
                tokens,
                "--no-recovery-snapshot",
                "--pid",
                pid,
            ]
        )
        return json.loads(capsys.readouterr().out)

    # The tokens cover process 222, so replaying them in the process the workflow was recorded in is refused.
    refused = replay("replay-other-process", "333")
    assert refused["success"] is False
    assert "approval token" in refused["stop_reason"]
    replayed = replay("replay-planned-process", "222")
    assert replayed["success"] is True
    assert replayed["executed_steps"] == [0]
    assert [line["target"]["process_id"] for line in _queued_lines(tmp_path)] == [333, 222]


def test_run_ui_workflow_queues_the_open_sheet_step_for_the_planned_revit(tmp_path, capsys, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    plan_argv = [
        "--sandbox",
        str(tmp_path),
        "--allow-sandbox-outside-safe-root",
        "--task-id",
        "open-sheet-plan",
        "plan-ui-workflow",
        "--name",
        "project-browser-open-sheet",
        "--sheet-number",
        "S2.0",
        "--pid",
        "222",
    ]

    assert cli.main(plan_argv) == 0
    steps = json.loads(capsys.readouterr().out)["steps"]
    token = steps[3]["policy"]["approval_token"]
    # The step's token is the one request-operation checks in this Revit process, and the step names the process.
    assert token == _targeted_token(_ACTIVATE_SHEET_PAYLOAD, 222)
    # status and wait-model-ready check that process too; the project browser plan reads no bridge status.
    assert [step["command"] for step in steps if step["args"][-2:] == ["--pid", "222"]] == [
        "status",
        "wait-model-ready",
        "request-operation",
    ]

    def run(task_id: str) -> dict:
        return run_ui_workflow(
            TaskJournal(tmp_path, task_id),
            name="project-browser-open-sheet",
            parameters={"sheet_number": "S2.0"},
            dry_run=False,
            approval_tokens={3: token},
            observe_func=lambda: {"state": "idle", "active_dialogs": []},
            command_runner=_open_sheet_runner(tmp_path),
            target_pid=222,
        )

    executed = run("open-sheet-run")
    assert executed["success"] is True
    assert executed["approved_executed_steps"] == [3]
    assert _queued_lines(tmp_path)[-1]["target"] == _TARGET_222

    # After a restart the id names a later process, which the approved token does not cover.
    _restart_bridge_session(monkeypatch, tmp_path, 222)
    refused = run("open-sheet-after-restart")
    assert refused["success"] is False
    assert refused["skipped_steps"] == [3]
    assert "approval token" in refused["stop_reason"].lower()
    assert len(_queued_lines(tmp_path)) == 1


def test_run_ui_workflow_open_sheet_token_is_the_one_request_operation_checks(tmp_path):
    plan = plan_ui_workflow(
        TaskJournal(tmp_path, "open-sheet-untargeted-plan"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
    )
    token = plan["steps"][3]["policy"]["approval_token"]

    result = run_ui_workflow(
        TaskJournal(tmp_path, "open-sheet-untargeted-run"),
        name="project-browser-open-sheet",
        parameters={"sheet_number": "S2.0"},
        dry_run=False,
        approval_tokens={3: token},
        observe_func=lambda: {"state": "idle", "active_dialogs": []},
        command_runner=_open_sheet_runner(tmp_path),
    )

    assert token == classify_action("request-operation", _ACTIVATE_SHEET_PAYLOAD).approval_token
    assert result["success"] is True
    # activate-view does not require a target, so the untargeted step still queues for every session.
    assert [line["operation"] for line in _queued_lines(tmp_path)] == ["activate-view"]
    assert "target" not in _queued_lines(tmp_path)[0]


def test_targeted_recipes_pass_the_target_to_every_step_that_takes_one():
    parser = cli.build_parser()
    commands = next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))
    parameters = {
        "sheet_number": "S2.0",
        "view_name": "STARTING VIEW",
        "target_name": "Project Browser",
        "target_control_type": "Pane",
        "workflow_name": "Live Readonly QA Workflow",
    }

    for recipe in UI_WORKFLOWS.values():
        for step in recipe.steps:
            # A recipe command that takes the bridge --pid gets the target, and no other command does.
            takes_target = "--pid" in commands[step.command]._option_string_actions
            assert takes_target == (step.command in BRIDGE_TARGET_COMMANDS), (recipe.name, step.command)
            rendered = step.render(parameters, _TARGET_222)
            if takes_target:
                assert parser.parse_args([step.command, *rendered["args"]]).pid == 222, (recipe.name, step.command)
            else:
                assert "--pid" not in rendered["args"], (recipe.name, step.command)


def test_agent_session_open_sheet_item_runs_in_the_revit_it_was_approved_for(tmp_path, monkeypatch):
    _live_revit_processes(monkeypatch, 222)
    _start_bridge_session(tmp_path, 222)
    approval = agent_session.build_agent_session_approval_plan(
        TaskJournal(tmp_path, "open-sheet-approval"),
        objective="Open sheet S2.0 from the project browser.",
        parameters={"sheet_number": "S2.0"},
        target_pid=222,
    )
    material = json.loads(Path(approval["private_material_path"]).read_text(encoding="utf-8"))
    item = next(item for item in material["approval_items"] if item["id"] == "ui:project-browser-open-sheet:step:3")
    assert item["revit_target"] == _TARGET_222
    assert item["approval_token"] == _targeted_token(_ACTIVATE_SHEET_PAYLOAD, 222)
    assert item["execute_command"].endswith("--pid 222")

    result = agent_session.execute_agent_session_approved_item(
        TaskJournal(tmp_path, "open-sheet-execute"),
        _IdleRevit(),
        RevitBridgeClient(tmp_path),
        approval_material_path=Path(approval["private_material_path"]),
        item_id=item["id"],
        execute=True,
        confirmation=f"I approve {item['id']}",
        bridge_refresh_timeout=0,
        ui_command_runner=_open_sheet_runner(tmp_path),
    )

    assert result["status"] == "executed"
    assert _queued_lines(tmp_path)[-1]["operation"] == "activate-view"
    assert _queued_lines(tmp_path)[-1]["target"] == _TARGET_222
