"""Card B3 gate: scanner G through the product path (the H21 child) on the CAD sample, then the decision rule.

Entry: ``VectorEditCoordinator.ensure_index`` with the default child path: ``PDFModel.vector_page_source``
on the GUI thread, the scan in the one-shot ``vector-scan`` child (``ObjectProbeRunner``), the index
file loaded on a worker thread, ``index_done`` delivered.  Three runs, each in a fresh interpreter, COLD:
neither ``numpy`` nor ``model.vector_paths.scan`` may be imported when the baseline is taken (the run
fails otherwise; both flags are recorded).  Per run: wall time from the gesture to ``index_done``
(array load included), the longest heartbeat gap of the H5 harness (0 ms timer; the synchronous
``vector_page_source`` call is inside the window, the file load is on a worker and is reported as
``load_seconds``), and the memory of BOTH processes.  A run only counts when the CHILD's file says which
scanner produced it (``scanner`` / ``accelerated``, expected F / accelerated since card B4: the sample is above the 1 MiB routing size) and holds exactly
``EXPECTED_PATHS`` paths (D24: a plausible number from some other callable is not evidence).

Memory, two different calculations, never mixed:
- GUI process "current baseline" = ``WorkingSetSize`` / ``PagefileUsage`` just before the gesture;
  ``peak_ws_minus_current_ws`` and ``peak_commit_minus_current_commit`` subtract that current value from
  the lifetime peak after the gesture.  ``peak_after_minus_peak_before_*`` is the growth of the
  high-water mark, reported separately and not used by the rule.
- Child process = its own lifetime peaks (it starts from nothing).  ``sum_*`` adds the GUI delta and the
  child peak (conservative: the two peaks do not coincide in time).  The rule's memory figure is
  ``sum_ws`` (working set, as the earlier rounds); the commit sum is printed and checked separately.

"400 MB" of the card is read as 400 MiB (419,430,400 bytes); the strict decimal reading (381.47 MiB) is
evaluated too and printed whenever it would change the rule.  The venv ``python.exe`` is a redirector
whose handle reads the launcher, not the worker (p19), so the probe launches the real interpreter with
the venv's packages on ``PYTHONPATH`` (the same program the product launches, one process deeper in a
venv).  The callables of the GUI process are captured at run time (H12) with ``sys.setprofile``
installed after the baseline; the child's callables are the ones the protocol tests run.

The sample is a local file: set ``PDF_EDITOR_CAD_SAMPLE``, else ``test_files/cad_vector/before.pdf``
(gitignored).  Run: ``.venv\\Scripts\\python.exe plans/cad-vector-object-editing-probes/p20_scan_gate.py
[out.json]``.  Windows only (process memory counters).
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = Path(os.environ.get("PDF_EDITOR_CAD_SAMPLE") or REPO_ROOT / "test_files" / "cad_vector" / "before.pdf")
MIB = 1024 * 1024
RUNS = 3
LIMIT_SECONDS = 4.0  # card B3 rule 1 and 3
LIMIT_GAP_MS = 100.0  # H5, rule 2
LIMIT_MEMORY_MIB = 400.0  # "400 MB" read as 400 MiB
LIMIT_MEMORY_DECIMAL_MIB = 400_000_000 / MIB  # the strict decimal reading, evaluated alongside
#: the sample's path count (a successful run must return exactly this) and the scanner the run must report
EXPECTED_PATHS = 414_510
EXPECTED_SCANNER = "F"
EXPECTED_ACCELERATED = True
#: GUI-thread callables profiled by ``sys.setprofile``.  The index file is read and validated on a worker
#: thread (``coordinator.last_load_seconds``), where this thread-local profiler cannot see it.
_WATCHED = ("vector_page_source", "ensure_index", "_start_child", "_finish_child", "_start_load")


def _counters(handle) -> tuple[int, int, int, int]:
    """(working set, peak working set, current commit, peak commit) of the process behind ``handle``, bytes."""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
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

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(handle), ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return (
        int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize),
        int(counters.PagefileUsage), int(counters.PeakPagefileUsage),
    )


def _self_counters() -> tuple[int, int, int, int]:
    return _counters(-1)  # the pseudo handle of the current process


def _open_process(pid: int):
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError(f"OpenProcess failed for pid {pid}")
    return handle


def _child() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(REPO_ROOT))
    site = next(p for p in sys.path if p.endswith("site-packages"))
    os.environ["PYTHONPATH"] = site  # for the real-interpreter child (see the module docstring)
    from types import SimpleNamespace

    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    import src.render_worker.launch as launch
    from controller.object_probe_runner import ObjectProbeRunner
    from controller.vector_edit_coordinator import VectorEditCoordinator
    from model.pdf_model import PDFModel
    from test_scripts.gui_stall_probe import run_gesture

    base = getattr(sys, "_base_executable", sys.executable)
    original_launch = launch.child_launch
    launch.child_launch = lambda kind, extra_args=None, **kw: original_launch(kind, extra_args, python_executable=base)

    app = QApplication.instance() or QApplication([])
    model = PDFModel()
    model.open_pdf(str(SAMPLE))

    child_info: dict = {}

    def factory(parent):
        process = QProcess(parent)

        def on_started() -> None:
            child_info["pid"] = int(process.processId())
            child_info["handle"] = _open_process(child_info["pid"])

        def on_finished(code: int, _status=None) -> None:
            child_info["exit_code"] = int(code)
            if "handle" in child_info:
                ws, peak_ws, commit, peak_commit = _counters(child_info["handle"])
                child_info["counters"] = (ws, peak_ws, commit, peak_commit)

        process.started.connect(on_started)
        process.finished.connect(on_finished)
        return process

    runner = ObjectProbeRunner(app, process_factory=factory)
    coordinator = VectorEditCoordinator(SimpleNamespace(model=model), runner=runner)
    result: dict = {}
    coordinator.index_done.connect(lambda page, index: result.update(status="done", at=time.perf_counter(), index=index))
    coordinator.index_refused.connect(lambda page, code: result.update(status=f"refused:{code}", at=time.perf_counter()))

    # Cold entry is a checked outcome, not an assumption (the D24 class).
    ws_before, peak_ws_before, commit_before, peak_commit_before = _self_counters()
    cold = {"numpy_loaded": "numpy" in sys.modules, "scan_loaded": "model.vector_paths.scan" in sys.modules,
            "transport_loaded": "model.vector_paths.transport" in sys.modules}

    called: dict[str, float] = {}
    open_frames: dict[int, tuple[str, float]] = {}

    def profiler(frame, event, arg):
        if event == "call":
            code = frame.f_code
            if code.co_name in _WATCHED and code.co_filename.startswith(str(REPO_ROOT)):
                open_frames[id(frame)] = (f"{Path(code.co_filename).relative_to(REPO_ROOT).as_posix()}:{code.co_qualname}",
                                          time.perf_counter())
        elif event == "return":
            entry = open_frames.pop(id(frame), None)
            if entry is not None:
                called[entry[0]] = called.get(entry[0], 0.0) + time.perf_counter() - entry[1]

    started = {}

    def gesture() -> None:
        started["t"] = time.perf_counter()
        sys.setprofile(profiler)
        coordinator.ensure_index(1)

    try:
        gap_ms, finished = run_gesture(app, gesture, lambda: "status" in result)
    finally:
        sys.setprofile(None)
    ws_after, peak_ws_after, commit_after, peak_commit_after = _self_counters()
    measured_calls = dict(called)
    index = result.get("index")
    child = child_info.get("counters")
    decoded_mib = sum(len(s) for s in model.vector_page_source(1)[0]) / MIB  # after the measurement
    gui_ws_delta = (peak_ws_after - ws_before) / MIB
    gui_commit_delta = (peak_commit_after - commit_before) / MIB
    out = {
        "status": result.get("status", "unfinished"),
        "finished": finished,
        "cold": cold,
        "wall_s": (result["at"] - started["t"]) if "at" in result else None,
        "gap_ms": gap_ms,
        "child_exit_code": child_info.get("exit_code"),
        "gui_ws_before_current_mib": ws_before / MIB,
        "gui_commit_before_current_mib": commit_before / MIB,
        "gui_peak_ws_before_mib": peak_ws_before / MIB,
        "gui_peak_commit_before_mib": peak_commit_before / MIB,
        "gui_peak_ws_after_mib": peak_ws_after / MIB,
        "gui_peak_commit_after_mib": peak_commit_after / MIB,
        "gui_ws_after_current_mib": ws_after / MIB,
        "peak_ws_minus_current_ws_mib": gui_ws_delta,
        "peak_commit_minus_current_commit_mib": gui_commit_delta,
        "peak_after_minus_peak_before_ws_mib": (peak_ws_after - peak_ws_before) / MIB,
        "peak_after_minus_peak_before_commit_mib": (peak_commit_after - peak_commit_before) / MIB,
        "child_peak_ws_mib": child[1] / MIB if child else None,
        "child_peak_commit_mib": child[3] / MIB if child else None,
        "sum_ws_mib": (gui_ws_delta + child[1] / MIB) if child else None,
        "sum_commit_mib": (gui_commit_delta + child[3] / MIB) if child else None,
        "paths": int(len(index.paths)) if index is not None else None,
        # what the CHILD recorded in the file it wrote (not the GUI interpreter's own scanner module)
        "scanner": getattr(index, "scanner", None) if index is not None else None,
        "accelerated": getattr(index, "accelerated", None) if index is not None else None,
        "load_seconds": coordinator.last_load_seconds,
        "index_nbytes_mib": index.nbytes / MIB if index is not None else None,
        "decoded_mib": decoded_mib,
        "callables_seconds": measured_calls,
    }
    print("P20_RESULT " + json.dumps(out))


def apply_rule(median_s: float, gap_ms: float, memory_mib: float, limit_mib: float = LIMIT_MEMORY_MIB) -> tuple[int, str]:
    """The decision rule of card B3 on a run THROUGH THE CHILD (H21 already applied: "measure again; then
    rule 1 or 3"), so rule 2 cannot be the answer again: time or memory over the limit is rule 3, else a
    gap over 100 ms keeps rule 1 from applying and is reported as unresolved (0), else rule 1."""
    if median_s > LIMIT_SECONDS or memory_mib > limit_mib:
        return 3, "median > 4.0 s or memory > 400 MB: card B4 (accelerator F)"
    if gap_ms > LIMIT_GAP_MS:
        return 0, "gap > 100 ms with the scan already in the child: neither rule 1 nor 3 applies; report"
    return 1, "median <= 4.0 s, gap <= 100 ms, memory <= 400 MB: ship G; skip B4"


def _run_failure(number: int, run: dict) -> str | None:
    if run["status"] != "done" or not run["finished"]:
        return f"run {number}: status {run['status']}, finished {run['finished']}"
    if run["child_exit_code"] != 0:
        return f"run {number}: the vector-scan child exited with {run['child_exit_code']}"
    cold = run["cold"]
    if cold["numpy_loaded"] or cold["scan_loaded"] or cold["transport_loaded"]:
        return f"run {number}: not a cold entry ({cold})"
    if run["sum_ws_mib"] is None:
        return f"run {number}: the child's memory was not read"
    if run["scanner"] != EXPECTED_SCANNER or run["accelerated"] is not EXPECTED_ACCELERATED:
        return (f"run {number}: the child reports scanner {run['scanner']!r} accelerated {run['accelerated']!r}, "
                f"expected {EXPECTED_SCANNER!r} accelerated {EXPECTED_ACCELERATED!r}")
    if run["paths"] != EXPECTED_PATHS:
        return f"run {number}: {run['paths']} paths, expected {EXPECTED_PATHS}"
    return None


def main() -> int:
    if not SAMPLE.exists():
        print(f"sample not found: set PDF_EDITOR_CAD_SAMPLE (tried {SAMPLE.name})")
        return 2
    runs = []
    for number in range(RUNS):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child"],
            capture_output=True, text=True, timeout=900, cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:  # even when a result line was printed
            print(f"run {number + 1} failed (exit {proc.returncode}):\n{proc.stderr[-800:]}")
            return 1
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("P20_RESULT ")]
        if not lines:
            print(f"run {number + 1} printed no result:\n{proc.stderr[-800:]}")
            return 1
        runs.append(json.loads(lines[-1][len("P20_RESULT "):]))
        r = runs[-1]
        problem = _run_failure(number + 1, r)
        if problem:
            print(problem)
            return 1
        print(f"run {number + 1}: {r['status']} wall {r['wall_s']:.2f} s gap {r['gap_ms']:.1f} ms "
              f"gui ws +{r['peak_ws_minus_current_ws_mib']:.0f} MiB child ws {r['child_peak_ws_mib']:.0f} MiB "
              f"sum ws {r['sum_ws_mib']:.0f} MiB sum commit {r['sum_commit_mib']:.0f} MiB paths {r['paths']} "
              f"scanner {r['scanner']} accelerated {r['accelerated']} load {r['load_seconds']:.3f} s")
    median_s = statistics.median(r["wall_s"] for r in runs)
    gap_ms = max(r["gap_ms"] for r in runs)
    memory_mib = max(r["sum_ws_mib"] for r in runs)
    commit_mib = max(r["sum_commit_mib"] for r in runs)
    rule, text = apply_rule(median_s, gap_ms, memory_mib)
    rule_decimal = apply_rule(median_s, gap_ms, memory_mib, LIMIT_MEMORY_DECIMAL_MIB)[0]
    rule_commit = apply_rule(median_s, gap_ms, commit_mib)[0]
    summary = {"scanner": runs[0]["scanner"], "accelerated": runs[0]["accelerated"], "paths": runs[0]["paths"],
               "median_wall_s": median_s, "max_gap_ms": gap_ms, "max_sum_ws_mib": memory_mib,
               "max_sum_commit_mib": commit_mib, "rule": rule, "rule_text": text,
               "rule_if_400_mb_is_decimal": rule_decimal, "rule_if_commit_sum_is_the_figure": rule_commit,
               "runs": runs}
    print(json.dumps({k: v for k, v in summary.items() if k != "runs"}, indent=1))
    print("callables (H12, GUI process):", sorted(runs[0]["callables_seconds"]))
    if len(sys.argv) > 1 and sys.argv[1] != "--child":
        Path(sys.argv[1]).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if "--child" in sys.argv:
        _child()
    else:
        sys.exit(main())
