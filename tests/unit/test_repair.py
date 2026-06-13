"""Unit tests for tool-call retry/repair (DCL-013).

A scripted async model stands in for the LLM, so the repair loop is exercised
deterministically with a small corpus of malformed outputs — no Ollama needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from declaw.brain.repair import with_tool_call_repair
from declaw.brain.stub_tools import echo


class _ScriptedModel:
    """Async model that replays pre-baked replies and records what it was sent."""

    def __init__(self, replies: list[BaseMessage]) -> None:
        self._replies = list(replies)
        self.received: list[list[BaseMessage]] = []

    @property
    def calls(self) -> int:
        return len(self.received)

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.received.append(list(messages))
        return self._replies.pop(0)


def _valid() -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "echo", "args": {"message": "hi"}, "id": "ok"}]
    )


# Corpus of malformed model outputs, one per failure mode.
_MALFORMED: dict[str, AIMessage] = {
    "invalid_json": AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "echo",
                "args": "{not json",
                "id": "c1",
                "error": "parse error",
                "type": "invalid_tool_call",
            }
        ],
    ),
    "unknown_tool": AIMessage(
        content="", tool_calls=[{"name": "ghost", "args": {}, "id": "c1"}]
    ),
    "bad_args": AIMessage(
        content="", tool_calls=[{"name": "echo", "args": {}, "id": "c1"}]
    ),
}


@pytest.mark.parametrize("malformed", list(_MALFORMED.values()), ids=list(_MALFORMED))
async def test_repairs_malformed_then_returns_valid(malformed: AIMessage) -> None:
    valid = _valid()
    model = _ScriptedModel([malformed, valid])
    repaired = with_tool_call_repair(model, [echo])

    out = await repaired([HumanMessage(content="please echo hi")])

    assert out is valid  # repaired to the valid reply
    assert model.calls == 2  # exactly one corrective retry


async def test_gives_up_after_max_retries() -> None:
    bad = _MALFORMED["unknown_tool"]
    model = _ScriptedModel([bad, bad, bad])
    repaired = with_tool_call_repair(model, [echo], max_retries=2)

    out = await repaired([HumanMessage(content="x")])

    assert out is bad  # last attempt returned unchanged, never hangs
    assert model.calls == 3  # 1 initial + max_retries


async def test_no_retry_when_first_reply_is_valid() -> None:
    valid = _valid()
    model = _ScriptedModel([valid])
    repaired = with_tool_call_repair(model, [echo])

    out = await repaired([HumanMessage(content="x")])

    assert out is valid
    assert model.calls == 1


async def test_no_retry_for_plain_answer() -> None:
    answer = AIMessage(content="Bonjour")
    model = _ScriptedModel([answer])
    repaired = with_tool_call_repair(model, [echo])

    out = await repaired([HumanMessage(content="hi")])

    assert out is answer
    assert model.calls == 1


async def test_corrective_prompt_is_sent_on_retry() -> None:
    model = _ScriptedModel([_MALFORMED["unknown_tool"], _valid()])
    repaired = with_tool_call_repair(model, [echo])

    await repaired([HumanMessage(content="x")])

    # The retry conversation contains a corrective human message naming the issue.
    second_call = model.received[1]
    assert any(
        isinstance(m, HumanMessage)
        and isinstance(m.content, str)
        and "does not exist" in m.content
        for m in second_call
    )
