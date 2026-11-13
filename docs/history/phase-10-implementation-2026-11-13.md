# Phase 10 implementation progress - 2026-11-13

Branch: `feat/phase-10`. Reviewed decisions preserved by `06d3551`; Phase 9
maintenance `3f1d803` integrated by merge `e3bac04`. Existing planning work and
Phase 9 branches were preserved. No remote push is implied by this report.

## Implemented boundaries

- Rust/Tauri source shell with explicit, disjoint bootstrap/gateway capabilities
  and generated application-command permissions. Remote gateway gets only the
  directory picker; handlers additionally validate window, exact origin,
  generation and owned-process liveness.
- Serialized supervisor, suspended Windows creation with an explicit inherited
  handle allowlist, assignment to a kill-on-close non-breakaway Job before resume,
  monotonic startup/stop deadlines and owned cleanup. Raw child stdout/stderr is
  drained in bounded scratch buffers and discarded. Native diagnostics use only
  closed state/error codes.
- Bounded typed parent/child protocol and separate correlated credential pipe.
  Explicit trusted-bootstrap token reveal uses the same approved store as gateway
  authentication. No token CLI/environment/URL/log/localStorage transport.
- Desktop Python entry reserves exactly `127.0.0.1:7842` before constructing
  Application. Desktop owns start/shutdown directly; ordinary gateway lifespan
  behavior remains the default. Stop refuses sessions/new turns, cancels turns
  and denies approvals before uvicorn drains connections.
- Tray controls, local status/login-help window, close-to-tray explanation,
  navigation/new-window refusal and gateway destruction when the launch lease
  ends. Picker fills only the candidate; existing save/restart authority remains.
- Optional quarantine/approval notice hooks preserve audit/default deny, with
  bounded queue and closed localized native dispatch policy. Installed delivery
  remains deferred. `desktop.lifecycle` audit records observed ready/stop intent,
  not crash-time audit flushing or completed process cleanup.

## Bugs found during verification

1. Existing chat sockets could start a turn after shutdown began. A failing
   gateway regression observed `turn.started`; shutdown now refuses new turns
   before cancellation yields.
2. A failed teardown could leave return code zero. The runtime now determines
   its result after teardown; the failure regression passed.
3. Real Windows Stop timed out although fake-core Stop passed. The private reader
   immediately started another synchronous read; CRT close waited for that read's
   descriptor lock. A subprocess test reproduced the four-second hang. Stop now
   ends the reader, and idle shutdown cancels synchronous I/O before close.
4. Native bundled `index.html` was excluded from the exact local URL allowlist;
   a failing native URL test covered the correction.
5. Picker labels were initially placed at a flat JSON key while the translator
   expects nested keys. A shipped-locale Node test failed, then passed with the
   nested EN/FR entries.

Gateway CSP additionally forbids child frames with `frame-src 'none'`. This
strengthens the existing policy; script/connect/origin permissions were not
widened. A failing CSP regression preceded the change. This deliberately
disallows a future iframe feature unless reviewed separately.

## Environment and observed checks

- Rust 1.100.0, Cargo 1.100.0, Tauri CLI 2.12.4, Tauri 2.12.5/build 2.7.4.
  CLI release ZIP SHA-256 was checked against official release metadata;
  development cache/tools are excluded from Git.
- Owner approved Rust/MSVC installation. The default recommended workload ran
  out of C-drive space; minimal MSVC 14.44.35207 and Windows SDK 10.0.26100.0
  installed on D. Installer requested reboot; subsequent native build/tests
  worked in the current session. The redundant newly installed stable Rust
  toolchain was removed; the exact pinned version remains.
- WebView2 157.0.4341.46. A non-bundling debug Tauri CLI build succeeded and the
  real bootstrap/gateway windows opened. Native status IPC worked. Smoke data
  used an empty isolated workspace/plugin directory and an encrypted fake-token
  fallback under `.cache/`; real vault credentials/documents were not inspected.
- Initial Python protocol: 32 passed; lifecycle/launcher slice: 26 passed;
  desktop+chat slice: 58 passed; notice emitter: 3 passed. These are intermediate
  observations, not the final full-suite count.
- Latest isolated pipe/audit slice: 3 passed. Node UI: 10 passed, including real
  nested EN/FR picker labels. Native actor fixture and real Job helper passed.
- Ruff and mypy (127 source files) passed before the final verification run.
  Full Python suite, final native checks and final branch review are in progress;
  append their actual results below before claiming completion.

## Independent review and fix pass

A fresh read-only whole-change reviewer found two important lifecycle defects
and one stale documentation row. No critical finding was reported.

- Delayed GUI callbacks could discard destruction and retain the old gateway
  window across restart. The fix requires an explicit generation-bound
  destruction acknowledgement before another core starts. GUI scheduling,
  destruction failure or a five-second acknowledgement timeout keeps the lease
  denied and blocks launch until confirmed. Gateway native labels are now
  `gateway-<generation>`; the handler checks that immutable native label as well
  as the JS argument, exact origin and process liveness. The capability prefix
  grants only picker access and does not grant native window creation.
- `Stopped(false)` and exit without a clean acknowledgement could be displayed
  as normal Stop. The actor now records a clean-stop result, drains final event
  frames before classifying process exit, checks exit code and Job process count,
  and preserves failure through cleanup. Brief Job-accounting settlement is
  bounded; it never makes the GUI wait on process work.
- Full native verification exposed Job accounting reaching zero before the
  process handle signaled exit. Cleanup now requires both conditions before
  success; the real process regression failed before this correction and passed
  afterward.
- The stale decision-table row describing desktop as future work was corrected.

Regression tests first observed forged-generation authorization and an unclean
Stop incorrectly reaching STOPPED; the missing teardown gate also failed before
implementation. The fix pass covers delayed/failed/reordered destruction replies,
timeouts, stale native labels, `Stopped(false)`, exit without acknowledgement and
production native/Python Stop with an explicit clean-outcome assertion. A real
descendant regression also verifies private-handle noninheritance, failed forged
event writes and EOF while that descendant is alive. Quarantine callback failure
is separately checked to retain both quarantine and its audit event.

Reviewer limits retained deliberately: authenticated WebView2/UI behavior remains
open; native notice-click/focus handling is not implemented or claimed tested;
durable crash recovery needs a separate ownership decision; release/platform
acceptance is deferred; exact dependency pins are not a vulnerability audit.
These limits are not silently treated as completed requirements. The remaining
manual acceptance cost is tracked by the checklist and release dossier.

## Implementation rulings and practical costs

- Retain the prepared `feat/phase-10` checkout and preserve existing planning
  changes before integrating maintenance. This follows the owner's chosen branch;
  it does not provide a second worktree for concurrent independent edits.
- Implement the independently testable Python IPC while the approved Windows
  toolchain was installed. Native/WebView2 acceptance stayed open; later runtime
  compatibility can still require changes.
- Use a PowerShell-native plan ledger on this Windows runner instead of the
  bash helper scripts. Commands/results are recorded explicitly; helper-generated
  bookkeeping is not claimed.
- Strengthen CSP with no child frames, at the cost of requiring a separate review
  for future iframe features. No currently implemented UI depends on iframes.
- Bind native gateway identity to generation-specific labels. Consumers assuming
  a fixed native window label must change; origin/API grants remain narrow.
- Keep one cohesive source-feature commit for the cross-language protocol,
  lifecycle and capability contract after the fix pass. This sacrifices per-task
  cherry-pick granularity but avoids intermediate commits with mismatched native
  and Python contracts. It does not merge/publish the branch or close manual gates.

The `computer-use` skill forbids automating user authentication dialogs
("Do not automate user authentication dialogs."). The native automation pipe
also became unavailable after the session resumed. Authenticated native UI
acceptance therefore remains a manual check, rather than an inferred pass from
API tests. Recovery, release/platform acceptance and dependency-security audit
limits above remain explicit; no new persistence architecture was silently chosen.

## Final automated verification for this commit

- `uv sync --frozen`: 153 packages checked.
- `uv run ruff check .`: passed.
- `uv run mypy declaw declaw_plugin_sdk`: passed, 127 source files.
- `uv run pytest` with fresh `.cache/phase10-full-after-review` basetemp:
  **1105 passed, 1 skipped, 3 warnings in 124.12 seconds**. The warnings concern
  upstream uvicorn/websockets legacy APIs. Log: ignored
  `.cache/phase10-full-after-review.log`.
- `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs`:
  **10 passed**.
- Native `cargo fmt --check`, locked `cargo clippy --all-targets -- -D warnings`:
  passed. Locked `cargo test`: **16 passed, 1 ignored driver-only worker**.
  The ignored worker is explicitly executed in an isolated subprocess by its
  passing driver test; it is not an omitted lifecycle scenario. Log:
  `.cache/phase10-native-complete.log`.
- Pinned Tauri CLI `cargo tauri build --debug --no-bundle` from `tauri/`: passed.
  Executable: `.cache/tauri-target/debug/declaw-desktop.exe` on this machine
  because the ignored target directory was explicitly selected. Log:
  `.cache/phase10-tauri-build-verified.log`.
- Local Markdown file links, intended-file exclusions and `git diff --check`:
  passed. Generated schemas, caches, temporary workspaces and encrypted test
  credentials are excluded from the commit. Remote GitHub CI has not run here.

This verifies the source implementation and its automated boundaries. It does
not close the manual WebView2/recovery checklist or release tickets. The final
independent reviewer was not rerun after the one test-verified fix pass.

## Remaining acceptance and scope limits

The [acceptance checklist](../phase-10-review.md) maps every open Phase 9 browser
category to WebView2. Authenticated real-WebView2 security/interaction, remote
picker IPC and native Stop after the pipe fix still need observed evidence.
The Windows automation skill prohibits automating user authentication dialogs;
API/socket authentication tests do not substitute for that UI acceptance.

Interrupted tasks/index writes do not have reliable durable desktop-launch
ownership. No automatic repair, blanket task failure, index purge or tool replay
was added. Further persistence changes require the separately scoped decision
and concurrent-CLI tests specified in the design.

DCL-144 and DCL-146..150 remain open. See the
[release-boundary dossier](../phase-10-release-boundaries.md). No installer,
signing key, notification registration, updater or model download was added.
