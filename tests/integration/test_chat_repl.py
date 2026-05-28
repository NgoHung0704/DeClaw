"""Integration test: the chat REPL against a live Ollama Mistral (DCL-016).

Self-skips unless Ollama is reachable with the configured model pulled. Proves
the acceptance — chat works against a running Ollama — by running one real turn
end-to-end through the assembled brain. The reply text is not asserted verbatim
(the 7B model is non-deterministic); we only require that the turn produced a
non-empty assistant reply, so the test stays robust. Multi-turn history
threading is covered deterministically by ``tests/unit/test_repl.py``.
"""

from __future__ import annotations

import pytest

from declaw.brain.ollama_client import OllamaClient
from declaw.brain.repl import build_brain, run_chat
from declaw.config import get_settings


async def test_repl_one_turn_against_live_ollama() -> None:
    settings = get_settings()
    health = await OllamaClient().health()
    if not health.reachable:
        pytest.skip("Ollama daemon not reachable")
    if not health.has_model(settings.model):
        pytest.skip(f"model {settings.model!r} not pulled")

    replies: list[str] = []
    inputs = iter(["In one short sentence, what is the capital of France?", "/exit"])

    def read() -> str | None:
        return next(inputs, None)

    graph = build_brain()
    await run_chat(graph, read=read, write=replies.append)

    assert len(replies) == 1  # the turn completed end-to-end
    assert replies[0].strip()  # and produced a non-empty reply
