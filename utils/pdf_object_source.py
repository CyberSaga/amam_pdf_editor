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

``Document.xref_set_key`` has the same decode inside, and more: PyMuPDF's
``JM_set_object_value`` puts the placeholder string ``(fitz: replace me!)``
at the key in the live object, prints the WHOLE object, decodes it, swaps the
value in for ``/<key>(fitz: replace me!)`` as text and parses the object
again.  So it renames such a name anywhere in the object it edits; and the
placeholder stays in place of the value wherever the text swap misses - a key
behind an indirect dictionary of the path (MuPDF puts it in that dictionary,
the print shows only the reference), a key printed otherwise (``#``,
non-ASCII), a value that does not parse (it raises after the placeholder is
in) - while a value of several objects adds keys of its own.

:func:`xref_set_key_exact` does not print the object: it parses the value
alone (exactly one PDF object, else it raises before anything is written),
walks the key path as MuPDF's ``pdf_dict_putp`` does and puts the value at the
last key.  A level that is an indirect dictionary is followed, so the key is
set where ``xref_get_key`` reads it; :func:`xref_key_holder` names that object.
Everything else is PyMuPDF's: the checks and exceptions, ``null`` stored as
null, a missing or direct non-dictionary level made a new dictionary.
:func:`exact_set_key` routes PyMuPDF's own methods that call ``xref_set_key``
(``Annot.set_colors``, ``Document.set_metadata``, ``Page.replace_image`` ...)
through it.

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
# fall back to PyMuPDF's own method.
_PRINTER_API = ("_as_pdf_document", "JM_object_to_buffer")
_SET_KEY_API = ("_as_pdf_document",)

# Document.xref_set_key's own checks (1.27.1).
_INVALID_NAME_CHARS = frozenset(" \t\n\r\x0b\x0c()<>[]{}/%\x00")
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


def _object_at(doc: fitz.Document, xref: int, key: str, as_pdf: Callable[..., Any]) -> tuple[Any, Any]:
    """PyMuPDF 1.27.1's ``xref_set_key`` up to its first write: the document
    and the object ``xref`` (``-1``: the trailer), with its errors in its order
    (``bad xref``; a key path of 256 bytes or more; an object that is no
    dictionary, MuPDF's ``not a dict``)."""
    mupdf = fitz.mupdf
    pdf = as_pdf(doc)
    if not 1 <= xref <= mupdf.pdf_xref_len(pdf) - 1 and xref != -1:  # _INRANGE: a float below the end too
        raise ValueError("bad xref")
    obj = mupdf.pdf_load_object(pdf, xref) if xref != -1 else mupdf.pdf_trailer(pdf)
    mupdf.pdf_dict_getp(obj, key)  # MuPDF refuses a long path before anything else
    if not mupdf.pdf_is_dict(obj):
        mupdf.pdf_dict_puts(obj, key, mupdf.PdfObj())  # raises MuPDF's "not a dict (<kind>)"
        raise Exception("cannot insert value for '%s'", key)
    return pdf, obj


def _levels(key: str) -> list[str]:
    """``key`` split as MuPDF's ``pdf_dict_putp`` and ``pdf_dict_getp`` split
    it: a trailing slash ends the path."""
    levels = key.split("/")
    if len(levels) > 1 and not levels[-1]:
        levels.pop()
    return levels


def _chain_end(obj: Any) -> int | None:
    """The number of the object a reference, or a chain of them, ends at, as
    MuPDF resolves it wherever it reads or writes (``pdf_resolve_indirect_chain``,
    at most 9 hops); ``None`` when ``obj`` is no reference."""
    mupdf = fitz.mupdf
    number = None
    for _hop in range(10):
        if not mupdf.pdf_is_indirect(obj):
            break
        number = mupdf.pdf_to_num(obj)
        obj = mupdf.pdf_resolve_indirect(obj)
    return number


def _walk(pdf: Any, obj: Any, key: str, *, create: bool) -> tuple[int | None, Any]:
    """The levels of ``key`` above the last, from ``obj``, as the setter walks
    them: a level that is an indirect dictionary is followed (the object at
    the end of its chain of references is the holder from there on); a level
    that is an indirect object of another kind is refused, as PyMuPDF refuses
    it; a missing or direct non-dictionary level is made a new direct
    dictionary (``create``, MuPDF's ``pdf_dict_putp``) or ends the walk, the
    rest being created in the level reached.  Returns the holder's number
    (``None``: ``obj`` itself, unless ``obj`` is a reference) and the level
    that takes the last key."""
    mupdf = fitz.mupdf
    holder = _chain_end(obj)  # an object that is only a reference is written at its end
    level = obj
    for name in _levels(key)[:-1]:
        child = mupdf.pdf_dict_gets(level, name)
        if mupdf.pdf_is_indirect(child):
            if not mupdf.pdf_is_dict(child):  # an array, a number, a reference to no object
                raise Exception("path to '%s' has indirects", key.split("/")[-1])
            holder = _chain_end(child)
        elif not mupdf.pdf_is_dict(child):
            if not create:
                break
            child = mupdf.pdf_new_dict(pdf, 1)
            mupdf.pdf_dict_puts(level, name, child)
        level = child
    return holder, level


def _one_object(pdf: Any, value: str) -> Any:
    """``value`` parsed as exactly one PDF object; a value of none or of
    several raises ``ValueError("bad 'value'")``, one MuPDF cannot parse
    MuPDF's error.  As in a dictionary, a bare word reads as null."""
    mupdf = fitz.mupdf
    stream = mupdf.fz_open_buffer(mupdf.fz_new_buffer_from_copied_data(f"[{value}]".encode()))
    lexbuf = mupdf.PdfLexbuf(mupdf.PDF_LEXBUF_SMALL)
    array = mupdf.pdf_parse_stm_obj(pdf, stream, lexbuf)
    if mupdf.pdf_array_len(array) != 1 or mupdf.pdf_lex(stream, lexbuf) != mupdf.PDF_TOK_EOF:
        raise ValueError("bad 'value'")
    return mupdf.pdf_array_get(array, 0)


def _set_object_value(
    doc: fitz.Document, xref: int, key: str, value: str, as_pdf: Callable[..., Any]
) -> BaseException | None:
    """Set ``key`` of ``xref`` to ``value`` without a placeholder: every check
    and the parse come before the first write, so an error changes nothing.

    Returns what it raised, without frames, for the caller to raise outside
    (LS-3, see :func:`_print_object`).  ``pdf_dict_puts`` stores ``null`` as
    null (``pdf_dict_putp`` would delete the key) and marks the object it
    writes into, so a full and an incremental save carry it.
    """
    mupdf = fitz.mupdf
    handling = sys.exc_info()[1]
    try:
        pdf, obj = _object_at(doc, xref, key, as_pdf)
        parsed = _one_object(pdf, value)
        _holder, level = _walk(pdf, obj, key, create=True)
        mupdf.pdf_dict_puts(level, _levels(key)[-1], parsed)
        return None
    except Exception as exc:
        return _without_frames(exc, handling)


def _checked_key(doc: fitz.Document, key: str) -> None:
    if doc.is_closed:
        raise ValueError("document closed")
    if not key or not isinstance(key, str) or _INVALID_NAME_CHARS.intersection(key) not in (set(), {"/"}):
        raise ValueError("bad 'key'")


def xref_set_key_exact(doc: fitz.Document, xref: int, key: str, value: str) -> None:
    """``doc.xref_set_key(xref, key, value)`` without its placeholder.

    Only the key changes: no other name or value of the object is printed and
    parsed again.  The key is set where ``doc.xref_get_key(xref, key)`` reads
    it, in the object :func:`xref_key_holder` names: through a level of the
    path that is an indirect dictionary, in that dictionary, created there when
    missing.  A value that is not exactly one PDF object raises before
    anything is written.

    Otherwise it is PyMuPDF's method: the same checks and exceptions
    (``ValueError`` for a closed document, a bad key, value or xref;
    ``AssertionError`` for a non-PDF document; MuPDF's error for an object
    that is no dictionary and for a value MuPDF cannot parse; ``Exception``
    for a path through an indirect object that is no dictionary), ``-1`` for
    the trailer, ``"null"`` stored as null, a missing or direct
    non-dictionary level of the path made a new dictionary.  Calls PyMuPDF's
    method (one WARNING per process) when this PyMuPDF lacks the private
    function.
    """
    _checked_key(doc, key)
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


def _key_holder(doc: fitz.Document, xref: int, key: str, as_pdf: Callable[..., Any]) -> int | BaseException:
    handling = sys.exc_info()[1]
    try:
        pdf, obj = _object_at(doc, xref, key, as_pdf)
        holder, _level = _walk(pdf, obj, key, create=False)
        return xref if holder is None else holder
    except Exception as exc:
        return _without_frames(exc, handling)


def xref_key_holder(doc: fitz.Document, xref: int, key: str) -> int:
    """The object that holds the last level of ``key`` of ``xref``: where
    :func:`xref_set_key_exact` sets it and ``xref_get_key`` reads it.

    That is the last indirect dictionary the path goes through, else ``xref``
    (``-1``: the trailer); for a reference, or a chain of them (``xref``
    itself may be an object that is only a reference), the object at its
    end.  Two key paths with the same holder and the same
    levels below it are one entry: writing one changes the other.  Raises what
    :func:`xref_set_key_exact` raises for the document, ``xref`` and ``key``;
    ``RuntimeError`` when this PyMuPDF lacks the private function (PyMuPDF's
    own method then decides where the key goes).
    """
    _checked_key(doc, key)
    api = _private(_SET_KEY_API)
    if api is None:
        _log_fallback_once("PyMuPDF's xref_set_key", "PyMuPDF lacks " + " / ".join(_SET_KEY_API))
        raise RuntimeError("the object holding the key cannot be told without " + " / ".join(_SET_KEY_API))
    found = _key_holder(doc, xref, key, *api)
    if isinstance(found, BaseException):
        raise found
    return found


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


__all__ = ["exact_set_key", "xref_key_holder", "xref_object_exact", "xref_set_key_exact"]
