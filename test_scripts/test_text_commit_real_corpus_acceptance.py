"""Real-corpus acceptance for the fourteen proven Type0 text edits.

The local source PDFs are gitignored, so CI deselects this module through the
``needs_fixtures`` marker.  A missing local fixture self-skips; a present file
is hash-pinned and must run.  CHB and Taoyuan contain outlined vector text and
are deliberately outside this test's success criteria.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
import shutil

import fitz
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]

from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.replay import ShowOp, replay_page_streams  # noqa: E402

pytestmark = pytest.mark.needs_fixtures


@dataclass(frozen=True)
class CorpusCase:
    page_index: int
    show_seq: int
    original: str | None
    replacement: str
    font_resource: str
    basefont: str
    expected_tj_compensation: float | None = None
    # When ``original`` is None the target text is read from the hash-pinned
    # fixture and checked against this digest, keeping identifying text out of git.
    original_sha256: str | None = None

    @property
    def label(self) -> str:
        return f"p{self.page_index + 1}/show{self.show_seq}: {self.original!r} -> {self.replacement!r}"


@dataclass(frozen=True)
class CorpusSpec:
    slug: str
    relative_path: str
    sha256: str
    cases: tuple[CorpusCase, ...]


HVAC = CorpusSpec(
    slug="hvac",
    relative_path="test_files/hvac-dwg.pdf",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    cases=(
        CorpusCase(4, 11, "空調冰水管線系統圖(1)", "空調冰水管線系統圖(4)", "C2_1", "PMingLiU"),
        CorpusCase(4, 16, "空調冷卻水管線系統圖(1)", "空調冷卻水管線系統表(1)", "C2_1", "PMingLiU"),
        CorpusCase(4, 6, "空調系統封面", "空調系統圖說", "C2_1", "PMingLiU"),
        CorpusCase(
            4,
            7,
            "Chilled Water Distribution System Diagram(1)",
            "Chilled Water Distribution System Diagram(4)",
            "C2_0",
            "ArialMT",
        ),
        CorpusCase(
            4,
            18,
            "1F Chilled Water System Plan Layout",
            "2F Chilled Water System Plan Layout",
            "C2_0",
            "ArialMT",
        ),
        CorpusCase(
            4,
            26,
            "Drawing List",
            "Drawing Title",
            "C2_0",
            "ArialMT",
            333.0,
        ),
        CorpusCase(5, 60, "2026.05.15", "2026.05.16", "C2_1", "MicrosoftJhengHeiRegular"),
        CorpusCase(
            5,
            58,
            "空調系統設計圖說A版",
            "空調系統設計圖說B版",
            "C2_1",
            "MicrosoftJhengHeiRegular",
            -79.0,
        ),
        CorpusCase(6, 7, "Buffer Tank", "Tank Buffer", "C2_1", "ArialMT"),
        CorpusCase(6, 5, "Buffer Tank", "Tank Buffer", "C2_1", "ArialMT"),
    ),
)

ECC = CorpusSpec(
    slug="ecc",
    relative_path="test_files/ecc-dwg.pdf",
    sha256="0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853",
    cases=(
        CorpusCase(0, 31, "專案名稱", "專案圖名", "F2", "DFKaiShu-SB-Estd-BF"),
        CorpusCase(0, 38, "平面配置圖", "機房配置圖", "F2", "DFKaiShu-SB-Estd-BF"),
        CorpusCase(0, 57, "113.05.03", "113.05.05", "F2", "DFKaiShu-SB-Estd-BF"),
        CorpusCase(
            0,
            60,
            None,
            "ECC-3",
            "F2",
            "DFKaiShu-SB-Estd-BF",
            -500.0,
            original_sha256="306a3a57a5bfe7d06316a66c06f4adde43b9d4a647266cabcebc412485bd0660",
        ),
    ),
)

CORPORA = (HVAC, ECC)
_TEXT_STATE_FIELDS = (
    "font_resource",
    "font_size",
    "tm",
    "ctm",
    "hscale",
    "char_spacing",
    "word_spacing",
    "rise",
    "render_mode",
    "origin_user",
)
_TJ_WITH_TRAILING_COMPENSATION = re.compile(
    rb"\[<([0-9A-Fa-f]+)> ([+-]?(?:\d+(?:\.\d*)?|\.\d+))\] TJ"
)


def _fixture(spec: CorpusSpec) -> Path:
    path = ROOT / spec.relative_path
    if not path.exists():
        pytest.skip(f"missing optional real-corpus fixture: {spec.relative_path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == spec.sha256, (
        f"{spec.slug} fixture changed; reselect show sequences before accepting it: {digest}"
    )
    return path


def _shows(doc: fitz.Document, page_index: int) -> tuple[ShowOp, ...]:
    page = doc[page_index]
    replay = replay_page_streams(
        [(xref, doc.xref_stream(xref)) for xref in page.get_contents()]
    )
    assert not replay.malformed, replay
    assert replay.refusal_reason is None, replay.refusal_reason
    return replay.shows


def _decode_show(
    registry: DocumentFontRegistry, page: fitz.Page, show: ShowOp
) -> str:
    assert show.font_resource is not None
    capability = registry.capability(page, show.font_resource)
    assert capability is not None
    assert capability.subtype == "Type0"
    assert capability.embedded is True
    assert capability.cid is not None
    decoded = capability.cid.decode_show_bytes(show.decoded_bytes)
    assert isinstance(decoded, str), decoded
    return decoded


def _resolve_cases(spec: CorpusSpec, doc: fitz.Document) -> tuple[CorpusCase, ...]:
    """Fill every hash-pinned ``original`` from the fixture's own show text."""
    registry = DocumentFontRegistry(doc)
    resolved: list[CorpusCase] = []
    for case in spec.cases:
        if case.original is None:
            show = _shows(doc, case.page_index)[case.show_seq]
            text = _decode_show(registry, doc[case.page_index], show)
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == case.original_sha256, (
                f"{spec.slug} p{case.page_index + 1}/show{case.show_seq}: target text changed"
            )
            case = replace(case, original=text)
        resolved.append(case)
    return tuple(resolved)


def _trace_for(page: fitz.Page, show: ShowOp, text: str) -> dict:
    expected = fitz.Point(show.origin_user) * page.transformation_matrix
    matches: list[dict] = []
    for trace in page.get_texttrace():
        full = "".join(chr(char[0]) for char in trace["chars"])
        start = full.find(text)
        while start >= 0:
            chars = trace["chars"][start : start + len(text)]
            rect = fitz.Rect(chars[0][3])
            for char in chars[1:]:
                rect |= fitz.Rect(char[3])
            matches.append(dict(trace, chars=chars, bbox=tuple(rect)))
            start = full.find(text, start + 1)
    assert matches, text
    match = min(
        matches,
        key=lambda candidate: abs(fitz.Point(candidate["chars"][0][2]) - expected),
    )
    assert abs(fitz.Point(match["chars"][0][2]) - expected) < 0.02
    return match


def _prepare(
    engine: TieredCommitEngine,
    doc: fitz.Document,
    case: CorpusCase,
) -> PreparedEdit | PlanRejection:
    assert case.original is not None
    page = doc[case.page_index]
    show = _shows(doc, case.page_index)[case.show_seq]
    registry = DocumentFontRegistry(doc)
    assert _decode_show(registry, page, show) == case.original
    trace = _trace_for(page, show, case.original)
    visual_origin = fitz.Point(trace["chars"][0][2]) * page.rotation_matrix
    visual_bbox = fitz.Rect(trace["bbox"]) * page.rotation_matrix
    return engine.prepare(
        page,
        target_text=case.original,
        replacement_text=case.replacement,
        expected_origin=tuple(visual_origin),
        target_bbox=tuple(visual_bbox),
    )


def _object_snapshot(doc: fitz.Document) -> tuple[tuple[str, str | bytes], ...]:
    return tuple(
        ("stream", doc.xref_stream(xref))
        if doc.xref_is_stream(xref)
        else ("object", doc.xref_object(xref))
        for xref in range(1, doc.xref_length())
    )


def _assert_only_target_streams_changed(
    before: tuple[tuple[str, str | bytes], ...],
    after: fitz.Document,
    changed_streams: set[int],
) -> None:
    assert after.xref_length() >= len(before) + 1
    for xref, original in enumerate(before, 1):
        current = (
            ("stream", after.xref_stream(xref))
            if after.xref_is_stream(xref)
            else ("object", after.xref_object(xref))
        )
        if xref in changed_streams:
            assert original[0] == current[0] == "stream"
            assert original[1] != current[1]
        else:
            assert current == original, f"non-target xref {xref} changed"


def _pixmap_array(page: fitz.Page, zoom: float = 2.0) -> np.ndarray:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )


def _assert_tj_compensation_is_last(
    prepared: PreparedEdit, expected: float
) -> None:
    written = prepared.replacement.replacement_bytes
    match = _TJ_WITH_TRAILING_COMPENSATION.fullmatch(written)
    assert match is not None, written
    assert float(match.group(2)) == pytest.approx(prepared.kern_adjustment, abs=1e-6)
    assert prepared.kern_adjustment == pytest.approx(expected, abs=1e-6)


def _assert_source_font_reused(
    source: fitz.Document,
    candidate: fitz.Document,
    case: CorpusCase,
    source_show: ShowOp,
    candidate_show: ShowOp,
) -> None:
    source_registry = DocumentFontRegistry(source)
    candidate_registry = DocumentFontRegistry(candidate)
    source_capability = source_registry.capability(
        source[case.page_index], source_show.font_resource
    )
    candidate_capability = candidate_registry.capability(
        candidate[case.page_index], candidate_show.font_resource
    )
    assert source_capability is not None and candidate_capability is not None
    assert source_show.font_resource == candidate_show.font_resource == case.font_resource
    assert source_capability.font_xref == candidate_capability.font_xref
    assert source_capability.basefont == candidate_capability.basefont == case.basefont
    assert source_capability.subtype == candidate_capability.subtype == "Type0"
    assert source_capability.embedded is candidate_capability.embedded is True
    assert source_capability.cid is not None and candidate_capability.cid is not None
    assert source.xref_object(source_capability.font_xref) == candidate.xref_object(
        candidate_capability.font_xref
    )
    assert _decode_show(
        candidate_registry, candidate[case.page_index], candidate_show
    ) == case.replacement


def test_production_engine_prepares_all_fourteen_real_type0_edits() -> None:
    """Red-first gate: report every current production refusal in one run."""
    refusals: list[str] = []
    prepared_count = 0
    for spec in CORPORA:
        path = _fixture(spec)
        with fitz.open(path) as doc:
            engine = TieredCommitEngine(doc, max_tier=1)
            for case in _resolve_cases(spec, doc):
                result = _prepare(engine, doc, case)
                if isinstance(result, PlanRejection):
                    refusals.append(
                        f"{spec.slug}/{case.label}: {result.reason}: {result.detail}"
                    )
                else:
                    prepared_count += 1
    assert prepared_count + len(refusals) == 14
    assert not refusals, "production engine refused real Type0 edits:\n" + "\n".join(
        refusals
    )


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

            _assert_only_target_streams_changed(
                source_snapshot, candidate, changed_streams
            )
            live_renders = {
                page_index: bytes(candidate[page_index].get_pixmap(alpha=False).samples)
                for page_index in {case.page_index for case in cases}
            }
            candidate.saveIncr()

        with fitz.open(candidate_path) as reopened:
            _assert_only_target_streams_changed(source_snapshot, reopened, changed_streams)
            for xref in range(len(source_snapshot) + 1, reopened.xref_length()):
                assert reopened.xref_get_key(xref, "Type") == ("name", "/XRef")

            for page_index, expected_samples in live_renders.items():
                assert bytes(reopened[page_index].get_pixmap(alpha=False).samples) == expected_samples

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

                mask = fitz.Rect(before_trace["bbox"]) | fitz.Rect(after_trace["bbox"])
                mask = mask * source[case.page_index].rotation_matrix
                masks.setdefault(case.page_index, []).append(mask + (-3, -3, 3, 3))
                edited_sequences.setdefault(case.page_index, set()).add(case.show_seq)

            for page_index, skipped in edited_sequences.items():
                before_page_shows = _shows(source, page_index)
                after_page_shows = _shows(reopened, page_index)
                assert len(after_page_shows) == len(before_page_shows)
                for before_show, after_show in zip(before_page_shows, after_page_shows):
                    if before_show.seq not in skipped:
                        assert after_show.origin_user == before_show.origin_user

            for page_index, page_masks in masks.items():
                before_pixels = _pixmap_array(source[page_index])
                after_pixels = _pixmap_array(reopened[page_index])
                assert before_pixels.shape == after_pixels.shape
                difference = np.any(before_pixels != after_pixels, axis=2)
                for mask in page_masks:
                    bounds = (mask * fitz.Matrix(2, 2)).irect
                    target = difference[
                        max(0, bounds.y0) : min(difference.shape[0], bounds.y1),
                        max(0, bounds.x0) : min(difference.shape[1], bounds.x1),
                    ]
                    assert np.any(target), (spec.slug, page_index, mask)
                    target[:] = False
                assert int(difference.sum()) == 0, (
                    spec.slug,
                    page_index,
                    "pixels changed outside target masks",
                )

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_digest
