"""Second-Mistral sanitizer classifier (DCL-040).

The sanitizer runs as a **separate** Ollama session from the brain (Principle
#4 / DCL-040 acceptance: "Sanitizer has no shared state with the brain"). That
separation is enforced two ways here:

1. A distinct ``ChatOllama`` built from ``settings.sanitizer_model`` — its own
   model handle, never the brain's bound, tool-aware model.
2. Every classification is a **fresh, stateless call**: the message list is
   rebuilt each time as ``[locked system prompt, fenced untrusted content]``.
   No conversation history, no scratchpad, no tool schemas are ever passed in,
   so an injection has no brain state to reach and nothing to hijack.

The model is forced into the :class:`SanitizerVerdict` schema via
``with_structured_output``. The classifier **fails closed**: any error, timeout,
or output that does not parse as a verdict becomes ``UNSAFE`` (see
``unsafe_fallback``) — we never let an unparseable response through as SAFE.

Like ``declaw.brain.chat_model``, the live model is exposed behind a simple
``Classifier`` callable seam so the orchestrator and tests can inject a fake
classifier and run with no Ollama daemon.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_ollama import ChatOllama

from declaw.config import Language, get_settings
from declaw.sanitizer.prompts import sanitizer_system_message, wrap_untrusted
from declaw.sanitizer.sanitizer import Classifier
from declaw.sanitizer.verdict import SanitizerVerdict, unsafe_fallback


def _coerce_verdict(raw: object) -> SanitizerVerdict:
    """Turn ``with_structured_output``'s result into a verdict, fail-closed."""
    if isinstance(raw, SanitizerVerdict):
        return raw
    if isinstance(raw, dict):
        try:
            return SanitizerVerdict.model_validate(raw)
        except Exception:  # noqa: BLE001 - bad parse must fail closed
            return unsafe_fallback("sanitizer returned an unparseable verdict")
    return unsafe_fallback("sanitizer returned an unexpected response type")


def build_ollama_classifier(
    *,
    model: str | None = None,
    base_url: str | None = None,
    language: Language | None = None,
) -> Classifier:
    """Build a ``Classifier`` backed by a separate Ollama session.

    ``model`` defaults to ``settings.sanitizer_model`` (kept distinct from the
    brain's ``settings.model``); ``base_url`` and ``language`` default to
    Settings. ``temperature=0`` keeps the SAFE/UNSAFE decision deterministic.
    """
    settings = get_settings()
    llm = ChatOllama(
        model=model or settings.sanitizer_model,
        base_url=base_url or settings.ollama_base_url,
        temperature=0,
    )
    structured = llm.with_structured_output(SanitizerVerdict)
    system = sanitizer_system_message(language)

    async def classify(content: str) -> SanitizerVerdict:
        # Rebuilt every call: no shared state with the brain (DCL-040).
        messages: list[BaseMessage] = [
            system,
            HumanMessage(content=wrap_untrusted(content)),
        ]
        try:
            raw = await structured.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - any failure must fail closed
            return unsafe_fallback(f"sanitizer error: {type(exc).__name__}")
        return _coerce_verdict(raw)

    return classify
