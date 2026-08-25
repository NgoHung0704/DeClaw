"""Corpus integrity. The rules matter more than the contents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from declaw.documents.benchmark import BenchmarkQuestion, run_benchmark
from declaw.documents.corpus.heldout import HELDOUT_DIR, HELDOUT_QUESTIONS
from declaw.documents.corpus.synthetic import SYNTHETIC_QUESTIONS, write_synthetic_corpus
from declaw.documents.models import SearchHit


def _perfect_retriever(
    questions: tuple[BenchmarkQuestion, ...], bodies: dict[str, str]
) -> Callable[..., Awaitable[list[SearchHit]]]:
    """Return exactly the document each question expects, whole.

    Isolates the corpus from retrieval quality: with the right document served
    at rank 1, any miss here is a fault in the question or its snippet, never
    in the search.
    """
    by_question = {q.question: q.expected_path for q in questions}

    async def retrieve(question: str, *, k: int = 5) -> list[SearchHit]:
        path = by_question.get(question)
        if path is None:
            return []
        return [
            SearchHit(
                chunk_id=f"{path}:0",
                doc_id=path,
                path=path,
                text=bodies[path],
                ordinal=0,
                distance=0.0,
            )
        ]

    return retrieve


def test_the_development_set_has_at_least_ten_questions() -> None:
    # DCL-117 asks for 10+ sample contracts' worth of evaluation.
    assert len(SYNTHETIC_QUESTIONS) >= 10


def test_every_synthetic_question_names_a_generated_document(tmp_path: Path) -> None:
    # A question whose document is not in the corpus scores zero forever and
    # looks like a retrieval failure. Catch it here instead.
    written = write_synthetic_corpus(tmp_path)
    names = {p.name for p in written}
    for question in SYNTHETIC_QUESTIONS:
        assert question.expected_path in names, question.expected_path


def test_every_synthetic_snippet_really_appears_in_its_document(tmp_path: Path) -> None:
    # Same trap from the other side: a snippet that drifted out of the source
    # text would make the benchmark permanently unwinnable.
    from declaw.documents.corpus.synthetic import SYNTHETIC_DOCUMENTS

    bodies = {d.name: "\n".join(d.paragraphs) for d in SYNTHETIC_DOCUMENTS}
    for question in SYNTHETIC_QUESTIONS:
        body = bodies[question.expected_path]
        assert question.expected_snippet in body, question.expected_snippet


def test_the_corpus_is_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    a = {p.name for p in write_synthetic_corpus(first)}
    b = {p.name for p in write_synthetic_corpus(second)}
    assert a == b


def test_the_development_set_is_french() -> None:
    assert all(q.language == "fr" for q in SYNTHETIC_QUESTIONS)


def test_the_heldout_set_exists_and_is_attributed() -> None:
    # External text with a recorded source is the only thing that makes the
    # held-out number mean anything.
    attribution = HELDOUT_DIR / "ATTRIBUTION.md"
    assert attribution.is_file()
    text = attribution.read_text(encoding="utf-8")
    assert "eur-lex" in text.lower()
    assert "http" in text
    assert "CELEX" in text


def test_every_heldout_question_names_a_committed_file() -> None:
    for question in HELDOUT_QUESTIONS:
        assert (HELDOUT_DIR / question.expected_path).is_file(), question.expected_path


async def test_every_heldout_question_is_winnable() -> None:
    # Same contract for the external set. Real legal texts are full of
    # non-breaking spaces (2039 in the RGPD alone), which is why this asserts
    # the benchmark's own matching rule rather than raw containment.
    bodies = {
        question.expected_path: (HELDOUT_DIR / question.expected_path).read_text(
            encoding="utf-8"
        )
        for question in HELDOUT_QUESTIONS
    }
    report = await run_benchmark(
        _perfect_retriever(HELDOUT_QUESTIONS, bodies), HELDOUT_QUESTIONS
    )
    assert report.misses == []
    assert report.recall_at_1 == 1.0


def test_no_heldout_question_text_appears_in_the_development_set() -> None:
    # If a held-out question leaked into the development set, the gap between
    # the two scores would stop meaning anything.
    development = {q.question.casefold() for q in SYNTHETIC_QUESTIONS}
    for question in HELDOUT_QUESTIONS:
        assert question.question.casefold() not in development


def test_the_two_sets_do_not_share_documents() -> None:
    development = {q.expected_path for q in SYNTHETIC_QUESTIONS}
    heldout = {q.expected_path for q in HELDOUT_QUESTIONS}
    assert development.isdisjoint(heldout)
