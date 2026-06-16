"""Integrity tests for the locked sanitizer corpora (DCL-046)."""

from __future__ import annotations

from declaw.sanitizer.corpus import BENIGN_CORPUS, INJECTION_CORPUS

_SEVERITIES = {"low", "medium", "high", "critical"}
_LANGUAGES = {"en", "fr"}


def test_injection_corpus_has_at_least_50() -> None:
    # Acceptance (DCL-046): 50+ known payloads.
    assert len(INJECTION_CORPUS) >= 50


def test_injection_corpus_is_bilingual() -> None:
    langs = {s.language for s in INJECTION_CORPUS}
    assert langs == _LANGUAGES
    assert sum(s.language == "en" for s in INJECTION_CORPUS) >= 20
    assert sum(s.language == "fr" for s in INJECTION_CORPUS) >= 20


def test_injection_samples_are_tagged() -> None:
    for s in INJECTION_CORPUS:
        assert s.severity in _SEVERITIES
        assert s.category  # non-empty category
        assert s.text.strip()


def test_injection_texts_are_unique() -> None:
    texts = [s.text for s in INJECTION_CORPUS]
    assert len(texts) == len(set(texts))


def test_injection_covers_key_categories() -> None:
    categories = {s.category for s in INJECTION_CORPUS}
    # The attack classes that matter most for DeClaw must all be represented.
    for required in (
        "ignore-instructions",
        "exfiltration",
        "tool-abuse",
        "network-exfil",
        "sanitizer-evasion",
    ):
        assert required in categories


def test_benign_corpus_is_substantial_and_bilingual() -> None:
    assert len(BENIGN_CORPUS) >= 40
    langs = {s.language for s in BENIGN_CORPUS}
    assert langs == _LANGUAGES


def test_benign_includes_hard_descriptive_mentions() -> None:
    # The corpus must stress the FP-prone cases (mentions AI/security/instructions).
    categories = {s.category for s in BENIGN_CORPUS}
    assert "mentions-ai" in categories
    assert "mentions-instructions" in categories
    assert "mentions-security" in categories


def test_corpora_do_not_overlap() -> None:
    injections = {s.text for s in INJECTION_CORPUS}
    benign = {s.text for s in BENIGN_CORPUS}
    assert injections.isdisjoint(benign)
