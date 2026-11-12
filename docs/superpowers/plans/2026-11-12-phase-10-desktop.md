# Phase 10 Desktop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Track execution with the checkboxes below.

**Goal:** Deliver a Windows-first Tauri shell around the existing gateway, with owned core lifecycle and narrowly scoped native features.

**Architecture:** Rust supervises one Python gateway and its descendants. The gateway continues to own application services, authentication, approvals and audit. A private versioned control channel carries lifecycle and safe notification events.

**Tech Stack:** Tauri 2, Rust, Windows Job Objects, Python 3.12+, uv, existing FastAPI/uvicorn and vanilla JS UI.

**Spec:** [Phase 10 design](../../specs/2026-11-12-phase-10-tauri-desktop-design.md).

## Execution status and branch prerequisite

Planning only, 2026-11-12. Neither product code nor dependency installation is authorized by this plan alone. Spec section 10 decisions remain pending ratification.

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

## Global constraints

- Exactly http://127.0.0.1:7842; no LAN binding, wildcard Origin or silent port fallback.
- Python owns tools, sanitizer, approvals and audit; native code cannot bypass them.
- Credentials remain vault/encrypted-fallback backed. No secret in argv, environment, logs, URLs or browser storage.
- Typed argv and IPC; no shell strings or generic native filesystem/process APIs.
- Proposed budgets: 30 seconds startup, 10 seconds graceful stop, 5 seconds forced cleanup.
- Source-development Windows delivery. Packaging, signing and updater release gates remain deferred pending scope ratification.
- Code/comments English; user-facing text EN/FR. Security tests precede implementation.

## Review focus

1. Replacement listener on port 7842 after core crash: unload webview and revoke capabilities (Tasks 2/4).
2. Descendant inherits control handles and prevents EOF: explicit inheritance allowlist (Tasks 2/3).
3. Stop while indexing or awaiting approval: cleanup terminates descendants and denies approvals (Tasks 3/7).
4. Workspace path with spaces, Unicode, junctions or cancellation: selection grants no filesystem access (Task 5).
5. Notifications unavailable in an unpackaged Windows build: prove support or report a scoped blocker (Tasks 1/6).

## Task 1 — Ratify boundaries and prove webview compatibility (DCL-140)

**Files:** Create tauri/Cargo.toml only if using a workspace; tauri/src-tauri/Cargo.toml, Cargo.lock, build.rs, tauri.conf.json, src/main.rs, src/lib.rs, capabilities/bootstrap.json, capabilities/gateway.json; local bootstrap assets under tauri/bootstrap/. Record results in docs/history/phase-10-desktop-spike-2026-11-12.md (use actual execution date).

**Interfaces:** Define window labels bootstrap and gateway. Gateway navigation target is the exact loopback URL. No generic invoke commands.

- [ ] Obtain decisions from spec section 10; update spec status with exactly what was approved.
- [ ] Consult current official Tauri docs for capability enforcement, custom command authorization, WebView2 and build prerequisites. Pin compatible dependencies rather than guessing version APIs.
- [ ] Build the smallest shell proving gateway cookie login, REST, WS chat/events and existing CSP without policy relaxation.
- [ ] Exercise navigation/new-window refusal and unauthorized invoke calls from the wrong window/origin; record actual outcomes.
- [ ] Prove notification permission and activation behavior in source-development Windows execution. If registration is necessary, resolve scope before continuing DCL-144.
- [ ] Run cargo check and Windows manual spike checks; commit with feat(DCL-140): add constrained desktop shell.

## Task 2 — Typed private protocol and supervisor (DCL-141/142)

**Files:** Create tauri/src-tauri/src/control.rs, supervisor.rs, windows_job.rs; tests under tauri/src-tauri/tests/supervisor.rs; Python schema in declaw/desktop/protocol.py and tests/unit/test_desktop_protocol.py.

**Interfaces:** Python ControlFrame discriminated union: Ready(version=1, launch_id, authority), Failure(version=1, launch_id, code), Stopped(version=1, launch_id), Notice(version=1, launch_id, event_id, kind, task_id optional). Parent sends Stop(version=1, launch_id). Unknown fields/types and wrong version/launch ID rejected. UTF-8 newline-delimited JSON, maximum frame 16 KiB; no credentials in this general protocol. Credential transfer is a separate one-shot private message with redaction and no generic forwarding.

Rust SupervisorState: Stopped, Starting, Running, Stopping, Failed. Supervisor::start(&mut self) -> Result<(), DesktopError>; stop(&mut self) -> Result<(), DesktopError>; state(&self) -> SupervisorState. Methods serialize transitions; lifecycle events finish asynchronous transitions.

- [ ] Write failing protocol tests for invalid version, extra fields, oversized/partial frame, wrong launch ID and secret-safe errors; run uv run pytest tests/unit/test_desktop_protocol.py.
- [ ] Implement strict schemas and bounded decoding, then rerun the same tests.
- [ ] Write supervisor tests: duplicate start yields one child; occupied port yields conflict without termination; timeout reaches Failed; wrong readiness cannot reach Running.
- [ ] Implement typed executable/argv resolution and process ownership. Assign a suspended child to a kill-on-close Job Object before resuming; abort if assignment fails. Job handle is never inherited; only intended pipe endpoints are inherited.
- [ ] Test unrelated process survival and descendant termination on job closure using real Windows helper processes; test failure before resume and cleanup after partial startup.
- [ ] Run cargo test --manifest-path tauri/src-tauri/Cargo.toml and commit feat(DCL-141): supervise owned desktop core.

## Task 3 — Python desktop lifecycle adapter (DCL-141/142)

**Files:** Create declaw/desktop/__init__.py, __main__.py, runtime.py; modify declaw/gateway/app.py only for a reusable async server seam; tests/unit/test_desktop_runtime.py and tests/integration/test_desktop_lifecycle.py.

**Interfaces:** async run_desktop(settings: Settings, channel: DesktopChannel) -> int; DesktopChannel.receive() -> ControlFrame; send(frame: ControlFrame) -> None; close() -> None. Transport uses inherited private handles, not a network endpoint. Existing CLI launcher stays compatible.

- [ ] Write failing tests asserting ready is sent only after successful application startup AND socket binding; Ollama absence does not prevent ready.
- [ ] Write tests for stop/EOF during startup, turn, pending approval and indexing; assert existing shutdown hooks run in their order and failures are reported without secrets.
- [ ] Implement the adapter using the existing Application and uvicorn lifecycle. Supply shutdown intent to the running server; do not emulate shutdown with an HTTP route.
- [ ] Prevent control handle inheritance into plugin processes. Test a plugin descendant cannot retain the channel or impersonate ready/notice.
- [ ] Run uv run pytest tests/unit/test_desktop_runtime.py tests/integration/test_desktop_lifecycle.py tests/unit/test_app_lifecycle.py tests/gateway/test_launch.py.
- [ ] Commit feat(DCL-141): connect desktop control to application lifecycle.

## Task 4 — Bootstrap, login, recovery and tray (DCL-142/143)

**Files:** Create tauri/src-tauri/src/bootstrap.rs, tray.rs; extend bootstrap assets and supervisor.rs; tests/bootstrap_security.rs and tests/tray_state.rs under tauri/src-tauri/.

**Interfaces:** Trusted bootstrap displays loading/error/retry and an explicitly requested one-time token display from the private child transfer. Gateway webview uses existing login endpoint/cookie. Tray actions map to supervisor start/stop/restart; Open focuses the window; Quit waits for cleanup. No credential getter callable by gateway content.

- [ ] Write failing tests for secret redaction, token access from gateway rejection, redirect/navigation refusal and wrong-window native invocation.
- [ ] Test core exit immediately destroys/unloads gateway content and revokes access; replacement listener cannot regain native privileges. Recreate only after owned readiness.
- [ ] Implement login/bootstrap, bounded diagnostics and retry. Never parse CLI stdout to obtain token; desktop entry suppresses console token output.
- [ ] Add single-instance coordination per user, close-to-tray explanation and state-driven enabled tray actions. Test duplicate launches do not start a second core.
- [ ] Verify normal stop uses 10-second grace then at most 5-second forced cleanup; startup timeout is 30 seconds. Distinguish crash termination from graceful audit flushing.
- [ ] Run Rust tests plus gateway auth/Host-Origin regression tests; manually exercise real WebView2 login/restart with EN/FR. Commit feat(DCL-143): add desktop lifecycle controls.

## Task 5 — Workspace picker (DCL-145)

**Files:** Create tauri/src-tauri/src/picker.rs, ui/js/desktop.js; modify ui/js/settings.js and ui/locales/en.json, fr.json; extend tests/gateway/ui-behavior.test.cjs and Rust picker authorization tests.

**Interfaces:** pick_workspace() -> Result<Option<String>, DesktopError> opens a directory-only OS dialog; cancellation is None. JS chooseWorkspace() resolves string or null. Existing settings save remains the authority; browser mode retains its current input.

- [ ] Test picker cancellation leaves settings unchanged; chosen absolute path fills the candidate only; save still invokes existing validation; restart-required feedback remains.
- [ ] Test wrong window/origin denial and path fixtures with spaces/Unicode/junction escapes through existing backend validation. Selection does not read/index outside workspace.
- [ ] Implement minimal scoped command and frontend feature detection, with localized labels and keyboard access.
- [ ] Run node --test tests/gateway/ui-behavior.test.cjs, relevant settings tests and Rust authorization tests; commit feat(DCL-145): select workspace through native dialog.

## Task 6 — Native notices (DCL-144)

**Files:** Create declaw/desktop/notifications.py, tauri/src-tauri/src/notifications.rs; adapt authoritative quarantine/approval emitters after tracing their current call sites; tests/unit/test_desktop_notifications.py and Rust notification unit tests.

**Interfaces:** emit_notice(kind: Literal['quarantine', 'approval_pending'], event_id: str, task_id: str | None) -> None emits a typed Notice to the owned channel. Native notification bodies are fixed EN/FR strings, never document text. Rust limits queue to 64 and delivery to 5 notices/minute, deduplicating the most recent 256 IDs.

- [ ] Write tests for malformed IDs, oversize frames, duplicate notices, queue/rate bounds, denied OS permission and sensitive content omission.
- [ ] Test notification click focuses UI without approving tools; stale task references fall back to the relevant page; notice loss never changes approval state.
- [ ] Implement authoritative event wiring without replacing existing audit sinks or correlation. Reject notice events from unowned channels.
- [ ] Run Python/Rust targeted suites and Windows real notification checks established in Task 1; commit feat(DCL-144): surface safe native notices.

## Task 7 — Recovery, regression and handoff

**Files:** tests/integration/test_desktop_lifecycle.py; tauri/src-tauri/tests/; docs/phase-10-review.md; docs/project-status.md, code-map.md, architecture-decisions.md, TICKETS.md; CI workflow additions scoped to supported desktop checks.

- [ ] Trace persisted task/audit/index states after forced interruption. Add failing recovery tests for actual uncovered states before implementing recovery; do not claim generic crash recovery from process termination alone.
- [ ] Exercise desktop crash, forced core stop, unavailable model, bad config, missing runtime and restart after partial indexing. Assert owned descendants gone and unrelated processes alive.
- [ ] Run uv sync --frozen; uv run ruff check .; uv run mypy declaw declaw_plugin_sdk; uv run pytest; node --test tests/gateway/ui-behavior.test.cjs.
- [ ] Run cargo fmt --manifest-path tauri/src-tauri/Cargo.toml --check; cargo clippy --manifest-path tauri/src-tauri/Cargo.toml --all-targets -- -D warnings; cargo test --manifest-path tauri/src-tauri/Cargo.toml; Windows Tauri build through the pinned CLI.
- [ ] Record manual Windows checks: tray, login, quit during approval/indexing, notification activation, picker, keyboard/high-DPI and EN/FR. Record machine/tool versions, skips and limitations in a dated report.
- [ ] Update status/map/decisions and ticket evidence. Keep installer/updater/signing tickets open until their own acceptance criteria pass; document Phase 14 prerequisites.
- [ ] Review the complete branch diff; commit only intended Phase 10 changes. Do not merge or publish solely because this plan is complete.

## Self-review

Spec coverage: baseline/scope -> prerequisite and Task 1; ownership/readiness -> Tasks 2/3; auth/native boundary -> Tasks 4/5; notices/audit -> Task 6; build/recovery/verification -> Task 7. Review clarifications map to Tasks 2, 3, 4 and 7. Protocol limits and notification limits above are implementation proposals to ratify alongside the draft, not measured guarantees. Security compatibility and packaging scope must be resolved before dependent code.
