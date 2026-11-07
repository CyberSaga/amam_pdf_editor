from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPalette, QRegion
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QTabBar,
    QWidget,
)

from view.pdf_view import PDFView
from view.text_inline_action_bar import TextInlineActionBar

# Characters the UI font (Microsoft JhengHei UI) draws itself. Anything else in a
# startup widget makes Qt search every system font on first layout, a ~0.6 s GUI
# freeze (PITFALLS: startup glyph fallback). Blocks listed here were measured cheap.
_SAFE_RANGES = (
    (0x0000, 0x024F),  # Latin
    (0x2000, 0x206F),  # general punctuation
    (0x2190, 0x2193),  # plain arrows
    (0x2261, 0x2261),  # identical to
    (0x25A0, 0x25A0),  # black square
    (0x25B2, 0x25B2),  # black up-pointing triangle
    (0x2605, 0x2605),  # black star
    (0x2500, 0x2500),  # box drawings light horizontal
    (0x3000, 0x30FF),  # CJK symbols, kana
    (0x4E00, 0x9FFF),  # CJK ideographs
    (0xFF00, 0xFFEF),  # fullwidth forms
)


def _needs_fallback(ch: str) -> bool:
    code = ord(ch)
    return not any(low <= code <= high for low, high in _SAFE_RANGES)


def _texts(root: QWidget) -> list[str]:
    values: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, QLabel | QAbstractButton):
            values.append(widget.text())
        if isinstance(widget, QLineEdit):
            values.extend([widget.text(), widget.placeholderText()])
        if isinstance(widget, QComboBox):
            values.extend(widget.itemText(i) for i in range(widget.count()))
        if isinstance(widget, QTabBar):
            values.extend(widget.tabText(i) for i in range(widget.count()))
    values.extend(action.text() for action in root.findChildren(QAction))
    return values


def test_startup_widget_text_needs_no_system_font_search(qapp):
    view = PDFView(defer_heavy_panels=False)
    try:
        offenders = sorted({ch for text in _texts(view) for ch in text if _needs_fallback(ch)})
        assert offenders == [], [f"U+{ord(ch):04X}" for ch in offenders]
    finally:
        view.deleteLater()
        qapp.processEvents()


def test_move_grip_text_needs_no_system_font_search(qapp):
    bar = TextInlineActionBar()
    try:
        assert [ch for ch in bar.move_grip.text() if _needs_fallback(ch)] == []
        assert "移動" in bar.move_grip.text()
    finally:
        bar.deleteLater()
        qapp.processEvents()


def test_the_guard_flags_the_glyphs_that_caused_the_freeze():
    assert all(_needs_fallback(ch) for ch in "\u21ba\u21bb\u283f")
    assert not any(_needs_fallback(ch) for ch in "復原重做移動\u2190\u2192")


def _render(icon: QIcon, size: int, mode: QIcon.Mode) -> QImage:
    image = icon.pixmap(QSize(size, size), mode).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return image


def _painted(image: QImage) -> list[QColor]:
    return [
        image.pixelColor(x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    ]


def test_undo_redo_buttons_are_drawn_icons_with_text(qapp):
    view = PDFView(defer_heavy_panels=False)
    try:
        undo, redo = view._action_undo_right, view._action_redo_right
        assert undo.text() == "復原" and redo.text() == "重做"
        for action in (undo, redo):
            assert not action.icon().isNull()
            assert _painted(_render(action.icon(), 32, QIcon.Mode.Normal))
        assert view.toolbar_right.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    finally:
        view.deleteLater()
        qapp.processEvents()


def test_redo_icon_mirrors_undo_icon(qapp):
    view = PDFView(defer_heavy_panels=False)
    try:
        undo = _render(view._action_undo_right.icon(), 32, QIcon.Mode.Normal)
        redo = _render(view._action_redo_right.icon(), 32, QIcon.Mode.Normal)
        assert undo != redo
        flipped = redo.flipped(Qt.Orientation.Horizontal)
        worst = max(
            abs(undo.pixelColor(x, y).alpha() - flipped.pixelColor(x, y).alpha())
            for x in range(undo.width())
            for y in range(undo.height())
        )
        assert worst <= 24
    finally:
        view.deleteLater()
        qapp.processEvents()


def test_icon_colour_follows_the_theme_and_the_disabled_state(qapp):
    from view.theme import THEME_REGISTRY

    view = PDFView(defer_heavy_panels=False)
    try:
        for theme_id in ("alpine-snow", "ink-porcelain"):
            view.apply_theme(theme_id, persist=False)
            tokens = THEME_REGISTRY[theme_id].tokens
            icon = view._action_undo_right.icon()
            normal = {c.name() for c in _painted(_render(icon, 32, QIcon.Mode.Normal))}
            disabled = {c.name() for c in _painted(_render(icon, 32, QIcon.Mode.Disabled))}
            assert QColor(tokens["fg"]).name() in normal
            assert QColor(tokens["fg_subtle"]).name() in disabled
    finally:
        view.apply_theme("alpine-snow", persist=False)
        view.deleteLater()
        qapp.processEvents()
        qapp.setStyleSheet("")


def test_move_grip_draws_six_dots_in_the_text_colour(qapp):
    from view.glyph_icons import GripDots

    bar = TextInlineActionBar()
    try:
        dots = bar.move_grip.findChild(GripDots)
        assert dots is not None
        dots.resize(dots.sizeHint())
        palette = dots.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#123456"))
        dots.setPalette(palette)
        image = QImage(dots.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        dots.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        assert any(c.name() == "#123456" for c in _painted(image))
        rows = {y for y in range(image.height()) if any(image.pixelColor(x, y).alpha() > 200 for x in range(image.width()))}
        columns = {x for x in range(image.width()) if any(image.pixelColor(x, y).alpha() > 200 for y in range(image.height()))}
        assert len(_runs(rows)) == 3 and len(_runs(columns)) == 2
    finally:
        bar.deleteLater()
        qapp.processEvents()


def _runs(values: set[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for value in sorted(values):
        if runs and value == runs[-1][-1] + 1:
            runs[-1].append(value)
        else:
            runs.append([value])
    return runs


@pytest.fixture(autouse=True)
def _reset_application_style(qapp):
    yield
    QApplication.instance().setStyleSheet("")
