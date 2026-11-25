"""Card B6, part 1 (design plan Step 5): model/vector_paths/edit.py::plan_delete.  Pure bytes in, plan out.  Red first.

D7 cuts [path_start, paint_end) and never re-serialises; the whitespace byte before a cut stays and the one after goes
only when both neighbours are whitespace.  D17 removes a whole leaf q..Q block only when it is inert and every one of
its records is editable and selected.  Adjacent ranges are merged.  The derived index equals a rescan of the new bytes.
"""

from __future__ import annotations

import hashlib
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths import edit as ve  # noqa: E402
from model.vector_paths.scan import VectorScanCancelled, scan_page  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
S = b"q 1 0 0 1 5 5 cm 0 0 m 9 9 l S Q\n0 0 m 5 5 l S\nq 0 0 m 1 1 l S 2 2 m 3 3 l S Q"


def _plan(streams: list[bytes], rows: list[int]):
    idx = scan_page(streams, IDENT6)
    mask = np.zeros(len(idx.paths), dtype=bool)
    mask[rows] = True
    return idx, ve.plan_delete(idx, mask, streams)


def _joined(plan) -> bytes:
    return b"".join(s for s in plan.new_streams if s is not None)


def test_a_lone_inert_block_is_removed_whole_and_the_start_of_stream_keeps_its_neighbour():
    _, plan = _plan([S], [0])
    assert plan.new_streams[0] == S[32:]  # leading boundary: nothing before, so the byte after stays
    assert plan.ranges[0].tolist() == [[0, 32]]


def test_a_span_outside_any_block_drops_one_whitespace_byte_when_both_neighbours_are_whitespace():
    _, plan = _plan([S], [1])
    assert plan.new_streams[0] == S[:33] + S[47:]
    assert plan.ranges[0].tolist() == [[33, 47]]


def test_one_of_two_paints_in_a_block_cuts_the_span_and_keeps_the_block():
    _, plan = _plan([S], [2])
    assert plan.new_streams[0] == S[:49] + S[63:]
    assert b"q 2 2 m 3 3 l S Q" in plan.new_streams[0]


def test_every_paint_of_a_block_selected_removes_the_block():
    _, plan = _plan([S], [2, 3])
    assert plan.ranges[0].tolist() == [[47, 78]]
    assert plan.new_streams[0] == S[:47]


def test_adjacent_ranges_merge():
    body = b"0 0 m 1 1 l S 2 2 m 3 3 l S 4 4 m 5 5 l S"
    _, plan = _plan([body], [1, 2])
    assert plan.ranges[0].tolist() == [[14, 41]]  # one range: the two records and the whitespace between them
    assert plan.new_streams[0] == body[:14]


def test_select_all_leaves_a_valid_blank_page():
    idx, plan = _plan([S], [0, 1, 2, 3])
    rescan = scan_page([plan.new_streams[0]], IDENT6)
    assert len(rescan.paths) == 0 and plan.new_streams[0].strip() == b""
    assert len(plan.derived.paths) == 0


def test_cumulative_cm_keeps_the_cm():
    body = b"1 0 0 1 5 5 cm 0 0 m 1 1 l S 1 0 0 1 2 2 cm 3 3 m 4 4 l S"
    _, plan = _plan([body], [0])
    assert b"1 0 0 1 5 5 cm" in plan.new_streams[0] and b"1 0 0 1 2 2 cm" in plan.new_streams[0]
    assert b"0 0 m 1 1 l S" not in plan.new_streams[0]


def test_non_editable_selected_rows_are_ignored_and_an_empty_selection_is_refused():
    body = b"/OC /x BDC 0 0 m 1 1 l S EMC 5 5 m 6 6 l S"
    idx = scan_page([body], IDENT6)
    only_oc = np.array([True, False])
    with pytest.raises(ValueError):
        ve.plan_delete(idx, only_oc, [body])
    with pytest.raises(ValueError):
        ve.plan_delete(idx, np.zeros(2, dtype=bool), [body])
    plan = ve.plan_delete(idx, np.array([True, True]), [body])
    assert b"/OC /x BDC 0 0 m 1 1 l S EMC" in plan.new_streams[0] and b"5 5 m 6 6 l S" not in plan.new_streams[0]


def test_untouched_streams_are_none_and_ranges_are_per_stream_and_local():
    a, b = b"0 0 m 1 1 l S", b"2 2 m 3 3 l S 4 4 m 5 5 l S"
    _, plan = _plan([a, b], [1])
    assert plan.new_streams[0] is None and plan.new_compressed[0] is None
    assert plan.ranges[0].shape == (0, 2)
    assert plan.ranges[1].tolist() == [[0, 13]]  # a cut at the stream start has no byte before it: the one after stays
    assert plan.new_streams[1] == b[13:]


def test_digests_compressed_bytes_and_kind():
    idx, plan = _plan([S], [1])
    assert plan.kind == "delete" and plan.frame == idx.frame
    assert plan.source_digests == (hashlib.sha256(S).digest(),)
    assert plan.planned_digests == (hashlib.sha256(plan.new_streams[0]).digest(),)
    assert zlib.decompress(plan.new_compressed[0]) == plan.new_streams[0]
    assert plan.new_compressed[0] == zlib.compress(plan.new_streams[0], 6)


@pytest.mark.parametrize("rows", [[0], [1], [2], [2, 3], [0, 2], [1, 3], [0, 1, 2, 3]])
def test_derived_index_equals_a_rescan_of_the_new_bytes(rows):
    _, plan = _plan([S], rows)
    fresh = scan_page([plan.new_streams[0]], IDENT6)
    for name in ("paths", "cubics", "segments", "blocks", "streams"):
        assert getattr(plan.derived, name).tobytes() == getattr(fresh, name).tobytes(), name
    assert plan.derived.indexed_end == fresh.indexed_end


def test_cancel_before_any_work_raises_and_returns_nothing():
    idx = scan_page([S], IDENT6)
    with pytest.raises(VectorScanCancelled):
        ve.plan_delete(idx, np.ones(len(idx.paths), dtype=bool), [S], cancel=lambda: True)


def test_a_stale_stream_is_refused():
    idx = scan_page([S], IDENT6)
    with pytest.raises(ValueError):
        ve.plan_delete(idx, np.ones(len(idx.paths), dtype=bool), [S + b" "])
