from __future__ import annotations

import json
import math
from pathlib import Path

import fitz
import pytest

from model import pdf_model as pdf_model_module
from model.edit_commands import SnapshotCommand
from model.pdf_model import PDFModel


@pytest.fixture
def model_with_text_pdf(tmp_path):
    path = tmp_path / "s.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path))
    doc.close()
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close_all_sessions()


def test_search_returns_results(model_with_text_pdf):
    results = model_with_text_pdf.tools.search.search_text("hello")
    assert len(results) >= 1
    page_num, context, rect = results[0]
    assert page_num == 1
    assert "hello" in context.lower()


def test_search_empty_returns_empty(model_with_text_pdf):
    assert model_with_text_pdf.tools.search.search_text("xyzzy_no_match") == []


def test_search_no_doc_returns_empty():
    assert PDFModel().tools.search.search_text("anything") == []


def test_search_tool_search_page(model_with_text_pdf):
    search = model_with_text_pdf.tools.search
    # Hit: same (page_num, context, rect) tuple shape as search_text.
    results = search.search_page(1, "hello")
    assert len(results) >= 1
    page_num, context, rect = results[0]
    assert page_num == 1
    assert "hello" in context.lower()
    assert results == search.search_text("hello")
    # No match on an existing page.
    assert search.search_page(1, "xyzzy_no_match") == []
    # Out-of-bounds pages return empty instead of raising.
    assert search.search_page(0, "hello") == []
    assert search.search_page(999, "hello") == []
    # No document open.
    assert PDFModel().tools.search.search_page(1, "hello") == []


def test_ocr_no_doc_returns_empty():
    assert PDFModel().tools.ocr.ocr_pages([1]) == {}


def test_ocr_invalid_page_raises(model_with_text_pdf):
    with pytest.raises((ValueError, RuntimeError)):
        model_with_text_pdf.tools.ocr.ocr_pages([999])


def test_add_highlight_rejects_page_zero(model_with_text_pdf):
    # Phase 2.4: page 0 must raise, not silently resolve doc[-1] (last page).
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_highlight(0, rect, (1.0, 1.0, 0.0, 0.5))
    assert len(list(model_with_text_pdf.doc[0].annots())) == 0  # no silent annotation


def test_add_rect_rejects_page_zero(model_with_text_pdf):
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_rect(0, rect, (1.0, 0.0, 0.0, 0.5), fill=False)
    assert len(list(model_with_text_pdf.doc[0].annots())) == 0


def test_add_highlight_rejects_out_of_range(model_with_text_pdf):
    rect = fitz.Rect(10, 10, 50, 30)
    with pytest.raises(ValueError):
        model_with_text_pdf.tools.annotation.add_highlight(999, rect, (1.0, 1.0, 0.0, 0.5))


@pytest.mark.parametrize(
    ("method_name", "expected_type"),
    [("add_underline", "Underline"), ("add_strikeout", "StrikeOut")],
)
def test_text_markup_methods_create_colored_annotations(
    model_with_text_pdf,
    method_name: str,
    expected_type: str,
) -> None:
    method = getattr(model_with_text_pdf.tools.annotation, method_name)

    method(1, fitz.Rect(70, 86, 145, 105), (0.1, 0.2, 0.9, 0.65))

    page = model_with_text_pdf.doc[0]
    annot = next(page.annots())
    assert annot.type[1] == expected_type
    assert annot.colors["stroke"] == pytest.approx([0.1, 0.2, 0.9])
    assert annot.opacity == pytest.approx(0.65, abs=0.01)
    assert len(annot.vertices or []) >= 4


@pytest.mark.parametrize("method_name", ["add_underline", "add_strikeout"])
def test_text_markup_methods_reject_page_zero_without_mutation(
    model_with_text_pdf,
    method_name: str,
) -> None:
    method = getattr(model_with_text_pdf.tools.annotation, method_name)
    with pytest.raises(ValueError):
        method(0, fitz.Rect(70, 86, 145, 105), (1.0, 0.0, 0.0, 1.0))
    assert list(model_with_text_pdf.doc[0].annots() or []) == []


def test_add_watermark_nan_angle_sanitized(model_with_text_pdf):
    # Phase 2.5: add_watermark must funnel through _coerce_wm so a NaN angle is
    # stored as the finite default instead of poisoning later rendering math.
    wm_id = model_with_text_pdf.tools.watermark.add_watermark([1], "DRAFT", angle=float("nan"))
    stored = next(
        wm for wm in model_with_text_pdf.tools.watermark.get_watermarks() if wm["id"] == wm_id
    )
    assert math.isfinite(stored["angle"])
    assert stored["angle"] == 0.0


def test_rawdict_text_compat_backfills_keyword_option(monkeypatch):
    sentinel = "_pdf_editor_rawdict_text_compat"

    def fake_get_text(page, option="text", *args, **kwargs):
        selected_option = kwargs.get("option", option)
        if selected_option != "rawdict":
            return "plain text"
        return {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "chars": [
                                        {"c": "H"},
                                        {"c": "i"},
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(fitz.Page, sentinel, False, raising=False)
    monkeypatch.setattr(fitz.Page, "get_text", fake_get_text)
    pdf_model_module._install_rawdict_text_compat()

    doc = fitz.open()
    try:
        page = doc.new_page()
        rawdict = page.get_text(option="rawdict")
    finally:
        doc.close()

    span = rawdict["blocks"][0]["lines"][0]["spans"][0]
    assert span["text"] == "Hi"


def test_close_all_sessions_tolerates_new_bypass_instance():
    model = PDFModel.__new__(PDFModel)

    model.close_all_sessions()
    model.__del__()


# --- F17-COH-3: a watermark belongs to its PAGE, not to a page number -----------
# The dialog stores the pages as numbers, and reorder / delete / insert / merge
# used to leave those numbers alone: after a structural op the watermark sat on
# whichever page now held the number -- in the view, in print and in the saved
# file -- and a deleted page left a number that named no page.  The numbers now
# follow the page they were chosen for (see ``WatermarkTool.on_pages_restructured``),
# an op that drops a watermark's last page hides the watermark with it, and
# undo / redo bring the exact lists back.


def _write_labelled_pdf(path: Path, labels: list[str]) -> Path:
    """One page per label, the label as the page's only text."""
    doc = fitz.open()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=12, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def _labelled_model(tmp_path: Path, labels: list[str], name: str = "labelled.pdf") -> PDFModel:
    path = _write_labelled_pdf(tmp_path / name, labels)
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _page_labels(model: PDFModel) -> list[str]:
    """Text of every page in order ('' is a blank page)."""
    return [page.get_text("text").strip() for page in model.doc]


def _stamped_labels(model: PDFModel) -> list[str]:
    """Text of every page the live overlay stamps ('' is a blank page)."""
    sid = model.get_active_session_id()
    return [
        label
        for page_num, label in enumerate(_page_labels(model), start=1)
        if model.tools.watermark.needs_page_overlay(sid, page_num, "view")
    ]


def _wm_lists(model: PDFModel) -> list[tuple[str, list[int]]]:
    return [(wm["text"], list(wm["pages"])) for wm in model.tools.watermark.get_watermarks()]


def _wm_pages(model: PDFModel) -> dict[str, list[int]]:
    return dict(_wm_lists(model))


def _record_snapshot_command(model: PDFModel, command_type: str, operation):
    """Run ``operation`` and record it the way the controller records a structural op."""
    before = model._capture_doc_snapshot()
    result = operation()
    after = model._capture_doc_snapshot()
    model.command_manager.record(SnapshotCommand(model, command_type, result, before, after, command_type))
    return result


@pytest.fixture
def abc_model(tmp_path):
    model = _labelled_model(tmp_path, ["A", "B", "C"])
    yield model
    model.close_all_sessions()


@pytest.fixture
def import_source(tmp_path) -> Path:
    return _write_labelled_pdf(tmp_path / "source.pdf", ["X", "Y"])


@pytest.mark.parametrize(
    ("operation", "labels_after", "pages_after"),
    [
        pytest.param(lambda m, s: m.move_page(1, 0), ["B", "A", "C"], [1], id="move_b_to_front"),
        pytest.param(lambda m, s: m.move_page(0, 2), ["B", "C", "A"], [1], id="move_a_to_end"),
        pytest.param(lambda m, s: m.move_page(2, 0), ["C", "A", "B"], [3], id="move_c_to_front"),
        pytest.param(lambda m, s: m.move_page(1, 2), ["A", "C", "B"], [3], id="move_b_over_c"),
        pytest.param(lambda m, s: m.delete_pages([1]), ["B", "C"], [1], id="delete_a"),
        pytest.param(lambda m, s: m.delete_pages([3]), ["A", "B"], [2], id="delete_c"),
        pytest.param(lambda m, s: m.insert_blank_page(1), ["", "A", "B", "C"], [3], id="blank_before_a"),
        pytest.param(lambda m, s: m.insert_blank_page(3), ["A", "B", "", "C"], [2], id="blank_after_b"),
        pytest.param(lambda m, s: m.insert_blank_page(99), ["A", "B", "C", ""], [2], id="blank_at_end"),
        pytest.param(
            lambda m, s: m.insert_pages_from_file(str(s), [1, 2], 1), ["X", "Y", "A", "B", "C"], [4], id="import_before_a"
        ),
        pytest.param(lambda m, s: m.insert_pages_from_file(str(s), [2], 2), ["A", "Y", "B", "C"], [3], id="import_between"),
    ],
)
def test_watermark_stays_on_its_page_through_a_structural_op(
    abc_model, import_source, operation, labels_after, pages_after
):
    model = abc_model
    model.tools.watermark.add_watermark([2], "STAMP")  # page "B"
    assert _stamped_labels(model) == ["B"]

    operation(model, import_source)

    assert _page_labels(model) == labels_after
    assert _stamped_labels(model) == ["B"]
    assert _wm_pages(model) == {"STAMP": pages_after}


def test_a_multi_page_watermark_follows_each_of_its_pages(tmp_path):
    model = _labelled_model(tmp_path, ["A", "B", "C", "D"])
    try:
        model.tools.watermark.add_watermark([1, 3], "STAMP")  # A and C
        model.delete_pages([2])
        assert _wm_pages(model) == {"STAMP": [1, 2]}
        model.move_page(0, 2)  # [C, D, A]
        assert _wm_pages(model) == {"STAMP": [1, 3]}
        assert _stamped_labels(model) == ["C", "A"]
    finally:
        model.close_all_sessions()


def test_deleting_the_last_page_of_a_watermark_removes_it_with_the_page(abc_model):
    model = abc_model
    model.tools.watermark.add_watermark([2], "GONE")
    model.tools.watermark.add_watermark([1, 2], "KEEP")
    sid = model.get_active_session_id()

    model.delete_pages([2])

    assert _wm_pages(model) == {"KEEP": [1]}  # no entry left naming no page
    assert _stamped_labels(model) == ["A"]
    clone = model.tools.prepare_doc_for_save(sid)
    try:
        assert clone is not None
        saved = json.loads(clone.embfile_get(model.tools.watermark.WATERMARK_EMBED_NAME))
        assert [wm["text"] for wm in saved] == ["KEEP"]  # nothing saved for the removed one
    finally:
        if clone is not None:
            clone.close()


def test_a_session_whose_every_watermark_lost_its_page_saves_without_a_clone(abc_model):
    model = abc_model
    model.tools.watermark.add_watermark([3], "ONLYC")
    model.delete_pages([3])
    assert model.tools.watermark.get_watermarks() == []
    assert model.tools.prepare_doc_for_save(model.get_active_session_id()) is None


def test_delete_everything_leaves_no_watermark_on_the_placeholder_page(abc_model):
    model = abc_model
    model.tools.watermark.add_watermark([1, 2, 3], "ALL")
    model.delete_pages([1, 2, 3])
    assert model.blank_placeholder_active
    assert model.tools.watermark.get_watermarks() == []
    assert _stamped_labels(model) == []


def test_an_import_over_the_placeholder_page_carries_no_old_watermark(abc_model, import_source):
    model = abc_model
    model.tools.watermark.add_watermark([1, 2, 3], "ALL")
    model.delete_pages([1, 2, 3])
    model.insert_pages_from_file(str(import_source), [1, 2], 1)
    assert model.tools.watermark.get_watermarks() == []
    assert _stamped_labels(model) == []


def test_an_all_pages_watermark_does_not_grow_onto_new_pages(abc_model, import_source):
    """Pins today's reading of the dialog's all-pages choice: it stores explicit numbers, so
    inserted pages are NOT covered.  Whether they should inherit it is an owner question."""
    model = abc_model
    model.tools.watermark.add_watermark([1, 2, 3], "ALL")
    model.insert_blank_page(2)
    model.insert_pages_from_file(str(import_source), [1], 1)
    assert _page_labels(model) == ["X", "A", "", "B", "C"]
    assert _wm_pages(model) == {"ALL": [2, 4, 5]}


def test_undo_and_redo_of_a_structural_op_restore_the_exact_lists(tmp_path):
    model = _labelled_model(tmp_path, ["A", "B", "C", "D"])
    try:
        model.tools.watermark.add_watermark([1, 2, 3, 4], "ALL")
        model.tools.watermark.add_watermark([3], "ONLYC")
        model.tools.watermark.add_watermark([2, 3], "BC")
        original = _wm_lists(model)

        _record_snapshot_command(model, "delete_pages", lambda: model.delete_pages([2, 3]))
        after = _wm_lists(model)
        assert after == [("ALL", [1, 2])]

        assert model.command_manager.undo()
        assert _wm_lists(model) == original
        assert _stamped_labels(model) == ["A", "B", "C", "D"]

        assert model.command_manager.redo()
        assert _wm_lists(model) == after
    finally:
        model.close_all_sessions()


@pytest.mark.parametrize(
    ("command_type", "operation", "pages_after"),
    [
        ("move_page", lambda m, s: m.move_page(0, 2), [1]),
        ("insert_blank_page", lambda m, s: m.insert_blank_page(1), [3]),
        ("insert_pages_from_file", lambda m, s: m.insert_pages_from_file(str(s), [1, 2], 2), [4]),
        ("delete_pages", lambda m, s: m.delete_pages([1]), [1]),
    ],
)
def test_undo_redo_round_trip_keeps_the_watermark_on_its_page(
    abc_model, import_source, command_type, operation, pages_after
):
    model = abc_model
    model.tools.watermark.add_watermark([2], "STAMP")
    original = _wm_pages(model)
    assert original == {"STAMP": [2]}

    _record_snapshot_command(model, command_type, lambda: operation(model, import_source))
    assert _wm_pages(model) == {"STAMP": pages_after}
    assert _stamped_labels(model) == ["B"]

    for _ in range(2):  # twice: the restored state must stay usable
        assert model.command_manager.undo()
        assert _wm_pages(model) == original
        assert _stamped_labels(model) == ["B"]
        assert model.command_manager.redo()
        assert _wm_pages(model) == {"STAMP": pages_after}
        assert _stamped_labels(model) == ["B"]


def test_a_watermark_added_after_a_structural_op_stays_on_its_page_through_undo_and_redo(abc_model):
    model = abc_model
    _record_snapshot_command(model, "move_page", lambda: model.move_page(0, 2))  # [B, C, A]
    model.tools.watermark.add_watermark([3], "LATE")  # page "A"
    assert _stamped_labels(model) == ["A"]

    assert model.command_manager.undo()  # [A, B, C]
    assert _wm_pages(model) == {"LATE": [1]}
    assert _stamped_labels(model) == ["A"]

    assert model.command_manager.redo()
    assert _wm_pages(model) == {"LATE": [3]}
    assert _stamped_labels(model) == ["A"]


def test_a_watermark_removed_after_a_structural_op_is_not_brought_back_by_undo(abc_model):
    model = abc_model
    wm_id = model.tools.watermark.add_watermark([1], "STAMP")
    _record_snapshot_command(model, "delete_pages", lambda: model.delete_pages([2]))
    assert model.tools.watermark.remove_watermark(wm_id)

    assert model.command_manager.undo()

    assert model.tools.watermark.get_watermarks() == []
    assert _stamped_labels(model) == []


def test_a_watermark_hidden_with_its_deleted_page_comes_back_whole_on_undo(abc_model):
    """A watermark whose page is gone is hidden (not editable); when undo brings the page
    back the very same entry -- id and parameters -- is shown again."""
    model = abc_model
    wm_id = model.tools.watermark.add_watermark([2], "STAMP", angle=10, opacity=0.25)
    _record_snapshot_command(model, "delete_pages", lambda: model.delete_pages([2]))
    assert model.tools.watermark.get_watermarks() == []
    assert not model.tools.watermark.update_watermark(wm_id, text="NOPE")
    assert not model.tools.watermark.remove_watermark(wm_id)

    assert model.command_manager.undo()

    (wm,) = model.tools.watermark.get_watermarks()
    assert (wm["id"], wm["text"], wm["angle"], wm["opacity"], wm["pages"]) == (wm_id, "STAMP", 10.0, 0.25, [2])


def test_a_failed_structural_op_rolls_the_watermark_lists_back(abc_model, monkeypatch):
    model = abc_model
    model.tools.watermark.add_watermark([2, 3], "STAMP")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pdf_model_module.outline_ops, "follow_dropped_names", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        model.delete_pages([1])

    assert len(model.doc) == 3
    assert _wm_pages(model) == {"STAMP": [2, 3]}
    assert _stamped_labels(model) == ["B", "C"]


def test_structural_ops_do_not_mark_the_watermarks_modified(abc_model):
    """Dirtiness of a structural op belongs to its command; the tool must not make a
    fully undone session look modified."""
    model = abc_model
    model.tools.watermark.add_watermark([2], "STAMP")
    sid = model.get_active_session_id()
    model.tools.watermark.on_session_saved(sid)
    assert not model.tools.watermark.has_unsaved_changes(sid)

    _record_snapshot_command(model, "move_page", lambda: model.move_page(1, 0))
    assert model.command_manager.undo()

    assert not model.tools.watermark.has_unsaved_changes(sid)


def test_a_page_structure_change_that_skipped_the_hook_is_detected_and_healed(abc_model, caplog):
    """Safety net behind the source scan: an op that changed the page list without telling
    the tools must neither crash nor leave numbers past the end."""
    model = abc_model
    model.tools.watermark.add_watermark([2, 3], "STAMP")

    with caplog.at_level("ERROR"):
        model.doc.delete_page(0)  # bypasses PDFModel's structural chokepoint
        pages = _wm_pages(model)

    assert all(1 <= page <= len(model.doc) for page in pages["STAMP"])
    assert any("without notifying" in record.getMessage() for record in caplog.records)


def test_tool_manager_fans_the_page_hooks_out_to_every_extension(abc_model):
    from model.tools.base import ToolExtension

    seen: list[tuple] = []

    class _Probe(ToolExtension):
        def on_pages_restructured(self, session_id, origins, old_count):
            seen.append(("restructured", list(origins), old_count))

        def capture_page_state(self, session_id):
            seen.append(("capture",))
            return {"probe": 1}

        def restore_page_state(self, session_id, state):
            seen.append(("restore", state))

        def prepare_derived_document(self, session_id, doc, origins):
            seen.append(("derived", list(origins)))

    model = abc_model
    model.tools._extensions.append(_Probe())
    sid = "probe-session"  # a session no real tool tracks: only the probe reacts

    model.tools.on_pages_restructured(sid, [2, None], 3)
    states = model.tools.capture_page_state(sid)
    model.tools.restore_page_state(sid, states)
    model.tools.prepare_derived_document(sid, model.doc, [1])

    assert seen == [("restructured", [2, None], 3), ("capture",), ("restore", {"probe": 1}), ("derived", [1])]
    # The base class stays a no-op for tools that hold no page-bound state.
    base = ToolExtension()
    assert base.capture_page_state(sid) is None
    assert base.on_pages_restructured(sid, [1], 1) is None


def test_restoring_plain_bytes_leaves_the_watermark_pages_alone(abc_model):
    """GUARD: bytes without a ``page_state`` (mocks, older callers) restore the document only."""
    model = abc_model
    model.tools.watermark.add_watermark([2], "STAMP")
    plain = bytes(model._capture_doc_snapshot())
    model.move_page(1, 0)
    assert _wm_pages(model) == {"STAMP": [1]}

    model.replace_active_document_from_snapshot(plain, [1])

    assert _page_labels(model) == ["A", "B", "C"]
    assert _wm_pages(model) == {"STAMP": [1]}  # untouched: it is the caller's job to pass page_origins


def test_a_page_state_that_does_not_fit_the_restored_document_falls_back_to_the_numbers(abc_model, caplog):
    """GUARD: a forged / stale snapshot must not install an id list of the wrong length."""
    model = abc_model
    model.tools.watermark.add_watermark([2, 3], "STAMP")
    snapshot = model._capture_doc_snapshot()
    snapshot.page_state = {"WatermarkTool": (0, 1)}  # two ids for a three-page document

    with caplog.at_level("ERROR"):
        model._restore_doc_from_snapshot(snapshot)

    assert any("does not fit" in record.getMessage() for record in caplog.records)
    assert _wm_pages(model) == {"STAMP": [2, 3]}
    assert _stamped_labels(model) == ["B", "C"]
