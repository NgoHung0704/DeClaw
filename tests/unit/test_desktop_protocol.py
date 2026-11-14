"""Fail-closed desktop IPC, independent of the native GUI/toolchain."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from declaw.desktop.protocol import (
    MAX_CONTROL_BYTES,
    MAX_CREDENTIAL_BYTES,
    BootstrapToken,
    FrameDecoder,
    ProtocolError,
    ProtocolSession,
    Ready,
    Stop,
    decode_frame,
    encode_frame,
)

LAUNCH = str(uuid4())
REQUEST = str(uuid4())


def wire(variant: str = "Ready", **fields: object) -> bytes:
    payload = {"type": variant, "version": 1, "launch_id": LAUNCH, **fields}
    return json.dumps(payload).encode() + b"\n"


def test_directional_roundtrip() -> None:
    for frame, direction in [
        (Ready(launch_id=LAUNCH, authority="127.0.0.1:7842"), "child"),
        (Stop(launch_id=LAUNCH), "parent"),
    ]:
        assert decode_frame(encode_frame(frame), direction=direction) == frame


@pytest.mark.parametrize("fields", [
    {"version": True}, {"version": 1.0}, {"version": "1"}, {"version": 2},
    {"launch_id": LAUNCH.upper()}, {"launch_id": "not-a-uuid"},
    {"authority": "localhost:7842"}, {"authority": "127.0.0.1:7843"},
    {"extra": "fake-secret"}, {"type": "Unknown"},
])
def test_invalid_fields_have_only_safe_error(fields: dict[str, object]) -> None:
    with pytest.raises(ProtocolError, match="^protocol_invalid$") as caught:
        decode_frame(wire(**{"authority": "127.0.0.1:7842", **fields}), direction="child")
    assert "fake-secret" not in repr(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("data", [
    b"\xff\n", b"[]\n", b"null\n", b"{\n", b"{}", b"{}\n{}\n",
    b'{"type":"Ready","type":"Stop"}\n',
])
def test_invalid_wire(data: bytes) -> None:
    with pytest.raises(ProtocolError, match="^protocol_invalid$"):
        decode_frame(data, direction="child")


def test_wrong_direction_and_secret_on_event_channel_are_rejected() -> None:
    for data in [wire("Stop"), wire("BootstrapToken", request_id=REQUEST, token="fake-secret")]:
        with pytest.raises(ProtocolError, match="^protocol_invalid$"):
            decode_frame(data, direction="child")


@pytest.mark.parametrize("fields", [
    {"kind": "other"}, {"language": "de"}, {"task_id": "filename.txt"},
    {"request_id": 42}, {"event_id": "bad"}, {"preview": "private"},
])
def test_notice_uses_only_closed_safe_fields(fields: dict[str, object]) -> None:
    values: dict[str, object] = {
        "event_id": str(uuid4()), "kind": "quarantine", "language": "en", **fields,
    }
    with pytest.raises(ProtocolError, match="^protocol_invalid$"):
        decode_frame(wire("Notice", **values), direction="child")


def test_stopped_clean_must_be_boolean_and_failure_code_is_closed() -> None:
    for data in [wire("Stopped", clean=1), wire("Failure", code="raw secret exception")]:
        with pytest.raises(ProtocolError):
            decode_frame(data, direction="child")


def test_decoder_handles_chunks_and_multiple_lines() -> None:
    decoder = FrameDecoder(direction="parent")
    data = wire("Stop")
    assert decoder.feed(data[:10]) == []
    assert decoder.feed(data[10:] + data) == [Stop(launch_id=LAUNCH)] * 2
    decoder.finish()


def test_decoder_bounds_unterminated_input_and_fails_closed_after_error() -> None:
    decoder = FrameDecoder(direction="parent")
    with pytest.raises(ProtocolError):
        decoder.feed(b"x" * MAX_CONTROL_BYTES)
    with pytest.raises(ProtocolError):
        decoder.feed(wire("Stop"))


def test_partial_eof_and_byte_limit_include_newline() -> None:
    decoder = FrameDecoder(direction="parent")
    decoder.feed(b"{")
    with pytest.raises(ProtocolError):
        decoder.finish()
    with pytest.raises(ProtocolError):
        decode_frame(b" " * MAX_CONTROL_BYTES + b"\n", direction="child")


def test_generation_and_duplicate_ready() -> None:
    session = ProtocolSession(LAUNCH)
    frame = decode_frame(wire(authority="127.0.0.1:7842"), direction="child")
    session.accept_child(frame)
    with pytest.raises(ProtocolError):
        session.accept_child(frame)
    with pytest.raises(ProtocolError):
        ProtocolSession(str(uuid4())).accept_child(frame)


def test_credential_request_is_explicit_correlated_single_use_and_redacted() -> None:
    session = ProtocolSession(LAUNCH)
    token = BootstrapToken(launch_id=LAUNCH, request_id=REQUEST, token="fake-secret")
    assert "fake-secret" not in repr(token)
    with pytest.raises(ProtocolError):
        session.accept_token(token)
    session.request_token(REQUEST)
    session.accept_token(token)
    with pytest.raises(ProtocolError):
        session.accept_token(token)
    session.request_token(str(uuid4()))
    session.close()
    with pytest.raises(ProtocolError):
        session.accept_token(token)


def test_credential_pipe_has_smaller_limit_and_direction() -> None:
    data = wire("BootstrapToken", request_id=REQUEST, token="fake-secret")
    frame = decode_frame(data, direction="credential")
    assert isinstance(frame, BootstrapToken)
    assert json.loads(encode_frame(frame)) == json.loads(data)
    with pytest.raises(ProtocolError):
        decode_frame(wire("Stop"), direction="credential")
    with pytest.raises(ProtocolError):
        decode_frame(wire("BootstrapToken", request_id=REQUEST,
                          token="x" * MAX_CREDENTIAL_BYTES), direction="credential")
