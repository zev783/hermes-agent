# Revit Operator Safety Model

The Revit human-operator layer is fail-closed by default. It may observe freely, but anything that changes Revit state, model state, worksharing state, files, links, cloud/central data, or active UI context must be explicitly approved and logged.

Implementation path: `tools/revit_operator/safety.py`

## Risk Levels

| Risk | Meaning | Default behavior |
| --- | --- | --- |
| `low` | Observation or read-only bridge operation | Allowed and logged |
| `medium` | Reserved for future verified workflows | Not used yet |
| `high` | Ambiguous UI/session action | Requires exact approval token |
| `critical` | Model-write-capable Revit operation | Requires exact approval plus operation guard flags |
| `blocked` | Generic destructive UI action | Refused |

## Always Allowed / Low Risk

Observation and read-only commands:

- `serve`
- `health`
- `north-star-status`
- `north-star-audit`
- `north-star-approval-plan`
- `north-star-stable-artifact-scan`
- `north-star-unblock-readiness`
- `north-star-watch`
- `north-star-resume-check`
- `north-star-human-gate-packet`
- `status`
- `list-processes`
- `list-revit-installs`
- `list-windows`
- `list-dialogs`
- `classify-dialog`
- `dialog-rule-library`
- `record-dialog-rule`
- `dialog-workflows`
- `dialog-workflow-matrix`
- `plan-dialog-response`
- `plan-current-dialog-response`
- `screenshot`
- `ocr-screenshot`
- `ocr-health`
- `ui-tree`
- `uia-tree`
- `uia-find-control`
- `uia-control-details`
- `uia-method-matrix`
- `find-control`
- `project-browser-snapshot`
- `project-browser-plan-navigation`
- `project-browser-plan-visual-activation`
- `project-browser-plan-activation`
- `properties-palette-snapshot`
- `find-view`
- `ribbon-actions`
- `ribbon-action-matrix`
- `plan-ribbon-action`
- `context-menu-actions`
- `context-menu-action-matrix`
- `context-menu-snapshot`
- `plan-context-menu-action`
- `plan-context-menu-item`
- `action-approval-matrix`
- `ui-execution-coverage-audit`
- `wait-for-window`
- `wait-for-dialog`
- `wait-until-idle`
- `wait-model-ready`
- `addin-security-preflight`
- `task-log`
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
- `ui-workflows`
- `ui-workflow-matrix`
- `ui-workflow-smoke-matrix`
- `plan-ui-workflow`
- `workflow-library`
- `record-workflow`
- `plan-workflow`
- `workflow-approval-plan`
- `export-metadata`
- `qa-report`
- `qa-workflow`

Read-only add-in bridge operations:

- `request-operation --operation active-document`
- `request-operation --operation export-metadata`
- `request-operation --operation qa-snapshot`

All allowed operations are still logged.

`action-approval-matrix` is an observation command even though it evaluates
high-risk primitives. It runs those primitives only in dry-run mode and
classifies representative bridge operations without queueing them, so it is
safe to use as a policy regression rehearsal.

`ui-execution-coverage-audit` is also an observation command. It scans existing
sandboxed journals for authorized executed UI actions, measures covered surfaces
such as focus, Escape, dialog click, UIA invoke, visual click, ribbon action,
context-menu action/item, and workflow-step execution, and reports missing
coverage without touching live Revit.

`uia-method-matrix` is an observation command. It classifies synthetic
`uia-invoke` payloads for every allowlisted UIA method, confirms exact approval
is required for non-destructive targets, confirms Save targets stay blocked,
and does not search, focus, click, or invoke live UI.

`supervision-endurance-matrix` is also an observation command. It runs the real
supervision loop against synthetic observers to validate resume, modal stop,
busy stall, and unknown stall behavior without touching live Revit or queueing
bridge operations.

`supervise-session` writes read-only checkpoints after each observation during
long runs and records the supervisor PID when available. The checkpoint file is
still sandboxed evidence only; it does not authorize UI actions or bridge
commands.

`supervision-endurance-audit` is read-only. It scans existing sandboxed
`supervision_log.json` files, excludes synthetic/test logs by default, requires
live main-window evidence unless explicitly relaxed, and reports whether an
hours-long target has actually been met. It merges overlapping qualifying
intervals before calculating `total_live_seconds` and preserves the unmerged sum
as `raw_total_live_seconds`. It reports active/stale in-progress supervisor PID
status where available. It does not poll, focus, click, type, or queue bridge
operations.

`bridge-restart-validation-plan` is read-only. It may report that a human
restart/reload is required, but it never closes, restarts, saves, syncs, reloads,
or modifies Revit. If the active copied model is dirty, the save/discard choice
belongs to the human supervisor only; the operator may write a no-save/no-sync
handoff checklist but must not click save-prompt buttons on its own.

`bridge-post-restart-validation` is read-only. It chains status, bridge status,
loaded-build verification, bridge readiness, add-in security preflight,
model-readiness checks, and a refreshed north-star audit after a human
restart/reload. It never focuses, clicks, types, invokes UIA, closes, restarts,
saves, syncs, reloads, detaches, upgrades, or modifies Revit.

`north-star-resume-check` is read-only. It refreshes north-star status and
approval artifacts, may run `bridge-post-restart-validation` when the bridge
restart gap remains and Revit is running, and refreshes the north-star audit. It
never focuses, clicks, types, invokes UIA, queues bridge writes, closes,
restarts, saves, syncs, reloads, detaches, upgrades, or modifies Revit.

`north-star-watch` is read-only. It polls Revit status, visible dialogs, and
bridge readiness, then refreshes the hard completion gate and unblock-readiness
artifacts. When explicitly requested, it can also rerun approval dry-run
preflight with expected Revit/title/view predicates before the hard gate. It may
publish stable current audit/gate/readiness/preflight files, and with an
explicit `--publish-current-handoff` flag it may republish the stable current
handoff bundle. It still has no authority to approve, execute, save, sync,
reload, restart, close, or modify Revit.

`north-star-human-gate-packet` is read-only. It writes a JSON and Markdown
handoff for the human supervisor with current manual gates, exact approval-token
commands, blocked effects, and the resume command to run after human action. It
does not approve or execute any UI/model action.

`north-star-stable-artifact-scan` is read-only. It scans sandbox-root
`NORTH_STAR_*CURRENT*` artifacts for stale approval credentials, executable
approval instructions, execution-authority flags, legacy tombstone redaction,
blocked-count consistency, and `blocked_gap_ids` drift from the hard completion
gate. When approval preflight is fresh, it also checks that existing
approval-facing handoff artifacts are at least as new as the stable preflight.
It validates that `NORTH_STAR_HANDOFF_CURRENT.json` references only existing
sandbox files in its `stable_files` map, and that referenced JSON files parse.
It writes scan JSON/Markdown under the sandbox and never touches Revit.

`north-star-completion-gate` is also read-only and is the only artifact that can
authorize `update_goal`. It directly applies the stable-handoff safety checks
above, including blocker-ID consistency, fresh-preflight handoff alignment, and
handoff file-reference integrity. Completion remains blocked unless this same
fresh gate reports both `completion_allowed: true` and
`may_call_update_goal: true`.

`north-star-unblock-readiness` is read-only. It converts the currently blocked
north-star gaps into per-blocker readiness packets that name current evidence,
safe next commands, required human or real-condition actions, and completion
evidence still needed. It recomputes the stable-handoff guard checks instead of
trusting only a prior scan artifact. It writes only sandbox JSON/Markdown,
exposes no approval token, and never grants execution or completion authority.

## Approval Required

The following require an exact-action approval token:

- `open-model`
- `install-addin`
- `trust-addin`
- approving `Always Load` on a verified Hermes unsigned-add-in startup prompt
- `ribbon-action`
- `context-menu-action`
- `context-menu-select-item`
- `project-browser-visual-activate`
- OCR-geometry `visual-click`
- focusing a Revit window
- clicking a named button
- typing text
- pressing non-Escape keys
- interacting with unknown dialogs
- detach/upgrade/workset prompt actions
- family/type catalog choices
- warning/failure dialogs
- print/export dialogs that may write files
- selection or active view changes
- opening a context menu on a visible UIA target
- clicking OCR-derived screen coordinates

Dry-run output includes:

```text
APPROVE:<digest>
```

The token binds approval to the exact payload that was reviewed. It is a human-supervision guardrail, not a cryptographic security boundary.

## Explicit Critical Operations

The operator can queue critical in-Revit operations for the add-in:

- `save`
- `sync` / `synchronize-with-central`
- `reload-links`
- `close-model`
- `set-project-info-parameter`
- `modify-model`

Critical operations require:

- `--execute`
- exact `--approval-token`
- `--allow-model-write` for model writes
- `--allow-sync` in addition to `--allow-model-write` for synchronization

Sync remains deliberately hard to trigger while testing older copied models. It requires a named sync operation, exact token, model-write guard, and sync-specific guard.

## Blocked By Default For Generic UI Actions

Generic UI clicks are blocked when their target text includes production-write or destructive terms:

- Save
- Save As
- Synchronize with Central
- Relinquish
- Publish
- overwrite files
- delete
- discard changes
- write to LucidLink
- write to Autodesk Docs / cloud / central
- central model writes

This prevents Hermes from casually clicking a dangerous visible button. Explicit named operations use the stricter critical-operation flow above.

## Dialog Classification

`classify-dialog` and `list-dialogs` use explicit title/text/button rules:

- `upgrade`, `detach`, `workset`, `central`, `reload`, `link`, `Manage Links`, `family`, `type catalog`, `Visibility/Graphics`, `View Template`, `warning`, `failure`, and export/output-path prompts classify as high risk and `ask_human`
- save-changes prompts classify as critical and `ask_human`
- `save`, `synchronize`, `relinquish`, `publish`, `overwrite`, `delete`, `Autodesk Docs`, and `LucidLink` classify as high risk and `ask_human`
- unknown dialogs are high risk and require a human
- informational dialogs may classify low risk, but automatic closing remains opt-in
- sandbox-learned rules can only be recorded as medium/high/critical and are classifiers only; they never authorize clicks or reduce a prompt to low risk

## Workflow Replay Safety

`run-ui-workflow` is a guarded recipe runner rather than a blanket action
approval. It renders a recipe, captures fresh status before every step, runs
low-risk observation/planning steps, stops on unexpected modal UI, and refuses
approval-gated steps unless the exact step-indexed approval token is supplied.
With `--execute`, only approved steps receive `--execute`; blocked policies,
manual placeholders, and missing tokens stop the recipe before action.

Recorded workflows are templates, not automatic scripts. Approval tokens are stripped at record time. Replay must re-observe Revit before each step, re-classify the requested action, and require fresh approval tokens for approval-gated steps. Parameterized workflow overrides are applied to copied step payloads before classification, so an override from `Cancel` to `Save` is blocked rather than inheriting the original step's risk. When the source journal contains the data, replay also checks recorded active document title/path, Revit version, active view, main-window identity, and modal dialog title/text/buttons before executing a step. A mismatch stops replay and can capture a recovery snapshot.

`workflow-approval-plan` writes a fresh approval package for a recorded workflow.
It regenerates exact approval tokens from the current replay payloads, reports
blocked steps, refuses stale recorded tokens, and never executes the replay.

`north-star-approval-plan` is observation-only. It writes a human handoff for
remaining approval-gated north-star validation actions and manual items, but it
does not focus Revit, click, type, invoke UIA, open context menus, queue bridge
commands, restart, save, sync, reload, close, detach, upgrade, or modify the
model.

## Sandboxing

Default writes are constrained to:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT
```

The selected sandbox must remain inside the known safe copied project area unless `--allow-sandbox-outside-safe-root` is supplied for tests/local development. Every output path is validated against the selected sandbox.

The Hermes plugin wrapper is stricter than the local development CLI: the
agent-facing `revit_operator` tool schema does not expose the
outside-safe-root override, and direct plugin payloads that include it through
structured args or raw `argv` are rejected unless
`HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests.

The MCP wrapper follows the same fail-closed rule. The public
`revit_operator_command` MCP tool signature does not expose the override, and
direct MCP payloads or raw `argv` attempts to include it are rejected unless
`HERMES_REVIT_OPERATOR_MCP_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests.

The HTTP control server also rejects payload-level outside-safe-root overrides
unless `HERMES_REVIT_OPERATOR_HTTP_ALLOW_EXTERNAL_SANDBOX=1` is set for local
tests. This applies to both JSON `allow_sandbox_outside_safe_root` and raw
`argv` payloads containing `--allow-sandbox-outside-safe-root`.

Model-opening defaults to the known safe copied project area. Use
`--allow-model-outside-safe-root` only for deliberate local development tests
through the direct local CLI. Agent-facing transports are stricter: the Hermes
plugin, MCP wrapper, and HTTP/control dispatcher reject that model-root override
from command args, raw `argv`, or nested request-operation JSON containing
`allow_model_outside_safe_root: true`.

## Required Log Fields

Every command writes a JSONL journal entry under:

```text
<sandbox>\revit_operator_runs\<task-id>\journal.jsonl
```

Entries include:

- timestamp
- task id
- command
- requested action
- observed UI state before action when available
- observed UI state after action when available
- risk classification
- approval status
- result status
- output file references when applicable

Each task also receives:

- `summary.md`
- `screenshots\`
- `metadata\`

The summary, metadata, and QA reports must include:

```text
DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW
```
