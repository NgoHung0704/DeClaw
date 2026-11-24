"""Typed agent state for the brain (DCL-011).

``AgentState`` is the LangGraph state schema threaded through the agentic loop.
It is a Pydantic model (not a plain ``TypedDict``) so it validates on
construction and round-trips cleanly to/from JSON for persistence and audit.

Slots:

* ``messages``   - the running conversation. Uses the ``add_messages`` reducer
                   so loop nodes append rather than overwrite. ``AnyMessage`` is
                   a discriminated union, so message subclasses (Human/AI/Tool/
                   System) survive JSON round-trips.
* ``scratchpad`` - free-form working notes the agent keeps across steps.
* ``plan``       - the current plan as an ordered list of steps.
* ``tool_calls`` - a flat log of tool calls issued during the run (messages also
                   carry them inline; this is a convenience index).
* ``audit_refs`` - ids of ``AuditEvent`` rows linked to this run (Principle #7).

Only ``messages`` has a reducer; the other slots are last-write-wins. Later
tickets populate the planning/audit slots; DCL-011 defines the schema and
proves it serializes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import AnyMessage, ToolCall
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from rich.console import Console


class AgentState(BaseModel):
    """Canonical state threaded through the agentic loop."""

    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    scratchpad: str = ""
    plan: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)

    def pretty_print(self, console: Console | None = None) -> None:
        """Render a formatted dashboard of the agent state to the console."""
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        c = console if console is not None else Console()

        if self.messages:
            msg_table = Table(
                title="💬 Conversation Messages",
                show_header=True,
                header_style="bold magenta",
            )
            msg_table.add_column("Role", style="bold", width=10)
            msg_table.add_column("Content")

            role_colors = {
                "human": "green",
                "ai": "cyan",
                "tool": "yellow",
                "system": "magenta",
            }
            for m in self.messages:
                role = m.type
                color = role_colors.get(role, "white")
                content = m.content if isinstance(m.content, str) else str(m.content)

                if hasattr(m, "tool_calls") and m.tool_calls:
                    calls_str = "\n".join(
                        f"[bold yellow]⚙ Call:[/bold yellow] {tc['name']}({tc['args']})"
                        for tc in m.tool_calls
                    )
                    content = f"{content}\n{calls_str}".strip()

                msg_table.add_row(f"[{color}]{role.upper()}[/{color}]", content)

            c.print(msg_table)

        if self.plan:
            plan_str = "\n".join(
                f" [bold cyan]{i}.[/bold cyan] {step}"
                for i, step in enumerate(self.plan, 1)
            )
            c.print(Panel(plan_str, title="📋 Current Plan", border_style="cyan"))

        if self.scratchpad:
            c.print(
                Panel(
                    self.scratchpad,
                    title="📝 Scratchpad Notes",
                    border_style="yellow",
                )
            )

        if self.audit_refs:
            c.print(f"[dim]🔒 Audit Refs: {', '.join(self.audit_refs)}[/dim]")
