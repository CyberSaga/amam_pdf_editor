"""Real-corpus acceptance for the manifest's proven Type0 text edits (the historic fourteen and any later row).

The local source PDFs are gitignored, so CI deselects this module through the
``needs_fixtures`` marker.  A missing local fixture self-skips; a present file
is hash-pinned and must run.  CHB and Taoyuan contain outlined vector text and
are deliberately outside this test's success criteria.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re
import shutil
import sys

import fitz
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402
from test_scripts.true_text_acceptance_helpers import (  # noqa: E402, F401
    _SEMANTIC_MAX_DEPTH,
    _TEXT_STATE_FIELDS,
    RENDER_ZOOM,
    FixtureUnavailable,
    _assert_only_target_streams_changed,
    _assert_pixels_changed_only_inside_masks,
    _assert_reopened_renders_match_live,
    _assert_source_font_reused,
    _assert_tj_compensation_is_last,
    _measurement_copy,
    _object_entry,
    _object_snapshot,
    _objects_semantically_equal,
    _pixmap_array,
    _prepare,
    _semantic_value,
    _shows,
    _trace_for,
    halo_mask,
    visual_frame,
)
from test_scripts.true_text_acceptance_helpers import decode_show as _decode_show  # noqa: E402
from test_scripts.true_text_corpus import (  # noqa: E402
    HISTORIC_FOURTEEN,
    MIN_ACTIVE_POSITIVES,
    CorpusCase,
    CorpusSpec,
    load_manifest,
)

pytestmark = pytest.mark.needs_fixtures


# The corpus table lives in the tracked manifest (test_scripts/fixtures/true_text_corpus/manifest.json);
# ``CorpusCase``/``CorpusSpec`` are the loader's classes, re-exported under their old names.
_MANIFEST = load_manifest()
CORPORA = _MANIFEST.corpus_specs()
HVAC = _MANIFEST.spec_by_slug("hvac")
ECC = _MANIFEST.spec_by_slug("ecc")


def _fixture(spec: CorpusSpec) -> Path:
    try:
        return helpers._fixture(spec)
    except FixtureUnavailable as exc:
        pytest.skip(str(exc))


def _resolve_cases(spec: CorpusSpec, doc: fitz.Document) -> tuple[CorpusCase, ...]:
    """Fill every hash-pinned ``original`` from the fixture's own show text.

    Every manifest row has ``original: null`` plus ``original_sha256``, so this branch serves all of them.
    Policy: a row on a proprietary or local_unrecorded corpus never carries a plaintext ``original`` (the
    calibration literals live only in ``CALIBRATION_STRINGS``); a plaintext ``original`` is tolerated on
    public rows only, and such a row passes through unchanged.
    """
    registry = DocumentFontRegistry(doc)
    resolved: list[CorpusCase] = []
    for case in spec.cases:
        if case.original is None:
            show = _shows(doc, case.page_index)[case.show_seq]
            text = _decode_show(
                registry, doc[case.page_index], show, font_kind=case.font_kind
            )
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == case.original_sha256, (
                f"{spec.slug} p{case.page_index + 1}/show{case.show_seq}: target text changed"
            )
            case = replace(case, original=text)
        resolved.append(case)
    return tuple(resolved)


def test_production_engine_prepares_all_manifest_positive_edits() -> None:
    """Red-first gate: report every current production refusal in one run."""
    refusals: list[str] = []
    prepared_count = 0
    visited: set[tuple[str, int, int]] = set()
    for spec in CORPORA:
        path = _fixture(spec)
        with fitz.open(path) as doc:
            engine = TieredCommitEngine(doc, max_tier=1)
            for case in _resolve_cases(spec, doc):
                visited.add((spec.slug, case.page_index, case.show_seq))
                result = _prepare(engine, doc, case)
                if isinstance(result, PlanRejection):
                    refusals.append(
                        f"{spec.slug}/{case.label}: {result.reason}: {result.detail}"
                    )
                else:
                    prepared_count += 1
    # independent oracle: the literal HISTORIC_FOURTEEN (outside the manifest) must all have been visited
    assert {t[:3] for t in HISTORIC_FOURTEEN} <= visited
    assert prepared_count + len(refusals) == len(visited)
    assert len(_MANIFEST.click_reachable_positives()) >= MIN_ACTIVE_POSITIVES
    assert not refusals, "production engine refused real Type0 edits:\n" + "\n".join(
        refusals
    )


def test_growth_oracle_agrees_with_the_product_on_the_historic_fourteen() -> None:
    """The shared growth-zone oracle (I0b S3a) agrees with the product on every historic row, BEFORE it is wired
    into the commit test.  Applicable = the product's own ``has_ink_growth`` (never a re-derived mirror); the
    oracle must pass in both shapes: the product shape (``prepared`` set) and the experiment shape (the 96 dpi
    page state)."""
    historic = {row[:3] for row in HISTORIC_FOURTEEN}
    seen: set[tuple[str, int, int]] = set()
    applicable: set[tuple[str, int, int]] = set()
    for slug in ("hvac", "ecc"):
        spec = _MANIFEST.spec_by_slug(slug)
        with fitz.open(_fixture(spec)) as doc:
            engine = TieredCommitEngine(doc, max_tier=1)
            for case in _resolve_cases(spec, doc):
                key = (slug, case.page_index, case.show_seq)
                if key not in historic:
                    continue
                prepared = _prepare(engine, doc, case)
                assert isinstance(prepared, PreparedEdit), key
                seen.add(key)
                target, verify_box = prepared.target_bbox_page, prepared.effective_verify_bbox
                assert (tuple(verify_box) != tuple(target)) is prepared.has_ink_growth, key
                args = (
                    doc,
                    case.page_index,
                    _shows(doc, case.page_index)[case.show_seq],
                    visual_frame(doc[case.page_index]),
                    target,
                    verify_box,
                    prepared.source_advance,
                )
                for prep in (prepared, None):  # the product shape, then the experiment shape
                    detail = helpers.check_growth_zone_was_blank(*args, prepared=prep, x_pre=0.0, k_inner=0.0)
                    assert detail is None, (key, prep is None, detail)
                if prepared.has_ink_growth:
                    applicable.add(key)
    assert seen == historic
    assert applicable == {("hvac", 4, 26)}


#: hvac p4/show11 with '線' swapped for '路', a glyph the embedded PMingLiU
#: subset does not carry.  (The ECC growth negative -- the longer drawing
#: number that crowded the column line in the 2026-09-21 experiment -- is not
#: recoverable: docs/experiments and _evidence_pilot keep only a redacted
#: placeholder, so no test invents it.)
_MISSING_GLYPH_REPLACEMENT = "空調冰水管路系統圖(1)"


def test_production_engine_refuses_a_glyph_missing_from_the_embedded_subset() -> None:
    """Guard (passes before the UI steps): Tier 0 and Tier 1 both refuse with
    ``type0_unicode_unmapped`` and the prepare leaves the document unchanged."""
    path = _fixture(HVAC)
    with fitz.open(path) as doc:
        case = next(
            case
            for case in _resolve_cases(HVAC, doc)
            if (case.page_index, case.show_seq) == (4, 11)
        )
        streams = [
            (xref, doc.xref_stream(xref)) for xref in doc[case.page_index].get_contents()
        ]
        engine = TieredCommitEngine(doc, max_tier=1)
        result = _prepare(engine, doc, replace(case, replacement=_MISSING_GLYPH_REPLACEMENT))
        assert isinstance(result, PlanRejection), result
        assert result.reason == "type0_unicode_unmapped", (result.reason, result.detail)
        assert [
            (xref, doc.xref_stream(xref)) for xref in doc[case.page_index].get_contents()
        ] == streams


def test_harness_prepare_measurement_does_not_mutate_the_judged_document(
    tmp_path: Path,
) -> None:
    """The harness's own measurements must leave the candidate byte-for-byte clean.

    Prepare-only on a /Rotate 270 page, then ``saveIncr`` + reopen, judged by
    the same non-target check the commit test uses (no stream may change).
    """
    source_path = _fixture(HVAC)
    candidate_path = tmp_path / "hvac-prepare-only.pdf"
    shutil.copyfile(source_path, candidate_path)
    with fitz.open(source_path) as source:
        case = next(c for c in _resolve_cases(HVAC, source) if (c.page_index, c.show_seq) == (4, 11))
        assert source[case.page_index].rotation == 270
        source_snapshot = _object_snapshot(source)

    with fitz.open(candidate_path) as candidate:
        engine = TieredCommitEngine(candidate, max_tier=1)
        prepared = _prepare(engine, candidate, case)
        assert isinstance(prepared, PreparedEdit), prepared
        candidate.saveIncr()

    with fitz.open(candidate_path) as reopened:
        _assert_only_target_streams_changed(source_snapshot, reopened, set())


def _mutate_non_target_content_stream_byte(doc: fitz.Document) -> int:
    """Flip one byte (a space to a newline) of an unedited page's stream."""
    xref = doc[0].get_contents()[0]
    data = doc.xref_stream(xref)
    index = data.index(b" ")
    doc.update_stream(xref, data[:index] + b"\n" + data[index + 1 :])
    return xref


def _mutate_non_target_page_rotate(doc: fitz.Document) -> int:
    """Change the /Rotate VALUE of an unedited page."""
    page = doc[0]
    doc.xref_set_key(page.xref, "Rotate", str((page.rotation + 90) % 360))
    return page.xref


def _mutate_target_font_widths_entry(doc: fitz.Document) -> int:
    """Change one /W width of the edited ArialMT CIDFont (object value, not order)."""
    font_xref = DocumentFontRegistry(doc).capability(doc[4], "C2_0").font_xref
    descendants = doc.xref_get_key(font_xref, "DescendantFonts")[1]
    match = re.search(r"/W (\d+) 0 R", descendants)
    assert match is not None, descendants
    xref = int(match.group(1))
    widths = doc.xref_object(xref)
    changed = re.sub(r"\[ (\d+) \]", lambda m: f"[ {int(m.group(1)) + 1} ]", widths, count=1)
    assert changed != widths
    doc.update_object(xref, changed)
    return xref


def _reorder_non_target_page_keys(doc: fitz.Document) -> int:
    """Key-order-only rewrite of an unedited /Rotate 270 page, via the real trigger.

    ``get_text`` toggles /Rotate, dirtying the /Page dict; ``saveIncr`` then
    rewrites it (and its nested /VP dicts) with the same keys and values in
    another order -- exactly what product page indexing does at open.
    """
    page = doc[3]
    assert page.rotation == 270
    page.get_text()
    return page.xref


def _mutate_non_target_extgstate_number(doc: fitz.Document) -> int:
    """Change a non-target ExtGState ``/CA 1`` to ``0.9999999`` (no rounding allowed)."""
    xref = 10642
    assert doc.xref_get_key(xref, "CA") == ("int", "1")
    doc.xref_set_key(xref, "CA", "0.9999999")
    return xref


def _add_key_to_non_target_page(doc: fitz.Document) -> int:
    """Add one key to an unedited page dict."""
    xref = doc[0].xref
    assert doc.xref_get_key(xref, "UserUnit") == ("null", "null")
    doc.xref_set_key(xref, "UserUnit", "1")
    return xref


def _retarget_non_target_page_reference(doc: fitz.Document) -> int:
    """Point an unedited page's ``/GS7`` resource at another existing object."""
    xref = doc[1].xref
    assert doc.xref_get_key(xref, "Resources/ExtGState/GS7") == ("xref", "10641 0 R")
    doc.xref_set_key(xref, "Resources/ExtGState/GS7", "10642 0 R")
    return xref


@pytest.mark.parametrize(
    ("mutate", "must_fail"),
    (
        (None, False),
        (_reorder_non_target_page_keys, False),
        (_mutate_non_target_content_stream_byte, True),
        (_mutate_non_target_page_rotate, True),
        (_mutate_target_font_widths_entry, True),
        (_mutate_non_target_extgstate_number, True),
        (_add_key_to_non_target_page, True),
        (_retarget_non_target_page_reference, True),
    ),
    ids=(
        "control",
        "key-order-only",
        "stream-byte",
        "page-rotate",
        "font-widths",
        "number-1-to-0.9999999",
        "added-key",
        "reference-target",
    ),
)
def test_non_target_object_check_catches_deliberate_mutations(
    mutate, must_fail: bool, tmp_path: Path
) -> None:
    """Mutation guard for ``_assert_only_target_streams_changed`` after reopen."""
    source_path = _fixture(HVAC)
    candidate_path = tmp_path / "hvac-mutated.pdf"
    shutil.copyfile(source_path, candidate_path)
    with fitz.open(source_path) as source:
        source_snapshot = _object_snapshot(source)

    with fitz.open(candidate_path) as candidate:
        mutated_xref = None if mutate is None else mutate(candidate)
        candidate.saveIncr()

    with fitz.open(candidate_path) as reopened:
        if mutated_xref is None:
            _assert_only_target_streams_changed(
                source_snapshot, reopened, set(), semantic=True
            )
            return
        # Every mutation must really reach the reopened file (raw text differs),
        # so a passing semantic check below cannot be a no-op mutation.
        assert _object_entry(reopened, mutated_xref) != source_snapshot[mutated_xref - 1]
        if must_fail:
            with pytest.raises(
                AssertionError, match=rf"non-target xref {mutated_xref} changed"
            ):
                _assert_only_target_streams_changed(
                    source_snapshot, reopened, set(), semantic=True
                )
        else:
            _assert_only_target_streams_changed(
                source_snapshot, reopened, set(), semantic=True
            )


@pytest.mark.parametrize(
    ("original", "current", "equal"),
    (
        ("<< /A 1 /B << /C 2 /D 3 >> >>", "<< /B << /D 3 /C 2 >> /A 1 >>", True),
        ("<< /A 1 >>", "<< /A 1.0 >>", True),  # same number, int/real kind folds
        ("<< /A 1 >>", "<< /A 1.00000000000000000001 >>", False),  # beyond float
        ("<< /A .3528 >>", "<< /A .3529 >>", False),
        ("<< /A 1 0 R >>", "<< /A 1 1 R >>", False),
        ("<< /A (\\101) >>", "<< /A <5C313031> >>", False),
        ("[ 1 2 ]", "[ 2 1 ]", False),
        ("<< /A 1 >>", "<< /A 1 /B null >>", False),
        ("<< /A 1 >>", "<< /A 1 /A 1 >>", False),
        ("<< /A (x) >>", "<< /A (x >>", False),
    ),
)
def test_semantic_object_comparison_ignores_only_dictionary_key_order(
    original: str, current: str, equal: bool
) -> None:
    """Unit guard for ``_objects_semantically_equal`` (no rounding, fail-closed)."""
    assert _objects_semantically_equal(original, current) is equal
    assert _objects_semantically_equal(current, original) is equal


def _small_page_pixels(*draws: fitz.Rect) -> np.ndarray:
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 50), "Buffer Tank", fontsize=12)
        for rect in draws:
            page.draw_rect(rect, color=(1, 0, 0), fill=(1, 0, 0))
        return _pixmap_array(page)


def test_pixel_mask_check_catches_a_change_outside_the_mask() -> None:
    """Mutation guard for ``_assert_pixels_changed_only_inside_masks``."""
    before = _small_page_pixels()
    mask = fitz.Rect(10, 30, 110, 60)
    inside = _small_page_pixels(fitz.Rect(40, 40, 44, 44))
    _assert_pixels_changed_only_inside_masks("synthetic", 0, before, inside, [mask])

    both = _small_page_pixels(fitz.Rect(40, 40, 44, 44), fitz.Rect(150, 80, 152, 82))
    with pytest.raises(AssertionError, match="pixels changed outside target masks"):
        _assert_pixels_changed_only_inside_masks("synthetic", 0, before, both, [mask])

    with pytest.raises(AssertionError, match="synthetic"):
        _assert_pixels_changed_only_inside_masks("synthetic", 0, before, before, [mask])


def test_live_render_check_catches_a_rect_drawn_on_the_live_document(
    tmp_path: Path,
) -> None:
    """Mutation guard for ``_assert_reopened_renders_match_live``."""
    path = tmp_path / "live-render.pdf"
    with fitz.open() as doc:
        doc.new_page(width=200, height=100).insert_text((20, 50), "Buffer Tank")
        doc.save(path)

    with fitz.open(path) as live:
        live_renders = {0: bytes(live[0].get_pixmap(alpha=False).samples)}
    with fitz.open(path) as reopened:
        _assert_reopened_renders_match_live(live_renders, reopened)

    with fitz.open(path) as live:
        live[0].draw_rect(fitz.Rect(150, 80, 152, 82), color=(1, 0, 0), fill=(1, 0, 0))
        live_renders = {0: bytes(live[0].get_pixmap(alpha=False).samples)}
    with fitz.open(path) as reopened:
        with pytest.raises(AssertionError):
            _assert_reopened_renders_match_live(live_renders, reopened)


@pytest.mark.parametrize("spec", CORPORA, ids=lambda spec: spec.slug)
def test_production_engine_commits_reopens_and_preserves_real_type0_pdf(
    spec: CorpusSpec, tmp_path: Path
) -> None:
    """Commit every edit through production, then prove resource/layout fidelity."""
    source_path = _fixture(spec)
    candidate_path = tmp_path / f"{spec.slug}-edited.pdf"
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    shutil.copyfile(source_path, candidate_path)

    with fitz.open(source_path) as source:
        cases = _resolve_cases(spec, source)
        source_snapshot = _object_snapshot(source)
        source_shows = {
            case: _shows(source, case.page_index)[case.show_seq] for case in cases
        }
        source_traces = {
            case: _trace_for(
                source[case.page_index], source_shows[case], case.original
            )
            for case in cases
        }
        changed_streams: set[int] = set()
        tier1_payloads: dict[CorpusCase, bytes] = {}
        growth_checked = 0

        with fitz.open(candidate_path) as candidate:
            engine = TieredCommitEngine(candidate, max_tier=1)
            for case in cases:
                prepared = _prepare(engine, candidate, case)
                assert isinstance(prepared, PreparedEdit), (
                    f"{spec.slug}/{case.label} refused: "
                    f"{prepared.reason}: {prepared.detail}"
                )
                assert prepared.font_resource == case.font_resource
                assert prepared.font_xref == DocumentFontRegistry(candidate).capability(
                    candidate[case.page_index], case.font_resource
                ).font_xref
                if case.expected_tj_compensation is not None:
                    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
                    _assert_tj_compensation_is_last(
                        prepared, case.expected_tj_compensation
                    )
                    tier1_payloads[case] = prepared.replacement.replacement_bytes
                else:
                    assert prepared.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH
                if case.expected_tier is not None:
                    assert prepared.tier == case.expected_tier, (
                        spec.slug,
                        case.page_index,
                        case.show_seq,
                    )

                if prepared.has_ink_growth:
                    # the growth zone is judged on the candidate as it stands just before THIS edit: the state
                    # the product verified (earlier edits of the same file are already in it)
                    with _measurement_copy(candidate) as pre_edit:
                        growth_detail = helpers.check_growth_zone_was_blank(
                            pre_edit,
                            case.page_index,
                            _shows(pre_edit, case.page_index)[case.show_seq],
                            visual_frame(pre_edit[case.page_index]),
                            prepared.target_bbox_page,
                            prepared.effective_verify_bbox,
                            prepared.source_advance,
                            prepared=prepared,
                            x_pre=0.0,
                            k_inner=0.0,
                        )
                    assert growth_detail is None, (spec.slug, case.label, growth_detail)
                    growth_checked += 1

                outcome = engine.commit(prepared)
                assert outcome.status is CommitStatus.COMMITTED, (
                    spec.slug,
                    case.label,
                    outcome,
                )
                assert outcome.font_outcomes
                assert all(
                    font.action == FontResourceAction.SOURCE_RESOURCE_REUSED
                    for font in outcome.font_outcomes
                )
                changed_streams.add(prepared.stream_xref)

            assert len(tier1_payloads) == sum(
                case.expected_tj_compensation is not None for case in cases
            )
            # a positive kern (the written number K > 0) pulls the next glyph back, i.e. the text grew
            # (patch.py kern_for_displacement): exactly those edits had their growth zone judged above
            assert growth_checked == sum(
                (case.expected_tj_compensation or 0.0) > 0.0 for case in cases
            )

            _assert_only_target_streams_changed(
                source_snapshot, candidate, changed_streams
            )
            live_renders = {
                page_index: bytes(candidate[page_index].get_pixmap(alpha=False).samples)
                for page_index in {case.page_index for case in cases}
            }
            candidate.saveIncr()

        with fitz.open(candidate_path) as reopened:
            _assert_only_target_streams_changed(
                source_snapshot, reopened, changed_streams, semantic=True
            )
            for xref in range(len(source_snapshot) + 1, reopened.xref_length()):
                assert reopened.xref_get_key(xref, "Type") == ("name", "/XRef")

            _assert_reopened_renders_match_live(live_renders, reopened)

            reopened_shows = {
                case: _shows(reopened, case.page_index)[case.show_seq]
                for case in cases
            }
            masks: dict[int, list[fitz.Rect]] = {}
            edited_sequences: dict[int, set[int]] = {}
            for case in cases:
                before_show = source_shows[case]
                after_show = reopened_shows[case]
                _assert_source_font_reused(
                    source, reopened, case, before_show, after_show
                )
                for field in _TEXT_STATE_FIELDS:
                    assert getattr(after_show, field) == getattr(before_show, field), (
                        spec.slug,
                        case.label,
                        field,
                    )

                before_trace = source_traces[case]
                after_trace = _trace_for(
                    reopened[case.page_index], after_show, case.replacement
                )
                assert after_trace["font"] == before_trace["font"] == case.basefont
                for field in ("dir", "size", "color", "opacity", "type"):
                    assert after_trace[field] == before_trace[field], (
                        spec.slug,
                        case.label,
                        field,
                    )
                assert after_trace["chars"][0][2] == before_trace["chars"][0][2]

                if case in tier1_payloads:
                    assert after_show.operator == "TJ"
                    assert after_show.array_item_count == 1
                    stream = reopened.xref_stream(after_show.stream_xref)
                    assert stream[after_show.op_start : after_show.op_end] == tier1_payloads[
                        case
                    ]

                masks.setdefault(case.page_index, []).append(
                    halo_mask(
                        before_trace["bbox"],
                        after_trace["bbox"],
                        visual_frame(source[case.page_index]),
                    )
                )
                edited_sequences.setdefault(case.page_index, set()).add(case.show_seq)

            for page_index in edited_sequences:
                edited = [
                    helpers.edited_show(
                        source_shows[case],
                        reopened_shows[case],
                        code_bytes=2 if case.font_kind == "type0" else 1,
                    )
                    for case in cases
                    if case.page_index == page_index
                ]
                neighbour_measurements: dict = {}
                neighbour_detail = helpers.check_neighbour_glyphs_unchanged(
                    source,
                    reopened,
                    page_index,
                    edited,
                    kind="positive",
                    frame=visual_frame(source[page_index]),
                    measurements=neighbour_measurements,
                )
                assert neighbour_detail is None, (spec.slug, page_index, neighbour_detail)
                # the oracle really looked: other glyphs were paired and the new glyphs' ink was checked
                assert neighbour_measurements["glyphs_paired"] > 0, (spec.slug, page_index)
                assert neighbour_measurements["target_glyphs_ink_checked"] >= 1, (spec.slug, page_index)

            for page_index, skipped in edited_sequences.items():
                before_page_shows = _shows(source, page_index)
                after_page_shows = _shows(reopened, page_index)
                assert len(after_page_shows) == len(before_page_shows)
                for before_show, after_show in zip(before_page_shows, after_page_shows):
                    if before_show.seq not in skipped:
                        assert after_show.origin_user == before_show.origin_user

            for page_index, page_masks in masks.items():
                _assert_pixels_changed_only_inside_masks(
                    spec.slug,
                    page_index,
                    _pixmap_array(source[page_index]),
                    _pixmap_array(reopened[page_index]),
                    page_masks,
                )

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_digest
