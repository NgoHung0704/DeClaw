"""Strict, bounded NDJSON for inherited desktop channels.

Only fixed error codes cross this boundary. Never expose decoder exceptions,
raw frames or credential replies through diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal, TypeAlias
from uuid import UUID

MAX_CONTROL_BYTES = 16 * 1024
MAX_CREDENTIAL_BYTES = 4 * 1024
Direction: TypeAlias = Literal["parent", "child", "credential"]
ErrorCode: TypeAlias = Literal[
    "invalid_settings", "port_conflict", "spawn_failed", "protocol_invalid",
    "startup_timeout", "shutdown_timeout", "unavailable",
]
ERROR_CODES = frozenset({
    "invalid_settings", "port_conflict", "spawn_failed", "protocol_invalid",
    "startup_timeout", "shutdown_timeout", "unavailable",
})


class ProtocolError(ValueError):
    """A deliberately payload-free error."""

    def __init__(self) -> None:
        super().__init__("protocol_invalid")


@dataclass(frozen=True, kw_only=True)
class _Frame:
    launch_id: str
    version: int = 1


@dataclass(frozen=True, kw_only=True)
class Stop(_Frame):
    type: Literal["Stop"] = "Stop"


@dataclass(frozen=True, kw_only=True)
class RequestBootstrapToken(_Frame):
    request_id: str
    type: Literal["RequestBootstrapToken"] = "RequestBootstrapToken"


@dataclass(frozen=True, kw_only=True)
class Ready(_Frame):
    authority: str
    type: Literal["Ready"] = "Ready"


@dataclass(frozen=True, kw_only=True)
class Failure(_Frame):
    code: ErrorCode
    type: Literal["Failure"] = "Failure"


@dataclass(frozen=True, kw_only=True)
class Stopped(_Frame):
    clean: bool
    type: Literal["Stopped"] = "Stopped"


@dataclass(frozen=True, kw_only=True)
class Notice(_Frame):
    event_id: str
    kind: Literal["quarantine", "approval_pending"]
    language: Literal["en", "fr"]
    task_id: str | None = None
    request_id: str | None = None
    type: Literal["Notice"] = "Notice"


@dataclass(frozen=True, kw_only=True)
class BootstrapToken(_Frame):
    request_id: str
    token: str = field(repr=False)
    type: Literal["BootstrapToken"] = "BootstrapToken"


ParentFrame: TypeAlias = Stop | RequestBootstrapToken
ChildFrame: TypeAlias = Ready | Failure | Stopped | Notice
Frame: TypeAlias = ParentFrame | ChildFrame | BootstrapToken

_VARIANTS: dict[Direction, dict[str, type[Frame]]] = {
    "parent": {"Stop": Stop, "RequestBootstrapToken": RequestBootstrapToken},
    "child": {"Ready": Ready, "Failure": Failure, "Stopped": Stopped, "Notice": Notice},
    "credential": {"BootstrapToken": BootstrapToken},
}


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError()
        result[key] = value
    return result


def _parse(data: bytes, direction: Direction) -> Frame | None:
    """Return no frame on malformed data, without retaining parser exceptions."""
    try:
        values = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(values, dict):
        return None
    variant = values.get("type")
    if not isinstance(variant, str):
        return None
    cls = _VARIANTS[direction].get(variant)
    if cls is None:
        return None
    required = {"type", "version", "launch_id"}
    optional: set[str] = set()
    match variant:
        case "RequestBootstrapToken":
            required.add("request_id")
        case "Ready":
            required.add("authority")
        case "Failure":
            required.add("code")
        case "Stopped":
            required.add("clean")
        case "Notice":
            required.update(("event_id", "kind", "language"))
            optional.update(("task_id", "request_id"))
        case "BootstrapToken":
            required.update(("request_id", "token"))
    if not required <= values.keys() or values.keys() - required - optional:
        return None
    if type(values["version"]) is not int or values["version"] != 1:
        return None
    for name in ("launch_id", "request_id", "event_id", "task_id"):
        if name in values and not (name in optional and values[name] is None):
            if not _uuid(values[name]):
                return None
    if variant == "Ready" and values["authority"] != "127.0.0.1:7842":
        return None
    if variant == "Stopped" and type(values["clean"]) is not bool:
        return None
    if variant == "Failure":
        if not isinstance(values["code"], str) or values["code"] not in ERROR_CODES:
            return None
    if variant == "Notice":
        if values["kind"] not in ("quarantine", "approval_pending"):
            return None
        if values["language"] not in ("en", "fr"):
            return None
    if variant == "BootstrapToken":
        token = values["token"]
        if not isinstance(token, str) or not token or any(ord(c) < 32 for c in token):
            return None
    return cls(**values)


def decode_frame(data: bytes, *, direction: Direction) -> Frame:
    """Decode one complete frame, checking byte bounds before UTF-8/JSON."""
    limit = MAX_CREDENTIAL_BYTES if direction == "credential" else MAX_CONTROL_BYTES
    if len(data) > limit or not data.endswith(b"\n") or b"\n" in data[:-1]:
        raise ProtocolError()
    frame = _parse(data[:-1], direction)
    if frame is None:
        raise ProtocolError()
    return frame


def encode_frame(frame: Frame) -> bytes:
    """Validate outgoing frames by the same rules as incoming frames."""
    direction: Direction = (
        "credential" if isinstance(frame, BootstrapToken)
        else "parent" if isinstance(frame, (Stop, RequestBootstrapToken)) else "child"
    )
    # Stable field order is irrelevant on the wire; secrets are never logged.
    data = json.dumps(asdict(frame), separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    decode_frame(data, direction=direction)
    return data


class FrameDecoder:
    """Incremental decoder with a per-frame bound, including before newline."""

    def __init__(self, *, direction: Direction) -> None:
        self._direction = direction
        self._limit = MAX_CREDENTIAL_BYTES if direction == "credential" else MAX_CONTROL_BYTES
        self._buffer = bytearray()
        self._failed = False

    def feed(self, data: bytes) -> list[Frame]:
        if self._failed:
            raise ProtocolError()
        frames: list[Frame] = []
        offset = 0
        try:
            while offset < len(data):
                newline = data.find(b"\n", offset)
                end = len(data) if newline == -1 else newline + 1
                size = end - offset
                if len(self._buffer) + size > self._limit:
                    raise ProtocolError()
                self._buffer.extend(memoryview(data)[offset:end])
                offset = end
                if newline == -1:
                    if len(self._buffer) >= self._limit:
                        raise ProtocolError()
                else:
                    frames.append(decode_frame(bytes(self._buffer), direction=self._direction))
                    self._buffer.clear()
        except ProtocolError:
            self._buffer.clear()
            self._failed = True
            raise
        return frames

    def finish(self) -> None:
        if self._buffer or self._failed:
            self._buffer.clear()
            self._failed = True
            raise ProtocolError()


class ProtocolSession:
    """Generation/one-shot checks layered above strict wire validation."""

    def __init__(self, launch_id: str) -> None:
        if not _uuid(launch_id):
            raise ProtocolError()
        self.launch_id = launch_id
        self._ready = False
        self._closed = False
        self._request: str | None = None

    def accept_child(self, frame: Frame) -> None:
        if self._closed or frame.launch_id != self.launch_id:
            raise ProtocolError()
        if not isinstance(frame, (Ready, Failure, Stopped, Notice)):
            raise ProtocolError()
        if isinstance(frame, Ready):
            if self._ready:
                raise ProtocolError()
            self._ready = True

    def request_token(self, request_id: str) -> None:
        if self._closed or self._request is not None or not _uuid(request_id):
            raise ProtocolError()
        self._request = request_id

    def accept_token(self, frame: BootstrapToken) -> None:
        if (self._closed or frame.launch_id != self.launch_id
                or self._request is None or frame.request_id != self._request):
            raise ProtocolError()
        self._request = None

    def cancel_token(self) -> None:
        self._request = None

    def close(self) -> None:
        self._closed = True
        self._request = None
