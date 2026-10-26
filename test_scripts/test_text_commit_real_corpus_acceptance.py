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

from model.text_commit.cid_fonts import (  # noqa: E402
    PdfParseError,
    _tokenize,
    canonical_pdf_scalar,
)
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402
from model.text_commit.replay import ShowOp, replay_page_streams  # noqa: E402
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


def _measurement_copy(doc: fitz.Document) -> fitz.Document:
    """Independent copy of ``doc``'s current state for extraction-only calls.

    On a /Rotate page PyMuPDF's ``get_texttrace()`` (like ``get_textpage`` and
    ``get_cdrawings``) toggles /Rotate to 0 and back, which marks the /Page
    object dirty: ``saveIncr`` then rewrites it with reordered keys.  The
    harness must not mutate the document it judges, so it extracts here.
    """
    return fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))


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
    with _measurement_copy(doc) as measured:
        trace = _trace_for(measured[case.page_index], show, case.original)
    visual_origin = fitz.Point(trace["chars"][0][2]) * page.rotation_matrix
    visual_bbox = fitz.Rect(trace["bbox"]) * page.rotation_matrix
    return engine.prepare(
        page,
        target_text=case.original,
        replacement_text=case.replacement,
        expected_origin=tuple(visual_origin),
        target_bbox=tuple(visual_bbox),
    )


def _object_entry(doc: fitz.Document, xref: int) -> tuple[str, str | bytes]:
    if doc.xref_is_stream(xref):
        return ("stream", doc.xref_stream(xref))
    return ("object", doc.xref_object(xref))


def _object_snapshot(doc: fitz.Document) -> tuple[tuple[str, str | bytes], ...]:
    return tuple(_object_entry(doc, xref) for xref in range(1, doc.xref_length()))


_SEMANTIC_MAX_DEPTH = 32


def _semantic_value(tokens: list[bytes], pos: int, depth: int) -> tuple[object, int]:
    """One PDF value as a comparable tree; ONLY dictionary key order is dropped.

    Tokens come from the production bounded tokenizer.  Unlike the production
    ``parse_pdf_value`` tree (reals as lossy ``float``, the reference
    generation dropped, literal and hex strings both folded to ``bytes``),
    everything here stays exact: names and literal strings by raw token,
    hex strings by their bytes, references as ``(xref, generation)``, arrays
    in order, and numbers through ``canonical_pdf_scalar`` -- exact decimal
    text, where only the int/real kind of the same value folds (plan §2.A).
    """
    if depth > _SEMANTIC_MAX_DEPTH:
        raise PdfParseError("object nesting over the depth budget")
    if pos >= len(tokens):
        raise PdfParseError("truncated object")
    token = tokens[pos]
    if (
        token.isdigit()
        and pos + 2 < len(tokens)
        and tokens[pos + 1].isdigit()
        and tokens[pos + 2] == b"R"
    ):
        return ("ref", int(token), int(tokens[pos + 1])), pos + 3
    if token == b"<<":
        entries: dict[bytes, object] = {}
        pos += 1
        while pos < len(tokens) and tokens[pos] != b">>":
            key = tokens[pos]
            if not key.startswith(b"/"):
                raise PdfParseError("dictionary key is not a name")
            if key in entries:
                raise PdfParseError("duplicate dictionary key")
            entries[key], pos = _semantic_value(tokens, pos + 1, depth + 1)
        if pos >= len(tokens):
            raise PdfParseError("unterminated dictionary")
        return ("dict", tuple(sorted(entries.items(), key=lambda kv: kv[0]))), pos + 1
    if token == b"[":
        items: list[object] = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != b"]":
            item, pos = _semantic_value(tokens, pos, depth + 1)
            items.append(item)
        if pos >= len(tokens):
            raise PdfParseError("unterminated array")
        return ("array", tuple(items)), pos + 1
    if token.startswith(b"/"):
        return ("name", token), pos + 1
    if token.startswith(b"("):
        return ("literal", token), pos + 1
    if token.startswith(b"<"):
        digits = bytes(c for c in token[1:-1] if not bytes((c,)).isspace())
        if len(digits) % 2:
            digits += b"0"
        return ("hex", bytes.fromhex(digits.decode("ascii"))), pos + 1
    if token in (b"true", b"false", b"null"):
        return ("keyword", token), pos + 1
    if token == b"R":
        raise PdfParseError("stray R outside an indirect reference")
    text = token.decode("ascii")
    return canonical_pdf_scalar("float" if "." in text else "int", text), pos + 1


def _objects_semantically_equal(original: str, current: str) -> bool:
    """Same parsed PDF value up to dictionary key order; any parse failure is unequal."""
    if original == current:
        return True
    try:
        trees = []
        for text in (original, current):
            tokens = _tokenize(text.encode("utf-8"))
            tree, end = _semantic_value(tokens, 0, 0)
            if end != len(tokens):
                return False
            trees.append(tree)
    except (PdfParseError, UnicodeError, ValueError):
        return False
    return trees[0] == trees[1]


def _assert_only_target_streams_changed(
    before: tuple[tuple[str, str | bytes], ...],
    after: fitz.Document,
    changed_streams: set[int],
    *,
    semantic: bool = False,
) -> None:
    """Every non-target xref unchanged; target streams changed.

    ``semantic=False`` compares serialized object text exactly.
    ``semantic=True`` (save/reopen, plan §4) compares non-stream objects by
    parsed value ignoring only dictionary key order; streams always compare
    by decoded bytes.
    """
    assert after.xref_length() >= len(before) + 1
    for xref, original in enumerate(before, 1):
        current = _object_entry(after, xref)
        if xref in changed_streams:
            assert original[0] == current[0] == "stream"
            assert original[1] != current[1]
        elif semantic and original[0] == current[0] == "object":
            assert isinstance(original[1], str) and isinstance(current[1], str)
            assert _objects_semantically_equal(original[1], current[1]), (
                f"non-target xref {xref} changed"
            )
        else:
            assert current == original, f"non-target xref {xref} changed"


def _pixmap_array(page: fitz.Page, zoom: float = 2.0) -> np.ndarray:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )


def _assert_reopened_renders_match_live(
    live_renders: dict[int, bytes], reopened: fitz.Document
) -> None:
    for page_index, expected_samples in live_renders.items():
        assert bytes(reopened[page_index].get_pixmap(alpha=False).samples) == expected_samples


def _assert_pixels_changed_only_inside_masks(
    slug: str,
    page_index: int,
    before_pixels: np.ndarray,
    after_pixels: np.ndarray,
    page_masks: list[fitz.Rect],
) -> None:
    assert before_pixels.shape == after_pixels.shape
    difference = np.any(before_pixels != after_pixels, axis=2)
    for mask in page_masks:
        bounds = (mask * fitz.Matrix(2, 2)).irect
        target = difference[
            max(0, bounds.y0) : min(difference.shape[0], bounds.y1),
            max(0, bounds.x0) : min(difference.shape[1], bounds.x1),
        ]
        assert np.any(target), (slug, page_index, mask)
        target[:] = False
    assert int(difference.sum()) == 0, (
        slug,
        page_index,
        "pixels changed outside target masks",
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
                _assert_pixels_changed_only_inside_masks(
                    spec.slug,
                    page_index,
                    _pixmap_array(source[page_index]),
                    _pixmap_array(reopened[page_index]),
                    page_masks,
                )

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_digest
