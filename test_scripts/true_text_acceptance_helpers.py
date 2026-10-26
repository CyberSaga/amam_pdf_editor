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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from io import BytesIO
from pathlib import Path

import fitz
import numpy as np
from fontTools.agl import UV2AGL, toUnicode
from fontTools.encodings.MacRoman import MacRoman
from fontTools.encodings.StandardEncoding import StandardEncoding
from fontTools.ttLib import TTFont

from model.text_commit.cid_fonts import (
    PdfParseError,
    _tokenize,
    canonical_pdf_scalar,
    read_embedded_font_program,
)
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import (
    _BASE14_ALIASES,
    _SIMPLE_SUBTYPES,
    DocumentFontRegistry,
    FontCapability,
    _is_symbolic,
    page_scoped_font_entry,
)
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream
from model.text_commit import transforms, verify
from model.text_commit.plan import PlanRejection, PreparedEdit
from model.text_commit.replay import PageReplay, ShowOp, replay_page_streams
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


# ----------------------------------------------------------------------------------------------
# S3a: the growth-zone oracle and the neighbour-glyph oracle
# ----------------------------------------------------------------------------------------------
def _box4(box: Sequence[float]) -> tuple[float, float, float, float]:
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def growth_zone_checks(
    source_doc: fitz.Document,
    page_index: int,
    show: ShowOp,
    frame: PageVisualFrame,
    target_bbox_visual: Sequence[float],
    verify_bbox_visual: Sequence[float],
    adv_old: float,
    *,
    prepared: PreparedEdit | None,
    x_pre: float | None,
    k_inner: float | None,
) -> tuple[int, str | None]:
    """``(glyphs already in the growth zone, raster/occupancy failure detail or None)`` from the product gates.

    Moved verbatim from ``scripts/evidence_rederive.py`` ``_growth_checks`` (which is now a thin
    ``OracleContext`` wrapper over this): always judged on a copy of ``source_doc``, the PRE-edit state.
    ``prepared`` is the product's own prepared edit (its page state and metric quad are used) or ``None``
    for an experiment, where the core builds a 96 dpi page state holding only the pixmap.  The detail is the
    product's raw string; the caller decides how to sanitise it.  A ``None`` slice term raises
    ``ValueError`` (after the glyph count), which the caller turns into ``oracle raised ValueError``.
    """
    target, grown = _box4(target_bbox_visual), _box4(verify_bbox_visual)
    meas = fitz.open("pdf", source_doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
    try:
        page = meas[page_index]
        glyphs = verify.count_growth_zone_glyphs(page, target_bbox=target, verify_bbox=grown)
        if x_pre is None or k_inner is None:
            raise ValueError("the slice origin is not provable")
        quad = transforms.map_text_quad_to_visual(
            page,
            show.tm,
            show.ctm,
            # the product computes ``source_advance * th`` with ``th = hscale / 100`` (plan.py _build_tier1): the other
            # association order differs in the last bit for about a third of the non-identity Tz values, and the
            # comparison below is exact on purpose
            # the slice origin x_pre is 0.0 for a whole-show target (Q10); k_inner shortens the width by the kerns
            # between the target's items (Q11)
            (
                x_pre * (show.hscale / 100.0),
                -0.35 * show.font_size,
                (x_pre + adv_old - k_inner / 1000.0 * show.font_size) * (show.hscale / 100.0),
                show.font_size,
            ),
            frame=frame,
        )
        if prepared is not None:
            state = verify.capture_page_state(meas, page, prepared)
            if prepared.background_bbox_page is not None and any(
                abs(a - b) > 0.0 for a, b in zip(prepared.background_bbox_page, quad, strict=True)
            ):
                return glyphs, "background: the prepared quad differs from the metric quad"
        else:
            pix = page.get_pixmap(dpi=verify._VERIFY_DPI)
            state = verify.PageState(
                streams=(),
                fonts=(),
                annots=(),
                nontarget_origins=(),
                pixmap_samples=bytes(pix.samples),
                pixmap_meta=(pix.width, pix.height, pix.stride, pix.n),
            )
        failure = verify._growth_probe_failure(
            state, target_bbox=target, verify_bbox=grown, background_bbox=quad, page=page, doc=meas
        )
        return glyphs, None if failure is None else getattr(failure, "detail", "growth probe failed")
    finally:
        meas.close()


def check_growth_zone_was_blank(
    source_doc: fitz.Document,
    page_index: int,
    show: ShowOp,
    frame: PageVisualFrame,
    target_bbox_visual: Sequence[float],
    verify_bbox_visual: Sequence[float],
    adv_old: float,
    *,
    prepared: PreparedEdit | None,
    x_pre: float | None,
    k_inner: float | None,
) -> str | None:
    """The product's growth gates, read-only: ``None`` = blank or not applicable, else a detail.

    Not applicable (``None``) when ``verify_bbox_visual == target_bbox_visual`` (shrink or equal advance).
    The detail strings are rederive's own: ``oracle raised <Type>``, ``glyphs: <n> character(s) already
    occupy the growth zone``, or the product's raster/occupancy/background detail."""
    if tuple(verify_bbox_visual) == tuple(target_bbox_visual):
        return None  # shrink or equal advance: no growth zone
    try:
        glyphs, failure = growth_zone_checks(
            source_doc,
            page_index,
            show,
            frame,
            target_bbox_visual,
            verify_bbox_visual,
            adv_old,
            prepared=prepared,
            x_pre=x_pre,
            k_inner=k_inner,
        )
    except Exception as exc:  # noqa: BLE001 - an oracle that cannot run does not pass
        return f"oracle raised {type(exc).__name__}"
    if glyphs:
        return f"glyphs: {glyphs} character(s) already occupy the growth zone"
    return failure


def assert_growth_zone_was_blank(*args, **kwargs) -> None:
    assert (detail := check_growth_zone_was_blank(*args, **kwargs)) is None, detail


@dataclass(frozen=True)
class EditedShow:
    """One edited show for the neighbour pairing.  Code units: Identity-H 2 bytes, simple 1 byte."""

    show_seq: int
    before_show: ShowOp
    after_show: ShowOp
    n_old: int
    n_new: int
    pre: int = 0
    post: int = 0


def edited_show(
    before_show: ShowOp, after_show: ShowOp, *, code_bytes: int, pre: int = 0, post: int = 0
) -> EditedShow:
    assert before_show.seq == after_show.seq, (before_show.seq, after_show.seq)
    for show in (before_show, after_show):
        assert len(show.decoded_bytes) % code_bytes == 0, (show.seq, code_bytes)
    n_old = len(before_show.decoded_bytes) // code_bytes - pre - post
    n_new = len(after_show.decoded_bytes) // code_bytes - pre - post
    assert n_old >= 0 and n_new >= 0, (n_old, n_new)
    return EditedShow(before_show.seq, before_show, after_show, n_old, n_new, pre, post)


_NEIGHBOUR_KINDS = ("positive", "control", "canary", "negative", "census")
#: the kinds whose rows are judged for overprinting (an ``overlap:`` leg failure)
_OVERLAP_JUDGED_KINDS = ("positive", "control", "canary")
#: a located show's first glyph origin must lie within this of the show's computed origin (base space)
_LOCATE_TOL_PT = 0.02
#: zoom of the ink-landed crops (display-list renders of a third copy, never the 2x page renders)
_INK_ZOOM = 6.0


@dataclass(frozen=True)
class _TraceGlyph:
    ucs: int
    gid: int
    origin: tuple[float, float]
    bbox: tuple[float, float, float, float]
    direction: tuple[float, float]

    @property
    def is_space(self) -> bool:
        return self.ucs > 0 and chr(self.ucs).isspace()


@dataclass(frozen=True)
class _Run:
    """One located emission of an edited show: before start ``b``, after start ``a`` (flat glyph indices)."""

    index: int
    b: int
    a: int
    pre: int
    n_old: int
    n_new: int
    post: int

    @property
    def target_before(self) -> range:
        return range(self.b + self.pre, self.b + self.pre + self.n_old)

    @property
    def target_after(self) -> range:
        return range(self.a + self.pre, self.a + self.pre + self.n_new)

    @property
    def successors_before(self) -> range:
        return range(self.b + self.pre + self.n_old, self.b + self.pre + self.n_old + self.post)


def _flatten_trace(page: fitz.Page) -> list[_TraceGlyph]:
    """The page's texttrace items in order, gid -1 (ToUnicode continuation) items dropped, span boundaries ignored.

    Geometry is ``frame.base`` space (unrotated, y down, CropBox flip and ``/UserUnit`` applied)."""
    glyphs: list[_TraceGlyph] = []
    for span in page.get_texttrace():
        direction = (float(span["dir"][0]), float(span["dir"][1]))
        for ucs, gid, origin, bbox in span["chars"]:
            if gid < 0:
                continue
            glyphs.append(
                _TraceGlyph(
                    int(ucs),
                    int(gid),
                    (float(origin[0]), float(origin[1])),
                    (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    direction,
                )
            )
    return glyphs


def _emissions(
    flat: list[_TraceGlyph],
    shows: Sequence[ShowOp],
    show: ShowOp,
    frame: PageVisualFrame,
    length: int,
) -> list[int] | str:
    """Flat indices of the emissions of ``show`` (one per emission, normally one), or a ``pairing:`` reason.

    Every glyph whose origin is the show's computed first origin is a candidate, but a candidate belongs to
    the SHOW that draws it: the page's shows whose own origin coincides (fill+stroke copies, shadow text)
    each own ``emissions`` consecutive candidates, in seq order, and ``show`` takes its own group.  A
    candidate count that is not a whole multiple of the coincident shows (a Form XObject glyph at that
    origin, say), or an emission group whose glyphs differ in content, is a pairing failure: the glyphs of
    the OTHER coincident shows stay paired neighbours and never disappear into the target set."""
    expected = fitz.Point(show.origin_user) * frame.base
    seqs = sorted(
        other.seq
        for other in shows
        if other.origin_reliable  # an unreliable origin (a pending advance) says nothing about where the glyphs are
        and abs(fitz.Point(other.origin_user) * frame.base - expected) < _LOCATE_TOL_PT
    )
    if show.seq not in seqs:
        return "the edited show is not among the shows at its own origin"
    candidates = [
        index for index, glyph in enumerate(flat) if abs(fitz.Point(glyph.origin) - expected) < _LOCATE_TOL_PT
    ]
    if not candidates:
        return "not located"
    if len(candidates) % len(seqs):
        return f"{len(candidates)} glyph origins coincide for {len(seqs)} show(s)"
    per_show = len(candidates) // len(seqs)
    position = seqs.index(show.seq)
    group = candidates[position * per_show : (position + 1) * per_show]
    if any(index + length > len(flat) for index in group):
        return "not located"
    shapes = {tuple(glyph.gid for glyph in flat[index : index + length]) for index in group}
    if len(shapes) != 1:
        return "the emissions of the show differ in content"
    return group


def _union(boxes: Sequence[Sequence[float]]) -> fitz.Rect | None:
    rect: fitz.Rect | None = None
    for box in boxes:
        rect = fitz.Rect(box) if rect is None else rect | fitz.Rect(box)
    return rect


def _positive_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    """Positive-area intersection (touching edges do not count; ``evidence_bundle._bbox_intersects``)."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _locate_runs(
    flat_before: list[_TraceGlyph],
    flat_after: list[_TraceGlyph],
    shows_before: Sequence[ShowOp],
    shows_after: Sequence[ShowOp],
    edited: Sequence[EditedShow],
    frame: PageVisualFrame,
) -> list[_Run] | str:
    """The sorted, aligned runs, or a ``pairing:`` detail."""
    runs: list[_Run] = []
    for index, item in enumerate(edited):
        before = _emissions(flat_before, shows_before, item.before_show, frame, item.pre + item.n_old + item.post)
        if isinstance(before, str):
            return f"pairing: edited show {index} (before): {before}"
        after = _emissions(flat_after, shows_after, item.after_show, frame, item.pre + item.n_new + item.post)
        if isinstance(after, str):
            return f"pairing: edited show {index} (after): {after}"
        if len(before) != len(after):
            return f"pairing: edited show {index} emissions differ ({len(before)} before, {len(after)} after)"
        runs.extend(
            _Run(index, b, a, item.pre, item.n_old, item.n_new, item.post)
            for b, a in zip(before, after, strict=True)
        )
    runs.sort(key=lambda run: run.b)
    shift = 0
    previous_end = 0
    for position, run in enumerate(runs):
        if run.b < previous_end:
            return f"pairing: edited segments {position - 1} and {position} overlap"
        if run.a != run.b + shift:
            return f"pairing: edited run {position} starts at {run.a} after, expected {run.b + shift}"
        shift += run.n_new - run.n_old
        previous_end = run.b + run.pre + run.n_old + run.post
    if len(flat_after) != len(flat_before) + shift:
        return f"pairing: {len(flat_before)} glyphs before and {len(flat_after)} after, expected {len(flat_before) + shift}"
    return runs


def _ink_pixels(display_list, rect: fitz.Rect) -> int:
    """Pixels of the 6x crop of ``rect`` that differ from its most common colour (0 for an empty crop)."""
    if rect.is_empty or rect.is_infinite:
        return 0
    pixmap = display_list.get_pixmap(matrix=fitz.Matrix(_INK_ZOOM, _INK_ZOOM), clip=rect, alpha=False)
    rows = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(-1, pixmap.n)
    total = rows.shape[0]
    if total == 0:
        return 0
    counts = np.unique(rows, axis=0, return_counts=True)[1]
    return int(total - counts.max())


def _px_box(box: Sequence[float], frame: PageVisualFrame, shape: tuple[int, ...]) -> fitz.IRect:
    pixel = (fitz.Rect(box) * frame.quarter_turn * fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)).irect
    return fitz.IRect(
        max(0, pixel.x0), max(0, pixel.y0), min(shape[1], pixel.x1), min(shape[0], pixel.y1)
    )


def check_neighbour_glyphs_unchanged(
    source: fitz.Document,
    reopened: fitz.Document,
    page_index: int,
    edited: Sequence[EditedShow],
    *,
    kind: str,
    frame: PageVisualFrame,
    inshow_tolerance: float = 1e-6,
    inshow_residual_pt: float = 0.0,
    halo_pt: float = _HALO_MARGIN_PT,
    measurements: dict | None = None,
) -> str | None:
    """Every glyph the edit did not target is where and what it was; the new glyphs landed ink.

    ``None`` = pass, else ``"neighbours: " + "; ".join(parts)`` (ASCII counts, indices and numbers only: never
    text, ``ucs`` or a font name).  The pairing flattens the texttrace of ``source`` and ``reopened`` (gid -1
    continuation items dropped) and aligns the edited runs by the shows' computed origins; legs, each reported
    when it fails: ``target_moved`` (the first target glyph's origin, exact), ``untouched_moved`` (every other
    glyph, exact), ``inshow_moved`` (successors inside an edited show, along/perpendicular to the baseline, within
    ``inshow_tolerance`` of ``inshow_residual_pt``), ``gid_mismatch``, ``overlap`` (a non-target glyph box
    overlapping the new glyphs; judged for positive, control and canary rows), ``ink_changed`` (a 2x render
    differs inside a non-target glyph box outside the target halo, one pixel of slack) and ``ink_not_landed``
    (a non-space new glyph whose 6x crop holds no pixel off its mode colour)."""
    if kind not in _NEIGHBOUR_KINDS:
        raise ValueError(f"unknown row kind {kind!r}")
    if not edited:
        raise ValueError("no edited show given")
    if any(not item.before_show.origin_reliable for item in edited):
        return "neighbours: pairing: edited show origin not reliable"
    # three measurement copies (``_measurement_copy``: a texttrace toggles /Rotate and dirties the page, so the
    # judged documents are never extracted from); render first, texttrace after, the 6x crops on their own copy
    with _measurement_copy(source) as copy_before, _measurement_copy(reopened) as copy_after, _measurement_copy(
        reopened
    ) as copy_crops:
        pixels_before = _pixmap_array(copy_before[page_index])
        pixels_after = _pixmap_array(copy_after[page_index])
        if pixels_before.shape != pixels_after.shape:
            return "neighbours: frame: raster size changed"
        after_frame = visual_frame(copy_after[page_index])
        if tuple(after_frame.base) != tuple(frame.base) or tuple(after_frame.quarter_turn) != tuple(
            frame.quarter_turn
        ):
            return "neighbours: frame: page geometry changed"
        flat_before = _flatten_trace(copy_before[page_index])
        flat_after = _flatten_trace(copy_after[page_index])
        located = _locate_runs(
            flat_before,
            flat_after,
            _shows(source, page_index),
            _shows(reopened, page_index),
            edited,
            frame,
        )
        if isinstance(located, str):
            return f"neighbours: {located}"
        runs = located
        parts: list[str] = []

        # the pairing: before index -> (after index, role) for every glyph outside the target ranges
        target_before = {index for run in runs for index in run.target_before}
        inshow = {index for run in runs for index in run.successors_before}
        ends = [(run.b + run.pre + run.n_old, run.n_new - run.n_old) for run in runs]
        paired: list[tuple[int, int, str]] = []
        for before_index in range(len(flat_before)):
            if before_index in target_before:
                continue
            after_index = before_index + sum(delta for end, delta in ends if end <= before_index)
            paired.append((before_index, after_index, "inshow" if before_index in inshow else "untouched"))
        target_after_all = [index for run in runs for index in run.target_after]
        paired_after = {after_index for _, after_index, _ in paired}
        assert paired_after.isdisjoint(target_after_all) and len(paired_after) + len(target_after_all) == len(
            flat_after
        )

        # target_moved: the first target glyph of each run keeps the origin exactly
        moved_targets = [
            math.dist(flat_before[run.b + run.pre].origin, flat_after[run.a + run.pre].origin)
            for run in runs
            if run.n_old >= 1
            and run.n_new >= 1
            and tuple(flat_before[run.b + run.pre].origin) != tuple(flat_after[run.a + run.pre].origin)
        ]
        if moved_targets:
            parts.append(f"target_moved: {len(moved_targets)} run(s), max {max(moved_targets):.3g} pt")

        # untouched_moved / inshow_moved / gid_mismatch
        untouched_devs: list[float] = []
        inshow_bad = 0
        max_untouched = 0.0
        max_inshow = 0.0
        gid_bad = 0
        for before_index, after_index, role in paired:
            glyph_before, glyph_after = flat_before[before_index], flat_after[after_index]
            if glyph_before.gid != glyph_after.gid:
                gid_bad += 1
            delta_x = glyph_after.origin[0] - glyph_before.origin[0]
            delta_y = glyph_after.origin[1] - glyph_before.origin[1]
            if role == "untouched":
                deviation = math.hypot(delta_x, delta_y)
                max_untouched = max(max_untouched, deviation)
                if tuple(glyph_after.origin) != tuple(glyph_before.origin):
                    untouched_devs.append(deviation)
            else:
                dir_x, dir_y = glyph_before.direction
                along = delta_x * dir_x + delta_y * dir_y
                across = delta_x * dir_y - delta_y * dir_x
                deviation = max(abs(along - inshow_residual_pt), abs(across))
                max_inshow = max(max_inshow, deviation)
                if deviation > inshow_tolerance:
                    inshow_bad += 1
        if untouched_devs:
            parts.append(f"untouched_moved: {len(untouched_devs)} glyph(s), max {max(untouched_devs):.3g} pt")
        if inshow_bad:
            parts.append(f"inshow_moved: {inshow_bad} glyph(s), max {max_inshow:.3g} pt")
        if gid_bad:
            parts.append(f"gid_mismatch: {gid_bad} glyph(s)")

        # overlap: a non-space non-target glyph box overlapping a run's new glyphs (positive area)
        after_unions = [
            union
            for run in runs
            if (union := _union([flat_after[index].bbox for index in run.target_after])) is not None
        ]
        overlap = sum(
            1
            for _, after_index, _ in paired
            if not flat_after[after_index].is_space
            and any(_positive_overlap(flat_after[after_index].bbox, tuple(union)) for union in after_unions)
        )
        if overlap and kind in _OVERLAP_JUDGED_KINDS:
            parts.append(f"overlap: {overlap} glyph(s)")

        # ink_changed: the 2x renders differ inside a non-target glyph box outside the target halos
        difference = np.any(pixels_before != pixels_after, axis=2)
        ink_changed = 0
        if difference.any():
            halos: list[fitz.IRect] = []
            for run in runs:
                union = _union(
                    [flat_before[index].bbox for index in run.target_before]
                    + [flat_after[index].bbox for index in run.target_after]
                )
                if union is None:
                    continue
                halo = union * frame.quarter_turn + (-halo_pt, -halo_pt, halo_pt, halo_pt)
                pixel = (halo * fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)).irect
                halos.append(
                    fitz.IRect(
                        pixel.x0 - _MASK_SLACK_PX,
                        pixel.y0 - _MASK_SLACK_PX,
                        pixel.x1 + _MASK_SLACK_PX,
                        pixel.y1 + _MASK_SLACK_PX,
                    )
                )
            for before_index, _, _ in paired:
                box = _px_box(flat_before[before_index].bbox, frame, difference.shape)
                if box.is_empty:
                    continue
                region = difference[box.y0 : box.y1, box.x0 : box.x1].copy()
                if not region.any():
                    continue
                for halo in halos:
                    y0, y1 = max(halo.y0, box.y0), min(halo.y1, box.y1)
                    x0, x1 = max(halo.x0, box.x0), min(halo.x1, box.x1)
                    if y0 < y1 and x0 < x1:
                        region[y0 - box.y0 : y1 - box.y0, x0 - box.x0 : x1 - box.x0] = False
                if region.any():
                    ink_changed += 1
        if ink_changed:
            parts.append(f"ink_changed: {ink_changed} glyph(s)")

        # ink_not_landed: every non-space new glyph holds ink in its box (6x crop on a third copy)
        display_list = copy_crops[page_index].get_displaylist(annots=True)
        ink_counts: list[int] = []
        for index in target_after_all:
            glyph = flat_after[index]
            if glyph.is_space:
                continue
            ink_counts.append(_ink_pixels(display_list, fitz.Rect(glyph.bbox) * frame.quarter_turn))
        ink_missing = sum(1 for count in ink_counts if count == 0)
        if ink_missing:
            parts.append(f"ink_not_landed: {ink_missing} of {len(ink_counts)} glyph(s)")

        if measurements is not None:
            measurements.update(
                glyphs_paired=len(paired),
                target_glyphs_before=sum(run.n_old for run in runs),
                target_glyphs_after=sum(run.n_new for run in runs),
                target_glyphs_ink_checked=len(ink_counts),
                max_untouched_dev=max_untouched,
                max_inshow_dev=max_inshow,
                overlap_glyphs=overlap,
                min_ink_after_px_6x=min(ink_counts) if ink_counts else None,
            )
    return "neighbours: " + "; ".join(parts) if parts else None


def assert_neighbour_glyphs_unchanged(*args, **kwargs) -> None:
    assert (detail := check_neighbour_glyphs_unchanged(*args, **kwargs)) is None, detail


def q12_inshow_residual_pt(
    old_widths: Sequence[float | None],
    new_widths: Sequence[float | None],
    *,
    font_size: float,
    hscale: float,
    trm_scale: float,
    user_unit: float,
) -> float:
    """The in-show successor shift the half-up integerisation of fractional ``/Widths`` leaves, in points.

    MuPDF reads each width as a float32 and rounds it half UP: ``r(w) = floor(float32(w) + 0.5) - w`` is the
    per-glyph error in width units; the successors move by ``(sum r over the new glyphs - sum r over the old
    ones)`` units of ``Tfs * Tz * trm_scale * user_unit / 1000`` pt (texttrace deltas are base space, which
    carries ``/UserUnit``).  A ``None`` width (not provable) raises ``ValueError``.  The Type0 ``/W`` residual
    is NOT established by this formula (S4 pins it)."""

    def residual(width: float | None) -> float:
        if width is None:
            raise ValueError("a glyph width is not provable")
        return math.floor(float(np.float32(width)) + 0.5) - width

    units = sum(residual(w) for w in new_widths) - sum(residual(w) for w in old_widths)
    return units * font_size * (hscale / 100.0) * trm_scale * user_unit / 1000.0


# ----------------------------------------------------------------------------------------------
# S3b: byte-range, wrapper, count and glyph-identity helpers
# ----------------------------------------------------------------------------------------------
def page_streams(doc: fitz.Document, page_index: int) -> list[tuple[int, bytes]]:
    """``[(xref, decoded bytes)]`` of the page's content streams, in ``/Contents`` order."""
    return [(xref, doc.xref_stream(xref) or b"") for xref in doc[page_index].get_contents()]


def _first_difference(left: bytes, right: bytes) -> int:
    """Index of the first unequal byte, or the length of the shorter side when one is a prefix of the other."""
    common = min(len(left), len(right))
    if left[:common] == right[:common]:
        return common
    low, high = 0, common  # left[:low] == right[:low] and left[:high] != right[:high]
    while high - low > 1:
        middle = (low + high) // 2
        if left[low:middle] == right[low:middle]:
            low = middle
        else:
            high = middle
    return low


def check_target_stream_changed_only_within(
    before: bytes, after: bytes, ranges: Sequence[tuple[int, int, int]]
) -> str | None:
    """Every byte of the stream outside the declared edits is unchanged (the shift rule of rederive's replay).

    Each range is ``(start, end_old, end_new)``: ``start`` and ``end_old`` in ``before`` coordinates,
    ``end_new`` in ``after`` coordinates (``start + shift_so_far + new_length``), so a later range sits in the
    earlier ranges' shifted suffix.  Compared: the prefix, every gap between ranges, the suffix and the total
    length; the changed middles themselves are not.  ``None`` = pass, else ``"stream_range: "`` + the failed
    legs, each with the before-coordinate offset of its first differing byte.  Bad ranges (empty, out of
    bounds, overlapping) are a caller bug: ``ValueError``."""
    if not ranges:
        raise ValueError("no ranges given")
    ordered = sorted(ranges, key=lambda item: item[0])
    previous_end = 0
    for start, end_old, _end_new in ordered:
        if not 0 <= start <= end_old <= len(before):
            raise ValueError(f"range ({start}, {end_old}) is not inside the {len(before)}-byte stream")
        if start < previous_end:
            raise ValueError("overlapping ranges")
        previous_end = end_old
    parts: list[str] = []
    cursor_before = cursor_after = shift = 0
    for index, (start, end_old, end_new) in enumerate(ordered):
        start_after = start + shift
        if end_new < start_after:
            raise ValueError(f"range ({start}, {end_old}, {end_new}) ends before it starts in the new stream")
        gap_before, gap_after = before[cursor_before:start], after[cursor_after:start_after]
        if gap_before != gap_after:
            where = cursor_before + _first_difference(gap_before, gap_after)
            label = "prefix_changed" if index == 0 else f"gap_changed: gap {index}"
            parts.append(f"{label}: first difference at byte {where}")
        shift = end_new - end_old
        cursor_before, cursor_after = end_old, end_new
    tail_before, tail_after = before[cursor_before:], after[cursor_after:]
    if tail_before != tail_after:
        where = cursor_before + _first_difference(tail_before, tail_after)
        parts.append(f"suffix_changed: first difference at byte {where}")
    if len(after) != len(before) + shift:
        parts.append(f"length: {len(after)} bytes after, expected {len(before) + shift}")
    return "stream_range: " + "; ".join(parts) if parts else None


def _mc_operand_start(stream: bytes, open_op_end: int) -> int | None:
    """Start offset of the operands of the ``BDC``/``BMC`` whose operator token ends at ``open_op_end``.

    One forward pass of the plain lexer (never materialised).  The operand list is the one the replay builds:
    an operator clears it (``true``/``false``/``null`` are dictionary values and stay), and the accepted
    shapes are exactly replay's: ``/Tag`` for BMC; ``/Tag /Name`` or ``/Tag <<...>>`` (the dictionary opened at
    the second operand and closed by the last) for BDC.  Anything else, or a stream that has no such operator
    token there, is ``None``."""
    operands: list = []
    operator = b""
    for token in lex_content_stream(stream):
        if token.start >= open_op_end:
            return None
        if token.kind in (TokenKind.WHITESPACE, TokenKind.COMMENT, TokenKind.MALFORMED):
            continue
        if token.kind is TokenKind.OPERATOR:
            raw = stream[token.start : token.end]
            if token.end == open_op_end:
                if raw not in (b"BDC", b"BMC"):
                    return None
                operator = raw
                break
            if raw not in (b"true", b"false", b"null"):
                operands.clear()
                continue
        elif token.kind is TokenKind.INLINE_IMAGE_DATA:
            operands.clear()
            continue
        operands.append(token)
    else:
        return None
    if not operands or operands[0].kind is not TokenKind.NAME:
        return None
    if operator == b"BMC":
        return operands[0].start if len(operands) == 1 else None
    if len(operands) == 2 and operands[1].kind is TokenKind.NAME:
        return operands[0].start
    if (
        len(operands) >= 3
        and operands[1].kind is TokenKind.DICT_OPEN
        and operands[-1].kind is TokenKind.DICT_CLOSE
    ):
        depth = 0
        for index in range(len(operands) - 1, 0, -1):
            if operands[index].kind is TokenKind.DICT_CLOSE:
                depth += 1
            elif operands[index].kind is TokenKind.DICT_OPEN:
                depth -= 1
                if depth == 0:
                    return operands[0].start if index == 1 else None
    return None


def check_wrapper_bytes_unchanged(
    before_streams: Mapping[int, bytes],
    after_streams: Mapping[int, bytes],
    before_replay: PageReplay,
    after_replay: PageReplay,
    edited_show_seq: int,
    edited_stream_xref: int,
    delta: int,
) -> str | None:
    """The marked-content wrappers around the edited show are byte-for-byte what they were.

    ``delta`` is ``end_new - end_old`` of the splice.  Only offsets in the edited stream and after the edit
    shift, by exactly ``delta``; a wrapper's closing ``EMC`` may live in ANOTHER content stream, where nothing
    shifts.  Per wrapper pair (outermost first): ``tag`` (operator, tag, properties or stream differ),
    ``open_moved``, ``open_unparsed`` (the operands cannot be located), ``open_changed`` (the operand-to-operator
    bytes differ), ``close`` (open before, not after, or the reverse), ``close_moved`` and ``close_changed``
    (the ``EMC`` bytes).  No wrapper on the show is a pass (the twin judge counts that as vacuous).  Tags and
    names are never printed."""
    if not 0 <= edited_show_seq < len(before_replay.shows):
        raise ValueError(f"no show {edited_show_seq} before the edit")
    old_show = before_replay.shows[edited_show_seq]
    if old_show.stream_xref != edited_stream_xref:
        raise ValueError("the edited show is not in the edited stream")
    if not 0 <= edited_show_seq < len(after_replay.shows):
        return "wrapper: show: edited show missing after"
    new_show = after_replay.shows[edited_show_seq]
    if not (
        new_show.stream_xref == old_show.stream_xref
        and new_show.op_start == old_show.op_start
        and new_show.op_end == old_show.op_end + delta
    ):
        return "wrapper: show_span: moved"

    def shifted(xref: int, offset: int) -> int:
        return offset + delta if xref == edited_stream_xref and offset >= old_show.op_end else offset

    old_wrappers = before_replay.wrappers_for(old_show)
    new_wrappers = after_replay.wrappers_for(new_show)
    if len(old_show.mc_stack) != len(new_show.mc_stack) or len(old_wrappers) != len(new_wrappers):
        return f"wrapper: stack: {len(old_wrappers)} before, {len(new_wrappers)} after"
    counts = dict.fromkeys(
        ("tag", "open_moved", "open_unparsed", "open_changed", "close", "close_moved", "close_changed"), 0
    )
    for old, new in zip(old_wrappers, new_wrappers, strict=True):
        if (old.operator, old.tag, old.props_kind, old.props_name, old.props_dict_keys, old.stream_xref) != (
            new.operator,
            new.tag,
            new.props_kind,
            new.props_name,
            new.props_dict_keys,
            new.stream_xref,
        ):
            counts["tag"] += 1
        if new.open_op_end != shifted(old.stream_xref, old.open_op_end):
            counts["open_moved"] += 1
        old_stream = before_streams.get(old.stream_xref, b"")
        new_stream = after_streams.get(new.stream_xref, b"")
        old_start = _mc_operand_start(old_stream, old.open_op_end)
        new_start = _mc_operand_start(new_stream, new.open_op_end)
        if old_start is None or new_start is None:
            counts["open_unparsed"] += 1
        elif old_stream[old_start : old.open_op_end] != new_stream[new_start : new.open_op_end] or (
            new_start != shifted(old.stream_xref, old_start)
        ):
            counts["open_changed"] += 1
        if old.closed != new.closed:
            counts["close"] += 1
        elif old.closed:
            assert old.close_stream_xref is not None and old.close_op_start is not None
            assert new.close_stream_xref is not None and new.close_op_start is not None
            if new.close_stream_xref != old.close_stream_xref or new.close_op_start != shifted(
                old.close_stream_xref, old.close_op_start
            ):
                counts["close_moved"] += 1
            old_close = before_streams.get(old.close_stream_xref, b"")[old.close_op_start : old.close_op_start + 3]
            new_close = after_streams.get(new.close_stream_xref, b"")[new.close_op_start : new.close_op_start + 3]
            if old_close != b"EMC" or new_close != b"EMC":
                counts["close_changed"] += 1
    parts = [f"{slug}: {count} of {len(old_wrappers)} wrapper(s)" for slug, count in counts.items() if count]
    return "wrapper: " + "; ".join(parts) if parts else None


def _operator_total(data: bytes) -> int:
    return sum(1 for token in lex_content_stream(data) if token.kind is TokenKind.OPERATOR)


def check_show_and_operator_counts_equal(
    before_streams: Sequence[tuple[int, bytes]], after_streams: Sequence[tuple[int, bytes]]
) -> str | None:
    """Per content stream, the number of shows and of operator tokens is unchanged by the edit.

    Stream LISTS (``page_streams``), not documents.  A different xref list is reported alone; a refused replay
    (``replay: refused before|after``) or one that turned malformed (``malformed: after``) is a failure."""
    xrefs_before, xrefs_after = [xref for xref, _ in before_streams], [xref for xref, _ in after_streams]
    if xrefs_before != xrefs_after:
        return f"counts: streams: {len(xrefs_before)} before, {len(xrefs_after)} after"
    replay_before = replay_page_streams(list(before_streams))
    replay_after = replay_page_streams(list(after_streams))
    if replay_before.refusal_reason is not None:
        return "counts: replay: refused before"
    if replay_after.refusal_reason is not None:
        return "counts: replay: refused after"
    if replay_after.malformed and not replay_before.malformed:
        return "counts: malformed: after"
    parts: list[str] = []
    for index, ((xref, data_before), (_, data_after)) in enumerate(zip(before_streams, after_streams, strict=True)):
        shows_before = sum(show.stream_xref == xref for show in replay_before.shows)
        shows_after = sum(show.stream_xref == xref for show in replay_after.shows)
        if shows_before != shows_after:
            parts.append(f"shows: stream {index}: {shows_before} before, {shows_after} after")
        operators_before, operators_after = _operator_total(data_before), _operator_total(data_after)
        if operators_before != operators_after:
            parts.append(f"operators: stream {index}: {operators_before} before, {operators_after} after")
    return "counts: " + "; ".join(parts) if parts else None


class IndependentLegUnavailable(Exception):
    """No independent glyph-identity leg exists for this font (the caller decides what that means).

    The message is a fixed ASCII sentence and never names a font."""


GLYPH_LEG_UNAVAILABLE = "glyph_identity: independent glyph leg unavailable"

_U1 = "a Type0 font without an Identity-H capability"
_U2 = "an unembedded font outside the base-14 text table"
_U3 = "a Type1 program (FontFile) is not read yet"
_U4 = "a CFF or OpenType program (FontFile3) is not read yet"
_U5 = "the embedded program cannot be read"
_U6 = "a nameless program has no (3,1) cmap"
_U7 = "the encoding cannot name the code"
_U8 = "a Type0 program has no Unicode cmap"

_BASE14_LATIN = frozenset(name for name in _BASE14_ALIASES if name not in ("Symbol", "ZapfDingbats"))
_SYMBOL_CODE_OFFSETS = (0x0000, 0xF000, 0xF100, 0xF200)


def _name_to_char(name: str) -> str:
    """The AGL text of a glyph name; a name with no text is unavailable (U7)."""
    text = toUnicode(name)
    if text == "":
        raise IndependentLegUnavailable(_U7)
    return text


def _encoding_names(doc: fitz.Document, font_xref: int) -> Callable[[int], str]:
    """``code -> glyph name`` for the simple font's ``/Encoding`` (ASCII scope only; ``/Differences`` is U7).

    A font without ``/Encoding`` falls back to ``StandardEncoding`` (the base-14 default)."""
    kind, value = doc.xref_get_key(font_xref, "Encoding")
    if kind == "null":
        base = "StandardEncoding"
    elif kind == "name":
        base = value.lstrip("/")
    else:
        if doc.xref_get_key(font_xref, "Encoding/Differences")[0] != "null":
            raise IndependentLegUnavailable(_U7)
        base_kind, base_value = doc.xref_get_key(font_xref, "Encoding/BaseEncoding")
        if base_kind != "name":
            raise IndependentLegUnavailable(_U7)
        base = base_value.lstrip("/")
    if base == "StandardEncoding":
        return lambda code: StandardEncoding[code] if 0 <= code < 256 else ".notdef"
    if base == "MacRomanEncoding":
        return lambda code: MacRoman[code] if 0 <= code < 256 else ".notdef"
    if base == "WinAnsiEncoding":

        def win_ansi(code: int) -> str:
            if not 0x20 <= code <= 0x7E:
                raise IndependentLegUnavailable(_U7)
            return UV2AGL[code]

        return win_ansi
    raise IndependentLegUnavailable(_U7)


class _TrueTypeView:
    """A lazily parsed embedded TrueType program: glyph names, cmaps, outlines (fontTools, never ``extract_font``)."""

    def __init__(self, program: bytes | None) -> None:
        if not program:
            raise IndependentLegUnavailable(_U5)
        try:
            self.font = TTFont(BytesIO(program), lazy=True)
            self.glyph_order = self.font.getGlyphOrder()
        except Exception as exc:  # noqa: BLE001 - any parse failure makes the leg unavailable, whatever fontTools raises
            raise IndependentLegUnavailable(_U5) from exc

    @cached_property
    def post_format(self) -> float:
        try:
            return float(self.font["post"].formatType)
        except Exception as exc:  # noqa: BLE001
            raise IndependentLegUnavailable(_U5) from exc

    @cached_property
    def cmaps(self) -> dict[tuple[int, int], dict[int, str]]:
        try:
            return {(table.platformID, table.platEncID): table.cmap for table in self.font["cmap"].tables}
        except Exception as exc:  # noqa: BLE001
            raise IndependentLegUnavailable(_U5) from exc

    @property
    def has_names(self) -> bool:
        """Post format 1 or 2 carries real glyph names; format 3 has none (``getGlyphOrder`` then invents some)."""
        return self.post_format in (1.0, 2.0)

    def gid(self, name: str | None) -> int | None:
        if not name:
            return None
        try:
            return int(self.font.getGlyphID(name))
        except KeyError:
            return None

    def has_outline(self, gid: int) -> bool:
        try:
            return self.font["glyf"][self.font.getGlyphName(gid)].numberOfContours != 0
        except Exception:  # noqa: BLE001 - a glyph that cannot be read has no outline we can vouch for
            return False

    def name_of(self, gid: int) -> str:
        return self.glyph_order[gid] if 0 <= gid < len(self.glyph_order) else ""


def _builtin_encoding(doc: fitz.Document, font_xref: int) -> bool:
    """True when the walk uses the font's own cmap (symbolic descriptor or no ``/Encoding``)."""
    return _is_symbolic(doc, font_xref) or doc.xref_get_key(font_xref, "Encoding")[0] == "null"


def _truetype_walk(doc: fitz.Document, font_xref: int, view: _TrueTypeView) -> Callable[[int], int | None]:
    """ISO 32000-1 9.6.6.4: the glyph the PDF machinery assigns to a code of an embedded simple TrueType font."""
    cmaps = view.cmaps
    if _builtin_encoding(doc, font_xref):

        def walk_builtin(code: int) -> int | None:
            if (3, 0) in cmaps:
                for offset in _SYMBOL_CODE_OFFSETS:
                    if code + offset in cmaps[(3, 0)]:
                        return view.gid(cmaps[(3, 0)][code + offset])
                return None
            if (1, 0) in cmaps:
                return view.gid(cmaps[(1, 0)].get(code))
            return None

        return walk_builtin
    names = _encoding_names(doc, font_xref)

    def walk_named(code: int) -> int | None:
        name = names(code)
        found: int | None = None
        if (3, 1) in cmaps:
            text = _name_to_char(name)
            found = view.gid(cmaps[(3, 1)].get(ord(text))) if len(text) == 1 else None
        elif (1, 0) in cmaps and name in MacRoman:
            found = view.gid(cmaps[(1, 0)].get(MacRoman.index(name)))
        if found is None and view.has_names:
            found = view.gid(name)
        return found

    return walk_named


def glyph_identity_inputs(
    reopened: fitz.Document,
    page_index: int,
    edited: EditedShow,
    *,
    frame: PageVisualFrame,
    code_bytes: int,
) -> tuple[tuple[int, ...], tuple[int, ...]] | str:
    """``(codes, gids)`` of the new glyphs of an edited show: the codes written (big-endian units of
    ``code_bytes``) and the glyph ids the texttrace of ``reopened`` reports for them, or a
    ``glyph_identity: pairing: <reason>`` detail when the show cannot be located."""
    with _measurement_copy(reopened) as measured:
        flat = _flatten_trace(measured[page_index])
    located = _emissions(
        flat,
        _shows(reopened, page_index),
        edited.after_show,
        frame,
        edited.pre + edited.n_new + edited.post,
    )
    if isinstance(located, str):
        return f"glyph_identity: pairing: {located}"
    first = located[0] + edited.pre
    gids = tuple(glyph.gid for glyph in flat[first : first + edited.n_new])
    data = edited.after_show.decoded_bytes[edited.pre * code_bytes : (edited.pre + edited.n_new) * code_bytes]
    codes = tuple(int.from_bytes(data[i : i + code_bytes], "big") for i in range(0, len(data), code_bytes))
    return codes, gids


def check_glyph_identity(
    reopened: fitz.Document,
    page_index: int,
    font_xref: int,
    replacement: str,
    font_kind: str,
    *,
    gid_after: Sequence[int],
    codes: Sequence[int],
    measurements: dict | None = None,
) -> str | None:
    """The glyphs drawn for ``replacement`` are the characters it claims (two legs, both required).

    Per non-space character ``i``: the CONSISTENCY leg takes the glyph the PDF's own font machinery assigns to
    the code that was written (``codes[i]``): it must exist (``unmapped``), equal the glyph the rendering drew
    (``gid_after[i]``, ``leg_gid_differs``), not be ``.notdef`` (``gid_zero``) and, in an embedded TrueType
    program, have an outline (``no_outline``).  The INDEPENDENT leg asks what that glyph IS and compares it to
    the character (``leg_char_differs``): ``glyph_name_agl`` (post names through the AGL),
    ``cmap_31_reverse`` (a nameless program: the character's own (3,1) entry must reach the glyph),
    ``standard_14_table`` (an unembedded base-14 font: the encoding table's name) or ``cid_program_cmap`` (Type0:
    the character's own entry in the program's Unicode cmap, (3,1) or (0,x), must reach the glyph).  A Type0
    font's ToUnicode is the product's own encoder read backwards, so it is NOT an independent leg: it is only
    cross-checked (``tounicode_disagrees``).
    ``IndependentLegUnavailable`` when no leg can be built (never a fallback); ``ValueError`` for inputs that
    contradict each other.  ``measurements`` receives ``leg``, ``glyphs_checked`` and ``outline_checked``.
    The program is read through its FontFile stream, never ``extract_font`` (it leaks the BaseFont name)."""
    if font_kind not in ("simple", "type0"):
        raise ValueError(f"unknown font kind {font_kind!r}")
    if not len(gid_after) == len(codes) == len(replacement):
        raise ValueError("gid_after, codes and replacement differ in length")
    with _measurement_copy(reopened) as measured:
        page = measured[page_index]
        entries = [entry for entry in page.get_fonts(full=True) if entry[0] == font_xref]
        if not entries:
            raise ValueError("the font is not on the page")
        entry = next((item for item in entries if page_scoped_font_entry(item)), entries[0])
        if font_kind == "type0" and entry[2] != "Type0":
            raise ValueError("font_kind type0 but the font is not Type0")
        if font_kind == "simple" and entry[2] not in _SIMPLE_SUBTYPES:
            raise ValueError("font_kind simple but the font is not a simple font")
        capability = DocumentFontRegistry(measured).capability(page, entry[4])
        if capability is None:
            raise ValueError("no font capability for the font")
        leg, view, walk, claim, uses_outline, agrees = _glyph_leg(measured, font_xref, capability, font_kind)
        unmapped: list[int] = []
        gid_differs: list[int] = []
        gid_zero: list[int] = []
        no_outline: list[int] = []
        char_differs: list[int] = []
        tounicode_disagrees: list[int] = []
        checked = outlined = 0
        for index, char in enumerate(replacement):
            if char.isspace():
                continue
            checked += 1
            walked = walk(codes[index])
            if walked is None:
                unmapped.append(index)
                continue
            if walked != gid_after[index]:
                gid_differs.append(index)
            if walked == 0:
                gid_zero.append(index)
            elif uses_outline and view is not None:
                outlined += 1
                if not view.has_outline(walked):
                    no_outline.append(index)
            if walked != 0 and not claim(codes[index], walked, char):
                char_differs.append(index)
            if agrees is not None and not agrees(codes[index], char):
                tounicode_disagrees.append(index)
    if measurements is not None:
        measurements.update(leg=leg, glyphs_checked=checked, outline_checked=outlined)
    slugs = (
        ("unmapped", unmapped),
        ("leg_gid_differs", gid_differs),
        ("gid_zero", gid_zero),
        ("no_outline", no_outline),
        ("leg_char_differs", char_differs),
        ("tounicode_disagrees", tounicode_disagrees),
    )
    parts = [f"{slug}: {len(found)} of {checked} glyph(s), first index {found[0]}" for slug, found in slugs if found]
    return f"glyph_identity: {leg}: " + "; ".join(parts) if parts else None


def _glyph_leg(
    doc: fitz.Document, font_xref: int, capability: FontCapability, font_kind: str
) -> tuple[
    str,
    _TrueTypeView | None,
    Callable[[int], int | None],
    Callable[[int, int, str], bool],
    bool,
    Callable[[int, str], bool] | None,
]:
    """``(leg, program view, walk(code) -> gid, claim(code, gid, char) -> bool, outline checked, agrees)`` for one
    font; ``agrees(code, char)`` is a consistency-only cross-check (Type0 ToUnicode), ``None`` otherwise."""
    if font_kind == "type0":
        cid = capability.cid
        if cid is None:
            raise IndependentLegUnavailable(_U1)
        view = _TrueTypeView(read_embedded_font_program(doc, font_xref))

        def walk_cid(code: int) -> int | None:
            gid = cid.gid_for(code)
            return gid if isinstance(gid, int) else None

        unicode_cmap = view.cmaps.get((3, 1))
        if unicode_cmap is None:
            unicode_cmap = next((view.cmaps[key] for key in sorted(view.cmaps) if key[0] == 0), None)
        if unicode_cmap is None:
            raise IndependentLegUnavailable(_U8)
        return (
            "cid_program_cmap",
            view,
            walk_cid,
            lambda code, gid, char: ord(char) in unicode_cmap and view.gid(unicode_cmap[ord(char)]) == gid,
            True,
            lambda code, char: cid.tounicode.decode_cid(code) == char,
        )
    descriptor = {
        key: doc.xref_get_key(font_xref, f"FontDescriptor/{key}") for key in ("FontFile", "FontFile2", "FontFile3")
    }
    if descriptor["FontFile2"][0] == "null":
        if descriptor["FontFile"][0] != "null":
            raise IndependentLegUnavailable(_U3)
        if descriptor["FontFile3"][0] != "null":
            raise IndependentLegUnavailable(_U4)
        stripped = capability.basefont.split("+", 1)[-1]
        if (
            capability.face_source != "base14"
            or capability.face is None
            or stripped not in _BASE14_LATIN
            or _is_symbolic(doc, font_xref)
        ):
            raise IndependentLegUnavailable(_U2)
        face = capability.face
        names = _encoding_names(doc, font_xref)

        def walk_base14(code: int) -> int | None:
            text = _name_to_char(names(code))
            return int(face.has_glyph(ord(text))) if len(text) == 1 else None

        return (
            "standard_14_table",
            None,
            walk_base14,
            lambda code, gid, char: _name_to_char(names(code)) == char,
            False,
            None,
        )
    kind, value = descriptor["FontFile2"]
    if kind != "xref":
        raise IndependentLegUnavailable(_U5)
    view = _TrueTypeView(doc.xref_stream(int(value.split()[0])))
    walk = _truetype_walk(doc, font_xref, view)
    if view.has_names:
        return (
            "glyph_name_agl",
            view,
            walk,
            lambda code, gid, char: _name_to_char(view.name_of(gid)) == char,
            True,
            None,
        )
    unicode_cmap = view.cmaps.get((3, 1))
    if unicode_cmap is None:
        raise IndependentLegUnavailable(_U6)
    return (
        "cmap_31_reverse",
        view,
        walk,
        lambda code, gid, char: ord(char) in unicode_cmap and view.gid(unicode_cmap[ord(char)]) == gid,
        True,
        None,
    )
