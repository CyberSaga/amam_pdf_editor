"""Limits shared by the object-probe child and its runner (Qt-free, standard library only)."""
from __future__ import annotations

# Largest answer line of kind ``text`` the GUI process will ever parse (measured: an 8,000-span
# page is 9.46 MB and 164 ms to parse and install on the GUI thread).  The child answers
# ``resource_limited`` above it; the runner stops reading and kills the child above it.
TEXT_ANSWER_MAX_BYTES = 2 * 1024 * 1024
