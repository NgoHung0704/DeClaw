# Roadmap — Phases 7, 8, 9

- **Date**: 2026-08-23
- **Status**: design direction approved; detailed spec written per phase
- **Covers**: DCL-090..097 (Phase 7), DCL-100..117 (Phase 8), DCL-120..134 (Phase 9)

## Why this document exists

The three phases together are 41 tickets — roughly six weeks of the original
estimate. That is too much for one design document: a Phase 9 spec written
today would rest on guesses about a plugin host that does not exist yet.

So the work is decomposed into three sub-projects, each with its own
spec → plan → implementation cycle. This document is the arc: what each phase
owns after the decisions below, and which cross-phase choices are already
settled so a later phase does not silently re-open them.

Only **Phase 7 has a detailed spec today**
(`2026-08-23-phase-7-plugin-host-design.md`). Phases 8 and 9 are sketches
here, to be specced when their turn comes, with real knowledge from the phase
before.

## Four decisions taken on 2026-08-23

| # | Question | Decision |
| --- | --- | --- |
| 1 | Pace | Roadmap for all three; detailed spec + implementation one phase at a time |
| 2 | Third-party plugin install in v0.1 | **No.** Builtin plugins + enable/disable only |
| 3 | Where does doc-intel run | **Thin plugin**: the plugin parses documents; the core owns embedding, encryption, the vector store, search and citations |
| 4 | Sanitizing document chunks | **At retrieval time, top-k only, verdict cached by SHA-256** |

## Four findings that changed the plan

These came out of reading the existing code against the ticket text. Each one
invalidates something `TICKETS.md` currently asserts.

### 1. DCL-112 as written is computationally infeasible

The sanitizer defaults to `qwen2.5:7b` at p50 = 4.19 s per call (`CLAUDE.md`,
measured 2026-07-26). A 100-page PDF chunked at ~512 tokens is 150-300 chunks,
so "sanitize every chunk before injection" costs **10-20 minutes per document**
and days for a realistic workspace. Nobody had multiplied it out.

Decision 4 resolves this: the trust boundary that matters is *content entering
the model's context*, not content sitting in a vector store. Only the top-k
chunks actually retrieved for a query get classified, and the verdict is cached
by chunk SHA-256 so the second query is free. This is the same reasoning that
already makes `filesystem_read` sanitized and `filesystem_list` not.

Cost of the trade, stated plainly: an injection sitting in an indexed document
is *stored* unclassified. It is classified before it can ever influence the
model. If a future feature reads chunks without going through retrieval, that
feature must sanitize them itself.

### 2. Plugin signatures cover the manifest, not the code

DCL-083 signs the raw bytes of `plugin.yaml`. The entrypoint `.py` can be
replaced wholesale and the signature still verifies. This is only a live
vulnerability if third-party plugins can be installed — which decision 2
removes from v0.1. **When the install flow returns (v0.2), the manifest must
gain a `files:` map of path → SHA-256 so the signature covers the code.**
Recorded here so it is not forgotten.

### 3. Subprocess isolation is not a security sandbox

DCL-092's acceptance criterion — "plugin cannot import declaw internals" — is
not achievable as a security property. `declaw` lives in the same virtualenv,
so it is importable no matter what `PYTHONPATH` says; an import hook that
blocks it can be removed by the plugin itself.

What the subprocess boundary genuinely provides: crash isolation, no shared
memory, no inherited environment, no keyring handle, and a process that can be
killed. The import hook is an **architectural boundary** — it stops a plugin
author from accidentally coupling to core internals — and is documented as
such, not as a defence against malicious code. Defending against malicious
plugin code needs OS-level sandboxing, the deferred Phase 3 problem.

### 4. TailwindCSS via CDN contradicts the product promise

The locked decision says "Vanilla JS + TailwindCSS CDN (zero build step)".
Loading `cdn.tailwindcss.com` sends the user's IP to a third party every time
the app opens. That violates Principle #7 and breaks MVP DoD #6 ("network
egress monitor confirms nothing left the device") on the very first screen —
for a product sold to EU professionals on the grounds that nothing leaves their
machine.

**Tailwind will be vendored as a static CSS file under `ui/css/`.** Still zero
build step at runtime; the build happens once, at development time, and the
output is committed.

## Phase 7 — Plugin Host

Full spec: `2026-08-23-phase-7-plugin-host-design.md`.

Owns: plugin discovery, subprocess isolation, the stdio IPC protocol, the
plugin SDK, crash supervision with backoff and quarantine, enable/disable
state, and the bridge that turns a plugin capability into a tool the brain can
call.

Does **not** own (deferred, not forgotten):

- install / uninstall / update of third-party plugins (decision 2)
- runtime signature enforcement — v0.1 only loads plugins shipped inside the
  application directory, which is stricter than checking a signature
- **DCL-071 / 072 / 073 (the plugin credential API) stay deferred.**
  `CLAUDE.md` currently plans to fold them into Phase 7. Decision 3 removes the
  reason: a parser plugin needs no secrets. The `credentials` permission stays
  in the enum, unexercised, until a plugin actually needs it.

## Phase 8 — doc-intel (sketch)

The split follows decision 3.

**In the plugin** (`plugins/builtin/doc-intel/`) — DCL-100..105: parsers for
PDF, DOCX, XLSX, TXT/Markdown, plus the chunker. This is the code that reads
adversarial binary files from strangers, and it carries the heavy dependencies
(`pypdf`, `unstructured`, `openpyxl`). It is exactly what the subprocess
boundary is worth having for. It returns structured chunks: text plus source
metadata (page, sheet, heading, ordinal).

**In the core** (`declaw/documents/`) — DCL-106..117: embedding via the existing
`build_ollama_embedder`, Fernet encryption via the existing `memory/crypto.py`,
a dedicated Chroma collection `declaw_documents`, hash-based incremental
indexing, the `watchdog` file watcher, semantic search, citations, and the
summarize / move / rename / organize actions.

Two consequences worth writing down now:

- **Citations are structural, not generated.** DCL-111 asks that every answer
  cite its source. A 3B model cannot be made to do that reliably by prompting —
  the same finding that made DCL-062's audit summaries deterministic templates
  rather than LLM output. So the search tool returns chunks carrying their
  source metadata, and the UI renders the sources that were actually retrieved,
  whether or not the model cites them inline. Citations then cannot be
  hallucinated.
- **Benchmarks get held-out discipline from day one.** The sanitizer's
  development corpus scored 91.7% while the external held-out set scored 53.3%
  — a 38-point gap, because a self-authored corpus grades its own homework.
  DCL-117's French legal benchmark must therefore include documents nobody on
  this project wrote. Sources have to be openly licensed (EUR-Lex, Légifrance
  open data), since real client documents cannot be committed.

## Phase 9 — Gateway & Web UI (sketch)

**Gateway** — DCL-120..126: FastAPI bound to loopback, a token minted on first
run and kept in the keyring, Origin/Host validation, per-route rate limits and
body size caps, REST routes, and a WebSocket for streaming chat.

**UI** — DCL-127..134: vanilla JS, vendored Tailwind, EN/FR locale JSON. Pages:
chat (streaming), documents (folder picker + indexing progress + search), audit
viewer with filters and export, settings, system status.

Reduced by decision 2: the plugin manager (DCL-130) becomes a list with
enable/disable and a permission panel, not an installer. The permission dialog
(DCL-082 / DCL-134) is no longer an install-time modal — with builtin-only
plugins there is no install moment. What it becomes is an open question for the
Phase 9 spec: either a one-time consent screen on first run, or a permission
panel in Settings showing what each plugin holds, with a revoke button.

Two long-standing follow-ups land naturally here: threading `task_id` through
chat turns (audit events from the REPL currently carry `task_id=None`), and
recording an episode at end-of-task (`memory/episodic.py` exists but nothing
populates it).

## Deltas against TICKETS.md

Tickets are not renumbered; their scope or acceptance text changes.

| Ticket | Change |
| --- | --- |
| DCL-091 | Scope reduced to enable / disable / quarantine. No install, uninstall, or update |
| DCL-092 | Acceptance reworded: the import hook is an architectural boundary, not a security one |
| DCL-094 | The SDK is a top-level package `declaw_plugin_sdk/`, not a module inside `declaw/` |
| DCL-095 | `plugin_state.json` (plain JSON) instead of `installed.db` (SQLite) |
| DCL-097 | Permission violations are caught at load time; the runtime kill trigger is protocol violation |
| DCL-071/072/073 | Remain deferred rather than folding into Phase 7 |
| DCL-112 | Sanitize at retrieval time, top-k only, cached by chunk hash |
| DCL-111 | Citations derive from retrieval metadata, not from model output |
| DCL-130/134 | Plugin manager is enable/disable + permissions; no install-time dialog |
| — | Tailwind is vendored locally instead of loaded from a CDN |

## Deferred to v0.2 or later

- Third-party plugin install, with `files:` digests added to the signed manifest
- The plugin credential API (DCL-071 / 072 / 073)
- OS-level sandboxing of plugin processes
- Multiple concurrent requests per plugin (a process pool); the protocol already
  carries request ids, so this is a non-breaking addition
