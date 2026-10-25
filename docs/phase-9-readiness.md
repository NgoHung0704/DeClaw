# Phase 9 readiness assessment

Reviewed: 2026-10-25 against the current working tree on `main`, including existing
uncommitted documentation/tooling changes. This is an assessment and handoff, not
a Phase 9 spec approval or implementation. No product code or dependencies change.

## Verdict

Ready to write the detailed Phase 9 specification; not ready to expose a gateway
by wrapping the CLI. The approved [roadmap](superpowers/specs/2026-08-23-phase-7-9-roadmap.md)
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

## Missing work and prerequisites

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
   indexing/search coordination, retry and shutdown. DocumentStore calls synchronous Chroma add/query/delete inside async methods; decide how blocking work is scheduled before claiming concurrent gateway responsiveness. Existing watcher tests are
   synthetic debounce/handler tests, not a real daemon integration test.
8. **Cold DB factory deadlock.** `get_sessionmaker` acquires `_lock`, then calls
   `get_engine`, which acquires the same non-reentrant `threading.Lock` if the
   engine is cold. Current chat/index initialize the engine first and mask this
   order dependency. A bounded isolated probe, with `build_engine` stubbed and no
   settings/DB access, left the worker blocked and `_engine` unset. Add a cold
   initialization regression test and fix before using these factories as web
   dependencies. This assessment does not implement the fix.
9. **Settings persistence and tool rebinding.** `get_settings` is process-cached
   environment configuration; no mutable persistent settings service exists.
   Define which changes require restart and how workspace/model/language changes
   update graph tools, document stores, watcher and plugin host consistently.
   Browser folder selection must not bypass workspace containment or pretend it
   can freely read arbitrary server paths. Native selection belongs to desktop
   integration unless a browser-compatible flow is explicitly designed.
10. **UI and runtime assets.** `ui/` has only placeholders; neither architecture
    viewer is the product UI. Build the approved vanilla JS/local CSS/EN+FR
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
   failing security and lifecycle tests. Fix the cold DB initialization defect.
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

## Repository cleanup and handoff

Applied here:

- Replaced the contradictory documentation index with current-context links and
  links to the existing Phase 7/8a/8b reviews. Removed repeated outdated security
  and product-state claims from that index; historical reviews remain intact.
- Synchronized backlog authority and the approved built-in-only permission/plugin
  scope. Pending Phase 9 tickets stay unchecked; no architecture option is chosen.
- Documented the separate architecture viewers and their build ownership. Migrated 17 stale CLAUDE.md citations: seven current principles now cite AGENTS.md and ten historical debt references cite the archive with verified anchors. Benchmark prose explicitly marks historical results.
- Removed tracked `docs-site/tsconfig.tsbuildinfo` (1,291 bytes at inspection) and
  ignored future copies; removed four zero-byte `.gitkeep` files in populated
  directories (`docs`, `scripts`, `plugins/builtin`, sanitizer corpus).

Kept deliberately:

- Lockfiles, held-out fixtures/attribution, tests and dated plans/reviews: these
  support reproducibility and rationale. File size alone is not obsolescence.
- Empty gateway/UI/Tauri/sandbox scaffolds: recorded roadmap boundaries referenced
  by architecture content; deleting them now would create broken references.
- Both architecture sites: one is CI-published, one has its own publication
  workflow. Choose a canonical viewer and migrate unique content before retiring
  either; deletion is not safe merely because both visualize architecture.
- The ignored original bootstrap prompt and existing `.superdesign` artifacts:
  local/history provenance is not established as disposable. The index marks the
  bootstrap prompt non-authoritative. No generated tool environments or user
  caches were recursively removed.

Dependency slimming candidates: direct imports of docker, playwright and apscheduler were not found under declaw, declaw_plugin_sdk, plugins, scripts or tests. The Docker preflight invokes the Docker CLI through subprocess, not the Python SDK. These declared dependencies merit a separate optional-dependency review with lockfile and full CI validation; absence of imports alone does not prove removal safe for every packaging workflow. No dependencies were removed here. Keep the FastAPI/uvicorn/websockets dependencies aligned with the approved upcoming phase rather than deleting them merely because the gateway is not built yet.

The cleanup reduces ambiguity more than disk usage. The largest tracked files
include reproducibility locks and legal benchmark fixtures; substantial local
space savings would require a separate, measured cache/dependency cleanup.

## Verification

- Targeted Python checks: **153 passed** across `test_repl`, `test_loop`,
  `test_tools_confirmation`, `test_tools_registry`, `test_documents_watcher`,
  `test_documents_indexer`, `test_documents_search`, `test_documents_actions`,
  `test_audit_events`, `test_audit_logger`, `test_config`, `test_db` and
  `tests/security/test_documents_isolation.py` using the existing Python 3.12.13
  environment. Ran `python -m pytest <those absolute test paths> -q --tb=short
  --basetemp <fresh writable directory> -o faulthandler_timeout=30` from outside
  the repository, with PYTHONPATH set to the checkout, to avoid loading its .env.
- Initial sandboxed pytest was interrupted during Windows asyncio socket-pair
  setup. The first run outside the sandbox had 95 passes and 58 fixture errors
  due to system temp-directory access denial. A fresh writable basetemp resolved
  that environment issue; the final targeted run had no skips or failures.
- Cold DB initialization probe: daemon thread invokes `get_sessionmaker` with
  both singletons reset and `build_engine` stubbed; after a one-second join,
  `worker.is_alive()` was True and `_engine is None`. No DB/keyring/settings
  access occurred. This is a reproduction, not a committed regression test.
- `docs-site`: `npm ci --no-audit --no-fund` succeeded after retrying outside the
  sandbox following EPERM. Guards initially caught 34 failures from 17 stale
  references; after migration **2,226 tests passed** and `npm run build` passed.
  Local Node was v24.16.0; CI specifies Node 22. Build warns about a JavaScript
  chunk above 500 kB; no bundle optimization is claimed.
- `architecture-site`: `npm test` passed **5 tests**. No browser interaction or
  deployment validation was rerun; only its README changed.
- Full Python CI (`uv sync --frozen`, Ruff, mypy and full pytest) and live Ollama
  benchmarks were not run. These results do not certify gateway security.
- All changes remain uncommitted. Source links generated from HEAD can point to
  the previous commit until the new documentation and citations are committed;
  commit and rebuild before publishing. No publication was performed.

- Local documentation validation: 106 Markdown link targets across 11 current documents resolved; remote URLs and heading anchors were not checked. git diff --check passed. The SHA-256 of .claude/settings.json matched the start-of-turn value.
