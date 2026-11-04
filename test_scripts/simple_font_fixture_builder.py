"""Synthetic embedded simple-font (TrueType) fixture builder (slice I0b, stage S2).

Builds one-page PDFs whose only text is a single literal ``Tj`` in a hand-authored embedded
``/TrueType`` simple font.  The font program is a ``fontTools.fontBuilder.FontBuilder`` glyf
TrueType whose outlines are plain rectangles, a different rectangle per character, so a wrong
glyph is visible in a rendering and never merely in a name.  Nothing here derives from a real
document.  The PDF objects are assembled as raw bytes (the ``stream_storage_fixtures``
convention) and opened with ``fitz.open(stream=...)``.

The kinds are *adversarial on purpose*; each names one font fact the glyph-identity oracle and
the planner must tell apart (design ``plans/true-text-frontier-design.md`` :197):

``winansi``
    Nonsymbolic, ``/Encoding /WinAnsiEncoding``, a ``(3,1)`` Unicode cmap, post format 2.
``symbolic_ascii``
    Symbolic, no ``/Encoding``, ONLY a ``(3,0)`` cmap over ``F020``-``F07E``; every code reaches
    the glyph whose post name is the character's own AGL name.
``symbolic_wrongname``
    As ``symbolic_ascii`` plus an INJECTIVE ``(3,1)`` lie: code ``0x41`` reaches the glyph NAMED
    ``B`` (drawn as B) while ``(3,1)`` maps U+0041 to that B glyph and U+0042 to the A glyph (injective,
    never a many-to-one table).  The table agrees with the lie in both directions, so a ``cmap_31_reverse``
    leg would PASS this kind (S3b measured it: code 0x41 and U+0041 both reach gid 35); only the post
    name B, which does not lie, catches it, and the glyph-identity oracle gives names precedence.
``tounicode_lie``
    As ``symbolic_ascii`` except that code ``0x41`` reaches the glyph named ``B`` (outline,
    post name and an honest ``(3,1)`` table, where U+0042 reverses to it, all say B) while the
    ``/ToUnicode`` CMap says ``0x41 -> U+0041``: only the ToUnicode lies.
``post3_cmap31``
    Nonsymbolic WinAnsi (class F30W) with post format 3 (no glyph names at all) and a correct
    ``(3,1)`` table: only the cmap reverse leg can prove a glyph's identity.  It guards the S3b
    cmap leg, NOT G1' (whose scope is ``/Encoding`` absent).
``symbolic_post3``
    Symbolic, no ``/Encoding``, post format 3, honest ``(3,0)`` and ``(3,1)`` tables, no
    ToUnicode: a nameless F30B positive guard.
``symbolic_post3_wrongglyph``
    As ``symbolic_post3`` except that ``(3,0)`` sends code ``0x41`` to the B outline (the
    ``(3,1)`` table stays honest): no name and no ToUnicode says otherwise, so MuPDF reads the
    CODE BYTE as the text.  A nameless F30B negative.
``winansi_nopost`` (slice I1, stage B1)
    Exactly ``winansi`` with the ``post`` table deleted from the program (class F30W): a nameless
    program whose only identity source is the ``(3,1)`` cmap (bug1868759 and veraPDF 6-8-3-3 are this shape).
``macroman``
    Nonsymbolic, ``/MacRomanEncoding``, honest ``(1,0)`` and ``(3,1)`` tables, post format 2 (class F30W):
    issue1233's shape.

The Type1 kinds (slice I1, stage B1) embed a hand-built Type1 program as ``/FontFile`` (``/Subtype /Type1``,
descriptor flags 4, NO ``/Encoding``; class F30B).  The program is cleartext + binary eexec + zero trailer
(``/Length1`` ``/Length2`` ``/Length3``); each glyph is a ``T1CharString`` rectangle (the same
:func:`glyph_shape` boxes), and ``.notdef`` is the LAST CharStrings entry, so FreeType's glyph order swaps
``.notdef`` and index 0 (:func:`type1_glyph_id`).

``type1_builtin``
    The built-in encoding vector ``dup <code> /<name> put`` for every printable character.
``type1_standard``
    As ``type1_builtin`` except that the cleartext says ``/Encoding StandardEncoding def`` (codes 0x27 and
    0x60 reach ``quoteright`` / ``quoteleft``, which the program does not have).
``type1_wrongname``
    As ``type1_builtin`` except that the vector sends code ``0x41`` to the glyph named ``B`` (drawn as B).
``type1_emptyglyph``
    As ``type1_builtin`` except that the charstring of glyph ``A`` is ``hsbw endchar``: it exists, is named
    right, and draws nothing.

The cmap-precedence kinds (slice I1, stage B2) all have NO ``/Encoding`` and post format 2 names, the shared glyph
order and the shared outlines unless stated; flags 4 (symbolic) unless stated.  For an embedded simple TrueType with
no ``/Encoding`` MuPDF selects ONE cmap table and reads the code from it, with no per-code fallback (measured
2026-11-01, ``i1_probe_cmaps.py``): flags&4: ``(3,0)`` > ``(3,1)`` > ``(1,0)``; nonsymbolic: ``(3,1)`` > ``(1,0)`` >
``(3,0)``.  In a ``(3,0)`` table the code is read as ``code`` first, then ``0xF000+code``; ``0xF100`` / ``0xF200`` are
never read.  A selected table that lacks the code draws ``.notdef`` although another present table maps it.

``symbolic_mac10``
    ONLY a ``(1,0)`` cmap, honest (the artofwar / bug1946953 shape).
``symbolic_mac10_wrongglyph``
    As ``symbolic_mac10`` except that ``(1,0)`` sends ``0x41`` to the glyph named ``B``.  MuPDF draws B for code
    0x41 (a wrong glyph for every reader).
``symbolic_f100``
    ONLY a ``(3,0)`` cmap at ``0xF100 + code``: MuPDF draws ``.notdef`` for every code (no reader finds a glyph).
``symbolic_30_partial``
    ``(3,0)`` at ``0xF000 + code`` honest but WITHOUT the ``0xF041`` entry, plus an honest ``(3,1)``.  MuPDF draws
    ``.notdef`` for A (the selected ``(3,0)`` lacks it) and the honest glyph for B.
``nonsymbolic_31_partial``
    Flags 32: ``(3,1)`` honest WITHOUT U+0041, plus an honest ``(1,0)``.  MuPDF draws ``.notdef`` for A.
``nonsymbolic_builtin_conflict``
    Flags 32: an honest ``(1,0)`` plus a LYING ``(3,0)`` (``0xF041`` -> the B glyph).  MuPDF selects the honest
    ``(1,0)`` and draws A; a reader that took ``(3,0)`` first (the symbolic order) would draw B.
``symbolic_names_lie``
    The honest A-outline glyph is RENAMED ``uni0041`` (an exact AGL form for A) and ONE extra glyph, appended as the
    last glyph (:data:`EXTRA_GLYPH_GID`) and named ``A``, carries the B outline.  ``(3,0)`` ``0xF041`` -> the extra
    glyph, ``(3,1)`` U+0041 -> the ``uni0041`` glyph; B and every other character are honest everywhere.  MuPDF
    walks ``(3,0)`` and draws B's outline under the name ``A`` (a wrong glyph for MuPDF and for the name reader); the
    program's own ``(3,1)`` table disagrees with the walked glyph's name: the cross-check twin.
``symbolic_postname_variant``
    The honest A glyph is renamed ``A.sc``; ``(3,0)`` honest otherwise (the walk reaches it, but its name is not an
    exact AGL name).

``nonsymbolic_plat0_lie``
    Flags 32 and the identity ``/ToUnicode`` (MuPDF's text then ignores the drawn glyph, as in ``tounicode_lie``): a
    LYING ``(0,3)`` Unicode table (U+0041 -> the B glyph) plus an honest ``(3,0)``.  Neither a ``(3,1)``
    nor a ``(1,0)`` table exists, so MuPDF falls back to the FIRST subtable of the cmap, the ``(0,3)`` lie, and draws B
    for code 0x41 (measured 2026-11-01, review finding F1).
``symbolic_plat0_lie``
    The same two tables (and the same identity ``/ToUnicode``) with flags 4: MuPDF selects the honest ``(3,0)`` and
    draws A; a reader that models only ``(3,0)``/``(1,0)``/``(3,1)`` cannot see the lie, and the routes disagree.

``type1_decoy_vector`` (Type1, flags 4, no ``/Encoding`` key, identity ``/ToUnicode``; review finding F2)
    As ``type1_wrongname`` (the vector sends code 0x41 to the glyph named B) plus a LATER decoy array
    ``/Decoy 256 array dup 65 /A put def`` after the vector's own ``readonly def``: FreeType stops at the vector's
    ``def`` and draws B; a reader that scans every ``dup N /name put`` up to ``eexec`` reads the decoy and sees A.

Which kinds draw a wrong glyph for SOME reader: ``symbolic_mac10_wrongglyph``, ``symbolic_names_lie``,
``nonsymbolic_plat0_lie`` and ``type1_decoy_vector`` for MuPDF; ``nonsymbolic_builtin_conflict`` only for a reader that
selects ``(3,0)`` before ``(1,0)`` and ``symbolic_plat0_lie`` only for one that selects ``(0,3)`` (MuPDF does neither).

MuPDF's text for a simple-font glyph is ToUnicode when present, else the post glyph NAME, else
(nameless program) the CODE BYTE; never the ``(3,1)`` cmap.  Numbers (widths, font size, origin)
are written as exact fixed-point decimals: a ``%g`` rendering keeps six significant digits.

Advances: every glyph advances :data:`GLYPH_ADVANCE` in the program and ``/Widths`` declares
:data:`GLYPH_ADVANCE` for every code of ``[32, 126]`` unless ``widths`` overrides some (MuPDF
integerises ``/Widths``; PITFALLS "MuPDF keeps ``/Widths`` as integers").  ``overhang`` widens
the outline of the glyph ``f`` to ``GLYPH_ADVANCE + overhang`` units while its advance stays
:data:`GLYPH_ADVANCE` (the CMR10-``f`` shape: ``xMax`` beyond the advance); every kind always
carries a real space glyph (empty outline, full advance).
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

import fitz
from fontTools.agl import UV2AGL
from fontTools.fontBuilder import FontBuilder
from fontTools.misc import eexec
from fontTools.misc.psCharStrings import T1CharString
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from test_scripts.stream_storage_fixtures import _assemble_pdf, _stream_obj

KINDS: tuple[str, ...] = (
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
)

#: the TrueType kinds of slice I1 stage B2: no /Encoding, post format 2, a cmap-table pattern per kind
CMAP_PRECEDENCE_KINDS: tuple[str, ...] = (
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
)
#: kinds with NO /Encoding and the NONSYMBOLIC descriptor flag (32): a built-in encoding walk through the cmap
NONSYMBOLIC_NO_ENCODING_KINDS: tuple[str, ...] = (
    "nonsymbolic_31_partial",
    "nonsymbolic_builtin_conflict",
    "nonsymbolic_plat0_lie",
)
#: kinds whose program is a Type1 ``/FontFile`` (class F30B)
TYPE1_KINDS: tuple[str, ...] = (
    "type1_builtin",
    "type1_standard",
    "type1_wrongname",
    "type1_emptyglyph",
    "type1_decoy_vector",
)
#: kinds with no /Encoding and the symbolic descriptor flag (class F30B)
SYMBOLIC_KINDS: tuple[str, ...] = (
    "symbolic_ascii",
    "symbolic_wrongname",
    "tounicode_lie",
    "symbolic_post3",
    "symbolic_post3_wrongglyph",
    *TYPE1_KINDS,
    "symbolic_mac10",
    "symbolic_mac10_wrongglyph",
    "symbolic_f100",
    "symbolic_30_partial",
    "symbolic_names_lie",
    "symbolic_postname_variant",
    "symbolic_plat0_lie",
)
#: kinds that carry the identity ``/ToUnicode`` CMap (``0x41 -> U+0041``): with it MuPDF's text no longer follows the
#: glyph that is drawn, so the engine's read-back verification cannot catch a lie in these kinds (review finding F1/F2)
TOUNICODE_KINDS: tuple[str, ...] = (
    "tounicode_lie",
    "nonsymbolic_plat0_lie",
    "symbolic_plat0_lie",
    "type1_decoy_vector",
)
#: kinds whose program carries no glyph names (post format 3, or no ``post`` table at all)
NAMELESS_KINDS: tuple[str, ...] = (
    "post3_cmap31",
    "symbolic_post3",
    "symbolic_post3_wrongglyph",
    "winansi_nopost",
)
#: TrueType kinds whose ``post`` table is deleted from the program
NO_POST_KINDS: tuple[str, ...] = ("winansi_nopost",)

UNITS_PER_EM = 1000
GLYPH_ADVANCE = 600
FIRST_CHAR = 0x20
LAST_CHAR = 0x7E
#: The glyph whose outline ``overhang`` widens past its advance.
OVERHANG_CHAR = "f"
RESOURCE_NAME = "F1"

_BASEFONT = "ABCDEF+TwinSans"
_ASCENT = 800
_DESCENT = -200
_SYMBOLIC = 4
_NONSYMBOLIC = 32
_PAGE_W = 595
_PAGE_H = 842

#: ``encoding=`` default: "whatever the kind has" (``None`` means NO /Encoding key)
_KIND_DEFAULT: str | None = "<kind default>"
#: the base /Encoding of a nonsymbolic kind that does not write /WinAnsiEncoding
_KIND_ENCODING: dict[str, str] = {"macroman": "MacRomanEncoding"}

_PRINTABLE = tuple(chr(code) for code in range(FIRST_CHAR, LAST_CHAR + 1))
_NAME = {char: UV2AGL[ord(char)] for char in _PRINTABLE}
_GLYPH_ORDER = [".notdef", *(_NAME[char] for char in _PRINTABLE)]
#: ``symbolic_names_lie`` appends ONE glyph named ``A`` (carrying the B outline); its glyph id
EXTRA_GLYPH_GID = len(_GLYPH_ORDER)
_RENAMED_A = {"symbolic_names_lie": "uni0041", "symbolic_postname_variant": "A.sc"}


def _kind_names(kind: str) -> dict[str, str]:
    """``char -> glyph name`` of ``kind``'s TrueType program (the shared AGL names, A renamed where a kind says so)."""
    names = dict(_NAME)
    if kind in _RENAMED_A:
        names["A"] = _RENAMED_A[kind]
    return names


def glyph_name(char: str) -> str:
    """The AGL glyph name the builder gives ``char``."""
    return _NAME[char]


def glyph_id(char: str, kind: str | None = None) -> int:
    """The glyph id MuPDF/FreeType reports for ``char`` in the program of ``kind``.

    ``kind=None`` (or any TrueType kind) is the shared TrueType glyph order index (``.notdef`` first); it is the HONEST
    outline's id even for ``symbolic_names_lie`` (the walk there reaches :data:`EXTRA_GLYPH_GID`).  A Type1
    kind answers :func:`type1_glyph_id` (the CharStrings index with FreeType's ``.notdef`` swap)."""
    if kind in TYPE1_KINDS:
        return type1_glyph_id(char)
    return _GLYPH_ORDER.index(_NAME[char])


#: Type1 CharStrings order: the printable glyphs, then ``.notdef`` LAST (so FreeType's swap is exercised)
_T1_ORDER = [*(_NAME[char] for char in _PRINTABLE), ".notdef"]


def type1_glyph_id(char: str) -> int:
    """FreeType's glyph id of ``char`` in a built Type1 program: its CharStrings index, except that ``.notdef``
    (index ``len - 1``) and index 0 swap places (measured 2026-11-01: order [A, B, .notdef, space] gives
    A=2, B=1, space=3; ``.notdef`` is gid 0)."""
    index = _T1_ORDER.index(_NAME[char])
    return _T1_ORDER.index(".notdef") if index == 0 else index


def glyph_shape(char: str) -> tuple[int, int, int]:
    """``(x_min, x_max, y_max)`` of ``char``'s rectangle outline in font units; ``(0, 0, 0)`` for
    the space.  Pairwise distinct over the printable set, so any two characters render apart."""
    if char == " ":
        return (0, 0, 0)
    code = ord(char)
    return (40 + (code * 7) % 90, 330 + (code * 11) % 230, 240 + (code * 53) % 520)


def _outline(char: str, extra_right: int = 0):
    x_min, x_max, y_max = glyph_shape(char)
    pen = TTGlyphPen(None)
    if x_max:
        x_max += extra_right
        pen.moveTo((x_min, 0))
        pen.lineTo((x_min, y_max))
        pen.lineTo((x_max, y_max))
        pen.lineTo((x_max, 0))
        pen.closePath()
    return pen.glyph()


def _cmap_subtable(platform: int, encoding: int, mapping: Mapping[int, str]) -> CmapSubtable:
    table = CmapSubtable.newSubtable(4)
    table.platformID = platform
    table.platEncID = encoding
    table.language = 0
    table.cmap = dict(mapping)
    return table


def _cmaps(kind: str) -> list[CmapSubtable]:
    names = _kind_names(kind)
    unicode_map = {ord(char): names[char] for char in _PRINTABLE}
    mac_map = dict(unicode_map)
    symbol_map = {0xF000 + ord(char): names[char] for char in _PRINTABLE}
    if kind in ("winansi", "post3_cmap31", "winansi_nopost"):
        return [_cmap_subtable(3, 1, unicode_map)]
    if kind == "macroman":
        return [_cmap_subtable(1, 0, mac_map), _cmap_subtable(3, 1, unicode_map)]
    if kind in ("symbolic_ascii", "symbolic_postname_variant"):
        return [_cmap_subtable(3, 0, symbol_map)]
    if kind == "symbolic_post3":
        return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]
    if kind == "symbolic_mac10":
        return [_cmap_subtable(1, 0, mac_map)]
    if kind == "symbolic_mac10_wrongglyph":
        mac_map[0x41] = "B"
        return [_cmap_subtable(1, 0, mac_map)]
    if kind == "symbolic_f100":
        return [_cmap_subtable(3, 0, {0xF100 + ord(char): names[char] for char in _PRINTABLE})]
    if kind == "symbolic_30_partial":
        del symbol_map[0xF041]
        return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]
    if kind == "nonsymbolic_31_partial":
        del unicode_map[0x41]
        return [_cmap_subtable(3, 1, unicode_map), _cmap_subtable(1, 0, mac_map)]
    if kind == "nonsymbolic_builtin_conflict":
        symbol_map[0xF041] = "B"
        return [_cmap_subtable(1, 0, mac_map), _cmap_subtable(3, 0, symbol_map)]
    if kind == "symbolic_names_lie":
        # (3,0) reaches the extra glyph NAMED "A" (B's outline); (3,1) U+0041 stays on the honest uni0041 glyph
        symbol_map[0xF041] = _NAME["A"]
        return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]
    if kind in ("nonsymbolic_plat0_lie", "symbolic_plat0_lie"):
        # a LYING (0,3) Unicode table (U+0041 -> the B glyph) beside an honest (3,0); fontTools writes (0,3) first
        unicode_map[0x41] = "B"
        return [_cmap_subtable(0, 3, unicode_map), _cmap_subtable(3, 0, symbol_map)]
    # The lies: code 0x41 reaches the B outline through the symbolic table
    symbol_map[0xF041] = "B"
    if kind == "symbolic_wrongname":
        # the Unicode table claims U+0041 for the B outline; injective: U+0042 -> the A outline
        unicode_map[0x41] = "B"
        unicode_map[0x42] = "A"
        return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]
    assert kind in ("tounicode_lie", "symbolic_post3_wrongglyph"), kind
    return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]  # (3,1) honest


def build_font_program(kind: str, *, overhang: int | None = None) -> bytes:
    """The TrueType program of ``kind`` (see the module docstring for what each kind is)."""
    if kind not in KINDS:
        raise ValueError(f"unknown simple-font kind {kind!r}")
    if kind in TYPE1_KINDS:
        return _build_type1_program(kind, overhang=overhang)[0]
    names = _kind_names(kind)
    order = [".notdef", *(names[char] for char in _PRINTABLE)]
    if kind == "symbolic_names_lie":
        order.append(_NAME["A"])  # the extra glyph NAMED "A" (EXTRA_GLYPH_GID)
    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(order)
    glyphs = {".notdef": _outline(" ")}
    metrics = {".notdef": (GLYPH_ADVANCE, 0)}
    for char in _PRINTABLE:
        extra = overhang if (overhang and char == OVERHANG_CHAR) else 0
        glyphs[names[char]] = _outline(char, extra)
        metrics[names[char]] = (GLYPH_ADVANCE, glyph_shape(char)[0])
    if kind == "symbolic_names_lie":
        glyphs[_NAME["A"]] = _outline("B")
        metrics[_NAME["A"]] = (GLYPH_ADVANCE, glyph_shape("B")[0])
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=_ASCENT, descent=_DESCENT)
    builder.setupNameTable({"familyName": "TwinSans", "styleName": "Regular"})
    cmap = newTable("cmap")
    cmap.tableVersion = 0
    cmap.tables = _cmaps(kind)
    builder.font["cmap"] = cmap
    builder.setupOS2(sTypoAscender=_ASCENT, sTypoDescender=_DESCENT, usWinAscent=_ASCENT, usWinDescent=-_DESCENT)
    builder.setupPost(keepGlyphNames=kind not in NAMELESS_KINDS)
    if kind in NO_POST_KINDS:
        del builder.font["post"]
    out = BytesIO()
    builder.save(out)
    return out.getvalue()


_T1_PRIVATE = (
    b"dup /Private 8 dict dup begin\n/RD {string currentfile exch readstring pop} executeonly def\n"
    b"/ND {noaccess def} executeonly def\n/NP {noaccess put} executeonly def\n"
    b"/lenIV 4 def\n/password 5839 def\n/MinFeature {16 16} def\n/BlueValues [] def\n"
    b"/Subrs 0 array\nND\n"
)


def _t1_charstring(char: str | None, extra_right: int = 0) -> bytes:
    """The charstring-encrypted (lenIV 4) charstring of ``char``'s rectangle; ``None`` draws nothing."""
    program: list = [0, GLYPH_ADVANCE, "hsbw"]
    x_min, x_max, y_max = glyph_shape(char) if char is not None else (0, 0, 0)
    if x_max:
        x_max += extra_right
        program += [x_min, 0, "rmoveto", 0, y_max, "rlineto", x_max - x_min, 0, "rlineto", 0, -y_max, "rlineto"]
        program.append("closepath")
    program.append("endchar")
    charstring = T1CharString()
    charstring.program = program
    charstring.compile()
    return eexec.encrypt(b"\x00\x00\x00\x00" + charstring.bytecode, 4330)[0]


def _t1_vector(kind: str) -> dict[int, str]:
    vector = {ord(char): _NAME[char] for char in _PRINTABLE}
    if kind in ("type1_wrongname", "type1_decoy_vector"):
        vector[0x41] = "B"
    return vector


#: ``type1_decoy_vector``: a second 256-entry array after the vector's own ``readonly def`` (not the font's encoding)
_T1_DECOY = b"/Decoy 256 array dup 65 /A put def\n"


def _type1_x_max(overhang: int | None) -> int:
    widest = max(glyph_shape(char)[1] for char in _PRINTABLE)
    return max(GLYPH_ADVANCE, widest + (overhang or 0))


def _build_type1_program(kind: str, *, overhang: int | None = None) -> tuple[bytes, int, int, int]:
    """``(program, Length1, Length2, Length3)`` of a Type1 kind: cleartext, binary eexec, zero trailer."""
    if kind == "type1_standard":
        encoding = b"/Encoding StandardEncoding def\n"
    else:
        encoding = b"/Encoding 256 array\n0 1 255 {1 index exch /.notdef put} for\n"
        for code, name in sorted(_t1_vector(kind).items()):
            encoding += b"dup %d /%s put\n" % (code, name.encode("ascii"))
        encoding += b"readonly def\n"
        if kind == "type1_decoy_vector":
            encoding += _T1_DECOY
    clear = (
        b"%!PS-AdobeFont-1.0: TwinSans 1.0\n"
        b"11 dict begin\n"
        b"/FontName /TwinSans def\n/PaintType 0 def\n/FontType 1 def\n"
        b"/FontMatrix [0.001 0 0 0.001 0 0] readonly def\n"
        + b"/FontBBox {0 %d %d %d} readonly def\n" % (_DESCENT, _type1_x_max(overhang), _ASCENT)
        + encoding
        + b"currentdict end\ncurrentfile eexec\n"
    )
    # the shape of a real program (multicolumn.pdf): the CharStrings dict is built INSIDE the Private block
    parts = [b"2 index /CharStrings %d dict dup begin\n" % len(_T1_ORDER)]
    for name in _T1_ORDER:
        char = next((c for c in _PRINTABLE if _NAME[c] == name), None)
        if kind == "type1_emptyglyph" and name == "A":
            char = None
        extra = overhang if (overhang and char == OVERHANG_CHAR) else 0
        charstring = _t1_charstring(char, extra)
        parts.append(b"/%s %d RD " % (name.encode("ascii"), len(charstring)) + charstring + b" ND\n")
    parts.append(b"end end\nreadonly put\nput\ndup /FontName get exch definefont pop\nmark currentfile closefile\n")
    binary = eexec.encrypt(b"\x00\x00\x00\x00" + _T1_PRIVATE + b"".join(parts), 55665)[0]
    trailer = (b"0" * 64 + b"\n") * 8 + b"cleartomark\n"
    return clear + binary + trailer, len(clear), len(binary), len(trailer)


@dataclass
class SimpleFixture:
    """One synthetic embedded-TrueType page plus the xrefs a test needs."""

    doc: fitz.Document
    kind: str
    resource_name: str
    font_xref: int
    fontfile_xref: int
    content_xref: int
    text: str
    fontsize: float
    origin: tuple[float, float]
    page_number: int = 0

    @property
    def page(self) -> fitz.Page:
        return self.doc[self.page_number]

    def content_bytes(self) -> bytes:
        return self.doc.xref_stream(self.content_xref) or b""


def _number(value: float) -> str:
    """``value`` as an exact fixed-point decimal (never exponent form, never rounded to 6 digits)."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"not a finite number: {value!r}")
    text = format(Decimal(repr(number)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _widths_array(widths: Mapping[str, float] | None) -> str:
    overrides = dict(widths or {})
    unknown = [char for char in overrides if char not in _NAME]
    if unknown:
        raise ValueError(f"widths names characters the font does not have: {unknown!r}")
    return "[" + " ".join(_number(overrides.get(char, GLYPH_ADVANCE)) for char in _PRINTABLE) + "]"


def _tounicode_cmap() -> bytes:
    """An identity ASCII ToUnicode CMap, the lie being that code 0x41 is not drawn as U+0041."""
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CMapName /TwinToUnicode def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<00> <FF>",
        "endcodespacerange",
        f"{len(_PRINTABLE)} beginbfchar",
        *(f"<{ord(char):02X}> <{ord(char):04X}>" for char in _PRINTABLE),
        "endbfchar",
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _literal(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("latin-1") + b")"


def build_embedded_simple_fixture(
    kind: str,
    text: str,
    *,
    fontsize: float = 12.0,
    origin: tuple[float, float] = (72, 700),
    widths: Mapping[str, float] | None = None,
    overhang: int | None = None,
    flags: int | None = None,
    encoding: str | None = _KIND_DEFAULT,
) -> SimpleFixture:
    """Build one page showing ``text`` as a single literal ``Tj`` in an embedded simple font.

    ``text`` must be printable ASCII (the program has exactly those glyphs).  ``widths`` maps a
    character to its declared ``/Widths`` entry, fractional allowed (default
    :data:`GLYPH_ADVANCE`); ``overhang`` is in font units (see the module docstring).

    ``flags`` overrides the descriptor ``/Flags`` (default: 4 for a kind in :data:`SYMBOLIC_KINDS`, else 32) and
    ``encoding`` the ``/Encoding`` key (a base encoding name such as ``"WinAnsiEncoding"``; ``None`` writes no
    ``/Encoding``; default: none for a kind in :data:`SYMBOLIC_KINDS` or :data:`NONSYMBOLIC_NO_ENCODING_KINDS`,
    ``/MacRomanEncoding`` for ``macroman``, ``/WinAnsiEncoding`` otherwise).  The two are independent, and the defaults leave every kind unchanged.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown simple-font kind {kind!r}")
    missing = [char for char in text if char not in _NAME]
    if missing:
        raise ValueError(f"text has characters the builder font lacks: {missing!r}")
    symbolic = kind in SYMBOLIC_KINDS
    if flags is None:
        flags = _SYMBOLIC if symbolic else _NONSYMBOLIC
    if encoding is _KIND_DEFAULT:
        encoding = None if (symbolic or kind in NONSYMBOLIC_NO_ENCODING_KINDS) else _KIND_ENCODING.get(kind, "WinAnsiEncoding")
    if kind in TYPE1_KINDS:
        program, length1, length2, length3 = _build_type1_program(kind, overhang=overhang)
        head_x_max = _type1_x_max(overhang)
        subtype, file_key = "Type1", "FontFile"
        file_dict = f"<< /Length {len(program)} /Length1 {length1} /Length2 {length2} /Length3 {length3} >>"
    else:
        program = build_font_program(kind, overhang=overhang)
        head_x_max = TTFont(BytesIO(program))["head"].xMax
        subtype, file_key = "TrueType", "FontFile2"
        file_dict = f"<< /Length {len(program)} /Length1 {len(program)} >>"
    font_dict = (
        f"<< /Type /Font /Subtype /{subtype} /BaseFont /{_BASEFONT} "
        f"/FirstChar {FIRST_CHAR} /LastChar {LAST_CHAR} /Widths {_widths_array(widths)} "
        "/FontDescriptor 5 0 R"
    )
    if encoding is not None:
        font_dict += f" /Encoding /{encoding}"
    if kind in TOUNICODE_KINDS:
        font_dict += " /ToUnicode 8 0 R"
    font_dict += " >>"
    descriptor = (
        f"<< /Type /FontDescriptor /FontName /{_BASEFONT} "
        f"/Flags {flags} "
        f"/FontBBox [0 {_DESCENT} {max(GLYPH_ADVANCE, head_x_max)} {_ASCENT}] /ItalicAngle 0 "
        f"/Ascent {_ASCENT} /Descent {_DESCENT} /CapHeight 700 /StemV 80 /{file_key} 6 0 R >>"
    )
    content = (
        f"BT /{RESOURCE_NAME} {_number(fontsize)} Tf {_number(origin[0])} {_number(origin[1])} Td ".encode(
            "ascii"
        )
        + _literal(text)
        + b" Tj ET"
    )
    bodies: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /{RESOURCE_NAME} 4 0 R >> >> /Contents 7 0 R >>"
        ).encode("ascii"),
        4: font_dict.encode("ascii"),
        5: descriptor.encode("ascii"),
        6: _stream_obj(file_dict, program),
        7: _stream_obj(f"<< /Length {len(content)} >>", content),
    }
    if kind in TOUNICODE_KINDS:
        cmap = _tounicode_cmap()
        bodies[8] = _stream_obj(f"<< /Length {len(cmap)} >>", cmap)
    doc = fitz.open(stream=_assemble_pdf(bodies), filetype="pdf")
    return SimpleFixture(
        doc=doc,
        kind=kind,
        resource_name=RESOURCE_NAME,
        font_xref=4,
        fontfile_xref=6,
        content_xref=7,
        text=text,
        fontsize=float(fontsize),
        origin=(float(origin[0]), float(origin[1])),
    )
