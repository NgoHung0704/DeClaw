# Phase 10 architecture repairs — 2026-11-14

## Scope

The owner authorized fixing all four P2 findings from the
[architecture review](phase-10-architecture-review-2026-11-13.md), then rebuilding
and reopening the source desktop for testing. Existing usability/download work
and local data are preserved. No installer or notification registration is added.

## Repairs

- Python teardown guards each service step and consumes failed/cancelled server
  outcomes independently, so Application.shutdown is still attempted within the
  existing shared deadline. Deadline cancellation propagates; faults stay unclean.
- Unexpected event EOF fails the launch and revokes readiness before owned
  cleanup. FIFO ordering preserves an acknowledged clean Stop followed by EOF.
- A private control writer bounds frame size, pending queue and write deadline.
  The actor never performs synchronous pipe writes. Cleanup cancels synchronous
  Windows I/O and joins the writer before reporting success; timeout retains
  ownership for cleanup retry.
- Gateway creation failure is tracked by generation and exposed through existing
  trusted status. EN/FR bootstrap feedback offers retry through Start/Open, on the
  GUI thread, reusing the healthy core and existing authorization checks.

## Verification

Fault tests were observed failing before the corresponding repair. The genuine
EOF fixture uses the base interpreter because the Windows venv redirector can
retain inherited handles and mask EOF. Full-pipe tests fill the actual OS pipe;
the cancellation unit test holds the reader open and verifies pending I/O,
bounded enqueueing, joined worker and closed writer handle.

Fresh frozen sync, Ruff and mypy passed. Node behavior tests passed 23 cases
using `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs`.
The final locked native suite passed **23 tests**; one worker is deliberately
marked ignored and invoked by its passing driver. This includes all four pipe
fault cases, including autonomous deadline expiry and actual child termination.
Formatting and all-target clippy with warnings denied passed on the final code.
The pinned Tauri debug build with `--no-bundle` passed; no installer was generated.

The first full Python run in the restricted session reported 1114 passed,
1 failed, 1 skipped and 3 upstream websocket deprecation warnings. The failure
was the unrelated CLI indexing test's Windows `CredWrite` error 1312. A full
rerun in the user session then passed: **1115 passed, 1 skipped, 3 upstream
warnings in 74.25 seconds**. No product change was made to hide the keyring error.

An independent static review found no important defect in the four repairs.
The view-builder injection tests the state helper and bootstrap behavior, not
an actual failing WebView2 installation. Real failure/retry acceptance remains
separate. The initial full-pipe Quit test was extended with an autonomous
write-deadline test following review.

## Desktop acceptance

Updated executable: `.cache/tauri-target/debug/declaw-desktop.exe`.
The rebuilt executable opened the bundled status and gateway Connect views.
Native Stop reached Core stopped and the gateway window disappeared; the local
listener was absent. Start returned to Running and opened a new gateway window.
Restart again passed through Stopping and returned to Running with a replacement
gateway window. No forced termination was used. Tray Quit/empty-Job acceptance
and actual failing-WebView2 retry were not exercised by these UI actions.

After user-assisted login, Audit Export JSON followed by Save JSON produced
`declaw-audit-2026-11-14 (4).json` in the WebView's effective `D:\Downloads`,
12,178 bytes. Export Markdown followed by Save MD produced
`declaw-audit-2026-11-14.md`, 599 bytes. Both triggered Download completed.
Read-only metadata checks confirmed the files; JSON parsed successfully and
Markdown was nonempty, without printing audit contents.

The earlier assumed download failure was a verification-path mistake: Windows
User Shell Folders reported `C:\Users\ADMIN\Downloads`, while the WebView download
history for the exact task filename identified `D:\Downloads`. Earlier JSON
exports were also present there. This corrects the earlier failure inference;
it does not establish that the native handler was required to make downloads
work. The handler now supplies the explicit policy and completion feedback.

No secrets or private fixture contents belong in this report. Release, installed
notification and crash-recovery gates remain in the existing Phase 10 checklist.
