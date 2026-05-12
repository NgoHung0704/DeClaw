# DeClaw

> Your private AI agent. Runs local. Explains everything.

DeClaw is a local-first AI agent for EU regulated professionals — lawyers, notaries, doctors, accountants — who cannot legally upload client data to cloud AI (GDPR + professional secrecy).

- **Private by default** — Mistral 7B runs 100% local via Ollama. Nothing leaves the machine.
- **Safe by architecture** — Tool execution runs in a mandatory Docker sandbox.
- **Transparent always** — Every task generates a natural-language audit log.
- **Easy for everyone** — 1-click installer, native desktop app, no terminal required.
- **Scalable by design** — Plugin-first architecture.

## Status

Pre-alpha. See [TICKETS.md](./TICKETS.md) for the full work plan and [CLAUDE.md](./CLAUDE.md) for current development context.

## Quickstart (developers)

```bash
uv sync
uv run declaw --help
```

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com/) (for any feature beyond the CLI shell).

## License

AGPL-3.0-or-later.
