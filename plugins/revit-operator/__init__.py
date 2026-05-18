"""Hermes plugin wrapper for the local Revit operator command surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


TOOL_NAME = "revit_operator"
TOOLSET = "plugin_revit_operator"
ALLOW_EXTERNAL_SANDBOX_ENV = "HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX"


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": (
            "Run one safety-gated revit-operator command and return its structured JSON. "
            "This is a wrapper over tools.revit_operator.cli, not a bypass. "
            "Actions still dry-run by default and require exact approval tokens."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The revit-operator subcommand to run, such as status, "
                        "list-dialogs, screenshot, plan-current-dialog-response, "
                        "run-safe-command, qa-workflow, or replay-workflow. "
                        "The serve command is blocked."
                    ),
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subcommand arguments as individual strings.",
                },
                "sandbox": {
                    "type": "string",
                    "description": "Optional sandbox root. Defaults to the operator's configured safe sandbox.",
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional task journal id to reuse.",
                },
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional full revit-operator argv for advanced/local testing. "
                        "Prefer command plus args."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    }


def _handler(args: dict, **_kwargs: Any) -> str:
    try:
        result = run_revit_operator_tool(args)
    except Exception as exc:
        result = _redact_plugin_payload(
            {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        )
    return json.dumps(result, ensure_ascii=False)


def run_revit_operator_tool(args: dict) -> dict:
    """Run a revit-operator command through the normal CLI parser/dispatcher."""

    try:
        argv = _payload_to_argv(args)
    except Exception as exc:
        return _redact_plugin_payload(
            {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    from tools.revit_operator.cli import build_parser, dispatch

    try:
        parsed = build_parser().parse_args(argv)
    except SystemExit as exc:
        return _redact_plugin_payload(
            {
                "success": False,
                "error": f"Invalid revit-operator arguments: exit {exc.code}",
                "argv": argv,
            }
        )

    if parsed.command == "serve":
        return _redact_plugin_payload(
            {
                "success": False,
                "error": "The serve command is intentionally blocked inside the Hermes plugin tool.",
                "argv": argv,
            }
        )

    result = dispatch(parsed)
    if isinstance(result, dict):
        result.setdefault("called_via", "hermes-plugin")
        return _redact_plugin_payload(result)
    return _redact_plugin_payload(
        {"success": True, "result": result, "called_via": "hermes-plugin"}
    )


def _payload_to_argv(args: dict) -> list[str]:
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object.")

    if "argv" in args and args["argv"]:
        argv = args["argv"]
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be a list of strings.")
        if "--allow-sandbox-outside-safe-root" in argv and not _allow_external_sandbox_for_tests():
            raise ValueError(
                "The Hermes plugin blocks --allow-sandbox-outside-safe-root unless "
                f"{ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
            )
        if _argv_requests_model_outside_safe_root(argv):
            raise ValueError(
                "The Hermes plugin blocks --allow-model-outside-safe-root through "
                "agent-facing calls. Use the direct local CLI for deliberate "
                "development tests."
            )
        return list(argv)

    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command is required.")

    argv: list[str] = []
    sandbox = args.get("sandbox")
    if sandbox:
        argv.extend(["--sandbox", str(Path(str(sandbox)))])
    if args.get("allow_sandbox_outside_safe_root"):
        if not _allow_external_sandbox_for_tests():
            raise ValueError(
                "The Hermes plugin blocks allow_sandbox_outside_safe_root unless "
                f"{ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
            )
        argv.append("--allow-sandbox-outside-safe-root")
    task_id = args.get("task_id")
    if task_id:
        argv.extend(["--task-id", str(task_id)])
    argv.append(command)

    command_args = args.get("args") or []
    if not isinstance(command_args, list) or not all(isinstance(item, str) for item in command_args):
        raise ValueError("args must be a list of strings.")
    argv.extend(command_args)
    if _argv_requests_model_outside_safe_root(argv):
        raise ValueError(
            "The Hermes plugin blocks --allow-model-outside-safe-root through "
            "agent-facing calls. Use the direct local CLI for deliberate "
            "development tests."
        )
    return argv


def _allow_external_sandbox_for_tests() -> bool:
    value = os.getenv(ALLOW_EXTERNAL_SANDBOX_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _redact_plugin_payload(payload: dict) -> dict:
    try:
        from tools.revit_operator.server import _redact_control_payload

        redacted = _redact_control_payload(payload)
    except Exception:
        return payload
    return redacted if isinstance(redacted, dict) else payload


def _argv_requests_model_outside_safe_root(argv: list[str]) -> bool:
    for index, item in enumerate(argv):
        if item == "--allow-model-outside-safe-root":
            return True
        if item == "--args-json" and index + 1 < len(argv):
            if _args_json_requests_model_outside_safe_root(argv[index + 1]):
                return True
        if item.startswith("--args-json="):
            if _args_json_requests_model_outside_safe_root(item.split("=", 1)[1]):
                return True
    return False


def _args_json_requests_model_outside_safe_root(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict) and value.get("allow_model_outside_safe_root") is True


def _check_requirements() -> bool:
    try:
        from tools.revit_operator.cli import build_parser  # noqa: F401
    except Exception:
        return False
    return True


def register(ctx) -> None:
    ctx.register_tool(
        name=TOOL_NAME,
        toolset=TOOLSET,
        schema=_tool_schema(),
        handler=_handler,
        check_fn=_check_requirements,
        description="Safety-gated local Revit operator command wrapper.",
        emoji="R",
    )
