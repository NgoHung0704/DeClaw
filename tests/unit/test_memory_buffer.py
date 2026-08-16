"""Tests for the short-term conversation buffer (DCL-052).

Acceptance: bound respected; eviction order correct.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from declaw.memory.buffer import ConversationBuffer


def test_bound_is_respected() -> None:
    buffer = ConversationBuffer(max_messages=3)
    for i in range(10):
        buffer.append(HumanMessage(content=f"m{i}"))
    assert len(buffer) == 3


def test_eviction_is_fifo() -> None:
    buffer = ConversationBuffer(max_messages=3)
    buffer.extend(HumanMessage(content=f"m{i}") for i in range(5))
    assert [m.content for m in buffer.messages] == ["m2", "m3", "m4"]


def test_under_capacity_keeps_everything_in_order() -> None:
    buffer = ConversationBuffer(max_messages=10)
    buffer.append(HumanMessage(content="hi"))
    buffer.append(AIMessage(content="hello"))
    assert [m.content for m in buffer.messages] == ["hi", "hello"]
    assert len(buffer) == 2


def test_messages_returns_a_copy() -> None:
    buffer = ConversationBuffer(max_messages=5)
    buffer.append(HumanMessage(content="a"))
    snapshot = buffer.messages
    snapshot.clear()
    assert len(buffer) == 1


def test_clear_empties_the_ring() -> None:
    buffer = ConversationBuffer(max_messages=5)
    buffer.extend([HumanMessage(content="a"), AIMessage(content="b")])
    buffer.clear()
    assert len(buffer) == 0
    assert buffer.messages == []


def test_zero_or_negative_bound_rejected() -> None:
    with pytest.raises(ValueError):
        ConversationBuffer(max_messages=0)
    with pytest.raises(ValueError):
        ConversationBuffer(max_messages=-1)


def test_mixed_types_evict_uniformly() -> None:
    buffer = ConversationBuffer(max_messages=2)
    buffer.append(HumanMessage(content="question"))
    buffer.append(AIMessage(content="answer"))
    buffer.append(HumanMessage(content="follow-up"))
    assert [type(m) for m in buffer.messages] == [AIMessage, HumanMessage]
