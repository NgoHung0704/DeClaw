"""Which files are indexed, and at what content hash.

SQLite rather than JSON — the opposite of the Phase 7 call for
``plugin_state.json``, and for a reason. That file holds four fields of user
policy where being diffable is the point. This is a machine-maintained index
over potentially thousands of files, looked up by hash on every pass.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.db.models import IndexedDocument

_HASH_CHUNK_BYTES = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Hash a file's contents, streamed so a large PDF is never held in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_CHUNK_BYTES):
            digest.update(block)
    return digest.hexdigest()


class DocumentCatalog:
    """The record of what has been indexed, so unchanged files are skipped."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def needs_index(self, relative_path: str, sha256: str) -> bool:
        """True when the file is unknown or its contents changed."""
        async with self._sessionmaker() as session:
            row = await session.get(IndexedDocument, relative_path)
            return row is None or row.content_sha256 != sha256

    async def record(
        self,
        *,
        relative_path: str,
        sha256: str,
        size_bytes: int,
        mtime: datetime,
        doc_type: str,
        chunk_count: int,
    ) -> None:
        """Insert or update the entry for one document."""
        async with self._sessionmaker() as session:
            row = await session.get(IndexedDocument, relative_path)
            if row is None:
                row = IndexedDocument(
                    path=relative_path,
                    content_sha256=sha256,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    doc_type=doc_type,
                    chunk_count=chunk_count,
                )
            else:
                row.content_sha256 = sha256
                row.size_bytes = size_bytes
                row.mtime = mtime
                row.doc_type = doc_type
                row.chunk_count = chunk_count
            row.indexed_at = datetime.now(timezone.utc)
            session.add(row)
            await session.commit()

    async def forget(self, relative_path: str) -> None:
        """Drop the entry, so the next pass re-indexes the file."""
        async with self._sessionmaker() as session:
            row = await session.get(IndexedDocument, relative_path)
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def known_paths(self) -> list[str]:
        """Every indexed path, sorted."""
        async with self._sessionmaker() as session:
            rows = await session.exec(select(IndexedDocument.path))
            return sorted(rows.all())
