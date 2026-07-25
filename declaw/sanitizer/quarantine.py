"""Quarantine store for UNSAFE content + audit hook (DCL-044 / DCL-045).

When the sanitizer (DCL-040..043) rules a piece of external content UNSAFE, the
brain must **never** see it (Principle #4/#5). Instead the content is dropped
here, into quarantine, and the brain receives a neutral placeholder. Quarantined
items are meant to be inspectable by the *user* in the UI (Phase 9), never fed
back into the model.

What this module guarantees:

* The raw content is held in a :class:`QuarantineRecord` for later human review,
  but the only data that ever leaves toward a log/audit channel is a SHA-256
  **hash** + source + reason — never the raw bytes (DCL-045: "Log every
  quarantine with hash + source"). Keeping plaintext out of logs matters: the
  content may itself be sensitive client data.
* Every ``add`` emits a :class:`QuarantineEvent` to an injectable ``AuditSink``.
  The default sink writes a structured warning to the operational logger; when
  the DB-backed audit trail lands (DCL-060/061) it becomes just another sink,
  with no change here.

The store is in-memory for now (survives a process, not a restart); a persistent
backend can implement the same small surface later without touching callers.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from declaw.config import Language
from declaw.log import logger
from declaw.sanitizer.verdict import SanitizerVerdict


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class QuarantineEvent:
    """Audit-facing record of a quarantine. Carries the hash, NEVER the content."""

    id: str
    source: str
    content_sha256: str
    reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """A piece of UNSAFE content held for user review. Never surfaced to the brain."""

    id: str
    source: str
    reason: str
    content_sha256: str
    # The raw content, kept ONLY for human inspection in the UI. No code path
    # returns this toward the brain/model.
    content: str
    created_at: datetime

    def to_event(self) -> QuarantineEvent:
        """Project to the audit-facing event (drops the raw content)."""
        return QuarantineEvent(
            id=self.id,
            source=self.source,
            content_sha256=self.content_sha256,
            reason=self.reason,
            created_at=self.created_at,
        )


# Audit sink seam: called once per quarantine. Any ``def f(event) -> None`` fits.
AuditSink = Callable[[QuarantineEvent], None]


def log_audit_sink(event: QuarantineEvent) -> None:
    """Default ``AuditSink``: structured warning to the operational logger.

    Logs hash + source + reason (DCL-045). The raw content is deliberately
    absent from the log line.
    """
    logger.bind(
        event="sanitizer.quarantine",
        quarantine_id=event.id,
        source=event.source,
        content_sha256=event.content_sha256,
        reason=event.reason,
    ).warning("Quarantined UNSAFE external content")


_NOTICE_EN = (
    "[DeClaw] Withheld {source} and quarantined it (id {short_id}): the screening "
    "model flagged a possible instruction aimed at the AI. The assistant never saw "
    "the content, so its answer may be wrong or incomplete. If you know this "
    "content is fine, this was a false positive - review it yourself."
)
_NOTICE_FR = (
    "[DeClaw] {source} a été retenu et mis en quarantaine (id {short_id}) : le "
    "modèle de filtrage y a détecté une possible instruction destinée à l'IA. "
    "L'assistant n'a pas vu le contenu, sa réponse peut donc être fausse ou "
    "incomplète. Si vous savez que ce contenu est sain, c'était un faux positif - "
    "vérifiez-le vous-même."
)


def user_notice_sink(write: Callable[[str], None], language: Language) -> AuditSink:
    """Build an ``AuditSink`` that tells the *user*, in words, about a quarantine.

    Why this exists: the model is handed only a neutral placeholder, and a small
    model paraphrases it badly — in live use qwen2.5:3b turned "quarantined as
    possibly unsafe" into "there might be a problem with the content or
    permissions", so the user was actively misinformed about what happened to
    their own file. DeClaw promises transparency, so the fact that content was
    withheld is stated by the application itself, never left to the model to
    retell. False positives happen (measured ~9% on the benign corpus), which is
    exactly why the notice says so and points the user at the quarantined item.

    Like every other quarantine sink, this one carries the id, source and nothing
    of the content.
    """

    def notify(event: QuarantineEvent) -> None:
        template = _NOTICE_FR if language == "fr" else _NOTICE_EN
        write(template.format(source=event.source, short_id=event.id[:8]))

    return notify


class QuarantineStore:
    """In-memory store of quarantined UNSAFE content (visible to the UI only)."""

    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._records: dict[str, QuarantineRecord] = {}
        self._audit: AuditSink = audit_sink if audit_sink is not None else log_audit_sink

    def add(self, *, content: str, source: str, verdict: SanitizerVerdict) -> str:
        """Quarantine ``content`` from ``source`` with the given UNSAFE ``verdict``.

        Returns the new record id. Emits a :class:`QuarantineEvent` to the audit
        sink as a side effect (DCL-045).
        """
        record = QuarantineRecord(
            id=str(uuid.uuid4()),
            source=source,
            reason=verdict.reason,
            content_sha256=_sha256(content),
            content=content,
            created_at=_utcnow(),
        )
        self._records[record.id] = record
        self._audit(record.to_event())
        return record.id

    def get(self, quarantine_id: str) -> QuarantineRecord:
        """Return the record (for UI display). Raises ``KeyError`` if unknown."""
        return self._records[quarantine_id]

    def list(self) -> list[QuarantineRecord]:
        """Return all quarantined records, newest first (for the UI).

        Ordered by insertion (the dict preserves it), which is robust even when
        two adds land in the same clock tick — unlike sorting on ``created_at``.
        """
        return list(reversed(self._records.values()))

    def __len__(self) -> int:
        return len(self._records)
