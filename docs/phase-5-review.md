# Phase 5 — Memory & Audit: Hướng dẫn review cho người mới

> **Đối tượng**: reviewer hoặc contributor mới. Đọc xong hiểu **memory 4 loại**, **audit trail hoạt động thế nào**, và **cách DeClaw đạt MVP DoD #5 (NL audit log) + #6 (egress monitor)**.

---

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Tại sao cần Phase 5?](#2-tại-sao-cần-phase-5)
3. [Memory — 4 loại agent memory](#3-memory--4-loại-agent-memory)
4. [Audit — Principle #7 hiện thực hóa](#4-audit--principle-7-hiện-thực-hóa)
5. [Các quyết định thiết kế cốt lõi](#5-các-quyết-định-thiết-kế-cốt-lõi)
6. [Bóc tách từng ticket](#6-bóc-tách-từng-ticket)
7. [CLI mới: `report`, `memory`, `audit`](#7-cli-mới-report-memory-audit)
8. [GDPR compliance — export + wipe](#8-gdpr-compliance--export--wipe)
9. [Network egress monitor — "data left device"](#9-network-egress-monitor--data-left-device)
10. [Verify chạy đúng](#10-verify-chạy-đúng)
11. [Trade-off honest](#11-trade-off-honest)
12. [Checklist review](#12-checklist-review)
13. [Thuật ngữ](#13-thuật-ngữ)

---

## 1. TL;DR — 30 giây

Phase 5 build **2 subsystem lớn** liên quan nhau:

**Memory** — DeClaw nhớ được gì:
- **Short-term buffer**: FIFO ring bounded, in-memory
- **Semantic memory** (ChromaDB): vector search theo topic, Fernet-encrypted at rest
- **Episodic memory** (SQLite): task history, query theo date/tag
- **Retrieval hook**: inject top-k memory hits vào context (chưa wire default)
- **GDPR export + wipe**: JSON archive + right-to-be-forgotten CLI

**Audit** — DeClaw ghi lại gì (Principle #7):
- **Typed audit events**: ToolCall, NetworkCall, Quarantine, PermissionPrompt... (discriminated union)
- **Real-time logger**: OUTERMOST tool wrapper — audit → confirm → sanitize → tool
- **NL summary + daily report**: deterministic templates (NOT LLM — no hallucination)
- **Network egress monitor**: patches httpx, mọi outbound call được ghi
- **Multi-format export**: JSON, Markdown, PDF (fpdf2)

+ **DCL-070 pulled forward**: keyring wrapper cho credentials (dependency của Fernet key).

**Status**: ✅ COMPLETE (398 unit tests + 1 skipped, mypy 62 files + ruff clean). MVP DoD #5 + #6 closed.

---

## 2. Tại sao cần Phase 5?

### Memory: agent cần "nhớ"

Không có memory:
- Mỗi lần chat = từ đầu, không nhớ document trước đã đọc
- Hỏi cùng câu 10 lần → phải re-parse document 10 lần
- Không thể "trở lại task tuần trước"

Có memory:
- Semantic search: "tôi hỏi về hợp đồng Dupont" → retrieve context liên quan từ document đã đọc
- Episodic: "task tôi làm hôm thứ Ba" → query DB
- Working buffer: giữ vài turn gần nhất trong prompt

### Audit: Principle #7 mandate

*"NEVER make a network call without logging it to the audit trail — 'data left the device' must be observable"*

Không có audit:
- User không biết agent làm gì thay mặt mình
- Không thể chứng minh "không có data gì rời khỏi máy" — vốn là core value proposition cho luật sư/bác sĩ
- Không GDPR-compliant (Article 15 — right of access, Article 30 — records of processing)

Có audit:
- Mỗi tool call, mỗi network call, mỗi quarantine event = 1 record
- Cuối ngày có "daily report" NL: *"DeClaw đã đọc 4 file, di chuyển 1 file, không gọi mạng ngoài Ollama"*
- User export dưới dạng PDF → gửi lawyer review

**MVP DoD #5** (*"Audit log shows what happened, in natural language"*) và **#6** (*"Network egress monitor confirms nothing left the device"*) đều được Phase 5 close.

---

## 3. Memory — 4 loại agent memory

### Taxonomy chuẩn ngành

| Loại | DeClaw ticket | File |
|---|---|---|
| **Short-term / working** | DCL-052 | [buffer.py](../declaw/memory/buffer.py) |
| **Semantic** (topic-based) | DCL-053 | [semantic.py](../declaw/memory/semantic.py) |
| **Episodic** (timestamped) | DCL-054 | [episodic.py](../declaw/memory/episodic.py) |
| **Procedural** (workflows) | ❌ chưa có ticket | — |

**Note**: DCL-053 semantic được scope theo **topic/document**, không phải **user preference**. Đây là gap CLAUDE.md ghi rõ — có thể add ticket "User preference memory" post-MVP.

### Retrieval hook (DCL-055)

`with_memory(model, retrieve)` là ModelCallable wrapper composable:
```python
# Latest human turn = query
# Top-k hits fold vào ONE SystemMessage (token-budgeted)
# Framed as data-not-instructions (chống indirect injection từ memory)
# Inject NGAY TRƯỚC newest turn
# Model-facing view only — không persist state
# Retrieval failure NON-FATAL
```

**NOT wired vào default `build_brain`** — cùng rule với system prompt: không add vào prompt mà không A/B probe trên qwen2.5:3b. Follow-up documented.

---

## 4. Audit — Principle #7 hiện thực hóa

### Cấu trúc event (DCL-060)

Discriminated union keyed on `event_type`:

```python
# Tất cả frozen pydantic models
class ToolCallEvent(BaseModel):
    event_type: Literal["tool_call"]
    schema_version: int  # ← envelope trên every payload
    tool_name: str
    args: dict  # clip_args truncate + SHA-256 fingerprint
    outcome: Literal["ok", "denied", "error"]
    duration_ms: int
    task_id: str | None
    # ...

class NetworkCallEvent(BaseModel):
    event_type: Literal["network_call"]
    host: str
    flagged: bool  # True khi outside allowlist
    # ...

class QuarantineEvent(BaseModel): ...
class PermissionPromptEvent(BaseModel): ...
class PluginPermissionEvent(BaseModel): ...  # DCL-084
class MemoryExportEvent(BaseModel): ...
class MemoryWipeEvent(BaseModel): ...  # NO content field by construction
```

`event_type` doubles as **indexed DB column** — query nhanh theo loại. `schema_version` cho phép evolution — old rows readable sau khi schema update.

### Real-time logger (DCL-061)

**Wrap order (outermost đầu tiên)**:
```
audit → confirmation → sanitizer → tool
```

`wrap_tool_with_audit` là **OUTERMOST**. Nghĩa là:
- Audit ghi call **exactly as model experienced it** (kể cả với clipped args)
- Denial → audit ghi `outcome="denied"` với DeClaw-generated denial string match
- Error → `outcome="error"` + exception info

**Bao ngoài sanitizer** để record kể cả khi sanitizer quarantine content — mọi transaction đều ghi.

### `AuditLogger` protocol

```python
class AuditLogger(Protocol):
    def log(self, event: AuditEvent) -> None: ...

class DbAuditLogger:
    # One committed session per event
    # Storage errors LOGGED, NEVER RAISED
    # → observability không được giảm availability
    # → revisit trong Phase 12 hardening

class InMemoryAuditLogger:
    # For tests
    events: list[AuditEvent]
```

### Sinks

- `quarantine_db_sink`: bridge sanitizer quarantine sang DB event
- `composite_sink`: fan-out ra nhiều sink. Trong `declaw chat` hiện có **3**: loguru + DB +
  `user_notice_sink` (thêm 2026-07-25 — thông báo quarantine trực tiếp cho user bằng EN/FR,
  vì model diễn giải placeholder sai; xem phase-4-review.md mục 5)
- `sync→async` cẩn thận: create_task under running loop + strong task refs, else asyncio.run — không leak task

---

## 5. Các quyết định thiết kế cốt lõi

### (1) **NL audit summary deterministic — NOT LLM-generated**

Locked decision. Reason: audit prose cho luật sư/bác sĩ **phải hallucination-free**. Nếu dùng LLM generate → có thể "add" chi tiết sai → user hiểu nhầm về hành vi agent → legal risk.

Solution: **template deterministic** với verb per-tool EN+FR:
```
"DeClaw a lu 4 fichiers, déplacé 1 fichier, aucune donnée n'a quitté l'appareil."
```

Templates ở [audit/summary.py](../declaw/audit/summary.py). Add tool → add template. Deterministic = same input → same output = auditable.

**Trade-off honest**: prose fixed, có thể "robot" không "natural" bằng LLM output. Chấp nhận cho MVP với target regulated professionals.

### (2) **ChromaDB telemetry OFF, no internet embedder**

Chroma 1.5.9 default **phones home** analytics (Principle #7 vi phạm). Fix:
```python
build_chroma_client(
    settings=Settings(
        anonymized_telemetry=False,  # ← explicit off
        ...
    )
)
```

+ Chroma default embedding function tải ONNX từ internet lần đầu → **NEVER engaged**. Embeddings supplied qua injectable `Embedder` seam → `OllamaClient.embed()` (nomic-embed-text local).

**Principle #7 enforcement structural**, không phải "user manually disable".

### (3) **Text encrypted trước Chroma, metadata plaintext**

Fernet encrypt text BEFORE reaching Chroma. Persisted files byte-scanned trong test để verify không có plaintext leak.

**Metadata (Chroma `where` filters) plaintext by design** — Chroma cần plaintext để filter. Convention: metadata là **labels only** (`source_type: "pdf"`, `client: "dupont"`), không payload (`content: "confidential..."`).

**Honest caveat**: embedding vectors **NOT encrypted**. Lý do: Chroma cần compare vectors để search. Embedding-inversion attack có thể approximate text từ vector. Documented → Phase 12 consideration.

### (4) **Egress monitor patches httpx globally**

DCL-064: `httpx.AsyncClient.send` + `Client.send` monkeypatched → **EVERY** outbound request emit NetworkCallEvent, success/failure alike.

- Host trong allowlist (loopback + configured Ollama) → OK
- Ngoài → `flagged=True` + loguru warning
- Installed as context manager quanh `declaw chat` → mọi Ollama call audited

**Honest scope**: in-process observation only. Nếu attacker spawn subprocess và gọi `curl` bypass httpx → not caught. OS-level enforcement = Phase 12 / DCL-216.

`requests` library **not hooked** — không phải dependency (dùng httpx thay). Nếu thêm `requests` sau → phải hook đồng thời hoặc reject.

### (5) **`wrap_tool_with_audit` là OUTERMOST wrapper**

Order matters:
```
audit(confirmation(sanitizer(tool)))
```

Không phải:
```
sanitizer(confirmation(audit(tool)))  ← WRONG
```

Vì:
- Audit phải record call **EXACTLY** như model gọi — kể cả bị denied hay bị sanitizer quarantine
- Nếu audit ở innermost → miss denied calls (không có exec → không log)
- Innermost audit = incomplete audit = broken Principle #7

### (6) **GDPR export = DECRYPTED, wipe = counts only**

**Export** (DCL-056): JSON archive self-describing, schema_version envelope, semantic text **DECRYPTED** (portability nghĩa là user đọc được), episodes as JSON. Đây là **Article 15** — right of access.

**Wipe** (DCL-057): xóa cả semantic + episodic. Audit trail giữ **counts only** — MemoryWipeEvent **KHÔNG có field content-bearing by construction**. Đây là **Article 17** — right to be forgotten, nhưng vẫn audit compliance (wipe happened, when, by whom).

CLI prompt confirm unless `--yes` — accidental wipe protection.

### (7) **fpdf2 new dependency cho PDF export**

Trade-off: extra dependency vs manual PDF gen. Chose fpdf2 vì:
- Core fonts đủ Latin-1 (EN + FR)
- Không cần TTF external
- Deterministic layout

Non-Latin-1 punctuation transliterated (vd em-dash `—` → hyphen). Test extract lại PDF qua pypdf → verify content preserved.

---

## 6. Bóc tách từng ticket

### DCL-050 — ChromaDB persistent client

**File**: [declaw/memory/chroma.py](../declaw/memory/chroma.py), [declaw/memory/embeddings.py](../declaw/memory/embeddings.py).

- `build_chroma_client(data_dir)` → persistent, telemetry OFF
- Collections namespaced `declaw_<purpose>` (validated slug, no `..`, no unicode surprise)
- **`Embedder` seam**: injectable interface, default `build_ollama_embedder()` uses nomic-embed-text via `OllamaClient.embed()` (new `/api/embed` method DCL-050 adds)
- Chroma default embedder (internet ONNX) never engaged — even accidentally

**Restart preserves vectors** — acceptance.

### DCL-051 — Fernet at-rest encryption

**File**: [declaw/memory/crypto.py](../declaw/memory/crypto.py).

- Fernet symmetric encryption, key stored via keyring (DCL-070)
- Text encrypted BEFORE Chroma sees it
- Persisted `.sqlite`/`.parquet` files scanned in tests: plaintext substring MUST NOT appear

**Dependency**: DCL-070 (keyring wrapper) pulled forward from Phase 6 for this.

### DCL-052 — Short-term conversation buffer

**File**: [declaw/memory/buffer.py](../declaw/memory/buffer.py).

- `deque(maxlen=N)` FIFO ring over LangChain messages
- Strict FIFO eviction — oldest first
- Copy-safe reads (return `list(deque)`, không expose deque directly)
- **In-memory by design** — Phase 9 sẽ hold one per conversation (không persist across restart intentionally)

### DCL-053 — Long-term semantic memory

**File**: [declaw/memory/semantic.py](../declaw/memory/semantic.py).

- `SemanticMemory.add(text, metadata)` — encrypt + store
- `.search(query, k=5)` — top-k retrieval, decrypt in `MemoryHit`
- `.export_all()`, `.wipe()` — GDPR support
- Deterministic fake embedder in tests → top-k acceptance **exact** (không depend trên real embedding stochasticity)

### DCL-054 — Episodic memory

**File**: [declaw/db/models.py](../declaw/db/models.py) (Episode model), [declaw/memory/episodic.py](../declaw/memory/episodic.py).

Migration `3f1c2a9d4e5b`:
- `Episode` table: uuid PK, task FK, JSON tags, tz-aware started/finished, indexed started_at
- `record(task_id, summary, tags)` — insert
- `query(on=date, tag=None)` — SQL WHERE date + Python filter tag (documented local-scale trade-off; if tag count grows → dedicated table)
- `export_all()`, `wipe()`

Full alembic chain verified against fresh DB (migration → schema → CRUD → wipe).

### DCL-055 — Memory retrieval in context assembly

**File**: [declaw/brain/memory_context.py](../declaw/brain/memory_context.py).

`with_memory(model, retrieve)` composable wrapper:
- Latest HumanMessage = query
- Retrieve top-k
- Fold vào ONE SystemMessage với token budget
- **Frame as data-not-instructions** (chống indirect injection từ memory)
- Inject just BEFORE newest turn
- Model-facing view only — không persist vào AgentState
- Retrieval failure non-fatal (log warning, continue)

**NOT wired vào default `build_brain`** — same rule as system prompt.

### DCL-056/057 — GDPR export + wipe

**File**: [declaw/memory/gdpr.py](../declaw/memory/gdpr.py).

CLI:
```powershell
declaw memory export --output archive.json
declaw memory wipe [--yes]
```

Archive shape:
```json
{
  "schema_version": 1,
  "exported_at": "2026-07-04T14:32:11+00:00",
  "semantic": [
    {"id": "...", "text": "<DECRYPTED>", "metadata": {...}}
  ],
  "episodes": [
    {"uuid": "...", "task_id": "...", "started_at": "...", ...}
  ]
}
```

Wipe empties BOTH stores. Emits:
- `MemoryExportEvent` (fields: count only, no content)
- `MemoryWipeEvent` (fields: counts only, structurally cannot leak content)

### DCL-060 — Typed, versioned audit events

**File**: [declaw/audit/events.py](../declaw/audit/events.py).

Union of frozen pydantic models, discriminated on `event_type`:
- `ToolCallEvent`
- `NetworkCallEvent`
- `QuarantineEvent`
- `PermissionPromptEvent`
- `PluginPermissionEvent` (DCL-084)
- `MemoryExportEvent`, `MemoryWipeEvent`

`schema_version` on every payload → migration story documented.

`to_db_row(event) -> AuditEvent` / `event_from_row(row) -> Event` — projection onto DCL-005 `audit_events` table.

**`clip_args`**: string args longer than 200 chars → SHA-256 fingerprint + truncated head. Audit DB không duplicate whole (possibly privileged) documents.

### DCL-061 — Real-time audit logger

**Files**: [declaw/audit/logger.py](../declaw/audit/logger.py), [declaw/audit/tooling.py](../declaw/audit/tooling.py), [declaw/audit/sinks.py](../declaw/audit/sinks.py).

- `AuditLogger` protocol
- `DbAuditLogger` (production) — one committed session per event, storage errors logged not raised
- `InMemoryAuditLogger` (tests)

`wrap_tool_with_audit(tool, logger)` = OUTERMOST wrapper. Order: `audit → confirmation → sanitizer → tool`.

**Detect denial**: exact match against DeClaw-generated denial string. `denial_message` made public in `confirmation.py` so audit can compare.

**Confirmation decision** → `PermissionPromptEvent` (optional `audit` param on confirmation provider).

**Quarantine → DB**: `quarantine_db_sink` bridge. Sync→async carefully (create_task under running loop + strong refs, else asyncio.run — never leak task).

**Composite sink**: append to loguru AND DB.

`registry.langchain_tools(..., audit=...)` wires everything.

`declaw chat` bootstraps schema (`ensure_schema` = idempotent create_all; alembic stamping for packaged apps = Phase 14).

### DCL-062/063 — NL audit summary + daily report

**Files**: [declaw/audit/summary.py](../declaw/audit/summary.py), [declaw/audit/report.py](../declaw/audit/report.py).

CLI: `declaw report [--date YYYY-MM-DD]`

**Deterministic templates**:
- Per-tool EN + FR verbs (`filesystem_read` → "read" / "a lu")
- Denied/failed suffixes
- Quarantine lines
- **MVP headline last line**: "Data left this device: yes/no" derived from `NetworkCallEvent.flagged`

`daily_report` groups by task within a UTC day. Unreadable rows counted (not fatal — audit robust).

### DCL-064 — Network egress monitor

**File**: [declaw/audit/egress.py](../declaw/audit/egress.py).

Monkeypatch `httpx.AsyncClient.send` and `Client.send`:
- Every outbound request → NetworkCallEvent
- Host outside `allowed_hosts_from_settings()` (loopback + Ollama) → `flagged=True` + loguru warning

Installed as context manager quanh `declaw chat` — mọi Ollama call là NetworkCallEvent (flagged=False vì trong allowlist).

**In-process only**. OS-level = Phase 12/DCL-216.

### DCL-065 — Audit export

**File**: [declaw/audit/export.py](../declaw/audit/export.py).

CLI: `declaw audit export --format {json|markdown|pdf} --output file`

- **JSON**: full typed payloads with envelope → round-trips through schema
- **Markdown**: one-line-per-event table
- **PDF**: fpdf2 core fonts, Latin-1 for EN+FR, non-Latin-1 transliterated

PDF verified in tests by extracting text back via pypdf.

### DCL-070 (pulled forward) — Keyring wrapper

**File**: [declaw/credentials/store.py](../declaw/credentials/store.py).

Original ticket Phase 6, pulled forward as dependency of DCL-051 (Fernet key must be vaulted).

- `CredentialStore` = namespaced CRUD over OS vault (Windows Credential Manager / Keychain / KWallet)
- Idempotent delete (delete twice → no error)
- **`KNOWN_SECRET_NAMES` registry + `purge()`**: keyring backends can't enumerate → this list IS the uninstaller story. **Extend it với every new secret**.
- Tests use in-memory backend — real vault never touched

DCL-074 (encrypted file fallback) is Phase 6 proper — xem [phase-6-review.md](./phase-6-review.md).

---

## 7. CLI mới: `report`, `memory`, `audit`

Phase 5 adds 3 new subcommand groups:

### `declaw report`

```powershell
# Today's report
declaw report

# Specific day
declaw report --date 2026-07-01
```

Output (EN):
```
Report — 2026-07-04

Task t_20260704_003 (14:22–14:24):
- DeClaw read 2 files (contract_a.pdf, contract_b.pdf).
- DeClaw quarantined 1 file (suspicious.pdf).

Task t_20260704_004 (15:10–15:12):
- DeClaw moved 1 file (draft.txt → archive/draft.txt) after user confirmation.

Data left this device: no.
```

### `declaw memory export|wipe`

```powershell
# Export archive
declaw memory export --output my_data.json

# Wipe (prompts unless --yes)
declaw memory wipe --yes
```

### `declaw audit export`

```powershell
# JSON (machine-readable, full envelope)
declaw audit export --format json --output audit.json

# Markdown (human-readable table)
declaw audit export --format markdown --output audit.md

# PDF (share with lawyer/compliance)
declaw audit export --format pdf --output audit.pdf
```

---

## 8. GDPR compliance — export + wipe

DeClaw target market = EU regulated professionals. GDPR compliance là **product requirement**, không "nice-to-have".

### Article 15 — Right of access

User được quyền **truy cập tất cả data về mình**. `declaw memory export` implement:
- Semantic memory: DECRYPTED text (readable), metadata, timestamps
- Episodic memory: task history, summary, tags
- Self-describing archive (schema_version, exported_at)

### Article 17 — Right to be forgotten

User được quyền **xóa tất cả data về mình**. `declaw memory wipe` implement:
- Empty semantic + episodic stores
- Audit trail giữ **counts only** — `MemoryWipeEvent` structurally không carry content
- Wipe itself is audited (compliance requires knowing wipe happened, when, by whom)

### Article 30 — Records of processing

Organization phải maintain **records of processing activities**. `declaw audit export --format pdf` cho lawyer/DPO review.

### Không phải "GDPR compliance certification"

Documented honestly: DeClaw provide **mechanisms** để user/organization comply. Certification (ISO 27001, SOC 2) là organizational process, không phải code.

---

## 9. Network egress monitor — "data left device"

### Value proposition core

DeClaw bán *"100% local, nothing leaves the device"*. Nếu không **provable** → không tin. Egress monitor là **proof mechanism**.

### Cách hoạt động

```python
# declaw/audit/egress.py
def install_egress_monitor(logger, allowed_hosts):
    original_async_send = httpx.AsyncClient.send
    original_sync_send = httpx.Client.send

    async def patched_async(self, request, **kw):
        event = NetworkCallEvent(
            host=request.url.host,
            method=request.method,
            flagged=(request.url.host not in allowed_hosts),
            ...
        )
        logger.log(event)
        return await original_async_send(self, request, **kw)

    httpx.AsyncClient.send = patched_async
    # ... symmetric for sync
```

Context manager pattern:
```python
with install_egress_monitor(logger, ["127.0.0.1", "localhost"]):
    # declaw chat runs here
    ...
```

### Allowlist

`allowed_hosts_from_settings(settings)`:
- `localhost`, `127.0.0.1`, `::1` — loopback always allowed
- `settings.ollama_base_url` host — usually `localhost` too

Nếu Ollama chạy remote (advanced dev config), host that được thêm vào allowlist.

**Bất cứ host nào khác** → `flagged=True` + loguru WARN log.

### Daily report line

`daily_report` cuối cùng có:
```
Data left this device: no.
```

Derived từ `any(event.flagged for event in network_events_today)`. Yes/no clear cho user.

### Limitations

- **In-process only** — subprocess bypass httpx sẽ không bị catch
- `requests` không hook (không phải DeClaw dependency)
- OS-level enforcement (iptables, firewall) = Phase 12 / DCL-216

---

## 10. Verify chạy đúng

### Bước 1 — Unit tests

```powershell
# Phase 5 memory tests
uv run pytest tests/unit/test_memory_*.py tests/unit/test_crypto*.py -v

# Phase 5 audit tests
uv run pytest tests/unit/test_audit_*.py -v

# Both together
uv run pytest tests/unit/test_memory_*.py tests/unit/test_audit_*.py tests/unit/test_credentials_store.py -v
```

Mong đợi: ~100+ tests all pass.

### Bước 2 — Alembic migration

```powershell
# Fresh DB
Remove-Item declaw.db -ErrorAction SilentlyContinue

# Run all migrations
uv run alembic upgrade head

# Verify migrations applied
uv run alembic current
# Phải hiện latest migration hash
```

### Bước 3 — Live audit smoke test

```powershell
# Chat, do a few tool calls
uv run declaw chat --debug
you> Use the filesystem_list tool with path '.'
you> /exit

# Check audit report
uv run declaw report
# Should list the filesystem_list call

# Export as PDF
uv run declaw audit export --format pdf --output test.pdf
# Open test.pdf — verify events readable
```

### Bước 4 — Verify egress monitor active

Trong chat, mọi turn có gọi Ollama → NetworkCallEvent flagged=False. Nếu manually add fake `httpx.get("https://evil.com")` vào code → sẽ warning trong loguru + flagged=True trong report.

### Bước 5 — GDPR flow

```powershell
# Populate memory (nếu semantic wire — currently not default)
# Then export
uv run declaw memory export --output my_data.json

# Verify archive readable + complete
Get-Content my_data.json | ConvertFrom-Json | Format-List

# Wipe
uv run declaw memory wipe --yes

# Verify empty
uv run declaw memory export --output after_wipe.json
# semantic: [], episodes: []
```

---

## 11. Trade-off honest

### ⚠️ Embedding vectors NOT encrypted

Chroma cần plaintext vector để search. Embedding-inversion attack có thể approximate text. **Documented** → Phase 12 consideration. Mitigation options:
- Encrypted search schemes (research area)
- Homomorphic encryption (too slow for MVP)
- Just accept for v0.1, warn user

### ⚠️ Egress monitor in-process only

Subprocess/native code bypass httpx = not caught. OS-level enforcement (DCL-216 Phase 12) sẽ complete story. For MVP, in-process là **90% coverage** — Python code paths.

### ⚠️ Audit summary templates need per-tool maintenance

Add new tool → forget to add EN+FR verbs → report shows generic "used X tool". Follow-up: enforce template presence in tool registration (linting hook).

### ⚠️ `task_id` chưa threaded qua chat tool calls

Audit events từ REPL có `task_id=None` cho đến khi tasks được created per user turn. Natural home: Phase 9 gateway. Currently: audit works but grouping by task hạn chế.

### ⚠️ Episodic memory chưa POPULATED by brain

Không có episode nào được record lúc end-of-task hiện tại. Wire khi tasks exist (Phase 9). Currently: episodic store exists, waiting for producer.

### ⚠️ `with_memory` retrieval NOT wired default

Same rule as system prompt: no additions to prompt without A/B probe on qwen2.5:3b. Wrapper composable, waiting for probe.

### ⚠️ `ensure_schema` create_all thay Alembic stamping

Chat REPL uses `create_all` idempotent — OK for dev. Packaged apps cần alembic stamping — Phase 14 concern.

### ⚠️ NL summary deterministic không "natural" như LLM

Trade-off intentional. Regulated professional > pretty prose. Documented.

---

## 12. Checklist review

### ✅ Memory
- [ ] ChromaDB telemetry OFF (`anonymized_telemetry=False`)
- [ ] Embedder injectable — never Chroma's default internet-ONNX
- [ ] Fernet key stored via keyring, NEVER on disk
- [ ] Text encrypted BEFORE Chroma sees — test scans persisted files for plaintext leak
- [ ] Metadata plaintext (labels only, no payload) — convention documented
- [ ] Semantic + episodic có `export_all()` + `wipe()`
- [ ] Buffer FIFO strict — oldest first eviction
- [ ] `with_memory` wrapper composable — NOT wired default

### ✅ Audit
- [ ] `AuditEvent` = discriminated union keyed on `event_type`
- [ ] `schema_version` on every event
- [ ] `clip_args` truncate + SHA-256 fingerprint (audit DB không duplicate documents)
- [ ] `DbAuditLogger` errors logged, NEVER raised (observability không giảm availability)
- [ ] `wrap_tool_with_audit` OUTERMOST — audit → confirmation → sanitizer → tool
- [ ] Denial detected via exact match against `denial_message` public constant
- [ ] Quarantine → DB via `quarantine_db_sink` bridge
- [ ] Composite sink append loguru + DB

### ✅ NL summary + report
- [ ] Templates deterministic, NOT LLM-generated (locked decision)
- [ ] Per-tool EN + FR verb templates
- [ ] Denied/failed suffixes
- [ ] "Data left device: yes/no" last line — MVP DoD #6 headline

### ✅ Egress monitor
- [ ] Patches BOTH `httpx.AsyncClient.send` and `Client.send`
- [ ] Success AND failure emit NetworkCallEvent
- [ ] Allowlist = loopback + Ollama host
- [ ] Outside allowlist → `flagged=True` + loguru warning
- [ ] Context manager pattern — installed around `declaw chat`

### ✅ Export
- [ ] JSON = full typed payload with envelope, round-trips
- [ ] Markdown = one-line-per-event table
- [ ] PDF via fpdf2 core fonts, EN+FR OK, verified via pypdf extract

### ✅ GDPR
- [ ] Export = DECRYPTED (portability)
- [ ] Wipe emits MemoryWipeEvent with **counts only** — no content field by construction
- [ ] CLI wipe prompts unless `--yes`

### ⚠️ Red flags
- ❌ NL summary calls LLM (violates locked decision, hallucination risk)
- ❌ Audit event has raw content field (leak risk)
- ❌ Wrap order != OUTERMOST audit (miss denied calls)
- ❌ ChromaDB `anonymized_telemetry` not explicitly False (default phones home)
- ❌ Embedder falls back to Chroma default (internet ONNX download)
- ❌ Fernet key on disk (should be keyring only)
- ❌ Text passed to Chroma without encryption (plaintext leak)
- ❌ NetworkCallEvent flagged based on IP not host (bypass via DNS trick)
- ❌ Egress monitor only patches AsyncClient (misses sync path)
- ❌ Wipe silent (no audit event) — cannot prove wipe happened

---

## 13. Thuật ngữ

| Term | Nghĩa |
|---|---|
| **Semantic memory** | Vector-based store, retrieve by similarity to query |
| **Episodic memory** | Timestamped log of past events/tasks |
| **Working memory** | Short-term buffer of recent context (few turns) |
| **Procedural memory** | Learned how-to knowledge (not implemented in DeClaw v0.1) |
| **ChromaDB** | OSS vector database, embedded Python |
| **Fernet** | Symmetric encryption from `cryptography` library — AES-128-CBC + HMAC |
| **Embedder** | Function `text -> vector[float]` — model that produces embeddings |
| **`nomic-embed-text`** | Local embedding model (via Ollama), 768-dim |
| **Discriminated union** | Pydantic pattern: union of models keyed on a Literal field (`event_type`) |
| **Schema version envelope** | Field `schema_version: int` on every event — migration support |
| **Monkeypatch** | Runtime replace method on a class — DeClaw does this for `httpx.Client.send` |
| **Allowlist** | Explicit list of allowed items; everything else = deny (fail-closed pattern) |
| **fpdf2** | PDF generation library (fork of fpdf), pure Python |
| **Alembic migration** | Version-controlled schema change — SQLAlchemy standard |
| **`ensure_schema`** | Idempotent create_all — dev convenience, not for packaged apps |
| **Keyring** | OS-native secret store (Windows Credential Manager, macOS Keychain, Linux KWallet) |
| **GDPR** | General Data Protection Regulation (EU) |
| **Article 15 / 17 / 30** | GDPR articles: right of access / right to be forgotten / records of processing |

---

## Related docs

- [phase-0-review.md](./phase-0-review.md) — Foundation (DB, config, log — Phase 5 depends on)
- [phase-1-review.md](./phase-1-review.md) — Brain (`with_memory` composable wrapper is a Phase 1 pattern)
- [phase-2-review.md](./phase-2-review.md) — Tools (audit wraps tools)
- [phase-4-review.md](./phase-4-review.md) — Sanitizer (quarantine bridges into audit)
- [phase-6-review.md](./phase-6-review.md) — Credentials + Permissions (DCL-070 landed here, DCL-074 in Phase 6)
- [CLAUDE.md](../CLAUDE.md) — Living dev context
- [TICKETS.md](../TICKETS.md) — DCL-050..057, 060..065

---

**Last updated**: 2026-07-04
