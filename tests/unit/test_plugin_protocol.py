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
