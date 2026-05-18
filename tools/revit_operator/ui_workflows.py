"""Conservative reusable UI workflow recipes for Revit operator planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .journal import TaskJournal, utc_now
from .safety import APPROVAL_REQUIRED, BLOCK, classify_action, validate_output_path

MODAL_SAFE_COMMANDS = {
    "status",
    "list-dialogs",
    "plan-current-dialog-response",
    "recovery-snapshot",
    "screenshot",
    "ui-tree",
    "uia-tree",
    "wait-model-ready",
    "addin-security-preflight",
}

WORKFLOW_SMOKE_SAFE_COMMANDS = {
    "status",
    "list-dialogs",
    "plan-current-dialog-response",
    "addin-security-preflight",
    "bridge-readiness",
    "verify-bridge-build",
    "wait-model-ready",
    "project-browser-plan-navigation",
    "plan-ribbon-action",
    "plan-context-menu-action",
    "context-menu-snapshot",
    "recovery-snapshot",
}

WORKFLOW_SMOKE_DIAGNOSTIC_FALSE_OK = {
    "bridge-readiness",
    "verify-bridge-build",
    "plan-ribbon-action",
    "plan-context-menu-action",
    "plan-current-dialog-response",
}


@dataclass(frozen=True)
class WorkflowStepRecipe:
    command: str
    args: tuple[str, ...] = ()
    purpose: str = ""
    risk: str = "low"
    requires_approval: bool = False
    human_only: bool = False
    note: str = ""

    def render(self, parameters: dict) -> dict:
        rendered_args = [_render_template(arg, parameters) for arg in self.args]
        missing = sorted(_missing_placeholders([self.command, *self.args], parameters))
        payload = {"command": self.command, "args": rendered_args}
        decision = classify_action(self.command, _payload_from_args(rendered_args))
        return {
            "command": self.command,
            "args": rendered_args,
            "purpose": self.purpose,
            "risk": self.risk,
            "requires_approval": self.requires_approval or decision.decision == "approval_required",
            "human_only": self.human_only,
            "policy": decision.to_dict(),
            "missing_parameters": missing,
            "executable_by_plan": False,
            "note": self.note,
            "payload_hint": payload,
        }


@dataclass(frozen=True)
class UIWorkflowRecipe:
    name: str
    summary: str
    category: str
    parameters: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    blocked_actions: tuple[str, ...] = ()
    approval_gates: tuple[str, ...] = ()
    steps: tuple[WorkflowStepRecipe, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "category": self.category,
            "parameters": list(self.parameters),
            "preconditions": list(self.preconditions),
            "blocked_actions": list(self.blocked_actions),
            "approval_gates": list(self.approval_gates),
            "step_count": len(self.steps),
        }


UI_WORKFLOWS: dict[str, UIWorkflowRecipe] = {
    "unsigned-addin-startup-preflight": UIWorkflowRecipe(
        name="unsigned-addin-startup-preflight",
        summary="Verify and plan a safe response to the Revit unsigned Hermes add-in startup prompt.",
        category="startup",
        preconditions=("A Security - Unsigned Add-in prompt is visible or suspected.",),
        blocked_actions=("load unknown add-in", "Load Once", "Do Not Load", "restart Revit through Hermes"),
        approval_gates=(
            "Always Load requires addin-security-preflight verification and an exact click approval token.",
            "trust-addin execution requires a separate exact approval token.",
        ),
        steps=(
            WorkflowStepRecipe("list-dialogs", purpose="Confirm the visible startup dialog and button text."),
            WorkflowStepRecipe(
                "plan-current-dialog-response",
                args=("--title-contains", "Unsigned"),
                purpose="Classify the prompt and render the conservative response playbook.",
            ),
            WorkflowStepRecipe(
                "addin-security-preflight",
                args=("--revit-version", "2025"),
                purpose="Verify the manifest and DLL path before any load button is considered.",
            ),
            WorkflowStepRecipe(
                "click",
                args=("--target", "Always Load"),
                purpose="Dry-run the exact startup approval click only after preflight verification.",
                risk="high",
                requires_approval=True,
                note="Prefer trust-addin and restart. Execute this click only if a human approves unblocking the current startup.",
            ),
        ),
    ),
    "bridge-readiness-gate": UIWorkflowRecipe(
        name="bridge-readiness-gate",
        summary="Check whether the rebuilt Hermes add-in is installed and loaded before relying on bridge polling.",
        category="bridge",
        preconditions=("Revit may be open; this workflow is read-only.",),
        blocked_actions=("restart Revit through Hermes", "save", "sync", "close model"),
        approval_gates=("Human must decide when a Revit restart/reload is safe.",),
        steps=(
            WorkflowStepRecipe("bridge-readiness", purpose="Audit manifest, DLL, and loaded bridge payload."),
            WorkflowStepRecipe("verify-bridge-build", purpose="Verify loaded build metadata after restart/reload."),
            WorkflowStepRecipe("status", purpose="Confirm Revit is idle and no modal prompt is blocking."),
        ),
    ),
    "project-browser-open-sheet": UIWorkflowRecipe(
        name="project-browser-open-sheet",
        summary="Plan safe navigation to a sheet through metadata, with Project Browser OCR evidence as fallback.",
        category="project-browser",
        parameters=("sheet_number",),
        preconditions=("Metadata snapshot should be current.", "Project Browser should be visible if OCR evidence is desired."),
        blocked_actions=("coordinate click", "direct row activation without one exact UIA target"),
        approval_gates=("activate-view requires exact approval token before execution.",),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm Revit state before navigation."),
            WorkflowStepRecipe(
                "wait-model-ready",
                args=("--expected-revit-version", "2025"),
                purpose="Verify idle, non-modal active-document readiness before planning navigation.",
            ),
            WorkflowStepRecipe(
                "project-browser-plan-navigation",
                args=("--sheet-number", "{sheet_number}", "--include-uia", "--include-ocr", "--ocr-backend", "rapidocr"),
                purpose="Find one metadata-backed sheet match and capture OCR line evidence.",
            ),
            WorkflowStepRecipe(
                "request-operation",
                args=("--operation", "activate-view", "--args-json", '{"sheet_number":"{sheet_number}"}'),
                purpose="Dry-run guarded sheet activation only after the plan has one exact match.",
                risk="critical",
                requires_approval=True,
                note="Execute only with a fresh exact approval token from the dry-run payload.",
            ),
        ),
    ),
    "manage-links-inspection": UIWorkflowRecipe(
        name="manage-links-inspection",
        summary="Open and inspect Manage Links conservatively; do not reload, unload, repath, or remove links.",
        category="links",
        blocked_actions=("reload link", "reload from", "unload", "remove", "browse/repath", "OK/Apply after edits"),
        approval_gates=("Opening Manage Links is approval-gated.", "Any link action needs a separate human decision."),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm Revit is idle and no dialog is already active."),
            WorkflowStepRecipe("plan-ribbon-action", args=("--name", "manage-links-command"), purpose="Resolve the Manage Links UIA command."),
            WorkflowStepRecipe(
                "ribbon-action",
                args=("--name", "manage-links-command"),
                purpose="Dry-run opening Manage Links; execute only with exact approval.",
                risk="high",
                requires_approval=True,
            ),
            WorkflowStepRecipe("plan-current-dialog-response", purpose="Classify the resulting dialog after human-approved open."),
        ),
    ),
    "review-warnings-inspection": UIWorkflowRecipe(
        name="review-warnings-inspection",
        summary="Open Review Warnings for evidence capture; resolving/deleting warning causes remains human-only.",
        category="warnings",
        blocked_actions=("delete elements", "resolve warnings", "accept destructive warning resolution"),
        approval_gates=("Opening Review Warnings is approval-gated.", "Any resolution is human-only."),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm idle state before opening warning UI."),
            WorkflowStepRecipe("plan-ribbon-action", args=("--name", "review-warnings-command"), purpose="Resolve Review Warnings command."),
            WorkflowStepRecipe(
                "ribbon-action",
                args=("--name", "review-warnings-command"),
                purpose="Dry-run opening Review Warnings; execute only with exact approval.",
                risk="high",
                requires_approval=True,
            ),
            WorkflowStepRecipe("screenshot", purpose="Capture warning UI after human-approved open."),
            WorkflowStepRecipe("ui-tree", purpose="Capture accessible warning UI evidence."),
        ),
    ),
    "visibility-graphics-inspection": UIWorkflowRecipe(
        name="visibility-graphics-inspection",
        summary="Open Visibility/Graphics for inspection; do not apply view graphics changes automatically.",
        category="view-state",
        blocked_actions=("OK after changes", "Apply", "import/export view settings"),
        approval_gates=("Opening the dialog is approval-gated.", "Applying changes requires a separate human decision."),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm idle state before opening view UI."),
            WorkflowStepRecipe("plan-ribbon-action", args=("--name", "visibility-graphics-command"), purpose="Resolve Visibility/Graphics command."),
            WorkflowStepRecipe(
                "ribbon-action",
                args=("--name", "visibility-graphics-command"),
                purpose="Dry-run opening Visibility/Graphics; execute only with exact approval.",
                risk="high",
                requires_approval=True,
            ),
            WorkflowStepRecipe("plan-current-dialog-response", purpose="Classify the resulting dialog before any button."),
        ),
    ),
    "view-template-inspection": UIWorkflowRecipe(
        name="view-template-inspection",
        summary="Inspect view template UI without assigning, modifying, deleting, or applying templates.",
        category="view-state",
        blocked_actions=("assign template", "apply", "delete", "duplicate", "modify template"),
        approval_gates=("Opening template UI is approval-gated.", "Template edits are human-only."),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm idle state before opening template UI."),
            WorkflowStepRecipe("plan-ribbon-action", args=("--name", "view-templates-command"), purpose="Resolve View Templates command."),
            WorkflowStepRecipe(
                "ribbon-action",
                args=("--name", "view-templates-command"),
                purpose="Dry-run opening View Templates; execute only with exact approval.",
                risk="high",
                requires_approval=True,
            ),
            WorkflowStepRecipe("plan-current-dialog-response", purpose="Classify the resulting dialog before any button."),
        ),
    ),
    "context-menu-inspect-target": UIWorkflowRecipe(
        name="context-menu-inspect-target",
        summary="Open one exact target's context menu, snapshot items, and require a separate approval for any item selection.",
        category="context-menu",
        parameters=("target_name", "target_control_type"),
        blocked_actions=("select destructive menu item", "save", "delete", "hide/isolate without approval"),
        approval_gates=("Opening the menu changes UI focus and requires approval.", "Selecting an item is a separate approval-gated action."),
        steps=(
            WorkflowStepRecipe(
                "plan-context-menu-action",
                args=("--name", "visible-control-menu", "--target-name", "{target_name}", "--control-type", "{target_control_type}"),
                purpose="Resolve exactly one UIA target for context-menu opening.",
            ),
            WorkflowStepRecipe(
                "context-menu-action",
                args=("--name", "visible-control-menu", "--target-name", "{target_name}", "--control-type", "{target_control_type}"),
                purpose="Dry-run right-click opening; execute only with exact approval.",
                risk="high",
                requires_approval=True,
            ),
            WorkflowStepRecipe("context-menu-snapshot", purpose="Capture menu/menu-item evidence after human-approved open."),
        ),
    ),
    "modal-dialog-recovery": UIWorkflowRecipe(
        name="modal-dialog-recovery",
        summary="Classify and capture evidence for a blocking modal dialog without pressing a button.",
        category="recovery",
        blocked_actions=("unknown OK", "Save", "Don't Save", "Upgrade", "Detach", "Reload", "Delete Elements"),
        approval_gates=("Any dialog button needs a known playbook and fresh human approval unless explicitly low-risk.",),
        steps=(
            WorkflowStepRecipe("list-dialogs", purpose="Read visible modal dialog text/buttons."),
            WorkflowStepRecipe("plan-current-dialog-response", args=("--use-ocr", "--ocr-backend", "rapidocr"), purpose="Plan a conservative response with OCR fallback."),
            WorkflowStepRecipe("recovery-snapshot", purpose="Capture screenshot, UI tree, bridge state, and dialog recovery plans."),
        ),
    ),
    "readonly-qa-pass": UIWorkflowRecipe(
        name="readonly-qa-pass",
        summary="Run the current read-only QA workflow and record its journal as a reusable template.",
        category="qa",
        parameters=("workflow_name",),
        blocked_actions=("save", "sync", "reload links", "model modification"),
        approval_gates=("Any focus/idle nudge or view activation requires separate approval.",),
        steps=(
            WorkflowStepRecipe("status", purpose="Confirm no blocking dialog before QA."),
            WorkflowStepRecipe("wait-model-ready", purpose="Verify idle, non-modal active-document readiness before QA."),
            WorkflowStepRecipe("qa-workflow", purpose="Run active-document, metadata, UI evidence, and draft report collection."),
            WorkflowStepRecipe(
                "record-workflow",
                args=("--source-task-id", "<qa-task-id>", "--name", "{workflow_name}"),
                purpose="Record successful task journal after reviewing outputs.",
                note="Replace <qa-task-id> with the actual qa-workflow task id.",
            ),
        ),
    ),
}


def list_ui_workflows() -> dict:
    return {
        "success": True,
        "count": len(UI_WORKFLOWS),
        "workflows": [recipe.to_dict() for recipe in UI_WORKFLOWS.values()],
    }


def validate_ui_workflow_matrix(journal: TaskJournal) -> dict:
    """Validate reusable UI workflow recipes without running live Revit commands."""

    sample_parameters = {
        "sheet_number": "S2.0",
        "view_name": "STARTING VIEW",
        "target_name": "Project Browser",
        "target_control_type": "Pane",
        "workflow_name": "Live Readonly QA Workflow",
    }
    cases = []
    for name, recipe in UI_WORKFLOWS.items():
        parameters = {
            key: sample_parameters[key]
            for key in recipe.parameters
            if key in sample_parameters
        }
        planned_steps = [step.render(parameters) for step in recipe.steps]
        missing = sorted(
            {
                missing
                for step in planned_steps
                for missing in step.get("missing_parameters", [])
            }
        )
        approval_steps = [
            index
            for index, step in enumerate(planned_steps)
            if step.get("requires_approval")
            or (isinstance(step.get("policy"), dict) and step["policy"].get("decision") == APPROVAL_REQUIRED)
        ]
        blocked_steps = [
            index
            for index, step in enumerate(planned_steps)
            if isinstance(step.get("policy"), dict) and step["policy"].get("decision") == BLOCK
        ]
        manual_placeholder_steps = [
            index
            for index, step in enumerate(planned_steps)
            if _has_manual_placeholder(step.get("args", []))
        ]
        checks = [
            _matrix_check(
                "summary_present",
                bool(recipe.summary),
                "Recipe has a summary.",
                "Recipe is missing a summary.",
            ),
            _matrix_check(
                "category_present",
                bool(recipe.category),
                "Recipe has a category.",
                "Recipe is missing a category.",
            ),
            _matrix_check(
                "steps_present",
                bool(recipe.steps),
                "Recipe has at least one step.",
                "Recipe has no steps.",
            ),
            _matrix_check(
                "sample_parameters_cover_required_parameters",
                not missing,
                "Sample parameters render every required placeholder.",
                "Sample parameters left placeholders unresolved: " + ", ".join(missing),
            ),
            _matrix_check(
                "blocked_actions_documented",
                bool(recipe.blocked_actions),
                "Recipe documents blocked actions.",
                "Recipe does not document blocked actions.",
            ),
            _matrix_check(
                "approval_gates_documented_when_needed",
                bool(recipe.approval_gates) or not approval_steps,
                "Recipe documents approval gates for approval-required steps.",
                "Recipe has approval-required steps but no approval gate text.",
            ),
            _matrix_check(
                "no_policy_blocked_steps",
                not blocked_steps,
                "No recipe step is generically blocked by safety policy.",
                "Recipe contains policy-blocked steps: " + ", ".join(map(str, blocked_steps)),
            ),
            _matrix_check(
                "manual_placeholders_have_notes",
                all(str(planned_steps[index].get("note") or "").strip() for index in manual_placeholder_steps),
                "Manual placeholder steps are annotated so replay stops for review.",
                "Manual placeholder steps need notes: " + ", ".join(map(str, manual_placeholder_steps)),
            ),
        ]
        for index in approval_steps:
            step = planned_steps[index]
            policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
            checks.append(
                _matrix_check(
                    f"step_{index}_approval_token_present",
                    bool(policy.get("approval_token")) or step.get("human_only"),
                    "Approval-required step exposes an exact approval token or is human-only.",
                    "Approval-required step lacks an exact approval token.",
                )
            )
        cases.append(
            {
                "name": name,
                "success": all(check["passed"] for check in checks),
                "category": recipe.category,
                "parameters": parameters,
                "required_parameters": list(recipe.parameters),
                "step_count": len(planned_steps),
                "approval_step_indexes": approval_steps,
                "blocked_step_indexes": blocked_steps,
                "manual_placeholder_step_indexes": manual_placeholder_steps,
                "checks": checks,
                "steps": planned_steps,
            }
        )

    output = journal.run_dir / "ui_workflow_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "recipe_count": len(cases),
        "step_count": sum(case["step_count"] for case in cases),
        "approval_gated_step_count": sum(len(case["approval_step_indexes"]) for case in cases),
        "manual_placeholder_count": sum(len(case["manual_placeholder_step_indexes"]) for case in cases),
        "blocked_step_count": sum(len(case["blocked_step_indexes"]) for case in cases),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": "Static recipe matrix only. No UI action, bridge command, save, sync, reload, close, or model modification was executed.",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "ui-workflow-matrix",
            "requested_action": {
                "recipe_count": len(cases),
                "step_count": result["step_count"],
            },
            "risk_classification": classify_action("ui-workflow-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only UI workflow recipe validation."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "failed_cases": result["failed_cases"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def run_ui_workflow_smoke_matrix(
    journal: TaskJournal,
    *,
    observe_func=None,
    command_runner=None,
    max_steps_per_recipe: int | None = None,
    sample_parameters: dict | None = None,
) -> dict:
    """Run smoke-safe observation/planning prefixes of all UI workflow recipes."""

    samples = {
        "sheet_number": "S2.0",
        "view_name": "STARTING VIEW",
        "target_name": "Project Browser",
        "workflow_name": "Live Readonly QA Workflow",
    }
    samples.update({str(key): str(value) for key, value in (sample_parameters or {}).items()})

    if command_runner is None:
        return {"success": False, "error": "No command runner was supplied."}

    cases = []
    for recipe_index, recipe in enumerate(UI_WORKFLOWS.values()):
        parameters = {
            key: samples[key]
            for key in recipe.parameters
            if key in samples
        }
        plan = plan_ui_workflow(journal, name=recipe.name, parameters=parameters)
        steps = list(plan.get("steps") or [])
        if max_steps_per_recipe is not None:
            steps = steps[: max(0, max_steps_per_recipe)]

        ran_steps: list[int] = []
        step_results: list[dict] = []
        stop_reason = ""
        for step_index, step in enumerate(steps):
            command = str(step.get("command") or "")
            before = _observe(observe_func)
            record = {
                "index": step_index,
                "command": command,
                "args": step.get("args", []),
                "before": before,
                "status": "pending",
            }
            if _has_manual_placeholder(step.get("args", [])):
                record["status"] = "stopped_manual_placeholder"
                record["reason"] = "Step contains a manual placeholder that must be replaced before running."
                step_results.append(record)
                stop_reason = record["reason"]
                break

            state = str(before.get("state") or "").lower()
            if state == "modal" and command not in MODAL_SAFE_COMMANDS:
                record["status"] = "stopped_unexpected_modal"
                record["reason"] = "Fresh observation found modal Revit UI before a non-modal-safe smoke step."
                step_results.append(record)
                stop_reason = record["reason"]
                break

            policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
            if policy.get("decision") == BLOCK:
                record["status"] = "stopped_blocked"
                record["reason"] = policy.get("reason") or "Step is blocked by safety policy."
                step_results.append(record)
                stop_reason = record["reason"]
                break
            if step.get("requires_approval") or policy.get("decision") == APPROVAL_REQUIRED:
                record["status"] = "stopped_approval_required"
                record["reason"] = "Smoke matrix does not supply approval tokens."
                record["expected_approval_token"] = policy.get("approval_token")
                step_results.append(record)
                stop_reason = record["reason"]
                break
            if command not in WORKFLOW_SMOKE_SAFE_COMMANDS:
                record["status"] = "stopped_not_smoke_safe"
                record["reason"] = f"Command {command!r} is not in the smoke-safe command allowlist."
                step_results.append(record)
                stop_reason = record["reason"]
                break

            argv = [command, *[str(arg) for arg in (step.get("args") or [])]]
            command_result = command_runner(argv, recipe.name, step_index)
            record["command_argv"] = argv
            record["command_result"] = command_result
            record["after"] = _observe(observe_func)
            record["status"] = "ran"
            ran_steps.append(step_index)
            step_results.append(record)
            if isinstance(command_result, dict) and command_result.get("success") is False:
                if _smoke_false_result_is_expected(command, command_result):
                    record["status"] = "ran_diagnostic_false"
                    record["nonfatal_diagnostic"] = True
                    continue
                stop_reason = command_result.get("error") or f"Step {step_index} returned success=false."
                break

        cases.append(
            {
                "name": recipe.name,
                "success": not any(
                    isinstance(result.get("command_result"), dict)
                    and result["command_result"].get("success") is False
                    and not result.get("nonfatal_diagnostic")
                    for result in step_results
                ),
                "parameters": parameters,
                "step_count": len(steps),
                "ran_steps": ran_steps,
                "ran_count": len(ran_steps),
                "stop_reason": stop_reason,
                "step_results": step_results,
            }
        )

    output = journal.run_dir / "ui_workflow_smoke_matrix.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    result = {
        "success": all(case["success"] for case in cases),
        "read_only": True,
        "recipe_count": len(cases),
        "ran_step_count": sum(case["ran_count"] for case in cases),
        "failed_cases": [case["name"] for case in cases if not case["success"]],
        "cases": cases,
        "path": str(output),
        "note": (
            "Smoke matrix only. It runs observation/planning commands from a fixed allowlist "
            "and stops before approval-gated, manual-placeholder, blocked, or non-smoke-safe steps."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "ui-workflow-smoke-matrix",
            "requested_action": {
                "recipe_count": len(cases),
                "max_steps_per_recipe": max_steps_per_recipe,
            },
            "risk_classification": classify_action("ui-workflow-smoke-matrix", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Smoke runner uses only read-only observation/planning commands."},
            "result": {
                "status": "passed" if result["success"] else "failed",
                "ran_step_count": result["ran_step_count"],
                "failed_cases": result["failed_cases"],
            },
            "output_files": [str(output)],
        }
    )
    return result


def plan_ui_workflow(
    journal: TaskJournal,
    *,
    name: str,
    parameters: dict | None = None,
) -> dict:
    recipe = UI_WORKFLOWS.get(name.strip().lower())
    if not recipe:
        return {"success": False, "error": f"Unknown UI workflow: {name}"}

    parameters = {str(key): str(value) for key, value in (parameters or {}).items()}
    planned_steps = [step.render(parameters) for step in recipe.steps]
    missing = sorted(
        {
            missing
            for step in planned_steps
            for missing in step.get("missing_parameters", [])
        }
    )
    result = {
        "success": not missing,
        "read_only": True,
        "planned_only": True,
        "name": recipe.name,
        "summary": recipe.summary,
        "category": recipe.category,
        "parameters": parameters,
        "required_parameters": list(recipe.parameters),
        "missing_parameters": missing,
        "preconditions": list(recipe.preconditions),
        "blocked_actions": list(recipe.blocked_actions),
        "approval_gates": list(recipe.approval_gates),
        "steps": planned_steps,
        "step_count": len(planned_steps),
        "path": str(journal.run_dir / "ui_workflow_plan.json"),
        "note": "Planning only. No UI action, bridge command, save, sync, close, reload, or model modification was executed.",
        "captured_at": utc_now(),
    }
    output = journal.run_dir / "ui_workflow_plan.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "plan-ui-workflow",
            "requested_action": {"name": name, "parameters": parameters},
            "risk_classification": classify_action("plan-ui-workflow", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Planning only."},
            "result": {
                "success": result["success"],
                "missing_parameters": missing,
                "step_count": len(planned_steps),
            },
            "output_files": [str(output)],
        }
    )
    return result


def run_ui_workflow(
    journal: TaskJournal,
    *,
    name: str,
    parameters: dict | None = None,
    dry_run: bool = True,
    approval_tokens: dict[int, str] | None = None,
    max_steps: int | None = None,
    stop_on_error: bool = True,
    observe_func=None,
    command_runner=None,
) -> dict:
    """Run a recipe through fresh observation and step-level safety gates."""

    plan = plan_ui_workflow(journal, name=name, parameters=parameters)
    output = journal.run_dir / "ui_workflow_run.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    if not plan.get("success"):
        result = {
            **plan,
            "success": False,
            "dry_run": dry_run,
            "executed_steps": [],
            "skipped_steps": [],
            "stop_reason": "Workflow recipe parameters are incomplete.",
            "run_path": str(output),
        }
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    if command_runner is None:
        result = {
            **plan,
            "success": False,
            "dry_run": dry_run,
            "executed_steps": [],
            "skipped_steps": [],
            "stop_reason": "No command runner was supplied.",
            "run_path": str(output),
        }
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    approval_tokens = approval_tokens or {}
    steps = list(plan.get("steps") or [])
    if max_steps is not None:
        steps = steps[: max(0, max_steps)]

    executed_steps: list[int] = []
    skipped_steps: list[int] = []
    step_results: list[dict] = []
    stop_reason = ""

    for index, step in enumerate(steps):
        before = _observe(observe_func)
        gate = _step_gate(step, index, before, dry_run=dry_run, approval_tokens=approval_tokens)
        record = {
            "index": index,
            "command": step.get("command"),
            "args": step.get("args", []),
            "before": before,
            "gate": gate,
            "status": "pending",
        }
        if not gate["allowed"]:
            record["status"] = gate["status"]
            skipped_steps.append(index)
            step_results.append(record)
            stop_reason = gate["reason"]
            break

        argv = [str(step.get("command")), *[str(arg) for arg in step.get("args", [])]]
        token = gate.get("approval_token")
        if token and not dry_run:
            argv.extend(["--execute", "--approval-token", token])
        elif token:
            argv.extend(["--approval-token", token])

        command_result = command_runner(argv, index)
        record["command_argv"] = argv
        record["command_result"] = command_result
        record["after"] = _observe(observe_func)
        record["status"] = "ran"
        executed_steps.append(index)
        step_results.append(record)
        if stop_on_error and isinstance(command_result, dict) and command_result.get("success") is False:
            stop_reason = command_result.get("error") or f"Step {index} returned success=false."
            break

    success = not stop_reason and len(step_results) == len(steps)
    approved_executed_steps = [
        int(record["index"])
        for record in step_results
        if record.get("status") == "ran"
        and isinstance(record.get("gate"), dict)
        and record["gate"].get("status") == "approved_execute"
    ]
    result = {
        **plan,
        "success": success,
        "dry_run": dry_run,
        "executed_steps": executed_steps,
        "approved_executed_steps": approved_executed_steps,
        "skipped_steps": skipped_steps,
        "step_results": step_results,
        "stop_reason": stop_reason,
        "run_path": str(output),
        "note": (
            "Recipe runner executed only steps allowed by fresh observation, step policy, "
            "and supplied approval tokens. Approval-gated steps were not run without exact tokens."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    before_state = next(
        (
            record.get("before")
            for record in step_results
            if isinstance(record.get("before"), dict)
        ),
        None,
    )
    after_state = next(
        (
            record.get("after")
            for record in reversed(step_results)
            if isinstance(record.get("after"), dict)
        ),
        None,
    )
    journal.write_entry(
        {
            "command": "run-ui-workflow",
            "requested_action": {"name": name, "parameters": parameters or {}, "dry_run": dry_run},
            "observed_ui_state_before_action": before_state,
            "observed_ui_state_after_action": after_state,
            "risk_classification": classify_action("run-ui-workflow", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Runner enforces step-level gates."},
            "result": {
                "status": "executed" if executed_steps else "stopped",
                "success": result["success"],
                "executed_steps": executed_steps,
                "approved_executed_steps": approved_executed_steps,
                "skipped_steps": skipped_steps,
                "stop_reason": stop_reason,
            },
            "output_files": [str(output)],
        }
    )
    return result


def _render_template(value: str, parameters: dict) -> str:
    rendered = value
    for key, val in parameters.items():
        rendered = rendered.replace("{" + key + "}", str(val))
    return rendered


def _missing_placeholders(values: list[str], parameters: dict) -> set[str]:
    missing: set[str] = set()
    for value in values:
        for match in re.findall(r"\{([a-zA-Z0-9_]+)\}", value):
            if match not in parameters:
                missing.add(match)
    return missing


def _payload_from_args(args: list[str]) -> dict:
    payload: dict[str, object] = {}
    index = 0
    while index < len(args):
        current = args[index]
        if not current.startswith("--"):
            index += 1
            continue
        key = current[2:].replace("-", "_")
        next_index = index + 1
        if next_index < len(args) and not args[next_index].startswith("--"):
            payload[key] = args[next_index]
            index += 2
        else:
            payload[key] = True
            index += 1
    return payload


def _observe(observe_func) -> dict:
    if observe_func is None:
        return {"available": False}
    try:
        result = observe_func()
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"available": False, "value": str(result)}


def _step_gate(
    step: dict,
    index: int,
    before: dict,
    *,
    dry_run: bool,
    approval_tokens: dict[int, str],
) -> dict:
    command = str(step.get("command") or "")
    if _has_manual_placeholder(step.get("args", [])):
        return {
            "allowed": False,
            "status": "stopped_manual_placeholder",
            "reason": "Step contains a manual placeholder that must be replaced before running.",
        }
    state = str(before.get("state") or "").lower()
    if state == "modal" and command not in MODAL_SAFE_COMMANDS:
        return {
            "allowed": False,
            "status": "stopped_unexpected_modal",
            "reason": "Fresh observation found modal Revit UI before a non-modal-safe step.",
        }
    policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
    if policy.get("decision") == BLOCK:
        return {
            "allowed": False,
            "status": "stopped_blocked",
            "reason": policy.get("reason") or "Step is blocked by safety policy.",
        }
    if step.get("human_only"):
        return {
            "allowed": False,
            "status": "stopped_human_only",
            "reason": "Step is marked human-only.",
        }
    if step.get("requires_approval") or policy.get("decision") == APPROVAL_REQUIRED:
        expected = policy.get("approval_token")
        supplied = approval_tokens.get(index)
        if not expected or supplied != expected:
            return {
                "allowed": False,
                "status": "stopped_approval_required",
                "reason": "Missing or incorrect approval token for this recipe step.",
                "expected_approval_token": expected,
            }
        return {
            "allowed": True,
            "status": "approved_dry_run" if dry_run else "approved_execute",
            "reason": "Exact step approval token supplied.",
            "approval_token": supplied,
        }
    return {
        "allowed": True,
        "status": "allowed",
        "reason": "Low-risk planning/observation step.",
    }


def _has_manual_placeholder(args: object) -> bool:
    if not isinstance(args, list):
        return False
    return any(isinstance(arg, str) and "<" in arg and ">" in arg for arg in args)


def _smoke_false_result_is_expected(command: str, result: dict) -> bool:
    if command not in WORKFLOW_SMOKE_DIAGNOSTIC_FALSE_OK:
        return False
    status = str(result.get("status") or "").lower()
    if status in {"not_ready", "stale_or_unverified", "not_found", "missing", "no_dialog"}:
        return True
    if result.get("read_only") is True and (
        result.get("ready_for_continuous_bridge") is False
        or result.get("executable") is False
        or result.get("has_dialog") is False
    ):
        return True
    if result.get("match_count") == 0 or result.get("dialog_count") == 0:
        return True
    return False


def _matrix_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
