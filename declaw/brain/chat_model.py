"""Build the real model side of the agentic loop from Ollama (DCL-012).

DCL-010 left the model as an injected ``ModelCallable`` seam so the loop could
be tested without a live LLM. This module fills that seam with a real Mistral
model served by Ollama, made tool-aware via ``ChatOllama.bind_tools``.

The bound model is given the same tools the loop's executor runs; the two must
agree, which is why ``build_agent_graph`` takes ``tools`` separately. Mistral
emits ``tool_calls`` on an ``AIMessage``; ``tools_condition`` then routes them
to the ``ToolNode`` executor.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from declaw.brain.loop import ModelCallable
from declaw.config import get_settings


def build_ollama_model(
    tools: Sequence[BaseTool],
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> ModelCallable:
    """Build a tool-aware ``ModelCallable`` backed by Ollama.

    ``tools`` must match the executor tools passed to ``build_agent_graph``.
    ``model`` and ``base_url`` default to the configured Settings values.
    """
    settings = get_settings()
    llm = ChatOllama(
        model=model or settings.model,
        base_url=base_url or settings.ollama_base_url,
    )
    bound = llm.bind_tools(list(tools))

    async def call(messages: Sequence[BaseMessage]) -> BaseMessage:
        return await bound.ainvoke(list(messages))

    return call
