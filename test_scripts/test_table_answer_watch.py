"""The A4 stall harness settles a gesture on the coordinator's own signals (card A4, 2026-11-19).

``test_cad_sample_click`` used to poll ``cached_table_rects`` + ``table_analysis_failed``.  Since the
table key became a hash of a one-page scratch copy, every poll built two copies of the page (about
7 ms each on the CAD sample), so the predicate was itself part of the measured heartbeat gap.  And an
answer of ``no_headroom`` (too little free memory for the child) marks nothing, so the predicate
stayed false until the 180 s timeout with no hint of why.  ``TableAnswerWatch`` waits on
``tables_ready`` / ``probe_failed`` instead: polling it builds nothing and a ``no_headroom``
answer names itself.  The real coordinator and a stub runner stand in for the sample; no PDF sample
is needed.
"""
from __future__ import annotations

import fitz
import pytest
from PySide6.QtCore import QObject, Signal

from model import table_objects
from model.pdf_model import PDFModel
from test_scripts.gui_stall_probe import CombinedAnswerWatch, TableAnswerWatch, TextAnswerWatch
from test_scripts.test_object_probe import StubRunner, _coordinator, _table_pdf


class _FakeProbe(QObject):
    tables_ready = Signal(int)
    text_index_ready = Signal(int)
    probe_failed = Signal(str, int, str)
    probe_dropped = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.pending_text = False

    def has_pending_text(self, page_num: int) -> bool:
        return self.pending_text


@pytest.fixture
def probe_model(tmp_path):
    m = PDFModel()
    m.open_pdf(_table_pdf(tmp_path / "t.pdf"))
    yield m
    m.close()


def test_a_fresh_watch_is_not_done():
    watch = TableAnswerWatch(_FakeProbe(), 1)
    assert watch.done() is False
    assert watch.status is None


def test_tables_ready_for_the_page_settles_the_watch():
    probe = _FakeProbe()
    watch = TableAnswerWatch(probe, 1)
    probe.tables_ready.emit(1)
    assert watch.done() is True
    assert watch.status == "ready"


@pytest.mark.parametrize("status", ["no_headroom", "analysis_failed", "resource_limited", "crashed"])
def test_a_failure_answer_for_the_page_settles_the_watch_and_names_its_status(status):
    probe = _FakeProbe()
    watch = TableAnswerWatch(probe, 1)
    probe.probe_failed.emit("tables", 1, status)
    assert watch.done() is True
    assert watch.status == status


def test_answers_for_another_page_or_kind_are_ignored():
    probe = _FakeProbe()
    watch = TableAnswerWatch(probe, 1)
    probe.tables_ready.emit(2)
    probe.probe_failed.emit("tables", 2, "no_headroom")
    probe.probe_failed.emit("scan", 1, "no_headroom")
    assert watch.done() is False
    assert watch.status is None


def test_reset_makes_the_watch_wait_for_the_next_answer():
    probe = _FakeProbe()
    watch = TableAnswerWatch(probe, 1)
    probe.tables_ready.emit(1)
    watch.reset()
    assert watch.done() is False
    probe.probe_failed.emit("tables", 1, "no_headroom")
    assert watch.status == "no_headroom"


def test_polling_the_watch_builds_no_page_copy(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("polling must not build a scratch copy")

    monkeypatch.setattr(table_objects, "scratch_page_bytes", boom)
    watch = TableAnswerWatch(_FakeProbe(), 1)
    for _ in range(50):
        assert watch.done() is False


def test_no_headroom_from_the_real_coordinator_settles_the_watch_with_nothing_cached(probe_model):
    """The run that waited out the 180 s timeout: the runner answers ``no_headroom`` and the old
    predicate never became true."""
    runner = StubRunner()
    coord = _coordinator(probe_model, runner)
    watch = TableAnswerWatch(coord, 1)
    coord.request_tables(1)
    assert watch.done() is False  # the job is running
    runner.complete(runner.order[0], {"v": 2, "status": "no_headroom"})
    assert watch.done() is True
    assert watch.status == "no_headroom"
    # What the old predicate looked at: still false, which is why it waited for the timeout.
    assert table_objects.cached_table_rects(probe_model, 1) is None
    assert table_objects.table_analysis_failed(probe_model, 1) is False


def test_a_complete_answer_from_the_real_coordinator_settles_the_watch_as_ready(probe_model):
    runner = StubRunner()
    coord = _coordinator(probe_model, runner)
    watch = TableAnswerWatch(coord, 1)
    coord.request_tables(1)
    runner.complete(runner.order[0], {"v": 2, "status": "complete", "rects": [[100.0, 200.0, 460.0, 320.0]]})
    assert watch.status == "ready"
    cached = table_objects.cached_table_rects(probe_model, 1)
    assert cached is not None and [tuple(r) for r in cached] == [tuple(fitz.Rect(100, 200, 460, 320))]


def test_a_stale_answer_leaves_the_watch_waiting(probe_model):
    """A page that changed while the child worked drops the answer silently (D1); the watch must
    keep waiting, so the harness times out and the drop is not mistaken for a result."""
    runner = StubRunner()
    coord = _coordinator(probe_model, runner)
    watch = TableAnswerWatch(coord, 1)
    coord.request_tables(1)
    probe_model.doc[0].insert_text((50, 50), "changed while the probe ran", fontsize=11)
    runner.complete(runner.order[0], {"v": 2, "status": "complete", "rects": [[100.0, 200.0, 460.0, 320.0]]})
    assert watch.done() is False
    assert table_objects.cached_table_rects(probe_model, 1) is None


# --------------------------------------------------------------------------- text and combined (A6.8)


def test_text_index_ready_for_the_page_settles_the_text_watch():
    probe = _FakeProbe()
    watch = TextAnswerWatch(probe, 1)
    assert watch.done() is False
    probe.text_index_ready.emit(2)
    assert watch.done() is False
    probe.text_index_ready.emit(1)
    assert watch.done() is True
    assert watch.status == "ready"


def test_text_failure_and_drop_settle_the_text_watch_and_other_kinds_do_not():
    probe = _FakeProbe()
    watch = TextAnswerWatch(probe, 1)
    probe.probe_failed.emit("tables", 1, "no_headroom")
    probe.probe_dropped.emit("tables", 1)
    probe.probe_failed.emit("text", 2, "crashed")
    assert watch.done() is False
    probe.probe_failed.emit("text", 1, "crashed")
    assert watch.status == "crashed"
    watch.reset()
    assert watch.done() is False
    probe.probe_dropped.emit("text", 1)
    assert watch.status == "dropped"


def test_combined_watch_without_a_text_request_is_done_on_the_table_answer_alone():
    probe = _FakeProbe()
    watch = CombinedAnswerWatch(probe, 1)
    assert watch.done() is False
    probe.tables_ready.emit(1)
    assert watch.done() is True
    assert watch.status == "ready"


def test_combined_watch_with_a_pending_text_job_waits_for_the_text_answer():
    probe = _FakeProbe()
    probe.pending_text = True
    watch = CombinedAnswerWatch(probe, 1)
    probe.tables_ready.emit(1)
    assert watch.done() is False
    probe.pending_text = False
    probe.text_index_ready.emit(1)
    assert watch.done() is True


def test_combined_watch_is_not_done_on_the_text_answer_alone_and_reset_clears_both():
    probe = _FakeProbe()
    watch = CombinedAnswerWatch(probe, 1)
    probe.text_index_ready.emit(1)
    assert watch.done() is False
    probe.tables_ready.emit(1)
    assert watch.done() is True
    watch.reset()
    assert watch.done() is False
    assert watch.text.status is None


class _FrontRunner(StubRunner):
    def submit(self, owner, kind, payloads, *, front=False):
        return super().submit(owner, kind, payloads)


def test_combined_watch_on_the_real_coordinator_waits_for_the_text_job_answer(probe_model):
    runner = _FrontRunner()
    coord = _coordinator(probe_model, runner)
    watch = CombinedAnswerWatch(coord, 1)
    coord.request_tables(1)
    assert coord.request_text_index(1) == "queued"
    runner.complete(runner.order[0], {"v": 2, "status": "no_headroom"})
    assert watch.status == "no_headroom"
    assert watch.done() is False  # the text job is still queued
    text_job = runner.order[1]
    runner.complete(text_job, {"v": 2, "status": "no_headroom"})
    assert watch.text.status == "no_headroom"
    assert watch.done() is True
