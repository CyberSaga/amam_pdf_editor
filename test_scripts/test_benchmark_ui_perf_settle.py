"""Benchmark settle must wait for ALL background work and flag a cap hit.

plans/perf-heavy-files.md step 0 (review item 7): ``_settle_background`` gave up
after 10 s and watched only the thumbnail coordinator, so ``bg_after_*`` on the
heavy files (12-13 s) were the cap, not the work, and later scenarios ran with
GIL-holding thumbnail work still going.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import benchmark_ui_perf as bench  # noqa: E402


class _App:
    def processEvents(self) -> None:  # noqa: N802 - Qt name
        pass


class _Coord:
    def __init__(self, busy_polls: int) -> None:
        self.busy_polls = busy_polls

    @property
    def has_active_job(self) -> bool:
        if self.busy_polls > 0:
            self.busy_polls -= 1
            return True
        return False


class _Controller:
    def __init__(self, thumb_polls: int = 0, page_polls: int = 0, batch_pending: bool = False) -> None:
        self._thumbnail_coordinator = _Coord(thumb_polls)
        self._page_render_coordinator = _Coord(page_polls)
        self._render_batch_pending_by_session = {"s": batch_pending}


def _child(controller) -> bench._Child:
    child = bench._Child(argparse.Namespace(file="x.pdf", profile=None, json_out="x.json"))
    child.app = _App()
    child.controller = controller
    return child


def test_settle_waits_for_the_page_render_coordinator_too() -> None:
    controller = _Controller(thumb_polls=0, page_polls=50)
    child = _child(controller)
    child._settle_background("bg_after_open")
    assert controller._page_render_coordinator.busy_polls == 0
    assert child.result.get("censored", []) == []


def test_settle_cap_hit_is_flagged_censored(monkeypatch) -> None:
    monkeypatch.setattr(bench, "SETTLE_CAP_S", 0.05)
    child = _child(_Controller(batch_pending=True))
    child._settle_background("bg_after_zoom")
    assert child.result["censored"] == ["bg_after_zoom"]


def test_settle_default_cap_is_300_s() -> None:
    # 120 s still censored the heavy 90-page file (bg_after_open median 127 s, step 0c).
    assert bench.SETTLE_CAP_S == 300.0


class _ThreadsLeft(dict):
    """``_threads`` that stays non-empty for ``polls`` truthiness checks."""

    def __init__(self, polls: int) -> None:
        super().__init__()
        self.polls = polls

    def __bool__(self) -> bool:
        if self.polls > 0:
            self.polls -= 1
            return True
        return False


def test_settle_waits_for_a_cancelled_thumbnail_thread() -> None:
    """cancel() clears the active job while its QThread is still inside get_pixmap."""
    controller = _Controller()
    controller._thumbnail_coordinator._threads = _ThreadsLeft(30)
    child = _child(controller)
    child._settle_background("bg_after_open")
    assert controller._thumbnail_coordinator._threads.polls == 0
    assert child.result.get("censored", []) == []


class _Flicker:
    """Busy, idle for one poll, then busy again (a singleShot(0)-chained batch)."""

    def __init__(self) -> None:
        self.sequence = [True] * 3 + [False] + [True] * 20

    @property
    def has_active_job(self) -> bool:
        return self.sequence.pop(0) if self.sequence else False


def test_settle_requires_idle_to_hold(monkeypatch) -> None:
    monkeypatch.setattr(bench, "SETTLE_HOLD_S", 0.02)
    controller = _Controller()
    controller._page_render_coordinator = _Flicker()
    child = _child(controller)
    child._settle_background("bg_after_zoom")
    assert controller._page_render_coordinator.sequence == []


def test_summary_keeps_process_transport_and_child_memory_metrics():
    from scripts.benchmark_ui_perf import _summarize

    result = _summarize({'sample': [
        {'samples': {}, 'render_child_peak_rss_mb': 100.,
         'render_process': {'doc_loads': 2, 'ipc_bytes': 1048576,
                            'frame_gui_ms': [1., 2.]}},
        {'samples': {}, 'render_child_peak_rss_mb': 120.,
         'render_process': {'doc_loads': 4, 'ipc_bytes': 3145728,
                            'frame_gui_ms': [3., 4.]}},
    ]})['sample']
    assert result['render_child_peak_rss_mb']['median_ms'] == 110.
    assert result['render_process']['doc_loads']['median_ms'] == 3.
    assert result['render_process']['ipc_bytes']['median_ms'] == 2097152.
    assert result['render_process']['frame_gui_ms']['p95_ms'] == 4.
