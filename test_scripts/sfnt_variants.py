"""Byte surgery on an sfnt program, for the table-directory tests (``test_sfnt.py``).

``plans/archive/sfnt-directory.md`` rules how both sfnt readers walk the table directory (first in-range entry wins, ``head``
>= 54 bytes, an out-of-range table is absent, ``ttcf`` refused).  Every ruling was measured against MuPDF on a
catalogue of crafted programs; this module rebuilds that catalogue from ANY base program so the tests need no stored
font bytes.  It is a test-side helper: it knows nothing about the product readers.

Two layers:

* :func:`assemble` lays tables out and writes the directory.  Each :class:`Entry` may carry a directory offset or
  length that differs from where its bytes really sit (a callable receives ``(file size, placed offset)`` and is
  resolved after layout, so "past the end of the file" can be expressed), a zero-length body, no trailing pad, or a
  sort key that moves its directory position (the directory is stably sorted by that key, tag by default).
* :class:`Variants` wraps one base program and builds the named shapes: a duplicated tag, a modified entry, a
  truncated ``head``, a ``ttcf`` container with file-absolute or member-relative offsets.

Base programs come from the existing fixture builders: the simple-font kinds
(``simple_font_fixture_builder.build_font_program``) feed the simple-font reader and :func:`type0_program`
(``type0_fixture_builder.build_identity_h_fixture`` with ``subset=True``) feeds the Type0 one.
"""
from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

#: ``callable(file size, placed offset) -> value`` or a plain int
Number = int | Callable[[int, int], int]

SFNT_VERSION = b"\x00\x01\x00\x00"


def past_eof_length(size: int, offset: int) -> int:
    """A directory length that runs 1000 bytes past the end of the file (``offset + length > size``)."""
    return size - offset + 1000


def past_eof_offset(size: int, offset: int) -> int:
    """A directory offset 100 bytes past the end of the file."""
    return size + 100


def last_word_offset(size: int, offset: int) -> int:
    """A directory offset 2 bytes before the end of the file (inside the last 4-byte word)."""
    return size - 2


@dataclass
class Entry:
    """One table directory entry plus the bytes it should (or should not) point at."""

    tag: bytes
    data: bytes | None  # None: a zero-length table placed at the layout cursor
    dir_len: Number | None = None  # the length the DIRECTORY states; default: the body length
    dir_off: Number | None = None  # the offset the DIRECTORY states; default: where the body really sits
    nopad: bool = False  # no 4-byte pad after the body (a table that ends exactly at the end of the file)
    dirkey: bytes | None = None  # sort key of the directory position; default: the tag


def parse_tables(program: bytes) -> list[tuple[bytes, bytes]]:
    """``(tag, bytes)`` of every table of a plain (non-ttcf) sfnt, in directory order."""
    (count,) = struct.unpack_from(">H", program, 4)
    out = []
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", program, 12 + 16 * index)
        out.append((tag, program[offset : offset + length]))
    return out


def directory_entries(program: bytes) -> list[tuple[bytes, int, int]]:
    """``(tag, offset, length)`` of every directory entry of a plain sfnt, in directory order."""
    (count,) = struct.unpack_from(">H", program, 4)
    return [
        (tag, offset, length)
        for tag, _checksum, offset, length in (
            struct.unpack_from(">4sIII", program, 12 + 16 * index) for index in range(count)
        )
    ]


def _resolve(value: Number, size: int, offset: int) -> int:
    return value(size, offset) if callable(value) else value


def assemble(members: list[list[Entry]], *, ttc: bool = False) -> bytes:
    """Lay out ``members`` (each a list of entries, bodies placed in list order) and write the directories.

    ``ttc=True`` writes a ``ttcf`` header and one directory per member; every offset is then FILE-ABSOLUTE, the shape
    MuPDF/FreeType load (the spec).  Each member's directory is stably sorted by ``dirkey`` (default: the tag)."""
    header_size = 12 + 4 * len(members) if ttc else 0
    directory_sizes = [12 + 16 * len(member) for member in members]
    body = b""
    placed: list[list[tuple[Entry, int, int]]] = []
    for member in members:
        row = []
        for entry in member:
            offset = header_size + sum(directory_sizes) + len(body)
            if entry.data is None:
                row.append((entry, offset, 0))
                continue
            body += entry.data
            length = len(entry.data)
            if not entry.nopad:
                body += b"\0" * (-len(body) % 4)
            row.append((entry, offset, length))
        placed.append(row)
    size = header_size + sum(directory_sizes) + len(body)
    directories: list[tuple[int, bytes]] = []
    position = header_size
    for row in placed:
        ordered = sorted(row, key=lambda item: item[0].dirkey if item[0].dirkey is not None else item[0].tag)
        count = len(ordered)
        power, exponent = 1, 0
        while power * 2 <= count:
            power *= 2
            exponent += 1
        directory = SFNT_VERSION + struct.pack(">HHHH", count, power * 16, exponent, count * 16 - power * 16)
        for entry, offset, length in ordered:
            stated_offset = offset if entry.dir_off is None else _resolve(entry.dir_off, size, offset)
            stated_length = length if entry.dir_len is None else _resolve(entry.dir_len, size, offset)
            directory += struct.pack(">4sIII", entry.tag, 0, stated_offset, stated_length)
        directories.append((position, directory))
        position += len(directory)
    out = b""
    if ttc:
        out = b"ttcf" + struct.pack(">II", 0x00010000, len(members))
        out += b"".join(struct.pack(">I", at) for at, _ in directories)
    out += b"".join(directory for _, directory in directories)
    out += body
    assert len(out) == size, (len(out), size)
    return out


def with_loca_format(head: bytes, loca_format: int) -> bytes:
    """``head`` with ``indexToLocFormat`` (int16 at byte 50) set to ``loca_format``."""
    return head[:50] + struct.pack(">h", loca_format) + head[52:]


def loca_format_of(head: bytes) -> int:
    return struct.unpack_from(">h", head, 50)[0]


def with_version(program: bytes, version: bytes) -> bytes:
    """``program`` with its sfnt version tag (the first 4 bytes) replaced, e.g. ``b"true"``."""
    assert len(version) == 4
    return version + program[4:]


def with_num_glyphs(maxp: bytes, count: int) -> bytes:
    """``maxp`` with ``numGlyphs`` (uint16 at byte 4) set to ``count``."""
    return maxp[:4] + struct.pack(">H", count) + maxp[6:]


class Variants:
    """Named table-directory shapes built from one base program (a plain, non-ttcf sfnt)."""

    def __init__(self, program: bytes) -> None:
        self.program = program
        self.tables = parse_tables(program)
        self.by_tag = dict(self.tables)

    def table(self, tag: bytes) -> bytes:
        return self.by_tag[tag]

    def entries(self, **replace: bytes) -> list[Entry]:
        """One entry per base table in directory order; ``replace`` maps a tag (``OS_2`` for ``OS/2``) to new bytes."""
        swaps = {key.replace("_", "/").encode("latin-1"): value for key, value in replace.items()}
        return [Entry(tag, swaps.get(tag, data)) for tag, data in self.tables]

    def roundtrip(self) -> bytes:
        """The base program re-assembled with no change (the control every variant is read against)."""
        return assemble([self.entries()])

    def with_table(self, tag: bytes, data: bytes) -> bytes:
        """The base program with one table's bytes replaced (a single entry)."""
        return assemble([[Entry(t, data if t == tag else d) for t, d in self.tables]])

    def placed_offset(self, tag: bytes) -> int:
        """Where ``tag`` lands in :meth:`roundtrip`."""
        for entry_tag, offset, _length in directory_entries(self.roundtrip()):
            if entry_tag == tag:
                return offset
        raise KeyError(tag)

    def modified(self, tag: bytes, **fields: Number | bool | None) -> bytes:
        """The base program with the ``tag`` entry's directory offset / length changed (``dir_off``, ``dir_len``)."""
        entries = [Entry(t, d, **fields) if t == tag else Entry(t, d) for t, d in self.tables]  # type: ignore[arg-type]
        return assemble([entries])

    def duplicated(self, tag: bytes, first: Entry | bytes | None, last: Entry | bytes | None) -> bytes:
        """The base program with ``tag`` listed twice, ``first`` then ``last`` (bytes, ``None`` = zero length, or an Entry)."""

        def entry(spec: Entry | bytes | None) -> Entry:
            return spec if isinstance(spec, Entry) else Entry(tag, spec)

        entries: list[Entry] = []
        for t, d in self.tables:
            if t == tag:
                entries += [entry(first), entry(last)]
            else:
                entries.append(Entry(t, d))
        return assemble([entries])

    def head_truncated_at_eof(self, length: int) -> bytes:
        """``head`` really ``length`` bytes long, placed LAST, ending exactly at the end of the file."""
        entries = [Entry(t, d) for t, d in self.tables if t != b"head"]
        entries.append(Entry(b"head", self.by_tag[b"head"][:length], nopad=True))
        return assemble([entries])

    def head_at_eof(self) -> bytes:
        """The control for :meth:`head_truncated_at_eof`: the whole 54-byte ``head`` last, ending at the end of the file."""
        entries = [Entry(t, d) for t, d in self.tables if t != b"head"]
        entries.append(Entry(b"head", self.by_tag[b"head"], nopad=True))
        return assemble([entries])

    def without(self, tag: bytes) -> bytes:
        """The base program with the ``tag`` directory entry (and its body) left out: ``numTables - 1`` entries."""
        return assemble([[Entry(t, d) for t, d in self.tables if t != tag]])

    def truncated_at_eof(self, tag: bytes, length: int) -> bytes:
        """``tag`` really ``length`` bytes long (the base body cut), placed LAST, ending exactly at the end of the file."""
        entries = [Entry(t, d) for t, d in self.tables if t != tag]
        entries.append(Entry(tag, self.by_tag[tag][:length], nopad=True))
        return assemble([entries])

    def hmtx_at_eof(self, remainder: int, **fields: Number | bool | None) -> bytes:
        """``hmtx`` placed LAST and unpadded, its body cut so its length is ``remainder`` mod 4; ``fields`` set its entry.

        A table that ends exactly at the end of a file whose length is not a multiple of 4: the shape that tells
        "clip to ``size - offset``" from FreeType's "clip to a whole number of 4-byte words"."""
        body = self.by_tag[b"hmtx"]
        body = body[: len(body) - (len(body) - remainder) % 4]
        entries = [Entry(t, d) for t, d in self.tables if t != b"hmtx"]
        entries.append(Entry(b"hmtx", body, nopad=True, **fields))  # type: ignore[arg-type]
        return assemble([entries])

    def ttcf_file_absolute(self, members: int = 1) -> bytes:
        """A ``ttcf`` collection whose member tables are addressed from the START OF THE FILE (the spec; MuPDF loads it)."""
        return assemble([self.entries() for _ in range(members)], ttc=True)

    def ttcf_member_relative(self) -> bytes:
        """``ttcf`` header + the plain sfnt untouched: table offsets are relative to the member start, not the file.

        This is the only collection shape the Type0 reader accepted before the unification (it parsed
        ``data[offset:]`` as a stand-alone font), so it is the red control for "ttcf is refused"."""
        header = b"ttcf" + struct.pack(">III", 0x00010000, 1, 16)
        return header + self.roundtrip()


@dataclass(frozen=True)
class Shape:
    """A named variant: what it is, and what FreeType (through ``fitz.Font``) does with it."""

    name: str
    data: bytes


def face_fatal_shapes(v: Variants) -> list[Shape]:
    """Directory shapes ``fitz.Font`` REFUSES to load (measured: MuPDF 1.27 / FreeType, simple TrueType route)."""
    fatal = [
        Shape("head_len_52", v.modified(b"head", dir_len=52)),
        Shape("head_len_53", v.modified(b"head", dir_len=53)),
        Shape("head_truncated_52_at_eof", v.head_truncated_at_eof(52)),
        Shape("head_dup_zero_last", v.duplicated(b"head", v.table(b"head"), None)),
        Shape("head_dup_zero_first", v.duplicated(b"head", None, v.table(b"head"))),
        Shape("head_length_past_eof", v.modified(b"head", dir_len=past_eof_length)),
        Shape("head_offset_past_eof", v.modified(b"head", dir_off=past_eof_offset)),
        Shape("loca_length_past_eof", v.modified(b"loca", dir_len=past_eof_length)),
        Shape("loca_offset_past_eof", v.modified(b"loca", dir_off=past_eof_offset)),
        Shape("hmtx_offset_past_eof", v.modified(b"hmtx", dir_off=past_eof_offset)),
        # a zero-length hmtx that wins first-wins is a missing hmtx (FreeType tt_face_lookup_table skips empty tables)
        Shape("hmtx_length_zero", v.modified(b"hmtx", dir_len=0)),
        Shape("hmtx_dup_zero_first", v.duplicated(b"hmtx", None, v.table(b"hmtx"))),
        # offset in the last word and an overflowing length: clipped to (size - offset) & ~3 == 0, i.e. a missing hmtx
        Shape("hmtx_last_word_length_past_eof", v.hmtx_at_eof(0, dir_off=last_word_offset, dir_len=past_eof_length)),
        # M2 (measured 2026-11-03, owner-ruled 2026-11-03): hmtx and hhea are REQUIRED.  "horizontal metrics (hmtx) table
        # missing" for an hmtx entry that is not in the directory at all, under either sfnt version
        Shape("hmtx_absent", v.without(b"hmtx")),
        Shape("hmtx_absent_true", with_version(v.without(b"hmtx"), b"true")),
        # "horizontal header (hhea) table missing": no hhea entry, a zero-length one, one past the end of the file
        Shape("hhea_absent", v.without(b"hhea")),
        Shape("hhea_length_zero", v.modified(b"hhea", dir_len=0)),
        Shape("hhea_offset_past_eof", v.modified(b"hhea", dir_off=past_eof_offset)),
        Shape("hhea_length_past_eof", v.modified(b"hhea", dir_len=past_eof_length)),
        # the loader reads 36 bytes AT the offset and fails ("unknown file format") when they run off the file
        Shape("hhea_truncated_34_at_eof", v.truncated_at_eof(b"hhea", 34)),
    ]
    return fatal


def lenient_shapes(v: Variants) -> list[Shape]:
    """Directory shapes ``fitz.Font`` LOADS (an optional table that is out of range is ignored; hmtx is clipped).

    ``glyf``, ``maxp`` and ``cmap`` out of range also load, but the face is empty (nothing paints / no cmap): they are
    here because the loader does not refuse them, and the readers refuse them for a different reason."""
    lenient = [
        Shape("head_54_at_eof", v.head_at_eof()),
        Shape("post_length_past_eof", v.modified(b"post", dir_len=past_eof_length)),
        Shape("post_offset_past_eof", v.modified(b"post", dir_off=past_eof_offset)),
        Shape("name_length_past_eof", v.modified(b"name", dir_len=past_eof_length)),
        Shape("name_offset_past_eof", v.modified(b"name", dir_off=past_eof_offset)),
        Shape("os2_length_past_eof", v.modified(b"OS/2", dir_len=past_eof_length)),
        Shape("os2_offset_past_eof", v.modified(b"OS/2", dir_off=past_eof_offset)),
        Shape("hmtx_length_past_eof", v.modified(b"hmtx", dir_len=past_eof_length)),
        # hmtx last, unpadded, body length 2 mod 4: FreeType keeps a whole number of words (size - offset) & ~3
        Shape("hmtx_unaligned_length_past_eof", v.hmtx_at_eof(2, dir_len=past_eof_length)),
        Shape("glyf_length_past_eof", v.modified(b"glyf", dir_len=past_eof_length)),
        Shape("glyf_offset_past_eof", v.modified(b"glyf", dir_off=past_eof_offset)),
        Shape("maxp_length_past_eof", v.modified(b"maxp", dir_len=past_eof_length)),
        Shape("maxp_offset_past_eof", v.modified(b"maxp", dir_off=past_eof_offset)),
        Shape("cmap_length_past_eof", v.modified(b"cmap", dir_len=past_eof_length)),
        Shape("cmap_offset_past_eof", v.modified(b"cmap", dir_off=past_eof_offset)),
        # the loader ignores the directory LENGTH of hhea and reads the 36 bytes at the offset: 34 / 35 with the data in
        # place, and a 36-byte hhea ending exactly at the end of the file, are faithful
        Shape("hhea_dirlen_34", v.modified(b"hhea", dir_len=34)),
        Shape("hhea_dirlen_35", v.modified(b"hhea", dir_len=35)),
        Shape("hhea_36_at_eof", v.truncated_at_eof(b"hhea", 36)),
    ]
    return lenient


def type0_program() -> bytes:
    """A small (subset) Identity-H TrueType program from the Type0 fixture builder; no cmap, no post, 50k glyph slots."""
    from test_scripts import type0_fixture_builder as t0

    fixture = t0.build_identity_h_fixture(subset=True)
    try:
        return t0.embedded_font_buffer(fixture)
    finally:
        fixture.doc.close()
