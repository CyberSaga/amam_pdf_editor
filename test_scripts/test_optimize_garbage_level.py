"""Optimize honours the chosen garbage level (owner decision 2026-11-11)."""
from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "garbage level")
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_fast_save_kwargs_honours_level(level: int) -> None:
    from model.pdf_optimizer import PdfOptimizeOptions, fast_save_kwargs

    assert fast_save_kwargs(PdfOptimizeOptions(garbage_level=level))["garbage"] == level


@pytest.mark.parametrize("level", [0, -3])
def test_level_zero_is_clamped_to_one(level: int) -> None:
    from model.pdf_optimizer import PdfOptimizeOptions, fast_save_kwargs, normalize_optimize_options

    assert fast_save_kwargs(PdfOptimizeOptions(garbage_level=level))["garbage"] == 1
    assert normalize_optimize_options(PdfOptimizeOptions(garbage_level=level)).garbage_level == 1


def test_level_above_four_is_clamped() -> None:
    from model.pdf_optimizer import PdfOptimizeOptions, fast_save_kwargs

    assert fast_save_kwargs(PdfOptimizeOptions(garbage_level=9))["garbage"] == 4


def test_presets_map_to_levels() -> None:
    from model.pdf_model import PDFModel

    assert PDFModel.preset_optimize_options("快速").garbage_level == 1
    assert PDFModel.preset_optimize_options("平衡").garbage_level == 1
    assert PDFModel.preset_optimize_options("極致壓縮").garbage_level == 4


def _optimize_kwargs(tmp_path: Path, level: int, latched: bool) -> list[int]:
    from model.pdf_model import PDFModel, PdfOptimizeOptions
    from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot

    source = _make_pdf(tmp_path / "source.pdf")
    observed: list[int] = []
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        model._sessions_by_id[sid].secure_save_required = latched
        snapshot = capture_optimize_source(model, sid)
        original = model._fast_save_kwargs

        def capture(options):
            kwargs = original(options)
            observed.append(kwargs["garbage"])
            return kwargs

        model._fast_save_kwargs = capture  # type: ignore[method-assign]
        opts = PdfOptimizeOptions(optimize_images=False, garbage_level=level)
        save_optimized_copy_from_snapshot(model, snapshot, str(tmp_path / f"out{level}.pdf"), opts)
    finally:
        model.close()
    return observed


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_non_latched_snapshot_saves_at_chosen_level(tmp_path: Path, level: int) -> None:
    assert _optimize_kwargs(tmp_path, level, latched=False) == [level]


@pytest.mark.parametrize("level", [0, 1, 3])
def test_latched_snapshot_never_below_secure_floor(tmp_path: Path, level: int) -> None:
    from model.pdf_model import SECURE_SAVE_GARBAGE_LEVEL

    assert _optimize_kwargs(tmp_path, level, latched=True) == [max(level, SECURE_SAVE_GARBAGE_LEVEL)]


def test_optimize_level_four_does_not_touch_live_doc(tmp_path: Path) -> None:
    from model.pdf_model import PDFModel, PdfOptimizeOptions
    from model.pdf_optimizer import capture_optimize_source, save_optimized_copy_from_snapshot

    source = _make_pdf(tmp_path / "source.pdf")
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source))
        before = model.doc.xref_length()
        snapshot = capture_optimize_source(model, sid)
        opts = PdfOptimizeOptions(optimize_images=False, garbage_level=4)
        save_optimized_copy_from_snapshot(model, snapshot, str(tmp_path / "o.pdf"), opts)
        assert model.doc.xref_length() == before
    finally:
        model.close()


def test_model_exposes_save_garbage_level(tmp_path: Path) -> None:
    from model.pdf_model import SECURE_SAVE_GARBAGE_LEVEL, PDFModel

    model = PDFModel()
    try:
        model.open_pdf(str(_make_pdf(tmp_path / "s.pdf")))
        assert model.save_garbage_level == 1
        model.secure_save_required = True
        assert model.save_garbage_level == SECURE_SAVE_GARBAGE_LEVEL
    finally:
        model.close()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dialog_slider_default_and_presets(qapp) -> None:
    from model.pdf_model import PDFModel
    from view.pdf_view import OptimizePdfDialog

    d = OptimizePdfDialog(preset_options=PDFModel.preset_optimize_options)
    assert (d.garbage_slider.minimum(), d.garbage_slider.maximum()) == (1, 4)
    assert d.garbage_slider.value() == 1
    assert d.get_options().garbage_level == 1
    d.preset_combo.setCurrentText("極致壓縮")
    assert d.garbage_slider.value() == 4
    assert d.get_options().garbage_level == 4
    d.preset_combo.setCurrentText("快速")
    assert d.garbage_slider.value() == 1
    assert d.get_options().garbage_level == 1


def test_dialog_slider_move_marks_custom_and_updates_caption(qapp) -> None:
    from model.pdf_model import PDFModel
    from view.pdf_view import OptimizePdfDialog

    d = OptimizePdfDialog(preset_options=PDFModel.preset_optimize_options)
    captions = set()
    for level in (2, 3, 4, 1):
        d.garbage_slider.setValue(level)
        assert d.get_options().garbage_level == level
        assert d.preset_combo.currentText() == "自訂"
        captions.add(d.garbage_caption.text())
    assert len(captions) == 4
    d.garbage_slider.setValue(4)
    assert "最慢" in d.garbage_caption.text()


def _make_dialog(monkeypatch, avail: int):
    from model.pdf_model import PDFModel
    from view.dialogs.optimize import OptimizePdfDialog

    monkeypatch.setattr(OptimizePdfDialog, "_available_height", lambda self: avail)
    return OptimizePdfDialog(preset_options=PDFModel.preset_optimize_options)


def test_dialog_fits_small_screen_with_visible_buttons(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    d = _make_dialog(monkeypatch, 600)
    d.show()
    qapp.processEvents()
    assert d.height() <= int(600 * 0.9)
    box = d.findChild(QDialogButtonBox)
    assert box.isVisible()
    assert d.rect().contains(box.mapTo(d, box.rect().topLeft()))
    assert d.rect().contains(box.mapTo(d, box.rect().bottomRight()))
    d.close()


def test_dialog_not_taller_than_content_on_large_screen(qapp, monkeypatch) -> None:
    d = _make_dialog(monkeypatch, 5000)
    assert d.height() <= d._content_needed_height()
    assert d.width() == 560
    d.close()


def test_settings_live_inside_scroll_area(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QScrollArea

    d = _make_dialog(monkeypatch, 600)
    area = d.findChild(QScrollArea)
    assert area is not None and area.widgetResizable()
    assert area.widget().isAncestorOf(d.garbage_slider)
    d.close()
