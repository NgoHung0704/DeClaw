# DeClaw code map

Read [status](project-status.md) first. This is a navigation map, not proof that
every component is wired into the product. Start from a user-facing entry point,
then follow dependencies and tests for the task at hand.

| Task / boundary | Start reading | Relevant tests |
| --- | --- | --- |
| CLI session and assembly | `declaw/main.py`, `declaw/brain/repl.py` | `tests/unit/test_repl.py`, `tests/integration/test_chat_repl.py` |
| Model, state, execution loop | `declaw/brain/loop.py`, `state.py`, `chat_model.py` | `tests/unit/test_loop.py`, `test_state.py`, `test_chat_model.py` |
| Context and optional memory | `declaw/brain/context.py`, `compaction.py`, `repair.py`, `memory_context.py` | `tests/unit/test_context.py`, `test_compaction.py`, `test_repair.py`, `test_memory_context.py` |
| Tool contracts and approval | `declaw/tools/base.py`, `registry.py`, `confirmation.py` | `tests/unit/test_tools_base.py`, `test_tools_registry.py`, `test_tools_confirmation.py` |
| Workspace filesystem | `declaw/tools/builtin/filesystem.py`, `_paths.py` | `tests/unit/test_tools_filesystem.py`, `test_path_traversal.py` |
| Documents: indexing and storage | `declaw/documents/session.py`, `indexer.py`, `catalog.py`, `store.py` | `tests/unit/test_documents_indexer.py`, `test_documents_store.py`, `test_documents_catalog.py` |
| Documents: search and actions | `declaw/documents/tools.py`, `search.py`, `citations.py`, `actions.py` | `tests/unit/test_documents_search.py`, `test_documents_actions.py`, `tests/integration/test_document_actions_e2e.py` |
| Parse in a plugin subprocess | `plugins/builtin/doc-intel/main.py`, `parsers/`, `chunker.py` | `tests/unit/doc_intel/`, `tests/integration/test_doc_intel_plugin.py` |
| Plugin lifecycle and permissions | `declaw/plugin_host/host.py`, `process.py`, `supervisor.py`, `permissions.py`, `signing.py` | `tests/integration/test_plugin_host.py`, `test_plugin_supervision.py`, `tests/security/test_plugin_isolation.py` |
| Plugin IPC contract | `declaw_plugin_sdk/protocol.py`, `runtime.py`, `declaw/plugin_host/ipc.py` | `tests/unit/test_plugin_protocol.py`, `test_plugin_runtime.py`, `test_plugin_ipc.py` |
| Untrusted text | `declaw/sanitizer/pipeline.py`, `sanitizer.py`, `classifier.py`, `quarantine.py` | `tests/unit/test_sanitizer_pipeline.py`, `test_sanitizer.py`, `tests/security/test_documents_isolation.py` |
| State, encryption and credentials | `declaw/db/`, `declaw/memory/`, `declaw/credentials/`, `alembic/` | `tests/unit/test_db.py`, `test_memory_crypto.py`, `test_credentials_store.py`, `test_credentials_fallback.py` |
| Audit and network observation | `declaw/audit/tooling.py`, `logger.py`, `egress.py`, `report.py` | `tests/unit/test_audit_events.py`, `test_audit_logger.py`, `test_audit_egress.py` |
| Configuration and defaults | `declaw/config.py`, `.env.example`, `pyproject.toml`, `uv.lock` | `tests/unit/test_config.py` |
| Architecture documentation site | `docs-site/package.json`, `docs-site/` | `npm run guards` and `npm run build` in `docs-site/` |

Filenames after the first path in a cell are relative to the same directory.

## Flows to trace before changing behavior

**Chat:** `main.chat` assembles audit, sanitizer, plugin host and registry;
`build_brain` binds the same tools to the model and graph; the graph alternates
model and tool execution. Non-READ tools pass confirmation, external READ text
passes sanitization, and audit wraps execution.

**Index:** `main.index` → shared document stack → catalog/hash comparison → host
IPC → doc-intel parser → core embeddings and encrypted text storage → catalog
update. Inspect failure ordering and subtree reconciliation before modifying it.

**Retrieve:** document search → query embedding → top-k chunks → per-chunk
sanitizer with hash-based cache → source metadata/citations → model observation.
Indexing does not pre-classify every chunk.

**Change documents:** registry confirmation → workspace-contained typed action
→ execution/audit. Summarization also retrieves screened content; trace both the
read and write boundaries rather than assuming approval alone makes content safe.

## Before proposing / after changing

Describe the current path and affected callers, reference the relevant code and
tests, and distinguish a requested feature from an already wired helper. Check
failure/denial paths for security-sensitive work. Run checks appropriate to the
change and update status/decisions with supporting evidence. Use the historical
log only to recover the reason for a choice.

## Planned gateway work

Before touching the gateway/UI scaffolds, read the [Phase 9 assessment](phase-9-readiness.md). Trace session assembly in main.chat/main.index, graph invocation in brain.repl, confirmation and audit wrappers, plugin lifecycle, and document watcher/indexer ownership. Existing component tests do not establish HTTP/WebSocket security or multi-session behavior.
