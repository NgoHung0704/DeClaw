"""Private inherited Windows pipe transport; no network control endpoint."""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import suppress
from typing import BinaryIO

from declaw.desktop.protocol import (
    BootstrapToken, ChildFrame, FrameDecoder, ParentFrame, ProtocolError,
    RequestBootstrapToken, Stop, encode_frame,
)


class PipeChannel:
    """One bounded control reader and separate event/credential writers.

    The control reader uses a daemon thread because Windows anonymous inherited
    pipes are synchronous, not asyncio-overlapped handles. It never owns an
    unbounded queue or keeps the interpreter alive after parent/job teardown.
    """

    def __init__(
        self, launch_id: str, control: BinaryIO, events: BinaryIO, credentials: BinaryIO,
    ) -> None:
        self.launch_id = launch_id
        self._control = control
        self._events = events
        self._credentials = credentials
        self._queue: asyncio.Queue[ParentFrame | ProtocolError | None] = asyncio.Queue(1)
        self._reader: threading.Thread | None = None
        self._closed = threading.Event()
        self._event_lock = asyncio.Lock()
        self._credential_lock = asyncio.Lock()

    @classmethod
    def from_handles(
        cls, launch_id: str, control: int, events: int, credentials: int,
    ) -> PipeChannel:
        """Consume only pipe handles; remove inheritance before any plugins start."""
        if os.name != "nt" or len({control, events, credentials}) != 3:
            raise ProtocolError()
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetFileType.argtypes = [wintypes.HANDLE]
        kernel.GetFileType.restype = wintypes.DWORD
        for handle in (control, events, credentials):
            if handle <= 0 or kernel.GetFileType(handle) != 3:  # FILE_TYPE_PIPE
                raise ProtocolError()
            os.set_handle_inheritable(handle, False)
        descriptors: list[int] = []
        try:
            for handle, mode in ((control, os.O_RDONLY), (events, os.O_WRONLY),
                                 (credentials, os.O_WRONLY)):
                descriptor = msvcrt.open_osfhandle(handle, mode | os.O_BINARY)
                os.set_inheritable(descriptor, False)
                descriptors.append(descriptor)
            return cls(launch_id, os.fdopen(descriptors[0], "rb", buffering=0),
                       os.fdopen(descriptors[1], "wb", buffering=0),
                       os.fdopen(descriptors[2], "wb", buffering=0))
        except BaseException:
            for descriptor in descriptors:
                with suppress(OSError):
                    os.close(descriptor)
            raise

    def _read(self, loop: asyncio.AbstractEventLoop) -> None:
        decoder = FrameDecoder(direction="parent")

        def enqueue(frame: ParentFrame | ProtocolError | None) -> None:
            future = asyncio.run_coroutine_threadsafe(self._queue.put(frame), loop)
            # Bounded backpressure; don't strand a non-daemon executor thread.
            while not self._closed.is_set():
                try:
                    future.result(timeout=.1)
                    return
                except TimeoutError:
                    continue
            future.cancel()

        try:
            while not self._closed.is_set():
                chunk = self._control.read(4096)
                if not chunk:
                    decoder.finish()
                    enqueue(None)
                    return
                for frame in decoder.feed(chunk):
                    if not isinstance(frame, (Stop, RequestBootstrapToken)):
                        raise ProtocolError()
                    enqueue(frame)
                    if isinstance(frame, Stop):
                        return  # Do not wait on a second read during cooperative teardown.
        except (OSError, ValueError):
            if not self._closed.is_set():
                enqueue(ProtocolError())

    async def receive(self) -> ParentFrame | None:
        if self._reader is None:
            self._reader = threading.Thread(
                target=self._read, args=(asyncio.get_running_loop(),), daemon=True,
                name="declaw-desktop-control",
            )
            self._reader.start()
        frame = await self._queue.get()
        if isinstance(frame, ProtocolError):
            raise frame
        return frame

    @staticmethod
    def _write(stream: BinaryIO, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            count = stream.write(remaining)
            if count is None or count <= 0:
                raise ProtocolError()
            remaining = remaining[count:]

    async def send(self, frame: ChildFrame) -> None:
        async with self._event_lock:
            await asyncio.to_thread(self._write, self._events, encode_frame(frame))

    async def send_bootstrap_token(self, frame: BootstrapToken) -> None:
        async with self._credential_lock:
            await asyncio.to_thread(self._write, self._credentials, encode_frame(frame))

    async def close(self) -> None:
        self._closed.set()
        if self._reader is not None and self._reader.is_alive() and os.name == "nt":
            # CRT close waits for an in-flight synchronous read's descriptor lock.
            # Cancel the reader's I/O first; never close it from the loop while blocked.
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenThread.restype = wintypes.HANDLE
            kernel.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
            kernel.CancelSynchronousIo.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenThread(1, False, self._reader.native_id)  # THREAD_TERMINATE
            if handle:
                try:
                    deadline = asyncio.get_running_loop().time() + .5
                    while self._reader.is_alive() and asyncio.get_running_loop().time() < deadline:
                        kernel.CancelSynchronousIo(handle)
                        await asyncio.sleep(.01)
                finally:
                    kernel.CloseHandle(handle)
        for stream in (self._control, self._events, self._credentials):
            if stream is self._control and self._reader is not None and self._reader.is_alive():
                continue  # Daemon reader/OS process cleanup owns this still-blocked handle.
            with suppress(OSError):
                stream.close()
