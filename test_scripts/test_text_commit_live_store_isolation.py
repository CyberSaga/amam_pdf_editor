"""Commit-time verification must not warm MuPDF's image store on the live doc.

MuPDF caches decoded image tiles per image, at the subsample level the first
consumer asked for, and every later render of the same document reuses the
closest cached level at or above the resolution it needs.  A fresh open (or
``tobytes`` reopen) has an empty cache, so it decodes at the render's own
level.  When commit verification rasterized (96 dpi) or extracted
(``get_text('rawdict')`` with ``TEXT_PRESERVE_IMAGES``, ``get_image_rects``)
on the LIVE document, a later live render at 1x reused those higher-resolution
decodes and no longer matched a fresh reopen of the very same bytes.

The fixture's image is high-frequency noise placed small, so 72 dpi, 96 dpi
and full-resolution decodes all rasterize differently -- the test first
proves that sensitivity on a throwaway copy, so it cannot pass vacuously.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.verify as verify_module  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    REPLACEMENT_EQUAL_ADVANCE,
    REPLACEMENT_LONGER,
    Type0Fixture,
    _set_page_xobject,
    append_page_content,
    build_identity_h_fixture,
    install_image_xobject,
)

_NOISE_SIZE = 628  # measured: 72 dpi, 96 dpi and full decodes all differ at 128pt
_NOISE_PLACEMENT = "q 128 0 0 128 380 100 cm /ImN Do Q"  # far from the target
_IMAGE_OCCUPANCY = "occupancy: image intersects growth zone"


def _install_noise_image(fixture: Type0Fixture) -> int:
    rng = random.Random(20260929)
    data = rng.randbytes(_NOISE_SIZE * _NOISE_SIZE * 3)
    doc = fixture.doc
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        f"<< /Type /XObject /Subtype /Image /Width {_NOISE_SIZE} "
        f"/Height {_NOISE_SIZE} /ColorSpace /DeviceRGB /BitsPerComponent 8 >>",
    )
    doc.update_stream(xref, data, compress=True)
    _set_page_xobject(fixture, "ImN", f"{xref} 0 R")
    append_page_content(fixture, _NOISE_PLACEMENT)
    return xref


def _render(page: fitz.Page) -> bytes:
    return bytes(page.get_pixmap(alpha=False).samples)


def _fresh_render(doc: fitz.Document, page_number: int) -> bytes:
    with fitz.open("pdf", doc.tobytes()) as fresh:
        return _render(fresh[page_number])


def _target_bbox_visual(fixture: Type0Fixture) -> tuple[float, float, float, float]:
    # Measured on a throwaway copy: the judged live document must see only
    # the product's own calls.
    with fitz.open("pdf", fixture.doc.tobytes()) as copy:
        page = copy[fixture.page_number]
        flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES
        for block in page.get_text("rawdict", flags=flags)["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = "".join(char["c"] for char in span["chars"])
                    if fixture.text in text:
                        start = text.index(fixture.text)
                        chars = span["chars"][start : start + len(fixture.text)]
                        raw = fitz.Rect(chars[0]["bbox"])
                        for char in chars[1:]:
                            raw |= fitz.Rect(char["bbox"])
                        visual = raw * page.rotation_matrix
                        return tuple(float(v) for v in visual)
    raise AssertionError("target text not found")


def _assert_fixture_is_store_sensitive(fixture: Type0Fixture) -> None:
    """Both warming legs must visibly change a later 1x render of a copy."""
    data = fixture.doc.tobytes()
    with fitz.open("pdf", data) as cold:
        baseline = _render(cold[fixture.page_number])
    with fitz.open("pdf", data) as warmed:
        warmed[fixture.page_number].get_pixmap(dpi=96)
        assert _render(warmed[fixture.page_number]) != baseline, "96 dpi leg"
    with fitz.open("pdf", data) as warmed:
        warmed[fixture.page_number].get_text("rawdict")
        assert _render(warmed[fixture.page_number]) != baseline, "rawdict leg"


@pytest.mark.parametrize("rotate", [0, 270])
@pytest.mark.parametrize(
    ("replacement", "tier"),
    [
        (REPLACEMENT_EQUAL_ADVANCE, CommitTier.TIER0_LOSSLESS_STREAM_PATCH),
        (REPLACEMENT_LONGER, CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE),
    ],
    ids=["tier0", "tier1-growth"],
)
def test_committed_live_document_renders_like_a_fresh_reopen(
    replacement: str, tier: CommitTier, rotate: int
) -> None:
    fixture = build_identity_h_fixture(rotate=rotate)
    try:
        _install_noise_image(fixture)
        _assert_fixture_is_store_sensitive(fixture)
        engine = TieredCommitEngine(fixture.doc, max_tier=1)
        prepared = engine.prepare(
            fixture.page,
            target_text=fixture.text,
            replacement_text=replacement,
            expected_origin=None,
            target_bbox=_target_bbox_visual(fixture),
        )
        assert isinstance(prepared, PreparedEdit), prepared
        assert prepared.tier is tier
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED, outcome

        live = _render(fixture.page)
        assert live == _fresh_render(fixture.doc, fixture.page_number), (
            "live render differs from a fresh reopen of the committed bytes"
        )
    finally:
        fixture.doc.close()


def _white_image_in_growth_zone(rotate: int) -> Type0Fixture:
    """A WHITE image over the growth zone: invisible to the raster proof on a
    white page, so only the image-occupancy gate can refuse it."""
    fixture = build_identity_h_fixture(rotate=rotate)
    install_image_xobject(fixture, name="ImW", rgb=(255, 255, 255))
    append_page_content(fixture, "q 6 0 0 20 122 690 cm /ImW Do Q")
    return fixture


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_white_image_in_growth_zone_is_refused_at_image_occupancy(rotate: int) -> None:
    fixture = _white_image_in_growth_zone(rotate)
    try:
        result = TieredCommitEngine(fixture.doc, max_tier=1).prepare(
            fixture.page,
            target_text=fixture.text,
            replacement_text=REPLACEMENT_LONGER,
            expected_origin=None,
            target_bbox=_target_bbox_visual(fixture),
        )
        assert isinstance(result, PlanRejection), result
        assert result.reason == RejectReason.GROWTH_REGION_NOT_BLANK
        assert result.detail == _IMAGE_OCCUPANCY, result.detail
    finally:
        fixture.doc.close()


@pytest.mark.parametrize("rotate", [0, 270])
def test_commit_re_proves_image_occupancy_and_reverts(
    rotate: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit-time gate (now run on an observation snapshot) still sees
    the image: prepare is forced past the gate, commit must refuse + revert."""
    fixture = _white_image_in_growth_zone(rotate)
    try:
        engine = TieredCommitEngine(fixture.doc, max_tier=1)
        real_gate = verify_module._images_intersect_growth
        monkeypatch.setattr(
            verify_module, "_images_intersect_growth", lambda *a, **k: False
        )
        prepared = engine.prepare(
            fixture.page,
            target_text=fixture.text,
            replacement_text=REPLACEMENT_LONGER,
            expected_origin=None,
            target_bbox=_target_bbox_visual(fixture),
        )
        assert isinstance(prepared, PreparedEdit), prepared
        monkeypatch.setattr(verify_module, "_images_intersect_growth", real_gate)
        before = fixture.content_bytes()
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.FAILED, outcome
        assert outcome.degraded_reason is not None
        assert _IMAGE_OCCUPANCY in outcome.degraded_reason, outcome
        assert fixture.content_bytes() == before
    finally:
        fixture.doc.close()


def _prepared_for(fixture: Type0Fixture, replacement: str) -> tuple[TieredCommitEngine, PreparedEdit]:
    engine = TieredCommitEngine(fixture.doc, max_tier=1)
    prepared = engine.prepare(
        fixture.page,
        target_text=fixture.text,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=_target_bbox_visual(fixture),
    )
    assert isinstance(prepared, PreparedEdit), prepared
    return engine, prepared


def _snapshot_fails_on_call(
    engine: TieredCommitEngine, monkeypatch: pytest.MonkeyPatch, failing_call: int
) -> list[int]:
    """Make the engine's ``failing_call``-th scratch copy (1-based) unbuildable."""
    real = engine._build_scratch_copy
    calls: list[int] = []

    def flaky() -> fitz.Document | None:
        calls.append(len(calls) + 1)
        return None if len(calls) == failing_call else real()

    monkeypatch.setattr(engine, "_build_scratch_copy", flaky)
    return calls


@pytest.mark.parametrize(
    "replacement", [REPLACEMENT_EQUAL_ADVANCE, REPLACEMENT_LONGER], ids=["tier0", "tier1"]
)
def test_commit_refuses_before_mutation_without_a_pre_state_snapshot(
    replacement: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: no pre-commit snapshot -> FAILED, and the live page is
    never observed nor patched (no fallback to rendering the live page)."""
    fixture = build_identity_h_fixture()
    try:
        engine, prepared = _prepared_for(fixture, replacement)
        before = fixture.content_bytes()
        calls = _snapshot_fails_on_call(engine, monkeypatch, failing_call=1)
        monkeypatch.setattr(
            fitz.Page,
            "get_pixmap",
            lambda *a, **k: pytest.fail("live page rendered without a snapshot"),
        )
        outcome = engine.commit(prepared)
        assert calls == [1]
        assert outcome.status is CommitStatus.FAILED, outcome
        assert outcome.fallback_chain[-1].endswith(RejectReason.VERIFICATION_FAILED)
        assert "snapshot" in (outcome.degraded_reason or "")
        assert fixture.content_bytes() == before
    finally:
        fixture.doc.close()


@pytest.mark.parametrize(
    ("replacement", "chain"),
    [
        (REPLACEMENT_EQUAL_ADVANCE, (f"tier0:{RejectReason.VERIFICATION_FAILED}",)),
        (
            REPLACEMENT_LONGER,
            (
                f"tier0:{RejectReason.ADVANCE_MISMATCH}",
                f"tier1:{RejectReason.VERIFICATION_FAILED}",
            ),
        ),
    ],
    ids=["tier0", "tier1"],
)
def test_commit_reverts_without_a_post_state_snapshot(
    replacement: str, chain: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: the patch was applied, the post snapshot cannot be built
    -> the patch is reverted and the commit FAILS (never verified live)."""
    fixture = build_identity_h_fixture()
    try:
        engine, prepared = _prepared_for(fixture, replacement)
        before = fixture.content_bytes()
        calls = _snapshot_fails_on_call(engine, monkeypatch, failing_call=2)
        outcome = engine.commit(prepared)
        assert calls == [1, 2]
        assert outcome.status is CommitStatus.FAILED, outcome
        assert outcome.fallback_chain == chain
        assert "snapshot" in (outcome.degraded_reason or "")
        assert fixture.content_bytes() == before
    finally:
        fixture.doc.close()
