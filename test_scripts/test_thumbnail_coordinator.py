from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import fitz
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage, QPixmap

import controller.pdf_controller as controller_module
import controller.thumbnail_coordinator as thumbnail_module
from controller.pdf_controller import PDFController
from controller.thumbnail_coordinator import ThumbnailCoordinator, ThumbnailFileSource
from model.pdf_model import PDFModel


def _pump_until(predicate, timeout_ms: int = 3000) -> None:
    loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(timeout_ms)

    def check() -> None:
        if predicate():
            loop.quit()
        else:
            QTimer.singleShot(5, check)

    QTimer.singleShot(0, check)
    loop.exec()


def _image() -> QImage:
    return QImage(2, 2, QImage.Format_RGB888)


def test_superseded_job_is_cancelled_before_new_strategy_is_selected(qapp) -> None:
    selected_after_cancel: list[bool] = []
    coordinator: ThumbnailCoordinator

    def resolve(_request):
        selected_after_cancel.append(not coordinator.has_active_job)
        return None

    coordinator = ThumbnailCoordinator(
        source_resolver=resolve,
        live_renderer=lambda _page, _profile: _image(),
        batch_consumer=lambda *_args: None,
        identity_matches=lambda *_args: True,
    )
    coordinator.request("sid-a", 1, 0, 3, "srgb")
    coordinator.request("sid-b", 1, 0, 1, "srgb")

    assert selected_after_cancel == [True, True]


def test_stale_batch_is_dropped_when_any_identity_component_differs(qapp) -> None:
    painted: list[tuple] = []
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: None,
        live_renderer=lambda _page, _profile: _image(),
        batch_consumer=lambda *args: painted.append(args),
        identity_matches=lambda sid, generation: sid == "sid-b" and generation == 7,
    )
    token = coordinator.request("sid-b", 7, 0, 1, "srgb")

    coordinator._accept_batch("wrong-token", "sid-b", 7, 0, [_image()])
    coordinator._accept_batch(token, "sid-a", 7, 0, [_image()])
    coordinator._accept_batch(token, "sid-b", 6, 0, [_image()])
    coordinator._accept_batch(token, "sid-b", 7, 0, [_image()])

    assert len(painted) == 1
    assert painted[0][:2] == (0, painted[0][1])
    assert isinstance(painted[0][1][0], QImage)


def test_stale_finished_signal_cannot_clear_current_job(qapp) -> None:
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: None,
        live_renderer=lambda _page, _profile: _image(),
        batch_consumer=lambda *_args: None,
        identity_matches=lambda *_args: True,
    )
    token = coordinator.request("sid-current", 9, 0, 1, "srgb")

    coordinator._worker_finished(token, "sid-stale", 9, True)

    assert coordinator.has_active_job


def test_live_fallback_renders_at_most_one_page_before_yielding(qapp) -> None:
    rendered: list[int] = []
    turns: list[int] = []

    def render(page: int, _profile: str) -> QImage:
        rendered.append(page)
        QTimer.singleShot(0, lambda: turns.append(len(rendered)))
        return _image()

    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: None,
        live_renderer=render,
        batch_consumer=lambda *_args: None,
        identity_matches=lambda *_args: True,
    )
    coordinator.request("sid-dirty", 2, 0, 3, "srgb")
    _pump_until(lambda: len(rendered) == 3)

    assert rendered == [0, 1, 2]
    assert turns[:2] == [1, 2]


def test_file_worker_uses_captured_path_and_emits_qimages(qapp, tmp_path: Path) -> None:
    pdf = tmp_path / "clean.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(pdf)
    doc.close()
    stat = pdf.stat()
    source = ThumbnailFileSource(
        path=str(pdf),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        password=None,
    )
    painted: list[tuple[int, list[QImage]]] = []
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: source,
        live_renderer=lambda *_args: (_ for _ in ()).throw(AssertionError("live renderer used")),
        batch_consumer=lambda start, images: painted.append((start, images)),
        identity_matches=lambda sid, generation: sid == "sid-clean" and generation == 3,
    )
    coordinator.request("sid-clean", 3, 0, 2, "srgb")
    _pump_until(lambda: len(painted) == 2)

    assert [start for start, _images in painted] == [0, 1]
    assert all(isinstance(images[0], QImage) for _start, images in painted)
    assert all(not isinstance(images[0], QPixmap) for _start, images in painted)
    assert all(images[0].width() >= 240 for _start, images in painted)
    coordinator.cancel()
    coordinator.wait_for_done()


def test_encrypted_file_worker_authenticates_with_captured_password(qapp, tmp_path: Path) -> None:
    pdf = tmp_path / "encrypted.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(
        pdf,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()
    stat = os.stat(pdf)
    source = ThumbnailFileSource(str(pdf), stat.st_size, stat.st_mtime_ns, "user-secret")
    painted: list[list[QImage]] = []
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: source,
        live_renderer=lambda *_args: (_ for _ in ()).throw(AssertionError("live renderer used")),
        batch_consumer=lambda _start, images: painted.append(images),
        identity_matches=lambda *_args: True,
    )
    coordinator.request("sid-encrypted", 4, 0, 1, "srgb")
    _pump_until(lambda: bool(painted))

    assert isinstance(painted[0][0], QImage)
    coordinator.cancel()
    coordinator.wait_for_done()


def test_controller_routes_thumbnail_range_to_coordinator_without_inline_render(qapp) -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.doc = MagicMock()
    controller.model.doc.__len__ = lambda _self=None: 40
    controller.model.get_active_session_id.return_value = "sid"
    controller.model.get_thumbnail.side_effect = AssertionError("GUI-thread render")
    controller._thumb_gen_by_session = {"sid": 8}
    controller._thumbnail_coordinator = MagicMock()
    controller._color_profile_for_session = MagicMock(return_value="gray")

    controller._schedule_thumbnail_batch(10, "sid", 8, 14)

    controller._thumbnail_coordinator.request.assert_called_once_with("sid", 8, 10, 14, "gray")
    controller.model.get_thumbnail.assert_not_called()


def test_controller_clean_source_resolution_never_captures_snapshot(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"source")
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.get_active_session_id.return_value = "sid"
    controller.model.session_has_unsaved_changes.return_value = False
    controller.model.get_session_meta.return_value = {"path": str(pdf), "saved_path": None}
    controller.model.password = "pw"
    controller.capture_worker_snapshot_bytes = MagicMock(side_effect=AssertionError("snapshot captured"))
    request = MagicMock(session_id="sid")

    source = controller._resolve_thumbnail_file_source(request)

    assert source is not None
    assert source.path == str(pdf)
    assert source.password == "pw"
    controller.capture_worker_snapshot_bytes.assert_not_called()


def test_controller_dirty_source_uses_live_fallback(tmp_path: Path) -> None:
    controller = PDFController.__new__(PDFController)
    controller.model = MagicMock()
    controller.model.get_active_session_id.return_value = "sid"
    controller.model.session_has_unsaved_changes.return_value = True

    assert controller._resolve_thumbnail_file_source(MagicMock(session_id="sid")) is None


def test_changed_file_descriptor_falls_back_to_live_renderer(qapp, tmp_path: Path) -> None:
    pdf = tmp_path / "changed.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf)
    doc.close()
    stat = pdf.stat()
    source = ThumbnailFileSource(str(pdf), stat.st_size, stat.st_mtime_ns, None)
    pdf.write_bytes(pdf.read_bytes() + b"\n")
    live_pages: list[int] = []
    painted: list[list[QImage]] = []
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: source,
        live_renderer=lambda page, _profile: live_pages.append(page) or _image(),
        batch_consumer=lambda _start, images: painted.append(images),
        identity_matches=lambda *_args: True,
    )

    coordinator.request("sid", 1, 0, 1, "srgb")
    _pump_until(lambda: bool(painted))

    assert live_pages == [0]
    coordinator.cancel()
    coordinator.wait_for_done()


def test_app_close_cancels_thumbnail_work_before_accepting(qapp) -> None:
    controller = PDFController.__new__(PDFController)
    controller._thumbnail_coordinator = MagicMock()
    controller._has_active_print_submission = MagicMock(return_value=False)
    controller._has_active_optimize_submission = MagicMock(return_value=False)
    controller.model = MagicMock()
    controller.model.get_dirty_session_ids.return_value = []
    event = MagicMock()

    controller.handle_app_close(event)

    controller._thumbnail_coordinator.cancel.assert_called_once_with()
    controller._thumbnail_coordinator.wait_for_done.assert_called_once_with(1000)
    event.accept.assert_called_once_with()


def test_app_close_stays_pending_while_thumbnail_worker_is_stopping(qapp) -> None:
    controller = PDFController.__new__(PDFController)
    controller._thumbnail_coordinator = MagicMock()
    controller._thumbnail_coordinator.wait_for_done.return_value = False
    event = MagicMock()

    controller.handle_app_close(event)

    event.ignore.assert_called_once_with()
    event.accept.assert_not_called()


# ---- R7-2: background readers of the target are joined before an install ----


def _save_controller(model, coordinator) -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = model
    controller.view = MagicMock()
    controller._thumbnail_coordinator = coordinator
    controller._thumb_gen_by_session = {}
    controller._invalidate_inline_editor_preview = MagicMock()
    controller._refresh_document_tabs = MagicMock()
    controller._update_undo_redo_tooltips = MagicMock()
    controller._schedule_thumbnail_batch = MagicMock()
    return controller


def _hold_worker_inside_a_render(monkeypatch, hold_s: float = 1.0):
    """Make the file worker sit inside a page render (target open) for ``hold_s``."""
    inside = threading.Event()
    real_scale = thumbnail_module.thumbnail_render_scale

    def slow_scale(page):
        inside.set()
        time.sleep(hold_s)
        return real_scale(page)

    monkeypatch.setattr(thumbnail_module, "thumbnail_render_scale", slow_scale)
    return inside


def _clean_pdf_with_active_file_worker(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hello", fontsize=12.0)
    doc.new_page()
    doc.save(pdf)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(pdf))
    model.use_incremental_save = True
    # The round-6 orphan fallback: the save takes the install-over-open-file path.
    monkeypatch.setattr(model, "_session_orphans_block_incremental", lambda: True)
    stat = pdf.stat()
    source = ThumbnailFileSource(str(pdf), stat.st_size, stat.st_mtime_ns, None)
    coordinator = ThumbnailCoordinator(
        source_resolver=lambda _request: source,
        live_renderer=lambda *_args: _image(),
        batch_consumer=lambda *_args: None,
        identity_matches=lambda *_args: True,
    )
    return pdf, model, coordinator


@contextlib.contextmanager
def _saving_over_an_open_target(
    tmp_path: Path, monkeypatch
) -> Iterator[tuple[Path, PDFModel, PDFController, list[str]]]:
    """A clean document whose thumbnail file worker is inside a page render (the target open) when
    the caller saves over it.  Yields ``(pdf, model, controller, errors)``, ``errors`` collecting every
    ``show_error``; the worker is cancelled and joined and the model closed on exit."""
    inside = _hold_worker_inside_a_render(monkeypatch)
    pdf, model, coordinator = _clean_pdf_with_active_file_worker(tmp_path, monkeypatch)
    errors: list[str] = []
    monkeypatch.setattr(controller_module, "show_error", lambda _view, msg: errors.append(str(msg)))
    controller = _save_controller(model, coordinator)
    try:
        coordinator.request(model.get_active_session_id(), 1, 0, 2, "srgb")
        assert inside.wait(5.0), "the file worker never reached a page render"
        yield pdf, model, controller, errors
    finally:
        coordinator.cancel()
        coordinator.wait_for_done()
        model.close()


def test_save_joins_the_thumbnail_file_worker_before_installing_over_the_target(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *_a, **_k: None)
    with _saving_over_an_open_target(tmp_path, monkeypatch) as (pdf, model, controller, errors):
        controller.save()

        assert errors == [], "the app's own thumbnail worker must not make the save fail"
        assert Path(model.doc.name).resolve() == pdf.resolve(), "the session must stay on the target"


def test_save_as_joins_the_thumbnail_file_worker_before_installing_over_the_target(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    with _saving_over_an_open_target(tmp_path, monkeypatch) as (pdf, model, controller, errors):
        controller.save_as(str(pdf))

        assert errors == []
        assert Path(model.doc.name).resolve() == pdf.resolve()


def _recording_controller(order: list[str], *, active_job: bool, joined: bool = True) -> PDFController:
    coordinator = MagicMock()
    coordinator.has_active_job = active_job
    coordinator.cancel.side_effect = lambda *_a: order.append("cancel")
    coordinator.wait_for_done.side_effect = lambda *_a: order.append("join") or joined
    model = MagicMock()
    model.saved_path = "doc.pdf"
    model.original_path = "doc.pdf"
    model.get_active_session_id.return_value = "sid-a"
    model.get_session_meta.return_value = {"saved_path": "doc.pdf"}
    model.save_as.side_effect = lambda *_a: order.append("save")
    model.save_session_as.side_effect = lambda *_a: order.append("save_session")
    controller = _save_controller(model, coordinator)
    controller._thumb_gen_by_session = {"sid-a": 5}
    controller._schedule_thumbnail_batch = MagicMock(
        side_effect=lambda *args: order.append(f"resume{args}")
    )
    return controller


def test_save_releases_readers_first_then_resumes_an_interrupted_job(qapp, monkeypatch) -> None:
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *_a, **_k: None)
    order: list[str] = []
    controller = _recording_controller(order, active_job=True)

    controller.save()

    assert order == ["cancel", "join", "save", "resume(0, 'sid-a', 5)"]


def test_save_does_not_start_thumbnails_when_none_were_running(qapp, monkeypatch) -> None:
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *_a, **_k: None)
    order: list[str] = []
    controller = _recording_controller(order, active_job=False)

    controller.save()

    assert order == ["cancel", "join", "save"]


def test_save_still_attempts_the_save_when_the_worker_does_not_stop_in_time(qapp, monkeypatch) -> None:
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *_a, **_k: None)
    order: list[str] = []
    controller = _recording_controller(order, active_job=False, joined=False)

    controller.save()

    assert order == ["cancel", "join", "save"]


def test_a_failed_save_still_resumes_the_interrupted_thumbnail_job(qapp, monkeypatch) -> None:
    monkeypatch.setattr(controller_module, "show_error", lambda *_a, **_k: None)
    order: list[str] = []
    controller = _recording_controller(order, active_job=True)
    controller.model.save_as.side_effect = OSError("disk full")

    controller.save_as("doc.pdf")

    assert order == ["cancel", "join", "resume(0, 'sid-a', 5)"]


def test_closing_a_background_tab_saves_after_the_readers_are_joined(qapp) -> None:
    order: list[str] = []
    controller = _recording_controller(order, active_job=True)

    assert controller._save_session_for_close("sid-b") is True

    assert order == ["cancel", "join", "save_session", "resume(0, 'sid-a', 5)"]


def test_closing_the_active_tab_does_not_restart_thumbnails_for_it(qapp) -> None:
    order: list[str] = []
    controller = _recording_controller(order, active_job=True)

    assert controller._save_session_for_close("sid-a") is True

    assert order == ["cancel", "join", "save_session"]


def test_close_dialog_save_joins_readers_before_the_model_save(qapp, monkeypatch) -> None:
    monkeypatch.setattr(
        controller_module.QFileDialog, "getSaveFileName", lambda *_a, **_k: ("doc.pdf", "")
    )
    order: list[str] = []
    controller = _recording_controller(order, active_job=False)

    assert controller._save_session_with_dialog("sid-a") is True

    assert order == ["cancel", "join", "save_session"]


def test_merge_export_joins_readers_before_writing_the_output(qapp) -> None:
    order: list[str] = []
    controller = _recording_controller(order, active_job=False)
    merged = MagicMock()
    controller.model.compose_merged_document.return_value = merged
    controller.model.save_external_document.side_effect = lambda *_a: order.append("export")
    controller.open_pdf = MagicMock(side_effect=lambda *_a: order.append("open"))

    controller.save_ordered_sources_as_new([{"path": "a.pdf"}], "out.pdf")

    assert order == ["cancel", "join", "export", "open"]
    merged.close.assert_called_once_with()
