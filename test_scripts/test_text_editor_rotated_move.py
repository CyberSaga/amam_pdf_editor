"""Round 7 / ROT: the rotated editor proxy's ``pos`` is a CORNER of the box.

The open path rotates the proxy about (0, 0) and puts ``pos`` at a rotation-dependent
corner of the box (90: x1, 180: x0 + W / y0 + H, 270: y1).  The drag clamp, the drag
finish (``editing_rect``) and the cross-page resolve used to treat ``pos`` as the
top-left of an unrotated box, so the first grip move on a /Rotate 90/180 page jumped the
box 52 / 89 px and ``editing_rect`` was wrong after any move on 90/180/270.

These are the pure-helper and Qt-transform tests; the real-MVC gesture and end-to-end
tests live in ``test_text_commit_editor_mouse_gestures.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtWidgets import QGraphicsScene, QWidget  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import view.text_editing as text_editing  # noqa: E402

_RECT = fitz.Rect(72.0, 109.05, 233.06, 123.05)
_PAGE_ORIGIN = (10.0, 30.0)


def _forward(rotation: int, rs: float):
    """The real open sequence of ``create_text_editor`` (layout, + page x, quarter turn)."""
    sr = _RECT * rs
    x0, y0 = _PAGE_ORIGIN
    width, height, pos_x, pos_y, norm = text_editing._compute_editor_proxy_layout(
        scaled_rect=sr,
        scaled_width=int(round(_RECT.width * rs)),
        page_y_offset=y0,
        rotation=rotation,
        content_height_px=max(int(round(sr.height)), 1),
    )
    pos_x += x0
    width, height, pos_x, pos_y = text_editing._quarter_turn_proxy_layout(
        scaled_rect=sr,
        page_x=x0,
        page_y=y0,
        rotation=norm,
        width_px=width,
        height_px=height,
        pos_x=pos_x,
        pos_y=pos_y,
    )
    return sr, width, height, pos_x, pos_y


def _literal_pre_refactor_forward(rotation: int, sr: fitz.Rect, width: int, height: int):
    """The open positions as they were hard-coded before the refactor (round-6 tree)."""
    x0, y0 = _PAGE_ORIGIN
    if rotation == 90:
        return float(x0 + sr.x1), float(y0 + sr.y0)
    if rotation == 270:
        return float(x0 + sr.x0), float(y0 + sr.y1)
    if rotation == 180:
        return float(sr.x0 + width + x0), float(y0 + sr.y0 + height)
    return float(sr.x0 + x0), float(y0 + sr.y0)


@pytest.mark.parametrize("scale", [1.0, 2.14])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_the_open_position_is_byte_identical_to_the_pre_refactor_literals(rotation, scale) -> None:
    """R2: the forward expressions stay literal (``x0 + sr.x1`` at 90, ``y0 + sr.y1`` at 270)."""
    sr, width, height, pos_x, pos_y = _forward(rotation, scale)
    expected = _literal_pre_refactor_forward(rotation, sr, width, height)
    assert (pos_x, pos_y) == expected  # exact, not approx: setPos(round(...)) follows


@pytest.mark.parametrize("scale", [1.0, 2.14])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_proxy_corner_offset_matches_the_literal_forward_corner(rotation, scale) -> None:
    """The inverse offset equals (open pos - page origin - rect top-left), against the literals."""
    sr, width, height, pos_x, pos_y = _forward(rotation, scale)
    dx, dy = text_editing._proxy_corner_offset(
        rotation, rect_w_px=sr.width, rect_h_px=sr.height, widget_w=width, widget_h=height
    )
    x0, y0 = _PAGE_ORIGIN
    assert pos_x - x0 - dx == pytest.approx(sr.x0, abs=1e-9)
    assert pos_y - y0 - dy == pytest.approx(sr.y0, abs=1e-9)
    # Hard-coded table (independent of the forward code): which corner of the box is pos.
    expected = {
        0: (0.0, 0.0),
        90: (sr.width, 0.0),
        180: (float(width), float(height)),
        270: (0.0, sr.height),
    }[rotation]
    assert (dx, dy) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_proxy_visual_extent_matches_the_rotated_proxy(qapp, rotation) -> None:
    """The extent table is checked against Qt's real transform, not against itself."""
    scene = QGraphicsScene()
    widget = QWidget()
    width, height = 161, 14
    widget.setFixedSize(width, height)
    proxy = scene.addWidget(widget)
    proxy.setTransformOriginPoint(0, 0)
    proxy.setRotation(rotation)
    pos = QPointF(300.0, 400.0)
    proxy.setPos(pos)
    left, top, right, bottom = text_editing._proxy_visual_extent(rotation, width, height)
    expected = QRectF(pos.x() + left, pos.y() + top, right - left, bottom - top)
    got = proxy.sceneBoundingRect()
    assert got.left() == pytest.approx(expected.left(), abs=1e-6)
    assert got.top() == pytest.approx(expected.top(), abs=1e-6)
    assert got.width() == pytest.approx(expected.width(), abs=1e-6)
    assert got.height() == pytest.approx(expected.height(), abs=1e-6)


def test_drag_page_resolution_uses_the_rotated_box_centre() -> None:
    """At 180 the proxy pos is the BOTTOM of the box: pos.y + H/2 lands on the wrong page."""
    from test_scripts.test_text_editing_gui_regressions import (
        _FakeEditorWidget,
        _FakeProxy,
        _make_view,
    )

    view = _make_view()
    view.continuous_pages = True
    view.page_y_positions = [0, 100]
    view.page_heights = [80, 80]
    view.text_editor = _FakeProxy(_FakeEditorWidget("text", "text", height=40), pos=QPointF(10, 95))
    view._editing_page_idx = 0
    view._editing_origin_page_idx = 0
    view._editing_rotation = 180

    # visual box y in [55, 95] -> centre 75 -> page 0 (the unrotated maths said 95 + 20 = 115).
    assert view._resolve_editor_page_idx_for_drag(95) == 0
