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
)

#: kinds with no /Encoding and the symbolic descriptor flag (class F30B)
SYMBOLIC_KINDS: tuple[str, ...] = (
    "symbolic_ascii",
    "symbolic_wrongname",
    "tounicode_lie",
    "symbolic_post3",
    "symbolic_post3_wrongglyph",
)
#: kinds written with post format 3 (no glyph names)
NAMELESS_KINDS: tuple[str, ...] = ("post3_cmap31", "symbolic_post3", "symbolic_post3_wrongglyph")

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

_PRINTABLE = tuple(chr(code) for code in range(FIRST_CHAR, LAST_CHAR + 1))
_NAME = {char: UV2AGL[ord(char)] for char in _PRINTABLE}
_GLYPH_ORDER = [".notdef", *(_NAME[char] for char in _PRINTABLE)]


def glyph_name(char: str) -> str:
    """The AGL glyph name the builder gives ``char``."""
    return _NAME[char]


def glyph_id(char: str) -> int:
    """The glyph index of ``char`` in every built program (one shared glyph order)."""
    return _GLYPH_ORDER.index(_NAME[char])


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
    unicode_map = {ord(char): _NAME[char] for char in _PRINTABLE}
    symbol_map = {0xF000 + ord(char): _NAME[char] for char in _PRINTABLE}
    if kind in ("winansi", "post3_cmap31"):
        return [_cmap_subtable(3, 1, unicode_map)]
    if kind == "symbolic_ascii":
        return [_cmap_subtable(3, 0, symbol_map)]
    if kind == "symbolic_post3":
        return [_cmap_subtable(3, 0, symbol_map), _cmap_subtable(3, 1, unicode_map)]
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
    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(list(_GLYPH_ORDER))
    glyphs = {".notdef": _outline(" ")}
    metrics = {".notdef": (GLYPH_ADVANCE, 0)}
    for char in _PRINTABLE:
        extra = overhang if (overhang and char == OVERHANG_CHAR) else 0
        glyphs[_NAME[char]] = _outline(char, extra)
        metrics[_NAME[char]] = (GLYPH_ADVANCE, glyph_shape(char)[0])
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
    out = BytesIO()
    builder.save(out)
    return out.getvalue()


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
) -> SimpleFixture:
    """Build one page showing ``text`` as a single literal ``Tj`` in an embedded simple font.

    ``text`` must be printable ASCII (the program has exactly those glyphs).  ``widths`` maps a
    character to its declared ``/Widths`` entry, fractional allowed (default
    :data:`GLYPH_ADVANCE`); ``overhang`` is in font units (see the module docstring).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown simple-font kind {kind!r}")
    missing = [char for char in text if char not in _NAME]
    if missing:
        raise ValueError(f"text has characters the builder font lacks: {missing!r}")
    program = build_font_program(kind, overhang=overhang)
    symbolic = kind in SYMBOLIC_KINDS
    head_x_max = TTFont(BytesIO(program))["head"].xMax
    font_dict = (
        f"<< /Type /Font /Subtype /TrueType /BaseFont /{_BASEFONT} "
        f"/FirstChar {FIRST_CHAR} /LastChar {LAST_CHAR} /Widths {_widths_array(widths)} "
        "/FontDescriptor 5 0 R"
    )
    if not symbolic:
        font_dict += " /Encoding /WinAnsiEncoding"
    if kind == "tounicode_lie":
        font_dict += " /ToUnicode 8 0 R"
    font_dict += " >>"
    descriptor = (
        f"<< /Type /FontDescriptor /FontName /{_BASEFONT} "
        f"/Flags {_SYMBOLIC if symbolic else _NONSYMBOLIC} "
        f"/FontBBox [0 {_DESCENT} {max(GLYPH_ADVANCE, head_x_max)} {_ASCENT}] /ItalicAngle 0 "
        f"/Ascent {_ASCENT} /Descent {_DESCENT} /CapHeight 700 /StemV 80 /FontFile2 6 0 R >>"
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
        6: _stream_obj(f"<< /Length {len(program)} /Length1 {len(program)} >>", program),
        7: _stream_obj(f"<< /Length {len(content)} >>", content),
    }
    if kind == "tounicode_lie":
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
