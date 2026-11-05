from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem

import view.pdf_view as pdf_view_module
from controller.pdf_controller import PDFController
from model.pdf_model import PDFModel
from test_scripts.qt_teardown import dispose_pdf_view, leaked_gui_since, snapshot_visible_gui
from view.pdf_view import PDFView, _ReorderableThumbnailList


def _make_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    for t in texts:
        page = doc.new_page()
        page.insert_text((72, 72), t, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _pump_events(ms: int = 250) -> None:
    app = QApplication.instance()
    assert app is not None
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _no_stray_gui_state():
    before = snapshot_visible_gui()
    yield
    leaked = leaked_gui_since(before)
    assert not leaked, "this test left GUI state behind for the next test: " + "; ".join(leaked)


@pytest.fixture()
def mvc(monkeypatch, qapp):
    monkeypatch.setattr("controller.pdf_controller.QMessageBox.information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("controller.pdf_controller.show_error", lambda *a, **k: None)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    yield model, view, controller
    dispose_pdf_view(view, controller, model)


class _InternalDropEvent(QDropEvent):
    """Synthesized internal drop whose source() reports the list itself."""

    def __init__(self, widget: QListWidget, pos: QPoint) -> None:
        super().__init__(
            QPointF(pos),
            Qt.MoveAction,
            QMimeData(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self._drag_source = widget

    def source(self) -> QListWidget:  # noqa: N802 - Qt override
        return self._drag_source


class _InternalDragMoveEvent(QDragMoveEvent):
    """Synthesized internal drag-move whose source() reports the list itself."""

    def __init__(self, widget: QListWidget, pos: QPoint) -> None:
        super().__init__(
            pos,
            Qt.MoveAction,
            QMimeData(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self._drag_source = widget

    def source(self) -> QListWidget:  # noqa: N802 - Qt override
        return self._drag_source


def _make_thumbnail_list(qapp, count: int = 5, height: int = 640) -> _ReorderableThumbnailList:
    widget = _ReorderableThumbnailList()
    widget.setFixedSize(240, height)
    for row in range(count):
        item = QListWidgetItem(f"頁{row + 1}")
        item.setSizeHint(QSize(200, 120))
        widget.addItem(item)
    widget.show()
    widget.doItemsLayout()
    qapp.processEvents()
    return widget


def _list_labels(widget: QListWidget) -> list[str]:
    return [widget.item(row).text() for row in range(widget.count())]


def _oracle_slot(widget: QListWidget, y: int) -> int:
    """Insert slot g from row centres, computed independently of the code under test."""
    for k in range(widget.count()):
        if y < widget.visualItemRect(widget.item(k)).center().y():
            return k
    return widget.count()


def _oracle_final_row(slot: int, source_row: int) -> int | None:
    if slot in (source_row, source_row + 1):
        return None
    return slot - 1 if slot > source_row else slot


def _drag_move(widget: QListWidget, pos: QPoint) -> None:
    widget.dragMoveEvent(_InternalDragMoveEvent(widget, pos))


class _FakeDrag:
    """QDrag stand-in; ``on_exec`` runs inside ``exec`` like the OS drag loop would."""

    on_exec = None

    def __init__(self, source) -> None:
        self.source = source

    def setMimeData(self, mime) -> None:  # noqa: N802
        pass

    def setPixmap(self, pixmap) -> None:  # noqa: N802
        pass

    def setHotSpot(self, point) -> None:  # noqa: N802
        pass

    def exec(self, *actions) -> object:
        if _FakeDrag.on_exec is not None:
            _FakeDrag.on_exec()
        return Qt.MoveAction


@pytest.fixture()
def fake_drag(monkeypatch):
    _FakeDrag.on_exec = None
    monkeypatch.setattr(pdf_view_module, "QDrag", _FakeDrag)
    yield _FakeDrag
    _FakeDrag.on_exec = None


def test_indicator_slot_follows_contract_table(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    try:
        widget.setCurrentRow(1)

        def slot_at(y: int) -> int | None:
            _drag_move(widget, QPoint(100, y))
            return widget._drop_indicator_slot

        r0 = widget.visualItemRect(widget.item(0))
        r2 = widget.visualItemRect(widget.item(2))
        r3 = widget.visualItemRect(widget.item(3))
        r4 = widget.visualItemRect(widget.item(4))
        assert slot_at(r0.top() + 4) == 0
        assert slot_at(r0.bottom() - 4) is None
        assert slot_at(r2.top() + 4) is None
        assert slot_at(r2.bottom() - 4) == 3
        assert slot_at(r3.center().y()) == 4
        assert slot_at(r4.bottom() + 30) == 5
    finally:
        widget.close()
        qapp.processEvents()


def test_indicator_matches_drop_on_real_layout_sweep(mvc, tmp_path) -> None:
    _, view, controller = mvc
    path = _make_pdf(tmp_path / "sweep.pdf", [f"p{i}" for i in range(1, 9)])
    view.resize(900, 620)
    view.show()
    controller.open_pdf(str(path))
    _pump_events(500)

    widget = view.thumbnail_list
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda s, d: emitted.append((s, d)))
    source = 2
    def _items() -> list[QListWidgetItem]:
        return [widget.item(r) for r in range(widget.count())]

    items = _items()
    assert len(items) == 8

    def sweep() -> int:
        checked = 0
        for y in range(0, widget.viewport().height(), 4):
            pos = QPoint(widget.viewport().width() // 2, y)
            widget.setCurrentRow(source)
            emitted.clear()
            _drag_move(widget, pos)
            slot = widget._drop_indicator_slot
            widget.dropEvent(_InternalDropEvent(widget, pos))
            if slot is None:
                assert emitted == [], f"y={y}: no indicator but a drop was emitted {emitted}"
            else:
                expected = _oracle_final_row(slot, source)
                assert expected is not None, f"y={y}: indicator in the no-op band slot={slot}"
                assert emitted == [(source, expected)], f"y={y}: slot={slot} emitted={emitted}"
                moved = widget.takeItem(expected)
                widget.insertItem(source, moved)
            # Identity, not text: the real view relabels rows 頁1..頁n after a reorder signal.
            assert _items() == items, f"y={y}: order not restored"
            checked += 1
        return checked

    assert sweep() > 20
    bar = widget.verticalScrollBar()
    bar.setValue(bar.maximum())
    qapp = QApplication.instance()
    assert qapp is not None
    qapp.processEvents()
    assert sweep() > 20


def test_indicator_cleared_on_leave_drop_and_drag_end(qapp, fake_drag) -> None:
    widget = _make_thumbnail_list(qapp)
    updates: list[int] = []
    viewport = widget.viewport()
    real_update = viewport.update
    viewport.update = lambda *a: (updates.append(1), real_update(*a))[1]
    try:
        widget.setCurrentRow(0)
        r3 = widget.visualItemRect(widget.item(3))
        pos = QPoint(100, r3.bottom() - 4)

        _drag_move(widget, pos)
        assert widget._drop_indicator_slot == 4
        updates.clear()
        widget.dragLeaveEvent(QDragLeaveEvent())
        assert widget._drop_indicator_slot is None
        assert updates

        _drag_move(widget, pos)
        assert widget._drop_indicator_slot == 4
        updates.clear()
        widget.dropEvent(_InternalDropEvent(widget, pos))
        assert widget._drop_indicator_slot is None
        assert updates

        widget.setCurrentRow(0)
        seen: list[int | None] = []

        def inside_exec() -> None:
            _drag_move(widget, pos)
            seen.append(widget._drop_indicator_slot)

        fake_drag.on_exec = inside_exec
        updates.clear()
        widget.startDrag(Qt.MoveAction)
        assert seen == [4]
        assert widget._drop_indicator_slot is None
        assert updates
    finally:
        del viewport.update
        widget.close()
        qapp.processEvents()


def test_indicator_uses_post_autoscroll_geometry(qapp) -> None:
    widget = _make_thumbnail_list(qapp, count=12, height=320)
    try:
        bar = widget.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(0)
        widget.setCurrentRow(0)
        y = widget.viewport().height() - 4

        _drag_move(widget, QPoint(100, y))

        assert bar.value() > 0, "edge hover must have auto-scrolled"
        assert widget._drop_indicator_slot == _oracle_slot(widget, y)
    finally:
        widget.close()
        qapp.processEvents()


def _pump_ms(qapp, ms: int) -> None:
    import time

    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)


def test_resting_in_the_edge_band_keeps_scrolling(qapp) -> None:
    """Opus recommendation (items 10 vs 28): tall full-width rows stay; the drag
    reaches far rows through a timer-driven edge scroll that does not stall
    when the cursor rests (one nudge per mouse event did)."""
    widget = _make_thumbnail_list(qapp, count=30, height=320)
    try:
        bar = widget.verticalScrollBar()
        bar.setValue(0)
        widget.setCurrentRow(0)
        y = widget.viewport().height() - 10
        _drag_move(widget, QPoint(100, y))
        after_first = bar.value()

        _pump_ms(qapp, 300)

        assert bar.value() > after_first + 3 * max(1, after_first), (after_first, bar.value())
        assert widget._drop_indicator_slot == _oracle_slot(widget, y)
    finally:
        widget._stop_drag_scroll()
        widget.close()
        qapp.processEvents()


def test_edge_scroll_speed_grows_with_depth_into_the_band(qapp) -> None:
    widget = _make_thumbnail_list(qapp, count=30, height=320)
    try:
        h = widget.viewport().height()
        shallow = widget._drag_scroll_step(QPoint(100, h - 46))
        deep = widget._drag_scroll_step(QPoint(100, h - 1))
        middle = widget._drag_scroll_step(QPoint(100, h // 2))
        assert middle == 0
        assert 0 < shallow < deep
        assert deep <= round(h * 0.15) + 1
        assert widget._drag_scroll_step(QPoint(100, 1)) < 0
    finally:
        widget.close()
        qapp.processEvents()


@pytest.mark.parametrize("end", ["drop", "leave", "leave_band"])
def test_edge_scroll_stops_when_the_drag_ends_or_leaves_the_band(qapp, end) -> None:
    widget = _make_thumbnail_list(qapp, count=30, height=320)
    try:
        bar = widget.verticalScrollBar()
        bar.setValue(0)
        widget.setCurrentRow(0)
        y = widget.viewport().height() - 10
        _drag_move(widget, QPoint(100, y))
        _pump_ms(qapp, 100)
        if end == "drop":
            widget.dropEvent(_InternalDropEvent(widget, QPoint(100, y)))
        elif end == "leave":
            widget.dragLeaveEvent(QDragLeaveEvent())
        else:
            _drag_move(widget, QPoint(100, widget.viewport().height() // 2))
        stopped_at = bar.value()
        _pump_ms(qapp, 150)
        assert bar.value() == stopped_at
    finally:
        widget._stop_drag_scroll()
        widget.close()
        qapp.processEvents()


def test_drop_uses_row_captured_at_drag_start(qapp, fake_drag) -> None:
    widget = _make_thumbnail_list(qapp)
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda s, d: emitted.append((s, d)))
    try:
        widget.setCurrentRow(1)

        def inside_exec() -> None:
            widget.setCurrentRow(3)
            rect = widget.visualItemRect(widget.item(4))
            widget.dropEvent(_InternalDropEvent(widget, QPoint(100, rect.bottom() - 4)))

        fake_drag.on_exec = inside_exec
        widget.startDrag(Qt.MoveAction)

        assert emitted == [(1, 4)]
        assert _list_labels(widget) == ["頁1", "頁3", "頁4", "頁5", "頁2"]
    finally:
        widget.close()
        qapp.processEvents()


def test_indicator_line_y_at_slot_boundary(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    try:
        widget.setCurrentRow(2)
        assert widget._drop_indicator_line_y() is None

        rect0 = widget.visualItemRect(widget.item(0))
        _drag_move(widget, QPoint(100, rect0.top() + 2))
        assert widget._drop_indicator_slot == 0
        assert widget._drop_indicator_line_y() == rect0.top()

        rect4 = widget.visualItemRect(widget.item(4))
        _drag_move(widget, QPoint(100, rect4.top() + 4))
        assert widget._drop_indicator_slot == 4
        assert widget._drop_indicator_line_y() == rect4.top()

        _drag_move(widget, QPoint(100, rect4.bottom() + 30))
        assert widget._drop_indicator_slot == 5
        assert widget._drop_indicator_line_y() == rect4.bottom()

        rect2 = widget.visualItemRect(widget.item(2))
        _drag_move(widget, QPoint(100, rect2.center().y()))
        assert widget._drop_indicator_slot is None
        assert widget._drop_indicator_line_y() is None
    finally:
        widget.close()
        qapp.processEvents()


def test_noop_band_emits_nothing(qapp) -> None:
    widget = _make_thumbnail_list(qapp)
    emitted: list[tuple[int, int]] = []
    widget.page_reordered.connect(lambda s, d: emitted.append((s, d)))
    try:
        r0 = widget.visualItemRect(widget.item(0))
        r1 = widget.visualItemRect(widget.item(1))
        r2 = widget.visualItemRect(widget.item(2))
        for y in (r0.bottom() - 4, r1.top() + 4, r1.center().y(), r1.bottom() - 4, r2.top() + 4):
            widget.setCurrentRow(1)
            widget.dropEvent(_InternalDropEvent(widget, QPoint(100, y)))
            assert emitted == []
            assert _list_labels(widget) == ["頁1", "頁2", "頁3", "頁4", "頁5"]
    finally:
        widget.close()
        qapp.processEvents()


def test_drop_reorders_model_end_to_end(mvc, tmp_path) -> None:
    model, view, controller = mvc
    controller.activate()
    path = _make_pdf(tmp_path / "e2e.pdf", [f"p{i}" for i in range(1, 7)])
    view.resize(900, 620)
    view.show()
    controller.open_pdf(str(path))
    _pump_events(500)

    widget = view.thumbnail_list
    widget.setCurrentRow(0)
    rect = widget.visualItemRect(widget.item(3))
    widget.dropEvent(_InternalDropEvent(widget, QPoint(widget.viewport().width() // 2, rect.bottom() - 4)))
    _pump_events(500)

    assert model.doc is not None
    assert [p.get_text("text").strip() for p in model.doc] == ["p2", "p3", "p4", "p1", "p5", "p6"]
    assert _list_labels(widget) == [f"頁{i}" for i in range(1, 7)]
