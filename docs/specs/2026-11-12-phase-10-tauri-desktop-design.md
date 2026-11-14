# Phase 10 — Tauri desktop shell

Date: 2026-11-12
Status: Seven section-10 decisions settled on 2026-11-12 by agent selection explicitly delegated by the owner. Product implementation is in progress; see the dated report and acceptance checklist.
Scope: Windows-first desktop integration; source-development delivery.

## 1. Intent and baseline

Provide one desktop entry point to the existing DeClaw gateway and EN/FR web UI, with reliable core ownership, native tray, notifications and workspace selection. Preserve the Python application as the sole owner of model execution, tools, approvals, indexing and audit.

Baseline integrated for implementation: reviewed planning decisions were preserved
in `06d3551`, then Phase 9 maintenance `3f1d803` was merged into `feat/phase-10`
by `e3bac04`. Planning commit `ecc615a` and repair base `110e9e7` remain in
history. The merge retained both documentation indexes; no reset or remote
publication was used. See the [implementation report](../history/phase-10-implementation-2026-11-13.md)
and [acceptance checklist](../phase-10-review.md) for current evidence and gaps.

The earlier Phase 9 Python/Node checks and owner visual feedback are dated
evidence, not completion of authenticated real-browser acceptance. M1 must run
the relevant open [browser checklist](../phase-9-review.md) inside WebView2 too.

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
| Notifications | quarantine sinks and ApprovalBroker emitters exist, but `/ws/events` is not a native-notice bus | Add optional authoritative notice seams; do not scrape logs or replace audit sinks |
| Persistence | Task rows have turn IDs; current code does not associate every write with a desktop launch | Recovery must identify owned work before altering persisted tasks/index state |

Relevant regression anchors: tests/gateway/test_launch.py, test_auth_flow.py, test_host_origin.py, test_chat_flow.py, test_events_ws.py, tests/unit/test_app_lifecycle.py and tests/gateway/ui-behavior.test.cjs. These were inspected as source where relevant, not executed for this documentation task.

## 2. Scope and ticket reconciliation

| Ticket | Phase 10 disposition and acceptance |
| --- | --- |
| DCL-140 | Tauri 2 application opens a local loading/error surface and gateway webview |
| DCL-141 | Own, supervise and stop Python and its plugin descendants; no orphan after quit or desktop crash |
| DCL-142 | Load only http://127.0.0.1:7842 after owned-instance readiness; first launch has bounded failure handling |
| DCL-143 | Tray Open, Start, Stop, Restart, Status and Quit reflect actual supervisor state |
| DCL-144 | Native quarantine and pending-approval notices; installed Windows identity/activation is deferred to Phase 14; Phase 10 covers safe event wiring and in-app fallback, with this ticket remaining open |
| DCL-145 | Native directory picker supplies an absolute candidate workspace path to existing settings validation |
| DCL-146 | Document signed, explicit opt-in update contract; shipping updater deferred to packaging gate |
| DCL-147 | Installer feasibility and prerequisite inventory only; clean-machine MSI acceptance remains a Phase 14 release gate |
| DCL-148/149 | macOS/Linux distribution deferred; no platform support claim from a Windows build |
| DCL-150 | Signing research and key-management requirements; no published signed release required by this phase |

The DCL-146..150 disposition is settled by section 10 decision 6: Phase 10 delivers research/documentation, while release acceptance remains at Phase 14. Do not mark those tickets complete on this basis. Record the release-boundary dossier described in section 8 even when shipping those features is deferred.

Excluded: OS-bridge tools, shell execution, frontend rewrite, model downloads, auto-start at login, public network listener, automatic updates and installer delivery. Docker is not a prerequisite for this shell-free desktop scope.

## 3. Alternatives and recommendation

1. Thin Tauri shell loading the existing gateway UI: preserves one UI and its same-origin contracts; requires careful native capability isolation. Recommended.
2. Bundle a second frontend served from a Tauri origin: easier local bootstrap but changes gateway Origin/CSP and duplicates asset deployment. Not selected.
3. Open the system browser from a tray process: smallest native surface but does not fulfill the requested desktop webview experience.

The thin shell is selected under the owner-delegated decision in section 10. First implementation milestone must prove that the supported WebView2 runtime preserves the existing cookie, HTTP, WebSocket and CSP behavior without weakening middleware.

## 4. Process ownership and state machine

Rust owns a single supervised core instance. Use an explicitly resolved Python executable and argv list with a fixed module entry point; never shell interpolation, arbitrary executable paths from web content, or process-name based termination. Development resolves the repository virtual environment. Release executable resolution belongs to Phase 14.

States: STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED. Startup failure or unexpected exit enters FAILED. Start is allowed only from STOPPED/FAILED after cleanup; concurrent starts coalesce. Restart serializes stop then start. Quit exits after cleanup. Closing the window hides it to tray, with a first-use EN/FR explanation; explicit Quit terminates the owned core.

Use single-instance coordination per OS user. A second launch focuses the existing desktop and exits. A busy port without verified ownership is an actionable conflict: never attach automatically or kill the listener. Do not change ports silently.

Windows must place the core and descendants in an owned Job Object with kill-on-close semantics, with assignment before child execution can escape supervision. Assignment failure aborts startup. Use process handles, not reusable PIDs, for termination. An inherited private control channel carries typed lifecycle messages; EOF causes graceful core shutdown. Keep stdout/stderr drained with bounded, redacted diagnostics. Do not enable breakaway, inherit the Job handle, or give plugins control-channel/listener handles. Job Objects supervise descendants; they are not an OS sandbox or a barrier against a compromised same-user process.

State transitions run through a serialized supervisor actor; UI/tray callbacks
enqueue actions without blocking the GUI thread. Retrying STARTING, STOPPING or
an incompletely cleaned FAILED launch cannot start another child. Readiness,
exit and native requests are tied to a launch generation; late events from an
older generation cannot change the current state or regain command access.

Selected policy budgets: startup 30 seconds, graceful shutdown 10 seconds, forced cleanup 5 seconds, measured with monotonic deadlines. Surface timeout and retry explicitly; do not loop automatic restarts. These are testable policy defaults, not measured performance guarantees. Stop must cancel turns, deny pending approvals and run the existing Application teardown. Forced termination is reported as unclean. Do not assume current services automatically recover interrupted tasks or index batches: Task 7 must establish an ownership-scoped recovery contract. Never blanket-fail all RUNNING tasks, erase index state or replay tools/approvals; unrelated CLI work may share the data directory. If recovery requires schema or durable-ownership changes, obtain that architecture decision before implementing them.

## 5. Readiness and authentication

Add a desktop-specific Python entry point around the existing gateway/Application, leaving ordinary CLI behavior intact. Enforce host AND port for desktop: reject settings other than `127.0.0.1:7842` with an actionable error, without silently overriding them or restricting the ordinary CLI's configurable port. The child must exclusively reserve the listener before starting Application services (which may initiate indexing), then pass the owned socket into the async server seam. A losing bind cannot start plugins/indexing or kill/attach to the winning listener. Ready requires completed lifespan startup and a serving owned listener; an after-start probe alone is insufficient proof of identity.

Private IPC contract: UTF-8 JSON lines, version exactly 1, a fresh UUID
launch_id, exact allowed fields, strict scalar types and direction-specific
frames; reject booleans as integer fields. Bound the accumulated bytes before
decoding (16 KiB including newline); reject invalid UTF-8, oversized/partial EOF,
duplicate Ready, wrong direction/version/generation and unknown variants with
fixed safe error codes. Parent frames: Stop and RequestBootstrapToken(request_id).
Child frames: Ready(authority), Failure(code), Stopped(clean),
Notice(event_id, kind, language: en|fr, task_id optional, request_id optional).
Kinds are exactly quarantine|approval_pending; IDs are canonical UUID strings
and authority is exactly `127.0.0.1:7842`. A Stopped frame is
not proof all descendants exited; Rust must confirm process/Job cleanup.

Credential replies use a separate inherited private pipe, not the general event
queue: one BootstrapToken(version, launch_id, request_id, token) response for an
explicit local bootstrap request, bounded to 4 KiB including newline. The reply
cannot be forwarded to gateway content or logged even on parse errors. Correlate
and close/cancel the request on launch exit or view dismissal; clear transient
display/secret buffers. A launch_id is a correlation value, not a credential or
a substitute for private endpoint ownership. These protocol constraints form the selected parent/child-channel contract in section 10.

The selected first scope retains paste-once token login. A trusted local bootstrap surface may show the token obtained through the private channel on explicit user action; it must not persist it or copy it automatically. Do not parse ordinary CLI console logs for credentials. Browser login still uses the existing endpoint and HttpOnly cookie. Suppress ordinary token console output in desktop mode. Resolve the existing vault/encrypted fallback once and inject that same SecretStore into token bootstrap AND gateway auth; do not mint against one store while login reads another. The stored token is persistent; the private transfer/display is transient and must not be described as token rotation or token expiry.

No token in URLs, command-line arguments, environment variables, audit payloads, diagnostics or localStorage. The persistent gateway token must not be exposed by a generic webview command. Automatic cookie bootstrap is a separate security decision and is not assumed approved here.

After core restart, show reconnection/login as necessary; do not replay chat requests or approvals. Ollama unavailable or model missing produces a usable status/settings view, not a failed desktop launch.

## 6. Native boundary

The gateway webview loads only the exact loopback origin. Block unexpected navigation, new windows and remote redirects; a remote page must never inherit native commands. The trusted loading/error surface has separate minimal capabilities. Disable production developer tooling unless explicitly enabled for development.

Native commands are a closed typed set, scoped to the intended window and allowed origin. No generic shell, filesystem, HTTP proxy, credential getter or arbitrary process launcher. Keep gateway CSP and sanitizer behavior intact. Selected privilege matrix:

| Surface | Native exposure |
| --- | --- |
| Bundled bootstrap window | Local-only lifecycle/status and explicit bootstrap-token request/display; never available from the remote gateway |
| Gateway window at exact loopback origin | Only the directory-picker command after owned readiness; no lifecycle, credentials, notification-send or generic plugin APIs |
| Tray/native backend | Calls the supervisor directly; does not trust JS events as lifecycle/notice authority |
| Unexpected URL/window/generation | Deny all application commands |

Tauri documents permissive defaults for registered application commands and
merged capability grants. Explicitly list enabled capabilities, use
AppManifest command permissions and a narrow remote-URL rule for the gateway;
avoid default/wildcard capability overlap. Validate caller window, URL, current
launch generation and owned-process liveness in native handlers as well. M1
must prove the exact IPC transport under existing gateway CSP; an origin/CSP
exception is not an implementation workaround. See [Tauri capabilities](https://v2.tauri.app/security/capabilities/).

On child exit, mark the launch lease invalid synchronously and reject commands,
then close/destroy the gateway webview. The actor must receive the generation-specific destruction acknowledgement before another launch; a scheduling/destruction error or five-second acknowledgement timeout remains failed and denies retry until destruction is confirmed. Native gateway labels encode the creation generation (`gateway-<generation>`), so a stale window cannot claim a newer generation through a JS argument. Do not assume Tauri exposes a generic
dynamic capability-revocation operation. Recreate the webview only after a newly
owned launch becomes ready; a replacement process listening on the same URL must
never inherit native access.

Directory picker is user initiated and returns a path or cancellation. Selection alone grants no read access and performs no indexing. Save continues through the existing settings endpoint, containment/path validation and restart-required feedback. A file outside the workspace cannot become a tool-readable file merely because a native picker selected it. Browser-only settings continue working without native APIs. The current browser UI has a text path field, not a file-input picker. Successful save may create the candidate directory under existing validation; only restart changes the active tool workspace. Environment overrides remain authoritative and must be reflected in feedback.

## 7. Notifications and audit

Wire authoritative quarantine and approval-pending events from Python to the owned native supervisor through the private channel. Do not accept arbitrary notification text from documents or webview callers. Include event identifier, event kind and safe task reference; render localized fixed text without document contents, filenames or credentials. Deduplicate by identifier and bound queues/rate; notification loss never affects approval state.

For the deferred native activation acceptance, clicking first focuses the existing gateway window without reload, navigation or
opening another chat socket. The current Chat mount replaces its connection;
remounting could cancel the very approval referenced by a notice. Route/focus
integration must retain the existing socket, pending turn and modal, or show a
localized stale/unavailable message without fabricating a prompt. Cross-session
or expired request IDs cannot approve or replay tools. Quarantine has no dedicated
viewer in the existing UI: use existing Audit navigation only when it preserves
live chat state, otherwise focus the window with safe fixed feedback. Do not add
an unplanned quarantine viewer. OS denial is nonfatal and keeps in-app feedback.

Known Windows scope conflict: official notification-plugin guidance associates
normal Windows behavior with installed applications and identifies development
identity limitations. Thus source execution does not establish branded toasts
or activation callbacks. Decision 7 defers installed identity/activation acceptance to Phase 14;
Phase 10 implements safe event wiring and retains in-app feedback; do not mark the ticket complete using a development toast or silently
install/register software. See [Tauri notifications](https://v2.tauri.app/plugin/notification/).

Selected notice delivery limits: queue 64, 5 notices per minute, most recent 256
event IDs for deduplication, using monotonic time. Use existing quarantine ID and
approval request ID as opaque references; do not send preview/args, file paths,
content or exception text. Language is the effective SettingsService en/fr value,
never arbitrary message text. Dedup keys include launch_id, kind and event_id.
Creation/loss of a native notice never changes
broker state. Nonblocking notice hooks must be isolated from audit persistence,
tool execution and the priority lifecycle channel.

Preserve existing audit events and task correlation. Add documented desktop lifecycle/notification outcomes without secrets or sensitive paths. Bootstrap failures before DB availability use redacted operational diagnostics, not fabricated persisted audit claims.

## 8. Build and delivery

Keep Rust sources, capabilities, config and icons under tauri/. Preserve vanilla ui/ assets and EN/FR key parity. Commit exact dependency resolutions during implementation. Development documentation must state Rust/MSVC/WebView2 and Python/uv prerequisites and how to run the source application.

Pin the Rust toolchain, Tauri CLI/crates and plugin versions together after M1;
record their Windows/MSRV prerequisites. Prefer the Cargo CLI and existing static
assets; do not assume an npm frontend build exists. Record crate features,
tauri.conf locations, capabilities/permissions and the exact source-run command.
Source validation uses a non-bundling build; installer-producing validation
requires the separate scope approval above. Keep native UI callbacks responsive.

Produce a release-boundary dossier covering DCL-146..150: updater disabled until
opt-in/signed-channel approval, Python/UI/migration/plugin delivery, WebView2
prerequisites, MSI feasibility, signing/key custody, data retention/uninstall,
platform test requirements and remaining acceptance owners. This is documentation,
not a substitute for installer/update/signing acceptance or ticket completion.

Phase 14 must solve Python distribution, migrations, builtin plugin assets, ui/ discovery, WebView2 provisioning, signing, uninstall/data retention and update rollback. No MSI is acceptable merely because it installs a shell that cannot find its Python core. Update checks must remain disabled until explicit opt-in and a signed release channel exists; signing keys never enter the repository or application bundle.

## 9. Verification and milestones

M1: Apply the settled decisions and establish a committed Phase 9 baseline; prove the Tauri/webview security compatibility spike.
M2: Implement supervisor and private lifecycle protocol with failure tests before security-critical code.
M3: Integrate readiness, login, retry and recovery views; retain browser regression coverage.
M4: Add tray, picker and native event delivery with EN/FR behavior.
M5: Run Windows process-level acceptance, record dated results and update code map, status and ticket evidence.

Required tests:

- Concurrent starts, duplicate desktop launches, port conflict, wrong-instance readiness and malformed/oversized control frames fail safely.
- Quit during startup, indexing, chat and pending approval; child crash, desktop crash and hanging shutdown leave no owned descendants.
- Unrelated Python processes and pre-existing gateway listeners remain untouched.
- Denied navigation/origin cannot invoke native commands; rejected auth and CSP behavior remain unchanged.
- No secret in logs, URLs, argv, environment, browser storage or diagnostics;
  persistent credentials remain in the approved vault/encrypted fallback. Tests
  use fake credentials and cover control-pipe errors and hostile stdout/stderr.
- Missing Ollama, absent model, denied notifications, picker cancellation and invalid workspace all remain recoverable.
- Native notifications never approve actions; restart never replays a pending tool.
- Windows manual checks cover hide/show, tray Quit, first-run login, restart, high DPI, keyboard access and EN/FR.

Python checks: uv sync --frozen; uv run ruff check .; uv run mypy declaw declaw_plugin_sdk; uv run pytest. Run existing Node UI regressions, Rust formatting/lint/unit checks and Windows desktop build once those targets exist. Process-level Windows tests are required in addition to mocked unit tests. Record skips and platform limitations explicitly.

## 10. Settled decisions ? 2026-11-12

The owner explicitly delegated selection of all seven decisions ("ch?t h? t?i
7 quy?t ??nh trong spec"). The following are agent-selected decisions under
that delegation, not a claim that the owner individually chose each alternative.
This settles architecture/scope for planning; it does not claim implementation,
verification, installation or publication.

| # | Selected decision | Rationale and boundary |
| --- | --- | --- |
| 1 | Thin Tauri 2 shell using the existing gateway UI at exactly `127.0.0.1:7842`. | Preserve one EN/FR UI and existing authentication/CSP. Reject a second frontend or browser-only shell; M1 must verify WebView2 compatibility without weakening security. |
| 2 | Desktop owns one core; an existing listener is a conflict. | Ownership and teardown stay provable. Never attach to or kill an unknown listener, or silently select another port. |
| 3 | Windows Job Object plus bounded typed private parent/child channels. | Supervise descendants with kill-on-close and cooperative shutdown; no HTTP shutdown endpoint. Preserve the separate credential pipe and native privilege matrix. This is not a shell sandbox. |
| 4 | Paste-once token login through explicit trusted-bootstrap reveal. | Reuse gateway authentication and the same approved SecretStore; no automatic cookie bootstrap, token logging or automatic clipboard copy. Automatic login is deferred. |
| 5 | Window close hides to tray; explicit Quit stops all owned descendants. | Keep background work available with a first-use EN/FR explanation. Quit uses bounded cooperative shutdown followed by owned-process cleanup. |
| 6 | Source-development Windows delivery in Phase 10; release acceptance for DCL-146..150 stays at Phase 14. | Deliver the release-boundary dossier now. Installer, updater, distribution and signing tickets remain open until their actual release criteria pass. |
| 7 | Defer installed Windows native-notification identity/activation acceptance to Phase 14. | Phase 10 implements safe event wiring and bounded dispatch, retaining in-app feedback. Native click activation/focus acceptance is deferred with installed delivery to Phase 14. No installation/registration is authorized by this decision. DCL-144 remains open; development toasts and mocks cannot satisfy installed acceptance. |

All seven decisions are settled. Phase 9 maintenance is integrated; the open M1 compatibility checks remain
acceptance prerequisites. Later recovery evidence may require
an additional scoped architecture decision before persistence changes; these
seven decisions do not authorize a new durable ownership schema. Routine module
names and test organization can follow repository conventions.

## References

- [Current status](../project-status.md)
- [Code map](../code-map.md)
- [Active decisions](../architecture-decisions.md)
- [Phase 9 design](2026-11-08-phase-9-gateway-web-ui-design.md)
- [Ticket ledger](../../TICKETS.md)
- [Tauri capabilities](https://v2.tauri.app/security/capabilities/) — consulted 2026-11-12; remote/native boundary requires explicit review.
- [Tauri Windows distribution](https://v2.tauri.app/distribute/windows-installer/) — consulted 2026-11-12; installer generation is separate from packaging the core.
- [Tauri notifications](https://v2.tauri.app/plugin/notification/) — rechecked 2026-11-12; Windows installation/development limitations make notification scope a gate.
- [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) — rechecked 2026-11-12; descendant ownership, breakaway and kill-on-close are process-management concerns, not sandboxing.

## Review clarifications

- The 2026-11-14 usability repairs retain one live Chat view/socket across in-app navigation. New conversation explicitly opens a fresh session without replay, including after connection loss; model/language snapshots apply there. Auth loss discards retained private UI state. This is in-memory continuity, not durable recovery.
- Audit exports use the existing authenticated same-origin endpoint with typed attachment filenames. The UI preflights auth/errors then offers an explicit Save link. A native browser-download handler accepts only the live gateway view/generation and exact audit-export URL, uses the browser-chosen absolute destination and refuses existing files. Fixed boolean-only completion feedback distinguishes prepared, completed and failed downloads. No new remote IPC command or origin/popup grant is added. See [repair evidence](../history/phase-10-usability-repairs-2026-11-14.md).

- On owned gateway exit, invalidate native command access through the launch lease and destroy its webview as specified in section 6. Do not reconnect until a new owned process completes readiness. Origin matching alone cannot authenticate a replacement listener on the same port.
- Unexpected event-channel EOF invalidates readiness even while the child is alive; only an acknowledged explicit clean Stop may drain EOF before process exit. Control writes use a bounded private writer with a deadline, and cleanup cancels and joins that writer before releasing ownership. Service/server failures do not skip later cooperative cleanup within the shared shutdown budget.
- A gateway WebView creation failure leaves the healthy core running and exposes a fixed EN/FR diagnostic in the trusted bootstrap. Start/Open retries the same live generation on the GUI thread through existing privileges; it does not grant remote commands or restart the core. See [architecture repair evidence](../history/phase-10-architecture-repairs-2026-11-14.md).
- Inherit control handles only into the intended Python child using an explicit handle allowlist. Close unused endpoints, prevent plugin descendants from inheriting them, and never inherit the Job Object handle. Test EOF and forged-event resistance with a descendant process.
- Graceful teardown is guaranteed only on cooperative normal stop/quit within the budget. Desktop crash or forced Job Object cleanup guarantees process termination, not flushed audit records or completed Application.shutdown.
- Crash recovery is an implementation investigation requirement, not a claim about current services. Trace persisted task states, audit writes and partial indexing; define and test recovery for each interrupted state before acceptance.
- M1 records source-mode notification limitations; installed identity/activation checks are deferred to Phase 14 under decision 7. Developer-mode output cannot establish installed-app acceptance. Leave DCL-144 open until that acceptance is verified.
