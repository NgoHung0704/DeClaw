"""Stub tools for exercising the agentic loop (DCL-010).

These exist only to prove the think -> tool-call -> observe loop end-to-end
without a live model. Real, typed and validated tools arrive in Phase 2
(see ``declaw/tools/`` and DCL-020+); do not build features on top of these.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def echo(message: str) -> str:
    """Echo ``message`` back, prefixed with ``echo:``.

    Deterministic placeholder so the loop has a tool to call. The model sees
    this docstring as the tool description.
    """
    return f"echo: {message}"
