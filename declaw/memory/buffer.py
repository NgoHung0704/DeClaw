"""Short-term conversation buffer (DCL-052).

A size-bounded, in-memory ring over LangChain messages. This is the agent's
*working* memory: the last N messages of the live conversation, cheap to read
on every turn. It deliberately does NOT persist anything — durable recall is
the job of semantic (DCL-053) and episodic (DCL-054) memory.

Relationship to the context-window machinery (DCL-014/015): those trim the
*model-facing view* of a full history that lives in ``AgentState``; the buffer
is an upstream, hard bound on how much history a caller keeps around at all
(the Phase 9 gateway holds one buffer per conversation instead of an unbounded
message list).

Eviction is strict FIFO — when the bound is hit, the oldest message goes, no
exceptions and no special-casing of message types. Anything worth keeping
longer than the ring must be promoted to long-term memory by the caller.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator

from langchain_core.messages import BaseMessage


class ConversationBuffer:
    """Bounded FIFO ring of conversation messages."""

    def __init__(self, max_messages: int) -> None:
        if max_messages < 1:
            raise ValueError(f"max_messages must be >= 1 (got {max_messages}).")
        self._max = max_messages
        self._ring: deque[BaseMessage] = deque(maxlen=max_messages)

    @property
    def max_messages(self) -> int:
        return self._max

    def append(self, message: BaseMessage) -> None:
        """Add one message; silently evicts the oldest when full."""
        self._ring.append(message)

    def extend(self, messages: Iterable[BaseMessage]) -> None:
        """Add several messages in order (same eviction rule)."""
        self._ring.extend(messages)

    @property
    def messages(self) -> list[BaseMessage]:
        """Current contents, oldest first. A copy — mutating it is safe."""
        return list(self._ring)

    def clear(self) -> None:
        self._ring.clear()

    def __len__(self) -> int:
        return len(self._ring)

    def __iter__(self) -> Iterator[BaseMessage]:
        return iter(list(self._ring))
