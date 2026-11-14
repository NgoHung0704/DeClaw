"""Windows synchronous pipe shutdown must not strand interpreter teardown."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["stop", "idle"])
@pytest.mark.skipif(os.name != "nt", reason="Windows synchronous pipe behavior")
def test_stop_closes_private_reader_without_waiting_for_parent_eof(mode: str) -> None:
    script = r'''
import asyncio,io,os,sys
from declaw.desktop.channel import PipeChannel
from declaw.desktop.protocol import Stop,encode_frame
async def main():
    read,write=os.pipe()
    channel=PipeChannel('00000000-0000-0000-0000-000000000000',os.fdopen(read,'rb',buffering=0),io.BytesIO(),io.BytesIO())
    receive=asyncio.create_task(channel.receive())
    if sys.argv[1]=="stop":
        os.write(write,encode_frame(Stop(launch_id=channel.launch_id)))
        await receive
    await asyncio.sleep(.1)
    await channel.close()
    receive.cancel()
    os.close(write)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, "-c", script, mode], capture_output=True, timeout=4)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(os.name != "nt", reason="Windows inherited handle boundary")
async def test_descendant_cannot_retain_control_or_forge_private_events() -> None:
    import ctypes
    import json
    import time
    from ctypes import wintypes
    from declaw.desktop.channel import PipeChannel

    class Attributes(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("descriptor", wintypes.LPVOID),
                    ("inherit", wintypes.BOOL)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
                                  ctypes.POINTER(Attributes), wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    pairs: list[tuple[int, int]] = []
    for _ in range(3):
        read, write = wintypes.HANDLE(), wintypes.HANDLE()
        attributes = Attributes(ctypes.sizeof(Attributes), None, True)
        assert kernel.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(attributes), 0)
        pairs.append((read.value, write.value))
    selected = [pairs[0][0], pairs[1][1], pairs[2][1]]
    parents = [pairs[0][1], pairs[1][0], pairs[2][0]]
    channel = PipeChannel.from_handles("00000000-0000-0000-0000-000000000000", *selected)
    for handle in selected:
        assert os.get_handle_inheritable(handle) is False
    for handle in parents:
        os.set_handle_inheritable(handle, False)
    script = r'''
import ctypes,json,sys,time
from ctypes import wintypes
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetFileType.argtypes=[wintypes.HANDLE];k.GetFileType.restype=wintypes.DWORD
k.WriteFile.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID]
handles=[int(value) for value in sys.argv[1:]]
written=wintypes.DWORD()
forged=k.WriteFile(handles[1],ctypes.create_string_buffer(b'forged'),6,ctypes.byref(written),None)
print(json.dumps(dict(types=[k.GetFileType(h) for h in handles],forged=bool(forged))),flush=True)
time.sleep(5)
'''
    child = subprocess.Popen([sys.executable, "-c", script, *map(str, selected)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=False)
    try:
        assert child.stdout is not None
        report = json.loads(child.stdout.readline())
        assert report["types"] == [0, 0, 0]
        assert report["forged"] is False
        await channel.close()
        assert child.poll() is None
        started = time.monotonic()
        buffer, count = ctypes.create_string_buffer(1), wintypes.DWORD()
        assert kernel.ReadFile(parents[1], buffer, 1, ctypes.byref(count), None) == 0
        assert ctypes.get_last_error() == 109  # ERROR_BROKEN_PIPE while descendant is alive
        assert time.monotonic() - started < 1
    finally:
        child.terminate()
        child.wait(timeout=5)
        await channel.close()
        for handle in parents:
            kernel.CloseHandle(handle)
