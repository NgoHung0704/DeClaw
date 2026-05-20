# DeClaw — Claude Code Context

> Living document. **Update after every completed ticket.** This is what future sessions read first.

## Current state
- Phase: 0 — Project Foundation
- Current ticket: DCL-007 (next — Pre-flight check script)
- Last updated: 2026-05-20

## Locked architectural decisions
- Python 3.12+ with uv (lockfile committed)
- LangGraph for agentic loop
- Ollama + Mistral 7B Instruct (default); nomic-embed-text for embeddings
- Docker sandbox **mandatory** for shell execution (disabled, never bypassed, when Docker unavailable)
- Dual-model sanitizer (second Mistral instance, locked prompt) for prompt injection defense
- ChromaDB for vector memory (Fernet at-rest encryption)
- FastAPI gateway binds `127.0.0.1:7842` only
- python-keyring for credentials (NO plaintext anywhere)
- **Plugin-first architecture** — every capability is a plugin in its own subprocess
- ed25519 signatures required for third-party plugins
- Tauri 2.0 desktop shell (Windows first, then macOS, Linux)
- Frontend: Vanilla JS + TailwindCSS CDN (zero build step), EN + FR i18n
- AGPL-3.0 license (commercial dual-license possible later)

## The 7 Inviolable Principles
1. NEVER store credentials in plaintext — always python-keyring
2. NEVER bind the gateway outside `127.0.0.1` — no LAN, no `0.0.0.0`
3. NEVER execute shell commands outside the Docker sandbox — if Docker is unavailable, the tool is **disabled**, not bypassed
4. NEVER skip the sanitizer layer on content sourced from outside the agent (email, web, file contents from user-pointed folders)
5. NEVER auto-trust content from documents/emails/web — treat as potentially adversarial
6. NEVER let an LLM call a function with raw user input as a shell string — all tools take **typed, validated parameters**
7. NEVER make a network call without logging it to the audit trail — "data left the device" must be observable

## Target market (MVP v0.1)
EU regulated professionals — lawyers, notaries, doctors, accountants — who cannot legally use cloud AI due to GDPR + professional secrecy. France-first.

## MVP definition of done
1. Install in < 5 min, no terminal required
2. Point at folder of PDFs/DOCX/XLSX
3. Ask in French or English, get cited answers
4. Move/rename/summarize via natural language (with confirmation)
5. Audit log shows what happened, in natural language
6. Network egress monitor confirms nothing left the device

## Phase gating (strict)
- Cannot start Phase 8 (doc-intel) before Phase 7 (plugin host) is done
- Cannot start Phase 9 (Web UI) before Phases 3 (sandbox) + 4 (sanitizer) are done
- Cannot ship v1.0 before Phase 12 (security hardening) is complete

## Working rules
- Update `CLAUDE.md` after every completed ticket
- Mark `[x]` in `TICKETS.md` when a ticket is done
- Commit format: `feat(DCL-XXX): description` or `fix(DCL-XXX): ...`
- Security-critical code: write tests **first** (TDD)
- Code + comments in English; UI defaults English + French
- When in doubt about architecture or security → stop, ask the user, log in "Open decisions"

## Completed tickets
- **DCL-001** — Project scaffold: uv-managed Python 3.12 project, full folder skeleton, pyproject.toml with all v0.1 dependencies, `declaw` Typer CLI with `version`/`status`/`start`/`stop`/`chat` commands, pydantic-settings config that enforces loopback-only host. `uv sync` resolves 196 packages; `uv run declaw --help` works.
- **DCL-002** — CLAUDE.md living context: this document.
- **DCL-003** — Ollama integration + health check: `declaw/brain/ollama_client.py` provides an async `OllamaClient` (httpx-based) with `version()`, `list_models()`, and a never-raising `health() -> OllamaHealth` snapshot. `declaw status` now shows `ollama_reachable` and `ollama_has_<model>`. 6 unit tests in `tests/unit/test_ollama_client.py` cover the happy path, missing model, connection errors, and HTTP errors using `httpx.MockTransport` — no live daemon needed.
- **DCL-004** — Config system with pydantic-settings: closeout ticket. `declaw/config.py` (delivered in DCL-001) provides typed `Settings` with `DECLAW_` prefix, `.env` support, loopback host validator, port range validator, language enum, path `~` expansion, and `OLLAMA_BASE_URL` unprefixed alias. `get_settings()` is the `@lru_cache` singleton. 10 unit tests in `tests/unit/test_config.py` cover defaults, env loading, type validation, loopback enforcement, path expansion, singleton behavior, and `.env` file loading. `.env.example` documents every knob.
- **DCL-005** — SQLite + SQLModel + Alembic. `declaw/db/engine.py` exposes async aiosqlite engine, sessionmaker, and `get_session()` context manager. `declaw/db/models.py` ships baseline `Task` (UUID PK, status enum, prompt/result/error) and `AuditEvent` (append-only, JSON payload, optional FK to tasks — required by Principle #7). Alembic configured to read DB URL from `Settings` (override via `DECLAW_DB_URL` for tests), with `render_as_batch=True` for SQLite ALTER support. Initial migration `b067ce5acbad` creates both tables + indexes. 5 CRUD smoke tests in `tests/unit/test_db.py` cover insert/read/update tasks, JSON payload roundtrip, audit→task FK link, and schema sanity.
- **DCL-006** — Structured JSON logging (loguru). `declaw/log.py` exposes `configure()`, the global `logger`, and `use_request_id()` context manager. Records emit single-line JSON with `timestamp` (ISO 8601 + tz), `level`, `message`, `request_id`, `logger`, plus `extra` (from `logger.bind`) and `exception`. Request ID is a `ContextVar` so it propagates correctly across `asyncio.Task` boundaries — concurrent requests can never cross wires. Level configurable via `DECLAW_LOG_LEVEL` setting (TRACE..CRITICAL). Operational logger is **separate** from the DB-backed audit trail (Principle #7) — those will live in `declaw/audit/` later. 8 unit tests in `tests/unit/test_log.py` cover JSON shape, ISO timestamp, level filtering, request_id propagation (nested + async-isolated), bound extras, and exception serialization.

## In progress
- (none — ready to start DCL-007)

## Open decisions
- (none yet)

## Future ideas (out of scope for current phase)
- Browser automation (Playwright) — deferred to Phase 2 / post-MVP
- Scheduler (APScheduler) — deferred to Phase 2 / post-MVP
- Vision-based agents, OS control beyond os-bridge, plugin marketplace, mobile apps — out of scope for v0.1

## Notes for next session
- DCL-006 done. To use the logger anywhere: `from declaw.log import logger, use_request_id`; call `configure()` once at process start (gateway entry, CLI entry). FastAPI middleware (later ticket) should wrap each request in `with use_request_id(req.headers.get("x-request-id") or uuid4()): ...`. Next: DCL-007 — pre-flight check script (Ollama running, Mistral pulled, Docker available, ports free).
