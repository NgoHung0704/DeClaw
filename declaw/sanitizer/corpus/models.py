"""Typed corpus sample models (DCL-046).

Two sample kinds, both frozen + hashable so the corpus can be used directly as
``pytest.mark.parametrize`` ids:

* :class:`InjectionSample` — a known-malicious payload the sanitizer must rule
  UNSAFE, tagged with a severity and a category.
* :class:`BenignSample` — ordinary professional content the sanitizer must rule
  SAFE, used to measure the false-positive rate (DCL-047).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from declaw.config import Language

# Rough blast radius if the injection succeeded. Used for reporting and to let
# the benchmark weight critical misses.
Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class InjectionSample:
    """A malicious payload. Expected verdict: UNSAFE."""

    text: str
    language: Language
    severity: Severity
    category: str


@dataclass(frozen=True, slots=True)
class BenignSample:
    """Ordinary content. Expected verdict: SAFE."""

    text: str
    language: Language
    category: str
