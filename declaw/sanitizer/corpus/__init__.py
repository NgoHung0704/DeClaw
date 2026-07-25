"""Locked sanitizer corpora (DCL-046).

* :data:`INJECTION_CORPUS` — known malicious payloads (EN + FR), expected UNSAFE.
* :data:`BENIGN_CORPUS` — ordinary professional content, expected SAFE, the
  denominator of the false-positive benchmark (DCL-047).
"""

from __future__ import annotations

from declaw.sanitizer.corpus.benign import BENIGN_CORPUS
from declaw.sanitizer.corpus.injections import INJECTION_CORPUS
from declaw.sanitizer.corpus.models import BenignSample, InjectionSample, Severity

__all__ = [
    "BENIGN_CORPUS",
    "INJECTION_CORPUS",
    "BenignSample",
    "InjectionSample",
    "Severity",
]
