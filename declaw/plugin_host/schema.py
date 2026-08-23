"""Rebuild a pydantic model from the JSON Schema a plugin announces.

Only a deliberately small subset of JSON Schema is accepted: a flat object of
scalars, string arrays and string enums. The restriction is a feature twice
over. It keeps validation host-side, so malformed arguments never reach the
subprocess (Principle #6). And flat, simple tool signatures are what a 3B model
actually calls correctly — the Phase 1 probes are unambiguous about that.

The one non-obvious accommodation is ``anyOf: [T, null]``. That is how pydantic
renders ``T | None``, so it is exactly what the SDK emits for an optional
argument; rejecting it would reject every plugin with an optional parameter.
General ``anyOf`` stays refused.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from declaw.plugin_host.errors import PluginLoadError

_SCALARS: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

_FORBIDDEN_KEYS = ("$ref", "oneOf", "allOf", "not", "patternProperties")


class PluginSchemaError(PluginLoadError):
    """A plugin's argument schema uses something this host does not support."""


def _unwrap_nullable(prop: str, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Turn ``anyOf: [T, null]`` into ``(T, True)``; leave anything else alone."""
    branches = spec.get("anyOf")
    if branches is None:
        return spec, False
    complaint = (
        f"property {prop!r}: only 'anyOf: [type, null]' is supported, not general anyOf"
    )
    if not isinstance(branches, list) or len(branches) != 2:
        raise PluginSchemaError(complaint)
    nulls = [b for b in branches if isinstance(b, dict) and b.get("type") == "null"]
    others = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    if len(nulls) != 1 or len(others) != 1:
        raise PluginSchemaError(complaint)
    merged = dict(others[0])
    for carried in ("description", "default"):
        if carried in spec:
            merged.setdefault(carried, spec[carried])
    return merged, True


def _annotation_for(prop: str, spec: dict[str, Any]) -> Any:
    for key in _FORBIDDEN_KEYS:
        if key in spec:
            raise PluginSchemaError(f"property {prop!r}: {key!r} is not supported")
    if "enum" in spec:
        values = spec["enum"]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise PluginSchemaError(f"property {prop!r}: only string enums are supported")
        return Literal[tuple(values)]
    declared = spec.get("type")
    if declared in _SCALARS:
        return _SCALARS[declared]
    if declared == "array":
        items = spec.get("items")
        if not isinstance(items, dict) or items.get("type") != "string":
            raise PluginSchemaError(f"property {prop!r}: only arrays of string are supported")
        return list[str]
    raise PluginSchemaError(f"property {prop!r}: unsupported type {declared!r}")


def model_from_json_schema(model_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a pydantic model from ``schema`` or raise :class:`PluginSchemaError`."""
    if schema.get("type") != "object":
        raise PluginSchemaError("an argument schema must be a JSON Schema object")
    for key in _FORBIDDEN_KEYS:
        if key in schema:
            raise PluginSchemaError(f"top-level {key!r} is not supported")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise PluginSchemaError("'properties' must be a mapping")
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for prop, raw_spec in properties.items():
        if not isinstance(raw_spec, dict):
            raise PluginSchemaError(f"property {prop!r}: definition must be a mapping")
        spec, nullable = _unwrap_nullable(prop, raw_spec)
        annotation = _annotation_for(prop, spec)
        description = spec.get("description")
        if nullable:
            annotation = annotation | None
        if prop in required and "default" not in spec:
            fields[prop] = (annotation, Field(..., description=description))
            continue
        # A property that is neither required nor defaulted may simply be
        # absent, so its type has to be able to hold None.
        if not nullable and "default" not in spec:
            annotation = annotation | None
        fields[prop] = (annotation, Field(spec.get("default"), description=description))

    # create_model's kwargs are untyped by construction; the values above are
    # the (annotation, FieldInfo) pairs it expects.
    return create_model(model_name, **fields)
