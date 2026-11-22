"""Model-facing context selection using LangChain helpers (DCL-014).

Full history stays in AgentState. Counts use the library's approximate helper
configured for three characters per token, not an exact serving-model guarantee.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

from declaw.brain.loop import ModelCallable

# Historical Mistral-derived budget; not a verified serving-model context limit.
MISTRAL_CONTEXT_TOKENS = 32768
_RESPONSE_RESERVE_TOKENS = 2048
DEFAULT_HARD_CAP = MISTRAL_CONTEXT_TOKENS - _RESPONSE_RESERVE_TOKENS  # 30720
DEFAULT_SOFT_CAP = 24000

# Keep the previous character ratio while using the library's message handling.
DEFAULT_TOKEN_COUNTER = partial(count_tokens_approximately, chars_per_token=3)


class ContextWindowExceededError(ValueError):
    """The required current context cannot fit the configured estimated budget."""


def fit_to_window(
    messages: Sequence[BaseMessage],
    *,
    hard_cap: int = DEFAULT_HARD_CAP,
    soft_cap: int = DEFAULT_SOFT_CAP,
    counter: Callable[[Sequence[BaseMessage]], int] = DEFAULT_TOKEN_COUNTER,
) -> list[BaseMessage]:
    """Select recent complete turns without modifying the caller's history.

    Above ``hard_cap``, target ``soft_cap`` using LangChain's message trimmer.
    Always retain the leading system instruction and the latest human turn,
    including all subsequent tool exchanges. That required context may exceed
    the soft target, but raises ``ContextWindowExceededError`` above the hard
    cap. Incoming tool history is assumed valid; this is not a repair helper.
    """
    # Validate the budget ordering before selecting messages.
    if not 0 <= soft_cap <= hard_cap:
        raise ValueError("Expected 0 <= soft_cap <= hard_cap")

    # Copy the history and skip trimming while it fits the hard cap.
    msgs = list(messages)
    if counter(msgs) <= hard_cap:
        return msgs

    # Find the start of the current user turn, including subsequent tool exchanges.
    latest_human = next(
        (i for i in range(len(msgs) - 1, -1, -1) if isinstance(msgs[i], HumanMessage)),
        None,
    )
    # Protect the leading system instruction and current turn; keep all if no user exists.
    head = msgs[:1] if msgs and isinstance(msgs[0], SystemMessage) else []
    required = msgs if latest_human is None else [*head, *msgs[latest_human:]]
    # Fail early when even the required context exceeds the hard cap.
    required_cost = counter(required)
    if required_cost > hard_cap:
        raise ContextWindowExceededError(
            f"Required context estimates {required_cost} tokens; hard cap is {hard_cap}"
        )

    def retains_required(selected: list[BaseMessage]) -> bool:
        # Preserve the required context within the hard cap.
        if latest_human is not None:
            tail = msgs[latest_human:]
        else:
            tail = msgs

        if len(selected) < len(required):
            return False

        if head:
            if selected[0] is not head[0]:
                return False

        selected_tail = selected[-len(tail):]
        for selected_message, original_message in zip(selected_tail, tail, strict=True):
            if selected_message is not original_message:
                return False

        if counter(selected) > hard_cap:
            return False

        return True

    # Aim for the soft target, then allow more space to preserve the current turn.
    for budget in (soft_cap, hard_cap):
        # Keep recent whole messages, starting at a user boundary after any system message.
        selected = trim_messages(
            msgs,
            max_tokens=budget,
            token_counter=counter,
            strategy="last",
            include_system=True,
            allow_partial=False,
            start_on="human",
            end_on=None,
        )
        # Accept only a selection that retains the complete required context.
        if retains_required(selected):
            return selected
    # Fall back to the required context, whose cost was already checked above.
    return required


def with_context_window(
    model: ModelCallable,
    *,
    counter: Callable[[Sequence[BaseMessage]], int] = DEFAULT_TOKEN_COUNTER,
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
