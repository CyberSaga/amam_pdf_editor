"""Card B2 (design plan Step 3, scanner G): ``model/vector_paths/scan.py::scan_page(accelerated=False)``.

Red first.  O-scan (MuPDF's own drawings) judges every twin and rotation; the builder's own byte marks
pin the offset convention; raw fixtures pin each flag, each refusal, the inline-image stop (H13), the
bytes-only rule (D15), the path-lifetime rules (D17) and a linear-time guard.
"""

from __future__ import annotations

import hashlib
import math
import sys
import time
from collections.abc import Callable
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.pdf_content_ops import page_user_space_matrix  # noqa: E402
from model.vector_paths import scan as scan_mod  # noqa: E402
from model.vector_paths.scan import (  # noqa: E402
    PAINT_NAMES,
    PathFlag,
    VectorIndex,
    VectorPageRefused,
    VectorScanCancelled,
    scan_page,
)
from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_grammar as vg  # noqa: E402
from test_scripts import vector_index_rows as vir  # noqa: E402
from test_scripts import vector_oracle_extra as voe  # noqa: E402
from test_scripts import vector_oracle_scan as vos  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
F = PathFlag
_ROW_PAINT = {"S": "S", "s": "S", "f": "f", "F": "f", "f*": "f", "B": "B", "B*": "B", "b": "B", "b*": "B", "n": "n"}


# ----------------------------------------------------------------------------- helpers


def _scan(*streams: bytes, frame=IDENT6, **kw) -> VectorIndex:
    return scan_page(list(streams), frame, **kw)


def _flags(idx: VectorIndex) -> list[PathFlag]:
    return [PathFlag(int(f)) for f in idx.paths["flags"]]


def _rows(idx: VectorIndex) -> list[vir.IndexRow]:
    """The index as O-scan's rows (page space, so the oracle's own frame is the identity)."""
    out: list[vir.IndexRow] = []
    segs, cubs = idx.segments, idx.cubics
    by_path: dict[int, list[np.void]] = {}
    for c in cubs:  # grouped once: O(cubics), not O(paths x cubics)
        by_path.setdefault(int(c["path"]), []).append(c)
    for i, p in enumerate(idx.paths):
        a, n = int(p["seg_start"]), int(p["seg_count"])
        sl = segs[a : a + n]
        segments = tuple((float(s["x0"]), float(s["y0"]), float(s["x1"]), float(s["y1"]), bool(s["from_cubic"])) for s in sl)
        cubics = tuple((int(c["seg_start"]) - a, int(c["seg_count"]), tuple(float(v) for v in c["pts"])) for c in by_path.get(i, ()))
        out.append(vir.IndexRow(_ROW_PAINT[PAINT_NAMES[int(p["paint"])]], segments, cubics))
    return out


def _twin(scene: vfb.Scene, page: int = 0) -> tuple[bytes, list[bytes], tuple[float, ...], VectorIndex]:
    data = vfb.build(scene)
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[page]
    streams = [doc.xref_stream(x) or b"" for x in pg.get_contents()]
    frame = page_user_space_matrix(pg)
    assert frame is not None
    return data, streams, frame, scan_page(streams, frame)


def _raw_page(body: bytes, **page_kw) -> vfb.PageSpec:
    return vfb.PageSpec((vfb.RawSpec(body, "raw"),), **page_kw)


def _oscan_body(body: bytes) -> list[str]:
    data, _s, _f, idx = _twin(vfb.Scene((_raw_page(body),)))
    return vos.o_scan(data, _rows(idx), frame=IDENT6)


def _pages() -> list[tuple[str, vfb.PageSpec]]:
    base = vfb.sample_scene().pages[0]
    out = [("sample", base)]
    out += [(f"rot{r}", vfb.replace(base, rotate=r)) for r in (90, 180, 270)]
    out.append(("cropbox", vfb.replace(base, cropbox=(10.0, 20.0, 150.0, 190.0))))
    out.append(("userunit2", vfb.replace(base, userunit=2.0)))
    out.append(("rot90_cropbox_uu", vfb.replace(base, rotate=90, cropbox=(10.0, 20.0, 150.0, 190.0), userunit=2.0)))
    out.append(("merged_pair", voe.merged_pair_page()))
    return out


# ----------------------------------------------------------------------------- O-scan on the twins


@pytest.mark.parametrize("name,page", _pages(), ids=[n for n, _ in _pages()])
def test_o_scan_on_every_page_frame(name: str, page: vfb.PageSpec) -> None:
    data, _streams, frame, idx = _twin(vfb.Scene((page, vfb.sample_scene().pages[1])))
    assert vos.o_scan(data, _rows(idx), frame=IDENT6) == [], name
    assert vos.o_scan(data, vir.rows_from_page(page), frame=vir.frame_of(page)) == []  # the builder's rows agree


@pytest.mark.parametrize("name,page", _pages(), ids=[n for n, _ in _pages()])
def test_page_user_space_matrix_equals_the_builder_frame(name: str, page: vfb.PageSpec) -> None:
    """Step 3 pins the mapping on /Rotate 90/180/270, an offset CropBox and /UserUnit 2."""
    doc = fitz.open(stream=vfb.build(vfb.Scene((page,))), filetype="pdf")
    got = page_user_space_matrix(doc[0])
    assert got is not None
    assert all(abs(a - b) < 1e-9 for a, b in zip(got, vir.frame_of(page), strict=True)), (got, vir.frame_of(page))


@pytest.mark.parametrize("name,scene", vfb.default_scenes(), ids=[n for n, _ in vfb.default_scenes()])
def test_o_scan_on_every_topology_twin(name: str, scene: vfb.Scene) -> None:
    data, streams, _frame, idx = _twin(scene)
    assert vos.o_scan(data, _rows(idx), frame=IDENT6) == [], name
    assert [int(s["length"]) for s in idx.streams] == [len(s) for s in streams]


@pytest.mark.parametrize("seed", range(40))
def test_o_scan_on_grammar_scenes(seed: int) -> None:
    scene = vg.random_scene(seed)
    data, _streams, _frame, idx = _twin(scene)
    assert vos.o_scan(data, _rows(idx), frame=IDENT6) == [], seed


def test_o_scan_curves_v_y_re_closepath_under_a_rotating_cm() -> None:
    bodies = [
        b"q 0.6 0.8 -0.8 0.6 40 20 cm 10 10 m 20 40 60 40 v S Q",
        b"q 0.6 0.8 -0.8 0.6 40 20 cm 10 10 m 20 40 60 40 y S Q",
        b"q 0.6 0.8 -0.8 0.6 40 20 cm 10 10 40 30 re S Q",
        b"q 0.6 0.8 -0.8 0.6 40 20 cm 10 10 m 30 5 60 60 90 10 c f Q",
        b"0 0 m 10 0 l 10 10 l h S",
        b"0 0 m 10 0 l 10 10 l s",
        b"0 0 m 10 0 l 10 10 l b",
        b"0 0 m 10 0 l 10 10 l f",
        b"0 0 m 10 0 l 0 0 l h S",
        b"0 0 m 10 0 l 20 20 m 30 20 l h S",
        b"5 5 m h S",
        b"q 2 0 0 2 0 0 cm 1 0 0 1 3 4 cm 10 10 m 40 40 l S Q",
    ]
    for body in bodies:
        assert _oscan_body(body) == [], body


# ----------------------------------------------------------------------------- offsets (B6 depends on them)


def _marks_for(page: vfb.PageSpec) -> tuple[list[tuple[int, int]], dict]:
    emit = vfb._emit_page(page)
    starts = [0]
    for s in emit.streams:
        starts.append(starts[-1] + len(s))
    return [(starts[i], len(s)) for i, s in enumerate(emit.streams)], emit.marks


@pytest.mark.parametrize("name,scene", vfb.default_scenes(), ids=[n for n, _ in vfb.default_scenes()])
def test_offsets_equal_the_builders_byte_marks(name: str, scene: vfb.Scene) -> None:
    page = scene.pages[0]
    _data, _streams, _frame, idx = _twin(scene)
    starts, marks = _marks_for(page)
    path_items = [i for i, it in enumerate(page.items) if isinstance(it, vfb.PathSpec)]
    assert len(idx.paths) == len(path_items)
    for row, item in zip(idx.paths, path_items, strict=True):
        m = marks[item]
        g = starts[m.stream][0]
        assert int(row["path_start"]) == g + m.start, (name, item)
        assert int(row["paint_end"]) == g + m.end, (name, item)
        if page.items[item].state.shape == "block":  # type: ignore[union-attr]
            blk = idx.blocks[int(row["block"])]
            assert (int(blk["q_start"]), int(blk["q_end"])) == (g + m.q_start, g + m.q_end), (name, item)  # type: ignore[operator]
        else:
            assert int(row["block"]) == -1
    assert idx.indexed_end == sum(len(s) for s in vfb._emit_page(page).streams)
    assert idx.stopped_at_inline_image is False


def test_span_ends_with_its_paint_operator_and_starts_at_its_first_operand() -> None:
    body = b"1 0 0 1 5 5 cm 12 13 m 40 41 l S  q 0 0 5 5 re f Q 7 8 9 10 re B* 1.5 2 m 3 4 5 6 7 8 c b"
    idx = _scan(body)
    spans = [body[int(r["path_start"]) : int(r["paint_end"])] for r in idx.paths]
    assert spans == [b"12 13 m 40 41 l S", b"0 0 5 5 re f", b"7 8 9 10 re B*", b"1.5 2 m 3 4 5 6 7 8 c b"]
    assert [PAINT_NAMES[int(p)] for p in idx.paths["paint"]] == ["S", "f", "B*", "b"]


# ----------------------------------------------------------------------------- traps: strings, comments, names, dicts


@pytest.mark.parametrize(
    "body",
    [
        b"(0 0 m 9 9 l S) Tj",
        b"(a \\) 0 0 m 9 9 l S \\( b) Tj",
        b"((0 0 m 9 9 l S)) Tj",
        b"<30 30 6d 20 39 20 39 20 6c 20 53> Tj",
        b"% 0 0 m 9 9 l S\n",
        b"% 0 0 m 9 9 l S",
        b"/A << /K (0 0 m 9 9 l S) /L <00> >> BDC EMC",
        b"/BI /BT /ET /ID /EI pop",
        b"[(0 0 m 9 9 l S)] TJ [ [ ] ] 1 2 3",
        b"BT /F1 12 Tf 10 100 Td (S Q q f) Tj ET",
    ],
)
def test_no_record_from_string_comment_name_or_dictionary_traps(body: bytes) -> None:
    idx = _scan(body)
    assert len(idx.paths) == 0
    assert idx.indexed_end == len(body)
    assert idx.stopped_at_inline_image is False


def test_traps_do_not_hide_the_real_records_after_them() -> None:
    body = b"(S) Tj % 0 0 m 9 9 l S\n 1 1 m 2 2 l S /A <</K (>>) /L <41>>> BDC 3 3 m 4 4 l S EMC <</A <41>>> pop 5 5 m 6 6 l f"
    idx = _scan(body)
    assert [body[int(r["path_start"]) : int(r["paint_end"])] for r in idx.paths] == [b"1 1 m 2 2 l S", b"3 3 m 4 4 l S", b"5 5 m 6 6 l f"]


def test_a_dictionary_ends_at_its_matching_double_angle_bracket() -> None:
    body = b"/OC <</A <41>>> BDC 0 0 m 5 5 l S EMC 1 1 m 2 2 l S"
    idx = _scan(body)
    assert len(idx.paths) == 2
    assert _flags(idx)[0] & F.IN_OC and not _flags(idx)[1] & F.IN_OC


def test_names_that_look_like_text_or_image_words_start_nothing() -> None:
    body = b"/BT /BI /ID /EI /ET pop 0 0 m 5 5 l S"
    idx = _scan(body)
    assert len(idx.paths) == 1 and idx.stopped_at_inline_image is False


# ----------------------------------------------------------------------------- inline image (D14 revision 2, H13)


def test_inline_image_stops_the_scan_at_its_bi_and_leaves_rows_before_it_intact() -> None:
    before = b"0 0 m 5 5 l S q 1 1 m 2 2 l f Q "
    body = before + b"BI /W 1 /H 1 /IM true /BPC 1 ID \x00 EI \x00 EI Q\n 7 7 m 8 8 l S"
    idx = _scan(body)
    assert idx.indexed_end == len(before) and idx.stopped_at_inline_image is True
    assert len(idx.paths) == 2 and int(idx.paths["paint_end"][-1]) <= idx.indexed_end
    plain = _scan(before)
    assert plain.paths.tobytes() == idx.paths.tobytes() and plain.segments.tobytes() == idx.segments.tobytes()


def test_inline_image_without_ei_stops_at_bi() -> None:
    body = b"0 0 m 1 1 l S BI /W 1 ID abc 1 1 m 2 2 l S"
    idx = _scan(body)
    assert idx.indexed_end == body.index(b"BI") and len(idx.paths) == 1 and idx.stopped_at_inline_image


def test_bi_inside_a_string_or_comment_does_not_stop_the_scan() -> None:
    idx = _scan(b"(BI) Tj % BI\n 0 0 m 1 1 l S")
    assert len(idx.paths) == 1 and idx.stopped_at_inline_image is False
    idx2 = _scan(b"(a(BI)b) Tj <4249> Tj 0 0 m 1 1 l S")
    assert len(idx2.paths) == 1 and idx2.stopped_at_inline_image is False


def test_the_text_commit_payload_scanner_is_never_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    from model.text_commit import pdf_lexer

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("scan_page must not call _scan_inline_image_payload")

    monkeypatch.setattr(pdf_lexer, "_scan_inline_image_payload", boom)
    idx = _scan(b"0 0 m 1 1 l S BI /W 1 /H 1 ID \x00 EI Q 2 2 m 3 3 l S")
    assert len(idx.paths) == 1 and idx.stopped_at_inline_image


def test_a_stop_in_the_first_stream_leaves_the_later_streams_unindexed() -> None:
    idx = _scan(b"0 0 m 1 1 l S BI ID x EI ", b"2 2 m 3 3 l S")
    assert len(idx.paths) == 1 and idx.stopped_at_inline_image and idx.indexed_end == len(b"0 0 m 1 1 l S ")


# ----------------------------------------------------------------------------- bytes only (D15)


def test_a_gs_makes_the_line_width_nan_until_the_next_w_or_the_restoring_q() -> None:
    body = b"3 w 0 0 m 1 1 l S /G0 gs 0 0 m 1 1 l S 4 w 0 0 m 1 1 l S q /G0 gs 5 w Q 0 0 m 1 1 l S q /G0 gs 0 0 m 1 1 l S Q 0 0 m 1 1 l S"
    w = [float(v) for v in _scan(body).paths["line_width"]]
    assert w[0] == 3.0 and math.isnan(w[1]) and w[2] == 4.0 and w[3] == 4.0 and math.isnan(w[4]) and w[5] == 4.0


def test_line_width_is_in_page_units_through_the_paint_time_ctm_and_frame() -> None:
    idx = _scan(b"2 w q 3 0 0 3 0 0 cm 0 0 m 1 1 l S Q", frame=(2.0, 0.0, 0.0, -2.0, 0.0, 100.0))
    assert abs(float(idx.paths["line_width"][0]) - 12.0) < 1e-5  # 2 * 3 * 2
    assert _scan(b"0 0 m 1 1 l S").paths["line_width"][0] == 1.0  # the PDF default


def test_equal_decoded_bytes_with_different_resources_give_equal_tables() -> None:
    page = vfb.PageSpec((vfb.RawSpec(b"/GS0 gs 0 0 m 9 9 l S", "raw"),))
    a = vfb.build(vfb.Scene((page,)))
    b = a.replace(b"/LW 1", b"/LW 7")
    assert a != b
    out = []
    for blob in (a, b):
        doc = fitz.open(stream=blob, filetype="pdf")
        pg = doc[0]
        out.append(scan_page([doc.xref_stream(x) or b"" for x in pg.get_contents()], page_user_space_matrix(pg)))
    assert _same(out[0], out[1])


def _same(a: VectorIndex, b: VectorIndex) -> bool:
    for name in ("paths", "cubics", "segments", "blocks", "streams"):
        if getattr(a, name).tobytes() != getattr(b, name).tobytes():  # NaN-safe
            return False
    return (a.indexed_end, a.stopped_at_inline_image, a.frame, a.stream_digests) == (b.indexed_end, b.stopped_at_inline_image, b.frame, b.stream_digests)


def test_ctm_column_is_the_user_space_ctm_without_the_frame() -> None:
    idx = _scan(b"2 0 0 2 10 20 cm q 1 0 0 1 3 4 cm 0 0 m 1 1 l S Q", frame=(1.0, 0.0, 0.0, -1.0, 0.0, 200.0))
    # in-q cm: translate(3,4) then outer (2,0,0,2,10,20): e = 3*2+10 = 16, f = 4*2+20 = 28
    assert [float(v) for v in idx.paths["ctm"][0]] == [2.0, 0.0, 0.0, 2.0, 16.0, 28.0]
    seg = idx.segments[0]
    assert (float(seg["x0"]), float(seg["y0"])) == (16.0, 200.0 - 28.0)


# ----------------------------------------------------------------------------- flags (section 4.4)


def test_a_plain_path_is_editable_and_nothing_else() -> None:
    idx = _scan(b"0 0 m 9 9 l S")
    assert _flags(idx) == [F.EDITABLE]
    bb = idx.paths["bbox"][0]
    assert bb[0] <= 0 and bb[1] <= 0 and bb[2] >= 9 and bb[3] >= 9 and bb[2] - 9 < 1e-5  # widened by a float32 step at most


def test_degenerate_has_no_segment_and_is_still_a_row() -> None:
    idx = _scan(b"5 5 m S 5 5 m h S")
    assert len(idx.paths) == 2 and len(idx.segments) == 0
    assert all(f & F.DEGENERATE for f in _flags(idx)) and all(int(c) == 0 for c in idx.paths["seg_count"])


def test_clip_paths_set_clip_and_later_paths_are_clipped_until_the_restoring_q() -> None:
    idx = _scan(b"q 0 0 5 5 re W n Q 0 0 m 1 1 l S 0 0 5 5 re W* n 2 2 m 3 3 l S q 4 4 m 5 5 l S Q")
    fl = _flags(idx)
    assert fl[0] & F.SETS_CLIP and not fl[0] & F.EDITABLE
    assert not fl[1] & F.CLIPPED and fl[1] & F.EDITABLE
    assert fl[2] & F.SETS_CLIP
    assert fl[3] & F.CLIPPED and fl[3] & F.EDITABLE and fl[4] & F.CLIPPED


def test_a_clip_inside_a_q_does_not_clip_paths_after_the_q() -> None:
    idx = _scan(b"q 0 0 5 5 re W n 1 1 m 2 2 l S Q 3 3 m 4 4 l S")
    fl = _flags(idx)
    assert fl[1] & F.CLIPPED and not fl[2] & F.CLIPPED


def test_text_render_mode_4_to_7_clips_from_et_until_the_restoring_q() -> None:
    idx = _scan(b"q BT 7 Tr (x) Tj ET 0 0 m 1 1 l S Q 2 2 m 3 3 l S BT 3 Tr (x) Tj ET 4 4 m 5 5 l S BT 4 Tr ET 6 6 m 7 7 l S")
    fl = _flags(idx)
    assert fl[0] & F.CLIPPED and not fl[1] & F.CLIPPED and not fl[2] & F.CLIPPED
    assert not fl[3] & F.CLIPPED  # BT 4 Tr ET shows no glyph: nothing is added to the clip (Astra B2 P2)
    mid = _scan(b"BT 7 Tr (x) Tj 0 0 m 1 1 l S ET")  # no clip yet inside the object (and the path is impure)
    assert not _flags(mid)[0] & F.CLIPPED


def test_impure_records() -> None:
    idx = _scan(b"0 0 m 1 1 l 1 0 0 1 5 5 cm S 0 0 m BT ET 3 3 l S 0 0 m 1 1 l /X Do S 0 0 m 1 1 l 2 w S 0 0 m 1 1 l S")
    fl = _flags(idx)
    assert [bool(f & F.IMPURE) for f in fl] == [True, True, True, True, False]
    assert all(not f & F.EDITABLE for f in fl[:4]) and fl[4] & F.EDITABLE


def test_a_record_that_crosses_a_q_or_q_boundary_is_impure() -> None:
    idx = _scan(b"q 0 0 m 9 9 l S 5 5 m 6 6 l Q S 0 0 m 9 9 l q 1 0 0 1 5 5 cm S Q")
    fl = _flags(idx)
    assert [bool(f & F.IMPURE) for f in fl] == [False, True, True]


def test_spans_streams() -> None:
    idx = _scan(b"0 0 m 1 1 l S 0 0 m 1", b"2 l S 5 5 m 6 6 l S")
    fl = _flags(idx)
    assert not fl[0] & F.SPANS_STREAMS and fl[1] & F.SPANS_STREAMS and not fl[1] & F.EDITABLE and not fl[2] & F.SPANS_STREAMS
    assert int(idx.paths["path_start"][1]) < len(b"0 0 m 1 1 l S 0 0 m 1") <= int(idx.paths["paint_end"][1])


def test_streams_do_not_join_tokens_and_state_carries_across_streams() -> None:
    idx = _scan(b"q 2 0 0 2 0 0 cm 0 0 m 5", b"5 l S")  # "5" and "5" are two numbers, not 55
    seg = idx.segments[0]
    assert (float(seg["x1"]), float(seg["y1"])) == (10.0, 10.0)
    assert [int(s["global_start"]) for s in idx.streams] == [0, len(b"q 2 0 0 2 0 0 cm 0 0 m 5")]
    assert idx.indexed_end == len(b"q 2 0 0 2 0 0 cm 0 0 m 5") + len(b"5 l S")
    closed = _scan(b"q 1 0 0 1 0 0 cm ", b"0 0 m 1 1 l S Q")
    assert len(closed.blocks) == 1 and closed.blocks["inert"][0] == False  # noqa: E712  (a block over two streams is never inert)


def test_marked_content_oc_pairs_by_depth_not_by_q() -> None:
    inside_q = _scan(b"q /OC /M BDC 0 0 m 1 1 l S Q 2 2 m 3 3 l S EMC 4 4 m 5 5 l S")
    assert [bool(f & F.IN_OC) for f in _flags(inside_q)] == [True, True, False]
    before_q = _scan(b"/OC /M BDC q 0 0 m 1 1 l S EMC 2 2 m 3 3 l S Q 4 4 m 5 5 l S")
    assert [bool(f & F.IN_OC) for f in _flags(before_q)] == [True, False, False]
    nested = _scan(b"/Span BMC /OC /M BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S EMC 4 4 m 5 5 l S /Span BMC /Tx /M BDC 6 6 m 7 7 l S EMC EMC")
    assert [bool(f & F.IN_OC) for f in _flags(nested)] == [True, False, False, False]
    assert not _flags(nested)[0] & F.EDITABLE and _flags(nested)[1] & F.EDITABLE


def test_unbalanced_emc_refuses_the_page() -> None:
    with pytest.raises(VectorPageRefused) as e:
        _scan(b"0 0 m 1 1 l S EMC")
    assert e.value.code == "SCAN_ERROR"


def test_ctm_singular() -> None:
    idx = _scan(b"q 0 0 0 0 5 5 cm 0 0 m 1 1 l S Q q 1 2 2 4 0 0 cm 0 0 m 1 1 l S Q 0 0 m 1 1 l S")
    fl = _flags(idx)
    assert fl[0] & F.CTM_SINGULAR and fl[1] & F.CTM_SINGULAR and not fl[2] & F.CTM_SINGULAR
    assert not fl[0] & F.EDITABLE and fl[2] & F.EDITABLE


def test_page_anchored_from_gs_and_non_device_colour_spaces_scoped_by_q() -> None:
    idx = _scan(
        b"q /G0 gs 0 0 m 1 1 l S Q 0 0 m 1 1 l S "
        b"q /Pattern cs /P1 scn 0 0 m 1 1 l f Q /DeviceRGB cs 1 0 0 sc 0 0 m 1 1 l f "
        b"q /CS0 CS 0 0 m 1 1 l S Q 0 0 m 1 1 l S /DeviceCMYK CS /DeviceGray cs 0 0 m 1 1 l B"
    )
    fl = _flags(idx)
    assert [bool(f & F.PAGE_ANCHORED) for f in fl] == [True, False, True, False, True, False, False]
    assert all(f & F.EDITABLE for f in fl)  # delete is allowed on an anchored path


def test_every_flag_value_is_distinct_and_fits_uint16() -> None:
    vals = [int(f) for f in PathFlag]
    assert len(set(vals)) == len(vals) == 9 and max(vals) < 2**16
    assert [f.name for f in PathFlag] == ["EDITABLE", "DEGENERATE", "SETS_CLIP", "CLIPPED", "IMPURE", "SPANS_STREAMS", "IN_OC", "CTM_SINGULAR", "PAGE_ANCHORED"]


# ----------------------------------------------------------------------------- path lifetime and blocks (D17)


def _blocks(body: bytes) -> VectorIndex:
    return _scan(body)


@pytest.mark.parametrize(
    "body",
    [
        b"q 0 0 m 9 9 l S 5 5 m 6 6 l Q S",  # an open path at the Q
        b"0 0 m 9 9 l q 1 0 0 1 5 5 cm S Q",  # an open path at the q
        b"q 0 0 5 5 re W n Q",  # a clip
        b"q /Sh sh Q",  # a shading
        b"q 0 0 m 1 1 l S BT ET 2 2 m 3 3 l S Q",  # text between two paths
        b"q 0 0 m 1 1 l S frobnicate Q",  # an unknown operator
        b"q 0 0 m 1 1 l S /Im Do Q",
        b"q 1 0 0 1 0 0 cm Q",  # no paint
        b"q 0 0 m 1 1 l n Q",  # a paint with n
        b"q /OC /M BDC 0 0 m 1 1 l S EMC Q",
        b"q (s) Tj 0 0 m 1 1 l S Q",
        b"q S 0 0 m 1 1 l S Q",  # a stray paint: records != paints
    ],
)
def test_block_is_not_inert(body: bytes) -> None:
    idx = _blocks(body)
    assert len(idx.blocks) == 1
    assert not bool(idx.blocks["inert"][0]), body


@pytest.mark.parametrize(
    "body,paints,cms",
    [
        (b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q", 1, 1),
        (b"q 0 0 m 9 9 l S 1 0 0 rg 2 2 m 3 3 l f Q", 2, 0),
        (b"q [4 2] 0 d 1 J 1 j 10 M 0 g 0 G 1 0 0 rg 1 0 0 RG 0 0 0 0 k 0 0 0 0 K /DeviceRGB cs /DeviceRGB CS 1 1 1 sc 1 1 1 SC /P scn /P SCN /RI ri 1 i /G0 gs 3 w 0 0 m 1 1 l 2 2 3 3 4 4 c h 0 0 1 1 re f* Q", 1, 0),
        (b"q 1 0 0 1 0 0 cm 2 0 0 2 0 0 cm 0 0 m 1 1 l B Q", 1, 2),
    ],
)
def test_block_is_inert_when_only_allowlisted_operators_and_whole_records(body: bytes, paints: int, cms: int) -> None:
    idx = _blocks(body)
    assert len(idx.blocks) == 1
    b = idx.blocks[0]
    assert bool(b["inert"]) and int(b["n_paints"]) == paints and int(b["n_cm"]) == cms, body
    assert int(b["q_start"]) == 0 and int(b["q_end"]) == len(body)
    assert all(int(x) == 0 for x in idx.paths["block"])


def test_cm_operand_range_of_a_block() -> None:
    body = b"  q 1 0 0 1 5 7.5 cm 0 0 m 9 9 l S Q"
    b = _scan(body).blocks[0]
    assert body[int(b["cm_operand_start"]) : int(b["cm_operand_end"])] == b"1 0 0 1 5 7.5"


def test_blocks_are_leaf_pairs_and_non_leaf_paths_have_no_block() -> None:
    body = b"0 0 m 1 1 l S q 2 2 m 3 3 l S q 4 4 m 5 5 l S Q 6 6 m 7 7 l S Q q 8 8 m 9 9 l S Q"
    idx = _scan(body)
    assert [int(b) for b in idx.paths["block"]] == [-1, -1, 0, -1, 1]
    assert [body[int(r["q_start"]) : int(r["q_end"])] for r in idx.blocks] == [b"q 4 4 m 5 5 l S Q", b"q 8 8 m 9 9 l S Q"]


def test_q_below_depth_zero_refuses_and_unclosed_q_gives_no_block() -> None:
    with pytest.raises(VectorPageRefused) as e:
        _scan(b"q Q Q")
    assert e.value.code == "SCAN_ERROR"
    idx = _scan(b"q 0 0 m 1 1 l S")
    assert len(idx.blocks) == 0 and int(idx.paths["block"][0]) == -1


# ----------------------------------------------------------------------------- geometry


def _bez(p: np.ndarray, t: np.ndarray) -> np.ndarray:
    u = 1 - t
    return (u**3)[:, None] * p[0] + (3 * u * u * t)[:, None] * p[1] + (3 * u * t * t)[:, None] * p[2] + (t**3)[:, None] * p[3]


def test_cubic_chords_follow_the_wang_count_within_epsilon_and_stay_exact_in_the_cubics_table() -> None:
    idx = _scan(b"10 10 m 40 90 70 -30 100 20 c S")
    pts = np.array(idx.cubics["pts"][0]).reshape(4, 2)
    assert [float(v) for v in pts.ravel()] == [10, 10, 40, 90, 70, -30, 100, 20]
    assert int(idx.cubics["path"][0]) == 0 and int(idx.cubics["seg_start"][0]) == 0
    n = vir.reference_chord_count([tuple(p) for p in pts], 0.01)
    assert int(idx.cubics["seg_count"][0]) == n == len(idx.segments) and n > 10
    assert bool(idx.segments["from_cubic"].all())
    t = np.linspace(0, 1, 100001)
    curve = _bez(pts, t)
    for s in idx.segments:  # every chord's midpoint is within eps of the curve
        mid = np.array([(s["x0"] + s["x1"]) / 2, (s["y0"] + s["y1"]) / 2])
        assert np.min(np.hypot(*(curve - mid).T)) < 0.01 + 1e-3
    assert [float(idx.segments["x0"][0]), float(idx.segments["y0"][0])] == [10.0, 10.0]
    assert [float(idx.segments["x1"][-1]), float(idx.segments["y1"][-1])] == [100.0, 20.0]
    assert np.allclose(idx.segments["x1"][:-1], idx.segments["x0"][1:])


def test_a_straight_cubic_is_one_chord_and_chords_are_counted_in_page_space() -> None:
    assert int(_scan(b"0 0 m 1 0 2 0 3 0 c S").cubics["seg_count"][0]) == 1
    uu = _scan(b"0 0 m 10 30 20 30 30 0 c S", frame=(2.0, 0.0, 0.0, -2.0, 0.0, 0.0))
    pts = np.array(uu.cubics["pts"][0]).reshape(4, 2)
    assert pts[3, 0] == 60.0  # control points are stored in page space
    assert int(uu.cubics["seg_count"][0]) == vir.reference_chord_count([tuple(p) for p in pts], 0.01)


def test_v_and_y_are_stored_as_full_cubics_and_re_is_four_lines_and_h_closes_only_when_open() -> None:
    idx = _scan(b"1 2 m 3 4 5 6 v S 1 2 m 3 4 5 6 y S 0 0 3 2 re f")
    assert [float(v) for v in idx.cubics["pts"][0]] == [1, 2, 1, 2, 3, 4, 5, 6]
    assert [float(v) for v in idx.cubics["pts"][1]] == [1, 2, 3, 4, 5, 6, 5, 6]
    assert [int(c) for c in idx.paths["seg_count"][2:]] == [4]
    h = _scan(b"0 0 m 10 0 l 10 10 l h S 0 0 m 10 0 l 0 0 l h S 0 0 m 10 0 l 10 10 l f 0 0 m 10 0 l 10 10 l s")
    assert [int(c) for c in h.paths["seg_count"]] == [3, 2, 2, 3]


def test_bbox_over_includes_the_control_polygon() -> None:
    idx = _scan(b"0 0 m 0 100 100 100 100 0 c S")
    bb = idx.paths["bbox"][0]
    assert bb[0] <= 0 and bb[1] <= 0 and bb[2] >= 100 and bb[3] >= 100
    assert bb.dtype == np.float32 and bb[3] - 100 < 1e-3


def test_page_space_segments_use_the_frame() -> None:
    idx = _scan(b"1 1 m 11 6 l S", frame=(1.0, 0.0, 0.0, -1.0, 3.0, 200.0))
    s = idx.segments[0]
    assert (float(s["x0"]), float(s["y0"]), float(s["x1"]), float(s["y1"])) == (4.0, 199.0, 14.0, 194.0)
    assert idx.frame == (1.0, 0.0, 0.0, -1.0, 3.0, 200.0)


# ----------------------------------------------------------------------------- tables, digests, shapes


def test_tables_have_the_columns_and_dtypes_of_section_4_1() -> None:
    idx = _scan(b"q 1 0 0 1 0 0 cm 0 0 m 1 1 l 2 2 3 3 4 4 c S Q")
    assert idx.paths.dtype.names == ("path_start", "paint_end", "block", "paint", "flags", "bbox", "line_width", "ctm", "seg_start", "seg_count")
    assert idx.paths.dtype["flags"] == np.uint16 and idx.paths.dtype["paint"] == np.uint8 and idx.paths.dtype["block"] == np.int32
    assert idx.paths.dtype["path_start"] == np.int64 and idx.paths.dtype["bbox"].base == np.float32 and idx.paths.dtype["ctm"].base == np.float64
    assert idx.segments.dtype.names == ("x0", "y0", "x1", "y1", "path", "from_cubic", "subpath")  # subpath: provisional 4.1 addition
    assert idx.segments.dtype["subpath"] == np.int32
    assert all(idx.segments.dtype[n] == np.float64 for n in ("x0", "y0", "x1", "y1")) and idx.segments.dtype["from_cubic"] == np.bool_
    assert idx.cubics.dtype.names == ("pts", "path", "seg_start", "seg_count") and idx.cubics.dtype["pts"].base == np.float64
    assert idx.blocks.dtype.names == ("q_start", "q_end", "n_paints", "inert", "n_cm", "cm_operand_start", "cm_operand_end")
    assert idx.streams.dtype.names == ("xref", "global_start", "length", "raw_key")
    assert idx.nbytes >= idx.paths.nbytes + idx.segments.nbytes + idx.cubics.nbytes + idx.blocks.nbytes


def test_stream_digests_and_stream_table() -> None:
    s1, s2 = b"0 0 m 1 1 l S", b"2 2 m 3 3 l f "
    idx = _scan(s1, s2)
    assert idx.stream_digests == (hashlib.sha256(s1).digest(), hashlib.sha256(s2).digest())
    assert [(int(r["global_start"]), int(r["length"])) for r in idx.streams] == [(0, len(s1)), (len(s1), len(s2))]
    assert int(idx.paths["path_start"][1]) == len(s1) + 0


def test_empty_and_missing_contents_give_empty_tables() -> None:
    for streams in ([], [b""], [b"", b"   \n"], [b"% only a comment"]):
        idx = scan_page(streams, IDENT6)
        assert len(idx.paths) == len(idx.segments) == len(idx.cubics) == len(idx.blocks) == 0
        assert len(idx.streams) == len(streams)
        assert idx.indexed_end == sum(len(s) for s in streams) and idx.stopped_at_inline_image is False
        assert idx.paths.dtype.names and idx.nbytes >= 0


def test_bad_input_types_raise_type_error() -> None:
    with pytest.raises(TypeError):
        scan_page(b"0 0 m 1 1 l S", IDENT6)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_page("0 0 m", IDENT6)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_page(None, IDENT6)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_page([b"x", "y"], IDENT6)  # type: ignore[list-item]
    with pytest.raises(TypeError):
        scan_page([b"x"], (1.0, 0.0, 0.0))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_page([b"x"], "abcdef")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        scan_page([b"x"], IDENT6, cancel=5)  # type: ignore[arg-type]


def test_frame_none_or_singular_refuses_no_frame() -> None:
    for frame in (None, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, float("nan"), 0.0)):
        with pytest.raises(VectorPageRefused) as e:
            scan_page([b"0 0 m 1 1 l S"], frame)  # type: ignore[arg-type]
        assert e.value.code == "NO_FRAME" and e.value.detail


def test_accelerated_scanner_is_f_inside_its_vocabulary_and_g_outside_it() -> None:
    fast = _scan(b"0 0 m 1 1 l S", accelerated=True)
    assert (fast.scanner, fast.accelerated) == ("F", True)
    masked = _scan(b"BT (x) Tj ET 0 0 m 1 1 l S", accelerated=True)  # strings and text are inside F's vocabulary since the mask stage
    assert (masked.scanner, masked.accelerated) == ("F", True)
    plain = _scan(b"0 0 m 1 1 l S BI /W 1 ID x EI", accelerated=True)  # an inline image: handed to G whole
    assert (plain.scanner, plain.accelerated) == ("G", False)  # full equality lives in test_vector_scan_fast.py


# ----------------------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    "body",
    [b"(abc", b"(a(b)c", b"(a\\", b"<41", b"<</A (x)", b"0 0 m 1.2.3 l S", b"--1 0 m 1 1 l S", b"1 0 0 1 +- 0 cm", b"0 0 m 1 l S", b"9" * 400 + b" 0 m"],
)
def test_scan_errors_refuse_the_page(body: bytes) -> None:
    with pytest.raises(VectorPageRefused) as e:
        _scan(body)
    assert e.value.code == "SCAN_ERROR" and e.value.detail


def test_page_refusal_exception_shape() -> None:
    err = VectorPageRefused("TOO_LARGE", "why")
    assert (err.code, err.detail) == ("TOO_LARGE", "why") and isinstance(err, Exception)


def test_cap_values_are_the_specified_ones() -> None:
    assert scan_mod.MAX_DECODED_BYTES == 256 * 1024 * 1024
    assert scan_mod.MAX_PAINTS == 4_000_000
    assert scan_mod.MAX_CHORD_ROWS == 8_000_000


def test_decoded_size_cap_is_checked_before_lexing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_mod, "MAX_DECODED_BYTES", 10)
    with pytest.raises(VectorPageRefused) as e:
        _scan(b"(unterminated and long")  # would be a SCAN_ERROR if it were lexed
    assert e.value.code == "TOO_LARGE"


def test_paint_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_mod, "MAX_PAINTS", 3)
    assert len(_scan(b"0 0 m 1 1 l S 0 0 m 1 1 l S 0 0 m 1 1 l S").paths) == 3
    with pytest.raises(VectorPageRefused) as e:
        _scan(b"0 0 m 1 1 l S 0 0 m 1 1 l S 0 0 m 1 1 l S 0 0 m 1 1 l S")
    assert e.value.code == "TOO_LARGE"


def test_chord_cap_is_checked_per_cubic_before_flattening(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_mod, "MAX_CHORD_ROWS", 20)
    with pytest.raises(VectorPageRefused) as e:
        _scan(b"0 0 m 0 100 100 100 100 0 c S")  # n is well over 20
    assert e.value.code == "CHORD_CAP"
    with pytest.raises(VectorPageRefused) as e2:  # a coordinate so large that n would be astronomic: refused, not allocated
        _scan(b"0 0 m 0 900000000000 900000000000 900000000000 100 0 c S")
    assert e2.value.code == "CHORD_CAP"
    monkeypatch.setattr(scan_mod, "MAX_CHORD_ROWS", 8_000_000)
    assert len(_scan(b"0 0 m 0 100 100 100 100 0 c S").segments) > 20


def test_cancel_and_progress() -> None:
    body = b"0 0 m 1 1 l S\n" * 40000
    with pytest.raises(VectorScanCancelled):
        _scan(body, cancel=lambda: True)
    seen: list[tuple[int, int]] = []
    idx = _scan(body, cancel=lambda: False, progress=lambda done, total: seen.append((done, total)))
    assert len(idx.paths) == 40000 and seen and seen[-1] == (len(body), len(body))
    assert all(t == len(body) for _d, t in seen) and [d for d, _t in seen] == sorted(d for d, _t in seen)


# ----------------------------------------------------------------------------- numbers


def test_numbers_that_f_and_g_must_agree_on() -> None:
    idx = _scan(b"1.2345678901234567890 9007199254740993 m 0.1234567890123456789012345678901234567890 -.5 l 1 2 +3. -0 re S")
    seg = idx.segments[0]
    f32 = lambda v: float(np.float32(v))  # noqa: E731  (operands are float32, as in MuPDF: probe 2026-11-23)
    assert float(seg["x0"]) == f32("1.2345678901234567890") and float(seg["y0"]) == f32(9007199254740993)
    assert float(seg["x1"]) == f32("0.1234567890123456789012345678901234567890") and float(seg["y1"]) == -0.5
    with pytest.raises(VectorPageRefused):
        _scan(b"1.2.3 0 m 1 1 l S")


# ----------------------------------------------------------------------------- linear time


def _best(fn: Callable[[], object], repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        try:
            fn()
        except VectorPageRefused:
            pass
        best = min(best, time.perf_counter() - t0)
    return best


def _outcome(body: bytes) -> tuple[str, int]:
    """("ok", rows) or (refusal code, 0): what a timing case must produce BEFORE it is timed."""
    try:
        return "ok", len(_scan(body).paths)
    except VectorPageRefused as exc:
        return exc.code, 0


# name -> (builder, outcome at size n, outcome at size 2n); a fast wrong answer must fail before timing
def _doubling_cases() -> dict[str, tuple[Callable[[int], bytes], Callable[[int], tuple[str, int]]]]:
    err: Callable[[int], tuple[str, int]] = lambda n: ("SCAN_ERROR", 0)  # noqa: E731
    ok0: Callable[[int], tuple[str, int]] = lambda n: ("ok", 0)  # noqa: E731
    return {
        "open_parens": (lambda n: b"(" * n, err),
        "nested_strings_open": (lambda n: b"(a" * (n // 2), err),
        "open_dicts": (lambda n: b"<" * n, err),
        "unterminated_hex": (lambda n: b"<" + b"41" * (n // 2), err),
        "digit_run": (lambda n: b"9" * n, err),
        "digit_run_then_letter": (lambda n: b"1" * n + b"x", err),
        "long_comment": (lambda n: b"%" + b"x" * n, ok0),
        "long_name": (lambda n: b"/" + b"a" * n, ok0),
        "long_string": (lambda n: b"BT (" + b"x" * n + b") Tj ET", ok0),
        "nested_balanced_strings": (lambda n: (b"(" * 500 + b")" * 500 + b" ") * (n // 1000), ok0),
        "long_dictionary": (lambda n: b"/A << " + b"/K (v) /L <41> " * (n // 14) + b">> BDC EMC", ok0),
        "brackets": (lambda n: b"[" * n, err),
        "long_array": (lambda n: b"[" + b"1 " * (n // 2) + b"] TJ", ok0),
    }


@pytest.mark.parametrize("name", list(_doubling_cases()))
def test_linear_time_on_hostile_streams(name: str) -> None:
    make, expect = _doubling_cases()[name]
    n = 400_000
    small, large = make(n), make(2 * n)
    assert _outcome(small) == expect(n), (name, "small")  # the expected answer, not merely a fast one
    assert _outcome(large) == expect(2 * n), (name, "large")
    t1 = _best(lambda: _scan(small))
    t2 = _best(lambda: _scan(large))
    assert t2 < 3.2 * t1 + 0.15, (name, t1, t2)


def test_linear_time_on_deep_q_and_long_valid_streams() -> None:
    cases = {
        "deep_q": (lambda n: b"q " * (n // 2), lambda n: 0),
        "deep_q_pairs": (lambda n: b"q " * (n // 4) + b"0 0 m 1 1 l S " + b"Q " * (n // 4), lambda n: 1),
        "many_paths": (lambda n: b"0 0 m 9 9 l S\n" * (n // 14), lambda n: n // 14),
        "many_cm_blocks": (lambda n: b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q\n" * (n // 36), lambda n: n // 36),
    }
    n = 400_000
    for name, (make, rows) in cases.items():
        assert _outcome(make(n)) == ("ok", rows(n)), name
        assert _outcome(make(2 * n)) == ("ok", rows(2 * n)), name
        t1 = _best(lambda m=make: _scan(m(n)), 2)
        t2 = _best(lambda m=make: _scan(m(2 * n)), 2)
        assert t2 < 3.2 * t1 + 0.15, (name, t1, t2)


def test_scan_throughput_is_recorded(capsys: pytest.CaptureFixture[str]) -> None:
    body = b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q\n0 0 m 10 30 20 30 30 0 c S\n" * 8000
    t0 = time.perf_counter()
    idx = _scan(body)
    dt = time.perf_counter() - t0
    print(f"scan G: {len(body) / 1e6:.2f} MB in {dt:.3f} s = {len(body) / 1e6 / dt:.2f} MB/s, {len(idx.paths)} paths, {len(idx.segments)} segments")
    assert len(idx.paths) == 16000


# ----------------------------------------------------------------------------- B2 review fixes (Astra + Opus probes, 2026-11-23)


def _refused(*streams: bytes, **kw: object) -> VectorPageRefused:
    with pytest.raises(VectorPageRefused) as e:
        _scan(*streams, **kw)  # type: ignore[arg-type]
    return e.value


def _token_split_points(body: bytes) -> list[int]:
    """Every offset where a token has just ended and whitespace follows: a legal stream boundary."""
    return [i for i in range(1, len(body)) if body[i] in b" \n" and body[i - 1] not in b" \n"]


_SPLIT_BODIES = [
    b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q 3 3 m 4 4 l f",
    b"2 w 0 0 m 5 5 l 6 6 7 7 8 8 c h B* 10 10 20 20 re S",
    b"/OC /L BDC 0 0 5 5 re W n 1 1 m 2 2 l S EMC /A << /K (x) >> BDC 4 4 m 5 5 l f EMC",
]


@pytest.mark.parametrize("body", _SPLIT_BODIES)
def test_every_editable_range_lies_in_one_stream_at_every_token_split(body: bytes) -> None:
    """Astra B2 P1 / class check: an EDITABLE range never straddles a stream boundary, wherever the split falls."""
    for i in _token_split_points(body):
        idx = _scan(body[:i], body[i:])
        for row, fl in zip(idx.paths, _flags(idx), strict=True):
            if fl & F.EDITABLE:
                a, b = int(row["path_start"]), int(row["paint_end"])
                assert not a < i < b, (body, i, a, b)
            lo, hi = int(row["path_start"]), int(row["paint_end"])
            if lo < i < hi:
                assert fl & F.SPANS_STREAMS and not fl & F.EDITABLE, (body, i)


def test_operands_in_the_previous_stream_make_the_record_span_streams() -> None:
    idx = _scan(b"0 0", b"m 100 100 l S")  # probe1 A: the first operand is in stream 0, the paint in stream 1
    assert _flags(idx)[0] & F.SPANS_STREAMS and not _flags(idx)[0] & F.EDITABLE
    assert int(idx.paths["path_start"][0]) == 0
    one = _scan(b"0 0 m 100 100 l S")
    assert [tuple(float(v) for v in s) for s in idx.segments[["x0", "y0", "x1", "y1"]]] == [tuple(float(v) for v in s) for s in one.segments[["x0", "y0", "x1", "y1"]]]


def test_cm_operands_in_the_previous_stream_leave_the_block_not_inert() -> None:
    idx = _scan(b"q 1 0 0 1 5", b"5 cm 0 0 m 1 1 l S Q")
    assert not bool(idx.blocks["inert"][0])
    assert (int(idx.blocks["cm_operand_start"][0]), int(idx.blocks["cm_operand_end"][0])) == (-1, -1)


def test_stray_w_is_pending_until_the_next_record_and_clips_what_follows() -> None:
    idx = _scan(b"W 0 0 5 5 re n 1 1 m 2 2 l S")  # probe6: the W belongs to the next painted path
    fl = _flags(idx)
    assert fl[0] & F.SETS_CLIP and not fl[0] & F.EDITABLE and fl[1] & F.CLIPPED


def test_w_n_with_no_path_clips_what_follows_until_the_restoring_q() -> None:
    idx = _scan(b"q W n 1 1 m 2 2 l S Q 3 3 m 4 4 l S")  # probe4 / probe1 D
    fl = _flags(idx)
    assert fl[0] & F.CLIPPED and not fl[1] & F.CLIPPED


def test_a_stray_w_makes_the_block_not_inert() -> None:
    assert not bool(_scan(b"q W 0 0 5 5 re n Q").blocks["inert"][0])


@pytest.mark.parametrize(
    "body,operator",
    [
        (b"1 2 3 m 50 50 l S", "m"),
        (b"9 1 0 0 1 50 50 cm 0 0 m 10 10 l S", "cm"),
        (b"0 0 m 1 1 l 5 S", "S"),
        (b"0 m 1 1 l S", "m"),
        (b"/N 0 m 1 1 l S", "m"),  # a name where a number is needed
        (b"0 0 m 1 1 l 1 2 w S", "w"),
        (b"[0 0] m 1 1 l S", "m"),
        (b"0 0 m 1 1 l 1 2 W n", "W"),
        (b"1 2 Tr", "Tr"),
        (b"/OC BDC", "BDC"),
        (b"(x) BMC", "BMC"),
        (b"/A /B /C gs", "gs"),
        (b"1 0 0 rg 0 0 m 1 1 l 5 f", "f"),
        (b"0 0 m 1 1 1 1 1 1 1 v S", "v"),
        (b"0 Do", "Do"),
        (b"(x) (y) Tj", "Tj"),
        (b"9 Tr", "Tr"),
        (b"1 1 1 1 1 1 1 re", "re"),
    ],
)
def test_wrong_operand_counts_and_kinds_refuse_the_page_naming_the_operator(body: bytes, operator: str) -> None:
    err = _refused(body)
    assert err.code == "SCAN_ERROR" and operator in err.detail.split(), (body, err.detail)


def test_a_wrong_kind_m_followed_by_s_is_refused() -> None:
    assert _refused(b"[1 2] 3 m 4 4 l S").code == "SCAN_ERROR"
    assert _refused(b"(a) (b) m 4 4 l S").code == "SCAN_ERROR"


def test_unknown_operators_and_legal_composite_operands_are_accepted() -> None:
    idx = _scan(b"1 2 3 4 5 frobnicate [(a) -3 (b)] TJ [3 2] 0 d /A <</K [1 2 [3]] /L <41 4> >> BDC 0 0 m 1 1 l S EMC")
    assert len(idx.paths) == 1 and _flags(idx)[0] == F.EDITABLE  # a non-/OC tag leaves the path editable


def test_pending_operands_are_bounded() -> None:
    assert _scan(b"1 " * 4096 + b"frobnicate 0 0 m 1 1 l S").paths.shape == (1,)
    err = _refused(b"1 " * 4097 + b"frobnicate")
    assert err.code == "SCAN_ERROR" and "operand" in err.detail


def test_array_element_bound_counts_the_whole_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_mod, "MAX_ARRAY_ELEMENTS", 1000)
    assert len(_scan(b"[" + b"1 " * 1000 + b"] TJ 0 0 m 1 1 l S").paths) == 1
    err = _refused(b"[" + b"1 " * 1001 + b"] TJ")
    assert err.code == "SCAN_ERROR" and "element" in err.detail
    assert scan_mod.MAX_PAINTS == 4_000_000  # the monkeypatch left the other caps alone


@pytest.mark.parametrize(
    "body",
    [b"1 ] 2 m", b"} 0 0 m", b"{ 0 0 m 1 1 l S", b"0 0 m ) 1 1 l S", b"0 0 m > 1 1 l S", b"0 0 m >> 1 1 l S", b"<4g> Tj", b"<41 !> Tj", b"[1 2 > ]", b"[1 2 >>", b"<</A [1 >> ]", b"[ { ] }"],
)
def test_stray_delimiters_unbalanced_braces_and_bad_hex_refuse(body: bytes) -> None:
    assert _refused(body).code == "SCAN_ERROR"


def test_container_nesting_depth_is_bounded() -> None:
    assert _refused(b"[" * 100000 + b"]" * 100000).code == "SCAN_ERROR"
    assert len(_scan(b"[" * 20 + b"]" * 20 + b" pop 0 0 m 1 1 l S").paths) == 1


@pytest.mark.parametrize(
    "plain,escaped",
    [
        (b"/OC /L BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S", b"/O#43 /L BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S"),
        (b"/OC /L BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S", b"/#4fC /L BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S"),
        (b"/DeviceRGB cs 0 0 m 1 1 l f /DeviceCMYK CS 0 0 m 1 1 l S", b"/Device#52GB cs 0 0 m 1 1 l f /DeviceCM#59K CS 0 0 m 1 1 l S"),
        (b"/DeviceGray cs 0 0 m 1 1 l f", b"/Device#47ray cs 0 0 m 1 1 l f"),
    ],
)
def test_escaped_name_spellings_give_the_same_flags(plain: bytes, escaped: bytes) -> None:
    a, b = _scan(plain), _scan(escaped)
    assert _flags(a) == _flags(b) and a.paths["flags"].tolist() == b.paths["flags"].tolist()
    assert len(a.paths) == len(b.paths) >= 1


def test_an_escaped_oc_tag_makes_the_path_in_oc() -> None:
    assert _flags(_scan(b"/O#43 /L BDC 0 0 m 1 1 l S EMC"))[0] & F.IN_OC


def test_a_dictionary_may_span_a_stream_boundary_between_complete_tokens() -> None:
    whole = b"/OC <</A (x) /B <41> /C <</D [1 2]>> >> BDC 0 0 m 1 1 l S EMC 2 2 m 3 3 l S"
    ref = _scan(whole)
    assert _flags(ref)[0] & F.IN_OC and len(ref.paths) == 2
    for i in _token_split_points(whole):
        idx = _scan(whole[:i], whole[i:])
        assert [bool(f & F.IN_OC) for f in _flags(idx)] == [True, False], i
        assert idx.segments.tobytes() == ref.segments.tobytes(), i
        assert idx.paths["path_start"].tolist() == ref.paths["path_start"].tolist(), i  # the global offsets do not move


def test_an_array_may_span_a_stream_boundary_and_an_unterminated_one_refuses() -> None:
    idx = _scan(b"[(a) 5 ", b"(b)] TJ 0 0 m 1 1 l S")
    assert len(idx.paths) == 1
    assert _refused(b"/A <</K 1", b"/L 2").code == "SCAN_ERROR"


def test_a_path_inside_bt_et_is_not_editable() -> None:
    idx = _scan(b"BT 0 0 m 1 1 l S ET 2 2 m 3 3 l S")
    fl = _flags(idx)
    assert fl[0] & F.IMPURE and not fl[0] & F.EDITABLE and fl[1] & F.EDITABLE
    straddle = _flags(_scan(b"0 0 m 1 1 l BT S ET"))
    assert straddle[0] & F.IMPURE
    painted_inside = _flags(_scan(b"BT ET 0 0 m BT 1 1 l S ET"))
    assert painted_inside[0] & F.IMPURE


@pytest.mark.parametrize(
    "body,clipped",
    [
        (b"BT 7 Tr ET 0 0 m 1 1 l S", False),  # nothing shown
        (b"BT 7 Tr (x) Tj ET 0 0 m 1 1 l S", True),
        (b"BT 7 Tr (x) Tj 0 Tr ET 0 0 m 1 1 l S", True),  # probe4: reset before ET, clip was recorded when shown
        (b"BT 0 Tr (x) Tj 7 Tr ET 0 0 m 1 1 l S", False),  # shown under a fill mode
        (b"BT 4 Tr [(a) 5 (b)] TJ ET 0 0 m 1 1 l S", True),
        (b"BT 5 Tr (a) ' ET 0 0 m 1 1 l S", True),
        (b'BT 6 Tr 1 2 (a) " ET 0 0 m 1 1 l S', True),
        (b"BT 3 Tr (a) Tj ET 0 0 m 1 1 l S", False),
        (b"BT 7 Tr (x) Tj ET BT ET 0 0 m 1 1 l S", True),
        (b"q BT 7 Tr (x) Tj ET Q 0 0 m 1 1 l S", False),
    ],
)
def test_text_clipping_is_recorded_when_text_is_shown_under_a_clip_mode(body: bytes, clipped: bool) -> None:
    assert bool(_flags(_scan(body))[0] & F.CLIPPED) is clipped, body


def _inside(idx: VectorIndex, row: int, x: float, y: float, rule: str) -> bool:
    """Fill inside test computed ONLY from the index: each subpath closes implicitly; non-zero or even-odd."""
    p = idx.paths[row]
    sl = idx.segments[int(p["seg_start"]) : int(p["seg_start"]) + int(p["seg_count"])]
    winding = 0
    for k in sorted({int(v) for v in sl["subpath"]}):
        pts = [(float(s["x0"]), float(s["y0"]), float(s["x1"]), float(s["y1"])) for s in sl[sl["subpath"] == k]]
        pts.append((pts[-1][2], pts[-1][3], pts[0][0], pts[0][1]))  # the implicit closing edge
        for x0, y0, x1, y1 in pts:
            if (y0 <= y) != (y1 <= y):
                t = (y - y0) / (y1 - y0)
                if x0 + t * (x1 - x0) > x:
                    winding += 1 if y1 > y0 else -1
    return winding != 0 if rule == "nz" else winding % 2 != 0


def _render_gray(body: bytes, x: int, y: int) -> int:
    doc = fitz.open()
    pg = doc.new_page(width=200, height=200)
    xr = doc.get_new_xref()
    doc.update_object(xr, "<<>>")
    doc.update_stream(xr, body)
    doc.xref_set_key(pg.xref, "Contents", f"{xr} 0 R")
    pix = doc[0].get_pixmap(alpha=False, colorspace=fitz.csGRAY)
    return pix.samples[y * pix.width + x]


@pytest.mark.parametrize("paint,rule", [("f", "nz"), ("f*", "eo")])
def test_fill_topology_is_recoverable_from_the_subpath_column(paint: str, rule: str) -> None:
    """Astra B2 P1 / probe1 C1 vs C2: the same explicit segments, different subpaths, different interiors."""
    two = f"0 0 m 100 0 l 100 100 l 100 100 m 200 200 l 200 0 l {paint}".encode()
    one = f"0 0 m 100 0 l 100 100 l 200 200 l 200 0 l {paint}".encode()
    flip = (1.0, 0.0, 0.0, -1.0, 0.0, 200.0)  # the page frame of the 200 x 200 render: index points are in pixel space
    a, b = _scan(two, frame=flip), _scan(one, frame=flip)
    cols = ("x0", "y0", "x1", "y1")
    assert [tuple(float(v) for v in s) for s in a.segments[list(cols)]] == [tuple(float(v) for v in s) for s in b.segments[list(cols)]]
    assert a.segments["subpath"].tolist() == [0, 0, 1, 1] and b.segments["subpath"].tolist() == [0, 0, 0, 0]
    assert [tuple(float(v) for v in s) for s in a.segments[list(cols)]][0] == (0.0, 200.0, 100.0, 200.0)
    px, py = 120, 180  # pixel (120, 180) = user point (120.5, 19.5): inside the one polygon, outside the two triangles
    for body, idx in ((two, a), (one, b)):
        dark = _render_gray(body, px, py) < 128
        assert _inside(idx, 0, px + 0.5, py + 0.5, rule) is dark, body


def test_subpaths_count_m_and_re_and_closing_edges_stay_in_their_subpath() -> None:
    idx = _scan(b"0 0 m 10 0 l 10 10 l h 20 20 5 5 re 30 30 m 40 40 l S")
    assert idx.segments["subpath"].tolist() == [0, 0, 0, 1, 1, 1, 1, 2]  # the closing edge of "h" stays in subpath 0


def test_line_width_keeps_the_conservative_page_space_maximum_under_anisotropic_ctms() -> None:
    idx = _scan(b"10 w q 10 0 0 0.1 0 0 cm 0 0 m 1 1 l S Q")
    assert abs(float(idx.paths["line_width"][0]) - 100.0) < 1e-3  # w times the larger singular value (10, 0.1)
    rot = _scan(b"2 w q 0 3 -1 0 0 0 cm 0 0 m 1 1 l S Q")
    assert abs(float(rot.paths["line_width"][0]) - 6.0) < 1e-4
    # the nominal width stays derivable: line_width / sigma_max(ctm * frame); 4.1 documents it (no extra column)
    ctm = [float(v) for v in idx.paths["ctm"][0]]
    assert (ctm[0], ctm[3]) == (10.0, float(np.float32(0.1)))  # operands are float32


def test_non_finite_or_float32_overflowing_geometry_refuses_without_leaking_warnings() -> None:
    import warnings

    big = b"1" + b"0" * 39
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for body in (
            big + b" 0 m 1 1 l S",
            b"1 " + big + b" m 1 1 l S",
            b"0 0 m 1 1 l " + big + b" 0 0 " + big + b" 0 0 c S",
            b"1" + b"0" * 200 + b" 0 0 1 0 0 cm " + b"1" + b"0" * 200 + b" 0 0 1 0 0 cm 0 0 m 1 1 l S",
            b"1" + b"0" * 300 + b" 0 m 1 1 l S",
            b"0 0 " + big + b" " + big + b" re S",
            b"0 0 m 1" + b"0" * 307 + b" 1 l S",
        ):
            err = _refused(body)
            assert err.code in ("SCAN_ERROR", "CHORD_CAP"), (body[:60], err.code)
        with pytest.raises(VectorPageRefused) as e:
            _scan(b"0 0 m 0 100000000000000000000000000000000 100000000000000000000000000000000 100000000000000000000000000000000 1 0 c S")
        assert e.value.code == "CHORD_CAP"


def test_a_finite_cubic_whose_wang_value_overflows_the_budget_refuses_as_chord_cap() -> None:
    err = _refused(b"0 0 m 300000000000000000000000000000000000000 0 -300000000000000000000000000000000000000 0 1 0 c S")
    assert err.code == "CHORD_CAP"


def test_long_finite_numbers_follow_the_pdf_grammar() -> None:
    idx = _scan(b"0" * 400 + b"1 " + b"0" * 400 + b"2." + b"0" * 400 + b" m 3 3 l S")
    seg = idx.segments[0]
    assert (float(seg["x0"]), float(seg["y0"])) == (1.0, 2.0)
    assert _refused(b"1" + b"0" * 400 + b" 0 m").code == "SCAN_ERROR"
    assert _refused(b"1" * (1 << 21) + b" 0 m").code == "SCAN_ERROR"  # the token bound that keeps the cost linear


def test_the_possessive_number_regex_is_reached_and_stays_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = [0]
    real = scan_mod._NUM

    class Spy:
        def fullmatch(self, word: bytes) -> object:
            calls[0] += 1
            return real.fullmatch(word)

    monkeypatch.setattr(scan_mod, "_NUM", Spy())
    for n in (200_000, 400_000):
        assert _refused(b"1" * n + b"x 0 m").code == "SCAN_ERROR"
        assert _refused(b"1" * n + b"." + b"1" * n + b"..").code == "SCAN_ERROR"
    assert calls[0] == 4  # every long near-number reached _NUM (no length pre-filter shortcut)


def test_degenerate_rows_keep_their_transformed_point_as_a_finite_bbox() -> None:
    idx = _scan(b"5 5 m S 5 5 m h S h S", frame=(1.0, 0.0, 0.0, -1.0, 3.0, 200.0))
    assert len(idx.paths) == 3 and all(f & F.DEGENERATE for f in _flags(idx))
    bb = idx.paths["bbox"]
    assert np.isfinite(bb).all()
    assert bb[0][0] <= 8.0 <= bb[0][2] and bb[0][1] <= 195.0 <= bb[0][3] and bb[0][2] - bb[0][0] < 1e-3


def test_bytes_only_and_sizes_are_charged_before_any_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in (bytearray(b"0 0 m"), memoryview(b"0 0 m")):
        with pytest.raises(TypeError):
            scan_page([bad], IDENT6)  # type: ignore[list-item]
    monkeypatch.setattr(scan_mod, "MAX_DECODED_BYTES", 10)
    with pytest.raises(VectorPageRefused) as e:  # refused on the second stream, before the bytearray is even looked at
        scan_page([b"x" * 6, b"y" * 6, bytearray(b"z")], IDENT6)  # type: ignore[list-item]
    assert e.value.code == "TOO_LARGE"


def test_a_cm_during_construction_moves_the_whole_path_like_the_renderer_does() -> None:
    """The renderer keeps the path in user space and applies the PAINT-time CTM (13): pinned against MuPDF."""
    body = b"0 0 m 1 0 l 1 0 0 1 10 0 cm 1 1 l S"
    assert _oscan_body(body) == []
    idx = _scan(body)
    segs = [(float(s["x0"]), float(s["y0"]), float(s["x1"]), float(s["y1"])) for s in idx.segments]
    assert segs == [(10.0, 0.0, 11.0, 0.0), (11.0, 0.0, 11.0, 1.0)]
    assert _flags(idx)[0] & F.IMPURE and not _flags(idx)[0] & F.EDITABLE
    assert _oscan_body(b"0 0 m 1 0 l 2 0 0 2 0 0 cm 1 1 l S") == []


def test_progress_ends_with_a_terminal_event_on_an_inline_image_stop() -> None:
    for body in (b"0 0 m 1 1 l S BI /W 1 ID x EI", b"BI /W 1 ID x EI 0 0 m 1 1 l S"):
        seen: list[tuple[int, int]] = []
        idx = _scan(body, progress=lambda d, t: seen.append((d, t)))
        assert idx.stopped_at_inline_image and seen and seen[-1] == (len(body), len(body)), body


def test_callback_exceptions_propagate_unchanged() -> None:
    def boom() -> bool:
        raise RuntimeError("cancel boom")

    def pboom(done: int, total: int) -> None:
        raise ValueError("progress boom")

    with pytest.raises(RuntimeError, match="cancel boom"):
        _scan(b"0 0 m 1 1 l S", cancel=boom)
    with pytest.raises(ValueError, match="progress boom"):
        _scan(b"0 0 m 1 1 l S", progress=pboom)


def _cancel_calls(body: bytes) -> int:
    n = [0]

    def cancel() -> bool:
        n[0] += 1
        return False

    _scan(body, cancel=cancel)
    return n[0]


def _cancel_at(body: bytes, k: int) -> None:
    n = [0]

    def cancel() -> bool:
        n[0] += 1
        return n[0] >= k

    _scan(body, cancel=cancel)


def test_cancellation_is_polled_inside_long_containers_and_during_table_assembly() -> None:
    long_array = b"[" + b"1 " * 200_000 + b"] TJ 0 0 m 1 1 l S"
    assert _cancel_calls(long_array) >= 6  # the container loop polls, not only the top-level loop
    tiny = b"0 0 m 1 1 l S"
    calls = _cancel_calls(tiny)
    assert calls >= 3  # stream start plus assembly checkpoints
    with pytest.raises(VectorScanCancelled):
        _cancel_at(tiny, calls)  # cancelling at the LAST checkpoint (inside assembly) still cancels
    with pytest.raises(VectorScanCancelled):
        _cancel_at(long_array, 4)


def test_the_scanner_has_no_dead_tick_attribute() -> None:
    assert not hasattr(scan_mod._Scanner((b"",), IDENT6, None, None), "tick")


# ----------------------------------------------------------------------------- class check: refuse, or agree and cut cleanly


def _doc_bytes_from_streams(streams: list[bytes]) -> bytes:
    doc = fitz.open()
    pg = doc.new_page(width=200, height=200)
    xrefs = []
    for s in streams:
        x = doc.get_new_xref()
        doc.update_object(x, "<<>>")
        doc.update_stream(x, s)
        xrefs.append(x)
    doc.xref_set_key(pg.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")
    return doc.tobytes()


def _flat(obj: object) -> tuple[float, ...]:
    if isinstance(obj, (int, float)):
        return (round(float(obj), 2),)
    out: tuple[float, ...] = ()
    for part in obj:  # type: ignore[attr-defined]
        out += _flat(part)
    return out


def _fingerprint(d: dict) -> tuple[object, ...]:
    items = tuple((it[0],) + tuple(_flat(p) for p in it[1:]) for it in d["items"])
    return (d.get("type"), items, _flat(d.get("fill") or ()), _flat(d.get("color") or ()), round(float(d.get("width") or 0.0), 2))


def _page_state(data: bytes) -> tuple[np.ndarray, list[dict]]:
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[0]
    pix = pg.get_pixmap(alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy(), pg.get_drawings()


def _cut_row(data: bytes, idx: VectorIndex, row: int) -> bytes:
    """Cut the row's byte range out of its content stream the D7 way and write the stream back."""
    doc = fitz.open(stream=data, filetype="pdf")
    xrefs = doc[0].get_contents()
    a, b = int(idx.paths["path_start"][row]), int(idx.paths["paint_end"][row])
    for k, st in enumerate(idx.streams):
        g, n = int(st["global_start"]), int(st["length"])
        if g <= a and b <= g + n:
            raw = doc.xref_stream(xrefs[k]) or b""
            doc.update_stream(xrefs[k], raw[: a - g] + raw[b - g :])
            return doc.tobytes()
    raise AssertionError("an EDITABLE range lies in no single stream")


def _cut_row_with(data: bytes, idx: VectorIndex, row: int, fill: bytes) -> bytes:
    """Like ``_cut_row`` but the row's byte range is replaced by ``fill`` (``b"\\n"`` = a neutral separator that cannot join tokens or extend a comment)."""
    doc = fitz.open(stream=data, filetype="pdf")
    xrefs = doc[0].get_contents()
    a, b = int(idx.paths["path_start"][row]), int(idx.paths["paint_end"][row])
    for k, st in enumerate(idx.streams):
        g, n = int(st["global_start"]), int(st["length"])
        if g <= a and b <= g + n:
            raw = doc.xref_stream(xrefs[k]) or b""
            doc.update_stream(xrefs[k], raw[: a - g] + fill + raw[b - g :])
            return doc.tobytes()
    raise AssertionError("an EDITABLE range lies in no single stream")


def _full_state(data: bytes) -> tuple[bytes, list[tuple[object, ...]]]:
    """The whole-page raster at a fixed 2x zoom (no exclusion region) and the ORDERED drawings (multiplicities kept)."""
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[0]
    pix = pg.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    return bytes(pix.samples), [_fingerprint(d) for d in pg.get_drawings()]


def _outcome_check(data: bytes, label: object, *, reference: bytes | None = None, victim: int | None = None) -> int:
    """THE outcome check of the D7 cut (design 4.4): the page after cutting an EDITABLE row equals, pixel for pixel
    and drawing for drawing in order, a page that never contained it.  The reference is ``reference`` (a page built
    by hand from the survivors only) when the case names its ``victim`` row, else the same page with the row's bytes
    replaced by a newline.  Either the page refuses, or a row is not EDITABLE (nothing is cut), or the two agree."""
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[0]
    frame = page_user_space_matrix(pg)
    try:
        idx = scan_page([doc.xref_stream(x) or b"" for x in pg.get_contents()], frame)
    except VectorPageRefused:
        return 0
    cut = 0
    for row, fl in enumerate(_flags(idx)):
        if not fl & F.EDITABLE or (victim is not None and row != victim):
            continue
        ref_data = reference if reference is not None else _cut_row_with(data, idx, row, b"\n")
        got, want = _full_state(_cut_row(data, idx, row)), _full_state(ref_data)
        assert got[1] == want[1], (label, row, "ordered drawings differ from the survivor-only page")
        assert got[0] == want[0], (label, row, "the raster differs from the survivor-only page")
        cut += 1
    return cut


_RED = b"1 0 0 rg "
_OUTCOME_CASES: dict[str, tuple[list[bytes], list[bytes] | None]] = {
    # a comment at the end of stream 0 swallows the first line of stream 1; cutting that 'record' joins the survivor to it
    "comment_across_streams_far": ([b"%c", b"10 10 m\n20 20 40 40 re f " + _RED + b"150 150 30 30 re f"], [b"", _RED + b"150 150 30 30 re f"]),
    "comment_across_streams_near": ([b"%c", b"10 10 m\n20 20 40 40 re f " + _RED + b"30 30 30 30 re f"], [b"", _RED + b"30 30 30 30 re f"]),
}


@pytest.mark.parametrize("name", list(_OUTCOME_CASES))
def test_outcome_check_hand_built_survivor_only_pages(name: str) -> None:
    streams, ref = _OUTCOME_CASES[name]
    assert ref is not None
    # the victim is the first path of stream 1; the survivor-only page is the same page without it, built from the survivors alone
    _outcome_check(_doc_bytes_from_streams(streams), name, reference=_doc_bytes_from_streams(ref), victim=0)


_OUTCOME_BODIES = [
    b"0 0 m 40 0 l 40 40 l S W n 10 10 60 40 re f",  # stray W after a path
    b"BT 7 Tr (x) Tj ET 10 10 60 40 re f 90 90 m 150 120 l S",  # mixed text / clip
    b"1 0 0 1 -16777216 0 cm 16777217 10 20 20 re f 1 0 0 1 16777216 0 cm 100 20 40 40 re S",  # huge translation
    b"1 0 0 1 1e30 0 cm 10 10 60 40 re f",  # a translation beyond float32
    b"20 20 m h 100 100 m 120 100 l S 1 J 8 w 20 20 m h 100 100 m 120 100 l S",  # zero-length subpath in a mixed path
]


@pytest.mark.parametrize("body", _OUTCOME_BODIES)
def test_outcome_check_on_boundary_hostile_bodies(body: bytes) -> None:
    _outcome_check(_doc_bytes_from_streams([body, b" " + _RED + b"150 150 30 30 re f"]), body)


@pytest.mark.parametrize("seed", range(40))
def test_outcome_check_on_grammar_scenes(seed: int) -> None:
    _outcome_check(vfb.build(vg.random_scene(seed)), ("scene", seed))


@pytest.mark.parametrize("seed", range(72))
def test_outcome_check_on_perturbed_pages(seed: int) -> None:
    streams, kind = vg.perturbed_streams(seed)
    _outcome_check(_doc_bytes_from_streams(streams), (seed, kind))


def _check_scene(data: bytes, label: object) -> int:
    """Either the page refuses, or O-scan agrees and every EDITABLE row can be cut without touching a survivor."""
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[0]
    streams = [doc.xref_stream(x) or b"" for x in pg.get_contents()]
    frame = page_user_space_matrix(pg)
    try:
        idx = scan_page(streams, frame)
    except VectorPageRefused as exc:
        assert exc.code in ("SCAN_ERROR", "CHORD_CAP", "TOO_LARGE"), (label, exc)
        return 0
    assert vos.o_scan(data, _rows(idx), frame=IDENT6) == [], label  # (a)
    pix0, draw0 = _page_state(data)
    cut = 0
    for row, fl in enumerate(_flags(idx)):
        if not fl & F.EDITABLE:
            continue
        pix1, draw1 = _page_state(_cut_row(data, idx, row))
        bb = [float(v) for v in idx.paths["bbox"][row]]
        lw = float(idx.paths["line_width"][row])
        grow = max(4.0 if math.isnan(lw) else lw, 1.0) * 10.0 + 2.0  # the miter limit bounds a stroke's reach; NaN = a gs width
        region = fitz.Rect(bb[0] - grow, bb[1] - grow, bb[2] + grow, bb[3] + grow)
        mask = np.ones(pix0.shape[:2], dtype=bool)
        mask[max(int(region.y0), 0) : max(int(region.y1) + 1, 0), max(int(region.x0), 0) : max(int(region.x1) + 1, 0)] = False
        assert np.array_equal(pix0[mask], pix1[mask]), (label, row, "O-pixel of a survivor changed")  # (b)
        after = {_fingerprint(d) for d in draw1}
        for d in draw0:
            if not fitz.Rect(d["rect"]).intersects(region):
                assert _fingerprint(d) in after, (label, row, "O-struct of a survivor changed")
        cut += 1
    return cut


@pytest.mark.parametrize("seed", range(40))
def test_class_check_on_grammar_scenes_cutting_every_editable_row(seed: int) -> None:
    data = vfb.build(vg.random_scene(seed))
    assert _check_scene(data, ("scene", seed)) >= 0


@pytest.mark.parametrize("seed", range(72))
def test_class_check_on_perturbed_pages_refuse_or_agree_and_cut_cleanly(seed: int) -> None:
    streams, kind = vg.perturbed_streams(seed)
    _check_scene(_doc_bytes_from_streams(streams), (seed, kind))


def test_the_perturbation_grammar_reaches_both_outcomes() -> None:
    refused = agreed = cut = 0
    for seed in range(len(vg.PERTURBATIONS) * 4):
        streams, _kind = vg.perturbed_streams(seed)
        data = _doc_bytes_from_streams(streams)
        n = _check_scene(data, seed)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            scan_page([doc.xref_stream(x) or b"" for x in doc[0].get_contents()], page_user_space_matrix(doc[0]))
            agreed += 1
        except VectorPageRefused:
            refused += 1
        cut += n
    assert refused >= 8 and agreed >= 8 and cut >= 20, (refused, agreed, cut)


# ----------------------------------------------------------------------------- review round 2 (P1/P2/P3), each pinned to a MuPDF probe


def test_a_comment_that_runs_to_the_end_of_a_stream_swallows_the_first_line_of_the_next() -> None:
    idx = _scan(b"%c", b"10 10 m\n20 20 40 40 re f")  # probe: MuPDF reads '10 10 m' as comment text
    assert len(idx.paths) == 1 and int(idx.paths["path_start"][0]) == len(b"%c10 10 m\n")
    assert _flags(idx)[0] & F.EDITABLE
    assert len(_scan(b"%a", b"b", b"\n0 0 5 5 re f").paths) == 1  # the comment survives an interior stream
    assert len(_scan(b"%a", b"0 0 5 5 re f").paths) == 0  # and a stream without a line end is swallowed whole
    assert int(_scan(b"%c\n", b"0 0 5 5 re f").paths["path_start"][0]) == 3  # a line end closes it: no carry
    assert int(_scan(b"%c\r", b"0 0 5 5 re f").paths["path_start"][0]) == 3


def test_operands_are_float32_like_mupdf_and_reals_beyond_2_31_refuse() -> None:
    seg = _scan(b"16777217 0 m 1 1 l S").segments[0]  # probe: with a -16777216 translation MuPDF puts 16777217 at x = 0
    assert float(seg["x0"]) == 16777216.0
    idx = _scan(b"1 0 0 1 -16777216 0 cm 16777217 10 20 20 re f")
    assert float(idx.segments["x0"][0]) == 0.0
    _scan(b"4294967316 0 m 1 1 l S")  # an integer token is read like MuPDF: float32 rounding (probe: 4294967296)
    assert _refused(b"4294967316.0 0 m 1 1 l S").code == "SCAN_ERROR"  # probe: MuPDF drops the rectangle at x = 20


def test_published_bbox_and_width_are_finite_and_never_rounded_down() -> None:
    import warnings

    fmax = int(np.finfo(np.float32).max)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        idx = _scan(f"0 0 m {fmax} 0 l S".encode())
    assert np.isfinite(idx.paths["bbox"]).all() and float(idx.paths["bbox"][0][2]) >= float(fmax)
    idx = _scan(b"q 1 0.37 0 1 0 0 cm 3 w 0 0 m 10 10 l S Q")
    ctm = [float(v) for v in idx.paths["ctm"][0]]
    a, b, c, d = ctm[0], ctm[1], ctm[2], ctm[3]
    sigma = math.hypot((a + d) / 2, (b - c) / 2) + math.hypot((a - d) / 2, (b + c) / 2)
    assert float(idx.paths["line_width"][0]) >= 3.0 * sigma  # rounding to float32 never lowers it
    assert _refused(b"q 1e30 0 0 1e30 0 0 cm 10000000000 w 0 0 m 1 1 l S Q".replace(b"1e30", b"1" + b"0" * 30)).code == "SCAN_ERROR"  # saturating would lose the nominal width
    with pytest.raises(VectorPageRefused) as e:
        scan_page([b"0 0 m 1 1 l S"], (1.0, 0.0, 0.0, 1.0, 1e39, 0.0))
    assert e.value.code == "NO_FRAME"


def test_a_zero_length_closed_subpath_in_a_mixed_path_is_inside_the_bbox() -> None:
    body = b"1 J 8 w 20 20 m h 100 100 m 120 100 l S"
    idx = _scan(body)
    assert float(idx.paths["bbox"][0][0]) <= 20.0 and not _flags(idx)[0] & F.DEGENERATE  # probe: MuPDF paints a dot at (20, 20)
    assert _render_gray(body, 20, 180) < 128
    assert float(_scan(b"20 20 m 100 100 m 120 100 l S").paths["bbox"][0][0]) > 90.0  # no 'h': no dot


_CLIP_TAIL = b" 0 0 200 200 re f"
_CLIP_HEAD = b"BT /helv 12 Tf 10 100 Td 7 Tr "


def _clip_page_drawn(body: bytes) -> bool:
    doc = fitz.open()
    pg = doc.new_page(width=200, height=200)
    pg.insert_text((5, 5), " ", fontname="helv")  # puts /helv into the page resources
    doc.update_stream(pg.get_contents()[0], b"0 g " + body + _CLIP_TAIL)
    pix = fitz.open(stream=doc.tobytes(), filetype="pdf")[0].get_pixmap(alpha=False)
    return pix.pixel(190, 10)[0] < 128


@pytest.mark.parametrize(
    "body",
    [
        _CLIP_HEAD + b"() Tj ET",
        _CLIP_HEAD + b"<> Tj ET",
        _CLIP_HEAD + b"[] TJ ET",
        _CLIP_HEAD + b"[10] TJ ET",
        _CLIP_HEAD + b"[()] TJ ET",
        _CLIP_HEAD + b"(X) Tj ET",
        _CLIP_HEAD + b"[(X)] TJ ET",
        _CLIP_HEAD + b"<58> Tj ET",
        _CLIP_HEAD + b"(X) Tj BT ET",  # a nested BT does not clear the pending clip
        _CLIP_HEAD + b"(X) Tj BT ET ET",
        _CLIP_HEAD + b"(X) Tj q Q ET",  # a Q discards it
        _CLIP_HEAD + b"q (X) Tj Q ET",
        _CLIP_HEAD + b"q (X) Tj Q (Y) Tj ET",
        _CLIP_HEAD + b"(X) Tj 0 Tr ET",
        _CLIP_HEAD + b"q 0 Tr Q (X) Tj ET",  # Q restores Tr 7
        b"BT /helv 12 Tf 10 100 Td q 7 Tr (X) Tj Q ET",
        b"q " + _CLIP_HEAD + b"(X) Tj ET Q",
    ],
)
def test_text_clip_flag_agrees_with_the_renderer_on_a_following_rectangle(body: bytes) -> None:
    streams = [b"0 g " + body + _CLIP_TAIL]
    idx = scan_page(streams, IDENT6)
    last = len(idx.paths) - 1
    assert bool(_flags(idx)[last] & F.CLIPPED) is (not _clip_page_drawn(body)), body


@pytest.mark.parametrize(
    "body",
    [
        b"q [/N] 0 d 10 10 30 40 re S Q",
        b"[1 (a)] 0 d 0 0 5 5 re S",
        b"[1 [2]] 0 d 0 0 5 5 re S",
        b"[1 abc] 0 d 0 0 5 5 re S",
        b"/OC <</A>> BDC EMC",
        b"/OC <</A 1 /B>> BDC EMC",
        b"/OC <<1 2>> BDC EMC",
    ],
)
def test_malformed_typed_containers_refuse(body: bytes) -> None:
    assert _refused(body).code == "SCAN_ERROR", body


@pytest.mark.parametrize("body", [b"[3 2] 0 d 0 0 5 5 re S", b"[] 0 d 0 0 5 5 re S", b"/OC <</A 1 /B [1 2] /C <</D (x)>>>> BDC EMC 0 0 5 5 re f"])
def test_wellformed_typed_containers_are_accepted(body: bytes) -> None:
    _scan(body)


def test_resource_names_are_captured_per_block_decoded_and_in_order() -> None:
    idx = _scan(b"q /GS#31 gs /Cs1 cs 0.5 /P1 scn 0 0 5 5 re f Q q 0 0 5 5 re f Q")
    assert idx.block_resources == (((b"gs", b"/GS1"), (b"cs", b"/Cs1"), (b"scn", b"/P1")), ())
    assert len(idx.block_resources) == len(idx.blocks)
    assert _flags(idx)[0] & F.PAGE_ANCHORED and not _flags(idx)[1] & F.PAGE_ANCHORED  # the conservative flag is unchanged


def test_pending_primitives_are_charged_before_they_are_allocated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_mod, "MAX_SEGMENT_ROWS", 100)
    assert _refused(b"1 1 1 1 re " * 200 + b"S").code == "TOO_LARGE"
    _scan(b"1 1 1 1 re " * 20 + b"S")


def test_a_very_long_token_is_followed_by_a_cancel_check() -> None:
    small = _cancel_calls(b"(a) Tj 0 0 m 1 1 l S")
    big = _cancel_calls(b"(" + b"a" * (1 << 18) + b") Tj 0 0 m 1 1 l S")
    assert big > small
    rows = _cancel_calls(b"q 0 0 1 1 re f Q " * 9000)  # the block-table assembly loop polls too
    assert rows > _cancel_calls(b"q 0 0 1 1 re f Q " * 10)
