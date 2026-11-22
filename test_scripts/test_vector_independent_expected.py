"""Card B1: the independent expected-stream emitter must not share the cutter (handoff item 4)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts import vector_fixture_builder as vfb  # noqa: E402
from test_scripts import vector_independent_expected as vie  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
EMITTER = "vector_independent_expected"
# Shared leaf modules the emitter may import (none today): a leaf has no splice or cut helper.
ALLOWED_SHARED_LEAVES: frozenset[str] = frozenset()
CUT_MODULES = frozenset({"vector_fixture_builder"})  # defines _cut / _plan / _commit

SELECTIONS = (
    (1,), (2,), (1, 2), (3,), (0,), (9,), (4,), (5,), (6,), (3, 4), (0, 1, 2), (3, 4, 5, 6),
    (0, 3, 9), (1, 2, 3), (7,), (8,), (10,), (11,), (), (99,), (1, 1), (0, 1, 2, 3, 4, 5, 6, 9),
    (2, 3), (1, 3), (0, 6), (4, 5), (0, 1, 2, 3, 4, 5, 6),
)


def _layout_scene() -> vfb.Scene:
    """Stream layouts the sample scene lacks: a fill-only ``f`` path at stream byte 0, a group whose opener
    carries a ``cm``, a second group, a standalone deletable block with a ``cm``, and a second stream."""
    p = vfb._p
    items = (
        p("rect", ((5, 5), (25, 25)), "f", fill=(0.0, 0.5, 0.0), shape="cumulative"),  # 0: first bytes, fill only
        p("rect", ((30, 30), (60, 60)), "B", (1, 0, 0, 1, 5, 5), fill=(1.0, 0.0, 0.0), block=1),  # 1: opener has a cm
        p("line", ((32, 32), (70, 90)), "S", stroke=(0.5, 0.0, 0.5), block=1),  # 2
        p("line", ((90, 20), (120, 40)), "S", (1, 0, 0, 1, 3, 3), block=2),  # 3: second group, opener cm
        p("rect", ((95, 50), (130, 70)), "f", fill=(0.0, 0.0, 1.0), block=2),  # 4
        p("rect", ((140, 140), (170, 170)), "f", (1, 0, 0, 1, 2, 2), fill=(0.2, 0.2, 0.2)),  # 5: standalone block + cm
        p("line", ((10, 150), (60, 160)), "S", stroke=(0.0, 0.0, 0.0), shape="cumulative"),  # 6
    )
    other = vfb.PageSpec((p("line", ((5, 5), (95, 95)), "S", stroke=(0.3, 0.3, 0.9)),))
    return vfb.Scene((vfb.PageSpec(items), other))


def _layout_scenes() -> list[tuple[str, vfb.Scene]]:
    scene = _layout_scene()
    split = vfb.replace(scene.pages[0], split_at=3)
    return [("layout", scene), ("layout+two_streams", vfb.Scene((split, scene.pages[1])))]


def _streams(doc_bytes: bytes) -> list[bytes]:
    doc = fitz.open(stream=doc_bytes, filetype="pdf")
    return [doc.xref_stream(x) for x in doc[0].get_contents()]


def _imports(path: Path, root: Path = SCRIPTS) -> set[str]:
    """Names of modules of ``root`` (default: test_scripts) that ``path`` imports (any statement, any depth)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name.rsplit(".", 1)[-1] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("test_scripts", "") or mod.startswith("test_scripts."):
                out.update(a.name for a in node.names)
                out.add(mod.rsplit(".", 1)[-1])
            else:
                out.add(mod.rsplit(".", 1)[-1])
    return {n for n in out if (root / f"{n}.py").exists()}


def _closure(start: str, root: Path = SCRIPTS) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        cur = todo.pop()
        for dep in _imports(root / f"{cur}.py", root):
            if dep not in seen:
                seen.add(dep)
                todo.append(dep)
    return seen


def test_emitter_import_chain_never_reaches_the_cutter() -> None:
    reach = _closure(EMITTER)
    assert not (reach & CUT_MODULES), reach & CUT_MODULES
    assert reach <= ALLOWED_SHARED_LEAVES, reach - ALLOWED_SHARED_LEAVES


def test_emitter_source_never_names_the_splice_helpers() -> None:
    src = (SCRIPTS / f"{EMITTER}.py").read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    assert not names & {"_cut", "_plan", "_commit", "_merge", "_envelopes", "_emit_page", "_assemble"}


def test_guard_detects_a_chain_through_another_module(tmp_path: Path) -> None:
    """The walker itself: a module reaching the builder through a middle module is caught.  The temporary
    modules live in ``tmp_path``, never in test_scripts/."""
    (tmp_path / "vector_fixture_builder.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "guard_middle.py").write_text("from test_scripts import vector_fixture_builder\n", encoding="utf-8")
    (tmp_path / "guard_top.py").write_text("from test_scripts import guard_middle\n", encoding="utf-8")
    assert "vector_fixture_builder" in _closure("guard_top", tmp_path)
    assert _closure("guard_top", tmp_path) == {"guard_middle", "vector_fixture_builder"}


@pytest.mark.parametrize("fate", ["commit", "rollback"])
def test_independent_equals_current_expected(fate: str) -> None:
    checked = 0
    scenes = [*vfb.default_scenes(), *_layout_scenes()]
    for name, scene in scenes:
        for sel in SELECTIONS:
            op = vfb.Op("delete", 0, sel, fate)
            old = _streams(vfb.expected(scene, op)[0])
            new = vie.expected_streams(scene, op)
            assert new == old, (name, sel, fate)
            checked += 1
    assert checked == len(scenes) * len(SELECTIONS)
    assert len(set(SELECTIONS)) == len(SELECTIONS)  # no selection is listed twice


def test_the_layout_scene_really_has_the_layouts_it_claims() -> None:
    """The differential is only as wide as the layouts: pin that the scene produces them."""
    streams = vie.expected_streams(_layout_scene(), vfb.Op("delete", 0, (), "commit"))
    assert len(streams) == 1
    text = streams[0]
    assert text.startswith(b"0 0.5 0 rg 5 5 20 20 re f")  # a fill-only path at stream byte 0, no q
    assert text.count(b" cm") >= 3  # group openers and the standalone block carry a cm
    assert text.count(b"q") >= 3
    split = vie.expected_streams(_layout_scenes()[1][1], vfb.Op("delete", 0, (), "commit"))
    assert len(split) == 2


def test_deleting_something_changes_the_stream() -> None:
    scene = vfb.sample_scene()
    before = vie.expected_streams(scene, vfb.Op("delete", 0, (), "commit"))
    after = vie.expected_streams(scene, vfb.Op("delete", 0, (1, 2), "commit"))
    assert before != after and len(after[0]) < len(before[0])


def test_bad_operations_raise() -> None:
    scene = vfb.sample_scene()
    with pytest.raises(ValueError):
        vie.expected_streams(scene, vfb.Op("move", 0, (0,)))
    with pytest.raises(ValueError):
        vie.expected_streams(scene, vfb.Op("delete", 1, (0,)))


def test_cross_mutation_off_by_one_cutter_is_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, (1, 2))
    good = _streams(vfb.expected(scene, op)[0])
    independent = vie.expected_streams(scene, op)
    assert independent == good

    real_cut = vfb._cut

    def off_by_one(data: bytes, ranges: list[tuple[int, int]]) -> bytes:
        return real_cut(data, [(s, e + 1) for s, e in ranges])

    monkeypatch.setattr(vfb, "_cut", off_by_one)
    broken_expected = _streams(vfb.expected(scene, op)[0])
    name = vfb.MUTANT_NAMES[4]  # in-place write: identical bytes to expected() on an exclusive scene
    broken_mutant = next(d for n, d, _f in vfb.mutants(scene, op) if n == name)
    # the old oracle pair agrees with itself: the bug is invisible to it ...
    assert _streams(broken_mutant) == broken_expected
    assert broken_expected != good
    # ... and the independent emitter still disagrees with both
    assert vie.expected_streams(scene, op) == good
    assert vie.expected_streams(scene, op) != broken_expected
    assert vie.expected_streams(scene, op) != _streams(broken_mutant)
