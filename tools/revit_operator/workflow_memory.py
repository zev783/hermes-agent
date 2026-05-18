"""Sandboxed reusable workflow memory for Revit operator runs."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path, PureWindowsPath

from .constants import DRAFT_LABEL
from .journal import TaskJournal, utc_now
from .safety import BLOCK, authorize, classify_action, validate_output_path

EXECUTABLE_REPLAY_ACTIONS = {"focus", "press-key", "click", "type-text", "uia-invoke"}
EXECUTABLE_REPLAY_COMMANDS = EXECUTABLE_REPLAY_ACTIONS | {"request-operation"}
REPLAYABLE_RECORDED_STATES = {"idle", "modal"}
UNSAFE_RECORDED_REPLAY_STATES = {"busy", "unknown", "unsupported", "not_running"}
GENERIC_TITLE_TERMS = {
    "autodesk",
    "revit",
    "project",
    "browser",
    "properties",
    "family",
    "floor",
    "ceiling",
    "sheet",
    "view",
    "plan",
}
PARAMETER_CANDIDATE_KEYS = {
    "target",
    "text",
    "key",
    "name",
    "sheet_number",
    "view_name",
    "query",
}


def list_workflows(sandbox: Path) -> dict:
    library = _library_dir(sandbox)
    if not library.exists():
        return {"success": True, "library": str(library), "workflows": []}
    workflows = []
    for path in sorted(library.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            workflows.append({"path": str(path), "valid": False, "error": str(exc)})
            continue
        workflows.append(
            {
                "path": str(path),
                "valid": True,
                "name": data.get("name"),
                "source_task_id": data.get("source_task_id"),
                "created_at": data.get("created_at"),
                "step_count": data.get("step_count"),
            }
        )
    return {"success": True, "library": str(library), "workflows": workflows}


def record_workflow(
    sandbox: Path,
    *,
    source_task_id: str,
    name: str,
    description: str = "",
) -> dict:
    source_journal = sandbox / "revit_operator_runs" / source_task_id / "journal.jsonl"
    source_error = validate_output_path(source_journal, sandbox)
    if source_error:
        return {"success": False, "error": source_error}
    if not source_journal.exists():
        return {"success": False, "error": f"Source journal not found: {source_journal}"}

    records = _read_journal(source_journal)
    steps = [_workflow_step(record, index) for index, record in enumerate(records)]
    safe_name = _safe_name(name)
    target = _library_dir(sandbox) / f"{safe_name}.json"
    target_error = validate_output_path(target, sandbox)
    if target_error:
        return {"success": False, "error": target_error}
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-workflow-template/v1",
        "name": name,
        "description": description,
        "created_at": utc_now(),
        "source_task_id": source_task_id,
        "source_journal": str(source_journal),
        "step_count": len(steps),
        "parameters": _workflow_parameters(steps),
        "steps": steps,
        "replay_policy": {
            "requires_fresh_observation": True,
            "requires_fresh_safety_classification": True,
            "approval_tokens_are_not_recorded_or_reused": True,
            "parameter_overrides_are_reclassified": True,
            "model_writes_remain_blocked_or_approval_gated": True,
        },
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "success": True,
        "path": str(target),
        "name": name,
        "source_task_id": source_task_id,
        "step_count": len(steps),
    }


def plan_workflow_replay(
    sandbox: Path,
    *,
    name: str | None = None,
    path: Path | None = None,
    parameters: dict | None = None,
) -> dict:
    workflow_path = _resolve_workflow_path(sandbox, name=name, path=path)
    path_error = validate_output_path(workflow_path, sandbox)
    if path_error:
        return {"success": False, "error": path_error}
    if not workflow_path.exists():
        return {"success": False, "error": f"Workflow template not found: {workflow_path}"}

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    planned_steps = []
    approval_required = []
    blocked = []
    for index, step in enumerate(workflow.get("steps") or []):
        command = str(step.get("command") or "")
        payload = _payload_for_step(step, parameters or {})
        decision = classify_action(command, payload)
        planned = {
            "index": index,
            "command": command,
            "payload": payload,
            "parameter_bindings": step.get("parameter_bindings") or [],
            "policy": decision.to_dict(),
            "will_execute": False,
            "reason": "Replay planning is dry-run only; execute requires fresh observation and approval.",
        }
        planned_steps.append(planned)
        if decision.decision == "approval_required":
            approval_required.append(index)
        elif decision.decision == "block":
            blocked.append(index)

    return {
        "success": True,
        "path": str(workflow_path),
        "name": workflow.get("name"),
        "step_count": len(planned_steps),
        "parameters": workflow.get("parameters") or [],
        "parameter_overrides": parameters or {},
        "approval_required_steps": approval_required,
        "blocked_steps": blocked,
        "can_replay_without_human": not approval_required and not blocked,
        "planned_steps": planned_steps,
        "replay_policy": workflow.get("replay_policy", {}),
    }


def plan_workflow_approvals(
    sandbox: Path,
    journal: TaskJournal,
    *,
    name: str | None = None,
    path: Path | None = None,
    parameters: dict | None = None,
) -> dict:
    """Create a fresh approval package for a recorded workflow replay."""

    workflow_path = _resolve_workflow_path(sandbox, name=name, path=path)
    path_error = validate_output_path(workflow_path, sandbox)
    if path_error:
        return {"success": False, "error": path_error}
    if not workflow_path.exists():
        return {"success": False, "error": f"Workflow template not found: {workflow_path}"}

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    replay_plan = plan_workflow_replay(
        sandbox,
        name=name,
        path=path,
        parameters=parameters or {},
    )
    if not replay_plan.get("success"):
        return replay_plan

    approval_steps = []
    blocked_steps = []
    approval_tokens: dict[str, str] = {}
    for step in replay_plan.get("planned_steps") or []:
        policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
        decision = str(policy.get("decision") or "")
        index = int(step.get("index") or 0)
        if decision == "approval_required":
            token = str(policy.get("approval_token") or "")
            approval_tokens[str(index)] = token
            approval_steps.append(
                {
                    "index": index,
                    "command": step.get("command"),
                    "payload": step.get("payload"),
                    "risk": policy.get("risk"),
                    "reason": policy.get("reason"),
                    "approval_token": token,
                    "human_review_required": True,
                    "review_prompt": (
                        "Approve this exact replay step only if the fresh Revit observation still "
                        "matches the recorded state predicates and the payload is acceptable."
                    ),
                }
            )
        elif decision == BLOCK:
            blocked_steps.append(
                {
                    "index": index,
                    "command": step.get("command"),
                    "payload": step.get("payload"),
                    "risk": policy.get("risk"),
                    "reason": policy.get("reason"),
                }
            )

    output = journal.run_dir / "workflow_approval_plan.json"
    output_error = validate_output_path(output, sandbox)
    if output_error:
        return {"success": False, "error": output_error}

    replay_target_args = _workflow_target_args(name=name or workflow.get("name"), path=workflow_path if path else None)
    parameters_arg = _parameters_arg(parameters or {})
    replay_dry_run_command = " ".join(
        ["revit-operator", "replay-workflow", *replay_target_args, *parameters_arg]
    )
    replay_execute_command = " ".join(
        [
            "revit-operator",
            "replay-workflow",
            *replay_target_args,
            "--execute",
            "--approval-tokens-json",
            _quote_cli_arg(json.dumps(approval_tokens, sort_keys=True, separators=(",", ":"))),
            *parameters_arg,
        ]
    )

    result = {
        "success": True,
        "read_only": True,
        "dry_run_only": True,
        "path": str(output),
        "workflow_path": str(workflow_path),
        "name": workflow.get("name"),
        "step_count": replay_plan.get("step_count"),
        "parameter_overrides": parameters or {},
        "template_contains_approval_tokens": _contains_approval_token(workflow),
        "stale_approval_tokens_reused": False,
        "approval_required_count": len(approval_steps),
        "blocked_count": len(blocked_steps),
        "approval_steps": approval_steps,
        "blocked_steps": blocked_steps,
        "approval_tokens_json": approval_tokens,
        "can_execute_with_fresh_approvals": bool(approval_steps) and not blocked_steps,
        "can_replay_without_human": bool(replay_plan.get("can_replay_without_human")),
        "replay_dry_run_command": replay_dry_run_command,
        "replay_execute_command_requires_human": replay_execute_command if not blocked_steps else None,
        "safety_note": (
            "This approval plan does not execute replay steps. Tokens are regenerated from the "
            "current payload classification and are not read from the recorded workflow template."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "workflow-approval-plan",
            "requested_action": {
                "workflow": str(workflow_path),
                "parameters": parameters or {},
            },
            "risk_classification": classify_action("workflow-approval-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only workflow approval planning."},
            "result": {
                "status": "planned",
                "approval_required_count": len(approval_steps),
                "blocked_count": len(blocked_steps),
                "stale_approval_tokens_reused": False,
            },
            "output_files": [str(output)],
        }
    )
    return result


def replay_workflow(
    sandbox: Path,
    journal: TaskJournal,
    observer,
    *,
    name: str | None = None,
    path: Path | None = None,
    dry_run: bool = True,
    approval_tokens: dict[int, str] | None = None,
    parameters: dict | None = None,
    stop_on_modal: bool = True,
    max_steps: int | None = None,
    recovery_snapshot_on_stop: bool = True,
) -> dict:
    """Plan or execute a recorded workflow with fresh gates.

    Replay is deliberately narrower than the command surface. It never reuses
    old approvals, observes Revit before every step, and only executes guarded
    action primitives or bridge operation requests.
    """

    workflow_path = _resolve_workflow_path(sandbox, name=name, path=path)
    path_error = validate_output_path(workflow_path, sandbox)
    if path_error:
        return {"success": False, "error": path_error}
    if not workflow_path.exists():
        return {"success": False, "error": f"Workflow template not found: {workflow_path}"}

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    raw_steps = workflow.get("steps") or []
    if max_steps is not None:
        raw_steps = raw_steps[: max(0, max_steps)]
    tokens = approval_tokens or {}
    replay_steps = []
    executed_steps = []
    skipped_steps = []
    blocked_steps = []
    approval_required_steps = []
    stop_reason = None

    for index, step in enumerate(raw_steps):
        command = str(step.get("command") or "")
        payload = _payload_for_step(step, parameters or {})

        before = _fresh_status(sandbox, observer)
        before_state = str(before.get("state") or "unknown")
        state_gate = _state_gate(step, before, stop_on_modal=stop_on_modal)
        decision = classify_action(command, payload)
        token = tokens.get(index)
        allowed, auth_reason = authorize(decision, token)
        executable = command in EXECUTABLE_REPLAY_COMMANDS
        replay_step = {
            "index": index,
            "command": command,
            "payload": payload,
            "template_state_predicates": step.get("state_predicates") or {},
            "parameter_bindings": step.get("parameter_bindings") or [],
            "fresh_observation": before,
            "state_gate": state_gate,
            "policy": decision.to_dict(),
            "authorization": {"allowed": allowed, "reason": auth_reason},
            "executable": executable,
            "dry_run": dry_run,
            "executed": False,
        }

        if not state_gate["allowed"]:
            replay_step["status"] = "stopped_state_gate"
            replay_steps.append(replay_step)
            stop_reason = state_gate["reason"]
            break
        if not executable:
            replay_step["status"] = "skipped_non_executable"
            replay_step["reason"] = "Replay only executes guarded action primitives and request-operation."
            skipped_steps.append(index)
            replay_steps.append(replay_step)
            continue
        if decision.decision == BLOCK:
            replay_step["status"] = "blocked"
            blocked_steps.append(index)
            replay_steps.append(replay_step)
            stop_reason = decision.reason
            break
        if decision.decision == "approval_required":
            approval_required_steps.append(index)
        if dry_run:
            replay_step["status"] = "dry_run"
            replay_step["reason"] = "Dry-run only; execute requires fresh exact approval tokens where required."
            replay_steps.append(replay_step)
            continue
        if not allowed:
            replay_step["status"] = "stopped_approval_required"
            replay_steps.append(replay_step)
            stop_reason = auth_reason
            break

        execution = _execute_replay_step(journal, observer, command, payload, token)
        replay_step["execution"] = execution
        replay_step["executed"] = bool(execution.get("success"))
        replay_step["status"] = "executed" if replay_step["executed"] else "failed"
        replay_step["after_observation"] = _fresh_status(sandbox, observer)
        if replay_step["executed"]:
            executed_steps.append(index)
        else:
            stop_reason = execution.get("error") or "Replay step failed."
            replay_steps.append(replay_step)
            break
        replay_steps.append(replay_step)

    output = journal.run_dir / ("workflow_replay_plan.json" if dry_run else "workflow_replay_result.json")
    output_error = validate_output_path(output, sandbox)
    if output_error:
        return {"success": False, "error": output_error}

    recovery_snapshot = None
    if stop_reason and recovery_snapshot_on_stop:
        recovery_snapshot = _capture_replay_recovery_snapshot(sandbox, journal, observer)

    result = {
        "success": stop_reason is None,
        "dry_run": dry_run,
        "path": str(output),
        "workflow_path": str(workflow_path),
        "name": workflow.get("name"),
        "step_count": len(replay_steps),
        "executed_steps": executed_steps,
        "skipped_steps": skipped_steps,
        "approval_required_steps": approval_required_steps,
        "blocked_steps": blocked_steps,
        "stop_reason": stop_reason,
        "recovery_snapshot": recovery_snapshot,
        "replay_policy": {
            **(workflow.get("replay_policy") or {}),
            "fresh_observation_per_step": True,
            "only_guarded_primitives_execute": True,
            "approval_tokens_are_fresh_inputs_only": True,
            "parameter_overrides_are_reclassified": True,
            "stop_on_modal": stop_on_modal,
            "recovery_snapshot_on_stop": recovery_snapshot_on_stop,
        },
        "parameter_overrides": parameters or {},
        "steps": replay_steps,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "replay-workflow",
            "requested_action": {
                "workflow": str(workflow_path),
                "dry_run": dry_run,
                "max_steps": max_steps,
                "stop_on_modal": stop_on_modal,
            },
            "result": {
                "status": "dry_run" if dry_run else ("executed" if result["success"] else "stopped"),
                "success": result["success"],
                "executed_steps": executed_steps,
                "stop_reason": stop_reason,
            },
            "output_files": [str(output), *_recovery_output_files(recovery_snapshot)],
        }
    )
    return result


def _capture_replay_recovery_snapshot(sandbox: Path, journal: TaskJournal, observer) -> dict:
    try:
        from .bridge import RevitBridgeClient
        from .recovery import capture_recovery_snapshot

        return capture_recovery_snapshot(
            journal,
            observer,
            RevitBridgeClient(sandbox),
            capture_screenshot=True,
            capture_ui_tree=True,
            max_depth=2,
            bridge_result_limit=5,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"Recovery snapshot failed: {type(exc).__name__}: {exc}",
        }


def _recovery_output_files(recovery_snapshot: dict | None) -> list[str]:
    if not isinstance(recovery_snapshot, dict):
        return []
    files = []
    if recovery_snapshot.get("path"):
        files.append(str(recovery_snapshot["path"]))
    for item in recovery_snapshot.get("output_files") or []:
        files.append(str(item))
    return files


def _contains_approval_token(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_approval_token(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_approval_token(child) for child in value)
    return isinstance(value, str) and value.startswith("APPROVE:")


def _workflow_target_args(*, name: str | None, path: Path | None) -> list[str]:
    if path is not None:
        return ["--path", _quote_cli_arg(str(path))]
    if name:
        return ["--name", _quote_cli_arg(str(name))]
    return []


def _parameters_arg(parameters: dict) -> list[str]:
    if not parameters:
        return []
    return [
        "--parameters-json",
        _quote_cli_arg(json.dumps(parameters, sort_keys=True, separators=(",", ":"))),
    ]


def _quote_cli_arg(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _library_dir(sandbox: Path) -> Path:
    return sandbox / "revit_operator_workflows"


def _read_journal(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _workflow_step(record: dict, index: int) -> dict:
    classification = dict(record.get("risk_classification") or {})
    classification.pop("approval_token", None)
    requested_action = record.get("requested_action")
    if not isinstance(requested_action, dict):
        requested_action = {}
    return {
        "timestamp": record.get("timestamp"),
        "command": record.get("command"),
        "requested_action": requested_action,
        "parameter_bindings": _parameter_bindings(requested_action, index),
        "risk_classification": classification,
        "state_predicates": _state_predicates(record),
        "approval_status": record.get("approval_status"),
        "result": record.get("result"),
        "output_files": record.get("output_files", []),
    }


def _workflow_parameters(steps: list[dict]) -> list[dict]:
    parameters = []
    seen = set()
    for step in steps:
        for binding in step.get("parameter_bindings") or []:
            name = binding.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            parameters.append(
                {
                    "name": name,
                    "step_index": binding.get("step_index"),
                    "path": binding.get("path"),
                    "default": binding.get("default"),
                    "description": binding.get("description"),
                }
            )
    return parameters


def _parameter_bindings(payload: dict, step_index: int) -> list[dict]:
    bindings: list[dict] = []

    def visit(value, path: list[str]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, [*path, str(key)])
            return
        if not path or path[-1] not in PARAMETER_CANDIDATE_KEYS:
            return
        if not isinstance(value, str) or not value.strip():
            return
        parameter_name = _safe_parameter_name(f"step_{step_index}_{'_'.join(path)}")
        bindings.append(
            {
                "name": parameter_name,
                "step_index": step_index,
                "path": path,
                "default": value,
                "description": f"Override {'.'.join(path)} for recorded workflow step {step_index}.",
            }
        )

    visit(payload, [])
    return bindings


def _payload_for_step(step: dict, parameters: dict) -> dict:
    payload = step.get("requested_action")
    if not isinstance(payload, dict):
        payload = {}
    payload = copy.deepcopy(payload)
    for binding in step.get("parameter_bindings") or []:
        name = binding.get("name")
        if not name or name not in parameters:
            continue
        path = [str(part) for part in binding.get("path") or []]
        if not path:
            continue
        _set_payload_path(payload, path, parameters[name])
    return payload


def _set_payload_path(payload: dict, path: list[str], value) -> None:
    target = payload
    for key in path[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            return
        target = child
    target[path[-1]] = value


def _safe_parameter_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "parameter"


def _state_predicates(record: dict) -> dict:
    before = record.get("observed_ui_state_before_action")
    recorded_state = before.get("state") if isinstance(before, dict) else None
    command = str(record.get("command") or "")
    recorded_state = str(recorded_state).strip().lower() if recorded_state else None
    predicates = {
        "schema": "hermes-revit-replay-state-predicates/v2",
        "recorded_pre_state": recorded_state,
        "allowed_states": [recorded_state] if recorded_state in REPLAYABLE_RECORDED_STATES else [],
        "recorded_state_replayable": (
            recorded_state not in UNSAFE_RECORDED_REPLAY_STATES if recorded_state else True
        ),
        "reject_modal": recorded_state != "modal",
        "requires_fresh_observation": True,
        "source": "recorded_journal" if recorded_state else "default_replay_guard",
        "narrow_execution_required": command in EXECUTABLE_REPLAY_COMMANDS,
    }
    if recorded_state == "modal":
        dialog_context = _dialog_context(before)
        predicates["requires_modal_dialog"] = True
        if dialog_context:
            predicates["dialog"] = dialog_context
    elif recorded_state:
        predicates["requires_no_active_dialogs"] = True

    main_window = _main_window_context(before)
    if main_window:
        predicates["main_window"] = main_window

    document = _document_context(before)
    if document:
        predicates["document"] = document

    return predicates


def _state_gate(step: dict, before: dict, *, stop_on_modal: bool) -> dict:
    state = str(before.get("state") or "unknown").strip().lower()
    predicates = step.get("state_predicates") or {}
    checks = []

    if predicates.get("recorded_state_replayable") is False:
        recorded = predicates.get("recorded_pre_state") or "unknown"
        return {
            "allowed": False,
            "state": state,
            "reason": f"Workflow step was recorded from unreplayable Revit state {recorded!r}.",
            "checks": checks,
        }

    allowed_states = [
        str(value).strip().lower()
        for value in predicates.get("allowed_states") or []
        if str(value).strip()
    ]
    if allowed_states and state.lower() not in allowed_states:
        return {
            "allowed": False,
            "state": state,
            "reason": f"Fresh Revit state {state!r} does not match recorded allowed states {allowed_states}.",
            "checks": checks,
        }
    if allowed_states:
        checks.append({"name": "state", "expected": allowed_states, "actual": state, "passed": True})

    reject_modal = bool(predicates.get("reject_modal", True))
    if stop_on_modal and reject_modal and state == "modal":
        return {
            "allowed": False,
            "state": state,
            "reason": "Fresh observation is modal; replay stopped before action.",
            "checks": checks,
        }

    dialogs = _active_dialogs(before)
    if predicates.get("requires_no_active_dialogs") and dialogs:
        return {
            "allowed": False,
            "state": state,
            "reason": "Recorded step expected no active dialogs, but fresh observation has a dialog.",
            "checks": checks,
        }
    if predicates.get("requires_no_active_dialogs"):
        checks.append({"name": "active_dialogs_absent", "expected": 0, "actual": 0, "passed": True})

    if predicates.get("requires_modal_dialog"):
        if state != "modal" or not dialogs:
            return {
                "allowed": False,
                "state": state,
                "reason": "Recorded step expected a matching modal dialog, but none is active.",
                "checks": checks,
            }
        ok, reason, check = _check_dialog_predicate(predicates.get("dialog") or {}, dialogs)
        checks.append(check)
        if not ok:
            return {"allowed": False, "state": state, "reason": reason, "checks": checks}

    ok, reason, check = _check_main_window_predicate(predicates.get("main_window") or {}, before)
    if check:
        checks.append(check)
    if not ok:
        return {"allowed": False, "state": state, "reason": reason, "checks": checks}

    ok, reason, check = _check_document_predicate(predicates.get("document") or {}, before)
    if check:
        checks.append(check)
    if not ok:
        return {"allowed": False, "state": state, "reason": reason, "checks": checks}

    return {
        "allowed": True,
        "state": state,
        "reason": "Fresh observation passed replay state gate.",
        "checks": checks,
    }


def _fresh_status(sandbox: Path, observer) -> dict:
    status = observer.status()
    if not isinstance(status, dict):
        status = {"state": "unknown", "raw_status": status}
    status = _with_active_document(sandbox, status)
    if status.get("state") == "modal" and "dialog_details" not in status:
        try:
            status = {**status, "dialog_details": observer.list_dialogs()}
        except Exception as exc:
            status = {
                **status,
                "dialog_details": {
                    "supported": False,
                    "error": f"Dialog detail observation failed: {type(exc).__name__}: {exc}",
                    "dialogs": [],
                },
            }
    return status


def _with_active_document(sandbox: Path, status: dict) -> dict:
    if "active_document" in status:
        return status
    try:
        from .bridge import RevitBridgeClient

        active_document = RevitBridgeClient(sandbox).active_document_status()
    except Exception as exc:
        active_document = {
            "available": False,
            "status": "error",
            "error": f"Bridge active document read failed: {type(exc).__name__}: {exc}",
        }
    return {**status, "active_document": active_document}


def _active_dialogs(status: dict | None) -> list[dict]:
    if not isinstance(status, dict):
        return []
    detailed = status.get("dialog_details")
    if isinstance(detailed, dict):
        dialogs = detailed.get("dialogs")
        if isinstance(dialogs, list):
            return [dialog for dialog in dialogs if isinstance(dialog, dict)]
    dialogs = status.get("active_dialogs")
    if isinstance(dialogs, list):
        return [dialog for dialog in dialogs if isinstance(dialog, dict)]
    return []


def _dialog_context(status: dict | None) -> dict:
    dialogs = _active_dialogs(status)
    if not dialogs:
        return {}
    dialog = dialogs[0]
    title = _clean_text(dialog.get("title"))
    text = _clean_text(dialog.get("dialog_text") or dialog.get("text"))
    buttons = [
        _clean_text(button)
        for button in dialog.get("buttons") or []
        if _clean_text(button)
    ]
    context = {}
    if title:
        context["title"] = title
        context["title_terms"] = _identity_terms(title)
    if text:
        context["text_terms"] = _identity_terms(text, include_generic=True, limit=10)
    if buttons:
        context["buttons"] = buttons
    return context


def _main_window_context(status: dict | None) -> dict:
    if not isinstance(status, dict):
        return {}
    main = status.get("main_window")
    if not isinstance(main, dict):
        return {}
    context = {}
    title = _clean_text(main.get("title"))
    if title:
        terms = _identity_terms(title)
        if terms:
            context["title_terms"] = terms
    revit_version = _clean_text(main.get("revit_version"))
    if revit_version:
        context["revit_version"] = revit_version
    return context


def _document_context(status: dict | None) -> dict:
    document = _extract_document_payload(status)
    if not document:
        return {}
    context = {}
    title = _clean_text(document.get("title") or document.get("document_title"))
    path = _clean_text(document.get("path") or document.get("document_path"))
    revit_version = _clean_text(document.get("revit_version"))
    active_view = document.get("active_view")
    if title:
        context["title"] = title
    if path:
        context["path_basename"] = _path_basename(path)
    if revit_version:
        context["revit_version"] = revit_version
    if isinstance(active_view, dict):
        view = {}
        name = _clean_text(active_view.get("name"))
        view_type = _clean_text(active_view.get("type") or active_view.get("view_type"))
        if name:
            view["name"] = name
        if view_type:
            view["type"] = view_type
        if view:
            context["active_view"] = view
    return context


def _extract_document_payload(value) -> dict:
    if not isinstance(value, dict):
        return {}
    if _looks_like_document(value):
        return value
    for key in ("document", "active_document"):
        nested = value.get(key)
        found = _extract_document_payload(nested)
        if found:
            return found
    return {}


def _looks_like_document(value: dict) -> bool:
    return any(
        key in value
        for key in (
            "title",
            "document_title",
            "path",
            "document_path",
            "worksharing",
            "central_path",
            "dirty",
            "active_view",
        )
    )


def _check_dialog_predicate(predicate: dict, dialogs: list[dict]) -> tuple[bool, str, dict]:
    if not predicate:
        return True, "No recorded dialog identity predicate.", {
            "name": "dialog_identity",
            "expected": {},
            "actual": len(dialogs),
            "passed": True,
        }

    actual_titles = [_clean_text(dialog.get("title")) for dialog in dialogs]
    expected_title = _clean_text(predicate.get("title"))
    expected_terms = [str(term).lower() for term in predicate.get("title_terms") or []]
    expected_buttons = [_button_label(button) for button in predicate.get("buttons") or []]
    expected_text_terms = [str(term).lower() for term in predicate.get("text_terms") or []]

    candidates = dialogs
    if expected_title:
        candidates = [
            dialog
            for dialog in candidates
            if _clean_text(dialog.get("title")).lower() == expected_title.lower()
        ]
    elif expected_terms:
        candidates = [
            dialog
            for dialog in candidates
            if _contains_terms(_clean_text(dialog.get("title")), expected_terms)
        ]
    if not candidates:
        return False, "Fresh modal dialog does not match recorded dialog title.", {
            "name": "dialog_identity",
            "expected_title": expected_title,
            "expected_title_terms": expected_terms,
            "actual_titles": actual_titles,
            "passed": False,
        }

    if expected_buttons:
        button_candidates = []
        for dialog in candidates:
            actual_buttons = {_button_label(button) for button in dialog.get("buttons") or []}
            if all(button in actual_buttons for button in expected_buttons):
                button_candidates.append(dialog)
        if not button_candidates:
            return False, "Fresh modal dialog buttons do not match recorded dialog.", {
                "name": "dialog_buttons",
                "expected": expected_buttons,
                "actual": [dialog.get("buttons") or [] for dialog in candidates],
                "passed": False,
            }
        candidates = button_candidates

    if expected_text_terms:
        text_candidates = [
            dialog
            for dialog in candidates
            if _contains_terms(_clean_text(dialog.get("dialog_text") or dialog.get("text")), expected_text_terms)
        ]
        if not text_candidates:
            return False, "Fresh modal dialog text does not match recorded dialog.", {
                "name": "dialog_text",
                "expected_terms": expected_text_terms,
                "passed": False,
            }

    return True, "Fresh modal dialog matches recorded predicate.", {
        "name": "dialog_identity",
        "expected_title": expected_title,
        "actual_titles": actual_titles,
        "passed": True,
    }


def _check_main_window_predicate(predicate: dict, status: dict) -> tuple[bool, str, dict | None]:
    if not predicate:
        return True, "No recorded main-window predicate.", None
    main = status.get("main_window") if isinstance(status, dict) else None
    if not isinstance(main, dict):
        return False, "Recorded step expected a Revit main window, but none is visible.", {
            "name": "main_window",
            "expected": predicate,
            "actual": None,
            "passed": False,
        }
    expected_version = _clean_text(predicate.get("revit_version"))
    actual_version = _clean_text(main.get("revit_version"))
    if expected_version and expected_version != actual_version:
        return False, "Fresh Revit version does not match recorded main-window version.", {
            "name": "main_window_revit_version",
            "expected": expected_version,
            "actual": actual_version,
            "passed": False,
        }
    expected_terms = [str(term).lower() for term in predicate.get("title_terms") or []]
    actual_title = _clean_text(main.get("title"))
    if expected_terms and not _contains_terms(actual_title, expected_terms):
        return False, "Fresh Revit main-window title does not match recorded workflow context.", {
            "name": "main_window_title",
            "expected_terms": expected_terms,
            "actual": actual_title,
            "passed": False,
        }
    return True, "Fresh main window matches recorded predicate.", {
        "name": "main_window",
        "expected": predicate,
        "actual": {"title": actual_title, "revit_version": actual_version},
        "passed": True,
    }


def _check_document_predicate(predicate: dict, status: dict) -> tuple[bool, str, dict | None]:
    if not predicate:
        return True, "No recorded document predicate.", None
    actual = _document_context(status)
    if not actual:
        return False, "Recorded step expected active document context, but the bridge did not provide it.", {
            "name": "active_document",
            "expected": predicate,
            "actual": None,
            "passed": False,
        }
    for key in ("title", "path_basename", "revit_version"):
        expected = _clean_text(predicate.get(key))
        actual_value = _clean_text(actual.get(key))
        if expected and expected.lower() != actual_value.lower():
            return False, f"Fresh active document {key} does not match recorded workflow context.", {
                "name": f"active_document_{key}",
                "expected": expected,
                "actual": actual_value,
                "passed": False,
            }
    expected_view = predicate.get("active_view")
    actual_view = actual.get("active_view")
    if isinstance(expected_view, dict):
        if not isinstance(actual_view, dict):
            return False, "Recorded step expected active view context, but fresh context has none.", {
                "name": "active_view",
                "expected": expected_view,
                "actual": None,
                "passed": False,
            }
        for key in ("name", "type"):
            expected = _clean_text(expected_view.get(key))
            actual_value = _clean_text(actual_view.get(key))
            if expected and expected.lower() != actual_value.lower():
                return False, f"Fresh active view {key} does not match recorded workflow context.", {
                    "name": f"active_view_{key}",
                    "expected": expected,
                    "actual": actual_value,
                    "passed": False,
                }
    return True, "Fresh active document matches recorded predicate.", {
        "name": "active_document",
        "expected": predicate,
        "actual": actual,
        "passed": True,
    }


def _clean_text(value) -> str:
    return str(value or "").replace("&", "").strip()


def _identity_terms(value: str, *, include_generic: bool = False, limit: int = 8) -> list[str]:
    terms = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,}", value.lower()):
        normalized = token.strip("_.-")
        if len(normalized) < 3:
            continue
        if not include_generic and normalized in GENERIC_TITLE_TERMS:
            continue
        if normalized not in terms:
            terms.append(normalized)
        if len(terms) >= limit:
            break
    return terms


def _contains_terms(value: str, terms: list[str]) -> bool:
    normalized = value.lower()
    return all(term in normalized for term in terms)


def _path_basename(value: str) -> str:
    if "\\" in value:
        return PureWindowsPath(value).name
    return Path(value).name


def _button_label(value: str) -> str:
    return _clean_text(value).lower()


def _execute_replay_step(
    journal: TaskJournal,
    observer,
    command: str,
    payload: dict,
    approval_token: str | None,
) -> dict:
    if command in EXECUTABLE_REPLAY_ACTIONS:
        from .actions import ActionRequest, SafeActionExecutor

        return SafeActionExecutor(observer, journal).run(
            ActionRequest(
                action=command,
                payload=payload,
                dry_run=False,
                approval_token=approval_token,
            )
        )
    if command == "request-operation":
        from .operations import OperationRequest, queue_operation

        return queue_operation(
            journal,
            OperationRequest(
                operation=str(payload.get("operation") or ""),
                args=payload.get("args") if isinstance(payload.get("args"), dict) else {},
                dry_run=False,
                approval_token=approval_token,
                allow_model_write=bool(payload.get("allow_model_write")),
                allow_sync=bool(payload.get("allow_sync")),
            ),
        )
    return {"success": False, "error": f"Command {command!r} is not replay-executable."}


def _safe_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip(".-")
    return normalized or "workflow"


def _resolve_workflow_path(
    sandbox: Path,
    *,
    name: str | None,
    path: Path | None,
) -> Path:
    if path is not None:
        return path if path.is_absolute() else sandbox / path
    if not name:
        raise ValueError("Either name or path is required.")
    candidate = _library_dir(sandbox) / f"{_safe_name(name)}.json"
    if candidate.exists():
        return candidate
    return _library_dir(sandbox) / name
