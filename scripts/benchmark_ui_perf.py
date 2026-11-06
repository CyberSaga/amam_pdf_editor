"""UI performance harness -- startup, open, zoom, F5 fit, scroll, tab switch.

Drives the real app in-process (``main.run(start_event_loop=False)`` + the
View's own user-facing entry points) under ``QT_QPA_PLATFORM=offscreen``, one
child interpreter per (file, run) so every run pays a cold start.  The parent
aggregates median and nearest-rank p90 per scenario and writes raw JSON to
``--out-dir`` (default: ``<TEMP>/pdf_editor_perf``; never inside the repo).

Scenarios (all wall clock, milliseconds):

* ``startup_wall``      parent spawn -> first window shown (includes interpreter start)
* ``startup_inproc``    child's first line -> first window shown
* ``open_first_paint``  ``view._queue_or_open_paths`` (cold: controller bootstrap
                        included) -> initial page quality ``low``
* ``open_high``         same start -> initial page quality ``high``
* ``zoom_sync``         ``view._zoom_relative`` call (signal -> ``change_scale``)
* ``zoom_settle``       same start -> every visible page quality ``high``
* ``f5_enter`` / ``f5_exit``  toggle fullscreen -> visible pages ``high``
                        (+ ``_rebuild_continuous_scene`` call counts)
* ``scroll_step_sync``  one scrollbar ``setValue`` (fast sweep, 40 steps)
* ``scroll_step_content`` same start -> every visible page at least ``low``
* ``tab_switch_low`` / ``tab_switch_high``  tab bar ``setCurrentIndex`` -> page ready
* ``gil_probe``         worker-thread raster of page 0 at 2.0 while the GUI only pumps

Stall windows (per scenario, ``summary[file]["windows"]``): ``gap_max_ms`` /
``gap_p95_ms`` (5 ms heartbeat lateness), ``input_latency_p95_ms`` /
``input_latency_max_ms`` (event posted from a thread -> handled), ``pump_max_ms``
(longest ``processEvents``).  Counts add ``sync_render_*``, ``live_thumb_*``,
``snapshot_capture_*`` (calls/ms), ``render_dispatched`` / ``render_consumed``;
the child records ``peak_rss_mb``.

``--repo-root`` runs the children against another source tree (e.g. a
pre-change snapshot) so baseline and patched builds interleave in one session.
``--profile SCENARIO`` wraps that scenario in cProfile (main thread only) and
writes ``.prof`` + a text summary next to the JSON.

Run:  .venv\\Scripts\\python.exe scripts/benchmark_ui_perf.py --runs 5
"""
from __future__ import annotations

import time

_CHILD_T_START = time.time()

import argparse  # noqa: E402
import collections  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread, QTimer, QObject  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [
    "test_files/1.pdf",
    "test_files/mozilla-pdf/artofwar.pdf",
    "test_files/mozilla-pdf/bpl13210.pdf",
    "test_files/mozilla-pdf/22060_A1_01_Plans.pdf",
]
SECOND_TAB_FILE = "test_files/test-horizontal-texts.pdf"
ZOOM_FACTORS = (1.1, 1.2, 1.3, 0.75, 0.6)
SCROLL_STEPS = 40
TAB_ROUND_TRIPS = 3
WAIT_TIMEOUT_S = 30.0
#: Background drain cap; the old 10 s cap censored every heavy-file bg_after_* sample
#: and 120 s still censored the 90-page heavy file (bg_after_open median 127 s).
SETTLE_CAP_S = 300.0
#: Idle must hold this long before a settle ends (chained singleShot(0) batches).
SETTLE_HOLD_S = 0.25
SCENARIOS = (
    "startup_wall",
    "startup_inproc",
    "open_first_paint",
    "open_high",
    "zoom_sync",
    "zoom_settle",
    "f5_enter",
    "f5_exit",
    "scroll_step_sync",
    "scroll_step_content",
    "scroll_sweep_total",
    "tab_switch_sync",
    "tab_switch_low",
    "tab_switch_high",
    "bg_after_open",
    "bg_after_zoom",
    "bg_after_f5_enter",
    "bg_after_f5_exit",
    "bg_after_scroll",
    "bg_after_tab_switch",
    "gil_probe",
)
#: Stall-probe tuning (plans/perf-heavy-files.md step 0b).
HEARTBEAT_INTERVAL_MS = 5
INPUT_PROBE_PERIOD_S = 0.02
#: Window metrics, in report order.
WINDOW_METRICS = (
    "gap_max_ms",
    "gap_p95_ms",
    "input_latency_p95_ms",
    "input_latency_max_ms",
    "pump_max_ms",
)


# ---------------------------------------------------------------- statistics


def _pct(samples: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100); 0.0 for no samples."""
    ordered = sorted(s for s in samples if s is not None)
    n = len(ordered)
    if not n:
        return 0.0
    return ordered[min(n - 1, max(0, math.ceil(n * q / 100.0) - 1))]


def _summary(samples: list[float]) -> dict:
    ordered = sorted(s for s in samples if s is not None)
    n = len(ordered)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "median_ms": round(statistics.median(ordered), 2),
        "p90_ms": round(_pct(ordered, 90), 2),
        "p95_ms": round(_pct(ordered, 95), 2),
        "min_ms": round(ordered[0], 2),
        "max_ms": round(ordered[-1], 2),
    }


# ---------------------------------------------------------------- stall probes


class HeartbeatProbe:
    """5 ms ``Qt.PreciseTimer``; records how late each tick fires.

    A blocked GUI thread coalesces missed ticks into one late tick, so
    ``gap_max_ms`` is the longest the event loop went unserved."""

    def __init__(self, interval_ms: int = HEARTBEAT_INTERVAL_MS) -> None:
        self.interval_ms = interval_ms
        self.gaps_ms: list[float] = []
        self._last = 0.0
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        now = time.perf_counter()
        self.gaps_ms.append(max(0.0, (now - self._last) * 1000.0 - self.interval_ms))
        self._last = now

    def start(self) -> None:
        self.gaps_ms = []
        self._last = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def metrics(self) -> dict:
        return {
            "gap_max_ms": round(max(self.gaps_ms, default=0.0), 3),
            "gap_p95_ms": round(_pct(self.gaps_ms, 95), 3),
        }


class InputLatencyProbe(QObject):
    """Time from posting a custom ``QEvent`` to its handling on the GUI thread.

    The poster is a background ``threading.Thread`` (``scripts/`` is outside the
    CI threading grep): a GUI-thread timer cannot post while the GUI is blocked.
    The thread also needs the GIL to run, so a GIL-holding raster delays the
    *post* as well as the handling; the figure is a lower bound on what a user
    event would wait.  Events to one receiver are delivered in order, so the
    post timestamps travel through a FIFO deque."""

    def __init__(self, period_s: float = INPUT_PROBE_PERIOD_S) -> None:
        super().__init__()
        self._type = QEvent.Type(QEvent.registerEventType())
        self._period_s = period_s
        self._posted: collections.deque[float] = collections.deque()
        self.latencies_ms: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def event(self, ev) -> bool:  # noqa: N802 - Qt name
        if ev.type() == self._type:
            try:
                posted = self._posted.popleft()
            except IndexError:
                return True
            self.latencies_ms.append((time.perf_counter() - posted) * 1000.0)
            return True
        return super().event(ev)

    def _post_loop(self) -> None:
        # time.sleep (high-resolution timer on Windows, py>=3.11) on a fixed
        # schedule: Event.wait(timeout) can oversleep by a 15 ms tick, which
        # would stretch the posting period and under-report a short block.
        next_t = time.perf_counter() + self._period_s
        while not self._stop.is_set():
            time.sleep(max(0.0, next_t - time.perf_counter()))
            if self._stop.is_set():
                break
            self._posted.append(time.perf_counter())
            QCoreApplication.postEvent(self, QEvent(self._type))
            next_t += self._period_s

    def start(self) -> None:
        self.latencies_ms = []
        self._posted.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._post_loop, name="bench-input-probe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5.0)
            self._thread = None
        QCoreApplication.removePostedEvents(self, int(self._type))
        self._posted.clear()

    def metrics(self) -> dict:
        return {
            "input_latency_p95_ms": round(_pct(self.latencies_ms, 95), 3),
            "input_latency_max_ms": round(max(self.latencies_ms, default=0.0), 3),
        }


def _wrap_timed(owner, name: str, prefix: str, counts: dict) -> None:
    """Replace ``owner.name`` with a wrapper counting ``<prefix>_calls`` / ``<prefix>_ms``."""
    original = getattr(owner, name)

    def timed(*a, **kw):
        t0 = time.perf_counter()
        try:
            return original(*a, **kw)
        finally:
            dt = (time.perf_counter() - t0) * 1000.0
            counts[f"{prefix}_calls"] = counts.get(f"{prefix}_calls", 0) + 1
            counts[f"{prefix}_ms"] = round(counts.get(f"{prefix}_ms", 0.0) + dt, 3)

    setattr(owner, name, timed)


def peak_rss_mb(pid: int | None = None) -> float | None:
    """Peak working set in MiB (self or an acknowledged raster PID)."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes  # noqa: PLC0415 - Windows only

    size_t = ctypes.c_size_t

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", size_t),
            ("WorkingSetSize", size_t),
            ("QuotaPeakPagedPoolUsage", size_t),
            ("QuotaPagedPoolUsage", size_t),
            ("QuotaPeakNonPagedPoolUsage", size_t),
            ("QuotaNonPagedPoolUsage", size_t),
            ("PagefileUsage", size_t),
            ("PeakPagefileUsage", size_t),
        ]

    # PITFALLS "ctypes GetProcessMemoryInfo silently zeroes without HANDLE restype".
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetCurrentProcess.argtypes = []
    k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    handle = k32.OpenProcess(0x1000 | 0x10, False, pid) if pid else k32.GetCurrentProcess()
    if not handle:
        return None
    try:
        if not k32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return round(counters.PeakWorkingSetSize / (1024.0 * 1024.0), 1)
    finally:
        if pid:
            k32.CloseHandle(handle)


# ---------------------------------------------------------------- child side


class _MemoryStore:
    """In-memory QSettings stand-in: the harness never writes the user's prefs."""

    def __init__(self, *_args) -> None:
        self._data: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self._data.get(key, default)

    def setValue(self, key, value) -> None:
        self._data[key] = value

    def remove(self, key) -> None:
        self._data.pop(key, None)

    def contains(self, key) -> bool:
        return key in self._data

    def sync(self) -> None:
        return None


class _Child:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.result: dict = {"file": Path(args.file).name, "samples": {}, "counts": {},
                            "render_worker": getattr(args, "render_worker", "thread")}
        self.app = self.view = self.controller = self.model = None
        self.profiler = None
        #: Stall windows (plans/perf-heavy-files.md step 0b); off until run() enables them.
        self.probes_enabled = False
        self._pump_ms: list[float] = []
        self._win_name: str | None = None
        self._heartbeat: HeartbeatProbe | None = None
        self._input_probe: InputLatencyProbe | None = None

    # -- helpers --------------------------------------------------------

    def _add(self, scenario: str, value_ms: float | None) -> None:
        self.result["samples"].setdefault(scenario, []).append(
            None if value_ms is None else round(value_ms, 3)
        )

    def _process_events(self) -> None:
        t0 = time.perf_counter()
        self.app.processEvents()
        if self._win_name is not None:
            self._pump_ms.append((time.perf_counter() - t0) * 1000.0)

    def _window_begin(self, name: str) -> None:
        """Start the heartbeat, the input probe and pump timing for one scenario window.

        Windows do not nest: a begin inside an open window is ignored (and so is
        its end), so a settle inside a scenario cannot corrupt the outer sample."""
        if not self.probes_enabled or self._win_name is not None:
            return
        if self._heartbeat is None:
            self._heartbeat = HeartbeatProbe()
            self._input_probe = InputLatencyProbe()
        self._pump_ms = []
        self._win_name = name
        self._heartbeat.start()
        assert self._input_probe is not None
        self._input_probe.start()

    def _window_end(self, name: str) -> None:
        if self._win_name != name or self._heartbeat is None or self._input_probe is None:
            return
        self._heartbeat.stop()
        self._input_probe.stop()
        metrics = {**self._heartbeat.metrics(), **self._input_probe.metrics()}
        metrics["pump_max_ms"] = round(max(self._pump_ms, default=0.0), 3)
        metrics["gap_n"] = len(self._heartbeat.gaps_ms)
        metrics["input_n"] = len(self._input_probe.latencies_ms)
        self.result.setdefault("windows", {}).setdefault(name, []).append(metrics)
        self._win_name = None
        self._pump_ms = []

    def _pump(self) -> None:
        self._process_events()
        time.sleep(0.0005)

    def _wait(self, predicate, timeout_s: float = WAIT_TIMEOUT_S) -> bool:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            self._process_events()
            if predicate():
                return True
            time.sleep(0.0005)
        return False

    def _quality(self, page_idx: int) -> str | None:
        sid = self.model.get_active_session_id()
        if not sid:
            return None
        return self.controller._page_quality_map(sid).get(page_idx)

    def _visible_pages(self) -> list[int]:
        start, end = self.view.visible_page_range(prefetch=0)
        return list(range(start, end + 1)) if end >= start else []

    def _all_visible(self, qualities: set[str]) -> bool:
        pages = self._visible_pages()
        return bool(pages) and all(self._quality(p) in qualities for p in pages)

    def _background_busy(self) -> bool:
        """Any thumbnail job, page-render job or pending visible batch still running."""
        controller = self.controller
        for name in ("_thumbnail_coordinator", "_page_render_coordinator"):
            coord = getattr(controller, name, None)
            if coord is None:
                continue
            # cancel() clears the active job while its QThread is still inside
            # get_pixmap (holding the GIL): a live thread is still busy.
            if getattr(coord, "has_active_job", False) or bool(getattr(coord, "_threads", None)):
                return True
        pending = getattr(controller, "_render_batch_pending_by_session", None) or {}
        return any(pending.values())

    def _settle_background(self, label: str | None = None, max_s: float | None = None) -> float:
        """Let ALL background work drain between scenarios (plans/perf-heavy-files.md step 0).

        Returns the ms the drain took: background work a scenario left behind.
        Waits for the thumbnail and page-render coordinators and any pending
        visible batch, up to ``SETTLE_CAP_S``; a cap hit is recorded under
        ``result["censored"]`` (the sample is then a lower bound, not the work)."""
        cap = SETTLE_CAP_S if max_s is None else max_s
        window = label if label and label.startswith("bg_after") else None
        if window:
            self._window_begin(window)
        try:
            return self._settle_loop(label, cap)
        finally:
            if window:
                self._window_end(window)

    def _settle_loop(self, label: str | None, cap: float) -> float:
        t0 = time.perf_counter()
        deadline = t0 + cap
        for _ in range(5):
            self._pump()
        settled = False
        idle_since: float | None = None
        while time.perf_counter() < deadline:
            self._pump()
            if self._background_busy():
                idle_since = None
                continue
            now = time.perf_counter()
            if idle_since is None:
                idle_since = now
            # Batches chain through singleShot(0): idle must hold, not just occur.
            if now - idle_since >= SETTLE_HOLD_S:
                settled = True
                break
        elapsed = (time.perf_counter() - t0) * 1000.0
        if not settled:
            self.result.setdefault("censored", []).append(label or "settle")
        for _ in range(20):
            self._pump()
        return elapsed

    def _profile_start(self, scenario: str) -> None:
        if self.args.profile == scenario:
            import cProfile

            self.profiler = cProfile.Profile()
            self.profiler.enable()

    def _profile_stop(self, scenario: str) -> None:
        if self.profiler is None or self.args.profile != scenario:
            return
        import io
        import pstats

        self.profiler.disable()
        stem = Path(self.args.json_out).with_suffix("")
        prof_path = Path(f"{stem}.{scenario}.prof")
        self.profiler.dump_stats(str(prof_path))
        buf = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=buf).sort_stats("cumulative")
        stats.print_stats(60)
        buf.write("\n\n==== tottime ====\n")
        stats.sort_stats("tottime").print_stats(40)
        Path(f"{stem}.{scenario}.txt").write_text(buf.getvalue(), encoding="utf-8")
        self.profiler = None

    def _install_counters(self) -> None:
        counts = self.result["counts"]

        def wrap(owner, name: str, key: str) -> None:
            original = getattr(owner, name)

            def counted(*a, **kw):
                counts[key] = counts.get(key, 0) + 1
                return original(*a, **kw)

            setattr(owner, name, counted)

        wrap(self.controller, "_rebuild_continuous_scene", "rebuild_continuous_scene")
        wrap(self.controller, "load_toc", "load_toc")
        wrap(self.view, "initialize_continuous_placeholders", "initialize_placeholders")
        wrap(self.controller, "_schedule_thumbnail_batch", "thumbnail_batch_requests")
        wrap(self.view, "_update_thumbnail_layout_metrics", "thumbnail_layout_passes")
        self._install_timed_counters()
        self._install_render_counters()
        original_consume = self.controller._consume_thumbnail_images

        def consume(start, images):
            counts["thumbnail_images_consumed"] = counts.get("thumbnail_images_consumed", 0) + len(images)
            return original_consume(start, images)

        # The coordinator holds the bound method; patch its consumer reference too.
        self.controller._consume_thumbnail_images = consume
        coord = getattr(self.controller, "_thumbnail_coordinator", None)
        if coord is not None and hasattr(coord, "_batch_consumer"):
            coord._batch_consumer = consume

    def _install_timed_counters(self) -> None:
        """Count and time the calls that rasterize or capture on the GUI thread.

        ``live_thumb`` wraps ``get_thumbnail``, which itself calls
        ``get_page_pixmap``: its time is also inside ``sync_render``."""
        counts = self.result["counts"]
        for owner, name, prefix in (
            (self.model, "get_page_pixmap", "sync_render"),
            (self.model, "get_thumbnail", "live_thumb"),
            (self.controller, "capture_worker_snapshot_bytes", "snapshot_capture"),
        ):
            if owner is not None and hasattr(owner, name):
                _wrap_timed(owner, name, prefix, counts)

    def _install_render_counters(self) -> None:
        counts = self.result["counts"]
        controller = self.controller
        original_dispatch = controller._dispatch_page_render_request

        def dispatch(*a, **kw):
            sent = original_dispatch(*a, **kw)
            if sent:
                counts["render_dispatched"] = counts.get("render_dispatched", 0) + 1
            return sent

        controller._dispatch_page_render_request = dispatch
        original_consume = controller._consume_page_render_image

        def consume(*a, **kw):
            counts["render_consumed"] = counts.get("render_consumed", 0) + 1
            return original_consume(*a, **kw)

        controller._consume_page_render_image = consume
        # The coordinator holds the bound method from construction.
        coord = getattr(controller, "_page_render_coordinator", None)
        if coord is not None and hasattr(coord, "_result_consumer"):
            coord._result_consumer = consume

    def _snapshot_counts(self) -> dict:
        return dict(self.result["counts"])

    def _delta_counts(self, before: dict) -> dict:
        after = self.result["counts"]
        return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}

    # -- scenarios ------------------------------------------------------

    def startup(self) -> None:
        t_in = time.perf_counter()
        self._profile_start("startup")
        import main  # noqa: PLC0415 - timed on purpose
        import utils.preferences as preferences

        preferences._make_default_store = _MemoryStore
        self.result["main_file"] = str(Path(main.__file__).resolve())
        startup = main.run(argv=[], start_event_loop=False)
        self.app, self.view = startup["app"], startup["view"]
        self._startup = startup
        self.app.processEvents()
        t_shown = time.time()
        self._profile_stop("startup")
        self._add("startup_inproc", (t_shown - _CHILD_T_START) * 1000.0)
        self._add("startup_wall", (t_shown - self.args.t0) * 1000.0)
        self.result["startup_main_run_ms"] = round((time.perf_counter() - t_in) * 1000.0, 3)
        self.result["window_size"] = [self.view.width(), self.view.height()]

    def open_document(self) -> None:
        path = str(Path(self.args.file).resolve())
        self._profile_start("open")
        self._window_begin("open")
        t0 = time.perf_counter()
        self.view._queue_or_open_paths([path])
        self.controller = self._startup["controller"]
        self.model = self._startup["model"]
        if self.controller is None:
            # Bootstrap runs on the signal; it is synchronous today.
            raise RuntimeError("controller not bootstrapped by the open path")
        self._install_counters()
        page = max(0, self.view.current_page)
        ok_low = self._wait(lambda: self._quality(page) in {"low", "high"})
        self._add("open_first_paint", (time.perf_counter() - t0) * 1000.0 if ok_low else None)
        ok_high = self._wait(lambda: self._quality(page) == "high")
        self._add("open_high", (time.perf_counter() - t0) * 1000.0 if ok_high else None)
        self._profile_stop("open")
        self._window_end("open")
        self.result["pages"] = len(self.model.doc)
        self._add("bg_after_open", self._settle_background("bg_after_open"))
        self.result["open_counts"] = dict(self.result["counts"])

    def gil_probe(self) -> None:
        """Does a worker-thread raster stall the GUI thread?  (plan hypothesis: it holds the GIL)

        A ``_PageRenderWorker`` on a QThread renders page 0 at scale 2.0 while the
        heartbeat and input probes run; the GUI thread only pumps events.  Any gap
        therefore comes from the raster, not from GUI work.  The raster time is
        stamped on the worker thread (direct connections): thread start to
        ``rendered`` emission, so it includes opening the snapshot bytes and the
        QImage conversion."""
        from controller.page_render_coordinator import (  # noqa: PLC0415 - needs a QApplication
            PageRenderIdentity,
            PageRenderRequest,
            _PageRenderWorker,
        )

        sid = self.model.get_active_session_id()
        snapshot = self.controller.capture_worker_snapshot_bytes()
        identity = PageRenderIdentity(
            token="gil_probe",
            session_id=sid,
            generation=0,
            revision=0,
            page_index=0,
            quality="high",
            rendered_scale=2.0,
            target_scale=2.0,
            color_profile=self.controller._color_profile_for_session(sid),
            device_pixel_ratio=1.0,
        )
        worker = _PageRenderWorker(PageRenderRequest(identity, snapshot))
        thread = QThread()
        worker.moveToThread(thread)
        stamps: dict[str, float] = {}
        done: list[bool] = []
        thread.started.connect(lambda: stamps.setdefault("t0", time.perf_counter()), Qt.ConnectionType.DirectConnection)
        thread.started.connect(worker.run)
        worker.rendered.connect(
            lambda *_: stamps.setdefault("t1", time.perf_counter()), Qt.ConnectionType.DirectConnection
        )
        worker.finished.connect(lambda *_: done.append(True), Qt.ConnectionType.DirectConnection)
        self._window_begin("gil_probe")
        try:
            thread.start()
            finished = self._wait(lambda: bool(done))
        finally:
            worker.cancel()
            thread.quit()
            thread.wait()
            self._window_end("gil_probe")
        raster_ms = (stamps["t1"] - stamps["t0"]) * 1000.0 if finished and {"t0", "t1"} <= stamps.keys() else None
        self._add("gil_probe", raster_ms)
        self.result["gil_probe_raster_ms"] = None if raster_ms is None else round(raster_ms, 3)
        worker.deleteLater()
        thread.deleteLater()

    def zoom(self) -> None:
        before = self._snapshot_counts()
        self._profile_start("zoom")
        self._window_begin("zoom")
        for factor in ZOOM_FACTORS:
            t0 = time.perf_counter()
            self.view._zoom_relative(factor)
            self._add("zoom_sync", (time.perf_counter() - t0) * 1000.0)
            ok = self._wait(lambda: self._all_visible({"high"}))
            self._add("zoom_settle", (time.perf_counter() - t0) * 1000.0 if ok else None)
        self._profile_stop("zoom")
        self._window_end("zoom")
        self._add("bg_after_zoom", self._settle_background("bg_after_zoom"))
        self.result["zoom_counts"] = self._delta_counts(before)

    def fullscreen(self) -> None:
        for phase in ("f5_enter", "f5_exit"):
            before = self._snapshot_counts()
            size_before = [self.view.graphics_view.width(), self.view.graphics_view.height()]
            self._profile_start(phase)
            self._window_begin(phase)
            t0 = time.perf_counter()
            self.view.sig_toggle_fullscreen.emit()
            ok = self._wait(lambda: self._all_visible({"high"}))
            # Let any trailing resize/fit settle so its rebuild is counted too.
            for _ in range(30):
                self._pump()
            self._add(phase, (time.perf_counter() - t0) * 1000.0 if ok else None)
            self._profile_stop(phase)
            self._window_end(phase)
            self._add(f"bg_after_{phase}", self._settle_background(f"bg_after_{phase}"))
            self.result[f"{phase}_counts"] = self._delta_counts(before)
            self.result[f"{phase}_viewport"] = [
                size_before,
                [self.view.graphics_view.width(), self.view.graphics_view.height()],
            ]

    def scroll(self) -> None:
        if len(self.model.doc) < 3:
            return
        sb = self.view.graphics_view.verticalScrollBar()
        self.view.scroll_to_page(0)
        self._wait(lambda: self._all_visible({"high"}))
        self._settle_background("pre_scroll")
        lo, hi = sb.minimum(), sb.maximum()
        before = self._snapshot_counts()
        self._profile_start("scroll")
        self._window_begin("scroll")
        t_sweep = time.perf_counter()
        for step in range(1, SCROLL_STEPS + 1):
            value = lo + (hi - lo) * step // SCROLL_STEPS
            t0 = time.perf_counter()
            sb.setValue(value)
            self._add("scroll_step_sync", (time.perf_counter() - t0) * 1000.0)
            ok = self._wait(lambda: self._all_visible({"low", "high"}))
            self._add("scroll_step_content", (time.perf_counter() - t0) * 1000.0 if ok else None)
        self._add("scroll_sweep_total", (time.perf_counter() - t_sweep) * 1000.0)
        self._profile_stop("scroll")
        self._window_end("scroll")
        self._add("bg_after_scroll", self._settle_background("bg_after_scroll"))
        self.result["scroll_counts"] = self._delta_counts(before)

    def tabs(self) -> None:
        second = str((ROOT / SECOND_TAB_FILE).resolve())
        self.view._queue_or_open_paths([second])
        self._wait(lambda: self.view.document_tab_bar.count() == 2)
        self._wait(lambda: self._quality(max(0, self.view.current_page)) == "high")
        self._settle_background("pre_tabs")
        bar = self.view.document_tab_bar
        before = self._snapshot_counts()
        self._profile_start("tabs")
        for _ in range(TAB_ROUND_TRIPS):
            for target in (0, 1):
                self._window_begin("tab_switch")
                t0 = time.perf_counter()
                bar.setCurrentIndex(target)
                self._add("tab_switch_sync", (time.perf_counter() - t0) * 1000.0)
                page = max(0, self.view.current_page)
                ok_low = self._wait(lambda p=page: self._quality(p) in {"low", "high"})
                self._add("tab_switch_low", (time.perf_counter() - t0) * 1000.0 if ok_low else None)
                ok_high = self._wait(lambda p=page: self._quality(p) == "high")
                self._add("tab_switch_high", (time.perf_counter() - t0) * 1000.0 if ok_high else None)
                self._window_end("tab_switch")
                self._add("bg_after_tab_switch", self._settle_background("bg_after_tab_switch"))
        self._profile_stop("tabs")
        self.result["tabs_counts"] = self._delta_counts(before)

    def run(self) -> None:
        self.startup()
        self.probes_enabled = True
        try:
            if not self.args.startup_only:
                self.open_document()
                self.gil_probe()
                self.zoom()
                self.fullscreen()
                self.scroll()
                self.tabs()
        finally:
            self._win_name = None
            for probe in (self._heartbeat, self._input_probe):
                if probe is not None:
                    probe.stop()
        self.result["peak_rss_mb"] = peak_rss_mb()
        client = self._startup.get('render_client')
        if client is not None:
            client.sample_memory()
            self.result['render_process'] = dict(client.metrics)
            self.result['render_child_peak_rss_mb'] = client.metrics['child_peak_mb']
            client.shutdown()
        Path(self.args.json_out).write_text(json.dumps(self.result, indent=1), encoding="utf-8")


def _child_main(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    child = _Child(args)
    child.result["child_import_ms"] = round((time.time() - _CHILD_T_START) * 1000.0, 3)
    child.run()
    sys.stdout.flush()
    # Teardown is not a target; skip it so a slow worker join cannot stall the sweep.
    os._exit(0)


# ---------------------------------------------------------------- parent side


def _child_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PDF_EDITOR_RENDER_WORKER"] = args.render_worker
    env.pop("PDF_EDITOR_DEBUG", None)
    return env


def _spawn(args: argparse.Namespace, root: str, file: str, run_idx: int, out_dir: Path, label: str) -> dict | None:
    stem = f"{label}.{Path(file).stem}.r{run_idx}"
    json_out = out_dir / f"{stem}.json"
    env = _child_env(args)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--file", str((ROOT / file).resolve()),
        "--repo-root", str(Path(root).resolve()),
        "--json-out", str(json_out),
        "--t0", repr(time.time()),
        "--render-worker", args.render_worker,
    ]
    if args.profile:
        cmd += ["--profile", args.profile]
    if args.startup_only:
        cmd += ["--startup-only"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(root).resolve()),
            env=env,
            capture_output=True,
            text=True,
            timeout=args.child_timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {stem}", flush=True)
        return None
    if proc.returncode != 0 or not json_out.is_file():
        print(f"  FAILED {stem} rc={proc.returncode}\n{proc.stderr[-2000:]}", flush=True)
        return None
    return json.loads(json_out.read_text(encoding="utf-8"))


def _summarize(runs: dict[str, list[dict]]) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for name, results in runs.items():
        per: dict[str, dict] = {}
        for scenario in SCENARIOS:
            samples = [v for r in results for v in r["samples"].get(scenario, [])]
            missing = sum(1 for v in samples if v is None)
            if samples:
                per[scenario] = {**_summary(samples), "timeouts": missing}
        per["counts_last_run"] = {
            k: results[-1].get(k)
            for k in ("open_counts", "zoom_counts", "f5_enter_counts", "f5_exit_counts", "scroll_counts", "tabs_counts")
        }
        windows: dict[str, dict] = {}
        for r in results:
            for wname, entries in r.get("windows", {}).items():
                bucket = windows.setdefault(wname, {})
                for entry in entries:
                    for metric in WINDOW_METRICS:
                        bucket.setdefault(metric, []).append(entry.get(metric, 0.0))
        per["windows"] = {
            wname: {metric: _summary(values) for metric, values in bucket.items()}
            for wname, bucket in windows.items()
        }
        rss = [r["peak_rss_mb"] for r in results if r.get("peak_rss_mb") is not None]
        per["peak_rss_mb"] = _summary(rss) if rss else {"n": 0}
        child_rss = [r['render_child_peak_rss_mb'] for r in results
                     if r.get('render_child_peak_rss_mb') is not None]
        per['render_child_peak_rss_mb'] = _summary(child_rss)
        process_runs = [r['render_process'] for r in results if r.get('render_process')]
        if process_runs:
            per['render_process'] = {
                key: _summary([r[key] for r in process_runs if key in r])
                for key in ('doc_loads', 'ipc_bytes', 'images', 'starts', 'fallbacks')}
            per['render_process']['frame_gui_ms'] = _summary(
                [value for r in process_runs for value in r.get('frame_gui_ms', [])])
        per["gil_probe_raster_ms"] = [r.get("gil_probe_raster_ms") for r in results]
        per["censored"] = sorted({c for r in results for c in r.get("censored", [])})
        per["pages"] = results[-1].get("pages")
        per["main_file"] = results[-1].get("main_file")
        summary[name] = per
    return summary


def _parent_main(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.gettempdir()) / "pdf_editor_perf"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or time.strftime("%Y%m%d_%H%M%S")
    files = args.files or DEFAULT_FILES
    # --ab-root: children alternate A (that tree, e.g. a pre-change snapshot)
    # and B (--repo-root) per (run, file) so machine drift hits both alike.
    roots = [("A", args.ab_root), ("B", args.repo_root)] if args.ab_root else [("", args.repo_root)]
    runs: dict[str, dict[str, list[dict]]] = {tag: {} for tag, _root in roots}
    for run_idx in range(args.runs):
        for file in files:
            for tag, root in roots:
                sub = f"{label}.{tag}" if tag else label
                print(f"[{sub}] run {run_idx + 1}/{args.runs} {Path(file).name}", flush=True)
                res = _spawn(args, root, file, run_idx, out_dir, sub)
                if res is not None:
                    runs[tag].setdefault(Path(file).name, []).append(res)
    summaries = {tag: _summarize(by_file) for tag, by_file in runs.items()}
    report = {
        "harness": "benchmark_ui_perf",
        "label": label,
        "roots": {tag: str(Path(root).resolve()) for tag, root in roots},
        "runs": args.runs,
        "profile": args.profile,
        "render_worker": args.render_worker,
        "summary": summaries,
        "raw": runs,
    }
    report_path = out_dir / f"{label}.summary.json"
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    first = summaries[roots[0][0]]
    for name, per in first.items():
        print(f"\n{name} ({per.get('pages')} pages)")
        for scenario in SCENARIOS:
            cells = []
            for tag, _root in roots:
                s = summaries[tag].get(name, {}).get(scenario)
                if s and s.get("n"):
                    cells.append(
                        f"{tag or 'median'} {s['median_ms']:>9.1f} (p90 {s['p90_ms']:>8.1f}, n={s['n']}, to={s['timeouts']})"
                    )
            if cells:
                print(f"  {scenario:22s} " + "  |  ".join(cells))
        for tag, _root in roots:
            windows = summaries[tag].get(name, {}).get("windows") or {}
            if windows:
                print(f"  stall windows {tag or ''} (median over samples, max over samples; ms)")
            for wname, metrics in windows.items():
                cells = " ".join(
                    f"{m.removesuffix('_ms')} {metrics[m]['median_ms']:.1f}/{metrics[m]['max_ms']:.1f}"
                    for m in WINDOW_METRICS
                    if metrics.get(m, {}).get("n")
                )
                print(f"    {wname:20s} {cells}")
            rss = summaries[tag].get(name, {}).get("peak_rss_mb")
            if rss and rss.get("n"):
                print(f"  peak_rss_mb {tag or ''}: median {rss['median_ms']:.0f} max {rss['max_ms']:.0f}")
            print(f"  counts {tag}: {summaries[tag].get(name, {}).get('counts_last_run')}")
            process = summaries[tag].get(name, {}).get('render_process')
            if process:
                print(f"  process {tag}: loads {process['doc_loads'].get('median_ms')} "
                      f"IPC bytes {process['ipc_bytes'].get('median_ms')} "
                      f"frame GUI p95 ms {process['frame_gui_ms'].get('p95_ms')} "
                      f"child peak MiB {summaries[tag][name]['render_child_peak_rss_mb'].get('median_ms')}")
            censored = summaries[tag].get(name, {}).get("censored")
            if censored:
                print(f"  CENSORED {tag} (settle cap {SETTLE_CAP_S:.0f} s hit): {censored}")
    print(f"\nreport: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--render-worker", choices=("thread", "process"), default="thread")
    parser.add_argument("--files", nargs="*", help="repo-relative PDFs (default: four sizes)")
    parser.add_argument("--out-dir", help="raw JSON directory (default <TEMP>/pdf_editor_perf)")
    parser.add_argument("--label", help="report label (default: timestamp)")
    parser.add_argument("--repo-root", default=str(ROOT), help="source tree the children import")
    parser.add_argument("--ab-root", help="interleave children against this second tree (reported as A; --repo-root is B)")
    parser.add_argument("--profile", choices=("startup", "open", "zoom", "f5_enter", "f5_exit", "scroll", "tabs"))
    parser.add_argument("--startup-only", action="store_true")
    parser.add_argument("--child-timeout", type=float, default=300.0)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--file", help=argparse.SUPPRESS)
    parser.add_argument("--json-out", help=argparse.SUPPRESS)
    parser.add_argument("--t0", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return _child_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
