# Phase 10 — Tauri desktop shell

Date: 2026-11-12
Status: DRAFT for owner review. No architecture choice below is ratified by this document.
Scope: Windows-first desktop integration; source-development delivery.

## 1. Intent and baseline

Provide one desktop entry point to the existing DeClaw gateway and EN/FR web UI, with reliable core ownership, native tray, notifications and workspace selection. Preserve the Python application as the sole owner of model execution, tools, approvals, indexing and audit.

This review covers the current Phase 9 working tree, including uncommitted repairs, rather than claiming those repairs exist on main. Local main was 61947f6 and the checked-out Phase 9 branch was afc5cf2 at inspection. Creating feat/phase-10 was denied by filesystem permissions; no branch or merge is implied here. Before implementation, integrate and validate the intended Phase 9 baseline, then create the requested branch from main. Do not silently carry uncommitted changes across branches.

Evidence:

| Boundary | Observed implementation | Consequence |
| --- | --- | --- |
| Desktop | tauri/src-tauri/src and tauri/icons contain placeholders | Rust application, configuration and capabilities are new work |
| Launcher | declaw/gateway/app.py asserts exactly 127.0.0.1 and runs foreground uvicorn | Desktop must reuse the launch restriction |
| Lifecycle | declaw/app.py owns services and ordered shutdown hooks | Desktop shutdown must reach Application.shutdown before escalation |
| Authentication | declaw/gateway/auth.py and routes/auth.py implement token login and session cookies | A webview is not automatically authenticated |
| Browser boundary | middleware.py enforces exact Host/Origin and CSP | Do not add wildcard origins to make Tauri work |
| Status | routes/status.py requires a session and has bounded Ollama probing | Status is not an anonymous readiness endpoint; missing Ollama is not gateway failure |
| Events | events.py provides authenticated bounded queues for indexing/plugin events | Native quarantine/approval notifications need explicit additional wiring |
| Settings | ui/js/settings.js edits model, language and workspace; workspace needs restart | Native picker feeds the same validated settings flow |
| Assets | UI_DIR resolves ui/ relative to source checkout | A desktop build alone does not package Python, UI or migrations |

Relevant regression anchors: tests/gateway/test_launch.py, test_auth_flow.py, test_host_origin.py, test_chat_flow.py, test_events_ws.py, tests/unit/test_app_lifecycle.py and tests/gateway/ui-behavior.test.cjs. These were inspected as source where relevant, not executed for this documentation task.

## 2. Scope and ticket reconciliation

| Ticket | Phase 10 disposition and acceptance |
| --- | --- |
| DCL-140 | Tauri 2 application opens a local loading/error surface and gateway webview |
| DCL-141 | Own, supervise and stop Python and its plugin descendants; no orphan after quit or desktop crash |
| DCL-142 | Load only http://127.0.0.1:7842 after owned-instance readiness; first launch has bounded failure handling |
| DCL-143 | Tray Open, Start, Stop, Restart, Status and Quit reflect actual supervisor state |
| DCL-144 | Native quarantine and pending-approval notices; clicking opens the UI and never approves a tool |
| DCL-145 | Native directory picker supplies an absolute candidate workspace path to existing settings validation |
| DCL-146 | Document signed, explicit opt-in update contract; shipping updater deferred to packaging gate |
| DCL-147 | Installer feasibility and prerequisite inventory only; clean-machine MSI acceptance remains a Phase 14 release gate |
| DCL-148/149 | macOS/Linux distribution deferred; no platform support claim from a Windows build |
| DCL-150 | Signing research and key-management requirements; no published signed release required by this phase |

The DCL-146..150 disposition is a proposed reconciliation of the historical backlog with the active Phase 14 packaging decision. Do not mark those tickets complete on this basis. Owner confirmation is required before changing their scope in TICKETS.md.

Excluded: OS-bridge tools, shell execution, frontend rewrite, model downloads, auto-start at login, public network listener, automatic updates and installer delivery. Docker is not a prerequisite for this shell-free desktop scope.

## 3. Alternatives and recommendation

1. Thin Tauri shell loading the existing gateway UI: preserves one UI and its same-origin contracts; requires careful native capability isolation. Recommended.
2. Bundle a second frontend served from a Tauri origin: easier local bootstrap but changes gateway Origin/CSP and duplicates asset deployment. Not selected for this draft.
3. Open the system browser from a tray process: smallest native surface but does not fulfill the requested desktop webview experience.

The recommendation is an author proposal, not an owner decision. First implementation milestone must prove that the supported WebView2 runtime preserves the existing cookie, HTTP, WebSocket and CSP behavior without weakening middleware.

## 4. Process ownership and state machine

Rust owns a single supervised core instance. Use an explicitly resolved Python executable and argv list with a fixed module entry point; never shell interpolation, arbitrary executable paths from web content, or process-name based termination. Development resolves the repository virtual environment. Release executable resolution belongs to Phase 14.

States: STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED. Startup failure or unexpected exit enters FAILED. Start is allowed only from STOPPED/FAILED after cleanup; concurrent starts coalesce. Restart serializes stop then start. Quit exits after cleanup. Closing the window hides it to tray, with a first-use EN/FR explanation; explicit Quit terminates the owned core.

Use single-instance coordination per OS user. A second launch focuses the existing desktop and exits. A busy port without verified ownership is an actionable conflict: never attach automatically or kill the listener. Do not change ports silently.

Windows must place the core and descendants in an owned Job Object with kill-on-close semantics, with assignment before child execution can escape supervision. Assignment failure aborts startup. Use process handles, not reusable PIDs, for termination. An inherited private control channel carries typed lifecycle messages; EOF causes graceful core shutdown. Keep stdout/stderr drained with bounded, redacted diagnostics.

Proposed budgets: startup 30 seconds, graceful shutdown 10 seconds, forced cleanup 5 seconds. Surface timeout and retry explicitly; do not loop automatic restarts. These are testable policy defaults, not measured performance guarantees. Stop must cancel turns, deny pending approvals and run the existing Application teardown. Forced termination is reported as unclean; subsequent startup reconciles persisted state using existing services.

## 5. Readiness and authentication

Add a desktop-specific Python entry point around the existing gateway/Application, leaving ordinary CLI behavior intact. The private channel uses versioned, size-bounded messages with launch identifier and explicit ready/error/stopped types. Ready requires successful Application startup and a bound listener. A TCP connection or arbitrary HTTP 200 is insufficient proof of identity.

Recommended first scope retains paste-once token login. A trusted local bootstrap surface may show the token obtained through the private channel on explicit user action; it must not persist it or copy it automatically. Do not parse ordinary CLI console logs for credentials. Browser login still uses the existing endpoint and HttpOnly cookie. Suppress ordinary token console output in desktop mode. Store credentials only through the existing vault/encrypted fallback.

No token in URLs, command-line arguments, environment variables, audit payloads, diagnostics or localStorage. The persistent gateway token must not be exposed by a generic webview command. Automatic cookie bootstrap is a separate security decision and is not assumed approved here.

After core restart, show reconnection/login as necessary; do not replay chat requests or approvals. Ollama unavailable or model missing produces a usable status/settings view, not a failed desktop launch.

## 6. Native boundary

The gateway webview loads only the exact loopback origin. Block unexpected navigation, new windows and remote redirects; a remote page must never inherit native commands. The trusted loading/error surface has separate minimal capabilities. Disable production developer tooling unless explicitly enabled for development.

Native commands are a closed typed set, scoped to the intended window and allowed origin. No generic shell, filesystem, HTTP proxy, credential getter or arbitrary process launcher. Verify custom command authorization explicitly; do not assume registering a command makes it restricted. Keep gateway CSP and sanitizer behavior intact.

Directory picker is user initiated and returns a path or cancellation. Selection alone grants no read access and performs no indexing. Save continues through the existing settings endpoint, containment/path validation and restart-required feedback. A file outside the workspace cannot become a tool-readable file merely because a native picker selected it. Browser-only settings continue working without native APIs.

## 7. Notifications and audit

Wire authoritative quarantine and approval-pending events from Python to the owned native supervisor through the private channel. Do not accept arbitrary notification text from documents or webview callers. Include event identifier, event kind and safe task reference; render localized fixed text without document contents, filenames or credentials. Deduplicate by identifier and bound queues/rate; notification loss never affects approval state.

Clicking focuses the corresponding UI where possible; stale references open the relevant page with an expired-state explanation. Approvals remain in the existing broker, default deny, with original timeouts. OS notification permission refusal is nonfatal and leaves in-app feedback available.

Preserve existing audit events and task correlation. Add documented desktop lifecycle/notification outcomes without secrets or sensitive paths. Bootstrap failures before DB availability use redacted operational diagnostics, not fabricated persisted audit claims.

## 8. Build and delivery

Keep Rust sources, capabilities, config and icons under tauri/. Preserve vanilla ui/ assets and EN/FR key parity. Commit exact dependency resolutions during implementation. Development documentation must state Rust/MSVC/WebView2 and Python/uv prerequisites and how to run the source application.

Phase 14 must solve Python distribution, migrations, builtin plugin assets, ui/ discovery, WebView2 provisioning, signing, uninstall/data retention and update rollback. No MSI is acceptable merely because it installs a shell that cannot find its Python core. Update checks must remain disabled until explicit opt-in and a signed release channel exists; signing keys never enter the repository or application bundle.

## 9. Verification and milestones

M1: Ratify decisions and establish a committed Phase 9 baseline; prove the Tauri/webview security compatibility spike.
M2: Implement supervisor and private lifecycle protocol with failure tests before security-critical code.
M3: Integrate readiness, login, retry and recovery views; retain browser regression coverage.
M4: Add tray, picker and native event delivery with EN/FR behavior.
M5: Run Windows process-level acceptance, record dated results and update code map, status and ticket evidence.

Required tests:

- Concurrent starts, duplicate desktop launches, port conflict, wrong-instance readiness and malformed/oversized control frames fail safely.
- Quit during startup, indexing, chat and pending approval; child crash, desktop crash and hanging shutdown leave no owned descendants.
- Unrelated Python processes and pre-existing gateway listeners remain untouched.
- Denied navigation/origin cannot invoke native commands; rejected auth and CSP behavior remain unchanged.
- No secret in logs, URLs, argv, environment, storage or diagnostics; tests use fake credentials.
- Missing Ollama, absent model, denied notifications, picker cancellation and invalid workspace all remain recoverable.
- Native notifications never approve actions; restart never replays a pending tool.
- Windows manual checks cover hide/show, tray Quit, first-run login, restart, high DPI, keyboard access and EN/FR.

Python checks: uv sync --frozen; uv run ruff check .; uv run mypy declaw declaw_plugin_sdk; uv run pytest. Run existing Node UI regressions, Rust formatting/lint/unit checks and Windows desktop build once those targets exist. Process-level Windows tests are required in addition to mocked unit tests. Record skips and platform limitations explicitly.

## 10. Decisions requiring owner ratification

1. Thin Tauri shell using existing gateway UI and exact 127.0.0.1:7842 authority.
2. Desktop owns its core; existing listeners cause conflict rather than automatic attachment.
3. Windows Job Object plus private parent/child control channel; no HTTP shutdown endpoint added.
4. Paste-once login via trusted bootstrap surface for initial scope; automatic login deferred.
5. Window close hides to tray; Quit stops owned descendants.
6. DCL-146..150 packaging/signing acceptance stays at Phase 14; Phase 10 delivers source-development desktop.

Implementation must wait for resolution of these security/architecture choices. Routine module names and test organization can follow repository conventions after approval.

## References

- [Current status](../project-status.md)
- [Code map](../code-map.md)
- [Active decisions](../architecture-decisions.md)
- [Phase 9 design](2026-11-08-phase-9-gateway-web-ui-design.md)
- [Ticket ledger](../../TICKETS.md)
- [Tauri capabilities](https://v2.tauri.app/security/capabilities/) — consulted 2026-11-12; remote/native boundary requires explicit review.
- [Tauri Windows distribution](https://v2.tauri.app/distribute/windows-installer/) — consulted 2026-11-12; installer generation is separate from packaging the core.

## Review clarifications

- When the owned gateway exits, immediately unload its webview and revoke native command access. Do not reload or reconnect to the loopback address until a newly owned process completes readiness. Origin matching alone cannot authenticate a replacement listener on the same port.
- Inherit control handles only into the intended Python child using an explicit handle allowlist. Close unused endpoints, prevent plugin descendants from inheriting them, and never inherit the Job Object handle. Test EOF and forged-event resistance with a descendant process.
- Graceful teardown is guaranteed only on cooperative normal stop/quit within the budget. Desktop crash or forced Job Object cleanup guarantees process termination, not flushed audit records or completed Application.shutdown.
- Crash recovery is an implementation investigation requirement, not a claim about current services. Trace persisted task states, audit writes and partial indexing; define and test recovery for each interrupted state before acceptance.
- M1 includes a Windows native-notification spike: verify application identity/registration, permission handling and activation callbacks for the source-development build. If supported notification behavior requires installer registration, record the concrete limitation and obtain a scope decision before marking DCL-144 complete.
