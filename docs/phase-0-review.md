# Phase 0 — Project Foundation: Hướng dẫn review cho người mới

> **Đối tượng**: reviewer hoặc contributor mới. Đọc xong hiểu **tại sao Phase 0 tồn tại**, **cách nó chuẩn bị nền cho toàn bộ project**, và **cách verify từng ticket chạy đúng**.

---

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Tại sao cần Phase 0?](#2-tại-sao-cần-phase-0)
3. [Các quyết định thiết kế cốt lõi](#3-các-quyết-định-thiết-kế-cốt-lõi)
4. [Bóc tách từng ticket](#4-bóc-tách-từng-ticket)
5. [Kiểm tra sức khỏe: pre-flight script](#5-kiểm-tra-sức-khỏe-pre-flight-script)
6. [Verify chạy đúng](#6-verify-chạy-đúng)
7. [Trade-off honest](#7-trade-off-honest)
8. [Checklist review](#8-checklist-review)
9. [Thuật ngữ](#9-thuật-ngữ)

---

## 1. TL;DR — 30 giây

Phase 0 là **nền móng kỹ thuật** cho toàn dự án — 7 ticket (DCL-001..007) build những thứ mà **mọi phase sau đều phụ thuộc**:

- Cấu trúc project + `uv` (package manager)
- **Config có type-safe** (pydantic-settings) — enforce ràng buộc bảo mật ngay tại lớp cấu hình
- **Database** (SQLite + Alembic migrations) — cho task history + audit trail
- **Logging structured** (loguru JSON) — mọi event debug được
- **Ollama client** — cầu nối với LLM local
- **Pre-flight check** — verify môi trường trước khi start

Không có Phase 0 → không thể bắt đầu Phase 1. Không có gì để nói chuyện với model, không có nơi lưu trạng thái, không có cách log lỗi.

**Status**: ✅ COMPLETE (DCL-001..007). ~40 unit tests, mock hết external dependencies.

---

## 2. Tại sao cần Phase 0?

### Không phải phase "làm cho có"

Nhiều project bỏ qua bước setup nghiêm túc → paid tech debt sau. Phase 0 của DeClaw làm ngược lại: **enforce constraint bảo mật ngay từ lớp config**, để mọi phase sau **không thể vi phạm** kể cả khi dev vô ý.

Ví dụ: 7 Inviolable Principles có nguyên tắc #2 *"NEVER bind the gateway outside 127.0.0.1"*. Phase 0 encode nguyên tắc này **ngay trong config validator** — code muốn set `host = "0.0.0.0"` sẽ raise ValidationError. Constraint không phải "tùy dev nhớ", mà là **structural**.

### Đầu tư sớm = trả giá thấp

Nếu bỏ Phase 0:
- Config text-based → dev quên set → prod bind sai host → **catastrophic**
- Không có Alembic → schema đổi tay → prod database drift → **data corruption**
- Log text-flat → grep debug production → 3 giờ thay vì 3 phút
- Không có pre-flight → user chạy `declaw chat` mà Ollama chưa cài → confusing error → churn user

Đây là **security-by-construction** vs security-by-hope.

---

## 3. Các quyết định thiết kế cốt lõi

### (1) **`uv` cho package management**

Không phải pip/poetry/conda. `uv`:
- Nhanh hơn 10-100x (Rust-based)
- **Lockfile committed** (`uv.lock`) — reproducible builds
- Không cần activate venv thủ công — `uv run <cmd>` tự lo

Xem [pyproject.toml](../pyproject.toml) và [uv.lock](../uv.lock).

### (2) **pydantic-settings với validator**

Config = **class Pydantic có type + validator**. Không phải dict, không phải YAML. Ưu điểm:

- **Type-safe**: `settings.port` là `int`, không phải `str`
- **Validation ngay khi load**: sai config → crash lúc startup, không phải lúc runtime
- **Validator custom**: encode 7 Principles (loopback host, valid port range, path expansion...)
- **Env var + `.env` file** support ra of the box

### (3) **SQLite + SQLModel + Alembic**

- **SQLite**: single-file DB, không cần server → chạy local dễ, backup = copy file
- **SQLModel**: unify Pydantic model + SQLAlchemy ORM → một schema cho cả API + DB
- **Alembic**: migration formal — đổi schema phải viết migration → auditable
- **aiosqlite driver**: async native → FastAPI gateway (Phase 9) không bị block

### (4) **loguru JSON logging + ContextVar request_id**

- **JSON output**: mỗi log line = 1 JSON → grep/jq/log aggregator hiểu ngay
- **request_id qua ContextVar**: propagate đúng qua `asyncio.Task` boundaries → concurrent request không cross wires
- **Separate với audit trail**: log = operational (debug), audit = compliance (Principle #7) → 2 kênh khác nhau, không nhầm

### (5) **Ollama client custom, không dùng SDK trực tiếp**

`OllamaClient` wrapper riêng thay vì import `ollama` package. Vì sao:
- **Mock được**: `httpx.MockTransport` inject vào constructor → test không cần daemon
- **Đóng gói API surface**: chỉ expose method DeClaw dùng, không leak internal Ollama API
- **Swap được**: mai mốt đổi backend (llama.cpp/vLLM) chỉ sửa 1 file

### (6) **Pre-flight check độc lập với runtime**

`declaw/preflight.py` là **module** với 4 check function độc lập. `scripts/preflight.py` chỉ là Rich-renderer bên ngoài.

→ FastAPI gateway (Phase 9) sẽ import module này để check môi trường lúc startup, **không** phải fork subprocess chạy script.

---

## 4. Bóc tách từng ticket

### DCL-001 — Project scaffold

**Delivered**: uv-managed Python 3.12 project, full folder skeleton, pyproject.toml với tất cả v0.1 dependencies, `declaw` Typer CLI với 5 commands (`version`/`status`/`start`/`stop`/`chat`).

**File chính**:
- [pyproject.toml](../pyproject.toml) — dependencies + entry point `declaw = "declaw.main:cli"`
- [declaw/main.py](../declaw/main.py) — Typer CLI + `console.print` Rich output
- Folder skeleton: `declaw/{brain,tools,sanitizer,sandbox,plugin_host,memory,audit,credentials,db,gateway}/` — mỗi cái có `__init__.py` (đa số rỗng, đánh dấu package)

**Verify**:
```powershell
uv sync                # 196 packages resolved
uv run declaw --help   # In ra 5 commands
```

### DCL-002 — CLAUDE.md living context

Không phải code — là **document quan trọng nhất** của project. Ghi:
- Locked architectural decisions (không đổi mà không bàn)
- 7 Inviolable Principles
- Phase gating rules
- Working rules (commit format, TDD cho security-critical)
- **Completed tickets** — living log các ticket đã done
- **Open decisions** — deferred decisions với reasoning
- **Notes for next session** — hand-off note

Xem [CLAUDE.md](../CLAUDE.md).

### DCL-003 — Ollama integration + health check

**Delivered**: [declaw/brain/ollama_client.py](../declaw/brain/ollama_client.py) — async `OllamaClient` (httpx-based).

3 method:
- `version() -> str` — GET `/api/version`, raise on failure
- `list_models() -> tuple[str, ...]` — GET `/api/tags`, list model đã pull
- `health() -> OllamaHealth` — **never raises**, aggregate snapshot cho `declaw status`

`OllamaHealth` là frozen dataclass:
```python
@dataclass(frozen=True)
class OllamaHealth:
    reachable: bool
    version: str | None
    models: tuple[str, ...]
    error: str | None = None
```

Tách `version`/`list_models` (strict, raise) khỏi `health()` (lenient, aggregate) → caller nào cần xử lý lỗi cụ thể dùng cái strict, UI/status dùng cái lenient.

**Tests**: 6 unit tests với `httpx.MockTransport` — no live daemon needed.

### DCL-004 — Config system

**Delivered**: [declaw/config.py](../declaw/config.py) — pydantic-settings `Settings` class.

Key features:
- `env_prefix="DECLAW_"` → mọi env var có tiền tố này
- `OLLAMA_BASE_URL` là **unprefixed alias** (Ollama chuẩn dùng tên này)
- **Loopback validator**: `host` chỉ chấp nhận `127.0.0.1`, `localhost`, `::1` — encode Principle #2
- **Port range**: 1024-65535
- **Path expansion**: `~/.declaw` → `/home/user/.declaw` tự động
- **Language enum**: `en` | `fr` — không cho tự do string
- `get_settings()` là `@lru_cache` singleton → 1 process 1 instance

**Tests**: 10 unit tests cover defaults, env loading, validation, singleton behavior, `.env` loading.

### DCL-005 — SQLite + SQLModel + Alembic

**Delivered**:
- [declaw/db/engine.py](../declaw/db/engine.py) — async engine + sessionmaker
- [declaw/db/models.py](../declaw/db/models.py) — 2 model: `Task` (UUID PK, status enum, prompt/result/error) + `AuditEvent` (append-only, JSON payload, FK to task)
- [alembic/](../alembic/) — Alembic setup + initial migration

Alembic config đọc DB URL từ `Settings` (override qua `DECLAW_DB_URL` cho test). `render_as_batch=True` để SQLite support ALTER (SQLite native không có).

**Tests**: 5 CRUD smoke tests với SQLite in-memory.

Xem chi tiết pattern lazy singleton của engine trong `get_engine()` + double-checked locking.

### DCL-006 — Structured JSON logging

**Delivered**: [declaw/log.py](../declaw/log.py) — loguru wrapper.

Exports:
- `configure(level)` — setup once at startup
- `logger` — global loguru logger
- `use_request_id(rid)` — context manager set request_id cho log block

Mỗi log line:
```json
{
  "timestamp": "2026-06-28T14:32:11.421+00:00",
  "level": "INFO",
  "message": "task started",
  "request_id": "req_abc123",
  "logger": "declaw.gateway.tasks",
  "extra": {"task_id": "t_..."},
  "exception": null
}
```

**request_id là ContextVar** — propagate qua `asyncio.Task` boundary (khác `threading.local`). Concurrent request A/B/C sẽ có request_id riêng, không cross wires.

**Không phải audit trail** — Principle #7 audit sẽ live ở `declaw/audit/` (Phase 5). Log này chỉ operational debug.

**Tests**: 8 unit tests.

### DCL-007 — Pre-flight check script

**Delivered**: [declaw/preflight.py](../declaw/preflight.py) — 4 check + `run_all()`.

Checks:
1. **Ollama reachable** — GET `/api/version` succeed
2. **Model pulled** — configured model trong list `/api/tags`
3. **Docker available** — `docker version` subprocess exit 0 (chú ý: dùng subprocess **không** import docker SDK, vì SDK fail-at-import khi Docker vắng mặt)
4. **Gateway port free** — thử `socket.bind` port cấu hình

Mỗi check return `CheckResult`:
```python
@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str
    remedy: str | None    # ← actionable fix instruction
```

**`remedy` là field riêng, không nhét vào message** — vì cho phép UI/CLI render khác nhau (Rich table với column riêng cho remedy).

[scripts/preflight.py](../scripts/preflight.py) là **thin Rich-renderer** — logic ở module, script chỉ render.

**Tests**: 11 unit tests với mock Ollama (httpx.MockTransport), mock Docker (monkeypatch `shutil.which`/`subprocess.run`), real `socket.bind` cho port negative case.

---

## 5. Kiểm tra sức khỏe: pre-flight script

`scripts/preflight.py` là **entry point verify Phase 0 chạy đúng end-to-end**.

```powershell
uv run python scripts/preflight.py
```

Output mong đợi (all green):
```
                    DeClaw pre-flight
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ check            ┃ status ┃ message                                            ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ollama.reachable │ PASS   │ Ollama v0.30.11 reachable at http://localhost:11434│
│ ollama.model     │ PASS   │ Model 'qwen2.5:3b' is pulled.                     │
│ docker.available │ PASS   │ Docker daemon reachable (server v29.1.3).         │
│ gateway.port     │ PASS   │ Port 127.0.0.1:7842 is free.                      │
└──────────────────┴────────┴────────────────────────────────────────────────────┘
```

Nếu fail bất cứ cái nào, script in ra **remedy actionable**:
```
Action required:
  • ollama.reachable: Install Ollama from https://ollama.com and run `ollama serve`.
```

Exit code:
- **0**: all pass
- **1**: any fail

**Lưu ý**: Docker check hiện HARD FAIL. Sau khi Open decision **defer shell + Docker khỏi v0.1**, Docker check nên chuyển thành **advisory** (warn only). Chưa làm — đây là follow-up documented.

---

## 6. Verify chạy đúng

### Bước 1 — Unit tests (offline, không cần Ollama)

```powershell
uv run pytest tests/unit/test_config.py tests/unit/test_ollama_client.py tests/unit/test_db.py tests/unit/test_log.py tests/unit/test_preflight.py -v
```

Mong đợi: **~40 tests all pass**. Mọi test dùng mock — không cần daemon nào.

### Bước 2 — CLI smoke test

```powershell
# Version + help
uv run declaw --help
uv run declaw version

# Status (không cần Ollama chạy)
uv run declaw status
# Output có ollama_reachable: no (expected khi daemon chưa chạy)
```

### Bước 3 — Alembic migration

```powershell
# Tạo DB + migrate
uv run alembic upgrade head

# Verify schema
# File declaw.db tạo ở cwd; schema có 2 bảng: task, auditevent
```

### Bước 4 — Pre-flight (cần Ollama + Docker sẵn sàng)

```powershell
uv run python scripts/preflight.py
```

Xem section trên.

---

## 7. Trade-off honest

### ⚠️ Docker check chưa "advisory-only"

Open decision đã chốt drop shell khỏi v0.1 → Docker không cần thiết. Nhưng `preflight.py` vẫn hard-fail nếu Docker vắng mặt. **Follow-up cần**: convert Docker check thành warning-only cho end-user runtime, dev preflight có thể vẫn strict.

### ⚠️ Alembic migration chưa được stamp

Khi packaged cho end-user (Phase 14), Alembic phải "stamp" DB đến version hiện tại lúc install. Chưa implement — CLAUDE.md ghi ("packaged-app migration story is Phase 14").

### ⚠️ Log rotation chưa có

loguru cấu hình cơ bản, không có rotation policy. Cho dev OK, production sẽ cần: max size, max age, compression. Follow-up cho Phase 12+.

### ⚠️ SQLite fine cho MVP, nhưng...

SQLite scale tốt đến vài GB. Nếu user có hàng chục ngàn tasks + audit events → cân nhắc Postgres. Chưa cần lo cho v0.1.

---

## 8. Checklist review

### ✅ Config
- [ ] Loopback validator raise trên `host="0.0.0.0"` — check test [test_config.py](../tests/unit/test_config.py)
- [ ] Port validator raise trên `port=80` (< 1024)
- [ ] Path expansion `~/.declaw` → absolute
- [ ] `get_settings()` singleton (không tạo Settings mới mỗi call)
- [ ] `.env` file load được — test có cover

### ✅ Ollama client
- [ ] `health()` không raise trên connection error → return `reachable=False`
- [ ] `version()` raise `httpx.HTTPStatusError` trên 5xx
- [ ] Mock via `httpx.MockTransport` — test không cần daemon

### ✅ DB
- [ ] `Task` + `AuditEvent` model có index đúng cột
- [ ] Alembic migration chạy được (`upgrade head` không error)
- [ ] `get_engine()` lazy + thread-safe (double-checked locking)
- [ ] Test dùng `build_engine(tmp_path)` — không đụng singleton production

### ✅ Log
- [ ] JSON output đúng shape (timestamp, level, message, request_id, logger, extra, exception)
- [ ] request_id ContextVar propagate qua async task boundary — test có cover
- [ ] `logger.bind(extra=...)` reflect vào `extra` field

### ✅ Preflight
- [ ] Docker check dùng subprocess (NOT `import docker`)
- [ ] Port check dùng real `socket.bind` (test negative case cần thật, không mock được)
- [ ] `CheckResult.remedy` là field riêng — cho phép UI render khác nhau

### ⚠️ Red flags
- ❌ Config value hard-coded ở nhiều nơi (should be `settings.<field>`)
- ❌ `import docker` ở top-level module (SDK fail-at-import khi Docker vắng)
- ❌ Log line concatenate string thay vì dùng `logger.bind(field=value)` → mất structured
- ❌ Test thật database (không dùng `tmp_path`) → CI slow + flaky
- ❌ `httpx.AsyncClient` không có transport param → không mock được

---

## 9. Thuật ngữ

| Term | Nghĩa |
|---|---|
| **uv** | Rust-based Python package manager, thay pip/poetry. Có lockfile committed. |
| **pydantic-settings** | Library con của Pydantic — load config từ env/`.env`/init với validation |
| **SQLModel** | Wrapper hợp nhất Pydantic + SQLAlchemy — một class định nghĩa cả API model lẫn DB model |
| **aiosqlite** | Async driver cho SQLite. Dùng qua SQLAlchemy async |
| **Alembic** | Migration tool của SQLAlchemy. Version schema đổi = 1 migration file, review được |
| **loguru** | Logging library Python, JSON output support out of the box |
| **ContextVar** | Python 3.7+ primitive, giống `threading.local` nhưng đúng với `asyncio.Task` |
| **httpx.MockTransport** | Test utility cho httpx — replace network transport bằng function trả response fake |
| **`@lru_cache`** | Decorator Python cache kết quả function call. Dùng cho singleton pattern |
| **`env_prefix`** | pydantic-settings option — mọi env var có prefix này mới được load. Vd `DECLAW_MODEL` với prefix `DECLAW_` |
| **Loopback address** | `127.0.0.1`, `localhost`, `::1` — chỉ máy local, không ra network. Principle #2 enforce |
| **Health snapshot** | Kết quả kiểm tra sức khỏe tại một thời điểm, không phải periodic heartbeat |
| **Pre-flight** | Kiểm tra môi trường trước khi start app. Fail nhanh với remedy actionable |

---

## Related docs

- [CLAUDE.md](../CLAUDE.md) — Living dev context
- [TICKETS.md](../TICKETS.md) — DCL-001..007 với acceptance criteria
- [README.md](../README.md) — High-level project overview + quickstart
- [phase-1-review.md](./phase-1-review.md) — Phase 1 review (Core Brain)

---

**Last updated**: 2026-06-28
