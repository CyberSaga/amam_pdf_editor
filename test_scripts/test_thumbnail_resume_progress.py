"""Thumbnail pass progress survives the visible-render pause (perf pass 2026-11-04).

Every visible render batch (zoom, scroll step, viewport change, F5) pauses the
thumbnail pass and resumes it afterwards.  The resume used to restart at row 0
even when the pass had already finished, so every viewport change re-rendered
every thumbnail of the document.  These tests pin the resume to the first row
not yet rendered for the current (thumbnail generation, render revision).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtGui import QImage

from controller.pdf_controller import PDFController

PAGES = 6


def _controller() -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: PAGES
    controller.model.get_active_session_id.return_value = "sid-1"
    controller.view = MagicMock()
    controller._thumbnail_coordinator = MagicMock()
    controller._thumbnail_resume_pending_by_session = set()
    controller._thumb_gen_by_session = {"sid-1": 5}
    controller._render_gen_by_session = {"sid-1": 7}
    controller._render_revision_by_session = {"sid-1": 3}
    controller._color_profile_for_session = MagicMock(return_value="srgb")
    return controller


def _image() -> QImage:
    image = QImage(4, 4, QImage.Format_RGB888)
    image.fill(0)
    return image


def _consume_rows(controller: PDFController, rows) -> None:
    for row in rows:
        controller._consume_thumbnail_images(row, [_image()])


def _pause_and_resume(controller: PDFController) -> None:
    controller._pause_thumbnails_for_visible_render("sid-1")
    controller._resume_thumbnails_after_visible_render("sid-1", 7)


def test_completed_pass_is_not_restarted_by_a_visible_render(qapp) -> None:
    controller = _controller()
    _consume_rows(controller, range(PAGES))
    assert controller.view.update_thumbnail_batch.call_count == PAGES

    _pause_and_resume(controller)

    controller._thumbnail_coordinator.request.assert_not_called()
    assert "sid-1" not in controller._thumbnail_resume_pending_by_session


def test_interrupted_pass_resumes_at_the_first_unrendered_row(qapp) -> None:
    controller = _controller()
    _consume_rows(controller, range(2))

    _pause_and_resume(controller)

    controller._thumbnail_coordinator.request.assert_called_once_with("sid-1", 5, 2, PAGES, "srgb")


def test_open_background_start_after_a_completed_pass_renders_nothing(qapp) -> None:
    controller = _controller()
    _consume_rows(controller, range(PAGES))

    controller._schedule_thumbnail_batch(0, "sid-1", 5)

    controller._thumbnail_coordinator.request.assert_not_called()


def test_partial_invalidation_window_already_rendered_is_skipped(qapp) -> None:
    controller = _controller()
    _consume_rows(controller, range(4))

    controller._schedule_thumbnail_batch(1, "sid-1", 5, 3)

    controller._thumbnail_coordinator.request.assert_not_called()


def test_new_thumbnail_generation_restarts_from_row_zero(qapp) -> None:
    """Regression guard: an invalidation (new generation) re-renders everything."""
    controller = _controller()
    _consume_rows(controller, range(PAGES))
    controller._thumb_gen_by_session["sid-1"] = 6

    controller._schedule_thumbnail_batch(0, "sid-1", 6)

    controller._thumbnail_coordinator.request.assert_called_once_with("sid-1", 6, 0, PAGES, "srgb")


def test_render_revision_bump_restarts_from_row_zero(qapp) -> None:
    """Regression guard: a render-visible mutation that did not invalidate the
    thumbnails still gets a full re-render on the next resume (as before)."""
    controller = _controller()
    _consume_rows(controller, range(PAGES))
    controller._render_revision_by_session["sid-1"] = 4

    _pause_and_resume(controller)

    controller._thumbnail_coordinator.request.assert_called_once_with("sid-1", 5, 0, PAGES, "srgb")


def test_progress_of_another_session_does_not_leak(qapp) -> None:
    controller = _controller()
    _consume_rows(controller, range(PAGES))
    controller.model.get_active_session_id.return_value = "sid-2"
    controller._thumb_gen_by_session["sid-2"] = 5
    controller._render_revision_by_session["sid-2"] = 3

    controller._schedule_thumbnail_batch(0, "sid-2", 5)

    controller._thumbnail_coordinator.request.assert_called_once_with("sid-2", 5, 0, PAGES, "srgb")
