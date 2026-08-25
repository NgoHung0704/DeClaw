"""Group parser blocks into ~512-token chunks that can each be cited.

Two rules shape the output:

* blocks MAY merge across pages — the chunk records the first and last page, so
  a citation reads "p.12" or "p.12-13". Uniform chunk sizes matter more than
  pinning each chunk to a single page;
* blocks NEVER merge across sheets, because a spreadsheet sheet is a separate
  context and a merged chunk would cite two places at once.

Token counting is ceil(chars / 3), the same conservative constant as
declaw/brain/context.py (_CHARS_PER_TOKEN). Core's estimate_tokens takes
messages rather than text, and this plugin cannot import declaw anyway, so the
one-line formula lives here with core named as its source.
"""

from __future__ import annotations

import re

from models import Block, Chunk

CHARS_PER_TOKEN = 3
DEFAULT_TARGET_TOKENS = 512

# Split after . ! ? or a newline, keeping the delimiter with the sentence.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: ceil(chars / 3)."""
    return -(-len(text) // CHARS_PER_TOKEN)


def _split_oversized(text: str, target_tokens: int) -> list[str]:
    """Break one too-large block into target-sized pieces."""
    limit = target_tokens * CHARS_PER_TOKEN
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_RE.split(text):
        if not sentence:
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) <= limit or not buffer:
            buffer = candidate
        else:
            pieces.append(buffer)
            buffer = sentence
        # A single sentence longer than the limit: hard-split it.
        while len(buffer) > limit:
            pieces.append(buffer[:limit])
            buffer = buffer[limit:]
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_blocks(
    blocks: list[Block], *, target_tokens: int = DEFAULT_TARGET_TOKENS
) -> list[Chunk]:
    """Turn parser blocks into ordered, citable chunks."""
    chunks: list[Chunk] = []
    pending: list[Block] = []

    def flush() -> None:
        if not pending:
            return
        text = "\n".join(b.text for b in pending)
        pages = [b.page for b in pending if b.page is not None]
        heading = next((b.heading for b in pending if b.heading), None)
        chunks.append(
            Chunk(
                text=text,
                ordinal=len(chunks),
                page=pages[0] if pages else None,
                page_end=pages[-1] if pages else None,
                sheet=pending[0].sheet,
                heading=heading,
            )
        )
        pending.clear()

    for block in blocks:
        if not block.text.strip():
            continue
        # A new sheet always starts a new chunk.
        if pending and pending[0].sheet != block.sheet:
            flush()
        if estimate_tokens(block.text) > target_tokens:
            flush()
            for piece in _split_oversized(block.text, target_tokens):
                pending.append(
                    Block(text=piece, page=block.page, sheet=block.sheet, heading=block.heading)
                )
                flush()
            continue
        projected = estimate_tokens("\n".join([*(b.text for b in pending), block.text]))
        if pending and projected > target_tokens:
            flush()
        pending.append(block)

    flush()
    return chunks
