"""Typer CLI entry point for DeClaw.

Implements the DCL-001 skeleton: ``start``, ``stop``, ``status``, ``chat``,
``version``. Concrete behavior is filled in by later tickets (DCL-003 wires
``status`` to Ollama; DCL-016 fills out ``chat``; DCL-120 implements the
gateway started by ``start``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from declaw import __version__
from declaw.brain.ollama_client import OllamaClient, OllamaHealth
from declaw.config import get_settings

if TYPE_CHECKING:  # heavy imports stay lazy at runtime
    from declaw.audit.logger import DbAuditLogger
    from declaw.memory.episodic import EpisodicMemory
    from declaw.memory.semantic import SemanticMemory

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
    from declaw.audit.logger import DbAuditLogger
    from declaw.audit.sinks import composite_sink, quarantine_db_sink
    from declaw.brain.repl import (
        build_brain,
        make_console_confirmation_provider,
        run_chat,
    )
    from declaw.db.engine import ensure_schema, get_engine, get_sessionmaker
    from declaw.sanitizer.classifier import build_ollama_classifier
    from declaw.sanitizer.quarantine import QuarantineStore, log_audit_sink
    from declaw.sanitizer.sanitizer import Sanitizer
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

    # Principle #7: every tool call / confirmation decision / quarantine lands
    # in the durable audit trail (SQLite, DCL-060/061).
    engine = get_engine()
    audit = DbAuditLogger(get_sessionmaker())

    # Principle #4: external content (file reads) must pass the sanitizer before
    # the brain sees it. A separate session (sanitizer_model) classifies the
    # output; UNSAFE content is quarantined and never reaches the model. The
    # quarantine store reports to both the operational log and the audit DB.
    quarantine = QuarantineStore(
        audit_sink=composite_sink(log_audit_sink, quarantine_db_sink(audit))
    )
    sanitizer = (
        Sanitizer(build_ollama_classifier(language=settings.language), quarantine=quarantine)
        if settings.sanitizer_required
        else None
    )
    tools = default_registry().langchain_tools(
        settings.language, approve, sanitizer=sanitizer, audit=audit
    )
    graph = build_brain(tools)

    sanitizer_state = "on" if sanitizer is not None else "off"
    console.print(
        f"[green]DeClaw chat[/green] - model [bold]{settings.model}[/bold], "
        f"workspace [bold]{settings.workspace_dir}[/bold], "
        f"sanitizer [bold]{sanitizer_state}[/bold], audit [bold]on[/bold]. "
        "Type [bold]/exit[/bold] to quit."
    )

    def read() -> str | None:
        try:
            return console.input("[bold cyan]you>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            return None

    def write(line: str) -> None:
        console.print(line)

    # No system prompt is seeded. Historical reason: a 2026-06-11 prompt-variant
    # probe showed ANY instruction text (system role or human prefix, minimal or
    # full) collapsed Mistral 7B tool-calling from 62% to 0-23%. After swapping
    # the default to Qwen2.5 3B on 2026-06-28 (tool-calling-tuned), the Mistral-
    # specific failure should be gone, but re-enabling system prompt requires an
    # A/B probe first - see CLAUDE.md Open decision "System prompt x tool-calling".
    # DCL-017's system_message() stays available for compositions that don't bind tools.
    async def _session() -> None:
        # Schema + chat share one event loop so aiosqlite connections created
        # during bootstrap stay usable for audit writes during the REPL.
        await ensure_schema(engine)
        await run_chat(graph, read=read, write=write, debug=debug)

    asyncio.run(_session())
    console.print("[dim]bye[/dim]")


memory_app = typer.Typer(
    name="memory",
    help="Export or wipe DeClaw's long-term memory (GDPR).",
    no_args_is_help=True,
)
cli.add_typer(memory_app)


def _build_memory_stack() -> tuple[SemanticMemory, EpisodicMemory, DbAuditLogger]:
    """Assemble (semantic, episodic, audit) over the real stores.

    Shared by ``memory export`` and ``memory wipe``. Imports are lazy so the
    lightweight commands don't pay for chroma/langchain.
    """
    from declaw.audit.logger import DbAuditLogger
    from declaw.db.engine import get_engine, get_sessionmaker
    from declaw.memory.chroma import build_chroma_client, get_collection
    from declaw.memory.crypto import get_or_create_fernet
    from declaw.memory.embeddings import build_ollama_embedder
    from declaw.memory.episodic import EpisodicMemory
    from declaw.memory.semantic import SemanticMemory

    get_engine()  # materializes data_dir
    collection = get_collection(build_chroma_client(), "semantic")
    semantic = SemanticMemory(
        collection, build_ollama_embedder(), fernet=get_or_create_fernet()
    )
    episodic = EpisodicMemory(get_sessionmaker())
    audit = DbAuditLogger(get_sessionmaker())
    return semantic, episodic, audit


@memory_app.command("export")
def memory_export(
    out: str = typer.Option(
        "", "--out", help="Destination JSON file (default: data_dir/exports/...)."
    ),
) -> None:
    """Export all stored memory as a JSON archive (GDPR portability)."""
    from datetime import datetime, timezone

    from declaw.db.engine import ensure_schema, get_engine
    from declaw.memory.gdpr import export_memory

    settings = get_settings()
    if out:
        destination = Path(out).expanduser()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destination = settings.data_dir / "exports" / f"declaw-memory-{stamp}.json"

    semantic, episodic, audit = _build_memory_stack()

    async def _run() -> Path:
        await ensure_schema(get_engine())
        return await export_memory(
            destination, semantic=semantic, episodic=episodic, audit=audit
        )

    written = asyncio.run(_run())
    console.print(f"[green]Memory exported[/green] to [bold]{written}[/bold]")


@memory_app.command("wipe")
def memory_wipe(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Delete ALL stored memory (right to be forgotten). Irreversible."""
    from declaw.db.engine import ensure_schema, get_engine
    from declaw.memory.gdpr import WipeReport, wipe_memory

    if not yes:
        confirmed = typer.confirm(
            "This permanently deletes ALL semantic memories and task history. Continue?"
        )
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow] Nothing was deleted.")
            raise typer.Exit(code=1)

    semantic, episodic, audit = _build_memory_stack()

    async def _run() -> WipeReport:
        await ensure_schema(get_engine())
        return await wipe_memory(semantic=semantic, episodic=episodic, audit=audit)

    report = asyncio.run(_run())
    console.print(
        f"[green]Memory wiped.[/green] Removed {report.semantic_removed} semantic "
        f"memories and {report.episodes_removed} episodes. "
        "An anonymized record (counts only) was kept in the audit trail."
    )


def main() -> None:
    """Module entry point used by ``python -m declaw.main``."""
    cli()


if __name__ == "__main__":
    main()
