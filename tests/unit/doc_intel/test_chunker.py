"""Blocks in, ~512-token chunks out."""

from __future__ import annotations

from chunker import chunk_blocks, estimate_tokens
from models import Block


def _block(text: str, **kw: object) -> Block:
    return Block(text=text, **kw)  # type: ignore[arg-type]


def test_estimate_tokens_matches_the_core_heuristic() -> None:
    # ceil(chars / 3), same constant as declaw/brain/context.py.
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 2
    assert estimate_tokens("") == 0


def test_small_blocks_merge_into_one_chunk() -> None:
    blocks = [_block("alpha"), _block("beta"), _block("gamma")]
    chunks = chunk_blocks(blocks, target_tokens=512)
    assert len(chunks) == 1
    assert "alpha" in chunks[0].text and "gamma" in chunks[0].text


def test_ordinals_are_sequential_from_zero() -> None:
    blocks = [_block("x" * 900) for _ in range(4)]
    chunks = chunk_blocks(blocks, target_tokens=100)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_no_chunk_exceeds_the_target_when_blocks_are_small() -> None:
    blocks = [_block("word " * 20) for _ in range(50)]
    chunks = chunk_blocks(blocks, target_tokens=200)
    assert all(estimate_tokens(c.text) <= 200 for c in chunks)


def test_a_chunk_spanning_pages_records_both_ends() -> None:
    blocks = [_block("alpha", page=1), _block("beta", page=2)]
    (chunk,) = chunk_blocks(blocks, target_tokens=512)
    assert chunk.page == 1
    assert chunk.page_end == 2


def test_a_single_page_chunk_has_matching_ends() -> None:
    (chunk,) = chunk_blocks([_block("alpha", page=7)], target_tokens=512)
    assert chunk.page == 7 and chunk.page_end == 7


def test_sheets_never_merge() -> None:
    # A spreadsheet sheet is a separate context; merging would produce a
    # citation that points at two places at once.
    blocks = [_block("a", sheet="Budget"), _block("b", sheet="Ventes")]
    chunks = chunk_blocks(blocks, target_tokens=512)
    assert len(chunks) == 2
    assert [c.sheet for c in chunks] == ["Budget", "Ventes"]


def test_an_oversized_block_is_split_on_sentence_boundaries() -> None:
    sentences = " ".join(f"Phrase numero {i} du contrat." for i in range(200))
    chunks = chunk_blocks([_block(sentences)], target_tokens=100)
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 120 for c in chunks)  # small overshoot tolerated
    # Nothing is lost.
    assert "Phrase numero 0 " in chunks[0].text
    assert "199" in chunks[-1].text


def test_a_block_with_no_sentence_boundaries_is_hard_split() -> None:
    chunks = chunk_blocks([_block("x" * 2000)], target_tokens=100)
    assert len(chunks) > 1
    assert sum(len(c.text) for c in chunks) == 2000


def test_heading_comes_from_the_first_block_that_has_one() -> None:
    blocks = [_block("intro"), _block("body", heading="Article 3")]
    (chunk,) = chunk_blocks(blocks, target_tokens=512)
    assert chunk.heading == "Article 3"


def test_empty_and_whitespace_blocks_are_dropped() -> None:
    assert chunk_blocks([_block("   "), _block("")], target_tokens=512) == []


def test_average_chunk_size_is_within_15_percent_of_target() -> None:
    # DCL-105's acceptance. Measured over non-final chunks: the last chunk of
    # a document is a remainder by construction and would skew the mean down.
    blocks = [_block("mot " * 30) for _ in range(200)]
    chunks = chunk_blocks(blocks, target_tokens=512)
    assert len(chunks) > 3
    sizes = [estimate_tokens(c.text) for c in chunks[:-1]]
    average = sum(sizes) / len(sizes)
    assert 512 * 0.85 <= average <= 512 * 1.15
