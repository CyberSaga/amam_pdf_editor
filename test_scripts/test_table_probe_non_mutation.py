"""Card A2 (plans/cad-vector-object-editing-handoff.md): the table probe never
changes the user's document (H1) and its cache is keyed on the page frame (H3)."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import fitz
import pytest

from model import table_objects
from model.pdf_model import PDFModel

_PROBE = (
    Path(__file__).resolve().parent.parent
    / "plans"
    / "cad-vector-object-editing-probes"
    / "p17_object_digest_cost.py"
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("p17_object_digest_cost", _PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _draw_table(page: fitz.Page) -> None:
    for r in range(4):
        for c in range(3):
            cell = fitz.Rect(100 + c * 120, 200 + r * 30, 100 + (c + 1) * 120, 200 + (r + 1) * 30)
            page.draw_rect(cell, color=(0, 0, 0), width=1)
            page.insert_text((cell.x0 + 5, cell.y0 + 20), f"R{r}C{c}", fontsize=11)


def _make_annotated_pdf(path: Path) -> Path:
    with fitz.open() as doc:
        for _ in range(3):
            _draw_table(doc.new_page(width=595, height=842))
        doc[0].insert_link(
            {"kind": fitz.LINK_URI, "from": fitz.Rect(100, 100, 200, 120), "uri": "https://example.com"}
        )
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = "f1"
        widget.rect = fitz.Rect(100, 100, 200, 120)
        doc[1].add_widget(widget)
        doc[2].add_text_annot(fitz.Point(120, 120), "note")
        doc.save(path)
    return path


@pytest.fixture
def model():
    m = PDFModel()
    yield m
    m.close()


@pytest.mark.parametrize("page_num", [1, 2, 3])
def test_table_rects_leaves_every_source_object_unchanged(model, tmp_path, page_num):
    probe = _load_probe()
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    before, *_ = probe.digest_table(model.doc)
    rects = table_objects.table_rects(model, page_num)
    after, *_ = probe.digest_table(model.doc)
    assert len(rects) == 1
    assert probe.differing(before, after) == []


def test_scratch_page_bytes_is_a_one_page_pdf_without_annotations(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    data = table_objects.scratch_page_bytes(model.doc, 3)
    with fitz.open(stream=data, filetype="pdf") as copy:
        assert len(copy) == 1
        assert list(copy[0].annots()) == []
    assert len(model.doc) == 3


def test_find_table_rects_returns_tuples_for_a_page():
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        _draw_table(page)
        rects = table_objects.find_table_rects(page)
    assert len(rects) == 1
    assert len(rects[0]) == 4


def test_frame_key_has_the_h3_shape(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    key = table_objects.frame_key(model, 1)
    # Page and the digest of the same one-page copy the worker detects on; no handle, no frame fields.
    payload = table_objects.PageInput(model, 1).payload
    assert key == (1, hashlib.sha256(payload).digest())


def test_rotate_pages_invalidates_cached_rects(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    table_objects.table_rects(model, 1)
    assert table_objects.cached_table_rects(model, 1) is not None
    model.rotate_pages([1], 90)
    assert table_objects.cached_table_rects(model, 1) is None
    rects = table_objects.table_rects(model, 1)
    expected = fitz.Rect(100, 200, 460, 320) * model.doc[0].rotation_matrix
    assert abs(rects[0].x0 - expected.x0) < 2 and abs(rects[0].y0 - expected.y0) < 2


def test_cached_table_rects_is_none_on_a_miss_and_does_no_work(model, tmp_path, monkeypatch):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))

    def boom(*_a, **_k):
        raise AssertionError("no work allowed")

    monkeypatch.setattr(table_objects, "find_table_rects", boom)
    assert table_objects.cached_table_rects(model, 1) is None


def test_store_table_rects_refuses_a_stale_key(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    key = table_objects.frame_key(model, 1)
    rect = fitz.Rect(1, 2, 3, 4)
    assert table_objects.store_table_rects(model, key, [rect]) is True
    assert table_objects.cached_table_rects(model, 1) == [rect]
    model.rotate_pages([1], 90)
    assert table_objects.store_table_rects(model, key, [rect]) is False
    assert table_objects.cached_table_rects(model, 1) is None


def test_table_rects_out_of_range_is_empty(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    assert table_objects.table_rects(model, 0) == []
    assert table_objects.table_rects(model, 99) == []


# --------------------------------------------------------------------------- D1/F1: handle identity


def _force_id_collision(monkeypatch) -> None:
    # Every handle gets the same id(): the deterministic form of CPython reusing the address of
    # a closed document for the next one (A3 review B2, owner decision D1).
    monkeypatch.setattr(table_objects, "id", lambda _obj: 42, raising=False)


def _make_other_pdf(path: Path) -> Path:
    """Same layout as ``_make_annotated_pdf`` but page 1 carries more text: other page bytes."""
    _make_annotated_pdf(path)
    with fitz.open(path) as doc:
        doc[0].insert_text((50, 60), "different bytes", fontsize=11)
        doc.saveIncr()
    return path


def test_another_document_with_other_page_bytes_never_sees_the_old_answer(model, tmp_path, monkeypatch):
    _force_id_collision(monkeypatch)
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    assert model.close_session(first) is True
    model.open_pdf(str(_make_other_pdf(tmp_path / "b.pdf")))
    assert table_objects.cached_table_rects(model, 1) is None
    assert table_objects.table_analysis_failed(model, 1) is False
    assert table_objects.table_analysis_failed(model, 2) is False


def test_snapshot_replacement_that_changes_the_page_bytes_drops_the_old_answer(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    old_key = table_objects.frame_key(model, 1)
    assert table_objects.store_table_rects(model, old_key, [fitz.Rect(1, 2, 3, 4)]) is True
    changed = fitz.open(stream=model.doc.tobytes(), filetype="pdf")
    changed[0].insert_text((50, 60), "changed", fontsize=11)
    model._restore_doc_from_snapshot(changed.tobytes())
    changed.close()
    assert table_objects.frame_key(model, 1) != old_key
    assert table_objects.cached_table_rects(model, 1) is None
    assert table_objects.store_table_rects(model, old_key, [fitz.Rect(1, 2, 3, 4)]) is False
    table_objects.mark_table_analysis_failed(model, old_key)
    assert table_objects.table_analysis_failed(model, 1) is False


def test_generation_is_stable_without_a_handle_change(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    generation = model.handle_generation
    model.rotate_pages([1], 90)
    model.doc = model.doc  # re-assigning the same handle is not a replacement
    assert model.handle_generation == generation


def test_switching_tabs_keeps_each_tabs_results(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    model.open_pdf(str(_make_other_pdf(tmp_path / "b.pdf")), append=True)
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(5, 6, 7, 8)])
    assert model.activate_session(first) is True
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(1, 2, 3, 4)]


def test_closing_one_of_two_tabs_keeps_the_answers_and_the_last_close_clears_them(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    model.open_pdf(str(_make_other_pdf(tmp_path / "b.pdf")), append=True)
    assert model.close_session(first) is True
    assert table_objects._cache(model) != {}  # entries do not name handles: nothing to retire
    assert table_objects._failed_keys(model) != {}
    assert model.close_session(model._active_session_id) is True
    assert not model.live_handle_generations()
    assert table_objects._cache(model) == {}
    assert table_objects._failed_keys(model) == {}


def test_an_entry_used_by_two_tabs_survives_closing_one(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    first = model._active_session_id
    table_objects.store_table_rects(model, table_objects.frame_key(model, 1), [fitz.Rect(1, 2, 3, 4)])
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "b.pdf")), append=True)  # identical page bytes
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(1, 2, 3, 4)]  # the second tab hits
    assert model.close_session(first) is True
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(1, 2, 3, 4)]


def test_snapshot_restore_with_same_bytes_hits_and_changed_bytes_never_serves_the_old_answer(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    old = model.handle_generation
    old_key = table_objects.frame_key(model, 1)
    table_objects.store_table_rects(model, old_key, [fitz.Rect(1, 2, 3, 4)])
    table_objects.mark_table_analysis_failed(model, table_objects.frame_key(model, 2))
    model._restore_doc_from_snapshot(model.doc.tobytes())
    assert model.handle_generation != old
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(1, 2, 3, 4)]  # same bytes: hit
    assert table_objects.table_analysis_failed(model, 2) is True
    changed = fitz.open(stream=model.doc.tobytes(), filetype="pdf")
    changed[0].insert_text((50, 60), "changed", fontsize=11)
    model._restore_doc_from_snapshot(changed.tobytes())
    changed.close()
    assert table_objects.frame_key(model, 1) != old_key
    assert table_objects.cached_table_rects(model, 1) is None  # changed bytes: miss
    assert table_objects.store_table_rects(model, old_key, [fitz.Rect(1, 2, 3, 4)]) is False


def test_the_cache_is_an_lru_capped_at_max_cached_pages(model, tmp_path):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    cap = table_objects.MAX_CACHED_PAGES
    keys = [(1, i.to_bytes(4, "big")) for i in range(cap + 1)]
    for key in keys[:cap]:
        table_objects._put(model, key, [(1, 2, 3, 4)])
    # A hit refreshes: the first key is used, so the second becomes the oldest.
    table_objects._cache(model).move_to_end(keys[0])
    table_objects._put(model, keys[cap], [(1, 2, 3, 4)])
    cache = table_objects._cache(model)
    assert len(cache) == cap
    assert keys[1] not in cache and keys[0] in cache and keys[cap] in cache


def test_257_distinct_keys_evict_the_oldest(model, tmp_path, monkeypatch):
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    monkeypatch.setattr(table_objects, "_key_is_current", lambda *_a, **_k: True)
    keys = [(1, i.to_bytes(4, "big")) for i in range(257)]
    for key in keys:
        table_objects.store_table_rects(model, key, [fitz.Rect(1, 2, 3, 4)])
        table_objects.mark_table_analysis_failed(model, key)
    assert len(table_objects._cache(model)) == 256
    assert keys[0] not in table_objects._cache(model) and keys[1] in table_objects._cache(model)
    assert len(table_objects._failed_keys(model)) == 256
    assert keys[0] not in table_objects._failed_keys(model)


def _page_digest(model: PDFModel) -> tuple[str, str]:
    """sha256 of a one-page copy of page 1 (no new /ID) and its text."""
    with fitz.open() as one:
        one.insert_pdf(model.doc, from_page=0, to_page=0)
        data = one.tobytes(no_new_id=True)
    return hashlib.sha256(data).hexdigest(), model.doc[0].get_text()


@pytest.mark.parametrize("outcome", ["complete", "analysis_failed", "crash"])
def test_delete_after_a_stale_table_answer_leaves_b_bytes_unchanged(qapp, model, tmp_path, monkeypatch, outcome):
    """Card D12 T14: a closed document's answer reaches a new document whose handle reuses the
    same id(); B's page bytes and text stay unchanged through click, delete and a forged id."""
    from model.object_requests import DeleteObjectRequest
    from test_scripts.qt_teardown import dispose_pdf_view
    from test_scripts.test_object_probe import _complete, _controller

    _force_id_collision(monkeypatch)
    model.open_pdf(str(_make_annotated_pdf(tmp_path / "a.pdf")))
    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    failures = []
    controller._object_probe.probe_failed.connect(lambda *a: failures.append(a))
    try:
        point = fitz.Point(170, 245)
        controller.lookup_object_at_point(1, point)  # A: the lookup is pending
        job = stub.order[0]
        assert model.close_session(model._active_session_id) is True
        model.open_pdf(str(_make_other_pdf(tmp_path / "b.pdf")))
        forged = fitz.Rect(10, 10, 50, 50)  # a table that exists in no document
        if outcome == "crash":
            stub.fail(job)
        elif outcome == "complete":
            stub.complete(job, _complete([[forged.x0, forged.y0, forged.x1, forged.y1]]))
        else:
            stub.complete(job, {"v": 2, "status": outcome})
        assert failures == []  # a stale answer of any kind is never reported ...
        assert stub.order == [job]  # ... never retried ...
        assert table_objects.cached_table_rects(model, 1) is None  # ... and never served to B
        assert table_objects.table_analysis_failed(model, 1) is False
        before = _page_digest(model)
        request = DeleteObjectRequest(
            object_id=table_objects.table_object_id(1, forged), object_kind="table", page_num=1
        )
        controller.lookup_object_at_point(1, point)  # click B: cold, a job of its own
        assert len(stub.order) == 2
        controller.delete_object(request)  # before B's answer: refused
        assert _page_digest(model) == before
        stub.complete(stub.order[1], _complete([]))  # B has no table
        controller.delete_object(request)  # after B's answer: the forged id matches nothing
        assert _page_digest(model) == before
    finally:
        dispose_pdf_view(view, controller, model)
