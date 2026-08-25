"""The plugin-side dispatch loop, driven without a real subprocess."""

from __future__ import annotations

import json
from typing import Any

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


def _drive(*lines: bytes) -> list[dict[str, Any]]:
    """Feed lines to run() and collect the frames it writes back."""
    inbox = list(lines) + [b""]
    written: list[dict[str, Any]] = []

    def read_line() -> bytes:
        return inbox.pop(0)

    def write_frame(data: bytes) -> None:
        assert data.endswith(b"\n")
        written.append(json.loads(data))

    run(Sample(), read_line=read_line, write_frame=write_frame)
    return written


def _request(method: str, **params: Any) -> bytes:
    return RequestFrame(id="r1", method=method, params=params).model_dump_json().encode() + b"\n"


def test_describe_returns_the_plugin_identity() -> None:
    (frame,) = _drive(_request("describe"))
    assert frame["ok"] is True
    assert frame["result"]["name"] == "sample"


def test_invoke_runs_the_capability() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={"message": "bonjour"}))
    assert frame["ok"] is True
    assert frame["result"] == "bonjour"


def test_invoke_uses_declared_defaults() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={}))
    assert frame["result"] == "hi"


def test_unknown_capability_is_reported_not_crashed() -> None:
    (frame,) = _drive(_request("invoke", capability="nope", args={}))
    assert frame["error"]["code"] == "unknown_capability"


def test_invalid_args_are_rejected_before_the_capability_runs() -> None:
    (frame,) = _drive(_request("invoke", capability="echo", args={"message": 42}))
    assert frame["error"]["code"] == "invalid_args"


def test_a_raising_capability_becomes_an_error_frame() -> None:
    (frame,) = _drive(_request("invoke", capability="boom", args={}))
    assert frame["error"]["code"] == "capability_failed"
    assert "exploded on purpose" in frame["error"]["message"]


def test_oversized_result_is_refused_rather_than_written() -> None:
    (frame,) = _drive(_request("invoke", capability="huge", args={}))
    assert frame["error"]["code"] == "result_too_large"


def test_unknown_method_is_reported_distinctly() -> None:
    # Built by hand: RequestFrame would reject an unknown method at construction.
    # The distinct code is what tells a newer host it is talking to an older
    # plugin, rather than that the frame was garbage.
    (frame,) = _drive(b'{"v": 1, "id": "r1", "method": "destroy", "params": {}}\n')
    assert frame["error"]["code"] == "unknown_method"
    assert frame["id"] == "r1"  # echoed, so the host can match it to its request


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
