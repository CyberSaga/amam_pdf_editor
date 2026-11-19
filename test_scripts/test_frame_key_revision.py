"""H3 / H22: ``table_objects.frame_key`` must change whenever what table detection sees changes.

``edit_count`` did not follow the page: undo and redo never touch it, and a page-snapshot undo keeps
the handle, so the pre-undo table answer was served after the undo (D1 review, finding A).  Two
hand-kept stand-ins for "did detection's input change" (the revision, then a content fingerprint)
each missed a case, so the key is now the SHA-256 of the one-page scratch copy detection reads
(owner decision, option 1, 2026-11-19).

The class check, on an outcome rather than a list of causes: after any document-changing
operation, if a FRESH detection on a new scratch copy differs from the one before, the key must
differ.  The oracle is detection itself, not the key's own input, so it is no tautology.
"""
from __future__ import annotations

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


def _grid_page(page: fitz.Page, text: str | None = None) -> None:
    for i in range(4):
        v = 50 + i * 50
        page.draw_line((v, 50), (v, 200))
        page.draw_line((50, v), (200, v))
    if text:
        page.insert_text((60, 80), text, fontsize=12)


def _tables(model: PDFModel) -> list:
    """Oracle: a fresh detection on a new scratch copy of page 1; the cache is bypassed."""
    scratch = fitz.open(stream=table_objects.scratch_page_bytes(model.doc, 1), filetype="pdf")
    try:
        return table_objects.find_table_rects(scratch[0])
    finally:
        scratch.close()


@pytest.fixture
def table_model(tmp_path):
    """595 x 842 page with a ruled 3 x 3 grid and text in a cell: detection finds one table."""
    path = tmp_path / "table.pdf"
    with fitz.open() as doc:
        _grid_page(doc.new_page(width=595, height=842), "cell")
        doc.save(path)
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close()


@pytest.fixture
def grid_model(tmp_path):
    """300 x 300 page, 3 x 3 ruled grid, no text: detection finds no table."""
    path = tmp_path / "grid.pdf"
    with fitz.open() as doc:
        _grid_page(doc.new_page(width=300, height=300))
        doc.save(path)
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close()


@pytest.fixture
def form_model(tmp_path):
    """Page 1 shows the ruled table and its text only through a Form XObject."""
    with fitz.open() as src:
        _grid_page(src.new_page(width=300, height=300), "cell")
        path = tmp_path / "form.pdf"
        with fitz.open() as doc:
            page = doc.new_page(width=300, height=300)
            xref = page.show_pdf_page(page.rect, src, 0)
            doc.save(path)
    m = PDFModel()
    m.open_pdf(str(path))
    m._form_xref = xref
    yield m
    m.close()


class _Span:
    bbox = (55.0, 55.0, 95.0, 75.0)
    text = "cell"
    confidence = 1.0


def _ocr_with_failing_rebuild(model: PDFModel) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("index rebuild failed")

    real = model.block_manager.rebuild_page
    model.block_manager.rebuild_page = boom
    try:
        with pytest.raises(RuntimeError):
            model.apply_ocr_spans(1, [_Span()])
    finally:
        model.block_manager.rebuild_page = real


def _overwrite_form_stream(model: PDFModel) -> None:
    # A writer that skips the revision: direct write, no tick.
    model.doc.update_stream(model._form_xref, b"q Q\n")


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


def test_key_is_stable_without_a_change(model):
    # Two scratch builds of an unchanged page are byte-identical (no_new_id), so the key is a hit key.
    assert table_objects.frame_key(model, 1) == table_objects.frame_key(model, 1)


def test_oracle_sees_a_form_xobject_only_change(form_model):
    # Negative control: the outer /Contents is unchanged, only the Form stream is overwritten, and
    # detection goes from 1 table to 0.  An oracle that read only /Contents would miss it.
    assert len(_tables(form_model)) == 1
    outer = form_model.doc[0].read_contents()
    key = table_objects.frame_key(form_model, 1)
    _overwrite_form_stream(form_model)
    assert form_model.doc[0].read_contents() == outer
    assert _tables(form_model) == []
    assert table_objects.frame_key(form_model, 1) != key


def test_failed_ocr_cannot_reuse_pre_ocr_tables(grid_model):
    assert _tables(grid_model) == []
    old_key = table_objects.frame_key(grid_model, 1)
    assert table_objects.store_table_rects(grid_model, old_key, [])
    assert table_objects.cached_table_rects(grid_model, 1) == []
    _ocr_with_failing_rebuild(grid_model)
    assert len(_tables(grid_model)) == 1  # the real write happened
    assert table_objects.cached_table_rects(grid_model, 1) is None
    assert table_objects.store_table_rects(grid_model, old_key, []) is False


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


def test_a_revision_tick_without_a_page_change_keeps_the_key(model):
    # By decision the key follows the page's bytes, not the revision: a write of edit_count or a
    # replaced command manager changes nothing detection reads, so a cached answer stays a hit.
    # (``content_revision`` itself stays on the model for the H22 slice guard.)
    from model.edit_commands import CommandManager

    key = table_objects.frame_key(model, 1)
    revision = model.content_revision
    model.edit_count = model.edit_count
    model.command_manager = CommandManager()
    assert model.content_revision != revision
    assert table_objects.frame_key(model, 1) == key


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


def _step(model, op) -> str | None:
    """Run ``op``; ``"kept"`` when detection changed but the key did not (the bug), ``"changed"``
    when detection changed and the key followed, ``None`` when detection did not change."""
    key, tables = table_objects.frame_key(model, 1), _tables(model)
    op(model)
    if _tables(model) == tables:
        return None
    return "kept" if table_objects.frame_key(model, 1) == key else "changed"


def _run_ops(model, ops) -> tuple[list[str], int]:
    """(operations whose detection change the key missed, operations that changed detection)."""
    failures: list[str] = []
    changed = 0
    for name, op in ops:
        outcome = _step(model, op)
        changed += outcome is not None
        if outcome == "kept":
            failures.append(name)
    return failures, changed


def test_a_failed_ocr_write_never_keeps_its_frame_key(grid_model):
    failures, changed = _run_ops(grid_model, [("ocr, index rebuild fails", _ocr_with_failing_rebuild)])
    assert changed == 1  # no table -> one table: the check is not vacuous
    assert failures == []


def test_a_form_xobject_write_never_keeps_its_frame_key(form_model):
    failures, changed = _run_ops(form_model, [("form stream overwrite", _overwrite_form_stream)])
    assert changed == 1  # one table -> none
    assert failures == []


def test_a_changed_page_never_keeps_its_frame_key(table_model, tmp_path):
    failures, changed = _run_ops(table_model, _OPS)
    assert changed >= 1  # the rotation moves the table: the check is not vacuous
    model = table_model
    model.save_as(str(tmp_path / "saved.pdf"))
    if _step(model, lambda m: m.command_manager.undo()) == "kept":
        failures.append("undo after save")
    assert failures == []
