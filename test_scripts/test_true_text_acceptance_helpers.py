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
