"""Read-only safety matrix for agent-facing Revit operator transports."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .journal import TaskJournal, utc_now
from .mcp_server import (
    ALLOW_EXTERNAL_SANDBOX_ENV as MCP_ALLOW_EXTERNAL_SANDBOX_ENV,
    _json_result,
    run_mcp_command,
)
from .server import (
    ALLOW_EXTERNAL_SANDBOX_ENV as HTTP_ALLOW_EXTERNAL_SANDBOX_ENV,
    _redact_control_payload,
    run_control_command,
)
from .safety import validate_output_path


APPROVAL_TOKEN_RE = re.compile(r"\bAPPROVE:[A-Za-z0-9_.:-]+\b")
APPROVAL_PHRASE_RE = re.compile(r"\bI approve\b", re.IGNORECASE)
REDACTION_MARKER_RE = re.compile(r"<redacted approval (?:material|token|phrase)>")
PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV = "HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX"


def build_transport_safety_matrix(
    journal: TaskJournal,
    *,
    repo_root: Path,
    stable_json: Path | None = None,
    stable_markdown: Path | None = None,
) -> dict:
    """Validate redaction/blocking behavior for CLI, HTTP, MCP, and plugin wrappers.

    This matrix is intentionally read-only.  It exercises only redactors and
    fail-closed argument paths that return before Revit/UI/bridge dispatch.
    """

    sample_payload = {
        "success": True,
        "required_human_approval_phrase": (
            "i approve safe-ribbon-view-tab with token APPROVE:transport-secret"
        ),
        "approval_token": "APPROVE:transport-secret",
        "nested": [
            "Nested phrase I APPROVE another action with token APPROVE:nested-secret"
        ],
    }

    from .cli import _redact_approval_stdout

    checks: list[dict] = [
        _redaction_check(
            "cli-stdout-redaction",
            "CLI stdout redactor removes approval tokens and phrases before printing.",
            _redact_approval_stdout(sample_payload),
            expected_redaction=True,
        ),
        _redaction_check(
            "http-control-redaction",
            "HTTP/control dispatcher redaction removes approval material from structured payloads.",
            _redact_control_payload(sample_payload),
            expected_redaction=True,
        ),
        _redaction_check(
            "mcp-json-redaction",
            "MCP JSON serializer redacts approval material before returning tool output.",
            json.loads(_json_result(sample_payload)),
            expected_redaction=True,
        ),
    ]

    plugin = _load_plugin(repo_root)
    if plugin.get("available"):
        plugin_module = plugin["module"]
        checks.append(
            _redaction_check(
                "plugin-redaction",
                "Hermes plugin wrapper redacts approval material before returning tool output.",
                plugin_module._redact_plugin_payload(sample_payload),
                expected_redaction=True,
            )
        )
        schema = plugin_module._tool_schema()
        properties = schema.get("parameters", {}).get("properties", {})
        checks.append(
            _boolean_check(
                "plugin-schema-withholds-external-sandbox-override",
                "Hermes plugin tool schema does not advertise the test-only outside-safe-root override.",
                "allow_sandbox_outside_safe_root" not in properties,
                payload={
                    "property_present": "allow_sandbox_outside_safe_root" in properties,
                },
            )
        )
    else:
        checks.append(
            _boolean_check(
                "plugin-wrapper-loadable",
                "Hermes plugin wrapper can be loaded for transport safety validation.",
                False,
                payload={"reason": plugin.get("reason")},
            )
        )

    checks.extend(_blocked_transport_checks(repo_root, plugin.get("module")))

    failed = [check for check in checks if not check.get("passed")]
    result = {
        "success": True,
        "read_only": True,
        "generated_at_utc": utc_now(),
        "may_execute_from_this_result": False,
        "completion_allowed": False,
        "may_call_update_goal": False,
        "audit_completion_authorized": False,
        "live_revit_touched": False,
        "status": "clean" if not failed else "violations",
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "failed_check_ids": [check["id"] for check in failed],
        "direct_approval_marker_count": sum(
            int(check.get("direct_approval_marker_count") or 0) for check in checks
        ),
        "redaction_marker_count": sum(
            int(check.get("redaction_marker_count") or 0) for check in checks
        ),
        "external_sandbox_override_env": {
            "http_enabled": _env_enabled(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV),
            "mcp_enabled": _env_enabled(MCP_ALLOW_EXTERNAL_SANDBOX_ENV),
            "plugin_enabled": _env_enabled(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV),
        },
        "checks": checks,
    }
    result["checked_at_utc"] = result["generated_at_utc"]

    json_path = journal.metadata_dir / "transport_safety_matrix.json"
    markdown_path = journal.metadata_dir / "transport_safety_matrix.md"
    stable_json = stable_json or journal.sandbox / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json"
    stable_markdown = (
        stable_markdown
        or journal.sandbox / "NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.md"
    )
    for path in [json_path, markdown_path, stable_json, stable_markdown]:
        error = validate_output_path(path, journal.sandbox)
        if error:
            return {
                **result,
                "success": False,
                "status": "violations",
                "failed_count": result["failed_count"] + 1,
                "error": error,
            }
        path.parent.mkdir(parents=True, exist_ok=True)
    result["path"] = str(json_path)
    result["markdown_path"] = str(markdown_path)
    result["stable_path"] = str(stable_json)
    result["stable_markdown_path"] = str(stable_markdown)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_transport_safety_markdown(result), encoding="utf-8")
    if json_path.resolve() != stable_json.resolve():
        shutil.copyfile(json_path, stable_json)
    if markdown_path.resolve() != stable_markdown.resolve():
        shutil.copyfile(markdown_path, stable_markdown)
    return result


def _blocked_transport_checks(repo_root: Path, plugin_module: Any | None) -> list[dict]:
    checks: list[dict] = []
    if _env_enabled(HTTP_ALLOW_EXTERNAL_SANDBOX_ENV):
        checks.append(
            _boolean_check(
                "http-blocks-external-sandbox-override",
                "HTTP/control dispatcher blocks the test-only outside-safe-root override by default.",
                False,
                payload={"reason": f"{HTTP_ALLOW_EXTERNAL_SANDBOX_ENV} is enabled."},
            )
        )
    else:
        checks.append(
            _blocked_result_check(
                "http-blocks-external-sandbox-override",
                "HTTP/control dispatcher blocks the test-only outside-safe-root override by default.",
                run_control_command(
                    {
                        "command": "known-dialogs",
                        "allow_sandbox_outside_safe_root": True,
                    }
                ),
                [HTTP_ALLOW_EXTERNAL_SANDBOX_ENV],
            )
        )

    outside_model = str(repo_root / "_transport_safety_outside_model.rvt")
    checks.append(
        _blocked_result_check(
            "http-blocks-model-root-override",
            "HTTP/control dispatcher blocks the local development model-root override.",
            run_control_command(
                {
                    "command": "open-model",
                    "args": [
                        "--model",
                        outside_model,
                        "--allow-model-outside-safe-root",
                    ],
                }
            ),
            ["--allow-model-outside-safe-root"],
        )
    )
    checks.append(
        _blocked_result_check(
            "http-blocks-recursive-serve",
            "HTTP/control dispatcher blocks recursive server startup.",
            run_control_command({"command": "serve"}),
            ["serve", "cannot be called"],
        )
    )

    if _env_enabled(MCP_ALLOW_EXTERNAL_SANDBOX_ENV):
        checks.append(
            _boolean_check(
                "mcp-blocks-external-sandbox-override",
                "MCP wrapper blocks the test-only outside-safe-root override by default.",
                False,
                payload={"reason": f"{MCP_ALLOW_EXTERNAL_SANDBOX_ENV} is enabled."},
            )
        )
    else:
        checks.append(
            _blocked_result_check(
                "mcp-blocks-external-sandbox-override",
                "MCP wrapper blocks the test-only outside-safe-root override by default.",
                run_mcp_command(
                    command="known-dialogs",
                    allow_sandbox_outside_safe_root=True,
                ),
                [MCP_ALLOW_EXTERNAL_SANDBOX_ENV],
            )
        )
    checks.append(
        _blocked_result_check(
            "mcp-blocks-model-root-override",
            "MCP wrapper blocks the local development model-root override.",
            run_mcp_command(
                command="open-model",
                args=[
                    "--model",
                    outside_model,
                    "--allow-model-outside-safe-root",
                ],
            ),
            ["--allow-model-outside-safe-root"],
        )
    )
    checks.append(
        _blocked_result_check(
            "mcp-blocks-recursive-serve",
            "MCP wrapper blocks recursive server startup.",
            run_mcp_command(command="serve"),
            ["serve", "blocked"],
        )
    )

    if plugin_module is None:
        return checks

    if _env_enabled(PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV):
        checks.append(
            _boolean_check(
                "plugin-blocks-external-sandbox-override",
                "Hermes plugin wrapper blocks the test-only outside-safe-root override by default.",
                False,
                payload={"reason": f"{PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV} is enabled."},
            )
        )
    else:
        checks.append(
            _blocked_result_check(
                "plugin-blocks-external-sandbox-override",
                "Hermes plugin wrapper blocks the test-only outside-safe-root override by default.",
                plugin_module.run_revit_operator_tool(
                    {
                        "command": "known-dialogs",
                        "allow_sandbox_outside_safe_root": True,
                    }
                ),
                [PLUGIN_ALLOW_EXTERNAL_SANDBOX_ENV],
            )
        )
    checks.append(
        _blocked_result_check(
            "plugin-blocks-model-root-override",
            "Hermes plugin wrapper blocks the local development model-root override.",
            plugin_module.run_revit_operator_tool(
                {
                    "command": "open-model",
                    "args": [
                        "--model",
                        outside_model,
                        "--allow-model-outside-safe-root",
                    ],
                }
            ),
            ["--allow-model-outside-safe-root"],
        )
    )
    checks.append(
        _blocked_result_check(
            "plugin-blocks-recursive-serve",
            "Hermes plugin wrapper blocks recursive server startup.",
            plugin_module.run_revit_operator_tool({"command": "serve"}),
            ["serve", "blocked"],
        )
    )
    return checks


def _redaction_check(
    check_id: str,
    requirement: str,
    payload: Any,
    *,
    expected_redaction: bool,
) -> dict:
    direct_count = _direct_approval_marker_count(payload)
    redaction_count = _redaction_marker_count(payload)
    passed = direct_count == 0 and (not expected_redaction or redaction_count > 0)
    return {
        "id": check_id,
        "requirement": requirement,
        "passed": passed,
        "status": "pass" if passed else "fail",
        "direct_approval_marker_count": direct_count,
        "redaction_marker_count": redaction_count,
        "expected_redaction_marker": expected_redaction,
        "reason": (
            "Approval material is redacted."
            if passed
            else "Output still exposes approval material or lacks expected redaction markers."
        ),
    }


def _blocked_result_check(
    check_id: str,
    requirement: str,
    payload: Any,
    required_error_terms: list[str],
) -> dict:
    direct_count = _direct_approval_marker_count(payload)
    redaction_count = _redaction_marker_count(payload)
    error = str(payload.get("error", "")) if isinstance(payload, dict) else ""
    missing_terms = [
        term for term in required_error_terms if term.lower() not in error.lower()
    ]
    success_value = payload.get("success") if isinstance(payload, dict) else None
    passed = success_value is False and not missing_terms and direct_count == 0
    return {
        "id": check_id,
        "requirement": requirement,
        "passed": passed,
        "status": "pass" if passed else "fail",
        "direct_approval_marker_count": direct_count,
        "redaction_marker_count": redaction_count,
        "success_value": success_value,
        "missing_error_terms": missing_terms,
        "reason": (
            "Transport failed closed before dispatch."
            if passed
            else "Transport did not fail closed with the expected error signature."
        ),
    }


def _boolean_check(check_id: str, requirement: str, passed: bool, *, payload: Any) -> dict:
    return {
        "id": check_id,
        "requirement": requirement,
        "passed": bool(passed),
        "status": "pass" if passed else "fail",
        "direct_approval_marker_count": _direct_approval_marker_count(payload),
        "redaction_marker_count": _redaction_marker_count(payload),
        "reason": "Check passed." if passed else "Check failed.",
    }


def _direct_approval_marker_count(value: Any) -> int:
    text = _safe_json(value)
    return len(APPROVAL_TOKEN_RE.findall(text)) + len(APPROVAL_PHRASE_RE.findall(text))


def _redaction_marker_count(value: Any) -> int:
    return len(REDACTION_MARKER_RE.findall(_safe_json(value)))


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_plugin(repo_root: Path) -> dict:
    plugin_path = repo_root / "plugins" / "revit-operator" / "__init__.py"
    if not plugin_path.exists():
        return {"available": False, "reason": f"Missing plugin at {plugin_path}."}
    try:
        spec = importlib.util.spec_from_file_location(
            "revit_operator_transport_safety_plugin",
            plugin_path,
        )
        if spec is None or spec.loader is None:
            return {"available": False, "reason": "Could not create plugin import spec."}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "module": module}


def _transport_safety_markdown(result: dict) -> str:
    lines = [
        "# Revit Operator Transport Safety Matrix",
        "",
        f"- status: `{result['status']}`",
        f"- read_only: `{str(result['read_only']).lower()}`",
        f"- live_revit_touched: `{str(result['live_revit_touched']).lower()}`",
        f"- completion_allowed: `{str(result['completion_allowed']).lower()}`",
        f"- may_call_update_goal: `{str(result['may_call_update_goal']).lower()}`",
        f"- audit_completion_authorized: `{str(result['audit_completion_authorized']).lower()}`",
        f"- may_execute_from_this_result: `{str(result['may_execute_from_this_result']).lower()}`",
        f"- check_count: `{result['check_count']}`",
        f"- passed_count: `{result['passed_count']}`",
        f"- failed_count: `{result['failed_count']}`",
        f"- direct_approval_marker_count: `{result['direct_approval_marker_count']}`",
        f"- redaction_marker_count: `{result['redaction_marker_count']}`",
        "",
        "| Check | Status | Direct Markers | Redaction Markers |",
        "| --- | --- | ---: | ---: |",
    ]
    for check in result["checks"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(check["id"]),
                    str(check["status"]),
                    str(check.get("direct_approval_marker_count", 0)),
                    str(check.get("redaction_marker_count", 0)),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)
