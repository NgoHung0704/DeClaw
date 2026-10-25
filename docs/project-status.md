# Current implementation status

Source inspection: 2026-10-25. This snapshot is not a fresh test or benchmark run.

| Area | Evidence and current scope |
| --- | --- |
| CLI and agent | `declaw/main.py:chat`, `declaw/brain/repl.py:build_brain`, and `declaw/brain/loop.py` assemble model/tool execution. |
| Filesystem tools | `declaw/tools/registry.py` registers typed tools, confirmation, sanitizer and audit wrappers. |
| Plugin host | `declaw/plugin_host/host.py` and `declaw_plugin_sdk/` implement supervised subprocesses and IPC. This is not an OS sandbox. |
| Document intelligence | `declaw/documents/session.py:build_document_stack` shares index/chat assembly; `plugins/builtin/doc-intel/` parses; core owns embedding, storage, retrieval and actions. |
| Watcher | Component exists in `declaw/documents/watcher.py`; not started by the current CLI. Reconciliation runs on indexing. |
| Memory | Components exist under `declaw/memory/`; `with_memory` is not in the default `build_brain` stack. Do not assume episodic memory is populated by chat. |
| Gateway | `declaw/main.py:start` and `stop` report unimplemented; `declaw/gateway/` is scaffolding. FastAPI being installed is not API availability. |
| Desktop and installer | `ui/` and `tauri/` are scaffolding; no connected end-user desktop release is established. |
| Shell sandbox | Deferred from v0.1; no product shell tool is exposed. |

Phase 0, 1, 2, 4, 5, 6 (buildable core), 7, 8a and 8b completion
was recorded in the historical development log. Phase 9 is the next planned
product phase, not a feature implemented by this documentation update.
DCL-071/072/073 remain deferred until a plugin actually needs credentials;
DCL-082 requires the future UI. The approved Phase 7–9 roadmap supersedes older
ticket assumptions: [roadmap](superpowers/specs/2026-08-23-phase-7-9-roadmap.md).

## Limits to preserve in proposals

- Chroma text payloads are encrypted; vectors and some metadata are not. SQLite
  is not wholly encrypted. Logical deletion is not a disk scrub.
- HTTP observation covers instrumented core-process `httpx` calls, not every
  process or all network egress.
- The default brain uses context-window trimming. Repair, summarizing compaction,
  memory retrieval and a system prompt must not be described as enabled merely
  because their helpers exist. Inspect `build_brain` and `chat` before changing them.
- Historical sanitizer scores differ substantially between development and
  held-out corpora. Do not turn a dated corpus score into a security guarantee.
- Document organization validates before execution but is not an atomic batch.
  Chat audit task IDs, packaged migrations and memory population remain follow-ups
  recorded in history; verify wiring before claiming they are resolved.

For any new task, verify the relevant row against the current checkout. Update
this file when executable behavior changes; put dated measurements in a separate
report with command, environment and corpus. Do not carry forward old test counts
as current validation.

## Phase 9 assessment

The [2026-10-25 readiness assessment](phase-9-readiness.md) identifies reusable CLI services, missing gateway/UI contracts and a cold DB factory initialization deadlock reproduced in isolation. Phase 9 is ready for detailed design, not implemented. No product behavior changed during the documentation cleanup.
