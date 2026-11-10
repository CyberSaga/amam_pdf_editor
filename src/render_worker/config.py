from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)
_warned = False


def render_worker_mode() -> str:
    global _warned
    value = os.environ.get("PDF_EDITOR_RENDER_WORKER", "process")
    if value in {"thread", "process"}:
        return value
    if not _warned:
        logger.warning("Invalid render worker mode; using process")
        _warned = True
    return "process"


def default_worker_count(cpus: int | None) -> int:
    """Compute children by core count: the GUI and the OS keep their share of the cores."""
    if cpus is None:
        return 1
    return 3 if cpus >= 8 else 2 if cpus >= 4 else 1


def render_worker_count() -> int:
    """Requested compute children, 1-3. An explicit env value wins; otherwise the core-based default.

    Admission (resource ledger, OS headroom, document size) can still hold the optional
    children back; this is the ceiling, not a promise.
    """
    value = os.environ.get("PDF_EDITOR_RENDER_WORKERS", "")
    if value in {"1", "2", "3"}:
        return int(value)
    return default_worker_count(os.cpu_count())
