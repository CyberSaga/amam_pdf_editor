"""Pure tests for ``test_scripts.true_text_acceptance_helpers`` (slice I0b, stage S1).

The helpers were moved out of the real-corpus acceptance module (``acc``), with one deliberate
change (H3): page-geometry conversions go through the computed ``PageVisualFrame``
(``frame.base`` / ``frame.quarter_turn``), not the PyMuPDF page matrices, which drop the CropBox
origin and ``/UserUnit`` on a rotated page.  The red tests call ``acc``'s names (they survive as
re-exports), so they fail on behaviour at the old code, not on a missing module.  Guards
(green before and after the move) are labelled as such.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import types

import fitz
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit import verify  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from test_scripts import stream_storage_fixtures as ssf  # noqa: E402
from test_scripts import test_text_commit_real_corpus_acceptance as acc  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402
from test_scripts import type0_fixture_builder as tb  # noqa: E402
from test_scripts.true_text_corpus import CorpusCase  # noqa: E402

_PAGE_MATRICES = {"rotation_matrix", "transformation_matrix", "derotation_matrix"}

#: every name moved into the helpers; acc re-exports each one under the same name
#: (``_decode_show`` is the one rename: the helper is the public ``decode_show``).
_MOVED = (
    "_TEXT_STATE_FIELDS",
    "_shows",
    "_trace_for",
    "_measurement_copy",
    "_prepare",
    "_object_entry",
    "_object_snapshot",
    "_SEMANTIC_MAX_DEPTH",
    "_semantic_value",
    "_objects_semantically_equal",
    "_assert_only_target_streams_changed",
    "_pixmap_array",
    "_assert_reopened_renders_match_live",
    "_assert_pixels_changed_only_inside_masks",
    "_assert_tj_compensation_is_last",
    "_assert_source_font_reused",
    "RENDER_ZOOM",
    "halo_mask",
    "visual_frame",
)


def _odd_page_fixture() -> tb.Type0Fixture:
    """identity_h on a ``/UserUnit 2`` page with an offset CropBox and ``/Rotate 90``.

    The shape of ``test_evidence_rederive.py::test_region_dict_frame_quarter_turn``: on this page
    ``page.transformation_matrix`` and ``page.rotation_matrix`` both drop the CropBox origin and
    the user unit, so only the computed frame locates the text.
    """
    fx = tb.build_identity_h_fixture(rotate=0)
    page = fx.doc[0]
    fx.doc.xref_set_key(page.xref, "UserUnit", "2")
    page.set_cropbox(fitz.Rect(20, 30, 575, 800))
    page.set_rotation(90)
    return fx


def _case_for(fx: tb.Type0Fixture, replacement: str) -> CorpusCase:
    return CorpusCase(
        page_index=0,
        show_seq=0,
        original=fx.text,
        replacement=replacement,
        font_resource=fx.resource_name,
        basefont="fixture",
    )


def _tj_payload(written: bytes, kern: float) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        replacement=types.SimpleNamespace(replacement_bytes=written), kern_adjustment=kern
    )


# --- red tests (fail on the pre-move acc code) -------------------------------------------------


def test_trace_for_locates_through_the_frame_on_a_user_unit_page() -> None:
    fx = _odd_page_fixture()
    show = acc._shows(fx.doc, 0)[0]
    frame = helpers.visual_frame(fx.doc[0])
    with acc._measurement_copy(fx.doc) as measured:
        trace = acc._trace_for(measured[0], show, fx.text)
    expected = fitz.Point(show.origin_user) * frame.base
    assert abs(fitz.Point(trace["chars"][0][2]) - expected) < 0.02
    # the page matrix the old code used lands elsewhere on this page: the frame is what matters
    assert abs(expected - fitz.Point(show.origin_user) * fx.doc[0].transformation_matrix) > 1.0


def test_prepare_target_bbox_is_the_frame_box_on_a_user_unit_page(monkeypatch) -> None:
    fx = _odd_page_fixture()
    doc = fx.doc
    frame = helpers.visual_frame(doc[0])
    with acc._measurement_copy(doc) as measured:
        chars = [char for trace in measured[0].get_texttrace() for char in trace["chars"]]
    box = fitz.Rect(chars[0][3])
    for char in chars[1:]:
        box |= fitz.Rect(char[3])
    want_bbox = tuple(box * frame.quarter_turn)
    want_origin = tuple(fitz.Point(chars[0][2]) * frame.quarter_turn)

    seen: dict = {}
    real_prepare = TieredCommitEngine.prepare

    def spy(self, page, **kwargs):
        seen.update(kwargs)
        return real_prepare(self, page, **kwargs)

    monkeypatch.setattr(TieredCommitEngine, "prepare", spy)
    engine = TieredCommitEngine(doc, max_tier=1)
    acc._prepare(engine, doc, _case_for(fx, fx.text))
    assert seen, "the engine's prepare was never called"
    assert seen["target_bbox"] == pytest.approx(want_bbox, abs=1e-6)
    assert seen["expected_origin"] == pytest.approx(want_origin, abs=1e-6)
    assert fitz.Rect(seen["target_bbox"]).intersects(doc[0].rect), "the box lies off the visual page"
    wrong = box * doc[0].rotation_matrix
    assert abs(wrong.x0 - want_bbox[0]) > 1.0, "this page must separate the frame from the page matrix"


def test_decode_show_reads_a_simple_font_show() -> None:
    doc = ssf.open_case("a")
    page = doc[0]
    show = acc._shows(doc, 0)[0]
    registry = DocumentFontRegistry(doc)
    assert acc._decode_show(registry, page, show, font_kind="simple") == ssf.TARGET


def test_tj_compensation_reads_a_literal_string_item() -> None:
    acc._assert_tj_compensation_is_last(_tj_payload(rb"[(a\)b) 12] TJ", 12.0), 12.0)


def test_helpers_never_import_pytest_and_use_no_page_matrices() -> None:
    toolkit = "Py" + "Side6"  # spelled in two halves: the suite runner classifies a file naming it as a Qt file
    for path in (
        ROOT / "test_scripts" / "true_text_acceptance_helpers.py",
        ROOT / "test_scripts" / "frontier_twins.py",
        ROOT / "test_scripts" / "test_text_commit_real_corpus_acceptance.py",
        ROOT / "test_scripts" / "test_text_commit_ui_real_corpus.py",
        ROOT / "test_scripts" / "test_text_commit_source_show_commit.py",
        ROOT / "test_scripts" / "test_text_commit_source_run.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not used & _PAGE_MATRICES, (path.name, used & _PAGE_MATRICES)
    imported: set[str] = set()
    for name in ("true_text_acceptance_helpers.py", "frontier_twins.py"):  # both stay pytest-free and Qt-free
        helper_tree = ast.parse((ROOT / "test_scripts" / name).read_text(encoding="utf-8"))
        for node in ast.walk(helper_tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
    assert "pytest" not in imported
    assert toolkit not in imported
    assert not imported & {"view", "controller"}


def test_acc_reexports_the_helpers() -> None:
    for name in _MOVED:
        assert getattr(acc, name) is getattr(helpers, name), name
    assert acc._decode_show is helpers.decode_show
    assert acc.FixtureUnavailable is helpers.FixtureUnavailable


# --- guards and new-helper behaviour (written with the helpers; not red-first) -----------------


def test_tj_compensation_rejects_a_kern_that_is_not_last() -> None:
    """Guard (green before and after): the old regex and the new lexer both refuse it."""
    with pytest.raises(AssertionError):
        acc._assert_tj_compensation_is_last(_tj_payload(b"[<41> 12 <42>] TJ", 12.0), 12.0)


def test_tj_compensation_accepts_the_hex_payload_and_checks_the_number() -> None:
    acc._assert_tj_compensation_is_last(_tj_payload(b"[<0041> -12.5] TJ", -12.5), -12.5)
    with pytest.raises(AssertionError):
        acc._assert_tj_compensation_is_last(_tj_payload(b"[<0041> -12.5] TJ", -12.5), -12.0)
    with pytest.raises(AssertionError):  # the written number is not the product's own kern
        acc._assert_tj_compensation_is_last(_tj_payload(b"[<0041> -12.5] TJ", -12.0), -12.0)


@pytest.mark.parametrize(
    "written",
    [
        b"[<41> 12] Tj",  # wrong operator
        b"[<41> 12] TJ 1 0 0 1 0 0 cm",  # trailing operator
        b"[<41> 12 % c\n] TJ",  # a comment fails
        b"[<41>] TJ",  # no number
        b"[12 <41>] TJ",  # number first
    ],
)
def test_tj_compensation_rejects_other_shapes(written: bytes) -> None:
    with pytest.raises(AssertionError):
        acc._assert_tj_compensation_is_last(_tj_payload(written, 12.0), 12.0)


def test_tj_compensation_ignores_whitespace_between_tokens() -> None:
    acc._assert_tj_compensation_is_last(_tj_payload(b"[ <41>\n12\t] TJ", 12.0), 12.0)


def test_decode_show_default_stays_fail_closed_to_type0() -> None:
    doc = ssf.open_case("a")
    show = acc._shows(doc, 0)[0]
    with pytest.raises(AssertionError):
        helpers.decode_show(DocumentFontRegistry(doc), doc[0], show)
    with pytest.raises(AssertionError):
        helpers.decode_show(DocumentFontRegistry(doc), doc[0], show, font_kind="type3")


def test_decode_show_simple_branch_refuses_a_type0_font() -> None:
    fx = tb.build_identity_h_fixture()
    show = acc._shows(fx.doc, 0)[0]
    with pytest.raises(AssertionError):
        helpers.decode_show(DocumentFontRegistry(fx.doc), fx.doc[0], show, font_kind="simple")
    assert helpers.decode_show(DocumentFontRegistry(fx.doc), fx.doc[0], show) == fx.text


def test_can_encode_simple_is_the_products_encode_rule() -> None:
    doc = ssf.open_case("a")
    show = acc._shows(doc, 0)[0]
    capability = DocumentFontRegistry(doc).capability(doc[0], show.font_resource)
    assert helpers.can_encode_simple(capability, ssf.REPLACEMENT) is True
    assert helpers.can_encode_simple(capability, "café") is False


def test_unprovable_page_geometry_is_a_failure_not_a_fallback(monkeypatch) -> None:
    doc = ssf.open_case("a")
    monkeypatch.setattr(helpers, "page_visual_frame_or_none", lambda page: None)
    with pytest.raises(AssertionError, match="page geometry is unsupported"):
        helpers.visual_frame(doc[0])
    show = acc._shows(doc, 0)[0]
    with pytest.raises(AssertionError, match="page geometry is unsupported"):
        helpers._trace_for(doc[0], show, ssf.TARGET)


def test_fixture_raises_fixture_unavailable_and_acc_converts_it_to_a_skip() -> None:
    spec = types.SimpleNamespace(relative_path="test_files/__no_such_fixture__.pdf", slug="none", sha256="0")
    with pytest.raises(helpers.FixtureUnavailable):
        helpers._fixture(spec)
    with pytest.raises(pytest.skip.Exception):
        acc._fixture(spec)


def test_source_font_reuse_applies_the_type0_asserts_only_to_type0_cases() -> None:
    fx = tb.build_identity_h_fixture()
    other = tb.build_identity_h_fixture()
    show = acc._shows(fx.doc, 0)[0]
    other_show = acc._shows(other.doc, 0)[0]
    case = _case_for(fx, fx.text)
    case = CorpusCase(**{**case.__dict__, "basefont": DocumentFontRegistry(fx.doc).capability(
        fx.doc[0], show.font_resource
    ).basefont})
    acc._assert_source_font_reused(fx.doc, other.doc, case, show, other_show)
    simple_case = CorpusCase(**{**case.__dict__, "font_kind": "simple"})
    # a simple-kind case decodes through the simple branch, which refuses this Type0 font
    with pytest.raises(AssertionError):
        acc._assert_source_font_reused(fx.doc, other.doc, simple_case, show, other_show)


def test_source_font_reuse_accepts_a_simple_font_case() -> None:
    """The positive simple leg: an unembedded base-14 Type1 font is reused and decodes latin-1.

    Pins the ``font_kind == "type0"`` gate: with the gate removed the Type0 asserts run on this
    Type1 font and the call fails.
    """
    source = ssf.open_case("a")
    candidate = fitz.open("pdf", source.tobytes())
    show = acc._shows(source, 0)[0]
    capability = DocumentFontRegistry(source).capability(source[0], show.font_resource)
    case = CorpusCase(
        page_index=0,
        show_seq=0,
        original=ssf.TARGET,
        replacement=ssf.TARGET,
        font_resource=show.font_resource,
        basefont=capability.basefont,
        font_kind="simple",
    )
    acc._assert_source_font_reused(source, candidate, case, show, acc._shows(candidate, 0)[0])


def test_simple_branch_refuses_an_unembedded_font_that_is_not_base14() -> None:
    """The narrowed rule: an unembedded non-base-14 simple font would take a host ``system`` face
    (machine-dependent), so ``decode_show`` refuses it whatever the host resolves it to."""
    doc = ssf.open_case("a")
    show = acc._shows(doc, 0)[0]
    font_xref = DocumentFontRegistry(doc).capability(doc[0], show.font_resource).font_xref
    doc.xref_set_key(font_xref, "BaseFont", "/NoSuchFontXyzQ")
    registry = DocumentFontRegistry(doc)  # a fresh registry: the first one cached the capability
    capability = registry.capability(doc[0], show.font_resource)
    assert capability.embedded is False and capability.face_source != "base14", capability.face_source
    with pytest.raises(AssertionError):
        helpers.decode_show(registry, doc[0], show, font_kind="simple")


# --- raster slack of the pixel-mask checker -----------------------------------------------------


def _mask_case(x1_pt: float, change_col: int) -> None:
    """A 40 x 40 pt page at RENDER_ZOOM: one change inside the mask, one at ``change_col``."""
    zoom = helpers.RENDER_ZOOM
    mask = fitz.Rect(10, 10, x1_pt, 20)
    size = int(40 * zoom)
    before = np.zeros((size, size, 3), dtype="uint8")
    after = before.copy()
    row = int(15 * zoom)  # a row inside the mask's pixel rows
    after[row, int(15 * zoom)] = 255  # inside the mask
    after[row, change_col] = 255
    helpers._assert_pixels_changed_only_inside_masks("synthetic", 0, before, after, [mask])


@pytest.mark.parametrize(
    ("x1_pt", "last_ok_col"),
    [(20.0, 40), (20.05, 41)],  # mask edge on a pixel boundary / 0.1 px inside the next pixel
)
def test_pixel_mask_allows_one_pixel_of_raster_slack_and_no_more(x1_pt: float, last_ok_col: int) -> None:
    _mask_case(x1_pt, last_ok_col)  # touching the mask's pixel rect: accepted
    with pytest.raises(AssertionError):
        _mask_case(x1_pt, last_ok_col + 1)  # one whole pixel further: rejected


def test_pixel_mask_still_requires_a_change_inside_the_mask() -> None:
    zoom = helpers.RENDER_ZOOM
    before = np.zeros((int(40 * zoom), int(40 * zoom), 3), dtype="uint8")
    with pytest.raises(AssertionError):
        helpers._assert_pixels_changed_only_inside_masks(
            "synthetic", 0, before, before.copy(), [fitz.Rect(10, 10, 20, 20)]
        )


def test_halo_mask_pads_the_union_of_the_two_boxes_by_the_product_halo() -> None:
    fx = _odd_page_fixture()
    frame = helpers.visual_frame(fx.doc[0])
    before, after = (10.0, 20.0, 50.0, 30.0), (12.0, 20.0, 70.0, 31.0)
    union = (fitz.Rect(before) | fitz.Rect(after)) * frame.quarter_turn
    pad = verify._HALO_MARGIN_PT
    assert tuple(helpers.halo_mask(before, after, frame)) == pytest.approx(
        (union.x0 - pad, union.y0 - pad, union.x1 + pad, union.y1 + pad)
    )


# --- S3b: byte-range, wrapper and count helpers (red-first against the stubs; plan section 3) -----------------


def _two_change_streams() -> tuple[bytes, bytes, list[tuple[int, int, int]]]:
    """A 42-byte stream and its edit: ``bbbb`` -> ``XXXXXX`` at 10 and ``ddd`` -> ``YY`` at 29 (before coordinates).

    The second change starts inside the first change's shifted suffix: its ``end_new`` is
    ``29 + 2 (shift after change 1) + 2 (new length)``, so a single range cannot describe both."""
    before = b"A" * 10 + b"bbbb" + b"C" * 15 + b"ddd" + b"E" * 10
    after = b"A" * 10 + b"XXXXXX" + b"C" * 15 + b"YY" + b"E" * 10
    return before, after, [(10, 14, 16), (29, 32, 33)]


def test_stream_range_applies_the_shift_rule_across_two_changes() -> None:
    before, after, ranges = _two_change_streams()
    assert len(before) == 42 and len(after) == 43
    check = helpers.check_target_stream_changed_only_within
    assert check(before, after, ranges) is None
    assert check(before, after, list(reversed(ranges))) is None  # sorted by start
    # the changed middle need not differ at all
    assert check(before, before[:10] + b"bbbb" + before[14:], [(10, 14, 14)]) is None
    mutated = bytearray(after)
    mutated[3] ^= 0xFF  # prefix
    assert check(before, bytes(mutated), ranges) == "stream_range: prefix_changed: first difference at byte 3"
    mutated = bytearray(after)
    mutated[21] ^= 0xFF  # gap 1: after offset 21 = before offset 19
    assert check(before, bytes(mutated), ranges) == "stream_range: gap_changed: gap 1: first difference at byte 19"
    mutated = bytearray(after)
    mutated[35] ^= 0xFF  # suffix: after offset 35 = before offset 34
    assert check(before, bytes(mutated), ranges) == "stream_range: suffix_changed: first difference at byte 34"
    detail = check(before, after + b"!", ranges)  # every leg is evaluated
    assert detail is not None and detail.startswith("stream_range: ")
    assert "length: 44 bytes after, expected 43" in detail and "suffix_changed:" in detail
    # a change outside the declared ranges, with the ranges describing a different edit
    detail = check(before, after, [(10, 14, 16)])
    assert detail is not None and "suffix_changed:" in detail and "length:" in detail


def test_stream_range_rejects_bad_ranges() -> None:
    check = helpers.check_target_stream_changed_only_within
    before = b"0123456789"
    for ranges in (
        [],  # nothing declared
        [(4, 3, 3)],  # start after end_old
        [(2, 11, 11)],  # end_old beyond the stream
        [(-1, 2, 2)],  # negative start
        [(2, 6, 6), (4, 8, 8)],  # overlapping
        [(5, 6, 4)],  # end_new before the shifted start
    ):
        with pytest.raises(ValueError):
            check(before, before, ranges)
    assert check(before, before, [(2, 4, 4), (4, 6, 6)]) is None  # adjacent ranges are allowed


_OC = b"/OC /P0 BDC BT /F1 12 Tf 72 700 Td (abc) Tj ET"


def _replay(*streams: bytes):
    pairs = [(index + 1, data) for index, data in enumerate(streams)]
    return dict(pairs), helpers.replay_page_streams(pairs)


def test_wrapper_check_follows_an_emc_in_another_stream() -> None:
    """The EMC sits in the second content stream: its offsets do not shift with an edit in the first."""
    edited = _OC.replace(b"(abc)", b"(abcde)")
    padding = b" " * 64  # the EMC sits past the edited show's op_end, so a shift applied to stream B would show
    before, rb = _replay(_OC, padding + b"EMC")
    assert rb.mc_wrappers[0].close_stream_xref == 2 and rb.mc_wrappers[0].close_op_start == 64
    assert rb.mc_wrappers[0].close_op_start >= rb.shows[0].op_end
    after, ra = _replay(edited, padding + b"EMC")
    check = helpers.check_wrapper_bytes_unchanged
    assert check(before, after, rb, ra, 0, 1, 2) is None
    moved, rm = _replay(edited, padding + b" EMC")
    assert check(before, moved, rb, rm, 0, 1, 2) == "wrapper: close_moved: 1 of 1 wrapper(s)"
    removed, rr = _replay(edited, b"")
    assert check(before, removed, rb, rr, 0, 1, 2) == "wrapper: close: 1 of 1 wrapper(s)"
    assert check(before, after, rb, ra, 0, 1, 3) == "wrapper: show_span: moved"
    other, ro = _replay(edited, padding + b"EMX")  # not an EMC: the replay leaves the wrapper open
    assert check(before, other, rb, ro, 0, 1, 2) == "wrapper: close: 1 of 1 wrapper(s)"
    # the replay says the EMC is at offset 0 of stream 2, but the bytes there are something else
    assert check(before, {1: edited, 2: padding + b"XYZ"}, rb, ra, 0, 1, 2) == (
        "wrapper: close_changed: 1 of 1 wrapper(s)"
    )
    with pytest.raises(ValueError):
        check(before, after, rb, ra, 0, 2, 2)  # the edited stream is not the show's stream
    with pytest.raises(ValueError):
        check(before, after, rb, ra, 5, 1, 2)  # no such show before


def test_wrapper_check_shifts_an_emc_in_the_edited_stream_after_the_edit() -> None:
    """The EMC is in the EDITED stream, past the edit: it moves by exactly ``delta`` and no more or less."""
    edited = _OC.replace(b"(abc)", b"(abcde)")
    before, rb = _replay(_OC + b" EMC")
    assert rb.mc_wrappers[0].close_stream_xref == 1 and rb.mc_wrappers[0].close_op_start > rb.shows[0].op_end
    after, ra = _replay(edited + b" EMC")
    check = helpers.check_wrapper_bytes_unchanged
    assert check(before, after, rb, ra, 0, 1, 2) is None
    assert check(before, after, rb, ra, 0, 1, 1) == "wrapper: show_span: moved"  # the delta is self-checked
    late, rl = _replay(edited + b"  EMC")  # one byte too late
    assert check(before, late, rb, rl, 0, 1, 2) == "wrapper: close_moved: 1 of 1 wrapper(s)"


def test_wrapper_check_reads_dict_and_bmc_operands() -> None:
    nested = b"/Span <</MCID 0>> BDC /P BMC BT /F1 12 Tf 72 700 Td (abc) Tj ET EMC EMC"
    before, rb = _replay(nested)
    assert len(rb.wrappers_for(rb.shows[0])) == 2
    check = helpers.check_wrapper_bytes_unchanged
    assert check(before, before, rb, rb, 0, 1, 0) is None
    changed, rc = _replay(nested.replace(b"/MCID 0", b"/MCID 1"))
    assert check(before, changed, rb, rc, 0, 1, 0) == "wrapper: open_changed: 1 of 2 wrapper(s)"
    junk, rj = _replay(b"42 " + _OC + b" EMC")
    assert rj.mc_wrappers[0].props_kind == "unparsed"
    assert check(junk, junk, rj, rj, 0, 1, 0) == "wrapper: open_unparsed: 1 of 1 wrapper(s)"
    bare, rbare = _replay(b"BT /F1 12 Tf 72 700 Td (abc) Tj ET")
    assert check(bare, bare, rbare, rbare, 0, 1, 0) is None  # no wrapper: nothing to compare


def test_counts_are_per_stream() -> None:
    first, second = b"BT /F1 12 Tf 72 700 Td (a) Tj ET", b"q Q"
    check = helpers.check_show_and_operator_counts_equal
    assert check([(1, first), (2, second)], [(1, first), (2, second)]) is None
    assert check([(1, first), (2, second)], [(1, first), (2, second + b" Q")]) == (
        "counts: operators: stream 1: 2 before, 3 after"
    )
    more = first.replace(b"ET", b"(b) Tj ET")
    detail = check([(1, first), (2, second)], [(1, more), (2, second)])
    assert detail == "counts: shows: stream 0: 1 before, 2 after; operators: stream 0: 5 before, 6 after"
    assert check([(1, first), (2, second)], [(1, first)]) == "counts: streams: 2 before, 1 after"
    assert check([(1, first)], [(7, first)]) == "counts: streams: 1 before, 1 after"
