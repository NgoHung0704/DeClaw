"""Run the sanitizer benchmark against the live Ollama classifier (DCL-047/048).

Thin runner over ``declaw.sanitizer.benchmark``. Builds the real
``build_ollama_classifier`` (a separate Mistral session) and runs it over the
locked corpora, reporting detection rate, false-positive rate (target < 2%,
DCL-047), and latency p50/p95 (target p95 < 500ms, DCL-048).

NOTE: the 500ms p95 target assumes a fast/GPU-served classifier; Mistral 7B on
CPU will be far slower per call. The harness reports the real numbers so the
target can be tracked as the model/hardware changes.

Usage::

    uv run python scripts/sanitizer_benchmark.py
    uv run python scripts/sanitizer_benchmark.py --quick   # 6-sample smoke
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
from declaw.sanitizer.corpus import BENIGN_CORPUS, INJECTION_CORPUS


def _print_report(report: BenchmarkReport, console: Console) -> None:
    table = Table(title="Sanitizer benchmark")
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
    _print_report(report, console)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
