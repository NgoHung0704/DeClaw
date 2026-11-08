"""Gateway approval broker (DCL-125, spec section 7).

The reusable piece of the confirmation gate is ``ConfirmationProvider``; the
gateway implementation of that seam is an ``ApprovalBroker``. Per session,
``create_provider`` returns a provider that publishes an ``approval.request``
message on the session's outbound queue and resolves the decision from the
matching ``approval.response`` reply.

Invariants (spec section 7):

- The broker NEVER writes to a socket. Publishing goes through the injected
  ``enqueue`` callable; the single-writer transport is wired in a later task.
- A provider is only reached after the confirmation wrapper validated the
  arguments (validate-before-prompt, §7.1), so ``args`` here is the canonical
  validated dump of exactly the object that will execute.
- Replies are accepted only when the request id exists, **belongs to the
  answering session**, is unexpired and unanswered. Duplicate, stale and
  cross-session replies are attack/bug indicators, not user input: they are
  ignored and logged, never treated as a decision.
- Default deny survives every failure mode: timeout, turn cancellation and
  session disconnect all resolve the pending decision as deny (§7.4).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from declaw.log import logger
from declaw.tools.base import DeclawTool
from declaw.tools.confirmation import ConfirmationProvider

APPROVAL_REQUEST_TYPE = "approval.request"
APPROVAL_TIMEOUT_SECONDS = 120.0
# Bounded memory of answered request ids, so replayed replies can be
# classified as duplicates instead of "unknown". The cap means an attacker
# spamming replies cannot grow this dict beyond a set of *issued* ids.
_ANSWERED_ID_CAP = 4096


@dataclass
class _PendingApproval:
    """Internal record of one outstanding approval request."""

    session_id: str
    tool_name: str
    args: dict[str, Any]
    preview: str
    expires_at: float
    future: asyncio.Future[bool]


def _render_preview(tool: DeclawTool[Any], args: dict[str, Any]) -> str:
    """Human-facing approval text, built exactly like the console flow."""
    preview = tool.confirmation_preview(args)
    if preview is not None:
        return preview
    rendered = ", ".join(f"{key}={value!r}" for key, value in args.items())
    return f"DeClaw wants to call {tool.name}({rendered})."


class ApprovalBroker:
    """Session-scoped approval requests over an outbound queue.

    ``clock`` is a ``() -> float`` seconds callable, injectable so tests cross
    the 120 s expiry without sleeping. ``handle_response`` and ``deny_all``
    must be called on the same event loop as the awaiting providers (the
    futures they resolve live on it).
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = APPROVAL_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._pending: dict[str, _PendingApproval] = {}
        self._answered: dict[str, float] = {}

    def create_provider(
        self, session_id: str, enqueue: Callable[[dict[str, Any]], None]
    ) -> ConfirmationProvider:
        """Return the provider that asks this session's user.

        ``enqueue`` hands the ``approval.request`` message to the session's
        outbound queue; the broker never touches a transport itself. The
        provider awaits the matching reply, resolved by ``handle_response``,
        and defaults to deny on timeout.
        """

        async def approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
            request_id = str(uuid.uuid4())
            expires_at = self._clock() + self._timeout_seconds
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            pending = _PendingApproval(
                session_id=session_id,
                tool_name=tool.name,
                args=args,
                preview=_render_preview(tool, args),
                expires_at=expires_at,
                future=future,
            )
            self._pending[request_id] = pending
            try:
                enqueue(
                    {
                        "type": APPROVAL_REQUEST_TYPE,
                        "id": request_id,
                        "session_id": session_id,
                        "tool": tool.name,
                        "args": args,
                        "preview": pending.preview,
                        "expires_at": expires_at,
                    }
                )
            except Exception:
                # No request left the broker, so there is nothing to answer:
                # remove the record and let the failure propagate (the gate
                # turns it into an observation; no approval can happen).
                self._remove(request_id)
                logger.bind(request_id=request_id, session_id=session_id).exception(
                    "Approval request could not be queued - failing closed"
                )
                raise
            remaining = max(0.0, expires_at - self._clock())
            try:
                return await asyncio.wait_for(future, remaining)
            except TimeoutError:
                self._remove(request_id)
                logger.bind(
                    request_id=request_id, session_id=session_id, tool=tool.name
                ).warning("Approval request timed out unanswered - defaulting to deny")
                return False
            finally:
                # whoever resolved the future already removed the record; the
                # pop makes sure no path leaves a stale entry behind.
                self._pending.pop(request_id, None)

        return approve

    def handle_response(self, session_id: str, response: Mapping[str, Any]) -> None:
        """Resolve a pending request from this session's reply, or ignore it.

        The reply is accepted only if its request id exists, belongs to
        ``session_id`` (whoever calls this passes the *authenticated* session,
        not a client-claimed one), is unexpired and unanswered. Anything else
        is ignored and logged: duplicate, stale and cross-session replies are
        attack/bug indicators, not user input. Only an explicit
        ``approved: True`` approves; a missing or truthy-but-not-True value
        denies.
        """
        request_id = response.get("id")
        if not isinstance(request_id, str) or not request_id:
            logger.bind(session_id=session_id).warning(
                "Approval reply without a request id ignored"
            )
            return
        pending = self._pending.get(request_id)
        if pending is None:
            already_answered = request_id in self._answered
            reason = "already answered (duplicate)" if already_answered else "unknown id"
            logger.bind(session_id=session_id, request_id=request_id).warning(
                "Approval reply ignored ({}): request is not pending", reason
            )
            return
        if pending.session_id != session_id:
            logger.bind(
                session_id=session_id,
                request_id=request_id,
                owner_session_id=pending.session_id,
            ).warning(
                "Cross-session approval reply ignored: request belongs to session {}",
                pending.session_id,
            )
            return
        if self._clock() >= pending.expires_at:
            logger.bind(session_id=session_id, request_id=request_id).warning(
                "Approval reply ignored: request expired - default deny stands"
            )
            return
        if pending.future.done():
            logger.bind(session_id=session_id, request_id=request_id).warning(
                "Approval reply ignored: request already answered"
            )
            return
        approved = response.get("approved") is True
        self._remove(request_id)
        pending.future.set_result(approved)
        logger.bind(session_id=session_id, request_id=request_id).info(
            "Approval {} for tool {}", "approved" if approved else "denied", pending.tool_name
        )

    def deny_all(self, session_id: str, reason: str) -> None:
        """Resolve every pending request of one session as deny.

        Called on turn cancellation and session disconnect (spec §7.4):
        different callers, same invariant — an approval nobody is able to
        answer must default to deny, never dangle or leak into a new turn.
        Other sessions are untouched: one user's disconnect cannot deny
        another user's approval.
        """
        for request_id, pending in list(self._pending.items()):
            if pending.session_id != session_id:
                continue
            self._remove(request_id)
            if not pending.future.done():
                pending.future.set_result(False)
            logger.bind(
                request_id=request_id, session_id=session_id, tool=pending.tool_name
            ).warning("Approval request denied: {}", reason)

    def _remove(self, request_id: str) -> None:
        """Move a request from pending to the bounded answered-id memory."""
        del self._pending[request_id]
        self._answered[request_id] = self._clock()
        if len(self._answered) > _ANSWERED_ID_CAP:
            self._answered.pop(next(iter(self._answered)))
