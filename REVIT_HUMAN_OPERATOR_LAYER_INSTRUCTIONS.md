# Revit Human-Operator Layer Instructions

Build the first version of a "Revit Human-Operator Layer" for Hermes: a safe local automation system that lets an AI agent operate Autodesk Revit like a trained human user, not merely call SDK/MCP functions.

This is not just an MCP server.
This is not just a pyRevit script.
This is not just a metadata exporter.

The goal is to give Hermes a durable, general-purpose ability to solve future Revit tasks by combining:

1. Human-style UI operation
2. Revit API / SDK calls where available
3. Screen/window/dialog observation
4. Keyboard/mouse/ribbon/menu control
5. Prompt detection and escalation
6. Model/document state extraction
7. Safety policy enforcement
8. Long-running task supervision
9. Structured logs and reversible workflows

## Why This Is Necessary

Many important Revit operations are not fully available through the SDK, pyRevit, or MCP-style commands. Real Revit workflows often require interacting with native UI surfaces:

- upgrade dialogs
- detach / preserve worksets prompts
- worksharing prompts
- link reload dialogs
- family load options
- type catalog dialogs
- warning review dialogs
- failure processing dialogs
- print/export dialogs
- Manage Links
- Visibility/Graphics
- View Templates
- Project Browser interactions
- ribbon-only tools
- modal Autodesk/Revit UI
- add-in panels
- dialogs implemented outside the Revit API
- workflows where the SDK exposes partial data but not the actual user-facing action

A future Hermes that can help with Revit must therefore be able to operate the UI like a human while still using Revit API calls when they are safer, clearer, or more precise.

## North Star

Hermes should eventually be able to receive a task like:

> "Open the copied local model, inspect the structural drawings, find missing grid bubbles, export sheets, check warnings, reload links if safe, and produce a draft QA report."

And then:

- open or attach to Revit
- know which Revit version is needed
- see whether Revit is busy
- identify the active model
- read visible dialogs
- classify prompt risk
- ask the human before risky actions
- use the UI for operations unavailable through the SDK
- use the SDK for reliable model queries
- avoid save/sync/destructive operations
- log every action
- produce draft outputs in a sandbox
- recover when Revit gets stuck
- explain what happened

## Core Design Principle

The agent should behave like a cautious junior Revit operator sitting at the machine, supervised by a human engineer.

It should be able to:

- look at the Revit UI
- understand what window/dialog/tool is active
- choose a safe next action
- click/type/navigate when appropriate
- pause and ask when risk is high
- use API automation when possible
- refuse unsafe actions by default
- keep a complete audit trail

## Architecture Objective

Design and prototype a hybrid Revit operation layer with four cooperating parts:

## 1. Revit UI Operator

A Windows UI automation layer that can observe and interact with Revit's visible UI.

Capabilities:

- enumerate Revit windows
- detect active/main/modal windows
- read window titles
- read dialog text
- list buttons, checkboxes, combo boxes, tree views, tabs, grids, menus
- identify enabled/disabled controls
- take screenshots
- locate controls by accessible name/class/text
- click buttons only when allowed
- type text only when allowed
- send keyboard shortcuts
- navigate menus/ribbon where feasible
- report uncertainty instead of guessing

Possible technologies:

- pywinauto
- Microsoft UI Automation / UIA
- WinAppDriver if useful
- pyautogui only as lower-level fallback
- OCR/screenshot analysis where controls are inaccessible

## 2. Revit In-Process Sensor / Command Add-in

A lightweight Revit add-in that runs inside Revit and exposes safe model state and read-only commands.

Purpose:

- provide reliable document/model data that UI automation cannot safely infer
- execute API calls on Revit's API thread
- use ExternalEvent correctly
- expose read-only inspection commands
- eventually expose guarded write commands

Capabilities:

- status of active document
- document path/title/version
- worksharing state
- central path
- dirty/saved state
- open views
- selected elements
- warnings
- links/imports
- sheets/views/levels/grids
- families/types
- project information
- export structured metadata
- possibly expose safe command wrappers

Important:
This add-in is not the whole solution. It complements UI operation. Revit API access alone is insufficient.

## 3. Agent Control Server

A local process that presents a stable interface to Hermes/Codex.

It should coordinate:

- UI automation
- in-Revit add-in communication
- safety policy
- logs
- screenshots
- task state
- human approvals

Interface may be:

- local HTTP server
- named pipe
- CLI wrapper
- eventually MCP, but MCP is only the agent-facing protocol, not the core capability

Example commands:

- `revit-operator health`
- `revit-operator status`
- `revit-operator screenshot`
- `revit-operator ui-tree`
- `revit-operator list-windows`
- `revit-operator list-dialogs`
- `revit-operator classify-dialog`
- `revit-operator click --target ... --approval-token ...`
- `revit-operator press-key --key Escape`
- `revit-operator wait-until-idle`
- `revit-operator export-metadata`
- `revit-operator run-safe-command`
- `revit-operator task-log`

## 4. Safety Governor

A mandatory policy layer that decides what actions are allowed, blocked, or require human approval.

It must classify actions by risk.

Always allowed / low risk:

- observe windows
- read UI tree
- take screenshot
- query active document
- export read-only metadata to sandbox
- press Escape to close non-destructive context where safe
- click OK on known informational prompts, if explicitly configured

Approval required:

- upgrade model
- detach from central
- preserve/discard worksets
- reload links
- open worksets
- close model
- change active view
- modify selection
- run model-changing Revit command
- interact with unknown dialog
- click any button with ambiguous consequence

Blocked by default:

- Save
- Save As
- Synchronize with Central
- Relinquish
- Publish
- overwrite files
- write to LucidLink
- write to Autodesk Docs / cloud / central
- delete model elements
- accept destructive warnings
- run arbitrary macros/add-ins without approval
- modify production files

Every action must be logged with:

- timestamp
- active Revit process/window
- active document
- requested action
- observed UI state before action
- risk classification
- approval status
- result
- output files
- screenshot reference if useful

## Immediate Prototype Objective

Build the smallest useful version of this human-operator layer.

Minimum viable prototype should support:

### A. Attach and Observe

- Detect running Revit processes.
- Identify Revit version.
- Identify main window.
- Identify active/modal dialogs.
- Extract UI Automation tree for the active Revit window.
- Take screenshot.
- Report whether Revit appears idle, busy, modal, or unknown.

### B. Active Document Awareness

Through in-process add-in if feasible:

- active document title/path
- Revit document version
- worksharing state
- central path
- dirty state if available
- active view name/type

If add-in is not yet feasible, define the interface and stub it cleanly.

### C. Dialog Understanding

- List all visible Revit-related dialogs.
- Extract dialog title/text/buttons.
- Classify risk using explicit rules.
- Produce JSON like:

```json
{
  "has_modal_dialog": true,
  "dialog_title": "...",
  "dialog_text": "...",
  "buttons": ["OK", "Cancel", "Upgrade"],
  "risk": "high",
  "recommended_action": "ask_human",
  "reason": "Dialog appears to involve model upgrade"
}
```

### D. Human-Style Action Primitives

Implement cautious primitives, not task-specific hacks:

- focus Revit
- focus window/dialog
- click named button
- press key
- type text
- wait for window
- wait for dialog
- wait until idle
- get screenshot
- get UI tree
- verify expected state changed

All action primitives must:

- be dry-run capable
- require safety classification
- return structured result JSON
- include before/after observation when possible

### E. Safe Read-Only Model Export

If the Revit add-in is feasible:

- Export basic metadata from the active document into a sandbox path.
- Include:
  - project info
  - levels
  - grids
  - views
  - sheets
  - titleblocks
  - links
  - warnings
  - families/types
- Do not save/sync/modify the model.

### F. Task Journal

Every operation should write a task journal:

- JSONL log of observations/actions/results
- Markdown summary
- screenshots directory
- exported metadata directory

## Sandbox and Safety Constraints

Use the local copied model and sandbox only.

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
- Do not save/sync.
- Do not modify engineering model contents unless explicitly approved.
- Any engineering output must be labeled:
  `DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW`

## Aspirational Capabilities to Design Toward

The architecture should be extensible enough that future Hermes can:

### 1. Open and Prepare Models

- choose correct Revit version
- open copied local models
- detect and handle upgrade prompts
- detach safely when approved
- choose workset options
- detect missing links
- wait for model open completion
- verify active document

### 2. Navigate Revit Like a Human

- use Project Browser
- activate views/sheets
- zoom/pan if needed
- inspect properties palette
- use ribbon commands
- use context menus
- interact with common dialogs
- search/select elements
- use temporary hide/isolate where safe
- inspect warnings UI

### 3. Combine UI and API Intelligence

- use API for precise element/model queries
- use UI automation for features not exposed in API
- reconcile what the API says with what the user sees
- detect when Revit is in a command, modal state, or failure mode

### 4. Perform QA/QC Workflows

- inspect sheets
- check view templates
- find missing tags/dimensions/grids
- review warnings
- inspect links/imports
- check titleblock metadata
- compare sheets/views against standards
- generate draft issue reports

### 5. Execute Controlled Production Workflows

Future only, with explicit approvals:

- batch export PDFs/DWGs
- reload links
- update parameters
- place tags
- create views/sheets
- run add-in commands
- modify families
- clean warnings
- perform repetitive drafting work

### 6. Recover from Problems

- detect frozen Revit
- detect stuck dialogs
- capture screenshot and UI tree on failure
- back out safely with Escape/Cancel where approved
- ask human for intervention
- resume after human acts
- avoid repeating failed clicks blindly

### 7. Learn Reusable UI Workflows

- record successful UI action sequences
- parameterize them
- replay with verification
- store known dialog classifiers
- maintain a library of safe Revit UI skills

## Deliverables

Create a design and prototype package with:

1. `REVIT_HUMAN_OPERATOR_LAYER.md`
   A full architecture document explaining the hybrid UI/API approach.

2. `REVIT_OPERATOR_SAFETY_MODEL.md`
   Safety policy, risk classifications, blocked actions, approval-required actions, and logging requirements.

3. `REVIT_UI_AUTOMATION_PROTOTYPE.md`
   Design notes and implementation details for UI Automation / pywinauto / screenshot/OCR layer.

4. `REVIT_OPERATOR_RUNBOOK.md`
   Step-by-step instructions for:
   - opening copied local models
   - starting the operator layer
   - checking status
   - inspecting dialogs
   - approving safe actions
   - exporting metadata
   - reviewing logs
   - shutting down safely

5. `REVIT_OPERATOR_VALIDATION.md`
   Evidence that:
   - output writes are sandboxed
   - no save/sync calls are made
   - high-risk UI actions are blocked or require approval
   - Revit UI state is observable
   - dialogs are classified conservatively
   - all actions are logged

6. Prototype source code for:
   - UI/window observer
   - dialog lister/classifier
   - screenshot capture
   - safe action executor
   - local command interface
   - optional Revit add-in bridge
   - optional metadata exporter

## Preferred Implementation Strategy

Start with UI observation first, because that is the missing capability.

Phase 1:

- Build `revit-operator status`
- Build `revit-operator list-windows`
- Build `revit-operator list-dialogs`
- Build `revit-operator screenshot`
- Build `revit-operator ui-tree`
- Build risk classifier for dialogs
- Log everything

Phase 2:

- Add safe action primitives:
  - focus
  - press key
  - click named button
  - wait for state
- Require explicit approval token for anything beyond observation.

Phase 3:

- Add in-process Revit add-in bridge for precise model/document state.
- Expose read-only metadata export.

Phase 4:

- Compose higher-level workflows:
  - open local model
  - handle approved upgrade/detach prompt
  - wait for model ready
  - export QA metadata
  - generate draft report

Phase 5:

- Add reusable workflow memory:
  - known dialogs
  - known safe button semantics
  - known Revit version behaviors
  - standard recovery paths

## Key Design Warning

Do not over-index on MCP. MCP can be an excellent final protocol for Hermes to call the operator layer, but MCP does not solve the actual hard problem. The hard problem is robust, safe, observable operation of a complex Windows desktop application whose important workflows are often only available through UI.

MCP is the wire.
The operator layer is the brain, eyes, hands, and safety harness.

## Success Criteria

The work is successful if Hermes gains a foundation for solving future Revit tasks by:

- seeing Revit's actual UI state
- understanding when Revit is asking for a decision
- using the mouse/keyboard/ribbon/dialogs safely
- calling the Revit API where it is better than UI automation
- avoiding production writes by default
- escalating risky choices to the human
- recording everything it did
- recovering from unexpected UI states
- producing useful sandboxed outputs

## Ultimate Benchmark

A human should be able to leave Revit open on a copied local model, ask Hermes to perform a cautious Revit task, and Hermes should be able to work through the UI/API environment for hours with supervision checkpoints - not by pretending every Revit capability is exposed through MCP, but by operating the application itself like a careful human assistant.
