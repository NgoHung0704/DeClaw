"""Unit tests for context compaction (DCL-015).

A fake summariser and an injected counter (one 'token' per message) make the
threshold and the summary deterministic — no Ollama needed.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from declaw.brain.compaction import compact_messages, make_summarizer, with_compaction


def _count_messages(messages: Sequence[BaseMessage]) -> int:
    return len(messages)


class _FakeSummarizer:
    def __init__(self, text: str = "SUMMARY") -> None:
        self.text = text
        self.calls: list[list[BaseMessage]] = []

    async def __call__(self, messages: Sequence[BaseMessage]) -> str:
        self.calls.append(list(messages))
        return self.text


async def test_no_compaction_under_threshold() -> None:
    summarizer = _FakeSummarizer()
    msgs = [HumanMessage(content="a"), HumanMessage(content="b")]

    result = await compact_messages(
        msgs, summarize=summarizer, threshold=5, keep_recent=2, counter=_count_messages
    )

    assert result == msgs
    assert summarizer.calls == []  # never summarised


async def test_compacts_oldest_into_summary_note() -> None:
    summarizer = _FakeSummarizer()
    msgs = [HumanMessage(content=f"m{i}") for i in range(10)]

    result = await compact_messages(
        msgs, summarize=summarizer, threshold=5, keep_recent=2, counter=_count_messages
    )

    assert len(result) == 3  # [summary note] + last 2 verbatim
    note = result[0]
    assert isinstance(note, SystemMessage)
    assert isinstance(note.content, str) and "SUMMARY" in note.content
    assert result[1:] == msgs[-2:]
    assert summarizer.calls == [msgs[:8]]  # summariser saw the 8 oldest


async def test_preserves_leading_system_message() -> None:
    summarizer = _FakeSummarizer()
    system = SystemMessage(content="rules")
    msgs: list[BaseMessage] = [system, *(HumanMessage(content=f"m{i}") for i in range(10))]

    result = await compact_messages(
        msgs, summarize=summarizer, threshold=5, keep_recent=2, counter=_count_messages
    )

    assert result[0] is system
    assert isinstance(result[1], SystemMessage)  # the summary note
    assert result[2:] == msgs[-2:]


async def test_no_compaction_when_nothing_older_than_recent() -> None:
    summarizer = _FakeSummarizer()
    msgs = [HumanMessage(content="a"), HumanMessage(content="b")]

    result = await compact_messages(
        msgs, summarize=summarizer, threshold=1, keep_recent=6, counter=_count_messages
    )

    assert result == msgs  # over threshold, but nothing older than keep_recent
    assert summarizer.calls == []


async def test_drops_orphan_tool_message_in_recent() -> None:
    summarizer = _FakeSummarizer()
    ai = AIMessage(content="", tool_calls=[{"name": "echo", "args": {"message": "x"}, "id": "c1"}])
    tool = ToolMessage(content="echo: x", tool_call_id="c1")
    msgs = [
        HumanMessage(content="h0"),
        HumanMessage(content="h1"),
        HumanMessage(content="h2"),
        HumanMessage(content="h3"),
        ai,
        tool,
        HumanMessage(content="hA"),
        HumanMessage(content="hB"),
    ]

    result = await compact_messages(
        msgs, summarize=summarizer, threshold=2, keep_recent=3, counter=_count_messages
    )

    # recent would start with the orphan ToolMessage (its AIMessage was folded away)
    assert not any(isinstance(m, ToolMessage) for m in result)
    assert result[-1] is msgs[-1]


async def test_make_summarizer_uses_model_content() -> None:
    captured: list[Sequence[BaseMessage]] = []

    async def fake_model(messages: Sequence[BaseMessage]) -> BaseMessage:
        captured.append(messages)
        return AIMessage(content="a concise summary")

    summarize = make_summarizer(fake_model)
    out = await summarize([HumanMessage(content="hello"), AIMessage(content="hi")])

    assert out == "a concise summary"
    assert isinstance(captured[0][0], SystemMessage)  # prompt leads with instruction


async def test_with_compaction_compacts_then_calls_model() -> None:
    summarizer = _FakeSummarizer()
    received: list[Sequence[BaseMessage]] = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        received.append(messages)
        return AIMessage(content="ok")

    wrapped = with_compaction(
        model, summarize=summarizer, threshold=5, keep_recent=2, counter=_count_messages
    )
    msgs = [HumanMessage(content=f"m{i}") for i in range(10)]

    out = await wrapped(msgs)

    assert isinstance(out, AIMessage)
    assert out.content == "ok"  # downstream reply intact
    assert summarizer.calls  # compaction was triggered
    assert len(received[0]) == 3  # model saw [note] + last 2
