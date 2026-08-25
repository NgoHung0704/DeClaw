"""Recall and MRR arithmetic, with a fake retriever so the numbers are exact."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from declaw.documents.benchmark import (
    DIVERGENCE_WARNING_POINTS,
    BenchmarkQuestion,
    run_benchmark,
)
from declaw.documents.models import SearchHit


def _hit(path: str, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=f"{path}:0", doc_id=path, path=path, text=text, ordinal=0, distance=0.1
    )


def _question(path: str = "contrat.pdf", snippet: str = "preavis") -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question="Quel est le preavis ?",
        expected_path=path,
        expected_snippet=snippet,
        language="fr",
    )


def _retriever(
    results: dict[str, list[SearchHit]],
) -> Callable[..., Awaitable[list[SearchHit]]]:
    async def retrieve(question: str, *, k: int = 5) -> list[SearchHit]:
        return results.get(question, [])[:k]

    return retrieve


async def test_a_first_place_hit_scores_perfectly() -> None:
    question = _question()
    report = await run_benchmark(
        _retriever({question.question: [_hit("contrat.pdf", "le preavis est de trois mois")]}),
        [question],
    )
    assert report.recall_at_1 == 1.0
    assert report.recall_at_5 == 1.0
    assert report.mrr == 1.0
    assert report.misses == []


async def test_a_third_place_hit_counts_for_recall_at_5_not_at_1() -> None:
    question = _question()
    hits = [
        _hit("autre.pdf", "sans rapport"),
        _hit("encore.pdf", "sans rapport"),
        _hit("contrat.pdf", "le preavis est de trois mois"),
    ]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_1 == 0.0
    assert report.recall_at_5 == 1.0
    assert report.mrr == 1 / 3


async def test_the_right_file_with_the_wrong_passage_is_not_a_hit() -> None:
    # Matching the document for the wrong reason must not score.
    question = _question(snippet="preavis")
    hits = [_hit("contrat.pdf", "clause de confidentialite")]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_5 == 0.0
    assert report.misses == [question.question]


async def test_snippet_matching_ignores_case_and_accents() -> None:
    question = _question(snippet="préavis")
    hits = [_hit("contrat.pdf", "LE PREAVIS EST DE TROIS MOIS")]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_5 == 1.0


async def test_no_results_is_a_miss_not_a_crash() -> None:
    question = _question()
    report = await run_benchmark(_retriever({}), [question])
    assert report.recall_at_5 == 0.0
    assert report.mrr == 0.0
    assert report.misses == [question.question]


async def test_scores_average_across_questions() -> None:
    first = BenchmarkQuestion("A?", "a.pdf", "alpha", "fr")
    second = BenchmarkQuestion("B?", "b.pdf", "beta", "fr")
    report = await run_benchmark(
        _retriever(
            {
                "A?": [_hit("a.pdf", "alpha here")],
                "B?": [_hit("wrong.pdf", "nothing")],
            }
        ),
        [first, second],
    )
    assert report.recall_at_5 == 0.5
    assert report.mrr == 0.5
    assert report.misses == ["B?"]


async def test_an_empty_question_set_scores_zero_without_dividing_by_zero() -> None:
    report = await run_benchmark(_retriever({}), [])
    assert report.recall_at_5 == 0.0
    assert report.total == 0


def test_the_divergence_threshold_is_five_points() -> None:
    # Same shape as the sanitizer benchmark's seen-vs-unseen warning.
    assert DIVERGENCE_WARNING_POINTS == 5.0
