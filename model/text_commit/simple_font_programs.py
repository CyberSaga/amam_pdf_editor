"""Proof that an embedded simple font's PROGRAM itself says which glyph a code draws (slice I1, G1').

A simple font with no ``/Encoding`` is drawn through the encoding BUILT INTO its embedded program: the
renderer maps the byte straight to a glyph with a cmap (TrueType) or the Type1 encoding vector, and no PDF
object says which character that glyph is.  ``/ToUnicode``, the extracted text and ``fitz.Font.has_glyph``
are all derived from the same machinery and cannot contradict it, so a program that draws the wrong glyph for
a byte is invisible to every text-based check (docs/PITFALLS.md, "MuPDF reads a simple TrueType glyph's text
from ToUnicode ...").  This module reads the program's own tables, with no fitz and no fontTools (``model/``
never imports fontTools: ``test_scripts/test_layer_boundaries.py``), and answers two questions per code:

``present(code)``
    EVERY cmap subtable the program carries, on any platform / encoding, reaches a real glyph for ``code`` (a ``(3,0)``
    subtable at ``code`` then ``0xF000 + code``, every other subtable at ``code``; the Type1 encoding vector).  MuPDF
    selects ONE table (for a font with no ``/Encoding``: flags&4 ``(3,0)`` > ``(3,1)`` > ``(1,0)`` > the FIRST
    subtable of the cmap, whatever its platform; nonsymbolic ``(3,1)`` > ``(1,0)`` > the FIRST subtable, measured
    2026-11-01) and has no per-code fallback (a selected table that lacks the code draws ``.notdef`` although another
    table maps it), so a code a present table does not map is NOT present.  The reader does not model that choice:
    every subtable is a route.  A subtable in a format the reader does not implement, or a repeated
    ``(platform, encoding)`` pair, makes the whole program ``unproven:unreadable``.  No agreement between the
    tables is required here: a conflicting font has the glyph, so it must reach :meth:`proves` and be refused
    with the specific reason, not fail as a missing glyph.
``proves(code, char)``
    ``present`` AND the glyph is, by the program's OWN evidence, the character: every table reaches the same
    glyph, its glyph name is an exact AGL name for ``char`` (no other glyph carries that name), a ``(3,1)``
    table sends ``char`` to the same glyph, a nameless program has that ``(3,1)`` table, and a non-space
    glyph draws something.

A program the module cannot vouch for yields an ``unproven:<why>`` proof whose ``present`` is False for every
code (the font then refuses ``encoding_failed`` at the first encode check, like an unreadable face).

Blind spots, known and accepted (plans/true-text-i1.md 6.4): a program that lies consistently in its names AND
every table; "outline" is operator presence, not ink (``rmoveto closepath`` counts); a Type1 glyph built only
from ``seac`` or flex has no outline here and is refused.
"""
from __future__ import annotations

import bisect
import logging
import re
import struct
from collections import Counter
from collections.abc import Callable

from model.text_commit import sfnt

logger = logging.getLogger(__name__)

#: One home with ``cid_fonts`` (``sfnt.MAX_FONT_PROGRAM_BYTES``); a module global so a test may patch it.
_MAX_FONT_PROGRAM_BYTES = sfnt.MAX_FONT_PROGRAM_BYTES
#: A Type1 program is decrypted byte by byte in Python: bound the cost (real programs are well under 1 MiB).
_MAX_TYPE1_PROGRAM_BYTES = 4 << 20

# The AGL names of printable ASCII, 0x20-0x7E (parity-tested against ``fontTools.agl.UV2AGL``).
_AGL_ASCII: dict[int, str] = {
    0x20 + index: name
    for index, name in enumerate(
        (
            "space exclam quotedbl numbersign dollar percent ampersand quotesingle parenleft parenright "
            "asterisk plus comma hyphen period slash zero one two three four five six seven eight nine "
            "colon semicolon less equal greater question at "
            "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z "
            "bracketleft backslash bracketright asciicircum underscore grave "
            "a b c d e f g h i j k l m n o p q r s t u v w x y z "
            "braceleft bar braceright asciitilde"
        ).split()
    )
}

# StandardEncoding over 0x20-0x7E: the AGL names except quoteright / quoteleft in the quote slots.
_STANDARD_ASCII: dict[int, str] = {**_AGL_ASCII, 0x27: "quoteright", 0x60: "quoteleft"}

# The 258 glyph names of the Macintosh standard order (``post`` formats 1.0 and 2.0).
_MAC_GLYPH_NAMES: tuple[str, ...] = tuple(
    (
        ".notdef .null nonmarkingreturn space exclam quotedbl numbersign dollar percent ampersand quotesingle "
        "parenleft parenright asterisk plus comma hyphen period slash zero one two three four five six seven "
        "eight nine colon semicolon less equal greater question at A B C D E F G H I J K L M N O P Q R S T U "
        "V W X Y Z bracketleft backslash bracketright asciicircum underscore grave a b c d e f g h i j k l m "
        "n o p q r s t u v w x y z braceleft bar braceright asciitilde Adieresis Aring Ccedilla Eacute Ntilde "
        "Odieresis Udieresis aacute agrave acircumflex adieresis atilde aring ccedilla eacute egrave "
        "ecircumflex edieresis iacute igrave icircumflex idieresis ntilde oacute ograve ocircumflex odieresis "
        "otilde uacute ugrave ucircumflex udieresis dagger degree cent sterling section bullet paragraph "
        "germandbls registered copyright trademark acute dieresis notequal AE Oslash infinity plusminus "
        "lessequal greaterequal yen mu partialdiff summation product pi integral ordfeminine ordmasculine "
        "Omega ae oslash questiondown exclamdown logicalnot radical florin approxequal Delta guillemotleft "
        "guillemotright ellipsis nonbreakingspace Agrave Atilde Otilde OE oe endash emdash quotedblleft "
        "quotedblright quoteleft quoteright divide lozenge ydieresis Ydieresis fraction currency "
        "guilsinglleft guilsinglright fi fl daggerdbl periodcentered quotesinglbase quotedblbase perthousand "
        "Acircumflex Ecircumflex Aacute Edieresis Egrave Iacute Icircumflex Idieresis Igrave Oacute "
        "Ocircumflex apple Ograve Uacute Ucircumflex Ugrave dotlessi circumflex tilde macron breve dotaccent "
        "ring cedilla hungarumlaut ogonek caron Lslash lslash Scaron scaron Zcaron zcaron brokenbar Eth eth "
        "Yacute yacute Thorn thorn minus multiply onesuperior twosuperior threesuperior onehalf onequarter "
        "threequarters franc Gbreve gbreve Idotaccent Scedilla scedilla Cacute cacute Ccaron ccaron dcroat"
    ).split()
)

_UNI_FORM = re.compile(r"uni([0-9A-F]{4})")
_U_FORM = re.compile(r"u([0-9A-F]{4,6})")


def _is_agl_name_of(name: str, char: str) -> bool:
    """True when ``name`` is an EXACT glyph name for the single character ``char``: its AGL name (printable
    ASCII), ``uniXXXX`` or ``uXXXX[XX]``.  A ``.suffix`` variant, a ligature or a multi-character name is not."""
    if len(char) != 1:
        return False
    code_point = ord(char)
    if _AGL_ASCII.get(code_point) == name:
        return True
    match = _UNI_FORM.fullmatch(name) or _U_FORM.fullmatch(name)
    return match is not None and int(match.group(1), 16) == code_point


class _Unproven(Exception):
    """A program the module reads but cannot vouch for (carries the ``unproven:<why>`` reason)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ======================================================================== TrueType (sfnt)


def _cmap_lookup(data: bytes, base: int, end: int) -> Callable[[int], int]:
    """A ``code -> gid`` function (0 = unmapped) over the cmap subtable at ``base`` (formats 0, 4, 6, 12).

    A subtable FreeType's validator would DROP (a length field shorter than the table it describes, a segment that
    starts after it ends, overlapping format-12 groups) or search linearly instead of bisecting (unsorted format-4
    segments) is not a table the reader can vouch for: it raises ``ValueError`` and the whole program is
    ``unproven:unreadable``.  A nameless program whose only subtables FreeType drops draws ``.notdef`` for every
    code, and a bisect over an unsorted table finds a different segment than FreeType's linear search."""
    (fmt,) = struct.unpack_from(">H", data, base)
    if fmt == 0:
        (length,) = struct.unpack_from(">H", data, base + 2)
        if length < 262 or base + length > end:
            raise ValueError("cmap format 0 length field is inconsistent with the table")
        array = data[base + 6 : base + 6 + 256]
        return lambda code: array[code] if 0 <= code < 256 else 0
    if fmt == 6:
        length, _language, first, count = struct.unpack_from(">HHHH", data, base + 2)
        if length < 10 + 2 * count or base + length > end:
            raise ValueError("cmap format 6 length field is inconsistent with the table")
        glyphs = struct.unpack_from(f">{count}H", data, base + 10)
        return lambda code: glyphs[code - first] if first <= code < first + count else 0
    if fmt == 4:
        (length,) = struct.unpack_from(">H", data, base + 2)
        (seg_x2,) = struct.unpack_from(">H", data, base + 6)
        segments = seg_x2 // 2
        end_pos = base + 14
        start_pos = end_pos + seg_x2 + 2  # endCode[], reservedPad, startCode[]
        delta_pos = start_pos + seg_x2
        range_pos = delta_pos + seg_x2
        if seg_x2 % 2 or length < 16 + 4 * seg_x2 or range_pos + seg_x2 > end:
            raise ValueError("cmap format 4 is truncated")
        end_codes = struct.unpack_from(f">{segments}H", data, end_pos)
        start_codes = struct.unpack_from(f">{segments}H", data, start_pos)
        deltas = struct.unpack_from(f">{segments}H", data, delta_pos)
        range_offsets = struct.unpack_from(f">{segments}H", data, range_pos)
        if not segments or end_codes[-1] != 0xFFFF:
            raise ValueError("the last cmap format 4 segment does not end at 0xFFFF")
        for index in range(segments):
            first_code, last_code = start_codes[index], end_codes[index]
            if first_code > last_code:
                raise ValueError("a cmap format 4 segment starts after it ends")
            if index and (last_code <= end_codes[index - 1] or first_code < start_codes[index - 1]):
                raise ValueError("cmap format 4 segments are not sorted")  # FreeType searches them linearly
            offset = range_offsets[index]
            if offset not in (0, 0xFFFF) and not (index == segments - 1 and first_code == last_code == 0xFFFF):
                address = range_pos + 2 * index + offset
                if address < range_pos + seg_x2 or address + 2 * (last_code - first_code + 1) > end:
                    raise ValueError("a cmap format 4 segment points outside the glyph id array")

        def lookup4(code: int) -> int:
            if not 0 <= code <= 0xFFFF:
                return 0
            index = bisect.bisect_left(end_codes, code)
            if index >= segments or start_codes[index] > code:
                return 0
            offset = range_offsets[index]
            if offset == 0xFFFF:
                return 0
            if offset == 0:
                return (code + deltas[index]) & 0xFFFF
            address = range_pos + 2 * index + offset + 2 * (code - start_codes[index])
            if address + 2 > end:
                return 0
            (glyph,) = struct.unpack_from(">H", data, address)
            return 0 if glyph == 0 else (glyph + deltas[index]) & 0xFFFF

        return lookup4
    if fmt == 12:
        (length,) = struct.unpack_from(">I", data, base + 4)
        (groups,) = struct.unpack_from(">I", data, base + 12)
        if length < 16 + 12 * groups or base + length > end:
            raise ValueError("cmap format 12 is truncated")
        values = struct.unpack_from(f">{3 * groups}I", data, base + 16)
        starts, ends, first_glyphs = values[0::3], values[1::3], values[2::3]
        for index in range(groups):
            if starts[index] > ends[index] or (index and starts[index] <= ends[index - 1]):
                raise ValueError("cmap format 12 groups are not sorted and disjoint")  # FreeType drops the table

        def lookup12(code: int) -> int:
            index = bisect.bisect_left(ends, code)
            if index >= groups or starts[index] > code:
                return 0
            return first_glyphs[index] + code - starts[index]

        return lookup12
    raise ValueError(f"unsupported cmap format {fmt}")


class _PostNames:
    """The bytes a post 2.0 name read needs: the table plus up to 255 bytes after it, and the table's own length."""

    __slots__ = ("data", "length")

    def __init__(self, data: bytes, length: int) -> None:
        self.data = data
        self.length = length


class _TrueTypeProgram:
    """The facts :class:`BuiltinGlyphProof` needs from one sfnt program (read lazily, memoised)."""

    def __init__(self, data: bytes) -> None:
        # the directory walk is ``sfnt``'s (first in-range entry wins, ttcf refused, head >= 54 in every entry); a
        # cmap or post entry past the end is absent there, as MuPDF reads it, and maxp/head/loca/glyf must survive
        tables = sfnt.read_glyph_tables(data)
        self.num_glyphs = tables.num_glyphs
        self._long_loca = tables.long_loca

        # nothing below keeps ``data`` (the whole program) alive: the cmap table and the post 2.0 names are COPIED
        # (a ``memoryview`` slice would pin the buffer), and the outline flags are read once, at the end
        self.cmaps: dict[tuple[int, int], Callable[[int], int]] = {}
        cmap = tables.directory.slot(b"cmap")
        if cmap is not None and cmap.length >= 4:
            cmap_bytes = cmap.copy(data)  # every offset below is relative to the table, as ``end`` is
            (subtables,) = struct.unpack_from(">H", cmap_bytes, 2)
            if 4 + 8 * subtables > len(cmap_bytes):
                raise ValueError("truncated cmap directory")
            for index in range(subtables):
                platform, encoding, offset = struct.unpack_from(">HHI", cmap_bytes, 4 + 8 * index)
                key = (platform, encoding)
                # EVERY subtable is a route (MuPDF may fall back to the first one, whatever its platform): a format
                # the reader lacks raises inside ``_cmap_lookup`` and a repeated pair raises here, both unreadable
                if key in self.cmaps:
                    raise ValueError("duplicate cmap subtable")
                if offset + 4 > len(cmap_bytes):
                    raise ValueError("cmap subtable offset past the table")
                self.cmaps[key] = _cmap_lookup(cmap_bytes, offset, len(cmap_bytes))

        self._names_kind = "none"
        self._post_names: _PostNames | None = None
        post = tables.directory.slot(b"post")
        if post is not None:
            if post.length < 32:
                raise ValueError("post header is truncated")
            (version,) = struct.unpack_from(">I", data, post.offset)
            if version == 0x00030000:
                pass
            elif version == 0x00010000:
                if self.num_glyphs > 258:
                    raise _Unproven("post_format")
                self._names_kind = "mac"
            elif version == 0x00020000:
                if post.length < 34:
                    raise ValueError("post 2.0 is truncated")
                self._names_kind = "indexed"
                # the final Pascal string may read up to 255 bytes past the table (its length byte is in range): keep
                # that tail, and the loop bound at the table's own length
                self._post_names = _PostNames(post.copy(data, tail=255), post.length)
            else:  # 2.5, 4.0 and anything else: the glyph order is not the plain table
                raise _Unproven("post_format")
        self._names: list[str] | None = None
        self._name_counts: Counter[str] | None = None
        self._outlines = self._reachable_outlines(data, tables)

    def _reachable_outlines(self, data: bytes, tables: sfnt.GlyphTables) -> dict[int, bool]:
        """``gid -> numberOfContours != 0`` for the glyphs a lookup can reach (the routes of codes 0..255).

        Enough for ``proves``: ``BuiltinGlyphProof.present`` clamps a code to 0..255 and ``proves`` asks ``outline`` only
        about a route glyph.  Every glyph of the program would bring back the per-glyph loop the Type0 reader dropped
        from the click path.  A composite is -1 and counts; a zero-length record is none; an unreadable one is none."""
        fmt, width, scale = (">II", 4, 1) if tables.long_loca else (">HH", 2, 2)  # (format, bytes per entry, offset scale)
        glyf_offset, glyf_length = tables.glyf.offset, tables.glyf.length
        flags: dict[int, bool] = {}
        for code in range(256):
            for gid in self.route_gids(code):
                if gid in flags or not 0 < gid < self.num_glyphs:
                    continue
                result = False
                try:
                    start, end = struct.unpack_from(fmt, data, tables.loca.offset + gid * width)
                    start, end = start * scale, end * scale
                    if end - start >= 2 and end <= glyf_length:
                        (contours,) = struct.unpack_from(">h", data, glyf_offset + start)
                        result = contours != 0
                except (struct.error, IndexError):
                    pass
                flags[gid] = result
        return flags

    @property
    def has_names(self) -> bool:
        return self._names_kind != "none"

    def _glyph_names(self) -> list[str]:
        """Glyph names by gid (``""`` where the program names none); all ``""`` for a program it cannot read."""
        if self._names is None:
            names = [""] * self.num_glyphs
            try:
                if self._names_kind == "mac":
                    names = list(_MAC_GLYPH_NAMES[: self.num_glyphs])
                elif self._names_kind == "indexed":
                    assert self._post_names is not None
                    post, length = self._post_names.data, self._post_names.length
                    (declared,) = struct.unpack_from(">H", post, 32)
                    count = min(declared, self.num_glyphs)  # fontTools clamps a bogus count to maxp
                    available = max(0, min(count, (length - 34) // 2))
                    indices = struct.unpack_from(f">{available}H", post, 34)
                    extra: list[str] = []
                    cursor, end = 34 + 2 * count, length
                    while cursor < end:
                        size = post[cursor]
                        extra.append(post[cursor + 1 : cursor + 1 + size].decode("latin-1"))
                        cursor += 1 + size
                    for gid, index in enumerate(indices):
                        if index < 258:
                            names[gid] = _MAC_GLYPH_NAMES[index]
                        elif index - 258 < len(extra):
                            names[gid] = extra[index - 258]
            except (struct.error, IndexError, ValueError):
                logger.debug("post glyph names unreadable", exc_info=True)
                names = [""] * self.num_glyphs
            self._names = names
        return self._names

    def name_of(self, gid: int) -> str:
        names = self._glyph_names()
        return names[gid] if 0 <= gid < len(names) else ""

    def name_is_unique(self, name: str) -> bool:
        if self._name_counts is None:
            self._name_counts = Counter(name for name in self._glyph_names() if name)
        return self._name_counts[name] == 1

    def outline(self, gid: int) -> bool:
        """``numberOfContours != 0`` of the glyph record (a composite is -1 and counts; a zero-length record is none).

        Read at construction for the glyphs a lookup can reach (``_reachable_outlines``); any other gid is False."""
        return self._outlines.get(gid, False)

    def route_gids(self, code: int) -> list[int]:
        """The glyph each cmap subtable of the program reaches for ``code`` (0 = that table does not map it)."""
        gids: list[int] = []
        for key, table in self.cmaps.items():
            gid = table(code)
            if key == (3, 0) and not gid:
                gid = table(0xF000 + code)
            gids.append(gid)
        return gids

    def present(self, code: int) -> bool:
        gids = self.route_gids(code)
        return bool(gids) and all(0 < gid < self.num_glyphs for gid in gids)

    def proves(self, code: int, char: str) -> bool:
        """Precondition: ``present(code)`` (the facade checks it first), so every route reaches a real glyph."""
        gids = self.route_gids(code)
        if len(set(gids)) != 1:
            return False
        gid = gids[0]
        if self.has_names:
            name = self.name_of(gid)
            if not _is_agl_name_of(name, char) or not self.name_is_unique(name):
                return False
        unicode_table = self.cmaps.get((3, 1))
        if unicode_table is None:
            if not self.has_names:
                return False
        elif unicode_table(ord(char)) != gid:
            return False
        return char.isspace() or self.outline(gid)


# ============================================================================ Type1

_EEXEC_KEY = 55665
_CHARSTRING_KEY = 4330
_MAX_SUBR_DEPTH = 8
_MAX_SCAN_STEPS = 20000

#: the ONLY text admitted between ``/Encoding 256 array`` and the ``def`` that closes it (FreeType's tokeniser reads
#: radix integers, comments, strings and bare ``<integer> /<name>`` pairs there that a looser grammar would skip):
#: the optional fill loop, then ``dup <decimal> /<name> put`` triples, then ``readonly def`` / ``def``
_VECTOR_LOOP = re.compile(rb"\s*0\s+1\s+255\s+\{\s*1\s+index\s+exch\s+/\.notdef\s+put\s*\}\s+for(?![^\s/\[\]{}()<>%])")
_VECTOR_TRIPLE = re.compile(rb"\s*dup\s+([0-9]+)\s*/([^\s/\[\]{}()<>%]+)\s+put(?![^\s/\[\]{}()<>%])")
_VECTOR_CLOSE = re.compile(rb"\s*(?:readonly\s+)?def(?![^\s/\[\]{}()<>%])")
_STANDARD_ENCODING_DEF = re.compile(rb"\s+StandardEncoding\s+def")
#: the ``/Encoding`` key as a whole name (``/EncodingX`` is another key), the ``256 array`` that opens the vector and
#: the standalone ``def`` token that closes it (``/def`` is a glyph NAME: it follows a ``/``, not a delimiter)
_ENCODING_KEY = re.compile(rb"/Encoding(?![^\s/\[\]{}()<>%])")
_ENCODING_ARRAY = re.compile(rb"\s*\d+\s+array(?![^\s/\[\]{}()<>%])")
_PRIVATE_KEY = re.compile(rb"/Private(?![^\s/\[\]{}()<>%])")
_CHARSTRINGS_HEADER = re.compile(rb"/CharStrings\s+\d+\s+dict\s+dup\s+begin")
_CHARSTRING_ENTRY = re.compile(rb"\s*/(\S+)\s+(\d+)\s+\S+\s")
_SUBR_ENTRY = re.compile(rb"\s*dup\s+(\d+)\s+(\d+)\s+\S+\s")
_ENTRY_END = re.compile(rb"[ \t\r\n]*(?:noaccess[ \t\r\n]+(?:def|put)|ND|NP|\|-|\|)?")
#: every ``/lenIV`` token, and the one spelling the reader admits (a plain decimal integer, then ``def``)
_LEN_IV_TOKEN = re.compile(rb"/lenIV(?![^\s/\[\]{}()<>%])")
_LEN_IV_DEF = re.compile(rb"/lenIV[ \t\r\n]+([0-9]{1,3})[ \t\r\n]+def(?![^\s/\[\]{}()<>%])")
_HEX_RUN = re.compile(rb"[0-9A-Fa-f]*")

#: Type1 charstring operators that put ink on the path: rlineto, hlineto, vlineto, rrcurveto, closepath,
#: vhcurveto, hvcurveto.
_DRAWING_OPS = frozenset({5, 6, 7, 8, 9, 30, 31})


def _t1_decrypt(data: bytes, key: int) -> bytes:
    out = bytearray(len(data))
    for index, cipher in enumerate(data):
        out[index] = cipher ^ (key >> 8)
        key = ((cipher + key) * 52845 + 22719) & 0xFFFF
    return bytes(out)


def _read_entries(
    plain: bytes, position: int, entry: re.Pattern[bytes], key: Callable[[re.Match[bytes]], object], *, unique: bool
) -> tuple[dict, int]:
    """The ``(start, stop)`` spans of the binary entries that follow ``position`` (CharStrings ``/name len RD ...``
    or Subrs ``dup i len RD ...``), keyed by ``key(match)``, and the position after the last one.  An entry that runs
    past the section raises; a repeated key raises when ``unique`` and otherwise keeps the last definition."""
    spans: dict = {}
    while True:
        match = entry.match(plain, position)
        if match is None:
            return spans, position
        start = match.end()
        stop = start + int(match.group(2))
        if stop > len(plain):
            raise ValueError("an entry runs past the eexec section")
        name = key(match)
        if unique and name in spans:
            raise ValueError("duplicate entry")
        spans[name] = (start, stop)
        position = _ENTRY_END.match(plain, stop).end()  # type: ignore[union-attr]


class _ScanState:
    __slots__ = ("done", "ps_stack", "stack", "steps")

    def __init__(self) -> None:
        self.stack: list[int | None] = []
        self.ps_stack: list[int | None] = []
        self.steps = _MAX_SCAN_STEPS
        self.done = False


class _Type1Program:
    """The facts :class:`BuiltinGlyphProof` needs from one Type1 program (charstrings decrypted lazily)."""

    def __init__(self, data: bytes) -> None:
        marker = data.find(b"eexec")
        if marker < 0:
            raise ValueError("no eexec section")
        clear = data[:marker]
        cursor = marker + 5
        while cursor < len(data) and data[cursor] in b" \t\r\n":
            cursor += 1
        body = data[cursor:]
        if len(body) < 4:
            raise ValueError("empty eexec section")
        if all(byte in b"0123456789abcdefABCDEF" for byte in body[:4]):
            digits = body.translate(None, b" \t\r\n")
            run = _HEX_RUN.match(digits)
            digits = run.group(0) if run else b""
            digits = digits[: len(digits) - len(digits) % 2]
            if len(digits) < 8:
                raise _Unproven("hex_eexec_unreadable")
            try:
                body = bytes.fromhex(digits.decode("ascii"))
            except ValueError as exc:
                raise _Unproven("hex_eexec_unreadable") from exc
        self._plain = plain = _t1_decrypt(body, _EEXEC_KEY)[4:]

        # The vector is ONLY the text between ``/Encoding 256 array`` and the ``def`` (or ``readonly def``) that closes
        # it, as FreeType reads it: a later array in the cleartext (``/Decoy 256 array dup 65 /A put def``) is not the
        # encoding.  The text in between must be EXACTLY the optional fill loop and ``dup <decimal> /<name> put``
        # triples (a whitelist: FreeType also reads radix codes, bare ``<integer> /<name>`` pairs and comments between
        # the tokens of a triple, and stops at a ``]``; and the regex of a looser grammar sees entries inside a comment
        # or a string that FreeType skips).  Two ``/Encoding`` definitions, a code assigned twice inside the vector, or
        # an ``/Encoding`` token inside the eexec section (FreeType honours it until ``/Private``) are not a program the
        # reader can vouch for.
        keys = list(_ENCODING_KEY.finditer(clear))
        if not keys:
            raise ValueError("no /Encoding")
        if len(keys) > 1:
            raise ValueError("more than one /Encoding definition")
        tail = clear[keys[0].end() :]
        self._encoding: dict[int, str]
        array = _ENCODING_ARRAY.match(tail)
        if _STANDARD_ENCODING_DEF.match(tail):
            self._encoding = _STANDARD_ASCII
        elif array is None:  # a predefined encoding other than StandardEncoding: the reader claims no code
            self._encoding = {}
        else:
            vector: dict[int, str] = {}
            at = array.end()
            fill = _VECTOR_LOOP.match(tail, at)
            if fill is not None:
                at = fill.end()
            while True:
                triple = _VECTOR_TRIPLE.match(tail, at)
                if triple is None:
                    break
                code = int(triple.group(1))
                if code in vector:
                    raise ValueError("a code is assigned twice in the /Encoding vector")
                vector[code] = triple.group(2).decode("latin-1")
                at = triple.end()
            if _VECTOR_CLOSE.match(tail, at) is None:
                raise ValueError("the /Encoding vector holds something other than dup/put triples")
            self._encoding = {code: name for code, name in vector.items() if code <= 255}

        header = _CHARSTRINGS_HEADER.search(plain)
        if header is None:
            raise ValueError("no CharStrings dictionary")
        # FreeType honours a font-dict ``/Encoding`` in the eexec section until it reads ``/Private`` and ignores it
        # after: an ``/Encoding`` before the first ``/Private`` is a vector the cleartext scan did not see.  A comment
        # or string before ``/Private`` could hide where FreeType's ``/Private`` really is, so none is admitted there.
        private_at = _PRIVATE_KEY.search(plain, 0, header.start())
        if private_at is None:
            raise ValueError("no /Private before the CharStrings dictionary")
        prefix = plain[: private_at.start()]
        if _ENCODING_KEY.search(prefix) or any(byte in prefix for byte in b"%("):
            raise ValueError("an /Encoding (or a comment / string) before /Private in the eexec section")
        # EXACTLY one ``/lenIV <decimal> def`` (or none: FreeType's default 4).  A radix number (``8#4``), a second
        # definition (FreeType takes the last, a first-match regex the first) or a non-integer is read differently by
        # FreeType than by a regex, and a wrong lenIV skips the wrong bytes of every charstring.
        len_iv_tokens = list(_LEN_IV_TOKEN.finditer(plain, 0, header.start()))
        self._len_iv = 4
        if len_iv_tokens:
            len_iv_def = _LEN_IV_DEF.match(plain, len_iv_tokens[0].start())
            if len(len_iv_tokens) > 1 or len_iv_def is None or int(len_iv_def.group(1)) > 255:
                raise ValueError("lenIV is not defined exactly once as a plain decimal integer")
            self._len_iv = int(len_iv_def.group(1))

        # a duplicate glyph name is unreadable (FreeType and a dict disagree on which wins)
        self._ranges, position = _read_entries(plain, header.end(), _CHARSTRING_ENTRY, lambda m: m.group(1).decode("latin-1"), unique=True)
        if not self._ranges:
            raise ValueError("no charstrings")
        if _LEN_IV_TOKEN.search(plain, position):
            raise ValueError("lenIV after the CharStrings dictionary")
        if ".notdef" not in self._ranges:
            raise _Unproven("no_notdef")
        self.num_glyphs = len(self._ranges)

        self._subr_ranges: dict[int, tuple[int, int]] = {}
        subrs_at = plain.find(b"/Subrs")
        if subrs_at >= 0:
            position = subrs_at + len(b"/Subrs")
            array_end = plain.find(b"array", position, position + 32)
            if array_end >= 0:  # a repeated Subr index: the last definition wins, as in the interpreter
                self._subr_ranges, _ = _read_entries(plain, array_end + len(b"array"), _SUBR_ENTRY, lambda m: int(m.group(1)), unique=False)
        self._decrypted: dict[tuple[str, int | str], bytes] = {}
        self._outlines: dict[str, bool] = {}

    def _charstring(self, key: tuple[str, int | str], span: tuple[int, int]) -> bytes:
        cached = self._decrypted.get(key)
        if cached is None:
            cached = _t1_decrypt(self._plain[span[0] : span[1]], _CHARSTRING_KEY)[self._len_iv :]
            self._decrypted[key] = cached
        return cached

    def _subr(self, index: object) -> bytes | None:
        if not isinstance(index, int) or index not in self._subr_ranges:
            return None
        return self._charstring(("subr", index), self._subr_ranges[index])

    def _scan(self, code: bytes, depth: int, state: _ScanState) -> bool:
        """True when a drawing operator executes in ``code`` (or in a subroutine it calls by a literal index)."""
        size = len(code)
        index = 0
        stack = state.stack
        while index < size:
            state.steps -= 1
            if state.steps < 0:
                state.done = True
                return False
            op = code[index]
            index += 1
            if op >= 32:
                if op <= 246:
                    stack.append(op - 139)
                elif op <= 250 and index < size:
                    stack.append((op - 247) * 256 + code[index] + 108)
                    index += 1
                elif op <= 254 and index < size:
                    stack.append(-(op - 251) * 256 - code[index] - 108)
                    index += 1
                elif op == 255 and index + 4 <= size:
                    stack.append(int.from_bytes(code[index : index + 4], "big", signed=True))
                    index += 4
                else:
                    return False
                continue
            if op in _DRAWING_OPS:
                return True
            if op == 10:  # callsubr: only a literal, in-range index is followed
                target = stack.pop() if stack else None
                subroutine = self._subr(target) if depth < _MAX_SUBR_DEPTH else None
                if subroutine is not None and self._scan(subroutine, depth + 1, state):
                    return True
                if state.done:
                    return False
            elif op == 11:  # return
                return False
            elif op == 14:  # endchar
                state.done = True
                return False
            elif op == 12:
                if index >= size:
                    return False
                escape = code[index]
                index += 1
                if escape == 12:  # div: the quotient is not a literal
                    del stack[-2:]
                    stack.append(None)
                elif escape == 16:  # callothersubr: arg1 .. argn n othersubr# callothersubr
                    other = stack.pop() if stack else None
                    count = stack.pop() if stack else None
                    if isinstance(count, int) and 0 <= count <= len(stack):
                        arguments = [stack.pop() for _ in range(count)]
                        state.ps_stack = arguments if other == 3 and count == 1 else [None] * count
                    else:
                        state.ps_stack = []
                elif escape == 17:  # pop: what the PostScript stack hands back
                    stack.append(state.ps_stack.pop() if state.ps_stack else None)
                else:  # seac, sbw, setcurrentpoint, dotsection, hstem3, vstem3
                    stack.clear()
            else:  # hints, moveto, hsbw
                stack.clear()
        return False

    def outline(self, name: str) -> bool:
        if name not in self._outlines:
            result = False
            try:
                charstring = self._charstring(("glyph", name), self._ranges[name])
                result = self._scan(charstring, 0, _ScanState())
            except (IndexError, KeyError, struct.error, ValueError, RecursionError):
                pass
            self._outlines[name] = result
        return self._outlines[name]

    def code_name(self, code: int) -> str:
        return self._encoding.get(code, ".notdef")

    def present(self, code: int) -> bool:
        name = self.code_name(code)
        return name != ".notdef" and name in self._ranges

    def proves(self, code: int, char: str) -> bool:
        """Precondition: ``present(code)`` (the facade checks it first), so the name is a real, non-.notdef glyph."""
        name = self.code_name(code)
        if not _is_agl_name_of(name, char):
            return False
        return char.isspace() or self.outline(name)


# ================================================================================= facade


class BuiltinGlyphProof:
    """What a font program proves about the glyph behind each byte of its built-in encoding.

    ``program_kind`` is ``"truetype"``, ``"type1"`` or ``"unproven:<why>"`` (``too_large``, ``unreadable``,
    ``fontfile3``, ``several_programs``, ``no_program``, ``no_notdef``, ``post_format``,
    ``hex_eexec_unreadable``); an ``unproven:*`` proof has no code present.  Not frozen: the program behind it
    memoises, and the charstring scans run lazily on first use."""

    __slots__ = ("_impl", "program_kind")

    def __init__(self, program_kind: str, impl: _TrueTypeProgram | _Type1Program | None = None) -> None:
        self.program_kind = program_kind
        self._impl = impl

    @property
    def num_glyphs(self) -> int:
        return 0 if self._impl is None else self._impl.num_glyphs

    def present(self, code: int) -> bool:
        """Every table of the program reaches a real glyph for ``code`` (no agreement or identity required)."""
        return self._impl is not None and 0 <= code <= 255 and self._impl.present(code)

    def proves(self, code: int, char: str) -> bool:
        """The program itself says the glyph behind ``code`` is the character ``char``."""
        return self.present(code) and self._impl.proves(code, char)  # type: ignore[union-attr]

    def unproven(self, text: str, codes: bytes) -> int:
        """How many ``(character, code)`` pairs have a glyph the program cannot prove is that character.

        A count only: a pair that is not even present is a missing glyph (``encoding_failed``), not unproven."""
        return sum(
            1 for char, code in zip(text, codes, strict=False) if self.present(code) and not self.proves(code, char)
        )


def unproven_proof(reason: str) -> BuiltinGlyphProof:
    """A proof that proves nothing, for a program the caller could not choose or read (``reason`` without the prefix)."""
    return BuiltinGlyphProof(f"unproven:{reason}")


def builtin_glyph_proof(program: bytes, kind: str) -> BuiltinGlyphProof:
    """Read ``program`` (the bytes MuPDF loaded for the font) as the descriptor key ``kind`` names it.

    ``kind`` is ``"FontFile2"`` (TrueType), ``"FontFile"`` (Type1) or ``"FontFile3"`` (CFF / OpenType: unproven).
    Never raises for a program it cannot read: the result is an ``unproven:*`` proof."""
    if kind == "FontFile3":
        return unproven_proof("fontfile3")
    if kind not in ("FontFile2", "FontFile"):
        raise ValueError(f"unknown font program key {kind!r}")
    if len(program) > (_MAX_FONT_PROGRAM_BYTES if kind == "FontFile2" else _MAX_TYPE1_PROGRAM_BYTES):
        return unproven_proof("too_large")
    try:
        if kind == "FontFile2":
            return BuiltinGlyphProof("truetype", _TrueTypeProgram(program))
        return BuiltinGlyphProof("type1", _Type1Program(program))
    except _Unproven as exc:
        return unproven_proof(exc.reason)
    except Exception:  # noqa: BLE001 - any parse failure means "cannot vouch", whatever the cause
        logger.debug("font program unreadable", exc_info=True)
        return unproven_proof("unreadable")
