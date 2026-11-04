from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import fitz
import pytest

from model.object_requests import DeleteObjectRequest, MoveObjectRequest, RotateObjectRequest
from model.pdf_content_ops import discover_native_image_invocations
from model.pdf_model import PDFModel


def _png_bytes(rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    # Generate a known-good tiny PNG without external deps (Pillow).
    # Distinct colours produce distinct image streams, hence distinct xrefs and
    # digests — the two app-images then resolve independently.
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 1, 1), 0)
    pix.set_pixel(0, 0, rgb)
    return pix.tobytes("png")


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=320, height=240)
    doc.save(path)
    doc.close()


def _image_markers(model: PDFModel, page_num: int = 1) -> dict[str, dict]:
    """object_id -> payload for every app-image marker annot on the page."""
    payloads: dict[str, dict] = {}
    for annot in model.doc[page_num - 1].annots() or []:
        if annot.info.get("subject") != "pdf_editor_image_object":
            continue
        payload = json.loads(annot.info.get("content") or "{}")
        payloads[payload["object_id"]] = payload
    return payloads


def _hit(model: PDFModel, point: fitz.Point):
    return model.get_object_info_at_point(1, point)


def test_add_image_object_creates_marker_and_hit_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            rect = fitz.Rect(40, 60, 140, 140)
            model.add_image_object(1, rect, _png_bytes(), rotation=0)

            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None
            assert hit.object_kind == "image"
            assert hit.supports_move is True
            assert hit.supports_delete is True
            assert hit.supports_rotate is True

            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_image_object"
            ]
            assert len(marker_annots) == 1
            payload = json.loads(marker_annots[0].info.get("content") or "{}")
            assert payload["kind"] == "image"
            assert "xref" in payload
        finally:
            model.close()


def test_move_image_object_updates_hit_location() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "move_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit.object_id,
                    object_kind=hit.object_kind,
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(160, 60, 260, 140),
                )
            )
            assert ok is True
            assert _hit(model, fitz.Point(60, 80)) is None
            moved = _hit(model, fitz.Point(180, 80))
            assert moved is not None
            assert moved.object_id == hit.object_id
        finally:
            model.close()


def test_rotate_image_object_updates_rotation_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
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
            rotated = _hit(model, fitz.Point(60, 80))
            assert rotated is not None
            assert rotated.rotation == 90
        finally:
            model.close()


def test_delete_image_object_removes_marker_and_page_image_ref() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "del_img.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 80))
            assert hit is not None
            page = model.doc[0]
            marker_annots = [
                annot for annot in (page.annots() or [])
                if annot.info.get("subject") == "pdf_editor_image_object"
            ]
            assert len(marker_annots) == 1
            before_images = list(page.get_images(full=True))

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))
            assert ok is True
            assert _hit(model, fitz.Point(60, 80)) is None

            # B1: the sole placement is gone, so _remove_native_image_invocation nulls
            # Resources/XObject/<name> and the page no longer lists the image. Re-fetch
            # the page handle rather than reusing the pre-delete one.
            assert len(before_images) == 1
            after_images = list(model.doc[0].get_images(full=True))
            assert after_images == [], f"page must list no images after delete, got {after_images}"

            # R6-01: the orphaned image xref must not survive as a recoverable object.
            # delete_objects_atomic sets secure_save_required, which makes the save a
            # full garbage=4 rewrite.
            assert model.secure_save_required is True
        finally:
            model.close()


def test_image_object_persists_through_save_and_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "persist_img.pdf"
        out = Path(tmp) / "persist_out.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)
            model.save_as(str(out))
        finally:
            model.close()

        model2 = PDFModel()
        try:
            model2.open_pdf(str(out))
            hit = _hit(model2, fitz.Point(60, 80))
            assert hit is not None
            assert hit.object_kind == "image"
        finally:
            model2.close()


def test_move_overlapping_app_images_both_survive() -> None:
    """Moving one app-image across an overlapping neighbour must not destroy the other.

    The real failure mode is visual: redaction of B's old region erases A's pixels
    from the content stream.  We verify both images still have content-stream placements.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_move.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            # Image A at (10, 10, 80, 80)
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes(), rotation=0)
            # Image B overlapping A, at (40, 40, 110, 110)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2, "Expected 2 image invocations before move"

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None and hit_b.object_kind == "image"

            # Move B to a new location that overlaps A
            ok = model.move_object(
                MoveObjectRequest(
                    object_id=hit_b.object_id,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(50, 50, 120, 120),
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2, (
                f"Expected 2 image invocations after move (A must survive), got {len(invocations_after)}"
            )
        finally:
            model.close()


def test_rotate_overlapping_app_image_neighbour_survives() -> None:
    """Rotating one app-image must not remove an overlapping neighbour's content-stream entry."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_rotate.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes(), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            ok = model.rotate_object(
                RotateObjectRequest(
                    object_id=hit_b.object_id,
                    object_kind="image",
                    page_num=1,
                    rotation_delta=90,
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2, (
                f"Expected 2 image invocations after rotate (A must survive), got {len(invocations_after)}"
            )
        finally:
            model.close()


def test_move_second_of_identical_app_images_moves_correct_placement() -> None:
    """Two app-images sharing the same xref AND identical bbox must be independently movable.

    Regression: _find_app_image_invocation used closest-bbox heuristic, which silently
    moved the FIRST placement when the user dragged the SECOND, breaking objects-mode UX.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "twin.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            rect = fitz.Rect(40, 60, 140, 140)
            oid1 = model.add_image_object(1, rect, png, rotation=0)
            oid2 = model.add_image_object(1, rect, png, rotation=0)
            assert oid1 != oid2

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2

            ok = model.move_object(
                MoveObjectRequest(
                    object_id=oid2,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=fitz.Rect(200, 100, 280, 160),
                )
            )
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 2

            # The placement that moved must be tied to oid2, NOT oid1.
            page = model.doc[0]
            payloads = {}
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payloads[payload["object_id"]] = payload

            assert payloads[oid1]["rect"] == [40.0, 60.0, 140.0, 140.0], (
                f"oid1 marker rect must remain at original, got {payloads[oid1]['rect']}"
            )
            # oid2 marker rect should reflect its new home
            r2 = payloads[oid2]["rect"]
            assert abs(r2[0] - 200) < 1.0 and abs(r2[2] - 280) < 1.0, (
                f"oid2 marker rect must reflect move destination, got {r2}"
            )

            # And the actual content-stream placement positions must agree:
            # one invocation at the original rect (oid1), one at the new rect (oid2).
            bboxes = sorted([(inv.bbox.x0, inv.bbox.y0, inv.bbox.x1, inv.bbox.y1) for inv in invocations_after])
            assert any(abs(b[0] - 40) < 1.0 and abs(b[2] - 140) < 1.0 for b in bboxes), (
                f"Expected an invocation still at original (40..140), got {bboxes}"
            )
            assert any(abs(b[0] - 200) < 1.0 and abs(b[2] - 280) < 1.0 for b in bboxes), (
                f"Expected an invocation at new (200..280), got {bboxes}"
            )
        finally:
            model.close()


# ---------------------------------------------------------------------------
# B1 (R5 backlog): deleting an app-image must strip ONLY its own content-stream
# invocation.  The old path redacted the image's rectangle, and
# ``apply_redactions`` is geometric: it destroys every image, glyph and stroke the
# rectangle touches.  See plans/archive/b1-delete-app-image-invocation-removal.md.
# ---------------------------------------------------------------------------


def test_delete_overlapping_app_images_neighbor_survives() -> None:
    """Deleting B must leave overlapping neighbour A's placement intact.

    Mirror of test_move_overlapping_app_images_both_survive for the delete path.
    Distinct colours => distinct xrefs => the two images resolve independently.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            assert len(discover_native_image_invocations(model.doc, 1)) == 2

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None and hit_b.object_kind == "image"

            ok = model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1))
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 1, (
                f"Expected 1 invocation after delete (A must survive), got {len(invocations_after)}"
            )
            # A's placement, not B's, is the survivor.
            surviving = invocations_after[0].bbox
            assert abs(surviving.x0 - 10) < 1.0 and abs(surviving.x1 - 80) < 1.0, (
                f"Survivor must be A at (10..80), got {tuple(surviving)}"
            )
            # A is still selectable; B's exclusive region is empty.
            assert _hit(model, fitz.Point(20, 20)) is not None
            assert _hit(model, fitz.Point(100, 100)) is None
        finally:
            model.close()


def test_delete_app_image_preserves_underlying_text() -> None:
    """apply_redactions strips glyphs under the rect; invocation removal must not."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "text_under_image.pdf"
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.insert_text((45, 70), "UNDER THE IMAGE", fontsize=9, fontname="helv")
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            assert "UNDER THE IMAGE" in model.doc[0].get_text()

            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 60))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, "image", 1))
            assert ok is True

            text_after = model.doc[0].get_text()
            assert "UNDER THE IMAGE" in text_after, (
                f"Deleting the image must not remove text beneath it; got {text_after.strip()!r}"
            )
        finally:
            model.close()


def test_delete_app_image_preserves_underlying_vector_art() -> None:
    """apply_redactions removes line art touching the rect; invocation removal must not."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "art_under_image.pdf"
        doc = fitz.open()
        page = doc.new_page(width=320, height=240)
        page.draw_line(fitz.Point(45, 60), fitz.Point(105, 60), color=(1, 0, 0), width=2)
        page.draw_line(fitz.Point(10, 220), fitz.Point(300, 220), color=(0, 1, 0), width=2)
        doc.save(path)
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            drawings_before = len(model.doc[0].get_drawings())
            assert drawings_before == 2

            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes(), rotation=0)
            hit = _hit(model, fitz.Point(60, 60))
            assert hit is not None

            ok = model.delete_object(DeleteObjectRequest(hit.object_id, "image", 1))
            assert ok is True

            drawings_after = len(model.doc[0].get_drawings())
            assert drawings_after == drawings_before, (
                f"Deleting the image must not remove line art crossing its rect; "
                f"{drawings_before} -> {drawings_after}"
            )
        finally:
            model.close()


def test_delete_one_of_two_shared_xref_images_neighbor_survives() -> None:
    """Identical bytes dedupe to one image xref under two XObject names.

    Deleting one placement must strip only its own name; the shared xref must stay
    alive while the neighbour still references it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shared_xref_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), png, rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), png, rotation=0)

            invocations_before = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_before) == 2
            shared_xref = invocations_before[0].xref
            assert invocations_before[1].xref == shared_xref, "expected PyMuPDF to dedupe the stream"

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            ok = model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1))
            assert ok is True

            invocations_after = discover_native_image_invocations(model.doc, 1)
            assert len(invocations_after) == 1, (
                f"Expected 1 invocation after delete, got {len(invocations_after)}"
            )
            # The shared xref survives because the neighbour still names it.
            assert invocations_after[0].xref == shared_xref
            assert model.doc.xref_stream(shared_xref), "shared image xref must still hold its stream"
        finally:
            model.close()


def test_delete_stale_shared_xref_marker_preserves_surviving_placement() -> None:
    """A stale marker must not retarget another placement of the same image stream."""
    from model.pdf_object_ops import _remove_native_image_invocation

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stale_shared_xref_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            stale_oid = model.add_image_object(1, fitz.Rect(10, 10, 80, 80), png, rotation=0)
            survivor_oid = model.add_image_object(
                1, fitz.Rect(150, 150, 220, 220), png, rotation=0
            )

            invocations = discover_native_image_invocations(model.doc, 1)
            assert len(invocations) == 2
            assert invocations[0].xref == invocations[1].xref

            # Simulate an external editor removing the first placement while leaving
            # pdf_editor's hidden marker annotation behind.
            assert _remove_native_image_invocation(model, invocations[0]) is True
            remaining = discover_native_image_invocations(model.doc, 1)
            assert len(remaining) == 1
            survivor_bbox = fitz.Rect(remaining[0].bbox)

            assert model.delete_object(DeleteObjectRequest(stale_oid, "image", 1)) is True

            after = discover_native_image_invocations(model.doc, 1)
            assert len(after) == 1, "deleting a stale marker must not delete its shared-xref neighbour"
            assert fitz.Rect(after[0].bbox) == survivor_bbox
            assert set(_image_markers(model)) == {survivor_oid}
        finally:
            model.close()


def test_delete_app_image_ambiguous_resolution_fails_safely() -> None:
    """Unresolvable placement => delete is a no-op, never a redaction.

    NOTE: this is a *contract* test, not a red-light test. On the pre-fix code the
    delete path never resolves an invocation at all, so it "succeeds" by redacting.
    It only becomes meaningful once resolution exists — it pins the decision that the
    ambiguous case fails safe rather than falling back to redaction.

    Ambiguity is forced the way it arises in the wild: the marker's recorded xref has
    drifted (post-GC renumbering), so resolution falls back to geometry+digest, and two
    same-digest twins sit at the same rect.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ambiguous_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            png = _png_bytes()
            rect = fitz.Rect(40, 60, 140, 140)
            oid1 = model.add_image_object(1, rect, png, rotation=0)
            oid2 = model.add_image_object(1, rect, png, rotation=0)
            assert len(discover_native_image_invocations(model.doc, 1)) == 2

            # Drift oid2's recorded xref to a dead value, keeping its digest: the
            # xref_candidates branch finds nothing, and the geometric+digest fallback
            # then sees two equally-good candidates and must refuse.
            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                if payload["object_id"] != oid2:
                    continue
                payload["xref"] = 999999
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            ok = model.delete_object(DeleteObjectRequest(oid2, "image", 1))
            assert ok is False, "ambiguous resolution must fail safe, not redact"

            # Document untouched: both placements and both markers survive.
            assert len(discover_native_image_invocations(model.doc, 1)) == 2
            markers = _image_markers(model)
            assert set(markers) == {oid1, oid2}
        finally:
            model.close()


def test_delete_app_image_then_undo_restores_both() -> None:
    """Undo after an overlap-delete brings the deleted image back, neighbour intact."""
    from model.edit_commands import SnapshotCommand

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "undo_delete.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None

            before = model._capture_doc_snapshot()
            assert model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1)) is True
            after = model._capture_doc_snapshot()

            assert len(discover_native_image_invocations(model.doc, 1)) == 1

            model.command_manager.record(
                SnapshotCommand(
                    model=model,
                    command_type="delete_object",
                    affected_pages=[1],
                    before_bytes=before,
                    after_bytes=after,
                    description="delete image",
                )
            )
            assert model.command_manager.undo() is True

            assert len(discover_native_image_invocations(model.doc, 1)) == 2
            assert _hit(model, fitz.Point(20, 20)) is not None
            assert _hit(model, fitz.Point(100, 100)) is not None
        finally:
            model.close()


def _raw_inherited_resources_pdf() -> bytes:
    """A spec-legal PDF whose /Page has NO /Resources — it inherits from /Pages.

    Hand-built because PyMuPDF always writes a page-level /Resources. Older writers and
    optimizers routinely emit this shape (PDF 1.7 §7.7.3.4, Table 30).
    """
    content = b"BT /F1 14 Tf 30 300 Td (INHERITED RESOURCES TEXT) Tj ET\n"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 "
            b"/Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 400 400] >>"
        ),
        3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        4: b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return bytes(out)


def _raw_two_page_mixed_resources_pdf() -> bytes:
    """Page 1 inherits resources; page 2 owns an unrelated resource dictionary."""
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 "
            b"/Resources << >> /MediaBox [0 0 400 400] >>"
        ),
        3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        4: b"<< /Length 0 >>\nstream\n\nendstream",
        5: (
            b"<< /Type /Page /Parent 2 0 R /Resources << >> "
            b"/MediaBox [0 0 400 400] /Contents 6 0 R >>"
        ),
        6: b"<< /Length 0 >>\nstream\n\nendstream",
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return bytes(out)


def test_delete_app_image_prunes_prefix_colliding_resource_name() -> None:
    """`/fzImg1` must not be considered "still referenced" because `/fzImg10` exists.

    PyMuPDF names page XObjects fzImg0, fzImg1, ... fzImg10, ... Once there are 11+ images,
    the retention check's raw substring scan (`b"/fzImg1" in stream`) matches the *token*
    `/fzImg10` in a neighbour's content stream, so the deleted image's resource entry is
    never pruned and the page keeps advertising an image it no longer draws.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "many_images.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oids = []
            for i in range(12):
                rgb = ((i * 20) % 256, (255 - i * 15) % 256, (i * 7) % 256)
                rect = fitz.Rect(10 + i * 5, 10 + i * 5, 60 + i * 5, 60 + i * 5)
                oids.append(model.add_image_object(1, rect, _png_bytes(rgb), rotation=0))

            invocations = discover_native_image_invocations(model.doc, 1)
            names = [inv.xobject_name for inv in invocations]
            assert "fzImg1" in names and "fzImg10" in names, names

            target = next(inv for inv in invocations if inv.xobject_name == "fzImg1")
            markers = _image_markers(model)
            target_oid = next(
                oid for oid, pl in markers.items() if abs(pl["rect"][0] - target.bbox.x0) < 1.5
            )

            before_images = list(model.doc[0].get_images(full=True))
            assert len(before_images) == 12

            assert model.delete_object(DeleteObjectRequest(target_oid, "image", 1)) is True

            after_names = [x[7] for x in model.doc[0].get_images(full=True)]
            assert "fzImg1" not in after_names, (
                f"fzImg1's resource entry must be pruned, got {sorted(after_names)}"
            )
            # The prefix-colliding neighbour must be untouched.
            assert "fzImg10" in after_names
            assert len(after_names) == 11
        finally:
            model.close()


def test_delete_app_image_does_not_shadow_inherited_resources() -> None:
    """Pruning must not fabricate a page-level /Resources on a page that inherits one.

    `xref_set_key(page.xref, "Resources/XObject/<name>", "null")` creates every missing
    link in the path, so on an inheriting page it writes a direct
    ``/Resources << /XObject << /fzImg0 null >> >>`` that SHADOWS the inherited dict —
    the page's fonts and other XObjects stop resolving through it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "inherited.pdf"
        path.write_bytes(_raw_inherited_resources_pdf())

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page_xref = model.doc[0].xref
            assert model.doc.xref_get_key(page_xref, "Resources")[0] == "null", (
                "fixture must start with an inheriting page"
            )
            text_before = model.doc[0].get_text().strip()
            assert "INHERITED RESOURCES TEXT" in text_before

            oid = model.add_image_object(1, fitz.Rect(50, 50, 150, 150), _png_bytes(), rotation=0)
            # PyMuPDF registers the XObject in the *inherited* dict, not on the page.
            assert model.doc.xref_get_key(page_xref, "Resources")[0] == "null"

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True

            kind, value = model.doc.xref_get_key(page_xref, "Resources")
            assert kind == "null", (
                f"delete must not fabricate a page-level /Resources, got {kind}: {value}"
            )
            # The inherited font must still resolve, and the image must be gone.
            assert model.doc[0].get_text().strip() == text_before
            assert discover_native_image_invocations(model.doc, 1) == []
            assert model.doc[0].get_images(full=True) == []
        finally:
            model.close()


def test_delete_inherited_image_ignores_same_name_in_unrelated_page_resources() -> None:
    """An unrelated page's `/fzImg0` must not retain the deleted inherited binding."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mixed_resources.pdf"
        path.write_bytes(_raw_two_page_mixed_resources_pdf())

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            target_oid = model.add_image_object(
                1, fitz.Rect(20, 20, 90, 90), _png_bytes((255, 0, 0)), rotation=0
            )
            model.add_image_object(
                2, fitz.Rect(120, 120, 190, 190), _png_bytes((0, 0, 255)), rotation=0
            )
            assert [row[7] for row in model.doc[0].get_images(full=True)] == ["fzImg0"]
            assert [row[7] for row in model.doc[1].get_images(full=True)] == ["fzImg0"]

            assert model.delete_object(DeleteObjectRequest(target_oid, "image", 1)) is True

            reopened = fitz.open("pdf", model.doc.tobytes(garbage=4))
            try:
                assert reopened[0].get_images(full=True) == [], (
                    "the deleted inherited resource must not survive secure garbage collection"
                )
                assert len(reopened[1].get_images(full=True)) == 1
            finally:
                reopened.close()
        finally:
            model.close()


def _strip_invocation(model: PDFModel, page_num: int = 1) -> None:
    """Excise the image's content-stream placement, leaving the marker annot orphaned.

    Simulates what an external editor does when it removes an image: the XObject
    invocation is gone, but our hidden marker annot (which it knows nothing about) stays.
    """
    from model.pdf_object_ops import _remove_native_image_invocation

    invocations = discover_native_image_invocations(model.doc, page_num)
    assert invocations, "fixture must have an invocation to strip"
    assert _remove_native_image_invocation(model, invocations[0]) is True


def test_delete_orphaned_app_image_marker_cleans_up_the_marker() -> None:
    """An unresolvable marker with NO surviving image must be deletable, not a zombie.

    Fail-safe (return False) is right when resolution is *ambiguous* — the pixels exist and
    deleting the marker alone would orphan them. It is wrong when there is no candidate at
    all: nothing renders, and refusing to delete leaves a hit-detectable object that
    advertises supports_delete=True and that no verb can touch (move/rotate already fail on
    this population, so delete was its last working verb).
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "orphan_marker.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            _strip_invocation(model)
            assert discover_native_image_invocations(model.doc, 1) == []
            # The marker survives and is still selectable — this is the zombie state.
            assert _hit(model, fitz.Point(60, 80)) is not None
            assert oid in _image_markers(model)

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True

            assert _image_markers(model) == {}, "the orphaned marker must be cleaned up"
            assert _hit(model, fitz.Point(60, 80)) is None
        finally:
            model.close()


def test_delete_app_image_with_corrupt_xref_payload_does_not_raise() -> None:
    """A non-numeric `xref` in the marker payload must not raise through the Qt slot.

    `int(payload.get("xref", 0) or 0)` on `"abc"` raised ValueError, which
    delete_objects_atomic re-raises after rollback and PDFController.delete_object does not
    catch. The digest still resolves the image, so the delete should simply succeed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "corrupt_xref.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payload["xref"] = "abc"  # corrupt / third-party writer
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            # Must not raise; the digest still identifies the unique image.
            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True
            assert discover_native_image_invocations(model.doc, 1) == []
        finally:
            model.close()


def test_delete_app_image_without_xref_in_payload_still_resolves() -> None:
    """The `if not xref: return False` guard was stronger than the resolver it gated.

    `_find_app_image_invocation` handles a missing/0 xref via its geometric+digest fallback,
    and `_resolve_marker_image_invocation` backfills the payload. Guarding on xref before
    calling them forecloses deletes that would otherwise succeed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "no_xref.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            oid = model.add_image_object(1, fitz.Rect(40, 60, 140, 140), _png_bytes(), rotation=0)

            page = model.doc[0]
            for annot in page.annots() or []:
                if annot.info.get("subject") != "pdf_editor_image_object":
                    continue
                payload = json.loads(annot.info.get("content") or "{}")
                payload.pop("xref", None)  # legacy marker, written before xref was recorded
                annot.set_info(
                    content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    subject="pdf_editor_image_object",
                )
                annot.update()

            assert model.delete_object(DeleteObjectRequest(oid, "image", 1)) is True
            assert discover_native_image_invocations(model.doc, 1) == []
            assert _image_markers(model) == {}
        finally:
            model.close()


def test_delete_overlapping_app_image_survives_save_reopen() -> None:
    """The rewritten content stream must persist: neighbour still there after reopen."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "overlap_persist.pdf"
        out = Path(tmp) / "overlap_persist_out.pdf"
        _make_pdf(path)

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.add_image_object(1, fitz.Rect(10, 10, 80, 80), _png_bytes((255, 0, 0)), rotation=0)
            model.add_image_object(1, fitz.Rect(40, 40, 110, 110), _png_bytes((0, 0, 255)), rotation=0)

            hit_b = _hit(model, fitz.Point(100, 100))
            assert hit_b is not None
            assert model.delete_object(DeleteObjectRequest(hit_b.object_id, "image", 1)) is True
            model.save_as(str(out))
        finally:
            model.close()

        model2 = PDFModel()
        try:
            model2.open_pdf(str(out))
            invocations = discover_native_image_invocations(model2.doc, 1)
            assert len(invocations) == 1, (
                f"Neighbour must survive save+reopen, got {len(invocations)} invocations"
            )
            assert _hit(model2, fitz.Point(20, 20)) is not None
            assert _hit(model2, fitz.Point(100, 100)) is None
        finally:
            model2.close()


# --- F15-G2: app images on offset MediaBox / CropBox and /UserUnit pages -----
#
# The app image is resolved through native discovery. With discovery offset by
# MediaBox.y0 (or unscaled by /UserUnit), move/rotate returned False, and delete
# took the "orphaned marker" branch: it returned True and removed the marker
# while the image stayed drawn and could no longer be selected.

_APP_IMAGE_GEOMETRIES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "negmb": {"mediabox": (-100, -200, 500, 600)},
    "posmb": {"mediabox": (50, 70, 650, 870)},
    "negcrop": {"mediabox": (-100, -200, 500, 600), "cropbox": (-50, -150, 400, 500)},
    "crop_past_mb": {"mediabox": (0, 0, 600, 800), "cropbox": (-50, -50, 500, 700)},
    "uu2": {"mediabox": (0, 0, 300, 400), "user_unit": 2},
}


def _make_box_geometry_pdf(
    path: Path,
    *,
    mediabox: tuple[float, float, float, float],
    cropbox: tuple[float, float, float, float] | None = None,
    user_unit: float | None = None,
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox is not None:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    if user_unit is not None:
        doc.xref_set_key(page.xref, "UserUnit", f"{user_unit:g}")
    doc.save(path)
    doc.close()


def _rgb_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, rgb)
    return pix.tobytes("png")


def _drawn_image_rects(model: PDFModel, page_num: int = 1) -> list[fitz.Rect]:
    page = model.doc[page_num - 1]
    return [
        fitz.Rect(rect)
        for image in page.get_images(full=True)
        for rect in page.get_image_rects(int(image[0]))
    ]


def _rect_centre(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _assert_rect_close(actual: fitz.Rect, expected: fitz.Rect, tol: float = 0.05) -> None:
    got = (actual.x0, actual.y0, actual.x1, actual.y1)
    want = (expected.x0, expected.y0, expected.x1, expected.y1)
    assert all(abs(a - b) <= tol for a, b in zip(got, want)), (got, want)


@pytest.mark.parametrize("geometry", sorted(_APP_IMAGE_GEOMETRIES))
def test_app_image_move_rotate_delete_on_offset_box_pages(geometry: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"app_box_{geometry}.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES[geometry])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            placed = fitz.Rect(300, 300, 380, 340)
            object_id = model.add_image_object(1, placed, _png_bytes(), rotation=0)
            (drawn,) = _drawn_image_rects(model)
            _assert_rect_close(drawn, placed)

            moved_to = fitz.Rect(320, 330, 400, 370)
            assert model.move_object(
                MoveObjectRequest(
                    object_id=object_id,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=moved_to,
                )
            ) is True
            (after_move,) = _drawn_image_rects(model)
            _assert_rect_close(after_move, moved_to)

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=object_id,
                    object_kind="image",
                    page_num=1,
                    rotation_delta=90,
                )
            ) is True
            hit = _hit(model, fitz.Point(360, 350))
            assert hit is not None and hit.object_kind == "image"
            assert abs((float(hit.rotation) % 360) - 90.0) <= 1.0

            assert model.delete_object(
                DeleteObjectRequest(object_id=object_id, object_kind="image", page_num=1)
            ) is True
            # The delete really removed the drawing, not just the hidden marker.
            assert _drawn_image_rects(model) == []
            assert _image_markers(model) == {}
            assert _hit(model, fitz.Point(360, 350)) is None
        finally:
            model.close()


# --- F15-4: the marker must record the DRAWN placement, not the requested rect ----
#
# Every later verb resolves the app image by matching the marker's rect (within 2 pt)
# and rotation against the drawn invocation. A marker that kept the requested rect
# after an absolute rotation (pre-rotation rect, new angle), a delta rotation from a
# free angle, a near-45-degree resize or a letterboxed insert no longer resolved: move
# and rotate returned False, and delete took the orphaned-marker branch, returned True
# and removed only the marker while the image stayed drawn (then hit as native_image).


def _marker_rect(model: PDFModel, object_id: str, page_num: int = 1) -> fitz.Rect:
    return fitz.Rect(_image_markers(model, page_num)[object_id]["rect"])


def _assert_delete_removes_drawing(model: PDFModel, object_id: str) -> None:
    assert model.delete_object(
        DeleteObjectRequest(object_id=object_id, object_kind="image", page_num=1)
    ) is True
    assert _drawn_image_rects(model) == [], "delete must remove the drawing, not only the marker"
    assert _image_markers(model) == {}


@pytest.mark.parametrize("angle", [30.0, 90.0])
@pytest.mark.parametrize("geometry", ["plain", "posmb", "negcrop"])
def test_app_image_absolute_rotation_keeps_move_rotate_delete_working(
    geometry: str, angle: float
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"abs_rot_{geometry}.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES[geometry])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            placed = fitz.Rect(200, 200, 350, 300)
            object_id = model.add_image_object(1, placed, _png_bytes(), rotation=0)

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=object_id,
                    object_kind="image",
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=angle,
                )
            ) is True
            (rotated,) = _drawn_image_rects(model)
            assert rotated != placed
            _assert_rect_close(_marker_rect(model, object_id), rotated)
            hit = _hit(model, _rect_centre(rotated))
            assert hit is not None and hit.object_id == object_id
            assert abs((float(hit.rotation) % 360) - angle) <= 1.0

            moved_to = fitz.Rect(rotated) + (20, 20, 20, 20)
            assert model.move_object(
                MoveObjectRequest(
                    object_id=object_id,
                    object_kind="image",
                    source_page=1,
                    destination_page=1,
                    destination_rect=moved_to,
                )
            ) is True
            (after_move,) = _drawn_image_rects(model)
            _assert_rect_close(after_move, moved_to, tol=0.5)
            _assert_rect_close(_marker_rect(model, object_id), after_move)

            assert model.rotate_object(
                RotateObjectRequest(
                    object_id=object_id,
                    object_kind="image",
                    page_num=1,
                    rotation_delta=0,
                    absolute_rotation=0.0,
                )
            ) is True
            (upright,) = _drawn_image_rects(model)
            # Back to the un-rotated 150x100 image, centred where the move left it.
            assert abs(upright.width - 150.0) <= 0.5 and abs(upright.height - 100.0) <= 0.5
            _assert_rect_close(_marker_rect(model, object_id), upright)

            _assert_delete_removes_drawing(model, object_id)
        finally:
            model.close()


def test_app_image_delta_rotation_from_free_angle_keeps_marker_on_drawing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "delta_from_free.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            object_id = model.add_image_object(1, fitz.Rect(200, 200, 350, 300), _png_bytes(), rotation=0)
            assert model.rotate_object(
                RotateObjectRequest(object_id, "image", 1, rotation_delta=0, absolute_rotation=30.0)
            ) is True
            assert model.rotate_object(
                RotateObjectRequest(object_id, "image", 1, rotation_delta=90)
            ) is True
            (drawn,) = _drawn_image_rects(model)
            _assert_rect_close(_marker_rect(model, object_id), drawn)
            assert abs(float(_image_markers(model)[object_id]["rotation"]) % 360 - 120.0) <= 1.0
            _assert_delete_removes_drawing(model, object_id)
        finally:
            model.close()


def test_app_image_resize_near_45_degrees_records_drawn_bbox() -> None:
    """At 45 degrees the AABB->size inversion is singular and the size is kept, so the
    drawn AABB differs from the requested one; the marker must follow the drawing."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resize_45.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            object_id = model.add_image_object(1, fitz.Rect(200, 200, 350, 300), _png_bytes(), rotation=0)
            assert model.rotate_object(
                RotateObjectRequest(object_id, "image", 1, rotation_delta=0, absolute_rotation=45.0)
            ) is True
            (rotated,) = _drawn_image_rects(model)
            requested = fitz.Rect(rotated.x0, rotated.y0, rotated.x1 + 60, rotated.y1 + 40)
            assert model.move_object(
                MoveObjectRequest(object_id, "image", 1, 1, requested)
            ) is True
            (drawn,) = _drawn_image_rects(model)
            _assert_rect_close(_marker_rect(model, object_id), drawn)
            _assert_delete_removes_drawing(model, object_id)
        finally:
            model.close()


def test_app_image_letterboxed_insert_records_drawn_bbox() -> None:
    """The UI inserts into a fixed 4:3 rect; an image of another aspect is letterboxed
    inside it, and the marker must hold the letterboxed placement."""
    wide_png = _rgb_png(20, 10, (0, 200, 0))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "letterbox.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            requested = fitz.Rect(100, 100, 200, 200)
            object_id = model.add_image_object(1, requested, wide_png, rotation=0)
            (drawn,) = _drawn_image_rects(model)
            assert drawn != requested, "fixture must exercise the letterboxed insert"
            _assert_rect_close(_marker_rect(model, object_id), drawn)

            moved_to = fitz.Rect(drawn) + (150, 150, 150, 150)
            assert model.move_object(
                MoveObjectRequest(object_id, "image", 1, 1, moved_to)
            ) is True
            (after_move,) = _drawn_image_rects(model)
            _assert_rect_close(after_move, moved_to, tol=0.5)
            _assert_delete_removes_drawing(model, object_id)
        finally:
            model.close()


def test_same_letterboxed_picture_inserted_twice_both_markers_follow_their_drawing(caplog) -> None:
    """Identical bytes reuse one image xref: the insert must pick ITS new placement."""
    wide_png = _rgb_png(20, 10, (0, 200, 0))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "letterbox_twice.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            with caplog.at_level("WARNING", logger="model.pdf_object_ops"):
                first = model.add_image_object(1, fitz.Rect(100, 100, 200, 200), wide_png, rotation=0)
                second = model.add_image_object(1, fitz.Rect(300, 300, 400, 400), wide_png, rotation=0)
            assert not [r for r in caplog.records if "add_image_object" in r.getMessage()]
            invocations = discover_native_image_invocations(model.doc, 1)
            assert len(invocations) == 2 and invocations[0].xref == invocations[1].xref
            _assert_rect_close(_marker_rect(model, first), fitz.Rect(100, 125, 200, 175))
            _assert_rect_close(_marker_rect(model, second), fitz.Rect(300, 325, 400, 375))

            for object_id in (first, second):
                moved_to = _marker_rect(model, object_id) + (0, 200, 0, 200)
                assert model.move_object(
                    MoveObjectRequest(object_id, "image", 1, 1, moved_to)
                ) is True
                _assert_rect_close(_marker_rect(model, object_id), moved_to, tol=0.5)
            assert model.delete_object(DeleteObjectRequest(first, "image", 1)) is True
            assert set(_image_markers(model)) == {second}
            (left,) = _drawn_image_rects(model)
            _assert_rect_close(left, fitz.Rect(300, 525, 400, 575), tol=0.5)
            _assert_delete_removes_drawing(model, second)
        finally:
            model.close()


# --- F14-MM-1b / F15-G4-IMG: app images on /Rotate pages -----------------------------
#
# ``insert_image`` and the image ``cm`` speak UNROTATED page space, while the request
# (``visual_rect``), the hit point, ``ObjectHitInfo.bbox`` and a move's destination are
# VISUAL. The visual rect went straight to ``insert_image``: on a /Rotate 90 page an
# image added at (100,200,200,250) was drawn at (592,100,642,200), the hidden marker
# stayed at the request (selectable where nothing is drawn) and an offset CropBox /
# MediaBox displaced it further. The oracle is the rendered ink (pixmap pixels at the
# identity matrix are visual coordinates), never ``get_image_rects`` (unrotated).

_ROTATED_BOXES = {
    "plain": {"mediabox": (0, 0, 600, 800)},
    "crop": {"mediabox": (0, 0, 600, 800), "cropbox": (30, 40, 565, 760)},
    "negmb": {"mediabox": (-100, -80, 500, 720)},
}


def _strip_png() -> bytes:
    """A 2x1 image: red left half, blue right half (shows orientation, not only place)."""
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 2, 1), 0)
    pix.set_pixel(0, 0, (255, 0, 0))
    pix.set_pixel(1, 0, (0, 0, 255))
    return pix.tobytes("png")


def _channel_table(lo: int, hi: int) -> bytes:
    return bytes(1 if lo <= v <= hi else 0 for v in range(256))


_HIGH = _channel_table(200, 255)
_LOW = _channel_table(0, 80)


def _ink_rect(page: fitz.Page, colour: str) -> fitz.Rect | None:
    """Visual bbox of the rendered red (``"r"``) or blue (``"b"``) pixels."""
    pix = page.get_pixmap(matrix=fitz.Identity, alpha=False)
    samples, n, stride, width = pix.samples, pix.n, pix.stride, pix.width
    tables = (_HIGH, _LOW, _LOW) if colour == "r" else (_LOW, _LOW, _HIGH)
    x0 = y0 = None
    x1 = y1 = -1
    for y in range(pix.height):
        row = samples[y * stride : y * stride + width * n]
        mask = (
            int.from_bytes(row[0::n].translate(tables[0]), "big")
            & int.from_bytes(row[1::n].translate(tables[1]), "big")
            & int.from_bytes(row[2::n].translate(tables[2]), "big")
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


def _strip_halves(page: fitz.Page) -> tuple[fitz.Rect, fitz.Rect]:
    """Visual bboxes of the strip's red and blue halves; both must be drawn."""
    red, blue = _ink_rect(page, "r"), _ink_rect(page, "b")
    assert red is not None and blue is not None, (red, blue)
    return red, blue


def _strip_ink(page: fitz.Page) -> fitz.Rect:
    red, blue = _strip_halves(page)
    return red | blue


def _make_rotated_box_pdf(path: Path, rotate: int, box: str) -> None:
    _make_box_geometry_pdf(path, **_ROTATED_BOXES[box])
    doc = fitz.open(path)
    doc.xref_set_key(doc[0].xref, "Rotate", str(rotate))
    doc.saveIncr()
    doc.close()


def _assert_strip_drawn_upright_at(page: fitz.Page, visual: fitz.Rect, tol: float = 2.0) -> None:
    red, blue = _strip_halves(page)
    mid = (visual.x0 + visual.x1) / 2.0
    _assert_rect_close(red, fitz.Rect(visual.x0, visual.y0, mid, visual.y1), tol)
    _assert_rect_close(blue, fitz.Rect(mid, visual.y0, visual.x1, visual.y1), tol)


@pytest.mark.parametrize("box", sorted(_ROTATED_BOXES))
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_app_image_on_rotated_page_is_drawn_hit_moved_and_deleted_in_visual_space(
    rotate: int, box: str
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"rot_{rotate}_{box}.pdf"
        out = Path(tmp) / f"rot_{rotate}_{box}_out.pdf"
        _make_rotated_box_pdf(path, rotate, box)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            placed = fitz.Rect(100, 200, 300, 300)
            object_id = model.add_image_object(1, placed, _strip_png(), rotation=0)
            _assert_strip_drawn_upright_at(model.doc[0], placed)
            # The hidden marker sits on the image (annotation rects are unrotated space).
            page = model.doc[0]
            (marker,) = [a for a in page.annots() or [] if a.info.get("subject") == "pdf_editor_image_object"]
            marker_visual = (fitz.Rect(marker.rect) * page.rotation_matrix).normalize()
            _assert_rect_close(marker_visual, placed + (-1, -1, 1, 1), tol=1.0)

            hit = _hit(model, _rect_centre(placed))
            assert hit is not None and hit.object_id == object_id and hit.object_kind == "image"
            _assert_rect_close(fitz.Rect(hit.bbox), placed, tol=1.0)
            # Nothing is selectable below the image, where nothing is drawn.
            assert _hit(model, fitz.Point(placed.x0 + 10, placed.y1 + 60)) is None

            moved_to = fitz.Rect(150, 250, 350, 350)
            assert model.move_object(
                MoveObjectRequest(object_id, "image", 1, 1, moved_to)
            ) is True
            _assert_strip_drawn_upright_at(model.doc[0], moved_to)
            moved = _hit(model, _rect_centre(moved_to))
            assert moved is not None and moved.object_id == object_id
            _assert_rect_close(fitz.Rect(moved.bbox), moved_to, tol=1.0)

            # A quarter-turn delta keeps the bbox (cardinal rewrite) and turns the
            # picture: red is no longer the left half. The marker follows the ink.
            assert model.rotate_object(
                RotateObjectRequest(object_id, "image", 1, rotation_delta=90)
            ) is True
            turned = _strip_ink(model.doc[0])
            _assert_rect_close(turned, moved_to, tol=2.0)
            turned_red = _ink_rect(model.doc[0], "r")
            assert turned_red is not None and turned_red.width > moved_to.width - 4
            turned_hit = _hit(model, _rect_centre(turned))
            assert turned_hit is not None and turned_hit.object_id == object_id
            _assert_rect_close(fitz.Rect(turned_hit.bbox), turned, tol=2.0)
            model.save_as(str(out))
        finally:
            model.close()

        reopened = PDFModel()
        try:
            reopened.open_pdf(str(out))
            again = _hit(reopened, fitz.Point(250, 300))
            assert again is not None and again.object_id == object_id
            assert reopened.delete_object(DeleteObjectRequest(object_id, "image", 1)) is True
            assert _ink_rect(reopened.doc[0], "r") is None
            assert _ink_rect(reopened.doc[0], "b") is None
            assert _image_markers(reopened) == {}
        finally:
            reopened.close()


@pytest.mark.parametrize("rotate", [90, 270])
def test_letterboxed_app_image_on_rotated_page_stays_inside_the_requested_visual_rect(
    rotate: int,
) -> None:
    """The UI's default rect letterboxes a 2:1 picture; on a quarter-turned page the
    letterbox must be taken in the VISUAL rect (not its swapped unrotated twin)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"letterbox_rot_{rotate}.pdf"
        _make_rotated_box_pdf(path, rotate, "plain")
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            requested = fitz.Rect(100, 200, 300, 400)
            object_id = model.add_image_object(1, requested, _strip_png(), rotation=0)
            drawn = fitz.Rect(100, 250, 300, 350)
            _assert_strip_drawn_upright_at(model.doc[0], drawn)
            hit = _hit(model, _rect_centre(drawn))
            assert hit is not None and hit.object_id == object_id
            _assert_rect_close(fitz.Rect(hit.bbox), drawn, tol=1.0)
            # The letterbox bands are empty: no phantom selection there.
            assert _hit(model, fitz.Point(200, 210)) is None
        finally:
            model.close()


def test_legacy_image_marker_on_rotated_page_still_resolves() -> None:
    """A marker written by an older build on a /Rotate page holds the image's
    UNROTATED placement (the numbers handed to ``insert_image``). It must still be
    selectable where the image is drawn, and still move and delete."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy_rot90.pdf"
        _make_rotated_box_pdf(path, 90, "plain")
        doc = fitz.open(path)
        page = doc[0]
        legacy_rect = fitz.Rect(200, 400, 300, 450)
        xref = page.insert_image(legacy_rect, stream=_strip_png(), overlay=True)
        marker = page.add_rect_annot(legacy_rect)
        payload = {
            "version": 1,
            "kind": "image",
            "object_id": "legacy-image",
            "page_num": 1,
            "rect": [200.0, 400.0, 300.0, 450.0],
            "rotation": 0,
            "xref": int(xref),
            "image_digest": hashlib.sha256(doc.xref_stream(xref)).hexdigest(),
        }
        marker.set_flags(marker.flags | fitz.PDF_ANNOT_IS_HIDDEN)
        marker.set_info(content=json.dumps(payload), subject="pdf_editor_image_object")
        marker.update()
        doc.saveIncr()
        doc.close()

        model = PDFModel()
        try:
            model.open_pdf(str(path))
            drawn = _strip_ink(model.doc[0])
            hit = _hit(model, _rect_centre(drawn))
            assert hit is not None and hit.object_id == "legacy-image"
            _assert_rect_close(fitz.Rect(hit.bbox), drawn, tol=2.0)
            # Its old (unrotated) numbers, read as visual, no longer select anything.
            assert _hit(model, fitz.Point(210, 440)) is None
            moved_to = fitz.Rect(drawn) + (40, 30, 40, 30)
            assert model.move_object(
                MoveObjectRequest("legacy-image", "image", 1, 1, moved_to)
            ) is True
            _assert_rect_close(_strip_ink(model.doc[0]), moved_to, tol=2.0)
            assert model.delete_object(DeleteObjectRequest("legacy-image", "image", 1)) is True
            assert _ink_rect(model.doc[0], "r") is None and _ink_rect(model.doc[0], "b") is None
            assert _image_markers(model) == {}
        finally:
            model.close()


# --- F15-G1-UU-ROT: app images on a ROTATED /UserUnit page --------------------------
#
# ``insert_image`` places through ``page.transformation_matrix``, which drops the
# ``/UserUnit`` scale once ``/Rotate != 0`` (and ``derotation_matrix`` drops it from the
# visual->unrotated mapping), so the picture was drawn ``UserUnit`` times too large and
# too far from the origin -- or off the page. The oracle is the rendered ink.


@pytest.mark.parametrize("user_unit", [2.0, 0.5])
@pytest.mark.parametrize("rotate", [90, 180, 270])
def test_app_image_on_rotated_user_unit_page_is_drawn_and_picked_at_the_requested_rect(
    rotate: int, user_unit: float
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"uu_{rotate}_{user_unit}.pdf"
        _make_box_geometry_pdf(path, mediabox=(0, 0, 300, 400), user_unit=user_unit)
        doc = fitz.open(path)
        doc.xref_set_key(doc[0].xref, "Rotate", str(rotate))
        doc.saveIncr()
        doc.close()
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            page_rect = fitz.Rect(model.doc[0].rect)
            width = page_rect.width * 0.4  # the 2:1 test picture fills it (no letterbox)
            placed = fitz.Rect(
                page_rect.width * 0.2, page_rect.height * 0.3, page_rect.width * 0.2 + width, page_rect.height * 0.3 + width / 2
            )
            object_id = model.add_image_object(1, placed, _strip_png(), rotation=0)
            _assert_strip_drawn_upright_at(model.doc[0], placed, tol=2.0)
            hit = _hit(model, _rect_centre(placed))
            assert hit is not None and hit.object_id == object_id and hit.object_kind == "image"
            _assert_rect_close(fitz.Rect(hit.bbox), placed, tol=1.5)
        finally:
            model.close()


# --- D-OLD-MARKERS (owner decision after round 15): repair old image markers -----------
#
# Markers saved by builds before F15-4 hold the pre-rotation rect with the rotated angle,
# or the 4:3 insert rect around a letterboxed picture. They did not resolve: Move /
# Rotate returned False silently and Delete removed only the hidden marker while the
# image stayed drawn. Now the marker is re-resolved when exactly ONE drawn placement has
# the same digest, the same angle and the same centre; otherwise the verb refuses with a
# reason code and Delete never removes the marker alone.


def _age_image_marker(model: PDFModel, object_id: str, **fields) -> None:
    """Rewrite one marker the way an older build saved it (payload AND annotation /Rect)."""
    page = model.doc[0]
    for annot in page.annots() or []:
        if annot.info.get("subject") != "pdf_editor_image_object":
            continue
        payload = json.loads(annot.info.get("content") or "{}")
        if payload.get("object_id") != object_id:
            continue
        for key, value in fields.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        if fields.get("rect") is not None:
            annot.set_rect(fitz.Rect(fields["rect"]))
        annot.set_info(content=json.dumps(payload), subject="pdf_editor_image_object")
        annot.update()
        return
    raise AssertionError(f"no marker {object_id}")


def _old_rotated_marker(model: PDFModel) -> tuple[str, fitz.Rect]:
    """A 3:2 picture rotated 30 degrees about its centre, marker holding the pre-rotation
    rect with the rotated angle (pre-F15-4 absolute-rotation branch)."""
    placed = fitz.Rect(200, 200, 350, 300)
    object_id = model.add_image_object(1, placed, _rgb_png(3, 2, (200, 0, 0)), rotation=0)
    assert model.rotate_object(
        RotateObjectRequest(object_id, "image", 1, rotation_delta=0, absolute_rotation=30.0)
    ) is True
    _age_image_marker(model, object_id, rect=[placed.x0, placed.y0, placed.x1, placed.y1])
    return object_id, placed


def _old_letterbox_marker(model: PDFModel, *, keep_xref: bool = True) -> tuple[str, fitz.Rect]:
    """A 2:1 picture inserted into the 4:3 insert rect, marker holding the 4:3 rect
    around the letterboxed drawing (pre-F15-4 add_image_object); optionally also without
    the ``xref`` field (markers written before it was recorded)."""
    requested = fitz.Rect(100, 100, 200, 175)
    object_id = model.add_image_object(1, requested, _rgb_png(20, 10, (0, 160, 0)), rotation=0)
    (drawn,) = _drawn_image_rects(model)
    assert drawn != requested, "fixture must exercise the letterboxed insert"
    fields: dict = {"rect": [requested.x0, requested.y0, requested.x1, requested.y1]}
    if not keep_xref:
        fields["xref"] = None
    _age_image_marker(model, object_id, **fields)
    return object_id, requested


_OLD_IMAGE_MARKERS = {
    "pre_rotation_rect": _old_rotated_marker,
    "letterbox_4_3": _old_letterbox_marker,
    "letterbox_no_xref": lambda model: _old_letterbox_marker(model, keep_xref=False),
}


@pytest.mark.parametrize("op", ["move", "resize", "rotate", "delete"])
@pytest.mark.parametrize("fixture", sorted(_OLD_IMAGE_MARKERS))
def test_old_image_marker_is_repaired_and_the_verb_changes_the_drawing(fixture: str, op: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"old_marker_{fixture}.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            object_id, _stale = _OLD_IMAGE_MARKERS[fixture](model)
            (drawn,) = _drawn_image_rects(model)
            angle = float(_image_markers(model)[object_id]["rotation"]) % 360
            if op == "move":
                dest = fitz.Rect(drawn) + (40, 120, 40, 120)
                assert model.move_object(MoveObjectRequest(object_id, "image", 1, 1, dest)) is True
                (after,) = _drawn_image_rects(model)
                _assert_rect_close(after, dest, tol=0.5)
            elif op == "resize":
                dest = fitz.Rect(drawn.x0, drawn.y0, drawn.x1 + 30, drawn.y1 + 20)
                assert model.move_object(MoveObjectRequest(object_id, "image", 1, 1, dest)) is True
                (after,) = _drawn_image_rects(model)
                assert after != drawn
            elif op == "rotate":
                assert model.rotate_object(
                    RotateObjectRequest(object_id, "image", 1, rotation_delta=90)
                ) is True
                (after,) = _drawn_image_rects(model)
                # Rotation about the drawn centre (not the stale rect's numbers).
                centre, was = _rect_centre(after), _rect_centre(drawn)
                assert abs(centre.x - was.x) <= 0.5 and abs(centre.y - was.y) <= 0.5, (after, drawn)
                new_angle = float(_image_markers(model)[object_id]["rotation"]) % 360
                assert abs(new_angle - (angle + 90) % 360) <= 1.0
            else:
                assert model.delete_object(DeleteObjectRequest(object_id, "image", 1)) is True
                assert _drawn_image_rects(model) == [], "delete must remove the drawing, not only the marker"
                assert _image_markers(model) == {}
                assert model.last_object_op_refusal is None
                return
            assert model.last_object_op_refusal is None
            # The marker now follows the drawing, so the next verb resolves directly.
            _assert_rect_close(_marker_rect(model, object_id), after, tol=0.05)
            _assert_delete_removes_drawing(model, object_id)
        finally:
            model.close()


def _no_clear_candidate_marker(model: PDFModel, case: str) -> str:
    """Two placements of the same picture share one centre and one angle (``twins``), or
    the one same-digest placement has another angle than the marker (``angle_mismatch``):
    no single clear candidate."""
    requested = fitz.Rect(100, 100, 200, 175)
    wide = _rgb_png(20, 10, (0, 160, 0))
    first = model.add_image_object(1, requested, wide, rotation=0)
    if case == "twins":
        second = model.add_image_object(1, requested, wide, rotation=0)
        _age_image_marker(model, second, rect=[requested.x0, requested.y0, requested.x1, requested.y1])
        return second
    # Drawn at 30 degrees; the old marker kept the old rect AND angle 0.
    assert model.rotate_object(
        RotateObjectRequest(first, "image", 1, rotation_delta=0, absolute_rotation=30.0)
    ) is True
    _age_image_marker(
        model, first, rect=[requested.x0, requested.y0, requested.x1, requested.y1], rotation=0
    )
    return first


@pytest.mark.parametrize("op", ["move", "rotate", "delete"])
@pytest.mark.parametrize("case", ["twins", "angle_mismatch"])
def test_old_image_marker_without_one_clear_candidate_refuses_and_keeps_marker_and_drawing(
    case: str, op: str
) -> None:
    from model.object_op_refusal import ObjectOpRefusal

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"ambiguous_{case}.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            object_id = _no_clear_candidate_marker(model, case)
            drawn_before = _drawn_image_rects(model)
            markers_before = _image_markers(model)
            if op == "move":
                ok = model.move_object(
                    MoveObjectRequest(object_id, "image", 1, 1, fitz.Rect(300, 300, 400, 350))
                )
            elif op == "rotate":
                ok = model.rotate_object(RotateObjectRequest(object_id, "image", 1, rotation_delta=90))
            else:
                ok = model.delete_object(DeleteObjectRequest(object_id, "image", 1))
            assert ok is False
            refusal = model.last_object_op_refusal
            assert refusal is not None and refusal.reason is ObjectOpRefusal.IMAGE_NOT_LOCATED
            assert refusal.object_kind == "image" and refusal.object_id == object_id
            assert _drawn_image_rects(model) == drawn_before
            # Never repaired by a guess, never removed alone.
            assert _image_markers(model) == markers_before
        finally:
            model.close()


@pytest.mark.parametrize("fixture", ["pre_rotation_rect", "letterbox_4_3"])
def test_old_image_marker_saved_and_reopened_is_repaired(fixture: str) -> None:
    """The real old-file case: the aged marker goes through a save and a fresh open (the
    digest is read from the saved stream) and is still repaired."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"old_saved_{fixture}.pdf"
        saved = Path(tmp) / f"old_saved_{fixture}_out.pdf"
        _make_box_geometry_pdf(path, **_APP_IMAGE_GEOMETRIES["plain"])
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            object_id, stale = _OLD_IMAGE_MARKERS[fixture](model)
            model.save_as(str(saved))
        finally:
            model.close()
        reopened = PDFModel()
        try:
            reopened.open_pdf(str(saved))
            _assert_rect_close(_marker_rect(reopened, object_id), stale)
            (drawn,) = _drawn_image_rects(reopened)
            dest = fitz.Rect(drawn) + (60, 200, 60, 200)
            assert reopened.move_object(MoveObjectRequest(object_id, "image", 1, 1, dest)) is True
            (after,) = _drawn_image_rects(reopened)
            _assert_rect_close(after, dest, tol=0.5)
            _assert_rect_close(_marker_rect(reopened, object_id), after)
            _assert_delete_removes_drawing(reopened, object_id)
        finally:
            reopened.close()
