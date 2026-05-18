"""Higher-level Revit operation request handling."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tools.path_security import validate_within_dir

from .constants import SAFE_PROJECT_ROOT
from .journal import TaskJournal, make_task_id, utc_now
from .revit_locator import infer_revit_version_from_model, resolve_revit_exe
from .safety import authorize, classify_action, validate_output_path
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


@dataclass
class OperationRequest:
    operation: str
    args: dict
    dry_run: bool = True
    approval_token: str | None = None
    allow_model_write: bool = False
    allow_sync: bool = False


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
    operation = request.operation.strip().lower()
    payload = {
        "operation": operation,
        "args": request.args,
        "allow_model_write": request.allow_model_write,
        "allow_sync": request.allow_sync,
    }
    decision = classify_action("request-operation", payload)
    allowed, reason = authorize(decision, request.approval_token)
    guard_error = _guard_operation(operation, request)

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

    result = {
        "success": False,
        "dry_run": request.dry_run,
        "command": command,
        "policy": decision.to_dict(),
        "authorization": {"allowed": allowed, "reason": reason},
        "bridge_queue": str(journal.sandbox / "bridge" / "command_queue.jsonl"),
    }
    if guard_error:
        result["error"] = guard_error
    elif request.dry_run:
        result["success"] = True
        result["next_step"] = _next_operation_step(decision.approval_token, operation)
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


def _next_operation_step(token: str | None, operation: str) -> str:
    flags = ["--execute"]
    if token:
        flags.extend(["--approval-token", token])
    if operation in MODEL_WRITE_OPERATIONS:
        flags.append("--allow-model-write")
    if operation in SYNC_OPERATIONS:
        flags.append("--allow-sync")
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
