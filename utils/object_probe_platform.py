"""Platform capability of the contained object-probe child (owner ruling 2026-11-20).

The child caps its own memory with a Windows Job Object (``src/object_probe/memory_limit.py``), and
admission reads Windows memory counters (``read_system_memory``).  Elsewhere neither exists, so the
child must never be launched there: an uncontained child is not an option.  Callers ask here, via the
module attribute, so a test patches one place.  Standard library only.
"""
from __future__ import annotations

import sys


def contained_probe_supported() -> bool:
    """True where the memory-contained object-probe child can run (Windows only)."""
    return sys.platform == "win32"
