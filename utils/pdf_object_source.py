"""The exact source text of a PDF object, read and set (W1B-DICT-RT).

``fitz.Document.xref_object`` does not hand out the object's source: PyMuPDF
decodes MuPDF's printed object with ``raw_unicode_escape`` (1.27.1,
``JM_EscapeStrFromBuffer``), so a name that holds a literal backslash-u escape
reads as something else - ``/F\\u0031`` (a backslash is a regular character in
a PDF name) as ``/F1``, ``/F\\udc80`` as a lone surrogate.  Written back with
``update_object``, that text renames the name (the content that selects it no
longer finds it) or raises ``UnicodeEncodeError``, and two such texts compare
equal across the rename.

:func:`xref_object_exact` prints the object with the same MuPDF printer and
keeps the bytes as they are.  The printer escapes every byte outside printable
ASCII (``#xx`` in a name, octal in a string, where it doubles a backslash too,
so only a name can hold an escape), so the text is ASCII, and
``update_object`` (which encodes it as UTF-8 and parses it) writes back
exactly the object that was read.  For an object without such a name it is
the text ``xref_object`` returns.

``Document.xref_set_key`` has the same decode inside: PyMuPDF's
``JM_set_object_value`` puts a placeholder at the key, prints the WHOLE
object, decodes it, swaps the value in and parses the text again, so it
renames such a name anywhere in the object it edits, and a lone surrogate
raises after the placeholder is already in the live object.
:func:`xref_set_key_exact` is that code with the decode taken out; everything
else, quirks included, is PyMuPDF's.  :func:`exact_set_key` routes PyMuPDF's
own methods that call ``xref_set_key`` (``Annot.set_colors``,
``Document.set_metadata``, ``Page.replace_image`` ...) through it.

``model/`` and ``utils/`` read and set objects with these;
``test_scripts/test_exact_object_text.py`` lists the reviewed whole-document
walks that still use ``xref_object`` and fails on any other call.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any

import fitz

logger = logging.getLogger(__name__)

# The private PyMuPDF functions the helpers use (1.27.1); without one they
# fall back to PyMuPDF's own, decoding method.
_PRINTER_API = ("_as_pdf_document", "JM_object_to_buffer")
_SET_KEY_API = (*_PRINTER_API, "JM_pdf_obj_from_str")

# Document.xref_set_key's own checks (1.27.1).
_INVALID_NAME_CHARS = frozenset(" \t\n\r\x0b\x0c()<>[]{}/%\x00")
_EYECATCHER = "fitz: replace me!"
_ABSENT = object()

_fallbacks_logged: set[str] = set()


def _log_fallback_once(using: str, reason: str) -> None:
    if using not in _fallbacks_logged:
        _fallbacks_logged.add(using)
        logger.warning("exact PDF object text unavailable (%s); using %s", reason, using)


def _private(names: tuple[str, ...]) -> tuple[Any, ...] | None:
    found = tuple(getattr(fitz, name, None) for name in names)
    return None if None in found else found


def _without_frames(exc: BaseException, handling: BaseException | None) -> BaseException:
    """``exc`` with no traceback on it or on the exceptions chained to it, up to
    ``handling``: the exception the caller was handling when it called is the
    caller's, keeps its frames, and is chained again when ``exc`` is raised."""
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and link is not handling and id(link) not in seen:
        seen.add(id(link))
        link.__traceback__ = None
        link = link.__cause__ or link.__context__
    return exc


def _print_object(
    doc: fitz.Document, xref: int, compressed: bool, as_pdf: Callable[..., Any], to_buffer: Callable[..., Any]
) -> tuple[bytes | None, str]:
    """MuPDF's printed object (``-1``: the trailer), or ``None`` and MuPDF's error message.

    A function of its own so that no MuPDF object is a local of the frame that
    raises: a traceback that kept the SWIG document wrapper would keep the
    file open after ``doc.close()`` for as long as a caller keeps the error
    (LS-3), and the ``RuntimeError`` is raised outside any handler, so it has
    no ``__context__`` either.
    """
    mupdf = fitz.mupdf
    try:
        pdf = as_pdf(doc)
        obj = mupdf.pdf_trailer(pdf) if xref == -1 else mupdf.pdf_load_object(pdf, xref)
        return bytes(mupdf.fz_buffer_extract_copy(to_buffer(mupdf.pdf_resolve_indirect(obj), int(compressed), 0))), ""
    except mupdf.FzErrorBase as exc:
        return None, str(exc)


def xref_object_exact(doc: fitz.Document, xref: int, *, compressed: bool = False) -> str:
    """``doc.xref_object(xref, compressed=compressed)`` without the escape decoding.

    ``-1`` reads the trailer.  Raises what ``xref_object`` raises, so a caller
    swapped from it keeps its ``except`` clauses: ``ValueError`` for a closed
    document, ``RuntimeError`` for a non-PDF document, an xref outside
    ``1 .. xref_length() - 1`` or a slot that holds no object (MuPDF's error
    is re-raised as ``RuntimeError`` carrying only its message: an error kept
    past ``close()`` must not keep the file open, LS-3).  Falls back to
    ``xref_object`` (one WARNING per process) when this PyMuPDF lacks the
    private printer or the printed bytes are not ASCII.
    """
    if doc.is_closed:
        raise ValueError("document closed")
    if not doc.is_pdf:
        raise RuntimeError("is no PDF")
    if xref != -1 and not 1 <= xref < doc.xref_length():
        raise RuntimeError("bad xref")
    api = _private(_PRINTER_API)
    if api is None:
        _log_fallback_once("PyMuPDF's xref_object", "PyMuPDF lacks " + " / ".join(_PRINTER_API))
        return doc.xref_object(xref, compressed=compressed)
    data, failure = _print_object(doc, xref, compressed, *api)
    if data is None:
        raise RuntimeError(failure)
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        _log_fallback_once("PyMuPDF's xref_object", f"xref {xref} printed a byte outside ASCII")
        return doc.xref_object(xref, compressed=compressed)


def _set_object_value(
    doc: fitz.Document,
    xref: int,
    key: str,
    value: str,
    as_pdf: Callable[..., Any],
    to_buffer: Callable[..., Any],
    from_str: Callable[..., Any],
) -> BaseException | None:
    """PyMuPDF 1.27.1's ``xref_set_key`` after its argument checks, with
    ``JM_set_object_value`` inlined and the printed object decoded as ASCII.

    Returns what it raised, without frames, for the caller to raise outside
    (LS-3, see :func:`_print_object`).  The order of the MuPDF calls is
    PyMuPDF's: the placeholder goes into the live object first, so what an
    error leaves behind, and what a holder of the old object sees, are the same.
    """
    mupdf = fitz.mupdf
    handling = sys.exc_info()[1]
    try:
        pdf = as_pdf(doc)
        if not 1 <= xref <= mupdf.pdf_xref_len(pdf) - 1 and xref != -1:  # _INRANGE: a float below the end too
            raise ValueError("bad xref")
        obj = mupdf.pdf_load_object(pdf, xref) if xref != -1 else mupdf.pdf_trailer(pdf)
        # JM_set_object_value
        bound = mupdf.pdf_get_bound_document(obj)
        path = key.split("/")
        skey = path.pop()
        if not mupdf.pdf_dict_getp(obj, key).m_internal:
            # Created here: refused when a higher level of the path is indirect.
            while path:
                if mupdf.pdf_is_indirect(mupdf.pdf_dict_getp(obj, "/".join(path))):
                    raise Exception("path to '%s' has indirects", skey)
                path.pop()
        mupdf.pdf_dict_putp(obj, key, mupdf.pdf_new_text_string(_EYECATCHER))
        testkey = mupdf.pdf_dict_getp(obj, key)
        if not mupdf.pdf_is_string(testkey) or mupdf.pdf_to_text_string(testkey) != _EYECATCHER:
            raise Exception("cannot insert value for '%s'", key)
        printed = bytes(mupdf.fz_buffer_extract_copy(to_buffer(obj, 1, 0)))
        try:
            text = printed.decode("ascii")
        except UnicodeDecodeError:
            _log_fallback_once("PyMuPDF's xref_set_key", f"xref {xref} printed a byte outside ASCII")
            text = printed.decode("raw_unicode_escape", errors="replace")  # JM_EscapeStrFromBuffer
        new_obj = from_str(bound, text.replace(f"/{skey}({_EYECATCHER})", f"/{skey} {value}", 1))
        # Document.xref_set_key
        if not new_obj.m_internal:
            return None
        if xref != -1:
            mupdf.pdf_update_object(pdf, xref, new_obj)
        else:
            for i in range(mupdf.pdf_dict_len(new_obj)):
                mupdf.pdf_dict_put(obj, mupdf.pdf_dict_get_key(new_obj, i), mupdf.pdf_dict_get_val(new_obj, i))
        return None
    except Exception as exc:
        return _without_frames(exc, handling)


def xref_set_key_exact(doc: fitz.Document, xref: int, key: str, value: str) -> None:
    """``doc.xref_set_key(xref, key, value)`` without the escape decoding.

    Leaves every other name of the object as it is.  Otherwise it is PyMuPDF's
    method: the same checks and exceptions (``ValueError`` for a closed
    document, a bad key, value or xref; ``AssertionError`` for a non-PDF
    document; MuPDF's error for a value that does not parse; ``Exception``
    for a path to create behind an indirect dictionary), ``-1`` for the
    trailer, ``"null"`` stored as null, and its placeholder string
    ``(fitz: replace me!)`` left at the key when the value does not parse or
    when the key exists behind an indirect dictionary of the path (MuPDF puts
    it there, then prints the object, which shows only the reference).
    Does what PyMuPDF does (one WARNING per process) when this PyMuPDF lacks
    the private functions (it calls PyMuPDF's method) or the printed bytes are
    not ASCII (it decodes them as PyMuPDF does).
    """
    if doc.is_closed:
        raise ValueError("document closed")
    if not key or not isinstance(key, str) or _INVALID_NAME_CHARS.intersection(key) not in (set(), {"/"}):
        raise ValueError("bad 'key'")
    if (
        not isinstance(value, str)
        or not value
        or value[0] == "/" and _INVALID_NAME_CHARS.intersection(value[1:]) != set()
    ):
        raise ValueError("bad 'value'")
    api = _private(_SET_KEY_API)
    if api is None:
        _log_fallback_once("PyMuPDF's xref_set_key", "PyMuPDF lacks " + " / ".join(_SET_KEY_API))
        fitz.Document.xref_set_key(doc, xref, key, value)  # the class's: exact_set_key may shadow doc's
        return
    error = _set_object_value(doc, xref, key, value, *api)
    if error is not None:
        raise error


@contextmanager
def exact_set_key(doc: fitz.Document) -> Iterator[None]:
    """Inside the block, ``doc.xref_set_key`` is :func:`xref_set_key_exact`.

    For PyMuPDF's own methods that call it on ``doc`` (``Annot.set_colors``,
    ``Document.set_metadata``, ``subset_fonts``, ``Page.replace_image``
    through ``xref_copy``, ``embfile_add`` ...): an attribute on the instance
    shadows the method.  On the way out the instance gets back what it had (an
    attribute someone else set, a test's spy, or none), unless something else
    replaced the routing inside the block.  A block inside another block for
    the same document changes nothing.
    """
    had = vars(doc).get("xref_set_key", _ABSENT)
    if isinstance(had, partial) and had.func is xref_set_key_exact and had.args[0] is doc:
        yield
        return
    routed = partial(xref_set_key_exact, doc)
    setattr(doc, "xref_set_key", routed)
    try:
        yield
    finally:
        if vars(doc).get("xref_set_key") is routed:
            if had is _ABSENT:
                delattr(doc, "xref_set_key")
            else:
                setattr(doc, "xref_set_key", had)


__all__ = ["exact_set_key", "xref_object_exact", "xref_set_key_exact"]
