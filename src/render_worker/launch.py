"""Argv for the app's own child processes, frozen or not.

In a frozen build (PyInstaller) ``sys.executable`` is the app exe, not a Python interpreter, so
``-m <module>`` would make the app run its own CLI parser (usage error, exit 2). The frozen child
is the app exe re-run with a flag that ``main.py`` dispatches before any Qt import. Every launch site must come through here
(test_child_launch_guard.py).
"""
from __future__ import annotations

import sys

# kind -> (module for ``python -m``, flag the frozen app exe dispatches on)
_CHILDREN = {
    "render": ("src.render_worker.worker_main", "--render-worker"),
    "print": ("src.printing.helper_main", "--print-helper"),
}


def child_launch(
    kind: str, extra_args: list[str] | None = None, *, python_executable: str | None = None
) -> tuple[str, list[str]]:
    """Return ``(program, args)`` for a child of ``kind`` (``render`` or ``print``)."""
    if kind not in _CHILDREN:
        raise ValueError(f"unknown child kind: {kind!r}")
    module, flag = _CHILDREN[kind]
    program = python_executable or sys.executable
    head = [flag] if getattr(sys, "frozen", False) else ["-m", module]
    return program, [*head, *(extra_args or [])]
