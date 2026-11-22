"""Card A3 accept (H5): a click or right-click on a path-heavy page never freezes the window.

Every gesture runs to completion (the child's answer is applied) with a longest heartbeat gap of
at most 100 ms.  The fixtures are built here: a page that is only ``/Fm0 Do`` with 200,000 paths in
the form, a 200,000-path page, and a page with three 4,000 x 4,000 images.
"""
from __future__ import annotations

import time

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import view.pdf_view as pdf_view
from model import table_objects
from model.pdf_model import PDFModel
from utils import object_probe_platform
from test_scripts import gui_stall_probe
from test_scripts.gui_stall_probe import CombinedAnswerWatch, run_gesture

LIMIT_MS = 100.0
PATHS = 200_000

# Gestures that still exceed LIMIT_MS after card A3, each with its cause outside A3's design
# (reported to the owner; the card's accept line is NOT met for these).
# Since A6.8 the gestures settle on the coordinator's answer signals (CombinedAnswerWatch), not on a
# table-cache poll, so no poll builds a scratch copy inside the measured gap.  What is left on the
# images page is the gesture's own bytes-key scratch copy (owner Q1, plans/cad-a6-text-offload-design.md).
_IMAGE_TABLE_KEY = (
    "bytes-key copy (F1), owner Q1: no cheaper exact-bytes copy exists (measured 2026-11-21: "
    "insert_pdf 31 + tobytes 62 + sha256 10 ms on the 48 MB page; Astra and the owner agreed)"
)
KNOWN_OVER_LIMIT = {
    ("images", "left click in objects"): _IMAGE_TABLE_KEY,
    ("images", "right click in browse"): _IMAGE_TABLE_KEY,
    ("images", "right click in objects"): _IMAGE_TABLE_KEY,
    ("images", "right click in text edit"): _IMAGE_TABLE_KEY,
}


def _path_stream(count: int) -> bytes:
    lines = []
    for i in range(count):
        x = 10 + (i * 7919) % 560
        y = 10 + (i * 104729) % 800
        lines.append(f"{x} {y} m {x + 3} {y + 4} l S")
    return ("0.2 w\n" + "\n".join(lines)).encode("ascii")


def _set_contents(doc: fitz.Document, page: fitz.Page, data: bytes) -> None:
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, data)
    page.set_contents(xref)


def build_form_page(path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        form = doc.get_new_xref()
        doc.update_object(
            form,
            "<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] /Resources << >> >>",
        )
        doc.update_stream(form, _path_stream(PATHS))
        doc.xref_set_key(page.xref, "Resources", f"<< /XObject << /Fm0 {form} 0 R >> >>")
        _set_contents(doc, page, b"/Fm0 Do")
        doc.save(path)


def build_path_page(path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _set_contents(doc, page, _path_stream(PATHS))
        doc.save(path)


def build_image_page(path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        for i in range(3):
            pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 4000, 4000), False)
            pix.clear_with(80 + i * 40)
            page.insert_image(fitz.Rect(50, 50 + i * 250, 250, 250 + i * 250), pixmap=pix)
        doc.save(path)


BUILDERS = {"form": build_form_page, "paths": build_path_page, "images": build_image_page}


def _pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


@pytest.mark.skipif(
    not object_probe_platform.contained_probe_supported(),
    reason="no contained probe child off Windows: the controller refuses tables, so the click gestures never get a table signal",
)
@pytest.mark.parametrize("fixture", sorted(BUILDERS))
def test_click_and_right_click_never_freeze_the_window(qapp, tmp_path, monkeypatch, fixture):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view

    path = tmp_path / f"{fixture}.pdf"
    BUILDERS[fixture](path)
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QMenu, "exec_", lambda self, *a, **k: None)
    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    results: dict[str, tuple[float, bool]] = {}
    unsuccessful: dict[str, str] = {}
    try:
        controller.open_pdf(str(path))
        view.resize(1200, 900)
        view.show()
        _pump(qapp, 1500)

        scene = view._doc_rect_to_scene_rect(0, fitz.Rect(300, 400, 310, 410)).center()
        pos = view.graphics_view.mapFromScene(scene)

        def cold():
            table_objects._cache(model).clear()

        probe = controller._object_probe
        watch = CombinedAnswerWatch(probe, 1)

        def text_index_built():
            # A child-routed page answers on text_index_ready; a small page is built inline in the
            # prewarm slot and answers nothing, so the page state (a dict read) is the other signal.
            # (only a stop-waiting condition: acceptance below reads the text status, H23)
            return gui_stall_probe.text_entry_settled(watch, model.block_manager.page_state(0))

        def stale_text_index():
            model.block_manager._page_state[0] = "stale"

        # name -> (mode to sit in first, gesture, settle predicate, prep run before the gesture)
        gestures = {
            "left click in objects": (
                "objects",
                lambda: QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, pos=pos),
                watch.done,
                None,
            ),
            "right click in browse": ("browse", lambda: view._show_context_menu(pos), watch.done, None),
            "right click in objects": ("objects", lambda: view._show_context_menu(pos), watch.done, None),
            "right click in text edit": ("text_edit", lambda: view._show_context_menu(pos), watch.done, None),
            # The text index is cold (page marked stale); the entry's prewarm runs on the next loop slot,
            # so nothing is pending yet when the gesture returns: only the built index settles it.
            "enter text edit mode": ("browse", lambda: view.set_mode("edit_text"), text_index_built, stale_text_index),
        }
        for name, (mode, gesture, settled, prep) in gestures.items():
            view.set_mode(mode)
            _pump(qapp, 100)
            cold()
            if prep is not None:
                prep()
            watch.reset()
            results[name] = run_gesture(qapp, gesture, settled)
            # done() is also true on a failure or a drop: acceptance reads the status (H23).
            if name == "enter text edit mode":
                failure = gui_stall_probe.text_entry_acceptance_failure(watch, model.block_manager.page_state(0))
            else:
                failure = gui_stall_probe.table_acceptance_failure(watch)
            if failure is not None:
                unsuccessful[name] = failure
        print(f"STALL {fixture}: {results}")
    finally:
        dispose_pdf_view(view, controller, model)
    assert not unsuccessful, f"{fixture}: gestures that settled on a failure: {unsuccessful}"
    for name, (gap, finished) in results.items():
        assert finished, f"{fixture} / {name}: the gesture did not finish"
    over = {(fixture, name) for name, (gap, _) in results.items() if gap > LIMIT_MS}
    expected = {key for key in KNOWN_OVER_LIMIT if key[0] == fixture}
    # Strict both ways: a new freeze fails, and so does a known one that got fixed (then drop it
    # from KNOWN_OVER_LIMIT).
    assert over == expected, f"over {LIMIT_MS:.0f} ms: {sorted(over)}; known: {sorted(expected)}; all: {results}"
