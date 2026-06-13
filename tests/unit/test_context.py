"""Unit tests for context-window management (DCL-014).

Eviction logic is exercised with an injected ``counter`` (one token per
message) so the caps are crisp; a separate test uses the real
``estimate_tokens`` to prove a long conversation stays under the 32k window.
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

from declaw.brain.context import (
    DEFAULT_HARD_CAP,
    MISTRAL_CONTEXT_TOKENS,
    estimate_tokens,
    fit_to_window,
    with_context_window,
)


def _count_messages(messages: Sequence[BaseMessage]) -> int:
    """Trivial counter: one 'token' per message."""
    return len(messages)


def test_estimate_tokens_basics() -> None:
    assert estimate_tokens([]) == 0
    short = estimate_tokens([HumanMessage(content="hi")])
    long = estimate_tokens([HumanMessage(content="word " * 500)])
    assert short > 0
    assert long > short


def test_fit_to_window_noop_under_cap() -> None:
    msgs = [HumanMessage(content="a"), HumanMessage(content="b")]
    result = fit_to_window(msgs, hard_cap=5, soft_cap=3, counter=_count_messages)
    assert result == msgs


def test_fit_to_window_evicts_oldest_keeps_recent() -> None:
    msgs = [HumanMessage(content=f"m{i}") for i in range(10)]
    result = fit_to_window(msgs, hard_cap=5, soft_cap=3, counter=_count_messages)
    assert result == msgs[-3:]  # trimmed down to soft_cap, newest kept


def test_fit_to_window_preserves_system_message() -> None:
    system = SystemMessage(content="rules")
    msgs: list[BaseMessage] = [system, *(HumanMessage(content=f"m{i}") for i in range(10))]
    result = fit_to_window(msgs, hard_cap=5, soft_cap=3, counter=_count_messages)
    assert result[0] is system
    assert result == [system, *msgs[-2:]]


def test_fit_to_window_keeps_last_message_even_if_oversized() -> None:
    only = HumanMessage(content="huge")
    result = fit_to_window([only], hard_cap=0, soft_cap=0, counter=_count_messages)
    assert result == [only]  # never drop the current turn


def test_fit_to_window_drops_orphan_tool_message() -> None:
    ai = AIMessage(content="", tool_calls=[{"name": "echo", "args": {"message": "x"}, "id": "c1"}])
    tool = ToolMessage(content="echo: x", tool_call_id="c1")
    final = HumanMessage(content="thanks")
    msgs = [HumanMessage(content="old1"), HumanMessage(content="old2"), ai, tool, final]

    result = fit_to_window(msgs, hard_cap=3, soft_cap=2, counter=_count_messages)

    # eviction leaves [tool, final]; the orphan ToolMessage is then dropped
    assert not any(isinstance(m, ToolMessage) for m in result)
    assert result[-1] is final


class _SpyModel:
    def __init__(self) -> None:
        self.received: list[BaseMessage] | None = None

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.received = list(messages)
        return AIMessage(content="ok")


async def test_with_context_window_trims_before_model_call() -> None:
    spy = _SpyModel()
    wrapped = with_context_window(spy, counter=_count_messages, hard_cap=3, soft_cap=2)
    msgs = [HumanMessage(content=f"m{i}") for i in range(10)]

    await wrapped(msgs)

    assert spy.received is not None
    assert len(spy.received) == 2  # the model only sees the trimmed view


def test_long_conversation_stays_under_32k() -> None:
    chunk = "lorem ipsum dolor sit amet " * 200  # a few hundred tokens each
    msgs: list[BaseMessage] = [SystemMessage(content="system rules")]
    msgs += [HumanMessage(content=chunk) for _ in range(100)]
    assert estimate_tokens(msgs) > MISTRAL_CONTEXT_TOKENS  # genuinely over the window

    fitted = fit_to_window(msgs)  # real estimate_tokens + default caps

    assert estimate_tokens(fitted) <= DEFAULT_HARD_CAP
    assert fitted[0].content == "system rules"  # system prompt preserved
