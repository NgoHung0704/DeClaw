# DeClaw — Tickets

> Single source of work plan. Mark `[x]` when done. Implementation order is strict: complete each phase before the next. Security phases (4, 5) gate everything after them.

**Legend**: ⚠️ critical • ⭐ MVP heart • Each ticket has: ID, Title, Description, Acceptance Criteria, Dependencies, Estimate.

---

## 📦 PHASE 0 — PROJECT FOUNDATION (Week 1)

### [x] DCL-001 — Project scaffold
- **Description**: Initialize uv project, `pyproject.toml`, `.gitignore`, full folder structure (see project structure in CLAUDE prompt).
- **Acceptance**:
  - `uv sync` succeeds
  - `uv run declaw --help` prints CLI help
  - All directories in project structure exist with `__init__.py` for Python packages
- **Dependencies**: none
- **Estimate**: 0.5d

### [x] DCL-002 — CLAUDE.md living context document
- **Description**: Create `CLAUDE.md` per template in prompt; update after every ticket.
- **Acceptance**: File exists with current state, locked decisions, 7 principles, completed/in-progress sections.
- **Dependencies**: DCL-001
- **Estimate**: 0.25d

### [x] DCL-003 — Ollama integration + health check
- **Description**: Async Ollama client wrapper, health check (model reachable, Mistral 7B pulled).
- **Acceptance**:
  - `declaw status` reports Ollama up/down + Mistral 7B presence
  - Unit test mocks Ollama HTTP responses
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [x] DCL-004 — Config system with pydantic-settings
- **Description**: `declaw/config.py` typed settings, `.env` support, env var prefix `DECLAW_`.
- **Acceptance**: Settings model loads from `.env`, validates types, exposes singleton.
- **Dependencies**: DCL-001
- **Estimate**: 0.25d

### [x] DCL-005 — SQLite + SQLModel setup with migrations
- **Description**: Engine, session, baseline models for tasks/audit; Alembic init.
- **Acceptance**: `alembic upgrade head` creates schema; CRUD smoke test passes.
- **Dependencies**: DCL-004
- **Estimate**: 0.5d

### [x] DCL-006 — Structured JSON logging (loguru)
- **Description**: JSON sink, request ID propagation, log levels via env.
- **Acceptance**: Log records are valid JSON with timestamp, level, request_id.
- **Dependencies**: DCL-004
- **Estimate**: 0.25d

### [x] DCL-007 — Pre-flight check script
- **Description**: `scripts/preflight.py` checks Ollama running, Mistral pulled, Docker available, ports free.
- **Acceptance**: Returns non-zero with actionable message on failure.
- **Dependencies**: DCL-003
- **Estimate**: 0.5d

---

## 🧠 PHASE 1 — CORE BRAIN (Weeks 2-3)

### [x] DCL-010 — LangGraph basic agentic loop
- **Description**: Minimal think → tool-call → observe loop.
- **Acceptance**: Loop processes a user turn end-to-end with a stub tool.
- **Dependencies**: DCL-003
- **Estimate**: 1d

### [x] DCL-011 — AgentState schema with typed slots
- **Description**: Pydantic state: messages, scratchpad, current plan, tool calls, audit refs.
- **Acceptance**: State serializes/deserializes; mypy strict passes.
- **Dependencies**: DCL-010
- **Estimate**: 0.5d

### [x] DCL-012 — Ollama function calling integration
- **Description**: Wire Mistral tool-use through langchain-ollama.
- **Acceptance**: Model returns structured tool call; brain routes to executor.
- **Dependencies**: DCL-010
- **Estimate**: 1d

### [x] DCL-013 — Tool output parser + retry/repair
- **Description**: Parse model output; on malformed JSON, retry with corrective prompt (max 2).
- **Acceptance**: Malformed outputs from corpus pass after retry.
- **Dependencies**: DCL-012
- **Estimate**: 0.5d

### [x] DCL-014 — Context window management (Mistral 32k)
- **Description**: Token counter, soft/hard caps with eviction policy.
- **Acceptance**: Long conversation does not exceed 32k tokens.
- **Dependencies**: DCL-011
- **Estimate**: 0.5d

### [x] DCL-015 — Context compaction strategy on overflow
- **Description**: Summarize oldest N turns into a compact note; preserve task plan + recent.
- **Acceptance**: Compaction triggered at threshold; downstream behavior intact.
- **Dependencies**: DCL-014
- **Estimate**: 1d

### [x] DCL-016 — CLI test interface
- **Description**: `declaw chat --debug` REPL using the brain.
- **Acceptance**: Multi-turn chat works against running Ollama.
- **Dependencies**: DCL-010
- **Estimate**: 0.5d

### [x] DCL-017 — System prompt template (FR + EN)
- **Description**: Templated prompts with locale switch; embed 7 principles.
- **Acceptance**: `DECLAW_LANGUAGE=fr` switches prompt language.
- **Dependencies**: DCL-010
- **Estimate**: 0.25d

---

## 🛠️ PHASE 2 — TOOL LAYER (Week 3-4)

### [x] DCL-020 — BaseTool abstract class with typed params
- **Description**: Pydantic-validated tool inputs/outputs. NO raw shell strings.
- **Acceptance**: A subclass passes mypy strict; runtime rejects invalid params.
- **Dependencies**: DCL-011
- **Estimate**: 0.5d

### [ ] DCL-021 — Tool: filesystem_read (workspace-scoped)
- **Description**: Reads file content limited to workspace root; rejects traversal.
- **Acceptance**: Path outside workspace raises; tests cover `..`, symlink, NTFS short names.
- **Dependencies**: DCL-020
- **Estimate**: 0.5d

### [ ] DCL-022 — Tool: filesystem_write (+ confirmation)
- **Description**: Workspace-scoped write; user confirmation required.
- **Acceptance**: Without confirmation token, write rejected.
- **Dependencies**: DCL-020
- **Estimate**: 0.5d

### [ ] DCL-023 — Tool: filesystem_move (+ confirmation)
- **Description**: Move within workspace only; never cross-volume; confirmation required.
- **Acceptance**: Cross-volume rejected; confirmation enforced.
- **Dependencies**: DCL-020
- **Estimate**: 0.5d

### [ ] DCL-024 — Tool: filesystem_list (workspace-scoped)
- **Description**: List entries with metadata (size, mtime, type).
- **Acceptance**: Out-of-scope paths rejected.
- **Dependencies**: DCL-020
- **Estimate**: 0.25d

### [ ] DCL-025 — Tool registry (typed registration)
- **Description**: Registration via decorator; no dynamic `eval`/`exec`.
- **Acceptance**: Unknown tool ID rejected; registry exposes JSON schema.
- **Dependencies**: DCL-020
- **Estimate**: 0.5d

### [ ] DCL-026 — Path traversal protection unit tests
- **Description**: 30+ adversarial paths (UTF-8 tricks, double encoding, alt streams).
- **Acceptance**: All adversarial paths rejected.
- **Dependencies**: DCL-021
- **Estimate**: 0.5d

---

## 🔒 PHASE 3 — SANDBOX LAYER (Week 4-5) ⚠️ CRITICAL

### [ ] DCL-030 — Docker SDK executor core
- **Description**: Run container with image, command, mounts, env; capture stdout/stderr/exit.
- **Acceptance**: Hello-world container returns 0 with output.
- **Dependencies**: DCL-006
- **Estimate**: 1d

### [ ] DCL-031 — Python sandbox Dockerfile
- **Description**: Read-only fs, no network, drop all capabilities, non-root user.
- **Acceptance**: Container has no `CAP_NET_*`; rootfs is RO.
- **Dependencies**: DCL-030
- **Estimate**: 0.5d

### [ ] DCL-032 — Shell sandbox Dockerfile (Alpine minimal)
- **Description**: Minimal busybox/Alpine.
- **Acceptance**: Image < 20MB; runs `sh -c`.
- **Dependencies**: DCL-030
- **Estimate**: 0.25d

### [ ] DCL-033 — Filesystem mount policy
- **Description**: Workspace bind only; everything else read-only or absent.
- **Acceptance**: Writing outside workspace fails.
- **Dependencies**: DCL-030
- **Estimate**: 0.5d

### [ ] DCL-034 — Network policy (deny-all default)
- **Description**: `--network=none` by default; explicit whitelist optional (future).
- **Acceptance**: `curl example.com` from sandbox fails.
- **Dependencies**: DCL-031
- **Estimate**: 0.25d

### [ ] DCL-035 — Resource limits
- **Description**: 1 CPU, 512MB mem, 30s timeout default.
- **Acceptance**: Forkbomb / memhog containers killed.
- **Dependencies**: DCL-030
- **Estimate**: 0.5d

### [ ] DCL-036 — Sandbox escape detection test suite
- **Description**: 10+ known CVE patterns (capabilities, proc exposure, /sys mounts).
- **Acceptance**: All escapes blocked.
- **Dependencies**: DCL-031
- **Estimate**: 1d

### [ ] DCL-037 — Graceful degradation when Docker unavailable
- **Description**: Shell tools **disabled**, never bypassed; clear UI message.
- **Acceptance**: With Docker stopped, shell tool unavailable; doc-intel still works.
- **Dependencies**: DCL-030
- **Estimate**: 0.25d

### [ ] DCL-038 — Container teardown verification
- **Description**: No leaked containers, networks, volumes after run.
- **Acceptance**: After 100 runs, `docker ps -a` count unchanged.
- **Dependencies**: DCL-030
- **Estimate**: 0.5d

---

## 🛡️ PHASE 4 — SANITIZER LAYER (Week 5-6) ⚠️ CRITICAL

### [ ] DCL-040 — Second Mistral instance for sanitizer
- **Description**: Separate Ollama session/context.
- **Acceptance**: Sanitizer has no shared state with brain.
- **Dependencies**: DCL-003
- **Estimate**: 0.5d

### [ ] DCL-041 — Sanitizer system prompt (locked)
- **Description**: No tool access; cannot see conversation.
- **Acceptance**: Prompt rejects requests outside SAFE/UNSAFE schema.
- **Dependencies**: DCL-040
- **Estimate**: 0.5d

### [ ] DCL-042 — Structured output schema (verdict + reason)
- **Description**: Pydantic `SanitizerVerdict`.
- **Acceptance**: Invalid outputs trigger retry.
- **Dependencies**: DCL-041
- **Estimate**: 0.25d

### [ ] DCL-043 — Integration into tool input pipeline
- **Description**: All external content passes sanitizer before brain sees it.
- **Acceptance**: Unsanitized external content path is unreachable.
- **Dependencies**: DCL-042, DCL-021
- **Estimate**: 0.5d

### [ ] DCL-044 — Quarantine system for UNSAFE content
- **Description**: Store quarantined content; never surface to brain.
- **Acceptance**: Quarantined items visible in UI only.
- **Dependencies**: DCL-043
- **Estimate**: 0.5d

### [ ] DCL-045 — Audit trail for quarantine events
- **Description**: Log every quarantine with hash + source.
- **Acceptance**: Quarantine appears in audit log.
- **Dependencies**: DCL-044, DCL-061
- **Estimate**: 0.25d

### [ ] DCL-046 — Injection corpus (FR + EN, 50+)
- **Description**: Known payloads; tag with severity.
- **Acceptance**: Corpus stored in `declaw/sanitizer/corpus/`.
- **Dependencies**: DCL-040
- **Estimate**: 0.5d

### [ ] DCL-047 — False positive benchmark (< 2%)
- **Description**: Benign corpus; measure FP rate.
- **Acceptance**: FP < 2%.
- **Dependencies**: DCL-046
- **Estimate**: 0.5d

### [ ] DCL-048 — Latency benchmark (< 500ms p95)
- **Description**: Measure per-chunk latency on dev hardware.
- **Acceptance**: p95 < 500ms.
- **Dependencies**: DCL-046
- **Estimate**: 0.25d

---

## 💾 PHASE 5 — MEMORY & AUDIT (Week 6-7)

### [ ] DCL-050 — ChromaDB setup + persistent client
- **Description**: Persistent local client; collection-per-purpose.
- **Acceptance**: Restart preserves vectors.
- **Dependencies**: DCL-004
- **Estimate**: 0.5d

### [ ] DCL-051 — At-rest encryption (Fernet)
- **Description**: Encrypt collection files; key in keyring.
- **Acceptance**: Raw files unreadable without key.
- **Dependencies**: DCL-050, DCL-070
- **Estimate**: 0.5d

### [ ] DCL-052 — Short-term conversation buffer
- **Description**: In-memory ring; size-bounded.
- **Acceptance**: Bound respected; eviction order correct.
- **Dependencies**: DCL-011
- **Estimate**: 0.25d

### [ ] DCL-053 — Long-term semantic memory
- **Description**: Vector search by topic.
- **Acceptance**: top-k retrieves expected docs.
- **Dependencies**: DCL-050
- **Estimate**: 0.5d

### [ ] DCL-054 — Episodic memory (task history)
- **Description**: Per-task records linked to audit.
- **Acceptance**: Query by date/tag works.
- **Dependencies**: DCL-005
- **Estimate**: 0.5d

### [ ] DCL-055 — Memory retrieval in Brain context assembly
- **Description**: Inject top-k memories into prompt with token budget.
- **Acceptance**: Brain uses retrieved memory in answers.
- **Dependencies**: DCL-053
- **Estimate**: 0.5d

### [ ] DCL-056 — Memory export (GDPR portability)
- **Description**: JSON dump of user data.
- **Acceptance**: `declaw memory export` writes complete archive.
- **Dependencies**: DCL-053, DCL-054
- **Estimate**: 0.5d

### [ ] DCL-057 — Memory wipe (right to be forgotten)
- **Description**: Delete all stored vectors + history.
- **Acceptance**: After wipe, retrieval is empty; audit retains anonymized record.
- **Dependencies**: DCL-053
- **Estimate**: 0.5d

### [ ] DCL-060 — Audit event schema (typed)
- **Description**: Pydantic events: ToolCall, NetworkCall, Quarantine, PermissionPrompt.
- **Acceptance**: Events persisted; schema versioned.
- **Dependencies**: DCL-005
- **Estimate**: 0.5d

### [ ] DCL-061 — Real-time audit logger in Brain
- **Description**: Every action emits an event.
- **Acceptance**: All tool calls produce events.
- **Dependencies**: DCL-060
- **Estimate**: 0.5d

### [ ] DCL-062 — NL audit summary generator (FR + EN)
- **Description**: Per-task plain-language summary.
- **Acceptance**: Summary mentions actions + “data left device: yes/no”.
- **Dependencies**: DCL-061
- **Estimate**: 0.5d

### [ ] DCL-063 — Daily report
- **Description**: "What did DeClaw do today?" rollup.
- **Acceptance**: Daily report available in UI + CLI.
- **Dependencies**: DCL-062
- **Estimate**: 0.5d

### [ ] DCL-064 — Network egress monitor
- **Description**: Hook outbound network calls (httpx/requests); alert + audit.
- **Acceptance**: Any unintended external call logged + flagged.
- **Dependencies**: DCL-060
- **Estimate**: 1d

### [ ] DCL-065 — Audit export (JSON, Markdown, PDF)
- **Description**: Multi-format export.
- **Acceptance**: Each format renders correctly.
- **Dependencies**: DCL-061
- **Estimate**: 0.5d

---

## 🔑 PHASE 6 — CREDENTIALS & PERMISSIONS (Week 7)

### [ ] DCL-070 — python-keyring wrapper (Windows Credential Manager priority)
- **Description**: CRUD around keyring with namespace.
- **Acceptance**: No plaintext anywhere; uninstaller removes secrets.
- **Dependencies**: DCL-004
- **Estimate**: 0.5d

### [ ] DCL-071 — Credential CRUD API (gated by core)
- **Description**: Plugins access secrets only via core API.
- **Acceptance**: Direct keyring access from plugin process fails.
- **Dependencies**: DCL-070, DCL-090
- **Estimate**: 0.5d

### [ ] DCL-072 — Credential access logging
- **Description**: Which plugin, when, why; rate-limited.
- **Acceptance**: Audit entries written per access.
- **Dependencies**: DCL-071, DCL-061
- **Estimate**: 0.25d

### [ ] DCL-073 — Credential scoping
- **Description**: Only authorized plugins read specific keys.
- **Acceptance**: Unauthorized plugin denied + logged.
- **Dependencies**: DCL-071
- **Estimate**: 0.5d

### [ ] DCL-074 — Encrypted secrets fallback
- **Description**: AES-256 file + key derived from OS user; used only if keyring missing.
- **Acceptance**: Fallback path documented; covered by tests.
- **Dependencies**: DCL-070
- **Estimate**: 0.5d

### [ ] DCL-080 — `plugin.yaml` schema + validator
- **Description**: Pydantic model; semantic checks (denied vs requested).
- **Acceptance**: Invalid manifests rejected with helpful error.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-081 — Permission enforcement middleware
- **Description**: Every tool call checked vs plugin permissions.
- **Acceptance**: Denied call returns structured error + audit event.
- **Dependencies**: DCL-080
- **Estimate**: 0.5d

### [ ] DCL-082 — Permission request UI dialog
- **Description**: Mobile-app-style prompts.
- **Acceptance**: Decline halts install; accept stores grant.
- **Dependencies**: DCL-081, DCL-127
- **Estimate**: 0.5d

### [ ] DCL-083 — Plugin signature verification (ed25519)
- **Description**: Verify on load; reject unsigned third-party plugins by default.
- **Acceptance**: Tampered plugin rejected.
- **Dependencies**: DCL-080
- **Estimate**: 0.5d

### [ ] DCL-084 — Permission audit log
- **Description**: Grants, denies, revocations recorded.
- **Acceptance**: All transitions visible in audit UI.
- **Dependencies**: DCL-081, DCL-061
- **Estimate**: 0.25d

---

## 🔌 PHASE 7 — PLUGIN HOST (Week 8) ⚠️ ARCHITECTURAL FOUNDATION

### [ ] DCL-090 — Plugin loader (discover plugins/ directory)
- **Description**: Scan builtin + user plugin dirs.
- **Acceptance**: Loader returns plugin index with status.
- **Dependencies**: DCL-080
- **Estimate**: 0.5d

### [ ] DCL-091 — Plugin lifecycle (install/uninstall/update/disable)
- **Description**: CRUD over installed plugins; state persisted.
- **Acceptance**: All transitions update registry.
- **Dependencies**: DCL-090
- **Estimate**: 1d

### [ ] DCL-092 — Subprocess isolation (each plugin its own Python process)
- **Description**: Spawn restricted subprocess (no inherited env, no keyring).
- **Acceptance**: Plugin cannot import declaw internals.
- **Dependencies**: DCL-091
- **Estimate**: 1d

### [ ] DCL-093 — IPC protocol (JSON over stdio, schema-validated)
- **Description**: Request/response + events; size-limited.
- **Acceptance**: Malformed frames rejected; large frames dropped.
- **Dependencies**: DCL-092
- **Estimate**: 1d

### [ ] DCL-094 — Plugin SDK skeleton
- **Description**: `declaw-plugin-sdk` package: BasePlugin, decorators, IPC client.
- **Acceptance**: Sample plugin builds against SDK.
- **Dependencies**: DCL-093
- **Estimate**: 0.5d

### [ ] DCL-095 — Plugin manifest registry
- **Description**: `~/.declaw/plugins/installed.db` via SQLite.
- **Acceptance**: Survives restarts.
- **Dependencies**: DCL-091
- **Estimate**: 0.25d

### [ ] DCL-096 — Plugin crash handling
- **Description**: Crash isolated; core unaffected; auto-restart with backoff.
- **Acceptance**: Killed plugin restarts; repeated crash quarantines plugin.
- **Dependencies**: DCL-092
- **Estimate**: 0.5d

### [ ] DCL-097 — Permission violation handling
- **Description**: Terminate plugin + notify user.
- **Acceptance**: Violation kills process and logs event.
- **Dependencies**: DCL-081, DCL-092
- **Estimate**: 0.25d

---

## 📄 PHASE 8 — DOC-INTEL PLUGIN (Week 9-10) ⭐ THE MVP HEART

### [ ] DCL-100 — doc-intel plugin scaffold + plugin.yaml
- **Description**: Manifest + entrypoint.
- **Acceptance**: Loads and idles cleanly.
- **Dependencies**: DCL-094
- **Estimate**: 0.25d

### [ ] DCL-101 — PDF parser (pypdf + unstructured fallback)
- **Description**: Text-first via pypdf; unstructured for scanned/complex.
- **Acceptance**: 10 sample PDFs parse with > 95% text recall.
- **Dependencies**: DCL-100
- **Estimate**: 1d

### [ ] DCL-102 — DOCX parser
- **Description**: python-docx full-document extraction.
- **Acceptance**: Tables, lists, headings preserved as structure.
- **Dependencies**: DCL-100
- **Estimate**: 0.5d

### [ ] DCL-103 — XLSX parser
- **Description**: openpyxl rows/sheets to structured chunks.
- **Acceptance**: Multi-sheet workbook parsed.
- **Dependencies**: DCL-100
- **Estimate**: 0.5d

### [ ] DCL-104 — TXT/Markdown parser
- **Description**: Plain extractor + frontmatter.
- **Acceptance**: Markdown headings preserved.
- **Dependencies**: DCL-100
- **Estimate**: 0.25d

### [ ] DCL-105 — Document chunker (semantic ~512 tokens)
- **Description**: Heading/paragraph aware.
- **Acceptance**: Average chunk size within target ±15%.
- **Dependencies**: DCL-101..DCL-104
- **Estimate**: 0.5d

### [ ] DCL-106 — Embedding generation (nomic-embed-text via Ollama)
- **Description**: Batched embedding requests.
- **Acceptance**: 1k chunks embedded < 2 min on dev hardware.
- **Dependencies**: DCL-003
- **Estimate**: 0.5d

### [ ] DCL-107 — Indexer pipeline
- **Description**: workspace folder → ChromaDB.
- **Acceptance**: End-to-end indexing of sample workspace.
- **Dependencies**: DCL-106, DCL-050
- **Estimate**: 1d

### [ ] DCL-108 — Incremental indexing
- **Description**: Hash-based change detection.
- **Acceptance**: Unchanged files skipped.
- **Dependencies**: DCL-107
- **Estimate**: 0.5d

### [ ] DCL-109 — File watcher (auto-index)
- **Description**: watchdog watches workspace.
- **Acceptance**: New file indexed within 5s.
- **Dependencies**: DCL-108
- **Estimate**: 0.5d

### [ ] DCL-110 — Semantic search (top-k)
- **Description**: Query embedding → ChromaDB → ranked results.
- **Acceptance**: top-3 relevance > 80% on benchmark.
- **Dependencies**: DCL-107
- **Estimate**: 0.5d

### [ ] DCL-111 — Citation system
- **Description**: Every answer cites doc + page/section.
- **Acceptance**: All RAG answers include citations.
- **Dependencies**: DCL-110
- **Estimate**: 0.5d

### [ ] DCL-112 — RAG prompt template (FR + EN)
- **Description**: Strict instruction to cite; sanitize document chunks.
- **Acceptance**: Localized prompts; chunks sanitized before injection.
- **Dependencies**: DCL-111, DCL-043
- **Estimate**: 0.5d

### [ ] DCL-113 — Action: summarize (writes `summary.md`)
- **Description**: Document- or set-level summary.
- **Acceptance**: Summary readable, cites sources.
- **Dependencies**: DCL-110
- **Estimate**: 0.5d

### [ ] DCL-114 — Action: move file (confirmation required)
- **Description**: Confirmation handshake.
- **Acceptance**: No move without explicit confirmation.
- **Dependencies**: DCL-023
- **Estimate**: 0.25d

### [ ] DCL-115 — Action: rename file (confirmation required)
- **Description**: Workspace-scoped rename with confirmation.
- **Acceptance**: Conflicts handled safely.
- **Dependencies**: DCL-023
- **Estimate**: 0.25d

### [ ] DCL-116 — Action: create folder structure
- **Description**: E.g., “organize invoices by supplier”.
- **Acceptance**: Plan presented to user, then executed on approve.
- **Dependencies**: DCL-114, DCL-115
- **Estimate**: 0.5d

### [ ] DCL-117 — French legal document benchmark suite
- **Description**: 10+ sample contracts; eval Q&A quality.
- **Acceptance**: Benchmark report committed under `tests/fixtures/`.
- **Dependencies**: DCL-110
- **Estimate**: 1d

---

## 🌐 PHASE 9 — GATEWAY & WEB UI (Week 10-11)

### [ ] DCL-120 — FastAPI app (bind 127.0.0.1 only)
- **Description**: Hardened uvicorn config; no LAN bind.
- **Acceptance**: External interface rejects connections.
- **Dependencies**: DCL-004
- **Estimate**: 0.5d

### [ ] DCL-121 — Local token authentication
- **Description**: Random token issued on first run; stored in keyring; required header.
- **Acceptance**: Requests without token rejected.
- **Dependencies**: DCL-070, DCL-120
- **Estimate**: 0.5d

### [ ] DCL-122 — Origin header validation middleware
- **Description**: Defend against CSRF/DNS rebinding (CVE-2026-25253 class).
- **Acceptance**: Foreign Origin/Host rejected.
- **Dependencies**: DCL-120
- **Estimate**: 0.5d

### [ ] DCL-123 — Rate limiting
- **Description**: Per-route soft caps.
- **Acceptance**: Abuse path 429s.
- **Dependencies**: DCL-120
- **Estimate**: 0.25d

### [ ] DCL-124 — Input size limits per endpoint
- **Description**: Reject oversized bodies.
- **Acceptance**: Limits documented + enforced.
- **Dependencies**: DCL-120
- **Estimate**: 0.25d

### [ ] DCL-125 — WebSocket endpoint (real-time chat)
- **Description**: Auth on handshake.
- **Acceptance**: Unauthenticated connection closed.
- **Dependencies**: DCL-121
- **Estimate**: 0.5d

### [ ] DCL-126 — REST API (/chat, /tasks, /audit, /plugins, /settings, /documents)
- **Description**: Typed routes.
- **Acceptance**: OpenAPI schema generated.
- **Dependencies**: DCL-120
- **Estimate**: 1d

### [ ] DCL-127 — UI: Chat interface (streaming)
- **Description**: Token stream via WS.
- **Acceptance**: First token < 1s on dev hardware.
- **Dependencies**: DCL-125
- **Estimate**: 1d

### [ ] DCL-128 — UI: Document panel
- **Description**: Folder picker, indexing status, search.
- **Acceptance**: Folder selection → indexing progress visible.
- **Dependencies**: DCL-107, DCL-126
- **Estimate**: 1d

### [ ] DCL-129 — UI: Audit log viewer
- **Description**: Filter by date, plugin, severity.
- **Acceptance**: Filters work; export buttons present.
- **Dependencies**: DCL-061
- **Estimate**: 0.5d

### [ ] DCL-130 — UI: Plugin manager
- **Description**: List/install/disable/uninstall.
- **Acceptance**: Permission dialog appears at install time.
- **Dependencies**: DCL-091, DCL-082
- **Estimate**: 0.5d

### [ ] DCL-131 — UI: Settings
- **Description**: Model, language, workspace path.
- **Acceptance**: Persists across restarts.
- **Dependencies**: DCL-004
- **Estimate**: 0.5d

### [ ] DCL-132 — UI: i18n (EN + FR)
- **Description**: JSON locales.
- **Acceptance**: All visible strings translated.
- **Dependencies**: DCL-127
- **Estimate**: 0.5d

### [ ] DCL-133 — UI: System status panel
- **Description**: Ollama, Docker, egress monitor health.
- **Acceptance**: Live updates via WS.
- **Dependencies**: DCL-064, DCL-007
- **Estimate**: 0.5d

### [ ] DCL-134 — UI: Permission dialog
- **Description**: As specified in prompt.
- **Acceptance**: Decline halts install.
- **Dependencies**: DCL-082
- **Estimate**: 0.5d

---

## 🖥️ PHASE 10 — TAURI DESKTOP APP (Week 12-13)

### [ ] DCL-140 — Tauri 2.0 project scaffold
- **Description**: src-tauri + assets.
- **Acceptance**: `tauri dev` opens webview.
- **Dependencies**: DCL-127
- **Estimate**: 1d

### [ ] DCL-141 — Python core lifecycle from Tauri
- **Description**: Spawn, monitor, kill on exit.
- **Acceptance**: No orphan Python process after quit.
- **Dependencies**: DCL-140
- **Estimate**: 1d

### [ ] DCL-142 — Webview points to localhost:7842
- **Description**: Wait-for-ready handshake.
- **Acceptance**: No race conditions on first launch.
- **Dependencies**: DCL-141
- **Estimate**: 0.25d

### [ ] DCL-143 — System tray icon + menu
- **Description**: start/stop/quit/status.
- **Acceptance**: Tray actions reflect core state.
- **Dependencies**: DCL-141
- **Estimate**: 0.5d

### [ ] DCL-144 — Native notifications integration
- **Description**: OS-native toasts.
- **Acceptance**: Quarantine/permission events surface natively.
- **Dependencies**: DCL-140
- **Estimate**: 0.5d

### [ ] DCL-145 — Native file picker
- **Description**: Replaces web file input.
- **Acceptance**: Picker returns absolute path.
- **Dependencies**: DCL-140
- **Estimate**: 0.25d

### [ ] DCL-146 — Auto-updater configuration
- **Description**: Signed releases; opt-in by default.
- **Acceptance**: Update flow demoed.
- **Dependencies**: DCL-150
- **Estimate**: 0.5d

### [ ] DCL-147 — Windows MSI installer (priority)
- **Description**: WiX-based MSI; pre-flight integration.
- **Acceptance**: MSI installs + uninstalls cleanly.
- **Dependencies**: DCL-141
- **Estimate**: 1d

### [ ] DCL-148 — macOS .dmg (Phase 2)
- **Description**: dmg + notarization.
- **Acceptance**: dmg runs on macOS 13+.
- **Dependencies**: DCL-141
- **Estimate**: 1d

### [ ] DCL-149 — Linux AppImage (Phase 2)
- **Description**: Single-file AppImage.
- **Acceptance**: Runs on Ubuntu LTS.
- **Dependencies**: DCL-141
- **Estimate**: 0.5d

### [ ] DCL-150 — Code signing (research)
- **Description**: EV cert (Windows), notarization (macOS).
- **Acceptance**: Signed builds published.
- **Dependencies**: DCL-147
- **Estimate**: 1d

---

## 🛡️ PHASE 11 — OS BRIDGE PLUGIN (Week 13-14) — Windows priority

### [ ] DCL-160 — os-bridge plugin scaffold (strict permissions)
- **Description**: Manifest minimizes permissions.
- **Acceptance**: Loads with explicit grant.
- **Dependencies**: DCL-094
- **Estimate**: 0.25d

### [ ] DCL-161 — OS bridge security review document
- **Description**: Threat model in `docs/threat_model.md`.
- **Acceptance**: Reviewed + checked in.
- **Dependencies**: DCL-160
- **Estimate**: 0.5d

### [ ] DCL-162 — Typed API design (NO shell strings)
- **Description**: Enum + int params; whitelists.
- **Acceptance**: No call accepts free-form strings.
- **Dependencies**: DCL-160
- **Estimate**: 0.5d

### [ ] DCL-163 — Audio: get_volume()
- **Description**: Windows COM API.
- **Acceptance**: Returns int 0-100.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-164 — Audio: set_volume(level)
- **Description**: Validated 0-100.
- **Acceptance**: Out-of-range rejected.
- **Dependencies**: DCL-163
- **Estimate**: 0.25d

### [ ] DCL-165 — Audio: mute/unmute
- **Description**: Toggle flags.
- **Acceptance**: State changes verified.
- **Dependencies**: DCL-163
- **Estimate**: 0.25d

### [ ] DCL-166 — Audio: list_audio_sessions (pycaw)
- **Description**: Per-app sessions.
- **Acceptance**: Returns active apps.
- **Dependencies**: DCL-163
- **Estimate**: 0.5d

### [ ] DCL-167 — Audio: set_app_volume(app_name enum, level)
- **Description**: Enum-validated app name.
- **Acceptance**: Unknown app rejected.
- **Dependencies**: DCL-166
- **Estimate**: 0.5d

### [ ] DCL-170 — Display: get_brightness
- **Description**: WMI-based.
- **Acceptance**: Returns int 0-100.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-171 — Display: set_brightness
- **Description**: Validated 0-100.
- **Acceptance**: Out-of-range rejected.
- **Dependencies**: DCL-170
- **Estimate**: 0.25d

### [ ] DCL-172 — Display: toggle_dark_mode
- **Description**: Safe Windows API (no raw registry strings).
- **Acceptance**: Toggle observable.
- **Dependencies**: DCL-162
- **Estimate**: 0.5d

### [ ] DCL-180 — Launcher: open_file(path)
- **Description**: Workspace or user-confirmed.
- **Acceptance**: Out-of-scope rejected.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-181 — Launcher: open_url(url)
- **Description**: Confirmation; default browser.
- **Acceptance**: Confirmation required.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-182 — Launcher: launch_app(app_id whitelist)
- **Description**: ID from user whitelist.
- **Acceptance**: Unknown ID rejected.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-183 — Whitelist editor in UI
- **Description**: User adds allowed apps with friendly name + path.
- **Acceptance**: Persisted + signed by user.
- **Dependencies**: DCL-182, DCL-131
- **Estimate**: 0.5d

### [ ] DCL-190 — Notifications: show_toast
- **Description**: Windows toast.
- **Acceptance**: Toast appears with title/body.
- **Dependencies**: DCL-162
- **Estimate**: 0.25d

### [ ] DCL-200 — OS bridge confirmation flow
- **Description**: Single source of truth for sensitive prompts.
- **Acceptance**: All sensitive APIs use the same flow.
- **Dependencies**: DCL-134
- **Estimate**: 0.5d

### [ ] DCL-201 — OS bridge audit trail integration
- **Description**: Every API call audited.
- **Acceptance**: Audit shows OS bridge calls.
- **Dependencies**: DCL-061
- **Estimate**: 0.25d

### [ ] DCL-202 — OS bridge security test suite
- **Description**: Injection attempts + boundary tests for each API.
- **Acceptance**: All adversarial tests pass.
- **Dependencies**: DCL-162
- **Estimate**: 1d

---

## 🧪 PHASE 12 — SECURITY HARDENING (Continuous, mandatory before v1.0)

### [ ] DCL-210 — Automated security checklist (`declaw security-check`)
- **Description**: CLI runs the gates.
- **Acceptance**: Non-zero on failure.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-211 — pip-audit in CI
- **Description**: Block on high severity.
- **Acceptance**: CI run includes audit step.
- **Dependencies**: DCL-223
- **Estimate**: 0.25d

### [ ] DCL-212 — Bandit static analysis in CI
- **Description**: Fail on medium+ findings outside allow-list.
- **Acceptance**: CI step present.
- **Dependencies**: DCL-223
- **Estimate**: 0.25d

### [ ] DCL-213 — Dependency lockfile + reproducible builds
- **Description**: `uv.lock` committed; reproducible build instructions.
- **Acceptance**: `uv sync --frozen` succeeds.
- **Dependencies**: DCL-001
- **Estimate**: 0.25d

### [ ] DCL-214 — OWASP Top 10 for LLM checklist
- **Description**: Map mitigations to tickets.
- **Acceptance**: `docs/security_model.md` includes mapping.
- **Dependencies**: DCL-217
- **Estimate**: 0.5d

### [ ] DCL-215 — Penetration test script
- **Description**: Simulated injections + sandbox escape attempts.
- **Acceptance**: Suite passes.
- **Dependencies**: DCL-036, DCL-046
- **Estimate**: 1d

### [ ] DCL-216 — Network egress test
- **Description**: Assert no internet reachability during a task.
- **Acceptance**: Test pins external traffic to zero.
- **Dependencies**: DCL-064
- **Estimate**: 0.5d

### [ ] DCL-217 — Threat model document (SECURITY.md)
- **Description**: STRIDE per component.
- **Acceptance**: Document committed.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-218 — Responsible disclosure policy + security@declaw.app
- **Description**: Coordinate via SECURITY.md.
- **Acceptance**: Inbox + policy live.
- **Dependencies**: DCL-217
- **Estimate**: 0.25d

---

## 📚 PHASE 13 — TESTING & QA (Continuous)

### [ ] DCL-220 — pytest + pytest-asyncio setup
- **Description**: Config + helpers.
- **Acceptance**: `uv run pytest` runs cleanly with 0 tests collected initially.
- **Dependencies**: DCL-001
- **Estimate**: 0.25d

### [ ] DCL-221 — Integration test framework
- **Description**: Fixtures for Ollama/Docker.
- **Acceptance**: Integration tests scoped behind markers.
- **Dependencies**: DCL-220
- **Estimate**: 0.5d

### [ ] DCL-222 — Coverage target > 80% (security > 95%)
- **Description**: Coverage gating in CI.
- **Acceptance**: Reports stored as artifacts.
- **Dependencies**: DCL-223
- **Estimate**: 0.25d

### [ ] DCL-223 — CI pipeline (GitHub Actions)
- **Description**: Lint/type/test/audit.
- **Acceptance**: Green pipeline on main.
- **Dependencies**: DCL-220
- **Estimate**: 0.5d

### [ ] DCL-224 — Pre-commit hooks (ruff, mypy, bandit)
- **Description**: Local enforcement.
- **Acceptance**: `pre-commit install` set up.
- **Dependencies**: DCL-001
- **Estimate**: 0.25d

### [ ] DCL-225 — Performance benchmarks (latency per tool call)
- **Description**: Track regressions.
- **Acceptance**: Bench results committed.
- **Dependencies**: DCL-220
- **Estimate**: 0.5d

### [ ] DCL-226 — Memory leak detection
- **Description**: Long-run session smoke tests.
- **Acceptance**: No unbounded growth over N hours.
- **Dependencies**: DCL-220
- **Estimate**: 0.5d

---

## 🚀 PHASE 14 — INSTALLER & LAUNCH (Week 15-16)

### [ ] DCL-230 — Pre-flight check UI in installer
- **Description**: Show Ollama/Docker/disk checks.
- **Acceptance**: Failure paths actionable.
- **Dependencies**: DCL-007, DCL-147
- **Estimate**: 0.5d

### [ ] DCL-231 — Bundled Ollama installer hook (Windows)
- **Description**: Offer to install Ollama if missing.
- **Acceptance**: Optional install completes.
- **Dependencies**: DCL-230
- **Estimate**: 0.5d

### [ ] DCL-232 — Auto-download Mistral 7B on first run
- **Description**: Progress UI.
- **Acceptance**: Resumable download.
- **Dependencies**: DCL-231
- **Estimate**: 0.5d

### [ ] DCL-233 — First-run wizard
- **Description**: Language, workspace, test query.
- **Acceptance**: Final step shows successful local response.
- **Dependencies**: DCL-232
- **Estimate**: 0.5d

### [ ] DCL-234 — CLI: start/stop/status/logs/update
- **Description**: Typer commands.
- **Acceptance**: All subcommands implemented + smoke-tested.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-235 — Uninstaller (purges credentials, vectors, audit log on request)
- **Description**: User-confirmed purge.
- **Acceptance**: No residual data after purge.
- **Dependencies**: DCL-057, DCL-070
- **Estimate**: 0.5d

### [ ] DCL-240 — README.md with security comparison vs OpenClaw
- **Description**: Marketing-grade summary.
- **Acceptance**: README in repo.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-241 — SECURITY.md
- **Description**: Threat model, principles, disclosure.
- **Acceptance**: Committed.
- **Dependencies**: DCL-217
- **Estimate**: 0.5d

### [ ] DCL-242 — Plugin development guide
- **Description**: `docs/plugin_development.md`.
- **Acceptance**: Walks through sample plugin.
- **Dependencies**: DCL-094
- **Estimate**: 0.5d

### [ ] DCL-243 — User manual (FR + EN)
- **Description**: Step-by-step lawyer flow.
- **Acceptance**: Both locales present.
- **Dependencies**: DCL-127
- **Estimate**: 1d

### [ ] DCL-244 — Architecture documentation
- **Description**: `docs/architecture.md`.
- **Acceptance**: Updated diagrams.
- **Dependencies**: DCL-001
- **Estimate**: 0.5d

### [ ] DCL-245 — Demo video script (lawyer use case)
- **Description**: 3-minute scripted demo.
- **Acceptance**: Script committed.
- **Dependencies**: DCL-127, DCL-128
- **Estimate**: 0.25d

### [ ] DCL-246 — Landing page copy (EU pro market)
- **Description**: Hero + features + compliance.
- **Acceptance**: Copy committed under `docs/marketing/`.
- **Dependencies**: DCL-240
- **Estimate**: 0.5d

### [ ] DCL-247 — Blog post: "Why we built DeClaw"
- **Description**: GDPR-compliant alternative narrative.
- **Acceptance**: Draft committed.
- **Dependencies**: DCL-246
- **Estimate**: 0.5d
