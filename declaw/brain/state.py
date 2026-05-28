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

from typing import Annotated

from langchain_core.messages import AnyMessage, ToolCall
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """Canonical state threaded through the agentic loop."""

    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    scratchpad: str = ""
    plan: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
