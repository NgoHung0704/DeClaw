# DeClaw — Claude Code Context

> Living document. **Update after every completed ticket.** This is what future sessions read first.

## Current state
- Phase: 0 — Project Foundation
- Current ticket: DCL-003 (next — Ollama integration + health check)
- Last updated: 2026-05-12

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

## In progress
- (none — ready to start DCL-003)

## Open decisions
- (none yet)

## Future ideas (out of scope for current phase)
- Browser automation (Playwright) — deferred to Phase 2 / post-MVP
- Scheduler (APScheduler) — deferred to Phase 2 / post-MVP
- Vision-based agents, OS control beyond os-bridge, plugin marketplace, mobile apps — out of scope for v0.1

## Notes for next session
- After DCL-001 is committed, move directly to DCL-003 (Ollama integration + health check). DCL-002 is satisfied by this very document.
