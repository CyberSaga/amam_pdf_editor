"""W1B-DICT-RT: an object written back from ``xref_object`` text loses names that hold a literal ``\\uXXXX``.

``Document.xref_object`` (PyMuPDF 1.27.1) decodes MuPDF's printed object with
``raw_unicode_escape``: a name ``/F\\u0031`` (a backslash is a regular
character in a PDF name) reads back as ``/F1`` and ``/F\\udc80`` as a lone
surrogate.  Code that captured that text and wrote it back renamed the name -
the content that selects it then finds no such resource - or raised
``UnicodeEncodeError``.  These tests pin the exact round trip on every such
path: the stream-storage restore and the patch revert built on it, the
annotation dictionary restore, the page-graph snapshot, the save-time
protected-page rollback, the signed append save's replay, the legacy
``/Dests`` rebuild after a page delete, the inherited-resources copy of the
paint-state writer and the new-font-stream dedupe.  The oracle is never
``xref_object`` (it decodes both sides alike): it is ``xref_get_key``, which
prints a name undecoded, the raw stream bytes and the render.
"""

from __future__ import annotations

import ast
import gc
import hashlib
import logging
import os
import sys
import traceback
from pathlib import Path

import fitz
import pytest

from model.page_snapshot import capture_page_graph, restore_page_graph
from model.text_commit.dto import StreamReplacement
from model.text_commit.inspect import (
    capture_annotation_parent_refs,
    capture_stream_storage,
    page_fingerprint,
    restore_annotation_parent_refs,
    restore_stream_storage,
)
from model.text_commit.patch import PatchSet, apply_patchset
from model.tools.manager import _ProtectedPageGuard, _StreamRecord

ROOT = Path(__file__).resolve().parents[1]

# Escapes that decode to a character ("1", short and long form), to a lone
# surrogate, and a truncated one that decodes to U+FFFD.
NAMES = ("F\\u0031", "F\\udc80", "F\\U00000031", "F\\u00")
_CONTENT = b"BT /F1 12 Tf 20 40 Td (Price 2024) Tj ET\n" * 4


def _render(doc: fitz.Document) -> str:
    return hashlib.sha256(doc[0].get_pixmap(dpi=36).samples).hexdigest()


def _reopened(doc: fitz.Document) -> fitz.Document:
    """``doc`` saved and reopened (numbering kept), so the test reads a file's objects."""
    data = doc.tobytes()
    doc.close()
    return fitz.open("pdf", data)


def _new_stream(doc: fitz.Document, dictionary: str, content: bytes, *, compress: bool) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, dictionary)
    doc.update_stream(xref, content, compress=compress)
    return xref


def _page_doc(name: str, *, page_font_name: str = "F1", content_dict: str = "<<>>", draw_form: bool = False):
    """A one-page document assembled from object text (``update_object`` of pure ASCII is byte-exact).

    ``draw_form``: the page draws Form XObject /Fm0, whose own /Resources call
    the font ``/<name>`` and whose content selects that name.  Otherwise the
    page's inline /Resources call the font ``/<page_font_name>`` and the
    content stream (dictionary ``content_dict``, Flate-compressed) shows text
    with it.  Returns ``(doc, form_xref_or_0, page_text_builder)``.
    """
    doc = fitz.open()
    page = doc.new_page(width=200, height=80)
    page_xref = page.xref
    parent = doc.xref_get_key(page_xref, "Parent")[1]
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    form = 0
    if draw_form:
        form = _new_stream(
            doc,
            f"<</Type/XObject/Subtype/Form/BBox[0 0 200 80]/Resources<</Font<</{name} {font} 0 R>>>>>>",
            f"BT /{name} 24 Tf 10 30 Td (Hello) Tj ET".encode(),
            compress=False,
        )
        resources = f"<</XObject<</Fm0 {form} 0 R>>>>"
        contents = _new_stream(doc, content_dict, b"q /Fm0 Do Q", compress=False)
    else:
        resources = f"<</Font<</{page_font_name} {font} 0 R>>>>"
        content = _CONTENT.replace(b"/F1 ", f"/{page_font_name} ".encode())
        contents = _new_stream(doc, content_dict, content, compress=True)

    def page_text(extra: str = "") -> str:
        return (
            f"<</Type/Page/Parent {parent}/MediaBox[0 0 200 80]/Resources{resources}"
            f"/Contents {contents} 0 R{extra}>>"
        )

    doc.update_object(page_xref, page_text())
    return _reopened(doc), form, page_text


def _grow_every_stream(doc: fitz.Document, page: fitz.Page) -> PatchSet:
    """A harmless full-stream PatchSet (one trailing space per content stream)."""
    replacements = []
    for xref in page.get_contents():
        current = doc.xref_stream(xref) or b""
        replacements.append(
            StreamReplacement(
                stream_xref=xref,
                start=0,
                end=len(current),
                expected_bytes=current,
                replacement_bytes=current + b" ",
                expected_stream_digest=hashlib.sha256(current).hexdigest(),
            )
        )
    return PatchSet(
        page_xref=page.xref,
        replacements=tuple(replacements),
        expected_page_fingerprint=page_fingerprint(doc, page),
    )


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# ----------------------------------------------------------- the exact reader


def test_exact_object_text_keeps_the_escape_and_is_xref_object_for_every_other_object() -> None:
    from utils.pdf_object_source import xref_object_exact

    doc, form, _page_text = _page_doc("F\\u0031", draw_form=True)
    try:
        text = xref_object_exact(doc, form)
        assert "/F\\u0031 " in text
        assert "/F\\u0031 " not in doc.xref_object(form)  # what PyMuPDF hands out decodes it
        text.encode("ascii")  # MuPDF's printer escapes every byte outside printable ASCII
        assert "/F\\u0031 " in xref_object_exact(doc, form, compressed=True)
        # Every object without such a name prints exactly as xref_object does, so
        # comparisons against text captured before the change stay valid.
        for xref in range(1, doc.xref_length()):
            if xref != form:
                assert xref_object_exact(doc, xref) == doc.xref_object(xref)
                assert xref_object_exact(doc, xref, compressed=True) == doc.xref_object(xref, compressed=True)
    finally:
        doc.close()


def test_exact_object_text_raises_what_xref_object_raises_and_reads_the_trailer() -> None:
    """Callers swapped from ``xref_object`` keep their ``except`` clauses: the
    same exception types for a freed slot, an xref out of range, a non-PDF
    document and a closed one; ``-1`` reads the trailer."""
    from utils.pdf_object_source import xref_object_exact

    doc = fitz.open()
    doc.new_page()
    freed = doc.get_new_xref()
    doc.update_object(freed, "<</A 1>>")
    doc.update_object(freed, "null")
    never_written = doc.get_new_xref()
    text_doc = fitz.open(stream=b"hello", filetype="txt")
    try:
        assert xref_object_exact(doc, -1) == doc.xref_object(-1)
        assert xref_object_exact(doc, never_written) == doc.xref_object(never_written)
        for target, xref in ((doc, freed), (doc, 0), (doc, doc.xref_length()), (doc, -2), (text_doc, 1)):
            with pytest.raises(Exception) as wanted:
                target.xref_object(xref)
            with pytest.raises(type(wanted.value)):
                xref_object_exact(target, xref)
    finally:
        doc.close()
        text_doc.close()
    with pytest.raises(ValueError):
        xref_object_exact(doc, 1)


@pytest.mark.skipif(sys.platform != "win32", reason="an open file blocks os.replace only on Windows")
def test_a_kept_read_error_does_not_keep_the_closed_document_open(tmp_path) -> None:
    """The ``RuntimeError`` for an unreadable slot holds no MuPDF document:
    kept past ``close()`` (a stored error, ``raise ... from exc``), it must not
    keep the file open (LS-3)."""
    from utils.pdf_object_source import xref_object_exact

    path = tmp_path / "doc.pdf"
    scratch = fitz.open()
    scratch.new_page()
    scratch.save(str(path))
    scratch.close()
    doc = fitz.open(str(path))
    freed = doc.get_new_xref()
    doc.update_object(freed, "<</A 1>>")
    doc.update_object(freed, "null")
    kept: list[BaseException] = []
    try:
        xref_object_exact(doc, freed)
    except RuntimeError as exc:
        kept.append(exc)
    assert kept
    doc.close()
    gc.collect()
    replacement = tmp_path / "other.pdf"
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)  # PermissionError while the file is still open
    assert kept


def test_exact_object_text_falls_back_to_xref_object_with_one_warning(monkeypatch, caplog) -> None:
    """Without the private printer, or when it prints a byte outside ASCII, the
    reader returns ``xref_object``'s text and warns once per process."""
    import utils.pdf_object_source as pdf_object_source

    doc, form, _page_text = _page_doc("F\\u0031", draw_form=True)
    try:
        real_printer = fitz.JM_object_to_buffer

        def non_ascii_printer(obj, compressed, ascii_):
            return fitz.mupdf.fz_new_buffer_from_copied_data(b"<</A (caf\xe9)>>")

        for printer in (None, non_ascii_printer):
            monkeypatch.setattr(pdf_object_source, "_fallbacks_logged", set())
            if printer is None:
                monkeypatch.delattr(fitz, "JM_object_to_buffer")
            else:
                monkeypatch.setattr(fitz, "JM_object_to_buffer", printer, raising=False)
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="utils.pdf_object_source"):
                assert pdf_object_source.xref_object_exact(doc, form) == doc.xref_object(form)
                assert pdf_object_source.xref_object_exact(doc, form) == doc.xref_object(form)
            assert len(_warnings(caplog)) == 1
            monkeypatch.setattr(fitz, "JM_object_to_buffer", real_printer, raising=False)
    finally:
        doc.close()


def test_exact_object_text_matches_xref_object_on_the_storage_fixtures() -> None:
    from test_scripts.stream_storage_fixtures import CASES, open_case
    from utils.pdf_object_source import xref_object_exact

    for case in CASES:
        doc = open_case(case)
        try:
            for xref in range(1, doc.xref_length()):
                assert xref_object_exact(doc, xref) == doc.xref_object(xref), (case, xref)
        finally:
            doc.close()


# ------------------------------------------------------ stream-storage restore


@pytest.mark.parametrize("name", NAMES)
def test_stream_storage_restore_keeps_a_backslash_u_name_of_a_form_dictionary(name, caplog) -> None:
    doc, form, _page_text = _page_doc(name, draw_form=True)
    try:
        want_font = doc.xref_get_key(form, "Resources/Font")
        assert name in want_font[1]
        want_render = _render(doc)
        storage = capture_stream_storage(doc, form)
        doc.update_stream(form, b" ", compress=False)
        assert _render(doc) != want_render

        with caplog.at_level(logging.WARNING):
            assert restore_stream_storage(doc, storage) is True
        assert _warnings(caplog) == []
        assert doc.xref_get_key(form, "Resources/Font") == want_font
        assert doc.xref_stream_raw(form) == storage.raw
        assert _render(doc) == want_render
        doc = _reopened(doc)
        assert doc.xref_get_key(form, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_patch_revert_keeps_a_backslash_u_key_of_the_content_stream(name, caplog) -> None:
    doc, _form, _page_text = _page_doc(name, content_dict=f"<</{name}/Kept>>")
    try:
        page = doc[0]
        xref = page.get_contents()[0]
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        assert doc.xref_get_key(xref, "Filter") == ("name", "/FlateDecode")
        raw = doc.xref_stream_raw(xref)
        applied = apply_patchset(doc, page, _grow_every_stream(doc, page))
        assert doc.xref_stream_raw(xref) != raw

        with caplog.at_level(logging.WARNING):
            assert applied.revert(doc) is True
        assert _warnings(caplog) == []
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        assert doc.xref_stream_raw(xref) == raw
    finally:
        doc.close()


# ------------------------------------------------ annotation dictionary restore


@pytest.mark.parametrize("name", NAMES)
def test_annotation_dictionary_restore_keeps_a_backslash_u_name(name) -> None:
    doc = fitz.open()
    page = doc.new_page()
    xref = page.add_text_annot((50, 50), "note").xref
    plain = doc.xref_object(xref, compressed=True)
    assert "\\" not in plain  # no escape yet: this text is exact
    doc.update_object(xref, f"{plain[:-2]}/{name}/Kept>>")
    doc = _reopened(doc)
    try:
        page = doc[0]
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        backup = capture_annotation_parent_refs(doc, page)
        doc.update_object(xref, plain)  # disturbed, as insert_pdf disturbs a copied page's annotations

        restore_annotation_parent_refs(doc, backup)
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
    finally:
        doc.close()


# ---------------------------------------------------------- page-graph snapshot


@pytest.mark.parametrize("name", NAMES)
def test_page_snapshot_restore_keeps_a_backslash_u_name_of_the_page_resources(name) -> None:
    doc, _form, page_text = _page_doc(name, page_font_name=name)
    try:
        page_xref = doc.page_xref(0)
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        want_render = _render(doc)
        snapshot = capture_page_graph(doc, 0, xref_epoch=0)
        doc.update_object(page_xref, page_text("/Rotate 90"))
        assert _render(doc) != want_render

        restore_page_graph(doc, 0, snapshot, xref_epoch=0)
        assert doc.xref_get_key(page_xref, "Rotate") == ("null", "null")
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


# ------------------------------------------------- save-time protected rollback


@pytest.mark.parametrize("name", NAMES)
def test_protected_page_rollback_keeps_a_backslash_u_key_of_the_content_stream(name, caplog) -> None:
    doc, _form, _page_text = _page_doc(name, content_dict=f"<</{name}/Kept>>")
    try:
        xref = doc[0].get_contents()[0]
        raw, decoded = doc.xref_stream_raw(xref), doc.xref_stream(xref)
        guard = _ProtectedPageGuard(doc, [0])
        doc.update_stream(xref, b"q Q " + decoded)  # a save hook rewrote the protected page
        assert guard.violations_in_place(doc) == [0]

        with caplog.at_level(logging.WARNING):
            assert guard.roll_back(doc, [0]) is True
        assert _warnings(caplog) == []
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        assert doc.xref_stream_raw(xref) == raw
        assert doc.xref_stream(xref) == decoded
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_protected_page_rollback_without_the_decoded_original_keeps_the_dictionary(name, monkeypatch) -> None:
    """The fallback (the original content cannot be re-decoded) writes the raw
    bytes, which drops ``/Filter``, then the dictionary: that second write must
    land, or a filtered stream is left as encoded bytes with no filter."""
    doc, _form, _page_text = _page_doc(name, content_dict=f"<</{name}/Kept>>")
    try:
        xref = doc[0].get_contents()[0]
        raw, decoded = doc.xref_stream_raw(xref), doc.xref_stream(xref)
        guard = _ProtectedPageGuard(doc, [0])
        monkeypatch.setattr(_StreamRecord, "decoded", lambda self: None)
        doc.update_stream(xref, b"q Q " + decoded)

        guard.roll_back(doc, [0])
        assert doc.xref_get_key(xref, "Filter") == ("name", "/FlateDecode")
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        assert doc.xref_stream_raw(xref) == raw
        assert doc.xref_stream(xref) == decoded
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_protected_page_rollback_keeps_a_backslash_u_name_of_the_page_resources(name, caplog) -> None:
    """A rollback whose hook left ``/Contents`` alone writes nothing to the page
    dictionary (``xref_set_key`` would print the whole dictionary through the
    same decode and rename the page's own font name)."""
    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page_xref = doc.page_xref(0)
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        xref = doc[0].get_contents()[0]
        guard = _ProtectedPageGuard(doc, [0])
        doc.update_stream(xref, b"q Q " + doc.xref_stream(xref))

        with caplog.at_level(logging.WARNING):
            assert guard.roll_back(doc, [0]) is True
        assert _warnings(caplog) == []
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
    finally:
        doc.close()


# ------------------------------------------------------------ signed append save


def _signed_pdf(path: Path, name: str) -> Path:
    """A one-page PDF with a signed signature field whose page's inline
    /Resources call the font ``/<name>`` and whose content selects it."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=80)
    page_xref = page.xref
    parent = doc.xref_get_key(page_xref, "Parent")[1]
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    contents = _new_stream(doc, "<<>>", f"BT /{name} 24 Tf 10 30 Td (Hello) Tj ET".encode(), compress=False)
    signature = doc.get_new_xref()
    doc.update_object(
        signature,
        "<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached/ByteRange[0 0 0 0]/Contents<00>>>",
    )
    field = doc.get_new_xref()
    doc.update_object(
        field,
        f"<</FT/Sig/T(S1)/V {signature} 0 R/Type/Annot/Subtype/Widget/Rect[0 0 0 0]/P {page_xref} 0 R/F 132>>",
    )
    doc.update_object(
        page_xref,
        f"<</Type/Page/Parent {parent}/MediaBox[0 0 200 80]/Resources<</Font<</{name} {font} 0 R>>>>"
        f"/Contents {contents} 0 R/Annots[{field} 0 R]>>",
    )
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<</Fields[{field} 0 R]/SigFlags 3>>")
    doc.save(str(path))
    doc.close()
    return path


def _span_fonts(page: fitz.Page) -> set[str]:
    blocks = page.get_text("rawdict")["blocks"]
    return {span["font"] for block in blocks for line in block.get("lines", []) for span in line["spans"]}


@pytest.mark.parametrize("name", NAMES)
def test_signed_append_save_keeps_a_backslash_u_name_of_a_replayed_page(name, tmp_path, caplog) -> None:
    """The replay writes each changed object of the live document onto the
    signed source; the page (changed by an added highlight) keeps its font name."""
    from model.signed_append_save import try_append_state_onto_source
    from model.text_commit.inspect import document_has_a_signed_signature

    source = _signed_pdf(tmp_path / "signed.pdf", name)
    state = fitz.open(str(source))
    try:
        assert document_has_a_signed_signature(state)
        page_xref = state.page_xref(0)
        want_font = state.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        assert _span_fonts(state[0]) == {"Helvetica"}
        state[0].add_highlight_annot(fitz.Rect(10, 10, 60, 40))
        stage = tmp_path / "stage.pdf"

        with caplog.at_level(logging.WARNING):
            assert try_append_state_onto_source(state, str(source), str(stage)) is None
        assert _warnings(caplog) == []
        saved = fitz.open(str(stage))
        try:
            assert saved.xref_get_key(page_xref, "Resources/Font") == want_font
            assert _span_fonts(saved[0]) == {"Helvetica"}
        finally:
            saved.close()
    finally:
        state.close()


# ------------------------------------------- legacy /Dests rebuilt after a delete


@pytest.mark.parametrize("name", NAMES)
def test_repointing_legacy_dests_after_a_page_delete_keeps_a_backslash_u_name(name) -> None:
    """Deleting page 3 drops its named destination from the catalog's
    ``/Dests``; the rebuilt dictionary keeps the other name byte for byte, so
    the link that selects it still resolves."""
    from model import page_refs

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=200, height=200)
    pages = [doc.page_xref(i) for i in range(3)]
    link = doc.get_new_xref()
    doc.update_object(link, f"<</Type/Annot/Subtype/Link/Rect[10 10 100 100]/Border[0 0 0]/Dest/{name}>>")
    doc.xref_set_key(pages[0], "Annots", f"[{link} 0 R]")
    dests = doc.get_new_xref()
    doc.update_object(dests, f"<</{name}[{pages[1]} 0 R/XYZ 0 200 0]/gone[{pages[2]} 0 R/Fit]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Dests", f"{dests} 0 R")
    doc = _reopened(doc)
    try:
        assert doc.xref_get_key(dests, name)[0] == "array"
        assert doc[0].get_links()[0]["page"] == 1
        doc.delete_page(2)
        page_refs.repoint_page_references(doc, {pages[2]: None})
        doc = _reopened(doc)
        assert doc.xref_get_key(dests, "gone") == ("null", "null")
        assert doc.xref_get_key(dests, name)[0] == "array"
        assert doc[0].get_links()[0]["page"] == 1
    finally:
        doc.close()


# ------------------------------------- inherited resources copied onto a page


@pytest.mark.parametrize("name", NAMES)
def test_copying_inherited_resources_onto_the_page_keeps_a_backslash_u_name(name) -> None:
    """The paint-state writer gives a page that inherits an indirect
    ``/Resources`` its own copy before registering anything in it; the copy
    keeps the font name the page's content selects."""
    from model.text_paint_state import _ensure_resources, page_resource_holder

    doc = fitz.open()
    page = doc.new_page(width=200, height=80)
    page_xref = page.xref
    parent = int(doc.xref_get_key(page_xref, "Parent")[1].split()[0])
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    resources = doc.get_new_xref()
    doc.update_object(resources, f"<</Font<</{name} {font} 0 R>>>>")
    contents = _new_stream(doc, "<<>>", f"BT /{name} 24 Tf 10 30 Td (Hello) Tj ET".encode(), compress=False)
    doc.update_object(page_xref, f"<</Type/Page/Parent {parent} 0 R/MediaBox[0 0 200 80]/Contents {contents} 0 R>>")
    doc.xref_set_key(parent, "Resources", f"{resources} 0 R")
    doc = _reopened(doc)
    try:
        page = doc[0]
        holder = page_resource_holder(doc, page)
        assert holder == (resources, "")
        want_font = doc.xref_get_key(resources, "Font")
        want_render = _render(doc)

        _ensure_resources(doc, page_xref, holder)
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


# ----------------------------------------------- /Annots held in its own object


@pytest.mark.parametrize("appender", ["annotation_tool", "navigation_graft"])
@pytest.mark.parametrize("name", NAMES)
def test_appending_to_an_indirect_annots_array_keeps_a_backslash_u_name(name, appender) -> None:
    """A page whose ``/Annots`` is an array object of its own: the two
    appenders read that array and write it back with one more reference; an
    entry that holds such a name keeps it."""
    from model.navigation_graft import NavigationGraft
    from model.tools.annotation_tool import AnnotationTool

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page_xref = page.xref
    note = page.add_text_annot((50, 50), "note").xref
    array = doc.get_new_xref()
    doc.update_object(array, f"[{note} 0 R <</Type/Annot/Subtype/Square/Rect[0 0 10 10]/{name}/Kept>>]")
    doc.xref_set_key(page_xref, "Annots", f"{array} 0 R")
    link = doc.get_new_xref()
    doc.update_object(link, "<</Type/Annot/Subtype/Link/Rect[10 10 100 100]/Border[0 0 0]>>")
    doc = _reopened(doc)
    try:
        literal = f"/{name}".encode()
        assert literal in doc.tobytes()
        if appender == "annotation_tool":
            assert AnnotationTool._reattach_annot(None, doc[0], link, "Link") is True  # type: ignore[arg-type]
        else:
            NavigationGraft(doc)._append_annots(page_xref, [link])
        assert doc.xref_get_key(page_xref, "Annots") == ("xref", f"{array} 0 R")
        assert literal in doc.tobytes()
        assert doc.xref_object(array, compressed=True).endswith(f"{link} 0 R]")
    finally:
        doc.close()


# ------------------------------------------------------ new font stream dedupe


def test_font_stream_dedupe_keeps_streams_whose_dictionaries_differ_by_a_backslash_u_name() -> None:
    """Two new font streams with equal bytes are one stream only when their
    dictionaries are equal too: ``/X\\u0031`` is not ``/X1``."""
    from model.font_stream_compaction import compact_new_font_streams

    doc = fitz.open()
    doc.new_page()
    start = doc.xref_length()
    program = bytes(range(64))
    escaped = _new_stream(doc, "<</Length1 64/X\\u0031 1>>", program, compress=False)
    plain = _new_stream(doc, "<</Length1 64/X1 1>>", program, compress=False)
    owners = []
    for stream in (escaped, plain):
        owner = doc.get_new_xref()
        doc.update_object(owner, f"<</Type/FontDescriptor/FontName/F/FontFile2 {stream} 0 R>>")
        owners.append(owner)
    try:
        compact_new_font_streams(doc, start)
        assert doc.xref_get_key(owners[0], "FontFile2") == ("xref", f"{escaped} 0 R")
        assert doc.xref_get_key(owners[1], "FontFile2") == ("xref", f"{plain} 0 R")
        assert doc.xref_get_key(escaped, "X\\u0031") == ("int", "1")
    finally:
        doc.close()


# ------------------------------------------------------------ the exact set_key


def _object_texts(doc: fitz.Document) -> list[str]:
    """The trailer and every slot as exact text, to compare two documents."""
    from utils.pdf_object_source import xref_object_exact

    texts = [xref_object_exact(doc, -1, compressed=True)]
    for xref in range(1, doc.xref_length()):
        try:
            texts.append(xref_object_exact(doc, xref, compressed=True))
        except RuntimeError as exc:
            texts.append(f"! {exc}")
    return texts


def _set_key_fixture() -> tuple[bytes, dict[str, int | float]]:
    """A saved document to edit, none of its objects holding a backslash-u name.

    ``target`` is a dictionary whose ``/Res`` is an indirect resources
    dictionary (``/Font`` direct in it) and whose ``/IArr``, ``/INum`` and
    ``/Gone`` refer to an array object, a number object and no object; there
    is a stream, and the array and number objects are targets too.  The
    string ``/S`` holds a literal backslash-u: the printer doubles the
    backslash, so it is not an escape."""
    doc = fitz.open()
    page = doc.new_page()
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    resources = doc.get_new_xref()
    doc.update_object(resources, f"<</Font<</F1 {font} 0 R>>>>")
    array = doc.get_new_xref()
    doc.update_object(array, "[1 2 3]")
    number = doc.get_new_xref()
    doc.update_object(number, "42")
    target = doc.get_new_xref()
    doc.update_object(
        target,
        f"<</Type/Test/A 1/Sub<</X 2>>/Arr[1 2 3]/S(caf\\351 \\\\u0031)/N/Name/Res {resources} 0 R"
        f"/IArr {array} 0 R/INum {number} 0 R/Gone 999 0 R>>",
    )
    stream = _new_stream(doc, "<</K/V>>", b"q Q", compress=False)
    places = {
        "target": target,
        "resources": resources,
        "array": array,
        "number": number,
        "stream": stream,
        "page": page.xref,
        "past the end": doc.xref_length(),
        "just below the end": doc.xref_length() - 0.5,  # PyMuPDF checks 1 <= xref <= length - 1
    }
    return doc.tobytes(), places


# (where, key, value): ``where`` names an xref of the fixture or is one.
_SET_KEY_CASES = [
    ("target", "A", "2"),
    ("target", "B", "/Foo"),
    ("target", "Sub/X", "[1 0 R]"),
    ("target", "Sub/Y/Z", "<</Q true>>"),
    ("target", "A", "null"),
    ("target", "Ref", "page"),
    ("target", "S", "(café)"),
    ("target", "H", "<FEFF0041>"),
    ("target", "A", "abc"),  # a bare word reads as null
    # A direct level that is not a dictionary becomes one (MuPDF's pdf_dict_putp).
    ("target", "Arr/X", "/V"),
    ("target", "A/X", "1"),
    # MuPDF's split of a key path: an empty level.
    ("target", "/Lead", "1"),
    ("target", "A//B", "1"),
    ("stream", "K", "/W"),
    ("resources", "Font/F1", "null"),
    (-1, "Custom", "/X"),
    (-1, "Custom", "null"),
    # Refused before anything is written: a level that is an indirect object
    # but no dictionary, an object that is no dictionary.
    ("target", "IArr/X", "1"),
    ("target", "INum/X", "1"),
    ("target", "Gone/X", "1"),
    ("array", "A", "1"),
    ("number", "A", "1"),
    ("array", "A", "[1 2"),
    ("target", "K" * 300, "1"),  # MuPDF reads no key path of 256 bytes or more
    ("target", "A B", "1"),
    ("target", "", "1"),
    ("target", 5, "1"),
    ("target", "A", "/a b"),
    ("target", "A", ""),
    ("target", "A", 5),
    (0, "A", "1"),
    ("past the end", "A", "1"),
    ("just below the end", "A", "1"),
    (-2, "A", "1"),
]


@pytest.mark.parametrize(("where", "key", "value"), _SET_KEY_CASES, ids=[str(case) for case in _SET_KEY_CASES])
def test_exact_set_key_does_what_xref_set_key_does_to_objects_without_such_a_name(where, key, value, caplog) -> None:
    """Same objects afterwards (the trailer and every slot) and the same
    exception type and arguments wherever PyMuPDF's method leaves no
    placeholder behind (the tests after this one pin where it does).  No
    fallback warning."""
    from utils.pdf_object_source import xref_set_key_exact

    data, places = _set_key_fixture()
    xref = places.get(where, where) if isinstance(where, str) else where
    if value == "page":
        value = f"{places['page']} 0 R"
    outcomes = []
    for setter in (fitz.Document.xref_set_key, xref_set_key_exact):
        doc = fitz.open("pdf", data)
        try:
            try:
                with caplog.at_level(logging.WARNING, logger="utils.pdf_object_source"):
                    setter(doc, xref, key, value)
                raised = None
            except Exception as exc:
                raised = (type(exc), exc.args)
            outcomes.append((raised, _object_texts(doc)))
        finally:
            doc.close()
    assert outcomes[1] == outcomes[0]
    assert _warnings(caplog) == []


# Where PyMuPDF's method leaves its placeholder: it puts the string
# ``(fitz: replace me!)`` at the key, prints the whole object, swaps the value
# in for ``/<key>(fitz: replace me!)`` as text and parses the object again.
_PLACEHOLDER = "fitz: replace me!"


def _changed_slots(before: list[str], after: list[str]) -> set[int]:
    """The xrefs (``-1``: the trailer) whose exact text differs."""
    return {index or -1 for index, (old, new) in enumerate(zip(before, after)) if old != new}


@pytest.mark.parametrize("object_streams", [False, True], ids=["plain", "object streams"])
@pytest.mark.parametrize(
    ("key", "value", "want"),
    [
        ("Res/Font/F1", "null", ("null", "null")),
        ("Res/Font/F2", "1 0 R", ("xref", "1 0 R")),
        ("Res/New/Deep", "/V", ("name", "/V")),
    ],
)
def test_exact_set_key_sets_a_key_behind_an_indirect_dictionary_in_that_dictionary(
    key, value, want, object_streams, tmp_path
) -> None:
    """A key path through an indirect dictionary is set in that dictionary,
    where ``xref_get_key`` reads it, and no other object changes; a full and
    an incremental save keep it, also when the file keeps its objects in
    object streams.  PyMuPDF's method puts its placeholder there (an existing
    key) and then prints the object, which shows only the reference, so the
    placeholder stays in place of the value; a missing key raises."""
    from utils.pdf_object_source import xref_key_holder, xref_set_key_exact

    data, places = _set_key_fixture()
    if object_streams:
        with fitz.open("pdf", data) as plain:
            data = plain.tobytes(use_objstms=1)
    target, resources = places["target"], places["resources"]
    rest = key.split("/", 1)[1]
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    doc = fitz.open(str(path))
    try:
        before = _object_texts(doc)
        assert xref_key_holder(doc, target, key) == resources
        xref_set_key_exact(doc, target, key, value)
        assert _changed_slots(before, _object_texts(doc)) == {resources}
        assert doc.xref_get_key(target, key) == want
        assert doc.xref_get_key(resources, rest) == want
        assert doc.xref_get_key(target, "Res") == ("xref", f"{resources} 0 R")
        doc.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
    with fitz.open(str(path)) as incremental:
        rewritten = incremental.tobytes()
    for saved in (path.read_bytes(), rewritten):
        with fitz.open("pdf", saved) as reopened:
            assert reopened.xref_get_key(target, key) == want
            assert not any(_PLACEHOLDER in text for text in _object_texts(reopened))

    doc = fitz.open("pdf", data)
    try:
        if key == "Res/Font/F1":
            fitz.Document.xref_set_key(doc, target, key, value)
            assert doc.xref_get_key(resources, rest) == ("string", _PLACEHOLDER)
        else:
            with pytest.raises(Exception, match="has indirects"):
                fitz.Document.xref_set_key(doc, target, key, value)
    finally:
        doc.close()


def test_exact_set_key_stores_null_behind_an_indirect_dictionary_as_null() -> None:
    """``null`` is stored at the key, not a deleted key (``xref_get_key``
    reads both as null): MuPDF's ``pdf_dict_putp`` would delete it."""
    from utils.pdf_object_source import xref_object_exact, xref_set_key_exact

    data, places = _set_key_fixture()
    with fitz.open("pdf", data) as doc:
        xref_set_key_exact(doc, places["target"], "Res/Font/F1", "null")
        assert xref_object_exact(doc, places["resources"], compressed=True) == "<</Font<</F1 null>>>>"


def test_exact_set_key_follows_a_level_that_is_a_stream_into_its_dictionary() -> None:
    """A level that refers to a stream is followed into the stream's
    dictionary (``AP/N/BBox``); the stream's bytes stay."""
    from utils.pdf_object_source import xref_key_holder, xref_set_key_exact

    data, places = _set_key_fixture()
    target, stream = places["target"], places["stream"]
    with fitz.open("pdf", data) as doc:
        xref_set_key_exact(doc, target, "Str", f"{stream} 0 R")
        before = _object_texts(doc)
        assert xref_key_holder(doc, target, "Str/K") == stream
        xref_set_key_exact(doc, target, "Str/K", "/W")
        assert _changed_slots(before, _object_texts(doc)) == {stream}
        assert doc.xref_get_key(stream, "K") == ("name", "/W")
        assert doc.xref_stream(stream) == b"q Q"


def _reference_chain_doc() -> tuple[bytes, dict[str, int]]:
    """``dict`` holds the resources; ``ref1`` is an object that is only a
    reference to it, ``ref2`` a reference to ``ref1``; ``owner`` refers to
    ``ref2`` (MuPDF reads such objects and resolves the chain).  The
    references are made with MuPDF: ``update_object`` parses a top-level
    ``4 0 R`` as the number 4."""
    mupdf = fitz.mupdf
    doc = fitz.open()
    doc.new_page()
    pdf = mupdf.pdf_document_from_fz_document(doc.this)
    dictionary = doc.get_new_xref()
    doc.update_object(dictionary, "<</XObject<</Im1 1 0 R>>>>")
    ref1 = doc.get_new_xref()
    mupdf.pdf_update_object(pdf, ref1, mupdf.pdf_new_indirect(pdf, dictionary, 0))
    ref2 = doc.get_new_xref()
    mupdf.pdf_update_object(pdf, ref2, mupdf.pdf_new_indirect(pdf, ref1, 0))
    owner = doc.get_new_xref()
    doc.update_object(owner, f"<</Res {ref2} 0 R>>")
    data = doc.tobytes()
    assert f"{ref2} 0 obj\n{ref1} 0 R".encode() in data  # a reference, not a number
    return data, {"dict": dictionary, "ref1": ref1, "ref2": ref2, "owner": owner}


@pytest.mark.parametrize(
    ("where", "key"),
    [("owner", "Res/XObject/Im1"), ("owner", "Res/New"), ("ref2", "XObject/Im1"), ("ref1", "New/Deep")],
)
def test_the_holder_of_a_key_behind_a_chain_of_references_is_the_object_at_its_end(where, key) -> None:
    """MuPDF follows a chain of references (a level, or the object itself) to
    the dictionary at its end and writes there: that object is the holder,
    not the first reference of the chain."""
    from utils.pdf_object_source import xref_key_holder, xref_object_exact, xref_set_key_exact

    data, places = _reference_chain_doc()
    with fitz.open("pdf", data) as doc:
        before = xref_object_exact(doc, places["dict"], compressed=True)
        assert xref_key_holder(doc, places[where], key) == places["dict"]
        xref_set_key_exact(doc, places[where], key, "/V")
        assert xref_object_exact(doc, places["dict"], compressed=True) != before
        assert doc.xref_get_key(places[where], key) == ("name", "/V")
    with fitz.open("pdf", data) as doc:
        for name in ("ref1", "ref2", "owner"):
            assert xref_key_holder(doc, places[name], "Unrelated") == (places["dict"] if name != "owner" else places["owner"])


@pytest.mark.parametrize(
    ("where", "key"),
    [
        ("target", "A B"),
        ("target", ""),
        ("target", 5),
        ("target", "K" * 300),
        ("target", "IArr/X"),
        ("array", "A"),
        (0, "A"),
        ("past the end", "A"),
        (-2, "A"),
    ],
    ids=str,
)
def test_xref_key_holder_raises_what_the_setter_raises(where, key) -> None:
    from utils.pdf_object_source import xref_key_holder, xref_set_key_exact

    data, places = _set_key_fixture()
    xref = places.get(where, where) if isinstance(where, str) else where
    with fitz.open("pdf", data) as doc:
        with pytest.raises(Exception) as wanted:
            xref_set_key_exact(doc, xref, key, "1")
        with pytest.raises(type(wanted.value)) as got:
            xref_key_holder(doc, xref, key)
        assert got.value.args == wanted.value.args
    closed = fitz.open("pdf", data)
    closed.close()
    with pytest.raises(ValueError, match="document closed"):
        xref_key_holder(closed, 1, "A")


_NOT_ONE_OBJECT = ["[1 2", "1 2", "/A /B", "1] /X [2", "1 0 R/X 2", "<</A 1>> /Z 9", "R", "]", "(a", "% c"]


@pytest.mark.parametrize("value", _NOT_ONE_OBJECT)
def test_exact_set_key_refuses_a_value_that_is_not_one_object_and_writes_nothing(value) -> None:
    """The value is parsed on its own first: one that is not exactly one PDF
    object raises and no object changes.  PyMuPDF's method swaps it into the
    printed object as text, so it raises after the placeholder is in place,
    adds keys of its own (``1 0 R/X 2``) or stores null (``R``)."""
    from utils.pdf_object_source import xref_set_key_exact

    data, places = _set_key_fixture()
    for where, key in (("target", "A"), ("target", "New"), ("target", "Res/Font/F1"), (-1, "New")):
        xref = places.get(where, where) if isinstance(where, str) else where
        doc = fitz.open("pdf", data)
        try:
            before = _object_texts(doc)
            with pytest.raises((ValueError, fitz.mupdf.FzErrorBase)):
                xref_set_key_exact(doc, xref, key, value)
            assert _object_texts(doc) == before, (where, key)
        finally:
            doc.close()


@pytest.mark.parametrize("key", ["F#20G", "Fé", "Trail/"])
def test_exact_set_key_sets_a_key_the_printer_writes_differently(key) -> None:
    """PyMuPDF's method looks for ``/<key>(fitz: replace me!)`` in the printed
    object; a key printed otherwise (``#`` and non-ASCII escaped) or one with a
    trailing slash (MuPDF ends the path there) is not found and the
    placeholder stays.  The helper sets the value."""
    from utils.pdf_object_source import xref_set_key_exact

    data, places = _set_key_fixture()
    target = places["target"]
    for setter, want in ((xref_set_key_exact, ("name", "/V")), (fitz.Document.xref_set_key, ("string", _PLACEHOLDER))):
        doc = fitz.open("pdf", data)
        try:
            setter(doc, target, key, "/V")
            assert doc.xref_get_key(target, key) == want
        finally:
            doc.close()


_GUARD_WHERES = ["target", "page", "array", "number", -1]
_GUARD_KEYS = [
    "A", "New", "Sub/X", "Sub/New/Deep", "Res/Font/F1", "Res/Font/F9", "Res/New/Deep", "Root/PdfeKey",
    "IArr/X", "INum/X", "Gone/X", "A/X", "Arr/X", "/Lead", "Trail/", "A//B", "/", "F#20G", "Fé",
]
# value -> what xref_get_key reads back after a successful set
_GUARD_VALUES = {
    "1": ("int", "1"),
    "null": ("null", "null"),
    "/V": ("name", "/V"),
    "(s)": ("string", "s"),
    "[1 0 R/Fit]": ("array", "[1 0 R/Fit]"),
    "<</K 1>>": ("dict", "<</K 1>>"),
    "abc": ("null", "null"),
    **{value: None for value in ("1 2", "[1 2", "1 0 R/X 2", "R", "]")},
}


def _guard_refuses(where: str | int, key: str, value: str) -> bool:
    """Whether the class guard's case must raise: a target that is no
    dictionary, a value that is not one object, or a path of ``target``
    through its indirect array, number or missing object."""
    return (
        where in ("array", "number")
        or _GUARD_VALUES[value] is None
        or where == "target" and key in ("IArr/X", "INum/X", "Gone/X")
    )


def test_exact_set_key_never_leaves_a_placeholder_and_changes_only_the_holder() -> None:
    """The class guard, over every target kind, key path and value: each case
    raises exactly when it must (``_guard_refuses``); no object holds
    PyMuPDF's placeholder afterwards; a call that raises changes no object
    and its holder query raises too; one that returns changes only the object
    ``xref_key_holder`` named, and ``xref_get_key`` reads the value back
    through the path."""
    from utils.pdf_object_source import xref_key_holder, xref_set_key_exact

    data, places = _set_key_fixture()
    doc = fitz.open("pdf", data)
    pristine = _object_texts(doc)
    doc.close()
    for where in _GUARD_WHERES:
        xref = places.get(where, where) if isinstance(where, str) else where
        for key in _GUARD_KEYS:
            for value, want in _GUARD_VALUES.items():
                case = (where, key, value)
                doc = fitz.open("pdf", data)
                try:
                    try:
                        holder = xref_key_holder(doc, xref, key)
                    except Exception:
                        holder = None
                    try:
                        xref_set_key_exact(doc, xref, key, value)
                    except Exception:
                        assert _guard_refuses(where, key, value), case
                        assert _object_texts(doc) == pristine, case
                        if want is not None:  # refused for the path: the holder query refuses it too
                            assert holder is None, case
                        continue
                    assert not _guard_refuses(where, key, value), case
                    after = _object_texts(doc)
                    assert not any(_PLACEHOLDER in text for text in after), case
                    assert holder is not None and _changed_slots(pristine, after) <= {holder}, case
                    assert doc.xref_get_key(xref, key) == want, case
                finally:
                    doc.close()


def test_exact_set_key_raises_what_xref_set_key_raises_for_a_closed_or_non_pdf_document() -> None:
    import pymupdf

    import utils.pdf_object_source as pdf_object_source
    from utils.pdf_object_source import xref_set_key_exact

    assert pdf_object_source._INVALID_NAME_CHARS == pymupdf.INVALID_NAME_CHARS  # the key and value checks

    text_doc = fitz.open(stream=b"hello", filetype="txt")
    closed = fitz.open()
    closed.new_page()
    closed.close()
    try:
        for doc in (text_doc, closed):
            with pytest.raises(Exception) as wanted:
                fitz.Document.xref_set_key(doc, 1, "A", "1")
            with pytest.raises(type(wanted.value)) as got:
                xref_set_key_exact(doc, 1, "A", "1")
            assert got.value.args == wanted.value.args
    finally:
        text_doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_exact_set_key_keeps_a_backslash_u_name_elsewhere_in_the_object(name, caplog) -> None:
    """Setting one key of a page whose inline /Resources call the font
    ``/<name>`` keeps that name; PyMuPDF's own renames it (or, for a lone
    surrogate, raises and leaves its placeholder in the edited key)."""
    from utils.pdf_object_source import xref_set_key_exact

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page_xref = doc.page_xref(0)
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        want_render = _render(doc)

        with caplog.at_level(logging.WARNING):
            xref_set_key_exact(doc, page_xref, "Tabs", "/S")
        assert _warnings(caplog) == []
        assert doc.xref_get_key(page_xref, "Tabs") == ("name", "/S")
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
        doc = _reopened(doc)
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render

        try:
            fitz.Document.xref_set_key(doc, page_xref, "Tabs", "/R")
        except UnicodeEncodeError:
            assert doc.xref_get_key(page_xref, "Tabs") == ("string", "fitz: replace me!")
        else:
            assert doc.xref_get_key(page_xref, "Resources/Font") != want_font
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_pymupdf_methods_inside_exact_set_key_keep_a_backslash_u_name(name) -> None:
    """``Annot.set_colors`` and ``Document.set_metadata`` call ``xref_set_key``
    on the document; inside ``exact_set_key(doc)`` that is the exact helper."""
    from utils.pdf_object_source import exact_set_key

    doc = fitz.open()
    page = doc.new_page()
    xref = page.add_rect_annot(fitz.Rect(10, 10, 50, 50)).xref
    plain = doc.xref_object(xref, compressed=True)
    assert "\\" not in plain  # no escape yet: this text is exact
    doc.update_object(xref, f"{plain[:-2]}/{name}/Kept>>")
    info = doc.get_new_xref()
    doc.update_object(info, f"<</Title(old)/{name}(custom)>>")
    doc.xref_set_key(-1, "Info", f"{info} 0 R")
    doc = _reopened(doc)
    try:
        page = doc[0]
        annot = page.load_annot(xref)
        with exact_set_key(doc):
            annot.set_colors(stroke=(1, 0, 0))
            doc.set_metadata({"title": "new"})
        assert doc.xref_get_key(xref, name) == ("name", "/Kept")
        assert doc.xref_get_key(xref, "C") == ("array", "[1 0 0]")
        assert doc.xref_get_key(info, name) == ("string", "custom")
        assert doc.xref_get_key(info, "Title") == ("string", "new")
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_replace_image_inside_exact_set_key_empties_a_dictionary_with_a_backslash_u_key(name) -> None:
    """``Page.replace_image`` (the optimizer's image rewrite) nulls every key of
    the old image through ``xref_set_key`` before copying the new one in: no
    key is left holding PyMuPDF's placeholder, and a lone surrogate no longer
    makes it raise."""
    from utils.pdf_object_source import exact_set_key

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    small = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
    image = page.insert_image(fitz.Rect(10, 10, 60, 60), pixmap=small)
    image = page.get_images()[0][0]
    plain = doc.xref_object(image, compressed=True)
    assert "\\" not in plain
    doc.update_object(image, f"{plain[:-2]}/{name}/Kept>>")
    doc = _reopened(doc)
    try:
        page = doc[0]
        wide = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 2), False)

        with exact_set_key(doc):
            page.replace_image(image, pixmap=wide)
        assert doc.xref_get_key(image, "Width") == ("int", "8")
        assert doc.xref_get_key(image, name) == ("null", "null")
        assert [k for k in doc.xref_get_keys(image) if doc.xref_get_key(image, k)[0] == "string"] == []
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_editing_the_metadata_keeps_a_backslash_u_key_of_the_info_dictionary(name, tmp_path) -> None:
    """``PDFModel.set_editable_metadata`` writes the Info dictionary key by key;
    a key of the document's own keeps its name."""
    from model.pdf_model import PDFModel

    doc = fitz.open()
    doc.new_page()
    info = doc.get_new_xref()
    doc.update_object(info, f"<</Title(Old)/{name}(custom)>>")
    doc.xref_set_key(-1, "Info", f"{info} 0 R")
    path = tmp_path / "info.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        info = int(model.doc.xref_get_key(-1, "Info")[1].split()[0])
        assert model.doc.xref_get_key(info, name) == ("string", "custom")

        assert model.set_editable_metadata({"title": "New"}) is True
        assert model.doc.xref_get_key(info, name) == ("string", "custom")
        assert model.doc.metadata["title"] == "New"
    finally:
        model.close()


def test_a_failing_set_key_leaves_the_exception_its_caller_handles_alone() -> None:
    """A key set that fails while its caller handles another error (a rollback
    after a failure) raises its own error without frames, but the caller's
    error keeps its traceback, as with PyMuPDF's method."""
    from utils.pdf_object_source import xref_set_key_exact

    data, places = _set_key_fixture()
    doc = fitz.open("pdf", data)

    def fails_first() -> None:
        raise KeyError("original")

    try:
        with pytest.raises(KeyError) as caught:
            try:
                fails_first()
            except KeyError:
                with pytest.raises(Exception, match="has indirects"):
                    xref_set_key_exact(doc, places["target"], "IArr/X", "1")
                raise
        assert "fails_first" in [frame.name for frame in traceback.extract_tb(caught.value.__traceback__)]
    finally:
        doc.close()


def test_exact_set_key_routes_over_an_attribute_it_did_not_install_and_puts_it_back() -> None:
    """A block routes even when the instance already carries another
    ``xref_set_key`` (a spy), and puts that one back on the way out; one set
    inside the block by someone else is left as it is."""
    from utils.pdf_object_source import exact_set_key

    doc = fitz.open()
    try:

        def spy(xref: int, key: str, value: str) -> None:
            raise AssertionError("not routed")

        setattr(doc, "xref_set_key", spy)
        with exact_set_key(doc):
            assert vars(doc)["xref_set_key"] is not spy
        assert vars(doc)["xref_set_key"] is spy
        delattr(doc, "xref_set_key")

        with exact_set_key(doc):
            setattr(doc, "xref_set_key", spy)
        assert vars(doc)["xref_set_key"] is spy
    finally:
        doc.close()


def test_exact_set_key_routes_only_inside_its_block_and_nests() -> None:
    from utils.pdf_object_source import exact_set_key

    doc, other = fitz.open(), fitz.open()
    try:
        with exact_set_key(doc):
            assert "xref_set_key" in vars(doc)
            with exact_set_key(doc):
                pass
            assert "xref_set_key" in vars(doc)  # the inner block leaves the outer one's routing
            assert "xref_set_key" not in vars(other)
        assert "xref_set_key" not in vars(doc)
        with pytest.raises(KeyError):
            with exact_set_key(doc):
                raise KeyError("x")
        assert "xref_set_key" not in vars(doc)
        assert doc.xref_set_key.__func__ is fitz.Document.xref_set_key
    finally:
        doc.close()
        other.close()


@pytest.mark.skipif(sys.platform != "win32", reason="an open file blocks os.replace only on Windows")
@pytest.mark.parametrize(("key", "value"), [("IArr/X", "1"), ("A", "[1 2")], ids=["refused path", "MuPDF error"])
def test_a_kept_set_key_error_does_not_keep_the_closed_document_open(key, value, tmp_path) -> None:
    """A path through an indirect array raises, so does a value MuPDF cannot
    parse; kept past ``close()``, the error must not keep the file open (LS-3)."""
    from utils.pdf_object_source import xref_set_key_exact

    path = tmp_path / "doc.pdf"
    data, places = _set_key_fixture()
    path.write_bytes(data)
    doc = fitz.open(str(path))
    kept: list[BaseException] = []
    try:
        xref_set_key_exact(doc, places["target"], key, value)
    except Exception as exc:
        kept.append(exc)
    assert kept
    doc.close()
    gc.collect()
    replacement = tmp_path / "other.pdf"
    replacement.write_bytes(data)
    os.replace(replacement, path)  # PermissionError while the file is still open
    assert kept


def test_exact_set_key_falls_back_to_pymupdf_with_one_warning(monkeypatch, caplog) -> None:
    """Without the private API the helper does what ``xref_set_key`` does and
    warns once; ``xref_key_holder`` cannot tell and raises."""
    import utils.pdf_object_source as pdf_object_source

    data, places = _set_key_fixture()
    docs = [fitz.open("pdf", data), fitz.open("pdf", data)]
    try:
        monkeypatch.setattr(pdf_object_source, "_fallbacks_logged", set())
        # PyMuPDF itself needs the real names, so only the helper is told one is missing.
        missing = (*pdf_object_source._SET_KEY_API, "JM_not_in_this_version")
        monkeypatch.setattr(pdf_object_source, "_SET_KEY_API", missing)
        with caplog.at_level(logging.WARNING, logger="utils.pdf_object_source"):
            for doc, setter in zip(docs, (fitz.Document.xref_set_key, pdf_object_source.xref_set_key_exact)):
                setter(doc, places["target"], "A", "2")
                setter(doc, places["target"], "B", "3")
            with pytest.raises(RuntimeError):
                pdf_object_source.xref_key_holder(docs[1], places["target"], "Res/Font/F1")
        monkeypatch.undo()
        assert len(_warnings(caplog)) == 1
        assert _object_texts(docs[1]) == _object_texts(docs[0])
    finally:
        for doc in docs:
            doc.close()


def test_exact_set_key_does_not_print_the_object(monkeypatch) -> None:
    """Only the key changes: the object is not printed and parsed again (that
    round trip is where PyMuPDF's method renamed a backslash-u name), so a
    printer that fails does not reach the helper."""
    import pymupdf

    import utils.pdf_object_source as pdf_object_source

    def no_printer(*args):
        raise AssertionError("the object was printed")

    data, places = _set_key_fixture()
    doc = fitz.open("pdf", data)
    try:
        monkeypatch.setattr(fitz, "JM_object_to_buffer", no_printer)
        monkeypatch.setattr(pymupdf, "JM_object_to_buffer", no_printer)
        monkeypatch.setattr(fitz.mupdf, "pdf_print_obj", no_printer)
        pdf_object_source.xref_set_key_exact(doc, places["target"], "Res/Font/F1", "null")
        pdf_object_source.xref_set_key_exact(doc, -1, "Custom", "/X")
        monkeypatch.undo()
        assert doc.xref_get_key(places["resources"], "Font/F1") == ("null", "null")
        assert doc.xref_get_key(-1, "Custom") == ("name", "/X")
    finally:
        doc.close()


# ------------------------------------------- keys set on a page dictionary


@pytest.mark.parametrize("name", NAMES)
def test_registering_a_paint_resource_keeps_a_backslash_u_name_of_the_page_resources(name) -> None:
    """A styled text edit registers its graphics state in the page's inline
    ``/Resources`` (two keys set on the page dictionary); the page's font
    keeps its name."""
    from model.text_paint_state import ResourceUse, _ensure_resources, _register

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page_xref = doc.page_xref(0)
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        want_render = _render(doc)
        holder = _ensure_resources(doc, page_xref, None)
        assert holder == (page_xref, "Resources/")

        assert _register(doc, holder, ResourceUse("ExtGState", "GS0", "<</ca 1>>")) == "GS0"
        assert doc.xref_get_key(page_xref, "Resources/ExtGState/GS0")[0] == "dict"
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


@pytest.mark.parametrize("appender", ["annotation_tool", "navigation_graft"])
@pytest.mark.parametrize("name", NAMES)
def test_appending_to_the_page_annots_keeps_a_backslash_u_name_of_the_page_resources(name, appender) -> None:
    """``/Annots`` held in the page dictionary: appending a link sets it on
    the page, and the page's font keeps its name."""
    from model.navigation_graft import NavigationGraft
    from model.tools.annotation_tool import AnnotationTool

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page = doc[0]
        page_xref = page.xref
        page.add_text_annot((150, 50), "note")
        kind, annots = doc.xref_get_key(page_xref, "Annots")
        assert kind == "array"  # in the page dictionary
        link = doc.get_new_xref()
        doc.update_object(link, "<</Type/Annot/Subtype/Link/Rect[10 10 100 70]/Border[0 0 0]>>")
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        want_render = _render(doc)

        if appender == "annotation_tool":
            assert AnnotationTool._reattach_annot(None, page, link, "Link") is True  # type: ignore[arg-type]
        else:
            NavigationGraft(doc)._append_annots(page_xref, [link])
        assert doc.xref_get_key(page_xref, "Annots") == ("array", f"{annots[:-1]} {link} 0 R]")
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_protected_page_rollback_of_a_replaced_contents_keeps_a_backslash_u_name_of_the_page_resources(
    name, caplog
) -> None:
    """A save hook replaced the protected page's ``/Contents``: the rollback
    sets it back on the page dictionary, and the page's font keeps its name."""
    from utils.pdf_object_source import xref_object_exact

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page_xref = doc.page_xref(0)
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        want_contents = doc.xref_get_key(page_xref, "Contents")
        want_render = _render(doc)
        guard = _ProtectedPageGuard(doc, [0])
        extra = _new_stream(doc, "<<>>", b"q Q", compress=False)
        page_source = xref_object_exact(doc, page_xref, compressed=True)
        contents = f"/Contents {want_contents[1]}"
        assert contents in page_source
        doc.update_object(page_xref, page_source.replace(contents, f"/Contents[{want_contents[1]} {extra} 0 R]"))

        with caplog.at_level(logging.WARNING):
            assert guard.roll_back(doc, [0]) is True
        assert _warnings(caplog) == []
        assert doc.xref_get_key(page_xref, "Contents") == want_contents
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _render(doc) == want_render
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_deleting_an_image_keeps_a_backslash_u_name_of_the_page_resources(name, tmp_path) -> None:
    """Deleting an image clears its ``/XObject`` entry of the page's inline
    ``/Resources``: the entry, itself named with such an escape, is cleared,
    and the page's font keeps its name."""
    from model.pdf_content_ops import discover_native_image_invocations
    from model.pdf_model import PDFModel
    from model.pdf_object_ops import _remove_native_image_invocation

    image_name = f"Im{name}"
    doc = fitz.open()
    page = doc.new_page(width=200, height=80)
    parent = doc.xref_get_key(page.xref, "Parent")[1]
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    image = _new_stream(
        doc,
        "<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray/BitsPerComponent 8>>",
        b"\x80",
        compress=False,
    )
    contents = _new_stream(
        doc, "<<>>", f"BT /{name} 24 Tf 10 30 Td (Hello) Tj ET q 40 0 0 40 120 20 cm /{image_name} Do Q".encode(),
        compress=False,
    )
    doc.update_object(
        page.xref,
        f"<</Type/Page/Parent {parent}/MediaBox[0 0 200 80]/Contents {contents} 0 R"
        f"/Resources<</Font<</{name} {font} 0 R>>/XObject<</{image_name} {image} 0 R>>>>>>",
    )
    path = tmp_path / "image.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        page_xref = model.doc.page_xref(0)
        want_font = model.doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]
        assert _span_fonts(model.doc[0]) == {"Helvetica"}
        invocations = discover_native_image_invocations(model.doc, 1)
        assert len(invocations) == 1

        assert _remove_native_image_invocation(model, invocations[0]) is True
        assert model.doc.xref_get_key(page_xref, f"Resources/XObject/{image_name}") == ("null", "null")
        assert model.doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _span_fonts(model.doc[0]) == {"Helvetica"}
    finally:
        model.close()


@pytest.mark.parametrize("name", NAMES)
def test_a_refused_paint_state_takes_the_write_back_and_keeps_a_backslash_u_name_of_the_page(name) -> None:
    """A paint state that cannot be re-applied takes the written text back by
    setting the page's ``/Contents`` to what it was: the caller still sees the
    refusal (not an error raised in the rollback), and the page's font keeps
    its name."""
    from model.text_edit_refusal import TextEditRefused
    from model.text_paint_state import PaintColour, TextPaintState, WriteStyle, paint_state_applied

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page = doc[0]
        page_xref = page.xref
        font_entry = doc.xref_get_key(page_xref, f"Resources/Font/{name}")
        assert font_entry[0] == "xref"
        before = page.get_contents()
        want_render = _render(doc)
        style = WriteStyle(TextPaintState(fill=PaintColour("pattern", ("P0",))))

        with pytest.raises(TextEditRefused):
            with paint_state_applied(page, style):
                page.insert_text((20, 40), "hi", fontname="helv")
        assert page.get_contents() == before
        assert doc.xref_get_key(page_xref, f"Resources/Font/{name}") == font_entry
        assert _render(doc) == want_render
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_stripping_a_baked_watermark_on_open_keeps_a_backslash_u_name_of_the_page(name) -> None:
    """Opening a file this app watermarked takes the baked copy out of the
    page (a stream that held only the mark leaves ``/Contents``); the page's
    font keeps its name."""
    from model.text_commit.pdf_lexer import encode_hex_string
    from model.tools.watermark_rendering import strip_marked_watermarks
    from utils.pdf_object_source import xref_object_exact

    doc, _form, _page_text = _page_doc(name, page_font_name=name)
    try:
        page = doc[0]
        page_xref = page.xref
        (content,) = page.get_contents()
        mark = b"q\n/Artifact <</Type /Pagination /Subtype /Watermark /PdfEditorWatermark "
        baked = _new_stream(
            doc,
            "<<>>",
            mark + encode_hex_string(b"wm1") + f">> BDC\nBT /{name} 30 Tf 20 20 Td (WM) Tj ET\nEMC\nQ\n".encode(),
            compress=False,
        )
        source = xref_object_exact(doc, page_xref, compressed=True)
        doc.update_object(page_xref, source.replace(f"/Contents {content} 0 R", f"/Contents[{content} 0 R {baked} 0 R]"))
        want_font = doc.xref_get_key(page_xref, "Resources/Font")
        assert name in want_font[1]

        assert strip_marked_watermarks(doc, [{"id": "wm1", "pages": [1]}]) == 1
        assert page.get_contents() == [content]
        assert doc.xref_get_key(page_xref, "Resources/Font") == want_font
        assert _span_fonts(page) == {"Helvetica"}
    finally:
        doc.close()


# ------------------------------------- keys set on the catalog and on bookmarks


@pytest.mark.parametrize("name", NAMES)
def test_dropping_the_open_action_of_a_deleted_page_keeps_a_backslash_u_name_of_the_catalog(name) -> None:
    """Deleting the page ``/OpenAction`` shows clears that key of the catalog;
    the form's default font, named in the same dictionary, keeps its name."""
    from model import page_refs
    from utils.pdf_object_source import xref_object_exact

    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=200, height=200)
    pages = [doc.page_xref(i) for i in range(2)]
    font = doc.get_new_xref()
    doc.update_object(font, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    catalog = doc.pdf_catalog()
    source = xref_object_exact(doc, catalog, compressed=True)
    doc.update_object(
        catalog,
        f"{source[:-2]}/OpenAction[{pages[1]} 0 R/Fit]"
        f"/AcroForm<</Fields[]/DR<</Font<</{name} {font} 0 R>>>>/DA(/{name} 0 Tf 0 g)>>>>",
    )
    doc = _reopened(doc)
    try:
        want_font = doc.xref_get_key(catalog, "AcroForm/DR/Font")
        assert name in want_font[1]
        doc.delete_page(1)

        page_refs.repoint_page_references(doc, {pages[1]: None})
        assert doc.xref_get_key(catalog, "OpenAction") == ("null", "null")
        assert doc.xref_get_key(catalog, "AcroForm/DR/Font") == want_font
    finally:
        doc.close()


@pytest.mark.parametrize("name", NAMES)
def test_retitling_a_bookmark_keeps_the_backslash_u_name_its_action_jumps_to(name) -> None:
    """A title edit sets ``/Title`` on the bookmark; its GoTo action keeps the
    named destination it selects, so the bookmark still jumps to page 2."""
    from model.outline_ops import OutlineRow, apply_outline_rows, outline_items

    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=200, height=200)
    second = doc.page_xref(1)
    dests = doc.get_new_xref()
    doc.update_object(dests, f"<</{name}[{second} 0 R/Fit]>>")
    root = doc.get_new_xref()
    item = doc.get_new_xref()
    doc.update_object(root, f"<</Type/Outlines/First {item} 0 R/Last {item} 0 R/Count 1>>")
    doc.update_object(item, f"<</Title(Old)/Parent {root} 0 R/A<</S/GoTo/D/{name}>>>>")
    catalog = doc.pdf_catalog()
    doc.xref_set_key(catalog, "Dests", f"{dests} 0 R")
    doc.xref_set_key(catalog, "Outlines", f"{root} 0 R")
    doc = _reopened(doc)
    try:
        items = outline_items(doc)
        assert items is not None and [(i.xref, i.title, i.page) for i in items] == [(item, "Old", 2)]

        assert apply_outline_rows(doc, [OutlineRow(1, "New", 2, item)], items) is True
        assert doc.xref_get_key(item, "A/D") == ("name", f"/{name}")
        assert doc.get_toc(simple=True) == [[1, "New", 2]]
    finally:
        doc.close()


# ---------------------------------------------------------------------- guard

# The only ``.xref_object(`` reads left in model/ and utils/: whole-document
# walks that use a slot's references, size or null-ness, where the decoded text
# is harmless and the exact reader would cost about three times as much per
# object, and the signed append save's comparison (rename-only differences come
# only from this bug; its replay reads ``xref_object_exact``).
_XREF_OBJECT_READS = {
    "model/xref_compaction.py:read_every_object": "loads every object once at open; the text is unused",
    "model/xref_compaction.py:open_compaction_verdict": "counts null slots",
    "model/save_compaction.py:_object_text": "reachability: the references only",
    "model/pdf_optimizer.py:xref_size_bytes": "size estimate for the audit report",
    "model/pdf_validator.py:check_pdf_conformance": "every slot must resolve; the text is unused",
    "model/signed_append_save.py:_source": "comparison only; the replay reads xref_object_exact",
    "utils/pdf_object_source.py:xref_object_exact": "the fallback without the private printer",
}


def _model_and_utils() -> list[Path]:
    return [path for folder in ("model", "utils") for path in (ROOT / folder).rglob("*.py")]


def _callers(path: Path, method: str) -> set[str]:
    """``path:function`` of every use of ``method`` in ``path``: any
    ``.<method>`` attribute (a call, an alias, ``map``, ``partial``) and a
    ``"<method>"`` string (``getattr``).  Per function, not per call."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found: set[str] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if (isinstance(child, ast.Attribute) and child.attr == method) or (
                isinstance(child, ast.Constant) and child.value == method
            ):
                found.add(f"{path.relative_to(ROOT).as_posix()}:{function}")
            visit(child, function)

    visit(tree, "<module>")
    return found


def test_xref_object_is_read_only_where_it_is_still_called() -> None:
    """Text from ``xref_object`` is not the object (W1B-DICT-RT): model/ and
    utils/ read objects with ``utils.pdf_object_source.xref_object_exact``,
    except the reviewed whole-document walks above.  A new ``.xref_object(``
    call fails here until it is switched or reviewed into the list."""
    callers = set().union(*(_callers(path, "xref_object") for path in _model_and_utils()))
    assert sorted(callers - _XREF_OBJECT_READS.keys()) == []
    assert sorted(_XREF_OBJECT_READS.keys() - callers) == []  # a stale entry


def test_xref_set_key_is_called_only_by_the_exact_helper() -> None:
    """``xref_set_key`` prints the whole object through the same decode:
    model/ and utils/ set keys with ``xref_set_key_exact``."""
    callers = set().union(*(_callers(path, "xref_set_key") for path in _model_and_utils()))
    assert sorted(callers) == [
        "utils/pdf_object_source.py:exact_set_key",  # shadows doc.xref_set_key for the block
        "utils/pdf_object_source.py:xref_set_key_exact",  # its fallback, PyMuPDF's method
    ]


# Every PyMuPDF method that calls ``xref_set_key`` on its document, directly
# or through another of its methods (1.27.1), and the name the guard below
# looks for (``None``: not looked for, and why).
_PYMUPDF_SET_KEY_CALLERS = {
    "Annot.set_colors": "set_colors",
    "Link.set_colors": "set_colors",
    "Link.set_flags": None,  # Annot.set_flags sets the flags directly; the model sets flags on annotations only
    "Document.embfile_add": "embfile_add",
    "Document.embfile_upd": "embfile_upd",
    "Document.scrub": "scrub",
    "Document.set_markinfo": "set_markinfo",
    "Document.set_metadata": "set_metadata",
    "Document.set_oc": "set_oc",
    "Document.set_pagelayout": "set_pagelayout",
    "Document.set_pagemode": "set_pagemode",
    "Document.subset_fonts": "subset_fonts",
    "Document.subset_fonts.set_old_widths": "subset_fonts",
    "Document.xref_copy": "xref_copy",
    "Page.replace_image": "replace_image",
    "Page.delete_image": "delete_image",
    "Page._set_pagebox": None,  # private: through the four box setters
    "Page.set_artbox": "set_artbox",
    "Page.set_bleedbox": "set_bleedbox",
    "Page.set_cropbox": "set_cropbox",
    "Page.set_trimbox": "set_trimbox",
    "Page.set_contents": "set_contents",
    "Page.add_widget": "add_widget",
    "Page.remove_rotation": "remove_rotation",  # updates the page's widgets
    "Widget._checker": None,  # private: through Widget.update
    "Widget._validate": None,  # private: through Widget.update
    "Widget.update": None,  # dict.update shares the name; the model never updates a widget
}
_SET_KEY_METHODS = {name for name in _PYMUPDF_SET_KEY_CALLERS.values() if name}


def test_the_guarded_methods_are_every_pymupdf_caller_of_xref_set_key() -> None:
    """Pins the list above to the installed PyMuPDF: a version that adds or
    moves a caller fails here until the list (and the model) is reviewed."""
    tree = ast.parse(Path(fitz.Document.xref_set_key.__code__.co_filename).read_text(encoding="utf-8"))

    def callers_of(names: set[str]) -> set[str]:
        found: set[str] = set()

        def visit(node: ast.AST, qualified: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(child, f"{qualified}.{child.name}" if qualified else child.name)
                    continue
                if isinstance(child, ast.Call):
                    func = child.func
                    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    # Widget.update() takes no argument; dict.update always takes one.
                    if called in names and (called != "update" or not (child.args or child.keywords)):
                        found.add(qualified)
                visit(child, qualified)

        visit(tree, "")
        return found

    reached = callers_of({"xref_set_key"})
    while True:
        more = callers_of({name.rsplit(".", 1)[1] for name in reached}) - reached
        if not more:
            break
        reached |= more
    assert sorted(reached) == sorted(_PYMUPDF_SET_KEY_CALLERS)


def _set_key_methods_outside_exact_set_key(path: Path) -> list[str]:
    """``path:function:line .method`` of every call of a guarded PyMuPDF
    method that is not inside a ``with exact_set_key(...)`` block of its
    function.  Calls only: ``options.subset_fonts`` is a setting."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found: list[str] = []

    def routes(item: ast.withitem) -> bool:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            return False
        return getattr(call.func, "id", None) == "exact_set_key" or getattr(call.func, "attr", None) == "exact_set_key"

    def visit(node: ast.AST, function: str, routed: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                # Its body runs when it is called, maybe after the block.
                visit(child, getattr(child, "name", function), False)
                continue
            if isinstance(child, (ast.With, ast.AsyncWith)) and any(routes(item) for item in child.items):
                visit(child, function, True)
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _SET_KEY_METHODS
                and not routed
            ):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{function}:{child.lineno} .{child.func.attr}")
            visit(child, function, routed)

    visit(tree, "<module>", False)
    return found


def test_pymupdf_methods_that_set_keys_run_inside_exact_set_key() -> None:
    """PyMuPDF's own methods that call ``xref_set_key`` (the list above) run
    in model/ and utils/ only inside ``exact_set_key(doc)``."""
    assert [use for path in _model_and_utils() for use in _set_key_methods_outside_exact_set_key(path)] == []
