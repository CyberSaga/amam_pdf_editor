"""After an undone rebuild the page keeps its layer bindings (real app, real drawing).

Owner report (2026-10-07, part 5 round 5): a consented rebuild (改用重建文字…)
followed by Ctrl+Z left the page in a state where every later true-text edit
was refused ``mc_wrapper_not_pure_layer`` ("圖層結構不支援原位修改"), even a pure
reorder of the run's own characters.  The page-snapshot restore grafted copies
of the page's OCGs (``insert_pdf``) that ``/OCProperties`` does not list; it is
now an in-place write by xref (``model/page_snapshot.py``).

Driven through the real app on a tmp COPY of the gitignored ecc-dwg drawing; CI
deselects this module through the ``needs_fixtures`` marker.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "test_scripts"))

pytestmark = pytest.mark.needs_fixtures

_ECC = ROOT / "test_files" / "ecc-dwg.pdf"
_RUN = "備為C標新設"
_LAYER_CLASS = "oc_layer_visible_default"


def _open_app(monkeypatch, tmp_path: Path):
    if not _ECC.exists():
        pytest.skip("test_files/ecc-dwg.pdf is not available")
    import test_text_commit_ui_real_corpus as ui

    work = tmp_path / "ecc.pdf"
    shutil.copyfile(_ECC, work)
    app = ui._App(monkeypatch, work, shipped=True)
    app.ensure_edit_text_run_mode()
    return app


def _click_run(app):
    with app.snapshot() as doc:
        rect = doc[0].search_for(_RUN)[0]
    editor = app.click_glyph(0, rect)
    app.pump(300)
    return editor


def _page_layer_state(app) -> tuple[int, Counter]:
    from model.text_commit.inspect import replay_page
    from model.text_commit.marked_content import classify_wrappers

    doc = app.model.doc  # read only
    page = doc[0]
    return page.xref, Counter(classify_wrappers(doc, page, replay_page(doc, page)).values())


def _rebuild(app, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import controller.pdf_controller as controller_module

    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", lambda *_a, **_k: True)
    editor = _click_run(app)
    app.type_replacing_all(editor, "2點擊頁面備為C標新設。")
    token, reason = app.wait_preview(editor)
    assert token is None and reason == "type0_unicode_unmapped"
    button = app.view.text_rebuild_btn
    app.wait(lambda: not button.isHidden(), 10)
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
    app.pump(1200)
    assert app.undo_depth() == 1


@pytest.mark.parametrize("path", ["undo", "undo_redo_undo"])
def test_reorder_after_an_undone_rebuild_commits_tier0(monkeypatch, tmp_path, path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from model.text_commit.dto import CommitTier

    app = _open_app(monkeypatch, tmp_path)
    try:
        pristine_xref, pristine_classes = _page_layer_state(app)
        assert pristine_classes[_LAYER_CLASS] > 0 and len(pristine_classes) == 1
        _rebuild(app, monkeypatch)
        app.trigger("_action_undo")
        app.pump(800)
        if path == "undo_redo_undo":
            app.trigger("_action_redo")
            app.pump(800)
            app.trigger("_action_undo")
            app.pump(800)
        assert _page_layer_state(app) == (pristine_xref, pristine_classes)

        editor = _click_run(app)
        orig = editor.property("original_text")
        assert orig == "備為C標新設。"
        app.type_replacing_all(editor, orig.replace("標新設", "設新標"))
        token, reason = app.wait_preview(editor)
        assert token is not None and reason is None
        QTest.mouseClick(app.view.text_apply_btn, Qt.LeftButton)
        app.pump(800)
        assert app.editor() is None
        assert app.undo_depth() == 1
        assert app.model.last_commit_outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
        with app.snapshot() as doc:
            assert "設新標" in doc[0].get_text()
    finally:
        app.close()


def test_growth_after_an_undone_rebuild_is_refused_for_growth_not_layers(
    monkeypatch, tmp_path
) -> None:
    app = _open_app(monkeypatch, tmp_path)
    try:
        _rebuild(app, monkeypatch)
        app.trigger("_action_undo")
        app.pump(800)
        editor = _click_run(app)
        orig = editor.property("original_text")
        app.type_replacing_all(editor, "新" + orig)
        _token, reason = app.wait_preview(editor)
        assert reason == "growth_region_not_blank"
    finally:
        app.close()
