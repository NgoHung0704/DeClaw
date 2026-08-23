"""How a plugin author says what their plugin can do.

A capability is an ``async def`` taking one parameter named ``args``, annotated
with a pydantic model. That model is the contract: its JSON Schema travels to
the host, which rebuilds it and validates every call before the plugin is even
asked. The author never parses raw input.

Every flag on the decorator defaults to the cautious value. Forgetting
``exposed_to_model=True`` hides a capability from the model; forgetting
``classification="read"`` puts it behind the confirmation gate. Mistakes make
the system quieter and stricter, never louder and looser.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel

from declaw_plugin_sdk.protocol import (
    SDK_VERSION,
    CapabilityDescriptor,
    Classification,
    DescribeResult,
)

CAPABILITY_ATTR = "__declaw_capability__"

# Coroutine, not Awaitable: the runtime hands these straight to
# asyncio.run(), which will not accept a bare Awaitable.
CapabilityFunc = Callable[..., Coroutine[Any, Any, Any]]
FuncT = TypeVar("FuncT", bound=CapabilityFunc)


class CapabilityDeclarationError(TypeError):
    """A capability was declared in a way the SDK cannot honour."""


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Everything the runtime needs to dispatch one capability."""

    name: str
    description_en: str
    description_fr: str
    requires: tuple[str, ...]
    exposed_to_model: bool
    produces_external_content: bool
    classification: Classification
    timeout_s: int
    args_model: type[BaseModel]
    func: CapabilityFunc

    def descriptor(self) -> CapabilityDescriptor:
        """Render the wire-facing announcement of this capability."""
        return CapabilityDescriptor(
            name=self.name,
            description_en=self.description_en,
            description_fr=self.description_fr,
            requires=self.requires,
            exposed_to_model=self.exposed_to_model,
            produces_external_content=self.produces_external_content,
            classification=self.classification,
            timeout_s=self.timeout_s,
            args_schema=self.args_model.model_json_schema(),
        )


def capability(
    *,
    name: str,
    description_en: str,
    description_fr: str,
    requires: Sequence[str] = (),
    exposed_to_model: bool = False,
    produces_external_content: bool = False,
    classification: Classification = "write",
    timeout_s: int = 120,
) -> Callable[[FuncT], FuncT]:
    """Mark an async method as a capability the host may invoke."""

    def decorate(func: FuncT) -> FuncT:
        if not inspect.iscoroutinefunction(func):
            raise CapabilityDeclarationError(
                f"capability {name!r} must be declared with 'async def'"
            )
        hints = get_type_hints(func)
        args_model = hints.get("args")
        if not (isinstance(args_model, type) and issubclass(args_model, BaseModel)):
            raise CapabilityDeclarationError(
                f"capability {name!r} must take a parameter named 'args' "
                "annotated with a pydantic BaseModel subclass"
            )
        setattr(
            func,
            CAPABILITY_ATTR,
            CapabilitySpec(
                name=name,
                description_en=description_en,
                description_fr=description_fr,
                requires=tuple(requires),
                exposed_to_model=exposed_to_model,
                produces_external_content=produces_external_content,
                classification=classification,
                timeout_s=timeout_s,
                args_model=args_model,
                func=func,
            ),
        )
        return func

    return decorate


class BasePlugin:
    """Base class every plugin subclasses exactly once."""

    name: str = ""
    version: str = "0.0.0"

    def capabilities(self) -> dict[str, CapabilitySpec]:
        """Collect the decorated methods, keyed by capability name."""
        found: dict[str, CapabilitySpec] = {}
        for attribute in dir(type(self)):
            spec = getattr(getattr(type(self), attribute, None), CAPABILITY_ATTR, None)
            if not isinstance(spec, CapabilitySpec):
                continue
            if spec.name in found:
                raise CapabilityDeclarationError(
                    f"capability name {spec.name!r} is declared twice on {type(self).__name__}"
                )
            found[spec.name] = spec
        return found

    def describe(self) -> DescribeResult:
        """Answer the host's ``describe`` request."""
        return DescribeResult(
            name=self.name,
            version=self.version,
            sdk_version=SDK_VERSION,
            capabilities=tuple(spec.descriptor() for spec in self.capabilities().values()),
        )
