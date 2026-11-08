"""Supervised whole-suite runner: the only sanctioned way to run the full test suite.

Design (plans/archive/test-suite-never-hangs.md, 1.1): every test file of the Qt lane runs
in its own child pytest process, all pure files share one child, and every child
runs under an external supervisor.  The supervisor watches a heartbeat file
written by ``scripts/pytest_heartbeat.py``; when it stops growing for
``--stall-seconds`` or the job outlives ``--file-ceiling`` the supervisor first
saves evidence (py-spy dump when available, heartbeat copy, log tail) and then
kills the child's whole process tree.  The hung test is named (last ``start``
without a ``finish``), the job is rerun once without it, and every job's junit
is merged into one report with one summary line.

An in-process watchdog cannot be the guarantee: ``faulthandler_exit_on_timeout``
deadlocks in ``ExitProcess`` when a Python thread is running (measured 5/5), so
only an external kill ends such a process every time.

Usage (from anywhere; paths derive from this file)::

    python scripts/run_suite.py                       # whole suite, both lanes
    python scripts/run_suite.py --files test_scripts/test_x.py --stall-seconds 120
    python scripts/run_suite.py -m "not local_only" --junit report.xml --cov
    python scripts/run_suite.py --lane pure -- -x     # args after -- go to pytest
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Run as a script only scripts/ is on sys.path; the repo root makes `scripts.*` importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._pytest_env import clean_pytest_env
from scripts.pytest_heartbeat import HEARTBEAT_ENV, pending_culprit, read_heartbeat

logger = logging.getLogger(__name__)

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
# Indented imports (inside a test function) and the conftest Qt fixtures count as Qt:
# such files create widgets and must not share the one pure interpreter.
QT_PATTERN: re.Pattern[str] = re.compile(
    r"PySide6|^[ \t]*(from|import) (view|controller|main\b|src\.printing)|qt_teardown|QApplication"
    r"|\bqapp\b|\bqtbot\b",
    re.MULTILINE,
)
# Lane overrides, posix paths relative to REPO_ROOT.  test_run_suite.py only names
# Qt in string literals (QT_PATTERN fixtures) and imports no Qt at all.
_FORCE_QT: set[str] = set()
_FORCE_PURE: set[str] = {"test_scripts/test_run_suite.py"}

STATUS_OK = "OK"
STATUS_FAIL = "FAIL"
STATUS_RC5_OK = "RC5_OK"
STATUS_COLLECT_ERROR = "COLLECT_ERROR"
STATUS_HUNG = "HUNG"
STATUS_CRASH = "CRASH"
_RC5 = "RC5"  # transient verdict, resolved by the collect-only probe

_LOG_TAIL_LINES = 200
_HEARTBEAT_TAIL_LINES = 20
# The three hang thresholds, defined once: argparse, supervise, run_job, collect_probe and
# SuiteTiming all default to them (see SuiteTiming for the layer order a test pins).
DEFAULT_STALL_SECONDS = 600.0  # > pyproject faulthandler_timeout (540) + one poll
DEFAULT_FILE_CEILING = 3600.0  # per job; CI passes 2400
DEFAULT_POLL_SECONDS = 5.0
_KILL_VERIFY_SECONDS = 15.0
_PYSPY_TIMEOUT = 60.0
_PYSPY_WARNED: list[bool] = []  # non-empty once the "py-spy not on PATH" line was logged
_COLLECT_RE = re.compile(r"(?<![\d/])(\d+)(?:/\d+)? tests? collected")


def classify(source: str, rel_path: str) -> str:
    """Return ``"qt"`` or ``"pure"`` for a test file; the override sets win."""
    if rel_path in _FORCE_PURE:
        return "pure"
    if rel_path in _FORCE_QT:
        return "qt"
    return "qt" if QT_PATTERN.search(source) else "pure"


@dataclass
class JobSpec:
    name: str
    files: list[Path]
    lane: str
    marker_expr: str | None = None
    passthrough: list[str] = field(default_factory=list)
    deselect: list[str] = field(default_factory=list)


def pytest_command(
    spec: JobSpec,
    junit: Path,
    python: str = sys.executable,
    extra: Sequence[str] = (),
) -> list[str]:
    """The child pytest command line for *spec* (layout pinned by test_run_suite.py)."""
    cmd = [python, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider", "--junitxml", str(junit)]
    if spec.marker_expr:
        cmd += ["-m", spec.marker_expr]
    for nodeid in spec.deselect:
        cmd += ["--deselect", nodeid]
    # Children run with cwd=REPO_ROOT. Repeating an absolute worktree path for
    # every pure-lane file can exceed Windows' CreateProcess command limit.
    for file in spec.files:
        try:
            cmd.append(str(file.relative_to(REPO_ROOT)))
        except ValueError:
            cmd.append(str(file))
    cmd += list(spec.passthrough)
    cmd += list(extra)
    return cmd


class JobCancelled(Exception):
    """The run is being torn down (``--parallel-lanes``: the other lane raised); the
    supervisor killed its child tree first."""


@dataclass
class SupervisedExit:
    returncode: int | None
    killed: bool
    reason: str | None
    elapsed: float
    evidence: list[Path] = field(default_factory=list)


# --------------------------------------------------------------------------- process tree

# A CreateProcess flag, a plain int so that _WindowsTree().popen_kwargs() also answers where kernel32 is absent.
_CREATE_SUSPENDED = 0x00000004

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", ctypes.c_long),
            ("tpDeltaPri", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
        ]

    class _JobBasicLimit(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
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

    class _IoCounters(ctypes.Structure):  # IO_COUNTERS
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JobExtendedLimit(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JobAccounting(ctypes.Structure):  # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    # Every call keeps its restype/argtypes: an untyped HANDLE is truncated (PITFALLS "Untyped ctypes windll").
    _k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _k32.OpenThread.restype = wintypes.HANDLE
    _k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.ResumeThread.restype = wintypes.DWORD
    _k32.ResumeThread.argtypes = [wintypes.HANDLE]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]

    _TH32CS_SNAPPROCESS = 0x00000002
    _TH32CS_SNAPTHREAD = 0x00000004
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _WAIT_TIMEOUT = 0x00000102
    _THREAD_SUSPEND_RESUME = 0x0002
    _RESUME_FAILED = 0xFFFFFFFF
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_BASIC_ACCOUNTING = 1  # JobObjectBasicAccountingInformation
    _JOB_EXTENDED_LIMIT = 9  # JobObjectExtendedLimitInformation


def _win_process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, image name) from one toolhelp snapshot."""
    table: dict[int, tuple[int, str]] = {}
    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE:
        return table
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return table


def _win_creation_time(handle: int) -> int:
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not _k32.GetProcessTimes(
        handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return 0
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


@dataclass
class _TreeMember:
    pid: int
    name: str
    handle: int | None = None  # Windows: an open handle pins the pid against reuse


def _win_descendants(root_pid: int) -> list[_TreeMember]:
    """Live descendants of *root_pid*, each with an open handle.

    A parent-pid link only counts when the child was created after its parent, so a
    stale parent pid that Windows reused never pulls in a process we did not spawn.
    """
    table = _win_process_table()
    access = _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE
    root = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, root_pid)
    if not root:
        return []
    try:
        ctimes = {root_pid: _win_creation_time(root)}
    finally:
        _k32.CloseHandle(root)
    members: list[_TreeMember] = []
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        for pid, (ppid, name) in table.items():
            if ppid != parent or pid in ctimes or pid == parent:
                continue
            handle = _k32.OpenProcess(access, False, pid)
            if not handle:
                continue
            ctime = _win_creation_time(handle)
            if ctime < ctimes[parent]:
                _k32.CloseHandle(handle)
                continue
            ctimes[pid] = ctime
            members.append(_TreeMember(pid, name, handle))
            frontier.append(pid)
    return members


def _resume_threads(pid: int) -> None:
    """Resume the suspended primary thread of our own child *pid* (started CREATE_SUSPENDED).

    Popen closes its thread handle, so a Toolhelp thread snapshot finds the thread by its owner pid; the caller's
    Popen still holds the process handle, so the pid cannot have been reused.  Raises OSError when no thread
    could be resumed: a child that never runs would wait for the stall kill.
    """
    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap or snap == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    tids: list[int] = []
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(_ThreadEntry32)
        ok = _k32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                tids.append(int(entry.th32ThreadID))
            ok = _k32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    resumed = False
    for tid in tids:
        thread = _k32.OpenThread(_THREAD_SUSPEND_RESUME, False, tid)
        if not thread:
            continue
        try:
            resumed = _k32.ResumeThread(thread) != _RESUME_FAILED or resumed
        finally:
            _k32.CloseHandle(thread)
    if not resumed:
        raise OSError(f"could not resume the suspended primary thread of pid {pid}")


def _job_active(job: int) -> int:
    """Processes still active in *job*, nested jobs included (the venv redirector's own); -1 if unknown."""
    info = _JobAccounting()
    if not _k32.QueryInformationJobObject(job, _JOB_BASIC_ACCOUNTING, ctypes.byref(info), ctypes.sizeof(info), None):
        logger.warning("cannot query a job object (WinError %s): its members are not verified", ctypes.get_last_error())
        return -1
    return int(info.ActiveProcesses)


def _job_drained(job: int, deadline: float) -> bool:
    """Wait until *job* has no active process, terminating it again on every poll; False if it still had one
    at *deadline* (checked once even when *deadline* already passed).  An unknown count ends the wait."""
    while True:
        if _job_active(job) <= 0:
            return True
        if time.monotonic() >= deadline:
            return False
        _k32.TerminateJobObject(job, 1)  # again: a process that joined while the previous terminate ran
        time.sleep(0.01)


def _posix_descendants(root_pid: int) -> list[_TreeMember]:
    """Best-effort descendants on POSIX (only used to aim py-spy; killpg does the kill)."""
    children: dict[int, list[tuple[int, str]]] = {}
    proc_dir = Path("/proc")
    if proc_dir.is_dir():
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text()
            except OSError:
                continue
            name = stat[stat.find("(") + 1 : stat.rfind(")")]
            fields = stat.rsplit(")", 1)[1].split()
            children.setdefault(int(fields[1]), []).append((int(entry.name), name))
    else:
        try:
            out = subprocess.run(
                ["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=10
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                children.setdefault(int(parts[1]), []).append((int(parts[0]), parts[2]))
    members: list[_TreeMember] = []
    frontier = [root_pid]
    seen = {root_pid}
    while frontier:
        for pid, name in children.get(frontier.pop(), []):
            if pid not in seen:
                seen.add(pid)
                members.append(_TreeMember(pid, name))
                frontier.append(pid)
    return members


class _ProcessTree:
    """How the supervisor starts, enumerates, dumps and closes one child's process tree.

    One instance, ``_TREE``, is chosen at import time.  Two kinds only, Windows and
    POSIX (Linux and macOS share every line: /proc when it exists, else ``ps``).  ``kill``
    fixes the order of the kill for both kinds; a kind only fills in its steps.
    ``_kill_tree`` and ``_reap_tree`` stay module seams that forward to it.  Lifecycle:
    ``popen_kwargs`` -> ``attach`` (first thing ``supervise`` does) -> ``kill`` for a live root
    or ``reap`` for one that already exited -> ``release`` (also in ``supervise``'s finally).

    The reach differs by kind.  Windows starts the child suspended and puts it in a Job
    Object of its own (KILL_ON_JOB_CLOSE) before it runs: every process the tree ever
    starts is in the job, so the kill reaches the orphans of an exited root, descendants
    behind a dead intermediate parent and processes spawned during the kill, and the job's
    close ends the tree even when run_suite itself dies.  The parent-pid walk with pinned
    handles stays as the second step and is the whole reach when attach fell back.  POSIX
    starts the child in its own session and kills the PROCESS GROUP: a descendant that
    starts its own session or group survives (E5 in plans/run-suite-job-object.md, a TODO,
    not fixed here), and ``reap`` does nothing, so the group an exited root leaves behind
    is not ended either.
    """

    kind = "abstract"

    def popen_kwargs(self) -> dict[str, object]:
        """Extra ``subprocess.Popen`` keyword arguments for the supervised child."""
        return {}

    def attach(self, proc: subprocess.Popen) -> None:
        """Bind the child *proc* that ``popen_kwargs`` just started to this kind's kill (default: nothing)."""

    def descendants(self, root_pid: int) -> list[_TreeMember]:
        """Live descendants of *root_pid*; best-effort, never raises."""
        try:
            return self._enumerate(root_pid)
        except Exception:  # noqa: BLE001 - evidence and verification are best-effort
            logger.warning("could not enumerate the process tree of pid %s", root_pid, exc_info=True)
            return []

    def pyspy_targets(self, root_pid: int, members: list[_TreeMember]) -> list[int]:
        """Pids to dump with py-spy: the root and every member."""
        return [root_pid] + [m.pid for m in members]

    def kill(self, proc: subprocess.Popen, members: list[_TreeMember]) -> list[int]:
        """Kill *proc* and its whole tree; return the pids still alive after the bound.

        Only processes we spawned are touched: *proc* itself, the processes in its job
        (Windows; only *proc*'s tree can join it) and the descendants that were enumerated
        (with pinned handles on Windows) while *proc* was alive.

        Windows terminates the job first (``TerminateJobObject``), then by handle only, never
        by a bare pid: every member passed the creation-time check in ``_win_descendants``, so
        a stale parent pid that Windows reused for an unrelated process can never be reached
        (``taskkill /T`` walks bare parent pids and could).  A fresh enumeration right before
        the kill catches anything the tree spawned since the evidence pass; descendants are
        ended before the root so the venv launcher never leaves its real python child
        orphaned.  The verification also waits for the job to be empty (a job that is not is
        reported as ``-proc.pid``, like a POSIX group).

        Every handle in *members* and every handle of the fresh enumeration is closed before
        returning, including the fresh duplicate of a pid already in *members*; the job
        handle is closed last (``release``).
        """
        targets = list(members)
        try:
            self._add_late_members(proc, targets)  # Windows: fresh enumeration; POSIX: nothing
            self._signal(proc, targets)  # Windows: TerminateProcess per handle; POSIX: killpg
            try:
                proc.kill()  # the root last (the venv launcher after its python child)
            except OSError:
                pass
            deadline = time.monotonic() + _KILL_VERIFY_SECONDS
            try:
                proc.wait(timeout=_KILL_VERIFY_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            survivors: list[int] = []
            if proc.poll() is None:
                survivors.append(proc.pid)
            survivors += self._verify(proc, targets, deadline)
            return survivors
        finally:
            try:
                self.close(targets)  # every pinned handle, the caller's and the fresh ones
            finally:
                self.release(proc)  # Windows: the job handle last, so KILL_ON_JOB_CLOSE ends any straggler

    def close(self, members: list[_TreeMember]) -> None:
        """Close every pinned handle in *members* (POSIX pins none)."""

    def reap(self, proc: subprocess.Popen) -> list[int]:
        """End what the already exited *proc* left behind, then ``release`` it; return what is still alive after
        the bound, like ``kill`` (default: nothing to end)."""
        return []

    def release(self, proc: subprocess.Popen) -> None:
        """Drop what ``attach`` holds for *proc*; idempotent (default: nothing)."""

    def _enumerate(self, root_pid: int) -> list[_TreeMember]:
        raise NotImplementedError

    def _add_late_members(self, proc: subprocess.Popen, targets: list[_TreeMember]) -> None:
        """Append what the tree spawned since *targets* was enumerated (default: nothing)."""

    def _signal(self, proc: subprocess.Popen, targets: list[_TreeMember]) -> None:
        raise NotImplementedError

    def _verify(self, proc: subprocess.Popen, targets: list[_TreeMember], deadline: float) -> list[int]:
        """Pids still alive at *deadline* (the root is checked by ``kill`` itself)."""
        raise NotImplementedError


class _WindowsTree(_ProcessTree):
    """One Job Object per supervised child (KILL_ON_JOB_CLOSE, a non-inheritable handle), then the walk.

    ``attach`` creates the job and assigns the suspended child before resuming it; when that fails it
    warns and the kill falls back to the parent-pid walk alone (plans/run-suite-job-object.md).
    """

    kind = "windows"

    def __init__(self) -> None:
        super().__init__()
        # One job per supervised child, by its pid.  The --parallel-lanes threads share _TREE, so the dict is
        # locked, and only around the dict itself, never around a kernel call that waits.
        self._jobs: dict[int, int] = {}
        self._jobs_lock = threading.Lock()

    def popen_kwargs(self) -> dict[str, object]:
        # Suspended until attach() has put it in its job, so nothing it spawns can start outside the job.
        return {"creationflags": _CREATE_SUSPENDED}

    def attach(self, proc: subprocess.Popen) -> None:
        """Put the suspended child in a job of its own, then resume it, also when the job failed."""
        try:
            self._open_job(proc)
        except OSError as exc:
            logger.warning(
                "could not put pid %s in a job object (%s); its kill falls back to the parent-pid walk", proc.pid, exc
            )
        finally:
            _resume_threads(proc.pid)  # always: a child left suspended would only end at the stall kill

    def reap(self, proc: subprocess.Popen) -> list[int]:
        """Terminate what the exited *proc* left in its job, wait until the job is empty, close it."""
        job = self._job(proc)
        if job is None:
            return []
        try:
            active = _job_active(job)
            if active > 0:
                logger.warning("pid %s exited and left %d process(es) in its job; ending them", proc.pid, active)
            _k32.TerminateJobObject(job, 1)  # a no-op on an empty job
            return [] if _job_drained(job, time.monotonic() + _KILL_VERIFY_SECONDS) else [-proc.pid]
        finally:
            self.release(proc)

    def release(self, proc: subprocess.Popen) -> None:
        """Close *proc*'s job handle, if it has one; idempotent."""
        with self._jobs_lock:
            job = self._jobs.pop(proc.pid, None)
        if job:
            _k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: whatever is still in the job ends with this handle

    def _job(self, proc: subprocess.Popen) -> int | None:
        with self._jobs_lock:
            return self._jobs.get(proc.pid)

    def _open_job(self, proc: subprocess.Popen) -> None:
        """Create *proc*'s job (KILL_ON_JOB_CLOSE) and assign the suspended child to it; OSError on failure."""
        job = _k32.CreateJobObjectW(None, None)  # NULL attributes: a handle that no child can inherit
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        with self._jobs_lock:
            self._jobs[proc.pid] = job  # owned from here: release() closes it on every path
        try:
            limits = _JobExtendedLimit()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _k32.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = _k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, proc.pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not _k32.AssignProcessToJobObject(job, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _k32.CloseHandle(handle)
        except OSError:
            self.release(proc)  # the child is not in the job, so closing it ends nothing
            raise

    def pyspy_targets(self, root_pid: int, members: list[_TreeMember]) -> list[int]:
        # Never conhost.exe and friends: py-spy only attaches to python.
        return [root_pid] + [m.pid for m in members if "python" in m.name.lower()]

    def close(self, members: list[_TreeMember]) -> None:
        for member in members:
            if member.handle:
                _k32.CloseHandle(member.handle)
                member.handle = None

    def _enumerate(self, root_pid: int) -> list[_TreeMember]:
        return _win_descendants(root_pid)  # looked up at call time: a module seam

    def _add_late_members(self, proc: subprocess.Popen, targets: list[_TreeMember]) -> None:
        known = {member.pid for member in targets}
        fresh = self.descendants(proc.pid)
        # One statement: from here the template's finally owns every fresh handle, so an
        # interrupt (a second Ctrl+C) in the lines below cannot leak one.
        targets.extend(fresh)
        # The caller's earlier handle already pins a known pid, so its fresh duplicate only
        # holds the process object open: close it now.  The entry stays in targets with
        # handle None, which _signal and _verify skip.
        self.close([member for member in fresh if member.pid in known])

    def _signal(self, proc: subprocess.Popen, targets: list[_TreeMember]) -> None:
        job = self._job(proc)
        if job is not None:
            # First, every process in the job at once: the in-flight spawns, an exited root's orphans and the
            # descendants behind a dead intermediate, which no parent-pid walk can see.
            _k32.TerminateJobObject(job, 1)
        for member in targets:  # then by handle (all there is when attach fell back), never a bare pid or taskkill /T
            if member.handle:
                _k32.TerminateProcess(member.handle, 1)

    def _verify(self, proc: subprocess.Popen, targets: list[_TreeMember], deadline: float) -> list[int]:
        survivors: list[int] = []
        for member in targets:
            if not member.handle:
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if _k32.WaitForSingleObject(member.handle, remaining_ms) == _WAIT_TIMEOUT:
                # Still alive (TerminateProcess is asynchronous): one more try.
                _k32.TerminateProcess(member.handle, 1)
                if _k32.WaitForSingleObject(member.handle, 5000) == _WAIT_TIMEOUT:
                    survivors.append(member.pid)
        job = self._job(proc)
        if job is not None and not _job_drained(job, deadline):
            survivors.append(-proc.pid)  # the job still has members: the marker POSIX uses for its group
        return survivors


class _PosixTree(_ProcessTree):
    """The process-group kill (``killpg``); attach, reap and release are the base no-ops.

    Its reach is not the Windows job's: a descendant that leaves the group (``setsid``,
    ``start_new_session=True``, ``setpgid``) survives the kill (E5: report the evidence-time
    members, then a pidfd kill, is a TODO, not fixed here), and nothing ends the group that a
    root which exited by itself leaves behind.
    """

    kind = "posix"

    def popen_kwargs(self) -> dict[str, object]:
        # A new session makes pgid == pid, so killpg(proc.pid) addresses the child's group.
        return {"start_new_session": True}

    def _enumerate(self, root_pid: int) -> list[_TreeMember]:
        return _posix_descendants(root_pid)  # only aims py-spy and the evidence header

    def _signal(self, proc: subprocess.Popen, targets: list[_TreeMember]) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True: pgid == pid
        except OSError:
            pass

    def _verify(self, proc: subprocess.Popen, targets: list[_TreeMember], deadline: float) -> list[int]:
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except OSError:
                return []  # the group is gone
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                return []
            time.sleep(0.1)
        return [-proc.pid]  # the process group still has members


_TREE: _ProcessTree = _WindowsTree() if sys.platform == "win32" else _PosixTree()


def _descendants(root_pid: int) -> list[_TreeMember]:
    return _TREE.descendants(root_pid)


def _close_members(members: list[_TreeMember]) -> None:
    _TREE.close(members)


def _kill_tree(proc: subprocess.Popen, members: list[_TreeMember]) -> list[int]:
    """Kill *proc* and its whole tree (see _ProcessTree.kill).  A module seam on purpose:
    supervise() calls it by name and test_supervise_collects_evidence_before_it_kills spies it."""
    return _TREE.kill(proc, members)


def _reap_tree(proc: subprocess.Popen) -> None:
    """End what the exited *proc* left behind (see _ProcessTree.reap) and warn about what survived; the
    module seam supervise() calls at its three exited-root sites."""
    survivors = _TREE.reap(proc)
    if survivors:
        logger.warning("process tree of pid %s not gone after the kill: %s", proc.pid, survivors)


# --------------------------------------------------------------------------- evidence


def _tail_lines(path: Path, n: int) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 256 * 1024))
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


def _collect_evidence(
    proc: subprocess.Popen,
    members: list[_TreeMember],
    *,
    heartbeat: Path,
    log: Path,
    evidence_dir: Path,
    reason: str,
    elapsed: float,
) -> list[Path]:
    """Save py-spy dumps, the heartbeat and the log tail; never raises."""
    evidence: list[Path] = []
    if not _ensure_dir(evidence_dir):
        return evidence
    stem = log.stem
    header = (
        f"run_suite: {reason} after {elapsed:.1f}s, child pid {proc.pid}, "
        f"tree {[(m.pid, m.name) for m in members]}\n"
    )

    pyspy = shutil.which("py-spy")
    if pyspy:
        targets = _TREE.pyspy_targets(proc.pid, members)
        out = evidence_dir / f"{stem}.pyspy.txt"
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(header)
                for pid in targets:
                    fh.write(f"\n===== py-spy dump --native --pid {pid} =====\n")
                    try:
                        res = subprocess.run(
                            [pyspy, "dump", "--native", "--pid", str(pid)],
                            capture_output=True,
                            text=True,
                            errors="replace",
                            timeout=_PYSPY_TIMEOUT,
                        )
                        fh.write(res.stdout)
                        if res.stderr:
                            fh.write(f"--- stderr (rc {res.returncode}) ---\n{res.stderr}")
                    except (OSError, subprocess.SubprocessError) as exc:
                        fh.write(f"py-spy failed: {exc!r}\n")
            evidence.append(out)
        except OSError:
            logger.warning("cannot write %s", out, exc_info=True)
    else:
        header += "py-spy not on PATH: no native stack dump\n"
        if not _PYSPY_WARNED:
            _PYSPY_WARNED.append(True)
            logger.warning("py-spy not on PATH; hung jobs get no native stack dump (heartbeat + log tail only)")

    evidence += _save_heartbeat_and_tail(heartbeat, log, evidence_dir, header)
    return evidence


def _ensure_dir(evidence_dir: Path) -> bool:
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cannot create evidence dir %s", evidence_dir, exc_info=True)
        return False
    return True


def _save_heartbeat_and_tail(heartbeat: Path, log: Path, evidence_dir: Path, header: str) -> list[Path]:
    """Copy the heartbeat and write the log tail into *evidence_dir*; never raises."""
    evidence: list[Path] = []
    if not _ensure_dir(evidence_dir):
        return evidence
    stem = log.stem
    hb_copy = evidence_dir / f"{stem}.heartbeat"
    try:
        if heartbeat.exists():
            shutil.copyfile(heartbeat, hb_copy)
        else:
            hb_copy.write_text("no heartbeat was written (hang before the first test)\n", encoding="utf-8")
        evidence.append(hb_copy)
    except OSError:
        logger.warning("cannot copy heartbeat %s", heartbeat, exc_info=True)

    tail = evidence_dir / f"{stem}.tail.log"
    try:
        lines = _tail_lines(log, _LOG_TAIL_LINES)
        tail.write_text(
            header + f"--- last {len(lines)} lines of {log.name} ---\n" + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        evidence.append(tail)
    except OSError:
        logger.warning("cannot write log tail %s", tail, exc_info=True)
    return evidence


# --------------------------------------------------------------------------- supervise


def supervise(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    heartbeat: Path,
    log: Path,
    stall_seconds: float,
    file_ceiling: float,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    evidence_dir: Path | None = None,
    cancel: threading.Event | None = None,
) -> SupervisedExit:
    """Run *cmd* to completion, or kill its whole tree on a stall or the ceiling.

    Progress is any change of the heartbeat file's (size, mtime), read fresh by
    ``os.stat`` every poll; before the first beat the process start counts.
    Evidence is collected before the kill; the kill is verified within a bound.
    A set *cancel* event kills the tree at the next poll and raises JobCancelled.
    """
    if evidence_dir is None:
        evidence_dir = log.parent / "evidence"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "wb") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **_TREE.popen_kwargs(),
        )
    try:  # opens right after Popen: the handler below must see every line that can raise
        _TREE.attach(proc)  # Windows: into its own job, then resumed (popen_kwargs started it suspended)
        start = time.monotonic()
        last_progress = start
        prev_poll = start
        last_sig: tuple[int, int] | None = None
        reason: str | None = None
        while True:
            try:
                rc = proc.wait(timeout=poll_seconds)
            except subprocess.TimeoutExpired:
                pass
            else:
                _reap_tree(proc)  # the root exited by itself: what it left in its job still holds the log
                return SupervisedExit(rc, False, None, time.monotonic() - start, [])
            if cancel is not None and cancel.is_set():
                raise JobCancelled(f"pid {proc.pid}")  # the handler below kills the tree
            now = time.monotonic()
            try:
                st = os.stat(heartbeat)
                sig = (st.st_size, st.st_mtime_ns)
            except OSError:
                sig = None
            if sig is not None and sig != last_sig:
                last_sig = sig
                # Credit the write time itself (mtime age mapped onto the monotonic
                # clock).  The change proves a write after the previous poll, so that
                # is the floor; a skewed mtime never moves progress back or ahead.
                age = max(0.0, time.time() - st.st_mtime)
                last_progress = min(now, max(last_progress, prev_poll, now - age))
            prev_poll = now
            elapsed = now - start
            if now - last_progress > stall_seconds:
                reason = "stall"
            elif elapsed > file_ceiling:
                reason = "ceiling"
            if reason is None:
                continue
            if proc.poll() is not None:  # exited between the wait and the check
                _reap_tree(proc)  # still killed=False (it ended by itself); reap logs what it left behind
                return SupervisedExit(proc.returncode, False, None, time.monotonic() - start, [])
            members = _descendants(proc.pid)
            try:
                evidence = _collect_evidence(
                    proc,
                    members,
                    heartbeat=heartbeat,
                    log=log,
                    evidence_dir=evidence_dir,
                    reason=reason,
                    elapsed=elapsed,
                )
            finally:
                survivors = _kill_tree(proc, members)  # closes the handles too
            if survivors:
                logger.warning("process tree of pid %s not gone after the kill: %s", proc.pid, survivors)
            return SupervisedExit(None, True, reason, elapsed, evidence)
    except BaseException:
        # Ctrl+C or an internal error: never leave the child tree behind.
        if proc.poll() is None:
            survivors = _kill_tree(proc, _descendants(proc.pid))
            if survivors:
                logger.warning("process tree of pid %s not gone after the kill: %s", proc.pid, survivors)
        else:
            _reap_tree(proc)  # the root already exited, but what it left behind may not have
        raise
    finally:
        # Every path closes the job.  Should run_suite itself crash or be killed, the OS closes this handle and
        # KILL_ON_JOB_CLOSE ends the tree all the same.
        _TREE.release(proc)


# --------------------------------------------------------------------------- jobs


@dataclass
class JobResult:
    spec: JobSpec
    status: str
    returncode: int | None
    culprit: str | None
    junit: Path | None
    log: Path
    heartbeat: Path
    evidence: list[Path]
    elapsed: float
    rerun: JobResult | None = None
    note: str = ""


def verdict(exit: SupervisedExit, events: list[dict], junit_exists: bool) -> tuple[str, str | None]:  # noqa: A002
    """Map a supervised exit to (status, culprit); ``"RC5"`` awaits the collect probe.

    A child that exits by itself with rc 1-4, no junit and a test still in flight never
    reached ``sessionfinish``.  rc 1 is the in-process faulthandler exit
    (``faulthandler_exit_on_timeout``, the common hang path: HUNG); rc 2-4 is a native
    abort that pytest's own ``faulthandler.enable()`` turned into rc 3 on Windows (CRASH).
    A real pytest rc 1-4 always writes the junit first, so those keep the plain mapping.
    """
    if exit.killed:
        return STATUS_HUNG, pending_culprit(events)
    rc = exit.returncode
    if rc == 0:
        return STATUS_OK, None
    if rc == 5:
        return _RC5, None
    if rc in (1, 2, 3, 4) and not junit_exists:
        in_flight = pending_culprit(events)
        if in_flight is not None:
            return (STATUS_HUNG if rc == 1 else STATUS_CRASH), in_flight
    if rc == 1:
        return STATUS_FAIL, None
    if rc in (2, 3, 4):  # interrupted / collection error, internal error, usage error
        return STATUS_COLLECT_ERROR, None
    # Negative (signal), > 5, or a large unsigned Windows status such as 0xC0000409.
    return STATUS_CRASH, pending_culprit(events)


def _parse_collected(text: str) -> int | None:
    count: int | None = None
    for line in text.splitlines():
        if "no tests collected" in line:
            count = 0
            continue
        match = _COLLECT_RE.search(line)
        if match:
            count = int(match.group(1))
    return count


RUN = "run"  # a job's pytest session
PROBE = "probe"  # its --collect-only count (rc 5 only)
_KIND_STEM = {RUN: "", PROBE: ".collect"}
_KIND_EXTRA: dict[str, tuple[str, ...]] = {RUN: (), PROBE: ("--collect-only", "-q")}
_PROBE_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class SuiteTiming:
    """The hang thresholds one child is supervised with; ``for_kind`` picks them per kind.

    ``main`` resolves one instance (``from_args``) and hands it to every job.  Layer order
    (test_default_timing_orders_the_two_hang_layers): pyproject's in-process
    faulthandler_timeout (540 s; its exit can deadlock) + one poll <= ``stall_seconds``
    (600 s, the external guaranteed kill) < CI's ``--file-ceiling`` (2400) <= the default
    ``file_ceiling`` (3600).  A lower ``--stall-seconds`` is a legitimate override (drills,
    the usage line), so ``main`` does not reject it.

    A collect-only probe never beats, so its stall and ceiling are both ``stall_seconds``
    (whatever ``file_ceiling`` and ``poll_seconds`` say) and it polls every
    ``_PROBE_POLL_SECONDS``.
    """

    stall_seconds: float = DEFAULT_STALL_SECONDS
    file_ceiling: float = DEFAULT_FILE_CEILING
    poll_seconds: float = DEFAULT_POLL_SECONDS

    @property
    def probe_timeout(self) -> float:
        return self.stall_seconds

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> SuiteTiming:
        """The one resolution: the stall and ceiling flags; the poll interval is not a flag."""
        return cls(stall_seconds=args.stall_seconds, file_ceiling=args.file_ceiling)

    def for_kind(self, kind: str) -> tuple[float, float, float]:
        """``(stall_seconds, file_ceiling, poll_seconds)`` for a child of *kind*."""
        if kind == PROBE:
            return self.probe_timeout, self.probe_timeout, _PROBE_POLL_SECONDS
        return self.stall_seconds, self.file_ceiling, self.poll_seconds


@dataclass(frozen=True)
class _ChildPaths:
    """Every file one supervised child owns; ``under`` is the one naming rule."""

    log: Path
    junit: Path
    heartbeat: Path
    evidence_dir: Path

    @classmethod
    def under(cls, out_dir: Path, stem: str) -> _ChildPaths:
        return cls(out_dir / f"{stem}.log", out_dir / f"{stem}.xml", out_dir / f"{stem}.heartbeat", out_dir / "evidence")


def _supervised_pytest(
    spec: JobSpec,
    kind: str,
    *,
    out_dir: Path,
    timing: SuiteTiming,
    paths: _ChildPaths | None = None,
    python: str = sys.executable,
    cwd: Path = REPO_ROOT,
    base_env: Mapping[str, str] | None = None,
    command_factory: Callable[..., list[str]] | None = None,
    cancel: threading.Event | None = None,
) -> tuple[SupervisedExit, _ChildPaths]:
    """One supervised child pytest of *kind* (RUN or PROBE) for *spec*.

    Owns the paths (*paths*, else ``<spec.name><kind stem>.*`` under *out_dir*), the
    removal of a stale junit and heartbeat, the clean child environment, the
    (stall, ceiling, poll) of *kind* and *cancel*.  ``command_factory`` defaults to
    the module's ``pytest_command`` looked up at call time.  A *cancel* already set raises
    JobCancelled before anything is touched or spawned; set later, ``supervise`` kills the
    tree at its next poll and raises it.
    """
    if kind not in _KIND_STEM:
        raise ValueError(f"unknown child kind {kind!r}")
    if cancel is not None and cancel.is_set():
        # A torn-down run starts nothing: no stale cleanup, no factory call, no child, no log.
        raise JobCancelled(f"{spec.name} {kind}: cancelled before start")
    if paths is None:
        paths = _ChildPaths.under(out_dir, spec.name + _KIND_STEM[kind])
    for stale in (paths.junit, paths.heartbeat):
        stale.unlink(missing_ok=True)
    env = clean_pytest_env(base_env)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env[HEARTBEAT_ENV] = str(paths.heartbeat)
    factory = command_factory if command_factory is not None else pytest_command
    cmd = factory(spec, paths.junit, python, list(_KIND_EXTRA[kind]))
    stall, ceiling, poll = timing.for_kind(kind)
    ex = supervise(
        cmd,
        cwd=cwd,
        env=env,
        heartbeat=paths.heartbeat,
        log=paths.log,
        stall_seconds=stall,
        file_ceiling=ceiling,
        poll_seconds=poll,
        evidence_dir=paths.evidence_dir,
        cancel=cancel,
    )
    return ex, paths


def collect_probe(
    spec: JobSpec,
    *,
    python: str,
    cwd: Path,
    env: Mapping[str, str] | None,
    log: Path,
    command_factory: Callable[..., list[str]] | None = None,
    timeout: float = DEFAULT_STALL_SECONDS,
    cancel: threading.Event | None = None,
) -> int:
    """Count the items *spec* selects with ``--collect-only -q``; -1 when unknown.

    A set *cancel* ends the probe's whole tree at its next poll and raises JobCancelled
    (never -1: -1 means the probe ran and its count is unknown); one already set raises
    before anything is spawned.

    Same files, ``-m``, passthrough and ``--deselect`` as the job (a rerun that
    deselected its only test exits 5 and must probe 0, not 1).  The probe runs
    supervised (a collection can hang too) and gets the same clean child
    environment as a run.  It writes exactly *log*; its junit and heartbeat sit
    beside it.  ``command_factory`` defaults to the module's ``pytest_command``
    looked up at call time.
    """
    ex, paths = _supervised_pytest(
        spec,
        PROBE,
        out_dir=log.parent,
        timing=SuiteTiming(timeout, timeout, _PROBE_POLL_SECONDS),
        paths=_ChildPaths(log, log.with_suffix(".xml"), log.with_suffix(".heartbeat"), log.parent / "evidence"),
        python=python,
        cwd=cwd,
        base_env=env,
        command_factory=command_factory,
        cancel=cancel,
    )
    if ex.killed or ex.returncode not in (0, 5):
        return -1
    try:
        text = paths.log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1
    count = _parse_collected(text)
    return -1 if count is None else count


def run_job(
    spec: JobSpec,
    out_dir: Path,
    *,
    python: str = sys.executable,
    cwd: Path = REPO_ROOT,
    stall_seconds: float,
    file_ceiling: float,
    rerun: bool = True,
    command_factory: Callable[..., list[str]] = pytest_command,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    base_env: Mapping[str, str] | None = None,
    cancel: threading.Event | None = None,
) -> JobResult:
    """Run one job under the supervisor and classify it (plan 1.1 steps 1-3)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ex, paths = _supervised_pytest(
        spec,
        RUN,
        out_dir=out_dir,
        timing=SuiteTiming(stall_seconds, file_ceiling, poll_seconds),
        python=python,
        cwd=cwd,
        base_env=base_env,
        command_factory=command_factory,
        cancel=cancel,
    )
    junit, log, heartbeat = paths.junit, paths.log, paths.heartbeat
    events = read_heartbeat(heartbeat)
    junit_exists = junit.exists()
    status, culprit = verdict(ex, events, junit_exists)
    result = JobResult(
        spec=spec,
        status=status,
        returncode=ex.returncode,
        culprit=culprit,
        junit=junit if junit_exists else None,
        log=log,
        heartbeat=heartbeat,
        evidence=list(ex.evidence),
        elapsed=ex.elapsed,
    )
    if ex.killed:
        result.note = f"killed on {ex.reason} after {ex.elapsed:.1f}s"
    elif status in (STATUS_HUNG, STATUS_CRASH):
        result.note = f"exited {ex.returncode} without a junit (in-process faulthandler exit or native abort?)"
        result.evidence = _save_heartbeat_and_tail(
            heartbeat,
            log,
            paths.evidence_dir,
            f"run_suite: child exited {ex.returncode} after {ex.elapsed:.1f}s with no junit; "
            f"test in flight: {culprit}\n",
        )

    if status == _RC5:
        n = collect_probe(
            spec,
            python=python,
            cwd=cwd,
            env=base_env,
            log=out_dir / f"{spec.name}.collect.log",
            command_factory=command_factory,
            timeout=stall_seconds,
            cancel=cancel,
        )
        if n == 0:
            result.status = STATUS_RC5_OK
            result.note = "exit 5 and collect-only selects no tests"
        else:
            result.status = STATUS_FAIL
            result.note = (
                f"exit 5 but collect-only selects {n} tests"
                if n > 0
                else "exit 5 and the collect-only probe failed or hung (see the .collect.log)"
            )
        return result

    if status not in (STATUS_HUNG, STATUS_CRASH):
        return result

    what = "hang" if status == STATUS_HUNG else "crash"
    if not events:
        result.note = _join(result.note, f"collection {what}: no test ever started; no rerun")
        return result
    if culprit is None:
        if ex.reason == "ceiling":
            # The job was still making progress; the kill landed between two tests, so
            # nothing is in flight to blame and nothing can be deselected.
            result.note = _join(
                result.note,
                "ceiling exceeded with no test in flight (a slow job, not a hang); "
                + ("junit kept" if junit_exists else "no junit was written, the job's results are lost")
                + "; no rerun",
            )
        else:
            result.note = _join(
                result.note,
                f"teardown {what}: every started test finished; junit kept"
                + ("" if junit_exists else " (none was written)")
                + "; no rerun",
            )
        return result
    if not rerun:
        result.note = _join(result.note, f"{what} in {culprit}; rerun disabled")
        return result

    result.note = _join(result.note, f"{what} in {culprit}; rerun once with --deselect")
    rerun_spec = dataclasses.replace(spec, name=f"{spec.name}-rerun", deselect=[*spec.deselect, culprit])
    result.rerun = run_job(
        rerun_spec,
        out_dir,
        python=python,
        cwd=cwd,
        stall_seconds=stall_seconds,
        file_ceiling=file_ceiling,
        rerun=False,
        command_factory=command_factory,
        poll_seconds=poll_seconds,
        base_env=base_env,
        cancel=cancel,
    )
    if result.rerun.status in (STATUS_HUNG, STATUS_CRASH):
        result.rerun.note = _join(result.rerun.note, "second hang/crash in the rerun; job stopped")
    return result


def _join(a: str, b: str) -> str:
    return f"{a}; {b}" if a else b


# --------------------------------------------------------------------------- aggregate


@dataclass
class Summary:
    passed: int
    failed: int
    skipped: int
    xfailed: int
    errors: int
    hung: int
    crashed: int
    rc5_ok: int
    elapsed: float


def _chain(results: list[JobResult]) -> list[JobResult]:
    """Every job followed by its rerun (a rerun never reruns: ``run_job(..., rerun=False)``)."""
    return [node for result in results for node in (result, result.rerun) if node is not None]


def _display_path(path: Path) -> str:
    """``path`` relative to the repo, POSIX-style; a path outside the repo prints as it is."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(path)


def _junit_suites(path: Path) -> tuple[list[ET.Element], str | None]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return [], f"unreadable junit {path.name}: {exc}"
    if root.tag == "testsuite":
        return [root], None
    return list(root.iter("testsuite")), None


def _synthetic_case(result: JobResult, kind: str, extra_note: str = "") -> ET.Element:
    target = result.culprit or result.spec.lane
    case = ET.Element(
        "testcase",
        {"classname": "run_suite", "name": f"{result.spec.name}::{target}", "time": f"{result.elapsed:.3f}"},
    )
    lines = [
        f"status: {result.status}",
        f"job: {result.spec.name} (lane {result.spec.lane})",
        f"culprit: {result.culprit or '-'}",
        f"returncode: {result.returncode}",
        f"note: {_join(result.note, extra_note) or '-'}",
        f"log: {_display_path(result.log)}",
        "evidence:",
        *[f"  {_display_path(p)}" for p in result.evidence],
        f"last heartbeat lines ({_display_path(result.heartbeat)}):",
        *[f"  {line}" for line in _tail_lines(result.heartbeat, _HEARTBEAT_TAIL_LINES)],
    ]
    message = f"{result.status}: {result.spec.name}" + (f" in {result.culprit}" if result.culprit else "")
    child = ET.SubElement(case, kind, {"message": message})
    child.text = "\n".join(lines)
    return case


def aggregate(results: list[JobResult], out_junit: Path, elapsed: float) -> Summary:
    """Merge every job (and rerun) junit into one ``<testsuites>`` and count it.

    HUNG/CRASH jobs add a synthetic ``<failure>`` testcase; a FAIL/COLLECT_ERROR job
    that contributed no failure or error of its own adds a synthetic ``<error>``, so
    a non-passing job can never produce a green exit code.
    """
    merged = ET.Element("testsuites")
    synthetic = ET.Element("testsuite", {"name": "run_suite"})
    chain = _chain(results)
    counts = Counter(result.status for result in chain)
    hung, crashed, rc5_ok = counts[STATUS_HUNG], counts[STATUS_CRASH], counts[STATUS_RC5_OK]
    for result in chain:
        own_bad = 0
        parse_note = ""
        if result.junit is not None and result.junit.exists():
            suites, problem = _junit_suites(result.junit)
            parse_note = problem or ""
            for suite in suites:
                merged.append(suite)
                own_bad += sum(
                    1 for tc in suite.iter("testcase") if tc.find("failure") is not None or tc.find("error") is not None
                )
        if result.status in (STATUS_HUNG, STATUS_CRASH):
            synthetic.append(_synthetic_case(result, "failure", parse_note))
        elif (result.status not in (STATUS_OK, STATUS_RC5_OK) and own_bad == 0) or parse_note:
            synthetic.append(_synthetic_case(result, "error", parse_note))
    if len(synthetic):
        merged.append(synthetic)

    passed = failed = errors = skipped = xfailed = 0
    for case in merged.iter("testcase"):
        if case.find("failure") is not None:
            failed += 1
        elif case.find("error") is not None:
            errors += 1
        else:
            skip = case.find("skipped")
            if skip is None:
                passed += 1
            elif skip.get("type") == "pytest.xfail":
                xfailed += 1
            else:
                skipped += 1
    merged.set("name", "run_suite")
    merged.set("tests", str(passed + failed + errors + skipped + xfailed))
    merged.set("failures", str(failed))
    merged.set("errors", str(errors))
    merged.set("skipped", str(skipped + xfailed))
    merged.set("time", f"{elapsed:.3f}")
    out_junit.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(merged).write(out_junit, encoding="utf-8", xml_declaration=True)
    return Summary(passed, failed, skipped, xfailed, errors, hung, crashed, rc5_ok, elapsed)


def summary_line(s: Summary) -> str:
    return (
        f"run_suite: {s.passed} passed, {s.failed} failed, {s.skipped} skipped, "
        f"{s.xfailed} xfailed, {s.errors} errors, {s.hung} hung, {s.crashed} crashed, "
        f"{s.rc5_ok} rc5-ok in {s.elapsed:.1f}s"
    )


def exit_code(s: Summary) -> int:
    return 1 if (s.failed or s.errors or s.hung or s.crashed) else 0


# --------------------------------------------------------------------------- CLI


def discover(test_dir: Path = REPO_ROOT / "test_scripts") -> list[Path]:
    return sorted(p for p in test_dir.glob("test_*.py") if p.is_file())


def build_jobs(
    files: list[Path], lane: str, marker_expr: str | None, passthrough: list[str]
) -> list[JobSpec]:
    """Qt files -> one job each (named after the stem); pure files -> one ``pure`` job."""
    qt_jobs: list[JobSpec] = []
    pure_files: list[Path] = []
    for path in files:
        try:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        if classify(source, _display_path(Path(path))) == "qt":
            qt_jobs.append(JobSpec(Path(path).stem, [path], "qt", marker_expr, list(passthrough)))
        else:
            pure_files.append(path)
    jobs: list[JobSpec] = []
    if lane in ("pure", "all") and pure_files:
        jobs.append(JobSpec("pure", pure_files, "pure", marker_expr, list(passthrough)))
    if lane in ("qt", "all"):
        jobs.extend(qt_jobs)
    return jobs


def _parse_args(argv: list[str]) -> argparse.Namespace:
    passthrough: list[str] = []
    if "--" in argv:
        idx = argv.index("--")
        argv, passthrough = argv[:idx], argv[idx + 1 :]
    parser = argparse.ArgumentParser(
        prog="run_suite.py",
        description="Run the test suite under a hang-proof supervisor (one child pytest per Qt file).",
    )
    parser.add_argument("-m", dest="marker_expr", metavar="EXPR", help="pytest -m marker expression")
    parser.add_argument("--junit", type=Path, help="merged junit path (default <out>/junit.xml)")
    parser.add_argument("--cov", action="store_true", help="coverage across all children, then xml + report")
    parser.add_argument(
        "--stall-seconds",
        type=float,
        default=DEFAULT_STALL_SECONDS,
        help="kill after this long without a heartbeat",
    )
    parser.add_argument(
        "--file-ceiling",
        type=float,
        default=DEFAULT_FILE_CEILING,
        help="wall-clock ceiling per job (a Qt job is one file; the pure job holds every pure file)",
    )
    parser.add_argument("--lane", choices=("qt", "pure", "all"), default="all")
    parser.add_argument("--files", nargs="+", type=Path, help="test files instead of discovering test_scripts/")
    parser.add_argument("--out", type=Path, help="output dir (default .run_suite/<UTC stamp>)")
    parser.add_argument("--no-rerun", action="store_true", help="do not rerun a hung/crashed job without its culprit")
    parser.add_argument("--durations", type=int, metavar="N", help="pass --durations=N to every child")
    parser.add_argument(
        "--parallel-lanes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run the pure job alongside the Qt lane (default; at most two children at once, Qt files "
        "stay serial); --no-parallel-lanes runs every job one after the other",
    )
    args = parser.parse_args(argv)
    args.passthrough = passthrough
    return args


def _job_label(spec: JobSpec) -> str:
    if spec.lane == "qt" and len(spec.files) == 1:
        return Path(spec.files[0]).name
    return f"{spec.name} ({len(spec.files)} files)"


def _job_env(spec: JobSpec, base_env: dict[str, str], cov: bool) -> dict[str, str]:
    """The child env for *spec*: with --cov, its own coverage data file.

    Two children appending to one .coverage at once (--parallel-lanes) corrupt it; a
    job's rerun gets the same env and so appends to the job's own file.
    """
    if not cov:
        return base_env
    return {**base_env, "COVERAGE_FILE": str(REPO_ROOT / f".coverage.{spec.name}")}


def _run_jobs(
    jobs: list[JobSpec],
    out_dir: Path,
    args: argparse.Namespace,
    base_env: dict[str, str],
    timing: SuiteTiming,
) -> list[JobResult]:
    """Run every job and return the results in job order.

    By default (``--no-parallel-lanes`` opts out) the pure job runs on a second
    thread while the Qt files run one at a time on this one, so at most two children
    exist at once and never two Qt children (plans/CI-faster.md).  Each job still has
    its own supervisor, heartbeat, junit and rerun.
    """
    lane_totals = {lane: sum(1 for j in jobs if j.lane == lane) for lane in ("pure", "qt")}
    lane_seen = {"pure": 0, "qt": 0}
    prefixes: list[str] = []
    for spec in jobs:
        lane_seen[spec.lane] += 1
        prefixes.append(f"[{spec.lane} {lane_seen[spec.lane]}/{lane_totals[spec.lane]}] {_job_label(spec)}")
    parallel = args.parallel_lanes and 0 < lane_totals["pure"] < len(jobs)
    print_lock = threading.Lock()
    cancel = threading.Event()  # set when this thread raises; the pure job's supervisor kills its child
    results: dict[int, JobResult] = {}

    def run_one(pos: int) -> None:
        spec = jobs[pos]
        if not parallel:
            print(f"{prefixes[pos]} ...", end=" ", flush=True)
        result = run_job(
            spec,
            out_dir,
            stall_seconds=timing.stall_seconds,
            file_ceiling=timing.file_ceiling,
            poll_seconds=timing.poll_seconds,
            rerun=not args.no_rerun,
            base_env=_job_env(spec, base_env, args.cov),
            cancel=cancel,
        )
        results[pos] = result
        extra = f" ({result.note})" if result.note else ""
        lines = [f"{result.status} {result.elapsed:.1f}s{extra}"]
        for node in _chain([result])[1:]:
            lines.append(f"    rerun without {node.spec.deselect[-1]} ... {node.status} {node.elapsed:.1f}s")
        if parallel:  # one whole line per job, so the two lanes never interleave mid-line
            lines[0] = f"{prefixes[pos]} ... {lines[0]}"
        with print_lock:
            for line in lines:
                print(line, flush=True)

    background = [pos for pos, spec in enumerate(jobs) if parallel and spec.lane == "pure"]
    errors: list[BaseException] = []

    def run_background() -> None:
        try:
            for pos in background:
                run_one(pos)
        except BaseException as exc:  # re-raised on the main thread after join
            errors.append(exc)

    worker: threading.Thread | None = None
    if background:
        print("run_suite: the pure job runs alongside the qt lane (--parallel-lanes)", flush=True)
        worker = threading.Thread(target=run_background, name="run_suite-pure-lane")
        worker.start()
    try:
        for pos in range(len(jobs)):
            if pos not in background:
                run_one(pos)
    except BaseException:
        cancel.set()  # Ctrl+C or an error here: stop the pure job too (its error, if any, is dropped)
        raise
    finally:
        if worker is not None:
            worker.join()  # never leave a supervised child running behind an exception
    if errors:
        raise errors[0]
    return [results[pos] for pos in range(len(jobs))]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    timing = SuiteTiming.from_args(args)  # the one resolution; nothing below reads args.stall_seconds/file_ceiling
    started = time.monotonic()
    out_dir: Path = args.out or REPO_ROOT / ".run_suite" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_junit: Path = (args.junit or out_dir / "junit.xml").resolve()

    passthrough: list[str] = []
    if args.durations is not None:
        passthrough.append(f"--durations={args.durations}")
    if args.cov:
        # Every job writes its own .coverage.<job> (see _job_env) and `coverage combine`
        # merges them at the end, so stale files from an earlier run must go first.
        for stale in (REPO_ROOT / ".coverage", *REPO_ROOT.glob(".coverage.*")):
            if stale.is_file():
                stale.unlink()
        # --cov-fail-under=0: pytest-cov otherwise copies pyproject's fail_under into every
        # child and fails each one on its partial coverage; the final `coverage report` gates.
        passthrough += ["--cov", "--cov-append", "--cov-report=", "--cov-fail-under=0"]
    passthrough += args.passthrough

    files = [p.resolve() for p in args.files] if args.files else discover()
    missing = [p for p in files if not p.is_file()]
    if missing:
        print(f"run_suite: no such test file: {', '.join(str(p) for p in missing)}", flush=True)
        return 1
    jobs = build_jobs(files, args.lane, args.marker_expr, passthrough)
    if not jobs:
        print("run_suite: no jobs selected (check --lane / --files)", flush=True)
        return 1

    base_env = clean_pytest_env()  # warns once here; run_job's own pass is then a no-op
    print(
        f"run_suite: {len(jobs)} jobs -> {_display_path(out_dir)} "
        f"(stall {timing.stall_seconds:g} s, ceiling {timing.file_ceiling:g} s)",
        flush=True,
    )
    results = _run_jobs(jobs, out_dir, args, base_env, timing)

    summary = aggregate(results, out_junit, time.monotonic() - started)
    rc = exit_code(summary)
    if args.cov:
        python = sys.executable
        subprocess.run([python, "-m", "coverage", "combine"], cwd=str(REPO_ROOT), check=False)
        subprocess.run([python, "-m", "coverage", "xml"], cwd=str(REPO_ROOT), check=False)
        report = subprocess.run([python, "-m", "coverage", "report"], cwd=str(REPO_ROOT), check=False)
        if report.returncode != 0:
            print(f"run_suite: coverage report exited {report.returncode}", flush=True)
            rc = 1
    print(f"run_suite: merged junit {_display_path(out_junit)}", flush=True)
    print(summary_line(summary), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
