"""Table cache keyed on the one-page scratch copy (CAD handoff, owner decision option 1, 2026-11-19).

The key's last field is the SHA-256 of the same bytes the worker detects on, so any change to
what detection reads (a Form XObject reached through ``N 1 R`` included) is a new key by
construction.  Three observable outcomes:

1. a change invalidates the old answer, and a worker from before the change cannot overwrite the
   new state;
2. detectable means selectable (a direct page dictionary), and a failed copy is never cached;
3. no change gives a real hit that builds exactly one copy per click and dispatches no job.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from controller.object_probe_coordinator import ObjectProbeCoordinator
from model import table_objects
from model.object_requests import OBJECT_LOOKUP_PENDING
from model.pdf_model import PDFModel
from test_scripts.test_object_probe import TABLE_RECT, StubRunner, _complete, _controller, _table_pdf

ROOT = Path(__file__).resolve().parent.parent
ISSUE18208 = ROOT / "test_files" / "mozilla-pdf" / "issue18208.pdf"

# --------------------------------------------------------------------------- synthetic PDFs

_GRID = b"".join(
    f"{50 + i * 50} 50 m {50 + i * 50} 200 l S\n50 {50 + i * 50} m 200 {50 + i * 50} l S\n".encode()
    for i in range(4)
)
_TEXT = b"BT /F1 12 Tf 60 150 Td (cell) Tj ET\n"
_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
#: visual frame (top-left origin) of the ruled grid on a 300 x 300 page
_GRID_POINT = fitz.Point(120, 170)


def _stream(data: bytes, extra: bytes = b"") -> bytes:
    return b"<< /Length %d %s>>\nstream\n" % (len(data), extra) + data + b"\nendstream"


def _raw_pdf(objects: dict[int, tuple[int, bytes]]) -> bytes:
    """``objects``: number -> (generation, body).  Object 1 is the catalog; the xref table records
    each generation, so a reference ``N 1 R`` is a real generation-1 reference."""
    out = bytearray(b"%PDF-1.5\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        generation, body = objects[number]
        offsets[number] = len(out)
        out += f"{number} {generation} obj\n".encode() + body + b"\nendobj\n"
    size = max(objects) + 1
    xref_at = len(out)
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        if number in offsets:
            out += f"{offsets[number]:010d} {objects[number][0]:05d} n \n".encode()
        else:
            out += b"0000000000 65535 f \n"
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


#: object number of the Form XObject that is referenced as ``5 1 R``
FORM_XREF = 5


def _form_generation_one_pdf() -> bytes:
    """Page 1 shows its ruled table and the text only through a Form XObject referenced as ``5 1 R``."""
    return _raw_pdf(
        {
            1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
            2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
            3: (
                0,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R"
                b" /Resources << /XObject << /Fm0 5 1 R >> >> >>",
            ),
            4: (0, _stream(b"/Fm0 Do\n")),
            FORM_XREF: (
                1,
                _stream(
                    _GRID + _TEXT,
                    b"/Type /XObject /Subtype /Form /BBox [0 0 300 300]"
                    b" /Resources << /Font << /F1 " + _FONT + b" >> >> ",
                ),
            ),
        }
    )


def _direct_page_pdf() -> bytes:
    """The page dictionary is a direct object inside ``/Kids``: ``page.xref == 0``."""
    return _raw_pdf(
        {
            1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
            2: (
                0,
                b"<< /Type /Pages /Count 1 /Kids [ << /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300]"
                b" /Contents 4 0 R /Resources << /Font << /F1 " + _FONT + b" >> >> >> ] >>",
            ),
            4: (0, _stream(_GRID + _TEXT)),
        }
    )


@pytest.fixture
def form_model(tmp_path):
    path = tmp_path / "form_gen1.pdf"
    path.write_bytes(_form_generation_one_pdf())
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close()


@pytest.fixture
def direct_model(tmp_path):
    path = tmp_path / "direct.pdf"
    path.write_bytes(_direct_page_pdf())
    m = PDFModel()
    m.open_pdf(str(path))
    yield m
    m.close()


@pytest.fixture
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(_table_pdf(tmp_path / "t.pdf"))
    yield m
    m.close()


@pytest.fixture
def copies(monkeypatch) -> list[int]:
    """Page numbers of every ``scratch_page_bytes`` call (the one-copy-per-click count)."""
    calls: list[int] = []
    real = table_objects.scratch_page_bytes

    def counting(doc, page_num):
        calls.append(page_num)
        return real(doc, page_num)

    monkeypatch.setattr(table_objects, "scratch_page_bytes", counting)
    return calls


# --------------------------------------------------------------------------- helpers


def _fresh(model: PDFModel, page_num: int = 1) -> list[fitz.Rect]:
    """Detection on a new scratch copy; the cache is bypassed."""
    with fitz.open(stream=table_objects.scratch_page_bytes(model.doc, page_num), filetype="pdf") as scratch:
        return [fitz.Rect(r) for r in table_objects.find_table_rects(scratch[0])]


def _run_worker(runner: StubRunner, job_id: int) -> None:
    """What the child does: detect on the job's own bytes and answer."""
    payload = runner.jobs[job_id][2][0]
    with fitz.open(stream=payload, filetype="pdf") as scratch:
        rects = table_objects.find_table_rects(scratch[0])
    runner.complete(job_id, _complete([list(r) for r in rects]))


def _click(model: PDFModel, coord: ObjectProbeCoordinator, runner: StubRunner, point: fitz.Point):
    """The normal non-blocking click: lookup; on pending the coordinator's job answers; lookup again."""
    info = model.get_object_info_at_point(1, point, blocking=False)
    if info is OBJECT_LOOKUP_PENDING:
        before = len(runner.order)
        coord.request_tables(1)
        if len(runner.order) > before:
            _run_worker(runner, runner.order[-1])
        info = model.get_object_info_at_point(1, point, blocking=False)
    return info


def _bboxes(info) -> list[fitz.Rect]:
    return [] if info is None else [fitz.Rect(info.bbox)]


# --------------------------------------------------------------------------- outcome 1


def _change_then_check(
    model, form_xref: int, new_stream: bytes, point: fitz.Point, expected_before: int, expected_after: int
) -> None:
    runner = StubRunner()
    coord = ObjectProbeCoordinator(model, runner=runner)

    fresh_before = _fresh(model)
    assert len(fresh_before) == expected_before
    primed = _click(model, coord, runner, point)  # the normal path stores the answer
    assert primed is not OBJECT_LOOKUP_PENDING
    assert _bboxes(primed) == fresh_before
    assert table_objects.cached_table_rects(model, 1) == fresh_before
    old_key = table_objects.frame_key(model, 1)

    # A writer that skips every tick: only the Form stream changes, the outer /Contents does not.
    outer = model.doc[0].read_contents()
    model.doc.update_stream(form_xref, new_stream)
    assert model.doc[0].read_contents() == outer
    fresh_after = _fresh(model)
    assert len(fresh_after) == expected_after  # the change is a real detection change

    assert table_objects.frame_key(model, 1) != old_key
    assert table_objects.cached_table_rects(model, 1) is None  # the old answer is not served
    info = _click(model, coord, runner, point)
    assert _bboxes(info) == fresh_after  # normal selection equals a detection that bypasses the cache
    assert table_objects.cached_table_rects(model, 1) == fresh_after

    # A worker from before the change, answering late, does not replace the new state.
    assert table_objects.store_table_rects(model, old_key, fresh_before) is False
    assert table_objects.cached_table_rects(model, 1) == fresh_after
    assert _bboxes(model.get_object_info_at_point(1, point, blocking=False)) == fresh_after


def test_generation_one_form_write_invalidates_the_old_answer(form_model):
    assert b"5 1 R" in form_model.doc.xref_object(3, compressed=True).encode()
    _change_then_check(form_model, FORM_XREF, b"q Q\n", _GRID_POINT, expected_before=1, expected_after=0)


@pytest.mark.needs_fixtures
@pytest.mark.skipif(not ISSUE18208.exists(), reason="test_files/mozilla-pdf/issue18208.pdf not present")
def test_issue18208_generation_one_form_write_invalidates_the_old_answer():
    # Page 1 shows Form 207 as ``/XObject0 207 1 R``.  The Form is the stamp at the page's top right
    # (BBox 136.5 x 45.8 at x 451, y 792) and holds no table, so overwriting it with "q Q" changes
    # nothing detectable.  The replacement stream draws a ruled grid with text in a font of the
    # Form's own resources: the page gains one table that no other stream carries (0 -> 1).
    grid = b"".join(
        f"{10 + i * 40} 5 m {10 + i * 40} 40 l S\n10 {5 + i * 12} m 130 {5 + i * 12} l S\n".encode()
        for i in range(4)
    )
    new_stream = b"0 G 1 w\n" + grid + b"BT /Font2 8 Tf 14 28 Td (cell) Tj ET\n"
    m = PDFModel()
    m.open_pdf(str(ISSUE18208))
    try:
        assert m.doc.xref_get_key(m.doc[0].xref, "Resources/XObject") == ("dict", "<</XObject0 207 1 R>>")
        _change_then_check(m, 207, new_stream, fitz.Point(520, 28), expected_before=0, expected_after=1)
    finally:
        m.close()


def test_a_late_worker_answer_after_a_form_write_is_dropped_and_the_new_job_decides(form_model):
    runner = StubRunner()
    coord = ObjectProbeCoordinator(form_model, runner=runner)
    ready: list[int] = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)  # the worker starts on the pre-change bytes
    late_job = runner.order[0]
    stale_payload = runner.jobs[late_job][2][0]
    form_model.doc.update_stream(FORM_XREF, b"q Q\n")  # no tick
    with fitz.open(stream=stale_payload, filetype="pdf") as scratch:
        stale = table_objects.find_table_rects(scratch[0])
    assert len(stale) == 1  # the worker really found the old table
    runner.complete(late_job, _complete([list(r) for r in stale]))
    assert ready == []
    assert table_objects.cached_table_rects(form_model, 1) is None
    assert table_objects.table_analysis_failed(form_model, 1) is False
    assert _bboxes(_click(form_model, coord, runner, _GRID_POINT)) == []  # the new state: no table


# --------------------------------------------------------------------------- outcome 2


def test_the_direct_page_dictionary_selects_its_table_through_the_click_path(direct_model):
    assert direct_model.doc[0].xref == 0  # not repaired into an indirect page
    fresh = _fresh(direct_model)
    assert len(fresh) == 1
    runner = StubRunner()
    coord = ObjectProbeCoordinator(direct_model, runner=runner)
    first = _click(direct_model, coord, runner, _GRID_POINT)
    assert first is not None and first.object_kind == "table"
    assert _bboxes(first) == fresh
    again = direct_model.get_object_info_at_point(1, _GRID_POINT, blocking=False)  # a real hit now
    assert again == first
    assert direct_model.get_object_info_at_point(1, fitz.Point(280, 280), blocking=False) is None


def test_a_failed_copy_is_never_cached_as_no_tables(qapp, model, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    point = fitz.Point(170, 245)
    try:
        with monkeypatch.context() as patch:
            def boom(doc, page_num):
                raise RuntimeError("scratch copy failed")

            patch.setattr(table_objects, "scratch_page_bytes", boom)
            info = controller.lookup_object_at_point(1, point)  # nothing raises out of the click path
            assert info is not OBJECT_LOOKUP_PENDING  # a click that cannot be answered must not wait
            assert stub.order == []  # no job without bytes
            assert table_objects.cached_table_rects(model, 1) is None
            assert table_objects.table_rects(model, 1) == []  # the blocking path never raises either
            assert controller.object_op_ready([1], ["table"]) is False  # refused, no raise
            assert stub.order == []
            assert table_objects._cache(model) == {}  # never stored as "no tables" ...
            assert not table_objects._failed_keys(model)  # ... nor under any key
        # Nothing was poisoned: with the copy working again the same page is analysed.
        assert controller.lookup_object_at_point(1, point) is OBJECT_LOOKUP_PENDING
        assert len(stub.order) == 1
    finally:
        dispose_pdf_view(view, controller, model)


def test_a_failed_copy_at_answer_time_stores_and_marks_nothing(model, monkeypatch):
    runner = StubRunner()
    coord = ObjectProbeCoordinator(model, runner=runner)
    ready: list[int] = []
    failures: list[tuple] = []
    coord.tables_ready.connect(ready.append)
    coord.probe_failed.connect(lambda *args: failures.append(args))
    coord.request_tables(1)

    def boom(doc, page_num):
        raise RuntimeError("scratch copy failed")

    monkeypatch.setattr(table_objects, "scratch_page_bytes", boom)
    runner.complete(runner.order[0], _complete([TABLE_RECT]))  # the page cannot be re-read: stale
    assert ready == [] and failures == []
    assert table_objects._cache(model) == {}
    assert not table_objects._failed_keys(model)


def test_no_document_and_out_of_range_pages_do_no_work(model, copies):
    empty = PDFModel()
    try:
        assert table_objects.cached_table_rects(empty, 1) is None
        assert table_objects.table_analysis_failed(empty, 1) is False
        assert table_objects.table_rects(empty, 1) == []
        with pytest.raises(ValueError):
            _ = table_objects.PageInput(empty, 1).key
    finally:
        empty.close()
    for page_num in (0, len(model.doc) + 1):
        assert table_objects.cached_table_rects(model, page_num) is None
        assert table_objects.table_analysis_failed(model, page_num) is False
        assert table_objects.table_rects(model, page_num) == []
        with pytest.raises(ValueError):
            _ = table_objects.PageInput(model, page_num).key
    assert copies == []


# --------------------------------------------------------------------------- outcome 3


def test_two_clicks_on_an_unchanged_page_build_one_copy_each_and_the_second_hits(qapp, model, monkeypatch, copies):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    point = fitz.Point(170, 245)
    try:
        assert controller.lookup_object_at_point(1, point) is OBJECT_LOOKUP_PENDING
        assert copies == [1]  # one copy: the key, the lookup and the worker's bytes
        assert len(stub.order) == 1
        job = next(iter(controller._object_probe._jobs.values()))
        assert hashlib.sha256(job.payloads[0]).digest() == job.key[-1]  # the key IS the worker's bytes

        copies.clear()
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        assert copies == [1]  # the answer is checked against the page as it is now: one new copy

        for _ in range(2):  # the second click, and a third
            copies.clear()
            info = controller.lookup_object_at_point(1, point)
            assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "table"
            assert copies == [1]  # a hit builds its copy to look up
            assert len(stub.order) == 1  # and dispatches no job
    finally:
        dispose_pdf_view(view, controller, model)


def _primed(model):
    """Runner + coordinator with page 1's answer stored through the normal click path."""
    runner = StubRunner()
    coord = ObjectProbeCoordinator(model, runner=runner)
    info = _click(model, coord, runner, fitz.Point(170, 245))
    assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "table"
    return runner, coord


@pytest.mark.parametrize("how", ["save_as", "save_in_place"])
def test_a_save_keeps_the_answer_and_dispatches_no_job(model, tmp_path, how):
    runner, coord = _primed(model)
    old_generation = model.handle_generation
    jobs = len(runner.order)
    model.save_as(str(tmp_path / ("t.pdf" if how == "save_in_place" else "saved.pdf")))
    assert model.handle_generation != old_generation  # a save does give the document a new handle
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(*TABLE_RECT)]
    info = model.get_object_info_at_point(1, fitz.Point(170, 245), blocking=False)
    assert info is not OBJECT_LOOKUP_PENDING and info.object_kind == "table"
    coord.request_tables(1)
    assert len(runner.order) == jobs  # no job after the save


def test_a_snapshot_restore_with_the_same_page_bytes_still_hits(model):
    runner, coord = _primed(model)
    jobs = len(runner.order)
    old_generation = model.handle_generation
    model._restore_doc_from_snapshot(model.doc.tobytes())
    assert model.handle_generation != old_generation
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(*TABLE_RECT)]
    coord.request_tables(1)
    assert len(runner.order) == jobs


def test_a_late_answer_across_a_save_with_the_same_bytes_is_stored(model, tmp_path):
    runner = StubRunner()
    coord = ObjectProbeCoordinator(model, runner=runner)
    ready: list[int] = []
    coord.tables_ready.connect(ready.append)
    coord.request_tables(1)  # the job starts before the save
    model.save_as(str(tmp_path / "saved.pdf"))
    runner.complete(runner.order[0], _complete([TABLE_RECT]))  # ... and answers after it
    assert ready == [1]
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(*TABLE_RECT)]


def test_request_tables_given_a_page_input_builds_nothing_itself(model, copies):
    runner = StubRunner()
    coord = ObjectProbeCoordinator(model, runner=runner)
    page_input = table_objects.PageInput(model, 1)
    key = page_input.key
    assert copies == [1]
    coord.request_tables(1, page_input=page_input)
    assert copies == [1]
    assert len(runner.order) == 1
    assert runner.jobs[runner.order[0]][2] == (page_input.payload,)
    assert coord._jobs[runner.order[0]].key == key


def test_object_op_ready_builds_one_copy_per_page_and_none_on_a_non_table(qapp, model, monkeypatch, copies):
    from test_scripts.qt_teardown import dispose_pdf_view

    view, controller, stub, log = _controller(qapp, model, monkeypatch)
    try:
        assert controller.object_op_ready([1], ["rect"]) is True
        assert copies == []
        assert controller.object_op_ready([1], ["table"]) is False  # cold: starts the job
        assert copies == [1] and len(stub.order) == 1
        stub.complete(stub.order[0], _complete([TABLE_RECT]))
        copies.clear()
        assert controller.object_op_ready([1], ["table"]) is True  # warm: one copy for the hit
        assert copies == [1] and len(stub.order) == 1
        copies.clear()
        # A batch of three tables on one page: still one copy (review F2).
        assert controller.object_op_ready([1, 1, 1], ["table"] * 3) is True
        assert copies == [1]
    finally:
        dispose_pdf_view(view, controller, model)


def test_an_image_hit_builds_no_table_copy(qapp, tmp_path, monkeypatch, copies):
    from test_scripts.qt_teardown import dispose_pdf_view

    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 4, 4), False)
        pix.clear_with(90)
        page.insert_image(fitz.Rect(100, 100, 200, 200), pixmap=pix)
        doc.save(tmp_path / "img.pdf")
    m = PDFModel()
    m.open_pdf(str(tmp_path / "img.pdf"))
    view, controller, stub, log = _controller(qapp, m, monkeypatch)
    try:
        info = controller.lookup_object_at_point(1, fitz.Point(150, 150))
        assert info is not None and info.object_kind == "native_image"
        assert copies == []  # the PageInput is lazy: an image click never builds it
    finally:
        dispose_pdf_view(view, controller, m)


# --------------------------------------------------------------------------- the key itself


def test_page_input_is_lazy_and_builds_one_copy_for_key_and_payload(model, copies):
    page_input = table_objects.PageInput(model, 2)
    assert copies == []
    key, payload = page_input.key, page_input.payload
    assert page_input.key is key and page_input.payload is payload
    assert copies == [2]
    assert key == (2, hashlib.sha256(payload).digest())  # page and bytes, nothing else
    assert table_objects.frame_key(model, 2) == key


def test_page_input_remembers_a_failed_build_and_builds_once(model, monkeypatch):
    calls: list[int] = []

    def boom(doc, page_num):
        calls.append(page_num)
        raise RuntimeError("scratch copy failed")

    monkeypatch.setattr(table_objects, "scratch_page_bytes", boom)
    page_input = table_objects.PageInput(model, 1)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            _ = page_input.key
        with pytest.raises(RuntimeError):
            _ = page_input.payload
    assert calls == [1]


def test_an_unchanged_page_keeps_its_key_across_revision_writes(model):
    key = table_objects.frame_key(model, 1)
    assert table_objects.store_table_rects(model, key, [fitz.Rect(*TABLE_RECT)])
    model.edit_count = model.edit_count  # a tick with no page change
    assert table_objects.frame_key(model, 1) == key
    assert table_objects.cached_table_rects(model, 1) == [fitz.Rect(*TABLE_RECT)]
