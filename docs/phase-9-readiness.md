# Phase 9 readiness assessment

Reviewed against the current source on 2026-10-25. This is a current handoff
assessment, not a Phase 9 design approval. The cold DB initialization fix is
committed as `5f168db`; the remaining gateway/UI gaps below are still open.

## Verdict

Ready to write the detailed Phase 9 specification; not ready to expose a gateway
by wrapping the CLI. The approved [roadmap](specs/2026-08-23-phase-7-9-roadmap.md)
settles loopback access, local assets, built-in plugins and retrieval sanitization.
Session ownership, browser authentication bootstrap and approval transport still
need a reviewed contract before implementation. Desktop packaging remains later.

## Current flow and reusable boundaries

| Boundary | Current implementation | Evidence and existing tests |
| --- | --- | --- |
| Session assembly | `main.chat` owns health checks, DB, audit, quarantine, sanitizer, plugin host, document tools and graph; its nested `_session` shares one event loop | [main.py](../declaw/main.py); [REPL tests](../tests/unit/test_repl.py) exercise history, errors and approvals, not a web session |
| Agent | `build_brain` builds an Ollama callable with context-window trimming; `build_agent_graph` alternates agent and tools | [repl.py](../declaw/brain/repl.py), [loop.py](../declaw/brain/loop.py); [loop tests](../tests/unit/test_loop.py) |
| Tool safety | `ToolRegistry.langchain_tools` composes typed validation, confirmation, external READ sanitization and audit; the same tools bind to model/executor | [registry.py](../declaw/tools/registry.py), [confirmation.py](../declaw/tools/confirmation.py); [registry tests](../tests/unit/test_tools_registry.py), [confirmation tests](../tests/unit/test_tools_confirmation.py), [path tests](../tests/unit/test_path_traversal.py) |
| Documents | `build_document_stack` shares store/catalog/indexer assembly. Chat supplies a sanitizer; indexing supplies `None` because screening happens on retrieval | [session.py](../declaw/documents/session.py), [indexer.py](../declaw/documents/indexer.py); [indexer tests](../tests/unit/test_documents_indexer.py), [document isolation tests](../tests/security/test_documents_isolation.py) |
| Progress and citations | Indexer accepts a progress callback. Search tools return source metadata; summary sources derive from retrieval | [tools.py](../declaw/documents/tools.py), [actions.py](../declaw/documents/actions.py); [search tests](../tests/unit/test_documents_search.py), [action tests](../tests/unit/test_documents_actions.py) |
| Plugin lifecycle | `PluginHost` provides start/stop/call/enable/disable and checks grants per call; subprocess calls serialize through a lock | [host.py](../declaw/plugin_host/host.py), [process.py](../declaw/plugin_host/process.py); [host integration tests](../tests/integration/test_plugin_host.py) cover load failures, revocation and lifecycle audit |
| Storage and secrets | Async SQLite factories, Task model, audit events, keyring abstraction and encrypted fallback already exist | [engine.py](../declaw/db/engine.py), [models.py](../declaw/db/models.py), [store.py](../declaw/credentials/store.py); [DB tests](../tests/unit/test_db.py), [credential tests](../tests/unit/test_credentials_store.py), [fallback tests](../tests/unit/test_credentials_fallback.py) |
| Reports and health | Audit reports/export, Ollama health and preflight checks can back typed read routes | [report.py](../declaw/audit/report.py), [export.py](../declaw/audit/export.py), [preflight.py](../declaw/preflight.py); [audit export tests](../tests/unit/test_audit_export.py), [preflight tests](../tests/unit/test_preflight.py) |

Keep these services behind a shared application/session boundary; the HTTP layer
should not call Typer commands, `asyncio.run`, console input or Rich renderers.
Keep validation, sanitizer and approval wrappers on every model-facing path.
REST document actions also need the same confirmation and containment policy.

## Gaps and prerequisite status

1. **Gateway implementation and security tests.** `declaw/gateway/` contains only
   empty package files; `main.start`/`stop` exit with an unimplemented message.
   There are no current route/auth/Origin/Host/rate/body-limit/WebSocket tests.
   Dependencies in `pyproject.toml` are not evidence of an API.
2. **Bind contract mismatch.** `Settings._enforce_loopback` accepts `localhost`
   and `::1`; `port` accepts configurable ports. `test_config.py` even tests port
   9000. The project invariant names `127.0.0.1:7842`. Pin the gateway launch
   contract and add negative tests before introducing a listener; do not silently
   reuse the broader settings as proof of compliance.
3. **Session/task ownership and cleanup.** `run_chat` owns an in-memory history
   and synchronous input, then calls `graph.ainvoke`. There is no session manager,
   durable task lifecycle, reconnect, cancellation or multi-client isolation.
   `Task` exists but CLI chat does not populate it. Tool and permission wrappers
   emit events without task IDs. Define session/turn/task IDs and propagate them
   through tool, permission, quarantine and network events.
4. **Approval transport.** The async `ConfirmationProvider` is reusable, but its
   console implementation is not. Define correlated requests, deadlines,
   disconnect-deny, rejection of duplicate/stale/cross-session replies and exact
   tool arguments/preview before execution. Preserve default deny and audit.
5. **Actual streaming.** `build_ollama_model` awaits `bound.ainvoke`; its callable
   returns a completed message. `run_chat` awaits a completed graph turn. Sending
   that reply through WebSocket is not token streaming. Design model/event
   streaming, ordering, backpressure, cancellation and structured citations.
   DCL-127's first-token target is an unmeasured target, not a readiness fact.
6. **Authentication bootstrap.** No gateway token name, minting, rotation or
   browser delivery flow exists. Reuse the credential abstraction and register
   the token in `KNOWN_SECRET_NAMES` for purge. Decide how a browser obtains it
   without exposing it in URLs, logs or persisted frontend storage. Specify
   HTTP and WebSocket Origin/Host behavior, missing/null Origin policy, size
   limits and rate limits; loopback alone is insufficient as a contract.
7. **Long-lived document lifecycle.** `DocumentWatcher` is not started anywhere
   in the CLI; its handler only implements create/modify. `ChangeBuffer` is an
   unsynchronized dictionary, while watchdog callbacks run outside the async
   loop. Specify safe event handoff, delete/move handling, reconciliation,
   indexing/search coordination, retry and shutdown. DocumentStore calls
   synchronous Chroma add/query/delete inside async methods; schedule blocking
   work deliberately before claiming concurrent gateway responsiveness. Existing
   watcher tests are synthetic debounce/handler tests, not a daemon integration test.
8. **Cold DB initialization — resolved.** Engine initialization now occurs
   outside the shared factory lock. Factory-first and concurrent cold-start
   regression tests pass without changing singleton semantics. Preserve these
   regressions when extracting services; see the
   [dated Python baseline](history/python-baseline-2026-10-25.md).
9. **Settings persistence and tool rebinding.** `get_settings` is process-cached
   environment configuration; no mutable persistent settings service exists.
   Define which changes require restart and how workspace/model/language changes
   update graph tools, document stores, watcher and plugin host consistently.
   Browser folder selection must not bypass workspace containment or pretend it
   can freely read arbitrary server paths. Native selection belongs to desktop
   integration unless a browser-compatible flow is explicitly designed.
10. **UI and runtime assets.** `ui/` has only placeholders. The removed
    architecture viewers were documentation, not a product UI. Build the approved vanilla JS/local CSS/EN+FR
    surface separately. Render model/document text as untrusted content; test
    markup injection as well as prompt injection. Do not add runtime CDNs.

## Limits that remain release gates

Audit persistence currently catches errors and continues; this is explicit and
covered by `test_db_logger_swallows_storage_errors`, not a durable-audit guarantee
on failure. `EgressMonitor` patches process-wide httpx and has pending sync audit
tasks: give it one application owner and a shutdown policy, not one per request.
Index currently constructs a host without audit and has no egress monitor wrapper;
reuse the indexing service with gateway audit wiring, not the CLI wrapper verbatim.

`ensure_schema` uses `create_all`, not migration upgrades/stamping; built-in
plugins and migration files are outside the wheel package list. Resolve packaging
before installer/release, not by claiming development checkout tests cover it.
Episodic memory population and optional brain wrappers are not enabled by the
presence of their modules. Do not make them hidden prerequisites for the first
safe gateway slice; scope them explicitly in the detailed spec.

## Proposed order, awaiting detailed design

1. Agree the security/session/approval/settings contracts above and write the
   failing security and lifecycle tests. The cold DB initialization prerequisite has since been fixed; preserve its regression tests.
2. Extract CLI-independent application/session assembly with deterministic
   shutdown; preserve CLI behavior and safety wrappers in regression tests.
3. Implement loopback/auth/Origin/Host/limits before enabling functional routes.
4. Add one end-to-end slice: authenticated chat, correlated human approval,
   audited tool execution, task IDs and disconnect denial; then real streaming.
5. Add documents/progress/reconciliation and plugin enable/disable/revoke, then
   audit/settings/status and the local EN/FR UI. Measure latency rather than
   treating the historical estimates as commitments.

No phase branch was created. Before implementation, identify the previous phase's
branch/ref and follow the branch-per-phase rule; current checkout is `main`.

## Repository and verification scope

Current documentation is Markdown. The optional architecture websites, their
site-only specification, design-tool metadata and four completed execution plans
were removed at the owner's request. This does not remove the planned product UI
under `ui/`. See the [documentation index](README.md) for retained context and
recovery references; do not reintroduce the sites as a Phase 9 prerequisite.

The [dated Python baseline](history/python-baseline-2026-10-25.md) records the
full checks after the DB fix: frozen sync, Ruff and mypy passed; pytest reported
786 passed and one environment-related symlink skip. These are dated local
results, not a claim about remote CI or gateway security. No new product tests
or model benchmarks were run during the subsequent Markdown consistency review.

The original assessment and former site validation logs remain recoverable from
Git commit `5f168db`. They are not part of the current build or test procedure.
