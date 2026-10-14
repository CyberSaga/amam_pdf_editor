"""Regression tests for add_text textbox mode backend behavior."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import AddTextboxCommand
from model.pdf_model import PDFModel


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def _make_pdf(path: Path, rotation: int = 0, with_seed: bool = False) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.set_rotation(rotation)
    if with_seed:
        page.insert_text(fitz.Point(40, 40), "KEEP_ORIGINAL", fontsize=12, fontname="helv", color=(0, 0, 0))
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 12, 12), 0)
        pix.clear_with(180)
        page.insert_image(fitz.Rect(220, 30, 260, 70), pixmap=pix)
        annot = page.add_rect_annot(fitz.Rect(40, 80, 110, 120))
        annot.update()
    doc.save(path)
    doc.close()


def _first_span_bbox_contains(page: fitz.Page, token: str) -> fitz.Rect | None:
    probe = _norm(token)
    data = page.get_text("dict", flags=0)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if probe in _norm(text):
                    return fitz.Rect(span["bbox"])
    return None


def test_add_textbox_rotation_anchor_visual_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for rot in (0, 90, 180, 270):
            path = Path(tmp) / f"rot_{rot}.pdf"
            _make_pdf(path, rotation=rot, with_seed=False)

            model = PDFModel()
            try:
                model.open_pdf(str(path))
                visual_rect = fitz.Rect(70, 58, 190, 116)
                token = f"ROT{rot}"
                model.add_textbox(
                    page_num=1,
                    visual_rect=visual_rect,
                    text=token,
                    font="",
                    size=18,
                    color=(0, 0, 0),
                )

                page = model.doc[0]
                span_bbox = _first_span_bbox_contains(page, token)
                assert span_bbox is not None, f"missing inserted token on rotation={rot}"
                visual_bbox = span_bbox * page.rotation_matrix

                # Anchor should map close to visual click-top-left regardless of page rotation.
                assert abs(visual_bbox.x0 - visual_rect.x0) <= 8.0, (rot, visual_bbox, visual_rect)
                assert abs(visual_bbox.y0 - visual_rect.y0) <= 20.0, (rot, visual_bbox, visual_rect)
            finally:
                model.close()


# Page geometries whose page space (``page.rect``) is NOT the raw CropBox:
# PyMuPDF reports ``page.cropbox`` MediaBox-relative and y-flipped, in raw
# PDF units, so a CropBox inside the MediaBox, a MediaBox origin away from
# (0,0) and ``/UserUnit 2`` each make it disagree with page space.
_BOX_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 500, 700)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
    "uu2": {"mediabox": (0, 0, 300, 400), "userunit": 2},
}


def _make_box_geometry_pdf(path: Path, geometry: str) -> None:
    spec = _BOX_GEOMETRIES[geometry]
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % spec["mediabox"])
    if "cropbox" in spec:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % spec["cropbox"])
    if "userunit" in spec:
        doc.xref_set_key(page.xref, "UserUnit", str(spec["userunit"]))
    doc.save(path)
    doc.close()


def _dark_ink_bbox(page: fitz.Page) -> fitz.Rect | None:
    """Bounding box of dark pixels in displayed page space (72 dpi)."""
    pix = page.get_pixmap(colorspace=fitz.csGRAY, alpha=False)
    width, height, samples = pix.width, pix.height, pix.samples
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        row = samples[y * width:(y + 1) * width]
        if min(row) >= 100:
            continue
        dark = [x for x, value in enumerate(row) if value < 100]
        xs.extend((dark[0], dark[-1]))
        ys.append(y)
    if not xs:
        return None
    sx = page.rect.width / width
    sy = page.rect.height / height
    return fitz.Rect(min(xs) * sx, min(ys) * sy, (max(xs) + 1) * sx, (max(ys) + 1) * sy)


@pytest.mark.parametrize("geometry", list(_BOX_GEOMETRIES))
@pytest.mark.parametrize("corner", ["top_left", "bottom_right"])
def test_add_textbox_ink_lands_at_requested_rect_on_offset_or_scaled_page_boxes(
    tmp_path: Path, geometry: str, corner: str
) -> None:
    """F15-G1: add_textbox clamped its insert rect against raw ``page.cropbox``.

    On a CropBox-inside-MediaBox page the top-left box collapsed to 1x1 (no ink),
    a MediaBox at (50,70) shifted the ink 40 pt right, and at ``/UserUnit 2`` the
    bottom-right quarter of the page drew nothing.
    """
    path = tmp_path / f"tb_{geometry}.pdf"
    _make_box_geometry_pdf(path, geometry)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        page_rect = fitz.Rect(model.doc[0].rect)
        if corner == "top_left":
            requested = fitz.Rect(10, 10, 200, 60)
        else:
            requested = fitz.Rect(
                page_rect.width - 170, page_rect.height - 60, page_rect.width - 10, page_rect.height - 10
            )
        model.add_textbox(1, requested, "MMMM", font="helv", size=20, color=(0, 0, 0))
        ink = _dark_ink_bbox(model.doc[0])
        assert ink is not None, f"{geometry}/{corner}: textbox drew no ink (requested {requested})"
        # Ink starts just inside the requested top-left corner and stays inside it.
        assert requested.x0 - 1 <= ink.x0 <= requested.x0 + 8, (geometry, corner, ink, requested)
        assert requested.y0 - 1 <= ink.y0 <= requested.y0 + 15, (geometry, corner, ink, requested)
        assert ink.x1 <= requested.x1 + 1 and ink.y1 <= requested.y1 + 1, (geometry, corner, ink, requested)
    finally:
        model.close()


# F15-G4: PyMuPDF places ``insert_htmlbox`` / Shape drawing through
# ``page.transformation_matrix``, which drops the CropBox/MediaBox origin once
# ``/Rotate != 0``. The rect the model computes is in true unrotated page space,
# so on a rotated offset-box page the ink used to land away from its box and the
# redaction (which is in true space) no longer covered it.
_ROTATED_BOX_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 500, 700)},
    "negmb": {"mediabox": (-100, -200, 500, 600)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
}


def _make_rotated_box_pdf(path: Path, geometry: str, rotation: int) -> None:
    spec = _ROTATED_BOX_GEOMETRIES[geometry]
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % spec["mediabox"])
    if "cropbox" in spec:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % spec["cropbox"])
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    doc.save(path)
    doc.close()


def _visual_words(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    return [(w[4], fitz.Rect(w[:4]) * page.rotation_matrix) for w in page.get_text("words")]


@pytest.mark.parametrize("corner", ["centre", "top_left", "bottom_right"])
@pytest.mark.parametrize("rotation", [90, 180, 270])
@pytest.mark.parametrize("geometry", list(_ROTATED_BOX_GEOMETRIES))
def test_add_textbox_ink_lands_at_requested_rect_on_rotated_offset_page_boxes(
    tmp_path: Path, geometry: str, rotation: int, corner: str
) -> None:
    """F15-G4: on /Rotate 90 with CropBox [30 40 500 700] the ink was 40/30 pt off
    its box, and on a MediaBox at (-100,-200) 200 pt to the right of it. The page
    edges are covered too: the shift is applied after the page clamp."""
    path = tmp_path / f"tbr_{geometry}_{rotation}.pdf"
    _make_rotated_box_pdf(path, geometry, rotation)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        page_rect = fitz.Rect(model.doc[0].rect)
        if corner == "centre":
            requested = fitz.Rect(200, 150, 360, 200)
        elif corner == "top_left":
            requested = fitz.Rect(10, 10, 200, 60)
        else:
            requested = fitz.Rect(
                page_rect.width - 170, page_rect.height - 60, page_rect.width - 10, page_rect.height - 10
            )
        model.add_textbox(1, requested, "MMMM", font="helv", size=20, color=(0, 0, 0))
        ink = _dark_ink_bbox(model.doc[0])
        assert ink is not None, f"{geometry}/{rotation}/{corner}: textbox drew no ink"
        assert requested.x0 - 1 <= ink.x0 <= requested.x0 + 8, (geometry, rotation, corner, ink, requested)
        assert requested.y0 - 1 <= ink.y0 <= requested.y0 + 15, (geometry, rotation, corner, ink, requested)
        assert ink.x1 <= requested.x1 + 1 and ink.y1 <= requested.y1 + 1, (geometry, rotation, corner, ink, requested)
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
@pytest.mark.parametrize("geometry", list(_ROTATED_BOX_GEOMETRIES))
def test_moving_a_textbox_on_a_rotated_offset_page_leaves_no_old_copy(
    tmp_path: Path, geometry: str, rotation: int
) -> None:
    """F15-G4: the redaction erases at the marker rect (true space); text drawn
    elsewhere survived a move, leaving two copies of the word."""
    from model.object_requests import MoveObjectRequest

    path = tmp_path / f"tbm_{geometry}_{rotation}.pdf"
    _make_rotated_box_pdf(path, geometry, rotation)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(1, fitz.Rect(200, 150, 360, 200), "MMMM", font="helv", size=20, color=(0, 0, 0))
        hit = model.get_object_info_at_point(1, fitz.Point(210, 160))
        assert hit is not None
        destination = fitz.Rect(200, 300, 360, 350)
        assert model.move_object(
            MoveObjectRequest(
                object_id=hit.object_id,
                object_kind="textbox",
                source_page=1,
                destination_page=1,
                destination_rect=destination,
            )
        )
        page = model.doc[0]
        words = [(w, r) for w, r in _visual_words(page) if w == "MMMM"]
        assert len(words) == 1, (geometry, rotation, words)
        ink = _dark_ink_bbox(page)
        assert ink is not None
        assert destination.x0 - 1 <= ink.x0 <= destination.x0 + 8, (geometry, rotation, ink)
        assert destination.y0 - 1 <= ink.y0 <= destination.y0 + 15, (geometry, rotation, ink)
    finally:
        model.close()


# F15-G1-UU-ROT: on a ROTATED ``/UserUnit != 1`` page PyMuPDF's htmlbox page matrix
# (``page.transformation_matrix``) drops the ``/UserUnit`` scale, so the ink was drawn
# at ``UserUnit`` times the requested size and offset (a bottom-right box fell off the
# page). The unrotated ``/UserUnit`` page and rotated unit pages were already right.
def _make_rotated_user_unit_pdf(path: Path, rotation: int, user_unit: float) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[0 0 300 400]")
    doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("corner", ["centre", "top_left", "bottom_right"])
@pytest.mark.parametrize("user_unit", [2.0, 0.5])
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_add_textbox_ink_lands_at_requested_rect_on_rotated_user_unit_page(
    tmp_path: Path, rotation: int, user_unit: float, corner: str
) -> None:
    path = tmp_path / f"tbuu_{rotation}_{user_unit}.pdf"
    _make_rotated_user_unit_pdf(path, rotation, user_unit)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        page_rect = fitz.Rect(model.doc[0].rect)
        box_w = min(160.0, page_rect.width - 20)
        if corner == "centre":
            cx, cy = page_rect.width / 2, page_rect.height / 2
            requested = fitz.Rect(cx - box_w / 2, cy - 25, cx + box_w / 2, cy + 25)
        elif corner == "top_left":
            requested = fitz.Rect(10, 10, 10 + box_w, 60)
        else:
            requested = fitz.Rect(
                page_rect.width - 10 - box_w, page_rect.height - 60, page_rect.width - 10, page_rect.height - 10
            )
        model.add_textbox(1, requested, "MMMM", font="helv", size=20, color=(0, 0, 0))
        ink = _dark_ink_bbox(model.doc[0])
        assert ink is not None, f"{rotation}/{user_unit}/{corner}: textbox drew no ink"
        assert requested.x0 - 1 <= ink.x0 <= requested.x0 + 8, (rotation, user_unit, corner, ink, requested)
        assert requested.y0 - 1 <= ink.y0 <= requested.y0 + 15, (rotation, user_unit, corner, ink, requested)
        assert ink.x1 <= requested.x1 + 1 and ink.y1 <= requested.y1 + 1, (rotation, user_unit, corner, ink, requested)
        # The glyphs keep their requested size: 4 x "M" at 20 pt Helvetica is ~68 pt wide.
        assert 55 <= ink.width <= 80, (rotation, user_unit, corner, ink)
    finally:
        model.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_moving_a_textbox_on_a_rotated_user_unit_page_leaves_no_old_copy(
    tmp_path: Path, rotation: int
) -> None:
    from model.object_requests import MoveObjectRequest

    path = tmp_path / f"tbuum_{rotation}.pdf"
    _make_rotated_user_unit_pdf(path, rotation, 2.0)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(1, fitz.Rect(200, 150, 360, 200), "MMMM", font="helv", size=20, color=(0, 0, 0))
        hit = model.get_object_info_at_point(1, fitz.Point(210, 160))
        assert hit is not None
        destination = fitz.Rect(200, 300, 360, 350)
        assert model.move_object(
            MoveObjectRequest(
                object_id=hit.object_id,
                object_kind="textbox",
                source_page=1,
                destination_page=1,
                destination_rect=destination,
            )
        )
        page = model.doc[0]
        assert len([1 for w in page.get_text("words") if w[4] == "MMMM"]) == 1
        ink = _dark_ink_bbox(page)
        assert ink is not None
        assert destination.x0 - 1 <= ink.x0 <= destination.x0 + 8, (rotation, ink)
        assert destination.y0 - 1 <= ink.y0 <= destination.y0 + 15, (rotation, ink)
        assert 55 <= ink.width <= 80, (rotation, ink)
    finally:
        model.close()


def test_add_textbox_default_font_supports_cjk() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cjk.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            token = "中文測試ABC"
            model.add_textbox(
                page_num=1,
                visual_rect=fitz.Rect(30, 60, 210, 120),
                text=token,
                font="",  # force default path
                size=16,
                color=(0, 0, 0),
            )
            page_text = model.doc[0].get_text("text")
            assert _norm(token) in _norm(page_text), page_text
        finally:
            model.close()


def test_add_textbox_atomic_undo_redo_boundaries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "atomic.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))

            before_a = model._capture_page_snapshot_strict(0)
            cmd_a = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(20, 40, 180, 90),
                text="TOKEN_A",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before_a,
            )
            model.command_manager.execute(cmd_a)

            before_b = model._capture_page_snapshot_strict(0)
            cmd_b = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(20, 110, 180, 160),
                text="TOKEN_B",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before_b,
            )
            model.command_manager.execute(cmd_b)

            t0 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t0 and "token_b" in t0

            model.command_manager.undo()
            t1 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t1 and "token_b" not in t1

            model.command_manager.undo()
            t2 = _norm(model.doc[0].get_text("text"))
            assert "token_a" not in t2 and "token_b" not in t2

            model.command_manager.redo()
            t3 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t3 and "token_b" not in t3

            model.command_manager.redo()
            t4 = _norm(model.doc[0].get_text("text"))
            assert "token_a" in t4 and "token_b" in t4
        finally:
            model.close()


def test_add_textbox_undo_keeps_other_page_objects() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nondestructive.pdf"
        _make_pdf(path, rotation=0, with_seed=True)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            before_text = _norm(page.get_text("text"))
            before_image_count = len(page.get_images(full=True))
            before_annots = len(list(page.annots() or []))

            before = model._capture_page_snapshot_strict(0)
            cmd = AddTextboxCommand(
                model=model,
                page_num=1,
                visual_rect=fitz.Rect(30, 160, 200, 210),
                text="NEW_INSERT",
                font="cjk",
                size=14,
                color=(0, 0, 0),
                before_page_snapshot_bytes=before,
            )
            model.command_manager.execute(cmd)
            model.command_manager.undo()

            page_after = model.doc[0]
            after_text = _norm(page_after.get_text("text"))
            after_image_count = len(page_after.get_images(full=True))
            after_annots = len(list(page_after.annots() or []))

            assert "keep_original" in after_text
            assert before_text == after_text
            assert before_image_count == after_image_count
            assert before_annots == after_annots
        finally:
            model.close()


def test_add_textbox_immediately_editable_by_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "editable_immediately.pdf"
        _make_pdf(path, rotation=0, with_seed=False)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            token = "NOW_EDITABLE"
            visual_rect = fitz.Rect(40, 72, 240, 132)
            model.add_textbox(
                page_num=1,
                visual_rect=visual_rect,
                text=token,
                font="cjk",
                size=16,
                color=(0, 0, 0),
            )

            # Click near the first line start in visual coordinates.
            hit = model.get_text_info_at_point(1, fitz.Point(visual_rect.x0 + 4, visual_rect.y0 + 18))
            assert hit is not None, "inserted text not hit-detectable immediately"
            assert "now_editable" in _norm(hit.target_text), hit.target_text
        finally:
            model.close()


# ---- F16-PASTE-1: pasted control characters ----------------------------------------
# insert_htmlbox stops at an embedded NUL (everything after it is silently lost) and
# draws every other C0/C1 control except tab/newline (VT, 0x01..0x1F, DEL, 0x80..0x9F)
# as a replacement glyph. The textbox chokepoint strips them before drawing and storing.

_CONTROL_PASTES = [
    pytest.param("Ab\x00\x01Cd", id="nul_soh"),
    pytest.param("Ab\x0b\x0cCd", id="vt_ff"),
    pytest.param("Ab\x7f\x85\x9fCd", id="del_c1"),
    pytest.param("Ab\ufffe\uffffCd", id="noncharacters"),
]


def _stored_marker_text(model: PDFModel) -> str:
    import json

    annot = next(iter(model.doc[0].annots()))
    return json.loads(annot.info["content"])["text"]


@pytest.mark.parametrize("pasted", _CONTROL_PASTES)
def test_add_textbox_strips_pasted_control_characters(pasted: str, tmp_path: Path) -> None:
    path = tmp_path / "ctrl.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(1, fitz.Rect(40, 60, 240, 120), pasted, font="helv", size=14, color=(0, 0, 0))
        # no replacement glyph of any kind: only the two words (and layout whitespace)
        assert "".join(model.doc[0].get_text().split()) == "AbCd", repr(model.doc[0].get_text())
        # the marker stores what was drawn, so move / rotate re-insert the same text
        assert _stored_marker_text(model) == "AbCd"
    finally:
        model.close()


def test_add_textbox_drops_a_pasted_image_anchor_instead_of_drawing_an_obj_box(
    tmp_path: Path,
) -> None:
    """F16-PASTE-2: U+FFFC (an image inside pasted HTML) was committed and drawn as a
    dashed "OBJ" box with no prompt; the text layer kept the character."""
    path = tmp_path / "fffc.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(1, fitz.Rect(40, 60, 240, 120), "Logo \ufffc X", font="helv", size=14, color=(0, 0, 0))
        assert "\ufffc" not in model.doc[0].get_text(), repr(model.doc[0].get_text())
        assert "".join(model.doc[0].get_text().split()).endswith("LogoX")
        assert _stored_marker_text(model) == "Logo  X"
        out = tmp_path / "fffc_saved.pdf"
        model.save_as(str(out))
        with fitz.open(str(out)) as reopened:
            assert "\ufffc" not in reopened[0].get_text()
    finally:
        model.close()


def test_add_textbox_of_only_an_image_anchor_is_refused_with_zero_mutation(tmp_path: Path) -> None:
    path = tmp_path / "fffc_only.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        before = model.doc[0].get_text()
        with pytest.raises(ValueError):
            model.add_textbox(1, fitz.Rect(40, 60, 240, 120), "\ufffc", font="helv", size=14, color=(0, 0, 0))
        assert model.doc[0].get_text() == before
        assert not list(model.doc[0].annots() or [])
    finally:
        model.close()


def test_add_textbox_control_chars_keep_newline_and_tab(tmp_path: Path) -> None:
    path = tmp_path / "ctrl_nl.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(
            1, fitz.Rect(40, 60, 240, 140), "One\x00\r\nTwo\x0bThree\tFour", font="helv", size=14, color=(0, 0, 0)
        )
        lines = [ln for ln in model.doc[0].get_text().splitlines() if ln.strip()]
        assert lines[0] == "One" and lines[1].replace(" ", "").startswith("TwoThree"), lines
        assert _stored_marker_text(model) == "One\nTwoThree\tFour"
    finally:
        model.close()


@pytest.mark.parametrize("pasted", ["\x00\x01\x02", "\x00 \x0b", "\x7f"])
def test_add_textbox_of_only_control_characters_is_refused_with_zero_mutation(
    pasted: str, tmp_path: Path
) -> None:
    path = tmp_path / "ctrl_only.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        before = model.doc[0].get_text()
        edits = model.edit_count
        with pytest.raises(ValueError):
            model.add_textbox(1, fitz.Rect(40, 60, 240, 120), pasted, font="helv", size=14, color=(0, 0, 0))
        assert model.doc[0].get_text() == before
        assert model.edit_count == edits
        assert not list(model.doc[0].annots() or [])
    finally:
        model.close()


def test_textbox_markup_strips_controls_so_the_layer_reference_matches_the_insert() -> None:
    from model.pdf_object_ops import _textbox_markup

    html, _css = _textbox_markup("Ab\x00\x0bCd\nEf", "helv", 12.0, (0.0, 0.0, 0.0))
    assert "\x00" not in html and "\x0b" not in html
    assert "AbCd<br>Ef" in html


def test_move_of_a_legacy_marker_with_control_characters_redraws_clean(tmp_path: Path) -> None:
    """A file saved by an older build can hold control characters in the marker."""
    import json

    from model.object_requests import MoveObjectRequest

    path = tmp_path / "legacy.pdf"
    _make_pdf(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.add_textbox(1, fitz.Rect(40, 60, 240, 120), "AbCd", font="helv", size=14, color=(0, 0, 0))
        page = model.doc[0]
        annot = next(iter(page.annots()))
        payload = json.loads(annot.info["content"])
        payload["text"] = "Ab\x0bCd"
        annot.set_info(content=json.dumps(payload, ensure_ascii=False))
        annot.update()
        hit = model.get_object_info_at_point(1, fitz.Point(60, 75))
        assert hit is not None
        moved = model.move_object(
            MoveObjectRequest(
                object_id=hit.object_id,
                object_kind="textbox",
                source_page=1,
                destination_page=1,
                destination_rect=fitz.Rect(40, 140, 240, 200),
            )
        )
        assert moved
        assert "".join(model.doc[0].get_text().split()) == "AbCd", repr(model.doc[0].get_text())
        assert _stored_marker_text(model) == "AbCd"
    finally:
        model.close()
