"""Shared GUI-test teardown (round 7 / ISO-2, round 17 / GATE16-1b).

``view.close()`` only hides a ``PDFView``: the view, its action bar, its ``live_text_strip`` (which holds the
inline editor until ``unbind()``) and the editor itself -- a visible top-level widget -- stay alive for the rest
of the process, and every later ``processEvents`` services them.  A harness that opens a real editor must
finalize it, close, ``deleteLater()`` and flush ``DeferredDelete``.

``view.close()`` is also *vetoed* by ``PDFController.handle_app_close`` while a print / optimize job runs, a
render or thumbnail join times out, or the unsaved-changes prompt is cancelled.  A test that simulates one of
those (``monkeypatch`` stays active until AFTER the fixture teardown) then left a still-visible ``PDFView`` for
every later test of the process (GATE16-1b: three I-beam tests of another module failed on it).
``dispose_pdf_view`` therefore hides and destroys the view whatever the close did, and
``snapshot_visible_gui`` / ``leaked_gui_since`` are the guard (an autouse fixture) that names the next leak.
"""

from __future__ import annotations

import gc
import time
import weakref
from typing import Any

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


def flush_deferred_deletes() -> None:
    """Run every pending ``deleteLater`` (``processEvents`` alone does not deliver ``DeferredDelete``)."""
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(3):
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
    gc.collect()


def _settle_zero_delay_callbacks(ms: int = 50) -> None:
    """Pump the event loop for ``ms`` so every queued cross-thread signal and the zero-delay timer it posts is
    delivered while the C++ objects they touch still exist.

    A coordinator that joined its worker thread during ``close()`` still has ``_worker_finished`` queued; that
    slot posts ``QTimer.singleShot(0, lambda: self._thread_finished(token))``, and the lambda calls
    ``thread.wait()`` on a ``QThread`` that is a child of the view.  One ``processEvents()`` delivers the signal
    only; the timer would then fire AFTER ``deleteLater()`` had destroyed the thread ("Internal C++ object
    (QThread) already deleted", GATE16-1b: ``test_13`` .. ``test_16`` of ``test_multi_tab_plan.py``)."""
    app = QApplication.instance()
    if app is None:
        return
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def dispose_pdf_view(view: Any, controller: Any = None, model: Any = None) -> None:
    """Tear a harness ``PDFView`` (and its controller preview session / model) down completely.

    Order matters: the inline editor is discarded FIRST, while the preview session is still the one the
    editor's debounce timer would restart (a late keystroke would otherwise begin a new, never-joined
    session -- TEARDOWN-1); then the session ends, the model closes, the view is closed and destroyed.

    The destruction does not depend on ``view.close()`` being carried out: ``closeEvent`` routes to
    ``handle_app_close``, which ignores the close while a test's simulated running job (or a patched prompt /
    join timeout) is still in force, and an ignored close leaves the window visible (GATE16-1b).  The view is
    hidden explicitly and ``deleteLater()``-ed regardless."""
    try:
        view.finalize_text_edit_for_close(save=False)
    except Exception:
        pass
    if controller is not None:
        try:
            controller._end_text_edit_plan_preview_session()
        except Exception:
            pass
    if model is not None:
        model.close()
    try:
        view.close()
        # Let queued zero-delay callbacks that were bound to the view (``QTimer.singleShot(0, self.method)``
        # in ``PDFView.__init__`` and the like) run while the C++ view still exists: PySide gives a plain bound
        # method no receiver context, so one delivered after the delete raises "Internal C++ object already
        # deleted" (GATE15-3).  One ``processEvents()`` is not enough for a callback that a queued signal posts
        # (a joined coordinator thread's ``finished``): pump for a short while (GATE16-1b).
        _settle_zero_delay_callbacks()
        view.hide()  # a vetoed close (see the module docstring) leaves the window visible
        view.deleteLater()
    except RuntimeError:  # already destroyed
        pass
    flush_deferred_deletes()


def _visible_gui_toplevels() -> list[Any]:
    """The visible top-level ``PDFView`` / inline-editor widgets the process owns right now."""
    from view.pdf_view import PDFView
    from view.text_editing import PreviewBackedInlineTextEditor

    app = QApplication.instance()
    if app is None:
        return []
    found: list[Any] = []
    for widget in app.topLevelWidgets():
        try:
            if isinstance(widget, (PDFView, PreviewBackedInlineTextEditor)) and widget.isVisible():
                found.append(widget)
        except RuntimeError:  # C++ object deleted under the wrapper
            continue
    return found


def snapshot_visible_gui() -> list[weakref.ref]:
    """Weak references to the visible top-level GUI widgets that exist BEFORE a test (what it did not leave)."""
    return [weakref.ref(widget) for widget in _visible_gui_toplevels()]


def leaked_gui_since(before: list[weakref.ref]) -> list[str]:
    """What a test left behind since ``before`` (a :func:`snapshot_visible_gui` result), cleaned up.

    A visible top-level ``PDFView`` / inline editor that is new since the snapshot, or an application
    override cursor, outlives the test and changes every later test's mouse delivery and cursor (GATE16-1b:
    a stray ``PDFView`` kept the open-hand cursor on the next test's viewport).  Each finding is returned as
    one sentence and then removed (hidden / restored), so the first leaker is reported once instead of
    poisoning every following test.  An empty list means the test cleaned up after itself."""
    flush_deferred_deletes()
    known = [ref() for ref in before]
    problems: list[str] = []
    for widget in _visible_gui_toplevels():
        if any(widget is old for old in known):
            continue
        try:
            geometry = widget.geometry()
            where = f"({geometry.x()},{geometry.y()},{geometry.width()},{geometry.height()})"
            problems.append(f"visible top-level {type(widget).__name__} {where} outlived the test")
            widget.hide()
        except RuntimeError:  # destroyed while being inspected
            continue
    cursor_findings = 0
    while QApplication.overrideCursor() is not None and cursor_findings < 32:
        cursor_findings += 1
        problems.append("an application override cursor outlived the test")
        QApplication.restoreOverrideCursor()
    return problems
