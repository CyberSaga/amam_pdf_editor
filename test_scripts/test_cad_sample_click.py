"""Card A4 accept: the owner's CAD sample never freezes the window on a click or right-click.

Runs, through the stall harness, a left click in objects mode and a right-click in browse,
objects and text-edit modes on page 1 of ``test_files/cad_vector/before.pdf`` (gitignored).
The longest heartbeat gap must be at most 100 ms on all four; the child's run time (gesture start
until the table analysis settles) is printed with the numbers.

A gesture settles on the coordinator's own answer signal (``CombinedAnswerWatch``: the table answer plus, when the gesture requested
one, the text answer), not on a cache
poll: with the key a hash of a scratch copy, each poll built page copies and inflated the very gap
this test measures.  The child needs free memory; with too little the coordinator answers
``no_headroom``, which marks nothing, and the test fails at once naming it instead of waiting out
the 180 s timeout (2026-11-19).
"""
from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import view.pdf_view as pdf_view
from model import table_objects
from model.pdf_model import PDFModel
from src.render_worker.memory import read_system_memory
from utils import object_probe_platform
from test_scripts.gui_stall_probe import CombinedAnswerWatch, run_gesture

LIMIT_MS = 100.0
SAMPLE = Path(__file__).resolve().parent.parent / "test_files" / "cad_vector" / "before.pdf"

# Gestures over LIMIT_MS on the sample, each with its measured cause.  Empty since A6.5 (2026-11-21):
# the browse right click no longer interprets the page on the GUI thread (child text job, pending menu);
# it was 1437 ms before A6 (cProfile 2026-11-18).
KNOWN_OVER_LIMIT: dict[str, str] = {}


def _pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


@pytest.mark.skipif(
    not object_probe_platform.contained_probe_supported(),
    reason="no contained probe child off Windows: the controller refuses tables, so the click gestures never get a table signal",
)
@pytest.mark.needs_fixtures
@pytest.mark.skipif(not SAMPLE.exists(), reason="owner's CAD sample not present")
def test_cad_sample_click_and_right_click_never_freeze_the_window(qapp, monkeypatch):
    from controller.pdf_controller import PDFController
    from test_scripts.qt_teardown import dispose_pdf_view

    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    monkeypatch.setattr(pdf_view.QMenu, "exec_", lambda self, *a, **k: None)
    model = PDFModel()
    view = pdf_view.PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    results: dict[str, tuple[float, bool]] = {}
    run_ms: dict[str, float] = {}
    statuses: dict[str, str | None] = {}
    starved: str | None = None
    probe = controller._object_probe
    watch = CombinedAnswerWatch(probe, 1)
    try:
        controller.open_pdf(str(SAMPLE))
        view.resize(1200, 900)
        view.show()
        _pump(qapp, 1500)

        page_rect = model.doc[0].rect
        center = fitz.Point(page_rect.width / 2, page_rect.height / 2)
        scene = view._doc_rect_to_scene_rect(0, fitz.Rect(center.x, center.y, center.x + 10, center.y + 10)).center()
        pos = view.graphics_view.mapFromScene(scene)

        gestures = {
            "left click in objects": (
                "objects",
                lambda: QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, pos=pos),
            ),
            "right click in browse": ("browse", lambda: view._show_context_menu(pos)),
            "right click in objects": ("objects", lambda: view._show_context_menu(pos)),
            "right click in text edit": ("text_edit", lambda: view._show_context_menu(pos)),
            # Cold text index (page marked stale); the prewarm runs on the next loop slot, so only the
            # built index settles the gesture (a child answer, or the page state for an inline build).
            "enter text edit mode": ("browse", lambda: view.set_mode("edit_text")),
        }
        for name, (mode, gesture) in gestures.items():
            view.set_mode(mode)
            _pump(qapp, 100)
            table_objects._cache(model).clear()
            watch.reset()
            settled = watch.done
            if name == "enter text edit mode":
                model.block_manager._page_state[0] = "stale"

                def settled():
                    return watch.text.done() or model.block_manager.page_state(0) == "clean"

            t0 = time.perf_counter()
            results[name] = run_gesture(qapp, gesture, settled)
            run_ms[name] = (time.perf_counter() - t0) * 1000.0
            statuses[name] = watch.status
            if watch.status == "no_headroom":
                memory = read_system_memory()
                starved = f"{name}; available memory now {memory.avail_phys >> 20 if memory else '?'} MiB"
                break  # environmental: the remaining gestures would only repeat it
        print(f"A4 STALL {results}")
        print(f"A4 RUN_MS {run_ms}")
        print(f"A4 STATUS {statuses}")
    finally:
        dispose_pdf_view(view, controller, model)
    assert starved is None, (
        f"the object probe answered no_headroom on {starved}: too little free memory to start its child"
        " (environmental, not a stall); free memory and rerun"
    )
    for name, (gap, finished) in results.items():
        assert finished, f"{name}: the gesture did not finish"
    over = {name for name, (gap, _) in results.items() if gap > LIMIT_MS}
    # Strict both ways: a new freeze fails, and so does a known one that got fixed.
    assert over == set(KNOWN_OVER_LIMIT), f"over {LIMIT_MS:.0f} ms: {sorted(over)}; all: {results}"
