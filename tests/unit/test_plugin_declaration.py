"""Declaring what a plugin can do, and what the host is told about it."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from declaw_plugin_sdk.declaration import (
    BasePlugin,
    CapabilityDeclarationError,
    capability,
)


class EchoArgs(BaseModel):
    message: str
    times: int = 1


class Sample(BasePlugin):
    name = "sample"
    version = "1.2.3"

    @capability(
        name="echo",
        description_en="Repeat a message.",
        description_fr="Repete un message.",
        exposed_to_model=True,
        classification="read",
    )
    async def echo(self, args: EchoArgs) -> str:
        return args.message * args.times

    @capability(
        name="hidden",
        description_en="Infrastructure only.",
        description_fr="Infrastructure uniquement.",
        requires=["filesystem.read"],
        produces_external_content=True,
        timeout_s=300,
    )
    async def hidden(self, args: EchoArgs) -> str:
        return "x"


def test_capabilities_are_discovered_by_name() -> None:
    assert set(Sample().capabilities()) == {"echo", "hidden"}


def test_describe_reports_identity_and_every_capability() -> None:
    described = Sample().describe()
    assert described.name == "sample"
    assert described.version == "1.2.3"
    assert {c.name for c in described.capabilities} == {"echo", "hidden"}


def test_describe_carries_the_declared_flags() -> None:
    by_name = {c.name: c for c in Sample().describe().capabilities}
    assert by_name["echo"].exposed_to_model is True
    assert by_name["echo"].classification == "read"
    assert by_name["hidden"].requires == ("filesystem.read",)
    assert by_name["hidden"].produces_external_content is True
    assert by_name["hidden"].timeout_s == 300


def test_undeclared_flags_default_to_the_safe_value() -> None:
    hidden = {c.name: c for c in Sample().describe().capabilities}["hidden"]
    assert hidden.exposed_to_model is False
    assert hidden.classification == "write"


def test_describe_embeds_the_args_json_schema() -> None:
    echo = {c.name: c for c in Sample().describe().capabilities}["echo"]
    assert echo.args_schema["properties"]["message"]["type"] == "string"
    assert echo.args_schema["required"] == ["message"]


def test_a_synchronous_capability_is_refused() -> None:
    with pytest.raises(CapabilityDeclarationError) as excinfo:

        class Bad(BasePlugin):
            @capability(name="s", description_en="a", description_fr="a")
            def sync_one(self, args: EchoArgs) -> str:  # not async
                return "x"

    assert "async" in str(excinfo.value)


def test_a_capability_without_a_pydantic_args_parameter_is_refused() -> None:
    with pytest.raises(CapabilityDeclarationError) as excinfo:

        class Bad(BasePlugin):
            @capability(name="s", description_en="a", description_fr="a")
            async def untyped(self, args: dict) -> str:  # type: ignore[type-arg]
                return "x"

    assert "args" in str(excinfo.value)


def test_duplicate_capability_names_are_refused() -> None:
    class Clashing(BasePlugin):
        name = "clash"

        @capability(name="same", description_en="a", description_fr="a")
        async def first(self, args: EchoArgs) -> str:
            return "1"

        @capability(name="same", description_en="b", description_fr="b")
        async def second(self, args: EchoArgs) -> str:
            return "2"

    with pytest.raises(CapabilityDeclarationError):
        Clashing().capabilities()
