"""T16-4X S10 red-light tests: inline /Annots dictionaries refuse with a stable code.

A page whose /Annots array holds an INLINE annotation dictionary (no indirect
reference) has no xref for that annotation: PyMuPDF's ``page.annots()`` raises
``AttributeError`` on it, and V0b's xref-keyed "annotations untouched" proof
cannot identify it.  The text-commit engine must refuse such a page with the
stable code ``annotations_not_indirect`` -- in ``prepare``, in ``commit`` and in
the plan preview -- with zero document mutation, while indirect pages and
pages whose only inline entry is an unlisted kind (Link) keep committing.

Synthetic fixtures only.  Pure lane: no view/controller/Qt imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.plan as plan_module  # noqa: E402
from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from utils.pdf_object_source import xref_object_exact  # noqa: E402

# Independent literal (house style, cid_hex_tj / mc_admission pattern): the pin
# must break if the production spelling drifts, and the red run must fail on
# the real AttributeError, not on a missing attribute.
ANNOTATIONS_NOT_INDIRECT = "annotations_not_indirect"

TARGET = "Hello world"
REPLACEMENT = "Hallo world"  # Helvetica e = a = 556: equal advance, Tier 0

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)
INL = "<< /Type /Annot /Subtype /Text /Rect [300 300 320 320] /Contents (n) >>"
INL2 = "<< /Type /Annot /Subtype /Text /Rect [350 350 370 370] /Contents (m) >>"
INL_LINK = (
    "<< /Type /Annot /Subtype /Link /Rect [300 300 320 320] /Border [0 0 0] >>"
)


# ---------------------------------------------------------------- fixtures


def _stream_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(
        content_xref,
        b"BT /F1 12 Tf 72 700 Td (Hello world) Tj "
        b"0 -40 Td (Downstream line stays) Tj ET",
    )
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _annots(doc: fitz.Document, value: str) -> None:
    doc.xref_set_key(doc[0].xref, "Annots", value)


def _shape_doc(shape: str) -> fitz.Document:
    """A: [INL]; B: [INL x 0 R]; F: /Annots N 0 R, N = [INL];
    controls C: [x 0 R]; D: /Annots N 0 R, N = [x 0 R]; E: inline Link only."""
    doc = _stream_doc()
    x = 0
    if shape in ("B", "C", "D"):
        x = doc[0].add_text_annot((400, 400), "x").xref
    if shape == "A":
        _annots(doc, f"[{INL}]")
    elif shape == "B":
        _annots(doc, f"[{INL} {x} 0 R]")
    elif shape == "C":
        _annots(doc, f"[{x} 0 R]")
    elif shape in ("D", "F"):
        array_xref = doc.get_new_xref()
        body = f"[{x} 0 R]" if shape == "D" else f"[{INL}]"
        doc.update_object(array_xref, body)
        _annots(doc, f"{array_xref} 0 R")
    elif shape == "E":
        _annots(doc, f"[{INL_LINK}]")
    else:  # pragma: no cover
        raise AssertionError(shape)
    return doc


def _kwargs(page: fitz.Page) -> dict:
    span = _span(page, "Hello")
    return {
        "target_text": TARGET,
        "replacement_text": REPLACEMENT,
        "expected_origin": tuple(float(v) for v in span["origin"]),
        "target_bbox": tuple(float(v) for v in span["bbox"]),
    }


def _objects(doc: fitz.Document) -> tuple:
    return (
        doc.xref_length(),
        tuple(
            (
                xref,
                xref_object_exact(doc, xref),
                doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else None,
            )
            for xref in range(1, doc.xref_length())
        ),
    )


def _request(doc: fitz.Document) -> PlanPreviewRequest:
    kw = _kwargs(doc[0])
    return PlanPreviewRequest(
        session_key="direct-annots",
        generation=1,
        target_text=kw["target_text"],
        replacement_text=kw["replacement_text"],
        expected_origin=kw["expected_origin"],
        target_bbox=kw["target_bbox"],
        clip_rect=kw["target_bbox"],
        render_scale=1.0,
    )


def _assert_prepare_refused(doc: fitz.Document) -> None:
    before = _objects(doc)
    page = doc[0]
    result = TieredCommitEngine(doc, max_tier=0).prepare(page, **_kwargs(page))
    assert isinstance(result, PlanRejection)
    assert result.reason == ANNOTATIONS_NOT_INDIRECT
    assert "Hello" not in result.detail
    assert _objects(doc) == before


def _assert_preview_refused(doc: fitz.Document) -> None:
    session = open_preview_session(doc, 0, "k", max_tier=0)
    assert session is not None  # the fingerprint is tolerant, not raising
    renderer = PlanPreviewRenderer(session)
    try:
        result = renderer.render(_request(doc))
    finally:
        renderer.close()
    assert result.reject_reason == ANNOTATIONS_NOT_INDIRECT
    assert result.plan_token is None


def _bypass_plan_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        plan_module, "require_indirect_annotations", lambda page: []
    )


# ------------------------------------------------------------------- tests


@pytest.mark.parametrize("shape", ["A", "B", "F"])
def test_prepare_refuses_inline_annotations_without_mutation(shape: str) -> None:
    doc = _shape_doc(shape)
    try:
        _assert_prepare_refused(doc)
    finally:
        doc.close()


@pytest.mark.parametrize("shape", ["C", "D", "E"])
def test_indirect_and_unlisted_inline_controls_still_commit(shape: str) -> None:
    doc = _shape_doc(shape)
    try:
        page = doc[0]
        xrefs_before = page.annot_xrefs()
        listed_before = [(a.xref, tuple(a.rect)) for a in page.annots()]
        engine = TieredCommitEngine(doc, max_tier=0)
        prepared = engine.prepare(page, **_kwargs(page))
        assert isinstance(prepared, PreparedEdit)
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED
        page = doc[0]
        assert page.annot_xrefs() == xrefs_before
        if shape in ("C", "D"):
            assert [(a.xref, tuple(a.rect)) for a in page.annots()] == listed_before
    finally:
        doc.close()


def test_commit_refuses_page_that_gained_inline_annotation_after_prepare() -> None:
    doc = _stream_doc()
    try:
        page = doc[0]
        engine = TieredCommitEngine(doc, max_tier=0)
        prepared = engine.prepare(page, **_kwargs(page))
        assert isinstance(prepared, PreparedEdit)
        _annots(doc, f"[{INL}]")
        before = _objects(doc)
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.FAILED
        assert outcome.fallback_chain == ("tier0:" + ANNOTATIONS_NOT_INDIRECT,)
        assert _objects(doc) == before
        assert "Hello world" in doc[0].get_text()
    finally:
        doc.close()


def test_prepare_backstop_refuses_when_the_plan_gate_is_bypassed(monkeypatch) -> None:
    _bypass_plan_gate(monkeypatch)
    doc = _shape_doc("A")
    try:
        _assert_prepare_refused(doc)
    finally:
        doc.close()


def test_preview_render_refuses_inline_annotations() -> None:
    doc = _shape_doc("A")
    try:
        _assert_preview_refused(doc)
    finally:
        doc.close()


def test_preview_backstop_refuses_when_the_plan_gate_is_bypassed(monkeypatch) -> None:
    _bypass_plan_gate(monkeypatch)
    doc = _shape_doc("A")
    try:
        _assert_preview_refused(doc)
    finally:
        doc.close()


@pytest.mark.parametrize("shape", ["C", "D", "E"])
def test_annotation_entries_equal_annots_on_listed_pages(shape: str) -> None:
    from model.text_commit.inspect import (
        annotation_entries,
        require_indirect_annotations,
    )

    doc = _shape_doc(shape)
    try:
        page = doc[0]
        assert annotation_entries(page) == tuple(
            (a.xref, tuple(a.rect)) for a in page.annots()
        )
        if shape == "E":
            assert require_indirect_annotations(page) == []
    finally:
        doc.close()


@pytest.mark.parametrize("shape", ["A", "B", "F"])
def test_strict_readers_raise_typed_error_on_inline_annotations(shape: str) -> None:
    from model.text_commit.inspect import (
        InlineAnnotationError,
        annotation_entries,
        require_indirect_annotations,
    )

    doc = _shape_doc(shape)
    try:
        with pytest.raises(InlineAnnotationError):
            annotation_entries(doc[0])
        with pytest.raises(InlineAnnotationError):
            require_indirect_annotations(doc[0])
    finally:
        doc.close()


def test_page_fingerprint_tolerates_and_distinguishes_inline_annotations() -> None:
    from model.text_commit.inspect import (
        _annotation_entries,
        annotation_entries,
        page_fingerprint,
    )

    doc = _stream_doc()
    try:
        _annots(doc, f"[{INL} {INL2}]")
        first = page_fingerprint(doc, doc[0])
        moved = INL.replace("[300 300 320 320]", "[310 310 330 330]")
        _annots(doc, f"[{moved} {INL2}]")
        second = page_fingerprint(doc, doc[0])
        assert first != second
        # The collision itself: each inline annotation keeps its OWN rect (the
        # old last-wins ``rects[0]`` read gave the last rect to both).
        page = doc[0]
        entries = _annotation_entries(page)
        assert [x for x, _r in entries] == [0, 0]
        assert len({rect for _x, rect in entries}) == 2
        # x0 only: a Text annotation's rect size is a PyMuPDF load quirk.
        assert [rect[0] for _x, rect in entries] == [310.0, 350.0]
    finally:
        doc.close()
    for shape in ("A", "B", "F"):
        doc = _shape_doc(shape)
        try:
            page_fingerprint(doc, doc[0])  # must not raise
        finally:
            doc.close()
    for shape in ("C", "D"):
        doc = _shape_doc(shape)
        try:
            page = doc[0]
            assert tuple(_annotation_entries(page)) == annotation_entries(page)
        finally:
            doc.close()


def test_tolerant_reader_skips_unknown_subtype_inline_entries() -> None:
    """PyMuPDF's ``annot_xrefs()`` drops an entry with an unknown /Subtype, so
    the walk must not hand its rect to the next inline annotation."""
    from model.text_commit.inspect import _annotation_entries

    unknown = "<< /Type /Annot /Subtype /Foo /Rect [100 100 120 120] >>"
    doc = _stream_doc()
    try:
        _annots(doc, f"[{unknown} {INL} {INL2}]")
        entries = _annotation_entries(doc[0])
        assert [x for x, _r in entries] == [0, 0]
        assert [rect[0] for _x, rect in entries] == [300.0, 350.0]
    finally:
        doc.close()


def _stale_handle_doc() -> tuple[fitz.Document, fitz.Page, int]:
    """A page handle held across an /Annots write: ``annot_xrefs()`` lists the
    new indirect annotation, MuPDF's cached annotation list does not."""
    doc = _stream_doc()
    held = doc[0]
    held.annot_xrefs()
    held.first_annot  # noqa: B018 -- loads MuPDF's annotation list
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        "<< /Type /Annot /Subtype /Text /Rect [300 300 320 320] "
        f"/Contents (n) /P {held.xref} 0 R >>",
    )
    doc.xref_set_key(held.xref, "Annots", f"[{xref} 0 R]")
    return doc, held, xref


def test_unreachable_listed_xref_never_leaks_a_plain_exception() -> None:
    """``load_annot`` cannot find an xref the first_annot walk did not reach
    (it walks the same list) and raises a bare ``Exception``; no reader may
    call it.  Strict readers raise the typed error, the fingerprint stays
    total, and ``prepare`` returns a verdict instead of raising."""
    from model.text_commit.inspect import (
        InlineAnnotationError,
        _annotation_entries,
        annotation_entries,
        page_fingerprint,
    )

    doc, held, xref = _stale_handle_doc()
    try:
        with pytest.raises(InlineAnnotationError):
            annotation_entries(held)
        assert [x for x, _r in _annotation_entries(held)] == [xref]
        page_fingerprint(doc, held)  # must not raise
        before = _objects(doc)
        result = TieredCommitEngine(doc, max_tier=0).prepare(held, **_kwargs(held))
        assert isinstance(result, PlanRejection)  # fail closed, not an exception
        assert _objects(doc) == before
    finally:
        doc.close()


# ----------------------------------------- the widget list, same disagreement

INL_WIDGET = (
    "<< /Type /Annot /Subtype /Widget /FT /Tx /T (f) /Rect [100 100 200 120] >>"
)


def _stale_widget_doc(inline: bool) -> tuple[fitz.Document, fitz.Page]:
    """A page handle held across an /Annots write that adds a widget:
    ``annot_xrefs()`` lists it, MuPDF's cached widget list does not, so
    ``page.widgets()`` raises a bare ``Exception`` ("xref N is not a widget of
    this page"; xref 0 for an inline one)."""
    doc = _stream_doc()
    held = doc[0]
    held.annot_xrefs()
    held.first_annot  # noqa: B018 -- loads MuPDF's annotation list
    held.first_widget  # noqa: B018 -- and its widget list
    if inline:
        _annots(doc, f"[{INL_WIDGET}]")
    else:
        xref = doc.get_new_xref()
        doc.update_object(xref, INL_WIDGET[:-2] + f" /P {held.xref} 0 R >>")
        _annots(doc, f"[{xref} 0 R]")
    return doc, held


@pytest.mark.parametrize("inline", [True, False], ids=["inline", "indirect"])
def test_stale_handle_widget_never_leaks_a_plain_exception(inline: bool) -> None:
    from model.text_commit.inspect import (
        page_fingerprint,
        page_has_widgets_or_signatures,
    )

    doc, held = _stale_widget_doc(inline)
    try:
        assert page_has_widgets_or_signatures(doc, held) is True
        page_fingerprint(doc, held)  # must not raise
        before = _objects(doc)
        result = TieredCommitEngine(doc, max_tier=0).prepare(held, **_kwargs(held))
        assert isinstance(result, PlanRejection)
        assert result.reason == "signed_or_widget_target"
        assert _objects(doc) == before
    finally:
        doc.close()


def test_widget_entries_equal_widgets_on_a_widget_page() -> None:
    from model.text_commit.inspect import _widget_entries

    doc = _stream_doc()
    try:
        page = doc[0]
        for name, y in (("a", 100), ("b", 160)):
            widget = fitz.Widget()
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_name = name
            widget.rect = fitz.Rect(100, y, 200, y + 20)
            page.add_widget(widget)
        page = doc[0]
        entries = _widget_entries(page)
        assert len(entries) == 2
        assert entries == [(w.xref, tuple(w.rect)) for w in page.widgets()]
    finally:
        doc.close()


# ----------------------------- inline vs out-of-sync: two causes, two answers


def _out_of_sync(*_args, **_kwargs):
    from model.text_commit.inspect import AnnotationListOutOfSync

    raise AnnotationListOutOfSync("1 of 1 listed /Annots entries are not loadable")


def test_out_of_sync_annotation_list_is_not_reported_as_inline() -> None:
    from model.text_commit.inspect import (
        AnnotationListOutOfSync,
        InlineAnnotationError,
        annotation_entries,
    )

    assert issubclass(AnnotationListOutOfSync, InlineAnnotationError)
    doc, held, _xref = _stale_handle_doc()
    try:
        with pytest.raises(AnnotationListOutOfSync):
            annotation_entries(held)
    finally:
        doc.close()


def test_commit_maps_an_out_of_sync_list_to_stale_plan(monkeypatch) -> None:
    import model.text_commit.engine as engine_module

    doc = _stream_doc()
    try:
        page = doc[0]
        engine = TieredCommitEngine(doc, max_tier=0)
        prepared = engine.prepare(page, **_kwargs(page))
        assert isinstance(prepared, PreparedEdit)
        monkeypatch.setattr(engine_module, "capture_page_state", _out_of_sync)
        before = _objects(doc)
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.STALE_PLAN
        assert outcome.fallback_chain == ("tier0:stale_plan",)
        assert _objects(doc) == before
    finally:
        doc.close()


def test_prepare_maps_an_out_of_sync_list_to_verification_failed(monkeypatch) -> None:
    import model.text_commit.engine as engine_module

    monkeypatch.setattr(engine_module, "capture_page_state", _out_of_sync)
    doc = _stream_doc()
    try:
        before = _objects(doc)
        page = doc[0]
        result = TieredCommitEngine(doc, max_tier=0).prepare(page, **_kwargs(page))
        assert isinstance(result, PlanRejection)
        assert result.reason == "verification_failed"
        assert _objects(doc) == before
    finally:
        doc.close()


def test_preview_maps_an_out_of_sync_list_to_verification_failed(monkeypatch) -> None:
    from model.text_commit.verify import PreStateBaselineCache

    monkeypatch.setattr(PreStateBaselineCache, "capture", _out_of_sync)
    doc = _stream_doc()
    try:
        session = open_preview_session(doc, 0, "k", max_tier=0)
        assert session is not None
        renderer = PlanPreviewRenderer(session)
        try:
            result = renderer.render(_request(doc))
        finally:
            renderer.close()
        assert result.reject_reason == "verification_failed"
        assert result.plan_token is None
    finally:
        doc.close()


# ------------------- unreadable /Annots: the detector owns its own failure mode


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("boom"), ValueError("boom"), fitz.mupdf.FzErrorFormat("boom")],
    ids=["runtime", "value", "mupdf"],
)
def test_require_indirect_annotations_types_an_unreadable_annots_read(
    monkeypatch, exc: Exception
) -> None:
    """PyMuPDF 1.27.1 tolerates every malformed /Annots shape probed (non-array,
    dangling ref, self-referencing array: ``annot_xrefs()`` returns ``[]``), so
    the failure is injected.  The detector must not rest on
    ``page_has_widgets_or_signatures`` having run first: it types its own read
    failure as :class:`InlineAnnotationError`."""
    from model.text_commit.inspect import (
        InlineAnnotationError,
        require_indirect_annotations,
    )

    def _raise(_self):
        raise exc

    monkeypatch.setattr(fitz.Page, "annot_xrefs", _raise)
    doc = _stream_doc()
    try:
        with pytest.raises(InlineAnnotationError) as info:
            require_indirect_annotations(doc[0])
        assert info.value.__cause__ is exc
        assert "Hello" not in str(info.value)
    finally:
        doc.close()


def test_prepare_refuses_when_the_annots_read_raises_past_the_widget_gate(
    monkeypatch,
) -> None:
    """The widget gate (which also reads ``annot_xrefs()``) is bypassed so the
    plan gate's own read is the one that raises."""
    monkeypatch.setattr(
        plan_module, "page_has_widgets_or_signatures", lambda doc, page: False
    )
    doc = _stream_doc()
    try:
        page = doc[0]
        kwargs = _kwargs(page)
        before = _objects(doc)

        def _raise(_self):
            raise RuntimeError("boom")

        monkeypatch.setattr(fitz.Page, "annot_xrefs", _raise)
        result = TieredCommitEngine(doc, max_tier=0).prepare(page, **kwargs)
        monkeypatch.undo()
        assert isinstance(result, PlanRejection)
        assert result.reason == ANNOTATIONS_NOT_INDIRECT
        assert _objects(doc) == before
    finally:
        doc.close()


# ------------------------- a /Parent cycle on a widget: the fingerprint is total


def _widget_parent_cycle_doc() -> fitz.Document:
    """A widget whose /Parent chain cycles: MuPDF raises ``FzErrorFormat``
    ("cycle in resources") from ``first_widget`` at PyMuPDF 1.27.1."""
    doc = _stream_doc()
    page_xref = doc[0].xref
    w1 = doc.get_new_xref()
    w2 = doc.get_new_xref()
    doc.update_object(
        w1,
        "<< /Type /Annot /Subtype /Widget /FT /Tx /T (f) /Rect [100 100 200 120] "
        f"/P {page_xref} 0 R /Parent {w2} 0 R >>",
    )
    doc.update_object(w2, f"<< /T (g) /Parent {w1} 0 R >>")
    _annots(doc, f"[{w1} 0 R]")
    return doc


def test_page_fingerprint_is_total_on_a_widget_parent_cycle() -> None:
    from model.text_commit.inspect import _widget_entries, page_fingerprint

    doc = _widget_parent_cycle_doc()
    try:
        with pytest.raises(fitz.mupdf.FzErrorBase):  # the fixture really raises
            doc[0].first_widget  # noqa: B018
        page = doc[0]
        rows = _widget_entries(page)  # must not raise
        assert len(rows) == 1
        assert rows[0][0] > 0
        assert rows[0][1] == (0.0, 0.0, 0.0, 0.0)
        first = page_fingerprint(doc, doc[0])  # must not raise
        assert first == page_fingerprint(doc, doc[0])
    finally:
        doc.close()


def test_open_preview_session_does_not_raise_on_a_widget_parent_cycle() -> None:
    doc = _widget_parent_cycle_doc()
    try:
        open_preview_session(doc, 0, "k", max_tier=0)  # must not raise
    finally:
        doc.close()
