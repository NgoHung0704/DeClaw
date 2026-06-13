"""Unit tests for the localized system prompt (DCL-017)."""

from __future__ import annotations

import pytest
from langchain_core.messages import SystemMessage

from declaw.brain.prompts import system_message, system_prompt


def test_language_switch_explicit() -> None:
    en = system_prompt("en")
    fr = system_prompt("fr")
    assert "Answer in English" in en
    assert "Répondez en français" in fr
    assert en != fr


def test_default_language_is_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECLAW_LANGUAGE", raising=False)
    assert system_prompt() == system_prompt("en")


def test_declaw_language_env_switches_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_LANGUAGE", "fr")
    assert system_prompt() == system_prompt("fr")  # the acceptance criterion


def test_prompt_embeds_seven_principles() -> None:
    for prompt in (system_prompt("en"), system_prompt("fr")):
        assert all(f"{i}." in prompt for i in range(1, 8))


def test_system_message_wraps_prompt() -> None:
    msg = system_message("fr")
    assert isinstance(msg, SystemMessage)
    assert msg.content == system_prompt("fr")
