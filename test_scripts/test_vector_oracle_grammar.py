"""Card B1 completion, item 6: the grammar-based twin generator feeds the same calibration.

Seeds are fixed here and appear in the test ids: a failing seed prints itself.  The generator emits
``vector_fixture_builder.Scene`` objects, so ``build``, ``expected``, ``mutants``, the facts and the
independent emitter apply unchanged.  The correct delete of a random selection must pass every
oracle (the six and the three before/after oracles of the completion card), the row oracles must
pass on the generated pages' own rows, and the sweep mutants derived from the same scenes must all
be killed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import test_vector_oracle_mutation_sweep as sweep  # noqa: E402
from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_grammar as vg  # noqa: E402
from test_scripts import vector_index_rows as vir  # noqa: E402
from test_scripts import vector_oracle_extra as voe  # noqa: E402
from test_scripts import vector_oracle_saved as vsv  # noqa: E402
from test_scripts import vector_oracle_scan as vos  # noqa: E402
from test_scripts import vector_oracles as vo  # noqa: E402

# chosen (greedy set cover over seeds 0..299, see test_the_judged_seeds_cover_the_grammar) so that the judged seeds
# together emit every grammar feature: paints, kinds, /OC, text and comment, a fill and a stroke of one path in both
# orders, a split stream and every topology flag the generator draws
SEEDS = (1, 2, 3, 8, 22, 23, 33, 42)
SWEEP_SEEDS = (22, 33)
ALL = {**vo.ORACLES, **vsv.BEFORE_AFTER}
NEW = tuple(vsv.BEFORE_AFTER)


def test_the_generator_is_seeded_and_reproducible() -> None:
    assert vg.random_scene(5) == vg.random_scene(5)
    assert vg.random_scene(5) != vg.random_scene(6)
    assert vg.random_ops(vg.random_scene(5), 5) == vg.random_ops(vg.random_scene(5), 5)


def test_the_generator_respects_its_caps_and_the_builders_constraints() -> None:
    for seed in range(60):
        scene = vg.random_scene(seed)
        items = scene.pages[0].items
        assert 4 <= len(items) <= vg.MAX_ITEMS, seed
        assert any(vfb.is_editable(i) for i in items), seed
        groups: dict[int, list[int]] = {}
        for idx, it in enumerate(items):
            if isinstance(it, vfb.PathSpec) and it.state.block is not None:
                groups.setdefault(it.state.block, []).append(idx)
        for members in groups.values():  # contiguous, one shared ctm
            assert members == list(range(members[0], members[0] + len(members))), seed
            assert len({items[m].ctm for m in members}) == 1, seed
        split = scene.pages[0].split_at
        assert split is None or (0 < split < len(items) and not (
            isinstance(items[split], vfb.PathSpec) and isinstance(items[split - 1], vfb.PathSpec)
            and items[split].state.block is not None and items[split].state.block == items[split - 1].state.block)), seed
        for op in vg.random_ops(scene, seed):
            assert op.kind == "delete" and op.selected and all(vfb.is_editable(items[i]) for i in op.selected), seed


def _judged() -> list[int]:
    """The seeds the calibration actually runs on (the matrix seeds and the sweep seeds)."""
    return sorted({*SEEDS, *SWEEP_SEEDS})


def test_the_judged_seeds_cover_the_grammar() -> None:
    """Coverage is asserted on the seeds that are JUDGED, not on a wider range nothing calibrates."""
    seen: set[str] = set()
    for seed in _judged():
        scene = vg.random_scene(seed)
        topo = scene.topology
        seen.update(f"topology:{name}" for name in ("second_page_shares", "shared_array", "form", "pattern", "ap", "orphan", "substring_xrefs", "indirect_length") if getattr(topo, name))
        items = scene.pages[0].items
        for a, b in zip(items, items[1:], strict=False):
            if isinstance(a, vfb.PathSpec) and isinstance(b, vfb.PathSpec) and (a.kind, a.points, a.ctm) == (b.kind, b.points, b.ctm) and {a.paint, b.paint} == {"f", "S"}:
                seen.add("pair:f+S" if a.paint == "f" else "pair:S+f")
        for it in items:
            if isinstance(it, vfb.RawSpec):
                seen.add("raw:" + it.label)
                continue
            seen.add("kind:" + it.kind)
            seen.add("paint:" + it.paint)
            st = it.state
            seen.update(name for name, on in (
                ("clip", st.clip), ("oc", st.oc), ("gs", st.gs), ("dash", bool(st.dash)), ("group", st.block is not None),
                ("cumulative", st.shape == "cumulative"), ("cm", it.ctm != vfb.IDENT),
            ) if on)
        seen.add("split" if scene.pages[0].split_at is not None else "single")
    expected = {"clip", "oc", "gs", "dash", "group", "cumulative", "cm", "split", "single", "raw:text", "raw:comment",
                "kind:line", "kind:poly", "kind:rect", "kind:curve", "paint:S", "paint:f", "paint:B", "paint:n",
                "pair:f+S", "pair:S+f", "topology:second_page_shares", "topology:shared_array", "topology:form",
                "topology:pattern", "topology:ap", "topology:orphan", "topology:substring_xrefs", "topology:indirect_length"}
    assert expected <= seen, sorted(expected - seen)


def test_the_generator_over_a_wide_range_emits_every_feature() -> None:
    seen: set[str] = set()
    for seed in range(60):
        scene = vg.random_scene(seed)
        for it in scene.pages[0].items:
            if isinstance(it, vfb.RawSpec):
                seen.add("raw:" + it.label)
                continue
            seen.add("kind:" + it.kind)
            seen.add("paint:" + it.paint)
            st = it.state
            seen.update(name for name, on in (
                ("clip", st.clip), ("oc", st.oc), ("gs", st.gs), ("dash", bool(st.dash)), ("group", st.block is not None),
                ("cumulative", st.shape == "cumulative"), ("cm", it.ctm != vfb.IDENT),
            ) if on)
        seen.add("split" if scene.pages[0].split_at is not None else "single")
    expected = {"clip", "oc", "gs", "dash", "group", "cumulative", "cm", "split", "single", "raw:text", "raw:comment",
                "kind:line", "kind:poly", "kind:rect", "kind:curve", "paint:S", "paint:f", "paint:B", "paint:n"}
    assert expected <= seen, sorted(expected - seen)


@pytest.mark.parametrize("seed", SEEDS, ids=[f"seed{s}" for s in SEEDS])
def test_the_correct_delete_of_a_random_selection_passes_every_oracle_and_every_mutant_is_killed(seed: int) -> None:
    scene = vg.random_scene(seed)
    ops = vg.random_ops(scene, seed)
    rep = vo.calibrate(vfb, [(f"seed{seed}", scene)], lambda _s: ops, ALL, extra_kw=vsv.kw_for_matrix)
    assert rep.ok, f"seed {seed}: " + "\n".join(rep.failures[:10])
    for name in ALL:
        assert rep.must_pass[name] > 0, (seed, name)


@pytest.mark.parametrize("seed", SEEDS, ids=[f"seed{s}" for s in SEEDS])
def test_the_row_oracles_pass_on_the_generated_pages_and_kill_their_mutants(seed: int) -> None:
    scene = vg.random_scene(seed)
    cells = voe.scan_cells(f"seed{seed}", scene.pages[0], scene=scene)
    rows = vir.rows_from_page(scene.pages[0])
    curve_rows = [r for r in rows if r.cubics and r.paint != "n"]
    for k, r in enumerate(curve_rows[:2]):
        cells += voe.flat_cells(f"seed{seed}/curve{k}", [r])
    rep = voe.calibrate_cells(cells, {"O-scan": vos.o_scan, **({"O-flat": voe.vof.o_flat} if curve_rows else {})})
    failures = [f for f in rep.failures if "empty must-kill column" not in f]
    assert not failures, f"seed {seed}: " + "\n".join(failures[:10])
    assert rep.must_kill["O-scan"] > 0


def test_the_sweep_mutants_of_generated_scenes_are_all_killed_by_every_oracle_of_their_domain() -> None:
    scenes = [(f"seed{s}", vg.random_scene(s)) for s in SWEEP_SEEDS]
    start = time.perf_counter()
    res = sweep.run_sweep(
        "grammar",
        scenes=scenes,
        selections=lambda scene: tuple(op.selected for op in vg.random_ops(scene, 1, count=2)),
        tokens=40,
        extra=vsv.BEFORE_AFTER,
        extra_kw=vsv.kw_for_matrix,
    )
    print(f"\ngrammar sweep: {res['total']} mutants, {len(res['survivors'])} survivors, kills {res['kills']}, {time.perf_counter() - start:.1f} s")  # type: ignore[arg-type]
    assert not res["survivors"], "\n".join(res["survivors"][:20])  # type: ignore[arg-type]
    weak = {n: k for n, k in res["kills"].items() if n in NEW and k < sweep.MIN_KILLS}  # type: ignore[attr-defined]
    assert not weak, f"new oracles that reject fewer than {sweep.MIN_KILLS} sweep mutants of their own domain: {weak}"

