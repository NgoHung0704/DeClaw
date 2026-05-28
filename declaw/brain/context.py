"""Context-window management for the agentic loop (Mistral 32k) (DCL-014).

As a conversation grows, the message list can exceed the model's context
window (Mistral 7B Instruct: 32k tokens). This module trims the messages that
are *sent to the model* so the prompt stays under budget, while the full
history is kept in ``AgentState`` for the audit trail (Principle #7).

Trimming here is plain eviction (drop oldest messages). Summarising evicted
turns into a compact note is DCL-015.

Token counting uses a deliberately *conservative* (over-estimating) heuristic
so we never silently exceed the window; a precise tokenizer can be injected
through the ``TokenCounter`` seam.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from declaw.brain.loop import ModelCallable

# A function that estimates the token cost of a message list.
TokenCounter = Callable[[Sequence[BaseMessage]], int]

# Mistral 7B Instruct context window, and how much we hold back for the reply.
MISTRAL_CONTEXT_TOKENS = 32768
_RESPONSE_RESERVE_TOKENS = 2048
DEFAULT_HARD_CAP = MISTRAL_CONTEXT_TOKENS - _RESPONSE_RESERVE_TOKENS  # 30720
DEFAULT_SOFT_CAP = 24000

# Conservative heuristic: ~3 chars/token (over-estimates vs the usual ~4 for
# English) plus a fixed per-message overhead for role/structure markers.
_CHARS_PER_TOKEN = 3
_PER_MESSAGE_OVERHEAD = 4


def _message_text(message: BaseMessage) -> str:
    text = message.content if isinstance(message.content, str) else str(message.content)
    if isinstance(message, AIMessage) and message.tool_calls:
        text = f"{text} {message.tool_calls}"
    return text


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Conservatively estimate the token cost of ``messages``."""
    total = 0
    for message in messages:
        chars = len(_message_text(message))
        total += -(-chars // _CHARS_PER_TOKEN) + _PER_MESSAGE_OVERHEAD  # ceil div
    return total


def fit_to_window(
    messages: Sequence[BaseMessage],
    *,
    hard_cap: int = DEFAULT_HARD_CAP,
    soft_cap: int = DEFAULT_SOFT_CAP,
    counter: TokenCounter = estimate_tokens,
) -> list[BaseMessage]:
    """Return ``messages`` trimmed to fit the window.

    No-op while under ``hard_cap``. Once exceeded, the oldest messages are
    dropped until the total is back under ``soft_cap`` (so we do not trim on
    every subsequent turn). A leading ``SystemMessage`` and the most recent
    message are always kept; a leading orphan ``ToolMessage`` (whose requesting
    ``AIMessage`` was evicted) is dropped to keep the prompt valid.
    """
    msgs = list(messages)
    if counter(msgs) <= hard_cap:
        return msgs

    head: list[BaseMessage] = []
    body = msgs
    if msgs and isinstance(msgs[0], SystemMessage):
        head, body = [msgs[0]], msgs[1:]

    while len(body) > 1 and counter([*head, *body]) > soft_cap:
        body.pop(0)
    while len(body) > 1 and isinstance(body[0], ToolMessage):
        body.pop(0)

    return [*head, *body]


def with_context_window(
    model: ModelCallable,
    *,
    counter: TokenCounter = estimate_tokens,
    hard_cap: int = DEFAULT_HARD_CAP,
    soft_cap: int = DEFAULT_SOFT_CAP,
) -> ModelCallable:
    """Wrap ``model`` so the messages it receives are trimmed to the window.

    Composable with the other ``ModelCallable`` wrappers. Only the model-facing
    view is trimmed; callers keep the full history in ``AgentState``.
    """

    async def call(messages: Sequence[BaseMessage]) -> BaseMessage:
        trimmed = fit_to_window(
            messages, hard_cap=hard_cap, soft_cap=soft_cap, counter=counter
        )
        return await model(trimmed)

    return call
