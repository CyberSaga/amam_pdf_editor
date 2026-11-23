"""Card B3: the index worker of ``VectorEditCoordinator`` (done / refused / cancel, registry-owned,
no start once admission is closed, generation discards late answers)."""
from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from controller.vector_edit_coordinator import VectorEditCoordinator
from controller.worker_registry import get_registry
from test_scripts.test_worker_registry_gate import thread_site_violations
from model.vector_paths import VectorPageRefused

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAME = (1.0, 0.0, 0.0, -1.0, 0.0, 100.0)
STREAM = b"10 10 m 90 90 l S\n"


class _Model:
    def __init__(self, result=None, raises: BaseException | None = None) -> None:
        self.result = result if result is not None else ((STREAM,), FRAME)
        self.raises = raises
        self.calls: list[int] = []

    def vector_page_source(self, page_num: int):
        self.calls.append(page_num)
        if self.raises is not None:
            raise self.raises
        return self.result


class _Recorder:
    def __init__(self, coordinator: VectorEditCoordinator) -> None:
        self.done: list[tuple[int, object]] = []
        self.refused: list[tuple[int, str]] = []
        self.progress: list[tuple[int, int]] = []
        coordinator.index_done.connect(lambda page, index: self.done.append((page, index)))
        coordinator.index_refused.connect(lambda page, code: self.refused.append((page, code)))
        coordinator.index_progress.connect(lambda d, t: self.progress.append((d, t)))


def _make(model) -> VectorEditCoordinator:
    return VectorEditCoordinator(SimpleNamespace(model=model), in_process=True)


def _drain(qapp, coordinator: VectorEditCoordinator, timeout_s: float = 20.0) -> None:
    """Pump until the coordinator holds no worker and the registry reports no live thread."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        qapp.processEvents()
        if not coordinator.busy and not get_registry().alive():
            qapp.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("worker did not finish")


@pytest.fixture(autouse=True)
def _admission_open():
    get_registry().open_admission()
    yield
    get_registry().open_admission()


def test_a_page_is_indexed_off_the_calling_thread_and_announced(qapp):
    model = _Model()
    coordinator = _make(model)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(3) is True
    assert coordinator.busy
    _drain(qapp, coordinator)
    assert model.calls == [3]
    assert rec.refused == []
    assert len(rec.done) == 1
    page, index = rec.done[0]
    assert page == 3
    assert len(index.paths) == 1
    assert rec.progress and rec.progress[-1][0] == rec.progress[-1][1]  # terminal progress event


def test_the_worker_is_registered_with_the_application_registry(qapp):
    coordinator = _make(_Model())
    _Recorder(coordinator)
    seen: list[int] = []
    original = get_registry().start_owned

    def spy(thread, cancel=None, *, dispose=False):
        seen.append(1)
        assert dispose is True and callable(cancel)
        return original(thread, cancel, dispose=dispose)

    get_registry().start_owned = spy  # type: ignore[method-assign]
    try:
        coordinator.ensure_index(1)
        assert any(w.__class__.__name__ == "_ThreadEntry" for w in get_registry().registered())
    finally:
        del get_registry().start_owned
    assert seen == [1]
    _drain(qapp, coordinator)


def test_no_worker_starts_once_admission_is_closed(qapp):
    model = _Model()
    coordinator = _make(model)
    rec = _Recorder(coordinator)
    get_registry().close_admission()
    assert coordinator.ensure_index(1) is False
    assert not coordinator.busy
    qapp.processEvents()
    assert rec.done == [] and rec.refused == []
    assert get_registry().registered() == []


def test_closed_admission_never_reads_the_model_nor_announces_a_refusal(qapp):
    model = _Model(raises=IndexError("page"))
    coordinator = _make(model)
    rec = _Recorder(coordinator)
    get_registry().close_admission()
    assert coordinator.ensure_index(1) is False
    qapp.processEvents()
    assert model.calls == []
    assert rec.refused == [] and rec.done == []
    assert not coordinator.busy


def test_busy_holds_while_a_superseded_worker_is_still_running(qapp, monkeypatch):
    import threading

    import model.vector_paths.scan as scan_mod

    release = threading.Event()
    entered = threading.Event()
    real = scan_mod.scan_page
    calls: list[int] = []

    def gated(streams, frame, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(20.0)
        return real(streams, frame, **kwargs)

    monkeypatch.setattr(scan_mod, "scan_page", gated)
    coordinator = _make(_Model())
    rec = _Recorder(coordinator)
    try:
        coordinator.ensure_index(1)
        assert entered.wait(10.0)
        coordinator.ensure_index(2)  # supersedes: the first worker is cancelled but still inside scan_page
        end = time.monotonic() + 10.0
        while time.monotonic() < end and not rec.done:
            qapp.processEvents()
            time.sleep(0.005)
        assert [p for p, _ in rec.done] == [2]
        for _ in range(20):
            qapp.processEvents()
            time.sleep(0.005)
        assert coordinator.busy  # the superseded worker has not exited
    finally:
        release.set()
    _drain(qapp, coordinator)
    assert not coordinator.busy


def test_a_refusal_of_the_model_is_announced_without_a_thread(qapp):
    model = _Model(raises=VectorPageRefused("NO_FRAME", "x"))
    coordinator = _make(model)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(2) is False
    qapp.processEvents()
    assert rec.refused == [(2, "NO_FRAME")]
    assert rec.done == [] and not coordinator.busy


def test_an_unexpected_model_error_is_a_scan_error_refusal(qapp):
    coordinator = _make(_Model(raises=IndexError("page")))
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(9) is False
    qapp.processEvents()
    assert rec.refused == [(9, "SCAN_ERROR")]


def test_a_scanner_refusal_in_the_worker_is_announced(qapp):
    # an unterminated array at the end of the page is a SCAN_ERROR refusal from the scanner itself
    coordinator = _make(_Model(result=((b"[ 1 2",), FRAME)))
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is True
    _drain(qapp, coordinator)
    assert rec.done == []
    assert rec.refused == [(1, "SCAN_ERROR")]


def test_a_frame_the_scanner_rejects_is_a_refusal(qapp):
    coordinator = _make(_Model(result=((STREAM,), (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))))
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    _drain(qapp, coordinator)
    assert rec.refused == [(1, "NO_FRAME")]


def test_cancel_discards_the_answer_and_stops_the_worker(qapp):
    coordinator = _make(_Model(result=((b"10 10 m 90 90 l S\n" * 400_000,), FRAME)))
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    coordinator.cancel()
    _drain(qapp, coordinator)
    assert rec.done == [] and rec.refused == []


def test_a_cancelled_worker_never_returns_an_index_even_before_it_starts_scanning(qapp):
    from controller.vector_edit_coordinator import _IndexWorker

    worker = _IndexWorker((STREAM,), FRAME, 7)
    got: list[object] = []
    worker.done.connect(lambda *a: got.append(("done", a)))
    worker.refused.connect(lambda *a: got.append(("refused", a)))
    worker.request_cancel()
    worker.request_cancel()  # idempotent
    worker.run()  # synchronous: the body, not the thread
    assert got == []


def test_a_newer_request_supersedes_the_older_one(qapp):
    model = _Model()
    coordinator = _make(model)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    coordinator.ensure_index(2)
    _drain(qapp, coordinator)
    assert [p for p, _ in rec.done] == [2]


def test_state_is_released_after_the_thread_finished(qapp):
    coordinator = _make(_Model())
    _Recorder(coordinator)
    coordinator.ensure_index(1)
    _drain(qapp, coordinator)
    assert not coordinator.busy
    assert get_registry().registered() == []


def test_cancel_without_a_worker_is_a_noop(qapp):
    coordinator = _make(_Model())
    coordinator.cancel()
    assert not coordinator.busy


def test_the_module_obeys_the_thread_site_guard_and_never_imports_the_view():
    source = (REPO_ROOT / "controller" / "vector_edit_coordinator.py").read_text(encoding="utf-8")
    assert thread_site_violations(source, {"_IndexWorker"}) == []
    tree = ast.parse(source)
    modules = [
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    ]
    assert not [m for m in modules if m.startswith("view") or m == "threading"]
    assert "threading.Thread" not in source
