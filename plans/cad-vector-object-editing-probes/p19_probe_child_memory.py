"""Card A3 decision rule: peak working set of the ``object-probe`` child.

Starts the real child (``src.render_worker.launch.child_launch("object-probe")``) on each stall
fixture of ``test_scripts/test_gui_stall.py`` and, when present, on page 1 of the owner's sample
``test_files/cad_vector/before.pdf``, and reads the child's peak working set.

Card A3b: reports peak working set, peak private commit, run time and the answer status under
``object_probe_memory_limit(read_system_memory())`` (the H24 cap, applied by the child itself).

Run: ``.venv\\Scripts\\python.exe plans/cad-vector-object-editing-probes/p19_probe_child_memory.py``
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402

from model import table_objects  # noqa: E402
from src.render_worker.launch import child_launch  # noqa: E402

MIB = 1024 * 1024


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_memory(popen: subprocess.Popen) -> tuple[int, int]:
    """(peak working set, peak private commit) in bytes."""
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        wintypes.HANDLE(int(popen._handle)), ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.PeakWorkingSetSize), int(counters.PeakPagefileUsage)


def run_child(payload: bytes) -> tuple[int, int, float, str]:
    # A venv's python.exe is a redirector: its handle would read the launcher, not the worker.
    # Run the real interpreter and hand it the venv's packages.
    program, args = child_launch("object-probe", python_executable=getattr(sys, "_base_executable", sys.executable))
    site = next(p for p in sys.path if p.endswith("site-packages"))
    env = {**os.environ, "PYTHONPATH": site}
    from src.render_worker.admission import object_probe_memory_limit
    from src.render_worker.memory import read_system_memory

    limit = object_probe_memory_limit(read_system_memory())
    if limit is None:
        raise RuntimeError("no memory headroom for the child on this machine")
    header = json.dumps({"v": 2, "kind": "tables", "sizes": [len(payload)], "mem": limit}).encode("utf-8")
    started = time.perf_counter()
    proc = subprocess.Popen(
        [program, *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO_ROOT, env=env,
    )
    out, _ = proc.communicate(header + b"\n" + payload)
    seconds = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"child exited {proc.returncode}")
    status = next(
        (json.loads(line).get("status", "?") for line in out.splitlines() if line.startswith(b'{"v"')), "no answer"
    )
    working_set, commit = _peak_memory(proc)
    return working_set, commit, seconds, status


def main() -> None:
    from test_scripts import test_gui_stall as stall

    results: dict[str, tuple[int, int, float, str]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, build in stall.BUILDERS.items():
            path = Path(tmp) / f"{name}.pdf"
            build(path)
            with fitz.open(path) as doc:
                results[name] = run_child(table_objects.scratch_page_bytes(doc, 1))
    sample = REPO_ROOT / "test_files" / "cad_vector" / "before.pdf"
    if sample.exists():
        with fitz.open(sample) as doc:
            results["sample"] = run_child(table_objects.scratch_page_bytes(doc, 1))
    for name, (peak, commit, seconds, status) in results.items():
        print(
            f"{name:8s} peak working set {peak / MIB:8.1f} MiB   peak commit {commit / MIB:8.1f} MiB"
            f"   child run time {seconds:6.1f} s   status {status}"
        )
    maximum = max(peak for peak, _, _, _ in results.values())
    print(f"maximum peak working set {maximum / MIB:.1f} MiB (card A3b: the cap is H24, not a charge)")


if __name__ == "__main__":
    main()
