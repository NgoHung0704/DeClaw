"""A/B/C experiment: which system prompt keeps Mistral 7B's tool-calling alive?

Background: the full A/B probe showed the DCL-017 system prompt drops tool
accuracy from 26/38 to 3/38 — the model *describes* tool calls instead of
emitting them. This script measures three fix candidates against the raw
no-system control, on a 16-prompt balanced subset of ``BENCHMARK_CORPUS_V0``
(cheap: ~4 min per variant instead of ~13).

Variants:

* control — no system prompt (the probe baseline).
* (a) minimal — 2-line identity + language pin; no principles.
* (b) current+tool-rule — the full DCL-017 prompt plus an explicit
  "call the tool, don't describe it" instruction.
* (c) minimal+tool-rule — (a) plus the same instruction.
* (d) human-prefix — NO system message; the minimal identity text is
  prepended to the user's message instead (tests whether instruction text
  hurts only when delivered via the system role).

Run with: ``uv run python scripts/probe_prompt_variants.py [--only SUBSTR]``.

Results (2026-06-11, Mistral 7B): control 8/13, (a) 3/13, (b) 0/13, (c) 0/13.
Any system message degrades tool-calling; tool-related wording kills it.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
from typing import Any

from langchain_core.messages import SystemMessage
from rich.console import Console

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.eval import (
    BENCHMARK_CORPUS_V0,
    PROBE_TOOLS,
    Prompt,
    TurnResult,
    run_prompt,
    summarize,
)
from declaw.brain.loop import build_agent_graph
from declaw.brain.ollama_client import OllamaClient
from declaw.brain.prompts import system_prompt
from declaw.config import get_settings


def _subset() -> list[Prompt]:
    """A balanced 16-prompt slice of the frozen corpus (deterministic)."""
    quota = {
        "direct-en": 4,
        "direct-fr": 3,
        "implicit-en": 3,
        "implicit-fr": 2,
        "no-tool-en": 1,
        "no-tool-fr": 1,
        "ambiguous": 1,
        "injection": 1,
    }
    taken: dict[str, int] = {key: 0 for key in quota}
    picked: list[Prompt] = []
    for prompt in BENCHMARK_CORPUS_V0:
        cat = prompt.category
        if cat in quota and taken[cat] < quota[cat]:
            picked.append(prompt)
            taken[cat] += 1
    return picked


_TOOL_RULE = (
    "When one of your tools can satisfy the request, CALL the tool. "
    "Never describe the call or write code for it; emit the tool call itself. "
    "Answer in plain text only when no tool fits."
)

_MINIMAL = (
    "You are DeClaw, a private AI assistant running locally on the user's "
    "machine. Answer in English.\n"
)


# (label, system message or None, human-message prefix or None)
Variant = tuple[str, SystemMessage | None, str | None]


def _variants() -> list[Variant]:
    current = system_prompt("en")
    return [
        ("control (no system)", None, None),
        ("(a) minimal", SystemMessage(content=_MINIMAL), None),
        (
            "(b) current + tool rule",
            SystemMessage(content=current + "\n" + _TOOL_RULE + "\n"),
            None,
        ),
        (
            "(c) minimal + tool rule",
            SystemMessage(content=_MINIMAL + "\n" + _TOOL_RULE + "\n"),
            None,
        ),
        ("(d) human-prefix", None, _MINIMAL),
    ]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        default=None,
        help="Run only variants whose label contains this substring.",
    )
    args = parser.parse_args()

    console = Console()
    settings = get_settings()

    health = await OllamaClient().health()
    if not health.reachable:
        console.print(f"[red]Ollama not reachable[/red]: {health.error}")
        return 1
    if not health.has_model(settings.model):
        console.print(f"[red]Model {settings.model!r} not pulled.[/red]")
        return 1

    subset = _subset()
    tools_by_name: dict[str, Any] = {t.name: t for t in PROBE_TOOLS}
    graph = build_agent_graph(model=build_ollama_model(PROBE_TOOLS), tools=PROBE_TOOLS)

    variants = _variants()
    if args.only:
        variants = [v for v in variants if args.only in v[0]]

    all_results: dict[str, list[TurnResult]] = {}
    for label, system, human_prefix in variants:
        console.print(f"\n[bold]Variant {label}[/bold] - {len(subset)} prompts...")
        results: list[TurnResult] = []
        for i, prompt in enumerate(subset, 1):
            if human_prefix is not None:
                prompt = dataclasses.replace(prompt, text=human_prefix + "\n" + prompt.text)
            r = await run_prompt(graph, prompt, tools_by_name, system=system)
            marker = "ERR" if r.error else (r.called_tool or "-")
            console.print(
                f"  [{i:2d}/{len(subset)}] [{prompt.category:11s}] "
                f"{r.elapsed_s:5.1f}s  called={marker}"
            )
            results.append(r)
        all_results[label] = results

    for label, results in all_results.items():
        summarize(label, results, console)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
