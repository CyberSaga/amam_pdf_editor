"""Worker lifetime at exit (Astra W1-W5, round 7): registry protocol and admission, the AST guard
over every controller thread site, W2, the release-once rule (W3), Ext-B refusal, the gate handle."""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from controller.worker_registry import WorkerRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- G: the guard.  Every QThread construction under controller/ is inside a function that -----
# ---- calls ``start_owned`` (so admission can refuse it); no file is exempt. ------------------------


def _is_qthread_base(base: ast.expr, known: set[str]) -> bool:
    name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else None
    return name == "QThread" or name in known


def _subclass_names(tree: ast.AST, seed: set[str]) -> set[str]:
    """Names of classes whose base list (any position) contains QThread or a known subclass."""
    names = set(seed)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                if any(_is_qthread_base(base, names) for base in node.bases):
                    names.add(node.name)
                    changed = True
    return names


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node of ``scope`` without descending into nested function scopes (nested ones are
    yielded themselves but not entered)."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        out.append(node)
        if not isinstance(node, _FUNCTIONS):
            stack.extend(ast.iter_child_nodes(node))
    return out


def thread_site_violations(source: str, known_subclasses: set[str] | None = None) -> list[int]:
    """Line numbers of QThread (or subclass) instantiations that are neither a direct argument of
    ``start_owned`` nor assigned to a name passed to ``start_owned`` in the same function scope.
    Nested functions are separate scopes."""
    tree = ast.parse(source)
    names = _subclass_names(tree, known_subclasses or set())
    names.add("QThread")
    violations: list[int] = []

    def check_scope(scope: ast.AST) -> None:
        nodes = _scope_nodes(scope)
        passed_names: set[str] = set()
        owned_calls: set[int] = set()
        for node in nodes:
            if isinstance(node, ast.Call) and _call_name(node) == "start_owned":
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    if isinstance(arg, ast.Name):
                        passed_names.add(arg.id)
                    elif isinstance(arg, ast.Call):
                        owned_calls.add(id(arg))
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id in passed_names for t in targets):
                    owned_calls.add(id(node.value))
        for node in nodes:
            if isinstance(node, ast.Call) and _call_name(node) in names and id(node) not in owned_calls:
                violations.append(node.lineno)
        for node in nodes:
            if isinstance(node, _FUNCTIONS):
                check_scope(node)

    check_scope(tree)
    return sorted(violations)


def _controller_sources() -> dict[str, str]:
    return {
        str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
        for p in sorted((REPO_ROOT / "controller").rglob("*.py"))
    }


def test_every_controller_thread_construction_site_starts_through_start_owned():
    sources = _controller_sources()
    known: set[str] = set()
    for text in sources.values():
        known |= _subclass_names(ast.parse(text), set())
    offenders = {
        name: lines
        for name, text in sources.items()
        if (lines := thread_site_violations(text, known))
    }
    assert not offenders, f"QThread constructed outside a start_owned function: {offenders}"


def test_guard_fails_a_second_bare_qthread_in_a_file_that_already_calls_start_owned():
    source = (
        "from PySide6.QtCore import QThread\n"
        "def owned(registry):\n"
        "    t = QThread()\n"
        "    registry.start_owned(t, None)\n"
        "def bare():\n"
        "    return QThread()\n"
    )
    assert thread_site_violations(source) == [6]


def test_guard_is_per_site_not_per_function():
    two_in_one = (
        "from PySide6.QtCore import QThread\n"
        "def f(r):\n"
        " t=QThread()\n"
        " r.start_owned(t)\n"
        " b=QThread()\n"
        " b.start()\n"
    )
    assert thread_site_violations(two_in_one) == [5]
    nested = (
        "from PySide6.QtCore import QThread\n"
        "def f(r):\n"
        " def inner():\n"
        "  r.start_owned(QThread())\n"
        " QThread().start()\n"
    )
    assert thread_site_violations(nested) == [5]
    direct = "from PySide6.QtCore import QThread\ndef f(r):\n r.start_owned(QThread(), None)\n"
    assert thread_site_violations(direct) == []


def test_guard_fails_an_instantiated_subclass_with_a_multi_base_list():
    source = (
        "from PySide6.QtCore import QThread\n"
        "class X(QThread, object):\n"
        "    pass\n"
        "class Y(X):\n"
        "    pass\n"
        "def bare():\n"
        "    return X(), Y()\n"
    )
    assert thread_site_violations(source) == [7, 7]
    owned = source + "def ok(r):\n    t = Y()\n    r.start_owned(t, None)\n"
    assert thread_site_violations(owned) == [7, 7]  # the ``ok`` site is fine


def test_guard_fails_module_and_class_level_construction_and_ignores_static_calls():
    source = (
        "from PySide6 import QtCore\n"
        "from PySide6.QtCore import QThread\n"
        "GLOBAL = QtCore.QThread()\n"
        "class C:\n"
        "    attr = QThread()\n"
        "    def f(self):\n"
        "        return QThread.currentThread()\n"
    )
    assert thread_site_violations(source) == [3, 5]


def test_every_known_thread_site_file_is_seen_by_the_guard():
    """The guard walks controller/ recursively: the seven coordinators and the verifier are all in it."""
    names = {Path(name).name for name in _controller_sources()}
    for expected in (
        "search_coordinator.py", "ocr_coordinator.py", "scan_verifier.py", "page_render_coordinator.py",
        "thumbnail_coordinator.py", "text_commit_coordinator.py", "print_coordinator.py", "pdf_controller.py",
    ):
        assert expected in names
        text = (REPO_ROOT / "controller" / expected).read_text(encoding="utf-8")
        assert "start_owned(" in text, f"{expected} starts a QThread without start_owned"


# ---- registry: admission and the owned start --------------------------------------------------


class _Probe:
    """A QThread subclass factory: records whether it ran; optionally holds until released."""

    @staticmethod
    def make(hold: bool = False):
        from PySide6.QtCore import QThread

        release = threading.Event()

        class T(QThread):
            ran = False

            def run(self) -> None:
                T.ran = True
                if hold:
                    release.wait(10)

        return T(), T, release


def test_start_owned_refuses_after_admission_is_closed_and_leaves_the_thread_unstarted(qapp):
    registry = WorkerRegistry()
    registry.close_admission()
    thread, cls, _release = _Probe.make()
    assert registry.start_owned(thread, None) is False
    assert not thread.isRunning()
    assert cls.ran is False
    assert registry.registered() == []
    registry.close_admission()  # idempotent
    registry.open_admission()
    thread2, cls2, _ = _Probe.make()
    assert registry.start_owned(thread2, None) is True
    assert thread2.wait(5000)
    assert cls2.ran is True


def test_start_owned_registers_atomically_and_a_poll_drops_it_once_the_thread_finished(qapp):
    registry = WorkerRegistry()
    cancelled: list[int] = []
    thread, _cls, release = _Probe.make(hold=True)
    assert registry.start_owned(thread, lambda: cancelled.append(1)) is True
    try:
        assert len(registry.alive()) == 1
        registry.cancel_all()
        registry.cancel_all()  # every poll pass cancels again: cheap and idempotent
        assert cancelled == [1, 1]
    finally:
        release.set()
        assert thread.wait(5000)
    assert registry.alive() == []
    assert registry.registered() == []
    # a later start sweeps finished entries too, without any poll
    again, _cls, _release = _Probe.make()
    assert registry.start_owned(again, None) is True
    assert again.wait(5000)
    third, _cls3, _r3 = _Probe.make()
    assert registry.start_owned(third, None) is True
    assert third.wait(5000)
    assert len(registry.registered()) <= 2


def test_start_owned_unregisters_when_start_raises(qapp):
    registry = WorkerRegistry()

    class Boom:
        def start(self) -> None:
            raise RuntimeError("cannot start")

        def isRunning(self) -> bool:
            return False

    with pytest.raises(RuntimeError):
        registry.start_owned(Boom(), None)
    assert registry.registered() == []


def test_worker_never_started_is_not_left_registered_by_a_refusal(qapp):
    registry = WorkerRegistry()
    registry.close_admission()
    for _ in range(3):
        thread, _cls, _ = _Probe.make()
        assert registry.start_owned(thread, None) is False
    assert registry.alive() == [] and registry.registered() == []


def test_alive_until_the_os_thread_exited_even_if_a_direct_finished_handler_blocks(qapp):
    from PySide6.QtCore import Qt

    registry = WorkerRegistry()
    thread, _cls, _ = _Probe.make()
    in_handler, release = threading.Event(), threading.Event()

    def handler() -> None:
        in_handler.set()
        release.wait(10)

    thread.finished.connect(handler, Qt.ConnectionType.DirectConnection)
    assert registry.start_owned(thread, None) is True
    try:
        assert in_handler.wait(5)
        assert thread.isFinished() and not thread.isRunning()
        assert thread.wait(0) is False
        assert len(registry.alive()) == 1, "the OS thread has not exited: the gate must not quit yet"
    finally:
        release.set()
        assert thread.wait(5000)
    assert registry.alive() == []


def test_a_start_still_in_progress_is_never_swept_and_stays_alive_after_admission_closed(qapp):
    from PySide6.QtCore import QThread

    entered, proceed, stop = threading.Event(), threading.Event(), threading.Event()

    class Slow(QThread):
        def start(self) -> None:
            entered.set()
            proceed.wait(10)
            super().start()

        def run(self) -> None:
            stop.wait(10)

    registry = WorkerRegistry()
    thread = Slow()
    results: list[bool] = []
    starter = threading.Thread(target=lambda: results.append(registry.start_owned(thread, None)))
    starter.start()
    try:
        assert entered.wait(5)
        registry.close_admission()  # after the admission check, before start() ran
        assert len(registry.alive()) == 1, "admitted but not yet started: not idle"
        proceed.set()
        starter.join(5)
        assert results == [True]
        assert thread.isRunning()
        assert len(registry.alive()) == 1
    finally:
        proceed.set()
        stop.set()
        starter.join(5)
        thread.wait(5000)
    assert registry.alive() == []


@pytest.fixture()
def mvc_session(monkeypatch, qapp):
    from test_scripts.test_multi_tab_plan import _mvc_session

    yield from _mvc_session(monkeypatch)


def test_refused_starts_leave_the_retirements_unchanged_for_search_and_ocr(mvc_session, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from controller.worker_registry import get_registry
    from test_scripts.test_multi_tab_plan import _make_pdf
    from utils import qt_workers

    model, _view, controller = mvc_session
    controller.open_pdf(str(_make_pdf(tmp_path / "A.pdf", ["alpha-key"])))
    monkeypatch.setattr(model.tools.ocr, "availability", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(controller, "show_error", lambda *a, **k: None, raising=False)
    registry = get_registry()
    before = len(qt_workers._retirements)
    registry.close_admission()
    try:
        for _ in range(3):
            controller.search_text("alpha")
        for _ in range(2):
            controller.start_ocr(SimpleNamespace(page_indices=[0], languages=["en"], device="cpu"))
    finally:
        registry.open_admission()
    assert len(qt_workers._retirements) == before


def test_release_of_a_refused_retirement_is_the_contract_of_retire_worker_with(qapp):
    from PySide6.QtCore import QObject, QThread

    from utils import qt_workers

    before = len(qt_workers._retirements)
    retirement = qt_workers.retire_worker_with(QThread(), QObject())
    assert len(qt_workers._retirements) == before + 1
    retirement.release()
    assert len(qt_workers._retirements) == before




class _Entry:
    def __init__(self, cancel_exc: Exception | None = None, alive: bool = True) -> None:
        self.cancel_exc = cancel_exc
        self.is_alive = alive
        self.cancels = 0

    def cancel(self) -> None:
        self.cancels += 1
        if self.cancel_exc is not None:
            raise self.cancel_exc

    def alive(self) -> bool:
        return self.is_alive


def test_cancel_all_cancels_each_entry_once_and_alive_drops_finished_ones():
    registry = WorkerRegistry()
    running, done = _Entry(), _Entry(alive=False)
    registry.register(running)
    registry.register(done)
    registry.cancel_all()
    assert running.cancels == 1 and done.cancels == 1
    assert registry.alive() == [running]
    assert registry.registered() == [running]


def test_w2_a_non_deletion_runtime_error_does_not_make_a_worker_done():
    registry = WorkerRegistry()
    entry = _Entry(cancel_exc=RuntimeError("something else entirely"))
    registry.register(entry)
    registry.cancel_all()
    assert registry.alive() == [entry], "a RuntimeError from cancel is not proof the thread ended"


def test_w2_an_alive_that_raises_counts_as_running():
    registry = WorkerRegistry()

    class Broken:
        def cancel(self) -> None:
            pass

        def alive(self) -> bool:
            raise RuntimeError("boom")

    broken = Broken()
    registry.register(broken)
    assert registry.alive() == [broken]


def test_w2_thread_entry_detects_deletion_with_shiboken_not_exception_text(qapp):
    from PySide6.QtCore import QThread
    import shiboken6
    from controller.worker_registry import _ThreadEntry

    registry = WorkerRegistry()
    thread = QThread()
    entry = _ThreadEntry(thread, None)
    entry.started = True  # start_owned sets this once ``start()`` returned
    registry.register(entry)
    assert registry.alive() == []  # started-and-finished (never ran): wait(0) is True
    registry.register(entry)
    shiboken6.delete(thread)
    assert registry.alive() == []
    assert registry.registered() == []


# ---- W3: a closed secondary window releases its context, once --------------------------------

def _make_pdf(path: Path) -> Path:
    import fitz

    with fitz.open() as doc:
        for number in range(2):
            doc.new_page(width=300, height=400).insert_text((36, 72), f"T {number}", fontsize=14)
        doc.save(path)
    return path


def _detach_secondary(qapp, tmp_path, monkeypatch):
    import time

    import main as main_module
    from PySide6.QtCore import QPoint

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    a, b = _make_pdf(tmp_path / "a.pdf"), _make_pdf(tmp_path / "b.pdf")
    startup = main_module.run(argv=[str(a), str(b)], start_event_loop=False)

    def pump(ms: int) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)

    pump(500)
    sid_b = startup["model"].get_active_session_id()
    rect = startup["view"].frameGeometry()
    startup["controller"].detach_document_session(sid_b, QPoint(rect.right() + 400, rect.top() + 50))
    pump(500)
    assert len(startup["secondary_windows"]) == 1
    return startup, startup["secondary_windows"][0], pump


def _finish(qapp, startup, pump) -> None:
    for ctx in list(startup["secondary_windows"]):
        ctx["view"].close()
    startup["view"].close()
    pump(100)
    qapp.setStyleSheet("")
    _reopen_admission()


def test_w3_closing_a_secondary_window_releases_its_context_exactly_once(qapp, tmp_path, monkeypatch):
    startup, secondary, pump = _detach_secondary(qapp, tmp_path, monkeypatch)
    calls: list[int] = []
    controller = secondary["controller"]
    real = controller.retire_background
    controller.retire_background = lambda: (calls.append(1), real())[1]
    try:
        secondary["view"].close()  # views lack WA_DeleteOnClose: `destroyed` never fires
        pump(100)
        assert calls == [1]
        assert secondary not in startup["secondary_windows"]
        secondary["view"].closed.emit()  # idempotent: a second trigger does nothing more
        assert calls == [1]
    finally:
        _finish(qapp, startup, pump)


def test_w3_an_ignored_close_does_not_release_the_context(qapp, tmp_path, monkeypatch):
    startup, secondary, pump = _detach_secondary(qapp, tmp_path, monkeypatch)
    calls: list[int] = []
    controller = secondary["controller"]
    real = controller.retire_background
    controller.retire_background = lambda: (calls.append(1), real())[1]
    controller.handle_app_close = lambda event: event.ignore()
    try:
        secondary["view"].close()
        pump(100)
        assert calls == []
        assert secondary in startup["secondary_windows"]
    finally:
        del controller.handle_app_close
        _finish(qapp, startup, pump)


def _reopen_admission() -> None:
    from controller.worker_registry import get_registry
    from view import ext_b_subset_worker

    get_registry().open_admission()
    ext_b_subset_worker.allow_new_ext_b_threads()


# ---- F: one idempotent release per window context (accepted close, destroyed, promotion) ---------


def test_f_a_b_c_promotion_releases_each_context_exactly_once(qapp, tmp_path, monkeypatch):
    import main as main_module
    from PySide6.QtCore import QPoint

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    paths = [_make_pdf(tmp_path / f"{n}.pdf") for n in "abc"]
    startup = main_module.run(argv=[str(p) for p in paths], start_event_loop=False)

    def pump(ms: int) -> None:
        import time

        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)

    try:
        pump(500)
        sids = list(startup["model"].session_ids)
        assert len(sids) == 3
        rect = startup["view"].frameGeometry()
        for offset, sid in zip((400, 900), sids[1:]):
            startup["controller"].detach_document_session(sid, QPoint(rect.right() + offset, rect.top() + 50))
            pump(400)
        assert len(startup["secondary_windows"]) == 2
        b_ctx = startup["secondary_windows"][0]
        counts = {"retire": 0, "close": 0, "search": 0, "ocr": 0}
        b_controller, b_model = b_ctx["controller"], b_ctx["model"]
        real_retire, real_close = b_controller.retire_background, b_model.close
        b_controller.retire_background = lambda: (counts.__setitem__("retire", counts["retire"] + 1), real_retire())[1]
        b_model.close = lambda: (counts.__setitem__("close", counts["close"] + 1), real_close())[1]
        real_search, real_ocr = b_controller._cancel_search, b_controller.cancel_ocr
        b_controller._cancel_search = lambda: (counts.__setitem__("search", counts["search"] + 1), real_search())[1]
        b_controller.cancel_ocr = lambda: (counts.__setitem__("ocr", counts["ocr"] + 1), real_ocr())[1]

        startup["view"].close()  # A closes: B is promoted (A released)
        pump(300)
        assert startup["view"] is b_ctx["view"]
        assert counts["retire"] == 0
        b_ctx["view"].close()  # B closes: `closed` releases B, C is promoted (B must not release twice)
        pump(300)
        assert counts["retire"] == 1, counts
        assert counts["close"] == 1, counts
        assert counts["search"] >= 1 and counts["ocr"] >= 1, "release must cancel search and OCR"
    finally:
        for ctx in list(startup["secondary_windows"]):
            ctx["view"].close()
        startup["view"].close()
        pump(100)
        qapp.setStyleSheet("")
        _reopen_admission()


# ---- D: Ext-B refuses new threads at shutdown and no longer blocks on aboutToQuit ---------------


def test_d_ext_b_refuses_new_threads_after_shutdown_was_requested(qapp):
    from view import ext_b_subset_worker as module

    module.refuse_new_ext_b_threads()
    try:
        service = module.ExtBSubsetService()
        service.request("<p>x</p>")
        assert module.live_ext_b_subset_threads() == []
        assert service._thread is None, "a refused request must not leave the service waiting on a thread"
    finally:
        module.allow_new_ext_b_threads()


def test_d_ext_b_no_longer_blocks_the_gui_thread_in_a_quit_hook(qapp, monkeypatch):
    from PySide6.QtCore import SIGNAL
    from view import ext_b_subset_worker as module

    monkeypatch.setattr(module, "warm_ext_b_subsets", lambda html: None)
    before = qapp.receivers(SIGNAL("aboutToQuit()"))
    service = module.ExtBSubsetService()
    service.request("<p>x</p>")
    for thread in module.live_ext_b_subset_threads():
        assert thread.wait(5000)
    assert qapp.receivers(SIGNAL("aboutToQuit()")) == before, "Ext-B must not hook aboutToQuit (blocking wait)"
    service.close()


# ---- E: run(start_event_loop=False) hands its caller a quit-gate handle --------------------------


def test_e_startup_context_exposes_a_quit_gate_with_request_and_done(qapp, monkeypatch):
    import time

    import main as main_module
    from controller.worker_registry import get_registry

    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    startup = main_module.run(argv=[], start_event_loop=False)
    gate = startup["quit_gate"]
    thread, cls, release = _Probe.make(hold=True)
    try:
        assert gate.done() is False, "nothing was requested yet"
        assert get_registry().start_owned(thread, None) is True
        gate.request()
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)
        assert gate.done() is False, "a worker is still running"
        late, late_cls, _ = _Probe.make()
        assert get_registry().start_owned(late, None) is False, "admission is closed once a quit was requested"
        release.set()
        assert thread.wait(5000)
        end = time.monotonic() + 5
        while not gate.done() and time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)
        assert gate.done() is True
        assert late_cls.ran is False
    finally:
        release.set()
        thread.wait(5000)
        startup["view"].close()
        qapp.processEvents()
        qapp.setStyleSheet("")
        _reopen_admission()
