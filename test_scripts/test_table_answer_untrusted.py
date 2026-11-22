"""H23 finding 1: the untrusted-child-answer class for the TABLE answer.

Whatever the child writes in ``rects``, the coordinator must end in exactly one terminal outcome
(a valid answer stored and announced, or one ``crashed`` failure after the single retry), leave the
caches untouched unless the answer is valid, and let the next job run.
"""
from __future__ import annotations

import pytest

from model import table_objects
from test_scripts.test_object_probe import TABLE_RECT, StubRunner, _complete, _coordinator, model  # noqa: F401

NAN = float("nan")
INF = float("inf")

BAD_RECTS = {
    "not_a_list": "oops",
    "none": None,
    "number": 5,
    "dict": {"a": 1},
    "rect_is_number": [5],
    "rect_is_string": ["abcd"],
    "rect_len_0": [[]],
    "rect_len_3": [[1.0, 2.0, 3.0]],
    "rect_len_5": [[1.0, 2.0, 3.0, 4.0, 5.0]],
    "nan": [[NAN, 0.0, 10.0, 10.0]],
    "inf": [[0.0, 0.0, INF, 10.0]],
    "neg_inf": [[-INF, 0.0, 10.0, 10.0]],
    "huge_int": [[0, 0, 10**400, 10]],
    "huge_neg_int": [[-(10**400), 0, 10, 10]],
    "bool": [[True, False, True, True]],
    "none_elem": [[None, 0.0, 10.0, 10.0]],
    "str_elem": [["1", 0.0, 10.0, 10.0]],
    "nested_elem": [[[1], 0.0, 10.0, 10.0]],
    "inverted_x": [[50.0, 0.0, 10.0, 10.0]],
    "negative_size": [[-1.0, -1.0, -2.0, -2.0]],
    "good_then_bad": [TABLE_RECT, [1.0, 2.0, 3.0]],
}


def _run(pdf_model, rects):
    runner = StubRunner()
    coord = _coordinator(pdf_model, runner)
    ready: list[int] = []
    failures: list[tuple] = []
    coord.tables_ready.connect(ready.append)
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_tables(1)
    runner.complete(runner.order[0], _complete(rects))
    if len(runner.order) == 2:  # the one retry
        runner.complete(runner.order[1], _complete(rects))
    return runner, coord, ready, failures


@pytest.mark.parametrize("name", list(BAD_RECTS))
def test_an_invalid_table_answer_fails_once_and_changes_no_cache(model, name):  # noqa: F811
    runner, coord, ready, failures = _run(model, BAD_RECTS[name])
    assert ready == []
    assert failures == [("tables", 1, "crashed")]
    assert table_objects.cached_table_rects(model, 1) is None
    # the next job runs: the failed mark of this page is the only state, another page is untouched
    coord.request_tables(2)
    runner.complete(runner.order[-1], _complete([TABLE_RECT]))
    assert ready == [2]
    assert table_objects.cached_table_rects(model, 2) is not None


@pytest.mark.parametrize("rects", [[TABLE_RECT], [(1, 2, 3, 4)], [], [[-5.0, -5.0, 10.0, 10.0]]])
def test_valid_answers_are_still_accepted(model, rects):  # noqa: F811
    _runner, _coord, ready, failures = _run(model, rects)
    assert ready == [1] and failures == []
    assert table_objects.cached_table_rects(model, 1) is not None
