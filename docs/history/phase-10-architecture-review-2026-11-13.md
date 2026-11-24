# Phase 10 architecture and implementation review — 2026-11-13

Follow-up: the [2026-11-14 repair report](phase-10-architecture-repairs-2026-11-14.md)
records changes and fresh verification for these findings. The observations
below describe the reviewed baseline, not the repaired working tree.

## Scope and verdict

Reviewed commit `4adb31b` against baseline `e3bac04`: 75 changed files, 9,718
added lines and 43 removed lines. Read the current status, code map, active
decisions, Phase 10 spec and plan, traced the Python/native/UI boundaries and
their tests, and obtained an independent static review of the native code.
The working tree was clean before review. Product code was not changed.

The thin desktop architecture is appropriate and the source builds and passes
the existing checks. It is not yet demonstrated reliable enough to close Phase
10: four runtime defects below need fixes and regression coverage, and the
recorded authenticated WebView2 acceptance gate remains open. Passing tests
currently omit important failure paths.

This is a correctness, architecture and maintainability review, not an exhaustive
security audit. Fault probes use isolated test doubles and ignored `.cache`
artifacts; they do not access user credentials or a real user vault.

## Findings

### P2 — Server failure can skip application shutdown

Evidence: [runtime.py](../../declaw/desktop/runtime.py), lines 179–205,
especially the consecutive `await serving` and `await application.shutdown()`
at lines 194–195. Re-awaiting an already failed server task raises before the
application cleanup call. The outer handler marks the stop unclean but does
not perform that cleanup.

Two controlled runtime probes injected a server exception before and after
Ready. Both returned exit code 1 and closed the listener/channel; both called
refuse-new-turns, cancel-turns and deny-approvals; neither called
`Application.shutdown()`. Native Job cleanup limits orphan processes, but does
not replace cooperative service, storage and audit teardown.

Required change: make application cleanup independent of the server task's
outcome, preserve the bounded stop budget and accurate unclean-stop reporting,
and cover both startup and running server failures.

### P2 — Event-pipe loss leaves a live, ready lease

Evidence: [supervisor.rs](../../tauri/src-tauri/src/supervisor.rs), lines
487–488 and 537. Event EOF only sets `event_eof`; exit processing also requires
the child process to have exited. An alive child that loses its event endpoint
can retain Running and a ready native lease without the supervision channel.

Reproduced through the unchanged production supervisor and Windows Job owner
using a synthetic core executable. It sent Ready, closed only the event
endpoint and remained alive. The snapshot still reported
`state=Running, ready=true, alive=true`. This is injected endpoint loss, not a
claim that the ordinary Python child closes this endpoint during normal use.

Required change: treat unexpected event EOF/read failure outside acknowledged
shutdown as failure, revoke the lease and perform bounded owned cleanup. Add
an actor-level regression test.

### P2 — Blocking control writes bypass supervisor deadlines

Evidence: [windows_job.rs](../../tauri/src-tauri/src/windows_job.rs), lines
261–264, performs synchronous `write_all`. The sole supervisor actor calls it
for Stop at [supervisor.rs](../../tauri/src-tauri/src/supervisor.rs):401 and
token requests at line 419; deadlines are installed after the writes at lines
403 and 423. A blocked write prevents the actor from handling Quit or deadlines.

Reproduced with a synthetic core that keeps the control pipe open without
draining it, peeks request IDs and returns fixture-only credential responses.
After 442 completed token requests the pipe filled; the next request timed out
at the caller and Quit did not finish within the probe's 12-second wait.
The snapshot remained Running/ready/alive. This is a sustained backpressure
fault injection, not a claim that a single ordinary request fills the pipe.
After the probe owner exited, its fake child was no longer running, consistent
with kill-on-close Job containment.

Required change: use bounded/cancellable control output or a dedicated writer
whose blocked operation cannot stop lifecycle/deadline processing. Add a full
pipe regression that proves Quit and owned cleanup remain bounded.

### P2 — Gateway WebView creation failure is silently discarded

Evidence: [bootstrap.rs](../../tauri/src-tauri/src/bootstrap.rs), lines
100–101, handles only `Ok(window)` from the gateway WebView builder. `open()`
at lines 112–122 falls back to bootstrap when the gateway window is absent,
without reconstructing it for the ready generation.

If bootstrap succeeds but the second WebView creation fails, the core remains
Running without the product window or a surfaced creation error. This finding
is established by tracing error handling; it was not reproduced by injecting
a WebView2 failure in a real GUI session.

Required change: surface a safe native error and provide a retry that creates
the gateway window for the same still-live generation. Retain generation and
origin checks. Test the builder failure/retry path.

### P3 — Invalid settings lose the structured startup diagnostic

Evidence: [__main__.py](../../declaw/desktop/__main__.py), lines 22–32.
`get_settings()` can raise after private channels have been opened, before
`run_desktop()` owns their lifecycle. The broad handler returns 1 without a
fixed failure frame or explicit channel close.

A controlled settings-parse failure returned 1, sent no frame and left the
channel's close method uncalled. Process exit reclaims handles; this is chiefly
a missing actionable startup diagnostic, not an enduring OS handle leak.

Required change: close an acquired channel on entry-point failure and map known
settings validation failures to the fixed protocol diagnostic without exposing
raw exception text or secrets.

## Architecture and file organization

Strengths:

- Python remains the application authority; Rust owns desktop process lifetime.
  Existing gateway and UI are reused through narrow lifecycle seams.
- The child is assigned to a kill-on-close Windows Job before execution;
  inherited handles are explicitly limited and the Job handle stays parent-only.
- Bootstrap credentials use a private channel. Shutdown is not exposed as an
  HTTP endpoint, and the gateway remains at `127.0.0.1:7842`.
- Trusted bootstrap and remote gateway views have separate capabilities.
  Gateway access checks native generation/window identity and exact authority.
  Navigation/new-window restrictions and acknowledged view destruction are
  substantive controls, not merely JavaScript flags.
- Unclean stops are represented explicitly. Existing tests cover stale view
  destruction, stop acknowledgement and child exit accounting.

No identical nonempty files were found among the changed files. Of added lines,
5,001 (about 51.5%) are Cargo.lock, 1,346 are tests, 414 documentation, 1,892
native product code and 800 Python product code. The commit size alone does
not indicate architecture bloat. Keep the lockfile, generated command
permissions and separate bootstrap assets: they have distinct responsibilities.

Reasonable cleanup opportunities:

- Remove obsolete empty placeholders `tauri/icons/.gitkeep` and
  `tauri/src-tauri/src/.gitkeep` after confirming tooling does not require them.
  The real icon lives under `tauri/src-tauri/icons/`.
- Consolidate repeated native test fixture setup for Python environment copying,
  temporary checkouts, waits and cleanup in the supervisor/unclean-stop tests.
  Do not introduce a new production abstraction merely to reduce test lines.
- Python/Rust wire types are necessary endpoint implementations, rather than
  duplicate modules to delete. Shared protocol examples/golden vectors would
  help prevent schema drift between languages.
- The roughly 640-line supervisor, including a large actor loop with related
  flags, is the main maintainability hotspot. Address the fault handling above
  before adding more lifecycle state; extract responsibilities only where their
  ownership and tests become clearer.
- Ruff formatting check reports 10 files needing formatting across the Python
  desktop source/tests. `ruff check` passes because formatting is a separate
  check. Normalize these files in a dedicated cleanup change.
- `docs/project-status.md:62` still says Phase 10 planning does not ratify pending
  architecture choices. That wording needs alignment with the seven settled
  spec decisions. Preserve the genuine open acceptance/recovery boundaries.

The spec, implementation plan, source run guide, release-boundary document,
manual checklist and dated evidence report serve different purposes. Keep their
roles explicit and link them instead of copying fresh verification claims into
each one. Historical plans are not the executable status authority.

## Verification performed

| Check | Result |
| --- | --- |
| `uv sync --frozen` | Passed; 153 packages checked |
| `uv run ruff check .` | Passed |
| `uv run mypy declaw declaw_plugin_sdk` | Passed; 127 source files |
| Full pytest suite | 1,105 passed, 1 skipped; 162.97 seconds |
| Gateway UI Node behavior tests | 10 passed |
| Rust formatting check | Passed |
| Locked Rust clippy, all targets, warnings denied | Passed |
| Locked native test suite | 16 passed, 1 ignored worker test; worker also executed by its driver |
| Pinned Tauri CLI debug build, no bundle | Passed; desktop executable built, no installer created |
| Python desktop formatting check | Failed: 10 files would be reformatted |

Full pytest emitted five warnings: three upstream Uvicorn/websockets legacy
deprecations and two unhandled aiosqlite worker-thread exceptions reporting
`Event loop is closed`, attributed by pytest to the quarantined-plugin test.
A focused desktop/plugin rerun with unhandled-thread warnings promoted to errors
passed all 11 tests and produced only the three upstream warnings. The thread
warnings remain untriaged; the evidence does not establish a Phase 10 regression.
They should not be silently represented as a warning-free full suite.

Local ignored evidence includes `.cache/phase10-audit-full.log`,
`.cache/phase10-audit-thread-warnings.log`, `.cache/phase10-audit-clippy.log`,
`.cache/phase10-audit-native-tests.log`, `.cache/phase10-audit-build.log`,
`.cache/phase10-review-probes.json`,
`.cache/phase10-eof-probe.log` and
`.cache/phase10-control-backpressure-probe.log`. These scratch artifacts are not
versioned deliverables or permanent reproducibility guarantees.

## Acceptance limits and next work

Actual authenticated WebView2 behavior remains unverified by this review:
effective remote IPC authorization, cookie-based REST/WebSocket operation,
navigation/popups/frames, workspace picker modality and Unicode/junction paths,
tray/keyboard/DPI/language behavior. Also retain the real simultaneous-launch
and forced desktop-parent-crash acceptance checks. Synthetic Job fault probes
do not replace those GUI/process acceptance scenarios. Native inventory was
available, but no DeClaw window was open; browser access was unavailable. No
authenticated GUI acceptance is claimed.

Installed notifications/activation and packaging are explicitly deferred to
Phase 14, and durable recovery policy remains an unresolved recorded boundary.
Those are not newly discovered implementation defects or authorization to add
recovery behavior.

Recommended order: fix server teardown and supervisor channel/backpressure
failure handling with regression tests; fix WebView creation recovery and
startup diagnostics; normalize formatting/fixtures/placeholders and stale status
wording; triage full-suite aiosqlite warnings; then run the authenticated native
acceptance matrix before closing Phase 10.
