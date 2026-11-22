"""Card B1 completion, items 3 to 5: O-struct mapped form, O-reopen and O-vendor, calibrated.

The three take a before/after pair, so they are registered in ``vector_oracles.calibrate`` beside the
existing six (through its ``extra_kw`` hook, which supplies each oracle's product-side input from the
builder: index rows, the page frame, a vendor document).  Must-kill is decided from the builder's facts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_index_rows as vir  # noqa: E402
from test_scripts import vector_matching as vm  # noqa: E402
from test_scripts import vector_oracle_extra as voe  # noqa: E402
from test_scripts import vector_oracle_saved as vsv  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402

ALL = {**vo.ORACLES, **vsv.BEFORE_AFTER}
NEW = ("O-struct mapped", "O-reopen", "O-vendor")


def _ops(_scene: object) -> list[vfb.Op]:
    return [vfb.Op("delete", 0, (1,)), vfb.Op("delete", 0, (1, 2)), vfb.Op("delete", 0, (3,)), vfb.Op("delete", 0, (0,)), vfb.Op("delete", 0, (9,))]


def _run(oracles: dict, *, small: bool = True) -> vo.Report:
    # the topologies that differ for the new oracles (shared streams, split streams, shared arrays); the
    # existing calibration test already runs every oracle of the six on all twelve
    scenes = [sc for sc in vfb.default_scenes() if sc[0] in ("exclusive", "two_streams", "second_page_shares", "shared_array", "shares+two_streams")]
    ops = _ops
    if small:  # the meta-tests need a few cells, not the whole matrix
        scenes = [sc for sc in scenes if sc[0] == "exclusive"]
        ops = lambda _s: [vfb.Op("delete", 0, (1, 2)), vfb.Op("delete", 0, (3,))]  # noqa: E731
    return vo.calibrate(vfb, scenes, ops, oracles, extra_kw=vsv.kw_for_matrix)


def _open(data: bytes) -> fitz.Document:
    return fitz.open(stream=data, filetype="pdf")


def _frame_scenes() -> list[tuple[str, vfb.Scene]]:
    """The sample under every page frame: /Rotate 90, 180, 270, an offset CropBox and /UserUnit 2."""
    base = vfb.sample_scene()
    page = base.pages[0]
    variants = {f"rot{r}": vfb.replace(page, rotate=r) for r in (90, 180, 270)}
    variants["cropbox"] = vfb.replace(page, cropbox=(10.0, 20.0, 150.0, 190.0))
    variants["userunit2"] = vfb.replace(page, userunit=2.0)
    return [(n, vfb.replace(base, pages=(p, base.pages[1]))) for n, p in variants.items()]


@pytest.mark.parametrize("frame", [n for n, _s in _frame_scenes()])
def test_every_new_oracle_accepts_correct_edits_and_kills_its_mutants_under_every_page_frame(frame: str) -> None:
    """The mapped oracle's frame and UserUnit handling, O-reopen's attribute check and (variable set) the
    Poppler leg, in one calibration run per frame."""
    scene = dict(_frame_scenes())[frame]
    rep = vo.calibrate(vfb, [(frame, scene)], lambda _s: [vfb.Op("delete", 0, (1, 2)), vfb.Op("delete", 0, (3,))], ALL, extra_kw=vsv.kw_for_matrix)
    mine = [f for f in rep.failures if any(n in f for n in NEW)]
    assert not mine, "\n".join(mine[:10])
    assert rep.ok, "\n".join(rep.failures[:10])  # every frame, /UserUnit 2 included: no failure is tolerated
    assert rep.must_kill["O-pixel"] > 0, "O-pixel judged no must-kill cell under this frame"
    assert all(rep.must_kill[n] > 0 for n in NEW)


def test_the_vendor_deleted_set_matcher_is_not_greedy() -> None:
    """D23: one non-greedy matcher.  a=[0, 0.55], b=[0.28, 0.05] at 0.3: a greedy walk pairs 0 with 0.28 and
    leaves 0.55 unmatched although 0-0.05 and 0.55-0.28 is a perfect matching."""
    a = [("t", (0.0,)), ("t", (0.55,))]
    b = [("t", (0.28,)), ("t", (0.05,))]
    assert vsv._unmatched(a, b, 0.3) == []
    assert vm.unmatched(a, b, 0.3) == []
    assert vm.unmatched(a, b[:1], 0.3) == [a[1]] or len(vm.unmatched(a, b[:1], 0.3)) == 1
    assert len(vm.unmatched(a, [("u", (0.0,)), ("u", (0.55,))], 0.3)) == 2  # tags must be equal
    assert vm.unmatched([], b, 0.3) == []
    assert vm.unmatched(a, [], 0.3) == a
    chain = [("t", (0.3 * k,)) for k in range(40)]  # a long augmenting chain
    assert vm.unmatched(chain, [("t", (0.3 * k + 0.29,)) for k in range(-1, 39)], 0.3) == []


def test_calibration_on_a_page_with_a_merged_fill_and_stroke_accepts_correct_halves_and_kills_every_mutant() -> None:
    """MuPDF merges the fill and the stroke of one path into one drawing: the nine oracles must still
    accept a correct half-delete and kill the mutants, with must-kill cells for every oracle."""
    scenes = [("merged_pair", vfb.Scene((voe.merged_pair_page(),)))]
    ops = [vfb.Op("delete", 0, s) for s in ((1,), (2,), (3,), (1, 2))]
    rep = vo.calibrate(vfb, scenes, lambda _s: ops, ALL, extra_kw=vsv.kw_for_matrix)
    assert rep.ok, "\n".join(rep.failures[:10])
    for name in ALL:
        assert rep.must_kill[name] > 0 and rep.must_pass[name] > 0, name


def test_the_builder_changed_region_scales_by_the_user_unit_and_matches_the_oracle_region() -> None:
    """Under /UserUnit 2 the builder region equals the oracle's (MuPDF scales coordinates and widths), and a
    kept selected path inside that region is invisible to O-pixel (it changes nothing outside it) while the
    mutant still carries the other facts, so it is killed by the oracles whose domain it violates."""
    scene = dict(_frame_scenes())["userunit2"]
    page = scene.pages[0]
    before = vfb.build(scene)
    sel = (1, 2)
    mine = vfb.region_rects(page, vfb.path_ordinals(page, sel))
    theirs = vo.changed_region_rects(_open(before)[0], vfb.drawing_indices(page, sel))
    assert mine and len(mine) == len(theirs)
    for a, b in zip(mine, theirs, strict=True):
        assert all(abs(x - y) < 1e-3 for x, y in zip(a, b, strict=True)), (a, b)
    unit1 = vfb.region_rects(vfb.replace(page, userunit=1.0), vfb.path_ordinals(page, sel))
    assert mine != unit1, "the region must differ from the one at /UserUnit 1"
    # a delete of a path that lies OUTSIDE the region (a neighbour) is a pixel change outside it: killed
    neighbour = vfb.expected(scene, vfb.Op("delete", 0, (0,)))[0]
    facts = vfb.expected(scene, vfb.Op("delete", 0, sel))[1]
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    assert vo.o_pixel(vfb.Op("delete", 0, sel), before, neighbour, **ctx)


# ----------------------------------------------------------------------------- registration and matrix


def test_new_oracles_declare_domains_inside_the_fact_kinds_and_raise_on_unknown_operations() -> None:
    assert set(vsv.BEFORE_AFTER) == set(NEW)
    data = vfb.build(vfb.sample_scene())
    for name, fn in vsv.BEFORE_AFTER.items():
        assert fn.DOMAIN <= set(vfb.FACT_KINDS), name
        with pytest.raises(ValueError):
            fn("rotate", data, data)
    assert vsv.BEFORE_AFTER["O-struct mapped"].DOMAIN == {"PATHS"}
    assert vsv.BEFORE_AFTER["O-vendor"].DOMAIN == {"PATHS"}
    assert vsv.BEFORE_AFTER["O-reopen"].DOMAIN == {"PATHS", "PIXELS_OUTSIDE"}


def test_calibration_matrix_every_new_oracle_rejects_every_must_kill_and_accepts_every_must_pass() -> None:
    rep = _run(ALL, small=False)
    assert rep.ok, "\n".join(rep.failures[:40])
    for name in ALL:
        assert rep.must_kill[name] > 0 and rep.must_pass[name] > 0, name
    assert rep.equivalent_everywhere() == []


@pytest.mark.parametrize("name", NEW)
def test_a_blind_new_oracle_fails_the_run(name: str) -> None:
    def blind(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
        return []

    blind.DOMAIN = ALL[name].DOMAIN  # type: ignore[attr-defined]
    rep = _run({**ALL, name: blind})
    assert any(f"{name} is blind" in f for f in rep.failures)


@pytest.mark.parametrize("name", NEW)
def test_a_paranoid_new_oracle_fails_the_run(name: str) -> None:
    def paranoid(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
        return ["always"]

    paranoid.DOMAIN = ALL[name].DOMAIN  # type: ignore[attr-defined]
    rep = _run({**ALL, name: paranoid})
    assert any(f"{name} rejects must-pass" in f for f in rep.failures)


def test_a_mutant_outside_every_domain_still_fails_the_run_with_the_new_oracles_registered() -> None:
    rep = _run({n: vsv.BEFORE_AFTER[n] for n in NEW})
    assert any(f.startswith("coverage gap") for f in rep.failures)  # no oracle covers DICT, OBJECTS ...


# ----------------------------------------------------------------------------- O-struct mapped: delete and move


def _case(selected: tuple[int, ...]) -> tuple[vfb.Scene, vfb.Op, bytes, dict]:
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, selected)
    facts = vfb.expected(scene, op)[1]
    kw = {**vsv.kw_for_matrix(scene, op), **{k: v for k, v in facts.context.items() if k not in ("scenario_op", "expected")}}
    return scene, op, vfb.build(scene), kw


def test_mapped_delete_accepts_the_correct_edit_and_kills_a_neighbour_and_a_kept_path() -> None:
    scene, op, before, kw = _case((1, 2))
    good = vfb.expected(scene, op)[0]
    assert vsv.o_struct_mapped(op, before, good, **kw) == []
    wider = vfb.expected(scene, vfb.Op("delete", 0, (1, 2, 3)))[0]
    assert vsv.o_struct_mapped(op, before, wider, **kw)
    narrower = vfb.expected(scene, vfb.Op("delete", 0, (1,)))[0]
    assert vsv.o_struct_mapped(op, before, narrower, **kw)
    assert vsv.o_struct_mapped(op, before, before, **kw)  # nothing deleted


def test_mapped_delete_keeps_the_surviving_half_of_a_merged_fill_and_stroke() -> None:
    page = voe.merged_pair_page()
    scene = vfb.Scene((page,))
    before = vfb.build(scene)
    for sel, survivor in (((2,), "f"), ((1,), "s")):  # delete the stroke: the fill stays; and the reverse
        op = vfb.Op("delete", 0, sel)
        kw = {"rows": vir.rows_from_page(page), "frame": vir.frame_of(page), "selected_rows": vir.selected_rows(page, sel)}
        good = vfb.expected(scene, op)[0]
        types = [d["type"] for d in _open(good)[0].get_cdrawings()]
        assert survivor in types and "fs" not in types[:2]
        assert vsv.o_struct_mapped(op, before, good, **kw) == [], sel
        both = vfb.expected(scene, vfb.Op("delete", 0, (1, 2)))[0]
        assert vsv.o_struct_mapped(op, before, both, **kw), "the surviving half was removed too"
        assert vsv.o_struct_mapped(op, before, before, **kw), "the selected half survived"


def _move_case(sel: tuple[int, ...], dx: float, dy: float) -> tuple[vfb.Scene, vfb.Op, bytes, bytes, dict]:
    scene = vfb.sample_scene()
    page = scene.pages[0]
    moved = vsv.moved_page(page, sel, dx, dy)
    op = vfb.Op("move", 0, sel)
    kw = {
        "rows": vir.rows_from_page(page),
        "frame": vir.frame_of(page),
        "selected_rows": vir.selected_rows(page, sel),
        "delta": (dx, dy),  # row (user) space: the oracle maps it through the frame's linear part
    }
    return scene, op, vfb.build(scene), vfb.build(vfb.replace(scene, pages=(moved, scene.pages[1]))), kw


def test_mapped_move_accepts_the_translated_selection_and_kills_wrong_moves() -> None:
    scene, op, before, good, kw = _move_case((0, 9), 7.0, 3.0)
    assert vsv.o_struct_mapped(op, before, good, **kw) == []
    assert vsv.o_struct_mapped(op, before, before, **kw), "nothing moved"
    assert vsv.o_struct_mapped(op, before, good, **{**kw, "delta": (7.0, -3.0)}), "wrong delta sign"
    assert vsv.o_struct_mapped(op, before, good, **{**kw, "delta": (7.0 + 0.01, 3.0)}), "delta off by 0.01"
    other = _move_case((0,), 7.0, 3.0)[3]
    assert vsv.o_struct_mapped(op, before, other, **kw), "one selected path stayed"


def test_mapped_move_tolerates_the_product_six_decimals_and_rejects_a_drift_beyond_it() -> None:
    _scene, op, before, good, kw = _move_case((0,), 7.0, 3.0)
    near = _move_case((0,), 7.0004, 3.0004)[3]  # 4e-4 pt: inside the 1e-3 tolerance
    assert vsv.o_struct_mapped(op, before, near, **kw) == []
    far = _move_case((0,), 7.0, 3.01)[3]
    assert vsv.o_struct_mapped(op, before, far, **kw)


def test_mapped_move_kills_an_unselected_path_that_moved_and_a_swapped_order() -> None:
    scene, op, before, good, kw = _move_case((0,), 7.0, 3.0)
    wrong = _move_case((0, 9), 7.0, 3.0)[3]  # path 9 moved although it was not selected
    assert vsv.o_struct_mapped(op, before, wrong, **kw)
    page = scene.pages[0]
    items = list(vsv.moved_page(page, (0,), 7.0, 3.0).items)
    items[0], items[9] = items[9], items[0]  # same drawings, other order
    swapped = vfb.build(vfb.replace(scene, pages=(vfb.replace(page, items=tuple(items)), scene.pages[1])))
    assert vsv.o_struct_mapped(op, before, swapped, **kw)


def test_moved_page_shifts_a_path_under_a_cumulative_scale_by_exactly_the_stated_delta() -> None:
    scene, _op, before, good, _kw = _move_case((0, 9), 7.0, 3.0)
    old, new = _open(before)[0].get_cdrawings(), _open(good)[0].get_cdrawings()
    for item in (0, 9, 5):
        i = vfb.drawing_indices(scene.pages[0], (item,))[0]
        a = [c for it in old[i]["items"] for p in it[1:] for c in p]
        b = [c for it in new[i]["items"] for p in it[1:] for c in p]
        want = (7.0, -3.0) if item in (0, 9) else (0.0, 0.0)  # item 5 stays (user y up, drawing y down)
        assert all(abs((y - x) - want[k % 2]) < 1e-3 for k, (x, y) in enumerate(zip(a, b, strict=True))), item


def test_moved_page_refuses_a_path_whose_translation_is_not_a_cm_operand_change() -> None:
    page = vfb.sample_scene().pages[0]
    with pytest.raises(ValueError):
        vsv.moved_page(page, (3,), 1.0, 1.0)  # a cumulative item
    with pytest.raises(ValueError):
        vsv.moved_page(page, (1,), 1.0, 1.0)  # a block member


def test_mapped_oracle_reports_an_unmappable_before_document() -> None:
    scene, op, before, kw = _case((1,))
    out = vsv.o_struct_mapped(op, before, before, **{**kw, "rows": kw["rows"][:3]})
    assert out and "O-scan" in out[0]


# ----------------------------------------------------------------------------- O-reopen


def test_reopen_round_trip_keeps_a_correct_delete_and_kills_the_three_damages() -> None:
    scene, op, before, kw = _case((1, 2))
    good = vfb.expected(scene, op)[0]
    assert vsv.o_reopen(op, before, good, **kw) == []
    assert vsv.o_reopen(op, before, before, **kw), "a path survives the save"
    doc = _open(good)
    doc.xref_set_key(doc.page_xref(0), "Rotate", "90")
    assert vsv.o_reopen(op, before, doc.tobytes(garbage=0), **kw), "a changed page attribute"
    doc = _open(good)
    doc.xref_set_key(doc.page_xref(0), "CropBox", "[1 1 190 190]")
    assert vsv.o_reopen(op, before, doc.tobytes(garbage=0), **kw), "a changed crop box"
    page = scene.pages[0]
    items = list(page.items)
    items[6] = vfb.replace(items[6], state=vfb.replace(items[6].state, stroke=(1.0, 0.0, 0.0)))  # an unselected path
    recoloured = vfb.expected(vfb.replace(scene, pages=(vfb.replace(page, items=tuple(items)), scene.pages[1])), op)[0]
    assert vsv.o_reopen(op, before, recoloured, **kw), "a pixel change outside the region"


def test_reopen_judges_the_reopened_file_not_the_produced_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A save that damages a correct edit is caught, and an oracle that skipped the save would not catch it."""
    scene, op, before, kw = _case((1, 2))
    good = vfb.expected(scene, op)[0]
    assert vsv.o_reopen(op, before, good, **kw) == []
    real = vsv.save_roundtrip
    calls: list[int] = []

    def damaging(data: bytes) -> bytes:
        calls.append(1)
        doc = _open(real(data))
        doc.xref_set_key(doc.page_xref(0), "Rotate", "180")  # damage made by the "save"
        return doc.tobytes(garbage=0)

    monkeypatch.setattr(vsv, "save_roundtrip", damaging)
    assert vsv.o_reopen(op, before, good, **kw), "the correct produced bytes were judged, not the reopened file"
    assert calls
    scene2, op2, before2, kw2 = _case((3,))

    def losing(data: bytes) -> bytes:
        return vfb.build(scene2)  # the "save" brought the deleted path back

    monkeypatch.setattr(vsv, "save_roundtrip", losing)
    assert vsv.o_reopen(op2, before2, vfb.expected(scene2, op2)[0], **kw2)


def test_reopen_class_a_adds_the_byte_check_across_the_save() -> None:
    scene, op, before, kw = _case((1, 2))
    good = vfb.expected(scene, op)[0]
    assert vsv.o_reopen(op, before, good, save_class="A", **kw) == []
    doc = _open(good)
    cx = doc[0].get_contents()[0]
    doc.update_stream(cx, (doc.xref_stream(cx) or b"") + b"% sneaked in\n")
    assert vsv.o_reopen(op, before, doc.tobytes(garbage=0), save_class="A", **kw)
    no_plan = {k: v for k, v in kw.items() if k not in ("ranges", "envelopes")}
    with pytest.raises(ValueError):
        vsv.o_reopen(op, before, good, save_class="A", **no_plan)  # class A needs the plan's ranges


def test_reopen_has_no_move_rule_yet() -> None:
    data = vfb.build(vfb.sample_scene())
    with pytest.raises(ValueError, match="move"):
        vsv.o_reopen("move", data, data)


def test_poppler_leg_is_a_clean_noop_when_the_variable_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PDF_EDITOR_PDFTOPPM", raising=False)
    assert vsv.poppler_available() is False
    data = vfb.build(vfb.sample_scene())
    assert vsv.poppler_agrees(data) == []
    scene, op, before, kw = _case((1, 2))
    assert vsv.o_reopen(op, before, vfb.expected(scene, op)[0], **kw) == []


def test_poppler_comparison_accepts_the_same_page_and_rejects_a_different_one() -> None:
    a = np.full((40, 40, 3), 255, dtype=np.uint8)
    b = a.copy()
    b[5:35, 5:35] = 0
    assert vsv.renders_agree(a, a.copy())
    assert not vsv.renders_agree(a, b)
    edge = a.copy()
    edge[:, 20] = 200  # a one-column anti-aliasing difference
    assert vsv.renders_agree(a, edge)
    assert not vsv.renders_agree(a, a[:, :30])  # different sizes beyond one pixel


def test_poppler_agrees_with_mupdf_on_every_twin_and_kills_a_different_document() -> None:
    base = vfb.sample_scene()
    hole = vfb.replace(base, pages=(vfb.replace(base.pages[0], items=tuple(i for k, i in enumerate(base.pages[0].items) if k != 1)), base.pages[1]))
    different = vsv.poppler_compare(vfb.build(hole), vfb.build(base))
    same = vsv.poppler_compare(vfb.build(base), vfb.build(base))
    if not os.environ.get("PDF_EDITOR_PDFTOPPM"):
        # no Poppler on this run: the leg is a documented no-op, and that is what is asserted (state, not a skip)
        assert vsv.poppler_available() is False
        assert different == [] and same == [], "an unset leg must neither pass nor fail anything"
        assert vsv.poppler_agrees(vfb.build(base)) == []
        return
    assert vsv.poppler_available() is True
    for name, scene in [*vfb.default_scenes(), *_frame_scenes()]:
        assert vsv.poppler_agrees(vfb.build(scene)) == [], name
    assert different, "Poppler's render of the damaged file must disagree with MuPDF's render of the intact one"
    assert same == []


# ----------------------------------------------------------------------------- O-vendor


def test_vendor_accepts_survivors_equal_to_the_vendor_file_and_kills_a_survivor_that_differs() -> None:
    scene, op, before, kw = _case((3,))  # a selection for which all three named mutants are real
    good = vfb.expected(scene, op)[0]
    assert vsv.o_vendor(op, before, good, **kw) == []
    seen = []
    for mname, mdata, _facts in vfb.mutants(scene, op):
        if mname in ("neighbour deleted too", "one selected path kept", "range shifted by one token"):
            seen.append(mname)
            assert vsv.o_vendor(op, before, mdata, **kw), mname
    assert len(seen) == 3


def test_vendor_tolerates_float32_re_emission_and_masks_watermark_groups() -> None:
    scene, op, before, kw = _case((1, 2))
    good = vfb.expected(scene, op)[0]
    jittered = vsv.vendor_from_expected(scene, op, jitter=4e-4)
    assert vsv.o_vendor(op, before, good, **{**kw, "vendor": jittered}) == []
    assert vsv.o_vendor(op, before, good, **{**kw, "vendor": vsv.vendor_from_expected(scene, op, jitter=0.05)}), "a 0.05 pt shift"
    marked = vsv.with_watermark(kw["vendor"], (152.0, 152.0, 188.0, 188.0))
    assert vsv.o_vendor(op, before, good, **{**kw, "vendor": marked}), "the vendor's extra group is a difference unless masked"
    assert vsv.o_vendor(op, before, good, **{**kw, "vendor": marked, "mask_rects": [(150.0, 150.0, 190.0, 190.0)]}) == []


def test_vendor_derives_the_vendor_deleted_set_by_order_free_geometric_matching() -> None:
    scene, op, before, kw = _case((1, 2))
    deleted = vsv.vendor_deleted_set(before, kw["vendor"])
    assert len(deleted) == 3  # the 'fs' rectangle (fill and stroke) and the line
    assert vsv.vendor_deleted_set(before, before) == []
    shuffled = vsv.vendor_from_expected(scene, vfb.Op("delete", 0, (1, 2)), jitter=0.2)  # within 0.3 pt
    assert len(vsv.vendor_deleted_set(before, shuffled)) == 3


def test_vendor_requires_a_vendor_document() -> None:
    data = vfb.build(vfb.sample_scene())
    with pytest.raises(ValueError, match="vendor"):
        vsv.o_vendor("delete", data, data)


# ----------------------------------------------------------------------------- comparable list for the mapped form


def _inline_case() -> tuple[vfb.Scene, vfb.Op, bytes, bytes, dict]:
    page = voe.inline_image_page()
    scene = vfb.Scene((page,))
    op = vfb.Op("delete", 0, (0,))  # the line before the inline image
    kw = {"rows": vir.rows_from_page(page), "frame": vir.frame_of(page), "selected_rows": vir.selected_rows(page, (0,))}
    return scene, op, vfb.build(scene), vfb.expected(scene, op)[0], kw


def test_mapped_form_works_on_the_comparable_list_of_a_page_with_an_inline_image() -> None:
    scene, op, before, good, kw = _inline_case()
    assert len(_open(before)[0].get_cdrawings()) == 2  # MuPDF also draws the path past the BI
    assert vsv.o_struct_mapped(op, before, good, **kw) == []
    assert vsv.o_struct_mapped(op, before, before, **kw), "the selected path survived"
    other = vfb.expected(scene, vfb.Op("delete", 0, (2,)))[0]  # the path past the BI is not in the comparable list
    assert vsv.o_struct_mapped(op, before, other, **kw), "the wrong path was deleted"


def test_mapped_form_works_on_the_comparable_list_of_a_page_that_calls_a_form() -> None:
    page, before = voe.form_page_data()
    scene = vfb.Scene((page,))
    op = vfb.Op("delete", 0, (0,))
    kw = {"rows": vir.rows_from_page(page), "frame": vir.frame_of(page), "selected_rows": vir.selected_rows(page, (0,))}
    good = voe.add_form(vfb.expected(scene, op)[0])
    assert len(_open(before)[0].get_cdrawings()) == 3  # the form's line is drawn by MuPDF too
    assert vsv.o_struct_mapped(op, before, good, **kw) == []
    assert vsv.o_struct_mapped(op, before, before, **kw)
    wrong = voe.add_form(vfb.expected(scene, vfb.Op("delete", 0, (2,)))[0])
    assert vsv.o_struct_mapped(op, before, wrong, **kw)


# ----------------------------------------------------------------------------- the default sweep, the new oracles registered


def test_the_default_sweep_with_the_new_oracles_registered_keeps_every_oracle_above_the_kill_floor() -> None:
    from test_scripts import test_vector_oracle_mutation_sweep as sweep

    res = sweep.run_sweep(extra=vsv.BEFORE_AFTER, extra_kw=vsv.kw_for_matrix)
    assert not res["survivors"], "\n".join(res["survivors"][:20])  # type: ignore[arg-type]
    assert not res["missed"], "\n".join(res["missed"][:20])  # type: ignore[arg-type]  # every in-domain oracle rejects every in-domain mutant
    weak = {n: k for n, k in res["kills"].items() if k < sweep.MIN_KILLS}  # type: ignore[attr-defined]
    assert not weak, weak
    assert set(NEW) <= set(res["kills"])  # type: ignore[arg-type]
