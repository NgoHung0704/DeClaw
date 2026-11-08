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
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from declaw.brain.loop import ModelCallable
from declaw.config import Language, get_settings


class _SnapshotModel:
    """A ``ModelCallable`` carrying the language of its effective-settings snapshot.

    ChatOllama has no language knob, but the snapshot must reach the model
    stack without going through the global ``get_settings()`` cache (spec
    section 12). The resolved language therefore rides on the callable
    (``model.language``) so the session layer reads it off the one object it
    already owns, and a future language-dependent model knob lands here
    without touching call sites.
    """

    def __init__(self, bound: Any, language: Language) -> None:
        self._bound = bound
        self.language = language

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        result: BaseMessage = await self._bound.ainvoke(list(messages))
        return result


def build_ollama_model(
    tools: Sequence[BaseTool],
    *,
    model: str | None = None,
    base_url: str | None = None,
    language: Language | None = None,
) -> ModelCallable:
    """Build a tool-aware ``ModelCallable`` backed by Ollama.

    ``tools`` must match the executor tools passed to ``build_agent_graph``.
    ``model``, ``base_url`` and ``language`` default to the configured
    Settings values, so the CLI keeps its current behavior by passing
    nothing; the gateway passes the values of its effective-settings
    snapshot instead.
    """
    settings = get_settings()
    llm = ChatOllama(
        model=model or settings.model,
        base_url=base_url or settings.ollama_base_url,
    )
    bound = llm.bind_tools(list(tools))

    return _SnapshotModel(bound, language if language is not None else settings.language)
