from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from model.geometry import unrotated_to_visual_rect
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest
from model.pdf_content_ops import discover_native_image_invocations
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    for y in range(8):
        for x in range(8):
            pix.set_pixel(x, y, rgb)
    return pix.tobytes("png")


def _make_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((255, 0, 0)))
    page.insert_image(fitz.Rect(70, 45, 170, 135), stream=_png_bytes((0, 255, 0)))
    doc.save(path)
    doc.close()


def _make_shared_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((10, 20, 30)))
    image_name = str(page.get_images(full=True)[0][7])
    stream_xref = int(page.get_contents()[0])
    original_stream = doc.xref_stream(stream_xref)
    duplicate_stream = original_stream + f"q\n100 0 0 70 150 140 cm\n/{image_name} Do\nQ\n".encode("ascii")
    doc.update_stream(stream_xref, duplicate_stream)
    doc.save(path)
    doc.close()


def _make_outer_q_nested_sibling_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((120, 30, 30)))
    page.insert_image(fitz.Rect(160, 30, 260, 100), stream=_png_bytes((30, 120, 30)))
    image_names = [str(image[7]) for image in page.get_images(full=True)]
    stream_xrefs = [int(xref) for xref in page.get_contents()]
    stream_xref = stream_xrefs[0]
    nested_name, target_name = image_names
    custom_stream = (
        b"q\n"
        b"q\n"
        + f"100 0 0 70 20 150 cm\n/{nested_name} Do\nQ\n".encode("ascii")
        + f"100 0 0 70 160 140 cm\n/{target_name} Do\n".encode("ascii")
        + b"Q\n"
    )
    doc.update_stream(stream_xref, custom_stream)
    for extra_stream_xref in stream_xrefs[1:]:
        doc.update_stream(extra_stream_xref, b"")
    doc.save(path)
    doc.close()


def _make_cropped_native_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(50, 60, 150, 140), stream=_png_bytes((200, 0, 0)))
    # Crop from the bottom: keep the top of the page unchanged.
    page.set_cropbox(fitz.Rect(0, 100, 400, 400))
    doc.save(path)
    doc.close()


def _make_native_image_no_cm_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((0, 0, 200)))
    image_name = str(page.get_images(full=True)[0][7])
    stream_xref = int(page.get_contents()[0])
    doc.update_stream(stream_xref, f"q\n/{image_name} Do\nQ\n".encode("ascii"))
    doc.save(path)
    doc.close()


def _hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def _image_names(page: fitz.Page) -> list[str]:
    return [str(image[7]) for image in page.get_images(full=True)]


def test_native_image_hit_detection_returns_native_kind() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert hit.object_id == "native_image:1:0"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True
            assert hit.rotation == 0
        finally:
            model.close()


def test_native_image_hit_prefers_topmost_invocation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_topmost.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(90, 60))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert hit.object_id == "native_image:1:1"
            assert fitz.Rect(hit.bbox) == fitz.Rect(70, 45, 170, 135)
        finally:
            model.close()


def test_move_native_image_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_move.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(180, 140, 280, 210),
                )
            )

            assert ok is True
            assert _hit(model, fitz.Point(30, 30)) is None
            moved = _hit(model, fitz.Point(200, 160))
            assert moved is not None
            assert moved.object_id == hit.object_id
            assert fitz.Rect(moved.bbox) == fitz.Rect(180, 140, 280, 210)
        finally:
            model.close()


def test_resize_native_image_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_resize.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.resize_object(
                ResizeObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    destination_rect=fitz.Rect(20, 20, 200, 140),
                )
            )

            assert ok is True
            resized = _hit(model, fitz.Point(180, 120))
            assert resized is not None
            assert resized.object_id == hit.object_id
            assert fitz.Rect(resized.bbox) == fitz.Rect(20, 20, 200, 140)
        finally:
            model.close()


def test_rotate_native_image_preserves_bbox_and_updates_rotation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_rotate.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None
            before_bbox = fitz.Rect(hit.bbox)

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )

            assert ok is True
            rotated = _hit(model, fitz.Point(30, 30))
            assert rotated is not None
            assert rotated.object_id == hit.object_id
            assert rotated.rotation == 90
            assert fitz.Rect(rotated.bbox) == before_bbox
        finally:
            model.close()


def test_delete_native_image_removes_one_invocation_but_keeps_shared_resource() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_delete_shared.pdf"
        _make_shared_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            names_before = _image_names(page)
            assert len(names_before) == 1

            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

            assert ok is True
            assert _hit(model, fitz.Point(30, 30)) is None
            survivor = _hit(model, fitz.Point(180, 60))
            assert survivor is not None
            assert survivor.object_kind == "native_image"
            # delete now forces a garbage=4 round-trip (R6-01 confidentiality), which
            # replaces model.doc — re-fetch the page instead of the pre-delete handle.
            assert _image_names(model.doc[0]) == names_before
        finally:
            model.close()


def test_delete_native_image_prunes_unused_resource_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_delete_unique.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            names_before = _image_names(page)
            assert len(names_before) == 2

            hit = _hit(model, fitz.Point(30, 30))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

            assert ok is True
            # delete now forces a garbage=4 round-trip (R6-01 confidentiality), which
            # replaces model.doc — re-fetch the page instead of the pre-delete handle.
            names_after = _image_names(model.doc[0])
            assert len(names_after) == 1
            assert names_after != names_before
            assert _hit(model, fitz.Point(30, 30)) is None
        finally:
            model.close()


def test_delete_native_image_does_not_delete_nested_sibling_in_outer_q() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_nested_q.pdf"
        _make_outer_q_nested_sibling_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            before = discover_native_image_invocations(model.doc, 1)
            assert len(before) == 2

            target = _hit(model, fitz.Point(180, 60))
            assert target is not None
            assert target.object_kind == "native_image"

            ok = model.delete_object(DeleteObjectRequest(target.object_id, target.object_kind, 1))

            assert ok is True
            after = discover_native_image_invocations(model.doc, 1)
            assert len(after) == 1
            survivor = _hit(model, fitz.Point(40, 40))
            assert survivor is not None
            assert survivor.object_kind == "native_image"
            assert fitz.Rect(survivor.bbox) == fitz.Rect(20, 20, 120, 90)
        finally:
            model.close()


def _make_image_sharing_its_scope_with_text_pdf(path: Path, wrap_in_q: bool) -> None:
    """One image invocation whose ``q`` block (or the top level) also draws page text.

    ``wrap_in_q``: ``q <text> cm Do Q``, the block's only ``Do`` is the image.
    Otherwise ``cm Do <text>`` at the top level: the text is drawn under that ``cm``.
    """
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png_bytes((0, 0, 200)))
    page.insert_text(fitz.Point(40, 200), "x", fontsize=12, fontname="helv")  # registers /helv
    image_name = str(page.get_images(full=True)[0][7])
    stream_xrefs = [int(xref) for xref in page.get_contents()]
    if wrap_in_q:
        content = f"q BT /helv 12 Tf 40 30 Td (KEEP) Tj ET 100 0 0 70 20 150 cm /{image_name} Do Q"
    else:
        # Under the image cm (100 x 70 scale) the text is placed in unit-square space.
        content = f"100 0 0 70 20 150 cm /{image_name} Do BT /helv 0.2 Tf 0.3 -1.5 Td (KEEP) Tj ET"
    doc.update_stream(stream_xrefs[0], content.encode("ascii"))
    for extra in stream_xrefs[1:]:
        doc.update_stream(extra, b" ")
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("wrap_in_q", [True, False], ids=["same_q_block", "top_level_cm"])
def test_delete_native_image_keeps_page_text_drawn_in_the_same_scope(wrap_in_q: bool) -> None:
    """F13-VF-2b class: deleting an image removed its whole ``q`` block whenever the
    block held one ``Do``, erasing the text drawn in it, and without a sole-image block
    removed the image ``cm`` too, moving everything drawn after it in that scope."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"native_shared_scope_{wrap_in_q}.pdf"
        _make_image_sharing_its_scope_with_text_pdf(path, wrap_in_q)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            words_before = [(w[4], tuple(round(v, 1) for v in w[:4])) for w in model.doc[0].get_text("words")]
            assert [name for name, _ in words_before] == ["KEEP"]
            hit = _hit(model, fitz.Point(70, 55))
            assert hit is not None and hit.object_kind == "native_image"

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))

            assert ok is True
            assert discover_native_image_invocations(model.doc, 1) == []
            words_after = [(w[4], tuple(round(v, 1) for v in w[:4])) for w in model.doc[0].get_text("words")]
            assert words_after == words_before
        finally:
            model.close()


def test_native_discovery_does_not_depend_on_get_image_info_order(monkeypatch) -> None:
    original = fitz.Page.get_image_info

    def _reversed_info(page: fitz.Page, *args, **kwargs):
        items = list(reversed(original(page, *args, **kwargs)))
        rewritten = []
        for idx, item in enumerate(items):
            rewritten_item = dict(item)
            rewritten_item["number"] = idx
            rewritten.append(rewritten_item)
        return rewritten

    monkeypatch.setattr(fitz.Page, "get_image_info", _reversed_info)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_reversed_info.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            first = _hit(model, fitz.Point(30, 30))
            topmost = _hit(model, fitz.Point(90, 60))

            assert first is not None
            assert fitz.Rect(first.bbox) == fitz.Rect(20, 20, 120, 90)
            assert topmost is not None
            assert fitz.Rect(topmost.bbox) == fitz.Rect(70, 45, 170, 135)
        finally:
            model.close()


def test_native_discovery_survives_missing_get_image_info(monkeypatch) -> None:
    monkeypatch.setattr(fitz.Page, "get_image_info", lambda self, *args, **kwargs: [])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_missing_info.pdf"
        _make_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = _hit(model, fitz.Point(30, 30))

            assert hit is not None
            assert hit.object_kind == "native_image"
            assert fitz.Rect(hit.bbox) == fitz.Rect(20, 20, 120, 90)
        finally:
            model.close()


def test_native_bbox_matches_get_image_info_on_cropped_page() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_cropbox.pdf"
        _make_cropped_native_image_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            expected = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])

            invocations = discover_native_image_invocations(model.doc, 1)
            assert len(invocations) == 1
            assert fitz.Rect(invocations[0].bbox) == expected
        finally:
            model.close()


def test_native_discovery_survives_no_cm_invocation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_no_cm.pdf"
        _make_native_image_no_cm_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            expected_bbox = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])

            hit = _hit(model, expected_bbox.tl + (expected_bbox.br - expected_bbox.tl) * 0.5)
            assert hit is not None
            assert hit.object_kind == "native_image"
            assert fitz.Rect(hit.bbox) == expected_bbox
        finally:
            model.close()


def test_native_no_cm_invocation_rejects_move_and_rotate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "native_no_cm_actions.pdf"
        _make_native_image_no_cm_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page = model.doc[0]
            bbox = fitz.Rect(page.get_image_info(xrefs=True)[0]["bbox"])
            center = fitz.Point((bbox.x0 + bbox.x1) * 0.5, (bbox.y0 + bbox.y1) * 0.5)
            hit = _hit(model, center)
            assert hit is not None
            assert hit.object_kind == "native_image"

            move_ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(40, 30, 140, 100),
                )
            )
            rotate_ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=90,
                )
            )

            assert move_ok is False
            assert rotate_ok is False
        finally:
            model.close()


# --- F15-G2: offset MediaBox / CropBox and /UserUnit pages ------------------
#
# Image discovery used to flip y against the MediaBox HEIGHT (not its y1) and
# ignored /UserUnit, so on these pages the discovered bbox, the hit test and
# the cm written back by a move were all offset from where MuPDF draws the
# image. The oracle is MuPDF's own ``page.get_image_rects``, never a literal.

_BOX_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "negmb": {"mediabox": (-100, -200, 500, 600)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
    "negcrop": {"mediabox": (-100, -200, 500, 600), "cropbox": (-50, -150, 400, 500)},
    "crop_past_mb": {"mediabox": (0, 0, 600, 800), "cropbox": (-50, -50, 500, 700)},
    "uu2": {"mediabox": (0, 0, 300, 400), "user_unit": 2},
    "negmb_r90": {"mediabox": (-100, -200, 500, 600), "rotate": 90},
    "negcrop_r270": {"mediabox": (-100, -200, 500, 600), "cropbox": (-50, -150, 400, 500), "rotate": 270},
    "uu2_r180": {"mediabox": (0, 0, 300, 400), "user_unit": 2, "rotate": 180},
}


def _make_box_geometry_image_pdf(
    path: Path,
    *,
    mediabox: tuple[float, float, float, float],
    cropbox: tuple[float, float, float, float] | None = None,
    user_unit: float | None = None,
    rotate: int = 0,
    rgb: tuple[int, int, int] = (40, 90, 160),
    offset: tuple[float, float] = (60, 80),
) -> None:
    """One 100x50 image drawn by a raw user-space ``cm`` on a page with the given boxes.

    ``offset`` places it from the clip box's lower-left corner (user units).
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(0, 0, 10, 10), stream=_png_bytes(rgb))
    image_name = str(page.get_images(full=True)[0][7])
    clip_x0 = max(mediabox[0], cropbox[0]) if cropbox else mediabox[0]
    clip_y0 = max(mediabox[1], cropbox[1]) if cropbox else mediabox[1]
    stream = (
        f"q\n100 0 0 50 {clip_x0 + offset[0]:g} {clip_y0 + offset[1]:g} cm\n/{image_name} Do\nQ\n"
    ).encode("ascii")
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<< >>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox is not None:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    if user_unit is not None:
        doc.xref_set_key(page.xref, "UserUnit", f"{user_unit:g}")
    if rotate:
        doc.xref_set_key(page.xref, "Rotate", str(rotate))
    doc.save(path)
    doc.close()


def _drawn_image_rects(model: PDFModel, page_num: int = 1) -> list[fitz.Rect]:
    page = model.doc[page_num - 1]
    return [
        fitz.Rect(rect)
        for image in page.get_images(full=True)
        for rect in page.get_image_rects(int(image[0]))
    ]


def _assert_rect_close(actual: fitz.Rect, expected: fitz.Rect, tol: float = 0.05) -> None:
    got = (actual.x0, actual.y0, actual.x1, actual.y1)
    want = (expected.x0, expected.y0, expected.x1, expected.y1)
    assert all(abs(a - b) <= tol for a, b in zip(got, want)), (got, want)


def _centre(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _drawn_visual_rects(model: PDFModel, page_num: int = 1) -> list[fitz.Rect]:
    """MuPDF's placements in VISUAL space: what the user sees and clicks (F14-MM-1b).

    ``get_image_rects`` and discovery are UNROTATED page space; the hit point,
    ``ObjectHitInfo.bbox`` and a move's destination are visual. At /Rotate 0 the two agree.
    """
    page = model.doc[page_num - 1]
    return [unrotated_to_visual_rect(page, rect) for rect in _drawn_image_rects(model, page_num)]


@pytest.mark.parametrize("geometry", sorted(_BOX_GEOMETRIES))
def test_native_image_discovery_and_hit_match_mupdf_on_offset_box_pages(geometry: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"box_{geometry}.pdf"
        _make_box_geometry_image_pdf(path, **_BOX_GEOMETRIES[geometry])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            (drawn,) = _drawn_image_rects(model)
            (invocation,) = discover_native_image_invocations(model.doc, 1)
            _assert_rect_close(fitz.Rect(invocation.bbox), drawn)

            (visual,) = _drawn_visual_rects(model)
            centre = _centre(visual)
            hit = model.get_object_info_at_point(1, centre)
            assert hit is not None and hit.object_kind == "native_image"
            _assert_rect_close(fitz.Rect(hit.bbox), visual)
            # No phantom: the empty area 200 pt below the image selects nothing.
            assert model.get_object_info_at_point(1, centre + fitz.Point(0, 200)) is None
        finally:
            model.close()


@pytest.mark.parametrize("geometry", sorted(_BOX_GEOMETRIES))
def test_native_image_move_and_resize_land_where_requested_on_offset_box_pages(geometry: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"box_move_{geometry}.pdf"
        _make_box_geometry_image_pdf(path, **_BOX_GEOMETRIES[geometry])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            (drawn,) = _drawn_visual_rects(model)
            hit = model.get_object_info_at_point(1, _centre(drawn))
            assert hit is not None and hit.object_kind == "native_image"

            moved_to = fitz.Rect(drawn.x0 + 20, drawn.y0 + 30, drawn.x1 + 20, drawn.y1 + 30)
            assert model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=moved_to,
                )
            ) is True
            (after_move,) = _drawn_visual_rects(model)
            _assert_rect_close(after_move, moved_to)

            resized_to = fitz.Rect(moved_to.x0, moved_to.y0, moved_to.x1 + 40, moved_to.y1 + 10)
            assert model.resize_object(
                ResizeObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    destination_rect=resized_to,
                )
            ) is True
            (after_resize,) = _drawn_visual_rects(model)
            _assert_rect_close(after_resize, resized_to)
            (invocation,) = discover_native_image_invocations(model.doc, 1)
            _assert_rect_close(
                unrotated_to_visual_rect(model.doc[0], fitz.Rect(invocation.bbox)), resized_to
            )
        finally:
            model.close()


def test_native_image_on_unprovable_page_frame_reports_mupdf_rect_and_refuses_cm_writes() -> None:
    """A /Rotate 45 page has no provable page frame (MuPDF renders it at the
    nearest quarter turn while ``page.rotation`` says 0). Discovery reports
    MuPDF's own placement and a move refuses instead of writing a guessed cm."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "box_rotate45.pdf"
        _make_box_geometry_image_pdf(path, mediabox=(-100, -200, 500, 600), rotate=45)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            (drawn,) = _drawn_image_rects(model)
            (invocation,) = discover_native_image_invocations(model.doc, 1)
            _assert_rect_close(fitz.Rect(invocation.bbox), drawn)
            stream_before = model.doc.xref_stream(invocation.stream_xref)

            hit = model.get_object_info_at_point(1, _centre(drawn))
            assert hit is not None and hit.object_kind == "native_image"
            moved_to = fitz.Rect(drawn.x0 + 20, drawn.y0 + 30, drawn.x1 + 20, drawn.y1 + 30)
            assert model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=moved_to,
                )
            ) is False
            assert model.doc.xref_stream(invocation.stream_xref) == stream_before
            (still_drawn,) = _drawn_image_rects(model)
            _assert_rect_close(still_drawn, drawn)
        finally:
            model.close()


# --- F14-MM-1b: native images on /Rotate pages are hit and moved where they are DRAWN ---
#
# Discovery reports UNROTATED page space; the hit test compared the VISUAL click point
# with it, so on a /Rotate 90 page a native image was selectable only at its unrotated
# numbers (where nothing is drawn), reported an unrotated bbox, and a move to a visual
# destination landed elsewhere. The oracle is the rendered ink (pixmap pixels at the
# identity matrix are visual coordinates).

_INK_HIGH = bytes(1 if v >= 200 else 0 for v in range(256))
_INK_LOW = bytes(1 if v <= 80 else 0 for v in range(256))

_ROTATED_NATIVE_BOXES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 565, 760)},
    "negmb": {"mediabox": (-100, -80, 500, 720)},
}


def _red_ink(page: fitz.Page) -> fitz.Rect | None:
    """Visual bbox of the rendered pure-red pixels."""
    pix = page.get_pixmap(matrix=fitz.Identity, alpha=False)
    samples, n, stride, width = pix.samples, pix.n, pix.stride, pix.width
    x0 = y0 = None
    x1 = y1 = -1
    for y in range(pix.height):
        row = samples[y * stride : y * stride + width * n]
        mask = (
            int.from_bytes(row[0::n].translate(_INK_HIGH), "big")
            & int.from_bytes(row[1::n].translate(_INK_LOW), "big")
            & int.from_bytes(row[2::n].translate(_INK_LOW), "big")
        )
        if not mask:
            continue
        hits = mask.to_bytes(width, "big")
        first, last = hits.find(1), hits.rfind(1)
        x0 = first if x0 is None else min(x0, first)
        x1 = max(x1, last + 1)
        y0 = y if y0 is None else y0
        y1 = y + 1
    if x0 is None or y0 is None:
        return None
    return fitz.Rect(x0, y0, x1, y1)


def _make_rotated_red_native_pdf(path: Path, rotate: int, box: str) -> None:
    """A red 100x50 (user units) native image drawn by a raw ``cm`` on a /Rotate page."""
    _make_box_geometry_image_pdf(
        path, rotate=rotate, rgb=(255, 0, 0), offset=(160, 280), **_ROTATED_NATIVE_BOXES[box]
    )


@pytest.mark.parametrize("box", sorted(_ROTATED_NATIVE_BOXES))
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_native_image_on_rotated_page_is_hit_moved_resized_and_deleted_where_drawn(
    rotate: int, box: str
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"native_rot_{rotate}_{box}.pdf"
        _make_rotated_red_native_pdf(path, rotate, box)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            drawn = _red_ink(model.doc[0])
            assert drawn is not None
            hit = model.get_object_info_at_point(1, _centre(drawn))
            assert hit is not None and hit.object_kind == "native_image"
            _assert_rect_close(fitz.Rect(hit.bbox), drawn, tol=1.5)
            # Selectable only where it is drawn: 150 pt to the right is empty page.
            assert model.get_object_info_at_point(1, _centre(drawn) + (150, 0)) is None

            moved_to = fitz.Rect(drawn) + (60, 40, 60, 40)
            assert model.move_object(
                MoveObjectRequest(hit.object_id, hit.object_kind, 1, 1, moved_to)
            ) is True
            _assert_rect_close(_red_ink(model.doc[0]), moved_to, tol=1.5)
            moved = model.get_object_info_at_point(1, _centre(moved_to))
            assert moved is not None and moved.object_kind == "native_image"
            _assert_rect_close(fitz.Rect(moved.bbox), moved_to, tol=1.5)

            resized_to = fitz.Rect(moved_to.x0, moved_to.y0, moved_to.x1 + 30, moved_to.y1 + 20)
            assert model.resize_object(
                ResizeObjectRequest(moved.object_id, moved.object_kind, 1, resized_to)
            ) is True
            _assert_rect_close(_red_ink(model.doc[0]), resized_to, tol=1.5)

            resized = model.get_object_info_at_point(1, _centre(resized_to))
            assert resized is not None
            assert model.delete_object(
                DeleteObjectRequest(resized.object_id, resized.object_kind, 1)
            ) is True
            assert _red_ink(model.doc[0]) is None
        finally:
            model.close()
