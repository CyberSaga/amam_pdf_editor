"""Heartbeat pytest plugin plus the reader helpers ``scripts/run_suite.py`` uses.

When ``PDF_EDITOR_TEST_HEARTBEAT`` names a file, every test appends one JSON line
at log-start and one at log-finish::

    {"nodeid": "test_scripts/test_x.py::test_a", "phase": "start", "t": 1761200000.1, "pid": 4242}

The supervisor watches the file's growth to detect a stall and names the culprit
as the last ``start`` without a matching ``finish``.  ``pid`` is the writer: a test
that runs pytest in a subprocess hands the variable down, so a nested session
appends its own lines to the same file; ``pending_culprit`` only counts the lines
of the first writer (the session the supervisor started).  Without the variable
the hooks do nothing and create nothing, so single-file runs are unaffected.

The plugin is stateless on purpose: the same module object can serve an outer
session and in-process ``pytester`` sessions, so the target path is read from
``os.environ`` on every hook call and the file is opened, written, flushed and
closed per line (the size/mtime change is what the supervisor sees).

Loaded for the real suite by ``pytest_plugins`` in ``test_scripts/conftest.py``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HEARTBEAT_ENV = "PDF_EDITOR_TEST_HEARTBEAT"


def _beat(nodeid: str, phase: str) -> None:
    target = os.environ.get(HEARTBEAT_ENV)
    if not target:
        return
    line = json.dumps({"nodeid": nodeid, "phase": phase, "t": time.time(), "pid": os.getpid()}) + "\n"
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
    except OSError:
        # Never fail a test because the heartbeat could not be written; the
        # supervisor then sees a stall and keeps the evidence.
        logger.warning("heartbeat write to %s failed", target, exc_info=True)


def pytest_runtest_logstart(nodeid: str, location: object) -> None:
    _beat(nodeid, "start")


def pytest_runtest_logfinish(nodeid: str, location: object) -> None:
    _beat(nodeid, "finish")


def read_heartbeat(path: Path) -> list[dict]:
    """Parse a heartbeat file; a missing file or a truncated/garbled line is skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: list[dict] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if isinstance(event, dict) and "nodeid" in event and "phase" in event:
            events.append(event)
    return events


def pending_culprit(events: list[dict]) -> str | None:
    """Return the last ``start`` nodeid with no later ``finish``, or ``None``.

    Only the first writer's lines count (see the module docstring); lines without a
    ``pid`` (older format) are taken as that writer's.
    """
    owner: object = events[0].get("pid") if events else None
    pending: dict[str, None] = {}  # insertion-ordered; a re-start moves the key to the end
    for event in events:
        nodeid = event.get("nodeid")
        if not isinstance(nodeid, str):
            continue
        if event.get("pid", owner) != owner:
            continue
        phase = event.get("phase")
        if phase == "start":
            pending.pop(nodeid, None)
            pending[nodeid] = None
        elif phase == "finish":
            pending.pop(nodeid, None)
    return next(reversed(pending), None) if pending else None
