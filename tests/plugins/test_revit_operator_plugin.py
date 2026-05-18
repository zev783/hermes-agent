import importlib.util
import json
from pathlib import Path


PLUGIN_PATH = Path(__file__).resolve().parents[2] / "plugins" / "revit-operator" / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("revit_operator_plugin_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_revit_operator_plugin_registers_tool():
    plugin = _load_plugin()
    calls = []

    class Ctx:
        def register_tool(self, **kwargs):
            calls.append(kwargs)

    plugin.register(Ctx())

    assert calls
    assert calls[0]["name"] == "revit_operator"
    assert calls[0]["toolset"] == "plugin_revit_operator"
    assert calls[0]["schema"]["parameters"]["properties"]["command"]
    assert (
        "allow_sandbox_outside_safe_root"
        not in calls[0]["schema"]["parameters"]["properties"]
    )


def test_revit_operator_plugin_runs_known_dialogs(tmp_path, monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setenv(plugin.ALLOW_EXTERNAL_SANDBOX_ENV, "1")

    result = plugin.run_revit_operator_tool(
        {
            "command": "known-dialogs",
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
            "task_id": "plugin-known-dialogs-test",
        }
    )

    assert result["success"] is True
    assert result["called_via"] == "hermes-plugin"
    assert result["count"] >= 5
    assert Path(result["journal"]["journal"]).is_relative_to(tmp_path)


def test_revit_operator_plugin_redacts_approval_material_in_results(monkeypatch):
    plugin = _load_plugin()

    from tools.revit_operator import cli

    def fake_dispatch(_args):
        return {
            "success": True,
            "required_human_approval_phrase": (
                "I approve safe-ribbon-view-tab with token APPROVE:plugin-secret"
            ),
            "approval_token": "APPROVE:plugin-secret",
        }

    monkeypatch.setattr(cli, "dispatch", fake_dispatch)

    result = plugin.run_revit_operator_tool({"command": "health"})
    result_text = json.dumps(result)

    assert result["success"] is True
    assert result["called_via"] == "hermes-plugin"
    assert "APPROVE:plugin-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval material>" in result_text


def test_revit_operator_plugin_redacts_approval_material_in_parse_errors(capsys):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
        {
            "command": "ignored",
            "argv": [
                "north-star-approval-verify",
                "--approval-token",
                "APPROVE:plugin-secret",
                "--bad-flag",
            ],
        }
    )
    capsys.readouterr()
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:plugin-secret" not in result_text
    assert "<redacted approval token>" in result_text


def test_revit_operator_plugin_handler_redacts_approval_material_in_exceptions(monkeypatch):
    plugin = _load_plugin()

    def fail_tool(_args):
        raise ValueError(
            "Bad phrase I approve safe-ribbon-view-tab with token APPROVE:plugin-secret"
        )

    monkeypatch.setattr(plugin, "run_revit_operator_tool", fail_tool)

    result = json.loads(plugin._handler({"command": "health"}))
    result_text = json.dumps(result)

    assert result["success"] is False
    assert "APPROVE:plugin-secret" not in result_text
    assert "I approve" not in result_text
    assert "<redacted approval token>" in result_text


def test_revit_operator_plugin_blocks_external_sandbox_escape_without_test_env(tmp_path):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
        {
            "command": "known-dialogs",
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
            "task_id": "plugin-known-dialogs-blocked-test",
        }
    )

    assert result["success"] is False
    assert "allow_sandbox_outside_safe_root" in result["error"]
    assert plugin.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_revit_operator_plugin_blocks_argv_external_sandbox_escape_without_test_env(tmp_path):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
        {
            "command": "known-dialogs",
            "argv": [
                "--sandbox",
                str(tmp_path),
                "--allow-sandbox-outside-safe-root",
                "known-dialogs",
            ],
        }
    )

    assert result["success"] is False
    assert "--allow-sandbox-outside-safe-root" in result["error"]
    assert plugin.ALLOW_EXTERNAL_SANDBOX_ENV in result["error"]


def test_revit_operator_plugin_blocks_model_outside_safe_root_flag(tmp_path):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
        {
            "command": "open-model",
            "args": [
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        }
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_revit_operator_plugin_blocks_argv_model_outside_safe_root_flag(tmp_path):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
        {
            "command": "ignored",
            "argv": [
                "open-model",
                "--model",
                str(tmp_path / "outside.rvt"),
                "--allow-model-outside-safe-root",
            ],
        }
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_revit_operator_plugin_blocks_nested_model_outside_safe_root_override(tmp_path):
    plugin = _load_plugin()

    result = plugin.run_revit_operator_tool(
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
        }
    )

    assert result["success"] is False
    assert "--allow-model-outside-safe-root" in result["error"]


def test_revit_operator_plugin_blocks_serve(tmp_path, monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setenv(plugin.ALLOW_EXTERNAL_SANDBOX_ENV, "1")

    result = plugin.run_revit_operator_tool(
        {
            "command": "serve",
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
        }
    )

    assert result["success"] is False
    assert "blocked" in result["error"].lower()


def test_revit_operator_plugin_runs_safe_command_dry_run(tmp_path, monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setenv(plugin.ALLOW_EXTERNAL_SANDBOX_ENV, "1")

    result = plugin.run_revit_operator_tool(
        {
            "command": "run-safe-command",
            "args": ["--name", "active-document"],
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
            "task_id": "plugin-safe-command-test",
        }
    )

    assert result["success"] is True
    assert result["called_via"] == "hermes-plugin"
    assert result["dry_run"] is True
    assert result["safe_command"]["delegates_to"] == "request-operation"
    assert result["safe_command"]["delegated_operation"] == "active-document"
    assert result["wrapper_policy"]["decision"] == "allow"
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_revit_operator_plugin_blocks_unsafe_safe_command(tmp_path, monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setenv(plugin.ALLOW_EXTERNAL_SANDBOX_ENV, "1")

    result = plugin.run_revit_operator_tool(
        {
            "command": "run-safe-command",
            "args": ["--name", "save", "--execute"],
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
            "task_id": "plugin-safe-command-block-test",
        }
    )

    assert result["success"] is False
    assert result["wrapper_policy"]["decision"] == "block"
    assert result["safe_command"]["delegates_to"] is None
    assert not (tmp_path / "bridge" / "command_queue.jsonl").exists()


def test_revit_operator_plugin_handler_returns_json(tmp_path, monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setenv(plugin.ALLOW_EXTERNAL_SANDBOX_ENV, "1")

    raw = plugin._handler(
        {
            "command": "dialog-workflows",
            "sandbox": str(tmp_path),
            "allow_sandbox_outside_safe_root": True,
            "task_id": "plugin-json-test",
        }
    )

    result = json.loads(raw)
    assert result["success"] is True
    assert result["called_via"] == "hermes-plugin"
