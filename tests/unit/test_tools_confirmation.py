"""Unit tests for the confirmation gate (DCL-022, DCL-125 / spec section 7).

A tiny ``_RecordingTool`` (DeclawTool subclass) appends to a module-level list
whenever its ``_arun`` runs. That lets us prove deny prevents ``_arun`` from
running at all - not merely from returning its result.

Validate-before-prompt (spec section 7, ratified decision 20.10): the wrapper
validates arguments against ``args_schema`` FIRST. Invalid arguments return a
validation-error observation to the model WITHOUT ever prompting; the prompt
displays the canonical validated dump; and the same validated object executes
on approval (identity, not re-parsing).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from declaw.tools.base import DeclawTool, ToolClass
from declaw.tools.confirmation import (
    always_approve,
    always_deny,
    wrap_tool_with_confirmation,
)


# --- Test scaffolding: recording DeclawTool subclasses ----------------------


_invocations: list[str] = []
_plan_runs: list[Any] = []


class _RecordedArgs(BaseModel):
    value: str


class _RecordingTool(DeclawTool[_RecordedArgs]):
    name: str = "recorder"
    description_en: str = "Record a value (EN)."
    description_fr: str = "Enregistre une valeur (FR)."
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_RecordedArgs] = _RecordedArgs

    async def _arun(self, args: _RecordedArgs) -> str:
        _invocations.append(args.value)
        return f"recorded: {args.value}"


class _PlanArgs(BaseModel):
    moves: list[str]
    dry_run: bool = False  # schema default: filled into the canonical dump


class _PlanTool(DeclawTool[_PlanArgs]):
    name: str = "planner"
    description_en: str = "Run a plan (EN)."
    description_fr: str = "Exécuter un plan (FR)."
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_PlanArgs] = _PlanArgs

    async def _arun(self, args: _PlanArgs) -> str:
        _plan_runs.append(args)
        return f"planned {len(args.moves)}"


@pytest.fixture(autouse=True)
def _isolate_invocations() -> Iterator[None]:
    _invocations.clear()
    _plan_runs.clear()
    yield
    _invocations.clear()
    _plan_runs.clear()


@pytest.fixture
def tool() -> _RecordingTool:
    return _RecordingTool()


class _ScriptedModel:
    """Async think-step returning canned replies (see declaw.brain.loop)."""

    def __init__(self, replies: list[BaseMessage]) -> None:
        self._replies = list(replies)

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return self._replies.pop(0)


# --- Approval path ----------------------------------------------------------


async def test_approve_runs_the_tool_and_returns_the_result(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "en", always_approve)
    result = await wrapped.ainvoke({"value": "hello"})
    assert result == "recorded: hello"
    assert _invocations == ["hello"]


# --- Denial path: localized + actually blocks _arun -------------------------


async def test_deny_returns_localized_denial_in_english(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "en", always_deny)
    result = await wrapped.ainvoke({"value": "hello"})
    assert result == "User denied the call to recorder."
    assert _invocations == []  # _arun must not run on deny


async def test_deny_returns_localized_denial_in_french(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "fr", always_deny)
    result = await wrapped.ainvoke({"value": "salut"})
    assert result == "L'utilisateur a refusé l'appel à recorder."
    assert _invocations == []


# --- Validate BEFORE prompt (spec section 7, ratified 20.10) -----------------


async def test_invalid_args_return_validation_observation_without_prompting(
    tool: _RecordingTool,
) -> None:
    """Invalid arguments mean there is nothing meaningful to approve: the
    provider must never be consulted, and the model gets the validation
    error directly as an observation (no exception escapes)."""

    async def must_not_be_called(
        t: DeclawTool[Any], args: dict[str, Any]
    ) -> bool:
        raise AssertionError("provider should not be called when args are invalid")

    wrapped = wrap_tool_with_confirmation(tool, "en", must_not_be_called)
    result = await wrapped.ainvoke({"wrong": "shape"})  # missing required 'value'

    assert "Invalid arguments for recorder" in result
    assert "fix the arguments" in result
    assert _invocations == []  # _arun never ran either


async def test_invalid_args_observation_localized_french(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "fr", always_approve)
    result = await wrapped.ainvoke({})
    assert "Arguments invalides pour recorder" in result
    assert _invocations == []


async def test_console_provider_never_sees_invalid_args(
    tool: _RecordingTool,
) -> None:
    """The console provider adopts the same ordering by going through the
    same wrapper: invalid args never reach the human as a question."""
    from declaw.brain.repl import make_console_confirmation_provider

    questions: list[str] = []

    def prompt(question: str) -> str:
        questions.append(question)
        return "y"

    provider = make_console_confirmation_provider(prompt, "en")
    wrapped = wrap_tool_with_confirmation(tool, "en", provider)
    result = await wrapped.ainvoke({"wrong": "shape"})

    assert "Invalid arguments for recorder" in result
    assert questions == []  # the human was never asked


async def test_prompt_shows_validated_dump_and_the_same_object_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt must show the canonical validated dump (defaults filled,
    undeclared keys stripped), and the validated object created BEFORE the
    prompt is the exact object that executes on approval."""
    captured: dict[str, Any] = {}

    async def spy(t: DeclawTool[Any], args: dict[str, Any]) -> bool:
        captured["args"] = args
        return True

    wrapped = wrap_tool_with_confirmation(_PlanTool(), "en", spy)

    validated_objects: list[Any] = []
    original = _PlanArgs.model_validate  # bound classmethod

    def counting_validate(data: object) -> Any:
        instance = original(data)
        validated_objects.append(instance)
        return instance

    monkeypatch.setattr(_PlanArgs, "model_validate", counting_validate)

    result = await wrapped.ainvoke({"moves": ["a.pdf", "b.pdf"], "extra": "noise"})

    assert result == "planned 2"
    # The provider (and so the prompt) sees the canonical validated dump:
    # the schema default is filled in, the undeclared key is gone.
    assert captured["args"] == {"moves": ["a.pdf", "b.pdf"], "dry_run": False}
    # Exactly ONE validation, and the object it produced is what ran:
    # the user approved exactly what executed (identity, not re-parsing).
    assert len(validated_objects) == 1
    assert _plan_runs == [validated_objects[0]]


async def test_invalid_args_reach_the_model_as_an_observation_not_a_bug() -> None:
    """End-to-end through the agent graph: a tool call with invalid arguments
    becomes a validation observation the model can act on — it is NOT the
    'unexpected tool failure / DeClaw bug' text, and no prompt happens."""
    from declaw.brain.loop import build_agent_graph

    async def must_not_be_called(
        t: DeclawTool[Any], args: dict[str, Any]
    ) -> bool:
        raise AssertionError("provider should not be called when args are invalid")

    wrapped = wrap_tool_with_confirmation(_RecordingTool(), "en", must_not_be_called)
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "recorder", "args": {}, "id": "call-1"}],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = build_agent_graph(model=model, tools=[wrapped])

    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert "Invalid arguments for recorder" in str(tool_msgs[0].content)
    assert "DeClaw bug" not in str(tool_msgs[0].content)
    assert _invocations == []


async def test_invalid_args_return_observation_on_the_audited_path(
    tool: _RecordingTool,
) -> None:
    """``declaw chat`` wires the audit wrapper around the gate on the
    production path; ordering must survive that composition. No approval
    prompt means no PermissionPromptEvent is emitted either, and the call is
    audited as "invalid" — forensically distinct from a call that ran ("ok")."""

    class _FakeAuditLogger:
        def __init__(self) -> None:
            self.events: list[Any] = []

        async def emit(self, event: Any) -> None:
            self.events.append(event)

    from declaw.audit.tooling import wrap_tool_with_audit

    audit = _FakeAuditLogger()
    inner = wrap_tool_with_confirmation(tool, "en", always_approve, audit=audit)
    audited = wrap_tool_with_audit(inner, tool=tool, language="en", audit=audit)

    result = await audited.ainvoke({})

    assert "Invalid arguments for recorder" in str(result)
    assert _invocations == []
    [event] = audit.events
    assert event.event_type == "tool.call"
    assert event.outcome == "invalid"


async def test_invalid_args_audited_as_invalid_in_french(
    tool: _RecordingTool,
) -> None:
    """The audit classification must not be English-only: the FR validation
    observation also audits as "invalid"."""

    class _FakeAuditLogger:
        def __init__(self) -> None:
            self.events: list[Any] = []

        async def emit(self, event: Any) -> None:
            self.events.append(event)

    from declaw.audit.tooling import wrap_tool_with_audit

    audit = _FakeAuditLogger()
    inner = wrap_tool_with_confirmation(tool, "fr", always_approve, audit=audit)
    audited = wrap_tool_with_audit(inner, tool=tool, language="fr", audit=audit)

    result = await audited.ainvoke({})

    assert "Arguments invalides pour recorder" in str(result)
    [event] = audit.events
    assert event.outcome == "invalid"


# --- Import guard for the langchain private-API hook (DCL-125) --------------


def test_import_fails_loudly_if_langchain_parse_input_hook_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A langchain upgrade that renames or reshapes ``BaseTool._parse_input``
    must break the import of the gate loudly: silently continuing would put
    langchain's own pre-validation back AHEAD of the gate (the exact ordering
    this module pins), so absent/incompatible hooks are a hard import error."""
    import importlib

    from langchain_core.tools import BaseTool

    import declaw.tools.confirmation as confirmation

    # Simulate the upgrade: the hook we override is gone.
    monkeypatch.delattr(BaseTool, "_parse_input")
    with pytest.raises(RuntimeError, match="_parse_input"):
        importlib.reload(confirmation)

    # Restore the real module state for every other test.
    monkeypatch.undo()
    importlib.reload(confirmation)


def test_import_fails_loudly_if_langchain_parse_input_signature_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same guard also catches a signature drift (renamed parameters)."""
    import importlib

    from langchain_core.tools import BaseTool

    import declaw.tools.confirmation as confirmation

    def reshaped_hook(self: object, raw_input: object, call_id: object) -> object:
        return raw_input

    monkeypatch.setattr(BaseTool, "_parse_input", reshaped_hook)
    with pytest.raises(RuntimeError, match="_parse_input"):
        importlib.reload(confirmation)

    monkeypatch.undo()
    importlib.reload(confirmation)


# --- Provider receives the right context -----------------------------------


async def test_provider_receives_the_tool_and_args(tool: _RecordingTool) -> None:
    captured: dict[str, Any] = {}

    async def spy(t: DeclawTool[Any], args: dict[str, Any]) -> bool:
        captured["tool"] = t
        captured["args"] = args
        return True

    wrapped = wrap_tool_with_confirmation(tool, "en", spy)
    await wrapped.ainvoke({"value": "x"})

    assert captured["tool"] is tool
    assert captured["args"] == {"value": "x"}


# --- Wrapped tool keeps the model-facing metadata --------------------------


def test_wrapped_tool_keeps_name_description_schema(
    tool: _RecordingTool,
) -> None:
    """The gate must be invisible to ``bind_tools`` - same name, locale
    description, and args_schema as the underlying DeclawTool."""
    wrapped_en = wrap_tool_with_confirmation(tool, "en", always_approve)
    wrapped_fr = wrap_tool_with_confirmation(tool, "fr", always_approve)
    assert isinstance(wrapped_en, StructuredTool)
    assert wrapped_en.name == "recorder"
    assert wrapped_en.description == "Record a value (EN)."
    assert wrapped_fr.description == "Enregistre une valeur (FR)."
    assert wrapped_en.args_schema is _RecordedArgs


# --- Console prompt shows the canonical validated dump ---------------------


async def test_console_prompt_renders_the_validated_dump() -> None:
    """Schema defaults are part of what runs, so they are part of what the
    human approves (console flow, through the same wrapper ordering)."""
    from declaw.brain.repl import make_console_confirmation_provider

    questions: list[str] = []

    def prompt(question: str) -> str:
        questions.append(question)
        return "y"

    provider = make_console_confirmation_provider(prompt, "en")
    wrapped = wrap_tool_with_confirmation(_PlanTool(), "en", provider)

    result = await wrapped.ainvoke({"moves": ["a.pdf"]})

    assert result == "planned 1"
    [question] = questions
    assert "moves=['a.pdf']" in question
    assert "dry_run=False" in question
