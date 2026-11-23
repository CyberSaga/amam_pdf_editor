"""CAD vector path editing (M1).  Imported lazily; numpy is imported inside the modules that need it.

The package itself imports nothing heavy: the public names below resolve on first use (PEP 562), so
``model.vector_paths.limits`` (what the GUI-side page source needs) does not pull numpy or the scanner
into the interpreter (B3 round 2).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from model.vector_paths.commit_state import DigestTable, WriteSet, digest_table, undeclared
    from model.vector_paths.scan import Frame, PathFlag, VectorIndex, VectorPageRefused, VectorScanCancelled, scan_page

_SOURCES = {
    "DigestTable": "commit_state",
    "WriteSet": "commit_state",
    "digest_table": "commit_state",
    "undeclared": "commit_state",
    "Frame": "scan",
    "PathFlag": "scan",
    "VectorIndex": "scan",
    "VectorPageRefused": "scan",
    "VectorScanCancelled": "scan",
    "scan_page": "scan",
}

__all__ = [
    "DigestTable",
    "Frame",
    "PathFlag",
    "VectorIndex",
    "VectorPageRefused",
    "VectorScanCancelled",
    "WriteSet",
    "digest_table",
    "scan_page",
    "undeclared",
]


def __getattr__(name: str) -> Any:
    module = _SOURCES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"model.vector_paths.{module}"), name)
    globals()[name] = value
    return value
