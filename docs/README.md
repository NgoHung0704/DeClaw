# DeClaw Documentation

> Reviewer-friendly documentation of DeClaw's completed phases. Đọc theo thứ tự để hiểu build-up từ nền móng đến layer bảo mật.

## Phase reviews

| Phase | Theme | Status | Doc |
|---|---|---|---|
| **0** | Project Foundation (config, DB, logging, Ollama client, preflight) | ✅ Complete | [phase-0-review.md](./phase-0-review.md) |
| **1** | Core Brain (LangGraph loop, agent state, model integration, probe framework) | ✅ Complete | [phase-1-review.md](./phase-1-review.md) |
| **2** | Tool Layer (typed tools, filesystem, confirmation gate, path traversal defense) | ✅ Complete | [phase-2-review.md](./phase-2-review.md) |
| **3** | Sandbox (Docker isolation) | ⏸️ Deferred | *(see note below)* |
| **4** | Sanitizer Layer (dual-model prompt injection defense) | ✅ Complete | [phase-4-review.md](./phase-4-review.md) |
| **5** | Memory & Audit (ChromaDB, Fernet, episodic DB, NL summary, egress monitor, GDPR export/wipe) | ✅ Complete | [phase-5-review.md](./phase-5-review.md) |
| **6** | Credentials & Permissions (keyring, AES fallback, plugin manifest, ed25519, grants) | ✅ Buildable core complete | [phase-6-review.md](./phase-6-review.md) |
| 7 | Plugin Host (subprocess isolation, IPC, kill trigger) | 🟡 Next (MVP critical path) | *(not yet reviewed)* |
| 8+ | Doc-Intel, Web UI, Desktop, OS-Bridge, Hardening, Installer | ⬜ Planned | *(future)* |

## Suggested reading order

**For a reviewer / interview panelist**:
1. [phase-0-review.md](./phase-0-review.md) — build up mental model of the foundations
2. [phase-1-review.md](./phase-1-review.md) — understand what "AI agent" means in DeClaw's design
3. [phase-2-review.md](./phase-2-review.md) — see how tools are typed & secured
4. [phase-4-review.md](./phase-4-review.md) — the flagship security feature (sanitizer)
5. [phase-5-review.md](./phase-5-review.md) — memory + audit trail (MVP DoD #5 + #6)
6. [phase-6-review.md](./phase-6-review.md) — credentials + permission foundation for plugins

**For a new contributor about to write code**:
1. [../CLAUDE.md](../CLAUDE.md) — the 7 Inviolable Principles + working rules
2. Phase reviews in order (0 → 1 → 2 → 4)
3. [../TICKETS.md](../TICKETS.md) — pick the next unclaimed ticket

**For someone doing a security review**:
- Start with **phase-4-review.md** (sanitizer, prompt injection defense)
- Then **phase-2-review.md** section 6 (path traversal defense — 36-vector corpus)
- Then check [../CLAUDE.md](../CLAUDE.md) "7 Inviolable Principles" enforcement

## Phase 3 — why deferred

Phase 3 (Docker sandbox) was originally the sandbox layer for shell execution — a hard requirement per Principle #3 (*"NEVER execute shell commands outside the Docker sandbox"*).

**Decision (2026-06-16, Option A in CLAUDE.md Open decisions)**: **Shell execution dropped from v0.1**, so Phase 3 is deferred post-MVP.

**Why**:
1. **MVP feature set doesn't need shell.** The 5 DoD items (read PDF/DOCX/XLSX, cited Q&A, file move/rename via typed tools, audit log, egress monitor) all work through the os-bridge plugin with **typed, validated parameters** (Principle #6) via Python `shutil` — no shell commands.
2. **Docker Desktop is a heavier burden than Ollama** for non-technical users: WSL2 + BIOS virtualization + admin rights, which lawyers/doctors typically can't set up.
3. **Docker Desktop licensing is paid** for orgs >250 employees OR >$10M revenue — law firms / medical practices may fall under this, creating a real cost/legal risk for the target market.
4. **Multi-GB RAM footprint** on user machines already tight with Word/Excel/browser.

Principle #3 stays in force: if/when shell returns post-MVP, it MUST go through a sandbox. Candidates for that future sandbox include:
- **Podman Desktop** (OSS, no enterprise licensing risk, rootless default)
- **Windows Sandbox** (built-in Windows Pro, ephemeral)
- **WSL2 directly** (avoids Docker Desktop licensing)
- **gVisor / Firecracker / nsjail** (Linux-first)

Full reasoning: [../CLAUDE.md](../CLAUDE.md) → "Open decisions" → "Docker requirement for end-users / shell execution in MVP".

## Related resources

- **[../README.md](../README.md)** — Project overview, quickstart, architecture stack
- **[../CLAUDE.md](../CLAUDE.md)** — Living dev context, locked decisions, open decisions
- **[../TICKETS.md](../TICKETS.md)** — Every ticket with acceptance criteria + dependencies + estimates
- **[../.env.example](../.env.example)** — Every configurable knob documented

---

**Last updated**: 2026-06-28 (after Qwen2.5 3B default model swap)
