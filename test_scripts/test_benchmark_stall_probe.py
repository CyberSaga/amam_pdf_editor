"""Stall probes of the UI perf harness (plans/perf-heavy-files.md step 0b).

The heartbeat (5 ms precise timer) and the input-latency probe (events posted
from a background thread every 20 ms) are what turns "the GUI froze for N ms"
into a number per scenario; these tests pin that they see a blocked turn.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import benchmark_ui_perf as bench  # noqa: E402


def _spin(app, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.0005)


@pytest.fixture
def probe_cleanup():
    started: list = []
    yield started
    for probe in started:
        probe.stop()
    assert not [t for t in threading.enumerate() if t.name == "bench-input-probe"]


def test_gap_probe_records_blocking_handler(qapp, probe_cleanup) -> None:
    probe = bench.HeartbeatProbe()
    probe_cleanup.append(probe)
    probe.start()
    QTimer.singleShot(50, lambda: time.sleep(0.2))
    _spin(qapp, 0.45)
    probe.stop()
    assert probe.metrics()["gap_max_ms"] >= 180

    idle = bench.HeartbeatProbe()
    probe_cleanup.append(idle)
    idle.start()
    _spin(qapp, 0.5)
    idle.stop()
    assert idle.metrics()["gap_p95_ms"] < 20


def test_input_latency_probe_records_blocked_turn(qapp, probe_cleanup) -> None:
    probe = bench.InputLatencyProbe()
    probe_cleanup.append(probe)
    probe.start()
    _spin(qapp, 0.1)
    QTimer.singleShot(0, lambda: time.sleep(0.15))
    _spin(qapp, 0.4)
    probe.stop()
    metrics = probe.metrics()
    # Posts every 20 ms: an event posted up to one period after the block began
    # still waits for its end, so a 150 ms block measures at least ~130 ms;
    # 110 leaves room for Windows sleep granularity (~15 ms).
    assert metrics["input_latency_max_ms"] >= 110
    assert metrics["input_latency_p95_ms"] <= metrics["input_latency_max_ms"]


class _SlowApp:
    def processEvents(self) -> None:  # noqa: N802 - Qt name
        time.sleep(0.03)


def test_pump_duration_recorded_per_process_events(qapp) -> None:
    child = bench._Child(argparse.Namespace(file="x.pdf", profile=None, json_out="x.json"))
    child.app = _SlowApp()
    child.probes_enabled = True
    child._window_begin("pumped")
    try:
        child._pump()
        child._wait(lambda: True)
    finally:
        child._window_end("pumped")
    entry = child.result["windows"]["pumped"][0]
    assert entry["pump_max_ms"] >= 25
    assert len(child._pump_ms) == 0  # window closed: recording stops


class _FakeModel:
    def __init__(self) -> None:
        self.args: list = []

    def get_page_pixmap(self, *a, **kw):
        self.args.append(a)
        time.sleep(0.005)
        return "pix"

    def get_thumbnail(self, *a, **kw):
        time.sleep(0.002)
        return "thumb"


class _FakeController:
    def capture_worker_snapshot_bytes(self) -> bytes:
        time.sleep(0.002)
        return b"x"


def test_sync_render_counter_wraps_get_page_pixmap() -> None:
    child = bench._Child(argparse.Namespace(file="x.pdf", profile=None, json_out="x.json"))
    child.model = _FakeModel()
    child.controller = _FakeController()
    child._install_timed_counters()
    assert child.model.get_page_pixmap(1, 2) == "pix"
    assert child.model.get_page_pixmap(3) == "pix"
    child.model.get_thumbnail(0)
    assert child.controller.capture_worker_snapshot_bytes() == b"x"
    counts = child.result["counts"]
    assert counts["sync_render_calls"] == 2
    assert counts["sync_render_ms"] > 0
    assert counts["live_thumb_calls"] == 1
    assert counts["snapshot_capture_calls"] == 1
    assert child.model.args == [(1, 2), (3,)]


def test_summary_has_p95() -> None:
    assert bench._summary([float(i) for i in range(1, 101)])["p95_ms"] == 95.0


@pytest.mark.skipif(sys.platform != "win32", reason="K32GetProcessMemoryInfo")
def test_peak_rss_mb_reads_nonzero() -> None:
    assert bench.peak_rss_mb() > 10
