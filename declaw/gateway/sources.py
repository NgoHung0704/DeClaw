"""The typed retrieval-source side channel for chat turns (DCL-127, spec section 8).

``chat.final.sources`` is built from a per-turn :class:`TurnSources` collector,
reached through the SAME context mechanism as the task id: the turn coroutine
sets ``current_turn_sources`` for its whole body, so document tools running
inside that turn record retrieval metadata through :func:`record_source`
without any new parameter. Outside a turn (the CLI) no collector is set and
recording is a no-op.

Sources are therefore STRUCTURAL: retrieval metadata recorded inside the
document search/summarize implementations. They are never parsed from tool
output text and never model-authored — a poisoned tool result or an
invented inline citation cannot reach the user's sources block.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


class TurnSources:
    """Collect the retrieval metadata of one turn, in recording order."""

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []

    def record(self, metadata: dict[str, Any]) -> None:
        """Record one retrieval hit's citation metadata; duplicates skipped."""
        if metadata not in self._sources:
            self._sources.append(dict(metadata))

    def sources(self) -> list[dict[str, Any]]:
        """The recorded source metadata, as fresh dicts for frame assembly."""
        return [dict(source) for source in self._sources]


current_turn_sources: ContextVar[TurnSources | None] = ContextVar(
    "current_turn_sources", default=None
)
"""The collector of the turn this execution context belongs to; None outside one."""


def record_source(metadata: dict[str, Any]) -> None:
    """Record retrieval metadata into the ambient turn's collector.

    No-op when no collector is set (CLI usage); the recording side never
    needs to know whether a gateway turn is in flight.
    """
    collector = current_turn_sources.get()
    if collector is not None:
        collector.record(metadata)
