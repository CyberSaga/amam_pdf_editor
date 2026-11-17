"""Hard memory cap for the object-probe child (H24), a Windows Job Object limit.

Standard library and ``ctypes`` only: the child applies it before it imports PyMuPDF.  A limit
makes allocations fail (``MemoryError`` or a native exit); it does not kill the process.
"""
from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_LIMIT_FLAGS = _JOB_OBJECT_LIMIT_PROCESS_MEMORY | _JOB_OBJECT_LIMIT_JOB_MEMORY

_job_handle = None  # kept for the life of the process, never closed
_kernel32 = None


class ContainmentError(RuntimeError):
    """The memory cap could not be set up or verified."""


if sys.platform == "win32":
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []


def _fail(what: str) -> ContainmentError:
    return ContainmentError(f"{what} failed (GetLastError {ctypes.get_last_error()})")


def apply_job_memory_limit(limit_bytes: int) -> None:
    """Put the current process in a Job Object that caps process and job memory at ``limit_bytes``."""
    global _job_handle
    if sys.platform != "win32":
        raise ContainmentError("unsupported platform")
    if type(limit_bytes) is not int or limit_bytes <= 0:
        raise ContainmentError("invalid memory limit")
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _fail("CreateJobObjectW")
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = _LIMIT_FLAGS
    info.ProcessMemoryLimit = limit_bytes
    info.JobMemoryLimit = limit_bytes
    size = ctypes.sizeof(info)
    if not _kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), size
    ):
        raise _fail("SetInformationJobObject")
    if not _kernel32.AssignProcessToJobObject(job, _kernel32.GetCurrentProcess()):
        raise _fail("AssignProcessToJobObject")
    _job_handle = job
    readback = _ExtendedLimits()
    returned = wintypes.DWORD(0)
    if not _kernel32.QueryInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(readback), size, ctypes.byref(returned)
    ):
        raise _fail("QueryInformationJobObject")
    if (
        (readback.BasicLimitInformation.LimitFlags & _LIMIT_FLAGS) != _LIMIT_FLAGS
        or readback.ProcessMemoryLimit != limit_bytes
        or readback.JobMemoryLimit != limit_bytes
    ):
        raise _fail("limit readback mismatch")
