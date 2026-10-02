"""Higher-level Revit operation request handling."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tools.path_security import validate_within_dir

from .bridge import RevitBridgeClient
from .constants import SAFE_PROJECT_ROOT
from .journal import TaskJournal, make_task_id, utc_now
from .revit_locator import infer_revit_version_from_model, resolve_revit_exe
from .safety import READ_ONLY_BRIDGE_OPERATIONS, SafetyDecision, authorize, classify_action, validate_output_path
from .version_support import validate_revit_version


MODEL_WRITE_OPERATIONS = {
    "save",
    "sync",
    "synchronize-with-central",
    "reload-links",
    "modify-model",
    "set-project-info-parameter",
}

SYNC_OPERATIONS = {"sync", "synchronize-with-central"}
PATH_OPERATIONS = {"open-model"}

# Every Revit with the add-in polls the shared queue and runs its untargeted lines, so operations that change a model
# or the open documents are queued only for a named Revit process. The add-in refuses them untargeted
# (TargetRequiredOperations in HermesRevitOperatorApp.cs).
TARGET_REQUIRED_OPERATIONS = MODEL_WRITE_OPERATIONS | {"open-model", "close-model"}


@dataclass
class OperationRequest:
    operation: str
    args: dict
    dry_run: bool = True
    approval_token: str | None = None
    allow_model_write: bool = False
    allow_sync: bool = False
    # The Revit the operation is for, by window or process id. Other Revit sessions skip the queued line.
    target_hwnd: int | None = None
    target_pid: int | None = None


def request_operation_payload(request: OperationRequest) -> dict:
    """The request-operation payload that queue_operation classifies and journals, without the target."""
    return {
        "operation": request.operation.strip().lower(),
        "args": request.args,
        "allow_model_write": request.allow_model_write,
        "allow_sync": request.allow_sync,
    }


def classify_operation(payload: dict, target: dict | None = None) -> SafetyDecision:
    """Classify a request-operation payload for the Revit process it is queued for.

    The approval covers the target as well, so a token approved for one Revit process does not run in another, or in a
    later process that reuses its id. Approval plans classify through here so that their tokens are the ones
    queue_operation expects.
    """
    return classify_action("request-operation", {**payload, "target": target} if target else payload)


def resolve_command_target(sandbox: Path, target_hwnd: int | None, target_pid: int | None) -> dict | None:
    """Resolve --hwnd/--pid to the target a queued line names, as queue_operation will, or None without either."""
    if not (target_hwnd or target_pid):
        return None
    return RevitBridgeClient(sandbox, target_hwnd=target_hwnd, target_pid=target_pid).command_target()


def target_cli_args(target: dict | None) -> list[str]:
    """The request-operation arguments that name a resolved target again."""
    return ["--pid", str(target["process_id"])] if target else []


def require_target(operation: str, bridge: RevitBridgeClient) -> dict:
    """Refuse an untargeted operation that must name its Revit process, listing the live ones to choose from."""
    if operation not in TARGET_REQUIRED_OPERATIONS:
        return {}
    live = [session for session in bridge.bridge_sessions() if session["live"]]
    return {
        "error": (
            f"Operation {operation!r} changes a model or the open documents, so it must name the Revit process "
            "it is for: pass --hwnd or --pid. " + _live_sessions_text(live)
        ),
        "live_sessions": live,
    }


def validate_model_path(path: Path, allow_outside_safe_root: bool = False) -> str | None:
    if allow_outside_safe_root:
        return None
    return validate_within_dir(path, SAFE_PROJECT_ROOT)


def open_model(
    model_path: Path,
    journal: TaskJournal,
    *,
    revit_version: str | None = None,
    revit_exe: str | None = None,
    detach: bool = False,
    allow_upgrade: bool = False,
    worksets: str | None = None,
    dry_run: bool = True,
    approval_token: str | None = None,
    allow_outside_safe_root: bool = False,
) -> dict:
    model_error = validate_model_path(model_path, allow_outside_safe_root)
    if model_error:
        raise ValueError(model_error)
    if not model_path.exists():
        raise FileNotFoundError(str(model_path))

    inferred = infer_revit_version_from_model(model_path)
    requested_version = revit_version or inferred
    version_error = None
    if requested_version:
        normalized_version, version_error = validate_revit_version(requested_version)
        requested_version = normalized_version or requested_version
    exe = resolve_revit_exe(requested_version, revit_exe)
    payload = {
        "model_path": str(model_path),
        "inferred_revit_version": inferred,
        "requested_revit_version": requested_version,
        "revit_exe": str(exe) if exe else None,
        "detach": detach,
        "allow_upgrade": allow_upgrade,
        "worksets": worksets,
    }
    decision = classify_action("open-model", payload)
    allowed, reason = authorize(decision, approval_token)

    result = {
        "success": False,
        "dry_run": dry_run,
        "policy": decision.to_dict(),
        "authorization": {"allowed": allowed, "reason": reason},
        "operation_plan": {
            "launch": [str(exe), str(model_path)] if exe else None,
            "expected_prompts": _expected_open_prompts(
                detach=detach,
                allow_upgrade=allow_upgrade,
                worksets=worksets,
                inferred_version=inferred,
                requested_version=requested_version,
            ),
            "post_open_checks": [
                "revit-operator status",
                "revit-operator list-dialogs",
                "revit-operator request-operation --operation active-document",
            ],
        },
    }
    if version_error:
        result["error"] = version_error
    elif exe is None:
        result["error"] = f"Could not locate Revit executable for version {requested_version!r}."
    elif dry_run:
        result["success"] = True
        result["next_step"] = f"Re-run with --execute --approval-token {decision.approval_token}"
    elif not allowed:
        result["error"] = reason
    else:
        env = dict(os.environ)
        env["HERMES_REVIT_OPERATOR_SANDBOX"] = str(journal.sandbox)
        process = subprocess.Popen([str(exe), str(model_path)], env=env)
        result.update(
            {
                "success": True,
                "pid": process.pid,
                "launched": True,
            }
        )

    journal.write_entry(
        {
            "command": "open-model",
            "requested_action": payload,
            "risk_classification": decision.to_dict(),
            "approval_status": result["authorization"],
            "result": {
                "status": "dry_run" if dry_run else ("launched" if result["success"] else "failed"),
                "success": result["success"],
            },
        }
    )
    return result


def queue_operation(journal: TaskJournal, request: OperationRequest) -> dict:
    payload = request_operation_payload(request)
    operation = payload["operation"]
    bridge = RevitBridgeClient(journal.sandbox, target_hwnd=request.target_hwnd, target_pid=request.target_pid)
    resolution = bridge.command_target() if request.target_hwnd or request.target_pid else None
    target = resolution.get("target") if resolution else None
    decision = classify_operation(payload, target)
    allowed, reason = authorize(decision, request.approval_token)
    guard_error = _guard_operation(operation, request)
    target_check = {} if guard_error else _check_target(operation, bridge, resolution)
    guard_error = guard_error or target_check.pop("error", None)

    command_id = request.args.get("id") or make_task_id(operation.replace("-", "_"))
    command = {
        "id": command_id,
        "timestamp": utc_now(),
        "operation": operation,
        "args": request.args,
        "guards": {
            "allow_model_write": request.allow_model_write,
            "allow_sync": request.allow_sync,
        },
        "approval": {
            "token": request.approval_token,
            "risk": decision.risk,
            "decision": decision.decision,
        },
    }
    if target:
        command["target"] = target

    result = {
        "success": False,
        "dry_run": request.dry_run,
        "command": command,
        "policy": decision.to_dict(),
        "authorization": {"allowed": allowed, "reason": reason},
        "bridge_queue": str(journal.sandbox / "bridge" / "command_queue.jsonl"),
        "target": target,
        **target_check,
    }
    if target:
        result["target_session"] = resolution["session"]
    if guard_error:
        result["error"] = guard_error
    elif request.dry_run:
        result["success"] = True
        result["next_step"] = _next_operation_step(decision.approval_token, operation, request)
    elif not allowed:
        result["error"] = reason
    else:
        queue_path = journal.sandbox / "bridge" / "command_queue.jsonl"
        error = validate_output_path(queue_path, journal.sandbox)
        if error:
            result["error"] = error
        else:
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            write_result = _append_command_jsonl(queue_path, command)
            result["bridge_write"] = write_result
            if write_result["success"]:
                result["success"] = True
                result["queued"] = True
            else:
                result["error"] = write_result["error"]

    journal.write_entry(
        {
            "command": "request-operation",
            "requested_action": payload,
            "risk_classification": decision.to_dict(),
            "approval_status": result["authorization"],
            "target": target,
            "result": {
                "status": "dry_run" if request.dry_run else ("queued" if result["success"] else "failed"),
                "success": result["success"],
            },
            "output_files": [result["bridge_queue"]],
        }
    )
    return result


def _append_command_jsonl(
    queue_path: Path,
    command: dict,
    *,
    attempts: int = 8,
    base_delay: float = 0.025,
) -> dict:
    line = json.dumps(command, sort_keys=True) + "\n"
    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            with queue_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            return {
                "success": True,
                "attempts": attempt + 1,
                "path": str(queue_path),
            }
        except OSError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(min(0.4, base_delay * (2**attempt)))
    return {
        "success": False,
        "attempts": max(1, attempts),
        "path": str(queue_path),
        "error": f"{type(last_error).__name__}: {last_error}",
        "error_type": type(last_error).__name__ if last_error else "OSError",
    }


def _guard_operation(operation: str, request: OperationRequest) -> str | None:
    if operation in PATH_OPERATIONS:
        raw_path = request.args.get("path") or request.args.get("model_path")
        if not raw_path:
            return f"Operation {operation!r} requires --args-json with path/model_path."
        path = Path(str(raw_path))
        model_error = validate_model_path(
            path,
            allow_outside_safe_root=bool(request.args.get("allow_model_outside_safe_root")),
        )
        if model_error:
            return model_error
        if not path.exists():
            return f"Model path does not exist: {path}"
    if operation in MODEL_WRITE_OPERATIONS and not request.allow_model_write:
        return f"Operation {operation!r} requires --allow-model-write."
    if operation in SYNC_OPERATIONS and not request.allow_sync:
        return "Synchronize with Central requires --allow-sync in addition to approval."
    if operation == "set-project-info-parameter":
        if not request.args.get("name"):
            return "set-project-info-parameter requires --name."
        if "value" not in request.args:
            return "set-project-info-parameter requires --value."
    if operation == "activate-view":
        if not (
            request.args.get("id")
            or request.args.get("view_id")
            or request.args.get("view_name")
            or request.args.get("name")
            or request.args.get("sheet_number")
        ):
            return "activate-view requires id/view_id, view_name/name, or sheet_number."
    return None


def _check_target(operation: str, bridge: RevitBridgeClient, resolution: dict | None) -> dict:
    """Check that the queued line runs in its target Revit only. Returns an error and/or fields for the result."""
    if resolution is None:
        return require_target(operation, bridge)
    if not resolution["success"]:
        return {"error": resolution["error"]}
    target_pid = resolution["target"]["process_id"]
    # A build older than command targets runs every line, this one included.
    ignoring = [
        session["process_id"]
        for session in bridge.bridge_sessions()
        if session["live"] and not session["honors_command_targets"] and session["process_id"] != target_pid
    ]
    if not ignoring:
        return {}
    pids = ", ".join(str(pid) for pid in ignoring)
    note = (
        f"Revit process {pids} runs" if len(ignoring) == 1 else f"Revit processes {pids} run"
    ) + " an add-in build that ignores command targets and would run this command as well."
    if operation in READ_ONLY_BRIDGE_OPERATIONS:
        return {"target_warning": note, "sessions_ignoring_target": ignoring}
    restart = " Restart it" if len(ignoring) == 1 else " Restart them"
    return {"error": note + restart + " on the current add-in build first.", "sessions_ignoring_target": ignoring}


def _live_sessions_text(sessions: list[dict]) -> str:
    if not sessions:
        return "No live Revit session writes status files to this bridge folder."
    described = [
        f"pid {session['process_id']} ({(session.get('document') or {}).get('title') or 'no document'})"
        for session in sessions
    ]
    return "Live Revit sessions on this bridge: " + "; ".join(described) + "."


def _next_operation_step(token: str | None, operation: str, request: OperationRequest) -> str:
    flags = ["--execute"]
    if token:
        flags.extend(["--approval-token", token])
    if operation in MODEL_WRITE_OPERATIONS:
        flags.append("--allow-model-write")
    if operation in SYNC_OPERATIONS:
        flags.append("--allow-sync")
    # The token covers the target, so the execution must name the same Revit.
    if request.target_hwnd:
        flags.extend(["--hwnd", str(request.target_hwnd)])
    if request.target_pid:
        flags.extend(["--pid", str(request.target_pid)])
    return "Re-run request-operation with " + " ".join(flags)


def _expected_open_prompts(
    *,
    detach: bool,
    allow_upgrade: bool,
    worksets: str | None,
    inferred_version: str | None,
    requested_version: str | None,
) -> list[dict]:
    prompts = []
    if inferred_version and requested_version and inferred_version != requested_version:
        prompts.append(
            {
                "kind": "version_mismatch",
                "risk": "high",
                "reason": f"Model marker suggests Revit {inferred_version}, requested {requested_version}.",
            }
        )
    if detach:
        prompts.append(
            {
                "kind": "detach_from_central",
                "risk": "critical",
                "reason": "Detach/preserve worksets prompt must be handled by a human-approved UI action.",
            }
        )
    if allow_upgrade:
        prompts.append(
            {
                "kind": "upgrade_model",
                "risk": "critical",
                "reason": "Upgrade prompt must be explicitly approved for copied local models only.",
            }
        )
    if worksets:
        prompts.append(
            {
                "kind": "worksets",
                "risk": "high",
                "reason": f"Requested workset option: {worksets}.",
            }
        )
    return prompts
