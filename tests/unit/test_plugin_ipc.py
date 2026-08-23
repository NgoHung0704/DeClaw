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
