# Active architecture decisions

This index separates current direction from historical discussion. Source
inspection date: 2026-10-25. A planned decision does not imply implementation.

| Decision | State and rationale / evidence |
| --- | --- |
| Python 3.12+, uv, LangGraph, Ollama | Current core stack; see `pyproject.toml`, `uv.lock`, `declaw/brain/`. Defaults live in `declaw/config.py`, not in old benchmark notes. |
| Local core with subprocess plugins | Current CLI is one Python application with a process per loaded plugin. Built-in filesystem tools and core document services are not all subprocess plugins. See `declaw/main.py` and `declaw/plugin_host/host.py`. |
| Thin doc-intel plugin | Plugin parses; core owns embeddings, encryption, vector storage, search and citations. Approved [Phase 7–9 roadmap](specs/2026-08-23-phase-7-9-roadmap.md). |
| Retrieval-time sanitization | Screen top-k retrieved chunks and cache verdicts by hash; do not classify every indexed chunk. Same roadmap; `declaw/documents/search.py`. |
| Typed tools, containment, confirmation and audit | Preserve the invariants in [AGENTS.md](../AGENTS.md); see registry, filesystem paths and audit wrappers. |
| Subprocess trust | Allowlisted environment and crash/lifecycle supervision are not OS sandboxing or a barrier to same-user resources/keyring. See `declaw/plugin_host/process.py` and the Phase 7 spec. |
| Credential storage | OS keyring with encrypted fallback; see `declaw/credentials/`. Do not claim keyring is the only implemented backend. |
| Shell execution | Dropped from v0.1: typed document/file actions need no shell, while Docker setup adds end-user burden. If shell returns, approved Docker isolation is required; never add an unsandboxed fallback. See [AGENTS.md](../AGENTS.md#invariants). |
| Gateway and desktop | Planned FastAPI loopback gateway (`127.0.0.1:7842`) and Windows-first Tauri 2 shell; currently scaffolding. |
| Repository documentation | Markdown status, code map, decisions and dated history are retained. Optional architecture viewers and their site-specific CI were removed by owner request on 2026-10-25; this does not alter the planned product UI. See [documentation index](README.md). |
| Frontend assets | Planned Vanilla JS, English/French, locally vendored assets. Tailwind CDN is superseded by the approved roadmap's no-runtime-CDN correction. |
| Third-party installation and plugin secrets | v0.1 uses built-ins with enable/disable and one-time audited auto-grants; revocations persist. Third-party installation requires code digests in the signed manifest and removal of built-in auto-grant assumptions. Current signatures cover manifest bytes only. Defer plugin credential APIs until a real plugin needs secrets; see roadmap and host tests. |
| Source attribution and evaluation | Sources derive from retrieval metadata, not model-authored citations. Benchmarks separate development and externally sourced held-out sets; no private client documents in committed fixtures. See `declaw/documents/citations.py`, `declaw/documents/corpus/heldout.py` and the Phase 8b spec. |
| License | Project metadata declares AGPL-3.0-or-later; see `pyproject.toml`. A possible future commercial license is not an implemented distribution/licensing flow. |
| Brain wrappers and prompts | Repair, compaction, memory retrieval and system-prompt activation require measured validation before default wiring. See `declaw/brain/repl.py` and `declaw/main.py`; old Mistral findings are historical, not proof about current Qwen behavior. |

Phase 9 depends on the completed sanitizer work. The old requirement that Phase 3
must precede Phase 9 is superseded for the shell-free v0.1 scope. This does not
waive isolation for any future shell feature. Security hardening remains a release
gate; component completion is not production certification.

When changing a decision, record the trigger, chosen behavior, alternatives and
evidence in a dated spec/ADR under `docs/`, then update this index. Keep concise
dated validation reports under `history/`; completed long logs may remain in Git
history instead of the working tree. Ask the user when a security or architecture
choice remains unresolved rather than treating a historical idea as approved.
