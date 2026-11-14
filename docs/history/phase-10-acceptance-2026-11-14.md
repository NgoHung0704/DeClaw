# Phase 10 acceptance attempt — 2026-11-14

Baseline: `3d88709`, source Windows desktop. Verdict: **not accepted yet**.
This attempt adds manual observations, not a new full automated-suite run.

## Observations

- Existing authenticated Audit and Settings remained accessible.
- Settings opened the actual Windows directory picker through gateway IPC.
  Cancel closed the dialog and preserved the workspace field. No settings were
  saved and no workspace was changed.
- After cancellation, Choose folder remained disabled in both the screenshot
  and a later accessibility observation. Repeat selection therefore did not
  recover during this attempt. The native reply/JavaScript completion path needs
  diagnosis; the underlying cause is not yet established.
- The main window was initially minimized. Launching the same executable again
  left it minimized on repeated observation. The user restored it through the
  taskbar. `bootstrap::open` currently calls show/set_focus without unminimize;
  this is a plausible cause, not yet a proven fix.

## Acceptance decision

Keep the broad picker and second-launch checklist entries open. Picker opening
and preservation on Cancel have partial evidence; repeated use failed. Prior
full-suite/build and download/lifecycle evidence remains in the architecture
repair report and does not override these observations.

Tray Quit/empty Job, hostile WebView input/origin paths, pending approval/core
loss, forced-crash persistence and high-DPI/full keyboard scenarios were not
completed in this attempt. Crash recovery still requires the recorded ownership
decision before automatic repair. No destructive crash test was performed on
the user's active data. Phase 10 must not be marked complete on this evidence.

## Diagnostic follow-up

The earlier inference that Cancel left the callback stuck was incorrect. The
unparented Select Folder window was still open behind the main window: targeting
the main window for the apparent Cancel click activated that window instead of
cancelling the separate dialog. Selecting the actual dialog window and clicking
its Cancel produced every native diagnostic milestone (callback with no
selection, send, receive and authorized reply); Choose folder became enabled and
the workspace was preserved. No callback/channel change was necessary.

The repair explicitly parents the picker to the requesting WebView window so
the dialog stays associated with it. Temporary fixed diagnostic milestones were
removed. Native pre/post authorization and candidate-only settings semantics are
unchanged. On the final nonbundled debug build, the parented dialog appeared
above DeClaw; Cancel re-enabled Choose folder, repeated opening and Cancel
succeeded twice, and the workspace field remained unchanged. No Save was used.

Adding unminimize before focus was tested in the rebuilt desktop: minimizing
the gateway then launching the executable again restored the same window ID,
authenticated Settings route and workspace field. A single desktop process
remained. Bootstrap reopening also uses unminimize; its separate minimized case
has not yet been manually exercised.

## Final repair validation

- Node shipped UI behavior suite: 23 passed.
- Locked native bootstrap-security, gateway-view and view-teardown suites:
  8 passed. No fixed-port lifecycle suite was run with the user app open.
- Rust formatting and all-target clippy with warnings denied passed.
- Pinned Tauri debug `--no-bundle` build passed after the running executable
  was released. The first final-build attempt failed with Windows file lock
  error 5; it was not a compiler error.
- Independent read-only review found no important issue in the production diff.
- Final executable again restored a minimized authenticated gateway on second
  launch. Parented-dialog repeated Cancel was verified as described above.

These two acceptance issues are resolved/corrected. Overall Phase 10 remains
open for the other scenarios listed above. Python code was unchanged; this
follow-up did not rerun full pytest and does not present earlier counts as new.

## Owner-triggered Quit check

After the owner reported tray Quit on the final build, a successful read-only
Windows process query found no desktop process or Python process matching
DeClaw/desktop/plugin paths. A successful TCP listener query found no listener
on port 7842. The first sandbox process query was denied and was not counted as
evidence; the user-session query succeeded. No process was terminated by the
verification commands. This establishes the observed post-Quit state; it does
not inspect an already-closed Job handle or establish forced-crash recovery.
An additional broad directory/name search matched 17 Python processes; further
classification identified all as IDE tooling (Serena, language servers and
VS Code's lsp_server.py), not desktop core/plugin workers. These were preserved.
