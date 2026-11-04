"""Owner-scoped deferred callbacks for Qt code (F16-VIEW-TIMER).

``QTimer.singleShot(ms, callable)`` has no receiver context in PySide: a callable bound to a widget still runs
after that widget's C++ object has been destroyed and raises ``RuntimeError: Internal C++ object ... already
deleted`` (or worse).  :func:`call_later` parents the one-shot timer to the *owner* instead, so destroying the
owner destroys the pending timer and the callback is simply never delivered.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


def call_later(owner: QObject, delay_ms: int, callback: Callable[[], object]) -> QTimer:
    """Run ``callback()`` once after ``delay_ms`` unless ``owner`` is destroyed first.

    Must be called on ``owner``'s thread (the timer is its child).  The timer deletes itself after firing so a
    long-lived owner does not accumulate dead children.  Returns the timer so a caller may ``stop()`` it.
    """
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.timeout.connect(timer.deleteLater)
    timer.start(max(0, int(delay_ms)))
    return timer
