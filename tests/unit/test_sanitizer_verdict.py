"""Unit tests for the SanitizerVerdict schema (DCL-042)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from declaw.sanitizer.verdict import SanitizerVerdict, unsafe_fallback


def test_safe_verdict_flags() -> None:
    v = SanitizerVerdict(verdict="SAFE", reason="ordinary text")
    assert v.is_safe is True
    assert v.is_unsafe is False


def test_unsafe_verdict_flags() -> None:
    v = SanitizerVerdict(verdict="UNSAFE", reason="ignore-previous-instructions")
    assert v.is_safe is False
    assert v.is_unsafe is True


def test_verdict_must_be_one_of_the_literals() -> None:
    # Acceptance (DCL-042): outputs outside the SAFE/UNSAFE schema are rejected.
    with pytest.raises(ValidationError):
        SanitizerVerdict(verdict="MAYBE", reason="x")  # type: ignore[arg-type]


def test_reason_is_required() -> None:
    with pytest.raises(ValidationError):
        SanitizerVerdict(verdict="SAFE")  # type: ignore[call-arg]


def test_verdict_is_frozen() -> None:
    v = SanitizerVerdict(verdict="SAFE", reason="ok")
    with pytest.raises(ValidationError):
        v.verdict = "UNSAFE"  # type: ignore[misc]


def test_roundtrip_json() -> None:
    v = SanitizerVerdict(verdict="UNSAFE", reason="jailbreak attempt")
    restored = SanitizerVerdict.model_validate_json(v.model_dump_json())
    assert restored == v


def test_unsafe_fallback_is_fail_closed() -> None:
    v = unsafe_fallback("model timed out")
    assert v.is_unsafe is True
    assert "timed out" in v.reason
