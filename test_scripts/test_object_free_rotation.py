"""AC-4 (model) — free arbitrary-angle rotation of images, preserved on move.

The legacy rotate path only handled 90° steps ("fit to rect"). Free rotation
adds a rotate-about-center path driven by an explicit absolute angle, and a move
of an already-rotated image must keep its angle (the review reported rotated
images snapping back upright on move). The 90° toolbar path is unchanged and is
covered by test_native_pdf_images_model.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from model.object_requests import MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    for y in range(8):
        for x in range(8):
            pix.set_pixel(x, y, rgb)
    return pix.tobytes("png")


def _make_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(120, 120, 220, 200), stream=_png_bytes())  # 100×80
    doc.save(path)
    doc.close()


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def test_free_rotate_native_image_to_30_degrees() -> None:
    """AC-4a: an absolute-angle rotate yields ~30° read-back, center preserved."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot.pdf"
        _make_image_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert hit is not None and hit.object_kind == "native_image"
            before_center = _center(fitz.Rect(hit.bbox))

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=30.0,
                )
            )
            assert ok is True

            rotated = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert rotated is not None
            assert abs((float(rotated.rotation) % 360) - 30.0) <= 1.0
            after_center = _center(fitz.Rect(rotated.bbox))
            assert abs(after_center.x - before_center.x) <= 1.5
            assert abs(after_center.y - before_center.y) <= 1.5
        finally:
            model.close()


def test_moving_a_freely_rotated_image_preserves_its_angle() -> None:
    """AC-4d: a rotated image keeps its angle after a move (no snap-to-upright)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotmove.pdf"
        _make_image_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert hit is not None

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=40.0,
                )
            )

            rotated = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert rotated is not None
            angle_before_move = float(rotated.rotation) % 360
            assert abs(angle_before_move - 40.0) <= 1.0

            # Translate the rotated image by (+80, +60): the new AABB is the old
            # one shifted by the same delta.
            old_bbox = fitz.Rect(rotated.bbox)
            dest = fitz.Rect(
                old_bbox.x0 + 80, old_bbox.y0 + 60, old_bbox.x1 + 80, old_bbox.y1 + 60
            )
            assert model.move_object(
                MoveObjectRequest(
                    object_id=rotated.object_id,
                    object_kind=rotated.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=dest,
                )
            )

            moved = model.get_object_info_at_point(1, _center(dest))
            assert moved is not None
            assert abs((float(moved.rotation) % 360) - angle_before_move) <= 1.0
        finally:
            model.close()


def test_resizing_a_rotated_image_does_not_inflate_geometry() -> None:
    """A resize of a rotated image must produce ~the requested AABB, not an
    AABB inflated by |cos|+|sin| (regression for the AABB→size inversion)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rotresize.pdf"
        _make_image_pdf(path)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            hit = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert hit is not None
            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=30.0,
                )
            )

            from model.object_requests import ResizeObjectRequest

            rotated = model.get_object_info_at_point(1, fitz.Point(170, 160))
            assert rotated is not None
            dest = fitz.Rect(100, 100, 280, 240)  # requested AABB, centre (190,170)
            assert model.resize_object(
                ResizeObjectRequest(
                    object_id=rotated.object_id,
                    object_kind=rotated.object_kind,
                    page_num=1,
                    destination_rect=dest,
                )
            )

            after = model.get_object_info_at_point(1, _center(dest))
            assert after is not None
            new_bbox = fitz.Rect(after.bbox)
            # The rendered AABB should match the requested AABB within a couple pt,
            # not be inflated ~1.37× (|cos30|+|sin30|).
            assert abs(new_bbox.width - dest.width) <= 3.0
            assert abs(new_bbox.height - dest.height) <= 3.0
        finally:
            model.close()


# --- F15-G2 / F15-G3: free rotation on offset-box and /UserUnit pages --------
#
# The free-rotation cm builder flipped y against the MediaBox height and took
# the destination centre as raw user space (no CropBox/MediaBox origin, no
# /UserUnit), so a rotated image moved or resized on such a page landed offset
# (crop: (-30, -100); posmb: (-50, +70)). The oracle is MuPDF's own
# ``page.get_image_rects`` (the drawn AABB), never a literal.

_FREE_ROTATION_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 500, 700)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
    "negmb": {"mediabox": (-100, -200, 500, 600)},
    "negcrop": {"mediabox": (-100, -200, 500, 600), "cropbox": (-50, -100, 400, 550)},
    "uu2": {"mediabox": (0, 0, 300, 400), "user_unit": 2},
}


def _make_box_geometry_image_pdf(
    path: Path,
    *,
    mediabox: tuple[float, float, float, float],
    cropbox: tuple[float, float, float, float] | None = None,
    user_unit: float | None = None,
) -> None:
    """A 100x80 image drawn by a raw user-space ``cm`` on a page with these boxes."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(0, 0, 10, 10), stream=_png_bytes())
    image_name = str(page.get_images(full=True)[0][7])
    clip_x0 = max(mediabox[0], cropbox[0]) if cropbox else mediabox[0]
    clip_y0 = max(mediabox[1], cropbox[1]) if cropbox else mediabox[1]
    stream = f"q\n100 0 0 80 {clip_x0 + 120:g} {clip_y0 + 120:g} cm\n/{image_name} Do\nQ\n".encode("ascii")
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<< >>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox is not None:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    if user_unit is not None:
        doc.xref_set_key(page.xref, "UserUnit", f"{user_unit:g}")
    doc.save(path)
    doc.close()


def _drawn_rect(model: PDFModel) -> fitz.Rect:
    page = model.doc[0]
    (rect,) = [
        fitz.Rect(r)
        for image in page.get_images(full=True)
        for r in page.get_image_rects(int(image[0]))
    ]
    return rect


@pytest.mark.parametrize("geometry", sorted(_FREE_ROTATION_GEOMETRIES))
def test_free_rotated_image_move_and_resize_on_offset_box_pages(geometry: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"rot_box_{geometry}.pdf"
        _make_box_geometry_image_pdf(path, **_FREE_ROTATION_GEOMETRIES[geometry])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            drawn = _drawn_rect(model)
            hit = model.get_object_info_at_point(1, _center(drawn))
            assert hit is not None and hit.object_kind == "native_image"
            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=30.0,
                )
            ) is True
            rotated_aabb = _drawn_rect(model)
            centre_before = _center(drawn)
            centre_after = _center(rotated_aabb)
            assert abs(centre_after.x - centre_before.x) <= 0.05
            assert abs(centre_after.y - centre_before.y) <= 0.05

            rotated = model.get_object_info_at_point(1, centre_after)
            assert rotated is not None
            dest = rotated_aabb + (20, 20, 20, 20)
            assert model.move_object(
                MoveObjectRequest(
                    object_id=rotated.object_id,
                    object_kind=rotated.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=dest,
                )
            ) is True
            moved = _drawn_rect(model)
            for got, want in zip(moved, dest):
                assert abs(got - want) <= 0.05, (tuple(moved), tuple(dest))

            moved_hit = model.get_object_info_at_point(1, _center(moved))
            assert moved_hit is not None
            assert abs((float(moved_hit.rotation) % 360) - 30.0) <= 1.0
            grown = moved + (-10, -10, 10, 10)
            assert model.resize_object(
                ResizeObjectRequest(
                    object_id=moved_hit.object_id,
                    object_kind=moved_hit.object_kind,
                    page_num=1,
                    destination_rect=grown,
                )
            ) is True
            resized = _drawn_rect(model)
            centre_resized = _center(resized)
            assert abs(centre_resized.x - _center(grown).x) <= 0.05
            assert abs(centre_resized.y - _center(grown).y) <= 0.05
            assert abs(resized.width - grown.width) <= 3.0
            assert abs(resized.height - grown.height) <= 3.0
        finally:
            model.close()
