# Revit Operator North-Star Audit

Current status: not complete.

This audit maps the original north-star prompt to concrete artifacts and gaps. It prevents treating the current prototype as finished merely because tests pass or a live read-only workflow succeeded.

## Objective Restatement

Build a Revit-operating agent substrate for Hermes: a local system that lets an AI agent observe and operate Autodesk Revit like a careful human operator, combining UI operation, Revit API automation, dialog understanding, safety enforcement, long-running supervision, logs, sandboxed outputs, and recovery.

## Prompt-To-Artifact Checklist

| Requirement | Evidence | Status |
| --- | --- | --- |
| Human-style UI operation | `focus`, `press-key`, `click`, `type-text`, `uia-invoke`; all dry-run and safety-gated; `uia-control-details` reports supported UIA action methods | Partial |
| Revit API/SDK calls where available | Revit add-in source under `tools/revit_operator/addin`; bridge status/heartbeat files; bridge command queue/results; live `active-document` and `export-metadata` verified; `activate-view` source is guarded through the bridge; bridge restart/reload validation handoff exists | Partial |
| Screen/window/dialog observation | `status`, `list-windows`, `list-dialogs`, `screenshot`, `ui-tree`, `uia-tree`, `find-control`, `uia-find-control`, `uia-control-details` | Implemented foundation |
| Keyboard/mouse/ribbon/menu control | `press-key`, `click`, `uia-invoke`, named `ribbon-action` descriptors for common tabs plus blocked File/Save/Sync surfaces, `uia-method-matrix`, `ui-execution-coverage-audit`, `ribbon-action-matrix`, `context-menu-action-matrix`, `context-menu-snapshot`, guarded `context-menu-action` opening through `right_click_input`, and `context-menu-select-item`; UIA can locate ribbon controls and execute explicit approved UIA methods | Partial; ribbon/context descriptor libraries exist, no full workflow library |
| Prompt detection and escalation | `classify-dialog`, known dialog rules, sandboxed learned dialog rules, dialog response playbooks with safe preflight commands and blocked-button guidance, approval-required policies | Partial; playbooks exist but need more live prompt coverage |
| Model/document state extraction | add-in bridge exports active document and metadata snapshot; `find-view` searches exported views/sheets for supervised navigation | Partial; read-only plus active-view session navigation |
| Safety policy enforcement | `safety.py`, blocked Save/Sync terms, exact approval tokens, sandbox validation, `action-approval-matrix` rehearsal, `uia-method-matrix` coverage for every allowlisted UIA method, and `ui-execution-coverage-audit` coverage reporting for authorized live UI execution | Implemented foundation |
| Long-running task supervision | `supervise-session`, `--resume`, bridge result waits, recovery snapshot, repeated busy/unknown stall detection, `supervision-endurance-matrix`, `supervision-endurance-audit` | Implemented foundation; live 2-hour/24-check endurance gate is cleared, but arbitrary hours-long recovery across future Revit tasks still needs broader validation |
| Structured logs and reversible workflows | JSONL journals, Markdown summaries, workflow templates, dry-run replay planning, workflow approval plans, parameterized replay planning with override reclassification, guarded replay runner, recorded state predicates, recovery snapshots on replay stop | Partial; guarded replay exists but needs broad live validation |
| Agent-facing control interface | CLI command surface, local HTTP `/health` and `/command`, Hermes plugin `revit_operator` tool wrapper, and thin MCP stdio wrapper | Implemented foundation; real stdio MCP client smoke passed for a read-only command |

## Named Deliverables

| Deliverable | Evidence | Status |
| --- | --- | --- |
| `REVIT_HUMAN_OPERATOR_LAYER.md` | Present | Done |
| `REVIT_OPERATOR_SAFETY_MODEL.md` | Present | Done |
| `REVIT_UI_AUTOMATION_PROTOTYPE.md` | Present | Done |
| `REVIT_OPERATOR_RUNBOOK.md` | Present | Done |
| `REVIT_OPERATOR_VALIDATION.md` | Present with live evidence | Done |
| Prototype source code | `tools/revit_operator/` package plus tests | Done as prototype |
| Hermes plugin wrapper | `plugins/revit-operator/` plus plugin tests | Done as prototype |
| MCP wrapper | `tools/revit_operator/mcp_server.py` plus tests | Done as thin transport prototype |

## Prototype Commands

Implemented command surface:

- `serve`
- `health`
- `north-star-status`
- `north-star-audit`
- `north-star-approval-plan`
- `north-star-approval-preflight`
- `north-star-ready-approvals`
- `north-star-next-approval`
- `north-star-waiting-state`
- `north-star-approval-verify`
- `north-star-watch`
- `north-star-resume-check`
- `north-star-human-gate-packet`
- `north-star-completion-gate`
- `north-star-blocked-ledger`
- `north-star-current-handoff`
- `north-star-stable-artifact-scan`
- `north-star-unblock-readiness`
- `status`
- `list-processes`
- `list-revit-installs`
- `list-windows`
- `list-dialogs`
- `known-dialogs`
- `dialog-rule-library`
- `record-dialog-rule`
- `dialog-workflows`
- `dialog-workflow-matrix`
- `plan-dialog-response`
- `plan-current-dialog-response`
- `classify-dialog`
- `screenshot`
- `ocr-screenshot`
- `ocr-health`
- `ui-tree`
- `uia-tree`
- `uia-find-control`
- `uia-control-details`
- `uia-method-matrix`
- `uia-invoke`
- `ribbon-actions`
- `ribbon-action-matrix`
- `plan-ribbon-action`
- `ribbon-action`
- `context-menu-actions`
- `context-menu-action-matrix`
- `context-menu-snapshot`
- `plan-context-menu-action`
- `context-menu-action`
- `plan-context-menu-item`
- `context-menu-select-item`
- `action-approval-matrix`
- `ui-execution-coverage-audit`
- `find-control`
- `project-browser-snapshot`
- `project-browser-plan-navigation`
- `project-browser-plan-visual-activation`
- `project-browser-visual-activate`
- `project-browser-plan-activation`
- `project-browser-activate-item`
- `properties-palette-snapshot`
- `wait-until-idle`
- `wait-model-ready`
- `wait-for-window`
- `wait-for-dialog`
- `export-metadata`
- `find-view`
- `bridge-status`
- `bridge-readiness`
- `bridge-restart-validation-plan`
- `bridge-post-restart-validation`
- `verify-bridge-build`
- `bridge-results`
- `wait-bridge-result`
- `recovery-snapshot`
- `recovery-drill-matrix`
- `supervise-session`
- `supervision-endurance-matrix`
- `supervision-endurance-audit`
- `workflow-library`
- `ui-workflows`
- `ui-workflow-matrix`
- `ui-workflow-smoke-matrix`
- `plan-ui-workflow`
- `run-ui-workflow`
- `record-workflow`
- `plan-workflow`
- `workflow-approval-plan`
- `replay-workflow`
- `open-model`
- `request-operation`
- `install-addin`
- `addin-security-preflight`
- `trust-addin`
- `qa-report`
- `qa-workflow`
- `focus`
- `press-key`
- `click`
- `type-text`
- `task-log`

Additional protocol wrapper:

- `revit-operator-mcp`

## Live Evidence

Live sandbox:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT\live_readonly_bridge_20260512
```

Verified live:

- Revit 2025 process/window observation.
- Startup dialog handling with approval-gated UI primitives.
- Bridge `active-document` and `export-metadata`.
- Metadata snapshot with levels, views, sheets, titleblocks, links, warnings, families, and types.
- Draft QA report.
- `qa-workflow` read-only workflow.
- `bridge-results` and `wait-bridge-result`.
- Known dialog listing.
- Expanded known-dialog/playbook listing now covers 21 built-in Revit prompt surfaces, including Manage Links, type catalog, Visibility/Graphics, View Template, missing links, open worksets, worksharing/central, warning review, failure processing, save-changes, and export-output-path prompts.
- Sandboxed learned dialog-rule recording/listing and classification.
- Conservative known-dialog response playbooks and response planning.
- Live `dialog-workflow-matrix` task `live-dialog-workflow-matrix` validated 21 representative prompt workflow cases with `failed_cases: []`, proving the playbooks classify expected prompt ids, include safe preflight commands, do not plan blocked-button clicks, and keep allowed-button plans approval-gated.
- Live `plan-current-dialog-response` wrote a current-dialog plan artifact and correctly produced no click when no dialog was visible.
- Live `plan-current-dialog-response --use-ocr --ocr-backend rapidocr` captured OCR evidence while Revit was idle and correctly left `plan: null` instead of treating whole-window OCR text as a prompt.
- Live `plan-dialog-response` for a save-changes prompt returned `risk: critical`, no planned action, and blocked Save/Don't Save choices.
- Workflow recording, dry-run replay planning, and guarded replay runner with fresh observation and recorded state predicates where journal context exists.
- Parameterized workflow template planning: a recorded `click --target Cancel` dry-run exposed `step_0_target`; overriding it to `OK` was reclassified as approval-required, and overriding it to `Save` was reclassified as blocked with no execution.
- Workflow approval planning: live `workflow-approval-plan` task `live-workflow-approval-plan` on `Parameterized Click Dry Run` confirmed the template contains no stored approval token, generated a fresh exact token for the current replay payload, and wrote a guarded replay execution command for human review; live `live-workflow-approval-plan-blocked` with `step_0_target=Save` returned `blocked_count: 1`, no approval tokens, and no execute command.
- North-star approval handoff: `north-star-approval-plan --sheet-number S2.0` writes a read-only approval packet for the remaining guarded validation steps, including context-menu open and exact context-menu item precondition steps needed by the UI execution coverage gate. It is not a substitute for approval or execution evidence and does not focus, click, type, invoke UIA, open context menus, queue bridge work, restart, save, sync, reload, close, detach, upgrade, or modify the model.
- Live `north-star-audit` now writes both `north_star_audit.json` and `north_star_audit.md`; latest stable `NORTH_STAR_AUDIT_CURRENT.md` exposes the prompt-to-artifact checklist in human-readable form. The audit reports `status: not_complete`, `north_star_complete: false`, `implementation_package_complete: true`, `objective_restatement`, no missing required commands, deliverables, prototype paths, live evidence tasks, or live evidence journals, and 10 unsatisfied checklist entries. The only unsatisfied items are the four live gates and the prompt requirements that depend on them. `supervision_endurance` is cleared. The bridge restart gap carries `restart_plan_artifact`, `no_save_checklist_path`, and `no_save_checklist_present: true` so the dirty copied-model restart/reload handoff is visible in the formal audit.
- Live `north-star-watch --sheet-number S2.0 --checks 2 --poll 0` task `live-north-star-watch-resume-check` wrote `north_star_watch.json`, observed the real Revit window twice, and stopped with `status: no_change`. It confirmed Revit was idle with no dialogs, `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, and failed bridge check `loaded_build_current`, without focusing, clicking, typing, invoking UIA, restarting, closing, saving, syncing, reloading, detaching, upgrading, or modifying the model.
- Live `north-star-watch --sheet-number S2.0 --checks 6 --poll 20` task `live-north-star-watch-after-approval-request-20260513` observed six idle Revit states after the next approval request, found no modal, hung, busy, or unknown condition, and still reported `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, and failed bridge check `loaded_build_current`.
- Live `north-star-resume-check --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-resume-check-stable-gate-20260513` refreshed north-star status, approval plan, post-restart bridge validation, audit artifacts, a hard completion-gate artifact, and stable `NORTH_STAR_AUDIT_CURRENT.*` / `NORTH_STAR_COMPLETION_GATE_CURRENT.*` files in one read-only run. It returned `status: blocked_human_or_real_condition`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and bridge validation failed checks `loaded_build_current` and `bridge_readiness_ready`, without focusing, clicking, typing, invoking UIA, queueing bridge writes, closing, restarting, saving, syncing, reloading, detaching, upgrading, or modifying the model.
- Live `north-star-human-gate-packet --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-human-gate-packet-current` wrote JSON and Markdown handoff artifacts with current manual gates, exact approval-token commands, blocked effects, and the post-human-action resume command. It did not approve or execute any UI/model action.
- Live `north-star-approval-verify --sheet-number S2.0 --approval-token <safe-ribbon-token>` task `live-north-star-approval-verify-safe-ribbon-20260513` matched the current `safe-ribbon-view-tab` approval item and wrote `north_star_approval_verify.json` with `execution_by_this_command: false` and `may_execute_from_this_result: false`; it explained the token without selecting the ribbon tab.
- Live `north-star-approval-preflight --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-approval-preflight-context-guard-20260513` ran the current approval plan's dry-run commands with execution and approval-token flags stripped, wrote stable `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` and `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md`, recorded the expected Revit/title/view context, reported `preflight_passed_count: 5`, `preflight_failed_count: 0`, and `unsafe_preflight_count: 0`, and did not approve or execute any gated action.
- Live `north-star-approval-preflight` task `live-north-star-context-guard-preflight-20260513` refreshed the stable approval preflight with the current expected context, again reporting `preflight_passed_count: 5`, `preflight_failed_count: 0`, `unsafe_preflight_count: 0`, and `ready_for_human_approval_count: 3` without approval or execution.
- Live `north-star-approval-preflight` task `live-north-star-freshness-preflight-20260513` refreshed the stable approval preflight with `approval_preflight_freshness`, `ttl_seconds: 900`, `preflight_passed_count: 5`, `unsafe_preflight_count: 0`, and `ready_for_human_approval_count: 3` without approval or execution.
- Live `north-star-ready-approvals --sheet-number S2.0` task `live-north-star-ready-approvals-token-summary-20260513` wrote `north_star_ready_approvals.json` and `.md`, reported `ready_approval_count: 3` and `withheld_approval_count: 2`, exposed execute-after-approval lines only for `safe-ribbon-view-tab`, `direct-uia-view-tab-select`, and `approved-workflow-open-sheet`, included token verification summaries with `may_execute_from_this_summary: false`, and withheld context-menu execute commands until preflight marks those items ready.
- Live `north-star-ready-approvals` task `live-north-star-ready-approvals-freshness-guard-20260513` carried `preflight_freshness_guard.status: fresh`, reported `ready_approval_count: 3`, `withheld_approval_count: 2`, and `may_execute_from_this_result: false`; stale preflight now withholds all ready execute lines in tests.
- Live `north-star-next-approval` task `live-north-star-next-approval-freshness-guard-20260513` carried `preflight_freshness_guard.status: fresh`, selected `safe-ribbon-view-tab`, and kept `may_execute_from_this_result: false`.
- Live `north-star-next-approval --sheet-number S2.0` task `live-north-star-next-approval-current-20260513` wrote `north_star_next_approval.json` and `.md`, reported `status: approval_ready`, selected `safe-ribbon-view-tab`, deferred the other two ready items with execute commands withheld, and kept both `may_execute_from_this_result` and selected item `may_execute_from_this_item` false.
- Live `north-star-waiting-state --sheet-number S2.0` task `live-north-star-waiting-state-current-hint-20260513` wrote stable `NORTH_STAR_WAITING_STATE_CURRENT.json` and `.md`, reported `status: waiting_for_human_or_real_condition`, `autonomous_progress_available: false`, `blocked_waiting_for_human_or_real_condition: true`, exact `required_human_approval_phrase`, and false execution flags.
- Live `north-star-approval-phrase-verify --phrase "READ ONLY PHRASE VERIFICATION PROBE - NOT HUMAN APPROVAL"` task `live-north-star-approval-phrase-verify-no-approval-20260513` refreshed the waiting-state handoff, reported `status: no_match`, `phrase_matches_waiting_state: false`, `approval_validated_for_current_waiting_state: false`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`. It deliberately did not supply the required human phrase and did not approve or execute any UI action.
- Live `north-star-approved-execution-preview --phrase "READ ONLY EXECUTION PREVIEW PROBE - NOT HUMAN APPROVAL"` task `live-north-star-approved-execution-preview-no-approval-20260513` refreshed phrase verification and next-approval handoffs, reported `status: approval_not_validated`, `selected_item_id: safe-ribbon-view-tab`, `selection_matches_verified_phrase: false`, empty `execute_command_preview`, empty `execute_powershell_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`. It proves the preview command withholds execution text when the exact current human approval phrase is not supplied.
- Live `north-star-approved-execution-preview` task `live-north-star-context-guard-preview-probe-20260513` deliberately used a non-approval phrase and mismatched title context. It reported `status: approval_not_validated`, `context_guard.status: context_mismatch`, a mismatch on `expected_title_contains` against the latest stable preflight context, empty `execute_command_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`.
- Live `north-star-approved-execution-preview` task `live-north-star-freshness-preview-probe-20260513` used a non-approval phrase against fresh matching preflight context. It reported `status: approval_not_validated`, `preflight_freshness_guard.status: fresh`, `context_guard.status: context_matched`, empty `execute_command_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`.
- Live `north-star-blocked-ledger` task `live-north-star-current-handoff-with-dry-run-commands-20260513` wrote stable `NORTH_STAR_BLOCKED_LEDGER_CURRENT.json` and `NORTH_STAR_BLOCKED_LEDGER_CURRENT.md` with four entries, one for each blocked gate, including approval items, manual completion steps, approval-token verify commands, PowerShell-safe dry-run/preflight commands, PowerShell-safe human-reviewed execute commands, resume commands, and recheck commands. It did not execute any gated action.
- Live `north-star-current-handoff` tasks including `live-north-star-waiting-state-current-hint-20260513` and the phrase-verifier refresh published stable sandbox-root current handoff files: `NORTH_STAR_APPROVAL_PLAN_CURRENT.json`, `NORTH_STAR_APPROVAL_PLAN_CURRENT.md`, `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`, `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md`, `NORTH_STAR_READY_APPROVALS_CURRENT.json`, `NORTH_STAR_READY_APPROVALS_CURRENT.md`, `NORTH_STAR_NEXT_APPROVAL_CURRENT.json`, `NORTH_STAR_NEXT_APPROVAL_CURRENT.md`, `NORTH_STAR_WAITING_STATE_CURRENT.json`, `NORTH_STAR_WAITING_STATE_CURRENT.md`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.json`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.md`, `NORTH_STAR_AUDIT_CURRENT.json`, `NORTH_STAR_AUDIT_CURRENT.md`, `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md`, `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`, `NORTH_STAR_COMPLETION_GATE_CURRENT.json`, `NORTH_STAR_COMPLETION_GATE_CURRENT.md`, and `NORTH_STAR_HANDOFF_CURRENT.json` / `NORTH_STAR_HANDOFF_CURRENT.md`. The current handoff reported `status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, `ready_approval_count: 3`, `next_approval_item_id: safe-ribbon-view-tab`, `autonomous_progress_available: false`, `human_or_real_condition_required: true`, `blocked_waiting_for_human_or_real_condition: true`, `waiting_state.status: waiting_for_human_or_real_condition`, `waiting_state.required_human_approval_phrase: <redacted approval phrase>`, and four blocked gates.
- Live `north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-current-handoff-with-gate-waiting-summary-20260513` refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*` with current waiting-state and next-approval summaries, including the exact required human phrase and selected next approval candidate, while keeping `completion_allowed: false`, `may_call_update_goal: false`, and all execution-authority fields false.
- Live `north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-current-handoff-with-supervised-command-packet-20260513` refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*` with a supervised read-only command packet for the next approval gate. The packet includes exact preflight, phrase-verification, approved-execution-preview, resume-check, and completion-gate commands while reporting `execution_command_included: false` and `may_execute_from_this_packet: false`.
- Live `north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-current-handoff-with-final-supervised-readonly-script-20260513` wrote stable `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` and refreshed the stable completion gate after the script existed. The completion gate reports the supervised-readonly script hint as present, the script parses with zero PowerShell errors, and inspection found no literal `--execute` flag in the script.
- Live `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` validation parsed the stable script with PowerShell (`parse_error_count: 0`) and executing it ran the repo-local read-only `north-star-resume-check` task `post-human-resume-check-current`; the script parses the returned JSON completion gate, warns `NORTH STAR STILL BLOCKED: do not call update_goal`, and now prints the blocked-gate ids when completion remains blocked. The current gate returned `status: blocked_human_or_real_condition`, `north_star_complete: false`, `may_call_update_goal: false`, blocked gates `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`, and bridge failed checks `loaded_build_current` and `bridge_readiness_ready`.
- Live `north-star-completion-gate` artifact from task `live-north-star-completion-gate-after-preview-followup-20260513` ran a fresh read-only audit and wrote `north_star_completion_gate.json` / `north_star_completion_gate.md` with `status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, `unsatisfied_count: 10`, zero missing required commands/files/live-task journals, blocked gates `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`, `blocked_gate_details` containing the concrete next step for each unresolved gate, `followup_actions` that list the next read-only commands and warn not to reuse stale approval tokens, and `stable_artifact_hints` that point the supervisor to the current human packet, audit, approval, next approval, waiting state, restart, resume, and handoff files at the sandbox root, with the ready-approvals, next-approval, and waiting-state hints present. Approval-gated followups now include `north-star-approval-phrase-verify` and `north-star-approved-execution-preview` before any separate execution command. This is a hard guard against marking the active goal complete while the fresh audit still has unsatisfied checklist entries.
- Live `north-star-completion-gate` task `live-north-star-completion-gate-after-freshness-guard-20260513` remained blocked after the freshness guard refresh, reporting `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and the same four human/real-condition blocked gates.
- Live `north-star-completion-gate` task `live-north-star-completion-gate-after-ready-freshness-guard-20260513` remained blocked after ready/next approval freshness enforcement, reporting `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and the same four human/real-condition blocked gates.
- Live `north-star-approval-preflight` task `live-north-star-waiting-freshness-preflight-20260513` refreshed the stable approval preflight with a 900-second freshness window, reporting `preflight_passed_count: 5`, `unsafe_preflight_count: 0`, and `ready_for_human_approval_count: 3` without approval or execution.
- Live `north-star-current-handoff` task `live-north-star-current-handoff-with-waiting-freshness-guard-20260513` refreshed stable `NORTH_STAR_WAITING_STATE_CURRENT.*` with `preflight_freshness_guard.status: fresh`, `may_execute_from_waiting_state: false`, `may_execute_from_this_result: false`, `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.
- Live `north-star-completion-gate` task `live-north-star-completion-gate-after-waiting-freshness-guard-20260513` remained blocked after the waiting-state freshness guard refresh, reporting `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and the same blocked gates: `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`.
- Guarded UI workflow recipe planning/running: `ui-workflows` lists 10 reusable recipes; live `ui-workflow-matrix` validated 10 recipes and 38 steps with `failed_cases: []`, 7 approval-gated steps, 1 annotated manual placeholder, and 0 blocked steps; live `ui-workflow-smoke-matrix` task `live-ui-workflow-smoke-matrix-2` ran 23 smoke-safe observation/planning steps across all 10 recipes with `failed_cases: []`; live `plan-ui-workflow` runs rendered unsigned add-in startup preflight, Project Browser sheet navigation, and Manage Links inspection plans; the Project Browser recipe now includes `wait-model-ready` before OCR-backed navigation; live `run-ui-workflow` runs low-risk observation/planning/readiness steps with fresh status observations and stops before approval-required `activate-view` or Manage Links opening when no exact step token is supplied.
- Live replay stop captured a recovery snapshot after stopping before an approval-required focus action.
- Recovery snapshot with embedded dialog recovery plans.
- Win32 `find-control` locating Project Browser.
- `project-browser-snapshot`.
- Live `project-browser-snapshot --include-ocr --ocr-backend rapidocr` captured OCR evidence from the Project Browser control with 17 detected lines.
- Project Browser UIA diagnostic showing panel accessibility but no item-level UIA rows in the current state.
- Live `project-browser-plan-navigation --sheet-number S2.0` observed Project Browser and produced a metadata-backed guarded `activate-view` route without executing it.
- Live `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr` captured Project Browser OCR/UIA evidence while still recommending the metadata-backed guarded `activate-view` route instead of clicking rows.
- Live `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr` task `live-project-browser-plan-navigation-ocr-evidence` matched visible OCR line `S2.0_1_FOUNDATION PLAN` as visual evidence while still avoiding coordinate clicks.
- Live `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-plan-navigation-ocr-geometry` preserved OCR item geometry for the same match: confidence `0.979984616691416`, bounds left `133.0`, top `193.0`, right `354.0`, bottom `214.0`, center `243.5,203.5`. It still recommended the approval-gated metadata-backed `activate-view` route and did not click coordinates.
- Live `project-browser-plan-visual-activation --sheet-number S2.0 --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-visual-click-plan` converted the same OCR geometry into a high-risk `visual-click` payload and exact approval token without executing it.
- Live `project-browser-visual-activate --sheet-number S2.0 --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-visual-click-dry-run` stayed in dry-run, reported missing exact approval for the `visual-click`, and did not click.
- Live `project-browser-plan-activation --name "S2.0"` found the Project Browser hwnd but zero item-level UIA matches, so direct activation stayed non-executable.
- Live `properties-palette-snapshot --include-uia --include-ocr --ocr-backend rapidocr --tree-depth 4 --uia-limit 300` task `live-properties-palette-snapshot` captured read-only Properties palette screenshot, UIA, and OCR evidence. OCR found 23 visible items including `Sheet: STARTING VIEW`, `Visibility/Graphics ...`, `Scale`, `Sheet Number`, `Z`, `Sheet Name`, and `STARTING VIEW`; no parameter edit, Apply click, save, sync, or model modification was executed.
- UIA tree with AutomationId/ControlType after installing `pywinauto`.
- UIA Save ribbon item discovery.
- Named ribbon `view-tab` descriptor resolved to exactly one live UIA target in dry-run. Current live planning task `live-plan-ribbon-view-tab-current` resolved the `View` UIA button and `live-uia-control-details-view-tab-current` reported supported methods including `select`, `invoke`, `set_focus`, `right_click_input`, and `toggle`; current dry-run tasks `live-dry-run-ribbon-view-tab-current` and `live-dry-run-uia-view-tab-select-current` verified exact approval-token gates, and no method was executed.
- Expanded ribbon descriptors now list 24 actions, including common Revit tabs, name-based command descriptors for Manage Links, Visibility/Graphics, View Templates, Review Warnings, and Project Information, plus blocked File/backstage, Save, Save As, Sync, Print, Export, and Publish surfaces; live `annotate-tab` planning matched exactly one UIA target and File/backstage/Print stayed non-executable.
- Live `ribbon-action-matrix` task `live-ribbon-action-matrix` validated 24 named ribbon descriptors with `failed_cases: []`, including locator/reason presence, approval-gated non-blocked descriptors, and non-executable blocked File/Save/Sync/Print/Export/Publish descriptors.
- Live `context-menu-action-matrix` task `live-context-menu-action-matrix` validated 3 named context-menu descriptors and 4 representative menu item policies with `failed_descriptors: []` and `failed_items: []`; Save/Delete surfaces stayed blocked, non-destructive menu targets stayed approval-gated, and no menu was opened or selected.
- Live `uia-method-matrix` task `live-uia-method-matrix` validated 10 allowlisted UIA methods and 21 synthetic policy cases with `failed_cases: []`, `approval_required_count: 11`, `blocked_count: 10`, `executed_count: 0`, and `live_ui_touched: false`; non-destructive targets stayed approval-required, Save targets stayed blocked for every method, unsupported methods were rejected before UIA lookup, and no UI was focused/searched/invoked.
- Live `action-approval-matrix` task `live-action-approval-matrix` validated 13 representative primitive/bridge-operation policy cases with `failed_cases: []`, `approval_required_count: 9`, `blocked_count: 2`, `allowed_count: 2`, and `executed_count: 0`; focus/click/type/non-Escape key/UIA/visual-click stayed approval-gated with exact tokens, generic Save click/UIA stayed blocked, Escape/read-only active-document stayed allowed, Save/activate-view bridge operations stayed critical approval-required, and no UI action or bridge command was executed.
- Live `ui-execution-coverage-audit` task `live-ui-execution-coverage-audit` scanned 204 sandboxed journals and reported `status: insufficient_evidence`, `target_met: false`, `qualifying_execution_count: 14`, `excluded_execution_count: 5`, covered surfaces `focus`, `escape-key`, and `dialog-click`, and missing surfaces `type-text`, `uia-invoke`, `visual-click`, `ribbon-action`, `context-menu-action`, `context-menu-item`, and `approved-ui-workflow-step`. The refreshed audit explicitly excluded dry-run workflow records from execution coverage and requires token-backed `approved_executed_steps` for workflow coverage. The audit itself did not poll, focus, click, type, invoke UIA, queue bridge operations, save, sync, reload, close, detach, upgrade, or modify Revit.
- `uia-invoke` dry-run approval for a non-blocked target.
- `uia-invoke` blocked Save target with no execution path.
- Read-only `supervise-session`.
- Live `supervise-session --resume` appended a second check to the same task log and preserved segment history.
- Live `supervise-session` task `live-supervise-endurance-real` recorded 12 checks across two resumed segments on the real Revit session, ending idle with zero active dialogs, no stall, no hung windows, and no UI/model action.
- Live `supervision-endurance-audit` task `live-supervision-endurance-audit` scanned sandboxed supervision logs against a 2-hour/24-check target and correctly reported `status: insufficient_evidence`, `target_met: false`, `qualifying_log_count: 5`, `excluded_log_count: 4`, `in_progress_log_count: 2`, `active_in_progress_log_count: 1`, `check_count: 18`, and `total_live_seconds: 54.28897299999999`; it excluded synthetic endurance-matrix logs and did not poll, focus, click, type, queue bridge operations, or touch Revit UI.
- Live `wait-model-ready --expected-title-contains "24522 St John XXIII" --expected-revit-version 2025 --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-wait-model-ready` verified idle/non-modal active-document readiness in one check with no UI action or model operation.
- Live `addin-security-preflight --revit-version 2025` task `live-addin-security-preflight-fixed` verified the Revit 2025 manifest, expected Hermes DLL path, valid Authenticode signature, and expected local signer subject; it did not click, sign, restart Revit, save, sync, or modify the model.
- Live `run-ui-workflow --name unsigned-addin-startup-preflight` task `live-run-ui-workflow-unsigned-addin-startup` ran dialog observation and add-in security preflight, then stopped before `click --target "Always Load"` because no exact approval token was supplied.
- Live `bridge-readiness --revit-version 2025` task `live-bridge-readiness-after-security-preflight` and `verify-bridge-build` task `live-verify-bridge-build-after-security-preflight` show the installed manifest/DLL are current, but the running Revit session has a stale loaded add-in payload without the new metadata block; human-approved Revit restart/reload is still required before claiming current continuous bridge readiness.
- Live `bridge-restart-validation-plan` task `live-bridge-restart-validation-plan` wrote a read-only human restart/reload handoff with `status: human_restart_required`, `pre_restart_files_ready: true`, `restart_or_reload_required: true`, `ready_for_continuous_bridge_now: false`, post-restart validation commands, and explicit blocked automation for close/restart/save/sync/reload/detach/upgrade.
- Live `bridge-post-restart-validation` task `live-bridge-post-restart-validation-current` ran the one-shot post-human-restart validation chain against the current session and failed safely before restart: Revit was idle with no dialogs, the copied detached model was ready, the add-in signature was verified, the bridge was connected, and the failed checks were `loaded_build_current` and `bridge_readiness_ready`. It wrote `bridge_post_restart_validation.json` and did not focus, click, type, invoke UIA, close, restart, save, sync, reload, detach, upgrade, or modify the model.
- `ocr-screenshot` missing-dependency artifact and screenshot.
- OCR health reports both Tesseract and RapidOCR backend readiness, and the `revit-ocr` extra includes a package-only RapidOCR backend option.
- RapidOCR was installed in the Hermes venv and live `ocr-screenshot --backend rapidocr` succeeded on the Revit main window with 123 detected text lines.
- Real stdio MCP client smoke discovered `revit_operator_health`, `revit_operator_commands`, and `revit_operator_command`, then called read-only `known-dialogs` through the MCP wrapper into a temp sandbox.
- Unit-level stalled-state supervision verifies repeated busy checks produce `stalled_state_detected`, hung-window evidence, and a read-only recovery snapshot.
- Recovery snapshot tests verify modal dialog evidence includes conservative dialog recovery plans with known dialog ids, blocked buttons, and no planned unsafe click.
- Live `recovery-drill-matrix` task `live-recovery-drill-matrix` validated 5 synthetic recovery cases with `failed_cases: []`, including a modal upgrade prompt that preserved known dialog id `upgrade-model`, returned `human_decision_required`, and produced no automatic planned action.
- Live `supervision-endurance-matrix` task `live-supervision-endurance-matrix` validated 4 synthetic long-run supervision cases with `failed_cases: []`, covering resume across two supervision segments, modal stop, busy stall with recovery snapshot capture, and unknown-state stall with recovery disabled. It used the real supervision loop with synthetic observers and did not touch live Revit, queue bridge operations, save, sync, reload, close, or modify the model.

## Verification

Latest focused verification:

```text
python -m pytest -n 0 --basetemp .\.tmp-pytest-revit -q tests\tools\test_revit_operator.py tests\plugins\test_revit_operator_plugin.py
217 passed
```

Additional verification:

```text
Python syntax compiled 35 Revit operator files plus the Hermes plugin wrapper.
CLI help lists the serve, bridge-status, addin-security-preflight, and context-menu commands.
Control-server tests verified /health, /command, and recursive serve blocking.
MCP wrapper tests verified tool registration, dispatcher delegation, JSON return shape, serve blocking by command and argv, and a real stdio MCP client read-only command call.
UIA method tests and live `uia-method-matrix` verified method discovery, explicit `select` execution under the existing `uia-invoke` primitive, synthetic policy coverage for all 10 allowlisted UIA methods, blocked Save targets for every method, unsupported-method rejection before UIA lookup, sandboxed artifact writing, and zero execution.
Context-menu tests verified descriptor listing, `context-menu-action-matrix` descriptor/item policy validation, blocked Save descriptor behavior, read-only menu/menu-item snapshots, exact-target planning, dry-run `right_click_input` routing through the existing approval gate, exact MenuItem selection dry-run, and blocked destructive menu items.
Project Browser navigation and visual fallback tests verified read-only plan generation, optional OCR line/item match evidence capture with confidence/bounds, OCR fallback routing to human review when metadata has no safe match, and approval-gated `visual-click` dry-run behavior from OCR geometry.
Properties palette tests verified read-only palette snapshot artifact creation, OCR/UIA summary propagation, top-level Properties control selection, and CLI dispatch.
Supervision resume tests verified append behavior and carried-forward state transitions.
Model-ready tests verified idle/non-modal active-document readiness, expected title/version/view predicates, modal stop behavior, and CLI artifact creation.
Supervision stall tests verified repeated busy detection and recovery snapshot capture.
Replay recovery-stop tests verified recovery snapshot capture.
Recovery snapshot tests verified embedded dialog recovery plans for modal prompts.
Recovery drill matrix tests and live `recovery-drill-matrix` verified conservative recommendation classifications, safe command suggestions, known-dialog preservation, and no automatic action for a high-risk upgrade prompt across synthetic modal/busy/idle/not-running/unknown states.
Supervision endurance matrix/audit tests and live `supervision-endurance-matrix`/`supervision-endurance-audit` verified resume/append across supervision segments, modal-stop behavior, busy-stall recovery snapshot capture, unknown-state stall handling, incremental checkpoint writing with supervisor PID, artifact writing, zero live Revit contact through the real supervision loop with synthetic observers, active/stale in-progress PID reporting, conservative active-interval extension only for confirmed running supervisor PIDs inside the checkpoint grace window, duration/checks remaining and ETA reporting, overlap-adjusted elapsed-time accounting, and fail-closed measurement of current live supervision evidence against a 2-hour/24-check target.
Workflow recipe/replay state-gate tests verified guarded UI recipe listing/planning/running, `ui-workflow-matrix` static recipe verification, `ui-workflow-smoke-matrix` live smoke-safe prefix validation, missing-parameter gates, fresh-observation modal stops, missing-token stops, approved-step token routing, workflow-run first/last observation journaling for coverage audits, `approved_executed_steps` coverage accounting, recorded active-document mismatch blocking, modal dialog mismatch blocking, bridge document context capture in action journals, parameter binding capture, parameter override planning, and blocked override reclassification.
Workflow approval plan tests and live `workflow-approval-plan` verified fresh approval-token regeneration from current replay payloads, no stale recorded-token reuse, blocked override handling, guarded execute command emission only when no step is blocked, and sandboxed artifact writing.
North-star audit/status/watch/resume/completion-gate tests and live `north-star-audit` verified prompt-to-artifact checklist generation, JSON and Markdown audit artifact writing, `objective_restatement`, `unverified_or_blocked_requirements`, command/live-evidence marker coverage, evidence-based gap evaluation from bridge readiness, live recovery snapshots, supervision endurance, and UI execution coverage artifacts, detailed endurance evidence propagation including active/stale in-progress PID counts, active-interval extension accounting, remaining duration/check counts, and ETA fields, per-gap blocker metadata for human-action, human-approval, real-condition, and cleared gates, top-level `blocker_summary` reporting, `completion_actions` splitting autonomous progress from human or real-condition gates, compact `north-star-status` blocker handoff generation with explicit `completion_gate_required` and `completion_gate_command` fields, read-only `north-star-watch` bridge/recovery state polling, read-only `north-star-resume-check` refresh of status/approval/bridge-validation/audit/completion-gate artifacts plus stable current audit/gate publishing after human-gated state changes, hard `north-star-completion-gate` refusal while the fresh audit has blocked or unverified requirements, completion-gate `blocked_gate_details` next-step reporting, completion-gate `followup_actions` stale-token guidance, completion-gate `stable_artifact_hints` pointing to the current sandbox-root handoff files, read-only `north-star-approval-verify` token explanation with no execution path, exact-current-item freshness reporting, and latest preflight readiness reporting, read-only `north-star-approval-preflight` dry-run command execution with approval/execution flags stripped plus per-item approval-readiness and expiring preflight-freshness reporting, read-only `north-star-ready-approvals` filtering so only preflight-ready items expose execute-after-approval lines, read-only `north-star-approval-plan` Markdown withholding of non-ready execute lines, read-only `north-star-blocked-ledger` unresolved-gate entries with non-ready execution commands withheld, read-only `north-star-current-handoff` stable current-file publishing including `NORTH_STAR_AUDIT_CURRENT.md` and `NORTH_STAR_READY_APPROVALS_CURRENT.md`, remaining-gap reporting, sandboxed artifact writing, and fail-closed `north_star_complete: false` while gaps remain. North-star evidence tests also verify that the latest bridge restart plan's generated no-save checklist path is carried into bridge gap evidence, and human-gate packet tests verify that the checklist is rendered in Markdown manual artifacts with token verification commands, token-bound payload digests, freshness rules, and latest preflight readiness for approval items. North-star approval-plan tests verify the read-only handoff writes exact-token candidate commands, embeds available dry-run `prevalidation` evidence, records `approval_freshness` token-bound payload digests and source artifacts, and does not execute any UI or model action.
North-star next-approval/waiting-state/approval-phrase/execution-preview tests and live `north-star-next-approval` / `north-star-waiting-state` / `north-star-approval-phrase-verify` / `north-star-approved-execution-preview` verified recommended ready-item selection, deferred ready-item execute-command withholding, stable `NORTH_STAR_NEXT_APPROVAL_CURRENT.*` and `NORTH_STAR_WAITING_STATE_CURRENT.*` publishing, exact required approval phrase rendering, exact phrase verification against the refreshed waiting state, wrong-phrase rejection, non-approval execution-preview withholding, latest-preflight context matching, preflight-freshness matching, stale-preflight command withholding, context-mismatch command withholding, and explicit false execution flags for the result, selected item, waiting state, phrase verifier, and execution preview. Current-handoff tests now verify the top-level handoff carries the `completion_actions` stop signal, including `autonomous_progress_available`, `human_or_real_condition_required`, `blocked_waiting_for_human_or_real_condition`, `waiting_state.required_human_approval_phrase`, and `waiting_state.preflight_freshness_guard`, while keeping `may_execute_from_waiting_state: false`. The latest live waiting-state refresh (`live-north-star-current-handoff-with-waiting-freshness-guard-20260513`) confirms the stable waiting artifact carries a fresh preflight guard while still denying execution authority. The latest supervised read-only checker refresh (`live-north-star-current-handoff-with-human-phrase-param-script-20260513`) also verifies that the checker requires `-HumanApprovalPhrase`, uses `<HUMAN_APPROVAL_PHRASE>` in generated command arrays instead of auto-supplying the approval phrase, parses with zero PowerShell errors, contains no literal `--execute` flag, fails closed with exit code `1` before invoking any read-only checks when given a deliberately wrong phrase, and leaves the completion gate at `phrase_must_be_supplied_by_human: true`, `auto_supplied_phrase_in_commands: false`, `execution_command_included: false`, and `may_execute_from_this_packet: false`.
North-star next-human-action tests and live `north-star-next-human-action` task `live-north-star-next-human-action-current-refresh-20260513` verified a stable one-screen `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` card that refreshes `NORTH_STAR_COMPLETION_GATE_CURRENT.*`, preserves `may_execute_from_this_result: false`, records the card as present in the completion gate's stable artifact hints, and summarizes only the current human unblock choices: human Revit restart/reload with no-save checklist and resume check, exact human approval phrase for the selected low-impact approval item, or waiting for a real recovery condition. Live `north-star-current-handoff` task `live-north-star-current-handoff-with-safety-guard-20260513` now publishes that card as part of the standard handoff, refreshes the hard gate after the card exists, and the stable gate parses it into `next_human_action_summary` with `execution_authority_violation: false`. The hard gate also now has a fail-closed `safety_guard_violations` list that blocks completion if waiting-state, next-approval, next-human-action, or supervised-checker artifacts claim execution authority; the current live gate reports zero such violations.
Expanded safety-guard tests verify each watched execution-authority source individually, and the current targeted Revit operator test slice reports `243 passed` with only the known pytest cache warning. Live `north-star-audit` task `live-north-star-audit-after-next-human-command-20260513` confirmed the implementation package remains complete with no missing commands, deliverables, prototype paths, live evidence tasks, or live evidence journals after adding `north-star-next-human-action`; it remains `status: not_complete` only because the four human/real-condition gates are still blocked.
Agent stop-status boundary tests and live `north-star-stable-artifact-scan` verified that `NORTH_STAR_AGENT_STOP_STATUS_CURRENT.*` mirrors the hard completion gate instead of becoming a second source of completion truth. The boundary guard fails closed if the stop marker claims completion, autonomous progress, execution authority, mismatched blocked gap IDs/counts, stale unsatisfied counts, safety-guard drift, Markdown drift, or approval material leakage while the hard gate remains blocked. The latest live scan `live-stable-scan-after-agent-stop-boundary-guard-20260514` reported `status: clean`, `violation_count: 0`, and `agent_stop_status_boundary_violation_count: 0`. The immediately following hard gate `live-completion-gate-after-agent-stop-boundary-guard-20260514` still reported `status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`, and `unsatisfied_count: 17`. This is explicit evidence that the active goal is still incomplete.
Read-only continuation refresh `live-north-star-watch-refresh-preflight-after-continue-20260514` refreshed approval preflight and republished the current handoff after confirming Revit was idle, non-modal, and still loading the stale bridge payload. It produced three ready human-approval candidates and zero unsafe preflight cases, but made no UI or model change and kept all execution-authority fields false. The follow-up hard gate `live-completion-gate-after-preflight-refresh-continue-20260514` remained `status: blocked` with `completion_allowed: false`, `may_call_update_goal: false`, `audit_completion_authorized: false`, four blocked gaps, and 17 unsatisfied requirements. The follow-up stable scan `live-stable-scan-after-preflight-refresh-continue-20260514` stayed clean with zero stale-approval, preflight-alignment, handoff-reference, and stop-status-boundary violations. The current human unblock brief and stable handoff are fresh, but completion still depends on human/real-condition gates.
Sanitized human-unblock and stop-status refresh `live-human-unblock-brief-after-continue-20260514` / `live-agent-stop-status-after-human-unblock-brief-continue-20260514` refreshed the credential-free handoff that says Hermes has no autonomous completion path right now. The brief lists only non-secret human/real-condition options, with all execution authority false, and the stop-status artifact reports `stop_for_human_or_real_condition`, `should_stop_agent: true`, and `wait_for_human_or_real_condition`. The final safety scan `live-stable-scan-after-agent-stop-refresh-continue-20260514` stayed clean with zero stop-status boundary violations. This confirms the latest current state is a safe pause, not a completed north star.
Restart-checklist freshness refresh `live-bridge-restart-validation-plan-checklist-refresh-20260514` verified the current copied model state and republished a no-save human checklist through `live-current-handoff-after-checklist-refresh-20260514`. The stable checklist now reflects the same active Revit 2025 state, dirty copied detached model, `STARTING VIEW / DrawingSheet`, and failed `loaded_build_current` check. The post-human resume script still parses with zero errors and no execution flag. Follow-up stable scan `live-stable-scan-after-checklist-handoff-refresh-20260514` remained clean, and hard gate `live-completion-gate-after-checklist-handoff-refresh-20260514` remained blocked with four unresolved gates and 17 unsatisfied requirements. This improves the human handoff freshness but does not clear any north-star gate.
Action approval matrix tests and live `action-approval-matrix` verified dry-run executor policy behavior for representative focus/click/type/key/UIA/visual-click primitives and classification-only bridge operations, including exact-token presence, blocked Save surfaces, critical Save/activate-view bridge policies, artifact writing, and zero execution.
UI execution coverage audit tests and live `ui-execution-coverage-audit` verified read-only journal scanning, exclusion of dry-run/synthetic/test/matrix/audit records, coverage grouping for authorized executed UI actions, payload-marked ribbon/context-menu UIA surface counting, fail-closed missing-surface reporting, and sandboxed artifact writing.
Current-dialog response planning tests verified visible-dialog planning.
Dialog workflow tests and `dialog-workflow-matrix` verified human-only upgrade, reload-link, Manage Links, type catalog, Visibility/Graphics, View Template, missing-link, open-workset, worksharing/central, warning-review, failure-processing, save-changes, and export-output-path prompts return blocked-button and preflight guidance with no planned unsafe click; allowed-button workflows remain approval-gated.
Ribbon descriptor tests and `ribbon-action-matrix` verified locator/reason coverage, approval-gated non-blocked descriptors, and blocked File/Save/Sync/Print/Export/Publish surfaces.
Context-menu matrix tests and live `context-menu-action-matrix` verified descriptor/reason coverage, approval-gated non-blocked descriptors, blocked Save descriptor behavior, and blocked Delete/Save representative menu item policies without opening a live menu.
Dialog OCR fallback tests verified OCR classification when modal dialog text is inaccessible, OCR classification when no accessible dialog is exposed but modal state exists, and no OCR prompt classification while Revit is idle.
Hermes plugin wrapper tests verified tool registration, JSON dispatch, and serve blocking.
Project Browser direct activation tests verified exact-target UIA dry-run gating and OCR-geometry visual-click approval gating.
Bridge-status tests verified add-in status/heartbeat loading, active-document status embedding, and CLI exposure of loaded-build metadata.
Bridge-build/readiness verifier tests verified expected-current metadata, stale loaded payloads, CLI `verify-bridge-build` output, and `bridge-readiness` manifest/DLL/loaded-payload gates.
Bridge restart validation plan and post-restart validation tests verified the human handoff checklist for stale loaded bridge payloads, generated `bridge_restart_no_save_checklist.md` output with active-document dirty-state context, one-shot read-only post-restart validation, blocked automation, sandboxed artifact writing, pass/fail behavior for current versus stale loaded bridge payloads, and no automated Revit close/restart/save/sync/reload action.
Live `bridge-status` task `live-bridge-status-current` confirmed the current Revit session is connected and idling but still loaded the older bridge payload without the rebuilt add-in source capability stamp.
Live `verify-bridge-build` task `live-verify-bridge-build-current` returned `stale_or_unverified`, with the bridge connected but the current metadata checks failing, which keeps the add-in validation gap open until Revit is restarted/reloaded.
Live `bridge-readiness` task `live-bridge-readiness` confirmed the source project, built DLL, and installed Revit 2025 manifest are present and aligned, but returned `ready_for_continuous_bridge: false` and `requires_revit_restart_or_reload: true` because the running session still loaded the older bridge payload.
Live `bridge-post-restart-validation` task `live-bridge-post-restart-validation-current` confirmed the current detached copied model is idle and ready, the add-in signature is verified, and the bridge is connected, but failed safely on stale loaded-build and readiness checks until human restart/reload occurs.
The Revit add-in source built against Revit 2025 with 0 errors and existing Microsoft.VisualBasic reference-conflict warnings using the workspace-local .NET 8 SDK.
```

Known warning:

```text
PytestCacheWarning: could not create cache path .pytest_cache ... Access is denied
```

The warning does not affect the focused test result.

## Remaining Gaps

The north star is not complete until these gaps are closed and live-verified:

- Verified live Project Browser item-level activation. A guarded direct UIA activation primitive exists and fails closed, and OCR line/item match geometry can now inspect the visible panel and produce a high-risk visual-click dry-run. The current Revit UI state exposes no matching item-level UIA rows for live execution, and visual-click execution has not been approved/live-executed. Metadata-backed activation remains the reliable route.
- Ribbon workflow execution beyond named tab/backstage descriptors. `ribbon-action` maps common Revit tabs to guarded UIA descriptors, `ribbon-action-matrix` verifies descriptor policy, File/Save/Sync surfaces are blocked, and `ui-execution-coverage-audit` now confirms no approved live `ribbon-action` execution coverage yet. Broader command-level ribbon workflow recipes still need live validation.
- Menu/context-menu workflows. `context-menu-action` can now plan/dry-run opening one exact context menu through `right_click_input`; `context-menu-action-matrix` verifies descriptors and representative item policies read-only; `context-menu-snapshot` can capture read-only menu item evidence; `context-menu-select-item` can dry-run/execute one exact approved `MenuItem`; `ui-execution-coverage-audit` now confirms no approved live `context-menu-action` or `context-menu-item` execution coverage yet. Broader real Revit context-menu recipes and live validation are still incomplete.
- OCR-driven handling of inaccessible dialogs and visual fallbacks. RapidOCR is installed, live-verified on Revit screenshots, and integrated as an opt-in current-dialog planning fallback with modal-state gating. Accuracy checks across real modal prompts and Tesseract support remain incomplete.
- Robust reusable workflow replay across real Revit tasks. Guarded UI workflow recipes, `ui-workflow-matrix` static recipe verification, `ui-workflow-smoke-matrix` live smoke-safe prefix validation, action approval rehearsal, a step-gated `run-ui-workflow` runner, workflow approval plans, a guarded `replay-workflow` primitive, recorded state predicates, parameter override reclassification, `approved_executed_steps` accounting, and recovery snapshot on stop now exist, but broader live validation across approved real Revit UI actions is still needed before this gap is closed.
- Broader live recovery from frozen/hung Revit and stuck dialogs. Stall detection, evidence capture, embedded dialog recovery plans, and a synthetic recovery drill matrix now exist, but live recovery drills across real stuck states are still needed.
- Safe prompt workflows for upgrade, detach, open worksets, worksharing/central, missing links, family load options, type catalogs, warning review, failure processing, save-changes, export-output-path, Manage Links, Visibility/Graphics, and View Templates. Learned classifier storage, conservative response playbooks, blocked-button guidance, safe preflight commands, and a representative playbook matrix verifier now exist, but live modal prompt drills across these surfaces still need broader validation.
- Broader approved live validation of UIA method execution beyond unit-tested `select`, available-method discovery, synthetic `uia-method-matrix` policy coverage, existing live invoke dry-runs, and `ui-execution-coverage-audit` showing zero approved live `uia-invoke` execution coverage.
- Live validation of rebuilt add-in continuous Idling after Revit restart, including `bridge-post-restart-validation.validation_passed: true`, `bridge-readiness.ready_for_continuous_bridge: true`, and `verify-bridge-build.status: current`. The current manifest/DLL/signature are verified, `bridge-restart-validation-plan` writes the human handoff, and `bridge-post-restart-validation` fails safely before restart, but the running Revit session still reports a stale loaded add-in payload until a human-approved restart/reload.

## Completion Gate

Do not mark the goal complete until every remaining gap above is either implemented and verified or explicitly removed from scope by the human. Passing tests and successful read-only live workflows are evidence of progress, not completion of the north-star goal.

The stable completion gate artifacts at `NORTH_STAR_COMPLETION_GATE_CURRENT.json` and `NORTH_STAR_COMPLETION_GATE_CURRENT.md` are the current hard stop. The latest supervised-checker refresh kept them blocked, and the refreshed gate reports `completion_allowed: false`, `may_call_update_goal: false`, `phrase_must_be_supplied_by_human: true`, and `auto_supplied_phrase_in_commands: false`. The fresh explicit completion-gate tasks `live-north-star-completion-gate-after-human-phrase-param-script-20260513`, `live-north-star-completion-gate-after-state-recheck-20260513`, `live-north-star-completion-gate-after-context-guard-20260513`, `live-north-star-completion-gate-after-freshness-guard-20260513`, `live-north-star-completion-gate-after-ready-freshness-guard-20260513`, and `live-north-star-completion-gate-after-waiting-freshness-guard-20260513` also remained blocked with `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`; the context/freshness/waiting-state guard gates reported no safety guard violations. The latest `north-star-next-human-action` task refreshed the same stable gate and remained blocked. `update_goal` may be called only when a fresh completion gate reports both `completion_allowed: true` and `may_call_update_goal: true`.

The latest live read-only recheck found no hidden state change: Revit was idle on the copied detached Revit 2025 model, there were zero visible dialogs, `bridge-readiness` still failed `loaded_build_current`, and `north-star-watch` task `live-north-star-watch-after-blocked-gate-20260513` reported `status: no_change`, `requires_revit_restart_or_reload: true`, and `requires_recovery_attention: false`.

The subsequent live read-only recheck tasks `live-north-star-recheck-status-20260513`, `live-north-star-recheck-bridge-readiness-20260513`, `live-north-star-recheck-completion-gate-20260513`, and `live-north-star-next-human-action-recheck-20260513` found the same stop state: Revit 2025 is running idle on the detached copied model, the active document is dirty, the bridge still requires a human-safe restart or reload, and the hard gate still reports `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `safety_guard_violations: []`, and the four unresolved gates `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`. The next-human-action card lists only human or real-condition unblock options and keeps `may_execute_from_this_result: false`.

Bridge-readiness reporting was tightened so quick rechecks expose failed check names without reparsing the full `checks` array. Focused tests passed (`8 passed, 231 deselected`), the full Revit operator slice passed (`243 passed`), and live read-only task `live-north-star-bridge-readiness-failed-checks-20260513` now reports `check_count: 6`, `passed_check_count: 5`, `failed_check_count: 1`, and `failed_checks: ["loaded_build_current"]` at the top level. This clarifies the blocker but does not clear it; the subsequent hard gate task `live-north-star-completion-gate-after-bridge-readiness-summary-20260513` still reports `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `safety_guard_violations: []`, and the same four blocked gates.

The human restart/reload handoff now carries compact restart context from the latest restart-validation plan. Focused tests passed (`17 passed, 222 deselected`), the full Revit operator slice passed (`243 passed`), read-only task `live-bridge-restart-validation-plan-restart-context-20260513` refreshed the no-save checklist from the current active-document bridge payload, and read-only task `live-north-star-next-human-action-current-restart-context-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with active document title/path, Revit 2025, active view `STARTING VIEW / DrawingSheet`, worksharing `enabled`, `dirty: true`, and an explicit dirty-state warning that Hermes must not choose Save, Don't Save, or Cancel. The hard gate tasks `live-north-star-completion-gate-after-restart-context-20260513` and `live-north-star-completion-gate-after-restart-context-tests-20260513` still report `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and no safety guard violations while carrying the restart context in the blocked bridge gate detail.

The human approval-phrase handoff now recomputes approval-preflight freshness from the latest stable preflight artifact when one exists, instead of trusting an older waiting-state snapshot. Focused tests passed (`19 passed, 222 deselected`) and the full Revit operator slice passed (`245 passed`), including a regression case where a stale latest preflight overrides a fresh-looking snapshot. Read-only task `live-north-star-next-human-action-preflight-freshness-source-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with `preflight_guard_source: latest_preflight_artifact`, `approval_preflight_status: preflight_stale`, `preflight_fresh_now: false`, and a warning that the approval phrase must not be used until `north-star-approval-preflight` is rerun. The hard gate tasks `live-north-star-completion-gate-after-approval-freshness-card-20260513` and `live-north-star-completion-gate-after-approval-freshness-tests-20260513` still report `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and no safety guard violations.

The hard completion gate now carries compact next-human-action option summaries, so the gate itself shows the human restart and approval freshness hazards without requiring a second artifact. Focused completion-gate/next-human-action tests passed (`16 passed, 225 deselected`) and the full Revit operator slice passed (`245 passed`). Live read-only tasks `live-north-star-completion-gate-with-option-summaries-20260513` and `live-north-star-completion-gate-after-option-summary-tests-20260513` remain blocked while showing restart option `dirty: true`, `dirty_state_warning_present: true`, approval option `preflight_guard_source: latest_preflight_artifact`, `approval_preflight_status: preflight_stale`, and `preflight_fresh_now: false` in both JSON and Markdown.

The next-human-action approval option now withholds the exact approval phrase when the latest approval preflight is stale. Focused completion-gate/next-human-action tests passed (`16 passed, 225 deselected`) and the full Revit operator slice passed (`245 passed`). Live read-only task `live-north-star-next-human-action-withheld-stale-phrase-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with `Required phrase: WITHHELD_UNTIL_PREFLIGHT_FRESH`, a preflight refresh command, and no printed stale phrase. The hard gate tasks `live-north-star-completion-gate-after-withheld-stale-phrase-20260513` and `live-north-star-completion-gate-after-withheld-stale-phrase-tests-20260513` remain blocked and record `required_human_approval_phrase_withheld: true`, `approval_preflight_status: preflight_stale`, and `approval_preflight_command_present: true` in `next_human_action_summary.option_summaries`.

After the user reiterated that the active goal must remain incomplete while the north star is blocked, live read-only task `live-north-star-approval-preflight-refresh-after-goal-reminder-20260513` refreshed the approval preflight and reported `status: preflighted`, `preflight_passed_count: 5`, `preflight_failed_count: 0`, `unsafe_preflight_count: 0`, `ready_for_human_approval_count: 3`, and a fresh 900-second preflight window expiring at `2026-05-13T13:44:40Z`. Live read-only task `live-north-star-next-human-action-after-fresh-preflight-20260513` refreshed the one-screen human-action card; the approval option now reports `approval_preflight_status: fresh`, `preflight_fresh_now: true`, `required_human_approval_phrase_withheld: false`, `phrase_must_be_supplied_by_human: true`, and `may_execute_from_this_option: false`. The follow-up hard gate task `live-north-star-completion-gate-after-fresh-preflight-human-action-20260513` still reports `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and no safety guard violations. The fresh approval packet is a current human handoff only; it does not satisfy the north-star goal and does not authorize Hermes to execute UI/model actions without the exact human-supplied phrase plus successful separate phrase verification and execution preview.

The latest blocked-state audit and stable handoff refresh also remain fail-closed. Live read-only task `live-north-star-audit-after-fresh-preflight-goal-continue-20260513` reported `status: not_complete`, `north_star_complete: false`, `blocked_gap_count: 4`, `cleared_gap_ids: ["supervision_endurance"]`, no autonomous completion path, and remaining blockers for human restart/reload, exact UI approval, real recovery-condition evidence, and approved UIA/ribbon/context-menu execution. Live read-only task `live-north-star-current-handoff-after-goal-continue-audit-20260513` republished the stable sandbox-root files and still reported `status: blocked`, `completion_allowed: false`, and `may_call_update_goal: false`.

The current handoff now exposes blocker IDs directly for agent and script consumption. `north-star-current-handoff` publishes top-level `blocked_gap_ids` and `blocked_gate_count`, and the waiting-state projection carries the same IDs. Focused current-handoff tests passed (`2 passed, 239 deselected`), the full Revit operator slice passed (`245 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-current-handoff-with-top-level-blocked-ids-20260513` refreshed the stable handoff with the four blocker IDs `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`; follow-up hard gate task `live-north-star-completion-gate-after-handoff-blocked-ids-20260513` remained blocked with no safety guard violations.

The stable handoff now also embeds the compact next-human-action option IDs and option summaries used by the completion gate. Focused current-handoff tests passed (`2 passed, 239 deselected`), the full Revit operator slice passed (`245 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-current-handoff-with-next-human-summaries-20260513` refreshed `NORTH_STAR_HANDOFF_CURRENT.*` with the three current unblock options `human-restart-or-reload-revit`, `provide-exact-human-approval-phrase`, and `wait-for-real-recovery-condition`, each with `may_execute_from_this_option: false`; follow-up hard gate task `live-north-star-completion-gate-after-handoff-next-human-summaries-20260513` remained blocked with no safety guard violations.

The completion gate now dynamically recomputes approval-preflight freshness when summarizing stable waiting-state and next-human-action artifacts, preventing an expired stable approval phrase from being treated as current. Focused north-star gate/approval tests passed (`29 passed, 214 deselected`), the full Revit operator slice passed (`247 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-completion-gate-with-dynamic-waiting-freshness-20260513` reported the latest preflight as stale, withheld the waiting-state approval phrase, marked the approval option stale in `next_human_action_summary`, disabled the supervised command packet, and still reported `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and no safety guard violations.

The next-human-action handoff now keeps the human approval path visible even when stale preflight means no next approval is selected. Focused north-star gate/approval tests passed (`31 passed, 214 deselected`), the full Revit operator slice passed (`249 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only tasks `live-north-star-current-handoff-stale-approval-path-visible-20260513` and `live-north-star-completion-gate-after-waiting-withheld-flag-fix-20260513` show the approval option as visible but blocked with no selected item, no phrase, `required_human_approval_phrase_withheld: true`, stale preflight status, no supervised command packet, and no safety guard violations. The goal remains blocked on the same four human/real-condition gates.

Stable approval artifacts now withhold stale credentials instead of merely warning around them. When the latest approval preflight is stale or lacks freshness metadata, the approval plan, human gate packet, and blocked ledger redact approval tokens, suppress exact approval phrases, clear phrase-verification/preview commands, and omit executable PowerShell while preserving dry-run guidance and withheld reasons. Focused approval/handoff tests passed (`22 passed, 224 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), and compileall passed. Live read-only task `live-north-star-current-handoff-with-stale-approval-leak-fix-20260513` republished the stable sandbox-root handoff; direct scans of `NORTH_STAR_APPROVAL_PLAN_CURRENT.*`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.*`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.*`, and `NORTH_STAR_READY_APPROVALS_CURRENT.*` found no `APPROVE:`, exact approval phrases, or `Execute only after explicit approval` lines. The follow-up hard gate `live-north-star-completion-gate-after-stale-approval-leak-fix-20260513` still reports `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `supervised_command_packet.available: false`, and `safety_guard_violations: []`.

The hard completion gate now carries the completion-audit counts directly instead of requiring callers to infer them from nested artifacts. Focused audit/gate tests passed (`24 passed, 222 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), and compileall passed. Live read-only task `live-north-star-completion-gate-with-audit-summary-20260513` reported `blocked_gate_count: 4`, `prompt_to_artifact_checklist_total_count: 124`, `prompt_to_artifact_checklist_satisfied_count: 114`, and `prompt_to_artifact_checklist_unsatisfied_count: 10`. Live read-only task `live-north-star-current-handoff-with-completion-audit-summary-20260513` republished `NORTH_STAR_COMPLETION_GATE_CURRENT.*` with the same `Completion Audit Summary`. This is stronger evidence that the goal remains incomplete, not completion authority.

The hard completion gate now also lists each unsatisfied requirement directly. Focused audit/gate tests passed (`24 passed, 222 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), and compileall passed. Live read-only task `live-north-star-completion-gate-with-unsatisfied-summaries-20260513` reported 10 `unsatisfied_requirement_summaries`, and `live-north-star-current-handoff-with-unsatisfied-summaries-20260513` republished the stable gate. `NORTH_STAR_COMPLETION_GATE_CURRENT.md` now includes `Unsatisfied Requirement Summaries`, including `gate:bridge_restart_validation` and `requirement:core-human-style-ui-operation`, while still reporting `completion_allowed: false` and `may_call_update_goal: false`.

The approval-preflight artifact now redacts approval credentials even when a current preflight is fresh: each candidate records readiness and withheld-token metadata without printing the token or executable approval PowerShell. The hard completion gate also has a stale-approval credential leak guard that scans stable approval handoff files when latest preflight freshness is stale or missing, and treats exposed approval tokens, exact phrases, executable preview text, or executable approval PowerShell as safety violations. Focused approval/gate tests passed (`25 passed, 223 deselected`), the full Revit operator slice passed (`252 passed` with the known pytest cache warning), compileall passed, and `git diff --check` passed. Live read-only task `live-north-star-approval-preflight-redacted-credentials-20260513` refreshed `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.*` with five passed dry-run preflights, zero unsafe preflights, three ready human-approval candidates, one state-change candidate, and one prevalidation candidate. A direct scan of the stable preflight JSON/Markdown found no approval token, exact approval phrase, `Execute only after explicit approval`, or executable approval PowerShell pattern. The follow-up hard gate task `live-north-star-completion-gate-after-preflight-redaction-20260513` remains the authoritative stop state: `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, 10 unsatisfied requirements, and no safety guard violations. Live handoff task `live-north-star-current-handoff-after-preflight-redaction-20260513` republished the stable current artifacts with the same four blockers.

The continuation recheck found no hidden unblocker. Live read-only `status` observed Revit idle on the copied detached Revit 2025 model with active view `STARTING VIEW / DrawingSheet`, `dirty: true`, and current bridge heartbeat/document output. Live `list-dialogs` reported zero dialogs. Live `bridge-readiness` still failed only `loaded_build_current`, which keeps the human restart/reload gate open. Live hard gate task `live-north-star-completion-gate-continuation-recheck-20260513` again reported `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, 10 unsatisfied requirements, and no safety guard violations. Live `north-star-next-human-action` and `north-star-current-handoff` continuation tasks republished the stable handoff; the remaining unblock paths are still human restart/reload, exact human approval for gated UI actions, or waiting for a real recovery condition.

The bridge restart no-save checklist now renders the current live document context instead of falling back to unknown values when the bridge active-document file uses the nested status shape. Focused bridge restart plan tests passed (`3 passed, 246 deselected`), the full Revit operator slice passed (`253 passed` with the known pytest cache warning), compileall passed, and a trailing-whitespace scan of touched files found no matches. Live read-only task `live-bridge-restart-validation-plan-nested-doc-fix-20260513` wrote a checklist naming the detached copied Revit 2025 model, active view `STARTING VIEW / DrawingSheet`, and `dirty: True`. Live handoff task `live-north-star-current-handoff-after-nested-doc-checklist-fix-20260513` republished the stable checklist, and a direct scan confirmed no unknown document fields or `dirty: None` remained. The follow-up hard completion gate `live-north-star-completion-gate-after-nested-doc-checklist-fix-20260513` still blocks completion with the same four gates and no safety guard violations.

The approval expiry recheck verified the persistent handoff fails closed after freshness expires. Hard gate task `live-north-star-completion-gate-after-approval-expiry-recheck-20260513` recomputed the latest preflight as stale, withheld the waiting-state approval phrase, disabled the supervised command packet, and detected stale approval credentials in older stable approval artifacts. Current handoff task `live-north-star-current-handoff-after-approval-expiry-redaction-20260513` then republished those stable artifacts with credentials withheld; a direct stable-file scan found no approval tokens, exact phrases, executable approval instructions, or executable approval PowerShell in the approval plan, human gate packet, or blocked ledger. The refreshed hard gate `live-north-star-completion-gate-after-approval-expiry-redaction-20260513` reports no safety guard violations, but completion remains blocked on the same four gates.

The stale-preflight redaction regression now covers every approval-facing stable artifact, not just the approval plan and ledger. The focused stale handoff test passed (`1 passed, 248 deselected`), the full Revit operator slice passed (`253 passed` with the known pytest cache warning), and compileall passed. A live broad scan across the current approval plan, ready approvals, next approval, waiting state, next-human-action, completion gate, human packet, blocked ledger, and top-level handoff stable files found no approval token, exact phrase, executable approval instruction, or executable approval PowerShell patterns. Hard gate task `live-north-star-completion-gate-after-broad-stable-redaction-test-20260513` remains blocked only by the four north-star gates and reports no safety guard violations.

The hard gate's own stale-credential scanner now covers the same top-level supervisor files that the broad live scan checks: stable completion gate, top-level handoff, and supervised read-only checker script, in addition to the approval plan, ready/next approval, waiting-state, next-human-action, human packet, and blocked-ledger artifacts. Focused completion-gate safety tests passed (`3 passed, 247 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live hard gate `live-north-star-completion-gate-after-expanded-stale-scan-scope-20260513` stayed blocked with no safety guard violations and the same four unresolved north-star gates.

The hard gate now also reports explicit remediation actions for safety-guard violations. If stale approval credentials, unreadable stale approval artifacts, or execution-authority claims are detected, `safety_guard_followup_actions` tells Hermes to regenerate the current handoff and rerun the completion gate before any approval phrase or token can be used. Focused completion-gate tests passed (`15 passed, 235 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live hard gate `live-north-star-completion-gate-with-safety-remediation-actions-20260513` shows a clean current safety state with `safety_guard_violations: []` and `safety_guard_followup_actions: []`, while the four north-star gates remain blocked.

The supervised read-only checker now requires both current phrase verification and a current approved execution preview before it can expose any executable packet. Focused current-handoff supervised-checker tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-supervised-preview-validation-20260513` kept the goal blocked, and live hard gate `live-north-star-completion-gate-after-supervised-preview-validation-20260513` again reported `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, no safety remediation actions, and the same four unresolved gates. A live scan across the current stable approval-facing artifacts, including `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1`, found no stale approval token, exact approval phrase, executable approval instruction, or executable approval PowerShell pattern. Since the current approval preflight is stale, the supervised checker stays unavailable until a fresh preflight, exact human-supplied phrase, phrase verification, and approved execution preview all pass.

The audit artifact now exposes the hard blocked state without requiring nested JSON parsing. `north-star-audit` mirrors the blocker and completion-action summaries into top-level `blocked_gap_ids`, `blocked_gap_count`, `cleared_gap_ids`, `cleared_gap_count`, `autonomous_progress_available`, `human_or_real_condition_required`, and `may_call_update_goal`. Focused audit tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live audit `live-north-star-audit-top-level-blocker-fields-20260513` reported four blocked gaps, one cleared gap (`supervision_endurance`), no autonomous progress, a human-or-real-condition requirement, and `may_call_update_goal: false`. Live handoff `live-north-star-current-handoff-after-audit-top-level-fields-20260513` republished stable `NORTH_STAR_AUDIT_CURRENT.json` with the same top-level fields while `NORTH_STAR_HANDOFF_CURRENT.json` still reports `blocked_gate_count: 4`.

The current handoff and waiting-state artifacts now expose the same blocker count under both names used in the package: `blocked_gap_count` and `blocked_gate_count`. Focused current-handoff tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-blocked-gap-count-alias-20260513` reported both counts as `4`, the stable waiting-state file reported both counts as `4` with no execution authority, and hard gate `live-north-star-completion-gate-after-handoff-gap-count-alias-20260513` stayed blocked with no safety violations.

The hard completion gate now exposes the same blocker count alias directly. `north-star-completion-gate` reports `blocked_gap_count` at the top level and inside `completion_audit_summary`, while retaining `blocked_gate_count` for existing consumers. Focused completion-gate tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live gate `live-north-star-completion-gate-blocked-gap-count-alias-20260513` and stable handoff refresh `live-north-star-current-handoff-after-gate-gap-count-alias-20260513` both show four blockers, no safety guard violations, and no completion authority.

The lightweight `north-star-status` artifact now exposes the same top-level blocker fields as the audit/gate/handoff family while still refusing completion authority. Focused status tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live status `live-north-star-status-top-level-blocker-fields-20260513` reported four blocked gaps, one cleared gap, no autonomous progress, and `completion_gate_required: true`; the follow-up hard gate `live-north-star-completion-gate-after-status-top-level-fields-20260513` stayed blocked with no safety guard violations.

The next-human-action card now carries the same blocker count fields as the hard gate and exposes them back through `next_human_action_summary`. Focused next-human-action tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live next-human card `live-north-star-next-human-action-blocker-counts-20260513` and hard gate `live-north-star-completion-gate-after-next-human-counts-20260513` both reported four blockers, no execution authority, and no safety guard violations.

The blocked ledger now exposes the same blocker IDs and counts without requiring a consumer to count entries. Focused blocked-ledger tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live ledger `live-north-star-blocked-ledger-blocker-counts-20260513`, stable handoff refresh `live-north-star-current-handoff-after-ledger-counts-20260513`, and hard gate `live-north-star-completion-gate-after-ledger-counts-20260513` all reported four blockers and no completion authority.

The human-gate packet now exposes the same top-level blocker fields as the status artifact it is based on, including blocked IDs/counts, cleared IDs/counts, remaining gap count, and the human-or-real-condition flag. Focused human-gate/stale-redaction tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live packet `live-north-star-human-gate-packet-blocker-fields-20260513`, stable handoff refresh `live-north-star-current-handoff-after-human-packet-fields-20260513`, and hard gate `live-north-star-completion-gate-after-human-packet-fields-20260513` all stayed blocked with four blockers and no safety guard violations.

The approval plan now exposes the same top-level blocker fields as the rest of the current handoff artifacts while remaining read-only and non-executing. Focused approval-plan tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live approval plan `live-north-star-approval-plan-blocker-fields-20260513`, stable handoff refresh `live-north-star-current-handoff-after-approval-plan-fields-20260513`, and hard gate `live-north-star-completion-gate-after-approval-plan-fields-20260513` all reported four blockers, one cleared gap, no autonomous progress, and no completion authority.

The compact status surface is now safe to publish as part of the stable handoff. `north-star-status` writes both JSON and Markdown, redacts approval tokens, strips executable approval flags from its approval-candidate commands, and points supervisors back to the approval-preflight/ready-approvals flow for fresh gated handoff. `north-star-current-handoff` now publishes `NORTH_STAR_STATUS_CURRENT.json` and `NORTH_STAR_STATUS_CURRENT.md`; the hard gate lists that status summary in stable artifact hints, scans it for stale credential leakage, and always fails if the status surface exposes executable approval flags. Focused status/current-handoff/guard tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoffs `live-north-star-current-handoff-with-stable-status-redacted-20260513` and `live-north-star-current-handoff-with-status-hard-gate-guard-20260513`, plus hard gates `live-north-star-completion-gate-after-stable-status-redaction-20260513` and `live-north-star-completion-gate-after-status-hard-gate-guard-20260513`, kept the goal blocked with four blockers, no safety guard violations, and no completion authority.

The hard completion gate now explains every unsatisfied checklist item directly. Each `unsatisfied_requirement_summaries` entry has a non-empty `reason`, and prompt requirements blocked by live gates also carry `blocked_by_gap_ids`. Focused completion-gate tests passed (`1 passed, 250 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-unsatisfied-reasons-20260513` and hard gate `live-north-star-completion-gate-with-unsatisfied-reasons-20260513` refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*`; all 10 unsatisfied summaries have reasons, including the four live gates and the six dependent prompt/MVP requirements, while completion remains blocked with no safety guard violations.

The compact status and full audit surfaces now carry the same blocker count alias as the rest of the handoff family. `north-star-status` and `north-star-audit` publish `blocked_gate_count` beside `blocked_gap_count` in JSON and Markdown, preventing lightweight supervisors from special-casing those two artifacts. Focused status/audit/current-handoff tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-status-audit-gate-count-alias-20260513` and hard gate `live-north-star-completion-gate-after-status-audit-gate-count-alias-20260513` refreshed the stable artifacts; all current north-star status, audit, gate, handoff, ledger, and next-human-action files report four blocked gates and no completion authority.

The compact status and full audit surfaces now deny completion authority explicitly. `north-star-status` and `north-star-audit` publish `completion_allowed: false` while still requiring a fresh `north-star-completion-gate` before `update_goal` can be considered. Focused status/audit tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-status-audit-completion-allowed-20260513` and hard gate `live-north-star-completion-gate-after-status-audit-completion-allowed-20260513` refreshed the stable status, audit, gate, handoff, ledger, and next-human-action artifacts; all six current JSON files now report `completion_allowed: false`, `blocked_gap_count: 4`, and `blocked_gate_count: 4`, with no safety guard violations and no completion authority.

Legacy `NORTH_STAR_BLOCKED_HANDOFF_CURRENT.*` artifacts now fail closed instead of lingering as old approval-token surfaces. `north-star-current-handoff` writes a deprecated redacted tombstone for the legacy JSON and Markdown files before downstream hard-gate scans run, and `_stale_approval_credential_leak_violations` scans those legacy filenames while redacting matching line text from violation records. Focused handoff/credential/status tests passed (`9 passed, 242 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-legacy-blocked-handoff-redacted-flag-20260513` republished the legacy tombstone with `deprecated: true`, `redacted: true`, and no execution authority; live hard gate `live-north-star-completion-gate-after-legacy-blocked-handoff-redacted-flag-20260513` remained blocked with no safety guard violations, and a broad stable scan found no approval credential or executable approval patterns.

The stable handoff surface now has its own read-only scanner. `north-star-stable-artifact-scan` scans every sandbox-root `NORTH_STAR_*CURRENT*` file for stale approval credentials, executable approval instructions, status-summary execution leaks, unsafe execution-authority flags, legacy blocked-handoff tombstone drift, and blocker/completion count inconsistency. It writes stable `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` / `.md` and has no authority to complete the goal. Focused scanner/audit/handoff tests passed (`9 passed, 242 deselected` and `6 passed, 248 deselected`), the full Revit operator slice passed (`258 passed` with the known pytest cache warning), and compileall passed. Live current handoff `live-north-star-current-handoff-with-stable-artifact-scan-command-20260513`, live scan `live-north-star-stable-artifact-scan-after-current-handoff-20260513`, and hard gate `live-north-star-completion-gate-after-final-stable-artifact-scan-20260513` show the current stable surface is clean (`violation_count: 0`) while the north-star goal remains blocked on the same four human/real-condition gates.

The unblock path now has a dedicated read-only readiness artifact. `north-star-unblock-readiness` writes stable `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` / `.md` with one packet per blocked gap, including current evidence presence, source artifact paths, required human or real-condition action, safe next commands, and the specific completion evidence needed. It is intentionally non-authoritative for completion and reports `completion_allowed: false`, `may_call_update_goal: false`, and `may_execute_from_this_result: false`; the hard completion authority remains `north-star-completion-gate`. Focused tests passed (`6 passed, 250 deselected`), the full Revit operator slice passed (`260 passed` with the known pytest cache warning), and live task `live-north-star-unblock-readiness-20260513` wrote the stable readiness files while preserving the four blocked gaps. The follow-up stable scan was clean, and hard gate `live-north-star-completion-gate-after-unblock-readiness-20260513` still blocks completion with zero safety guard violations. `north-star-watch` now also refreshes the hard gate and unblock-readiness at the end of each polling run, so a watch result cannot imply completion from the compact status surface alone.

Live watch hard-gate validation confirmed the new fail-closed behavior. Task `live-north-star-watch-with-hard-gate-20260513` returned `status: no_change`, embedded a blocked completion gate with four blocker IDs, and embedded an unblock-readiness summary with `may_execute_from_this_result: false`. The follow-up stable scan stayed clean, and `live-north-star-completion-gate-after-watch-hard-gate-20260513` still reports `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

`north-star-watch --refresh-approval-preflight` now optionally refreshes the read-only approval dry-run preflight with expected Revit/title/view context before the hard gate. This keeps a waiting human approval packet fresh during supervision without executing UI actions or changing completion authority; `north-star-completion-gate` remains the only source that can permit `update_goal`. Live task `live-north-star-watch-refresh-preflight-20260513` verified the preflight refresh path, refreshed the preflight window to `2026-05-13T16:55:56Z`, and still ended with the hard gate blocked on the same four blockers.

`north-star-watch --publish-current-handoff` now republishes the stable current handoff bundle after optional preflight and before the final hard gate. This keeps the human-facing `NORTH_STAR_HANDOFF_CURRENT.*`, waiting-state, next-human-action, blocked-ledger, and completion-gate files synchronized during supervision without executing UI actions or changing completion authority. Focused watch tests passed (`4 passed, 254 deselected`), the full Revit operator/plugin slice passed (`262 passed`), and compileall passed. Live task `live-north-star-watch-refresh-preflight-current-handoff-20260513` ran read-only with `--refresh-approval-preflight --publish-current-handoff`, refreshed preflight to `2026-05-13T17:04:53Z`, republished the handoff with `blocked_gap_count: 4`, and still ended with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `safety_guard_violation_count: 0`, and `unblock_readiness.may_execute_from_this_result: false`. Follow-up scan `live-north-star-stable-artifact-scan-after-watch-handoff-refresh-20260513` was clean, and hard gate `live-north-star-completion-gate-after-watch-handoff-refresh-20260513` remained blocked on `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`.

`north-star-stable-artifact-scan` now checks stable `blocked_gap_ids` against the hard completion gate, not just blocker counts. It also flags artifacts whose reported blocker count does not match their own `blocked_gap_ids` length. Focused stable-scan tests passed (`4 passed, 255 deselected`), the full Revit operator/plugin slice passed (`263 passed`), and compileall passed. Live task `live-north-star-stable-artifact-scan-with-blocker-id-guard-20260513` reported `status: clean`, `violation_count: 0`, `consistency_violation_count: 0`, and `blocker_mismatch_count: 0`; the fresh hard gate `live-north-star-completion-gate-after-blocker-id-guard-20260513` stayed blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and zero safety guard violations.

`north-star-stable-artifact-scan` now also checks fresh-preflight handoff alignment. When `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` is fresh, existing approval-facing stable handoff artifacts must not be older than that preflight; otherwise the scan reports a `fresh-preflight-stale-handoff-artifact` violation and the supervisor must regenerate the current handoff before using approval phrases. Focused stable-scan tests passed (`6 passed, 255 deselected`), the full Revit operator/plugin slice passed (`265 passed`), and compileall passed. Live task `live-north-star-stable-artifact-scan-with-preflight-alignment-20260513` reported `status: clean`, `preflight_alignment_status: aligned`, `preflight_alignment_checked: 19`, `preflight_alignment_stale: 0`, and `violation_count: 0`; hard gate `live-north-star-completion-gate-after-preflight-alignment-guard-20260513` remained blocked on the same four north-star blockers.

`north-star-stable-artifact-scan` now validates the `stable_files` references inside `NORTH_STAR_HANDOFF_CURRENT.json`. Referenced stable files must stay inside the sandbox, exist, and parse when they are JSON. Focused stable-scan tests passed (`7 passed, 255 deselected`), the full Revit operator/plugin slice passed (`266 passed`), and compileall passed. The first live scan after adding this guard surfaced expired-preflight stale-approval violations, which were cleared by a read-only `north-star-watch --refresh-approval-preflight --publish-current-handoff` task `live-north-star-watch-refresh-after-handoff-reference-guard-20260513`. The follow-up scan `live-north-star-stable-artifact-scan-after-reference-refresh-20260513` reported `status: clean`, `handoff_reference_status: ok`, `handoff_reference_count: 29`, `handoff_missing_count: 0`, `handoff_outside_sandbox_count: 0`, and `handoff_unreadable_json_count: 0`; the hard gate `live-north-star-completion-gate-after-reference-guard-20260513` stayed blocked with `completion_allowed: false`, `may_call_update_goal: false`, and the same four blockers.

`north-star-completion-gate` now directly consumes the pure stable-scan guard checks, so a future complete audit cannot bypass stable handoff integrity by skipping `north-star-stable-artifact-scan`. The gate safety guard includes stable artifact consistency, fresh-preflight handoff alignment, and stable handoff file-reference integrity. Focused completion-gate/stable-scan tests passed (`27 passed, 236 deselected`), the full Revit operator/plugin slice passed (`267 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-hard-gate-integration-20260513` was clean, and hard gate `live-north-star-completion-gate-with-integrated-stable-scan-guards-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

`north-star-unblock-readiness` now recomputes the stable-handoff guard checks directly instead of trusting only the last stable scan artifact. Its `artifact_readiness` section reports `stable_handoff_guard_clean`, `stable_handoff_guard_violation_count`, and `stable_handoff_guard_violation_ids`, so a human-facing unblock packet exposes stale handoff hazards even if `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` is stale. Focused gate/scan/unblock tests passed (`30 passed, 234 deselected`), the full Revit operator/plugin slice passed (`268 passed`), and compileall passed. Live task `live-north-star-unblock-readiness-with-dynamic-stable-guard-20260513` reported `stable_handoff_guard_clean: true`, `stable_handoff_guard_violation_count: 0`, and four remaining blockers; hard gate `live-north-star-completion-gate-after-dynamic-unblock-guard-20260513` stayed blocked with `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

`north-star-unblock-readiness` also now emits `safe_supervision_refresh_command` and `safe_supervision_refresh_powershell` in both `artifact_readiness` and each blocker packet. The command is a context-preserving, read-only `north-star-watch --refresh-approval-preflight --publish-current-handoff --checks 1 --poll 0` line built from the latest approval-preflight expected context, and tests verify that it does not include execution or approval-token flags. Live task `live-north-star-watch-refresh-after-unblock-refresh-command-20260513` refreshed the approval preflight and republished the current handoff without UI execution; the resulting readiness artifact included the context-preserving refresh PowerShell for `S2.0`, Revit `2025`, `24522 St John XXIII`, `Structural_Current Working-R25-BIM.rvt`, and `STARTING VIEW`. Stable scan `live-north-star-stable-artifact-scan-after-unblock-refresh-command-20260513` stayed clean, while hard gate `live-north-star-completion-gate-after-unblock-refresh-command-20260513` still blocked completion on the same four gates with no safety guard violations.

The stable artifact scan and hard completion gate now also validate that unblock-readiness refresh command semantically. They flag missing command arrays, missing PowerShell, wrong command names, missing refresh flags, wrong sheet/version/title/path/view context, `--execute`, approval-token flags, approval phrases, leaked `APPROVE:` tokens, packet drift, and PowerShell mismatch. This makes the readiness refresh line a checked handoff contract rather than an unchecked string. Live scan `live-north-star-stable-artifact-scan-after-refresh-command-guard-20260513` validated five current refresh-command handoffs and reported `unblock_refresh_command_violation_count: 0`; hard gate `live-north-star-completion-gate-after-refresh-command-guard-20260513` still blocked completion on the same four human/real-condition gates with zero safety guard violations.

Fresh-preflight alignment now covers `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` and `.md` too. A current approval preflight with stale unblock-readiness packets is treated as a stale handoff violation, so blocker packets and their read-only refresh command stay synchronized with the approval context.

`north-star-watch` now refreshes unblock-readiness before returning its final hard completion gate. That order matters because the hard gate directly consumes fresh-preflight alignment checks; a watch run that refreshed preflight but evaluated the gate before writing unblock-readiness would correctly report stale unblock-readiness even though the subsequent packet write fixed it. Live task `live-north-star-watch-refresh-after-watch-order-fix-20260513` verified the fixed order: the returned hard gate had zero safety guard violations while still blocking completion on the same four unresolved north-star gates.

The top-level current handoff now links the safety artifacts the hard gate depends on when they already exist. `NORTH_STAR_HANDOFF_CURRENT.json` includes `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.*` and `NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` in `stable_files`, and the stable artifact scan validates those references. Focused current-handoff/stable-scan tests passed (`14 passed, 254 deselected`), the full Revit operator/plugin slice passed (`272 passed`), and compileall passed. Live task `live-north-star-watch-refresh-after-handoff-safety-links-20260513` republished the handoff with those safety links present; live scan `live-north-star-stable-artifact-scan-after-handoff-safety-links-20260513` reported `reference_count: 33`, `present_count: 33`, `missing_count: 0`, and `violation_count: 0`; hard gate `live-north-star-completion-gate-after-handoff-safety-links-20260513` still blocked completion with four blockers and zero safety guard violations.

`north-star-watch --publish-current-handoff` now performs a final post-unblock handoff refresh before the hard gate. The watch first refreshes the handoff after approval preflight, writes unblock-readiness, then republishes the handoff so a fresh sandbox can link the newly created `NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` files before completion-gate safety checks run. Focused watch/handoff/scan/gate tests passed (`41 passed, 227 deselected`), the full Revit operator/plugin slice passed (`272 passed`), and compileall passed. Live watch `live-north-star-watch-refresh-after-post-unblock-handoff-20260513` reported `refresh_count: 2` and `post_unblock_refresh_ran: true`; live scan `live-north-star-stable-artifact-scan-after-post-unblock-handoff-20260513` remained clean; live hard gate `live-north-star-completion-gate-after-post-unblock-handoff-20260513` still blocked completion with four blockers and zero safety guard violations.

Stable artifact execution-authority scanning now fails closed for future `may_execute*` fields. The guard no longer relies only on a fixed list such as `may_execute_from_this_result`; it catches any stable JSON key that starts with `may_execute` when its value is `true`, plus the explicit command-execution booleans already guarded. Focused tests passed (`11 passed, 258 deselected` and `36 passed, 233 deselected`), the full Revit operator/plugin slice passed (`273 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-exec-authority-key-guard-20260513` stayed clean with zero violations, and live hard gate `live-north-star-completion-gate-after-exec-authority-key-guard-20260513` still blocked completion with four blockers, ten unsatisfied requirements, no completion authority, and zero safety guard violations.

Stable artifact execution-authority scanning now also covers future artifact files, not only future keys. `_stable_artifact_consistency_report` keeps the fixed required artifact checks but appends every sandbox-root `NORTH_STAR_*CURRENT*.json` file, and it treats execution-authority values as valid only when they are explicitly `false` or `null`. This catches new current handoff files and stringified booleans before they can imply execution authority. Focused tests passed (`4 passed, 267 deselected` and `38 passed, 233 deselected`), the full Revit operator/plugin slice passed (`275 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-dynamic-exec-authority-guard-20260513` stayed clean with zero violations, and live hard gate `live-north-star-completion-gate-after-dynamic-exec-authority-guard-20260513` still blocked completion with four blockers, ten unsatisfied requirements, no completion authority, and zero safety guard violations.

Fresh-preflight alignment now also covers future approval-facing current handoff files. `_stable_artifact_preflight_alignment_report` keeps the fixed approval-facing artifact list, appends future sandbox-root `NORTH_STAR_*CURRENT*` files, and excludes known credential-free/non-approval diagnostics such as status, audit, stable-scan output, legacy tombstones, restart checklists, and post-human resume scripts. Focused tests passed (`5 passed, 268 deselected` and `40 passed, 233 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live watch `live-north-star-watch-refresh-after-dynamic-preflight-alignment-20260513` refreshed preflight and republished the handoff without UI execution; live scan `live-north-star-stable-artifact-scan-after-dynamic-preflight-alignment-20260513` stayed clean with no stale alignment artifacts; live hard gate `live-north-star-completion-gate-after-dynamic-preflight-alignment-20260513` still blocked completion with four blockers, ten unsatisfied requirements, no completion authority, and zero safety guard violations.

Stale approval scanning now treats raw execution flags as credential-bearing stale approval leakage. `_stale_approval_credential_leak_violations` flags `--execute`, `--approval-token`, and `--approval-tokens-json` in stale approval-facing current artifacts in addition to approval tokens, exact approval phrases, execute-after-approval instructions, and `execute_powershell` fields, while redacting matching line text from violation records. Focused stale checks passed (`3 passed, 270 deselected`), the stable-scan/completion-gate/current-handoff/stale-approval slice passed (`42 passed, 231 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-stale-approval-flag-guard-20260513` stayed clean with zero stale approval violations; live hard gate `live-north-star-completion-gate-after-stale-approval-flag-guard-20260513` still blocked completion with four blockers, ten unsatisfied requirements, no completion authority, and zero safety guard violations.

The hard completion gate now republishes its own stable current audit and gate files. Direct `north-star-completion-gate` no longer leaves `NORTH_STAR_COMPLETION_GATE_CURRENT.*` pointing at an older watch/resume run; it writes `stable_current_files`, copies the fresh completion gate and audit artifacts to the sandbox root, and still refuses completion unless the same result reports both `completion_allowed: true` and `may_call_update_goal: true`. Focused hard-gate tests passed (`18 passed, 255 deselected`), the adjacent handoff/watch/gate slice passed (`44 passed, 229 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live task `live-north-star-completion-gate-with-direct-stable-publish-20260513` updated `NORTH_STAR_COMPLETION_GATE_CURRENT.json` to point at the fresh run while remaining blocked; live scan `live-north-star-stable-artifact-scan-after-direct-gate-stable-publish-20260513` stayed clean with zero violations.

Unsigned add-in prompt handling now recognizes unverified-publisher startup wording as well as explicit unsigned wording. Expected Hermes add-in prompts retain the approval-gated `Always Load` plan after `addin-security-preflight`, while unknown add-in prompts classify separately as `unsigned-addin-unknown`, block every load button, and plan no click. Focused dialog tests and the full Revit operator/plugin slice passed (`279 passed`). Live dialog matrix task `live-dialog-workflow-matrix-unverified-addin-guard-20260513` verified the new human-only unknown-add-in path; after a read-only watch refresh, hard gate `live-north-star-completion-gate-after-unverified-addin-refresh-20260513` remained blocked with no safety guard violations and stable scan `live-north-star-stable-artifact-scan-after-unverified-addin-refresh-20260513` stayed clean.

Each `north-star-audit` gap now includes a `blocker` object. `blocked: true`
means the missing evidence is currently gated by a named condition such as
human restart/reload, exact approval tokens, real stuck-state occurrence, or
elapsed supervision time. `blocked: false` with `autonomy_status: cleared` means
that gap's evidence has been satisfied. The audit and approval handoff also
include `blocker_summary`, which counts blocked and cleared gaps, groups blocker
types, lists blocked gap IDs, and exposes booleans for human-required,
real-condition-required, and time-gated completion gates.

Each audit also includes `completion_actions`. `autonomous_actions` contains
remaining work Hermes can continue without approval; it is currently empty
because supervision endurance is cleared and the remaining gaps are human-action,
human-approval, or real-condition gates. `human_actions` and
`real_condition_actions` list gates Hermes must not clear alone. Treat
`completion_actions.may_call_update_goal: false` as an explicit instruction that
the goal is not complete. Even when audit progress looks clean, the final
completion authority is a fresh `north-star-completion-gate` artifact with
`completion_allowed: true` and `may_call_update_goal: true`.

The live recovery-drill gap is evidence-driven. `north-star-audit` scans
`recovery_snapshot.json` artifacts and only clears the gap when a non-matrix,
non-synthetic live Revit snapshot shows a modal, busy, unknown, or hung-window
recovery condition with conservative recovery guidance. Idle snapshots and
synthetic/matrix artifacts remain useful evidence, but they do not satisfy the
live recovery-drill gate.

Approval phrase handoffs are now explicitly time-bound. When a fresh
`north-star-human-gate-packet` or `north-star-completion-gate` exposes an exact
human approval phrase, the JSON and Markdown show `approval_phrase_expires_at_utc`,
`approval_preflight_remaining_seconds`, and `approval_phrase_execution_authority:
false`. That prevents a phrase printed in a handoff from being mistaken for
permission to execute. The north-star remains blocked until the four live gates
are actually cleared and a fresh hard gate reports completion authority.

Approval phrase metadata is now a stable-artifact safety guard, not only a
rendering convention. `north-star-stable-artifact-scan` and
`north-star-completion-gate` inspect fresh-preflight `NORTH_STAR_*CURRENT*`
handoff files that expose exact approval phrases and flag any phrase context
missing expiry metadata or missing `approval_phrase_execution_authority: false`.
Live task `live-north-star-stable-artifact-scan-after-phrase-metadata-guard-20260513`
reported `approval_phrase_metadata_violation_count: 0`, and hard gate
`live-north-star-completion-gate-after-phrase-metadata-guard-20260513` still
blocked completion only on the remaining real north-star gates, with
`safety_guard_violations: []`.

The current blocked handoff was refreshed after regenerating the bridge restart
checklist. `live-bridge-restart-validation-plan-refresh-continue-20260513`
confirmed the copied local detached document is dirty and the loaded bridge
build is not current, so the next restart/reload step remains human-only and
no-save. `live-north-star-current-handoff-after-restart-plan-refresh-continue-20260513`
then republished the stable handoff around that checklist, and
`live-north-star-stable-scan-after-restart-plan-handoff-continue-20260513`
validated the root `NORTH_STAR_*CURRENT*` artifacts with zero violations. This
does not clear the north-star goal; it preserves a clean waiting state until a
human restart/reload, fresh exact approval, or real recovery condition provides
the missing evidence.

Continuation refresh `live-north-star-watch-continuation-refresh-20260513`
kept the waiting state current: Revit was running, idle, and dialog-free, the
approval preflight was refreshed to `2026-05-13T19:44:07Z`, and the hard gate
still reported four blocked gates with no safety guard violations. Stable scan
`live-north-star-stable-scan-after-continuation-watch-20260513` then checked the
root current artifacts and found zero violations, so the remaining work is still
the real north-star unblock work rather than artifact hygiene.

The command-surface checklist is stricter now. `run-safe-command` exists as a
fail-closed read-only wrapper around `active-document`, `export-metadata`, and
`qa-snapshot`, and unsupported names such as `save` are blocked before bridge
delegation. The refreshed audit from
`live-north-star-watch-after-run-safe-command-20260513` also checks
`REVIT_HUMAN_OPERATOR_LAYER_INSTRUCTIONS.md`,
`REVIT_OPERATOR_NEXT_GOAL_PROMPT.md`, `health`, `serve`, `run-safe-command`, and
`request-operation`. Stable scan
`live-north-star-stable-scan-after-run-safe-command-20260513` stayed clean, but
completion authority remains false until the human restart/reload,
human-approved live UI execution, and real recovery-condition gates are cleared.

The safe-command wrapper is now covered through the agent-facing transports as
well as the CLI. Focused tests across CLI, MCP, and `plugins/revit-operator`
passed, and the full Revit operator/plugin slice passed with `288 passed`.
Plugin and MCP tests both verify that `active-document` stays dry-run by default
and that `save --execute` is blocked before bridge delegation. Stable scan
`live-north-star-stable-scan-after-safe-wrapper-surfaces-20260513` remained
clean with no completion authority.

The same safe-command behavior is now covered through the local HTTP control
server. The `/command` regression verifies read-only `active-document` dry-run
behavior and blocked `save --execute` behavior, so the agent-facing HTTP
transport no longer relies only on CLI/plugin/MCP wrapper tests for this guard.
This improves transport coverage but does not clear any of the four remaining
north-star gates.

The local HTTP control server also exposes a read-only `/commands` discovery
endpoint now. It lists the available CLI command surface and blocked server-mode
commands, so an agent can discover `run-safe-command` and the north-star gate
commands without scraping help text or invoking actions. This is control-surface
hardening only; the hard completion gate remains blocked by the same live
human/real-condition requirements.

The prompt-to-artifact completion audit now covers the original prompt's four
architecture parts and seven aspirational design directions explicitly. These
are mapped to concrete files, commands, live evidence tasks, and remaining
gates, so the hard gate no longer treats the architecture and aspirational
sections as only prose. Live task
`live-north-star-watch-after-architecture-aspirational-checklist-20260513`
published the expanded checklist with 26 prompt-requirement entries and still
blocked completion on the same four real gates. Stable scan
`live-north-star-stable-scan-after-architecture-aspirational-checklist-20260513`
remained clean.

The source-code deliverable now has component-level checklist coverage too.
The audit explicitly checks prototype source evidence for the UI/window
observer, dialog lister/classifier, screenshot capture, safe action executor,
local command interface, optional Revit add-in bridge, and optional metadata
exporter. Live task
`live-north-star-watch-after-prototype-component-checklist-20260513` marked all
seven component entries satisfied while still blocking completion on the same
four real gates, and stable scan
`live-north-star-stable-scan-after-prototype-component-checklist-20260513`
remained clean.

The hard completion gate now has a coverage guard over the completion audit
itself. If an audit claims `status: complete` and `north_star_complete: true`
but omits any required checklist ID from the original prompt, source/component
package, command surface, live evidence set, gate list, architecture checks, or
aspirational checks, the gate adds
`completion-audit-missing-required-checklist-items` and keeps
`completion_allowed: false`. Latest live task
`live-north-star-watch-after-completion-audit-coverage-guard-20260513`
reported 156 required checklist IDs, 156 present, zero missing, but still 17
unsatisfied entries across the same four real gates. Stable scan
`live-north-star-stable-scan-after-completion-audit-coverage-guard-20260513`
reported zero violations and `may_call_update_goal: false`. This confirms the
current audit is complete in coverage, not complete in goal state.

The raw audit now exposes blocker chains directly on blocked prompt
requirements. Each unsatisfied requirement can include top-level `blocked_gaps`
and `blocked_by_gap_ids`, matching the nested evidence and the completion-gate
summary. Latest live task
`live-north-star-watch-after-raw-blocker-surfacing-20260513` shows
`requirement:core-human-style-ui-operation` blocked by both
`live_ui_workflow_execution` and `live_uia_ribbon_context_execution`, with next
steps pointing to exact human approvals. The hard gate still reports
`completion_allowed: false`, `may_call_update_goal: false`, four blocked gates,
17 unsatisfied entries, zero safety guard violations, and zero missing required
checklist IDs.

The hard completion gate now exposes the autonomy boundary directly instead of
requiring callers to inspect the audit artifact. Latest live task
`live-north-star-watch-after-gate-autonomy-boundary-20260513` published a gate
with `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and
`blocked_waiting_for_human_or_real_condition: true`. It also shows zero
autonomous actions, three human actions, and one real-condition action. This is
the current authoritative reason the thread goal must remain active: the
remaining proof requires human restart/reload, exact human approval for live UI
execution, exact human approval for live UIA/ribbon/context execution, and a
real stuck/modal/busy/unknown Revit condition for recovery evidence.

The hard completion gate also now requires audit-side completion authority.
`north-star-completion-gate` will not report `completion_allowed: true` unless
the fresh audit includes `completion_actions.may_call_update_goal: true`.
Latest live task
`live-north-star-watch-after-audit-completion-authority-20260513` reports
`audit_completion_authorized: false`, `completion_allowed: false`, and
`may_call_update_goal: false`. This closes a false-completion path where a
syntactically complete audit could otherwise omit the audit's own goal-update
authorization.

The stable current artifact scan now has the same audit-authority invariant for
published completion gates. If `NORTH_STAR_COMPLETION_GATE_CURRENT.json` claims
`completion_allowed: true` or `may_call_update_goal: true` without
`audit_completion_authorized: true`, the scan raises
`completion-gate-allowed-without-audit-authority`. Latest live task
`live-north-star-watch-after-stable-audit-authority-guard-20260513` still
reports `audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, four blocked gates, and 17 unsatisfied entries.
Stable scan
`live-north-star-stable-scan-after-stable-audit-authority-guard-20260513`
reports `status: clean`, 33 current artifacts, zero consistency violations, and
zero total violations. This does not complete the north star; it prevents stale
or malformed current artifacts from pretending the goal can be closed.

Generated handoff and resume scripts now enforce that same three-field
completion rule. The watch loop, resume-check result, next-human-action
completion option, `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`, and
`NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` require
`completion_allowed: true`, `may_call_update_goal: true`, and
`audit_completion_authorized: true` before presenting the goal as closable.
Latest live task `live-north-star-watch-after-script-audit-authority-guard-20260513`
republished those current artifacts and still reports
`audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, four blocked gates, and 17 unsatisfied entries.
Stable scan
`live-north-star-stable-scan-after-script-audit-authority-guard-20260513`
reports `status: clean`, 33 current artifacts, and zero violations.

Artifact-summary audit-authority propagation is now hardened as well.
Unblock-readiness, blocked-ledger, current-handoff, next-human-action, and
watch `current_handoff_refresh` summaries all carry normalized
`audit_completion_authorized` values, and completion-derived status uses the
shared three-field helper. Latest live task
`live-north-star-watch-after-artifact-authority-summary-guard-20260513`
reports `audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, four blocked gates, and 17 unsatisfied entries.
Stable scan
`live-north-star-stable-scan-after-artifact-authority-summary-guard-20260513`
reports `status: clean`, 33 current artifacts, and zero violations. The goal
therefore remains active, not complete.

The current-artifact producers now make audit-authority absence explicit rather
than nullable. `north-star-audit`, `north-star-status`,
`north-star-waiting-state`, and the deprecated blocked handoff tombstone all
publish `audit_completion_authorized: false` while blocked. Latest live task
`live-north-star-watch-after-explicit-audit-authority-current-fields-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`, four
blocked gates, and 17 unsatisfied entries. Stable scan
`live-north-star-stable-scan-after-explicit-audit-authority-current-fields-20260513`
reports `status: clean`, 33 current artifacts, zero violations, and explicit
`audit_completion_authorized: false` summaries for status, audit, waiting-state,
and legacy blocked-handoff current files. The north-star goal is still not
complete.

The next-human-action handoff now makes approval coverage explicit. The selected
`safe-ribbon-view-tab` item only covers
`live_uia_ribbon_context_execution`; `live_ui_workflow_execution` remains a
separate approval-gated blocker. Latest live task
`live-north-star-watch-after-next-human-approval-coverage-clarity-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, and 17 unsatisfied
entries. Stable scan
`live-north-star-stable-scan-after-next-human-approval-coverage-clarity-20260513`
reports `status: clean`, 33 current artifacts, and zero violations. The goal is
still active because the remaining blockers require human action or a real
Revit recovery condition.

The stable artifact scan now enforces the approval-coverage metadata instead of
only publishing it. It validates that the selected approval item's covered gaps
and the remaining approval blockers agree with
`selected_item_covers_all_approval_blockers`. Latest live task
`live-north-star-watch-after-approval-coverage-scan-guard-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, 17 unsatisfied
entries, and zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-approval-coverage-scan-guard-20260513`
reports `status: clean`, 33 current artifacts, zero violations, and
`approval_coverage_violation_count: 0`. The north-star goal is still not
complete.

The hard completion gate now surfaces the same approval coverage boundary in
its `next_human_action_summary`, so a reader does not need to inspect the
separate stable scan to see what the selected approval phrase does and does not
cover. Latest live task
`live-north-star-watch-after-gate-approval-coverage-summary-20260513` reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, 17 unsatisfied
entries, zero safety guard violations, `approval_coverage_status: clean`, and
`approval_coverage_violation_count: 0`. It also shows
`selected_item_gap_ids: [live_uia_ribbon_context_execution]` and
`remaining_approval_gap_ids_after_selected_item: [live_ui_workflow_execution]`.
Stable scan
`live-north-star-stable-scan-after-gate-approval-coverage-summary-20260513`
reports `status: clean`, 33 current artifacts, and zero violations. The goal
therefore remains active, not complete.

The human-readable completion gate now surfaces the same approval coverage
boundary as the JSON gate. Latest live task
`live-north-star-watch-after-gate-markdown-approval-coverage-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, 17 unsatisfied
entries, and zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-gate-markdown-approval-coverage-20260513`
reports `status: clean`, zero violations, and
`approval_coverage_violation_count: 0`. The current completion gate markdown
now shows the selected approval item covers
`live_uia_ribbon_context_execution` while
`live_ui_workflow_execution` remains in
`remaining_approval_gap_ids_after_selected_item`. The north-star goal is still
not complete.

The stable artifact scan now detects drift between the completion gate markdown
and the JSON approval coverage boundary. Latest live stable scan
`live-north-star-stable-scan-after-gate-markdown-coverage-drift-guard-20260513`
reports `status: clean`, zero violations,
`completion_gate_markdown_approval_coverage_violation_count: 0`,
`expected_line_count: 6`, and `missing_line_count: 0`. The hard gate still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, 17 unsatisfied
entries, and zero safety guard violations, so the goal remains active.

The unblock-readiness handoff guard now includes the approval coverage and
completion-gate markdown drift checks directly, instead of relying only on the
latest stable scan summary. Latest live unblock-readiness task
`live-north-star-unblock-readiness-after-markdown-coverage-guard-20260513`
reports `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, four
blocked gaps, four blocked gates, `stable_artifact_scan_clean: true`,
`stable_handoff_guard_clean: true`, and
`stable_handoff_guard_violation_count: 0`. The north-star goal is still not
complete.

The unblock-readiness markdown now includes the third hard completion-authority
field, `audit_completion_authorized`, and the stable artifact scan verifies the
markdown against the unblock-readiness JSON. Latest live stable scan
`live-north-star-stable-scan-after-unblock-markdown-guard-20260513` reports
`status: clean`, zero violations,
`unblock_readiness_markdown_completion_guard.status: clean`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-unblock-markdown-guard-20260513`
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The north-star goal
therefore remains active, not complete.

The hard completion gate now exposes an explicit
`safety_guard_violation_count` in JSON, summary, and markdown. Latest hard gate
`live-north-star-completion-gate-after-safety-count-20260513` reports
`status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and `safety_guard_violation_count: 0`. Stable scan
`live-north-star-stable-scan-after-safety-count-20260513` reports
`status: clean` and zero violations. The north-star goal remains active.

The stable artifact scan now verifies the hard gate's safety guard count
instead of merely displaying it. It compares `safety_guard_violation_count`
against the `safety_guard_violations` list length and
`completion_audit_summary.safety_guard_violation_count`. Latest live stable
scan `live-north-star-stable-scan-after-safety-count-consistency-20260513`
reports `status: clean`, zero violations, `consistency_violation_count: 0`, and
matching safety counts of 0 at the top level, list length, and completion audit
summary. The hard completion gate remains blocked with four blocked gaps and 17
unsatisfied requirements.

The completion-gate markdown now has an audited safety-count mirror. Final
stable scan
`live-north-star-stable-scan-after-markdown-safety-count-final-20260513`
reports
`status: clean`, zero violations,
`completion_gate_markdown_safety_count.status: clean`,
`expected_line_count: 2`, and `missing_line_count: 0`, proving the current
human-readable gate includes the same `safety_guard_violation_count: 0` as the
JSON gate and the Safety Guard Violations section count. Fresh hard gate
`live-north-star-completion-gate-after-markdown-safety-count-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal is still
blocked, not complete.

The human-gate packet now explicitly denies completion and execution authority.
Its JSON publishes `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`; its markdown mirrors those fields before
the human checklist. Final stable scan
`live-north-star-stable-scan-after-human-gate-guard-final-20260513` reports
`status: clean`, zero violations,
`human_gate_packet_markdown_completion_guard.status: clean`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-gate-guard-20260513` still reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The human packet is
therefore only a supervised handoff; the goal remains active, not complete.

The current handoff now explicitly denies completion and execution authority.
Its JSON publishes `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, and
`may_execute_from_this_result: false`; its markdown mirrors those four fields.
The blocked ledger also publishes `may_execute_from_this_result: false`.
Final stable scan
`live-north-star-stable-scan-after-handoff-guard-final-20260513` reports
`status: clean`, zero violations,
`handoff_markdown_completion_guard.status: clean`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-handoff-guard-20260513` still reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal is still
blocked, not complete.

The next-human-action card now explicitly denies completion and execution
authority in both JSON and markdown. The markdown mirrors
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`. Final stable scan
`live-north-star-stable-scan-after-next-human-markdown-guard-final-20260513`
reports `status: clean`, zero violations,
`next_human_action_markdown_completion_guard.status: clean`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-markdown-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The ready-approvals artifact now explicitly denies execution authority in both
JSON and markdown. `NORTH_STAR_READY_APPROVALS_CURRENT.md` mirrors
`may_execute_from_this_result: false` from the JSON artifact, and stable scan
`live-north-star-stable-scan-after-ready-approvals-markdown-guard-final-20260513`
reports `status: clean`, zero violations,
`ready_approvals_markdown_execution_guard.status: clean`,
`expected_line_count: 1`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-ready-approvals-markdown-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The deprecated legacy blocked-handoff tombstone now explicitly denies
completion and execution authority in both JSON and markdown. Its markdown
mirrors `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`. Final stable scan
`live-north-star-stable-scan-after-legacy-handoff-markdown-guard-final-20260513`
reports `status: clean`, zero violations,
`legacy_blocked_handoff_markdown_completion_guard.status: clean`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-legacy-handoff-markdown-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The stable artifact scan now has a generic authority Markdown mirror guard.
For every `NORTH_STAR_*_CURRENT.json` file with a matching Markdown artifact,
any exposed `completion_allowed`, `may_call_update_goal`,
`audit_completion_authorized`, or `may_execute_from_this_result` field must be
mirrored in the Markdown. Final stable scan
`live-north-star-stable-scan-after-authority-mirror-guard-final-20260513`
reports `status: clean`, zero violations,
`authority_markdown_mirror.status: clean`, `checked_artifact_count: 13`,
`checked_key_count: 42`, and `skipped_missing_markdown_count: 0`. Fresh hard
gate `live-north-star-completion-gate-after-authority-mirror-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

Recovery snapshots now carry an explicit north-star qualification result.
`live-recovery-gate-idle-snapshot-20260513` observed Revit as `idle`, so it
recorded `validated_live_recovery_drill: false` and
`north_star_recovery_gate.qualifies: false` with the exclusion reason
`snapshot does not show a live recovery condition`. This keeps idle observation
evidence separate from a real stuck/frozen/modal/busy/unknown recovery drill.
Final stable scan
`live-north-star-stable-scan-after-recovery-qualification-final-20260513`
reports `status: clean` and zero violations. Fresh hard gate
`live-north-star-completion-gate-after-recovery-qualification-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

Stable artifact scanning now verifies recovery snapshot qualification claims.
Any sandbox `revit_operator_runs/*/recovery_snapshot.json` artifact that claims
`validated_live_recovery_drill: true` must also include a qualifying embedded
`north_star_recovery_gate`, and the current classifier must still agree. Final
stable scan
`live-north-star-stable-scan-after-recovery-qualification-guard-final-20260513`
reports `status: clean`, zero violations,
`recovery_snapshot_qualification.status: clean`, `checked_snapshot_count: 9`,
`claimed_valid_count: 0`, `embedded_qualifying_gate_count: 0`, and
`computed_qualifying_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-recovery-qualification-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The latest read-only supervision refresh handled approval-preflight expiry.
Stable scan `live-north-star-stable-scan-preflight-expiry-check-20260513`
correctly detected stale approval-credential exposure after the prior preflight
expired at `2026-05-13T23:18:16Z`. Read-only watch
`live-north-star-watch-refresh-after-preflight-expiry-20260513` refreshed the
approval preflight and current handoff, observed Revit `idle` with zero dialogs,
and did not perform any UI or model action. Final stable scan
`live-north-star-stable-scan-after-preflight-refresh-final-20260513` reports
`preflight_status: fresh`, expiry `2026-05-13T23:34:01Z`, `status: clean`, zero
violations, and `stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-preflight-refresh-20260513` still reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The stale-approval remediation follow-up now directs future agents to the exact
read-only refresh path instead of a generic handoff repair. For
`stale-approval-credential-leak`, the safety follow-up lists
`north-star-watch --refresh-approval-preflight --publish-current-handoff
--checks 1 --poll 0`, followed by `north-star-stable-artifact-scan` and
`north-star-completion-gate`, and points to
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` for the context-matched
`safe_supervision_refresh_command`. Final stable scan
`live-north-star-stable-scan-after-stale-followup-guard-final-20260513` reports
`preflight_status: fresh`, expiry `2026-05-13T23:34:01Z`, `status: clean`, zero
violations, and `stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-stale-followup-guard-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The stable artifact scan now emits a preflight refresh advisory before approval
material actually goes stale. When a current approval preflight is fresh but
inside the advisory window, the scan remains `clean` but reports
`preflight_refresh_advisory.status: refresh_soon` and supplies only the
read-only `north-star-watch --refresh-approval-preflight
--publish-current-handoff --checks 1 --poll 0` refresh path. Live stable scan
`live-north-star-stable-scan-after-preflight-advisory-final-20260513` reported
`status: clean`, zero violations, `refresh_recommended: true`, about 90 seconds
remaining before the `2026-05-13T23:34:01Z` approval-preflight expiry, and zero
stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-preflight-advisory-20260513` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. A follow-up
read-only watch refresh
`live-north-star-watch-refresh-after-preflight-advisory-20260513` refreshed the
preflight/current handoff without any UI or model action. Final stable scan
`live-north-star-stable-scan-after-preflight-advisory-refresh-final-20260513`
reported `status: clean`, zero violations,
`preflight_refresh_advisory.status: fresh`, `refresh_recommended: false`, about
807 seconds remaining before the refreshed `2026-05-13T23:48:01Z` expiry, and
zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-preflight-advisory-refresh-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The stable artifact scan now verifies read-only PowerShell handoff scripts
directly. `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` and
`NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` are checked for required
read-only validation commands, the three-field completion-gate guard, and
absence of execution/write affordances such as `--execute`, `--approval-token`,
direct UI command names, approved-execution command names, and write-oriented
commands. Live stable scan
`live-north-star-stable-scan-after-readonly-script-guard-20260513` reported
`status: clean`, zero violations, `stable_readonly_script_guard.status: clean`,
2 checked scripts, `forbidden_match_count: 0`, and
`missing_completion_guard_count: 0`. A read-only watch refresh
`live-north-star-watch-refresh-after-readonly-script-guard-20260513` refreshed
preflight/current handoff after the advisory window was reached. Final stable
scan
`live-north-star-stable-scan-after-readonly-script-guard-refresh-final-20260513`
reported `status: clean`, zero violations,
`stable_readonly_script_guard.status: clean`, 2 checked scripts,
`forbidden_match_count: 0`, `missing_completion_guard_count: 0`, and a fresh
preflight with about 813 seconds remaining. Fresh hard gate
`live-north-star-completion-gate-after-readonly-script-guard-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps are
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The stable artifact scan now verifies next-human Markdown approval coverage.
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` must mirror the approval coverage
boundary from `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`, including
`approval_blocker_gap_ids`, `selected_item_gap_ids`,
`remaining_approval_gap_ids_after_selected_item`,
`selected_item_covers_all_approval_blockers`, and
`approval_coverage_fields_present`. Targeted next-human coverage tests passed
(`4 passed`), the focused north-star/stable group passed (`73 passed`), the
full Revit operator/plugin slice passed (`321 passed`), and compileall passed.
Live scan
`live-north-star-stable-scan-detect-next-human-markdown-coverage-20260513`
found one stale Markdown coverage violation with five missing lines. The
read-only watch refresh
`live-north-star-watch-refresh-after-next-human-markdown-coverage-20260513`
republished current handoff artifacts. Final stable scan
`live-north-star-stable-scan-after-next-human-markdown-coverage-refresh-20260513`
reported `status: clean`, zero violations,
`next_human_action_markdown_approval_coverage.status: clean`, zero missing
coverage lines, clean completion-gate Markdown approval coverage, fresh
preflight, and zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-next-human-markdown-coverage-refresh-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The stable artifact scan now verifies the unblock-readiness stable-scan mirror.
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` must not be more permissive than
the current `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json`; optimistic drift,
such as claiming the stable scan is clean while the scan has violations, blocks
both the stable scan and the hard completion gate. Pessimistic stale data is
reported as refresh-worthy but does not authorize execution. Targeted mirror
tests passed (`4 passed`), the focused north-star/stable group passed
(`71 passed`), the full Revit operator/plugin slice passed (`320 passed`), and
compileall passed. Live scan
`live-north-star-stable-scan-detect-unblock-mirror-drift-20260513` initially
detected one unblock mirror violation with three mismatched fields. After the
rule was narrowed to optimistic risk and the read-only watch refresh
`live-north-star-watch-refresh-clear-pessimistic-unblock-mirror-20260513`
republished current handoff artifacts, final stable scan
`live-north-star-stable-scan-after-unblock-mirror-clear-refresh-20260513`
reported `status: clean`, zero violations,
`unblock_stable_scan_mirror.status: ok`,
`unblock_stable_scan_mirror_violation_count: 0`, zero optimistic mismatches,
zero pessimistic mismatches, fresh preflight, and zero stale approval
violations. Fresh hard gate
`live-north-star-completion-gate-after-unblock-mirror-clear-refresh-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The stable artifact scan now verifies the latest resume-check artifact's
top-level completion mirror. If `revit_operator_runs/*/north_star_resume_check.json`
exists, the stable scan requires top-level `completion_allowed`,
`may_call_update_goal`, `audit_completion_authorized`, blocked gap counts,
unsatisfied count, and safety guard count to be present and to match the nested
`completion_gate`. The first live scan after this guard reported
`latest_resume_completion_mirror.status: violations` because the existing
resume artifact did not publish all of those top-level fields. The
`north-star-resume-check` result now writes the missing top-level fields and
keeps the nested completion-gate fields used by the mirror comparison. Targeted
resume artifact tests passed (`4 passed`), the focused north-star/stable group
passed (`67 passed`), the full Revit operator/plugin slice passed
(`316 passed`), and compileall passed. Live read-only resume check
`live-north-star-resume-check-after-resume-artifact-fix-20260513` reported
completion denied with four blocked gaps, four blocked gates, 17 unsatisfied
requirements, and a failed bridge validation. Read-only watch refresh
`live-north-star-watch-refresh-after-resume-artifact-fix-20260513` refreshed
approval preflight/current handoff and cleared stale preflight safety
violations. Final stable scan
`live-north-star-stable-scan-after-watch-refresh-20260513` reported
`status: clean`, zero violations,
`latest_resume_completion_mirror.status: clean`,
`latest_resume_completion_mirror_violation_count: 0`,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`, fresh preflight, and zero
stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-watch-refresh-20260513` still reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The read-only script guard now verifies sandbox binding and goal-update
language. Both stable PowerShell handoff scripts must include the current
sandbox path and `--sandbox` argument, and any `update_goal` reference must be
limited to explicit `do not call update_goal` warning text. Live stable scan
`live-north-star-stable-scan-after-script-binding-guard-20260513` reported
`status: clean`, zero violations, `stable_readonly_script_guard.status: clean`,
2 checked scripts, `forbidden_match_count: 0`,
`unsafe_goal_update_reference_count: 0`, `missing_sandbox_binding_count: 0`,
`missing_completion_guard_count: 0`, and zero stale approval violations. Fresh
hard gate `live-north-star-completion-gate-after-script-binding-guard-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

`north-star-watch` now mirrors the hard completion gate at the top level of its
JSON output. Live read-only watch
`live-north-star-watch-top-level-gate-fields-20260513` refreshed approval
preflight/current handoff and reported top-level `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`, matching the nested `completion_gate`
summary. Final stable scan
`live-north-star-stable-scan-after-watch-top-level-fields-20260513` reported
`status: clean`, zero violations, fresh preflight, clean script guard, and zero
stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-watch-top-level-fields-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The stable artifact scan now verifies the latest watch artifact's top-level
completion mirror. If `revit_operator_runs/*/north_star_watch.json` exists, the
stable scan requires top-level `completion_allowed`, `may_call_update_goal`,
`audit_completion_authorized`, blocked gap counts, unsatisfied count, and safety
guard count to be present and to match the nested `completion_gate`. Live
read-only watch `live-north-star-watch-refresh-for-watch-mirror-guard-20260513`
reported completion denied with four blocked gaps and 17 unsatisfied
requirements. Final stable scan
`live-north-star-stable-scan-after-watch-mirror-guard-20260513` reported
`status: clean`, zero violations,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`,
`missing_top_level_field_count: 0`, `mismatch_count: 0`, fresh preflight, clean
script guard, and zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-watch-mirror-guard-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The hard completion gate now has explicit watch-mirror regression coverage. A
drifting latest `north_star_watch.json` artifact causes
`latest-watch-top-level-completion-field-mismatch`, prevents
`completion_allowed`, and produces the `repair-stable-handoff-artifacts`
follow-up action even if a test audit otherwise claims completion. Live stable
scan `live-north-star-stable-scan-after-watch-mirror-hard-gate-20260513`
reported `status: clean`, zero violations,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`,
`missing_top_level_field_count: 0`, `mismatch_count: 0`, fresh preflight, and
zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-watch-mirror-hard-gate-20260513` still
reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The human gate packet now exposes approval item `gap_ids` in Markdown and the
stable scan/hard gate require those lines to mirror
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json`. This closes a human-handoff gap
where an approval item could show an approval phrase without plainly showing
which north-star blockers it covers. Targeted tests passed (`3 passed`), the
focused north-star/stable group passed (`75 passed`), the full Revit
operator/plugin slice passed (`323 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-detect-human-gate-approval-gap-20260513`
first reported one stale Markdown violation with five missing `gap_ids` lines.
Read-only watch refresh
`live-north-star-watch-refresh-after-human-gate-approval-gap-20260513`
republished the current handoff. Final stable scan
`live-north-star-stable-scan-after-human-gate-approval-gap-refresh-20260513`
reported `status: clean`, zero violations, clean human-gate approval gap
mirror, fresh preflight, and zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-human-gate-approval-gap-refresh-20260513`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The ready-approvals packet now exposes ready item `gap_ids` in Markdown and the
stable scan/hard gate require those lines to mirror
`NORTH_STAR_READY_APPROVALS_CURRENT.json`. This closes the higher-risk handoff
case where an item can include an approval phrase and guarded execute command
without plainly showing which north-star blocker it applies to. Targeted tests
passed (`3 passed`), the focused north-star/stable group passed (`80 passed`),
the full Revit operator/plugin slice passed (`325 passed`), and compileall
passed. Live stable scan
`live-north-star-stable-scan-detect-ready-approvals-approval-gap-20260514`
first reported one stale Markdown violation with three missing ready item
`gap_ids` lines. Read-only watch refresh
`live-north-star-watch-refresh-after-ready-approvals-approval-gap-20260514`
republished the current handoff. Final stable scan
`live-north-star-stable-scan-after-ready-approvals-approval-gap-refresh-20260514`
reported `status: clean`, zero violations, clean ready-approvals approval gap
mirror, fresh preflight, and zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-ready-approvals-approval-gap-refresh-20260514`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The next-approval packet now exposes the selected approval item's `gap_ids` in
Markdown and the stable scan/hard gate require that line to mirror
`NORTH_STAR_NEXT_APPROVAL_CURRENT.json`. This closes the single-candidate
approval handoff case where the selected item has the exact approval phrase and
guarded execute command. Targeted tests passed (`4 passed`), the focused
north-star/stable group passed (`84 passed`), the full Revit operator/plugin
slice passed (`327 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-detect-next-approval-approval-gap-20260514`
first reported one stale Markdown violation with one missing selected-item
`gap_ids` line. Read-only watch refresh
`live-north-star-watch-refresh-after-next-approval-approval-gap-20260514`
republished the current handoff. Final stable scan
`live-north-star-stable-scan-after-next-approval-approval-gap-refresh-20260514`
reported `status: clean`, zero violations, clean next-approval approval gap
mirror, clean ready-approvals approval gap mirror, fresh preflight, and zero
stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-next-approval-approval-gap-refresh-20260514`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

The waiting-state handoff now exposes the selected next approval item's
`gap_ids` in both JSON and Markdown, and the stable scan/hard gate require
those values to mirror `NORTH_STAR_NEXT_APPROVAL_CURRENT.json`. This closes the
current-handoff case where a waiting-state approval phrase could be visible
without the same blocker-scope line shown in the selected next approval packet.
Targeted tests passed (`3 passed`), the focused north-star/stable group passed
(`126 passed`), the full Revit operator/plugin slice passed (`329 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-detect-waiting-state-approval-gap-20260514`
first reported two stale waiting-state approval-gap violations with one missing
Markdown line. Read-only watch refresh
`live-north-star-watch-refresh-after-waiting-state-approval-gap-20260514`
republished the current handoff with `safety_guard_violation_count: 0`. Final
stable scan
`live-north-star-stable-scan-after-waiting-state-approval-gap-refresh-20260514`
reported `status: clean`, zero violations, clean waiting-state approval gap
mirror, fresh preflight, and zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-waiting-state-approval-gap-refresh-20260514`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. The blocked gaps
remain `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

Continuation audit remains blocked. Read-only watch
`live-north-star-watch-continue-20260514` refreshed the handoff without
execution and still reported four blocked gaps, four blocked gates, 17
unsatisfied requirements, and zero safety guard violations. Fresh hard gate
`live-north-star-completion-gate-continue-20260514` still reports
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and `human_or_real_condition_required: true`. Dry-run
`live-ribbon-view-tab-dry-run-inspect-20260514` found the Revit `View` ribbon
button exactly and did not execute; the policy remained `approval_required`.
Approval-plan refresh `live-north-star-approval-plan-continue-20260514` shows
ready approval items for `safe-ribbon-view-tab`,
`direct-uia-view-tab-select`, and `approved-workflow-open-sheet`, but they are
not execution authority unless the human supplies an exact current approval
phrase. Additional dry-runs
`live-uia-view-tab-select-dry-run-inspect-20260514`,
`live-approved-workflow-open-sheet-dry-run-continue-20260514`,
`live-project-browser-plan-navigation-continue-20260514`, and
`live-request-activate-view-dry-run-continue-20260514d` added read-only
evidence that Revit is idle and connected, `S2.0` has a single
metadata-backed sheet match, the deterministic guarded add-in route is
available, and every live action still stops at `approval_required`. Stable
scan `live-north-star-stable-scan-after-dryruns-20260514` reports `status:
clean`, zero violations, fresh preflight, and zero stale approval violations.
Hard gate `live-north-star-completion-gate-after-dryruns-20260514` still
reports blocked with the same four blocker IDs. Stable scan
`live-north-star-stable-scan-continue-20260514` reports
`status: clean`, zero violations, fresh preflight, and zero stale approval
violations. The blocked gaps remain `bridge_restart_validation`,
`live_ui_workflow_execution`, `live_recovery_drills`, and
`live_uia_ribbon_context_execution`; the goal remains active, not complete.

Bridge restart validation is now narrowed to a loaded-add-in freshness problem.
The first post-restart validation attempt
`live-bridge-post-restart-validation-no-restart-20260514` used an expected path
ending in `.rvt`, which did not match the active detached copied-local filename
`24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM_detached.rvt`.
The corrected read-only validation
`live-bridge-post-restart-validation-no-restart-detached-path-20260514` proved
the model is idle, non-modal, Revit 2025, and on `STARTING VIEW`, but still
failed bridge restart validation because the loaded add-in does not report the
current bridge build metadata. `live-verify-bridge-build-after-post-restart-check-20260514`
reported `stale_or_unverified`, and
`live-bridge-readiness-after-post-restart-check-20260514` reported `not_ready`:
the DLL and manifest are present and connected, but loaded add-in metadata is
missing `bridge_protocol_version 0.2`,
`source_capability_stamp: continuous-idling-status-v1`,
continuous-idling support, and `SetRaiseWithoutDelay` support. Restart plan
`live-bridge-restart-validation-plan-after-stale-build-20260514` therefore
reports `human_restart_required`, `pre_restart_files_ready: true`, and
`restart_or_reload_required: true`. Hermes is still blocked from closing,
restarting, saving, syncing, reloading, detaching, upgrading, or modifying
Revit. Refresh
`live-north-star-watch-refresh-after-bridge-stale-20260514` and stable scan
`live-north-star-stable-scan-after-bridge-watch-refresh-20260514` stayed
read-only and clean, with the next approval phrase refreshed through
`2026-05-14T01:52:22Z`. The goal remains active, not complete, until a human
safely restarts/reloads Revit and the loaded add-in reports the current bridge
metadata.

The next-human-action handoff now mirrors the bridge restart blocker's
technical cause instead of only saying restart/reload is required. The current
stable card exposes `bridge_technical_cause: Loaded Revit add-in is stale or
lacks current bridge metadata.`, `failed_bridge_checks: loaded_build_current`,
`requires_revit_restart_or_reload: true`, and
`no_save_checklist_present: true` for `human-restart-or-reload-revit`. Targeted
coverage passed (`1 passed`), the focused north-star/stable suite passed
(`126 passed`), the full Revit operator/plugin slice passed (`329 passed`),
and compileall passed. Live artifact refresh
`live-north-star-next-human-action-bridge-cause-20260514` wrote those fields,
stable scan
`live-north-star-stable-scan-after-next-human-bridge-cause-20260514` reported
clean, and hard gate
`live-north-star-completion-gate-after-next-human-bridge-cause-20260514`
remained blocked with four blockers and zero safety guard violations. The goal
remains active, not complete.

The bridge-cause handoff is now enforced by the stable scan and hard gate. The
new guard requires `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` to mirror the
restart option's technical cause, failed bridge checks, restart requirement,
and no-save checklist presence from JSON. A drift raises
`next-human-markdown-bridge-cause-drift` and routes to
`repair-stable-handoff-artifacts`. Targeted bridge-cause guard tests passed
(`2 passed`), the focused north-star/stable suite passed (`128 passed`), the
full Revit operator/plugin slice passed (`331 passed`), and compileall passed.
Live scan
`live-north-star-stable-scan-after-bridge-cause-watch-refresh-20260514`
reported clean bridge-cause mirroring, zero violations, fresh preflight, and
zero stale approval violations. Fresh hard gate
`live-north-star-completion-gate-after-bridge-cause-watch-refresh-20260514`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates,
17 unsatisfied requirements, and zero safety guard violations. The current
selected approval phrase expires at `2026-05-14T02:06:51Z`; the goal remains
active, not complete.

The human restart/no-save checklist now carries the same bridge freshness
cause as the next-human-action card. `bridge-restart-validation-plan` writes a
`Bridge Reload Cause` section into
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`, including the stale
loaded add-in cause, `failed_readiness_checks: loaded_build_current`, failed
loaded-build metadata checks, expected bridge metadata
`bridge_protocol_version 0.2` and
`source_capability_stamp continuous-idling-status-v1`, continuous-Idling and
`SetRaiseWithoutDelay` expectations, and the observed missing loaded metadata.
Targeted checklist coverage passed (`2 passed`), the full Revit
operator/plugin slice passed (`331 passed`), and compileall passed. Live plan
`live-bridge-restart-validation-plan-checklist-cause-20260514` remained
read-only and reported `human_restart_required`; watch refresh
`live-north-star-watch-refresh-after-checklist-cause-20260514` republished the
current handoff. Stable scan
`live-north-star-stable-scan-after-checklist-cause-20260514` reported
`status: clean`, zero violations, and zero stale approval leaks. Fresh hard
gate `live-north-star-completion-gate-after-checklist-cause-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`, and
`audit_completion_authorized: false`. The goal remains active, not complete.

The restart/no-save checklist bridge-cause content is now part of the hard
stable-handoff guard set. When the current next-human-action JSON exposes a
`human-restart-or-reload-revit` option with bridge-cause metadata, the stable
scan and hard completion gate require
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` to include the
`Bridge Reload Cause` section, stale loaded-addin root cause,
`failed_readiness_checks: loaded_build_current`, loaded-build metadata failure
details, expected bridge protocol/source capability values, continuous-Idling
expectations, and observed loaded metadata. Drift raises
`restart-checklist-bridge-cause-drift` and routes to
`repair-stable-handoff-artifacts`. Targeted guard tests passed (`4 passed`),
the focused north-star/stable suite passed (`76 passed`), the full Revit
operator/plugin slice passed (`333 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-after-checklist-bridge-cause-guard-final-20260514`
reported clean checklist bridge-cause validation and zero violations. Fresh
hard gate
`live-north-star-completion-gate-after-checklist-bridge-cause-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The stable next-human-action post-human resume script path is now guarded. The
stable scan and hard completion gate require
`human-restart-or-reload-revit.post_action_resume_script` to equal
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` and require the Markdown card
to show that same `Resume script:` line. Drift raises
`next-human-resume-script-path-drift` or
`next-human-resume-script-markdown-drift` and routes to stable handoff repair.
Targeted resume-script-path coverage passed (`2 passed`), the focused
north-star/next-human/stable suite passed (`86 passed`), the full Revit
operator/plugin slice passed (`337 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-after-next-human-resume-path-guard-20260514`
reported clean resume-script path validation and zero violations. Fresh hard
gate `live-north-star-completion-gate-after-next-human-resume-path-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

Final next-human restart-checklist path guard verification: after narrowing
the guard to stable/source checklist evidence, targeted path-drift coverage
passed (`3 passed`), the focused north-star/next-human/stable suite passed
(`84 passed`), the full Revit operator/plugin slice passed (`335 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-next-human-checklist-path-guard-final-20260514`
reported clean checklist path validation and zero violations. Fresh hard gate
`live-north-star-completion-gate-after-next-human-checklist-path-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The stable next-human-action restart checklist path is now guarded. The stable
scan and hard completion gate require
`human-restart-or-reload-revit.checklist_path` to equal
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` and require the
Markdown card to show that same `Checklist:` line; the run-specific checklist
is retained only as `source_checklist_path`. Drift raises
`next-human-restart-checklist-path-drift` or
`next-human-restart-checklist-markdown-drift` and routes to stable handoff
repair. Targeted path-drift tests passed (`3 passed`). Live stable scan
`live-north-star-stable-scan-after-next-human-checklist-path-guard-20260514`
reported clean checklist path validation and zero violations. Fresh hard gate
`live-north-star-completion-gate-after-next-human-checklist-path-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The next-human-action restart option now points humans at the stable current
restart checklist path. `human-restart-or-reload-revit.checklist_path` prefers
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`, while the
run-specific checklist from `bridge-restart-validation-plan` remains available
as `source_checklist_path` for traceability. Targeted coverage passed
(`1 passed`), the focused north-star/next-human/stable suite passed
(`82 passed`), the full Revit operator/plugin slice passed (`333 passed`),
and compileall passed. Live refresh
`live-north-star-watch-refresh-after-stable-checklist-path-20260514`
republished the current handoff with the stable checklist path; stable scan
`live-north-star-stable-scan-after-stable-checklist-path-20260514` stayed
clean, and hard gate
`live-north-star-completion-gate-after-stable-checklist-path-20260514`
remained blocked with four blocked gates, 17 unsatisfied requirements, and zero
safety guard violations. The goal remains active, not complete.

The stable next-human-action post-human resume command is now guarded. The
stable scan and hard completion gate require the
`human-restart-or-reload-revit` resume command to be the read-only
`north-star-resume-check` path, require required context flags such as
`--sheet-number` and `--revit-version`, reject execution flags, approval-token
flags, approval phrases, and direct UI/write commands, verify the PowerShell
line mirrors the command arguments, and require the Markdown card to show the
same `Resume command:` line. Drift raises `next-human-resume-command-*`
violations and routes to `repair-stable-handoff-artifacts`. Targeted
resume-command coverage passed (`2 passed`), the focused
north-star/next-human/stable suite passed (`88 passed`), the full Revit
operator/plugin slice passed (`339 passed`), and compileall passed. The first
live scan correctly exposed expired preflight/stale approval credentials; the
read-only refresh
`live-north-star-watch-refresh-after-next-human-resume-command-guard-20260514`
republished the handoff without granting completion. Final stable scan
`live-north-star-stable-scan-after-next-human-resume-command-guard-final-20260514`
reported clean resume-command validation and zero violations. Fresh hard gate
`live-north-star-completion-gate-after-next-human-resume-command-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The post-human resume command now also has expected-context validation. The
stable scan and hard completion gate compare the resume command against the
latest `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.expected_context`; when title,
path, view name, or view type expectations are present, the command must carry
the matching `--expected-title-contains`, `--expected-path-contains`,
`--expected-view-name`, and `--expected-view-type` arguments. Missing or
mismatched context raises
`next-human-resume-command-required-option-missing` or
`next-human-resume-command-context-mismatch` and routes to
`repair-stable-handoff-artifacts`. Targeted context coverage passed
(`4 passed`), the focused north-star/next-human/stable suite passed
(`90 passed`), the full Revit operator/plugin slice passed (`341 passed`, with
one existing pywinauto deprecation warning), and compileall passed. Live stable
scan
`live-north-star-stable-scan-after-next-human-resume-command-context-guard-20260514`
reported clean resume-command context validation and zero violations. Fresh
hard gate
`live-north-star-completion-gate-after-next-human-resume-command-context-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The hard human/real-condition boundary is now mirrored and guarded in the
human-facing handoff artifacts. When the completion gate reports
`blocked_waiting_for_human_or_real_condition: true`,
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` and
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` must both expose
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and
`blocked_waiting_for_human_or_real_condition: true` in JSON and Markdown. Drift
raises `human-real-boundary-*` violations and routes to
`repair-stable-handoff-artifacts`. The compact artifact summary used by
unblock-readiness now carries these completion-gate fields so the readiness
packet cannot silently default them to false. Targeted boundary coverage passed
(`3 passed`), the focused north-star/unblock/stable suite passed (`96 passed`),
the full Revit operator/plugin slice passed (`343 passed`), and compileall
passed. Live stable scan
`live-north-star-stable-scan-after-human-real-boundary-guard-final-20260514`
reported clean human/real-condition boundary validation and zero violations.
Fresh hard gate
`live-north-star-completion-gate-after-human-real-boundary-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations. The
goal remains active, not complete.

The human/real-condition boundary guard now covers the broader stable handoff
surface: `NORTH_STAR_HANDOFF_CURRENT.*`,
`NORTH_STAR_WAITING_STATE_CURRENT.*`,
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.*`,
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*`, and
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*`. The human gate packet now derives
`blocked_waiting_for_human_or_real_condition` when status payloads omit it and
renders that field in Markdown, so the supervised handoff cannot hide that
Hermes is waiting on a human or a real Revit condition. Targeted coverage
passed (`5 passed`), the focused north-star handoff/gate slice passed
(`99 passed`), the full Revit operator/plugin slice passed (`344 passed`), and
compileall passed. Live refresh
`live-north-star-watch-refresh-after-expanded-human-real-boundary-guard-20260514`
republished the stable handoff read-only. Live stable scan
`live-north-star-stable-scan-after-expanded-human-real-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and 5 checked boundary
artifacts. Fresh hard gate
`live-north-star-completion-gate-after-expanded-human-real-boundary-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_waiting_for_human_or_real_condition: true`,
and zero safety guard violations. The goal remains active, not complete.

The human-gate packet now has the same stable blocker-count contract as the
other current handoff artifacts. The generator publishes `generated_at_utc` and
`blocked_gate_count`; stable scan includes
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json` and flags non-empty stable artifacts
that omit either blocker count. Focused coverage passed (`4 passed`), then the
full Revit operator/plugin slice passed (`366 passed`). Live
`live-north-star-human-gate-packet-count-repair-20260514` produced matching
blocked gap/gate counts and no completion or execution authority. The first
scan under the stronger contract found the stale published human packet, and
read-only watch refresh
`live-north-star-watch-refresh-after-human-packet-count-contract-20260514`
republished the current handoff. Final stable scan
`live-north-star-stable-scan-after-human-packet-count-contract-refresh-20260514`
returned clean with zero stable metadata violations. Hard gate
`live-north-star-completion-gate-after-human-packet-count-contract-refresh-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The active goal remains open.

The human-gate packet status now distinguishes autonomous work from external
human/real-condition blockers. It reports `autonomous_progress_available` when
the status artifact still has a safe autonomous next step, and only reports
`blocked_human_or_real_condition` when the same fields show no autonomous path
and a human or real condition is required. Focused coverage passed
(`2 passed`), and the full Revit operator/plugin slice passed (`367 passed`).
Live `live-north-star-human-gate-status-guard-refresh-20260514` correctly
remained `blocked_human_or_real_condition` for the current sandbox because the
hard gate has no autonomous progress path. Stable scan
`live-north-star-stable-scan-after-human-gate-status-guard-20260514` was clean,
and hard gate
`live-north-star-completion-gate-after-human-gate-status-guard-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations.

The latest human-gate packet refresh remains handoff-only and does not satisfy
the north-star gate. `live-north-star-human-gate-packet-refresh-20260514b`
reported `blocked_human_or_real_condition`, four blocked gaps, no autonomous
progress, and no execution/update authority. Stable scan
`live-north-star-stable-scan-after-human-packet-refresh-20260514b` stayed clean
with zero violations, including zero stale approval violations and zero unblock
mirror drift. Hard gate
`live-north-star-completion-gate-after-human-packet-refresh-20260514b` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active until the human
restart/reload, approval, and real-condition gates have fresh evidence.

Direct current-handoff refresh now repairs the same stale unblock-readiness
condition that the watch path already handled. After publishing the stable
handoff, `north-star-current-handoff` refreshes
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` and then refreshes the hard completion
gate again. `north-star-unblock-readiness` no longer reports stale-preflight
alignment for its own two stable output files while rewriting them, while the
independent stable scan still flags those same stale files before self-refresh.
This closes the out-of-order approval-preflight/handoff gap observed during
live refreshes. Focused ordering coverage passed (`6 passed`), the full Revit
operator/plugin slice passed (`364 passed`), compileall passed, and
`git diff --check` passed with only LF-to-CRLF warnings on `.gitignore` and
`pyproject.toml`. Live
`live-north-star-current-handoff-patched-refresh-20260514` reported zero
handoff-guard violations from the refreshed unblock readiness and zero safety
guard violations from the final completion-gate refresh. Stable scan
`live-north-star-stable-scan-after-patched-handoff-20260514` reported
`status: clean`, `violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-patched-handoff-20260514` remains
blocked with `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, and
`blocked_gap_count: 4`. The goal remains active, not complete.

After the approval preflight expired, stable scan correctly blocked stale
approval-facing artifacts instead of treating them as usable. The read-only
watch refresh
`live-north-star-watch-refresh-after-expired-preflight-20260514` regenerated the
approval preflight and current handoff without save/sync/model actions.
Follow-up stable scan
`live-north-star-stable-scan-after-expired-preflight-refresh-20260514` reported
zero violations, zero preflight-alignment violations, zero stale approval
violations, and a clean read-only script guard. Fresh hard gate
`live-north-star-completion-gate-after-expired-preflight-refresh-20260514`
remains blocked with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and zero safety guard violations. The
goal remains active, not complete.

The latest blocked handoff packets were refreshed from the current hard gate
without executing Revit UI/model actions. Human gate packet
`live-north-star-human-gate-packet-final-blocked-refresh-20260514` remains
`blocked_human_or_real_condition` with four blocked gaps, no autonomous
progress, and no goal-update authority. Next human action
`live-north-star-next-human-action-final-blocked-refresh-20260514` lists the
three remaining allowed directions: human restart/reload, exact human approval
phrase, or waiting for a real recovery condition; it does not grant execution
or goal-update authority. Follow-up stable scan
`live-north-star-stable-scan-after-human-packets-refresh-20260514` is clean
with zero stale approval, preflight-alignment, human-gate, or completion-guard
violations. Fresh hard gate
`live-north-star-completion-gate-after-human-packets-refresh-20260514` remains
blocked with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and zero safety guard violations.
There is no current autonomous route to completion.

The add-in build/install side has been advanced as far as it can be without
restarting Revit. A user-local .NET 8 SDK was installed under
`%LOCALAPPDATA%\hermes\dotnet-sdk`, the current Revit operator add-in source was
built into `tools\revit_operator\addin\bin\Release\net8.0-windows-current`,
the DLL was signed with the Hermes local code-signing certificate, and the
Revit 2025 manifest now points to that fresh signed DLL. The verifier now
accepts the newest known local Hermes output path, so a fresh build can be
installed beside the locked DLL while Revit is still running. Focused
resolver/bridge tests passed (`6 passed`), the full Revit operator/plugin
slice passed (`366 passed`), and compileall passed. Live add-in security
preflight `live-addin-security-preflight-after-current-path-resolver-20260514`
is verified, and live bridge readiness
`live-bridge-readiness-after-current-path-resolver-20260514` now fails only
`loaded_build_current`; the manifest, signed assembly, and bridge connection
checks pass. Restart handoff
`live-bridge-restart-plan-after-current-dll-install-20260514` refreshed the
no-save checklist against this current DLL. Stable scan
`live-north-star-stable-scan-after-current-dll-install-20260514` is clean.
Fresh hard gate
`live-north-star-completion-gate-after-current-dll-install-20260514` remains
blocked with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The bridge restart gate now truly waits on
the human Revit restart/reload, not on a missing local build/install step.

The next-human restart option summary now carries the same read-only
post-human resume command as the full restart option. Stable scan verifies that
`option_summaries[].post_action_resume_command` and
`post_action_resume_powershell` mirror the option-level
`north-star-resume-check` command and do not contain execution flags, approval
tokens, direct UI commands, or write-oriented commands. Summary drift raises
`next-human-resume-command-summary-*` violations and routes to stable handoff
repair. Focused tests passed (`5 passed`). Live next-human refresh
`live-north-star-next-human-action-after-resume-summary-guard-20260514`
published the summary command, live stable scan
`live-north-star-stable-scan-after-resume-summary-guard-20260514` was clean,
and fresh hard gate
`live-north-star-completion-gate-after-resume-summary-guard-20260514` still
blocks completion with four live/real-condition gaps, 17 unsatisfied
requirements, and zero safety guard violations. The goal remains active, not
complete.

The boundary guard now also includes the durable blocked ledger. The ledger
already carried `autonomous_progress_available`,
`human_or_real_condition_required`, and
`blocked_waiting_for_human_or_real_condition` in JSON; its Markdown now renders
the same lines, and the stable scan treats
`NORTH_STAR_BLOCKED_LEDGER_CURRENT.*` as a checked human-facing boundary
artifact. Targeted blocked-ledger/boundary tests passed (`5 passed`), the
focused north-star handoff/gate slice passed (`102 passed`), the full Revit
operator/plugin slice passed (`345 passed`), and compileall passed. Live
refresh
`live-north-star-watch-refresh-after-blocked-ledger-boundary-guard-20260514`
republished the stable handoff read-only. Live stable scan
`live-north-star-stable-scan-after-blocked-ledger-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and 6 checked boundary
artifacts. Fresh hard gate
`live-north-star-completion-gate-after-blocked-ledger-boundary-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The hard human/real-condition boundary is now enforced on the status, audit,
and approval-plan stable artifacts as well. `NORTH_STAR_STATUS_CURRENT.*`,
`NORTH_STAR_AUDIT_CURRENT.*`, and `NORTH_STAR_APPROVAL_PLAN_CURRENT.*` now
publish `autonomous_progress_available`, `human_or_real_condition_required`,
and `blocked_waiting_for_human_or_real_condition` in JSON and Markdown, and
the stable scan treats drift in those artifacts as a boundary violation. This
prevents the compact status surfaces from making the active north-star goal
look complete or autonomously finishable when the authoritative completion
gate is blocked. Targeted boundary coverage passed (`7 passed`), the focused
north-star boundary/gate slice passed (`114 passed`), the full Revit
operator/plugin slice passed (`346 passed`), and compileall passed. Live
refresh
`live-north-star-watch-refresh-after-status-audit-plan-boundary-guard-20260514`
republished the stable handoff read-only. Live stable scan
`live-north-star-stable-scan-after-status-audit-plan-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and 9 checked boundary
artifacts. Fresh hard gate
`live-north-star-completion-gate-after-status-audit-plan-boundary-guard-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The bridge restart/no-save checklist now carries the unsigned add-in startup
preflight result directly in the human handoff. This matters because the next
real unblock path is a human restart/reload, and startup can be interrupted by
an add-in security prompt. The checklist now shows the verified manifest path,
expected DLL path, signature status, signer subject, blocked prompt buttons,
and the rule that Hermes must not click from the checklist; `Always Load`
still requires a separate exact approval token. Targeted restart/add-in tests
passed (`5 passed`), the full Revit operator/plugin slice passed (`346 passed`),
and compileall passed. Live `addin-security-preflight` verified the expected
Hermes add-in and valid local code-signing certificate. Live restart plan
`live-bridge-restart-plan-with-addin-preflight-20260514` wrote the updated
checklist, live watch refresh
`live-north-star-watch-refresh-after-restart-checklist-addin-preflight-20260514`
republished it to the stable current artifacts, and live stable scan
`live-north-star-stable-scan-after-restart-checklist-addin-preflight-20260514`
reported zero violations. Fresh hard gate
`live-north-star-completion-gate-after-restart-checklist-addin-preflight-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The restart/no-save checklist add-in preflight is now protected by the stable
artifact scan and by the hard completion gate. The scan compares the latest
`bridge_restart_validation_plan.json` `addin_security_preflight` payload with
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` and requires the
human-visible checklist to show the preflight section, verified add-in fields,
blocked prompt buttons, signature details, the `Always Load` approval rule, and
the warning that Hermes must not click from the checklist without a separate
exact token. Drift raises `restart-checklist-addin-preflight-*` violations and
routes to `repair-stable-handoff-artifacts`. Targeted coverage passed
(`9 passed`), the full Revit operator/plugin slice passed (`348 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-restart-checklist-addin-preflight-guard-20260514`
reported clean add-in preflight validation and zero violations. Fresh hard gate
`live-north-star-completion-gate-after-restart-checklist-addin-preflight-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The current human handoff was refreshed after the latest approval preflight.
The first stable scan after the standalone preflight refresh correctly found
`fresh-preflight-stale-handoff-artifact` violations because approval-facing
handoff files were older than `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.*`.
Read-only watch refresh
`live-north-star-watch-refresh-after-human-action-stale-handoff-20260514`
regenerated the preflight and current handoff as one supervised sequence,
observed Revit idle with no dialogs, and did not focus, click, type, invoke
UIA, restart, close, save, sync, reload, detach, upgrade, or modify the model.
Final stable scan
`live-north-star-stable-scan-after-human-action-handoff-refresh-final-20260514`
reported clean handoff validation, zero stale approval violations, and clean
restart checklist add-in preflight validation. Fresh hard gate
`live-north-star-completion-gate-after-human-action-handoff-refresh-final-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The follow-up read-only gate refresh after the latest correction did not change
the completion status. `live-north-star-resume-check-refresh-20260514b` again
reported `blocked_human_or_real_condition`; bridge validation still failed on
`loaded_build_current` and `bridge_readiness_ready`. The read-only watch refresh
`live-north-star-watch-refresh-after-resume-refresh-20260514b` republished the
current handoff and approval preflight, observed Revit idle with no visible
dialogs, and still found the bridge restart/reload gate blocked on the stale
loaded add-in build. Stable scan
`live-north-star-stable-scan-after-watch-refresh-20260514b` returned to clean
state with zero violations and zero unblock mirror drift. Hard gate
`live-north-star-completion-gate-after-watch-refresh-20260514b` still blocks
completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The active goal must remain open.

The pre-human resume check before restarting Revit also confirmed the goal is
not complete. Live task
`live-north-star-resume-check-before-human-restart-20260514` remained
`blocked_human_or_real_condition`; bridge validation failed on
`loaded_build_current` and `bridge_readiness_ready`, so the current signed
add-in build is installed but not yet loaded by the running Revit process. The
same read-only check surfaced stale approval-preflight drift after the prior
preflight expired, which temporarily made the nested stable-scan guard report
stale approval credential leaks. A read-only watch refresh,
`live-north-star-watch-refresh-after-stale-resume-check-20260514`, republished
the current handoff with a fresh approval preflight and took no UI/model action.
Follow-up stable scan
`live-north-star-stable-scan-after-stale-resume-refresh-20260514` returned to
zero violations, and hard gate
`live-north-star-completion-gate-after-stale-resume-refresh-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. This is the correct state: the north-star
goal remains active until the real human/restart and approval/recovery gates are
satisfied by fresh evidence.

The autonomous stop interlock is now enforced by stable scan and the hard
completion gate. When the hard gate is blocked on human approval, human action,
or a real Revit condition with no autonomous progress path,
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json.autonomous_stop` must be active,
must keep update-goal/execution authority false, must allow only observation and
read-only refresh command kinds, must carry no credential material, must mark
its nested refresh command read-only, and must mirror the hard gate's blocked
gap IDs. The stable scan also checks the corresponding Markdown lines and the
nested stop refresh command for forbidden execution/approval-token flags.
Focused guard coverage passed (`12 passed`), the full Revit operator/plugin
slice passed (`361 passed`), and compileall passed. Live
`live-north-star-unblock-readiness-after-autonomous-stop-guard-20260514`
regenerated the current unblock packet with `autonomous_stop.active: true` and
`safe_refresh_read_only: true`. Read-only watch refresh
`live-north-star-watch-refresh-after-autonomous-stop-guard-20260514` repaired
expired preflight handoff state without executing UI/model actions. Final
stable scan
`live-north-star-stable-scan-final-after-gate-autonomous-stop-guard-20260514`
reported zero violations, including
`unblock_autonomous_stop_violation_count: 0` and
`unblock_refresh_command_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-autonomous-stop-guard-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The unblock-readiness handoff now has an explicit autonomous stop interlock.
When the hard completion gate is blocked on human approval, human action, or a
real Revit condition and no autonomous progress path remains,
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json.autonomous_stop` becomes active. It
allows only observation and read-only refresh command kinds, keeps
`may_call_update_goal`, `audit_completion_authorized`, and
`may_execute_from_this_result` false, records that no credential material is
included, and says not to execute UI/model actions, restart/reload Revit,
answer prompts, call bridge action endpoints, or call `update_goal` from this
packet. Focused unblock-readiness coverage passed (`8 passed`), the full
Revit operator/plugin slice passed (`359 passed`), and compileall passed. Live
`live-north-star-unblock-readiness-after-autonomous-stop-20260514` wrote a
current unblock packet with `autonomous_stop.active: true`, four blocked gate
IDs, and only `observation` / `read_only_refresh` as allowed command kinds.
Live stable scan
`live-north-star-stable-scan-final-after-autonomous-stop-20260514` reported
zero violations. Fresh hard gate
`live-north-star-completion-gate-after-autonomous-stop-20260514` still blocks
completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The goal remains active, not complete.

The stable current metadata guard is now part of both stable-scan and hard-gate
safety. The guard checks the durable current completion gate, blocked ledger,
handoff, next-human-action, waiting-state, and unblock-readiness JSON artifacts
for `generated_at_utc`, `read_only: true`, and
`may_execute_from_this_result: false`; metadata drift routes to
`repair-stable-handoff-artifacts`. Focused metadata coverage passed
(`18 passed`), the full Revit operator/plugin slice passed (`359 passed`), and
compileall passed. Live watch refresh
`live-north-star-watch-refresh-before-stable-current-metadata-20260514`
republished the current handoff after refreshing approval preflight, observed
Revit idle with no dialogs, and kept completion blocked. Final stable scan
`live-north-star-stable-scan-final-after-stable-current-metadata-20260514`
reported zero violations and `stable_current_metadata_violation_count: 0`.
Fresh hard gate
`live-north-star-completion-gate-final-after-stable-current-metadata-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The stable artifact scan now turns its approval-preflight refresh advisory into
a self-contained operator command block. When the preflight is stale or nearing
expiry, `preflight_refresh_advisory` includes the exact read-only
`north-star-watch --refresh-approval-preflight --publish-current-handoff
--checks 1 --poll 0` command, the PowerShell form, the expected Revit context
derived from `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`, and the follow-up
`north-star-stable-artifact-scan` / `north-star-completion-gate` checks. The
Markdown mirrors those fields and continues to omit `--execute`,
`--approval-token`, generated `APPROVE:` tokens, and exact `I approve` phrase
material. Focused tests passed (`2 passed`). Live stable scan
`live-north-star-stable-scan-after-refresh-advisory-markdown-20260514` was
clean, and fresh hard gate
`live-north-star-completion-gate-after-refresh-advisory-markdown-20260514`
still blocks completion with the same four live/real-condition gaps, 17
unsatisfied requirements, and zero safety guard violations. The goal remains
active, not complete.

The current handoff now has a next-human option mirror guard. Stable scan and
the hard completion gate compare
`NORTH_STAR_HANDOFF_CURRENT.json.next_human_action` against
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` for option count, option IDs, and
redacted option summaries, and they reject approval-token or exact approval
phrase material in that handoff summary layer. Drift raises
`handoff-next-human-options-mirror-drift`; credential material raises
`handoff-next-human-options-credential-leak`. Focused mirror tests passed
(`3 passed`), the full Revit operator/plugin slice passed (`355 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-handoff-next-human-options-mirror-guard-20260514`
reported a clean handoff mirror with zero mismatches and zero credential leaks.
Fresh hard gate
`live-north-star-completion-gate-after-handoff-next-human-options-mirror-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The stable scan and hard completion gate now enforce an unblock-readiness
next-human option mirror. `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` must
match `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` for option count, option IDs,
and redacted option summaries, and that summary layer must not expose approval
tokens or exact approval phrases. Drift raises
`unblock-readiness-next-human-options-mirror-drift`; credential material raises
`unblock-readiness-next-human-options-credential-leak`; both route to stable
handoff repair rather than execution authority. Focused stable-scan/unblock
tests passed (`4 passed`), the full Revit operator/plugin slice passed
(`354 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-unblock-next-human-options-mirror-guard-20260514`
reported a clean mirror with zero mismatches and zero credential leaks. Fresh
hard gate
`live-north-star-completion-gate-after-unblock-next-human-options-mirror-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The unblock-readiness packet now mirrors the next-human option summaries
directly. `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` and Markdown expose
`next_human_option_count`, `next_human_option_ids`, and redacted
`next_human_option_summaries`, so the remaining human/recovery unblock paths
are visible from the single diagnostic packet without exposing exact approval
phrases. Focused unblock-readiness tests passed (`4 passed`), the full Revit
operator/plugin slice passed (`353 passed`), and compileall passed. A live
approval preflight expired during this refresh, and the stale credential guard
correctly raised violations until
`live-north-star-watch-refresh-after-unblock-option-summary-stale-preflight-20260514`
regenerated the approval-facing handoff read-only. Final live unblock-readiness
`live-north-star-unblock-readiness-option-summary-clean-mirror-20260514`
reported a clean stable-scan mirror, a clean stable handoff guard, and three
next-human option summaries. Final stable scan
`live-north-star-stable-scan-after-unblock-option-summary-clean-mirror-20260514`
reported zero violations, and fresh hard gate
`live-north-star-completion-gate-after-unblock-option-summary-clean-mirror-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The direct next-human-action handoff now exposes the same compact option
summary fields that downstream completion-gate and current-handoff summaries
already derive. `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` includes
`option_count`, `option_ids`, and redacted `option_summaries`, so a quick read
of that single stable artifact identifies the available human restart/reload,
human approval, and real-condition recovery paths without needing to recompute
the summary from `next_human_options`. Exact approval phrases are intentionally
omitted from the summary layer. Focused next-human tests passed (`3 passed`),
the full Revit operator/plugin slice passed (`353 passed`), and compileall
passed. Live `live-north-star-next-human-action-option-summary-20260514`
regenerated the stable card with three option summaries. Live stable scan
`live-north-star-stable-scan-after-next-human-option-summary-20260514`
reported zero violations and zero approval phrase metadata violations. Fresh
hard gate
`live-north-star-completion-gate-after-next-human-option-summary-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The next-human handoff now protects its post-human resume command from missing
expected Revit context. When `north-star-next-human-action` is run without
explicit title/path/view expectations, it derives those fields from the latest
approval-preflight artifact before writing
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*`. This repaired the live drift where a
context-free read-only handoff caused four hard-gate safety violations for
missing expected context options. Focused next-human/resume-command tests
passed (`6 passed`), the full Revit operator/plugin slice passed
(`353 passed`), and compileall passed. Live repair
`live-north-star-next-human-action-derived-context-repair-20260514` regenerated
the current next-human artifact with inherited expected title/path/view fields.
Live stable scan
`live-north-star-stable-scan-after-next-human-derived-context-repair-20260514`
reported zero violations, zero next-human resume-command violations, zero
missing context options, and zero context mismatches. Live resume check
`live-north-star-resume-check-after-next-human-derived-context-repair-20260514`
reported zero safety guard violations while bridge validation still failed on
`loaded_build_current` and `bridge_readiness_ready`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-derived-context-repair-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The approval phrase provenance guard now covers both structured metadata and
stable markdown handoffs. Any stable artifact that exposes an exact approval
phrase must carry provenance language making clear that generated artifacts are
not approval provenance and are not execution authority. The generator now
threads that warning through waiting-state, approval-item, blocked-ledger, and
current-handoff output, and the scanner reports
`approval-phrase-provenance-note-missing` when it is absent. Focused
approval/handoff tests passed (`12 passed`), the full Revit operator/plugin
slice passed (`352 passed`), and compileall passed. Live refresh
`live-north-star-watch-refresh-after-phrase-provenance-metadata-guard-20260514b`
republished the current handoff read-only and reported zero safety guard
violations. Live stable scan
`live-north-star-stable-scan-after-phrase-provenance-metadata-guard-20260514b`
reported zero violations, zero approval phrase metadata violations, and a clean
read-only script guard. Fresh hard gate
`live-north-star-completion-gate-after-phrase-provenance-metadata-guard-20260514b`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The supervised read-only handoff script no longer contains the exact human
approval phrase or approval token it asks the operator to supply. The script
now carries only the runtime placeholder and relies on
`north-star-approval-phrase-verify` plus the read-only
`north-star-approved-execution-preview` command to validate any human-supplied
phrase against current waiting-state artifacts. The stable read-only script
guard now treats `APPROVE:*` token literals and `I approve` phrase literals as
forbidden material in stable scripts, so future drift becomes a stable-scan and
hard-gate safety violation instead of a hidden approval-boundary weakness.
Focused handoff/leak coverage passed (`9 passed`), the full Revit
operator/plugin slice passed (`350 passed`), and compileall passed. Live watch
refresh `live-north-star-watch-refresh-after-supervised-script-token-removal-20260514`
republished current handoff artifacts read-only, observed Revit idle with no
dialogs, and produced no approval literal leaks in the supervised script. Live
stable scan
`live-north-star-stable-scan-after-supervised-script-token-removal-20260514`
reported zero violations and `forbidden_match_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-supervised-script-token-removal-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

Approval phrase intake now has an explicit provenance guard. Phrase
verification publishes `phrase_source`, `phrase_source_required`,
`phrase_source_attested`, and `artifact_phrase_is_not_approval_provenance`.
Matching the generated waiting-state text and approval token is no longer
enough for preview readiness unless the command also carries
`--phrase-source human_active_conversation`. The approved execution preview
therefore withholds the command preview when a phrase is copied from artifacts
without human-source attestation, while still remaining read-only even when the
source is attested. The supervised read-only script was regenerated so its
runtime placeholder is passed with the phrase-source guard and still contains
no exact phrase or token. Focused provenance coverage passed (`19 passed` and
then `14 passed` for the narrowed repair set), the full Revit operator/plugin
slice passed (`351 passed`), and compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-phrase-source-guard-20260514` republished
current handoff artifacts read-only, and live stable scan
`live-north-star-stable-scan-after-phrase-source-guard-20260514` reported zero
violations, zero stale approval violations, and a clean script guard. Fresh hard
gate `live-north-star-completion-gate-after-phrase-source-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The phrase-source guard is now enforced by stable-scan, not just by the current
generated script. `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` must carry
both `--phrase-source` and `human_active_conversation`; otherwise stable scan
raises `stable-readonly-script-required-term-missing` and the hard gate treats
the handoff as unsafe drift. Focused stable-script guard tests passed
(`10 passed`), the full Revit operator/plugin slice passed (`352 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-phrase-source-stable-guard-20260514`
reported a clean script guard with zero missing required terms and zero
forbidden matches. Fresh hard gate
`live-north-star-completion-gate-after-phrase-source-stable-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The post-human resume bridge summary is now enforced by stable-scan and the
hard completion gate. `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` must
include the bridge validation extraction and `BRIDGE VALIDATION` failed-checks
status output; drift raises `stable-readonly-script-required-term-missing` and
routes to `repair-stable-handoff-artifacts`, not to execution authority repair.
Targeted guard/routing coverage passed (`5 passed`), the full Revit
operator/plugin slice passed (`349 passed`), and compileall passed. Live watch
refresh `live-north-star-watch-refresh-after-resume-bridge-summary-guard-20260514`
republished current handoff artifacts read-only, observed Revit idle with no
dialogs, and kept the bridge restart gate blocked on `loaded_build_current`.
Live stable scan
`live-north-star-stable-scan-after-resume-bridge-summary-guard-20260514`
reported zero violations, clean read-only script guard status, and
`missing_required_term_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-resume-bridge-summary-guard-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The post-human resume script now exposes bridge validation status directly in
the operator-facing console output. After `north-star-resume-check` JSON is
parsed, `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` prints bridge
validation status, `validation_passed`, and failed bridge checks before the
completion-gate warning. This makes the safe restart/reload handoff more
auditable without adding execution authority or any UI/model action. Targeted
resume/handoff tests passed (`7 passed`), the full Revit operator/plugin slice
passed (`348 passed`), and compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-resume-script-bridge-summary-20260514`
regenerated current handoff artifacts, observed Revit idle with no dialogs, and
kept the bridge restart gate blocked on `loaded_build_current`. Stable script
inspection confirmed the bridge summary lines in
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`. Live stable scan
`live-north-star-stable-scan-after-resume-script-bridge-summary-20260514`
reported zero violations and a clean read-only script guard. Fresh hard gate
`live-north-star-completion-gate-after-resume-script-bridge-summary-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The approval preflight command now carries its own read-only handoff-refresh
hint. `north-star-approval-preflight` writes
`post_preflight_handoff_refresh` with the exact
`north-star-watch --refresh-approval-preflight --publish-current-handoff`
command, marked read-only with no execution command and no approval token. This
directly addresses the stale-handoff condition found after standalone
preflight refreshes by telling the operator how to republish approval-facing
current artifacts before requesting or using a human approval phrase. Targeted
coverage passed (`4 passed`), the full Revit operator/plugin slice passed
(`348 passed`), and compileall passed. Live
`live-north-star-approval-preflight-with-refresh-hint-20260514` exposed the
refresh command, withheld all approval credentials, and reported zero unsafe
preflight items. The hinted read-only watch refresh
`live-north-star-watch-refresh-after-approval-preflight-refresh-hint-20260514`
observed Revit idle with no dialogs and regenerated the current handoff. Final
stable scan
`live-north-star-stable-scan-after-approval-preflight-refresh-hint-20260514`
reported zero violations and zero stale approval leaks. Fresh hard gate
`live-north-star-completion-gate-after-approval-preflight-refresh-hint-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The bridge restart/no-save checklist now carries the same hard completion-gate
rule as the resume and supervised-check scripts. It explicitly requires a fresh
`north-star-completion-gate` or `north-star-resume-check.completion_gate` with
`completion_allowed: true`, `may_call_update_goal: true`, and
`audit_completion_authorized: true`, and states that status/audit summaries are
diagnostic only. Stable scan enforces this via
`restart_no_save_checklist_completion_guard`; drift raises
`restart-checklist-completion-guard-*` and routes to
`repair-stable-handoff-artifacts`. Focused guard coverage passed (`7 passed`).
Live read-only restart plan `live-bridge-restart-plan-completion-guard-20260514`
refreshed the checklist and still showed `human_restart_required` because the
running Revit session has not reloaded the current bridge. Live watch refresh
`live-north-star-watch-after-checklist-guard-20260514` republished current
handoff artifacts. Stable scan
`live-north-star-stable-scan-after-checklist-guard-20260514` reported
`status: clean`, `violation_count: 0`, and completion-guard checklist drift
count zero. Fresh hard gate
`live-north-star-completion-gate-after-checklist-guard-20260514` remains
blocked with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

The current handoff now exposes top-level next-action summaries and redacts
stale approval credentials from stable artifacts. `NORTH_STAR_HANDOFF_CURRENT`
mirrors the compact next human action, restart/reload, approval, required real
condition, and post-human resume command/script summaries so an operator can
see the real blockers without relying on nested packet internals. When the
latest approval preflight is stale, stable approval-facing artifacts now
withhold approval phrases, tokens, verify commands, and execute flags; stale
command fragments are not preserved in safe handoff files. The unavailable
fallback supervised read-only script includes the required audit guard terms
but still provides no execution authority. Focused coverage passed (`2
passed`), the full Revit operator/plugin slice passed (`367 passed`), and
compileall passed. Live current-handoff refresh
`live-north-star-current-handoff-stale-approval-redaction-repair-20260514`
regenerated current files and kept the goal blocked because the approval
preflight was stale. Stable scan
`live-north-star-stable-scan-after-stale-approval-redaction-repair-20260514`
reported zero violations, zero stale approval leaks, zero approval phrase
metadata violations, and a clean supervised read-only script guard. Fresh hard
gate `live-north-star-completion-gate-after-stale-approval-redaction-repair-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

On continuation, the safe autonomous path was limited to read-only refresh and
verification. Watch refresh
`live-north-star-watch-refresh-current-handoff-continue-20260514` observed the
running Revit 2025 session idle with no dialogs, detected the bridge restart
gate still blocked on `loaded_build_current`, refreshed approval preflight, and
republished stable current handoff artifacts without focusing, clicking,
typing, invoking UIA, restarting, saving, syncing, reloading, detaching,
upgrading, closing, or modifying Revit. Stable scan
`live-north-star-stable-scan-after-watch-refresh-continue-20260514` reported
zero violations, zero stale approval leaks, clean approval phrase metadata, and
clean read-only script guards. Hard gate
`live-north-star-completion-gate-after-watch-refresh-continue-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

Fresh guarded UI workflow validation was rerun without execution authority.
Static matrix `live-ui-workflow-matrix-continuation-20260514` validated 10
recipes and 38 steps with zero blocked or failed recipe cases; seven steps
remain approval-gated and one remains a manual placeholder. Smoke matrix
`live-ui-workflow-smoke-matrix-continuation-20260514` ran 19 allowed
observation/planning prefix steps across those recipes, observed Revit 2025
idle with no dialogs, and stopped before any approval-gated or non-smoke-safe
step. This improved live evidence for reusable UI workflow planning, but it
does not satisfy the live execution gates because no approved click, UIA,
ribbon, context-menu, restart, reload, save, sync, detach, upgrade, close, or
model-modifying action was executed. Hard gate
`live-north-star-completion-gate-after-ui-smoke-continuation-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

Workflow memory and replay validation were refreshed as another safe
autonomous workstream. `live-workflow-library-continuation-20260514` found two
valid recorded templates. `live-plan-workflow-qa-continuation-20260514`
planned the recorded QA replay and kept focus steps approval-gated.
Parameterized planning with target `OK`
(`live-plan-workflow-parameterized-safe-continuation-20260514e`) remained
approval-required, while target `Save`
(`live-plan-workflow-parameterized-blocked-continuation-20260514e`) was
blocked. Fresh workflow approval plans regenerated approval requirements from
current payload classification, did not reuse stale approval tokens, and did
not find stored approval tokens in templates; the blocked `Save` override had
no execute command. Dry-run replays for the QA workflow and both parameterized
overrides performed fresh Revit observation and state-gate checks, executed
zero steps, and stopped the `Save` override as blocked; its recovery snapshot
showed idle state and therefore did not satisfy the real recovery-drill gate.
Hard gate
`live-north-star-completion-gate-after-workflow-memory-continuation-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. The goal remains active, not complete.

Recovery recommendation drills were refreshed without inducing or fabricating a
live failure state. `live-recovery-drill-matrix-continuation-20260514`
validated five synthetic scenarios and confirmed conservative outcomes for
high-risk modal upgrade, busy, idle, not-running, and unknown states. The matrix
produced no automatic action for the high-risk upgrade prompt and remained
read-only, so it improves recovery policy evidence but cannot clear
`live_recovery_drills`, which requires a real stuck, frozen, modal, busy, or
unknown Revit condition. Hard gate
`live-north-star-completion-gate-after-recovery-matrix-continuation-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-recovery-matrix-continuation-20260514`
reported zero stable-artifact violations and clean read-only script guards. The
goal remains active, not complete.

UIA, ribbon, and context method policy evidence was refreshed as a read-only
workstream. `live-uia-method-matrix-continuation-20260514` validated 21 cases
across 10 UIA methods; 11 cases require approval, 10 are blocked, none were
executed, and no live UI was touched. `live-ribbon-action-matrix-continuation-20260514`
validated 24 static ribbon action cases; 20 are approval-gated, seven are
blocked, and no ribbon controls were located, focused, clicked, or invoked.
`live-context-menu-action-matrix-continuation-20260514` validated three
context-menu descriptors and four menu item cases; two descriptors are
approval-gated, one is blocked, and no context menu was opened or selected.
The follow-up coverage audit
`live-ui-execution-coverage-audit-after-method-matrices-continuation-20260514`
still reports `status: insufficient_evidence` and `target_met: false`: the
only covered live surfaces are `focus`, `escape-key`, and `dialog-click`.
`type-text`, `uia-invoke`, `visual-click`, `ribbon-action`,
`context-menu-action`, `context-menu-item`, and `approved-ui-workflow-step`
remain missing. Hard gate
`live-north-star-completion-gate-after-method-matrices-continuation-20260514`
still blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and zero safety guard violations.
Stable scan
`live-north-star-stable-scan-after-method-matrices-continuation-20260514`
reported zero stable-artifact violations, zero stale approval leaks, clean
approval phrase metadata, and clean read-only script guards. The remaining
blocked gaps are `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the goal
remains active, not complete.

Resume readiness confirmed there is no further autonomous safe progress path.
`live-north-star-unblock-readiness-resume-20260514` returned blocked with
`autonomous_progress_available: false` and allowed only observation/read-only
refresh. The permitted watch refresh
`live-north-star-watch-refresh-after-readiness-resume-20260514` observed one
idle Revit 2025 cycle with no dialogs, the copied detached structural model on
`STARTING VIEW`, a refreshed approval preflight, and republished stable handoff
artifacts. It preserved the bridge restart/reload blocker because
`loaded_build_current` still fails. Hard gate
`live-north-star-completion-gate-after-readiness-watch-resume-20260514` still
blocks completion with four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and zero safety guard violations.
Stable scan
`live-north-star-stable-scan-after-readiness-watch-resume-20260514` reported
zero stable-artifact violations, zero stale approval leaks, clean approval
phrase metadata, and clean read-only script guards. The goal remains active,
not complete.

The latest prompt-to-artifact audit rechecked the original objective against
current artifacts. `live-north-star-audit-after-readiness-resume-20260514`
found all named documents and prototype source paths present and marked the
implementation package complete, but it still returned `status: not_complete`
with `completion_allowed: false`, `may_call_update_goal: false`, and
`audit_completion_authorized: false`. The paired blocked ledger
`live-north-star-blocked-ledger-after-readiness-resume-20260514` reported four
blocked gaps and no autonomous progress path. The remaining gaps require human
or real-condition evidence: no-save bridge restart/reload validation, approved
live UI workflow execution, recovery evidence from an actual stuck/modal/busy
state, and approved live UIA/ribbon/context-menu execution.

The human handoff artifacts were refreshed and the stable artifact guard was
repaired. `live-north-star-human-gate-packet-after-audit-resume-20260514`
created a fresh read-only human gate packet, and
`live-north-star-next-human-action-after-audit-resume-20260514` created a
three-option next-action card. Republish
`live-north-star-current-handoff-after-human-packet-resume-20260514` surfaced a
stable blocker-ID mismatch, which the hard gate correctly treated as a safety
guard violation. The repair sequence reran current handoff publication,
confirmed clean stable artifacts with
`live-north-star-stable-scan-after-human-packet-gate-resume-20260514`, and
reran the hard gate as
`live-north-star-completion-gate-after-human-packet-repair-resume-20260514`.
The final gate has zero safety guard violations but still blocks completion
with four blocked gaps, four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and no autonomous progress path.

Focused safety regression tests were rerun for the same guard family. The
initial pytest run failed before collection because the default temp base under
`AppData\Local\Temp` was inaccessible. Rerunning serially with a
workspace-local `--basetemp` selected 12 tests and all passed. The selected
tests covered blocker-ID mismatch detection, stable handoff repair routing,
execution-authority guard coverage, and next-human-action authority behavior.
This confirms the repair path is covered by tests, but it is not completion
evidence for the live human/real-condition gates.

The bridge restart blocker was refreshed with current read-only bridge
evidence. `live-bridge-status-current-blocker-20260514` found reachable bridge
files and a current add-in heartbeat, while
`live-verify-bridge-build-current-blocker-20260514` remained
`stale_or_unverified` because current bridge build metadata is missing from the
loaded add-in status. `live-bridge-readiness-current-blocker-20260514` remained
`not_ready` on `loaded_build_current`. The refreshed no-save checklist from
`live-bridge-restart-validation-plan-current-blocker-20260514` confirmed the
human restart/reload path is still required and that the copied detached model
is dirty, so Hermes must not save, sync, close, restart, reload, or answer
save/add-in prompts on its own.

The bridge evidence refresh exposed a sequencing issue in the audit workflow:
handoff, stable scan, and hard gate were first run in parallel, which produced
a transient stable blocker-ID mismatch. The same operations were then rerun
sequentially. The final sequence ended with clean stable artifacts and hard
gate `live-north-star-completion-gate-final-after-sequential-bridge-repair-20260514`
showing zero safety guard violations. The hard gate still blocks completion
with four blocked gaps, four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and no autonomous progress path.

A fresh live recovery snapshot checked whether the recovery gate had become
satisfiable. `live-recovery-snapshot-current-condition-20260514` captured
screenshot and UI tree evidence and showed Revit 2025 idle, not hung, and with
zero dialogs. The snapshot does not qualify as a live recovery drill, so the
`live_recovery_drills` blocker remains. The following hard gate surfaced stale
approval credentials because the latest approval preflight had expired. A
read-only watch refresh
`live-north-star-watch-refresh-after-stale-approval-from-recovery-snapshot-20260514`
refreshed approval preflight and current handoff artifacts. Stable scan
`live-north-star-stable-scan-after-stale-approval-refresh-20260514` then
returned clean with zero stale approval violations, and hard gate
`live-north-star-completion-gate-after-stale-approval-refresh-20260514`
returned zero safety guard violations. Completion remains blocked by the same
four human/real-condition gaps.

The runbook now records the artifact sequencing requirement that emerged from
the live repair work. `REVIT_OPERATOR_RUNBOOK.md` instructs future operators to
run current handoff, stable scan, hard gate, final stable scan, and final hard
gate sequentially, never in parallel, because the stable scan compares current
handoff files against the current hard gate. This is process hardening only; it
does not satisfy the remaining human/real-condition gates. The new focused
test `test_revit_operator_runbook_requires_sequential_north_star_artifact_refresh`
guards that runbook procedure; after a whitespace-normalization fix, it passed
as a single-test slice.

The procedure is now backed by a first-class read-only command:
`north-star-refresh-sequence`. It executes the dependent current handoff,
stable scan, hard gate, final stable scan, and final hard gate in that exact
order, with separate child task journals and a parent summary that treats only
the final hard gate as completion authority. This prevents another parallel
refresh mismatch but does not satisfy the remaining human/real-condition gates.
The full Revit operator test module passed after the change (`364 passed`) with
only the existing `.pytest_cache` permission warning. A real CLI smoke run of
`north-star-refresh-sequence` returned five ordered steps and remained blocked
with no completion authority.

The latest authoritative live sequence is
`live-north-star-refresh-sequence-correct-sandbox-after-repair-20260514` in
`live_readonly_bridge_20260512`. It ran the five dependent steps in order and
ended with `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, zero safety guard violations, no autonomous progress,
and a human/real-condition requirement.

After regenerating the next-human-action packet, the latest hard gate
`live-north-star-refresh-sequence-after-next-human-action-20260514` still
reports no completion authority: four blocked gaps, four blocked gates, 17
unsatisfied requirements, zero safety guard violations, no autonomous progress,
and `human_or_real_condition_required: true`.

The post-human resume path is now harder to misuse. The stable resume script
runs `north-star-resume-check` and then `north-star-refresh-sequence`, preserving
the hard completion rule after a human restart/reload or approval checkpoint.
Focused script tests and the full Revit operator module passed, and live task
`live-north-star-refresh-sequence-after-posthuman-script-hardening-20260514`
confirmed the regenerated stable script includes the sequential refresh while
the hard gate remains blocked with zero safety guard violations.

The human handoff now has a sanitized brief. `north-star-human-unblock-brief`
writes `NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json` / `.md` with no exact
approval phrases, no approval tokens, and no execution commands. Live task
`live-human-unblock-brief-20260514` verified the redaction, and follow-up hard
gate `live-north-star-refresh-sequence-after-human-unblock-brief-20260514`
remains blocked only on the four external gates with zero safety guard
violations and no autonomous progress.

The latest completion audit snapshot is explicit: audit task
`live-north-star-completion-audit-status-20260514` reports the implementation
package complete but the north star incomplete, with blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. Hard gate
`live-hard-gate-completion-audit-status-20260514` refuses completion with
`completion_allowed: false`, `may_call_update_goal: false`, and
`audit_completion_authorized: false`; stable scan
`live-stable-scan-completion-audit-status-20260514` is clean with zero safety
or credential violations.

The final verification pass also covered plugin exposure and syntax:
`tests/plugins/test_revit_operator_plugin.py` passed (`6 passed`) and
`python -m compileall tools/revit_operator plugins/revit-operator` completed.

A short read-only watch later refreshed approval preflight and found the new
sanitized human-unblock brief stale relative to that preflight. The current
handoff publisher now regenerates `NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.*`
as part of the handoff. Live sequence
`live-north-star-refresh-sequence-after-handoff-brief-repair-20260514` restored
zero safety guard violations and remains blocked only on the four external
gates.

`NORTH_STAR_HANDOFF_CURRENT.md` now also points directly to the sanitized human
unblock brief. Live task
`live-north-star-refresh-sequence-after-handoff-markdown-brief-20260514`
confirmed the current handoff has the Human Unblock Brief section and still
ends with zero safety guard violations and no completion authority.

The sanitized brief now includes a machine-readable stop reason:
`human_or_real_condition_required_no_autonomous_progress`. Live task
`live-north-star-refresh-sequence-after-stop-reason-20260514` confirmed this
field is present while the hard gate remains blocked with zero safety guard
violations. Compileall over `tools/revit_operator` and `plugins/revit-operator`
passed after the change.

The stop condition is now a first-class stable artifact. The new read-only
`north-star-agent-stop-status` command writes
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` / `.md`, and the current handoff
regenerates and links it. Live sequence
`live-north-star-refresh-sequence-after-agent-stop-status-20260514` ended with
clean stable artifacts and the stop-status artifact reporting
`stop_for_human_or_real_condition`, `should_stop_agent: true`, no execution
authority, and a recommendation to wait for a human or real Revit condition.
The final hard gate still blocks completion with four blocked gaps, 17
unsatisfied requirements, no autonomous progress, zero safety guard violations,
and no permission to call `update_goal`.

The restart/no-save checklist freshness check is now part of the stable handoff
safety surface. When bridge restart validation still requires a human
restart/reload, the stable scan compares the latest bridge restart validation
plan, the plan's source no-save checklist, the stable next-human-action card,
and `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`. Stale or missing
checklist mirrors raise restart-checklist freshness safety violations and route
to stable handoff repair rather than execution authority. Focused freshness and
routing tests passed, the full Revit operator module passed, the plugin slice
passed, and compileall completed. Live refresh
`live-watch-refresh-after-restart-checklist-freshness-guard-20260514` observed
Revit 2025 idle with no dialogs and republished the current handoff read-only;
stable scan
`live-stable-scan-after-refresh-restart-checklist-freshness-guard-20260514`
was clean with zero stale approval or checklist freshness violations. Hard gate
`live-completion-gate-after-refresh-restart-checklist-freshness-guard-20260514`
still blocks completion with four blocked gaps, 17 unsatisfied requirements,
zero safety guard violations, and no completion authority.

The completion audit JSON now exposes explicit count fields instead of making
operators infer them from checklist arrays: `remaining_gap_count`,
`unsatisfied_count`, `unverified_or_blocked_requirement_count`, and prompt
checklist total/satisfied/unsatisfied counts. Focused audit-count coverage
passed. Live refresh
`live-north-star-refresh-sequence-after-audit-counts-20260514` republished
stable artifacts showing four remaining gaps and 17 unsatisfied checklist items
out of 159 total. The same hard gate still blocks completion with zero safety
guard violations and no autonomous progress.

The agent stop-status artifact now includes the credential-free human unblock
paths and sanitized option summaries that a future Hermes run needs to stop
cleanly: stable human-unblock brief, bridge restart/no-save checklist, and
post-human resume script paths. Focused stop-status tests passed, and live
refresh `live-north-star-refresh-sequence-after-stop-paths-20260514`
confirmed the stop artifact has three sanitized options, no approval-token or
exact-phrase material, and direct handoff paths while the hard gate still blocks
completion.

The Hermes plugin wrapper is now stricter about sandbox boundaries. The
`revit_operator` tool schema does not advertise the test-only
outside-safe-root override, and direct structured-arg or raw-argv attempts to
use that override fail closed unless a local test environment flag is set.
Focused plugin coverage passed with eight tests. This improves the agent-facing
substrate, but it does not clear the live Revit gates, so completion remains
blocked. Live safe-sandbox plugin call
`live-plugin-agent-stop-status-safe-sandbox-20260514` proved the normal
Hermes-facing path still works without the test override and returns the same
blocked stop status through `called_via: hermes-plugin`.

The MCP wrapper received the same sandbox-boundary hardening. The public
`revit_operator_command` MCP tool no longer exposes the outside-safe-root
override, and direct structured or raw-argv attempts to use that override fail
closed unless a dedicated local test environment flag is set. Focused MCP tests
passed, and live safe-sandbox MCP call
`live-mcp-agent-stop-status-safe-sandbox-20260514` returned the current blocked
stop status through `called_via: mcp` without completion authority.

The HTTP control server received the same sandbox-boundary hardening. JSON
payloads and raw `argv` attempts to use the outside-safe-root override fail
closed unless a dedicated local test environment flag is set. Focused HTTP
tests passed, and live safe-sandbox dispatcher call
`live-http-agent-stop-status-safe-sandbox-20260514` returned the current
blocked stop status without completion authority.

The agent-facing transports also now block model-root override smuggling.
Direct local CLI development tests can still use `--allow-model-outside-safe-root`,
but plugin, MCP, and HTTP/control-dispatcher paths reject that override through
command args, raw `argv`, and nested request-operation JSON. Focused plugin
coverage passed with 11 tests, and focused control/MCP model-root coverage
passed with eight selected tests. This tightens the safe copied-model boundary,
but it does not clear the live Revit gates, so completion remains blocked. The
full Revit operator regression later passed with 381 tests, the plugin slice
passed with 11 tests, and compileall completed for `tools/revit_operator` and
`plugins/revit-operator`.

The follow-up read-only live refresh regenerated stale stable handoff artifacts
without touching Revit. The final stable scan
`live-model-root-refresh-scan-clean-check-20260514` was clean, and the final
completion gate `live-model-root-refresh-gate-clean-check-20260514` still
reported four blocked gaps, 17 unsatisfied requirements, no safety guard
violations, and no permission to call `update_goal`.

A later read-only supervision refresh
`live-supervision-refresh-after-model-root-gate-20260514` refreshed approval
preflight and republished the current handoff. It found Revit running and idle,
with no dialogs, but bridge readiness still failed `loaded_build_current` and
required human restart or reload. The refreshed approval preflight found three
items ready for human review, and the follow-up ready-approval, next-approval,
human-gate-packet, current-handoff, stable-scan, and completion-gate artifacts
were regenerated without executing any approval-gated action. Final stable scan
`live-stable-scan-after-ready-approvals-20260514` was clean; final completion
gate `live-completion-gate-after-ready-approvals-20260514` remained blocked
with four blocked gaps, 17 unsatisfied requirements, zero safety guard
violations, and no permission to call `update_goal`.

The completion audit checklist now carries structured blocker metadata for
every unsatisfied prompt-to-artifact row. Focused and full test coverage passed,
then live read-only refresh `live-audit-blocker-metadata-refresh-20260514`
regenerated the stable audit and gate. The refreshed audit had 17 unsatisfied
rows and zero missing blocker metadata rows; the stable scan remained clean and
the final completion gate still blocked completion with four blocked gaps and no
safety guard violations.

The blocker metadata requirement is now enforced by the stable artifact scan and
the hard completion gate, not only produced by the audit. Tests covering
malformed audit rows passed and the full Revit operator regression now reports
`383 passed`. Live read-only sequence
`live-audit-blocker-metadata-guard-refresh-20260514` regenerated the stable
handoff, stable scan, and hard gate in order. The final stable scan was clean
with zero blocker-metadata violations and zero missing blocker rows; the final
hard gate still refused completion with `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, four
blocked gaps, 17 unsatisfied requirements, and zero safety guard violations.

The final bridge-readiness refresh tightened the current handoff without
clearing the gate. `live-addin-security-readiness-final-check-20260514`
verified the Revit 2025 manifest, expected Hermes DLL path, and local
Authenticode signature. `live-bridge-readiness-final-check-20260514` and
`live-verify-bridge-build-final-check-20260514` confirmed the bridge is
connected but the loaded add-in is still stale or missing current bridge
metadata, so `loaded_build_current` remains the failed check.
`live-bridge-restart-validation-plan-final-check-20260514` refreshed the
no-save human restart/reload checklist with `pre_restart_files_ready: true` and
`status: human_restart_required`. The refreshed stop-status artifact
`live-agent-stop-status-after-final-bridge-check-20260514` reports
`should_stop_agent: true`, no autonomous progress, and no execution authority.
The subsequent stable scan was clean, and the final hard gate still blocks
completion with four blocked gaps, 17 unsatisfied requirements, no missing
blocker metadata, and zero safety guard violations.

Completion-gate stdout has been hardened so the agent-facing command response
does not expose approval phrases or approval tokens. Focused regression coverage
passed for redacting only `north-star-completion-gate` stdout, the live pattern
check found no direct approval markers in the command output, and the latest
post-scan hard gate still reports `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, four
blocked gaps, 17 unsatisfied requirements, and zero safety guard violations.
The docs have also been sanitized to avoid preserving literal approval material
in validation notes.

After a bounded continuation attempt, a longer read-only `north-star-watch`
refresh exceeded the tool timeout and was treated as inconclusive. The matching
repo-local watch processes were stopped, and the partial artifacts were not used
as completion evidence. A read-only stop-status refresh repaired the stable
stop boundary, then `live-stable-scan-after-interrupted-watch-cleanup-20260514`
returned `status: clean` with zero violations. The final hard gate
`live-completion-gate-after-interrupted-watch-cleanup-final-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, no autonomous progress, human/real-condition gates required, and
zero safety guard violations.

The read-only watch path now finalizes its own stop-status boundary instead of
requiring manual cleanup after a completed watch. It refreshes stable
agent-stop status after publishing the hard gate, rebuilds/publishes a final
gate, and refreshes agent-stop status again against that final gate. The
completion-gate Markdown mirrors `may_execute_from_this_result: false` so the
stable authority mirror has both JSON and Markdown coverage. Tests covering the
watch path and drift checks passed, the full Revit operator regression passed
with `384 passed`, and live one-check watch
`live-north-star-watch-finalization-fix-check-20260514` completed with zero
safety guard violations. The follow-up stable scan was clean, and the follow-up
hard gate still reports `completion_allowed: false`, `may_call_update_goal:
false`, `audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, no autonomous progress, human/real-condition gates required, and
zero safety guard violations.

The post-human resume path now finalizes the same stop-status boundary as the
watch path. `north-star-resume-check` refreshes stable agent-stop status after
its hard gate, rebuilds/publishes a final gate, then refreshes agent-stop status
again against that final gate. Focused resume-check coverage, the combined
continuation boundary slice, and the full Revit operator regression passed.
Live resume check `live-resume-check-finalization-fix-check-20260514` remained
blocked on stale bridge checks but returned zero safety guard violations. A
subsequent hard gate correctly rejected stale approval handoff material after
the latest preflight expired; read-only refresh
`live-refresh-preflight-after-resume-finalization-fix-20260514` regenerated the
preflight and current handoff, and the final stable scan and hard gate returned
clean blocked status with four unresolved external gates and 17 unsatisfied
requirements.
