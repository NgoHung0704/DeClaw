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
    """Start an interactive chat REPL backed by the local brain."""
    # Imported lazily so `version`/`status` don't pay the langchain import cost.
    from declaw.brain.prompts import system_message
    from declaw.brain.repl import (
        build_brain,
        make_console_confirmation_provider,
        run_chat,
    )
    from declaw.tools.registry import default_registry

    settings = get_settings()
    health = asyncio.run(OllamaClient().health())
    if not health.reachable:
        console.print(
            f"[red]Ollama not reachable[/red] at {settings.ollama_base_url} "
            f"({health.error}). Start Ollama, then try again."
        )
        raise typer.Exit(code=1)
    if not health.has_model(settings.model):
        console.print(
            f"[red]Model {settings.model!r} not pulled.[/red] "
            f"Run: [bold]ollama pull {settings.model}[/bold]"
        )
        raise typer.Exit(code=1)

    # The filesystem tools operate inside the workspace; make sure it exists.
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    # WRITE/DESTRUCTIVE tools are gated behind a console confirmation prompt;
    # READ tools auto-run. markup=False so the "[y/N]" hint and any "[" in the
    # rendered args are not parsed as Rich tags.
    def confirm_prompt(question: str) -> str:
        return console.input(question, markup=False, emoji=False)

    approve = make_console_confirmation_provider(confirm_prompt, settings.language)
    tools = default_registry().langchain_tools(settings.language, approve)
    graph = build_brain(tools)

    console.print(
        f"[green]DeClaw chat[/green] - model [bold]{settings.model}[/bold], "
        f"workspace [bold]{settings.workspace_dir}[/bold]. "
        "Type [bold]/exit[/bold] to quit."
    )

    def read() -> str | None:
        try:
            return console.input("[bold cyan]you>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            return None

    def write(line: str) -> None:
        console.print(line)

    asyncio.run(run_chat(graph, read=read, write=write, debug=debug, system=system_message()))
    console.print("[dim]bye[/dim]")


def main() -> None:
    """Module entry point used by ``python -m declaw.main``."""
    cli()


if __name__ == "__main__":
    main()
