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
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
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
    extra: list[str] = (),  # type: ignore[assignment]
) -> list[str]:
    """The child pytest command line for *spec* (layout pinned by test_run_suite.py)."""
    cmd = [python, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider", "--junitxml", str(junit)]
    if spec.marker_expr:
        cmd += ["-m", spec.marker_expr]
    for nodeid in spec.deselect:
        cmd += ["--deselect", nodeid]
    cmd += [str(f) for f in spec.files]
    cmd += list(spec.passthrough)
    cmd += list(extra)
    return cmd


@dataclass
class SupervisedExit:
    returncode: int | None
    killed: bool
    reason: str | None
    elapsed: float
    evidence: list[Path] = field(default_factory=list)


# --------------------------------------------------------------------------- process tree


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

    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _WAIT_TIMEOUT = 0x00000102


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


def _descendants(root_pid: int) -> list[_TreeMember]:
    try:
        if sys.platform == "win32":
            return _win_descendants(root_pid)
        return _posix_descendants(root_pid)
    except Exception:  # noqa: BLE001 - evidence and verification are best-effort
        logger.warning("could not enumerate the process tree of pid %s", root_pid, exc_info=True)
        return []


def _close_members(members: list[_TreeMember]) -> None:
    if sys.platform != "win32":
        return
    for member in members:
        if member.handle:
            _k32.CloseHandle(member.handle)
            member.handle = None


def _kill_tree(proc: subprocess.Popen, members: list[_TreeMember]) -> list[int]:
    """Kill *proc* and its whole tree; return the pids still alive after the bound.

    Only processes we spawned are touched: *proc* itself and the descendants that
    were enumerated (with pinned handles on Windows) while *proc* was alive.

    Windows terminates by handle only, never by a bare pid: every member passed the
    creation-time check in ``_win_descendants``, so a stale parent pid that Windows
    reused for an unrelated process can never be reached (``taskkill /T`` walks bare
    parent pids and could).  A fresh enumeration right before the kill catches
    anything the tree spawned since the evidence pass; descendants are ended before
    the root so the venv launcher never leaves its real python child orphaned.
    """
    extra: list[_TreeMember] = []
    targets = list(members)
    if sys.platform == "win32":
        known = {member.pid for member in members}
        extra = [member for member in _descendants(proc.pid) if member.pid not in known]
        targets.extend(extra)
        for member in targets:
            if member.handle:
                _k32.TerminateProcess(member.handle, 1)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True: pgid == pid
        except OSError:
            pass
    try:
        proc.kill()
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
    if sys.platform == "win32":
        try:
            for member in targets:
                if not member.handle:
                    continue
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if _k32.WaitForSingleObject(member.handle, remaining_ms) == _WAIT_TIMEOUT:
                    # Still alive (TerminateProcess is asynchronous): one more try.
                    _k32.TerminateProcess(member.handle, 1)
                    if _k32.WaitForSingleObject(member.handle, 5000) == _WAIT_TIMEOUT:
                        survivors.append(member.pid)
        finally:
            _close_members(extra)
    else:
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except OSError:
                break
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                break
            time.sleep(0.1)
        else:
            survivors.append(-proc.pid)  # the process group still has members
    return survivors


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
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cannot create evidence dir %s", evidence_dir, exc_info=True)
        return evidence
    stem = log.stem
    header = (
        f"run_suite: {reason} after {elapsed:.1f}s, child pid {proc.pid}, "
        f"tree {[(m.pid, m.name) for m in members]}\n"
    )

    pyspy = shutil.which("py-spy")
    if pyspy:
        targets = [proc.pid] + [
            m.pid for m in members if sys.platform != "win32" or "python" in m.name.lower()
        ]
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


def _save_heartbeat_and_tail(heartbeat: Path, log: Path, evidence_dir: Path, header: str) -> list[Path]:
    """Copy the heartbeat and write the log tail into *evidence_dir*; never raises."""
    evidence: list[Path] = []
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("cannot create evidence dir %s", evidence_dir, exc_info=True)
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
    poll_seconds: float = 5.0,
    evidence_dir: Path | None = None,
) -> SupervisedExit:
    """Run *cmd* to completion, or kill its whole tree on a stall or the ceiling.

    Progress is any change of the heartbeat file's (size, mtime), read fresh by
    ``os.stat`` every poll; before the first beat the process start counts.
    Evidence is collected before the kill; the kill is verified within a bound.
    """
    if evidence_dir is None:
        evidence_dir = log.parent / "evidence"
    log.parent.mkdir(parents=True, exist_ok=True)
    popen_kw: dict = {}
    if sys.platform != "win32":
        popen_kw["start_new_session"] = True
    with open(log, "wb") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **popen_kw,
        )
    start = time.monotonic()
    last_progress = start
    prev_poll = start
    last_sig: tuple[int, int] | None = None
    reason: str | None = None
    try:
        while True:
            try:
                rc = proc.wait(timeout=poll_seconds)
                return SupervisedExit(rc, False, None, time.monotonic() - start, [])
            except subprocess.TimeoutExpired:
                pass
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
                survivors = _kill_tree(proc, members)
                _close_members(members)
            if survivors:
                logger.warning("process tree of pid %s not gone after the kill: %s", proc.pid, survivors)
            return SupervisedExit(None, True, reason, elapsed, evidence)
    except BaseException:
        # Ctrl+C or an internal error: never leave the child tree behind.
        if proc.poll() is None:
            members = _descendants(proc.pid)
            try:
                _kill_tree(proc, members)
            finally:
                _close_members(members)
        raise


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


def collect_probe(
    spec: JobSpec,
    *,
    python: str,
    cwd: Path,
    env: dict[str, str],
    log: Path,
    command_factory: Callable[..., list[str]] | None = None,
    timeout: float = 600.0,
) -> int:
    """Count the items *spec* selects with ``--collect-only -q``; -1 when unknown.

    Same files, ``-m``, passthrough and ``--deselect`` as the job (a rerun that
    deselected its only test exits 5 and must probe 0, not 1).  The probe runs
    supervised (a collection can hang too).  ``command_factory`` defaults to the
    module's ``pytest_command`` looked up at call time.
    """
    factory = command_factory if command_factory is not None else pytest_command
    probe_spec = dataclasses.replace(spec, deselect=list(spec.deselect))
    junit = log.with_suffix(".xml")
    heartbeat = log.with_suffix(".heartbeat")
    try:
        heartbeat.unlink()
    except OSError:
        pass
    cmd = factory(probe_spec, junit, python, ["--collect-only", "-q"])
    probe_env = dict(env)
    probe_env[HEARTBEAT_ENV] = str(heartbeat)
    ex = supervise(
        cmd,
        cwd=cwd,
        env=probe_env,
        heartbeat=heartbeat,
        log=log,
        stall_seconds=timeout,
        file_ceiling=timeout,
        poll_seconds=0.2,
        evidence_dir=log.parent / "evidence",
    )
    if ex.killed or ex.returncode not in (0, 5):
        return -1
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1
    count = _parse_collected(text)
    return -1 if count is None else count


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


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
    poll_seconds: float = 5.0,
    base_env: Mapping[str, str] | None = None,
) -> JobResult:
    """Run one job under the supervisor and classify it (plan 1.1 steps 1-3)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / f"{spec.name}.xml"
    log = out_dir / f"{spec.name}.log"
    heartbeat = out_dir / f"{spec.name}.heartbeat"
    for stale in (junit, heartbeat):
        _unlink(stale)

    env = clean_pytest_env(base_env)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env[HEARTBEAT_ENV] = str(heartbeat)

    cmd = command_factory(spec, junit, python, [])
    ex = supervise(
        cmd,
        cwd=cwd,
        env=env,
        heartbeat=heartbeat,
        log=log,
        stall_seconds=stall_seconds,
        file_ceiling=file_ceiling,
        poll_seconds=poll_seconds,
        evidence_dir=out_dir / "evidence",
    )
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
            out_dir / "evidence",
            f"run_suite: child exited {ex.returncode} after {ex.elapsed:.1f}s with no junit; "
            f"test in flight: {culprit}\n",
        )

    if status == _RC5:
        n = collect_probe(
            spec,
            python=python,
            cwd=cwd,
            env=env,
            log=out_dir / f"{spec.name}.collect.log",
            command_factory=command_factory,
            timeout=stall_seconds,
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
    rerun_spec = dataclasses.replace(
        spec,
        name=f"{spec.name}-rerun",
        files=list(spec.files),
        passthrough=list(spec.passthrough),
        deselect=[*spec.deselect, culprit],
    )
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
    flat: list[JobResult] = []
    for result in results:
        node: JobResult | None = result
        while node is not None:
            flat.append(node)
            node = node.rerun
    return flat


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
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
    hung = crashed = rc5_ok = 0
    for result in _chain(results):
        if result.status == STATUS_HUNG:
            hung += 1
        elif result.status == STATUS_CRASH:
            crashed += 1
        elif result.status == STATUS_RC5_OK:
            rc5_ok += 1
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
        elif result.status not in (STATUS_OK, STATUS_RC5_OK) and own_bad == 0:
            synthetic.append(_synthetic_case(result, "error", parse_note))
        elif parse_note:
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


def _rel_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


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
        if classify(source, _rel_posix(Path(path))) == "qt":
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
    parser.add_argument("--stall-seconds", type=float, default=600.0, help="kill after this long without a heartbeat")
    parser.add_argument(
        "--file-ceiling",
        type=float,
        default=3600.0,
        help="wall-clock ceiling per job (a Qt job is one file; the pure job holds every pure file)",
    )
    parser.add_argument("--lane", choices=("qt", "pure", "all"), default="all")
    parser.add_argument("--files", nargs="+", type=Path, help="test files instead of discovering test_scripts/")
    parser.add_argument("--out", type=Path, help="output dir (default .run_suite/<UTC stamp>)")
    parser.add_argument("--no-rerun", action="store_true", help="do not rerun a hung/crashed job without its culprit")
    parser.add_argument("--durations", type=int, metavar="N", help="pass --durations=N to every child")
    args = parser.parse_args(argv)
    args.passthrough = passthrough
    return args


def _job_label(spec: JobSpec) -> str:
    if spec.lane == "qt" and len(spec.files) == 1:
        return Path(spec.files[0]).name
    return f"{spec.name} ({len(spec.files)} files)"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    started = time.monotonic()
    out_dir: Path = args.out or REPO_ROOT / ".run_suite" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_junit: Path = (args.junit or out_dir / "junit.xml").resolve()

    passthrough: list[str] = []
    if args.durations is not None:
        passthrough.append(f"--durations={args.durations}")
    if args.cov:
        coverage_file = REPO_ROOT / ".coverage"
        if coverage_file.exists():
            coverage_file.unlink()
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
    lane_totals = {lane: sum(1 for j in jobs if j.lane == lane) for lane in ("pure", "qt")}
    lane_seen = {"pure": 0, "qt": 0}
    print(f"run_suite: {len(jobs)} jobs -> {_display_path(out_dir)}", flush=True)
    results: list[JobResult] = []
    for spec in jobs:
        lane_seen[spec.lane] += 1
        prefix = f"[{spec.lane} {lane_seen[spec.lane]}/{lane_totals[spec.lane]}] {_job_label(spec)}"
        print(f"{prefix} ...", end=" ", flush=True)
        result = run_job(
            spec,
            out_dir,
            stall_seconds=args.stall_seconds,
            file_ceiling=args.file_ceiling,
            rerun=not args.no_rerun,
            base_env=base_env,
        )
        results.append(result)
        extra = f" ({result.note})" if result.note else ""
        print(f"{result.status} {result.elapsed:.1f}s{extra}", flush=True)
        node = result.rerun
        while node is not None:
            print(f"    rerun without {node.spec.deselect[-1]} ... {node.status} {node.elapsed:.1f}s", flush=True)
            node = node.rerun

    summary = aggregate(results, out_junit, time.monotonic() - started)
    rc = exit_code(summary)
    if args.cov:
        python = sys.executable
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
