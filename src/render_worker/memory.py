from __future__ import annotations

import ctypes
import sys


def peak_working_set_mb(pid: int) -> float | None:
    """Observed lifetime peak for one Windows PID, without retaining a handle."""
    if sys.platform != 'win32' or not pid:
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in
            ['peak', 'working', 'qpp', 'qp', 'qnp', 'qn', 'page', 'pagepeak']]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    kernel.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return None
    try:
        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        if kernel.K32GetProcessMemoryInfo(handle, ctypes.byref(counter), counter.cb):
            return round(counter.peak / 1048576, 1)
        return None
    finally:
        kernel.CloseHandle(handle)
