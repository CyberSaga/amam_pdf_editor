from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessMemory:
    pid: int
    working_set_bytes: int
    private_commit_bytes: int
    peak_working_set_bytes: int


@dataclass(frozen=True)
class MemoryCohort:
    """One bounded sampling pass, NOT an atomic OS-wide snapshot.

    Working sets include shared pages, so their sum is the conservative RSS
    convention, not unique physical RAM. Missing processes invalidate totals.
    Members' independent lifetime peaks must never be summed as a cohort peak.
    Caller supplies every owned PID; this does not discover descendants or
    protect against PID reuse between an owner lookup and opening its handle.
    """

    started_at: float
    finished_at: float
    samples: tuple[ProcessMemory, ...]
    missing_pids: tuple[int, ...]

    @property
    def working_set_bytes(self) -> int | None:
        return None if self.missing_pids else sum(item.working_set_bytes for item in self.samples)

    @property
    def private_commit_bytes(self) -> int | None:
        return None if self.missing_pids else sum(item.private_commit_bytes for item in self.samples)


def sample_memory_cohort(pids: Iterable[int], *,
                         reader: Callable[[int], ProcessMemory | None] | None = None,
                         clock: Callable[[], float] = time.perf_counter) -> MemoryCohort:
    members = list(pids)
    for pid in members:
        if type(pid) is not int:
            raise TypeError('PID must be an integer')
        if not 0 < pid < 2**32:
            raise ValueError('PID must be a positive DWORD')
    read = reader or read_process_memory
    samples = []
    missing = []
    started = clock()
    for pid in dict.fromkeys(members):
        sample = read(pid)
        if sample is None or sample.pid != pid:
            missing.append(pid)
        else:
            samples.append(sample)
    return MemoryCohort(started, clock(), tuple(samples), tuple(missing))


def read_process_memory(pid: int) -> ProcessMemory | None:
    """Windows current working set and private commit; no handle retained.

    PROCESS_MEMORY_COUNTERS_EX.PrivateUsage is private commit, not private RSS:
    https://learn.microsoft.com/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex
    An inaccessible/exited PID is unknown, never a zero-byte sample.
    """
    if sys.platform != 'win32' or type(pid) is not int or not 0 < pid < 2**32:
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in
            ['PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
             'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
             'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage']]

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
            return ProcessMemory(pid, counter.WorkingSetSize, counter.PrivateUsage,
                                 counter.PeakWorkingSetSize)
        return None
    finally:
        kernel.CloseHandle(handle)


def peak_working_set_mb(pid: int) -> float | None:
    """Legacy single-PID observed lifetime peak; not a combined App peak."""
    sample = read_process_memory(pid)
    return round(sample.peak_working_set_bytes / 1048576, 1) if sample is not None else None
