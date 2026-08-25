"""Walk a folder, parse what changed, and store the result.

The indexer takes a ``parse`` callable rather than a ``PluginHost``: that keeps
it unit-testable with no subprocess, and lets Phase 9 route parsing differently
without touching this file.

Two invariants worth stating, because both protect the user from confidently
wrong answers later:

* the catalog is updated only AFTER chunks are stored, so a document that
  failed halfway is retried on the next run rather than remembered as done;
* a document that yielded no text (a scan) is reported out loud and NOT
  recorded as indexed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from declaw.documents.catalog import DocumentCatalog, file_sha256
from declaw.documents.models import DocumentChunk, document_id
from declaw.documents.store import DocumentStore
from declaw.log import logger
from declaw.tools.builtin._paths import WorkspacePathError, resolve_in_workspace

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".txt", ".md", ".markdown"})

ParseCallable = Callable[[str], Awaitable[dict[str, Any]]]
ProgressCallback = Callable[["IndexProgress"], None]


@dataclass(frozen=True, slots=True)
class IndexProgress:
    """One step of an indexing run, for a progress bar or a WebSocket frame."""

    done: int
    total: int
    path: str


@dataclass(slots=True)
class IndexReport:
    """What one indexing run did."""

    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)


def _to_chunks(raw: Sequence[dict[str, Any]]) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            text=str(item["text"]),
            ordinal=int(item["ordinal"]),
            page=item.get("page"),
            page_end=item.get("page_end"),
            sheet=item.get("sheet"),
            heading=item.get("heading"),
        )
        for item in raw
    ]


class DocumentIndexer:
    """Bring the vector store up to date with a folder of documents."""

    def __init__(
        self,
        *,
        parse: ParseCallable,
        store: DocumentStore,
        catalog: DocumentCatalog,
        workspace: Path,
    ) -> None:
        self.parse = parse
        self.store = store
        self.catalog = catalog
        self.workspace = workspace.resolve()

    def _candidates(self, folder: Path) -> list[Path]:
        return sorted(
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )

    async def index(
        self, folder: Path | None = None, *, on_progress: ProgressCallback | None = None
    ) -> IndexReport:
        """Index every supported file under ``folder`` (default: the workspace)."""
        root = (folder or self.workspace).resolve()
        candidates = self._candidates(root)
        report = IndexReport()

        for position, path in enumerate(candidates, start=1):
            relative = path.relative_to(self.workspace).as_posix()
            if on_progress is not None:
                on_progress(IndexProgress(done=position, total=len(candidates), path=relative))
            try:
                await self._index_one(relative, report)
            except WorkspacePathError as exc:
                report.failed += 1
                report.warnings.append(f"{relative}: outside the workspace ({exc})")
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
                report.failed += 1
                report.warnings.append(f"{relative}: {exc}")
                logger.warning(f"Indexing failed for {relative}: {exc}")
        return report

    async def _index_one(self, relative: str, report: IndexReport) -> None:
        # Re-validate through the workspace boundary even though rglob started
        # inside it: a symlink can point anywhere.
        resolved = resolve_in_workspace(relative)

        digest = file_sha256(resolved)
        if not await self.catalog.needs_index(relative, digest):
            report.skipped += 1
            return

        result = await self.parse(str(resolved))
        doc_type = str(result.get("doc_type", "unknown"))
        chunks = _to_chunks(result.get("chunks", []))

        if doc_type == "pdf-scanned" or not chunks:
            report.warnings.append(
                f"{relative}: looks like a scanned document — DeClaw cannot read it yet"
                if doc_type == "pdf-scanned"
                else f"{relative}: no readable text found"
            )
            return

        if result.get("truncated"):
            report.warnings.append(f"{relative}: very large, indexing was truncated")

        doc = document_id(relative)
        self.store.delete_document(doc)
        await self.store.add_document(doc, relative, chunks)

        stat = resolved.stat()
        # Recorded only now: a document that failed above is retried next run.
        await self.catalog.record(
            relative_path=relative,
            sha256=digest,
            size_bytes=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            doc_type=doc_type,
            chunk_count=len(chunks),
        )
        report.indexed += 1
