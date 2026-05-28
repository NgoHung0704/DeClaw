"""Unit tests for the Ollama-backed ModelCallable (DCL-012).

``ChatOllama`` is faked at its construction boundary (the same way the Ollama
health client is tested against ``httpx.MockTransport``), so these run with no
Ollama daemon. The live-model path is covered by the integration test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.loop import build_agent_graph
from declaw.brain.stub_tools import echo
from declaw.config import get_settings


@dataclass
class _Recorder:
    model: str | None = None
    base_url: str | None = None
    tools: list[object] = field(default_factory=list)
    calls: list[list[BaseMessage]] = field(default_factory=list)


def _install_fake_ollama(
    monkeypatch: pytest.MonkeyPatch, replies: list[BaseMessage]
) -> _Recorder:
    """Replace ChatOllama with a fake that records construction + scripts replies."""
    rec = _Recorder()
    pending = list(replies)

    class FakeBound:
        async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
            rec.calls.append(list(messages))
            return pending.pop(0)

    class FakeChatOllama:
        def __init__(self, *, model: str, base_url: str) -> None:
            rec.model = model
            rec.base_url = base_url

        def bind_tools(self, tools: Sequence[object]) -> FakeBound:
            rec.tools = list(tools)
            return FakeBound()

    monkeypatch.setattr("declaw.brain.chat_model.ChatOllama", FakeChatOllama)
    return rec


async def test_build_ollama_model_wires_settings_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"message": "hi"}, "id": "c1"}],
    )
    rec = _install_fake_ollama(monkeypatch, [reply])

    model = build_ollama_model([echo])

    # Construction used the configured model + base_url, bound with our tool.
    assert rec.model == get_settings().model
    assert rec.base_url == get_settings().ollama_base_url
    assert rec.tools == [echo]

    out = await model([HumanMessage(content="hi")])
    assert isinstance(out, AIMessage)
    assert out.tool_calls  # the model produced a structured tool call


async def test_loop_routes_model_tool_call_to_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Turn 1: model emits a tool call. Turn 2: model answers after observing.
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"message": "hi"}, "id": "c1"}],
    )
    answer = AIMessage(content="done")
    _install_fake_ollama(monkeypatch, [tool_call, answer])

    model = build_ollama_model([echo])
    graph = build_agent_graph(model=model, tools=[echo])
    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

    messages = result["messages"]
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1  # the structured tool call routed to the executor
    assert tool_msgs[0].content == "echo: hi"

    final = messages[-1]
    assert isinstance(final, AIMessage)
    assert final.content == "done"
