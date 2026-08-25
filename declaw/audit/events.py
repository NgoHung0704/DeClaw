"""Typed audit event schema (DCL-060).

Every observable action DeClaw takes is recorded as one of the frozen Pydantic
events below. Events serialize into the ``audit_events`` table (DCL-005) as a
JSON payload; ``event_type`` doubles as the Pydantic discriminator and the
indexed DB column, so the same string routes both storage queries and
deserialization.

Design constraints:

* **Versioned** — every payload carries ``schema_version`` so future readers
  can migrate old rows (acceptance: "schema versioned").
* **Frozen** — audit records are append-only facts; nothing mutates one after
  emission.
* **Privacy-aware** — tool args can embed user document content (e.g.
  ``filesystem_write``'s ``content``). ``clip_args`` truncates long string
  values and replaces the tail with a SHA-256 fingerprint, so the audit trail
  proves *what happened* without duplicating whole (possibly privileged)
  documents into a second store.

The union deliberately starts with the four types named by the ticket
(ToolCall, NetworkCall, Quarantine, PermissionPrompt); later tickets append
new members (e.g. memory export/wipe for DCL-056/057) rather than reshaping
existing ones.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from declaw.db.models import AuditEvent as AuditEventRow

AUDIT_SCHEMA_VERSION = 1

# Longest string value stored verbatim in an event payload. Anything longer is
# clipped and fingerprinted (see clip_args).
MAX_ARG_CHARS = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class _BaseAuditEvent(BaseModel):
    """Common envelope for every audit event."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    schema_version: int = AUDIT_SCHEMA_VERSION
    task_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class ToolCallEvent(_BaseAuditEvent):
    """One tool invocation requested by the model, whatever its outcome."""

    event_type: Literal["tool.call"] = "tool.call"
    tool_name: str
    classification: str = Field(description="ToolClass value: read / write / destructive.")
    args: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal["ok", "error", "denied"]
    error: str | None = None
    duration_ms: float | None = None


class NetworkCallEvent(_BaseAuditEvent):
    """One outbound network request (Principle #7: egress must be observable)."""

    event_type: Literal["network.call"] = "network.call"
    method: str
    url: str
    host: str
    status_code: int | None = None
    error: str | None = None
    # True when the destination host is outside the local allowlist — the
    # "data may have left the device" signal the egress monitor raises.
    flagged: bool = False


class QuarantineEvent(_BaseAuditEvent):
    """External content ruled UNSAFE by the sanitizer and quarantined.

    Mirrors ``declaw.sanitizer.quarantine.QuarantineEvent`` (the in-process
    wire format) but as a durable, versioned record. Carries the content hash,
    never the content (DCL-045).
    """

    event_type: Literal["sanitizer.quarantine"] = "sanitizer.quarantine"
    quarantine_id: str
    source: str
    content_sha256: str
    reason: str


class PermissionPromptEvent(_BaseAuditEvent):
    """A human was asked to approve a non-READ tool call."""

    event_type: Literal["permission.prompt"] = "permission.prompt"
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    decision: Literal["approved", "denied"]
    channel: str = Field(default="console", description="Where the prompt was shown.")


class MemoryExportEvent(_BaseAuditEvent):
    """User exported their memory archive (GDPR portability, DCL-056)."""

    event_type: Literal["memory.export"] = "memory.export"
    destination: str
    semantic_count: int
    episode_count: int


class MemoryWipeEvent(_BaseAuditEvent):
    """User wiped their memory (right to be forgotten, DCL-057).

    Deliberately anonymized: counts only, no ids, no content — the audit
    trail must prove the wipe happened without undoing it.
    """

    event_type: Literal["memory.wipe"] = "memory.wipe"
    semantic_removed: int
    episodes_removed: int


class PluginPermissionEvent(_BaseAuditEvent):
    """A plugin-permission state change or enforcement decision (DCL-084).

    ``action`` covers the whole lifecycle: ``granted``/``revoked`` (user
    decisions on the grant store), ``denied_call`` (a requested-but-ungranted
    permission was exercised), and ``violation`` (the plugin exercised a
    permission its manifest never even requested — DCL-097 escalation).
    """

    event_type: Literal["plugin.permission"] = "plugin.permission"
    plugin: str
    permission: str
    action: Literal["granted", "revoked", "denied_call", "violation"]


class PluginLifecycleEvent(_BaseAuditEvent):
    """A plugin process changed state (DCL-091 / DCL-096 / DCL-097).

    ``load_failed`` covers a manifest or capability set the host refused;
    ``quarantined`` is the terminal state after repeated crashes or protocol
    violations. Both are user-visible on purpose: a plugin that silently
    stopped working would be worse than one that says why.
    """

    event_type: Literal["plugin.lifecycle"] = "plugin.lifecycle"
    plugin: str
    version: str = ""
    action: Literal[
        "started",
        "stopped",
        "crashed",
        "restarted",
        "quarantined",
        "enabled",
        "disabled",
        "load_failed",
    ]
    detail: str = ""


AnyAuditEvent = Annotated[
    ToolCallEvent
    | NetworkCallEvent
    | QuarantineEvent
    | PermissionPromptEvent
    | MemoryExportEvent
    | MemoryWipeEvent
    | PluginPermissionEvent
    | PluginLifecycleEvent,
    Field(discriminator="event_type"),
]

_EVENT_ADAPTER: TypeAdapter[AnyAuditEvent] = TypeAdapter(AnyAuditEvent)


def clip_args(args: dict[str, Any], *, max_chars: int = MAX_ARG_CHARS) -> dict[str, Any]:
    """Return ``args`` with long string values clipped + SHA-256 fingerprinted.

    Only top-level string values are clipped — that is where document bodies
    live in practice (``content``, ``text``). The fingerprint lets an auditor
    match the clipped value against a known file without the audit DB storing
    the full (possibly privileged) text.
    """
    clipped: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > max_chars:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            clipped[key] = (
                f"{value[:max_chars]}"
                f"...[clipped {len(value) - max_chars} chars, sha256={digest[:16]}]"
            )
        else:
            clipped[key] = value
    return clipped


def to_db_row(event: AnyAuditEvent) -> AuditEventRow:
    """Project a typed event onto the ``audit_events`` SQLModel row.

    The full event (envelope included) goes into ``payload`` so a row is
    self-contained; ``event_type`` / ``task_id`` / ``created_at`` are mirrored
    into their indexed columns for querying.
    """
    return AuditEventRow(
        id=event.id,
        event_type=event.event_type,
        task_id=event.task_id,
        payload=event.model_dump(mode="json"),
        created_at=event.created_at,
    )


def event_from_payload(payload: dict[str, Any]) -> AnyAuditEvent:
    """Rehydrate a typed event from a stored JSON payload.

    Raises ``pydantic.ValidationError`` on unknown ``event_type`` or malformed
    fields — a corrupt audit row should be loud, not silently coerced.
    """
    return _EVENT_ADAPTER.validate_python(payload)


def event_from_row(row: AuditEventRow) -> AnyAuditEvent:
    """Rehydrate a typed event from its DB row."""
    return event_from_payload(row.payload)
