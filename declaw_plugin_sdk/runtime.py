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
from typing import Any, get_args

from pydantic import BaseModel, ValidationError

from declaw_plugin_sdk.declaration import BasePlugin, CapabilitySpec
from declaw_plugin_sdk.protocol import (
    MAX_FRAME_BYTES,
    ErrorCode,
    FrameError,
    Method,
    RequestFrame,
    ResponseFrame,
)

ReadLine = Callable[[], bytes]
WriteFrame = Callable[[bytes], None]

_METHODS: frozenset[str] = frozenset(get_args(Method))


def _error(request_id: str, code: ErrorCode, message: str) -> ResponseFrame:
    return ResponseFrame(id=request_id, ok=False, error=FrameError(code=code, message=message))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _invoke(
    plugin: BasePlugin, specs: dict[str, CapabilitySpec], frame: RequestFrame
) -> ResponseFrame:
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
        print(traceback.format_exc(), file=sys.stderr)
        return _error(frame.id, "capability_failed", f"{type(exc).__name__}: {exc}")
    return ResponseFrame(id=frame.id, ok=True, result=_jsonable(result))


def handle_line(
    plugin: BasePlugin, specs: dict[str, CapabilitySpec], line: bytes
) -> tuple[ResponseFrame | None, bool]:
    """Turn one input line into (response, should_stop)."""
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        # No usable id: the host counts this as a protocol violation, which is
        # the correct outcome for a host that sent something unreadable.
        return _error("", "internal", f"Unreadable request frame: {exc}."), False

    # Check the method before model validation. RequestFrame types it as a
    # Literal, so validation would collapse "method I don't know" into a
    # generic parse error — and that distinction is exactly what diagnoses
    # version skew against a newer host.
    if isinstance(raw, dict) and isinstance(raw.get("method"), str):
        if raw["method"] not in _METHODS:
            request_id = raw["id"] if isinstance(raw.get("id"), str) else ""
            return (
                _error(request_id, "unknown_method", f"Unknown method {raw['method']!r}."),
                False,
            )

    try:
        frame = RequestFrame.model_validate(raw)
    except ValidationError as exc:
        return _error("", "internal", f"Unreadable request frame: {exc}."), False

    if frame.method == "describe":
        return (
            ResponseFrame(id=frame.id, ok=True, result=plugin.describe().model_dump(mode="json")),
            False,
        )
    if frame.method == "shutdown":
        return ResponseFrame(id=frame.id, ok=True, result=None), True
    return _invoke(plugin, specs, frame), False


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
