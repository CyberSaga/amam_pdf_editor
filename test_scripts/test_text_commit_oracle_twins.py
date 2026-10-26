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

Red-first record (stage S3b).  Stubs first (the four ``check_*`` returning ``None``, ``glyph_identity_inputs``
returning ``((), ())``): the behaviour reds are the 16 ``test_oracle_twin`` ids (``expected fail, got pass`` for
i-v, ``passed without checking any glyph`` for the guards and vi-xii), the seven-kind matrix, the unavailable
cases U2/U3/U4/U6/U7 (``DID NOT RAISE``) and the two forgery tests.  Red by import (attribute) only: the registry
test (17 ids), the non-vacuity pairs for the four new names and the id list in
``test_text_commit_frontier_twins.py``.  Written WITH the helper, not red-first: the split-stream refusal pin,
``no_outline``, U1, U5, the contradicting-inputs test and the premise tests (which pin Step 0 numbers).
"""
from __future__ import annotations

import dataclasses
import sys
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import verify  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.cid_fonts import read_embedded_font_program  # noqa: E402
from model.text_commit.plan import PlanRejection  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from model.text_commit.patch import build_transplant_replacement  # noqa: E402
from model.text_commit.pdf_lexer import splice_stream  # noqa: E402
from model.text_commit.stroke_occupancy import strokes_provably_clear  # noqa: E402
from scripts import evidence_rederive as rd  # noqa: E402
from test_scripts import frontier_twins  # noqa: E402
from test_scripts import painter_matrix_fixtures as pmf  # noqa: E402
from test_scripts import simple_font_fixture_builder as sfb  # noqa: E402
from test_scripts import stream_storage_fixtures as ssf  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402
from test_scripts import type0_fixture_builder as tb  # noqa: E402
from test_scripts.true_text_corpus import CorpusCase  # noqa: E402

SPECS = {spec.twin_id: spec for spec in frontier_twins.ORACLE_TWINS}
_ADAPTER_TARGETS = {
    "growth": "check_growth_zone_was_blank",
    "neighbours": "check_neighbour_glyphs_unchanged",
    "stream_range": "check_target_stream_changed_only_within",
    "wrapper": "check_wrapper_bytes_unchanged",
    "counts": "check_show_and_operator_counts_equal",
    "glyph_identity": "check_glyph_identity",
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
    assert len(ids) == len(set(ids)) == 18
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


# ----------------------------------------------------------------------------------------------
# S3b premise tests: the byte/wrapper twins test what they claim (observed at HEAD, Step 0)
# ----------------------------------------------------------------------------------------------
def test_twin_ii_deletes_the_closing_emc_inside_the_edited_stream(oracle_runs):
    """(ii): the wrapper closes in the edited stream before the defect and stays open after it.

    The render is unchanged by the deletion (the runner's pixel-mask assert only allows the halo to change),
    the replay is not malformed and counts no EMC underflow."""
    (run,) = oracle_runs["ii"]
    before = replay_page_streams(helpers.page_streams(run.source, 0))
    (wrapper_before,) = before.wrappers_for(run.before_show)
    assert wrapper_before.closed and wrapper_before.close_stream_xref == run.replacement.stream_xref
    after = replay_page_streams(helpers.page_streams(run.after, 0))
    (wrapper_after,) = after.wrappers_for(helpers._shows(run.after, 0)[0])
    assert not wrapper_after.closed and wrapper_after.close_stream_xref is None
    assert not after.malformed and after.mc_emc_underflows == 0 and len(after.shows) == len(before.shows)
    rep = run.replacement
    shrink = len(run.source.xref_stream(rep.stream_xref)) - len(run.after.xref_stream(rep.stream_xref))
    assert shrink == len(b" EMC") - (len(rep.replacement_bytes) - (rep.end - rep.start))


def test_twin_ii_split_stream_wrapper_is_refused_by_the_product():
    """Written with the helper (pins the Step 0 observation).  Why (ii) deletes an inline EMC: a BDC in stream A closed by an EMC in stream B (``oc_layer="split"``) is
    refused ``mc_splice_crosses_wrapper_boundary``, so the cross-stream shift rule is covered by the helper unit
    test (``test_wrapper_check_follows_an_emc_in_another_stream``) and not by a twin."""
    doc = frontier_twins._identity_h(far_show=True, oc_layer="split")()
    try:
        streams = helpers.page_streams(doc, 0)
        assert len(streams) == 2 and streams[1][1] == b"EMC"
        replay = replay_page_streams(streams)
        (wrapper,) = replay.wrappers_for(replay.shows[0])
        assert wrapper.stream_xref == streams[0][0] and wrapper.close_stream_xref == streams[1][0]
        prepared = TieredCommitEngine(doc, max_tier=1).prepare(
            doc[0],
            target_text=tb.CJK_TEXT,
            replacement_text=tb.REPLACEMENT_EQUAL_ADVANCE,
            **frontier_twins.located_arguments(doc, tb.CJK_TEXT),
        )
        assert isinstance(prepared, PlanRejection)
        assert str(prepared.reason) == "mc_splice_crosses_wrapper_boundary"
    finally:
        doc.close()


def test_twin_iii_rect_lies_inside_the_halo_over_the_tail_glyph(oracle_runs):
    """(iii): the 1 pt square is inside ``halo_mask`` (so neighbours must pass) and inside the first tail glyph's box."""
    (run,) = oracle_runs["iii"]
    prepared = run.prepared
    assert prepared is not None
    box = prepared.target_bbox_page
    height = run.after[0].rect.height
    rect = fitz.Rect(box[2] + 0.5, height - 703, box[2] + 1.5, height - 702)
    with helpers._measurement_copy(run.after) as copy:
        flat = helpers._flatten_trace(copy[0])
        after_trace = helpers._trace_for(copy[0], helpers._shows(run.after, 0)[0], tb.REPLACEMENT_EQUAL_ADVANCE)
    mask = helpers.halo_mask(box, after_trace["bbox"], run.frame)
    assert mask.contains(rect)
    first_tail_glyph = fitz.Rect(flat[len(tb.REPLACEMENT_EQUAL_ADVANCE)].bbox)
    assert first_tail_glyph.contains(rect)


# ----------------------------------------------------------------------------------------------
# S3b: the glyph-identity legs on the builder kinds (plan section 3; the s3b spec matrix)
# ----------------------------------------------------------------------------------------------
_LEVEL_A = "Level A 2024"
#: kind -> (leg, expected detail or None).  Index 6 is the A; 10 glyphs are non-space.
_MATRIX = {
    "winansi": ("glyph_name_agl", None),
    "post3_cmap31": ("cmap_31_reverse", None),
    "symbolic_post3": ("cmap_31_reverse", None),
    "symbolic_ascii": ("glyph_name_agl", None),
    "tounicode_lie": (
        "glyph_name_agl",
        "glyph_identity: glyph_name_agl: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
    "symbolic_post3_wrongglyph": (
        "cmap_31_reverse",
        "glyph_identity: cmap_31_reverse: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
    "symbolic_wrongname": (
        "glyph_name_agl",
        "glyph_identity: glyph_name_agl: leg_char_differs: 1 of 10 glyph(s), first index 6",
    ),
}


def _unedited_inputs(doc: fitz.Document, *, code_bytes: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """``(codes, gids)`` of the first show of an UNEDITED document (the show as its own before and after)."""
    show = helpers._shows(doc, 0)[0]
    edited = helpers.edited_show(show, show, code_bytes=code_bytes)
    inputs = helpers.glyph_identity_inputs(
        doc, 0, edited, frame=helpers.visual_frame(doc[0]), code_bytes=code_bytes
    )
    assert isinstance(inputs, tuple), inputs
    return inputs


def _identity(doc, font_xref, text, kind, *, code_bytes, measurements=None, codes=None, gids=None):
    own_codes, own_gids = _unedited_inputs(doc, code_bytes=code_bytes)
    return helpers.check_glyph_identity(
        doc,
        0,
        font_xref,
        text,
        kind,
        gid_after=own_gids if gids is None else gids,
        codes=own_codes if codes is None else codes,
        measurements=measurements,
    )


assert sorted(_MATRIX) == sorted(sfb.KINDS)  # every builder kind has a row


@pytest.mark.parametrize("kind", sfb.KINDS)
def test_glyph_identity_legs_on_the_builder_kinds(kind):
    leg, expected = _MATRIX[kind]
    fixture = sfb.build_embedded_simple_fixture(kind, _LEVEL_A)
    measurements: dict = {}
    detail = _identity(
        fixture.doc, fixture.font_xref, _LEVEL_A, "simple", code_bytes=1, measurements=measurements
    )
    assert detail == expected
    assert measurements["leg"] == leg
    assert measurements["glyphs_checked"] == 10
    assert measurements["outline_checked"] == 10  # an embedded TrueType program: every glyph has an outline


def _remove_the_unicode_cmap(fixture) -> None:
    program = fixture.doc.xref_stream(fixture.fontfile_xref)
    font = TTFont(BytesIO(program))
    font["cmap"].tables = [
        table for table in font["cmap"].tables if (table.platformID, table.platEncID) != (3, 1)
    ]
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(fixture.fontfile_xref, out.getvalue())


def test_glyph_identity_has_no_leg_for_a_nameless_program_without_a_unicode_cmap():
    """U6, and the fontTools trap: a post-format-3 program has no names, yet ``getGlyphOrder()`` hands out the AGL
    names of its (3,1) cmap, so an AGL leg reading them is the cmap leg in disguise; the leg is therefore chosen
    from the post format and not from the names, and without a (3,1) table nothing is left to read."""
    fixture = sfb.build_embedded_simple_fixture("symbolic_post3", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    trap = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    assert trap.getGlyphOrder()[sfb.glyph_id("A")] == "A" and trap["post"].formatType == 3.0  # the trap, pinned
    _remove_the_unicode_cmap(fixture)
    font = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    assert font["post"].formatType == 3.0
    assert "A" not in font.getGlyphOrder()  # synthesized names, not the builder's
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_has_no_leg_for_an_unembedded_non_base14_font():
    """U2: an unembedded font outside the base-14 table has no program and no table to read."""
    doc = ssf.open_case("a")
    try:
        codes, gids = _unedited_inputs(doc, code_bytes=1)
        doc.xref_set_key(4, "BaseFont", "/NoSuchFaceAnywhere")
        with pytest.raises(helpers.IndependentLegUnavailable):
            helpers.check_glyph_identity(doc, 0, 4, ssf.TARGET, "simple", gid_after=gids, codes=codes)
    finally:
        doc.close()


@pytest.mark.parametrize("key", ["FontFile", "FontFile3"])
def test_glyph_identity_defers_type1_and_cff_programs(key):
    """U3/U4: the Type1 and CFF recipes are written down for I1 and not implemented; raising keeps them from passing."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    descriptor = int(fixture.doc.xref_get_key(fixture.font_xref, "FontDescriptor")[1].split()[0])
    fixture.doc.xref_set_key(descriptor, key, f"{fixture.fontfile_xref} 0 R")
    if key == "FontFile3":  # PyMuPDF's get_fonts() needs the stream /Subtype of a FontFile3
        fixture.doc.xref_set_key(fixture.fontfile_xref, "Subtype", "/OpenType")
    fixture.doc.xref_set_key(descriptor, "FontFile2", "null")
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_defers_a_differences_encoding():
    """U7: ``/Differences`` is I8's (F31); the encoding cannot name the code, so the leg is unavailable."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    fixture.doc.xref_set_key(
        fixture.font_xref, "Encoding", "<</BaseEncoding/WinAnsiEncoding/Differences[65/B]>>"
    )
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_type0_leg_catches_a_forged_gid_or_code():
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    assert len(set(gids)) == 4
    measurements: dict = {}
    assert (
        _identity(fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, measurements=measurements)
        is None
    )
    assert measurements["leg"] == "cid_program_cmap"
    assert measurements["glyphs_checked"] == measurements["outline_checked"] == 4
    reversed_gids = _identity(
        fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, gids=tuple(reversed(gids))
    )
    assert reversed_gids == "glyph_identity: cid_program_cmap: leg_gid_differs: 4 of 4 glyph(s), first index 0"
    swapped = _identity(
        fixture.doc, fixture.font_xref, tb.CJK_TEXT, "type0", code_bytes=2, codes=tuple(reversed(codes))
    )
    assert swapped == (
        "glyph_identity: cid_program_cmap: leg_gid_differs: 4 of 4 glyph(s), first index 0; "
        "leg_char_differs: 4 of 4 glyph(s), first index 0; "
        "tounicode_disagrees: 4 of 4 glyph(s), first index 0"
    )


def test_glyph_identity_standard14_leg_catches_a_forged_code():
    doc = ssf.open_case("a")
    try:
        codes, gids = _unedited_inputs(doc, code_bytes=1)
        measurements: dict = {}
        assert _identity(doc, 4, ssf.TARGET, "simple", code_bytes=1, measurements=measurements) is None
        assert measurements["leg"] == "standard_14_table"
        assert measurements["glyphs_checked"] == 9 and measurements["outline_checked"] == 0
        forged = (*codes[:-1], ord("5"))  # the last glyph is still drawn as '4', but the code written is '5'
        detail = _identity(doc, 4, ssf.TARGET, "simple", code_bytes=1, codes=forged)
        assert detail == (
            "glyph_identity: standard_14_table: leg_gid_differs: 1 of 9 glyph(s), first index 9; "
            "leg_char_differs: 1 of 9 glyph(s), first index 9"
        )
    finally:
        doc.close()


def test_glyph_identity_reports_a_glyph_without_an_outline():
    """Written with the helper.  ``no_outline``: the code written reaches the empty space glyph, drawn and walked consistently, for an 'A'."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    space_gid = sfb.glyph_id(" ")
    forged_codes = (*codes[:6], 0x20, *codes[7:])
    forged_gids = (*gids[:6], space_gid, *gids[7:])
    detail = helpers.check_glyph_identity(
        fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=forged_gids, codes=forged_codes
    )
    assert detail == (
        "glyph_identity: glyph_name_agl: no_outline: 1 of 10 glyph(s), first index 6; "
        "leg_char_differs: 1 of 10 glyph(s), first index 6"
    )


def test_glyph_identity_has_no_leg_for_a_type0_font_without_a_capability():
    """Written with the helper.  U1: a Type0 font whose ToUnicode is gone has no Identity-H capability, so no ToUnicode leg."""
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    tb.strip_tounicode(fixture)
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )


def test_glyph_identity_has_no_leg_for_an_unreadable_program():
    """Written with the helper.  U5: an embedded stream that is not a font."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    fixture.doc.update_stream(fixture.fontfile_xref, b"this is not a font program")
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )


def test_glyph_identity_rejects_contradicting_inputs():
    """Written with the helper: inputs that contradict each other are a caller bug (``ValueError``)."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    base = (fixture.doc, 0, fixture.font_xref, _LEVEL_A)
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "cff", gid_after=gids, codes=codes)  # unknown font kind
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "simple", gid_after=gids[:-1], codes=codes)  # lengths differ
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(*base, "type0", gid_after=gids, codes=codes)  # not a Type0 font
    with pytest.raises(ValueError):
        helpers.check_glyph_identity(
            fixture.doc, 0, 9999, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )  # not a font of the page


def test_glyph_identity_type0_leg_is_the_program_cmap_not_the_tounicode():
    """Written with the helper.  Two ToUnicode claims swapped: ToUnicode alone would pass the page, the program's
    own (3,1) cmap does not.  The product commits the edit through the lie (twin ``v-type0``); here the unedited page
    is judged against the text it claims to say and against the text the program really draws."""
    fixture = tb.build_identity_h_fixture()
    mappings = tb.default_tounicode_mappings(fixture)
    mappings[0], mappings[1] = (mappings[0][0], mappings[1][1]), (mappings[1][0], mappings[0][1])
    tb.write_minimal_tounicode(fixture, mappings)
    lie_text = frontier_twins.TYPE0_LIE_TARGET  # what the page claims to say
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    # the claimed text agrees with ToUnicode and the walk, but not with the program's own cmap
    assert (
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, lie_text, "type0", gid_after=gids, codes=codes
        )
        == "glyph_identity: cid_program_cmap: leg_char_differs: 2 of 4 glyph(s), first index 0"
    )
    # the true text is what the program draws: the cmap leg passes and the ToUnicode cross-check disagrees
    assert (
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )
        == "glyph_identity: cid_program_cmap: tounicode_disagrees: 2 of 4 glyph(s), first index 0"
    )


def test_glyph_identity_type0_catches_a_permuted_cidtogid_map():
    """Refuter nit: every other synthetic Type0 fixture has an identity CIDToGIDMap.  Here code(你) draws the 好
    outline: the walk follows the map, the rendering agrees with it, ToUnicode still says 你, and only the
    program's cmap sees that the glyph is not the character."""
    fixture = tb.build_identity_h_fixture()
    first, second = tb.cid_for(tb.CJK_TEXT[0]), tb.cid_for(tb.CJK_TEXT[1])
    table = tb.identity_cidtogid_bytes(
        max(tb.cid_for(char) for char in tb.CJK_TEXT) + 1, {first: second, second: first}
    )
    tb.set_cidtogid_stream(fixture, table)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    assert gids[0] == second and gids[1] == first  # the rendering follows the map
    measurements: dict = {}
    detail = helpers.check_glyph_identity(
        fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes, measurements=measurements
    )
    assert detail == "glyph_identity: cid_program_cmap: leg_char_differs: 2 of 4 glyph(s), first index 0"
    assert measurements["leg"] == "cid_program_cmap"


def test_glyph_identity_has_no_leg_for_a_type0_program_without_a_unicode_cmap():
    """U8 (written with the helper): no (3,1) and no (0,x) table, so there is no independent Type0 leg and no fallback."""
    fixture = tb.build_identity_h_fixture()
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=2)
    font = TTFont(BytesIO(read_embedded_font_program(fixture.doc, fixture.font_xref)))
    macintosh = CmapSubtable.newSubtable(0)
    macintosh.platformID, macintosh.platEncID, macintosh.language, macintosh.cmap = 1, 0, 0, {}
    font["cmap"].tables = [macintosh]
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(tb.fontfile2_xref(fixture), out.getvalue())
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, tb.CJK_TEXT, "type0", gid_after=gids, codes=codes
        )


def _rename_glyph_a(fixture) -> None:
    """Rename the glyph ``A`` of the embedded post-2 program to ``g123`` (an AGL-less name), everywhere."""
    font = TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))
    order = ["g123" if name == "A" else name for name in font.getGlyphOrder()]
    font["glyf"].glyphs["g123"] = font["glyf"].glyphs.pop("A")
    font["hmtx"].metrics["g123"] = font["hmtx"].metrics.pop("A")
    for table in font["cmap"].tables:
        table.cmap = {code: ("g123" if name == "A" else name) for code, name in table.cmap.items()}
    font.setGlyphOrder(order)
    out = BytesIO()
    font.save(out)
    fixture.doc.update_stream(fixture.fontfile_xref, out.getvalue())


def test_glyph_identity_post_names_without_agl_text_are_unavailable_not_a_mismatch():
    """U7 on post names (written with the helper): a post-2 program whose glyph names the AGL cannot read has no
    independent leg; reporting ``leg_char_differs`` would claim a finding about the glyph that the oracle cannot make."""
    fixture = sfb.build_embedded_simple_fixture("winansi", _LEVEL_A)
    codes, gids = _unedited_inputs(fixture.doc, code_bytes=1)
    _rename_glyph_a(fixture)
    assert TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref))).getGlyphOrder()[sfb.glyph_id("A")] == "g123"
    with pytest.raises(helpers.IndependentLegUnavailable):
        helpers.check_glyph_identity(
            fixture.doc, 0, fixture.font_xref, _LEVEL_A, "simple", gid_after=gids, codes=codes
        )
