"""Card A5 accept (H5, H17): a 200,000-path page that holds one image stays live.

The click is answered by the real object-probe child (limit 100 ms on the GUI thread); each edit and
its undo run on a warm scan with a longest heartbeat gap of at most Q1 (1 s).  ``parse_operators`` is
patched to raise on inputs over 65,536 bytes: the edits must never tokenise the whole stream.
"""
from __future__ import annotations

import time

import fitz
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import view.pdf_view as pdf_view
from model import pdf_content_ops, pdf_object_ops
from model.content_scan import clear_scan_cache
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest
from model.pdf_model import PDFModel
from test_scripts.gui_stall_probe import run_gesture
from test_scripts.test_gui_stall import PATHS, _path_stream

CLICK_LIMIT_MS = 100.0
EDIT_LIMIT_MS = 1000.0  # Q1
WHOLE_STREAM = 65536

# Card D9 (zlib level-1 splice writer) took the four edits from ~1.1-1.6 s to ~0.40-0.42 s and card
# D10 (lazy placements) took get_image_rects out of the click (2026-11-20, a warm 200,000-path page).
# The click's last cost was the page scan set: page_scan_set decoded and hashed the 4.3 MB stream 4
# times in one synchronous click (~80 of ~113 ms, cProfile); one shared ``PageScanSet`` per click
# (A5 review item 6) took the click to ~20 ms of work and ~75 ms measured here, so no gesture is
# listed as over its limit any more.
KNOWN_OVER_LIMIT: dict[str, str] = {}


def _build(path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
        pix.clear_with(120)
        page.insert_image(fitz.Rect(300, 400, 400, 470), pixmap=pix)
        name = str(page.get_images(full=True)[0][7])
        xrefs = [int(x) for x in page.get_contents()]
        doc.update_stream(
            xrefs[0],
            _path_stream(PATHS) + f"\nq 100 0 0 70 300 372 cm /{name} Do Q\n".encode("ascii"),
        )
        for extra in xrefs[1:]:
            doc.update_stream(extra, b" ")
        doc.save(path)


def _pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_click_edits_and_undo_never_freeze_the_window(qapp, tmp_path, monkeypatch):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view

    clear_scan_cache()
    path = tmp_path / "heavy_image.pdf"
    _build(path)
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    results: dict[str, tuple[float, bool]] = {}
    try:
        controller.open_pdf(str(path))
        view.resize(1200, 900)
        view.show()
        _pump(qapp, 1500)
        view.set_mode("objects")
        _pump(qapp, 100)

        def guard(real):
            def checked(stream):
                if len(stream) > WHOLE_STREAM:
                    raise AssertionError("parse_operators reached on a whole stream")
                return real(stream)

            return checked

        monkeypatch.setattr(pdf_content_ops, "parse_operators", guard(pdf_content_ops.parse_operators))
        monkeypatch.setattr(pdf_object_ops, "parse_operators", guard(pdf_object_ops.parse_operators))

        scene = view._doc_rect_to_scene_rect(0, fitz.Rect(345, 430, 355, 440)).center()
        pos = view.graphics_view.mapFromScene(scene)
        results["click"] = run_gesture(
            qapp,
            lambda: QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, pos=pos),
            lambda: not model.image_scan_jobs(1),
        )
        _pump(qapp, 200)
        assert model.image_scan_jobs(1) == []

        def stream() -> bytes:
            return model.doc.xref_stream(int(model.doc[0].get_contents()[0]))

        object_id = "native_image:1:0"
        rect = fitz.Rect(320, 420, 440, 500)
        edits = {
            "move": lambda: controller.move_object(MoveObjectRequest(object_id, "native_image", 1, 1, rect)),
            "resize": lambda: controller.resize_object(ResizeObjectRequest(object_id, "native_image", 1, rect)),
            "rotate": lambda: controller.rotate_object(RotateObjectRequest(object_id, "native_image", 1, 90)),
            "delete": lambda: controller.delete_object(DeleteObjectRequest(object_id, "native_image", 1)),
        }
        for name, edit in edits.items():
            before = stream()
            results[name] = run_gesture(qapp, edit, lambda: True)
            assert stream() != before, f"{name} changed nothing: {model.last_object_op_refusal}"
            results[f"undo {name}"] = run_gesture(qapp, controller.undo, lambda: True)
            assert stream() == before, f"undo {name} did not restore the stream"
        print(f"STALL native image page: {results}")
    finally:
        dispose_pdf_view(view, controller, model)
    for name, (gap, finished) in results.items():
        assert finished, f"{name}: the gesture did not finish"
    limits = {name: (CLICK_LIMIT_MS if name == "click" else EDIT_LIMIT_MS) for name in results}
    over = {name for name, (gap, _) in results.items() if gap > limits[name]}
    # A gesture may exceed its limit only for a cause listed here (reported to the owner: the card's
    # accept line is NOT met for it).  Not strict the other way: a faster machine may pass the click.
    # The four edits and their undos carry no entry: they must stay within Q1.
    assert over <= set(KNOWN_OVER_LIMIT), f"new freeze: {sorted(over - set(KNOWN_OVER_LIMIT))}; all: {results}"
