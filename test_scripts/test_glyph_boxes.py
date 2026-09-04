"""Point-verified glyph ink boxes read from the embedded TrueType program.

The oracle throughout is MuPDF's own ``fz_bound_glyph`` at ``fz_scale(upem,
upem)`` — the exact control box the painter's ink is bounded by.  Every
assertion is two-sided: the padded box must CONTAIN the oracle (safety: a
box that misses ink is a false-safe in the duplicate-painter gate) and must
lie inside the oracle dilated by one font unit (value: a box much larger
than the ink refuses admissions that are actually safe).

Nothing here reads a document from disk: the fixture font is authored by
``type0_fixture_builder`` and every adversarial program is a mutated copy of
its bytes held in memory.  No glyph names, font names or file basenames
reach any assertion message (plan §10 privacy).
"""
from __future__ import annotations

import math

import fitz
import pytest
from fitz import mupdf

from model.text_commit.cid_fonts import (
    build_identity_h_cid_capability,
    parse_truetype_glyph_program,
    read_embedded_font_program,
)
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.glyph_boxes import (
    GLYPH_BOX_REASONS,
    GlyphBox,
    GlyphBoxCache,
    glyph_unit_box,
)
from test_scripts.painter_matrix_fixtures import (
    TRICKY_FONT_PATH,
    build_face_fixture,
    tricky_font_available,
)
from test_scripts.type0_fixture_builder import (
    CJK_TEXT,
    build_identity_h_fixture,
    fontfile2_xref,
)

# One unit of pad is the module's contract; the oracle is exact, so the
# padded box may exceed it by at most this much on every side.
PAD = 1.0

# Composite component flags used by the synthesised-glyph fixtures.
_ARG_1_AND_2_ARE_WORDS = 0x0001
_ARGS_ARE_XY_VALUES = 0x0002
_WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
_MORE_COMPONENTS = 0x0020
_SCALED_COMPONENT_OFFSET = 0x0800

_F2DOT14_ONE_AND_A_HALF = 24576  # 1.5 × 16384
# Far enough out that the scaled offset (600, 300) and the unscaled one
# (400, 200) put the union's right edge 200 units apart — the two readings
# must be separated by much more than the 1-unit pad or the case proves
# nothing about SCALED_COMPONENT_OFFSET.
_COMPONENT_OFFSET = (400, 200)


# ------------------------------------------------------------- fixtures


class _Sfnt:
    """Raw table addressing for the TEST side only — never the module's."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        tables: dict[bytes, tuple[int, int]] = {}
        for i in range(int.from_bytes(data[4:6], "big")):
            base = 12 + i * 16
            tables[data[base : base + 4]] = (
                int.from_bytes(data[base + 8 : base + 12], "big"),
                int.from_bytes(data[base + 12 : base + 16], "big"),
            )
        self.tables = tables
        head = tables[b"head"][0]
        self.upem = int.from_bytes(data[head + 18 : head + 20], "big")
        long_loca = int.from_bytes(data[head + 50 : head + 52], "big") == 1
        maxp = tables[b"maxp"][0]
        self.num_glyphs = int.from_bytes(data[maxp + 4 : maxp + 6], "big")
        hhea = tables[b"hhea"][0]
        self.num_h_metrics = int.from_bytes(data[hhea + 34 : hhea + 36], "big")
        self.hmtx = tables[b"hmtx"][0]
        self.glyf = tables[b"glyf"][0]
        loca, size = tables[b"loca"][0], (4 if long_loca else 2)
        self.loca = [
            int.from_bytes(data[loca + i * size : loca + (i + 1) * size], "big")
            * (1 if long_loca else 2)
            for i in range(self.num_glyphs + 1)
        ]

    def glyph_bytes(self, gid: int) -> bytes:
        start, end = self.loca[gid], self.loca[gid + 1]
        return self.data[self.glyf + start : self.glyf + end] if end > start else b""

    def header_box(self, gid: int) -> tuple[int, int, int, int] | None:
        raw = self.glyph_bytes(gid)
        if len(raw) < 10:
            return None
        return tuple(  # type: ignore[return-value]
            int.from_bytes(raw[i : i + 2], "big", signed=True)
            for i in (2, 4, 6, 8)
        )

    def is_composite(self, gid: int) -> bool:
        raw = self.glyph_bytes(gid)
        return len(raw) >= 2 and int.from_bytes(raw[0:2], "big", signed=True) < 0

    def lsb_from_tail_array(self, gid: int) -> int:
        """OpenType ``hmtx``: ``leftSideBearing[]`` follows ``hMetrics[]``."""
        if gid < self.num_h_metrics:
            at = self.hmtx + gid * 4 + 2
        else:
            at = self.hmtx + self.num_h_metrics * 4 + (gid - self.num_h_metrics) * 2
        return int.from_bytes(self.data[at : at + 2], "big", signed=True)

    def lsb_from_last_metric(self, gid: int) -> int:
        """The ADVANCE-width fallback rule, applied to lsb — measurably wrong."""
        at = self.hmtx + min(gid, self.num_h_metrics - 1) * 4 + 2
        return int.from_bytes(self.data[at : at + 2], "big", signed=True)


@pytest.fixture(scope="module")
def program() -> bytes:
    fixture = build_identity_h_fixture()
    try:
        data = fixture.doc.xref_stream(fontfile2_xref(fixture))
    finally:
        fixture.doc.close()
    assert data
    return data


@pytest.fixture(scope="module")
def sfnt(program: bytes) -> _Sfnt:
    return _Sfnt(program)


def _oracle(data: bytes, upem: int, gid: int) -> tuple[float, float, float, float]:
    """``fz_bound_glyph`` on a font built from ``data`` — the ink control box."""
    buffer = mupdf.fz_new_buffer_from_copied_data(data)
    font = mupdf.fz_new_font_from_buffer(None, buffer, 0, 1)
    rect = mupdf.fz_bound_glyph(font, gid, mupdf.fz_scale(upem, upem))
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _assert_brackets(box: GlyphBox, oracle: tuple[float, ...], gid: int) -> None:
    assert box.reason is None, f"gid {gid} refused: {box.reason}"
    assert box.units is not None
    units = box.units
    assert (
        units[0] <= oracle[0]
        and units[1] <= oracle[1]
        and units[2] >= oracle[2]
        and units[3] >= oracle[3]
    ), f"gid {gid}: {units} does not contain the oracle {oracle}"
    assert (
        units[0] >= oracle[0] - PAD
        and units[1] >= oracle[1] - PAD
        and units[2] <= oracle[2] + PAD
        and units[3] <= oracle[3] + PAD
    ), f"gid {gid}: {units} exceeds the oracle {oracle} dilated by {PAD}"


def _sample_gids(sfnt: _Sfnt, simple_wanted: int, composite_wanted: int):
    simple: list[int] = []
    composite: list[int] = []
    gid = 0
    while (
        len(simple) < simple_wanted or len(composite) < composite_wanted
    ) and gid < sfnt.num_glyphs:
        if sfnt.glyph_bytes(gid):
            if sfnt.is_composite(gid):
                if len(composite) < composite_wanted:
                    composite.append(gid)
            elif len(simple) < simple_wanted:
                simple.append(gid)
        gid += 1
    return simple, composite


def _lsb_mismatch_gids(sfnt: _Sfnt) -> list[int]:
    out = []
    for gid in range(sfnt.num_glyphs):
        header = sfnt.header_box(gid)
        if header is not None and sfnt.lsb_from_tail_array(gid) != header[0]:
            out.append(gid)
    return out


# ------------------------------------------------ containment vs the oracle


def test_padded_point_box_brackets_the_oracle_on_simple_glyphs(
    program: bytes, sfnt: _Sfnt
) -> None:
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    simple, _ = _sample_gids(sfnt, 300, 0)
    assert len(simple) == 300
    # The lsb != xMin glyphs are the whole point of the shift; force them in.
    for gid in _lsb_mismatch_gids(sfnt):
        if not sfnt.is_composite(gid) and gid not in simple:
            simple.append(gid)
    for gid in simple:
        _assert_brackets(
            glyph_unit_box(program, parsed, gid),
            _oracle(program, sfnt.upem, gid),
            gid,
        )


def test_padded_point_box_brackets_the_oracle_on_composite_glyphs(
    program: bytes, sfnt: _Sfnt
) -> None:
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    _, composite = _sample_gids(sfnt, 0, 30)
    assert len(composite) == 30
    for gid in composite:
        _assert_brackets(
            glyph_unit_box(program, parsed, gid),
            _oracle(program, sfnt.upem, gid),
            gid,
        )


def test_lsb_differs_from_xmin_glyphs_are_covered_exactly(
    program: bytes, sfnt: _Sfnt
) -> None:
    """The shift, not the pad, is what covers these — assert it tightly."""
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    mismatched = _lsb_mismatch_gids(sfnt)
    assert len(mismatched) >= 2, "fixture face must exercise the lsb shift"
    for gid in mismatched:
        oracle = _oracle(program, sfnt.upem, gid)
        box = glyph_unit_box(program, parsed, gid)
        assert box.reason is None, f"gid {gid}: {box.reason}"
        assert box.units is not None
        assert box.units == (
            oracle[0] - PAD,
            oracle[1] - PAD,
            oracle[2] + PAD,
            oracle[3] + PAD,
        ), f"gid {gid}: {box.units} is not the oracle {oracle} padded by {PAD}"


def test_left_side_bearing_comes_from_the_hmtx_tail_array(
    program: bytes, sfnt: _Sfnt
) -> None:
    """``hmtx`` tails with ``leftSideBearing[]``; only the ADVANCE falls back
    to the last ``hMetrics`` entry.  Reading the last metric's lsb instead
    misses the ink of every gid past ``numberOfHMetrics``."""
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    tail_gids = [
        gid
        for gid in range(sfnt.num_h_metrics, sfnt.num_glyphs)
        if sfnt.glyph_bytes(gid)
    ]
    assert tail_gids, "fixture face must have a gid past numberOfHMetrics"
    for gid in tail_gids:
        oracle = _oracle(program, sfnt.upem, gid)
        _assert_brackets(glyph_unit_box(program, parsed, gid), oracle, gid)
    # The rejected rule is not merely different: it under-bounds.
    header = sfnt.header_box(tail_gids[0])
    assert header is not None
    wrong_shift = sfnt.lsb_from_last_metric(tail_gids[0]) - header[0]
    right_shift = sfnt.lsb_from_tail_array(tail_gids[0]) - header[0]
    assert abs(wrong_shift - right_shift) > PAD


# ------------------------------------------------------ header cross-check


def _zero_header(sfnt: _Sfnt, gid: int) -> bytes:
    """A copy of the program whose ``gid`` header box reads (0, 0, 1, 1)."""
    at = sfnt.glyf + sfnt.loca[gid] + 2
    out = bytearray(sfnt.data)
    out[at : at + 8] = (
        (0).to_bytes(2, "big", signed=True)
        + (0).to_bytes(2, "big", signed=True)
        + (1).to_bytes(2, "big", signed=True)
        + (1).to_bytes(2, "big", signed=True)
    )
    return bytes(out)


@pytest.mark.parametrize("shape", ["simple", "composite"])
def test_a_zeroed_glyph_header_refuses_rather_than_bounding(
    program: bytes, sfnt: _Sfnt, shape: str
) -> None:
    simple, composite = _sample_gids(sfnt, 40, 5)
    gid = (simple if shape == "simple" else composite)[-1]
    mutated = _zero_header(sfnt, gid)
    parsed = parse_truetype_glyph_program(mutated)
    assert parsed is not None
    box = glyph_unit_box(mutated, parsed, gid)
    assert box.units is None
    assert box.reason == "glyf_header_disagrees"
    # MuPDF ignores the header entirely: the outline is still there, so a
    # header-trusting reader would have under-bounded real ink silently.
    oracle = _oracle(mutated, sfnt.upem, gid)
    assert oracle[2] - oracle[0] > 1.0


# ---------------------------------------------------- synthesised composite


def _build_composite(
    first: int, second: int, *, scaled_offset: bool, self_ref_host: int | None = None
) -> bytes:
    """Two components; the second at (100, 50) under a 1.5x scale."""
    out = bytearray((-1).to_bytes(2, "big", signed=True) + b"\x00" * 8)
    flags = _ARG_1_AND_2_ARE_WORDS | _ARGS_ARE_XY_VALUES | _MORE_COMPONENTS
    out += flags.to_bytes(2, "big")
    out += (self_ref_host if self_ref_host is not None else first).to_bytes(2, "big")
    out += (0).to_bytes(2, "big", signed=True) * 1
    out += (0).to_bytes(2, "big", signed=True)
    flags = (
        _ARG_1_AND_2_ARE_WORDS
        | _ARGS_ARE_XY_VALUES
        | _WE_HAVE_AN_X_AND_Y_SCALE
        | (_SCALED_COMPONENT_OFFSET if scaled_offset else 0)
    )
    out += flags.to_bytes(2, "big")
    out += second.to_bytes(2, "big")
    out += _COMPONENT_OFFSET[0].to_bytes(2, "big", signed=True)
    out += _COMPONENT_OFFSET[1].to_bytes(2, "big", signed=True)
    out += _F2DOT14_ONE_AND_A_HALF.to_bytes(2, "big", signed=True)
    out += _F2DOT14_ONE_AND_A_HALF.to_bytes(2, "big", signed=True)
    return bytes(out)


def _install_glyph(sfnt: _Sfnt, host: int, body: bytes, header: tuple) -> bytes:
    """Overwrite ``host``'s glyf slot in place (loca stays valid) and align
    its hmtx lsb with the header so the shift is zero."""
    patched = bytearray(body)
    for index, value in zip((2, 4, 6, 8), header):
        patched[index : index + 2] = int(value).to_bytes(2, "big", signed=True)
    start = sfnt.glyf + sfnt.loca[host]
    assert len(patched) <= sfnt.loca[host + 1] - sfnt.loca[host]
    out = bytearray(sfnt.data)
    out[start : start + len(patched)] = patched
    at = sfnt.hmtx + host * 4 + 2
    out[at : at + 2] = int(header[0]).to_bytes(2, "big", signed=True)
    return bytes(out)


def _widest_slot(sfnt: _Sfnt) -> int:
    return max(
        range(min(2000, sfnt.num_glyphs)),
        key=lambda gid: sfnt.loca[gid + 1] - sfnt.loca[gid],
    )


@pytest.mark.parametrize("scaled_offset", [False, True])
def test_synthesised_composite_matches_the_oracle_under_a_2x2_scale(
    program: bytes, sfnt: _Sfnt, scaled_offset: bool
) -> None:
    """SCALED_COMPONENT_OFFSET is HONOURED by MuPDF: the two readings put the
    box 50 units apart, so this case discriminates between them."""
    simple, _ = _sample_gids(sfnt, 8, 0)
    first, second = simple[4], simple[6]
    host = _widest_slot(sfnt)
    body = _build_composite(first, second, scaled_offset=scaled_offset)
    # Header from a first pass over an accurate-enough placeholder, then a
    # second install with the oracle-derived box (the module cross-checks it).
    probe = _install_glyph(sfnt, host, body, (-32768, -32768, 32767, 32767))
    oracle = _oracle(probe, sfnt.upem, host)
    header = (
        math.floor(oracle[0]),
        math.floor(oracle[1]),
        math.ceil(oracle[2]),
        math.ceil(oracle[3]),
    )
    mutated = _install_glyph(sfnt, host, body, header)
    parsed = parse_truetype_glyph_program(mutated)
    assert parsed is not None
    _assert_brackets(
        glyph_unit_box(mutated, parsed, host),
        _oracle(mutated, sfnt.upem, host),
        host,
    )


def test_the_two_component_offset_readings_are_far_apart(
    program: bytes, sfnt: _Sfnt
) -> None:
    """Guards the discrimination the previous test relies on: MuPDF really
    does move the component when SCALED_COMPONENT_OFFSET is set, by far more
    than the 1-unit pad could absorb."""
    simple, _ = _sample_gids(sfnt, 8, 0)
    host = _widest_slot(sfnt)
    boxes = []
    for scaled in (False, True):
        body = _build_composite(simple[4], simple[6], scaled_offset=scaled)
        probe = _install_glyph(sfnt, host, body, (-32768, -32768, 32767, 32767))
        boxes.append(_oracle(probe, sfnt.upem, host))
    assert boxes[1][2] - boxes[0][2] == pytest.approx(
        0.5 * _COMPONENT_OFFSET[0]
    ), f"{boxes[0]} vs {boxes[1]}"
    assert boxes[1][2] - boxes[0][2] > 2 * PAD


def test_a_self_referencing_composite_refuses(program: bytes, sfnt: _Sfnt) -> None:
    simple, _ = _sample_gids(sfnt, 8, 0)
    host = _widest_slot(sfnt)
    body = _build_composite(simple[4], simple[6], scaled_offset=False, self_ref_host=host)
    mutated = _install_glyph(sfnt, host, body, (0, 0, 100, 100))
    parsed = parse_truetype_glyph_program(mutated)
    assert parsed is not None
    box = glyph_unit_box(mutated, parsed, host)
    assert box.units is None
    assert box.reason == "composite_unsupported"


# ------------------------------------------------------------ closed slugs


def test_gid_at_or_past_num_glyphs_is_out_of_range(program: bytes) -> None:
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    for gid in (parsed.num_glyphs, parsed.num_glyphs + 1, -1):
        box = glyph_unit_box(program, parsed, gid)
        assert box.units is None
        assert box.reason == "gid_out_of_range"


def test_glyph_box_reasons_is_a_closed_ascii_tuple() -> None:
    assert isinstance(GLYPH_BOX_REASONS, tuple)
    assert set(GLYPH_BOX_REASONS) == {
        "glyf_unavailable",
        "glyf_parse_error",
        "glyf_header_disagrees",
        "glyf_degenerate",
        "composite_unsupported",
        "gid_out_of_range",
    }
    for slug in GLYPH_BOX_REASONS:
        assert slug.isascii() and slug.replace("_", "").isalnum()


def test_truncated_glyph_data_reports_a_parse_error(
    program: bytes, sfnt: _Sfnt
) -> None:
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    simple, _ = _sample_gids(sfnt, 8, 0)
    gid = simple[7]
    # Cut the program off inside gid's outline data.
    truncated = program[: sfnt.glyf + sfnt.loca[gid] + 12]
    box = glyph_unit_box(truncated, parsed, gid)
    assert box.units is None
    assert box.reason == "glyf_parse_error"


# ------------------------------------------------------- the cache surface


def _capability(fixture):
    capability = build_identity_h_cid_capability(fixture.doc, fixture.font_xref)
    assert hasattr(capability, "glyphs"), capability
    return capability


def test_cache_serves_the_same_box_as_the_free_function() -> None:
    fixture = build_identity_h_fixture()
    try:
        capability = _capability(fixture)
        cache = GlyphBoxCache()
        data = read_embedded_font_program(fixture.doc, fixture.font_xref)
        assert data is not None
        parsed = parse_truetype_glyph_program(data)
        assert parsed is not None
        sf = _Sfnt(data)
        simple, _ = _sample_gids(sf, 5, 0)
        for gid in simple:
            served = cache.box(fixture.doc, capability, gid)
            assert served.reason is None and served.units is not None
            assert served == glyph_unit_box(data, parsed, gid)
    finally:
        fixture.doc.close()


def test_an_otto_program_reports_glyf_unavailable() -> None:
    fixture = build_identity_h_fixture()
    try:
        capability = _capability(fixture)
        assert GlyphBoxCache().box(fixture.doc, capability, 5).reason is None
        fixture.doc.update_stream(
            fontfile2_xref(fixture), b"OTTO" + b"\x00" * 64, compress=False
        )
        box = GlyphBoxCache().box(fixture.doc, capability, 5)
        assert box.units is None
        assert box.reason == "glyf_unavailable"
    finally:
        fixture.doc.close()


def test_the_program_stream_is_fetched_once_per_font(monkeypatch) -> None:
    fixture = build_identity_h_fixture()
    try:
        capability = _capability(fixture)
        target = fontfile2_xref(fixture)
        cache = GlyphBoxCache()
        fetches: list[int] = []
        original = fitz.Document.xref_stream

        def counting(self, xref, *args, **kwargs):
            if xref == target:
                fetches.append(xref)
            return original(self, xref, *args, **kwargs)

        monkeypatch.setattr(fitz.Document, "xref_stream", counting)
        cache.box(fixture.doc, capability, 5)
        after_first = len(fetches)
        assert after_first >= 1
        for gid in (6, 7, 8, 5):
            cache.box(fixture.doc, capability, gid)
        assert len(fetches) == after_first, (
            "the one-slot program memo must serve every further gid of the "
            "same font without re-fetching its stream"
        )
    finally:
        fixture.doc.close()


def test_cache_invalidates_when_the_font_program_is_rewritten() -> None:
    """The xref does not move — only the bytes behind it — so the digest in
    the key is what has to catch this.  The rewrite stays a PARSEABLE
    program, or the capability could not be rebuilt to ask again."""
    fixture = build_identity_h_fixture()
    try:
        capability = _capability(fixture)
        cache = GlyphBoxCache()
        gid = 5
        first = cache.box(fixture.doc, capability, gid)
        assert first.reason is None and first.units is not None
        sf = _Sfnt(read_embedded_font_program(fixture.doc, fixture.font_xref))
        fixture.doc.update_stream(
            fontfile2_xref(fixture), _zero_header(sf, gid), compress=False
        )
        rebuilt = _capability(fixture)
        assert rebuilt.evidence_digest != capability.evidence_digest
        second = cache.box(fixture.doc, rebuilt, gid)
        assert second.units is None
        assert second.reason == "glyf_header_disagrees"
        # ...and the stale key still answers with the box it was built from.
        assert cache.box(fixture.doc, capability, gid) == first
    finally:
        fixture.doc.close()


def test_registry_owns_a_glyph_box_cache_cleared_by_bump_generation() -> None:
    fixture = build_identity_h_fixture()
    try:
        registry = DocumentFontRegistry(fixture.doc)
        capability = _capability(fixture)
        assert registry.glyph_boxes.box(fixture.doc, capability, 5).reason is None
        assert registry.glyph_boxes.cached_count > 0
        registry.bump_generation()
        assert registry.glyph_boxes.cached_count == 0
    finally:
        fixture.doc.close()


# ------------------------------------------------------- a second upem


def test_a_second_units_per_em_face_brackets_the_oracle_too() -> None:
    """A different face, a different upem, and — the reason this cell earns
    its keep — the SHORT ``loca`` format the fixture face never exercises."""
    if not tricky_font_available():
        pytest.skip("the alternative TrueType face is not installed here")
    fixture = build_face_fixture(TRICKY_FONT_PATH, CJK_TEXT)
    try:
        data = read_embedded_font_program(fixture.doc, fixture.font_xref)
        if not data:
            pytest.skip("alternative face is not embedded as FontFile2")
        parsed = parse_truetype_glyph_program(data)
        if parsed is None:
            pytest.skip("alternative face is CFF, not a glyf program")
        sf = _Sfnt(data)
        assert sf.upem != 256, "this cell must exercise a second units-per-em"
        assert parsed.index_to_loc_format == 0, "and the short loca format"
        simple, _ = _sample_gids(sf, 20, 0)
        assert simple
        for gid in simple:
            _assert_brackets(
                glyph_unit_box(data, parsed, gid), _oracle(data, sf.upem, gid), gid
            )
    finally:
        fixture.doc.close()


# ------------------------------------------------ the extended sfnt pass


def test_glyph_program_carries_the_re_addressing_fields(
    program: bytes, sfnt: _Sfnt
) -> None:
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    assert parsed.units_per_em == sfnt.upem
    assert parsed.index_to_loc_format in (0, 1)
    assert parsed.glyf_offset == sfnt.glyf
    assert parsed.hmtx_offset == sfnt.hmtx
    assert parsed.number_of_h_metrics == sfnt.num_h_metrics
    # The existing contract is unchanged.
    assert parsed.num_glyphs == sfnt.num_glyphs
    assert parsed.glyf_length == sfnt.tables[b"glyf"][1]
    assert len(parsed.loca) == sfnt.num_glyphs + 1
