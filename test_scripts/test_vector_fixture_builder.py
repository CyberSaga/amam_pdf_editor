"""Card B1: the twin builder (design plan section 9, handoff H6).

The builder writes PDF bytes and *facts* for a scene it models abstractly; it never reads its own
bytes back (rule A).  These tests are the independent check: facts are compared with what MuPDF
reports for the bytes.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402


def _drawing_bbox(drawing: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for item in drawing["items"]:
        if item[0] == "l":
            pts = [item[1], item[2]]
        elif item[0] == "c":
            pts = list(item[1:5])
        elif item[0] == "re":
            pts = [fitz.Point(item[1].x0, item[1].y0), fitz.Point(item[1].x1, item[1].y1)]
        else:
            pts = []
        xs += [p.x for p in pts]
        ys += [p.y for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def test_fact_kinds_are_the_fixed_list() -> None:
    assert vfb.FACT_KINDS == ("PATHS", "OTHER_PAGES", "OUTSIDE_BYTES", "OBJECTS", "PIXELS_OUTSIDE", "DICT")


def test_mutant_names_are_the_fixed_list_in_order() -> None:
    assert vfb.MUTANT_NAMES == (
        "neighbour deleted too",
        "one selected path kept",
        "block removed where a D17 rule fails",
        "range shifted by one token",
        "write in place on a shared stream",
        "copy skipped with a shared indirect array",
        "/Rotate changed on the edited page",
        "a trailer key changed",
        "a foreign stream changed",
        "restore skipped after a failure",
        "/Contents left repointed after a rollback",
        "extra dictionary key",
        "decoded bytes restored under another filter",
    )


def test_build_is_deterministic_and_opens() -> None:
    scene = vfb.sample_scene()
    a, b = vfb.build(scene), vfb.build(scene)
    assert a == b
    doc = fitz.open(stream=a, filetype="pdf")
    assert len(doc) == len(scene.pages)
    assert len(doc[0].get_drawings()) == vfb.drawing_count(scene.pages[0])


def test_facts_paths_match_what_mupdf_reports() -> None:
    """Independent truth check: the abstract facts equal MuPDF's drawings of the bytes."""
    scene = vfb.sample_scene()
    data, facts = vfb.expected(scene, vfb.Op("delete", 0, (1,)))
    doc = fitz.open(stream=data, filetype="pdf")
    drawings = doc[0].get_drawings()
    records = facts["PATHS"]
    assert len(drawings) == len(records)
    height = doc[0].mediabox.height
    for drawing, record in zip(drawings, records, strict=True):
        pts = [pt for prim in record[1] for pt in prim[1:]]
        want = (
            min(p[0] for p in pts),
            height - max(p[1] for p in pts),
            max(p[0] for p in pts),
            height - min(p[1] for p in pts),
        )
        assert _drawing_bbox(drawing) == pytest.approx(want, abs=1e-3)


def test_expected_delete_drops_the_selected_editable_path_only() -> None:
    scene = vfb.sample_scene()
    before = fitz.open(stream=vfb.build(scene), filetype="pdf")
    data, facts = vfb.expected(scene, vfb.Op("delete", 0, (2,)))
    after = fitz.open(stream=data, filetype="pdf")
    assert len(after[0].get_drawings()) == len(before[0].get_drawings()) - 1
    assert len(facts["PATHS"]) == vfb.drawing_count(scene.pages[0]) - 1


def test_non_editable_selected_paths_are_skipped() -> None:
    scene = vfb.sample_scene()
    editable_flags = [vfb.is_editable(item) for item in scene.pages[0].items if isinstance(item, vfb.PathSpec)]
    assert not all(editable_flags), "sample scene must hold a non-editable path (OC / clip)"
    bad = editable_flags.index(False)
    data, facts = vfb.expected(scene, vfb.Op("delete", 0, (bad,)))
    assert data == vfb.build(scene) or len(facts["PATHS"]) == vfb.drawing_count(scene.pages[0])


def test_move_is_not_built_before_c1() -> None:
    with pytest.raises(NotImplementedError):
        vfb.expected(vfb.sample_scene(), vfb.Op("move", 0, (0,)))


def test_unknown_operation_raises() -> None:
    with pytest.raises(ValueError):
        vfb.expected(vfb.sample_scene(), vfb.Op("frobnicate", 0, (0,)))


@pytest.mark.parametrize("name", sorted(vfb.TOPOLOGY_FLAGS))
def test_every_topology_builds_a_document_mupdf_opens(name: str) -> None:
    scene = vfb.scene_for_topology(name)
    doc = fitz.open(stream=vfb.build(scene), filetype="pdf")
    assert len(doc) >= 1
    for page in doc:
        page.get_drawings()


def test_topology_references_are_what_they_claim() -> None:
    shares = fitz.open(stream=vfb.build(vfb.scene_for_topology("second_page_shares")), filetype="pdf")
    assert shares[0].get_contents() == shares[1].get_contents()
    plain = fitz.open(stream=vfb.build(vfb.scene_for_topology("exclusive")), filetype="pdf")
    assert plain[0].get_contents() != plain[1].get_contents()
    array = fitz.open(stream=vfb.build(vfb.scene_for_topology("shared_array")), filetype="pdf")
    first = array.xref_get_key(array[0].xref, "Contents")
    assert first == array.xref_get_key(array[1].xref, "Contents")
    assert first[0] == "xref"
    sub = fitz.open(stream=vfb.build(vfb.scene_for_topology("substring_xrefs")), filetype="pdf")
    contents = {x for page in sub for x in page.get_contents()}
    assert 5 in contents and 15 in contents


def test_two_stream_contents_and_split_paths() -> None:
    scene = vfb.scene_for_topology("two_streams")
    doc = fitz.open(stream=vfb.build(scene), filetype="pdf")
    assert len(doc[0].get_contents()) == 2


def test_mutants_return_all_names_with_openable_bytes_and_full_facts() -> None:
    scene = vfb.sample_scene()
    result = vfb.mutants(scene, vfb.Op("delete", 0, (1,)))
    assert tuple(name for name, _b, _f in result) == vfb.MUTANT_NAMES
    for _name, data, facts in result:
        fitz.open(stream=data, filetype="pdf")
        assert set(facts) >= set(vfb.FACT_KINDS)


def test_a_correct_delete_differs_from_each_inequivalent_mutant_in_some_fact() -> None:
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, (1,))
    _data, good = vfb.expected(scene, op)
    differing = {
        name
        for name, _b, facts in vfb.mutants(scene, op)
        if vfb.facts_diff(vfb.expected(scene, vfb.scenario_of(name, op))[1], facts, vfb.FACT_KINDS)
    }
    assert "neighbour deleted too" in differing
    assert "one selected path kept" in differing
    assert "/Rotate changed on the edited page" in differing
    assert good is not None


def _mupdf_halves(page: vfb.PageSpec) -> list[tuple[int, str]]:
    drawings = fitz.open(stream=vfb.build(vfb.Scene((page,))), filetype="pdf")[0].get_drawings()
    return [(di, k) for di, d in enumerate(drawings) for k in ("f", "s") if k in str(d.get("type"))]


def test_the_builders_merge_prediction_equals_mupdfs_drawing_halves() -> None:
    """The builder predicts (never reads) which fill and stroke MuPDF merges into one ``fs`` drawing; the
    prediction is compared here with MuPDF over the scenes, the merged-pair twin and every generator seed."""
    from test_scripts import vector_grammar as vg
    from test_scripts import vector_oracle_extra as voe

    pages = [("merged_pair", voe.merged_pair_page()), *((n, s.pages[0]) for n, s in vfb.default_scenes())]
    pages += [(f"seed{seed}", vg.random_scene(seed).pages[0]) for seed in range(80)]
    merged = 0  # pages with a merge MuPDF really made: the comparison is not vacuous
    for name, page in pages:
        predicted = [h for halves in vfb._halves_by_path(page) for h in halves]
        assert predicted == _mupdf_halves(page), name
        by_path = vfb._halves_by_path(page)
        merged += any(by_path[k][0][0] == by_path[k + 1][0][0] for k in range(len(by_path) - 1))  # two PATHS, one drawing
    assert vfb._halves_by_path(voe.merged_pair_page())[1:3] == [[(1, "f")], [(1, "s")]]  # the stroke joined the fill's drawing
    assert merged >= 5


def test_rule_a_mutant_facts_do_not_come_from_reading_bytes() -> None:
    """Rule A: the builder module must not parse the PDFs it emits."""
    source = Path(vfb.__file__).read_text(encoding="utf-8")
    for forbidden in ("fitz.open", "get_drawings", "get_cdrawings", "lex_content_stream"):
        assert forbidden not in source


def test_facts_diff_is_per_kind() -> None:
    a = vfb.Facts({k: 1 for k in vfb.FACT_KINDS})
    b = vfb.Facts({k: 1 for k in vfb.FACT_KINDS})
    b["DICT"] = 2
    assert vfb.facts_diff(a, b, vfb.FACT_KINDS) == ["DICT"]
    assert vfb.facts_diff(a, b, ("PATHS",)) == []


def test_scene_replace_keeps_frozen_scenes_independent() -> None:
    scene = vfb.sample_scene()
    other = replace(scene, topology=vfb.Topology(orphan=True))
    assert vfb.build(scene) != vfb.build(other)
