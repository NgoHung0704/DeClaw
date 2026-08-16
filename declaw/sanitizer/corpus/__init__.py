"""Locked sanitizer corpora (DCL-046).

Two sets with different jobs — do not merge them:

* :data:`INJECTION_CORPUS` / :data:`BENIGN_CORPUS` — the **development** corpus,
  written in this repo (EN + FR). Prompt few-shot examples may be inspired by it,
  so scores on it measure "did we keep what we tuned for", not generalization.
* :data:`HELDOUT_INJECTIONS` / :data:`HELDOUT_BENIGN` — an **unseen** set built
  from external text (EN + DE). Nothing here may ever appear in a prompt. The
  gap between the two scores is the overfitting measure: on 2026-07-26 it was
  91.7% on the development corpus vs ~70% on outside data.
"""

from __future__ import annotations

from declaw.sanitizer.corpus.benign import BENIGN_CORPUS
from declaw.sanitizer.corpus.heldout import HELDOUT_BENIGN, HELDOUT_INJECTIONS
from declaw.sanitizer.corpus.injections import INJECTION_CORPUS
from declaw.sanitizer.corpus.models import BenignSample, InjectionSample, Severity

__all__ = [
    "BENIGN_CORPUS",
    "HELDOUT_BENIGN",
    "HELDOUT_INJECTIONS",
    "INJECTION_CORPUS",
    "BenignSample",
    "InjectionSample",
    "Severity",
]
