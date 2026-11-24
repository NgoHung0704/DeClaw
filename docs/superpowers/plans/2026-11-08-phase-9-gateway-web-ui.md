# Phase 9 — Gateway & Web UI Implementation Plan

Historical execution plan: implementation was delivered on 2026-11-08;
see the [dated baseline](../../history/phase-9-baseline-2026-11-08.md) and
[renewed verification](../../history/phase-9-verification-2026-11-12.md).
The original checkboxes/instructions below are preserved as authored, not a
current backlog or a claim that this maintenance reran their red/green steps.
The original machine-local SDD ledger is not required to navigate these records.
Node is now used for development behavior tests; no frontend build was added.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the loopback FastAPI gateway and local EN/FR web UI in front of the same CLI services, per the ratified Phase 9 spec.

**Architecture:** One Python process: `declaw start` builds an `Application` (extracted from `main.chat`) and runs uvicorn programmatically against a FastAPI app whose routes share the CLI's brain, typed tools, sanitizer, confirmation, audit, plugin host and document stack. Security middleware (auth, Host/Origin, rate limits, body caps) lands before any functional route; no wrapper is bypassed or duplicated.

**Tech Stack:** Python 3.12 + uv, FastAPI/uvicorn (already in `pyproject.toml`), vanilla JS modules + hand-written CSS, JSON locales. No Node toolchain, no runtime CDN.

**Spec:** `docs/specs/2026-11-08-phase-9-gateway-web-ui-design.md` — binding authority; this plan argues from it. Ratified: all 12 decisions of spec section 20, also recorded in the versioned architecture decisions and baseline.

## Global Constraints

- Bind contract: `127.0.0.1` only. `gateway/app.py` asserts `settings.host == "127.0.0.1"` at startup independently of `Settings._enforce_loopback`; `DECLAW_HOST=0.0.0.0` or a LAN IP aborts startup (spec §1).
- Default port 7842, configurable via `DECLAW_PORT` (spec §1). Host-header allowlist derives from the **actual bind authority**, never a hard-coded 7842.
- WRITE/DESTRUCTIVE tools: human confirmation, default deny. Timeout, cancel, disconnect ⇒ deny (spec §7).
- Token never in URLs, logs, audit events, HTTP responses, or browser storage (spec §2).
- Session cookie: `declaw_session=<id>; HttpOnly; SameSite=Strict; Path=/`; no `Secure` flag (plain HTTP loopback) (spec §2).
- Origin required and must equal `http://127.0.0.1:<port>` on every non-GET/HEAD and every WS handshake; missing/null Origin ⇒ 403 / close 4403 (fail closed) (spec §3).
- Byte counting before body buffering at ASGI receive level, including chunked requests without `Content-Length` (spec §4). Caps: 64 KiB default, 16 KiB `PUT /api/settings`, WS message 32 KiB → close 1009.
- No REST document write actions; mutations only via chat approvals (spec §9).
- External text renders as plain text via `textContent`/`createTextNode`; `innerHTML` with untrusted data forbidden; no Markdown rendering (spec §13).
- CSP on every response: `default-src 'self'; connect-src 'self' ws://<bind-authority>; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'` + `X-Content-Type-Options: nosniff` (spec §13).
- Mutable settings keys (v0.1): `model`, `language`, `workspace_dir` only; security toggles stay env-only. Snapshot per new session; global `get_settings()` cache never mutated for a browser request (spec §12).
- Rate limits (spec §4): login 5/min → 429 + `Retry-After`; chat turn start 10/min/session; other WS 30/s/connection; authenticated REST reads 120/min/session.
- Approval: validate-before-prompt everywhere (CLI ordering changes to match); user approves exactly the validated object that executes (spec §7, §18).
- Code/comments in English; commit format `feat(DCL-XXX): ...` / `fix(DCL-XXX): ...`. CI: `uv sync --frozen`, `uv run ruff check .`, `uv run mypy declaw declaw_plugin_sdk`, `uv run pytest`.
- Chat history is in-memory per connection; one active turn per connection (second message ⇒ typed `busy` error); cancelled turns recorded FAILED with `error="cancelled by user"` — no `TaskStatus` migration (spec §6).
- Plugin enable takes effect at next gateway start; disable is immediate (spec §11).

## Review Focus

(Input classes the agreed tests may not exercise; each is pinned by the named test in its owning task.)

1. **No-`Content-Length` oversize body** — a chunked request whose total exceeds the cap must 413 even though no header declares size (Task 4, `test_body_cap_chunked_no_content_length`).
2. **Cross-session approval reply** — an `approval.response` whose id belongs to another session is ignored + logged, never executes (Task 5, `test_cross_session_reply_ignored`).
3. **Non-default port binding** — with `DECLAW_PORT=9000`, Host/Origin checks and the CSP `connect-src` accept `127.0.0.1:9000` and reject `127.0.0.1:7842` (Task 3, `test_host_allowlist_follows_actual_port`; Task 15, `test_csp_connect_src_derived_from_bind`).
4. **Context-surviving task IDs** — events emitted by async work scheduled *from inside* a turn (egress sync-bridge, quarantine sinks) must carry the turn's task_id via copied context, not just direct calls (Task 6, `test_task_id_survives_task_scheduling`).
5. **Fake citations in tool output text** — a tool whose result string contains fake citation markers must NOT leak them into `chat.final.sources`; sources come only from the `TurnSources` collector (Task 10, `test_sources_not_parsed_from_tool_text`).

---

### Task 1: Launch contract + `declaw start` (DCL-120, spec §1)

**Files:**
- Create: `declaw/gateway/app.py`
- Modify: `declaw/main.py:89-102` (`start`, `stop`)
- Test: `tests/gateway/test_launch.py` (create `tests/gateway/__init__.py`)

**Interfaces:**
- Produces: `assert_launch_contract(settings: Settings) -> None` (raises `GatewayLaunchError` unless `settings.host == "127.0.0.1"`); `create_app(settings: Settings) -> FastAPI` (empty app + health root for now); `main.start` runs `uvicorn.Server` programmatically in the foreground with `proxy_headers=False`, no `--reload`, access log into loguru DEBUG.

- [ ] **Step 1: Write failing tests** — `test_start_refuses_0000`: Settings with `host="0.0.0.0"` → `assert_launch_contract` raises; `test_start_refuses_lan_ip` (e.g. `192.168.1.10`); `test_start_refuses_localhost_and_ipv6`: `localhost` and `::1` also refused at launch (settings stay valid, launch is not); `test_launch_accepts_127001`; `test_create_app_returns_fastapi`.
- [ ] **Step 2: Run** `uv run pytest tests/gateway/test_launch.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `declaw/gateway/app.py` + rewrite `main.start` to build settings, assert contract, run uvicorn; `main.stop` keeps unimplemented message pointing at Ctrl-C (DCL-234 delta, spec §19).
- [ ] **Step 4: Run launch tests** — Expected: PASS. Run `uv run pytest tests/unit/test_cli_plugins.py tests/unit/test_config.py -q` (neighbors) — Expected: PASS.
- [ ] **Step 5: Commit** `feat(DCL-120): enforce strict 127.0.0.1 launch contract in declaw start`.

### Task 2: Gateway token + session registry (DCL-121, spec §2)

**Files:**
- Create: `declaw/gateway/auth.py`
- Modify: `declaw/credentials/store.py:34` (`KNOWN_SECRET_NAMES` gains `"gateway-token"`)
- Test: `tests/gateway/test_auth.py`, `tests/unit/test_credentials_store.py` (extend)

**Interfaces:**
- Consumes: `SecretStore` protocol (`get/set/delete/purge`), `default_credential_store(secrets_path)`.
- Produces: `mint_gateway_token(store: SecretStore) -> str` (creates-or-gets `secrets.token_urlsafe(32)` under name `gateway-token`); `rotate_gateway_token(store: SecretStore) -> str`; `SessionRegistry` with `create() -> str`, `validate(session_id: str) -> bool`, `drop(session_id: str) -> None`, 12 h absolute expiry, in-memory dict; cookie helpers `session_cookie(session_id: str) -> str` / clear variant. Constant `GATEWAY_TOKEN_NAME = "gateway-token"`.

- [ ] **Step 1: Failing tests** — mint stores via SecretStore fake and returns 43-char urlsafe token; second mint returns same value without re-write; rotate replaces; credential-store test that `purge()` removes `gateway-token`; registry validates fresh id, rejects unknown, rejects expired (inject clock), drop invalidates.
- [ ] **Step 2: Run** `uv run pytest tests/gateway/test_auth.py tests/unit/test_credentials_store.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `auth.py` + `KNOWN_SECRET_NAMES` extension. No token value ever logged: assert via caplog in test.
- [ ] **Step 4: Run** — Expected: PASS both files.
- [ ] **Step 5: Commit** `feat(DCL-121): mint keyring-backed gateway token and session registry`.

### Task 3: Host/Origin policy middleware (DCL-122, spec §3)

**Files:**
- Create: `declaw/gateway/middleware.py`
- Modify: `declaw/gateway/app.py` (`create_app` installs middleware)
- Test: `tests/gateway/test_host_origin.py`

**Interfaces:**
- Consumes: Task 1 `create_app(settings)`.
- Produces: pure-ASGI `HostOriginMiddleware(app, bind_authority: str)` — Host must equal `<authority>` exactly (403 otherwise, incl. missing host on HTTP/1.1); Origin must equal `http://<authority>` on non-GET/HEAD and WS handshakes; missing/`null` Origin ⇒ 403; WS handshake failures close with 4403. Installed first, before routing.

- [ ] **Step 1: Failing tests** — foreign Host 403; right Host passes GET; POST without Origin 403; `Origin: http://evil.example` POST 403; `Origin: null` POST 403; correct Origin passes; WS handshake foreign Origin → close code 4403 (use `websockets` or httpx-ASGI test client capable of raw handshake); `test_host_allowlist_follows_actual_port` with port 9000 settings: Host `127.0.0.1:9000` passes, `127.0.0.1:7842` 403.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** middleware + install in `create_app`.
- [ ] **Step 4: Run** → PASS; `uv run pytest tests/gateway -q` green.
- [ ] **Step 5: Commit** `feat(DCL-122): fail-closed Host/Origin policy for REST and WebSocket`.

### Task 4: Rate limits + body caps (DCL-123, DCL-124, spec §4)

**Files:**
- Modify: `declaw/gateway/middleware.py`
- Test: `tests/gateway/test_limits.py`

**Interfaces:**
- Produces: `RateLimiter` token buckets (in-process, per session / global) with the Global Constraints table values; `BodyCapMiddleware(app, default_cap=64*1024, overrides: dict[str,int])`; ASGI-receive-level byte counting before buffering; WS single-message cap 32 KiB → close 1009. Error JSON shape `{"error": {"code": str, "message": str}}`; 429 carries `Retry-After`.

- [ ] **Step 1: Failing tests** — login route bucket: 6th POST in a minute → 429 + `Retry-After`; REST read bucket keyed by session 120/min; default body 64 KiB ok / over → 413; `PUT /api/settings` 16 KiB override; `test_body_cap_chunked_no_content_length`: send chunked body > cap with no `Content-Length` (raw ASGI receive messages) → 413; WS message 33 KiB → close 1009; `security tests first` comments in file header.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** buckets + receive-wrapper + WS cap in `middleware.py`, wire into `create_app`.
- [ ] **Step 4: Run** → PASS; full `tests/gateway` green.
- [ ] **Step 5: Commit** `feat(DCL-123, DCL-124): session rate limits and ASGI-level body caps`.

### Task 5: ApprovalBroker + validate-before-prompt (spec §7, ratified §20.10)

**Files:**
- Create: `declaw/gateway/approval.py`
- Modify: `declaw/tools/confirmation.py:65` (`wrap_tool_with_confirmation`), `declaw/brain/repl.py:81` (`make_console_confirmation_provider`)
- Test: `tests/gateway/test_approval.py`, extend `tests/unit/test_tools_confirmation.py`

**Interfaces:**
- Consumes: `ConfirmationProvider` (`async (tool, args) -> bool`), `DeclawTool.args_schema`, `tool.confirmation_preview(validated_args)`.
- Produces: `ApprovalBroker` with `create_provider(session_id: str, enqueue: Callable[[dict], None]) -> ConfirmationProvider`; pending requests `{id: uuid4, session_id, tool, args, preview, expires_at: now+120s}` + future; reply handling accepting only same-session, unexpired, unanswered ids (else ignore + log); timeout/cancel/disconnect resolve deny; **validate-before-prompt ordering in `wrap_tool_with_confirmation`**: invalid args → validation-error observation to the model, no prompt, no provider call; prompt shows canonical validated dump; the same validated object executes. Console provider adopts identical ordering.

- [ ] **Step 1: Failing tests** — invalid args produce validation-error observation and provider is never called (new ordering both providers); prompt text contains the validated dump and executed call receives that same object (identity assertion); timeout → deny; `test_cross_session_reply_ignored` (Review Focus 2); duplicate reply accepted once then rejected; stale/expired id rejected; expired request auto-denies the future.
- [ ] **Step 2: Run** → FAIL (new ordering fails current wrapper: it prompts before validating).
- [ ] **Step 3: Implement broker + reorder `wrap_tool_with_confirmation`; update CLI confirmation tests to pin the new behavior.
- [ ] **Step 4: Run** `uv run pytest tests/gateway/test_approval.py tests/unit/test_tools_confirmation.py tests/unit/test_tools_registry.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(DCL-125): approval transport with validate-before-prompt ordering`.

### Task 6: Auth route + AuthEvent + task-correlated audit (spec §2, §6)

**Files:**
- Create: `declaw/gateway/routes/auth.py`, `declaw/audit/correlation.py`
- Modify: `declaw/audit/events.py` (add `AuthEvent`, extend `AnyAuditEvent`), `declaw/gateway/routes/__init__.py`
- Test: `tests/gateway/test_auth_flow.py`, `tests/unit/test_audit_events.py` (extend), `tests/unit/test_audit_logger.py` (extend)

**Interfaces:**
- Consumes: Task 2 (`mint_gateway_token`, `SessionRegistry`, cookie helpers), `DbAuditLogger`.
- Produces: routes `POST /api/auth/login` (`hmac.compare_digest` verify, sets cookie, 401 on bad token, emits `AuthEvent("gateway.auth")` **without token material**), `POST /api/auth/logout`, `GET /api/auth/status`; `declaw/audit/correlation.py`: `current_task_id: ContextVar[str | None]`, `class TaskCorrelatingAuditLogger` wrapping an inner logger — `emit(event)` applies `model_copy(update={"task_id": ...})` to any event whose `task_id` is unset; explicit ids preserved.

- [ ] **Step 1: Failing tests** — login ok sets cookie + audits success; wrong token 401 + audits failure; token value absent from caplog and audit payload; logout drops session; status reflects auth; unauth'd API access → 401; correlation: event with unset task_id gains contextvar value, event with explicit id untouched; `test_task_id_survives_task_scheduling` (Review Focus 4): task created with copied context, event emitted inside `asyncio.create_task` from that context still correlated.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** routes + AuthEvent + TaskCorrelatingAuditLogger; wire logger into `create_app`.
- [ ] **Step 4: Run** → PASS; `tests/unit/test_audit_*` green.
- [ ] **Step 5: Commit** `feat(DCL-121, DCL-129): paste-once login route and task-correlated audit logging`.

### Task 7: `Application` extraction + deterministic shutdown (spec §5, M2)

**Files:**
- Create: `declaw/app.py`
- Modify: `declaw/main.py` (`chat` becomes console-sink Application consumer), `declaw/brain/repl.py:150` (`run_chat` signature if needed)
- Test: `tests/unit/test_app_lifecycle.py`

**Interfaces:**
- Consumes: engine/sessionmaker factories, `DbAuditLogger`, `QuarantineStore`, `Sanitizer`, `PluginHost`, `build_document_stack`, `EgressMonitor`, tool registry factory.
- Produces: `class Application` with async `start()` and `shutdown()`; owns the services list of spec §5; `main.chat` = build `Application` (console sinks + console confirmation provider) then `run_chat`; EgressMonitor gets exactly one owner with uninstall in shutdown; shutdown order: stop accepting sessions → cancel in-flight turns → deny pending approvals → stop watcher → `host.stop()` → uninstall egress monitor → dispose engine. Gateway starts and serves `/api/status` even when Ollama is down (typed error on chat instead of hard exit).

- [ ] **Step 1: Failing tests** — lifecycle: start then shutdown calls each service's stop in recorded order (fakes record call names; assert exact sequence); double-shutdown is safe; chat builds Application (monkeypatch count); Ollama-missing start does not raise.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `Application`; refactor `main.chat` minimally; existing CLI suites must pass unmodified** (`test_repl.py`, `test_tools_registry.py`, `test_tools_confirmation.py`, document/plugin suites; cold-start DB regressions preserved).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_app_lifecycle.py tests/unit/test_repl.py tests/unit/test_db.py -q` then full `uv run pytest` — Expected: PASS (baseline count preserved: 786 pass / 1 env skip of 2026-10-25).
- [ ] **Step 5: Commit** `refactor(DCL-120): extract Application service layer from main.chat`.

### Task 8: SettingsService (DCL-131, spec §12)

**Files:**
- Create: `declaw/settings_service.py`
- Modify: `declaw/brain/repl.py:68` (`build_brain` gains explicit `model: str`, `language: Language` params fed from snapshot), `declaw/brain/model.py` or `ollama` builder (`build_ollama_model` same)
- Test: `tests/unit/test_settings_service.py`

**Interfaces:**
- Consumes: `Settings` (env layer), `get_settings()`.
- Produces: `class SettingsService` (path `data_dir/settings.json`): `effective() -> EffectiveSettings` (immutable pydantic snapshot composing env > file > defaults); `update(model: str|None, language: str|None, workspace_dir: str|None) -> dict[str, str]` returning per-key `applied: "new_session"|"restart_required"`; validation `language ∈ {en,fr}`, `model` non-empty, `workspace_dir` must exist-or-be-creatable and not equal `data_dir`. Global `get_settings()` cache never mutated.

- [ ] **Step 1: Failing tests** — precedence env > file > defaults; effective() snapshot immutable (mutation attempt raises/ignored); update writes file and returns applied flags (model/language → new_session; workspace_dir → restart_required); invalid language rejected; workspace==data_dir rejected; nonexistent workspace creatable ok; `lru_cache` untouched (no cache clear calls — assert via monkeypatch).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement service + explicit params on `build_brain`/`build_ollama_model` (defaults preserve current CLI behavior).
- [ ] **Step 4: Run** service tests + `tests/unit/test_chat_model.py tests/unit/test_loop.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(DCL-131): settings service with explicit per-session snapshot injection`.

### Task 9: WS chat sessions + first end-to-end slice (DCL-125, M3, spec §6)

**Files:**
- Create: `declaw/gateway/session.py`, `declaw/gateway/ws.py`
- Test: `tests/gateway/test_chat_flow.py` (integration)

**Interfaces:**
- Consumes: `Application`, `ApprovalBroker`, `TaskCorrelatingAuditLogger`, `default_registry().langchain_tools(language, approve, sanitizer, audit)`.
- Produces: `class GatewaySession` (message history, one active turn, one bounded outbound queue `asyncio.Queue(maxsize=256)`, one writer task); `class SessionManager` (create/drop); WS endpoint `/ws/chat`: cookie-auth at handshake (unauth close 4401), per-connection session, turn = user message → `Task` row PENDING→RUNNING→COMPLETED (result stored) / FAILED (`error="cancelled by user"` on cancel), `Episode` row on completion (summary = final answer truncated 500 chars, empty tags), second message during a turn → `busy` error frame, `cancel {turn_id}` cancels turn, disconnect cancels in-flight turn and denies that session's pending approvals. Task contextvar set for the whole turn (direct + copied-context async work).

**M3 slice (must land here):** authenticated WS chat turn invoking a WRITE tool: correlated approval works over the socket, execution audited with the turn's task_id, task row written, disconnect-deny verified end-to-end. Deterministic model fake, no Ollama required.

- [ ] **Step 1: Failing tests** — happy turn completes, Task row COMPLETED with result; WRITE-tool turn sends `approval.request` (validated args in prompt), `approval.response {approved:true}` → tool executes, audited with task_id; deny → tool not executed, denial observation; timeout → deny; disconnect mid-approval → deny + turn FAILED; second message during turn → `busy`; cancel → status FAILED `cancelled by user`, pending approval denied; Episode row linked by task_id; two connections have isolated histories.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** session/ws modules wired into `create_app`.
- [ ] **Step 4: Run** slice tests + full `tests/gateway -q` → PASS.
- [ ] **Step 5: Commit** `feat(DCL-125): websocket chat sessions with correlated approvals (M3 slice)`.

### Task 10: Real streaming + typed sources (DCL-127, M4, spec §8)

**Files:**
- Create: `declaw/gateway/sources.py` (`TurnSources` collector + contextvar accessor)
- Modify: `declaw/gateway/session.py`/`ws.py` (turn runner: `graph.astream_events(version="v2")` forwarding), `declaw/documents/tools.py:81` + actions (record retrieval metadata into the collector)
- Test: `tests/gateway/test_streaming.py`, `tests/unit/test_documents_citations.py` (extend)

**Interfaces:**
- Consumes: Task 9 turn machinery; document search/summarize implementations.
- Produces: per-turn frames with monotonic `seq`: `chat.delta {turn_id, seq, text}`, `tool.start/tool.end {turn_id, seq, name, args|result_preview}`, `approval.request`, `chat.final {turn_id, seq, text, sources}`; `TurnSources.record(metadata: dict) -> None` threaded via the same context mechanism as task_id; backpressure: outbound queue 256, producer awaits, 5 s full ⇒ cancel turn with terminal error frame; cancel ordering: no `chat.final` after cancel-ack.

- [ ] **Step 1 (gate test first, spec §8):** write `test_stream_events_escape_graph`: a streaming fake runnable yields tokens; assert real `on_chat_model_stream` events surface through `graph.astream_events` on a running graph. **If this gate fails after implementation attempts, take the token-sink fallback knowingly and record it in the ledger (Ruling).**
- [ ] **Step 2: Run gate** → FAIL initially.
- [ ] **Step 3: Implement** streaming turn runner + collector + document-side recording.
- [ ] **Step 4: Failing→passing tests** — ordered `seq` across mixed frames; cancel stops token production, no `chat.final` after cancel-ack; backpressure: fake unread client, queue full 5 s → turn cancelled + terminal error frame; `test_sources_not_parsed_from_tool_text` (Review Focus 5): tool returning text with fake citations yields `sources` containing only collector metadata; `chat.final.sources` built structurally.
- [ ] **Step 5: Run** `uv run pytest tests/gateway tests/unit/test_documents_citations.py -q` → PASS.
- [ ] **Step 6: Commit** `feat(DCL-127): token streaming with typed citation side channel`.

### Task 11: REST surface (DCL-126, spec §9)

**Files:**
- Create: `declaw/gateway/schemas.py`, `declaw/gateway/routes/{status,tasks,audit,documents,settings,plugins}.py`
- Test: `tests/gateway/test_rest.py`

**Interfaces:**
- Consumes: `Application` services, `SettingsService`, audit report/export (`declaw/audit/report.py`, `export.py`), catalog, plugin host, `GrantStore`.
- Produces: exactly the route table of spec §9 under `/api` (auth/cookies required; typed bodies in `schemas.py`; uniform error shape `{"error": {"code", "message"}}`). **No mutating document routes.** `GET /api/audit` keyset pagination on `(created_at, id)` with filters `date_from/date_to/event_type/task_id`; `GET /api/audit/export?day=&format=md|json` reuses report/export; `POST /api/plugins/{name}/enable` semantics per Global Constraints (enable → next start); `GET /api/settings` + `PUT /api/settings` per Task 8 flags; `POST /api/documents/reindex` starts reconciliation (progress via `/ws/events`, Task 14).

- [ ] **Step 1: Failing tests** — every route: 401 unauth'd; status aggregates Ollama health/plugins.version/egress+watcher state; tasks list/detail; audit filters + keyset pagination correctness; export md/json round-trip; plugins list/enable/disable with semantics flags; permissions grant/revoke audited as `PluginPermissionEvent`; settings GET/PUT with `applied` flags; documents catalog + search sanitized (q/k params); **no REST route mutates documents** — assert route inventory contains no document write verb.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement schemas + routes.
- [ ] **Step 4: Run** → PASS; full `tests/gateway` green.
- [ ] **Step 5: Commit** `feat(DCL-126): typed read-only REST surface with audit and plugin management`.

### Task 12: Document watcher handoff + indexing worker (DCL-128 server side, spec §10)

**Files:**
- Modify: `declaw/documents/watcher.py` (queue handoff, `on_deleted`/`on_moved`), `declaw/documents/session.py`/`store.py` (`asyncio.to_thread` wrapping), `declaw/app.py` (gateway-mode watcher ownership)
- Test: `tests/gateway/test_documents_gateway.py`, extend `tests/unit/test_documents_watcher.py`

**Interfaces:**
- Consumes: `DocumentWatcher`, index/catalog/store reconciliation, `Application`.
- Produces: watchdog-thread → `loop.call_soon_threadsafe(queue.put_nowait, ...)` into a loop-owned `asyncio.Queue` replacing the unsynchronized `ChangeBuffer` dict; loop-side debounce/coalescing keyed by path (semantics unchanged, single-threaded); queue cap 10 000 paths, drop-oldest + operational-log warning; delete = remove chunks + drop catalog rows, move = delete-old + index-new; one serialized indexing worker for watcher/manual/startup triggers with bounded retry (3 attempts: immediate, 30 s, 5 min) then marked failed + progress-reported; `Application.start()` runs `DocumentWatcher` in gateway mode only; shutdown drains queue then stops observer (inserted into Task 7's order between "deny approvals" and "host.stop()").

- [ ] **Step 1: Failing tests** — thread-safe handoff (events produced from a thread land in loop queue); debounce coalescing preserved; delete removes chunks+row; move reindexes; retry schedule (fake clock: 0s/30s/300s) then failed, progress broadcast noted, no infinite retry; queue-full drops oldest with warning; blocking Chroma calls run via `to_thread` (assert no loop stall: a concurrent chat turn keeps ticking during a reindex with a sleep-instrumented store).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; keep CLI behavior unchanged (`main.index` path untouched).
- [ ] **Step 4: Run** watcher + gateway doc tests + `tests/unit/test_documents_indexer.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(DCL-128): loop-safe watcher handoff and serialized indexing worker`.

### Task 13: `/ws/events` + status broadcast (DCL-133, spec §13 status page backing)

**Files:**
- Create: `declaw/gateway/events.py` (broadcaster)
- Test: `tests/gateway/test_events_ws.py`

**Interfaces:**
- Consumes: Task 11 status service, Task 12 progress callback, plugin lifecycle.
- Produces: `EventBroadcaster` with `subscribe() -> asyncio.Queue` / `unsubscribe(q)` / `broadcast(event: dict)`; `/ws/events` endpoint (auth 4401, Origin 4403, 32 KiB cap, rate limits per Task 4); event frames `index.progress {total, done, current_path}`, plugin enable/disable confirmations, watcher operational warnings.

- [ ] **Step 1: Failing tests** — auth + origin enforced on handshake; progress events reach a subscribed client; multiple subscribers isolated; unsubscribe stops delivery; token-bucket applies.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. **Step 5: Commit** `feat(DCL-133): websocket event stream for indexing and plugin changes`.

### Task 14: Web UI — markup, CSS, routing, CSP (DCL-127–130, 133 server side, spec §13)

**Files:**
- Create: `ui/index.html`, `ui/js/{app,api,chat,documents,audit,plugins,settings,status,connect}.js`, `ui/css/main.css`, `ui/locales/{en,fr}.json`
- Modify: `declaw/gateway/app.py` (static mount + security headers middleware)
- Test: `tests/gateway/test_ui_security.py`

**Interfaces:**
- Consumes: all REST/WS routes; locale JSON keyed by dotted IDs fetched at runtime.
- Produces: hash-routed vanilla-JS pages (connect, chat, documents, audit, plugins, settings, status) served as static files by FastAPI at `/`; security-headers middleware on every response (Global Constraints CSP with `connect-src` derived from the actual bind authority — Review Focus 3); WS URL derived from `window.location`, never hard-coded 7842; untrusted text via `textContent`/`createTextNode` only; no inline script/style; UI copy states honest semantics (enable→next start badge, workspace restart badge, no fake folder picker — shows configured path + Reindex).

- [ ] **Step 1: Failing tests** — `test_csp_connect_src_derived_from_bind`: with port 9000, response CSP contains `ws://127.0.0.1:9000` and never `7842`; `nosniff` present on `/` and API; `test_no_inline_script_or_style`: served HTML contains no `onclick=`/`<script>` without `src`/`style=` attributes (static scan of `index.html` fixture served); locale completeness: `en.json` and `fr.json` have identical key sets (CI test).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** static surface + headers middleware. **Step 4: Run** → PASS. **Step 5: Commit** `feat(DCL-127): local UI surface with strict content security policy`.

### Task 15: UI chat/documents/plugins/settings/audit/status pages (DCL-127–132, M5 UI)

**Files:**
- Modify: the `ui/js/*.js` modules created in Task 14
- Test: `tests/gateway/test_ui_security.py` (extend), manual DOM checklist in `docs/phase-9-review.md`

**Interfaces:**
- Consumes: Tasks 9–13 endpoints/frames.
- Produces: functional pages — connect (paste-once token), chat (streaming bubbles, per-turn cancel, approval modal with tool name + canonical validated args + approve/deny wired to request id, connection-loss banner), documents (catalog, reindex, progress, honest workspace copy), audit (filters, keyset pagination, export), plugins (list/enable/disable with semantics badges, permissions panel grant/revoke), settings (three mutable keys with `applied` feedback), status (polls `/api/status` + `/ws/events`); EN/FR switch via settings; EN and FR copy for every visible string including error-code mapping and approval modal chrome.

- [ ] **Step 1: Failing tests (server-verifiable parts)** — every API error code has a mapping key in both locales; approval modal i18n keys exist; settings PUT result flags rendered labels exist in locales.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement pages;** any server-visible copy through locale files only. **Step 4: Run** → PASS; whole `tests/gateway` suite green.
- [ ] **Step 5: Manual DOM checklist** documented in `docs/phase-9-review.md` (repo has no JS test runner — spec §17 M5; markup-injection manual checklist).
- [ ] **Step 6: Commit** `feat(DCL-128, DCL-129, DCL-130, DCL-131, DCL-132, DCL-134): functional web UI pages with EN/FR locales` or split per-ticket commits as convenient.

### Task 16: Verification sweep, latency measurement, docs handoff (M5 close, AGENTS.md duties)

**Files:**
- Create: `docs/history/phase-9-baseline-2026-11-08.md` (dated measurement report — never a fresh guarantee)
- Modify: `docs/project-status.md`, `docs/code-map.md`, `docs/architecture-decisions.md`, `docs/specs/2026-11-08-phase-9-gateway-web-ui-design.md` (status draft→approved-record), `TICKETS.md`
- Test: no new product tests; all existing suites green.

**Interfaces:**
- Consumes: everything.
- Produces: dated report with the exact commands run (uv sync --frozen / ruff / mypy / pytest, counts) and first-token latency measured per spec §17 M5 (fixture + measured Ollama number, recorded not asserted); status page rows updated for gateway/UI/watcher; spec header marked ratified with the 12 decisions; TICKETS.md checkboxes `[x]` DCL-120..134 with evidence links; code-map rows for `declaw/app.py`, `declaw/gateway/*`, `declaw/settings_service.py`; decisions doc records the ratified section-20 items.

- [ ] **Step 1: Full CI** — `uv sync --frozen && uv run ruff check . && uv run mypy declaw declaw_plugin_sdk && uv run pytest` — Expected: all green, counts recorded.
- [ ] **Step 2: Latency measurement** with local Ollama; record environment, model, first-token ms per turn in the dated report. If Ollama unavailable in this environment, record the skip honestly.
- [ ] **Step 3: Update docs** per AGENTS.md handoff rules (status, map, decisions, spec, TICKETS).
- [ ] **Step 4: Commit** `docs: record Phase 9 delivery, ratified decisions and dated baseline`.
