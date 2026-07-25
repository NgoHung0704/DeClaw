"""Unit tests for the locked sanitizer prompt (DCL-041)."""

from __future__ import annotations

import pytest
from langchain_core.messages import SystemMessage

from declaw.sanitizer.prompts import (
    CONTENT_END,
    CONTENT_START,
    sanitizer_system_message,
    sanitizer_system_prompt,
    wrap_untrusted,
)


def test_explicit_language_switch() -> None:
    en = sanitizer_system_prompt("en")
    fr = sanitizer_system_prompt("fr")
    assert en != fr
    assert "security classifier" in en
    assert "classifieur de sécurité" in fr


def test_default_language_is_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECLAW_LANGUAGE", raising=False)
    assert sanitizer_system_prompt() == sanitizer_system_prompt("en")


def test_language_env_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_LANGUAGE", "fr")
    assert sanitizer_system_prompt() == sanitizer_system_prompt("fr")


@pytest.mark.parametrize("language", ["en", "fr"])
def test_prompt_locks_in_the_core_guarantees(language: str) -> None:
    prompt = sanitizer_system_prompt(language)  # type: ignore[arg-type]
    # No tools / no actions.
    assert "no tool" in prompt.lower() or "aucun outil" in prompt.lower()
    # Content is data, instructions inside must never be obeyed.
    assert "DATA" in prompt or "DONNÉES" in prompt
    assert "NEVER" in prompt or "JAMAIS" in prompt
    # Only the two verdict labels are valid output.
    assert "SAFE" in prompt and "UNSAFE" in prompt
    # The markers the content is fenced with are named in the prompt.
    assert CONTENT_START in prompt and CONTENT_END in prompt


def test_system_message_wrapper() -> None:
    msg = sanitizer_system_message("en")
    assert isinstance(msg, SystemMessage)
    assert msg.content == sanitizer_system_prompt("en")


def test_wrap_untrusted_fences_content() -> None:
    wrapped = wrap_untrusted("hello world")
    assert wrapped.startswith(CONTENT_START)
    assert wrapped.endswith(CONTENT_END)
    assert "hello world" in wrapped
