"""MCP stdio wrapper for the Revit human-operator command surface.

This module is intentionally thin.  MCP is only a transport here; every tool
call is routed back through the existing ``run_control_command`` dispatcher so
sandbox validation, dry-run defaults, approval tokens, and journaling stay in
one place.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Optional

from .server import _redact_control_payload, run_control_command

logger = logging.getLogger("hermes.revit_operator.mcp")

_MCP_SERVER_AVAILABLE = False
try:
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]


BLOCKED_MCP_COMMANDS = {"serve", "mcp-serve"}
_GLOBAL_FLAGS_WITH_VALUE = {"--sandbox", "--task-id"}
_GLOBAL_FLAGS_WITHOUT_VALUE = {"--allow-sandbox-outside-safe-root", "--json"}
ALLOW_EXTERNAL_SANDBOX_ENV = "HERMES_REVIT_OPERATOR_MCP_ALLOW_EXTERNAL_SANDBOX"


def run_mcp_command(
    *,
    command: str,
    args: Optional[list[str]] = None,
    sandbox: Optional[str] = None,
    task_id: Optional[str] = None,
    allow_sandbox_outside_safe_root: bool = False,
    argv: Optional[list[str]] = None,
) -> dict:
    """Run one Revit operator command as an MCP request.

    The result shape is the same structured JSON dict returned by the CLI and
    HTTP surfaces, with ``called_via`` added for auditability.
    """

    try:
        external_sandbox_allowed = _allow_external_sandbox_for_tests()
        payload = _build_payload(
            command=command,
            args=args,
            sandbox=sandbox,
            task_id=task_id,
            allow_sandbox_outside_safe_root=allow_sandbox_outside_safe_root,
            argv=argv,
        )
        if payload.get("_blocked_error"):
            result = {
                "success": False,
                "error": payload["_blocked_error"],
            }
        else:
            result = run_control_command(
                payload,
                allow_sandbox_outside_safe_root=(
                    allow_sandbox_outside_safe_root or external_sandbox_allowed
                ),
            )
    except Exception as exc:
        result = _redact_control_payload(
            {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    if isinstance(result, dict):
        result.setdefault("called_via", "mcp")
        redacted = _redact_control_payload(result)
        return redacted if isinstance(redacted, dict) else result
    redacted = _redact_control_payload(
        {"success": True, "result": result, "called_via": "mcp"}
    )
    if isinstance(redacted, dict):
        return redacted
    return {"success": True, "result": result, "called_via": "mcp"}


def list_mcp_commands() -> dict:
    """Return the command names visible through the MCP wrapper."""

    try:
        from .cli import build_parser

        parser = build_parser()
        commands: list[str] = []
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                commands = sorted(action.choices)
                break
    except Exception as exc:
        return _redact_control_payload(
            {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "called_via": "mcp",
            }
        )

    return {
        "success": True,
        "commands": commands,
        "blocked_commands": sorted(BLOCKED_MCP_COMMANDS),
        "called_via": "mcp",
    }


def create_mcp_server() -> "FastMCP":
    """Create a FastMCP server exposing the Revit operator wrapper tools."""

    if not _MCP_SERVER_AVAILABLE:
        raise ImportError(
            "Revit operator MCP wrapper requires the 'mcp' package. "
            "Install Hermes with the mcp extra or use the CLI/HTTP/plugin wrapper."
        )

    mcp = FastMCP("revit-operator")

    @mcp.tool()
    def revit_operator_health() -> str:
        """Run the read-only Revit operator health command."""

        return _json_result(run_mcp_command(command="health"))

    @mcp.tool()
    def revit_operator_commands() -> str:
        """List Revit operator commands available through this MCP wrapper."""

        return _json_result(list_mcp_commands())

    @mcp.tool()
    def revit_operator_command(
        command: str,
        args: Optional[list[str]] = None,
        sandbox: Optional[str] = None,
        task_id: Optional[str] = None,
        argv: Optional[list[str]] = None,
    ) -> str:
        """Run one safety-gated Revit operator command.

        Use ``command`` plus ``args`` for normal calls.  ``argv`` exists for
        advanced local testing and is still blocked from starting server modes.
        Actions dry-run by default and still require exact approval tokens.
        """

        return _json_result(
            run_mcp_command(
                command=command,
                args=args,
                sandbox=sandbox,
                task_id=task_id,
                argv=argv,
            )
        )

    return mcp


def run_mcp_server(*, verbose: bool = False) -> None:
    """Start the Revit operator MCP server on stdio."""

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    server = create_mcp_server()

    import asyncio

    async def _run() -> None:
        await server.run_stdio_async()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.debug("Revit operator MCP server stopped by keyboard interrupt.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="revit-operator-mcp")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)
    try:
        run_mcp_server(verbose=args.verbose)
    except ImportError as exc:
        print(
            json.dumps(
                _redact_control_payload({"success": False, "error": str(exc)}),
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    return 0


def _build_payload(
    *,
    command: str,
    args: Optional[list[str]],
    sandbox: Optional[str],
    task_id: Optional[str],
    allow_sandbox_outside_safe_root: bool,
    argv: Optional[list[str]],
) -> dict:
    if argv:
        checked_argv = _coerce_string_list(argv, "argv")
        if (
            "--allow-sandbox-outside-safe-root" in checked_argv
            and not _allow_external_sandbox_for_tests()
        ):
            return {
                "command": "health",
                "args": [],
                "_blocked_error": (
                    "The MCP wrapper blocks --allow-sandbox-outside-safe-root "
                    f"unless {ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
                ),
            }
        if (
            allow_sandbox_outside_safe_root
            and "--allow-sandbox-outside-safe-root" not in checked_argv
        ):
            if not _allow_external_sandbox_for_tests():
                return {
                    "command": "health",
                    "args": [],
                    "_blocked_error": (
                        "The MCP wrapper blocks allow_sandbox_outside_safe_root "
                        f"unless {ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
                    ),
                }
            checked_argv = ["--allow-sandbox-outside-safe-root", *checked_argv]
        blocked = _blocked_command_from_argv(checked_argv)
        if blocked:
            return _blocked_payload(blocked)
        return {"argv": checked_argv}

    if not isinstance(command, str) or not command.strip():
        raise ValueError("command is required.")
    command = command.strip()
    if command in BLOCKED_MCP_COMMANDS:
        return _blocked_payload(command)

    payload: dict = {"command": command, "args": _coerce_string_list(args or [], "args")}
    if sandbox:
        payload["sandbox"] = str(Path(str(sandbox)))
    if task_id:
        payload["task_id"] = str(task_id)
    if allow_sandbox_outside_safe_root:
        if not _allow_external_sandbox_for_tests():
            return {
                "command": "health",
                "args": [],
                "_blocked_error": (
                    "The MCP wrapper blocks allow_sandbox_outside_safe_root "
                    f"unless {ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
                ),
            }
    return payload


def _allow_external_sandbox_for_tests() -> bool:
    value = os.getenv(ALLOW_EXTERNAL_SANDBOX_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _blocked_payload(command: str) -> dict:
    return {
        "command": "health",
        "args": [],
        "_blocked_error": (
            f"The {command!r} command is blocked through the MCP wrapper. "
            "Start long-running servers explicitly from a local shell."
        ),
    }


def _coerce_string_list(value: object, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
    return list(value)


def _blocked_command_from_argv(argv: list[str]) -> str | None:
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in _GLOBAL_FLAGS_WITH_VALUE:
            index += 2
            continue
        if item in _GLOBAL_FLAGS_WITHOUT_VALUE:
            index += 1
            continue
        if item.startswith("--"):
            index += 1
            continue
        return item if item in BLOCKED_MCP_COMMANDS else None
    return None


def _json_result(result: dict) -> str:
    redacted = _redact_control_payload(result)
    return json.dumps(
        redacted if isinstance(redacted, dict) else result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
