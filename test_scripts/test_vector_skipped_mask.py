"""Card B7 step 6 (plans/b7-design-astra.md section 4): the exact `skipped` mask.  Red first.

Owner 11-26: a class the user cannot see is not "skipped".  Counted: a non-editable row with a visible paint that
is non-editable because of IMPURE, SPANS_STREAMS, IN_OC or SETS_CLIP.  Not counted: paint `n`, a singular CTM.
The mask is built before the topmost row / the marquee is chosen, so an uncounted row never hides a counted one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.vector_paths import index as qi  # noqa: E402
from model.vector_paths.scan import PathFlag, scan_page  # noqa: E402

IDENT6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
LINE = "0 w 0 0 m 30 0 l S "


def _scan(*streams: str):
    return scan_page([s.encode("ascii") for s in streams], IDENT6)


def _run(idx, mode, rect=(-1.0, -1.0, 40.0, 10.0), tol=0.0):
    mask, skipped = qi.select_counting_skipped(idx, rect, tol, mode)
    return [int(i) for i in np.flatnonzero(mask)], skipped


def _flags(idx) -> list[int]:
    return [int(f) for f in idx.paths["flags"]]


REASONS = {
    "in_oc": ("/OC /x BDC " + LINE + "EMC", PathFlag.IN_OC),
    "impure": ("0 0 m 1 w 30 0 l S", PathFlag.IMPURE),
    "sets_clip": ("0 w 0 0 m 30 0 l W S", PathFlag.SETS_CLIP),
}


@pytest.mark.parametrize("mode", ["touch", "contain"])
@pytest.mark.parametrize("reason", sorted(REASONS))
def test_each_counted_reason_is_one_skipped_row(reason, mode):
    stream, flag = REASONS[reason]
    idx = _scan(stream)
    assert _flags(idx)[-1] & int(flag) and not _flags(idx)[-1] & int(PathFlag.EDITABLE)
    assert _run(idx, mode) == ([], 1)


def test_a_row_that_spans_streams_is_counted():
    idx = _scan("0 w 0 0 m ", "30 0 l S")
    assert _flags(idx)[0] & int(PathFlag.SPANS_STREAMS)
    assert _run(idx, "touch") == ([], 1)


def test_several_reasons_on_one_row_count_once():
    idx = _scan("/OC /x BDC 0 0 m 1 w 30 0 l W S EMC")
    assert _flags(idx)[0] & int(PathFlag.IN_OC) and _flags(idx)[0] & int(PathFlag.IMPURE)
    assert _run(idx, "touch") == ([], 1)


@pytest.mark.parametrize("mode", ["touch", "contain"])
def test_a_clip_setter_with_paint_n_is_not_counted(mode):
    idx = _scan("0 0 30 10 re W n")
    assert _run(idx, mode) == ([], 0)


def test_an_ordinary_paint_n_row_is_not_counted():
    assert _run(_scan("0 0 m 30 0 l n"), "touch") == ([], 0)


@pytest.mark.parametrize("mode", ["touch", "contain"])
def test_a_singular_ctm_row_is_not_counted_even_with_another_reason(mode):
    plain = _scan("q 0 0 0 0 0 0 cm " + LINE + "Q")
    assert _flags(plain)[0] & int(PathFlag.CTM_SINGULAR)
    assert _run(plain, mode, (-1, -1, 1, 1)) == ([], 0)
    both = _scan("/OC /x BDC q 0 0 0 0 0 0 cm " + LINE + "Q EMC")
    assert _flags(both)[0] & int(PathFlag.CTM_SINGULAR) and _flags(both)[0] & int(PathFlag.IN_OC)
    assert _run(both, mode, (-1, -1, 1, 1)) == ([], 0)


@pytest.mark.parametrize("mode", ["touch", "contain", "click"])
def test_clipped_and_page_anchored_editable_rows_are_selected_not_skipped(mode):
    idx = _scan("0 0 100 100 re W n 0 w 0 5 m 30 5 l S")
    assert _flags(idx)[1] & int(PathFlag.CLIPPED) and _flags(idx)[1] & int(PathFlag.EDITABLE)
    rect = (-1.0, 4.0, 40.0, 6.0) if mode != "click" else (10.0, 5.0, 10.0, 5.0)
    assert _run(idx, mode, rect, 1.0) == ([1], 0)


def test_click_on_a_counted_row_alone_selects_nothing_and_says_one():
    idx = _scan("/OC /x BDC " + LINE + "EMC")
    assert _run(idx, "click", (10.0, 0.0, 10.0, 0.0), 1.0) == ([], 1)


def test_click_falls_through_a_counted_row_to_the_editable_row_below():
    idx = _scan(LINE, "/OC /x BDC " + LINE + "EMC")
    assert _run(idx, "click", (10.0, 0.0, 10.0, 0.0), 1.0) == ([0], 0)


def test_click_through_an_n_row_sees_the_counted_row_below_it():
    idx = _scan("/OC /x BDC " + LINE + "EMC 0 0 m 30 0 l n")
    assert _run(idx, "click", (10.0, 0.0, 10.0, 0.0), 1.0) == ([], 1)


def test_click_on_nothing_is_zero_zero():
    assert _run(_scan(LINE), "click", (10.0, 50.0, 10.0, 50.0), 1.0) == ([], 0)


def test_the_selection_mask_equals_select_for_every_mode():
    idx = _scan(LINE, "/OC /x BDC " + LINE + "EMC 0 0 m 30 0 l n")
    for mode, rect in (("touch", (-1, -1, 40, 10)), ("contain", (-1, -1, 40, 10)), ("click", (10, 0, 10, 0))):
        mask, _skipped = qi.select_counting_skipped(idx, rect, 1.0, mode)
        assert np.array_equal(mask, qi.select(idx, rect, 1.0, mode)), mode


def test_summary_uses_the_same_countable_rule():
    idx = _scan("/OC /x BDC " + LINE + "EMC 0 0 m 30 0 l n " + LINE)
    everything = np.ones(len(idx.paths), dtype=bool)
    selected, skipped, _bbox = qi.summary(idx, everything)
    assert (selected, skipped) == (1, 1)  # the n row is not skipped
