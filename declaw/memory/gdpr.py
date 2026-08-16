"""GDPR memory portability + right to be forgotten (DCL-056 / DCL-057).

Export writes one self-describing JSON archive of everything DeClaw remembers
about the user: semantic memories (decrypted — portability means *readable*
data, per GDPR Art. 20) and episodic task history. Wipe deletes both stores
and leaves only an anonymized audit record (counts, never content), so the
trail proves the wipe happened without undoing it.

Both operations emit audit events (Principle #7): exporting personal data and
destroying it are exactly the actions a regulated professional must be able
to evidence later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from declaw.audit.events import MemoryExportEvent, MemoryWipeEvent
from declaw.audit.logger import AuditLogger
from declaw.memory.episodic import EpisodicMemory
from declaw.memory.semantic import SemanticMemory

MEMORY_EXPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WipeReport:
    """What a wipe removed (the anonymized facts the audit trail keeps)."""

    semantic_removed: int
    episodes_removed: int


async def export_memory(
    destination: Path,
    *,
    semantic: SemanticMemory,
    episodic: EpisodicMemory,
    audit: AuditLogger | None = None,
) -> Path:
    """Write the complete memory archive to ``destination`` (JSON, UTF-8)."""
    semantic_records = semantic.export_all()
    episodes = await episodic.export_all()

    archive = {
        "declaw_memory_export": {
            "schema_version": MEMORY_EXPORT_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "semantic": [
            {"id": r.id, "text": r.text, "metadata": r.metadata} for r in semantic_records
        ],
        "episodes": [e.model_dump(mode="json") for e in episodes],
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if audit is not None:
        await audit.emit(
            MemoryExportEvent(
                destination=str(destination),
                semantic_count=len(semantic_records),
                episode_count=len(episodes),
            )
        )
    return destination


async def wipe_memory(
    *,
    semantic: SemanticMemory,
    episodic: EpisodicMemory,
    audit: AuditLogger | None = None,
) -> WipeReport:
    """Delete all semantic memories + episodes; audit keeps counts only."""
    semantic_removed = semantic.wipe()
    episodes_removed = await episodic.wipe()
    report = WipeReport(
        semantic_removed=semantic_removed, episodes_removed=episodes_removed
    )
    if audit is not None:
        await audit.emit(
            MemoryWipeEvent(
                semantic_removed=report.semantic_removed,
                episodes_removed=report.episodes_removed,
            )
        )
    return report
