# Phase 9 — Gateway & Web UI: Design

> **Ratified design record** (2026-11-08): all twelve section-20 decisions
> were ratified as proposed, and the phase was implemented on
> `feat/phase-9-gateway-web-ui` following sections 1-17 (milestones M1-M5).
> Wiring evidence: [Phase 9 baseline](../history/phase-9-baseline-2026-11-08.md),
> [manual UI checklist](../phase-9-review.md), [code map](../code-map.md).
> Limitations remain section 18 — honest limits, unchanged by implementation.

- **Date**: 2026-11-08
- **Status**: ratified (implemented on this branch; see the baseline report)
- **Tickets**: DCL-120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131,
  132, 133, 134, plus DCL-082 (permission experience)
- **Branch**: `feat/phase-9-gateway-web-ui` (from `main`, which carries Phases
  0–8b)
- **Context**: [roadmap](2026-08-23-phase-7-9-roadmap.md) (approved sketch and
  cross-phase decisions), [readiness assessment](../phase-9-readiness.md)
  (current-source gap list this spec answers)

## Goal

Give DeClaw a local browser UI by putting a loopback-only FastAPI gateway in
front of the *same* assembled services the CLI uses today — brain, typed tools,
sanitizer, confirmation, audit, plugin host, document stack — without
bypassing, duplicating, or weakening any of those wrappers.

Concretely, after this phase a user can: run `declaw start`, open
`http://127.0.0.1:7842`, authenticate, chat with streaming answers, approve or
deny tool calls from the browser, index and search documents, inspect the audit
trail, manage built-in plugins and their permission grants, change a small set
of settings, and see system status — in English or French, with no runtime CDN.

## Non-goals

- **Any non-loopback access.** No LAN, no tunnels, no multi-user. The threat
  model is drive-by web content, CSRF and DNS rebinding against a local
  server — not remote attackers and not local malware running as the user.
- **Third-party plugin install/uninstall/update** (roadmap decision 2). The
  plugin UI lists built-ins, enables/disables them, and shows/revokes grants.
- **Daemon/service management.** `declaw start` runs the gateway in the
  foreground; Ctrl-C stops it. `declaw stop`, auto-start, logs and update
  commands stay with DCL-234 (Phase 10+). See section 19 deltas.
- **File upload endpoints.** Documents enter through the workspace folder on
  disk; the gateway never accepts file bodies.
- **Durable chat history and reconnect-resume.** Chat history lives in memory
  per WebSocket connection. Task rows and audit events are durable; the
  conversation transcript is not (see *Honest limitations*).
- **Shell execution** of any kind (deferred; requires approved Docker
  isolation).
- **Packaging/installer work.** `ensure_schema` uses `create_all`, built-in
  plugins live outside the wheel. Phase 14 problems; recorded as limitations,
  not solved here.
- **Markdown rendering in the UI.** v0.1 renders model and document text as
  plain text. See section 13.

## Architecture

```
  browser (http://127.0.0.1:7842)            one Python process
  ---------------------------------    +--------------------------------------+
   index.html / app.js / local CSS     |  uvicorn (loopback only)             |
   locales/{en,fr}.json                |    FastAPI app                       |
        |  REST /api/*  (cookie auth)  |      middleware: Host, Origin,       |
        |  WS /ws/chat                 |                rate limit, body cap  |
        |  WS /ws/events               |      routes / ws handlers            |
        v                              |        |                             |
                                       |  SessionManager -- ApprovalBroker    |
                                       |        |          (Confirmation-     |
                                       |        |           Provider factory) |
                                       |  Application (new, declaw/app.py)    |
                                       |    brain per session -- ToolRegistry |
                                       |    sanitizer + quarantine            |
                                       |    PluginHost -- doc-intel subprocess|
                                       |    DocumentStack + DocumentWatcher   |
                                       |    DbAuditLogger -- SQLite           |
                                       |    EgressMonitor (one, app-owned)    |
                                       +--------------------------------------+
```

The HTTP layer never calls Typer commands, `asyncio.run`, console input or
Rich renderers. It talks to a new `Application` object that owns service
assembly and lifecycle; `declaw chat` is refactored to build on the same
object so the CLI and the gateway can never drift apart on safety wiring.

New/changed modules, each with one job:

| Module | Job |
| --- | --- |
| `declaw/app.py` | `Application`: assemble and own engine, audit, quarantine, sanitizer, plugin host, document stack, watcher, egress monitor, settings service. Deterministic start/stop. Shared by CLI and gateway. |
| `declaw/gateway/app.py` | FastAPI factory: middleware, routes, static UI, lifespan bound to `Application`. |
| `declaw/gateway/auth.py` | Token mint/rotate/verify, session cookie issue/validate, in-memory session registry. |
| `declaw/gateway/middleware.py` | Host allowlist, Origin policy, per-route rate limits, body size caps. |
| `declaw/gateway/schemas.py` | Pydantic request/response models for every route and WS message. |
| `declaw/gateway/sessions.py` | `SessionManager` / `GatewaySession`: per-connection chat state, turns, task IDs, cancellation. |
| `declaw/gateway/approvals.py` | `ApprovalBroker`: correlated, deadline-bound, disconnect-denying approval transport. |
| `declaw/gateway/routes/*.py` | `auth`, `status`, `tasks`, `audit`, `plugins`, `settings`, `documents`. |
| `declaw/gateway/ws.py` | `/ws/chat` and `/ws/events` handlers. |
| `declaw/settings_service.py` | Persistent, UI-mutable settings layered over env config. |
| `declaw/brain/streaming.py` | Token-streaming model callable that still returns a complete message. |
| `ui/` | `index.html`, `js/` modules, local CSS, `locales/en.json` + `fr.json`. |

## 1. Bind and launch contract (DCL-120)

The gateway binds inside the application process: `declaw start` builds the
`Application`, then runs uvicorn programmatically against the FastAPI app.

- **Bind host.** The readiness assessment flags a mismatch: the project
  invariant names `127.0.0.1:7842`, while `Settings._enforce_loopback` also
  accepts `localhost` and `::1` (`declaw/config.py`). Decision: the launch
  contract is **127.0.0.1 only**. `gateway/app.py` asserts
  `settings.host == "127.0.0.1"` at startup and refuses to bind anything else,
  independently of the settings validator (defense in depth: the check lives in
  the launcher, not only in config parsing). `localhost`/`::1` remain valid
  *settings* for future use but are not a launchable gateway configuration in
  v0.1. Negative test: `DECLAW_HOST=0.0.0.0` and a LAN IP both abort startup.
- **Port.** Default and expected value 7842. The port stays configurable via
  `DECLAW_PORT` (development convenience; `test_config.py` already exercises a
  non-default port) — port flexibility does not widen network exposure because
  the bind host is pinned. The Host-header allowlist (section 3) is derived
  from the actual bind authority.
- **Hardened uvicorn config.** No `--reload` in the shipped path, access log
  routed into loguru at DEBUG (it can carry query strings), `proxy_headers`
  off, `forwarded_allow_ips` unset — there is no proxy, ever.
- **`declaw stop`** stays unimplemented with a message pointing at Ctrl-C;
  daemon management is DCL-234. This is a deliberate delta from the ticket
  wording, recorded in section 19.

## 2. Authentication bootstrap (DCL-121)

The open question from the readiness assessment was: how does a browser obtain
the token without exposing it in URLs, logs or persisted frontend storage?

**Decision: paste-once login issuing an opaque session cookie.**

1. **Token.** On first gateway start, `auth.py` mints `secrets.token_urlsafe(32)`
   and stores it through the existing `SecretStore` abstraction
   (`declaw/credentials/store.py`) under the name `gateway-token`.
   `KNOWN_SECRET_NAMES` gains `gateway-token` so uninstall/purge covers it.
   The token is printed to the console on every `declaw start` (the user needs
   it to log in) and is never written to logs, audit events or HTTP responses.
   `declaw start --rotate-token` replaces it and invalidates all sessions.
2. **Login.** The UI's connect screen asks for the token once.
   `POST /api/auth/login {token}` verifies with `hmac.compare_digest`; on
   success the server mints an opaque session ID (`secrets.token_urlsafe(32)`),
   keeps it in an in-memory registry with an absolute expiry (12 h), and sets:
   `Set-Cookie: declaw_session=<id>; HttpOnly; SameSite=Strict; Path=/`.
   The gateway token itself is never stored in the browser — not in
   localStorage, not in sessionStorage, not in the cookie.
3. **Requests.** REST routes require a valid session cookie. WebSocket
   handshakes send cookies automatically, so the same check runs before
   `accept()`. `POST /api/auth/logout` drops the registry entry;
   `GET /api/auth/status` reports authenticated/not.
4. **No `Secure` flag** on the cookie: the scheme is plain HTTP on loopback.
   CSRF is carried by `SameSite=Strict` plus the Origin/Host policy of
   section 3. Recorded as a limitation.
5. **Audit.** A new `AuthEvent` (`gateway.auth`) records login success/failure
   and logout with no token material — Principle #7 extends to the new
   security boundary. Failed logins are rate-limited (section 4).

Alternative considered: putting the token in a first-run URL fragment
(`#token=...`). Rejected: fragments stay out of server logs but still land in
browser history and are one redirect away from leaking; a paste-once flow is
simpler to reason about and matches how the CLI already prints secrets to the
console (e.g. quarantine notices).

## 3. Origin and Host policy (DCL-122)

Defends the CVE-2026-25253 class (CSRF / DNS rebinding against loopback
services). Implemented as pure-ASGI middleware before routing.

- **Host:** the `Host` header must exactly match the bound authority
  (`127.0.0.1:<port>`). Anything else — foreign domains, other ports, missing
  host on HTTP/1.1 — gets `403`. A browser that resolved an attacker's domain
  to 127.0.0.1 sends that domain in `Host` and dies here.
- **Origin:** required on every non-GET/HEAD request and on every WebSocket
  handshake. It must equal `http://127.0.0.1:<port>`. Missing or `null` Origin
  on a state-changing request is `403` (fail closed). GET/HEAD are exempt:
  they are read-only, and `SameSite=Strict` already prevents cross-site
  credentialed reads.
- **WebSocket:** both checks run on the handshake; failures close with code
  4401 (unauthenticated) or 4403 (forbidden origin/host) before any application
  message flows.
- `Sec-Fetch-Site` cross-checking was considered and left out: modern browsers
  send it, but the Origin+Host pair already denies the attack classes above,
  and one policy surface is easier to test than two. Revisit if a concrete
  bypass appears.

## 4. Rate limits and body caps (DCL-123, DCL-124)

In-process token buckets, per route class, keyed by session (and globally for
unauthenticated endpoints). Constants live in `middleware.py`, documented in
one table:

| Scope | Limit | Response on exceed |
| --- | --- | --- |
| `POST /api/auth/login` | 5/minute | 429 + `Retry-After` (slows token brute force from local processes) |
| Chat turn start (`/ws/chat` message) | 10/minute per session | WS error frame |
| Other WS messages | 30/second per connection | WS error frame |
| Authenticated REST reads | 120/minute per session | 429 |
| Default JSON body | 64 KiB | 413 |
| `PUT /api/settings` | 16 KiB | 413 |

Enforcement details that make the caps real:

- **Byte counting happens before body buffering**, at ASGI receive level —
  including chunked requests with no `Content-Length`. A route that parses
  first and measures later has already lost.
- **WebSocket messages are capped too:** the application rejects any single
  WS message over 32 KiB and closes persistent violators with code `1009`
  (message too big); the server frame limit is set on the WS stack as well.
  Rate limits alone do not bound one oversized frame.
- There are no large legitimate bodies anywhere in this API — documents are
  indexed from disk, never uploaded (non-goal). If a future route needs a
  bigger cap, it gets an explicit per-route override in the same table.

## 5. Application service extraction

Before any route exists, `declaw/app.py` extracts what `main.chat` assembles
today into an `Application` with explicit lifecycle:

- **Owns:** engine/sessionmaker, `DbAuditLogger`, `QuarantineStore`,
  `Sanitizer` (when `sanitizer_required`), `PluginHost`, `DocumentStack`,
  `DocumentWatcher` (gateway mode only — CLI behavior unchanged), one
  process-wide `EgressMonitor`, the `SettingsService` (section 12), and the
  tool registry factory.
- **One event loop.** The readiness assessment is explicit: aiosqlite
  connections and asyncio subprocess transports bind to their creating loop.
  `Application.start()` runs on the uvicorn loop; `main.chat` keeps its single
  `asyncio.run` and builds the same object inside it.
- **Deterministic shutdown order:** stop accepting sessions → cancel in-flight
  turns → deny all pending approvals → stop watcher → `host.stop()` → uninstall
  egress monitor → dispose engine. Each step has a regression test.
- **Ollama health at startup.** The gateway starts and serves the status UI
  even when Ollama or a model is missing; chat turns then fail with a typed
  error the UI renders. This differs from `main.chat`'s hard exit on purpose:
  a web UI that refuses to start tells the user nothing.
- **CLI refactor.** `main.chat` becomes: build `Application` with console
  sinks (quarantine user-notice prints) and the console confirmation provider;
  run `run_chat`. Existing REPL/confirmation tests must pass unmodified.

The `EgressMonitor` gets exactly one owner (`Application`) with an explicit
uninstall on shutdown — the readiness assessment's "one application owner, a
shutdown policy, not one per request".

## 6. Sessions, turns and task IDs

- **Session = one authenticated `/ws/chat` connection, run as an actor.**
  Each connection gets a `GatewaySession` with its own message history, exactly
  **one active turn at a time** (a second message during a turn gets a typed
  `busy` error, not a queue), exactly **one bounded outbound queue** and
  **exactly one WebSocket writer**. Every frame — token deltas, tool events,
  approval requests, terminal frames, errors — goes through that queue, so
  ordering and backpressure have a single owner. Two browser tabs are two
  sessions with isolated histories; they share only stateless services (the
  registry's tools, the plugin host with its existing call-serialization lock).
- **Turn = one user message.** Each turn creates a `Task` row
  (`declaw/db/models.py`) whose `prompt` is the user text and whose `status`
  moves PENDING → RUNNING → COMPLETED/FAILED. On completion the final answer
  is stored in `Task.result`.
- **Task ID propagation.** Setting a `contextvars.ContextVar` is not enough on
  its own: today's emitters (`wrap_tool_with_audit`, the confirmation wrapper,
  the quarantine DB sink, `EgressMonitor`) construct events with no `task_id`,
  and `DbAuditLogger.emit` persists the frozen event as given. The mechanism is
  therefore a **task-aware audit decorator** (`TaskCorrelatingAuditLogger`)
  wrapping `DbAuditLogger`: at `emit` time it reads the contextvar and applies
  `model_copy(update={"task_id": ...})` to any event whose `task_id` is unset,
  preserving an explicit ID when present. Every gateway emitter shares this
  decorated logger, and async work scheduled from within a turn (the egress
  sync-bridge, quarantine sinks) runs in a copied context so the ID survives
  the handoff. The CLI keeps the undecorated logger: no contextvar is set, no
  behavior changes, existing tests pass. The new `AuthEvent` (section 2) is
  added to the closed `AnyAuditEvent` union in `declaw/audit/events.py`.
- **Episodes.** On task completion the session writes an `Episode` row linked
  by `task_id` (the roadmap explicitly lands this follow-up here). The summary
  is the final answer truncated to 500 characters with empty tags — no extra
  LLM call. This is population plumbing, not the memory-enhanced brain; the
  retrieval wrappers stay out of the default stack exactly as the project
  status warns.
- **Cancellation.** A client `cancel {turn_id}` message cancels the turn's
  asyncio task; `CancelledError` unwinds the graph, pending tool calls and any
  pending approval. The task row lands in FAILED with `error="cancelled by
  user"` — reusing the existing `TaskStatus` enum rather than adding a
  migration for CANCELLED. Flagged in section 20.
- **Disconnect** cancels the in-flight turn and denies that session's pending
  approvals (section 7).

## 7. Approval transport

The reusable piece is `ConfirmationProvider`
(`declaw/tools/confirmation.py`); the console implementation is not reusable.
New: `ApprovalBroker`.

1. A non-READ tool call inside a turn hits the confirmation wrapper, whose
   `approve` is a broker-generated provider bound to the calling session.
   **Validate before prompt:** today the wrapper passes raw `kwargs` to the
   provider and validates only after approval (`run_validated`). The gateway
   flow reverses this: arguments are validated against the tool's
   `args_schema` *first* (invalid arguments return a validation-error
   observation to the model without ever prompting), and the prompt displays
   the canonical validated dump. The same validated object is what executes on
   approval — the user always approves exactly what will run. The console
   provider adopts the same ordering so CLI and gateway cannot diverge; the
   ordering change is covered by registry/confirmation regression tests.
2. The broker creates a request: `{id: uuid4, session_id, tool, args, preview,
   expires_at: now+120s}` and a pending future, then enqueues
   `approval.request` on the session's outbound queue (single writer,
   section 6) — it never writes to the socket directly. `preview` comes from
   `tool.confirmation_preview(validated_args)` exactly as the console flow
   builds it.
3. The client answers `approval.response {id, approved}`. The broker accepts
   the reply only if the id exists, **belongs to the answering session**, is
   unexpired and unanswered. Otherwise the reply is ignored and logged
   (duplicate, stale and cross-session replies are attack/bug indicators, not
   user input).
4. Timeout, turn cancellation or session disconnect resolve the future with
   **deny** — default deny survives every failure mode.
5. The existing `PermissionPromptEvent` audit inside
   `wrap_tool_with_confirmation` fires unchanged, now with the turn's task ID.

Because tools are bound per session (`registry.langchain_tools(language,
approve, sanitizer, audit)` called per session with that session's provider),
one user's approval can never release another user's tool call. Tool binding
cost is trivial (StructuredTool construction); the plugin host's per-plugin
call lock already serializes plugin calls across sessions.

## 8. Streaming chat (DCL-125, DCL-127)

Today `build_ollama_model` awaits `bound.ainvoke` and `run_chat` awaits a
completed turn; WebSocket-forwarding that is not token streaming.

- **Model side — explicit contract, proven by test.** `ModelCallable` today
  returns one completed message and `build_ollama_model` awaits
  `bound.ainvoke`; swapping the internals to `astream`-and-aggregate does not
  by itself guarantee token events reach an outside observer. The contract is
  therefore: the graph node invokes the model runnable with its
  `RunnableConfig` propagated, and a milestone M4 integration test must prove
  real `on_chat_model_stream` events escape a running graph (using a streaming
  fake runnable, then Ollama) before any UI streaming code ships. If
  propagation cannot be made reliable, the fallback is a per-turn token sink
  injected alongside the model — still real streaming, just not routed through
  LangGraph's event API.
- **Citations are a typed side channel, not parsed text.** Document tools
  currently return a rendered `str`; structured source metadata does not reach
  the graph. A per-turn `TurnSources` collector (reached through the same
  context mechanism as the task ID) records retrieval metadata inside the
  search/summarize implementations. `chat.final.sources` is built from that
  collector — never parsed from tool output, never model-authored.
- **Graph side.** A turn runs via `graph.astream_events(version="v2", ...)`
  with the turn's message state as input. The session forwards, per turn and
  with a monotonically increasing `seq`:
  - `chat.delta {turn_id, seq, text}` — token deltas
  - `tool.start / tool.end {turn_id, seq, name, args|result_preview}` —
    structured tool progress
  - `approval.request` — enqueued by the broker through the same outbound
    queue (section 7)
  - `chat.final {turn_id, seq, text, sources}` — complete answer plus the
    collected source metadata
- **Backpressure.** A per-connection bounded queue (256 messages); the
  producer awaits. If the queue stays full for 5 s the client is not reading:
  the turn is cancelled with a terminal error frame. No unbounded buffering,
  no silent drops.
- **Cancellation ordering.** `cancel` stops token production first; a
  `chat.final` never follows a cancellation acknowledgement for the same turn.
- **Latency.** DCL-127's "first token < 1 s" is a measurement task in
  milestone M5 (section 17), not a design claim. If real streaming proves
  unreliable with tool-calling models, the fallback is completed-message
  delivery chunked by sentence — shipped knowingly, with the latency target
  re-measured, never asserted.

## 9. REST API (DCL-126)

All routes under `/api`, all bodies typed in `schemas.py`, OpenAPI generated
by FastAPI. Error shape everywhere: `{"error": {"code": str, "message": str}}`.

| Route | Purpose |
| --- | --- |
| `POST /api/auth/login` / `logout`, `GET /api/auth/status` | section 2 |
| `GET /api/status` | Ollama health + model presence, plugin states, version, egress monitor on/off, watcher on/off |
| `GET /api/tasks`, `GET /api/tasks/{id}` | Durable task list/detail (status, result, timestamps) |
| `GET /api/audit` | Filters: `date_from`, `date_to`, `event_type`, `task_id`; keyset pagination on `(created_at, id)` |
| `GET /api/audit/export?day=&format=md\|json` | Reuses `declaw/audit/report.py` and `export.py` |
| `GET /api/plugins` | Built-in plugins: name, version, localized description, state, failures |
| `POST /api/plugins/{name}/disable` | Immediate: stops the running plugin, audited |
| `POST /api/plugins/{name}/enable` | Marks enabled + clears quarantine, audited; **takes effect at next gateway start** (see section 11) |
| `GET /api/plugins/{name}/permissions` | Requested / author-denied / granted sets |
| `POST /api/plugins/{name}/permissions/{perm}/grant` / `revoke` | Existing `GrantStore.grant/revoke`, audited |
| `GET /api/settings`, `PUT /api/settings` | section 12 |
| `GET /api/documents` | Catalog listing (path, size, status, timestamps) |
| `POST /api/documents/reindex` | Start reconciliation; progress streams on `/ws/events` |
| `GET /api/documents/search?q=&k=` | Sanitized retrieval exactly as chat sees it (a debugging aid the UI also uses) |

**Decision: no REST write actions.** Organize/summarize/move stay chat tools
behind the approval transport. The readiness assessment requires that any REST
document action keep confirmation and containment; giving the REST surface no
mutating document route satisfies that requirement by construction in v0.1 and
keeps one approval UX, not two. Flagged for ratification in section 20.

## 10. Documents over the gateway

- **Watcher handoff — one chosen design.** `Application` starts
  `DocumentWatcher` in gateway mode. Watchdog callbacks run on a watchdog
  thread and hand events to the app loop via
  `loop.call_soon_threadsafe(queue.put_nowait, ...)` into a **loop-owned
  `asyncio.Queue`**; the current unsynchronized `ChangeBuffer` dict is
  replaced by this queue plus loop-side debounce/coalescing keyed by path
  (debounce semantics unchanged, now single-threaded by construction). Queue
  full (10 000 pending paths) drops oldest with an operational-log warning.
  Shutdown drains the queue, then stops the observer.
- **Delete/move handling.** The handler gains `on_deleted`/`on_moved`, mapped
  to catalog/store reconciliation (remove chunks, drop catalog rows; a move is
  delete-old + index-new) — today only create/modify exist.
- **One indexing worker, with retry.** Watcher-triggered indexing, manual
  reindex and startup reconciliation all feed a single serialized indexing
  worker. A failed path is retried with bounded backoff (3 attempts:
  immediately, after 30 s, after 5 min), then marked failed, reported on the
  progress stream and visible in the catalog — no silent loss, no infinite
  retry. Startup reconciliation runs the indexer's existing full-scan
  reconciliation once at gateway start.
- **Blocking work.** `DocumentStore`'s synchronous Chroma add/query/delete
  inside async methods are wrapped with `asyncio.to_thread` so a reindex does
  not stall chat turns.
- **Coordination — honest version.** Search stays *available* during indexing,
  but Chroma read/write thread-safety from concurrent `to_thread` calls is
  established by a dedicated test before we rely on it; if the test says no,
  reads serialize with writes through the same worker and the UI simply shows
  slightly slower search during reindex.
- **Progress.** The indexer's existing progress callback feeds
  `index.progress {total, done, current_path}` broadcasts on `/ws/events`.
- **Folder picker honesty.** A browser cannot return arbitrary server paths.
  The documents page shows the configured workspace path and a Reindex button;
  changing the workspace is a settings change (restart-required, section 12).
  Native folder selection belongs to the later Tauri integration. The UI copy
  says exactly this rather than pretending otherwise.

## 11. Plugins and the permission experience (DCL-130, DCL-082/134)

**Decision: a permission panel in Settings, not a first-run consent modal.**

Rationale: the approved Phase 7 model gives built-in plugins one-time audited
auto-grants at first load. A first-run consent screen would appear *after* the
grants already exist — security theater — or would require a "grants pending"
state machine the host does not have and v0.1 does not need. The honest UX is
a panel that shows, per built-in plugin: requested permissions, the author's
`denied` promise-list, current grants, with grant/revoke buttons. Every change
flows through `GrantStore.grant/revoke` and lands in the audit trail as
`PluginPermissionEvent` (already implemented). The UI warns that revoking
`filesystem.read` from `doc-intel` disables document parsing; runtime denial
is enforced by the existing `PermissionEnforcer`.

**Enable/disable semantics (honest).** `PluginHost.disable` stops a running
plugin immediately. `PluginHost.enable` today only flips persisted state and
clears quarantine — it neither loads nor starts the plugin process, and
existing sessions keep the tool list they were built with. So: **disable is
immediate; enable takes effect at the next gateway start**, and the UI labels
it exactly that way (with a restart badge like workspace changes). Hot-loading
a plugin into a running host is deliberately out of v0.1 scope; flagged in
section 20.

The plugin page lists name, version, localized description
(`manifest.description_for_language`), state (enabled/disabled/quarantined)
and load failures, with enable/disable actions. No install, uninstall or
update UI exists.

## 12. Settings service (DCL-131)

- **Storage.** `settings.json` in `data_dir`, managed by
  `declaw/settings_service.py`. Precedence: environment > file > defaults.
  `SettingsService` composes the two. At cold process startup, `get_settings()`
  freezes the effective workspace from this file into its singleton, retaining
  which fields came explicitly from the environment. This aligns filesystem
  containment, plugin parsing, the indexer and watcher after restart; browser
  requests never clear or mutate that singleton. Model/language composition
  remains per-session.
- **Mutable keys (v0.1):** `model`, `language`, `workspace_dir`. Nothing else
  is editable from the UI; security toggles (`sanitizer_required`, etc.) stay
  env-only so a compromised session cannot quietly lower defenses.
- **Apply semantics — explicit injection, no cache mutation.** `model` and
  `language` cannot flow through `get_settings()`: it is a process-wide
  `lru_cache`, and `build_ollama_model` reads it directly. The
  `SettingsService` therefore composes env + file into an **immutable
  effective-settings snapshot** per new session, and `build_brain` /
  `build_ollama_model` gain explicit `model`/`language` parameters fed from
  that snapshot. The global settings cache is never cleared or mutated to
  serve a browser request. With that injection path, `model`/`language` apply
  to **new** chat sessions. `workspace_dir` is **restart-required**: the
  document stack, watcher, catalog and path containment all key off it, and a
  partial hot-rebind is the kind of inconsistency the readiness assessment
  warns about. The PUT response marks each changed key
  `applied: "new_session" | "restart_required"` and the UI shows a restart
  badge. Validation: `language ∈ {en, fr}`; `model` non-empty (existence
  checked against Ollama at next session start, not at save);
  `workspace_dir` must exist or be creatable and must not equal `data_dir`.

## 13. Web UI (DCL-127–130, 133)

- **Stack.** Vanilla JS modules, `index.html` with hash routing, hand-written
  local CSS, system font stack. **Delta from the roadmap's "vendored
  Tailwind"**: vendoring Tailwind properly means a Node build step the Python
  CI does not have, for six small pages. Hand-written CSS keeps every shipped
  byte auditable and drops a toolchain. Flagged in section 20.
- **Pages:** connect (token), chat, documents, audit, plugins, settings,
  status. All served as static files by FastAPI at `/`.
- **Security headers** on every response: `Content-Security-Policy:
  default-src 'self'; connect-src 'self' ws://<bind-authority>; img-src 'self'
  data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`,
  `X-Content-Type-Options: nosniff`. The `connect-src` WebSocket authority is
  **generated from the actual bind host/port** (section 1 keeps the port
  configurable), and the frontend derives its WebSocket URL from
  `window.location` — never a hard-coded 7842. No runtime CDN, no inline
  script/style — the CSP is testable and tight by construction.
- **Rendering untrusted text.** Model output, document chunks, audit payloads
  and plugin strings are inserted only via `textContent`/`createTextNode`.
  `innerHTML` with untrusted data is forbidden; a comment in the JS module
  header says so. **No Markdown rendering in v0.1** — answers display as plain
  text with preserved whitespace. This deletes an entire XSS class at the cost
  of formatting; recorded as a limitation, reversible later with a vendored,
  sanitized renderer.
- **Chat page.** Streaming bubbles, per-turn cancel, approval modal showing
  tool name, exact arguments or the tool's own preview, and approve/deny
  buttons wired to the correlated request ID. Connection-loss banner; no fake
  resume (non-goal).
- **Status page** polls `/api/status` and subscribes to `/ws/events` for live
  plugin/indexing changes (DCL-133).

## 14. i18n (DCL-132)

`ui/locales/en.json` and `fr.json`, fetched at runtime, keyed by dotted
string IDs; the active language comes from settings. Every visible string —
including error-code mapping and approval modal chrome — goes through the
locale files. Server-generated text (tool denials, plugin descriptions) is
already localized server-side and passes through untouched.

## 15. Audit surface (DCL-129)

The viewer filters by date range, event type and task ID; export reuses the
existing daily report (Markdown) and JSON export. **Delta:** the ticket's
"filter by severity" is dropped — the audit schema has no severity field and
inventing one is a schema change this phase does not need. Event-type
filtering covers the intent. If the audit DB write path is failing (the
documented swallow-and-continue behavior of `DbAuditLogger`), the UI shows an
"audit unavailable" state instead of an empty trail pretending to be complete.
That state needs a source of truth the logger does not currently expose:
`DbAuditLogger` gains a thread-safe degraded counter (incremented in the
existing `except` path) surfaced through `/api/status`; the viewer
distinguishes "no matching events" from "writes are failing".

## 16. Error handling matrix

| Situation | Behavior |
| --- | --- |
| Ollama down at gateway start | Gateway starts; `/api/status` shows red; chat turns fail with typed error |
| Ollama dies mid-turn | Turn fails; task FAILED with error; session stays open (same contract as REPL) |
| Wrong/expired token at login | 401, rate-limited, audited, no token material logged |
| WS drops with pending approval | Approval denied, turn cancelled, task FAILED |
| Plugin crashes mid-turn | Existing supervisor/quarantine path; tool error observation reaches the model |
| Sanitizer model missing with `sanitizer_required` | Fail closed (existing behavior): external content withheld |
| Audit DB write failure | Logged, turn continues (documented existing limit; UI shows "audit unavailable") |
| Chroma/store failure during reindex | Job marked failed; progress stream reports; watcher keeps running |
| Settings PUT invalid | 422 with per-field errors; file unchanged |

## 17. Testing strategy — security tests first

Per project rule, the security-critical tests are written (and fail) before
implementation. Milestones follow the readiness assessment's proposed order.

**M1 — contracts and failing tests:**
- startup refuses `0.0.0.0` / LAN IP even when env-crafted
- 401 without session cookie; 403 wrong Host; 403 foreign/missing Origin on
  POST; WS handshake closed on unauth (4401) and foreign Origin (4403)
- 413 oversize body — including a chunked request with no `Content-Length`;
  429 login brute force; a single oversized WS message closed with `1009`
- approval: timeout → deny; disconnect → deny; cross-session reply rejected;
  duplicate reply accepted once then rejected; the prompt shows the validated
  arguments and the executed call receives that same validated object;
  invalid arguments produce a validation-error observation without prompting
- `task_id` present on tool/permission/quarantine/egress events emitted
  during a gateway turn, including events scheduled from the turn's context
- CSP/nosniff headers present on `/` and API responses
- shutdown order test: pending approvals denied, watcher stopped, host
  stopped, egress monitor uninstalled

**M2 — application extraction:** existing CLI suites pass unmodified
(`test_repl.py`, `test_tools_registry.py`, `test_tools_confirmation.py`,
document and plugin suites) plus new `Application` lifecycle tests. The
cold-start DB regressions from the readiness fix are preserved.

**M3 — first end-to-end slice:** authenticated WS chat turn with a WRITE tool:
correlated approval, audited execution, task row with ID, disconnect-deny.

**M4 — streaming:** first, the gate test from section 8: a streaming fake
runnable (then real Ollama) produces actual `on_chat_model_stream` events
through `graph.astream_events` — if this fails, the token-sink fallback is
taken knowingly. Then: ordered `seq`, cancel propagates, backpressure
cancels, no `chat.final` after cancel-ack, and `chat.final.sources` comes
from the typed collector (assert structurally — a turn whose tool output text
contains fake citations must not leak them into `sources`).

**M5 — documents/plugins/settings/status/audit/UI:** multi-client history
isolation; approval never crosses sessions; settings precedence env > file;
restart-required flags; audit filters and export; EN/FR locale completeness
test (same key set both files). DOM-level markup-injection is verified by a
manual checklist; Node's built-in runner now executes bootstrap, Documents,
chat answer/citation and audit rendering regressions with a minimal DOM.
Server-side CSP and
no-inline-script tests run in CI. First-token latency is measured and recorded
in a dated history report — not asserted as a guarantee.

## 18. Honest limitations

- Loopback + token + cookie is not multi-user auth. Any local process can
  attempt logins (rate-limited) and a process running as the user can read
  `data_dir` directly. The defended classes are drive-by web content, CSRF and
  DNS rebinding.
- The session cookie lacks `Secure` (plain HTTP on loopback); CSRF rests on
  `SameSite=Strict` plus Origin/Host checks.
- The gateway token is printed to the console on start — visible in terminal
  scrollback and to shoulder-surfing. It is the practical bootstrap for a
  local single-user app; rotation is one flag away.
- Chat history is per-connection memory, and each connection runs one turn at
  a time. Disconnecting loses the transcript; tasks and audit remain. Both are
  deliberate scope cuts, not oversights.
- Plugin enable is not hot: it takes effect at the next gateway start
  (`PluginHost.enable` does not load or start processes today, and v0.1 does
  not add that). Disable is immediate.
- The confirmation wrapper's validate-before-prompt ordering change alters one
  CLI-observable behavior: a tool call with invalid arguments no longer
  prompts first — the model gets the validation error directly. This is a
  security-motivated improvement, covered by regression tests.
- Cancelled turns are recorded as FAILED because `TaskStatus` has no CANCELLED
  value; a migration was judged not worth the semantic.
- Episode summaries are truncated final answers, not LLM-written summaries.
- `DbAuditLogger` still swallows storage errors by design; the gateway does
  not change that release gate.
- `EgressMonitor` observes instrumented `httpx` calls in this process only. It
  is not an OS firewall and does not see plugin-process egress.
- Plain-text rendering means no rich formatting in answers.
- Watcher integration coverage is partly synthetic (as today); blocking
  Chroma calls are moved off the loop but Chroma/SQLite concurrency limits
  are unchanged.
- Packaging (`create_all` vs migrations, plugins outside the wheel) is
  untouched and remains a Phase 14 gate.

## 19. Ticket mapping

| Ticket | Section | Scope notes |
| --- | --- | --- |
| DCL-120 | 1 | `start` = foreground uvicorn; `stop` deferred to DCL-234 |
| DCL-121 | 2 | Keyring-stored token + paste-once login + session cookie; `--rotate-token` |
| DCL-122 | 3 | Host allowlist + Origin fail-closed, WS included |
| DCL-123 | 4 | Token buckets, 429 + `Retry-After` |
| DCL-124 | 4 | 64 KiB default, per-route overrides |
| DCL-125 | 2, 8 | Cookie+Origin at handshake; streaming protocol |
| DCL-126 | 9 | Typed routes; no REST document writes (decision) |
| DCL-127 | 8, 13 | Real streaming; latency measured in M5, not guaranteed |
| DCL-128 | 10, 13 | Workspace path display + reindex + progress; no fake folder picker |
| DCL-129 | 15 | Severity filter dropped (no such field) |
| DCL-130 | 11 | Built-ins only: list, enable/disable, permissions panel |
| DCL-131 | 12 | Three mutable keys; workspace restart-required |
| DCL-132 | 14 | JSON locales, completeness-tested |
| DCL-133 | 13 | Status page + `/ws/events` |
| DCL-134 / DCL-082 | 11 | Settings permission panel; first-run modal rejected with rationale |

## 20. Decisions to ratify at review

1. **Strict 127.0.0.1 launch** even though `Settings` accepts `localhost`/`::1`
   (section 1). Ratify, or widen the launch contract with matching Host
   allowlist rules.
2. **Paste-once token → HttpOnly SameSite=Strict cookie**, token never in
   browser storage or URLs (section 2).
3. **No REST document write actions**; mutations only via chat approvals
   (section 9).
4. **Permission panel, not first-run consent** (section 11).
5. **Hand-written CSS instead of vendored Tailwind** (section 13).
6. **No Markdown rendering in v0.1** (section 13).
7. **Workspace changes restart-required**; model/language apply to new
   sessions (section 12).
8. **Cancelled turns recorded as FAILED**, no `TaskStatus` migration
   (section 6).
9. **`declaw stop` stays unimplemented** this phase (section 1).
10. **Validate-before-prompt in the confirmation wrapper** — user approves
    exactly the validated arguments that will execute (section 7).
11. **Plugin enable = next gateway start; disable = immediate** — no hot
    plugin loading in v0.1 (section 11).
12. **One active turn per chat connection** — a second message during a turn
    is rejected `busy` rather than queued (section 6).
