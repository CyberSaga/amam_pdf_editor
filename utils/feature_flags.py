"""Switches for features that are built but not offered to users yet."""

from __future__ import annotations

import os
from collections.abc import Mapping

VECTOR_EDIT_ENV = "PDF_EDITOR_VECTOR_EDIT"


def vector_edit_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """The internal vector-path selection and delete (card B7).  Off: every write entry takes the lease now (11-28), but
    the Astra r5 must-fixes of the flag-on flow are open (plans/b7-review-r5.md, plans/b7-class-design-xhigh.md)."""
    return (os.environ if environ is None else environ).get(VECTOR_EDIT_ENV, "") == "1"
