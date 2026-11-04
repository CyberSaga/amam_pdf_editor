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

import dataclasses
import re
from io import BytesIO

import fitz
import numpy as np
import pytest
from fontTools.agl import UV2AGL
from fontTools.misc import eexec, psLib
from fontTools.misc.psCharStrings import T1CharString
from fontTools.pens.boundsPen import BoundsPen
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


def _type1(fixture: sfb.SimpleFixture) -> dict:
    """The embedded Type1 program (``/FontFile``), parsed by fontTools' PostScript reader."""
    return psLib.suckfont(fixture.doc.xref_stream(fixture.fontfile_xref), "ascii")


def _type1_bounds(font: dict, name: str):
    """``(xMin, yMin, xMax, yMax)`` of the named Type1 glyph, ``None`` when it draws nothing."""
    private = font["Private"]
    len_iv = private.get("lenIV", 4)
    charstring = T1CharString(eexec.decrypt(font["CharStrings"][name], 4330)[0][len_iv:], subrs=[])
    pen = BoundsPen(None)
    charstring.draw(pen)
    return pen.bounds


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
        "winansi_nopost",
        "type1_builtin",
        "type1_standard",
        "type1_wrongname",
        "type1_emptyglyph",
        "symbolic_mac10",
        "symbolic_mac10_wrongglyph",
        "symbolic_f100",
        "symbolic_30_partial",
        "nonsymbolic_31_partial",
        "nonsymbolic_builtin_conflict",
        "symbolic_names_lie",
        "symbolic_postname_variant",
        "nonsymbolic_plat0_lie",
        "symbolic_plat0_lie",
        "type1_decoy_vector",
        "macroman",
    }
    programs ={kind: _program(fixture) for kind, fixture in built.items() if kind not in sfb.TYPE1_KINDS}

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

    # winansi_nopost: exactly winansi (nonsymbolic, /WinAnsiEncoding, (3,1) only) with NO post table at all
    fx, font = built["winansi_nopost"], programs["winansi_nopost"]
    reference = programs["winansi"]
    assert _flags(fx) & 32 and not _flags(fx) & 4
    assert _font_dict_key(fx, "Encoding") == ("name", "/WinAnsiEncoding")
    assert "post" not in font and "post" in reference
    assert _subtable(font, 3, 0) is None and _subtable(font, 3, 1) is not None
    for code in range(0x20, 0x7F):
        assert _coords(font, _subtable(font, 3, 1).cmap[code]) == _coords(reference, _agl(chr(code))), code

    # macroman: nonsymbolic, /MacRomanEncoding, honest (1,0) AND (3,1) tables, post 2 names (issue1233's shape)
    fx, font = built["macroman"], programs["macroman"]
    reference = programs["winansi"]
    assert _flags(fx) & 32 and not _flags(fx) & 4
    assert _font_dict_key(fx, "Encoding") == ("name", "/MacRomanEncoding")
    assert font["post"].formatType == 2.0 and _subtable(font, 3, 0) is None
    for code in range(0x20, 0x7F):
        assert _subtable(font, 1, 0).cmap[code] == _subtable(font, 3, 1).cmap[code] == _agl(chr(code)), code
        assert _coords(font, _agl(chr(code))) == _coords(reference, _agl(chr(code))), code

    # the Type1 kinds: a /FontFile program under a /Type1 font dict, flags 4, no /Encoding, .notdef LAST
    for kind in sfb.TYPE1_KINDS:
        fx = built[kind]
        assert _font_dict_key(fx, "Subtype") == ("name", "/Type1"), kind
        assert _flags(fx) & 4 and not _flags(fx) & 32, kind
        assert _font_dict_key(fx, "Encoding")[0] == "null", kind
        assert _font_dict_key(fx, "FontDescriptor/FontFile")[0] == "xref", kind
        assert _font_dict_key(fx, "FontDescriptor/FontFile2")[0] == "null", kind
        assert _font_dict_key(fx, "FontDescriptor/FontFile3")[0] == "null", kind
        raw = fx.doc.xref_stream(fx.fontfile_xref)
        lengths = [int(fx.doc.xref_get_key(fx.fontfile_xref, f"Length{n}")[1]) for n in (1, 2, 3)]
        assert sum(lengths) == len(raw), kind
        assert raw[: lengths[0]].endswith(b"currentfile eexec\n"), kind
        assert raw[lengths[0] + lengths[1] :].endswith(b"cleartomark\n"), kind
        if kind == "type1_decoy_vector":
            continue  # fontTools' psLib cannot read it (the point of the kind); its facts are pinned below
        font = _type1(fx)
        order = list(font["CharStrings"])
        assert order[-1] == ".notdef" and order[0] == "space" and len(order) == 96, kind
        assert font["Private"].get("lenIV", 4) == 4, kind
        glyph_a, glyph_b = _type1_bounds(font, "A"), _type1_bounds(font, "B")
        assert glyph_b is not None and glyph_a != glyph_b, kind
        assert _type1_bounds(font, "space") is None and _type1_bounds(font, ".notdef") is None, kind
        # every honest printable code reaches the glyph whose name is the character's own AGL name
        encoding = font["Encoding"]
        if kind != "type1_standard":  # the standard vector is the StandardEncoding table, checked below
            for code in range(0x20, 0x7F):
                want = "B" if (kind == "type1_wrongname" and code == 0x41) else _agl(chr(code))
                assert encoding[code] == want, (kind, code)
            assert encoding[0x00] == ".notdef" and encoding[0x80] == ".notdef", kind

    standard = _type1(built["type1_standard"])["Encoding"]
    raw = built["type1_standard"].doc.xref_stream(built["type1_standard"].fontfile_xref)
    assert b"/Encoding StandardEncoding def" in raw
    assert standard[0x41] == "A" and standard[0x20] == "space" and standard[0x27] == "quoteright"
    assert b"dup 65 /A put" in built["type1_builtin"].doc.xref_stream(built["type1_builtin"].fontfile_xref)

    # type1_decoy_vector (review finding F2): type1_wrongname's program with ONE decoy array, defined after the real
    # vector's own ``readonly def`` and before ``currentdict end``; the eexec and trailer sections are byte-identical
    decoy, wrong_raw = built["type1_decoy_vector"], built["type1_wrongname"].doc.xref_stream(built["type1_wrongname"].fontfile_xref)
    decoy_raw = decoy.doc.xref_stream(decoy.fontfile_xref)
    decoy_len1 = int(decoy.doc.xref_get_key(decoy.fontfile_xref, "Length1")[1])
    wrong_len1 = int(built["type1_wrongname"].doc.xref_get_key(built["type1_wrongname"].fontfile_xref, "Length1")[1])
    extra = b"/Decoy 256 array dup 65 /A put def\n"
    assert decoy_len1 == wrong_len1 + len(extra)
    assert decoy_raw[decoy_len1:] == wrong_raw[wrong_len1:]
    assert decoy_raw[:decoy_len1].replace(extra, b"") == wrong_raw[:wrong_len1]
    assert decoy_raw[:decoy_len1].count(b"/Encoding") == 1 and decoy_raw[:decoy_len1].count(extra) == 1
    assert b"dup 126 /asciitilde put\nreadonly def\n" + extra + b"currentdict end" in decoy_raw[:decoy_len1]
    assert b"dup 65 /B put\n" in decoy_raw[:decoy_len1]
    assert _font_dict_key(decoy, "ToUnicode")[0] == "xref"

    # type1_wrongname: code 0x41 reaches the glyph NAMED B (and 0x42 still B); a glyph named A still exists
    wrong = _type1(built["type1_wrongname"])
    assert wrong["Encoding"][0x41] == "B" and wrong["Encoding"][0x42] == "B"
    assert "A" in wrong["CharStrings"] and _type1_bounds(wrong, "A") is not None

    # type1_emptyglyph: the glyph A exists, is named right, is reached by code 0x41 and draws nothing
    empty = _type1(built["type1_emptyglyph"])
    assert empty["Encoding"][0x41] == "A" and "A" in empty["CharStrings"]
    assert _type1_bounds(empty, "A") is None and _type1_bounds(empty, "B") is not None

    # ---- slice I1 stage B2: the cmap-precedence kinds.  Every one has NO /Encoding and post format 2 names; the
    # tables present, the descriptor flags, the renames and the missing entries are the whole point of each kind.
    reference = programs["winansi"]
    honest_names = {code: _agl(chr(code)) for code in range(0x20, 0x7F)}
    honest_mac = dict(honest_names)
    honest_uni = dict(honest_names)
    honest_sym = {0xF000 + code: name for code, name in honest_names.items()}
    cmap_tables = {
        kind: {(table.platformID, table.platEncID): table.cmap for table in programs[kind]["cmap"].tables}
        for kind in sfb.CMAP_PRECEDENCE_KINDS
    }
    for kind in sfb.CMAP_PRECEDENCE_KINDS:
        assert _font_dict_key(built[kind], "Encoding")[0] == "null", kind
        assert _font_dict_key(built[kind], "Subtype") == ("name", "/TrueType"), kind
        assert programs[kind]["post"].formatType == 2.0, kind
        assert (_font_dict_key(built[kind], "ToUnicode")[0] == "xref") == (kind in sfb.TOUNICODE_KINDS), kind
        assert kind in sfb.SYMBOLIC_KINDS or kind in sfb.NONSYMBOLIC_NO_ENCODING_KINDS, kind
        if kind in sfb.NONSYMBOLIC_NO_ENCODING_KINDS:
            assert _flags(built[kind]) & 32 and not _flags(built[kind]) & 4, kind
        else:
            assert _flags(built[kind]) & 4 and not _flags(built[kind]) & 32, kind
    assert set(sfb.CMAP_PRECEDENCE_KINDS) == {
        "symbolic_mac10",
        "symbolic_mac10_wrongglyph",
        "symbolic_f100",
        "symbolic_30_partial",
        "nonsymbolic_31_partial",
        "nonsymbolic_builtin_conflict",
        "symbolic_names_lie",
        "symbolic_postname_variant",
        "nonsymbolic_plat0_lie",
        "symbolic_plat0_lie",
    }
    # the glyph order is the shared one (every outline is the reference's) unless a kind says otherwise
    for kind in sfb.CMAP_PRECEDENCE_KINDS:
        if kind in ("symbolic_names_lie", "symbolic_postname_variant"):
            continue
        assert programs[kind].getGlyphOrder() == reference.getGlyphOrder(), kind

    # symbolic_mac10: ONLY a (1,0) table, honest (artofwar / bug1946953 shape)
    assert set(cmap_tables["symbolic_mac10"]) == {(1, 0)}
    assert cmap_tables["symbolic_mac10"][(1, 0)] == honest_mac

    # symbolic_mac10_wrongglyph: as above but (1,0) sends 0x41 to the glyph named B
    assert set(cmap_tables["symbolic_mac10_wrongglyph"]) == {(1, 0)}
    assert cmap_tables["symbolic_mac10_wrongglyph"][(1, 0)] == {**honest_mac, 0x41: "B"}

    # symbolic_f100: ONLY a (3,0) table at 0xF100+code (MuPDF never reads F100: .notdef for every code)
    assert set(cmap_tables["symbolic_f100"]) == {(3, 0)}
    assert cmap_tables["symbolic_f100"][(3, 0)] == {0xF100 + code: name for code, name in honest_names.items()}

    # symbolic_30_partial: (3,0) at F000+code WITHOUT 0xF041, plus an honest (3,1)
    assert set(cmap_tables["symbolic_30_partial"]) == {(3, 0), (3, 1)}
    assert cmap_tables["symbolic_30_partial"][(3, 0)] == {k: v for k, v in honest_sym.items() if k != 0xF041}
    assert 0xF041 not in cmap_tables["symbolic_30_partial"][(3, 0)]
    assert cmap_tables["symbolic_30_partial"][(3, 1)] == honest_uni

    # nonsymbolic_31_partial: flags 32, (3,1) WITHOUT U+0041, plus an honest (1,0)
    assert set(cmap_tables["nonsymbolic_31_partial"]) == {(3, 1), (1, 0)}
    assert cmap_tables["nonsymbolic_31_partial"][(3, 1)] == {k: v for k, v in honest_uni.items() if k != 0x41}
    assert 0x41 not in cmap_tables["nonsymbolic_31_partial"][(3, 1)]
    assert cmap_tables["nonsymbolic_31_partial"][(1, 0)] == honest_mac

    # nonsymbolic_builtin_conflict: flags 32, honest (1,0) + a LYING (3,0) (F041 -> the B glyph)
    assert set(cmap_tables["nonsymbolic_builtin_conflict"]) == {(1, 0), (3, 0)}
    assert cmap_tables["nonsymbolic_builtin_conflict"][(1, 0)] == honest_mac
    assert cmap_tables["nonsymbolic_builtin_conflict"][(3, 0)] == {**honest_sym, 0xF041: "B"}

    # symbolic_names_lie: the honest A outline is RENAMED uni0041, ONE extra glyph named A carries the B outline;
    # (3,0) F041 -> the extra glyph, (3,1) U+0041 -> the uni0041 glyph; B and every other char honest everywhere
    font = programs["symbolic_names_lie"]
    order = font.getGlyphOrder()
    assert len(order) == len(reference.getGlyphOrder()) + 1
    assert order[sfb.glyph_id("A")] == "uni0041" and "A" not in order[: sfb.EXTRA_GLYPH_GID]
    assert order[sfb.EXTRA_GLYPH_GID] == "A" and sfb.EXTRA_GLYPH_GID == len(order) - 1
    assert _coords(font, "uni0041") == _coords(reference, "A") != _coords(reference, "B")
    assert _coords(font, "A") == _coords(reference, "B")
    assert font["hmtx"]["A"] == reference["hmtx"]["B"]
    lies = cmap_tables["symbolic_names_lie"]
    assert set(lies) == {(3, 0), (3, 1)}
    assert lies[(3, 0)] == {**honest_sym, 0xF041: "A"}
    assert lies[(3, 1)] == {**honest_uni, 0x41: "uni0041"}

    # symbolic_postname_variant: the honest A glyph is named A.sc; (3,0) honest otherwise (only that table)
    font = programs["symbolic_postname_variant"]
    assert font.getGlyphOrder()[sfb.glyph_id("A")] == "A.sc" and "A" not in font.getGlyphOrder()
    assert _coords(font, "A.sc") == _coords(reference, "A")
    assert set(cmap_tables["symbolic_postname_variant"]) == {(3, 0)}
    assert cmap_tables["symbolic_postname_variant"][(3, 0)] == {**honest_sym, 0xF041: "A.sc"}

    # nonsymbolic_plat0_lie / symbolic_plat0_lie (review finding F1): a LYING (0,3) Unicode table (U+0041 -> the B
    # glyph) beside an honest (3,0), no (3,1) and no (1,0); the identity ToUnicode keeps MuPDF's text at "A"; the
    # (0,3) record is the FIRST subtable of the cmap (the table MuPDF falls back to for a nonsymbolic font)
    for kind in ("nonsymbolic_plat0_lie", "symbolic_plat0_lie"):
        assert set(cmap_tables[kind]) == {(0, 3), (3, 0)}, kind
        assert cmap_tables[kind][(0, 3)] == {**honest_uni, 0x41: "B"}, kind
        assert cmap_tables[kind][(3, 0)] == honest_sym, kind
        assert [(t.platformID, t.platEncID) for t in programs[kind]["cmap"].tables][0] == (0, 3), kind
        assert programs[kind].getGlyphOrder() == reference.getGlyphOrder(), kind
    assert _flags(built["nonsymbolic_plat0_lie"]) & 32 and _flags(built["symbolic_plat0_lie"]) & 4


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


#: slice I1 stage B2, MEASURED 2026-11-01 (HEAD 2acd192 + B1): kind -> (texttrace text, texttrace gids) of "AB".
#: 34 = the A outline, 35 = the B outline, 0 = ``.notdef`` (blank in the builder), EXTRA_GLYPH_GID = the glyph named
#: ``A`` that carries the B outline.  MuPDF selects ONE cmap table (flags&4: (3,0) > (3,1) > (1,0); nonsymbolic:
#: (3,1) > (1,0) > (3,0)) and draws ``.notdef`` when that table lacks the code, whatever another table says.
_TEXTTRACE_AB = {
    "symbolic_mac10": ("AB", (34, 35)),
    "symbolic_mac10_wrongglyph": ("BB", (35, 35)),
    "symbolic_f100": ("��", (0, 0)),  # MuPDF's text for ``.notdef`` is U+FFFD
    "symbolic_30_partial": ("�B", (0, 35)),
    "nonsymbolic_31_partial": ("�B", (0, 35)),
    "nonsymbolic_builtin_conflict": ("AB", (34, 35)),
    "symbolic_names_lie": ("AB", (sfb.EXTRA_GLYPH_GID, 35)),
    "symbolic_postname_variant": ("AB", (34, 35)),
    # the identity ToUnicode keeps the text "AB"; MuPDF falls back to the lying (0,3) (the FIRST subtable) for the
    # nonsymbolic font and draws the B glyph for code 0x41, but selects the honest (3,0) for the symbolic one
    "nonsymbolic_plat0_lie": ("AB", (35, 35)),
    "symbolic_plat0_lie": ("AB", (34, 35)),
}


def test_texttrace_gids_follow_the_cmap_mupdf_uses():
    """Pins the MuPDF texttrace gid of each builder kind (the glyph-identity helper's measured side)."""
    for kind in sfb.KINDS:
        fixture = sfb.build_embedded_simple_fixture(kind, "AB")
        with helpers._measurement_copy(fixture.doc) as measured:
            chars = measured[0].get_texttrace()[0]["chars"]
        if kind in _TEXTTRACE_AB:
            text, gids = _TEXTTRACE_AB[kind]
            assert [char[1] for char in chars] == list(gids), (kind, [char[1] for char in chars])
            assert "".join(chr(char[0]) for char in chars) == text, (kind, [char[0] for char in chars])
            continue
        lies = kind in _LYING_KINDS
        want = [sfb.glyph_id("B" if lies else "A", kind), sfb.glyph_id("B", kind)]
        assert [char[1] for char in chars] == want, (kind, [char[1] for char in chars])
        # the texttrace character is MuPDF's text for the glyph: the ToUnicode CMap wins when there
        # is one (tounicode_lie says A over the B glyph), else the glyph NAME (wrongname says B),
        # else the CODE BYTE of a nameless program (symbolic_post3_wrongglyph reads A over the B
        # outline); never the (3,1) cmap
        # type1_wrongname reads "BB" (the glyph name); type1_emptyglyph reads "AB" over A's gid with no ink
        text = {"symbolic_wrongname": "BB", "type1_wrongname": "BB"}.get(kind, "AB")
        assert "".join(chr(char[0]) for char in chars) == text, kind


def test_texttrace_gids_of_a_type1_program_follow_the_freetype_notdef_swap():
    """The Type1 builder puts ``.notdef`` last in CharStrings; FreeType (hence MuPDF's texttrace) swaps ``.notdef``
    with index 0: the glyph at index 0 (``space``) gets the ``.notdef`` slot and ``.notdef`` is gid 0."""
    fixture = sfb.build_embedded_simple_fixture("type1_builtin", "A B")
    with helpers._measurement_copy(fixture.doc) as measured:
        chars = measured[0].get_texttrace()[0]["chars"]
    assert [(chr(char[0]), char[1]) for char in chars] == [("A", 33), (" ", 95), ("B", 34)]
    assert [sfb.glyph_id(char, "type1_builtin") for char in "A B"] == [33, 95, 34]
    assert sfb.glyph_id("A") == 34  # the TrueType order index is not the Type1 gid
    order = list(_type1(fixture)["CharStrings"])
    assert order.index("A") == 33 and order.index("space") == 0 and order.index(".notdef") == 95


#: kinds whose code 0x41 draws the B outline FOR MUPDF (what the render shows).  symbolic_mac10_wrongglyph and
#: symbolic_names_lie are in; nonsymbolic_builtin_conflict is NOT: its (3,0) table lies but MuPDF reads the honest
#: (1,0) table (nonsymbolic order (3,1) > (1,0) > (3,0)), so a reader that took (3,0) first would draw B.
_LYING_KINDS = (
    "symbolic_wrongname",
    "tounicode_lie",
    "symbolic_post3_wrongglyph",
    "type1_wrongname",
    "symbolic_mac10_wrongglyph",
    "symbolic_names_lie",
    "nonsymbolic_plat0_lie",
    "type1_decoy_vector",
)
#: kinds with a ``.notdef`` slot, by name: the characters of "ABC" that render as the (blank) ``.notdef``
_NOTDEF_KINDS = {
    "symbolic_f100": "ABC",
    "symbolic_30_partial": "A",
    "nonsymbolic_31_partial": "A",
}


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
    if kind in _NOTDEF_KINDS:
        # slice I1 stage B2, named exemptions.  Pixels cannot tell ".notdef drawn" from "nothing drawn" (the builder's
        # .notdef is blank); the texttrace gid 0 above is the evidence that MuPDF reached it.  symbolic_f100: every
        # code is .notdef, so A, B and C all render as the empty page.  The partial kinds: A is .notdef (the empty
        # page) while B and C keep their ink and apart.
        blank = _render(sfb.build_embedded_simple_fixture(kind, " "))
        for char in _NOTDEF_KINDS[kind]:
            assert _differing_pixels(renders[char], blank) == 0, (kind, char)
        for char in set("ABC") - set(_NOTDEF_KINDS[kind]):
            assert _differing_pixels(renders[char], blank) > 0, (kind, char)
        if kind != "symbolic_f100":
            assert _differing_pixels(renders["B"], renders["C"]) > 0, kind
        return
    assert _differing_pixels(renders["A"], renders["C"]) > 0, kind
    assert _differing_pixels(renders["B"], renders["C"]) > 0, kind
    if kind in _LYING_KINDS:
        assert _differing_pixels(renders["A"], renders["B"]) == 0, kind
    else:
        assert _differing_pixels(renders["A"], renders["B"]) > 0, kind
    if kind == "type1_emptyglyph":
        # the glyph A exists but draws nothing: its render IS the empty page, while B and C have ink
        blank = _render(sfb.build_embedded_simple_fixture(kind, " "))
        assert _differing_pixels(renders["A"], blank) == 0, kind
        assert _differing_pixels(renders["B"], blank) > 0 and _differing_pixels(renders["C"], blank) > 0, kind


# ----------------------------------------------------------------------------------------------
# Recorded observations: what the product does at HEAD ("observed, not assumed", design :203)
# ----------------------------------------------------------------------------------------------
def _outcome(build, target: str, replacement: str, *, located: bool, max_tier: int = 1) -> tuple:
    """``("COMMITTED", tier, decision_chain)`` or ``("REJECTED", reason, detail)``: prepare, then commit.

    ``located=False`` calls ``prepare(expected_origin=None, target_bbox=None)`` (the planner's own
    1.35 em quad); ``located=True`` passes the acceptance-shaped origin and box.  The tables below hold
    for BOTH call shapes (:func:`_both_ways`)."""
    doc = build()
    try:
        engine = TieredCommitEngine(doc, max_tier=max_tier)
        arguments = frontier_twins.located_arguments(doc, target) if located else {"expected_origin": None}
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


#: The I1 CONTRACT (plans/true-text-i1.md section 4), rewritten from the HEAD observations of slices I0b/I1-B before
#: any product change; the replacement writes the byte 0x41 ("Level A 2024").  Every honest kind COMMITS at tier 0.
#: Every kind that draws, or may draw, a WRONG glyph for 0x41 is REFUSED ``font_builtin_encoding_unproven`` (G1'): the
#: ToUnicode lie, the wrong name, the nameless wrong glyph, the Type1 wrong name and empty glyph, the (1,0) lie, the
#: names/cmap disagreement, the post-name variant and the route conflict.  The kinds no table maps at all stay
#: ``encoding_failed`` (a missing glyph, decided BEFORE G1'): symbolic_f100 fails the SOURCE encode check (no code of the
#: target is present), the two partial-table kinds fail the REPLACEMENT encode check (the A is not present).
#: ``symbolic_ascii`` COMMITS since I1 (plan 7.1 recommended outcome, design :203): the program proves every glyph.
_UNPROVEN = (
    "REJECTED",
    "font_builtin_encoding_unproven",
    "font /F1 (ABCDEF+TwinSans) cannot prove the glyph of 1 replacement character code(s) through its built-in encoding",
)
_REPLACEMENT_NOT_ENCODABLE = (
    "REJECTED",
    "encoding_failed",
    "replacement contains characters outside the verified simple encoding or the font's glyph set",
)
_KIND_OUTCOMES = {
    "winansi": ("COMMITTED", 0, ("tier0:committed",)),
    "post3_cmap31": ("COMMITTED", 0, ("tier0:committed",)),
    "winansi_nopost": ("COMMITTED", 0, ("tier0:committed",)),
    "macroman": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_ascii": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_wrongname": _UNPROVEN,
    "tounicode_lie": _UNPROVEN,
    "symbolic_post3": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_post3_wrongglyph": _UNPROVEN,
    "type1_builtin": ("COMMITTED", 0, ("tier0:committed",)),
    "type1_standard": ("COMMITTED", 0, ("tier0:committed",)),
    "type1_wrongname": _UNPROVEN,
    "type1_emptyglyph": _UNPROVEN,
    "symbolic_mac10": ("COMMITTED", 0, ("tier0:committed",)),
    "symbolic_mac10_wrongglyph": _UNPROVEN,
    "symbolic_f100": (
        "REJECTED",
        "encoding_failed",
        "reverse encoder does not reproduce the source string bytes",
    ),
    "symbolic_30_partial": _REPLACEMENT_NOT_ENCODABLE,
    "nonsymbolic_31_partial": _REPLACEMENT_NOT_ENCODABLE,
    "nonsymbolic_builtin_conflict": _UNPROVEN,
    "symbolic_names_lie": _UNPROVEN,
    "symbolic_postname_variant": _UNPROVEN,
    "nonsymbolic_plat0_lie": _UNPROVEN,
    "symbolic_plat0_lie": _UNPROVEN,
    "type1_decoy_vector": _UNPROVEN,
}
#: kinds whose target cannot be located by the acceptance-shaped call (``helpers._trace_for`` finds no texttrace
#: text equal to the target: every glyph is ``.notdef``, text U+FFFD); only the bare call shape is observed
_UNLOCATABLE_KINDS = ("symbolic_f100",)
#: the texttrace glyph id at the replaced position (the "B" -> "A" slot) of a committed edit: 34 is the A outline.
#: After I1 every COMMITTED kind commits the honest glyph; the wrong-glyph commits of HEAD (tounicode_lie 35,
#: symbolic_post3_wrongglyph 35, type1_emptyglyph 33 with no ink, symbolic_30_partial a ``.notdef``, symbolic_names_lie
#: the extra glyph) are refusals now.  Type1 gids follow the CharStrings index with FreeType's .notdef swap (A is 33).
_KIND_COMMITTED_GID = {
    "winansi": 34,
    "post3_cmap31": 34,
    "winansi_nopost": 34,
    "macroman": 34,
    "symbolic_ascii": 34,
    "symbolic_post3": 34,
    "symbolic_mac10": 34,
    "type1_builtin": 33,
    "type1_standard": 33,
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
    "winansi_nopost": "F30W",
    "macroman": "F30W",
    "type1_builtin": "F30B",
    "type1_standard": "F30B",
    "type1_wrongname": "F30B",
    "type1_emptyglyph": "F30B",
    "symbolic_mac10": "F30B",
    "symbolic_mac10_wrongglyph": "F30B",
    "symbolic_f100": "F30B",
    "symbolic_30_partial": "F30B",
    "nonsymbolic_31_partial": "F30B",
    "nonsymbolic_builtin_conflict": "F30B",
    "symbolic_names_lie": "F30B",
    "symbolic_postname_variant": "F30B",
    "nonsymbolic_plat0_lie": "F30B",
    "symbolic_plat0_lie": "F30B",
    "type1_decoy_vector": "F30B",
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
    """The I1 contract (plan section 4) per builder kind, for the bare and the acceptance-shaped call.  Before I1 this
    was an observation of HEAD (the first full run corrected two expectations taken from the design)."""
    assert set(_KIND_OUTCOMES) == set(sfb.KINDS)
    for spec in frontier_twins.all_twins():
        kind = spec.twin_id.removeprefix("simple_")
        assert spec.class_id == _KIND_CLASS[kind], spec.twin_id
        if kind in _UNLOCATABLE_KINDS:
            # the acceptance-shaped call cannot locate the target (every glyph is .notdef): pin that, observe the bare shape
            with pytest.raises(AssertionError, match=spec.target):
                _outcome(spec.build, spec.target, spec.replacement, located=True)
            observed = _outcome(spec.build, spec.target, spec.replacement, located=False)
        else:
            observed = _both_ways(spec.build, spec.target, spec.replacement)
        assert observed == _KIND_OUTCOMES[kind], (spec.twin_id, observed)
        assert _label(observed) == spec.expected, spec.twin_id
        if kind in _KIND_COMMITTED_GID:  # "commits a wrong glyph" is asserted, not inferred
            assert _committed_gid(spec, spec.target.index("B")) == _KIND_COMMITTED_GID[kind], kind
        else:
            assert observed[0] == "REJECTED", kind
        # a negative twin is REFUSED by G1' since I1 (engine-pinned: no slice owns it any more)
        if spec.polarity == "negative":
            assert spec.expected == "font_builtin_encoding_unproven" and spec.owned_until_slice is None, spec.twin_id
        else:
            assert spec.owned_until_slice is None, spec.twin_id


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
    assert [spec.twin_id for spec in frontier_twins.ORACLE_TWINS] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "v-b",
        "v-c",
        "v-d",
        "v-type0",
        "v-guard-post3",
        "v-guard-cmap31",
        "v-guard-std14",
        "vi",
        "vii",
        "viii",
        "viii-b",
        "ix",
        "x",
        "xi",
        "xii",
        "xiii",
    ]  # S3b (i-v and the three guards) in front of S3a's vi-xii, then xiii (the token-aware shading gate)


def _right_of(edge_pt: float) -> str:
    """A clip that keeps only the page area left of ``edge_pt``."""
    return f"0 0 {edge_pt:g} 842 re W n"


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
            frontier_twins.prepend_clip(fixture, clip_path)
        return fixture.doc

    return _both_ways(build, text, replacement)


def _x_rule_outcomes() -> tuple:
    """Twin (x): identity_h with a 0.5 pt filled rule at x 133..133.5, past the grown text's right edge
    (132 pt).  Both call shapes are pinned separately: they agree on the reason and the ``raster:``
    detail head, and differ only in the pixel region the probe names (the located box is the tighter)."""

    def build() -> fitz.Document:
        fixture = tb.build_identity_h_fixture()
        tb.append_page_content(fixture, "q 0 g 133 696 0.5 12 re f Q")
        return fixture.doc

    bare = _outcome(build, tb.CJK_TEXT, tb.REPLACEMENT_LONGER, located=False)
    shaped = _outcome(build, tb.CJK_TEXT, tb.REPLACEMENT_LONGER, located=True)
    return bare, shaped


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
        # (v) the tounicode_lie product path is the kind row above: REFUSED by G1' since I1
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
        "xii_gap_clip": _simple_growth("Figure 123", fontsize=6.0, clip_path=frontier_twins.GAP_CLIP),
        # (x) a filled rule 1 pt past the after edge: outside the growth rect (120..132) so the drawing
        # bbox test and the occupancy gate stay quiet, inside halo(V) minus halo(T) (x <= 134), so the
        # raster probe refuses.  Observed at HEAD 9ced903 (the S3a step-0 prediction held).
        "x_rule_past_the_after_edge": _x_rule_outcomes(),
    }
    assert observed == {
        "v": ("REJECTED", "font_builtin_encoding_unproven", _UNPROVEN[2]),
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
        "x_rule_past_the_after_edge": (
            (
                "REJECTED",
                "growth_region_not_blank",
                "raster: growth probe region (164, 170, 179, 198) is not uniform pre-edit",
            ),
            (
                "REJECTED",
                "growth_region_not_blank",
                "raster: growth probe region (164, 173, 179, 196) is not uniform pre-edit",
            ),
        ),
    }


def test_symbolic_ascii_keeps_the_quote_slot_and_non_ascii_replacements_at_encoding_failed():
    """G1' admits the honest (3,0)-only program, but a quote-slot replacement (an unnamed encoding is unknown there:
    StandardEncoding would put quoteright at 0x27) and a non-ASCII replacement stay ``encoding_failed``."""
    spec = frontier_twins.twin("simple_symbolic_ascii")
    for replacement in ("Level ' 2024", "Level ` 2024", "Level é 2024"):
        assert _both_ways(spec.build, spec.target, replacement) == _REPLACEMENT_NOT_ENCODABLE, replacement


def _last_glyph_ink_pixels(clip_path: str | None) -> int:
    """Non-white pixels (2x render of a measurement copy) in the committed tenth glyph's texttrace
    box of "Figure 123" at 6 pt, bare ``prepare``."""
    fixture = sfb.build_embedded_simple_fixture("winansi", "Figure 1", fontsize=6.0)
    if clip_path is not None:
        frontier_twins.prepend_clip(fixture, clip_path)
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
    assert _last_glyph_ink_pixels(frontier_twins.GAP_CLIP) == 0  # the gap clip: committed, blank


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


# ----------------------------------------------------------------------------------------------
# Q12 for Type0: does MuPDF integerise a CID font's /W and /DW widths too?  (S4 Step 0c, decides the residual of a Type0 row)
# ----------------------------------------------------------------------------------------------
_TYPE0_RAW_WIDTHS = (1000.5, 999.4, 1000.6, 1000.0)
#: half UP after the float32 parse, exactly as for a simple font's /Widths
_TYPE0_INTEGERISED = (1001.0, 999.0, 1001.0)


def _type0_advances_in_units(w_literal: str, dw_literal: str | None = None) -> list[float]:
    """The texttrace advances of the four glyphs of ``CJK_TEXT`` at 100 pt (one width unit is 0.1 pt), last one unobservable."""
    fixture = tb.build_identity_h_fixture(tb.CJK_TEXT, fontsize=100.0, origin=(10, 700))
    try:
        tb.set_w_array(fixture, w_literal)
        if dw_literal is not None:
            tb.set_dw(fixture, dw_literal)
        with helpers._measurement_copy(fixture.doc) as measured:
            chars = measured[0].get_texttrace()[0]["chars"]
    finally:
        fixture.doc.close()
    assert len(chars) == len(tb.CJK_TEXT)
    return [(chars[index + 1][2][0] - chars[index][2][0]) / 100.0 * 1000.0 for index in range(len(chars) - 1)]


def test_q12_mupdf_integerises_type0_w_widths():
    """Observed 2026-10-27 (S4 Step 0c, D15 branch I): MuPDF integerises a Type0 width exactly like a /Widths entry: half UP
    after the float32 parse, in the array form ``c [w]``, the range form ``c c w`` and for /DW.  The capability still hands
    the raw floats to the residual formula (``width_of_cid`` never rounds), so the Type0 in-show residual of S4 is the
    simple-font formula over ``width_of_cid``.  Written before the adapter, green on its first run (an observation)."""
    cids = [tb.cid_for(char) for char in tb.CJK_TEXT]
    array = "[ " + " ".join(f"{cid} [ {width} ]" for cid, width in zip(cids, _TYPE0_RAW_WIDTHS, strict=True)) + " ]"
    ranges = "[ " + " ".join(f"{cid} {cid} {width}" for cid, width in zip(cids[:3], _TYPE0_RAW_WIDTHS[:3], strict=True)) + " ]"
    for literal in (array, ranges):
        units = _type0_advances_in_units(literal)
        assert units == pytest.approx(list(_TYPE0_INTEGERISED), abs=0.01), literal
        assert units != pytest.approx(list(_TYPE0_RAW_WIDTHS[:3]), abs=0.01), literal  # NOT the exact widths
    assert _type0_advances_in_units("[ ]", "1000.5") == pytest.approx([1001.0] * 3, abs=0.01)
    assert _type0_advances_in_units("[ ]", "999.4") == pytest.approx([999.0] * 3, abs=0.01)
    fixture = tb.build_identity_h_fixture(tb.CJK_TEXT, fontsize=100.0, origin=(10, 700))
    try:
        tb.set_w_array(fixture, array)
        capability = DocumentFontRegistry(fixture.doc).capability(fixture.doc[0], fixture.resource_name)
        assert capability is not None and capability.cid is not None
        assert [capability.cid.width_of_cid(cid) for cid in cids] == list(_TYPE0_RAW_WIDTHS)
    finally:
        fixture.doc.close()


# ----------------------------------------------------------------------------------------------
# T7 (round-4 lane stage C, D-R4-2): the twin judge names a neighbours pass that paired no glyph
# ----------------------------------------------------------------------------------------------
#: twin vii's page-frame stroke, exactly as its spec in ``frontier_twins._S3A_TWINS`` builds it
_VII_FRAME_STROKE = "q 0.5 w 20 20 555 802 re S Q"


def test_judge_reports_a_neighbours_pass_that_paired_no_glyph(tmp_path):
    """Twin vii rebuilt WITHOUT its far show: the page holds only the edited show, so the neighbours helper passes (the
    target glyphs' ink is checked) with every untouched-glyph leg unexercised.  The judge names that pass (T7), the twin
    mirror of rederive's visible ``glyphs_paired: 0``.  Red first: ``judge`` returned no mismatch for it."""
    vii = next(spec for spec in frontier_twins.ORACLE_TWINS if spec.twin_id == "vii")
    assert "neighbours" in vii.must_pass and vii.paths == {"product"}
    lone = dataclasses.replace(vii, build=frontier_twins._identity_h(raw=_VII_FRAME_STROKE, far_show=False))
    runs = frontier_twins.twin_runs(lone, tmp_path / "lone")
    try:
        (run,) = runs
        assert not isinstance(run, frontier_twins.Refusal)
        # premise: the helper itself passes, checks the target ink and pairs nothing (judge clears the sink per helper)
        assert frontier_twins.ORACLE_HELPERS["neighbours"](run) is None
        assert run.measurements["glyphs_paired"] == 0 and run.measurements["target_glyphs_ink_checked"] >= 1
        mismatches = frontier_twins.judge(lone, runs)
    finally:
        frontier_twins.close_runs(runs)
    assert mismatches == ["vii/product/neighbours: passed without pairing any glyph"]
