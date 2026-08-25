"""Measure retrieval quality: does the right passage come back, and how high?

Retrieval, not answer quality. A 3B model's phrasing is a known and large
variable (Phase 1), and letting it into the measurement would swamp the signal
this is meant to produce.

A question counts as a hit only when the expected DOCUMENT appears in the top-k
AND the retrieved text contains the expected SNIPPET. Matching the right file
for the wrong reason is not a hit — otherwise a corpus of one document would
score perfectly.

Model-agnostic on purpose: ``run_benchmark`` takes a retrieve callable, so the
unit tests use a fake and the live runner passes the real store.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from declaw.documents.models import SearchHit

DEFAULT_K = 5
# Warn when the development and held-out scores diverge by more than this.
# Same shape as the sanitizer benchmark's seen-vs-unseen warning, and for the
# same reason: a self-authored corpus grades its own homework.
DIVERGENCE_WARNING_POINTS = 5.0

Retriever = Callable[..., Awaitable[list[SearchHit]]]


@dataclass(frozen=True, slots=True)
class BenchmarkQuestion:
    """One question with the passage that should answer it."""

    question: str
    expected_path: str
    expected_snippet: str
    language: str


@dataclass(frozen=True, slots=True)
class QuestionResult:
    """Where the expected passage landed. ``rank`` is 1-based, 0 means absent."""

    question: str
    rank: int


@dataclass(slots=True)
class BenchmarkReport:
    """Aggregate retrieval quality over one question set."""

    results: list[QuestionResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def recall_at_1(self) -> float:
        return self._recall(1)

    @property
    def recall_at_5(self) -> float:
        return self._recall(5)

    @property
    def mrr(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 / r.rank for r in self.results if r.rank > 0) / len(self.results)

    @property
    def misses(self) -> list[str]:
        return [r.question for r in self.results if r.rank == 0]

    def _recall(self, k: int) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if 0 < r.rank <= k) / len(self.results)


def _normalise(text: str) -> str:
    """Casefold and strip accents, so 'préavis' matches 'PREAVIS'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _rank_of(question: BenchmarkQuestion, hits: Sequence[SearchHit]) -> int:
    snippet = _normalise(question.expected_snippet)
    for position, hit in enumerate(hits, start=1):
        if hit.path != question.expected_path:
            continue
        if snippet in _normalise(hit.text):
            return position
    return 0


async def run_benchmark(
    retrieve: Retriever,
    questions: Sequence[BenchmarkQuestion],
    *,
    k: int = DEFAULT_K,
) -> BenchmarkReport:
    """Score ``questions`` against ``retrieve``."""
    report = BenchmarkReport()
    for question in questions:
        hits = await retrieve(question.question, k=k)
        report.results.append(
            QuestionResult(question=question.question, rank=_rank_of(question, hits))
        )
    return report
