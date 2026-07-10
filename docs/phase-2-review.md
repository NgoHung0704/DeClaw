# Phase 2 — Tool Layer: Hướng dẫn review cho người mới

> **Đối tượng**: reviewer hoặc contributor mới. Đọc xong hiểu **thế nào là "typed tool"**, **cách DeClaw chặn escape khỏi workspace**, và **tại sao mọi write đều cần confirmation**.

---

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Tại sao "typed tools" quan trọng](#2-tại-sao-typed-tools-quan-trọng)
3. [Các quyết định thiết kế cốt lõi](#3-các-quyết-định-thiết-kế-cốt-lõi)
4. [Kiến trúc + luồng dữ liệu](#4-kiến-trúc--luồng-dữ-liệu)
5. [Bóc tách từng ticket](#5-bóc-tách-từng-ticket)
6. [Path traversal defense — hardening đặc biệt](#6-path-traversal-defense--hardening-đặc-biệt)
7. [Confirmation gate — MVP DoD #4](#7-confirmation-gate--mvp-dod-4)
8. [Verify chạy đúng](#8-verify-chạy-đúng)
9. [Trade-off honest](#9-trade-off-honest)
10. [Checklist review](#10-checklist-review)
11. [Thuật ngữ](#11-thuật-ngữ)

---

## 1. TL;DR — 30 giây

Phase 2 build **4 tool filesystem thật đầu tiên** cho DeClaw, tuân thủ Principle #6 *("tools take typed, validated parameters — never raw strings")*:

- **`DeclawTool` abstract base** với `args_schema` Pydantic
- 4 tool: `filesystem_read`, `filesystem_list`, `filesystem_write`, `filesystem_move`
- **Confirmation gate**: mọi WRITE/DESTRUCTIVE hỏi user `[y/N]` trước khi chạy
- **Tool registry**: single source of truth cho danh sách tool ship
- **Path traversal defense**: 36-vector corpus + Windows-specific hardening (NTFS ADS, NUL bytes)

Phase 2 kết thúc = **MVP DoD #4 xong** (*"move/rename via natural language with confirmation"*).

**Status**: ✅ COMPLETE (DCL-020..026 + wired vào `declaw chat`). ~50 tests + path traversal corpus 36 vector.

---

## 2. Tại sao "typed tools" quan trọng

### Anti-pattern: raw string tool

Nhiều LLM agent framework có tool kiểu:
```python
@tool
def run_shell(command: str) -> str:
    return subprocess.run(command, shell=True, ...)
```

**Đây là thảm họa security**. Model có thể gọi `run_shell("rm -rf ~")`. Không có validation → không có phòng thủ.

Principle #6 của DeClaw: **NEVER let an LLM call a function with raw user input as a shell string**. Mọi tool phải nhận **typed, validated parameters**.

### DeClaw pattern: typed schema

```python
class FilesystemReadArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative path")
    max_bytes: int = Field(default=100000, ge=1)

class FilesystemReadTool(DeclawTool[FilesystemReadArgs]):
    args_schema = FilesystemReadArgs

    async def _arun(self, path: str, max_bytes: int = 100000) -> str:
        resolved = _resolve_in_workspace(path)  # ← boundary check
        return resolved.read_text(encoding="utf-8")[:max_bytes]
```

- `path` là `str` với description bilingual → model biết cần workspace-relative
- `max_bytes` là `int` với `ge=1` → không thể pass 0 hoặc negative
- `_resolve_in_workspace()` reject absolute paths, `..`, NTFS ADS, NUL bytes
- **Nếu model pass `path="../../../etc/passwd"` → tool raise `WorkspacePathError` NGAY, không đến `read_text`**

Bảo mật là **structural**, không phải "hope model doesn't do bad thing".

---

## 3. Các quyết định thiết kế cốt lõi

### (1) **`DeclawTool[ArgsT]` generic + `args_schema`**

`DeclawTool` là generic Pydantic BaseModel, subclass tham số hóa concrete args schema:

```python
class DeclawTool(BaseModel, Generic[ArgsT]):
    name: str
    description_en: str
    description_fr: str
    classification: ToolClass       # READ / WRITE / DESTRUCTIVE
    args_schema: type[ArgsT]

    async def _arun(self, **kwargs) -> str: ...  # subclass implement
    def run_validated(self, raw_args: dict) -> str:
        validated = self.args_schema.model_validate(raw_args)  # ← runtime check
        return await self._arun(**validated.model_dump())
```

- **Type safety** ở cả compile time (mypy) và runtime (pydantic)
- **Frozen=True** — tool metadata immutable sau construction
- **Bilingual description** — probe cho thấy FR reliability = 0% với description EN only

### (2) **Classification: READ / WRITE / DESTRUCTIVE**

Enum 3 giá trị quyết định routing:

- **READ**: auto-run, không confirm (đọc không nguy hiểm)
- **WRITE**: confirm với user (`filesystem_write`, `filesystem_move`)
- **DESTRUCTIVE**: confirm nghiêm ngặt hơn (chưa có tool nào ship dạng này — reserve)

Đây là **product feature**, không phải fallback: probe data cho thấy 7B accuracy ~60-67% quá thấp để autonomous action. Confirmation gate là cách UX-safe.

### (3) **Workspace-scoped, không phải "sandbox nhẹ"**

Tất cả tool operate **trong `settings.workspace_dir`** (default `~/DeClaw-workspace`). Không bao giờ thoát:

- Absolute path (vd `C:\Windows`) → reject
- `..` traversal → reject
- Windows: `:` (drive spec hoặc NTFS ADS) → reject
- NUL byte injection → reject

Đây **không phải Docker sandbox** (đó là Phase 3, deferred). Đây là **path resolution boundary** — cheaper, structural, đủ cho MVP không có shell.

### (4) **Confirmation provider abstract**

Confirmation không hard-code `input()` từ terminal. Nó là:
```python
ConfirmationProvider = Callable[[DeclawTool, dict], Awaitable[bool]]
```

- CLI dùng `make_console_confirmation_provider(console.input)` → async wrap blocking prompt qua `asyncio.to_thread`
- Phase 9 WebUI có thể inject WebSocket confirmation provider — không sửa tool code

Đây là **transport-agnostic pattern** — chuẩn cho reusable business logic.

### (5) **Registry as single source of truth**

`ToolRegistry` là name→tool map. `default_registry()` register **explicitly**:

```python
_BUILTIN_TOOLS: tuple[type[DeclawTool[Any]], ...] = (
    FilesystemReadTool,
    FilesystemWriteTool,
    FilesystemMoveTool,
    FilesystemListTool,
)
```

Explicit tuple = **auditable list** của mọi tool DeClaw ship. Reviewer nhìn 1 chỗ biết attack surface.

**No `eval`/`exec`, no string-driven construction** (Principle #6): chỉ chấp nhận `type[DeclawTool]` concrete subclass.

### (6) **`langchain_tools(...)` là source of truth cho wiring**

Registry method `langchain_tools(language, approve, sanitizer=None)`:
- **READ tools**: pass through `as_langchain_tool(language)` — auto-run
- **WRITE/DESTRUCTIVE**: wrap qua `wrap_tool_with_confirmation(tool, language, approve)` — hỏi user trước
- **Tool có `produces_external_content=True`**: wrap qua `wrap_tool_with_sanitizer` (Phase 4)

Cùng 1 list feed vào `bind_tools()` (model) và `ToolNode` (executor). **Không thể** tạo mismatch — model biết tool nào, ToolNode có tool đó.

---

## 4. Kiến trúc + luồng dữ liệu

### Flow: user gõ `Use the filesystem_write tool with path 'notes.txt' and content 'hi'`

```
1. Brain (LangGraph) nhận message user
2. Ollama model return AIMessage với tool_call:
   filesystem_write({"path": "notes.txt", "content": "hi", "overwrite": false})

3. ToolNode nhận tool_call, tìm tool "filesystem_write" trong registry
4. Registry: filesystem_write là WRITE → wrapped với ConfirmationGate

5. ConfirmationGate.arun():
   → call approve(tool, args)
   → approve = make_console_confirmation_provider(console.input, language)
   → prompt user: "DeClaw wants to call filesystem_write({'path': 'notes.txt', ...}). Approve? [y/N]"
   → run blocking console.input qua asyncio.to_thread (không stall event loop)
   → user gõ 'y' → return True

6. Since approved:
   → tool.run_validated({"path": "notes.txt", "content": "hi", "overwrite": false})
   → args_schema validate: path str, content str, overwrite bool — pass
   → tool._arun(path="notes.txt", content="hi", overwrite=False)
   → _resolve_in_workspace("notes.txt") → workspace/notes.txt (safe)
   → write UTF-8 to file
   → return "Wrote 2 bytes to notes.txt"

7. If user gõ Enter (deny) or EOF:
   → return False → tool return localized message: "User denied..."
   → Brain nhận denial, không exec

8. ToolMessage("Wrote 2 bytes to notes.txt") về Brain
9. Brain summarize → user
```

### `_resolve_in_workspace` — path boundary

**Hot path** của mọi tool. 3 lớp:
```python
def _resolve_in_workspace(raw_path: str) -> Path:
    # 1. Reject absolute (C:\, /, //server\share)
    if os.path.isabs(raw_path) or _is_unc(raw_path):
        raise WorkspacePathError(...)

    # 2. Windows-only: reject `:` (drive spec OR NTFS Alternate Data Stream)
    if sys.platform == "win32" and ":" in raw_path:
        raise WorkspacePathError(...)

    # 3. Resolve absolute + canonicalize
    resolved = (workspace / raw_path).resolve()

    # 4. Reject if outside workspace (path.relative_to raise)
    resolved.relative_to(workspace)  # raise if outside

    # 5. Reject NUL byte
    if "\x00" in raw_path:
        raise WorkspacePathError(...)

    return resolved
```

4 consumer trong `filesystem.py`. Candidate promote lên `declaw/tools/builtin/_paths.py` (documented follow-up).

---

## 5. Bóc tách từng ticket

### DCL-020 — `DeclawTool` abstract base

**Delivered**: [declaw/tools/base.py](../declaw/tools/base.py) — Pydantic-validated tool definition.

`DeclawTool[ArgsT]` là generic Pydantic BaseModel. Concrete subclass:
```python
class EchoTool(DeclawTool[EchoArgs]):
    name: str = "echo"
    description_en: str = "Echo the given message back."
    description_fr: str = "Renvoie le message donné."
    classification: ToolClass = ToolClass.READ
    args_schema: type[EchoArgs] = EchoArgs

    async def _arun(self, message: str) -> str:
        return message
```

- **`_arun` abstract by convention** — base raise NotImplementedError (không dùng ABCMeta vì conflict với ModelMetaclass)
- `run_validated(raw_args)` validate qua schema → call `_arun` — pydantic ValidationError trên bad args
- `description_for(language)` switch EN/FR
- `as_langchain_tool(language)` build StructuredTool — LangChain-compatible

**Tests**: 11 unit tests.

### DCL-021 — `filesystem_read` (READ)

**Delivered**: [declaw/tools/builtin/filesystem.py](../declaw/tools/builtin/filesystem.py) — `FilesystemReadTool`.

Args:
- `path: str` (required, workspace-relative)
- `max_bytes: int` (default 100000, `ge=1`) — cap để 1 tool call không blow context window

**Hot path**: `_resolve_in_workspace` (xem section 4).

**Tests**: 13 tests — happy path, traversal corpus, file-shape errors, schema validation.

### DCL-022 — `filesystem_write` (WRITE) + confirmation

**Delivered**: `FilesystemWriteTool` + [declaw/tools/confirmation.py](../declaw/tools/confirmation.py).

Tool args: `path`, `content`, `overwrite=False`. 2 extra guardrail:
- Refuse overwrite by default (phải `overwrite=true` explicit)
- Refuse silent `mkdir -p` parent (parent phải tồn tại)

**`ConfirmationProvider`**:
```python
ConfirmationProvider = Callable[[DeclawTool[Any], dict], Awaitable[bool]]
```

Chose `Callable` alias over `Protocol` — plain `async def` function match cleanly under mypy strict.

**Test helpers**: `always_approve` / `always_deny`.

**`wrap_tool_with_confirmation(tool, language, approve)`** build StructuredTool:
- Coroutine await `approve` trước khi delegate `run_validated`
- Return localized denial message trên False
- **Wrapped tool giữ nguyên metadata** (name, description, args_schema) → `bind_tools` model không thấy khác gì
- Gate **invisible** với model → model không biết có gate, cứ emit tool_call bình thường

### DCL-023 — `filesystem_move` (WRITE)

**Delivered**: `FilesystemMoveTool`. Args: `source`, `destination`, `overwrite=False`.

Order of checks:
1. Source exists
2. Source is file (not dir)
3. Cross-volume check (`source.drive != destination.drive`) — defense-in-depth
4. Destination exists → need `overwrite=true`
5. Destination parent exists
6. `source.replace(destination)` (atomic, cross-platform)

Confirmation reuse DCL-022 unchanged.

**Tests**: 11 tests — every refusal verifies **side-effect**: source never lost, destination never created. Botched move = user data loss = critical.

### DCL-024 — `filesystem_list` (READ)

**Delivered**: `FilesystemListTool`. Single arg `path: str = "."` (default workspace root).

**Format choice: plain text**, không JSON/markdown. Probe data: Mistral 7B re-interpret structured output kém → plain text token-cheap, model-friendly:
```
type | size  | modified            | name
file |    59 | 2026-06-16 22:07:27 | test.txt
dir  |     - | 2026-06-15 10:12:33 | archive
```

Empty dir → `"{path} is empty."` (không phải empty string — model có thể misread).

**Tests**: 9 tests.

### DCL-025 — Tool registry

**Delivered**: [declaw/tools/registry.py](../declaw/tools/registry.py).

`ToolRegistry` — name → `DeclawTool` instance map. `register` là class decorator or direct call:
```python
@registry.register
class MyTool(DeclawTool[MyArgs]): ...

# OR:
registry.register(MyTool)  # same thing
```

- Duplicate → `ValueError`
- Unknown → `UnknownToolError(KeyError)`
- `json_schemas()` return `{name: args_schema.model_json_schema()}`

`default_registry()` register 4 built-in filesystem tools từ `_BUILTIN_TOOLS` tuple — **single auditable list**.

**`langchain_tools(language, approve, sanitizer=None)`** là source of truth cho wiring (xem section 3.6).

**Tests**: 11 tests.

### DCL-026 — Path traversal protection

**Delivered**: [tests/unit/test_path_traversal.py](../tests/unit/test_path_traversal.py) — 36-vector corpus + hardening.

3 nhóm vector:
- **`_ALWAYS_REJECTED`** (13): forward-slash `..`, `/etc/passwd`, NUL bytes — raise trên every OS
- **`_WINDOWS_ONLY_REJECTED`** (12, `skipif != win32`): drive specs, UNC, backslash traversal, `:` NTFS ADS
- **`_CONTAINED_TRICKS`** (11): URL-encoding, unicode dot look-alikes, `~` — phải stay inside workspace

Headline test `test_invariant_never_escapes` parametrize over 36 vector.

**Hardening từ probe**:
1. **NTFS Alternate Data Streams** (`notes.txt:hidden`, `::$DATA`) — resolved inside workspace nhưng là side-channel → reject on Windows via `":" in raw_path` guard
2. **NUL bytes** raise bare `ValueError` from `resolve()` → convert thành `WorkspacePathError` cho auditable boundary

**Follow-up wired vào chat**: `main.py:120+` build console confirmation provider, register vào brain via `default_registry().langchain_tools()`. MVP DoD #4 closed.

---

## 6. Path traversal defense — hardening đặc biệt

Đây là section dành riêng vì đây là **security-critical code**.

### Attack vectors covered

| Vector | Ví dụ | Behavior |
|---|---|---|
| Forward-slash traversal | `../../../etc/passwd` | Raise `WorkspacePathError` |
| Multi-level traversal | `foo/../../../bar` | Raise (resolve trước, check sau) |
| Absolute Unix | `/etc/passwd` | Raise (absolute reject) |
| Absolute Windows | `C:\Windows\System32` | Raise |
| UNC path | `\\server\share\file` | Raise (Windows) |
| NUL byte | `foo\x00.txt` | Raise `WorkspacePathError` |
| NTFS ADS | `notes.txt:hidden`, `file::$DATA` | Raise on Windows (`:` guard) |
| Windows short name | `PROGRA~1\..` | Reject after resolve() canonicalize |
| Symlink escape | symlink→`/etc` | Resolve follow symlink → outside → reject |
| URL encoding | `%2e%2e%2fetc` | Stay inside (không URL-decode) |
| Unicode look-alike | `．．/etc` (fullwidth dot) | Stay inside (không normalize) |
| `~` expansion | `~/secrets` | Stay inside (không expand `~`) |

### Why Windows `:` is Windows-only guard

`sys.platform == "win32"` gated because:
- Windows: `:` **never legal** trong filename → always drive spec hoặc NTFS ADS
- POSIX: `:` **is legal** filename character. Reject nó trên Linux/Mac sẽ block legitimate files

Cross-platform code phải guard OS-specific — đây là ví dụ tốt.

### Corpus locked = regression guard

Corpus có `_ALWAYS_REJECTED`, `_WINDOWS_ONLY_REJECTED`, `_CONTAINED_TRICKS` là **frozen tuples**. Không có "cleanup" hay "refactor" xóa vector. Mỗi vector = 1 CVE (Common Vulnerabilities and Exposures) tránh được.

Add mới OK. Remove NEVER.

---

## 7. Confirmation gate — MVP DoD #4

MVP DoD #4: *"Move/rename/summarize via natural language **with confirmation**"*.

### UX flow

```
you> Please rename test.txt to notes.txt

[Brain thinks]
[Tool call: filesystem_move({"source": "test.txt", "destination": "notes.txt"})]

DeClaw wants to call filesystem_move({'source': 'test.txt', 'destination': 'notes.txt'}). Approve? [y/N]: y

[Tool result: Moved test.txt to notes.txt]
Brain: Done. Renamed test.txt to notes.txt.
```

### Default-deny khi nghi ngờ

- Explicit `y`/`yes`/`o`/`oui` (case-insensitive, trimmed) → approve
- Bất cứ gì khác: Enter, `n`, EOF, Ctrl-C, whitespace → **deny**

Đây là **fail-safe**: user không rõ, tool không chạy. Bảo vệ data loss.

### Async-safe

Console `input()` là blocking. Trong async graph (LangGraph), blocking input sẽ stall event loop → mọi tool khác cũng đứng. Solution:
```python
loop.run_in_executor(None, blocking_input, question)
# OR (modern):
await asyncio.to_thread(blocking_input, question)
```

Console input chạy thread pool → event loop tiếp tục drive các concurrent operation. Đây là **cần thiết** cho FastAPI gateway (Phase 9) — nhiều request đồng thời.

### Transport-agnostic

`make_console_confirmation_provider(prompt_fn, language)` — `prompt_fn` là injectable. CLI dùng `console.input`, WebUI (Phase 9) inject WebSocket message. Same tool code, khác transport.

---

## 8. Verify chạy đúng

### Bước 1 — Unit tests

```powershell
uv run pytest tests/unit/test_tools_base.py tests/unit/test_tools_filesystem.py tests/unit/test_tools_confirmation.py tests/unit/test_tools_registry.py tests/unit/test_path_traversal.py -v
```

Mong đợi: **~50 tests all pass**. Path traversal parametrized với 36 vector.

### Bước 2 — Live chat với `--debug`

```powershell
# Verify workspace + tạo file test
mkdir C:\Users\ADMIN\DeClaw-workspace -ErrorAction SilentlyContinue
"Hello DeClaw." | Out-File -Encoding utf8 C:\Users\ADMIN\DeClaw-workspace\test.txt

# Chạy chat
uv run declaw chat --debug
```

Test 4 tool:

**READ (không confirmation)**:
```
you> Use the filesystem_list tool with path '.'
[tool call] filesystem_list({'path': '.'})
[tool result] file | 13 | ... | test.txt
```

**READ (không confirmation, có sanitizer)**:
```
you> Use the filesystem_read tool with path 'test.txt'
[tool call] filesystem_read({'path': 'test.txt'})
[tool result] Hello DeClaw.
```

**WRITE (có confirmation)**:
```
you> Use the filesystem_write tool with path 'note.txt' and content 'hi'
[tool call] filesystem_write({'path': 'note.txt', 'content': 'hi'})
DeClaw wants to call filesystem_write(...). Approve? [y/N]: y
[tool result] Wrote 2 bytes to note.txt
```

**Deny WRITE**:
```
you> Use the filesystem_write tool with path 'evil.txt' and content 'bad'
DeClaw wants to call filesystem_write(...). Approve? [y/N]:  <Enter>
[tool result] User denied the call to filesystem_write.
```

### Bước 3 — Verify boundary

Trong chat, thử tấn công:
```
you> Use the filesystem_read tool with path '../../../../etc/passwd'
[tool call] filesystem_read({'path': '../../../../etc/passwd'})
[tool result] Error: workspace path traversal rejected
```

Escape KHÔNG xảy ra. Tool raise `WorkspacePathError` → ToolNode surface là ToolMessage error → Brain thấy error, không thấy file.

---

## 9. Trade-off honest

### ⚠️ Không phải sandbox thật

Path resolution boundary chỉ chặn access **filesystem qua tool**. Nếu tool có bug (vd `subprocess.run` với user input) → escape. Phase 3 (Docker sandbox) sẽ là real defense-in-depth cho shell execution.

Nhưng như đã bàn (CLAUDE.md Open decision), MVP v0.1 không có shell → sandbox không cần trong scope.

### ⚠️ Confirmation gate không log decision

Hiện confirmation approve/deny **không** ghi vào audit trail. Principle #7 yêu cầu mọi action loggable. Follow-up: Phase 5 (Memory & Audit, DCL-060+) sẽ hook audit.

### ⚠️ Tool description bilingual, nhưng system prompt không seed FR

Ngay cả với description FR đủ, model reply có thể EN nếu system prompt không pin language. Chờ Qwen A/B probe (xem Phase 1 review).

### ⚠️ Registry pattern hard-code list Phase 2 tool

Tuple `_BUILTIN_TOOLS` liệt 4 tool concrete. Plugin tool (Phase 7+) sẽ register runtime → cần extend registry. Current design OK vì plugin host chưa build.

### ⚠️ Confirmation không có "remember answer"

Mỗi write call = 1 prompt. Nếu user muốn move 100 file → 100 prompt. UX kém. Follow-up: "session approve" (approve all write cho 5 phút), hoặc batch confirmation. Phase 9 (WebUI) sẽ có UI tốt hơn cho batch.

---

## 10. Checklist review

### ✅ Base + Schema
- [ ] `DeclawTool[ArgsT]` generic — subclass parameterize args_schema
- [ ] `args_schema` là Pydantic BaseModel, validate runtime
- [ ] `frozen=True` — tool metadata immutable
- [ ] Bilingual `description_en` + `description_fr` — mandatory
- [ ] `classification` field: READ/WRITE/DESTRUCTIVE — enum, không string

### ✅ Filesystem tools
- [ ] Tất cả 4 tool dùng `_resolve_in_workspace` — không tự roll boundary check
- [ ] `filesystem_write` refuse overwrite by default
- [ ] `filesystem_move` cross-volume check explicit
- [ ] `filesystem_list` output plain text (không JSON) — probe-driven
- [ ] `filesystem_read` có `max_bytes` cap để không blow context

### ✅ Confirmation
- [ ] `ConfirmationProvider` là Callable alias, không Protocol (mypy strict)
- [ ] `always_approve` / `always_deny` test helpers
- [ ] `wrap_tool_with_confirmation` giữ nguyên metadata → invisible với bind_tools
- [ ] EOF/Ctrl-C = deny (default-safe)
- [ ] Async — blocking input qua `asyncio.to_thread`

### ✅ Registry
- [ ] `register()` chỉ chấp nhận `type[DeclawTool]` subclass — no eval/exec
- [ ] Duplicate raise `ValueError`
- [ ] Unknown raise `UnknownToolError(KeyError)`
- [ ] `_BUILTIN_TOOLS` tuple explicit — auditable
- [ ] `langchain_tools()` single source of truth cho READ/WRITE routing

### ✅ Path traversal
- [ ] `_ALWAYS_REJECTED` + `_WINDOWS_ONLY_REJECTED` + `_CONTAINED_TRICKS` corpus locked
- [ ] `test_invariant_never_escapes` parametrized over toàn corpus
- [ ] Windows `:` guard `sys.platform`-gated
- [ ] NUL byte raise `WorkspacePathError` (không bare ValueError)
- [ ] Symlink follow qua `resolve()` — escape thì `relative_to` fail

### ⚠️ Red flags
- ❌ Tool subclass không dùng `args_schema` → args validation bypass
- ❌ Path check dùng `startswith(workspace)` thay vì `relative_to` → bypass với symlink
- ❌ `resolve()` không canonicalize NTFS short name → bypass Windows
- ❌ Confirmation provider default-approve → catastrophic
- ❌ Registry chấp nhận string tool name → eval/exec risk
- ❌ WRITE/DESTRUCTIVE tool skip confirmation trong test → tests silently bypass gate
- ❌ Tool description hard-code EN only → FR reliability collapse (probe-driven)

---

## 11. Thuật ngữ

| Term | Nghĩa |
|---|---|
| **Typed tool** | Tool có schema Pydantic cho args, không nhận raw string |
| **`args_schema`** | Pydantic BaseModel class — định nghĩa shape args tool nhận |
| **Classification** | READ/WRITE/DESTRUCTIVE — quyết định routing (auto vs confirm) |
| **Workspace-scoped** | Tool chỉ operate trong `settings.workspace_dir`, không thoát |
| **Path traversal** | Attack technique: dùng `..` để escape khỏi thư mục dự định |
| **NTFS ADS** | Alternate Data Stream — Windows filesystem feature cho phép `file.txt:hidden`. Side-channel |
| **NUL byte injection** | Attack: nhét `\x00` để truncate path — nhiều lang stop parse at NUL |
| **UNC path** | Universal Naming Convention — `\\server\share\file` Windows network path |
| **Symlink escape** | Attack: tạo symlink trong workspace pointing ra ngoài, dùng để read outside |
| **Canonical path** | Path đã resolve symlink + short name + relative → absolute unique |
| **Confirmation gate** | Layer hỏi user y/N trước khi execute action nguy hiểm |
| **Confirmation provider** | Injectable interface cho confirmation — CLI vs WebSocket vs auto |
| **Transport-agnostic** | Design không phụ thuộc protocol cụ thể — swap transport không sửa business logic |
| **`bind_tools`** | LangChain method attach tool schema vào model — model biết cách emit tool_call |
| **`StructuredTool`** | LangChain tool class chấp nhận `args_schema` — force typed args |
| **`ToolNode`** | LangGraph node execute tool calls, return ToolMessage |
| **Registry** | Central map name→instance, single source of truth for lookup |
| **CVE** | Common Vulnerabilities and Exposures — mỗi vector chống được = 1 CVE tránh |

---

## Related docs

- [phase-0-review.md](./phase-0-review.md) — Phase 0 (Foundation)
- [phase-1-review.md](./phase-1-review.md) — Phase 1 (Core Brain)
- [phase-4-review.md](./phase-4-review.md) — Phase 4 (Sanitizer)
- [CLAUDE.md](../CLAUDE.md) — Living dev context
- [TICKETS.md](../TICKETS.md) — DCL-020..026 với acceptance criteria

---

**Last updated**: 2026-06-28
