"""Lossy, bounded notices isolated from audit and approval decisions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Literal

from declaw.audit.correlation import current_task_id
from declaw.desktop.protocol import Notice, encode_frame


class NoticeEmitter:
    def __init__(
        self, launch_id: str, language: Callable[[], str],
        send: Callable[[Notice], Awaitable[None]],
    ) -> None:
        self._launch_id = launch_id
        self._language = language
        self._send = send
        self._queue: asyncio.Queue[Notice | None] = asyncio.Queue(64)
        self._closed = False

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def emit_notice(
        self, kind: Literal["quarantine", "approval_pending"], event_id: str,
        task_id: str | None, request_id: str | None = None,
    ) -> None:
        if self._closed:
            return
        try:
            language = self._language()
            if language not in ("en", "fr"):
                return
            frame = Notice(launch_id=self._launch_id, event_id=event_id, kind=kind,
                           language=language, task_id=task_id, request_id=request_id)  # type: ignore[arg-type]
            encode_frame(frame)
            self._queue.put_nowait(frame)
        except Exception:
            # Optional delivery must not prevent audit writes or default-deny.
            # Exception strings may contain external content; never log them.
            return

    def quarantine(self, event_id: str) -> None:
        self.emit_notice("quarantine", event_id, current_task_id.get())

    def approval(self, request_id: str) -> None:
        self.emit_notice("approval_pending", request_id, current_task_id.get(), request_id)

    async def run(self) -> None:
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            with suppress(Exception):
                await self._send(frame)

    async def close(self) -> None:
        self._closed = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)
