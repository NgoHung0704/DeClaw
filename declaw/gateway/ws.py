"""The ``/ws/chat`` endpoint (DCL-125, spec sections 6 and 7).

Handshake order: cookie authentication BEFORE accept (no valid session cookie
-> close 4401; the foreign-Origin 4403 already lives in the Host/Origin
middleware from Task 3), then the not-accepting and readiness checks, then the
per-session wiring: one :class:`GatewaySession`, one approval provider bound
to that session's outbound queue, one tool list, one graph.

Disconnect cancels the in-flight turn and denies the session's pending
approvals. That cleanup is shielded: a shutdown or transport cancellation
pressing on the request task must not cut the cancel-then-deny-then-persist
sequence short — default deny survives every failure mode.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, WebSocket
from langchain_core.tools import BaseTool
from starlette.websockets import WebSocketDisconnect

from declaw.app import Application
from declaw.audit.logger import AuditLogger
from declaw.brain.context import with_context_window
from declaw.brain.chat_model import build_ollama_model
from declaw.brain.loop import ModelCallable, build_agent_graph
from declaw.brain.repl import AgentGraph
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.auth import SESSION_COOKIE_NAME
from declaw.gateway.session import GatewaySession, SessionManager
from declaw.log import logger
from declaw.settings_service import EffectiveSettings, InvalidSettingsFileError

# Close codes on the chat transport. 4401/4403 are the app-level codes the M1
# contract established; 1011/1013 are protocol codes for internal refusal and
# shutdown (not yet covered by a spec table).
WS_UNAUTHENTICATED_CLOSE_CODE = 4401
WS_NOT_ACCEPTING_CLOSE_CODE = 1013
WS_INTERNAL_ERROR_CLOSE_CODE = 1011

# A session's model: tests inject a deterministic fake; production builds the
# Ollama stack from the session's effective-settings snapshot (spec section 12).
ModelFactory = Callable[[Sequence[BaseTool], EffectiveSettings], ModelCallable]


def build_session_graph(
    session: GatewaySession,
    snapshot: EffectiveSettings,
    *,
    application: Application,
    audit: AuditLogger,
    broker: ApprovalBroker,
    model_factory: ModelFactory | None = None,
) -> AgentGraph:
    """Compile one connection's own graph.

    Tools are bound per session (spec section 7.6) with THIS session's
    approval provider, so one user's approval can never release another
    user's tool call. The audit logger is the task-correlating one, so
    every tool/permission event the graph emits carries the turn's task id.
    """
    registry = application.registry
    if registry is None:
        raise RuntimeError("Application.start() must run before chat sessions.")
    provider = broker.create_provider(session.id, session.enqueue)
    tools = registry.langchain_tools(
        snapshot.language,
        provider,
        sanitizer=application.sanitizer,
        audit=audit,
    )
    model = (
        model_factory
        if model_factory is not None
        else _default_model_factory
    )(tools, snapshot)
    return build_agent_graph(model=model, tools=tools)


def _default_model_factory(tools: Sequence[BaseTool], snapshot: EffectiveSettings) -> ModelCallable:
    """The production model stack, fed from the snapshot (never the env cache)."""
    model = build_ollama_model(tools, model=snapshot.model, language=snapshot.language)
    return with_context_window(model)


def session_graph_factory(
    *,
    application: Application,
    audit: AuditLogger,
    broker: ApprovalBroker,
    model_factory: ModelFactory | None = None,
) -> Callable[[GatewaySession, EffectiveSettings], AgentGraph]:
    """Bind everything the per-session graph needs into one factory call."""

    def factory(session: GatewaySession, snapshot: EffectiveSettings) -> AgentGraph:
        return build_session_graph(
            session,
            snapshot,
            application=application,
            audit=audit,
            broker=broker,
            model_factory=model_factory,
        )

    return factory


router = APIRouter()


@router.websocket("/ws/chat")
async def chat_endpoint(websocket: WebSocket) -> None:
    # WebSocket.state is a per-connection State; the shared gateway services
    # live on the app (spec section 6: stateless services shared by sessions).
    state = websocket.scope["app"].state
    registry: Any = state.session_registry
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not isinstance(cookie, str) or not registry.validate(cookie):
        # Auth BEFORE accept: no valid session cookie -> close 4401.
        await websocket.close(code=WS_UNAUTHENTICATED_CLOSE_CODE, reason="authentication required")
        return

    manager: SessionManager = state.session_manager
    if not manager.accepting:
        await websocket.close(code=WS_NOT_ACCEPTING_CLOSE_CODE, reason="gateway is shutting down")
        return

    application: Application | None = getattr(state, "application", None)
    if application is None or application.registry is None:
        await websocket.close(code=WS_INTERNAL_ERROR_CLOSE_CODE, reason="chat is not available")
        return

    await websocket.accept()
    try:
        snapshot = application.settings_service.effective()
    except InvalidSettingsFileError as exc:
        logger.bind(error=str(exc)).error("Chat session refused: settings fail closed")
        await websocket.close(
            code=WS_INTERNAL_ERROR_CLOSE_CODE, reason="invalid settings file"
        )
        return

    session = manager.create(snapshot)
    try:
        await session.serve(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        # Disconnect, cancellation and shutdown pressure must not cut the
        # cancel-turn -> deny-approvals -> persist sequence short.
        with CancelScope(shield=True):
            await session.close()
        manager.drop(session)
