# Revit UI Automation Prototype

The first UI automation slice prioritizes observation over action. It provides a stable command interface for Hermes to inspect Revit's real Windows UI state, classify prompts, capture evidence, and perform guarded primitives only after safety evaluation.

Implementation paths:

- `tools/revit_operator/windows.py`
- `tools/revit_operator/actions.py`
- `tools/revit_operator/dialogs.py`
- `tools/revit_operator/ocr.py`
- `tools/revit_operator/operations.py`
- `tools/revit_operator/project_browser.py`
- `tools/revit_operator/addin_installer.py`
- `tools/revit_operator/uia.py`
- `tools/revit_operator/qa.py`
- `tools/revit_operator/recovery.py`
- `tools/revit_operator/supervision.py`
- `tools/revit_operator/workflows.py`
- `tools/revit_operator/workflow_memory.py`
- `tools/revit_operator/cli.py`
- `tools/revit_operator/server.py`
- `plugins/revit-operator/`

## Technology Choice

Phase 1 uses Python stdlib `ctypes` against Win32 APIs:

- `EnumWindows`
- `GetWindowTextW`
- `GetClassNameW`
- `GetWindowRect`
- `GetWindowThreadProcessId`
- `QueryFullProcessImageNameW`
- `CreateToolhelp32Snapshot` / `Process32FirstW` / `Process32NextW`
- `IsHungAppWindow`
- `Enum`-style child traversal through `GetWindow`
- GDI `BitBlt` / `GetDIBits` screenshot capture

This avoids making `pywinauto`, WinAppDriver, OCR, or Pillow mandatory for the first prototype. Optional `pywinauto` is used for UIA tree/detail/action support and for `type-text` execution if installed.

The UIA path uses optional `pywinauto` and exposes AutomationId, ControlType, class name, enabled state, and visibility when available.

The OCR path supports two optional backends: `tesseract` through `Pillow`, `pytesseract`, and a local Tesseract executable; and `rapidocr` through the Python package backend. Missing dependencies are reported as structured artifacts. When an OCR backend exposes item geometry, the artifact preserves text items, confidence, boxes, and computed bounds.

## Commands

### `revit-operator serve`

Runs a loopback local HTTP control server with `GET /health`, `GET /commands`,
and `POST /command`. The server delegates to the same CLI dispatcher, so routed
commands keep the same sandbox checks, safety classifications, approval tokens,
and journals. Recursive `serve` requests are refused.

### Hermes `revit_operator` Plugin Tool

The bundled `plugins/revit-operator` plugin registers a `revit_operator` tool in
toolset `plugin_revit_operator`. It delegates to the same CLI dispatcher and
therefore inherits sandbox checks, safety classification, approval tokens, and
journals. The plugin blocks `serve` inside tool calls.

### `revit-operator health`

Reports platform support and optional dependency availability.

### `revit-operator north-star-audit`

Writes a read-only prompt-to-artifact completion checklist. It verifies named
deliverables, key source files, command coverage, live evidence task markers,
and remaining gaps. The remaining-gap status is derived from current bridge
readiness, supervision endurance, and UI execution coverage artifacts where
those artifacts can prove a gap is closed. It is intentionally allowed to report
`north_star_complete: false`.

### `revit-operator north-star-approval-plan`

Writes a read-only human handoff for the remaining approval-gated north-star
validation steps. The plan includes exact-token commands for already planned
safe candidates, manual items that require human action, and blocked-operation
notes. It does not focus Revit, click, type, invoke UIA, open context menus,
queue bridge work, restart, save, sync, reload, close, detach, upgrade, or
modify the model.

### `revit-operator north-star-unblock-readiness`

Writes a read-only per-blocker readiness packet for the current north-star
gates. It reads stable handoff artifacts, preflight freshness, and current gap
evidence, then reports safe next commands and completion evidence still needed
without exposing approval credentials or granting execution authority.

### `revit-operator north-star-stable-artifact-scan`

Scans sandbox-root `NORTH_STAR_*CURRENT*` artifacts without touching Revit. It
checks for stale approval credentials, status-summary execute leaks,
execution-authority flags, legacy tombstone drift, blocker count mismatches, and
stable `blocked_gap_ids` drift from the hard completion gate. When the latest
approval preflight is fresh, it also checks that existing approval-facing
handoff artifacts were written after that preflight. It also validates the
`stable_files` map inside `NORTH_STAR_HANDOFF_CURRENT.json` so referenced
stable files must exist, remain inside the sandbox, and parse when JSON.

### `revit-operator north-star-watch`

Polls live Revit status, visible dialogs, and bridge readiness without taking
UI or model action. It refreshes the hard completion gate and unblock-readiness
artifacts after polling. Optional `--refresh-approval-preflight` reruns
read-only approval dry-runs with expected Revit/title/view predicates, and
optional `--publish-current-handoff` republishes the stable human handoff bundle
after that preflight so supervision checkpoints do not rely on stale
`NORTH_STAR_HANDOFF_CURRENT.*` files.

### `revit-operator status`

Reports:

- platform support
- running Revit processes
- whether Revit appears to be running
- main window candidate
- active/modal dialog candidates
- state: `unsupported`, `not_running`, `modal`, `busy`, `idle`, or `unknown`
- active document bridge status

### `revit-operator list-processes`

Lists running Revit processes even when a visible Revit window is not found.

### `revit-operator list-windows`

Lists visible Revit-related top-level windows. `--all` includes all top-level windows for troubleshooting.

### `revit-operator list-dialogs`

Lists Revit-related dialog-like windows, extracts visible text/buttons, and classifies each dialog conservatively.

### `revit-operator plan-current-dialog-response`

Reads the currently visible Revit dialog list and writes
`current_dialog_response_plan.json` with the same conservative response plan
used by `plan-dialog-response`. This is read-only and never clicks; any planned
button remains a separate approval-gated `click` dry-run.

`--use-ocr --ocr-backend auto|tesseract|rapidocr` captures a read-only OCR
screenshot when dialog text is inaccessible. OCR text is classified as a prompt
only when fresh Revit status is modal or active dialogs are present. When Revit
is idle, OCR is saved as evidence but not treated as a dialog decision.

### `revit-operator known-dialogs`

Lists built-in reusable dialog rules. The current rule set includes unsigned add-in prompts, pyRevit loader errors, transmitted model prompts, unresolved/missing references, upgrade/detach/open-workset/worksharing prompts, link reloads, family load options, warning review, failure processing, save-changes, and print/export prompts.

### `revit-operator record-dialog-rule`

Records a conservative learned dialog classifier under the sandbox. Learned rules can only be medium/high/critical risk, are used by `classify-dialog`, and never authorize a click or lower a prompt's risk to low.

### `revit-operator dialog-rule-library`

Lists both built-in prompt rules and sandbox-learned classifiers.

### `revit-operator dialog-workflows`

Lists conservative response playbooks for known dialogs, including safe
preflight commands, blocked button labels, and approval conditions for prompts
that remain human-only.

The unsigned Hermes add-in startup prompt has a specific playbook: run
`addin-security-preflight`, prefer `trust-addin` and restart, and only plan
`Always Load` as an approval-gated click when the manifest and DLL path are the
expected local Hermes operator add-in.

Unverified-publisher prompts that do not identify the expected Hermes add-in are
classified separately as unknown unsigned add-ins. They return no planned click
and block all load buttons until a human verifies the publisher, DLL, and
manifest path.

### `revit-operator dialog-workflow-matrix`

Runs a read-only representative validation matrix across every built-in dialog
workflow. It classifies sample prompts, verifies safe preflight commands are
returned, verifies allowed button plans remain approval-gated, and checks that
no planned click targets a blocked button. It writes
`dialog_workflow_matrix.json` under the task journal directory and never
interacts with live Revit dialogs.

### `revit-operator plan-dialog-response`

Classifies supplied dialog text/buttons and, for configured known prompts,
returns an approval-gated `click` dry-run plan. Destructive prompts such as
upgrade remain human-only with no planned click, but still return preflight
evidence commands and blocked-button guidance.

### `revit-operator ui-tree`

Exports a shallow tree of visible child controls for the active Revit target window. The fallback tree is based on Win32 child windows; UIA commands enrich this with AutomationId, ControlType, class names, available action methods, and accessible names where Revit exposes them.

### `revit-operator uia-tree`

Exports an optional Microsoft UI Automation tree through `pywinauto`. When `pywinauto` is not installed, it writes a structured dependency-missing artifact instead of failing unclearly.

### `revit-operator uia-find-control`

Searches the UIA tree by name, ControlType, AutomationId, and class name. This is the semantic locator for ribbon and WPF-style Revit controls that are not visible in the Win32 child-window tree.

### `revit-operator uia-control-details`

Searches matching UIA wrappers and reports visibility, enabled state, path, and available action methods such as `invoke`, `select`, `expand`, `toggle`, `click_input`, `double_click_input`, or `right_click_input`. This is read-only and is intended to choose a safe explicit method before any approved execution.

### `revit-operator uia-method-matrix`

Runs a synthetic, read-only safety matrix over every allowlisted UIA invocation
method. It verifies non-destructive UIA targets require exact approval,
destructive Save targets remain blocked for every method, unsupported methods
are rejected before UIA lookup, and `executed_count` stays zero.

### `revit-operator uia-invoke`

Invokes exactly one visible enabled UIA control after dry-run review and exact approval. It supports `--method auto` plus explicit approved methods such as `select`, `expand`, `double_click_input`, and `right_click_input`. It is routed through the safety governor, so blocked terms such as Save and Synchronize remain blocked even when UIA exposes a matching ribbon item. Ambiguous or disabled matches fail closed.

### `revit-operator ribbon-actions`

Lists named ribbon/menu descriptors such as `view-tab`, `manage-tab`,
`manage-links-command`, `visibility-graphics-command`,
`view-templates-command`, `review-warnings-command`, and blocked descriptors
such as `save`, `print`, `export`, and `publish`.

### `revit-operator ribbon-action-matrix`

Runs a read-only descriptor verifier for every named ribbon action. It checks
that each descriptor has a UIA locator, description, and safety reason; verifies
non-blocked descriptors remain `approval_required`; and verifies blocked
descriptors remain non-executable even if live UIA later finds a matching
control. It writes `ribbon_action_matrix.json` and does not locate, click,
invoke, or focus any live UI control.

### `revit-operator plan-ribbon-action`

Resolves a named ribbon/menu descriptor to live UIA matches and reports whether
the target is executable. It is observation-only.

### `revit-operator ribbon-action`

Dry-runs or executes a named ribbon/menu descriptor through the same
`uia-invoke` safety gate. Descriptors such as Save, Synchronize, Print, Export,
and Publish have no execution path.

### `revit-operator context-menu-actions`

Lists named context-menu descriptors such as `project-browser-item-menu`,
`visible-control-menu`, and blocked descriptors such as `save-control-menu`.

### `revit-operator context-menu-action-matrix`

Runs a read-only descriptor and representative item verifier for context-menu
workflows. It checks target locators, descriptions, safety reasons,
`right_click_input` usage, approval-gated non-blocked descriptors, blocked Save
surfaces, and representative item policies such as Properties requiring
approval while Delete and Save remain blocked. It writes
`context_menu_action_matrix.json` and does not open a context menu or select a
menu item.

### `revit-operator context-menu-snapshot`

Captures read-only UIA evidence for visible `Menu` and `MenuItem` controls and
writes `context_menu_snapshot.json`. This is intended immediately after a
context menu is opened so Hermes can inspect available menu items before any
selection is planned.

### `revit-operator plan-context-menu-action`

Resolves a named context-menu descriptor to live UIA matches. The plan is
read-only and executable only when one visible enabled target is found. It also
states the required post-open observation commands because menu item selection
is a separate action.

### `revit-operator context-menu-action`

Dry-runs or executes opening one context menu through `uia-invoke --method
right_click_input`. It never selects a context-menu item; after opening a menu,
Hermes must observe the UI again, classify any available menu item, and request
fresh approval before selecting anything.

### `revit-operator plan-context-menu-item`

Resolves one exact visible `MenuItem` target after a context-menu snapshot.
Dangerous item names such as Delete or Save remain blocked by the safety
governor.

### `revit-operator context-menu-select-item`

Dry-runs or executes selecting one exact `MenuItem` through the `uia-invoke`
safety gate. It is approval-required because selecting a menu item can run a
Revit command or change UI/model state.

### `revit-operator find-control`

Searches the active Revit target's Win32 UI tree by visible text and/or class name and writes `control_matches.json` under the task run directory. This is the first read-only control locator for future Project Browser, palette, ribbon, and dialog workflows.

### `revit-operator project-browser-snapshot`

Locates the visible Project Browser control, captures a shallow UI tree and BMP screenshot for that control hwnd, and writes `project_browser_snapshot.json`. `--include-uia` adds UIA node evidence, and `--include-ocr --ocr-backend auto|tesseract|rapidocr` adds read-only OCR text and item geometry evidence for the Project Browser region when available. This is observation only; it does not activate views, change selection, expand tree nodes, click coordinates, or navigate.

### `revit-operator project-browser-plan-navigation`

Captures Project Browser evidence, optionally including UIA/OCR evidence,
searches bridge metadata for a requested sheet/view, and writes
`project_browser_navigation_plan.json`. When exactly one non-placeholder match
exists, it recommends the guarded
`request-operation --operation activate-view` path because that route is more
deterministic than clicking Project Browser rows. This is planning only; it
does not click, select, or activate anything.
When OCR is enabled, the plan also includes `visual_evidence` with OCR line or
item matches for the requested sheet/view text. RapidOCR item matches include
confidence, polygon boxes, and computed bounds when available. Those matches
are human-readable fallback evidence only; they are not coordinate-click
targets.

### `revit-operator project-browser-plan-visual-activation`

Plans a visual fallback click from Project Browser OCR geometry. It requires a
single OCR item match with bounds and writes
`project_browser_visual_activation_plan.json` with the target text, window
coordinates, screen coordinates, and exact `visual-click` approval token. This
is read-only planning; it does not click.

### `revit-operator project-browser-visual-activate`

Runs the OCR-geometry visual fallback through `SafeActionExecutor` as a
`visual-click` primitive. It dry-runs by default, captures fresh evidence,
requires the exact approval token for the current coordinate payload, and is
intended only when metadata-backed or UIA-backed routes are unavailable.

### `revit-operator project-browser-plan-activation`

Locates the Project Browser hwnd and searches for an item-level UIA target by
name, control type, AutomationId, or class. The plan is read-only and marks the
action executable only when exactly one visible enabled target is found.

### `revit-operator project-browser-activate-item`

Runs the direct Project Browser UIA activation path through the same
`uia-invoke` safety gate. It dry-runs by default and requires the exact approval
token before execution. If no item-level UIA target is exposed, it remains
non-executable and recommends metadata-backed navigation.

### `revit-operator properties-palette-snapshot`

Locates the visible Properties palette, captures a shallow UI tree and BMP
screenshot for that palette hwnd, and writes
`properties_palette_snapshot.json`. `--include-uia` adds UIA node evidence, and
`--include-ocr --ocr-backend auto|tesseract|rapidocr` adds read-only OCR text
and item geometry evidence. This is observation only; it does not change
selection, focus controls, type parameter values, click Apply, or modify the
model.

### `revit-operator find-view`

Searches the latest bridge metadata snapshot for matching sheets/views by query,
view name, sheet number, and view type. Exact non-placeholder matches include
an `activate-view` hint for a later `request-operation` dry-run. This command is
read-only and does not interact with the Project Browser directly.

### `revit-operator request-operation --operation activate-view`

Queues an in-process Revit API active-view change after exact human approval.
The dry-run is critical-risk, returns an approval token, and execution writes to
the bridge queue only when the token matches the exact payload. It intentionally
does not require `--allow-model-write` because changing the active view should
not modify model contents, but it still changes session state and remains
approval-required.

### `revit-operator screenshot`

Captures the active Revit target window to BMP under the task journal's screenshot directory.

### `revit-operator ocr-screenshot`

Captures a screenshot and runs optional OCR. `--backend auto` chooses the first available backend; `--backend tesseract` requires Pillow, pytesseract, and the Tesseract executable; `--backend rapidocr` uses the Python RapidOCR package backend. If OCR dependencies are absent, it still writes `ocr_screenshot.json` with a screenshot path, dependency list, backend health, and install hint. When the OCR result includes geometry, `ocr_screenshot.json` includes `items` with text, confidence, boxes, and bounds.

### `revit-operator ocr-health`

Reports readiness for both OCR backends, including Pillow, pytesseract, local Tesseract executable discovery, RapidOCR package availability, preferred backend, and install hints. This is read-only and captures no UI.

### `revit-operator wait-model-ready`

Polls Revit until the observer reports idle state, no active/modal dialogs, and
an active-document bridge payload is available. Optional predicates can require
title/path text, Revit version, active view name, and active view type. It writes
`model_ready_status.json` and stops immediately on modal state by default. This
is read-only; it does not dismiss prompts, open models, activate views, save, or
sync.

### `revit-operator list-revit-installs`

Lists Revit executables discovered under `C:\Program Files\Autodesk\Revit 20??` and reports the default test model hint.

### Guarded Actions

Implemented action primitives:

- `focus`
- `press-key`
- `click --target <button text>`
- `type-text --text <text>`
- `ocr-health`
- `ocr-screenshot`
- `wait-for-window`
- `wait-for-dialog`
- `wait-model-ready`
- `uia-tree`
- `uia-find-control`
- `uia-control-details`
- `uia-method-matrix`
- `uia-invoke`
- `ribbon-actions`
- `ribbon-action-matrix`
- `plan-ribbon-action`
- `ribbon-action`
- `north-star-status`
- `north-star-audit`
- `north-star-approval-plan`
- `north-star-watch`
- `north-star-resume-check`
- `north-star-human-gate-packet`
- `north-star-unblock-readiness`
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
- `open-model`
- `request-operation`
- `install-addin`
- `addin-security-preflight`
- `qa-report`
- `qa-workflow`
- `bridge-results`
- `bridge-readiness`
- `bridge-restart-validation-plan`
- `bridge-post-restart-validation`
- `verify-bridge-build`
- `wait-bridge-result`
- `recovery-snapshot`
- `recovery-drill-matrix`
- `supervise-session`
- `supervision-endurance-matrix`
- `supervision-endurance-audit`
- `ui-workflows`
- `ui-workflow-matrix`
- `ui-workflow-smoke-matrix`
- `plan-ui-workflow`
- `run-ui-workflow`
- `workflow-library`
- `record-workflow`
- `plan-workflow`
- `workflow-approval-plan`
- `replay-workflow`

All actions:

- dry-run by default
- run through `classify_action`
- return structured JSON
- log before/after observations when possible
- require `--execute` to act
- require `--approval-token` for high-risk primitives
- can use `--expect-state <state>` to verify the observed state after execution

### `revit-operator action-approval-matrix`

Dry-runs representative human-style primitives through the same
`SafeActionExecutor` and classifies representative bridge operations without
queueing them. The matrix checks that low-risk Escape and read-only
active-document operations are allowed, risky focus/click/type/UIA/visual-click
cases expose exact approval tokens, and generic Save surfaces are blocked. It
writes `action_approval_matrix.json` and reports `executed_count: 0`.

### `revit-operator ui-execution-coverage-audit`

Scans sandboxed task journals for authorized executed UI actions and groups
them by coverage surface: focus, Escape, dialog click, type text, UIA invoke,
visual click, ribbon action, context-menu action, context-menu item, and
approved UI workflow step. Ribbon and context-menu coverage is detected from
the executed UIA payload markers, not only from task names. Dry-runs and
low-risk recipe steps are excluded; workflow coverage requires
`approved_executed_steps` from a token-backed `run-ui-workflow` execution. It writes
`ui_execution_coverage_audit.json`, reports
missing surfaces, and does not poll, focus, click, type, invoke UIA, queue
bridge operations, save, sync, reload, close, detach, upgrade, or modify Revit.

### `revit-operator open-model`

Launches a selected Revit executable with a copied local `.rvt` path after dry-run review and approval. It infers `R25` as Revit 2025, reports expected prompts such as upgrade/detach/worksets, and logs the launch plan before execution.

### `revit-operator request-operation`

Queues a command for the in-process add-in under:

```text
<sandbox>\bridge\command_queue.jsonl
```

The add-in writes results to:

```text
<sandbox>\bridge\command_results.jsonl
```

Supported operations include read-only metadata export, add-in-side model opening with detach options, and guarded save/sync/reload/close/modify commands.

### `revit-operator run-safe-command`

Provides the first conservative safe-command wrapper requested by the north-star
prompt. It delegates only to read-only bridge operations: `active-document`,
`export-metadata`, and `qa-snapshot`. The command is dry-run by default; with
`--execute`, it can queue only those read-only operations. Unsupported names such
as `save`, `sync`, `reload-links`, or `activate-view` are blocked instead of
falling through to arbitrary bridge execution.

### `revit-operator bridge-results`

Lists recent results written by the in-process add-in under:

```text
<sandbox>\bridge\command_results.jsonl
```

This gives Hermes an explicit way to inspect completed add-in work without parsing journals or assuming a command finished.

### `revit-operator bridge-readiness`

Runs a read-only readiness audit for the add-in bridge. It checks the expected
Revit add-in manifest, the built DLL, the loaded bridge status, and current
loaded-build metadata. It returns `ready_for_continuous_bridge: true` only when
the installed manifest, DLL, and running Revit session all agree. If the DLL and
manifest are ready but Revit is still running an old payload, it returns
`requires_revit_restart_or_reload: true` and does not close, restart, save, sync,
or modify Revit.

### `revit-operator bridge-restart-validation-plan`

Writes a read-only human handoff plan when the installed bridge is ready but the
running Revit session needs a human restart or reload. It includes blocked
automation rules, post-restart validation commands, and success criteria for
`bridge-status`, `verify-bridge-build`, `bridge-readiness`, and
`wait-model-ready`. It never closes, restarts, saves, syncs, reloads, or modifies
Revit.

### `revit-operator bridge-post-restart-validation`

Runs the post-human-restart validation chain in one read-only command. It
observes Revit status, reads bridge status, verifies the loaded build, checks
bridge readiness, runs add-in security preflight, waits for model readiness with
expected predicates, and refreshes `north-star-audit`. It returns
`validation_passed: true` only when every check passes. Before a human
restart/reload, it should fail safely on stale loaded-build/readiness checks
without focusing, clicking, typing, invoking UIA, closing, restarting, saving,
syncing, reloading, detaching, upgrading, or modifying Revit.

### `revit-operator north-star-resume-check`

Runs the read-only resume path after a human-gated state changes. It refreshes
the compact north-star status, writes a fresh approval handoff, runs
`bridge-post-restart-validation` when the bridge restart gap is still open and
Revit is running, refreshes the full north-star audit, and writes
`north_star_resume_check.json`. It reports `may_call_update_goal: true` only if
the refreshed hard completion gate proves completion.

### `revit-operator north-star-watch`

Polls Revit state, dialog count, and bridge readiness read-only while waiting
for a human restart/reload or a real recovery condition. After polling it
refreshes the hard `north-star-completion-gate`, publishes stable current
audit/gate files, and writes `north-star-unblock-readiness`. With
`--refresh-approval-preflight`, it also reruns read-only approval dry-runs with
expected Revit/title/view context before the hard gate. It does not focus,
click, type, invoke UIA, queue bridge writes, close, restart, save, sync,
reload, detach, upgrade, or modify Revit.

### `revit-operator north-star-human-gate-packet`

Writes a concise human handoff packet in JSON and Markdown. The packet includes
remaining manual gates, approval-token commands, expected effects, blocked
effects, and the `north-star-resume-check` command to run after a human action.
It is intentionally a handoff artifact only and does not approve, focus, click,
type, invoke UIA, queue bridge writes, save, sync, reload, close, detach,
upgrade, or modify Revit.

### `revit-operator verify-bridge-build`

Reads the bridge status and verifies that the loaded Revit add-in reports the current bridge protocol, source capability stamp, and continuous-Idling flags. It is read-only and returns `status: current` only when the running Revit session has loaded the expected add-in payload; otherwise it returns `stale_or_unverified` with failed checks and a restart/reload recommendation.

### `revit-operator wait-bridge-result`

Waits for a specific bridge command id and returns the matching result, timeout status, and check count. This is the first supervision primitive for long-running Revit API-thread operations.

### `revit-operator recovery-snapshot`

Captures a read-only stuck-state evidence bundle with status, dialogs, embedded dialog recovery plans, UI tree, screenshot, active document bridge state, recent bridge results, and a conservative recommended next step. It is intended for recovery and human escalation before repeating actions.

### `revit-operator recovery-drill-matrix`

Runs a read-only synthetic recovery validation matrix for modal, busy, idle,
not-running, and unknown states. It verifies conservative recommendation
classifications, expected safe commands, next-step guidance, known-dialog id
preservation, and no automatic action for a high-risk upgrade prompt. It writes
`recovery_drill_matrix.json` and does not touch live Revit UI.

### `revit-operator supervise-session`

Polls Revit status and recent bridge results for a bounded duration, records state transitions, and stops early on modal dialogs unless configured otherwise. It is read-only and writes `supervision_log.json`. Long runs checkpoint the log after each observation with `checkpoint_status: running` and `supervisor_pid`, then overwrite it with `checkpoint_status: complete` on clean exit so partial endurance evidence is recoverable after interruption.

### `revit-operator supervision-endurance-matrix`

Runs bounded synthetic drills through the real `supervise-session` loop. It
validates resume/append across multiple segments, modal stopping, repeated busy
stall detection with recovery snapshot capture, and repeated unknown-state
stall detection with recovery disabled. It writes
`supervision_endurance_matrix.json` and normal per-case supervision logs, but it
does not observe, click, type, queue, save, sync, or modify live Revit.

### `revit-operator supervision-endurance-audit`

Scans sandboxed `supervision_log.json` files and measures only qualifying live
logs against a target duration/check count. By default it excludes synthetic
matrix/test logs and requires live main-window evidence. Qualifying intervals
are merged before computing `total_live_seconds`, so overlapping supervisors
cannot double-count elapsed evidence; `raw_total_live_seconds` is preserved for
diagnostics. In-progress logs report active/stale supervisor PID status when a
PID is available. It writes `supervision_endurance_audit.json`, reports
`target_met`, and does not poll, focus, click, type, queue bridge operations,
save, sync, or modify Revit.

### `revit-operator install-addin`

Writes the Revit `.addin` manifest after the add-in DLL has been built. Dry-run reports the target manifest path, expected assembly path, and missing build prerequisites.

### `revit-operator addin-security-preflight`

Read-only startup prompt preflight for the Hermes Revit add-in. It checks the
installed Revit-version manifest, confirms the Assembly path points to the
expected `HermesRevitOperator.dll`, probes Authenticode signature status, and
returns whether `Always Load` may even be considered after exact human approval.
It does not click, sign, trust certificates, restart Revit, save, sync, or
modify the model.

### `revit-operator qa-report`

Generates a draft QA report from `metadata_snapshot.json` or the latest exported metadata.

### `revit-operator qa-workflow`

Runs the first supervised read-only workflow:

- observe current Revit status
- refuse to proceed if active dialogs are present
- queue `active-document`
- wait for the bridge result
- queue `export-metadata`
- wait for the bridge result
- copy metadata into the task run directory
- capture UI tree and screenshot
- generate a draft QA report

When the currently loaded add-in is not polling continuously, `--focus-hwnd`, `--focus-approval-token`, and `--idle-nudge` can safely focus Revit and press Escape to trigger an Idling pass.

### `revit-operator ui-workflows`

Lists named guarded workflow recipes that compose existing low-level primitives
without executing them. Current recipes cover unsigned add-in startup preflight,
bridge readiness, Project Browser sheet navigation, Manage Links inspection,
Review Warnings, Visibility/Graphics, View Templates, context-menu inspection,
modal-dialog recovery, and read-only QA.

### `revit-operator ui-workflow-matrix`

Runs a read-only static verifier over every reusable UI workflow recipe. It
renders sample parameters, verifies required placeholders resolve, checks that
recipes document blocked actions and approval gates, confirms no step is
generically blocked by safety policy, confirms approval-required steps expose
exact tokens, and verifies manual placeholder steps are annotated so replay
stops for review. It writes `ui_workflow_matrix.json` and never runs a live
Revit command.

### `revit-operator ui-workflow-smoke-matrix`

Runs smoke-safe prefixes of every reusable UI workflow recipe against the
current Revit session. The command runner allowlist is limited to
observation/planning commands such as status, dialog planning, readiness checks,
bridge readiness diagnostics, ribbon/context planning, Project Browser planning,
and recovery snapshots. It stops before approval-gated, blocked,
manual-placeholder, or non-smoke-safe steps. Stale bridge-readiness diagnostics
are recorded as nonfatal evidence because they are expected until Revit loads
the rebuilt add-in.

### `revit-operator plan-ui-workflow`

Renders one UI workflow recipe to a structured checklist with preconditions,
blocked actions, approval gates, missing parameters, and step-level safety
classification. The planner is read-only and never clicks, queues bridge
commands, saves, syncs, reloads, closes, or modifies Revit.

### `revit-operator run-ui-workflow`

Runs a recipe through a supervised step runner. Before every step it captures a
fresh Revit status observation. Low-risk observation/planning steps can run;
approval-gated steps stop unless the caller supplies the exact step-indexed
approval token. With `--execute`, the runner passes `--execute` only to approved
steps. Missing manual placeholders, blocked policies, unexpected modal UI, and
command failures stop the run by default. Recipes can include read-only
readiness gates such as `wait-model-ready`; the Project Browser sheet recipe now
checks Revit 2025 active-document readiness before OCR-backed navigation.

### `revit-operator record-workflow`

Records an existing task journal as a reusable workflow template under:

```text
<sandbox>\revit_operator_workflows\
```

Approval tokens are not recorded. Templates explicitly require fresh observation and fresh safety classification before any future replay. When the source journal contains enough context, recorded steps also carry state predicates for active document title/path, Revit version, active view, main-window identity, and modal dialog title/text/buttons. Common payload fields such as `target`, `text`, `key`, `name`, `sheet_number`, `view_name`, and `query` are emitted as parameter bindings so future plans can vary a recorded workflow without editing the template by hand.

### `revit-operator workflow-library`

Lists recorded workflow templates in the selected sandbox.

### `revit-operator plan-workflow`

Dry-runs a recorded workflow replay plan. It re-classifies every recorded step, marks all steps as non-executing, reports approval-required and blocked steps, and preserves the rule that actual replay requires fresh observation and approvals. `--parameters-json` accepts a JSON object of parameter overrides; overrides are applied to copied step payloads and then classified, so changing a harmless recorded target to `Save` is blocked during planning.

### `revit-operator workflow-approval-plan`

Writes a fresh approval package for a recorded workflow replay. It regenerates
exact approval tokens from current payload classification, reports blocked
steps, emits a guarded `replay-workflow --execute --approval-tokens-json ...`
command only when no step is blocked, and proves recorded approval tokens were
not reused. It is read-only and writes `workflow_approval_plan.json`.

### `revit-operator replay-workflow`

Runs the first guarded replay path for recorded workflow templates. It is
dry-run by default, observes Revit before every step, stops on modal UI by
default unless the recorded step expects a matching modal dialog, reclassifies
each step, checks recorded state predicates against the fresh observation, and
executes only guarded action primitives or `request-operation`. Approval tokens
are supplied as fresh step-indexed inputs and are never stored in the workflow
template.

`--parameters-json` can also be supplied to replay; the runner applies those overrides before fresh classification and before any approval check.

## UI Target Selection

The default target selection is:

1. foreground visible Revit dialog if present
2. first visible Revit dialog if present
3. foreground main Revit window if present
4. largest visible non-dialog Revit window

This favors modal prompt handling before general window interaction.

## Screenshot Format

The first prototype writes BMP because it can be generated with stdlib + Win32/GDI. Future improvements may add PNG output through Pillow or Windows Imaging Component, but BMP is sufficient for durable evidence capture.

## Known Limitations

- OCR screenshot capture, dependency health checks, live RapidOCR text extraction with item geometry, opt-in OCR fallback for current-dialog planning, and opt-in Project Browser OCR evidence are verified. Tesseract remains unavailable on this machine, and OCR accuracy checks across real modal prompts still need broader validation.
- UIA tree, semantic control search, available-method inspection, approval-gated explicit methods, parameterized workflow planning, and state-predicate guarded workflow replay exist when dependencies are available; broader live workflow replay validation is still incomplete.
- Named ribbon descriptors exist for common Revit tabs, selected command-level UIA name searches, plus blocked File/Save/Sync/Print/Export/Publish surfaces; context-menu descriptors exist for selected actions, with static descriptor and representative item policy validation. A broad command-level ribbon/menu/context-menu workflow semantic model is still incomplete.
- Project Browser observation, optional OCR line/item-match evidence with bounds, read-only navigation planning, approval-gated OCR-geometry visual-click fallback planning/dry-run, and guarded direct UIA activation exist. The current live Project Browser exposes the panel hwnd but not item-level UIA rows for `S2.0`, so UIA direct activation is not live-executable in that state.
- Properties palette observation, screenshot, UIA evidence, and OCR item extraction are live-verified. Parameter editing remains intentionally unsupported.
- Model-ready predicates are live-verified for idle/non-modal active-document state, expected Revit version, and expected active view.
- The running Revit session must load the rebuilt add-in DLL before source changes such as continuous Idling polling take effect.
- Model opening is launch-only; detach/upgrade/workset choices are still handled through observed Revit prompts.
- Save/sync/write operations require the add-in DLL to be built, installed, loaded in Revit, and explicitly approved.
- UIA methods and `type-text` execution depend on optional `pywinauto`.
- UI automation is only supported on native Windows.

## Future UIA Expansion

The next implementation pass should add:

- broader live validation of UIA methods and Revit-specific patterns beyond invoke/select/click fallbacks
- OCR fallback for inaccessible dialogs
- persistent known-dialog classifier library beyond the built-in rules
- ribbon/menu/context-menu navigation descriptors
- Project Browser tree handling
- broader Properties palette workflows beyond read-only extraction
- broader wait predicates for command-specific completion beyond active-document readiness
- screenshot diffing and visual verification
- broader live workflow replay validation with state predicates and fresh approval gates
