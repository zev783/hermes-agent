# Revit Operator Runbook

This runbook describes how to use the first local Revit human-operator prototype safely.

Primary command:

```powershell
revit-operator <command>
```

From a source checkout before installation, use:

```powershell
python -m tools.revit_operator.cli <command>
```

## Safety Defaults

Use only the copied local model and sandbox.

Safe project:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion
```

Safe sandbox:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT
```

Test model:

```text
C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt
```

R25 means Revit 2025.

Do not write to LucidLink, Autodesk Docs, cloud, central, or production files by default. Save/sync/modify operations are available only as explicit named add-in operations with exact approval and guard flags.

Approved UI-only items from private approval material may be executed with
`--execute --allow-approved-ui` after a fresh dry-run/readiness check. This
relaxes the outer `I approve <item-id>` phrase only for UI workflow steps and
UIA candidate controls that already carry a fresh private approval token. It
does not apply to model-changing items, model-open prompts, Save, Sync,
Publish, reload links, detach/upgrade/workset prompts, destructive dialog
buttons, or unknown dialogs.

To rehearse the current approval gates without executing any UI or model action:

```powershell
revit-operator action-approval-matrix
```

Expected: `success: true`, `dry_run_only: true`, blocked Save cases, approval
tokens for high-risk representative actions, and `executed_count: 0`.

To list fresh approval material without exposing tokens, including UI-only
operator-consent commands when available:

```powershell
revit-operator agent-session-approval-readiness-queue
```

Expected: `approval_tokens_included: false`. UI-only rows may include
`approved_ui_execute_command` with `--allow-approved-ui`; model-change and
model-open prompt rows keep `approved_ui_execute_command: null` and still
require exact confirmation.

To inventory the untracked copied-project RVT examples that Hermes may use for
dry-run/open choreography:

```powershell
revit-operator list-safe-models
```

Expected: `read_only: true`. The command scans the known copied local project,
skips the sandbox by default, marks the current structural R25/Revit 2025 test
model, and emits `agent-model-open-choreography` dry-run argv only. It does not
open Revit, touch model files, save, sync, or export metadata.

Audit which authorized live UI surfaces have actually executed:

```powershell
revit-operator ui-execution-coverage-audit
```

Expected before the UI execution gap is closed: `status:
insufficient_evidence`. Current live evidence may cover safe startup dialog
clicks, focus, and Escape, while still missing approved UIA/ribbon/context-menu
and visual-click execution. A guarded workflow step counts toward execution
coverage only when `run-ui-workflow` reports token-backed
`approved_executed_steps`; smoke-safe observation and planning steps do not
close that gap.

## 1. Build and Install the Add-in

The add-in source is at:

```text
tools\revit_operator\addin\
```

Build for Revit 2025 after installing a .NET SDK:

```powershell
dotnet build .\tools\revit_operator\addin\HermesRevitOperator.csproj -c Release -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025"
```

If the machine has only .NET runtimes and no SDK, install a user-local .NET 8
SDK and use that `dotnet.exe` for the build. When Revit is already running and
has locked the previous DLL, build to a fresh Hermes-owned output folder and
install the manifest to that path for the next human restart/reload:

```powershell
$dotnet = "$env:LOCALAPPDATA\hermes\dotnet-sdk\dotnet.exe"
$out = ".\tools\revit_operator\addin\bin\Release\net8.0-windows-current"
& $dotnet build .\tools\revit_operator\addin\HermesRevitOperator.csproj -c Release -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025" -p:OutputPath="$out\" -p:AppendTargetFrameworkToOutputPath=false
```

Dry-run the manifest install:

```powershell
revit-operator install-addin --revit-version 2025
```

Then run the approved install command with the exact approval token from dry-run output. Restart Revit after installing the manifest.

If Revit shows an unsigned add-in security prompt, first verify that the manifest and DLL are the expected local Hermes operator add-in:

```powershell
revit-operator addin-security-preflight --revit-version 2025
revit-operator plan-ui-workflow --name unsigned-addin-startup-preflight
```

If the preflight verifies the expected local add-in, prefer signing and trusting the local add-in before restarting Revit:

```powershell
revit-operator trust-addin --assembly ".\tools\revit_operator\addin\bin\Release\net8.0-windows-current\HermesRevitOperator.dll"
```

Review the impact statement, then run the approved `--execute --approval-token ...` command. This creates/reuses a CurrentUser code-signing certificate, trusts it in CurrentUser Root and TrustedPublisher, and signs the Hermes add-in DLL. If a prompt is already open and the human chooses to unblock the current startup, `Always Load` remains an approval-gated `click --target "Always Load"` after preflight; otherwise restart Revit so it reloads the now-signed DLL.

The dialog classifier also treats "publisher could not be verified" add-in
prompts as unsigned/unverified startup prompts. If the prompt does not mention
the expected Hermes add-in, the operator plans no click and blocks `Always Load`,
`Load Once`, and `Do Not Load` until a human inspects the dialog.

## 2. Check Operator Health

```powershell
revit-operator health
revit-operator list-revit-installs
```

Expected:

- `supported: true` on native Windows
- optional dependency status for `pywinauto` and `PIL.ImageGrab`

Optional local HTTP control server:

```powershell
revit-operator serve --host 127.0.0.1 --port 8765
```

Use this only on loopback. It exposes:

- `GET /health`
- `GET /commands`
- `POST /command`

The `/commands` endpoint lists the CLI command surface and blocked server-mode
commands. The `/command` endpoint accepts either
`{"command":"status","args":[]}` or an explicit `{"argv":["status"]}` shape.
Routed commands still use the same sandbox validation, safety classification,
approval-token checks, and journals as the CLI. The server refuses recursive
`serve` requests.

Optional Hermes plugin tool:

```text
plugin: revit-operator
toolset: plugin_revit_operator
tool: revit_operator
```

The plugin is a wrapper over the same CLI dispatcher. It accepts `command`,
`args`, `sandbox`, and `task_id`, returns structured JSON, and blocks `serve`
inside tool calls so an agent cannot accidentally start a long-running server.
It still dry-runs actions by default and still requires exact approval tokens.

Optional MCP stdio wrapper:

```powershell
revit-operator-mcp
```

From a source checkout:

```powershell
python -m tools.revit_operator.mcp_server
```

MCP client configuration can point at either command. The wrapper exposes:

- `revit_operator_health`
- `revit_operator_commands`
- `revit_operator_command`

`revit_operator_command` accepts `command`, `args`, `sandbox`, and `task_id`
and delegates to the same control dispatcher as the CLI/HTTP/plugin surfaces.
It blocks long-running server commands such as `serve`; actions still dry-run
by default and still require exact approval tokens.

## 3. Check Revit Status

```powershell
revit-operator status
revit-operator north-star-status --sheet-number S2.0
revit-operator north-star-audit
revit-operator north-star-approval-plan --sheet-number S2.0
revit-operator north-star-approval-preflight --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-ready-approvals --sheet-number S2.0
revit-operator north-star-next-approval --sheet-number S2.0
revit-operator north-star-waiting-state --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-approval-phrase-verify --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet --phrase "I approve <item-id> with token APPROVE:<token>"
revit-operator north-star-approved-execution-preview --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet --phrase "I approve <item-id> with token APPROVE:<token>"
revit-operator north-star-approval-verify --sheet-number S2.0 --approval-token APPROVE:<token>
revit-operator north-star-watch --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet --refresh-approval-preflight --publish-current-handoff --checks 6 --poll 20
revit-operator north-star-resume-check --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-human-gate-packet --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-human-unblock-brief --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-agent-stop-status --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-blocked-ledger --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-refresh-sequence --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-stable-artifact-scan
revit-operator north-star-unblock-readiness
revit-operator north-star-completion-gate
revit-operator bridge-status
revit-operator bridge-readiness
revit-operator bridge-restart-validation-plan
revit-operator bridge-post-restart-validation --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator verify-bridge-build
```

Prefer `north-star-refresh-sequence` for dependent north-star artifact refreshes.
It runs current handoff, stable scan, hard gate, final stable scan, and final
hard gate as one read-only operation while preserving each child task journal.

If running the commands manually, run dependent north-star artifact commands
sequentially. Do not run
`north-star-current-handoff`, `north-star-stable-artifact-scan`, and
`north-star-completion-gate` in parallel: the stable scan compares sandbox-root
handoff files against the current hard gate, and parallel execution can create
a transient blocker-ID mismatch. The safe order is:

```powershell
revit-operator north-star-current-handoff --sheet-number S2.0 --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
revit-operator north-star-stable-artifact-scan
revit-operator north-star-completion-gate
revit-operator north-star-stable-artifact-scan
revit-operator north-star-completion-gate
```

If the hard gate reports `stable-blocker-id-mismatch`,
`stale-approval-credential-leak`, or another stable handoff safety violation,
follow the gate's repair action first, then rerun the sequence above. Never
treat the intermediate stable scan or status output as completion authority.

Review:

- `state`
- `revit_running`
- `processes`
- `main_window`
- `active_dialogs`
- `active_document`
- `bridge-status.addin_status.payload.addin`
- `bridge-readiness.ready_for_continuous_bridge`
- `bridge-readiness.requires_revit_restart_or_reload`
- `bridge-post-restart-validation.validation_passed`
- `verify-bridge-build.status`
- `north-star-status.completion_gate_required`
- `north-star-status.completion_gate_command`
- `north-star-resume-check.may_call_update_goal`
- `north-star-audit.north_star_complete`
- `north-star-audit.remaining_gaps`
- `north-star-audit.blocker_summary`
- `north-star-approval-preflight.preflight_passed_count`
- `north-star-approval-preflight.unsafe_preflight_count`
- `north-star-ready-approvals.ready_approval_count`
- `north-star-ready-approvals.withheld_approval_count`
- `north-star-next-approval.selected_item`
- `north-star-next-approval.may_execute_from_this_result`
- `north-star-waiting-state.status`
- `north-star-waiting-state.required_human_approval_phrase`
- `north-star-waiting-state.may_execute_from_this_result`
- `north-star-approval-phrase-verify.phrase_matches_waiting_state`
- `north-star-approval-phrase-verify.approval_validated_for_current_waiting_state`
- `north-star-approval-phrase-verify.may_execute_from_this_result`
- `north-star-approved-execution-preview.status`
- `north-star-approved-execution-preview.execute_command_preview`
- `north-star-approved-execution-preview.may_execute_from_this_result`
- `north-star-approval-verify.token_matches_current_approval_item`
- `north-star-completion-gate.completion_allowed`
- `north-star-completion-gate.may_call_update_goal`
- `north-star-stable-artifact-scan.violation_count`
- `north-star-stable-artifact-scan.handoff_reference_violation_count`
- `north-star-unblock-readiness.blocker_readiness`
- `north-star-unblock-readiness.may_execute_from_this_result`
- `north-star-blocked-ledger.entries`
- `north-star-current-handoff.stable_files`
- `north-star-current-handoff.stable_files.stable_artifact_scan`
- `north-star-current-handoff.stable_files.unblock_readiness`
- `north-star-current-handoff.autonomous_progress_available`
- `north-star-current-handoff.blocked_waiting_for_human_or_real_condition`

If `active_document.status` is `stub`, the in-process add-in bridge is not connected yet. UI observation still works.

`north-star-audit` writes a machine-readable completion checklist. It should
remain `north_star_complete: false` until the remaining gaps are live-verified
or explicitly removed from scope. Check `gap_evidence` to see which live
artifact currently proves or fails each gap; the audit reads bridge readiness,
supervision endurance, and UI execution coverage artifacts instead of relying
only on a static gap list. The JSON also exposes `remaining_gap_count`,
`unsatisfied_count`, `unverified_or_blocked_requirement_count`, and prompt
checklist total/satisfied/unsatisfied counts so reviewers can compare summary
counts against the hard completion gate without recalculating them from arrays.

`north-star-status` writes a compact read-only blocker handoff for day-to-day
status checks. It includes `remaining_gaps`, `approval_candidates`,
`manual_gates`, `completion_gate_required`, and `completion_gate_command`.
Treat `may_call_update_goal: false` as authoritative evidence that the active
goal is not complete, but never treat status alone as completion evidence. Run
`north-star-completion-gate` and require `completion_allowed: true` plus
`may_call_update_goal: true` from that fresh gate before marking the goal
complete.

When any stable current handoff artifact exposes an exact human approval phrase,
the same phrase context must also show the phrase expiry and
`approval_phrase_execution_authority: false`. The phrase is handoff data only:
Hermes must still rerun preflight, verify the exact human-supplied phrase,
preview the separate execution command, and satisfy the hard completion gate.

`north-star-approval-plan` writes a read-only human handoff for the remaining
approval-gated validation steps. It may include exact-token commands for a
planned safe ribbon tab selection, direct UIA tab selection, guarded workflow
activation, context-menu opening, and exact context-menu item selection, but it
executes none of them. Treat it as an approval packet, not a completion signal.
When fresh dry-run artifacts exist, each approval item includes a
`prevalidation` block showing whether the target currently resolves, whether a
workflow stopped at the approval gate, and which artifact provided the evidence.
Each approval item also includes `approval_freshness` with the token-bound
payload digest and source prevalidation artifact. Prevalidation is only a
snapshot; rerun the dry-run, `north-star-approval-preflight`, and
`north-star-approval-verify` immediately before executing any approved action.
When a latest preflight artifact exists, the approval-plan Markdown also shows
approval readiness and withholds human-facing execute lines for items not marked
ready. The JSON command payload remains available for dry-run/preflight tooling.
Context-menu item approval entries have strict preconditions: the context menu
must already be open and a fresh `plan-context-menu-item` plus
`context-menu-snapshot` must report exactly one enabled target.

`north-star-approval-preflight` runs the current approval plan's generated
dry-run commands after stripping execution and approval-token flags. It writes
`north_star_approval_preflight.json` and `.md`, plus stable sandbox-root copies
`NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` and
`NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md`. Use it immediately before asking a
human to approve a gated UI action. The preflight separates dry-run success from
approval readiness: items can be `ready_for_human_approval`,
`requires_ui_state_change`, `requires_prevalidation`, or blocked/failed. Do not
ask for approval tokens for items that are not ready. It does not approve or
execute any action.

`north-star-ready-approvals` writes a narrower read-only handoff containing
only the approval items that the latest preflight marks
`ready_for_human_approval`. It writes `north_star_ready_approvals.json` and
`.md`. Ready items include verify, dry-run, and execute-after-approval commands;
each ready item also includes a token verification summary, bound payload
digest, and `may_execute_from_this_summary: false` so the summary cannot be
mistaken for execution approval. Withheld items are listed separately with the
readiness reason and no execute command. Use this before asking the human for
approval so non-ready UI actions are not accidentally promoted.

`north-star-next-approval` writes a single-item read-only handoff for the next
safest currently ready approval candidate. It writes
`north_star_next_approval.json` and `.md`, and the current handoff publishes
stable sandbox-root copies at `NORTH_STAR_NEXT_APPROVAL_CURRENT.json` and
`NORTH_STAR_NEXT_APPROVAL_CURRENT.md`. It selects only one item, lists other
ready items as deferred, withholds deferred execute commands, and keeps both
`may_execute_from_this_result` and the selected item's
`may_execute_from_this_item` false. Use it to decide what to ask the human
about next; it is not authorization to execute.

`north-star-waiting-state` writes the smallest read-only pause/resume artifact
for the current north-star gate state. It refreshes the current handoff and
publishes `NORTH_STAR_WAITING_STATE_CURRENT.json` and
`NORTH_STAR_WAITING_STATE_CURRENT.md`. Use it when Hermes needs to know whether
autonomous progress is still available or whether it must wait for a human
approval/action or a real stuck/modal/busy/unknown Revit condition. It includes
the exact `required_human_approval_phrase` for the current single next approval
candidate, but both `may_execute_from_this_result` and
`may_execute_from_waiting_state` remain false.

`north-star-approval-phrase-verify` checks an exact supplied human approval
phrase against the freshly refreshed waiting-state phrase, then verifies the
embedded token against the current approval plan and latest preflight readiness.
It writes `north_star_approval_phrase_verify.json` and `.md`. Even when
`approval_validated_for_current_waiting_state` is true, the command remains
read-only; it is not execution authority and keeps `may_execute_from_this_result`
false.

`north-star-approved-execution-preview` is the next read-only guard after phrase
verification. It takes the same exact phrase, refreshes phrase verification and
the next-approval handoff, then shows the exact separate command that would be
eligible only when the phrase, token, latest preflight readiness, and selected
next item still match. It writes `north_star_approved_execution_preview.json`
and `.md`. A non-matching phrase withholds the command. A matching phrase still
does not execute anything; `may_execute_from_this_result` remains false.

`north-star-watch` is a read-only polling handoff for the waiting period after
the package is built. It observes Revit state, dialog count, bridge readiness,
and the compact north-star status. It stops early if the loaded bridge becomes
current after a human restart/reload, or if a real modal/busy/unknown/hung state
appears that needs recovery evidence. After polling, it refreshes the hard
`north-star-completion-gate`, publishes stable current audit/gate files, and
writes `north-star-unblock-readiness` so the watch result never relies on status
alone for completion authority. With `--refresh-approval-preflight`, it also
reruns the read-only approval dry-runs using the supplied expected Revit/title/view
context before the hard gate, keeping the human approval handoff fresh without
executing any action. With `--publish-current-handoff`, it also republishes the
stable `NORTH_STAR_HANDOFF_CURRENT.*` bundle after the optional preflight so the
human-facing packet, waiting state, next-human-action card, blocked ledger, and
completion gate stay aligned during a supervision loop. It refreshes that
handoff again after `north-star-unblock-readiness` writes stable blocker
packets, so a first-run watch handoff can link the newly created
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.*` safety artifacts before the final hard
gate runs. It does not focus, click, type, invoke UIA, restart, close, save,
sync, reload, detach, upgrade, or modify the model.

`north-star-resume-check` is the read-only command to run after a human-gated
state changes, such as after a human restarts/reloads Revit or after approved
live UI validation. It refreshes `north-star-status`, writes a new approval
plan, runs `bridge-post-restart-validation` when the bridge restart gap is still
open and Revit is running, refreshes `north-star-audit`, and writes
`north_star_resume_check.json`. It still does not focus, click, type, invoke
UIA, queue bridge writes, restart, close, save, sync, reload, detach, upgrade,
or modify the model.

`north-star-human-gate-packet` writes a concise JSON and Markdown packet for
the human supervisor. It extracts the current manual gates, exact approval-token
commands, token verification commands, token-bound payload digests, freshness
rules, blocked effects, and the post-human-gate resume command into
`north_star_human_gate_packet.json` and `north_star_human_gate_packet.md`. When
`NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json` exists, the packet also embeds the
latest approval-readiness status for each approval item and warns against
requesting or executing tokens for items that still need a UI state change or
fresh prevalidation. It is a handoff only; it does not approve or execute any
UI/model action.

`north-star-completion-gate` runs a fresh read-only audit and writes
`north_star_completion_gate.json`. Treat this as the final guard before marking
the goal complete. Do not call `update_goal` unless that same fresh artifact
reports both `completion_allowed: true` and `may_call_update_goal: true`.
The command also republishes `NORTH_STAR_COMPLETION_GATE_CURRENT.*` and
`NORTH_STAR_AUDIT_CURRENT.*` directly from the fresh run, so the stable current
files are not dependent on a later watch, resume-check, or handoff refresh.
The hard gate also applies the stable-handoff checks used by
`north-star-stable-artifact-scan`, so broken `NORTH_STAR_HANDOFF_CURRENT.json`
references, blocker-ID drift, stale approval-facing artifacts after fresh
preflight, or execution-authority drift block completion even if the audit
otherwise appears complete.
When blocked, the gate includes `blocked_gate_details` and `followup_actions`;
for approval-gated items, the follow-up freshness rule requires regenerating the
approval plan, running preflight, verifying each token, and not reusing stale
approval tokens.
The gate also includes `stable_artifact_hints` so the supervisor can open the
current human packet, audit checklist, approval plan/preflight, restart
checklist, next-approval handoff, resume script, and top-level handoff without
searching timestamped run directories.

`north-star-approval-verify` checks a supplied approval token against a fresh
approval plan and writes `north_star_approval_verify.json`. It is only a
read-only explanation of what the token currently matches. When the latest
approval preflight exists, it also reports whether the matched item is ready for
human approval now. It does not execute the matching command, and
`may_execute_from_this_result` remains false.

`north-star-blocked-ledger` writes one durable JSON entry for each unresolved
gate and a Markdown companion for human review, including current evidence,
approval items, manual completion step, approval-token verify commands,
dry-run/preflight commands, human-reviewed execute commands for the
approval-gated items, and recheck commands. When the latest approval preflight
marks an item as not ready, the ledger withholds its execute command and records
the readiness reason instead. It is read-only and is the quickest
artifact for a human to inspect before deciding what to unblock.

`north-star-current-handoff` refreshes the blocked ledger and completion gate,
then publishes stable current files at the sandbox root:
`NORTH_STAR_APPROVAL_PLAN_CURRENT.json`,
`NORTH_STAR_APPROVAL_PLAN_CURRENT.md`,
`NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.json`,
`NORTH_STAR_APPROVAL_PREFLIGHT_CURRENT.md`,
`NORTH_STAR_READY_APPROVALS_CURRENT.json`,
`NORTH_STAR_READY_APPROVALS_CURRENT.md`,
`NORTH_STAR_NEXT_APPROVAL_CURRENT.json`,
`NORTH_STAR_NEXT_APPROVAL_CURRENT.md`,
`NORTH_STAR_WAITING_STATE_CURRENT.json`,
`NORTH_STAR_WAITING_STATE_CURRENT.md`,
`NORTH_STAR_BLOCKED_LEDGER_CURRENT.json`,
`NORTH_STAR_BLOCKED_LEDGER_CURRENT.md`,
`NORTH_STAR_AUDIT_CURRENT.json`,
`NORTH_STAR_AUDIT_CURRENT.md`,
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` when a restart/reload
checklist is available,
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.json`,
`NORTH_STAR_HUMAN_GATE_PACKET_CURRENT.md`,
`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1`,
`NORTH_STAR_COMPLETION_GATE_CURRENT.json`,
`NORTH_STAR_COMPLETION_GATE_CURRENT.md`,
`NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` / `.md` when an existing stable
scan is present,
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` / `.md` when existing unblock
packets are present,
`NORTH_STAR_BLOCKED_HANDOFF_CURRENT.json` / `.md` as a deprecated redacted
legacy tombstone, and
`NORTH_STAR_HANDOFF_CURRENT.json` / `NORTH_STAR_HANDOFF_CURRENT.md`. Use these stable files for the latest
handoff instead of hunting through timestamped task directories. It is read-only
and does not approve or execute any UI/model action. The JSON and Markdown also
surface `autonomous_progress_available`,
`human_or_real_condition_required`, and
`blocked_waiting_for_human_or_real_condition` so a supervisor can tell when
Hermes should stop spinning and wait for explicit human approval/action or a
real recovery condition. The `waiting_state` object also carries
`required_human_approval_phrase` for the single next approval candidate, but
`may_execute_from_waiting_state` remains false; execution still requires a fresh
token verification and explicit human approval.

`north-star-stable-artifact-scan` reads the sandbox-root
`NORTH_STAR_*CURRENT*` files and writes
`NORTH_STAR_STABLE_ARTIFACT_SCAN_CURRENT.json` / `.md`. It checks for stale
approval credentials, executable approval instructions, raw stale approval
execution flags such as `--execute`, `--approval-token`, and
`--approval-tokens-json`, execution-authority flags across every sandbox-root
`NORTH_STAR_*CURRENT*.json` file, including
any future `may_execute*` JSON key unless it is explicitly `false` or `null`,
legacy tombstone redaction, blocker count consistency, `blocked_gap_ids`
drift from the hard completion gate, fresh-preflight handoff alignment, and
`NORTH_STAR_HANDOFF_CURRENT.json` `stable_files` reference integrity. It also
validates the `NORTH_STAR_UNBLOCK_READINESS_CURRENT.json`
`safe_supervision_refresh_command` / PowerShell handoff so the command stays a
read-only, context-matched `north-star-watch` refresh and never gains execution
or approval-token flags. When approval preflight is fresh, the scan also treats
the fixed approval-facing handoff list and future sandbox-root
`NORTH_STAR_*CURRENT*` files as preflight-aligned artifacts unless they are
known credential-free/non-approval diagnostics such as status, audit,
stable-scan output, legacy tombstones, restart checklists, or post-human resume
scripts. Those approval-facing artifacts must be at least as new as the current
preflight. It also enforces approval-phrase metadata: every stable artifact that
exposes an exact approval phrase must carry expiry metadata and explicitly deny
execution authority. The scan also verifies
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.*` mirrors the hard completion-gate stop
boundary, so a stale stop-status file cannot claim autonomous progress or
completion authority when the hard gate is still blocked. It also verifies that
`NORTH_STAR_BRIDGE_RESTART_NO_SAVE_CHECKLIST_CURRENT.md` is fresh relative to
the latest bridge restart validation plan and source no-save checklist whenever
the next human action is a bridge restart/reload. It is a diagnostic safety scan
only;
`violation_count: 0`, `consistency_violation_count: 0`,
`preflight_alignment_violation_count: 0`, `handoff_reference_violation_count: 0`,
`unblock_refresh_command_violation_count: 0`, and
`approval_phrase_metadata_violation_count: 0` are useful evidence that the
handoff surface is clean, not completion authority.

`north-star-unblock-readiness` reads the current stable handoff artifacts plus
the latest gap evidence and writes
`NORTH_STAR_UNBLOCK_READINESS_CURRENT.json` / `.md`. Each unresolved blocker gets
a packet with current evidence presence, source artifacts, required human or
real-condition action, safe next commands, and the exact completion evidence
needed. It also recomputes stable-handoff guard checks and reports
`stable_handoff_guard_clean`, `stable_handoff_guard_violation_count`, and
`stable_handoff_guard_violation_ids` in `artifact_readiness`. It also includes
`safe_supervision_refresh_command` and `safe_supervision_refresh_powershell`,
which are read-only `north-star-watch --refresh-approval-preflight
--publish-current-handoff --checks 1 --poll 0` refresh lines carrying the latest
expected Revit/title/path/view predicates. These refresh lines must not include
`--execute`, `--approval-token`, or `--approval-tokens-json`. It is diagnostic
only and always keeps `completion_allowed: false`, `may_call_update_goal:
false`, and `may_execute_from_this_result: false`.

`NORTH_STAR_POST_HUMAN_RESUME_CHECK_CURRENT.ps1` is generated for the human
supervisor to run after completing a safe restart/reload or approved validation
step. It invokes the repo-local CLI through `python -m tools.revit_operator.cli`
with the sandbox and task id already supplied, then runs only the read-only
`north-star-resume-check` followed by `north-star-refresh-sequence`. The resume
check writes a fresh `north-star-completion-gate` result and republishes
`NORTH_STAR_AUDIT_CURRENT.*` and `NORTH_STAR_COMPLETION_GATE_CURRENT.*`; the
sequential refresh then reruns current handoff, stable scan, hard gate, final
stable scan, and final hard gate in order. The script parses the returned JSON
and prints an explicit `NORTH STAR STILL BLOCKED: do not call update_goal`
warning unless the final refresh result reports `completion_allowed: true`,
`may_call_update_goal: true`, and `audit_completion_authorized: true`; a
successful script invocation by itself is not completion evidence.

`north-star-human-unblock-brief` writes
`NORTH_STAR_HUMAN_UNBLOCK_BRIEF_CURRENT.json` / `.md`. This is the safest
artifact to hand to a human when the hard gate is waiting on external action:
it lists the current human/real-condition options, restart checklist path, and
post-human resume script path, but deliberately omits exact approval phrases,
approval tokens, and executable UI commands. Use the source next-human-action
artifact only when the human is intentionally supplying approval material in the
active conversation.

`north-star-agent-stop-status` writes
`NORTH_STAR_AGENT_STOP_STATUS_CURRENT.json` / `.md`. This is the
machine-readable stop/continue artifact for Hermes itself. When it reports
`should_stop_agent: true`, `recommended_agent_action:
wait_for_human_or_real_condition`, and the hard gate still reports no
completion authority, Hermes must stop autonomous attempts and wait for a human
or real Revit condition. The artifact includes credential-free
`human_unblock_paths` and `sanitized_options` so Hermes can point the human to
the stable human-unblock brief, restart/no-save checklist, and post-human resume
script without exposing approval phrases, approval tokens, or executable UI
commands. The artifact is read-only, credential-free, and never grants
execution authority.

The Hermes plugin tool `revit_operator` uses the same CLI dispatcher, but its
agent-facing schema does not expose the test-only outside-safe-root sandbox
override. Direct plugin calls that try to pass that override through structured
args or raw `argv` fail closed unless
`HERMES_REVIT_OPERATOR_PLUGIN_ALLOW_EXTERNAL_SANDBOX=1` is deliberately set for
local tests. Do not set that environment variable for normal Revit work.

The MCP tool `revit_operator_command` follows the same rule. Its public tool
signature does not expose the outside-safe-root override, and raw `argv`
attempts to include `--allow-sandbox-outside-safe-root` fail closed unless
`HERMES_REVIT_OPERATOR_MCP_ALLOW_EXTERNAL_SANDBOX=1` is set for local tests.
Do not set that environment variable for normal Revit work.

The HTTP `/command` surface also fails closed for the outside-safe-root
override. JSON payloads that set `allow_sandbox_outside_safe_root` or raw `argv`
payloads containing `--allow-sandbox-outside-safe-root` are rejected unless
`HERMES_REVIT_OPERATOR_HTTP_ALLOW_EXTERNAL_SANDBOX=1` is deliberately set for
local tests. Do not set that environment variable for normal Revit work.

Model opening has a separate safe-root guard. The direct local CLI retains
`--allow-model-outside-safe-root` for deliberate development tests, but
agent-facing plugin, MCP, and HTTP/control-dispatcher calls reject that override
from command args, raw `argv`, or nested request-operation JSON. Normal Hermes
Revit work must use copied local models under the known safe project area.

Every `north-star-audit.gap_evidence` item also includes a `blocker` object.
Use it to distinguish implementation work from gates Hermes cannot clear alone:
human restart/reload, exact approval tokens, real stuck-state occurrence, or
elapsed supervision time.

Use `north-star-audit.blocker_summary` for the quick answer. If
`completion_blocked` is true, the goal is still not complete; the summary lists
which blocker classes remain and how many gaps are cleared.

Use `north-star-audit.completion_actions` to split what can still progress
autonomously from what requires human approval or a real Revit condition. Do not
mark the goal complete from the audit alone; run `north-star-completion-gate`
and require `completion_allowed: true` plus `may_call_update_goal: true` in that
fresh gate.

`supervision-endurance-audit` is read-only. It scans sandbox logs and does not
poll or touch Revit. For a running supervisor with a confirmed live PID, it may
extend the latest in-progress interval to the audit timestamp, but only inside
the active checkpoint grace window; stale or PID-less checkpoints do not inflate
the elapsed-time evidence. Use `duration_remaining_seconds`,
`check_count_remaining`, and `estimated_duration_target_at` to decide when to
rerun the audit.

For the live recovery-drill gap, run `recovery-snapshot` only when Revit is
actually modal, busy, unknown, hung, or otherwise stuck. The audit excludes idle
snapshots and synthetic/matrix recovery artifacts, so do not treat a normal
read-only recovery snapshot as completion evidence.

After rebuilding/reinstalling the add-in, `bridge-status` should report:

- `source_capability_stamp: continuous-idling-status-file-retry-v2`
- `supports_continuous_idling: true`
- `uses_idling_set_raise_without_delay: true`
- the loaded `assembly_path`
- the loaded `assembly_last_write_utc`

`bridge-readiness` checks the expected manifest, DLL, loaded bridge payload,
and restart/reload gate in one read-only audit. If it returns
`requires_revit_restart_or_reload: true`, the DLL and manifest are ready but the
running Revit session still loaded an old payload; ask the human to restart or
reload Revit when safe, and do not save, sync, close, or restart through Hermes.

`verify-bridge-build` wraps the loaded-payload checks in one read-only command. It should return `status: current` before Hermes relies on continuous bridge polling. If it returns `stale_or_unverified`, Revit is still running an older DLL or an unverified payload and must be restarted/reloaded before closing the bridge-validation gap.

If `bridge-readiness` shows the installed manifest/DLL are ready but the running
payload is stale, write the human handoff checklist:

```powershell
revit-operator bridge-restart-validation-plan --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
```

Hermes must not close, restart, save, sync, reload, detach, or upgrade Revit.
If the live copied model is dirty, the human must make the no-save/no-sync
decision manually; Hermes must not answer a save-changes prompt. The
`bridge-restart-validation-plan` output includes `no_save_checklist_path`, which
points to a generated Markdown checklist in the task run directory:

```text
<sandbox>\revit_operator_runs\<task-id>\bridge_restart_no_save_checklist.md
```

For the current live sandbox, a convenience copy is also written to:

```text
<sandbox>\REVIT_RESTART_RELOAD_NO_SAVE_CHECKLIST.md
```

After the human restarts or reloads Revit safely, run the plan's
post-restart validation commands before relying on continuous bridge polling.

For the post-human-restart check, use the one-shot read-only validator:

```powershell
revit-operator bridge-post-restart-validation --revit-version 2025 --expected-title-contains "24522 St John XXIII" --expected-view-name "STARTING VIEW" --expected-view-type DrawingSheet
```

It runs status, bridge status, loaded-build verification, bridge readiness,
add-in security preflight, model readiness, and a refreshed north-star audit in
one journaled command. It should return `validation_passed: true` only after
the running Revit session has loaded the current signed bridge. Before the
human restart/reload, it should fail safely on `loaded_build_current` and
`bridge_readiness_ready` without focusing, clicking, typing, closing,
restarting, saving, syncing, reloading, detaching, upgrading, or modifying the
model.

## 4. Open the Copied Local Model

Dry-run first:

```powershell
revit-operator open-model --model "C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt"
```

Review:

- inferred Revit version; `R25` should infer `2025`
- Revit executable path
- expected upgrade/detach/workset prompts
- approval token

Execute only after review:

```powershell
revit-operator open-model --model "<copied-local-model.rvt>" --execute --approval-token APPROVE:<digest>
```

If Revit shows upgrade, detach, workset, worksharing/central, link, warning, failure, save-changes, print, or export prompts, inspect them with the operator before clicking anything.

If Revit is already running with the add-in loaded, the add-in can open the model on Revit's API thread:

```powershell
revit-operator request-operation --operation open-model --args-json "{\"path\":\"<copied-local-model.rvt>\",\"detach\":true}" --execute --approval-token APPROVE:<digest>
```

## 5. Inspect Windows and Dialogs

```powershell
revit-operator list-windows
revit-operator list-processes
revit-operator list-dialogs
```

Use `list-dialogs` before interacting with any Revit prompt. Unknown dialogs are treated as high risk.

List reusable known dialog rules:

```powershell
revit-operator known-dialogs
```

List built-in and sandbox-learned dialog rules:

```powershell
revit-operator dialog-rule-library
```

List conservative dialog response playbooks:

```powershell
revit-operator dialog-workflows
```

Validate all built-in dialog playbooks against representative prompts:

```powershell
revit-operator dialog-workflow-matrix
```

Plan a known dialog response:

```powershell
revit-operator plan-dialog-response --title "Unresolved References" --button "Manage Links" --button "Ignore and continue opening the project"
```

Plan a response for the currently visible Revit dialog without manually
transcribing it:

```powershell
revit-operator plan-current-dialog-response
```

If the dialog text is inaccessible, use the opt-in OCR fallback:

```powershell
revit-operator plan-current-dialog-response --use-ocr --ocr-backend rapidocr
```

OCR planning is still read-only. OCR text is classified as a prompt only when
fresh Revit status is modal or active dialogs are present; when Revit is idle,
the OCR artifact is saved as evidence but no dialog plan is produced.

The response planner may suggest a `click` dry-run for a known button, but
execution still requires the exact approval token from that click dry-run.
Upgrade/detach/workset, worksharing/central, missing-link, warning/failure,
save-changes, print/export, and other destructive prompts remain human-only.
Known human-only playbooks include safe preflight commands, blocked button
labels, and approval conditions so Hermes can collect evidence and escalate
without guessing.

Record a conservative learned dialog rule after a supervised run:

```powershell
revit-operator record-dialog-rule --rule-id custom-link-warning --title-term "Custom Link Warning" --button-term "Review" --risk high --recommended-action ask_human_review_without_reload --reason "Custom link prompt requires supervised review."
```

Learned rules are classifiers only. They help Hermes recognize a prompt and escalate consistently; they do not approve clicks or lower risk below medium.

Manual classification:

```powershell
revit-operator classify-dialog --title "Upgrade model" --text "This model was saved in an earlier version." --button Cancel --button Upgrade
```

## 6. Capture Evidence

Screenshot:

```powershell
revit-operator screenshot
```

OCR fallback:

```powershell
revit-operator ocr-health
python -m pip install ".[revit-ocr]"
revit-operator ocr-screenshot --hwnd <main-window-hwnd> --backend auto
```

`ocr-health` reports both OCR backends. The `tesseract` backend requires Pillow, pytesseract, and a local Tesseract OCR executable. The `rapidocr` backend uses the Python package backend from the `revit-ocr` extra and does not need a separate Tesseract executable. If dependencies are missing, `ocr-screenshot` still writes an evidence artifact and screenshot path. Set `HERMES_TESSERACT_CMD` if `tesseract.exe` is installed but not on `PATH`.

UI tree:

```powershell
revit-operator ui-tree
```

UI Automation tree, when `pywinauto` is installed:

```powershell
python -m pip install ".[revit]"
revit-operator uia-tree --hwnd <main-window-hwnd> --max-depth 4 --limit 200
```

Find a semantic UIA control:

```powershell
revit-operator uia-find-control --hwnd <main-window-hwnd> --automation-id "ID_Save_RibbonItemControl" --max-depth 4 --limit 20
```

Inspect supported UIA action methods for an exact target:

```powershell
revit-operator uia-control-details --hwnd <main-window-hwnd> --name "S2.0" --exact --max-depth 8 --limit 20
```

Validate UIA method policy without touching live UI:

```powershell
revit-operator uia-method-matrix
```

Dry-run a UIA invoke:

```powershell
revit-operator uia-invoke --hwnd <main-window-hwnd> --automation-id "View" --max-depth 4 --limit 20
```

When executing after approval, the `--method` flag can pin a supported UIA
method such as `invoke`, `select`, `expand`, `toggle`, `click_input`, or
`double_click_input`. `right_click_input` is available for guarded context-menu
opening only. The default `auto` method tries conservative semantic
methods first and still runs under the same approval token gate.

List named guarded ribbon/menu descriptors:

```powershell
revit-operator ribbon-actions
```

Validate the descriptor table without touching live Revit UI:

```powershell
revit-operator ribbon-action-matrix
```

Plan a named ribbon/menu action before any invocation:

```powershell
revit-operator plan-ribbon-action --name view-tab --max-depth 5 --limit 20
```

Dry-run a named ribbon action:

```powershell
revit-operator ribbon-action --name view-tab
```

Execute only after human approval with the exact token from dry-run output:

```powershell
revit-operator ribbon-action --name view-tab --execute --approval-token APPROVE:<digest>
```

Blocked targets such as Save and Synchronize have no execution path:

```powershell
revit-operator ribbon-action --name save
```

List guarded context-menu descriptors:

```powershell
revit-operator context-menu-actions
```

Validate context-menu descriptors and representative item policies without
touching the live UI:

```powershell
revit-operator context-menu-action-matrix
```

After a context menu is open, capture read-only menu evidence:

```powershell
revit-operator context-menu-snapshot --max-depth 4 --limit 100
```

This writes `context_menu_snapshot.json` and lists visible `Menu` and
`MenuItem` controls when UIA exposes them. It does not select an item.

Plan opening a context menu for one exact UIA target:

```powershell
revit-operator plan-context-menu-action --name project-browser-item-menu --target-name "S2.0"
```

Dry-run context-menu opening:

```powershell
revit-operator context-menu-action --name project-browser-item-menu --target-name "S2.0"
```

Execute only after human approval with the exact token from dry-run output:

```powershell
revit-operator context-menu-action --name project-browser-item-menu --target-name "S2.0" --execute --approval-token APPROVE:<digest>
```

This only opens the context menu through `right_click_input`. It does not choose
any menu item. After the menu opens, run fresh observation such as `status`,
`list-dialogs`, and `uia-tree` before planning or approving any selection.

Plan one exact context-menu item after reviewing the snapshot:

```powershell
revit-operator plan-context-menu-item --item "Properties"
```

Dry-run item selection:

```powershell
revit-operator context-menu-select-item --item "Properties"
```

Execute only after reviewing the fresh snapshot and exact approval token:

```powershell
revit-operator context-menu-select-item --item "Properties" --execute --approval-token APPROVE:<digest>
```

Dangerous item names such as Save, Sync, Delete, Publish, or overwrite remain
blocked by policy.

Find a visible control:

```powershell
revit-operator find-control --text "Project Browser" --max-depth 8 --limit 20
```

Capture read-only Project Browser evidence:

```powershell
revit-operator project-browser-snapshot --search-depth 8 --tree-depth 4
revit-operator project-browser-snapshot --search-depth 8 --tree-depth 4 --include-uia --include-ocr --ocr-backend rapidocr
```

Plan Project Browser/view navigation without changing Revit state:

```powershell
revit-operator project-browser-plan-navigation --sheet-number S101
revit-operator project-browser-plan-navigation --sheet-number S101 --include-uia --include-ocr --ocr-backend rapidocr
```

This captures Project Browser evidence, optionally includes UIA/OCR evidence,
searches metadata, and recommends the guarded
`request-operation --operation activate-view` route only when exactly one
non-placeholder view/sheet match exists. It does not click the Project Browser,
change selection, or activate a view.

When OCR is enabled, review `visual_evidence.ocr_matches`. These are visible
text matches for human inspection only; RapidOCR matches may include confidence,
polygon boxes, and computed bounds. They are not coordinate-click targets.

Plan an OCR-geometry visual fallback click without changing Revit state:

```powershell
revit-operator project-browser-plan-visual-activation --sheet-number S2.0 --ocr-backend rapidocr --include-uia
```

The plan writes `project_browser_visual_activation_plan.json` and returns a
`visual-click` approval token only if exactly one OCR item match has bounds.
The dry-run executor form still does not click:

```powershell
revit-operator project-browser-visual-activate --sheet-number S2.0 --ocr-backend rapidocr --include-uia
```

Execution requires `--execute --approval-token APPROVE:<digest>` and should be
reserved for supervised fallback cases where metadata-backed `activate-view`
and UIA item activation are not usable.

Plan direct Project Browser UIA item activation:

```powershell
revit-operator project-browser-plan-activation --name "S2.0"
```

Execute direct activation only when the plan resolves exactly one visible
enabled UIA target and the human supplies the exact approval token from the
dry-run:

```powershell
revit-operator project-browser-activate-item --name "S2.0" --execute --approval-token APPROVE:<digest>
```

If Project Browser rows are not exposed through UIA, the command remains
non-executable and recommends the metadata-backed `project-browser-plan-navigation`
route.

Capture read-only Properties palette evidence:

```powershell
revit-operator properties-palette-snapshot --include-uia --include-ocr --ocr-backend rapidocr
```

This locates the visible Properties palette and captures its UI tree,
screenshot, optional UIA tree, and optional OCR evidence. It is observation
only: it does not focus fields, type values, click Apply, change selection, or
modify the model. Review `ocr_lines` / `ocr_items` for visible property names
and values such as sheet number, sheet name, scale, or Visibility/Graphics.

Find sheets/views from the latest bridge metadata before any navigation:

```powershell
revit-operator find-view --sheet-number S101
revit-operator find-view --query "framing" --view-type FloorPlan
```

When exactly one non-placeholder match is found, the output includes an
`activation` hint for a later approval-gated `activate-view` request. This is
metadata lookup only; it does not change the active Revit view.

Outputs are written under:

```text
<sandbox>\revit_operator_runs\<task-id>\
```

## 7. Approve Safe Actions

Actions dry-run by default:

```powershell
revit-operator click --target Cancel
```

Review the JSON:

- `policy.risk`
- `policy.decision`
- `policy.approval_token`
- `before`
- `next_step`

Only if the human approves the exact action, run:

```powershell
revit-operator click --target Cancel --execute --approval-token APPROVE:<digest>
```

Escape is the only low-risk key primitive:

```powershell
revit-operator press-key --key Escape --execute
```

Generic clicks on save/sync/publish/delete/overwrite remain blocked. Use explicit `request-operation` commands for approved model operations.

## 8. Request Add-in Operations

Read active document status through the add-in:

```powershell
revit-operator request-operation --operation active-document
```

Export metadata through the add-in:

```powershell
revit-operator request-operation --operation export-metadata
```

For the narrow read-only bridge allowlist, the `run-safe-command` wrapper is a
safer agent-facing entry point. It accepts only `active-document`,
`export-metadata`, and `qa-snapshot`; unsupported names such as `save` are
blocked before they can delegate to the bridge queue.

```powershell
revit-operator run-safe-command --name active-document
revit-operator run-safe-command --name export-metadata
revit-operator run-safe-command --name qa-snapshot --args-json '{"sheet_number":"S2.0"}'
```

Change the active view only after a metadata lookup and explicit approval:

```powershell
revit-operator request-operation --operation activate-view --sheet-number S101
revit-operator request-operation --operation activate-view --sheet-number S101 --execute --approval-token APPROVE:<digest>
```

Activating a view changes Revit session state, so it is critical-risk and
approval-required. It does not require `--allow-model-write` because it should
not modify model contents.

Dry-run a save request:

```powershell
revit-operator request-operation --operation save --allow-model-write
```

Execute only after review:

```powershell
revit-operator request-operation --operation save --allow-model-write --execute --approval-token APPROVE:<digest>
```

Sync requires an extra guard:

```powershell
revit-operator request-operation --operation sync --allow-model-write --allow-sync --execute --approval-token APPROVE:<digest>
```

Use sync only on deliberately selected copied/local test workflows until it is fully validated.

Modify a project information parameter:

```powershell
revit-operator request-operation --operation set-project-info-parameter --name "Project Status" --value "QA Draft" --allow-model-write
```

Reload Revit links:

```powershell
revit-operator request-operation --operation reload-links --allow-model-write
```

Close the active model without saving:

```powershell
revit-operator request-operation --operation close-model
```

## 9. Inspect Bridge Results

Read loaded add-in status and heartbeat metadata:

```powershell
revit-operator bridge-status
```

The add-in writes command results to:

```text
<sandbox>\bridge\command_results.jsonl
```

List recent bridge results:

```powershell
revit-operator bridge-results --limit 10
```

Wait for a specific queued command result:

```powershell
revit-operator wait-bridge-result --command-id active_document-20260512T190722Z-13d9196d --timeout 60 --poll 1
```

These commands are read-only and are useful for supervising long-running add-in work.

## 10. Wait for Idle

```powershell
revit-operator wait-until-idle --timeout 120 --poll 2
```

Wait until Revit is ready for supervised model work:

```powershell
revit-operator wait-model-ready --timeout 120 --poll 2 --expected-title-contains "24522 St John XXIII" --expected-revit-version 2025
```

This waits for idle state, no active/modal dialogs, a bridge active-document
payload, and any supplied document/view predicates. It writes
`model_ready_status.json` and does not dismiss prompts, activate views, save, or
sync.

Wait for a specific window or dialog:

```powershell
revit-operator wait-for-window --title-contains "Autodesk Revit" --timeout 60
revit-operator wait-for-dialog --title-contains "Upgrade" --timeout 60
```

If the state remains `modal`, inspect dialogs. If it remains `busy` or `unknown`, capture a screenshot and UI tree before taking further action.

Capture a recovery bundle:

```powershell
revit-operator recovery-snapshot --max-depth 2 --bridge-result-limit 10
```

This writes `recovery_snapshot.json` plus optional UI tree/screenshot evidence, embedded dialog recovery plans when dialogs are visible, and a conservative next step. It never clicks, types, queues bridge commands, saves, syncs, reloads, or closes the model.

Validate the recovery recommendation table without touching live Revit:

```powershell
revit-operator recovery-drill-matrix
```

Rehearse supervision resume/stall behavior without touching live Revit:

```powershell
revit-operator supervision-endurance-matrix
```

Expected: four synthetic cases pass: resume segments, modal stop, busy stall
with recovery snapshot capture, and unknown stall with recovery disabled. This
does not replace a real multi-hour endurance run.

Audit accumulated live supervision evidence against an hours-long target:

```powershell
revit-operator supervision-endurance-audit --target-hours 2 --min-checks 24
```

Expected before the endurance gap is closed: `status: insufficient_evidence`.
The audit is read-only; it scans sandboxed `supervision_log.json` files, excludes
synthetic/test logs by default, and does not start a new polling run. It merges
overlapping qualifying intervals before computing `total_live_seconds`, so
concurrent supervision logs cannot falsely satisfy the elapsed-time gate.

Run a bounded read-only supervision loop:

```powershell
revit-operator supervise-session --duration 300 --poll 5 --bridge-result-limit 10
```

For a quick check:

```powershell
revit-operator supervise-session --max-checks 2 --poll 1
```

Resume an existing supervision log by reusing the same `--task-id`:

```powershell
revit-operator --task-id live-supervise-resume supervise-session --resume --max-checks 1 --poll 1
```

This writes or appends `supervision_log.json`, records state transitions and
segments, and stops early on modal dialogs unless `--continue-on-modal` is
supplied. Resume mode is read-only; it appends observations and does not act on
Revit.

During a long run, `supervise-session` checkpoints `supervision_log.json` after
each observation with `checkpoint_status: running` and `supervisor_pid`. On
clean exit it rewrites the same file with `checkpoint_status: complete`. This makes read-only
endurance evidence recoverable if a supervisor is interrupted before the final
return payload is printed.

Repeated busy/unknown states are treated as a possible stall. By default,
`supervise-session` stops after 12 consecutive busy/unknown checks with no
active dialog and captures a read-only recovery snapshot. Tune or disable this:

```powershell
revit-operator supervise-session --stall-after-checks 6
revit-operator supervise-session --stall-after-checks 0 --no-recovery-on-stall
```

## 11. Export Read-Only Metadata

Without the add-in bridge, this writes a stub metadata file that documents the missing bridge:

```powershell
revit-operator export-metadata
```

When the Revit add-in writes:

```text
<sandbox>\bridge\metadata_snapshot.json
```

the same command will copy that snapshot into the task metadata directory.

## 12. Run the Read-Only QA Workflow

When Revit is open with no active dialogs and the add-in bridge is loaded:

```powershell
revit-operator qa-workflow --timeout 120 --poll 1
```

If the currently running Revit session loaded an older add-in that only processes queued work after a UI event, first dry-run focus to get the exact token:

```powershell
revit-operator focus --hwnd <main-window-hwnd>
```

Then run the workflow with a supervised focus and Escape nudge:

```powershell
revit-operator qa-workflow --timeout 120 --poll 1 --focus-hwnd <main-window-hwnd> --focus-approval-token APPROVE:<digest> --idle-nudge
```

The workflow refuses to start when active dialogs are present. It writes metadata, UI tree, screenshot, journal entries, and a draft QA report under the selected sandbox.

## 13. Generate QA Report

```powershell
revit-operator qa-report
```

The report is a draft and must remain labeled:

```text
DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW
```

## 14. Review Logs

```powershell
revit-operator task-log --latest
```

Review:

- `journal.jsonl`
- `summary.md`
- `screenshots\`
- `metadata\`

Every engineering output must remain labeled:

```text
DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW
```

## 15. Record Workflow Memory

List guarded reusable UI workflow recipes:

```powershell
revit-operator ui-workflows
```

Validate all reusable UI workflow recipes without running them:

```powershell
revit-operator ui-workflow-matrix
```

Run smoke-safe observation/planning prefixes for every recipe:

```powershell
revit-operator ui-workflow-smoke-matrix
```

Plan one recipe without executing anything:

```powershell
revit-operator plan-ui-workflow --name project-browser-open-sheet --sheet-number S2.0
revit-operator plan-ui-workflow --name manage-links-inspection
```

Run a recipe through the guarded step runner:

```powershell
revit-operator run-ui-workflow --name project-browser-open-sheet --sheet-number S2.0
```

The runner captures fresh status before every step. It can run low-risk
observation/planning steps, but stops before approval-gated steps unless exact
step-indexed approval tokens are supplied. Recipe plans are checklists over
existing guarded primitives. They may include approval-gated future steps, but
the planner itself never clicks, queues bridge commands, saves, syncs, reloads,
closes, or modifies Revit.

After a successful supervised task, record its journal as a reusable sandbox template:

```powershell
revit-operator record-workflow --source-task-id live-qa-workflow-3 --name "Live Readonly QA Workflow" --description "Read-only active document, metadata export, UI evidence, and draft report."
```

List recorded templates:

```powershell
revit-operator workflow-library
```

Dry-run a replay plan:

```powershell
revit-operator plan-workflow --name "Live Readonly QA Workflow"
```

Recorded templates can expose parameter bindings for common payload fields.
Inspect the template or plan output for parameter names, then pass fresh values
as JSON. Overrides are copied into the step payload and reclassified before any
execution path exists:

```powershell
$parameters = '{"step_0_target":"OK"}'
revit-operator plan-workflow --name "Parameterized Click Dry Run" --parameters-json $parameters
```

A dangerous override must remain blocked:

```powershell
$parameters = '{"step_0_target":"Save"}'
revit-operator plan-workflow --name "Parameterized Click Dry Run" --parameters-json $parameters
```

Create a fresh approval package for a recorded replay:

```powershell
revit-operator workflow-approval-plan --name "Parameterized Click Dry Run"
```

Review `workflow_approval_plan.json`. It must show
`stale_approval_tokens_reused: false`. If a parameter override changes a step
to a blocked action such as `Save`, the plan returns blocked steps and no
execute command.

Dry-run the guarded replay runner:

```powershell
revit-operator replay-workflow --name "Live Readonly QA Workflow"
```

The replay runner observes Revit before every step, reclassifies each action,
checks recorded state predicates where available, stops on unexpected modal UI
by default, and executes only a narrow subset:

- `focus`
- `press-key`
- `click`
- `type-text`
- `uia-invoke`
- `request-operation`

If replay stops in execute mode, it writes a read-only `recovery_snapshot.json`
by default so the next operator can inspect Revit state before resuming. Use
`--no-recovery-snapshot` only when collecting that evidence is not useful.

To execute, provide fresh exact approval tokens by step index:

```powershell
revit-operator replay-workflow --name "Live Readonly QA Workflow" --execute --approval-tokens-json '{"2":"APPROVE:<digest>"}'
```

When replaying a parameterized workflow, pass `--parameters-json` in the same
way as planning. Approval tokens still need to be fresh and step-indexed; they
are not recorded in the workflow template.

Recorded workflow templates are not automatic replay scripts. They do not store reusable approval tokens and require fresh Revit observation, matching document/window/dialog context where recorded, fresh dialog classification, and fresh approval before future actions.

## 16. Shut Down Safely

For cautious shutdown:

1. Ensure no high-risk Revit dialog is unresolved.
2. Capture `status`, `list-dialogs`, and `screenshot`.
3. If saving/syncing/closing through Hermes, use explicit approved `request-operation` commands.
4. Close Revit manually only if appropriate for the copied local model.
5. Archive the task journal if the run produced useful QA evidence.
