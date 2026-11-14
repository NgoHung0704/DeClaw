# Phase 10 acceptance checklist

Updated 2026-11-14. Checked boxes require observed evidence in the
[implementation report](history/phase-10-implementation-2026-11-13.md) or
[architecture repair report](history/phase-10-architecture-repairs-2026-11-14.md).
This checklist maps the open [Phase 9 browser checks](phase-9-review.md) to the
desktop. Server/minimal-DOM tests do not close WebView2 acceptance items.

## Automated boundaries

- [x] Exact desktop host/port and exclusive listener reservation before services.
- [x] Strict bounded directional IPC, separate token pipe, generation/request checks.
- [x] Gateway gets only picker; bootstrap local commands and token access are separate.
- [x] Real Job cleanup kills descendants and preserves an unrelated process.
- [x] Fake-core actor covers duplicate Start, token request, restart and Quit.
- [x] Delayed/failed GUI destruction blocks restart; stale results and a stale
  native window claiming the current generation cannot regain access.
- [x] Unclean/missing Stop acknowledgement is reported as failure. Production
  native actor plus Python child Stop/Start/Quit is tested with an isolated vault.
- [x] Real loopback WebSocket stop cancels a pending approval without a tool write.
- [x] Existing sockets refuse new turns once shutdown starts.
- [x] Windows pipe Stop regression reproduced and fixed; idle-reader cancellation tested.
- [x] Real descendant cannot retain control/event/credential handles or forge an
  event; EOF is observed while that descendant remains alive.
- [x] Picker candidate/cancellation/browser fallback and shipped EN/FR label tests.
- [x] Notice-hook failure retains default deny; dispatch rate/dedup and fixed body tests.
- [x] Server/service failure and cancelled server drain do not skip later cleanup;
  one total timeout still bounds teardown.
- [x] Unexpected event EOF revokes readiness while the child is alive; acknowledged
  clean Stop followed by EOF remains clean.
- [x] Actual full control pipe cannot block Quit or autonomous write deadlines;
  cleanup cancels pending native I/O and joins its writer.
- [x] Injected gateway-builder state failure offers a localized same-core retry;
  actual WebView2 build failure remains a manual acceptance gap.

## WebView2 and Windows UI

The [2026-11-14 acceptance attempt](history/phase-10-acceptance-2026-11-14.md)
initially reported repeat-use picker and minimized second-launch problems.
Follow-up corrected the Cancel inference: the unparented dialog was still open
behind the main window; actual Cancel completed normally. Minimized gateway
restore passed after adding unminimize. Parented-dialog final acceptance is
recorded in that report; compound entries below remain open.

- [x] Bundled bootstrap opens and calls native status under its CSP.
- [x] Owned gateway opens the existing UI at the exact loopback authority.
- [ ] Repeat native Stop after the Windows pipe fix; verify STOPPED, destroyed
  gateway window and empty Job, then Start/Restart/Quit through the native UI.
  The 2026-11-14 rebuilt app reached STOPPED, removed its gateway window and
  successfully completed Start/Restart. Tray Quit/empty-Job UI acceptance is
  still separate; the checkbox remains open.
  Follow-up: after owner-triggered Quit on the final build, successful Windows
  process/listener checks found no DeClaw-related Python/desktop process and no
  listener on 7842. The closed Job itself was not queried; evidence is in the
  acceptance report.
- [ ] Paste-once login, HttpOnly cookie reload/logout, REST settings/status and
  both chat/events sockets under gateway CSP, without new allowed origins.
- [ ] Actual remote picker IPC succeeds under CSP; wrong-origin/window, iframe,
  redirect and new-window requests remain denied. Cancellation changes no value.
- [ ] Markup-shaped model text, document names, audit/plugin payloads render as
  literal text (Phase 9 markup checklist) and cause no script execution.
- [ ] WRITE approval, deny/timeout, streaming cancel and core loss preserve the
  original chat socket/state; no replay after restart (Phase 9 session checklist).
- [ ] Documents/plugins/settings/status report deferred changes and unavailable
  models truthfully (Phase 9 settings/status checklist).
- [ ] Close-to-tray, second launch focus, Status/login reopening, tray action
  states, keyboard access, high DPI and full EN/FR switching.

Installed toast branding, click activation and focus-without-remount acceptance are explicitly deferred to Phase 14
under decision 7; DCL-144 remains open. No installed notification test is marked
passed. Simulated notice dispatch is not installed acceptance.

## Interrupted persistence

- [ ] Establish durable ownership of interrupted task/index writes before any
  automatic repair. Current rows do not reliably identify a desktop launch;
  unrelated CLI work can share the data directory. Do not blanket-fail RUNNING
  tasks, purge indexes or replay approvals/tools.
- [ ] Approve any necessary ownership/schema decision separately, then test
  concurrent unrelated CLI work, forced crash and partial-index restart recovery.

Graceful cancellation uses current task failure semantics. Job process cleanup
does not establish durable crash recovery or audit flushing.
