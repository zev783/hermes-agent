# Revit Operator Validation

This document maps the expanded Revit human-operator requirements to concrete implementation evidence and verification commands.

For the full prompt-to-artifact north-star checklist, see `REVIT_OPERATOR_NORTH_STAR_AUDIT.md`.

## Implementation Evidence

| Requirement | Evidence |
| --- | --- |
| Output writes are sandboxed | `cli.py` resolves a sandbox; `safety.py` validates sandbox/output paths; `journal.py` writes under the sandbox |
| Running Revit processes are detectable | `windows.py` implements `list_processes` with Win32 Toolhelp enumeration and includes processes in `status` |
| Revit UI state is observable | `windows.py` implements `status`, `list_windows`, `list_dialogs`, `ui_tree`, and `screenshot` |
| OCR fallback exists | `ocr-screenshot` captures a screenshot and runs optional OCR through `auto`, `tesseract`, or `rapidocr` backends, preserves OCR text items with confidence/bounds when the backend exposes geometry, or writes a structured missing-dependency artifact |
| OCR readiness is explicit | `ocr-health` reports Tesseract and RapidOCR backend readiness, Python packages, executable discovery, preferred backend, and install hints without capturing UI |
| UIA state is observable when dependency is available | `uia-tree` exports AutomationId/ControlType data through optional `pywinauto`; `uia-control-details` reports supported wrapper action methods; missing dependency is reported clearly |
| UIA controls are locatable | `uia-find-control` searches UIA name, ControlType, AutomationId, and class name |
| UIA invocation is guarded | `uia-invoke` dry-runs by default, requires exact approval, rejects ambiguous matches, supports explicit approved methods, and blocked targets such as Save have no execution path; `uia-method-matrix` verifies every allowlisted UIA method policy without touching live UI |
| Approval gates are rehearsable | `action-approval-matrix` dry-runs representative focus/click/type/key/UIA/visual-click primitives through the same executor, classifies representative bridge operations, verifies exact tokens for approval-required cases, verifies blocked Save surfaces, and reports zero executions |
| Live UI execution coverage is auditable | `ui-execution-coverage-audit` scans sandboxed journals for authorized executed UI actions, groups them by surface and payload-marked ribbon/context-menu semantics, and reports missing UIA/ribbon/context-menu/visual/workflow execution coverage without touching Revit |
| Named ribbon actions are guarded | `ribbon-actions`, `ribbon-action-matrix`, `plan-ribbon-action`, and `ribbon-action` map known ribbon/menu requests to UIA descriptors, include common Revit tab descriptors, name-based command descriptors, and blocked File/Save/Sync/Print/Export/Publish surfaces, verify descriptor policy without touching live UI, and execute only through the `uia-invoke` approval gate |
| Context-menu workflows are guarded | `context-menu-actions`, `context-menu-action-matrix`, `context-menu-snapshot`, `plan-context-menu-action`, `context-menu-action`, `plan-context-menu-item`, and `context-menu-select-item` separate menu opening from item selection, use exact UIA targets, validate descriptor/item policies without live UI contact, snapshot visible menu items read-only, block dangerous descriptors/items, and require approval before any UI action |
| Visible controls are locatable | `find-control` searches the active Revit Win32 UI tree by text/class and writes `control_matches.json` |
| Project Browser is observable | `project-browser-snapshot` locates the Project Browser control and captures its UI tree, screenshot, optional UIA tree, and optional OCR evidence without navigation; `project-browser-plan-navigation` carries OCR line/item matches, confidence, and bounds as visual evidence; `project-browser-plan-visual-activation` and `project-browser-visual-activate` turn OCR geometry into approval-gated visual-click plans/dry-runs without automatic coordinate clicking |
| Properties palette is observable | `properties-palette-snapshot` locates the visible Properties palette and captures its UI tree, screenshot, optional UIA tree, and optional OCR evidence without focusing fields, typing values, clicking Apply, or modifying the model |
| Metadata-backed view lookup exists | `find-view` searches exported sheets/views and writes an approval-gated activation hint only for an exact non-placeholder match |
| Dialogs classify conservatively | `classify_dialog` treats unknown dialogs and Revit workflow prompts as high risk |
| Known prompt rules exist | `dialogs.py` and `known-dialogs` expose reusable rules for unsigned add-ins, transmitted models, unresolved/missing links, upgrade/detach/open-workset/worksharing prompts, link reloads, warnings, failure processing, family load options, save-changes, and print/export |
| Learned dialog rules are sandboxed | `record-dialog-rule` writes conservative learned classifiers under `revit_operator_dialog_rules`; `dialog-rule-library` lists built-in and learned rules; `classify-dialog` consults learned rules without authorizing actions |
| Dialog response playbooks exist | `dialog-workflows` lists conservative known-dialog playbooks; `dialog-workflow-matrix` validates representative prompt playbooks; `plan-dialog-response` and `plan-current-dialog-response` return approval-gated click dry-run plans only for configured non-destructive prompt responses and otherwise return safe preflight commands, blocked buttons, and approval conditions |
| Dialog OCR fallback is guarded | `plan-current-dialog-response --use-ocr` can capture OCR evidence for inaccessible dialog text, but it classifies OCR text as a prompt only when fresh Revit status is modal or active dialogs are present |
| Generic dangerous UI clicks are blocked | `classify_action("click", {"target": "Save"})` returns `block` |
| Active-view changes are approval-gated | `request-operation --operation activate-view` is critical-risk, requires an exact approval token to execute, and does not require the model-write guard |
| Explicit save/sync/reload/close/modify requests exist | `request-operation` queues named bridge commands; sync requires `--allow-sync` |
| Model opening exists | `open-model` validates copied paths, infers R25 as Revit 2025, resolves Revit.exe, dry-runs, and launches after approval; add-in `open-model` can open from already-running Revit with detach options |
| In-process add-in source exists | `tools/revit_operator/addin/HermesRevitOperatorApp.cs` implements `IExternalApplication`, active document status, metadata export, and guarded command execution |
| Add-in install path exists | `addin_installer.py` and `install-addin` write the Revit `.addin` manifest after the DLL is built |
| Unsigned add-in popup has a mitigation | `addin-security-preflight` verifies the Revit 2025 manifest, expected Hermes DLL path, and Authenticode signature before any load decision; the unsigned-add-in dialog playbook recognizes both explicit unsigned prompts and "publisher could not be verified" wording, prefers `trust-addin` and restart for the verified Hermes add-in, only plans `Always Load` as an approval-gated click for the verified Hermes add-in, and blocks all load buttons for unknown add-ins |
| Loaded add-in build is observable | `bridge-status` reads `addin_status.json` and `addin_heartbeat.json`; `verify-bridge-build` checks the loaded bridge protocol, source capability stamp, and continuous-Idling flags; `bridge-readiness` audits the source project, built DLL, installed manifest, loaded bridge payload, and restart/reload gate; the add-in source writes bridge protocol, source capability stamp, session id, assembly path, assembly version, assembly last-write time, and continuous-Idling capability flags |
| Bridge restart/reload handoff is explicit | `bridge-restart-validation-plan` writes a read-only human handoff checklist, stale loaded-addin cause, failed/expected bridge metadata, and post-restart validation commands when `bridge-readiness` shows the installed DLL/manifest are ready but the running Revit session is stale; `bridge-post-restart-validation` runs the read-only post-human-restart status, bridge, add-in-security, model-readiness, and north-star checks in one journaled command |
| Bridge supervision exists | `bridge-results` lists command results and `wait-bridge-result` waits for a specific add-in command id |
| Recovery evidence exists | `recovery-snapshot` captures status, dialogs, dialog recovery plans, UI tree, screenshot, active document bridge state, recent bridge results, and recommended next steps without taking action; `recovery-drill-matrix` validates synthetic recovery recommendations without touching live Revit |
| Long-running supervision exists | `supervise-session` polls Revit state, records transitions, captures recent bridge results, checkpoints `supervision_log.json` after each observation with supervisor PID, stops on modal states by default, detects repeated busy/unknown stalls, can capture recovery evidence on stall, and can resume/append by task id; `supervision-endurance-matrix` rehearses resume, modal-stop, busy-stall, and unknown-stall behavior through the real loop with synthetic observers; `supervision-endurance-audit` checks accumulated live logs against an hours-long target, merges overlapping intervals before counting elapsed evidence, reports active/stale in-progress PID status, and reports insufficiency explicitly |
| Model readiness predicate exists | `wait-model-ready` waits for idle/non-modal Revit state, bridge active-document availability, and optional expected document/version/view predicates, then writes `model_ready_status.json` without taking UI or model actions |
| QA workflow scaffold exists | `qa-workflow` queues read-only bridge commands, waits for results, captures UI evidence, exports metadata, and writes a draft QA report |
| Workflow memory exists | `ui-workflows`, `ui-workflow-matrix`, `ui-workflow-smoke-matrix`, `plan-ui-workflow`, and `run-ui-workflow` expose reusable guarded UI workflow recipes with static recipe verification, live smoke-safe prefix validation, and fresh-observation step gates; `run-ui-workflow` journals first/last live observations so approved workflow execution can be audited; `record-workflow` writes sandboxed workflow templates from task journals; templates omit approval tokens, carry state predicates for document/view/window/dialog context when available, and expose parameter bindings for common payload fields; `workflow-library` lists them; `plan-workflow` dry-runs replay classification and reclassifies parameter overrides; `workflow-approval-plan` writes fresh approval-token packages and blocks unsafe overrides; `replay-workflow` performs fresh-observation, state-predicate guarded replay and captures recovery snapshots on stop; approval tokens are not reused |
| All actions are logged | `cli.py`, `actions.py`, `operations.py`, `recovery.py`, `supervision.py`, `workflows.py`, `addin_installer.py`, and `qa.py` write task journal entries |
| Local command interface exists | `pyproject.toml` exposes `revit-operator` and `revit-operator-mcp`; `serve` exposes local HTTP `/health` and `/command`; the HTTP control server refuses the test-only outside-safe-root override from JSON payloads or raw argv unless `HERMES_REVIT_OPERATOR_HTTP_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests; `plugins/revit-operator` registers the `revit_operator` Hermes tool; the plugin schema withholds the test-only outside-safe-root override and refuses that override from structured args or raw argv unless `HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests; `tools/revit_operator/mcp_server.py` exposes a thin MCP stdio wrapper whose public tool signature also withholds the outside-safe-root override and refuses that override unless `HERMES_REVIT_OPERATOR_MCP_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests; package data includes add-in source/templates/scripts |
| Agent-facing transport safety is auditable | `transport-safety-matrix` writes a read-only JSON/Markdown matrix that checks CLI/stdout, HTTP/control, MCP, and Hermes plugin approval-material redaction, verifies the plugin schema withholds the test-only sandbox override, and verifies HTTP/MCP/plugin wrappers fail closed for external-sandbox overrides, model-root overrides, and recursive server startup without touching Revit |
| Completion audit is explicit | `north-star-audit` writes JSON and Markdown prompt-to-artifact checklists, verifies named deliverables/commands/live evidence markers, evaluates gap evidence from bridge readiness, recovery snapshots, supervision endurance, and UI execution coverage artifacts, preserves detailed endurance fields such as overlap-adjusted seconds, active/stale in-progress PID counts, and active-interval extension accounting, reports per-gap blocker metadata (`human_action_required`, `human_approval_required`, `real_condition_required`, or `time_gated`), rolls those blockers into a top-level `blocker_summary`, splits remaining autonomous versus human/real-condition work in `completion_actions`, and reports `north_star_complete: false` while remaining gaps exist; `north-star-status` writes a compact read-only blocker handoff with approval candidates, manual gates, and explicit `completion_gate_required` / `completion_gate_command` fields so status cannot be used as the final completion authority; `north-star-approval-plan` writes a read-only approval handoff for the next guarded validation actions without executing them, embeds available dry-run `prevalidation` evidence for candidate approval items, records `approval_freshness` metadata including token-bound payload digest and source prevalidation artifact, and withholds human-facing execute lines for items that latest preflight does not mark ready; `north-star-approval-preflight` runs generated dry-run commands with execution and approval-token flags stripped, reports per-item approval readiness, and records expected Revit/title/view context plus expiring freshness metadata before tokens are requested; `north-star-ready-approvals` writes a read-only filtered handoff that exposes execute-after-approval lines only for items latest preflight marks ready and withholds non-ready items with reasons; `north-star-approval-phrase-verify` checks an exact supplied phrase against the current waiting-state phrase and token mapping while keeping `may_execute_from_this_result` false; `north-star-approved-execution-preview` shows the exact separate command only after phrase, token, preflight readiness, next selected item, requested Revit/title/view context, and unexpired preflight freshness still match, while keeping execution flags false; `north-star-approval-verify` explains what a supplied token currently matches without executing it, reports whether the token matches exactly one current approval item, and includes latest preflight readiness while keeping `may_execute_from_this_result` false; `north-star-watch` polls the same live gates read-only, stops on bridge-ready or recovery-condition state changes, then refreshes a hard completion-gate result plus unblock-readiness so watch output cannot rely on status alone, and can explicitly republish the stable current handoff after optional preflight; `north-star-resume-check` refreshes status, approval handoff, post-restart bridge validation, audit artifacts, a hard completion-gate artifact, and stable `NORTH_STAR_AUDIT_CURRENT.*` / `NORTH_STAR_COMPLETION_GATE_CURRENT.*` files after a human-gated state changes; `north-star-human-gate-packet` writes concise JSON/Markdown handoff artifacts for the human supervisor, including token verification commands, freshness rules, and latest preflight readiness for approval items; `north-star-next-human-action` writes stable `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` one-screen unblock cards and refreshes the stable completion gate without granting execution authority; `north-star-blocked-ledger` writes one durable entry per unresolved gate and withholds execute commands for approval items that latest preflight does not mark ready; `north-star-current-handoff` publishes stable current JSON/Markdown files at the sandbox root, includes `NORTH_STAR_AUDIT_CURRENT.json` and `NORTH_STAR_AUDIT_CURRENT.md`, and links existing stable artifact-scan/unblock-readiness safety files in `stable_files` when present; `north-star-stable-artifact-scan` writes JSON/Markdown diagnostics for sandbox-root `NORTH_STAR_*CURRENT*` files, checking stale approval credential leakage, execution-authority drift, legacy tombstone redaction, blocker count consistency, `blocked_gap_ids` consistency against the hard completion gate, fresh-preflight handoff mtime alignment, and `NORTH_STAR_HANDOFF_CURRENT.json` `stable_files` reference integrity without touching Revit; `north-star-completion-gate` runs a fresh audit, directly applies those stable-handoff safety checks as completion-gate safety guards, includes `blocked_gate_details` with concrete next steps, `followup_actions` with stale-token warnings, and `stable_artifact_hints` pointing to the current human packet/audit/approval/restart/resume/scan handoff files, and refuses completion unless `completion_allowed` and `may_call_update_goal` are both true |
| Next approval handoff is explicit | `north-star-next-approval` writes a single-item read-only handoff for the next safest ready approval candidate only when latest preflight freshness is still valid, defers other ready items without execute commands, writes `NORTH_STAR_NEXT_APPROVAL_CURRENT.json` / `.md` through the current handoff, and keeps `may_execute_from_this_result: false` |
| Waiting state handoff is explicit | `north-star-waiting-state` writes `NORTH_STAR_WAITING_STATE_CURRENT.json` / `.md` with the current pause/resume state, exact required approval phrase, human/real-condition gates, and false execution flags; `north-star-approval-phrase-verify` can verify that phrase without approving or executing anything; `north-star-approved-execution-preview` can show the exact eligible separate command only after phrase verification, latest-preflight context matching, and latest-preflight freshness checks all succeed |
| Optional Revit UIA dependency is reproducible | `pyproject.toml` defines the `revit` extra with Windows-only `pywinauto` |
| Optional OCR dependency is reproducible | `pyproject.toml` defines the `revit-ocr` extra with `Pillow`, `pytesseract`, and `rapidocr-onnxruntime`; Tesseract still requires a separate executable, while RapidOCR is package-based |

## Verification Commands

Run from the repo root:

```powershell
python -m compileall -q tools\revit_operator plugins\revit-operator
python -m pytest -n 0 --basetemp .\.tmp-pytest-revit -q tests\tools\test_revit_operator.py tests\plugins\test_revit_operator_plugin.py
```

Build add-in after installing a .NET SDK:

```powershell
dotnet build .\tools\revit_operator\addin\HermesRevitOperator.csproj -c Release -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025"
```

## Local Verification Performed

Current repository verification:

- Python syntax checks passed for the Revit operator package and Hermes plugin wrapper.
- `python -m pytest -n 0 --basetemp .\.tmp-pytest-revit -q tests\tools\test_revit_operator.py tests\plugins\test_revit_operator_plugin.py` passed: 243 tests.
- Revit API DLLs exist at `C:\Program Files\Autodesk\Revit 2025`.
- A local .NET 8 SDK was installed under `.tmp-dotnet\sdk` for this workspace.
- `HermesRevitOperator.dll` built successfully against Revit 2025.
- The Revit 2025 `.addin` manifest was installed under `%APPDATA%\Autodesk\Revit\Addins\2025`.
- The add-in DLL was signed and `Get-AuthenticodeSignature` reports `Valid` in the non-elevated Hermes context.

Live Revit 2025 read-only bridge verification performed on 2026-05-12:

- Revit 2025 launched the copied local model from:
  `C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt`
- Live validation sandbox:
  `C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT\live_readonly_bridge_20260512`
- Revit process/window observation succeeded:
  - PID: `10920`
  - main HWND: `2297118`
  - title: `Autodesk Revit 2025.2 - [24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM_detached - Sheet: Z - STARTING VIEW]`
  - state after startup prompts: `idle`
- Startup prompts were observed, classified, and handled through approval-gated UI primitives:
  - `PyRevitLoader - Error Loading pyRevit`: clicked `Close`
  - `Transmitted model`: clicked `Work with this model temporarily`; did not choose the central-model save option
  - `Unresolved References`: clicked `Ignore and continue opening the project`; did not open Manage Links or reload links
- The in-process add-in bridge loaded and wrote:
  - `bridge\addin_status.json`
  - `bridge\addin_heartbeat.json`
  - `bridge\active_document.json`
- Required bridge-loop proof succeeded:
  - queued `active-document`
  - `bridge\command_queue.jsonl` recorded command id `active_document-20260512T184536Z-6611d57a`
  - `bridge\command_results.jsonl` recorded success for `active-document`
  - `bridge\active_document.json` contained live active document state
- Active document state reported:
  - title: `24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM_detached`
  - Revit version: `2025`
  - worksharing: `enabled`
  - active view: `STARTING VIEW` / `DrawingSheet`
  - dirty: `true`
- Read-only metadata export succeeded:
  - bridge snapshot: `bridge\metadata_snapshot.json`
  - CLI copy: `revit_operator_runs\live-export-copy\metadata\metadata-20260512T184854Z.json`
  - label: `DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW`
  - read_only: `true`
  - counts: 3 levels, 0 grids, 116 views, 8 sheets, 9 titleblocks, 1 link, 23 warnings, 202 families, 1029 types
- UI evidence succeeded:
  - UI tree: `revit_operator_runs\live-ui-tree\ui_tree.json`
  - screenshot: `revit_operator_runs\live-screenshot-2\screenshots\screenshot-20260512T184945Z.bmp`
- OCR fallback evidence succeeded:
  - `ocr-screenshot --hwnd 2297118` captured a screenshot and wrote `revit_operator_runs\live-ocr-screenshot\ocr_screenshot.json`
  - missing Python dependencies reported: `Pillow`, `pytesseract`
  - screenshot: `revit_operator_runs\live-ocr-screenshot\screenshots\screenshot-20260512T200202Z.bmp`
- OCR readiness check succeeded:
  - `ocr-health` wrote journal `revit_operator_runs\live-ocr-health\journal.jsonl`
  - ready: `false`
  - current readiness shape reports both `tesseract` and `rapidocr` backends; on this machine both are currently unavailable
  - missing: `Pillow`, `pytesseract`, `Tesseract executable`, `rapidocr-onnxruntime or rapidocr`
  - no screenshot was captured and no OCR was run
- RapidOCR backend installation and live extraction succeeded:
  - installed `rapidocr-onnxruntime>=1.4.4,<1.5` into the Hermes venv
  - `ocr-health` task `live-ocr-health-rapidocr` reported `ready: true`, `preferred_backend: rapidocr`, `rapidocr_onnxruntime: true`
  - Tesseract remained unavailable because `pytesseract` and a Tesseract executable are not installed
  - `ocr-screenshot --backend rapidocr --hwnd 2297118` task `live-ocr-rapidocr-screenshot` captured the live Revit window and wrote `ocr_screenshot.json`
  - OCR result: `success: true`, `dependency_missing: false`, `backend: rapidocr`, `line_count: 123`, `text_length: 2280`
  - screenshot: `revit_operator_runs\live-ocr-rapidocr-screenshot\screenshots\screenshot-20260512T220819Z.bmp`
- UIA evidence succeeded after installing optional local dependencies `pywinauto` and `comtypes` in the Hermes venv:
  - initial missing-dependency artifact: `revit_operator_runs\live-uia-tree\uia_tree.json`
  - live UIA tree: `revit_operator_runs\live-uia-tree-real\uia_tree.json`
  - node count: 148
  - exposed ribbon tabs, quick access controls, AutomationIds, ControlTypes, enabled state, and visibility
- UIA semantic control location succeeded:
  - `uia-find-control --automation-id "ID_Save_RibbonItemControl"` matched one Save ribbon item
  - output: `revit_operator_runs\live-uia-find-save\uia_control_matches.json`
  - matched AutomationId: `ID_Save_RibbonItemControl`
  - no click or invocation was performed; generic Save actions remain blocked
- UIA invocation safety checks succeeded:
  - `uia-invoke --automation-id "View"` dry-ran only and returned exact approval token `<redacted approval token>`
  - `uia-invoke --automation-id "ID_Save_RibbonItemControl"` returned `status: blocked`
  - blocked Save output says `No execution path; this action is blocked by policy.`
  - no live UIA invoke was executed without human approval
- UIA method policy matrix succeeded:
  - `uia-method-matrix` task `live-uia-method-matrix` validated 10 allowlisted UIA methods and 21 synthetic policy cases
  - result: `failed_cases: []`, `approval_required_count: 11`, `blocked_count: 10`, `executed_count: 0`, `live_ui_touched: false`
  - each method kept non-destructive targets approval-required, Save targets blocked, and unsupported methods rejected before UIA lookup
  - no UIA tree was searched, no window was focused, and no control was invoked
- Action approval matrix succeeded:
  - `action-approval-matrix` task `live-action-approval-matrix` validated 13 representative primitive/bridge-operation policy cases
  - result: `failed_cases: []`, `approval_required_count: 9`, `blocked_count: 2`, `allowed_count: 2`, `executed_count: 0`
  - checked exact approval tokens for focus/click/type/non-Escape key/UIA/visual-click cases, blocked generic Save click/UIA targets, allowed Escape/read-only active-document cases, and critical approval for Save/activate-view bridge operations
  - no UI action was executed and no bridge operation was queued
- UI execution coverage audit succeeded:
  - `ui-execution-coverage-audit` task `live-ui-execution-coverage-audit` scanned 204 sandboxed journals without touching Revit and explicitly excluded dry-run workflow records from execution coverage
  - result: `status: insufficient_evidence`, `target_met: false`, `qualifying_execution_count: 14`, `excluded_execution_count: 5`
  - covered required surfaces: `focus`, `escape-key`, and `dialog-click`
  - missing required surfaces: `type-text`, `uia-invoke`, `visual-click`, `ribbon-action`, `context-menu-action`, `context-menu-item`, and `approved-ui-workflow-step`
  - approved workflow coverage requires token-backed `approved_executed_steps`; low-risk observation/planning workflow steps do not count
  - no UI action, bridge operation, save, sync, reload, close, detach, upgrade, or model modification was executed by the audit
- Named ribbon action plan succeeded:
  - `plan-ribbon-action --name view-tab --max-depth 5 --limit 20` matched one live UIA target: `View`
  - output journal: `revit_operator_runs\live-plan-ribbon-view-tab\journal.jsonl`
  - policy: `risk: high`, `decision: approval_required`, token `<redacted approval token>`
  - no ribbon action was executed
- Expanded ribbon action listing and live plan succeeded:
  - `ribbon-actions` task `live-ribbon-actions-expanded` returned 15 descriptors
  - descriptors include common Revit tabs: Architecture, Structure, Systems, Insert, Annotate, Analyze, Collaborate, View, Manage, Add-Ins, RTM, and Modify
  - blocked descriptors include File/backstage, Save, and Synchronize with Central
  - `plan-ribbon-action --name annotate-tab --max-depth 5 --limit 20` matched exactly one live UIA target and returned approval token `<redacted approval token>`
  - `plan-ribbon-action --name file-menu --max-depth 5 --limit 20` remained non-executable because the descriptor is blocked
- Expanded ribbon command descriptor listing succeeded:
  - `ribbon-actions` task `live-ribbon-actions-expanded-2` returned 24 descriptors
  - added name-based descriptors for Manage Links, Visibility/Graphics, View Templates, Review Warnings, and Project Information
  - added blocked descriptors for Save As, Print, Export, and Publish
  - `plan-ribbon-action --name print` task `live-plan-ribbon-print-blocked` remained non-executable because the descriptor is blocked
  - `plan-ribbon-action --name manage-links-command` task `live-plan-ribbon-manage-links-descriptor` produced an approval-gated name-based search payload; the current visible ribbon state exposed no matching target, so it was not executable
  - current live planning task `live-plan-ribbon-view-tab-current` resolved `View` to one enabled UIA button with approval token `<redacted approval token>`; `live-uia-control-details-view-tab-current` reported available methods including `select`, `invoke`, `set_focus`, `right_click_input`, and `toggle`, but no method was executed
  - current dry-run task `live-dry-run-ribbon-view-tab-current` confirmed `ribbon-action --name view-tab` is executable only with the exact `<redacted approval token>` token and executed nothing
  - current dry-run task `live-dry-run-uia-view-tab-select-current` confirmed direct `uia-invoke --automation-id View --method select` remains blocked without its exact token and executed nothing
  - current dry-run task `live-dry-run-context-menu-project-browser-current` confirmed the context-menu action remains non-executing in the current visible UI state and executed nothing
  - current live planning tasks `live-plan-ribbon-manage-links-current` and `live-plan-context-menu-project-browser-current` produced approval-gated payloads but found no executable target in the current visible UI state
- Read-only supervision succeeded:
  - `supervise-session --max-checks 2 --poll 1 --duration 10 --bridge-result-limit 3` wrote `revit_operator_runs\live-supervise-session\supervision_log.json`
  - check count: 2
  - final state: `idle`
  - active dialogs: 0
  - stop reason: `max_checks_reached`
- Read-only supervision resume succeeded:
  - `supervise-session --max-checks 1 --poll 1 --duration 10 --bridge-result-limit 3` wrote `revit_operator_runs\live-supervise-resume\supervision_log.json`
  - a second call with `--resume --max-checks 1` appended a second observation
  - `previous_check_count`: 1, `new_check_count`: 1, `check_count`: 2
  - the log contains two supervision segments
  - no actions were executed
- Longer live supervision resume succeeded:
  - `supervise-session --duration 60 --poll 5 --max-checks 6 --bridge-result-limit 5` task `live-supervise-endurance-real` recorded 6 live checks
  - a second call with `--resume --duration 60 --poll 5 --max-checks 6` appended 6 more checks to the same task
  - final result: `check_count: 12`, `previous_check_count: 6`, `new_check_count: 6`, two supervision segments, final state `idle`, active dialog count `0`
  - stall analysis reported `stalled: false`, hung window count `0`, and recommendation `Continue observing.`
  - no UI action, bridge operation, save, sync, reload, close, detach, upgrade, or model modification was executed
- Supervision endurance evidence audit succeeded:
  - `supervision-endurance-audit --target-hours 2 --min-checks 24` task `live-supervision-endurance-audit` scanned sandboxed supervision logs without polling Revit
  - result: `status: insufficient_evidence`, `target_met: false`, `qualifying_log_count: 5`, `excluded_log_count: 4`, `in_progress_log_count: 2`, `active_in_progress_log_count: 1`
  - accumulated live evidence was `check_count: 18`, `total_live_seconds: 54.28897299999999`, `total_live_hours: 0.015080270277777776`, below the 2-hour/24-check gate
  - elapsed evidence is overlap-adjusted; the audit merges qualifying intervals before setting `total_live_seconds`, keeps `raw_total_live_seconds` for diagnostics, and reports active/stale in-progress supervisor PID status
  - synthetic endurance-matrix logs were excluded and no UI action, bridge operation, save, sync, reload, close, detach, upgrade, or model modification was executed
- Model readiness predicate succeeded:
  - `wait-model-ready --timeout 10 --poll 1 --expected-title-contains "24522 St John XXIII" --expected-revit-version 2025 --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-wait-model-ready` wrote `model_ready_status.json`
  - result: `ready: true`, `stop_reason: model_ready`, `check_count: 1`
  - checks passed for Revit running, main window present, idle state, no active dialogs, active-document bridge availability, document title, Revit version, active view name, and active view type
  - no dialog click, model open, view activation, save, sync, or model modification was executed
- Unsigned add-in startup preflight succeeded:
  - `addin-security-preflight --revit-version 2025` task `live-addin-security-preflight-fixed` verified the installed Revit 2025 manifest points to the expected `HermesRevitOperator.dll`, the DLL exists, the Authenticode signature is valid, and the signer subject is `CN=Hermes Revit Operator Local Code Signing`
  - result: `status: verified`, `expected_local_hermes_addin: true`, `needs_trust_addin: false`, `allowed_dialog_button: Always Load`
  - no dialog click, certificate write, signing operation, Revit restart, save, sync, or model modification was executed
- Current loaded bridge is still stale:
  - `bridge-readiness --revit-version 2025` task `live-bridge-readiness-after-security-preflight` verified the source project, built DLL, and installed manifest, but returned `ready_for_continuous_bridge: false`
  - `verify-bridge-build` task `live-verify-bridge-build-after-security-preflight` returned `status: stale_or_unverified` because the loaded add-in payload lacks the new `addin` metadata block, `bridge_protocol_version: 0.2`, and `continuous-idling-status-file-retry-v2`
  - next step remains human-approved Revit restart/reload when safe; Hermes did not close, restart, save, sync, reload, or modify Revit
- Bridge restart validation handoff succeeded:
  - `bridge-restart-validation-plan` task `live-bridge-restart-validation-plan` wrote `bridge_restart_validation_plan.json`
  - result: `status: human_restart_required`, `pre_restart_files_ready: true`, `restart_or_reload_required: true`, `ready_for_continuous_bridge_now: false`
  - post-restart validation commands include `status`, `bridge-status`, `verify-bridge-build`, `bridge-readiness --revit-version 2025`, `addin-security-preflight --revit-version 2025`, and `wait-model-ready` with expected title/version/view predicates
  - blocked automation explicitly says Hermes must not close/restart Revit automatically and must not save, sync, reload links, detach, or upgrade as part of the handoff
- Bridge post-restart validator failed safely before human restart:
  - `bridge-post-restart-validation --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-bridge-post-restart-validation-current` wrote `bridge_post_restart_validation.json`
  - result: `validation_passed: false`, `status: failed`
  - passed checks included `status_observed`, `no_active_dialogs`, `bridge_status_connected`, `addin_security_verified`, `model_ready`, and `north_star_status_refreshed`
  - failed checks were `loaded_build_current` and `bridge_readiness_ready`, confirming the current running Revit session still needs a human restart/reload before continuous bridge readiness can be claimed
  - the validator was read-only and did not focus, click, type, invoke UIA, close, restart, save, sync, reload, detach, upgrade, or modify the model
- Control location succeeded:
  - `find-control --text "Project Browser" --max-depth 8 --limit 20` matched one visible Project Browser control
  - output: `revit_operator_runs\live-find-control-project-browser\control_matches.json`
  - matched hwnd: `1379600`
- Project Browser snapshot succeeded:
  - `project-browser-snapshot --search-depth 8 --tree-depth 4` matched one visible Project Browser control
  - output: `revit_operator_runs\live-project-browser-snapshot\project_browser_snapshot.json`
  - screenshot: `revit_operator_runs\live-project-browser-snapshot\screenshots\screenshot-20260512T194042Z.bmp`
  - selected hwnd: `1379600`
- Project Browser UIA diagnostic succeeded:
  - `project-browser-snapshot --include-uia --tree-depth 5 --uia-limit 300` wrote `revit_operator_runs\live-project-browser-snapshot-uia\project_browser_snapshot.json`
  - UIA node count: 6
  - evidence shows the panel/control is accessible, but browser item rows are not exposed as UIA tree items in the current state
- Project Browser OCR snapshot succeeded:
  - `project-browser-snapshot --include-ocr --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-snapshot-ocr` wrote `project_browser_snapshot.json`
  - selected hwnd: `1379600`
  - OCR result: `success: true`, `line_count: 17`
- Metadata-backed view lookup succeeded:
  - `find-view --sheet-number S2.0` matched one sheet: `S2.0 / FOUNDATION PLAN`
  - output: `revit_operator_runs\live-find-view-s2-plan\view_matches.json`
  - activation hint: `activate-view` with `id` 712292 and `sheet_number` `S2.0`
- Active-view dry-run guard succeeded:
  - `request-operation --operation activate-view --sheet-number S2.0` returned `risk: critical`
  - it required approval token `<redacted approval token>`
  - it did not require `--allow-model-write`
  - it did not execute or queue a bridge command
- Draft QA report succeeded:
  - `revit_operator_runs\live-qa-report\qa_report.md`
  - report label: `DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW`
  - findings included missing grids and 23 warnings for review
- Supervised read-only QA workflow succeeded:
  - command used focus plus Escape idle nudge because the current Revit session had loaded the older DLL before the continuous Idling source change
  - task id: `live-qa-workflow-3`
  - metadata: `revit_operator_runs\live-qa-workflow-3\metadata\metadata-20260512T190725Z.json`
  - UI tree: `revit_operator_runs\live-qa-workflow-3\ui_tree.json`
  - screenshot: `revit_operator_runs\live-qa-workflow-3\screenshots\screenshot-20260512T190725Z.bmp`
  - QA report: `revit_operator_runs\live-qa-workflow-3\qa_report.md`
  - final observed state: `idle`
- Bridge result supervision succeeded:
  - `bridge-results --limit 5` returned the latest successful `active-document` and `export-metadata` results from `bridge\command_results.jsonl`
  - `wait-bridge-result --command-id export_metadata-20260512T190723Z-7c70481c --timeout 0` found the matching result in one check
- Current loaded bridge status check:
  - `bridge-status` task `live-bridge-status-current` returned connected status and an idling heartbeat
  - the loaded Revit session still reports the older bridge payload without `source_capability_stamp` or assembly metadata, confirming Revit must be restarted/reloaded before the rebuilt add-in metadata can be live-validated
- Current loaded bridge build verification:
  - `verify-bridge-build` task `live-verify-bridge-build-current` returned `status: stale_or_unverified`
  - it passed `bridge_connected` and failed `addin_metadata_present`, `bridge_protocol_version`, `source_capability_stamp`, `supports_continuous_idling`, and `uses_idling_set_raise_without_delay`
  - this is expected until Revit is restarted/reloaded with the rebuilt add-in DLL
- Current bridge readiness audit:
  - `bridge-readiness` task `live-bridge-readiness` found the source project, built DLL, installed Revit 2025 manifest, and manifest Assembly path all present and aligned
  - it returned `ready_for_continuous_bridge: false` and `requires_revit_restart_or_reload: true` because the running Revit session is still loaded with the older bridge payload
  - next step is human-supervised Revit restart/reload when safe; Hermes did not close, restart, save, sync, reload, or modify Revit
- Recovery snapshot succeeded:
  - `recovery-snapshot --max-depth 2 --bridge-result-limit 5` wrote `revit_operator_runs\live-recovery-snapshot\recovery_snapshot.json`
  - screenshot: `revit_operator_runs\live-recovery-snapshot\screenshots\screenshot-20260512T193102Z.bmp`
  - observed state: `idle`
  - recommendation: `safe_to_continue_read_only`
- Recovery snapshot with embedded dialog plans succeeded:
  - `recovery-snapshot --max-depth 2 --bridge-result-limit 5` task `live-recovery-snapshot-dialog-plans` wrote `revit_operator_runs\live-recovery-snapshot-dialog-plans\recovery_snapshot.json`
  - current live state was `idle`, so `dialog_recovery_plans` was empty; unit coverage verifies modal snapshots include known dialog id, blocked buttons, and no planned unsafe click for an upgrade prompt
- Recovery drill matrix succeeded:
  - `recovery-drill-matrix` task `live-recovery-drill-matrix` validated 5 synthetic cases: modal upgrade dialog, busy without dialog, idle, Revit not running, and unknown state
  - result: `failed_cases: []`
  - the modal upgrade drill preserved known dialog id `upgrade-model`, returned `human_decision_required`, and produced no planned automatic action
  - no live Revit state was changed and no recovery action was executed
- Supervision endurance matrix succeeded:
  - `supervision-endurance-matrix` task `live-supervision-endurance-matrix` validated 4 synthetic long-run supervision cases
  - result: `failed_cases: []`
  - cases covered resume across two supervision segments, modal stop, busy stall with recovery snapshot capture, and unknown-state stall with recovery disabled
  - no live Revit UI action, bridge operation, save, sync, reload, close, or model modification was executed
- Known-dialog rule listing succeeded:
  - `known-dialogs` originally returned 10 reusable built-in rules and wrote journal `revit_operator_runs\live-known-dialogs\journal.jsonl`
  - expanded `known-dialogs` task `live-known-dialogs-expanded` returned 14 reusable built-in rules, adding Manage Links, type catalog, Visibility/Graphics, and View Template coverage
  - expanded `known-dialogs` task `live-known-dialogs-expanded-2` now returns 21 reusable built-in rules, adding missing links, open worksets, worksharing/central, warning review, failure processing, save-changes, and export-output-path coverage
- Learned dialog rule memory is implemented and unit-tested:
  - `record-dialog-rule` writes one JSON rule per classifier under the sandbox
  - learned rules cannot be recorded as low-risk
  - `classify-dialog` uses sandbox-learned rules for recognition while still returning conservative risk/recommended-action fields
  - `dialog-rule-library` lists both built-in and learned classifiers
- Dialog response playbooks are implemented and unit-tested:
  - `dialog-workflows` lists 21 known conservative response recipes
  - `plan-dialog-response` can produce approval-gated `click` dry-run plans for transmitted-model and unresolved-reference prompts
  - upgrade-model and reload-link prompts remain human-only with no planned click
  - Manage Links, type catalog, Visibility/Graphics, and View Template prompts are recognized as human-only workflows with blocked buttons and approval conditions
  - missing links, open worksets, worksharing/central, warning review, failure processing, save-changes, and export-output-path prompts are recognized as human-only workflows with blocked buttons and approval conditions
  - human-only prompt plans include safe preflight commands, blocked buttons, and approval conditions
- Live/sandbox dialog response planning succeeded:
  - `plan-dialog-response --title "Unresolved References" --button "Manage Links" --button "Ignore and continue opening the project"` wrote journal `revit_operator_runs\live-plan-dialog-response-unresolved\journal.jsonl`
  - planned action: dry-run `click` target `Ignore and continue opening the project`
  - click policy: `risk: high`, `decision: approval_required`, token `<redacted approval token>`
  - `plan-dialog-response --title "Autodesk Revit" --text "Do you want to save changes?" --button "Save" --button "Don't Save" --button "Cancel"` wrote journal `revit_operator_runs\live-plan-dialog-response-save-changes\journal.jsonl`
  - save-changes prompt result: `risk: critical`, `planned_action: null`, blocked buttons include `Save` and `Don't Save`
  - no click was executed
- Live current-dialog response planning succeeded:
  - `plan-current-dialog-response` wrote `revit_operator_runs\live-current-dialog-response-plan\current_dialog_response_plan.json`
  - active dialog count was 0, so no planned click was produced
  - no click was executed
- Live current-dialog OCR fallback succeeded:
  - `plan-current-dialog-response --use-ocr --ocr-backend rapidocr` task `live-current-dialog-ocr-plan-idle-gated` captured OCR evidence with `line_count: 168`
  - Revit was idle and active dialog count was 0, so `plan` remained `null`
  - reason: `No modal Revit dialog matched; OCR evidence was captured but not classified as a prompt.`
  - no click, UI invocation, save, sync, or model operation was executed
- Workflow memory succeeded:
  - `record-workflow --source-task-id live-qa-workflow-3 --name "Live Readonly QA Workflow"` wrote `revit_operator_workflows\Live-Readonly-QA-Workflow.json`
  - recorded workflow step count: 8
  - `workflow-library` listed the recorded template as valid
  - `plan-workflow --name "Live Readonly QA Workflow"` dry-ran the recorded workflow and reported focus steps as approval-required, with no execution
  - `replay-workflow` is now implemented as a conservative replay runner: dry-run by default, fresh observation before every step, recorded document/view/window/dialog state predicates when available, stop-on-unexpected-modal by default, no reusable approval tokens, and execution limited to guarded action primitives plus `request-operation`
- Parameterized workflow planning succeeded:
  - `click --target Cancel` dry-run task `live-parameterized-click-dry-run` produced no click and no UI state change
  - `record-workflow --source-task-id live-parameterized-click-dry-run --name "Parameterized Click Dry Run"` wrote `revit_operator_workflows\Parameterized-Click-Dry-Run.json` with parameter `step_0_target`
  - `plan-workflow --name "Parameterized Click Dry Run" --parameters-json '{"step_0_target":"OK"}'` reclassified the override as approval-required and did not execute it
  - `plan-workflow --name "Parameterized Click Dry Run" --parameters-json '{"step_0_target":"Save"}'` reclassified the override as blocked, returned `blocked_steps: [0]`, and did not execute it
- Workflow approval planning succeeded:
  - `workflow-approval-plan --name "Parameterized Click Dry Run"` task `live-workflow-approval-plan` wrote `workflow_approval_plan.json`
  - result: `template_contains_approval_tokens: false`, `stale_approval_tokens_reused: false`, `approval_required_count: 1`, `blocked_count: 0`
  - generated fresh replay token `<redacted approval token>` for step 0 and a guarded `replay-workflow --execute --approval-tokens-json ...` command for human review
  - `workflow-approval-plan --name "Parameterized Click Dry Run" --parameters-json '{"step_0_target":"Save"}'` task `live-workflow-approval-plan-blocked` returned `blocked_count: 1`, `approval_required_count: 0`, and no execute command
- North-star approval handoff succeeded:
- `north-star-approval-plan --sheet-number S2.0` writes `north_star_approval_plan.json` with exact-token candidate commands and manual items for the remaining guarded validation work, including context-menu open and exact context-menu item precondition steps needed by the UI execution coverage gate
- it is read-only and does not focus, click, type, invoke UIA, open a context menu, queue bridge work, restart, save, sync, reload, close, detach, upgrade, or modify the model
- `north-star-watch --sheet-number S2.0 --checks 2 --poll 0` task `live-north-star-watch-resume-check` wrote `north_star_watch.json`, observed the real Revit window twice, and stopped with `status: no_change`
- watch observations reported Revit `state: idle`, `dialog_count: 0`, `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, and failed bridge check `loaded_build_current`
- the watch safety note confirms it does not focus, click, type, invoke UIA, restart, close, save, sync, reload, detach, upgrade, or modify the model
- `north-star-watch --sheet-number S2.0 --checks 6 --poll 20` task `live-north-star-watch-after-approval-request-20260513` observed six idle Revit states after requesting the next approval, found no dialogs or hung window, and still reported `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, and failed bridge check `loaded_build_current`
- `north-star-resume-check --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-resume-check-stable-gate-20260513` wrote `north_star_resume_check.json`
- the resume check refreshed `north_star_status.json`, `north_star_approval_plan.json`, `bridge_post_restart_validation.json`, `north_star_audit.json`, `north_star_completion_gate.json`, and the stable `NORTH_STAR_AUDIT_CURRENT.*` / `NORTH_STAR_COMPLETION_GATE_CURRENT.*` files in one journaled read-only command
- result: `status: blocked_human_or_real_condition`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, with bridge validation failed checks `loaded_build_current` and `bridge_readiness_ready`
- it did not focus, click, type, invoke UIA, queue bridge writes, close, restart, save, sync, reload, detach, upgrade, or modify the model
- `north-star-human-gate-packet --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-human-gate-packet-current` wrote `north_star_human_gate_packet.json` and `north_star_human_gate_packet.md`
- the packet includes the current manual gates, a structured `manual_completion_checklist`, approval-token commands, token verification commands, freshness rules, latest preflight readiness for approval items, blocked effects, and the post-human-action `north-star-resume-check` command; it is a handoff artifact only and executed nothing
- `north-star-approval-verify` task `live-north-star-approval-verify-safe-ribbon-20260513` matched the current safe ribbon approval item without executing it
- `north-star-approval-preflight --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` task `live-north-star-approval-preflight-context-guard-20260513` wrote stable `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` and `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md` after running generated dry-run commands with execution and approval-token flags stripped; result: `preflight_passed_count: 5`, `preflight_failed_count: 0`, `unsafe_preflight_count: 0`; the artifact records the expected Revit/title/view context and reports approval-readiness counts so passed dry-runs are not mistaken for approval-ready UI state
- `north-star-approval-preflight` task `live-north-star-freshness-preflight-20260513` refreshed stable preflight with `approval_preflight_freshness`, `ttl_seconds: 900`, `preflight_passed_count: 5`, `unsafe_preflight_count: 0`, and `ready_for_human_approval_count: 3`
- `north-star-ready-approvals` task `live-north-star-ready-approvals-token-summary-20260513` wrote `north_star_ready_approvals.json` and `.md`; result: `ready_approval_count: 3`, `withheld_approval_count: 2`, ready ids `safe-ribbon-view-tab`, `direct-uia-view-tab-select`, and `approved-workflow-open-sheet`, with context-menu items withheld because they require a UI state change or fresh prevalidation; ready items include token verification summaries, bound payload digests, and `may_execute_from_this_summary: false`
- `north-star-ready-approvals` task `live-north-star-ready-approvals-freshness-guard-20260513` reported `preflight_freshness_guard.status: fresh`, `ready_approval_count: 3`, `withheld_approval_count: 2`, and `may_execute_from_this_result: false`; stale preflight now withholds all ready execute lines in tests
- `north-star-next-approval` task `live-north-star-next-approval-freshness-guard-20260513` reported `status: approval_ready`, selected `safe-ribbon-view-tab`, carried `preflight_freshness_guard.status: fresh`, and kept `may_execute_from_this_result: false`
- `north-star-next-approval` task `live-north-star-next-approval-current-20260513` wrote `north_star_next_approval.json` and `.md`; result: `status: approval_ready`, selected item `safe-ribbon-view-tab`, `ready_approval_count: 3`, `deferred_ready_count: 2`, `may_execute_from_this_result: false`, and selected item `may_execute_from_this_item: false`
- `north-star-waiting-state` task `live-north-star-waiting-state-current-hint-20260513` wrote stable `NORTH_STAR_WAITING_STATE_CURRENT.json` and `NORTH_STAR_WAITING_STATE_CURRENT.md`; result: `status: waiting_for_human_or_real_condition`, `autonomous_progress_available: false`, `blocked_waiting_for_human_or_real_condition: true`, `required_human_approval_phrase: <redacted approval phrase>`, `may_execute_from_this_result: false`, and `may_execute_from_waiting_state: false`
- `north-star-blocked-ledger` task `live-north-star-current-handoff-with-dry-run-commands-20260513` wrote stable `NORTH_STAR_BLOCKED_LEDGER_CURRENT.json` and `NORTH_STAR_BLOCKED_LEDGER_CURRENT.md` with one entry per remaining blocked gate, approval-token verify commands, PowerShell-safe dry-run/preflight commands, PowerShell-safe human-reviewed execute commands for ready items, and withheld execute commands for items not marked ready by latest preflight
- `north-star-current-handoff` task `live-north-star-waiting-state-current-hint-20260513` wrote stable sandbox-root files `NORTH_STAR_APPROVAL_PLAN_CURRENT.json`, `NORTH_STAR_APPROVAL_PLAN_CURRENT.md`, `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`, `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md`, `NORTH_STAR_READY_APPROVALS_CURRENT.json`, `NORTH_STAR_READY_APPROVALS_CURRENT.md`, `NORTH_STAR_NEXT_APPROVAL_CURRENT.json`, `NORTH_STAR_NEXT_APPROVAL_CURRENT.md`, `NORTH_STAR_WAITING_STATE_CURRENT.json`, `NORTH_STAR_WAITING_STATE_CURRENT.md`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.json`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.md`, `NORTH_STAR_AUDIT_CURRENT.json`, `NORTH_STAR_AUDIT_CURRENT.md`, `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md`, `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`, `NORTH_STAR_COMPLETION_GATE_CURRENT.json`, `NORTH_STAR_COMPLETION_GATE_CURRENT.md`, and `NORTH_STAR_HANDOFF_CURRENT.json` / `NORTH_STAR_HANDOFF_CURRENT.md` with `status: blocked`, `ready_approval_count: 3`, `next_approval_item_id: safe-ribbon-view-tab`, `autonomous_progress_available: false`, `human_or_real_condition_required: true`, `blocked_waiting_for_human_or_real_condition: true`, `waiting_state.status: waiting_for_human_or_real_condition`, `waiting_state.required_human_approval_phrase: <redacted approval phrase>`, `waiting_state.may_execute_from_waiting_state: false`, and `may_call_update_goal: false`
- `north-star-current-handoff` task `live-north-star-current-handoff-with-gate-waiting-summary-20260513` refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*` so the hard gate itself includes current waiting-state and next-approval summaries, including `required_human_approval_phrase`, `selected_item_id: safe-ribbon-view-tab`, and `may_execute` fields that remain false
- `north-star-current-handoff` task `live-north-star-current-handoff-with-supervised-command-packet-20260513` refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*` so the hard gate also includes a supervised read-only command packet with exact preflight, phrase-verification, preview, resume-check, and completion-gate commands; the packet reports `execution_command_included: false` and `may_execute_from_this_packet: false`
- `north-star-current-handoff` task `live-north-star-current-handoff-with-final-supervised-readonly-script-20260513` wrote stable `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1`, refreshed `NORTH_STAR_COMPLETION_GATE_CURRENT.*` after the script existed, and the gate's stable artifact hints report the script present. PowerShell parser validation reported `parse_error_count: 0`; inspection found no literal `--execute` flag in the script.
- `north-star-current-handoff` task `live-north-star-current-handoff-with-human-phrase-param-script-20260513` refreshed the stable handoff after tightening the supervised read-only checker: `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` now requires `-HumanApprovalPhrase`, generated command arrays use `<HUMAN_APPROVAL_PHRASE>` as the placeholder, PowerShell parser validation reported `parse_error_count: 0`, inspection found no literal `--execute` flag, and the completion gate reports `phrase_must_be_supplied_by_human: true`, `auto_supplied_phrase_in_commands: false`, `execution_command_included: false`, and `may_execute_from_this_packet: false`
- A deliberate wrong-phrase run of `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1 -HumanApprovalPhrase "WRONG-PHRASE-FOR-FAIL-CLOSED-VALIDATION"` exited with code `1`, emitted the `HumanApprovalPhrase does not match` guard message, and did not print any `RUNNING READ-ONLY CHECK` lines, proving the checker stops before invoking even read-only commands when the human phrase is wrong
- Live read-only rechecks after the blocked gate confirmed no hidden unblocker was present: `status` task `live-status-recheck-after-blocked-gate-20260513` saw Revit 2025 idle on the detached copied model with active view `STARTING VIEW`, `list-dialogs` task `live-list-dialogs-recheck-after-blocked-gate-20260513` reported `count: 0`, `bridge-readiness` task `live-bridge-readiness-recheck-after-blocked-gate-20260513` still failed `loaded_build_current`, and `north-star-watch` task `live-north-star-watch-after-blocked-gate-20260513` reported `status: no_change`, `requires_revit_restart_or_reload: true`, `requires_recovery_attention: false`, and `dialog_count: 0`
- `north-star-next-human-action` task `live-north-star-next-human-action-current-refresh-20260513` wrote stable `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` and `.md`, refreshed stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*`, and reported `status: blocked_waiting_for_human_or_real_condition`, `completion_allowed: false`, `may_call_update_goal: false`, `may_execute_from_this_result: false`, with three human unblock options: safe human Revit restart/reload using the no-save checklist, exact human approval phrase for `safe-ribbon-view-tab`, and waiting for a real recovery condition; the refreshed completion gate's `next-human-action` stable artifact hint is present
- `north-star-current-handoff` task `live-north-star-current-handoff-with-safety-guard-20260513` now publishes the same `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` files as part of the standard stable handoff, refreshes the hard completion gate after the card exists, and leaves `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `may_execute_from_this_result: false`; the stable completion gate now parses the card into `next_human_action_summary` with option ids `human-restart-or-reload-revit`, `provide-exact-human-approval-phrase`, and `wait-for-real-recovery-condition`, reports `execution_authority_violation: false`, and reports `safety_guard_violations: []`
- `north-star-audit` task `live-north-star-audit-after-next-human-command-20260513` confirmed the expanded command checklist still has no missing commands, deliverables, prototype paths, live evidence tasks, or live evidence journals, while remaining `status: not_complete` because the same four human/real-condition gates are blocked
- Safety-guard tests now cover every handoff execution-authority source watched by the completion gate: waiting-state, next-approval, next-human-action, supervised packet execution authority, supervised packet execution command inclusion, supervised packet auto-supplied phrase, and missing human-phrase requirement; the targeted Revit operator slice reports `243 passed` with the known pytest cache warning
- `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` was parsed with PowerShell and returned `parse_error_count: 0`; executing it ran the repo-local read-only `north-star-resume-check` with task id `post-human-resume-check-current`, parsed the returned JSON completion gate, warned `NORTH STAR STILL BLOCKED: do not call update_goal`, listed blocked gates `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`, and failed safely on `loaded_build_current` and `bridge_readiness_ready`
- `north-star-approval-phrase-verify` task `live-north-star-approval-phrase-verify-no-approval-20260513` deliberately supplied a non-matching probe phrase, wrote `north_star_approval_phrase_verify.json` / `.md`, reported `status: no_match`, `phrase_matches_waiting_state: false`, `approval_validated_for_current_waiting_state: false`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`, proving the phrase verifier does not convert a probe into approval
- `north-star-approved-execution-preview` task `live-north-star-approved-execution-preview-no-approval-20260513` deliberately supplied a non-matching probe phrase, wrote `north_star_approved_execution_preview.json` / `.md`, reported `status: approval_not_validated`, empty `execute_command_preview`, empty `execute_powershell_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`, proving the preview command withholds execution text without the exact current phrase
- `north-star-approved-execution-preview` task `live-north-star-context-guard-preview-probe-20260513` deliberately supplied a non-approval phrase plus mismatched title context; it reported `context_guard.status: context_mismatch`, a mismatch on `expected_title_contains` against `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`, empty `execute_command_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`
- `north-star-approved-execution-preview` task `live-north-star-freshness-preview-probe-20260513` supplied a non-approval probe phrase against fresh matching context; it reported `preflight_freshness_guard.status: fresh`, `context_guard.status: context_matched`, empty `execute_command_preview`, `execution_by_this_command: false`, and `may_execute_from_this_result: false`
- `north-star-completion-gate` task `live-north-star-completion-gate-after-context-guard-20260513` remained blocked after the context-guard refresh, with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and blocked gates for human restart/reload, exact-approved live UI workflow coverage, real recovery evidence, and exact-approved live UIA/ribbon/context-menu coverage
- `north-star-completion-gate` task `live-north-star-completion-gate-after-freshness-guard-20260513` remained blocked after the freshness guard refresh, with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and no safety guard violations
- `north-star-completion-gate` task `live-north-star-completion-gate-after-ready-freshness-guard-20260513` remained blocked after ready/next approval freshness enforcement, with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and the same four human/real-condition blocked gates
- `north-star-completion-gate` artifact from task `live-north-star-completion-gate-after-preview-followup-20260513` wrote `north_star_completion_gate.json` with `status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, zero missing required evidence counts, blocked gates still listed, and stable artifact hints including ready approvals, next approval, and waiting state; approval-gated followups now include `north-star-approval-phrase-verify` and `north-star-approved-execution-preview`
- `north-star-completion-gate` task `live-north-star-completion-gate-after-human-phrase-param-script-20260513` refreshed the hard gate after the supervised-checker safety fix; result stayed `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, with blocked gaps `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`
- North-star completion audit succeeded:
  - `north-star-audit` task `live-north-star-audit` wrote `north_star_audit.json`
  - result: `status: not_complete`, `north_star_complete: false`, `implementation_package_complete: true`
  - missing commands and live evidence markers were empty
  - remaining gaps listed human-approved Revit restart/reload, broad approved live UI workflows, live stuck-state recovery drills, hours-long live supervision endurance, and approved live UIA/ribbon/context-menu method execution across real Revit surfaces
- Guarded UI workflow recipes succeeded:
  - `ui-workflows` task `live-ui-workflows-with-unsigned-addin` listed 10 planning-only recipes: unsigned add-in startup preflight, bridge readiness, Project Browser sheet navigation, Manage Links, Review Warnings, Visibility/Graphics, View Templates, context-menu inspection, modal-dialog recovery, and read-only QA
  - `ui-workflow-matrix` task `live-ui-workflow-matrix` validated 10 recipes and 38 steps with `failed_cases: []`, 7 approval-gated steps, 1 annotated manual placeholder, and 0 blocked steps
  - `ui-workflow-smoke-matrix` task `live-ui-workflow-smoke-matrix-2` ran 23 smoke-safe observation/planning steps across all 10 recipes with `failed_cases: []`, then stopped before approval-gated, manual-placeholder, blocked, or non-smoke-safe steps
  - `plan-ui-workflow --name project-browser-open-sheet --sheet-number S2.0` task `live-plan-ui-workflow-project-browser-with-ready` rendered a 4-step plan with read-only status, `wait-model-ready`, Project Browser planning, and approval-required `activate-view`
  - `plan-ui-workflow --name unsigned-addin-startup-preflight` task `live-plan-ui-workflow-unsigned-addin-startup` rendered a 4-step startup prompt plan with `list-dialogs`, `plan-current-dialog-response`, `addin-security-preflight`, and approval-required `click --target "Always Load"`
  - `plan-ui-workflow --name manage-links-inspection` task `live-plan-ui-workflow-manage-links` rendered a plan with blocked link actions and approval gates
  - no UI action, bridge command, save, sync, reload, close, or model modification was executed by the planner
- Guarded UI workflow runner succeeded:
  - `run-ui-workflow --name project-browser-open-sheet --sheet-number S2.0` task `live-run-ui-workflow-project-browser-with-ready` executed low-risk `status`, `wait-model-ready`, and `project-browser-plan-navigation`, captured fresh observations before each step, matched Project Browser OCR evidence with item bounds/confidence, and stopped before approval-required `activate-view`
  - `run-ui-workflow --name unsigned-addin-startup-preflight` task `live-run-ui-workflow-unsigned-addin-startup` executed low-risk `list-dialogs`, `plan-current-dialog-response`, and `addin-security-preflight`, then stopped before approval-required `click --target "Always Load"` because no exact approval token was supplied
  - `run-ui-workflow --name manage-links-inspection` task `live-run-ui-workflow-manage-links` executed low-risk `status` and `plan-ribbon-action`, then stopped before approval-required `ribbon-action`
  - no approval-gated UI action, bridge command, save, sync, reload, close, or model modification was executed
- Live replay dry-run succeeded:
  - `replay-workflow --name "Live Readonly QA Workflow" --max-steps 8` wrote `revit_operator_runs\live-replay-workflow-dry-run\workflow_replay_plan.json`
  - all eight steps received fresh Revit observations
  - observed Revit state was `idle` for each step
  - approval-required steps: 1 and 4 (`focus`)
  - non-executable report/workflow steps were skipped rather than replayed blindly
  - no step executed
- Live replay stop recovery succeeded:
  - `replay-workflow --name "Live Readonly QA Workflow" --execute --max-steps 2` wrote `revit_operator_runs\live-replay-recovery-stop\workflow_replay_result.json`
  - step 0 queued read-only `active-document`
  - step 1 stopped before approval-required `focus` because no fresh approval token was supplied
  - recovery snapshot: `revit_operator_runs\live-replay-recovery-stop\recovery_snapshot.json`
  - no UI action, save, sync, reload-links, close-model, detach command, upgrade command, or model-modifying bridge operation was executed
- Live Project Browser navigation planning succeeded:
  - `project-browser-plan-navigation --sheet-number S2.0 --tree-depth 3` wrote `revit_operator_runs\live-project-browser-navigation-plan\project_browser_navigation_plan.json`
  - Project Browser was observed and screenshotted
  - exactly one metadata-backed sheet match was found
  - recommended route was approval-gated `request-operation --operation activate-view` with args `{ "id": 712292, "sheet_number": "S2.0" }`
  - no Project Browser click, selection change, view activation, save, or sync was executed
- Live Project Browser navigation planning with OCR succeeded:
  - `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-plan-navigation-ocr` wrote `project_browser_navigation_plan.json`
  - Project Browser OCR/UIA evidence was captured while the route still preferred metadata-backed `activate-view`
  - no Project Browser click, selection change, view activation, save, or sync was executed
- Live Project Browser OCR line-match evidence succeeded:
  - `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-plan-navigation-ocr-evidence` returned `visual_evidence.ocr_match_count: 1`
  - OCR matched visible Project Browser line `S2.0_1_FOUNDATION PLAN` while still recommending the metadata-backed guarded `activate-view` route
  - no coordinate click, Project Browser activation, selection change, view activation, save, or sync was executed
- Live Project Browser OCR geometry evidence succeeded:
  - `project-browser-plan-navigation --sheet-number S2.0 --include-ocr --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-plan-navigation-ocr-geometry` returned `visual_evidence.ocr_item_count: 17` and one `ocr_item` match
  - matched text: `S2.0_1_FOUNDATION PLAN`
  - confidence: `0.979984616691416`
  - bounds: left `133.0`, top `193.0`, right `354.0`, bottom `214.0`, center `243.5,203.5`
  - the plan still recommended approval-gated metadata-backed `activate-view`; no coordinate click, selection change, view activation, save, or sync was executed
- Live Project Browser OCR visual-click planning succeeded:
  - `project-browser-plan-visual-activation --sheet-number S2.0 --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-visual-click-plan` found one OCR item match and produced a high-risk `visual-click` approval token
  - payload: hwnd `1379600`, window point `243.5,203.5`, screen point `251.5,1093.5`, target `S2.0_1_FOUNDATION PLAN`
  - `project-browser-visual-activate --sheet-number S2.0 --ocr-backend rapidocr --include-uia --tree-depth 4 --uia-limit 300` task `live-project-browser-visual-click-dry-run` remained `dry_run`, reported missing approval for the exact `visual-click`, and did not execute
  - no coordinate click, Project Browser activation, selection change, view activation, save, or sync was executed
- Live direct Project Browser activation planning failed closed:
  - `project-browser-plan-activation --name "S2.0" --max-depth 8 --limit 30` wrote `revit_operator_runs\live-project-browser-direct-activation-plan\project_browser_item_activation_plan.json`
  - Project Browser hwnd `1379600` was found
  - item-level UIA match count was 0, so `executable` was `false`
  - no Project Browser click, selection change, view activation, save, or sync was executed
- Live Properties palette snapshot succeeded:
  - `find-control --text "Properties" --max-depth 8 --limit 20` task `live-find-control-properties-before` matched two visible Properties controls and selected the top-level control for snapshotting
  - `properties-palette-snapshot --include-uia --include-ocr --ocr-backend rapidocr --tree-depth 4 --uia-limit 300` task `live-properties-palette-snapshot` wrote `properties_palette_snapshot.json`
  - selected hwnd: `15862206`
  - UIA node count: `22`
  - OCR result: `success: true`, `line_count: 23`, `item_count: 23`
  - OCR evidence included visible sheet properties such as `Sheet: STARTING VIEW`, `Visibility/Graphics ...`, `Scale`, `Sheet Number`, `Z`, `Sheet Name`, and `STARTING VIEW`
  - no field focus, typing, Apply click, selection change, save, sync, or model modification was executed
- No save, sync, reload-links, close-model, detach command, upgrade command, or model-modifying bridge operation was executed during this read-only validation.
- Direct safety gate checks succeeded:
  - `click --target Save` remained blocked by default.
  - `request-operation --operation save` failed without `--allow-model-write`.
  - `request-operation --operation sync --allow-model-write` failed without `--allow-sync`.
  - live `bridge\command_queue.jsonl` contained only `active-document` and `export-metadata`.
- Known-dialog rule checks now cover:
  - transmitted model startup prompt
  - unresolved references startup prompt
  - missing-link prompts
  - open-workset prompts
  - worksharing/central prompts
  - warning review and failure processing prompts
  - save-changes and export-output-path prompts
  - unsigned Hermes add-in startup prompt
- Dialog workflow matrix succeeded:
  - `dialog-workflow-matrix` task `live-dialog-workflow-matrix` validated 21 representative prompt workflow cases
  - result: `failed_cases: []`
  - checked that representative prompts classify to the expected known dialog id, include safe preflight commands, do not plan blocked-button clicks, require approval for every allowed-button plan, and leave human-only workflows without planned actions
  - no live Revit dialog button was clicked
- Ribbon action matrix succeeded:
  - `ribbon-action-matrix` task `live-ribbon-action-matrix` validated 24 named ribbon descriptors
  - result: `failed_cases: []`, `blocked_count: 7`, `approval_gated_count: 20`
  - checked locator presence, descriptions, safety reasons, approval-gated non-blocked descriptors, and explicitly blocked File/Save/Save As/Sync/Print/Export/Publish descriptors
  - no ribbon control was located, clicked, invoked, or focused
- Context-menu action matrix succeeded:
  - `context-menu-action-matrix` task `live-context-menu-action-matrix` validated 3 named context-menu descriptors and 4 representative menu item policies
  - result: `failed_descriptors: []`, `failed_items: []`, `blocked_descriptor_count: 1`, `approval_gated_descriptor_count: 2`
  - checked target locator coverage, descriptions, safety reasons, `right_click_input` use, blocked Save descriptor behavior, approval-gated non-blocked descriptors, and representative Properties/Delete/Save/Hide in View item policies
  - no context menu was opened and no menu item was selected

Final verification after code changes:

- Python syntax check passed for 35 Revit operator Python files plus the Hermes plugin wrapper.
- `python -m pytest -n 0 --basetemp .\.tmp-pytest-revit -q tests\tools\test_revit_operator.py tests\plugins\test_revit_operator_plugin.py` passed: 243 tests.
- Local HTTP control-server verification passed: `/health` returned service metadata, `/command` ran `known-dialogs` through the CLI dispatcher, and recursive `serve` was blocked.
- Hermes plugin wrapper verification passed: `revit_operator` registers under `plugin_revit_operator`, calls the CLI dispatcher, returns JSON, and blocks `serve`.
- MCP wrapper verification passed: `revit_operator_command` delegates to the same control dispatcher, returns structured JSON, blocks `serve` by command and argv, and `python -m tools.revit_operator.mcp_server --help` works. A real stdio MCP client smoke test discovered `revit_operator_health`, `revit_operator_commands`, and `revit_operator_command`, then called `known-dialogs` through `revit_operator_command` into a temp sandbox.
- UIA method verification passed: `uia-control-details` reports available methods, `uia-invoke --method select` uses an explicit method under the existing approval-gated primitive, `uia-method-matrix` covers all 10 allowlisted methods without live UI contact, and `project-browser-activate-item --method ...` carries the method into the guarded payload.
- Action approval matrix verification passed: representative dry-run primitive cases and classification-only bridge-operation cases preserve allow/approval/block decisions, exact approval tokens, critical risks where expected, artifact writing, and `executed_count: 0`.
- UI execution coverage audit verification passed: sandboxed journals are scanned read-only, synthetic/test/matrix/audit entries and dry-runs are excluded, qualifying executed UI actions are grouped by coverage surface, payload-marked ribbon/context-menu UIA executions are counted under their real surfaces, workflow execution coverage requires `approved_executed_steps`, and missing UIA/ribbon/context-menu/visual/workflow surfaces are reported fail-closed.
- Ribbon descriptor verification passed: common tab descriptors are listed, `ribbon-action-matrix` verifies every descriptor has locators/reasons and preserves approval/blocking policy, name-based command descriptors route through UIA accessible-name searches, `annotate-tab` dry-runs through the approval-gated UIA invoke path, and File/backstage/Print remain blocked even if UIA targets are found.
- OCR backend verification passed: health output covers Tesseract and RapidOCR backends, RapidOCR result parsing handles common output shapes including item geometry, `--backend` is exposed on `ocr-screenshot`, injected OCR execution remains testable, and live RapidOCR extraction succeeded on a Revit screenshot.
- Workflow recipe/state-predicate/parameterization verification passed: guarded UI workflow recipes render planning-only checklists with missing-parameter gates and approval steps; `ui-workflow-matrix` verifies every recipe has sample-covered parameters, blocked-action documentation, approval gates, no policy-blocked steps, approval tokens for gated steps, and annotated manual placeholders; `ui-workflow-smoke-matrix` runs only smoke-safe observation/planning prefixes and treats stale bridge-readiness diagnostics as nonfatal evidence; `run-ui-workflow` executes low-risk steps with fresh status observations, journals first/last observations for execution coverage audits, and stops before missing approval tokens, unexpected modal UI, manual placeholders, or blocked policies; recorded templates capture document/view/window/dialog context when available; action journals include bridge active-document context; parameter bindings are emitted for common payload fields; parameter overrides are reclassified before execution; `workflow-approval-plan` regenerates fresh tokens and blocks unsafe overrides; and replay stops before execution on active-document or modal-dialog mismatches.
- North-star audit verification passed: `north-star-audit` checks named deliverables, prototype paths, required commands, live evidence task markers, and evidence-based gap status from bridge readiness, live recovery snapshots, supervision endurance, and UI execution coverage artifacts; it preserves detailed endurance evidence including active/stale in-progress PID counts, reports per-gap blocker metadata for human-action, human-approval, real-condition, and time-gated gaps, publishes the aggregate `blocker_summary`, and emits `completion_actions` so Hermes can distinguish autonomous wait/progress from human or real-condition gates; recovery evidence is fail-closed and excludes synthetic/matrix artifacts and idle snapshots; `north-star-approval-plan` writes a read-only human handoff for the next guarded validation actions; `north-star-approval-preflight` runs approval dry-runs with execution and approval-token flags stripped and records expiring freshness metadata; `north-star-ready-approvals` writes only currently ready approval items with non-ready execute commands withheld; `north-star-approval-phrase-verify` checks exact waiting-state approval phrases without execution authority; `north-star-approved-execution-preview` withholds command previews unless phrase verification, token readiness, next selected item, requested Revit/title/view context, and unexpired preflight freshness all match the latest preflight; `north-star-approval-verify` explains supplied approval tokens without execution; `north-star-blocked-ledger` writes durable unresolved-gate JSON and Markdown entries; `north-star-current-handoff` writes stable current JSON/Markdown copies at the sandbox root; `north-star-completion-gate` runs a fresh audit and blocks completion while any requirement remains unverified or blocked; tests verify the audit writes a read-only artifact and does not mark the north star complete while gaps remain.
- North-star next-approval, waiting-state, phrase-verification, and execution-preview checks passed: `north-star-next-approval` selects one currently ready approval candidate, writes read-only JSON/Markdown, withholds deferred ready execute commands, publishes `NORTH_STAR_NEXT_APPROVAL_CURRENT.*` through the current handoff, and keeps `may_execute_from_this_result: false`; `north-star-waiting-state` publishes `NORTH_STAR_WAITING_STATE_CURRENT.*` with the exact required approval phrase, `preflight_freshness_guard`, and false execution flags; `north-star-approval-phrase-verify` matches only the exact current waiting-state phrase, rejects wrong phrases, hashes the supplied phrase in the journal, and keeps `may_execute_from_this_result: false`; `north-star-approved-execution-preview` shows the exact separate execution command only after phrase validation, context matching, and preflight freshness checks succeed, rejects wrong phrases and stale/mismatched preflight context, and keeps `may_execute_from_this_result: false`. Current-handoff tests also verify the stable handoff carries `autonomous_progress_available`, `human_or_real_condition_required`, `blocked_waiting_for_human_or_real_condition`, the underlying `completion_actions`, and a `waiting_state` with the exact required approval phrase and `preflight_freshness_guard` while keeping `may_execute_from_waiting_state: false`.
- Context-menu verification passed: descriptors list includes blocked Save surfaces, `context-menu-action-matrix` verifies descriptor and representative item policies without opening live menus, plans require an exact target, `context-menu-snapshot` writes read-only menu/menu-item evidence, `context-menu-action` dry-runs through `uia-invoke --method right_click_input`, `context-menu-select-item` dry-runs through exact `MenuItem` UIA invocation, and destructive menu items are blocked.
- Stalled-state supervision verification passed: repeated busy checks trigger `stalled_state_detected`, record hung-window evidence in `stall_analysis`, capture a read-only recovery snapshot with embedded dialog recovery plans when dialogs are present, and `recovery-drill-matrix` verifies conservative recovery recommendations for representative synthetic states.
- Supervision endurance verification passed: `supervision-endurance-matrix` runs the real supervision loop against synthetic observers and verifies resume/append, modal stop, busy stall recovery snapshot capture, unknown-state stall handling, incremental checkpoint writing with supervisor PID, artifact writing, and zero live Revit contact; `supervision-endurance-audit` verifies accumulated live supervision logs are measured against target hours/checks, overlapping intervals are not double-counted, active in-progress supervisor PID status is reported, and insufficient evidence is reported without polling Revit.
- Active supervision accounting verification passed: `supervision-endurance-audit` extends an in-progress interval only when the supervisor PID is confirmed running and the last checkpoint is within the active grace window; stale or PID-less logs are not inflated; the audit reports duration/checks remaining and an estimated duration target timestamp only when a PID-confirmed active interval is available.
- Model-ready verification passed: tests cover idle/non-modal active-document readiness, expected document/version/view predicates, modal stop behavior, and CLI output artifact creation.
- Dialog workflow verification passed: upgrade, reload-link, Manage Links, type catalog, Visibility/Graphics, View Template, missing-link, open-workset, worksharing/central, warning-review, failure-processing, save-changes, and export-output-path prompts produce no planned unsafe click while returning blocked-button and safe-preflight guidance for escalation.
- Dialog OCR fallback verification passed: tests cover OCR classification when modal dialog text is missing, OCR classification when no accessible dialog exists but status is modal, and refusal to classify OCR text as a dialog prompt when Revit is idle.
- Project Browser navigation and visual fallback verification passed: `project-browser-plan-navigation` writes a read-only plan, can include Project Browser OCR line/item match evidence with confidence and bounds, uses OCR as human-readable visual fallback evidence, and prefers the guarded `activate-view` bridge route for one exact metadata match. `project-browser-plan-visual-activation` converts one OCR item match into an approval-gated `visual-click` payload, and `project-browser-visual-activate` dry-runs without execution unless the exact token is supplied.
- Bridge-build/readiness verification passed: tests cover add-in status/heartbeat loading, active-document status embedding, CLI `bridge-status` output, `verify-bridge-build` success/stale result shapes, `bridge-readiness` manifest/DLL/loaded-payload gates, top-level readiness check counts and failed-check names, `bridge-restart-validation-plan` human handoff output, and `bridge-post-restart-validation` pass/fail output.
- `python -m tools.revit_operator.cli --help` listed the `serve`, `north-star-audit`, `north-star-approval-plan`, `north-star-approval-preflight`, `north-star-ready-approvals`, `north-star-next-approval`, `north-star-waiting-state`, `north-star-approval-phrase-verify`, `north-star-approved-execution-preview`, `north-star-approval-verify`, `north-star-blocked-ledger`, `north-star-current-handoff`, `north-star-completion-gate`, `bridge-status`, `bridge-readiness`, `bridge-restart-validation-plan`, `bridge-post-restart-validation`, `verify-bridge-build`, `wait-model-ready`, `addin-security-preflight`, `dialog-workflow-matrix`, `ribbon-action-matrix`, `context-menu-action-matrix`, `action-approval-matrix`, `ui-execution-coverage-audit`, `recovery-drill-matrix`, `supervision-endurance-matrix`, `supervision-endurance-audit`, `ui-workflow-matrix`, `ui-workflow-smoke-matrix`, `ui-workflows`, `plan-ui-workflow`, `run-ui-workflow`, `workflow-approval-plan`, Project Browser visual-click, `properties-palette-snapshot`, `context-menu-snapshot`, context-menu action, and context-menu item commands.
- Revit add-in source built successfully against Revit 2025 to `.tmp-revit-build-check` after adding loaded-build metadata; build result was 0 errors and 3 existing `Microsoft.VisualBasic` reference-conflict warnings from Revit API references.

## Manual Revit Validation Checklist

On native Windows with Revit 2025 and the copied local model:

- Build and install `HermesRevitOperator.dll`.
- Restart Revit and confirm `<sandbox>\bridge\addin_status.json` is written.
- Run `revit-operator bridge-status` and confirm the loaded add-in reports `source_capability_stamp: continuous-idling-status-file-retry-v2`, `supports_continuous_idling: true`, and the expected assembly path/last-write time.
- Run `revit-operator bridge-readiness` and confirm `ready_for_continuous_bridge: true`.
- Run `revit-operator verify-bridge-build` and confirm it returns `status: current`.
- Run `revit-operator bridge-post-restart-validation --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet` and confirm `validation_passed: true`.
- `revit-operator status` reports a Revit main window and state.
- `revit-operator list-dialogs` detects visible modal dialogs.
- Upgrade/detach/workset/link/warning/failure dialogs classify as high risk.
- `revit-operator open-model` dry-runs and then launches the copied model after approval.
- `revit-operator request-operation --operation active-document` writes bridge status.
- `revit-operator request-operation --operation export-metadata` writes metadata.
- Save requires exact token plus `--allow-model-write`.
- Sync requires exact token plus `--allow-model-write --allow-sync`.
- Generic `click --target Save` remains blocked.
- `revit-operator qa-report` writes a draft report under the sandbox.
- `journal.jsonl` contains each observation/action with risk and approval status.

## Remaining Gaps

- The add-in source now calls `IdlingEventArgs.SetRaiseWithoutDelay()` and writes loaded-build metadata, but the currently running Revit session loaded the previous DLL before these source changes. `bridge-readiness` now shows the source project, built DLL, and manifest are ready while `requires_revit_restart_or_reload` is true; `verify-bridge-build` still returns `stale_or_unverified`, and `bridge-post-restart-validation` fails safely on `loaded_build_current` and `bridge_readiness_ready`. Human-supervised restart/reload and then `bridge-post-restart-validation.validation_passed: true`, `bridge-readiness.ready_for_continuous_bridge: true`, and `verify-bridge-build.status: current` are required before relying on continuous polling without a focus/Escape nudge. The live sandbox also contains `REVIT_RESTART_RELOAD_NO_SAVE_CHECKLIST.md` to make the current dirty copied-model restart/reload gate explicit: Hermes must not choose save/sync options or answer a save-changes prompt.
- Direct Project Browser item activation is implemented as a guarded UIA primitive, but the current live Revit Project Browser does not expose item-level UIA rows for `S2.0`. Project Browser OCR line/item match geometry is available for human-readable fallback inspection and can now produce a high-risk approval-gated visual-click fallback plan/dry-run, but the current reliable safe navigation path is still metadata-backed `find-view` or `project-browser-plan-navigation` plus approval-gated `activate-view`.
- `replay-workflow` has unit coverage for recorded document/view/window/dialog predicates, guarded design, and recovery snapshots on stop, but still needs broader live validation across several real Revit UI workflows before it can close the reusable workflow replay gap.
- OCR engine execution is live-verified through RapidOCR on a Revit screenshot. Remaining OCR work is workflow integration for inaccessible dialogs and accuracy validation; Tesseract remains unavailable on this machine.
- Upgrade/detach/workset choices are not fully automated; they are supervised prompt workflows. Playbooks now expose blocked buttons and preflight evidence guidance, but live prompt action recipes still need broader validation.
- Sync has not been live-tested and should remain limited to copied/local test workflows until validated.
- It does not write to LucidLink, Autodesk Docs, cloud, central, or production paths by default.
- It provides CLI, local HTTP, Hermes plugin, and thin MCP stdio wrappers. The MCP wrapper has unit coverage plus real stdio MCP client smoke coverage for a read-only command.

## Prototype Milestone Gate

The current read-only prototype milestone is valid when:

- Python syntax checks pass.
- Focused tests pass.
- The add-in DLL builds against Revit 2025.
- The add-in manifest is installed for Revit 2025.
- Revit loads the add-in and writes bridge status.
- `bridge-readiness` proves the manifest/DLL/loaded bridge are aligned, and `verify-bridge-build` proves the loaded DLL reports the current source capability stamp and continuous-Idling flags, with `bridge-status` providing the raw assembly metadata.
- Revit UI status detects the process, main window, dialogs, and idle state.
- `ocr-screenshot` can capture screenshot evidence, choose `auto`/`tesseract`/`rapidocr` backends, execute RapidOCR when installed, and report OCR dependency gaps clearly.
- `uia-tree` can expose AutomationId/ControlType data when `pywinauto` is installed.
- `uia-find-control` can locate at least one known ribbon item by AutomationId without invoking it.
- `uia-control-details` can inspect available UIA action methods, `uia-method-matrix` can validate every allowlisted method policy without live UI contact, and `uia-invoke` can dry-run approval-required UIA actions, use an explicit approved method, and block dangerous UIA targets.
- `ui-execution-coverage-audit` can measure authorized live UI execution coverage and currently reports that approved live UIA/ribbon/context-menu/visual/workflow execution is still missing.
- `context-menu-action` can dry-run opening one exact context menu target through `right_click_input`, while blocked descriptors and dangerous targets remain non-executable.
- `context-menu-action-matrix` can validate context-menu descriptors and representative item policies read-only, with Save/Delete blocked and non-destructive items approval-gated.
- `context-menu-snapshot` can write read-only menu/menu-item evidence before any menu item selection is planned.
- `context-menu-select-item` can dry-run one exact menu item selection and blocks destructive item names by policy.
- `supervise-session` can poll the live Revit session, record state transitions/read-only bridge context, write a normal journal summary entry, detect repeated busy/unknown stalls, capture recovery evidence on stall, and resume/append the same supervision log by task id; `supervision-endurance-audit` can distinguish the current short live evidence from the remaining hours-long endurance requirement.
- `wait-model-ready` can verify idle, non-modal, active-document readiness with optional expected title/version/view predicates.
- `find-control` can locate at least one known visible Revit UI panel from the live Win32 tree.
- `project-browser-snapshot` can capture read-only Project Browser evidence from the located control hwnd, including optional OCR evidence.
- `project-browser-plan-navigation` can match requested sheet/view text against OCR lines/items and preserve OCR confidence/bounds for visual fallback evidence while still avoiding coordinate clicks.
- `project-browser-plan-visual-activation` and `project-browser-visual-activate` can convert one OCR item match into a high-risk `visual-click` dry-run with an exact approval token and no execution by default.
- `properties-palette-snapshot` can capture read-only Properties palette screenshot, UIA, and OCR evidence from the located control hwnd.
- Known startup dialogs classify to named reusable rules when recognized.
- Queued `active-document` writes `command_results.jsonl` and `active_document.json`.
- Queued `export-metadata` writes read-only sandbox metadata.
- `bridge-results` and `wait-bridge-result` can inspect add-in command completion.
- `recovery-snapshot` can capture a stuck-state evidence bundle without taking action, including conservative per-dialog recovery plans.
- `qa-workflow` can run a supervised read-only sequence and write metadata, UI evidence, and a draft report.
- A successful run can be recorded as a sandboxed workflow template without reusable approval tokens.
- Recorded workflow templates can be dry-run planned and guarded-replayed with fresh observation, recorded state predicates, parameter override reclassification, and fresh step approvals before any execution.
- `qa-report` writes a sandboxed draft report from live metadata.
- Save, sync, reload links, close model, detach, upgrade, and model-changing operations remain blocked or approval-gated.

## North-Star Completion Gate

The north-star Hermes Revit goal is not complete yet. It remains open until Hermes can operate Revit across real supervised tasks for extended periods, including robust Project Browser and ribbon workflows, known-dialog workflow memory, OCR and broader live UIA fallbacks, recovery from stuck states, reusable verified UI sequences, and safe composition of UI actions with API automation.

Latest live read-only refresh: `live-north-star-waiting-freshness-preflight-20260513` reported `status: preflighted`, `preflight_passed_count: 5`, `unsafe_preflight_count: 0`, `ready_for_human_approval_count: 3`, and `approval_preflight_freshness.ttl_seconds: 900`. `live-north-star-current-handoff-with-waiting-freshness-guard-20260513` refreshed stable `NORTH_STAR_WAITING_STATE_CURRENT.*` with `preflight_freshness_guard.status: fresh`, `may_execute_from_waiting_state: false`, and `may_execute_from_this_result: false`. `live-north-star-completion-gate-after-waiting-freshness-guard-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `safety_guard_violations: []`, and the same four blocked gates: `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`. This is progress evidence only; it is not completion authority.

Latest bridge-readiness reporting refresh: focused bridge-readiness tests passed (`8 passed, 231 deselected`) after adding top-level `check_count`, `passed_check_count`, `failed_check_count`, `passed_checks`, and `failed_checks`; the full Revit operator slice also passed (`243 passed`). Live read-only task `live-north-star-bridge-readiness-failed-checks-20260513` reported `status: not_ready`, `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, `check_count: 6`, `passed_check_count: 5`, `failed_check_count: 1`, and `failed_checks: ["loaded_build_current"]`. The follow-up hard gate task `live-north-star-completion-gate-after-bridge-readiness-summary-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `safety_guard_violations: []`, and the same four blocked gates. The clearer report does not change the gate state; it makes the human restart/reload blocker explicit.

Latest restart-context handoff refresh: focused next-human-action/current-handoff/completion-gate tests passed (`17 passed, 222 deselected`) after adding `restart_context` and `dirty_state_warning` to the human restart/reload option; the full Revit operator slice passed (`243 passed`). Read-only task `live-bridge-restart-validation-plan-restart-context-20260513` refreshed the no-save checklist from the current bridge heartbeat and active-document payload. Read-only task `live-north-star-next-human-action-current-restart-context-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with active document title/path, Revit 2025, active view `STARTING VIEW / DrawingSheet`, worksharing `enabled`, `dirty: true`, and an explicit warning that Hermes must not choose Save, Don't Save, or Cancel. Hard gate tasks `live-north-star-completion-gate-after-restart-context-20260513` and `live-north-star-completion-gate-after-restart-context-tests-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`.

Latest approval-freshness handoff refresh: focused next-human-action/current-handoff/completion-gate tests passed (`19 passed, 222 deselected`) and the full Revit operator slice passed (`245 passed`) after the human approval option was changed to prefer the latest stable approval preflight artifact over older waiting-state snapshots. Read-only task `live-north-star-next-human-action-preflight-freshness-source-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with `preflight_guard_source: latest_preflight_artifact`, `approval_preflight_status: preflight_stale`, `preflight_fresh_now: false`, and a warning that the approval phrase must not be used until `north-star-approval-preflight` is rerun and fresh. Hard gate tasks `live-north-star-completion-gate-after-approval-freshness-card-20260513` and `live-north-star-completion-gate-after-approval-freshness-tests-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`.

Latest completion-gate handoff summary refresh: focused completion-gate/next-human-action tests passed (`16 passed, 225 deselected`) and the full Revit operator slice passed (`245 passed`) after the hard completion gate summary was expanded to include compact next-human-action option details. Live read-only tasks `live-north-star-completion-gate-with-option-summaries-20260513` and `live-north-star-completion-gate-after-option-summary-tests-20260513` remained blocked but now expose the key human-gate facts directly in `north_star_completion_gate.json` and `.md`: restart option `dirty: true`, `dirty_state_warning_present: true`, approval option `preflight_guard_source: latest_preflight_artifact`, `approval_preflight_status: preflight_stale`, and `preflight_fresh_now: false`. This makes the completion gate itself a sufficient high-level hard stop without requiring the supervisor to open `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` for those details.

Latest stale-phrase withholding refresh: focused completion-gate/next-human-action tests passed (`16 passed, 225 deselected`) and the full Revit operator slice passed (`245 passed`) after the next-human-action approval option was changed to withhold the exact approval phrase whenever the latest approval preflight is not fresh. Live read-only task `live-north-star-next-human-action-withheld-stale-phrase-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with `Required phrase: WITHHELD_UNTIL_PREFLIGHT_FRESH`, a preflight refresh command, and no printed stale phrase. The follow-up hard gate tasks `live-north-star-completion-gate-after-withheld-stale-phrase-20260513` and `live-north-star-completion-gate-after-withheld-stale-phrase-tests-20260513` remained blocked and record `required_human_approval_phrase_withheld: true`, `approval_preflight_status: preflight_stale`, and `approval_preflight_command_present: true` in `next_human_action_summary.option_summaries`.

Latest fresh-preflight human-action refresh: after the user reiterated that the north-star goal is not complete while blocked, live read-only task `live-north-star-approval-preflight-refresh-after-goal-reminder-20260513` refreshed the approval preflight and reported `status: preflighted`, `preflight_passed_count: 5`, `preflight_failed_count: 0`, `unsafe_preflight_count: 0`, `ready_for_human_approval_count: 3`, and `approval_preflight_freshness.expires_at_utc: 2026-05-13T13:44:40Z`. Live read-only task `live-north-star-next-human-action-after-fresh-preflight-20260513` refreshed `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*`; its approval option reports `approval_preflight_status: fresh`, `preflight_fresh_now: true`, `required_human_approval_phrase_withheld: false`, `phrase_must_be_supplied_by_human: true`, and `may_execute_from_this_option: false`. The hard gate task `live-north-star-completion-gate-after-fresh-preflight-human-action-20260513` still reports `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`. A fresh approval packet is therefore only a current human handoff; it is not completion authority and it does not permit Hermes to execute any UI/model action unless the exact phrase is supplied by the human in chat and the separate verification/preview gates still pass.

Latest blocked-state audit/handoff refresh: live read-only task `live-north-star-audit-after-fresh-preflight-goal-continue-20260513` reported `status: not_complete`, `north_star_complete: false`, `blocked_gap_count: 4`, `cleared_gap_ids: ["supervision_endurance"]`, no autonomous completion path, and the remaining blockers `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`. Live read-only task `live-north-star-current-handoff-after-goal-continue-audit-20260513` republished the stable sandbox-root handoff files and still reported `status: blocked`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest current-handoff blocker summary refresh: `north-star-current-handoff` now publishes top-level `blocked_gap_ids` and `blocked_gate_count` fields, and `NORTH_STAR_WAITING_STATE_CURRENT.*` carries the same blocked IDs so Hermes does not have to infer unresolved gates from nested `completion_actions`. Focused current-handoff tests passed (`2 passed, 239 deselected`), the full Revit operator slice passed (`245 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-current-handoff-with-top-level-blocked-ids-20260513` reported `blocked_gap_ids: ["bridge_restart_validation", "live_ui_workflow_execution", "live_recovery_drills", "live_uia_ribbon_context_execution"]`, `blocked_gate_count: 4`, `completion_allowed: false`, and `may_call_update_goal: false`. The follow-up hard gate task `live-north-star-completion-gate-after-handoff-blocked-ids-20260513` remained blocked with the same four IDs and `safety_guard_violations: []`.

Latest current-handoff next-human-action summary refresh: `north-star-current-handoff` now embeds the compact next-human-action `option_ids` and `option_summaries` used by the hard completion gate, so the stable handoff identifies the available human unblock paths without requiring a second JSON read. Focused current-handoff tests passed (`2 passed, 239 deselected`), the full Revit operator slice passed (`245 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-current-handoff-with-next-human-summaries-20260513` refreshed `NORTH_STAR_HANDOFF_CURRENT.*` with option IDs `human-restart-or-reload-revit`, `provide-exact-human-approval-phrase`, and `wait-for-real-recovery-condition`; every option summary reports `may_execute_from_this_option: false`. The follow-up hard gate task `live-north-star-completion-gate-after-handoff-next-human-summaries-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`.

Latest dynamic approval-freshness gate refresh: the completion gate now recomputes latest approval-preflight freshness when summarizing both `NORTH_STAR_WAITING_STATE_CURRENT.json` and `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`, so stale stable artifacts cannot keep presenting an expired approval phrase as usable. Focused north-star gate/approval tests passed (`29 passed, 214 deselected`), the full Revit operator slice passed (`247 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only task `live-north-star-completion-gate-with-dynamic-waiting-freshness-20260513` reported `waiting_state_summary.preflight_guard_source: latest_preflight_artifact`, `waiting_state_summary.preflight_fresh_now: false`, `waiting_state_summary.required_human_approval_phrase: null`, `waiting_state_summary.required_human_approval_phrase_withheld: true`, `next_human_action_summary.option_summaries[provide-exact-human-approval-phrase].approval_preflight_status: preflight_stale`, `supervised_command_packet.available: false`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`.

Latest stale-approval-path visibility refresh: stale approval preflight no longer removes the human approval path from the next-human-action handoff. It stays visible as `provide-exact-human-approval-phrase`, but with `selected_item_id: null`, `required_human_approval_phrase_withheld: true`, `approval_preflight_status: preflight_stale`, and `may_execute_from_this_option: false`. Focused north-star gate/approval tests passed (`31 passed, 214 deselected`), the full Revit operator slice passed (`249 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live read-only tasks `live-north-star-current-handoff-stale-approval-path-visible-20260513` and `live-north-star-completion-gate-after-waiting-withheld-flag-fix-20260513` refreshed the stable handoff and hard gate; both remain blocked with the same four blocker IDs, `waiting_state_summary.required_human_approval_phrase: null`, `waiting_state_summary.required_human_approval_phrase_withheld: true`, `supervised_command_packet.available: false`, `completion_allowed: false`, `may_call_update_goal: false`, and `safety_guard_violations: []`.

Latest stale-approval credential leak fix: stable approval handoff artifacts now fail closed when the latest approval preflight is stale or missing freshness metadata. `NORTH_STAR_APPROVAL_PLAN_CURRENT.*`, `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.*`, and `NORTH_STAR_BLOCKED_LEDGER_CURRENT.*` keep dry-run/preflight guidance but withhold approval tokens, exact approval phrases, phrase-verification commands, execution previews, and executable PowerShell until a fresh preflight marks an item ready. Focused approval/handoff tests passed (`22 passed, 224 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), compileall passed for `tools/revit_operator` and `plugins/revit-operator`, and `git diff --check` passed for the touched files. Live read-only task `live-north-star-current-handoff-with-stale-approval-leak-fix-20260513` republished the stable handoff with the approval path visible but non-executable; a direct stable-file scan found no `APPROVE:`, exact approval phrases, or `Execute only after explicit approval` lines in the approval plan, human gate packet, blocked ledger, or ready-approvals files. The hard gate task `live-north-star-completion-gate-after-stale-approval-leak-fix-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `supervised_command_packet.available: false`, and `safety_guard_violations: []`.

Latest completion-audit hard-gate refresh: `north-star-completion-gate` now exposes top-level `blocked_gate_count` and a compact `completion_audit_summary` with the objective restatement, prompt-to-artifact checklist totals, missing counts, blocked gate count, and audit artifact paths. Focused audit/gate tests passed (`24 passed, 222 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), compileall passed, and `git diff --check` passed. Live task `live-north-star-completion-gate-with-audit-summary-20260513` reported `blocked_gate_count: 4`, `prompt_to_artifact_checklist_total_count: 124`, `prompt_to_artifact_checklist_satisfied_count: 114`, `prompt_to_artifact_checklist_unsatisfied_count: 10`, `completion_allowed: false`, and `may_call_update_goal: false`. Live task `live-north-star-current-handoff-with-completion-audit-summary-20260513` republished `NORTH_STAR_COMPLETION_GATE_CURRENT.*`; the stable Markdown now includes `Completion Audit Summary`, `blocked_gate_count: 4`, and `prompt_to_artifact_checklist_unsatisfied_count: 10`.

Latest unsatisfied-requirement summary refresh: `north-star-completion-gate` now includes `unsatisfied_requirement_summaries` in JSON and an `Unsatisfied Requirement Summaries` section in Markdown. The list names all 10 currently unsatisfied items directly: the four real gates (`bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, `live_uia_ribbon_context_execution`) plus six prompt/MVP requirements blocked by those gates. Focused audit/gate tests passed (`24 passed, 222 deselected`), the full Revit operator slice passed (`250 passed` with the known pytest cache warning), compileall passed, and `git diff --check` passed. Live tasks `live-north-star-completion-gate-with-unsatisfied-summaries-20260513` and `live-north-star-current-handoff-with-unsatisfied-summaries-20260513` refreshed the run and stable artifacts; `NORTH_STAR_COMPLETION_GATE_CURRENT.json` reports `unsatisfied_requirement_summaries.Count: 10`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest approval-preflight credential redaction refresh: `north-star-approval-preflight` now writes per-item approval readiness without exposing approval tokens or executable approval PowerShell in the stable preflight artifact. The completion gate also has an automated stale-approval credential leak guard that scans stable approval handoff artifacts when the latest preflight is stale or missing freshness, and fails completion if stale artifacts expose `APPROVE:` tokens, exact approval phrases, executable preview text, or executable approval PowerShell. Focused approval/gate tests passed (`25 passed, 223 deselected`), the full Revit operator slice passed (`252 passed` with the known pytest cache warning), compileall passed for `tools/revit_operator` and `plugins/revit-operator`, and `git diff --check` passed. Live read-only task `live-north-star-approval-preflight-redacted-credentials-20260513` refreshed `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.*` with `preflight_passed_count: 5`, `preflight_failed_count: 0`, `unsafe_preflight_count: 0`, `ready_for_human_approval_count: 3`, `requires_state_change_count: 1`, and `requires_prevalidation_count: 1`; a direct scan of the stable preflight JSON/Markdown found no `APPROVE:`, exact approval phrase, `Execute only after explicit approval`, or executable approval PowerShell patterns. The hard gate task `live-north-star-completion-gate-after-preflight-redaction-20260513` remained blocked with `blocked_gate_count: 4`, `prompt_to_artifact_checklist_total_count: 124`, `prompt_to_artifact_checklist_satisfied_count: 114`, `prompt_to_artifact_checklist_unsatisfied_count: 10`, `safety_guard_violations: []`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`. Live handoff task `live-north-star-current-handoff-after-preflight-redaction-20260513` republished the stable current files with the same four blockers.

Latest continuation recheck: `status` task `live-status-refresh-continuation-20260513` observed Revit idle on the copied detached Revit 2025 model, active view `STARTING VIEW / DrawingSheet`, `dirty: true`, and bridge heartbeat/document files updating. `list-dialogs` task `live-list-dialogs-refresh-continuation-20260513` reported `count: 0`. `bridge-readiness` task `live-bridge-readiness-refresh-continuation-20260513` still reported `ready_for_continuous_bridge: false`, `requires_revit_restart_or_reload: true`, and failed check `loaded_build_current`. The hard gate task `live-north-star-completion-gate-continuation-recheck-20260513` remained blocked with the same four blocker IDs, `blocked_gate_count: 4`, 10 unsatisfied requirements, `safety_guard_violations: []`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`. `north-star-next-human-action` task `live-north-star-next-human-action-continuation-recheck-20260513` and `north-star-current-handoff` task `live-north-star-current-handoff-continuation-recheck-20260513` republished the stable handoff; the only available unblock paths remain human restart/reload, exact current human approval, or a real recovery condition.

Latest bridge checklist context fix: the no-save restart checklist now normalizes the live nested active-document bridge payload before rendering observed document fields. Focused bridge restart plan tests passed (`3 passed, 246 deselected`), and the full Revit operator slice passed (`253 passed` with the known pytest cache warning). Live read-only task `live-bridge-restart-validation-plan-nested-doc-fix-20260513` regenerated `bridge_restart_no_save_checklist.md` with title `24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM_detached`, Revit version `2025`, active view `STARTING VIEW / DrawingSheet`, and `dirty: True`. Live handoff task `live-north-star-current-handoff-after-nested-doc-checklist-fix-20260513` republished `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`; a direct scan found no `(unknown)` document fields or `dirty: None`. The hard gate task `live-north-star-completion-gate-after-nested-doc-checklist-fix-20260513` remained blocked with the same four blocker IDs, `blocked_gate_count: 4`, `safety_guard_violations: []`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest approval-expiry safety refresh: after the previous approval preflight expired at `2026-05-13T14:36:13Z`, the hard gate task `live-north-star-completion-gate-after-approval-expiry-recheck-20260513` correctly reported `preflight_fresh_now: false`, withheld the waiting-state approval phrase, disabled the supervised command packet, and raised stale-approval credential leak violations against older persistent approval handoff artifacts. Running `north-star-current-handoff` task `live-north-star-current-handoff-after-approval-expiry-redaction-20260513` regenerated the persistent approval plan, human packet, and blocked ledger files with credentials withheld. A direct scan of those stable JSON/Markdown files found no `APPROVE:`, exact approval phrase, `Execute only after explicit approval`, or executable approval PowerShell patterns. The follow-up hard gate task `live-north-star-completion-gate-after-approval-expiry-redaction-20260513` returned `safety_guard_violations: []` while still reporting `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, and the same four blocked gates.

Latest broad stable-redaction regression: the stale-credential handoff test now scans all persistent approval-facing stable artifacts, including approval plan, ready approvals, next approval, waiting state, next-human-action, completion gate, human packet, blocked ledger, and top-level handoff JSON/Markdown, and asserts that stale-preflight output contains no `APPROVE:`, exact approval phrases, or explicit approval execute instructions. Focused test `current_handoff_withholds_stale_approval_credentials` passed (`1 passed, 248 deselected`), the full Revit operator slice passed (`253 passed` with the known pytest cache warning), and compileall passed. A live broad scan across the current stable files found no token/phrase/executable approval patterns, and hard gate task `live-north-star-completion-gate-after-broad-stable-redaction-test-20260513` still reports `safety_guard_violations: []`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest hard-gate stale-scan scope refresh: `_stale_approval_credential_leak_violations` now includes the stable completion gate, top-level handoff, and supervised read-only checker script in its built-in stale-preflight scan, matching the broader live stable artifact surface. Focused completion-gate safety tests passed (`3 passed, 247 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live hard gate task `live-north-star-completion-gate-after-expanded-stale-scan-scope-20260513` still reports `safety_guard_violations: []`, `blocked_gate_count: 4`, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest safety-remediation follow-up refresh: `north-star-completion-gate` now emits `safety_guard_followup_actions` when the hard gate detects stale approval credentials, unreadable stale approval artifacts, or stable artifacts claiming execution authority. The Markdown includes a `Safety Guard Follow-Up Actions` section so the next safe remediation command is visible alongside the violation. Focused completion-gate tests passed (`15 passed, 235 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live hard gate task `live-north-star-completion-gate-with-safety-remediation-actions-20260513` reported no current safety violations, `safety_guard_followup_actions: []`, and the same blocked north-star state: `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest supervised read-only checker approval-validation refresh: the stable supervised checker now fails closed unless `approval_phrase_verify` has validated the current waiting state and `approved_execution_preview` has produced a `preview_ready` packet for that same current human phrase. Focused current-handoff supervised-checker tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live current handoff task `live-north-star-current-handoff-with-supervised-preview-validation-20260513` remained blocked with the four unresolved gates. Live hard gate task `live-north-star-completion-gate-after-supervised-preview-validation-20260513` reported `status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `safety_guard_violations: []`, and `safety_guard_followup_actions: []`. A broad scan of the current stable approval-facing artifacts, including `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1`, found no approval token, exact approval phrase, executable approval instruction, or executable approval PowerShell patterns. Because the current approval preflight is stale, the supervised checker remains unavailable rather than carrying stale execution authority.

Latest audit top-level blocker field refresh: `north-star-audit` now publishes top-level `blocked_gap_ids`, `blocked_gap_count`, `cleared_gap_ids`, `cleared_gap_count`, `autonomous_progress_available`, `human_or_real_condition_required`, and `may_call_update_goal` fields that mirror the nested blocker and completion-action sources of truth. Focused audit tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live read-only audit task `live-north-star-audit-top-level-blocker-fields-20260513` reported `status: not_complete`, `north_star_complete: false`, `blocked_gap_count: 4`, blocked gaps `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`, `cleared_gap_ids: ["supervision_endurance"]`, `autonomous_progress_available: false`, `human_or_real_condition_required: true`, and `may_call_update_goal: false`. Live handoff task `live-north-star-current-handoff-after-audit-top-level-fields-20260513` republished stable `NORTH_STAR_AUDIT_CURRENT.json` with those same top-level fields and stable `NORTH_STAR_HANDOFF_CURRENT.json` with `blocked_gate_count: 4`.

Latest current-handoff count-alias refresh: `north-star-current-handoff` and `NORTH_STAR_WAITING_STATE_CURRENT.*` now publish `blocked_gap_count` alongside the existing `blocked_gate_count` so simple selectors can read the same blocker count used by the audit artifact. Focused current-handoff tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live handoff task `live-north-star-current-handoff-blocked-gap-count-alias-20260513` reported `blocked_gap_count: 4`, `blocked_gate_count: 4`, and the same four blocked gap IDs. The stable waiting-state JSON also reported both counts as `4` with `may_execute_from_waiting_state: false`. The hard gate task `live-north-star-completion-gate-after-handoff-gap-count-alias-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `safety_guard_violations: []`, and `safety_guard_followup_actions: []`.

Latest completion-gate count-alias refresh: `north-star-completion-gate` now publishes `blocked_gap_count` beside `blocked_gate_count` in both the top-level gate result and `completion_audit_summary`, with Markdown showing both counts. Focused completion-gate tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live hard gate task `live-north-star-completion-gate-blocked-gap-count-alias-20260513` reported both counts as `4`, no safety guard violations, and no completion authority. Live handoff task `live-north-star-current-handoff-after-gate-gap-count-alias-20260513` republished stable `NORTH_STAR_COMPLETION_GATE_CURRENT.*`; the stable JSON and Markdown now show `blocked_gap_count: 4`, `blocked_gate_count: 4`, the same four blocked gap IDs, `north_star_complete: false`, `completion_allowed: false`, and `may_call_update_goal: false`.

Latest status top-level blocker field refresh: `north-star-status` remains non-authoritative for completion, but now exposes top-level `blocked_gap_ids`, `blocked_gap_count`, `cleared_gap_ids`, `cleared_gap_count`, `remaining_gap_count`, `autonomous_progress_available`, and `human_or_real_condition_required` so lightweight status checks match the audit/gate/handoff surfaces. Focused status tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live status task `live-north-star-status-top-level-blocker-fields-20260513` reported `status: not_complete`, `north_star_complete: false`, `completion_gate_required: true`, `blocked_gap_count: 4`, `cleared_gap_count: 1`, `autonomous_progress_available: false`, and `human_or_real_condition_required: true`. The hard gate task `live-north-star-completion-gate-after-status-top-level-fields-20260513` remained blocked with the same four blocked gap IDs and no safety guard violations.

Latest next-human-action blocker count refresh: `north-star-next-human-action` now publishes `blocked_gap_count` and `blocked_gate_count` at the top level, in its nested completion-gate reference, in the stable Markdown, and in the hard gate's `next_human_action_summary`. Focused next-human-action tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live next-human task `live-north-star-next-human-action-blocker-counts-20260513` reported `status: blocked_waiting_for_human_or_real_condition`, `blocked_gap_count: 4`, `blocked_gate_count: 4`, `may_execute_from_this_result: false`, and the same four blocked gap IDs. The follow-up hard gate `live-north-star-completion-gate-after-next-human-counts-20260513` remained blocked with `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, no safety guard violations, and `next_human_action_summary.execution_authority_violation: false`.

Latest blocked-ledger blocker count refresh: `north-star-blocked-ledger` now publishes `blocked_gap_ids`, `blocked_gap_count`, and `blocked_gate_count`, and renders those counts plus a `Blocked Gap IDs` section in Markdown. Focused blocked-ledger tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live ledger task `live-north-star-blocked-ledger-blocker-counts-20260513` reported `entry_count: 4`, `blocked_gap_count: 4`, `blocked_gate_count: 4`, and the same four blocked gap IDs. Live handoff task `live-north-star-current-handoff-after-ledger-counts-20260513` republished stable `NORTH_STAR_BLOCKED_LEDGER_CURRENT.*` with the same counts, and hard gate `live-north-star-completion-gate-after-ledger-counts-20260513` stayed blocked with no safety guard violations.

Latest human-gate packet blocker field refresh: `north-star-human-gate-packet` now mirrors the top-level blocker fields from `north-star-status`, including `blocked_gap_ids`, `blocked_gap_count`, `cleared_gap_ids`, `cleared_gap_count`, `remaining_gap_count`, `autonomous_progress_available`, and `human_or_real_condition_required`, and its Markdown includes a `Blocked Gap IDs` section. Focused human-gate/stale-redaction tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live packet task `live-north-star-human-gate-packet-blocker-fields-20260513` reported four blocked gaps, one cleared gap, no autonomous progress, and no completion authority. Live handoff task `live-north-star-current-handoff-after-human-packet-fields-20260513` republished stable `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.*` with those fields, and hard gate `live-north-star-completion-gate-after-human-packet-fields-20260513` remained blocked with no safety guard violations.

Latest approval-plan blocker field refresh: `north-star-approval-plan` now publishes top-level `blocked_gap_ids`, `blocked_gap_count`, `blocked_gate_count`, `cleared_gap_ids`, `cleared_gap_count`, `autonomous_progress_available`, and `human_or_real_condition_required`, and its Markdown renders the same counts. Focused approval-plan tests passed (`2 passed, 248 deselected`), the full Revit operator slice passed (`254 passed` with the known pytest cache warning), and compileall passed. Live approval-plan task `live-north-star-approval-plan-blocker-fields-20260513` reported four blocked gaps, one cleared gap, no autonomous progress, and human/real-condition requirements. Live handoff task `live-north-star-current-handoff-after-approval-plan-fields-20260513` republished stable `NORTH_STAR_APPROVAL_PLAN_CURRENT.*` with those fields, and hard gate `live-north-star-completion-gate-after-approval-plan-fields-20260513` remained blocked with no safety guard violations.

Latest stable status redaction refresh: `north-star-status` now writes JSON plus Markdown while withholding approval tokens and executable approval flags from its approval-candidate summary. `north-star-current-handoff` publishes `NORTH_STAR_STATUS_CURRENT.json` and `NORTH_STAR_STATUS_CURRENT.md`, and the hard completion gate includes the status summary in stable artifact hints, stale-credential scanning, and a permanent status-only execution-leak guard. Focused status/current-handoff/guard tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff tasks `live-north-star-current-handoff-with-stable-status-redacted-20260513` and `live-north-star-current-handoff-with-status-hard-gate-guard-20260513` republished the stable status files with four blocked gaps and no approval credential or execute-command exposure. Direct global and status-only scans found no approval token, exact approval phrase, explicit execute-after-approval instruction, executable approval PowerShell, or status-only `--execute`/approval-token flags. Hard gates `live-north-star-completion-gate-after-stable-status-redaction-20260513` and `live-north-star-completion-gate-after-status-hard-gate-guard-20260513` remained blocked with no safety guard violations and no completion authority.

Latest unsatisfied-requirement reason refresh: `north-star-completion-gate` now derives a non-empty `reason` for each `unsatisfied_requirement_summaries` item and includes `blocked_by_gap_ids` where prompt requirements are blocked by live gates. Focused completion-gate tests passed (`1 passed, 250 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff task `live-north-star-current-handoff-with-unsatisfied-reasons-20260513` and hard gate `live-north-star-completion-gate-with-unsatisfied-reasons-20260513` refreshed `NORTH_STAR_COMPLETION_GATE_CURRENT.*`; all 10 unsatisfied summaries now have reasons, the Markdown renders `Reason:` lines, and the gate remains blocked with four blockers, no safety guard violations, and no completion authority.

Latest status/audit count-alias refresh: `north-star-status` and `north-star-audit` now publish top-level `blocked_gate_count` alongside `blocked_gap_count`, and both Markdown summaries render the alias. Focused status/audit/current-handoff tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-status-audit-gate-count-alias-20260513` and hard gate `live-north-star-completion-gate-after-status-audit-gate-count-alias-20260513` refreshed stable current artifacts; `NORTH_STAR_STATUS_CURRENT.*`, `NORTH_STAR_AUDIT_CURRENT.*`, `NORTH_STAR_COMPLETION_GATE_CURRENT.*`, `NORTH_STAR_HANDOFF_CURRENT.*`, `NORTH_STAR_BLOCKED_LEDGER_CURRENT.*`, and `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` now all report `blocked_gate_count: 4`, while completion remains blocked with no safety guard violations.

Latest status/audit completion-authority refresh: `north-star-status` and `north-star-audit` now publish explicit `completion_allowed: false` while still pointing final completion authority to `north-star-completion-gate`. Focused status/audit tests passed (`4 passed, 247 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-status-audit-completion-allowed-20260513` and hard gate `live-north-star-completion-gate-after-status-audit-completion-allowed-20260513` refreshed stable current artifacts; status, audit, completion gate, handoff, blocked ledger, and next-human-action now all expose `completion_allowed: false`, `blocked_gap_count: 4`, and `blocked_gate_count: 4`, and completion remains blocked with no safety guard violations.

Latest legacy blocked-handoff remediation: `north-star-current-handoff` now overwrites legacy `NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json` and `.md` with a deprecated, redacted, non-executable tombstone before any downstream completion-gate scan runs, and the hard gate includes those legacy filenames in stale-credential scanning. Stale-credential violations now record artifact and line numbers without copying credential-bearing line text into new artifacts. Focused handoff/credential/status tests passed (`9 passed, 242 deselected`), the full Revit operator slice passed (`255 passed` with the known pytest cache warning), and compileall passed. Live handoff `live-north-star-current-handoff-with-legacy-blocked-handoff-redacted-flag-20260513` and hard gate `live-north-star-completion-gate-after-legacy-blocked-handoff-redacted-flag-20260513` refreshed stable current artifacts; a broad scan of `NORTH_STAR_*CURRENT*` files found no approval tokens, exact approval phrases, executable approval instructions, or executable approval PowerShell patterns, and completion remains blocked with no safety guard violations.

Latest handoff safety-artifact linkage refresh: `north-star-current-handoff` now links existing `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.*` and `NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` files in `stable_files` so the top-level current handoff exposes the safety artifacts used by the hard gate. Focused current-handoff/stable-scan tests passed (`14 passed, 254 deselected`), the full Revit operator/plugin slice passed (`272 passed`), and compileall passed. Live read-only watch task `live-north-star-watch-refresh-after-handoff-safety-links-20260513` refreshed preflight and republished the current handoff; `NORTH_STAR_HANDOFF_CURRENT.json` reports all four safety-artifact links present with `stable_file_count: 33`. Live stable scan `live-north-star-stable-artifact-scan-after-handoff-safety-links-20260513` reported `status: clean`, `violation_count: 0`, `handoff_reference_violation_count: 0`, `reference_count: 33`, `present_count: 33`, and `missing_count: 0`. Live hard gate `live-north-star-completion-gate-after-handoff-safety-links-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest first-run watch handoff refresh fix: `north-star-watch --publish-current-handoff` now refreshes the current handoff again after writing `north-star-unblock-readiness`, then runs the final hard completion gate. This preserves the post-preflight handoff alignment while ensuring a fresh sandbox handoff links newly created `NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` safety artifacts before gate evaluation. Focused watch/current-handoff/stable-scan/gate tests passed (`41 passed, 227 deselected`), the full Revit operator/plugin slice passed (`272 passed`), and compileall passed. Live read-only watch `live-north-star-watch-refresh-after-post-unblock-handoff-20260513` reported `current_handoff_refresh.refresh_count: 2`, `post_unblock_refresh_ran: true`, no execution authority, and a blocked final hard gate. Live stable scan `live-north-star-stable-artifact-scan-after-post-unblock-handoff-20260513` stayed clean with `reference_count: 33`, `present_count: 33`, `missing_count: 0`, and `violation_count: 0`. Live hard gate `live-north-star-completion-gate-after-post-unblock-handoff-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest execution-authority key guard: stable artifact consistency now treats any JSON key beginning with `may_execute` as execution authority, not only the older enumerated fields. This catches future fields such as `may_execute_from_this_item`, `may_execute_from_this_option`, and `may_execute_from_this_summary` before they can appear as `true` in stable handoff artifacts. Focused execution-authority tests passed (`11 passed, 258 deselected`), the stable-scan/completion-gate/current-handoff slice passed (`36 passed, 233 deselected`), the full Revit operator/plugin slice passed (`273 passed`), and compileall passed. Live stable scan `live-north-star-stable-artifact-scan-after-exec-authority-key-guard-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment_violation_count: 0`, `unblock_refresh_command_violation_count: 0`, and `may_call_update_goal: false`. Live hard gate `live-north-star-completion-gate-after-exec-authority-key-guard-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest dynamic execution-authority artifact guard: stable artifact consistency now scans every sandbox-root `NORTH_STAR_*CURRENT*.json` file, not only the historical fixed artifact list, for execution-authority keys. Values are fail-closed: a present `may_execute*`, `execution_by_this_command`, `execution_command_included`, or `execution_authority_violation` key is acceptable only when its value is explicitly `false` or `null`; stringified booleans and other non-false values are violations. Focused dynamic execution-authority tests passed (`4 passed, 267 deselected`), the stable-scan/completion-gate/current-handoff slice passed (`38 passed, 233 deselected`), the full Revit operator/plugin slice passed (`275 passed`), and compileall passed. Live stable scan `live-north-star-stable-artifact-scan-after-dynamic-exec-authority-guard-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment_violation_count: 0`, `unblock_refresh_command_violation_count: 0`, and `may_call_update_goal: false`. Live hard gate `live-north-star-completion-gate-after-dynamic-exec-authority-guard-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest dynamic fresh-preflight alignment guard: stable artifact alignment now keeps the fixed approval-facing handoff list but appends future sandbox-root `NORTH_STAR_*CURRENT*` files unless they are known credential-free/non-approval diagnostics such as status, audit, stable-scan output, legacy tombstones, restart checklists, or post-human resume scripts. A future approval-facing current artifact older than a fresh `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` is now flagged before approval phrases can be requested or used. Focused alignment tests passed (`5 passed, 268 deselected`), the stable-scan/completion-gate/current-handoff slice passed (`40 passed, 233 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live read-only watch `live-north-star-watch-refresh-after-dynamic-preflight-alignment-20260513` refreshed preflight to `2026-05-13T18:33:00Z`, republished the current handoff twice, and kept the hard gate blocked. Live stable scan `live-north-star-stable-artifact-scan-after-dynamic-preflight-alignment-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment.checked_artifact_count: 21`, `preflight_alignment.stale_artifact_count: 0`, and `unblock_refresh_command_violation_count: 0`. Live hard gate `live-north-star-completion-gate-after-dynamic-preflight-alignment-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest stale approval flag leak guard: stale-preflight approval artifact scanning now flags raw `--execute`, `--approval-token`, and `--approval-tokens-json` flags in addition to approval tokens, exact approval phrases, execute-after-approval instructions, and `execute_powershell` fields. Violation records still redact matching line text instead of copying sensitive stale approval material into new artifacts. Focused stale checks passed (`3 passed, 270 deselected`), the stable-scan/completion-gate/current-handoff/stale-approval slice passed (`42 passed, 231 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live stable scan `live-north-star-stable-artifact-scan-after-stale-approval-flag-guard-20260513` reported `status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`, `preflight_alignment_violation_count: 0`, `unblock_refresh_command_violation_count: 0`, and `may_call_update_goal: false`. Live hard gate `live-north-star-completion-gate-after-stale-approval-flag-guard-20260513` remained blocked with `blocked_gate_count: 4`, `unsatisfied_count: 10`, `completion_allowed: false`, `may_call_update_goal: false`, and zero safety guard violations.

Latest direct hard-gate stable publishing: a direct `north-star-completion-gate` run now publishes `NORTH_STAR_COMPLETION_GATE_CURRENT.*` and `NORTH_STAR_AUDIT_CURRENT.*` from the fresh run instead of relying on watch/resume/current-handoff paths to refresh those stable files later. Focused hard-gate tests passed (`18 passed, 255 deselected`), the stable-scan/completion-gate/current-handoff/watch/resume slice passed (`44 passed, 229 deselected`), the full Revit operator/plugin slice passed (`277 passed`), and compileall passed. Live hard gate `live-north-star-completion-gate-with-direct-stable-publish-20260513` wrote `stable_current_files` with completion gate and audit files, left `completion_allowed: false` and `may_call_update_goal: false`, and updated `NORTH_STAR_COMPLETION_GATE_CURRENT.json` to point at that fresh run. Follow-up stable scan `live-north-star-stable-artifact-scan-after-direct-gate-stable-publish-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment_violation_count: 0`, `unblock_refresh_command_violation_count: 0`, `blocked_gate_count: 4`, and `unsatisfied_count: 10`.

Latest unverified add-in prompt guard: unsigned add-in classification now also catches "publisher could not be verified" startup wording. Verified Hermes add-in prompts still plan only an approval-gated `Always Load` click after `addin-security-preflight`; unknown add-in prompts classify as `unsigned-addin-unknown`, block `Always Load`, `Load Once`, and `Do Not Load`, and plan no click. Focused dialog tests passed (`5 passed` and `8 passed` slices), the full Revit operator/plugin slice passed (`279 passed`), and compileall passed. Live dialog matrix task `live-dialog-workflow-matrix-unverified-addin-guard-20260513` passed with 22 representative cases and confirmed the unknown add-in case has no planned action. After a read-only watch preflight/handoff refresh, live hard gate `live-north-star-completion-gate-after-unverified-addin-refresh-20260513` remained blocked with four blockers, ten unsatisfied requirements, no safety guard violations, and no completion authority; live stable scan `live-north-star-stable-artifact-scan-after-unverified-addin-refresh-20260513` stayed clean with zero violations.

Latest agent stop-status boundary guard: `north-star-agent-stop-status` publishes `NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` / `.md` as a read-only stop marker for Hermes, and `north-star-stable-artifact-scan` now verifies that marker against the hard `NORTH_STAR_COMPLETION_GATE_CURRENT.json` boundary. The scan flags drift if the stop-status file claims completion, autonomous progress, execution authority, mismatched blocker counts, mismatched blocker IDs, or leaked approval material while the hard gate remains blocked. Focused stop-status/stable-scan tests passed (`5 passed`), the full Revit operator slice passed (`369 passed` with the known pytest cache warning), plugin tests passed (`6 passed`), and compileall passed for `tools/revit_operator` and `plugins/revit-operator`. Live stable scan `live-stable-scan-after-agent-stop-boundary-guard-20260514` reported `status: clean`, `violation_count: 0`, and `agent_stop_status_boundary_violation_count: 0`. The follow-up hard gate `live-completion-gate-after-agent-stop-boundary-guard-20260514` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`, `unsatisfied_count: 17`, and no safety guard violations. This confirms the stop-status file is a safe pause/handoff artifact, not completion authority.

Latest read-only handoff refresh after continuing the active goal: `north-star-watch --refresh-approval-preflight --publish-current-handoff --checks 1 --poll 0` task `live-north-star-watch-refresh-preflight-after-continue-20260514` observed Revit 2025 idle on the copied detached model, found zero dialogs, refreshed the approval preflight, and republished the current handoff without focusing, clicking, typing, invoking UIA, restarting, closing, saving, syncing, reloading, detaching, upgrading, or modifying the model. The refresh reported `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, `blocked_gap_count: 4`, and `safety_guard_violation_count: 0`. The follow-up hard gate `live-completion-gate-after-preflight-refresh-continue-20260514` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`, and `unsatisfied_count: 17`; follow-up stable scan `live-stable-scan-after-preflight-refresh-continue-20260514` reported `status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`, `preflight_alignment_violation_count: 0`, `handoff_reference_violation_count: 0`, and `agent_stop_status_boundary_violation_count: 0`. This keeps the human handoff current while preserving the active incomplete state.

Latest sanitized human-unblock refresh: `north-star-human-unblock-brief` task `live-human-unblock-brief-after-continue-20260514` wrote a credential-free brief with three options: human restart/reload using the no-save checklist, human-supplied approval phrase followed by separate read-only verification/preview, or waiting for a real recovery condition. It reported `approval_material_included: false`, `approval_material_withheld: true`, `autonomous_progress_available: false`, `blocked_waiting_for_human_or_real_condition: true`, `completion_allowed: false`, `may_call_update_goal: false`, and `may_execute_from_this_result: false`. Follow-up stable scan `live-stable-scan-after-human-unblock-brief-continue-20260514` stayed clean, and follow-up hard gate `live-completion-gate-after-human-unblock-brief-continue-20260514` still reported the four blockers and 17 unsatisfied requirements. `north-star-agent-stop-status` task `live-agent-stop-status-after-human-unblock-brief-continue-20260514` then refreshed `NORTH_STAR_AGENT_STOP_STATUS_CURRENT.*` with `status: stop_for_human_or_real_condition`, `should_stop_agent: true`, `recommended_agent_action: wait_for_human_or_real_condition`, and no execution authority. Final stable scan `live-stable-scan-after-agent-stop-refresh-continue-20260514` remained clean with `agent_stop_status_boundary_violation_count: 0`.

Latest restart-checklist freshness refresh: live status task `live-status-for-checklist-staleness-20260514` confirmed Revit 2025 was idle on the copied detached model, with zero dialogs, active view `STARTING VIEW / DrawingSheet`, `dirty: true`, and bridge heartbeat/document payloads still updating. Bridge-readiness task `live-bridge-readiness-for-checklist-staleness-20260514` still failed only `loaded_build_current`; the post-human resume script parsed with zero PowerShell errors and contains only safety text mentioning save/sync/reload/close terms, not executable action flags. `bridge-restart-validation-plan` task `live-bridge-restart-validation-plan-checklist-refresh-20260514` refreshed the no-save checklist from that current state, and `north-star-current-handoff` task `live-current-handoff-after-checklist-refresh-20260514` republished `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` at `2026-05-14T10:14:12Z`. Follow-up stable scan `live-stable-scan-after-checklist-handoff-refresh-20260514` stayed clean with zero stale-approval, preflight-alignment, approval-phrase metadata, handoff-reference, and stop-status-boundary violations. Follow-up hard gate `live-completion-gate-after-checklist-handoff-refresh-20260514` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`, `unsatisfied_count: 17`, and no safety guard violations.

Latest stable-artifact scan command refresh: `north-star-stable-artifact-scan` is now a first-class read-only command and required command-list item. It scans sandbox-root `NORTH_STAR_*CURRENT*` files for stale approval credential leakage, status-summary execution leaks, execution-authority drift, legacy blocked-handoff tombstone redaction, and blocker/completion consistency, then writes `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` and `.md` without touching Revit. Focused stable-scan/audit/handoff tests passed (`9 passed, 242 deselected` and `6 passed, 248 deselected`), the full Revit operator slice passed (`258 passed` with the known pytest cache warning), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-current-handoff-20260513` reported `status: clean`, `artifact_count: 31`, `violation_count: 0`, and `credential_scan_mode: status_always_and_stale_preflight_current_artifacts`; the follow-up hard gate `live-north-star-completion-gate-after-final-stable-artifact-scan-20260513` remained blocked with the same four blockers, no safety guard violations, and no completion authority.

Latest unblock-readiness command refresh: `north-star-unblock-readiness` is now a first-class read-only command and required command-list item. It writes `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` and `.md` with one diagnostic packet per blocked north-star gap, including current evidence presence, source artifacts, required human or real-condition action, safe next commands, and completion evidence still needed. The command has no execution or completion authority: it always reports `completion_allowed: false`, `may_call_update_goal: false`, and `may_execute_from_this_result: false`. Focused unblock-readiness/stable-scan/safety tests passed (`6 passed, 250 deselected`), the full Revit operator slice passed (`260 passed` with the known pytest cache warning), and compileall passed. Live task `live-north-star-unblock-readiness-20260513` reported four blocker packets for `bridge_restart_validation`, `live_ui_workflow_execution`, `live_recovery_drills`, and `live_uia_ribbon_context_execution`; follow-up scan `live-north-star-stable-artifact-scan-after-unblock-readiness-20260513` reported `status: clean`, `artifact_count: 33`, and `violation_count: 0`; hard gate `live-north-star-completion-gate-after-unblock-readiness-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and zero safety guard violations.

Latest watch hard-gate refresh: `north-star-watch` now refreshes the hard completion gate, publishes stable current audit/gate files, and writes the unblock-readiness packet after polling so watch output cannot rely on the non-authoritative status artifact alone. Focused watch/readiness tests passed (`4 passed, 252 deselected`), the full Revit operator slice passed (`260 passed` with the known pytest cache warning), and compileall passed. Live watch task `live-north-star-watch-with-hard-gate-20260513` observed one read-only check, reported `status: no_change`, and embedded `completion_gate.status: blocked`, `north_star_complete: false`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and `unblock_readiness.may_execute_from_this_result: false`. The follow-up stable scan was clean, and hard gate `live-north-star-completion-gate-after-watch-hard-gate-20260513` still blocks completion with zero safety guard violations.

Latest watch approval-preflight refresh: `north-star-watch --refresh-approval-preflight` now reruns the read-only approval dry-run preflight with the same expected Revit/title/view context predicates before refreshing the hard gate and unblock-readiness. Focused watch/preflight tests passed (`6 passed, 251 deselected`), the full Revit operator slice passed (`261 passed` with the known pytest cache warning), and compileall passed. Live task `live-north-star-watch-refresh-preflight-20260513` refreshed preflight during the watch with `status: preflighted`, `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, and `expires_at_utc: 2026-05-13T16:55:56Z`, then still embedded `completion_gate.status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and `unblock_readiness.may_execute_from_this_result: false`. Follow-up stable scan `live-north-star-stable-artifact-scan-after-watch-refresh-preflight-20260513` was clean, and hard gate `live-north-star-completion-gate-after-watch-refresh-preflight-20260513` still blocks completion with zero safety guard violations.

Latest watch current-handoff refresh: `north-star-watch --publish-current-handoff` now explicitly republishes the stable current handoff bundle after optional preflight and before the final hard completion gate, keeping `NORTH_STAR_HANDOFF_CURRENT.*`, waiting state, next-human-action card, blocked ledger, and completion gate aligned during supervision. Focused watch tests passed (`4 passed, 254 deselected`), the full Revit operator/plugin slice passed (`262 passed`), and compileall passed. Live task `live-north-star-watch-refresh-preflight-current-handoff-20260513` ran one read-only check with `--refresh-approval-preflight --publish-current-handoff`, reported `preflight_status: preflighted`, `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, `preflight_expires_at_utc: 2026-05-13T17:04:53Z`, `handoff_ran: true`, `handoff_status: blocked`, `handoff_completion_allowed: false`, `handoff_may_call_update_goal: false`, and `handoff_blocked_gap_count: 4`. The embedded hard gate still reported `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and zero safety guard violations; `unblock_readiness.may_execute_from_this_result` remained false. Follow-up scan `live-north-star-stable-artifact-scan-after-watch-handoff-refresh-20260513` reported `status: clean`, `artifact_count: 33`, and `violation_count: 0`; hard gate `live-north-star-completion-gate-after-watch-handoff-refresh-20260513` remained blocked with the same four blockers and no completion authority.

Latest stable blocker-ID consistency guard: `north-star-stable-artifact-scan` now checks stable JSON artifacts that expose `blocked_gap_ids` against the hard `NORTH_STAR_COMPLETION_GATE_CURRENT.json` blocker IDs, and also flags count fields that do not match the local `blocked_gap_ids` length. Focused stable-scan tests passed (`4 passed, 255 deselected`), the full Revit operator/plugin slice passed (`263 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-with-blocker-id-guard-20260513` reported `status: clean`, `artifact_count: 33`, `violation_count: 0`, `consistency_violation_count: 0`, and `blocker_mismatch_count: 0`. The hard gate `live-north-star-completion-gate-after-blocker-id-guard-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest fresh-preflight handoff alignment guard: `north-star-stable-artifact-scan` now treats a fresh approval preflight as unsafe if existing approval-facing stable handoff artifacts are older than `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`. This catches the case where a preflight was refreshed but the human-facing handoff bundle was not republished afterward. Focused stable-scan tests passed (`6 passed, 255 deselected`), the full Revit operator/plugin slice passed (`265 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-with-preflight-alignment-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment_status: aligned`, `preflight_alignment_checked: 19`, and `preflight_alignment_stale: 0`. The fresh hard gate `live-north-star-completion-gate-after-preflight-alignment-guard-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest stable handoff reference-integrity guard: `north-star-stable-artifact-scan` now validates the `stable_files` map inside `NORTH_STAR_HANDOFF_CURRENT.json`; each referenced file must stay inside the sandbox, exist, and parse when it is JSON. Focused stable-scan tests passed (`7 passed, 255 deselected`), the full Revit operator/plugin slice passed (`266 passed`), and compileall passed. The first live scan after the guard correctly reported stale-approval violations because the previous preflight had expired. A read-only watch refresh (`live-north-star-watch-refresh-after-handoff-reference-guard-20260513`) reran approval preflight and republished the current handoff, keeping the hard gate blocked. The follow-up live scan `live-north-star-stable-artifact-scan-after-reference-refresh-20260513` reported `status: clean`, `violation_count: 0`, `handoff_reference_status: ok`, `handoff_reference_count: 29`, `handoff_present_count: 29`, `handoff_missing_count: 0`, `handoff_outside_sandbox_count: 0`, and `handoff_unreadable_json_count: 0`. The hard gate `live-north-star-completion-gate-after-reference-guard-20260513` still reports `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, and zero safety guard violations.

Latest hard-gate stable-scan integration: `north-star-completion-gate` now directly consumes the pure stable-scan guard checks for stable artifact consistency, fresh-preflight handoff alignment, and current handoff file references. An otherwise complete audit is blocked when these stable handoff checks fail, so completion cannot bypass the scan by calling only the hard gate. Focused completion-gate/stable-scan tests passed (`27 passed, 236 deselected`), the full Revit operator/plugin slice passed (`267 passed`), and compileall passed. Live scan `live-north-star-stable-artifact-scan-after-hard-gate-integration-20260513` remained clean, and live hard gate `live-north-star-completion-gate-with-integrated-stable-scan-guards-20260513` reported `status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, `safety_guard_violation_count: 0`, and `safety_guard_followup_count: 0`.

Latest unblock-readiness dynamic guard refresh: `north-star-unblock-readiness` now recomputes the stable-handoff guard checks directly instead of trusting only the last stable scan artifact. The readiness packet reports `stable_handoff_guard_clean`, `stable_handoff_guard_violation_count`, and `stable_handoff_guard_violation_ids`, so a human-facing unblock packet can expose broken handoff references, blocker drift, stale preflight alignment, stale approval credentials, or execution leaks even if `NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` is stale. Focused gate/scan/unblock tests passed (`30 passed, 234 deselected`), the full Revit operator/plugin slice passed (`268 passed`), and compileall passed. Live task `live-north-star-unblock-readiness-with-dynamic-stable-guard-20260513` reported `status: blocked`, `blocked_gap_count: 4`, `completion_allowed: false`, `may_call_update_goal: false`, `stable_artifact_scan_clean: true`, `stable_handoff_guard_clean: true`, and `stable_handoff_guard_violation_count: 0`. The follow-up hard gate `live-north-star-completion-gate-after-dynamic-unblock-guard-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest unblock-readiness refresh-command handoff: `north-star-unblock-readiness` now includes a current `safe_supervision_refresh_command` plus quoted PowerShell line in `artifact_readiness` and each blocker packet. The command is a read-only `north-star-watch` refresh with `--refresh-approval-preflight`, `--publish-current-handoff`, `--checks 1`, `--poll 0`, and the latest expected Revit/title/path/view context from `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`; tests assert it withholds `--execute`, `--approval-token`, and `--approval-tokens-json`. Focused unblock-readiness tests passed (`3 passed, 261 deselected`), the full Revit operator/plugin slice passed (`268 passed`), and compileall passed. Live watch task `live-north-star-watch-refresh-after-unblock-refresh-command-20260513` refreshed preflight with `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, and `expires_at_utc: 2026-05-13T17:40:36Z`; `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` then reported `stable_handoff_guard_clean: true` and the expected `safe_supervision_refresh_powershell`. Follow-up stable scan `live-north-star-stable-artifact-scan-after-unblock-refresh-command-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment_violation_count: 0`, and `handoff_reference_violation_count: 0`. Hard gate `live-north-star-completion-gate-after-unblock-refresh-command-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest unblock refresh-command safety guard: `north-star-stable-artifact-scan` and the hard `north-star-completion-gate` now directly validate `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` refresh command handoffs. The guard requires a command argument list and quoted PowerShell line for `north-star-watch`, requires `--refresh-approval-preflight`, `--publish-current-handoff`, `--checks 1`, `--poll 0`, and the latest expected Revit/title/path/view context, and flags `--execute`, `--approval-token`, `--approval-tokens-json`, approval phrases, token strings, packet drift, missing read-only flags, or PowerShell mismatches. Focused regression tests passed (`9 passed, 257 deselected`), the full Revit operator/plugin slice passed (`270 passed`), and compileall passed. Live watch refresh `live-north-star-watch-refresh-after-refresh-command-guard-20260513` refreshed approval preflight with `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, and `expires_at_utc: 2026-05-13T17:49:53Z` while observing Revit idle with no dialogs. Live stable scan `live-north-star-stable-artifact-scan-after-refresh-command-guard-20260513` reported `status: clean`, `violation_count: 0`, `unblock_refresh_command.status: ok`, `command_count: 5`, `packet_command_count: 4`, and `unblock_refresh_command_violation_count: 0`. Hard gate `live-north-star-completion-gate-after-refresh-command-guard-20260513` remained blocked with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest unblock-readiness preflight-alignment guard: `north-star-stable-artifact-scan` now includes `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` and `.md` in the fresh-preflight handoff alignment set. If approval preflight is fresh but unblock-readiness is older, the stable scan and hard completion gate flag `fresh-preflight-stale-handoff-artifact`, preventing stale per-blocker readiness packets from sitting beside current approval context. Focused stable-scan regression tests passed (`9 passed, 258 deselected`), the full Revit operator/plugin slice passed (`271 passed`), and compileall passed.

Latest watch ordering fix: the fresh-preflight alignment guard exposed that `north-star-watch --refresh-approval-preflight --publish-current-handoff` could evaluate its final hard gate before regenerating `NORTH_STAR_UNBLOCK_READINESS_CURRENT.*`, causing the returned gate to correctly flag stale unblock-readiness. `north-star-watch` now writes unblock-readiness before its final hard completion gate. Focused watch-order regression tests passed (`4 passed, 263 deselected`), the full Revit operator/plugin slice passed (`271 passed`), and compileall passed. Live watch `live-north-star-watch-refresh-after-watch-order-fix-20260513` refreshed preflight with `ready_for_human_approval_count: 3`, `unsafe_preflight_count: 0`, and `expires_at_utc: 2026-05-13T17:58:41Z`, then returned a final hard gate with no safety guard violations. Live stable scan `live-north-star-stable-artifact-scan-after-watch-order-fix-20260513` reported `status: clean`, `violation_count: 0`, `preflight_alignment.checked_artifact_count: 21`, `preflight_alignment.stale_artifact_count: 0`, and `unblock_refresh_command_violation_count: 0`. Hard gate `live-north-star-completion-gate-after-watch-order-fix-20260513` remained blocked only on the same four north-star gates with `completion_allowed: false`, `may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`, and zero safety guard violations.

Latest approval phrase expiry visibility refresh: the hard completion gate and
human gate packet now print the expiry for any exposed exact human approval
phrase and explicitly report `approval_phrase_execution_authority: false`.
The corresponding JSON fields include `approval_phrase_expires_at_utc` and
`approval_preflight_remaining_seconds`. This makes the phrase visibly
time-bound handoff data, not permission to execute. Focused handoff/gate tests
passed (`22 passed`); the goal remains blocked until the remaining human or
real-condition gates are actually cleared and a fresh hard completion gate
reports `completion_allowed: true` and `may_call_update_goal: true`.

Latest approval phrase metadata guard: `north-star-stable-artifact-scan` and
the hard `north-star-completion-gate` now fail closed when a fresh-preflight
stable current artifact exposes an exact approval phrase without
`approval_phrase_expires_at_utc` or without
`approval_phrase_execution_authority: false`. Focused phrase/stable-scan/gate
tests passed (`24 passed`), the full Revit operator/plugin slice passed
(`281 passed` with the known pytest cache warning), compileall passed, and
`git diff --check` reported only the existing LF/CRLF warnings on `.gitignore`
and `pyproject.toml`. Live watch task
`live-north-star-watch-refresh-after-phrase-metadata-guard-20260513` refreshed
approval preflight to `2026-05-13T19:33:09Z` and republished current handoffs.
Live stable scan
`live-north-star-stable-artifact-scan-after-phrase-metadata-guard-20260513`
reported `status: clean`, `violation_count: 0`,
`approval_phrase_metadata.status: clean`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. Live hard gate
`live-north-star-completion-gate-after-phrase-metadata-guard-20260513` remained
blocked only on the real north-star blockers, with `completion_allowed: false`,
`may_call_update_goal: false`, `safety_guard_violations: []`, and the same four
blocked gates: `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`.

Latest restart-handoff refresh evidence: the copied local model is still
connected through the bridge, but the loaded bridge build is stale and the
active detached document is dirty, so Hermes must not close, restart, save,
sync, reload, detach, upgrade, or decide preservation. Read-only task
`live-bridge-restart-validation-plan-refresh-continue-20260513` regenerated the
human no-save restart checklist and reported `restart_or_reload_required: true`,
`ready_for_continuous_bridge_now: false`, and failed check
`loaded_build_current`. Read-only handoff task
`live-north-star-current-handoff-after-restart-plan-refresh-continue-20260513`
republished the current handoff with that checklist as the next human action and
kept `completion_allowed: false`, `may_call_update_goal: false`, and four
blocked gates. Follow-up stable scan
`live-north-star-stable-scan-after-restart-plan-handoff-continue-20260513`
reported `status: clean`, `violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`,
`unblock_refresh_command_violation_count: 0`, and `may_call_update_goal: false`.
The north star is therefore still open; this evidence only confirms the current
blocked handoff is safe and current.

Latest continuation refresh: read-only watch task
`live-north-star-watch-continuation-refresh-20260513` refreshed approval
preflight to `2026-05-13T19:44:07Z`, observed Revit running, idle, with zero
dialogs and no hung main window, and still reported
`ready_for_continuous_bridge: false` with failed check `loaded_build_current`.
Its hard gate remained blocked with `completion_allowed: false`,
`may_call_update_goal: false`, `blocked_gate_count: 4`, `unsatisfied_count: 10`,
and zero safety guard violations. Follow-up stable scan
`live-north-star-stable-scan-after-continuation-watch-20260513` checked 33
current artifacts and reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest safe-command wrapper refresh: `run-safe-command` is now implemented as a
fail-closed wrapper for the read-only bridge allowlist: `active-document`,
`export-metadata`, and `qa-snapshot`. Focused safety/audit/CLI tests passed
(`5 passed`), the full Revit operator/plugin slice passed (`284 passed`), and
compileall passed. Live dry-run task `live-run-safe-command-dry-run-20260513`
wrapped `active-document` without queueing a bridge command, while a local block
smoke for `run-safe-command --name save --execute` returned structured blocked
JSON and did not create a queue. Read-only watch task
`live-north-star-watch-after-run-safe-command-20260513` refreshed approval
preflight to `2026-05-13T19:54:22Z`; the hard gate remained blocked only on the
same four real gates with zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-run-safe-command-20260513` checked 33 current
artifacts and reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. The refreshed audit checklist now
also explicitly marks the instruction file, next-goal prompt, `health`, `serve`,
`run-safe-command`, and `request-operation` as satisfied checklist items.

Latest safe-wrapper surface coverage: the Hermes plugin and MCP wrappers now
have explicit regression coverage for `run-safe-command`. Focused wrapper tests
passed (`7 passed`) across CLI, MCP, and `plugins/revit-operator`, and the full
Revit operator/plugin slice passed (`288 passed`). Compileall passed. The plugin
tool schema now names `run-safe-command` as a normal agent-facing command while
still blocking `serve`; tests confirm both plugin and MCP dry-run
`run-safe-command --name active-document` without queue creation, and both block
`run-safe-command --name save --execute` before bridge delegation. Follow-up
stable scan `live-north-star-stable-scan-after-safe-wrapper-surfaces-20260513`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`,
`unblock_refresh_command_violation_count: 0`, and
`may_call_update_goal: false`.

Latest HTTP control-server wrapper coverage: the local `/command` endpoint now
has explicit regression coverage for `run-safe-command`. Focused HTTP/CLI/MCP
tests passed (`6 passed`), and the full Revit operator/plugin slice remained
green (`288 passed`). The HTTP test verifies `run-safe-command --name
active-document` dry-runs through `/command` without creating a bridge queue,
and `run-safe-command --name save --execute` returns blocked JSON over HTTP
before bridge delegation. Compileall passed and `git diff --check` still reports
only the existing LF/CRLF warnings on `.gitignore` and `pyproject.toml`.

Latest HTTP command-discovery coverage: the loopback control server now exposes
`GET /commands` in addition to `/health` and `/command`. The endpoint returns the
available CLI command surface plus blocked server-mode commands, including
`run-safe-command`, `north-star-completion-gate`, and blocked `serve`. Focused
control-server tests passed (`2 passed`), the full Revit operator/plugin slice
passed (`288 passed`), compileall passed, and the runbook/prototype docs now
list `/commands`.

Latest prompt-coverage audit expansion: the hard north-star audit now maps the
original prompt's four architecture parts and seven aspirational design
directions as first-class prompt-to-artifact checklist entries, in addition to
the core and MVP requirements. Focused audit/gate tests passed (`2 passed`), the
full Revit operator/plugin slice passed (`288 passed`), and compileall passed.
Live watch task
`live-north-star-watch-after-architecture-aspirational-checklist-20260513`
refreshed approval preflight to `2026-05-13T20:09:09Z`; the hard gate remained
blocked with `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`completion_allowed: false`, `may_call_update_goal: false`, and zero safety
guard violations. The refreshed audit has 26 `prompt_requirement` checklist
entries. Stable scan
`live-north-star-stable-scan-after-architecture-aspirational-checklist-20260513`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest prototype-source component audit: the north-star checklist now maps the
explicit source-code deliverable into seven component entries: UI/window
observer, dialog lister/classifier, screenshot capture, safe action executor,
local command interface, optional Revit add-in bridge, and optional metadata
exporter. Focused audit/gate tests passed (`2 passed`), the full Revit
operator/plugin slice passed (`288 passed`), and compileall passed. Live watch
task `live-north-star-watch-after-prototype-component-checklist-20260513`
refreshed approval preflight to `2026-05-13T20:14:05Z`; the hard gate remained
blocked with `completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, and zero safety guard
violations. The refreshed audit marks all seven prototype-source component
entries as `satisfied`. Stable scan
`live-north-star-stable-scan-after-prototype-component-checklist-20260513`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest completion-audit coverage guard: the hard completion gate now refuses a
completion-candidate audit that omits any required prompt-to-artifact checklist
ID. Focused completion-gate tests passed (`4 passed`), the full Revit
operator/plugin slice passed (`289 passed`), compileall passed, and
`git diff --check` reported only the existing LF/CRLF warnings on `.gitignore`
and `pyproject.toml`. Live watch task
`live-north-star-watch-after-completion-audit-coverage-guard-20260513`
refreshed approval preflight to `2026-05-13T20:23:24Z`; the hard gate remained
blocked with `completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, and zero safety guard
violations. The gate summary reported 156 required checklist IDs, 156 present,
and zero missing. Stable scan
`live-north-star-stable-scan-after-completion-audit-coverage-guard-20260513`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. The north-star goal remains
incomplete; this guard only prevents a false completion claim.

Latest raw-audit blocker surfacing: prompt requirement checklist entries now
copy `blocked_gaps` and `blocked_by_gap_ids` to the top level of raw
`unverified_or_blocked_requirements`, so downstream agents do not have to infer
the live blocker chain from nested evidence. Focused audit/gate tests passed
(`2 passed`), the full Revit operator/plugin slice passed (`289 passed`),
compileall passed, and `git diff --check` again reported only the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-raw-blocker-surfacing-20260513` refreshed approval
preflight to `2026-05-13T20:28:37Z`; the hard gate remained blocked with
`completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, zero safety guard violations,
and zero missing required checklist IDs. The current raw audit shows
`requirement:core-human-style-ui-operation` blocked by
`live_ui_workflow_execution` and `live_uia_ribbon_context_execution` at top
level. Stable scan
`live-north-star-stable-scan-after-raw-blocker-surfacing-20260513` reported
`status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest hard-gate autonomy boundary: `north-star-completion-gate` now exposes
the audit's `completion_actions` directly, including
`autonomous_progress_available`, `human_or_real_condition_required`,
`blocked_waiting_for_human_or_real_condition`, and the autonomous/human/real
action lists. Focused gate coverage passed (`1 passed`), the full Revit
operator/plugin slice passed (`289 passed`), compileall passed, and
`git diff --check` still only reported the existing LF/CRLF warnings on
`.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-gate-autonomy-boundary-20260513` refreshed approval
preflight to `2026-05-13T20:34:01Z`; the stable completion gate now reports
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, zero autonomous actions,
three human actions, one real-condition action, zero safety guard violations,
and zero missing required checklist IDs. Stable scan
`live-north-star-stable-scan-after-gate-autonomy-boundary-20260513` reported
`status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. This confirms the hard gate is
waiting on external human/real-condition evidence, not on another autonomous
implementation step.

Latest audit-authority gate hardening: the hard completion gate now requires
the fresh audit's own `completion_actions.may_call_update_goal: true` before it
can report `completion_allowed: true`. A clean-looking audit with
`north_star_complete: true` is therefore insufficient unless the audit also
authorizes goal completion. Focused completion-gate authority tests passed
(`5 passed`), the full Revit operator/plugin slice passed (`290 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-audit-completion-authority-20260513` refreshed
approval preflight to `2026-05-13T20:39:01Z`; the stable completion gate
reported `audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, zero safety guard violations, and zero missing required
checklist IDs. Stable scan
`live-north-star-stable-scan-after-audit-completion-authority-20260513`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest stable-scan audit-authority guard: the stable artifact scanner now
records `audit_completion_authorized` in current-artifact summaries and flags a
published `NORTH_STAR_COMPLETION_GATE_CURRENT.json` that grants
`completion_allowed` or `may_call_update_goal` without
`audit_completion_authorized: true`. Focused stable-scan tests passed
(`2 passed`), the full Revit operator/plugin slice passed (`291 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-stable-audit-authority-guard-20260513` refreshed
approval preflight to `2026-05-13T20:45:54Z`; the stable completion gate
reported `audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, zero safety guard violations, and zero missing required
checklist IDs. Stable scan
`live-north-star-stable-scan-after-stable-audit-authority-guard-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`consistency_violation_count: 0`, `stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. The north-star goal remains
incomplete; the new scan guard prevents stale current files from falsely
granting completion authority.

Latest script/handoff audit-authority guard: generated completion handoffs now
require the same three fields before saying `update_goal` may be called:
`completion_allowed: true`, `may_call_update_goal: true`, and
`audit_completion_authorized: true`. The live watch and resume-check consumers
also use that shared helper, and the generated
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` and
`NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` both contain the
`$Gate.audit_completion_authorized -eq $true` guard and warning text that
surfaces the audit-authority value when blocked. Focused handoff/resume tests
passed (`8 passed`), the full Revit operator/plugin slice passed
(`291 passed`), compileall passed, and `git diff --check` still only reported
the existing LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch
task `live-north-star-watch-after-script-audit-authority-guard-20260513`
refreshed approval preflight to `2026-05-13T20:52:41Z`; the completion gate
remained blocked with `audit_completion_authorized: false`,
`completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, zero safety guard violations,
and zero missing required checklist IDs. Stable scan
`live-north-star-stable-scan-after-script-audit-authority-guard-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`consistency_violation_count: 0`, `stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest artifact-summary audit-authority guard: lower-level north-star summary
artifacts now propagate `audit_completion_authorized` explicitly, and derived
completion checks use the same three-field rule:
`completion_allowed: true`, `may_call_update_goal: true`, and
`audit_completion_authorized: true`. `current_handoff_refresh` also normalizes
missing audit-authority data to `false`, so older or mocked handoff payloads do
not silently omit the field. Focused artifact-summary tests passed
(`8 passed`), the previously failing handoff-refresh regression test passed
(`1 passed`), the full Revit operator/plugin slice passed (`292 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-artifact-authority-summary-guard-20260513`
reported Revit 2025 idle, no active dialogs, stale loaded bridge build still
requiring Revit restart/reload, and a blocked completion gate with
`audit_completion_authorized: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, zero safety guard violations,
and zero missing required checklist IDs. Stable scan
`live-north-star-stable-scan-after-artifact-authority-summary-guard-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`consistency_violation_count: 0`, `status_summary_violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`. Current unblock readiness,
blocked ledger, handoff, refreshed gate summary, and next-human-action summary
all report `audit_completion_authorized: false`; next human action remains
`blocked_waiting_for_human_or_real_condition`.

Latest explicit current-artifact audit-authority fields: `north-star-audit`,
`north-star-status`, `north-star-waiting-state`, and the deprecated blocked
handoff tombstone now publish explicit `audit_completion_authorized` values
instead of leaving stable-scan summaries as `null`. These artifacts remain
non-authoritative for goal closure; the field is present to make blocked state
unambiguous. Focused audit/status/waiting/current-artifact tests passed
(`20 passed`), the full Revit operator/plugin slice passed (`292 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-explicit-audit-authority-current-fields-20260513`
remained read-only and reported `audit_completion_authorized: false`,
`completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, and
`unsatisfied_count: 17`. Stable scan
`live-north-star-stable-scan-after-explicit-audit-authority-current-fields-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`consistency_violation_count: 0`, and `status_summary_violation_count: 0`;
`NORTH_STAR_STATUS_CURRENT.json`, `NORTH_STAR_AUDIT_CURRENT.json`,
`NORTH_STAR_WAITING_STATE_CURRENT.json`, and
`NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json` all summarize
`audit_completion_authorized: false`.

Latest next-human approval coverage clarity: the next-human-action artifact now
separates all approval-gated blocker gaps from the single selected approval
item's coverage. This prevents the `safe-ribbon-view-tab` approval phrase from
appearing to satisfy both `live_uia_ribbon_context_execution` and the broader
`live_ui_workflow_execution` blocker. Targeted next-human-action tests passed
(`8 passed`), `python -m py_compile tools\revit_operator\north_star.py` passed,
the full Revit operator/plugin slice passed (`292 passed`), compileall passed,
and `git diff --check` still only reported the existing LF/CRLF warnings on
`.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-next-human-approval-coverage-clarity-20260513`
remained read-only and reported `audit_completion_authorized: false`,
`completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, and
`unsatisfied_count: 17`. `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` now reports
`approval_blocker_gap_ids: [live_ui_workflow_execution,
live_uia_ribbon_context_execution]`, `selected_item_gap_ids:
[live_uia_ribbon_context_execution]`,
`remaining_approval_gap_ids_after_selected_item: [live_ui_workflow_execution]`,
and `selected_item_covers_all_approval_blockers: false`. Stable scan
`live-north-star-stable-scan-after-next-human-approval-coverage-clarity-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`consistency_violation_count: 0`, `status_summary_violation_count: 0`,
`stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`preflight_alignment_violation_count: 0`, and
`unblock_refresh_command_violation_count: 0`.

Latest approval-coverage scan guard: the stable artifact scan and completion
safety guard now validate that `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`
approval options contain internally consistent coverage metadata. The guard
checks that `approval_blocker_gap_ids`, `selected_item_gap_ids`,
`remaining_approval_gap_ids_after_selected_item`, and
`selected_item_covers_all_approval_blockers` agree, so a selected approval item
cannot be misrepresented as clearing unrelated approval blockers. A targeted
negative test for mismatched coverage passed, the stable-scan group passed
(`17 passed`), the full Revit operator/plugin slice passed (`293 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-approval-coverage-scan-guard-20260513` remained
read-only and reported `audit_completion_authorized: false`,
`completion_allowed: false`, `may_call_update_goal: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-approval-coverage-scan-guard-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`approval_coverage.status: clean`, `human_approval_option_count: 1`, and
`approval_coverage_violation_count: 0`. The goal remains blocked because the
hard gate still requires human action or a real Revit recovery condition.

Latest gate approval-coverage summary: `NORTH_STAR_COMPLETION_GATE_CURRENT.json`
now carries the next-human-action approval coverage summary directly, including
`approval_coverage_status`, `approval_coverage_violation_count`, and the
selected approval item's blocker/selected/remaining gap sets. This makes the
hard gate itself show that `safe-ribbon-view-tab` covers
`live_uia_ribbon_context_execution` while `live_ui_workflow_execution` remains
uncovered. Targeted summary/gate tests passed (`2 passed`), the focused
next-human/stable-scan/completion-gate group passed (`47 passed`), the full
Revit operator/plugin slice passed (`293 passed`), compileall passed, and
`git diff --check` still only reported the existing LF/CRLF warnings on
`.gitignore` and `pyproject.toml`. Live watch task
`live-north-star-watch-after-gate-approval-coverage-summary-20260513` remained
read-only and reported `completion_allowed: false`, `may_call_update_goal:
false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`,
`unsatisfied_count: 17`, zero safety guard violations,
`approval_coverage_status: clean`, and `approval_coverage_violation_count: 0`.
Stable scan `live-north-star-stable-scan-after-gate-approval-coverage-summary-20260513`
reported `status: clean`, `artifact_count: 33`, `violation_count: 0`,
`approval_coverage.status: clean`, and `approval_coverage_violation_count: 0`.

Latest gate markdown approval-coverage summary: the human-readable
`NORTH_STAR_COMPLETION_GATE_CURRENT.md` now mirrors the approval coverage
boundary from the JSON gate. The `provide-exact-human-approval-phrase` option
prints `approval_blocker_gap_ids`, `selected_item_gap_ids`,
`remaining_approval_gap_ids_after_selected_item`,
`selected_item_covers_all_approval_blockers`, and
`approval_coverage_fields_present`. Targeted completion-gate markdown coverage
test passed (`1 passed`), the focused next-human/stable-scan/completion-gate
group passed (`47 passed`), the full Revit operator/plugin slice passed
(`293 passed`), compileall passed, and `git diff --check` still only reported
the existing LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live watch
task `live-north-star-watch-after-gate-markdown-approval-coverage-20260513`
remained read-only and reported `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `unsatisfied_count: 17`, and zero safety guard
violations. Stable scan
`live-north-star-stable-scan-after-gate-markdown-approval-coverage-20260513`
reported `status: clean`, `violation_count: 0`, and
`approval_coverage_violation_count: 0`. The current completion gate markdown
contains six approval coverage lines, including
`selected_item_gap_ids: live_uia_ribbon_context_execution` and
`remaining_approval_gap_ids_after_selected_item: live_ui_workflow_execution`.

Latest completion-gate markdown drift guard: the stable artifact scan now
verifies that `NORTH_STAR_COMPLETION_GATE_CURRENT.md` mirrors the approval
coverage boundary from `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`. The guard
checks the expected markdown lines for `approval_coverage_status`,
`approval_blocker_gap_ids`, `selected_item_gap_ids`,
`remaining_approval_gap_ids_after_selected_item`,
`selected_item_covers_all_approval_blockers`, and
`approval_coverage_fields_present`, and flags drift if any line is missing.
Targeted coverage tests passed (`2 passed`), the stable-scan group passed
(`18 passed`), the full Revit operator/plugin slice passed (`294 passed`),
compileall passed, and `git diff --check` still only reported the existing
LF/CRLF warnings on `.gitignore` and `pyproject.toml`. Live stable scan
`live-north-star-stable-scan-after-gate-markdown-coverage-drift-guard-20260513`
reported `status: clean`, `violation_count: 0`,
`approval_coverage_violation_count: 0`,
`completion_gate_markdown_approval_coverage_violation_count: 0`,
`completion_gate_markdown_approval_coverage.status: clean`,
`expected_line_count: 6`, and `missing_line_count: 0`. The current hard gate
remains blocked with `completion_allowed: false`, `may_call_update_goal:
false`, `audit_completion_authorized: false`, `blocked_gap_count: 4`,
`unsatisfied_count: 17`, and zero safety guard violations.

Latest unblock-readiness markdown coverage guard: the dynamic
`north-star-unblock-readiness` handoff guard now recomputes the next-human
approval coverage and completion-gate markdown coverage checks directly, so a
stale or inconsistent stable scan cannot hide markdown drift at handoff time.
Targeted unblock-readiness guard tests passed (`2 passed`), the focused
stable-scan/unblock-readiness/completion-gate group passed (`46 passed`), the
full Revit operator/plugin slice passed (`295 passed`), compileall passed, and
`git diff --check` still only reported the existing LF/CRLF warnings on
`.gitignore` and `pyproject.toml`. Live unblock-readiness task
`live-north-star-unblock-readiness-after-markdown-coverage-guard-20260513`
remained read-only and reported `status: blocked`,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `stable_artifact_scan_clean: true`,
`stable_handoff_guard_clean: true`, and
`stable_handoff_guard_violation_count: 0`. The north-star goal remains blocked
because the hard gate still requires human action or a real Revit recovery
condition.

Latest unblock-readiness completion-authority markdown guard:
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.md` now prints
`audit_completion_authorized` beside `completion_allowed`,
`may_call_update_goal`, and `may_execute_from_this_result`. The stable artifact
scan now verifies that the unblock-readiness markdown mirrors those four
completion-authority guard fields from
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json`, and the hard completion-gate safety
guard includes the same check. Targeted tests passed (`2 passed`), the focused
stable-scan/unblock-readiness/completion-gate group passed (`47 passed`), the
full Revit operator/plugin slice passed (`296 passed`), and compileall passed.
After a read-only supervision refresh
`live-north-star-watch-refresh-after-unblock-markdown-guard-20260513`, live
stable scan `live-north-star-stable-scan-after-unblock-markdown-guard-20260513`
reported `status: clean`, `violation_count: 0`,
`unblock_readiness_markdown_completion_guard.status: clean`,
`unblock_readiness_markdown_completion_guard_violation_count: 0`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh completion gate
`live-north-star-completion-gate-after-unblock-markdown-guard-20260513`
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, and zero safety guard
violations. The goal remains blocked by the live human/real-condition gates.

Latest hard-gate safety count: `NORTH_STAR_COMPLETION_GATE_CURRENT.json` now
publishes `safety_guard_violation_count` directly, and the same count appears
in `completion_audit_summary` and the completion-gate markdown. This removes
the need for downstream handoff readers to infer safety status from the
`safety_guard_violations` list length. Targeted completion-gate tests passed
(`2 passed`), the focused stable-scan/unblock-readiness/completion-gate group
passed (`47 passed`), the full Revit operator/plugin slice passed
(`296 passed`), and compileall passed. Fresh hard gate
`live-north-star-completion-gate-after-safety-count-20260513` reported
`status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and a zero-length
`safety_guard_violations` list. Stable scan
`live-north-star-stable-scan-after-safety-count-20260513` reported
`status: clean` and `violation_count: 0`. The north-star goal is still not
complete.

Latest hard-gate safety count consistency guard: the stable artifact scan now
checks that any published `safety_guard_violation_count` matches the
`safety_guard_violations` list length and the
`completion_audit_summary.safety_guard_violation_count` value. A targeted
negative drift test passed (`2 passed` with the clean scan fixture), the focused
stable-scan/unblock-readiness/completion-gate group passed (`48 passed`), the
full Revit operator/plugin slice passed (`297 passed`), and compileall passed.
Live stable scan
`live-north-star-stable-scan-after-safety-count-consistency-20260513` reported
`status: clean`, `violation_count: 0`, `consistency_violation_count: 0`, and
for `NORTH_STAR_COMPLETION_GATE_CURRENT.json`:
`safety_guard_violation_count: 0`,
`safety_guard_violation_list_count: 0`, and
`completion_audit_summary_safety_guard_violation_count: 0`. The fresh hard gate
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, and `unsatisfied_count: 17`.

Latest completion-gate markdown safety-count guard: the stable artifact scan
now verifies that `NORTH_STAR_COMPLETION_GATE_CURRENT.md` mirrors the hard
gate's `safety_guard_violation_count` from
`NORTH_STAR_COMPLETION_GATE_CURRENT.json` in both the top-level gate summary
line and the Safety Guard Violations section count. The hard completion-gate
safety guard now includes this markdown drift check, so stale or edited human
readable gate text cannot silently disagree with the JSON safety count.
Targeted drift tests passed (`2 passed`), the focused
stable-scan/unblock-readiness/completion-gate group passed (`49 passed`), the
full Revit operator/plugin slice passed (`298 passed`), and compileall passed.
Read-only live refresh
`live-north-star-watch-refresh-after-markdown-safety-count-20260513` confirmed
Revit was idle with no dialogs while still requiring bridge restart/reload
validation because the loaded bridge build is stale and the copied detached
model is dirty. Final live stable scan
`live-north-star-stable-scan-after-markdown-safety-count-final-20260513`
reported
`status: clean`, `violation_count: 0`,
`completion_gate_markdown_safety_count.status: clean`,
`completion_gate_markdown_safety_count_violation_count: 0`,
`expected_line_count: 2`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-markdown-safety-count-20260513`
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest human-gate packet completion-authority guard:
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json` now explicitly publishes
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`, because the human-gate packet is a
supervised handoff and not completion or execution authority. The markdown now
mirrors those four fields and states that a fresh hard completion gate or
resume-check completion gate is still required before `update_goal`. The stable
artifact scan now verifies this JSON/Markdown mirror, and the hard completion
gate safety guard includes the same drift check. Targeted tests passed
(`2 passed`), the focused stable-scan/unblock-readiness/completion-gate/human
gate group passed (`51 passed`), the full Revit operator/plugin slice passed
(`299 passed`), and compileall passed. Read-only live refresh
`live-north-star-watch-refresh-after-human-gate-guard-20260513` confirmed Revit
was idle with no dialogs while still requiring human restart/reload validation
because the loaded bridge build is stale and the copied detached model is
dirty. Final live stable scan
`live-north-star-stable-scan-after-human-gate-guard-final-20260513` reported
`status: clean`, `violation_count: 0`,
`human_gate_packet_markdown_completion_guard.status: clean`,
`human_gate_packet_markdown_completion_guard_violation_count: 0`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-gate-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest current handoff completion-authority guard:
`NORTH_STAR_HANDOFF_CURRENT.json` now explicitly publishes
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`; its markdown mirrors those same four
fields. The stable artifact scan now verifies this handoff JSON/Markdown
mirror, and the hard completion-gate safety guard includes the same drift
check. The blocked ledger also now publishes
`may_execute_from_this_result: false` so the ledger cannot be interpreted as
execution authority. Targeted handoff/ledger tests passed (`3 passed`), the
focused stable-scan/unblock-readiness/completion-gate/handoff group passed
(`56 passed`), the full Revit operator/plugin slice passed (`300 passed`),
and compileall passed. Read-only live refresh
`live-north-star-watch-refresh-after-handoff-guard-20260513` confirmed Revit
was idle with no dialogs while still requiring human restart/reload validation
because the loaded bridge build is stale and the copied detached model is
dirty. Final live stable scan
`live-north-star-stable-scan-after-handoff-guard-final-20260513` reported
`status: clean`, `violation_count: 0`,
`handoff_markdown_completion_guard.status: clean`,
`handoff_markdown_completion_guard_violation_count: 0`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-handoff-guard-20260513` still reported
`status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest next-human-action markdown completion-authority guard:
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` now mirrors the JSON authority fields
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and
`may_execute_from_this_result: false`. The stable artifact scan now verifies
that mirror, and the hard completion-gate safety guard includes the same drift
check so the one-screen human unblock card cannot silently omit the audit
authority denial. Targeted next-human-action guard tests passed (`4 passed`),
the focused stable-scan/unblock-readiness/completion-gate/handoff/next-human
group passed (`63 passed`), the full Revit operator/plugin slice passed
(`301 passed`), and compileall passed. Read-only live refresh
`live-north-star-watch-refresh-after-next-human-markdown-guard-20260513`
confirmed Revit was idle with no dialogs while still requiring human
restart/reload validation because the loaded bridge build is stale and the
copied detached model is dirty. Final live stable scan
`live-north-star-stable-scan-after-next-human-markdown-guard-final-20260513`
reported `status: clean`, `violation_count: 0`,
`next_human_action_markdown_completion_guard.status: clean`,
`next_human_action_markdown_completion_guard_violation_count: 0`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-markdown-guard-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest ready-approvals markdown execution-authority guard:
`NORTH_STAR_READY_APPROVALS_CURRENT.md` now mirrors
`NORTH_STAR_READY_APPROVALS_CURRENT.json` with
`may_execute_from_this_result: false`, so the human-facing ready-approval list
cannot be mistaken for authority to execute an approval-gated UI action.
The stable artifact scan now verifies that mirror, and the hard completion-gate
safety guard includes the same drift check. Targeted ready-approvals guard tests
passed (`3 passed`), the focused stable-scan/unblock-readiness/completion-gate/
ready-approvals group passed (`61 passed`), the full Revit operator/plugin
slice passed (`302 passed`), and compileall passed. Read-only live refresh
`live-north-star-watch-refresh-after-ready-approvals-markdown-guard-20260513`
confirmed Revit was idle with no dialogs while still requiring human
restart/reload validation because the loaded bridge build is stale and the
copied detached model is dirty. Final live stable scan
`live-north-star-stable-scan-after-ready-approvals-markdown-guard-final-20260513`
reported `status: clean`, `violation_count: 0`,
`ready_approvals_markdown_execution_guard.status: clean`,
`ready_approvals_markdown_execution_guard_violation_count: 0`,
`expected_line_count: 1`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-ready-approvals-markdown-guard-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest legacy blocked-handoff markdown completion-authority guard:
`NORTH_STAR_BLOCKED_HANDOFF_CURRENT.md` now mirrors the deprecated/redacted
legacy JSON tombstone with `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`, and
`may_execute_from_this_result: false`. The stable artifact scan now verifies
this legacy JSON/Markdown mirror, and the hard completion-gate safety guard
includes the same drift check so the retired handoff surface cannot silently
omit the audit authority denial. Targeted legacy handoff tests passed
(`4 passed`), the focused stable-scan/unblock-readiness/completion-gate/
handoff group passed (`59 passed`), the full Revit operator/plugin slice passed
(`303 passed`), and compileall passed. Read-only live refresh
`live-north-star-watch-refresh-after-legacy-handoff-markdown-guard-20260513`
confirmed Revit was idle with no dialogs while still requiring human
restart/reload validation because the loaded bridge build is stale and the
copied detached model is dirty. Final live stable scan
`live-north-star-stable-scan-after-legacy-handoff-markdown-guard-final-20260513`
reported `status: clean`, `violation_count: 0`,
`legacy_blocked_handoff_markdown_completion_guard.status: clean`,
`legacy_blocked_handoff_markdown_completion_guard_violation_count: 0`,
`expected_line_count: 4`, and `missing_line_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-legacy-handoff-markdown-guard-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest generic authority Markdown mirror guard:
The stable artifact scan now performs a general sweep across
`NORTH_STAR_*_CURRENT.json` files that have matching Markdown artifacts. When a
JSON artifact exposes `completion_allowed`, `may_call_update_goal`,
`audit_completion_authorized`, or `may_execute_from_this_result`, the matching
Markdown must mirror the same authority-denial line. The hard completion-gate
safety guard includes this sweep, so future current-artifact drift is blocked
even before a purpose-built guard exists for that artifact. Targeted authority
mirror tests passed (`3 passed`), the focused stable-scan/unblock-readiness/
completion-gate/handoff group passed (`60 passed`), the full Revit
operator/plugin slice passed (`304 passed`), and compileall passed. Read-only
live refresh
`live-north-star-watch-refresh-after-authority-mirror-guard-20260513`
confirmed Revit was idle with no dialogs while still requiring human
restart/reload validation because the loaded bridge build is stale and the
copied detached model is dirty. Final live stable scan
`live-north-star-stable-scan-after-authority-mirror-guard-final-20260513`
reported `status: clean`, `violation_count: 0`,
`authority_markdown_mirror.status: clean`,
`authority_markdown_mirror_violation_count: 0`,
`checked_artifact_count: 13`, `checked_key_count: 42`, and
`skipped_missing_markdown_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-authority-mirror-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest recovery snapshot north-star qualification:
`recovery-snapshot` now writes `north_star_recovery_gate` and
`validated_live_recovery_drill` into both the snapshot JSON and command result.
The same classifier is used by the north-star audit path, so synthetic test
snapshots, idle snapshots, and non-Revit snapshots cannot accidentally satisfy
the `live_recovery_drills` gate. Targeted recovery tests passed (`4 passed`),
the focused recovery/north-star/completion/stable-scan group passed
(`65 passed`), the full Revit operator/plugin slice passed (`305 passed`), and
compileall passed. Live read-only snapshot
`live-recovery-gate-idle-snapshot-20260513` observed Revit in `idle` state with
no active dialogs. It reported `validated_live_recovery_drill: false`,
`north_star_recovery_gate.qualifies: false`, and excluded the artifact because
`snapshot does not show a live recovery condition`. Fresh hard gate
`live-north-star-completion-gate-after-recovery-qualification-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. Final stable scan
`live-north-star-stable-scan-after-recovery-qualification-final-20260513`
reported `status: clean` and `violation_count: 0`. The north-star goal remains
active and incomplete.

Latest recovery qualification stable-scan guard:
`north-star-stable-artifact-scan` and the hard completion-gate safety guard now
check every sandbox `revit_operator_runs/*/recovery_snapshot.json` artifact
that claims `validated_live_recovery_drill: true`. A snapshot cannot claim
north-star recovery credit unless its embedded `north_star_recovery_gate`
qualifies and the current classifier still agrees. Targeted regression checks
passed (`3 passed`), the focused stable-scan/completion/recovery group passed
(`59 passed`), the full Revit operator/plugin slice passed (`306 passed`), and
compileall passed. Fresh hard gate
`live-north-star-completion-gate-after-recovery-qualification-guard-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. Final stable scan
`live-north-star-stable-scan-after-recovery-qualification-guard-final-20260513`
reported `status: clean`, `violation_count: 0`,
`recovery_snapshot_qualification.status: clean`,
`recovery_snapshot_qualification_violation_count: 0`,
`checked_snapshot_count: 9`, `claimed_valid_count: 0`,
`embedded_qualifying_gate_count: 0`, and `computed_qualifying_count: 0`. The
north-star goal remains active and incomplete.

Human-gate blocker-count contract:
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json` is now part of the stable current
metadata scan. The human-gate packet publishes `generated_at_utc` and
`blocked_gate_count`, and stable scan reports `stable-blocker-count-missing`
when a non-empty stable artifact lists `blocked_gap_ids` without the matching
count. Focused human-packet/stable-scan coverage passed (`4 passed`), and the
full Revit operator/plugin slice passed (`366 passed`). Live
`live-north-star-human-gate-packet-count-repair-20260514` produced
`blocked_gap_count: 4`, `blocked_gate_count: 4`, a generation timestamp,
`completion_allowed: false`, `may_call_update_goal: false`, and
`may_execute_from_this_result: false`. The first live scan under the stronger
contract correctly found the stale published human packet missing
`blocked_gate_count` and `generated_at_utc`; read-only watch refresh
`live-north-star-watch-refresh-after-human-packet-count-contract-20260514`
republished the current handoff without UI/model action. Final stable scan
`live-north-star-stable-scan-after-human-packet-count-contract-refresh-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_current_metadata_violation_count: 0`,
`stale_approval_violation_count: 0`, and zero unblock mirror drift. Fresh hard
gate
`live-north-star-completion-gate-after-human-packet-count-contract-refresh-20260514`
still reported `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations.

Human-gate status guard:
`north-star-human-gate-packet` now derives its top-level status from the same
`autonomous_progress_available` and
`blocked_waiting_for_human_or_real_condition` fields it publishes. It no longer
labels a non-complete state as human/real-condition blocked when the current
audit still has an autonomous safe next step. Focused status coverage passed
(`2 passed`), and the full Revit operator/plugin slice passed (`367 passed`).
Live `live-north-star-human-gate-status-guard-refresh-20260514` still reported
`status: blocked_human_or_real_condition` because the current hard gate reports
`autonomous_progress_available: false`, `human_or_real_condition_required:
true`, and `blocked_waiting_for_human_or_real_condition: true`. Follow-up
stable scan `live-north-star-stable-scan-after-human-gate-status-guard-20260514`
reported `status: clean`, `violation_count: 0`, and zero stable metadata,
stale-approval, approval-phrase, read-only-script, or unblock-mirror
violations. Fresh hard gate
`live-north-star-completion-gate-after-human-gate-status-guard-20260514` still
reported `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations.

Human-gate packet refresh after blocked correction:
`live-north-star-human-gate-packet-refresh-20260514b` refreshed the stable
human-gate packet after the latest blocked-state correction. It returned
`status: blocked_human_or_real_condition`, `success: true`,
`blocked_gap_count: 4`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`autonomous_progress_available: false`, and `may_execute_from_this_result:
false`. Follow-up stable scan
`live-north-star-stable-scan-after-human-packet-refresh-20260514b` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`,
`stable_readonly_script_guard_violation_count: 0`, and
`unblock_stable_scan_mirror_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-packet-refresh-20260514b` still
reported `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations.

Next-human resume command summary guard:
The restart option summary in `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` now
mirrors the stable post-human resume script and read-only
`north-star-resume-check` command, so downstream handoff summaries carry the
same safe resume path as the full option and Markdown card. Stable scan now
flags missing, drifted, or forbidden resume-command material in the summary
with `next-human-resume-command-summary-*` violations and routes them to stable
handoff repair instead of treating them as completion authority. Focused
coverage passed (`5 passed`). Live refresh
`live-north-star-watch-refresh-before-resume-summary-guard-20260514`
regenerated read-only current handoff state. Live next-human card
`live-north-star-next-human-action-after-resume-summary-guard-20260514`
published a restart summary containing the read-only resume command. Live
stable scan `live-north-star-stable-scan-after-resume-summary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`next_human_action_resume_command_violation_count: 0`, and clean handoff and
unblock next-human mirrors. Fresh hard gate
`live-north-star-completion-gate-after-resume-summary-guard-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Post-correction read-only gate refresh:
Read-only resume check
`live-north-star-resume-check-refresh-20260514b` reconfirmed that the running
Revit bridge is still stale before human restart/reload. It reported
`status: blocked_human_or_real_condition`, failed bridge checks
`loaded_build_current` and `bridge_readiness_ready`, four blocked gates, 17
unsatisfied requirements, no autonomous progress, and zero safety guard
violations. Read-only watch refresh
`live-north-star-watch-refresh-after-resume-refresh-20260514b` republished the
current handoff and approval preflight, observed Revit idle with no visible
dialogs, and still reported `requires_revit_restart_or_reload: true` with
`failed_bridge_checks: ["loaded_build_current"]`. Stable scan
`live-north-star-stable-scan-after-watch-refresh-20260514b` then reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
and zero unblock mirror drift. Fresh hard gate
`live-north-star-completion-gate-after-watch-refresh-20260514b` still reported
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. No
goal-completion update is permitted from this state.

Pre-human resume check and approval-expiry hygiene:
Live read-only resume check
`live-north-star-resume-check-before-human-restart-20260514` correctly stayed
blocked before the human-safe Revit restart/reload. Bridge validation failed on
`loaded_build_current` and `bridge_readiness_ready`, confirming that the
installed current DLL is not yet the DLL loaded by the running Revit session.
That resume check also exposed a stale approval-preflight condition in the
nested safety guard: the stable artifact scan reported stale approval
credential leaks after the prior preflight expired. The repair path was
read-only: `live-north-star-watch-refresh-after-stale-resume-check-20260514`
republished the current handoff with `--refresh-approval-preflight` and did not
focus, click, type, invoke UIA, queue bridge writes, restart, close, save, sync,
reload, detach, upgrade, or modify the model. Follow-up stable scan
`live-north-star-stable-scan-after-stale-resume-refresh-20260514` reported
`status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, clean read-only script guard status, and
zero forbidden matches. Fresh hard gate
`live-north-star-completion-gate-after-stale-resume-refresh-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. This
confirms the goal remains active and incomplete; the required next step is still
the human-safe Revit restart/reload plus the post-human resume check.

Current handoff refresh ordering:
Direct `north-star-current-handoff` now refreshes
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` after publishing the stable handoff,
then refreshes `NORTH_STAR_COMPLETION_GATE_CURRENT.*` again so stale
preflight/unblock mirrors do not persist until a later watch cycle.
`north-star-unblock-readiness` also ignores stale preflight alignment on its own
two stable output files while it is rewriting them, with direct self-refresh
regression coverage proving that stable scan still flags the same stale files
outside the rewrite path. Targeted handoff/unblock ordering tests passed
(`6 passed`), the full Revit operator/plugin slice passed (`364 passed`),
compileall passed, and `git diff --check` passed with only the existing
LF-to-CRLF warnings for `.gitignore` and `pyproject.toml`. Live
`live-north-star-current-handoff-patched-refresh-20260514` reported
`unblock_readiness_refreshed_after_handoff.stable_handoff_guard_violation_count:
0` and
`completion_gate_refreshed_after_unblock_readiness.safety_guard_violation_count:
0`. Follow-up stable scan
`live-north-star-stable-scan-after-patched-handoff-20260514` reported
`status: clean` and `violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-patched-handoff-20260514` still reported
`north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, and zero safety guard violations. The north-star goal
remains active and incomplete.

Expired approval-preflight recovery:
After the approval preflight expired, live stable scan correctly reported stale
approval-artifact violations instead of allowing approval-facing artifacts to
remain usable. The read-only watch refresh
`live-north-star-watch-refresh-after-expired-preflight-20260514` republished
approval preflight and current handoff artifacts without Revit save/sync/model
actions. Follow-up stable scan
`live-north-star-stable-scan-after-expired-preflight-refresh-20260514` reported
`status: clean`, `violation_count: 0`,
`preflight_alignment_violation_count: 0`,
`stale_approval_violation_count: 0`, and clean read-only script guard status.
Fresh hard gate
`live-north-star-completion-gate-after-expired-preflight-refresh-20260514`
still reported `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Current blocked handoff refresh:
The latest human-facing packets were refreshed from the current hard gate
without Revit UI/model execution. `live-north-star-human-gate-packet-final-
blocked-refresh-20260514` reported
`status: blocked_human_or_real_condition`, `blocked_gap_count: 4`,
`autonomous_progress_available: false`, and `may_call_update_goal: false`.
`live-north-star-next-human-action-final-blocked-refresh-20260514` reported
three human/real-condition options:
`human-restart-or-reload-revit`, `provide-exact-human-approval-phrase`, and
`wait-for-real-recovery-condition`, with `may_execute_from_this_result: false`
and `may_call_update_goal: false`. Follow-up stable scan
`live-north-star-stable-scan-after-human-packets-refresh-20260514` reported
`status: clean`, `violation_count: 0`,
`preflight_alignment_violation_count: 0`,
`stale_approval_violation_count: 0`, and zero human-gate/completion-guard
violations. Fresh hard gate
`live-north-star-completion-gate-after-human-packets-refresh-20260514` still
reported `north_star_complete: false`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. There is no current autonomous route to completion.

Current add-in build/install state:
The local machine had only .NET runtimes, so a user-local .NET 8 SDK was
installed under `%LOCALAPPDATA%\hermes\dotnet-sdk` to build the Revit 2025
operator add-in without requiring machine-wide SDK installation. The current
add-in source was built into an unlocked output folder,
`tools\revit_operator\addin\bin\Release\net8.0-windows-current`, signed with
the Hermes local code-signing certificate, and the Revit 2025 manifest now
points to that fresh signed DLL. The verifier was updated so the default local
Hermes assembly resolver accepts the newest known Hermes output path instead of
requiring the locked in-use DLL path. Focused resolver/bridge tests passed
(`6 passed`), the full Revit operator/plugin slice passed (`366 passed`), and
compileall passed. Live add-in security preflight
`live-addin-security-preflight-after-current-path-resolver-20260514` reported
`status: verified`, `expected_local_hermes_addin: true`,
`needs_trust_addin: false`, `can_consider_always_load_after_human_approval:
true`, and `signature.status: Valid`. Live bridge readiness
`live-bridge-readiness-after-current-path-resolver-20260514` now passes
`source_project_present`, `built_assembly_present`, `manifest_present`,
`manifest_points_to_expected_assembly`, and `bridge_connected`; the only
remaining failed check is `loaded_build_current`, so
`requires_revit_restart_or_reload: true`. Restart handoff
`live-bridge-restart-plan-after-current-dll-install-20260514` refreshed the
no-save checklist with `addin_security_status: verified` and the new expected
assembly path. Follow-up stable scan
`live-north-star-stable-scan-after-current-dll-install-20260514` reported
`status: clean`, `violation_count: 0`, and zero restart-checklist bridge-cause
or completion-guard violations. Fresh hard gate
`live-north-star-completion-gate-after-current-dll-install-20260514` remains
blocked with `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations.

Bridge restart checklist completion guard:
The bridge restart/no-save checklist now points humans back to the hard
completion gate, not to status or audit proxy artifacts. The generated
checklist requires a fresh `north-star-completion-gate` or
`north-star-resume-check.completion_gate` with `completion_allowed: true`,
`may_call_update_goal: true`, and `audit_completion_authorized: true`, and says
status/audit summaries are diagnostic only. Stable scan now verifies this text
whenever the `human-restart-or-reload-revit` option is present; drift raises
`restart-checklist-completion-guard-*` violations and the hard gate routes the
issue to stable handoff repair. Focused restart-checklist guard tests passed
(`7 passed`). Live restart plan
`live-bridge-restart-plan-completion-guard-20260514` regenerated the checklist
read-only, verified the add-in manifest/signature, and still reported
`human_restart_required` because the loaded Revit bridge is stale. Live watch
refresh `live-north-star-watch-after-checklist-guard-20260514` republished the
current handoff and kept completion blocked. Live stable scan
`live-north-star-stable-scan-after-checklist-guard-20260514` reported
`status: clean`, `violation_count: 0`, and
`restart_no_save_checklist_completion_guard_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-checklist-guard-20260514` still reported
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Autonomous stop stable guard:
The stable artifact scan and hard completion gate now validate
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json.autonomous_stop` against the current
hard completion gate. When completion is blocked by human approval, human
action, or a real Revit condition and no autonomous progress path remains, the
unblock packet must publish `autonomous_stop.active: true`, allow only
observation/read-only refresh command kinds, keep all execution/update-goal
authority false, carry no credential material, mark its refresh command
read-only, and mirror the blocked gap IDs from the hard gate. Stable scan also
checks the human Markdown section and the nested stop refresh command. Focused
coverage passed (`12 passed`), the full Revit operator/plugin slice passed
(`361 passed`), and compileall passed. Live
`live-north-star-unblock-readiness-after-autonomous-stop-guard-20260514`
regenerated the unblock packet with `autonomous_stop.active: true` and
`safe_refresh_read_only: true`. The first guard scan correctly rejected stale
approval artifacts after the previous preflight expired; read-only watch refresh
`live-north-star-watch-refresh-after-autonomous-stop-guard-20260514`
republished the current handoff without execution. Final stable scans
`live-north-star-stable-scan-final-after-autonomous-stop-guard-20260514` and
`live-north-star-stable-scan-final-after-gate-autonomous-stop-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`unblock_autonomous_stop_violation_count: 0`,
`unblock_refresh_command_violation_count: 0`,
`stable_current_metadata_violation_count: 0`,
`stale_approval_violation_count: 0`, and
`stable_readonly_script_guard_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-autonomous-stop-guard-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Autonomous stop handoff:
`north-star-unblock-readiness` now writes an `autonomous_stop` block whenever
the hard completion gate is blocked on human approval, human action, or a real
Revit condition and no autonomous progress path remains. The block explicitly
limits the next command kinds to observation and read-only refresh, keeps
`may_call_update_goal`, `audit_completion_authorized`, and
`may_execute_from_this_result` false, records that no credential material is
included, and restates that Hermes must not execute UI/model actions,
restart/reload Revit, answer prompts, call bridge action endpoints, or call
`update_goal` from the unblock packet. Focused unblock-readiness coverage
passed (`8 passed`), the full Revit operator/plugin slice passed
(`359 passed`), and compileall passed. Live
`live-north-star-unblock-readiness-after-autonomous-stop-20260514` wrote
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` in the live bridge sandbox with
`autonomous_stop.active: true`, `allowed_next_command_kinds: observation,
read_only_refresh`, `credential_material_included: false`, and four blocked
gates. Live stable scan
`live-north-star-stable-scan-final-after-autonomous-stop-20260514` reported
`status: clean`, `violation_count: 0`,
`stable_current_metadata_violation_count: 0`,
`stale_approval_violation_count: 0`, and
`stable_readonly_script_guard_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-autonomous-stop-20260514` still reported
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Stable current metadata guard:
The stable artifact scan and hard completion gate now require each durable
current handoff JSON in the completion/waiting/handoff/ledger/next-human/unblock
family to publish `generated_at_utc`, `read_only: true`, and
`may_execute_from_this_result: false`. Drift raises
`stable-current-generated-at-missing`, `stable-current-readonly-drift`, or
`stable-current-execution-authority-*` and routes to stable handoff repair
rather than allowing a stale or executable-looking handoff to stand. Focused
metadata guard coverage passed (`18 passed`), the full Revit operator/plugin
slice passed (`359 passed`), and compileall passed. Live watch refresh
`live-north-star-watch-refresh-before-stable-current-metadata-20260514`
refreshed approval preflight and republished the current handoff read-only
while observing Revit idle with no dialogs. Final stable scan
`live-north-star-stable-scan-final-after-stable-current-metadata-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_current_metadata_violation_count: 0`, and
`stable_readonly_script_guard_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-final-after-stable-current-metadata-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and `safety_guard_violation_count: 0`.
The north-star goal remains active and incomplete.

Next-human resume script path guard:
The stable artifact scan and hard completion gate now verify that
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` points
`human-restart-or-reload-revit.post_action_resume_script` at the stable
sandbox-root `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`, and that
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` shows the same stable
`Resume script:` line. Drift raises `next-human-resume-script-path-drift` or
`next-human-resume-script-markdown-drift` and routes to stable handoff repair.
Targeted resume-script-path tests passed (`2 passed`), the focused
north-star/next-human/stable suite passed (`86 passed`), the full Revit
operator/plugin slice passed (`337 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-after-next-human-resume-path-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`next_human_action_resume_script_path_violation_count: 0`, and
`next_human_action_restart_checklist_path_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-resume-path-guard-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Final next-human checklist path guard verification:
After narrowing the guard to apply only when a stable/source restart checklist
is present, targeted restart-checklist-path tests passed (`3 passed`), the
focused north-star/next-human/stable suite passed (`84 passed`), the full Revit
operator/plugin slice passed (`335 passed`), and compileall passed. Live stable
scan
`live-north-star-stable-scan-after-next-human-checklist-path-guard-final-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`next_human_action_restart_checklist_path_violation_count: 0`, and
`restart_no_save_checklist_bridge_cause_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-checklist-path-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Next-human restart checklist path guard:
The stable artifact scan and hard completion gate now verify that
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` points
`human-restart-or-reload-revit.checklist_path` at the stable sandbox-root
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`, and that
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` shows the same stable `Checklist:`
line. Run-specific restart-plan checklist paths remain allowed only as
`source_checklist_path`. Drift raises
`next-human-restart-checklist-path-drift` or
`next-human-restart-checklist-markdown-drift` and routes to stable handoff
repair. Targeted restart-checklist-path tests passed (`3 passed`). Live stable
scan `live-north-star-stable-scan-after-next-human-checklist-path-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`,
`next_human_action_restart_checklist_path_violation_count: 0`, and
`restart_no_save_checklist_bridge_cause_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-checklist-path-guard-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Stable restart checklist path handoff:
The next-human-action card now prefers the stable sandbox-root
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` path for the
`human-restart-or-reload-revit` option while retaining the run-specific
`bridge_restart_no_save_checklist.md` as `source_checklist_path` in JSON. This
keeps the human-facing `Checklist:` line pointed at the current handoff file
rather than a transient run artifact. Targeted coverage passed (`1 passed`),
the focused north-star/next-human/stable suite passed (`82 passed`), the full
Revit operator/plugin slice passed (`333 passed`), and compileall passed. Live
watch refresh
`live-north-star-watch-refresh-after-stable-checklist-path-20260514`
republished the current handoff; `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`
now reports `checklist_path:
...\NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` and preserves the
old run artifact as `source_checklist_path`. Stable scan
`live-north-star-stable-scan-after-stable-checklist-path-20260514` reported
`status: clean`, `violation_count: 0`, and
`restart_no_save_checklist_bridge_cause_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-stable-checklist-path-20260514` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Bridge restart checklist cause guard:
The stable artifact scan and hard completion-gate safety guard now verify that
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` carries the bridge
restart cause fields when the current next-human-action card exposes a
`human-restart-or-reload-revit` option with bridge-cause metadata. The guard
requires the checklist to include the `Bridge Reload Cause` section, the stale
loaded-addin root-cause phrase, `restart_or_reload_required`,
`failed_readiness_checks: loaded_build_current`, loaded-build failure details,
expected `bridge_protocol_version 0.2`,
`source_capability_stamp continuous-idling-status-file-retry-v2`, continuous-Idling and
`SetRaiseWithoutDelay` expectations, and observed loaded metadata. Drift raises
`restart-checklist-bridge-cause-drift` and routes to stable handoff repair.
Targeted bridge-cause guard tests passed (`4 passed`), the focused
north-star/stable guard suite passed (`76 passed`), the full Revit
operator/plugin slice passed (`333 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-after-checklist-bridge-cause-guard-final-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and
`restart_no_save_checklist_bridge_cause_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-checklist-bridge-cause-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Bridge restart no-save checklist cause clarity:
`bridge-restart-validation-plan` now writes the immediate stale loaded-addin
cause directly into the human no-save/no-sync checklist, not only into the
next-human-action card. The current
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` includes a
`Bridge Reload Cause` section with `technical_cause: Loaded Revit add-in is
stale or lacks current bridge build metadata.`, `restart_or_reload_required:
True`, `failed_readiness_checks: loaded_build_current`, failed loaded-build
metadata checks, expected loaded metadata
`bridge_protocol_version=0.2`,
`source_capability_stamp=continuous-idling-status-file-retry-v2`,
`supports_continuous_idling=True`, and
`uses_idling_set_raise_without_delay=True`, plus observed missing loaded
metadata. Targeted checklist tests passed (`2 passed`), the full Revit
operator/plugin slice passed (`331 passed`), and compileall passed. Live
restart plan `live-bridge-restart-validation-plan-checklist-cause-20260514`
reported `status: human_restart_required`,
`pre_restart_files_ready: true`, `ready_for_continuous_bridge_now: false`, and
`restart_or_reload_required: true`. Watch refresh
`live-north-star-watch-refresh-after-checklist-cause-20260514` republished the
current handoff read-only. Stable scan
`live-north-star-stable-scan-after-checklist-cause-20260514` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
and `next_human_action_markdown_bridge_cause_violation_count: 0`. Fresh hard
gate `live-north-star-completion-gate-after-checklist-cause-20260514` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`,
`unsatisfied_count: 17`, and `safety_guard_violation_count: 0`. The
north-star goal remains active and incomplete.

Latest preflight-expiry refresh:
Stable scan `live-north-star-stable-scan-preflight-expiry-check-20260513`
detected that the previous approval preflight had expired at
`2026-05-13T23:18:16Z` and correctly reported stale approval-credential leaks
in the current handoff/approval artifacts. Read-only watch task
`live-north-star-watch-refresh-after-preflight-expiry-20260513` refreshed the
approval preflight and current handoff without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit. It observed Revit `idle` with zero dialogs and refreshed the
preflight through `2026-05-13T23:34:01Z`. Final stable scan
`live-north-star-stable-scan-after-preflight-refresh-final-20260513` reported
`preflight_status: fresh`, `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and
`recovery_snapshot_qualification_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-preflight-refresh-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest stale-approval remediation follow-up hardening:
The hard completion-gate safety follow-up for stale approval credential leaks
now points to the exact read-only refresh sequence:
`north-star-watch --refresh-approval-preflight --publish-current-handoff
--checks 1 --poll 0`, then `north-star-stable-artifact-scan`, then
`north-star-completion-gate`. It also tells agents to use
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` for the context-matched
`safe_supervision_refresh_command` / `safe_supervision_refresh_powershell`, so
future stale-token remediation does not rely on a generic handoff-only repair.
Targeted stale-follow-up tests passed (`3 passed`), the focused stable-scan/
completion-gate/approval-metadata group passed (`55 passed`), the full Revit
operator/plugin slice passed (`306 passed`), and compileall passed. Final live
stable scan `live-north-star-stable-scan-after-stale-followup-guard-final-20260513`
reported `preflight_status: fresh`, expiry `2026-05-13T23:34:01Z`,
`status: clean`, `violation_count: 0`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-stale-followup-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest approval-preflight refresh advisory:
`north-star-stable-artifact-scan` now reports a read-only
`preflight_refresh_advisory` when the approval preflight is still valid but near
expiry. This does not authorize any action; it points future agents to the
context-matched read-only watch refresh before approval-bearing artifacts become
stale. Targeted advisory checks passed (`3 passed`), the focused stable-scan/
completion-gate/approval-metadata group passed (`56 passed`), the full Revit
operator/plugin slice passed (`307 passed`), and compileall passed. Live stable
scan `live-north-star-stable-scan-after-preflight-advisory-final-20260513`
reported `status: clean`, `violation_count: 0`,
`preflight_refresh_advisory.status: refresh_soon`,
`refresh_recommended: true`, about 90 seconds remaining before the
`2026-05-13T23:34:01Z` preflight expiry, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-preflight-advisory-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. A follow-up read-only watch refresh
`live-north-star-watch-refresh-after-preflight-advisory-20260513` refreshed the
preflight and current handoff without focusing, clicking, typing, invoking UIA,
saving, syncing, reloading, detaching, upgrading, closing, or modifying Revit.
Final stable scan
`live-north-star-stable-scan-after-preflight-advisory-refresh-final-20260513`
reported `status: clean`, `violation_count: 0`,
`preflight_refresh_advisory.status: fresh`,
`refresh_recommended: false`, about 807 seconds remaining before the refreshed
`2026-05-13T23:48:01Z` expiry, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-preflight-advisory-refresh-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. The north-star goal remains active and
incomplete.

Latest stable read-only script guard:
`north-star-stable-artifact-scan` and the hard completion-gate safety guard now
inspect stable PowerShell handoff scripts. `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`
and `NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` must contain only the
expected read-only validation command names, must include the three-field
completion gate check, and must not expose `--execute`, `--approval-token`,
direct UI commands, approved-execution commands, or write-oriented commands.
Targeted script-guard tests passed (`3 passed`), the focused stable/completion
group passed (`55 passed`), the full Revit operator/plugin slice passed
(`309 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-readonly-script-guard-20260513` reported
`status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, checked 2 scripts,
`forbidden_match_count: 0`, `missing_completion_guard_count: 0`, and
`stable_readonly_script_guard_violation_count: 0`. Because the approval
preflight was near expiry, read-only watch refresh
`live-north-star-watch-refresh-after-readonly-script-guard-20260513` refreshed
the preflight and current handoff without focusing, clicking, typing, invoking
UIA, saving, syncing, reloading, detaching, upgrading, closing, or modifying
Revit. Final stable scan
`live-north-star-stable-scan-after-readonly-script-guard-refresh-final-20260513`
reported `status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, checked 2 scripts,
`forbidden_match_count: 0`, `missing_completion_guard_count: 0`,
`preflight_refresh_advisory.status: fresh`, about 813 seconds remaining, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-readonly-script-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Latest stable script sandbox/update-goal binding guard:
The stable read-only script guard now also verifies that both stable PowerShell
handoff scripts are bound to the current sandbox and that any `update_goal`
reference appears only inside an explicit `do not call update_goal` warning.
This prevents a stale or manually edited script from silently running against a
different sandbox or auto-completing the thread outside the hard completion
gate. Targeted script-guard tests passed (`3 passed`), the focused stable/
completion group passed (`56 passed`), the full Revit operator/plugin slice
passed (`310 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-script-binding-guard-20260513` reported
`status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, checked 2 scripts,
`forbidden_match_count: 0`, `unsafe_goal_update_reference_count: 0`,
`missing_sandbox_binding_count: 0`, `missing_completion_guard_count: 0`,
`preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-script-binding-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Latest watch top-level completion field mirror:
`north-star-watch` now mirrors the fresh hard completion gate at the top level
of its JSON result, including `completion_allowed`, `may_call_update_goal`,
`audit_completion_authorized`, blocked gap counts, unsatisfied count, and
safety guard violation count. This prevents read-only refresh/watch output from
being misread when the nested `completion_gate` object is not inspected.
Targeted watch tests passed (`4 passed`), the focused north-star group passed
(`60 passed`), the full Revit operator/plugin slice passed (`310 passed`), and
compileall passed. Live read-only watch
`live-north-star-watch-top-level-gate-fields-20260513` refreshed approval
preflight and current handoff, then reported top-level
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`, matching its nested completion gate.
Final stable scan
`live-north-star-stable-scan-after-watch-top-level-fields-20260513` reported
`status: clean`, `violation_count: 0`,
`preflight_refresh_advisory.status: fresh`,
`stable_readonly_script_guard.status: clean`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-watch-top-level-fields-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Latest watch completion mirror stable-scan guard:
`north-star-stable-artifact-scan` and the hard completion-gate safety guard now
inspect the latest `revit_operator_runs/*/north_star_watch.json` artifact. If a
watch artifact exists, its top-level completion fields must be present and must
mirror its nested hard `completion_gate`; otherwise the stable scan and hard
gate report safety violations. Targeted watch mirror tests passed (`6 passed`),
the focused north-star/stable-scan group passed (`62 passed`), the full Revit
operator/plugin slice passed (`312 passed`), and compileall passed. Live
read-only watch
`live-north-star-watch-refresh-for-watch-mirror-guard-20260513` refreshed
approval preflight/current handoff and reported `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. Final stable scan
`live-north-star-stable-scan-after-watch-mirror-guard-20260513` reported
`status: clean`, `violation_count: 0`,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`,
`missing_top_level_field_count: 0`, `mismatch_count: 0`,
`preflight_refresh_advisory.status: fresh`,
`stable_readonly_script_guard.status: clean`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-watch-mirror-guard-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Latest watch mirror hard-gate regression:
The hard completion gate now has explicit regression coverage proving that a
drifting latest `north_star_watch.json` artifact blocks completion even when a
test audit otherwise reports completion. The safety guard reports
`latest-watch-top-level-completion-field-mismatch` and returns the
`repair-stable-handoff-artifacts` follow-up action. Targeted watch mirror/hard
gate checks passed (`4 passed`), the focused north-star/stable group passed
(`63 passed`), the full Revit operator/plugin slice passed (`313 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-watch-mirror-hard-gate-20260513` reported
`status: clean`, `violation_count: 0`,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`,
`missing_top_level_field_count: 0`, `mismatch_count: 0`,
`preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-watch-mirror-hard-gate-20260513` still
reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Latest resume completion mirror stable-scan guard:
`north-star-stable-artifact-scan` and the hard completion-gate safety guard now
also inspect the latest `revit_operator_runs/*/north_star_resume_check.json`
artifact. If a resume-check artifact exists, its top-level completion fields
must be present and must mirror the nested hard `completion_gate`; otherwise
the stable scan and hard gate report safety violations. The first live scan
after adding this guard correctly found that the resume artifact was missing
top-level blocked-gap/count fields. `north-star-resume-check` now writes
`blocked_gap_ids`, `blocked_gap_count`, `blocked_gate_count`,
`unsatisfied_count`, and `safety_guard_violation_count` at the top level and
keeps the nested gate values needed for the mirror check. Targeted resume
mirror tests passed (`4 passed`), the focused north-star/stable group passed
(`67 passed`), the full Revit operator/plugin slice passed (`316 passed`), and
compileall passed. Live read-only resume check
`live-north-star-resume-check-after-resume-artifact-fix-20260513` reported
`status: blocked_human_or_real_condition`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`bridge_validation_ran: true`, `bridge_validation.status: failed`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 70` because it still saw stale preflight
violations from the artifact it replaced. The subsequent read-only watch
refresh `live-north-star-watch-refresh-after-resume-artifact-fix-20260513`
refreshed approval preflight/current handoff and reported
`safety_guard_violation_count: 0` without focusing, clicking, typing, invoking
UIA, saving, syncing, reloading, detaching, upgrading, closing, or modifying
Revit. Final stable scan
`live-north-star-stable-scan-after-watch-refresh-20260513` reported
`status: clean`, `violation_count: 0`,
`latest_resume_completion_mirror.status: clean`,
`latest_resume_completion_mirror_violation_count: 0`,
`latest_watch_completion_mirror.status: clean`,
`latest_watch_completion_mirror_violation_count: 0`,
`preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-watch-refresh-20260513` still reported
`status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Unblock-readiness stable-scan mirror guard:
`north-star-stable-artifact-scan` now checks whether
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` accurately mirrors the current
`NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` stable-scan summary. The guard
distinguishes optimistic drift from conservative stale data: optimistic drift,
such as an unblock packet claiming the stable scan is clean while the current
stable scan has violations, becomes a safety violation and also blocks the hard
completion gate; pessimistic drift is reported for refresh but does not grant
execution authority or block completion by itself. Targeted mirror tests passed
(`4 passed`), the focused north-star/stable group passed (`71 passed`), the
full Revit operator/plugin slice passed (`320 passed`), and compileall passed.
The first live stable scan
`live-north-star-stable-scan-detect-unblock-mirror-drift-20260513` reported
`status: violations`, `violation_count: 1`,
`unblock_stable_scan_mirror.status: violations`, one mirror violation, and
three mismatched fields. After refining the rule and running read-only watch
refresh `live-north-star-watch-refresh-clear-pessimistic-unblock-mirror-20260513`,
final stable scan
`live-north-star-stable-scan-after-unblock-mirror-clear-refresh-20260513`
reported `status: clean`, `violation_count: 0`,
`unblock_stable_scan_mirror.status: ok`,
`unblock_stable_scan_mirror_violation_count: 0`,
`optimistic_mismatch_count: 0`, `pessimistic_mismatch_count: 0`,
`preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-unblock-mirror-clear-refresh-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Next-human markdown approval coverage guard:
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` now has to mirror the approval
coverage boundary from `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`. The
generated Markdown prints `approval_blocker_gap_ids`, `selected_item_gap_ids`,
`remaining_approval_gap_ids_after_selected_item`,
`selected_item_covers_all_approval_blockers`, and
`approval_coverage_fields_present`, so a human-facing approval phrase cannot be
mistaken for approval of all remaining UI blockers when it only covers one
selected item. Targeted next-human coverage tests passed (`4 passed`), the
focused north-star/stable group passed (`73 passed`), the full Revit
operator/plugin slice passed (`321 passed`), and compileall passed. Live stable
scan
`live-north-star-stable-scan-detect-next-human-markdown-coverage-20260513`
correctly reported `status: violations`, `violation_count: 1`,
`next_human_action_markdown_approval_coverage.status: violations`, one
next-human markdown coverage violation, and five missing coverage lines from
the stale Markdown. Read-only watch refresh
`live-north-star-watch-refresh-after-next-human-markdown-coverage-20260513`
republished current handoff artifacts without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit. Final stable scan
`live-north-star-stable-scan-after-next-human-markdown-coverage-refresh-20260513`
reported `status: clean`, `violation_count: 0`,
`next_human_action_markdown_approval_coverage.status: clean`,
`next_human_action_markdown_approval_coverage_violation_count: 0`,
`missing_line_count: 0`, `completion_gate_markdown_approval_coverage.status:
clean`, `preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-markdown-coverage-refresh-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Human gate packet approval gap mirror:
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md` now mirrors every approval item's
`gap_ids` from `NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json`. This keeps the
human-facing approval handoff tied to the exact north-star blocker IDs each
approval item can help satisfy, instead of relying only on prose around the
approval phrase. The stable artifact scan and hard completion-gate safety
guard both fail closed if the Markdown is missing, unreadable, or missing any
approval item gap line, and those failures are routed to stable handoff repair.
Targeted approval-gap tests passed (`3 passed`), the focused north-star/stable
group passed (`75 passed`), the full Revit operator/plugin slice passed
(`323 passed`), and compileall passed. The first live stable scan
`live-north-star-stable-scan-detect-human-gate-approval-gap-20260513`
correctly reported `status: violations`, `violation_count: 1`,
`human_gate_packet_markdown_approval_gap.status: violations`, one
human-gate approval-gap violation, and five missing gap lines from the stale
Markdown. Read-only watch refresh
`live-north-star-watch-refresh-after-human-gate-approval-gap-20260513`
republished current handoff artifacts without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit. Final stable scan
`live-north-star-stable-scan-after-human-gate-approval-gap-refresh-20260513`
reported `status: clean`, `violation_count: 0`,
`human_gate_packet_markdown_approval_gap.status: clean`,
`human_gate_packet_markdown_approval_gap_violation_count: 0`,
`missing_line_count: 0`, `preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-gate-approval-gap-refresh-20260513`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Ready approvals approval gap mirror:
`NORTH_STAR_READY_APPROVALS_CURRENT.md` now mirrors every ready approval item's
`gap_ids` from `NORTH_STAR_READY_APPROVALS_CURRENT.json`. This is stricter
than the human-gate packet guard because ready approvals can include exact
human approval phrases and guarded execute commands; the Markdown must show
which blocker each ready item applies to. The stable artifact scan and hard
completion-gate safety guard now fail closed if the ready-approvals Markdown is
missing, unreadable, or missing any ready item gap line, and those failures are
routed to stable handoff repair. Targeted ready-approval gap tests passed
(`3 passed`), the focused north-star/stable group passed (`80 passed`), the
full Revit operator/plugin slice passed (`325 passed`), and compileall passed.
The first live stable scan
`live-north-star-stable-scan-detect-ready-approvals-approval-gap-20260514`
correctly reported `status: violations`, `violation_count: 1`,
`ready_approvals_markdown_approval_gap.status: violations`, one ready-approval
gap violation, and three missing gap lines from the stale Markdown. Read-only
watch refresh
`live-north-star-watch-refresh-after-ready-approvals-approval-gap-20260514`
republished current handoff artifacts without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit. Final stable scan
`live-north-star-stable-scan-after-ready-approvals-approval-gap-refresh-20260514`
reported `status: clean`, `violation_count: 0`,
`ready_approvals_markdown_approval_gap.status: clean`,
`ready_approvals_markdown_approval_gap_violation_count: 0`,
`missing_line_count: 0`, `preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-ready-approvals-approval-gap-refresh-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Next approval approval gap mirror:
`NORTH_STAR_NEXT_APPROVAL_CURRENT.md` now mirrors the selected approval item's
`gap_ids` from `NORTH_STAR_NEXT_APPROVAL_CURRENT.json`. This is the most
focused approval handoff because it contains the single selected approval
candidate, exact human approval phrase, and guarded execute command, so the
selected item's blocker scope must be visible in Markdown. The stable artifact
scan and hard completion-gate safety guard now fail closed if the next-approval
Markdown is missing, unreadable, or missing the selected item gap line, and
those failures are routed to stable handoff repair. Targeted next-approval gap
tests passed (`4 passed`), the focused north-star/stable group passed
(`84 passed`), the full Revit operator/plugin slice passed (`327 passed`), and
compileall passed. The first live stable scan
`live-north-star-stable-scan-detect-next-approval-approval-gap-20260514`
correctly reported `status: violations`, `violation_count: 1`,
`next_approval_markdown_approval_gap.status: violations`, one next-approval
gap violation, and one missing selected-item gap line from the stale Markdown.
Read-only watch refresh
`live-north-star-watch-refresh-after-next-approval-approval-gap-20260514`
republished current handoff artifacts without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit. Final stable scan
`live-north-star-stable-scan-after-next-approval-approval-gap-refresh-20260514`
reported `status: clean`, `violation_count: 0`,
`next_approval_markdown_approval_gap.status: clean`,
`next_approval_markdown_approval_gap_violation_count: 0`,
`missing_line_count: 0`, `ready_approvals_markdown_approval_gap.status:
clean`, `preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-approval-approval-gap-refresh-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Waiting-state approval gap mirror:
`NORTH_STAR_WAITING_STATE_CURRENT.json` and
`NORTH_STAR_WAITING_STATE_CURRENT.md` now mirror the selected next approval
item's `gap_ids` from `NORTH_STAR_NEXT_APPROVAL_CURRENT.json`. This keeps the
currently exposed approval phrase tied to the exact blocker scope visible in
the waiting-state handoff. The stable artifact scan and hard completion-gate
safety guard now fail closed if the waiting-state JSON is missing
`next_approval_gap_ids`, if those IDs drift from the selected next-approval
item, or if the Markdown omits the matching `next_approval_gap_ids` line.
Targeted waiting-state approval gap tests passed (`3 passed`), the focused
north-star/stable group passed (`126 passed`), the full Revit operator/plugin
slice passed (`329 passed`), and compileall passed. The first live stable scan
`live-north-star-stable-scan-detect-waiting-state-approval-gap-20260514`
correctly reported `status: violations`, `violation_count: 2`,
`waiting_state_approval_gap.status: violations`, two waiting-state approval
gap violations, and one missing Markdown line from stale handoff artifacts.
Read-only watch refresh
`live-north-star-watch-refresh-after-waiting-state-approval-gap-20260514`
republished current handoff artifacts without focusing, clicking, typing,
invoking UIA, saving, syncing, reloading, detaching, upgrading, closing, or
modifying Revit, and reported `safety_guard_violation_count: 0`. Final stable
scan
`live-north-star-stable-scan-after-waiting-state-approval-gap-refresh-20260514`
reported `status: clean`, `violation_count: 0`,
`waiting_state_approval_gap.status: clean`,
`waiting_state_approval_gap_violation_count: 0`, `missing_line_count: 0`,
`preflight_refresh_advisory.status: fresh`, and
`stale_approval_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-waiting-state-approval-gap-refresh-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`safety_guard_violation_count: 0`, and blocked gaps
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`. The
north-star goal remains active and incomplete.

Continuation gate check:
Read-only watch `live-north-star-watch-continue-20260514` refreshed the live
sandbox handoff and reported `status: no_change`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
`safety_guard_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-continue-20260514` still reported
`status: blocked`, `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `autonomous_progress_available: false`,
and `human_or_real_condition_required: true`. A dry-run of
`ribbon-action --name view-tab --limit 50` located exactly one enabled Revit
`View` ribbon button and did not execute it; policy remained
`approval_required` for the UI invoke. Approval-plan refresh
`live-north-star-approval-plan-continue-20260514` produced ready approval
items for `safe-ribbon-view-tab`, `direct-uia-view-tab-select`, and
`approved-workflow-open-sheet`, but all require exact human approval phrases.
Additional dry-run evidence
`live-uia-view-tab-select-dry-run-inspect-20260514`,
`live-approved-workflow-open-sheet-dry-run-continue-20260514`,
`live-project-browser-plan-navigation-continue-20260514`, and
`live-request-activate-view-dry-run-continue-20260514d` confirmed the current
Revit document is idle and connected, found a single metadata-backed sheet
match for `S2.0` / `FOUNDATION PLAN`, planned the deterministic guarded add-in
`activate-view` route, and stopped at `approval_required` without executing any
UI or model-changing operation. Follow-up stable scan
`live-north-star-stable-scan-after-dryruns-20260514` remained clean, and hard
gate `live-north-star-completion-gate-after-dryruns-20260514` remained blocked
with the same four blocker IDs.
Stable scan `live-north-star-stable-scan-continue-20260514` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
`preflight_refresh_advisory.status: fresh`, and clean waiting-state,
next-approval, and ready-approvals approval-gap mirrors. The remaining blocked
gaps are still `bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the
north-star goal remains active and incomplete.

Bridge restart validation evidence:
`live-bridge-post-restart-validation-no-restart-20260514` first failed model
readiness because the expected path string included `.rvt` while the active
copied local document is the detached filename
`24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM_detached.rvt`.
Rerun
`live-bridge-post-restart-validation-no-restart-detached-path-20260514` used
the safer detached-local substring `Structural_Current Working-R25-BIM`; model
readiness passed, but bridge restart validation still failed because the
running add-in lacks current build metadata. Individual diagnostics
`live-verify-bridge-build-after-post-restart-check-20260514` and
`live-bridge-readiness-after-post-restart-check-20260514` reported
`status: stale_or_unverified` / `status: not_ready`: source project, built DLL,
manifest, manifest assembly path, and bridge connection are present, but
`loaded_build_current` failed because loaded add-in metadata is absent
(`bridge_protocol_version 0.2`, `continuous-idling-status-file-retry-v2`,
continuous-idling support, and `SetRaiseWithoutDelay` support are not reported
by the running Revit session). Restart handoff
`live-bridge-restart-validation-plan-after-stale-build-20260514` therefore
reported `status: human_restart_required`, `pre_restart_files_ready: true`,
`ready_for_continuous_bridge_now: false`, and
`restart_or_reload_required: true`, with explicit blocked automation:
Hermes must not close, restart, save, sync, reload, detach, upgrade, or modify
Revit/model contents. Refreshed handoff/watch
`live-north-star-watch-refresh-after-bridge-stale-20260514` and stable scan
`live-north-star-stable-scan-after-bridge-watch-refresh-20260514` stayed
read-only and clean; the current selected approval phrase remains for
`safe-ribbon-view-tab` and expires at `2026-05-14T01:52:22Z`. The north-star
goal remains active and incomplete until a human safely restarts/reloads Revit
and the post-restart checks report the current loaded bridge.

Bridge handoff technical-cause mirror:
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` and Markdown now expose the bridge
restart blocker's immediate technical cause, failed bridge checks, restart
requirement, and no-save checklist presence. For the current live state, the
human restart/reload option reports `bridge_technical_cause: Loaded Revit
add-in is stale or lacks current bridge metadata.`, `failed_bridge_checks:
loaded_build_current`, `requires_revit_restart_or_reload: true`, and
`no_save_checklist_present: true`. Targeted regression coverage passed
(`1 passed`), the focused north-star/stable suite passed (`126 passed`), the
full Revit operator/plugin slice passed (`329 passed`), and compileall passed.
Live refresh
`live-north-star-next-human-action-bridge-cause-20260514` wrote the new fields
to the stable next-human-action card, stable scan
`live-north-star-stable-scan-after-next-human-bridge-cause-20260514` reported
`status: clean`, and hard gate
`live-north-star-completion-gate-after-next-human-bridge-cause-20260514`
remained blocked with the same four blocker IDs and zero safety guard
violations. The north-star goal remains active and incomplete.

Bridge cause Markdown guard:
The stable artifact scan and hard completion-gate safety guard now require
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.md` to mirror the
`human-restart-or-reload-revit` bridge cause fields from
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`. If the Markdown omits the
technical cause, failed bridge checks, restart requirement, or no-save
checklist presence, the scan raises `next-human-markdown-bridge-cause-drift`
and the hard gate routes the issue to stable handoff repair. Targeted bridge
cause drift tests passed (`2 passed`), the focused north-star/stable suite
passed (`128 passed`), the full Revit operator/plugin slice passed
(`331 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-bridge-cause-watch-refresh-20260514`
reported `status: clean`, `violation_count: 0`,
`next_human_action_markdown_bridge_cause.status: clean`,
`next_human_action_markdown_bridge_cause_violation_count: 0`,
`stale_approval_violation_count: 0`, and
`preflight_refresh_advisory.status: fresh`. Fresh hard gate
`live-north-star-completion-gate-after-bridge-cause-watch-refresh-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
and `safety_guard_violation_count: 0`. The current selected approval phrase is
for `safe-ribbon-view-tab` and expires at `2026-05-14T02:06:51Z`; the
north-star goal remains active and incomplete.

Next-human resume command guard:
The stable artifact scan and hard completion-gate safety guard now validate the
human-visible post-restart resume command in
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*`. The
`human-restart-or-reload-revit` option must expose a read-only
`north-star-resume-check` command, include required context flags such as
`--sheet-number` and `--revit-version`, omit `--execute`, approval-token flags,
approval phrases, and direct UI/write commands, keep the PowerShell line in
sync with the command argument list, and mirror that exact `Resume command:`
line in Markdown. Drift raises `next-human-resume-command-*` violations and
routes to stable handoff repair. Targeted resume-command tests passed
(`2 passed`), the focused north-star/next-human/stable suite passed
(`88 passed`), the full Revit operator/plugin slice passed (`339 passed`), and
compileall passed. A first live scan correctly found stale approval credentials
after the previous preflight expired; read-only watch refresh
`live-north-star-watch-refresh-after-next-human-resume-command-guard-20260514`
refreshed preflight/current handoff while keeping completion false. Final live
stable scan
`live-north-star-stable-scan-after-next-human-resume-command-guard-final-20260514`
reported `status: clean`, `violation_count: 0`, and
`next_human_action_resume_command_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-resume-command-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Next-human resume command context guard:
The resume-command guard now also compares the
`human-restart-or-reload-revit.post_action_resume_command` arguments against
the latest expected Revit context from `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT`.
When expected title/path/view constraints exist, the stable scan requires the
resume command to include matching `--expected-title-contains`,
`--expected-path-contains`, `--expected-view-name`, and
`--expected-view-type` options in addition to `--sheet-number` and
`--revit-version`; missing or mismatched context raises
`next-human-resume-command-required-option-missing` or
`next-human-resume-command-context-mismatch` and routes to stable handoff
repair. Targeted resume-command context coverage passed (`4 passed`), the
focused north-star/next-human/stable suite passed (`90 passed`), the full
Revit operator/plugin slice passed (`341 passed`, with one existing pywinauto
deprecation warning), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-next-human-resume-command-context-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`next_human_action_resume_command_violation_count: 0`,
`missing_context_option_count: 0`, and `context_mismatch_count: 0`. Fresh hard
gate
`live-north-star-completion-gate-after-next-human-resume-command-context-guard-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
zero safety guard violations. The north-star goal remains active and
incomplete.

Human/real-condition boundary guard:
The stable handoff now mirrors the hard completion gate's "no autonomous
progress remains" boundary into `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` and
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*`. When the hard gate reports
`blocked_waiting_for_human_or_real_condition: true`, the stable scan and hard
completion gate require the human-facing artifacts to show
`autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and
`blocked_waiting_for_human_or_real_condition: true` in both JSON and Markdown.
Drift raises `human-real-boundary-*` violations and routes to stable handoff
repair. The implementation also expanded compact stable-artifact summaries so
unblock-readiness receives those completion-gate fields instead of falling back
to false defaults. Targeted boundary coverage passed (`3 passed`), the focused
north-star/unblock/stable suite passed (`96 passed`), the full Revit
operator/plugin slice passed (`343 passed`), and compileall passed. Live watch
refresh `live-north-star-watch-refresh-after-human-real-boundary-summary-fix-20260514`
republished the handoff without granting completion. Final live stable scan
`live-north-star-stable-scan-after-human-real-boundary-guard-final-20260514`
reported `status: clean`, `violation_count: 0`, and
`human_real_condition_boundary_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-real-boundary-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`, and
zero safety guard violations. The north-star goal remains active and
incomplete.

Expanded human/real-condition boundary guard:
The stable scan now validates the same hard human/real-condition boundary
across the broader human-facing handoff set:
`NORTH_STAR_HANDOFF_CURRENT.*`, `NORTH_STAR_WAITING_STATE_CURRENT.*`,
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.*`,
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*`, and
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*`. The human gate packet builder now
derives `blocked_waiting_for_human_or_real_condition` when older status
payloads do not provide it directly, and its Markdown renders the same field
so a human supervisor sees the boundary instead of only the JSON seeing it.
Targeted human-gate/boundary tests passed (`5 passed`), the focused
north-star handoff/gate slice passed (`99 passed`), the full Revit
operator/plugin slice passed (`344 passed`), and compileall passed. Live watch
refresh
`live-north-star-watch-refresh-after-expanded-human-real-boundary-guard-20260514`
republished the stable handoff read-only with 4 blocked gates, 17 unsatisfied
checks, and safety guard violations 0. Live stable scan
`live-north-star-stable-scan-after-expanded-human-real-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and checked 5 boundary
artifacts. Fresh hard gate
`live-north-star-completion-gate-after-expanded-human-real-boundary-guard-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Blocked-ledger boundary guard:
The blocked ledger is also part of the human-facing handoff contract. The
stable scan now validates `NORTH_STAR_BLOCKED_LEDGER_CURRENT.*` against the
same hard human/real-condition boundary, and
`_blocked_ledger_markdown` renders `autonomous_progress_available`,
`human_or_real_condition_required`, and
`blocked_waiting_for_human_or_real_condition` beside the existing completion
authority flags. Drift in the ledger Markdown raises
`human-real-boundary-markdown-drift` and routes through the same stable
handoff repair path. Targeted blocked-ledger/boundary coverage passed
(`5 passed`), the focused north-star handoff/gate slice passed (`102 passed`),
the full Revit operator/plugin slice passed (`345 passed`), and compileall
passed. Live watch refresh
`live-north-star-watch-refresh-after-blocked-ledger-boundary-guard-20260514`
republished the stable handoff read-only. Live stable scan
`live-north-star-stable-scan-after-blocked-ledger-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and checked 6 boundary
artifacts, including the blocked ledger. Fresh hard gate
`live-north-star-completion-gate-after-blocked-ledger-boundary-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Status/audit/approval-plan boundary guard:
The stable scan now validates `NORTH_STAR_STATUS_CURRENT.*`,
`NORTH_STAR_AUDIT_CURRENT.*`, and `NORTH_STAR_APPROVAL_PLAN_CURRENT.*` against
the same hard human/real-condition boundary already enforced on the stable
handoff, waiting-state, human-gate, next-human-action, unblock-readiness, and
blocked-ledger artifacts. The status, audit, and approval-plan builders now
write `autonomous_progress_available`, `human_or_real_condition_required`, and
`blocked_waiting_for_human_or_real_condition` into JSON and Markdown, so the
most common status surfaces cannot imply that the north-star goal is complete
or autonomously finishable while the hard gate is blocked. Targeted boundary
coverage passed (`7 passed`), the focused north-star boundary/gate slice passed
(`114 passed`), the full Revit operator/plugin slice passed (`346 passed`),
and compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-status-audit-plan-boundary-guard-20260514`
republished the stable handoff read-only. Live stable scan
`live-north-star-stable-scan-after-status-audit-plan-boundary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`human_real_condition_boundary_violation_count: 0`, and checked 9 boundary
artifacts. Fresh hard gate
`live-north-star-completion-gate-after-status-audit-plan-boundary-guard-final-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Restart checklist add-in prompt preflight:
The generated bridge restart/no-save checklist now embeds the current
`addin-security-preflight` result. The human restart handoff therefore shows
whether the Revit 2025 add-in manifest points to the expected Hermes operator
DLL, whether the DLL is present and signed, which unsigned-startup buttons are
blocked, and that `Always Load` is only possible after exact human approval.
Targeted restart/add-in/unsigned-startup tests passed (`5 passed`), the full
Revit operator/plugin slice passed (`346 passed`), and compileall passed. Live
`addin-security-preflight` reported `status: verified`,
`expected_local_hermes_addin: true`, `needs_trust_addin: false`,
`allowed_dialog_button: Always Load`, blocked `Load Once` and `Do Not Load`,
and a valid signature from `CN=Hermes Revit Operator Local Code Signing`.
Live restart plan
`live-bridge-restart-plan-with-addin-preflight-20260514` wrote the updated
checklist, and live watch refresh
`live-north-star-watch-refresh-after-restart-checklist-addin-preflight-20260514`
republished it as `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md`.
Live stable scan
`live-north-star-stable-scan-after-restart-checklist-addin-preflight-20260514`
reported `status: clean`, `violation_count: 0`, and zero restart-checklist
bridge-cause violations. Fresh hard gate
`live-north-star-completion-gate-after-restart-checklist-addin-preflight-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Restart checklist add-in preflight stable guard:
The stable artifact scan and hard completion-gate safety guard now validate
that `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` still mirrors
the latest `bridge_restart_validation_plan.json` `addin_security_preflight`
payload. The checklist must include the add-in startup preflight section,
verified status fields, the allowed `Always Load` approval rule, blocked load
buttons, signature status, signer subject, and the exact-token warning that
Hermes must not click from the checklist. Drift raises
`restart-checklist-addin-preflight-*` violations and routes to stable handoff
repair instead of allowing a misleading restart handoff. Targeted
restart-checklist add-in preflight tests passed (`9 passed`), the full Revit
operator/plugin slice passed (`348 passed`), and compileall passed. Live stable
scan
`live-north-star-stable-scan-after-restart-checklist-addin-preflight-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`restart_no_save_checklist_addin_preflight.status: clean`, and
`restart_no_save_checklist_addin_preflight_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-restart-checklist-addin-preflight-guard-20260514`
still reported `status: blocked`, `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`blocked_waiting_for_human_or_real_condition: true`, and zero safety guard
violations. The north-star goal remains active and incomplete.

Current human handoff refresh:
A standalone approval preflight refresh can intentionally make older
approval-facing handoff artifacts stale. Live scan
`live-north-star-stable-scan-after-human-action-refresh-20260514` caught that
state with `fresh-preflight-stale-handoff-artifact` violations after
`live-north-star-approval-preflight-refresh-after-addin-preflight-guard-20260514`
refreshed preflight. Read-only watch refresh
`live-north-star-watch-refresh-after-human-action-stale-handoff-20260514`
then regenerated approval preflight and the current handoff together, observed
Revit idle with no dialogs, and kept completion blocked. Final stable scan
`live-north-star-stable-scan-after-human-action-handoff-refresh-final-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and
`restart_no_save_checklist_addin_preflight_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-human-action-handoff-refresh-final-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Stable scan preflight refresh advisory:
`north-star-stable-artifact-scan` now renders the approval-preflight refresh
advisory as an operator-ready command block in both JSON and Markdown. The
advisory includes the exact read-only
`north-star-watch --refresh-approval-preflight --publish-current-handoff
--checks 1 --poll 0` command, the PowerShell form, expected Revit context from
the latest approval preflight, and the post-refresh validation commands
`north-star-stable-artifact-scan` and `north-star-completion-gate`. It
explicitly reports `read_only: true`, `execution_command_included: false`, and
`approval_token_included: false`, and the Markdown omits `--execute`,
`--approval-token`, `APPROVE:` tokens, and exact `I approve` phrase material.
Focused coverage passed (`2 passed`). Live stable scan
`live-north-star-stable-scan-after-refresh-advisory-markdown-20260514` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
fresh preflight, and confirmed the current Markdown contains the refresh
command, expected context, and after-refresh checks without execution or
approval-token material. Fresh hard gate
`live-north-star-completion-gate-after-refresh-advisory-markdown-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Current-handoff next-human mirror guard:
`north-star-stable-artifact-scan` and the hard completion gate now verify that
`NORTH_STAR_HANDOFF_CURRENT.json.next_human_action` mirrors
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` for option count, option IDs, and
redacted option summaries. Drift raises
`handoff-next-human-options-mirror-drift`; approval-token or exact-phrase
material in the handoff summary raises
`handoff-next-human-options-credential-leak`; both route to stable handoff
repair. Focused mirror coverage passed (`3 passed`), the full Revit
operator/plugin slice passed (`355 passed`), and compileall passed. Live
stable scan
`live-north-star-stable-scan-after-handoff-next-human-options-mirror-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`handoff_next_human_options_mirror_violation_count: 0`, mirror status `ok`,
zero mismatches, and zero credential leaks. Fresh hard gate
`live-north-star-completion-gate-after-handoff-next-human-options-mirror-guard-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Unblock-readiness next-human mirror guard:
`north-star-stable-artifact-scan` and the hard completion gate now verify that
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` mirrors the next-human option
count, IDs, and redacted summaries from `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`.
The guard reports `unblock-readiness-next-human-options-mirror-drift` when the
unblock packet goes stale and
`unblock-readiness-next-human-options-credential-leak` if its summary layer
exposes approval tokens or exact approval phrases. Focused stable-scan/unblock
coverage passed (`4 passed`), the full Revit operator/plugin slice passed
(`354 passed`), and compileall passed. Live stable scan
`live-north-star-stable-scan-after-unblock-next-human-options-mirror-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`unblock_next_human_options_mirror_violation_count: 0`, mirror status `ok`,
zero mismatches, and zero credential leaks. Fresh hard gate
`live-north-star-completion-gate-after-unblock-next-human-options-mirror-guard-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Unblock-readiness option summary fields:
`north-star-unblock-readiness` now promotes the next-human option summary layer
from `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json` into
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` and Markdown as
`next_human_option_count`, `next_human_option_ids`, and redacted
`next_human_option_summaries`. This lets the single unblock-readiness packet
show the human restart/reload, exact-human-approval, and real-recovery
unblock paths while omitting exact approval phrases. Focused unblock-readiness
coverage passed (`4 passed`), the full Revit operator/plugin slice passed
(`353 passed`), and compileall passed. During live refresh the approval
preflight expired, causing stale approval credential violations; the safe
read-only watch refresh
`live-north-star-watch-refresh-after-unblock-option-summary-stale-preflight-20260514`
republished fresh approval-facing artifacts with zero safety guard violations.
Live unblock-readiness
`live-north-star-unblock-readiness-option-summary-clean-mirror-20260514`
then reported `stable_artifact_scan_clean: true`,
`stable_handoff_guard_clean: true`, `next_human_option_count: 3`, and the
three expected option IDs. Final stable scan
`live-north-star-stable-scan-after-unblock-option-summary-clean-mirror-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and
`unblock_stable_scan_mirror_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-unblock-option-summary-clean-mirror-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Next-human option summary fields:
`north-star-next-human-action` now writes top-level `option_count`,
`option_ids`, and redacted `option_summaries` directly into
`NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.json`, matching the summary surface used
inside the hard completion gate and current handoff. The summary layer omits
exact human approval phrases while preserving option IDs, kinds, execution
authority flags, bridge restart cause, approval coverage fields, selected item
ID, freshness status, and recovery observation hints. Focused next-human
handoff coverage passed (`3 passed`), the full Revit operator/plugin slice
passed (`353 passed`), and compileall passed. Live task
`live-north-star-next-human-action-option-summary-20260514` regenerated the
stable card with `option_count: 3`, option IDs
`human-restart-or-reload-revit`, `provide-exact-human-approval-phrase`, and
`wait-for-real-recovery-condition`, and three redacted summaries. Live stable
scan
`live-north-star-stable-scan-after-next-human-option-summary-20260514`
reported `status: clean`, `violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`, and
`next_human_action_resume_command_violation_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-next-human-option-summary-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Next-human resume context repair:
`north-star-next-human-action` now derives missing expected Revit context
fields from the latest `NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` artifact
when an operator invokes the read-only handoff without explicit
`--expected-title-contains`, `--expected-path-contains`,
`--expected-view-name`, or `--expected-view-type` flags. This prevents a
context-free handoff refresh from corrupting the stable post-human resume
command and tripping the hard gate. Focused next-human/resume-command coverage
passed (`6 passed`), the full Revit operator/plugin slice passed
(`353 passed`), and compileall passed. Live repair
`live-north-star-next-human-action-derived-context-repair-20260514`
regenerated `NORTH_STAR_NEXT_HUMAN_ACTION_CURRENT.*` with the expected
title/path/view context inherited from the preflight artifact. Live stable scan
`live-north-star-stable-scan-after-next-human-derived-context-repair-20260514`
reported `status: clean`, `violation_count: 0`,
`next_human_action_resume_command_violation_count: 0`,
`missing_context_option_count: 0`, and `context_mismatch_count: 0`. Live resume
check
`live-north-star-resume-check-after-next-human-derived-context-repair-20260514`
reported zero safety guard violations and still failed bridge validation on
`loaded_build_current` and `bridge_readiness_ready`, confirming the remaining
blocker is the human-safe Revit restart/reload, not handoff drift. Fresh hard
gate `live-north-star-completion-gate-after-next-human-derived-context-repair-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Approval phrase provenance metadata guard:
Stable approval-phrase metadata scanning now requires phrase-bearing artifacts
to say that generated handoff artifacts are not approval provenance and are not
execution authority. The shared provenance note is emitted into waiting-state,
approval-item, blocked-ledger, and current-handoff markdown paths, and the
stable scan raises `approval-phrase-provenance-note-missing` if an exact phrase
appears without that warning. Focused approval/handoff coverage passed
(`12 passed`), the full Revit operator/plugin slice passed (`352 passed`), and
compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-phrase-provenance-metadata-guard-20260514b`
republished current handoff artifacts read-only and reported zero safety guard
violations while keeping completion blocked. Live stable scan
`live-north-star-stable-scan-after-phrase-provenance-metadata-guard-20260514b`
reported `status: clean`, `violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`, clean read-only script guard
status, zero forbidden matches, and zero missing required terms. Fresh hard gate
`live-north-star-completion-gate-after-phrase-provenance-metadata-guard-20260514b`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Supervised read-only approval literal hardening:
`NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` no longer embeds the exact
human approval phrase or approval token. The script still accepts a
`-HumanApprovalPhrase` runtime parameter, but phrase validation is delegated to
`north-star-approval-phrase-verify` against current waiting-state artifacts and
execution remains limited to `north-star-approved-execution-preview` read-only
validation. The stable read-only script guard now rejects approval-token
literals matching `APPROVE:*` and exact approval-phrase literals containing
`I approve`, preventing handoff scripts from weakening the human approval
boundary. Focused approval-leak/current-handoff tests passed (`9 passed`), the
full Revit operator/plugin slice passed (`350 passed`), and compileall passed.
Live watch refresh
`live-north-star-watch-refresh-after-supervised-script-token-removal-20260514`
regenerated the current handoff read-only, observed Revit idle with no dialogs,
and kept completion blocked. A narrow script inspection reported
`NO_APPROVAL_LITERAL_LEAKS_FOUND`. Live stable scan
`live-north-star-stable-scan-after-supervised-script-token-removal-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, and
`forbidden_match_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-supervised-script-token-removal-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Approval phrase provenance guard:
`north-star-approval-phrase-verify` now separates text/token matching from
human-source provenance. A phrase can match the current waiting-state handoff
and token, but preview readiness is withheld unless the caller also supplies
the explicit `--phrase-source human_active_conversation` attestation. Generated
handoff artifacts are marked as not approval provenance, and
`north-star-approved-execution-preview` now keeps its command preview withheld
when phrase source is missing or untrusted. The supervised read-only handoff
script now includes `--phrase-source human_active_conversation` beside the
runtime `<HUMAN_APPROVAL_PHRASE>` placeholder without embedding the phrase or
token. Focused provenance and handoff tests passed (`19 passed`, then
`14 passed` after tightening the script assertion), the full Revit
operator/plugin slice passed (`351 passed`), and compileall passed. Live watch
refresh `live-north-star-watch-refresh-after-phrase-source-guard-20260514`
regenerated current handoff artifacts read-only, observed the same blocked
state, and kept completion blocked. Script inspection reported
`NO_APPROVAL_LITERAL_LEAKS_FOUND` and confirmed the phrase-source guard lines.
Live stable scan
`live-north-star-stable-scan-after-phrase-source-guard-20260514` reported
`status: clean`, `violation_count: 0`, `stable_readonly_script_guard.status:
clean`, and `forbidden_match_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-phrase-source-guard-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Phrase-source stable guard:
The stable read-only script guard now requires
`NORTH_STAR_SUPERVISED_READONLY_CHECK_CURRENT.ps1` to contain both the
`--phrase-source` argument and the `human_active_conversation` source value.
If those terms drift out of the supervised read-only checker, stable scan raises
`stable-readonly-script-required-term-missing`, which also appears in the hard
gate safety guard path. This prevents the approval provenance guard from being
lost in future handoff regeneration. Focused stable-script coverage passed
(`10 passed`), the full Revit operator/plugin slice passed (`352 passed`), and
compileall passed. Live stable scan
`live-north-star-stable-scan-after-phrase-source-stable-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, `missing_required_term_count: 0`,
and `forbidden_match_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-phrase-source-stable-guard-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Resume bridge summary stable guard:
The stable read-only script guard now treats the resume-script bridge summary
as a checked handoff contract. `NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`
must contain the bridge-validation JSON extraction line, the `BRIDGE
VALIDATION` status output, and the failed-checks output; otherwise stable scan
raises `stable-readonly-script-required-term-missing` and the hard gate routes
the issue to stable handoff repair. Targeted stable-script tests passed
(`5 passed`), the full Revit operator/plugin slice passed (`349 passed`), and
compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-resume-bridge-summary-guard-20260514`
regenerated the current handoff read-only, observed Revit idle with no dialogs,
and kept completion blocked. Live stable scan
`live-north-star-stable-scan-after-resume-bridge-summary-guard-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, and
`missing_required_term_count: 0`. Fresh hard gate
`live-north-star-completion-gate-after-resume-bridge-summary-guard-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Post-human resume bridge validation summary:
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` now prints a concise
`BRIDGE VALIDATION` line after parsing `north-star-resume-check` JSON and before
the completion-gate warning. The line reports bridge validation status,
`validation_passed`, and failed bridge checks so a human can see whether a safe
Revit restart/reload fixed the loaded bridge before reading the full JSON. The
script remains read-only and still refuses to imply completion unless the parsed
hard gate reports all completion authority fields true. Targeted resume/handoff
coverage passed (`7 passed`), the full Revit operator/plugin slice passed
(`348 passed`), and compileall passed. Live watch refresh
`live-north-star-watch-refresh-after-resume-script-bridge-summary-20260514`
regenerated the current handoff, observed Revit idle with no dialogs, and kept
completion blocked because `loaded_build_current` still requires a human-safe
Revit restart/reload. The stable script inspection found the new bridge
validation summary line in
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`. Live stable scan
`live-north-star-stable-scan-after-resume-script-bridge-summary-20260514`
reported `status: clean`, `violation_count: 0`,
`stable_readonly_script_guard.status: clean`, and zero stale approval
violations. Fresh hard gate
`live-north-star-completion-gate-after-resume-script-bridge-summary-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Approval preflight refresh hint:
`north-star-approval-preflight` now returns and renders a
`post_preflight_handoff_refresh` block with the exact read-only
`north-star-watch --refresh-approval-preflight --publish-current-handoff`
command to run after a standalone preflight. This makes the stale-handoff
repair path explicit at the source command, keeps execution and approval-token
fields false, and tells the operator why approval-facing handoff artifacts must
be republished before any approval phrase is requested or used. Targeted
approval-preflight tests passed (`4 passed`), the full Revit operator/plugin
slice passed (`348 passed`), and compileall passed. Live
`live-north-star-approval-preflight-with-refresh-hint-20260514` included the
new refresh block, three ready approval items, zero unsafe preflight items, no
approval tokens, and no execute commands. The hinted read-only refresh
`live-north-star-watch-refresh-after-approval-preflight-refresh-hint-20260514`
republished the current handoff, observed Revit idle with no dialogs, and kept
completion blocked. Final stable scan
`live-north-star-stable-scan-after-approval-preflight-refresh-hint-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and clean restart-checklist add-in
preflight validation. Fresh hard gate
`live-north-star-completion-gate-after-approval-preflight-refresh-hint-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Current handoff summary and stale approval redaction:
`north-star-current-handoff` now publishes compact top-level summaries for the
next human action, next required real condition, restart/reload handoff,
approval handoff, and post-human resume commands/scripts. This keeps the stable
handoff directly usable without digging through nested packets. Stale approval
artifacts are now redacted more aggressively: expired approval-facing current
files withhold approval phrases, approval tokens, verify commands, and execute
flags instead of preserving stale command fragments. The fallback supervised
read-only script also carries the required audit guard terms while still
refusing to execute when no current packet is available. Focused stale-redaction
and handoff-summary coverage passed (`2 passed`), the full Revit
operator/plugin slice passed (`367 passed`), and compileall passed. Live
handoff refresh
`live-north-star-current-handoff-stale-approval-redaction-repair-20260514`
reported the expected top-level summaries and kept completion blocked because
the approval preflight was stale. Live stable scan
`live-north-star-stable-scan-after-stale-approval-redaction-repair-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, and a clean supervised read-only script
guard. Fresh hard gate
`live-north-star-completion-gate-after-stale-approval-redaction-repair-20260514`
still reports `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Read-only continuation refresh:
When asked to continue without a human approval or Revit restart, the only safe
autonomous action was to refresh the read-only supervision artifacts. Live watch
refresh `live-north-star-watch-refresh-current-handoff-continue-20260514` ran
one observation cycle, observed Revit 2025 idle with no dialogs, refreshed the
approval preflight, and republished the current handoff. It reported three
items ready for human approval, zero unsafe preflight items, and no UI/model
execution. Live stable scan
`live-north-star-stable-scan-after-watch-refresh-continue-20260514` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`, and a clean read-only script
guard. Fresh hard gate
`live-north-star-completion-gate-after-watch-refresh-continue-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Fresh UI workflow recipe validation:
Continuation also refreshed the guarded workflow evidence without executing any
UI or model action. Static matrix
`live-ui-workflow-matrix-continuation-20260514` validated 10 reusable UI
workflow recipes, 38 planned steps, seven approval-gated steps, one manual
placeholder, zero blocked recipe cases, and no failed cases. Smoke matrix
`live-ui-workflow-smoke-matrix-continuation-20260514` ran 19 read-only
observation/planning prefix steps across 10 recipes and stopped before
approval-gated, manual-placeholder, blocked, or non-smoke-safe steps. The smoke
run observed Revit 2025 idle with no active dialogs and confirmed the active
document bridge still reports the copied detached structural model on
`STARTING VIEW`; it performed no click, type, UIA invoke, restart, save, sync,
reload, detach, upgrade, close, or model modification. Fresh hard gate
`live-north-star-completion-gate-after-ui-smoke-continuation-20260514` still
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Fresh workflow memory and replay validation:
Continuation refreshed the recorded workflow library and replay guards without
executing any replay step. `live-workflow-library-continuation-20260514`
reported two valid sandbox templates: `Live Readonly QA Workflow` and
`Parameterized Click Dry Run`. `live-plan-workflow-qa-continuation-20260514`
planned eight QA replay steps, marked two focus steps approval-required, and
reported `can_replay_without_human: false`. The parameterized replay plan with
target `OK`
(`live-plan-workflow-parameterized-safe-continuation-20260514e`) reclassified
the override as approval-required, while the target `Save`
(`live-plan-workflow-parameterized-blocked-continuation-20260514e`) was blocked
with no approval-required steps. Fresh workflow approval plans confirmed
`stale_approval_tokens_reused: false` and
`template_contains_approval_tokens: false`; the blocked `Save` override exposed
no execute command. Dry-run replays
`live-replay-workflow-qa-dry-run-continuation-20260514`,
`live-replay-workflow-parameterized-safe-dry-run-continuation-20260514`, and
`live-replay-workflow-parameterized-blocked-dry-run-continuation-20260514`
performed fresh observation and state-gate checks, executed zero steps, required
human approval for allowed UI actions, and stopped the `Save` override as
blocked. The blocked dry-run recovery snapshot classified the live state as
idle and did not count as a recovery-drill gate. Fresh hard gate
`live-north-star-completion-gate-after-workflow-memory-continuation-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. The
north-star goal remains active and incomplete.

Fresh recovery-drill matrix validation:
Continuation refreshed the conservative recovery recommendation matrix without
changing live Revit state. `live-recovery-drill-matrix-continuation-20260514`
validated five synthetic scenarios: modal upgrade dialog, busy with no dialog,
idle with no dialog, Revit not running, and unknown state. Each case matched
the expected conservative classification, included a safe next command, and
provided a next step; the high-risk upgrade dialog produced no automatic
planned action. The command was read-only and explicitly synthetic, so it did
not satisfy the live recovery gate. Fresh hard gate
`live-north-star-completion-gate-after-recovery-matrix-continuation-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, and zero safety guard violations. Stable
scan `live-north-star-stable-scan-after-recovery-matrix-continuation-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, `approval_phrase_metadata_violation_count:
0`, and clean read-only script guards. The north-star goal remains active and
incomplete.

Fresh UIA, ribbon, and context method matrix validation:
Continuation refreshed the UI execution method policy evidence without
touching live Revit UI. `live-uia-method-matrix-continuation-20260514`
validated 21 cases across 10 UIA methods, with 11 approval-required cases, 10
blocked cases, zero executed cases, no failed cases, and `live_ui_touched:
false`. `live-ribbon-action-matrix-continuation-20260514` validated 24 static
ribbon action descriptors, with 20 approval-gated cases, seven blocked cases,
and no failed cases; it did not locate, focus, click, or invoke a ribbon
control. `live-context-menu-action-matrix-continuation-20260514` validated
three context-menu descriptors and four menu item cases, with two
approval-gated descriptors, one blocked descriptor, and no failed cases; it
did not open a context menu or select a menu item. Coverage audit
`live-ui-execution-coverage-audit-after-method-matrices-continuation-20260514`
remained `status: insufficient_evidence`, `target_met: false`, with 14
qualifying historical live executions and 117 excluded entries. It found live
coverage only for `focus`, `escape-key`, and `dialog-click`; missing surfaces
remain `type-text`, `uia-invoke`, `visual-click`, `ribbon-action`,
`context-menu-action`, `context-menu-item`, and `approved-ui-workflow-step`.
Fresh hard gate
`live-north-star-completion-gate-after-method-matrices-continuation-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, `human_or_real_condition_required:
true`, and zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-method-matrices-continuation-20260514`
reported `status: clean`, `violation_count: 0`,
`stale_approval_violation_count: 0`, `approval_phrase_metadata_violation_count:
0`, and clean read-only script guards. The remaining blockers are
`bridge_restart_validation`, `live_ui_workflow_execution`,
`live_recovery_drills`, and `live_uia_ribbon_context_execution`; the
north-star goal remains active and incomplete.

Resume readiness and handoff refresh:
On resume, `live-north-star-unblock-readiness-resume-20260514` confirmed the
autonomous stop state: only observation and read-only refresh commands are
allowed, `autonomous_progress_available: false`, and the same four blocker
gaps remain. The permitted refresh
`live-north-star-watch-refresh-after-readiness-resume-20260514` ran one
read-only observation, observed Revit 2025 idle with zero dialogs and the
detached structural model on `STARTING VIEW`, refreshed the approval preflight,
and republished stable current handoff artifacts. It also confirmed the bridge
restart/reload blocker still fails `loaded_build_current`, so the bridge is not
ready for continuous operation until a human performs the no-save restart or
reload path. Fresh hard gate
`live-north-star-completion-gate-after-readiness-watch-resume-20260514`
reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `blocked_gap_count: 4`,
`blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, `human_or_real_condition_required:
true`, and zero safety guard violations. Stable scan
`live-north-star-stable-scan-after-readiness-watch-resume-20260514` reported
`status: clean`, `violation_count: 0`, `stale_approval_violation_count: 0`,
`approval_phrase_metadata_violation_count: 0`, and clean read-only script
guards. The north-star goal remains active and incomplete.

Fresh prompt-to-artifact audit:
`live-north-star-audit-after-readiness-resume-20260514` restated the objective
as a Revit Human-Operator Layer, verified the named documents and prototype
source package are present, and reported `implementation_package_complete:
true`. It still returned `status: not_complete`, `completion_allowed: false`,
`may_call_update_goal: false`, and `audit_completion_authorized: false`
because live/human gates remain. `live-north-star-blocked-ledger-after-readiness-resume-20260514`
reported `status: blocked`, `blocked_gap_count: 4`, `blocked_gate_count: 4`,
and `autonomous_progress_available: false`. The remaining gaps are a
human-approved no-save bridge restart/reload and post-restart validation,
broad approved live UI workflow execution, real-condition recovery evidence,
and approved live UIA/ribbon/context-menu execution across actual Revit
surfaces.

Human handoff packet refresh and artifact consistency repair:
`live-north-star-human-gate-packet-after-audit-resume-20260514` wrote a fresh
read-only human gate packet with three human-action items and one
real-condition item. `live-north-star-next-human-action-after-audit-resume-20260514`
wrote a one-screen next-action card with three choices: human no-save
restart/reload, exact human approval for a gated UI action, or waiting for a
real recovery condition. Republish
`live-north-star-current-handoff-after-human-packet-resume-20260514` exposed a
stable artifact blocker-ID mismatch; hard gate
`live-north-star-completion-gate-after-human-packet-resume-20260514` therefore
reported one safety guard violation and refused completion. The remediation
sequence republished current handoff
`live-north-star-current-handoff-after-human-packet-gate-resume-20260514`, ran
stable scan `live-north-star-stable-scan-after-human-packet-gate-resume-20260514`
with `status: clean` and zero violations, then reran hard gate
`live-north-star-completion-gate-after-human-packet-repair-resume-20260514`.
The final hard gate returned `completion_allowed: false`,
`may_call_update_goal: false`, `audit_completion_authorized: false`,
`blocked_gap_count: 4`, `blocked_gate_count: 4`, `unsatisfied_count: 17`,
`autonomous_progress_available: false`, `human_or_real_condition_required:
true`, and `safety_guard_violation_count: 0`. The north-star goal remains
active and incomplete.

Focused safety regression verification:
After the live stable artifact mismatch was repaired, the focused regression
slice for the relevant guards was rerun. The first pytest invocation did not
reach test execution because pytest-xdist could not create its default temp
base under `AppData\Local\Temp`. The same slice was rerun serially with a
workspace-local `--basetemp` and passed: `12 passed, 349 deselected`. The slice
covered stable blocker-ID mismatch detection, stable handoff repair routing,
execution-authority safety guards, and the next-human-action card authority
rules. Pytest emitted a cache warning because `.pytest_cache` could not be
written, but the selected tests all passed. This improves safety evidence only;
it does not clear the human/real-condition north-star gates.

Bridge blocker refresh and sequential artifact repair:
Read-only bridge checks were refreshed for the `bridge_restart_validation`
blocker. `live-bridge-status-current-blocker-20260514` confirmed the bridge
files are reachable and the add-in heartbeat is active. `live-verify-bridge-build-current-blocker-20260514`
returned `status: stale_or_unverified`; the loaded add-in status lacks the
current bridge protocol/capability metadata. `live-bridge-readiness-current-blocker-20260514`
returned `status: not_ready` with failed check `loaded_build_current`.
`live-bridge-restart-validation-plan-current-blocker-20260514` wrote a fresh
read-only no-save checklist and returned `status: human_restart_required`,
`restart_or_reload_required: true`, `human_handoff_required: true`, and
`pre_restart_files_ready: true`; its checklist records the copied detached
model as dirty, keeps save/discard decisions human-only, and blocks Hermes from
answering unsigned add-in prompts from the checklist.

An initial handoff/stable-scan/gate refresh was incorrectly run in parallel and
created a transient stable blocker-ID mismatch. The dependent artifact sequence
was rerun sequentially:
`live-north-star-current-handoff-sequential-repair-after-bridge-blocker-20260514`,
`live-north-star-stable-scan-sequential-repair-after-bridge-blocker-20260514`,
`live-north-star-completion-gate-sequential-repair-after-bridge-blocker-20260514`,
`live-north-star-stable-scan-final-after-sequential-bridge-repair-20260514`,
and `live-north-star-completion-gate-final-after-sequential-bridge-repair-20260514`.
The final stable scan is clean with zero violations, and the final hard gate
has `safety_guard_violation_count: 0`. Completion is still blocked:
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates,
17 unsatisfied requirements, and no autonomous progress path.

Live recovery snapshot and stale approval repair:
`live-recovery-snapshot-current-condition-20260514` captured a read-only live
recovery snapshot with screenshot and shallow UI tree evidence. It observed
Revit 2025 running idle, not hung, with zero active dialogs, and therefore
`validated_live_recovery_drill: false`; the recovery recommendation was
`safe_to_continue_read_only`, so `live_recovery_drills` remains blocked until a
real stuck, frozen, modal, busy, or unknown Revit state occurs. Running the
hard gate after this observation exposed stale approval material in stable
handoff artifacts because the approval preflight had expired. The repair used
read-only watch refresh
`live-north-star-watch-refresh-after-stale-approval-from-recovery-snapshot-20260514`
with approval preflight refresh and current handoff publication. It produced a
fresh preflight with three human-approval items and zero unsafe preflight
items. Stable scan
`live-north-star-stable-scan-after-stale-approval-refresh-20260514` then
reported `status: clean`, `violation_count: 0`, zero stale approval
violations, zero approval phrase metadata violations, and clean read-only
script guards. Final hard gate
`live-north-star-completion-gate-after-stale-approval-refresh-20260514`
returned `safety_guard_violation_count: 0` but still refused completion with
four blocked gaps, four blocked gates, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`, and
`audit_completion_authorized: false`.

Runbook sequencing guard:
`REVIT_OPERATOR_RUNBOOK.md` now explicitly requires the dependent north-star
artifact refresh commands to run sequentially, not in parallel:
`north-star-current-handoff`, `north-star-stable-artifact-scan`,
`north-star-completion-gate`, then a final stable scan and hard gate. This
documents the repair lesson from the transient blocker-ID mismatch and keeps
future operators from treating intermediate stable scan/status output as
completion authority. A focused regression test,
`test_revit_operator_runbook_requires_sequential_north_star_artifact_refresh`,
now verifies the runbook contains the no-parallel warning, the exact sequential
command order, the transient blocker-ID mismatch rationale, and the warning
that intermediate stable scan/status output is not completion authority. The
first run failed on a line-wrap-sensitive assertion; after normalizing
whitespace, the focused test passed (`1 passed`) with only the existing
`.pytest_cache` permission warning.

Sequential refresh command hardening:
The read-only `north-star-refresh-sequence` command now wraps the required
current handoff, stable scan, hard gate, final stable scan, and final hard gate
sequence in one ordered operation. Each child command uses its own task journal,
the parent result mirrors only the final hard gate as completion authority, and
`may_execute_from_this_result` remains false. Focused tests cover the step
order, child artifact preservation, safety allow-list entry, CLI dispatch, and
the runbook warning that intermediate stable scan/status output is not
completion authority. The full `tests/tools/test_revit_operator.py` module
passed after the change (`364 passed`) with only the existing `.pytest_cache`
permission warning. A real CLI smoke run of `north-star-refresh-sequence`
returned `success: true`, `status: blocked`, five ordered steps, and no
completion authority.

Correct live-sandbox refresh:
After regenerating the bridge restart no-save checklist, refreshing the
supervision endurance audit, and refreshing approval preflight/current handoff
in `live_readonly_bridge_20260512`, task
`live-north-star-refresh-sequence-correct-sandbox-after-repair-20260514` ran the
new five-step sequence in order. It returned `status: blocked`,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, four blocked gates, 17
unsatisfied requirements, zero safety guard violations, no autonomous progress
available, and `human_or_real_condition_required: true`.

Latest human-gate handoff refresh:
Task `live-next-human-action-after-refresh-sequence-20260514` regenerated the
sanitized next-human-action packet in the correct live sandbox. It exposed three
non-executable options: human restart/reload for bridge validation, human
approval for the remaining approved UI execution checks, and waiting for a real
recovery condition. Follow-up hard gate task
`live-north-star-refresh-sequence-after-next-human-action-20260514` reran the
five-step sequence and remained blocked with four blocked gaps, four blocked
gates, 17 unsatisfied requirements, zero safety guard violations,
`autonomous_progress_available: false`, and
`human_or_real_condition_required: true`.

Post-human resume hardening:
The stable post-human resume script now runs both `north-star-resume-check` and
`north-star-refresh-sequence`, so a human restart/reload or approval checkpoint
is followed by the same ordered current-handoff/stable-scan/hard-gate sequence.
The script still has no execution authority and still gates completion on
`completion_allowed`, `may_call_update_goal`, and
`audit_completion_authorized`. Focused script-guard tests passed (`6 passed`),
the full Revit operator test module passed (`364 passed`) with only the known
`.pytest_cache` warning, and live task
`live-north-star-refresh-sequence-after-posthuman-script-hardening-20260514`
confirmed the stable script contains `north-star-refresh-sequence` while the
hard gate remains blocked with four gaps, zero safety guard violations, and no
autonomous progress.

Sanitized human unblock brief:
`north-star-human-unblock-brief` now writes
`NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json` and `.md` with the remaining
human/real-condition options, checklist paths, and post-human resume script path
without embedding exact approval phrases, approval tokens, or execution
commands. Focused redaction/CLI/safety tests passed (`5 passed`), the full
Revit operator module passed (`366 passed`) with only the known `.pytest_cache`
warning, and live task `live-human-unblock-brief-20260514` confirmed the JSON
and Markdown contain no `APPROVE:` literal and no exact approval phrase text.
Follow-up hard gate task
`live-north-star-refresh-sequence-after-human-unblock-brief-20260514` stayed
blocked with four gaps, 17 unsatisfied requirements, zero safety guard
violations, no autonomous progress, and a human/real-condition requirement.

Current completion audit snapshot:
Task `live-north-star-completion-audit-status-20260514` restated the current
north-star objective against the implementation package and reported
`implementation_package_complete: true`, `north_star_complete: false`, four
blocked gaps, one cleared gap, 17 unsatisfied requirements, no autonomous
progress, and a human/real-condition requirement. The authoritative hard gate
`live-hard-gate-completion-audit-status-20260514` likewise returned
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gates, 17 unsatisfied
requirements, and zero safety guard violations. Stable scan
`live-stable-scan-completion-audit-status-20260514` returned `status: clean`
with zero violations, zero stale approval violations, zero read-only script
guard violations, and zero approval phrase metadata violations.

Short-watch stale brief repair:
Task `live-north-star-short-watch-after-external-block-20260514` saw no human
or Revit state change, but its fresh approval preflight exposed stale stable
handoff artifacts for the new sanitized human unblock brief. The current
handoff publisher now regenerates `NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.*`
with the rest of the approval-facing handoff. Focused repair tests passed
(`7 passed`), the full Revit operator module passed (`366 passed`), and live
task `live-north-star-refresh-sequence-after-handoff-brief-repair-20260514`
returned zero safety guard violations while still refusing completion on the
same four human/real-condition gates.

Current handoff usability refresh:
`NORTH_STAR_HANDOFF_CURRENT.md` now includes a dedicated Human Unblock Brief
section and explicitly points humans to `NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.md`.
Focused handoff/brief tests passed (`3 passed`), the full Revit operator module
passed (`366 passed`), and live task
`live-north-star-refresh-sequence-after-handoff-markdown-brief-20260514`
confirmed the stable handoff contains the sanitized brief section while the hard
gate remains blocked with zero safety guard violations.

Agent stop-reason guard:
`NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json` and `.md` now expose
`agent_stop_reason: human_or_real_condition_required_no_autonomous_progress`
when the hard gate is blocked only by external human/real-condition gates. This
gives future Hermes runs a machine-readable stop signal instead of encouraging
repeated polling. Focused tests passed (`2 passed`), the full Revit operator
module passed (`366 passed`), and live task
`live-north-star-refresh-sequence-after-stop-reason-20260514` regenerated the
brief with that stop reason while preserving zero safety guard violations.
`python -m compileall tools/revit_operator plugins/revit-operator` also passed
after the stop-reason change.

Agent stop-status artifact:
`north-star-agent-stop-status` now writes
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` and `.md` as a first-class,
credential-free stop/continue decision for Hermes. The current handoff
regenerates the artifact and points `NORTH_STAR_HANDOFF_CURRENT.md` to it.
Focused stop-status/handoff/CLI/safety tests passed (`6 passed`), the full
Revit operator module passed (`368 passed`), the plugin slice passed
(`6 passed`), and compileall completed without syntax errors. Live read-only
task `live-north-star-refresh-sequence-after-agent-stop-status-20260514`
reported the stable scan clean with zero violations and the stop-status
artifact at `stop_for_human_or_real_condition`, `should_stop_agent: true`,
`recommended_agent_action: wait_for_human_or_real_condition`, and
`may_execute_from_this_result: false`. The final hard gate still refused
completion with four blocked gaps, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, and zero safety guard violations.

Restart checklist freshness guard:
`north-star-stable-artifact-scan` and the hard completion gate now verify that
the stable `NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` is at least
as fresh as the latest bridge restart validation plan and its source no-save
checklist when the current next human action is the bridge restart/reload path.
Focused restart-checklist freshness coverage passed (`8 passed`), the broader
guard slice passed (`12 passed`), the full Revit operator module passed
(`371 passed`), the Revit operator plugin slice passed (`6 passed`), and
compileall over `tools/revit_operator` plus `plugins/revit-operator` completed
without syntax errors. Live refresh
`live-watch-refresh-after-restart-checklist-freshness-guard-20260514`
republished approval preflight and current handoff artifacts read-only, then
`live-stable-scan-after-refresh-restart-checklist-freshness-guard-20260514`
reported `status: clean`, `violation_count: 0`, zero stale approval violations,
and zero restart-checklist freshness violations. The follow-up hard gate
`live-completion-gate-after-refresh-restart-checklist-freshness-guard-20260514`
still refused completion with four blocked gaps, 17 unsatisfied requirements,
zero safety guard violations, and no permission to call `update_goal`.

Audit count hardening:
`north-star-audit` now writes explicit JSON counts for `remaining_gap_count`,
`unsatisfied_count`, `unverified_or_blocked_requirement_count`, and prompt
checklist total/satisfied/unsatisfied counts instead of requiring downstream
tools to infer them from arrays. The audit Markdown mirrors those fields.
Focused audit-count and related guard coverage passed (`3 passed`). Live
read-only sequence `live-north-star-refresh-sequence-after-audit-counts-20260514`
regenerated stable current artifacts with `audit_remaining_gap_count: 4`,
`audit_unsatisfied_count: 17`, `audit_checklist_total_count: 159`, and
`audit_checklist_unsatisfied_count: 17`; the final hard gate still reported
zero safety guard violations and no completion authority.

Agent stop-status human path surface:
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` now carries credential-free
`human_unblock_paths` and `sanitized_options`, including the stable human
unblock brief, bridge restart/no-save checklist, and post-human resume script
paths. This lets a future Hermes run stop and point the human to the right
files without scanning timestamped run directories or exposing approval
material. Focused stop-status boundary coverage passed (`3 passed`). Live
read-only sequence `live-north-star-refresh-sequence-after-stop-paths-20260514`
regenerated the stable stop artifact with `should_stop_agent: true`,
`recommended_agent_action: wait_for_human_or_real_condition`, three sanitized
options, direct stable human-unblock/checklist/resume paths, no approval-token
or exact-phrase material, zero stable-scan violations, and no completion
authority.

Hermes plugin sandbox gate:
The `revit_operator` Hermes plugin no longer exposes the test-only
outside-safe-root sandbox override in its tool schema. If a caller supplies that
override through structured args or raw `argv`, the wrapper returns structured
JSON failure unless `HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX=1` is
set for local tests. The `serve` command remains blocked inside the plugin.
Plugin tests now cover schema omission, structured-arg refusal, raw-argv
refusal, `serve` blocking, dry-run safe command behavior, unsafe safe-command
blocking, and JSON handler output (`8 passed`). This protects the Hermes-facing
tool from writing outside the known safe Revit project area by default. Live
safe-sandbox plugin call `live-plugin-agent-stop-status-safe-sandbox-20260514`
ran `north-star-agent-stop-status` through `called_via: hermes-plugin` without
the test override and returned `status: stop_for_human_or_real_condition`,
`should_stop_agent: true`, direct human-unblock paths, four blocked gaps, 17
unsatisfied requirements, and no completion authority.

MCP sandbox gate:
The `revit_operator_command` MCP tool no longer exposes the test-only
outside-safe-root sandbox override in its public tool signature. Structured
requests or raw `argv` that try to use the override fail closed unless
`HERMES_REVIT_OPERATOR_MCP_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests.
Focused MCP wrapper coverage passed (`9 passed`). Live safe-sandbox MCP call
`live-mcp-agent-stop-status-safe-sandbox-20260514` ran
`north-star-agent-stop-status` through `called_via: mcp` without the test
override and returned the same stop-for-human status, four blocked gaps, 17
unsatisfied requirements, direct human-unblock paths, and no completion
authority.

HTTP sandbox gate:
The local HTTP control server now refuses `allow_sandbox_outside_safe_root` from
JSON payloads and refuses raw `argv` containing `--allow-sandbox-outside-safe-root`
unless `HERMES_REVIT_OPERATOR_HTTP_ALLOW_EXTERNAL_SANDBOX=1` is set for local
tests. Focused HTTP control-server coverage passed (`4 passed`). Live
safe-sandbox dispatcher call `live-http-agent-stop-status-safe-sandbox-20260514`
ran `north-star-agent-stop-status` without the test override and returned the
same stop-for-human status, direct human-unblock paths, four blocked gaps, 17
unsatisfied requirements, and no completion authority.

Agent-facing model-root gate:
The direct local CLI still supports `--allow-model-outside-safe-root` for
deliberate development tests, but the Hermes plugin, MCP wrapper, and
HTTP/control dispatcher now reject that override from command args, raw `argv`,
or nested request-operation JSON containing `allow_model_outside_safe_root` set
to true. Focused plugin coverage passed with the new model-root cases included
(`11 passed`), and the focused control/MCP model-root slice passed (`8
passed`). This prevents an agent-facing transport from opening a model outside
the known safe copied project area by smuggling the local development override
through a wrapper.

Full regression after the model-root gate passed: `tests/tools/test_revit_operator.py`
reported `381 passed`, `tests/plugins/test_revit_operator_plugin.py` reported
`11 passed`, and `python -m compileall tools/revit_operator plugins/revit-operator`
completed without syntax errors.

Live read-only north-star refresh after the model-root gate remained blocked,
as expected. After regenerating stale handoff artifacts, stable artifact scan
`live-model-root-refresh-scan-clean-check-20260514` reported `violation_count:
0`, and completion gate `live-model-root-refresh-gate-clean-check-20260514`
reported four blocked gaps, 17 unsatisfied requirements, `completion_allowed:
false`, `may_call_update_goal: false`, and `safety_guard_violation_count: 0`.

Read-only supervision refresh `live-supervision-refresh-after-model-root-gate-20260514`
then refreshed approval preflight and republished the current handoff without
focusing, clicking, typing, invoking UIA, queueing bridge writes, restarting,
closing, saving, syncing, reloading, detaching, upgrading, or modifying Revit.
It reported three approval items ready for human review, but the completion
gate stayed blocked with four blocked gaps, 17 unsatisfied requirements,
`completion_allowed: false`, `may_call_update_goal: false`, and zero safety
guard violations. Follow-up read-only artifacts
`live-ready-approvals-after-watch-20260514`,
`live-next-approval-after-watch-20260514`, and
`live-human-gate-packet-after-watch-20260514` refreshed the human-gated
approval handoff without executing any approval-gated action. Final stable scan
`live-stable-scan-after-ready-approvals-20260514` was clean, and final
completion gate `live-completion-gate-after-ready-approvals-20260514` remained
blocked with the same four gaps and 17 unsatisfied requirements.

Audit blocker metadata hardening:
`prompt_to_artifact_checklist` entries now carry structured `blocker` metadata
for every unsatisfied row. Focused audit coverage passed, the full
`tests/tools/test_revit_operator.py` suite passed with `381 passed`, and
`python -m compileall tools/revit_operator` completed without syntax errors.
Live read-only refresh `live-audit-blocker-metadata-refresh-20260514` regenerated
the stable audit and hard gate; all 17 unsatisfied checklist rows had blocker
metadata, final stable scan was clean, and the completion gate remained blocked
with four blocked gaps, 17 unsatisfied requirements, and zero safety guard
violations.

Plugin and compile verification:
After adding the sanitized human unblock brief and post-human refresh sequence
hardening, the Revit operator plugin test slice passed (`6 passed`) and
`python -m compileall tools/revit_operator plugins/revit-operator` completed
without syntax errors.

Audit blocker metadata gate:
`north-star-stable-artifact-scan` and `north-star-completion-gate` now treat
missing structured blocker metadata on any unsatisfied
`prompt_to_artifact_checklist` row as an audit integrity violation. Focused
coverage for malformed audit rows and the full Revit operator regression passed
(`383 passed`, with the known pytest cache warning), and
`python -m compileall tools/revit_operator` completed without syntax errors.
Live read-only refresh
`live-audit-blocker-metadata-guard-refresh-20260514` regenerated the dependent
stable handoff, stable scan, and hard gate in sequence. The final stable scan
reported `status: clean`, `violation_count: 0`,
`completion_audit_blocker_metadata_violation_count: 0`, and zero missing
blocker rows. The final hard gate still reported `status: blocked`,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, zero missing blocker rows, and zero safety guard violations.

Final bridge-readiness and stop-status refresh:
Current read-only add-in security and bridge checks confirmed the Hermes Revit
2025 manifest, expected DLL path, and local code-signing signature are valid.
`live-bridge-readiness-final-check-20260514` and
`live-verify-bridge-build-final-check-20260514` still report the loaded Revit
session as stale because `loaded_build_current` fails; the bridge is connected
but lacks current bridge protocol/capability metadata. Refreshed handoff
`live-bridge-restart-validation-plan-final-check-20260514` reports
`pre_restart_files_ready: true`, `restart_or_reload_required: true`, and
`status: human_restart_required` for the dirty copied local model. Stable
stop-status refresh `live-agent-stop-status-after-final-bridge-check-20260514`
records `should_stop_agent: true`, with approval material withheld and only
observation/read-only refresh allowed. The following stable scan
`live-stable-scan-after-stop-status-final-bridge-check-20260514` was clean, and
hard gate `live-completion-gate-after-stop-status-final-bridge-check-20260514`
still returned `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, zero missing blocker rows, and zero safety guard violations.

Completion-gate stdout redaction:
The CLI response for `north-star-completion-gate` now redacts approval phrases
and approval tokens from stdout while preserving non-sensitive status fields and
leaving handoff artifacts available for supervised review. Focused regression
coverage passed for the redaction path and the completion-gate artifact writer.
Live task `live-completion-gate-stdout-redaction-pattern-check-20260514`
confirmed the command output contained no direct approval markers and did
contain redaction markers. The follow-up stable scan
`live-stable-scan-after-stdout-redaction-check-20260514` remained clean, and
hard gate `live-completion-gate-after-stdout-redaction-stable-scan-20260514`
still reported `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, and zero safety guard violations.

Interrupted-watch cleanup:
A longer read-only `north-star-watch` refresh was stopped after it exceeded the
tool timeout and left only partial evidence. The two matching repo-local Python
processes for task `live-north-star-watch-continue-until-complete-refresh-20260514`
were stopped explicitly. The partial gate stayed blocked but showed stop-status
drift, so `live-agent-stop-status-after-interrupted-watch-cleanup-20260514`
refreshed the fail-closed stop boundary. Follow-up stable scan
`live-stable-scan-after-interrupted-watch-cleanup-20260514` reported
`status: clean`, `violation_count: 0`, and zero stop-status-boundary violations.
Final hard gate
`live-completion-gate-after-interrupted-watch-cleanup-final-20260514` reported
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, `autonomous_progress_available: false`,
`human_or_real_condition_required: true`, and zero safety guard violations.

Watch finalization hardening:
`north-star-watch` now refreshes the stable agent stop-status after publishing
its hard completion gate, rebuilds/publishes a final gate against that refreshed
stop-status, and refreshes stop-status again against the final gate. The
completion-gate Markdown now also mirrors `may_execute_from_this_result: false`
so human-readable and machine-readable authority fields agree. Focused watch,
stop-status, stable-scan, and hard-gate tests passed, and the full Revit
operator regression passed with `384 passed`. Live one-check read-only watch
`live-north-star-watch-finalization-fix-check-20260514` completed with
`safety_guard_violation_count: 0`, both stop-status refreshes at
`stop_for_human_or_real_condition`, and no execution authority. Follow-up stable
scan `live-stable-scan-after-watch-finalization-fix-20260514` was clean with
zero authority-mirror and stop-status-boundary violations. Follow-up hard gate
`live-completion-gate-after-watch-finalization-fix-20260514` still blocks
completion with four blocked gaps, 17 unsatisfied requirements, and zero safety
guard violations.

Resume-check finalization hardening:
`north-star-resume-check` now uses the same stop-status/final-gate/stop-status
finalization sequence as `north-star-watch`, so the post-human continuation path
cannot complete with a stale stable agent stop-status boundary. Focused
resume-check coverage passed, the combined watch/resume/stop-status/stable-scan
slice passed, and the full Revit operator regression passed with `384 passed`.
Live resume check `live-resume-check-finalization-fix-check-20260514` still
failed bridge validation on `loaded_build_current` and `bridge_readiness_ready`,
but returned `safety_guard_violation_count: 0` with both stop-status refreshes
at `stop_for_human_or_real_condition`. After the approval preflight expired,
the hard gate correctly reported stale-approval guard violations; read-only
refresh `live-refresh-preflight-after-resume-finalization-fix-20260514`
regenerated preflight and handoff artifacts with three approval items ready for
human review and zero unsafe preflight cases. Final stable scan
`live-stable-scan-after-preflight-resume-fix-20260514` was clean, and final
hard gate `live-completion-gate-after-preflight-resume-fix-20260514` remained
blocked with four gaps, 17 unsatisfied requirements, and zero safety guard
violations.

Transport redaction hardening:
Approval-material redaction now replaces approval phrases case-insensitively,
not only in the canonical casing. The local HTTP command-list error path, MCP
command fallback result path, MCP command-list error path, MCP JSON serializer,
and MCP server startup error path all route through the same redaction helper
used by CLI/stdout and plugin outputs. Focused transport coverage passed for
26 selected Revit operator tests and 3 selected plugin tests. This is a safety
hardening step only; it does not unblock the four live north-star gates or grant
execution authority.

Transport safety matrix command:
`transport-safety-matrix` is now a first-class read-only command and required
north-star command-list item. It writes a structured matrix for CLI/stdout,
HTTP/control, MCP, and Hermes plugin redaction plus fail-closed wrapper checks
for external-sandbox overrides, model-root overrides, and recursive server
startup. The command reports `live_revit_touched: false` and withholds raw
approval material from its JSON/Markdown artifacts. This improves auditability
only; it does not unblock the four live north-star gates or grant execution
authority.

Stable transport safety handoff:
`transport-safety-matrix` now also publishes stable
`NORTH_STAR_TRANSPORT_SAFETY_MATRIX_CURRENT.json` and `.md` files at the
sandbox root. `north-star-current-handoff` regenerates those files, includes
them in `NORTH_STAR_HANDOFF_CURRENT.json` `stable_files`, and the stable
artifact scan treats the matrix as timestamped read-only current metadata with
no execution authority. Focused matrix/current-handoff/stable-scan tests passed
for the stable publication path.

Transport safety matrix enforcement:
`north-star-stable-artifact-scan` and the hard `north-star-completion-gate`
now explicitly verify the stable transport matrix. The guard requires
`status: clean`, `read_only: true`, `live_revit_touched: false`,
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, `may_execute_from_this_result: false`,
`failed_count: 0`, `direct_approval_marker_count: 0`, a positive
`check_count`, and Markdown lines mirroring the same fields. Focused regression
coverage passed for clean matrix publication, failing matrix scan violations,
completion-gate safety guard coverage, CLI matrix output, and direct matrix
generation (`5 passed`), the full Revit operator module passed (`416 passed`),
the Revit operator plugin tests passed (`14 passed`), and compileall completed.
Live read-only refresh `live-watch-refresh-after-transport-matrix-gate-20260514`
republished the current handoff; stable scan
`live-stable-scan-after-transport-matrix-gate-20260514` reported
`status: clean`, `violation_count: 0`, and
`transport_safety_matrix_violation_count: 0`; the matrix reported
`status: clean`, `check_count: 14`, `failed_count: 0`,
`direct_approval_marker_count: 0`, and `may_execute_from_this_result: false`.
The hard gate `live-completion-gate-after-transport-matrix-gate-20260514`
remained blocked with `completion_allowed: false`, `may_call_update_goal:
false`, `audit_completion_authorized: false`, four blocked gaps, no autonomous
progress path, and zero safety guard violations.

Human unblock brief redaction consistency:
The sanitized human-unblock brief now marks approval-related option material as
withheld even when the source next-human-action artifact contains a fresh
approval phrase for supervised human review. The stable artifact scan and hard
completion gate now verify the stable
`NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json` / `.md` pair for direct approval
marker leaks, top-level redaction drift, option-level redaction drift, and
conflicting `required_human_approval_phrase_withheld` state. Focused regression
coverage passed for redacted brief generation, stable-scan withheld drift,
agent stop-status propagation, and the clean stable-scan case (`4 passed`);
the full Revit operator module passed (`417 passed`), and plugin coverage
remained green (`14 passed`). Live read-only refresh
`live-watch-refresh-after-human-unblock-redaction-20260514` republished the
current handoff; the stable human-unblock brief reports
`approval_material_included: false`, `approval_material_withheld: true`, and
the approval option reports `approval_material_included: false`,
`approval_material_withheld: true`, and
`required_human_approval_phrase_withheld: true`. Stable scan
`live-stable-scan-after-human-unblock-redaction-20260514` reported
`status: clean`, `violation_count: 0`,
`human_unblock_brief_redaction_violation_count: 0`, and
`transport_safety_matrix_violation_count: 0`. The hard gate
`live-completion-gate-after-human-unblock-redaction-20260514` remained blocked
with `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, no autonomous progress
path, and zero safety guard violations.

Agent stop-status redaction consistency:
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` now normalizes sanitized options
before publication so approval-related stop options explicitly keep
`approval_material_included: false`, `approval_material_withheld: true`, and
`required_human_approval_phrase_withheld: true`. The existing agent stop-status
boundary guard now also verifies option-level redaction state, direct approval
marker counts, option material leak counts, and inconsistent withheld flags.
Focused coverage passed for clean stop-status publication, stop-boundary drift,
option redaction drift, and the clean stable-scan case (`4 passed`); the full
Revit operator module passed (`418 passed`), and plugin coverage remained green
(`14 passed`). Live read-only refresh
`live-watch-refresh-after-agent-stop-redaction-20260514` republished the
current handoff; the stable stop-status artifact reports
`status: stop_for_human_or_real_condition`, `should_stop_agent: true`,
`approval_material_included: false`, and `approval_material_withheld: true`,
with the approval option also reporting material included false, material
withheld true, and phrase withheld true. Stable scan
`live-stable-scan-after-agent-stop-redaction-20260514` reported
`status: clean`, `violation_count: 0`,
`agent_stop_status_boundary_violation_count: 0`,
`inconsistent_withheld_count: 0`, `option_material_leak_count: 0`, and
`human_unblock_brief_redaction_violation_count: 0`. The hard gate
`live-completion-gate-after-agent-stop-redaction-20260514` remained blocked
with `completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, no autonomous progress
path, and zero safety guard violations.

Current handoff stop-status mirror:
`NORTH_STAR_HANDOFF_CURRENT.json` now carries the same credential-free
stop-status authority and redaction fields as
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json`, including
`completion_allowed`, `may_call_update_goal`, `audit_completion_authorized`,
`hard_gate_allows_completion`, `may_execute_from_this_result`,
`approval_material_included`, and `approval_material_withheld`. The current
handoff Markdown now mirrors those fields inside its `Agent Stop Status`
section, and the stable artifact scan/hard completion gate treat missing or
stale handoff stop-status Markdown as a stable-handoff violation. Focused
handoff/stop-status coverage passed (`11 passed`), the full Revit operator
module passed (`419 passed`), plugin coverage passed (`14 passed`), and
compileall completed. Live read-only refresh
`live-watch-refresh-after-handoff-stop-mirror-20260514` republished the current
handoff without focusing, clicking, typing, invoking UIA, restarting, saving,
syncing, reloading, detaching, upgrading, or modifying Revit. Stable scan
`live-stable-scan-after-handoff-stop-mirror-20260514` reported
`status: clean`, `violation_count: 0`,
`handoff_markdown_completion_guard_violation_count: 0`,
`agent_stop_status_boundary_violation_count: 0`, and zero safety violations.
The hard gate `live-completion-gate-after-handoff-stop-mirror-20260514`
remained blocked with `completion_allowed: false`, `may_call_update_goal:
false`, `audit_completion_authorized: false`, four blocked gaps, 17
unsatisfied requirements, no autonomous progress path, and zero safety guard
violations.

Compact status stop-boundary guard:
`NORTH_STAR_STATUS_CURRENT.json` now publishes a credential-free agent stop
signal alongside its completion guard fields: `agent_stop_status`,
`should_stop_agent`, `agent_stop_reason`, `recommended_agent_action`, and
`may_execute_from_this_result: false`. The Markdown status summary mirrors those
same fields, and stable artifact scan now flags missing JSON stop fields,
missing Markdown, unreadable Markdown, or Markdown drift with
`status-summary-stop-boundary-*` violations routed to stable handoff repair.
Focused status/summary coverage passed (`4 passed`), the full Revit operator
module passed (`420 passed`), plugin coverage passed (`14 passed`), compileall
completed, and `git diff --check` still only reported the existing LF/CRLF
warnings on `.gitignore` and `pyproject.toml`. Live status task
`live-status-stop-signal-20260515` reported `agent_stop_status:
stop_for_human_or_real_condition`, `should_stop_agent: true`,
`north_star_complete: false`, four blocked gaps, and no autonomous progress
path. Read-only watch refresh
`live-watch-refresh-after-status-stop-signal-20260515` republished the current
handoff without focusing, clicking, typing, invoking UIA, queueing bridge
writes, restarting, closing, saving, syncing, reloading, detaching, upgrading,
or modifying Revit. Stable scan
`live-stable-scan-after-status-stop-signal-20260515` reported `status: clean`,
`violation_count: 0`, and `status_summary_violation_count: 0`. The hard gate
`live-completion-gate-after-status-stop-signal-20260515` remained blocked with
`completion_allowed: false`, `may_call_update_goal: false`,
`audit_completion_authorized: false`, four blocked gaps, 17 unsatisfied
requirements, `blocked_waiting_for_human_or_real_condition: true`, and zero
safety guard violations.
