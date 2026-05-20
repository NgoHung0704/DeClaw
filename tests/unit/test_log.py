"""Unit tests for the operational JSON logger (DCL-006).

Each test reconfigures the global loguru logger to write to an in-memory
``StringIO`` so we can parse and assert on individual records without
touching stderr or the filesystem.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Iterator
from datetime import datetime

import pytest

from declaw.log import configure, logger, set_request_id, use_request_id


@pytest.fixture
def sink() -> Iterator[io.StringIO]:
    """Fresh in-memory sink installed on the global logger."""
    buffer = io.StringIO()
    configure(level="TRACE", stream=buffer, force=True)
    try:
        yield buffer
    finally:
        # Clear request_id between tests so leakage is impossible.
        set_request_id(None)


def _lines(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


# --- Shape of a record -----------------------------------------------------


def test_record_is_valid_json_with_required_fields(sink: io.StringIO) -> None:
    logger.info("hello")

    records = _lines(sink)
    assert len(records) == 1
    record = records[0]

    assert set(record.keys()) >= {"timestamp", "level", "message", "request_id"}
    assert record["level"] == "INFO"
    assert record["message"] == "hello"
    assert record["request_id"] is None  # no context active


def test_timestamp_is_iso8601(sink: io.StringIO) -> None:
    logger.info("tick")

    record = _lines(sink)[0]
    # fromisoformat accepts the format loguru produces (with offset).
    parsed = datetime.fromisoformat(str(record["timestamp"]))
    assert parsed.tzinfo is not None  # has a timezone offset


# --- Level filtering --------------------------------------------------------


def test_records_below_threshold_are_dropped() -> None:
    buffer = io.StringIO()
    configure(level="WARNING", stream=buffer, force=True)

    logger.debug("nope")
    logger.info("nope")
    logger.warning("yes")
    logger.error("yes")

    levels = [r["level"] for r in _lines(buffer)]
    assert levels == ["WARNING", "ERROR"]


# --- request_id propagation -------------------------------------------------


def test_use_request_id_attaches_id(sink: io.StringIO) -> None:
    with use_request_id("req-42"):
        logger.info("inside")
    logger.info("outside")

    records = _lines(sink)
    assert records[0]["request_id"] == "req-42"
    assert records[1]["request_id"] is None


def test_nested_use_request_id_restores_outer(sink: io.StringIO) -> None:
    with use_request_id("outer"):
        logger.info("a")
        with use_request_id("inner"):
            logger.info("b")
        logger.info("c")

    ids = [r["request_id"] for r in _lines(sink)]
    assert ids == ["outer", "inner", "outer"]


async def test_request_id_isolated_across_async_tasks(sink: io.StringIO) -> None:
    # Two concurrent tasks, each with their own request_id. ContextVar must
    # keep them isolated even though they interleave on the event loop.
    async def task(rid: str, n: int) -> None:
        with use_request_id(rid):
            for _ in range(n):
                logger.info(rid)
                await asyncio.sleep(0)  # force interleave

    await asyncio.gather(task("alpha", 3), task("beta", 3))

    records = _lines(sink)
    assert len(records) == 6
    for r in records:
        assert r["request_id"] == r["message"]  # never crossed wires


# --- Extras -----------------------------------------------------------------


def test_bound_extras_are_included(sink: io.StringIO) -> None:
    logger.bind(user="alice", action="login").info("event")

    record = _lines(sink)[0]
    assert record["extra"] == {"user": "alice", "action": "login"}


def test_exception_is_serialized(sink: io.StringIO) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.opt(exception=True).error("caught")

    record = _lines(sink)[0]
    assert "exception" in record
    assert "RuntimeError" in str(record["exception"])
