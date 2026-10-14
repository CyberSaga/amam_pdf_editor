"""Round 4 real-IME acceptance fixes, driven through the real app.

The app is launched exactly as for a user (``main.run`` via the umbrella's
``_App`` harness) on a tmp COPY of the gitignored ecc-dwg drawing; the original
under ``test_files/`` is never modified.  The IME commit is a
``QInputMethodEvent`` commit string, as 新注音 sends it.  CI deselects this module
through the ``needs_fixtures`` marker (the drawing is gitignored).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "test_scripts"))

pytestmark = pytest.mark.needs_fixtures

_ECC = ROOT / "test_files" / "ecc-dwg.pdf"
#: The note run under the cloud-line legend (a Type0 run whose new glyphs the
#: font cannot map, so a CJK commit is refused by the plan preview).
_RUN = "備為C標新設"
_COMMIT = "點擊頁面"


def _open_refused_editor(monkeypatch, tmp_path: Path, *, prepare=None, probe=None):
    """Open the real app on a copy, commit an unmappable IME string into the
    run and wait for the plan-preview refusal.  Returns (app, editor).

    ``prepare(app)`` runs right after the app is up (before the editor opens);
    ``probe(app, editor)`` runs with the freshly opened, untouched editor and
    its return value is stored as ``app.before``."""
    if not _ECC.exists():
        pytest.skip("test_files/ecc-dwg.pdf is not available")
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication

    import test_text_commit_ui_real_corpus as ui

    work = tmp_path / "ecc.pdf"
    shutil.copyfile(_ECC, work)
    app = ui._App(monkeypatch, work, shipped=True)
    try:
        if prepare is not None:
            prepare(app)
        app.ensure_edit_text_run_mode()
        with app.snapshot() as doc:
            rect = doc[0].search_for(_RUN)[0]
        editor = app.click_glyph(0, rect)
        app.pump(200)
        app.before = probe(app, editor) if probe is not None else None
        event = QInputMethodEvent("", [])
        event.setCommitString(_COMMIT)
        QApplication.sendEvent(editor, event)
        assert app.wait(lambda: editor.plan_rejection_reason() is not None, 10)
        app.pump(100)
    except BaseException:
        app.close()
        raise
    return app, editor


def test_a_refused_ime_commit_repaints_the_refusal_badge(
    tmp_path: Path, monkeypatch
) -> None:
    """RED before R4-1: after the refusal the viewport was pixel-identical to the
    frozen original (no badge) and still reported 預覽更新中."""
    from PySide6.QtGui import QImage

    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        assert editor.plan_rejection_reason() is not None
        frozen = editor._frozen_first_frame_image
        assert frozen is not None
        painted = editor.viewport().grab().toImage()
        assert painted != frozen.convertToFormat(painted.format()), (
            "the refused input painted the bare frozen frame"
        )
        assert editor.plan_preview_badge_text() == "無法套用"
        assert editor.plan_preview_refused() is True
        assert editor.plan_preview_pending() is False
        assert isinstance(painted, QImage)
    finally:
        app.close()


# ---------------------------------------------------------------- R4-5 latency


def test_a_slow_refusal_is_repainted_with_the_refusal_badge(
    tmp_path: Path, monkeypatch
) -> None:
    """R4-5: the measured pipeline is ~0.2 s; the ~8 s the owner saw was a
    stale 預覽更新中 badge that nothing repainted after the refusal.  A slow
    worker (0.4 s sleep inside the real render) makes the 150 ms debounce
    repaint land well BEFORE the result, so the refusal itself must schedule a
    full repaint.  RED before R4-1: only the cursor-blink rect was painted
    after the refusal and the badge still read 預覽更新中."""
    import time

    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication

    if not _ECC.exists():
        pytest.skip("test_files/ecc-dwg.pdf is not available")

    import test_text_commit_ui_real_corpus as ui
    from model.text_commit.preview import PlanPreviewRenderer

    real_render = PlanPreviewRenderer.render

    def _slow_render(self, request):
        time.sleep(0.4)  # on the preview worker thread, never the GUI thread
        return real_render(self, request)

    monkeypatch.setattr(PlanPreviewRenderer, "render", _slow_render)

    class _Paints(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[tuple[float, object]] = []

        def eventFilter(self, obj, event):  # noqa: N802 - Qt override
            if event.type() == QEvent.Paint:
                self.records.append((time.monotonic(), event.region().boundingRect()))
            return False

    work = tmp_path / "ecc.pdf"
    shutil.copyfile(_ECC, work)
    app = ui._App(monkeypatch, work, shipped=True)
    try:
        app.ensure_edit_text_run_mode()
        with app.snapshot() as doc:
            rect = doc[0].search_for(_RUN)[0]
        editor = app.click_glyph(0, rect)
        app.pump(200)
        paints = _Paints()
        editor.viewport().installEventFilter(paints)
        event = QInputMethodEvent("", [])
        event.setCommitString(_COMMIT)
        QApplication.sendEvent(editor, event)
        assert app.wait(lambda: editor.plan_rejection_reason() is not None, 10)
        t_rejected = time.monotonic()
        app.pump(400)

        viewport_rect = editor.viewport().rect()
        after = [r for t, r in paints.records if t >= t_rejected]
        assert any(r.contains(viewport_rect) for r in after), (
            f"no full repaint after the refusal; paints after it: {after}"
        )
        assert editor.plan_preview_badge_text() == "無法套用"
        frozen = editor._frozen_first_frame_image
        assert frozen is not None
        painted = editor.viewport().grab().toImage()
        assert painted != frozen.convertToFormat(painted.format())
    finally:
        app.close()


# ---------------------------------------------------------------- R4-2 inline bar


def _editor_viewport_rect(view):
    """The editor's rect in graphics_view.viewport() coordinates."""
    proxy = view.text_editor
    return view.graphics_view.mapFromScene(
        proxy.mapRectToScene(proxy.boundingRect())
    ).boundingRect()


def _bar_rect(view):
    return view.text_action_bar.geometry()


def _has_ancestor(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def test_inline_bar_is_a_viewport_child_and_shows_the_refusal(
    tmp_path: Path, monkeypatch
) -> None:
    """RED before R4-2: Apply lived in the right sidebar text card."""
    import os

    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        view = app.view
        viewport = view.graphics_view.viewport()
        assert _has_ancestor(view.text_apply_btn, viewport)
        assert not _has_ancestor(view.text_apply_btn, view.right_sidebar)
        bar = view.text_action_bar
        assert bar.isVisible()
        assert viewport.rect().contains(_bar_rect(view))
        assert not _bar_rect(view).intersects(_editor_viewport_rect(view))
        assert "原字型沒有這個字" in view.text_plan_status_label.text()
        assert not view.text_plan_status_label.isHidden()
        assert not view.text_rebuild_btn.isHidden()
        assert view.text_cancel_btn.isEnabled()
        assert not view.text_apply_btn.isEnabled()
        shot_dir = os.environ.get("R4_SHOT_DIR")
        if shot_dir:
            view.grab().save(str(Path(shot_dir) / "r42_refused_bar.png"))
    finally:
        app.close()


def test_inline_bar_visible_with_right_sidebar_dragged_to_zero(
    tmp_path: Path, monkeypatch
) -> None:
    """RED before R4-2: the owner's sidebar was 0 px and Apply was invisible."""

    def _collapse(app) -> None:
        splitter = app.view.main_splitter
        sizes = splitter.sizes()
        total = sum(sizes)
        splitter.setSizes([sizes[0], total - sizes[0], 0])
        app.pump(100)

    app, editor = _open_refused_editor(monkeypatch, tmp_path, prepare=_collapse)
    try:
        view = app.view
        assert view.main_splitter.sizes()[-1] == 0
        assert not view.text_apply_btn.visibleRegion().isEmpty()
        assert not view.text_cancel_btn.visibleRegion().isEmpty()
        assert not view.text_plan_status_label.visibleRegion().isEmpty()
    finally:
        app.close()


def test_bar_clicks_never_finalize_or_move_focus(tmp_path: Path, monkeypatch) -> None:
    """RED before R4-2 (no bar).  Clicks on the disabled Apply, the rebuild
    button (consent mocked to No by the harness) and the bar background must
    not finalize the editor (CLICK_AWAY / FOCUS_OUTSIDE) nor move focus."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import view.text_editing as te

    finalizes: list[str] = []
    original = te.TextEditManager.finalize_text_edit

    def _spy(self, reason=te.TextEditFinalizeReason.CLICK_AWAY, **kwargs):
        finalizes.append(reason.value)
        return original(self, reason, **kwargs)

    monkeypatch.setattr(te.TextEditManager, "finalize_text_edit", _spy)
    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        view = app.view
        focus_changes: list[tuple] = []
        app.app.focusChanged.connect(lambda old, new: focus_changes.append((old, new)))
        finalizes.clear()
        bar = view.text_action_bar
        assert not view.text_apply_btn.isEnabled()
        QTest.mouseClick(view.text_apply_btn, Qt.LeftButton)
        app.pump(100)
        QTest.mouseClick(view.text_rebuild_btn, Qt.LeftButton)
        app.pump(200)
        QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, QPoint(bar.width() - 3, 3))
        app.pump(300)
        bad = [r for r in finalizes if r in ("click_away", "focus_outside")]
        assert bad == [], finalizes
        assert focus_changes == []
        assert app.editor() is editor
        assert view._is_scene_focus_within_editor()
        before = editor.toPlainText()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_X)
        app.pump(100)
        assert editor.toPlainText() != before
    finally:
        app.close()


def test_bar_follows_scroll_and_hides_with_the_editor(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        view = app.view
        gv = view.graphics_view
        bar = view.text_action_bar
        assert bar.isVisible()
        center = view.text_editor.sceneBoundingRect().center()

        # A smaller window gives the view scroll range (the page fits otherwise).
        view.resize(700, 450)
        app.pump(200)
        gv.centerOn(center)
        app.pump(100)
        scrollbars = [
            sb for sb in (gv.verticalScrollBar(), gv.horizontalScrollBar())
            if sb.maximum() > sb.minimum()
        ]
        assert scrollbars, "no scroll range after shrinking the window"
        assert bar.isVisible()
        offset = bar.pos() - _editor_viewport_rect(view).bottomRight()
        sb = scrollbars[0]
        start = sb.value()
        sb.setValue(start + 20 if start + 20 <= sb.maximum() else start - 20)
        app.pump(100)
        assert bar.isVisible()
        assert bar.pos() - _editor_viewport_rect(view).bottomRight() == offset

        # Scroll the editor out of the viewport: the bar hides.
        hidden = False
        for candidate in scrollbars:
            for target in (candidate.maximum(), candidate.minimum()):
                candidate.setValue(target)
                app.pump(100)
                if not _editor_viewport_rect(view).intersects(gv.viewport().rect()):
                    hidden = True
                    break
            if hidden:
                break
        assert hidden, "could not scroll the editor out of the viewport"
        assert bar.isHidden()
        # Scroll back: shown again.
        gv.centerOn(center)
        app.pump(100)
        assert bar.isVisible()

        # Window resize keeps the bar inside the viewport.
        view.resize(900, 700)
        app.pump(200)
        if _editor_viewport_rect(view).intersects(gv.viewport().rect()):
            assert bar.isVisible()
            assert gv.viewport().rect().contains(_bar_rect(view))
        else:
            assert bar.isHidden()

        # Escape tears the editor down and the bar goes with it.
        gv.centerOn(view.text_editor.sceneBoundingRect().center())
        app.pump(100)
        QTest.keyClick(app.editor(), Qt.Key_Escape)
        app.pump(200)
        assert app.editor() is None
        assert bar.isHidden()
    finally:
        app.close()


def test_bar_does_not_move_the_editor(tmp_path: Path, monkeypatch) -> None:
    def _probe(app, editor):
        proxy = app.view.text_editor
        return (proxy.scenePos(), editor.size())

    app, editor = _open_refused_editor(monkeypatch, tmp_path, probe=_probe)
    try:
        proxy = app.view.text_editor
        assert app.view.text_action_bar.isVisible()
        assert (proxy.scenePos(), editor.size()) == app.before
    finally:
        app.close()


def test_apply_through_the_bar_commits_a_verified_edit_once(
    tmp_path: Path, monkeypatch
) -> None:
    """GUARD (green before and after): the bar's Apply is the old Apply."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        view = app.view
        text = editor.property("original_text")
        assert "標新設" in text, text
        app.type_replacing_all(editor, text.replace("標新設", "設新標"))
        token, reason = app.wait_preview(editor)
        assert token is not None, reason
        assert app.wait(view.text_apply_btn.isEnabled, 5)
        before = len(app.live_commits())
        QTest.mouseClick(view.text_apply_btn, Qt.LeftButton)
        app.pump(600)
        assert len(app.live_commits()) == before + 1
        result = view._last_text_edit_finalize_result
        assert result is not None and result.reason.value == "apply"
        assert app.editor() is None
        assert view.text_action_bar.isHidden()
    finally:
        app.close()


def test_bar_follows_a_resize_that_only_recenters_the_scene(
    tmp_path: Path, monkeypatch
) -> None:
    """RED before the deferred reposition: with the whole page fitting in the
    viewport (scroll range 0) a resize only re-centres the scene, so no
    scrollbar ``valueChanged`` fires.  The filter ran before QGraphicsView
    re-centred, so the bar kept the stale position and overlapped the editor."""
    app, editor = _open_refused_editor(monkeypatch, tmp_path)
    try:
        view = app.view
        bar = view.text_action_bar
        view.resize(2600, 1100)
        app.pump(300)
        view._position_text_action_bar()
        assert bar.isVisible()
        offset = bar.pos() - _editor_viewport_rect(view).bottomRight()
        for size in ((2600, 1130), (2600, 1300), (2900, 1300), (2600, 1100)):
            view.resize(*size)
            app.pump(300)
            assert bar.isVisible(), size
            editor_rect = _editor_viewport_rect(view)
            assert not bar.geometry().intersects(editor_rect), size
            assert bar.pos() - editor_rect.bottomRight() == offset, size
    finally:
        app.close()
