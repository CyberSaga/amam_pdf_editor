"""Card B1: calibration of the oracles (design plan section 9, D23 rule A, handoff H6).

Every oracle must reject every must-kill cell (a mutant whose facts differ from the correct facts
inside the oracle's DOMAIN) and accept every must-pass input.  Must-kill is decided from the
builder's facts only, never by running an oracle.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import model.doc_bytes as doc_bytes  # noqa: E402  (D24: the product's save prelude is installed)
from model.vector_paths import commit_state  # noqa: E402
from test_scripts import vector_fixture_builder as vfb  # noqa: E402


def _open(data: bytes) -> fitz.Document:
    return fitz.open(stream=data, filetype="pdf")


# ----------------------------------------------------------------------------- commit_state


def test_digest_table_is_stable_and_has_page_trailer_and_container_entries() -> None:
    data = vfb.build(vfb.sample_scene())
    t1 = commit_state.digest_table(_open(data))
    t2 = commit_state.digest_table(_open(data))
    assert t1 == t2
    assert t1.trailer
    assert 3 in t1.pages and 4 in t1.pages
    assert 3 not in t1.entries
    assert t1.xref_length == _open(data).xref_length()
    assert t1.elapsed_ms >= 0.0


def test_null_transaction_table_equals_table_of_the_reopened_snapshot() -> None:
    """Must-pass: capture a snapshot with the product's serializer, reopen, compare (H9)."""
    for name, scene in vfb.default_scenes():
        doc = _open(vfb.build(scene))
        live = commit_state.digest_table(doc)
        snapshot = doc_bytes.keep_snapshot_in_memory(doc)
        assert commit_state.digest_table(doc) == live, f"capture changed the live table ({name})"
        reopened = commit_state.digest_table(_open(snapshot))
        assert reopened == live, f"snapshot reopen changed the table ({name})"
        assert commit_state.undeclared(live, reopened, commit_state.WriteSet(-1, frozenset(), frozenset())) == [], name


def test_undeclared_reports_a_foreign_object_and_the_trailer() -> None:
    data = vfb.build(vfb.sample_scene())
    before = commit_state.digest_table(_open(data))
    doc = _open(data)
    doc.update_stream(9, b"% changed\n")
    after = commit_state.digest_table(doc)
    ws = commit_state.WriteSet(3, frozenset({5}), frozenset())
    assert commit_state.undeclared(before, after, ws) == [9]
    doc2 = _open(data)
    doc2.xref_set_key(-1, "Marker", "(x)")
    assert commit_state.undeclared(before, commit_state.digest_table(doc2), ws) == [-1]


def test_undeclared_allows_the_declared_stream_page_contents_and_new_xrefs() -> None:
    data = vfb.build(vfb.sample_scene())
    before = commit_state.digest_table(_open(data))
    doc = _open(data)
    doc.update_stream(5, b"0 0 m 1 1 l S\n")
    new = doc.get_new_xref()
    doc.update_object(new, "<< >>")
    doc.xref_set_key(3, "Contents", f"{new} 0 R")
    after = commit_state.digest_table(doc)
    ok = commit_state.WriteSet(3, frozenset({5}), frozenset({new}))
    assert commit_state.undeclared(before, after, ok) == []
    assert commit_state.undeclared(before, after, commit_state.WriteSet(3, frozenset({5}), frozenset())) == [new]
    assert 5 in commit_state.undeclared(before, after, commit_state.WriteSet(3, frozenset(), frozenset({new})))


def test_page_object_may_differ_only_in_contents() -> None:
    data = vfb.build(vfb.sample_scene())
    before = commit_state.digest_table(_open(data))
    doc = _open(data)
    doc.xref_set_key(3, "Rotate", "90")
    ws = commit_state.WriteSet(3, frozenset(), frozenset())
    assert commit_state.undeclared(before, commit_state.digest_table(doc), ws) == [3]


def test_digest_table_slices_call_on_yield_and_exclude_callback_time() -> None:
    doc = _open(vfb.build(vfb.sample_scene()))
    calls: list[tuple[int, int]] = []
    table = commit_state.digest_table(doc, on_yield=lambda d, t: calls.append((d, t)), yield_every_ms=0)
    assert calls and calls[-1][0] == calls[-1][1]
    assert all(0 <= d <= t for d, t in calls)
    assert table == commit_state.digest_table(doc)


# ----------------------------------------------------------------------------- oracles

from test_scripts import vector_oracles as vo  # noqa: E402


def _ops(_scene: object) -> list[vfb.Op]:
    return [
        vfb.Op("delete", 0, (1,)),  # one member of a two-path block (D17 rule 4 fails)
        vfb.Op("delete", 0, (1, 2)),  # the whole block
        vfb.Op("delete", 0, (3,)),  # bare path followed by a bare identity path
        vfb.Op("delete", 0, (0,)),
        vfb.Op("delete", 0, (9,)),
    ]


def _run(oracles: dict, *, small: bool = True) -> vo.Report:
    scenes = vfb.default_scenes()
    if small:  # the meta-tests need a few cells, not the whole matrix
        scenes = [sc for sc in scenes if sc[0] in ("exclusive", "second_page_shares")]
    return vo.calibrate(vfb, scenes, _ops, oracles)


def test_every_oracle_declares_a_domain_inside_the_fact_kinds() -> None:
    assert set(vo.ORACLES) == {"O-rebuild", "O-struct", "O-pixel", "O-bytes", "O-dict", "rule B"}
    for name, fn in vo.ORACLES.items():
        assert isinstance(fn.DOMAIN, frozenset) and fn.DOMAIN <= set(vfb.FACT_KINDS), name
    assert vo.ORACLES["O-rebuild"].DOMAIN == frozenset(vfb.FACT_KINDS)
    assert vo.ORACLES["O-struct"].DOMAIN == {"PATHS"}
    assert vo.ORACLES["O-pixel"].DOMAIN == {"PIXELS_OUTSIDE"}
    assert vo.ORACLES["O-bytes"].DOMAIN == {"OUTSIDE_BYTES"}
    assert vo.ORACLES["O-dict"].DOMAIN == {"DICT"}
    assert vo.ORACLES["rule B"].DOMAIN == {"OBJECTS", "OTHER_PAGES"}


@pytest.mark.parametrize("name", sorted(vo.ORACLES))
def test_each_oracle_raises_on_an_operation_it_has_no_rule_for(name: str) -> None:
    data = vfb.build(vfb.sample_scene())
    with pytest.raises(ValueError):
        vo.ORACLES[name]("move", data, data, expected=data)


def test_calibration_every_oracle_rejects_every_must_kill_and_accepts_every_must_pass() -> None:
    rep = _run(vo.ORACLES, small=False)
    assert rep.ok, "\n".join(rep.failures[:40])
    for name in vo.ORACLES:
        assert rep.must_kill[name] > 0, f"{name}: empty must-kill column"
        assert rep.must_pass[name] > 0
    assert rep.equivalent_everywhere() == [], f"stop rule: equivalent on every topology: {rep.equivalent_everywhere()}"


def test_a_deliberately_blind_oracle_fails_the_run() -> None:
    def blind(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
        return []

    blind.DOMAIN = vo.ORACLES["O-struct"].DOMAIN  # type: ignore[attr-defined]
    rep = _run({**vo.ORACLES, "O-struct": blind})
    assert not rep.ok
    assert any("O-struct is blind" in f for f in rep.failures)


def test_an_oracle_that_rejects_a_correct_edit_fails_the_run() -> None:
    def paranoid(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
        return ["always"]

    paranoid.DOMAIN = vo.ORACLES["O-dict"].DOMAIN  # type: ignore[attr-defined]
    rep = _run({**vo.ORACLES, "O-dict": paranoid})
    assert any("rejects must-pass input" in f for f in rep.failures)


def test_a_mutant_outside_every_domain_fails_the_run() -> None:
    """O-rebuild's domain is every kind, so the gap only exists in a registry without it."""
    rep = _run({"O-struct": vo.ORACLES["O-struct"]})
    assert any(f.startswith("coverage gap") for f in rep.failures)


def test_an_oracle_with_an_empty_must_kill_column_fails_the_run() -> None:
    def idle(op: object, before: bytes, after: bytes, **kw: object) -> list[str]:
        return []

    idle.DOMAIN = frozenset()  # type: ignore[attr-defined]
    rep = _run({**vo.ORACLES, "idle": idle})
    assert any("idle has an empty must-kill column" in f for f in rep.failures)


# ----------------------------------------------------------------------------- matching (H7)

from test_scripts import vector_matching as vm  # noqa: E402


def _rec(x: float, tag: str = "s") -> vm.Record:
    return (tag, (x, 0.5))


def _greedy(a: list[vm.Record], b: list[vm.Record]) -> bool:
    free = list(b)
    for rec in a:
        hit = next((i for i, other in enumerate(free) if vm.records_equal(rec, other)), None)
        if hit is None:
            return False
        free.pop(hit)
    return not free


def test_matcher_pairs_two_records_a_greedy_pass_would_mispair() -> None:
    """A1 is within tolerance of B1 and B2, A2 of B1 only; all sit within a tolerance of cell edges."""
    a = [_rec(0.0005), _rec(0.0014)]
    b = [_rec(0.0011), _rec(-0.0004)]
    assert vm.records_equal(a[0], b[0]) and vm.records_equal(a[0], b[1])
    assert vm.records_equal(a[1], b[0]) and not vm.records_equal(a[1], b[1])
    assert _greedy(a, b) is False
    assert vm.match_multisets(a, b) is True
    assert vm.match_multisets(list(reversed(a)), b) is True


def test_matcher_rejects_when_no_perfect_matching_exists() -> None:
    assert vm.match_multisets([_rec(0.0005), _rec(0.0014)], [_rec(0.0011), _rec(0.5)]) is False
    assert vm.match_multisets([_rec(1.0)], [_rec(1.0, "f")]) is False  # tags differ
    assert vm.match_multisets([_rec(1.0)], []) is False
    assert vm.match_multisets([], []) is True


def test_matcher_counts_duplicates_as_a_multiset() -> None:
    assert vm.match_multisets([_rec(2.0), _rec(2.0)], [_rec(2.0), _rec(2.0)]) is True
    assert vm.match_multisets([_rec(2.0), _rec(2.0)], [_rec(2.0), _rec(3.0)]) is False


def test_tolerance_is_max_of_base_and_eight_float32_ulps() -> None:
    assert vm.tolerance(10.0) == 1e-3
    assert vm.tolerance(1e6) > 1e-3  # 8 ulp of float32 at 1e6 is 0.0625
    assert vm.coordinates_match(5.0, 5.0009) and not vm.coordinates_match(5.0, 5.0011)


def test_a_component_over_5000_candidate_edges_fails_as_ambiguous() -> None:
    many = [_rec(0.0) for _ in range(80)]  # 80 x 80 = 6400 candidate edges in one component
    with pytest.raises(vm.AmbiguousFixture, match="ambiguous fixture"):
        vm.match_multisets(many, list(many))


# ----------------------------------------------------------------------------- Astra B1 review fixes


def test_digest_strips_only_the_top_level_length_of_a_stream_dictionary() -> None:
    data = vfb.build(vfb.sample_scene())
    doc = _open(data)
    doc.xref_set_key(9, "Note", "(/Length 1)")
    first = commit_state.digest_table(doc)
    doc.xref_set_key(9, "Note", "(/Length 2)")
    second = commit_state.digest_table(doc)
    ws = commit_state.WriteSet(3, frozenset({5}), frozenset())
    assert commit_state.undeclared(first, second, ws) == [9]
    doc.xref_set_key(9, "Meta", "<< /Length 1 >>")
    third = commit_state.digest_table(doc)
    doc.xref_set_key(9, "Meta", "<< /Length 2 >>")
    assert commit_state.undeclared(third, commit_state.digest_table(doc), ws) == [9]


def test_undeclared_sees_a_new_container_object_and_a_longer_xref_table() -> None:
    data = vfb.build(vfb.sample_scene())
    before = commit_state.digest_table(_open(data))
    doc = _open(data)
    new = doc.get_new_xref()
    doc.update_object(new, "<< /Type /ObjStm >>")
    after = commit_state.digest_table(doc)
    empty = commit_state.WriteSet(-1, frozenset(), frozenset())
    assert commit_state.undeclared(before, after, empty) == [new]
    assert commit_state.undeclared(before, after, commit_state.WriteSet(-1, frozenset(), frozenset({new}))) == []


def test_digest_table_enumerates_pages_and_trailer_inside_the_timed_yielded_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _open(vfb.build(vfb.sample_scene()))
    events: list[str] = []
    real = commit_state._key_digest

    def spy(d: fitz.Document, xref: int, skip: frozenset[str]) -> bytes:
        if xref == commit_state.TRAILER_KEY:
            events.append("trailer")
        return real(d, xref, skip)

    monkeypatch.setattr(commit_state, "_key_digest", spy)
    table = commit_state.digest_table(doc, on_yield=lambda d, t: events.append("yield"), yield_every_ms=0)
    assert events.count("yield") > 2, "a sliced pass must yield during the work, not once at the end"
    assert events.index("trailer") < len(events) - 1 and events[-1] == "yield"
    assert events.index("trailer") < max(i for i, e in enumerate(events) if e == "yield")
    assert table.elapsed_ms > 0.0


def test_matcher_is_safe_across_a_float32_exponent_boundary() -> None:
    a, b = _rec(32767.999), _rec(32768.0)
    assert vm.records_equal(a, b)
    assert vm.match_multisets([a], [b]) is True
    assert vm.match_multisets([b], [a]) is True
    assert vm.match_multisets([_rec(32767.999), _rec(32768.002)], [_rec(32768.001), _rec(32767.998)]) is True


def test_the_edge_cap_is_enforced_before_the_graph_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real = vm.records_equal

    def counting(x: vm.Record, y: vm.Record) -> bool:
        nonlocal calls
        calls += 1
        return real(x, y)

    monkeypatch.setattr(vm, "records_equal", counting)
    many = [_rec(0.0) for _ in range(400)]  # 160,000 candidate pairs if the graph were built
    with pytest.raises(vm.AmbiguousFixture, match="ambiguous fixture"):
        vm.match_multisets(many, list(many))
    assert calls <= vm.MAX_COMPONENT_EDGES + 2 * len(many)


@pytest.mark.parametrize("entry", ["match_multisets", "unmatched"])
@pytest.mark.parametrize("n", [71, 400])
def test_both_matcher_entry_points_refuse_an_over_cap_component_alike(entry: str, n: int) -> None:
    """Astra B5: 71 identical records give 5,041 candidate edges (cap 5,000).  match_multisets raised while
    unmatched() accepted: the cap applies before graph construction in both."""
    many = [_rec(0.0) for _ in range(n)]
    assert n * n > vm.MAX_COMPONENT_EDGES
    fn = vm.match_multisets if entry == "match_multisets" else vm.unmatched
    with pytest.raises(vm.AmbiguousFixture, match="ambiguous fixture"):
        fn(many, list(many))
    under = [_rec(0.0) for _ in range(70)]  # 4,900 edges: still a legal fixture through both
    assert (vm.match_multisets(under, list(under)) is True) if entry == "match_multisets" else (vm.unmatched(under, list(under)) == [])


def test_unmatched_edge_cap_is_enforced_before_the_graph_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real_near = vm.tolerance

    def counting(x: float) -> float:
        nonlocal calls
        calls += 1
        return real_near(x)

    many = [_rec(0.0) for _ in range(400)]
    monkeypatch.setattr(vm, "tolerance", counting)
    with pytest.raises(vm.AmbiguousFixture):
        vm.unmatched(many, list(many))
    # 160,000 candidate pairs if built (about 640,000 calls).  The width scan costs 4 calls per record
    # (two records lists, two coordinates), each tested pair 4 (two coordinates, two tolerances).
    assert calls <= 4 * 2 * len(many) + 4 * (vm.MAX_COMPONENT_EDGES + len(many))


def test_exclusivity_is_decided_per_stream_not_once_per_scene() -> None:
    """D20b: with only S0 shared, a legal in-place edit of S1 is declared in place."""
    scene = dict(vfb.default_scenes())["shares+two_streams"]
    data, facts = vfb.expected(scene, vfb.Op("delete", 0, (6,)))  # item 6 lives in S1
    assert facts.context["stream_xrefs"] == frozenset({6})
    assert facts.context["new_xrefs"] == frozenset()
    before = vfb.build(scene)
    assert vo.rule_b("delete", before, data, **{k: v for k, v in facts.context.items() if k != "scenario_op"}) == []
    # an edit of S0 (shared with page 1) still goes through a copy
    _d0, f0 = vfb.expected(scene, vfb.Op("delete", 0, (3,)))
    assert f0.context["stream_xrefs"] == frozenset() and len(f0.context["new_xrefs"]) == 1  # type: ignore[arg-type]


def test_indirect_length_fixture_gives_the_second_stream_its_own_indirect_length() -> None:
    base = vfb.sample_scene(vfb.Topology(indirect_length=True))
    scene = vfb.replace(base, pages=(vfb.replace(base.pages[0], split_at=5), base.pages[1]))
    doc = _open(vfb.build(scene))
    assert doc.xref_get_key(5, "Length")[1].endswith(" 0 R")
    assert doc.xref_get_key(6, "Length")[1].endswith(" 0 R")
    _data, facts = vfb.expected(scene, vfb.Op("delete", 0, (6,)))
    assert facts.context["stream_xrefs"] == frozenset()  # an indirect /Length forces the copy


def test_o_rebuild_verifies_the_actual_cut_not_the_supplied_ranges() -> None:
    """A correct edit with a comment appended outside every legal envelope is rejected, as O-bytes does."""
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, (1, 2))
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, op)
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    ctx["expected"] = good
    assert vo.o_rebuild(op, before, good, **ctx) == []
    doc = _open(good)
    doc.update_stream(5, (doc.xref_stream(5) or b"") + b"% sneaked in\n")
    tampered = doc.tobytes(garbage=0)
    assert vo.o_bytes(op, before, tampered, **ctx), "O-bytes must reject the appended comment"
    assert vo.o_rebuild(op, before, tampered, **ctx), "O-rebuild must verify the real cut too"


@pytest.mark.parametrize("rotate", [90, 180, 270])
def test_oracles_accept_correct_edits_on_a_rotated_page(rotate: int) -> None:
    base = vfb.sample_scene()
    scene = vfb.replace(base, pages=(vfb.replace(base.pages[0], rotate=rotate), base.pages[1]))
    rep = vo.calibrate(vfb, [(f"rot{rotate}", scene)], _ops, vo.ORACLES)
    assert not [f for f in rep.failures if "must-pass" in f], rep.failures[:5]


# ----------------------------------------------------------------------------- Astra round 2


def _two_path_doc(second_first_x: str = "1", streams: tuple[bytes, ...] | None = None) -> bytes:
    """A one-page document written with fitz; one content stream unless ``streams`` is given."""
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    texts = streams or (f"0 0 m 9 9 l S\n{second_first_x} 5 m 9 9 l S\n".encode(),)
    refs = []
    for body in texts:
        x = doc.get_new_xref()
        doc.update_object(x, "<< >>")
        doc.update_stream(x, body, compress=False, new=True)
        refs.append(f"{x} 0 R")
    doc.xref_set_key(doc.page_xref(0), "Contents", "[" + " ".join(refs) + "]" if len(refs) > 1 else refs[0])
    return doc.tobytes(garbage=0)


def test_prestate_keeps_pdf_value_types_not_only_text() -> None:
    def with_foo(value: str) -> bytes:
        doc = _open(vfb.build(vfb.sample_scene()))
        doc.xref_set_key(5, "Foo", value)
        return doc.tobytes(garbage=0)

    name_doc, string_doc = with_foo("1"), with_foo("(1)")  # same printed value, different type
    for fn in (vo.o_dict, vo.o_rebuild):
        assert fn("delete", name_doc, string_doc, fate="rollback", expected=name_doc), fn.__name__


def test_digest_sees_an_array_nested_length_and_ignores_a_string_typed_container_type() -> None:
    doc = _open(vfb.build(vfb.sample_scene()))
    doc.xref_set_key(9, "Arr", "[/Length 7]")
    first = commit_state.digest_table(doc)
    doc.xref_set_key(9, "Arr", "[/Length 8]")
    ws = commit_state.WriteSet(3, frozenset(), frozenset())
    assert commit_state.undeclared(first, commit_state.digest_table(doc), ws) == [9]
    doc.xref_set_key(9, "Type", "(/XRef)")
    assert 9 not in commit_state.digest_table(doc).containers
    doc.xref_set_key(9, "Type", "/XRef")  # a real name on a real stream is a container
    assert 9 in commit_state.digest_table(doc).containers
    doc.update_object(12, "<< /Type /XRef >>")  # a plain dictionary is not a stream
    assert 12 not in commit_state.digest_table(doc).containers


def test_o_pixel_does_not_wrap_a_negative_mask_index_for_an_off_page_selection() -> None:
    base = vfb.sample_scene()
    off = vfb.PathSpec("line", ((-60.0, 10.0), (-10.0, 20.0)), "S")
    scene = vfb.replace(base, pages=(vfb.replace(base.pages[0], items=(off, *base.pages[0].items)), base.pages[1]))
    op = vfb.Op("delete", 0, (0,))
    before = vfb.build(scene)
    _good, facts = vfb.expected(scene, op)
    wrong = vfb.expected(scene, vfb.Op("delete", 0, (0, 1)))[0]  # also deletes a visible line
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    assert vo.o_pixel(op, before, wrong, **ctx)


def test_o_bytes_carries_the_open_path_state_across_content_streams() -> None:
    before = _two_path_doc(streams=(b"0 0 m 9 9 l\n", b"1 1 m 2 2 l S\n"))
    after = _two_path_doc(streams=(b"0 0 m 9 9 l\n", b"\n"))
    ranges = {1: [(0, 13)]}
    envelopes = {1: [(0, 13, 0, 13, False)]}
    assert vo.o_bytes("delete", before, after, ranges=ranges, envelopes=envelopes)


def test_o_rebuild_rejects_an_undeclared_new_object() -> None:
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, (1, 2))
    before = vfb.build(scene)
    good, facts = vfb.expected(scene, op)
    doc = _open(good)
    n = doc.get_new_xref()
    doc.update_object(n, "<< /Junk 123 >>")
    junk = doc.tobytes(garbage=0)
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    ctx["expected"] = good
    assert vo.o_rebuild(op, before, junk, **ctx)


def test_o_struct_compares_survivors_exactly_for_a_delete() -> None:
    """Design plan section 9 (Tolerances): 'Deletes stay exact'."""
    before = _two_path_doc("1")
    after = _two_path_doc("1.000001")
    assert vo.o_struct("delete", before, after, selected_drawings=())


# ----------------------------------------------------------------------------- Astra round 3


def _good_case() -> tuple[vfb.Scene, vfb.Op, bytes, bytes, dict]:
    scene = vfb.sample_scene()
    op = vfb.Op("delete", 0, (1, 2))
    good, facts = vfb.expected(scene, op)
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    ctx["expected"] = good
    return scene, op, vfb.build(scene), good, ctx


@pytest.mark.parametrize(
    ("old", "new"),
    [("/A#2FB 1", "/A#2FB 2"), ("/Bin <410042>", "/Bin <410043>")],
)
def test_escaped_names_and_hex_strings_are_compared_byte_exact(old: str, new: str) -> None:
    _scene, op, before, good, ctx = _good_case()
    docs = []
    for text in (old, new):
        d = _open(good)
        px = d.page_xref(0)
        d.update_object(px, d.xref_object(px, compressed=False).rstrip()[:-2] + f" {text} >>")  # top-level key
        docs.append(d.tobytes(garbage=0))
    ctx["expected"] = docs[0]
    base_ctx = dict(ctx)
    assert vo.rule_b(op, docs[0], docs[1], **base_ctx), "rule B"
    assert vo.o_rebuild(op, before, docs[1], **base_ctx), "O-rebuild"


def test_a_range_for_a_nonexistent_stream_index_is_rejected() -> None:
    _scene, op, before, good, ctx = _good_case()
    ctx["ranges"] = {**ctx["ranges"], 999: [(0, 1)]}
    ctx["envelopes"] = {**ctx["envelopes"], 999: [(0, 1, 0, 1, False)]}
    assert vo.o_bytes(op, before, good, **ctx)
    assert vo.o_rebuild(op, before, good, **ctx)


# ----------------------------------------------------------------------------- merged fill+stroke pair (Opus round)

from test_scripts import vector_oracle_extra as voe  # noqa: E402

_MERGED_SELECTIONS = [(0,), (1,), (2,), (3,), (4,), (1, 2), (2, 3)]


def _merged_case(sel: tuple[int, ...]) -> tuple[vfb.Scene, vfb.Op, bytes, bytes, dict]:
    scene = vfb.Scene((voe.merged_pair_page(),))
    op = vfb.Op("delete", 0, sel)
    good, facts = vfb.expected(scene, op)
    ctx = {k: v for k, v in facts.context.items() if k != "scenario_op"}
    ctx["expected"] = good
    return scene, op, vfb.build(scene), good, ctx


@pytest.mark.parametrize("sel", _MERGED_SELECTIONS)
def test_every_oracle_accepts_a_correct_delete_on_a_page_with_a_merged_fill_and_stroke(sel: tuple[int, ...]) -> None:
    _scene, op, before, good, ctx = _merged_case(sel)
    for name, fn in vo.ORACLES.items():
        assert fn(op, before, good, **ctx) == [], (name, sel)


def test_the_selection_maps_paths_to_mupdf_drawings_and_halves_when_a_fill_and_stroke_merge() -> None:
    page = voe.merged_pair_page()
    assert vfb.drawing_indices(page, (0,)) == (0,)
    assert vfb.drawing_indices(page, (1,)) == (1,)
    assert vfb.drawing_indices(page, (2,)) == (1,)  # the stroke half of the merged drawing
    assert vfb.drawing_indices(page, (1, 2)) == (1,)
    assert vfb.drawing_indices(page, (3,)) == (2,)
    assert vfb.drawing_indices(page, (4,)) == (3,)
    assert vfb.selected_halves(page, (1,)) == ((1, "f"),)
    assert vfb.selected_halves(page, (2,)) == ((1, "s"),)
    assert vfb.selected_halves(page, (3,)) == ((2, "f"), (2, "s"))


@pytest.mark.parametrize("sel", _MERGED_SELECTIONS)
def test_the_builder_region_equals_the_oracle_region_when_a_fill_and_stroke_merge(sel: tuple[int, ...]) -> None:
    scene, _op, before, _good, _ctx = _merged_case(sel)
    page = scene.pages[0]
    shape = vo._render(_open(before)[0]).shape
    mine = vfb.region_mask(shape, vfb.region_rects(page, vfb.path_ordinals(page, sel)))
    theirs = vo.region_mask(shape, vo.changed_region_rects(_open(before)[0], vfb.drawing_indices(page, sel)))
    assert (mine == theirs).all(), sel


@pytest.mark.parametrize(
    ("sel", "wrong"),
    [((2,), (3,)), ((3,), (2,)), ((1, 2), (3,)), ((1, 2), (1,)), ((2,), (1, 2)), ((1,), (2,)), ((2,), (1,))],
)
def test_o_struct_kills_the_neighbour_or_wider_or_narrower_delete_on_a_merged_pair_page(sel: tuple[int, ...], wrong: tuple[int, ...]) -> None:
    scene, op, before, _good, ctx = _merged_case(sel)
    bad = vfb.expected(scene, vfb.Op("delete", 0, wrong))[0]
    assert vo.o_struct(op, before, bad, **ctx), (sel, wrong)
    assert vo.o_struct(op, before, before, **ctx), "nothing deleted"


@pytest.mark.parametrize("sel", [(2,), (3,), (1, 2)])
def test_o_pixel_kills_a_neighbour_delete_on_a_merged_pair_page(sel: tuple[int, ...]) -> None:
    scene, op, before, _good, ctx = _merged_case(sel)
    for other in ((0,), (4,), (3,) if sel != (3,) else (2,)):
        bad = vfb.expected(scene, vfb.Op("delete", 0, other))[0]
        assert vo.o_pixel(op, before, bad, **ctx), (sel, other)
