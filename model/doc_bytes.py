"""Whole-document serialization through MuPDF's native output (H10-2 Part B).

PyMuPDF's ``tobytes()`` and ``save(io.BytesIO)`` route every ``fz_write`` through
a Python file object (``JM_new_output_fileptr``), and MuPDF's classic xref writer
makes about one write per table row.  A document whose xref declares 4M slots took
18.6 s per snapshot that way; the same 80,001,834 bytes written to a file took
0.35 s (0.056 s vs 0.18 s on an ordinary 47 MB file).  The bytes are identical.

``serialize_doc`` is the one place a snapshot is made:

* by default it writes a temp file in ``scratch_dir`` (MuPDF's native file
  output), reads it back and removes it at once; when that file cannot be
  written (the directory vanished, the volume is full) the same bytes come from
  the in-memory sink instead, so no edit ever depends on a writable disk
  (``tobytes`` never did; F12-H102-2);
* a DECRYPTED copy of an encrypted document never touches disk: when the output
  would be plaintext of a file that is encrypted on disk (``encryption`` other
  than KEEP on a document whose trailer carries ``/Encrypt``), or when the caller
  says so (``in_memory=True``: a copy that was already decrypted, a
  secure-latched session), MuPDF writes into an in-memory ``fz_buffer`` instead.

Both sinks produce the bytes ``tobytes`` would (pinned by ``test_doc_bytes.py``).
The in-memory sink mirrors ``Document.save``'s private prelude, so it relies on
PyMuPDF internals bounded by the ``>=1.27,<1.28`` pin; if any is missing it falls
back to ``tobytes`` (slow, still in memory).

No Qt.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

# A whole-document ``encryption=KEEP`` snapshot of a live document.  The model owns
# the real one (``PDFModel.serialize_document_bytes``: its private temp dir, and
# memory only once the session is secure-latched); a text-commit engine or preview
# session without a model behind it falls back to :func:`keep_snapshot_in_memory`.
SnapshotSerializer = Callable[[fitz.Document], bytes]


def source_is_encrypted(doc: fitz.Document) -> bool:
    """``True`` when ``doc``'s file is encrypted on disk (any scheme, owner-only too).

    Reads the trailer's encryption string from ``metadata``: it stays set after
    ``authenticate()`` and never touches the crypt state (``needs_pass`` on an
    authenticated handle would clobber its key, R9 M9-1).
    """
    try:
        return bool((doc.metadata or {}).get("encryption"))
    except (RuntimeError, ValueError, AttributeError):
        return True  # unknown: treat as encrypted, i.e. keep plaintext in memory


def serialize_doc(
    doc: fitz.Document,
    *,
    encryption: int,
    garbage: int = 0,
    no_new_id: int = 0,
    deflate: int = 0,
    scratch_dir: str | Path | None = None,
    in_memory: bool = False,
) -> bytes:
    """``doc.tobytes(garbage=, no_new_id=, deflate=, encryption=)``, byte-identical.

    ``encryption`` has no default: KEEP preserves the source encryption, anything
    else decrypts.  ``scratch_dir`` is where the temp file goes (``None``: the
    system temp dir).  A file sink that fails for a disk reason (``OSError``, or the
    ``FzErrorBase`` MuPDF raises for a failed open/write) is retried through the
    in-memory sink; an error of the document itself (zero pages, ...) is raised by
    whichever sink sees it first.
    """
    options = {
        "garbage": garbage,
        "no_new_id": no_new_id,
        "deflate": deflate,
        "encryption": encryption,
    }
    if in_memory or (encryption != fitz.PDF_ENCRYPT_KEEP and source_is_encrypted(doc)):
        return serialize_in_memory(doc, **options)
    try:
        return serialize_via_file(doc, scratch_dir, **options)
    except (OSError, fitz.mupdf.FzErrorBase) as exc:
        # Only reachable for KEEP / plaintext-source documents, so the in-memory
        # retry is no weaker than the file sink.  A real document error surfaces
        # again from the retry.  ``str(exc)``, never the exception: its traceback
        # holds the ``serialize_via_file`` frame with the SWIG document, and a
        # kept log record would keep the MuPDF file open (the WinError 5 class,
        # see ``xref_compaction``).
        logger.warning("snapshot temp file unavailable (%s); serializing in memory", str(exc))
        return serialize_in_memory(doc, **options)


def keep_snapshot_in_memory(doc: fitz.Document) -> bytes:
    """The fail-closed :data:`SnapshotSerializer`: KEEP bytes, never a temp file.

    A garbage=0 serialization still holds whatever a destructive edit removed, and
    only the model knows whether its session is latched, so a caller without a
    model keeps the bytes in memory rather than guess.
    """
    return serialize_doc(doc, encryption=fitz.PDF_ENCRYPT_KEEP, in_memory=True)


def serialize_via_file(
    doc: fitz.Document,
    scratch_dir: str | Path | None = None,
    *,
    encryption: int,
    garbage: int = 0,
    no_new_id: int = 0,
    deflate: int = 0,
) -> bytes:
    """The bytes ``doc.save(<temp file>, ...)`` writes; the temp file is removed."""
    fd, name = tempfile.mkstemp(
        prefix="snap_", suffix=".pdf", dir=None if scratch_dir is None else str(scratch_dir)
    )
    os.close(fd)
    path = Path(name)
    try:
        doc.save(
            name, garbage=garbage, no_new_id=no_new_id, deflate=deflate, encryption=encryption
        )
        return path.read_bytes()
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove snapshot temp file %s", path)


def serialize_in_memory(
    doc: fitz.Document,
    *,
    encryption: int,
    garbage: int = 0,
    no_new_id: int = 0,
    deflate: int = 0,
) -> bytes:
    """The bytes ``doc.tobytes(...)`` returns, written by MuPDF into an ``fz_buffer``.

    Mirrors ``Document.save`` for these options: the same argument checks, the
    same ``PdfWriteOptions``, and its prelude (``resynth_required = 0``,
    ``JM_embedded_clean``, ``JM_ensure_identity`` unless ``no_new_id``), then
    ``pdf_write_document`` into a native output instead of the Python one.
    """
    mupdf = fitz.mupdf
    as_pdf = getattr(fitz, "_as_pdf_document", None)
    embedded_clean = getattr(fitz, "JM_embedded_clean", None)
    ensure_identity = getattr(fitz, "JM_ensure_identity", None)
    if as_pdf is None or embedded_clean is None or ensure_identity is None:
        logger.debug("native in-memory sink unavailable; serializing through tobytes")
        return doc.tobytes(
            garbage=garbage, no_new_id=no_new_id, deflate=deflate, encryption=encryption
        )
    if doc.is_closed or doc.is_encrypted:
        raise ValueError("document closed or encrypted")
    if doc.page_count < 1:
        raise ValueError("cannot save with zero pages")
    pdf = as_pdf(doc)
    opts = mupdf.PdfWriteOptions()
    opts.do_incremental = 0
    opts.do_ascii = 0
    opts.do_compress = deflate
    opts.do_compress_images = 0
    opts.do_compress_fonts = 0
    opts.do_decompress = 0
    opts.do_garbage = garbage
    opts.do_pretty = 0
    opts.do_linear = 0
    opts.do_clean = 0
    opts.do_sanitize = 0
    opts.dont_regenerate_id = no_new_id
    opts.do_appearance = 0
    opts.do_encrypt = encryption
    opts.permissions = 4095
    opts.do_preserve_metadata = 1
    opts.do_use_objstms = 0
    opts.compression_effort = 0
    pdf.m_internal.resynth_required = 0
    embedded_clean(pdf)
    if no_new_id == 0:
        ensure_identity(pdf)
    buffer = mupdf.FzBuffer(1 << 16)
    out = mupdf.FzOutput(buffer)
    mupdf.pdf_write_document(pdf, out, opts)
    out.fz_close_output()
    return bytes(buffer.fz_buffer_extract())
