"""Argv for the app's own child processes, frozen or not.

In a frozen build (PyInstaller) ``sys.executable`` is the app exe, not a Python interpreter, so
``-m <module>`` (or a script path) would make the app run its own CLI parser (usage error, exit 2).
The frozen child is the app exe re-run with a flag that ``main.py`` dispatches before any Qt import
(``--render-worker``, ``--print-helper``, ``--recent-probe``). Every launch site must come through here
(test_child_launch_guard.py).
"""
from __future__ import annotations

from pathlib import Path
import sys

# kind -> (module for ``python -m``, flag the frozen app exe dispatches on)
_CHILDREN = {
    "render": ("src.render_worker.worker_main", "--render-worker"),
    "print": ("src.printing.helper_main", "--print-helper"),
    "object-probe": ("src.object_probe.helper_main", "--object-probe"),
}
# kind -> (stdlib-only script path from the repo root, flag the frozen app exe dispatches on).
# A script child is started as ``<interpreter> -I -S -u <script>``: isolated and site-less, so it
# imports nothing from the app (``-m`` would fail under ``-I``, which drops the working directory).
_SCRIPT_CHILDREN = {
    "recent-probe": ("utils/recent_file_worker.py", "--recent-probe"),
}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def child_launch(
    kind: str, extra_args: list[str] | None = None, *, python_executable: str | None = None
) -> tuple[str, list[str]]:
    """Return ``(program, args)`` for a child of ``kind`` (``render``, ``print`` or ``recent-probe``)."""
    frozen = getattr(sys, "frozen", False)
    if kind in _SCRIPT_CHILDREN:
        script, flag = _SCRIPT_CHILDREN[kind]
        if frozen:
            return python_executable or sys.executable, [flag, *(extra_args or [])]
        # The actual interpreter, not the Windows venv redirector whose grandchild cannot be reaped.
        program = python_executable or getattr(sys, "_base_executable", sys.executable)
        return program, ["-I", "-S", "-u", str(_REPO_ROOT / script), *(extra_args or [])]
    if kind not in _CHILDREN:
        raise ValueError(f"unknown child kind: {kind!r}")
    module, flag = _CHILDREN[kind]
    program = python_executable or sys.executable
    head = [flag] if frozen else ["-m", module]
    return program, [*head, *(extra_args or [])]
