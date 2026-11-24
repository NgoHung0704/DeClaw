"""Transport-independent retrieval-source context and ownership contracts."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any


def _sources() -> Any:
    assert importlib.util.find_spec("declaw.documents.sources") is not None, (
        "retrieval-source context must live in the shared documents layer"
    )
    return importlib.import_module("declaw.documents.sources")


def test_sources_are_noop_without_context_and_copy_metadata() -> None:
    module = _sources()
    module.record_source({"path": "outside.txt"})
    collector = module.TurnSources()
    metadata = {"path": "a.txt", "page": 1}
    token = module.current_turn_sources.set(collector)
    try:
        module.record_source(metadata)
        module.record_source(dict(metadata))
        metadata["path"] = "changed.txt"
        returned = collector.sources()
        returned[0]["page"] = 99
        assert collector.sources() == [{"path": "a.txt", "page": 1}]
    finally:
        module.current_turn_sources.reset(token)
    module.record_source({"path": "after.txt"})
    assert collector.sources() == [{"path": "a.txt", "page": 1}]


async def test_sources_follow_child_tasks_and_isolate_concurrent_turns() -> None:
    module = _sources()

    async def turn(path: str) -> list[dict[str, Any]]:
        collector = module.TurnSources()
        token = module.current_turn_sources.set(collector)
        try:
            async def child() -> None:
                await asyncio.sleep(0)
                module.record_source({"path": path})

            await asyncio.create_task(child())
            return collector.sources()
        finally:
            module.current_turn_sources.reset(token)

    assert await asyncio.gather(turn("a.txt"), turn("b.txt")) == [
        [{"path": "a.txt"}], [{"path": "b.txt"}],
    ]
    assert module.current_turn_sources.get() is None
