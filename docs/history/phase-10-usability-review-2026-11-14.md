# Phase 10 desktop usability review — 2026-11-14

## Method and scope

Hands-on Windows/WebView2 review of the locally built source desktop app at
commit `4adb31b`, spanning the evening of November 13 and November 14 in
Europe/Paris. Interacted with actual app windows using native computer use;
this is separate from the automated and fault-injection
[architecture review](phase-10-architecture-review-2026-11-13.md).

The first session was already authenticated. Submitted harmless generated-text
chat prompts, inspected Documents/Settings/Status/Plugins/Audit, opened and
cancelled the native directory picker, temporarily saved French then restored
English, and tested streaming cancellation and a subsequent turn. Existing
model/workspace values and plugin permissions were retained. No document was
edited or deleted; no tool write was approved. Chat prompts and settings saves
can leave ordinary task/audit records. Later relaunched the desktop and exercised
native Stop, Start and Restart before requesting user-assisted authentication.
After the user signed in again, tested authenticated reload, both audit export
buttons, hide/reopen state retention and audit pagination. The final app remains
open and authenticated on Audit with filters reset to the latest records.

## Observed findings

### High priority: leaving Chat discards the visible conversation

Reproduction independent of language changes or process restart:

1. Send a simple request for the marker `NAVIGATION-CHECK-OK`.
2. Observe the user message and successful assistant response.
3. Open Documents from the sidebar, then return to Chat.
4. Observe the empty welcome screen; the completed conversation is absent.

This also happened on the first return from the initial settings/page review.
The observation establishes loss of the visible conversation and continuity;
it does not establish deletion of persistent task/audit data.

Code evidence: [chat.js](../../ui/js/chat.js):136–161 closes the old socket,
resets active-turn state and constructs a new empty log on each mount.
[core.js](../../ui/js/core.js) replaces main content on route changes.
Retain the live conversation across in-app navigation and make starting a new
conversation an explicit action. Durable history/reconnect recovery needs its
own scoped design; do not replay approvals or writes to reconstruct a view.

### Medium priority: settings language change leaves mixed languages

On English Settings, choose Français and Save. Sidebar and page heading become
French, while Model, Language, Workspace folder, Choose folder, Save and restart
helper text remain English. The saved-feedback banner also remains in the old
language. Reversing the change produces the opposite-language feedback.

Code evidence: [settings.js](../../ui/js/settings.js):74–92 builds feedback
before `setLanguage`, then updates only navigation and heading. Navigation to
the current settings hash does not trigger a fresh hash-change render.
Re-render/update the complete form consistently while preserving values and
focus, and localize feedback after selecting the effective UI language.

### Medium priority: cancellation has no explicit outcome in the transcript

During a long generated response, Send disabled and Cancel enabled correctly.
Cancel stopped streaming and restored Send; a subsequent request returned
`AFTER-CANCEL-OK`. However, the partial assistant response appears as ordinary
answer text, with no cancelled label. Status merely returns to ready. Mark the
partial response as stopped and make cancellation acknowledgement visible.

An unexpected `filesystem_read …` activity card appeared during the no-tools
generation test and remained without a visible completion. This is a UI
observation, not proof of a new tool invocation or its cause. Trace frame/task
correlation and tool completion before attributing it to model behavior,
replayed activity or backend execution. Start/end activity should be reconciled
into a clear running/succeeded/failed/cancelled state instead of orphan ellipses.

Follow-up evidence from the actual Audit UI shows a matching test-time
`filesystem_read` attempt against a fictional filename, rejected because
`max_bytes` was null. This supports a tool-selection/argument failure during the
no-tools prompt, without demonstrating file access or a successful tool action.
The activity card still failed to make that validation failure understandable.

### High priority: desktop audit export silently does nothing

In the authenticated Audit page, clicked Export json and Export md separately
for the displayed day. Neither showed a new window, save/download UI, error or
success feedback; the page stayed unchanged. No filesystem download audit was
performed, so the direct observation is the missing visible export workflow.

The incompatible wiring is explicit: [audit.js](../../ui/js/audit.js):26 uses
`window.open(..., "_blank")`, while the gateway builder in
[bootstrap.rs](../../tauri/src-tauri/src/bootstrap.rs):99 returns
`NewWindowResponse::Deny`. Provide a bounded authenticated export/download flow
with visible outcome and error handling; retain the default denial of arbitrary
popups rather than broadly allowing new windows.

### Medium priority: audit Older works but Newer remains disabled

Scrolled to the bottom of the first audit page and clicked Older. The records
changed to older timestamps, confirming a page transition. Newer remained
disabled, so the user cannot step back through that pagination control. Clear
filters returned to the latest records and was used to restore the final state.

Code evidence: [audit.js](../../ui/js/audit.js):62–81 ignores the `direction`
parameter, always disables Newer and only enables Older using `next_cursor`.
Keep cursor history for backward navigation, reset it when filters change and
test first/older/back/last-page behavior. Keep pagination reachable without
scrolling through the full raw-JSON table.

### Medium priority: audit data is difficult to scan

At the normal approximately 1180-pixel-wide desktop window, event names such as
`network.call` wrap into several fragments, timestamp/UUID share one cell and
raw JSON dominates each row. Date filters have weak visible labeling; the export
date has no clear visible label. Prefer readable timestamp/event/summary columns,
an expandable payload view, and explicit From/To/export-day labels. Retain safe
literal-text rendering of untrusted payloads.

### Lower priority: document and status presentation expose raw values

Documents renders raw byte counts and long ISO timestamps. Status displays
`true`, `reachable` and `doc-intel=enabled`. Replace these with localized status
labels, human-readable sizes/local times and optional technical details.

The existing conversation reported UTF-8 failure reading a Word file that
Documents lists as indexed. Audit confirms an earlier `filesystem_read` error;
this review did not request that file's contents. Index success and tool choice
are different paths: trace document-aware routing/retrieval, and provide a
recoverable explanation rather than implying that indexed Office files are
unreadable by the whole application.

### Lower priority: picker and desktop entry flow need polish

Choose folder successfully opened a native Select Folder dialog from the real
gateway WebView. Escape/Cancel returned without changing the workspace field.
The dialog started at a previously used Windows location rather than the active
workspace. Consider a validated current-workspace initial directory and an
app-specific dialog title. Selection/save, Unicode paths, junction behavior and
wrong-origin IPC denial were not exercised in this GUI review.

Startup opens both bootstrap/status and main gateway windows. This is a
two-view trust design, but the visible handoff requires the user to locate the
other window/tray and copy a token. Preserve the trust boundary while making
one primary window and the next action obvious; do not silently grant credential
commands to the remote gateway to simplify the interaction.

## Positive observations

- Normal chat submission and model response worked in the actual WebView.
- Documents, Plugins, Settings, Status and Audit routes loaded successfully.
- The dark theme, spacing, typography and selected sidebar state are coherent.
- Native folder IPC and cancellation worked, without saving a new workspace.
- Streaming disables duplicate Send; cancellation permits a successful next turn.
- Fresh launch reached Running. Native Stop reached Core stopped and removed
  the gateway window; Start returned to Running; Restart returned to Running
  with a newly created gateway window. These observations do not independently
  prove an empty Windows Job or absence of all descendants.
- Native bootstrap French labels and status text translated, and English was
  restored. This selector is distinct from the gateway Settings language.
- Launching the executable a second time brought the existing gateway window
  forward, with the same gateway/status window IDs and no additional app window.
  This verifies the visible single-instance behavior, not a process-tree audit.
- After user-assisted login, Ctrl+R returned to a working authenticated Chat
  without requesting the token again; authenticated Audit data also loaded.
- Clicking X hid the gateway from the visible-window inventory. Launching the
  executable again restored the same gateway window ID on Audit with an unsent
  `gateway.auth` filter value still present. This verifies hide/reopen and state
  retention through second launch. The tray menu itself was not operated in
  this test, and the filter was subsequently cleared.

## Limits and remaining acceptance

Relaunch/restart displayed a fresh Connect screen. Authentication was handed to
the user; no credentials were submitted by automation or included in this report.
Forced crash,
WRITE approval/denial, installed notifications, durable recovery, high-DPI
behavior, precise latency, full screen-reader support and hostile-origin
authorization are not claimed tested here. Existing architecture findings remain
open even when normal lifecycle interaction succeeds.

Direct tray-menu Open/Quit interaction remains unverified because the current
native inventory did not expose a targetable shell/tray surface. Hide/reopen
through second launch is recorded separately above. No product code was changed
and no new automated product tests were run for this documentation update.
