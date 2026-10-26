"""H3 parity lock for the historic fourteen (slice I0b, stage S1).

The acceptance harness used to convert the located texttrace origin and box with the PyMuPDF
page matrices (``page.rotation_matrix``); the moved ``_prepare`` converts through the computed
``PageVisualFrame`` (``frame.quarter_turn``) instead.  This guard proves the change is
bit-identical on every historic real-corpus case: the OLD values are recomputed here with the
literal PyMuPDF property, the NEW values are captured from what the moved ``_prepare`` hands
``TieredCommitEngine.prepare``, and they must be equal to the last float bit.  Ten of the
fourteen (hvac pages 4-6) sit on a ``/Rotate 270`` page, where the two spellings can diverge; on an unrotated page
both are the identity, so only a rotated case carries information (asserted below).

This file is the one place that may name the PyMuPDF page matrices: the AST guard in
``test_true_text_acceptance_helpers.py`` covers the helpers, the acceptance module and the three
consumer suites.
Guard (green before and after the move); a red here is a finding, never a reason to edit the code.
"""
from __future__ import annotations

import fitz
import pytest

from model.text_commit.engine import TieredCommitEngine
from test_scripts import test_text_commit_real_corpus_acceptance as acc
from test_scripts import true_text_acceptance_helpers as helpers
from test_scripts.true_text_corpus import HISTORIC_FOURTEEN

pytestmark = pytest.mark.needs_fixtures

_HISTORIC_KEYS = {row[:3] for row in HISTORIC_FOURTEEN}


def _compare_spec(spec, monkeypatch) -> tuple[list[tuple], list[tuple]]:
    """``(rows, rotated)``: per compared case the (slug, page, show, rotation, deltas) row."""
    path = acc._fixture(spec)
    rows: list[tuple] = []
    seen: list[dict] = []
    real_prepare = TieredCommitEngine.prepare

    def spy(self, page, **kwargs):
        seen.append(kwargs)
        return real_prepare(self, page, **kwargs)

    with monkeypatch.context() as patch, fitz.open(path) as doc:
        patch.setattr(TieredCommitEngine, "prepare", spy)
        cases = [
            case
            for case in acc._resolve_cases(spec, doc)
            if (spec.slug, case.page_index, case.show_seq) in _HISTORIC_KEYS
        ]
        engine = TieredCommitEngine(doc, max_tier=1)
        for case in cases:
            page = doc[case.page_index]
            show = helpers._shows(doc, case.page_index)[case.show_seq]
            with helpers._measurement_copy(doc) as measured:
                trace = helpers._trace_for(measured[case.page_index], show, case.original)
            # OLD: the literal PyMuPDF property, exactly as the pre-move harness spelled it
            frame = helpers.visual_frame(page)
            # both halves of the frame equal the literal PyMuPDF properties, bit for bit
            assert tuple(frame.base) == tuple(page.transformation_matrix), (spec.slug, case.page_index)
            assert tuple(frame.quarter_turn) == tuple(page.rotation_matrix), (spec.slug, case.page_index)
            old_origin = tuple(fitz.Point(trace["chars"][0][2]) * page.rotation_matrix)
            old_bbox = tuple(fitz.Rect(trace["bbox"]) * page.rotation_matrix)
            seen.clear()
            helpers._prepare(engine, doc, case)
            assert len(seen) == 1, "the spy on TieredCommitEngine.prepare did not fire exactly once"
            new_origin = tuple(seen[0]["expected_origin"])
            new_bbox = tuple(seen[0]["target_bbox"])
            rows.append(
                (
                    spec.slug,
                    case.page_index,
                    case.show_seq,
                    page.rotation,
                    old_origin,
                    new_origin,
                    old_bbox,
                    new_bbox,
                )
            )
    return rows, [row for row in rows if row[3] != 0]


@pytest.mark.parametrize("slug", ["hvac", "ecc"])
def test_prepare_inputs_are_bit_identical_to_the_old_page_matrix_values(slug, monkeypatch):
    spec = acc._MANIFEST.spec_by_slug(slug)
    rows, rotated = _compare_spec(spec, monkeypatch)
    assert rows, "no historic case was compared"
    for slug_, page, show, rotation, old_origin, new_origin, old_bbox, new_bbox in rows:
        assert new_origin == old_origin, (slug_, page, show, rotation, old_origin, new_origin)
        assert new_bbox == old_bbox, (slug_, page, show, rotation, old_bbox, new_bbox)
    if slug == "hvac":
        # ten of the fourteen are on hvac pages 4-6, /Rotate 270: the only rows that carry information
        assert len(rotated) == 10, len(rotated)


def test_every_historic_case_was_compared(monkeypatch):
    compared: set[tuple[str, int, int]] = set()
    for slug in ("hvac", "ecc"):
        rows, _ = _compare_spec(acc._MANIFEST.spec_by_slug(slug), monkeypatch)
        compared.update((row[0], row[1], row[2]) for row in rows)
    assert compared == _HISTORIC_KEYS
