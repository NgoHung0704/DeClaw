# Phase 7 — Plugin Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run DeClaw plugins as isolated subprocesses that speak a size-capped JSON protocol, survive crashing, can be turned off, and expose selected capabilities to the brain as ordinary typed tools.

**Architecture:** A plugin is a directory with a `plugin.yaml` and a Python entrypoint. The host spawns it as `python -m declaw_plugin_sdk.bootstrap <dir> <entrypoint>` with a scrubbed environment, asks it `describe`, validates every capability against the signed manifest, and registers the model-facing ones as `DeclawTool` proxies. The wire format lives in the SDK package so host and plugin share one definition and cannot drift.

**Tech Stack:** Python 3.12, pydantic v2, asyncio subprocesses, NDJSON over stdio, pytest + pytest-asyncio, mypy strict, ruff.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-7-plugin-host-design.md` (read it; the roadmap `docs/superpowers/specs/2026-08-23-phase-7-9-roadmap.md` gives the surrounding context)

## Global Constraints

- Python `>=3.12`. `from __future__ import annotations` at the top of every module (repo-wide convention).
- `uv run mypy declaw` must pass under `strict = true`, and `uv run ruff check` clean, before every commit. Line length 100.
- `uv run pytest` must pass. `asyncio_mode = "auto"` is already set — do **not** add `@pytest.mark.asyncio`.
- Code and comments in English. Any user-facing string ships in EN **and** FR.
- Tests never sleep in real time and never require Ollama, Docker, or a network. Inject clocks and sleeps.
- Security-critical code is TDD: the failing test is written and *run* before the implementation.
- `MAX_FRAME_BYTES = 32 * 1024 * 1024`. `PROTOCOL_VERSION = 1`. `SDK_VERSION = 1`.
- Crash policy: backoff `1, 2, 4, 8, 16, 32, 60, 60…` seconds; **3 crashes within 300 s** → quarantine.
- Protocol-violation policy: **3 violations within one process lifetime** → kill + quarantine. Counter resets on restart.
- Timeouts: capability default `120` s, hard cap `600` s. Shutdown: `shutdown` frame → 5 s → `terminate()` → 2 s → `kill()`.
- Commit format `feat(DCL-XXX): …` / `fix(DCL-XXX): …`. Commit at the end of every task.
- `declaw_plugin_sdk` depends on **pydantic only**. It must never import `declaw`.

## File Structure

**New package — `declaw_plugin_sdk/`** (top-level, shipped in the wheel):

| File | Responsibility |
| --- | --- |
| `protocol.py` | Frame models, error codes, version constants, `MAX_FRAME_BYTES`. **Shared**: the host imports these too |
| `declaration.py` | `BasePlugin`, the `@capability` decorator, `_CapabilitySpec` |
| `_isolation.py` | The `declaw.*` import blocker |
| `runtime.py` | The synchronous dispatch loop |
| `bootstrap.py` | `python -m` entry: dup stdout, install blocker, import entrypoint, run |

**New modules — `declaw/plugin_host/`** (joins the existing `manifest.py`, `permissions.py`, `signing.py`):

| File | Responsibility |
| --- | --- |
| `ipc.py` | Host-side NDJSON encode/decode with the size cap |
| `schema.py` | JSON Schema → pydantic model, restricted subset |
| `process.py` | Spawn, scrubbed env, stderr drain, one-at-a-time request, shutdown ladder |
| `state.py` | `plugin_state.json` |
| `loader.py` | Discovery + capability validation against the manifest |
| `supervisor.py` | Backoff, crash counting, quarantine, timeouts, violation counting |
| `tools.py` | `PluginTool` proxy |
| `host.py` | `PluginHost` facade + auto-grant |
| `errors.py` | The host-side exception taxonomy |

**Modified:** `declaw/tools/registry.py` (`register_instance`), `declaw/tools/builtin/filesystem.py` + new `declaw/tools/builtin/_paths.py`, `declaw/audit/events.py`, `declaw/audit/summary.py`, `declaw/main.py`, `declaw/config.py`, `pyproject.toml`.

**Test fixtures:** `tests/fixtures/plugins/{echo-plugin,crash-plugin,hang-plugin}/`.

### Two deviations from the spec, decided while planning

1. **The protocol lives in the SDK, not in `declaw/plugin_host/protocol.py`.** The SDK cannot import `declaw`, so a host-side definition would have to be duplicated plugin-side and the two would drift. `declaw` importing `declaw_plugin_sdk` is fine — the blocker only stops the reverse.
2. **The host passes the entrypoint path as `argv[2]`.** The spec's command line was `bootstrap <plugin_dir>`, which would make the SDK parse `plugin.yaml` and therefore depend on PyYAML. The host has already parsed and validated the manifest, so it passes the result.

---

### Task 1: Promote the workspace path resolver

`_resolve_in_workspace` has four consumers in `filesystem.py`, and DCL-021 already flagged the promotion as reasonable. The fifth consumer arrives in Phase 8: the host must resolve and validate a path before handing it to a parser plugin, since the plugin opens files itself rather than receiving bytes over the pipe. Doing the move now, on its own, keeps it a pure refactor with the traversal corpus as its proof — rather than a change buried inside a feature commit.

**Files:**
- Create: `declaw/tools/builtin/_paths.py`
- Modify: `declaw/tools/builtin/filesystem.py`
- Test: `tests/unit/test_path_traversal.py` (existing — update the import only)

**Interfaces:**
- Consumes: nothing
- Produces: `declaw.tools.builtin._paths.WorkspacePathError`, `declaw.tools.builtin._paths.resolve_in_workspace(raw_path: str, workspace: Path) -> Path`

- [ ] **Step 1: Read the current implementation**

Run: `sed -n '1,90p' declaw/tools/builtin/filesystem.py`

Copy `WorkspacePathError` and `_resolve_in_workspace` **verbatim** — including the Windows `":"` guard and the NUL-byte check. This is a move, not a rewrite. Behaviour must not change by one character.

- [ ] **Step 2: Create the new module**

Create `declaw/tools/builtin/_paths.py` with the module docstring below, then paste the two moved definitions, renaming the function to drop its leading underscore (it is now public within the package):

```python
"""Workspace containment for every path DeClaw touches.

Moved out of ``filesystem.py`` when the plugin host became the fifth
consumer. The guarantee, unchanged since DCL-026 and pinned by the 36-vector
corpus in ``tests/unit/test_path_traversal.py``: every input either raises
``WorkspacePathError`` or resolves strictly inside the workspace. Nothing
leaks, on any platform.
"""
```

- [ ] **Step 3: Re-export from `filesystem.py` and delete the originals**

At the top of `declaw/tools/builtin/filesystem.py`, replace the removed definitions with:

```python
from declaw.tools.builtin._paths import WorkspacePathError, resolve_in_workspace

# Kept as a private alias so the four call sites below read unchanged.
_resolve_in_workspace = resolve_in_workspace
```

`WorkspacePathError` stays importable from `filesystem` because other modules and tests already import it from there.

- [ ] **Step 4: Run the full traversal corpus**

Run: `uv run pytest tests/unit/test_path_traversal.py tests/unit/test_tools_filesystem.py -q`
Expected: PASS, same count as before the move (75 cases on Windows). A single failure means the move was not verbatim — revert and redo it.

- [ ] **Step 5: Typecheck and commit**

```bash
uv run mypy declaw && uv run ruff check
git add declaw/tools/builtin/_paths.py declaw/tools/builtin/filesystem.py
git commit -m "refactor(DCL-092): promote workspace path resolver to _paths.py"
```

---

### Task 2: SDK package skeleton and the shared wire protocol

**Files:**
- Create: `declaw_plugin_sdk/__init__.py`, `declaw_plugin_sdk/protocol.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_plugin_protocol.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PROTOCOL_VERSION`, `SDK_VERSION`, `MAX_FRAME_BYTES`, `ErrorCode`, `RequestFrame`, `ResponseFrame`, `FrameError`, `CapabilityDescriptor`, `DescribeResult` — all from `declaw_plugin_sdk.protocol`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_protocol.py`:

```python
"""The wire contract between the host and a plugin process."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from declaw_plugin_sdk.protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    SDK_VERSION,
    CapabilityDescriptor,
    DescribeResult,
    FrameError,
    RequestFrame,
    ResponseFrame,
)


def test_request_frame_roundtrips_through_json() -> None:
    frame = RequestFrame(id="abc", method="invoke", params={"capability": "parse"})
    restored = RequestFrame.model_validate_json(frame.model_dump_json())
    assert restored == frame
    assert restored.v == PROTOCOL_VERSION


def test_request_frame_rejects_unknown_method() -> None:
    with pytest.raises(ValidationError):
        RequestFrame(id="abc", method="rm_rf")  # type: ignore[arg-type]


def test_request_frame_rejects_extra_fields() -> None:
    # extra="forbid": a plugin cannot smuggle fields past the host.
    with pytest.raises(ValidationError):
        RequestFrame.model_validate({"id": "a", "method": "describe", "sneaky": 1})


def test_success_and_error_responses() -> None:
    ok = ResponseFrame(id="a", ok=True, result={"n": 1})
    assert ok.error is None
    bad = ResponseFrame(id="a", ok=False, error=FrameError(code="invalid_args", message="no"))
    assert bad.error is not None and bad.error.code == "invalid_args"


def test_error_code_vocabulary_is_closed() -> None:
    with pytest.raises(ValidationError):
        FrameError(code="made_up", message="x")  # type: ignore[arg-type]


def test_capability_descriptor_defaults_fail_safe() -> None:
    # Forgetting a flag must hide the capability from the model and gate it.
    cap = CapabilityDescriptor(
        name="parse",
        description_en="Parse a document.",
        description_fr="Analyse un document.",
        args_schema={"type": "object", "properties": {}},
    )
    assert cap.exposed_to_model is False
    assert cap.classification == "write"
    assert cap.produces_external_content is False
    assert cap.requires == ()
    assert cap.timeout_s == 120


def test_describe_result_carries_sdk_version() -> None:
    described = DescribeResult(name="echo", version="1.0.0")
    assert described.sdk_version == SDK_VERSION
    assert described.capabilities == ()


def test_frame_cap_is_32_mib() -> None:
    assert MAX_FRAME_BYTES == 32 * 1024 * 1024
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_protocol.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw_plugin_sdk'`

- [ ] **Step 3: Create the package and the protocol module**

`declaw_plugin_sdk/__init__.py`:

```python
"""DeClaw plugin SDK — the contract a plugin process is written against.

This package is deliberately independent of ``declaw``: a plugin runs in a
subprocess where importing ``declaw.*`` is blocked, so anything a plugin needs
must live here. Its only dependency is pydantic.

The host imports this package too. That direction is fine and intentional —
one definition of the wire format means the two sides cannot drift apart.
"""

from __future__ import annotations

from declaw_plugin_sdk.protocol import PROTOCOL_VERSION, SDK_VERSION

__all__ = ["PROTOCOL_VERSION", "SDK_VERSION"]
```

`declaw_plugin_sdk/protocol.py`:

```python
"""Frames exchanged over the plugin's stdio, and the vocabulary of failures."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
SDK_VERSION = 1

# Hard ceiling on one NDJSON line, in both directions. A parsed 500-page PDF
# is a few MB of text; 32 MiB leaves headroom without letting a runaway plugin
# exhaust host memory.
MAX_FRAME_BYTES = 32 * 1024 * 1024

Method = Literal["describe", "invoke", "shutdown"]

ErrorCode = Literal[
    "unknown_method",
    "unknown_capability",
    "invalid_args",
    "capability_failed",
    "result_too_large",
    "internal",
]

Classification = Literal["read", "write", "destructive"]


class RequestFrame(BaseModel):
    """Host -> plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: int = PROTOCOL_VERSION
    id: str
    method: Method
    params: dict[str, Any] = Field(default_factory=dict)


class FrameError(BaseModel):
    """Structured failure carried by a non-ok response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    message: str


class ResponseFrame(BaseModel):
    """Plugin -> host."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: int = PROTOCOL_VERSION
    id: str
    ok: bool
    result: Any = None
    error: FrameError | None = None


class CapabilityDescriptor(BaseModel):
    """One thing a plugin can do, as announced by ``describe``.

    Every flag defaults to the cautious value: a capability the author forgot
    to annotate stays invisible to the model and gated behind confirmation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description_en: str
    description_fr: str
    # Permission values as plain strings; the SDK cannot import DeClaw's
    # PluginPermission enum. The host converts and validates them.
    requires: tuple[str, ...] = ()
    exposed_to_model: bool = False
    produces_external_content: bool = False
    classification: Classification = "write"
    timeout_s: int = 120
    args_schema: dict[str, Any]


class DescribeResult(BaseModel):
    """The plugin's answer to ``describe``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    sdk_version: int = SDK_VERSION
    capabilities: tuple[CapabilityDescriptor, ...] = ()
```

- [ ] **Step 4: Add the package to the wheel**

In `pyproject.toml`, change:

```toml
[tool.hatch.build.targets.wheel]
packages = ["declaw", "declaw_plugin_sdk"]
```

Without this the bootstrap module is absent from any installed build and every plugin dies with an unhelpful import error.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_protocol.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw_plugin_sdk/ tests/unit/test_plugin_protocol.py pyproject.toml
git commit -m "feat(DCL-093): shared wire protocol in declaw_plugin_sdk"
```

---

### Task 3: Host-side NDJSON codec

**Files:**
- Create: `declaw/plugin_host/errors.py`, `declaw/plugin_host/ipc.py`
- Test: `tests/unit/test_plugin_ipc.py`

**Interfaces:**
- Consumes: `declaw_plugin_sdk.protocol` (Task 2)
- Produces: `encode_frame(frame: BaseModel) -> bytes`, `decode_response(line: bytes) -> ResponseFrame`; exceptions `PluginHostError`, `ProtocolViolationError`, `FrameTooLargeError`, `MalformedFrameError`, `PluginCrashedError`, `PluginTimeoutError`, `PluginUnavailableError`, `PluginLoadError`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_ipc.py`:

```python
"""NDJSON framing: everything a hostile or buggy plugin can put on the wire."""

from __future__ import annotations

import json

import pytest

from declaw.plugin_host.errors import FrameTooLargeError, MalformedFrameError
from declaw.plugin_host.ipc import decode_response, encode_frame
from declaw_plugin_sdk.protocol import MAX_FRAME_BYTES, RequestFrame, ResponseFrame


def test_encoded_frame_is_one_line_of_json() -> None:
    data = encode_frame(RequestFrame(id="1", method="describe"))
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    assert json.loads(data)["method"] == "describe"


def test_embedded_newlines_do_not_break_framing() -> None:
    # The reason NDJSON is safe here: JSON escapes newlines itself.
    frame = RequestFrame(id="1", method="invoke", params={"text": "a\nb\nc"})
    data = encode_frame(frame)
    assert data.count(b"\n") == 1


def test_decode_accepts_a_valid_response() -> None:
    line = encode_frame(ResponseFrame(id="1", ok=True, result={"n": 1}))
    assert decode_response(line).result == {"n": 1}


def test_encode_refuses_to_emit_an_oversized_frame() -> None:
    with pytest.raises(FrameTooLargeError):
        encode_frame(RequestFrame(id="1", method="invoke", params={"x": "a" * MAX_FRAME_BYTES}))


def test_decode_rejects_an_oversized_line() -> None:
    with pytest.raises(FrameTooLargeError):
        decode_response(b"x" * (MAX_FRAME_BYTES + 1))


def test_decode_rejects_malformed_json() -> None:
    with pytest.raises(MalformedFrameError):
        decode_response(b"{not json\n")


def test_decode_rejects_a_json_scalar() -> None:
    with pytest.raises(MalformedFrameError):
        decode_response(b'"just a string"\n')


def test_decode_rejects_a_frame_missing_its_id() -> None:
    with pytest.raises(MalformedFrameError):
        decode_response(b'{"v": 1, "ok": true}\n')


def test_decode_rejects_a_future_protocol_version() -> None:
    with pytest.raises(MalformedFrameError) as excinfo:
        decode_response(b'{"v": 99, "id": "1", "ok": true}\n')
    assert "99" in str(excinfo.value)


def test_decode_rejects_extra_fields() -> None:
    with pytest.raises(MalformedFrameError):
        decode_response(b'{"v": 1, "id": "1", "ok": true, "extra": 1}\n')
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_ipc.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.errors'`

- [ ] **Step 3: Write the exception taxonomy**

`declaw/plugin_host/errors.py`:

```python
"""Every way the plugin host can fail, as one importable taxonomy.

Kept in its own module so `ipc`, `process`, `supervisor` and `host` can raise
each other's errors without importing each other.
"""

from __future__ import annotations


class PluginHostError(Exception):
    """Base class for every plugin-host failure."""


class PluginLoadError(PluginHostError):
    """A plugin could not be loaded. Message is user-facing."""


class ProtocolViolationError(PluginHostError):
    """The plugin broke the wire contract. Three of these kill the process."""


class FrameTooLargeError(ProtocolViolationError):
    """A frame exceeded MAX_FRAME_BYTES in either direction."""


class MalformedFrameError(ProtocolViolationError):
    """A frame was not parseable as a valid response."""


class PluginCrashedError(PluginHostError):
    """The plugin process exited while a request was in flight."""


class PluginTimeoutError(PluginHostError):
    """A capability exceeded its declared timeout; the process was restarted."""


class PluginUnavailableError(PluginHostError):
    """The plugin is disabled or quarantined, so the call cannot be made."""
```

- [ ] **Step 4: Write the codec**

`declaw/plugin_host/ipc.py`:

```python
"""Encode and decode one NDJSON frame, refusing anything oversized or malformed.

Newline-delimited JSON rather than a length prefix: JSON escapes newlines, so
one object per line is unambiguous, and a corrupted stream stays readable in a
log. The size cap is enforced on both sides — ``encode_frame`` refuses to emit
an oversized frame so we never write something the peer must reject.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from declaw.plugin_host.errors import FrameTooLargeError, MalformedFrameError
from declaw_plugin_sdk.protocol import MAX_FRAME_BYTES, PROTOCOL_VERSION, ResponseFrame


def encode_frame(frame: BaseModel) -> bytes:
    """Serialise ``frame`` as one newline-terminated JSON line."""
    data = frame.model_dump_json().encode("utf-8")
    if len(data) + 1 > MAX_FRAME_BYTES:
        raise FrameTooLargeError(
            f"Refusing to send a {len(data)} byte frame; the limit is {MAX_FRAME_BYTES}."
        )
    return data + b"\n"


def decode_response(line: bytes) -> ResponseFrame:
    """Parse one line into a :class:`ResponseFrame` or raise a violation."""
    if len(line) > MAX_FRAME_BYTES:
        raise FrameTooLargeError(
            f"Received a {len(line)} byte frame; the limit is {MAX_FRAME_BYTES}."
        )
    try:
        raw: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MalformedFrameError(f"Frame is not valid JSON: {exc}.") from exc
    if not isinstance(raw, dict):
        raise MalformedFrameError("Frame must be a JSON object.")
    version = raw.get("v")
    if version != PROTOCOL_VERSION:
        raise MalformedFrameError(
            f"Frame declares protocol version {version!r}; this host speaks {PROTOCOL_VERSION}."
        )
    try:
        return ResponseFrame.model_validate(raw)
    except ValidationError as exc:
        raise MalformedFrameError(f"Frame is not a valid response: {exc}.") from exc
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_ipc.py -q`
Expected: PASS (10 tests)

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/errors.py declaw/plugin_host/ipc.py tests/unit/test_plugin_ipc.py
git commit -m "feat(DCL-093): size-capped NDJSON codec and host error taxonomy"
```

---

### Task 4: JSON Schema to pydantic, restricted subset

The host rebuilds a pydantic model from the schema a plugin announces, so arguments are validated **host-side** and malformed input never reaches the subprocess (Principle #6).

**Files:**
- Create: `declaw/plugin_host/schema.py`
- Test: `tests/unit/test_plugin_schema.py`

**Interfaces:**
- Consumes: `PluginLoadError` (Task 3)
- Produces: `PluginSchemaError(PluginLoadError)`, `model_from_json_schema(model_name: str, schema: dict[str, Any]) -> type[BaseModel]`

**Critical detail:** pydantic renders an optional field as `{"anyOf": [{"type": "integer"}, {"type": "null"}]}`. That is the schema the SDK itself produces, so the reader must accept exactly that two-branch nullable idiom while still rejecting general `anyOf`. Miss this and every plugin with an optional argument fails to load.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_schema.py`:

```python
"""Rebuilding a pydantic model from a plugin's announced JSON Schema."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from declaw.plugin_host.schema import PluginSchemaError, model_from_json_schema


class _Args(BaseModel):
    path: str
    max_pages: int | None = None
    verbose: bool = False
    tags: list[str] = []
    mode: str = "fast"


def _rebuild(model: type[BaseModel]) -> type[BaseModel]:
    return model_from_json_schema("Rebuilt", model.model_json_schema())


def test_roundtrips_a_realistic_pydantic_model() -> None:
    # The headline case: whatever the SDK emits, the host can read back.
    rebuilt = _rebuild(_Args)
    parsed = rebuilt.model_validate({"path": "a.pdf"})
    assert parsed.model_dump()["path"] == "a.pdf"


def test_required_field_stays_required() -> None:
    rebuilt = _rebuild(_Args)
    with pytest.raises(ValidationError):
        rebuilt.model_validate({})


def test_optional_field_rendered_as_anyof_null_is_accepted() -> None:
    # pydantic writes `int | None` as anyOf[integer, null]. Rejecting that
    # would reject every plugin with an optional argument.
    rebuilt = _rebuild(_Args)
    assert rebuilt.model_validate({"path": "a", "max_pages": 3}).model_dump()["max_pages"] == 3
    assert rebuilt.model_validate({"path": "a"}).model_dump()["max_pages"] is None


def test_defaults_survive() -> None:
    rebuilt = _rebuild(_Args)
    dumped = rebuilt.model_validate({"path": "a"}).model_dump()
    assert dumped["verbose"] is False
    assert dumped["mode"] == "fast"


def test_wrong_type_is_rejected_at_the_host() -> None:
    rebuilt = _rebuild(_Args)
    with pytest.raises(ValidationError):
        rebuilt.model_validate({"path": "a", "max_pages": "not a number"})


def test_string_array_supported() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_validate({"tags": ["x"]}).model_dump()["tags"] == ["x"]


def test_string_enum_becomes_a_literal() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"mode": {"enum": ["fast", "slow"]}},
        "required": ["mode"],
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_validate({"mode": "fast"}).model_dump()["mode"] == "fast"
    with pytest.raises(ValidationError):
        rebuilt.model_validate({"mode": "sideways"})


def test_description_is_carried_into_the_field() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Where to read."}},
        "required": ["path"],
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_fields["path"].description == "Where to read."


@pytest.mark.parametrize(
    ("schema", "needle"),
    [
        ({"type": "array"}, "object"),
        (
            {"type": "object", "properties": {"nested": {"type": "object"}}},
            "nested",
        ),
        (
            {"type": "object", "properties": {"x": {"$ref": "#/$defs/Y"}}},
            "x",
        ),
        (
            {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}]}}},
            "x",
        ),
        (
            {
                "type": "object",
                "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
            },
            "x",
        ),
        (
            {"type": "object", "properties": {"x": {"type": "array", "items": {"type": "integer"}}}},
            "x",
        ),
        ({"type": "object", "properties": {"x": {"enum": [1, 2]}}}, "x"),
    ],
)
def test_unsupported_constructs_are_rejected_by_name(schema: dict[str, Any], needle: str) -> None:
    with pytest.raises(PluginSchemaError) as excinfo:
        model_from_json_schema("A", schema)
    assert needle in str(excinfo.value)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.schema'`

- [ ] **Step 3: Write the converter**

`declaw/plugin_host/schema.py`:

```python
"""Rebuild a pydantic model from the JSON Schema a plugin announces.

Only a deliberately small subset of JSON Schema is accepted: a flat object of
scalars, string arrays and string enums. The restriction is a feature twice
over. It keeps validation host-side, so malformed arguments never reach the
subprocess (Principle #6). And flat, simple tool signatures are what a 3B model
actually calls correctly — the Phase 1 probes are unambiguous about that.

The one non-obvious accommodation is ``anyOf: [T, null]``. That is how pydantic
renders ``T | None``, so it is exactly what the SDK emits for an optional
argument; rejecting it would reject every plugin with an optional parameter.
General ``anyOf`` stays refused.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from declaw.plugin_host.errors import PluginLoadError

_SCALARS: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

_FORBIDDEN_KEYS = ("$ref", "oneOf", "allOf", "not", "patternProperties")


class PluginSchemaError(PluginLoadError):
    """A plugin's argument schema uses something this host does not support."""


def _unwrap_nullable(prop: str, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Turn ``anyOf: [T, null]`` into ``(T, True)``; leave anything else alone."""
    branches = spec.get("anyOf")
    if branches is None:
        return spec, False
    if not isinstance(branches, list) or len(branches) != 2:
        raise PluginSchemaError(
            f"property {prop!r}: only 'anyOf: [type, null]' is supported, not general anyOf"
        )
    nulls = [b for b in branches if isinstance(b, dict) and b.get("type") == "null"]
    others = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    if len(nulls) != 1 or len(others) != 1:
        raise PluginSchemaError(
            f"property {prop!r}: only 'anyOf: [type, null]' is supported, not general anyOf"
        )
    merged = dict(others[0])
    for carried in ("description", "default"):
        if carried in spec:
            merged.setdefault(carried, spec[carried])
    return merged, True


def _annotation_for(prop: str, spec: dict[str, Any]) -> Any:
    for key in _FORBIDDEN_KEYS:
        if key in spec:
            raise PluginSchemaError(f"property {prop!r}: {key!r} is not supported")
    if "enum" in spec:
        values = spec["enum"]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise PluginSchemaError(f"property {prop!r}: only string enums are supported")
        return Literal[tuple(values)]
    declared = spec.get("type")
    if declared in _SCALARS:
        return _SCALARS[declared]
    if declared == "array":
        items = spec.get("items")
        if not isinstance(items, dict) or items.get("type") != "string":
            raise PluginSchemaError(f"property {prop!r}: only arrays of string are supported")
        return list[str]
    raise PluginSchemaError(f"property {prop!r}: unsupported type {declared!r}")


def model_from_json_schema(model_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a pydantic model from ``schema`` or raise :class:`PluginSchemaError`."""
    if schema.get("type") != "object":
        raise PluginSchemaError("an argument schema must be a JSON Schema object")
    for key in _FORBIDDEN_KEYS:
        if key in schema:
            raise PluginSchemaError(f"top-level {key!r} is not supported")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise PluginSchemaError("'properties' must be a mapping")
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for prop, raw_spec in properties.items():
        if not isinstance(raw_spec, dict):
            raise PluginSchemaError(f"property {prop!r}: definition must be a mapping")
        spec, nullable = _unwrap_nullable(prop, raw_spec)
        annotation = _annotation_for(prop, spec)
        description = spec.get("description")
        if prop in required and not nullable:
            fields[prop] = (annotation, Field(..., description=description))
        else:
            if nullable:
                annotation = annotation | None
            fields[prop] = (annotation, Field(spec.get("default"), description=description))

    # create_model's kwargs are untyped by construction; the field tuples above
    # are the (annotation, FieldInfo) pairs it expects.
    return create_model(model_name, **fields)  # type: ignore[call-overload, no-any-return]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_schema.py -q`
Expected: PASS (8 tests + 7 parametrised rejections)

If `test_roundtrips_a_realistic_pydantic_model` fails, print `_Args.model_json_schema()` and compare against the branches above — pydantic's exact rendering is the thing this module has to match.

- [ ] **Step 5: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/schema.py tests/unit/test_plugin_schema.py
git commit -m "feat(DCL-093): rebuild pydantic args models from plugin JSON Schema"
```

---

### Task 5: SDK capability declaration

**Files:**
- Create: `declaw_plugin_sdk/declaration.py`
- Test: `tests/unit/test_plugin_declaration.py`

**Interfaces:**
- Consumes: `declaw_plugin_sdk.protocol` (Task 2)
- Produces: `BasePlugin`, `capability(...)` decorator, `CapabilitySpec`, `CapabilityDeclarationError`, `CAPABILITY_ATTR`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_declaration.py`:

```python
"""Declaring what a plugin can do, and what the host is told about it."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from declaw_plugin_sdk.declaration import (
    BasePlugin,
    CapabilityDeclarationError,
    capability,
)


class EchoArgs(BaseModel):
    message: str
    times: int = 1


class Sample(BasePlugin):
    name = "sample"
    version = "1.2.3"

    @capability(
        name="echo",
        description_en="Repeat a message.",
        description_fr="Repete un message.",
        exposed_to_model=True,
        classification="read",
    )
    async def echo(self, args: EchoArgs) -> str:
        return args.message * args.times

    @capability(
        name="hidden",
        description_en="Infrastructure only.",
        description_fr="Infrastructure uniquement.",
        requires=["filesystem.read"],
        produces_external_content=True,
        timeout_s=300,
    )
    async def hidden(self, args: EchoArgs) -> str:
        return "x"


def test_capabilities_are_discovered_by_name() -> None:
    assert set(Sample().capabilities()) == {"echo", "hidden"}


def test_describe_reports_identity_and_every_capability() -> None:
    described = Sample().describe()
    assert described.name == "sample"
    assert described.version == "1.2.3"
    assert {c.name for c in described.capabilities} == {"echo", "hidden"}


def test_describe_carries_the_declared_flags() -> None:
    by_name = {c.name: c for c in Sample().describe().capabilities}
    assert by_name["echo"].exposed_to_model is True
    assert by_name["echo"].classification == "read"
    assert by_name["hidden"].requires == ("filesystem.read",)
    assert by_name["hidden"].produces_external_content is True
    assert by_name["hidden"].timeout_s == 300


def test_undeclared_flags_default_to_the_safe_value() -> None:
    hidden = {c.name: c for c in Sample().describe().capabilities}["hidden"]
    assert hidden.exposed_to_model is False
    assert hidden.classification == "write"


def test_describe_embeds_the_args_json_schema() -> None:
    echo = {c.name: c for c in Sample().describe().capabilities}["echo"]
    assert echo.args_schema["properties"]["message"]["type"] == "string"
    assert echo.args_schema["required"] == ["message"]


def test_a_synchronous_capability_is_refused() -> None:
    with pytest.raises(CapabilityDeclarationError) as excinfo:

        class Bad(BasePlugin):
            @capability(name="s", description_en="a", description_fr="a")
            def sync_one(self, args: EchoArgs) -> str:  # not async
                return "x"

    assert "async" in str(excinfo.value)


def test_a_capability_without_a_pydantic_args_parameter_is_refused() -> None:
    with pytest.raises(CapabilityDeclarationError) as excinfo:

        class Bad(BasePlugin):
            @capability(name="s", description_en="a", description_fr="a")
            async def untyped(self, args: dict) -> str:  # type: ignore[type-arg]
                return "x"

    assert "args" in str(excinfo.value)


def test_duplicate_capability_names_are_refused() -> None:
    class Clashing(BasePlugin):
        name = "clash"

        @capability(name="same", description_en="a", description_fr="a")
        async def first(self, args: EchoArgs) -> str:
            return "1"

        @capability(name="same", description_en="b", description_fr="b")
        async def second(self, args: EchoArgs) -> str:
            return "2"

    with pytest.raises(CapabilityDeclarationError):
        Clashing().capabilities()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_declaration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw_plugin_sdk.declaration'`

- [ ] **Step 3: Write the declaration module**

`declaw_plugin_sdk/declaration.py`:

```python
"""How a plugin author says what their plugin can do.

A capability is an ``async def`` taking one parameter named ``args``, annotated
with a pydantic model. That model is the contract: its JSON Schema travels to
the host, which rebuilds it and validates every call before the plugin is even
asked. The author never parses raw input.

Every flag on the decorator defaults to the cautious value. Forgetting
``exposed_to_model=True`` hides a capability from the model; forgetting
``classification="read"`` puts it behind the confirmation gate. Mistakes make
the system quieter and stricter, never louder and looser.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import BaseModel

from declaw_plugin_sdk.protocol import (
    SDK_VERSION,
    CapabilityDescriptor,
    Classification,
    DescribeResult,
)

CAPABILITY_ATTR = "__declaw_capability__"


class CapabilityDeclarationError(TypeError):
    """A capability was declared in a way the SDK cannot honour."""


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Everything the runtime needs to dispatch one capability."""

    name: str
    description_en: str
    description_fr: str
    requires: tuple[str, ...]
    exposed_to_model: bool
    produces_external_content: bool
    classification: Classification
    timeout_s: int
    args_model: type[BaseModel]
    func: Callable[..., Awaitable[Any]]

    def descriptor(self) -> CapabilityDescriptor:
        """Render the wire-facing announcement of this capability."""
        return CapabilityDescriptor(
            name=self.name,
            description_en=self.description_en,
            description_fr=self.description_fr,
            requires=self.requires,
            exposed_to_model=self.exposed_to_model,
            produces_external_content=self.produces_external_content,
            classification=self.classification,
            timeout_s=self.timeout_s,
            args_schema=self.args_model.model_json_schema(),
        )


def capability(
    *,
    name: str,
    description_en: str,
    description_fr: str,
    requires: tuple[str, ...] | list[str] = (),
    exposed_to_model: bool = False,
    produces_external_content: bool = False,
    classification: Classification = "write",
    timeout_s: int = 120,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Mark an async method as a capability the host may invoke."""

    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(func):
            raise CapabilityDeclarationError(
                f"capability {name!r} must be declared with 'async def'"
            )
        hints = get_type_hints(func)
        args_model = hints.get("args")
        if not (isinstance(args_model, type) and issubclass(args_model, BaseModel)):
            raise CapabilityDeclarationError(
                f"capability {name!r} must take a parameter named 'args' "
                "annotated with a pydantic BaseModel subclass"
            )
        setattr(
            func,
            CAPABILITY_ATTR,
            CapabilitySpec(
                name=name,
                description_en=description_en,
                description_fr=description_fr,
                requires=tuple(requires),
                exposed_to_model=exposed_to_model,
                produces_external_content=produces_external_content,
                classification=classification,
                timeout_s=timeout_s,
                args_model=args_model,
                func=func,
            ),
        )
        return func

    return decorate


class BasePlugin:
    """Base class every plugin subclasses exactly once."""

    name: str = ""
    version: str = "0.0.0"

    def capabilities(self) -> dict[str, CapabilitySpec]:
        """Collect the decorated methods, keyed by capability name."""
        found: dict[str, CapabilitySpec] = {}
        for attribute in dir(type(self)):
            spec = getattr(getattr(type(self), attribute, None), CAPABILITY_ATTR, None)
            if not isinstance(spec, CapabilitySpec):
                continue
            if spec.name in found:
                raise CapabilityDeclarationError(
                    f"capability name {spec.name!r} is declared twice on {type(self).__name__}"
                )
            found[spec.name] = spec
        return found

    def describe(self) -> DescribeResult:
        """Answer the host's ``describe`` request."""
        return DescribeResult(
            name=self.name,
            version=self.version,
            sdk_version=SDK_VERSION,
            capabilities=tuple(spec.descriptor() for spec in self.capabilities().values()),
        )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_declaration.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw_plugin_sdk/declaration.py tests/unit/test_plugin_declaration.py
git commit -m "feat(DCL-094): SDK capability declaration with fail-safe defaults"
```

---

### Task 6: SDK runtime, isolation, bootstrap, and the echo fixture

**Files:**
- Create: `declaw_plugin_sdk/_isolation.py`, `declaw_plugin_sdk/runtime.py`, `declaw_plugin_sdk/bootstrap.py`
- Create: `tests/fixtures/plugins/echo-plugin/plugin.yaml`, `tests/fixtures/plugins/echo-plugin/main.py`
- Test: `tests/unit/test_plugin_runtime.py`

**Interfaces:**
- Consumes: `CapabilitySpec`, `BasePlugin` (Task 5); `RequestFrame`, `ResponseFrame`, `FrameError`, `MAX_FRAME_BYTES` (Task 2)
- Produces: `DeclawImportBlocker`, `install_import_blocker()`, `handle_line(plugin, specs, line) -> tuple[ResponseFrame | None, bool]`, `run(plugin, *, read_line=None, write_frame=None)`, `bootstrap.main(argv=None)`

**Why the loop is synchronous:** on Windows the Proactor event loop cannot
`connect_read_pipe` to stdin, so an asyncio stdio loop in the child does not
work. One request is in flight at a time anyway, so a blocking read loop with
`asyncio.run()` per request is both simpler and portable. Capabilities stay
`async def`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_runtime.py`:

```python
"""The plugin-side dispatch loop, driven without a real subprocess."""

from __future__ import annotations

import json

from pydantic import BaseModel

from declaw_plugin_sdk._isolation import DeclawImportBlocker
from declaw_plugin_sdk.declaration import BasePlugin, capability
from declaw_plugin_sdk.protocol import MAX_FRAME_BYTES, RequestFrame
from declaw_plugin_sdk.runtime import run


class Args(BaseModel):
    message: str = "hi"


class Sample(BasePlugin):
    name = "sample"
    version = "1.0.0"

    @capability(name="echo", description_en="Echo.", description_fr="Echo.")
    async def echo(self, args: Args) -> str:
        return args.message

    @capability(name="boom", description_en="Fail.", description_fr="Echoue.")
    async def boom(self, args: Args) -> str:
        raise RuntimeError("exploded on purpose")

    @capability(name="huge", description_en="Too big.", description_fr="Trop gros.")
    async def huge(self, args: Args) -> str:
        return "a" * (MAX_FRAME_BYTES + 1)


def _drive(*lines: bytes) -> list[dict[str, object]]:
    """Feed lines to run() and collect the frames it writes back."""
    inbox = list(lines) + [b""]
    written: list[dict[str, object]] = []

    def read_line() -> bytes:
        return inbox.pop(0)

    def write_frame(data: bytes) -> None:
        assert data.endswith(b"\n")
        written.append(json.loads(data))

    run(Sample(), read_line=read_line, write_frame=write_frame)
    return written


def _request(method: str, **params: object) -> bytes:
    return RequestFrame(id="r1", method=method, params=params).model_dump_json().encode() + b"\n"


def test_describe_returns_the_plugin_identity() -> None:
    (frame,) = _drive(_request("describe"))
    assert frame["ok"] is True
    assert frame["result"]["name"] == "sample"  # type: ignore[index]


def test_invoke_runs_the_capability() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={"message": "bonjour"}))
    assert frame["ok"] is True
    assert frame["result"] == "bonjour"


def test_invoke_uses_declared_defaults() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={}))
    assert frame["result"] == "hi"


def test_unknown_capability_is_reported_not_crashed() -> None:
    (frame,) = _drive(_request("invoke", capability="nope", args={}))
    assert frame["error"]["code"] == "unknown_capability"  # type: ignore[index]


def test_invalid_args_are_rejected_before_the_capability_runs() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={"message": 42}))
    assert frame["error"]["code"] == "invalid_args"  # type: ignore[index]


def test_a_raising_capability_becomes_an_error_frame() -> None:
    (frame,) = _drive(_request("invoke", capability="boom", args={}))
    assert frame["error"]["code"] == "capability_failed"  # type: ignore[index]
    assert "exploded on purpose" in frame["error"]["message"]  # type: ignore[index]


def test_oversized_result_is_refused_rather_than_written() -> None:
    (frame,) = _drive(_request("invoke", capability="huge", args={}))
    assert frame["error"]["code"] == "result_too_large"  # type: ignore[index]


def test_unknown_method_is_reported() -> None:
    (frame,) = _drive(b'{"v": 1, "id": "r1", "method": "describe", "params": {}}\n'.replace(
        b"describe", b"destroy"
    ))
    assert frame["error"]["code"] == "unknown_method"  # type: ignore[index]


def test_unparseable_line_produces_an_error_frame() -> None:
    (frame,) = _drive(b"{not json\n")
    assert frame["ok"] is False


def test_shutdown_stops_the_loop() -> None:
    frames = _drive(_request("shutdown"), _request("describe"))
    assert len(frames) == 1  # the describe after shutdown is never read


def test_blank_lines_are_skipped() -> None:
    frames = _drive(b"\n", _request("describe"))
    assert len(frames) == 1


def test_import_blocker_rejects_declaw_and_its_submodules() -> None:
    blocker = DeclawImportBlocker()
    for name in ("declaw", "declaw.config", "declaw.credentials.store"):
        try:
            blocker.find_spec(name)
        except ImportError:
            continue
        raise AssertionError(f"{name} should have been blocked")


def test_import_blocker_does_not_block_the_sdk_itself() -> None:
    # 'declaw_plugin_sdk' starts with 'declaw' — a naive prefix check would
    # block the SDK the plugin is written against.
    assert DeclawImportBlocker().find_spec("declaw_plugin_sdk") is None
    assert DeclawImportBlocker().find_spec("declawful") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_runtime.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw_plugin_sdk._isolation'`

- [ ] **Step 3: Write the import blocker**

`declaw_plugin_sdk/_isolation.py`:

```python
"""Block ``declaw.*`` imports inside a plugin process.

This is an ARCHITECTURAL boundary, not a security control, and the difference
matters. ``declaw`` lives in the same virtualenv, so it is importable no matter
what PYTHONPATH says, and plugin code could remove this hook from
``sys.meta_path`` in one line. What the hook buys is that a plugin author
cannot accidentally couple to core internals: the failure is immediate and the
message says what to do instead.

Real containment of hostile plugin code needs OS-level sandboxing.
"""

from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Sequence


class DeclawImportBlocker:
    """A ``sys.meta_path`` finder that refuses the core package."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        # Exact match or a real submodule. 'declaw_plugin_sdk' must pass.
        if fullname == "declaw" or fullname.startswith("declaw."):
            raise ImportError(
                f"Plugins may not import {fullname!r}. A plugin talks to DeClaw only "
                "over the IPC protocol; everything you need is in declaw_plugin_sdk."
            )
        return None


def install_import_blocker() -> None:
    """Install the blocker ahead of every other finder."""
    sys.meta_path.insert(0, DeclawImportBlocker())  # type: ignore[arg-type]
```

- [ ] **Step 4: Write the dispatch loop**

`declaw_plugin_sdk/runtime.py`:

```python
"""The plugin-side loop: read one frame, answer it, repeat.

Synchronous on purpose. Windows' Proactor event loop cannot attach asyncio
stream readers to stdin, and only one request is ever in flight, so a blocking
read with ``asyncio.run()`` per request is both simpler and portable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from declaw_plugin_sdk.declaration import BasePlugin, CapabilitySpec
from declaw_plugin_sdk.protocol import (
    MAX_FRAME_BYTES,
    FrameError,
    RequestFrame,
    ResponseFrame,
)

ReadLine = Callable[[], bytes]
WriteFrame = Callable[[bytes], None]


def _error(request_id: str, code: Any, message: str) -> ResponseFrame:
    return ResponseFrame(id=request_id, ok=False, error=FrameError(code=code, message=message))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _invoke(plugin: BasePlugin, specs: dict[str, CapabilitySpec], frame: RequestFrame) -> ResponseFrame:
    name = frame.params.get("capability")
    spec = specs.get(name) if isinstance(name, str) else None
    if spec is None:
        return _error(frame.id, "unknown_capability", f"No capability named {name!r}.")
    raw_args = frame.params.get("args", {})
    if not isinstance(raw_args, dict):
        return _error(frame.id, "invalid_args", "'args' must be an object.")
    try:
        args = spec.args_model.model_validate(raw_args)
    except ValidationError as exc:
        return _error(frame.id, "invalid_args", str(exc))
    try:
        result = asyncio.run(spec.func(plugin, args))
    except Exception as exc:  # noqa: BLE001 - any failure becomes an error frame
        detail = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc(), file=sys.stderr)
        return _error(frame.id, "capability_failed", detail)
    return ResponseFrame(id=frame.id, ok=True, result=_jsonable(result))


def handle_line(
    plugin: BasePlugin, specs: dict[str, CapabilitySpec], line: bytes
) -> tuple[ResponseFrame | None, bool]:
    """Turn one input line into (response, should_stop)."""
    try:
        raw = json.loads(line)
        frame = RequestFrame.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        return _error("", "internal", f"Unreadable request frame: {exc}."), False

    if frame.method == "describe":
        return ResponseFrame(id=frame.id, ok=True, result=plugin.describe().model_dump(mode="json")), False
    if frame.method == "shutdown":
        return ResponseFrame(id=frame.id, ok=True, result=None), True
    if frame.method == "invoke":
        return _invoke(plugin, specs, frame), False
    return _error(frame.id, "unknown_method", f"Unknown method {frame.method!r}."), False


def _encode(frame: ResponseFrame) -> bytes:
    data = frame.model_dump_json().encode("utf-8")
    if len(data) + 1 > MAX_FRAME_BYTES:
        replacement = _error(
            frame.id,
            "result_too_large",
            f"Result would be {len(data)} bytes; the frame limit is {MAX_FRAME_BYTES}.",
        )
        data = replacement.model_dump_json().encode("utf-8")
    return data + b"\n"


def _write_all(fd: int, data: bytes) -> None:
    """os.write may write partially; a 32 MiB frame must not be truncated."""
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def run(
    plugin: BasePlugin,
    *,
    read_line: ReadLine | None = None,
    write_frame: WriteFrame | None = None,
) -> None:
    """Serve requests until stdin closes or a shutdown frame arrives."""
    reader: ReadLine = read_line or sys.stdin.buffer.readline
    writer: WriteFrame = write_frame or (lambda data: _write_all(1, data))
    specs = plugin.capabilities()
    while True:
        line = reader()
        if not line:
            return
        if not line.strip():
            continue
        response, stop = handle_line(plugin, specs, line)
        if response is not None:
            writer(_encode(response))
        if stop:
            return
```

- [ ] **Step 5: Write the bootstrap entry**

`declaw_plugin_sdk/bootstrap.py`:

```python
"""``python -m declaw_plugin_sdk.bootstrap <plugin_dir> <entrypoint>``.

Order matters here. The real stdout is duplicated away and fd 1 is pointed at
stderr *before* any plugin code runs, so a stray ``print()`` in the plugin
cannot corrupt the protocol stream. The import blocker goes in next, before the
entrypoint is imported, so it covers the plugin's own imports.

The host passes the entrypoint path rather than letting this module read
``plugin.yaml``: the host has already parsed and validated the manifest, and
keeping YAML out of here keeps the SDK's dependencies to pydantic alone.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from declaw_plugin_sdk._isolation import install_import_blocker
from declaw_plugin_sdk.declaration import BasePlugin
from declaw_plugin_sdk.runtime import _write_all, run


def _load_plugin_class(plugin_dir: Path, entrypoint: str) -> type[BasePlugin]:
    module_path = plugin_dir / entrypoint
    spec = importlib.util.spec_from_file_location(f"declaw_plugin_{plugin_dir.name}", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot import plugin entrypoint {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    found = [
        value
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, BasePlugin) and value is not BasePlugin
    ]
    if len(found) != 1:
        raise SystemExit(
            f"{module_path} must define exactly one BasePlugin subclass, found {len(found)}."
        )
    return found[0]


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: python -m declaw_plugin_sdk.bootstrap <plugin_dir> <entrypoint>")
    plugin_dir = Path(args[0]).resolve()

    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    install_import_blocker()
    sys.path.insert(0, str(plugin_dir))

    plugin = _load_plugin_class(plugin_dir, args[1])()
    run(plugin, write_frame=lambda data: _write_all(protocol_fd, data))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Create the echo fixture**

`tests/fixtures/plugins/echo-plugin/plugin.yaml`:

```yaml
manifest_version: 1
name: echo-plugin
version: 1.0.0
description_en: Test plugin that echoes messages back.
description_fr: Plugin de test qui renvoie les messages.
entrypoint: main.py
author: DeClaw test suite
permissions:
  requested:
    - filesystem.read
  denied:
    - network
```

`tests/fixtures/plugins/echo-plugin/main.py`:

```python
"""Echo plugin — the reference plugin the host integration tests drive."""

from __future__ import annotations

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class EchoArgs(BaseModel):
    message: str
    times: int = 1


class CountArgs(BaseModel):
    values: list[str]


class EchoPlugin(BasePlugin):
    name = "echo-plugin"
    version = "1.0.0"

    @capability(
        name="echo",
        description_en="Repeat a message back.",
        description_fr="Renvoie un message.",
        exposed_to_model=True,
        classification="read",
    )
    async def echo(self, args: EchoArgs) -> str:
        return " ".join([args.message] * args.times)

    @capability(
        name="count",
        description_en="Count the values given.",
        description_fr="Compte les valeurs fournies.",
        requires=["filesystem.read"],
    )
    async def count(self, args: CountArgs) -> dict[str, int]:
        return {"count": len(args.values)}

    @capability(
        name="noisy",
        description_en="Print to stdout, then answer.",
        description_fr="Ecrit sur stdout, puis repond.",
        exposed_to_model=True,
        classification="read",
    )
    async def noisy(self, args: EchoArgs) -> str:
        # Proves stdout hygiene: this must not corrupt the protocol stream.
        print("stray print that must not reach the host as a frame")
        return args.message
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_runtime.py -q`
Expected: PASS (13 tests)

- [ ] **Step 8: Drive the plugin by hand once**

This is the milestone worth seeing with your own eyes — the plugin works before
any host exists:

```bash
echo '{"v":1,"id":"1","method":"describe","params":{}}' | uv run python -m declaw_plugin_sdk.bootstrap tests/fixtures/plugins/echo-plugin main.py
```

Expected: one JSON line on stdout whose `result.name` is `echo-plugin`.

- [ ] **Step 9: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw_plugin_sdk/ tests/unit/test_plugin_runtime.py tests/fixtures/plugins/echo-plugin/
git commit -m "feat(DCL-094): SDK runtime, import blocker, bootstrap, echo fixture"
```

---

### Task 7: The plugin process

**Files:**
- Create: `declaw/plugin_host/process.py`
- Modify: `declaw/plugin_host/errors.py` (add `PluginCapabilityError`)
- Test: `tests/unit/test_plugin_env.py`, `tests/integration/test_plugin_process.py`

**Interfaces:**
- Consumes: `encode_frame`, `decode_response` (Task 3); the error taxonomy (Task 3); `RequestFrame`, `MAX_FRAME_BYTES` (Task 2); the echo fixture (Task 6)
- Produces: `build_plugin_env(plugin_name: str) -> dict[str, str]`, `PluginProcess(name, plugin_dir, entrypoint, python=None)` with `start()`, `request(method, params=None, *, timeout) -> Any`, `shutdown()`, `kill()`, property `running`

- [ ] **Step 1: Write the failing environment test**

Create `tests/unit/test_plugin_env.py`:

```python
"""The spawned environment is built from scratch, never inherited."""

from __future__ import annotations

import pytest

from declaw.plugin_host.process import build_plugin_env


def test_no_declaw_setting_leaks_into_the_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("DECLAW_DATA_DIR", "/secret")
    env = build_plugin_env("echo-plugin")
    leaked = [k for k in env if k.startswith("DECLAW_") and k != "DECLAW_PLUGIN_NAME"]
    assert leaked == []


def test_no_ollama_variable_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert [k for k in build_plugin_env("p") if k.startswith("OLLAMA")] == []


def test_arbitrary_user_variables_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    assert "AWS_SECRET_ACCESS_KEY" not in build_plugin_env("p")


def test_the_plugin_is_told_its_own_name() -> None:
    assert build_plugin_env("echo-plugin")["DECLAW_PLUGIN_NAME"] == "echo-plugin"


def test_python_needs_these_to_run_at_all() -> None:
    env = build_plugin_env("p")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert "PATH" in env
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_plugin_process.py`:

```python
"""A real subprocess, a real pipe. Deterministic: no Ollama, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.errors import PluginCapabilityError, PluginTimeoutError
from declaw.plugin_host.process import PluginProcess

ECHO_DIR = Path(__file__).parent.parent / "fixtures" / "plugins" / "echo-plugin"


async def _started(directory: Path = ECHO_DIR) -> PluginProcess:
    process = PluginProcess(name=directory.name, plugin_dir=directory, entrypoint="main.py")
    await process.start()
    return process


async def test_describe_round_trips_through_a_real_pipe() -> None:
    process = await _started()
    try:
        described = await process.request("describe", timeout=30)
        assert described["name"] == "echo-plugin"
        assert {c["name"] for c in described["capabilities"]} == {"echo", "count", "noisy"}
    finally:
        await process.shutdown()


async def test_invoke_returns_the_capability_result() -> None:
    process = await _started()
    try:
        result = await process.request(
            "invoke", {"capability": "echo", "args": {"message": "salut", "times": 2}}, timeout=30
        )
        assert result == "salut salut"
    finally:
        await process.shutdown()


async def test_a_stray_print_does_not_corrupt_the_stream() -> None:
    # 'noisy' prints to stdout before answering. If stdout hygiene were broken
    # the next frame read would be the print output, not JSON.
    process = await _started()
    try:
        assert await process.request(
            "invoke", {"capability": "noisy", "args": {"message": "ok"}}, timeout=30
        ) == "ok"
        assert await process.request("describe", timeout=30)["name"] == "echo-plugin"
    finally:
        await process.shutdown()


async def test_an_error_frame_becomes_a_typed_exception() -> None:
    process = await _started()
    try:
        with pytest.raises(PluginCapabilityError) as excinfo:
            await process.request("invoke", {"capability": "nope", "args": {}}, timeout=30)
        assert excinfo.value.code == "unknown_capability"
    finally:
        await process.shutdown()


async def test_timeout_raises_rather_than_hanging() -> None:
    process = await _started()
    try:
        # 'describe' answers instantly; a zero timeout is the deterministic way
        # to exercise the timeout path without a sleeping fixture.
        with pytest.raises(PluginTimeoutError):
            await process.request("describe", timeout=0.0)
    finally:
        await process.kill()


async def test_shutdown_stops_the_process() -> None:
    process = await _started()
    await process.shutdown()
    assert process.running is False
```

- [ ] **Step 3: Run both and watch them fail**

Run: `uv run pytest tests/unit/test_plugin_env.py tests/integration/test_plugin_process.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.process'`

- [ ] **Step 4: Add the capability error**

Append to `declaw/plugin_host/errors.py`:

```python
class PluginCapabilityError(PluginHostError):
    """The plugin answered a request with a structured error frame."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")
```

- [ ] **Step 5: Write the process wrapper**

`declaw/plugin_host/process.py`:

```python
"""One plugin subprocess: spawn it, talk to it, stop it.

Three details here are load-bearing and easy to get wrong:

* the environment is BUILT, not filtered — a filter forgets a variable, a
  build cannot;
* stderr is drained by a background task for the whole process lifetime,
  because an undrained pipe fills its OS buffer and blocks the plugin
  mid-write, which is indistinguishable from a hang;
* ``limit=MAX_FRAME_BYTES`` on the stream reader means an oversized line
  raises instead of buffering without bound.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from declaw.log import logger
from declaw.plugin_host.errors import (
    FrameTooLargeError,
    PluginCapabilityError,
    PluginCrashedError,
    PluginHostError,
    PluginTimeoutError,
    ProtocolViolationError,
)
from declaw.plugin_host.ipc import decode_response, encode_frame
from declaw_plugin_sdk.protocol import MAX_FRAME_BYTES, RequestFrame, ResponseFrame

BOOTSTRAP_MODULE = "declaw_plugin_sdk.bootstrap"

# Variables a Python subprocess genuinely needs. Everything else is withheld.
_PASSTHROUGH = ("SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME")


def build_plugin_env(plugin_name: str) -> dict[str, str]:
    """Build the plugin's environment from scratch (Principle: no inheritance)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "DECLAW_PLUGIN_NAME": plugin_name,
    }
    for name in _PASSTHROUGH:
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


class PluginProcess:
    """A live plugin subprocess with one request in flight at a time."""

    def __init__(
        self,
        *,
        name: str,
        plugin_dir: Path,
        entrypoint: str,
        python: str | None = None,
    ) -> None:
        self._name = name
        self._plugin_dir = plugin_dir
        self._entrypoint = entrypoint
        self._python = python or sys.executable
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            BOOTSTRAP_MODULE,
            str(self._plugin_dir),
            self._entrypoint,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._plugin_dir),
            env=build_plugin_env(self._name),
            limit=MAX_FRAME_BYTES,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            logger.bind(plugin=self._name).debug(line.decode("utf-8", "replace").rstrip())

    async def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any:
        """Send one request and return its result, or raise a typed error."""
        async with self._lock:
            proc = self._proc
            if proc is None or proc.stdin is None or proc.returncode is not None:
                raise PluginCrashedError(f"Plugin {self._name!r} is not running.")
            frame = RequestFrame(id=str(uuid.uuid4()), method=method, params=params or {})
            try:
                proc.stdin.write(encode_frame(frame))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise PluginCrashedError(f"Plugin {self._name!r} closed its input.") from exc
            try:
                response = await asyncio.wait_for(self._read_matching(frame.id), timeout)
            except TimeoutError as exc:
                raise PluginTimeoutError(
                    f"Plugin {self._name!r} did not answer {method!r} within {timeout}s."
                ) from exc
            if not response.ok:
                error = response.error
                raise PluginCapabilityError(
                    error.code if error else "internal",
                    error.message if error else "plugin reported failure with no detail",
                )
            return response.result

    async def _read_matching(self, request_id: str) -> ResponseFrame:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise PluginCrashedError(f"Plugin {self._name!r} is not running.")
        try:
            line = await proc.stdout.readline()
        except ValueError as exc:
            # StreamReader raises ValueError when a line exceeds its limit.
            raise FrameTooLargeError(
                f"Plugin {self._name!r} sent a frame over {MAX_FRAME_BYTES} bytes."
            ) from exc
        if not line:
            raise PluginCrashedError(f"Plugin {self._name!r} exited mid-request.")
        response = decode_response(line)
        if response.id != request_id:
            raise ProtocolViolationError(
                f"Plugin {self._name!r} sent a frame for id {response.id!r}, expected {request_id!r}."
            )
        return response

    async def shutdown(self) -> None:
        """Graceful, then firm, then final: frame -> 5s -> terminate -> 2s -> kill."""
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None and proc.stdin is not None:
            try:
                proc.stdin.write(
                    encode_frame(RequestFrame(id=str(uuid.uuid4()), method="shutdown"))
                )
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, PluginHostError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5.0)
            except TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 2.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        await self._cleanup()

    async def kill(self) -> None:
        """Stop immediately, for the timeout and violation paths."""
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None
```

- [ ] **Step 6: Run both suites**

Run: `uv run pytest tests/unit/test_plugin_env.py tests/integration/test_plugin_process.py -q`
Expected: PASS (5 unit + 6 integration)

If the integration tests hang, the cause is almost always the stderr drain: comment out `_drain_stderr` and watch them hang harder, which confirms the diagnosis, then restore it.

- [ ] **Step 7: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/process.py declaw/plugin_host/errors.py tests/unit/test_plugin_env.py tests/integration/test_plugin_process.py
git commit -m "feat(DCL-092): isolated plugin subprocess with scrubbed env and stderr drain"
```

---

### Task 8: Persisted plugin state

**Files:**
- Create: `declaw/plugin_host/state.py`
- Test: `tests/unit/test_plugin_state.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PluginRecord` (frozen dataclass: `enabled`, `quarantined`, `quarantine_reason`, `last_version`, `auto_granted`), `PluginStateStore(path)` with `record(name)`, `all()`, `set_enabled(name, enabled)`, `quarantine(name, reason)`, `clear_quarantine(name)`, `note_version(name, version)`, `note_auto_grant(name, permission)`, `has_auto_granted(name, permission)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_state.py`:

```python
"""Plugin enable/disable/quarantine, persisted as readable JSON."""

from __future__ import annotations

import json
from pathlib import Path

from declaw.plugin_host.state import PluginStateStore


def test_an_unknown_plugin_defaults_to_enabled(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "plugin_state.json")
    record = store.record("echo-plugin")
    assert record.enabled is True
    assert record.quarantined is False


def test_disable_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "plugin_state.json"
    PluginStateStore(path).set_enabled("echo-plugin", False)
    assert PluginStateStore(path).record("echo-plugin").enabled is False


def test_quarantine_records_its_reason_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "plugin_state.json"
    PluginStateStore(path).quarantine("echo-plugin", "crashed 3 times in 5 minutes")
    reloaded = PluginStateStore(path).record("echo-plugin")
    assert reloaded.quarantined is True
    assert "3 times" in reloaded.quarantine_reason


def test_clearing_quarantine_also_clears_the_reason(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "s.json")
    store.quarantine("p", "boom")
    store.clear_quarantine("p")
    assert store.record("p").quarantined is False
    assert store.record("p").quarantine_reason == ""


def test_auto_grant_is_remembered_so_a_revoke_sticks(tmp_path: Path) -> None:
    # The point of this field: a permission auto-granted once is never
    # auto-granted again, so revoking it is permanent.
    path = tmp_path / "s.json"
    store = PluginStateStore(path)
    assert store.has_auto_granted("p", "filesystem.read") is False
    store.note_auto_grant("p", "filesystem.read")
    assert PluginStateStore(path).has_auto_granted("p", "filesystem.read") is True


def test_the_file_is_readable_json_a_human_can_diff(tmp_path: Path) -> None:
    # Transparency is the reason this is not SQLite.
    path = tmp_path / "s.json"
    store = PluginStateStore(path)
    store.set_enabled("echo-plugin", False)
    store.note_version("echo-plugin", "1.0.0")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["echo-plugin"]["enabled"] is False
    assert raw["echo-plugin"]["last_version"] == "1.0.0"


def test_all_returns_every_known_plugin(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "s.json")
    store.set_enabled("a", False)
    store.quarantine("b", "x")
    assert set(store.all()) == {"a", "b"}


def test_a_corrupt_state_file_does_not_break_startup(tmp_path: Path) -> None:
    # Losing enable/disable preferences is annoying; refusing to start is worse.
    path = tmp_path / "s.json"
    path.write_text("{ not json", encoding="utf-8")
    assert PluginStateStore(path).record("p").enabled is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.state'`

- [ ] **Step 3: Write the store**

`declaw/plugin_host/state.py`:

```python
"""Which plugins are on, off, or quarantined — as plain JSON.

Deliberately not SQLite, and deliberately next to ``plugin_grants.json``. This
file is the user's own policy, so being able to open it, read it and diff it is
a transparency feature rather than an implementation detail. Four fields per
plugin do not justify a second database with its own migration chain.

Crash counters are NOT here. A restart gives a misbehaving plugin a fresh
chance; if it still misbehaves it is re-quarantined within a minute. Quarantine
itself does persist, because clearing it should be a deliberate act.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from declaw.log import logger

STATE_FILENAME = "plugin_state.json"


@dataclass(frozen=True, slots=True)
class PluginRecord:
    """Everything remembered about one plugin between runs."""

    enabled: bool = True
    quarantined: bool = False
    quarantine_reason: str = ""
    last_version: str = ""
    # Permissions auto-granted at least once. Presence here means "never
    # auto-grant again", which is what makes a user's revoke permanent.
    auto_granted: tuple[str, ...] = ()


class PluginStateStore:
    """Load, mutate and persist :class:`PluginRecord`s."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: dict[str, PluginRecord] = {}
        if path.is_file():
            self._records = self._load(path)

    @staticmethod
    def _load(path: Path) -> dict[str, PluginRecord]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Ignoring unreadable {path}: {exc}. Plugin state resets to defaults.")
            return {}
        if not isinstance(raw, dict):
            logger.warning(f"Ignoring {path}: top level is not an object.")
            return {}
        records: dict[str, PluginRecord] = {}
        for name, values in raw.items():
            if not isinstance(values, dict):
                continue
            records[name] = PluginRecord(
                enabled=bool(values.get("enabled", True)),
                quarantined=bool(values.get("quarantined", False)),
                quarantine_reason=str(values.get("quarantine_reason", "")),
                last_version=str(values.get("last_version", "")),
                auto_granted=tuple(str(p) for p in values.get("auto_granted", [])),
            )
        return records

    def record(self, name: str) -> PluginRecord:
        return self._records.get(name, PluginRecord())

    def all(self) -> dict[str, PluginRecord]:
        return dict(self._records)

    def _update(self, name: str, **changes: Any) -> None:
        self._records[name] = replace(self.record(name), **changes)
        self._save()

    def set_enabled(self, name: str, enabled: bool) -> None:
        self._update(name, enabled=enabled)

    def quarantine(self, name: str, reason: str) -> None:
        self._update(name, quarantined=True, quarantine_reason=reason)

    def clear_quarantine(self, name: str) -> None:
        self._update(name, quarantined=False, quarantine_reason="")

    def note_version(self, name: str, version: str) -> None:
        self._update(name, last_version=version)

    def note_auto_grant(self, name: str, permission: str) -> None:
        current = self.record(name).auto_granted
        if permission not in current:
            self._update(name, auto_granted=(*current, permission))

    def has_auto_granted(self, name: str, permission: str) -> bool:
        return permission in self.record(name).auto_granted

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            name: {
                "enabled": record.enabled,
                "quarantined": record.quarantined,
                "quarantine_reason": record.quarantine_reason,
                "last_version": record.last_version,
                "auto_granted": sorted(record.auto_granted),
            }
            for name, record in sorted(self._records.items())
        }
        # Write-then-replace so a crash mid-write cannot leave a truncated file.
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._path)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_state.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/state.py tests/unit/test_plugin_state.py
git commit -m "feat(DCL-095): persist plugin enable/disable/quarantine as plain JSON"
```

---

### Task 9: Plugin lifecycle audit event

**Files:**
- Modify: `declaw/audit/events.py`, `declaw/audit/summary.py`
- Test: `tests/unit/test_audit_events.py`, `tests/unit/test_audit_summary.py` (both existing — add cases)

**Interfaces:**
- Consumes: `_BaseAuditEvent`, `AnyAuditEvent` (existing)
- Produces: `PluginLifecycleEvent` with `event_type="plugin.lifecycle"`, fields `plugin: str`, `version: str = ""`, `action: Literal[...]`, `detail: str = ""`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_audit_events.py`:

```python
def test_plugin_lifecycle_event_round_trips_through_a_db_row() -> None:
    from declaw.audit.events import PluginLifecycleEvent, event_from_row, to_db_row

    event = PluginLifecycleEvent(
        plugin="echo-plugin", version="1.0.0", action="quarantined", detail="3 crashes in 5 min"
    )
    restored = event_from_row(to_db_row(event))
    assert restored == event


def test_plugin_lifecycle_action_vocabulary_is_closed() -> None:
    import pytest
    from pydantic import ValidationError

    from declaw.audit.events import PluginLifecycleEvent

    with pytest.raises(ValidationError):
        PluginLifecycleEvent(plugin="p", action="exploded")  # type: ignore[arg-type]
```

Append to `tests/unit/test_audit_summary.py`:

```python
def test_quarantined_plugin_appears_in_the_english_summary() -> None:
    from declaw.audit.events import PluginLifecycleEvent
    from declaw.audit.summary import summarize_events

    text = summarize_events(
        [PluginLifecycleEvent(plugin="echo-plugin", action="quarantined", detail="3 crashes")],
        "en",
    )
    assert "echo-plugin" in text
    assert "quarantin" in text.lower()


def test_quarantined_plugin_appears_in_the_french_summary() -> None:
    from declaw.audit.events import PluginLifecycleEvent
    from declaw.audit.summary import summarize_events

    text = summarize_events([PluginLifecycleEvent(plugin="echo-plugin", action="disabled")], "fr")
    assert "echo-plugin" in text
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_audit_events.py tests/unit/test_audit_summary.py -q`
Expected: FAIL — `ImportError: cannot import name 'PluginLifecycleEvent'`

- [ ] **Step 3: Add the event**

In `declaw/audit/events.py`, after `PluginPermissionEvent`:

```python
class PluginLifecycleEvent(_BaseAuditEvent):
    """A plugin process changed state (DCL-091 / DCL-096 / DCL-097).

    ``load_failed`` covers a manifest or capability set the host refused;
    ``quarantined`` is the terminal state after repeated crashes or protocol
    violations. Both are user-visible: a plugin that silently stopped working
    would be worse than one that says why.
    """

    event_type: Literal["plugin.lifecycle"] = "plugin.lifecycle"
    plugin: str
    version: str = ""
    action: Literal[
        "started",
        "stopped",
        "crashed",
        "restarted",
        "quarantined",
        "enabled",
        "disabled",
        "load_failed",
    ]
    detail: str = ""
```

Add `| PluginLifecycleEvent` to the `AnyAuditEvent` union.

- [ ] **Step 4: Add the summary templates**

In `declaw/audit/summary.py`, add to each language block in `_L`:

```python
# English
"plugin_lifecycle": "Plugin {plugin}: {action}.{detail}",
# French
"plugin_lifecycle": "Extension {plugin} : {action}.{detail}",
```

Add the bilingual action words next to `_TOOL_TEMPLATES`:

```python
_PLUGIN_ACTIONS = {
    "en": {
        "started": "started",
        "stopped": "stopped",
        "crashed": "crashed",
        "restarted": "restarted",
        "quarantined": "quarantined after repeated failures",
        "enabled": "enabled",
        "disabled": "disabled",
        "load_failed": "could not be loaded",
    },
    "fr": {
        "started": "demarree",
        "stopped": "arretee",
        "crashed": "a plante",
        "restarted": "redemarree",
        "quarantined": "mise en quarantaine apres des echecs repetes",
        "enabled": "activee",
        "disabled": "desactivee",
        "load_failed": "n'a pas pu etre chargee",
    },
}
```

In `summarize_events`, add a branch alongside the existing ones:

```python
        elif isinstance(event, PluginLifecycleEvent):
            detail = f" {event.detail}" if event.detail else ""
            lines.append(
                "- "
                + strings["plugin_lifecycle"].format(
                    plugin=event.plugin,
                    action=_PLUGIN_ACTIONS[language][event.action],
                    detail=detail,
                )
            )
```

Import `PluginLifecycleEvent` at the top of the module.

- [ ] **Step 5: Run the full audit suite**

Run: `uv run pytest tests/unit/test_audit_events.py tests/unit/test_audit_summary.py tests/unit/test_audit_export.py -q`
Expected: PASS. The export test matters too: JSON/Markdown/PDF export walks the union, so a new member that breaks it shows up here.

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/audit/events.py declaw/audit/summary.py tests/unit/test_audit_events.py tests/unit/test_audit_summary.py
git commit -m "feat(DCL-096): PluginLifecycleEvent with bilingual summary lines"
```

---

### Task 10: Discovery and capability validation

**Files:**
- Create: `declaw/plugin_host/loader.py`
- Modify: `declaw/config.py` (add `builtin_plugins_dir`), `.env.example`
- Test: `tests/unit/test_plugin_loader.py`

**Interfaces:**
- Consumes: `PluginManifest`, `PluginPermission`, `load_manifest`, `ManifestError` (existing `manifest.py`); `model_from_json_schema`, `PluginSchemaError` (Task 4); `DescribeResult`, `CapabilityDescriptor`, `SDK_VERSION` (Task 2); `PluginLoadError` (Task 3)
- Produces: `DiscoveredPlugin(directory, manifest)`, `DiscoveryFailure(directory, reason)`, `ValidatedCapability(descriptor, permissions, args_model)`, `builtin_plugins_dir(settings) -> Path`, `discover(search_dir) -> tuple[list[DiscoveredPlugin], list[DiscoveryFailure]]`, `validate_described(manifest, described) -> tuple[ValidatedCapability, ...]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_loader.py`:

```python
"""Discovery, and the gate every capability must pass before it can run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.loader import discover, validate_described
from declaw.plugin_host.manifest import parse_manifest
from declaw.plugin_host.schema import PluginSchemaError
from declaw_plugin_sdk.protocol import CapabilityDescriptor, DescribeResult

_MANIFEST = {
    "manifest_version": 1,
    "name": "echo-plugin",
    "version": "1.0.0",
    "description_en": "Echo.",
    "description_fr": "Echo.",
    "entrypoint": "main.py",
    "permissions": {"requested": ["filesystem.read"], "denied": ["network"]},
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}


def _cap(**overrides: Any) -> CapabilityDescriptor:
    base: dict[str, Any] = {
        "name": "echo",
        "description_en": "Echo.",
        "description_fr": "Echo.",
        "args_schema": _SCHEMA,
    }
    return CapabilityDescriptor(**{**base, **overrides})


def _described(*capabilities: CapabilityDescriptor, **overrides: Any) -> DescribeResult:
    base: dict[str, Any] = {"name": "echo-plugin", "version": "1.0.0"}
    return DescribeResult(**{**base, **overrides}, capabilities=capabilities)


def test_a_clean_capability_validates() -> None:
    manifest = parse_manifest(_MANIFEST)
    (validated,) = validate_described(manifest, _described(_cap()))
    assert validated.descriptor.name == "echo"
    assert validated.args_model.model_validate({"message": "hi"})


def test_requested_permission_is_converted_to_the_enum() -> None:
    from declaw.plugin_host.manifest import PluginPermission

    manifest = parse_manifest(_MANIFEST)
    (validated,) = validate_described(manifest, _described(_cap(requires=["filesystem.read"])))
    assert validated.permissions == (PluginPermission.FILESYSTEM_READ,)


def test_a_capability_requiring_an_unrequested_permission_refuses_the_whole_plugin() -> None:
    # This is where DCL-097's "permission violation" actually lives: load time.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(requires=["network"])))
    assert "network" in str(excinfo.value)


def test_an_unknown_permission_string_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError):
        validate_described(manifest, _described(_cap(requires=["filesystem.obliterate"])))


def test_a_capability_name_that_is_not_a_slug_is_refused() -> None:
    # The name becomes a tool name sent to the model; Ollama restricts these.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(name="Echo It!")))
    assert "Echo It!" in str(excinfo.value)


def test_duplicate_capability_names_are_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError):
        validate_described(manifest, _described(_cap(), _cap()))


def test_a_name_mismatch_between_manifest_and_describe_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(), name="something-else"))
    assert "something-else" in str(excinfo.value)


def test_a_future_sdk_version_is_refused_with_a_readable_message() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(), sdk_version=99))
    assert "99" in str(excinfo.value)


def test_an_unsupported_args_schema_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    bad = {"type": "object", "properties": {"nested": {"type": "object"}}}
    with pytest.raises(PluginSchemaError):
        validate_described(manifest, _described(_cap(args_schema=bad)))


def test_model_facing_write_capability_with_external_content_is_refused() -> None:
    # The registry sanitizes READ external-content tools and confirms non-READ
    # ones, but never composes both — so this shape would reach the model
    # unsanitized. Refuse it rather than leave the hole open.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(
            manifest,
            _described(
                _cap(
                    exposed_to_model=True,
                    classification="write",
                    produces_external_content=True,
                )
            ),
        )
    assert "sanitiz" in str(excinfo.value).lower()


def test_the_same_shape_is_fine_when_it_is_not_exposed_to_the_model() -> None:
    manifest = parse_manifest(_MANIFEST)
    validated = validate_described(
        manifest,
        _described(_cap(classification="write", produces_external_content=True)),
    )
    assert len(validated) == 1


def test_discover_finds_a_plugin_directory(tmp_path: Path) -> None:
    directory = tmp_path / "echo-plugin"
    directory.mkdir()
    (directory / "plugin.yaml").write_text(
        "manifest_version: 1\nname: echo-plugin\nversion: 1.0.0\n"
        "description_en: Echo.\ndescription_fr: Echo.\nentrypoint: main.py\n",
        encoding="utf-8",
    )
    found, failures = discover(tmp_path)
    assert [p.manifest.name for p in found] == ["echo-plugin"]
    assert failures == []


def test_one_broken_manifest_does_not_stop_the_others(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    (good / "plugin.yaml").write_text(
        "manifest_version: 1\nname: good\nversion: 1.0.0\n"
        "description_en: G.\ndescription_fr: G.\nentrypoint: main.py\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "plugin.yaml").write_text("name: 'MISSING EVERYTHING'\n", encoding="utf-8")

    found, failures = discover(tmp_path)
    assert [p.manifest.name for p in found] == ["good"]
    assert len(failures) == 1 and failures[0].directory == bad


def test_a_missing_directory_is_empty_not_fatal(tmp_path: Path) -> None:
    found, failures = discover(tmp_path / "does-not-exist")
    assert found == [] and failures == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_loader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.loader'`

- [ ] **Step 3: Add the settings knob**

In `declaw/config.py`, under the Paths block:

```python
    builtin_plugins_dir: Path | None = Field(
        default=None,
        description=(
            "Where the shipped plugins live. Defaults to <repo>/plugins/builtin in a "
            "development checkout and to a directory beside the executable when packaged."
        ),
    )
```

Add it to the existing `_expand_user` validator's field list. Document it in `.env.example`:

```
# Where the shipped plugins live. Leave unset unless you are packaging DeClaw.
# DECLAW_BUILTIN_PLUGINS_DIR=
```

- [ ] **Step 4: Write the loader**

`declaw/plugin_host/loader.py`:

```python
"""Find plugins, and decide whether each one is allowed to run.

Discovery is deliberately narrow in v0.1: only ``plugins/builtin`` is scanned.
Scanning a user directory would be a third-party install path by file copy,
with no signature check — exactly what the phase decision excluded.

``validate_described`` is the gate. A plugin that fails ANY check does not
start at all, rather than starting and failing later in a way the user has to
interpret. Every message names the offending capability.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

import declaw
from declaw.config import Settings
from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.manifest import (
    MANIFEST_FILENAME,
    ManifestError,
    PluginManifest,
    PluginPermission,
    load_manifest,
)
from declaw.plugin_host.schema import model_from_json_schema
from declaw_plugin_sdk.protocol import SDK_VERSION, CapabilityDescriptor, DescribeResult

# A capability name becomes a tool name the model sees, and Ollama's
# function-calling schema restricts what may appear there.
CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,50}$")


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    directory: Path
    manifest: PluginManifest


@dataclass(frozen=True, slots=True)
class DiscoveryFailure:
    directory: Path
    reason: str


@dataclass(frozen=True, slots=True)
class ValidatedCapability:
    descriptor: CapabilityDescriptor
    permissions: tuple[PluginPermission, ...]
    args_model: type[BaseModel]


def builtin_plugins_dir(settings: Settings) -> Path:
    """Resolve where the shipped plugins live, checkout or packaged."""
    if settings.builtin_plugins_dir is not None:
        return settings.builtin_plugins_dir
    candidates = [
        # Development checkout: plugins/ is a sibling of the declaw package.
        Path(declaw.__file__).resolve().parent.parent / "plugins" / "builtin",
        # Packaged app: shipped beside the executable.
        Path(sys.executable).resolve().parent / "plugins" / "builtin",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def discover(search_dir: Path) -> tuple[list[DiscoveredPlugin], list[DiscoveryFailure]]:
    """Scan ``search_dir`` for plugin directories. A broken one is skipped, not fatal."""
    if not search_dir.is_dir():
        return [], []
    found: list[DiscoveredPlugin] = []
    failures: list[DiscoveryFailure] = []
    for entry in sorted(search_dir.iterdir()):
        if not entry.is_dir() or not (entry / MANIFEST_FILENAME).is_file():
            continue
        try:
            found.append(DiscoveredPlugin(directory=entry, manifest=load_manifest(entry)))
        except ManifestError as exc:
            failures.append(DiscoveryFailure(directory=entry, reason=str(exc)))
    return found, failures


def validate_described(
    manifest: PluginManifest, described: DescribeResult
) -> tuple[ValidatedCapability, ...]:
    """Check a plugin's announced capabilities against its signed manifest."""
    if described.sdk_version != SDK_VERSION:
        raise PluginLoadError(
            f"Plugin {manifest.name!r} speaks SDK version {described.sdk_version}; "
            f"this DeClaw understands {SDK_VERSION}."
        )
    if described.name != manifest.name:
        raise PluginLoadError(
            f"Plugin in {manifest.name!r}'s directory identifies itself as "
            f"{described.name!r}; the manifest and the code disagree."
        )

    requested = set(manifest.permissions.requested)
    validated: list[ValidatedCapability] = []
    seen: set[str] = set()

    for descriptor in described.capabilities:
        name = descriptor.name
        if not CAPABILITY_NAME_RE.match(name):
            raise PluginLoadError(
                f"Plugin {manifest.name!r}: capability name {name!r} must be a lowercase slug."
            )
        if name in seen:
            raise PluginLoadError(
                f"Plugin {manifest.name!r} declares capability {name!r} more than once."
            )
        seen.add(name)

        permissions: list[PluginPermission] = []
        for raw in descriptor.requires:
            try:
                permission = PluginPermission(raw)
            except ValueError as exc:
                raise PluginLoadError(
                    f"Plugin {manifest.name!r}, capability {name!r}: "
                    f"{raw!r} is not a permission DeClaw knows."
                ) from exc
            if permission not in requested:
                raise PluginLoadError(
                    f"Plugin {manifest.name!r}, capability {name!r} requires "
                    f"{permission.value!r}, which its manifest never requested."
                )
            permissions.append(permission)

        if (
            descriptor.exposed_to_model
            and descriptor.produces_external_content
            and descriptor.classification != "read"
        ):
            raise PluginLoadError(
                f"Plugin {manifest.name!r}, capability {name!r}: a model-facing capability "
                "that returns external content must be classified 'read', otherwise the "
                "registry would confirm it without sanitizing it."
            )

        validated.append(
            ValidatedCapability(
                descriptor=descriptor,
                permissions=tuple(permissions),
                args_model=model_from_json_schema(f"{manifest.name}_{name}_Args", descriptor.args_schema),
            )
        )
    return tuple(validated)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_loader.py tests/unit/test_config.py -q`
Expected: PASS (14 loader tests, plus the existing config suite still green)

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/loader.py declaw/config.py .env.example tests/unit/test_plugin_loader.py
git commit -m "feat(DCL-090): plugin discovery and load-time capability validation"
```

---

### Task 11: Supervision — backoff, crashes, quarantine, violations

**Files:**
- Create: `declaw/plugin_host/supervisor.py`
- Create: `tests/fixtures/plugins/crash-plugin/{plugin.yaml,main.py}`, `tests/fixtures/plugins/hang-plugin/{plugin.yaml,main.py}`
- Test: `tests/unit/test_plugin_supervisor.py`, `tests/integration/test_plugin_supervision.py`

**Interfaces:**
- Consumes: `PluginProcess` (Task 7), the error taxonomy (Tasks 3 and 7)
- Produces: `SupervisedProcess` protocol, `PluginSupervisor(name, factory, on_quarantine, clock=…, sleep=…)` with `start()`, `call(method, params, *, timeout)`, `stop()`, properties `quarantined`, `restarts`; constants `CRASH_LIMIT = 3`, `CRASH_WINDOW_S = 300.0`, `VIOLATION_LIMIT = 3`, `BACKOFF_SECONDS`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_plugin_supervisor.py`:

```python
"""Restart policy, driven by a fake process and an injected clock.

No test here sleeps: `sleep` records the durations it was asked for.
"""

from __future__ import annotations

from typing import Any

import pytest

from declaw.plugin_host.errors import (
    PluginCrashedError,
    PluginTimeoutError,
    PluginUnavailableError,
    ProtocolViolationError,
)
from declaw.plugin_host.supervisor import CRASH_LIMIT, PluginSupervisor


class FakeProcess:
    """A process whose next answer the test chooses."""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.started = 0
        self.killed = 0
        self.stopped = 0

    @property
    def running(self) -> bool:
        return self.started > self.stopped + self.killed

    async def start(self) -> None:
        self.started += 1

    async def request(self, method: str, params: Any = None, *, timeout: float) -> Any:
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def shutdown(self) -> None:
        self.stopped += 1

    async def kill(self) -> None:
        self.killed += 1


class Harness:
    def __init__(self, script: list[Any]) -> None:
        self.processes: list[FakeProcess] = []
        self.script = script
        self.slept: list[float] = []
        self.now = 0.0
        self.quarantines: list[str] = []

    def factory(self) -> FakeProcess:
        process = FakeProcess(self.script)
        self.processes.append(process)
        return process

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def supervisor(self) -> PluginSupervisor:
        return PluginSupervisor(
            name="echo-plugin",
            factory=self.factory,  # type: ignore[arg-type]
            on_quarantine=lambda reason: self.quarantines.append(reason),
            clock=self.clock,
            sleep=self.sleep,
        )


async def test_a_healthy_call_just_returns() -> None:
    harness = Harness(["pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_a_crash_restarts_the_process_and_still_raises() -> None:
    harness = Harness([PluginCrashedError("died"), "pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    with pytest.raises(PluginCrashedError):
        await supervisor.call("invoke", {}, timeout=1.0)
    assert len(harness.processes) == 2  # a replacement was spawned
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_backoff_grows_then_caps_at_sixty_seconds() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(20)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(8):
        with pytest.raises((PluginCrashedError, PluginUnavailableError)):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert harness.slept[:3] == [1.0, 2.0, 4.0]
    assert max(harness.slept) <= 60.0


async def test_three_crashes_inside_the_window_quarantine_the_plugin() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert supervisor.quarantined is True
    assert harness.quarantines and "crash" in harness.quarantines[0].lower()


async def test_a_quarantined_plugin_refuses_further_calls() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
    with pytest.raises(PluginUnavailableError):
        await supervisor.call("invoke", {}, timeout=1.0)


async def test_crashes_spread_beyond_the_window_do_not_quarantine() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
        harness.now += 400.0  # push each crash outside the 300s window
    assert supervisor.quarantined is False


async def test_a_timeout_kills_and_restarts() -> None:
    harness = Harness([PluginTimeoutError("slow"), "pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    with pytest.raises(PluginTimeoutError):
        await supervisor.call("invoke", {}, timeout=1.0)
    assert harness.processes[0].killed == 1
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_three_protocol_violations_quarantine_the_plugin() -> None:
    harness = Harness([ProtocolViolationError("garbage") for _ in range(3)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(3):
        with pytest.raises(ProtocolViolationError):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert supervisor.quarantined is True
    assert "protocol" in harness.quarantines[0].lower()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_supervisor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.supervisor'`

- [ ] **Step 3: Write the supervisor**

`declaw/plugin_host/supervisor.py`:

```python
"""Keep one plugin alive, and know when to stop trying.

Two independent counters, because they mean different things. A *crash* is the
plugin dying; three inside five minutes means it cannot run here, so it is
quarantined. A *protocol violation* is the plugin lying on the wire; three in
one process lifetime means it is not speaking our language, so it is
quarantined too. Neither counter persists — a restart of DeClaw gives a plugin
a fresh chance, and re-quarantine takes under a minute if nothing changed.

``clock`` and ``sleep`` are injected so the tests exercise the whole policy
without spending real seconds on it.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from declaw.log import logger
from declaw.plugin_host.errors import (
    PluginCrashedError,
    PluginTimeoutError,
    PluginUnavailableError,
    ProtocolViolationError,
)

CRASH_LIMIT = 3
CRASH_WINDOW_S = 300.0
VIOLATION_LIMIT = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)


class SupervisedProcess(Protocol):
    """The slice of :class:`PluginProcess` the supervisor depends on."""

    @property
    def running(self) -> bool: ...

    async def start(self) -> None: ...

    async def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any: ...

    async def shutdown(self) -> None: ...

    async def kill(self) -> None: ...


ProcessFactory = Callable[[], SupervisedProcess]
QuarantineCallback = Callable[[str], None]


class PluginSupervisor:
    """One plugin's process, restarted on failure until it earns quarantine."""

    def __init__(
        self,
        *,
        name: str,
        factory: ProcessFactory,
        on_quarantine: QuarantineCallback,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._name = name
        self._factory = factory
        self._on_quarantine = on_quarantine
        self._clock = clock
        self._sleep = sleep
        self._process: SupervisedProcess | None = None
        self._crashes: deque[float] = deque()
        self._violations = 0
        self._restarts = 0
        self._quarantined = False

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    @property
    def restarts(self) -> int:
        return self._restarts

    async def start(self) -> None:
        self._process = self._factory()
        await self._process.start()

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any:
        """Make one request, applying the restart policy to whatever goes wrong."""
        if self._quarantined:
            raise PluginUnavailableError(
                f"Plugin {self._name!r} is quarantined and will not be called."
            )
        process = self._process
        if process is None:
            raise PluginUnavailableError(f"Plugin {self._name!r} was never started.")
        try:
            return await process.request(method, params, timeout=timeout)
        except ProtocolViolationError:
            await self._on_violation(process)
            raise
        except PluginTimeoutError:
            await process.kill()
            await self._restart()
            raise
        except PluginCrashedError:
            await self._on_crash()
            raise

    async def _on_violation(self, process: SupervisedProcess) -> None:
        self._violations += 1
        await process.kill()
        if self._violations >= VIOLATION_LIMIT:
            self._quarantine(
                f"{self._violations} protocol violations in one process lifetime"
            )
            return
        await self._restart()

    async def _on_crash(self) -> None:
        now = self._clock()
        self._crashes.append(now)
        while self._crashes and now - self._crashes[0] > CRASH_WINDOW_S:
            self._crashes.popleft()
        if len(self._crashes) >= CRASH_LIMIT:
            self._quarantine(
                f"{len(self._crashes)} crashes within {int(CRASH_WINDOW_S)} seconds"
            )
            return
        await self._restart()

    async def _restart(self) -> None:
        delay = BACKOFF_SECONDS[min(self._restarts, len(BACKOFF_SECONDS) - 1)]
        logger.warning(f"Restarting plugin {self._name!r} in {delay}s.")
        await self._sleep(delay)
        self._restarts += 1
        self._violations = 0
        self._process = self._factory()
        await self._process.start()

    def _quarantine(self, reason: str) -> None:
        self._quarantined = True
        self._process = None
        logger.error(f"Quarantining plugin {self._name!r}: {reason}.")
        self._on_quarantine(reason)

    async def stop(self) -> None:
        if self._process is not None:
            await self._process.shutdown()
            self._process = None
```

- [ ] **Step 4: Run the unit tests**

Run: `uv run pytest tests/unit/test_plugin_supervisor.py -q`
Expected: PASS (8 tests, all in well under a second — if any test takes seconds, `sleep` was not injected properly)

- [ ] **Step 5: Create the crash and hang fixtures**

`tests/fixtures/plugins/crash-plugin/plugin.yaml`:

```yaml
manifest_version: 1
name: crash-plugin
version: 1.0.0
description_en: Test plugin that exits mid-request.
description_fr: Plugin de test qui se termine en pleine requete.
entrypoint: main.py
```

`tests/fixtures/plugins/crash-plugin/main.py`:

```python
"""Exits hard while a request is in flight, to exercise crash handling."""

from __future__ import annotations

import os

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class CrashPlugin(BasePlugin):
    name = "crash-plugin"
    version = "1.0.0"

    @capability(name="die", description_en="Exit hard.", description_fr="Se termine.")
    async def die(self, args: NoArgs) -> str:
        # os._exit skips cleanup, which is exactly the ugly death being tested.
        os._exit(1)
```

`tests/fixtures/plugins/hang-plugin/plugin.yaml`:

```yaml
manifest_version: 1
name: hang-plugin
version: 1.0.0
description_en: Test plugin that never answers.
description_fr: Plugin de test qui ne repond jamais.
entrypoint: main.py
```

`tests/fixtures/plugins/hang-plugin/main.py`:

```python
"""Never answers, to exercise the timeout path."""

from __future__ import annotations

import time

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class HangPlugin(BasePlugin):
    name = "hang-plugin"
    version = "1.0.0"

    @capability(name="wait", description_en="Never answer.", description_fr="Ne repond jamais.")
    async def wait(self, args: NoArgs) -> str:
        time.sleep(3600)
        return "unreachable"
```

- [ ] **Step 6: Write the integration test**

Create `tests/integration/test_plugin_supervision.py`:

```python
"""Crash and hang against real subprocesses, with backoff collapsed to zero."""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.errors import PluginCrashedError, PluginTimeoutError
from declaw.plugin_host.process import PluginProcess
from declaw.plugin_host.supervisor import PluginSupervisor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


def _supervisor(directory: Path, quarantines: list[str]) -> PluginSupervisor:
    async def no_sleep(_seconds: float) -> None:
        return None

    return PluginSupervisor(
        name=directory.name,
        factory=lambda: PluginProcess(
            name=directory.name, plugin_dir=directory, entrypoint="main.py"
        ),
        on_quarantine=quarantines.append,
        sleep=no_sleep,
    )


async def test_a_real_crash_is_reported_and_the_plugin_comes_back() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "crash-plugin", quarantines)
    await supervisor.start()
    try:
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {"capability": "die", "args": {}}, timeout=30)
        assert supervisor.restarts == 1
        assert quarantines == []
    finally:
        await supervisor.stop()


async def test_repeated_real_crashes_quarantine_the_plugin() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "crash-plugin", quarantines)
    await supervisor.start()
    try:
        for _ in range(3):
            with pytest.raises(PluginCrashedError):
                await supervisor.call("invoke", {"capability": "die", "args": {}}, timeout=30)
        assert supervisor.quarantined is True
        assert quarantines
    finally:
        await supervisor.stop()


async def test_a_real_hang_times_out_and_the_process_is_replaced() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "hang-plugin", quarantines)
    await supervisor.start()
    try:
        with pytest.raises(PluginTimeoutError):
            await supervisor.call("invoke", {"capability": "wait", "args": {}}, timeout=1.0)
        assert supervisor.restarts == 1
    finally:
        await supervisor.stop()
```

- [ ] **Step 7: Run everything**

Run: `uv run pytest tests/unit/test_plugin_supervisor.py tests/integration/test_plugin_supervision.py -q`
Expected: PASS (8 unit + 3 integration). The hang test should finish in about a second, not an hour — if it does not, the timeout is not killing the process.

- [ ] **Step 8: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/supervisor.py tests/unit/test_plugin_supervisor.py tests/integration/test_plugin_supervision.py tests/fixtures/plugins/
git commit -m "feat(DCL-096): supervise plugins with backoff, crash and violation quarantine"
```

---

### Task 12: The proxy tool

**Files:**
- Create: `declaw/plugin_host/tools.py`
- Modify: `declaw/tools/registry.py`
- Test: `tests/unit/test_plugin_tools.py`

**Interfaces:**
- Consumes: `DeclawTool`, `ToolClass` (existing `tools/base.py`); `ValidatedCapability` (Task 10)
- Produces: `PluginTool` (a `DeclawTool[BaseModel]` with extra fields `plugin`, `capability`, `invoke`), `plugin_tool_name(plugin, capability) -> str`, `build_plugin_tool(*, plugin_name, capability, invoke) -> PluginTool`; `ToolRegistry.register_instance(tool) -> DeclawTool[Any]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plugin_tools.py`:

```python
"""Turning a plugin capability into a tool the brain can call."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from declaw.plugin_host.loader import ValidatedCapability
from declaw.plugin_host.tools import build_plugin_tool, plugin_tool_name
from declaw.tools.base import ToolClass
from declaw.tools.builtin.filesystem import FilesystemReadTool
from declaw.tools.registry import ToolRegistry
from declaw_plugin_sdk.protocol import CapabilityDescriptor


class Args(BaseModel):
    message: str
    times: int = 1


def _capability(**overrides: Any) -> ValidatedCapability:
    base: dict[str, Any] = {
        "name": "echo",
        "description_en": "Repeat a message.",
        "description_fr": "Repete un message.",
        "args_schema": Args.model_json_schema(),
        "classification": "read",
    }
    return ValidatedCapability(
        descriptor=CapabilityDescriptor(**{**base, **overrides}),
        permissions=(),
        args_model=Args,
    )


def _recording_invoke() -> tuple[list[tuple[str, str, dict[str, Any]]], Any]:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(plugin: str, capability: str, args: dict[str, Any]) -> Any:
        calls.append((plugin, capability, args))
        return "bonjour"

    return calls, invoke


def test_tool_name_is_namespaced_with_dashes_converted() -> None:
    assert plugin_tool_name("doc-intel", "search") == "doc_intel_search"


def test_a_plugin_cannot_shadow_a_builtin_tool() -> None:
    # Namespacing is what makes this structurally impossible.
    assert plugin_tool_name("evil", "filesystem_read") != "filesystem_read"


def test_the_tool_forwards_validated_args_to_the_plugin() -> None:
    calls, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    import asyncio

    assert asyncio.run(tool.run_validated({"message": "salut", "times": 2})) == "bonjour"
    assert calls == [("echo-plugin", "echo", {"message": "salut", "times": 2})]


def test_invalid_args_are_rejected_before_the_plugin_is_contacted() -> None:
    calls, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    import asyncio

    with pytest.raises(ValidationError):
        asyncio.run(tool.run_validated({"times": 2}))
    assert calls == []  # nothing reached the subprocess


def test_a_structured_result_is_rendered_as_json_for_the_model() -> None:
    async def invoke(plugin: str, capability: str, args: dict[str, Any]) -> Any:
        return {"count": 3, "nom": "société"}

    tool = build_plugin_tool(plugin_name="p", capability=_capability(), invoke=invoke)
    import asyncio

    rendered = asyncio.run(tool.run_validated({"message": "x"}))
    assert json.loads(rendered)["count"] == 3
    assert "société" in rendered  # accents survive; ensure_ascii is off


def test_classification_and_descriptions_come_from_the_capability() -> None:
    _, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="p", capability=_capability(), invoke=invoke)
    assert tool.classification is ToolClass.READ
    assert tool.description_for("fr") == "Repete un message."


def test_external_content_flag_is_carried_so_the_sanitizer_applies() -> None:
    _, invoke = _recording_invoke()
    capability = _capability(produces_external_content=True)
    tool = build_plugin_tool(plugin_name="p", capability=capability, invoke=invoke)
    assert tool.produces_external_content is True


def test_register_instance_adds_a_prebuilt_tool() -> None:
    _, invoke = _recording_invoke()
    registry = ToolRegistry()
    registry.register_instance(
        build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    )
    assert registry.names() == ["echo_plugin_echo"]


def test_register_instance_still_refuses_a_duplicate_name() -> None:
    _, invoke = _recording_invoke()
    registry = ToolRegistry()
    registry.register(FilesystemReadTool)
    clashing = build_plugin_tool(
        plugin_name="filesystem", capability=_capability(name="read"), invoke=invoke
    )
    with pytest.raises(ValueError):
        registry.register_instance(clashing)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_plugin_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.tools'`

- [ ] **Step 3: Write the proxy tool**

`declaw/plugin_host/tools.py`:

```python
"""A plugin capability, dressed as an ordinary tool.

Everything downstream — ``bind_tools``, ``ToolNode``, the confirmation gate,
the sanitizer wrapper, the audit wrapper — treats this exactly like a built-in
tool, because it IS one: a ``DeclawTool`` whose ``_arun`` happens to travel
over a pipe. Nothing in the registry or the brain needs to know a subprocess
is involved.

Names are namespaced with the plugin slug, so a plugin cannot shadow
``filesystem_read`` no matter what it calls its capability.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from declaw.plugin_host.loader import ValidatedCapability
from declaw.tools.base import DeclawTool, ToolClass

InvokeCallable = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


def plugin_tool_name(plugin: str, capability: str) -> str:
    """Build the model-visible tool name for one capability."""
    return f"{plugin.replace('-', '_')}_{capability.replace('-', '_')}"


class PluginTool(DeclawTool[BaseModel]):
    """A ``DeclawTool`` that forwards to a plugin process."""

    plugin: str
    capability: str
    invoke: InvokeCallable

    async def _arun(self, args: BaseModel) -> str:
        result = await self.invoke(self.plugin, self.capability, args.model_dump(mode="json"))
        if isinstance(result, str):
            return result
        # ensure_ascii=False so French accents reach the model intact.
        return json.dumps(result, ensure_ascii=False, indent=2)


def build_plugin_tool(
    *, plugin_name: str, capability: ValidatedCapability, invoke: InvokeCallable
) -> PluginTool:
    """Wrap one validated capability as a registry-ready tool."""
    descriptor = capability.descriptor
    return PluginTool(
        name=plugin_tool_name(plugin_name, descriptor.name),
        description_en=descriptor.description_en,
        description_fr=descriptor.description_fr,
        classification=ToolClass(descriptor.classification),
        args_schema=capability.args_model,
        produces_external_content=descriptor.produces_external_content,
        plugin=plugin_name,
        capability=descriptor.name,
        invoke=invoke,
    )
```

- [ ] **Step 4: Teach the registry to take instances**

In `declaw/tools/registry.py`, add `register_instance` and make `register` delegate to it so there is one insertion path:

```python
    def register_instance(self, tool: DeclawTool[Any]) -> DeclawTool[Any]:
        """Register an already-constructed tool.

        Plugin proxy tools are bound to a specific plugin and capability, so
        they cannot be built by the class-and-instantiate path ``register``
        uses. Both routes share this one duplicate check.
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        return tool

    def register(self, tool_cls: type[DeclawTool[Any]]) -> type[DeclawTool[Any]]:
        """Instantiate and register ``tool_cls``. Usable as a class decorator."""
        # Concrete DeclawTool subclasses default every field (DCL-020), so they
        # instantiate with no args; the base type ``type[DeclawTool[Any]]``
        # can't express that, hence the targeted ignore.
        self.register_instance(tool_cls())  # type: ignore[call-arg]
        return tool_cls
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_plugin_tools.py tests/unit/test_tools_registry.py -q`
Expected: PASS (9 new + the existing 11 registry tests still green)

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/tools.py declaw/tools/registry.py tests/unit/test_plugin_tools.py
git commit -m "feat(DCL-090): expose plugin capabilities as namespaced DeclawTools"
```

---

### Task 13: The PluginHost facade

**Files:**
- Create: `declaw/plugin_host/host.py`
- Test: `tests/integration/test_plugin_host.py`

**Interfaces:**
- Consumes: everything from Tasks 7, 8, 10, 11, 12; `GrantStore`, `PermissionEnforcer` (existing `permissions.py`); `AuditLogger` (existing)
- Produces: `LoadedPlugin(manifest, directory, capabilities, supervisor, enforcer)`, `PluginHost(...)` with `start()`, `stop()`, `loaded()`, `failures()`, `call(plugin, capability, args)`, `model_tools()`, `enable(name)`, `disable(name)`; constant `MAX_TIMEOUT_S = 600.0`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_plugin_host.py`:

```python
"""The host end to end: discover, spawn, validate, grant, call, stop."""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.audit.events import PluginLifecycleEvent, PluginPermissionEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.plugin_host.errors import PluginUnavailableError
from declaw.plugin_host.host import PluginHost
from declaw.plugin_host.manifest import PluginPermission
from declaw.plugin_host.permissions import GrantStore, PermissionDeniedError
from declaw.plugin_host.state import PluginStateStore

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


def _host(tmp_path: Path, audit: InMemoryAuditLogger | None = None) -> PluginHost:
    return PluginHost(
        search_dir=FIXTURES / "echo-only",
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
        audit=audit,
    )


@pytest.fixture(autouse=True)
def _echo_only(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Point discovery at a directory holding only the echo fixture.

    crash-plugin and hang-plugin live alongside it and would be started too.
    """
    target = FIXTURES / "echo-only"
    target.mkdir(exist_ok=True)
    link = target / "echo-plugin"
    if not link.exists():
        import shutil

        shutil.copytree(FIXTURES / "echo-plugin", link)


async def test_start_loads_the_plugin_and_publishes_its_model_tools(tmp_path: Path) -> None:
    host = _host(tmp_path)
    await host.start()
    try:
        assert [p.manifest.name for p in host.loaded()] == ["echo-plugin"]
        names = {tool.name for tool in host.model_tools()}
        # 'count' is not exposed_to_model, so the brain must never see it.
        assert names == {"echo_plugin_echo", "echo_plugin_noisy"}
    finally:
        await host.stop()


async def test_a_call_reaches_the_plugin(tmp_path: Path) -> None:
    host = _host(tmp_path)
    await host.start()
    try:
        result = await host.call("echo-plugin", "echo", {"message": "salut", "times": 2})
        assert result == "salut salut"
    finally:
        await host.stop()


async def test_manifest_permissions_are_auto_granted_and_audited(tmp_path: Path) -> None:
    audit = InMemoryAuditLogger()
    host = _host(tmp_path, audit)
    await host.start()
    try:
        grants = GrantStore(tmp_path / "plugin_grants.json")
        assert PluginPermission.FILESYSTEM_READ in grants.granted("echo-plugin")
        granted = [
            e
            for e in audit.events
            if isinstance(e, PluginPermissionEvent) and e.action == "granted"
        ]
        assert granted and granted[0].plugin == "echo-plugin"
    finally:
        await host.stop()


async def test_a_revoked_permission_is_not_auto_granted_again(tmp_path: Path) -> None:
    # The whole point of tracking auto_granted in plugin_state.json.
    host = _host(tmp_path)
    await host.start()
    await host.stop()

    grants = GrantStore(tmp_path / "plugin_grants.json")
    await grants.revoke("echo-plugin", PluginPermission.FILESYSTEM_READ)

    host2 = _host(tmp_path)
    await host2.start()
    try:
        reloaded = GrantStore(tmp_path / "plugin_grants.json")
        assert PluginPermission.FILESYSTEM_READ not in reloaded.granted("echo-plugin")
        with pytest.raises(PermissionDeniedError):
            await host2.call("echo-plugin", "count", {"values": ["a"]})
    finally:
        await host2.stop()


async def test_a_disabled_plugin_is_not_started(tmp_path: Path) -> None:
    state = PluginStateStore(tmp_path / "plugin_state.json")
    state.set_enabled("echo-plugin", False)
    host = PluginHost(
        search_dir=FIXTURES / "echo-only",
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
    )
    await host.start()
    try:
        assert host.loaded() == []
        assert host.model_tools() == []
    finally:
        await host.stop()


async def test_a_quarantined_plugin_is_not_started(tmp_path: Path) -> None:
    PluginStateStore(tmp_path / "plugin_state.json").quarantine("echo-plugin", "crashed")
    host = _host(tmp_path)
    await host.start()
    try:
        assert host.loaded() == []
    finally:
        await host.stop()


async def test_calling_an_unloaded_plugin_raises_unavailable(tmp_path: Path) -> None:
    host = _host(tmp_path)
    await host.start()
    try:
        with pytest.raises(PluginUnavailableError):
            await host.call("not-here", "echo", {})
    finally:
        await host.stop()


async def test_lifecycle_events_are_audited(tmp_path: Path) -> None:
    audit = InMemoryAuditLogger()
    host = _host(tmp_path, audit)
    await host.start()
    await host.stop()
    actions = {e.action for e in audit.events if isinstance(e, PluginLifecycleEvent)}
    assert "started" in actions and "stopped" in actions
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/integration/test_plugin_host.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.plugin_host.host'`

- [ ] **Step 3: Write the facade**

`declaw/plugin_host/host.py`:

```python
"""The single surface the rest of DeClaw uses to talk to plugins.

Startup is a pipeline, and every stage can refuse: discover a directory, read
its manifest, spawn the process, ask it to describe itself, validate what it
claims against what its manifest requested, grant what a builtin plugin needs,
and only then publish its tools. A plugin that fails any stage is skipped with
an audited reason; the others load normally.

Auto-granting is narrow and deliberate. A builtin plugin ships inside the
application, so a user who does not trust it cannot trust DeClaw either — there
is no separate trust decision to prompt for, and prompting would only train
people to click through. What makes it acceptable is that it is visible
(audited, listed by `declaw plugins list`) and reversible (a revoked permission
is recorded and never auto-granted again). None of that reasoning survives
contact with third-party plugins, which is why installation is out of scope
until there is a dialog to gate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from declaw.audit.events import PluginLifecycleEvent
from declaw.audit.logger import AuditLogger
from declaw.config import Settings, get_settings
from declaw.log import logger
from pydantic import ValidationError

from declaw.plugin_host.errors import PluginHostError, PluginUnavailableError
from declaw.plugin_host.loader import (
    ValidatedCapability,
    builtin_plugins_dir,
    discover,
    validate_described,
)
from declaw.plugin_host.manifest import PluginManifest
from declaw.plugin_host.permissions import GrantStore, PermissionEnforcer
from declaw.plugin_host.process import PluginProcess
from declaw.plugin_host.state import PluginStateStore
from declaw.plugin_host.supervisor import PluginSupervisor
from declaw.plugin_host.tools import PluginTool, build_plugin_tool
from declaw_plugin_sdk.protocol import DescribeResult

# No capability may hold a process hostage longer than this, whatever it declares.
MAX_TIMEOUT_S = 600.0
DESCRIBE_TIMEOUT_S = 30.0


@dataclass(slots=True)
class LoadedPlugin:
    """One plugin that started, validated, and is serving calls."""

    manifest: PluginManifest
    directory: Path
    capabilities: dict[str, ValidatedCapability]
    supervisor: PluginSupervisor
    enforcer: PermissionEnforcer


class PluginHost:
    """Discover, run, and route calls to plugins."""

    def __init__(
        self,
        *,
        state: PluginStateStore,
        grants: GrantStore,
        settings: Settings | None = None,
        search_dir: Path | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._search_dir = search_dir or builtin_plugins_dir(self._settings)
        self._state = state
        self._grants = grants
        self._audit = audit
        self._plugins: dict[str, LoadedPlugin] = {}
        self._failures: list[str] = []

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Load every enabled, non-quarantined plugin found on disk."""
        found, discovery_failures = discover(self._search_dir)
        for failure in discovery_failures:
            self._failures.append(f"{failure.directory.name}: {failure.reason}")
            await self._emit(failure.directory.name, "load_failed", detail=failure.reason)

        for candidate in found:
            record = self._state.record(candidate.manifest.name)
            if not record.enabled or record.quarantined:
                continue
            try:
                await self._load(candidate.directory, candidate.manifest)
            # PluginHostError covers PluginLoadError AND the runtime failures a
            # describe handshake can hit (crash, timeout, error frame). Catching
            # only PluginLoadError would let one sick plugin abort startup for
            # every other plugin.
            except (PluginHostError, ValidationError, OSError) as exc:
                self._failures.append(f"{candidate.manifest.name}: {exc}")
                logger.error(f"Plugin {candidate.manifest.name!r} failed to load: {exc}")
                await self._emit(candidate.manifest.name, "load_failed", detail=str(exc))

    async def _load(self, directory: Path, manifest: PluginManifest) -> None:
        supervisor = PluginSupervisor(
            name=manifest.name,
            factory=lambda: PluginProcess(
                name=manifest.name, plugin_dir=directory, entrypoint=manifest.entrypoint
            ),
            on_quarantine=lambda reason: self._state.quarantine(manifest.name, reason),
        )
        await supervisor.start()
        try:
            raw = await supervisor.call("describe", timeout=DESCRIBE_TIMEOUT_S)
            described = DescribeResult.model_validate(raw)
            validated = validate_described(manifest, described)
        except Exception:
            await supervisor.stop()
            raise

        await self._auto_grant(manifest)
        self._plugins[manifest.name] = LoadedPlugin(
            manifest=manifest,
            directory=directory,
            capabilities={c.descriptor.name: c for c in validated},
            supervisor=supervisor,
            enforcer=PermissionEnforcer(manifest, self._grants, audit=self._audit),
        )
        self._state.note_version(manifest.name, manifest.version)
        await self._emit(manifest.name, "started", version=manifest.version)

    async def _auto_grant(self, manifest: PluginManifest) -> None:
        """Grant what a builtin manifest requests, once, and remember doing it."""
        for permission in manifest.permissions.requested:
            if self._state.has_auto_granted(manifest.name, permission.value):
                continue  # already offered once; a later revoke must stick
            if permission in self._grants.granted(manifest.name):
                continue
            await self._grants.grant(manifest.name, permission, audit=self._audit)
            self._state.note_auto_grant(manifest.name, permission.value)

    async def stop(self) -> None:
        for name, plugin in list(self._plugins.items()):
            await plugin.supervisor.stop()
            await self._emit(name, "stopped", version=plugin.manifest.version)
        self._plugins.clear()

    # ------------------------------------------------------------------- calls

    async def call(self, plugin: str, capability: str, args: dict[str, Any]) -> Any:
        """Invoke a capability after checking every permission it declared."""
        loaded = self._plugins.get(plugin)
        if loaded is None:
            raise PluginUnavailableError(f"Plugin {plugin!r} is not loaded.")
        validated = loaded.capabilities.get(capability)
        if validated is None:
            raise PluginUnavailableError(
                f"Plugin {plugin!r} has no capability {capability!r}."
            )
        for permission in validated.permissions:
            await loaded.enforcer.require(permission)
        timeout = min(float(validated.descriptor.timeout_s), MAX_TIMEOUT_S)
        return await loaded.supervisor.call(
            "invoke", {"capability": capability, "args": args}, timeout=timeout
        )

    # ------------------------------------------------------------ introspection

    def loaded(self) -> list[LoadedPlugin]:
        return list(self._plugins.values())

    def failures(self) -> list[str]:
        return list(self._failures)

    def model_tools(self) -> list[PluginTool]:
        """Proxy tools for every capability a plugin published to the model."""
        tools: list[PluginTool] = []
        for plugin in self._plugins.values():
            for validated in plugin.capabilities.values():
                if not validated.descriptor.exposed_to_model:
                    continue
                tools.append(
                    build_plugin_tool(
                        plugin_name=plugin.manifest.name,
                        capability=validated,
                        invoke=self.call,
                    )
                )
        return tools

    # ---------------------------------------------------------------- user acts

    async def enable(self, name: str) -> None:
        self._state.set_enabled(name, True)
        self._state.clear_quarantine(name)
        await self._emit(name, "enabled")

    async def disable(self, name: str) -> None:
        loaded = self._plugins.pop(name, None)
        if loaded is not None:
            await loaded.supervisor.stop()
        self._state.set_enabled(name, False)
        await self._emit(name, "disabled")

    async def _emit(self, plugin: str, action: Any, *, version: str = "", detail: str = "") -> None:
        if self._audit is None:
            return
        await self._audit.emit(
            PluginLifecycleEvent(plugin=plugin, version=version, action=action, detail=detail)
        )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/integration/test_plugin_host.py -q`
Expected: PASS (8 tests)

Add `tests/fixtures/plugins/echo-only/` to `.gitignore` — it is a copy made by the fixture, not source.

- [ ] **Step 5: Run the whole suite for the first time**

Run: `uv run pytest -q`
Expected: every previous test still green. This is the first task that touches shared wiring, so a regression here is a real one.

- [ ] **Step 6: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/plugin_host/host.py tests/integration/test_plugin_host.py .gitignore
git commit -m "feat(DCL-091): PluginHost facade with audited auto-grant for builtin plugins"
```

---

### Task 14: CLI and chat wiring

**Files:**
- Modify: `declaw/main.py`
- Test: `tests/unit/test_cli_plugins.py`

**Interfaces:**
- Consumes: `PluginHost`, `PluginStateStore`, `GrantStore`, `discover`, `builtin_plugins_dir` (Tasks 8, 10, 13)
- Produces: CLI commands `declaw plugins list|enable|disable|revoke`; `declaw chat` with the host started inside the event loop

**The constraint that shapes this task:** `main.py:191` currently builds the tool
list and the graph *before* `asyncio.run(_session())`. `PluginHost.start()` is
async and asyncio subprocess transports belong to the loop that created them,
so a host started outside `_session()` yields pipes the REPL cannot read. The
existing comment about `ensure_schema` and aiosqlite documents the same
constraint for the same reason — extend that pattern rather than invent one.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_plugins.py`:

```python
"""The plugins CLI group. Reads state and manifests; starts no subprocess."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from declaw.main import cli
from declaw.plugin_host.state import PluginStateStore

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins" / "echo-plugin"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DECLAW_BUILTIN_PLUGINS_DIR", str(FIXTURES.parent))
    from declaw.config import get_settings

    get_settings.cache_clear()


def test_list_shows_the_plugin_its_version_and_its_permissions() -> None:
    result = runner.invoke(cli, ["plugins", "list"])
    assert result.exit_code == 0
    assert "echo-plugin" in result.stdout
    assert "1.0.0" in result.stdout
    assert "filesystem.read" in result.stdout


def test_disable_then_list_reports_it_disabled(tmp_path: Path) -> None:
    assert runner.invoke(cli, ["plugins", "disable", "echo-plugin"]).exit_code == 0
    assert PluginStateStore(tmp_path / "plugin_state.json").record("echo-plugin").enabled is False
    assert "disabled" in runner.invoke(cli, ["plugins", "list"]).stdout.lower()


def test_enable_clears_a_quarantine(tmp_path: Path) -> None:
    PluginStateStore(tmp_path / "plugin_state.json").quarantine("echo-plugin", "crashed")
    assert runner.invoke(cli, ["plugins", "enable", "echo-plugin"]).exit_code == 0
    record = PluginStateStore(tmp_path / "plugin_state.json").record("echo-plugin")
    assert record.quarantined is False and record.enabled is True


def test_revoke_removes_an_existing_grant(tmp_path: Path) -> None:
    import asyncio

    from declaw.plugin_host.grants_helper import load_grants  # see Step 3
    from declaw.plugin_host.manifest import PluginPermission

    # Grant first, so the test proves removal rather than an empty store.
    grants = load_grants(tmp_path)
    asyncio.run(grants.grant("echo-plugin", PluginPermission.FILESYSTEM_READ))
    assert PluginPermission.FILESYSTEM_READ in load_grants(tmp_path).granted("echo-plugin")

    result = runner.invoke(cli, ["plugins", "revoke", "echo-plugin", "filesystem.read"])
    assert result.exit_code == 0
    assert load_grants(tmp_path).granted("echo-plugin") == frozenset()


def test_revoking_an_unknown_permission_fails_with_a_readable_message() -> None:
    result = runner.invoke(cli, ["plugins", "revoke", "echo-plugin", "filesystem.obliterate"])
    assert result.exit_code != 0
    assert "filesystem.obliterate" in result.stdout


def test_an_unknown_plugin_name_is_rejected() -> None:
    result = runner.invoke(cli, ["plugins", "disable", "no-such-plugin"])
    assert result.exit_code != 0
    assert "no-such-plugin" in result.stdout
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_cli_plugins.py -q`
Expected: FAIL — `No such command 'plugins'`

- [ ] **Step 3: Add the small grants helper**

Both the CLI and the chat command need a `GrantStore` at the conventional
path. Create `declaw/plugin_host/grants_helper.py`:

```python
"""Where the grant and state files live, in one place.

Two commands and the chat session all need these paths; deriving them
separately in each would be three chances to disagree.
"""

from __future__ import annotations

from pathlib import Path

from declaw.plugin_host.permissions import GRANTS_FILENAME, GrantStore
from declaw.plugin_host.state import STATE_FILENAME, PluginStateStore


def load_grants(data_dir: Path) -> GrantStore:
    return GrantStore(data_dir / GRANTS_FILENAME)


def load_state(data_dir: Path) -> PluginStateStore:
    return PluginStateStore(data_dir / STATE_FILENAME)
```

- [ ] **Step 4: Add the CLI group**

`main.py` imports lazily inside commands to keep `version`/`status` fast, so
the annotation on `_known_plugin` needs a type-only import. Add near the top of
the file:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from declaw.plugin_host.manifest import PluginManifest
```

Then, after the existing commands:

```python
plugins_app = typer.Typer(help="List and control the plugins DeClaw ships with.")
cli.add_typer(plugins_app, name="plugins")


def _known_plugin(name: str) -> PluginManifest:
    """Resolve a plugin name to its manifest or exit with a readable error."""
    from declaw.config import get_settings
    from declaw.plugin_host.loader import builtin_plugins_dir, discover

    found, _failures = discover(builtin_plugins_dir(get_settings()))
    for candidate in found:
        if candidate.manifest.name == name:
            return candidate.manifest
    known = ", ".join(sorted(c.manifest.name for c in found)) or "none"
    console.print(f"[red]No plugin named {name!r}.[/red] Installed: {known}.")
    raise typer.Exit(code=1)


@plugins_app.command("list")
def plugins_list() -> None:
    """Show every shipped plugin, its state, and the permissions it holds."""
    from declaw.config import get_settings
    from declaw.plugin_host.grants_helper import load_grants, load_state
    from declaw.plugin_host.loader import builtin_plugins_dir, discover

    settings = get_settings()
    found, failures = discover(builtin_plugins_dir(settings))
    state = load_state(settings.data_dir)
    grants = load_grants(settings.data_dir)

    if not found and not failures:
        console.print("[dim]No plugins found.[/dim]")
        return

    for candidate in found:
        manifest = candidate.manifest
        record = state.record(manifest.name)
        if record.quarantined:
            status = f"[red]quarantined[/red] ({record.quarantine_reason})"
        elif not record.enabled:
            status = "[yellow]disabled[/yellow]"
        else:
            status = "[green]enabled[/green]"
        held = grants.granted(manifest.name)
        console.print(f"[bold]{manifest.name}[/bold] {manifest.version} - {status}")
        console.print(f"  {manifest.description_for_language(settings.language)}")
        for permission in sorted(p.value for p in manifest.permissions.requested):
            mark = "granted" if any(p.value == permission for p in held) else "not granted"
            console.print(f"  - {permission}: {mark}")
    for failure in failures:
        console.print(f"[red]{failure.directory.name}[/red]: {failure.reason}")


@plugins_app.command("enable")
def plugins_enable(name: str) -> None:
    """Enable a plugin and clear any quarantine on it."""
    from declaw.config import get_settings
    from declaw.plugin_host.grants_helper import load_state

    _known_plugin(name)
    state = load_state(get_settings().data_dir)
    state.set_enabled(name, True)
    state.clear_quarantine(name)
    console.print(f"[green]{name} enabled.[/green] It starts with the next 'declaw chat'.")


@plugins_app.command("disable")
def plugins_disable(name: str) -> None:
    """Stop a plugin from starting."""
    from declaw.config import get_settings
    from declaw.plugin_host.grants_helper import load_state

    _known_plugin(name)
    load_state(get_settings().data_dir).set_enabled(name, False)
    console.print(f"[yellow]{name} disabled.[/yellow]")


@plugins_app.command("revoke")
def plugins_revoke(name: str, permission: str) -> None:
    """Take a permission away from a plugin. It is never auto-granted again."""
    import asyncio

    from declaw.config import get_settings
    from declaw.plugin_host.grants_helper import load_grants
    from declaw.plugin_host.manifest import PluginPermission

    _known_plugin(name)
    try:
        parsed = PluginPermission(permission)
    except ValueError:
        allowed = ", ".join(sorted(p.value for p in PluginPermission))
        console.print(f"[red]Unknown permission {permission!r}.[/red] Known: {allowed}.")
        raise typer.Exit(code=1) from None
    grants = load_grants(get_settings().data_dir)
    asyncio.run(grants.revoke(name, parsed))
    console.print(f"[green]{permission} revoked from {name}.[/green]")
```

`PluginManifest` needs a `description_for_language(language)` helper — add it
to `declaw/plugin_host/manifest.py` alongside the existing validators:

```python
    def description_for_language(self, language: str) -> str:
        """Return the manifest description in the user's language."""
        return self.description_fr if language == "fr" else self.description_en
```

- [ ] **Step 5: Restructure the chat command**

In `declaw/main.py`, the block currently at lines ~191-193 reads:

```python
    tools = default_registry().langchain_tools(
        settings.language, approve, sanitizer=sanitizer, audit=audit
    )
    graph = build_brain(tools)
```

Delete those four lines and move the work inside `_session`, which becomes:

```python
    async def _session() -> None:
        # Schema, plugin subprocesses and the chat all share one event loop:
        # aiosqlite connections and asyncio subprocess transports are both
        # bound to the loop that created them.
        await ensure_schema(engine)

        from declaw.plugin_host.grants_helper import load_grants, load_state
        from declaw.plugin_host.host import PluginHost

        host = PluginHost(
            state=load_state(settings.data_dir),
            grants=load_grants(settings.data_dir),
            settings=settings,
            audit=audit,
        )
        await host.start()
        for failure in host.failures():
            console.print(f"[yellow]Plugin not loaded -[/yellow] {failure}")

        registry = default_registry()
        for tool in host.model_tools():
            registry.register_instance(tool)
        tools = registry.langchain_tools(
            settings.language, approve, sanitizer=sanitizer, audit=audit
        )
        graph = build_brain(tools)

        loaded = ", ".join(p.manifest.name for p in host.loaded()) or "none"
        console.print(f"[dim]plugins: {loaded}[/dim]")
        try:
            await run_chat(
                graph, read=read, write=write, debug=debug, language=settings.language
            )
        finally:
            await host.stop()
```

The banner printed before `_session` still reports model, workspace, sanitizer
and audit; the plugin line is printed from inside, once the host knows what
actually loaded.

- [ ] **Step 6: Run the CLI tests**

Run: `uv run pytest tests/unit/test_cli_plugins.py -q`
Expected: PASS (6 tests)

- [ ] **Step 7: Verify chat still starts**

Requires Ollama with `qwen2.5:3b` and `qwen2.5:7b` pulled. If they are not
available, skip this step and note it — do not fake it.

Run: `uv run declaw chat`
Expected: the banner appears, followed by `plugins: none` (no plugin ships yet
in `plugins/builtin/`; doc-intel arrives in Phase 8). Type `/exit`.

- [ ] **Step 8: Typecheck and commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/main.py declaw/plugin_host/grants_helper.py declaw/plugin_host/manifest.py tests/unit/test_cli_plugins.py
git commit -m "feat(DCL-091): declaw plugins CLI and host wiring inside the chat event loop"
```

---

### Task 15: Security suite and documentation

**Files:**
- Create: `tests/fixtures/plugins/probe-plugin/{plugin.yaml,main.py}`, `tests/fixtures/plugins/overreach-plugin/{plugin.yaml,main.py}`
- Create: `tests/security/test_plugin_isolation.py`
- Modify: `CLAUDE.md`, `TICKETS.md`, `docs/phase-7-review.md` (new)

**Interfaces:**
- Consumes: everything above
- Produces: no new code interfaces; this task proves the security claims and records the phase

- [ ] **Step 1: Create the probe fixture**

`tests/fixtures/plugins/probe-plugin/plugin.yaml`:

```yaml
manifest_version: 1
name: probe-plugin
version: 1.0.0
description_en: Test plugin that reports on its own sandbox.
description_fr: Plugin de test qui rapporte son propre environnement.
entrypoint: main.py
```

`tests/fixtures/plugins/probe-plugin/main.py`:

```python
"""Reports what the plugin process can see, so tests can assert on it."""

from __future__ import annotations

import os

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class ProbePlugin(BasePlugin):
    name = "probe-plugin"
    version = "1.0.0"

    @capability(
        name="try_import",
        description_en="Try to import declaw and report the outcome.",
        description_fr="Tente d'importer declaw et rapporte le resultat.",
    )
    async def try_import(self, args: NoArgs) -> str:
        try:
            import declaw  # noqa: F401
        except ImportError as exc:
            return f"blocked: {exc}"
        return "IMPORT SUCCEEDED"

    @capability(
        name="import_sdk",
        description_en="Confirm the SDK itself is importable.",
        description_fr="Confirme que le SDK est importable.",
    )
    async def import_sdk(self, args: NoArgs) -> str:
        import declaw_plugin_sdk.protocol

        return f"ok {declaw_plugin_sdk.protocol.SDK_VERSION}"

    @capability(
        name="dump_env",
        description_en="Return the environment variable names visible here.",
        description_fr="Renvoie les noms des variables d'environnement visibles.",
    )
    async def dump_env(self, args: NoArgs) -> list[str]:
        return sorted(os.environ)
```

- [ ] **Step 2: Create the overreach fixture**

This one's manifest requests nothing, while its capability demands
`filesystem.read`. Loading it must fail.

`tests/fixtures/plugins/overreach-plugin/plugin.yaml`:

```yaml
manifest_version: 1
name: overreach-plugin
version: 1.0.0
description_en: Test plugin whose code asks for more than its manifest.
description_fr: Plugin de test dont le code demande plus que son manifeste.
entrypoint: main.py
```

`tests/fixtures/plugins/overreach-plugin/main.py`:

```python
"""Declares a capability needing a permission the manifest never requested."""

from __future__ import annotations

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class OverreachPlugin(BasePlugin):
    name = "overreach-plugin"
    version = "1.0.0"

    @capability(
        name="peek",
        description_en="Read files.",
        description_fr="Lit des fichiers.",
        requires=["filesystem.read"],
    )
    async def peek(self, args: NoArgs) -> str:
        return "never reached"
```

- [ ] **Step 3: Write the security tests**

Create `tests/security/test_plugin_isolation.py`:

```python
"""The security claims of the plugin boundary, proven against real processes.

These assert what the boundary DOES provide. What it does not provide is
documented in the Phase 7 spec under 'Honest limitations' — a malicious plugin
runs with the user's privileges and can remove the import hook. These tests do
not pretend otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.loader import validate_described
from declaw.plugin_host.manifest import load_manifest
from declaw.plugin_host.process import PluginProcess
from declaw_plugin_sdk.protocol import DescribeResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


async def _probe() -> PluginProcess:
    directory = FIXTURES / "probe-plugin"
    process = PluginProcess(name="probe-plugin", plugin_dir=directory, entrypoint="main.py")
    await process.start()
    return process


async def test_a_plugin_cannot_import_declaw() -> None:
    process = await _probe()
    try:
        result = await process.request(
            "invoke", {"capability": "try_import", "args": {}}, timeout=30
        )
        assert result.startswith("blocked:")
        assert "may not import" in result
    finally:
        await process.shutdown()


async def test_a_plugin_can_still_import_its_own_sdk() -> None:
    # 'declaw_plugin_sdk' shares a prefix with 'declaw'; blocking it would
    # break every plugin.
    process = await _probe()
    try:
        result = await process.request(
            "invoke", {"capability": "import_sdk", "args": {}}, timeout=30
        )
        assert result.startswith("ok ")
    finally:
        await process.shutdown()


async def test_no_declaw_or_ollama_setting_is_visible_to_the_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECLAW_SANITIZER_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    process = await _probe()
    try:
        names = await process.request(
            "invoke", {"capability": "dump_env", "args": {}}, timeout=30
        )
        leaked = [n for n in names if n.startswith(("DECLAW_", "OLLAMA"))]
        assert leaked == ["DECLAW_PLUGIN_NAME"]
    finally:
        await process.shutdown()


async def test_a_capability_demanding_more_than_its_manifest_refuses_to_load() -> None:
    # DCL-097 at load time: the plugin never gets to run.
    directory = FIXTURES / "overreach-plugin"
    manifest = load_manifest(directory)
    process = PluginProcess(
        name="overreach-plugin", plugin_dir=directory, entrypoint="main.py"
    )
    await process.start()
    try:
        described = DescribeResult.model_validate(
            await process.request("describe", timeout=30)
        )
        with pytest.raises(PluginLoadError) as excinfo:
            validate_described(manifest, described)
        assert "filesystem.read" in str(excinfo.value)
        assert "never requested" in str(excinfo.value)
    finally:
        await process.shutdown()
```

- [ ] **Step 4: Run the security suite**

Run: `uv run pytest tests/security/ -q`
Expected: PASS (4 tests)

`test_a_plugin_cannot_import_declaw` returning `IMPORT SUCCEEDED` means the
blocker is installed after the entrypoint import, or the prefix check is wrong.
Check the order in `bootstrap.main`.

- [ ] **Step 5: Run everything, twice**

```bash
uv run pytest -q
uv run pytest -q
```

Both runs must be green and produce the same counts. Running twice catches
state that leaks between runs through `plugin_state.json` or the copied
`echo-only` fixture directory.

- [ ] **Step 6: Write the phase review**

Create `docs/phase-7-review.md` following the shape of `docs/phase-6-review.md`. It must state plainly:

- what was built, module by module
- test counts (unit / integration / security), mypy file count, ruff status
- the four honest limitations from the spec, verbatim — a malicious plugin is not contained, enforcement is host-side only, builtin code is not signature-verified, one request at a time
- that DCL-071/072/073 remain deferred and why
- that `plugins/builtin/` is empty until Phase 8

- [ ] **Step 7: Update TICKETS.md**

Mark DCL-090 through DCL-097 `[x]`. Rewrite four acceptance criteria to match what was built rather than what was assumed:

- **DCL-091**: "Enable, disable and quarantine persist across restarts. Install, uninstall and update are out of scope for v0.1 (builtin plugins only)."
- **DCL-092**: "Spawned with a built-from-scratch environment and no keyring access. The `declaw.*` import hook enforces the architectural boundary; it is not a security control — see docs/phase-7-review.md."
- **DCL-095**: "`~/.declaw/plugin_state.json` survives restarts. Plain JSON, not SQLite: this is user policy and being diffable is a feature."
- **DCL-097**: "A capability requiring a permission its manifest never requested refuses the load. Three protocol violations in one process lifetime kill and quarantine the plugin. Both audited."

- [ ] **Step 8: Update CLAUDE.md**

Add a Phase 7 section under Completed tickets summarising each ticket the way the Phase 5 and 6 sections do. Then:

- **Current state**: Phase 7 complete on `feat/phase-7-plugin-host`; next is Phase 8 (doc-intel) on a branch from it
- **In progress**: none
- **Locked decisions**: note that the plugin credential API stays deferred, and that builtin plugins auto-grant their manifest permissions — with the rule that this must close when third-party install opens
- **Notes for next session**: point at both spec documents; record that Phase 8 is a thin parser plugin with the core owning embedding, encryption, Chroma and search; record that chunk sanitizing happens at retrieval time on top-k with a hash cache
- Update the **Last updated** date

- [ ] **Step 9: Final verification and commit**

```bash
uv run pytest -q
uv run mypy declaw declaw_plugin_sdk
uv run ruff check
git add -A
git commit -m "feat(DCL-097): plugin isolation security suite, phase 7 review, docs"
```

Report the real numbers from these three commands in the phase review. If
anything fails, fix it before committing — a green claim with a red suite is
the one outcome this project does not tolerate.

---

## Notes for the executor

**Order matters.** Tasks 1-4 are independent leaves and could be done in any
order, but 5 needs 2, 6 needs 5, 7 needs 6, 10 needs 4, 11 needs 7, 12 needs
10, 13 needs 8+10+11+12, 14 needs 13, 15 needs everything. Do them in order.

**The milestone to enjoy** is Task 6 Step 8: piping a JSON line into the
bootstrap and getting a valid frame back, before any host exists.

**If integration tests hang**, the cause is nearly always one of two things:
stderr is not being drained, or a fixture plugin is waiting on stdin that was
never written. Both show as a test that never finishes rather than one that
fails.

**Do not weaken a test to make it pass.** If `validate_described` rejects
something the plan expects it to accept, the bug is in one of them — find out
which before editing either.

