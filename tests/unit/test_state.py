"""Unit tests for AgentState (DCL-011).

Focus: the slots exist with sane defaults, and the whole state round-trips
through JSON with message subclasses preserved (the acceptance criterion).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from declaw.brain.state import AgentState


def test_defaults_are_empty() -> None:
    state = AgentState()
    assert state.messages == []
    assert state.scratchpad == ""
    assert state.plan == []
    assert state.tool_calls == []
    assert state.audit_refs == []


def test_serialize_deserialize_round_trip() -> None:
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"message": "x"}, "id": "c1"}],
    )
    state = AgentState(
        messages=[
            HumanMessage(content="hello"),
            ai_call,
            ToolMessage(content="echo: x", tool_call_id="c1"),
            AIMessage(content="done"),
        ],
        scratchpad="working notes",
        plan=["find file", "summarize"],
        tool_calls=[{"name": "echo", "args": {"message": "x"}, "id": "c1"}],
        audit_refs=["evt-1", "evt-2"],
    )

    restored = AgentState.model_validate_json(state.model_dump_json())

    # Message subclasses survive the discriminated-union round-trip.
    assert [type(m).__name__ for m in restored.messages] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    assert restored.scratchpad == "working notes"
    assert restored.plan == ["find file", "summarize"]
    assert restored.audit_refs == ["evt-1", "evt-2"]
    assert restored == state
