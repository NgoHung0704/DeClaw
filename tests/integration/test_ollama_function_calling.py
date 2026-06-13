"""Integration test: real Mistral function calling through Ollama (DCL-012).

Skipped automatically unless a local Ollama daemon is reachable AND the
configured model is pulled. It proves the real wire works: ChatOllama +
``bind_tools`` round-trips to an ``AIMessage``. It deliberately does NOT
hard-assert that the 7B model chooses to call the tool (that reliability is
DCL-013's concern), to keep the test from being flaky.

There is no ``integration`` pytest marker yet (DCL-221 sets up the integration
framework); for now the test self-skips at runtime via an Ollama health check.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.ollama_client import OllamaClient
from declaw.brain.stub_tools import echo
from declaw.config import get_settings


async def test_real_mistral_returns_message_through_bound_tools() -> None:
    settings = get_settings()
    health = await OllamaClient().health()
    if not health.reachable:
        pytest.skip("Ollama daemon not reachable")
    if not health.has_model(settings.model):
        pytest.skip(f"model {settings.model!r} not pulled")

    model = build_ollama_model([echo])
    out = await model(
        [HumanMessage(content="Use the echo tool to repeat the word 'bonjour'.")]
    )

    # The real wire works: a chat message came back from the live model.
    assert isinstance(out, AIMessage)

    # If the model chose to call a tool, it must be a well-formed echo call.
    for call in out.tool_calls:
        assert call["name"] == "echo"
        assert "message" in call["args"]
