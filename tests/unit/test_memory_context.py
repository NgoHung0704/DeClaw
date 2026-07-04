"""Tests for memory retrieval in Brain context assembly (DCL-055).

Acceptance: "Brain uses retrieved memory in answers" — proven with a scripted
model that records exactly what it was shown, plus an end-to-end
build_agent_graph run where the injected memory changes the answer path.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from declaw.brain.loop import build_agent_graph
from declaw.brain.memory_context import (
    build_memory_note,
    with_memory,
)
from declaw.memory.semantic import MemoryHit


def _hit(text: str, distance: float = 0.1) -> MemoryHit:
    return MemoryHit(id=text[:8], text=text, metadata={}, distance=distance)


class RecordingModel:
    """Scripted model that records the messages of each call."""

    def __init__(self, reply: str = "ok") -> None:
        self.calls: list[list[BaseMessage]] = []
        self._reply = reply

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.calls.append(list(messages))
        return AIMessage(content=self._reply)


async def test_memory_note_injected_before_latest_human_turn() -> None:
    model = RecordingModel()

    async def retrieve(query: str) -> list[MemoryHit]:
        assert query == "What did the Acme contract say?"
        return [_hit("The Acme contract was signed in March 2026.")]

    wrapped = with_memory(model, retrieve)
    history: list[BaseMessage] = [
        HumanMessage(content="hello"),
        AIMessage(content="hi"),
        HumanMessage(content="What did the Acme contract say?"),
    ]
    await wrapped(history)

    [seen] = model.calls
    assert len(seen) == 4
    note = seen[2]
    assert isinstance(note, SystemMessage)
    assert "Acme contract was signed in March 2026" in note.content
    assert isinstance(seen[3], HumanMessage)  # note sits right before the query


async def test_no_hits_means_no_injection() -> None:
    model = RecordingModel()

    async def retrieve(query: str) -> list[MemoryHit]:
        return []

    wrapped = with_memory(model, retrieve)
    history: list[BaseMessage] = [HumanMessage(content="anything")]
    await wrapped(history)
    [seen] = model.calls
    assert len(seen) == 1  # untouched


async def test_retrieval_failure_is_non_fatal() -> None:
    model = RecordingModel(reply="still fine")

    async def retrieve(query: str) -> list[MemoryHit]:
        raise RuntimeError("chroma exploded")

    wrapped = with_memory(model, retrieve)
    reply = await wrapped([HumanMessage(content="hi")])
    assert reply.content == "still fine"
    assert len(model.calls) == 1


async def test_token_budget_caps_the_note() -> None:
    hits = [_hit(f"memory {i}: " + "x" * 400, distance=i / 10) for i in range(20)]
    note = build_memory_note(hits, token_budget=300)
    assert note is not None
    # Nearest-first: memory 0 must be in, the far tail must be cut.
    assert "memory 0" in note.content
    assert "memory 19" not in note.content


async def test_note_is_none_when_nothing_fits() -> None:
    assert build_memory_note([_hit("y" * 10_000)], token_budget=50) is None


async def test_history_is_not_mutated() -> None:
    model = RecordingModel()

    async def retrieve(query: str) -> list[MemoryHit]:
        return [_hit("a memory")]

    wrapped = with_memory(model, retrieve)
    history: list[BaseMessage] = [HumanMessage(content="q")]
    await wrapped(history)
    assert len(history) == 1  # the caller's list is untouched


async def test_brain_uses_retrieved_memory_in_answer() -> None:
    """End-to-end through build_agent_graph: the acceptance."""

    async def retrieve(query: str) -> list[MemoryHit]:
        return [_hit("The client's deadline is 2026-09-01.")]

    async def scripted_model(messages: Sequence[BaseMessage]) -> BaseMessage:
        # The "model" answers from whatever memory note it can see.
        notes = [
            m.content
            for m in messages
            if isinstance(m, SystemMessage) and "long-term memory" in str(m.content)
        ]
        if notes and "2026-09-01" in str(notes[0]):
            return AIMessage(content="Your deadline is 2026-09-01.")
        return AIMessage(content="I don't know.")

    graph = build_agent_graph(model=with_memory(scripted_model, retrieve), tools=[])
    result = await graph.ainvoke({"messages": [HumanMessage(content="When is my deadline?")]})
    assert result["messages"][-1].content == "Your deadline is 2026-09-01."
