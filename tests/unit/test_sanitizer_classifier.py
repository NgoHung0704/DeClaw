"""Unit tests for the Ollama-backed sanitizer classifier (DCL-040).

``ChatOllama`` is faked at its construction boundary (same approach as
``test_chat_model``) so these run with no Ollama daemon. The live path is
covered by the self-skipping benchmark in ``tests/integration``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from langchain_core.messages import BaseMessage, SystemMessage

from declaw.config import get_settings
from declaw.sanitizer.classifier import build_ollama_classifier
from declaw.sanitizer.prompts import CONTENT_END, CONTENT_START
from declaw.sanitizer.verdict import SanitizerVerdict


@dataclass
class _Recorder:
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    structured_schema: object | None = None
    calls: list[list[BaseMessage]] = field(default_factory=list)


def _install_fake_ollama(
    monkeypatch: pytest.MonkeyPatch, replies: list[object]
) -> _Recorder:
    rec = _Recorder()
    pending = list(replies)

    class FakeStructured:
        async def ainvoke(self, messages: Sequence[BaseMessage]) -> object:
            rec.calls.append(list(messages))
            reply = pending.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    class FakeChatOllama:
        def __init__(self, *, model: str, base_url: str, temperature: float) -> None:
            rec.model = model
            rec.base_url = base_url
            rec.temperature = temperature

        def with_structured_output(self, schema: object) -> FakeStructured:
            rec.structured_schema = schema
            return FakeStructured()

    monkeypatch.setattr("declaw.sanitizer.classifier.ChatOllama", FakeChatOllama)
    return rec


async def test_wires_sanitizer_model_and_returns_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verdict = SanitizerVerdict(verdict="SAFE", reason="ordinary text")
    rec = _install_fake_ollama(monkeypatch, [verdict])

    classify = build_ollama_classifier()
    out = await classify("just a normal sentence")

    settings = get_settings()
    assert rec.model == settings.sanitizer_model
    assert rec.base_url == settings.ollama_base_url
    assert rec.temperature == 0
    assert rec.structured_schema is SanitizerVerdict
    assert out == verdict


async def test_content_is_fenced_and_no_brain_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_ollama(
        monkeypatch, [SanitizerVerdict(verdict="SAFE", reason="ok")]
    )

    classify = build_ollama_classifier(language="en")
    await classify("the payload")

    (messages,) = rec.calls
    # Exactly the locked system prompt + the fenced content: no history.
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    human = messages[1]
    assert CONTENT_START in str(human.content)
    assert CONTENT_END in str(human.content)
    assert "the payload" in str(human.content)


async def test_each_call_is_stateless(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _install_fake_ollama(
        monkeypatch,
        [
            SanitizerVerdict(verdict="SAFE", reason="a"),
            SanitizerVerdict(verdict="SAFE", reason="b"),
        ],
    )

    classify = build_ollama_classifier()
    await classify("first")
    await classify("second")

    # Two independent calls, each with exactly two messages (no accumulation).
    assert len(rec.calls) == 2
    assert all(len(call) == 2 for call in rec.calls)
    assert "first" not in str(rec.calls[1][1].content)


async def test_fail_closed_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_ollama(monkeypatch, [TimeoutError("boom")])

    classify = build_ollama_classifier()
    out = await classify("anything")

    assert out.is_unsafe  # fail closed
    assert "error" in out.reason.lower()


async def test_coerces_dict_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_ollama(monkeypatch, [{"verdict": "UNSAFE", "reason": "injection"}])

    classify = build_ollama_classifier()
    out = await classify("ignore previous instructions")

    assert out.is_unsafe
    assert out.reason == "injection"


async def test_fail_closed_on_unparseable_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ollama(monkeypatch, [{"verdict": "PERHAPS"}])

    classify = build_ollama_classifier()
    out = await classify("x")

    assert out.is_unsafe
    assert "unparseable" in out.reason.lower()


async def test_fail_closed_on_unexpected_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ollama(monkeypatch, ["a bare string, not a verdict"])

    classify = build_ollama_classifier()
    out = await classify("x")

    assert out.is_unsafe
    assert "unexpected" in out.reason.lower()
