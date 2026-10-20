from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QMessageBox

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.object_op_refusals import (  # noqa: E402
    REASON_SENTENCES,
    batch_refusal_message,
    object_refusal_message,
)
from controller.pdf_controller import PDFController  # noqa: E402
from model.object_op_refusal import ObjectOpRefusal, ObjectOpRefused  # noqa: E402
from model.object_requests import (  # noqa: E402
    BatchDeleteObjectsRequest,
    BatchMoveObjectsRequest,
    DeleteObjectRequest,
    MoveObjectRequest,
    ObjectRef,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model.pdf_content_ops import discover_native_image_invocations  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402


class _FakeCommandManager:
    def __init__(self) -> None:
        self.recorded = []

    def record(self, cmd) -> None:
        self.recorded.append(cmd)


class _FakeModel:
    def __init__(self) -> None:
        self.doc = [object()]
        self.command_manager = _FakeCommandManager()
        self.calls = []

    def _capture_doc_snapshot(self) -> bytes:
        return b"snapshot"

    def move_object(self, request):
        self.calls.append(("move", request))
        return True

    def rotate_object(self, request):
        self.calls.append(("rotate", request))
        return True

    def delete_object(self, request):
        self.calls.append(("delete", request))
        return True

    def delete_objects_atomic(self, requests):
        self.calls.append(("delete_atomic", list(requests)))
        return True

    def get_object_info_at_point(self, page_num: int, point: fitz.Point):
        self.calls.append(("hit", page_num, point))
        return "hit-info"


def _make_controller() -> PDFController:
    controller = PDFController.__new__(PDFController)
    controller.model = _FakeModel()
    controller.view = SimpleNamespace(current_page=0)
    controller._invalidate_active_render_state = lambda *args, **kwargs: None
    controller._update_undo_redo_tooltips = lambda: None
    controller.show_page = lambda page_idx: None
    return controller


def test_controller_delegates_object_hit_info() -> None:
    controller = _make_controller()
    point = fitz.Point(10, 20)
    result = PDFController.get_object_info_at_point(controller, 1, point)
    assert result == "hit-info"
    assert controller.model.calls[-1] == ("hit", 1, point)


def test_controller_records_snapshot_for_move_object() -> None:
    controller = _make_controller()
    request = MoveObjectRequest("obj-1", "textbox", 1, 1, fitz.Rect(10, 20, 30, 40))

    PDFController.move_object(controller, request)

    assert controller.model.calls[-1] == ("move", request)
    assert len(controller.model.command_manager.recorded) == 1


def test_controller_records_snapshot_for_batch_move_object() -> None:
    controller = _make_controller()
    batch = BatchMoveObjectsRequest(
        moves=[
            MoveObjectRequest("obj-1", "rect", 1, 1, fitz.Rect(10, 20, 30, 40)),
            MoveObjectRequest("obj-2", "rect", 1, 1, fitz.Rect(50, 60, 70, 80)),
        ]
    )

    PDFController.move_object(controller, batch)

    assert ("move", batch.moves[0]) in controller.model.calls
    assert ("move", batch.moves[1]) in controller.model.calls
    assert len(controller.model.command_manager.recorded) == 1


def test_controller_records_snapshot_for_rotate_and_delete_object() -> None:
    controller = _make_controller()
    rotate = RotateObjectRequest("obj-1", "textbox", 1, 90)
    delete = DeleteObjectRequest("obj-2", "rect", 1)

    PDFController.rotate_object(controller, rotate)
    PDFController.delete_object(controller, delete)

    assert ("rotate", rotate) in controller.model.calls
    assert ("delete", delete) in controller.model.calls
    assert len(controller.model.command_manager.recorded) == 2


def test_controller_records_snapshot_for_batch_delete_object() -> None:
    controller = _make_controller()
    batch = BatchDeleteObjectsRequest(
        objects=[
            ObjectRef(object_id="obj-1", object_kind="rect", page_num=1),
            ObjectRef(object_id="obj-2", object_kind="textbox", page_num=1),
        ]
    )

    PDFController.delete_object(controller, batch)

    # The controller must cross the model boundary once so a mid-batch failure can
    # restore the entire batch rather than leaving a partial deletion behind.
    assert controller.model.calls == [
        (
            "delete_atomic",
            [
                DeleteObjectRequest("obj-1", "rect", 1),
                DeleteObjectRequest("obj-2", "textbox", 1),
            ],
        )
    ]
    assert len(controller.model.command_manager.recorded) == 1


# --- D-OLD-MARKERS: a refused object op is never silent ----------------------------------
#
# Owner decision after round 15: when Move / Resize / Rotate / Delete of an object still
# refuses, the Controller shows ONE plain zh-TW message saying which object could not be
# changed and why; a batch that partly refuses says how many objects were not changed.
# The Model records the reason code (``PDFModel.last_object_op_refusal``); the sentences
# live in ``controller/object_op_refusals.py``.

_LATIN = re.compile(r"[A-Za-z]")


def _capture_message_boxes(monkeypatch) -> list[str]:
    """QMessageBox double: every critical box the real ``show_error`` opens."""
    shown: list[str] = []

    def _critical(_parent, _title, text, *_args, **_kwargs):
        shown.append(str(text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(_critical))
    return shown


class _RefusingModel(_FakeModel):
    """Refuses the ops on ``refused`` object ids with ``reason``, records the code like
    ``PDFModel`` does, and succeeds for every other id."""

    def __init__(self, refused: set[str], reason: ObjectOpRefusal) -> None:
        super().__init__()
        self.refused = refused
        self.reason = reason
        self.last_object_op_refusal = None

    def _answer(self, object_id: str, object_kind: str) -> bool:
        if object_id in self.refused:
            self.last_object_op_refusal = ObjectOpRefused(self.reason, object_kind, object_id)
            return False
        self.last_object_op_refusal = None
        return True

    def move_object(self, request):
        self.calls.append(("move", request))
        return self._answer(request.object_id, request.object_kind)

    def resize_object(self, request):
        self.calls.append(("resize", request))
        return self._answer(request.object_id, request.object_kind)

    def rotate_object(self, request):
        self.calls.append(("rotate", request))
        return self._answer(request.object_id, request.object_kind)

    def delete_object(self, request):
        self.calls.append(("delete", request))
        return self._answer(request.object_id, request.object_kind)

    def delete_objects_atomic(self, requests):
        self.calls.append(("delete_atomic", list(requests)))
        self.last_object_op_refusal = None
        for request in requests:
            if not self._answer(request.object_id, request.object_kind):
                return False
        return True


def _refusing_controller(refused: set[str], reason: ObjectOpRefusal) -> PDFController:
    controller = _make_controller()
    controller.model = _RefusingModel(refused, reason)
    return controller


def _run_single_op(
    controller: PDFController, op: str, kind: str, object_id: str = "obj-1", *, move_to: fitz.Rect | None = None
) -> None:
    """Call the real controller slot for one Move / Resize / Rotate / Delete of ``object_id``."""
    if op == "move":
        dest = fitz.Rect(10, 20, 30, 40) if move_to is None else move_to
        PDFController.move_object(controller, MoveObjectRequest(object_id, kind, 1, 1, dest))
    elif op == "resize":
        PDFController.resize_object(controller, ResizeObjectRequest(object_id, kind, 1, fitz.Rect(10, 20, 60, 70)))
    elif op == "rotate":
        PDFController.rotate_object(controller, RotateObjectRequest(object_id, kind, 1, 90))
    else:
        PDFController.delete_object(controller, DeleteObjectRequest(object_id, kind, 1))


_SINGLE_REFUSALS = [
    ("move", "textbox", ObjectOpRefusal.TEXTBOX_TEXT_CHANGED, "移動", "文字框"),
    ("resize", "image", ObjectOpRefusal.IMAGE_NOT_LOCATED, "調整大小", "圖片"),
    ("rotate", "image", ObjectOpRefusal.IMAGE_NOT_LOCATED, "旋轉", "圖片"),
    ("rotate", "textbox", ObjectOpRefusal.TEXTBOX_TEXT_CHANGED, "旋轉", "文字框"),
    ("delete", "textbox", ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT, "刪除", "文字框"),
    ("delete", "native_image", ObjectOpRefusal.OBJECT_NOT_FOUND, "刪除", "圖片"),
]


@pytest.mark.parametrize(("op", "kind", "reason", "verb_word", "kind_word"), _SINGLE_REFUSALS)
def test_refused_object_op_shows_one_plain_zh_tw_message(
    monkeypatch, op: str, kind: str, reason: ObjectOpRefusal, verb_word: str, kind_word: str
) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller({"obj-1"}, reason)
    _run_single_op(controller, op, kind)

    assert len(shown) == 1, shown
    message = shown[0]
    assert message == object_refusal_message(op, ObjectOpRefused(reason, kind, "obj-1"))
    assert verb_word in message and kind_word in message
    assert REASON_SENTENCES[reason] in message
    assert not _LATIN.search(message), message
    assert controller.model.command_manager.recorded == []


def test_successful_object_op_shows_no_message(monkeypatch) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller(set(), ObjectOpRefusal.OPERATION_FAILED)
    PDFController.move_object(controller, MoveObjectRequest("obj-1", "textbox", 1, 1, fitz.Rect(10, 20, 30, 40)))
    PDFController.delete_object(controller, DeleteObjectRequest("obj-2", "image", 1))
    assert shown == []
    assert len(controller.model.command_manager.recorded) == 2


def test_batch_move_that_partly_refuses_says_how_many_objects_did_not_move(monkeypatch) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller({"obj-2"}, ObjectOpRefusal.IMAGE_NOT_LOCATED)
    batch = BatchMoveObjectsRequest(
        moves=[
            MoveObjectRequest("obj-1", "rect", 1, 1, fitz.Rect(10, 20, 30, 40)),
            MoveObjectRequest("obj-2", "image", 1, 1, fitz.Rect(50, 60, 70, 80)),
            MoveObjectRequest("obj-3", "textbox", 1, 1, fitz.Rect(90, 60, 120, 80)),
        ]
    )
    PDFController.move_object(controller, batch)

    # The two that moved are one undo step; the refusal is reported once, with counts.
    assert len(controller.model.command_manager.recorded) == 1
    assert len(shown) == 1, shown
    message = shown[0]
    assert "3" in message and "1" in message and "移動" in message
    assert REASON_SENTENCES[ObjectOpRefusal.IMAGE_NOT_LOCATED] in message
    assert not _LATIN.search(message), message


def test_batch_move_that_fully_refuses_reports_every_object(monkeypatch) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller({"obj-1", "obj-2"}, ObjectOpRefusal.TEXTBOX_TEXT_CHANGED)
    batch = BatchMoveObjectsRequest(
        moves=[
            MoveObjectRequest("obj-1", "textbox", 1, 1, fitz.Rect(10, 20, 30, 40)),
            MoveObjectRequest("obj-2", "textbox", 1, 1, fitz.Rect(50, 60, 70, 80)),
        ]
    )
    PDFController.move_object(controller, batch)
    assert controller.model.command_manager.recorded == []
    assert len(shown) == 1 and "2" in shown[0] and "文字框" in shown[0], shown


def test_batch_delete_refusal_says_no_object_was_deleted(monkeypatch) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller({"obj-2"}, ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT)
    batch = BatchDeleteObjectsRequest(
        objects=[
            ObjectRef(object_id="obj-1", object_kind="rect", page_num=1),
            ObjectRef(object_id="obj-2", object_kind="textbox", page_num=1),
        ]
    )
    PDFController.delete_object(controller, batch)
    assert controller.model.command_manager.recorded == []
    assert len(shown) == 1, shown
    message = shown[0]
    # Atomic: the one refusal rolled the whole batch back, so all 2 stay.
    assert "2" in message and "刪除" in message and "文字框" in message
    assert REASON_SENTENCES[ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT] in message
    assert not _LATIN.search(message), message


def test_every_object_refusal_code_has_a_plain_zh_tw_sentence() -> None:
    assert set(REASON_SENTENCES) == set(ObjectOpRefusal)
    for reason in ObjectOpRefusal:
        for verb in ("move", "resize", "rotate", "delete"):
            for kind in ("textbox", "image", "native_image", "rect", None):
                text = object_refusal_message(verb, ObjectOpRefused(reason, kind, "x"))
                assert text and not _LATIN.search(text), (reason, verb, kind, text)
    # No code at all (a model that did not record one) still speaks, in plain words.
    for text in (
        object_refusal_message("move", None),
        batch_refusal_message("move", 4, [None, None]),
    ):
        assert text and not _LATIN.search(text), text


# Real model, real controller methods: the codes the Model records reach the dialog.


def _real_model_controller(tmp_path):
    path = tmp_path / "dom_ctrl.pdf"
    doc = fitz.open()
    doc.new_page(width=420, height=600)
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    controller = _make_controller()
    controller.model = model
    return model, controller


@pytest.mark.parametrize("op", ["move", "rotate", "delete"])
def test_real_stale_textbox_refusal_reaches_the_message_box(monkeypatch, tmp_path, op: str) -> None:
    shown = _capture_message_boxes(monkeypatch)
    model, controller = _real_model_controller(tmp_path)
    try:
        box = fitz.Rect(100, 100, 300, 160)
        model.add_textbox(1, box, "Goodbye", font="helv", size=14)
        page = model.doc[0]
        page.insert_text(fitz.Point(110, 150), "KEEP", fontsize=12, fontname="helv")
        for annot in page.annots() or []:
            if annot.info.get("subject") == "pdf_editor_textbox_object":
                payload = json.loads(annot.info.get("content") or "{}")
                payload["text"] = "Hello"
                annot.set_info(content=json.dumps(payload), subject="pdf_editor_textbox_object")
                annot.update()
                object_id = payload["object_id"]
        _run_single_op(controller, op, "textbox", object_id, move_to=box + (0, 200, 0, 200))
        assert len(shown) == 1, shown
        assert REASON_SENTENCES[ObjectOpRefusal.TEXTBOX_TEXT_CHANGED] in shown[0]
        assert "文字框" in shown[0] and not _LATIN.search(shown[0])
        assert len(model.command_manager._undo_stack) == 0
    finally:
        model.close()


def test_real_ambiguous_old_image_marker_delete_reaches_the_message_box(monkeypatch, tmp_path) -> None:
    shown = _capture_message_boxes(monkeypatch)
    model, controller = _real_model_controller(tmp_path)
    try:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 10), False)
        pix.set_rect(pix.irect, (0, 160, 0))
        wide = pix.tobytes("png")
        requested = fitz.Rect(100, 100, 200, 175)
        model.add_image_object(1, requested, wide, rotation=0)
        second = model.add_image_object(1, requested, wide, rotation=0)
        page = model.doc[0]
        for annot in page.annots() or []:
            payload = json.loads(annot.info.get("content") or "{}")
            if payload.get("object_id") == second:
                payload["rect"] = [requested.x0, requested.y0, requested.x1, requested.y1]
                annot.set_rect(requested)
                annot.set_info(content=json.dumps(payload), subject="pdf_editor_image_object")
                annot.update()
        PDFController.delete_object(controller, DeleteObjectRequest(second, "image", 1))
        assert len(shown) == 1, shown
        assert REASON_SENTENCES[ObjectOpRefusal.IMAGE_NOT_LOCATED] in shown[0]
        assert "圖片" in shown[0]
        assert len(discover_native_image_invocations(model.doc, 1)) == 2
    finally:
        model.close()


# --- D-OBJ-FRAME: the Controller tells the View which objects stayed ------------------------


def _noting_controller(refused: set[str]) -> tuple[PDFController, list[list[str]]]:
    controller = _refusing_controller(refused, ObjectOpRefusal.IMAGE_NOT_LOCATED)
    notices: list[list[str]] = []
    controller.view = SimpleNamespace(current_page=0, note_object_op_refused=lambda ids: notices.append(list(ids)))
    return controller, notices


@pytest.mark.parametrize("op", ["move", "resize", "rotate"])
def test_refused_object_op_names_the_object_to_the_view(monkeypatch, op: str) -> None:
    _capture_message_boxes(monkeypatch)
    controller, notices = _noting_controller({"obj-1"})
    _run_single_op(controller, op, "image")
    assert notices == [["obj-1"]]


def test_accepted_object_op_does_not_notify_the_view(monkeypatch) -> None:
    _capture_message_boxes(monkeypatch)
    controller, notices = _noting_controller(set())
    PDFController.move_object(controller, MoveObjectRequest("obj-1", "image", 1, 1, fitz.Rect(10, 20, 30, 40)))
    PDFController.rotate_object(controller, RotateObjectRequest("obj-1", "image", 1, 90))
    assert notices == []


def test_partly_refused_batch_move_names_only_the_refused_objects_to_the_view(monkeypatch) -> None:
    _capture_message_boxes(monkeypatch)
    controller, notices = _noting_controller({"obj-2"})
    batch = BatchMoveObjectsRequest(
        moves=[
            MoveObjectRequest("obj-1", "rect", 1, 1, fitz.Rect(10, 20, 30, 40)),
            MoveObjectRequest("obj-2", "image", 1, 1, fitz.Rect(50, 60, 70, 80)),
        ]
    )
    PDFController.move_object(controller, batch)
    assert notices == [["obj-2"]]


def test_a_view_that_cannot_take_the_notice_does_not_break_the_refusal_report(monkeypatch) -> None:
    shown = _capture_message_boxes(monkeypatch)
    controller = _refusing_controller({"obj-1"}, ObjectOpRefusal.IMAGE_NOT_LOCATED)

    def _boom(_ids) -> None:
        raise RuntimeError("view gone")

    controller.view = SimpleNamespace(current_page=0, note_object_op_refused=_boom)
    PDFController.move_object(controller, MoveObjectRequest("obj-1", "image", 1, 1, fitz.Rect(10, 20, 30, 40)))
    assert len(shown) == 1
