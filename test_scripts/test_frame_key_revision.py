"""H3 / H22: the revision field of ``table_objects.frame_key`` must change whenever the page does.

``edit_count`` did not: undo and redo never touch it, and a page-snapshot undo keeps the handle,
so the pre-undo table answer was served after the undo (D1 review, finding A, owner 2026-11-19).
The class check: over a run of document-changing operations, a page whose bytes changed never
keeps its frame key.
"""
from __future__ import annotations

import hashlib

import fitz
import pytest

from model import table_objects
from model.edit_commands import AddTextboxCommand
from model.pdf_model import PDFModel


def _pdf(path) -> str:
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), "hello", fontsize=12)
        doc.save(path)
    return str(path)


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_pdf(tmp_path / "a.pdf"))
    yield m
    m.close()


def _digest(model: PDFModel) -> str:
    # What table detection reads: the content stream, the annotations and the boxes.  (The bytes
    # of a scratch copy are no use here: every save writes a new /ID.)
    page = model.doc[0]
    h = hashlib.sha256(page.read_contents())
    for annot in page.annots() or []:
        h.update(repr((annot.type, tuple(annot.rect), annot.info.get("content"))).encode())
    h.update(repr((page.rotation, tuple(page.cropbox), tuple(page.mediabox))).encode())
    return h.hexdigest()


def _add_textbox(model: PDFModel) -> None:
    cmd = AddTextboxCommand(
        model=model,
        page_num=1,
        visual_rect=fitz.Rect(72, 200, 400, 400),
        text="added text",
        font="helv",
        size=14.0,
        color=(0, 0, 0),
        before_page_snapshot_bytes=model._capture_page_snapshot_strict(0),
    )
    model.command_manager.execute(cmd)


def test_digest_is_stable_without_a_change(model):
    assert _digest(model) == _digest(model)


def test_undo_of_a_page_snapshot_command_changes_the_frame_key(model):
    _add_textbox(model)
    key = table_objects.frame_key(model, 1)
    assert table_objects.store_table_rects(model, key, [fitz.Rect(72, 200, 400, 400)])
    assert model.command_manager.undo() is True
    assert table_objects.frame_key(model, 1) != key
    assert table_objects.cached_table_rects(model, 1) is None


def test_redo_changes_the_frame_key(model):
    _add_textbox(model)
    model.command_manager.undo()
    key = table_objects.frame_key(model, 1)
    assert model.command_manager.redo() is True
    assert table_objects.frame_key(model, 1) != key


def test_any_write_of_edit_count_is_a_new_revision(model):
    # A save sets edit_count to 0 while a failed handle renewal keeps the handle: an older
    # count-0 key of that handle must not match again.
    key = table_objects.frame_key(model, 1)
    model.edit_count = model.edit_count
    assert table_objects.frame_key(model, 1) != key


def test_a_replaced_command_manager_is_a_new_revision(model):
    from model.edit_commands import CommandManager

    key = table_objects.frame_key(model, 1)
    model.command_manager = CommandManager()
    assert table_objects.frame_key(model, 1) != key


def _rotate(model):
    model.rotate_pages([1], 90)


_OPS = [
    ("add textbox", _add_textbox),
    ("undo", lambda m: m.command_manager.undo()),
    ("redo", lambda m: m.command_manager.redo()),
    ("undo again", lambda m: m.command_manager.undo()),
    ("rotate", _rotate),
    ("add textbox on the rotated page", _add_textbox),
    ("undo after rotate", lambda m: m.command_manager.undo()),
]


def test_a_changed_page_never_keeps_its_frame_key(model, tmp_path):
    failures = []
    for name, op in _OPS:
        key, digest = table_objects.frame_key(model, 1), _digest(model)
        op(model)
        if table_objects.frame_key(model, 1) == key and _digest(model) != digest:
            failures.append(name)
    model.save_as(str(tmp_path / "saved.pdf"))
    key, digest = table_objects.frame_key(model, 1), _digest(model)
    model.command_manager.undo()
    if table_objects.frame_key(model, 1) == key and _digest(model) != digest:
        failures.append("undo after save")
    assert failures == []
