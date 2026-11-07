from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)
_warned = False


def render_worker_mode() -> str:
    global _warned
    if getattr(sys, "frozen", False):
        return "thread"
    value = os.environ.get("PDF_EDITOR_RENDER_WORKER", "thread")
    if value in {"thread", "process"}:
        return value
    if not _warned:
        logger.warning("Invalid render worker mode; using thread")
        _warned = True
    return "thread"


def render_worker_count() -> int:
    """Requested compute children: 1 (default) or 2. Two is explicit, never automatic."""
    return 2 if os.environ.get("PDF_EDITOR_RENDER_WORKERS") == "2" else 1
