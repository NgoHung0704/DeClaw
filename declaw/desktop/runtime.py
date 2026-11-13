"""Owned loopback listener and application lifecycle for the desktop child."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

import uvicorn
from fastapi import FastAPI

from declaw.app import Application
from declaw.audit.events import DesktopLifecycleEvent
from declaw.config import Settings
from declaw.credentials.fallback import SECRETS_FILENAME
from declaw.credentials.store import default_credential_store
from declaw.desktop.protocol import (
    BootstrapToken, ChildFrame, Failure, ParentFrame, ProtocolError,
    Ready, RequestBootstrapToken, Stop, Stopped,
)
from declaw.desktop.notifications import NoticeEmitter
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.app import GatewayLaunchError, assert_launch_contract, create_app
from declaw.gateway.auth import mint_gateway_token
from declaw.gateway.middleware import WS_MESSAGE_CAP_BYTES

STARTUP_SECONDS = 30.0
SHUTDOWN_SECONDS = 10.0


class DesktopChannel(Protocol):
    launch_id: str

    async def receive(self) -> ParentFrame | None: ...
    async def send(self, frame: ChildFrame) -> None: ...
    async def send_bootstrap_token(self, frame: BootstrapToken) -> None: ...
    async def close(self) -> None: ...


async def receive_control(
    channel: DesktopChannel, stop: asyncio.Event, token: Callable[[], str],
) -> None:
    """EOF is stop; credentials use only the dedicated private sender."""
    while True:
        frame = await channel.receive()
        if frame is None:
            stop.set()
            return
        if frame.launch_id != channel.launch_id:
            raise ProtocolError()
        if isinstance(frame, Stop):
            stop.set()
            return
        if isinstance(frame, RequestBootstrapToken):
            value = token()
            await channel.send_bootstrap_token(BootstrapToken(
                launch_id=channel.launch_id, request_id=frame.request_id, token=value,
            ))
            del value


def reserve_listener(settings: Settings) -> socket.socket:
    """Bind before constructing services. No reuse/attachment/port fallback."""
    assert_launch_contract(settings)
    if settings.port != 7842:
        raise GatewayLaunchError("invalid_settings")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.set_inheritable(False)
        listener.bind(("127.0.0.1", 7842))
        listener.listen(128)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


async def run_desktop(settings: Settings, channel: DesktopChannel) -> int:
    """Run one core; native parent independently enforces process deadlines.

    Desktop owns Application.start/shutdown directly rather than cancelling an
    untracked uvicorn lifespan task during partial application startup.
    """
    listener: socket.socket | None = None
    application: Application | None = None
    server: uvicorn.Server | None = None
    serving: asyncio.Task[None] | None = None
    control: asyncio.Task[None] | None = None
    startup: asyncio.Task[None] | None = None
    stopping: asyncio.Task[bool] | None = None
    clean = False
    gateway: FastAPI | None = None
    emitter: NoticeEmitter | None = None
    notices: asyncio.Task[None] | None = None

    async def serve_owned() -> int:
        nonlocal listener, application, server, serving, control, startup, stopping, clean, gateway
        nonlocal emitter, notices
        try:
            listener = reserve_listener(settings)
        except GatewayLaunchError:
            await channel.send(Failure(launch_id=channel.launch_id, code="invalid_settings"))
            return 1
        except OSError:
            await channel.send(Failure(launch_id=channel.launch_id, code="port_conflict"))
            return 1
        store = default_credential_store(settings.data_dir / SECRETS_FILENAME)
        emitter = NoticeEmitter(channel.launch_id,
                                lambda: application.settings_service.effective().language
                                if application is not None else settings.language,
                                channel.send)
        application = Application(settings, mode="gateway", quarantine_event=emitter.quarantine)
        broker = ApprovalBroker(pending_notice=emitter.approval)
        gateway = create_app(settings, application=application, secret_store=store,
                             manage_application_lifespan=False, approval_broker=broker)
        notices = asyncio.create_task(emitter.run())
        stop = asyncio.Event()
        control = asyncio.create_task(receive_control(channel, stop, lambda: mint_gateway_token(store)))
        stopping = asyncio.create_task(stop.wait())
        startup = asyncio.create_task(application.start())
        done, _ = await asyncio.wait(
            {startup, control, stopping}, timeout=STARTUP_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            await channel.send(Failure(launch_id=channel.launch_id, code="startup_timeout"))
            return 1
        if control.done():
            await control
        if stop.is_set():
            clean = True
            return 0
        await startup
        server = uvicorn.Server(uvicorn.Config(
            app=gateway, host="127.0.0.1", port=7842, lifespan="off",
            log_config=None, access_log=False, proxy_headers=False,
            ws_max_size=WS_MESSAGE_CAP_BYTES, timeout_graceful_shutdown=int(SHUTDOWN_SECONDS),
        ))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        deadline = asyncio.get_running_loop().time() + STARTUP_SECONDS
        while not server.started:
            if serving.done():
                await serving
                raise RuntimeError("unavailable")
            if control.done():
                await control
            if stop.is_set():
                clean = True
                return 0
            if asyncio.get_running_loop().time() >= deadline:
                await channel.send(Failure(launch_id=channel.launch_id, code="startup_timeout"))
                return 1
            await asyncio.sleep(.01)
        if hasattr(application, "audit"):
            await application.audit.emit(DesktopLifecycleEvent(launch_id=channel.launch_id, phase="ready"))
        await channel.send(Ready(launch_id=channel.launch_id, authority="127.0.0.1:7842"))
        await asyncio.wait({serving, control, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if control.done():
            await control
        clean = stop.is_set()
        if clean and hasattr(application, "audit"):
            await application.audit.emit(DesktopLifecycleEvent(launch_id=channel.launch_id, phase="stop_requested"))
        return 0 if clean else 1
    try:
        result = await serve_owned()
    except ProtocolError:
        with suppress(Exception):
            await channel.send(Failure(launch_id=channel.launch_id, code="protocol_invalid"))
        result = 1
    except Exception:
        with suppress(Exception):
            await channel.send(Failure(launch_id=channel.launch_id, code="unavailable"))
        result = 1
    finally:
        async def teardown() -> None:
            if startup is not None and not startup.done():
                startup.cancel()
                with suppress(asyncio.CancelledError):
                    await startup
            if application is not None:
                # Refuse/cancel/deny before uvicorn drains connections.
                if server is not None and gateway is not None:
                    manager = gateway.state.session_manager
                    await manager.stop_accepting_sessions()
                    await manager.cancel_in_flight_turns()
                    await manager.deny_pending_approvals()
                    server.should_exit = True
                if serving is not None:
                    await serving
                await application.shutdown()

        try:
            async with asyncio.timeout(SHUTDOWN_SECONDS):
                await teardown()
        except (Exception, asyncio.CancelledError):
            clean = False
            if serving is not None:
                serving.cancel()
            # The native Job owner must enforce final cleanup; never claim clean.
        for task in (control, stopping):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        if emitter is not None:
            await emitter.close()
        if notices is not None:
            notices.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await notices
        if listener is not None:
            listener.close()
        with suppress(Exception):
            await channel.send(Stopped(launch_id=channel.launch_id, clean=clean))
        await channel.close()

    return result if clean else 1
