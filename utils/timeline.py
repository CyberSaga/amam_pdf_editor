"""Opt-in startup timeline for measuring a (frozen) build: ``PDF_EDITOR_TIMELINE=<file>``.

With the variable set, ``start()`` records ``process_start`` and ``mark(event)`` appends one JSON
line ``{"event": ..., "t_ms": ...}`` per event, ``t_ms`` being milliseconds of ``time.perf_counter``
since ``start()``. ``process_start`` also carries the wall clock (``wall``, epoch seconds) and the
pid so an external launcher can add the time before Python started. Each event is written at most
once per ``start()``. Unset (or empty), ``start()`` is one environment lookup and ``mark()`` is a
single ``None`` check: nothing is opened, created or changed. Write failures disable the helper;
they never reach the caller.

Standard library only (no Qt), so ``main.py`` can import it before anything else.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping

logger = logging.getLogger(__name__)

ENV_VAR = "PDF_EDITOR_TIMELINE"

_path: str | None = None
_t0 = 0.0
_seen: set[str] = set()


def start(environ: Mapping[str, str] | None = None) -> None:
    """(Re)read the environment, reset the clock and the once-per-event memory."""
    global _path, _t0
    _seen.clear()
    _path = (os.environ if environ is None else environ).get(ENV_VAR) or None
    if _path is None:
        return
    _t0 = time.perf_counter()
    _seen.add("process_start")
    _write(_path, {"event": "process_start", "t_ms": 0.0, "wall": time.time(), "pid": os.getpid()})


def enabled() -> bool:
    return _path is not None


def mark(event: str) -> None:
    """Record ``event`` (the first time only) when the timeline is on."""
    path = _path
    if path is None or event in _seen:
        return
    _seen.add(event)
    _write(path, {"event": event, "t_ms": round((time.perf_counter() - _t0) * 1000.0, 3)})


def _write(path: str, record: dict) -> None:
    global _path
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except (OSError, TypeError, ValueError):
        logger.debug("startup timeline disabled: cannot append to its target", exc_info=True)
        _path = None
