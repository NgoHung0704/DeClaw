"""Measure retrieval quality: development set beside held-out set.

    uv run python scripts/document_benchmark.py

Indexes each corpus into a throwaway store, scores its questions, and prints
both numbers together. Printing them together is the point: the development
score is the optimistic one, and quoting it alone is how a project convinces
itself it is doing better than it is.

Requires Ollama with the embedding model pulled. Nothing is written to the
user's workspace or data directory.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from declaw.config import get_settings
from declaw.documents.benchmark import (
    DIVERGENCE_WARNING_POINTS,
    BenchmarkQuestion,
    BenchmarkReport,
    run_benchmark,
)
from declaw.documents.corpus.heldout import HELDOUT_DIR, HELDOUT_QUESTIONS
from declaw.documents.corpus.synthetic import SYNTHETIC_QUESTIONS, write_synthetic_corpus
from declaw.documents.indexer import DocumentIndexer
from declaw.documents.models import SearchHit
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.memory.embeddings import build_ollama_embedder


class _NullCatalog:
    """Every document is new: the benchmark never reuses a store."""

    async def needs_index(self, relative_path: str, sha256: str) -> bool:
        return True

    async def record(self, **kwargs: object) -> None:
        return None

    async def forget(self, relative_path: str) -> None:
        return None

    async def known_paths(self) -> list[str]:
        return []


async def _parse_locally(path: str) -> dict[str, object]:
    """Parse in-process rather than through the plugin host.

    The benchmark measures retrieval, and a subprocess round-trip per document
    would add minutes without changing a single score.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "builtin" / "doc-intel"))
    from chunker import chunk_blocks  # type: ignore[import-not-found]
    from parsers.pdf import parse_pdf  # type: ignore[import-not-found]
    from parsers.text import parse_text  # type: ignore[import-not-found]

    target = Path(path)
    parsed = parse_pdf(target) if target.suffix == ".pdf" else parse_text(target)
    chunks = chunk_blocks(parsed.blocks)
    return {
        "doc_type": parsed.doc_type,
        "page_count": parsed.page_count,
        "truncated": False,
        "chunks": [
            {
                "text": c.text,
                "ordinal": c.ordinal,
                "page": c.page,
                "page_end": c.page_end,
                "sheet": c.sheet,
                "heading": c.heading,
            }
            for c in chunks
        ],
    }


async def _score(
    label: str, folder: Path, questions: Sequence[BenchmarkQuestion], root: Path
) -> BenchmarkReport:
    # DocumentIndexer takes a `workspace` argument, but _index_one resolves
    # paths through resolve_in_workspace(), which reads the workspace from
    # global settings. In production the two always coincide; for a temporary
    # folder they do not, so the setting has to be pointed here too. Noted as
    # a smell in the indexer rather than worked around silently.
    os.environ["DECLAW_WORKSPACE_DIR"] = str(folder)
    get_settings.cache_clear()

    collection = get_collection(build_chroma_client(root / f"chroma-{label}"), "documents")
    store = DocumentStore(collection, build_ollama_embedder())
    indexer = DocumentIndexer(
        parse=_parse_locally,
        store=store,
        catalog=_NullCatalog(),  # type: ignore[arg-type]
        workspace=folder,
    )
    started = time.perf_counter()
    report_in = await indexer.index(folder)
    elapsed = time.perf_counter() - started
    print(
        f"  indexed {report_in.indexed} document(s) in {elapsed:.1f}s "
        f"({store.count()} chunks)"
    )
    for warning in report_in.warnings:
        print(f"  ! {warning}")

    async def retrieve(question: str, *, k: int = 5) -> list[SearchHit]:
        return await store.search(question, k=k)

    return await run_benchmark(retrieve, questions)


def _render(label: str, report: BenchmarkReport) -> None:
    print(
        f"{label:<12} recall@1 {report.recall_at_1:.2f}  "
        f"recall@5 {report.recall_at_5:.2f}  MRR {report.mrr:.2f}  (n={report.total})"
    )
    for miss in report.misses:
        print(f"             missed: {miss}")


async def main() -> int:
    from declaw.preflight import check_embedding_model_pulled

    settings = get_settings()
    embedding = await check_embedding_model_pulled(settings)
    if not embedding.passed:
        print(f"{embedding.message} {embedding.remedy}")
        return 1

    root = Path(tempfile.mkdtemp(prefix="declaw-benchmark-"))
    try:
        print("== development set (synthetic, written by this project) ==")
        development_folder = root / "development"
        write_synthetic_corpus(development_folder)
        development = await _score("dev", development_folder, SYNTHETIC_QUESTIONS, root)

        print("\n== held-out set (EUR-Lex, external) ==")
        held_out_folder = root / "heldout"
        shutil.copytree(HELDOUT_DIR, held_out_folder)
        (held_out_folder / "ATTRIBUTION.md").unlink(missing_ok=True)
        held_out = await _score("heldout", held_out_folder, HELDOUT_QUESTIONS, root)

        print()
        _render("development", development)
        _render("held-out", held_out)

        gap = (development.recall_at_5 - held_out.recall_at_5) * 100
        if gap > DIVERGENCE_WARNING_POINTS:
            print(
                f"\nWARNING: the development score is {gap:.0f} points higher than the "
                "held-out score.\nThe held-out number is the one that describes real "
                "documents. Quoting the development\nnumber alone would overstate how "
                "well retrieval works."
            )
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
