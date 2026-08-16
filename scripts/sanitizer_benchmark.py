"""Run the sanitizer benchmark against the live Ollama classifier (DCL-047/048).

Thin runner over ``declaw.sanitizer.benchmark``. Builds the real
``build_ollama_classifier`` (a separate Mistral session) and runs it over the
locked corpora, reporting detection rate, false-positive rate (target < 2%,
DCL-047), and latency p50/p95 (target p95 < 500ms, DCL-048).

Two corpora are reported, and the **gap between them is the point**: the
development corpus was written here and its phrasings inform the prompt's
few-shot examples, so a good score there only says "we kept what we tuned for".
The held-out set is external text no prompt has ever seen. On 2026-07-26 that
gap was 91.7% vs ~70% — the classifier had learned our wordings, not the
concept. Report both or the number flatters itself.

NOTE: the p95 < 500ms target is unreachable for any local LLM classifier
(fastest measured: 1.46s on a 3b; the shipped 7b: ~4.9s). An encoder classifier
does it in ~30ms, which says the target is the wrong architecture rather than
impossible — see CLAUDE.md, "Sanitizer model capability".

Usage::

    uv run python scripts/sanitizer_benchmark.py
    uv run python scripts/sanitizer_benchmark.py --quick     # 6-sample smoke
    uv run python scripts/sanitizer_benchmark.py --dev-only  # skip held-out
"""

from __future__ import annotations

import argparse
import asyncio

from rich.console import Console
from rich.table import Table

from declaw.brain.ollama_client import OllamaClient
from declaw.config import get_settings
from declaw.sanitizer.benchmark import BenchmarkReport, run_benchmark
from declaw.sanitizer.classifier import build_ollama_classifier
from declaw.sanitizer.corpus import (
    BENIGN_CORPUS,
    HELDOUT_BENIGN,
    HELDOUT_INJECTIONS,
    INJECTION_CORPUS,
)


def _print_report(report: BenchmarkReport, console: Console, title: str) -> None:
    table = Table(title=title)
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", style="white")
    table.add_row("injections tested", str(len(report.injection_results)))
    table.add_row("benign tested", str(len(report.benign_results)))
    table.add_row("detection rate", f"{report.detection_rate:.1%}")
    fp = report.false_positive_rate
    fp_ok = "[green]OK[/green]" if report.meets_fp_target else "[red]FAIL[/red]"
    table.add_row("false-positive rate", f"{fp:.1%} (target <2%) {fp_ok}")
    table.add_row("latency p50", f"{report.latency_p50:.3f}s")
    lat_ok = "[green]OK[/green]" if report.meets_latency_target else "[red]FAIL[/red]"
    table.add_row("latency p95", f"{report.latency_p95:.3f}s (target <0.5s) {lat_ok}")
    console.print(table)

    if report.missed_injections:
        console.print("\n[red]Missed injections (ruled SAFE):[/red]")
        for r in report.missed_injections:
            console.print(f"  [{r.language}/{r.category}] {r.text[:80]}")
    if report.false_positives:
        console.print("\n[yellow]False positives (benign ruled UNSAFE):[/yellow]")
        for r in report.false_positives:
            console.print(f"  [{r.language}/{r.category}] {r.text[:80]}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quick", action="store_true", help="Run a small 6-sample smoke subset."
    )
    parser.add_argument(
        "--dev-only",
        action="store_true",
        help="Skip the held-out set (faster, but the number then flatters itself).",
    )
    args = parser.parse_args()

    console = Console()
    settings = get_settings()

    health = await OllamaClient().health()
    if not health.reachable:
        console.print(
            f"[red]Ollama not reachable[/red] at {settings.ollama_base_url}: "
            f"{health.error}"
        )
        return 1
    if not health.has_model(settings.sanitizer_model):
        console.print(
            f"[red]Sanitizer model {settings.sanitizer_model!r} not pulled.[/red] "
            f"Run: ollama pull {settings.sanitizer_model}"
        )
        return 1

    classify = build_ollama_classifier()
    if args.quick:
        injections = INJECTION_CORPUS[:3] + INJECTION_CORPUS[-3:]
        benign = BENIGN_CORPUS[:3] + BENIGN_CORPUS[-3:]
    else:
        injections = None
        benign = None

    console.print("[bold]Running sanitizer benchmark...[/bold] (one call per sample)")
    report = await run_benchmark(classify, injections=injections, benign=benign)
    _print_report(report, console, "Sanitizer benchmark - development corpus (seen)")

    if args.quick or args.dev_only:
        console.print(
            "\n[yellow]Held-out set skipped.[/yellow] The development score alone "
            "does not measure generalization."
        )
        return 0

    console.print(
        "\n[bold]Running held-out set...[/bold] (external text, never in a prompt)"
    )
    heldout = await run_benchmark(
        classify, injections=HELDOUT_INJECTIONS, benign=HELDOUT_BENIGN
    )
    _print_report(heldout, console, "Sanitizer benchmark - held-out (unseen)")

    drop = report.detection_rate - heldout.detection_rate
    console.print(
        f"\n[bold]Generalization gap:[/bold] detection {report.detection_rate:.1%} "
        f"(seen) vs {heldout.detection_rate:.1%} (unseen) = "
        f"[{'red' if drop > 0.05 else 'green'}]{drop:+.1%}[/]"
    )
    if drop > 0.05:
        console.print(
            "[yellow]A large gap means the classifier learned our phrasings rather "
            "than the concept. Fix the concept, do not tune against held-out "
            "samples.[/yellow]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
