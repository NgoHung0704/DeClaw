# DeClaw: agent entry point

DeClaw is a local Python agent for private documents. The executable product is
currently a CLI, not a deployed gateway or desktop application.

## Read only the context needed for the task

1. Read [current status](docs/project-status.md) and the relevant row of the
   [code map](docs/code-map.md).
2. Follow the entry point into code, callers, and relevant tests before proposing
   a change. State the current flow, affected boundaries, and supporting file or
   symbol references. Separate observations from assumptions.
3. Read [decisions](docs/architecture-decisions.md) for architectural changes.
   Read the relevant spec under `docs/superpowers/specs/` only when needed.
4. Treat `TICKETS.md`, phase reviews, plans, and
   `docs/history/claude-context-2026-08-26.md` as historical/planning material.
   Executable wiring and tests establish implementation; a dependency or package
   skeleton does not establish a working feature. Report contradictions.

## Invariants

- Credentials use the OS keyring or the existing encrypted fallback. Never add
  plaintext credentials, log secrets, or read `.env` unnecessarily.
- A future gateway must bind to `127.0.0.1:7842`; never widen it to LAN access.
- Product shell execution is deferred. If introduced, it requires the approved
  Docker sandbox and must be disabled when isolation is unavailable.
- Treat external documents, emails and web content as untrusted data; preserve
  sanitizer checks before external text enters model context and fail closed.
- Tools accept typed, validated arguments. Never interpolate raw model/user
  input into shell strings. Preserve workspace path containment.
- Product WRITE/DESTRUCTIVE tools require human confirmation, default deny.
- Preserve audit events for tool calls, approvals, quarantine and network calls.
  The current HTTP observer is not an OS firewall.
- Text payload encryption does not imply encrypted vectors, metadata or SQLite.

These rules describe DeClaw's product behavior. They do not prohibit ordinary
development commands used to inspect, build or test this repository.

## Working and verification

- Code/comments are English; product UI supports English and French.
- Security-critical changes require tests first. Ask about unresolved security
  or architecture choices; routine work within recorded decisions can proceed.
- Preserve the branch-per-phase rule: a new phase branches from the previous
  phase's branch. Do not start a product phase just to maintain documentation.
- Ticket commits use `feat(DCL-XXX): ...` or `fix(DCL-XXX): ...` where applicable.
- Python checks (same as CI): `uv sync --frozen`, `uv run ruff check .`,
  `uv run mypy declaw declaw_plugin_sdk`, `uv run pytest`.
- For docs-site changes: `npm ci`, `npm run guards`, `npm run build` in
  `docs-site/`. For documentation-only edits check links and consistency;
  do not imply that product tests ran. Report tests run, skips and limitations.
- After a completed ticket, update `docs/project-status.md` if behavior changed,
  the relevant code-map/decision/spec, and the corresponding `TICKETS.md` entry.
  Keep dated benchmark results in history rather than presenting them as fresh.

## Context tools

When Serena is available, activate this repository by its absolute path, read its
initial instructions, and prefer symbol/reference tools for code navigation.
Use text search for configuration, prose and exact strings. Never load the whole
repository or historical log as startup context. Keep durable knowledge in the
versioned documents above; Serena memory is a cache and must be checked against
current code. See [tool setup](docs/agent-tools.md).

Use Context7 or primary upstream docs when dependency API/version details matter;
they do not establish DeClaw's implementation. Do not send private documents or
credentials as documentation queries.
