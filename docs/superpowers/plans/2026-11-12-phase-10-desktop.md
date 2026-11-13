# Phase 10 Desktop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Track execution with the checkboxes below.

**Goal:** Deliver a Windows-first Tauri shell around the existing gateway, with owned core lifecycle and narrowly scoped native features.

**Architecture:** Rust supervises one Python gateway and its descendants. The gateway continues to own application services, authentication, approvals and audit. A private versioned control channel carries lifecycle and safe notification events.

**Tech Stack:** Tauri 2, Rust, Windows Job Objects, Python 3.12+, uv, existing FastAPI/uvicorn and vanilla JS UI.

**Spec:** [Phase 10 design](../../specs/2026-11-12-phase-10-tauri-desktop-design.md).

## Execution status and branch prerequisite

Implementation authorized by the owner on 2026-11-12 ("code it"), resumed 2026-11-13. Rust/MSVC installation was separately approved. See the [progress report](../../history/phase-10-implementation-2026-11-13.md) and [acceptance checklist](../../phase-10-review.md). All seven spec section-10 decisions were settled under explicit owner delegation on 2026-11-12; see the spec for the selected scope.

Branch setup completed on 2026-11-12. The Phase 9 repair commit is `110e9e7`;
local `main` was fast-forwarded from `61947f6` to that exact tested commit,
then `feat/phase-10` was created from `main`. No remote push occurred.
Existing changes were preserved; the two Phase 10 planning documents were
excluded from the Phase 9 commit and carried into this branch.
See [Phase 9 verification](../../history/phase-9-verification-2026-11-12.md):
the full suite completed, the owner accepted the visual UI, and authenticated
real-browser security/interaction checklist items remain open. This baseline
does not claim completion of those manual checks or ratify section 10.

- [x] Inspect and preserve all existing changes; commit Phase 9 separately.
- [x] Establish the tested Phase 9 baseline on local main (`110e9e7`), with the manual-check limitations recorded above.
- [x] Create feat/phase-10 from that main commit.
- [x] Retain the existing checkout: only the two Phase 10 planning documents remained untracked after the Phase 9 commit; no separate worktree was needed for planning.
- [x] Include the two documents in the Phase 10 planning commit; record the committed Phase 9 base and branch below.

Execution log: planning branch `feat/phase-10`, base `110e9e7` (same as
local main and `feat/phase-9-gateway-web-ui` at branch creation). No Phase 10
product code, dependencies or architecture approvals were added.

Documentation re-review, 2026-11-12: current Phase 9 is `3f1d803` and is not an
ancestor of this planning branch. The completed checkboxes above describe the
original branch creation only. They do not establish the latest implementation
prerequisite. The owner asked for document review/correction, not a main merge or
publication; preserve refs and add the pending integration gate below.

## Task 0 — Dependency baseline and owner decisions (no product code)

Files: this plan, the Phase 10 spec and the eventual dated spike/review reports.

- [x] Preserve `ecc615a` and these reviewed planning changes. Inspect local Git
  status, then integrate Phase 9 commit `3f1d803` (or a reviewed successor) into
  this branch through the normal integration process, without reset/force-push.
  If the chosen process requires main integration, do that only with its own
  authorization. Verify the selected Phase 9 tip is an ancestor of Phase 10.
- [x] Read the Phase 9 maintenance report from the selected baseline and update
  the exact source paths: documents/sources.py, settings_file.py and the new CI
  feature-branch trigger. Do not resurrect removed dependencies/scaffolding.
- [x] Record all seven spec section-10 decisions under owner delegation (2026-11-12): source-development delivery, DCL-146..150 release acceptance and installed Windows notification identity/activation deferred to Phase 14. DCL-144 remains open.
- [x] Map open Phase 9 browser checks to Task 1 WebView2 acceptance. Existing
  visual feedback or server/minimal-DOM tests do not check off browser security.

Task 0 is complete: e3bac04 integrates 3f1d803 while retaining the reviewed docs; current source paths/CI were read, and docs/phase-10-review.md maps the browser acceptance. Task 1 acceptance remains open; mapping is not verification.

## Global constraints

- Exactly http://127.0.0.1:7842; no LAN binding, wildcard Origin or silent port fallback.
- Python owns tools, sanitizer, approvals and audit; native code cannot bypass them.
- Credentials remain vault/encrypted-fallback backed. No secret in argv, environment, logs, URLs or browser storage.
- Typed argv and IPC; no shell strings or generic native filesystem/process APIs.
- Selected policy budgets: 30 seconds startup, 10 seconds graceful stop, 5 seconds forced cleanup.
- Source-development Windows delivery. Packaging, signing and updater release gates remain deferred to Phase 14 under decision 6.
- Code/comments English; user-facing text EN/FR. Security tests precede implementation.
- Native handlers enforce the spec's privilege matrix and current launch lease;
  no generic getter, process, filesystem or notification API exposed to gateway.
- Rust UI callbacks remain nonblocking. Use monotonic deadlines and fixed safe
  diagnostic codes; raw child output/validation errors must not leak secrets.

## Review focus

1. Replacement listener and delayed old-launch events: invalidate launch lease, deny native commands and destroy the webview before any retry (Tasks 2/4).
2. Descendant inherits control handles and prevents EOF: explicit inheritance allowlist (Tasks 2/3).
3. Stop while indexing or awaiting approval: cleanup terminates descendants and denies approvals (Tasks 3/7).
4. Workspace path with spaces, Unicode, junctions or cancellation: selection grants no filesystem access (Task 5).
5. Installed Windows notification identity versus source scope, click remounting active chat, and stale/cross-session IDs: explicit scope decision and socket-preservation tests (Tasks 0/1/6).

## Task 1 — Ratify boundaries and prove webview compatibility (DCL-140)

**Files:** One crate at tauri/src-tauri/Cargo.toml with its Cargo.lock, build.rs,
tauri.conf.json, src/main.rs, src/lib.rs, capabilities/bootstrap.json,
capabilities/gateway.json and permissions/*.toml. Pin the toolchain in
tauri/rust-toolchain.toml; bootstrap assets live in tauri/bootstrap/. No extra
Cargo workspace is needed. Record results in a dated docs/history/phase-10-desktop-spike report.

**Interfaces:** Define the local bootstrap label and immutable native gateway-<generation> labels; scope the picker capability to that native-only prefix. Gateway navigation target is the exact loopback URL. No generic invoke commands.

- [ ] Complete Task 0 above, preserving the seven settled decisions and their scope limits.
- [ ] Pin the compatible Rust toolchain, Cargo Tauri CLI, crate/plugins and MSRV; record WebView2/MSVC prerequisites. Create rust-toolchain.toml and explicit application-command permissions. Use AppManifest command permissions, an explicit capability list and narrow gateway remote access; inspect combined grants. No frontend build or npm dependency is assumed.
- [ ] Build the smallest shell proving gateway cookie login, REST, WS chat/events and existing CSP without policy relaxation.
- [ ] Write denial tests before native commands: wrong window/origin, no overlapping default capability, disallowed credential/lifecycle/notification APIs on gateway. Prove actual remote IPC transport under unchanged CSP, redirects/new windows/iframes refusal and normal browser-only fallback. Use deterministic test gateway/auth fixtures without making them a production launcher.
- [ ] Record source-mode notification behavior and the decision-7 deferral. Installed branding/permission/click activation checks belong to Phase 14; do not install/register software or complete DCL-144 from a development toast.
- [ ] Run `cargo check --manifest-path tauri/src-tauri/Cargo.toml` and record exact pinned `cargo tauri dev` invocation/working directory and non-bundling build command from CLI help. Installer generation is outside this spike unless separately approved. Record M1 results, then commit feat(DCL-140): add constrained desktop shell.

## Task 2 — Typed private protocol and supervisor (DCL-141/142)

**Files:** Create tauri/src-tauri/src/control.rs, supervisor.rs, windows_job.rs; tests under tauri/src-tauri/tests/supervisor.rs; Python schema in declaw/desktop/protocol.py and tests/unit/test_desktop_protocol.py.

**Interfaces:** Python ParentFrame is Stop(version=1, launch_id) or
RequestBootstrapToken(version=1, launch_id, request_id). ChildFrame is
Ready(version=1, launch_id, authority), Failure(version=1, launch_id, code),
Stopped(version=1, launch_id, clean: bool), or Notice(version=1, launch_id,
event_id, kind: quarantine|approval_pending, language: en|fr, task_id optional,
request_id optional). BootstrapToken(version=1, launch_id, request_id, token)
travels ONLY on the separate inherited credential pipe and matches an explicit
bootstrap request. UUIDs are canonical strings, authority exactly `127.0.0.1:7842`;
normalize neither unknown fields nor invalid scalar types. Control frames are
at most 16 KiB, credential replies 4 KiB, including newline, enforced before
decode. Fixed safe errors never include raw payload or secret-bearing repr.

Rust SupervisorState: Stopped, Starting, Running, Stopping, Failed.
SupervisorHandle::start/stop/restart return Result<(), DesktopError> for queued
action acceptance; they do not wait on process work on the GUI thread. An owned
actor serializes transitions and publishes state snapshots. DesktopError is a
closed enum of safe codes (invalid_settings, port_conflict, spawn_failed,
protocol_invalid, startup_timeout, shutdown_timeout, unavailable); no captured
command line, stdout, payload or OS exception text is returned to web content.

- [ ] Write failing Python/Rust protocol tests: extra fields, bool-for-int,
  unknown/direction-invalid variant, invalid UTF-8/UUID/authority/language,
  duplicate Ready, partial EOF, oversize before newline and stale request IDs.
  Include secret replies mistakenly sent on the general channel: reject with a
  fixed code and no token in captured logs/errors. Run `uv run pytest tests/unit/test_desktop_protocol.py`.
- [ ] Implement strict schemas and bounded decoding, then rerun the same tests.
- [ ] Write supervisor tests: duplicate/concurrent actions yield one child,
  FAILED cannot restart before cleanup; occupied port conflict leaves the
  listener untouched; stale generations cannot change state; deadlines reach
  FAILED without blocking a GUI heartbeat; malformed Ready cannot reach RUNNING.
- [ ] Resolve the canonical repository .venv/Scripts/python.exe and fixed
  `-m declaw.desktop` argv from trusted launch configuration, never web content
  or ambient cwd. Assign the suspended child to a kill-on-close Job Object
  before resume; abort and clean up on assignment failure. No breakaway flags;
  explicit handle-inheritance allowlist; Job handle stays parent-only.
- [ ] Bound/drain child stdout/stderr but do not forward arbitrary output to UI
  or persistence. Render allowlisted safe diagnostics, not regex-only redaction
  of unknown text. Test fake token split across output chunks, full pipes and
  EOF while stopping; notice traffic cannot starve lifecycle/token handling.
- [ ] Test unrelated process survival and descendant termination on job closure using real Windows helper processes; test failure before resume and cleanup after partial startup.
- [ ] Run cargo test --manifest-path tauri/src-tauri/Cargo.toml and commit feat(DCL-141): supervise owned desktop core.

## Task 3 — Python desktop lifecycle adapter (DCL-141/142)

**Files:** Create declaw/desktop/__init__.py, __main__.py, runtime.py; modify declaw/gateway/app.py for reusable async launch/shutdown seams and declaw/app.py only for a narrow lifecycle/notice seam if needed; tests/unit/test_desktop_runtime.py and tests/integration/test_desktop_lifecycle.py. Reuse the selected Phase 9 module layout.

**Interfaces:** async run_desktop(settings: Settings, channel: DesktopChannel) -> int;
DesktopChannel has async receive() -> ParentFrame, send(frame: ChildFrame) -> None,
send_bootstrap_token(frame: BootstrapToken) -> None and close() -> None. The last
sender uses the separate private credential pipe. Transport uses inherited
private handles, not a network endpoint. Existing CLI launch stays compatible.

- [ ] Write failing tests for non-7842 settings rejection and an exclusive bind
  before Application construction/start. Busy port must not start plugins,
  reconcile/index files, attach to or terminate the existing listener. Ready is
  emitted only after lifespan startup and serving the owned socket; Ollama down
  does not prevent ready. Reuse assert_launch_contract plus desktop-only port validation.
- [ ] Write tests for stop/EOF during startup, turn, pending approval and indexing; assert existing shutdown hooks run in their order and failures are reported without secrets.
- [ ] Implement the adapter with the exclusively reserved socket and shared
  Application/uvicorn lifecycle. A stop coordinator first refuses sessions/turns,
  cancels active turns and denies approvals, then completes connection/lifespan
  teardown within one 10-second budget. Test live WebSocket/approval shutdown:
  simply setting server.should_exit and waiting for uvicorn to drain can wait
  on those same sockets before Application's cancellation hooks run. Reuse
  idempotent hooks; no HTTP shutdown route or duplicate engine disposal.
- [ ] Resolve one approved vault/fallback SecretStore and inject it into auth
  and explicit bootstrap credential handling. Test absent keyring with a fake
  encrypted-fallback store, mismatched/stale token requests and no token printed
  by desktop startup; ordinary CLI bootstrap remains unchanged.
- [ ] Prevent control handle inheritance into plugin processes. Test a plugin descendant cannot retain the channel or impersonate ready/notice.
- [ ] Run uv run pytest tests/unit/test_desktop_runtime.py tests/integration/test_desktop_lifecycle.py tests/unit/test_app_lifecycle.py tests/gateway/test_launch.py.
- [ ] Commit feat(DCL-141): connect desktop control to application lifecycle.

## Task 4 — Bootstrap, login, recovery and tray (DCL-142/143)

**Files:** Create tauri/src-tauri/src/bootstrap.rs, tray.rs; extend bootstrap assets and supervisor.rs; tests/bootstrap_security.rs and tests/tray_state.rs under tauri/src-tauri/.

**Interfaces:** Trusted bootstrap displays loading/error/retry and an explicitly requested transient token display from the private child transfer. Gateway webview uses existing login endpoint/cookie. Tray actions map to supervisor start/stop/restart; Open focuses the window; Quit waits for cleanup. No credential getter callable by gateway content.

The trusted bootstrap can be reopened through the native Status/login-help
surface while the core runs, so a failed/expired login does not require restarting
Python or exposing a credential getter to gateway JS. Each reveal requires an
explicit user action and matching private request ID; the token remains persistent
in the vault and is not rotated as a side effect of displaying it.

- [ ] Write failing tests for secret redaction, token access from gateway rejection, redirect/navigation refusal and wrong-window native invocation.
- [ ] Test core exit immediately destroys/unloads gateway content and revokes access; replacement listener cannot regain native privileges. Recreate only after owned readiness.
- [ ] Implement login/bootstrap, bounded diagnostics and retry. Never parse CLI stdout to obtain token; desktop entry suppresses console token output.
- [ ] Add single-instance coordination per user, close-to-tray explanation and state-driven enabled tray actions. Test duplicate launches do not start a second core.
- [ ] Test duplicate/reordered Ready/exit/stop and old-generation native requests;
  invalid launch lease or dead owned process denies commands immediately, then
  destroys the gateway webview. Prove queued retries cannot resurrect old access.
- [ ] Verify normal stop uses 10-second grace then at most 5-second forced cleanup;
  startup timeout is 30 seconds. The GUI heartbeat must stay responsive during
  each deadline. Confirm actual Job/process cleanup after Stopped; distinguish
  crash termination from graceful audit flushing.
- [ ] Run Rust tests plus gateway auth/Host-Origin regression tests; manually exercise real WebView2 login/restart with EN/FR. Commit feat(DCL-143): add desktop lifecycle controls.

## Task 5 — Workspace picker (DCL-145)

**Files:** Create tauri/src-tauri/src/picker.rs, ui/js/desktop.js; modify ui/js/settings.js and ui/locales/en.json, fr.json; extend tests/gateway/ui-behavior.test.cjs and Rust picker authorization tests.

**Interfaces:** pick_workspace() -> Result<Option<String>, DesktopError> opens a directory-only OS dialog; cancellation is None. JS chooseWorkspace() resolves string or null. Existing settings save remains the authority; browser mode retains its current input.

- [ ] Test picker cancellation leaves settings unchanged; chosen absolute path fills the candidate only; save still invokes existing validation; restart-required feedback remains.
- [ ] Test wrong window/origin denial and path fixtures with spaces/Unicode/junction escapes through existing backend validation. Selection does not read/index outside workspace.
- [ ] Implement minimal scoped command and frontend feature detection, with localized labels and keyboard access.
- [ ] Test env-overridden workspace save separately: candidate can be saved but
  effective workspace still follows environment precedence. The current text
  field remains usable in browser mode and native cancellation changes nothing.
- [ ] Run `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs`,
  `uv run pytest tests/unit/test_settings_service.py tests/unit/test_config.py tests/gateway/test_rest.py`
  and Rust picker tests; commit feat(DCL-145): select workspace through native dialog.

## Task 6 — Native notices (DCL-144)

**Files:** Create declaw/desktop/notifications.py, tauri/src-tauri/src/notifications.rs;
adapt declaw/app.py quarantine-sink composition and declaw/gateway/approval.py
request emitter via optional injected callbacks; preserve their ordinary CLI/web
behavior. Extend ui/js/desktop.js and behavior tests for focus without remount;
tests/unit/test_desktop_notifications.py and Rust notification tests.

**Interfaces:** emit_notice(kind: Literal['quarantine', 'approval_pending'], event_id: str,
task_id: str | None, request_id: str | None = None) -> None queues a typed Notice
without blocking authoritative work. Bodies are fixed EN/FR strings. Rust uses
queue 64, 5 notices/minute and dedup of the most recent 256 IDs, per settled spec.
Python SettingsService's effective language selects localized fixed text through
the strict language field defined in Task 2; no model/content-derived strings.
Handle invalid settings/notice-hook failures without failing audit or approvals.

Decision 7 defers installed native-notification acceptance to Phase 14;
record that deferral and leave DCL-144 acceptance open. Do not
execute installation/registration steps or label native delivery complete; safe
event-hook tests and existing in-app feedback do not replace the missing acceptance.

- [ ] Write tests for malformed IDs, oversize frames, duplicate notices, queue/rate bounds, denied OS permission and sensitive content omission.
- [ ] Deferred to Phase 14 under decision 7: test actual native click focusing the existing window preserves the original WebSocket,
  pending turn/modal and typed message buffer: no reload/hash remount/new socket,
  no tool approval/replay. Expired/cross-session IDs show fixed localized feedback;
  do not navigate to nonexistent task/quarantine viewers. If Audit navigation
  cannot preserve a live chat, focus only. Notice loss never changes broker state.
- [ ] Implement authoritative event wiring without replacing existing audit sinks or correlation. Reject notice events from unowned channels.
- [ ] Run Python/Rust targeted suites, including simulated focus callbacks and unavailable-native fallback; record installed Windows notification checks as deferred to Phase 14, not passed; commit feat(DCL-144): surface safe native notices.

## Task 7 — Recovery, regression and handoff

**Files:** tests/integration/test_desktop_lifecycle.py; tauri/src-tauri/tests/; docs/phase-10-review.md; docs/project-status.md, code-map.md, architecture-decisions.md, TICKETS.md; CI workflow additions scoped to supported desktop checks.

- [ ] Trace persisted task/audit/index states after forced interruption and
  identify which writes belong to the owned launch. Document a precise recovery
  contract and obtain any required schema/ownership decision before changes.
  Add failing tests with concurrent unrelated CLI work: recover only owned work,
  never blanket-mark every RUNNING task, purge indexes or replay approved tools.
  If ownership cannot be established, record the limitation and block the recovery
  acceptance claim rather than inventing safe automatic repair.
- [ ] Exercise desktop crash, forced core stop, unavailable model, bad config, missing runtime and restart after partial indexing. Assert owned descendants gone and unrelated processes alive.
- [ ] Run `uv sync --frozen`; `uv run ruff check .`; `uv run mypy declaw declaw_plugin_sdk`;
  `uv run pytest`; `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs`.
  Use the documented loopback-capable runner and a fresh local basetemp where needed.
- [ ] Run cargo fmt --manifest-path tauri/src-tauri/Cargo.toml --check; cargo clippy
  --manifest-path tauri/src-tauri/Cargo.toml --all-targets -- -D warnings; cargo test
  --manifest-path tauri/src-tauri/Cargo.toml; the exact pinned Windows non-bundling
  Tauri build command recorded in Task 1. Only run installer-producing checks in
  the separately approved notification/package scope.
- [ ] Record manual Windows checks: tray, login, quit during approval/indexing, notification activation, picker, keyboard/high-DPI and EN/FR. Record machine/tool versions, skips and limitations in a dated report.
- [ ] Update status/map/decisions and ticket evidence. Keep installer/updater/signing tickets open until their own acceptance criteria pass; document Phase 14 prerequisites.
- [ ] Review the complete branch diff; commit only intended Phase 10 changes. Do not merge or publish solely because this plan is complete.

## Task 8 — Release-boundary dossier (DCL-146..150)

Files: docs/phase-10-release-boundaries.md and links from docs/README.md;
TICKETS.md only for ratified scope notes, never unverified completion checkmarks.

- [ ] Write the deferred-delivery matrix: updater opt-in and signed channel,
  trusted key custody, Python/UI/migrations/builtin-plugin assets, MSI/WebView2
  prerequisites, uninstall/data retention, rollback and macOS/Linux acceptance.
  State evidence still required, owner and phase for each item.
- [ ] Separate any approved installed notification test fixture from an actual
  end-user installer. No model downloads, autostart, signing keys or update
  network check is added by the dossier. Record no acceptance beyond observed checks.
- [ ] Check links and spec/ticket consistency; keep DCL-146..150 open until their
  original acceptance or a separately ratified scope change is satisfied.

## Self-review

Spec coverage: dependency baseline/decisions -> Task 0; webview security and known
Windows notification constraint -> Task 1; protocol/process ownership -> Task 2;
exclusive binding/auth/shutdown -> Task 3; bootstrap/tray/picker -> Tasks 4/5;
safe notices and live chat preservation -> Task 6; scoped recovery/verification ->
Task 7; deferred delivery artifacts -> Task 8. Protocol/notice limits are selected
policy defaults with matching spec values, not measured guarantees. Task 0 is
complete; WebView2/Windows UI and recovery acceptance remain open, and
notification scope is settled by decision 7. No product task is marked complete by these decisions. Only documents were changed in this pass.


## Execution evidence - 2026-11-13

Task 0 is complete. Tasks 1-6 have implementation and automated evidence in the
[report](../../history/phase-10-implementation-2026-11-13.md), with remaining
checks in the [checklist](../../phase-10-review.md); do not infer whole-task
completion from source existence. Task 7 has outstanding real-WebView2 and
ownership-scoped recovery acceptance. Task 8 is documented in the
[release-boundary dossier](../../phase-10-release-boundaries.md); release tickets
remain open. Product code has not been pushed by this execution.
