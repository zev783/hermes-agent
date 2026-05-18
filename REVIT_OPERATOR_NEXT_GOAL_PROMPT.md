# Revit Operator Next Goal Prompt

## Original Purpose To Preserve

Build Hermes into a safe local Revit human-operator layer: a system that can operate Autodesk Revit like a careful trained user sitting at the workstation, while also using the Revit API where it is safer and more precise.

This is not just an MCP server, not just a pyRevit script, and not just a metadata exporter. The core purpose is durable Revit task capability through:

- human-style UI observation and operation
- Revit API access through an in-process add-in
- screen, window, and dialog awareness
- keyboard, mouse, ribbon, menu, and modal-dialog control
- prompt detection and risk classification
- model/document state extraction
- safety policy enforcement
- long-running supervision
- structured logs, sandboxed outputs, and reversible workflows

Hermes should behave like a cautious junior Revit operator supervised by a human engineer. It must see Revit, understand when Revit is asking for a decision, use UI automation where the SDK is insufficient, use the API where the API is better, avoid production writes by default, and escalate risky choices.

## Current State

The first implementation produced useful scaffolding but did not reach the real operating milestone.

Implemented:

- documentation package for the Revit operator architecture, safety model, runbook, validation plan, and UI automation prototype
- `tools/revit_operator` Python package
- CLI commands for status, windows, dialogs, screenshots, UI tree, opening models, queueing operations, add-in install/trust, metadata export, QA report, and task logs
- safety policy with guarded write operations and blocked destructive defaults
- task journaling to JSONL and Markdown
- Revit 2025 add-in project
- local .NET 8 build path
- Revit 2025 `.addin` manifest installation
- signed/trusted add-in DLL to avoid the unsigned add-in startup popup
- launch path for Revit 2025 against the copied local R25 model
- focused pytest coverage for the Python operator layer

Live evidence:

- Revit 2025 launched against the copied local test model.
- The add-in loaded far enough to write `addin_status.json`.
- Revit was responding with a main window handle.

Not yet working:

- queued add-in commands are not being processed
- `active_document.json` is not being written
- `command_results.jsonl` is not being written
- live metadata export is not proven
- live QA report generation from Revit metadata is not proven
- the UI/window observer did not reliably report Revit windows even though the process had a main window handle
- save, sync, reload links, close, and modify operations exist only as guarded queued operations and are not validated end to end

## Introspection: Why The Previous Attempt Failed

The implementation failed to achieve the stated goal because it overvalued scaffold completion and undervalued live proof.

Specific failure causes:

- I treated architecture, CLI surface, safety rules, and code structure as progress toward operation before proving the minimum live control loop.
- I added higher-risk future operation paths, such as save, sync, reload, close, and modify, before proving the read-only bridge could process a single `active-document` command.
- I assumed the add-in `Idling` event handler shape was correct instead of validating that queued commands were processed immediately after startup.
- The add-in wrote startup status, which looked like success, but the actual command loop remained broken.
- I did not hold the work to a hard milestone: "queue active-document, receive command result, write active_document.json."
- The UI observer was accepted too early even though CLI output contradicted Windows process evidence.
- The unsigned add-in popup was handled, but the follow-up validation stopped at add-in startup instead of proving bridge command execution.
- The scope expanded from "observe and read safely" into "support future write operations" before the observation and read-only path were dependable.

The corrected approach is to make the live read-only loop non-negotiable before adding or claiming broader Revit capability.

## New Primary Goal

Make the Hermes Revit operator layer actually usable against a live Revit 2025 session by fixing the in-process add-in bridge, validating UI observation, and proving a safe read-only QA workflow on the copied local test model.

Do not claim the goal is complete until there is live evidence that Hermes can:

1. observe the Revit process/window
2. process a queued in-process add-in command
3. write active document state
4. export read-only metadata to the sandbox
5. generate a draft QA report from that metadata
6. log the full operation

## Safe Paths

Known safe local project area:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion
```

Safe sandbox:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT
```

Current test model:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt
```

Important:

- R25 means Revit 2025.
- Do not assume R25 means Revit 2027.
- Do not write to LucidLink.
- Do not write to Autodesk Docs.
- Do not write to any central model.
- Do not save or sync during this read-only validation goal.
- Do not detach, upgrade, reload links, close models, or modify model contents unless explicitly approved by the user.
- Any engineering output must be labeled `DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW`.

## Immediate Tasks

1. Fix the Revit add-in bridge command loop.
   - Investigate the `Idling` handler and `UIApplication` access.
   - Replace with or supplement using `ExternalEvent` if needed.
   - Prove `active-document` writes both `command_results.jsonl` and `active_document.json`.

2. Validate live read-only document state.
   - active document title
   - active document path
   - Revit version
   - worksharing state
   - central path if available
   - dirty state if available
   - active view name and type

3. Fix or validate UI observation.
   - detect running Revit process
   - identify main window handle and title
   - identify active or modal dialogs
   - capture screenshot
   - export UI Automation tree where available
   - reconcile CLI output with `Get-Process Revit` evidence

4. Prove safe metadata export.
   - export only to the sandbox
   - include project info, levels, grids, views, sheets, titleblocks, links, warnings, families, and types where feasible
   - do not save, sync, or modify the model

5. Generate a draft QA report.
   - use exported metadata
   - write Markdown to the sandbox
   - label output `DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW`

6. Update validation documentation with real evidence.
   - commands run
   - output paths
   - proof that outputs are sandboxed
   - proof that save/sync/model writes were not executed
   - remaining limitations

7. Keep tests passing.
   - run the focused Revit operator tests
   - add tests for the bridge loop and UI observer fixes where practical

## Success Criteria

The goal is successful only when the following are true:

- Revit 2025 opens the copied local model.
- The operator detects the running Revit process and main window.
- The in-process add-in bridge processes at least `active-document`.
- `active_document.json` is written in the sandbox bridge directory.
- `command_results.jsonl` records a successful command result.
- Read-only metadata is exported to the sandbox.
- A draft QA report is generated from the exported metadata.
- Task journal entries exist for observations and actions.
- Save, sync, reload, close, detach, upgrade, and model-changing operations remain blocked or approval-gated.
- No production, LucidLink, Autodesk Docs, or central model path is written.
- Focused automated tests pass.

## Hard Rule For The Next Agent

Do not broaden the scope until the live read-only bridge loop works.

The first proof must be:

```text
queue active-document -> Revit add-in processes command -> command_results.jsonl written -> active_document.json written
```

Only after that should the work move to metadata export, QA reports, or future write-capable workflows.
