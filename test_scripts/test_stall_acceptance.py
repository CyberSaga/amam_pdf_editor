"""H23 findings 3 and 11: the stall acceptance rejects every failed or dropped answer.

``watch.done()`` only says the gesture stopped waiting; it is also true on a failure or a drop.
The acceptance helpers must read the status and fail on anything but "ready".
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from test_scripts import gui_stall_probe
from test_scripts.gui_stall_probe import CombinedAnswerWatch

FAILURE_STATUSES = ["no_headroom", "resource_limited", "analysis_failed", "containment_failed", "crashed"]


class FakeProbe(QObject):
    tables_ready = Signal(int)
    probe_failed = Signal(str, int, str)
    text_index_ready = Signal(int)
    probe_dropped = Signal(str, int)

    pending_text = False

    def has_pending_text(self, _page_num: int) -> bool:
        return self.pending_text


def _watch() -> tuple[FakeProbe, CombinedAnswerWatch]:
    probe = FakeProbe()
    return probe, CombinedAnswerWatch(probe, 1)


def test_a_ready_table_answer_is_accepted():
    probe, watch = _watch()
    probe.tables_ready.emit(1)
    assert watch.done() and gui_stall_probe.table_acceptance_failure(watch) is None


def test_no_table_answer_yet_is_not_accepted():
    _probe, watch = _watch()
    assert gui_stall_probe.table_acceptance_failure(watch) is not None


@pytest.mark.parametrize("status", FAILURE_STATUSES)
def test_every_failed_table_status_is_reported_as_failed(status):
    probe, watch = _watch()
    probe.probe_failed.emit("tables", 1, status)
    assert watch.done()  # the gesture stopped waiting ...
    failure = gui_stall_probe.table_acceptance_failure(watch)
    assert failure is not None and status in failure  # ... but it did not succeed


def test_text_entry_accepts_a_ready_signal_and_an_inline_build():
    probe, watch = _watch()
    probe.text_index_ready.emit(1)
    assert gui_stall_probe.text_entry_acceptance_failure(watch, "clean") is None
    _probe2, watch2 = _watch()  # no text job requested, index built inline
    assert gui_stall_probe.text_entry_acceptance_failure(watch2, "clean") is None


@pytest.mark.parametrize("status", FAILURE_STATUSES)
def test_text_entry_rejects_every_failed_text_status_even_with_a_built_index(status):
    probe, watch = _watch()
    probe.probe_failed.emit("text", 1, status)
    assert watch.text.done()
    failure = gui_stall_probe.text_entry_acceptance_failure(watch, "clean")
    assert failure is not None and status in failure


def test_text_entry_rejects_a_dropped_signal():
    probe, watch = _watch()
    probe.probe_dropped.emit("text", 1)
    assert watch.text.done()
    assert gui_stall_probe.text_entry_acceptance_failure(watch, "clean") is not None


def test_a_stale_dropped_signal_does_not_settle_while_a_text_job_is_pending():
    probe, watch = _watch()
    probe.probe_dropped.emit("text", 1)
    probe.pending_text = True  # the replacement job is still running
    assert watch.text.done()  # the raw watch is true for the stale drop ...
    assert not gui_stall_probe.text_entry_settled(watch, "stale")  # ... the settle predicate is not
    assert not gui_stall_probe.text_entry_settled(watch, "clean")
    probe.text_index_ready.emit(1)  # the real answer arrives
    assert gui_stall_probe.text_entry_settled(watch, "clean")


def test_text_settle_without_pending_job_follows_the_signal_or_a_clean_page():
    probe, watch = _watch()
    assert not gui_stall_probe.text_entry_settled(watch, "stale")
    assert gui_stall_probe.text_entry_settled(watch, "clean")  # inline build
    probe.probe_dropped.emit("text", 1)  # dropped and nothing pending: stop waiting
    assert gui_stall_probe.text_entry_settled(watch, "stale")


def test_text_entry_rejects_no_signal_and_an_unbuilt_index():
    _probe, watch = _watch()
    assert gui_stall_probe.text_entry_acceptance_failure(watch, "stale") is not None


def test_other_pages_and_kinds_do_not_count():
    probe, watch = _watch()
    probe.probe_failed.emit("text", 2, "analysis_failed")
    probe.probe_failed.emit("tables", 1, "analysis_failed")  # a tables failure is not a text status
    assert watch.text.status is None
    assert gui_stall_probe.text_entry_acceptance_failure(watch, "clean") is None


@pytest.mark.parametrize(("table", "text"), [("no_headroom", None), (None, "no_headroom"), ("ready", "no_headroom")])
def test_starvation_reads_the_table_and_the_text_status(table, text):
    probe, watch = _watch()
    if table == "no_headroom":
        probe.probe_failed.emit("tables", 1, "no_headroom")
    elif table == "ready":
        probe.tables_ready.emit(1)
    if text == "no_headroom":
        probe.probe_failed.emit("text", 1, "no_headroom")
    assert gui_stall_probe.starved(watch) is True


@pytest.mark.parametrize("status", FAILURE_STATUSES)
def test_combined_gesture_rejects_table_ready_with_any_text_failure(status):
    """H2: tables=ready must not hide a failed text analysis (class: completion mistaken for success)."""
    probe, watch = _watch()
    probe.tables_ready.emit(1)
    probe.probe_failed.emit("text", 1, status)
    assert watch.done()
    failure = gui_stall_probe.combined_acceptance_failure(watch)
    assert failure is not None and status in failure


def test_combined_gesture_rejects_table_ready_with_a_dropped_text_job():
    probe, watch = _watch()
    probe.tables_ready.emit(1)
    probe.probe_dropped.emit("text", 1)
    assert watch.done()
    assert gui_stall_probe.combined_acceptance_failure(watch) is not None


def test_combined_gesture_accepts_table_ready_with_text_ready_or_no_text_job():
    probe, watch = _watch()
    probe.tables_ready.emit(1)
    assert gui_stall_probe.combined_acceptance_failure(watch) is None
    probe.text_index_ready.emit(1)
    assert gui_stall_probe.combined_acceptance_failure(watch) is None


@pytest.mark.parametrize("status", FAILURE_STATUSES)
def test_combined_gesture_still_rejects_a_failed_table(status):
    probe, watch = _watch()
    probe.probe_failed.emit("tables", 1, status)
    probe.text_index_ready.emit(1)
    assert gui_stall_probe.combined_acceptance_failure(watch) is not None


def test_both_stall_tests_use_the_combined_acceptance_helper():
    """Closure check: the real acceptance path of each combined gesture is the combined helper."""
    from pathlib import Path

    here = Path(__file__).parent
    for name in ("test_gui_stall.py", "test_cad_sample_click.py"):
        src = (here / name).read_text(encoding="utf-8")
        assert "combined_acceptance_failure(watch)" in src, name
        assert "gui_stall_probe.table_acceptance_failure(watch)" not in src, name


def test_no_starvation_on_other_failures():
    probe, watch = _watch()
    probe.probe_failed.emit("tables", 1, "analysis_failed")
    probe.probe_failed.emit("text", 1, "resource_limited")
    assert gui_stall_probe.starved(watch) is False
