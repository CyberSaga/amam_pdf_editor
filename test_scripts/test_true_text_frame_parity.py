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

Two further needs_fixtures pins live here because they share the historic-fourteen walk:

* ``test_trace_for_and_locate_trace_agree_on_the_historic_fourteen`` (S2, plan decision D-2): acc's
  ``_trace_for`` and rederive's ``_locate_trace`` locate the same texttrace run on every whole-show
  historic row, so unifying them stays a follow-up and not a drift risk.
* ``test_small_glyph_heights_moves_rawdict_boxes_not_texttrace_boxes`` (S2, risk R16): the
  process-global ``small_glyph_heights`` flag is pinned ON by conftest but unset in the rederive
  CLI; this measures which of the oracle's two box sources depends on it.
"""
from __future__ import annotations

import fitz
import pytest

from model.text_commit import verify
from model.text_commit.engine import TieredCommitEngine
from scripts import evidence_rederive as rd
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


def _historic_cases(spec, doc):
    return [
        case
        for case in acc._resolve_cases(spec, doc)
        if (spec.slug, case.page_index, case.show_seq) in _HISTORIC_KEYS
    ]


def test_trace_for_and_locate_trace_agree_on_the_historic_fourteen():
    """Every historic case is a whole show (``helpers._prepare`` asserts the decoded show equals
    ``case.original``), so both locators get the same needle; they must pick the same texttrace run
    and return the same origin and box, bit for bit."""
    compared: set[tuple[str, int, int]] = set()
    for slug in ("hvac", "ecc"):
        spec = acc._MANIFEST.spec_by_slug(slug)
        with fitz.open(acc._fixture(spec)) as doc:
            for case in _historic_cases(spec, doc):
                show = helpers._shows(doc, case.page_index)[case.show_seq]
                with helpers._measurement_copy(doc) as measured:
                    mpage = measured[case.page_index]
                    ours = helpers._trace_for(mpage, show, case.original)
                    located = rd._locate_trace(mpage, show, helpers.visual_frame(mpage), case.original)
                key = (slug, case.page_index, case.show_seq)
                assert located is not None, key
                distance, origin, bbox = located
                assert distance < 0.02, (key, distance)
                assert origin == tuple(ours["chars"][0][2]), key
                assert bbox == tuple(ours["bbox"]), key
                compared.add(key)
    assert compared == _HISTORIC_KEYS


def _hvac_page4_boxes(path, small_glyph_heights: bool) -> tuple[list, list]:
    """``(texttrace char boxes, rawdict non-space char boxes)`` of hvac page index 4 under the flag.
    Only numbers are kept (no document text)."""
    previous = bool(fitz.TOOLS.set_small_glyph_heights())  # no argument: read the current value
    fitz.TOOLS.set_small_glyph_heights(small_glyph_heights)
    try:
        with fitz.open(path) as doc, helpers._measurement_copy(doc) as measured:
            page = measured[4]
            trace = [tuple(char[3]) for item in page.get_texttrace() for char in item["chars"]]
            raw = [
                tuple(char[1:])
                for char in verify._iter_nonspace_chars(verify.visible_text(page, "rawdict"))
            ]
        return trace, raw
    finally:
        fitz.TOOLS.set_small_glyph_heights(previous)


def test_small_glyph_heights_moves_rawdict_boxes_not_texttrace_boxes():
    """R16: the shared helpers read texttrace boxes (flag-independent), while
    ``count_growth_zone_glyphs`` reads rawdict boxes (flag-dependent).  Measured on hvac page 4:
    3464 texttrace glyph boxes identical ON and OFF; 619 of 3161 rawdict boxes differ."""
    path = acc._fixture(acc._MANIFEST.spec_by_slug("hvac"))
    trace_on, raw_on = _hvac_page4_boxes(path, True)
    trace_off, raw_off = _hvac_page4_boxes(path, False)
    assert trace_on and raw_on
    assert trace_on == trace_off  # texttrace boxes do not depend on the flag
    assert len(raw_on) == len(raw_off)
    assert raw_on != raw_off  # rawdict boxes do: the flag rescales the font's ascender/descender to a 1 em box
    assert _hvac_page4_boxes(path, True) == (trace_on, raw_on)  # and the ON measurement is repeatable
