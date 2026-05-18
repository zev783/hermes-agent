# Revit Human-Operator Layer

This document defines the first Hermes Revit human-operator layer: a local, safety-governed automation surface that can observe and operate Autodesk Revit as a cautious human operator would. The current prototype is implemented under `tools/revit_operator/` and exposed through the `revit-operator` console script, a local HTTP wrapper, a Hermes plugin wrapper, and a thin MCP stdio wrapper.

The layer is deliberately not just an MCP server, pyRevit script, or metadata exporter. MCP may become the external protocol later, but the hard capability is safe, observable, reversible operation of a Windows desktop application whose workflows often require native UI.

## Goals

The operator layer gives Hermes a durable foundation for future Revit tasks by combining:

- Windows UI observation and interaction
- Revit API state through an in-process add-in bridge
- conservative dialog and action risk classification
- reusable known-dialog rules for common Revit prompts
- screenshot, UI tree, and window/process inspection
- dry-run first action primitives
- supervised model-opening and model-operation requests
- sandboxed read-only metadata export
- in-process add-in command execution for API-thread operations
- append-only task journals
- sandboxed workflow templates recorded from successful runs
- recovery snapshots for stuck-state evidence and next-step guidance
- human approval gates for risky operations

The design target is a supervised junior Revit operator: it observes first, reports uncertainty, asks before risky decisions, refuses production writes by default, and records everything.

## Architecture

The system has four cooperating parts.

### 1. Revit UI Operator

Prototype path: `tools/revit_operator/windows.py`

The UI operator enumerates visible Windows UI state and extracts Revit-related windows, dialogs, controls, and screenshots.

Current capabilities:

- `list-windows`: enumerate top-level windows and filter Revit-related windows
- `status`: detect unsupported, not running, modal, busy, idle, or unknown state
- `list-dialogs`: extract visible dialog text/buttons and classify risk
- `ui-tree`: export a shallow Win32 child-window tree
- `screenshot`: capture the active Revit window to BMP using Win32/GDI

Implementation starts with stdlib `ctypes` Win32 APIs so Phase 1 has no new hard dependency. Optional dependencies such as `pywinauto` can deepen UIA support later.

### 2. Revit In-Process Sensor / Command Add-in

Prototype path: `tools/revit_operator/bridge.py`
Add-in source path: `tools/revit_operator/addin/`

The implementation includes a Revit add-in source project. The add-in loads as `IExternalApplication`, uses Revit's `Idling` event as the API-thread bridge, and exchanges JSON files with Hermes under the sandbox:

- `<sandbox>/bridge/active_document.json`
- `<sandbox>/bridge/addin_status.json`
- `<sandbox>/bridge/addin_heartbeat.json`
- `<sandbox>/bridge/metadata_snapshot.json`
- `<sandbox>/bridge/command_queue.jsonl`
- `<sandbox>/bridge/command_results.jsonl`

The CLI reads these files if present and otherwise returns clear stub responses. The add-in source builds against Revit 2025 when a .NET SDK and the local Revit API DLLs are available.

Current add-in responsibilities:

- run Revit API work on the API thread through `Idling`
- write add-in status/heartbeat files with loaded assembly, bridge protocol, session id, and continuous-Idling capability metadata
- expose read-only active document state
- expose model-ready predicates for idle/non-modal active document verification
- export model metadata
- write command results for long-running supervision
- execute guarded operations from the command queue:
  - active-document
  - export-metadata / qa-snapshot
  - save
  - synchronize-with-central
  - reload-links
  - close-model
  - set-project-info-parameter / modify-model

### 3. Agent Control Interface

Prototype paths: `tools/revit_operator/cli.py`, `tools/revit_operator/server.py`, `tools/revit_operator/mcp_server.py`, `plugins/revit-operator/`

The first stable interface is a local CLI wrapper, with optional local HTTP, Hermes plugin, and MCP stdio wrappers that route requests back through the same parser, safety checks, sandbox validation, and journal path:

- `revit-operator serve`
- `revit-operator health`
- `revit-operator north-star-status`
- `revit-operator north-star-audit`
- `revit-operator north-star-approval-plan`
- `revit-operator north-star-watch`
- `revit-operator north-star-resume-check`
- `revit-operator north-star-human-gate-packet`
- `revit-operator north-star-stable-artifact-scan`
- `revit-operator north-star-unblock-readiness`
- `revit-operator status`
- `revit-operator list-processes`
- `revit-operator list-revit-installs`
- `revit-operator list-windows`
- `revit-operator list-dialogs`
- `revit-operator known-dialogs`
- `revit-operator dialog-rule-library`
- `revit-operator dialog-workflows`
- `revit-operator dialog-workflow-matrix`
- `revit-operator classify-dialog`
- `revit-operator plan-dialog-response`
- `revit-operator plan-current-dialog-response`
- `revit-operator record-dialog-rule`
- `revit-operator screenshot`
- `revit-operator ocr-screenshot`
- `revit-operator ocr-health`
- `revit-operator ui-tree`
- `revit-operator uia-tree`
- `revit-operator uia-find-control`
- `revit-operator uia-control-details`
- `revit-operator uia-method-matrix`
- `revit-operator uia-invoke`
- `revit-operator ribbon-actions`
- `revit-operator ribbon-action-matrix`
- `revit-operator plan-ribbon-action`
- `revit-operator ribbon-action`
- `revit-operator context-menu-actions`
- `revit-operator context-menu-action-matrix`
- `revit-operator context-menu-snapshot`
- `revit-operator plan-context-menu-action`
- `revit-operator context-menu-action`
- `revit-operator plan-context-menu-item`
- `revit-operator context-menu-select-item`
- `revit-operator action-approval-matrix`
- `revit-operator ui-execution-coverage-audit`
- `revit-operator find-control`
- `revit-operator project-browser-snapshot`
- `revit-operator project-browser-plan-navigation`
- `revit-operator project-browser-plan-visual-activation`
- `revit-operator project-browser-visual-activate`
- `revit-operator project-browser-plan-activation`
- `revit-operator project-browser-activate-item`
- `revit-operator properties-palette-snapshot`
- `revit-operator wait-until-idle`
- `revit-operator wait-model-ready`
- `revit-operator export-metadata`
- `revit-operator find-view`
- `revit-operator bridge-status`
- `revit-operator bridge-readiness`
- `revit-operator bridge-restart-validation-plan`
- `revit-operator bridge-post-restart-validation`
- `revit-operator verify-bridge-build`
- `revit-operator bridge-results`
- `revit-operator wait-bridge-result`
- `revit-operator recovery-snapshot`
- `revit-operator recovery-drill-matrix`
- `revit-operator supervise-session`
- `revit-operator supervision-endurance-matrix`
- `revit-operator supervision-endurance-audit`
- `revit-operator ui-workflows`
- `revit-operator ui-workflow-matrix`
- `revit-operator ui-workflow-smoke-matrix`
- `revit-operator plan-ui-workflow`
- `revit-operator run-ui-workflow`
- `revit-operator workflow-library`
- `revit-operator record-workflow`
- `revit-operator plan-workflow`
- `revit-operator workflow-approval-plan`
- `revit-operator replay-workflow`
- `revit-operator focus`
- `revit-operator press-key`
- `revit-operator click`
- `revit-operator type-text`
- `revit-operator wait-for-window`
- `revit-operator wait-for-dialog`
- `revit-operator open-model`
- `revit-operator request-operation`
- `revit-operator install-addin`
- `revit-operator addin-security-preflight`
- `revit-operator trust-addin`
- `revit-operator qa-report`
- `revit-operator task-log`
- `revit-operator-mcp`

Commands return structured JSON and write journal entries. Hermes can call this through terminal execution, through `POST /command` on the local HTTP server, through the `revit_operator` tool registered by the `revit-operator` plugin when that plugin/toolset is enabled, or through the `revit_operator_command` MCP tool exposed by `revit-operator-mcp`. The MCP layer is intentionally only a wire protocol wrapper; it blocks long-running server commands and delegates to the existing safety-gated dispatcher.

### 4. Safety Governor

Prototype path: `tools/revit_operator/safety.py`

The governor classifies every command before execution:

- observation/read-only commands are low risk
- UI actions are dry-run capable and logged
- high-risk actions require an exact-action approval token
- generic UI clicks on save/sync/publish/delete/overwrite remain blocked
- explicit named Revit operations such as save/sync/reload/modify can be queued only with exact approval and operation-specific guard flags
- unknown dialogs are treated as high risk

The governor is intentionally conservative. The system should fail closed when it cannot determine a safe action.

## Data Flow

1. Hermes invokes `revit-operator <command>`.
2. The CLI resolves the sandbox and creates/opens a task journal.
3. The UI observer captures current Revit window/dialog state.
4. The bridge stub reads active document or metadata handoff files if present.
5. The safety governor classifies actions and dialogs.
6. Commands return JSON and append JSONL/Markdown journal entries.
7. Screenshots, UI trees, and metadata are written only under the sandbox.

## Repository Artifacts

Current prototype source:

- `tools/revit_operator/constants.py`: safe project paths and draft label
- `tools/revit_operator/safety.py`: action/dialog classification and sandbox checks
- `tools/revit_operator/dialogs.py`: reusable known-dialog rules
- `tools/revit_operator/journal.py`: JSONL/Markdown task journaling
- `tools/revit_operator/windows.py`: Win32 window/dialog/tree/screenshot observation
- `tools/revit_operator/actions.py`: dry-run and guarded action executor
- `tools/revit_operator/bridge.py`: Revit add-in handoff/stub
- `tools/revit_operator/workflows.py`: supervised read-only workflows
- `tools/revit_operator/workflow_memory.py`: sandboxed workflow template recording/listing
- `tools/revit_operator/recovery.py`: read-only recovery snapshots and recommendations
- `tools/revit_operator/cli.py`: local command interface
- `tools/revit_operator/server.py`: local HTTP control interface over the CLI command surface
- `tools/revit_operator/mcp_server.py`: MCP stdio wrapper over the same control dispatcher
- `plugins/revit-operator/`: Hermes plugin tool wrapper over the CLI dispatcher

Packaging:

- `pyproject.toml` exposes `revit-operator = "tools.revit_operator.cli:main"`

## Phase Map

Phase 1 is implemented as the current prototype:

- status
- list-processes
- list-windows
- list-dialogs
- screenshot
- optional OCR screenshot fallback
- OCR dependency readiness checks
- ui-tree
- optional UIA tree and semantic UIA control search through `pywinauto`
- named guarded ribbon/menu action descriptors backed by UIA, plus read-only descriptor matrix validation
- named guarded context-menu descriptors, read-only descriptor/item policy matrix validation, menu item snapshots, and exact-item selection through the same UIA approval gate
- read-only action approval matrix rehearsal for representative primitive and bridge-operation policies
- find-control by visible text/class from the Win32 tree
- Project Browser snapshot by located control hwnd
- Properties palette snapshot by located control hwnd
- risk classifier
- 21 known-dialog rules for common high-risk prompts
- sandboxed learned dialog-rule recording/listing for conservative prompt recognition
- 21 conservative dialog response playbooks for known prompts, plus a read-only representative matrix verifier that checks classifications, blocked buttons, preflight commands, and approval-gated planned clicks
- task journaling

Phase 2 is implemented as guarded primitives and model opening:

- focus
- press-key
- click named button
- wait-for-window
- wait-for-dialog
- type text through optional `pywinauto`
- open a context menu for one exact UIA target through `right_click_input`
- dry-run default
- approval token required for high-risk UI actions, with `action-approval-matrix` validating representative allow/approval/block cases, `uia-method-matrix` validating supported UIA method policy without executing UI, and `ui-execution-coverage-audit` measuring which authorized live UI surfaces have actually executed
- optional `--expect-state` verification after executed actions
- `open-model` launches a selected Revit version with a copied local model after approval

Phase 3 source and command supervision are implemented:

- active document handoff contract
- metadata snapshot handoff contract
- metadata-backed `find-view` lookup with approval-gated activation hints
- sandboxed stub metadata export
- Revit add-in source project
- add-in manifest installer command
- add-in status and heartbeat inspection with loaded-build metadata
- bridge command result listing and waiting
- read-only bridge restart/reload validation handoff and one-shot post-restart validation when the installed DLL is ready but the running Revit session is stale
- recovery snapshot bundle for stuck-state capture and synthetic recovery drill validation
- read-only supervision loop for state transitions, recent bridge results, and resume/append by task id
- synthetic supervision endurance matrix for resume, modal-stop, busy-stall, and unknown-stall behavior
- command queue for guarded in-process save/sync/reload/close/modify operations

Phase 4 has a first read-only workflow:

- `qa-workflow` queues read-only active-document and metadata commands
- bridge results are polled with timeout evidence
- UI tree, screenshot, metadata copy, and draft QA report are written under the sandbox
- approved upgrade/detach workflows remain supervised prompt workflows

Phase 5 has an initial memory primitive:

- record a task journal as a reusable workflow template under the sandbox
- list recorded workflow templates
- dry-run replay planning that re-classifies each recorded step
- fresh workflow approval package generation that refuses stale recorded tokens and blocks unsafe parameter overrides
- parameter bindings for common payload fields, with `--parameters-json` overrides reclassified before any replay
- guarded replay with fresh observation before every step, stop-on-modal by default, and fresh approval tokens by step index
- recorded state predicates for document title/path, Revit version, active view, main-window identity, and modal dialog title/text/buttons when that context exists in the journal
- recorded workflows require fresh observation, safety classification, and approvals before any replay

Remaining Phase 5 work:

- learned/recorded dialog libraries beyond the built-in rules
- broader live replay validation across multiple real Revit UI workflows

## Current Status Versus North Star

This package is a validated foundation, not the complete north-star Revit operator. The current prototype can observe Revit, classify dialogs conservatively, expose CLI/HTTP/plugin/MCP command surfaces, inspect UIA action methods, execute guarded primitives, rehearse representative approval/blocking policies without execution, audit authorized live UI execution coverage, list and plan guarded common ribbon-tab actions, validate ribbon and context-menu descriptor policies without touching live UI, plan and dry-run context-menu opening and exact menu-item selection, report loaded add-in bridge status/readiness, write a safe bridge restart/reload validation handoff, run a read-only post-restart bridge validation chain, run a read-only north-star resume check after human-gated state changes, write a read-only north-star approval handoff and concise human gate packet for the next guarded live actions, scan stable north-star handoff artifacts for credential leaks and consistency drift, write per-blocker unblock-readiness packets, queue read-only add-in work, export live metadata, verify live model readiness with idle/non-modal active-document predicates, plan safe Project Browser/view navigation with OCR line/item-match evidence including RapidOCR bounds, produce approval-gated OCR-geometry visual-click plans for visible Project Browser rows, capture read-only Properties palette UIA/OCR evidence, plan, matrix-validate, smoke-run, and step-run named guarded UI workflow recipes, run live RapidOCR screenshot extraction, use OCR as an opt-in current-dialog fallback with modal-state gating, detect repeated busy/unknown supervision stalls with recovery evidence, audit accumulated live supervision time against an hours-long target, validate synthetic recovery recommendations and supervision endurance behavior, guard workflow replay with recorded state predicates, fresh approval packages, and parameter override reclassification, and run a supervised read-only QA workflow. Live execution coverage currently proves focus, Escape, and dialog-click surfaces only; it does not yet provide broadly validated direct Project Browser activation, approved live UIA/ribbon/context-menu method execution, broadly validated command-level ribbon/menu/context-menu workflow replay, robust live recovery drills against real stuck Revit states, or hours-long autonomous recovery across arbitrary Revit tasks.

The north-star completion audit is intentionally stricter than package completion. UI workflow coverage counts only approval-token-backed `approved_executed_steps`; smoke-safe observation/planning recipe steps do not close the approved workflow execution gap.

## Safety Constraints

Default safe project area:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion
```

Default sandbox:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT
```

Current test model:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt
```

R25 means Revit 2025. The prototype now infers `R25` filenames as Revit 2025 for `open-model`, while still reporting versions detected from Revit window/process text such as `Autodesk Revit 2025`.

Engineering outputs must be labeled:

```text
DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW
```
