"""The sfnt table directory, read once, for both TrueType readers (``plans/archive/sfnt-directory.md``).

Two readers walk the same directory: the simple-font reader (``simple_font_programs._TrueTypeProgram``, behind the
``fitz.Font`` face gate) and the Type0 reader (``cid_fonts.parse_truetype_glyph_program``, which has NO loader gate).
This module owns the walk, so they cannot disagree about which bytes a tag names.  The rules are the measured
MuPDF 1.27 / FreeType behaviour (simple TrueType route), or a refusal where nothing was measured:

* **First wins.**  Of a repeated tag the first IN-RANGE entry by directory position is the table, a zero-length first
  entry included (the table is then empty).  An out-of-range entry is skipped and remembered in ``dropped``.
* **``head`` is checked in every entry.**  Any ``head`` entry that is out of range or shorter than
  :data:`HEAD_MIN_LENGTH` refuses the program, even a losing duplicate.
* **A table past the end is dropped**, not fatal: its offset is past the end of the program, or offset + length is.
  ``hmtx`` is the exception: a length past the end is clipped to ``(size - offset) & ~3`` (FreeType keeps a whole
  number of 4-byte words), and an ``hmtx`` that no entry supplies, because every one starts past the end or clips to
  no bytes, refuses the program (the loader refuses that face).  Whether a dropped table matters is the
  caller's decision: :func:`read_glyph_tables` refuses a program without ``maxp``/``head``/``loca``/``glyf``, a
  reader that has no use for ``cmap`` or ``post`` just sees them absent.
* **``ttcf`` is refused.**  MuPDF reads face 0 of a collection with file-absolute member offsets, but only one- and
  two-member shapes were measured, and FontFile2 is a TrueType program, not a collection.

Offsets are absolute in the bytes given to the readers, so a :class:`TableSlot` addresses the original program and no
reader needs a private copy.  Stdlib only: no fitz, no Qt, no fontTools, and never ``cid_fonts`` or
``simple_font_programs`` (the layer under both).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

#: Largest font program either reader reads (single home; both readers bind it to ``_MAX_FONT_PROGRAM_BYTES``).
MAX_FONT_PROGRAM_BYTES = 64 << 20

#: Shortest ``head`` the loader accepts (measured 2026-11-03: lengths 52 and 53 are refused, 54 loads).
HEAD_MIN_LENGTH = 54

_SFNT_VERSIONS = (b"\x00\x01\x00\x00", b"true")
_RECORD = struct.Struct(">4sIII")  # tag, checksum, offset, length
_DIRECTORY_HEADER = 12
_RECORD_SIZE = 16


class SfntError(ValueError):
    """The program is not one both readers may read.  ``reason`` is the machine-readable cause.

    A ``ValueError`` so the simple-font reader's ``except Exception`` (``unproven:unreadable``) is unchanged.
    Reasons: ``not_truetype``, ``ttcf``, ``truncated_directory``, ``head``, ``hmtx_out_of_range``,
    ``hmtx_empty``, ``required_table_missing``, ``loca_format``, ``loca_short``."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TableSlot:
    """Where one table sits in the bytes given to :func:`read_directory` (absolute; never a copy)."""

    offset: int
    length: int  # hmtx: clipped to a whole number of words before the end of the program

    def copy(self, data: bytes, tail: int = 0) -> bytes:
        """``data[offset : offset + length + tail]``: the table bytes plus ``tail`` more (clamped to the end of ``data``).

        The only way to keep a table WITHOUT keeping the whole program alive: a ``memoryview`` slice pins its
        buffer, a copy does not."""
        return bytes(data[self.offset : self.offset + self.length + tail])


@dataclass(frozen=True, slots=True)
class SfntDirectory:
    """The table directory of one program, after the first-wins and out-of-range rules."""

    size: int  # len(data)
    slots: dict[bytes, TableSlot]  # first in-range entry per tag, by directory position
    dropped: frozenset[bytes]  # tags that had an out-of-range entry (a later in-range entry may still be in ``slots``)

    def slot(self, tag: bytes) -> TableSlot | None:
        return self.slots.get(tag)


@dataclass(frozen=True, slots=True)
class GlyphTables:
    """What a glyph-presence proof needs from ``maxp`` / ``head`` / ``loca`` / ``glyf``, already validated."""

    directory: SfntDirectory
    num_glyphs: int  # maxp uint16 @4 (the table is at least 6 bytes)
    long_loca: bool  # head int16 @50 == 1
    units_per_em: int  # head uint16 @18
    loca: TableSlot  # length >= (num_glyphs + 1) * (4 if long_loca else 2)
    glyf: TableSlot


def read_directory(data: bytes) -> SfntDirectory:
    """Walk the table directory of a plain (non-collection) TrueType program; raise :class:`SfntError` when unreadable.

    Order of the checks (the first that applies decides ``reason``):

    1. fewer than 12 bytes, or a tag other than 0x00010000 / ``true``: ``not_truetype`` (``ttcf``: ``ttcf``);
    2. ``12 + 16 * numTables`` past the end: ``truncated_directory``;
    3. entries in directory order: a ``head`` entry out of range or under :data:`HEAD_MIN_LENGTH`: ``head``;
       an offset past the end, or a length running past it (``hmtx`` excepted: clipped), goes to ``dropped``;
       anything else is kept if its tag has no slot yet;
    4. ``hmtx`` dropped with no surviving entry: ``hmtx_out_of_range`` (a clip to 0 bytes raises it at step 3);
       a winning ``hmtx`` of zero length: ``hmtx_empty``.

    O(numTables); no table body is touched."""
    size = len(data)
    if size < _DIRECTORY_HEADER:
        raise SfntError("not_truetype", "shorter than the sfnt header")
    version = bytes(data[:4])
    if version == b"ttcf":
        raise SfntError("ttcf", "a TrueType collection is refused")
    if version not in _SFNT_VERSIONS:
        raise SfntError("not_truetype", f"unknown sfnt version {version!r}")
    (table_count,) = struct.unpack_from(">H", data, 4)
    if _DIRECTORY_HEADER + _RECORD_SIZE * table_count > size:
        raise SfntError("truncated_directory", f"{table_count} entries do not fit in {size} bytes")
    slots: dict[bytes, TableSlot] = {}
    dropped: set[bytes] = set()
    for index in range(table_count):
        tag, _checksum, offset, length = _RECORD.unpack_from(data, _DIRECTORY_HEADER + _RECORD_SIZE * index)
        in_range = offset <= size and length <= size - offset
        if tag == b"head" and (not in_range or length < HEAD_MIN_LENGTH):
            raise SfntError("head", f"head entry at {offset} length {length} in a {size}-byte program")
        if offset > size:
            dropped.add(tag)
            continue
        if not in_range:
            if tag != b"hmtx":
                dropped.add(tag)
                continue
            # FreeType (tt_face_load_font_dir): "make metrics table length a multiple of 4"; a zero-length winner is
            # a missing table, and a missing hmtx is fatal (an entry that would lose first-wins is just ignored)
            length = (size - offset) & ~3
            if length == 0 and b"hmtx" not in slots:
                raise SfntError("hmtx_out_of_range", f"hmtx at {offset} clips to no bytes in a {size}-byte program")
        slots.setdefault(tag, TableSlot(offset, length))
    if b"hmtx" in dropped and b"hmtx" not in slots:
        raise SfntError("hmtx_out_of_range", "every hmtx entry starts past the end of the program")
    hmtx = slots.get(b"hmtx")
    if hmtx is not None and hmtx.length == 0:  # a zero-length winner is a missing table (measured: "hmtx table missing")
        raise SfntError("hmtx_empty", "the winning hmtx entry is empty")
    return SfntDirectory(size=size, slots=slots, dropped=frozenset(dropped))


def read_glyph_tables(data: bytes) -> GlyphTables:
    """:func:`read_directory` plus the ``maxp`` / ``head`` / ``loca`` / ``glyf`` core both readers share.

    Raises :class:`SfntError` (``required_table_missing``) when one of the four is absent or dropped or ``maxp`` is
    under 6 bytes, ``loca_format`` when ``indexToLocFormat`` is not 0 or 1, and ``loca_short`` when ``loca`` holds fewer than ``numGlyphs + 1`` entries.  ``cmap``, ``post``,
    ``hmtx`` and ``hhea`` are not required here: read them from :attr:`GlyphTables.directory`."""
    directory = read_directory(data)
    maxp, head = directory.slot(b"maxp"), directory.slot(b"head")
    loca, glyf = directory.slot(b"loca"), directory.slot(b"glyf")
    if maxp is None or maxp.length < 6 or head is None or loca is None or glyf is None:
        raise SfntError("required_table_missing", "maxp, head, loca and glyf are all required")
    # ``head`` is at least HEAD_MIN_LENGTH here: read_directory refuses every shorter entry
    (num_glyphs,) = struct.unpack_from(">H", data, maxp.offset + 4)
    (units_per_em,) = struct.unpack_from(">H", data, head.offset + 18)
    (loca_format,) = struct.unpack_from(">h", data, head.offset + 50)
    # FreeType takes any nonzero format as a long loca while the readers' 2-byte layout would be short: a value that
    # the two cannot agree on is refused, not guessed (the loader still loads such a face, so the face gate passes)
    if loca_format not in (0, 1):
        raise SfntError("loca_format", f"indexToLocFormat {loca_format}")
    long_loca = loca_format == 1
    if loca.length < (num_glyphs + 1) * (4 if long_loca else 2):
        raise SfntError("loca_short", f"loca holds {loca.length} bytes for {num_glyphs} glyphs")
    return GlyphTables(
        directory=directory,
        num_glyphs=num_glyphs,
        long_loca=long_loca,
        units_per_em=units_per_em,
        loca=loca,
        glyf=glyf,
    )
