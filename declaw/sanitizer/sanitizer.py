"""Sanitizer orchestrator (DCL-043).

Ties the pieces together: take untrusted ``content`` + a ``source`` label, run
it through the injected :data:`Classifier` (DCL-040), and either return the
content as SAFE or drop it into the :class:`QuarantineStore` (DCL-044) and
return a result that carries only a quarantine id — never the content.

The brain side of the pipeline (``declaw.sanitizer.pipeline``) calls
:meth:`Sanitizer.check`; on UNSAFE it substitutes a neutral placeholder, so an
injection can never reach the model. This is the structural enforcement behind
Inviolable Principles #4 and #5.

The :data:`Classifier` alias lives here (not in ``classifier.py``) on purpose:
it is a plain ``Callable`` with no heavy imports, so the orchestrator, the tool
pipeline, and the registry can depend on it without pulling ``ChatOllama`` /
``langchain_ollama`` into the tool layer. ``build_ollama_classifier`` (the real,
heavy implementation) imports this alias, not the other way around.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from declaw.sanitizer.quarantine import QuarantineStore
from declaw.sanitizer.verdict import SanitizerVerdict

# Async classifier seam: untrusted content -> typed verdict.
Classifier = Callable[[str], Awaitable[SanitizerVerdict]]


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """Outcome of one sanitization check."""

    verdict: SanitizerVerdict
    source: str
    # The content, present ONLY when SAFE. None when quarantined, so an UNSAFE
    # result structurally cannot carry the payload toward the brain.
    safe_content: str | None
    # Set iff the content was quarantined (UNSAFE).
    quarantine_id: str | None

    @property
    def is_safe(self) -> bool:
        return self.verdict.is_safe


class Sanitizer:
    """Classify untrusted content and quarantine anything UNSAFE."""

    def __init__(
        self,
        classifier: Classifier,
        *,
        quarantine: QuarantineStore | None = None,
    ) -> None:
        self._classify = classifier
        self._quarantine = quarantine if quarantine is not None else QuarantineStore()

    @property
    def quarantine(self) -> QuarantineStore:
        """The backing quarantine store (the UI reads quarantined items here)."""
        return self._quarantine

    async def check(self, content: str, *, source: str) -> SanitizationResult:
        """Classify ``content``; quarantine it if UNSAFE.

        ``source`` is a short label of where the content came from (e.g.
        ``"tool:filesystem_read"``) for the audit trail. On SAFE the result
        carries the content; on UNSAFE it carries only the quarantine id.
        """
        verdict = await self._classify(content)
        if verdict.is_safe:
            return SanitizationResult(
                verdict=verdict,
                source=source,
                safe_content=content,
                quarantine_id=None,
            )
        quarantine_id = self._quarantine.add(
            content=content, source=source, verdict=verdict
        )
        return SanitizationResult(
            verdict=verdict,
            source=source,
            safe_content=None,
            quarantine_id=quarantine_id,
        )
