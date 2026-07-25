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


@pytest.mark.parametrize("language", ["en", "fr"])
def test_prompt_keeps_the_worked_examples(language: str) -> None:
    """The few-shot block is load-bearing, not decoration (see module docstring).

    Without it, qwen2.5:3b quarantines ordinary documents that merely contain a
    password or an IBAN — measured 17.9% false positives vs 7.5% with it. A
    well-meaning tidy-up of the prompt would silently reintroduce that.
    """
    prompt = sanitizer_system_prompt(language)  # type: ignore[arg-type]
    assert "CONTENT:" in prompt or "CONTENU :" in prompt
    # Both sides of the boundary must be demonstrated, or the model only learns one.
    assert prompt.count("-> SAFE") >= 3
    assert prompt.count("-> UNSAFE") >= 3
    # The sensitivity rule itself must survive too.
    assert "SENSITIVITY IS NOT A THREAT" in prompt or "N'EST PAS UNE MENACE" in prompt


@pytest.mark.parametrize("language", ["en", "fr"])
def test_prompt_examples_are_not_corpus_samples(language: str) -> None:
    """Never teach to the test: the benchmark corpus must stay an unseen set.

    If a prompt example is also a corpus sample, DCL-047/048 stops measuring
    generalization and starts measuring recall of the prompt.
    """
    from declaw.sanitizer.corpus import BENIGN_CORPUS, INJECTION_CORPUS

    prompt = sanitizer_system_prompt(language)  # type: ignore[arg-type]
    for sample in (*BENIGN_CORPUS, *INJECTION_CORPUS):
        assert sample.text not in prompt, f"corpus sample leaked into the prompt: {sample.text!r}"


def test_system_message_wrapper() -> None:
    msg = sanitizer_system_message("en")
    assert isinstance(msg, SystemMessage)
    assert msg.content == sanitizer_system_prompt("en")


def test_wrap_untrusted_fences_content() -> None:
    wrapped = wrap_untrusted("hello world")
    assert wrapped.startswith(CONTENT_START)
    assert wrapped.endswith(CONTENT_END)
    assert "hello world" in wrapped
