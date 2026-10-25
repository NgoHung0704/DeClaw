# DeClaw: agent instructions

The product is a local Python CLI. Gateway, product UI and desktop are planned.

## Read and work

- Start with [status](docs/project-status.md) and the relevant [code-map](docs/code-map.md) row; trace code, callers and tests before proposing changes. Cite evidence and separate observations from assumptions.
- Before architecture changes, read [active decisions](docs/architecture-decisions.md) and the relevant [spec](docs/specs/). Ask about unresolved security/architecture choices; routine work within recorded decisions can proceed.
- Backlog, reviews and [Git-recovered logs](docs/README.md#history) are historical/planning material. Executable wiring establishes implementation; report contradictions. Do not load the full repository or old logs at startup.

## Invariants

- Credentials use the OS keyring or existing encrypted fallback. Never add plaintext credentials, log secrets or read `.env` unnecessarily.
- A future gateway binds to `127.0.0.1:7842`; never widen to LAN access.
- Shell execution is deferred; any future shell tool requires approved Docker isolation and stays disabled when isolation is unavailable.
- External documents, emails and web content are untrusted. Preserve sanitizer checks before external text enters model context; fail closed.
- Tools take typed, validated arguments. Never interpolate raw model/user input into shell strings; preserve workspace path containment.
- WRITE/DESTRUCTIVE product tools require human confirmation, default deny.
- Preserve audit events for tool calls, approvals, quarantine and network calls. HTTP observation is not an OS firewall.
- Text payload encryption does not imply encrypted vectors, metadata or SQLite.

These invariants govern product behavior, not ordinary development inspection/build/test commands.

## Verification and handoff

- Code/comments are English; product UI supports English and French. Write security-critical tests before implementation.
- A new phase branches from the previous phase's branch. Do not start a product phase for documentation maintenance.
- Ticket commits use `feat(DCL-XXX): ...` or `fix(DCL-XXX): ...` where applicable.
- Python CI: `uv sync --frozen`, `uv run ruff check .`, `uv run mypy declaw declaw_plugin_sdk`, `uv run pytest`.
- Documentation-only edits: check links/consistency; do not imply product tests ran. Report checks, skips and limitations.
- After a ticket, update status if behavior changed, the relevant map/decision/spec and `TICKETS.md`. Keep measurements in dated reports, not as fresh guarantees.

## Context tools

- When Serena is available, read its initial instructions, activate this absolute repository path and prefer symbols/references for Python navigation. Use text search for prose/configuration; [tool setup](docs/agent-tools.md) has details.
- Durable knowledge belongs in versioned docs; Serena memories are caches to verify against current code.
- Use Context7 or primary upstream docs when dependency API/version details matter. Never send private documents or credentials as documentation queries.
