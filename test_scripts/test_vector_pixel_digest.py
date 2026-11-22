"""Card B1 completion: PIXELS_OUTSIDE is a real render digest (owner decision 2026-11-22).

The fact is the SHA-256 of the 2x, annotations-off, no-alpha render outside the changed region; the
oracle compares the masked samples themselves.  Not a symbolic path list.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402

_OP = vfb.Op("delete", 0, (1, 2))


def _ctx(facts: vfb.Facts) -> dict:
    return {k: v for k, v in facts.context.items() if k != "scenario_op"}


def _alpha_mutant(good: bytes) -> bytes:
    """The correct edit, plus an ExtGState alpha on the graphics state of an UNTOUCHED path."""
    doc = fitz.open(stream=good, filetype="pdf")
    xref = next(x for x in range(1, doc.xref_length()) if "/GS0" in doc.xref_object(x))
    text = re.sub(r"/GS0\s*<<[^>]*>>", "/GS0 << /LW 1 /CA 0.3 /ca 0.3 >>", doc.xref_object(xref))
    doc.update_object(xref, text)
    return doc.tobytes(garbage=0)


def test_pixels_outside_fact_is_a_sha256_render_digest() -> None:
    _data, facts = vfb.expected(vfb.sample_scene(), _OP)
    head, rest = facts[vfb.PIXELS_OUTSIDE]
    assert re.fullmatch(r"[0-9a-f]{64}", head)
    assert len(rest) == 1 and re.fullmatch(r"[0-9a-f]{64}", rest[0])  # the other page's own render


def test_the_fact_equals_the_digest_of_the_before_render_outside_the_region() -> None:
    """A correct delete changes nothing outside the region: expected-after digest == before digest."""
    scene = vfb.sample_scene()
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, _OP)
    sel = facts.context["selected_drawings"]
    assert facts[vfb.PIXELS_OUTSIDE] == vo.pixels_outside_digest(before, before, selected_drawings=sel)
    assert facts[vfb.PIXELS_OUTSIDE] == vo.pixels_outside_digest(before, good, selected_drawings=sel)


def test_rendering_is_deterministic_null_transaction() -> None:
    scene = vfb.sample_scene()
    before = vfb.build(scene)
    d1 = vo.pixels_outside_digest(before, before, rollback=True)
    d2 = vo.pixels_outside_digest(before, before, rollback=True)
    assert d1 == d2
    assert vfb.expected(scene, _OP)[1][vfb.PIXELS_OUTSIDE] == vfb.expected(scene, _OP)[1][vfb.PIXELS_OUTSIDE]
    # the rollback fact of the untouched document is the full-page digest of the document itself
    assert vfb.expected(scene, vfb.Op("delete", 0, (1, 2), "rollback"))[1][vfb.PIXELS_OUTSIDE] == d1


def test_an_alpha_change_on_an_untouched_path_is_invisible_to_the_symbolic_facts_and_caught_by_pixels() -> None:
    scene = vfb.sample_scene()
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, _OP)
    bad = _alpha_mutant(good)
    assert bad != good
    old = vo._records(fitz.open(stream=good, filetype="pdf")[0])
    new = vo._records(fitz.open(stream=bad, filetype="pdf")[0])
    assert old == new  # the surviving path records stay equal: the symbolic fact is blind here
    sel = facts.context["selected_drawings"]
    assert vo.pixels_outside_digest(before, bad, selected_drawings=sel) != facts[vfb.PIXELS_OUTSIDE]
    assert vo.o_pixel(_OP, before, bad, **_ctx(facts))
    assert not vo.o_pixel(_OP, before, good, **_ctx(facts))


def test_the_changed_region_is_masked_and_nothing_else() -> None:
    """Pixels inside the selected rectangles may differ; the digest must not see them."""
    scene = vfb.sample_scene()
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, _OP)
    sel = facts.context["selected_drawings"]
    # a path outside the region does change the digest
    neighbour = vfb.expected(scene, vfb.Op("delete", 0, (1, 2, 3)))[0]
    assert vo.pixels_outside_digest(before, neighbour, selected_drawings=sel) != facts[vfb.PIXELS_OUTSIDE]


def _cropbox_scene() -> vfb.Scene:
    base = vfb.sample_scene()
    return vfb.Scene((vfb.replace(base.pages[0], cropbox=(0.0, 0.0, 200.0, 120.0)), base.pages[1]), base.topology)


def test_a_render_size_change_is_a_digest_difference_not_an_index_error() -> None:
    """A non-square page: the /Rotate mutant changes the page-0 render size (B1 review finding 1)."""
    scene = _cropbox_scene()
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, _OP)
    sel = facts.context["selected_drawings"]
    rotated = next(d for n, d, _f in vfb.mutants(scene, _OP) if n == vfb.MUTANT_NAMES[6])
    digest = vo.pixels_outside_digest(before, rotated, selected_drawings=sel)  # must not raise
    assert digest != facts[vfb.PIXELS_OUTSIDE]
    assert vo.o_pixel(_OP, before, rotated, **_ctx(facts))  # a finding, not an exception
    assert not vo.o_pixel(_OP, before, good, **_ctx(facts))


_DIFF_SELECTIONS = ((), (0,), (1,), (1, 2), (3,), (3, 4), (5,), (6,), (9,), (0, 3, 9), (1, 2, 3, 4, 5, 6), (7,), (8,))


def _geometry_scenes() -> list[tuple[str, vfb.Scene]]:
    base = vfb.sample_scene()
    out = list(vfb.default_scenes())
    for rot in (90, 180, 270):
        page = vfb.replace(base.pages[0], rotate=rot, cropbox=(10.0, 20.0, 190.0, 150.0))
        out.append((f"rot{rot}+crop", vfb.Scene((page, base.pages[1]), base.topology)))
    out.append(("crop", _cropbox_scene()))
    return out


def test_builder_region_equals_the_oracle_region_on_every_scene_and_selection() -> None:
    """Rule A differential: the builder derives the region from its own records, the oracle from MuPDF."""
    checked = 0
    for name, scene in _geometry_scenes():
        before = vfb.build(scene)
        page = fitz.open(stream=before, filetype="pdf")[0]
        shape = vo._render(page).shape
        for sel in _DIFF_SELECTIONS:
            idx = vfb.drawing_indices(scene.pages[0], sel)
            mine = vfb.region_mask(shape, vfb.region_rects(scene.pages[0], idx))
            theirs = vo.region_mask(shape, vo.changed_region_rects(page, idx))
            assert (mine == theirs).all(), (name, sel, int((mine != theirs).sum()))
            checked += 1
    assert checked == len(_geometry_scenes()) * len(_DIFF_SELECTIONS)


def test_builder_digest_equals_the_oracle_digest_of_the_same_pair() -> None:
    scene = _cropbox_scene()
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, _OP)
    idx = facts.context["selected_drawings"]
    assert facts[vfb.PIXELS_OUTSIDE] == vo.pixels_outside_digest(before, good, selected_drawings=idx)


def test_render_pair_time_on_the_largest_twin_is_bounded() -> None:
    scene = max((s for _n, s in vfb.default_scenes()), key=lambda s: len(vfb.build(s)))
    before = vfb.build(scene)
    t0 = time.perf_counter()
    vo.pixels_outside_digest(before, before)
    assert time.perf_counter() - t0 < 2.0
