"""The two names of the vector scanner that the GUI-side page source needs without importing numpy.

``model.vector_paths.scan`` imports and re-exports both (its own tests patch ``scan.MAX_DECODED_BYTES``);
``PDFModel.vector_page_source`` imports this module only, so the scanner and numpy stay out of the GUI
interpreter until a worker needs them (B3 round 2).  Standard library only.
"""
from __future__ import annotations

MAX_DECODED_BYTES = 256 * 1024 * 1024
#: most content streams of one page the ``vector-scan`` child accepts (the manifest of stream lengths is
#: bounded by it; the coordinator refuses ``TOO_LARGE`` above it before a job or a directory exists)
MAX_STREAMS = 100_000
#: decoded bytes above which a page is scanned by the accelerated scanner F (card B4); at or below, G (the
#: oracle) runs: F's start-up cost is not worth it on a small page
ACCELERATE_ABOVE_BYTES = 1 << 20


class VectorPageRefused(Exception):
    """The page cannot be indexed.  ``code``: NO_FRAME | TOO_LARGE | SCAN_ERROR | CHORD_CAP."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
