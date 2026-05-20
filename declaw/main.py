"""Typer CLI entry point for DeClaw.

Implements the DCL-001 skeleton: ``start``, ``stop``, ``status``, ``chat``,
``version``. Concrete behavior is filled in by later tickets (DCL-003 wires
``status`` to Ollama; DCL-016 fills out ``chat``; DCL-120 implements the
gateway started by ``start``).
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from declaw import __version__
from declaw.brain.ollama_client import OllamaClient, OllamaHealth
from declaw.config import get_settings

cli = typer.Typer(
    name="declaw",
    help="DeClaw — Your private AI agent. Runs local. Explains everything.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@cli.command()
def version() -> None:
    """Print the DeClaw version."""
    console.print(f"DeClaw [bold]{__version__}[/bold]")


@cli.command()
def status() -> None:
    """Show core configuration and runtime health."""
    settings = get_settings()
    health = asyncio.run(OllamaClient().health())

    table = Table(title="DeClaw status", show_lines=False)
    table.add_column("setting", style="cyan", no_wrap=True)
    table.add_column("value", style="white")
    table.add_row("version", __version__)
    table.add_row("host", settings.host)
    table.add_row("port", str(settings.port))
    table.add_row("language", settings.language)
    table.add_row("model", settings.model)
    table.add_row("sanitizer_model", settings.sanitizer_model)
    table.add_row("embedding_model", settings.embedding_model)
    table.add_row("ollama_base_url", settings.ollama_base_url)
    table.add_row("ollama_reachable", _format_reachable(health))
    table.add_row(
        f"ollama_has_{settings.model}",
        "[green]yes[/green]" if health.has_model(settings.model) else "[red]no[/red]",
    )
    table.add_row("data_dir", str(settings.data_dir))
    table.add_row("workspace_dir", str(settings.workspace_dir))
    table.add_row("docker_sandbox_required", str(settings.require_docker_sandbox))
    table.add_row("sanitizer_required", str(settings.sanitizer_required))
    table.add_row("plugin_signature_required", str(settings.plugin_signature_required))
    table.add_row("block_external_network", str(settings.block_external_network))
    console.print(table)


def _format_reachable(health: OllamaHealth) -> str:
    if health.reachable:
        return f"[green]yes[/green] (v{health.version})"
    return f"[red]no[/red] ({health.error})"


@cli.command()
def start() -> None:
    """Start the DeClaw gateway. (Implemented in DCL-120.)"""
    console.print("[yellow]start[/yellow]: gateway not implemented yet (DCL-120).")
    raise typer.Exit(code=1)


@cli.command()
def stop() -> None:
    """Stop a running DeClaw gateway. (Implemented in DCL-120.)"""
    console.print("[yellow]stop[/yellow]: gateway not implemented yet (DCL-120).")
    raise typer.Exit(code=1)


@cli.command()
def chat(
    debug: bool = typer.Option(False, "--debug", help="Enable verbose tracing."),
) -> None:
    """Start an interactive chat REPL. (Implemented in DCL-016.)"""
    _ = debug
    console.print("[yellow]chat[/yellow]: REPL not implemented yet (DCL-016).")
    raise typer.Exit(code=1)


def main() -> None:
    """Module entry point used by ``python -m declaw.main``."""
    cli()


if __name__ == "__main__":
    main()
