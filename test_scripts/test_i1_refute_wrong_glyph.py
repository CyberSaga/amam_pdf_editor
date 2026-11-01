"""Slice I1 refuter 1 (the wrong-glyph hunter): fonts built to slip a wrong or missing glyph past G1' and the oracle.

Every test builds an in-memory variant of a ``simple_font_fixture_builder`` program and asserts the I1 promise: the
product either REFUSES the edit (``font_builtin_encoding_unproven`` or ``encoding_failed``) or commits the glyph MuPDF
really draws for the character.  A failing test is a refuter finding (plans/true-text-i1.md, refuter 1); a passing one
is a variant the gate holds.  The known blind spots of plans/true-text-i1.md 6.4 (a consistent lie in names AND every
cmap; operator presence is not ink) are pinned here as blind spots, not asserted as refusals.

The replacement is always ``Level B 2024`` -> ``Level A 2024`` (the twins' pair): character index 6 writes code 0x41.
Variants that need MuPDF's text to ignore the drawn glyph carry the identity ``/ToUnicode`` (as ``tounicode_lie``),
so the engine's read-back cannot be what catches them.
"""
from __future__ import annotations

import struct
from collections.abc import Callable
from io import BytesIO

import fitz
import pytest
from fontTools.misc import eexec
from fontTools.misc.psCharStrings import T1CharString
from fontTools.ttLib import TTFont

from model.text_commit.dto import CommitStatus
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.plan import PlanRejection
from model.text_commit.simple_font_programs import builtin_glyph_proof
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts import true_text_acceptance_helpers as helpers

TARGET = "Level B 2024"
REPLACEMENT = "Level A 2024"
_REFUSALS = ("font_builtin_encoding_unproven", "encoding_failed")
_A = sfb.glyph_id("A")  # 34 in every TrueType kind
_B = sfb.glyph_id("B")  # 35
_PRINTABLE = range(0x20, 0x7F)


# ----------------------------------------------------------------------------------------------
# harness
# ----------------------------------------------------------------------------------------------
def _build(
    monkeypatch,
    kind: str,
    *,
    text: str = TARGET,
    flags: int | None = None,
    tounicode: bool = True,
    mutate: Callable[[bytes], bytes] | None = None,
) -> bytes:
    """The PDF bytes of ``kind`` showing ``text``; ``mutate`` rewrites the embedded program afterwards."""
    with monkeypatch.context() as patch:
        if tounicode and kind not in sfb.TOUNICODE_KINDS:
            patch.setattr(sfb, "TOUNICODE_KINDS", (*sfb.TOUNICODE_KINDS, kind))
        fixture = sfb.build_embedded_simple_fixture(kind, text, flags=flags)
    if mutate is not None:
        program = fixture.doc.xref_stream(fixture.fontfile_xref)
        fixture.doc.update_stream(fixture.fontfile_xref, mutate(program))
    data = fixture.doc.tobytes()
    fixture.doc.close()
    return data


def _oracle(doc: fitz.Document, text: str) -> str | None:
    """``check_glyph_identity`` over the first show of ``doc`` (its own codes and texttrace gids)."""
    try:
        show = helpers._shows(doc, 0)[0]
        edited = helpers.edited_show(show, show, code_bytes=1)
        inputs = helpers.glyph_identity_inputs(doc, 0, edited, frame=helpers.visual_frame(doc[0]), code_bytes=1)
        if isinstance(inputs, str):
            return inputs
        codes, gids = inputs
        return helpers.check_glyph_identity(doc, 0, 4, text, "simple", gid_after=gids, codes=codes)
    except helpers.IndependentLegUnavailable as exc:
        return f"unavailable: {exc}"


def _outcome(data: bytes, target: str = TARGET, replacement: str = REPLACEMENT) -> tuple:
    """``("REJECTED", reason, detail)`` or ``("COMMITTED", texttrace gids, oracle detail on the committed file)``."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        engine = TieredCommitEngine(doc, max_tier=1)
        prepared = engine.prepare(doc[0], target_text=target, replacement_text=replacement, expected_origin=None)
        if isinstance(prepared, PlanRejection):
            return ("REJECTED", str(prepared.reason), prepared.detail)
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        committed = fitz.open(stream=doc.tobytes(), filetype="pdf")
    finally:
        doc.close()
    try:
        with helpers._measurement_copy(committed) as measured:
            gids = tuple(char[1] for char in measured[0].get_texttrace()[0]["chars"])
        return ("COMMITTED", gids, _oracle(committed, replacement))
    finally:
        committed.close()


def _drawn(data: bytes) -> tuple[int, ...]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return tuple(char[1] for span in doc[0].get_texttrace() for char in span["chars"])
    finally:
        doc.close()


def _assert_refused(outcome: tuple, drawn_for_a: int, note: str = "") -> None:
    """The I1 promise for a variant that draws ``drawn_for_a`` (not the honest A) for code 0x41."""
    assert outcome[0] == "REJECTED" and outcome[1] in _REFUSALS, (
        f"G1' admitted code 0x41 while MuPDF draws gid {drawn_for_a}{note} for it; committed gids {outcome[1]}, "
        f"oracle on the committed file: {outcome[2]!r}"
    )


def _assert_commits_the_honest_glyph(outcome: tuple, honest: int = _A) -> None:
    assert outcome[0] == "COMMITTED", outcome
    assert outcome[1][6] == honest, outcome
    assert outcome[2] is None, outcome


# ----------------------------------------------------------------------------------------------
# sfnt surgery (raw bytes: fontTools sorts and repairs what these tests must keep broken)
# ----------------------------------------------------------------------------------------------
def _directory(program: bytes) -> dict[bytes, tuple[int, int, int]]:
    (count,) = struct.unpack_from(">H", program, 4)
    found: dict[bytes, tuple[int, int, int]] = {}
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", program, 12 + 16 * index)
        found.setdefault(tag, (index, offset, length))
    return found


def _replace_table(program: bytes, tag: bytes, table: bytes) -> bytes:
    index, _offset, _length = _directory(program)[tag]
    out = bytearray(program)
    while len(out) % 4:
        out.append(0)
    offset = len(out)
    out += table
    struct.pack_into(">II", out, 12 + 16 * index + 8, offset, len(table))
    return bytes(out)


def _fmt4(segments: list[tuple[int, int, int | list[int]]]) -> bytes:
    """A format-4 subtable, segments IN THE ORDER GIVEN: ``(start, end, delta)`` or ``(start, end, [gids])``."""
    count = len(segments)
    ends, starts, deltas, offsets, glyphs = [], [], [], [], []
    for index, (start, end, value) in enumerate(segments):
        ends.append(end)
        starts.append(start)
        if isinstance(value, int):
            deltas.append(value & 0xFFFF)
            offsets.append(0)
        else:
            deltas.append(0)
            offsets.append(2 * (count - index) + 2 * len(glyphs))
            glyphs.extend(value)
    body = (
        struct.pack(f">{count}H", *ends)
        + b"\0\0"
        + struct.pack(f">{count}H", *starts)
        + struct.pack(f">{count}H", *deltas)
        + struct.pack(f">{count}H", *offsets)
        + struct.pack(f">{len(glyphs)}H", *glyphs)
    )
    return struct.pack(">HHHHHHH", 4, 14 + len(body), 0, 2 * count, 0, 0, 0) + body


def _fmt0(gids: list[int], length: int = 262) -> bytes:
    return struct.pack(">HHH", 0, length, 0) + bytes(gids)


def _fmt6(first: int, gids: list[int], length: int | None = None) -> bytes:
    declared = 10 + 2 * len(gids) if length is None else length
    return struct.pack(">HHHHH", 6, declared, 0, first, len(gids)) + struct.pack(f">{len(gids)}H", *gids)


def _fmt12(groups: list[tuple[int, int, int]]) -> bytes:
    body = b"".join(struct.pack(">III", *group) for group in groups)
    return struct.pack(">HHIII", 12, 0, 16 + len(body), 0, len(groups)) + body


def _cmap(subtables: list[tuple[int, int, bytes]], version: int = 0) -> bytes:
    records, data = b"", b""
    base = 4 + 8 * len(subtables)
    for platform, encoding, subtable in subtables:
        records += struct.pack(">HHI", platform, encoding, base + len(data))
        data += subtable + (b"\0" if len(subtable) % 2 else b"")
    return struct.pack(">HH", version, len(subtables)) + records + data


def _with_cmap(table: bytes) -> Callable[[bytes], bytes]:
    return lambda program: _replace_table(program, b"cmap", table)


def _gid(code: int) -> int:
    return 1 + code - 0x20


def _single_code_fmt4(mapping: dict[int, int]) -> bytes:
    return _fmt4([(code, code, gid - code) for code, gid in sorted(mapping.items())] + [(0xFFFF, 0xFFFF, 1)])


_HONEST_SYMBOL = {0xF000 + code: _gid(code) for code in _PRINTABLE}
_HONEST_UNICODE = {code: _gid(code) for code in _PRINTABLE}


# ----------------------------------------------------------------------------------------------
# FINDING: a format-4 table whose segments are not sorted (FreeType searches it linearly, the reader bisects)
# ----------------------------------------------------------------------------------------------
def test_an_unsorted_format4_table_is_read_the_way_freetype_reads_it(monkeypatch):
    """Segments [F020-F07E glyph array with F041 -> B], [F020-F040 honest], [F020-F07E honest], [FFFF].  FreeType's
    validator flags the table UNSORTED (not invalid) and ``tt_cmap4_char_map_linear`` takes the FIRST segment that
    contains the code: B.  The product's ``bisect_left`` over the end codes lands on the third segment: A.  Every
    other code is honest in both readers, so the names, the (3,0)-only route and the outlines all prove A."""
    lying = [_gid(code - 0xF000) for code in range(0xF020, 0xF07F)]
    lying[0x41 - 0x20] = _B
    table = _fmt4(
        [(0xF020, 0xF07E, lying), (0xF020, 0xF040, 1 - 0xF020), (0xF020, 0xF07E, 1 - 0xF020), (0xFFFF, 0xFFFF, 1)]
    )
    mutate = _with_cmap(_cmap([(3, 0, table)]))
    drawn = _drawn(_build(monkeypatch, "symbolic_ascii", text="AB", mutate=mutate))
    assert drawn == (_B, _B)  # MuPDF draws B for code 0x41
    _assert_refused(_outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate)), drawn[0])


def test_an_overlapping_but_sorted_format4_table_commits_the_glyph_freetype_draws(monkeypatch):
    """Held: sorted starts and ends with an overlap -- FreeType's first containing segment and the product's bisect
    are the same segment (here the honest one).  fontTools reads the LAST segment, so the oracle false-alarms."""
    table = _fmt4(
        [
            (0xF020, 0xF041, 1 - 0xF020),
            (0xF041, 0xF07E, [_B] + [_gid(code) for code in range(0x42, 0x7F)]),
            (0xFFFF, 0xFFFF, 1),
        ]
    )
    mutate = _with_cmap(_cmap([(3, 0, table)]))
    assert _drawn(_build(monkeypatch, "symbolic_ascii", text="AB", mutate=mutate)) == (_A, _B)
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate))
    assert outcome[0] == "COMMITTED" and outcome[1][6] == _A, outcome


# ----------------------------------------------------------------------------------------------
# FINDING (low): a nameless program whose only cmap subtables FreeType's validator rejects -> .notdef everywhere
# ----------------------------------------------------------------------------------------------
_REJECTED_BY_FREETYPE = {
    "fmt4_start_after_end": _cmap(
        [
            (3, 0, _fmt4([(0xF020, 0xF07E, 1 - 0xF020), (0xF0A0, 0xF090, 0), (0xFFFF, 0xFFFF, 1)])),
            (3, 1, _fmt4([(0x20, 0x7E, 1 - 0x20), (0xA0, 0x90, 0), (0xFFFF, 0xFFFF, 1)])),
        ]
    ),
    "fmt12_overlapping_groups": _cmap([(3, 1, _fmt12([(0x20, 0x50, 1), (0x41, 0x7E, _A)]))]),
    "fmt0_length_field_0": _cmap([(3, 1, _fmt0([_gid(code) if 0x20 <= code <= 0x7E else 0 for code in range(256)], 0))]),
    "fmt6_length_field_10": _cmap([(3, 1, _fmt6(0x20, [_gid(code) for code in _PRINTABLE], length=10))]),
}


@pytest.mark.parametrize("variant", sorted(_REJECTED_BY_FREETYPE))
def test_a_nameless_program_whose_tables_freetype_drops_proves_nothing(monkeypatch, variant):
    """The reader never validates a subtable; FreeType drops one that fails its default-level validation, and a
    nameless program with no charmap left draws ``.notdef`` for every code.  Severity is low: the SOURCE text is
    already invisible (every glyph of the show is gid 0), so the edit makes nothing worse -- but G1' proves glyphs
    MuPDF never draws.  With post names MuPDF falls back to the names and draws the honest glyph (measured), so only
    nameless programs are affected."""
    mutate = _with_cmap(_REJECTED_BY_FREETYPE[variant])
    drawn = _drawn(_build(monkeypatch, "symbolic_post3", text="AB", mutate=mutate))
    assert drawn == (0, 0)
    _assert_refused(_outcome(_build(monkeypatch, "symbolic_post3", mutate=mutate)), drawn[0])


# ----------------------------------------------------------------------------------------------
# Type1 programs
# ----------------------------------------------------------------------------------------------
_VECTOR_END = b"dup 126 /asciitilde put\nreadonly def\n"


def _type1(
    monkeypatch,
    *,
    text: str = TARGET,
    clear: Callable[[bytes], bytes] | None = None,
    private: bytes | None = None,
    charstring: Callable | None = None,
    order: list[str] | None = None,
    flags: int | None = None,
    kind: str = "type1_builtin",
) -> bytes:
    """A ``type1_builtin`` program with the cleartext rewritten by ``clear``, the eexec ``Private`` prefix replaced
    by ``private``, the charstring builder replaced by ``charstring`` or the CharStrings order by ``order``."""
    with monkeypatch.context() as patch:
        if private is not None:
            patch.setattr(sfb, "_T1_PRIVATE", private)
        if charstring is not None:
            patch.setattr(sfb, "_t1_charstring", charstring)
        if order is not None:
            patch.setattr(sfb, "_T1_ORDER", order)
        if clear is not None:
            original = sfb._build_type1_program

            def rebuilt(kind_: str, *, overhang: int | None = None) -> tuple[bytes, int, int, int]:
                program, length1, length2, length3 = original(kind_, overhang=overhang)
                head = clear(program[:length1])
                return head + program[length1:], len(head), length2, length3

            patch.setattr(sfb, "_build_type1_program", rebuilt)
        return _build(patch, kind, text=text, flags=flags)


def _replace_once(old: bytes, new: bytes) -> Callable[[bytes], bytes]:
    def edit(clear: bytes) -> bytes:
        assert clear.count(old) == 1, old
        return clear.replace(old, new)

    return edit


def _before_vector_end(extra: bytes) -> Callable[[bytes], bytes]:
    return _replace_once(_VECTOR_END, _VECTOR_END.replace(b"readonly def\n", extra + b"readonly def\n"))


#: FINDING: entries FreeType's t1_parse_encoding reads (any ``<integer> /<name>`` pair, radix integers, comments
#: between tokens) that the reader's ``dup <digits> /<name> put`` regex does not see; each sends code 0x41 to B
_HIDDEN_FROM_THE_REGEX = {
    "radix_8": b"dup 8#101 /B put\n",
    "radix_16": b"dup 16#41 /B put\n",
    "bare_pair_without_dup_put": b"65 /B\n",
    "comment_between_tokens": b"dup 65 % note\n /B put\n",
}


@pytest.mark.parametrize("variant", sorted(_HIDDEN_FROM_THE_REGEX))
def test_a_vector_entry_freetype_reads_but_the_regex_skips(monkeypatch, variant):
    clear = _before_vector_end(_HIDDEN_FROM_THE_REGEX[variant])
    drawn = _drawn(_type1(monkeypatch, text="AB", clear=clear))
    assert drawn == (sfb.type1_glyph_id("B"), sfb.type1_glyph_id("B"))  # MuPDF draws B for 0x41
    _assert_refused(_outcome(_type1(monkeypatch, clear=clear)), drawn[0])


#: FINDING: an entry only the regex sees (inside a comment or a string, which FreeType skips as one token): the
#: honest ``dup 65 /A put`` is removed, so MuPDF draws ``.notdef`` for 0x41 while the reader proves A
_SEEN_ONLY_BY_THE_REGEX = {
    "comment": b"% dup 65 /A put\n",
    "string": b"(dup 65 /A put) pop\n",
}


@pytest.mark.parametrize("variant", sorted(_SEEN_ONLY_BY_THE_REGEX))
def test_a_vector_entry_only_the_regex_reads(monkeypatch, variant):
    clear = _replace_once(b"dup 65 /A put\n", _SEEN_ONLY_BY_THE_REGEX[variant])
    drawn = _drawn(_type1(monkeypatch, text="AB", clear=clear))
    assert drawn == (0, sfb.type1_glyph_id("B"))  # .notdef for 0x41, B stays visible
    _assert_refused(_outcome(_type1(monkeypatch, clear=clear)), drawn[0])


def test_a_bracket_inside_the_vector_ends_it_for_freetype(monkeypatch):
    """FINDING (low): FreeType's vector parse stops at ``]`` (or ``def``); the reader reads on to ``def``.  Every
    code is ``.notdef`` for MuPDF, so the source is already invisible."""
    clear = _replace_once(
        b"0 1 255 {1 index exch /.notdef put} for\n", b"0 1 255 {1 index exch /.notdef put} for\n]\n"
    )
    drawn = _drawn(_type1(monkeypatch, text="AB", clear=clear))
    assert drawn == (0, 0)
    _assert_refused(_outcome(_type1(monkeypatch, clear=clear)), drawn[0])


def _eexec_encoding(lying_code: int = 0x41) -> bytes:
    names = [sfb.glyph_name(chr(code)) if 0x20 <= code <= 0x7E else ".notdef" for code in range(256)]
    names[lying_code] = "B"
    return b"dup /Encoding [" + b" ".join(b"/" + name.encode("ascii") for name in names) + b"] readonly put\n"


def test_an_encoding_redefined_inside_the_eexec_section_before_private(monkeypatch):
    """FINDING: FreeType parses the decrypted eexec section with the same keyword table and accepts a font-dict
    ``/Encoding`` there until ``/Private`` is seen; ``dup /Encoding [...] readonly put`` is also valid PostScript
    (the font dict is on the operand stack), so psLib -- and the oracle -- see it too.  The reader only scans the
    cleartext."""
    private = _eexec_encoding() + sfb._T1_PRIVATE
    drawn = _drawn(_type1(monkeypatch, text="AB", private=private))
    assert drawn == (sfb.type1_glyph_id("B"), sfb.type1_glyph_id("B"))
    _assert_refused(_outcome(_type1(monkeypatch, private=private)), drawn[0])


def test_an_encoding_in_the_eexec_section_after_private_is_ignored_by_both(monkeypatch):
    """Held: after ``/Private`` FreeType ignores a font-dict keyword; the product never reads it."""
    lying = _eexec_encoding().replace(b"dup /Encoding", b"/Encoding").replace(b"readonly put", b"readonly def")
    private = sfb._T1_PRIVATE.replace(b"/lenIV", lying + b"/lenIV")
    data = _type1(monkeypatch, private=private)
    assert _drawn(_type1(monkeypatch, text="AB", private=private)) == (33, 34)
    _assert_commits_the_honest_glyph(_outcome(data), honest=sfb.type1_glyph_id("A"))


_RECTANGLE = T1CharString()
_RECTANGLE.program = [0, 0, "hsbw", 100, 0, "rmoveto", 0, 400, "rlineto", 300, 0, "rlineto", 0, -400, "rlineto"]
_RECTANGLE.program += ["closepath", "endchar"]
_RECTANGLE.compile()
#: read with lenIV 4: ``0 0 hsbw endchar`` (blank); read with lenIV 8: a 300 x 400 rectangle
_TWO_FACED = b"\0\0\0\0" + bytes([139, 139, 13, 14]) + _RECTANGLE.bytecode


def _two_faced_a(original: Callable) -> Callable:
    def charstring(char: str | None, extra_right: int = 0) -> bytes:
        if char == "A":
            return eexec.encrypt(_TWO_FACED, 4330)[0]
        return original(char, extra_right)

    return charstring


def _ink(data: bytes) -> int:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pixmap = doc[0].get_pixmap(dpi=72, clip=fitz.Rect(60, 120, 140, 160))
        samples = pixmap.samples
        return sum(1 for index in range(0, len(samples), pixmap.n) if samples[index] < 128)
    finally:
        doc.close()


_LEN_IV = {
    "radix": b"/lenIV 8#4 def",  # the regex reads 8, FreeType's T1_ToInt and psLib read 4
    "repeated": b"/lenIV 8 def\n/lenIV 4 def",  # the reader takes the first, FreeType and psLib the last
}


@pytest.mark.parametrize("variant", sorted(_LEN_IV))
def test_a_lenIV_the_reader_and_freetype_read_differently(monkeypatch, variant):
    """FINDING (both readers blind): the reader skips 8 bytes of every charstring and sees the rectangle; FreeType
    skips 4 and draws ``0 0 hsbw endchar`` -- a blank A, committed.  The oracle passes it too: fontTools'
    ``T1CharString.draw`` keeps executing after ``endchar`` and finds the rectangle (see the next test)."""
    private = sfb._T1_PRIVATE.replace(b"/lenIV 4 def", _LEN_IV[variant])
    charstring = _two_faced_a(sfb._t1_charstring)
    assert _ink(_type1(monkeypatch, text="A", private=private, charstring=charstring)) == 0
    control = sfb._T1_PRIVATE.replace(b"/lenIV 4 def", b"/lenIV 8 def")  # the rectangle IS ink when read with 8
    assert _ink(_type1(monkeypatch, text="A", private=control, charstring=charstring)) > 0
    outcome = _outcome(_type1(monkeypatch, private=private, charstring=charstring))
    _assert_refused(outcome, sfb.type1_glyph_id("A"), " (with NO ink)")


def test_the_oracle_sees_no_outline_for_a_glyph_whose_ink_follows_endchar(monkeypatch):
    """FINDING (oracle only): ``0 0 hsbw endchar`` followed by a rectangle draws nothing in MuPDF (FreeType stops at
    endchar) and the PRODUCT refuses it; the helper's ``_Type1View.has_outline`` (BoundsPen over
    ``T1CharString.draw``) runs past ``endchar`` and vouches for it, so the oracle's ``no_outline`` leg misses it."""
    charstring = _two_faced_a(sfb._t1_charstring)
    assert _ink(_type1(monkeypatch, text="A", charstring=charstring)) == 0
    outcome = _outcome(_type1(monkeypatch, charstring=charstring))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome
    doc = fitz.open(stream=_type1(monkeypatch, text=REPLACEMENT, charstring=charstring), filetype="pdf")
    try:
        detail = _oracle(doc, REPLACEMENT)
    finally:
        doc.close()
    assert detail is not None and "no_outline" in detail, detail


def test_a_glyph_drawn_only_by_rmoveto_closepath_is_the_known_blind_spot(monkeypatch):
    """Known blind spot (plan 6.4), pinned: both readers count operator presence, MuPDF draws nothing."""
    original = sfb._t1_charstring

    def charstring(char: str | None, extra_right: int = 0) -> bytes:
        if char == "A":
            program = T1CharString()
            program.program = [0, 600, "hsbw", 100, 0, "rmoveto", "closepath", "endchar"]
            program.compile()
            return eexec.encrypt(b"\0\0\0\0" + program.bytecode, 4330)[0]
        return original(char, extra_right)

    assert _ink(_type1(monkeypatch, text="A", charstring=charstring)) == 0
    outcome = _outcome(_type1(monkeypatch, charstring=charstring))
    assert outcome[0] == "COMMITTED" and outcome[2] is None, outcome


@pytest.mark.parametrize(
    ("old", "new"),
    [(b"dup 65 /A put\n", b"dup 65 /.notdef put\n"), (b"dup 65 /A put\n", b"dup 65 /Agrave put\n")],
    ids=["notdef_slot", "name_absent_from_charstrings"],
)
def test_a_vector_slot_without_a_real_glyph_is_a_missing_glyph(monkeypatch, old, new):
    data = _type1(monkeypatch, clear=_replace_once(old, new))
    assert _drawn(_type1(monkeypatch, text="AB", clear=_replace_once(old, new)))[0] == 0
    outcome = _outcome(data)
    assert outcome[:2] == ("REJECTED", "encoding_failed"), outcome


def test_notdef_in_the_middle_of_charstrings_commits_the_glyph_freetype_draws(monkeypatch):
    order = [name for name in sfb._T1_ORDER if name != ".notdef"]
    order.insert(10, ".notdef")
    drawn = _drawn(_type1(monkeypatch, text="AB", order=order))
    outcome = _outcome(_type1(monkeypatch, order=order))
    _assert_commits_the_honest_glyph(outcome, honest=drawn[0])


@pytest.mark.parametrize("len_iv", [0, 1])
def test_lenIV_0_and_1_commit_the_honest_glyph(monkeypatch, len_iv):
    def charstring(char: str | None, extra_right: int = 0) -> bytes:
        program: list = [0, sfb.GLYPH_ADVANCE, "hsbw"]
        x_min, x_max, y_max = sfb.glyph_shape(char) if char is not None else (0, 0, 0)
        if x_max:
            program += [x_min, 0, "rmoveto", 0, y_max, "rlineto", x_max - x_min, 0, "rlineto", 0, -y_max, "rlineto"]
            program.append("closepath")
        program.append("endchar")
        compiled = T1CharString()
        compiled.program = program
        compiled.compile()
        return eexec.encrypt(b"\0" * len_iv + compiled.bytecode, 4330)[0]

    private = sfb._T1_PRIVATE.replace(b"/lenIV 4 def", b"/lenIV %d def" % len_iv)
    _assert_commits_the_honest_glyph(
        _outcome(_type1(monkeypatch, private=private, charstring=charstring)), honest=sfb.type1_glyph_id("A")
    )


def test_a_hex_eexec_program_commits_the_honest_glyph(monkeypatch):
    """Held for the product (psLib cannot read the hex form, so the oracle is unavailable there)."""
    original = sfb._build_type1_program

    def hexed(kind: str, *, overhang: int | None = None) -> tuple[bytes, int, int, int]:
        program, length1, length2, length3 = original(kind, overhang=overhang)
        digits = program[length1 : length1 + length2].hex().upper().encode("ascii")
        body = b"\n".join(digits[i : i + 64] for i in range(0, len(digits), 64)) + b"\n"
        return program[:length1] + body + program[length1 + length2 :], length1, len(body), length3

    with monkeypatch.context() as patch:
        patch.setattr(sfb, "_build_type1_program", hexed)
        data = _build(patch, "type1_builtin")
    outcome = _outcome(data)
    assert outcome[0] == "COMMITTED" and outcome[1][6] == sfb.type1_glyph_id("A"), outcome


@pytest.mark.parametrize("flags", [4, 32])
def test_a_vector_naming_uni0041_beside_a_glyph_named_a_commits_the_glyph_the_vector_names(monkeypatch, flags):
    """The vector sends 0x41 to ``uni0041`` (the A outline) while a glyph NAMED ``A`` draws B.  MuPDF follows the
    built-in vector for both flag values (measured: gid of ``uni0041``), so the product's commit is honest."""
    order = list(sfb._T1_ORDER)
    order.insert(order.index("A") + 1, "uni0041")
    original = sfb._t1_charstring
    # _build_type1_program derives the drawn character from the NAME; uni0041 has no entry there, so map by hand
    names = {sfb.glyph_name(chr(code)): chr(code) for code in _PRINTABLE}

    def rebuilt(kind: str, *, overhang: int | None = None) -> tuple[bytes, int, int, int]:
        clear = b"%!PS-AdobeFont-1.0: TwinSans 1.0\n11 dict begin\n/FontName /TwinSans def\n/PaintType 0 def\n"
        clear += b"/FontType 1 def\n/FontMatrix [0.001 0 0 0.001 0 0] readonly def\n"
        clear += b"/FontBBox {0 -200 700 800} readonly def\n/Encoding 256 array\n"
        clear += b"0 1 255 {1 index exch /.notdef put} for\n"
        for code in _PRINTABLE:
            name = "uni0041" if code == 0x41 else sfb.glyph_name(chr(code))
            clear += b"dup %d /%s put\n" % (code, name.encode("ascii"))
        clear += b"readonly def\ncurrentdict end\ncurrentfile eexec\n"
        parts = [b"2 index /CharStrings %d dict dup begin\n" % len(order)]
        for name in order:
            char = {"uni0041": "A", "A": "B", ".notdef": None}.get(name, names.get(name))
            charstring = original(char)
            parts.append(b"/%s %d RD " % (name.encode("ascii"), len(charstring)) + charstring + b" ND\n")
        parts.append(b"end end\nreadonly put\nput\ndup /FontName get exch definefont pop\nmark currentfile closefile\n")
        binary = eexec.encrypt(b"\0\0\0\0" + sfb._T1_PRIVATE + b"".join(parts), 55665)[0]
        trailer = (b"0" * 64 + b"\n") * 8 + b"cleartomark\n"
        return clear + binary + trailer, len(clear), len(binary), len(trailer)

    with monkeypatch.context() as patch:
        patch.setattr(sfb, "_build_type1_program", rebuilt)
        drawn = _drawn(_build(patch, "type1_builtin", text="AB", flags=flags))
        data = _build(patch, "type1_builtin", flags=flags)
    assert drawn[0] == order.index("uni0041")  # .notdef is last: no swap reaches index 34
    _assert_commits_the_honest_glyph(_outcome(data), honest=drawn[0])


# ----------------------------------------------------------------------------------------------
# TrueType variants that hold
# ----------------------------------------------------------------------------------------------
def test_a_symbol_table_mapping_code_and_f000_code_to_different_glyphs(monkeypatch):
    """MuPDF reads ``code`` before ``0xF000 + code``; the product's (3,0) route does too."""
    code_lies = _with_cmap(_cmap([(3, 0, _single_code_fmt4({**_HONEST_SYMBOL, 0x41: _B}))]))
    assert _drawn(_build(monkeypatch, "symbolic_ascii", text="AB", mutate=code_lies)) == (_B, _B)
    assert _outcome(_build(monkeypatch, "symbolic_ascii", mutate=code_lies))[:2] == (
        "REJECTED",
        "font_builtin_encoding_unproven",
    )
    f000_lies = _with_cmap(_cmap([(3, 0, _single_code_fmt4({**_HONEST_SYMBOL, 0x41: _A, 0xF041: _B}))]))
    assert _drawn(_build(monkeypatch, "symbolic_ascii", text="AB", mutate=f000_lies)) == (_A, _B)
    _assert_commits_the_honest_glyph(_outcome(_build(monkeypatch, "symbolic_ascii", mutate=f000_lies)))


@pytest.mark.parametrize(("name", "commits"), [("A.alt", False), ("uni0041.alt", False), ("uni0041", True), ("u0041", True)])
def test_post2_name_variants_of_a(monkeypatch, name, commits):
    monkeypatch.setitem(sfb._RENAMED_A, "symbolic_ascii", name)
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii"))
    if commits:
        _assert_commits_the_honest_glyph(outcome)
    else:
        assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


def _post_index_patch(target_char: str, source_char: str) -> Callable[[bytes], bytes]:
    """Give ``target_char``'s glyph the post-2 name index of ``source_char``'s glyph (a duplicate name)."""

    def mutate(program: bytes) -> bytes:
        _index, offset, _length = _directory(program)[b"post"]
        out = bytearray(program)
        (source,) = struct.unpack_from(">H", out, offset + 34 + 2 * sfb.glyph_id(source_char))
        struct.pack_into(">H", out, offset + 34 + 2 * sfb.glyph_id(target_char), source)
        return bytes(out)

    return mutate


def test_a_duplicate_post_name_on_an_unused_glyph_does_not_refuse_the_honest_a(monkeypatch):
    _assert_commits_the_honest_glyph(_outcome(_build(monkeypatch, "symbolic_ascii", mutate=_post_index_patch("z", "y"))))


def test_a_duplicate_post_name_on_the_used_glyph_refuses(monkeypatch):
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", mutate=_post_index_patch("Z", "A")))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


def test_post_1_on_a_program_not_in_the_macintosh_order_refuses(monkeypatch):
    def mutate(program: bytes) -> bytes:
        out = bytearray(program)
        struct.pack_into(">I", out, _directory(program)[b"post"][1], 0x00010000)
        return bytes(out)

    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


def test_a_composite_glyph_counts_as_an_outline(monkeypatch):
    from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

    def mutate(program: bytes) -> bytes:
        font = TTFont(BytesIO(program))
        order = font.getGlyphOrder()
        glyf = font["glyf"]
        glyf.glyphs["Abase"] = glyf["A"]
        font["hmtx"].metrics["Abase"] = font["hmtx"].metrics["A"]
        component = GlyphComponent()
        component.glyphName, component.x, component.y, component.flags = "Abase", 0, 0, 0x4
        composite = Glyph()
        composite.numberOfContours = -1
        composite.components = [component]
        glyf.glyphs["A"] = composite
        font.setGlyphOrder([*order, "Abase"])
        glyf.glyphOrder = [*order, "Abase"]
        out = BytesIO()
        font.save(out)
        return out.getvalue()

    _assert_commits_the_honest_glyph(_outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate)))


def test_a_glyph_record_with_zero_contours_is_no_outline(monkeypatch):
    def mutate(program: bytes) -> bytes:
        tables = _directory(program)
        loca, glyf, head = tables[b"loca"][1], tables[b"glyf"][1], tables[b"head"][1]
        if struct.unpack_from(">h", program, head + 50)[0] == 1:
            (start,) = struct.unpack_from(">I", program, loca + 4 * _A)
        else:
            start = 2 * struct.unpack_from(">H", program, loca + 2 * _A)[0]
        out = bytearray(program)
        struct.pack_into(">h", out, glyf + start, 0)  # the record keeps its bytes; numberOfContours = 0
        return bytes(out)

    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


def test_a_consistent_lie_in_every_table_of_a_nameless_program_is_the_known_blind_spot(monkeypatch):
    """Known blind spot (plan 6.4, design risk 2), pinned: (3,0) and (3,1) both send A to the B outline, no names.
    Both readers pass it and MuPDF draws B."""
    lie = _cmap(
        [
            (3, 0, _single_code_fmt4({**_HONEST_SYMBOL, 0xF041: _B})),
            (3, 1, _single_code_fmt4({**_HONEST_UNICODE, 0x41: _B})),
        ]
    )
    outcome = _outcome(_build(monkeypatch, "symbolic_post3", mutate=_with_cmap(lie)))
    assert outcome[0] == "COMMITTED" and outcome[1][6] == _B and outcome[2] is None, outcome


def test_a_nameless_program_with_only_a_platform0_table_is_unproven(monkeypatch):
    table = _cmap([(0, 3, _fmt4([(0x20, 0x7E, 1 - 0x20), (0xFFFF, 0xFFFF, 1)]))])
    outcome = _outcome(_build(monkeypatch, "symbolic_post3", mutate=_with_cmap(table)))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


@pytest.mark.parametrize(
    ("flags", "tables"),
    [
        (32, [(1, 1, _fmt0([(_B if code == 0x41 else _gid(code)) if 0x20 <= code <= 0x7E else 0 for code in range(256)])), (3, 0, _single_code_fmt4(_HONEST_SYMBOL))]),
        (4, [(0, 4, _fmt12([(0x20, 0x40, 1), (0x41, 0x41, _B), (0x42, 0x7E, _gid(0x42))])), (3, 0, _single_code_fmt4(_HONEST_SYMBOL))]),
        (32, [(3, 1, _single_code_fmt4(_HONEST_UNICODE)), (3, 10, _fmt12([(0x20, 0x40, 1), (0x41, 0x41, _B), (0x42, 0x7E, _gid(0x42))]))]),
    ],
    ids=["nonsymbolic_1_1_lie_first", "symbolic_0_4_lie", "nonsymbolic_3_10_lie_beside_3_1"],
)
def test_review1_neighbours_a_lying_table_beside_an_honest_one_refuses(monkeypatch, flags, tables):
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", flags=flags, mutate=_with_cmap(_cmap(tables))))
    assert outcome[0] == "REJECTED" and outcome[1] in _REFUSALS, outcome


def _two_cmap_tags(first: bytes, second: bytes) -> Callable[[bytes], bytes]:
    """The program with TWO ``cmap`` directory records: ``first`` then ``second``."""

    def mutate(program: bytes) -> bytes:
        (count,) = struct.unpack_from(">H", program, 4)
        records = [list(struct.unpack_from(">4sIII", program, 12 + 16 * i)) for i in range(count)]
        for record in records:
            record[2] += 16  # one more directory record
        tail = bytearray(program[12 + 16 * count :])
        base = 12 + 16 * (count + 1)
        offsets = []
        for table in (first, second):
            while len(tail) % 4:
                tail.append(0)
            offsets.append(base + len(tail))
            tail += table
        position = next(i for i, record in enumerate(records) if record[0] == b"cmap")
        records[position][2:] = [offsets[0], len(first)]
        records.insert(position + 1, [b"cmap", 0, offsets[1], len(second)])
        head = bytearray(program[:12])
        struct.pack_into(">H", head, 4, count + 1)
        return bytes(head) + b"".join(struct.pack(">4sIII", *record) for record in records) + bytes(tail)

    return mutate


@pytest.mark.parametrize("arrangement", ["honest_then_lie", "lie_then_honest", "empty_then_lie"])
def test_two_cmap_records_in_the_table_directory(monkeypatch, arrangement):
    honest = _cmap([(3, 0, _single_code_fmt4(_HONEST_SYMBOL))])
    lie = _cmap([(3, 0, _single_code_fmt4({**_HONEST_SYMBOL, 0xF041: _B}))])
    first, second = {"honest_then_lie": (honest, lie), "lie_then_honest": (lie, honest), "empty_then_lie": (b"", lie)}[
        arrangement
    ]
    mutate = _two_cmap_tags(first, second)
    drawn = _drawn(_build(monkeypatch, "symbolic_ascii", text="AB", mutate=mutate))
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate))
    if outcome[0] == "COMMITTED":
        assert outcome[1][6] == drawn[0] == _A, (outcome, drawn)
    else:
        assert outcome[1] in _REFUSALS, outcome


def test_a_cmap_header_version_freetype_ignores_changes_nothing(monkeypatch):
    def mutate(program: bytes) -> bytes:
        out = bytearray(program)
        struct.pack_into(">H", out, _directory(program)[b"cmap"][1], 1)
        return bytes(out)

    _assert_commits_the_honest_glyph(_outcome(_build(monkeypatch, "symbolic_ascii", mutate=mutate)))
    lie = _outcome(_build(monkeypatch, "symbolic_post3_wrongglyph", mutate=mutate))
    assert lie[:2] == ("REJECTED", "font_builtin_encoding_unproven"), lie


def test_a_ttcf_container_under_fontfile2_is_unreadable():
    assert builtin_glyph_proof(b"ttcf\x00\x01\x00\x00\x00\x00\x00\x01\x00\x00\x00\x10" + b"\0" * 64, "FontFile2").program_kind == (
        "unproven:unreadable"
    )


# ----------------------------------------------------------------------------------------------
# ToUnicode, the planner's encoding edges, the capability cache
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["symbolic_ascii", "symbolic_mac10", "type1_builtin"])
def test_a_tounicode_beside_an_honest_program_still_commits(monkeypatch, kind):
    honest = sfb.type1_glyph_id("A") if kind in sfb.TYPE1_KINDS else _A
    _assert_commits_the_honest_glyph(_outcome(_build(monkeypatch, kind, tounicode=True)), honest=honest)


@pytest.mark.parametrize("kind", ["symbolic_mac10_wrongglyph", "type1_wrongname"])
def test_a_tounicode_beside_a_lying_program_refuses(monkeypatch, kind):
    outcome = _outcome(_build(monkeypatch, kind, tounicode=True))
    assert outcome[:2] == ("REJECTED", "font_builtin_encoding_unproven"), outcome


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        ("Level  A 2024", "COMMITTED"),
        ("Level A 2024 ", "COMMITTED"),
        ("Level ~ 2024", "COMMITTED"),
        ("Level ' 2024", "encoding_failed"),
        ("Level \u00e9 2024", "encoding_failed"),
    ],
    ids=["space_inside", "trailing_space", "asciitilde", "quote_slot", "non_ascii"],
)
def test_planner_encoding_edges_on_symbolic_ascii(monkeypatch, replacement, expected):
    outcome = _outcome(_build(monkeypatch, "symbolic_ascii"), replacement=replacement)
    assert (outcome[0] if outcome[0] == "COMMITTED" else outcome[1]) == expected, outcome
    if outcome[0] == "COMMITTED":
        assert outcome[2] is None, outcome


def test_a_source_code_the_program_cannot_prove_is_not_checked_by_design(monkeypatch):
    """Plan 7.2 (G1' checks replacement codes only): the target's lying A is replaced by an honest B and commits."""
    data = _build(monkeypatch, "tounicode_lie", text="Level A 2024")
    outcome = _outcome(data, target="Level A 2024", replacement="Level B 2024")
    assert outcome[0] == "COMMITTED" and outcome[1][6] == _B, outcome


def test_a_program_rewritten_in_place_is_reproved_on_a_new_page_handle(monkeypatch):
    doc = fitz.open(stream=_build(monkeypatch, "symbolic_ascii"), filetype="pdf")
    lie = fitz.open(stream=_build(monkeypatch, "tounicode_lie"), filetype="pdf")
    try:
        engine = TieredCommitEngine(doc, max_tier=1)
        first = engine.prepare(doc[0], target_text=TARGET, replacement_text=REPLACEMENT, expected_origin=None)
        assert not isinstance(first, PlanRejection), first
        doc.update_stream(6, lie.xref_stream(6))
        second = engine.prepare(doc[0], target_text=TARGET, replacement_text=REPLACEMENT, expected_origin=None)
        assert isinstance(second, PlanRejection) and str(second.reason) == "font_builtin_encoding_unproven", second
    finally:
        doc.close()
        lie.close()


# ----------------------------------------------------------------------------------------------
# real programs (needs_fixtures)
# ----------------------------------------------------------------------------------------------
_REAL = {
    "artofwar": ("test_files/mozilla-pdf/artofwar.pdf", 73, "The", "ehT", "T-e"),
    "bug1946953": ("test_files/mozilla-pdf/bug1946953.pdf", 1, "Type", "epyT", "Tqpe"),
}


@pytest.mark.needs_fixtures
@pytest.mark.parametrize("slug", sorted(_REAL))
def test_real_programs_commit_honest_glyphs_and_refuse_the_unproven_one(slug):
    """artofwar names its hyphen ``minus`` (not the AGL name of '-'): '-' refuses ``font_builtin_encoding_unproven``.
    bug1946953 names every printable glyph it has by its AGL name, so its refusal case is a glyph it lacks ('q':
    ``encoding_failed``)."""
    from test_scripts.test_true_text_i1_real_programs import _open_public

    relative_path, show_index, target, honest, refused = _REAL[slug]
    try:
        doc = _open_public(relative_path)
    except helpers.FixtureUnavailable as exc:
        pytest.skip(str(exc))
    try:
        show = helpers._shows(doc, 0)[show_index]
        with helpers._measurement_copy(doc) as measured:
            trace = helpers._trace_for(measured[0], show, target)
        frame = helpers.visual_frame(doc[0])
        located = {
            "expected_origin": tuple(fitz.Point(trace["chars"][0][2]) * frame.quarter_turn),
            "target_bbox": tuple(fitz.Rect(trace["bbox"]) * frame.quarter_turn),
        }
        engine = TieredCommitEngine(doc, max_tier=1)
        bad = engine.prepare(doc[0], target_text=target, replacement_text=refused, **located)
        assert isinstance(bad, PlanRejection), bad
        assert str(bad.reason) == ("font_builtin_encoding_unproven" if slug == "artofwar" else "encoding_failed"), bad
        good = engine.prepare(doc[0], target_text=target, replacement_text=honest, **located)
        assert not isinstance(good, PlanRejection), good
        assert engine.commit(good).status is CommitStatus.COMMITTED
    finally:
        doc.close()
