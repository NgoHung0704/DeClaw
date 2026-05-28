"""Context compaction on overflow (DCL-015).

DCL-014 keeps prompts under the window by *dropping* the oldest messages, which
loses information. Compaction is the smarter alternative: once the conversation
crosses a threshold, the oldest turns are replaced by a single concise summary
note, while a leading ``SystemMessage`` and the most recent turns are kept
verbatim. The task plan lives in ``AgentState.plan`` (a slot, not a message),
so it is preserved automatically; the summary prompt also asks the model to
retain plans and decisions.

Like DCL-014 this trims the *model-facing* view; the full history stays in
``AgentState`` for the audit trail (Principle #7). Summarising needs the model,
so it is async and injected as a ``Summarizer`` — tests pass a fake.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from declaw.brain.context import DEFAULT_SOFT_CAP, TokenCounter, estimate_tokens
from declaw.brain.loop import ModelCallable

# Produces a concise summary of a run of messages.
Summarizer = Callable[[Sequence[BaseMessage]], Awaitable[str]]

DEFAULT_COMPACTION_THRESHOLD = DEFAULT_SOFT_CAP
DEFAULT_KEEP_RECENT = 6

_SUMMARY_INSTRUCTION = (
    "You are compacting an assistant conversation to save context space. "
    "Summarise the conversation below into a concise note that preserves key "
    "facts, the user's requests, decisions, the task plan, and any tool results. "
    "Do not call any tools; reply with the summary text only."
)


def _message_line(message: BaseMessage) -> str:
    text = message.content if isinstance(message.content, str) else str(message.content)
    return f"{message.type}: {text}"


def _render(messages: Sequence[BaseMessage]) -> str:
    return "\n".join(_message_line(m) for m in messages)


def make_summarizer(model: ModelCallable) -> Summarizer:
    """Build a ``Summarizer`` that asks ``model`` to summarise a run of messages."""

    async def summarize(messages: Sequence[BaseMessage]) -> str:
        prompt: list[BaseMessage] = [
            SystemMessage(content=_SUMMARY_INSTRUCTION),
            HumanMessage(content=_render(messages)),
        ]
        reply = await model(prompt)
        return reply.content if isinstance(reply.content, str) else str(reply.content)

    return summarize


async def compact_messages(
    messages: Sequence[BaseMessage],
    *,
    summarize: Summarizer,
    threshold: int = DEFAULT_COMPACTION_THRESHOLD,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    counter: TokenCounter = estimate_tokens,
) -> list[BaseMessage]:
    """Replace the oldest turns with a summary note once over ``threshold``.

    No-op while under ``threshold`` or when there is nothing older than the
    ``keep_recent`` most recent messages. A leading ``SystemMessage`` and the
    recent tail are kept verbatim; a leading orphan ``ToolMessage`` in the tail
    is dropped to keep the prompt valid.
    """
    msgs = list(messages)
    if counter(msgs) <= threshold:
        return msgs

    head: list[BaseMessage] = []
    rest = msgs
    if msgs and isinstance(msgs[0], SystemMessage):
        head, rest = [msgs[0]], msgs[1:]

    recent: list[BaseMessage] = rest[-keep_recent:] if keep_recent > 0 else []
    old = rest[: len(rest) - len(recent)]
    if not old:
        return msgs  # nothing old enough to compact

    summary = await summarize(old)
    note = SystemMessage(content=f"Summary of earlier conversation:\n{summary}")

    while len(recent) > 1 and isinstance(recent[0], ToolMessage):
        recent.pop(0)

    return [*head, note, *recent]


def with_compaction(
    model: ModelCallable,
    *,
    summarize: Summarizer,
    threshold: int = DEFAULT_COMPACTION_THRESHOLD,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    counter: TokenCounter = estimate_tokens,
) -> ModelCallable:
    """Wrap ``model`` so its incoming messages are compacted when over threshold.

    Composable with the other ``ModelCallable`` wrappers; only the model-facing
    view is compacted, the caller keeps the full history in ``AgentState``.
    """

    async def call(messages: Sequence[BaseMessage]) -> BaseMessage:
        compacted = await compact_messages(
            messages,
            summarize=summarize,
            threshold=threshold,
            keep_recent=keep_recent,
            counter=counter,
        )
        return await model(compacted)

    return call
