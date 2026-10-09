"""Revit operator transports: CLI output redaction, sandbox guards, HTTP control server, MCP."""

import asyncio
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.revit_operator import cli, mcp_server
from tools.revit_operator.journal import TaskJournal
from tools.revit_operator.server import (
    ALLOW_EXTERNAL_SANDBOX_ENV as HTTP_ALLOW_EXTERNAL_SANDBOX_ENV,
    list_control_commands,
    make_control_server,
    run_control_command,
)
from tools.revit_operator.safety import (
    BLOCK,
    validate_output_path,
    validate_sandbox_root,
)
from tools.revit_operator.transport_safety import (
    PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV,
    build_transport_safety_matrix,
)


@pytest.mark.parametrize(
    "command",
    [
        "north-star-approval-plan",
        "north-star-approval-preflight",
        "north-star-ready-approvals",
        "north-star-next-approval",
        "north-star-waiting-state",
        "north-star-approval-phrase-verify",
        "north-star-approved-execution-preview",
        "north-star-approval-verify",
        "north-star-watch",
        "north-star-resume-check",
        "north-star-human-gate-packet",
        "north-star-next-human-action",
        "north-star-current-handoff",
        "north-star-completion-gate",
        "north-star-unblock-readiness",
    ],
)
def test_cli_approval_sensitive_stdout_redacts_approval_material(command):
    class Args:
        pass

    args = Args()
    args.command = command

    result = {
        "success": True,
        "waiting_state_summary": {
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:secret"
            ),
            "next_approval_token": "APPROVE:secret",
        },
        "next_approval_summary": {
            "verify_command": ["north-star-approval-verify", "--approval-token", "APPROVE:secret"],
            "approval_token_present": True,
        },
    }

    redacted = cli._stdout_result(args, result)
    redacted_text = json.dumps(redacted)
    original_text = json.dumps(result)

    assert "APPROVE:secret" in original_text
    assert "I approve" in original_text
    assert "APPROVE:secret" not in redacted_text
    assert "I approve" not in redacted_text
    assert redacted["next_approval_summary"]["approval_token_present"] is True


@pytest.mark.parametrize("command", ["run-ui-workflow", "replay-workflow"])
def test_cli_help_does_not_emit_token_shaped_approval_examples(command, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--approval-tokens-json" in help_text
    assert "<approval-token>" in help_text
    assert "APPROVE:" not in help_text


def test_cli_exception_output_redacts_approval_material(monkeypatch, capsys):
    def fail_dispatch(_args):
        raise ValueError(
            "Bad phrase I approve safe-ribbon-view-tab with token APPROVE:secret"
        )

    monkeypatch.setattr(cli, "dispatch", fail_dispatch)

    code = cli.main(["health"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "APPROVE:secret" not in captured.err
    assert "I approve" not in captured.err
    assert "<redacted approval phrase>" in captured.err
    assert "<redacted approval token>" in captured.err


def test_sandbox_validation_defaults_to_known_safe_project(tmp_path):
    error = validate_sandbox_root(tmp_path, allow_outside_safe_root=False)
    assert error is not None

    assert validate_sandbox_root(tmp_path, allow_outside_safe_root=True) is None
    assert validate_output_path(tmp_path / "ok.json", tmp_path) is None
    assert validate_output_path(tmp_path.parent / "escape.json", tmp_path) is not None


def test_control_server_health_and_command(tmp_path, monkeypatch):
    monkeypatch.setenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    server = make_control_server(
        "127.0.0.1",
        0,
        sandbox=tmp_path,
        allow_sandbox_outside_safe_root=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["success"] is True
        assert health["service"] == "revit-operator"
        assert "/commands" in health["endpoints"]

        with urllib.request.urlopen(base + "/commands", timeout=5) as response:
            commands = json.loads(response.read().decode("utf-8"))
        assert commands["success"] is True
        assert commands["service"] == "revit-operator"
        assert commands["transport"] == "local-http"
        assert "run-safe-command" in commands["commands"]
        assert "north-star-completion-gate" in commands["commands"]
        assert "serve" in commands["blocked_commands"]

        body = json.dumps(
            {
                "command": "known-dialogs",
                "task_id": "server-known-dialogs-test",
                "args": [],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["success"] is True
        assert result["count"] >= 5
        assert Path(result["journal"]["journal"]).is_relative_to(tmp_path)

        body = json.dumps(
            {
                "command": "run-safe-command",
                "task_id": "server-safe-command-test",
                "args": ["--name", "active-document"],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            safe_result = json.loads(response.read().decode("utf-8"))
        assert safe_result["success"] is True
        assert safe_result["dry_run"] is True
        assert safe_result["safe_command"]["delegates_to"] == "request-operation"
        assert safe_result["wrapper_policy"]["decision"] == "allow"
        assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()

        body = json.dumps(
            {
                "command": "run-safe-command",
                "task_id": "server-safe-command-block-test",
                "args": ["--name", "save", "--execute"],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)
        blocked_result = json.loads(exc_info.value.read().decode("utf-8"))
        assert blocked_result["success"] is False
        assert blocked_result["wrapper_policy"]["decision"] == BLOCK
        assert blocked_result["safe_command"]["delegates_to"] is None
        assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_transport_safety_matrix_is_read_only_and_clean(tmp_path, monkeypatch):
    monkeypatch.delenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)

    result = build_transport_safety_matrix(
        TaskJournal(tmp_path, "transport-safety-matrix-test"),
        repo_root=Path.cwd(),
    )
    result_text = json.dumps(result)

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["live_revit_touched"] is False
    assert result["status"] == "clean"
    assert result["failed_count"] == 0
    assert result["direct_approval_marker_count"] == 0
    assert result["redaction_marker_count"] > 0
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert Path(result["markdown_path"]).is_relative_to(tmp_path)
    assert Path(result["stable_path"]) == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    assert Path(result["stable_path"]).exists()
    assert (
        Path(result["stable_markdown_path"])
        == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md"
    )
    assert Path(result["stable_markdown_path"]).exists()
    stable_markdown = Path(result["stable_markdown_path"]).read_text(encoding="utf-8")
    assert "- completion_allowed: `false`" in stable_markdown
    assert "- may_call_update_goal: `false`" in stable_markdown
    assert "- audit_completion_authorized: `false`" in stable_markdown
    assert "- may_execute_from_this_result: `false`" in stable_markdown
    assert "APPROVE:" not in result_text
    assert "i approve" not in result_text.lower()
    check_ids = {check["id"] for check in result["checks"]}
    assert {
        "cli-stdout-redaction",
        "http-control-redaction",
        "mcp-json-redaction",
        "plugin-redaction",
        "http-blocks-external-sandbox-override",
        "mcp-blocks-external-sandbox-override",
        "plugin-blocks-external-sandbox-override",
        "http-blocks-model-root-override",
        "mcp-blocks-model-root-override",
        "plugin-blocks-model-root-override",
    }.issubset(check_ids)


def test_cli_transport_safety_matrix_writes_readonly_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)
    monkeypatch.delenv(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV, raising=False)

    code = cli.main(
        [
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "--task-id",
            "transport-safety-matrix-cli-test",
            "transport-safety-matrix",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    output_text = json.dumps(output)

    assert code == 0
    assert output["success"] is True
    assert output["read_only"] is True
    assert output["live_revit_touched"] is False
    assert output["status"] == "clean"
    assert output["direct_approval_marker_count"] == 0
    assert Path(output["path"]).is_relative_to(tmp_path)
    assert Path(output["stable_path"]) == tmp_path / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    assert Path(output["stable_markdown_path"]).exists()
    assert "APPROVE:" not in output_text
    assert "i approve" not in output_text.lower()


def test_control_command_redacts_approval_material_in_results(monkeypatch):
    def fake_dispatch(_args):
        return {
            "success": True,
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:server-secret"
            ),
            "approval_token": "APPROVE:server-secret",
        }

    monkeypatch.setattr(cli, "dispatch", fake_dispatch)

    result = run_control_command({"command": "health"})
    result_text = json.dumps(result)

    assert result["success"] is True
    assert "APPROVE:server-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval material>" in result_text


def test_control_command_redacts_approval_material_in_parse_errors(capsys):
    result = run_control_command(
        {
            "argv": [
                "north-star-approval-verify",
                "--approval-token",
                "APPROVE:server-secret",
                "--bad-flag",
            ]
        }
    )
    capsys.readouterr()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:server-secret" not in result_text
    assert "<redacted approval token>" in result_text


def test_control_commands_list_redacts_approval_material_in_errors(monkeypatch):
    def fail_available_commands():
        raise ValueError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:server-secret"
        )

    monkeypatch.setattr(cli, "_available_commands", fail_available_commands)

    result = list_control_commands()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:server-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval token>" in result_text
    assert "<redacted approval phrase>" in result_text


def test_cli_approval_stdout_redacts_phrase_case_insensitively():
    result = cli._redact_approval_stdout(
        "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:case-secret"
    )

    assert "APPROVE:case-secret" not in result
    assert "i approve" not in result.lower()
    assert "<redacted approval token>" in result
    assert "<redacted approval phrase>" in result


def test_mcp_command_redacts_approval_material_in_results(monkeypatch):
    def fake_control_command(*_args, **_kwargs):
        return {
            "success": True,
            "required_human_approval_phrase": (
                "i approve safe-ribbon-view-tab with token APPROVE:mcp-secret"
            ),
            "approval_token": "APPROVE:mcp-secret",
        }

    monkeypatch.setattr(mcp_server, "run_control_command", fake_control_command)

    result = mcp_server.run_mcp_command(command="health")
    result_text = json.dumps(result)

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval material>" in result_text


def test_mcp_command_redacts_approval_material_in_exceptions(monkeypatch):
    def fail_control_command(*_args, **_kwargs):
        raise ValueError(
            "Bad phrase I approve safe-ribbon-view-tab with token APPROVE:mcp-secret"
        )

    monkeypatch.setattr(mcp_server, "run_control_command", fail_control_command)

    result = mcp_server.run_mcp_command(command="health")
    result_text = json.dumps(result)

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval token>" in result_text


def test_mcp_list_commands_redacts_approval_material_in_errors(monkeypatch):
    def fail_build_parser():
        raise ValueError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:mcp-list-secret"
        )

    monkeypatch.setattr(cli, "build_parser", fail_build_parser)

    result = mcp_server.list_mcp_commands()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "APPROVE:mcp-list-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval token>" in result_text
    assert "<redacted approval phrase>" in result_text


def test_mcp_json_result_redacts_approval_material():
    result_text = mcp_server._json_result(
        {
            "success": True,
            "required_human_approval_phrase": (
                "i approve safe-ribbon-view-tab with token APPROVE:mcp-json-secret"
            ),
            "approval_token": "APPROVE:mcp-json-secret",
        }
    )

    assert "APPROVE:mcp-json-secret" not in result_text
    assert "i approve" not in result_text.lower()
    assert "<redacted approval material>" in result_text


def test_mcp_main_redacts_approval_material_in_import_errors(monkeypatch, capsys):
    def fail_run_mcp_server(*, verbose):
        raise ImportError(
            "Bad phrase i approve safe-ribbon-view-tab with token APPROVE:mcp-main-secret"
        )

    monkeypatch.setattr(mcp_server, "run_mcp_server", fail_run_mcp_server)

    code = mcp_server.main([])
    captured = capsys.readouterr()

    assert code == 2
    assert "APPROVE:mcp-main-secret" not in captured.out
    assert "i approve" not in captured.out.lower()
    assert "<redacted approval token>" in captured.out
    assert "<redacted approval phrase>" in captured.out


def test_control_server_blocks_external_sandbox_escape_without_test_env(tmp_path):
    result = run_control_command(
        {
            "command": "known-dialogs",
            "allow_sandbox_outside_safe_root": True,
        },
        default_sandbox=tmp_path,
    )

    assert result["success"] is False
    assert "allow_sandbox_outside_safe_root" in result["error"]
    assert HTTP_ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_control_server_blocks_argv_external_sandbox_escape_without_test_env(tmp_path):
    result = run_control_command(
        {
            "argv": [
                "--sandbox",
                str(tmp_path),
                "--allow-sandbox-outside-safe-root",
                "known-dialogs",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-sandbox-outside-safe-root" in result["error"]
    assert HTTP_ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_control_server_blocks_model_outside_safe_root_flag(tmp_path):
    result = run_control_command(
        {
            "command": "open-model",
            "args": [
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_argv_model_outside_safe_root_flag(tmp_path):
    result = run_control_command(
        {
            "argv": [
                "open-model",
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_nested_model_outside_safe_root_override(tmp_path):
    result = run_control_command(
        {
            "command": "request-operation",
            "args": [
                "--operation",
                "open-model",
                "--args-json",
                json.dumps(
                    {
                        "path": str(tmp_path / "outside.rvt"),
                        "allow_model_outside_safe_root": True,
                    }
                ),
            ],
        },
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_control_server_blocks_recursive_serve(tmp_path, monkeypatch):
    monkeypatch.setenv(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = run_control_command(
        {"command": "serve"},
        default_sandbox=tmp_path,
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert "cannot be called" in result["error"]


def test_mcp_wrapper_runs_known_dialogs(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="known-dialogs",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-known-dialogs-test",
    )

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert result["count"] >= 5
    assert Path(result["journal"]["journal"]).is_relative_to(tmp_path)


def test_mcp_wrapper_blocks_external_sandbox_escape_without_test_env(tmp_path):
    result = mcp_server.run_mcp_command(
        command="known-dialogs",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-known-dialogs-blocked-test",
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "allow_sandbox_outside_safe_root" in result["error"]
    assert mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_mcp_wrapper_blocks_argv_external_sandbox_escape_without_test_env(tmp_path):
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "known-dialogs",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-sandbox-outside-safe-root" in result["error"]
    assert mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_mcp_wrapper_blocks_model_outside_safe_root_flag(tmp_path):
    result = mcp_server.run_mcp_command(
        command="open-model",
        args=[
            "--model",
            str(tmp_path / "outside.rvt"),
            "--allow-model-outside-safe-root",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_argv_model_outside_safe_root_flag(tmp_path):
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "open-model",
            "--model",
            str(tmp_path / "outside.rvt"),
            "--allow-model-outside-safe-root",
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_nested_model_outside_safe_root_override(tmp_path):
    result = mcp_server.run_mcp_command(
        command="request-operation",
        args=[
            "--operation",
            "open-model",
            "--args-json",
            json.dumps(
                {
                    "path": str(tmp_path / "outside.rvt"),
                    "allow_model_outside_safe_root": True,
                }
            ),
        ],
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "--allow-model-outside-safe-root" in result["error"]


def test_mcp_wrapper_blocks_server_commands(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="serve",
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "blocked" in result["error"].lower()


def test_mcp_wrapper_blocks_server_commands_in_argv(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="ignored",
        argv=[
            "--sandbox",
            str(tmp_path),
            "--allow-sandbox-outside-safe-root",
            "serve",
        ],
        allow_sandbox_outside_safe_root=True,
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert "blocked" in result["error"].lower()


def test_mcp_wrapper_runs_safe_command_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="run-safe-command",
        args=["--name", "active-document"],
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-safe-command-test",
    )

    assert result["success"] is True
    assert result["called_via"] == "mcp"
    assert result["dry_run"] is True
    assert result["safe_command"]["delegates_to"] == "request-operation"
    assert result["wrapper_policy"]["decision"] == "allow"
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_mcp_wrapper_blocks_unsafe_safe_command(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    result = mcp_server.run_mcp_command(
        command="run-safe-command",
        args=["--name", "save", "--execute"],
        sandbox=str(tmp_path),
        allow_sandbox_outside_safe_root=True,
        task_id="mcp-safe-command-block-test",
    )

    assert result["success"] is False
    assert result["called_via"] == "mcp"
    assert result["wrapper_policy"]["decision"] == BLOCK
    assert result["safe_command"]["delegates_to"] is None
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


class _FakeMcpToolManager:
    def __init__(self):
        self.tools = {}

    def add_tool(self, fn):
        self.tools[fn.__name__] = fn


class _FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self._tool_manager = _FakeMcpToolManager()

    def tool(self):
        def decorator(fn):
            self._tool_manager.add_tool(fn)
            return fn

        return decorator


def test_mcp_server_registers_thin_wrapper_tools(monkeypatch, tmp_path):
    monkeypatch.setenv(mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV, "1")
    monkeypatch.setattr(mcp_server, "_MCP_SERVER_AVAILABLE", True)
    monkeypatch.setattr(mcp_server, "FastMCP", _FakeFastMCP)

    server = mcp_server.create_mcp_server()

    assert {"revit_operator_health", "revit_operator_commands", "revit_operator_command"}.issubset(
        server._tool_manager.tools
    )
    assert (
        "allow_sandbox_outside_safe_root"
        not in server._tool_manager.tools["revit_operator_command"].__code__.co_varnames
    )
    raw = server._tool_manager.tools["revit_operator_command"](
        command="known-dialogs",
        sandbox=str(tmp_path),
        task_id="mcp-server-tool-test",
    )
    result = json.loads(raw)
    assert result["success"] is True
    assert result["called_via"] == "mcp"


def test_mcp_stdio_server_serves_read_only_command(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run_smoke():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tools.revit_operator.mcp_server"],
            cwd=str(Path.cwd()),
            env={
                **os.environ,
                "PYTHONPATH": str(Path.cwd()),
                mcp_server.ALLOW_EXTERNAL_SANDBOX_ENV: "1",
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                listed = await asyncio.wait_for(session.list_tools(), timeout=15)
                result = await asyncio.wait_for(
                    session.call_tool(
                        "revit_operator_command",
                        arguments={
                            "command": "known-dialogs",
                            "sandbox": str(tmp_path),
                            "task_id": "mcp-stdio-known-dialogs-test",
                        },
                    ),
                    timeout=30,
                )
        return listed, result

    listed, result = asyncio.run(run_smoke())
    tool_names = {tool.name for tool in listed.tools}
    payload = json.loads(result.content[0].text)

    assert {"revit_operator_health", "revit_operator_commands", "revit_operator_command"}.issubset(
        tool_names
    )
    assert payload["success"] is True
    assert payload["called_via"] == "mcp"
    assert Path(payload["journal"]["journal"]).is_relative_to(tmp_path)


def test_cli_refuses_sandbox_outside_safe_root_without_override(tmp_path, capsys):
    code = cli.main(["--sandbox", str(tmp_path), "health"])

    assert code == 2
    err = json.loads(capsys.readouterr().err)
    assert "Sandbox must stay inside" in err["error"]
