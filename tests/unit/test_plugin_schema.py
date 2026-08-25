"""Rebuilding a pydantic model from a plugin's announced JSON Schema."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from declaw.plugin_host.schema import PluginSchemaError, model_from_json_schema


class _Args(BaseModel):
    path: str
    max_pages: int | None = None
    verbose: bool = False
    tags: list[str] = []
    mode: str = "fast"


def _rebuild(model: type[BaseModel]) -> type[BaseModel]:
    return model_from_json_schema("Rebuilt", model.model_json_schema())


def test_roundtrips_a_realistic_pydantic_model() -> None:
    # The headline case: whatever the SDK emits, the host can read back.
    rebuilt = _rebuild(_Args)
    parsed = rebuilt.model_validate({"path": "a.pdf"})
    assert parsed.model_dump()["path"] == "a.pdf"


def test_required_field_stays_required() -> None:
    rebuilt = _rebuild(_Args)
    with pytest.raises(ValidationError):
        rebuilt.model_validate({})


def test_optional_field_rendered_as_anyof_null_is_accepted() -> None:
    # pydantic writes `int | None` as anyOf[integer, null]. Rejecting that
    # would reject every plugin with an optional argument.
    rebuilt = _rebuild(_Args)
    assert rebuilt.model_validate({"path": "a", "max_pages": 3}).model_dump()["max_pages"] == 3
    assert rebuilt.model_validate({"path": "a"}).model_dump()["max_pages"] is None


def test_defaults_survive() -> None:
    rebuilt = _rebuild(_Args)
    dumped = rebuilt.model_validate({"path": "a"}).model_dump()
    assert dumped["verbose"] is False
    assert dumped["mode"] == "fast"


def test_wrong_type_is_rejected_at_the_host() -> None:
    rebuilt = _rebuild(_Args)
    with pytest.raises(ValidationError):
        rebuilt.model_validate({"path": "a", "max_pages": "not a number"})


def test_string_array_supported() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_validate({"tags": ["x"]}).model_dump()["tags"] == ["x"]


def test_string_enum_becomes_a_literal() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"mode": {"enum": ["fast", "slow"]}},
        "required": ["mode"],
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_validate({"mode": "fast"}).model_dump()["mode"] == "fast"
    with pytest.raises(ValidationError):
        rebuilt.model_validate({"mode": "sideways"})


def test_description_is_carried_into_the_field() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Where to read."}},
        "required": ["path"],
    }
    rebuilt = model_from_json_schema("A", schema)
    assert rebuilt.model_fields["path"].description == "Where to read."


@pytest.mark.parametrize(
    ("schema", "needle"),
    [
        ({"type": "array"}, "object"),
        (
            {"type": "object", "properties": {"nested": {"type": "object"}}},
            "nested",
        ),
        (
            {"type": "object", "properties": {"x": {"$ref": "#/$defs/Y"}}},
            "x",
        ),
        (
            {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}]}}},
            "x",
        ),
        (
            {
                "type": "object",
                "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
            },
            "x",
        ),
        (
            {
                "type": "object",
                "properties": {"x": {"type": "array", "items": {"type": "integer"}}},
            },
            "x",
        ),
        ({"type": "object", "properties": {"x": {"enum": [1, 2]}}}, "x"),
    ],
)
def test_unsupported_constructs_are_rejected_by_name(schema: dict[str, Any], needle: str) -> None:
    with pytest.raises(PluginSchemaError) as excinfo:
        model_from_json_schema("A", schema)
    assert needle in str(excinfo.value)
