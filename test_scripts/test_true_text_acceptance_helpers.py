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
    assert check(before, after, list(reversed(ranges))) is None  # sorted by (start, end_old)
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


def test_stream_range_orders_a_tie_at_start_like_splice_stream() -> None:
    """A zero-width insertion at ``s`` precedes a change that starts at ``s`` (splice_stream's order), whatever the input order."""
    check = helpers.check_target_stream_changed_only_within
    before, after = b"(AB) Tj", b"X (AB) Tj"
    insertion, show = (0, 0, 2), (0, 4, 6)  # "X " inserted, then "(AB)" replaced by itself in the shifted suffix
    assert check(before, after, [insertion, show]) is None  # control: the input already in splice order (green before the fix)
    assert check(before, after, [show, insertion]) is None  # red before the fix: ValueError("overlapping ranges")


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


# --- S6 (round-4 lane): the wrapper helper's keyword form ``ranges=`` (every change of an experiment row) ----------------


def _splice(data: bytes, pieces: list[tuple[int, int, bytes]]) -> bytes:
    """``data`` with each ``(start, end_old, new)`` replaced; offsets in ``data`` coordinates, pieces in stream order."""
    out, cursor = bytearray(), 0
    for start, end_old, new in pieces:
        out += data[cursor:start] + new
        cursor = end_old
    return bytes(out + data[cursor:])


def _oc_closed():
    """The base fixture ``_OC + b" EMC"`` and its replay; its offsets are premises read from the replay, not assumed."""
    streams, replay = _replay(_OC + b" EMC")
    show, wrapper = replay.shows[0], replay.mc_wrappers[0]
    assert helpers._mc_operand_start(streams[1], wrapper.open_op_end) == 0  # the BDC's operands open the stream
    assert (wrapper.open_op_end, wrapper.close_stream_xref, wrapper.close_op_start) == (11, 1, 47)
    assert (show.op_start, show.string_end, show.op_end, len(streams[1])) == (35, 40, 43, 50)
    return streams, replay


def _after_offsets(replay) -> tuple[int, int, int]:
    """``(show op_start, show op_end, EMC start)`` of the one show and the one wrapper of an after replay."""
    show, wrapper = replay.shows[0], replay.mc_wrappers[0]
    return show.op_start, show.op_end, wrapper.close_op_start


def test_wrapper_ranges_judge_the_tc_shape() -> None:
    """U1: an insertion at the show's start, the string replaced (+2 bytes), an insertion at the show's end (the real
    CANARY_TC shape).  An insertion at a token START moves it; one exactly at a token END (``op_end``) lands after the token
    and does not; each offset takes the cumulative shift of the last range that precedes it."""
    before, rb = _oc_closed()
    check = helpers.check_wrapper_bytes_unchanged
    pieces = [(35, 35, b"0.25 Tc "), (35, 40, b"(abcde)"), (43, 43, b" 0 Tc")]
    after, ra = _replay(_splice(before[1], pieces))
    assert _after_offsets(ra) == (43, 53, 62)  # premise: the show is [43, 53) after, the EMC at 62
    ranges = [(35, 35, 43), (35, 40, 50), (43, 43, 58)]
    assert check(before, after, rb, ra, 0, ranges={1: ranges}) is None
    assert check(before, after, rb, ra, 0, ranges={1: list(reversed(ranges))}) is None  # sorted by (start, end_old)
    two, rt = _replay(_splice(before[1], [pieces[0], pieces[2]]))  # the two insertions only
    assert check(before, two, rb, rt, 0, ranges={1: [(35, 35, 43), (43, 43, 56)]}) is None
    late, rl = _replay(_splice(before[1], [*pieces, (47, 47, b" ")]))  # one undeclared space before the EMC
    assert check(before, late, rb, rl, 0, ranges={1: ranges}) == "wrapper: close_moved: 1 of 1 wrapper(s)"


def test_wrapper_ranges_move_an_emc_only_by_the_changes_before_it() -> None:
    """U2: a restore inserted AFTER the closing EMC is not part of the EMC's shift (the EMC moves by the first insertion only)."""
    before, rb = _oc_closed()
    after, ra = _replay(_splice(before[1], [(35, 35, b"0.25 Tc "), (50, 50, b" 0 g")]))
    assert _after_offsets(ra) == (43, 51, 55)
    assert helpers.check_wrapper_bytes_unchanged(before, after, rb, ra, 0, ranges={1: [(35, 35, 43), (50, 50, 62)]}) is None


def test_wrapper_ranges_shift_each_stream_by_its_own_changes() -> None:
    """U3: the show and its BDC in stream 1, the EMC in stream 2; only a stream's own ranges move its offsets."""
    check = helpers.check_wrapper_bytes_unchanged
    edited, padding = _OC.replace(b"(abc)", b"(abcde)"), b" " * 64
    before, rb = _replay(_OC, padding + b"EMC")
    assert (rb.mc_wrappers[0].close_stream_xref, rb.mc_wrappers[0].close_op_start) == (2, 64)
    assert (rb.shows[0].op_start, rb.shows[0].string_end) == (35, 40)
    after, ra = _replay(edited, padding + b"EMC")  # (i) the edit in stream 1 does not move stream 2's EMC
    assert check(before, after, rb, ra, 0, ranges={1: [(35, 40, 42)]}) is None
    both, rboth = _replay(edited, b" " + padding + b"EMC")  # (ii) stream 2 gains one leading space: its EMC moves to 65
    assert rboth.mc_wrappers[0].close_op_start == 65
    assert check(before, both, rb, rboth, 0, ranges={1: [(35, 40, 42)], 2: [(0, 0, 1)]}) is None
    assert check(before, both, rb, rboth, 0, ranges={1: [(35, 40, 42)]}) == "wrapper: close_moved: 1 of 1 wrapper(s)"
    closed, rc = _replay(_OC + b" EMC", b"q Q")  # (iii) the wrapper closes in stream 1; only stream 2 changes
    other, ro = _replay(_OC + b" EMC", b"q Q q Q")
    assert check(closed, other, rc, ro, 0, ranges={2: [(0, 0, 4)]}) is None


def test_wrapper_ranges_insertion_at_the_emc_start_moves_the_emc() -> None:
    """U4: four bytes inserted exactly where the EMC starts land before it; the same bytes after the EMC leave it in place."""
    before, rb = _oc_closed()
    check = helpers.check_wrapper_bytes_unchanged
    after, ra = _replay(_splice(before[1], [(47, 47, b"0 g ")]))
    assert _after_offsets(ra) == (35, 43, 51)
    assert check(before, after, rb, ra, 0, ranges={1: [(47, 47, 51)]}) is None
    wrong, rw = _replay(before[1] + b" 0 g")
    assert _after_offsets(rw) == (35, 43, 47)
    assert check(before, wrong, rb, rw, 0, ranges={1: [(47, 47, 51)]}) == "wrapper: close_moved: 1 of 1 wrapper(s)"
    assert check(before, before, rb, rb, 0, ranges={1: [(47, 50, 50)]}) is None  # an identity range over the EMC itself


def test_wrapper_ranges_insertions_at_the_bdc() -> None:
    """U5: an insertion right after the BDC token leaves ``open_op_end`` (a token end); one at the operands' start moves both."""
    before, rb = _oc_closed()
    check = helpers.check_wrapper_bytes_unchanged
    after, ra = _replay(_splice(before[1], [(11, 11, b" 0 g")]))
    assert ra.mc_wrappers[0].open_op_end == 11 and _after_offsets(ra) == (39, 47, 51)
    assert check(before, after, rb, ra, 0, ranges={1: [(11, 11, 15)]}) is None
    front, rf = _replay(_splice(before[1], [(0, 0, b"q Q ")]))
    assert rf.mc_wrappers[0].open_op_end == 15 and helpers._mc_operand_start(front[1], 15) == 4
    assert check(before, front, rb, rf, 0, ranges={1: [(0, 0, 4)]}) is None


def test_wrapper_ranges_fail_closed_on_a_range_across_the_show() -> None:
    """U6: a range that starts before an edge of the show and ends after it says nothing about where that edge went."""
    before, rb = _oc_closed()
    check = helpers.check_wrapper_bytes_unchanged
    for straddling in ((32, 40, 40), (41, 46, 46), (0, 50, 50)):  # across op_start, across op_end, across both
        assert check(before, before, rb, rb, 0, ranges={1: [straddling]}) == "wrapper: show_span: straddled", straddling
    transplant, rt = _replay(_splice(before[1], [(35, 43, b"(abcde) Tj")]))  # the whole operator, edge to edge
    assert check(before, transplant, rb, rt, 0, ranges={1: [(35, 43, 45)]}) is None
    assert check(before, before, rb, rb, 0, ranges={1: [(30, 35, 35)]}) is None  # ends exactly at op_start


def test_wrapper_ranges_reject_bad_input() -> None:
    """U7: the two call forms are exclusive (``TypeError``); bad ranges are a caller bug (``ValueError``)."""
    before, rb = _oc_closed()
    check = helpers.check_wrapper_bytes_unchanged
    one = {1: [(35, 40, 40)]}
    for args, kwargs in (((), {}), ((1, 0), {"ranges": one}), ((1,), {}), ((), {"delta": 0}), ((1,), {"ranges": one})):
        with pytest.raises(TypeError):
            check(before, before, rb, rb, 0, *args, **kwargs)
    for ranges in (
        {},  # nothing declared
        {1: []},  # a stream with no range
        {9: [(0, 0, 0)]},  # not one of the page's content streams
        {1: [(36, 35, 35)]},  # start after end_old
        {1: [(45, 51, 51)]},  # end_old beyond the stream
        {1: [(-1, 0, 0)]},  # negative start
        {1: [(10, 20, 20), (15, 25, 25)]},  # overlapping
        {1: [(5, 6, 4)]},  # end_new before the start
        {1: [(0, 0, 4), (10, 10, 12)]},  # end_new before the start shifted by the earlier range
    ):
        with pytest.raises(ValueError):
            check(before, before, rb, rb, 0, ranges=ranges)
    assert check(before, before, rb, rb, 0, ranges={1: [(35, 40, 40), (40, 43, 43)]}) is None  # adjacent ranges
    twice, rt = _replay(_splice(before[1], [(35, 35, b"0 g "), (35, 35, b"0 G ")]))  # two insertions at one offset
    assert check(before, twice, rb, rt, 0, ranges={1: [(35, 35, 39), (35, 35, 43)]}) is None


def test_wrapper_one_range_equals_the_positional_form() -> None:
    """U8 (the equivalence the product branch relies on): one change inside the show's operator span given as ``ranges=``
    is the positional ``(xref, delta)`` call, on every positional case of the three tests above and on three in-show
    ranges over the base fixture (each with the EMC in place and one byte late)."""
    check = helpers.check_wrapper_bytes_unchanged
    edited, padding = _OC.replace(b"(abc)", b"(abcde)"), b" " * 64
    nested = b"/Span <</MCID 0>> BDC /P BMC BT /F1 12 Tf 72 700 Td (abc) Tj ET EMC EMC"
    cases = []  # (before streams, before replay, after streams, after replay, delta): the change is the show's string
    first, rfirst = _replay(_OC, padding + b"EMC")
    for streams in ((edited, padding + b"EMC"), (edited, padding + b" EMC"), (edited, b""), (edited, padding + b"EMX")):
        cases += [(first, rfirst, *_replay(*streams), delta) for delta in (2, 3)]
    cases.append((first, rfirst, {1: edited, 2: padding + b"XYZ"}, _replay(edited, padding + b"EMC")[1], 2))
    same, rsame = _replay(_OC + b" EMC")
    for stream in (edited + b" EMC", edited + b"  EMC"):
        cases += [(same, rsame, *_replay(stream), delta) for delta in (1, 2)]
    nest, rnest = _replay(nested)
    cases += [(nest, rnest, nest, rnest, 0), (nest, rnest, *_replay(nested.replace(b"/MCID 0", b"/MCID 1")), 0)]
    junk, rjunk = _replay(b"42 " + _OC + b" EMC")
    bare, rbare = _replay(b"BT /F1 12 Tf 72 700 Td (abc) Tj ET")
    cases += [(junk, rjunk, junk, rjunk, 0), (bare, rbare, bare, rbare, 0)]
    seen = set()
    for before, rb, after, ra, delta in cases:
        start, end_old = rb.shows[0].op_start, rb.shows[0].string_end
        positional = check(before, after, rb, ra, 0, 1, delta)
        assert check(before, after, rb, ra, 0, ranges={1: [(start, end_old, end_old + delta)]}) == positional
        seen.add(positional)
    base, rbase = _oc_closed()
    for start, end_old, new in ((35, 40, b"(abcde)"), (36, 39, b"abcde"), (35, 43, b"(abcde) Tj")):
        for late in (False, True):
            stream = _splice(base[1], [(start, end_old, new)])
            after, ra = _replay(stream[:-4] + b" " + stream[-4:] if late else stream)
            positional = check(base, after, rbase, ra, 0, 1, len(new) - (end_old - start))
            assert check(base, after, rbase, ra, 0, ranges={1: [(start, end_old, start + len(new))]}) == positional
            seen.add(positional)
    # non-vacuity: the equivalence held over passes and over every kind of failure these cases produce
    assert seen == {
        None,
        "wrapper: show_span: moved",
        "wrapper: close_moved: 1 of 1 wrapper(s)",
        "wrapper: close: 1 of 1 wrapper(s)",
        "wrapper: close_changed: 1 of 1 wrapper(s)",
        "wrapper: open_changed: 1 of 2 wrapper(s)",
        "wrapper: open_unparsed: 1 of 1 wrapper(s)",
    }, seen


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
