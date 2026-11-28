"""Switches for features that are built but not offered to users yet."""

from __future__ import annotations

import os
from collections.abc import Mapping

VECTOR_EDIT_ENV = "PDF_EDITOR_VECTOR_EDIT"


def vector_edit_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """The internal vector-path selection and delete (card B7).  Off until every write entry takes a lease
    (WatermarkTool.on_session_open and the pdf_object_ops free functions do not yet): see TODOS."""
    return (os.environ if environ is None else environ).get(VECTOR_EDIT_ENV, "") == "1"
