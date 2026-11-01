"""Slice I1 (G1'): ``model/text_commit/simple_font_programs.py`` against the builder kinds and the helper legs.

The product reads an embedded simple font's PROGRAM with its own sfnt / Type1 reader (no fontTools in
``model/``).  Here fontTools is the reference: the parity tests pin that the product's facts equal fontTools'
and that the product is never LESS strict than the independent helper legs of the acceptance oracle
(``true_text_acceptance_helpers._glyph_leg``).  Pure lane except the one ``needs_fixtures`` test that reads the
four real programs behind the owner's rows.
"""
from __future__ import annotations

import dataclasses
import statistics
import struct
import time
from io import BytesIO

import fitz
import pytest
from fontTools.agl import UV2AGL
from fontTools.encodings.StandardEncoding import StandardEncoding
from fontTools.fontBuilder import FontBuilder
from fontTools.misc import eexec, psLib
from fontTools.misc.psCharStrings import T1CharString
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.ttLib.tables._p_o_s_t import standardGlyphOrder

from model.text_commit import cid_fonts
from model.text_commit import simple_font_programs as sfp
from model.text_commit.fonts import DocumentFontRegistry, compute_simple_font_evidence_digest
from model.text_commit.simple_font_programs import builtin_glyph_proof
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts import true_text_acceptance_helpers as helpers
from test_scripts.stream_storage_fixtures import _assemble_pdf, _stream_obj
from test_scripts.test_true_text_i1_real_programs import _open_public, _unedited_show_inputs

_PRINTABLE_CODES = range(0x20, 0x7F)
_TRUETYPE_KINDS = tuple(kind for kind in sfb.KINDS if kind not in sfb.TYPE1_KINDS)
#: kinds fontTools' psLib cannot parse (review finding F2): the helper has NO leg for them (U5) and the reference
#: comparisons that go through ``suckfont`` do not apply; the product reads them and refuses the lying code
_PSLIB_UNREADABLE = ("type1_decoy_vector",)


def _program(fixture: sfb.SimpleFixture) -> bytes:
    program = fixture.doc.xref_stream(fixture.fontfile_xref)
    assert program is not None
    return program


def _proof_of(kind: str):
    fixture = sfb.build_embedded_simple_fixture(kind, "AB")
    return fixture, builtin_glyph_proof(_program(fixture), "FontFile" if kind in sfb.TYPE1_KINDS else "FontFile2")


def _helper_passes(fixture: sfb.SimpleFixture) -> dict[int, bool]:
    """Per printable code: does the acceptance helper's walk + claim (+ outline) vouch for the character itself?

    ``check_glyph_identity`` skips whitespace outright; here a space is held to the walk and the claim (no outline), the
    same bar the product's ``proves`` sets for it.  An ``IndependentLegUnavailable`` (a name the claim cannot read, U7)
    is no vouching."""
    capability = DocumentFontRegistry(fixture.doc).capability(fixture.page, fixture.resource_name)
    assert capability is not None
    if fixture.kind in _PSLIB_UNREADABLE:  # no leg can be built: nothing is vouched for
        with pytest.raises(helpers.IndependentLegUnavailable) as raised:
            helpers._glyph_leg(fixture.doc, fixture.font_xref, capability, "simple")
        assert str(raised.value) == helpers._U5
        return {code: False for code in _PRINTABLE_CODES}
    _leg, view, walk, claim, uses_outline, _agrees = helpers._glyph_leg(
        fixture.doc, fixture.font_xref, capability, "simple"
    )
    passes: dict[int, bool] = {}
    for code in _PRINTABLE_CODES:
        char = chr(code)
        try:
            walked = walk(code)
            passes[code] = bool(
                walked
                and claim(code, walked, char)
                and (char.isspace() or not uses_outline or view is None or view.has_outline(walked))
            )
        except helpers.IndependentLegUnavailable:
            passes[code] = False
    return passes


# ----------------------------------------------------------------------------------------------
# (iv) the literals
# ----------------------------------------------------------------------------------------------
def test_the_agl_ascii_literal_equals_fonttools():
    assert sfp._AGL_ASCII == {code: UV2AGL[code] for code in range(0x20, 0x7F)}
    assert len(sfp._AGL_ASCII) == 95


def test_the_standard_encoding_literal_equals_fonttools_over_printable_ascii():
    assert sfp._STANDARD_ASCII == {code: StandardEncoding[code] for code in range(0x20, 0x7F)}
    assert sfp._STANDARD_ASCII[0x27] == "quoteright" and sfp._STANDARD_ASCII[0x60] == "quoteleft"


def test_the_macintosh_glyph_order_literal_equals_fonttools():
    assert sfp._MAC_GLYPH_NAMES == tuple(standardGlyphOrder)
    assert len(sfp._MAC_GLYPH_NAMES) == 258


def test_the_program_size_cap_equals_the_type0_readers():
    assert sfp._MAX_FONT_PROGRAM_BYTES == cid_fonts._MAX_FONT_PROGRAM_BYTES


# ----------------------------------------------------------------------------------------------
# (iii) the product reads the same names / CharStrings order as fontTools
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", [kind for kind in _TRUETYPE_KINDS if kind not in sfb.NAMELESS_KINDS])
def test_the_truetype_glyph_names_equal_fonttools_glyph_order(kind):
    fixture, proof = _proof_of(kind)
    impl = proof._impl
    assert proof.program_kind == "truetype" and impl is not None
    font = TTFont(BytesIO(_program(fixture)))
    assert [impl.name_of(gid) for gid in range(proof.num_glyphs)] == font.getGlyphOrder(), kind
    assert proof.num_glyphs == len(font.getGlyphOrder())


@pytest.mark.parametrize("kind", [kind for kind in sfb.TYPE1_KINDS if kind not in _PSLIB_UNREADABLE])
def test_the_type1_charstrings_order_equals_suckfont(kind):
    fixture, proof = _proof_of(kind)
    assert proof.program_kind == "type1"
    font = psLib.suckfont(_program(fixture), "ascii")
    assert list(proof._impl._ranges) == list(font["CharStrings"]), kind
    assert proof.num_glyphs == len(font["CharStrings"])
    for code in range(256):  # the encoding vector: every named code equals fontTools' vector
        want = font["Encoding"][code]
        assert proof._impl.code_name(code) == (want if kind != "type1_standard" or 0x20 <= code <= 0x7E else ".notdef"), (
            kind,
            code,
        )


@pytest.mark.parametrize("kind", _TRUETYPE_KINDS)
def test_the_truetype_outline_test_equals_number_of_contours(kind):
    fixture, proof = _proof_of(kind)
    font = TTFont(BytesIO(_program(fixture)))
    order = font.getGlyphOrder()
    for gid in range(proof.num_glyphs):
        assert proof._impl.outline(gid) == (font["glyf"][order[gid]].numberOfContours != 0), (kind, gid)


def _mapped(kind: str, mapping: dict[int, str], fmt: int, platform: int = 1, encoding: int = 0) -> bytes:
    """A small honest program whose ONE cmap subtable has format ``fmt`` and maps ``mapping``."""
    return _mapped_tables([(platform, encoding, fmt, mapping)])


def _mapped_tables(subtables: list[tuple[int, int, int, dict[int, str]]]) -> bytes:
    """A small program (the printable glyphs, post 2 names) whose cmap holds ``(platform, encoding, format, mapping)``
    subtables.  fontTools writes them sorted by (platform, encoding)."""
    names = [".notdef", *(sfb.glyph_name(char) for char in sfb._PRINTABLE)]
    builder = FontBuilder(sfb.UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(names)
    glyphs = {".notdef": sfb._outline(" ")}
    metrics = {".notdef": (sfb.GLYPH_ADVANCE, 0)}
    for char in sfb._PRINTABLE:
        glyphs[sfb.glyph_name(char)] = sfb._outline(char)
        metrics[sfb.glyph_name(char)] = (sfb.GLYPH_ADVANCE, sfb.glyph_shape(char)[0])
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "T", "styleName": "R"})
    tables = []
    for platform, encoding, fmt, mapping in subtables:
        table = CmapSubtable.newSubtable(fmt)
        table.platformID, table.platEncID, table.language, table.cmap = platform, encoding, 0, dict(mapping)
        tables.append(table)
    cmap = newTable("cmap")
    cmap.tableVersion = 0
    cmap.tables = tables
    builder.font["cmap"] = cmap
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost(keepGlyphNames=True)
    out = BytesIO()
    builder.save(out)
    return out.getvalue()


@pytest.mark.parametrize("fmt", [0, 4, 6, 12])
def test_every_supported_cmap_format_reads_like_fonttools(fmt):
    # scattered and contiguous runs: format 4 must use both idDelta and glyphIdArray segments
    codes = [*range(0x20, 0x30), 0x41, 0x43, 0x45, 0x50, 0x51, 0x52, 0x7E]
    mapping = {code: sfb.glyph_name(chr(code)) for code in codes}
    program = _mapped("fmt", mapping, fmt)
    font = TTFont(BytesIO(program))
    reference = {code: font.getGlyphID(name) for code, name in font["cmap"].getcmap(1, 0).cmap.items()}
    lookup = builtin_glyph_proof(program, "FontFile2")._impl.cmaps[(1, 0)]
    assert reference, fmt
    for code in range(0, 300):
        assert lookup(code) == reference.get(code, 0), (fmt, code)


def test_a_cmap_format_the_reader_does_not_know_makes_the_program_unreadable():
    program = bytearray(_mapped("fmt", {0x41: "A"}, 6))
    font = TTFont(BytesIO(bytes(program)))
    assert font["cmap"].tables[0].format == 6
    cmap_at = next(
        struct.unpack_from(">I", program, 12 + 16 * i + 8)[0]
        for i in range(struct.unpack_from(">H", program, 4)[0])
        if program[12 + 16 * i : 12 + 16 * i + 4] == b"cmap"
    )
    subtable_at = cmap_at + struct.unpack_from(">I", program, cmap_at + 4 + 4)[0]
    struct.pack_into(">H", program, subtable_at, 2)  # format 2: high-byte mapping, not read
    proof = builtin_glyph_proof(bytes(program), "FontFile2")
    assert proof.program_kind == "unproven:unreadable"
    assert not any(proof.present(code) for code in range(256))


# ----------------------------------------------------------------------------------------------
# (i) / (ii) parity with the independent helper legs
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sfb.KINDS)
def test_whatever_the_product_proves_the_helper_leg_vouches_for(kind):
    """(i) ``proves`` implies the helper's walk + claim + outline pass; never the reverse (the product is stricter)."""
    fixture, proof = _proof_of(kind)
    helper = _helper_passes(fixture)
    proved = [code for code in _PRINTABLE_CODES if proof.proves(code, chr(code))]
    assert proved or kind == "symbolic_f100", kind  # f100 reaches no glyph at all; every other kind proves something
    for code in proved:
        if kind in _PSLIB_UNREADABLE:  # the helper has no leg: the product proves what the vector says (not 0x41)
            assert not helper[code] and code != 0x41, (kind, code, chr(code))
        else:
            assert helper[code], (kind, code, chr(code))


#: Where the product is stricter than the helper leg on a printable code (``proves`` False, helper passes).  The design
#: lists five kinds as "product stricter" (nonsymbolic_builtin_conflict, symbolic_30_partial, nonsymbolic_31_partial,
#: symbolic_f100, symbolic_names_lie): the product demands EVERY present table to agree, while the helper selects the one
#: table MuPDF selects.  Measured after the B2 tightening, only the first still differs on an ASCII code: the helper
#: follows MuPDF's order ((1,0) wins for a nonsymbolic font, so it draws the honest A) while the product sees the lying
#: (3,0) as a second route and refuses.  The partial-table kinds and symbolic_f100 are "unmapped" for the helper AND
#: "not present" for the product (both False); symbolic_names_lie fails the helper's own (3,1) cross-check (B2), so
#: both are False there too.  The expected differences are pinned EXACTLY, so a drift in either reader turns red.
#: symbolic_plat0_lie (review finding F1): MuPDF selects the honest (3,0) and the helper follows it, while the product
#: sees the lying (0,3) as a second route and refuses.  type1_decoy_vector: the helper has no leg (U5), the product
#: proves every code but the lying 0x41, so ``helper`` is all False there and the difference is every proved code.
_PRODUCT_STRICTER = {
    "nonsymbolic_builtin_conflict": {0x41},
    "symbolic_plat0_lie": {0x41},
    "type1_decoy_vector": set(_PRINTABLE_CODES) - {0x41},
}


@pytest.mark.parametrize("kind", sfb.KINDS)
def test_the_product_and_the_helper_leg_agree_outside_the_pinned_stricter_cases(kind):
    """(ii) equality of outcome on every printable code, apart from the pinned stricter set."""
    fixture, proof = _proof_of(kind)
    helper = _helper_passes(fixture)
    differing = {code for code in _PRINTABLE_CODES if proof.proves(code, chr(code)) != helper[code]}
    assert differing == _PRODUCT_STRICTER.get(kind, set()), (kind, sorted(differing))
    if kind in _PSLIB_UNREADABLE:  # the product is the only reader: it proves exactly the differing codes
        assert all(proof.proves(code, chr(code)) for code in differing), kind
        return
    for code in differing:
        assert helper[code] and not proof.proves(code, chr(code)), (kind, code)  # the product is the stricter side


# ----------------------------------------------------------------------------------------------
# (v) present / proves unit cases
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["symbolic_30_partial", "nonsymbolic_31_partial"])
def test_a_table_that_lacks_a_code_makes_the_code_not_present(kind):
    _fixture, proof = _proof_of(kind)
    assert not proof.present(0x41) and not proof.proves(0x41, "A")  # MuPDF draws .notdef for A
    assert proof.present(0x42) and proof.proves(0x42, "B")
    assert proof.unproven("AB", b"AB") == 0  # a missing glyph is encoding_failed's business, not G1'


def test_symbolic_f100_has_no_present_code():
    _fixture, proof = _proof_of("symbolic_f100")
    assert not any(proof.present(code) for code in range(256))
    assert proof.program_kind == "truetype"


def test_a_conflicting_font_has_the_glyph_but_proves_nothing_for_the_conflicting_code():
    _fixture, proof = _proof_of("nonsymbolic_builtin_conflict")
    assert proof.present(0x41) and not proof.proves(0x41, "A")
    assert proof.present(0x42) and proof.proves(0x42, "B")
    assert proof.unproven("AB", b"AB") == 1


# ----------------------------------------------------------------------------------------------
# review finding F1: EVERY cmap subtable of the program is a route (MuPDF falls back to the FIRST subtable)
# ----------------------------------------------------------------------------------------------
_HONEST = {code: sfb.glyph_name(chr(code)) for code in _PRINTABLE_CODES}
_LIE = {**_HONEST, 0x41: "B"}
_PARTIAL = {code: name for code, name in _HONEST.items() if code != 0x41}


@pytest.mark.parametrize("kind", ["nonsymbolic_plat0_lie", "symbolic_plat0_lie"])
def test_a_lying_unicode_platform_table_beside_an_honest_one_is_a_disagreeing_route(kind):
    _fixture, proof = _proof_of(kind)
    assert proof.program_kind == "truetype"
    assert proof.present(0x41) and not proof.proves(0x41, "A") and not proof.proves(0x41, "B")
    assert proof.proves(0x42, "B")  # the tables agree on every other code
    assert proof.unproven("AB", b"AB") == 1


@pytest.mark.parametrize(
    ("subtables", "present", "proved"),
    [
        # a format-12 (3,10) table is a route like any other, whatever the platform / encoding
        ([(3, 1, 4, _HONEST), (3, 10, 12, _LIE)], True, False),
        ([(0, 3, 4, _LIE), (3, 1, 4, _HONEST)], True, False),
        ([(1, 1, 0, _LIE), (3, 1, 4, _HONEST)], True, False),
        ([(0, 3, 6, _LIE), (1, 0, 0, _HONEST), (3, 1, 4, _HONEST)], True, False),
        # a table that lacks the code makes the code not present (MuPDF may select it and draw .notdef)
        ([(0, 3, 4, _PARTIAL), (3, 1, 4, _HONEST)], False, False),
        ([(3, 10, 12, _PARTIAL), (3, 1, 4, _HONEST)], False, False),
        # honest tables that agree on every code still prove it
        ([(0, 3, 4, _HONEST), (1, 0, 0, _HONEST), (3, 1, 4, _HONEST), (3, 10, 12, _HONEST)], True, True),
        ([(0, 3, 4, _HONEST), (3, 1, 4, _HONEST)], True, True),
    ],
    ids=["31+3_10lie", "03lie+31", "11lie+31", "03lie+10+31", "03partial+31", "3_10partial+31", "four-honest", "03+31"],
)
def test_every_cmap_subtable_must_map_the_code_to_the_same_glyph(subtables, present, proved):
    proof = builtin_glyph_proof(_mapped_tables(subtables), "FontFile2")
    assert proof.program_kind == "truetype"
    assert proof.present(0x41) is present and proof.proves(0x41, "A") is proved
    assert proof.proves(0x42, "B")  # every table maps B honestly
    assert proof.unproven("A", b"A") == (1 if present and not proved else 0)


def _cmap_table_offset(program: bytes) -> int:
    for position in range(struct.unpack_from(">H", program, 4)[0]):
        if program[12 + 16 * position : 12 + 16 * position + 4] == b"cmap":
            return struct.unpack_from(">I", program, 12 + 16 * position + 8)[0]
    raise AssertionError("no cmap table")


def test_a_duplicate_platform_encoding_pair_makes_the_program_unreadable():
    program = bytearray(_mapped_tables([(0, 3, 4, _HONEST), (3, 1, 4, _HONEST)]))
    struct.pack_into(">HH", program, _cmap_table_offset(bytes(program)) + 4 + 8, 0, 3)  # the second record becomes (0,3)
    proof = builtin_glyph_proof(bytes(program), "FontFile2")
    assert proof.program_kind == "unproven:unreadable" and not any(proof.present(code) for code in range(256))


@pytest.mark.parametrize("target", [(0, 3), (3, 10), (1, 1), (3, 1)], ids=lambda pair: f"{pair[0]}_{pair[1]}")
@pytest.mark.parametrize("fmt", [2, 8, 13, 14])
def test_a_cmap_subtable_in_a_format_the_reader_lacks_makes_the_program_unreadable(target, fmt):
    """Only formats 0 / 4 / 6 / 12 are read; a subtable in any other format, on ANY platform, is a route the reader
    cannot evaluate, so the whole program is unproven (every code absent)."""
    others = [key for key in ((0, 3), (3, 10), (1, 1), (3, 1)) if key != target][:1]
    honest = _mapped_tables([(*key, 4, _HONEST) for key in sorted({target, *others})])
    program = bytearray(honest)
    cmap_at = _cmap_table_offset(honest)
    (count,) = struct.unpack_from(">H", program, cmap_at + 2)
    patched = 0
    for position in range(count):
        platform_id, encoding_id, offset = struct.unpack_from(">HHI", program, cmap_at + 4 + 8 * position)
        if (platform_id, encoding_id) == target:
            struct.pack_into(">H", program, cmap_at + offset, fmt)
            patched += 1
    assert patched == 1
    proof = builtin_glyph_proof(bytes(program), "FontFile2")
    assert proof.program_kind == "unproven:unreadable", (target, fmt)
    assert not any(proof.present(code) for code in range(256))


@pytest.mark.parametrize("kind", ["symbolic_ascii", "type1_builtin", "winansi_nopost", "post3_cmap31"])
def test_whitespace_needs_no_outline(kind):
    fixture, proof = _proof_of(kind)
    assert proof.present(0x20) and proof.proves(0x20, " ")
    assert not proof.proves(0x20, "A")  # the glyph is the space, not an A


# ----------------------------------------------------------------------------------------------
# review finding F2: the Type1 vector is the text between ``/Encoding 256 array`` and the ``def`` that closes it
# ----------------------------------------------------------------------------------------------
def _type1_patched(old: bytes, new: bytes, kind: str = "type1_builtin"):
    program = _program(sfb.build_embedded_simple_fixture(kind, "AB"))
    assert program.count(old) == 1, old
    return builtin_glyph_proof(program.replace(old, new), "FontFile")


def test_a_decoy_array_after_the_vector_does_not_override_it():
    _fixture, proof = _proof_of("type1_decoy_vector")
    assert proof.program_kind == "type1"
    assert proof._impl.code_name(0x41) == "B"  # FreeType stops at the vector's own ``def``
    assert proof.present(0x41) and not proof.proves(0x41, "A")  # the glyph is B: it proves a B, never an A
    assert proof.proves(0x42, "B") and proof.proves(0x43, "C")
    assert proof.unproven("A", b"A") == 1


def test_assignments_after_the_vectors_def_are_ignored_even_without_a_decoy_name():
    proof = _type1_patched(b"readonly def\ncurrentdict end", b"readonly def\ndup 65 /B put\ncurrentdict end")
    assert proof.program_kind == "type1" and proof._impl.code_name(0x41) == "A" and proof.proves(0x41, "A")


def test_a_vector_closed_by_a_plain_def_reads_like_one_closed_by_readonly_def():
    proof = _type1_patched(b"readonly def\ncurrentdict end", b"def\ncurrentdict end")
    assert proof.program_kind == "type1" and proof.proves(0x41, "A") and proof.proves(0x7E, "~")


def test_a_code_assigned_twice_inside_the_vector_is_unreadable():
    proof = _type1_patched(b"dup 65 /A put\n", b"dup 65 /A put\ndup 65 /B put\n")
    assert proof.program_kind == "unproven:unreadable" and not proof.present(0x41) and not proof.present(0x42)


def test_a_second_encoding_definition_is_unreadable():
    proof = _type1_patched(
        b"currentdict end\ncurrentfile eexec", b"/Encoding StandardEncoding def\ncurrentdict end\ncurrentfile eexec"
    )
    assert proof.program_kind == "unproven:unreadable" and not proof.present(0x41)
    proof = _type1_patched(
        b"currentdict end\ncurrentfile eexec",
        b"/Encoding 256 array dup 65 /B put readonly def\ncurrentdict end\ncurrentfile eexec",
        kind="type1_standard",
    )
    assert proof.program_kind == "unproven:unreadable" and not proof.present(0x41)


def test_a_glyph_named_def_does_not_close_the_vector():
    """``/def`` is a glyph NAME, not the ``def`` operator: only a standalone token ends the vector."""
    proof = _type1_patched(b"dup 66 /B put\n", b"dup 66 /B put\ndup 200 /def put\n")
    assert proof.program_kind == "type1" and proof.proves(0x42, "B") and proof.proves(0x7E, "~")
    assert proof._impl.code_name(200) == "def"


def test_a_type1_glyph_that_draws_nothing_is_present_but_not_proved():
    _fixture, proof = _proof_of("type1_emptyglyph")
    assert proof.present(0x41) and not proof.proves(0x41, "A")
    assert proof.proves(0x42, "B")
    assert proof.unproven("A", b"A") == 1


def test_an_unproven_proof_has_no_present_code():
    for reason in ("fontfile3", "too_large", "unreadable", "several_programs", "no_program"):
        proof = sfp.unproven_proof(reason)
        assert proof.program_kind == f"unproven:{reason}"
        assert not any(proof.present(code) or proof.proves(code, chr(code)) for code in range(256))
        assert proof.unproven("Level A", b"Level A") == 0


def test_a_fontfile3_blob_is_unproven():
    proof = builtin_glyph_proof(b"OTTO" + b"\0" * 100, "FontFile3")
    assert proof.program_kind == "unproven:fontfile3"
    assert not proof.present(0x41)


def test_a_truncated_sfnt_is_unreadable():
    fixture = sfb.build_embedded_simple_fixture("symbolic_ascii", "AB")
    program = _program(fixture)
    for cut in (0, 8, 40, len(program) // 2):
        proof = builtin_glyph_proof(program[:cut], "FontFile2")
        assert proof.program_kind == "unproven:unreadable", cut
        assert not proof.present(0x41)
    assert builtin_glyph_proof(b"OTTO" + program[4:], "FontFile2").program_kind == "unproven:unreadable"


def test_a_program_over_the_size_cap_is_too_large(monkeypatch):
    fixture = sfb.build_embedded_simple_fixture("symbolic_ascii", "AB")
    program = _program(fixture)
    monkeypatch.setattr(sfp, "_MAX_FONT_PROGRAM_BYTES", len(program) - 1)
    proof = builtin_glyph_proof(program, "FontFile2")
    assert proof.program_kind == "unproven:too_large" and not proof.present(0x41)
    monkeypatch.setattr(sfp, "_MAX_FONT_PROGRAM_BYTES", len(program))
    assert builtin_glyph_proof(program, "FontFile2").program_kind == "truetype"
    type1 = _program(sfb.build_embedded_simple_fixture("type1_builtin", "AB"))
    monkeypatch.setattr(sfp, "_MAX_TYPE1_PROGRAM_BYTES", len(type1) - 1)
    assert builtin_glyph_proof(type1, "FontFile").program_kind == "unproven:too_large"


def _patch_post_version(program: bytes, version: int) -> bytes:
    data = bytearray(program)
    for index in range(struct.unpack_from(">H", data, 4)[0]):
        if data[12 + 16 * index : 12 + 16 * index + 4] == b"post":
            struct.pack_into(">I", data, struct.unpack_from(">I", data, 12 + 16 * index + 8)[0], version)
            return bytes(data)
    raise AssertionError("no post table")


@pytest.mark.parametrize("version", [0x00025000, 0x00040000])
def test_post_format_2_5_and_4_are_unproven(version):
    program = _patch_post_version(_program(sfb.build_embedded_simple_fixture("symbolic_ascii", "AB")), version)
    proof = builtin_glyph_proof(program, "FontFile2")
    assert proof.program_kind == "unproven:post_format" and not proof.present(0x41)


def test_post_format_1_is_valid_only_up_to_258_glyphs():
    for count, expected in ((100, "truetype"), (258, "truetype"), (259, "unproven:post_format")):
        names = [*standardGlyphOrder[:258], *(f"extra{i}" for i in range(max(0, count - 258)))][:count]
        builder = FontBuilder(1000, isTTF=True)
        builder.setupGlyphOrder(names)
        builder.setupGlyf({name: sfb._outline("A") for name in names})
        builder.setupHorizontalMetrics({name: (600, 0) for name in names})
        builder.setupHorizontalHeader(ascent=800, descent=-200)
        builder.setupNameTable({"familyName": "T", "styleName": "R"})
        table = CmapSubtable.newSubtable(4)
        table.platformID, table.platEncID, table.language = 1, 0, 0
        table.cmap = {0x41: "A"}
        cmap = newTable("cmap")
        cmap.tableVersion, cmap.tables = 0, [table]
        builder.font["cmap"] = cmap
        builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
        builder.setupPost(keepGlyphNames=True)
        builder.font["post"].formatType = 1.0
        out = BytesIO()
        builder.save(out)
        program = out.getvalue()
        assert float(TTFont(BytesIO(program))["post"].formatType) == 1.0 or count > 258
        proof = builtin_glyph_proof(program, "FontFile2")
        if count > 258:  # fontTools writes 2.0 when it must name glyphs beyond the standard order; force 1.0 bytes
            program = _patch_post_version(program, 0x00010000)
            proof = builtin_glyph_proof(program, "FontFile2")
        assert proof.program_kind == expected, count
        if expected == "truetype":
            assert proof._impl.name_of(3) == "space" and proof._impl.name_of(36) == "A"
            assert proof.proves(0x41, "A")


def _post_table_offset(program: bytes) -> int:
    for index in range(struct.unpack_from(">H", program, 4)[0]):
        if program[12 + 16 * index : 12 + 16 * index + 4] == b"post":
            return struct.unpack_from(">I", program, 12 + 16 * index + 8)[0]
    raise AssertionError("no post table")


def test_a_duplicate_glyph_name_blocks_the_proof_per_glyph():
    """Glyph B is renamed ``A`` in the post table (both glyphs now carry the name A): neither is proved as an A, B
    is no longer named B, and every other letter is still proved.  fontTools would not build such a font."""
    program = bytearray(_program(sfb.build_embedded_simple_fixture("symbolic_ascii", "AB")))
    index_of_a = standardGlyphOrder.index("A")
    struct.pack_into(">H", program, _post_table_offset(bytes(program)) + 34 + 2 * sfb.glyph_id("B"), index_of_a)
    proof = builtin_glyph_proof(bytes(program), "FontFile2")
    assert proof.program_kind == "truetype"
    assert [proof._impl.name_of(sfb.glyph_id(char)) for char in "ABC"] == ["A", "A", "C"]
    assert proof.present(0x41) and proof.present(0x42)
    assert not proof.proves(0x41, "A")  # another glyph carries the name A
    assert not proof.proves(0x42, "B") and not proof.proves(0x42, "A")
    assert proof.proves(0x43, "C")
    assert proof.unproven("ABC", b"ABC") == 2


def _hex_form(fixture: sfb.SimpleFixture) -> bytes:
    program = _program(fixture)
    length1 = int(fixture.doc.xref_get_key(fixture.fontfile_xref, "Length1")[1])
    length2 = int(fixture.doc.xref_get_key(fixture.fontfile_xref, "Length2")[1])
    body = program[length1 : length1 + length2].hex().upper().encode("ascii")
    lines = b"\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    return program[:length1] + lines + b"\n" + program[length1 + length2 :]


def test_a_hex_eexec_type1_program_reads_like_the_binary_one():
    fixture = sfb.build_embedded_simple_fixture("type1_builtin", "AB")
    binary = builtin_glyph_proof(_program(fixture), "FontFile")
    hexed = builtin_glyph_proof(_hex_form(fixture), "FontFile")
    assert hexed.program_kind == "type1" and hexed.num_glyphs == binary.num_glyphs
    for code in _PRINTABLE_CODES:
        assert hexed.present(code) == binary.present(code)
        assert hexed.proves(code, chr(code)) == binary.proves(code, chr(code))


def test_an_unreadable_hex_eexec_section_is_unproven():
    fixture = sfb.build_embedded_simple_fixture("type1_builtin", "AB")
    program = _program(fixture)
    clear = program[: int(fixture.doc.xref_get_key(fixture.fontfile_xref, "Length1")[1])]
    assert builtin_glyph_proof(clear + b"ABCD\n", "FontFile").program_kind == "unproven:hex_eexec_unreadable"
    assert builtin_glyph_proof(clear[: clear.index(b"eexec")], "FontFile").program_kind == "unproven:unreadable"


def test_a_type1_program_without_notdef_is_unproven(monkeypatch):
    monkeypatch.setattr(sfb, "_T1_ORDER", [name for name in sfb._T1_ORDER if name != ".notdef"])
    program = sfb._build_type1_program("type1_builtin")[0]
    proof = builtin_glyph_proof(program, "FontFile")
    assert proof.program_kind == "unproven:no_notdef" and not proof.present(0x41)


def test_a_subroutine_drawn_glyph_has_an_outline_and_a_non_literal_call_does_not():
    """The scan follows a callsubr with a LITERAL index into Subrs; a computed index contributes nothing."""

    def charstring(program: list) -> bytes:
        cs = T1CharString()
        cs.program = program
        cs.compile()
        return eexec.encrypt(b"\0\0\0\0" + cs.bytecode, 4330)[0]

    subr0 = charstring([0, 100, "rlineto", "return"])
    glyph_literal = charstring([0, 500, "hsbw", 0, "callsubr", "endchar"])
    glyph_computed = charstring([0, 500, "hsbw", 1, 0, "div", "callsubr", "endchar"])
    glyph_empty = charstring([0, 500, "hsbw", "endchar"])
    private = (
        b"dup /Private 8 dict dup begin\n/RD {string currentfile exch readstring pop} executeonly def\n"
        b"/ND {noaccess def} executeonly def\n/NP {noaccess put} executeonly def\n/lenIV 4 def\n"
        b"/Subrs 1 array\ndup 0 %d RD " % len(subr0) + subr0 + b" NP\nND\n"
    )
    entries = {".notdef": glyph_empty, "A": glyph_literal, "B": glyph_computed, "C": glyph_empty}
    body = b"2 index /CharStrings %d dict dup begin\n" % len(entries)
    for name, cs in entries.items():
        body += b"/%s %d RD " % (name.encode(), len(cs)) + cs + b" ND\n"
    body += b"end end\nreadonly put\nput\ndup /FontName get exch definefont pop\nmark currentfile closefile\n"
    encrypted = eexec.encrypt(b"\0\0\0\0" + private + body, 55665)[0]
    clear = (
        b"%!PS-AdobeFont-1.0: T 1.0\n11 dict begin\n/FontName /T def\n/FontType 1 def\n"
        b"/Encoding 256 array\n0 1 255 {1 index exch /.notdef put} for\n"
        b"dup 65 /A put\ndup 66 /B put\ndup 67 /C put\nreadonly def\ncurrentdict end\ncurrentfile eexec\n"
    )
    proof = builtin_glyph_proof(clear + encrypted, "FontFile")
    assert proof.program_kind == "type1"
    assert proof.proves(0x41, "A")  # drawn only through Subrs[0]
    assert proof.present(0x42) and not proof.proves(0x42, "B")  # a computed index is not followed
    assert proof.present(0x43) and not proof.proves(0x43, "C")  # hsbw endchar alone


# ----------------------------------------------------------------------------------------------
# the wiring in FontCapability
# ----------------------------------------------------------------------------------------------
def _capability(fixture: sfb.SimpleFixture):
    capability = DocumentFontRegistry(fixture.doc).capability(fixture.page, fixture.resource_name)
    assert capability is not None
    return capability


@pytest.mark.parametrize("kind", ["winansi", "post3_cmap31", "winansi_nopost"])
def test_a_font_with_an_encoding_has_no_builtin_proof_and_is_unchanged(kind):
    capability = _capability(sfb.build_embedded_simple_fixture(kind, "Level B 2024"))
    assert capability.builtin_proof is None
    assert capability.builtin_encoding_unproven("Level A 2024", b"Level A 2024") == 0
    assert capability.missing_glyphs("Level A 2024") == ""


@pytest.mark.parametrize("kind", ["symbolic_ascii", "symbolic_post3", "type1_builtin", "symbolic_mac10"])
def test_an_in_scope_font_checks_presence_through_the_proof_not_the_face(kind):
    capability = _capability(sfb.build_embedded_simple_fixture(kind, "Level B 2024"))
    assert capability.builtin_proof is not None and capability.face_source == "extracted"
    assert capability.missing_glyphs("Level A 2024") == ""
    assert capability.missing_glyphs("Level é") == "é"  # a code the program does not have
    assert capability.builtin_encoding_unproven("Level A 2024", b"Level A 2024") == 0


def test_the_proof_does_not_take_part_in_capability_equality():
    first = _capability(sfb.build_embedded_simple_fixture("symbolic_ascii", "AB"))
    second = _capability(sfb.build_embedded_simple_fixture("symbolic_ascii", "AB"))
    assert first.builtin_proof is not second.builtin_proof
    assert dataclasses.replace(first, builtin_proof=second.builtin_proof) == first
    assert dataclasses.replace(first, builtin_proof=None) == first
    assert "builtin_proof" not in repr(first)


def test_two_font_programs_on_one_descriptor_are_unproven():
    fixture = sfb.build_embedded_simple_fixture("symbolic_ascii", "Level B 2024")
    descriptor = int(fixture.doc.xref_get_key(fixture.font_xref, "FontDescriptor")[1].split()[0])
    fixture.doc.xref_set_key(descriptor, "FontFile", f"{fixture.fontfile_xref} 0 R")
    capability = _capability(fixture)
    assert capability.builtin_proof is not None
    assert capability.builtin_proof.program_kind == "unproven:several_programs"
    assert capability.missing_glyphs("A") == "A"  # nothing is present: encoding_failed


def test_rewriting_the_program_in_place_rebuilds_the_proof():
    """The evidence digest folds the FontFile bytes, so a cached capability never serves a stale proof."""
    fixture = sfb.build_embedded_simple_fixture("symbolic_ascii", "Level B 2024")
    registry = DocumentFontRegistry(fixture.doc)
    before = registry.capability(fixture.page, fixture.resource_name)
    assert before is not None and before.builtin_encoding_unproven("A", b"A") == 0
    digest = compute_simple_font_evidence_digest(fixture.doc, fixture.font_xref)
    lie = sfb.build_embedded_simple_fixture("symbolic_post3_wrongglyph", "AB")
    fixture.doc.update_stream(fixture.fontfile_xref, _program(lie))
    assert compute_simple_font_evidence_digest(fixture.doc, fixture.font_xref) != digest
    after = registry.capability(fixture.page, fixture.resource_name)
    assert after is not None and after.builtin_encoding_unproven("A", b"A") == 1


# ----------------------------------------------------------------------------------------------
# (vi) latency
# ----------------------------------------------------------------------------------------------
def _wide_truetype(count: int) -> bytes:
    """An honest symbolic TrueType of ``count`` glyphs: the printable AGL names, then ``g0001`` ...; (3,0) + (3,1) + (1,0)."""
    names = [".notdef", *(sfb.glyph_name(char) for char in sfb._PRINTABLE)]
    extra = [f"g{index:04d}" for index in range(count - len(names))]
    builder = FontBuilder(sfb.UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(names + extra)
    glyphs = {".notdef": sfb._outline(" ")}
    metrics = {".notdef": (sfb.GLYPH_ADVANCE, 0)}
    for char in sfb._PRINTABLE:
        glyphs[sfb.glyph_name(char)] = sfb._outline(char)
        metrics[sfb.glyph_name(char)] = (sfb.GLYPH_ADVANCE, sfb.glyph_shape(char)[0])
    for index, name in enumerate(extra):
        pen = TTGlyphPen(None)
        pen.moveTo((10, 0))
        pen.lineTo((10, 300 + index % 400))
        pen.lineTo((300, 300 + index % 400))
        pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (sfb.GLYPH_ADVANCE, 10)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Wide", "styleName": "Regular"})
    unicode_map = {ord(char): sfb.glyph_name(char) for char in sfb._PRINTABLE}
    unicode_map.update({0x4E00 + index: name for index, name in enumerate(extra)})
    symbol_map = {0xF000 + ord(char): sfb.glyph_name(char) for char in sfb._PRINTABLE}
    cmap = newTable("cmap")
    cmap.tableVersion = 0
    cmap.tables = [
        sfb._cmap_subtable(3, 0, symbol_map),
        sfb._cmap_subtable(3, 1, unicode_map),
        sfb._cmap_subtable(1, 0, {ord(char): sfb.glyph_name(char) for char in sfb._PRINTABLE}),
    ]
    builder.font["cmap"] = cmap
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost(keepGlyphNames=True)
    out = BytesIO()
    builder.save(out)
    return out.getvalue()


def _wide_type1(count: int) -> bytes:
    """A Type1 program of ``count`` glyphs (the printable ones, then ``g001`` ... with ~150-byte charstrings), ``.notdef`` last."""
    extra = [f"g{index:03d}" for index in range(count - len(sfb._PRINTABLE) - 1)]
    names = [*(sfb.glyph_name(char) for char in sfb._PRINTABLE), *extra, ".notdef"]
    encoding = b"/Encoding 256 array\n0 1 255 {1 index exch /.notdef put} for\n"
    for char in sfb._PRINTABLE:
        encoding += b"dup %d /%s put\n" % (ord(char), sfb.glyph_name(char).encode("ascii"))
    encoding += b"readonly def\n"
    clear = (
        b"%!PS-AdobeFont-1.0: Wide 1.0\n11 dict begin\n/FontName /Wide def\n/PaintType 0 def\n/FontType 1 def\n"
        b"/FontMatrix [0.001 0 0 0.001 0 0] readonly def\n/FontBBox {0 -200 1000 800} readonly def\n"
        + encoding
        + b"currentdict end\ncurrentfile eexec\n"
    )
    parts = [b"2 index /CharStrings %d dict dup begin\n" % len(names)]
    for name in names:
        program: list = [0, sfb.GLYPH_ADVANCE, "hsbw", 40, 0, "rmoveto"]
        if name != ".notdef" and name != "space":
            for step in range(24):
                program += [10 + step, 20 + step % 7, "rlineto"]
            program += [0, 250, 100, 0, 0, -250, "rrcurveto", "closepath"]
        program.append("endchar")
        charstring = T1CharString()
        charstring.program = program
        charstring.compile()
        encrypted = eexec.encrypt(b"\0\0\0\0" + charstring.bytecode, 4330)[0]
        parts.append(b"/%s %d RD " % (name.encode("ascii"), len(encrypted)) + encrypted + b" ND\n")
    parts.append(b"end end\nreadonly put\nput\ndup /FontName get exch definefont pop\nmark currentfile closefile\n")
    binary = eexec.encrypt(b"\0\0\0\0" + sfb._T1_PRIVATE + b"".join(parts), 55665)[0]
    return clear + binary + (b"0" * 64 + b"\n") * 8 + b"cleartomark\n"


def _six_font_pdf() -> bytes:
    """A page with four 300-glyph Type1 fonts and two 1 000-glyph TrueType fonts, all symbolic with no /Encoding."""
    programs = [("FontFile", _wide_type1(300)) for _ in range(4)] + [("FontFile2", _wide_truetype(1000)) for _ in range(2)]
    widths = sfb._widths_array(None)
    bodies: dict[int, bytes] = {}
    fonts = " ".join(f"/F{index + 1} {5 + 3 * index} 0 R" for index in range(len(programs)))
    content = b" ".join(
        f"BT /F{index + 1} 12 Tf 72 {700 - 20 * index} Td (Level A 2024) Tj ET".encode("ascii")
        for index in range(len(programs))
    )
    bodies[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    bodies[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    bodies[3] = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << {fonts} >> >> /Contents 4 0 R >>".encode()
    bodies[4] = _stream_obj(f"<< /Length {len(content)} >>", content)
    for index, (key, program) in enumerate(programs):
        font, descriptor, stream = 5 + 3 * index, 6 + 3 * index, 7 + 3 * index
        subtype = "Type1" if key == "FontFile" else "TrueType"
        bodies[font] = (
            f"<< /Type /Font /Subtype /{subtype} /BaseFont /ABCDEF+Wide{index} /FirstChar 32 /LastChar 126 "
            f"/Widths {widths} /FontDescriptor {descriptor} 0 R >>"
        ).encode("ascii")
        bodies[descriptor] = (
            f"<< /Type /FontDescriptor /FontName /ABCDEF+Wide{index} /Flags 4 /FontBBox [0 -200 1000 800] "
            f"/ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 /{key} {stream} 0 R >>"
        ).encode("ascii")
        extra = f" /Length1 {len(program)}" if key == "FontFile2" else ""
        bodies[stream] = _stream_obj(f"<< /Length {len(program)}{extra} >>", program)
    return _assemble_pdf(bodies)


#: CI-safe ceiling for the cold capability build of six embedded built-in-encoding fonts (plan 3.2: 50 ms target)
_LATENCY_CEILING_MS = 150.0


def test_cold_capabilities_of_six_large_embedded_fonts_build_within_the_budget():
    data = _six_font_pdf()
    totals: list[float] = []
    for _ in range(5):
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            page = doc[0]
            names = [entry[4] for entry in page.get_fonts(full=True)]
            assert len(names) == 6
            registry = DocumentFontRegistry(doc)
            started = time.perf_counter()
            capabilities = [registry.capability(page, name) for name in names]
            totals.append((time.perf_counter() - started) * 1000.0)
            assert all(capability is not None and capability.builtin_proof is not None for capability in capabilities)
            kinds = sorted(capability.builtin_proof.program_kind for capability in capabilities)  # type: ignore[union-attr]
            assert kinds == ["truetype", "truetype", "type1", "type1", "type1", "type1"]
            for capability in capabilities:  # and the proofs answer
                assert capability.missing_glyphs("Level A 2024") == ""  # type: ignore[union-attr]
                assert capability.builtin_encoding_unproven("Level A 2024", b"Level A 2024") == 0  # type: ignore[union-attr]
        finally:
            doc.close()
    median = statistics.median(totals)
    print(f"cold capability build of 4 Type1 (300 glyphs) + 2 TrueType (1000 glyphs): median {median:.1f} ms of {totals}")
    assert median < _LATENCY_CEILING_MS, (median, totals)


# ----------------------------------------------------------------------------------------------
# (vii) the four real programs behind the owner's rows
# ----------------------------------------------------------------------------------------------
_REAL_CASES = (
    ("test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", 3),
    ("test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", 49),
    ("test_files/sample-files-main/001-trivial/minimal-document.pdf", 7),
    ("test_files/mozilla-pdf/artofwar.pdf", 73),
    ("test_files/mozilla-pdf/bug1946953.pdf", 1),
)


@pytest.mark.needs_fixtures
@pytest.mark.parametrize(("relative_path", "show_index"), _REAL_CASES, ids=[f"{p.split('/')[-1]}-s{i}" for p, i in _REAL_CASES])
def test_the_real_programs_prove_every_glyph_of_the_edited_show(relative_path, show_index):
    """The evidence that the owner's rows still commit: every (code, char) of the show is proved, nothing is missing."""
    try:
        doc = _open_public(relative_path)
    except helpers.FixtureUnavailable as exc:
        pytest.skip(str(exc))
    try:
        show, codes, _gids, text = _unedited_show_inputs(doc, show_index)
        assert text and len(text) == len(codes)
        capability = DocumentFontRegistry(doc).capability(doc[0], show.font_resource)
        assert capability is not None and capability.builtin_proof is not None, relative_path
        proof = capability.builtin_proof
        assert proof.program_kind in ("type1", "truetype"), proof.program_kind
        for char, code in zip(text, codes, strict=True):
            assert proof.present(code), (relative_path, show_index, char, code)
            assert proof.proves(code, char), (relative_path, show_index, char, code)
        assert capability.missing_glyphs(text) == ""
        assert capability.builtin_encoding_unproven(text, bytes(codes)) == 0
    finally:
        doc.close()
