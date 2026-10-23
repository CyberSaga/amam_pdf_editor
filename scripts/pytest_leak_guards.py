"""Leak-guard pytest plugin: three autouse fixtures that make the LEAKER red (Phase 2 of
``plans/test-suite-never-hangs.md``).

* ``gui``    (``_leak_guard_gui``)    -- a visible top-level ``PDFView`` / inline editor (or an override
  cursor) outlived the test.  Uses ``test_scripts/qt_teardown.py``.
* ``thread`` (``_leak_guard_thread``) -- a ``QThread`` started during the test is still running.  Started
  threads are tracked through a one-time wrap of ``QThread.start``.  The guard never stops, quits,
  terminates or waits on a thread (that can hang; the runner's stall kill is the safety net).
* ``modal``  (``_leak_guard_modal``)  -- ``QMessageBox.exec/information/warning/critical/question`` and
  ``QDialog.exec`` raise :class:`UnexpectedModalDialog` unless the test patches the call itself or carries
  ``@pytest.mark.real_modal``.  The attempt is also recorded, because PySide6 prints and swallows an
  exception raised inside a slot that C++ invoked; teardown then reports it, unless the test already
  failed in setup or call WITH that exception (reported once).  Zero-delay callbacks the leaker armed are
  run inside its own teardown, so they cannot fire into the next test.

Each guard sits behind an allowlist of test module FILE NAMES that may only shrink (``_KNOWN_GUI_LEAKERS``,
``_KNOWN_THREAD_LEAKERS``): a listed module only produces a :class:`LeakGuardWarning`.  The modal guard has
no allowlist.  Setting ``PDF_EDITOR_LEAK_GUARD_REPORT`` to a file path switches every guard to record mode
(one JSON line per finding; record mode never ADDS a failure, but a direct modal call still raises, so
that test fails once and its attempt is written down), which is how the allowlists are discovered.

Loaded for the real suite by ``pytest_plugins`` in ``test_scripts/conftest.py``.  Qt is imported lazily and
every guard is inert when PySide6 is unavailable; a test in the pure lane only pays a ``PySide6.QtWidgets``
import check and a few dictionary lookups.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import warnings
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

logger = logging.getLogger(__name__)

# qt_teardown.py lives in test_scripts/ (no package __init__); it is imported lazily inside the fixtures.
_TEST_SCRIPTS = str(Path(__file__).resolve().parents[1] / "test_scripts")
if _TEST_SCRIPTS not in sys.path:
    sys.path.insert(0, _TEST_SCRIPTS)

REPORT_ENV = "PDF_EDITOR_LEAK_GUARD_REPORT"

_REAL_MODAL_MARKER = (
    "real_modal: the test runs a genuine modal exec() (QDialog/QMessageBox) on purpose; the modal guard stands down"
)


class UnexpectedModalDialog(RuntimeError):
    """A test reached a modal dialog call it neither patched nor marked ``real_modal``."""


class LeakGuardWarning(UserWarning):
    """A leak that is excused (allowlisted module) or merely recorded (record mode)."""


# Test module FILE NAMES (e.g. "test_foo.py").  The orchestrator fills these from the discovery run; a guard
# test requires every name to exist and entries may only be removed.
_KNOWN_GUI_LEAKERS: frozenset[str] = frozenset(
    {  # discovery run 2026-10-23: a visible PreviewBackedInlineTextEditor outlived the test
        "test_text_commit_apply_by_token.py",
        "test_text_commit_no_silent_legacy.py",
        "test_text_commit_plan_preview_no_css.py",
        "test_text_edit_rotated_page_gui.py",
    }
)
_KNOWN_THREAD_LEAKERS: frozenset[str] = frozenset()

GUARDED_MODAL_CALLS: tuple[tuple[str, str], ...] = (
    ("QMessageBox", "exec"),
    ("QMessageBox", "information"),
    ("QMessageBox", "warning"),
    ("QMessageBox", "critical"),
    ("QMessageBox", "question"),
    ("QDialog", "exec"),
)
_STATIC_MODAL_CALLS = frozenset({"information", "warning", "critical", "question"})


# --------------------------------------------------------------------------- outcome of a finding


def module_key(item: Any) -> str:
    """The allowlist key of a test: the base name of its file."""
    return Path(str(item.path)).name


def report_finding(guard: str, item: Any, detail: str, *, allowlist: frozenset[str]) -> None:
    """Decide the outcome of one finding: record it, warn about it, or fail the test (teardown ERROR)."""
    message = f"leak guard [{guard}]: {detail}"
    target = os.environ.get(REPORT_ENV)
    if target:
        entry = {
            "guard": guard,
            "nodeid": item.nodeid,
            "module": module_key(item),
            "detail": detail,
            "pid": os.getpid(),
        }
        try:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            logger.warning("leak guard report write to %s failed", target, exc_info=True)
        warnings.warn(message, LeakGuardWarning, stacklevel=2)
        return
    if module_key(item) in allowlist:
        warnings.warn(message, LeakGuardWarning, stacklevel=2)
        return
    pytest.fail(message, pytrace=False)


def _qt_widgets_available() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


# --------------------------------------------------------------------------- guard 1: gui


@pytest.fixture(autouse=True)
def _leak_guard_gui(request: pytest.FixtureRequest) -> Iterator[None]:
    # No QtWidgets module loaded means no QApplication can exist: stand down without importing anything.
    if "PySide6.QtWidgets" not in sys.modules:
        yield
        return
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        yield
        return
    try:
        import qt_teardown

        before = qt_teardown.snapshot_visible_gui()
    except ImportError:  # `view` is not importable (a foreign rootdir): nothing to guard
        yield
        return
    yield
    known = [ref() for ref in before]
    if not any(not any(widget is old for old in known) for widget in qt_teardown._visible_gui_toplevels()):
        # Common case: nothing new is visible.  An override cursor with no new window is only noticed by
        # the full check, so look at it here too (cheap, no event processing).
        if QApplication.overrideCursor() is None:
            return
    problems = qt_teardown.leaked_gui_since(before)
    if problems:
        report_finding("gui", request.node, "; ".join(problems), allowlist=_KNOWN_GUI_LEAKERS)


# --------------------------------------------------------------------------- guard 2: thread

# id(thread) -> weakref; the callback drops the entry when the wrapper is collected.
_STARTED: dict[int, weakref.ref] = {}
_original_start: Any = None
# A worker that signalled `finished` has its `thread.quit` delivered queued (the QThread lives in the main
# thread) and still has to be scheduled to leave exec(): give it a bounded moment, never an unbounded wait.
_THREAD_SETTLE_S = 0.3


def _register_started(thread: Any) -> None:
    key = id(thread)
    if key in _STARTED and _STARTED[key]() is thread:
        return

    def _forget(ref: weakref.ref, key: int = key) -> None:
        if _STARTED.get(key) is ref:
            del _STARTED[key]

    try:
        _STARTED[key] = weakref.ref(thread, _forget)
    except TypeError:  # pragma: no cover - a wrapper that cannot be weak-referenced is not tracked
        logger.debug("QThread wrapper %r cannot be weak-referenced", type(thread))


def _install_start_wrapper() -> None:
    global _original_start
    if _original_start is not None:
        return
    try:
        from PySide6.QtCore import QThread
    except ImportError:
        return
    original = QThread.start

    def start(self: Any, *args: Any, **kwargs: Any) -> Any:
        _register_started(self)
        return original(self, *args, **kwargs)

    start.__name__ = getattr(original, "__name__", "start")
    start.__doc__ = getattr(original, "__doc__", None)
    QThread.start = start  # type: ignore[method-assign]
    _original_start = original


def _alive_started() -> list[Any]:
    """The tracked threads whose Python wrapper still exists."""
    alive = []
    for ref in list(_STARTED.values()):
        thread = ref()
        if thread is not None:
            alive.append(thread)
    return alive


def _is_running(thread: Any) -> bool:
    try:
        return bool(thread.isRunning())
    except RuntimeError:  # the C++ object is gone: not alive
        return False


def _thread_label(thread: Any) -> str:
    try:
        name = thread.objectName()
    except RuntimeError:
        name = ""
    return name or type(thread).__name__


@pytest.fixture(autouse=True)
def _leak_guard_thread(request: pytest.FixtureRequest) -> Iterator[None]:
    if _original_start is None:  # PySide6 unavailable or the wrap was not installed
        yield
        return
    running_before = {id(t) for t in _alive_started() if _is_running(t)}
    yield
    candidates = [t for t in _alive_started() if id(t) not in running_before and _is_running(t)]
    if not candidates:
        return
    import qt_teardown

    qt_teardown.flush_deferred_deletes()
    still_running = [t for t in candidates if _is_running(t)]
    if still_running:
        from PySide6.QtCore import QCoreApplication

        deadline = time.monotonic() + _THREAD_SETTLE_S
        while still_running and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
            still_running = [t for t in still_running if _is_running(t)]
    for thread in still_running:
        detail = f"QThread {_thread_label(thread)} started during the test is still running"
        report_finding("thread", request.node, detail, allowlist=_KNOWN_THREAD_LEAKERS)


# --------------------------------------------------------------------------- guard 3: modal

# Set when a phase of the test (setup or call) ended with UnexpectedModalDialog: pytest reports that failure
# (or the xfail) itself, so the teardown must not report the same attempt a second time.
_MODAL_RAISED = pytest.StashKey[bool]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    yield
    if call.excinfo is not None and isinstance(call.excinfo.value, UnexpectedModalDialog):
        item.stash[_MODAL_RAISED] = True


def _blocked_call(cls_name: str, name: str, attempts: list[str], nodeid: str) -> Any:
    label = f"{cls_name}.{name}"

    def blocked(*args: Any, **kwargs: Any) -> Any:
        attempts.append(label)
        raise UnexpectedModalDialog(
            f"leak guard [modal]: {label} was called by {nodeid}; "
            "monkeypatch it in the test or mark the test real_modal"
        )

    return staticmethod(blocked) if name in _STATIC_MODAL_CALLS else blocked


@pytest.fixture(autouse=True)
def _leak_guard_modal(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("real_modal") is not None or not _qt_widgets_available():
        yield
        return
    from PySide6 import QtWidgets

    attempts: list[str] = []
    for cls_name, name in GUARDED_MODAL_CALLS:
        monkeypatch.setattr(
            getattr(QtWidgets, cls_name), name, _blocked_call(cls_name, name, attempts, request.node.nodeid)
        )
    yield
    if not attempts:
        return
    # The leaker may have armed zero-delay callbacks (QTimer.singleShot(0, ...)) before it reached the modal;
    # run them here, inside the leaker, instead of letting them fire into the next test's event pump.
    import qt_teardown

    qt_teardown._settle_zero_delay_callbacks()
    if request.node.stash.get(_MODAL_RAISED, False) and not os.environ.get(REPORT_ENV):
        return  # the exception reached setup or the test body: it already failed (or xfailed), once
    detail = "modal dialog call(s) attempted and swallowed inside Qt: " + ", ".join(attempts)
    report_finding("modal", request.node, detail, allowlist=frozenset())


# --------------------------------------------------------------------------- plugin hooks


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", _REAL_MODAL_MARKER)
    _install_start_wrapper()
