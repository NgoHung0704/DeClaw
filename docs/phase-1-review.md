# Phase 1 — Core Brain: Hướng dẫn review cho người mới

> **Đối tượng**: reviewer hoặc contributor mới. Đọc xong hiểu **thế nào là "agentic loop"**, **cách DeClaw ghép LangGraph với Ollama**, và **những quyết định probe-driven** (khác thường!) đã shape Phase 1.

---

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Agent là gì? Agentic loop là gì?](#2-agent-là-gì-agentic-loop-là-gì)
3. [Các quyết định thiết kế cốt lõi](#3-các-quyết-định-thiết-kế-cốt-lõi)
4. [Kiến trúc: 2 node LangGraph](#4-kiến-trúc-2-node-langgraph)
5. [Bóc tách từng ticket](#5-bóc-tách-từng-ticket)
6. [Probe-driven calibration — điểm đặc biệt của Phase 1](#6-probe-driven-calibration--điểm-đặc-biệt-của-phase-1)
7. [Verify chạy đúng](#7-verify-chạy-đúng)
8. [Trade-off honest](#8-trade-off-honest)
9. [Checklist review](#9-checklist-review)
10. [Thuật ngữ](#10-thuật-ngữ)

---

## 1. TL;DR — 30 giây

Phase 1 build **"não" của DeClaw** — vòng lặp agent nói chuyện với LLM local qua tool calling:

- **LangGraph state machine** 2 node: `agent` (think → gọi model) và `tools` (execute tool call)
- **Ollama binding** qua `langchain-ollama` — model tự chọn tool nào gọi, khi nào dừng
- **Context management** trim message list nếu vượt cửa sổ model
- **REPL CLI** — `declaw chat` là user-facing surface đầu tiên
- **Probe framework** — corpus 50 prompt đo accuracy tool-calling → mọi thay đổi model/prompt đều được đo, không đoán

Điểm đặc biệt: Phase 1 có **nhiều quyết định counter-intuitive** driven bởi probe data (vd bỏ system prompt vì nó giảm tool-calling từ 68% xuống 8% trên Mistral 7B). Đây là **evidence-based engineering** hiếm gặp trong LLM projects.

**Status**: ✅ COMPLETE (DCL-010..017 + post-Phase-1 calibration + model swap 2026-06-28).

---

## 2. Agent là gì? Agentic loop là gì?

### Agent

Đơn giản: **một LLM có công cụ (tools) + khả năng quyết định**. Không chỉ trả lời câu hỏi, mà có thể:
- Đọc file
- Tính toán
- Gọi API
- Ghi file

Model quyết định *khi nào* gọi tool, *tool nào*, và *tham số gì* — không phải dev hard-code.

### Agentic loop

Vòng lặp:
```
1. User hỏi
2. Model think → quyết định gọi tool (hoặc trả lời trực tiếp)
3. Nếu gọi tool → framework execute tool → lấy kết quả
4. Result đưa lại model
5. Model think lại → gọi tool tiếp / trả lời cuối
6. Lặp cho đến khi model không gọi tool nữa
```

Ví dụ concrete với DeClaw:
```
User: "Đọc test.txt cho tôi"
  ↓
Model: tool_call filesystem_read({"path": "test.txt"})
  ↓
ToolNode: đọc file → "Hello DeClaw..."
  ↓
Model: "File contains: 'Hello DeClaw...'"
  ↓
(không gọi tool nữa, END)
```

**Đây là what "AI agent" thực sự nghĩa** — không phải chatbot, mà là loop có action.

---

## 3. Các quyết định thiết kế cốt lõi

### (1) **LangGraph over raw LangChain**

LangChain có `AgentExecutor` cho pattern này, nhưng:
- Opaque state — khó debug
- Retry/error handling implicit
- Không thể inject custom logic vào loop

**LangGraph** = state machine explicit:
- `AgentState` là **Pydantic BaseModel** với typed slots (messages, plan, tool_calls, audit_refs)
- Node là function `(state) -> state` — testable, mockable
- Edge là function `(state) -> next_node_name` — routing explicit
- State serializable → có thể save/restore session sau này

→ **Auditability** và **testability** đắng ký với security-first của DeClaw.

### (2) **Model injected qua `ModelCallable` interface**

`build_agent_graph(model, tools)` nhận **`model` là async callable**:
```python
ModelCallable = Callable[[Sequence[BaseMessage]], Awaitable[BaseMessage]]
```

**Không** hard-code `ChatOllama`. → Test dùng scripted fake model, production dùng real Ollama, mai mốt swap qua vLLM/llama.cpp chỉ đổi 1 layer.

Đây là **dependency injection** — pattern chuẩn cho testable systems.

### (3) **`with_tool_call_repair` composable nhưng KHÔNG bật mặc định**

Có wrapper `with_tool_call_repair(model, tools, max_retries=2)` phát hiện bad tool call và re-prompt model. Nghe hay, nhưng **probe data cho thấy nó làm accuracy TỆ hơn** trên Mistral 7B (10/15 raw vs 9/15 with repair).

→ Wrapper vẫn có (composable), nhưng **default off**. Documented với evidence trong CLAUDE.md.

Bài học: **"tính năng nghe hay" cần verify empirically, không assume**.

### (4) **KHÔNG seed system prompt vào chat** (probe-driven)

Đây là quyết định counter-intuitive nhất. Best practice thường là "seed system prompt với rules cho model". DeClaw làm ngược lại — không seed gì. Vì sao?

**Prompt-variant experiment** (2026-06-11):
- Control (không system prompt): **68%** tool-calling accuracy
- Với system prompt (dạng nào cũng vậy): **0-23%**

Bất kỳ text hướng dẫn nào — system role, user prefix, minimal, full — đều **collapse** tool-calling của Mistral 7B. Model đi vào chế độ "explain" thay vì "call tool".

→ **Cost of trade-off**: consigne "trả lời tiếng Pháp" mất, 7 principles không còn model-facing (nhưng vẫn structurally enforced).

**Sau khi swap sang Qwen2.5 3B (2026-06-28)**: Mistral-specific failure mode có thể không còn. Nhưng CLAUDE.md ghi rõ: **chưa** re-enable system prompt cho đến khi A/B probe validate trên Qwen. **Don't quietly re-enable without evidence.**

### (5) **Bilingual tool descriptions** (probe-driven)

Probe với description tiếng Anh only: FR implicit prompts = **0/5**.

→ Every tool phải có `description_en` + `description_fr`. `bind_tools()` gửi model description theo locale từ Settings.

→ FR user không bị second-class. Đây là product requirement cho target market EU.

### (6) **Context window management với soft/hard cap**

Model có context window (Mistral 7B: 32K, Qwen2.5 3B: 32K+). Long conversation → tràn. Solution 2 tầng:

- **Hard cap** (30720 = 32768 - 2048 reserve): NEVER exceed → nếu vượt, evict oldest messages
- **Soft cap** (24000): eviction target — không trim mỗi turn, chỉ khi vượt hard cap

`fit_to_window` giữ:
- Leading `SystemMessage` (nếu có)
- Most recent message
- Drop orphan `ToolMessage` (đầu tail bị mồ côi khi cắt)

**Trim là view model-facing only**. Full history vẫn ở `AgentState.messages` cho audit.

### (7) **Compaction thay vì plain drop** (DCL-015)

Thay drop oldest → thay bằng 1 SystemMessage summary note.

`with_compaction(model)` wrapper: khi vượt threshold, call model để tóm tắt turns cũ → thay bằng summary → trim.

**Default off** (compaction thêm 1 LLM call = latency cost). On chỉ khi latency budget cho phép.

---

## 4. Kiến trúc: 2 node LangGraph

```
                    START
                      │
                      ▼
                 ┌──────────┐
                 │  agent   │ ◀──────┐
                 │ (call    │        │
                 │  model)  │        │
                 └─────┬────┘        │
                       │             │
                  tool_calls?        │
                       │             │
              ┌────────┴───────┐     │
              │                │     │
             yes               no    │
              │                │     │
              ▼                ▼     │
        ┌──────────┐          END    │
        │  tools   │                 │
        │(ToolNode)│─────────────────┘
        └──────────┘
```

**agent node**: gọi injected `model(state.messages)`. Model trả:
- AIMessage với `tool_calls` → route sang `tools`
- AIMessage không có tool_calls → END

**tools node**: `ToolNode` (LangGraph built-in) execute mỗi tool call, trả ToolMessage cho mỗi call.

**Router `tools_condition`**: check `state.messages[-1].tool_calls` không rỗng → route "tools", else "END".

Đây là **classic ReAct pattern** (Reason + Act), simplified.

### `AgentState` typed slots (DCL-011)

```python
class AgentState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages]  # reducer: append
    scratchpad: str = ""
    plan: list[str] = []
    tool_calls: list[ToolCall] = []
    audit_refs: list[str] = []  # for Principle #7
```

- `messages` dùng `add_messages` reducer → append, không overwrite. Đây là LangGraph feature.
- `AnyMessage` là discriminated union → serialize/deserialize round-trip giữ nguyên subtype (HumanMessage vs AIMessage vs ToolMessage vs SystemMessage)
- `plan`, `audit_refs` chưa populate — reserve slot cho phase sau (planning, audit)

---

## 5. Bóc tách từng ticket

### DCL-010 — LangGraph basic agentic loop

**Delivered**: [declaw/brain/loop.py](../declaw/brain/loop.py) — `build_agent_graph(model, tools)`.

State ban đầu là `MessagesState` (LangGraph built-in). DCL-011 sau thay bằng `AgentState`.

Model injected — không phụ thuộc Ollama. Loop testable end-to-end với fake model.

**Stub tool** `echo` trong [declaw/brain/stub_tools.py](../declaw/brain/stub_tools.py) — real tools chờ Phase 2.

**Tests**: 2 unit tests dùng scripted fake model.

### DCL-011 — AgentState typed slots

**Delivered**: [declaw/brain/state.py](../declaw/brain/state.py) — `AgentState` Pydantic BaseModel.

Thay thế `MessagesState` placeholder. Bug fix: model reader phải `state.messages` (attribute), không `state["messages"]` (dict).

**Serialization tested**: 4 mixed messages + populated slots serialize → deserialize → equal.

### DCL-012 — Ollama function calling integration

**Delivered**: [declaw/brain/chat_model.py](../declaw/brain/chat_model.py) — `build_ollama_model(tools)`.

```python
def build_ollama_model(tools, *, model=None, base_url=None) -> ModelCallable:
    bound = ChatOllama(
        model=model or settings.model,
        base_url=base_url or settings.ollama_base_url,
    ).bind_tools(tools)

    async def call(messages):
        return await bound.ainvoke(messages)

    return call
```

`bind_tools(tools)` gửi model schema JSON của tool → model biết cách emit tool_call. Đây là **Ollama function calling API**.

**Tests**: fake `ChatOllama` tại boundary construction — no daemon. Plus 1 integration test self-skip nếu daemon không có.

### DCL-013 — Tool output parser + repair (composable, KHÔNG default)

**Delivered**: [declaw/brain/repair.py](../declaw/brain/repair.py) — `with_tool_call_repair(model, tools)`.

Detect 3 failure modes:
- `invalid_tool_calls` (args không parse JSON)
- Unknown tool name
- Args fail pydantic schema

Nếu detect → re-prompt model với corrective message. Max 2 retries.

**Probe cho thấy KHÔNG ăn** — Mistral 7B misuse thường là "closest real tool" (nhưng sai args) chứ không phải invalid_tool_calls / unknown. Repair tăng "no tool" cases.

→ Wrapper vẫn có (composable), **default off** trong `build_brain`.

**Tests**: 7 tests với scripted fake model malformed outputs.

### DCL-014 — Context window management

**Delivered**: [declaw/brain/context.py](../declaw/brain/context.py) — `fit_to_window` + `with_context_window` wrapper.

`estimate_tokens` heuristic: `ceil(chars/3) + per-message overhead`. **Over-estimate** — thà cắt sớm còn hơn tràn.

Eviction rule: giữ leading SystemMessage + most recent message. Drop orphan ToolMessage.

**Injectable `TokenCounter`**: nếu mai mốt cần chính xác, dùng tokenizer thật thay heuristic.

### DCL-015 — Compaction (composable, KHÔNG default)

**Delivered**: [declaw/brain/compaction.py](../declaw/brain/compaction.py) — upgrade DCL-014.

Thay drop oldest turns → thay bằng SystemMessage summary note.

Summariser default: LLM call với prompt "summarize concisely, preserve facts/decisions/plan, no tool calls".

**Default off**: compaction = extra LLM call = latency cost. On chỉ khi latency budget cho phép.

### DCL-016 — CLI test interface

**Delivered**: [declaw/brain/repl.py](../declaw/brain/repl.py) — `build_brain(tools)` + `run_chat(graph, read, write)`.

`build_brain` là **assembly point**: build Ollama model, wrap với context window (không repair, không compaction default), build agent graph.

`run_chat` là REPL:
- Injectable `read`/`write` I/O — testable không cần terminal
- `/exit`/`/quit` để thoát
- Blank line skip
- `--debug` in `[tool call]`/`[tool result]` lines

[declaw/main.py:87](../declaw/main.py#L87) là chat command:
- Health check Ollama trước
- Ensure workspace dir exists
- Wire registry tools + confirmation provider + sanitizer vào brain
- Chạy REPL

### DCL-017 — System prompt template (FR + EN)

**Delivered**: [declaw/brain/prompts.py](../declaw/brain/prompts.py) — locked EN/FR prompts.

**Trạng thái tricky**: prompt tồn tại **nhưng không được seed** vào `declaw chat` (probe data). Vẫn có cho:
- Composition khác không bind tools (sanitizer dùng approach tương tự)
- Nếu mai mốt A/B verify Qwen chịu được system prompt → re-enable

Prompts embed 7 Inviolable Principles + pin language "Answer in English"/"Répondez en français".

---

## 6. Probe-driven calibration — điểm đặc biệt của Phase 1

### `declaw/brain/eval.py` — reusable benchmark

Promotes probe từ ad-hoc script thành framework:
- **`PROBE_TOOLS`**: 3 toy tool (echo/add/say_hello) — đơn giản để cô lập tool-calling reliability khỏi complexity của fs tool
- **`BENCHMARK_CORPUS_V0`**: 50 frozen prompt, 8 category:
  - Direct EN/FR (8/8)
  - Implicit EN/FR (8/5)
  - No-tool EN/FR (5/5)
  - Ambiguous (5)
  - Adversarial (6) — bad-args, unknown-tool, injection...
- **Framework**: `run_prompt`, `summarize`, `per_prompt_table`

Corpus **locked** → mọi run so sánh được.

### 3 decisions từ probe

**1. Bỏ `with_tool_call_repair` khỏi default** (10/15 raw vs 9/15 with repair)

**2. Bỏ system prompt khỏi `declaw chat`** (68% raw vs 8% with system)

**3. Swap default model Mistral 7B → Qwen2.5 3B** (60.5% → 87%, p50 15s → 1.4s, FR implicit 0/5 → 5/5)

Mỗi quyết định có **evidence** ghi trong CLAUDE.md "post-Phase-1 calibration" — không phải claim, là data.

### Reproduce probe

```powershell
# Full 50-prompt corpus (~2-5 phút với GPU, ~15 phút CPU)
uv run python scripts/probe_mistral.py

# Với repair wrapper
uv run python scripts/probe_mistral.py --with-repair

# Với system prompt seed
uv run python scripts/probe_mistral.py --with-system
```

Output: summary table + per-prompt breakdown.

---

## 7. Verify chạy đúng

### Bước 1 — Unit tests

```powershell
uv run pytest tests/unit/test_loop.py tests/unit/test_state.py tests/unit/test_chat_model.py tests/unit/test_repair.py tests/unit/test_context.py tests/unit/test_compaction.py tests/unit/test_prompts.py tests/unit/test_repl.py -v
```

Mong đợi: ~30-40 tests all pass.

### Bước 2 — Live chat smoke test

```powershell
uv run declaw chat --debug
```

Test loop end-to-end:
```
you> hi
[tool call] echo({'message': 'hi'})   ← nếu build_brain default có echo stub
[tool result] hi
Brain: <response>
```

Hoặc với real fs tools (Phase 2 wired vào chat):
```
you> Use the filesystem_list tool with path '.'
[tool call] filesystem_list({'path': '.'})
[tool result] type | size | ...
Brain: <listing summary>
```

### Bước 3 — Probe

```powershell
uv run python scripts/probe_mistral.py
```

So sánh với baseline trong CLAUDE.md. Nếu accuracy tụt drastically → có regression.

---

## 8. Trade-off honest

### ⚠️ Model reliability là hard ceiling

**Không có wrapper nào fix được model kém tool calling**. Repair, compaction, prompt engineering đều không cải thiện Mistral 7B đáng kể. Model swap là **duy nhất** giải quyết được.

Bài học: **model choice > prompt engineering** cho tool-calling reliability.

### ⚠️ FR reliability lower than EN (trước Qwen swap)

Mistral 7B: FR implicit **0/5**. Sau swap sang Qwen2.5: **5/5**. Đây là **product-critical** cho target market EU.

Follow-up: bilingual tool descriptions là mandatory, chưa đủ. FR few-shot examples trong system prompt có thể improve nữa (chưa test).

### ⚠️ System prompt off = FR language pin off

Consequence documented. User FR gõ tiếng Pháp có thể nhận response tiếng Anh. Workaround: user post-process, hoặc re-enable system prompt sau khi A/B verify Qwen chịu được.

### ⚠️ Context management là view-only, không phải retention policy

`fit_to_window` chỉ cắt model-facing view. Full history stay `AgentState.messages`. Nếu app không lưu state → mất history khi restart.

Persistent conversation history sẽ ở Phase 5+ (episodic memory).

### ⚠️ Compaction chưa persist summary vào state

Mỗi lần compact tạo summary mới → duplicate work. Follow-up optimization: persist summary vào `AgentState` để reuse.

---

## 9. Checklist review

### ✅ Architecture
- [ ] `AgentState` là Pydantic BaseModel, không dict
- [ ] `messages` field dùng `add_messages` reducer (append), không overwrite
- [ ] Model injected qua `ModelCallable` protocol — không hard-code ChatOllama
- [ ] Router `tools_condition` check `tool_calls` không rỗng

### ✅ Ollama binding
- [ ] `build_ollama_model` call `bind_tools(tools)` — model biết tool schema
- [ ] Tool list wire vào brain **phải match** tool list bind vào model
- [ ] Test với fake `ChatOllama` — no daemon needed

### ✅ Wrappers
- [ ] `with_tool_call_repair` composable — không bật default
- [ ] `with_context_window` bật default trong `build_brain`
- [ ] `with_compaction` composable — không bật default (latency cost)
- [ ] Wrapper composable — order matter, documented

### ✅ REPL
- [ ] `run_chat` inject read/write I/O — testable
- [ ] `/exit` + `/quit` handle
- [ ] Blank line skip
- [ ] `--debug` in tool call/result

### ✅ Prompts
- [ ] EN + FR versions của mọi prompt
- [ ] Language switch qua Settings + `DECLAW_LANGUAGE` env
- [ ] **Không** seed system prompt vào `declaw chat` (probe-driven)

### ✅ Probe framework
- [ ] `BENCHMARK_CORPUS_V0` locked (add, không rewrite)
- [ ] Toy tools (echo/add/say_hello) đơn giản — isolate tool-calling từ tool complexity
- [ ] Baseline numbers ghi trong CLAUDE.md có evidence

### ⚠️ Red flags
- ❌ System prompt seed vào chat mà không có A/B probe evidence
- ❌ Hard-code model name thay vì `settings.model`
- ❌ Model created ở nhiều nơi thay vì 1 factory
- ❌ `state["messages"]` (dict access) thay vì `state.messages` (attribute)
- ❌ Tool list bind_tools ≠ ToolNode list → routing sai
- ❌ Probe corpus modified (không add) → invalidate historical numbers

---

## 10. Thuật ngữ

| Term | Nghĩa |
|---|---|
| **Agent** | LLM + tools + decision loop. Không chỉ chatbot, có action |
| **Agentic loop** | Think → tool-call → observe → repeat until done |
| **LangGraph** | Framework state machine cho LLM apps. Node + edge + state |
| **State machine** | Cấu trúc có states + transitions rõ ràng — testable, auditable |
| **Node** | Function `(state) -> state` trong LangGraph |
| **Edge / Router** | Function `(state) -> next_node_name` — quyết định next node |
| **Reducer** (LangGraph) | Function merge state field khi node return partial state. `add_messages` = append |
| **ModelCallable** | Async callable `messages -> AIMessage`. Interface DeClaw inject model |
| **Tool call** | LLM output request execute một tool với args cụ thể |
| **`bind_tools`** | Method của LangChain chat model — attach tool schema, model biết cách emit tool_call |
| **Context window** | Số token tối đa model xử lý được. Qwen2.5 32K, GPT-4 128K |
| **Compaction** | Nén conversation history bằng summarization thay vì drop |
| **Tokenizer** | Chuyển text → token IDs. Model có tokenizer riêng, dùng để đếm chính xác |
| **Probe / Benchmark** | Corpus locked chạy đo metric, so sánh cross-config |
| **`with_structured_output`** | LangChain feature ép model trả JSON theo schema Pydantic |
| **AnyMessage** | Discriminated union của HumanMessage/AIMessage/ToolMessage/SystemMessage. Serialize giữ nguyên subtype |
| **REPL** | Read-Eval-Print Loop — interactive shell |
| **ReAct** | Reasoning + Acting pattern — think, act, observe, repeat. LangGraph loop DeClaw là ReAct simplified |

---

## Related docs

- [phase-0-review.md](./phase-0-review.md) — Phase 0 (Foundation)
- [phase-2-review.md](./phase-2-review.md) — Phase 2 (Tool Layer)
- [phase-4-review.md](./phase-4-review.md) — Phase 4 (Sanitizer)
- [CLAUDE.md](../CLAUDE.md) — Living dev context, đặc biệt "Post-Phase 1 calibration"
- [TICKETS.md](../TICKETS.md) — DCL-010..017 với acceptance criteria

---

**Last updated**: 2026-06-28
