"""Frontier twins (slice I0b, stage S2): the simple-font builder and the observed HEAD outcomes.

CI lane, no marker: every fixture here is synthetic.  This file has two jobs.

1. Prove the FontBuilder programs of ``simple_font_fixture_builder`` carry the font facts their
   kind names (pure fontTools reads of the embedded program, never a rendering shortcut), so the
   later glyph-identity twins cannot be self-consistent fakes.
2. Record, as a pinned table, what ``TieredCommitEngine.prepare`` returns at HEAD for each kind and
   for the product paths of the future ORACLE twins ("observed, not assumed", design :203).  A
   pinned row is an observation of the code as it is, not a statement that the outcome is right: a
   COMMITTED ``tounicode_lie`` is slice I1's G1' red, left for I1.

Red-first record (stage S2).  Red before the builder existed (ImportError), then red again under
five deliberate builder mutations: ``test_builder_kinds_have_the_named_font_facts`` (all five),
``test_fitz_renders_a_and_b_of_every_kind_apart`` (A/B naming swapped),
``test_texttrace_gids_follow_the_cmap_mupdf_uses`` (swapped naming, dropped ToUnicode) and
``test_q12_mupdf_integerises_an_x_point_five_width_half_up`` (a half-even claim).  Recorded
observations, red by import only (they had no earlier state; the first full run corrected two
expectations taken from the design): ``test_simple_twins_prepare_as_observed_at_head`` and
``test_future_twin_product_paths_are_recorded_as_observed_at_head``.  Written together with the
builder, not red-first: the input-validation, outline-distinctness, space/overhang,
fractional-widths and registry tests.

Review fix-up round (same stage): red first (red evidence in the plan's running log) for the exact
fixed-point numbers (``None == 600.0625`` under ``%g``), the FontBBox covering the overhang, the
injective ``symbolic_wrongname`` lie (``'B' == 'A'`` under the many-to-one table), the two nameless
kinds (unknown-kind ValueError before the builder knew them) and the gap clip (``assert not True``
under a plain rectangle).  The (xii) clip rows, per-kind committed-gid pins and the float32 Q12 row
are observations pinned together with the code they describe.
"""
from __future__ import annotations

import re
from io import BytesIO

import fitz
import numpy as np
import pytest
from fontTools.agl import UV2AGL
from fontTools.ttLib import TTFont

from model.text_commit.dto import CommitStatus
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.plan import PlanRejection
from test_scripts import frontier_twins
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts import true_text_acceptance_helpers as helpers
from test_scripts import type0_fixture_builder as tb


def _program(fixture: sfb.SimpleFixture) -> TTFont:
    """The embedded TrueType program, read back out of the built document."""
    return TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))


def _agl(char: str) -> str:
    return UV2AGL[ord(char)]


def _subtable(font: TTFont, platform: int, encoding: int):
    return font["cmap"].getcmap(platform, encoding)


def _coords(font: TTFont, glyph_name: str) -> tuple:
    glyph = font["glyf"][glyph_name]
    coordinates = glyph.getCoordinates(font["glyf"])[0]
    return tuple((int(x), int(y)) for x, y in coordinates)


def _font_dict_key(fixture: sfb.SimpleFixture, key: str) -> tuple[str, str]:
    return fixture.doc.xref_get_key(fixture.font_xref, key)


def _flags(fixture: sfb.SimpleFixture) -> int:
    return int(fixture.doc.xref_get_key(fixture.font_xref, "FontDescriptor/Flags")[1])


def test_builder_kinds_have_the_named_font_facts():
    built = {kind: sfb.build_embedded_simple_fixture(kind, "AB") for kind in sfb.KINDS}
    assert set(built) == {
        "winansi",
        "symbolic_ascii",
        "symbolic_wrongname",
        "tounicode_lie",
        "post3_cmap31",
        "symbolic_post3",
        "symbolic_post3_wrongglyph",
    }
    programs = {kind: _program(fixture) for kind, fixture in built.items()}

    # winansi: nonsymbolic, /WinAnsiEncoding, (3,1) U+0041 -> glyph named A, post names present
    fx, font = built["winansi"], programs["winansi"]
    assert _flags(fx) & 32 and not _flags(fx) & 4
    assert _font_dict_key(fx, "Encoding") == ("name", "/WinAnsiEncoding")
    assert _subtable(font, 3, 1).cmap[0x41] == "A"
    assert _subtable(font, 3, 0) is None
    assert font["post"].formatType == 2.0

    # symbolic_ascii: symbolic, no /Encoding, only (3,0) F020-F07E, each code reaches the glyph
    # whose post name is the character's own AGL name
    fx, font = built["symbolic_ascii"], programs["symbolic_ascii"]
    assert _flags(fx) & 4 and not _flags(fx) & 32
    assert _font_dict_key(fx, "Encoding")[0] == "null"
    assert _subtable(font, 3, 1) is None
    symbol = _subtable(font, 3, 0).cmap
    assert sorted(symbol) == list(range(0xF020, 0xF07F))
    for code in range(0x20, 0x7F):
        assert symbol[0xF000 + code] == _agl(chr(code)), code

    # symbolic_wrongname: code 0x41 reaches the glyph NAMED B, while (3,1) claims U+0041 for it
    fx, font = built["symbolic_wrongname"], programs["symbolic_wrongname"]
    assert _flags(fx) & 4 and _font_dict_key(fx, "Encoding")[0] == "null"
    assert _subtable(font, 3, 0).cmap[0xF041] == "B"
    assert _subtable(font, 3, 1).cmap[0x41] == "B"  # the Unicode table claims A, the glyph is B
    assert _coords(font, "A") != _coords(font, "B")  # a glyph named A still exists
    assert _subtable(font, 3, 0).cmap[0xF042] == "B"  # B stays B through the symbol table
    # the (3,1) lie is INJECTIVE (U+0041 -> B, U+0042 -> A): a cmap reverse leg must fail on
    # content, not on a many-to-one table that has no unique reverse
    unicode_map = _subtable(font, 3, 1).cmap
    assert unicode_map[0x42] == "A"
    assert len(set(unicode_map.values())) == len(unicode_map)

    # tounicode_lie: ToUnicode says 0x41 -> U+0041 while the outline, post name and (3,1) say B
    fx, font = built["tounicode_lie"], programs["tounicode_lie"]
    assert _flags(fx) & 4 and _font_dict_key(fx, "Encoding")[0] == "null"
    assert _subtable(font, 3, 0).cmap[0xF041] == "B"
    assert _subtable(font, 3, 1).cmap[0x42] == "B" and _subtable(font, 3, 1).cmap[0x41] == "A"
    assert font["post"].formatType == 2.0
    kind, value = _font_dict_key(fx, "ToUnicode")
    assert kind == "xref"
    cmap_text = fx.doc.xref_stream(int(value.split()[0])).decode("latin-1")
    assert "<41> <0041>" in cmap_text

    # symbolic_post3: nameless (post 3), symbolic, no /Encoding, honest (3,0) AND (3,1), no ToUnicode
    fx, font = built["symbolic_post3"], programs["symbolic_post3"]
    assert font["post"].formatType == 3.0
    assert _flags(fx) & 4 and _font_dict_key(fx, "Encoding")[0] == "null"
    assert _font_dict_key(fx, "ToUnicode")[0] == "null"
    reference = programs["winansi"]
    for code in range(0x20, 0x7F):
        symbol_glyph = _subtable(font, 3, 0).cmap[0xF000 + code]
        unicode_glyph = _subtable(font, 3, 1).cmap[code]
        assert symbol_glyph == unicode_glyph, code
        assert _coords(font, symbol_glyph) == _coords(reference, _agl(chr(code))), code

    # symbolic_post3_wrongglyph: as symbolic_post3 except that code 0x41 draws the B outline through
    # (3,0), while the (3,1) table stays honest and nothing (no name, no ToUnicode) says otherwise
    fx, font = built["symbolic_post3_wrongglyph"], programs["symbolic_post3_wrongglyph"]
    assert font["post"].formatType == 3.0
    assert _flags(fx) & 4 and _font_dict_key(fx, "Encoding")[0] == "null"
    assert _font_dict_key(fx, "ToUnicode")[0] == "null"
    drawn = _subtable(font, 3, 0).cmap[0xF041]
    assert _coords(font, drawn) == _coords(reference, "B")
    assert _coords(font, _subtable(font, 3, 1).cmap[0x41]) == _coords(reference, "A")

    # post3_cmap31: post format 3 (no glyph names) with a correct (3,1) table
    fx, font = built["post3_cmap31"], programs["post3_cmap31"]
    assert font["post"].formatType == 3.0
    reference = programs["winansi"]
    for char in "AB":
        glyph = _subtable(font, 3, 1).cmap[ord(char)]
        assert _coords(font, glyph) == _coords(reference, _agl(char)), char
    assert _coords(font, _subtable(font, 3, 1).cmap[0x41]) != _coords(
        font, _subtable(font, 3, 1).cmap[0x42]
    )


def test_builder_validates_its_inputs():
    with pytest.raises(ValueError):
        sfb.build_embedded_simple_fixture("no_such_kind", "A")
    with pytest.raises(ValueError):
        sfb.build_embedded_simple_fixture("winansi", "café")  # no glyph for it
    with pytest.raises(ValueError):
        sfb.build_embedded_simple_fixture("winansi", "A", widths={"é": 500})


def test_glyph_outlines_are_pairwise_distinct():
    shapes = [sfb.glyph_shape(chr(code)) for code in range(0x21, 0x7F)]
    assert len(set(shapes)) == len(shapes)
    assert sfb.glyph_shape(" ") == (0, 0, 0)


def test_the_space_glyph_is_real_and_overhang_widens_only_the_f_outline():
    plain = _program(sfb.build_embedded_simple_fixture("winansi", "A"))
    over = _program(sfb.build_embedded_simple_fixture("winansi", "A", overhang=300))
    for font in (plain, over):
        assert font["hmtx"]["space"][0] == sfb.GLYPH_ADVANCE  # a real advance...
        assert font["glyf"]["space"].numberOfContours == 0  # ...and no outline
        for char in "Af ":
            assert font["hmtx"][sfb.glyph_name(char)][0] == sfb.GLYPH_ADVANCE
    assert plain["glyf"]["f"].xMax <= sfb.GLYPH_ADVANCE
    assert over["glyf"]["f"].xMax == plain["glyf"]["f"].xMax + 300
    assert over["glyf"]["f"].xMax > over["hmtx"]["f"][0]  # xMax beyond the advance
    for char in "AB":  # no other glyph is touched
        assert _coords(over, sfb.glyph_name(char)) == _coords(plain, sfb.glyph_name(char))


def test_fractional_widths_reach_the_widths_array_and_the_product_capability():
    fixture = sfb.build_embedded_simple_fixture("winansi", "AB", widths={"A": 600.5, "B": 601.25})
    assert _font_dict_key(fixture, "FirstChar")[1] == "32"
    cap = DocumentFontRegistry(fixture.doc).capability(fixture.page, fixture.resource_name)
    assert cap is not None and cap.advance_source == "widths"
    assert cap.width_of_code(ord("A")) == 600.5 and cap.width_of_code(ord("B")) == 601.25
    assert cap.width_of_code(ord("C")) == float(sfb.GLYPH_ADVANCE)


def test_numbers_are_written_exactly_and_non_finite_ones_are_refused():
    """``%g`` keeps six significant digits (600.0625 -> 600.062) and may switch to exponent form."""
    fixture = sfb.build_embedded_simple_fixture("winansi", "AB", widths={"A": 600.0625, "B": 0.00001})
    cap = DocumentFontRegistry(fixture.doc).capability(fixture.page, fixture.resource_name)
    assert cap is not None
    assert cap.width_of_code(ord("A")) == 600.0625  # seven significant digits survive
    declared = fixture.doc.xref_get_key(fixture.font_xref, "Widths")[1]
    exponent = re.compile(r"\d[eE][-+]?\d")
    assert not exponent.search(declared)  # fixed point, never 1e-05
    tiny = sfb.build_embedded_simple_fixture("winansi", "A", fontsize=0.00001, origin=(0.5, 1e-7))
    assert not exponent.search(tiny.content_bytes().decode("ascii"))
    assert b"0.00001 Tf 0.5 0.0000001 Td" in tiny.content_bytes()
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            sfb.build_embedded_simple_fixture("winansi", "A", widths={"A": bad})


def test_the_font_bbox_covers_the_overhanging_outline():
    from fontTools.ttLib import TTFont as _TTFont

    for overhang in (None, 300):
        fixture = sfb.build_embedded_simple_fixture("winansi", "A", overhang=overhang)
        x_max = _TTFont(BytesIO(fixture.doc.xref_stream(fixture.fontfile_xref)))["head"].xMax
        bbox = fixture.doc.xref_get_key(fixture.font_xref, "FontDescriptor/FontBBox")[1]
        assert float(bbox.strip("[]").split()[2]) >= x_max, (overhang, bbox, x_max)


def test_texttrace_gids_follow_the_cmap_mupdf_uses():
    """Pins the MuPDF texttrace gid of each builder kind (the glyph-identity helper's measured side)."""
    for kind in sfb.KINDS:
        fixture = sfb.build_embedded_simple_fixture(kind, "AB")
        with helpers._measurement_copy(fixture.doc) as measured:
            chars = measured[0].get_texttrace()[0]["chars"]
        lies = kind in _LYING_KINDS
        want = [sfb.glyph_id("B" if lies else "A"), sfb.glyph_id("B")]
        assert [char[1] for char in chars] == want, (kind, [char[1] for char in chars])
        # the texttrace character is MuPDF's text for the glyph: the ToUnicode CMap wins when there
        # is one (tounicode_lie says A over the B glyph), else the glyph NAME (wrongname says B),
        # else the CODE BYTE of a nameless program (symbolic_post3_wrongglyph reads A over the B
        # outline); never the (3,1) cmap
        text = {"symbolic_wrongname": "BB"}.get(kind, "AB")
        assert "".join(chr(char[0]) for char in chars) == text, kind


#: kinds whose code 0x41 draws the B outline
_LYING_KINDS = ("symbolic_wrongname", "tounicode_lie", "symbolic_post3_wrongglyph")


def _render(fixture: sfb.SimpleFixture) -> np.ndarray:
    return helpers._pixmap_array(fixture.page)


def _differing_pixels(left: np.ndarray, right: np.ndarray) -> int:
    return int(np.any(left != right, axis=2).sum())


@pytest.mark.parametrize("kind", sfb.KINDS)
def test_fitz_renders_a_and_b_of_every_kind_apart(kind):
    """A wrong glyph must show in pixels, or a later glyph-identity twin could be vacuous.

    The three lying kinds draw code 0x41 as B by construction: there A renders exactly like B (and
    still unlike C), which is the lie a name/cmap/ToUnicode read has to catch."""
    renders = {char: _render(sfb.build_embedded_simple_fixture(kind, char)) for char in "ABC"}
    assert _differing_pixels(renders["A"], renders["C"]) > 0, kind
    assert _differing_pixels(renders["B"], renders["C"]) > 0, kind
    if kind in _LYING_KINDS:
        assert _differing_pixels(renders["A"], renders["B"]) == 0, kind
    else:
        assert _differing_pixels(renders["A"], renders["B"]) > 0, kind


# ----------------------------------------------------------------------------------------------
# Recorded observations: what the product does at HEAD ("observed, not assumed", design :203)
# ----------------------------------------------------------------------------------------------
def _located_arguments(doc: fitz.Document, target: str) -> dict:
    """``expected_origin`` / ``target_bbox`` exactly as the acceptance harness hands them to ``prepare``:
    the texttrace run of ``target`` turned through ``frame.quarter_turn`` (``helpers._prepare``)."""
    page = doc[0]
    show = helpers._shows(doc, 0)[0]
    with helpers._measurement_copy(doc) as measured:
        trace = helpers._trace_for(measured[0], show, target)
    frame = helpers.visual_frame(page)
    return {
        "expected_origin": tuple(fitz.Point(trace["chars"][0][2]) * frame.quarter_turn),
        "target_bbox": tuple(fitz.Rect(trace["bbox"]) * frame.quarter_turn),
    }


def _outcome(build, target: str, replacement: str, *, located: bool, max_tier: int = 1) -> tuple:
    """``("COMMITTED", tier, decision_chain)`` or ``("REJECTED", reason, detail)``: prepare, then commit.

    ``located=False`` calls ``prepare(expected_origin=None, target_bbox=None)`` (the planner's own
    1.35 em quad); ``located=True`` passes the acceptance-shaped origin and box.  The tables below hold
    for BOTH call shapes (:func:`_both_ways`)."""
    doc = build()
    try:
        engine = TieredCommitEngine(doc, max_tier=max_tier)
        arguments = _located_arguments(doc, target) if located else {"expected_origin": None}
        result = engine.prepare(
            doc[0], target_text=target, replacement_text=replacement, **arguments
        )
        if isinstance(result, PlanRejection):
            return ("REJECTED", str(result.reason), result.detail)
        outcome = engine.commit(result)
        assert outcome.status is CommitStatus.COMMITTED, (outcome.status, outcome.degraded_reason)
        return ("COMMITTED", result.tier.value, outcome.decision_chain)
    finally:
        doc.close()


def _both_ways(build, target: str, replacement: str) -> tuple:
    """The outcome, asserted identical for the bare and the acceptance-shaped ``prepare`` call."""
    bare = _outcome(build, target, replacement, located=False)
    shaped = _outcome(build, target, replacement, located=True)
    assert bare == shaped, (bare, shaped)
    return bare


#: HEAD 413557f; the replacement writes the byte 0x41 ("Level A 2024").  winansi / post3 commit as
#: Tier 0 (guards).  symbolic_ascii is REFUSED: its only cmap is (3,0), so ``face.has_glyph`` finds
#: nothing and the product's own coverage rule fails closed (design :203 expected COMMITTED).
#: symbolic_wrongname is REFUSED, but only by luck of extraction: MuPDF reads the text of a
#: glyph from its NAME, so the committed byte extracts as "B" and the scratch verification says
#: "replacement text not extractable at the target"; no glyph-identity gate is involved.
#: tounicode_lie is COMMITTED: the ToUnicode CMap makes the B outline extract as "A", so nothing
#: in the planner or the verifier sees the lie.  That is slice I1's G1' red, owned by I1, and NOT
#: something S2 fixes.
_KIND_OUTCOMES = {
    "winansi": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_ascii": (
        "REJECTED",
        "encoding_failed",
        "reverse encoder does not reproduce the source string bytes",
    ),
    "symbolic_wrongname": (
        "REJECTED",
        "verification_failed",
        "replacement text not extractable at the target",
    ),
    "tounicode_lie": ("COMMITTED", 0, ("tier0:committed",)),
    "post3_cmap31": ("COMMITTED", 0, ("tier0:committed",)),
    # the nameless F30B shapes: both COMMIT; symbolic_post3_wrongglyph commits a WRONG glyph (gid 35)
    "symbolic_post3": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_post3_wrongglyph": ("COMMITTED", 0, ("tier0:committed",)),
}
#: the texttrace glyph id at the replaced position (the "B" -> "A" slot) of a committed edit: 34 is
#: the A outline, 35 the B outline.  tounicode_lie and symbolic_post3_wrongglyph COMMIT a wrong glyph.
_KIND_COMMITTED_GID = {
    "winansi": 34,
    "post3_cmap31": 34,
    "symbolic_post3": 34,
    "tounicode_lie": 35,
    "symbolic_post3_wrongglyph": 35,
}
#: brief v5: F30W = embedded with a /WinAnsi|MacRoman|Standard /Encoding; F30B = embedded with NO
#: /Encoding (built-in encoding or symbolic cmap), the class of the H-F30b false-safe hypothesis.
_KIND_CLASS = {
    "winansi": "F30W",
    "post3_cmap31": "F30W",
    "symbolic_ascii": "F30B",
    "symbolic_wrongname": "F30B",
    "tounicode_lie": "F30B",
    "symbolic_post3": "F30B",
    "symbolic_post3_wrongglyph": "F30B",
}


def _label(outcome: tuple) -> str:
    return "COMMITTED" if outcome[0] == "COMMITTED" else str(outcome[1])


def _committed_gid(spec, index: int) -> int:
    """The texttrace glyph id at character ``index`` of the committed document (measurement copy)."""
    doc = spec.build()
    try:
        engine = TieredCommitEngine(doc, max_tier=1)
        prepared = engine.prepare(
            doc[0], target_text=spec.target, replacement_text=spec.replacement, expected_origin=None
        )
        assert not isinstance(prepared, PlanRejection), spec.twin_id
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        with helpers._measurement_copy(doc) as measured:
            return measured[0].get_texttrace()[0]["chars"][index][1]
    finally:
        doc.close()


def test_simple_twins_prepare_as_observed_at_head():
    """Recorded observation (red by import only: it had no earlier state).  The first full run
    corrected two expectations taken from the design, see the table's comment."""
    assert set(_KIND_OUTCOMES) == set(sfb.KINDS)
    for spec in frontier_twins.all_twins():
        kind = spec.twin_id.removeprefix("simple_")
        assert spec.class_id == _KIND_CLASS[kind], spec.twin_id
        observed = _both_ways(spec.build, spec.target, spec.replacement)
        assert observed == _KIND_OUTCOMES[kind], (spec.twin_id, observed)
        assert _label(observed) == spec.expected, spec.twin_id
        if kind in _KIND_COMMITTED_GID:  # "commits a wrong glyph" is asserted, not inferred
            assert _committed_gid(spec, spec.target.index("B")) == _KIND_COMMITTED_GID[kind], kind
        else:
            assert observed[0] == "REJECTED", kind
        # a negative twin is owned by the slice that gives it a glyph-identity reason, whether HEAD
        # commits it (tounicode_lie) or refuses it by accident of extraction (wrongname)
        if spec.polarity == "negative":
            assert spec.owned_until_slice == "I1", spec.twin_id


def test_the_twin_registry_covers_every_builder_kind_once():
    specs = frontier_twins.all_twins()
    assert sorted(spec.twin_id for spec in specs) == sorted(f"simple_{kind}" for kind in sfb.KINDS)
    assert {spec.class_id for spec in specs} == {"F30W", "F30B"}
    for class_id in ("F30W", "F30B"):
        assert all(spec.class_id == class_id for spec in frontier_twins.twins_for(class_id))
    assert frontier_twins.twin("simple_tounicode_lie").polarity == "negative"
    assert frontier_twins.twins_for("NO_SUCH_CLASS") == ()
    with pytest.raises(KeyError):
        frontier_twins.twin("no_such_twin")
    assert frontier_twins.ORACLE_TWINS == ()


def _clipped(fixture: sfb.SimpleFixture, clip_path: str) -> sfb.SimpleFixture:
    """``clip_path`` (path operators ending in ``W n``) prepended before the show."""
    fixture.doc.update_stream(
        fixture.content_xref, clip_path.encode("ascii") + b" " + fixture.content_bytes()
    )
    return fixture


def _right_of(edge_pt: float) -> str:
    """A clip that keeps only the page area left of ``edge_pt``."""
    return f"0 0 {edge_pt:g} 842 re W n"


#: a two-rectangle union clip: its bounding box spans the page, but the 105..107.2 pt gap is outside
#: the path, and the tenth glyph's ink (105.16..106.99 pt at 6 pt) lies in the gap
_GAP_CLIP = "0 0 105 842 re 107.2 0 487.8 842 re W n"


def _identity_h_growth(*, frame_stroke: bool) -> tuple:
    def build() -> fitz.Document:
        fixture = tb.build_identity_h_fixture()
        if frame_stroke:  # a hairline page frame, far from the 72..120 pt growth strip
            stroke = b" q 0.5 w 20 20 555 802 re S Q"
            fixture.doc.update_stream(fixture.content_xref, fixture.content_bytes() + stroke)
        return fixture.doc

    return _both_ways(build, tb.CJK_TEXT, tb.REPLACEMENT_LONGER)


def _simple_growth(
    replacement: str,
    *,
    text: str = "Figure 1",
    fontsize: float = 12.0,
    overhang: int | None = None,
    clip_path: str | None = None,
) -> tuple:
    def build() -> fitz.Document:
        fixture = sfb.build_embedded_simple_fixture(
            "winansi", text, fontsize=fontsize, overhang=overhang
        )
        if clip_path is not None:
            _clipped(fixture, clip_path)
        return fixture.doc

    return _both_ways(build, text, replacement)


def _outcome_of_kind(kind: str) -> tuple:
    spec = frontier_twins.twin(f"simple_{kind}")
    return _both_ways(spec.build, spec.target, spec.replacement)


_GROWTH = ("COMMITTED", 1, ("tier0:rejected:advance_mismatch", "tier1:committed"))
_NOT_EXTRACTABLE = ("REJECTED", "verification_failed", "replacement text not extractable at the target")


def test_future_twin_product_paths_are_recorded_as_observed_at_head():
    """What ``prepare``/``commit`` do today on the product paths of the S3a/S3b twins.

    Every row is pinned for both call shapes (bare ``expected_origin=None`` and the acceptance
    harness's located origin and box; they agree).  Nothing here asserts the OUTCOME is right; each
    row becomes an ``OracleTwinSpec.product_expected`` (or a reason to rebuild the twin) in the stage
    that implements the twin.  At 6 pt "Figure 1" is eight 3.6 pt glyphs from x = 72 (right edge
    100.8 pt), the grown text ten.
    """
    observed = {
        # (v) the tounicode_lie product path is the kind row above: COMMITTED, tier 0
        "v": _outcome_of_kind("tounicode_lie"),
        # (vii) Tier 1 growth on identity_h; the far page-frame stroke changes nothing
        "vii_no_stroke": _identity_h_growth(frame_stroke=False),
        "vii_frame_stroke": _identity_h_growth(frame_stroke=True),
        # (ix) the overhanging f, with and without the real space glyph after it
        "ix_f_then_space": _simple_growth("Figure f ", text="Figure", overhang=300),
        "ix_f_last": _simple_growth("Figure f", text="Figure", overhang=300),
        # (xi) Tier 1 growth at Tf 6 (and at Tf 12 for contrast)
        "xi_tf6": _simple_growth("Figure 123", fontsize=6.0),
        "xi_tf12": _simple_growth("Figure 123", fontsize=12.0),
        # (xii) a clip path before the show, 6 pt, "Figure 1" -> "Figure 123": the tenth glyph's ink
        # spans 105.162..106.986 pt, the ninth's 101.52..103.32.  A plain rectangle that leaves the
        # LAST glyph's ink outside the path (edge 105) or the last two (edge 101.5) is REFUSED:
        # MuPDF drops a glyph from extraction only when its ink lies outside the clip path's
        # bounding box.  Edge 106 clips half of the last glyph and edge 107 clips nothing: both commit.
        "xii_last_glyph_ink_clipped": _simple_growth("Figure 123", fontsize=6.0, clip_path=_right_of(105.0)),
        "xii_two_glyphs_ink_clipped": _simple_growth("Figure 123", fontsize=6.0, clip_path=_right_of(101.5)),
        "xii_last_glyph_partly_clipped": _simple_growth("Figure 123", fontsize=6.0, clip_path=_right_of(106.0)),
        "xii_clip_edge_beyond_the_ink": _simple_growth("Figure 123", fontsize=6.0, clip_path=_right_of(107.0)),
        # the (xii) shape: a gap clip whose bounding box contains the last glyph but whose area
        # misses its ink commits, and leaves that glyph drawing nothing (asserted below)
        "xii_gap_clip": _simple_growth("Figure 123", fontsize=6.0, clip_path=_GAP_CLIP),
    }
    assert observed == {
        "v": ("COMMITTED", 0, ("tier0:committed",)),
        "vii_no_stroke": _GROWTH,
        "vii_frame_stroke": _GROWTH,
        "ix_f_then_space": _GROWTH,
        "ix_f_last": _GROWTH,
        "xi_tf6": _GROWTH,
        "xi_tf12": _GROWTH,
        "xii_last_glyph_ink_clipped": _NOT_EXTRACTABLE,
        "xii_two_glyphs_ink_clipped": _NOT_EXTRACTABLE,
        "xii_last_glyph_partly_clipped": _GROWTH,
        "xii_clip_edge_beyond_the_ink": _GROWTH,
        "xii_gap_clip": _GROWTH,
    }


def _last_glyph_ink_pixels(clip_path: str | None) -> int:
    """Non-white pixels (2x render of a measurement copy) in the committed tenth glyph's texttrace
    box of "Figure 123" at 6 pt, bare ``prepare``."""
    fixture = sfb.build_embedded_simple_fixture("winansi", "Figure 1", fontsize=6.0)
    if clip_path is not None:
        _clipped(fixture, clip_path)
    doc = fixture.doc
    try:
        engine = TieredCommitEngine(doc, max_tier=1)
        prepared = engine.prepare(
            doc[0], target_text="Figure 1", replacement_text="Figure 123", expected_origin=None
        )
        assert not isinstance(prepared, PlanRejection)
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        with helpers._measurement_copy(doc) as measured:
            page = measured[0]
            box = fitz.Rect(page.get_texttrace()[0]["chars"][9][3]) * helpers.visual_frame(page).quarter_turn
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=box, alpha=False)
            return int((np.frombuffer(pixmap.samples, dtype=np.uint8) < 255).sum())
    finally:
        doc.close()


def test_the_gap_clip_commits_and_leaves_the_last_growth_glyph_blank():
    """The (xii) blind spot: the product commits and its extraction check passes, yet the new last
    glyph draws nothing.  Measured for one two-rectangle union clip, not for every clip shape."""
    unclipped = _last_glyph_ink_pixels(None)
    assert unclipped > 0
    assert _last_glyph_ink_pixels(_right_of(107.0)) == unclipped  # an edge past the ink changes nothing
    partial = _last_glyph_ink_pixels(_right_of(106.0))
    assert 0 < partial < unclipped  # half the glyph survives
    assert _last_glyph_ink_pixels(_GAP_CLIP) == 0  # the gap clip: committed, blank


# ----------------------------------------------------------------------------------------------
# Q12: how MuPDF integerises a fractional /Widths entry (S4's residual formula depends on it)
# ----------------------------------------------------------------------------------------------
_Q12_WIDTHS = {"a": 600.5, "b": 601.5, "c": 602.5, "d": 599.5, "e": 600.4, "f": 600.6, "g": 600.0, "i": 600.49999}
#: half UP (away from zero for positive widths): .5 always rounds to the next unit.  Python's
#: ``round`` is half-even (600.5 -> 600, 602.5 -> 602) and truncation would give 600/601/602/599.
#: MuPDF parses the real as float32 first: 600.49999 is 600.5 in float32, so it rounds UP to 601
#: (floor(float32(w) + 0.5)), where a float64 floor(w + 0.5) would give 600.
_Q12_INTEGERISED = {"a": 601, "b": 602, "c": 603, "d": 600, "e": 600, "f": 601, "g": 600, "i": 601}


def test_q12_mupdf_integerises_an_x_point_five_width_half_up():
    text = "abcdefgih"  # the trailing glyph makes the last advance of interest measurable
    fixture = sfb.build_embedded_simple_fixture(
        "winansi", text, fontsize=100.0, origin=(10, 700), widths=_Q12_WIDTHS
    )
    declared = fixture.doc.xref_get_key(fixture.font_xref, "Widths")[1]
    assert "600.5" in declared and "602.5" in declared and "599.5" in declared  # the PDF is fractional
    with helpers._measurement_copy(fixture.doc) as measured:
        chars = measured[0].get_texttrace()[0]["chars"]
    assert "".join(chr(char[0]) for char in chars) == text
    units = {}
    for index, char in enumerate(text[:-1]):
        advance_pt = chars[index + 1][2][0] - chars[index][2][0]
        units[char] = advance_pt / 100.0 * 1000.0  # fontsize 100: one width unit is 0.1 pt
    for char, expected in _Q12_INTEGERISED.items():
        assert units[char] == pytest.approx(expected, abs=0.01), (char, units[char])
    # and it is NOT what Python's round (half-even) or truncation would give
    assert [round(_Q12_WIDTHS[char]) for char in "abcd"] == [600, 602, 602, 600]
    assert [int(_Q12_WIDTHS[char]) for char in "abcd"] == [600, 601, 602, 599]
    assert [_Q12_INTEGERISED[char] for char in "abcd"] == [601, 602, 603, 600]
