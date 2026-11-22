"""Limits shared by the object-probe child and its runner (Qt-free, standard library only)."""
from __future__ import annotations

# Largest answer line of kind ``text`` the GUI process will ever parse (measured: an 8,000-span
# page is 9.46 MB and 164 ms to parse and install on the GUI thread).  The child answers
# ``resource_limited`` above it; the runner stops reading and kills the child above it.
TEXT_ANSWER_MAX_BYTES = 2 * 1024 * 1024

# Largest answer line of every other kind (``scan``, ``tables``) the runner will ever parse.
# Measured: a scan row of a Do deep in a 7 MB stream with long-decimal ``cm`` values is about 235
# bytes, so an honest answer at SCAN_CACHE_MAX_RECORDS (200,000 records) is about 45 MiB; the cap is
# a margin of about 1.4 above that.  Enforced on the bytes, before any JSON parsing, so a hostile
# line costs one kill and a ``resource_limited`` answer, not a parse on the GUI thread.
ANSWER_MAX_BYTES = 64 * 1024 * 1024


def answer_cap(kind: str | None) -> int:
    """The stdout byte cap of one answer line of ``kind``."""
    return TEXT_ANSWER_MAX_BYTES if kind == "text" else ANSWER_MAX_BYTES
