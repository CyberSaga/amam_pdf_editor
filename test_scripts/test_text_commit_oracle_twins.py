"""ORACLE twins (slice I0b, stage S3a): the growth-zone and neighbour-glyph helpers, judged on synthetic pages.

CI lane, no marker: every document is built at run time.  The runner lives in
``test_scripts/frontier_twins.py`` (``twin_runs`` / ``judge`` / ``run_oracle_twin``), the helpers in
``test_scripts/true_text_acceptance_helpers.py``; plan section 4 holds the twin table.

Red-first record (stage S3a).  The helpers were first written as stubs (``growth_zone_checks`` returning
``(0, None)``, both ``check_*`` returning ``None``); the behaviour reds are the growth ``expected fail,
got pass`` on vi, viii, viii-b and x, the neighbours ones on vi, viii, viii-b and xii, the delegation spy
(rederive still had its own body), the parity ``glyphs:`` / ``oracle raised ValueError`` rows and the six
neighbour unit tests through their fail legs.  Red by import (attribute) only, labelled as such below:
the registry test, the four non-vacuity tests and the Q12 test.  The reds are pasted in
``plans/true-text-i0b.md``'s running log.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import verify  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.patch import build_transplant_replacement  # noqa: E402
from model.text_commit.pdf_lexer import splice_stream  # noqa: E402
from model.text_commit.stroke_occupancy import strokes_provably_clear  # noqa: E402
from scripts import evidence_rederive as rd  # noqa: E402
from test_scripts import frontier_twins  # noqa: E402
from test_scripts import painter_matrix_fixtures as pmf  # noqa: E402
from test_scripts import simple_font_fixture_builder as sfb  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402
from test_scripts import type0_fixture_builder as tb  # noqa: E402
from test_scripts.true_text_corpus import CorpusCase  # noqa: E402

SPECS = {spec.twin_id: spec for spec in frontier_twins.ORACLE_TWINS}
_ADAPTER_TARGETS = {
    "growth": "check_growth_zone_was_blank",
    "neighbours": "check_neighbour_glyphs_unchanged",
}


@pytest.fixture(scope="module")
def oracle_runs(tmp_path_factory):
    """Every twin's runs, built once per module (the non-vacuity tests judge them repeatedly)."""
    runs = {
        spec.twin_id: frontier_twins.twin_runs(spec, tmp_path_factory.mktemp(f"twin-{spec.twin_id}"))
        for spec in frontier_twins.ORACLE_TWINS
    }
    yield runs
    for twin_runs in runs.values():
        frontier_twins.close_runs(twin_runs)


# ----------------------------------------------------------------------------------------------
# the twins and the runner's own guards
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("spec", frontier_twins.ORACLE_TWINS, ids=lambda spec: spec.twin_id)
def test_oracle_twin(spec, tmp_path):
    assert frontier_twins.run_oracle_twin(spec, tmp_path) == []


def test_oracle_twin_registry_is_well_formed():
    """Red by import only (the registry did not exist): names, paths and heads are coherent."""
    ids = [spec.twin_id for spec in frontier_twins.ORACLE_TWINS]
    assert len(ids) == len(set(ids)) == 8
    for spec in frontier_twins.ORACLE_TWINS:
        assert not spec.must_fail & spec.must_pass, spec.twin_id
        assert (spec.must_fail | spec.must_pass) <= set(frontier_twins.ORACLE_HELPERS), spec.twin_id
        assert spec.paths and spec.paths <= {"product", "experiment"}, spec.twin_id
        assert ("experiment" in spec.paths) == (spec.experiment is not None), spec.twin_id
        assert ("product" in spec.paths) == (spec.product_expected is not None), spec.twin_id
        for name, head in spec.detail_heads:
            assert head
            assert name == "product" or name in spec.must_fail, (spec.twin_id, name)
            assert name != "product" or "product" in spec.paths, (spec.twin_id, name)
        # a crashing core yields ``oracle raised <Type>``, which counts as an expected fail unless a head is pinned
        assert spec.must_fail <= {name for name, _ in spec.detail_heads}, spec.twin_id
    assert set(frontier_twins.ORACLE_HELPERS) == set(_ADAPTER_TARGETS)


@pytest.mark.parametrize("name", sorted(_ADAPTER_TARGETS))
def test_a_no_op_helper_turns_every_must_fail_twin_red(name, monkeypatch, oracle_runs):
    """Red by import only.  Non-vacuity: with the helper stubbed to pass, every twin that needs it to fail is red."""
    monkeypatch.setattr(helpers, _ADAPTER_TARGETS[name], lambda *args, **kwargs: None)
    specs = [spec for spec in frontier_twins.ORACLE_TWINS if name in spec.must_fail]
    assert specs
    for spec in specs:
        mismatches = frontier_twins.judge(spec, oracle_runs[spec.twin_id])
        assert any(f"/{name}:" in mismatch for mismatch in mismatches), (spec.twin_id, mismatches)


@pytest.mark.parametrize("name", sorted(_ADAPTER_TARGETS))
def test_an_always_failing_helper_turns_every_must_pass_twin_red(name, monkeypatch, oracle_runs):
    """Red by import only.  The mirror: with the helper stubbed to fail, every twin that needs it to pass is red."""
    monkeypatch.setattr(helpers, _ADAPTER_TARGETS[name], lambda *args, **kwargs: "stub: fail")
    specs = [spec for spec in frontier_twins.ORACLE_TWINS if name in spec.must_pass]
    assert specs
    for spec in specs:
        mismatches = frontier_twins.judge(spec, oracle_runs[spec.twin_id])
        assert any(f"/{name}:" in mismatch for mismatch in mismatches), (spec.twin_id, mismatches)


# ----------------------------------------------------------------------------------------------
# premise tests: the twins test what they claim
# ----------------------------------------------------------------------------------------------
def test_twin_vii_exercises_the_stroke_proof(oracle_runs):
    """(vii) passes because the page-frame stroke overlaps the growth strip's box and is PROVABLY clear."""
    (run,) = oracle_runs["vii"]
    prepared = run.prepared
    assert prepared is not None and prepared.has_ink_growth
    with helpers._measurement_copy(run.source) as copy:
        page = copy[0]
        zone = verify._growth_zone_rect(prepared.target_bbox_page, prepared.effective_verify_bbox)
        assert zone is not None
        growth_dict = verify._growth_rect_in_dict_space(page, zone)
        overlapping = [
            drawing
            for drawing in page.get_drawings()
            if verify._rects_overlap(fitz.Rect(drawing["rect"]), growth_dict)
        ]
        assert overlapping, "the frame stroke must overlap the growth zone's box, or the proof is not exercised"
        assert strokes_provably_clear(
            page,
            overlapping,
            zone,
            to_visual=run.frame.quarter_turn,
            margin=verify._STROKE_CLEARANCE_MARGIN_PT,
        )
        assert verify._drawings_intersect_growth(page, zone) is False


def test_twin_viii_b_locates_through_the_frame(oracle_runs, monkeypatch):
    """(viii-b) is one odd page (/UserUnit 2, an offset CropBox, /Rotate 90): the located box is the frame box."""
    (run,) = oracle_runs["viii-b"]
    assert run.frame.user_unit == 2.0
    assert run.frame.rotation == 90
    doc = fitz.open("pdf", run.source.tobytes())
    try:
        resource = helpers._shows(doc, 0)[0].font_resource
        with helpers._measurement_copy(doc) as copy:
            trace = helpers._trace_for(copy[0], helpers._shows(doc, 0)[0], tb.CJK_TEXT)
        seen: dict = {}
        real_prepare = TieredCommitEngine.prepare

        def spy(self, page, **kwargs):
            seen.update(kwargs)
            return real_prepare(self, page, **kwargs)

        monkeypatch.setattr(TieredCommitEngine, "prepare", spy)
        case = CorpusCase(
            page_index=0,
            show_seq=0,
            original=tb.CJK_TEXT,
            replacement=tb.REPLACEMENT_LONGER,
            font_resource=resource,
            basefont="fixture",
        )
        helpers._prepare(TieredCommitEngine(doc, max_tier=1), doc, case)
    finally:
        doc.close()
    assert seen["target_bbox"] == tuple(fitz.Rect(trace["bbox"]) * run.frame.quarter_turn)
    assert fitz.Rect(seen["target_bbox"]).intersects(run.source[0].rect)


# ----------------------------------------------------------------------------------------------
# rederive consumption: one core, parity with rederive's own built-in oracle
# ----------------------------------------------------------------------------------------------
def _growth_context(run, *, x_pre: float | None = 0.0, k_inner: float | None = 0.0) -> rd.OracleContext:
    return rd.OracleContext(
        source_doc=run.source,
        after_doc=run.after,
        page_index=0,
        show=run.before_show,
        frame=run.frame,
        target_bbox_visual=run.target_vis,
        verify_bbox_visual=run.verify_vis,
        adv_old=run.adv_old,
        prepared=None,
        case={},
        x_pre=x_pre,
        k_inner=k_inner,
    )


def _helper_growth(run, *, x_pre: float | None = 0.0, k_inner: float | None = 0.0) -> str | None:
    return helpers.check_growth_zone_was_blank(
        run.source,
        0,
        run.before_show,
        run.frame,
        run.target_vis,
        run.verify_vis,
        run.adv_old,
        prepared=None,
        x_pre=x_pre,
        k_inner=k_inner,
    )


@pytest.fixture(scope="module")
def blank_run(tmp_path_factory):
    spec = dataclasses.replace(
        SPECS["vi"], twin_id="parity-blank", build=lambda: tb.build_identity_h_fixture().doc
    )
    runs = frontier_twins.twin_runs(spec, tmp_path_factory.mktemp("parity-blank"))
    yield runs[0]
    frontier_twins.close_runs(runs)


def test_parity_growth_oracle_reports_the_glyphs_in_the_zone(oracle_runs):
    (run,) = oracle_runs["vi"]
    detail = _helper_growth(run)
    assert detail is not None and detail.startswith("glyphs: ")
    assert detail == rd.assert_growth_zone_was_blank(_growth_context(run))


def test_parity_growth_oracle_passes_a_blank_zone(blank_run):
    assert blank_run.verify_vis != blank_run.target_vis
    assert _helper_growth(blank_run) is None
    assert rd.assert_growth_zone_was_blank(_growth_context(blank_run)) is None


def test_product_shape_growth_oracle_checks_the_background_quad(oracle_runs):
    """Twin vii in product shape: a perturbed ``adv_old`` makes the metric quad differ from the prepared one."""
    (run,) = oracle_runs["vii"]
    assert run.prepared is not None

    def growth(adv_old: float) -> str | None:
        return helpers.check_growth_zone_was_blank(
            run.source,
            0,
            run.before_show,
            run.frame,
            run.target_vis,
            run.verify_vis,
            adv_old,
            prepared=run.prepared,
            x_pre=0.0,
            k_inner=0.0,
        )

    assert growth(run.adv_old) is None
    assert growth(run.adv_old + 0.5) == "background: the prepared quad differs from the metric quad"


def test_parity_growth_oracle_is_not_applicable_without_growth(oracle_runs):
    (run,) = oracle_runs["vi"]
    flat = dataclasses.replace(run, verify_vis=run.target_vis)
    assert _helper_growth(flat) is None
    assert rd.assert_growth_zone_was_blank(_growth_context(flat)) is None


def test_parity_growth_oracle_refuses_an_unprovable_slice_origin(oracle_runs):
    (run,) = oracle_runs["vi"]
    for terms in ({"x_pre": None}, {"k_inner": None}):
        assert _helper_growth(run, **terms) == "oracle raised ValueError"
        assert rd.assert_growth_zone_was_blank(_growth_context(run, **terms)) == "oracle raised ValueError"


def test_rederive_growth_checks_delegates_to_the_helper_core(oracle_runs, monkeypatch):
    """The rederive wrapper owns ctx unpacking and the ``_ascii`` boundary; the body is the helper's core."""
    (run,) = oracle_runs["vi"]
    calls: list[tuple] = []
    detail = "raster: " + "x" * 400 + "é"

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return 3, detail

    monkeypatch.setattr(helpers, "growth_zone_checks", spy)
    ctx = _growth_context(run)
    glyphs, got = rd._growth_checks(ctx)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (run.source, 0, run.before_show, run.frame, run.target_vis, run.verify_vis, run.adv_old)
    assert kwargs == {"prepared": None, "x_pre": 0.0, "k_inner": 0.0}
    assert glyphs == 3
    assert got == rd._ascii(detail) and len(got) == 300
    monkeypatch.setattr(helpers, "growth_zone_checks", lambda *args, **kwargs: (0, None))
    assert rd._growth_checks(ctx) == (0, None)


# ----------------------------------------------------------------------------------------------
# neighbour helper unit tests (documents built in memory; no saveIncr)
# ----------------------------------------------------------------------------------------------
def _documents(build, new_stream_of) -> tuple[fitz.Document, fitz.Document]:
    """``(source, after)``: the built page and a copy whose show stream is ``new_stream_of(source, show)``."""
    built = build()
    data = built.tobytes()
    built.close()
    source = fitz.open("pdf", data)
    show = helpers._shows(source, 0)[0]
    after = fitz.open("pdf", data)
    after.update_stream(show.stream_xref, new_stream_of(source, show))
    return source, after


def _kern_splice(target: str, replacement: str):
    def new_stream(source, show):
        rep, _, _ = frontier_twins.e_kern(source, show, target, replacement)
        return splice_stream(source.xref_stream(show.stream_xref), [rep])

    return new_stream


def _neighbours(source, after, *, kind="positive", pre=0, post=0, code_bytes=None, measurements=None, **kwargs):
    before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
    if code_bytes is None:
        code_bytes = frontier_twins._code_bytes(source, before_show)
    edited = [helpers.edited_show(before_show, after_show, code_bytes=code_bytes, pre=pre, post=post)]
    return helpers.check_neighbour_glyphs_unchanged(
        source,
        after,
        0,
        edited,
        kind=kind,
        frame=helpers.visual_frame(source[0]),
        measurements=measurements,
        **kwargs,
    )


def test_neighbours_check_in_show_successors_of_a_slice_target():
    """``(ABCDEF) Tj`` -> ``[(ABXYZ) 600 (EF)] TJ``: slice target CD (pre 2, post 2), successors E, F held in place by K.

    Deviation from the s3a spec's wording: its pass leg ran as a judged kind, but holding E in place under a
    three-glyph replacement makes Z overprint E, so the pass leg runs as ``negative`` (overlap not judged)
    and the judged kind is asserted to report that overlap alone."""

    def splice(kern: str):
        def new_stream(source, show):
            stream = source.xref_stream(show.stream_xref)
            return splice_stream(
                stream,
                [build_transplant_replacement(stream, show, f"[(ABXYZ) {kern} (EF)] TJ".encode("ascii"))],
            )

        return new_stream

    build = lambda: sfb.build_embedded_simple_fixture("winansi", "ABCDEF").doc  # noqa: E731
    source, after = _documents(build, splice("600"))
    try:
        edited = helpers.edited_show(
            helpers._shows(source, 0)[0], helpers._shows(after, 0)[0], code_bytes=1, pre=2, post=2
        )
        assert (edited.pre, edited.n_old, edited.n_new, edited.post) == (2, 2, 3, 2)
        # K = 600 holds E and F where they were, so the third new glyph overprints E by construction:
        # the position legs pass, and a judged kind reports exactly the overlap and nothing else
        measurements: dict = {}
        assert _neighbours(source, after, kind="negative", pre=2, post=2, measurements=measurements) is None
        assert measurements["glyphs_paired"] == 4 and measurements["max_inshow_dev"] <= 1e-6
        assert _neighbours(source, after, pre=2, post=2) == "neighbours: overlap: 1 glyph(s)"
    finally:
        source.close()
        after.close()
    source, after = _documents(build, splice("0"))  # no compensation: E and F move a whole glyph
    try:
        detail = _neighbours(source, after, kind="negative", pre=2, post=2)
        assert detail is not None and detail.startswith("neighbours: ")
        assert "inshow_moved: 2 glyph(s)" in detail
    finally:
        source.close()
        after.close()


def test_neighbours_skip_tounicode_continuation_items():
    """A two-codepoint ToUnicode entry adds a gid -1 item that must not shift the pairing."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.map_cid_to_two_codepoints(fixture, tb.cid_for("好"))
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        with helpers._measurement_copy(source) as copy:
            items = [item for span in copy[0].get_texttrace() for item in span["chars"]]
        assert any(item[1] < 0 for item in items), "premise: the before trace holds a gid -1 continuation item"
        assert _neighbours(source, after) is None
        before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
        miscounted = helpers.EditedShow(0, before_show, after_show, 5, 4)  # the continuation item counted
        detail = helpers.check_neighbour_glyphs_unchanged(
            source, after, 0, [miscounted], kind="positive", frame=helpers.visual_frame(source[0])
        )
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_pair_form_xobject_glyphs_positionally():
    """Glyphs drawn by a Form XObject have no ShowOp: they pair by position and must not move."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.install_text_form_xobject(
            fixture, name="Fm0", text=tb.TAIL_TEXT, fontsize=12.0, origin=(72.0, 500.0)
        )
        tb.append_page_content(fixture, "/Fm0 Do")
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_LONGER))
    try:
        assert _neighbours(source, after, kind="negative") is None
        form_xref = next(
            xref
            for xref in range(1, after.xref_length())
            if after.xref_is_stream(xref) and b"1 0 0 1 72 500 Tm" in (after.xref_stream(xref) or b"")
        )
        form_stream = after.xref_stream(form_xref)
        for moved in (b"73 500 Tm", b"72.001 500 Tm"):  # a whole point, then a thousandth: exact, no tolerance
            after.update_stream(form_xref, form_stream.replace(b"72 500 Tm", moved))
            detail = _neighbours(source, after, kind="negative")
            assert detail is not None and "untouched_moved:" in detail, moved
    finally:
        source.close()
        after.close()


def test_neighbours_overlap_fails_only_for_judged_kinds():
    spec = SPECS["vi"]
    source, after = _documents(spec.build, _kern_splice(spec.target, spec.replacement))
    try:
        for kind in ("negative", "census"):
            assert _neighbours(source, after, kind=kind) is None, kind
        for kind in ("positive", "control", "canary"):
            detail = _neighbours(source, after, kind=kind)
            assert detail is not None and "overlap: 1 glyph(s)" in detail, (kind, detail)
        with pytest.raises(ValueError):
            _neighbours(source, after, kind="no-such-kind")
    finally:
        source.close()
        after.close()


def test_neighbours_ink_landed_leg_turns_through_the_frame():
    """On a /Rotate 270 page, white painted over the new text fails ``ink_not_landed``; the clean edit passes."""

    def build():
        return tb.build_identity_h_fixture(rotate=270).doc

    new_stream = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)
    source, after = _documents(build, new_stream)
    try:
        measurements: dict = {}
        assert _neighbours(source, after, measurements=measurements) is None
        assert measurements["target_glyphs_ink_checked"] == 4
        assert measurements["min_ink_after_px_6x"] > 0
        stream = after.xref_stream(helpers._shows(after, 0)[0].stream_xref)
        after.update_stream(
            helpers._shows(after, 0)[0].stream_xref, stream + b" q 1 g 70 690 52 20 re f Q"
        )
        detail = _neighbours(source, after)
        assert detail is not None and "ink_not_landed:" in detail
    finally:
        source.close()
        after.close()


def test_neighbours_refuse_a_misaligned_pairing():
    spec = SPECS["vi"]
    source, after = _documents(spec.build, _kern_splice(spec.target, spec.replacement))
    try:
        before_show, after_show = helpers._shows(source, 0)[0], helpers._shows(after, 0)[0]
        frame = helpers.visual_frame(source[0])
        honest = helpers.EditedShow(0, before_show, after_show, 4, 5)
        assert helpers.check_neighbour_glyphs_unchanged(source, after, 0, [honest], kind="negative", frame=frame) is None
        crooked = helpers.EditedShow(0, before_show, after_show, 4, 6)  # one glyph too many on the after side
        detail = helpers.check_neighbour_glyphs_unchanged(source, after, 0, [crooked], kind="negative", frame=frame)
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_target_moved_leg():
    """Extra to the spec's six (written with the helper): the first target glyph's origin must not move."""

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert b"1 0 0 1 72 700 Tm" in spliced
        return spliced.replace(b"1 0 0 1 72 700 Tm", b"1 0 0 1 73 700 Tm")

    source, after = _documents(lambda: tb.build_identity_h_fixture().doc, new_stream)
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and "target_moved: 1 run(s)" in detail
    finally:
        source.close()
        after.close()


@pytest.mark.parametrize("rotate", [0, 270])
def test_neighbours_gid_and_ink_legs_catch_a_swapped_neighbour(rotate):
    """Extra to the spec's six: a neighbour redrawn as other glyphs in the same place changes gid and ink.

    Run unrotated and on /Rotate 270 (the rotation of ten of the historic fourteen): the ink leg's pixel boxes
    go through ``frame.quarter_turn``, and dropping it only shows on a rotated page."""
    tail_hex = tb.encode_cids(tb.TAIL_TEXT).hex().upper().encode("ascii")
    other_hex = tb.encode_cids(tb.REPLACEMENT_EQUAL_ADVANCE[:2]).hex().upper().encode("ascii")

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert tail_hex in spliced
        return spliced.replace(tail_hex, other_hex)

    source, after = _documents(
        lambda: tb.build_identity_h_fixture(tail_text=tb.TAIL_TEXT, rotate=rotate).doc, new_stream
    )
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None
        assert "gid_mismatch: 2 glyph(s)" in detail and "ink_changed: 2 glyph(s)" in detail
        assert "untouched_moved" not in detail
    finally:
        source.close()
        after.close()


def _coincident_second_show(fixture) -> None:
    """A second, separate show drawn at the first show's origin with the same text (fill+stroke style)."""
    hex_text = tb.encode_cids(tb.CJK_TEXT).hex().upper()
    tb.append_page_content(
        fixture, f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 700 Tm <{hex_text}> Tj ET"
    )


def test_neighbours_pair_a_coincident_unedited_show_as_untouched():
    """Two shows share one origin: the edited one is show 0, the other must stay a PAIRED neighbour.

    Before the fix every glyph within 0.02 pt of the edited origin counted as another emission of the edited
    show, so the second show was zipped in as a target run and never checked."""

    def build():
        fixture = tb.build_identity_h_fixture()
        _coincident_second_show(fixture)
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        measurements: dict = {}
        # the new glyphs overprint the untouched copy by construction: overlap is not judged for a negative row
        assert _neighbours(source, after, kind="negative", measurements=measurements) is None
        assert measurements["glyphs_paired"] == 4 and measurements["target_glyphs_after"] == 4
    finally:
        source.close()
        after.close()


def test_neighbours_catch_a_rewritten_coincident_show():
    other_hex = tb.encode_cids(tb.REPLACEMENT_EQUAL_ADVANCE).hex().upper().encode("ascii")
    original_hex = tb.encode_cids(tb.CJK_TEXT).hex().upper().encode("ascii")

    def build():
        fixture = tb.build_identity_h_fixture()
        _coincident_second_show(fixture)
        return fixture.doc

    def new_stream(source, show):
        spliced = _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)(source, show)
        assert original_hex in spliced  # the second show, untouched by the splice
        return spliced.replace(original_hex, other_hex)

    source, after = _documents(build, new_stream)
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and "gid_mismatch: 2 glyph(s)" in detail  # the last two glyphs are shared by both texts
    finally:
        source.close()
        after.close()


def test_neighbours_refuse_an_unmatched_coincident_glyph_count():
    """A Form XObject glyph at the edited origin has no ShowOp: the count cannot be matched to shows."""

    def build():
        fixture = tb.build_identity_h_fixture()
        pmf.install_text_form_xobject(
            fixture, name="Fm0", text=tb.TAIL_TEXT, fontsize=12.0, origin=(72.0, 700.0)
        )
        tb.append_page_content(fixture, "/Fm0 Do")
        return fixture.doc

    source, after = _documents(build, _kern_splice(tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE))
    try:
        detail = _neighbours(source, after, kind="negative")
        assert detail is not None and detail.startswith("neighbours: pairing")
    finally:
        source.close()
        after.close()


def test_neighbours_check_a_shrinking_slice_with_held_successors_as_positive():
    """``(ABCDEF)`` -> ``[(ABX) -600 (EF)] TJ``: a SHORTER slice with E, F held in place passes a judged kind."""
    build = lambda: sfb.build_embedded_simple_fixture("winansi", "ABCDEF").doc  # noqa: E731

    def new_stream(source, show):
        stream = source.xref_stream(show.stream_xref)
        return splice_stream(stream, [build_transplant_replacement(stream, show, b"[(ABX) -600 (EF)] TJ")])

    source, after = _documents(build, new_stream)
    try:
        edited = helpers.edited_show(
            helpers._shows(source, 0)[0], helpers._shows(after, 0)[0], code_bytes=1, pre=2, post=2
        )
        assert (edited.n_old, edited.n_new) == (2, 1)
        measurements: dict = {}
        assert _neighbours(source, after, pre=2, post=2, measurements=measurements) is None
        assert measurements["overlap_glyphs"] == 0 and measurements["glyphs_paired"] == 4
        assert measurements["max_inshow_dev"] <= 1e-6
    finally:
        source.close()
        after.close()


# ----------------------------------------------------------------------------------------------
# Q12: the in-show residual formula (a pure function in S3a; S4 applies it)
# ----------------------------------------------------------------------------------------------
def test_q12_inshow_residual_matches_the_measured_rows():
    """Red by import only (the function did not exist).  Half-up on the float32 width, per MuPDF."""
    kwargs = {"font_size": 10.0, "hscale": 100.0, "trm_scale": 1.0, "user_unit": 1.0}
    # 600.7 -> 600.4: r(600.7) = +0.3, r(600.4) = -0.4, so -0.7 width units = -0.007 pt at 10 pt
    assert helpers.q12_inshow_residual_pt([600.7], [600.4], **kwargs) == pytest.approx(-0.007, abs=1e-12)
    # float32(600.49999) is 600.5, which rounds UP: r = +0.50001 (a float64 floor would give -0.49999)
    kilo = {"font_size": 1000.0, "hscale": 100.0, "trm_scale": 1.0, "user_unit": 1.0}
    assert helpers.q12_inshow_residual_pt([], [600.49999], **kilo) == pytest.approx(0.50001, abs=1e-9)
    # the scale factors: Tz, the text/CTM scale and /UserUnit all multiply
    scaled = {"font_size": 10.0, "hscale": 50.0, "trm_scale": 0.5, "user_unit": 2.0}
    assert helpers.q12_inshow_residual_pt([600.7], [600.4], **scaled) == pytest.approx(-0.007 * 0.5 * 0.5 * 2.0, abs=1e-12)
    assert helpers.q12_inshow_residual_pt([600.0], [600.0], **kwargs) == 0.0
    with pytest.raises(ValueError):
        helpers.q12_inshow_residual_pt([None], [600.0], **kwargs)
