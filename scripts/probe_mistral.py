"""Probe Mistral against ``BENCHMARK_CORPUS_V0`` (Phase 1 review spike).

Thin runner over ``declaw.brain.eval``. By default it runs the raw graph
(``build_ollama_model`` + ``build_agent_graph``), which matches the production
``build_brain`` composition. Pass ``--with-repair`` to also run a variant
wrapped with ``with_tool_call_repair`` for comparison.

Usage::

    uv run python scripts/probe_mistral.py
    uv run python scripts/probe_mistral.py --with-repair
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from rich.console import Console

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.eval import (
    BENCHMARK_CORPUS_V0,
    PROBE_TOOLS,
    TurnResult,
    per_prompt_table,
    run_prompt,
    summarize,
)
from declaw.brain.loop import build_agent_graph
from declaw.brain.ollama_client import OllamaClient
from declaw.brain.prompts import system_message
from declaw.brain.repair import with_tool_call_repair
from declaw.config import get_settings


async def _run_variant(
    label: str,
    graph: Any,
    console: Console,
    tools_by_name: dict[str, Any],
    system: Any = None,
) -> list[TurnResult]:
    console.print(
        f"\n[bold]Probe ({label})[/bold] - {len(BENCHMARK_CORPUS_V0)} prompts..."
    )
    results: list[TurnResult] = []
    for i, prompt in enumerate(BENCHMARK_CORPUS_V0, 1):
        r = await run_prompt(graph, prompt, tools_by_name, system=system)
        marker = "ERR" if r.error else (r.called_tool or "-")
        console.print(
            f"  [{i:2d}/{len(BENCHMARK_CORPUS_V0)}] [{prompt.category:13s}] "
            f"{r.elapsed_s:5.1f}s  called={marker}"
        )
        results.append(r)
    return results


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--with-repair",
        action="store_true",
        help="Also run a variant wrapped with with_tool_call_repair.",
    )
    parser.add_argument(
        "--with-system",
        action="store_true",
        help=(
            "Also run a variant seeding the DCL-017 system prompt, to measure "
            "its effect on tool-calling (the declaw chat composition)."
        ),
    )
    args = parser.parse_args()

    console = Console()
    settings = get_settings()

    health = await OllamaClient().health()
    if not health.reachable:
        console.print(
            f"[red]Ollama not reachable[/red] at {settings.ollama_base_url}: {health.error}"
        )
        return 1
    if not health.has_model(settings.model):
        console.print(
            f"[red]Model {settings.model!r} not pulled.[/red] "
            f"Run: ollama pull {settings.model}"
        )
        return 1

    tools_by_name: dict[str, Any] = {t.name: t for t in PROBE_TOOLS}

    raw_graph = build_agent_graph(
        model=build_ollama_model(PROBE_TOOLS), tools=PROBE_TOOLS
    )
    # (label, graph, system message or None)
    runs: list[tuple[str, Any, Any]] = [("raw", raw_graph, None)]
    if args.with_system:
        runs.append(("with system prompt", raw_graph, system_message()))
    if args.with_repair:
        rep_graph = build_agent_graph(
            model=with_tool_call_repair(build_ollama_model(PROBE_TOOLS), PROBE_TOOLS),
            tools=PROBE_TOOLS,
        )
        runs.append(("with repair", rep_graph, None))

    all_results: dict[str, list[TurnResult]] = {}
    for label, graph, system in runs:
        all_results[label] = await _run_variant(
            label, graph, console, tools_by_name, system=system
        )

    for label, results in all_results.items():
        summarize(label, results, console)
        per_prompt_table(label, results, console)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
