from __future__ import annotations

from abc import ABC
from collections.abc import Sequence

import fitz


class ToolExtension(ABC):
    """Base extension contract for PDFModel tools."""

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        return None

    def on_session_close(self, session_id: str) -> None:
        return None

    def on_session_saved(self, session_id: str) -> None:
        return None

    def has_unsaved_changes(self, session_id: str) -> bool:
        return False

    def needs_page_overlay(self, session_id: str, page_num: int, purpose: str) -> bool:
        return False

    def apply_page_overlay(self, session_id: str, page_num: int, page: fitz.Page, purpose: str) -> None:
        return None

    def prepare_doc_for_save(self, session_id: str, doc: fitz.Document) -> fitz.Document | None:
        return None

    # -- page structure (F17-COH-3, F17-COH-4) ---------------------------------
    # State a tool keeps per PAGE (a watermark's page list) names pages by number,
    # and a structural op (delete, move, insert, merge) renumbers them.  PDFModel
    # reports every such change through ONE chokepoint (``_pages_restructured``),
    # stores the tool's page state in each document snapshot so undo / redo bring
    # it back exactly, and lets the tool apply its persisted effect to a PDF built
    # from the session's pages.  Tools without page-bound state keep the no-ops.

    def on_pages_restructured(self, session_id: str, origins: Sequence[int | None], old_count: int) -> None:
        """The page list of the session changed.

        ``origins[j]`` is the 1-based page of the PREVIOUS list that new page ``j + 1``
        is, or ``None`` for a page that did not exist before.  A previous page may
        appear once, several times (a merge that uses the document twice) or not at
        all (deleted).  ``old_count`` is the previous page count.
        """
        return None

    def capture_page_state(self, session_id: str) -> object | None:
        """Immutable page-bound state to store in a document snapshot, or ``None``."""
        return None

    def restore_page_state(self, session_id: str, state: object | None) -> None:
        """Put back what ``capture_page_state`` returned, after the document was restored."""
        return None

    def prepare_derived_document(
        self, session_id: str, doc: fitz.Document, origins: Sequence[int | None]
    ) -> None:
        """Apply the persisted effect to a NEW document built from this session's pages.

        An export of some pages or a merge into a new file: ``origins`` is as in
        ``on_pages_restructured`` but relative to the session's CURRENT pages.
        Mutates ``doc`` in place.
        """
        return None
