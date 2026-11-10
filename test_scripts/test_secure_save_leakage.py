from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest

from model.object_requests import DeleteObjectRequest
from model.pdf_model import SECURE_SAVE_GARBAGE_LEVEL, PDFModel

# One marker per latch trigger; each lives in the thing the edit removes.
MARK_DELETE = b"LEAK-DELETE-PAGE-MARK-51873"
MARK_MOVE = b"LEAK-MOVE-PAGE-MARK-62984"
MARK_TOC = b"LEAK-TOC-EDIT-MARK-73095"
MARK_META = b"LEAK-META-EDIT-MARK-84106"
MARK_OBJECT = b"LEAK-OBJECT-DELETE-MARK-95217"
MARK_TEXTBOX = b"LEAK-TEXTBOX-DELETE-MARK-16328"

# The five latch triggers: delete page, move page, TOC edit, metadata edit and
# ``delete_objects_atomic``.  Only delete page, TOC edit and object delete can
# DISCRIMINATE the level (their removed content is an orphan in the live doc and
# leaks at 0, see ``test_unsanitised_level_zero_leaks``).  Move page removes
# nothing and ``set_metadata`` overwrites /Info in place, so those two are
# structural checks that hold at every level.
# Garbage levels the model's save call is forced to (test seam, no product
# edit).  Level 0 is the unsanitised serialization the latch exists to
# prevent; run it with ``LEAK_TEST_LEVELS=0`` to see the red light.
LEVELS = [int(v) for v in os.environ.get("LEAK_TEST_LEVELS", "1,2,3,4").split(",")]


def _base_doc(pages: int = 3) -> fitz.Document:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page(width=300, height=200).insert_text((30, 60), f"page {i + 1} body", fontsize=12)
    return doc


def _build_delete(path: Path) -> None:
    doc = _base_doc()
    # insert_text hex-encodes its string, so append a raw comment stream
    # to the page's /Contents: the marker is then a plain byte run.
    page = doc[1]
    old = page.get_contents()[0]
    extra = doc.get_new_xref()
    doc.update_object(extra, "<<>>")
    doc.update_stream(extra, b"% " + MARK_DELETE + b"\n")
    doc.xref_set_key(page.xref, "Contents", f"[{old} 0 R {extra} 0 R]")
    doc.save(path)
    doc.close()


def _build_move(path: Path) -> None:
    doc = _base_doc()
    doc.set_toc([[1, MARK_MOVE.decode(), 1], [1, "second", 2], [1, "third", 3]])
    doc.save(path)
    doc.close()


def _build_toc(path: Path) -> None:
    doc = _base_doc()
    doc.set_toc([[1, MARK_TOC.decode(), 1], [1, "kept", 2]])
    doc.save(path)
    doc.close()


def _build_meta(path: Path) -> None:
    doc = _base_doc()
    doc.set_metadata({"title": MARK_META.decode(), "author": "a", "subject": "", "keywords": ""})
    doc.save(path)
    doc.close()


def _build_object(path: Path) -> None:
    doc = _base_doc(pages=1)
    page = doc[0]
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    pix.clear_with(200)
    xref = page.insert_image(fitz.Rect(100, 100, 160, 160), pixmap=pix)
    doc.xref_set_key(xref, "MarkKey", f"({MARK_OBJECT.decode()})")
    doc.save(path)
    doc.close()


def _op_object(model: PDFModel) -> None:
    hit = model.get_object_info_at_point(1, fitz.Point(130, 130))
    assert hit is not None and hit.object_kind == "native_image"
    assert model.delete_objects_atomic([DeleteObjectRequest(hit.object_id, hit.object_kind, 1)])


def _op_delete(model: PDFModel) -> None:
    assert model.delete_pages([2]) == [2]


def _op_move(model: PDFModel) -> None:
    assert model.move_page(0, 2)


def _op_toc(model: PDFModel) -> None:
    assert model.set_toc([[1, "kept", 2]])  # the marker bookmark is removed


def _op_meta(model: PDFModel) -> None:
    assert model.set_editable_metadata({"title": ""})


TRIGGERS = {
    "delete_page": (_build_delete, _op_delete, MARK_DELETE),
    "move_page": (_build_move, _op_move, MARK_MOVE),
    "toc_edit": (_build_toc, _op_toc, MARK_TOC),
    "metadata_edit": (_build_meta, _op_meta, MARK_META),
    "object_delete": (_build_object, _op_object, MARK_OBJECT),
}

# Triggers whose removed content leaks at level 0 (the negative control).
LEAKING_AT_ZERO = ["delete_page", "toc_edit", "object_delete"]


def _marker_hits(path: Path, marker: bytes) -> list[str]:
    """Where the marker occurs: raw bytes, every decoded stream, every object."""
    hits: list[str] = []
    text = marker.decode("ascii")
    wide = text.encode("utf-16-be")  # PDF text strings may be UTF-16BE
    raw = path.read_bytes()
    if marker in raw or wide in raw:
        hits.append("raw")
    doc = fitz.open(path)
    try:
        for xref in range(1, doc.xref_length()):
            for name, reader in (("stream", doc.xref_stream), ("stream_raw", doc.xref_stream_raw)):
                try:
                    data = reader(xref)
                except Exception:
                    data = None
                if data and (marker in data or wide in data):
                    hits.append(f"xref {xref} {name}")
            try:
                obj = doc.xref_object(xref)
            except Exception:
                obj = ""
            if text in obj:
                hits.append(f"xref {xref} object")
    finally:
        doc.close()
    return hits


def _force_level(monkeypatch: pytest.MonkeyPatch, level: int) -> list[int]:
    """Test seam: force the garbage kwarg of every ``_save_doc`` call."""
    seen: list[int] = []
    original = PDFModel._save_doc

    def _forcing(doc, target, *, garbage=0, incremental=False):
        seen.append(garbage)
        return original(doc, target, garbage=level, incremental=incremental)

    monkeypatch.setattr(PDFModel, "_save_doc", staticmethod(_forcing))
    return seen


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str, level: int) -> list[str]:
    build, op, marker = TRIGGERS[trigger]
    source = tmp_path / f"{trigger}.pdf"
    out = tmp_path / f"{trigger}_out.pdf"
    build(source)
    assert _marker_hits(source, marker), "fixture must contain the marker before the edit"
    model = PDFModel()
    try:
        model.open_pdf(str(source))
        op(model)
        assert model.secure_save_required is True
        seen = _force_level(monkeypatch, level)
        model.save_as(str(out))
        assert seen, "the save went through _save_doc"
    finally:
        model.close_all_sessions()
    check = fitz.open(out)
    try:
        assert check.page_count >= 1
    finally:
        check.close()
    return _marker_hits(out, marker)


@pytest.mark.parametrize("trigger", LEAKING_AT_ZERO)
def test_unsanitised_level_zero_leaks(tmp_path, monkeypatch, trigger) -> None:
    """Always-on negative control: the leakage tests below are only meaningful if
    the marker really survives an unsanitised (level 0) serialization."""
    assert _run(tmp_path, monkeypatch, trigger, 0) != []


def test_unsanitised_level_zero_leaks_after_textbox_delete(tmp_path, monkeypatch) -> None:
    """Textbox delete (a redaction rewrite) also latches; probed with a comment
    stream stamped into the live page contents after the textbox is added."""
    source = tmp_path / "tb.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(source)
    doc.close()
    outs = {}
    for level in (0, SECURE_SAVE_GARBAGE_LEVEL):
        model = PDFModel()
        try:
            model.open_pdf(str(source))
            model.add_textbox(1, fitz.Rect(200, 150, 360, 200), "MMMM", font="helv", size=20, color=(0, 0, 0))
            live = model.doc
            page = live[0]
            old = page.get_contents()[0]
            extra = live.get_new_xref()
            live.update_object(extra, "<<>>")
            live.update_stream(extra, b"% " + MARK_TEXTBOX + b"\n")
            live.xref_set_key(page.xref, "Contents", f"[{old} 0 R {extra} 0 R]")
            hit = model.get_object_info_at_point(1, fitz.Point(210, 160))
            assert hit is not None and hit.object_kind == "textbox"
            assert model.delete_objects_atomic([DeleteObjectRequest(hit.object_id, hit.object_kind, 1)])
            assert model.secure_save_required is True
            _force_level(monkeypatch, level)
            out = tmp_path / f"tb_out_{level}.pdf"
            model.save_as(str(out))
            outs[level] = _marker_hits(out, MARK_TEXTBOX)
        finally:
            model.close_all_sessions()
            monkeypatch.undo()
    assert outs[0] != []
    assert outs[SECURE_SAVE_GARBAGE_LEVEL] == []


@pytest.mark.parametrize("trigger", ["delete_page", "toc_edit", "object_delete"])
@pytest.mark.parametrize("level", LEVELS)
def test_latched_save_removes_the_edited_out_marker(tmp_path, monkeypatch, trigger, level) -> None:
    assert _run(tmp_path, monkeypatch, trigger, level) == []


@pytest.mark.parametrize("level", LEVELS)
def test_latched_metadata_edit_save_is_structurally_sound(tmp_path, monkeypatch, level) -> None:
    # Structural check, not a level discriminator: ``set_metadata`` overwrites
    # /Info in place, so the old title is not an orphan and never leaks, even at 0.
    assert _run(tmp_path, monkeypatch, "metadata_edit", level) == []


@pytest.mark.parametrize("level", LEVELS)
def test_latched_move_page_save_keeps_the_outline_title_exactly_once(
    tmp_path, monkeypatch, level
) -> None:
    # Structural check, not a level discriminator: a move removes nothing, the
    # outline title is live, so its marker must appear as one outline object,
    # never as an extra orphaned copy.
    hits = _run(tmp_path, monkeypatch, "move_page", level)
    assert [h for h in hits if h.endswith("object")] and len(hits) == len(
        [h for h in hits if h.endswith("object")] + [h for h in hits if h == "raw"]
    ), hits
    assert len([h for h in hits if h.endswith("object")]) == 1, hits


@pytest.mark.parametrize("trigger", ["delete_page", "toc_edit", "metadata_edit", "object_delete"])
def test_production_latched_save_leaks_nothing_at_the_production_level(
    tmp_path, monkeypatch, trigger
) -> None:
    """No level forcing: the real latched save path at the level it really uses.

    Ties the leakage evidence above to production: the save must call
    ``_save_doc`` with ``SECURE_SAVE_GARBAGE_LEVEL`` and the edited-out marker
    must be gone from that very output.
    """
    build, op, marker = TRIGGERS[trigger]
    source = tmp_path / f"{trigger}_prod.pdf"
    out = tmp_path / f"{trigger}_prod_out.pdf"
    build(source)
    seen: list[int] = []
    original = PDFModel._save_doc

    def _spy(doc, target, *, garbage=0, incremental=False):
        seen.append(garbage)
        return original(doc, target, garbage=garbage, incremental=incremental)

    model = PDFModel()
    try:
        model.open_pdf(str(source))
        op(model)
        monkeypatch.setattr(PDFModel, "_save_doc", staticmethod(_spy))
        model.save_as(str(out))
    finally:
        model.close_all_sessions()
    assert seen and set(seen) == {SECURE_SAVE_GARBAGE_LEVEL}
    assert _marker_hits(out, marker) == []
