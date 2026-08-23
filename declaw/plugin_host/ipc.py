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
