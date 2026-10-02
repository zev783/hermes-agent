"""Read-only bridge restart/reload validation planning."""

from __future__ import annotations

import json
from pathlib import Path

from .addin_security import addin_security_preflight
from .bridge import RevitBridgeClient
from .constants import DRAFT_LABEL
from .journal import TaskJournal
from .readiness import wait_model_ready
from .safety import classify_action, validate_output_path


def bridge_post_restart_validation(
    journal: TaskJournal,
    observer,
    bridge: RevitBridgeClient,
    *,
    repo_root: Path,
    command_names: list[str],
    revit_version: str = "2025",
    addins_root: Path | None = None,
    assembly_path: Path | None = None,
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    expected_view_name: str = "",
    expected_view_type: str = "",
    timeout: float = 120.0,
    poll: float = 2.0,
    security_preflight_fn=addin_security_preflight,
    wait_model_ready_fn=wait_model_ready,
    north_star_audit_fn=None,
) -> dict:
    """Run the read-only post-human-restart validation checklist."""

    from .north_star import run_north_star_audit

    output = journal.run_dir / "bridge_post_restart_validation.json"
    error = validate_output_path(output, journal.sandbox)
    if error:
        return {"success": False, "error": error}

    status = observer.status()
    bridge_status = bridge.bridge_status()
    loaded_build = bridge.verify_loaded_build()
    readiness = bridge.bridge_readiness(
        revit_version=revit_version,
        addins_root=addins_root,
        assembly_path=assembly_path,
    )
    security = security_preflight_fn(
        journal,
        revit_version=revit_version,
        addins_root=addins_root,
        assembly_path=assembly_path,
    )
    model_ready = wait_model_ready_fn(
        journal,
        observer,
        bridge,
        timeout=timeout,
        poll=poll,
        expected_title_contains=expected_title_contains,
        expected_path_contains=expected_path_contains,
        expected_revit_version=revit_version,
        expected_view_name=expected_view_name,
        expected_view_type=expected_view_type,
        require_bridge=True,
        stop_on_modal=True,
    )
    audit = (north_star_audit_fn or run_north_star_audit)(
        journal,
        repo_root=repo_root,
        command_names=command_names,
    )

    checks = [
        _validation_check(
            "status_observed",
            bool(status.get("supported", True)) and bool(status.get("revit_running")),
            "Revit status was observed and Revit is running.",
            "Revit was not observed running.",
        ),
        _validation_check(
            "no_active_dialogs",
            not bool(status.get("active_dialogs")),
            "No active dialogs were visible during validation.",
            "One or more active dialogs were visible during validation.",
        ),
        _validation_check(
            "bridge_status_connected",
            bool(bridge_status.get("available")),
            "Bridge status or heartbeat payload is available.",
            "Bridge status and heartbeat payloads are unavailable.",
        ),
        _validation_check(
            "loaded_build_current",
            bool(loaded_build.get("success")) and loaded_build.get("status") == "current",
            "Loaded add-in reports current bridge metadata.",
            "Loaded add-in is stale or lacks current bridge metadata.",
        ),
        _validation_check(
            "bridge_readiness_ready",
            bool(readiness.get("ready_for_continuous_bridge")),
            "Bridge readiness reports ready_for_continuous_bridge.",
            "Bridge readiness does not report ready_for_continuous_bridge.",
        ),
        _validation_check(
            "addin_security_verified",
            security.get("status") == "verified",
            "Add-in manifest, DLL path, and signature are verified.",
            "Add-in security preflight is not verified.",
        ),
        _validation_check(
            "model_ready",
            bool(model_ready.get("ready")),
            "Copied local Revit model is idle, non-modal, and matches expected predicates.",
            "Model readiness predicates did not pass.",
        ),
        _validation_check(
            "north_star_status_refreshed",
            audit.get("success") is True and bool(audit.get("path")),
            "North-star audit artifact was refreshed.",
            "North-star audit artifact was not refreshed.",
        ),
    ]
    validation_passed = all(check["passed"] for check in checks)
    failed_checks = [check["name"] for check in checks if not check["passed"]]
    verify_bridge_failed_checks = _failed_check_names(loaded_build.get("checks"))
    bridge_readiness_failed_checks = _failed_check_names(readiness.get("checks"))
    result = {
        "success": validation_passed,
        "read_only": True,
        "status": "passed" if validation_passed else "failed",
        "validation_passed": validation_passed,
        "revit_version": revit_version,
        "checks": checks,
        "failed_checks": failed_checks,
        "failed_check_count": len(failed_checks),
        "ready_for_continuous_bridge": readiness.get("ready_for_continuous_bridge"),
        "requires_revit_restart_or_reload": readiness.get(
            "requires_revit_restart_or_reload"
        ),
        "verify_bridge_build_status": loaded_build.get("status"),
        "verify_bridge_build_success": loaded_build.get("success") is True,
        "verify_bridge_build_failed_checks": verify_bridge_failed_checks,
        "verify_bridge_build_failed_check_count": len(verify_bridge_failed_checks),
        "bridge_readiness_status": readiness.get("status"),
        "bridge_readiness_failed_checks": bridge_readiness_failed_checks,
        "bridge_readiness_failed_check_count": len(bridge_readiness_failed_checks),
        "model_ready_ready": model_ready.get("ready"),
        "status_observation": {
            "state": status.get("state"),
            "revit_running": status.get("revit_running"),
            "active_dialog_count": len(status.get("active_dialogs") or []),
            "main_window": status.get("main_window"),
        },
        "bridge_status": bridge_status,
        "verify_bridge_build": loaded_build,
        "bridge_readiness": readiness,
        "addin_security_preflight": security,
        "model_ready": model_ready,
        "north_star_audit": {
            "status": audit.get("status"),
            "north_star_complete": audit.get("north_star_complete"),
            "implementation_package_complete": audit.get("implementation_package_complete"),
            "blocker_summary": audit.get("blocker_summary"),
            "remaining_gaps": audit.get("remaining_gaps"),
            "path": audit.get("path"),
        },
        "path": str(output),
        "safety_note": (
            "This validation is read-only. It does not close, restart, focus, click, type, "
            "invoke UIA, save, sync, reload, detach, upgrade, or modify Revit."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    output_files = [str(output)]
    for nested in (model_ready, audit):
        nested_path = nested.get("path") if isinstance(nested, dict) else None
        if nested_path:
            output_files.append(str(nested_path))
    journal.write_entry(
        {
            "command": "bridge-post-restart-validation",
            "requested_action": {
                "revit_version": revit_version,
                "expected_title_contains": expected_title_contains,
                "expected_path_contains": expected_path_contains,
                "expected_view_name": expected_view_name,
                "expected_view_type": expected_view_type,
            },
            "risk_classification": classify_action("bridge-post-restart-validation", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only post-restart validation."},
            "result": {
                "status": result["status"],
                "validation_passed": validation_passed,
                "failed_checks": failed_checks,
                "verify_bridge_build_failed_checks": verify_bridge_failed_checks,
                "bridge_readiness_failed_checks": bridge_readiness_failed_checks,
            },
            "output_files": output_files,
        }
    )
    return result


def bridge_restart_validation_plan(
    journal: TaskJournal,
    bridge: RevitBridgeClient,
    *,
    revit_version: str = "2025",
    addins_root: Path | None = None,
    assembly_path: Path | None = None,
    expected_title_contains: str = "",
    expected_path_contains: str = "",
    expected_view_name: str = "",
    expected_view_type: str = "",
    security_preflight_fn=addin_security_preflight,
) -> dict:
    """Write a safe human handoff plan for validating a bridge reload/restart."""

    readiness = bridge.bridge_readiness(
        revit_version=revit_version,
        addins_root=addins_root,
        assembly_path=assembly_path,
    )
    security = security_preflight_fn(
        journal,
        revit_version=revit_version,
        addins_root=addins_root,
        assembly_path=assembly_path,
    )
    active_document = bridge.active_document_status()
    pre_restart_ready = _pre_restart_files_ready(readiness)
    restart_required = bool(readiness.get("requires_revit_restart_or_reload"))
    post_commands = _post_restart_commands(
        revit_version=revit_version,
        expected_title_contains=expected_title_contains,
        expected_path_contains=expected_path_contains,
        expected_view_name=expected_view_name,
        expected_view_type=expected_view_type,
    )
    blocked = [
        "Hermes must not close or restart Revit automatically.",
        "Hermes must not save, Save As, synchronize, relinquish, reload links, detach, or upgrade as part of this handoff.",
        "Hermes must not write to LucidLink, Autodesk Docs, cloud, central, or production paths.",
        "If the model is dirty, the human decides whether and how to preserve work before restart.",
    ]
    human_steps = [
        "Review bridge-readiness and addin-security-preflight output.",
        "If source DLL, manifest, and signature are ready, ask the human to restart or reload Revit when safe.",
        "After the human brings Revit back with the copied local model, run the post_restart_validation_commands in order.",
        "Treat any modal prompt after restart as high risk; run plan-current-dialog-response before clicking.",
    ]
    if not restart_required and readiness.get("ready_for_continuous_bridge"):
        human_steps.insert(0, "No restart is currently required; the loaded bridge already reports current metadata.")
    elif not pre_restart_ready:
        human_steps.insert(0, "Do not ask for restart yet; build/install/sign readiness checks are still incomplete.")

    output = journal.run_dir / "bridge_restart_validation_plan.json"
    checklist_output = journal.run_dir / "bridge_restart_no_save_checklist.md"
    error = validate_output_path(output, journal.sandbox) or validate_output_path(
        checklist_output, journal.sandbox
    )
    if error:
        return {"success": False, "error": error}

    checklist = _restart_no_save_checklist(
        active_document=active_document,
        addin_security=security,
        post_commands=post_commands,
        readiness=readiness,
    )
    checklist_output.write_text(checklist, encoding="utf-8")

    result = {
        "success": True,
        "read_only": True,
        "status": _plan_status(readiness, pre_restart_ready, restart_required),
        "revit_version": revit_version,
        "pre_restart_files_ready": pre_restart_ready,
        "restart_or_reload_required": restart_required,
        "ready_for_continuous_bridge_now": bool(readiness.get("ready_for_continuous_bridge")),
        "bridge_readiness": readiness,
        "addin_security_preflight": security,
        "active_document": active_document,
        "human_handoff_required": restart_required or not readiness.get("ready_for_continuous_bridge"),
        "human_steps": human_steps,
        "blocked_automation": blocked,
        "post_restart_validation_commands": post_commands,
        "no_save_checklist_path": str(checklist_output),
        "success_criteria": [
            "verify-bridge-build returns status: current.",
            "bridge-readiness returns ready_for_continuous_bridge: true.",
            "bridge-status loaded addin metadata includes bridge_protocol_version 0.2 and source_capability_stamp continuous-idling-status-file-retry-v2.",
            "wait-model-ready returns ready: true for the copied local model and expected Revit version/view predicates.",
            "No save, sync, reload, close, detach, upgrade, or model-write operation was executed by Hermes.",
        ],
        "path": str(output),
        "note": (
            "This is a read-only restart/reload validation plan. It does not close, restart, "
            "save, sync, reload, or modify Revit."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    journal.write_entry(
        {
            "command": "bridge-restart-validation-plan",
            "requested_action": {
                "revit_version": revit_version,
                "addins_root": str(addins_root) if addins_root else None,
                "assembly_path": str(assembly_path) if assembly_path else None,
            },
            "risk_classification": classify_action("bridge-restart-validation-plan", {}).to_dict(),
            "approval_status": {"allowed": True, "reason": "Read-only bridge restart validation plan."},
            "result": {
                "status": result["status"],
                "restart_or_reload_required": restart_required,
                "pre_restart_files_ready": pre_restart_ready,
                "addin_security_status": security.get("status"),
                "no_save_checklist_path": str(checklist_output),
            },
            "output_files": [str(output), str(checklist_output)],
        }
    )
    return result


def _pre_restart_files_ready(readiness: dict) -> bool:
    checks = {check.get("name"): check.get("passed") for check in readiness.get("checks") or []}
    return all(
        checks.get(name) is True
        for name in (
            "source_project_present",
            "built_assembly_present",
            "manifest_present",
            "manifest_points_to_expected_assembly",
        )
    )


def _plan_status(readiness: dict, pre_restart_ready: bool, restart_required: bool) -> str:
    if readiness.get("ready_for_continuous_bridge"):
        return "bridge_current"
    if pre_restart_ready and restart_required:
        return "human_restart_required"
    if pre_restart_ready:
        return "post_restart_validation_needed"
    return "pre_restart_setup_incomplete"


def _post_restart_commands(
    *,
    revit_version: str,
    expected_title_contains: str,
    expected_path_contains: str,
    expected_view_name: str,
    expected_view_type: str,
) -> list[str]:
    commands = [
        "revit-operator status",
        "revit-operator bridge-status",
        "revit-operator verify-bridge-build",
        f"revit-operator bridge-readiness --revit-version {revit_version}",
        "revit-operator addin-security-preflight --revit-version " + revit_version,
    ]
    wait_parts = [
        "revit-operator wait-model-ready",
        "--timeout 120",
        "--poll 2",
        f"--expected-revit-version {revit_version}",
    ]
    if expected_title_contains:
        wait_parts.extend(["--expected-title-contains", _quote_arg(expected_title_contains)])
    if expected_path_contains:
        wait_parts.extend(["--expected-path-contains", _quote_arg(expected_path_contains)])
    if expected_view_name:
        wait_parts.extend(["--expected-view-name", _quote_arg(expected_view_name)])
    if expected_view_type:
        wait_parts.extend(["--expected-view-type", _quote_arg(expected_view_type)])
    commands.append(" ".join(wait_parts))
    return commands


def _quote_arg(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _restart_no_save_checklist(
    *,
    active_document: dict,
    addin_security: dict | None = None,
    post_commands: list[str],
    readiness: dict | None = None,
) -> str:
    document_payload = _active_document_payload(active_document)
    readiness_payload = readiness if isinstance(readiness, dict) else {}
    loaded_build = readiness_payload.get("loaded_build")
    loaded_build_payload = loaded_build if isinstance(loaded_build, dict) else {}
    expected_metadata = loaded_build_payload.get("expected")
    expected_metadata_payload = expected_metadata if isinstance(expected_metadata, dict) else {}
    observed_addin = loaded_build_payload.get("loaded_addin")
    observed_addin_payload = observed_addin if isinstance(observed_addin, dict) else {}
    failed_readiness_checks = _list_text(readiness_payload.get("failed_checks"))
    failed_loaded_checks = _failed_check_names(loaded_build_payload.get("checks"))
    technical_cause = _bridge_restart_technical_cause(
        readiness_payload=readiness_payload,
        failed_readiness_checks=failed_readiness_checks,
    )
    dirty = document_payload.get("dirty")
    title = document_payload.get("title") or "(unknown)"
    path = document_payload.get("path") or "(unknown)"
    revit_version = document_payload.get("revit_version") or "(unknown)"
    view = document_payload.get("active_view") if isinstance(document_payload, dict) else None
    view_payload = view if isinstance(view, dict) else {}
    active_view = view_payload.get("name") or "(unknown)"
    active_view_type = view_payload.get("type") or "(unknown)"
    if dirty is True:
        dirty_note = "The active copied model reports dirty: true. Save/discard decisions are human-only."
    elif dirty is False:
        dirty_note = "The active copied model reports dirty: false."
    else:
        dirty_note = "Dirty state is unknown. Treat save/discard decisions as human-only."

    lines = [
        "# Bridge Restart / Reload No-Save Checklist",
        "",
        DRAFT_LABEL,
        "",
        "Purpose: clear the bridge restart validation gate without letting Hermes save, sync, reload links, detach, upgrade, close, or modify Revit.",
        "",
        "## Observed Active Document",
        "",
        f"- title: `{title}`",
        f"- path: `{path}`",
        f"- revit_version: `{revit_version}`",
        f"- active_view: `{active_view}`",
        f"- active_view_type: `{active_view_type}`",
        f"- dirty: `{dirty}`",
        f"- dirty_note: {dirty_note}",
        "",
        "## Bridge Reload Cause",
        "",
        f"- technical_cause: {technical_cause}",
        f"- readiness_status: `{readiness_payload.get('status') or '(unknown)'}`",
        f"- restart_or_reload_required: `{readiness_payload.get('requires_revit_restart_or_reload')}`",
        f"- failed_readiness_checks: {_inline_code_list(failed_readiness_checks)}",
        f"- failed_loaded_build_checks: {_inline_code_list(failed_loaded_checks)}",
        "- expected_loaded_metadata: "
        + _metadata_summary(
            expected_metadata_payload,
            keys=(
                "bridge_protocol_version",
                "source_capability_stamp",
                "supports_continuous_idling",
                "uses_idling_set_raise_without_delay",
            ),
        ),
        "- observed_loaded_metadata: "
        + _metadata_summary(
            observed_addin_payload,
            keys=(
                "bridge_protocol_version",
                "source_capability_stamp",
                "supports_continuous_idling",
                "uses_idling_set_raise_without_delay",
            ),
        ),
        "",
        *_addin_security_checklist_lines(addin_security),
        "",
        "## Human-Only Restart / Reload",
        "",
        "1. Confirm the open model is the copied local/detached test model, not a central, cloud, LucidLink, or production model.",
        "2. Do not run Save, Save As, Synchronize with Central, Publish, Relinquish, Reload Links, Detach, Upgrade, or any model-changing command.",
        "3. If Revit asks whether to save changes, Hermes must not answer. The human decides manually; do not save or sync from Hermes.",
        "4. Restart or reload Revit only when the human accepts the copied-model consequences.",
        "5. Reopen only the safe copied local test model with the matching Revit version from the working-copy area.",
        "6. Treat any add-in, worksharing, link, warning, or save-changes prompt as high risk until re-observed and classified.",
        "",
        "## Post-Human Checks",
        "",
    ]
    lines.extend(f"- `{command}`" for command in post_commands)
    lines.extend(
        [
            "",
            "Do not mark the north-star goal complete unless a fresh `north-star-completion-gate` or `north-star-resume-check.completion_gate` reports `completion_allowed: true`, `may_call_update_goal: true`, and `audit_completion_authorized: true`. Status and audit summaries are diagnostic only.",
            "",
        ]
    )
    return "\n".join(lines)


def _addin_security_checklist_lines(addin_security: dict | None) -> list[str]:
    payload = addin_security if isinstance(addin_security, dict) else {}
    signature = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    blocked_buttons = _list_text(payload.get("blocked_dialog_buttons"))
    return [
        "## Add-In Startup Prompt Preflight",
        "",
        f"- addin_security_status: `{payload.get('status') or '(unknown)'}`",
        f"- expected_local_hermes_addin: `{payload.get('expected_local_hermes_addin')}`",
        f"- needs_trust_addin: `{payload.get('needs_trust_addin')}`",
        "- can_consider_always_load_after_human_approval: "
        f"`{payload.get('can_consider_always_load_after_human_approval')}`",
        "- allowed_dialog_button_after_human_approval: "
        f"`{payload.get('allowed_dialog_button') or '(none)'}`",
        f"- blocked_dialog_buttons: {_inline_code_list(blocked_buttons)}",
        f"- manifest: `{paths.get('manifest') or manifest.get('path') or '(unknown)'}`",
        f"- expected_assembly: `{paths.get('expected_assembly') or '(unknown)'}`",
        f"- signature_status: `{signature.get('status') or '(unknown)'}`",
        f"- signer_subject: `{signature.get('signer_subject') or '(unknown)'}`",
        f"- recommendation: {payload.get('recommended_action') or '(unknown)'}",
        "- prompt_rule: If an unsigned add-in prompt appears, Hermes must not click "
        "it from this checklist. Run `plan-current-dialog-response` and require "
        "an exact approval token before any `Always Load` click.",
    ]


def _bridge_restart_technical_cause(
    *,
    readiness_payload: dict,
    failed_readiness_checks: list[str],
) -> str:
    if "loaded_build_current" in failed_readiness_checks:
        return "Loaded Revit add-in is stale or lacks current bridge build metadata."
    if readiness_payload.get("requires_revit_restart_or_reload"):
        return "Bridge readiness requires a human-controlled Revit restart or reload."
    if failed_readiness_checks:
        return "Bridge pre-restart file or manifest readiness checks are incomplete."
    if readiness_payload.get("ready_for_continuous_bridge"):
        return "Loaded Revit add-in already reports current continuous bridge metadata."
    return "Bridge restart validation state is unknown; keep the handoff human-only."


def _failed_check_names(checks: object) -> list[str]:
    if not isinstance(checks, list):
        return []
    names: list[str] = []
    for check in checks:
        if isinstance(check, dict) and not check.get("passed"):
            name = check.get("name")
            if name:
                names.append(str(name))
    return names


def _list_text(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _inline_code_list(values: list[str]) -> str:
    if not values:
        return "`(none)`"
    return ", ".join(f"`{value}`" for value in values)


def _metadata_summary(payload: dict, *, keys: tuple[str, ...]) -> str:
    parts = []
    for key in keys:
        value = payload.get(key, "(missing)")
        parts.append(f"{key}=`{value}`")
    return "; ".join(parts)


def _active_document_payload(active_document: dict) -> dict:
    if not isinstance(active_document, dict):
        return {}
    document = active_document.get("document")
    if not isinstance(document, dict):
        return {}
    nested = document.get("document")
    if isinstance(nested, dict):
        return nested
    return document


def _validation_check(name: str, passed: bool, pass_reason: str, fail_reason: str) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": pass_reason if passed else fail_reason,
    }
