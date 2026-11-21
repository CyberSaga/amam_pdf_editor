from __future__ import annotations

import logging

import fitz

logger = logging.getLogger(__name__)


def apply_production_tools() -> None:
    """Set the process-wide PyMuPDF TOOLS state the app runs with.

    PDFModel.__init__ and every child process that interprets pages (object-probe kind
    ``text``) call this, so an entry extracted in a child equals one extracted in the app.
    """
    try:
        fitz.TOOLS.set_small_glyph_heights(True)
        logger.debug("PyMuPDF TOOLS.set_small_glyph_heights(True)")
    except AttributeError:
        logger.warning("PyMuPDF has no TOOLS support; skipping the glyph height setting")
