"""Astra A5 and A6: the untrusted-child-answer class for the SCAN answer.

Whatever the child writes in a scan row, the coordinator ends in exactly one terminal outcome (a valid
answer admitted, or one ``crashed`` failure after the single retry), the scan cache stays untouched
unless the answer is valid, and the next job runs.  An over-budget answer is refused by its record
count before any record is converted.
"""

from __future__ import annotations

import copy

import pytest

from model import content_scan
from test_scripts.test_native_image_probe import (  # noqa: F401
    StubRunner,
    _coordinator,
    _frame_failed,
    _scan_answer,
    model,
)

NAN = float("nan")
INF = float("inf")
HUGE = 10**400

# the ten fields of a Do row, in order (content_scan.to_json)
ROW_FIELDS = (
    "name", "do_index", "do_span", "cm_index", "cm_span", "cm_values", "q_index", "q_end", "q_span", "q_count",
)
BAD_SCALARS = [True, False, "5", "x", 1.5, INF, -INF, NAN, HUGE, -HUGE, -1, [], {}, [1]]
BAD_INDEX = BAD_SCALARS + [None]


def _answer_with(pdf_model, mutate) -> dict:
    answer = copy.deepcopy(_scan_answer(pdf_model))
    mutate(answer["scans"][0])
    return answer


def _set_row(field: int, value):
    def mutate(scan):
        scan["dos"][0][field] = value

    return mutate


def _set_top(key: str, value):
    def mutate(scan):
        scan[key] = value

    return mutate


def _set_nested(field: int, index: int, value):
    def mutate(scan):
        scan["dos"][0][field][index] = value

    return mutate


def _mutations() -> dict[str, object]:
    cases: dict[str, object] = {}
    for key in ("length", "operator_count"):
        for i, value in enumerate(BAD_INDEX):
            cases[f"{key}-{i}"] = _set_top(key, value)
    cases["dos-not-list"] = _set_top("dos", "oops")
    cases["dos-none"] = _set_top("dos", None)
    cases["dos-row-not-list"] = lambda scan: scan["dos"].__setitem__(0, 7)
    cases["dos-row-short"] = lambda scan: scan["dos"][0].pop()
    cases["dos-row-long"] = lambda scan: scan["dos"][0].append(0)
    cases["name-int"] = _set_row(0, 5)
    cases["name-none"] = _set_row(0, None)
    for field in (1, 9):  # never null: the Do's operator index, the q count
        for i, value in enumerate(BAD_INDEX):
            cases[f"{ROW_FIELDS[field]}-{i}"] = _set_row(field, value)
    for field in (3, 6, 7):  # nullable operator indexes
        for i, value in enumerate(BAD_SCALARS):
            cases[f"{ROW_FIELDS[field]}-{i}"] = _set_row(field, value)
    for field in (2, 4, 8):  # spans
        for i, value in enumerate(BAD_SCALARS):
            cases[f"{ROW_FIELDS[field]}-{i}"] = _set_row(field, value)
        for index in (0, 1):
            for i, value in enumerate(BAD_INDEX):
                cases[f"{ROW_FIELDS[field]}[{index}]-{i}"] = _set_nested(field, index, value)
        cases[f"{ROW_FIELDS[field]}-inverted"] = lambda scan, f=field: scan["dos"][0].__setitem__(
            f, [scan["dos"][0][f][1], scan["dos"][0][f][0]]
        )
        cases[f"{ROW_FIELDS[field]}-past-length"] = lambda scan, f=field: scan["dos"][0].__setitem__(
            f, [0, scan["length"] + 1]
        )
        cases[f"{ROW_FIELDS[field]}-len3"] = _set_row(field, [0, 1, 2])
    for i, value in enumerate(BAD_SCALARS):
        cases[f"cm_values-{i}"] = _set_row(5, value)
    for index in range(6):
        for i, value in enumerate([True, "1", INF, -INF, NAN, HUGE, None, [1], {}]):
            cases[f"cm_values[{index}]-{i}"] = _set_nested(5, index, value)
    cases["cm_values-len5"] = _set_row(5, [1.0] * 5)
    cases["cm_values-len7"] = _set_row(5, [1.0] * 7)
    return cases


MUTATIONS = _mutations()


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_a_malformed_scan_answer_fails_once_and_changes_no_cache(model, name):  # noqa: F811
    content_scan.clear_scan_cache()
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready: list[int] = []
    failures: list[tuple] = []
    coord.image_scan_ready.connect(ready.append)
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_image_scan(1)
    bad = _answer_with(model, MUTATIONS[name])
    runner.complete(runner.order[0], bad)
    assert len(runner.order) == 2, "the first malformed answer is retried once"
    runner.complete(runner.order[1], bad)
    assert ready == []
    assert failures == [("scan", 1, "crashed")]
    assert content_scan._cache == {}  # nothing of a malformed answer was admitted
    assert _frame_failed(model)
    # the next job runs
    coord.request_image_scan(2)
    runner.complete(runner.order[-1], _scan_answer(model, 2))
    assert ready == [2]


def test_the_unmodified_answer_is_admitted(model):  # noqa: F811
    runner = StubRunner()
    coord = _coordinator(model, runner)
    ready: list[int] = []
    coord.image_scan_ready.connect(ready.append)
    coord.request_image_scan(1)
    runner.complete(runner.order[0], _scan_answer(model))
    assert ready == [1] and len(runner.order) == 1


# ---- A6 -----------------------------------------------------------------------------------------


def test_an_over_budget_answer_is_refused_before_any_record_is_converted(model, monkeypatch):  # noqa: F811
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures: list[tuple] = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_image_scan(1)
    answer = copy.deepcopy(_scan_answer(model))
    row = answer["scans"][0]["dos"][0]
    answer["scans"][0]["dos"] = [row] * (content_scan.SCAN_CACHE_MAX_RECORDS + 1)
    conversions: list[int] = []
    original = content_scan.from_json

    def spy(obj):
        conversions.append(1)
        return original(obj)

    monkeypatch.setattr(content_scan, "from_json", spy)
    runner.complete(runner.order[0], answer)
    assert conversions == []
    assert failures == [("scan", 1, "resource_limited")]
    assert len(runner.order) == 1  # no retry for an answer that is simply too big
    assert content_scan._cache == {}
    assert _frame_failed(model)


def test_an_over_budget_answer_for_a_changed_frame_is_dropped_quietly(model, monkeypatch):  # noqa: F811
    runner = StubRunner()
    coord = _coordinator(model, runner)
    failures: list[tuple] = []
    coord.probe_failed.connect(lambda kind, page, reason: failures.append((kind, page, reason)))
    coord.request_image_scan(1)
    answer = copy.deepcopy(_scan_answer(model))
    row = answer["scans"][0]["dos"][0]
    answer["scans"][0]["dos"] = [row] * (content_scan.SCAN_CACHE_MAX_RECORDS + 1)
    model.mark_image_scan_failed(1, model.image_scan_set_key(1), "")  # the frame is no longer the one asked for
    monkeypatch.setattr(model, "image_scan_set_key", lambda *a, **k: (b"other",))
    conversions: list[int] = []
    monkeypatch.setattr(content_scan, "from_json", lambda obj: conversions.append(1))
    runner.complete(runner.order[0], answer)
    assert conversions == []
    assert content_scan._cache == {}
