"""Local HTTP control server for the Revit operator CLI surface."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ALLOW_EXTERNAL_SANDBOX_ENV = "HERMES_REVIT_OPERATOR_HTTP_ALLOW_EXTERNAL_SANDBOX"


def make_control_server(
    host: str,
    port: int,
    *,
    sandbox: Path | None = None,
    allow_sandbox_outside_safe_root: bool = False,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RevitOperatorRequestHandler)
    server.revit_operator_sandbox = sandbox
    server.revit_operator_allow_external_sandbox = (
        allow_sandbox_outside_safe_root and _allow_external_sandbox_for_tests()
    )
    return server


def serve_control_server(
    *,
    host: str,
    port: int,
    sandbox: Path | None = None,
    allow_sandbox_outside_safe_root: bool = False,
) -> dict:
    server = make_control_server(
        host,
        port,
        sandbox=sandbox,
        allow_sandbox_outside_safe_root=allow_sandbox_outside_safe_root,
    )
    address, actual_port = server.server_address
    print(json.dumps({"success": True, "service": "revit-operator", "host": address, "port": actual_port}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"success": True, "stopped": True, "host": address, "port": actual_port}


def run_control_command(
    payload: dict,
    *,
    default_sandbox: Path | None = None,
    allow_sandbox_outside_safe_root: bool = False,
) -> dict:
    argv: list[str] = []
    try:
        argv = _payload_to_argv(
            payload,
            default_sandbox=default_sandbox,
            allow_sandbox_outside_safe_root=allow_sandbox_outside_safe_root,
        )
        from .cli import _stdout_result, build_parser, dispatch

        args = build_parser().parse_args(argv)
        if args.command == "serve":
            return {"success": False, "error": "The serve command cannot be called through the control server."}
        return _redact_control_payload(_stdout_result(args, dispatch(args)))
    except SystemExit as exc:
        return _redact_control_payload(
            {
                "success": False,
                "error": f"Invalid command arguments: exit {exc.code}",
                "argv": argv,
            }
        )
    except Exception as exc:
        return _redact_control_payload(
            {"success": False, "error": f"{type(exc).__name__}: {exc}", "argv": argv}
        )


def list_control_commands() -> dict:
    try:
        from .cli import _available_commands

        commands = _available_commands()
    except Exception as exc:
        return _redact_control_payload(
            {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        )
    return {
        "success": True,
        "service": "revit-operator",
        "transport": "local-http",
        "commands": commands,
        "blocked_commands": ["serve"],
    }


def _payload_to_argv(
    payload: dict,
    *,
    default_sandbox: Path | None,
    allow_sandbox_outside_safe_root: bool,
) -> list[str]:
    if "argv" in payload:
        argv = payload["argv"]
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be a list of strings.")
        if (
            "--allow-sandbox-outside-safe-root" in argv
            and not allow_sandbox_outside_safe_root
            and not _allow_external_sandbox_for_tests()
        ):
            raise ValueError(
                "The HTTP control server blocks --allow-sandbox-outside-safe-root "
                f"unless {ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
            )
        if _argv_requests_model_outside_safe_root(argv):
            raise ValueError(
                "The control dispatcher blocks --allow-model-outside-safe-root "
                "through agent-facing transports. Use the direct local CLI for "
                "deliberate development tests."
            )
        return list(argv)

    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Payload requires command or argv.")

    argv: list[str] = []
    sandbox = payload.get("sandbox")
    if sandbox is None and default_sandbox is not None:
        sandbox = str(default_sandbox)
    if sandbox:
        argv.extend(["--sandbox", str(sandbox)])
    payload_requests_external_sandbox = bool(
        payload.get("allow_sandbox_outside_safe_root", False)
    )
    if payload_requests_external_sandbox and not _allow_external_sandbox_for_tests():
        raise ValueError(
            "The HTTP control server blocks allow_sandbox_outside_safe_root "
            f"unless {ALLOW_EXTERNAL_SANDBOX_ENV}=1 is set for local tests."
        )
    if payload_requests_external_sandbox or allow_sandbox_outside_safe_root:
        if not _allow_external_sandbox_for_tests():
            # Internal callers such as workflow runners or MCP wrappers may pass
            # this parameter only after applying their own stricter transport gate.
            pass
        argv.append("--allow-sandbox-outside-safe-root")
    task_id = payload.get("task_id")
    if task_id:
        argv.extend(["--task-id", str(task_id)])
    argv.append(command)
    args = payload.get("args") or []
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("args must be a list of strings.")
    argv.extend(args)
    if _argv_requests_model_outside_safe_root(argv):
        raise ValueError(
            "The control dispatcher blocks --allow-model-outside-safe-root "
            "through agent-facing transports. Use the direct local CLI for "
            "deliberate development tests."
        )
    return argv


def _allow_external_sandbox_for_tests() -> bool:
    value = os.getenv(ALLOW_EXTERNAL_SANDBOX_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _redact_control_payload(payload: dict) -> dict:
    try:
        from .cli import _redact_approval_stdout

        redacted = _redact_approval_stdout(payload)
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


class RevitOperatorRequestHandler(BaseHTTPRequestHandler):
    server_version = "RevitOperatorHTTP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(
                {
                    "success": True,
                    "service": "revit-operator",
                    "transport": "local-http",
                    "endpoints": ["/health", "/commands", "/command"],
                }
            )
            return
        if self.path == "/commands":
            self._write_json(list_control_commands())
            return
        self._write_json({"success": False, "error": "Not found."}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/command":
            self._write_json({"success": False, "error": "Not found."}, status=404)
            return
        try:
            payload = self._read_json()
            result = run_control_command(
                payload,
                default_sandbox=getattr(self.server, "revit_operator_sandbox", None),
                allow_sandbox_outside_safe_root=bool(
                    getattr(self.server, "revit_operator_allow_external_sandbox", False)
                ),
            )
        except Exception as exc:
            self._write_json(
                _redact_control_payload(
                    {"success": False, "error": f"{type(exc).__name__}: {exc}"}
                ),
                status=400,
            )
            return
        self._write_json(result, status=200 if result.get("success") else 400)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        data = self.rfile.read(length)
        payload = json.loads(data.decode("utf-8") if data else "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _write_json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
