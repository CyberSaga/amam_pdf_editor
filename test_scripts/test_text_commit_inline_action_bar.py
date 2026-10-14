"""R4-2: pure placement rule of the inline action bar beside the editor."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402

from view.text_inline_action_bar import compute_inline_action_bar_pos  # noqa: E402

_VIEWPORT = QRect(0, 0, 800, 600)
_BAR = QSize(200, 30)


def _bar_rect(pos: QPoint) -> QRect:
    return QRect(pos, _BAR)


def test_bar_placement_below_flip_clamp_and_side() -> None:
    # Below, right-aligned with the editor.
    editor = QRect(300, 100, 200, 40)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos == QPoint(editor.right() - _BAR.width() + 1, editor.bottom() + 1 + 4)
    assert not _bar_rect(pos).intersects(editor)

    # Near the bottom: flips above.
    editor = QRect(300, 560, 200, 30)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos is not None
    assert pos.y() == editor.top() - 4 - _BAR.height()
    assert not _bar_rect(pos).intersects(editor)

    # Editor hugging the left edge: x is clamped to the margin.
    editor = QRect(2, 100, 60, 20)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos is not None
    assert pos.x() == 4
    assert not _bar_rect(pos).intersects(editor)

    # Taller than the room above and below: goes to the right side.
    editor = QRect(100, 5, 200, 590)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos is not None
    assert pos.x() == editor.right() + 1 + 4
    assert not _bar_rect(pos).intersects(editor)
    assert _VIEWPORT.contains(_bar_rect(pos))

    # ... and to the left side when the right side does not fit either.
    editor = QRect(500, 5, 290, 590)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos is not None
    assert pos.x() == editor.left() - 4 - _BAR.width()
    assert not _bar_rect(pos).intersects(editor)

    # Off-viewport editor: no placement.
    assert compute_inline_action_bar_pos(QRect(900, 100, 50, 20), _BAR, _VIEWPORT) is None
    assert compute_inline_action_bar_pos(QRect(100, -200, 50, 20), _BAR, _VIEWPORT) is None


def test_bar_placement_fallback_stays_inside_the_viewport() -> None:
    # The editor fills the viewport: overlap is accepted only in the fallback.
    editor = QRect(0, 0, 800, 600)
    pos = compute_inline_action_bar_pos(editor, _BAR, _VIEWPORT)
    assert pos == QPoint(800 - 200 - 4, 600 - 30 - 4)
    assert _VIEWPORT.contains(_bar_rect(pos))


def test_bar_wider_than_the_viewport_clamps_to_the_left_margin() -> None:
    pos = compute_inline_action_bar_pos(QRect(10, 10, 50, 20), QSize(900, 30), _VIEWPORT)
    assert pos is not None and pos.x() == 4
