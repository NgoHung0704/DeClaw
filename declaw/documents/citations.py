"""Render sources from retrieval metadata, never from model output.

DCL-111 asks that every answer cite its source. A 3B model cannot be prompted
into doing that reliably — the same finding that made DCL-062's audit summaries
deterministic templates. So the source list is built from what was actually
retrieved: the model may cite inline or not, and the user still sees exactly
which passages the answer was drawn from. A citation here cannot be
hallucinated, because no model wrote it.
"""

from __future__ import annotations

from declaw.config import Language
from declaw.documents.models import SearchHit
from declaw.documents.search import SearchOutcome

_L = {
    "en": {
        "sources": "Sources:",
        "none": "No documents matched. Have you run 'declaw index' on your workspace?",
        "withheld": "{count} passage(s) were withheld because they looked unsafe to read.",
    },
    "fr": {
        "sources": "Sources :",
        "none": "Aucun document ne correspond. Avez-vous lancé « declaw index » ?",
        "withheld": "{count} passage(s) ont été écartés car ils semblaient dangereux à lire.",
    },
}


def format_source(hit: SearchHit) -> str:
    """Render one hit's origin: 'contrat.pdf p.12-13', 'compta.xlsx [Budget]'."""
    if hit.sheet:
        return f"{hit.path} [{hit.sheet}]"
    if hit.page is not None:
        end = hit.page_end if hit.page_end is not None else hit.page
        span = f"{hit.page}" if end == hit.page else f"{hit.page}-{end}"
        return f"{hit.path} p.{span}"
    if hit.heading:
        return f"{hit.path} - {hit.heading}"
    return hit.path


def render_outcome(outcome: SearchOutcome, language: Language) -> str:
    """Render retrieved passages plus a sources block, for the model to read."""
    strings = _L[language]
    if not outcome.hits:
        text = strings["none"]
        if outcome.withheld:
            text += "\n" + strings["withheld"].format(count=outcome.withheld)
        return text

    passages = [f"[{i}] {hit.text}" for i, hit in enumerate(outcome.hits, start=1)]
    sources = [f"[{i}] {format_source(hit)}" for i, hit in enumerate(outcome.hits, start=1)]
    parts = ["\n\n".join(passages), strings["sources"], "\n".join(sources)]
    if outcome.withheld:
        parts.append(strings["withheld"].format(count=outcome.withheld))
    return "\n\n".join(parts)
