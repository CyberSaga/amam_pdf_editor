from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz
import pytest

from model.object_op_refusal import ObjectOpRefusal
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, RotateObjectRequest
from model.page_content_text import content_text
from model.pdf_model import PDFModel


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text(fitz.Point(40, 40), "LEGACY_TEXT", fontsize=12, fontname="helv", color=(0, 0, 0))
    doc.save(path)
    doc.close()


def _object_hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def test_add_textbox_creates_hidden_object_marker_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "textbox.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            visual_rect = fitz.Rect(50, 70, 180, 110)
            model.add_textbox(1, visual_rect, "OBJECT_BOX", font="cjk", size=14, color=(0, 0, 0))

            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None
            assert hit.object_kind == "textbox"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_textbox_object"
            ]
            assert len(marker_annots) == 1
            payload = json.loads(marker_annots[0].info.get("content") or "{}")
            assert payload["kind"] == "textbox"
            assert payload["text"] == "OBJECT_BOX"
        finally:
            model.close()


def test_get_object_info_ignores_legacy_text_without_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _object_hit(model, fitz.Point(42, 38))
            assert hit is None
        finally:
            model.close()


def test_add_rect_creates_object_metadata_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)

            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None
            assert hit.object_kind == "rect"
            assert hit.supports_rotate is False
        finally:
            model.close()


def test_rect_appearance_persists_independent_stroke_fill_and_border_width() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rect_appearance.pdf"
        output = Path(tmp) / "rect_appearance_saved.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(
                1,
                fitz.Rect(20, 90, 120, 150),
                stroke_color=(1.0, 0.0, 0.0, 0.75),
                fill_color=(0.0, 1.0, 0.0, 0.75),
                border_width=2.5,
            )
            model.save_as(str(output))
        finally:
            model.close()

        reopened = fitz.open(output)
        try:
            page = reopened[0]
            annot = next(page.annots())
            assert annot.type[1] == "Square"
            assert annot.colors["stroke"] == pytest.approx([1.0, 0.0, 0.0])
            assert annot.colors["fill"] == pytest.approx([0.0, 1.0, 0.0])
            assert annot.border["width"] == pytest.approx(2.5)
            assert annot.opacity == pytest.approx(0.75, abs=0.01)
            payload = json.loads(annot.info["content"])
            assert payload["stroke_color"] == pytest.approx([1.0, 0.0, 0.0, 0.75])
            assert payload["fill_color"] == pytest.approx([0.0, 1.0, 0.0, 0.75])
            assert payload["border_width"] == pytest.approx(2.5)
        finally:
            reopened.close()


def test_rect_no_fill_is_transparent_and_keeps_validated_border() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rect_no_fill.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(
                1,
                fitz.Rect(20, 90, 120, 150),
                stroke_color=(0.0, 0.0, 1.0, 1.0),
                fill_color=None,
                border_width=3.0,
            )
            page = model.doc[0]
            annot = next(page.annots())
            assert not annot.colors.get("fill")
            assert annot.border["width"] == pytest.approx(3.0)
            payload = json.loads(annot.info["content"])
            assert payload["fill_color"] is None
        finally:
            model.close()


@pytest.mark.parametrize("border_width", [-1, 0, 21, float("nan"), "wide"])
def test_rect_rejects_invalid_border_width_without_mutation(border_width: object) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rect_bad_border.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            with pytest.raises((TypeError, ValueError)):
                model.tools.annotation.add_rect(
                    1,
                    fitz.Rect(20, 90, 120, 150),
                    stroke_color=(1.0, 0.0, 0.0, 1.0),
                    fill_color=None,
                    border_width=border_width,
                )
            assert list(model.doc[0].annots() or []) == []
        finally:
            model.close()


def test_move_rect_object_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)
            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(160, 95, 260, 155),
                )
            )
            assert ok is True
            assert _object_hit(model, fitz.Point(30, 100)) is None
            moved = _object_hit(model, fitz.Point(180, 110))
            assert moved is not None
            assert moved.object_id == hit.object_id
        finally:
            model.close()


def test_delete_rect_object_removes_annotation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delete_rect.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.tools.annotation.add_rect(1, fitz.Rect(20, 90, 120, 150), (1.0, 0.0, 0.0, 1.0), False)
            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None

            ok = model.delete_object(
                DeleteObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                )
            )
            assert ok is True
            assert _object_hit(model, fitz.Point(30, 100)) is None
        finally:
            model.close()


def test_rotate_textbox_object_updates_rotation_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotate_box.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_ME", font="cjk", size=14, color=(0, 0, 0))
            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None
            assert hit.rotation == 0

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert ok is True

            # F15-6: the quarter-turned box is 40x130 about the old centre (115, 90).
            rotated = _object_hit(model, fitz.Point(115, 90))
            assert rotated is not None
            assert rotated.rotation == 90
        finally:
            model.close()


def test_textbox_absolute_rotation_sets_exact_angle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotate_box_absolute.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_ME", font="cjk", size=14, color=(0, 0, 0))
            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=180,
                )
            )
            rotated = _object_hit(model, fitz.Point(80, 90))
            assert rotated is not None
            assert rotated.rotation == 180

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=360,
                )
            )
            reset = _object_hit(model, fitz.Point(80, 90))
            assert reset is not None
            assert reset.rotation == 0
        finally:
            model.close()


def test_delete_textbox_after_move_and_rotate_removes_all_markers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delete_rotated_box.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "ROT_DEL", font="cjk", size=14, color=(0, 0, 0))
            hit = _object_hit(model, fitz.Point(80, 90))
            assert hit is not None

            moved_ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(120, 100, 250, 140),
                )
            )
            assert moved_ok is True

            rotated_ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert rotated_ok is True

            delete_ok = model.delete_object(
                DeleteObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                )
            )
            assert delete_ok is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_textbox_object"
            ]
            assert marker_annots == []
            assert _object_hit(model, fitz.Point(180, 120)) is None
        finally:
            model.close()


def test_move_textbox_keeps_overlapping_annotations_once() -> None:
    """F11-ANN-1: moving a textbox redacts its old rect; annotations that
    survive the redaction (everything but FreeText) must not be re-added on
    top of themselves, and a neighbouring textbox marker must not gain a
    subject-less (visible) copy."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_box_annots.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "MOVE_ME", font="cjk", size=14, color=(0, 0, 0))
            model.add_textbox(1, fitz.Rect(150, 80, 260, 120), "NEIGHBOUR", font="cjk", size=14, color=(0, 0, 0))
            page = model.doc[0]
            page.add_highlight_annot(fitz.Rect(60, 75, 120, 95)).update()
            page.add_rect_annot(fitz.Rect(90, 80, 140, 105)).update()

            def census() -> dict[tuple[str, str], int]:
                counts: dict[tuple[str, str], int] = {}
                for annot in model.doc[0].annots():
                    key = (annot.type[1], annot.info.get("subject") or "")
                    counts[key] = counts.get(key, 0) + 1
                return counts

            before = census()
            hit = _object_hit(model, fitz.Point(70, 100))
            assert hit is not None and hit.object_kind == "textbox"
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(40, 160, 170, 200),
                )
            )
            assert ok is True
            assert census() == before
            for annot in model.doc[0].annots():
                assert fitz.Rect(model.doc[0].rect).contains(annot.rect), (annot.type[1], annot.rect)
        finally:
            model.close()



def test_move_textbox_keeps_links_over_its_old_rect() -> None:
    """F11-ANN-3: the textbox move redacts the old rect; a link over it
    (``page.annots()`` never lists links) must not be deleted by the redaction."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_box_links.pdf"
        _make_pdf(path)

        model = PDFModel()
        held = None
        try:
            model.open_pdf(str(path))
            model.add_textbox(1, fitz.Rect(50, 70, 180, 110), "MOVE_ME", font="cjk", size=14, color=(0, 0, 0))
            model.doc[0].insert_link(
                {"kind": fitz.LINK_URI, "from": fitz.Rect(60, 75, 120, 95), "uri": "https://example.com/box"}
            )
            # ``insert_link`` does not refresh the loaded page's link list; load it anew.
            held = model.doc[0]

            def links(page: fitz.Page) -> list[tuple]:
                return sorted(
                    (link.get("xref"), link.get("uri"), tuple(round(v, 1) for v in fitz.Rect(link["from"])))
                    for link in page.get_links()
                )

            before = links(held)
            assert len(before) == 1
            hit = _object_hit(model, fitz.Point(70, 100))
            assert hit is not None and hit.object_kind == "textbox"
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(40, 160, 170, 200),
                )
            )
            assert ok is True
            assert links(model.doc[0]) == before
            assert links(held) == before
        finally:
            held = None
            model.close()


# F14-MM-1: on a /Rotate 90/180/270 page the textbox move/rotate/delete redaction
# was applied with the VISUAL rect, which MuPDF reads in unrotated space. It missed
# the textbox's own glyphs (a second copy stayed drawn) and erased page text that
# sits at the unrotated coordinates equal to the visual rect. VICTIM is placed
# there on purpose and is never visually under the textbox (that is F13-VF-2b).
_F14_VICTIM_ORIGIN = fitz.Point(310, 320)


def _make_rotated_victim_pdf(path: Path, rotation: int) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(_F14_VICTIM_ORIGIN, "VICTIM", fontsize=12, fontname="helv")
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()


def _f14_visual_rect(rotation: int) -> fitz.Rect:
    # At /Rotate 0 the visual rect equals unrotated space, so keep it off VICTIM.
    return fitz.Rect(300, 300, 460, 330) if rotation else fitz.Rect(300, 400, 460, 430)


def _visual_words(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    return [(w[4], fitz.Rect(w[:4]) * page.rotation_matrix) for w in page.get_text("words")]


def _assert_one_textbox_copy_inside(page: fitz.Page, visual_rect: fitz.Rect) -> None:
    words = _visual_words(page)
    names = [name for name, _ in words]
    assert names.count("Moving") == 1, (page.rotation, names)
    assert names.count("box") == 1, (page.rotation, names)
    assert "VICTIM" in names, (page.rotation, names)
    zone = fitz.Rect(visual_rect) + (-2, -2, 2, 2)
    for name, rect in words:
        if name in ("Moving", "box"):
            assert zone.contains(rect), (page.rotation, name, rect, visual_rect)


def _open_with_textbox(path: Path, rotation: int) -> tuple[PDFModel, object, fitz.Rect]:
    _make_rotated_victim_pdf(path, rotation)
    model = PDFModel()
    model.open_pdf(str(path))
    visual_rect = _f14_visual_rect(rotation)
    model.add_textbox(1, visual_rect, "Moving box", font="helv", size=12)
    _assert_one_textbox_copy_inside(model.doc[0], visual_rect)
    hit = _object_hit(model, visual_rect.tl + (20, 15))
    assert hit is not None and hit.object_kind == "textbox"
    return model, hit, visual_rect


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_move_textbox_on_rotated_page_leaves_one_copy_and_keeps_unrelated_text(rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, _visual_rect = _open_with_textbox(Path(tmp) / f"move_r{rotation}.pdf", rotation)
        try:
            dest = fitz.Rect(hit.bbox) + (40, 60, 40, 60)
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=dest,
                )
            )
            assert ok is True
            _assert_one_textbox_copy_inside(model.doc[0], dest)
            moved = _object_hit(model, dest.tl + (20, 15))
            assert moved is not None and moved.object_id == hit.object_id

            out = Path(tmp) / f"move_r{rotation}_saved.pdf"
            model.save_as(str(out))
        finally:
            model.close()
        with fitz.open(str(out)) as reopened:
            _assert_one_textbox_copy_inside(reopened[0], dest)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotate_textbox_on_rotated_page_leaves_one_copy_and_keeps_unrelated_text(rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, visual_rect = _open_with_textbox(Path(tmp) / f"rot_r{rotation}.pdf", rotation)
        try:
            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=180,
                )
            )
            assert ok is True
            _assert_one_textbox_copy_inside(model.doc[0], visual_rect)
        finally:
            model.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_delete_textbox_on_rotated_page_leaves_no_orphan_and_keeps_unrelated_text(rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, visual_rect = _open_with_textbox(Path(tmp) / f"del_r{rotation}.pdf", rotation)
        try:
            ok = model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            )
            assert ok is True
            names = [name for name, _ in _visual_words(model.doc[0])]
            assert "Moving" not in names and "box" not in names, (rotation, names)
            assert "VICTIM" in names, (rotation, names)
            assert _object_hit(model, visual_rect.tl + (20, 15)) is None
        finally:
            model.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_move_textbox_on_rotated_page_keeps_a_link_visually_under_it(rotation: int) -> None:
    # Guard for the annotation snapshot: once the redaction hits the textbox's real
    # (unrotated) area it also hits a link drawn under the box; the snapshot must be
    # taken in that same space or the link is lost.
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, visual_rect = _open_with_textbox(Path(tmp) / f"link_r{rotation}.pdf", rotation)
        held = None
        try:
            link_visual = fitz.Rect(visual_rect.x0 + 5, visual_rect.y0 + 5, visual_rect.x0 + 60, visual_rect.y0 + 20)
            # PyMuPDF 1.27 ``insert_link`` stores "from" as given in unrotated space.
            model.doc[0].insert_link(
                {"kind": fitz.LINK_URI, "from": (link_visual * model.doc[0].derotation_matrix).normalize(),
                 "uri": "https://example.com/rotated"}
            )
            # ``insert_link`` does not refresh the loaded page's link list; load it anew.
            held = model.doc[0]
            before = sorted((link.get("uri"), tuple(round(v, 1) for v in fitz.Rect(link["from"])))
                            for link in held.get_links())
            assert len(before) == 1
            # get_links() "from" is visual space: the link really is under the textbox.
            assert (fitz.Rect(visual_rect) + (-1, -1, 1, 1)).contains(fitz.Rect(held.get_links()[0]["from"]))
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(hit.bbox) + (40, 60, 40, 60),
                )
            )
            assert ok is True
            after = sorted((link.get("uri"), tuple(round(v, 1) for v in fitz.Rect(link["from"])))
                           for link in model.doc[0].get_links())
            assert after == before
        finally:
            held = None
            model.close()


# F13-VF-2b: moving, rotating or deleting an app textbox redacted the textbox's whole
# rect, a geometric erase, so page text visually under the box was lost with it
# (UNDERLYING PAGE TEXT kept only fragments, or nothing). The textbox draws its glyphs
# as its own htmlbox Form XObject, so only that drawing may be removed.
_VF2B_TEXT = "UNDERLYING PAGE TEXT"
_VF2B_WORDS = ("UNDERLYING", "PAGE", "TEXT")


def _vf2b_open(path: Path, rotation: int) -> tuple[PDFModel, object, fitz.Rect]:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text(fitz.Point(40, 100), _VF2B_TEXT, fontsize=12, fontname="helv")
    if rotation:
        page.set_rotation(rotation)
    text_visual = fitz.Rect()
    for word in page.get_text("words"):
        text_visual |= fitz.Rect(word[:4]) * page.rotation_matrix
    visual_page = fitz.Rect(page.rect) + (6, 6, -6, -6)
    doc.save(path)
    doc.close()
    centre = fitz.Point((text_visual.x0 + text_visual.x1) / 2, (text_visual.y0 + text_visual.y1) / 2)
    box = (text_visual + (-10, -10, 10, 10)) | fitz.Rect(centre.x - 110, centre.y - 16, centre.x + 110, centre.y + 16)
    box &= visual_page
    model = PDFModel()
    model.open_pdf(str(path))
    model.add_textbox(1, box, "Moving box", font="helv", size=12)
    names = [w[4] for w in model.doc[0].get_text("words")]
    for word in (*_VF2B_WORDS, "Moving", "box"):
        assert names.count(word) == 1, (rotation, word, names)
    hit = _object_hit(model, box.tl + (4, 4))
    assert hit is not None and hit.object_kind == "textbox"
    return model, hit, box


def _vf2b_assert_page_text_kept(page: fitz.Page, textbox_copies: int, label: str) -> None:
    names = [w[4] for w in page.get_text("words")]
    for word in _VF2B_WORDS:
        assert names.count(word) == 1, (label, word, names)
    assert names.count("Moving") == textbox_copies, (label, names)
    assert names.count("box") == textbox_copies, (label, names)


def _vf2b_dest(page: fitz.Page, box: fitz.Rect) -> fitz.Rect:
    bottom = float(page.rect.y1) - 8
    return fitz.Rect(box.x0, bottom - box.height, box.x1, bottom)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("op", ["move", "rotate", "delete"])
def test_textbox_object_op_keeps_the_page_text_under_the_box(op: str, rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, box = _vf2b_open(Path(tmp) / f"vf2b_{op}_r{rotation}.pdf", rotation)
        out = Path(tmp) / f"vf2b_{op}_r{rotation}_saved.pdf"
        try:
            if op == "move":
                dest = _vf2b_dest(model.doc[0], box)
                ok = model.move_object(MoveObjectRequest(hit.object_id, "textbox", 1, 1, dest))
            elif op == "rotate":
                ok = model.rotate_object(
                    RotateObjectRequest(object_id=hit.object_id, object_kind="textbox", page_num=1, rotation_delta=180)
                )
            else:
                ok = model.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1))
            assert ok is True
            copies = 0 if op == "delete" else 1
            _vf2b_assert_page_text_kept(model.doc[0], copies, f"{op} r{rotation}")
            model.save_as(str(out))
        finally:
            model.close()
        with fitz.open(str(out)) as reopened:
            _vf2b_assert_page_text_kept(reopened[0], copies, f"{op} r{rotation} reopened")


@pytest.mark.parametrize("op", ["move", "delete"])
def test_textbox_saved_and_reopened_keeps_the_page_text_under_it(op: str) -> None:
    """After save/reopen the htmlbox invocation sits bare inside one merged content
    stream; the textbox drawing must still be found and removed alone."""
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, box = _vf2b_open(Path(tmp) / "vf2b_saved_src.pdf", 0)
        saved = Path(tmp) / "vf2b_saved.pdf"
        try:
            model.save_as(str(saved))
        finally:
            model.close()
        reopened = PDFModel()
        try:
            reopened.open_pdf(str(saved))
            hit = _object_hit(reopened, box.tl + (4, 4))
            assert hit is not None and hit.object_kind == "textbox"
            if op == "move":
                ok = reopened.move_object(
                    MoveObjectRequest(hit.object_id, "textbox", 1, 1, _vf2b_dest(reopened.doc[0], box))
                )
            else:
                ok = reopened.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1))
            assert ok is True
            _vf2b_assert_page_text_kept(reopened.doc[0], 1 if op == "move" else 0, f"reopened {op}")
        finally:
            reopened.close()


@pytest.mark.parametrize("op", ["move", "rotate", "delete"])
def test_textbox_drawn_partly_outside_its_xobject_refuses_instead_of_erasing_page_text(op: str) -> None:
    """A box whose words are not all in its own htmlbox drawing (a text edit drew some
    as loose page glyphs; F15-2 follow-up b: a grown box) cannot be removed as one
    object. When page text it does not own lies in the box, the op must refuse and
    change nothing rather than redact the rect."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vf2b_mixed.pdf"
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text(fitz.Point(150, 112), "KEEP", fontsize=12, fontname="helv")
        doc.save(path)
        doc.close()
        model = PDFModel()
        model.open_pdf(str(path))
        try:
            box = fitz.Rect(40, 80, 260, 140)
            model.add_textbox(1, box, "Hello", font="helv", size=12)
            page = model.doc[0]
            # The edit's loose glyphs: drawn into the page content, not the XObject.
            page.insert_text(fitz.Point(50, 132), "World", fontsize=12, fontname="helv")
            for annot in page.annots() or []:
                if annot.info.get("subject") == "pdf_editor_textbox_object":
                    payload = json.loads(annot.info.get("content") or "{}")
                    payload["text"] = "Hello\nWorld"
                    annot.set_info(content=json.dumps(payload), subject="pdf_editor_textbox_object")
                    annot.update()
            hit = _object_hit(model, box.tl + (4, 4))
            assert hit is not None and hit.object_kind == "textbox"
            before = sorted(w[4] for w in model.doc[0].get_text("words"))
            assert before == ["Hello", "KEEP", "World"]
            if op == "move":
                ok = model.move_object(MoveObjectRequest(hit.object_id, "textbox", 1, 1, box + (0, 120, 0, 120)))
            elif op == "rotate":
                ok = model.rotate_object(
                    RotateObjectRequest(object_id=hit.object_id, object_kind="textbox", page_num=1, rotation_delta=180)
                )
            else:
                ok = model.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1))
            assert ok is False
            refusal = model.last_object_op_refusal
            assert refusal is not None and refusal.reason is ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT
            assert refusal.object_kind == "textbox" and refusal.object_id == hit.object_id
            assert sorted(w[4] for w in model.doc[0].get_text("words")) == before
            assert _object_hit(model, box.tl + (4, 4)) is not None
        finally:
            model.close()


# F14-MM-2: PyMuPDF inflates a new rect annotation's /Rect by 1 pt per side (the /RD
# inset) and set_border(width=0) does not undo it. The hit bbox must be the object's TRUE
# rect (the payload rect), or every drag re-feeds the inflated rect and the box grows.

def _assert_rect_close(actual: fitz.Rect, expected: fitz.Rect, label: str) -> None:
    assert tuple(round(v, 3) for v in actual) == tuple(round(v, 3) for v in expected), (label, actual, expected)


def _move_to(model: PDFModel, hit, dest: fitz.Rect) -> None:
    ok = model.move_object(
        MoveObjectRequest(
            object_id=hit.object_id,
            object_kind=hit.object_kind,
            source_page=1,
            destination_page=1,
            destination_rect=dest,
        )
    )
    assert ok is True


def _first_glyph_origin(page: fitz.Page) -> tuple[float, float]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", ()):
            for span in line["spans"]:
                for ch in span["chars"]:
                    if ch["c"] == "M":
                        return ch["origin"]
    raise AssertionError("textbox glyph not found")


@pytest.mark.parametrize("rotation", [0, 90])
def test_textbox_hit_bbox_is_the_true_rect_and_move_round_trips(rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit, visual_rect = _open_with_textbox(Path(tmp) / f"mm2_r{rotation}.pdf", rotation)
        try:
            _assert_rect_close(hit.bbox, visual_rect, "bbox at creation")
            origin0 = _first_glyph_origin(model.doc[0])
            delta = (37.5, 61.25)
            for cycle in range(3):
                hit = _object_hit(model, visual_rect.tl + (20, 15))
                assert hit is not None
                _move_to(model, hit, fitz.Rect(hit.bbox) + (*delta, *delta))
                hit = _object_hit(model, visual_rect.tl + (20 + delta[0], 15 + delta[1]))
                assert hit is not None
                _assert_rect_close(hit.bbox, visual_rect + (*delta, *delta), f"bbox after move {cycle}")
                _move_to(model, hit, fitz.Rect(hit.bbox) - (*delta, *delta))
                hit = _object_hit(model, visual_rect.tl + (20, 15))
                assert hit is not None
                _assert_rect_close(hit.bbox, visual_rect, f"bbox after round trip {cycle}")
                origin = _first_glyph_origin(model.doc[0])
                assert origin == pytest.approx(origin0, abs=0.01), (cycle, origin, origin0)
            out = Path(tmp) / f"mm2_r{rotation}_saved.pdf"
            model.save_as(str(out))
        finally:
            model.close()
        with fitz.open(str(out)) as reopened:
            assert _first_glyph_origin(reopened[0]) == pytest.approx(origin0, abs=0.01)


def test_rect_object_hit_bbox_is_the_true_rect_and_repeated_moves_do_not_grow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mm2_rect.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(20, 90, 120, 150)
            model.tools.annotation.add_rect(1, rect, (1.0, 0.0, 0.0, 1.0), False)
            hit = _object_hit(model, fitz.Point(30, 100))
            assert hit is not None
            _assert_rect_close(hit.bbox, rect, "rect bbox at creation")
            for cycle in range(3):
                _move_to(model, hit, fitz.Rect(hit.bbox) + (40, 20, 40, 20))
                hit = _object_hit(model, fitz.Point(70, 120))
                assert hit is not None
                _assert_rect_close(hit.bbox, rect + (40, 20, 40, 20), f"rect bbox moved {cycle}")
                _move_to(model, hit, fitz.Rect(hit.bbox) - (40, 20, 40, 20))
                hit = _object_hit(model, fitz.Point(30, 100))
                assert hit is not None
                _assert_rect_close(hit.bbox, rect, f"rect bbox round trip {cycle}")
        finally:
            model.close()


# F15-3: a rect object's marker /Rect is the rect annotation ITSELF, so it lives in
# UNROTATED page space, while the hit point, destination_rect and payload rect are
# VISUAL. Hit testing and move must convert at the boundary; the oracle is the drawn ink.

_F15_3_VISUAL_RECT = fitz.Rect(100, 100, 200, 160)


def _make_rotated_rect_pdf(path: Path, rotation: int, *, cropbox: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    if cropbox:
        page.set_cropbox(fitz.Rect(30, 50, 570, 760))
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()


def _red_ink_bbox(page: fitz.Page) -> fitz.Rect | None:
    """Bounding box (visual points) of the saturated-red pixels of the rendered page."""
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    samples = pix.samples
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pix.height):
        row = y * pix.stride
        for x in range(pix.width):
            r, g, b = samples[row + x * 3], samples[row + x * 3 + 1], samples[row + x * 3 + 2]
            if r > 200 and g < 60 and b < 60:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return fitz.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _assert_ink_at(page: fitz.Page, expected: fitz.Rect, label: str) -> None:
    ink = _red_ink_bbox(page)
    assert ink is not None, (label, "no red ink drawn")
    for got, want in zip(tuple(ink), tuple(expected)):
        assert abs(got - want) <= 3.0, (label, tuple(ink), tuple(expected))


@pytest.mark.parametrize("cropbox", [False, True], ids=["plain", "crop"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rect_object_on_rotated_page_is_selectable_where_drawn_and_moves_there(
    rotation: int, cropbox: bool
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"f15_3_r{rotation}.pdf"
        _make_rotated_rect_pdf(path, rotation, cropbox=cropbox)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(_F15_3_VISUAL_RECT)
            model.tools.annotation.add_rect(1, rect, (1.0, 0.0, 0.0, 1.0), True)
            page = model.doc[0]
            _assert_ink_at(page, rect, "drawn at creation")
            # Where the ink is, the object is: every corner area and the centre hit it.
            for point in (rect.tl + (3, 3), rect.br - (3, 3), (rect.tl + rect.br) * 0.5):
                hit = _object_hit(model, fitz.Point(point))
                assert hit is not None and hit.object_kind == "rect", (rotation, point)
                _assert_rect_close(hit.bbox, rect, f"bbox at {point}")
            # Where nothing is drawn, nothing is selectable (the unrotated marker rect).
            elsewhere = fitz.Point(rect.tl + (3, 3)) * page.derotation_matrix
            if not rect.contains(elsewhere):
                assert _object_hit(model, elsewhere) is None, (rotation, elsewhere)
            hit = _object_hit(model, fitz.Point(rect.tl + (10, 10)))
            for cycle, delta in enumerate([(20.0, 0.0), (0.0, 35.0), (-20.0, -35.0)]):
                dest = fitz.Rect(hit.bbox) + (*delta, *delta)
                _move_to(model, hit, dest)
                _assert_ink_at(model.doc[0], dest, f"ink after move {cycle}")
                hit = _object_hit(model, fitz.Point(dest.tl + (10, 10)))
                assert hit is not None and hit.object_kind == "rect"
                _assert_rect_close(hit.bbox, dest, f"bbox after move {cycle}")
            _assert_ink_at(model.doc[0], rect, "ink after the round trip")
            out = Path(tmp) / "f15_3_saved.pdf"
            model.save_as(str(out))
        finally:
            model.close()
        with fitz.open(str(out)) as reopened:
            _assert_ink_at(reopened[0], rect, "ink after save and reopen")


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_delete_rect_object_on_rotated_page_removes_the_drawn_ink(rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"f15_3_del_r{rotation}.pdf"
        _make_rotated_rect_pdf(path, rotation, cropbox=False)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(_F15_3_VISUAL_RECT)
            model.tools.annotation.add_rect(1, rect, (1.0, 0.0, 0.0, 1.0), True)
            hit = _object_hit(model, fitz.Point(rect.tl + (10, 10)))
            assert hit is not None
            assert model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            ) is True
            assert _red_ink_bbox(model.doc[0]) is None
            assert _object_hit(model, fitz.Point(rect.tl + (10, 10))) is None
        finally:
            model.close()


def test_image_object_hit_bbox_is_the_true_rect_and_repeated_moves_do_not_grow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mm2_image.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
            pix.set_rect(pix.irect, (10, 120, 200))
            rect = fitz.Rect(100, 120, 180, 180)
            model.add_image_object(1, rect, pix.tobytes("png"))
            hit = _object_hit(model, fitz.Point(110, 130))
            assert hit is not None and hit.object_kind == "image"
            _assert_rect_close(hit.bbox, rect, "image bbox at creation")
            for cycle in range(2):
                _move_to(model, hit, fitz.Rect(hit.bbox) + (30, 20, 30, 20))
                hit = _object_hit(model, fitz.Point(140, 160))
                assert hit is not None and hit.object_kind == "image"
                _assert_rect_close(hit.bbox, rect + (30, 20, 30, 20), f"image bbox moved {cycle}")
                _move_to(model, hit, fitz.Rect(hit.bbox) - (30, 20, 30, 20))
                hit = _object_hit(model, fitz.Point(110, 130))
                assert hit is not None and hit.object_kind == "image"
                _assert_rect_close(hit.bbox, rect, f"image bbox round trip {cycle}")
        finally:
            model.close()


@pytest.mark.parametrize("adder", ["add_rect_annot", "add_circle_annot"])
def test_recreated_square_or_circle_annot_keeps_its_saved_outer_rect(adder: str) -> None:
    """F14-MM-2 bug class: re-creating a Square/Circle from its saved (outer) rect with
    add_rect_annot/add_circle_annot inflated it again by the library's 1 pt /RD inset."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mm2_recreate.pdf"
        _make_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            annot = getattr(page, adder)(fitz.Rect(60, 100, 160, 150))
            annot.set_colors(stroke=(1, 0, 0))
            annot.update()
            before = fitz.Rect(annot.rect)
            tool = model.tools.annotation
            saved = [dict(s, xref=None) for s in tool._save_overlapping_annots(page, fitz.Rect(0, 0, 320, 240))]
            assert len(saved) == 1
            page.delete_annot(annot)
            tool._restore_annots(page, saved)
            restored = [a for a in page.annots()]
            assert len(restored) == 1
            _assert_rect_close(restored[0].rect, before, "recreated outer rect")
        finally:
            model.close()


# F15-2: the textbox marker payload was a write-once copy of the text. After the user
# edited the textbox's words (edit_text), Rotate Object / Move re-inserted the OLD
# payload text, silently reverting the edit (also after save/reopen). A text edit must
# keep the marker in step, and move/rotate must refuse a marker whose text is no
# longer what the page draws instead of writing it back.

_F15_BOX = fitz.Rect(100, 100, 300, 160)


def _f15_model(tmp: Path, engine: str) -> PDFModel:
    from model.text_commit.dto import TextCommitSettings

    path = tmp / "f15_doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    page.insert_text(fitz.Point(72, 500), "page body far below", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    model = PDFModel(text_commit_settings=TextCommitSettings(engine=engine))
    model.open_pdf(str(path))
    return model


def _f15_words(page: fitz.Page) -> list[str]:
    return [w[4] for w in page.get_text("words")]


def _f15_marker_payloads(page: fitz.Page) -> list[dict]:
    return [
        json.loads(annot.info.get("content") or "{}")
        for annot in (page.annots() or [])
        if annot.info.get("subject") == "pdf_editor_textbox_object"
    ]


def _f15_edit(model: PDFModel, point: fitz.Point, new_text: str):
    from model.edit_commands import EditTextResult

    info = model.get_text_info_at_point(1, point, allow_fallback=False)
    assert info is not None
    result = model.edit_text(
        1,
        fitz.Rect(info.target_bbox),
        new_text,
        font=info.font,
        size=float(info.size),
        color=tuple(info.color),
        original_text=info.target_text,
        target_span_id=info.target_span_id,
        target_mode="run",
        # The finding's path: the explicit rebuild consent ("改用重建文字…").
        allow_rebuild=True,
        confirm_fallback=lambda *_a: True,
    )
    assert result is EditTextResult.SUCCESS, result
    return info


def _f15_rotate(model: PDFModel, object_id: str) -> bool:
    return model.rotate_object(
        RotateObjectRequest(
            object_id=object_id, object_kind="textbox", page_num=1,
            rotation_delta=0, absolute_rotation=90,
        )
    )


def _f15_move(model: PDFModel, object_id: str, bbox: fitz.Rect) -> bool:
    return model.move_object(
        MoveObjectRequest(object_id, "textbox", 1, 1, fitz.Rect(bbox) + (0, 200, 0, 200))
    )


@pytest.mark.parametrize("engine", ["tiered", "legacy"])
@pytest.mark.parametrize("op", ["rotate", "move"])
def test_textbox_object_op_after_text_edit_keeps_the_edited_text(engine: str, op: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), engine)
        try:
            model.add_textbox(1, _F15_BOX, "Hello", font="helv", size=14)
            model.ensure_page_index_built(1)
            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None and hit.object_kind == "textbox"
            _f15_edit(model, fitz.Point(110, 112), "Goodbye")
            assert "Goodbye" in _f15_words(model.doc[0])
            assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["Goodbye"]

            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None
            ok = _f15_rotate(model, hit.object_id) if op == "rotate" else _f15_move(model, hit.object_id, hit.bbox)
            assert ok is True
            words = _f15_words(model.doc[0])
            assert words.count("Goodbye") == 1, words
            assert "Hello" not in words, words
            assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["Goodbye"]
        finally:
            model.close()


def test_textbox_partial_line_edit_syncs_marker_and_survives_save_reopen_rotate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        out = Path(tmp) / "f15_saved.pdf"
        try:
            model.add_textbox(1, _F15_BOX, "Hello\nWorld", font="helv", size=14)
            model.ensure_page_index_built(1)
            _f15_edit(model, fitz.Point(110, 112), "Goodbye")
            payloads = _f15_marker_payloads(model.doc[0])
            assert [p["text"] for p in payloads] == ["Goodbye\nWorld"]
            object_id = payloads[0]["object_id"]
            model.save_as(str(out))
        finally:
            model.close()

        reopened = PDFModel()
        try:
            reopened.open_pdf(str(out))
            assert [p["text"] for p in _f15_marker_payloads(reopened.doc[0])] == ["Goodbye\nWorld"]
            assert _f15_rotate(reopened, object_id) is True
            words = _f15_words(reopened.doc[0])
            assert "Goodbye" in words and "World" in words, words
            assert "Hello" not in words, words
        finally:
            reopened.close()


def test_textbox_edit_to_empty_removes_the_object_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "Hello", font="helv", size=14)
            model.ensure_page_index_built(1)
            _f15_edit(model, fitz.Point(110, 112), "")
            assert "Hello" not in _f15_words(model.doc[0])
            # The box is empty: a surviving marker would let Rotate/Move re-insert "Hello".
            assert _f15_marker_payloads(model.doc[0]) == []
            assert _object_hit(model, fitz.Point(110, 110)) is None
        finally:
            model.close()


def _f15_age_textbox_marker(page: fitz.Page, **fields) -> None:
    """Rewrite the (one) textbox marker the way an older build left it."""
    for annot in page.annots() or []:
        if annot.info.get("subject") == "pdf_editor_textbox_object":
            payload = json.loads(annot.info.get("content") or "{}")
            payload.update(fields)
            annot.set_info(content=json.dumps(payload), subject="pdf_editor_textbox_object")
            annot.update()
            return
    raise AssertionError("no textbox marker")


def _f15_op(model: PDFModel, op: str, object_id: str, bbox: fitz.Rect) -> bool:
    if op == "rotate":
        return _f15_rotate(model, object_id)
    if op == "move":
        return _f15_move(model, object_id, bbox)
    return model.delete_object(DeleteObjectRequest(object_id, "textbox", 1))


@pytest.mark.parametrize("variant", ["live", "saved_and_reopened", "page_rotate_90"])
@pytest.mark.parametrize("op", ["rotate", "move", "delete"])
def test_textbox_with_stale_marker_text_is_repaired_from_its_one_drawing(op: str, variant: str) -> None:
    """D-OLD-MARKERS (was: refuse). A file saved by a build without the sync carries a
    marker whose text the page no longer draws. When exactly one htmlbox drawing shares
    the marker's centre and angle and holds everything drawn in the box, the marker is
    re-resolved to the text that drawing shows, so the op moves what the user sees and
    never writes the old words back. Also after a save/reopen (the real old-file case:
    fonts are compacted and renamed on save) and on a /Rotate 90 page."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            box = _F15_BOX
            if variant == "page_rotate_90":
                model.doc[0].set_rotation(90)
                box = fitz.Rect(300, 100, 500, 160)  # clear of the page body text (unrotated y 100..300)
            model.add_textbox(1, box, "Goodbye", font="helv", size=14)
            _f15_age_textbox_marker(model.doc[0], text="Hello")
            if variant == "saved_and_reopened":
                saved = Path(tmp) / "old_build_saved.pdf"
                model.save_as(str(saved))
                model.close()
                model = PDFModel()
                model.open_pdf(str(saved))
                assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["Hello"]
            hit = _object_hit(model, box.tl + (10, 10))
            assert hit is not None and hit.object_kind == "textbox"
            assert _f15_op(model, op, hit.object_id, hit.bbox) is True
            assert model.last_object_op_refusal is None
            words = _f15_words(model.doc[0])
            assert words.count("Goodbye") == (0 if op == "delete" else 1), words
            assert "Hello" not in words, words
            texts = [p["text"] for p in _f15_marker_payloads(model.doc[0])]
            assert texts == ([] if op == "delete" else ["Goodbye"])
        finally:
            model.close()


@pytest.mark.parametrize("op", ["rotate", "move"])
def test_annotation_appearance_text_does_not_prove_the_marker_text_is_drawn(op: str) -> None:
    """GATE15-2 / F11-ANN-4: the "page still draws the stored text" check reads page
    CONTENT only. A visible FreeText comment lying in the box that spells the stale
    marker text must not count as the page drawing it."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "Goodbye", font="helv", size=14)
            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") == "pdf_editor_textbox_object":
                    payload = json.loads(annot.info.get("content") or "{}")
                    payload["text"] = "Hello"
                    annot.set_info(content=json.dumps(payload), subject="pdf_editor_textbox_object")
                    annot.update()
            page.add_freetext_annot(fitz.Rect(110, 130, 290, 155), "Hello", fontsize=11).update()
            assert "Hello" in _f15_words(model.doc[0])  # the annotation text is visible
            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None and hit.object_kind == "textbox"
            ok = _f15_rotate(model, hit.object_id) if op == "rotate" else _f15_move(model, hit.object_id, hit.bbox)
            # D-OLD-MARKERS: the stale marker is re-resolved from the page CONTENT (its one
            # htmlbox drawing, 'Goodbye'), never from the comment that spells 'Hello'.
            assert ok is True
            assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["Goodbye"]
            content_words = [w[4] for w in content_text(model.doc[0], "words")]
            assert content_words.count("Goodbye") == 1 and "Hello" not in content_words, content_words
        finally:
            model.close()


def test_textbox_text_dragged_out_of_the_box_leaves_no_marker_behind() -> None:
    """A same-page drag (edit_text with new_rect) that lands outside the box takes the
    text out of the object; the emptied marker must not re-insert it on Rotate."""
    from model.edit_commands import EditTextResult

    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "Hello", font="helv", size=14)
            model.ensure_page_index_built(1)
            info = model.get_text_info_at_point(1, fitz.Point(110, 112), allow_fallback=False)
            assert info is not None
            result = model.edit_text(
                1,
                fitz.Rect(info.target_bbox),
                "Hello",
                font=info.font,
                size=float(info.size),
                color=tuple(info.color),
                original_text=info.target_text,
                target_span_id=info.target_span_id,
                target_mode="run",
                new_rect=fitz.Rect(100, 300, 300, 340),
                allow_rebuild=True,
                confirm_fallback=lambda *_a: True,
            )
            assert result is EditTextResult.SUCCESS, result
            assert _f15_words(model.doc[0]).count("Hello") == 1
            assert _f15_marker_payloads(model.doc[0]) == []
            assert _object_hit(model, fitz.Point(110, 110)) is None
        finally:
            model.close()


@pytest.mark.parametrize(
    ("stored", "old", "new", "expected"),
    [
        ("Hello", "Hello", "Goodbye", "Goodbye"),
        ("Hello\nWorld", "Hello", "Goodbye", "Goodbye\nWorld"),
        # the index joins wrapped lines without the stored whitespace
        ("Hello big\nWorld", "Hellobig", "X", "X\nWorld"),
        ("Hello\nWorld", "World", "", "Hello"),
        ("ab ab", "ab", "cd", None),  # ambiguous: never guess
        ("Hello", "Bye", "X", None),  # absent
        ("Hello", "", "X", None),  # nothing to place
    ],
)
def test_textbox_marker_text_replacement_ignores_whitespace_and_refuses_to_guess(
    stored: str, old: str, new: str, expected: str | None
) -> None:
    from model.pdf_object_ops import _replace_ignoring_whitespace

    assert _replace_ignoring_whitespace(stored, old, new) == expected


@pytest.mark.parametrize(
    ("stored", "old", "count"),
    [
        ("Hello", "Hello", 1),
        ("Hello big\nWorld", "Hellobig", 1),
        ("ab ab", "ab", 2),
        ("aaa", "aa", 2),
        ("Hello", "Bye", 0),
        ("Hello", "", 0),
    ],
)
def test_textbox_marker_occurrence_count_ignores_whitespace(stored: str, old: str, count: int) -> None:
    from model.pdf_object_ops import _occurrences_ignoring_whitespace

    assert _occurrences_ignoring_whitespace(stored, old) == count


def test_textbox_marker_the_sync_cannot_place_is_flagged_and_refuses_rotate() -> None:
    from model.pdf_object_ops import sync_textbox_markers_after_text_edit

    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "ab ab", font="helv", size=14)
            inside = [fitz.Rect(102, 102, 140, 120)]
            # Text the box does not hold (page text under it was edited): untouched.
            sync_textbox_markers_after_text_edit(model, 1, member_rects=inside, source_text="Nope", new_text="X")
            payloads = _f15_marker_payloads(model.doc[0])
            assert len(payloads) == 1 and payloads[0]["text"] == "ab ab"
            assert "content_unsynced" not in payloads[0]
            # Ambiguous (twice in the box): never guess, flag it.
            sync_textbox_markers_after_text_edit(model, 1, member_rects=inside, source_text="ab", new_text="cd")
            payloads = _f15_marker_payloads(model.doc[0])
            assert len(payloads) == 1 and payloads[0]["text"] == "ab ab"
            assert payloads[0]["content_unsynced"] is True
            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None
            assert _f15_rotate(model, hit.object_id) is False
            # D-OLD-MARKERS: never silent; a flagged marker is not "repaired" (the flag is
            # this build's own record that an edit could not be placed).
            assert model.last_object_op_refusal.reason is ObjectOpRefusal.TEXTBOX_TEXT_CHANGED
            assert _f15_words(model.doc[0]).count("ab") == 2
            # A marker outside the edited runs is not touched.
            sync_textbox_markers_after_text_edit(
                model, 1, member_rects=[fitz.Rect(10, 400, 40, 420)], source_text="ab ab", new_text="Y"
            )
            assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["ab ab"]
        finally:
            model.close()


@pytest.mark.parametrize("rotation", [0, 90])
def test_textbox_grown_by_a_longer_edit_still_rotates_with_the_new_text(rotation: int) -> None:
    """The legacy rebuild lays a longer text out past the box: the marker rect must grow
    over the new words, or Rotate / Move erase only part of them (or refuse)."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            if rotation:
                model.doc[0].set_rotation(rotation)
            box = fitz.Rect(100, 100, 200, 122)
            model.add_textbox(1, box, "Hello", font="helv", size=14)
            model.ensure_page_index_built(1)
            long_text = "Goodbye cruel world of very long words here"
            info = model.get_text_info_at_point(1, box.tl + (10, 12), allow_fallback=False)
            assert info is not None and info.target_text.strip() == "Hello"
            _f15_edit(model, box.tl + (10, 12), long_text)
            payloads = _f15_marker_payloads(model.doc[0])
            assert [p["text"] for p in payloads] == [long_text]
            grown = fitz.Rect(payloads[0]["rect"])
            assert grown.contains(box) and grown != box
            hit = _object_hit(model, box.tl + (10, 10))
            assert hit is not None
            assert _f15_rotate(model, hit.object_id) is True
            words = _f15_words(model.doc[0])
            for token in long_text.split():
                assert words.count(token) == 1, (token, words)
            assert "Hello" not in words
        finally:
            model.close()


# --- F15-6: rotating a textbox turns its box, it must not re-flow the text ----------------

_F15_6_TEXT = "Quarterly revenue summary"


def _f15_6_text_spans(page: fitz.Page) -> list[dict]:
    return [
        span
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if "LEGACY" not in span["text"] and span["text"].strip()
    ]


def _f15_6_open(tmp: str, box: fitz.Rect, page_rotation: int = 0) -> tuple[PDFModel, object]:
    path = Path(tmp) / "f15_6.pdf"
    _make_pdf(path)
    model = PDFModel()
    model.open_pdf(str(path))
    if page_rotation:
        model.doc[0].set_rotation(page_rotation)
    model.add_textbox(1, box, _F15_6_TEXT, font="helv", size=14)
    hit = _object_hit(model, box.tl + (5, 5))
    assert hit is not None and hit.object_kind == "textbox"
    return model, hit


def _f15_6_rotate_to(model: PDFModel, hit, angle: int) -> bool:
    return model.rotate_object(
        RotateObjectRequest(
            object_id=hit.object_id,
            object_kind=hit.object_kind,
            page_num=1,
            rotation_delta=0,
            absolute_rotation=angle,
        )
    )


def _f15_6_payload_rect(model: PDFModel) -> fitz.Rect:
    payloads = _f15_marker_payloads(model.doc[0])
    assert len(payloads) == 1
    return fitz.Rect(payloads[0]["rect"])


def _assert_text_not_reflowed(model: PDFModel, label: str) -> None:
    spans = _f15_6_text_spans(model.doc[0])
    assert [span["text"] for span in spans] == [_F15_6_TEXT], (label, [s["text"] for s in spans])
    assert abs(spans[0]["size"] - 14.0) < 0.01, (label, spans[0]["size"])


@pytest.mark.parametrize("page_rotation", [0, 90])
@pytest.mark.parametrize("angle", [90, 180, 270, 0])
def test_rotating_a_textbox_keeps_its_font_size_and_line_count(angle: int, page_rotation: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, hit = _f15_6_open(tmp, fitz.Rect(50, 100, 250, 130), page_rotation)
        try:
            _assert_text_not_reflowed(model, "added")
            assert _f15_6_rotate_to(model, hit, angle) is True
            _assert_text_not_reflowed(model, f"rotated to {angle}")
        finally:
            model.close()


@pytest.mark.parametrize("angle", [90, 270])
def test_quarter_turn_swaps_the_box_about_its_centre_and_text_stays_inside(angle: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        box = fitz.Rect(50, 100, 250, 130)
        model, hit = _f15_6_open(tmp, box)
        try:
            assert _f15_6_rotate_to(model, hit, angle) is True
            turned = _f15_6_payload_rect(model)
            _assert_rect_close(turned, fitz.Rect(135, 15, 165, 215), "turned box")
            moved_hit = _object_hit(model, fitz.Point(150, 60))
            assert moved_hit is not None and moved_hit.object_id == hit.object_id
            _assert_rect_close(fitz.Rect(moved_hit.bbox), turned, "hit bbox follows the turned box")
            assert _object_hit(model, fitz.Point(60, 115)) is None  # old wide rect is gone
            zone = turned + (-2, -2, 2, 2)
            for span in _f15_6_text_spans(model.doc[0]):
                assert zone.contains(fitz.Rect(span["bbox"])), (angle, span["bbox"], turned)
        finally:
            model.close()


def test_textbox_quarter_turn_round_trip_restores_the_original_box() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        box = fitz.Rect(50, 100, 250, 130)
        model, hit = _f15_6_open(tmp, box)
        try:
            for angle in (90, 180, 270, 0):
                assert _f15_6_rotate_to(model, hit, angle) is True
                _assert_text_not_reflowed(model, f"step {angle}")
            _assert_rect_close(_f15_6_payload_rect(model), box, "round trip box")
            before = _f15_6_text_spans(model.doc[0])[0]["bbox"]
            assert fitz.Rect(before).intersects(box)
            # Delta rotation turns the box the same way as the absolute form.
            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind="textbox",
                    page_num=1,
                    rotation_delta=90,
                )
            )
            _assert_rect_close(_f15_6_payload_rect(model), fitz.Rect(135, 15, 165, 215), "delta turn")
            _assert_text_not_reflowed(model, "delta 90")
        finally:
            model.close()


def test_quarter_turn_near_the_page_edge_slides_the_box_in_instead_of_cropping_it() -> None:
    """Page is 320x240: the turned box is 200 tall, so about the centre it would cross the
    bottom edge. Clamping would crop it and re-flow (shrink) the text."""
    with tempfile.TemporaryDirectory() as tmp:
        model, hit = _f15_6_open(tmp, fitz.Rect(0, 200, 200, 230))
        try:
            assert _f15_6_rotate_to(model, hit, 90) is True
            turned = _f15_6_payload_rect(model)
            assert abs(turned.width - 30) < 0.01 and abs(turned.height - 200) < 0.01, turned
            assert fitz.Rect(model.doc[0].rect).contains(turned), turned
            _assert_text_not_reflowed(model, "edge")
        finally:
            model.close()


# F16-1: PyMuPDF 1.27's htmlbox draws emoji and shaped scripts correctly but writes a
# lossy text layer for them (U+1F600 reads back as U+1F60, Devanagari conjuncts and the
# Arabic lam-lam ligature as glyph ids). That loss is accepted (OD-UNI1-COMMIT), but the
# textbox object ops compared the RAW stored text with the page text layer, so Move,
# Rotate and Delete refused such a box right after it was created.
_F16_LOSSY_TEXTS = {
    "emoji": "Hi \U0001F600 there",
    "devanagari": "नमस्ते दुनिया",
    "arabic": "مرحبا بالعالم",
    "ext_b": "\U00020000\U00020001 ext b",
    # Only Ext-B: its text layer is spaces, so nothing of it can be compared as text.
    "ext_b_only": "\U00020000\U00020001",
}
_F16_BOX = fitz.Rect(100, 100, 300, 160)


def _f16_open(tmp: Path, rotation: int, text: str) -> tuple[PDFModel, object]:
    path = tmp / f"f16_r{rotation}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    model.add_textbox(1, _F16_BOX, text, font="helv", size=14)
    hit = _object_hit(model, _F16_BOX.tl + (10, 10))
    assert hit is not None and hit.object_kind == "textbox"
    return model, hit


def _f16_delete_at(model: PDFModel, point: fitz.Point) -> None:
    hit = _object_hit(model, point)
    assert hit is not None and hit.object_kind == "textbox"
    assert model.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1)) is True


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("label", list(_F16_LOSSY_TEXTS))
@pytest.mark.parametrize("op", ["move", "rotate180", "rotate90", "delete"])
def test_textbox_with_a_lossy_text_layer_moves_rotates_and_deletes(op: str, label: str, rotation: int) -> None:
    if label == "ext_b_only":
        from utils.cjk_ext_b_font import find_ext_b_fonts

        if not find_ext_b_fonts():
            pytest.skip("no Ext-B font installed: htmlbox draws .notdef for Ext-B")
    with tempfile.TemporaryDirectory() as tmp:
        model, hit = _f16_open(Path(tmp), rotation, _F16_LOSSY_TEXTS[label])
        out = Path(tmp) / "f16_saved.pdf"
        try:
            before = sorted(_f15_words(model.doc[0]))
            assert before, (label, rotation)
            if op == "move":
                dest = fitz.Rect(hit.bbox) + (0, 200, 0, 200)
                ok = model.move_object(MoveObjectRequest(hit.object_id, "textbox", 1, 1, dest))
                assert ok is True, (op, label, rotation)
                # One copy, at the destination; nothing left at the old place.
                assert sorted(_f15_words(model.doc[0])) == before
                assert _object_hit(model, _F16_BOX.tl + (10, 10)) is None
                _f16_delete_at(model, dest.tl + (10, 10))
            elif op == "rotate180":
                ok = model.rotate_object(
                    RotateObjectRequest(object_id=hit.object_id, object_kind="textbox", page_num=1, rotation_delta=180)
                )
                assert ok is True, (op, label, rotation)
                assert sorted(_f15_words(model.doc[0])) == before
                _f16_delete_at(model, fitz.Rect(hit.bbox).tl + (10, 10))
            elif op == "rotate90":
                # The finding's path: an absolute quarter turn (the box turns and rewraps).
                ok = model.rotate_object(
                    RotateObjectRequest(
                        object_id=hit.object_id, object_kind="textbox", page_num=1,
                        rotation_delta=0, absolute_rotation=90,
                    )
                )
                assert ok is True, (op, label, rotation)
                centre = fitz.Rect(hit.bbox)
                _f16_delete_at(model, fitz.Point((centre.x0 + centre.x1) / 2, (centre.y0 + centre.y1) / 2))
            else:
                ok = model.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1))
                assert ok is True, (op, label, rotation)
            # Every path ends with the box deleted: the original drawing and the
            # re-inserted one were both removed, no copy and no marker left behind.
            assert _f15_words(model.doc[0]) == [], (op, label, rotation)
            assert _f15_marker_payloads(model.doc[0]) == []
            model.save_as(str(out))
        finally:
            model.close()
        with fitz.open(str(out)) as reopened:
            assert reopened[0].get_text("words") == []


@pytest.mark.parametrize("op", ["rotate", "move"])
def test_textbox_lossy_text_layer_still_refuses_a_stale_marker(op: str) -> None:
    """F16-1 leniency is bounded: the stored text is compared with what htmlbox's text
    layer carries for it, so a stale emoji box (stored 'there', page draws 'here')
    still refuses Move / Rotate instead of writing the old words back."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "Hi \U0001F600 here", font="helv", size=14)
            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") == "pdf_editor_textbox_object":
                    payload = json.loads(annot.info.get("content") or "{}")
                    payload["text"] = "Hi \U0001F600 there"
                    annot.set_info(content=json.dumps(payload), subject="pdf_editor_textbox_object")
                    annot.update()
            before = _f15_words(model.doc[0])
            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None and hit.object_kind == "textbox"
            ok = _f15_rotate(model, hit.object_id) if op == "rotate" else _f15_move(model, hit.object_id, hit.bbox)
            assert ok is False
            assert model.last_object_op_refusal.reason is ObjectOpRefusal.TEXTBOX_TEXT_CHANGED
            assert _f15_words(model.doc[0]) == before
            assert "there" not in before
            # D-OLD-MARKERS: the lossy text layer ('U+1F60' for the emoji) must never be
            # written back into the marker as a "repair".
            assert [p["text"] for p in _f15_marker_payloads(model.doc[0])] == ["Hi \U0001F600 there"]
        finally:
            model.close()


# F16-1-LOSSY (round 17): the marker sync matched the index text (htmlbox's LOSSY text
# layer: U+1F600 reads back as U+1F60) against the RAW stored text, so an edit whose
# source run held a lossy character found no occurrence, left the marker stale and the
# next Move refused; a longer text was not grown over either.
_F17_LOSSY_OLD = "Hi \U0001F600 there"


def _f17_lossy_paragraph_edit(model: PDFModel, new_text: str):
    from model.edit_commands import EditTextResult

    model.ensure_page_index_built(1)
    info = model.get_text_info_at_point(1, _F16_BOX.tl + (4, 8), allow_fallback=False)
    assert info is not None
    result = model.edit_text(
        1,
        fitz.Rect(info.target_bbox),
        new_text,
        font=info.font,
        size=float(info.size),
        color=tuple(info.color),
        original_text=info.target_text,
        target_span_id=info.target_span_id,
        target_mode="paragraph",
        allow_rebuild=True,
        confirm_fallback=lambda *_a: True,
    )
    assert result is EditTextResult.SUCCESS, result
    return info


@pytest.mark.parametrize(
    "new_text",
    [
        "Hi X",
        "Hi and a much longer replacement that should wrap over several lines inside the box",
        "Hi \U0001F600 and a much longer replacement that should wrap over several lines inside the box",
    ],
    ids=["short", "long_latin", "long_with_emoji"],
)
def test_f17_edit_of_a_lossy_textbox_syncs_the_marker_grows_it_and_moves(new_text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        model, _hit = _f16_open(Path(tmp), 0, _F17_LOSSY_OLD)
        try:
            _f17_lossy_paragraph_edit(model, new_text)
            (payload,) = _f15_marker_payloads(model.doc[0])
            assert payload["text"] == new_text, payload
            assert not payload.get("content_unsynced")
            marker_rect = fitz.Rect(payload["rect"])
            ink = [fitz.Rect(w[:4]) for w in model.doc[0].get_text("words")]
            assert ink and all(marker_rect.contains(r + (1, 1, -1, -1)) for r in ink), (marker_rect, ink)
            hit = _object_hit(model, _F16_BOX.tl + (4, 4))
            assert hit is not None and hit.object_kind == "textbox"
            dest = fitz.Rect(hit.bbox) + (0, 200, 0, 200)
            before = sorted(_f15_words(model.doc[0]))
            assert model.move_object(MoveObjectRequest(hit.object_id, "textbox", 1, 1, dest)) is True
            assert sorted(_f15_words(model.doc[0])) == before
            assert all(fitz.Rect(w[:4]).y0 >= dest.y0 - 1 for w in model.doc[0].get_text("words"))
        finally:
            model.close()


@pytest.mark.parametrize(
    ("stored", "source", "new", "expected"),
    [
        # a run that mixes Latin with the lossy emoji: the index text is "aὠb"
        ("a\U0001F600b cd", "aὠb", "Z", "Z cd"),
        # the lossy character alone (the run IS the emoji)
        ("Hi \U0001F600 there", "ὠ", "ok", "Hi ok there"),
        # the whole box: the index joins the runs differently from the stored text
        ("Hi \U0001F600\nthere", "Hiὠthere", "Bye", "Bye"),
        # a Latin run inside the box still takes the raw path
        ("Hi \U0001F600 there", "there", "here", "Hi \U0001F600 here"),
    ],
)
def test_f17_sync_places_a_lossy_index_text_in_the_stored_text(
    stored: str, source: str, new: str, expected: str
) -> None:
    from model.pdf_object_ops import sync_textbox_markers_after_text_edit

    with tempfile.TemporaryDirectory() as tmp:
        model, _hit = _f16_open(Path(tmp), 0, stored)
        try:
            sync_textbox_markers_after_text_edit(
                model, 1, member_rects=[fitz.Rect(102, 102, 140, 120)], source_text=source, new_text=new
            )
            (payload,) = _f15_marker_payloads(model.doc[0])
            assert payload["text"] == expected
            assert not payload.get("content_unsynced")
        finally:
            model.close()


@pytest.mark.parametrize(
    ("stored", "source", "flagged"),
    [
        # two emoji both read back as U+1F60: the edited one cannot be told apart
        ("a\U0001F600b\U0001F600c", "ὠ", True),
        # the edited text is in neither the stored text nor its text layer: not this box's
        ("Hi \U0001F600 there", "Nope", False),
    ],
)
def test_f17_sync_flags_an_ambiguous_lossy_source_and_leaves_foreign_text_alone(
    stored: str, source: str, flagged: bool
) -> None:
    from model.pdf_object_ops import sync_textbox_markers_after_text_edit

    with tempfile.TemporaryDirectory() as tmp:
        model, _hit = _f16_open(Path(tmp), 0, stored)
        try:
            sync_textbox_markers_after_text_edit(
                model, 1, member_rects=[fitz.Rect(102, 102, 140, 120)], source_text=source, new_text="Z"
            )
            (payload,) = _f15_marker_payloads(model.doc[0])
            assert payload["text"] == stored
            assert bool(payload.get("content_unsynced")) is flagged
        finally:
            model.close()


@pytest.mark.parametrize("label", ["emoji", "devanagari", "arabic"])
@pytest.mark.parametrize("op", ["move", "delete"])
def test_textbox_with_a_lossy_text_layer_over_page_text_removes_only_its_own_drawing(op: str, label: str) -> None:
    """F16-1 + F13-VF-2b: the box's own htmlbox form is identified by the characters
    htmlbox's text layer writes for the stored text, so a lossy box lying over page text
    it does not own is removed alone instead of being refused (the guarded rect
    redaction would see its lossy characters as foreign page text)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "f16_keep.pdf"
        doc = fitz.open()
        page = doc.new_page(width=420, height=600)
        page.insert_text(fitz.Point(150, 130), "KEEP", fontsize=12, fontname="helv")
        doc.save(path)
        doc.close()
        model = PDFModel()
        model.open_pdf(str(path))
        try:
            model.add_textbox(1, _F16_BOX, _F16_LOSSY_TEXTS[label], font="helv", size=14)
            hit = _object_hit(model, _F16_BOX.tl + (4, 4))
            assert hit is not None and hit.object_kind == "textbox"
            box_words = sorted(w for w in _f15_words(model.doc[0]) if w != "KEEP")
            if op == "move":
                dest = fitz.Rect(hit.bbox) + (0, 200, 0, 200)
                assert model.move_object(MoveObjectRequest(hit.object_id, "textbox", 1, 1, dest)) is True
                assert sorted(_f15_words(model.doc[0])) == sorted([*box_words, "KEEP"])
                moved = [w for w in model.doc[0].get_text("words") if w[4] != "KEEP"]
                assert moved and all(fitz.Rect(w[:4]).y0 >= dest.y0 - 1 for w in moved), moved
            else:
                assert model.delete_object(DeleteObjectRequest(hit.object_id, "textbox", 1)) is True
                assert _f15_words(model.doc[0]) == ["KEEP"]
        finally:
            model.close()


# --- D-OLD-MARKERS: textbox markers that do not resolve ---------------------------------


@pytest.mark.parametrize("op", ["rotate", "move", "delete"])
@pytest.mark.parametrize(
    "case", ["loose_glyphs_in_box", "two_same_centre_drawings", "drawing_of_another_box"]
)
def test_textbox_stale_marker_without_one_clear_drawing_refuses_with_a_reason(case: str, op: str) -> None:
    """No guess: when the box holds more than one drawing's text (a loose word an older
    edit drew, or a second box drawn at the same centre), or the one drawing there is
    another, healthy textbox's (the stale marker's own drawing is gone), the stale marker
    stays as it is, the page is unchanged and the op reports TEXTBOX_TEXT_CHANGED."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, "Goodbye", font="helv", size=14)
            page = model.doc[0]
            if case == "loose_glyphs_in_box":
                page.insert_text(fitz.Point(110, 150), "KEEP", fontsize=12, fontname="helv")
            _f15_age_textbox_marker(page, text="Hello")
            if case == "drawing_of_another_box":
                # An external tool removed the stale box's drawing, then a healthy box
                # was added at the same place.
                (form_xref,) = [x[0] for x in page.get_xobjects() if x[2] == 0]
                model.doc.update_stream(form_xref, b" ")
                assert "Goodbye" not in _f15_words(page)
            if case in ("two_same_centre_drawings", "drawing_of_another_box"):
                model.add_textbox(1, _F15_BOX, "Goodbye", font="helv", size=14)
            payloads_before = _f15_marker_payloads(model.doc[0])
            stale = next(p for p in payloads_before if p["text"] == "Hello")
            words_before = sorted(_f15_words(model.doc[0]))
            assert _f15_op(model, op, stale["object_id"], fitz.Rect(stale["rect"])) is False
            refusal = model.last_object_op_refusal
            assert refusal is not None and refusal.reason is ObjectOpRefusal.TEXTBOX_TEXT_CHANGED
            assert refusal.object_kind == "textbox" and refusal.object_id == stale["object_id"]
            assert sorted(_f15_words(model.doc[0])) == words_before
            assert _f15_marker_payloads(model.doc[0]) == payloads_before
        finally:
            model.close()


_DOM_LONG_TEXT = "Alpha Beta Gamma Delta Epsilon"


@pytest.mark.parametrize("op", ["rotate", "move"])
def test_textbox_marker_with_the_pre_rotation_rect_is_repaired_to_its_drawing(op: str) -> None:
    """Same text, same angle, same centre, stale rect: an old marker that kept the box
    from before a quarter turn while the drawing was turned about its centre. The words
    centred outside the stale rect made Move/Rotate refuse; the one same-centre drawing
    is the clear candidate, so the rect is re-resolved and every word follows."""
    with tempfile.TemporaryDirectory() as tmp:
        model = _f15_model(Path(tmp), "legacy")
        try:
            model.add_textbox(1, _F15_BOX, _DOM_LONG_TEXT, font="helv", size=14)
            hit = _object_hit(model, fitz.Point(110, 110))
            assert hit is not None
            assert _f15_rotate(model, hit.object_id) is True
            (turned_payload,) = _f15_marker_payloads(model.doc[0])
            turned = fitz.Rect(turned_payload["rect"])
            assert turned != _F15_BOX and int(turned_payload["rotation"]) == 90
            _f15_age_textbox_marker(model.doc[0], rect=[_F15_BOX.x0, _F15_BOX.y0, _F15_BOX.x1, _F15_BOX.y1])
            if op == "rotate":
                ok = model.rotate_object(
                    RotateObjectRequest(
                        object_id=hit.object_id, object_kind="textbox", page_num=1,
                        rotation_delta=0, absolute_rotation=0,
                    )
                )
            else:
                ok = _f15_move(model, hit.object_id, turned)
            assert ok is True
            assert model.last_object_op_refusal is None
            words = _f15_words(model.doc[0])
            for token in _DOM_LONG_TEXT.split():
                assert words.count(token) == 1, (token, words)
            (after,) = _f15_marker_payloads(model.doc[0])
            assert after["text"] == _DOM_LONG_TEXT
            if op == "move":
                expected = turned + (0, 200, 0, 200)
                got = fitz.Rect(after["rect"])
                assert max(abs(a - b) for a, b in zip(got, expected)) <= 1.0, (got, expected)
        finally:
            model.close()


# F15-G1-UU-ANNOT: the same rect object on a ROTATED /UserUnit != 1 page.  The rect
# annotation takes TRUE unrotated space (model.geometry) from add_rect_annot, while
# ``Annot.rect`` / ``set_rect`` live in PyMuPDF's /UserUnit-less derotated space, so
# the marker was created, picked and moved in different spaces there.

_F15_G1_UU_RECT = fitz.Rect(30, 40, 90, 80)


def _make_rotated_user_unit_pdf(path: Path, rotation: int, user_unit: float) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    doc.reload_page(page)
    doc[0].set_rotation(rotation)
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("user_unit", [2.0, 0.5])
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rect_object_on_rotated_user_unit_page_is_drawn_picked_moved_and_deleted_in_place(
    rotation: int, user_unit: float
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"f15_g1_uu_r{rotation}.pdf"
        _make_rotated_user_unit_pdf(path, rotation, user_unit)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(_F15_G1_UU_RECT)
            model.tools.annotation.add_rect(1, rect, (1.0, 0.0, 0.0, 1.0), True)
            _assert_ink_at(model.doc[0], rect, "drawn at creation")
            centre = (rect.tl + rect.br) * 0.5
            hit = _object_hit(model, fitz.Point(centre))
            assert hit is not None and hit.object_kind == "rect", (rotation, user_unit)
            _assert_rect_close(hit.bbox, rect, "bbox at creation")
            far = fitz.Point(rect.br + (40, 30))
            assert _object_hit(model, far) is None
            for cycle, delta in enumerate([(25.0, 0.0), (0.0, 20.0), (-25.0, -20.0)]):
                dest = fitz.Rect(hit.bbox) + (*delta, *delta)
                _move_to(model, hit, dest)
                _assert_ink_at(model.doc[0], dest, f"ink after move {cycle}")
                hit = _object_hit(model, fitz.Point((dest.tl + dest.br) * 0.5))
                assert hit is not None and hit.object_kind == "rect"
                _assert_rect_close(hit.bbox, dest, f"bbox after move {cycle}")
            _assert_ink_at(model.doc[0], rect, "ink after the round trip")
            moved = fitz.Rect(rect) + (30.0, 20.0, 30.0, 20.0)
            _move_to(model, hit, moved)
            out = Path(tmp) / f"f15_g1_uu_r{rotation}_saved.pdf"
            model.save_as(str(out))
            with fitz.open(str(out)) as reopened:
                _assert_ink_at(reopened[0], moved, "ink after save and reopen")
            hit = _object_hit(model, fitz.Point((moved.tl + moved.br) * 0.5))
            assert hit is not None
            assert model.delete_object(
                DeleteObjectRequest(object_id=hit.object_id, object_kind=hit.object_kind, page_num=1)
            ) is True
            assert _red_ink_bbox(model.doc[0]) is None
        finally:
            model.close()
