"""General Revit agent session planning and completion gating."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .actions import ActionRequest, SafeActionExecutor
from .bridge import RevitBridgeClient
from .constants import DRAFT_LABEL, SAFE_PROJECT_ROOT
from .journal import TaskJournal, utc_now
from .operations import OperationRequest, open_model, queue_operation
from .readiness import wait_model_ready
from .safety import APPROVAL_REQUIRED, BLOCK, classify_action, validate_output_path
from .session_checkpoint import build_agent_session_resume_plan, write_agent_session_checkpoint
from .supervision import audit_supervision_endurance, build_supervision_status, supervise_session
from .uia import uia_tree
from .ui_workflows import UI_WORKFLOWS, run_ui_workflow
from .windows import RevitWindowObserver


AGENT_REQUIREMENTS = [
    {
        "id": "arbitrary-ui-flows",
        "requirement": "Autonomously handle arbitrary Revit UI flows.",
        "success_criteria": [
            "Plan unknown UI work without guessing.",
            "Route known UI flows through reusable recipes.",
            "Use fresh observation before every UI step.",
            "Execute approval-gated UI actions only with exact fresh approval tokens.",
            "Record before/after evidence for each executed UI step.",
        ],
    },
    {
        "id": "approved-model-changing-work",
        "requirement": "Execute approved model-changing work.",
        "success_criteria": [
            "Classify every model-changing request as approval-required or blocked.",
            "Require explicit allow-model-write and, for sync, allow-sync guards.",
            "Use Revit bridge/API operations on the Revit thread where available.",
            "Capture the approval token, command payload, result, and final model state.",
            "Never save, sync, publish, or write production files without the matching guard.",
        ],
    },
    {
        "id": "model-open-prompt-choreography",
        "requirement": "Handle full model-open prompt choreography.",
        "success_criteria": [
            "Choose the correct Revit version from model/version hints.",
            "Open only copied local models from the allowed area.",
            "Detect upgrade, detach, workset, link, and unsigned add-in prompts.",
            "Classify each prompt and stop for human approval where risk is high.",
            "Verify the active document after the open completes.",
        ],
    },
    {
        "id": "multi-hour-task-planning",
        "requirement": "Plan and supervise multi-hour Revit tasks.",
        "success_criteria": [
            "Persist a session plan, checkpoints, and resume instructions in the sandbox.",
            "Run periodic observation/supervision without destructive action.",
            "Stop on modal dialogs, busy stalls, unknown state, or failed evidence gates.",
            "Produce a final audit that maps the user objective to concrete artifacts.",
            "Refuse to report completion until every success criterion has evidence.",
        ],
    },
]


INTENT_PATTERNS = {
    "model_open": r"\bopen\b.*\b(model|rvt)\b|\bupgrade\b|\bdetach\b|\bworksets?\b",
    "ui_flow": (
        r"\bui\b|\bdialog\b|\bribbon\b|\bcontext menu\b|\bproject browser\b|"
        r"\bmanage links\b|\bvisibility/?graphics\b|\bview templates?\b|"
        r"\bfamily load\b|\btype catalog\b|\bwarnings?\b"
    ),
    "model_change": (
        r"\breload\b.*\blinks?\b|\brepath\b|\bupdate parameters?\b|\bplace\b|"
        r"\bcreate\b|\bmodify\b|\bdelete\b|\bsave\b|\bsync\b|\bsynchroni[sz]e\b"
    ),
    "long_running": r"\bhours?\b|\bmulti-hour\b|\blong[- ]running\b|\bbatch\b|\ball sheets?\b|\ball drawings?\b",
}


WORKFLOW_HINTS = {
    "unsigned-addin-startup-preflight": ["unsigned", "add-in", "addin", "startup", "security"],
    "bridge-readiness-gate": ["bridge", "addin", "add-in", "loaded", "readiness"],
    "project-browser-open-sheet": ["project browser", "sheet", "drawing", "view"],
    "manage-links-inspection": ["manage links", "links", "reload", "repath"],
    "review-warnings-inspection": ["warning", "warnings", "review warnings"],
    "visibility-graphics-inspection": ["visibility", "graphics", "visibility/graphics", "vg"],
    "view-template-inspection": ["view template", "view templates"],
    "context-menu-inspect-target": ["context menu", "right click", "right-click"],
    "modal-dialog-recovery": ["modal", "dialog", "stuck", "recovery"],
    "readonly-qa-pass": ["qa", "qc", "quality", "inspect", "report"],
}


MODEL_CHANGE_OPERATIONS = {
    "reload-links": r"\breload\b.*\blinks?\b|\brepath\b.*\blinks?",
    "set-project-info-parameter": r"\bupdate parameters?\b|\bproject info\b",
    "activate-view": r"\bactivate\b.*\b(view|sheet)\b|\bopen\b.*\bsheet\b",
    "save": r"\bsave\b",
    "sync": r"\bsync\b|\bsynchroni[sz]e\b",
    "delete": r"\bdelete\b",
}


UI_SCOUT_KNOWN_PHRASES = [
    "manage links",
    "review warnings",
    "visibility/graphics",
    "visibility graphics",
    "view templates",
    "project browser",
    "properties palette",
    "family load",
    "type catalog",
    "worksets",
    "reload links",
    "temporary hide",
    "temporary isolate",
    "sheet list",
]


UI_SCOUT_STOP_WORDS = {
    "about",
    "after",
    "again",
    "all",
    "also",
    "and",
    "any",
    "are",
    "around",
    "before",
    "current",
    "find",
    "for",
    "from",
    "handle",
    "hermes",
    "into",
    "like",
    "model",
    "need",
    "next",
    "open",
    "operate",
    "please",
    "revit",
    "should",
    "show",
    "that",
    "the",
    "then",
    "this",
    "through",
    "use",
    "using",
    "what",
    "when",
    "where",
    "with",
    "without",
}


DEFAULT_AGENT_COMPLETION_OBJECTIVE = (
    "have revit autonomously handle arbitrary ui flows, approved model-changing work, "
    "full model-open prompt choreography and multi-hour task planning"
)


def plan_agent_session(
    journal: TaskJournal,
    *,
    objective: str,
    model_path: str = "",
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    max_hours: float = 4.0,
    parameters: dict | None = None,
) -> dict:
    """Create a durable, non-executing plan for a broad Revit agent session."""

    started_at = utc_now()
    objective_text = " ".join(str(objective or "").split())
    parameters = {str(key): str(value) for key, value in (parameters or {}).items()}
    intents = _detect_intents(objective_text)
    candidate_workflows = _candidate_workflow_plans(objective_text, parameters)
    model_change_requests = _model_change_requests(objective_text, parameters)
    phases = _build_phases(
        objective_text=objective_text,
        intents=intents,
        candidate_workflows=candidate_workflows,
        model_change_requests=model_change_requests,
        model_path=model_path,
        expected_revit_version=expected_revit_version,
        expected_title_contains=expected_title_contains,
        max_hours=max_hours,
        parameters=parameters,
    )
    requirements = _requirement_coverage(intents, candidate_workflows, model_change_requests)
    checklist = _prompt_to_artifact_checklist(requirements, phases)
    blockers = _completion_blockers(requirements, checklist)

    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-plan/v1",
        "created_at": started_at,
        "objective": objective_text,
        "intents": intents,
        "parameters": parameters,
        "model_path": model_path,
        "expectations": {
            "expected_revit_version": expected_revit_version,
            "expected_title_contains": expected_title_contains,
            "max_hours": max_hours,
        },
        "requirements": requirements,
        "phases": phases,
        "candidate_ui_workflows": candidate_workflows,
        "model_change_requests": model_change_requests,
        "prompt_to_artifact_checklist": checklist,
        "completion_blockers": blockers,
        "goal_complete": False,
        "may_call_update_goal": False,
        "reason": "This is a durable plan only; live execution and coverage evidence are still required.",
        "safety_summary": {
            "model_write_performed": False,
            "save_sync_publish_performed": False,
            "production_write_performed": False,
            "approval_required_actions_executed": False,
        },
        "journal": journal.describe(),
    }

    plan_path = journal.run_dir / "agent_session_plan.json"
    checklist_path = journal.run_dir / "agent_session_checklist.json"
    md_path = journal.run_dir / "agent_session_plan.md"
    _write_json(plan_path, journal.sandbox, result)
    _write_json(checklist_path, journal.sandbox, {"checklist": checklist, "completion_blockers": blockers})
    _write_text(md_path, journal.sandbox, _plan_markdown(result))
    result["path"] = str(plan_path)
    result["checklist_path"] = str(checklist_path)
    result["markdown_path"] = str(md_path)
    result["output_files"] = [str(plan_path), str(checklist_path), str(md_path)]

    journal.write_entry(
        {
            "command": "agent-session-plan",
            "requested_action": {"objective": objective_text},
            "risk_classification": classify_action("agent-session-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Planning only; no Revit action executed."},
            "result": {
                "status": "planned",
                "success": True,
                "goal_complete": False,
                "blocker_count": len(blockers),
            },
            "output_files": result["output_files"],
        }
    )
    return result


def run_agent_session(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    objective: str,
    model_path: str = "",
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    max_hours: float = 4.0,
    parameters: dict | None = None,
    run_open_dry_run: bool = True,
    bridge_refresh_timeout: float = 10.0,
    supervision_duration: float = 0.0,
    supervision_poll: float = 5.0,
    supervision_max_checks: int | None = None,
) -> dict:
    """Execute the safe/read-only portions of a broad agent session plan."""

    started_at = utc_now()
    plan = plan_agent_session(
        journal,
        objective=objective,
        model_path=model_path,
        expected_revit_version=expected_revit_version,
        expected_title_contains=expected_title_contains,
        max_hours=max_hours,
        parameters=parameters or {},
    )
    output_files = list(plan.get("output_files") or [])
    steps: list[dict] = []

    initial_status = observer.status()
    active_dialogs = initial_status.get("active_dialogs") or []
    steps.append(
        {
            "step": "observe-status",
            "success": True,
            "state": initial_status.get("state"),
            "active_dialog_count": len(active_dialogs),
            "main_window": initial_status.get("main_window"),
        }
    )
    dialogs = observer.list_dialogs()
    steps.append(
        {
            "step": "list-dialogs",
            "success": bool(dialogs.get("supported", True)),
            "dialog_count": len(dialogs.get("dialogs") or []),
            "dialogs": dialogs.get("dialogs") or [],
        }
    )

    if active_dialogs:
        status = "stopped_on_modal"
        reason = "Active Revit dialog is present; only observation was performed."
    else:
        bridge_status = bridge.bridge_status()
        steps.append(
            {
                "step": "bridge-status",
                "success": True,
                "available": bool(bridge_status.get("available")),
                "status": bridge_status.get("status"),
                "bridge": bridge_status,
            }
        )
        loaded_build = bridge.verify_loaded_build()
        steps.append(
            {
                "step": "verify-bridge-build",
                "success": bool(loaded_build.get("success")),
                "status": loaded_build.get("status"),
                "loaded_build": loaded_build,
            }
        )
        if model_path and run_open_dry_run:
            try:
                open_dry_run = open_model(
                    Path(model_path),
                    journal,
                    revit_version=expected_revit_version or None,
                    dry_run=True,
                )
            except (FileNotFoundError, ValueError, OSError) as exc:
                open_dry_run = {
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "dry_run": True,
                }
            steps.append({"step": "open-model-dry-run", **_without_approval_tokens(open_dry_run)})
        active_document_refresh = queue_operation(
            journal,
            OperationRequest(operation="active-document", args={}, dry_run=False),
        )
        active_document_step = {
            "step": "bridge-active-document-refresh",
            "queued": active_document_refresh.get("success"),
            "queue_result": _without_approval_tokens(active_document_refresh),
        }
        command_id = active_document_refresh.get("command", {}).get("id")
        if active_document_refresh.get("success") and command_id:
            active_document_step["wait_result"] = bridge.wait_for_command_result(
                command_id,
                timeout=bridge_refresh_timeout,
                poll=1,
            )
            active_document_step["success"] = bool(active_document_step["wait_result"].get("success"))
        else:
            active_document_step["success"] = False
            active_document_step["error"] = active_document_refresh.get("error") or "Bridge command was not queued."
        steps.append(active_document_step)
        readiness = wait_model_ready(
            journal,
            observer,
            bridge,
            timeout=0,
            poll=1,
            expected_title_contains=expected_title_contains,
            expected_revit_version=expected_revit_version,
        )
        if readiness.get("path"):
            output_files.append(str(readiness["path"]))
        steps.append({"step": "wait-model-ready-check", **readiness})
        if supervision_duration > 0:
            supervision = supervise_session(
                journal,
                observer,
                bridge,
                duration=supervision_duration,
                poll=supervision_poll,
                max_checks=supervision_max_checks,
                stop_on_modal=True,
            )
            if supervision.get("path"):
                output_files.append(str(supervision["path"]))
            steps.append({"step": "supervise-session", **supervision})
        status = "stopped_at_approval_gates"
        reason = "Read-only session preflight ran; approval-gated UI/model-changing phases were not executed."

    result = {
        "success": True,
        "read_only": True,
        "planned_only": False,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-run/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "reason": reason,
        "objective": plan.get("objective"),
        "plan": plan,
        "steps": steps,
        "output_files": _dedupe(output_files),
        "goal_complete": False,
        "may_call_update_goal": False,
        "safety_summary": {
            "model_write_performed": False,
            "save_sync_publish_performed": False,
            "production_write_performed": False,
            "approval_required_actions_executed": False,
        },
        "journal": journal.describe(),
    }
    run_path = journal.run_dir / "agent_session_run.json"
    md_path = journal.run_dir / "agent_session_run.md"
    result["path"] = str(run_path)
    result["markdown_path"] = str(md_path)
    result["output_files"] = _dedupe([*result["output_files"], str(run_path), str(md_path)])
    _write_json(run_path, journal.sandbox, _without_approval_tokens(result))
    _write_text(md_path, journal.sandbox, _run_markdown(result))
    journal.write_entry(
        {
            "command": "agent-session-run",
            "requested_action": {"objective": result.get("objective")},
            "risk_classification": classify_action("agent-session-run", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only execution of safe session phases."},
            "result": {
                "status": result["status"],
                "success": True,
                "goal_complete": False,
                "step_count": len(steps),
            },
            "output_files": result["output_files"],
        }
    )
    return _without_approval_tokens(result)


def build_agent_session_completion_audit(
    journal: TaskJournal,
    *,
    objective: str = DEFAULT_AGENT_COMPLETION_OBJECTIVE,
    artifact_root: Path | None = None,
    max_artifacts: int = 500,
    target_hours: float = 4.0,
) -> dict:
    """Audit current sandbox evidence against the broad Revit-agent objective."""

    started_at = utc_now()
    objective_text = " ".join(str(objective or DEFAULT_AGENT_COMPLETION_OBJECTIVE).split())
    root = artifact_root or journal.sandbox
    path_error = validate_output_path(root, journal.sandbox)
    if path_error:
        return {
            "success": False,
            "error": path_error,
            "goal_complete": False,
            "may_call_update_goal": False,
            "completion_allowed": False,
        }

    audit_path = journal.run_dir / "agent_session_completion_audit.json"
    md_path = journal.run_dir / "agent_session_completion_audit.md"
    inventory = _completion_artifact_inventory(root, journal.sandbox, max_artifacts=max_artifacts)
    artifacts = inventory.pop("_loaded_artifacts", [])
    checklist = _completion_checklist(
        artifacts,
        audit_path=audit_path,
        objective=objective_text,
        target_hours=target_hours,
    )
    requirement_summaries = _completion_requirement_summaries(checklist)
    hard_gates = _completion_hard_gates(artifacts, target_hours=target_hours)
    blocked_items = [
        {
            "id": row["id"],
            "requirement_id": row["requirement_id"],
            "reason": row["gap"],
        }
        for row in checklist
        if not row.get("satisfied")
    ]
    blocked_gates = [gate for gate in hard_gates if not gate.get("passed")]
    goal_complete = not blocked_items and not blocked_gates
    next_commands = _completion_next_commands(objective_text, target_hours=target_hours)
    command_checks = [_completion_command_check(command) for command in next_commands]
    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-completion-audit/v1",
        "created_at": started_at,
        "objective": objective_text,
        "concrete_deliverables": AGENT_REQUIREMENTS,
        "artifact_root": str(root),
        "artifact_inventory": inventory,
        "prompt_to_artifact_checklist": checklist,
        "requirement_summaries": requirement_summaries,
        "hard_completion_gates": hard_gates,
        "blocked_items": blocked_items,
        "blocked_gates": blocked_gates,
        "blocked_count": len(blocked_items) + len(blocked_gates),
        "status": "complete" if goal_complete else "incomplete",
        "reason": (
            "Every strict Revit-agent completion criterion has current sandbox evidence."
            if goal_complete
            else "The objective is not complete; one or more live evidence gates are missing."
        ),
        "goal_complete": goal_complete,
        "completion_allowed": goal_complete,
        "may_call_update_goal": goal_complete,
        "audit_rules": {
            "proxy_signals_are_insufficient": True,
            "tests_or_manifests_alone_do_not_authorize_completion": True,
            "private_approval_material_is_not_copied_into_public_audit": True,
            "uncertainty_counts_as_incomplete": True,
        },
        "next_recommended_commands": next_commands,
        "next_command_checks": command_checks,
        "next_commands_are_read_only": all(check["read_only"] for check in command_checks),
        "path": str(audit_path),
        "markdown_path": str(md_path),
        "output_files": [str(audit_path), str(md_path)],
        "journal": journal.describe(),
    }
    sanitized = _without_approval_tokens(result)
    _write_json(audit_path, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _completion_audit_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-session-completion-audit",
            "requested_action": {
                "objective": objective_text,
                "artifact_root": str(root),
                "target_hours": target_hours,
            },
            "risk_classification": classify_action("agent-session-completion-audit", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only completion evidence audit."},
            "result": {
                "status": result["status"],
                "blocked_count": result["blocked_count"],
                "goal_complete": goal_complete,
                "may_call_update_goal": goal_complete,
            },
            "output_files": result["output_files"],
        }
    )
    return sanitized


def build_agent_session_real_gate_ledger(
    journal: TaskJournal,
    *,
    objective: str = DEFAULT_AGENT_COMPLETION_OBJECTIVE,
    artifact_root: Path | None = None,
    max_artifacts: int = 500,
    target_hours: float = 4.0,
    refresh_supervision_status: bool = True,
) -> dict:
    """Write a read-only ledger of real-world gates that still block completion."""

    started_at = utc_now()
    objective_text = " ".join(str(objective or DEFAULT_AGENT_COMPLETION_OBJECTIVE).split())
    root = artifact_root or journal.sandbox
    path_error = validate_output_path(root, journal.sandbox)
    if path_error:
        return {
            "success": False,
            "error": path_error,
            "goal_complete": False,
            "may_call_update_goal": False,
            "completion_allowed": False,
            "may_execute_from_this_result": False,
        }

    supervision_status = None
    if refresh_supervision_status:
        supervision_status = build_supervision_status(
            journal,
            target_hours=target_hours,
            require_live_window=True,
        )

    completion = build_agent_session_completion_audit(
        journal,
        objective=objective_text,
        artifact_root=root,
        max_artifacts=max_artifacts,
        target_hours=target_hours,
    )
    if not completion.get("success"):
        return {
            "success": False,
            "error": completion.get("error") or "completion audit failed",
            "completion_audit": completion,
            "goal_complete": False,
            "may_call_update_goal": False,
            "completion_allowed": False,
            "may_execute_from_this_result": False,
        }

    gates = [
        _real_gate_ledger_row(gate, objective=objective_text, target_hours=target_hours)
        for gate in completion.get("hard_completion_gates", [])
    ]
    blocked_gates = [gate for gate in gates if not gate.get("passed")]
    ready_gates = [
        gate
        for gate in blocked_gates
        if gate.get("status") == "ready_for_human_or_real_condition"
    ]
    missing_readiness_gates = [
        gate
        for gate in blocked_gates
        if gate.get("status") == "blocked_missing_readiness_evidence"
    ]
    next_actions = [
        action
        for gate in blocked_gates
        for action in gate.get("next_read_only_actions", [])
    ]
    goal_complete = bool(completion.get("goal_complete"))
    status = (
        "completion_ready"
        if goal_complete
        else "waiting_on_human_or_real_conditions"
        if ready_gates
        else "blocked_missing_readiness_evidence"
    )
    output = journal.run_dir / "agent_session_real_gate_ledger.json"
    md_path = journal.run_dir / "agent_session_real_gate_ledger.md"
    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-real-gate-ledger/v1",
        "created_at": started_at,
        "objective": objective_text,
        "artifact_root": str(root),
        "status": status,
        "reason": (
            "Strict completion audit says all real gates are satisfied."
            if goal_complete
            else "One or more real approval, prompt, model-change, or endurance gates still lack live evidence."
        ),
        "completion_audit": {
            "path": completion.get("path"),
            "status": completion.get("status"),
            "blocked_count": completion.get("blocked_count"),
            "goal_complete": completion.get("goal_complete"),
            "may_call_update_goal": completion.get("may_call_update_goal"),
        },
        "supervision_status": _supervision_status_summary(supervision_status),
        "gate_summary": {
            "total": len(gates),
            "passed": len([gate for gate in gates if gate.get("passed")]),
            "ready_for_human_or_real_condition": len(ready_gates),
            "blocked_missing_readiness_evidence": len(missing_readiness_gates),
            "blocked": len(blocked_gates),
        },
        "real_gates": gates,
        "pending_real_conditions": [
            gate.get("next_required_real_condition")
            for gate in blocked_gates
            if gate.get("next_required_real_condition")
        ],
        "next_read_only_actions": next_actions,
        "next_actions_are_read_only": all(action.get("read_only") for action in next_actions),
        "execution_guard": {
            "may_execute_from_this_result": False,
            "approval_tokens_included": False,
            "approval_phrases_included": False,
            "private_approval_material_withheld": True,
            "requires_fresh_human_confirmation_for_execution": True,
            "requires_fresh_pre_action_observation": True,
            "completion_authority": "agent-session-completion-audit",
        },
        "goal_complete": goal_complete,
        "completion_allowed": bool(completion.get("completion_allowed")),
        "may_call_update_goal": bool(completion.get("may_call_update_goal")),
        "path": str(output),
        "markdown_path": str(md_path),
        "output_files": _dedupe(
            [
                str(output),
                str(md_path),
                completion.get("path"),
                completion.get("markdown_path"),
                *((supervision_status or {}).get("output_files") or []),
            ]
        ),
        "journal": journal.describe(),
    }
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _real_gate_ledger_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-session-real-gate-ledger",
            "requested_action": {
                "objective": objective_text,
                "artifact_root": str(root),
                "target_hours": target_hours,
                "refresh_supervision_status": refresh_supervision_status,
            },
            "risk_classification": classify_action("agent-session-real-gate-ledger", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only real-gate ledger only."},
            "result": {
                "status": result["status"],
                "blocked_gates": result["gate_summary"]["blocked"],
                "goal_complete": goal_complete,
                "may_call_update_goal": result["may_call_update_goal"],
                "may_execute_from_this_result": False,
            },
            "output_files": result["output_files"],
        }
    )
    return sanitized


def refresh_agent_session_evidence(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    objective: str = DEFAULT_AGENT_COMPLETION_OBJECTIVE,
    model_path: str = "",
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    max_hours: float = 4.0,
    parameters: dict | None = None,
    include_uia: bool = False,
    ui_limit: int = 20,
    max_artifacts: int = 500,
) -> dict:
    """Run all non-executing evidence collectors that can advance the agent goal."""

    from .model_open_choreography import build_model_open_prompt_approval_plan, run_model_open_choreography

    started_at = utc_now()
    objective_text = " ".join(str(objective or DEFAULT_AGENT_COMPLETION_OBJECTIVE).split())
    parameters = {str(key): str(value) for key, value in (parameters or {}).items()}
    steps: list[dict] = []
    output_files: list[str] = []

    def add_step(step_id: str, result: dict) -> dict:
        sanitized = _without_approval_tokens(result)
        steps.append(
            {
                "id": step_id,
                "status": sanitized.get("status") or sanitized.get("stop_reason"),
                "success": sanitized.get("success"),
                "read_only": sanitized.get("read_only", True),
                "goal_complete": sanitized.get("goal_complete", False),
                "may_call_update_goal": sanitized.get("may_call_update_goal", False),
                "path": sanitized.get("path"),
                "markdown_path": sanitized.get("markdown_path"),
                "output_files": sanitized.get("output_files") or [
                    value
                    for key, value in sanitized.items()
                    if key in {"path", "markdown_path", "private_material_path"} and isinstance(value, str)
                ],
            }
        )
        output_files.extend(value for value in steps[-1]["output_files"] if isinstance(value, str))
        return sanitized

    checkpoint = add_step(
        "agent-session-checkpoint",
        write_agent_session_checkpoint(
            journal,
            observer,
            bridge,
            objective=objective_text,
            expected_revit_version=expected_revit_version,
            expected_title_contains=expected_title_contains,
            expected_path_contains=expected_path_contains,
        ),
    )
    add_step(
        "agent-session-resume-plan",
        build_agent_session_resume_plan(
            journal,
            checkpoint_path=Path(checkpoint["path"]) if checkpoint.get("path") else None,
            resume_minutes=max(1.0, min(max_hours * 60.0, 60.0)),
        ),
    )
    scout = add_step(
        "agent-ui-flow-scout",
        scout_agent_ui_flow(
            journal,
            observer,
            objective=objective_text,
            limit=ui_limit,
            include_uia=include_uia,
        ),
    )
    if scout.get("path"):
        add_step(
            "agent-ui-flow-approval-plan",
            build_ui_flow_candidate_approval_plan(
                journal,
                scout_path=Path(scout["path"]),
                limit=ui_limit,
            ),
        )
    add_step(
        "agent-session-approval-plan",
        build_agent_session_approval_plan(
            journal,
            objective=objective_text,
            model_path=model_path,
            expected_revit_version=expected_revit_version,
            expected_title_contains=expected_title_contains,
            max_hours=max_hours,
            parameters=parameters,
        ),
    )
    if model_path:
        choreography = add_step(
            "agent-model-open-choreography",
            run_model_open_choreography(
                journal,
                observer,
                bridge,
                model_path=Path(model_path),
                revit_version=expected_revit_version,
                expected_title_contains=expected_title_contains,
                expected_path_contains=expected_path_contains,
                execute_open=False,
                timeout=0,
            ),
        )
        if choreography.get("path"):
            add_step(
                "agent-model-open-prompt-approval-plan",
                build_model_open_prompt_approval_plan(
                    journal,
                    choreography_path=Path(choreography["path"]),
                ),
            )
    else:
        steps.append(
            {
                "id": "agent-model-open-choreography",
                "status": "skipped_needs_model_path",
                "success": True,
                "read_only": True,
                "goal_complete": False,
                "may_call_update_goal": False,
                "path": None,
                "markdown_path": None,
                "output_files": [],
            }
        )
    add_step(
        "supervision-endurance-audit",
        audit_supervision_endurance(
            journal,
            target_hours=max_hours,
            require_live_window=True,
        ),
    )
    completion = add_step(
        "agent-session-completion-audit",
        build_agent_session_completion_audit(
            journal,
            objective=objective_text,
            max_artifacts=max_artifacts,
            target_hours=max_hours,
        ),
    )

    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-evidence-refresh/v1",
        "created_at": started_at,
        "finished_at": utc_now(),
        "objective": objective_text,
        "status": "blocked_at_completion_gates" if not completion.get("goal_complete") else "completion_ready",
        "reason": (
            "Read-only evidence was refreshed; approval/live-condition gates remain."
            if not completion.get("goal_complete")
            else "Read-only evidence refresh found all completion gates satisfied."
        ),
        "steps": steps,
        "step_count": len(steps),
        "completion_audit": {
            "path": completion.get("path"),
            "status": completion.get("status"),
            "blocked_count": completion.get("blocked_count"),
            "blocked_gates": completion.get("blocked_gates"),
            "goal_complete": completion.get("goal_complete"),
            "may_call_update_goal": completion.get("may_call_update_goal"),
        },
        "safety_summary": {
            "clicked_or_typed": False,
            "model_write_performed": False,
            "save_sync_publish_performed": False,
            "approval_required_actions_executed": False,
            "commands_are_read_only": True,
        },
        "goal_complete": bool(completion.get("goal_complete")),
        "may_call_update_goal": bool(completion.get("may_call_update_goal")),
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_session_evidence_refresh.json"
    md_path = journal.run_dir / "agent_session_evidence_refresh.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = _dedupe([*output_files, str(output), str(md_path)])
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _evidence_refresh_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-session-evidence-refresh",
            "requested_action": {"objective": objective_text},
            "risk_classification": classify_action("agent-session-evidence-refresh", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only evidence refresh only."},
            "result": {
                "status": result["status"],
                "step_count": len(steps),
                "goal_complete": result["goal_complete"],
                "may_call_update_goal": result["may_call_update_goal"],
            },
            "output_files": result["output_files"],
        }
    )
    return sanitized


def build_agent_session_approval_plan(
    journal: TaskJournal,
    *,
    objective: str,
    model_path: str = "",
    expected_revit_version: str = "",
    expected_title_contains: str = "",
    max_hours: float = 4.0,
    parameters: dict | None = None,
) -> dict:
    """Create a fresh approval packet for the gated phases of an agent session."""

    parameters = {str(key): str(value) for key, value in (parameters or {}).items()}
    plan = plan_agent_session(
        journal,
        objective=objective,
        model_path=model_path,
        expected_revit_version=expected_revit_version,
        expected_title_contains=expected_title_contains,
        max_hours=max_hours,
        parameters=parameters,
    )
    public_items: list[dict] = []
    private_items: list[dict] = []
    blocked_items: list[dict] = []

    for item in _ui_workflow_approval_items(plan.get("objective") or "", parameters):
        public_items.append(_without_approval_tokens(item["public"]))
        private_items.append(item["private"])
    for item in _model_change_approval_items(plan.get("objective") or "", parameters):
        if item.get("blocked"):
            blocked_items.append(_without_approval_tokens(item["public"]))
        else:
            public_items.append(_without_approval_tokens(item["public"]))
            private_items.append(item["private"])

    private_material = {
        "label": DRAFT_LABEL,
        "created_at": utc_now(),
        "schema": "hermes-revit-agent-session-approval-material/v1",
        "objective": plan.get("objective"),
        "approval_items": private_items,
        "warning": (
            "Private approval material. Use only after a fresh agent-session-run preflight "
            "still matches the intended Revit state."
        ),
    }
    public = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-approval-plan/v1",
        "created_at": utc_now(),
        "objective": plan.get("objective"),
        "plan_path": plan.get("path"),
        "approval_required_count": len(public_items),
        "blocked_count": len(blocked_items),
        "approval_material_withheld_from_public": True,
        "approval_items": public_items,
        "blocked_items": blocked_items,
        "private_material_contains_approval_tokens": bool(private_items),
        "goal_complete": False,
        "may_call_update_goal": False,
        "safety_note": (
            "This command creates approval material only. It does not click, type, "
            "queue model-changing commands, save, sync, publish, or modify Revit."
        ),
        "journal": journal.describe(),
    }
    public_path = journal.run_dir / "agent_session_approval_plan.json"
    private_path = journal.run_dir / "agent_session_approval_private_material.json"
    md_path = journal.run_dir / "agent_session_approval_plan.md"
    public["path"] = str(public_path)
    public["private_material_path"] = str(private_path)
    public["markdown_path"] = str(md_path)
    public["output_files"] = [str(public_path), str(private_path), str(md_path)]
    _write_json(public_path, journal.sandbox, _without_approval_tokens(public))
    _write_json(private_path, journal.sandbox, private_material)
    _write_text(md_path, journal.sandbox, _approval_plan_markdown(public))
    journal.write_entry(
        {
            "command": "agent-session-approval-plan",
            "requested_action": {"objective": plan.get("objective")},
            "risk_classification": classify_action("agent-session-approval-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Approval planning only; no Revit action executed."},
            "result": {
                "status": "planned",
                "approval_required_count": len(public_items),
                "blocked_count": len(blocked_items),
                "goal_complete": False,
            },
            "output_files": public["output_files"],
        }
    )
    return _without_approval_tokens(public)


def execute_agent_session_approved_item(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    bridge: RevitBridgeClient,
    *,
    approval_material_path: Path,
    item_id: str,
    execute: bool = False,
    confirmation: str = "",
    bridge_refresh_timeout: float = 10.0,
    ui_command_runner=None,
) -> dict:
    """Dry-run or execute one explicitly approved session item."""

    started_at = utc_now()
    path_error = validate_output_path(approval_material_path, journal.sandbox)
    if path_error:
        return {"success": False, "error": path_error}
    if not approval_material_path.exists():
        return {"success": False, "error": f"Approval material not found: {approval_material_path}"}
    material = json.loads(approval_material_path.read_text(encoding="utf-8"))
    item = _find_private_approval_item(material, item_id)
    if item is None:
        return {"success": False, "error": f"Approval item not found: {item_id}"}

    preflight = run_agent_session(
        journal,
        observer,
        bridge,
        objective=str(material.get("objective") or ""),
        run_open_dry_run=False,
        bridge_refresh_timeout=bridge_refresh_timeout,
        supervision_duration=0,
    )
    expected_phrase = f"I approve {item_id}"
    confirmation_ok = str(confirmation or "").strip() == expected_phrase
    execution = {
        "executed": False,
        "dry_run": not execute,
        "confirmation_required": execute,
        "confirmation_ok": confirmation_ok,
        "expected_confirmation_phrase": expected_phrase,
    }
    if preflight.get("status") == "stopped_on_modal":
        status = "stopped_on_modal"
        reason = "Fresh preflight found a modal dialog before approved execution."
    elif execute and not confirmation_ok:
        status = "stopped_confirmation_required"
        reason = "Execution requires the exact human confirmation phrase for this item."
    elif item.get("kind") == "model-change-operation":
        execution.update(
            _execute_model_change_item(
                journal,
                bridge,
                item,
                execute=execute,
            )
        )
        status = "executed" if execution.get("executed") else "ready_for_approval_execution"
        reason = (
            "Approved model-change item executed."
            if execution.get("executed")
            else "Approved model-change item dry-run completed; no Revit change was queued."
        )
    elif item.get("kind") == "ui-workflow-step":
        execution.update(
            _execute_ui_workflow_item(
                journal,
                observer,
                item,
                execute=execute,
                ui_command_runner=ui_command_runner,
            )
        )
        status = "executed" if execution.get("executed") else "ready_for_approval_execution"
        reason = (
            "Approved UI workflow item executed."
            if execution.get("executed")
            else "Approved UI workflow item dry-run completed; no UI action was executed."
        )
    else:
        status = "unsupported_item"
        reason = f"Unsupported approval item kind: {item.get('kind')}"

    result = {
        "success": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-session-approved-item/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "reason": reason,
        "item_id": item_id,
        "item_kind": item.get("kind"),
        "execute_requested": bool(execute),
        "preflight": preflight,
        "execution": execution,
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_session_approved_item_result.json"
    md_path = journal.run_dir / "agent_session_approved_item_result.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = [str(output), str(md_path)]
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _approved_item_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-session-execute-approved-item",
            "requested_action": {"item_id": item_id, "execute": bool(execute)},
            "risk_classification": classify_action("agent-session-execute-approved-item", {}).to_dict(),
            "approval_status": {
                "allowed": not execute or confirmation_ok,
                "reason": "Exact confirmation supplied." if confirmation_ok else "Dry-run or missing confirmation.",
            },
            "result": {
                "status": status,
                "executed": execution.get("executed"),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
        }
    )
    return sanitized


def scout_agent_ui_flow(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    objective: str,
    max_depth: int = 4,
    limit: int = 20,
    capture_screenshot: bool = False,
    include_uia: bool = False,
    uia_limit: int = 500,
    uia_tree_func=None,
) -> dict:
    """Observe the live UI and propose approval-gated candidates for unknown UI work."""

    started_at = utc_now()
    objective_text = " ".join(str(objective or "").split())
    status = _observer_result(observer, "status")
    dialogs = _observer_result(observer, "list_dialogs")
    active_dialogs = _visible_dialogs(status, dialogs)
    has_modal = bool(active_dialogs) or status.get("state") == "modal"
    terms = _ui_scout_terms(objective_text)
    tree_result = _observer_ui_tree(observer, max_depth=max_depth)
    tree_path = journal.run_dir / "agent_ui_flow_scout_ui_tree.json"
    _write_json(tree_path, journal.sandbox, tree_result)
    uia_result = None
    uia_path = None
    if include_uia:
        uia_result = _observer_uia_tree(
            observer,
            max_depth=max_depth,
            limit=max(1, uia_limit),
            uia_tree_func=uia_tree_func,
        )
        uia_path = journal.run_dir / "agent_ui_flow_scout_uia_tree.json"
        _write_json(uia_path, journal.sandbox, uia_result)

    screenshot_result = None
    output_files = [str(tree_path)]
    if uia_path:
        output_files.append(str(uia_path))
    if capture_screenshot:
        screenshot_result = _observer_screenshot(observer, journal.default_screenshot_path())
        if screenshot_result.get("path"):
            output_files.append(str(screenshot_result["path"]))

    if has_modal:
        candidates: list[dict] = []
        next_actions = _modal_dialog_next_actions(active_dialogs)
        result_status = "stopped_on_modal"
        reason = "A Revit dialog is active; arbitrary UI scouting must classify and resolve that prompt first."
    else:
        candidates = _dedupe_ui_candidates(
            [
                *_ui_scout_candidates(tree_result.get("tree"), terms, limit=max(0, limit), source="win32"),
                *(
                    _ui_scout_candidates(uia_result.get("tree"), terms, limit=max(0, limit), source="uia")
                    if isinstance(uia_result, dict)
                    else []
                ),
            ],
            limit=max(0, limit),
        )
        next_actions = _candidate_next_actions(candidates)
        if candidates:
            result_status = "candidates_found"
            reason = "Read-only UI candidates were found; execution still requires fresh dry-run and approval."
        else:
            result_status = "needs_workflow_authoring"
            reason = (
                "No matching controls were found in the observed tree; capture more evidence "
                "or record a new reusable workflow before executing UI actions."
            )
            next_actions = _workflow_authoring_next_actions(objective_text, max_depth=max_depth)

    result = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-ui-flow-scout/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": result_status,
        "reason": reason,
        "objective": objective_text,
        "terms": terms,
        "observation": {
            "status": status,
            "dialogs": dialogs,
            "has_modal_dialog": has_modal,
            "ui_tree": {
                "supported": tree_result.get("supported"),
                "success": tree_result.get("success", tree_result.get("supported")),
                "hwnd": tree_result.get("hwnd"),
                "path": str(tree_path),
                "error": tree_result.get("error"),
            },
            "uia_tree": {
                "requested": include_uia,
                "supported": uia_result.get("supported") if isinstance(uia_result, dict) else None,
                "success": uia_result.get("success") if isinstance(uia_result, dict) else None,
                "hwnd": uia_result.get("hwnd") if isinstance(uia_result, dict) else None,
                "node_count": uia_result.get("node_count") if isinstance(uia_result, dict) else None,
                "path": str(uia_path) if uia_path else None,
                "error": uia_result.get("error") if isinstance(uia_result, dict) else None,
            },
            "screenshot": screenshot_result,
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
        "next_actions": next_actions,
        "requires_approval_before_execution": True,
        "model_write_performed": False,
        "ui_action_executed": False,
        "goal_complete": False,
        "may_call_update_goal": False,
        "safety_summary": {
            "observation_only": True,
            "clicked_or_typed": False,
            "save_sync_publish_performed": False,
            "approval_tokens_exposed": False,
        },
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_ui_flow_scout.json"
    md_path = journal.run_dir / "agent_ui_flow_scout.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = _dedupe([*output_files, str(output), str(md_path)])
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _ui_flow_scout_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-ui-flow-scout",
            "requested_action": {"objective": objective_text, "max_depth": max_depth, "limit": limit},
            "risk_classification": classify_action("agent-ui-flow-scout", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Observation-only UI flow scouting."},
            "result": {
                "status": result_status,
                "success": True,
                "candidate_count": len(candidates),
                "goal_complete": False,
            },
            "output_files": sanitized["output_files"],
        }
    )
    return sanitized


def build_ui_flow_candidate_approval_plan(
    journal: TaskJournal,
    *,
    scout_path: Path,
    limit: int = 10,
) -> dict:
    """Turn a UI scout artifact into redacted public approvals and private tokens."""

    path_error = validate_output_path(scout_path, journal.sandbox)
    if path_error:
        return {
            "success": False,
            "error": path_error,
            "goal_complete": False,
            "may_call_update_goal": False,
            "journal": journal.describe(),
        }
    if not scout_path.exists():
        return {
            "success": False,
            "error": f"UI scout artifact not found: {scout_path}",
            "goal_complete": False,
            "may_call_update_goal": False,
            "journal": journal.describe(),
        }
    try:
        scout = json.loads(scout_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid UI scout JSON: {exc}",
            "goal_complete": False,
            "may_call_update_goal": False,
            "journal": journal.describe(),
        }
    if not isinstance(scout, dict):
        return {
            "success": False,
            "error": "UI scout artifact must contain a JSON object.",
            "goal_complete": False,
            "may_call_update_goal": False,
            "journal": journal.describe(),
        }

    candidates = [candidate for candidate in scout.get("candidates") or [] if isinstance(candidate, dict)]
    public_items: list[dict] = []
    private_items: list[dict] = []
    blocked_items: list[dict] = []
    for index, candidate in enumerate(candidates[: max(0, limit)]):
        item = _ui_candidate_approval_item(index, candidate)
        if item.get("blocked"):
            blocked_items.append(_without_approval_tokens(item["public"]))
        else:
            public_items.append(_without_approval_tokens(item["public"]))
            private_items.append(item["private"])

    private_material = {
        "label": DRAFT_LABEL,
        "created_at": utc_now(),
        "schema": "hermes-revit-agent-ui-flow-approval-material/v1",
        "source_scout_path": str(scout_path),
        "source_scout_schema": scout.get("schema"),
        "source_scout_status": scout.get("status"),
        "approval_items": private_items,
        "warning": (
            "Private UI approval material. Use only after a fresh UI scout and dry-run "
            "still match the intended Revit state."
        ),
    }
    public = {
        "success": True,
        "read_only": True,
        "planned_only": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-ui-flow-approval-plan/v1",
        "created_at": utc_now(),
        "source_scout_path": str(scout_path),
        "source_scout_schema": scout.get("schema"),
        "source_scout_status": scout.get("status"),
        "source_candidate_count": len(candidates),
        "considered_candidate_count": min(max(0, limit), len(candidates)),
        "approval_required_count": len(public_items),
        "blocked_count": len(blocked_items),
        "approval_material_withheld_from_public": True,
        "approval_items": public_items,
        "blocked_items": blocked_items,
        "private_material_contains_approval_tokens": bool(private_items),
        "goal_complete": False,
        "may_call_update_goal": False,
        "safety_note": (
            "This command creates approval material only. It does not click, type, "
            "queue model-changing commands, save, sync, publish, or modify Revit."
        ),
        "journal": journal.describe(),
    }
    public_path = journal.run_dir / "agent_ui_flow_approval_plan.json"
    private_path = journal.run_dir / "agent_ui_flow_approval_private_material.json"
    md_path = journal.run_dir / "agent_ui_flow_approval_plan.md"
    public["path"] = str(public_path)
    public["private_material_path"] = str(private_path)
    public["markdown_path"] = str(md_path)
    public["output_files"] = [str(public_path), str(private_path), str(md_path)]
    _write_json(public_path, journal.sandbox, _without_approval_tokens(public))
    _write_json(private_path, journal.sandbox, private_material)
    _write_text(md_path, journal.sandbox, _ui_flow_approval_plan_markdown(public))
    journal.write_entry(
        {
            "command": "agent-ui-flow-approval-plan",
            "requested_action": {"scout_path": str(scout_path), "limit": limit},
            "risk_classification": classify_action("agent-ui-flow-approval-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Approval planning only; no Revit action executed."},
            "result": {
                "status": "planned",
                "approval_required_count": len(public_items),
                "blocked_count": len(blocked_items),
                "goal_complete": False,
            },
            "output_files": public["output_files"],
        }
    )
    return _without_approval_tokens(public)


def execute_ui_flow_approved_candidate(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    *,
    approval_material_path: Path,
    item_id: str,
    execute: bool = False,
    confirmation: str = "",
) -> dict:
    """Dry-run or execute one candidate from private UI scout approval material."""

    started_at = utc_now()
    path_error = validate_output_path(approval_material_path, journal.sandbox)
    if path_error:
        return {"success": False, "error": path_error, "goal_complete": False, "may_call_update_goal": False}
    if not approval_material_path.exists():
        return {
            "success": False,
            "error": f"Approval material not found: {approval_material_path}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    try:
        material = json.loads(approval_material_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid approval material JSON: {exc}",
            "goal_complete": False,
            "may_call_update_goal": False,
        }
    item = _find_private_approval_item(material if isinstance(material, dict) else {}, item_id)
    if item is None:
        return {"success": False, "error": f"Approval item not found: {item_id}", "goal_complete": False}
    if item.get("kind") != "ui-candidate-control":
        return {
            "success": False,
            "error": f"Approval item is not a UI candidate control: {item.get('kind')}",
            "goal_complete": False,
        }

    expected_confirmation = f"I approve {item_id}"
    confirmation_ok = str(confirmation or "").strip() == expected_confirmation
    pre_action_status = _observer_result(observer, "status")
    pre_action_dialogs = _observer_result(observer, "list_dialogs")
    active_dialogs = _visible_dialogs(pre_action_status, pre_action_dialogs)
    has_modal = bool(active_dialogs) or pre_action_status.get("state") == "modal"
    payload = _ui_candidate_action_payload(item)
    action_result = None
    if has_modal:
        status = "stopped_on_modal"
        reason = "Fresh observation found a modal dialog before approved UI candidate execution."
    elif execute and not confirmation_ok:
        status = "stopped_confirmation_required"
        reason = "Execution requires the exact human confirmation phrase for this UI candidate."
    else:
        action_result = SafeActionExecutor(observer, journal).run(
            ActionRequest(
                action="uia-invoke",
                payload=payload,
                dry_run=not execute,
                approval_token=str(item.get("approval_token") or ""),
            )
        )
        if execute:
            status = "executed" if action_result.get("executed") else "failed"
            reason = (
                "Approved UI candidate executed."
                if action_result.get("executed")
                else "Approved UI candidate execution failed or was blocked by verification."
            )
        else:
            status = "ready_for_approval_execution"
            reason = "Approved UI candidate dry-run completed; no UI action was executed."

    result = {
        "success": True,
        "label": DRAFT_LABEL,
        "schema": "hermes-revit-agent-ui-flow-approved-candidate/v1",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "reason": reason,
        "item_id": item_id,
        "item_kind": item.get("kind"),
        "target": item.get("target"),
        "execute_requested": bool(execute),
        "confirmation_required": bool(execute),
        "confirmation_ok": confirmation_ok,
        "expected_confirmation_phrase": expected_confirmation,
        "pre_action_observation": {
            "status": pre_action_status,
            "dialogs": pre_action_dialogs,
            "has_modal_dialog": has_modal,
        },
        "action_payload": payload,
        "action_result": _without_approval_tokens(action_result) if action_result else None,
        "receipt": {
            "approval_bound_to_private_item": bool(item.get("approval_token")),
            "private_material_schema": material.get("schema") if isinstance(material, dict) else None,
            "source_scout_path": material.get("source_scout_path") if isinstance(material, dict) else None,
            "ui_action_executed": bool(action_result and action_result.get("executed")),
            "model_write_performed": False,
            "save_sync_publish_performed": False,
        },
        "goal_complete": False,
        "may_call_update_goal": False,
        "journal": journal.describe(),
    }
    output = journal.run_dir / "agent_ui_flow_approved_candidate_result.json"
    md_path = journal.run_dir / "agent_ui_flow_approved_candidate_result.md"
    result["path"] = str(output)
    result["markdown_path"] = str(md_path)
    result["output_files"] = [str(output), str(md_path)]
    sanitized = _without_approval_tokens(result)
    _write_json(output, journal.sandbox, sanitized)
    _write_text(md_path, journal.sandbox, _ui_flow_approved_candidate_markdown(sanitized))
    journal.write_entry(
        {
            "command": "agent-ui-flow-execute-approved-candidate",
            "requested_action": {"item_id": item_id, "execute": bool(execute)},
            "risk_classification": _without_approval_tokens(classify_action("uia-invoke", payload).to_dict()),
            "approval_status": {
                "allowed": not execute or confirmation_ok,
                "reason": "Exact confirmation supplied." if confirmation_ok else "Dry-run or missing confirmation.",
            },
            "result": {
                "status": status,
                "executed": bool(action_result and action_result.get("executed")),
                "goal_complete": False,
            },
            "output_files": result["output_files"],
        }
    )
    return sanitized


def _observer_result(observer: RevitWindowObserver, method_name: str) -> dict:
    method = getattr(observer, method_name, None)
    if not callable(method):
        return {"success": False, "supported": False, "error": f"Observer has no {method_name} method."}
    try:
        result = method()
    except Exception as exc:  # pragma: no cover - defensive around live UI automation
        return {"success": False, "supported": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"success": False, "error": f"{method_name} returned non-dict."}


def _observer_ui_tree(observer: RevitWindowObserver, *, max_depth: int) -> dict:
    method = getattr(observer, "ui_tree", None)
    if not callable(method):
        return {"success": False, "supported": False, "tree": None, "error": "Observer has no ui_tree method."}
    try:
        result = method(max_depth=max(0, max_depth))
    except TypeError:
        try:
            result = method(None, max(0, max_depth))
        except Exception as exc:  # pragma: no cover - defensive around live UI automation
            return {"success": False, "supported": False, "tree": None, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive around live UI automation
        return {"success": False, "supported": False, "tree": None, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, dict):
        return result
    return {"success": False, "supported": False, "tree": None, "error": "ui_tree returned non-dict."}


def _observer_uia_tree(
    observer: RevitWindowObserver,
    *,
    max_depth: int,
    limit: int,
    uia_tree_func,
) -> dict:
    tree_func = uia_tree_func or uia_tree
    try:
        result = tree_func(observer=observer, max_depth=max(0, max_depth), limit=max(1, limit))
    except Exception as exc:  # pragma: no cover - defensive around live UI automation
        return {"success": False, "supported": False, "tree": None, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, dict):
        return result
    return {"success": False, "supported": False, "tree": None, "error": "uia_tree returned non-dict."}


def _observer_screenshot(observer: RevitWindowObserver, output: Path) -> dict:
    method = getattr(observer, "screenshot", None)
    if not callable(method):
        return {"success": False, "supported": False, "error": "Observer has no screenshot method."}
    try:
        result = method(output)
    except Exception as exc:  # pragma: no cover - defensive around live UI automation
        return {"success": False, "supported": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"success": False, "error": "screenshot returned non-dict."}


def _visible_dialogs(status: dict, dialogs: dict) -> list[dict]:
    visible: list[dict] = []
    for dialog in dialogs.get("dialogs") or []:
        if isinstance(dialog, dict):
            visible.append(dialog)
    for dialog in status.get("active_dialogs") or []:
        if isinstance(dialog, dict) and not any(dialog == known for known in visible):
            visible.append(dialog)
    return visible


def _modal_dialog_next_actions(dialogs: list[dict]) -> list[dict]:
    dialog = dialogs[0] if dialogs else {}
    return [
        {
            "kind": "modal-dialog-gate",
            "recommended_action": "plan-current-dialog-response",
            "command": _command(["plan-current-dialog-response", "--index", "0"]),
            "risk": "high",
            "requires_approval": True,
            "reason": "Visible modal dialog blocks reliable UI navigation; classify the prompt before any click/key action.",
            "dialog": _without_approval_tokens(
                {
                    "title": dialog.get("title") or dialog.get("dialog_title") or "",
                    "text": dialog.get("dialog_text") or "",
                    "buttons": dialog.get("buttons") or [],
                    "classification": dialog.get("classification"),
                }
            ),
        }
    ]


def _ui_scout_terms(objective: str) -> list[str]:
    text = objective.casefold()
    raw_terms: list[str] = []
    for double_quoted, single_quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', objective):
        raw_terms.append(double_quoted or single_quoted)
    for phrase in UI_SCOUT_KNOWN_PHRASES:
        if phrase in text:
            raw_terms.append(phrase)
    words = [
        word
        for word in re.findall(r"[a-z0-9][a-z0-9/-]*", text)
        if word not in UI_SCOUT_STOP_WORDS and (len(word) >= 4 or word in {"qa", "qc", "vg", "pdf", "dwg", "rvt"})
    ]
    for size in (3, 2):
        for index in range(0, max(0, len(words) - size + 1)):
            phrase = " ".join(words[index : index + size])
            if phrase and phrase not in UI_SCOUT_STOP_WORDS:
                raw_terms.append(phrase)
    raw_terms.extend(words)
    return _dedupe([_ui_norm(term) for term in raw_terms if _ui_norm(term)])[:40]


def _ui_scout_candidates(tree: dict | None, terms: list[str], *, limit: int, source: str) -> list[dict]:
    if not tree or not terms or limit == 0:
        return []
    candidates: list[dict] = []

    def visit(node: dict, depth: int, path: list[str]) -> None:
        if not isinstance(node, dict):
            return
        title = str(node.get("title") or node.get("name") or "")
        control_type = str(node.get("control_type") or node.get("localized_control_type") or "")
        class_name = str(node.get("class_name") or node.get("class") or "")
        automation_id = str(node.get("automation_id") or node.get("automationId") or "")
        label = title or control_type or class_name or str(node.get("hwnd") or "")
        next_path = [*path, label] if label else path
        node_text = _ui_norm(
            " ".join(
                str(node.get(key) or "")
                for key in (
                    "title",
                    "name",
                    "text",
                    "value",
                    "class_name",
                    "class",
                    "control_type",
                    "localized_control_type",
                    "automation_id",
                    "automationId",
                    "help_text",
                )
            )
        )
        matched = [term for term in terms if _ui_term_matches_node(term, node_text)]
        if matched:
            candidates.append(
                _ui_candidate_payload(
                    node,
                    title=title,
                    class_name=class_name,
                    control_type=control_type,
                    automation_id=automation_id,
                    depth=depth,
                    path=next_path,
                    matched_terms=matched,
                    source=source,
                )
            )
        for child in node.get("children") or []:
            visit(child, depth + 1, next_path)

    visit(tree, 0, [])
    candidates.sort(key=lambda item: (-int(item.get("score", 0)), int(item.get("depth", 999)), item.get("path", "")))
    return candidates[:limit]


def _ui_candidate_payload(
    node: dict,
    *,
    title: str,
    class_name: str,
    control_type: str,
    automation_id: str,
    depth: int,
    path: list[str],
    matched_terms: list[str],
    source: str,
) -> dict:
    target_name = title or automation_id or control_type or class_name
    payload = {
        "name": target_name,
        "control_type": control_type,
        "automation_id": automation_id,
        "class_name": class_name,
        "hwnd": node.get("hwnd") or node.get("handle"),
        "method": "invoke",
    }
    policy = classify_action("uia-invoke", payload)
    score = len(set(matched_terms)) + sum(2 for term in matched_terms if " " in term)
    if target_name and _ui_norm(target_name) in matched_terms:
        score += 3
    recommended_action = "dry_run_uia_invoke_then_request_approval"
    if policy.decision == BLOCK:
        recommended_action = "do_not_execute"
    elif node.get("enabled") is False:
        recommended_action = "inspect_disabled_control"
    return {
        "target": target_name,
        "title": title,
        "class_name": class_name,
        "control_type": control_type,
        "automation_id": automation_id,
        "hwnd": node.get("hwnd") or node.get("handle"),
        "enabled": node.get("enabled"),
        "visible": node.get("visible"),
        "rect": node.get("rect"),
        "depth": depth,
        "source": source,
        "path": " > ".join(part for part in path if part),
        "matched_terms": matched_terms,
        "score": score,
        "confidence": "medium" if score >= 3 else "low",
        "policy": _without_approval_tokens(policy.to_dict()),
        "recommended_action": recommended_action,
        "inspection_command": _ui_control_details_command(payload),
        "dry_run_command": _ui_invoke_command(payload, execute=False),
        "approval_execution_template": _ui_invoke_command(payload, execute=True),
    }


def _dedupe_ui_candidates(candidates: list[dict], *, limit: int) -> list[dict]:
    candidates.sort(key=lambda item: (-int(item.get("score", 0)), int(item.get("depth", 999)), item.get("path", "")))
    seen: set[tuple[str, str, str]] = set()
    result = []
    for candidate in candidates:
        key = (
            _ui_norm(candidate.get("target") or ""),
            _ui_norm(candidate.get("control_type") or candidate.get("class_name") or ""),
            _ui_norm(candidate.get("path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def _ui_candidate_approval_item(index: int, candidate: dict) -> dict:
    target = str(candidate.get("target") or candidate.get("title") or candidate.get("name") or "")
    payload = {
        "name": target,
        "control_type": str(candidate.get("control_type") or ""),
        "automation_id": str(candidate.get("automation_id") or ""),
        "class_name": str(candidate.get("class_name") or ""),
        "method": "invoke",
        "exact": True,
    }
    if candidate.get("hwnd") is not None:
        payload["hwnd"] = candidate.get("hwnd")
    policy = classify_action("uia-invoke", payload)
    policy_payload = policy.to_dict()
    item_id = f"ui-candidate:{index}:{_workflow_slug(target or f'candidate-{index}')}"
    public = {
        "id": item_id,
        "kind": "ui-candidate-control",
        "target": target,
        "source": candidate.get("source"),
        "path": candidate.get("path"),
        "matched_terms": candidate.get("matched_terms") or [],
        "confidence": candidate.get("confidence") or "unknown",
        "control_type": payload.get("control_type"),
        "automation_id": payload.get("automation_id"),
        "class_name": payload.get("class_name"),
        "hwnd": payload.get("hwnd"),
        "method": payload.get("method"),
        "exact": True,
        "risk": policy_payload.get("risk"),
        "reason": policy_payload.get("reason"),
        "policy": _without_approval_tokens(policy_payload),
        "blocked": policy.decision == BLOCK,
        "approval_token_withheld": bool(policy_payload.get("approval_token")) and policy.decision != BLOCK,
        "execute_command_withheld": policy.decision != BLOCK,
        "inspection_command": _ui_control_details_command(payload),
        "dry_run_command": _ui_invoke_command(payload, execute=False),
        "verify_before_execution": [
            "agent-ui-flow-scout",
            "uia-control-details",
            "uia-invoke dry-run",
            "agent-session-checkpoint",
        ],
    }
    if policy.decision == BLOCK:
        return {"blocked": True, "public": public}
    token = str(policy_payload.get("approval_token") or "")
    private = {
        **public,
        "action_payload": payload,
        "approval_token": token,
        "execute_command": _ui_candidate_execute_command(payload, token),
    }
    return {"blocked": False, "public": public, "private": private}


def _ui_candidate_action_payload(item: dict) -> dict:
    material_payload = item.get("action_payload")
    if isinstance(material_payload, dict) and material_payload:
        return dict(material_payload)
    payload = {
        "name": str(item.get("target") or ""),
        "control_type": str(item.get("control_type") or ""),
        "automation_id": str(item.get("automation_id") or ""),
        "class_name": str(item.get("class_name") or ""),
        "method": str(item.get("method") or "invoke"),
        "exact": True,
    }
    if item.get("hwnd") is not None:
        payload["hwnd"] = item.get("hwnd")
    return payload


def _ui_candidate_execute_command(payload: dict, approval_token: str) -> str:
    parts = ["uia-invoke"]
    if payload.get("name"):
        parts.extend(["--name", str(payload["name"])])
    if payload.get("control_type"):
        parts.extend(["--control-type", str(payload["control_type"])])
    if payload.get("automation_id"):
        parts.extend(["--automation-id", str(payload["automation_id"])])
    if payload.get("class_name"):
        parts.extend(["--class-name", str(payload["class_name"])])
    if payload.get("hwnd") is not None:
        parts.extend(["--hwnd", str(payload["hwnd"])])
    parts.extend(["--method", str(payload.get("method") or "invoke"), "--exact", "--execute"])
    if approval_token:
        parts.extend(["--approval-token", approval_token])
    return _command(parts)


def _candidate_next_actions(candidates: list[dict]) -> list[dict]:
    actions = []
    for candidate in candidates[:5]:
        actions.append(
            {
                "kind": "candidate-control",
                "target": candidate.get("target"),
                "source": candidate.get("source"),
                "recommended_action": candidate.get("recommended_action"),
                "risk": candidate.get("policy", {}).get("risk"),
                "requires_approval": candidate.get("policy", {}).get("decision") == APPROVAL_REQUIRED,
                "inspection_command": candidate.get("inspection_command"),
                "dry_run_command": candidate.get("dry_run_command"),
                "approval_execution_template": candidate.get("approval_execution_template"),
                "reason": candidate.get("policy", {}).get("reason"),
            }
        )
    return actions


def _workflow_authoring_next_actions(objective: str, *, max_depth: int) -> list[dict]:
    return [
        {
            "kind": "broaden-observation",
            "recommended_action": "capture-ui-tree",
            "command": _command(["ui-tree", "--max-depth", str(max_depth + 2)]),
            "risk": "low",
            "requires_approval": False,
            "reason": "Capture a deeper Win32 tree before deciding that the UI path is inaccessible.",
        },
        {
            "kind": "broaden-observation",
            "recommended_action": "capture-screenshot",
            "command": "screenshot",
            "risk": "low",
            "requires_approval": False,
            "reason": "Use visual evidence or OCR when controls are inaccessible.",
        },
        {
            "kind": "author-workflow",
            "recommended_action": "record-workflow-after-human-demonstration",
            "command": _command(
                [
                    "record-workflow",
                    "--source-task-id",
                    "<source-task-id>",
                    "--name",
                    _workflow_slug(objective),
                    "--description",
                    objective or "Observed Revit UI workflow",
                ]
            ),
            "risk": "low",
            "requires_approval": False,
            "reason": "Unknown flows should become reusable recipes instead of one-off guessed clicks.",
        },
    ]


def _ui_control_details_command(payload: dict) -> str:
    parts = ["uia-control-details"]
    if payload.get("name"):
        parts.extend(["--name", str(payload["name"])])
    if payload.get("control_type"):
        parts.extend(["--control-type", str(payload["control_type"])])
    if payload.get("automation_id"):
        parts.extend(["--automation-id", str(payload["automation_id"])])
    if payload.get("class_name"):
        parts.extend(["--class-name", str(payload["class_name"])])
    if payload.get("hwnd") is not None:
        parts.extend(["--hwnd", str(payload["hwnd"])])
    parts.append("--exact")
    return _command(parts)


def _ui_invoke_command(payload: dict, *, execute: bool) -> str:
    parts = ["uia-invoke"]
    if payload.get("name"):
        parts.extend(["--name", str(payload["name"])])
    if payload.get("control_type"):
        parts.extend(["--control-type", str(payload["control_type"])])
    if payload.get("automation_id"):
        parts.extend(["--automation-id", str(payload["automation_id"])])
    if payload.get("class_name"):
        parts.extend(["--class-name", str(payload["class_name"])])
    if payload.get("hwnd") is not None:
        parts.extend(["--hwnd", str(payload["hwnd"])])
    parts.extend(["--method", str(payload.get("method") or "invoke"), "--exact"])
    if execute:
        parts.extend(["--execute", "--approval-token", "<fresh approval token from dry-run>"])
    return _command(parts)


def _ui_term_matches_node(term: str, node_text: str) -> bool:
    if not term or not node_text:
        return False
    if term in node_text:
        return True
    words = [word for word in term.split() if word]
    return len(words) > 1 and all(word in node_text for word in words)


def _ui_norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("&", "").strip())


def _workflow_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (slug[:48].strip("-") or "revit-ui-workflow")


def _detect_intents(objective: str) -> dict:
    text = objective.casefold()
    return {name: bool(re.search(pattern, text, re.IGNORECASE)) for name, pattern in INTENT_PATTERNS.items()}


def _candidate_workflow_plans(objective: str, parameters: dict) -> list[dict]:
    text = objective.casefold()
    matches = []
    for name, hints in WORKFLOW_HINTS.items():
        if name not in UI_WORKFLOWS:
            continue
        if any(hint in text for hint in hints):
            matches.append(_workflow_plan_payload(name, parameters, matched_hints=[hint for hint in hints if hint in text]))
    if not matches and objective.strip():
        matches.append(_workflow_plan_payload("readonly-qa-pass", parameters, matched_hints=["default-readonly-qa"]))
    return matches


def _workflow_plan_payload(name: str, parameters: dict, *, matched_hints: list[str]) -> dict:
    recipe = UI_WORKFLOWS[name]
    steps = [_without_approval_tokens(step.render(parameters)) for step in recipe.steps]
    approval_required = [
        index
        for index, step in enumerate(steps)
        if step.get("requires_approval") or step.get("policy", {}).get("decision") == APPROVAL_REQUIRED
    ]
    blocked = [
        index
        for index, step in enumerate(steps)
        if step.get("policy", {}).get("decision") == BLOCK
    ]
    missing_parameters = sorted(
        {missing for step in steps for missing in (step.get("missing_parameters") or [])}
    )
    return {
        "name": recipe.name,
        "summary": recipe.summary,
        "category": recipe.category,
        "matched_hints": matched_hints,
        "parameters": parameters,
        "required_parameters": list(recipe.parameters),
        "missing_parameters": missing_parameters,
        "preconditions": list(recipe.preconditions),
        "blocked_actions": list(recipe.blocked_actions),
        "approval_gates": list(recipe.approval_gates),
        "step_count": len(steps),
        "approval_required_steps": approval_required,
        "blocked_steps": blocked,
        "can_plan": not missing_parameters,
        "can_execute_without_human": not approval_required and not blocked and not missing_parameters,
        "plan_command": _command(["plan-ui-workflow", "--name", recipe.name, "--parameters-json", json.dumps(parameters)]),
        "dry_run_command": _command(
            ["run-ui-workflow", "--name", recipe.name, "--parameters-json", json.dumps(parameters)]
        ),
        "steps": steps,
    }


def _model_change_requests(objective: str, parameters: dict) -> list[dict]:
    text = objective.casefold()
    requests = []
    for operation, pattern in MODEL_CHANGE_OPERATIONS.items():
        if not re.search(pattern, text, re.IGNORECASE):
            continue
        payload = _operation_payload(operation, parameters)
        decision = classify_action(
            "request-operation",
            {
                "operation": operation,
                "args": payload,
                "allow_model_write": operation not in {"save", "sync", "delete"},
                "allow_sync": operation == "sync",
            },
        )
        requests.append(
            {
                "operation": operation,
                "payload": payload,
                "policy": _without_approval_tokens(decision.to_dict()),
                "approval_required": decision.decision == APPROVAL_REQUIRED,
                "blocked": decision.decision == BLOCK or operation in {"save", "sync", "delete"},
                "dry_run_command": _request_operation_command(operation, payload),
                "execute_note": (
                    "Execution requires a fresh dry-run approval token, --execute, and explicit write guards. "
                    "This session plan does not execute model-changing work."
                ),
            }
        )
    return requests


def _ui_workflow_approval_items(objective: str, parameters: dict) -> list[dict]:
    text = objective.casefold()
    items: list[dict] = []
    for name, hints in WORKFLOW_HINTS.items():
        if name not in UI_WORKFLOWS or not any(hint in text for hint in hints):
            continue
        recipe = UI_WORKFLOWS[name]
        for index, step_recipe in enumerate(recipe.steps):
            step = step_recipe.render(parameters)
            policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
            token = str(policy.get("approval_token") or "")
            if policy.get("decision") != APPROVAL_REQUIRED or not token:
                continue
            item_id = f"ui:{recipe.name}:step:{index}"
            execute_command = _command(
                [
                    "run-ui-workflow",
                    "--name",
                    recipe.name,
                    "--execute",
                    "--approval-tokens-json",
                    json.dumps({str(index): token}, sort_keys=True, separators=(",", ":")),
                    "--parameters-json",
                    json.dumps(parameters, sort_keys=True),
                ]
            )
            public = {
                "id": item_id,
                "kind": "ui-workflow-step",
                "workflow": recipe.name,
                "step_index": index,
                "command": step.get("command"),
                "args": step.get("args", []),
                "risk": policy.get("risk"),
                "reason": policy.get("reason"),
                "approval_token_withheld": True,
                "execute_command_withheld": True,
                "verify_before_execution": [
                    "agent-session-run",
                    "plan-ui-workflow",
                    "run-ui-workflow dry-run",
                ],
            }
            private = {
                **public,
                "parameters": parameters,
                "approval_token": token,
                "execute_command": execute_command,
            }
            items.append({"public": public, "private": private})
    return items


def _model_change_approval_items(objective: str, parameters: dict) -> list[dict]:
    text = objective.casefold()
    items: list[dict] = []
    for operation, pattern in MODEL_CHANGE_OPERATIONS.items():
        if not re.search(pattern, text, re.IGNORECASE):
            continue
        payload = _operation_payload(operation, parameters)
        blocked = operation in {"save", "sync", "delete"}
        allow_model_write = not blocked
        allow_sync = operation == "sync"
        decision = classify_action(
            "request-operation",
            {
                "operation": operation,
                "args": payload,
                "allow_model_write": allow_model_write,
                "allow_sync": allow_sync,
            },
        )
        policy = decision.to_dict()
        item_id = f"model-change:{operation}"
        public = {
            "id": item_id,
            "kind": "model-change-operation",
            "operation": operation,
            "payload": payload,
            "risk": policy.get("risk"),
            "reason": (
                "Blocked by session approval policy."
                if blocked
                else policy.get("reason")
            ),
            "blocked": blocked,
            "approval_token_withheld": bool(policy.get("approval_token")) and not blocked,
            "execute_command_withheld": not blocked,
            "verify_before_execution": [
                "agent-session-run",
                "request-operation dry-run",
                "post-action active-document refresh",
            ],
        }
        if blocked:
            items.append({"blocked": True, "public": public})
            continue
        token = str(policy.get("approval_token") or "")
        execute_parts = ["request-operation", "--operation", operation, "--execute"]
        if payload:
            execute_parts.extend(["--args-json", json.dumps(payload, sort_keys=True)])
        execute_parts.extend(["--allow-model-write", "--approval-token", token])
        private = {
            **public,
            "approval_token": token,
            "execute_command": _command(execute_parts),
        }
        items.append({"blocked": False, "public": public, "private": private})
    return items


def _find_private_approval_item(material: dict, item_id: str) -> dict | None:
    for item in material.get("approval_items") or []:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def _execute_model_change_item(
    journal: TaskJournal,
    bridge: RevitBridgeClient,
    item: dict,
    *,
    execute: bool,
) -> dict:
    operation = str(item.get("operation") or "")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    token = str(item.get("approval_token") or "")
    pre_action_document = _safe_bridge_active_document(bridge)
    request = OperationRequest(
        operation=operation,
        args=payload,
        dry_run=not execute,
        approval_token=token,
        allow_model_write=True,
        allow_sync=operation in {"sync", "synchronize-with-central"},
    )
    result = queue_operation(journal, request)
    command_id = result.get("command", {}).get("id")
    wait_result = None
    post_action_refresh = None
    post_action_wait = None
    post_action_document = None
    if execute and result.get("success") and command_id:
        wait_result = bridge.wait_for_command_result(command_id, timeout=60, poll=1)
    if execute and result.get("success"):
        post_action_refresh = queue_operation(
            journal,
            OperationRequest(operation="active-document", args={}, dry_run=False),
        )
        refresh_id = post_action_refresh.get("command", {}).get("id")
        if post_action_refresh.get("success") and refresh_id:
            post_action_wait = bridge.wait_for_command_result(refresh_id, timeout=15, poll=1)
        post_action_document = _safe_bridge_active_document(bridge)
    return {
        "kind": "model-change-operation",
        "operation": operation,
        "pre_action_active_document": _without_approval_tokens(pre_action_document),
        "dry_run_result": _without_approval_tokens(result),
        "wait_result": _without_approval_tokens(wait_result) if wait_result else None,
        "post_action_refresh": _without_approval_tokens(post_action_refresh) if post_action_refresh else None,
        "post_action_wait_result": _without_approval_tokens(post_action_wait) if post_action_wait else None,
        "post_action_active_document": _without_approval_tokens(post_action_document) if post_action_document else None,
        "receipt": {
            "requested_operation": operation,
            "queued_operation": result.get("command", {}).get("operation"),
            "model_write_guard": request.allow_model_write,
            "sync_guard": request.allow_sync,
            "approval_bound_to_private_item": bool(token),
            "post_action_refresh_requested": bool(post_action_refresh),
            "post_action_refresh_success": bool(post_action_refresh and post_action_refresh.get("success")),
        },
        "executed": bool(execute and result.get("success")),
    }


def _safe_bridge_active_document(bridge: RevitBridgeClient) -> dict:
    try:
        status = bridge.active_document_status()
    except Exception as exc:
        return {"available": False, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return status if isinstance(status, dict) else {"available": False, "status": "invalid", "raw_status": status}


def _execute_ui_workflow_item(
    journal: TaskJournal,
    observer: RevitWindowObserver,
    item: dict,
    *,
    execute: bool,
    ui_command_runner,
) -> dict:
    workflow = str(item.get("workflow") or "")
    step_index = int(item.get("step_index") or 0)
    token = str(item.get("approval_token") or "")
    parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
    result = run_ui_workflow(
        journal,
        name=workflow,
        parameters=parameters,
        dry_run=not execute,
        approval_tokens={step_index: token},
        max_steps=step_index + 1,
        observe_func=observer.status,
        command_runner=ui_command_runner,
    )
    return {
        "kind": "ui-workflow-step",
        "workflow": workflow,
        "step_index": step_index,
        "workflow_result": _without_approval_tokens(result),
        "executed": bool(execute and result.get("success")),
    }


def _operation_payload(operation: str, parameters: dict) -> dict:
    if operation == "set-project-info-parameter":
        return {
            "name": parameters.get("parameter_name", "{parameter_name}"),
            "value": parameters.get("parameter_value", "{parameter_value}"),
        }
    if operation == "activate-view":
        return {
            "sheet_number": parameters.get("sheet_number", "{sheet_number}"),
        }
    return {}


def _request_operation_command(operation: str, payload: dict) -> str:
    args = ["request-operation", "--operation", operation]
    if payload:
        args.extend(["--args-json", json.dumps(payload, sort_keys=True)])
    return _command(args)


def _completion_artifact_inventory(root: Path, sandbox: Path, *, max_artifacts: int) -> dict:
    root = Path(root)
    loaded: list[dict] = []
    skipped: list[dict] = []
    summaries: list[dict] = []
    if not root.exists():
        return {
            "root_exists": False,
            "json_file_count": 0,
            "loaded_count": 0,
            "skipped_count": 0,
            "schema_counts": {},
            "artifacts": [],
            "skipped": [],
            "_loaded_artifacts": [],
        }

    candidates: list[tuple[float, int, Path]] = []
    for path in root.rglob("*.json"):
        try:
            stat = path.stat()
        except OSError as exc:
            skipped.append(
                {
                    "path": str(path),
                    "reason": f"stat failed: {type(exc).__name__}",
                }
            )
            continue
        candidates.append((stat.st_mtime, stat.st_size, path))
    candidates.sort(reverse=True)

    for _mtime, size, path in candidates[: max(0, max_artifacts)]:
        if size > 2_000_000:
            skipped.append(
                {
                    "path": str(path),
                    "relative_path": _safe_relative_path(path, sandbox),
                    "reason": "JSON artifact exceeded the 2 MB audit read limit.",
                    "bytes": size,
                }
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append(
                {
                    "path": str(path),
                    "relative_path": _safe_relative_path(path, sandbox),
                    "reason": f"JSON parse failed: {type(exc).__name__}: {exc}",
                    "bytes": size,
                }
            )
            continue
        if not isinstance(payload, dict):
            skipped.append(
                {
                    "path": str(path),
                    "relative_path": _safe_relative_path(path, sandbox),
                    "reason": "JSON artifact was not an object.",
                    "bytes": size,
                }
            )
            continue
        artifact = {
            "path": path,
            "payload": payload,
            "schema": _completion_artifact_schema(path, payload),
            "bytes": size,
        }
        loaded.append(artifact)
        summaries.append(_completion_artifact_summary(artifact, sandbox))

    schema_counts: dict[str, int] = {}
    for artifact in loaded:
        schema = artifact["schema"] or "<unknown>"
        schema_counts[schema] = schema_counts.get(schema, 0) + 1
    return {
        "root_exists": True,
        "json_file_count": len(candidates),
        "loaded_count": len(loaded),
        "max_artifacts": max_artifacts,
        "truncated": len(candidates) > max_artifacts,
        "skipped_count": len(skipped),
        "schema_counts": dict(sorted(schema_counts.items())),
        "artifacts": summaries,
        "skipped": skipped[:50],
        "_loaded_artifacts": loaded,
    }


def _completion_artifact_schema(path: Path, payload: dict) -> str:
    schema = str(payload.get("schema") or "")
    if schema:
        return schema
    name = path.name.lower()
    if name == "model_ready_status.json":
        return "hermes-revit-model-ready-status/v1"
    if name == "supervision_log.json":
        return "hermes-revit-supervision-log/v1"
    if name == "supervision_endurance_audit.json":
        return "hermes-revit-supervision-endurance-audit/v1"
    if name == "supervision_endurance_matrix.json":
        return "hermes-revit-supervision-endurance-matrix/v1"
    if name.endswith("task_journal.jsonl"):
        return "hermes-revit-task-journal/v1"
    return ""


def _completion_artifact_summary(artifact: dict, sandbox: Path) -> dict:
    payload = artifact["payload"]
    schema = artifact["schema"]
    private = "approval-material" in schema
    return {
        "path": str(artifact["path"]),
        "relative_path": _safe_relative_path(artifact["path"], sandbox),
        "schema": schema,
        "status": payload.get("status") or payload.get("stop_reason") or payload.get("checkpoint_status"),
        "success": payload.get("success"),
        "read_only": payload.get("read_only"),
        "planned_only": payload.get("planned_only"),
        "goal_complete": payload.get("goal_complete"),
        "may_call_update_goal": payload.get("may_call_update_goal"),
        "created_at": payload.get("created_at") or payload.get("started_at") or payload.get("audit_timestamp"),
        "private_payload_withheld": private,
        "signals": _completion_artifact_signals(artifact),
        "bytes": artifact.get("bytes"),
    }


def _completion_artifact_signals(artifact: dict) -> dict:
    payload = artifact["payload"]
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    execution_receipt = execution.get("receipt") if isinstance(execution.get("receipt"), dict) else {}
    return {
        "approval_required_count": payload.get("approval_required_count"),
        "blocked_count": payload.get("blocked_count"),
        "prompt_event_count": len(payload.get("prompt_events") or []) if isinstance(payload.get("prompt_events"), list) else None,
        "ready": payload.get("ready"),
        "check_count": payload.get("check_count"),
        "target_met": payload.get("target_met"),
        "execute_requested": payload.get("execute_requested"),
        "executed": execution.get("executed"),
        "ui_action_executed": receipt.get("ui_action_executed"),
        "model_write_guard": execution_receipt.get("model_write_guard"),
        "post_action_refresh_success": execution_receipt.get("post_action_refresh_success"),
    }


def _completion_checklist(
    artifacts: list[dict],
    *,
    audit_path: Path,
    objective: str,
    target_hours: float,
) -> list[dict]:
    rows: list[dict] = []
    for requirement in AGENT_REQUIREMENTS:
        for index, criterion in enumerate(requirement["success_criteria"], start=1):
            evidence, gap = _completion_criterion_evidence(
                artifacts,
                requirement["id"],
                index,
                audit_path=audit_path,
                objective=objective,
                target_hours=target_hours,
            )
            rows.append(
                {
                    "id": f"{requirement['id']}:criterion-{index}",
                    "requirement_id": requirement["id"],
                    "requirement": requirement["requirement"],
                    "criterion_index": index,
                    "success_criterion": criterion,
                    "satisfied": bool(evidence) and not gap,
                    "evidence": evidence,
                    "gap": gap,
                }
            )
    return rows


def _completion_criterion_evidence(
    artifacts: list[dict],
    requirement_id: str,
    criterion_index: int,
    *,
    audit_path: Path,
    objective: str,
    target_hours: float,
) -> tuple[list[dict], str]:
    if requirement_id == "arbitrary-ui-flows":
        if criterion_index == 1:
            evidence = _artifact_evidence(
                _artifacts_by_schema(artifacts, "hermes-revit-agent-ui-flow-scout/v1"),
                "UI scout artifacts plan unknown UI work from observation without clicking.",
            )
            return evidence, "" if evidence else "No agent-ui-flow-scout artifact was found."
        if criterion_index == 2:
            evidence = [
                {
                    "source": "code",
                    "path": "tools/revit_operator/ui_workflows.py",
                    "reason": f"{len(UI_WORKFLOWS)} reusable UI workflow recipes are available.",
                }
            ] if UI_WORKFLOWS else []
            evidence.extend(
                _artifact_evidence(
                    _artifacts_by_schema(artifacts, "hermes-revit-workflow-template/v1"),
                    "Recorded workflow templates are available for replay planning.",
                )
            )
            return evidence, "" if evidence else "No reusable UI workflow recipe or workflow template evidence was found."
        if criterion_index == 3:
            evidence = _artifact_evidence(
                _executed_ui_artifacts(artifacts),
                "Executed UI artifacts include fresh pre-action observation/preflight data.",
            )
            return evidence, "" if evidence else "No executed approval-gated UI artifact with fresh observation was found."
        if criterion_index == 4:
            evidence = _artifact_evidence(
                _approved_executed_ui_artifacts(artifacts),
                "UI execution required an exact approval phrase/token binding.",
            )
            return evidence, "" if evidence else "No executed UI action with exact approval confirmation evidence was found."
        evidence = _artifact_evidence(
            _ui_before_after_artifacts(artifacts),
            "Executed UI artifact carries before/action-result evidence.",
        )
        return evidence, "" if evidence else "No executed UI artifact with before/action-result evidence was found."

    if requirement_id == "approved-model-changing-work":
        if criterion_index == 1:
            evidence = _artifact_evidence(
                _model_change_planning_artifacts(artifacts),
                "Approval/session plans classify model-changing requests as approval-required or blocked.",
            )
            return evidence, "" if evidence else "No model-change approval planning artifact was found."
        if criterion_index == 2:
            evidence = _artifact_evidence(
                _executed_model_change_artifacts(artifacts, require_guard=True),
                "Executed model-change artifact includes allow-model-write/sync guard evidence.",
            )
            return evidence, "" if evidence else "No executed model-change artifact with write guards was found."
        if criterion_index == 3:
            evidence = _artifact_evidence(
                _executed_model_change_artifacts(artifacts, require_bridge_queue=True),
                "Executed model-change artifact queued work through the guarded bridge/API path.",
            )
            return evidence, "" if evidence else "No executed model-change bridge/API result was found."
        if criterion_index == 4:
            evidence = _artifact_evidence(
                _executed_model_change_artifacts(artifacts, require_post_document=True),
                "Executed model-change artifact includes payload/result and post-action document refresh.",
            )
            return evidence, "" if evidence else "No executed model-change receipt with final model state was found."
        unsafe = _unsafe_write_signal_artifacts(artifacts)
        if unsafe:
            return _artifact_evidence(unsafe, "Unsafe write signal found."), "One or more artifacts report unsafe save/sync/publish/delete behavior."
        return [
            {
                "source": "audit-scan",
                "path": str(audit_path),
                "reason": "No save/sync/publish/production-write signal was found in loaded artifacts.",
            }
        ], ""

    if requirement_id == "model-open-prompt-choreography":
        if criterion_index == 1:
            evidence = _artifact_evidence(
                _model_open_version_artifacts(artifacts),
                "Model-open choreography includes an expected Revit version.",
            )
            return evidence, "" if evidence else "No model-open choreography artifact with Revit version evidence was found."
        if criterion_index == 2:
            evidence = _artifact_evidence(
                _safe_local_model_open_artifacts(artifacts),
                "Model-open artifact references a copied local model under the safe project root.",
            )
            return evidence, "" if evidence else "No model-open artifact proves the model path is under the safe copied project root."
        if criterion_index == 3:
            evidence = _artifact_evidence(
                _prompt_event_artifacts(artifacts),
                "Model-open choreography observed startup/open prompt events.",
            )
            return evidence, "" if evidence else "No live model-open/startup prompt event artifact was found."
        if criterion_index == 4:
            evidence = _artifact_evidence(
                _classified_prompt_artifacts(artifacts),
                "Prompt artifacts include classifier/approval-plan decisions.",
            )
            return evidence, "" if evidence else "No prompt classifier/approval-plan artifact for model-open prompts was found."
        evidence = _artifact_evidence(
            _model_ready_artifacts(artifacts),
            "Model readiness/active-document verification succeeded after open.",
        )
        return evidence, "" if evidence else "No model-ready or active-document verification artifact was found."

    if requirement_id == "multi-hour-task-planning":
        if criterion_index == 1:
            required = [
                ("hermes-revit-agent-session-plan/v1", "session plan"),
                ("hermes-revit-agent-session-checkpoint/v1", "checkpoint"),
                ("hermes-revit-agent-session-resume-plan/v1", "resume plan"),
            ]
            evidence = []
            missing = []
            for schema, label in required:
                found = _artifacts_by_schema(artifacts, schema)
                if found:
                    evidence.extend(_artifact_evidence(found[:1], f"Found {label} evidence."))
                else:
                    missing.append(label)
            return evidence, "" if not missing else "Missing " + ", ".join(missing) + " artifact evidence."
        if criterion_index == 2:
            evidence = _artifact_evidence(
                _supervision_log_artifacts(artifacts),
                "Supervision logs contain periodic read-only observations.",
            )
            return evidence, "" if evidence else "No live supervision log with periodic observations was found."
        if criterion_index == 3:
            evidence = _artifact_evidence(
                _supervision_stop_gate_artifacts(artifacts),
                "Supervision artifacts demonstrate stop-on-modal/stall/unknown-state behavior.",
            )
            return evidence, "" if evidence else "No supervision stop/recovery matrix or live stop artifact was found."
        if criterion_index == 4:
            return [
                {
                    "source": "current-audit",
                    "path": str(audit_path),
                    "reason": f"This audit maps the objective to concrete sandbox artifacts: {objective}",
                }
            ], ""
        evidence = [
            {
                "source": "current-audit",
                "path": str(audit_path),
                "reason": "This audit sets goal_complete and may_call_update_goal from strict evidence gates only.",
            }
        ]
        return evidence, ""

    return [], "Unknown requirement criterion."


def _completion_requirement_summaries(checklist: list[dict]) -> list[dict]:
    summaries = []
    for requirement in AGENT_REQUIREMENTS:
        rows = [row for row in checklist if row["requirement_id"] == requirement["id"]]
        satisfied = [row for row in rows if row.get("satisfied")]
        summaries.append(
            {
                "id": requirement["id"],
                "requirement": requirement["requirement"],
                "satisfied": len(satisfied) == len(rows),
                "satisfied_criteria": len(satisfied),
                "total_criteria": len(rows),
                "missing_criteria": [
                    {
                        "criterion_index": row["criterion_index"],
                        "success_criterion": row["success_criterion"],
                        "gap": row["gap"],
                    }
                    for row in rows
                    if not row.get("satisfied")
                ],
            }
        )
    return summaries


def _completion_hard_gates(artifacts: list[dict], *, target_hours: float) -> list[dict]:
    ui_ready = _ready_ui_artifacts(artifacts)
    model_change_ready = _ready_model_change_artifacts(artifacts)
    prompt_ready = _classified_prompt_artifacts(artifacts)
    active_supervision = _active_supervision_status_artifacts(artifacts)
    gates = [
        {
            "id": "arbitrary-ui-live-execution",
            "requirement_id": "arbitrary-ui-flows",
            "passed": bool(_artifacts_by_schema(artifacts, "hermes-revit-agent-ui-flow-scout/v1"))
            and bool(_approved_executed_ui_artifacts(artifacts)),
            "reason": "Requires both a UI scout and an executed approved UI action artifact.",
            "readiness_evidence": _artifact_evidence(
                ui_ready,
                "A UI candidate dry-run is ready for explicit approval/execution.",
            ),
            "next_required_real_condition": "Execute an approved UI item with the exact confirmation phrase.",
        },
        {
            "id": "approved-model-change-live-execution",
            "requirement_id": "approved-model-changing-work",
            "passed": bool(_executed_model_change_artifacts(artifacts, require_post_document=True)),
            "reason": "Requires an executed approved model-change receipt with post-action document evidence.",
            "readiness_evidence": _artifact_evidence(
                model_change_ready,
                "A model-change dry-run is ready for explicit approval/execution.",
            ),
            "next_required_real_condition": "Execute an approved model-change item with exact confirmation and guard flags.",
        },
        {
            "id": "model-open-full-prompt-and-ready",
            "requirement_id": "model-open-prompt-choreography",
            "passed": bool(_prompt_event_artifacts(artifacts))
            and bool(_classified_prompt_artifacts(artifacts))
            and bool(_model_ready_artifacts(artifacts)),
            "reason": "Requires prompt events, prompt classification/approval handling, and model-ready verification.",
            "readiness_evidence": _artifact_evidence(
                prompt_ready,
                "Prompt classification/approval material exists, but live prompt execution/readiness is not fully proven.",
            ),
            "next_required_real_condition": "Observe a real model-open/startup prompt sequence and verify model readiness after approved handling.",
        },
        {
            "id": "multi-hour-live-supervision-target",
            "requirement_id": "multi-hour-task-planning",
            "passed": bool(_endurance_target_artifacts(artifacts, target_hours=target_hours)),
            "reason": f"Requires a supervision-endurance-audit target_met artifact for at least {target_hours:g} hours.",
            "readiness_evidence": _artifact_evidence(
                active_supervision,
                "A supervision status artifact shows active observation or partial endurance progress.",
            ),
            "next_required_real_condition": "Let live supervision continue until the endurance audit target is met.",
        },
    ]
    return gates


def _completion_next_commands(objective: str, *, target_hours: float) -> list[str]:
    return [
        _command(["agent-session-evidence-refresh", "--objective", objective, "--target-hours", str(target_hours)]),
        _command(["agent-session-supervision-status", "--target-hours", str(target_hours)]),
        _command(["agent-session-checkpoint", "--objective", objective]),
        _command(["agent-session-resume-plan", "--checkpoint", "<agent_session_checkpoint.json>"]),
        _command(["agent-ui-flow-scout", "--objective", objective, "--include-uia"]),
        _command(["agent-ui-flow-approval-plan", "--scout", "<agent_ui_flow_scout.json>"]),
        _command(
            [
                "agent-ui-flow-execute-approved-candidate",
                "--approval-material",
                "<agent_ui_flow_approval_private_material.json>",
                "--item-id",
                "<ui-candidate-id>",
            ]
        ),
        _command(["agent-model-open-choreography", "--model", "<copied-local-model>", "--revit-version", "2025"]),
        _command(["agent-model-open-prompt-approval-plan", "--choreography", "<model_open_choreography.json>"]),
        _command(["agent-session-approval-plan", "--objective", objective]),
        _command(["agent-session-execute-approved-item", "--approval-material", "<agent_session_approval_private_material.json>", "--item-id", "<approval-item-id>"]),
        _command(["supervise-session", "--duration", str(int(max(0.1, target_hours) * 3600)), "--poll", "30", "--stop-on-modal"]),
        _command(["supervision-endurance-audit", "--target-hours", str(target_hours)]),
        _command(["agent-session-completion-audit", "--objective", objective]),
    ]


def _completion_command_check(command: str) -> dict:
    return {
        "command": command,
        "contains_execute_flag": "--execute" in command,
        "contains_approval_token": "APPROVE:" in command or "--approval-token" in command or "--approval-tokens-json" in command,
        "read_only": "--execute" not in command and "APPROVE:" not in command and "--approval-token" not in command and "--approval-tokens-json" not in command,
    }


def _real_gate_ledger_row(gate: dict, *, objective: str, target_hours: float) -> dict:
    readiness = gate.get("readiness_evidence") if isinstance(gate.get("readiness_evidence"), list) else []
    passed = bool(gate.get("passed"))
    status = (
        "passed"
        if passed
        else "ready_for_human_or_real_condition"
        if readiness
        else "blocked_missing_readiness_evidence"
    )
    actions = _real_gate_next_readonly_actions(gate, objective=objective, target_hours=target_hours)
    return {
        "id": gate.get("id"),
        "requirement_id": gate.get("requirement_id"),
        "passed": passed,
        "status": status,
        "reason": gate.get("reason"),
        "readiness_count": len(readiness),
        "readiness_evidence": readiness,
        "next_required_real_condition": None if passed else gate.get("next_required_real_condition"),
        "next_read_only_actions": actions,
        "next_actions_are_read_only": all(action.get("read_only") for action in actions),
    }


def _real_gate_next_readonly_actions(gate: dict, *, objective: str, target_hours: float) -> list[dict]:
    gate_id = str(gate.get("id") or "")
    if bool(gate.get("passed")):
        return []
    if gate_id == "arbitrary-ui-live-execution":
        return [
            _gate_action(
                "refresh-ui-candidates",
                _command(["agent-ui-flow-scout", "--objective", objective, "--include-uia"]),
                "Refresh the live UI candidate list before any human-approved UI action.",
            ),
            _gate_action(
                "dry-run-approved-ui-candidate",
                _command(
                    [
                        "agent-ui-flow-execute-approved-candidate",
                        "--approval-material",
                        "<agent_ui_flow_approval_private_material.json>",
                        "--item-id",
                        "<ui-candidate-id>",
                    ]
                ),
                "Dry-run a private approval item without --execute before requesting human confirmation.",
            ),
        ]
    if gate_id == "approved-model-change-live-execution":
        return [
            _gate_action(
                "refresh-model-change-approval-plan",
                _command(["agent-session-approval-plan", "--objective", objective]),
                "Refresh model-change approval material without queueing Revit work.",
            ),
            _gate_action(
                "dry-run-approved-model-change",
                _command(
                    [
                        "agent-session-execute-approved-item",
                        "--approval-material",
                        "<agent_session_approval_private_material.json>",
                        "--item-id",
                        "<approval-item-id>",
                        "--bridge-refresh-timeout",
                        "0",
                    ]
                ),
                "Dry-run the guarded model-change item without --execute or write guards.",
            ),
        ]
    if gate_id == "model-open-full-prompt-and-ready":
        return [
            _gate_action(
                "observe-model-open-choreography",
                _command(
                    [
                        "agent-model-open-choreography",
                        "--model",
                        "<copied-local-model>",
                        "--revit-version",
                        "2025",
                    ]
                ),
                "Observe model-open prompt choreography against a copied local model.",
            ),
            _gate_action(
                "plan-model-open-prompt-approval",
                _command(
                    [
                        "agent-model-open-prompt-approval-plan",
                        "--choreography",
                        "<model_open_choreography.json>",
                    ]
                ),
                "Classify observed model-open prompts and prepare approval material.",
            ),
            _gate_action(
                "verify-model-ready",
                _command(["wait-model-ready", "--timeout", "0"]),
                "Verify active-document readiness after approved prompt handling.",
            ),
        ]
    if gate_id == "multi-hour-live-supervision-target":
        return [
            _gate_action(
                "refresh-supervision-status",
                _command(["agent-session-supervision-status", "--target-hours", str(target_hours)]),
                "Refresh active supervision process/log status.",
            ),
            _gate_action(
                "audit-supervision-endurance",
                _command(["supervision-endurance-audit", "--target-hours", str(target_hours)]),
                "Check whether accumulated live observation has met the endurance target.",
            ),
        ]
    return [
        _gate_action(
            "refresh-evidence",
            _command(["agent-session-evidence-refresh", "--objective", objective, "--target-hours", str(target_hours)]),
            "Refresh read-only evidence for this gate.",
        )
    ]


def _gate_action(kind: str, command: str, reason: str) -> dict:
    check = _completion_command_check(command)
    return {
        "kind": kind,
        "command": command,
        "read_only": check["read_only"],
        "contains_execute_flag": check["contains_execute_flag"],
        "contains_approval_token": check["contains_approval_token"],
        "reason": reason,
    }


def _supervision_status_summary(status: dict | None) -> dict:
    if not isinstance(status, dict):
        return {"refreshed": False}
    audit = status.get("endurance_audit") if isinstance(status.get("endurance_audit"), dict) else {}
    return {
        "refreshed": True,
        "path": status.get("path"),
        "markdown_path": status.get("markdown_path"),
        "status": status.get("status"),
        "reason": status.get("reason"),
        "target_hours": status.get("target_hours"),
        "active_supervision_count": status.get("active_supervision_count"),
        "log_count": status.get("log_count"),
        "target_met": audit.get("target_met"),
        "total_live_hours": audit.get("total_live_hours"),
        "qualifying_log_count": audit.get("qualifying_log_count"),
    }


def _artifacts_by_schema(artifacts: list[dict], *schemas: str) -> list[dict]:
    wanted = set(schemas)
    return [artifact for artifact in artifacts if artifact.get("schema") in wanted]


def _artifact_evidence(artifacts: list[dict], reason: str, *, limit: int = 5) -> list[dict]:
    return [
        {
            "source": "artifact",
            "path": str(artifact["path"]),
            "schema": artifact.get("schema") or "",
            "status": artifact["payload"].get("status")
            or artifact["payload"].get("stop_reason")
            or artifact["payload"].get("checkpoint_status"),
            "reason": reason,
        }
        for artifact in artifacts[:limit]
    ]


def _executed_ui_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in artifacts:
        payload = artifact["payload"]
        schema = artifact.get("schema")
        if schema == "hermes-revit-agent-ui-flow-approved-candidate/v1":
            receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
            if payload.get("execute_requested") and receipt.get("ui_action_executed"):
                result.append(artifact)
        if schema == "hermes-revit-agent-session-approved-item/v1" and payload.get("item_kind") == "ui-workflow-step":
            execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
            if payload.get("execute_requested") and execution.get("executed"):
                result.append(artifact)
    return result


def _approved_executed_ui_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in _executed_ui_artifacts(artifacts):
        payload = artifact["payload"]
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
        if payload.get("confirmation_ok") or execution.get("confirmation_ok") or receipt.get("approval_bound_to_private_item"):
            result.append(artifact)
    return result


def _ready_ui_artifacts(artifacts: list[dict]) -> list[dict]:
    return [
        artifact
        for artifact in artifacts
        if artifact.get("schema") == "hermes-revit-agent-ui-flow-approved-candidate/v1"
        and artifact["payload"].get("status") == "ready_for_approval_execution"
        and not artifact["payload"].get("execute_requested")
    ]


def _ui_before_after_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in _executed_ui_artifacts(artifacts):
        payload = artifact["payload"]
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        if payload.get("pre_action_observation") and payload.get("action_result"):
            result.append(artifact)
        elif execution.get("workflow_result"):
            result.append(artifact)
    return result


def _model_change_planning_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in artifacts:
        payload = artifact["payload"]
        schema = artifact.get("schema")
        if schema == "hermes-revit-agent-session-approval-plan/v1" and (
            payload.get("approval_required_count") or payload.get("blocked_count")
        ):
            result.append(artifact)
        if schema == "hermes-revit-agent-session-plan/v1" and payload.get("model_change_requests"):
            result.append(artifact)
    return result


def _ready_model_change_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in artifacts:
        payload = artifact["payload"]
        if artifact.get("schema") != "hermes-revit-agent-session-approved-item/v1":
            continue
        if payload.get("item_kind") != "model-change-operation":
            continue
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        if payload.get("status") == "ready_for_approval_execution" and not payload.get("execute_requested"):
            result.append(artifact)
    return result


def _executed_model_change_artifacts(
    artifacts: list[dict],
    *,
    require_guard: bool = False,
    require_bridge_queue: bool = False,
    require_post_document: bool = False,
) -> list[dict]:
    result = []
    for artifact in artifacts:
        payload = artifact["payload"]
        if artifact.get("schema") != "hermes-revit-agent-session-approved-item/v1":
            continue
        if payload.get("item_kind") != "model-change-operation" or not payload.get("execute_requested"):
            continue
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        receipt = execution.get("receipt") if isinstance(execution.get("receipt"), dict) else {}
        if not execution.get("executed"):
            continue
        if require_guard and not receipt.get("model_write_guard"):
            continue
        if require_bridge_queue and not receipt.get("queued_operation"):
            continue
        if require_post_document and not (receipt.get("post_action_refresh_success") and execution.get("post_action_active_document")):
            continue
        result.append(artifact)
    return result


def _unsafe_write_signal_artifacts(artifacts: list[dict]) -> list[dict]:
    unsafe = []
    for artifact in artifacts:
        payload = artifact["payload"]
        if _nested_true_key(payload, {"save_sync_publish_performed", "production_write_performed"}):
            unsafe.append(artifact)
            continue
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        receipt = execution.get("receipt") if isinstance(execution.get("receipt"), dict) else {}
        operation = str(receipt.get("requested_operation") or receipt.get("queued_operation") or "").lower()
        if execution.get("executed") and operation in {"save", "sync", "synchronize-with-central", "delete", "publish"}:
            unsafe.append(artifact)
    return unsafe


def _model_open_version_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in _artifacts_by_schema(artifacts, "hermes-revit-model-open-choreography/v1"):
        expectations = artifact["payload"].get("expectations") if isinstance(artifact["payload"].get("expectations"), dict) else {}
        if expectations.get("expected_revit_version"):
            result.append(artifact)
    return result


def _safe_local_model_open_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in _artifacts_by_schema(artifacts, "hermes-revit-model-open-choreography/v1"):
        model_path = artifact["payload"].get("model_path")
        if model_path and _path_is_under_safe_project_root(str(model_path)):
            result.append(artifact)
    return result


def _prompt_event_artifacts(artifacts: list[dict]) -> list[dict]:
    return [
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-model-open-choreography/v1")
        if isinstance(artifact["payload"].get("prompt_events"), list) and artifact["payload"].get("prompt_events")
    ]


def _classified_prompt_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in _prompt_event_artifacts(artifacts):
        events = artifact["payload"].get("prompt_events") or []
        if any(isinstance(event, dict) and event.get("plans") for event in events):
            result.append(artifact)
    result.extend(
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-model-open-prompt-approval-plan/v1")
        if artifact["payload"].get("approval_required_count") is not None or artifact["payload"].get("manual_required_count") is not None
    )
    return result


def _model_ready_artifacts(artifacts: list[dict]) -> list[dict]:
    result = []
    for artifact in artifacts:
        payload = artifact["payload"]
        schema = artifact.get("schema")
        if schema == "hermes-revit-model-ready-status/v1" and payload.get("ready"):
            result.append(artifact)
        elif schema == "hermes-revit-model-open-choreography/v1" and payload.get("status") == "model_ready":
            result.append(artifact)
    return result


def _supervision_log_artifacts(artifacts: list[dict]) -> list[dict]:
    return [
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-supervision-log/v1")
        if int(artifact["payload"].get("check_count") or 0) > 0
    ]


def _supervision_stop_gate_artifacts(artifacts: list[dict]) -> list[dict]:
    result = [
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-supervision-endurance-matrix/v1")
        if artifact["payload"].get("success")
    ]
    result.extend(
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-supervision-log/v1")
        if str(artifact["payload"].get("stop_reason") or "")
        in {"modal_state_detected", "stalled_state_detected", "unknown_state_detected"}
    )
    return result


def _endurance_target_artifacts(artifacts: list[dict], *, target_hours: float) -> list[dict]:
    result = []
    for artifact in _artifacts_by_schema(artifacts, "hermes-revit-supervision-endurance-audit/v1"):
        payload = artifact["payload"]
        if payload.get("target_met") and float(payload.get("target_hours") or 0.0) >= target_hours:
            result.append(artifact)
    return result


def _active_supervision_status_artifacts(artifacts: list[dict]) -> list[dict]:
    return [
        artifact
        for artifact in _artifacts_by_schema(artifacts, "hermes-revit-agent-session-supervision-status/v1")
        if artifact["payload"].get("status") in {"active", "target_met"}
        or int(artifact["payload"].get("active_supervision_count") or 0) > 0
    ]


def _nested_true_key(value, names: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in names and child is True:
                return True
            if _nested_true_key(child, names):
                return True
    if isinstance(value, list):
        return any(_nested_true_key(child, names) for child in value)
    return False


def _path_is_under_safe_project_root(raw_path: str) -> bool:
    try:
        path = Path(raw_path).resolve(strict=False)
        safe_root = SAFE_PROJECT_ROOT.resolve(strict=False)
        return path == safe_root or path.is_relative_to(safe_root)
    except Exception:
        return False


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except Exception:
        return str(path)


def _build_phases(
    *,
    objective_text: str,
    intents: dict,
    candidate_workflows: list[dict],
    model_change_requests: list[dict],
    model_path: str,
    expected_revit_version: str,
    expected_title_contains: str,
    max_hours: float,
    parameters: dict,
) -> list[dict]:
    phases = [
        {
            "id": "session-preflight",
            "status": "ready_to_plan",
            "risk": "low",
            "requires_approval": False,
            "purpose": "Create a fresh observation baseline and confirm the sandbox/operator are usable.",
            "commands": [
                "health",
                "status",
                "list-dialogs",
                "bridge-readiness",
                "verify-bridge-build",
            ],
            "evidence_required": ["status JSON", "dialog list", "bridge readiness artifact", "journal entry"],
        }
    ]
    if intents.get("model_open") or model_path:
        phases.append(
            {
                "id": "model-open-prompt-choreography",
                "status": "approval_gated" if model_path else "needs_model_path",
                "risk": "high",
                "requires_approval": True,
                "purpose": "Open a copied local model, classify startup/open prompts, and verify the active document.",
                "commands": _model_open_commands(model_path, expected_revit_version, expected_title_contains),
                "prompt_classes": [
                    "unsigned add-in",
                    "upgrade model",
                    "detach from central",
                    "preserve/discard worksets",
                    "missing/reload links",
                    "worksharing prompts",
                ],
                "approval_gates": [
                    "open-model execution",
                    "upgrade",
                    "detach/preserve worksets",
                    "unknown dialog button",
                    "close/restart/save/sync",
                ],
                "evidence_required": [
                    "open-model dry run",
                    "dialog classification JSON for every prompt",
                    "model_ready_status.json",
                    "active document bridge payload",
                ],
            }
        )
    if candidate_workflows:
        phases.append(
            {
                "id": "ui-workflow-routing",
                "status": "recipe_candidates_ready",
                "risk": "high",
                "requires_approval": any(wf.get("approval_required_steps") for wf in candidate_workflows),
                "purpose": "Route known UI tasks through reusable workflow recipes; unknown UI remains a recording/planning task.",
                "commands": [
                    _command(["agent-ui-flow-scout", "--objective", objective_text]),
                    _command(["agent-ui-flow-approval-plan", "--scout", "<agent_ui_flow_scout.json>"]),
                    _command(
                        [
                            "agent-ui-flow-execute-approved-candidate",
                            "--approval-material",
                            "<agent_ui_flow_approval_private_material.json>",
                            "--item-id",
                            "<ui-candidate-id>",
                        ]
                    ),
                    *[wf["plan_command"] for wf in candidate_workflows],
                ],
                "candidate_workflows": [
                    {
                        "name": wf["name"],
                        "category": wf["category"],
                        "missing_parameters": wf["missing_parameters"],
                        "approval_required_steps": wf["approval_required_steps"],
                    }
                    for wf in candidate_workflows
                ],
                "evidence_required": ["ui_workflow_plan.json", "before/after observations for executed steps"],
            }
        )
    if intents.get("model_change") or model_change_requests:
        phases.append(
            {
                "id": "approved-model-changing-work",
                "status": "approval_gated",
                "risk": "critical",
                "requires_approval": True,
                "purpose": "Prepare guarded Revit API/bridge operation requests without executing model writes.",
                "commands": [request["dry_run_command"] for request in model_change_requests]
                or ["request-operation --operation <operation>"],
                "model_change_requests": model_change_requests,
                "blocked_by_default": ["save", "sync", "publish", "delete", "production/cloud/central writes"],
                "evidence_required": [
                    "fresh dry-run policy with exact payload",
                    "human approval token",
                    "bridge command result",
                    "post-action active document status",
                ],
            }
        )
    phases.append(
        {
            "id": "multi-hour-supervision",
            "status": "planned",
            "risk": "low",
            "requires_approval": False,
            "purpose": "Keep a long-running task observable, resumable, and auditable.",
            "commands": [
                _command(["agent-session-evidence-refresh", "--objective", objective_text]),
                _command(["agent-session-supervision-status", "--target-hours", str(max_hours)]),
                _command(["agent-session-checkpoint", "--objective", objective_text]),
                _command(["agent-session-resume-plan", "--checkpoint", "<agent_session_checkpoint.json>"]),
                f"supervise-session --duration {int(max(0.1, max_hours) * 3600)} --poll 30 --stop-on-modal",
                f"supervision-endurance-audit --target-hours {max_hours}",
            ],
            "checkpoint_policy": {
                "checkpoint_minutes": 15,
                "stop_on_modal": True,
                "stop_on_unknown_state": True,
                "capture_recovery_snapshot_on_stall": True,
                "resume_requires_fresh_status": True,
            },
            "evidence_required": [
                "supervision_log.json",
                "state transition log",
                "recovery snapshot on stall/modal",
                "final prompt-to-artifact checklist",
            ],
        }
    )
    phases.append(
        {
            "id": "completion-audit",
            "status": "blocked_until_all_evidence_exists",
            "risk": "low",
            "requires_approval": False,
            "purpose": "Refuse done/complete until every requirement maps to current evidence.",
            "commands": ["agent-session-completion-audit"],
            "evidence_required": [
                "all checklist rows satisfied",
                "no blocker rows",
                "fresh live artifacts, not just static manifests",
            ],
        }
    )
    return phases


def _model_open_commands(model_path: str, expected_revit_version: str, expected_title_contains: str) -> list[str]:
    commands = ["list-revit-installs"]
    if model_path:
        open_args = ["open-model", "--model", model_path]
        if expected_revit_version:
            open_args.extend(["--revit-version", expected_revit_version])
        commands.append(_command(open_args))
        choreography_args = ["agent-model-open-choreography", "--model", model_path]
        if expected_revit_version:
            choreography_args.extend(["--revit-version", expected_revit_version])
        if expected_title_contains:
            choreography_args.extend(["--expected-title-contains", expected_title_contains])
        commands.append(_command(choreography_args))
        commands.append(
            _command(["agent-model-open-prompt-approval-plan", "--choreography", "<model_open_choreography.json>"])
        )
    else:
        commands.append("open-model --model <copied-local-model>")
        commands.append("agent-model-open-choreography --model <copied-local-model>")
        commands.append("agent-model-open-prompt-approval-plan --choreography <model_open_choreography.json>")
    commands.extend(
        [
            "wait-for-dialog --timeout 5",
            "plan-current-dialog-response",
            "list-dialogs",
            _command(
                [
                    "wait-model-ready",
                    *(
                        ["--expected-revit-version", expected_revit_version]
                        if expected_revit_version
                        else []
                    ),
                    *(
                        ["--expected-title-contains", expected_title_contains]
                        if expected_title_contains
                        else []
                    ),
                ]
            ),
        ]
    )
    return commands


def _requirement_coverage(intents: dict, candidate_workflows: list[dict], model_change_requests: list[dict]) -> list[dict]:
    rows = []
    for requirement in AGENT_REQUIREMENTS:
        req_id = requirement["id"]
        status = "partial"
        evidence = []
        blockers = []
        if req_id == "arbitrary-ui-flows":
            evidence = [
                "agent-ui-flow-scout observation-only candidate discovery",
                "UI workflow recipe library",
                "run-ui-workflow step gates",
                "workflow replay memory",
            ]
            blockers = [
                "Arbitrary unknown UI can now be scouted, but successful execution still requires fresh approval-gated steps or recipe authoring.",
                "Live breadth across ribbon, dialogs, context menus, and add-in panels is not proven by this plan.",
            ]
            if candidate_workflows:
                evidence.append("objective matched candidate UI workflow recipes")
        elif req_id == "approved-model-changing-work":
            evidence = ["request-operation safety policy", "allow-model-write and allow-sync guards"]
            blockers = [
                "This plan does not execute model-changing work.",
                "Fresh approval tokens and post-action live verification are required per operation.",
            ]
            if model_change_requests:
                evidence.append("objective mapped to guarded model-change operation candidates")
        elif req_id == "model-open-prompt-choreography":
            evidence = ["open-model dry-run", "dialog classifier", "wait-model-ready"]
            blockers = [
                "Full startup/open prompt sequences require live prompt evidence.",
                "Upgrade/detach/workset choices remain human approval gates.",
            ]
        elif req_id == "multi-hour-task-planning":
            evidence = ["supervise-session", "supervision-endurance-audit", "agent session checkpoint plan"]
            blockers = [
                "No multi-hour live endurance run is produced by this plan.",
                "Final done status requires a fresh prompt-to-artifact completion audit.",
            ]
        rows.append(
            {
                **requirement,
                "status": status,
                "satisfied": False,
                "current_evidence": evidence,
                "blockers": blockers,
                "intent_present": _requirement_intent_present(req_id, intents),
            }
        )
    return rows


def _requirement_intent_present(req_id: str, intents: dict) -> bool:
    return {
        "arbitrary-ui-flows": intents.get("ui_flow"),
        "approved-model-changing-work": intents.get("model_change"),
        "model-open-prompt-choreography": intents.get("model_open"),
        "multi-hour-task-planning": intents.get("long_running"),
    }.get(req_id, False)


def _prompt_to_artifact_checklist(requirements: list[dict], phases: list[dict]) -> list[dict]:
    rows = []
    for requirement in requirements:
        rows.append(
            {
                "id": f"requirement:{requirement['id']}",
                "requirement": requirement["requirement"],
                "expected_artifacts": requirement["success_criteria"],
                "evidence": requirement["current_evidence"],
                "satisfied": False,
                "blockers": requirement["blockers"],
            }
        )
    for phase in phases:
        rows.append(
            {
                "id": f"phase:{phase['id']}",
                "requirement": phase["purpose"],
                "expected_artifacts": phase.get("evidence_required", []),
                "evidence": phase.get("commands", []),
                "satisfied": phase["id"] == "session-preflight",
                "blockers": [] if phase["id"] == "session-preflight" else ["Phase has not been executed and verified."],
            }
        )
    return rows


def _completion_blockers(requirements: list[dict], checklist: list[dict]) -> list[dict]:
    blockers = []
    for requirement in requirements:
        for reason in requirement.get("blockers") or []:
            blockers.append(
                {
                    "id": requirement["id"],
                    "type": "requirement_not_satisfied",
                    "reason": reason,
                }
            )
    for row in checklist:
        if not row.get("satisfied"):
            blockers.append(
                {
                    "id": row["id"],
                    "type": "checklist_unsatisfied",
                    "reason": "Checklist row lacks live evidence.",
                }
            )
    return blockers


def _evidence_refresh_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Evidence Refresh",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Goal complete: `{str(result.get('goal_complete')).lower()}`",
        f"May call update_goal: `{str(result.get('may_call_update_goal')).lower()}`",
        f"Reason: {result.get('reason')}",
        "",
        "## Steps",
        "",
    ]
    for step in result.get("steps", []):
        lines.append(
            f"- `{step.get('id')}`: status=`{step.get('status')}` "
            f"success=`{str(step.get('success')).lower()}`"
        )
    completion = result.get("completion_audit") if isinstance(result.get("completion_audit"), dict) else {}
    lines.extend(
        [
            "",
            "## Completion Audit",
            "",
            f"- status: `{completion.get('status')}`",
            f"- blocked_count: `{completion.get('blocked_count')}`",
            f"- path: `{completion.get('path')}`",
        ]
    )
    lines.extend(["", "## Safety", ""])
    for key, value in result.get("safety_summary", {}).items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines) + "\n"


def _completion_audit_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Completion Audit",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Goal complete: `{str(result.get('goal_complete')).lower()}`",
        f"May call update_goal: `{str(result.get('may_call_update_goal')).lower()}`",
        f"Blocked count: `{result.get('blocked_count')}`",
        f"Reason: {result.get('reason')}",
        "",
        "## Objective",
        "",
        result.get("objective") or "",
        "",
        "## Requirement Coverage",
        "",
    ]
    for summary in result.get("requirement_summaries", []):
        lines.append(
            f"- `{summary.get('id')}`: satisfied=`{str(summary.get('satisfied')).lower()}` "
            f"({summary.get('satisfied_criteria')}/{summary.get('total_criteria')})"
        )
    lines.extend(["", "## Hard Gates", ""])
    for gate in result.get("hard_completion_gates", []):
        lines.append(f"- `{gate.get('id')}`: passed=`{str(gate.get('passed')).lower()}` - {gate.get('reason')}")
    lines.extend(["", "## Missing Evidence", ""])
    for item in result.get("blocked_items", [])[:50]:
        lines.append(f"- `{item.get('id')}`: {item.get('reason')}")
    for gate in result.get("blocked_gates", []):
        lines.append(f"- `{gate.get('id')}`: {gate.get('reason')}")
    if not result.get("blocked_items") and not result.get("blocked_gates"):
        lines.append("- None.")
    lines.extend(["", "## Next Read-Only Commands", ""])
    for command in result.get("next_recommended_commands", []):
        lines.append(f"- `{command}`")
    return "\n".join(lines) + "\n"


def _real_gate_ledger_markdown(result: dict) -> str:
    guard = result.get("execution_guard") if isinstance(result.get("execution_guard"), dict) else {}
    summary = result.get("gate_summary") if isinstance(result.get("gate_summary"), dict) else {}
    completion = result.get("completion_audit") if isinstance(result.get("completion_audit"), dict) else {}
    supervision = result.get("supervision_status") if isinstance(result.get("supervision_status"), dict) else {}
    lines = [
        "# Revit Agent Real Gate Ledger",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Goal complete: `{str(result.get('goal_complete')).lower()}`",
        f"May call update_goal: `{str(result.get('may_call_update_goal')).lower()}`",
        f"May execute from this result: `{str(guard.get('may_execute_from_this_result')).lower()}`",
        f"Reason: {result.get('reason')}",
        "",
        "## Completion Audit",
        "",
        f"- status: `{completion.get('status')}`",
        f"- blocked_count: `{completion.get('blocked_count')}`",
        f"- path: `{completion.get('path')}`",
        "",
        "## Supervision",
        "",
        f"- status: `{supervision.get('status')}`",
        f"- active_supervision_count: `{supervision.get('active_supervision_count')}`",
        f"- target_met: `{str(supervision.get('target_met')).lower()}`",
        f"- total_live_hours: `{supervision.get('total_live_hours')}`",
        "",
        "## Gate Summary",
        "",
        f"- total: `{summary.get('total')}`",
        f"- passed: `{summary.get('passed')}`",
        f"- ready_for_human_or_real_condition: `{summary.get('ready_for_human_or_real_condition')}`",
        f"- blocked_missing_readiness_evidence: `{summary.get('blocked_missing_readiness_evidence')}`",
        "",
        "## Real Gates",
        "",
    ]
    for gate in result.get("real_gates", []):
        lines.append(
            f"- `{gate.get('id')}`: status=`{gate.get('status')}` "
            f"readiness_count=`{gate.get('readiness_count')}`"
        )
        if gate.get("next_required_real_condition"):
            lines.append(f"  next: {gate.get('next_required_real_condition')}")
    lines.extend(["", "## Next Read-Only Actions", ""])
    for action in result.get("next_read_only_actions", []):
        lines.append(f"- `{action.get('command')}`")
    if not result.get("next_read_only_actions"):
        lines.append("- None.")
    lines.extend(["", "## Execution Guard", ""])
    for key in (
        "approval_tokens_included",
        "approval_phrases_included",
        "private_approval_material_withheld",
        "requires_fresh_human_confirmation_for_execution",
        "requires_fresh_pre_action_observation",
    ):
        lines.append(f"- {key}: `{str(guard.get(key)).lower()}`")
    return "\n".join(lines) + "\n"


def _plan_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Objective: {result.get('objective') or ''}",
        "Goal complete: `false`",
        f"Reason: {result['reason']}",
        "",
        "## Requirements",
        "",
    ]
    for req in result.get("requirements", []):
        lines.append(f"- `{req['id']}`: `{req['status']}`")
    lines.extend(["", "## Phases", ""])
    for phase in result.get("phases", []):
        lines.append(f"- `{phase['id']}`: `{phase['status']}`")
    lines.extend(["", "## Completion Blockers", ""])
    for blocker in result.get("completion_blockers", []):
        lines.append(f"- `{blocker['id']}`: {blocker['reason']}")
    return "\n".join(lines) + "\n"


def _run_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Run",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result['status']}`",
        "Goal complete: `false`",
        f"Reason: {result['reason']}",
        "",
        "## Steps",
        "",
    ]
    for step in result.get("steps", []):
        lines.append(f"- `{step.get('step')}`: success=`{str(step.get('success')).lower()}`")
    lines.extend(["", "## Safety", ""])
    for key, value in result.get("safety_summary", {}).items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines) + "\n"


def _approval_plan_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Session Approval Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Objective: {result.get('objective') or ''}",
        "Goal complete: `false`",
        f"Approval items: `{result.get('approval_required_count', 0)}`",
        f"Blocked items: `{result.get('blocked_count', 0)}`",
        "Approval material withheld from public plan: `true`",
        "",
        "## Approval Items",
        "",
    ]
    for item in result.get("approval_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('reason')}")
    if not result.get("approval_items"):
        lines.append("- None.")
    lines.extend(["", "## Blocked Items", ""])
    for item in result.get("blocked_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('reason')}")
    if not result.get("blocked_items"):
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _approved_item_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent Approved Item Result",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Item: `{result.get('item_id')}`",
        f"Kind: `{result.get('item_kind')}`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Execution",
        "",
    ]
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    for key in ("executed", "dry_run", "confirmation_required", "confirmation_ok"):
        lines.append(f"- {key}: `{str(execution.get(key)).lower()}`")
    return "\n".join(lines) + "\n"


def _ui_flow_scout_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent UI Flow Scout",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        "Read-only: `true`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Candidates",
        "",
    ]
    for candidate in result.get("candidates", []):
        lines.append(
            f"- `{candidate.get('target')}`: {candidate.get('recommended_action')} "
            f"(risk `{candidate.get('policy', {}).get('risk')}`)"
        )
    if not result.get("candidates"):
        lines.append("- None.")
    lines.extend(["", "## Next Actions", ""])
    for action in result.get("next_actions", []):
        command = action.get("command") or action.get("dry_run_command") or action.get("inspection_command") or ""
        lines.append(f"- `{action.get('recommended_action')}`: {command}")
    return "\n".join(lines) + "\n"


def _ui_flow_approval_plan_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent UI Flow Approval Plan",
        "",
        DRAFT_LABEL,
        "",
        f"Source scout: `{result.get('source_scout_path')}`",
        "Goal complete: `false`",
        f"Approval items: `{result.get('approval_required_count', 0)}`",
        f"Blocked items: `{result.get('blocked_count', 0)}`",
        "Approval material withheld from public plan: `true`",
        "",
        "## Approval Items",
        "",
    ]
    for item in result.get("approval_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('target')} ({item.get('reason')})")
    if not result.get("approval_items"):
        lines.append("- None.")
    lines.extend(["", "## Blocked Items", ""])
    for item in result.get("blocked_items", []):
        lines.append(f"- `{item.get('id')}`: {item.get('target')} ({item.get('reason')})")
    if not result.get("blocked_items"):
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _ui_flow_approved_candidate_markdown(result: dict) -> str:
    lines = [
        "# Revit Agent UI Flow Approved Candidate Result",
        "",
        DRAFT_LABEL,
        "",
        f"Status: `{result.get('status')}`",
        f"Item: `{result.get('item_id')}`",
        f"Target: `{result.get('target')}`",
        "Goal complete: `false`",
        f"Reason: {result.get('reason')}",
        "",
        "## Execution",
        "",
        f"- execute_requested: `{str(result.get('execute_requested')).lower()}`",
        f"- confirmation_required: `{str(result.get('confirmation_required')).lower()}`",
        f"- confirmation_ok: `{str(result.get('confirmation_ok')).lower()}`",
        f"- ui_action_executed: `{str(result.get('receipt', {}).get('ui_action_executed')).lower()}`",
        f"- model_write_performed: `{str(result.get('receipt', {}).get('model_write_performed')).lower()}`",
    ]
    return "\n".join(lines) + "\n"


def _write_json(path: Path, sandbox: Path, payload: dict) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, sandbox: Path, text: str) -> None:
    error = validate_output_path(path, sandbox)
    if error:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _command(parts: list[str]) -> str:
    return " ".join(_quote(part) for part in parts if str(part) != "")


def _quote(value: object) -> str:
    text = str(value)
    if not text:
        return "''"
    if re.search(r"\s|[{}\"']", text):
        return "'" + text.replace("'", "''") + "'"
    return text


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _without_approval_tokens(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            if str(key).lower() == "approval_token" and child:
                sanitized[key] = "<withheld; regenerate from fresh dry run>"
            else:
                sanitized[key] = _without_approval_tokens(child)
        return sanitized
    if isinstance(value, list):
        return [_without_approval_tokens(child) for child in value]
    if isinstance(value, str):
        redacted = re.sub(r"\bAPPROVE:[A-Za-z0-9_.:-]+\b", "<withheld approval token>", value)
        return re.sub(r"\bI approve\b", "<withheld approval phrase>", redacted, flags=re.IGNORECASE)
    return value
