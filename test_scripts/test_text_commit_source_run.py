"""Click-time source-show grouping (UI stage G2, plan section 6, 2026-09-30).

The run index splits one content-stream show at every space and at every
character-kind change ("Buffer Tank" -> 'Buffer', 'Tank'; "設計圖說A版" ->
'設計圖說', 'A', '版'), so a run-mode click used to return one word that the
engine's exact show binding can never match.  The owner decided to group at
CLICK time, never in the index: a Qt-free resolver proves that the clicked
line's runs are exactly one show and the hit becomes that whole show.

Proof (all must hold, else the hit keeps today's single-run behaviour):
decoded show text minus whitespace == the concatenated run texts; the
non-space glyph counts match; the first member run (PARSER order, never
origin.x) sits within 0.05 pt of the show origin; no other show's origin
lies inside the union bbox.  The resolver reads stream bytes and the font
registry only -- never ``get_text``/``get_texttrace``/``get_drawings``/
``get_image_rects`` on the live document (plan section 6 records their side
effects).

Every fixture is synthetic (plan section 10 data policy).  The real-corpus
leg at the bottom is ``needs_fixtures``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.geometry import unrotated_to_visual_point, unrotated_to_visual_rect  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import _origin_in_page_space  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.type0_fixture_builder import (  # noqa: E402
    Type0Fixture,
    append_page_content,
    build_identity_h_fixture,
    encode_cids,
    set_text_matrix,
)

_ORIGIN_TOL = 1e-3


# ---------------------------------------------------------------- helpers


def _open_model(tmp_path: Path, doc: fitz.Document, name: str) -> PDFModel:
    path = tmp_path / f"{name}.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    model.set_text_target_mode("run")
    model.ensure_page_index_built(1)
    return model


def _fixture_model(tmp_path: Path, fixture: Type0Fixture, name: str) -> PDFModel:
    return _open_model(tmp_path, fixture.doc, name)


def _runs(model: PDFModel, page_idx: int = 0) -> list:
    return list(model.block_manager.get_runs(page_idx))


def _run_by_text(model: PDFModel, text: str, page_idx: int = 0, nth: int = 0):
    matches = [r for r in _runs(model, page_idx) if r.text == text]
    assert len(matches) > nth, f"no run {text!r} (#{nth}) in {[r.text for r in _runs(model, page_idx)]}"
    return matches[nth]


def _visual_centre(model: PDFModel, run, page_idx: int = 0) -> fitz.Point:
    page = model.doc[page_idx]
    rect = unrotated_to_visual_rect(page, fitz.Rect(run.bbox))
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _hit_on(model: PDFModel, run, page_idx: int = 0):
    hit = model.get_text_info_at_point(page_idx + 1, _visual_centre(model, run, page_idx))
    assert hit is not None
    return hit


def _visual_union(model: PDFModel, runs, page_idx: int = 0) -> fitz.Rect:
    page = model.doc[page_idx]
    union = fitz.Rect(runs[0].bbox)
    for run in runs[1:]:
        union |= fitz.Rect(run.bbox)
    return unrotated_to_visual_rect(page, union)


def _rect_close(a: fitz.Rect, b: fitz.Rect, tol: float = _ORIGIN_TOL) -> bool:
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(tuple(a), tuple(b)))


def _source_ref(hit):
    return getattr(hit, "source_ref", None)


def _members(hit) -> tuple:
    return tuple(getattr(hit, "member_span_ids", ()) or ())


def _append_show(fixture: Type0Fixture, text: str, x: float, y: float) -> None:
    hex_operand = encode_cids(text).hex().upper()
    append_page_content(
        fixture,
        f"BT /{fixture.resource_name} {fixture.fontsize:g} Tf "
        f"1 0 0 1 {x:g} {y:g} Tm <{hex_operand}> Tj ET",
    )


# ------------------------------------------------ positive: one show, many runs


def test_buffer_tank_rot0_hit_is_the_whole_show(tmp_path: Path) -> None:
    """Positive control for every refusal below: one Tj, two runs, one target."""
    model = _fixture_model(tmp_path, build_identity_h_fixture("Buffer Tank"), "rot0")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        tank_run = _run_by_text(model, "Tank")
        # Click the LAST member: grouping must not depend on which word is hit.
        hit = _hit_on(model, tank_run)
        assert hit.target_text == "Buffer Tank"
        assert _members(hit) == (buffer_run.span_id, tank_run.span_id)
        assert hit.target_span_id == buffer_run.span_id
        assert _rect_close(hit.target_bbox, _visual_union(model, [buffer_run, tank_run]))
        ref = _source_ref(hit)
        assert ref is not None
        assert ref.seq == 0
        assert ref.page_xref == model.doc[0].xref
        assert ref.stream_xref == model.doc[0].get_contents()[0]
        # Clicking the first word yields the identical target.
        again = _hit_on(model, buffer_run)
        assert again.target_text == "Buffer Tank"
        assert _source_ref(again) == ref
    finally:
        model.close()


def test_mirrored_buffer_tank_keeps_parser_order(tmp_path: Path) -> None:
    """Tm -1 0 0 1: origin.x ordering would read 'Tank Buffer'; parser order must win."""
    fixture = build_identity_h_fixture("Buffer Tank", origin=(300.0, 700.0))
    set_text_matrix(fixture, (-1.0, 0.0, 0.0, 1.0))
    model = _fixture_model(tmp_path, fixture, "mirror")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        tank_run = _run_by_text(model, "Tank")
        assert float(tank_run.origin.x) < float(buffer_run.origin.x), "fixture must be mirrored"
        hit = _hit_on(model, tank_run)
        assert hit.target_text == "Buffer Tank"
        assert _members(hit) == (buffer_run.span_id, tank_run.span_id)
        assert _source_ref(hit) is not None
        assert _rect_close(hit.target_bbox, _visual_union(model, [buffer_run, tank_run]))
    finally:
        model.close()


def test_cjk_latin_kind_split_is_exact_without_inserted_spaces(tmp_path: Path) -> None:
    model = _fixture_model(tmp_path, build_identity_h_fixture("設計圖說A版"), "cjk")
    try:
        runs = _runs(model)
        assert [r.text for r in runs] == ["設計圖說", "A", "版"], "fixture must kind-split"
        hit = _hit_on(model, runs[1])
        assert hit.target_text == "設計圖說A版"
        assert _members(hit) == tuple(r.span_id for r in runs)
        assert _source_ref(hit) is not None
    finally:
        model.close()


def test_rotated_page_source_origin_is_the_binding_origin(tmp_path: Path) -> None:
    """``source_ref.origin`` is VISUAL space: step 3 feeds it as expected_origin."""
    model = _fixture_model(
        tmp_path, build_identity_h_fixture("Buffer Tank", rotate=90), "rot90"
    )
    try:
        page = model.doc[0]
        assert page.rotation == 90
        tank_run = _run_by_text(model, "Tank")
        buffer_run = _run_by_text(model, "Buffer")
        hit = _hit_on(model, tank_run)
        assert hit.target_text == "Buffer Tank"
        ref = _source_ref(hit)
        assert ref is not None
        replay = replay_page_streams(
            [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
        )
        expected = _origin_in_page_space(page, replay.shows[ref.seq])
        assert expected is not None
        assert abs(ref.origin[0] - expected[0]) <= _ORIGIN_TOL
        assert abs(ref.origin[1] - expected[1]) <= _ORIGIN_TOL
        visual_first = unrotated_to_visual_point(page, fitz.Point(buffer_run.origin))
        assert abs(fitz.Point(ref.origin) - visual_first) <= 0.05
        assert _rect_close(hit.target_bbox, _visual_union(model, [buffer_run, tank_run]))
    finally:
        model.close()


def test_simple_font_show_groups_through_latin1(tmp_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Buffer Tank", fontname="helv", fontsize=12)
    model = _open_model(tmp_path, doc, "helv")
    try:
        tank_run = _run_by_text(model, "Tank")
        hit = _hit_on(model, tank_run)
        assert hit.target_text == "Buffer Tank"
        assert _source_ref(hit) is not None
    finally:
        model.close()


def test_twin_identical_shows_get_distinct_source_refs(tmp_path: Path) -> None:
    fixture = build_identity_h_fixture("Buffer Tank")
    _append_show(fixture, "Buffer Tank", 72.0, 600.0)
    model = _fixture_model(tmp_path, fixture, "twins")
    try:
        first = _hit_on(model, _run_by_text(model, "Tank", nth=0))
        second = _hit_on(model, _run_by_text(model, "Tank", nth=1))
        assert first.target_text == second.target_text == "Buffer Tank"
        ref_a, ref_b = _source_ref(first), _source_ref(second)
        assert ref_a is not None and ref_b is not None
        assert ref_a != ref_b
        assert {ref_a.seq, ref_b.seq} == {0, 1}
        assert ref_a.op_start != ref_b.op_start
        assert set(_members(first)).isdisjoint(_members(second))
    finally:
        model.close()


# ------------------------------------------- negatives (paired with the positives)


def test_two_tj_on_one_baseline_is_not_grouped(tmp_path: Path) -> None:
    """``<Buffer> Tj < Tank> Tj`` extracts as the SAME two runs as one show.

    Paired with ``test_buffer_tank_rot0_hit_is_the_whole_show``: identical
    runs, but the line is two shows, so the hit must stay the single word
    (which then refuses at binding -- safe) and carry no ``source_ref``.

    PAIRED NEGATIVE: passes before the resolver exists (today's hit is one
    word with no ``source_ref``); it is meaningful only next to its positive
    control.  Refused twice over: text proof ("Buffer" != "BufferTank") and
    the pen-continuing-successor rule.
    """
    model = _fixture_model(
        tmp_path, build_identity_h_fixture("Buffer", tail_text=" Tank"), "twoshow"
    )
    try:
        assert [r.text for r in _runs(model)] == ["Buffer", "Tank"]
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert _source_ref(hit) is None
        assert hit.target_text == "Tank"
        hit = _hit_on(model, _run_by_text(model, "Buffer"))
        assert _source_ref(hit) is None
        assert hit.target_text == "Buffer"
    finally:
        model.close()


def test_foreign_show_origin_inside_union_refuses(tmp_path: Path) -> None:
    """A second, positioned (reliable-origin) show inside the union refuses.

    The foreign show paints nothing (empty operand), so the text and glyph
    proofs still pass: only the foreign-origin check can refuse here.

    PAIRED NEGATIVE: passes before the resolver exists; proven live by a
    scratch mutation (foreign-origin loop disabled -> this test fails).
    """
    fixture = build_identity_h_fixture("Buffer Tank")
    # Inside the union: x between the two words, just above the baseline.
    append_page_content(
        fixture, f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 100 702 Tm <> Tj ET"
    )
    model = _fixture_model(tmp_path, fixture, "foreign")
    try:
        assert [r.text for r in _runs(model)] == ["Buffer", "Tank"]
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert _source_ref(hit) is None
        assert hit.target_text == "Tank"
    finally:
        model.close()


def test_pen_continuing_successor_show_refuses(tmp_path: Path) -> None:
    """A successor show with an untracked (unreliable) origin refuses the group.

    Replay does not track advances, so a show that continues the pen of the
    candidate has no provable origin; the resolver cannot prove it lies
    outside the union and fails closed.

    PAIRED NEGATIVE: passes before the resolver exists; proven live by a
    scratch mutation (successor rule disabled -> this test fails).
    """
    fixture = build_identity_h_fixture("Buffer Tank")
    stream = fixture.content_bytes()
    assert stream.rstrip().endswith(b"ET")
    fixture.doc.update_stream(
        fixture.content_xref, stream.rstrip()[:-2] + b" <> Tj ET"
    )
    model = _fixture_model(tmp_path, fixture, "successor")
    try:
        page = model.doc[0]
        shows = replay_page_streams(
            [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
        ).shows
        assert len(shows) == 2 and shows[1].origin_reliable is False
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert _source_ref(hit) is None
        assert hit.target_text == "Tank"
    finally:
        model.close()



# ------------------------------------ F1: one show, one line; untracked painters
#
# VERIFY finding F1 (2026-09-30): the proof bound an untracked-pen show's
# extracted line to the reliable show it was painted over.  Rule (5) looked
# only at the candidate's immediate successor, and nothing stopped two lines
# claiming the same show.  Every refusal below is paired with a positive.

_A_SHOW = "BT /{F} 12 Tf 1 0 0 1 72 700 Tm (Buffer Tank) Tj ET "


def _helv_body_model(tmp_path: Path, body: str, name: str) -> PDFModel:
    """A helv page whose whole content stream is ``body`` (``{F}`` = font name)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "x", fontname="helv", fontsize=12)
    font_name = page.get_fonts(full=True)[0][4]
    doc.update_stream(page.get_contents()[0], body.format(F=font_name).encode("latin-1"))
    return _open_model(tmp_path, doc, name)


def _type0_body_model(tmp_path: Path, body: str, name: str) -> PDFModel:
    """An Identity-H page whose content stream is ``body`` (``{F}`` = resource)."""
    fixture = build_identity_h_fixture("Buffer Tank")
    fixture.doc.update_stream(
        fixture.content_xref, body.format(F=fixture.resource_name).encode("ascii")
    )
    return _fixture_model(tmp_path, fixture, name)


def _hx(text: str) -> str:
    return "<" + encode_cids(text).hex().upper() + ">"


def _page_shows(model: PDFModel, page_idx: int = 0) -> tuple:
    page = model.doc[page_idx]
    return replay_page_streams(
        [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
    ).shows


def _grouped_lines(model: PDFModel) -> dict[tuple[int, int], int]:
    """(block, line) -> claimed show seq, for every proven group on page 0."""
    from model.text_commit.source_run import group_page_runs

    runs = {r.span_id: r for r in _runs(model)}
    groups = group_page_runs(
        model.doc, model.doc[0], list(runs.values()), registry=DocumentFontRegistry(model.doc)
    )
    out: dict[tuple[int, int], int] = {}
    for span_id, group in groups.items():
        run = runs[span_id]
        out[(int(run.block_idx), int(run.line_idx))] = int(group.source_ref.seq)
    return out


def test_untracked_pen_show_over_a_reliable_show_is_never_proven_as_it(
    tmp_path: Path,
) -> None:
    """The verbatim F1 counterexample: D (untracked pen) repaints A at 72,700.

    ``10 700 Tm 56 Tc (x) Tj 0 Tc (Buffer Tank) Tj`` puts D's glyphs exactly
    on A's; D's extracted line starts at A's origin, so the origin test alone
    proved D's line as A (seq 0).  Both new rules refuse it independently:
    two lines claim seq 0, and D is an untracked painter on A's baseline.
    """
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 1 0 0 1 10 700 Tm 56 Tc (x) Tj 0 Tc (Buffer Tank) Tj ET",
        "f1_verbatim",
    )
    try:
        assert [s.origin_reliable for s in _page_shows(model)] == [True, True, False]
        buffers = [r for r in _runs(model) if r.text == "Buffer"]
        assert len(buffers) == 2 and len({r.line_idx for r in buffers}) == 2
        assert _grouped_lines(model) == {}
        for run in _runs(model):
            hit = _hit_on(model, run)
            assert _source_ref(hit) is None, run.span_id
            assert hit.target_text in {"Buffer", "Tank", "x"}
    finally:
        model.close()


def test_one_show_claimed_by_two_lines_groups_neither(tmp_path: Path) -> None:
    """A RELIABLE painter (a TJ kern lands its glyphs on A): uniqueness alone refuses.

    ``[(x) -4666.667 (Buffer Tank)] TJ`` from 10,700 paints 'Buffer Tank' at
    exactly 72,700.  Its origin is reliable and outside A's union and it is
    not A's successor, so only the one-claim-per-show rule sees that the
    second extracted line also claims A.
    """
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 1 0 0 1 10 700 Tm [(x) -4666.667 (Buffer Tank)] TJ ET",
        "two_claims",
    )
    try:
        assert all(s.origin_reliable for s in _page_shows(model))
        firsts = [r for r in _runs(model) if r.text == "Buffer"]
        assert len(firsts) == 2 and len({r.line_idx for r in firsts}) == 2
        assert all(abs(float(r.origin.x) - 72.0) < 0.05 for r in firsts), "painter must land on A"
        assert _grouped_lines(model) == {}
        for run in firsts:
            assert _source_ref(_hit_on(model, run)) is None
    finally:
        model.close()


def test_untracked_show_painting_inside_the_union_refuses(tmp_path: Path) -> None:
    """An untracked painter the uniqueness rule cannot see.

    ``10 700 Tm 70 Tc (x) Tj 0 Tc (Q) Tj`` paints 'Q' at x=86, inside A's
    union, as its OWN extracted line: only A's line claims A.  Replay cannot
    say where Q lands, only that it lies on the text line of its last
    repositioning; that line crosses A's union, so A cannot be proven.
    """
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 1 0 0 1 10 700 Tm 70 Tc (x) Tj 0 Tc (Q) Tj ET",
        "untracked_inside",
    )
    try:
        q_run = _run_by_text(model, "Q")
        buffer_run = _run_by_text(model, "Buffer")
        tank_run = _run_by_text(model, "Tank")
        assert q_run.line_idx != buffer_run.line_idx
        assert fitz.Rect(buffer_run.bbox).x0 < float(q_run.origin.x) < fitz.Rect(tank_run.bbox).x1
        assert _grouped_lines(model) == {}
        hit = _hit_on(model, tank_run)
        assert _source_ref(hit) is None
        assert hit.target_text == "Tank"
    finally:
        model.close()


def test_untracked_show_on_a_far_baseline_keeps_the_group(tmp_path: Path) -> None:
    """PAIRED CONTROL (passes before and after): the untracked extent is BOUNDED.

    The same untracked chain 300 pt below A must not refuse A -- this is what
    separates the band rule from "any untracked show on the page refuses".
    """
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 1 0 0 1 10 400 Tm 70 Tc (x) Tj 0 Tc (Q) Tj ET",
        "untracked_far",
    )
    try:
        assert _page_shows(model)[-1].origin_reliable is False
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert hit.target_text == "Buffer Tank"
        ref = _source_ref(hit)
        assert ref is not None and ref.seq == 0
    finally:
        model.close()


def test_untracked_show_in_an_unresolvable_font_refuses_anywhere(tmp_path: Path) -> None:
    """Fail closed: no font evidence -> the across-baseline extent is unbounded.

    ``/F9`` is not in the page resources, so neither the writing direction
    nor the glyph extent of the untracked show can be bounded; even 300 pt
    away it may paint into A's union.
    """
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 1 0 0 1 10 400 Tm (x) Tj /F9 12 Tf (Q) Tj ET",
        "untracked_nofont",
    )
    try:
        last = _page_shows(model)[-1]
        assert last.font_resource == "F9" and last.origin_reliable is False
        assert _grouped_lines(model) == {}
    finally:
        model.close()


def test_untracked_show_under_a_singular_text_matrix_refuses(tmp_path: Path) -> None:
    """Fail closed: a non-invertible text matrix cannot be mapped to text space."""
    model = _helv_body_model(
        tmp_path,
        _A_SHOW + "BT /{F} 12 Tf 0 0 0 0 10 400 Tm (x) Tj (Q) Tj ET",
        "untracked_singular",
    )
    try:
        assert _page_shows(model)[-1].origin_reliable is False
        assert _grouped_lines(model) == {}
    finally:
        model.close()


# ------------------------- F2: the group text is what the page's line shows
#
# VERIFY finding F2 (2026-09-30): MuPDF synthesizes a space from a TJ kern
# (and from positive Tc) that is NOT in the decoded show text, and the
# whitespace-stripped equality accepted it, so the editor showed
# 'BufferTank' for a page that reads 'Buffer Tank'.  Where MuPDF inserts
# that space is its own gap heuristic (helv 12 pt: kern -100 no space,
# -150 space; Tc 1.5 no space, 2.0 spaces), which stream bytes cannot
# prove -- so these shows are never grouped.


@pytest.mark.parametrize("font_kind", ["helv", "type0"])
def test_kerned_tj_array_is_not_grouped(tmp_path: Path, font_kind: str) -> None:
    if font_kind == "helv":
        model = _helv_body_model(
            tmp_path,
            "BT /{F} 12 Tf 1 0 0 1 72 700 Tm [(Buffer) -400 (Tank)] TJ ET",
            "tj_kern_helv",
        )
    else:
        model = _type0_body_model(
            tmp_path,
            "BT /{F} 12 Tf 1 0 0 1 72 700 Tm ["
            + _hx("Buffer")
            + " -400 "
            + _hx("Tank")
            + "] TJ ET",
            "tj_kern_type0",
        )
    try:
        assert model.doc[0].get_text().strip() == "Buffer Tank"
        assert [r.text for r in _runs(model)] == ["Buffer", "Tank"]
        assert _grouped_lines(model) == {}
        for run in _runs(model):
            hit = _hit_on(model, run)
            assert _source_ref(hit) is None
            assert hit.target_text == run.text
    finally:
        model.close()


def test_tj_array_repeating_its_text_is_not_grouped(tmp_path: Path) -> None:
    """'[(Buffer Tank) -500 (Buffer Tank)] TJ' reads 'Buffer Tank Buffer Tank'."""
    model = _helv_body_model(
        tmp_path,
        "BT /{F} 12 Tf 1 0 0 1 72 700 Tm [(Buffer Tank) -500 (Buffer Tank)] TJ ET",
        "tj_twice",
    )
    try:
        assert model.doc[0].get_text().strip() == "Buffer Tank Buffer Tank"
        assert _grouped_lines(model) == {}
        hit = _hit_on(model, _run_by_text(model, "Tank", nth=1))
        assert _source_ref(hit) is None
        assert hit.target_text == "Tank"
    finally:
        model.close()


def test_single_item_tj_array_still_groups(tmp_path: Path) -> None:
    """PAIRED CONTROL (passes before and after): one string item has no kern gap."""
    model = _helv_body_model(
        tmp_path,
        "BT /{F} 12 Tf 1 0 0 1 72 700 Tm [(Buffer Tank)] TJ ET",
        "tj_single",
    )
    try:
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert hit.target_text == "Buffer Tank" == model.doc[0].get_text().strip()
        assert _source_ref(hit) is not None
    finally:
        model.close()


@pytest.mark.parametrize("font_kind", ["helv", "type0"])
def test_positive_char_spacing_show_is_not_grouped(tmp_path: Path, font_kind: str) -> None:
    """Same defect class from a single-string show: Tc gaps become page spaces.

    helv ``2 Tc (BufferTank)`` reads 'B u f f e r T a n k'; Type0 ``8 Tc``
    '設計圖說A版' reads '設計圖說A 版'.  Both grouped with the decoded text.
    """
    if font_kind == "helv":
        model = _helv_body_model(
            tmp_path, "BT /{F} 12 Tf 1 0 0 1 72 700 Tm 2 Tc (BufferTank) Tj ET", "tc_helv"
        )
        page_text = "B u f f e r T a n k"
    else:
        model = _type0_body_model(
            tmp_path,
            "BT /{F} 12 Tf 1 0 0 1 72 700 Tm 8 Tc " + _hx("設計圖說A版") + " Tj ET",
            "tc_type0",
        )
        page_text = "設計圖說A 版"
    try:
        assert model.doc[0].get_text().strip() == page_text
        assert _grouped_lines(model) == {}
        run = _runs(model)[-1]
        hit = _hit_on(model, run)
        assert _source_ref(hit) is None
        assert hit.target_text == run.text
    finally:
        model.close()


# -------------------------------------------------------------- outlines


def test_run_mode_outline_is_the_grouped_union(tmp_path: Path) -> None:
    fixture = build_identity_h_fixture("Buffer Tank")
    _append_show(fixture, "Pump", 72.0, 600.0)
    model = _fixture_model(tmp_path, fixture, "outline")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        tank_run = _run_by_text(model, "Tank")
        targets = model.get_text_targets(0, "run")
        texts = [t.text for t in targets]
        assert texts == ["Buffer Tank", "Pump"], texts
        grouped = targets[0]
        union = _visual_union(model, [buffer_run, tank_run])
        assert _rect_close(fitz.Rect(grouped.bbox), union)
        hit = _hit_on(model, tank_run)
        assert _rect_close(fitz.Rect(grouped.bbox), hit.target_bbox)
        # Paragraph targets are untouched by run grouping.
        assert all(t.text != "Tank" for t in targets)
    finally:
        model.close()


# ------------------------------------------------ no live extraction / cache


def test_guard_resolver_never_queries_live_extraction(tmp_path: Path, monkeypatch) -> None:
    """GUARD (passes before the resolver exists): hit path stays extraction-free.

    Plan section 6 records live-document side effects of ``get_texttrace``
    (page dict re-serialisation) and of default-flag rawdict/image queries
    (image-store warming).  After the index is built, a grouped hit must be
    answerable from stream bytes and the font registry alone.
    """
    model = _fixture_model(tmp_path, build_identity_h_fixture("Buffer Tank"), "guard")
    try:
        tank_run = _run_by_text(model, "Tank")
        point = _visual_centre(model, tank_run)
        calls: list[str] = []

        def _forbid(name):
            def _raise(self, *args, **kwargs):
                calls.append(name)
                raise AssertionError(f"live extraction call: {name}")
            return _raise

        for name in ("get_text", "get_texttrace", "get_drawings", "get_image_rects"):
            monkeypatch.setattr(fitz.Page, name, _forbid(name))
        hit = model.get_text_info_at_point(1, point)
        targets = model.get_text_targets(0, "run")
        assert calls == []
        assert hit is not None and targets
    finally:
        monkeypatch.undo()
        model.close()


def test_resolver_cache_is_warm_and_pull_invalidated(tmp_path: Path, monkeypatch) -> None:
    from model.text_commit import source_run

    fixture = build_identity_h_fixture("Buffer Tank")
    model = _fixture_model(tmp_path, fixture, "cache")
    try:
        replays: list[int] = []
        real_replay = source_run.replay_page_streams

        def _counting(*args, **kwargs):
            replays.append(1)
            return real_replay(*args, **kwargs)

        monkeypatch.setattr(source_run, "replay_page_streams", _counting)
        tank_run = _run_by_text(model, "Tank")
        assert _hit_on(model, tank_run).target_text == "Buffer Tank"
        cold = len(replays)
        assert cold == 1
        for _ in range(3):
            assert _hit_on(model, tank_run).target_text == "Buffer Tank"
            model.get_text_targets(0, "run")
        assert len(replays) == cold, "warm hits must reuse the cached page groups"

        # A live content change (stream bytes) invalidates by digest, even with
        # the SAME index object still in place.
        page = model.doc[0]
        xref = page.get_contents()[0]
        old = model.doc.xref_stream(xref)
        new_hex = encode_cids("Buffer Tuna").hex().upper().encode("ascii")
        old_hex = encode_cids("Buffer Tank").hex().upper().encode("ascii")
        model.doc.update_stream(xref, old.replace(old_hex, new_hex))
        stale_hit = _hit_on(model, tank_run)
        assert len(replays) == cold + 1
        assert _source_ref(stale_hit) is None, "index says 'Tank', stream says 'Tuna'"

        # Index rebuild (what commit/undo do) re-proves against the new runs.
        model.block_manager.rebuild_page(0, model.doc)
        tuna_run = _run_by_text(model, "Tuna")
        assert _hit_on(model, tuna_run).target_text == "Buffer Tuna"
        assert len(replays) == cold + 2
    finally:
        model.close()


# ------------------------------------------------------------ real corpus


@pytest.mark.needs_fixtures
def test_real_corpus_run_hit_is_the_decoded_show(tmp_path: Path) -> None:
    import shutil

    import test_text_commit_real_corpus_acceptance as acc
    from test_scripts.true_text_corpus import MIN_ACTIVE_POSITIVES, load_manifest

    manifest = load_manifest()
    refs_by_case: dict[str, object] = {}
    checked = 0
    for spec in manifest.click_reachable_specs():
        source = acc._fixture(spec)
        work = tmp_path / Path(spec.relative_path).name
        shutil.copyfile(source, work)
        model = PDFModel()
        try:
            model.open_pdf(str(work))
            model.set_text_target_mode("run")
            doc = model.doc
            cases = acc._resolve_cases(spec, doc)
            registry = DocumentFontRegistry(doc)
            for case in cases:
                page_idx = case.page_index
                page = doc[page_idx]
                model.ensure_page_index_built(page_idx + 1)
                show = acc._shows(doc, page_idx)[case.show_seq]
                decoded = acc._decode_show(registry, page, show)
                assert decoded == case.original
                show_dict = fitz.Point(*show.origin_user) * acc.visual_frame(page).base
                runs = list(model.block_manager.get_runs(page_idx))
                first = next(
                    (r for r in runs if abs(fitz.Point(r.origin) - show_dict) < 0.05), None
                )
                assert first is not None, f"{spec.slug} p{page_idx}/show{case.show_seq}: no run at show origin"
                line = sorted(
                    (r for r in runs if (r.block_idx, r.line_idx) == (first.block_idx, first.line_idx)),
                    key=lambda r: r.span_idx,
                )
                last = line[-1]
                centre = unrotated_to_visual_rect(page, fitz.Rect(last.bbox))
                point = fitz.Point((centre.x0 + centre.x1) / 2.0, (centre.y0 + centre.y1) / 2.0)
                hit = model.get_text_info_at_point(page_idx + 1, point)
                label = f"{spec.slug} p{page_idx}/show{case.show_seq}"
                assert hit is not None, label
                assert hit.target_text == decoded, label
                ref = _source_ref(hit)
                assert ref is not None, label
                assert ref.seq == case.show_seq, label
                assert ref.page_xref == page.xref, label
                assert _members(hit) == tuple(r.span_id for r in line), label
                refs_by_case[label] = ref
                checked += 1
        finally:
            model.close()
    assert checked == len(manifest.click_reachable_positives())
    assert checked >= MIN_ACTIVE_POSITIVES
    assert refs_by_case["hvac p6/show5"] != refs_by_case["hvac p6/show7"]
