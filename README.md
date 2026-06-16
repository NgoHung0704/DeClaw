# 🦀 DeClaw

> **Your private AI agent. Runs local. Explains everything.**

DeClaw is a local-first AI agent designed for **EU regulated professionals** — lawyers, notaries, doctors, accountants — who cannot legally use cloud AI on client data because of GDPR and professional secrecy.

- **Private by default** — Mistral 7B runs 100% local via Ollama. Nothing leaves the machine. Ever.
- **Safe by architecture** — Every tool takes typed, validated parameters scoped to your workspace; external content is screened by a dual-model sanitizer before the agent acts on it; file changes require your confirmation. (Shell execution and its mandatory Docker sandbox are deferred to post-MVP — v0.1 needs no shell.)
- **Transparent always** — Every task produces a natural-language audit log; a network egress monitor proves nothing left the device.
- **Easy for everyone** — One-click installer, native desktop app (Tauri), no terminal required.
- **Scalable by design** — Plugin-first architecture: every capability is an installable skill that can be disabled or removed.

---

## Why DeClaw exists

EU professionals handling 50–500 confidential documents a day face an impossible choice:

| Option | Problem |
| --- | --- |
| Cloud AI (Claude.ai, ChatGPT, Copilot) | Violates GDPR + professional secrecy. **Illegal** for client data. |
| Don't use AI | Falls behind on document workload. |
| Existing local agents (OpenClaw, NanoClaw, ZeroClaw…) | Insecure, too technical, no audit trail. |

DeClaw is built specifically for that market: regulated, document-heavy, French/English-speaking, willing to pay for a tool that **just works** and is **provably private**.

---

## The 7 Inviolable Principles

These are not guidelines. They cannot be bypassed for performance, convenience, or "just for testing." If a feature requires breaking one, the feature is wrong.

1. **NEVER** store credentials in plaintext — always `python-keyring` (OS-native vault).
2. **NEVER** bind the gateway outside `127.0.0.1` — no LAN, no `0.0.0.0`, no exceptions.
3. **NEVER** execute shell commands outside the Docker sandbox — if Docker is unavailable, the tool is **disabled**, not bypassed.
4. **NEVER** skip the sanitizer layer on content sourced from outside the agent (email, web, file contents).
5. **NEVER** auto-trust content from documents/emails/web — all external content is treated as potentially adversarial.
6. **NEVER** let an LLM call a function with raw user input as a shell string — all tools take **typed, validated parameters**.
7. **NEVER** make a network call without logging it to the audit trail — "data left the device" must be observable.

---

## MVP definition (v0.1)

The MVP is "done" when an EU lawyer can:

1. ✅ Install DeClaw in under 5 minutes, **no terminal required**
2. ✅ Point DeClaw at a folder of client documents (PDF, DOCX, XLSX, TXT)
3. ✅ Ask questions in French or English and get **correct, cited answers**
4. ✅ Command the agent to move/rename/summarize files (with confirmation)
5. ✅ Review a clear audit log: "Here's what I did, and confirmation that nothing left your device"
6. ✅ Verify (network-level) that 100% nothing was sent to the internet

**Out of scope for v0.1**: shell execution and its Docker sandbox (deferred — the v0.1 feature set needs no shell), browser automation, vision-based agents, OS control beyond `os-bridge`, plugin marketplace, mobile apps.

---

## Architecture

### Stack

| Layer | Choice |
| --- | --- |
| Brain model | Ollama + Mistral 7B Instruct (default). Optional: Mistral 8x7B, Mixtral, Llama 3.1 8B |
| Embeddings | `nomic-embed-text` (via Ollama) |
| Language | Python 3.12+ (uv-managed, lockfile committed) |
| Agent framework | LangGraph |
| API gateway | FastAPI, bound to `127.0.0.1:7842` only |
| Desktop shell | Tauri 2.0 (Rust + webview), Windows first |
| Frontend | Vanilla JS + TailwindCSS CDN (zero build step), EN + FR i18n |
| Vector store | ChromaDB (Fernet at-rest encryption) |
| Document parsing | `pypdf`, `python-docx`, `openpyxl`, `unstructured` |
| Task / audit DB | SQLite via SQLModel |
| Credentials | `python-keyring` (Windows Credential Manager / Keychain / KWallet) |
| Sandbox | Docker SDK for Python (shell execution only — **deferred to post-MVP**) |
| Prompt-injection defense | Dual-model sanitizer (second Mistral instance, locked-down prompt) — **implemented (Phase 4)** |
| Plugin signatures | ed25519 (`pynacl`) |
| License | AGPL-3.0-or-later (commercial dual-license possible) |

### High-level diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ TAURI DESKTOP SHELL   ·   native window · system tray · auto-updater │
│ WEBVIEW UI   ·   HTML + TailwindCSS + Vanilla JS   ·   EN / FR i18n  │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    │  HTTP REST / WebSocket
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ DeClaw CORE  (Python — runs entirely on the user's machine)          │
│                                                                      │
│  ┌─────────┐     ┌─────────────┐      reasoning                      │
│  │ Gateway │ ──▶ │    Brain    │ ◀──▶  Ollama (Mistral 7B)           │
│  │(FastAPI)│     │ (LangGraph) │       100% local                    │
│  └─────────┘     └──────┬──────┘                                     │
│   loopback only         │ tool call                                  │
│   token + origin        ▼                                            │
│                  ┌──────────────┐                                    │
│                  │ PLUGIN HOST  │  each plugin = isolated            │
│                  └──┬────────┬──┘  subprocess · ed25519-signed       │
│          ┌──────────┘        └──────────┐                            │
│          ▼                              ▼                            │
│    ┌───────────┐                  ┌───────────┐                      │
│    │ Doc-Intel │                  │ OS-Bridge │                      │
│    │  (v0.1)   │                  │ (Phase 2) │                      │
│    └─────┬─────┘                  └───────────┘                      │
│          │ external content (PDF text, file body, …)                 │
│          ▼                                                           │
│    ┌─────────────┐   UNSAFE ──▶ quarantine (brain never sees it)     │
│    │  SANITIZER  │                                                   │
│    │ (Mistral #2)│   SAFE ────▶ returned to the Brain                │
│    └─────────────┘                                                   │
│                                                                      │
│  Storage    : ChromaDB (encrypted) · SQLite (tasks/audit) · Keyring  │
│  Always-on  : Audit logger + Network egress monitor (every action)   │
│  Deferred   : Docker sandbox for shell execution (post-MVP)          │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼  local only — never the internet
```

### Plugin-first architecture

**Every capability is a plugin.** This is non-negotiable. The core contains only:

- **Brain** (LangGraph orchestrator)
- **Sanitizer** (prompt-injection defense)
- **Sandbox executor** (Docker isolation)
- **Permission system** (mobile-app-style consent dialogs)
- **Audit logger** + network egress monitor
- **Plugin host** (loader, signature verification, subprocess isolation, IPC)
- **Gateway** (FastAPI)

Document Intelligence, OS Bridge, Email Reader — all plugins. Benefits:

- Disable a misbehaving plugin → the rest of the system keeps working
- New integrations are added without touching core
- Third parties can write plugins (ed25519 signatures required)
- Security audits are scoped per plugin
- Each plugin runs in its own Python subprocess with no keyring access (must go through core API)

### Plugin manifest example (`plugin.yaml`)

```yaml
name: doc-intel
version: 1.0.0
display_name: "Document Intelligence"
signature: "ed25519:…"   # required for non-builtin plugins

permissions:
  - type: filesystem_read
    scope: user_workspace
  - type: filesystem_write
    scope: user_workspace
    requires_confirmation: true
  - type: vector_store

denied:
  - network_external
  - shell_execute
  - credential_access
  - os_control

entry_point: "doc_intel.main:Plugin"
```

### Sanitizer layer

Every piece of content from outside the agent (PDF text, email body, web page) goes through a **second Mistral instance** with a locked-down system prompt **before** the brain sees it. The sanitizer cannot execute tools, cannot see conversation history, and outputs only `{verdict: SAFE|UNSAFE, reason: str}`. It **fails closed** (any error or unparseable output is treated as UNSAFE). UNSAFE content is quarantined (logged by hash + source, never raw) and surfaced in the UI; the brain never sees it. Implemented in Phase 4 and wired into `declaw chat` — file contents are sanitized before the agent acts on them.

Performance targets, encoded in the Phase 4 benchmark harness (`scripts/sanitizer_benchmark.py`, over a locked 110-sample FR+EN corpus):
- False positive rate < 2% (on the benign corpus)
- Detection rate high on the known-injection corpus (false negatives low)
- p95 latency < 500 ms per chunk

> Note: the latency target assumes a fast/GPU-served classifier; on Mistral 7B/CPU it will be slower. The harness reports the real numbers so the target can be tracked as the model/hardware changes.

### Audit log

After every task, the brain auto-generates a natural-language audit entry:

```json
{
  "task_id": "t_20260512_001",
  "user_query": "Find all contracts with penalty clauses for client Dupont",
  "summary_fr": "J'ai trouvé 4 contrats avec des clauses de pénalité…",
  "summary_en": "I found 4 contracts with penalty clauses…",
  "actions": [
    {"tool": "doc_intel.search", "query": "Dupont penalty clause", "results": 4},
    {"tool": "doc_intel.cite", "documents": ["contract_2024_03.pdf", "…"]}
  ],
  "network_calls": [],
  "data_left_device": false,
  "model_used": "mistral:7b",
  "plugins_invoked": ["doc-intel"]
}
```

A network egress monitor cross-checks `network_calls` against the actual outbound traffic during the task.

---

## Project status

**Pre-alpha — Phases 0–2 and 4 complete; Phase 3 (sandbox) deferred for v0.1.** The core agent already runs: `declaw chat` drives a local LangGraph brain (Mistral 7B via Ollama) with typed, workspace-scoped filesystem tools, a confirmation gate on writes, and the dual-model sanitizer screening file contents before the brain sees them. Still missing for a usable product: document intelligence (Phase 8), the web UI (Phase 9), and the desktop app (Phase 10).

### Roadmap

| Phase | Theme | Status |
| --- | --- | --- |
| 0 | Project foundation (scaffold, config, logging, preflight) | ✅ done |
| 1 | Core brain (LangGraph loop, tool calls, context management) | ✅ done |
| 2 | Tool layer (typed filesystem tools, registry) | ✅ done |
| 3 | **Sandbox layer** (Docker isolation, escape tests) | ⏸️ deferred (post-MVP) |
| 4 | **Sanitizer layer** ⚠️ (dual-model defense, injection corpus) | ✅ done |
| 5 | Memory & audit (ChromaDB, network egress monitor) | 🟡 next (MVP critical path) |
| 6 | Credentials & permissions (keyring, plugin perms, ed25519) | ⬜ planned |
| 7 | Plugin host (subprocess isolation, IPC, SDK) | ⬜ planned |
| 8 | ⭐ Doc-Intel plugin (PDF/DOCX/XLSX, RAG, citations) | ⬜ planned |
| 9 | Gateway & Web UI (FastAPI, chat, audit viewer, FR+EN) | ⬜ planned |
| 10 | Tauri desktop app (Windows MSI, tray, native picker) | ⬜ planned |
| 11 | OS-Bridge plugin (typed audio/display/launcher) | ⬜ planned |
| 12 | Security hardening (pen tests, OWASP-LLM, SECURITY.md) | ⬜ planned |
| 13 | Testing & QA (CI, coverage gates, benchmarks) | ⬜ continuous |
| 14 | Installer & launch (MSI, first-run wizard, docs) | ⬜ planned |

### Phase gating (strict)

- ⛔ Phase 8 (doc-intel) cannot start before Phase 7 (plugin host) is complete
- ⛔ Phase 9 (Web UI) cannot start before Phase 4 (sanitizer) is complete ✅ — Phase 3 (sandbox) is **deferred for v0.1** (shell execution dropped), so it no longer gates Phase 9
- ⛔ v1.0 cannot ship before Phase 12 (security hardening) is complete

> **Why Phase 3 is deferred:** the v0.1 feature set (document Q&A, file move/rename) needs no shell, and requiring Docker Desktop (WSL2, admin rights, paid licensing for larger orgs) contradicts the "install in under 5 minutes, no terminal" goal. Principle #3 stays in force: if shell execution returns post-MVP, it must go through the Docker sandbox — never bypassed.

### Tracking work

- **Backlog**: [GitHub Issues](https://github.com/NgoHung0704/DeClaw/issues) — every phase has an umbrella issue with sub-issues for each ticket (DCL-001 through DCL-247).
- **Milestones**: [Phase milestones](https://github.com/NgoHung0704/DeClaw/milestones) — one per phase.
- **Source-of-truth files** (mirror the GitHub backlog):
  - [`TICKETS.md`](./TICKETS.md) — full ticket list with acceptance criteria, dependencies, estimates.
  - [`CLAUDE.md`](./CLAUDE.md) — living development context for Claude Code sessions.

---

## Repository layout

```
declaw/                Core Python package
├── gateway/           FastAPI app (loopback only)
├── brain/             LangGraph orchestrator
├── sanitizer/         Prompt-injection defense (+ corpus)
├── sandbox/           Docker SDK executor
├── plugin_host/       Loader, IPC, signatures, isolation
├── memory/            ChromaDB wrapper + Fernet encryption
├── audit/             Logger, NL reporter, network egress monitor
├── credentials/       python-keyring wrapper
├── db/                SQLite via SQLModel
├── tools/builtin/     Core sandboxed tools
├── config.py          pydantic-settings (enforces loopback)
└── main.py            Typer CLI

plugins/builtin/
├── doc-intel/         ⭐ MVP plugin (PDF/DOCX/XLSX, RAG, actions)
└── os-bridge/         Phase 2 plugin (audio/display/launcher)

ui/                    Vanilla JS + Tailwind CDN, EN + FR
tauri/                 Tauri 2.0 desktop shell
sandbox_images/        Dockerfiles for python/shell sandboxes
tests/
├── unit/
├── integration/
├── security/          ⚠️ Critical: injection, escape, perm, egress
└── fixtures/
scripts/               Preflight checks, installer helpers, GitHub sync
docs/                  Architecture, security model, plugin guide
```

---

## Quickstart (developers)

**Prerequisites**: Python 3.12+, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com/) with `mistral:7b` pulled. Docker is **not** required for v0.1 (it is only needed for the deferred shell sandbox).

```bash
# Install dependencies (reproducible build via uv.lock)
uv sync

# Show CLI help
uv run declaw --help

# Print current configuration (loopback host, security flags, model names)
uv run declaw status

# Print version
uv run declaw version

# Chat with the local agent (needs Ollama running with mistral:7b)
uv run declaw chat            # add --debug to trace tool calls
```

`declaw chat` is a working local-agent REPL (Phases 1–2 + 4): it can read, list, write, and move files inside your workspace with typed, validated parameters — writes/moves ask for confirmation, and file contents pass the sanitizer first. The `start` / `stop` subcommands (the FastAPI gateway) are stubs until Phase 9.

The sanitizer benchmark can be run against your local model:

```bash
uv run python scripts/sanitizer_benchmark.py            # full corpus
uv run python scripts/sanitizer_benchmark.py --quick    # 6-sample smoke
```

### Working rules (for contributors and Claude Code)

- Update `CLAUDE.md` after every completed ticket.
- Mark `[x]` in `TICKETS.md` when a ticket is done.
- Commit format: `feat(DCL-XXX): description` or `fix(DCL-XXX): …`
- Security-critical code: write tests **first** (TDD).
- Code + comments in English. UI defaults to English + French.
- When in doubt about architecture or security → stop, ask, log in `CLAUDE.md` "Open decisions".

### Backlog sync utility

`scripts/sync_github_issues.py` is an idempotent script that mirrors `TICKETS.md` to GitHub (milestones, phase labels, parent umbrella issues, sub-issues). Re-run it whenever you add or rename tickets:

```bash
uv run python scripts/sync_github_issues.py            # create/update
uv run python scripts/sync_github_issues.py --project 3  # also add to project board
```

---

## Security

If you discover a vulnerability, please follow the disclosure policy in [SECURITY.md](./SECURITY.md) (in progress — Phase 12). Until then, open a private security advisory on GitHub.

DeClaw refuses to ship v1.0 until Phase 12 (security hardening) is complete: pen-test script, OWASP Top 10 for LLM mapping, threat model, network egress test asserting zero outbound traffic during a task, `pip-audit` + Bandit in CI.

---

## License

AGPL-3.0-or-later. Commercial dual-licensing may be offered later for organizations that cannot meet the AGPL's network-use clause.

---

## Acknowledgements

DeClaw was conceived as an answer to a specific gap in the EU professional-services market: local AI that is **simultaneously** private, safe, transparent, and usable by non-developers. None of the existing local agents satisfied all four constraints — hence this project.
