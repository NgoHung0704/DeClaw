"""Frames exchanged over the plugin's stdio, and the vocabulary of failures."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
SDK_VERSION = 1

# Hard ceiling on one NDJSON line, in both directions. A parsed 500-page PDF
# is a few MB of text; 32 MiB leaves headroom without letting a runaway plugin
# exhaust host memory.
MAX_FRAME_BYTES = 32 * 1024 * 1024

Method = Literal["describe", "invoke", "shutdown"]

ErrorCode = Literal[
    "unknown_method",
    "unknown_capability",
    "invalid_args",
    "capability_failed",
    "result_too_large",
    "internal",
]

Classification = Literal["read", "write", "destructive"]


class RequestFrame(BaseModel):
    """Host -> plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: int = PROTOCOL_VERSION
    id: str
    method: Method
    params: dict[str, Any] = Field(default_factory=dict)


class FrameError(BaseModel):
    """Structured failure carried by a non-ok response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    message: str


class ResponseFrame(BaseModel):
    """Plugin -> host."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: int = PROTOCOL_VERSION
    id: str
    ok: bool
    result: Any = None
    error: FrameError | None = None


class CapabilityDescriptor(BaseModel):
    """One thing a plugin can do, as announced by ``describe``.

    Every flag defaults to the cautious value: a capability the author forgot
    to annotate stays invisible to the model and gated behind confirmation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description_en: str
    description_fr: str
    # Permission values as plain strings; the SDK cannot import DeClaw's
    # PluginPermission enum. The host converts and validates them.
    requires: tuple[str, ...] = ()
    exposed_to_model: bool = False
    produces_external_content: bool = False
    classification: Classification = "write"
    timeout_s: int = 120
    args_schema: dict[str, Any]


class DescribeResult(BaseModel):
    """The plugin's answer to ``describe``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    sdk_version: int = SDK_VERSION
    capabilities: tuple[CapabilityDescriptor, ...] = ()
