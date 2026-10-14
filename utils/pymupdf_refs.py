"""PyMuPDF object-lifetime helpers (reference cycles that pin a file open).

``Page.first_annot`` / ``Annot.next`` register every walked annotation in the
strong ``_annot_refs`` dict of the annotation's parent page, and an annotation
reached through ``.next`` owns a strong reference to that parent page: a
Page<->Annot cycle that only the cyclic GC frees.  ``Document.close`` does not
release it, so on Windows the MuPDF file stream stays open and the file cannot
be replaced until an unrelated collection runs (R10 MBT-1).  A walk over a
single annotation (``first_annot`` only, weak parent proxy) is cycle-free.

A loaded page is also SHARED: while any ``fitz.Page`` of page *n* is alive
(that cycle garbage, a traceback a log handler keeps, a caller's variable),
every later ``doc[n]`` wraps the same MuPDF page, whose annotation, widget and
link lists were built when it was first loaded.  A write that replaces the
page's object graph by xref (``model.page_snapshot.restore_page_graph``) goes
round MuPDF's annotation API, so those lists must be rebuilt with
:func:`sync_open_pages` (F11-ANN-2).
"""

from __future__ import annotations

import logging

import fitz

logger = logging.getLogger(__name__)


def forget_walked_annot(annot: object) -> None:
    """Drop the page-side strong reference to an annotation reached via ``.next``.

    Breaks the Page<->Annot cycle: once the caller drops ``annot`` both are freed
    by reference counting.  The annotation itself stays fully usable (it keeps
    its own parent); only the bookkeeping entry that would invalidate it when
    the page is erased is removed.  Best effort: a PyMuPDF without the private
    ``_annot_refs`` registry has nothing to forget, and
    ``utils.path_staging.replace_file`` still recovers from the leftover garbage.
    """
    try:
        refs = annot.parent._annot_refs  # type: ignore[attr-defined]
        refs.pop(id(annot), None)
    except Exception:
        logger.debug("annotation registry not available; leaving it to the cyclic GC", exc_info=True)


def sync_open_pages(doc: fitz.Document) -> None:
    """Rebuild the annotation / widget / link lists of every loaded page of ``doc``.

    Call after writing a page's objects by xref (``update_object`` on the page
    dictionary or its ``/Annots``): MuPDF keeps those lists per loaded page and
    only its own annotation API updates them, so a page still loaded across the
    write keeps listing the old annotations -- ``load_annot`` of a written-back
    one raises "xref N is not an annot of this page" and ``get_links`` misses a
    written-back link (F11-ANN-2).  ``pdf_sync_open_pages`` is MuPDF's own
    post-undo resync; pages that are not loaded have nothing cached.  An
    ``Annot`` object whose annotation is no longer listed reads as xref 0 /
    type -1 afterwards (MuPDF drops its object) instead of a dead xref.

    Best effort, never raises: the write it follows has already succeeded.  A
    non-PDF document is skipped (its PDF view is a null wrapper that MuPDF
    would dereference).  The warning logs ``str(exc)``, never the exception: a
    record-keeping handler would otherwise keep its traceback and the document.
    """
    if not getattr(doc, "is_pdf", False):
        return
    try:
        mupdf = fitz.mupdf
        pdf = mupdf.pdf_document_from_fz_document(doc.this)
        if pdf.m_internal is None:
            return
        mupdf.pdf_sync_open_pages(pdf)
    except Exception as exc:  # noqa: BLE001 - must not fail the write it follows
        logger.warning("could not resync loaded pages after an in-place page write: %s", str(exc))
