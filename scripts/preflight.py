"""Pre-flight check entry point.

Run with::

    uv run python scripts/preflight.py

Exit code is 0 if all checks pass, 1 otherwise. Failures print an
actionable remedy on stderr so the operator can fix them without
reading the source.
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console
from rich.table import Table

from declaw.preflight import CheckResult, run_all


def render(results: list[CheckResult]) -> int:
    console = Console()
    table = Table(title="DeClaw pre-flight", show_lines=False)
    table.add_column("check", style="cyan", no_wrap=True)
    table.add_column("status")
    table.add_column("message", style="white")

    for r in results:
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        table.add_row(r.name, status, r.message)
    console.print(table)

    failed = [r for r in results if not r.passed]
    if failed:
        console.print("\n[red bold]Action required:[/red bold]")
        for r in failed:
            if r.remedy:
                console.print(f"  • [cyan]{r.name}[/cyan]: {r.remedy}")
        return 1
    console.print("\n[green bold]All checks passed.[/green bold]")
    return 0


def main() -> None:
    results = asyncio.run(run_all())
    sys.exit(render(results))


if __name__ == "__main__":
    main()
