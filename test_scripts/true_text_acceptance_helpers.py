"""Shared oracle code for the true-text acceptance suites (moved out of the real-corpus acceptance module).

Everything here is test-side and free of pytest and Qt: ``_fixture`` raises
:class:`FixtureUnavailable` (the acceptance module converts it to a skip), and the
page-geometry conversions go through the product's computed
:class:`~model.text_commit.transforms.PageVisualFrame` (``frame.base`` /
``frame.quarter_turn``), never the PyMuPDF page matrices, which drop the CropBox origin and
``/UserUnit`` on a rotated page (docs/PITFALLS.md).  Import it only as
``test_scripts.true_text_acceptance_helpers`` (``test_scripts`` is a namespace package, so one
dotted spelling keeps one module identity).
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import fitz
import numpy as np

from model.text_commit.cid_fonts import (
    PdfParseError,
    _tokenize,
    canonical_pdf_scalar,
)
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream
from model.text_commit.plan import PlanRejection, PreparedEdit
from model.text_commit.replay import ShowOp, replay_page_streams
from model.text_commit.transforms import PageVisualFrame, page_visual_frame_or_none
from model.text_commit.verify import _HALO_MARGIN_PT
from test_scripts.true_text_corpus import CorpusCase, CorpusSpec

ROOT = Path(__file__).resolve().parents[1]

#: The one raster scale of the pixel-mask checks: the MuPDF pixmaps, the mask matrix and the UI
#: umbrella's Poppler render (``72 * RENDER_ZOOM`` dpi) all share this pixel grid.
RENDER_ZOOM = 2.0
#: Raster slack of the pixel-mask checker, applied AFTER the pt -> px rounding.  The PDF-space halo is
#: the product's ``_HALO_MARGIN_PT``; Poppler's anti-aliasing lights pixels ~0.1 px beyond it where
#: MuPDF stays inside, so the checker tolerates exactly one extra pixel instead of a wider pt pad.
_MASK_SLACK_PX = 1

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


class FixtureUnavailable(Exception):
    """The optional local real-corpus fixture is not on this machine (the caller skips)."""


def _fixture(spec: CorpusSpec) -> Path:
    path = ROOT / spec.relative_path
    if not path.exists():
        raise FixtureUnavailable(f"missing optional real-corpus fixture: {spec.relative_path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == spec.sha256, (
        f"{spec.slug} fixture changed; reselect show sequences before accepting it: {digest}"
    )
    return path


def visual_frame(page: fitz.Page) -> PageVisualFrame:
    """``page``'s computed visual frame; an unprovable geometry is a test failure, never a fallback."""
    frame = page_visual_frame_or_none(page)
    assert frame is not None, "page geometry is unsupported"
    return frame


def _shows(doc: fitz.Document, page_index: int) -> tuple[ShowOp, ...]:
    page = doc[page_index]
    replay = replay_page_streams(
        [(xref, doc.xref_stream(xref)) for xref in page.get_contents()]
    )
    assert not replay.malformed, replay
    assert replay.refusal_reason is None, replay.refusal_reason
    return replay.shows


def decode_show(
    registry: DocumentFontRegistry,
    page: fitz.Page,
    show: ShowOp,
    *,
    font_kind: str = "type0",
) -> str:
    """The show's decoded text.  ``font_kind`` defaults to ``"type0"`` so the positional callers keep
    their fail-closed Type0 asserts; ``"simple"`` admits an embedded Type1/TrueType font or an
    unembedded base-14 one (an unembedded non-base-14 font would take a host ``system`` face, which
    would make acceptance machine-dependent)."""
    assert show.font_resource is not None
    capability = registry.capability(page, show.font_resource)
    assert capability is not None
    if font_kind == "type0":
        assert capability.subtype == "Type0"
        assert capability.embedded is True
        assert capability.cid is not None
        decoded = capability.cid.decode_show_bytes(show.decoded_bytes)
        assert isinstance(decoded, str), decoded
        return decoded
    assert font_kind == "simple", font_kind
    assert capability.subtype in ("Type1", "TrueType"), capability.subtype
    assert capability.embedded or capability.face_source == "base14", (
        capability.embedded,
        capability.face_source,
    )
    return show.decoded_bytes.decode("latin-1")


def can_encode_simple(capability: FontCapability, text: str) -> bool:
    """``True`` when the simple font can encode ``text`` (the product's own rule, not a re-derived range)."""
    return capability.encode_simple(text) is not None


def _trace_for(page: fitz.Page, show: ShowOp, text: str) -> dict:
    expected = fitz.Point(show.origin_user) * visual_frame(page).base
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
    frame = visual_frame(page)
    show = _shows(doc, case.page_index)[case.show_seq]
    registry = DocumentFontRegistry(doc)
    assert decode_show(registry, page, show, font_kind=case.font_kind) == case.original
    with _measurement_copy(doc) as measured:
        trace = _trace_for(measured[case.page_index], show, case.original)
    visual_origin = fitz.Point(trace["chars"][0][2]) * frame.quarter_turn
    visual_bbox = fitz.Rect(trace["bbox"]) * frame.quarter_turn
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


def _pixmap_array(page: fitz.Page, zoom: float = RENDER_ZOOM) -> np.ndarray:
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
    scale = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    height, width = difference.shape
    boxes = [(mask, (mask * scale).irect) for mask in page_masks]
    for mask, bounds in boxes:
        # Exactly the historic check: each mask must still hold a change of its own after the
        # earlier masks were cleared (order-dependent, as acc always was), and is then cleared.
        inside = difference[
            max(0, bounds.y0) : min(height, bounds.y1), max(0, bounds.x0) : min(width, bounds.x1)
        ]
        assert np.any(inside), (slug, page_index, mask)
        inside[:] = False
    for _mask, bounds in boxes:  # the slack is raster-level, after the pt -> px rounding
        difference[
            max(0, bounds.y0 - _MASK_SLACK_PX) : min(height, bounds.y1 + _MASK_SLACK_PX),
            max(0, bounds.x0 - _MASK_SLACK_PX) : min(width, bounds.x1 + _MASK_SLACK_PX),
        ] = False
    assert int(difference.sum()) == 0, (
        slug,
        page_index,
        "pixels changed outside target masks",
    )


def halo_mask(
    before_bbox: tuple[float, float, float, float] | fitz.Rect,
    after_bbox: tuple[float, float, float, float] | fitz.Rect,
    frame: PageVisualFrame,
) -> fitz.Rect:
    """The visual-space mask of one edit: the union of the before and after texttrace boxes
    (page-space metric boxes) turned through ``frame.quarter_turn`` and padded by the product's
    ``_HALO_MARGIN_PT``.  The only place the acceptance suites build this mask."""
    box = (fitz.Rect(before_bbox) | fitz.Rect(after_bbox)) * frame.quarter_turn
    return box + (-_HALO_MARGIN_PT, -_HALO_MARGIN_PT, _HALO_MARGIN_PT, _HALO_MARGIN_PT)


def _assert_tj_compensation_is_last(prepared: PreparedEdit, expected: float) -> None:
    """The Tier 1 payload is exactly one fresh ``[<string> <number>] TJ`` whose number is the kern.

    Lexed with the production lexer (whitespace dropped, a comment fails): ARRAY_OPEN, one STRING or
    HEXSTRING item, one NUMBER, ARRAY_CLOSE, OPERATOR ``TJ``, in that order and nothing else.
    """
    written = prepared.replacement.replacement_bytes
    tokens = [token for token in lex_content_stream(written) if token.kind is not TokenKind.WHITESPACE]
    assert all(token.kind is not TokenKind.COMMENT for token in tokens), written
    kinds = [token.kind for token in tokens]
    assert len(kinds) == 5 and (
        kinds[0] is TokenKind.ARRAY_OPEN
        and kinds[1] in (TokenKind.STRING, TokenKind.HEXSTRING)
        and kinds[2] is TokenKind.NUMBER
        and kinds[3] is TokenKind.ARRAY_CLOSE
        and kinds[4] is TokenKind.OPERATOR
    ), (kinds, written)
    assert written[tokens[4].start : tokens[4].end] == b"TJ", written
    kern = float(written[tokens[2].start : tokens[2].end])
    assert math.isclose(kern, prepared.kern_adjustment, abs_tol=1e-6, rel_tol=0.0), (
        kern,
        prepared.kern_adjustment,
    )
    assert math.isclose(prepared.kern_adjustment, expected, abs_tol=1e-6, rel_tol=0.0), (
        prepared.kern_adjustment,
        expected,
    )


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
    if case.font_kind == "type0":
        assert source_capability.subtype == candidate_capability.subtype == "Type0"
        assert source_capability.embedded is candidate_capability.embedded is True
        assert source_capability.cid is not None and candidate_capability.cid is not None
    assert source.xref_object(source_capability.font_xref) == candidate.xref_object(
        candidate_capability.font_xref
    )
    assert decode_show(
        candidate_registry,
        candidate[case.page_index],
        candidate_show,
        font_kind=case.font_kind,
    ) == case.replacement
