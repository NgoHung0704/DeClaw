"""Tool-call output parsing with retry/repair (DCL-013).

Small local models (Mistral 7B) sometimes emit broken tool calls: arguments
that are not valid JSON, a tool name that does not exist, or arguments that
miss a required field. ``with_tool_call_repair`` wraps a ``ModelCallable`` so
that, when the model's reply has such a problem, it is re-prompted with a
corrective message describing what was wrong — up to ``max_retries`` times.
After that the last attempt is returned as-is (the executor's ``ToolNode`` then
surfaces any remaining error), so the loop never hangs.

The wrapper is composable and leaves the model factory untouched::

    model = with_tool_call_repair(build_ollama_model(tools), tools)
    graph = build_agent_graph(model=model, tools=tools)
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

from declaw.brain.loop import ModelCallable


def with_tool_call_repair(
    model: ModelCallable,
    tools: Sequence[BaseTool],
    *,
    max_retries: int = 2,
) -> ModelCallable:
    """Wrap ``model`` so malformed/invalid tool calls trigger a corrective retry.

    ``tools`` must be the same tools the model was made aware of (and that the
    executor runs). Up to ``max_retries`` corrective re-prompts are made before
    the last reply is returned unchanged.
    """
    tools_by_name = {tool.name: tool for tool in tools}

    async def call(messages: Sequence[BaseMessage]) -> BaseMessage:
        history: list[BaseMessage] = list(messages)
        reply = await model(history)
        for _ in range(max_retries):
            problems = _tool_call_problems(reply, tools_by_name)
            if not problems:
                return reply
            history = [*history, reply, HumanMessage(content=_correction(problems))]
            reply = await model(history)
        return reply

    return call


def _tool_call_problems(
    message: BaseMessage, tools_by_name: dict[str, BaseTool]
) -> list[str]:
    """Return human-readable problems with a reply's tool calls (empty = fine)."""
    if not isinstance(message, AIMessage):
        return []

    problems: list[str] = []
    for invalid in message.invalid_tool_calls:
        problems.append(
            f"The arguments for tool {invalid.get('name')!r} were not valid JSON "
            f"({invalid.get('error')})."
        )
    for tool_call in message.tool_calls:
        name = tool_call["name"]
        tool = tools_by_name.get(name)
        if tool is None:
            available = ", ".join(sorted(tools_by_name)) or "(none)"
            problems.append(f"Tool {name!r} does not exist. Available tools: {available}.")
            continue
        problems.extend(_argument_problems(name, tool, tool_call["args"]))
    return problems


def _argument_problems(name: str, tool: BaseTool, args: dict[str, object]) -> list[str]:
    schema = tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return []
    try:
        schema.model_validate(args)
    except ValidationError as exc:
        return [f"The arguments for tool {name!r} are invalid: {exc}."]
    return []


def _correction(problems: list[str]) -> str:
    bullets = "\n".join(f"- {problem}" for problem in problems)
    return (
        "Your previous tool call could not be used:\n"
        f"{bullets}\n"
        "Call the tool again using only the available tools, with corrected "
        "arguments that match the tool's required parameters."
    )
