"""Run-mode click and Apply latency (critique step 12, the blocker of the default flip).

Before the fix (plan section 6, 2026-10-02 L entry, five fresh app sessions
each, background renders quiesced): the cold first click on HVAC p5/p6 held
the GUI thread ~1.6-1.7 s, the first click after a commit was cold again
(~1.6 s), and the Apply-by-token identity rebind took ~1.7 s, all of it
``replay_page_streams`` walking ~930k tokens of vector drawing.  The proof
step ``_prove_line`` also scanned every show for every extracted line
(O(lines x shows) ``fitz.Point`` arithmetic: ~140 ms on HVAC p4 alone).

Targets: the click blocks the GUI thread < 150 ms and the rebind takes
< 300 ms median on p5/p6.  The assertions below use generous, CI-safe
margins; the measured table lives in the plan.  The B5 side-effect contract
(no extraction on the live document) is pinned by ``test_text_commit_source_run``.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.source_run import SourceRunResolver, group_page_runs  # noqa: E402

#: Generous ceilings (the targets are 150 ms click / 300 ms rebind).
GROUPING_BUDGET_S = 0.3
CLICK_STALL_BUDGET_MS = 400.0
REBIND_BUDGET_MS = 600.0


# ------------------------------------------------------- synthetic (CI-safe)


def _many_lines_model(tmp_path: Path, columns: int = 6, rows: int = 100) -> PDFModel:
    """``columns x rows`` two-word shows, each on its own line (all provable groups)."""
    doc = fitz.open()
    page = doc.new_page(width=1300, height=1100)
    page.insert_text((10, 10), "x", fontname="helv", fontsize=6)
    xref = page.get_contents()[0]
    parts = []
    for col in range(columns):
        for row in range(rows):
            x = 20 + col * 210
            y = 1080 - row * 10.5
            parts.append(f"BT /helv 6 Tf 1 0 0 1 {x:g} {y:g} Tm (Item{col}x{row} ab) Tj ET")
    doc.update_stream(xref, "\n".join(parts).encode("latin-1"))
    path = tmp_path / "many-lines.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    model.set_text_target_mode("run")
    model.ensure_page_index_built(1)
    return model


def test_grouping_a_page_with_hundreds_of_lines_is_fast(tmp_path: Path) -> None:
    """RED before the fix: candidate lookup scanned every show for every line."""
    model = _many_lines_model(tmp_path)
    try:
        doc = model.doc
        page = doc[0]
        runs = list(model.block_manager.get_runs(0))
        assert len(runs) == 1200, len(runs)
        streams = read_page_streams(doc, page)
        registry = DocumentFontRegistry(doc)
        group_page_runs(doc, page, runs, registry=registry, streams=streams)  # warm fonts
        best = float("inf")
        groups: dict = {}
        for _ in range(3):
            started = time.perf_counter()
            groups = group_page_runs(doc, page, runs, registry=registry, streams=streams)
            best = min(best, time.perf_counter() - started)
        # Every two-word line is one provable show.
        assert len({g.source_ref.seq for g in groups.values()}) == 600
        assert best < GROUPING_BUDGET_S, f"grouping took {best * 1000:.0f} ms"
    finally:
        model.close()


def _annotated_doc(count: int) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=1200, height=1200)
    page.insert_text((20, 20), "x", fontname="helv", fontsize=8)
    for index in range(count):
        x = 20 + (index % 40) * 29
        y = 40 + (index // 40) * 29
        rect = fitz.Rect(x, y, x + 20, y + 20)
        kind = index % 5
        if kind == 0:
            page.add_rect_annot(rect)
        elif kind == 1:
            page.add_text_annot(rect.tl, "note")  # carries a Popup
        elif kind == 2:
            page.add_freetext_annot(rect, "t")
        elif kind == 3:
            page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://example.invalid"})
        else:
            widget = fitz.Widget()
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_name = f"f{index}"
            widget.rect = rect
            page.add_widget(widget)
    return doc


def test_fingerprint_annotation_entries_match_page_annots() -> None:
    """GUARD (labelled): the fast annotation walk yields exactly ``page.annots()``."""
    from model.text_commit.inspect import _annotation_entries

    doc = _annotated_doc(60)
    try:
        page = doc[0]
        expected = [(annot.xref, tuple(annot.rect)) for annot in page.annots()]
        assert len(expected) == 36  # rect + text + freetext; never link/popup/widget
        assert _annotation_entries(page) == expected
        page.set_rotation(90)
        assert _annotation_entries(page) == [
            (annot.xref, tuple(annot.rect)) for annot in page.annots()
        ]
    finally:
        doc.close()


@pytest.mark.needs_fixtures
def test_fast_annotation_walk_equals_annots_on_the_real_corpora() -> None:
    """GUARD (labelled): HVAC p5 carries 367 annotations; every page must match."""
    from model.text_commit.inspect import _annotation_entries

    acc = _umbrella().acc
    total = 0
    for spec in acc.CORPORA:
        with fitz.open(str(acc._fixture(spec))) as doc:
            for page in doc:
                expected = [(annot.xref, tuple(annot.rect)) for annot in page.annots()]
                assert _annotation_entries(page) == expected, (spec.slug, page.number)
                total += len(expected)
    assert total > 300, total


def test_page_fingerprint_of_an_annotation_heavy_page_is_fast() -> None:
    """RED before the fix: ``page.annots()`` reloads each annot by xref (O(n^2))."""
    from model.text_commit.inspect import page_fingerprint

    doc = _annotated_doc(1500)
    try:
        page = doc[0]
        page_fingerprint(doc, page)
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            page_fingerprint(doc, page)
            best = min(best, time.perf_counter() - started)
        assert best < 0.25, f"page_fingerprint took {best * 1000:.0f} ms"
    finally:
        doc.close()


def _reference_loca(data: bytes) -> tuple[int, ...] | None:
    """The pre-step-12 per-glyph ``loca`` loop (the equality oracle)."""
    num_tables = int.from_bytes(data[4:6], "big")
    tables = {}
    for i in range(num_tables):
        base = 12 + i * 16
        tables[data[base : base + 4]] = (
            int.from_bytes(data[base + 8 : base + 12], "big"),
            int.from_bytes(data[base + 12 : base + 16], "big"),
        )
    maxp_off, _ = tables[b"maxp"]
    head_off, _ = tables[b"head"]
    loca_off, loca_len = tables[b"loca"]
    num_glyphs = int.from_bytes(data[maxp_off + 4 : maxp_off + 6], "big")
    long_format = int.from_bytes(data[head_off + 50 : head_off + 52], "big") == 1
    size = 4 if long_format else 2
    loca_raw = data[loca_off : loca_off + loca_len]
    return tuple(
        int.from_bytes(loca_raw[i * size : (i + 1) * size], "big") * (1 if long_format else 2)
        for i in range(num_glyphs + 1)
    )


def _embedded_programs(doc: fitz.Document) -> list[bytes]:
    from model.text_commit.cid_fonts import _program_from_descendant, resolve_descendant

    programs = []
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Subtype") != ("name", "/Type0"):
                continue
        except Exception:  # noqa: BLE001 - not a dictionary
            continue
        _, descendant = resolve_descendant(doc, xref)
        if descendant is not None:
            program = _program_from_descendant(doc, descendant)
            if program:
                programs.append(program)
    return programs


def test_loca_parse_equals_the_per_glyph_loop() -> None:
    """GUARD (labelled): the bulk ``loca`` unpack equals the old per-glyph loop."""
    from model.text_commit.cid_fonts import parse_truetype_glyph_program
    from test_scripts.type0_fixture_builder import build_identity_h_fixture

    fixture = build_identity_h_fixture("Buffer Tank 設計圖說A版")
    programs = _embedded_programs(fixture.doc)
    assert programs
    for program in programs:
        parsed = parse_truetype_glyph_program(program)
        assert parsed is not None and parsed.loca == _reference_loca(program)


@pytest.mark.needs_fixtures
def test_loca_parse_equals_the_per_glyph_loop_on_the_real_corpora() -> None:
    """GUARD (labelled): every embedded HVAC/ECC CID program parses identically."""
    from model.text_commit.cid_fonts import parse_truetype_glyph_program

    acc = _umbrella().acc
    checked = 0
    for spec in acc.CORPORA:
        with fitz.open(str(acc._fixture(spec))) as doc:
            for program in _embedded_programs(doc):
                parsed = parse_truetype_glyph_program(program)
                if parsed is None:
                    continue
                assert parsed.loca == _reference_loca(program)
                checked += 1
    assert checked >= 5, checked


class _ScanEverything:
    """The pre-step-12 behaviour: every query returns every show (the oracle)."""

    def __init__(self, base_origins) -> None:
        self._all = list(range(len(base_origins)))

    def near(self, _point):
        return self._all

    def x_between(self, _low, _high):
        return self._all


def _groups_with_and_without_index(monkeypatch, model: PDFModel, page_idx: int):
    import model.text_commit.source_run as source_run

    doc = model.doc
    page = doc[page_idx]
    runs = list(model.block_manager.get_runs(page_idx))
    registry = DocumentFontRegistry(doc)
    fast = group_page_runs(doc, page, runs, registry=registry)
    with monkeypatch.context() as patch:
        patch.setattr(source_run, "_OriginIndex", _ScanEverything)
        reference = group_page_runs(doc, page, runs, registry=registry)
    return fast, reference


def test_indexed_grouping_equals_the_full_scan(tmp_path: Path, monkeypatch) -> None:
    """GUARD (labelled; the index only pre-filters): same groups as scanning every show."""
    model = _many_lines_model(tmp_path, columns=3, rows=40)
    try:
        fast, reference = _groups_with_and_without_index(monkeypatch, model, 0)
        assert fast == reference and len(fast) == 240
    finally:
        model.close()


@pytest.mark.needs_fixtures
def test_indexed_grouping_equals_the_full_scan_on_the_real_corpora(monkeypatch) -> None:
    umb = _umbrella()
    acc = umb.acc
    checked = 0
    for spec in acc.CORPORA:
        path = acc._fixture(spec)
        model = PDFModel()
        try:
            model.open_pdf(str(path))
            model.set_text_target_mode("run")
            for page_idx in sorted({case.page_index for case in spec.cases}):
                model.ensure_page_index_built(page_idx + 1)
                fast, reference = _groups_with_and_without_index(monkeypatch, model, page_idx)
                assert fast == reference, (spec.slug, page_idx)
                assert fast, (spec.slug, page_idx)
                checked += 1
        finally:
            model.close()
    assert checked == 4


# ------------------------------------------------------- real app (fixtures)


def _umbrella():
    import test_text_commit_ui_real_corpus as umb

    return umb


def _busy(app) -> int:
    busy = 0
    for name in ("_page_render_coordinator", "_thumbnail_coordinator"):
        coordinator = getattr(app.controller, name, None)
        if coordinator is None:
            continue
        busy += len(getattr(coordinator, "_threads", {}) or {})
        busy += 1 if getattr(coordinator, "has_active_job", False) else 0
    return busy


def _quiesce(app) -> None:
    """Wait out page/thumbnail renders: they are not the click's own work."""
    assert app.wait(lambda: _busy(app) == 0, 120.0), "renders never settled"
    app.pump(300)


class _Heartbeat:
    """Largest gap between 10 ms timer ticks = longest GUI-thread block."""

    def __init__(self) -> None:
        from PySide6.QtCore import QTimer

        self.ticks: list[float] = []
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.timer.timeout.connect(lambda: self.ticks.append(time.perf_counter()))

    def start(self) -> None:
        self.ticks = [time.perf_counter()]
        self.timer.start()

    def stop(self) -> float:
        self.timer.stop()
        self.ticks.append(time.perf_counter())
        return max(b - a for a, b in zip(self.ticks, self.ticks[1:])) * 1000.0


def _hover_and_click(app, beat: _Heartbeat, page_index: int, rect: fitz.Rect):
    """Real hover then click on a glyph; returns (editor, max GUI stall ms)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    centre = app.view._doc_rect_to_scene_rect(page_index, rect).center()
    app.view.graphics_view.centerOn(centre)
    app.pump(300)
    _quiesce(app)
    position = app.view.graphics_view.mapFromScene(centre)
    viewport = app.view.graphics_view.viewport()
    beat.start()
    QTest.mouseMove(viewport, position)
    app.pump(300)
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, position)
    app.wait(lambda: app.editor() is not None, 60.0)
    app.pump(100)
    return app.editor(), beat.stop()


_PAIRS = ((5, 60, 58), (6, 7, 5))


@pytest.mark.needs_fixtures
@pytest.mark.parametrize(("page_index", "first_seq", "second_seq"), _PAIRS, ids=["hvac-p5", "hvac-p6"])
def test_hvac_click_and_apply_do_not_block_the_gui_thread(
    tmp_path: Path, monkeypatch, page_index: int, first_seq: int, second_seq: int
) -> None:
    """Cold click, Apply (identity rebind) and the first click after the commit."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    umb = _umbrella()
    acc = umb.acc
    source_path = acc._fixture(acc.HVAC)
    work_path = tmp_path / f"hvac-p{page_index}-latency.pdf"
    shutil.copyfile(source_path, work_path)
    with fitz.open(str(source_path)) as source:
        cases = acc._resolve_cases(acc.HVAC, source)
        first = umb._find_case(acc.HVAC, cases, page_index, first_seq)
        second = umb._find_case(acc.HVAC, cases, page_index, second_seq)
        first_rect = umb._glyph_rect(source, first, first.original)
        second_rect = umb._glyph_rect(source, second, second.original)

    rebinds: list[float] = []
    original_rebind = TieredCommitEngine.cached_candidate_identity_failure

    def _timed_rebind(engine, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_rebind(engine, *args, **kwargs)
        finally:
            rebinds.append((time.perf_counter() - started) * 1000.0)

    monkeypatch.setattr(TieredCommitEngine, "cached_candidate_identity_failure", _timed_rebind)
    app = umb._App(monkeypatch, work_path)
    problems: list[str] = []
    try:
        app.goto_page(page_index)
        app.ensure_edit_text_run_mode()
        beat = _Heartbeat()
        # The resolver must really be cold for this page.
        assert isinstance(app.model._source_run_resolver, SourceRunResolver)
        assert app.model._source_run_resolver._pages.get(page_index) is None

        editor, cold_stall = _hover_and_click(app, beat, page_index, first_rect)
        assert editor is not None and editor.toPlainText() == first.original
        assert app.view.editing_source_ref is not None
        if cold_stall >= CLICK_STALL_BUDGET_MS:
            problems.append(f"cold click blocked the GUI thread {cold_stall:.0f} ms")

        app.type_replacing_all(editor, first.replacement)
        token, reason = app.wait_preview(editor)
        assert token is not None, reason
        _quiesce(app)
        commits = len(app.live_commits())
        QTest.mouseClick(app.view.text_apply_btn, Qt.LeftButton)
        app.pump(400)
        assert len(app.live_commits()) == commits + 1, "Apply did not commit"
        assert rebinds, "the Apply did not go through the identity rebind"
        if rebinds[-1] >= REBIND_BUDGET_MS:
            problems.append(f"Apply identity rebind took {rebinds[-1]:.0f} ms")

        editor_b, after_stall = _hover_and_click(app, beat, page_index, second_rect)
        assert editor_b is not None and editor_b.toPlainText() == second.original
        if after_stall >= CLICK_STALL_BUDGET_MS:
            problems.append(f"first click after the commit blocked {after_stall:.0f} ms")
        app.press_escape(editor_b)
    finally:
        app.close()
    assert not problems, "\n".join(problems)
