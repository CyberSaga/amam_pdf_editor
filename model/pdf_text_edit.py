"""Edit-text / redaction engine (R3.5 god-module decomposition seam — LAST model seam).

The edit-text resolution, redaction insertion, protected-span replay, overflow
push-down and post-edit verification extracted out of PDFModel as free functions
(``def fn(model: PDFModel, ...)``), mirroring ``model/pdf_optimizer.py`` and
``model/pdf_object_ops.py``. PDFModel keeps 1-line delegating wrappers (``edit_text``
plus the private helpers the test net pokes directly). Bodies are moved verbatim
(only ``self`` -> ``model``); the undo-snapshot boundary stays with ``edit_text``'s
caller contract (snapshot captured once, restored on failure). ``_classify_insert_path``
and ``_EditTextResolveResult`` move here too and are re-exported from ``pdf_model`` so
existing ``from model.pdf_model import ...`` test imports keep working.

Cross-cutting helpers reached via ``model.`` (they STAY on PDFModel because callers
outside this cluster use them): ``_needs_cjk_font`` (object-ops), ``_resolve_font_for_push``
(add-text), ``_convert_text_to_html`` / ``_build_insert_css`` / ``_build_multi_style_html``
(controller + view preview), ``_maybe_garbage_collect`` (encryption-preserving roundtrip).
"""

from __future__ import annotations

import difflib
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclasses_replace
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, TypeAlias

import fitz

from model.edit_commands import EditTextResult, MaintenanceBook
from model.edit_requests import RebuildConsent, SourceShowRef, StyleOverrides, UnkeepableGlyph
from model.font_stream_compaction import font_compaction_scope, insert_htmlbox_tracked
from model.geometry import (
    clamp_rect_to_page,
    rect_union,
    unrotated_page_rect,
    visual_to_unrotated_rect,
)
from model.joined_edit_runs import JoinedEditGroup, find_joined_fragments, joined_record_for
from model.off_axis_shows import read_streams, restore_turned_shows
from model.page_content_text import content_text, content_textpage
from model.pdf_object_ops import sync_textbox_markers_after_text_edit, textbox_page_words
from model.rtl_text import contains_rtl, grows_right_to_left
from model.text_block import EditableSpan, TextBlock, rotation_degrees_from_dir
from model.text_commit.dto import (
    CommitOutcome,
    CommitStatus,
    RejectReason,
    TextCommitSettings,
    legacy_commit_outcome,
)
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import find_pages_sharing_content_stream
from model.text_commit.plan import PreparedEdit, PlanRejection, prepare_tier0_plan
from model.text_commit.source_run import SourceRunGroup, SourceRunResolver
from model.text_commit.transforms import (
    UnsupportedPageGeometryError,
    insert_text_page_space,
    page_visual_frame,
)
from model.text_edit_refusal import TextEditRefusal, TextEditRefused
from model.text_normalization import is_unchanged_text, normalize_text, token_coverage_ratio
from model.text_paint_state import (
    PageTextStates,
    WriteStyle,
    paint_state_applied,
    refusal_for,
    style_for_run,
    style_for_runs,
)
from utils.cjk_ext_b_font import (
    FONT_NAME_PREFIX as EXT_B_FONT_NAME_PREFIX,
    ext_b_component_missing,
    ext_b_install_would_help,
    ext_b_refusal_reason,
)

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EditTextResolveResult:
    target_span: EditableSpan
    resolved_target_span_id: str
    effective_target_mode: str
    target_member_span_ids: set[str]
    overlap_cluster: list[EditableSpan]
    protected_spans: list[EditableSpan]
    target: TextBlock
    resolved_font: str
    rotation: int
    is_vertical: bool
    insert_rotate: int
    redact_rect: fitz.Rect
    reopen_anchor_rect: fitz.Rect | None = None
    # UI step 3: the proven source show the target resolves to, RE-DERIVED
    # here on the commit side (never taken from the view).  When set, the
    # members are exactly the group and the Tier 0 target is the show.
    source_group: SourceRunGroup | None = None
    # The key ``reopen_anchor_rect`` is stored under: the span id for a run,
    # ``source_run.group_anchor_key`` for a multi-member group.
    reopen_anchor_key: str | None = None


def _member_spans(resolve_result: _EditTextResolveResult) -> list[EditableSpan]:
    """The edited runs: the overlap cluster's members, in cluster order."""
    members = resolve_result.target_member_span_ids
    return [span for span in resolve_result.overlap_cluster if span.span_id in members]


def _simple_font_can_encode(text: str) -> bool:
    """True iff ``page.insert_text`` with a simple (base-14) font writes every
    character of ``text`` as itself.

    PyMuPDF's ``getTJstr`` encodes a simple font's text as one byte per code
    point: ``ord(c) < 256`` is written as-is and EVERY other character becomes
    0xB7 ("·") -- silently, whatever glyphs the font has (Helvetica has a
    ``€`` glyph and still gets ``·``).  C0/C1 control code points are excluded
    too: their byte would select an unrelated glyph.  Only printable Latin-1
    is safe; anything else (Arabic, Hebrew, Thai, Devanagari, Cyrillic, Greek,
    ``€``, combining marks, ZWJ, emoji, CJK, ...) needs the htmlbox engine.
    This is the one predicate for "may this text go through
    ``insert_text(<base-14 font>)``" -- the CJK regex (``_needs_cjk_font``)
    answers a different question (which fallback font) and is NOT a stand-in
    for it (F10-UNI-1).
    """
    for ch in text or "":
        code = ord(ch)
        if not (0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF):
            return False
    return True


def _presence_norm(text: str) -> str:
    """``normalize_text`` after NFKC, for "is the requested text on the page"
    checks: htmlbox extracts shaped Arabic as presentation forms (U+FExx) and
    may compose/decompose marks, which NFKC folds back to the requested form."""
    return normalize_text(unicodedata.normalize("NFKC", text or ""))


def _is_ignorable_for_presence(ch: str) -> bool:
    """Whitespace and invisible format characters (ZWJ/ZWNJ/soft hyphen,
    variation selectors) render as nothing and do not extract reliably."""
    if ch.isspace() or unicodedata.category(ch) == "Cf":
        return True
    code = ord(ch)
    return 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


def _codepoint_label(ch: str) -> str:
    """The ``U+XXXX`` label a character is reported under -- the ONE format
    behind the lost-character lists, ``UnkeepableGlyph.codepoint`` and the
    acknowledged-loss sets they are matched against."""
    return f"U+{ord(ch):04X}"


def _label_char(label: str) -> str:
    """The character a ``_codepoint_label`` names."""
    return chr(int(label[2:], 16))


def _lost_requested_chars(requested: str, page_text: str) -> list[str]:
    """The requested characters (NFKC, minus ignorables) absent from
    ``page_text``, as ``U+XXXX`` labels.  A lossy insert (``·`` substitution,
    a font fallback without the glyph, a corrupt ToUnicode for non-BMP or
    shaped Indic text) shows up here even when the fuzzy similarity gate
    would accept the line."""
    have = set(unicodedata.normalize("NFKC", page_text or ""))
    lost: list[str] = []
    for ch in unicodedata.normalize("NFKC", requested or ""):
        if _is_ignorable_for_presence(ch) or ch in have:
            continue
        label = _codepoint_label(ch)
        if label not in lost:
            lost.append(label)
    return lost


# Placeholder characters outside the Cc/Co/Cs/Cn categories: U+FFFD (replacement
# character) and U+FFFC (object replacement character, F16-PASTE-2).
_PLACEHOLDER_CHARS = frozenset("\ufffd\ufffc")


def _is_identityless_placeholder(ch: str) -> bool:
    """U+FFFD, U+FFFC, control codes, private-use, surrogate and unassigned
    code points: text with no Unicode identity of its own.  No renderer can
    be shown to have drawn "it", so a lossy text layer is never forgiven for
    it (F11-UNI-1) -- unless it is untouched and the consent acknowledged
    it (decision C, ``_rebuild_glyph_loss``).

    U+FFFC (OBJECT REPLACEMENT CHARACTER, category So) is in the class
    although it has a name: it is the anchor of an inline object (an image
    in pasted HTML reads back as U+FFFC from ``toPlainText()``), never a
    character a PDF text layer means.  htmlbox draws it as a dashed "OBJ"
    box and round-trips it, so the lossy-layer gates never see it as lost
    (F16-PASTE-2)."""
    return ch in _PLACEHOLDER_CHARS or unicodedata.category(ch) in ("Cc", "Co", "Cs", "Cn")


def _is_unkeepable_glyph(ch: str) -> bool:
    """A visible character a rebuild cannot reproduce: identity-less
    (``_is_identityless_placeholder``) and not layout whitespace (``\\n`` /
    ``\\t`` are control codes too, but no glyph)."""
    return _is_identityless_placeholder(ch) and not _is_ignorable_for_presence(ch)


def _unkeepable_glyph_fate(ch: str) -> str:
    """What htmlbox draws in place of an unkeepable glyph: U+FFFD, U+FFFC (a
    dashed "OBJ" box) and control codes get a replacement glyph
    (``"replaced"``), private-use, surrogate and unassigned code points the
    blank .notdef (``"removed"``).  Pinned against the pinned PyMuPDF by
    ``test_unkeepable_glyph_fate_matches_htmlbox``."""
    return "replaced" if ch in _PLACEHOLDER_CHARS or unicodedata.category(ch) == "Cc" else "removed"


def _unkeepable_glyph(span_id: str | None, index: int, ch: str) -> UnkeepableGlyph:
    return UnkeepableGlyph(
        span_id=span_id,
        index=index,
        codepoint=_codepoint_label(ch),
        fate=_unkeepable_glyph_fate(ch),
    )


def _span_unkeepable_glyphs(span: EditableSpan) -> list[UnkeepableGlyph]:
    """The unkeepable glyphs of a replayed neighbour's text, as the consent
    report names them (``span_id``, index into the text without its trailing
    newline)."""
    return [
        _unkeepable_glyph(span.span_id, index, ch)
        for index, ch in enumerate((span.text or "").rstrip("\n"))
        if _is_unkeepable_glyph(ch)
    ]


def _untouched_glyph_report(
    source_text: str, new_text: str
) -> tuple[UnkeepableGlyph, ...] | None:
    """The unkeepable glyphs of ``new_text`` the user did NOT type: each one
    must sit in a stretch the edit left equal to ``source_text`` (a character
    diff).  ``None`` when any of them was typed -- a placeholder the user
    typed is never acknowledgeable (F11-UNI-1 decision C)."""
    if not any(_is_unkeepable_glyph(ch) for ch in new_text):
        return ()  # nothing to report: skip the (quadratic) character diff
    untouched = [False] * len(new_text)
    matcher = difflib.SequenceMatcher(None, source_text, new_text, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for j in range(j1, j2):
                untouched[j] = True
    report: list[UnkeepableGlyph] = []
    for index, ch in enumerate(new_text):
        if not _is_unkeepable_glyph(ch):
            continue
        if not untouched[index]:
            return None
        report.append(_unkeepable_glyph(None, index, ch))
    return tuple(report)


def _rebuild_glyph_loss(
    new_text: str, resolve_result: _EditTextResolveResult
) -> tuple[UnkeepableGlyph, ...]:
    """Every untouched glyph a consented rebuild of ``resolve_result`` with
    ``new_text`` cannot keep: those in the edited text (``span_id`` None) and
    those in the overlapping neighbour runs it redacts and replays.  Empty
    when there are none -- and when the user typed one, so nothing can be
    acknowledged and the rebuild keeps refusing."""
    source_text = "".join(span.text or "" for span in _member_spans(resolve_result)) or (
        resolve_result.target.text or ""
    )
    own = _untouched_glyph_report(source_text, new_text or "")
    if own is None:
        return ()
    neighbours = [
        glyph for span in resolve_result.protected_spans for glyph in _span_unkeepable_glyphs(span)
    ]
    return own + tuple(neighbours)


def _acknowledged_labels(
    glyphs: tuple[UnkeepableGlyph, ...] | list[UnkeepableGlyph],
) -> tuple[set[str], int]:
    """The acknowledged code point labels and how many of the glyphs htmlbox
    draws as .notdef (``"removed"``)."""
    return {g.codepoint for g in glyphs}, sum(1 for g in glyphs if g.fate == "removed")


# Height of the scratch page a reference render is laid out on: tall enough
# that a replacement never overflows (scale_low=0 is the backstop), and within
# MuPDF's 14400 pt page limit.
_REFERENCE_PAGE_HEIGHT = 14400.0


class _HtmlboxReference(NamedTuple):
    """What ``insert_htmlbox`` produces for one markup on a scratch page."""

    text: str  # its text layer, as extraction reads it back
    glyphs: Counter[tuple[str, int]]  # inked glyphs, (font name, glyph id)
    notdef: int  # glyphs drawn as .notdef (glyph id 0): no font had them


def _texttrace_glyphs(
    page: fitz.Page, rect: fitz.Rect | None = None
) -> tuple[Counter[tuple[str, int]], int]:
    """``(font name, glyph id)`` of every non-whitespace glyph the page draws
    (centre inside ``rect`` when given), plus the count of .notdef glyphs.

    Glyph ids come from ``get_texttrace``, not from the text layer, so they
    identify what is DRAWN even where the ToUnicode map is wrong."""
    glyphs: Counter[tuple[str, int]] = Counter()
    notdef = 0
    for span in page.get_texttrace():
        font = str(span.get("font", ""))
        # An Ext-B subset font's codes are htmlbox's 16-bit cut of the code
        # point (U+20000 -> U+2000, a space): never skip its glyphs as
        # whitespace, or the evidence for them would be empty (EXTB-SUBSET).
        ext_b_font = font.startswith(EXT_B_FONT_NAME_PREFIX)
        for ch in span.get("chars", ()):
            code, gid = int(ch[0]), int(ch[1])
            if not ext_b_font and 0 <= code < 0x110000 and chr(code).isspace():
                continue
            if rect is not None:
                x0, y0, x1, y1 = ch[3]
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                if not (rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1):
                    continue
            if gid == 0:
                notdef += 1
            else:
                glyphs[(font, gid)] += 1
    return glyphs, notdef


def _htmlbox_reference(html: str, css: str, width: float) -> _HtmlboxReference:
    """Render ``html`` / ``css`` on a throwaway page ``width`` wide: the text
    layer and the glyphs ``insert_htmlbox`` writes for this markup."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=max(float(width), 1.0), height=_REFERENCE_PAGE_HEIGHT)
        insert_htmlbox_tracked(page, page.rect, html, css=css, scale_low=0, scratch=True)
        glyphs, notdef = _texttrace_glyphs(page)
        return _HtmlboxReference(page.get_text("text"), glyphs, notdef)
    finally:
        doc.close()


# A replayed span is one line: never let htmlbox wrap it (the box it is drawn
# in is only as long as the measured line, so a wrap would be a layout change).
_NO_WRAP_CSS = "\nspan { white-space: pre; word-break: normal; overflow-wrap: normal; }"

# D-RTL-GROW: the markup of a right-to-left run (``_spans_grow_right_to_left``)
# is laid out as a right-to-left paragraph -- right-aligned in its box, so the
# box is pinned on the edge the text starts at, extra lines are right-aligned
# too and neutral characters (a final full stop) sit where a right-to-left
# reader expects them.  Every builder of such a markup appends it: the insert
# and its verification's reference render stay one layout.
_RTL_BASE_CSS = "\nbody { direction: rtl; }"


def _paragraph_text(model: PDFModel, span: Any) -> str | None:
    """The text of the index block that holds ``span``, in reading order (the
    paragraph whose base direction decides a mixed run), ``None`` when the
    block cannot be read."""
    page_idx = getattr(span, "page_idx", None)
    block_idx = getattr(span, "block_idx", None)
    if page_idx is None or block_idx is None:
        return None
    try:
        runs = [r for r in model.block_manager.get_runs(int(page_idx)) if r.block_idx == block_idx]
    except Exception:
        logger.debug("paragraph text for the direction rule unavailable", exc_info=True)
        return None
    runs.sort(key=lambda r: (int(r.line_idx), int(r.span_idx)))
    return " ".join(r.text or "" for r in runs) or None


def _spans_grow_right_to_left(
    model: PDFModel, spans: list[Any], new_text: str | None = None
) -> bool:
    """D-RTL-GROW: do the runs ``spans`` (one edit's members, or one replayed
    neighbour) keep their RIGHT edge and grow to the left?
    ``grows_right_to_left`` over their text in reading order; a run holding
    both directions takes the base direction of the block of the first one.

    ``new_text`` is the text an EDIT draws in their place (F17-RTL-LATIN): the
    old runs say which edge the box is pinned on, the new text says how it is
    laid out, so the answer is yes only when BOTH are right-to-left.  A Hebrew
    word retyped as ``'Hello world.'`` is a left-to-right run (the first rule
    of ``grows_right_to_left``); laid out right-to-left its full stop would
    land on the wrong side and its brackets would be mirrored.  ``None`` (a
    replayed neighbour, which draws its own old text again) asks about the old
    text alone."""
    if not spans:
        return False
    ordered = sorted(
        spans,
        key=lambda s: (
            int(getattr(s, "block_idx", 0) or 0),
            int(getattr(s, "line_idx", 0) or 0),
            int(getattr(s, "span_idx", 0) or 0),
        ),
    )
    text = " ".join(str(getattr(s, "text", "") or "") for s in ordered)
    if not contains_rtl(text):
        return False  # the common case never reads the paragraph
    paragraph = _paragraph_text(model, ordered[0])
    if not grows_right_to_left(text, paragraph):
        return False
    return new_text is None or grows_right_to_left(new_text, paragraph)


def preview_insert_css(
    model: PDFModel,
    size: float,
    color: tuple,
    font_hint: str = "helv",
    line_height: float = 0.0,
    member_spans: list[Any] | None = None,
    new_text: str | None = None,
) -> str:
    """D-RTL-PREVIEW: the CSS of the live htmlbox preview of an edit of
    ``member_spans`` (``None`` / empty for a new text box) that draws
    ``new_text`` (the typed text; ``None`` when the caller has none).

    ``_build_insert_css`` plus -- when the edited runs grow right-to-left
    (``_spans_grow_right_to_left``, the commit's own rule over the run being
    edited AND the text it draws, F17-RTL-LATIN) -- ``_RTL_BASE_CSS``, so the
    preview frame keeps the box's right edge exactly where the committed
    rebuild does.  The ONE builder of preview CSS: the controller's public
    builder and the view's model-shim both come here.
    """
    css = model._build_insert_css(size, color, font_hint, line_height=line_height)
    spans = list(member_spans or [])
    if spans and _spans_grow_right_to_left(model, spans, new_text):
        css += _RTL_BASE_CSS
    return css


def _span_anchor(span: Any, rtl: bool) -> fitz.Point:
    """Where a replayed run's text starts: its ``origin``, or with ``rtl``
    its right-to-left start (``_start_point(rtl=True)`` over its box)."""
    if rtl:
        start = _start_glyph_origin(
            [span],
            int(getattr(span, "rotation", 0) or 0),
            float(getattr(span, "size", 0.0) or 0.0),
            rtl=True,
        )
        if start is not None:
            return start
    return fitz.Point(span.origin)


def _glyph_start(ch: Any, rotation: int, rtl: bool) -> tuple[float, float]:
    """One texttrace glyph's own start, the measure ``_start_point`` uses:
    its origin, or with ``rtl`` its far advance edge along the writing
    direction on its baseline."""
    if not rtl:
        return float(ch[2][0]), float(ch[2][1])
    edge, _use_max = _RTL_START_EDGE.get(rotation, _RTL_START_EDGE[0])
    if edge in (0, 2):
        return float(ch[3][edge]), float(ch[2][1])
    return float(ch[2][0]), float(ch[3][edge])

# Longest side (pt) of a placement box; MuPDF's page limit is 14400.
_PLACEMENT_BOX_LIMIT = 14000.0

# What "kept its size / its origin" means for a replayed neighbour (pt).
_REPLAY_SIZE_TOLERANCE = 0.05
_REPLAY_ORIGIN_TOLERANCE = 0.5


class _HtmlboxPlacement(NamedTuple):
    """Where an htmlbox goes so its text lands at a given origin."""

    box: fitz.Rect  # the rect to insert into (may reach past the page edge)
    ink: fitz.Rect  # union of the boxes of the glyphs it draws


class _HtmlboxProbe(NamedTuple):
    """What ``insert_htmlbox(box, html)`` draws, measured on a scratch page."""

    spare: float  # < 0: the markup does not fit at ``scale_low`` (nothing drawn)
    scale: float  # the scale htmlbox drew the markup at
    chars: list  # ``get_texttrace`` chars in DRAWING order (RTL: rightmost first)
    rotation: int  # writing direction of the drawn text, 0/90/180/270
    size: float  # largest drawn font size


def _probe_htmlbox_chars(
    page: fitz.Page,
    box: fitz.Rect,
    html: str,
    css: str,
    *,
    rotate: int,
    scale_low: float,
) -> _HtmlboxProbe:
    """``insert_htmlbox(box, html)`` drawn on a scratch page with the live
    page's size and ``/Rotate``; ``chars`` is empty when nothing was drawn."""
    page_rect = unrotated_page_rect(page)
    probe_doc = fitz.open()
    try:
        probe = probe_doc.new_page(width=page_rect.width, height=page_rect.height)
        if page.rotation:
            probe.set_rotation(page.rotation)
        spare, scale = insert_htmlbox_tracked(
            probe, box, html, css=css, rotate=rotate, scale_low=scale_low, scratch=True
        )
        if spare < 0:
            return _HtmlboxProbe(float(spare), float(scale), [], 0, 0.0)
        spans = probe.get_texttrace()
        chars = [ch for span in spans for ch in span.get("chars", ())]
        drawn = [span for span in spans if span.get("chars")]
        return _HtmlboxProbe(
            float(spare),
            float(scale),
            chars,
            rotation_degrees_from_dir(drawn[0].get("dir")) if drawn else 0,
            max((float(span.get("size") or 0.0) for span in drawn), default=0.0),
        )
    finally:
        probe_doc.close()


# Per text rotation: (axis is x, the start is the maximum) of the writing
# direction, and of the lines' stacking direction (where the first line is).
_WRITING_START_ALONG = {0: (True, False), 90: (False, False), 180: (True, True), 270: (False, True)}
_WRITING_START_ACROSS = {0: (False, False), 90: (True, True), 180: (False, True), 270: (True, False)}


def _start_glyph_origin(
    spans: list[EditableSpan], rotation: int, size: float, *, rtl: bool = False
) -> fitz.Point | None:
    """Where the first glyph of a rewrite of ``spans`` belongs (F14-VM-2):
    the origin of the run that starts the text, in the page's unrotated space.
    With ``rtl`` (D-RTL-GROW) the anchor is the right-to-left start instead:
    the FAR edge of the runs' boxes along the writing direction (the right
    edge of upright text) on the first line's baseline -- see ``_start_point``.

    The first line is the one at the writing direction's start of the lines
    (top for ``rotation`` 0, bottom for 180, the right edge for 90, the left
    edge for 270); among its runs (baselines within 0.6 em: a superscript is
    still the same line) the one nearest the text start gives the origin.  A
    multi-line extent starts every line at the extent's start edge (htmlbox
    wraps to the rect's edge, not to the first line's indent), so along the
    writing direction the extreme over ALL runs is used.  ``None`` without
    spans."""
    return _start_point(
        [(span.origin.x, span.origin.y) for span in spans],
        rotation,
        size,
        rtl=rtl,
        boxes=[tuple(fitz.Rect(span.bbox)) for span in spans] if rtl else None,
    )


# Per text rotation: does the right-to-left start (the far end of the boxes
# along the writing direction) lie on the x axis, and on which box edge
# (index into ``(x0, y0, x1, y1)``), taking the max (True) or the min.
_RTL_START_EDGE = {0: (2, True), 90: (3, True), 180: (0, False), 270: (1, False)}


def _start_point(
    points: list,
    rotation: int,
    size: float,
    *,
    rtl: bool = False,
    boxes: list | None = None,
) -> fitz.Point | None:
    """The text start of the glyph or run origins ``points`` written in
    direction ``rotation`` -- the ONE rule for where a text starts, used for
    the original runs (``_start_glyph_origin``) AND for what a probe drew
    (``_drawn_text_start``), so the two sides of a placement always measure
    the same point (F15-VM2-RTL).  Geometric, never drawing order: MuPDF draws
    a right-to-left run rightmost glyph first, but its start along the line
    is still the extreme the rotation names (the leftmost origin at 0).

    ``rtl`` (D-RTL-GROW, owner decision: a right-to-left run keeps its RIGHT
    edge): along the writing direction the start is the FAR edge of the glyph
    or run ``boxes`` ``(x0, y0, x1, y1)`` instead (upright text: the largest
    ``x1``; text written toward -x: the smallest ``x0``; down the page: the
    largest ``y1``; up it: the smallest ``y0``) -- an advance edge, not an
    origin, so a substitute font of another width still ends where the word
    ended.  Across it, the first line's baseline as for left-to-right.
    Without ``boxes`` the far-end origin is used."""
    if not points:
        return None
    rotation = rotation if rotation in (0, 90, 180, 270) else 0
    # (axis, start is the maximum) along the writing direction and across it
    along_x, along_use_max = _WRITING_START_ALONG[rotation]
    across_x, across_use_max = _WRITING_START_ACROSS[rotation]

    def _coord(point: Any, use_x: bool) -> float:
        return float(point[0] if use_x else point[1])

    pick = max if across_use_max else min
    across_extreme = pick(_coord(p, across_x) for p in points)
    first_line = [
        p for p in points if abs(_coord(p, across_x) - across_extreme) <= 0.6 * max(size, 1.0)
    ] or list(points)
    along_pick = max if along_use_max else min
    start = along_pick(first_line, key=lambda p: _coord(p, along_x))
    along_value = along_pick(_coord(p, along_x) for p in points)
    across_value = _coord(start, across_x)
    if rtl:
        edge, use_max = _RTL_START_EDGE[rotation]
        end_pick = max if use_max else min
        along_value = (
            end_pick(float(box[edge]) for box in boxes)
            if boxes
            else end_pick(_coord(p, along_x) for p in points)
        )
    return (
        fitz.Point(along_value, across_value)
        if along_x
        else fitz.Point(across_value, along_value)
    )


def _drawn_text_start(probe: _HtmlboxProbe, *, rtl: bool = False) -> fitz.Point | None:
    """Where the text a probe drew starts (``_start_point`` over its glyph
    origins, and with ``rtl`` over its glyph boxes), ``None`` when it drew
    nothing.  Not ``chars[0]``: the first DRAWN glyph of right-to-left text is
    its rightmost one."""
    return _start_point(
        [ch[2] for ch in probe.chars],
        probe.rotation,
        probe.size,
        rtl=rtl,
        boxes=[ch[3] for ch in probe.chars] if rtl else None,
    )


# Leading line breaks of an htmlbox markup: ``_convert_text_to_html`` /
# ``_build_multi_style_html`` write one ``<br>`` per ``\n``.
_LEADING_BREAKS_RE = re.compile(r"^(?:\s*<br\s*/?>)+", re.IGNORECASE)


def _place_htmlbox_at_origin(
    page: fitz.Page,
    html: str,
    css: str,
    *,
    text: str,
    size: float,
    origin: fitz.Point,
    anchor: fitz.Rect,
    rotate: int = 0,
    rtl: bool = False,
) -> _HtmlboxPlacement:
    """The box to hand ``insert_htmlbox`` so the text of ``html`` is drawn at
    ``size`` with its first glyph on ``origin`` -- F13-VF-3.

    Giving htmlbox the tight bbox of the text it replaces (``scale_low=0``)
    lets MuPDF shrink an untouched neighbour to fit a line box taller than
    that bbox (60 pt -> 43 pt) and re-anchors its baseline.  A box too long
    and too tall to constrain anything makes the markup draw at its natural
    size; where the first glyph lands in it is measured on a scratch page of
    the live page's geometry (htmlbox's layout is a pure translation of the
    box), and the box is moved by the difference.  ``anchor`` is only where
    the replaced text was: the centre the oversized box is built around.
    With ``rtl`` the text is right-to-left (D-RTL-GROW): ``origin`` is its
    right-to-left start (``_start_point(rtl=True)``, the right edge of
    upright text) and the drawn text is measured the same way.
    Raises when the markup cannot be drawn at its size or draws nothing."""
    lines = text.count("\n") + 1
    run = min(
        _PLACEMENT_BOX_LIMIT,
        max(anchor.width, anchor.height) + size * (2.0 * len(text) + 4.0),
    )
    across = min(_PLACEMENT_BOX_LIMIT, max(6.0 * size * lines, 16.0))
    width, height = (run, across) if rotate in (0, 180) else (across, run)
    cx, cy = (anchor.x0 + anchor.x1) / 2.0, (anchor.y0 + anchor.y1) / 2.0
    trial = fitz.Rect(cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)

    probe = _probe_htmlbox_chars(page, trial, html, css, rotate=rotate, scale_low=1)
    if probe.spare < 0:
        raise RuntimeError(
            f"htmlbox cannot draw the text at {size}pt in a {width:.0f}x{height:.0f}pt box"
        )
    chars = probe.chars
    start = _drawn_text_start(probe, rtl=rtl)
    if not chars or start is None:
        raise RuntimeError("htmlbox drew no glyphs for the text")
    # ``origin`` is the replayed text's START (a run origin, or the push-down
    # span's geometric start), so it is matched with the drawn text's start,
    # never with its first DRAWN glyph (F15-VM2-RTL).
    dx = float(origin.x) - float(start.x)
    dy = float(origin.y) - float(start.y)
    ink = rect_union([fitz.Rect(ch[3]) for ch in chars])
    return _HtmlboxPlacement(trial + (dx, dy, dx, dy), ink + (dx, dy, dx, dy))


def _align_htmlbox_rect(
    page: fitz.Page,
    box: fitz.Rect,
    html: str,
    css: str,
    *,
    origin: fitz.Point | None,
    rotate: int,
    scale_low: float,
    rtl: bool = False,
) -> fitz.Rect:
    """``box`` moved so ``insert_htmlbox(box, html, scale_low=scale_low)``
    draws its first glyph on ``origin`` -- F14-VM-2.

    MuPDF starts the text 1 pt inside the rect's left edge and puts the
    baseline at the line box's ascent of the substitute font, so a rect set
    from the replaced run's bbox draws the rewrite off its original origin
    (+1.0 pt x and up to ~2.5 pt of baseline at 48 pt) and a drag adds that
    error on every move.  The box keeps its size (so fit, wrap and shrink are
    those of the box the caller chose); only its position changes, by the
    difference measured on a scratch page of the live page's geometry (the
    layout is a translation of the box).  ``box`` itself when ``origin`` is
    ``None``, when the markup does not fit at ``scale_low`` (the live insert
    then draws nothing either) or when the probe fails: the placement is a
    refinement, never a reason to fail an edit.

    What lands on ``origin`` is the START of the first line, measured with
    the rule ``_start_glyph_origin`` used for the target (F15-VM2-RTL): not
    the first DRAWN glyph, which for right-to-left text is the rightmost one
    (the rewrite moved left by its own width).  A markup that starts with
    blank lines (the user pressed Enter before the text) has no glyph on its
    first line: the start is measured on the markup without those
    ``<br>``s in the same box, so the first (blank) line takes ``origin`` and
    the text is drawn the blank lines' htmlbox height further on, instead
    of being pulled back onto the original baseline.  When the two markups
    would be drawn at different scales (``scale_low < 1`` shrank one) the
    measurement does not transfer and the box is kept.

    ``rtl`` (D-RTL-GROW): ``origin`` is the right-to-left start of the
    target (``_start_glyph_origin(rtl=True)``) and the drawn text is measured
    by the same rule, so a longer right-to-left rewrite keeps its right edge
    and grows left."""
    if origin is None:
        return box
    try:
        full = _probe_htmlbox_chars(page, box, html, css, rotate=rotate, scale_low=scale_low)
        if full.spare < 0 or not full.chars:
            return box
        measured = full
        leading_breaks = _LEADING_BREAKS_RE.match(html)
        if leading_breaks:
            measured = _probe_htmlbox_chars(
                page, box, html[leading_breaks.end():], css,
                rotate=rotate, scale_low=scale_low,
            )
            if (
                measured.spare < 0
                or not measured.chars
                or abs(measured.scale - full.scale) > 1e-6
            ):
                logger.debug(
                    "first-line placement: the markup without its leading breaks "
                    "draws differently (box kept)"
                )
                return box
    except Exception as exc:
        logger.debug("first-glyph placement probe failed (box kept): %s", exc)
        return box
    start = _drawn_text_start(measured, rtl=rtl)
    if start is None:
        return box
    dx = float(origin.x) - float(start.x)
    dy = float(origin.y) - float(start.y)
    return box + (dx, dy, dx, dy)


def _insert_htmlbox_unshrunk(
    page: fitz.Page, box: fitz.Rect, html: str, css: str, *, rotate: int = 0
) -> None:
    """``insert_htmlbox`` that never shrinks the text (``scale_low=1``); raises
    instead, nothing drawn, when it would have to."""
    spare, _scale = insert_htmlbox_tracked(page, box, html, css=css, rotate=rotate, scale_low=1)
    if spare < 0:
        raise RuntimeError("htmlbox would have to shrink the text to draw it")


class _TextLayerProblem(str):
    """Why a htmlbox insert is refused: the technical text (a ``str``, logged)
    plus the stable refusal code the Controller maps to a zh-TW sentence."""

    reason: TextEditRefusal

    def __new__(cls, reason: TextEditRefusal, detail: str) -> _TextLayerProblem:
        problem = super().__new__(cls, detail)
        problem.reason = reason
        return problem


def _lossy_text_layer_problem(
    requested: str,
    page_text: str,
    reference: _HtmlboxReference,
    page_glyphs: Counter[tuple[str, int]],
    acknowledged: tuple[UnkeepableGlyph, ...] | list[UnkeepableGlyph] = (),
) -> _TextLayerProblem | None:
    """Why a htmlbox insert whose text layer lacks requested characters must
    still be refused, or ``None`` when the loss is only the accepted
    text-layer limitation (owner decision OD-UNI1-COMMIT).

    PyMuPDF 1.27's htmlbox draws emoji, other non-BMP characters and shaped
    clusters (Indic conjuncts, Arabic lam-alef, ...) correctly but writes a
    wrong ToUnicode for them: non-BMP code points cut to 16 bits, shaped
    glyphs written as their glyph ids.  Such characters are accepted on
    GLYPH evidence; everything else keeps the text-presence contract:

    * a requested character that htmlbox's own text layer DOES carry (the
      scratch reference has it) but the page lacks was really lost;
    * a placeholder without a Unicode identity (U+FFFD, U+FFFC, controls,
      PUA, unassigned -- ``_is_identityless_placeholder``) is forgiven ONLY when
      it is in ``acknowledged``: untouched glyphs the user was told the
      rebuild cannot keep and consented to (F11-UNI-1 decision C).  htmlbox
      draws them as a replacement glyph or .notdef, never as the source
      glyph;
    * a .notdef in the reference means htmlbox has no font for some
      requested character -- the page would show nothing (or a box) there;
      only the acknowledged ``"removed"`` glyphs may account for one;
    * every glyph the reference draws must be drawn on the page.
    """
    lost = _lost_requested_chars(requested, page_text)
    if not lost:
        return None
    acknowledged_labels, acknowledged_notdef = _acknowledged_labels(acknowledged)
    layer_lossy = set(_lost_requested_chars(requested, reference.text))
    # The ``U+XXXX`` labels of ``lost`` that name an identity-less placeholder.
    placeholders = {label for label in lost if _is_identityless_placeholder(_label_char(label))}
    really_lost = [
        label
        for label in lost
        if label not in layer_lossy
        or (label in placeholders and label not in acknowledged_labels)
    ]
    if really_lost:
        # Only identity-less placeholders nobody acknowledged: the user can
        # fix that by confirming (or removing them); anything else is text
        # that really did not reach the page.
        placeholders_only = all(label in placeholders for label in really_lost)
        return _TextLayerProblem(
            TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED
            if placeholders_only
            else TextEditRefusal.CHARACTERS_LOST,
            "requested characters are not on the page after the insert: "
            f"{', '.join(really_lost)}",
        )
    if reference.notdef > acknowledged_notdef:
        ext_b_reason = ext_b_refusal_reason(requested)
        detail = (
            "no font draws some of the requested characters (.notdef glyph): "
            f"{', '.join(lost)}"
        )
        if ext_b_reason:
            detail += f"; {ext_b_reason}"
            # "Install the system Ext-B fonts" only where that can help
            # (Windows, none installed); an installed font that lacks the glyph
            # (Ext-G) or a platform with no lookup gets the plain "use other
            # characters" sentence (F12-DLG-4).
            if ext_b_install_would_help():
                return _TextLayerProblem(TextEditRefusal.EXT_B_FONT_MISSING, detail)
            # Fonts installed but fontTools unimportable: a broken install,
            # not a font without the glyph (F13-ENV-3).
            if ext_b_component_missing():
                return _TextLayerProblem(TextEditRefusal.EXT_B_COMPONENT_MISSING, detail)
        return _TextLayerProblem(TextEditRefusal.NO_FONT_FOR_CHARACTERS, detail)
    undrawn = reference.glyphs - page_glyphs
    if undrawn:
        return _TextLayerProblem(
            TextEditRefusal.GLYPHS_NOT_DRAWN,
            f"the glyphs for {', '.join(lost)} are not drawn on the page after the "
            f"insert ({sum(undrawn.values())} missing)",
        )
    return None


def _classify_insert_path(
    *,
    new_text: str,
    member_spans: list,
    rotation: int,
    is_vertical: bool,
    preserve_multi_style: bool,
    has_new_rect: bool,
    needs_cjk: bool,
    text_width: float,
    available_width: float,
    size: float,
    rtl: bool = False,
) -> Literal["htmlbox", "fast"]:
    """Shared insert-path classifier: ``"fast"`` (single-line ``insert_text``)
    vs ``"htmlbox"`` (``insert_htmlbox``).

    The preview renderer (view) and the commit path (model) MUST both route
    through this function so an opened editor and the committed PDF never
    diverge in which renderer drew the glyphs.

    ``"fast"`` is chosen only for the strict single-line, single-style,
    unrotated, no-wrap, printable-Latin-1 case that ``page.insert_text`` can
    reproduce exactly (``_simple_font_can_encode``: any other character would
    be written as U+00B7, F10-UNI-1).
    Empty ``member_spans`` always falls back to ``"htmlbox"``: there is no
    anchor span to derive the ``insert_text`` origin from, and a downstream
    ``min(member_spans, ...)`` would raise.
    A right-to-left edit (``rtl``, D-RTL-GROW) is always ``"htmlbox"``:
    ``insert_text`` writes from the left origin, the rule anchors the right
    edge (a mixed run in a right-to-left paragraph can be Latin-1).
    """
    if not member_spans:
        return "htmlbox"
    if rtl:
        return "htmlbox"
    if is_vertical:
        return "htmlbox"
    # insert_text(rotate=0) writes upright text along +x: right only for a run
    # written along +x.  Every turned run -- 180 as well as the quarter turns --
    # needs the htmlbox, which follows the run's direction (F15-VM2-FAST180).
    if rotation != 0:
        return "htmlbox"
    if has_new_rect:
        return "htmlbox"
    if "\n" in (new_text or ""):
        return "htmlbox"
    if needs_cjk:
        return "htmlbox"
    if not _simple_font_can_encode(new_text):
        return "htmlbox"
    if preserve_multi_style:
        return "htmlbox"
    try:
        span_top = min(float(s.bbox.y0) for s in member_spans)
        span_bot = max(float(s.bbox.y1) for s in member_spans)
    except (AttributeError, TypeError, ValueError):
        return "htmlbox"
    if (span_bot - span_top) > max(2.0, float(size) * 1.5):
        return "htmlbox"
    if not (0.0 < float(text_width) <= float(available_width)):
        return "htmlbox"
    return "fast"


# insert_htmlbox always uses about 2 pt of leading on top of the text lines.
_HTMLBOX_LEADING_OVERHEAD = 2.0

# Slack when comparing a run's width with the gap to the next run: PyMuPDF
# reports bboxes as float32 and the original word usually ends flush against it.
_NEIGHBOUR_FIT_TOL_PT = 0.25


# max(|dx|, |dy|) of a unit vector 2.5 degrees off an axis is 0.9990; MuPDF
# reports exact axis directions, so anything this close is on the axis.
_AXIS_ALIGNED_TOL = 1e-3


def _is_axis_aligned_dir(direction: object) -> bool:
    """True when a writing direction lies on a page axis (0/90/180/270 degrees).

    Only for such text is the extracted axis-aligned bbox the text's own
    footprint.  A run turned off the axes (a 45-degree "DRAFT" watermark, a
    skewed stamp) has a bbox that is a large square around a thin diagonal of
    ink; treating that square as a neighbour, a floor or an ink core refuses or
    shrinks edits on lines the text never touches (F15-VF4OV-DIAGONAL).
    A missing or malformed direction counts as axis-aligned (the old reading).
    """
    try:
        dx, dy = abs(float(direction[0])), abs(float(direction[1]))  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return True
    norm = (dx * dx + dy * dy) ** 0.5
    if norm <= 1e-6:
        return True
    return max(dx, dy) / norm >= 1.0 - _AXIS_ALIGNED_TOL


def _neighbour_limit(
    model: PDFModel,
    page_idx: int,
    member_spans: list,
    target_member_span_ids: set[str],
    *,
    along_x: bool,
    toward_min: bool,
) -> float | None:
    """The ONE wall rule of ``_horizontal_neighbour_limit`` and
    ``_vertical_neighbour_limit`` (F13-VF-4, F13-VF-4b, F14-VF4-OVERLAP),
    stated on the axis the edited run(s) grow along: page x (``along_x``) or
    page y, toward smaller coordinates (``toward_min``: an upside-down run, a
    run reading up the page) or larger ones.  Every direction is this rule
    with the axes swapped, so a change to it cannot drift between them.

    An untouched run (not a member, carrying text, on a page axis) walls the
    edit when it shares the band across the growth axis (more than half of
    the narrower extent overlaps) and, along it, starts at or past the edited
    extent's far edge (its near edge is the wall) -- or starts inside the
    extent but sticks out past that edge (negative kerning, condensed spacing
    across a style change, float32 bbox overlap): it is replayed at its
    origin, which does not keep a GROWN edit from being drawn over it, and
    the old text already reached that far, so its wall is the extent's old
    far edge.  Runs behind the start, or wholly inside the extent, never wall
    the edit.  The nearest wall wins; ``None`` = nothing on the growth side.
    """
    spans = [s for s in member_spans if s is not None]
    if not spans:
        return None
    extent = rect_union([fitz.Rect(s.bbox) for s in spans])
    if extent.is_empty:
        return None
    tol = _NEIGHBOUR_FIT_TOL_PT

    def _axes(rect: fitz.Rect) -> tuple[float, float, float, float, float]:
        """``(lo, hi)`` along the growth axis, ``(lo, hi, length)`` across it."""
        if along_x:
            return rect.x0, rect.x1, rect.y0, rect.y1, rect.height
        return rect.y0, rect.y1, rect.x0, rect.x1, rect.width

    e_lo, e_hi, e_alo, e_ahi, e_alen = _axes(extent)
    nearest = max if toward_min else min
    limit: float | None = None
    for run in model.block_manager.get_runs(page_idx):
        if run.span_id in target_member_span_ids or not (run.text or "").strip():
            continue
        r = fitz.Rect(run.bbox)
        if r.is_empty or not _is_axis_aligned_dir(run.dir_vec):
            continue
        lo, hi, alo, ahi, alen = _axes(r)
        if min(ahi, e_ahi) - max(alo, e_alo) <= 0.5 * min(alen, e_alen):
            continue  # another line band / column
        if toward_min:
            if hi <= e_lo + tol:
                wall = float(hi)
            elif hi < e_hi - tol and lo < e_lo - tol:
                wall = float(e_lo)  # ends inside, sticks out past the start
            else:
                continue  # behind the start, or wholly inside the extent
        elif lo >= e_hi - tol:
            wall = float(lo)
        elif lo > e_lo + tol and hi > e_hi + tol:
            wall = float(e_hi)  # starts inside, sticks out past the far edge
        else:
            continue  # behind the start, or wholly inside the extent
        limit = wall if limit is None else nearest(limit, wall)
    return limit


def _right_neighbour_limit(
    model: PDFModel,
    page_idx: int,
    member_spans: list,
    target_member_span_ids: set[str],
) -> float | None:
    """``_horizontal_neighbour_limit`` for a run written toward +x."""
    return _horizontal_neighbour_limit(
        model, page_idx, member_spans, target_member_span_ids, grows_left=False
    )


def _horizontal_neighbour_limit(
    model: PDFModel,
    page_idx: int,
    member_spans: list,
    target_member_span_ids: set[str],
    *,
    grows_left: bool,
) -> float | None:
    """Edge of the nearest untouched run on the side the edited run(s) GROW toward.

    Written toward +x (``grows_left`` False) that is the left edge of the nearest
    run to the RIGHT.  An upside-down run (text rotation 180) is written toward
    -x, so the run it grows into is the nearest one to the LEFT and the wall is
    that run's right edge; a run on the other side is behind the text's start and
    never walls it (F16-2: the +x wall of an upside-down run capped it at the
    word's own width and shrank it, while the side it grows into had no wall).
    The rule (``_neighbour_limit``) is stated here for +x; ``grows_left``
    mirrors it.

    The rebuild re-draws the edited text at its old origin in the substitute
    font, which is often wider than the original; the page's right safe margin
    is not the only wall -- the next run on the line stays where it is and the
    new text must not be drawn over it (F13-VF-4).  A run counts when it is not
    one of the edited members, carries text, and shares the edited line band
    (more than half of the shorter height overlaps); it must start at or past
    the edited extent's right edge, or begin inside it but stick out of it past
    the edit's own origin (they are replayed at their origin, which does not
    keep a grown edit from being drawn over them; their wall is the extent's
    old right edge, F14-VF4-OVERLAP).  Runs that start at or left of the
    edit's origin, or lie wholly inside the extent, are not right-hand
    neighbours.  Neither is a run written off the page axes (a diagonal
    watermark or stamp): its bbox is a square around a thin diagonal, not the
    ink on this line, so it never walls the edit; real ink under the new text
    is the overprint guard's call (F15-VF4OV-DIAGONAL).  A run on another axis
    (90 degrees) keeps its bbox, which is its footprint.  ``None`` = nothing on
    the growth side (the right for +x, the left for ``grows_left``).
    """
    return _neighbour_limit(
        model, page_idx, member_spans, target_member_span_ids,
        along_x=True, toward_min=grows_left,
    )


def _vertical_neighbour_limit(
    model: PDFModel,
    page_idx: int,
    member_spans: list,
    target_member_span_ids: set[str],
    *,
    reads_up: bool,
) -> float | None:
    """The page-y wall the edited quarter-turn run(s) may not grow past.

    The vertical twin of ``_horizontal_neighbour_limit`` (F13-VF-4b; the same
    rule, ``_neighbour_limit``, on page y): a quarter-turn
    run is re-drawn at its old start and grows ALONG its reading direction --
    down the page, or up it when ``reads_up`` -- and the next untouched run on
    the same column stays where it is, so the new text must stop short of it.
    A run counts when it is not one of the edited members, carries text, lies
    on a page axis, shares the edited column (more than half of the narrower
    width overlaps across the reading direction) and starts at or past the
    extent's far edge, or starts inside it but sticks out past that edge (its
    wall is then the old far edge: the edit may not get longer than it was,
    F14-VF4-OVERLAP).  Reading down the wall is the neighbour's top edge, the
    smallest such; reading up it is the neighbour's bottom edge, the largest.
    Runs behind the start, on another column or off the axes (a diagonal
    stamp's bbox is a square, not ink on this column) never wall the edit.
    ``None`` = nothing further along the column.
    """
    return _neighbour_limit(
        model, page_idx, member_spans, target_member_span_ids,
        along_x=False, toward_min=reads_up,
    )


def _right_safe(page_rect: fitz.Rect, size: float) -> float:
    """The page's safe right margin line: ``max(60, min(120, 2 * size))`` pt
    in from the edge."""
    return float(page_rect.x1) - max(60.0, min(120.0, float(size) * 2.0))


def _right_wall(page_rect: fitz.Rect, size: float, extent: fitz.Rect) -> float:
    """Right limit of a horizontal in-place rebuild of the run(s) in ``extent``.

    Normally the page's safe right margin (``max(60, min(120, 2 * size))`` from
    the edge): a re-broken paragraph keeps clear of it.  Text that ALREADY
    reaches past it (a title or a page number set in the margin) never honoured
    that margin, and clamping its box to it makes the box narrower than the
    word itself -- the word re-wraps onto several lines, pushes the lines below
    down, or (start past the margin) gets an inverted box and a false
    ``TEXT_DOES_NOT_FIT`` (F14-DT-1).  For such text the wall is the page edge
    less 10 pt, the bound a dragged box and strategy B use, for a single line;
    a multi-line extent (a paragraph) keeps at least its own old right edge.
    The wall never lies left of the extent, and never beyond the page.  A wall
    other than ``_right_safe`` is already a hard limit: the caller adds no
    further slack to it.
    """
    right_safe = _right_safe(page_rect, size)
    if extent.is_empty or extent.x1 <= right_safe:
        return right_safe
    wall = min(float(extent.x1), float(page_rect.x1))
    if float(extent.height) <= max(2.0, float(size) * 1.5):
        wall = max(wall, float(page_rect.x1) - 10.0)
    return wall


def _left_safe(page_rect: fitz.Rect, size: float) -> float:
    """The page's safe LEFT margin line, the mirror of ``_right_safe`` (the
    margin an upside-down run grows toward)."""
    return float(page_rect.x0) + max(60.0, min(120.0, float(size) * 2.0))


def _left_wall(page_rect: fitz.Rect, size: float, extent: fitz.Rect) -> float:
    """Left limit of an in-place rebuild of the upside-down run(s) in ``extent``
    (F16-2): exactly ``_right_wall`` seen in the page mirrored about its
    vertical axis, so the two cannot drift."""
    axis = float(page_rect.x0) + float(page_rect.x1)
    mirrored = (
        extent
        if extent.is_empty
        else fitz.Rect(axis - extent.x1, extent.y0, axis - extent.x0, extent.y1)
    )
    return axis - _right_wall(page_rect, size, mirrored)


def _has_complex_script(model: PDFModel, text: str) -> bool:
    """
    判斷文字是否包含常見複雜腳本（RTL/CJK）。
    用於在文字擷取不穩定時放寬驗證閾值（僅限特定流程）。
    """
    if not text:
        return False
    return bool(
        re.search(
            r"[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
            text,
        )
    )


def _push_down_can_move(block: dict, above_y: float) -> bool:
    """Whether ``_push_down_overlapping_text`` may ever move this text block.

    Only blocks that START below the edit move (``bbox.y0 >= above_y - 1``):
    the following lines of the edited paragraph are the SAME block and stay
    where they are.  WMode 1 (vertical) glyphs cannot be redacted by their
    extracted boxes (F10-UNI-3): redact + replay would keep the original and
    add a copy, so such a block is left where it is -- as is one with a line
    written off the page axes (F15-VM2-FAST180).  The wrap floor
    (``_wrap_floor``) uses the same rule, so the two cannot drift
    (F14-VF4-WRAP).
    """
    if block.get("type") != 0:
        return False
    if any(int(line.get("wmode", 0) or 0) == 1 for line in block.get("lines", [])):
        logger.debug("_push_down_overlapping_text: 略過垂直書寫 block")
        return False
    # A line written off the page axes (a diagonal stamp) cannot be redrawn by
    # a quarter-turn htmlbox: it came back upright (F15-VM2-FAST180).
    if not all(_is_axis_aligned_dir(line.get("dir")) for line in block.get("lines", [])):
        logger.debug("_push_down_overlapping_text: skipping a block written off the axes")
        return False
    return float(block["bbox"][1]) >= above_y - 1.0


def _untouched_span_rects(
    page: fitz.Page,
    edited_extent: fitz.Rect,
    x0: float,
    x1: float,
    *,
    skip_block: Callable[[dict], bool] | None = None,
) -> list[fitz.Rect]:
    """The boxes of the text spans that can bound a wrap: inside the htmlbox
    columns ``[x0, x1]``, carrying text, written on a page axis (a diagonal
    run's bbox is no ink on this column, F15-VF4OV-DIAGONAL) and NOT on the
    edited line (its neighbours are walled by ``_horizontal_neighbour_limit``).
    ``skip_block`` leaves out whole text blocks."""
    raw = content_text(page, "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    rects: list[fitz.Rect] = []
    for block in raw.get("blocks", ()):
        if block.get("type") != 0 or (skip_block is not None and skip_block(block)):
            continue
        for line in block.get("lines", ()):
            if not _is_axis_aligned_dir(line.get("dir")):
                continue
            for span in line.get("spans", ()):
                if not (span.get("text") or "").strip():
                    continue
                r = fitz.Rect(span["bbox"])
                if r.is_empty or r.x1 <= x0 + 0.5 or r.x0 >= x1 - 0.5:
                    continue
                overlap = min(r.y1, edited_extent.y1) - max(r.y0, edited_extent.y0)
                if overlap > 0.5 * min(r.height, edited_extent.height):
                    continue
                rects.append(r)
    return rects


def _wrap_floor(
    page: fitz.Page,
    edited_extent: fitz.Rect,
    x0: float,
    x1: float,
    above_y: float,
) -> float | None:
    """Top of the nearest untouched text BELOW the edited line, inside the
    htmlbox columns ``[x0, x1]``, that the push-down will never move.

    A horizontal rebuild draws its htmlbox from the edited line down towards
    the page foot; the wrapped lines get room only where the push-down can
    clear it.  The next lines of the edited paragraph (same block) and any
    block that starts above the edit stay put, so the wrap must end above them
    (F14-VF4-WRAP).  Read after the redaction, so lines that are themselves
    rewritten (paragraph mode) are gone.  ``None`` = nothing bounds the wrap.
    """
    mid = edited_extent.y0 + edited_extent.y1
    below = [
        float(r.y0)
        for r in _untouched_span_rects(
            page, edited_extent, x0, x1,
            skip_block=lambda block: _push_down_can_move(block, above_y),
        )
        if (r.y0 + r.y1) > mid
    ]
    return min(below) if below else None


def _wrap_ceiling(
    page: fitz.Page,
    edited_extent: fitz.Rect,
    x0: float,
    x1: float,
) -> float | None:
    """Bottom of the nearest untouched text ABOVE the edited line, inside the
    htmlbox columns ``[x0, x1]``.

    The mirror of ``_wrap_floor`` for an upside-down run (F16-2): its extra lines
    stack UP the page, and nothing is pushed up out of the way (the push-down
    only moves blocks downward), so every untouched line above the edit bounds
    the wrap, whichever block it belongs to.  Read after the redaction, so the
    edited text itself is gone.  ``None`` = nothing bounds the wrap.
    """
    mid = edited_extent.y0 + edited_extent.y1
    above = [
        float(r.y1)
        for r in _untouched_span_rects(page, edited_extent, x0, x1)
        if (r.y0 + r.y1) < mid
    ]
    return max(above) if above else None


# A glyph's ink core for the overprint check (F14-VF4-WRAP): the middle 70 %
# of its advance and the band 0.1-0.6 em above the baseline.  Extracted boxes
# are the font's whole ascender-descender box, which legitimately touches the
# next line under tight leading and the next run on the line.
_INK_CORE_TRIM = 0.15
_INK_CORE_BAND_EM = (0.1, 0.6)


# An ink core is a ``fitz.Rect`` for text on a page axis, or the four corners
# of the turned box for text written off the axes (F15-VF4OV-DIAGONAL).
_InkCore: TypeAlias = "fitz.Rect | tuple[tuple[float, float], ...]"


def _glyph_ink_core(g: _PageGlyph) -> _InkCore:
    ux, uy = g.direction
    vx, vy = uy, -ux  # "up" in page space (y points down)
    ox, oy = g.origin
    em = g.size if g.size > 0 else abs(g.bbox.height)
    b0, b1 = (em * f for f in _INK_CORE_BAND_EM)
    if _is_axis_aligned_dir(g.direction):
        bbox = g.bbox
        along = [
            (cx - ox) * ux + (cy - oy) * uy
            for cx in (bbox.x0, bbox.x1)
            for cy in (bbox.y0, bbox.y1)
        ]
        a0, a1 = min(along), max(along)
        trim = (a1 - a0) * _INK_CORE_TRIM
        a0, a1 = a0 + trim, a1 - trim
        xs = [ox + ux * a + vx * b for a in (a0, a1) for b in (b0, b1)]
        ys = [oy + uy * a + vy * b for a in (a0, a1) for b in (b0, b1)]
        return fitz.Rect(min(xs), min(ys), max(xs), max(ys))
    # Off the axes the extracted box is the bbox of the TURNED glyph box -- a
    # square several times the glyph -- so its projection overstates the glyph
    # and the axis-aligned core of that is a block that reaches lines the
    # glyph never touches.  Use the glyph's own length (its advance) and keep
    # the turned corners.
    advance = g.advance if g.advance > 0 else 0.5 * em
    trim = advance * _INK_CORE_TRIM
    a0, a1 = trim, advance - trim
    return tuple(
        (ox + ux * a + vx * b, oy + uy * a + vy * b)
        for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))
    )


def _core_polygon(core: _InkCore) -> tuple[tuple[float, float], ...]:
    if isinstance(core, fitz.Rect):
        return ((core.x0, core.y0), (core.x1, core.y0), (core.x1, core.y1), (core.x0, core.y1))
    return core


def _polygons_overlap(
    a: tuple[tuple[float, float], ...], b: tuple[tuple[float, float], ...]
) -> bool:
    """Separating-axis test for two convex polygons; touching is no overlap
    (the same 0.05 pt margin as the axis-aligned test)."""
    for poly in (a, b):
        for i in range(len(poly)):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % len(poly)]
            nx, ny = y1 - y0, x0 - x1
            length = (nx * nx + ny * ny) ** 0.5
            if length <= 1e-9:
                continue
            nx, ny = nx / length, ny / length
            pa = [x * nx + y * ny for x, y in a]
            pb = [x * nx + y * ny for x, y in b]
            if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= 0.05:
                return False
    return True


def _cores_overlap(a: _InkCore, b: _InkCore) -> bool:
    if isinstance(a, fitz.Rect) and isinstance(b, fitz.Rect):
        return (
            min(a.x1, b.x1) - max(a.x0, b.x0) > 0.05 and min(a.y1, b.y1) - max(a.y0, b.y0) > 0.05
        )
    return _polygons_overlap(_core_polygon(a), _core_polygon(b))


def _new_text_overprints(
    before: list[_PageGlyph],
    after: list[_PageGlyph],
    exempt: list[fitz.Rect],
) -> list[str]:
    """Glyphs the insert added whose ink core lies on an untouched glyph's.

    ``before`` is the page right before the edited text is inserted (after
    the redaction, the protected-span replay and the push-down), so every
    glyph of ``after`` with no same-character glyph within
    ``_GLYPH_MATCH_TOL`` of its origin in ``before`` is the edit's own text.
    An untouched glyph whose core overlaps an ``exempt`` rect may be covered.
    Untouched glyphs written off the page axes (a 45-degree watermark, a
    skewed stamp) are no collision: the edit may print over them (D-DIAG-INK,
    owner decision); horizontal and vertical runs still block.
    """
    existed = {id(g) for g in _glyphs_still_present(after, before)}
    added = [g for g in after if g.inked and id(g) not in existed]
    if not added:
        return []
    # Only glyphs near the inserted text can be under it.
    reach = rect_union([g.bbox for g in added])
    pad = max(g.size for g in added) or 12.0
    reach = fitz.Rect(reach.x0 - pad, reach.y0 - pad, reach.x1 + pad, reach.y1 + pad)
    untouched = [
        (g, core)
        for g in before
        if g.inked and g.bbox.intersects(reach) and _is_axis_aligned_dir(g.direction)
        for core in (_glyph_ink_core(g),)
        if not any(_cores_overlap(core, e) for e in exempt)
    ]
    hits: list[str] = []
    for g in added:
        core = _glyph_ink_core(g)
        for u, ucore in untouched:
            if _cores_overlap(core, ucore):
                hits.append(f"{g.key[0]!r} over {u.key[0]!r} at ({u.origin[0]:.1f}, {u.origin[1]:.1f})")
                break
    return hits


def _raw_span_chars(raw_glyphs: dict, block_idx: int, line_idx: int, span_idx: int) -> list:
    """The ``chars`` of one span of ``raw_glyphs`` (a ``rawdict``), located
    by its block / line / span indexes in that extraction; ``[]`` when the
    span cannot be found."""
    try:
        span = raw_glyphs["blocks"][block_idx]["lines"][line_idx]["spans"][span_idx]
        return list(span.get("chars", ()))
    except (KeyError, IndexError, TypeError):
        return []


def _push_down_span_start(
    raw_chars: list, line: dict, span: dict, *, rtl: bool = False
) -> fitz.Point:
    """Where a pushed-down ``dict`` span's text starts: ``_start_point`` over
    the origins of its glyphs ``raw_chars`` (``_raw_span_chars`` of the same
    text page's ``rawdict``), the measure ``_place_htmlbox_at_origin`` matches
    the replay with; with ``rtl`` (D-RTL-GROW) its right-to-left start over
    the glyph boxes.  The span's own ``origin`` when its glyphs cannot be
    found."""
    origin = span["origin"]
    chars = [ch for ch in raw_chars if ch.get("origin")]
    start = _start_point(
        [ch["origin"] for ch in chars],
        rotation_degrees_from_dir(line.get("dir")),
        float(span.get("size") or 0.0),
        rtl=rtl,
        boxes=[tuple(ch["bbox"]) for ch in chars if ch.get("bbox")] if rtl else None,
    )
    return start if start is not None else fitz.Point(origin[0], origin[1])


def _push_down_overlapping_text(
    model: PDFModel,
    page: fitz.Page,
    page_rect: fitz.Rect,
    above_y: float,
    new_bottom: float,
    edit_x0: float,
    edit_x1: float,
) -> None:
    """
    換行溢出修正：將位於 [above_y, new_bottom] Y 區間內（且與
    [edit_x0, edit_x1] X 範圍有重疊）的文字塊向下推移，使它們
    落在 new_bottom 之後，保留原有文字內容，不重疊於新插入的文字。

    支援 cascade：每個 block 推移後，若與下一個 block 仍有重疊，
    自動繼續推移，直到頁面底部。

    Args:
        page       : 當前頁面物件
        page_rect  : 頁面邊界 Rect
        above_y    : 原始 block 的底部 Y（= redact_rect.y1）
        new_bottom : 新插入文字的底部 Y（= shrunk_rect.y1）
        edit_x0    : 編輯區 X 左邊界
        edit_x1    : 編輯區 X 右邊界
    """
    GAP   = 2.0   # 推移後與上方文字的最小間距
    X_TOL = 5.0   # X 方向重疊容差
    page_idx = page.number

    # ── 1. 取得整頁文字結構 ──
    # 不使用 TEXT_PRESERVE_LIGATURES：確保 span 文字中的 ﬁ/ﬀ/ﬂ 等合字
    # 已被展開（ﬁ→fi、ﬀ→ff 等），避免 insert_text(helv) 因字型不支援合字
    # 而靜默丟棄字元，導致 push-down 後文字殘缺。
    # Content only (F11-ANN-4): an annotation's appearance text is not a text
    # block; pushing it down would re-insert it as page content.
    _pd_textpage = content_textpage(page, fitz.TEXT_PRESERVE_WHITESPACE)
    raw = content_text(page, "dict", textpage=_pd_textpage)
    # Same text page, so the same blocks/lines/spans: the glyph origins give
    # each pushed span its geometric START (F15-VM2-RTL); a dict span's
    # ``origin`` is its first glyph in DRAWING order (the rightmost one of a
    # right-to-left span).
    raw_glyphs = content_text(page, "rawdict", textpage=_pd_textpage)

    # ── 2. 找出溢出區間內且 X 重疊的文字 block ──
    # (bbox, block index in the extraction, block): the index names the
    # block's own glyphs in ``raw_glyphs`` (owned-glyph redaction, F13-VF-2).
    candidates: list[tuple[fitz.Rect, int, dict]] = []
    for block_idx, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:      # 只處理純文字 block
            continue
        if not _push_down_can_move(block, above_y):
            continue
        bbox = fitz.Rect(block["bbox"])
        # Y 範圍：必須在 above_y 和 new_bottom + margin 之間開始
        if bbox.y0 > new_bottom + 5.0:
            continue
        # X 重疊：至少有部分與編輯欄重疊
        if bbox.x1 < edit_x0 - X_TOL or bbox.x0 > edit_x1 + X_TOL:
            continue
        candidates.append((fitz.Rect(bbox), block_idx, block))

    if not candidates:
        logger.debug("_push_down_overlapping_text: 溢出區內無需推移的文字塊")
        return

    # ── 3. 按 y0 排序，cascade 計算各 block 的 delta_y ──
    candidates.sort(key=lambda c: c[0].y0)
    push_floor = new_bottom + GAP   # 目前可用的最低安全邊界

    plan: list[tuple[fitz.Rect, int, dict, float]] = []   # (bbox, block_idx, block, delta_y)
    for bbox, block_idx, block in candidates:
        delta_y = max(0.0, push_floor - bbox.y0)
        new_y1  = bbox.y1 + delta_y
        if new_y1 > page_rect.y1 + 5.0:
            logger.warning(
                f"_push_down: block [y={bbox.y0:.0f}~{bbox.y1:.0f}] "
                f"推移 {delta_y:.1f}pt 後超出頁面，跳過"
            )
            push_floor = max(push_floor, bbox.y1 + GAP)
            continue
        plan.append((fitz.Rect(bbox), block_idx, block, delta_y))
        push_floor = new_y1 + GAP   # cascade：更新安全邊界

    if not plan:
        return

    # ── 4. 預先收集所有 span 資料（讀），避免 redact 後影響 get_text ──
    insert_tasks: list[dict] = []
    redact_rects: list[fitz.Rect] = []
    shifted_annots: list[dict] = []

    for bbox, block_idx, block, delta_y in plan:
        redact_rects.append(fitz.Rect(bbox))
        # 儲存此 block 上的 annotation 並記錄推移量（F11-ANN-1：redaction 後
        # 仍存在的 annot 原地平移，被刪除的才重建；同一 xref 只處理一次）
        for saved_a in model.tools.annotation._save_overlapping_annots(page, bbox):
            shifted_annots.append(dict(saved_a, offset=(0.0, delta_y)))
        # 收集 span 資訊
        # D-RTL-GROW: a right-to-left span keeps its right edge; a mixed span
        # follows its block's base direction (``grows_right_to_left``).
        block_text = " ".join(
            str(sp.get("text", "")) for ln in block.get("lines", []) for sp in ln.get("spans", [])
        )
        for line_idx, line in enumerate(block.get("lines", [])):
            for span_idx, span in enumerate(line.get("spans", [])):
                orig = span.get("origin")
                if not orig:
                    continue
                raw_chars = _raw_span_chars(raw_glyphs, block_idx, line_idx, span_idx)
                start = _push_down_span_start(raw_chars, line, span)
                span_rtl = grows_right_to_left(span.get("text", ""), block_text)
                anchor = (
                    _push_down_span_start(raw_chars, line, span, rtl=True)
                    if span_rtl
                    else start
                )
                c_int = span.get("color", 0)
                insert_tasks.append({
                    "glyph_keys": _span_glyph_keys(raw_chars),
                    "origin": fitz.Point(start.x, start.y + delta_y),
                    "rtl": span_rtl,
                    "anchor": fitz.Point(anchor.x, anchor.y + delta_y),
                    # The run's direction (F15-VM2-FAST180): a block that is not
                    # horizontal is redrawn along its own direction, in a box
                    # built around the span's pushed bbox.
                    "rotate": _replay_rotate(rotation_degrees_from_dir(line.get("dir"))),
                    "bbox": fitz.Rect(span.get("bbox") or block["bbox"]) + (0, delta_y, 0, delta_y),
                    "text":   span.get("text", ""),
                    "font":   span.get("font", "helv"),
                    "size":   float(span.get("size", 12)),
                    "color":  (
                        ((c_int >> 16) & 0xFF) / 255.0,
                        ((c_int >>  8) & 0xFF) / 255.0,
                        ( c_int        & 0xFF) / 255.0,
                    ),
                })

    # F17-COL-1 (same class): every pushed span is drawn again below, so its
    # paint state is captured now, before the redaction, and re-applied to
    # what is drawn; text that moves cannot keep a page-space soft mask.
    _pd_states = PageTextStates(page, fitz.TEXT_PRESERVE_WHITESPACE)
    for task in insert_tasks:
        keys = task.pop("glyph_keys")
        style = None if _pd_states.all_plain else style_for_run(_pd_states.state_of(keys))
        refusal = refusal_for(style, moved=True, what="a block the push-down moves")
        if refusal is not None:
            raise refusal
        task["style"] = style

    # ── 5. 批次 Redact（一次 apply，減少 PDF stream 操作次數）──
    # Erase only the pushed blocks' own glyphs (F13-VF-2): a block's bounding
    # box can hold glyphs of another block that is not re-inserted below.
    # The caller's transaction rolls the page back on either refusal.
    _pd_flags = fitz.TEXT_PRESERVE_WHITESPACE
    # The glyphs of ``raw_glyphs`` itself (same text page, same flags): nothing
    # above wrote to the page -- the annotation save and the paint capture
    # only read it -- so a second extraction would return the same dict.
    _glyphs_before = _glyphs_from_rawdict(raw_glyphs)
    _pushed_blocks = {block_idx for _bbox, block_idx, _block, _dy in plan}
    _redaction = _redact_owned_glyphs(
        page,
        _glyphs_before,
        [g for g in _glyphs_before if g.block_idx in _pushed_blocks],
        redact_rects,
        _pd_flags,
    )
    if _redaction.survivors:
        raise TextEditRefused(
            TextEditRefusal.REDACTION_LEFT_SOURCE,
            "push-down redaction left the pushed text on the page: "
            f"{len(_redaction.survivors)} glyph(s)",
        )
    if _redaction.lost_foreign:
        raise TextEditRefused(
            TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST,
            "push-down redaction also erased "
            f"{len(_redaction.lost_foreign)} glyph(s) of text it does not move",
        )
    # 在推移後的位置還原 annotation
    if shifted_annots:
        model.tools.annotation._restore_annots(page, shifted_annots)

    # ── 6. 批次 Insert（使用 insert_htmlbox 確保 Unicode 完整保留）──
    # 改用 insert_htmlbox（而非 insert_text）的原因：
    # insert_text(fontname="helv") 會靜默丟棄 helv 不支援的字元（如 €、emoji），
    # 導致 push-down 後文字殘缺。insert_htmlbox 使用 CSS 渲染引擎，
    # 完整支援 Unicode，確保 € 等特殊字元能被正確插入與還原。
    import html as _html_module
    inserted = 0
    _pr = unrotated_page_rect(page)  # origins are unrotated-space
    for task in insert_tasks:
        if not task["text"].strip():
            continue
        x  = float(task["origin"].x)
        y  = float(task["origin"].y)  # baseline
        sz = float(task["size"])
        r, g, b = task["color"]
        # 估算文字寬度（保守估計）
        est_w  = max(sz * len(task["text"]) * 0.75, sz * 2)
        x0     = max(x, _pr.x0)
        x1     = min(x + est_w, _pr.x1)
        y0     = max(y - sz * 1.15, _pr.y0)  # 基線上方（ascender）
        y1     = min(y + sz * 0.40, _pr.y1)  # 基線下方（descender）
        rotate = int(task["rotate"])
        if rotate:
            # Turned text: the span's own (pushed) bbox is where it was.
            x0, y0, x1, y1 = clamp_rect_to_page(task["bbox"], _pr)
        if x1 <= x0 or y1 <= y0:
            continue
        color_hex = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        html_str = (
            f'<span style="color:{color_hex}">'
            f'{_html_module.escape(task["text"])}</span>'
        )
        css_str = (
            f"* {{ font-size: {sz}pt; white-space: pre; "
            f"margin:0; padding:0; }}"
        )
        if task["rtl"]:
            css_str += _RTL_BASE_CSS
        try:
            # F13-VF-3: the pushed text keeps its size and its (shifted)
            # baseline; the estimated box only anchors the measured one.
            # D-RTL-GROW: a right-to-left span is matched by its right edge.
            placement = _place_htmlbox_at_origin(
                page, html_str, css_str,
                text=task["text"], size=sz,
                origin=task["anchor"], anchor=fitz.Rect(x0, y0, x1, y1), rotate=rotate,
                rtl=task["rtl"],
            )
            with paint_state_applied(page, task["style"]):
                _insert_htmlbox_unshrunk(page, placement.box, html_str, css_str, rotate=rotate)
            inserted += 1
        except Exception as e_html:
            # 最後回退：仍嘗試 insert_text（可能丟字元，但不會崩潰）
            logger.debug(
                f"_push_down insert_htmlbox 失敗，回退 insert_text: {e_html}"
            )
            try:
                with paint_state_applied(page, task["style"]):
                    insert_text_page_space(
                        page, task["origin"], task["text"],
                        fontname="helv",
                        fontsize=sz, color=task["color"], rotate=rotate,
                    )
                inserted += 1
            except Exception as e2:
                logger.warning(
                    f"_push_down: span '{task['text'][:20]}' 無法插入: {e2}"
                )

    # ── 7. 更新 TextBlockManager 索引中被推移 block 的 layout_rect ──
    for bbox, _block_idx, _block, delta_y in plan:
        new_rect = fitz.Rect(
            bbox.x0, bbox.y0 + delta_y,
            bbox.x1, bbox.y1 + delta_y,
        )
        tb = model.block_manager.find_by_rect(page_idx, bbox)
        if tb:
            model.block_manager.update_block(tb, layout_rect=new_rect)

    logger.debug(
        f"_push_down_overlapping_text: 推移了 {len(plan)} 個 block，"
        f"插入 {inserted} 個 span"
    )


def _replay_rotate(rotation: int) -> int:
    """The ``rotate`` that makes ``insert_text`` / ``insert_htmlbox`` write along a
    run's direction.  ``rotation`` is the run's writing direction as the index
    names it (``rotation_degrees_from_dir``: 90 reads DOWN the page, 270 reads
    UP); both PyMuPDF calls turn the other way, so the quarter turns swap
    (``PDFModel._insert_rotate_for_htmlbox``).  0 and 180 are their own inverse.
    The ONE mapping for every site that redraws a run other than the edited
    one (F15-VM2-FAST180)."""
    return (360 - rotation) % 360 if rotation in (0, 90, 180, 270) else 0


def _protected_span_rotate(span: EditableSpan) -> int:
    """The ``rotate`` a protected span is replayed with."""
    return _replay_rotate(int(span.rotation))


def _replay_protected_span_as_html(
    model: PDFModel,
    page: fitz.Page,
    span: EditableSpan,
    text: str,
    fontsize: float,
    color: tuple,
    fontname: str,
    rotate: int,
    style: WriteStyle | None = None,
) -> None:
    """Replay one neighbour through htmlbox at its own size and origin
    (F13-VF-3): the box comes from ``_place_htmlbox_at_origin``, never from
    the span's tight bbox with ``scale_low=0``.  A right-to-left neighbour
    keeps its right edge instead of its origin (D-RTL-GROW).  ``style``: the
    neighbour's own paint state, re-applied to what is drawn (F17-COL-1)."""
    html_content, css, placement = _protected_span_html_placement(
        model, page, span, text, fontsize, color, fontname, rotate
    )
    with paint_state_applied(page, style):
        _insert_htmlbox_unshrunk(page, placement.box, html_content, css, rotate=rotate)


def _protected_span_html_placement(
    model: PDFModel,
    page: fitz.Page,
    span: EditableSpan,
    text: str,
    fontsize: float,
    color: tuple,
    fontname: str,
    rotate: int,
) -> tuple[str, str, _HtmlboxPlacement]:
    """``(html, css, placement)`` of a protected span's htmlbox replay: the
    markup (``_protected_span_markup``) and where ``_place_htmlbox_at_origin``
    puts it so the text lands on the span's anchor -- its origin, or its right
    edge for a right-to-left neighbour (D-RTL-GROW).  Shared by the replay and
    by the validation that re-renders it (OD-UNI1-COMMIT)."""
    rtl = _spans_grow_right_to_left(model, [span])
    anchor, html_content, css = _protected_span_markup(
        model, page, span, text, fontsize, color, fontname, rtl=rtl
    )
    placement = _place_htmlbox_at_origin(
        page, html_content, css,
        text=text, size=fontsize, origin=_span_anchor(span, rtl), anchor=anchor, rotate=rotate,
        rtl=rtl,
    )
    return html_content, css, placement


def _replay_protected_spans(
    model: PDFModel,
    page: fitz.Page,
    spans: list[EditableSpan],
    styles: dict[str, WriteStyle | None] | None = None,
) -> None:
    """Draw the untouched neighbours the rebuild erased again.  ``styles``
    (span id -> paint state, captured by ``_rebuild_paint`` before the
    erase): each neighbour comes back in its own render mode, colour space,
    ExtGState and layer (F17-COL-1); a span without an entry is plain."""
    for span in spans:
        style = (styles or {}).get(span.span_id)
        text, fontsize, color, fontname = _protected_span_replay_style(model, span)
        if not text:
            continue
        rotate = _protected_span_rotate(span)
        is_cjk_text = model._needs_cjk_font(text)
        # insert_text with a base-14 font writes U+00B7 for every non-Latin-1
        # character (F10-UNI-1), CJK or not -- such text must replay as html.
        latin1_safe = _simple_font_can_encode(text)

        # CJK text can be silently dropped by insert_text(helv) without raising.
        # Prefer HTML replay first to preserve Unicode reliably.
        if is_cjk_text or not latin1_safe:
            try:
                _replay_protected_span_as_html(
                    model, page, span, text, fontsize, color, fontname, rotate, style
                )
                continue
            except Exception as e_html:
                logger.debug(
                    "protected replay html fallback failed span=%s err=%s; fallback to insert_text candidates",
                    span.span_id,
                    e_html,
                )
            if not is_cjk_text:
                # No insert_text candidate below can write this text without
                # U+00B7 substitution.  Leave the span missing so
                # _validate_protected_spans refuses and rolls the edit back.
                logger.warning(
                    "protected replay: html replay failed for non-Latin-1 span=%s; "
                    "not substituting via insert_text",
                    span.span_id,
                )
                continue

        candidates = [fontname]
        if is_cjk_text:
            candidates.extend(["china-ts", "helv"])
        else:
            candidates.extend(["helv", "tiro", "cour"])

        inserted = False
        tried: list[str] = []
        for cand in candidates:
            if cand in tried:
                continue
            tried.append(cand)
            try:
                with paint_state_applied(page, style):
                    insert_text_page_space(
                        page,
                        fitz.Point(span.origin.x, span.origin.y),
                        text,
                        fontname=cand,
                        fontsize=fontsize,
                        color=color,
                        rotate=rotate,
                    )
                inserted = True
                break
            except Exception as e_font:
                logger.debug(
                    "protected replay fallback failed span=%s font=%s err=%s",
                    span.span_id,
                    cand,
                    e_font,
                )

        if inserted:
            continue

        # Last fallback: htmlbox path is more tolerant for non-base14 fonts.
        _replay_protected_span_as_html(
            model, page, span, text, fontsize, color, fontname, rotate, style
        )


class _RebuildPaint(NamedTuple):
    """The paint state of the text one legacy rebuild writes again
    (F17-COL-1..4), captured before anything is erased: the edited text's
    style and each replayed neighbour's (span id -> style; ``None`` = plain,
    written exactly as before)."""

    edit: WriteStyle | None
    protected: dict[str, WriteStyle | None]


def _span_glyph_keys(raw_chars: list) -> list[tuple[str, int, int]]:
    """The inked glyph keys (``_PageGlyph.key``) of one rawdict span's
    ``chars`` (``_raw_span_chars``)."""
    keys: list[tuple[str, int, int]] = []
    for ch in raw_chars:
        c = ch.get("c", "")
        if not c or ch.get("synthetic") or c.isspace():
            continue
        bbox = ch["bbox"]
        ox, oy = (float(v) for v in ch.get("origin", (bbox[0], bbox[3])))
        keys.append((c, round(ox * 10), round(oy * 10)))
    return keys


def _run_glyph_keys(glyphs: list[_PageGlyph], span: EditableSpan) -> list[tuple[str, int, int]]:
    return [g.key for g in _glyphs_owned_by_runs(glyphs, [span], fitz.Rect(span.bbox)) if g.inked]


def _rebuild_paint(
    model: PDFModel,
    page: fitz.Page,
    resolve_result: _EditTextResolveResult,
    *,
    new_text: str,
    color: tuple,
    moved: bool,
) -> _RebuildPaint:
    """The ONE capture of what the rebuild must keep (F17-COL-1..4), taken
    from the page as it is BEFORE the rebuild touches it.  Raises
    ``TextEditRefused(TEXT_STATE_NOT_REPRODUCIBLE)`` -- with nothing written
    -- when the edited text (``new_text`` non-empty; ``moved``: dragged) or a
    replayed neighbour is painted in a state the writers cannot reproduce."""
    capture = PageTextStates(page)
    if capture.all_plain:
        return _RebuildPaint(None, {})
    glyphs = _page_glyphs(page)
    edit: WriteStyle | None = None
    # A member with no inked glyph (a whitespace run) draws nothing: it has no
    # state to keep and must not count as a plain run beside styled ones.
    inked = [
        (span, keys)
        for span in _member_spans(resolve_result)
        if (keys := _run_glyph_keys(glyphs, span))
    ]
    if new_text and inked:
        edit = style_for_runs(
            [capture.state_of(keys) for _span, keys in inked],
            [tuple(span.color) if span.color else None for span, _keys in inked],
            color,
        )
        refusal = refusal_for(edit, moved=moved, what="the edited text")
        if refusal is not None:
            raise refusal
    protected: dict[str, WriteStyle | None] = {}
    for span in resolve_result.protected_spans:
        style = style_for_run(capture.state_of(_run_glyph_keys(glyphs, span)))
        refusal = refusal_for(style, moved=False, what="an untouched neighbour it replays")
        if refusal is not None:
            raise refusal
        protected[span.span_id] = style
    logger.debug(
        "rebuild paint page=%s edit=%s protected=%s",
        page.number,
        None if edit is None else (edit.fill, edit.state.describe()),
        {k: (None if v is None else v.state.describe()) for k, v in protected.items()},
    )
    return _RebuildPaint(edit, protected)


def _refuse_moving_styled_text(
    model: PDFModel, page: fitz.Page, resolve_result: _EditTextResolveResult
) -> None:
    """A cross-page move re-creates the moved text as a plain text box on
    another page, which carries no render mode, ExtGState or layer: source
    text drawn invisible, as an outline, translucent / blended or inside an
    optional-content layer -- or in a state the capture cannot establish --
    is refused before anything changes (F17-COL same class).  A colour that is
    only in another colour space (gray, CMYK, spot) moves as the text box's RGB
    colour, as the move's consent says (owner question, TODOS F17-COL)."""
    capture = PageTextStates(page)
    if capture.all_plain:
        return
    glyphs = _page_glyphs(page)
    for span in _member_spans(resolve_result):
        state = capture.state_of(_run_glyph_keys(glyphs, span))
        if state is not None and state.changes_visibility:
            raise TextEditRefused(
                TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
                "a cross-page move cannot carry the paint state of the moved text: "
                + state.describe(),
            )


def _protected_span_replay_style(
    model: PDFModel, span: EditableSpan
) -> tuple[str, float, tuple, str]:
    """``(text, fontsize, color, fontname)`` a protected span is replayed with."""
    text = (span.text or "").rstrip("\n")
    fontsize = max(1.0, float(span.size))
    color = tuple(span.color) if span.color else (0.0, 0.0, 0.0)
    fontname = model._resolve_font_for_push(span.font or "helv")
    return text, fontsize, color, fontname


def _protected_span_markup(
    model: PDFModel,
    page: fitz.Page,
    span: EditableSpan,
    text: str,
    fontsize: float,
    color: tuple,
    fontname: str,
    *,
    rtl: bool = False,
) -> tuple[fitz.Rect, str, str]:
    """The anchor box and htmlbox markup a protected span is replayed with --
    the ONE builder for the replay and for its validation's reference render.
    The box is only where the span was: ``_place_htmlbox_at_origin`` makes the
    box the markup is actually inserted into (F13-VF-3).  ``rtl``: laid out as
    a right-to-left paragraph (``_RTL_BASE_CSS``, D-RTL-GROW)."""
    bbox = fitz.Rect(span.bbox)
    if bbox.width < 2:
        bbox.x1 = bbox.x0 + max(2.0, fontsize * 0.8)
    if bbox.height < 2:
        bbox.y1 = bbox.y0 + max(2.0, fontsize * 1.2)
    html_content = model._convert_text_to_html(text, fontsize, color, latin_font=fontname)
    css = model._build_insert_css(fontsize, color, fontname) + _NO_WRAP_CSS
    if rtl:
        css += _RTL_BASE_CSS
    return clamp_rect_to_page(bbox, unrotated_page_rect(page)), html_content, css


def _glyph_evidence_rect(rect: fitz.Rect, size: float, page_rect: fitz.Rect) -> fitz.Rect:
    """``rect`` grown by a couple of ems: htmlbox may place a glyph's box a
    little outside the box it was given (leading, scale, rounding)."""
    pad = max(4.0, 2.0 * float(size))
    grown = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    return clamp_rect_to_page(grown, page_rect)


def _protected_span_drawn_with_lossy_layer(
    model: PDFModel,
    page: fitz.Page,
    span: EditableSpan,
    page_text: str,
    norm_page: str,
    acknowledged: tuple[UnkeepableGlyph, ...] | list[UnkeepableGlyph] = (),
) -> bool:
    """A replayed protected span whose text is not in the page's text layer
    is still intact when the loss is only htmlbox's lossy ToUnicode for it
    (OD-UNI1-COMMIT): its expected text layer is on the page and its glyphs
    are drawn where it was replayed."""
    text, fontsize, color, fontname = _protected_span_replay_style(model, span)
    if not text or _simple_font_can_encode(text):
        return False  # replayed by insert_text: no htmlbox text layer to forgive
    try:
        html_content, css, placement = _protected_span_html_placement(
            model, page, span, text, fontsize, color, fontname, _protected_span_rotate(span)
        )
        reference = _htmlbox_reference(
            html_content, css, max(placement.box.width, placement.box.height)
        )
        page_glyphs, _notdef = _texttrace_glyphs(
            page, _glyph_evidence_rect(placement.ink, fontsize, unrotated_page_rect(page))
        )
    except Exception:
        logger.debug("protected span reference render failed: %s", span.span_id, exc_info=True)
        return False
    expected = _presence_norm(reference.text)
    if not expected or expected not in norm_page:
        return False
    problem = _lossy_text_layer_problem(text, page_text, reference, page_glyphs, acknowledged)
    if problem is not None:
        logger.warning("protected span %s not intact after replay: %s", span.span_id, problem)
        return False
    logger.warning(
        "protected span %s replayed with a lossy htmlbox text layer (OD-UNI1-COMMIT): %s",
        span.span_id,
        _lost_requested_chars(text, page_text),
    )
    return True


def _glyphs_unacknowledged(
    glyphs: list[UnkeepableGlyph],
    acknowledged: tuple[UnkeepableGlyph, ...] | list[UnkeepableGlyph],
) -> bool:
    """Is one of the unkeepable ``glyphs`` not in ``acknowledged``?  The ONE
    test behind a replayed neighbour's acceptance (``_protected_span_present``)
    and the refusal code picked for its failure
    (``_protected_glyphs_unacknowledged``)."""
    return not set(glyphs) <= set(acknowledged)


def _protected_glyphs_unacknowledged(
    protected_spans: list[EditableSpan],
    acknowledged_glyph_loss: tuple[UnkeepableGlyph, ...] = (),
) -> bool:
    """Does a replayed neighbour carry an unkeepable glyph the consent did not
    acknowledge?  The reason code of that ``_validate_protected_spans``
    failure (ZH-REFUSALS); the same test the validator applies per span."""
    return any(
        _glyphs_unacknowledged(_span_unkeepable_glyphs(span), acknowledged_glyph_loss)
        for span in protected_spans
    )


def _protected_span_present(
    model: PDFModel,
    page: fitz.Page,
    span: EditableSpan,
    page_text: str,
    full_page: str,
    acknowledged_glyph_loss: tuple[UnkeepableGlyph, ...],
) -> bool:
    """Is the replayed neighbour's text on the page (the presence half of
    ``_validate_protected_spans``)?"""
    # F11-UNI-1 (decision C): a replayed neighbour carrying a glyph with
    # no Unicode identity cannot come back as itself.  ``_presence_norm``
    # drops U+FFFD, so without this gate such a neighbour "passed" while
    # the replay silently drew another glyph; it is accepted only when the
    # consent acknowledged exactly this run's unkeepable glyphs.
    unkeepable = _span_unkeepable_glyphs(span)
    if unkeepable:
        if _glyphs_unacknowledged(unkeepable, acknowledged_glyph_loss):
            logger.warning(
                "protected span %s carries unacknowledged unkeepable glyphs: %s",
                span.span_id,
                [g.codepoint for g in unkeepable],
            )
            return False
    else:
        probe = _presence_norm(span.text)
        if not probe or probe in full_page:
            return True
    # Not in the text layer as itself: intact only when htmlbox's lossy
    # ToUnicode (and the acknowledged glyphs) account for the whole loss.
    if _protected_span_drawn_with_lossy_layer(
        model, page, span, page_text, full_page, unkeepable
    ):
        return True
    logger.warning("protected span missing after replay: %s", span.span_id)
    return False


def _protected_span_drawn_in_place(
    model: PDFModel, span: EditableSpan, traces: list[dict]
) -> bool:
    """Is a glyph drawn at the neighbour's own size on its own origin
    (F13-VF-3)?  Presence alone let a replay that shrank and moved the
    neighbour pass.  ``traces`` is the page's ``get_texttrace()``.  A
    right-to-left neighbour is replayed on its right edge (D-RTL-GROW), so
    its glyphs are matched there, by the same measure (``_glyph_start``)."""
    text, fontsize, _color, _fontname = _protected_span_replay_style(model, span)
    if not text or not _presence_norm(span.text):
        return True  # nothing identifiable was replayed
    rtl = _spans_grow_right_to_left(model, [span])
    origin = _span_anchor(span, rtl)
    rotation = int(getattr(span, "rotation", 0) or 0)
    for trace in traces:
        if abs(float(trace.get("size", 0.0)) - fontsize) > _REPLAY_SIZE_TOLERANCE:
            continue
        for ch in trace.get("chars", ()):
            gx, gy = _glyph_start(ch, rotation, rtl)
            if (
                abs(gx - float(origin.x)) <= _REPLAY_ORIGIN_TOLERANCE
                and abs(gy - float(origin.y)) <= _REPLAY_ORIGIN_TOLERANCE
            ):
                return True
    logger.warning(
        "protected span %s is not drawn at its size %.2f and origin %s after replay",
        span.span_id,
        fontsize,
        tuple(origin),
    )
    return False


def _validate_protected_spans(
    model: PDFModel,
    page: fitz.Page,
    protected_spans: list[EditableSpan],
    acknowledged_glyph_loss: tuple[UnkeepableGlyph, ...] = (),
) -> bool:
    if not protected_spans:
        return True  # nothing was replayed: no page text to extract
    page_text = content_text(page, "text")
    full_page = _presence_norm(page_text)
    traces: list[dict] | None = None
    for span in protected_spans:
        if not _protected_span_present(
            model, page, span, page_text, full_page, acknowledged_glyph_loss
        ):
            return False
        if traces is None:
            traces = page.get_texttrace()
        if not _protected_span_drawn_in_place(model, span, traces):
            return False
    return True


def _resolve_edit_target(
    model: PDFModel,
    *,
    page_num: int,
    page_idx: int,
    page: fitz.Page,
    rect: fitz.Rect,
    new_text: str,
    font: str,
    size: float,
    color: tuple,
    original_text: str | None,
    new_rect: fitz.Rect | None,
    resolved_target_span_id: str | None,
    effective_target_mode: str,
    source_ref: SourceShowRef | None = None,
    check_no_change: bool = True,
) -> tuple[EditTextResult, _EditTextResolveResult | None]:
    target_span = None
    if resolved_target_span_id:
        target_span = model.block_manager.find_run_by_id(page_idx, resolved_target_span_id)
        if target_span is None:
            logger.debug("target_span_id not found in current index: %s", resolved_target_span_id)

    if target_span is None:
        target = model.block_manager.find_by_rect(
            page_idx, rect, original_text=original_text, doc=model.doc
        )
        if not target:
            logger.warning("無法找到目標文字方塊，頁面 %s 矩形 %s", page_num, rect)
            return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

        clip_text = content_text(page, "text", clip=target.rect).strip()
        norm_clip = normalize_text(clip_text)
        norm_block = normalize_text(target.text)
        if norm_block and norm_clip:
            match_ratio = difflib.SequenceMatcher(None, norm_block, norm_clip).ratio()
            if match_ratio < 0.5:
                logger.debug("索引文字與頁面文字不匹配 (ratio=%.2f)，重建該頁索引", match_ratio)
                model.block_manager.rebuild_page(page_idx, model.doc)
                target = model.block_manager.find_by_rect(
                    page_idx, rect, original_text=original_text, doc=model.doc
                )
                if not target:
                    logger.warning("重建索引後仍找不到目標文字方塊")
                    return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

        candidate_spans = model.block_manager.find_overlapping_runs(page_idx, target.layout_rect, tol=0.5)
        if candidate_spans:
            text_probe = normalize_text(original_text or target.text or "")
            if text_probe:
                scored = sorted(
                    candidate_spans,
                    key=lambda sp: difflib.SequenceMatcher(
                        None, text_probe, normalize_text(sp.text)
                    ).ratio(),
                )
                target_span = scored[-1]
            else:
                target_span = candidate_spans[-1]
            resolved_target_span_id = target_span.span_id

    if target_span is None:
        logger.warning("unable to resolve target span for edit on page %s", page_num)
        return EditTextResult.TARGET_SPAN_NOT_FOUND, None

    if not resolved_target_span_id:
        resolved_target_span_id = target_span.span_id

    # UI step 3: re-derive the clicked run's proven source show HERE, with
    # the same Qt-free resolver the hit used, instead of trusting the view.
    source_group: SourceRunGroup | None = None
    if source_ref is not None:
        group = (
            _rederive_source_group(model, page_idx, target_span.span_id)
            if effective_target_mode == "run"
            else None
        )
        if group is None or group.source_ref != source_ref:
            logger.info(
                "edit_text: source_ref does not match the re-derived show on page %s "
                "(mode=%s, grouped=%s); refusing with zero mutation",
                page_num,
                effective_target_mode,
                group is not None,
            )
            return EditTextResult.TARGET_SOURCE_MISMATCH, None
        source_group = group
    elif effective_target_mode == "run" and original_text:
        # A ref-less caller that forwarded the hit's grouped text (the
        # positional controller path, a move) targets the whole show; one
        # naming a single word keeps today's single-run target -- the whole
        # show is never rewritten for a caller that named part of it.
        group = _rederive_source_group(model, page_idx, target_span.span_id)
        if (
            group is not None
            and len(group.member_span_ids) > 1
            and _strip_ws(original_text) == _strip_ws(group.text)
        ):
            source_group = group
    if source_group is not None:
        first_member = model.block_manager.find_run_by_id(
            page_idx, source_group.first_span_id
        )
        if first_member is None:
            return EditTextResult.TARGET_SPAN_NOT_FOUND, None
        target_span = first_member
        resolved_target_span_id = first_member.span_id

    # S17-ANCHOR-JOIN: the runs ONE earlier app edit wrote on one baseline are
    # one target when the caller names their whole text (the hit forwarded it);
    # a caller naming one fragment keeps the single-run target.
    joined_group: JoinedEditGroup | None = None
    if source_group is None and effective_target_mode == "run" and original_text:
        candidate = model._joined_edit_group_for(
            page_idx,
            model.block_manager.get_runs(page_idx),
            span_id=target_span.span_id,
        )
        if candidate is not None and _strip_ws(original_text) == _strip_ws(candidate.text):
            joined_group = candidate
            target_span = candidate.members[0]
            resolved_target_span_id = target_span.span_id

    # The provenance that names the members and their box: the proven show,
    # else the joined edit run (derived only without a show), else the one
    # resolved run.  The anchor key stays the show's: a joined run keys its
    # anchor by its first run.
    member_group: SourceRunGroup | JoinedEditGroup | None = (
        source_group if source_group is not None else joined_group
    )
    target_member_span_ids: set[str] = (
        set(member_group.member_span_ids)
        if member_group is not None
        else {resolved_target_span_id}
    )
    anchor_key: str | None = (
        source_group.anchor_key if source_group is not None else resolved_target_span_id
    )
    own_bbox = member_group.rect() if member_group is not None else fitz.Rect(target_span.bbox)
    # First run-mode edit of this span (or grouped show) records its
    # original bbox+size as the reopen anchor; later edits reuse it so the
    # box doesn't cumulate shrink. Drag edits (new_rect) and paragraph mode
    # never anchor. A grouped show keys its anchor by the WHOLE group, so a
    # per-word anchor of its first run can never shrink its cluster (B1).
    reopen_anchor_rect: fitz.Rect | None = None
    if effective_target_mode == "run" and new_rect is None and anchor_key:
        reopen_anchor_rect = model._get_run_reopen_anchor_rect(page_idx, anchor_key)
        if reopen_anchor_rect is None:
            reopen_anchor_rect = fitz.Rect(own_bbox)
            model._set_run_reopen_anchor_rect(page_idx, anchor_key, reopen_anchor_rect)
        if model._get_run_reopen_anchor_size(page_idx, anchor_key) is None:
            model._set_run_reopen_anchor_size(page_idx, anchor_key, float(target_span.size))
    target_bbox_for_cluster = fitz.Rect(
        reopen_anchor_rect if reopen_anchor_rect is not None else own_bbox
    )
    if member_group is not None:
        # The overlap cluster always covers the whole group's union.
        target_bbox_for_cluster |= member_group.rect()
    target_block_idx = target_span.block_idx
    target_rotation = int(target_span.rotation)
    if effective_target_mode == "paragraph":
        para = model._resolve_paragraph_candidate(
            page_idx=page_idx,
            probe_rect=fitz.Rect(rect),
            original_text=original_text,
            preferred_run_id=target_span.span_id,
        )
        if para is not None:
            target_member_span_ids = set(para.run_ids)
            target_bbox_for_cluster = fitz.Rect(para.bbox)
            target_block_idx = para.block_idx
            target_rotation = int(para.rotation)
            if para.run_ids and resolved_target_span_id not in target_member_span_ids:
                resolved_target_span_id = para.run_ids[0]
            reopen_anchor_rect = None
        else:
            logger.debug(
                "paragraph mode requested but paragraph not resolved for run=%s; fallback to run mode",
                target_span.span_id,
            )
            effective_target_mode = "run"

    overlap_cluster = model.block_manager.find_overlapping_runs(
        page_idx,
        target_bbox_for_cluster,
        tol=0.5,
    )
    if _is_axis_aligned_dir(target_span.dir_vec):
        # S17-WMARK-UNDER (owner decision): a run turned off the page axes (a
        # 45-degree watermark) only has a bbox that is a big square around a
        # thin diagonal of ink; it is not text the edited word was drawn on
        # top of, so it is no cluster member to erase and replay (the replay
        # draws it upright).  It stays on the page as it is.
        overlap_cluster = [
            s for s in overlap_cluster
            if s.span_id in target_member_span_ids or _is_axis_aligned_dir(s.dir_vec)
        ]
    if not overlap_cluster:
        overlap_cluster = [
            s for s in model.block_manager.get_runs(page_idx)
            if s.span_id in target_member_span_ids
        ]
    if not overlap_cluster:
        overlap_cluster = [target_span]
    if member_group is not None:
        present = {s.span_id for s in overlap_cluster}
        for span in model.block_manager.get_runs(page_idx):
            if span.span_id in target_member_span_ids and span.span_id not in present:
                overlap_cluster.append(span)

    protected_spans = [s for s in overlap_cluster if s.span_id not in target_member_span_ids]
    cluster_union = rect_union([fitz.Rect(s.bbox) for s in overlap_cluster])

    target = model.block_manager.find_by_id(
        page_idx,
        f"page_{page_idx}_block_{target_block_idx}",
    )
    if not target:
        target = model.block_manager.find_by_rect(
            page_idx, fitz.Rect(target_bbox_for_cluster), original_text=original_text, doc=model.doc
        )
    if not target:
        logger.warning("unable to resolve target block for span %s", resolved_target_span_id)
        return EditTextResult.TARGET_BLOCK_NOT_FOUND, None

    resolved_font = model._resolve_add_text_font(font)
    current_font = model._resolve_add_text_font(target.font or "helv")
    text_unchanged = is_unchanged_text(target.text or "", new_text)
    size_unchanged = abs(float(size) - float(target.size)) <= 0.01
    target_color = tuple(float(c) for c in (target.color or (0.0, 0.0, 0.0)))
    request_color = tuple(float(c) for c in (color or (0.0, 0.0, 0.0)))
    color_unchanged = len(target_color) == len(request_color) and all(
        abs(a - b) <= 0.001 for a, b in zip(target_color, request_color)
    )
    if (
        check_no_change
        and new_rect is None
        and text_unchanged
        and resolved_font == current_font
        and size_unchanged
        and color_unchanged
    ):
        logger.debug(
            "edit_text no-op: page=%s span=%s text/style unchanged; skip geometry re-estimation",
            page_num,
            resolved_target_span_id,
        )
        return EditTextResult.NO_CHANGE, None

    rotation = int(target_rotation)
    is_vertical = rotation in (90, 270)
    insert_rotate = model._insert_rotate_for_htmlbox(rotation)
    redact_rect = fitz.Rect(cluster_union if not cluster_union.is_empty else target.layout_rect)

    return EditTextResult.SUCCESS, _EditTextResolveResult(
        target_span=target_span,
        resolved_target_span_id=resolved_target_span_id,
        effective_target_mode=effective_target_mode,
        target_member_span_ids=target_member_span_ids,
        overlap_cluster=overlap_cluster,
        protected_spans=protected_spans,
        target=target,
        resolved_font=resolved_font,
        rotation=rotation,
        is_vertical=is_vertical,
        insert_rotate=insert_rotate,
        redact_rect=redact_rect,
        reopen_anchor_rect=fitz.Rect(reopen_anchor_rect) if reopen_anchor_rect is not None else None,
        source_group=source_group,
        reopen_anchor_key=anchor_key if reopen_anchor_rect is not None else None,
    )


def _sync_textbox_objects(
    model: PDFModel,
    page_num: int,
    new_text: str,
    resolve_result: _EditTextResolveResult,
    *,
    new_rect: fitz.Rect | None,
    style: tuple[str, float, tuple] | None,
    words_before: list | None,
) -> None:
    """Bring the app textbox markers the edit touched in step with it (F15-2).

    Runs after every successful commit (tiered and legacy). Move / Rotate Object
    re-insert the marker's stored text, so leaving it stale reverts the edit. A sync
    failure never fails the committed edit: the marker then no longer matches the page
    and Move / Rotate refuse it (``_textbox_payload_drawn_on_page``).
    """
    member_spans = sorted(
        _member_spans(resolve_result),
        key=lambda span: (span.block_idx, span.line_idx, span.span_idx),
    )
    source_text = "".join(span.text or "" for span in member_spans) or (resolve_result.target.text or "")
    member_rects = [fitz.Rect(span.bbox) for span in member_spans] or [
        fitz.Rect(resolve_result.target.layout_rect)
    ]
    try:
        sync_textbox_markers_after_text_edit(
            model,
            page_num,
            member_rects=member_rects,
            source_text=source_text,
            new_text=new_text,
            destination_rect=new_rect,
            style=style,
            words_before=words_before,
        )
    except Exception:
        logger.exception("textbox marker sync after the text edit failed (page %s)", page_num)


def _strip_ws(text: str | None) -> str:
    return "".join((text or "").split())


def _choose_anchor_run(
    rebuilt_runs: list[EditableSpan],
    anchor_rect: fitz.Rect,
    region: fitz.Rect,
    norm_new: str,
    *,
    multi_show: bool,
) -> EditableSpan | None:
    """The rebuilt run a reopen anchor may move onto, or ``None`` = drop it.

    ``rebuild_page`` reassigns span ids, so the anchor must follow the edit
    onto the run the edit produced.  Distance alone is not evidence: the
    nearest run to the old box can be an unrelated line (F14-ANCHOR-STALE --
    a heading re-inserted as two runs was anchored onto the text above it).
    Ranking, best first:

    0. a run whose text IS the rewritten text (nearest to the anchor wins);
    1. a run that is a fragment of the rewritten text lying in ``region`` --
       for a grouped show the caller regroups it, otherwise the edit was
       re-inserted as several runs, no single one proves it, and planting
       the old box on one of them would reopen that fragment over its
       neighbours, so the anchor is dropped (live run boxes serve the click);
    2. no text evidence (extraction drift, an emptied run): the single run
       inside ``region``; zero or several are ambiguous, so none.

    A run outside ``region`` (the old box united with the new layout box) is
    never chosen.
    """
    cx = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
    cy = float(anchor_rect.y0 + (anchor_rect.height / 2.0))

    def _dist_sq(span: EditableSpan) -> float:
        box = fitz.Rect(span.bbox)
        return (float(box.x0 + box.width / 2.0) - cx) ** 2 + (
            float(box.y0 + box.height / 2.0) - cy
        ) ** 2

    exact: list[EditableSpan] = []
    fragments: list[EditableSpan] = []
    in_region: list[EditableSpan] = []
    for span in rebuilt_runs:
        if not fitz.Rect(span.bbox).intersects(region):
            continue
        in_region.append(span)
        norm_span = normalize_text(span.text or "")
        if not norm_new or not norm_span:
            continue
        if norm_span == norm_new:
            exact.append(span)
        elif norm_span in norm_new:
            fragments.append(span)
    if exact:
        return min(exact, key=_dist_sq)
    if fragments:
        return min(fragments, key=_dist_sq) if multi_show else None
    if len(in_region) == 1:
        return in_region[0]
    return None


def _record_joined_edit_run(
    model: PDFModel,
    page_idx: int,
    new_text: str,
    resolve_result: _EditTextResolveResult,
    new_layout_rect: fitz.Rect,
) -> None:
    """S17-ANCHOR-JOIN: remember that the rebuild wrote ``new_text`` as several
    runs on one baseline, so the next click opens them as ONE box.

    A record is kept only when the rebuilt page really shows exactly
    ``new_text`` as two or more runs of one line inside the edit's region.
    Bookkeeping only: it can never fail the committed edit.  Older records are
    left alone -- they prove only while the page shows their text, so undo
    revives them.
    """
    try:
        old_rects = [fitz.Rect(span.bbox) for span in _member_spans(resolve_result)] or [
            fitz.Rect(resolve_result.target.layout_rect)
        ]
        old_union = rect_union(old_rects)
        fragments = find_joined_fragments(
            model.block_manager.get_runs(page_idx),
            normalize_text(new_text or ""),
            fitz.Rect(old_union) | fitz.Rect(new_layout_rect),
        )
        if fragments:
            model._remember_joined_edit_run(page_idx, joined_record_for(new_text, fragments))
    except Exception as joined_exc:
        logger.debug("joined edit-run bookkeeping skipped: %s", joined_exc)


def _rederive_source_group(
    model: PDFModel, page_idx: int, span_id: str
) -> SourceRunGroup | None:
    """The proven source show containing ``span_id``, from the model's own
    resolver (the per-page cache the hit warmed; pull-validated against the
    live stream digest and the index's run list).  ``None`` = not provable."""
    doc = model.doc
    if doc is None:
        return None
    resolver = getattr(model, "_source_run_resolver", None)
    if not isinstance(resolver, SourceRunResolver):
        resolver = SourceRunResolver()
        try:
            model._source_run_resolver = resolver
        except Exception:
            pass
    try:
        runs = model.block_manager.get_runs(page_idx)
        return resolver.group_for_span(doc, page_idx, runs, span_id)
    except Exception:  # fail closed: nothing provable
        logger.debug("edit_text: source-show re-derivation failed", exc_info=True)
        return None


class _RebuildRolledBack(TextEditRefused):
    """The legacy rebuild failed AFTER ``_rollback_rebuild_page`` put the page
    back: ``edit_text`` must not roll back a second time.  Carries the stable
    refusal code the Controller turns into one zh-TW sentence (ZH-REFUSALS)."""


def _rollback_rebuild_page(
    model: PDFModel,
    page_idx: int,
    snapshot_bytes: bytes,
    maintenance_book: MaintenanceBook | None,
) -> None:
    """The ONE rollback of a failed legacy (redact + reinsert) edit.

    The rewrite revoked the page's fidelity protection and queued a
    ``clean_contents`` entry (``mark_page_content_dirty``); restoring only the
    bytes would leave a verified Tier 0 page unprotected and pending, so the
    next save would clean it and its undo would go stale (R5-BOOK-1).  The
    book is restored only AFTER the bytes are back: a failed byte restore
    raises first and the truthful dirty bookkeeping stays.
    """
    model._restore_page_from_snapshot(page_idx, snapshot_bytes)
    if maintenance_book is not None:
        maintenance_book.restore(model)
    model.block_manager.rebuild_page(page_idx, model.doc)


def _roll_back_and_refuse(
    model: PDFModel,
    page_idx: int,
    snapshot_bytes: bytes,
    maintenance_book: MaintenanceBook | None,
    reason: TextEditRefusal,
    detail: str,
) -> _RebuildRolledBack:
    """Put the page back (``_rollback_rebuild_page``) and build the refusal
    to raise for it -- ``raise _roll_back_and_refuse(...)`` at every site, so
    ``_RebuildRolledBack``'s promise (the page is back BEFORE the exception
    exists) holds by construction.  A rollback that fails raises here instead,
    and ``edit_text`` sees a plain error from inside the rewrite (its own
    attempt then reports ``ROLLBACK_FAILED``)."""
    _rollback_rebuild_page(model, page_idx, snapshot_bytes, maintenance_book)
    return _RebuildRolledBack(reason, detail)


def _rollback_failed_refusal(model: PDFModel, detail: str) -> TextEditRefused:
    """The ``ROLLBACK_FAILED`` refusal, with the session latched damaged first.

    The rewrite may have left a half-rewritten page and no undo entry exists;
    the Controller's sentence says so, and the latch is what actually stops a
    later in-place save from writing that page over the original file
    (S13-DLG5-DAMAGED).  The ONE builder for every site that raises it.
    """
    model.mark_session_damaged("text edit rollback failed")
    return TextEditRefused(TextEditRefusal.ROLLBACK_FAILED, detail)


# ── Owned-glyph redaction (F13-VF-2) ────────────────────────────────────────
# A legacy rewrite erases some runs and re-draws them.  Redacting their
# bounding box (or the bounding box of several runs) also erased every OTHER
# glyph inside it -- the tail of the word on the line above, the head of the
# next word -- which nothing replayed or checked.  The rewrite now erases
# exactly the glyphs it owns (one tiny redaction at each owned glyph's
# centre, just above its baseline) and proves afterwards that no other glyph
# on the page went away.

_GLYPH_REDACT_HALF = 0.1  # pt; a point-sized redaction inside the glyph
# MuPDF redacts a glyph whose box (origin, advance, the FONT's ascender and
# descender) touches a redaction.  That box is not the extracted one: for
# MSBM10 (ascender 0.464 em, descender 0) the extracted box centre lies above
# it.  A point on the glyph's advance midline a little above the baseline is
# inside MuPDF's box for any font with an ascender above this fraction.
_GLYPH_REDACT_LIFT_EM = 0.15
_OWN_TOL = 0.5  # pt; a glyph belongs to a run whose box contains it
# Removing glyphs from a show re-emits the glyphs after them; their origins
# can move by a rounding step (518.45 -> 518.46).  A glyph is still there when
# the same character is within this distance of where it was.
_GLYPH_MATCH_TOL = 0.3  # pt


class _PageGlyph(NamedTuple):
    key: tuple[str, int, int]  # (char, origin x * 10, origin y * 10)
    bbox: fitz.Rect
    block_idx: int
    inked: bool  # False for whitespace: nothing to see, nothing to lose
    origin: tuple[float, float]
    size: float
    direction: tuple[float, float]  # the line's unit writing direction
    line: tuple[int, int] = (-1, -1)  # (block, line) in the extraction
    # Distance to the next glyph origin along ``direction``; set only for
    # glyphs written off the page axes, whose extracted box is the bbox of a
    # turned box and so cannot give the glyph's own length (F15-VF4OV-DIAGONAL).
    advance: float = 0.0


class _OwnedRedaction(NamedTuple):
    survivors: list[str]  # owned glyphs still on the page
    lost_foreign: list[str]  # glyphs the rewrite did not own that are gone


def _page_glyphs(page: fitz.Page, flags: int = 0) -> list[_PageGlyph]:
    """Every content glyph (annotations excluded, F11-ANN-4).  ``flags=0``
    is the extraction the run index is built from (``TextBlockManager``),
    so a run's box is exactly the union of its glyphs' boxes here."""
    return _glyphs_from_rawdict(
        content_text(page, "rawdict", textpage=content_textpage(page, flags))
    )


def _glyphs_from_rawdict(raw: dict) -> list[_PageGlyph]:
    """``_page_glyphs`` over a content ``rawdict`` already extracted (with the
    flags the keys it is compared with were built from, and the page
    unchanged since): a caller that holds one need not extract twice."""
    out: list[_PageGlyph] = []
    for block_idx, block in enumerate(raw.get("blocks", ())):
        for line_idx, line in enumerate(block.get("lines", ())):
            dx, dy = (float(v) for v in (line.get("dir") or (1.0, 0.0)))
            norm = (dx * dx + dy * dy) ** 0.5 or 1.0
            direction = (dx / norm, dy / norm)
            line_start = len(out)
            for span in line.get("spans", ()):
                size = float(span.get("size") or 0.0)
                for ch in span.get("chars", ()):
                    c = ch.get("c", "")
                    if not c or ch.get("synthetic"):
                        continue
                    bbox = fitz.Rect(ch["bbox"])
                    ox, oy = (float(v) for v in ch.get("origin", (bbox.x0, bbox.y1)))
                    out.append(
                        _PageGlyph(
                            (c, round(ox * 10), round(oy * 10)),
                            bbox,
                            block_idx,
                            not c.isspace(),
                            (ox, oy),
                            size,
                            direction,
                            (block_idx, line_idx),
                        )
                    )
            if not _is_axis_aligned_dir(direction):
                _fill_glyph_advances(out, line_start)
    return out


def _fill_glyph_advances(glyphs: list[_PageGlyph], start: int) -> None:
    """Set ``advance`` on ``glyphs[start:]`` (one line written off the page
    axes): the distance from each origin to the next along the line's
    direction, the previous glyph's for the last one, half an em when the line
    has a single glyph."""
    n = len(glyphs) - start
    if n <= 0:
        return
    ux, uy = glyphs[start].direction
    order = sorted(
        range(start, start + n),
        key=lambda i: glyphs[i].origin[0] * ux + glyphs[i].origin[1] * uy,
    )
    steps: dict[int, float] = {}
    for a, b in zip(order, order[1:]):
        step = (glyphs[b].origin[0] - glyphs[a].origin[0]) * ux + (
            glyphs[b].origin[1] - glyphs[a].origin[1]
        ) * uy
        if step > 0.05:
            steps[a] = step
    previous = 0.0
    for i in order:
        step = steps.get(i, previous)
        if step <= 0.05:
            step = 0.5 * glyphs[i].size
        glyphs[i] = glyphs[i]._replace(advance=step)
        previous = step


def _glyph_redact_point(g: _PageGlyph) -> fitz.Point:
    """A point inside MuPDF's redaction box of ``g``: on the baseline below
    the extracted box centre, lifted towards the ascender."""
    ox, oy = g.origin
    ux, uy = g.direction
    cx = (g.bbox.x0 + g.bbox.x1) / 2.0
    cy = (g.bbox.y0 + g.bbox.y1) / 2.0
    along = (cx - ox) * ux + (cy - oy) * uy
    lift = _GLYPH_REDACT_LIFT_EM * g.size
    # "Up" (towards the ascender) in page space, whose y axis points down.
    return fitz.Point(ox + ux * along + uy * lift, oy + uy * along - ux * lift)


def _glyphs_still_present(
    glyphs: list[_PageGlyph], after: list[_PageGlyph]
) -> list[_PageGlyph]:
    """The inked ``glyphs`` that ``after`` still holds: same character, origin
    within ``_GLYPH_MATCH_TOL``.

    ``after`` is indexed by character and a grid cell two tolerances wide, so
    a glyph is only compared with the candidates of the 3x3 cells around its
    own (two origins within the tolerance of each other are at most one cell
    apart, with a whole tolerance to spare).  The match test is the same, so
    the result -- and its order, that of ``glyphs`` -- is exactly the
    all-pairs scan's; a dense page (5000 glyphs) takes a few ms instead of
    ~26 ms per call, and the rewrite calls this three times or more."""
    tol = _GLYPH_MATCH_TOL
    cell = 2.0 * tol
    by_cell: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    for a in after:
        if a.inked:
            ax, ay = a.origin
            by_cell.setdefault(
                (a.key[0], math.floor(ax / cell), math.floor(ay / cell)), []
            ).append((ax, ay))
    present = []
    for g in glyphs:
        if not g.inked:
            continue
        gx, gy = g.origin
        char, cx, cy = g.key[0], math.floor(gx / cell), math.floor(gy / cell)
        if any(
            abs(ax - gx) <= tol and abs(ay - gy) <= tol
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for ax, ay in by_cell.get((char, cx + dx, cy + dy), ())
        ):
            present.append(g)
    return present


def _rect_holds(outer: fitz.Rect, inner: fitz.Rect, tol: float = _OWN_TOL) -> bool:
    return (
        inner.x0 >= outer.x0 - tol
        and inner.y0 >= outer.y0 - tol
        and inner.x1 <= outer.x1 + tol
        and inner.y1 <= outer.y1 + tol
    )


def _glyphs_owned_by_runs(
    glyphs: list[_PageGlyph], runs: list[EditableSpan], fallback_rect: fitz.Rect
) -> list[_PageGlyph]:
    """The glyphs of ``runs``: in the run's own block and inside its box.

    A glyph of another block that happens to lie inside a run's box is not
    the run's (two-hop neighbours, overlapping text objects).  A run that
    owns no inked glyph that way (index drift) owns the glyphs its box holds
    in any block, and with no usable run box the ``fallback_rect`` decides.
    """
    owned: dict[int, _PageGlyph] = {}
    run_rects = [
        (rect, int(r.block_idx)) for r in runs if not (rect := fitz.Rect(r.bbox)).is_empty
    ]
    if not run_rects:
        run_rects = [(fitz.Rect(fallback_rect), -1)]
    for rect, block_idx in run_rects:
        mine = [
            i for i, g in enumerate(glyphs)
            if g.block_idx == block_idx and _rect_holds(rect, g.bbox)
        ]
        if not any(glyphs[i].inked for i in mine):
            mine = [i for i, g in enumerate(glyphs) if _rect_holds(rect, g.bbox)]
        for i in mine:
            owned[i] = glyphs[i]
    return list(owned.values())


def _owned_redaction_rects(
    glyphs_before: list[_PageGlyph], owned: list[_PageGlyph]
) -> list[fitz.Rect]:
    """The text redactions that erase ``owned``.

    One redaction per glyph costs ~3.5 ms (annotation + apply), so a
    paragraph of 1300 glyphs took 4.5 s.  Owned glyphs that follow each other
    on one axis-aligned line, with no foreign inked glyph of that line between
    them, share one 0.2 pt strip joining their redaction points; anything
    else (a slanted line, a lone glyph) keeps its own point.
    """
    h = _GLYPH_REDACT_HALF
    owned_ids = {id(g) for g in owned}
    by_line: dict[tuple[int, int], list[_PageGlyph]] = {}
    for g in glyphs_before:
        if g.line != (-1, -1):
            by_line.setdefault(g.line, []).append(g)
    rects: list[fitz.Rect] = []
    grouped: set[int] = set()
    for line_glyphs in by_line.values():
        ux, uy = line_glyphs[0].direction
        if min(abs(ux), abs(uy)) > 1e-3:
            continue  # slanted: per-glyph points below
        ordered = sorted(
            line_glyphs, key=lambda g: g.origin[0] * ux + g.origin[1] * uy
        )
        strip: list[fitz.Point] = []

        def close() -> None:
            if strip:
                xs = [p.x for p in strip]
                ys = [p.y for p in strip]
                rects.append(fitz.Rect(min(xs) - h, min(ys) - h, max(xs) + h, max(ys) + h))
                strip.clear()

        for g in ordered:
            if id(g) in owned_ids:
                strip.append(_glyph_redact_point(g))
                grouped.add(id(g))
            elif g.inked:
                close()
        close()
    for g in owned:
        if id(g) not in grouped:
            p = _glyph_redact_point(g)
            rects.append(fitz.Rect(p.x - h, p.y - h, p.x + h, p.y + h))
    return rects


def _redact_owned_glyphs(
    page: fitz.Page,
    glyphs_before: list[_PageGlyph],
    owned: list[_PageGlyph],
    line_art_rects: list[fitz.Rect],
    flags: int = 0,
) -> _OwnedRedaction:
    """Erase exactly ``owned`` (and the line art each ``line_art_rects`` box
    fully covers, as the box redaction did); report what went wrong.

    Text: a point-sized redaction inside each owned glyph
    (``_glyph_redact_point``; joined into strips along a line by
    ``_owned_redaction_rects``), so MuPDF removes those glyphs and only a
    glyph drawn over the same points -- never the rest of a bounding box.
    Line art: the rewrite's own boxes, text untouched.  The caller refuses on
    either list (and rolls back).
    """
    # S17-WMARK-UNDER: MuPDF erases a turned glyph whose (square) box holds a
    # redaction point, whether or not the glyph is near that point.  Keep the
    # streams to put such text back; skipped when the page has no turned text.
    _streams_before = (
        read_streams(page.parent, page)
        if owned and any(not _is_axis_aligned_dir(g.direction) for g in glyphs_before)
        else None
    )
    line_art = [rect for rect in line_art_rects if not rect.is_empty]
    for rect in line_art:
        page.add_redact_annot(rect)
    if line_art:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            text=fitz.PDF_REDACT_TEXT_NONE,
        )
    for rect in _owned_redaction_rects(glyphs_before, owned):
        page.add_redact_annot(rect)
    if owned:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )
    owned_keys = {g.key for g in owned}
    foreign = [g for g in glyphs_before if g.inked and g.key not in owned_keys]

    def _lost_foreign(after: list[_PageGlyph]) -> list[_PageGlyph]:
        kept = {id(g) for g in _glyphs_still_present(foreign, after)}
        return [g for g in foreign if id(g) not in kept]

    after = _page_glyphs(page, flags)
    lost = _lost_foreign(after)
    if (
        lost
        and _streams_before is not None
        and all(not _is_axis_aligned_dir(g.direction) for g in lost)
        and all(_is_axis_aligned_dir(g.direction) for g in owned)
        and restore_turned_shows(page.parent, page, _streams_before)
    ):
        # Only turned (watermark-like) glyphs were lost, and the edit's own
        # glyphs are upright: the redaction took them by their box, not their
        # ink.  Their shows are back as written; re-measure what is still lost.
        after = _page_glyphs(page, flags)
        lost = _lost_foreign(after)
        if not lost and sum(1 for g in after if g.inked) != (
            sum(1 for g in glyphs_before if g.inked) - sum(1 for g in owned if g.inked)
        ):
            # Every lost glyph is back but the page holds another count of ink
            # than "before minus the erased word": a repair that put something
            # twice (or somewhere else) is no repair.  Report the loss.
            logger.warning("turned text restore changed the glyph count; refusing it")
            lost = foreign[:1]
    return _OwnedRedaction(
        survivors=sorted({g.key[0] for g in _glyphs_still_present(owned, after)}),
        lost_foreign=sorted({g.key[0] for g in lost}),
    )


class _RebuildMarkup(NamedTuple):
    """The htmlbox markup of one legacy rebuild insert (and the inputs the
    insert strategies reuse).  Built by ONE function so the insert and the
    verification's reference render can never diverge (OD-UNI1-COMMIT)."""

    member_spans: list[EditableSpan]
    preserve_multi_style: bool
    line_height: float
    html: str
    css: str
    # D-RTL-GROW: the edited runs grow right-to-left AND the new text is
    # right-to-left (``_spans_grow_right_to_left``); ``css`` then lays the
    # markup out as a right-to-left paragraph.
    rtl: bool = False


def _rebuild_insert_markup(
    model: PDFModel,
    *,
    page_num: int,
    new_text: str,
    size: float,
    color: tuple,
    resolve_result: _EditTextResolveResult,
) -> _RebuildMarkup:
    member_spans = _member_spans(resolve_result)
    member_colors_distinct = {
        tuple(round(float(c), 3) for c in (s.color or (0.0, 0.0, 0.0)))
        for s in member_spans
    }
    request_color_rounded = tuple(
        round(float(c), 3) for c in (color or (0.0, 0.0, 0.0))
    )
    preserve_multi_style = (
        resolve_result.effective_target_mode == "paragraph"
        and len(member_colors_distinct) > 1
        and request_color_rounded in member_colors_distinct
    )

    if preserve_multi_style:
        html_content = model._build_multi_style_html(
            new_text,
            member_spans,
            default_color=color,
            latin_font=resolve_result.resolved_font,
        )
        logger.debug(
            "multi-style paragraph preserve: page=%s members=%s distinct_colors=%s",
            page_num,
            len(member_spans),
            len(member_colors_distinct),
        )
    else:
        html_content = model._convert_text_to_html(
            new_text, size, color, latin_font=resolve_result.resolved_font
        )
    # 行高保真：從 member_spans 推導原 PDF 的真實 leading。多行時取
    # 相鄰 baseline (origin.y) 推進的中位數；單行時取最大 bbox 高度。
    # 明確傳入 _build_insert_css，繞過自動 line-height 夾擠，避免
    # committed box 比原文字高/矮而推擠相鄰文字。
    #
    # 垂直（/Rotate 90/270 圖紙）文字：行的「厚度」在未旋轉空間是 x 方向，bbox 的
    # y 方向長度是文字長度而不是行高。用 y 會得到 ~27pt 的行高：rect 模式整段被
    # 縮到 43%，無 rect 模式字被推離釘住的邊約 8.5pt（ROT90-UP-1）。
    _line_ht = 0.0
    if member_spans:
        _vertical = bool(resolve_result.is_vertical)
        origins_y = sorted({
            round(float(s.origin.x if _vertical else s.origin.y), 2)
            for s in member_spans
        })
        if len(origins_y) >= 2:
            advances = sorted(
                b - a for a, b in zip(origins_y, origins_y[1:]) if (b - a) > 0.5
            )
            if advances:
                _line_ht = advances[len(advances) // 2]
        if _line_ht <= 0.0:
            if _vertical:
                _line_ht = max(
                    float(s.bbox.x1) - float(s.bbox.x0) for s in member_spans
                )
            else:
                _line_ht = max(
                    float(s.bbox.y1) - float(s.bbox.y0) for s in member_spans
                )
    css = model._build_insert_css(
        size, color, resolve_result.resolved_font, line_height=_line_ht
    )
    rtl = _spans_grow_right_to_left(model, member_spans, new_text)
    if rtl:
        css += _RTL_BASE_CSS
    return _RebuildMarkup(
        member_spans=member_spans,
        preserve_multi_style=preserve_multi_style,
        line_height=_line_ht,
        html=html_content,
        css=css,
        rtl=rtl,
    )


# A dragged edit that moved less than this (pt) still sits where the source text
# was: the overlap cluster's neighbours stay in its domain (S17-DRAG-GUARD).
_DRAG_MOVED_TOL_PT = 0.5


def _apply_redact_insert(model: PDFModel, **kwargs: Any) -> fitz.Rect:
    """The legacy redact + reinsert operation, as ONE font-compaction scope.

    Every ``insert_htmlbox`` below (replay of protected spans, pre-push probe
    push-down, vertical retry, strategies A/B/C) embeds its own copy of the
    font; the scope dedupes and Flate-compresses them once on a normal exit,
    before the caller captures the command's after-snapshot.  A failure
    (strategy C rollback, ...) leaves the document to the caller's rollback.
    """
    page = kwargs["page"]
    with font_compaction_scope(page.parent):
        return _apply_redact_insert_body(model, **kwargs)


def _apply_redact_insert_body(
    model: PDFModel,
    *,
    page: fitz.Page,
    page_num: int,
    page_idx: int,
    page_rect: fitz.Rect,
    new_text: str,
    size: float,
    color: tuple,
    vertical_shift_left: bool,
    new_rect: fitz.Rect | None,
    snapshot_bytes: bytes,
    resolve_result: _EditTextResolveResult,
    maintenance_book: MaintenanceBook | None = None,
    source_rect: fitz.Rect | None = None,
    place_anyway: bool = False,
    paint: _RebuildPaint | None = None,
) -> fitz.Rect:
    # F17-COL-1..4: what the rebuild writes again keeps its paint state; the
    # capture runs before anything is erased (``edit_text`` takes it before
    # the consent; a direct caller gets it here) and refuses an unkeepable one.
    if paint is None:
        paint = _rebuild_paint(
            model, page, resolve_result,
            new_text=new_text, color=color, moved=new_rect is not None,
        )
    _saved_annots = model.tools.annotation._save_overlapping_annots(page, resolve_result.redact_rect)
    # Erase the cluster's own glyphs only (F13-VF-2): ``redact_rect`` is the
    # cluster's bounding box, which also holds glyphs of runs outside the
    # cluster (never replayed, never validated).  It still bounds the
    # annotation save above and the dirty region below.
    _glyphs_before = _page_glyphs(page)
    _cluster_rects = [
        fitz.Rect(s.bbox) for s in resolve_result.overlap_cluster if not fitz.Rect(s.bbox).is_empty
    ]
    _redaction = _redact_owned_glyphs(
        page,
        _glyphs_before,
        _glyphs_owned_by_runs(
            _glyphs_before, resolve_result.overlap_cluster, resolve_result.redact_rect
        ),
        _cluster_rects or [fitz.Rect(resolve_result.redact_rect)],
    )
    _survivors = _redaction.survivors
    if _survivors:
        logger.warning(
            "rebuild redaction left the source glyphs on page=%s rect=%s survivors=%s",
            page_num,
            resolve_result.redact_rect,
            _survivors,
        )
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            TextEditRefusal.REDACTION_LEFT_SOURCE,
            "overlap edit redaction failed: the original text is still on the page after "
            f"redaction (vertical or unredactable text): {', '.join(_survivors)}",
        )
    if _redaction.lost_foreign:
        logger.warning(
            "rebuild redaction would erase %s untouched glyph(s) outside the edited runs "
            "on page=%s rect=%s",
            len(_redaction.lost_foreign),
            page_num,
            resolve_result.redact_rect,
        )
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST,
            "overlap edit redaction failed: erasing the edited runs also erased "
            f"{len(_redaction.lost_foreign)} glyph(s) of untouched text",
        )
    if _saved_annots:
        model.tools.annotation._restore_annots(page, _saved_annots)
    if resolve_result.protected_spans:
        model._replay_protected_spans(page, resolve_result.protected_spans, paint.protected)
    model.mark_page_content_dirty(page_idx, fitz.Rect(resolve_result.redact_rect))
    logger.debug(
        "overlap_redaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s redact_rect=%s",
        page_num,
        resolve_result.resolved_target_span_id,
        resolve_result.effective_target_mode,
        len(resolve_result.overlap_cluster),
        len(resolve_result.protected_spans),
        resolve_result.redact_rect,
    )

    _markup = _rebuild_insert_markup(
        model,
        page_num=page_num,
        new_text=new_text,
        size=size,
        color=color,
        resolve_result=resolve_result,
    )
    member_spans = _markup.member_spans
    preserve_multi_style = _markup.preserve_multi_style
    _line_ht = _markup.line_height
    html_content = _markup.html
    css = _markup.css
    # D-RTL-GROW (owner decision): a right-to-left run keeps the edge its
    # reading starts at -- its RIGHT edge upright -- and grows away from it.
    # Every along-the-line choice below (the pinned box edge, the wall, the
    # neighbour side, the placement measure) flips with it; the line stacking
    # (which way extra lines go) follows the text rotation only.
    rtl = _markup.rtl
    rotation = int(resolve_result.rotation)
    is_vertical = bool(resolve_result.is_vertical)
    # The edited runs' own extent (not the block's): "in place" is where they
    # were, and text already past the safe margin is walled at the page edge,
    # not at a margin left of itself (F14-DT-1).
    _edit_extent = rect_union([fitz.Rect(s.bbox) for s in member_spans])

    # Overprint guard (F14-VF4-WRAP): an in-place horizontal rewrite must
    # never be drawn over untouched text, except text the edited runs already
    # covered in the source (an overlap cluster).  Quarter-turn edits are
    # guarded too (F13-VF-4b).  A dragged box is guarded as well but never
    # capped (S17 / F13-VF-4c, owner decision): the user's placement wins on
    # size, not over other text.  ``place_anyway`` is the user's per-edit
    # answer to that refusal and lifts the guard (an edit with no ``new_rect``
    # ignores it: its guard stays on).
    _guard_overprint = new_rect is None or not place_anyway
    # The overlap cluster's replayed neighbours (text the edited run was
    # drawn on top of in the source, overlap textbox edits) are the edit's
    # own domain: the rewrite may cover them again.  They are bounded by the
    # F13-VF-4 / F13-VF-4b neighbour caps.
    _overprint_exempt: list[fitz.Rect] = (
        [fitz.Rect(s.bbox) for s in resolve_result.protected_spans]
        if _guard_overprint
        else []
    )

    def _refuse_if_overprinted(before_insert: list[_PageGlyph] | None) -> None:
        if before_insert is None:
            return
        hits = _new_text_overprints(before_insert, _page_glyphs(page), _overprint_exempt)
        if not hits:
            return
        logger.warning(
            "rebuild would draw the edited text over untouched text page=%s: %s",
            page_num,
            hits[:5],
        )
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            # A dragged box has its own code: the Controller offers "place
            # anyway" for it, and "reduce the text" is the wrong advice.
            TextEditRefusal.TEXT_DOES_NOT_FIT
            if new_rect is None
            else TextEditRefusal.DRAGGED_BOX_OVERPRINTS,
            "the edited text does not fit without being drawn over untouched "
            f"text ({len(hits)} glyph(s), e.g. {hits[0]}); rolled back.",
        )

    # How far a dragged run moves: its new rect's corner minus the corner of
    # the rect the drag started from (F14-VM-2).  A rewrite in place, and a
    # drag whose rect the page clamp emptied (below), do not move.
    drag_delta = fitz.Point(0, 0)
    if new_rect is not None:
        clamped_new = fitz.Rect(
            max(float(new_rect.x0), page_rect.x0),
            max(float(new_rect.y0), page_rect.y0),
            min(float(new_rect.x1), page_rect.x1 - 5),
            min(float(new_rect.y1), page_rect.y1 - 5),
        )
        # A sliver check, not a minimum size: this rect is in UNROTATED space, so on a
        # /Rotate 90/270 page its width is the VISUAL line height (3-5 pt on drawing
        # sheets).  Only fall back when the page clamp shrank the box below 5 pt AND
        # below what the caller asked for (E2E3-1).
        _min_w = min(5.0, float(new_rect.width))
        if (clamped_new.is_empty or clamped_new.is_infinite
                or clamped_new.width < _min_w):
            logger.warning("new_rect %s clamped 後為空，退回原位插入", new_rect)
            # "In place" is the edited run(s), not the BLOCK: a table row is one
            # PyMuPDF block holding several cells, and its rect starts at the
            # row's first cell (F13-VF-1).
            clamped_new = fitz.Rect(
                _edit_extent if not _edit_extent.is_empty else resolve_result.target.layout_rect
            )
        else:
            _drag_from = fitz.Rect(source_rect) if source_rect is not None else None
            if _drag_from is None or _drag_from.is_empty:
                _drag_from = _edit_extent
            if not _drag_from.is_empty:
                drag_delta = fitz.Point(
                    float(clamped_new.x0) - float(_drag_from.x0),
                    float(clamped_new.y0) - float(_drag_from.y0),
                )
                if rtl:
                    # The anchored edge moves with the drag: the page clamp
                    # trims the far side of the new rect, not the start.
                    if is_vertical:
                        if rotation == 90:  # reads down: starts (RTL) at y1
                            drag_delta.y = float(clamped_new.y1) - float(_drag_from.y1)
                    elif rotation != 180:  # upright: starts (RTL) at x1
                        drag_delta.x = float(clamped_new.x1) - float(_drag_from.x1)
        base_layout = clamped_new
        if abs(drag_delta.x) > _DRAG_MOVED_TOL_PT or abs(drag_delta.y) > _DRAG_MOVED_TOL_PT:
            # The text left the spot the overlap cluster was drawn at, so the
            # neighbours it covered in the source are no longer its domain: a
            # drop on one of them is an overprint like a drop on any other run.
            _overprint_exempt.clear()
    else:
        base_layout = fitz.Rect(
            resolve_result.reopen_anchor_rect
            if resolve_result.reopen_anchor_rect is not None
            else resolve_result.target.layout_rect
        )

    # 快/慢路徑分類，預覽（view.PreviewRenderer）與 commit（此處）共用
    # 同一 _classify_insert_path，確保開啟編輯框與最終 PDF 用同一渲染器。
    needs_cjk = model._needs_cjk_font(new_text)
    fast_margin = 15
    right_wall = _right_wall(page_rect, float(size), _edit_extent)
    # An upside-down run (text rotation 180) is written toward -x and stacks its
    # extra lines UP the page: its box is pinned on its right edge and bottom,
    # and the wall, the neighbour and the wrap limit are the mirrored ones
    # (F16-2).  Only the horizontal in-place htmlbox route reads this.
    # ``grows_left`` is the along-the-line half (box pinned on its RIGHT edge,
    # left wall, neighbour on the left): upside-down XOR right-to-left
    # (D-RTL-GROW: upright Hebrew grows left, upside-down Hebrew grows toward
    # +x).  ``stacks_up`` is the across half and follows the rotation alone.
    stacks_up = rotation == 180 and not is_vertical
    grows_left = (rotation == 180) != rtl and not is_vertical
    left_wall = _left_wall(page_rect, float(size), _edit_extent)
    fast_available_w = max(
        0.0,
        right_wall - max(float(base_layout.x0), page_rect.x0) - fast_margin,
    )
    # An edit that is dragged to a new rect is where the user put it; every
    # other horizontal edit keeps its line and must clear the next run on it.
    neighbour_limit: float | None = None
    # A quarter-turn edit grows along its reading direction instead: it must
    # stop short of the next run on its column (F13-VF-4b).
    reads_up = is_vertical and rotation == 270
    # Which way its box grows along the column: up the page for text reading
    # up, down for text reading down -- and the other way round for
    # right-to-left text, which keeps the end it starts at (D-RTL-GROW).
    # ``reads_up`` itself stays the line-stacking side (first line left/right).
    grows_up = reads_up != (rtl and is_vertical)
    vertical_limit: float | None = None
    if new_rect is None and not is_vertical:
        neighbour_limit = _horizontal_neighbour_limit(
            model, page_idx, member_spans, resolve_result.target_member_span_ids,
            grows_left=grows_left,
        )
    elif new_rect is None:
        vertical_limit = _vertical_neighbour_limit(
            model, page_idx, member_spans, resolve_result.target_member_span_ids,
            reads_up=grows_up,
        )
    if neighbour_limit is not None and not grows_left:
        fast_available_w = min(
            fast_available_w,
            max(0.0, neighbour_limit - max(float(base_layout.x0), page_rect.x0))
            + _NEIGHBOUR_FIT_TOL_PT,
        )
    fast_insert_font = model._resolve_font_for_push(resolve_result.resolved_font)
    try:
        _fast_font_obj = fitz.Font(fast_insert_font)
        fast_text_width = _fast_font_obj.text_length(new_text, fontsize=size)
    except Exception:
        fast_insert_font = "helv"
        fast_text_width = fitz.Font(fast_insert_font).text_length(
            new_text, fontsize=size
        )

    insert_path = _classify_insert_path(
        new_text=new_text,
        member_spans=member_spans,
        rotation=rotation,
        is_vertical=is_vertical,
        preserve_multi_style=preserve_multi_style,
        has_new_rect=new_rect is not None,
        needs_cjk=needs_cjk,
        text_width=fast_text_width,
        available_width=fast_available_w,
        size=size,
        rtl=rtl,
    )

    if insert_path == "fast":
        origin_span = min(
            member_spans,
            key=lambda span: (float(span.origin.x), float(span.origin.y)),
        )
        origin = fitz.Point(
            float(origin_span.origin.x),
            float(origin_span.origin.y),
        )
        _fast_before = _page_glyphs(page) if _guard_overprint else None
        with paint_state_applied(page, paint.edit):
            insert_text_page_space(
                page,
                origin,
                new_text,
                fontname=fast_insert_font,
                fontsize=float(size),
                color=tuple(float(c) for c in color),
                rotate=0,
            )
        _refuse_if_overprinted(_fast_before)
        return fitz.Rect(
            _edit_extent.x0,
            _edit_extent.y0,
            min(_edit_extent.x0 + fast_text_width, page_rect.x1 - 10),
            _edit_extent.y1,
        )

    # The htmlbox draws the first glyph off its rect's corner (1 pt in, at the
    # substitute font's line-box ascent): every insert below moves its rect so
    # the text START of its first line (``_start_point``, never the first DRAWN
    # glyph: F15-VM2-RTL) lands on the original origin, plus the drag (F14-VM-2).
    _start = _start_glyph_origin(member_spans, rotation, float(size), rtl=rtl)
    target_origin = (
        fitz.Point(_start.x + drag_delta.x, _start.y + drag_delta.y)
        if _start is not None
        else None
    )

    def _insert_edited_text(rect: fitz.Rect, scale_low: float) -> tuple[float, float]:
        placed = _align_htmlbox_rect(
            page, rect, html_content, css,
            origin=target_origin, rotate=resolve_result.insert_rotate, scale_low=scale_low,
            rtl=rtl,
        )
        with paint_state_applied(page, paint.edit):
            return insert_htmlbox_tracked(
                page, placed, html_content, css=css,
                rotate=resolve_result.insert_rotate, scale_low=scale_low,
            )

    # Where the htmlbox starts the text.  Text reading DOWN the unrotated page
    # (run rotation 90, ``insert_rotate`` 270) starts at the rect's TOP with its
    # first line at the RIGHT edge; text reading UP (``dir (0,-1)``, run rotation
    # 270, ``insert_rotate`` 90 -- the /Rotate 90 drawing layout) starts at the
    # rect's BOTTOM with its first line at the LEFT edge.  The rect must stay
    # pinned on that start and grow away from it (ROT90-UP-1).
    if is_vertical:
        if new_rect is not None:
            base_y1 = float(base_layout.y1)
            base_y0 = float(base_layout.y0)
            if grows_up:
                insert_rect = fitz.Rect(
                    base_layout.x0, page_rect.y0, base_layout.x1, base_layout.y1
                )
            else:
                insert_rect = fitz.Rect(
                    base_layout.x0, base_layout.y0, base_layout.x1, page_rect.y1
                )
            # The htmlbox needs one line box plus ~2 pt of leading across the
            # lines; a rect exactly as wide as the line (the unmoved bbox) made
            # MuPDF scale the whole run down to fit (~8 %).  Widen it AWAY from
            # the pinned first-line edge, so the text stays where it was.
            _need_w = _line_ht + 2.0
            if _line_ht > 0.0 and insert_rect.width < _need_w:
                if reads_up:
                    insert_rect.x1 = insert_rect.x0 + _need_w
                else:
                    insert_rect.x0 = insert_rect.x1 - _need_w
        else:
            # ``base_layout`` (the run's reopen anchor), never the BLOCK's
            # layout rect: the htmlbox starts the text at this rect's top (or
            # bottom, reading up), and a multi-run block starts at another
            # cell's run (F13-VF-1).
            base_rect = model._vertical_html_rect(
                base_layout, new_text, size, resolve_result.resolved_font,
                page_rect,
                # upward text: first line at the left edge, extra lines grow
                # right, so the left edge is the fixed one whatever the caller
                # asked for (``vertical_shift_left`` cannot move a first line)
                anchor_right=False if reads_up else vertical_shift_left,
            )
            base_y1 = base_rect.y1
            base_y0 = base_rect.y0
            # The box runs to the page edge, or to the next run on the column
            # (F13-VF-4b) -- never shorter than the old text itself.
            if grows_up:
                far_y0 = page_rect.y0
                if vertical_limit is not None:
                    far_y0 = min(max(far_y0, vertical_limit), float(base_rect.y0))
                insert_rect = fitz.Rect(base_rect.x0, far_y0, base_rect.x1, base_rect.y1)
            else:
                far_y1 = page_rect.y1
                if vertical_limit is not None:
                    far_y1 = max(min(far_y1, vertical_limit), float(base_rect.y1))
                insert_rect = fitz.Rect(base_rect.x0, base_rect.y0, base_rect.x1, far_y1)
    else:
        margin = 15
        x0 = max(float(base_layout.x0), page_rect.x0)
        # Slack before the SAFE margin only; a wall that replaced it (text already
        # past the margin, F14-DT-1) is the limit itself.
        if grows_left:
            if abs(left_wall - _left_safe(page_rect, float(size))) > 1e-6:
                margin = 0
        elif right_wall != _right_safe(page_rect, float(size)):
            margin = 0
        if new_rect is not None:
            x1 = min(float(base_layout.x1), page_rect.x1 - 10)
        elif grows_left:
            # Pinned on the right edge (where the text starts), growing toward
            # -x up to the left wall or the neighbour on that side.
            x1 = min(float(base_layout.x1), page_rect.x1)
            max_w = max(0, min(page_rect.width - margin, x1 - left_wall - margin))
            x0 = max(x1 - max(resolve_result.target.layout_rect.width, max_w), left_wall)
            if neighbour_limit is not None:
                # Never narrower than the edited extent itself (it fitted there).
                x0 = max(x0, min(neighbour_limit, float(_edit_extent.x0)))
        else:
            max_w = max(0, min(
                page_rect.width - margin,
                right_wall - x0 - margin
            ))
            x1 = min(x0 + max(resolve_result.target.layout_rect.width, max_w), right_wall)
            if neighbour_limit is not None:
                # Never narrower than the edited extent itself (it fitted there).
                x1 = min(x1, max(neighbour_limit, float(_edit_extent.x1)))
        y0 = max(float(base_layout.y0), page_rect.y0)
        # 不再用 line_count×size×2 + size×2 的過度保守地板，改信任實際
        # 文字框高度，避免單行編輯被誤判為溢出而推擠下方未編輯文字。
        base_y1 = y0 + float(base_layout.height)
        insert_y1 = float(page_rect.y1)
        # The wrap limit (ceiling or floor) is read around the edited runs'
        # own extent and leaves room for lines of their own height.
        _extent = _edit_extent if not _edit_extent.is_empty else fitz.Rect(base_layout)
        _line_box = _line_ht if _line_ht > 0.0 else float(base_layout.height)
        if stacks_up:
            # The first line sits at the box's BOTTOM and the extra lines stack
            # up the page: the box is pinned on the run's bottom edge and runs
            # up to the page top, or to the nearest untouched line above it
            # (``_wrap_ceiling``, the mirror of F14-VF4-WRAP).  Nothing is
            # pushed, so there is no wrap room to make.
            bottom = min(max(float(base_layout.y1), page_rect.y0), float(page_rect.y1))
            top = float(page_rect.y0)
            if new_rect is None:
                _ceiling = _wrap_ceiling(page, _extent, x0, x1)
                if _ceiling is not None:
                    top = max(
                        top,
                        min(_ceiling, bottom - (_line_box + _HTMLBOX_LEADING_OVERHEAD + 0.5)),
                    )
                    if bottom - top < 2.0 * _line_box + _HTMLBOX_LEADING_OVERHEAD:
                        css = css + _NO_WRAP_CSS
                    logger.debug(
                        "wrap ceiling %.1f (next untouched line above the edit) -> box y0 %.1f",
                        _ceiling,
                        top,
                    )
            y0, base_y1, insert_y1 = top, bottom, bottom
        elif new_rect is None:
            # Wrapped lines only get room the push-down can clear: never
            # below the top of the next line of the same paragraph (or of a
            # block that started above the edit), which stays where it is
            # (F14-VF4-WRAP).  Always room for the first line itself.
            _floor = _wrap_floor(
                page, _extent, x0, x1, above_y=float(resolve_result.redact_rect.y1)
            )
            if _floor is not None:
                insert_y1 = min(
                    insert_y1,
                    max(_floor, y0 + _line_box + _HTMLBOX_LEADING_OVERHEAD + 0.5),
                )
                # No room for a second line: the text stays on its line,
                # shrunk (strategy C) or refused.  Without this MuPDF's
                # shrink-to-fit also wraps, stacking half-size lines inside
                # the one line band.
                if insert_y1 - y0 < 2.0 * _line_box + _HTMLBOX_LEADING_OVERHEAD:
                    css = css + _NO_WRAP_CSS
                logger.debug(
                    "wrap floor %.1f (next untouched line below the edit) -> box y1 %.1f",
                    _floor,
                    insert_y1,
                )
        insert_rect = fitz.Rect(x0, y0, x1, insert_y1)

    insert_rect = clamp_rect_to_page(insert_rect, page_rect)

    def _strategy_b_rect(rect: fitz.Rect) -> fitz.Rect:
        """Strategy B: widen ``rect`` to the measured text width (capped at
        the page edge and the right-hand neighbour, F13-VF-4)."""
        font_for_measure = "china-ts" if needs_cjk else resolve_result.resolved_font
        try:
            font_obj = fitz.Font(font_for_measure)
        except Exception:
            font_for_measure = "helv"
            font_obj = fitz.Font(font_for_measure)
        text_width = font_obj.text_length(
            new_text.replace('\n', ''), fontsize=size
        )
        expanded_width = max(
            rect.width, text_width * 1.15 + size
        )
        left, right = float(rect.x0), float(rect.x1)
        if grows_left:
            # Widen toward -x from the pinned right edge (F16-2).
            left = max(right - expanded_width, page_rect.x0 + 10)
            if neighbour_limit is not None:
                left = max(left, min(neighbour_limit, rect.x0))
        else:
            right = min(left + expanded_width, page_rect.x1 - 10)
            if neighbour_limit is not None:
                right = min(right, max(neighbour_limit, rect.x1))
        return clamp_rect_to_page(fitz.Rect(left, rect.y0, right, rect.y1), page_rect)

    skip_prepush = resolve_result.effective_target_mode == "paragraph" and new_rect is not None
    # An upside-down run grows UP the page: the push-down moves text downward,
    # so there is nothing for it to clear (F16-2).
    if not is_vertical and not skip_prepush and not stacks_up:
        try:
            _probe_doc = fitz.open()
            _probe_page = _probe_doc.new_page(
                width=page_rect.width, height=page_rect.height
            )
            # The probe runs the same A -> B -> C chain as the insert below:
            # a box the text does not fit at full size returns spare -1,
            # which used to read as "fills the box to the page foot" and
            # pushed the next block off the page, where the push-down skips
            # it and the shrunk text was drawn over it (F14-VF4-WRAP).
            def _probe(rect: fitz.Rect, scale_low: float) -> float:
                return insert_htmlbox_tracked(
                    _probe_page, rect, html_content, css=css,
                    rotate=0, scale_low=scale_low, scratch=True,
                )[0]

            _probe_rect = fitz.Rect(insert_rect)
            _probe_spare = _probe(_probe_rect, 1)
            if _probe_spare < 0:
                _probe_rect = _strategy_b_rect(insert_rect)
                _probe_spare = _probe(_probe_rect, 1)
            if _probe_spare < 0:
                _probe_spare = _probe(_probe_rect, 0.5)
            _probe_doc.close()
            # insert_htmlbox 固定多吃約 2pt leading；扣除後 probe 才能
            # 反映真實文字高度，否則單行編輯會被誤判為溢出觸發 push-down。
            _probe_used_h = max(
                0.0, _probe_rect.height - _probe_spare - _HTMLBOX_LEADING_OVERHEAD
            )
            _probe_y1 = _probe_rect.y0 + _probe_used_h
            _probe_y1 = float(min(max(_probe_y1, base_y1), page_rect.y1))
            height_growth = _probe_y1 - resolve_result.redact_rect.y1
            meaningful_growth = max(0.5, float(size) * 0.2)
            if _probe_spare < 0:
                # Does not fit even at 50 %: the insert below refuses and
                # rolls back; moving other text first would be wasted.
                logger.debug("Pre-push skipped: the text does not fit even at 50 %%")
            elif height_growth > meaningful_growth:
                logger.debug(
                    "換行預估溢出 %.1fpt，預先推移下方文字塊（pre-push）",
                    height_growth,
                )
                model._push_down_overlapping_text(
                    page, page_rect,
                    above_y=resolve_result.redact_rect.y1,
                    new_bottom=_probe_y1,
                    edit_x0=x0,
                    edit_x1=x1,
                )
            else:
                logger.debug(
                    "Pre-push probe skipped: growth %.2fpt <= threshold %.2fpt",
                    height_growth,
                    meaningful_growth,
                )
        except TextEditRefused:
            # The push-down already rewrote the page: never continue the
            # edit over it; ``edit_text`` rolls the page back (F13-VF-2).
            raise
        except Exception as _probe_err:
            logger.debug("Pre-push probe 失敗（忽略）: %s", _probe_err)
    elif skip_prepush:
        logger.debug("Pre-push probe skipped (paragraph mode with dragged new_rect)")

    if is_vertical:
        try:
            _shrink_doc = fitz.open()
            _shrink_page = _shrink_doc.new_page(
                width=page_rect.width, height=page_rect.height
            )
            insert_htmlbox_tracked(
                _shrink_page,
                insert_rect, html_content, css=css,
                rotate=resolve_result.insert_rotate, scale_low=1, scratch=True,
            )
            padding = model._calc_vertical_padding(size)
            shrunk_rect = model._binary_shrink_height(
                _shrink_page, insert_rect, new_text,
                iterations=7, padding=padding, min_y1=base_y1,
                grow_up=grows_up, max_y0=base_y0 if grows_up else None,
                far_limit=(
                    float(insert_rect.y0 if grows_up else insert_rect.y1)
                    if vertical_limit is not None
                    else None
                ),
            )
            _shrink_doc.close()
        except Exception as _shrink_err:
            logger.debug("垂直 binary_shrink 失敗，回退 insert_rect: %s", _shrink_err)
            shrunk_rect = fitz.Rect(insert_rect)
        shrunk_rect = clamp_rect_to_page(shrunk_rect, page_rect)
        _vertical_before = _page_glyphs(page) if _guard_overprint else None
        spare_height, scale_used = _insert_edited_text(shrunk_rect, 1)
        if spare_height < 0 and vertical_limit is not None:
            # Walled by the next run: shrink to at most half size, like the
            # horizontal strategy C, or refuse -- never a speck (F13-VF-4b).
            spare_height, scale_used = _insert_edited_text(shrunk_rect, 0.5)
            if spare_height < 0:
                raise _roll_back_and_refuse(
                    model, page_idx, snapshot_bytes, maintenance_book,
                    TextEditRefusal.TEXT_DOES_NOT_FIT,
                    f"the edited text does not fit at {size}pt (or half of it) before "
                    "the next run on its column; rolled back.",
                )
        elif spare_height < 0:
            _insert_edited_text(shrunk_rect, 0)
        _refuse_if_overprinted(_vertical_before)
        new_layout_rect = fitz.Rect(shrunk_rect)
        logger.debug(
            "垂直策略（臨時頁量測）: spare_height=%s, shrunk_rect=%s",
            spare_height,
            shrunk_rect,
        )
        return new_layout_rect

    _htmlbox_before = _page_glyphs(page) if _guard_overprint else None
    spare_height, scale_used = _insert_edited_text(insert_rect, 1)
    new_layout_rect = fitz.Rect(insert_rect)
    logger.debug("策略 A: spare_height=%s, scale=%s", spare_height, scale_used)

    if spare_height < 0:
        logger.debug("策略 A 失敗，嘗試策略 B（自動擴寬）")
        try:
            expanded_rect = _strategy_b_rect(insert_rect)
            spare_height, scale_used = _insert_edited_text(expanded_rect, 1)
            new_layout_rect = fitz.Rect(expanded_rect)
            logger.debug(
                "策略 B: spare_height=%s, scale=%s",
                spare_height,
                scale_used,
            )
        except Exception as ex_b:
            logger.debug("策略 B 失敗: %s", ex_b)

    if spare_height < 0:
        spare_height, scale_used = _insert_edited_text(new_layout_rect, 0.5)
        if spare_height < 0:
            raise _roll_back_and_refuse(
                model, page_idx, snapshot_bytes, maintenance_book,
                TextEditRefusal.TEXT_DOES_NOT_FIT,
                f"文字框內容在字級 {size}pt 下無法完整塞入 "
                f"(spare_height={spare_height})，"
                "策略 A/B/C 均失敗，已回滾。",
            )
        logger.debug(
            "策略 C（水平, scale_low=0.5）: spare_height=%s, scale=%s",
            spare_height,
            scale_used,
        )
    _refuse_if_overprinted(_htmlbox_before)

    text_used_height = new_layout_rect.height - spare_height
    if stacks_up:
        # Pinned at the bottom: the used height is measured up from there.
        computed_y0 = min(
            new_layout_rect.y1 - text_used_height,
            new_layout_rect.y1 - float(base_layout.height),
        )
        shrunk_rect = fitz.Rect(
            new_layout_rect.x0, max(computed_y0, new_layout_rect.y0),
            new_layout_rect.x1, new_layout_rect.y1,
        )
    else:
        computed_y1 = new_layout_rect.y0 + text_used_height
        computed_y1 = max(computed_y1, base_y1)
        shrunk_rect = fitz.Rect(
            new_layout_rect.x0, new_layout_rect.y0,
            new_layout_rect.x1, computed_y1
        )
    shrunk_rect = clamp_rect_to_page(shrunk_rect, page_rect)
    if resolve_result.reopen_anchor_rect is not None:
        # Pin the committed layout back to the anchor so the box geometry
        # is identical to the previous open — no per-commit shrink.
        return clamp_rect_to_page(fitz.Rect(resolve_result.reopen_anchor_rect), page_rect)
    return fitz.Rect(shrunk_rect)


def _verify_rebuild_edit(
    model: PDFModel,
    *,
    page: fitz.Page,
    page_num: int,
    page_idx: int,
    page_rect: fitz.Rect,
    new_text: str,
    size: float,
    color: tuple,
    snapshot_bytes: bytes,
    resolve_result: _EditTextResolveResult,
    new_layout_rect: fitz.Rect,
    maintenance_book: MaintenanceBook | None = None,
    acknowledged_glyph_loss: tuple[UnkeepableGlyph, ...] = (),
) -> None:
    full_page_text = page.get_text("text")
    # Every requested character must actually be on the page, or the rebuild
    # is refused -- never SUCCESS with lost text (F10-UNI-1).  The fuzzy gates
    # below tolerate extraction drift, so on their own they also accepted a
    # line whose new characters were all written as U+00B7.
    #
    # One accepted exception (owner decision OD-UNI1-COMMIT): characters
    # htmlbox DRAWS correctly but writes a wrong ToUnicode for (emoji and
    # other non-BMP code points, Indic conjuncts, Arabic lam-alef, ...).
    # Those commit on glyph evidence, and the presence gates compare the page
    # with the text layer htmlbox writes for this exact markup (a scratch
    # reference render) instead of the requested text.
    #
    # A second one (F11-UNI-1, owner decision C): untouched glyphs with no
    # Unicode identity the user was told the rebuild cannot keep and
    # acknowledged (``acknowledged_glyph_loss``); htmlbox draws a replacement
    # glyph or nothing for them, so the same reference-render comparison
    # applies.  Unacknowledged or typed placeholders still roll back.
    own_acknowledged = [g for g in acknowledged_glyph_loss if g.span_id is None]
    # F16-PASTE-2: a placeholder nobody acknowledged is refused HERE, not only
    # through the lossy-layer comparison below -- that comparison is skipped
    # when the text layer carries every requested character, and htmlbox's
    # does for U+FFFC (it draws a dashed "OBJ" box and reads it back as itself).
    acknowledged_labels = {g.codepoint for g in own_acknowledged}
    unacknowledged = sorted(
        {_codepoint_label(ch) for ch in new_text or "" if _is_unkeepable_glyph(ch)}
        - acknowledged_labels
    )
    if unacknowledged:
        logger.warning(
            "rebuild verification: unacknowledged placeholder(s) in the requested text page=%s: %s",
            page_num,
            unacknowledged,
        )
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED,
            "overlap edit verification failed: the requested text holds characters that "
            f"cannot be reproduced and were not acknowledged: {', '.join(unacknowledged)}",
        )
    presence_text = new_text
    lost_chars = _lost_requested_chars(new_text, full_page_text)
    if lost_chars:
        markup = _rebuild_insert_markup(
            model,
            page_num=page_num,
            new_text=new_text,
            size=size,
            color=color,
            resolve_result=resolve_result,
        )
        glyph_area = page_rect if new_layout_rect.is_empty else new_layout_rect
        reference = _htmlbox_reference(markup.html, markup.css, glyph_area.width)
        page_glyphs, _notdef = _texttrace_glyphs(
            page, _glyph_evidence_rect(glyph_area, size, page_rect)
        )
        problem = _lossy_text_layer_problem(
            new_text, full_page_text, reference, page_glyphs, own_acknowledged
        )
        if problem is not None:
            logger.warning(
                "rebuild verification: requested characters missing after insert page=%s lost=%s: %s",
                page_num,
                lost_chars,
                problem,
            )
            raise _roll_back_and_refuse(
                model, page_idx, snapshot_bytes, maintenance_book,
                problem.reason, f"overlap edit verification failed: {problem}"
            )
        logger.warning(
            "rebuild committed with a lossy htmlbox text layer page=%s chars=%s: "
            "copy/search returns other characters (OD-UNI1-COMMIT); acknowledged "
            "unkeepable glyphs drawn as another glyph or not at all (F11-UNI-1)=%s",
            page_num,
            lost_chars,
            [(g.index, g.codepoint, g.fate) for g in own_acknowledged],
        )
        presence_text = reference.text
    # NFKC-folded on both sides: htmlbox extracts shaped Arabic as
    # presentation forms, which would otherwise never match (F10-UNI-1).
    norm_new = _presence_norm(presence_text)
    norm_page = _presence_norm(full_page_text)
    nfkc_new = unicodedata.normalize("NFKC", presence_text or "")

    if norm_new and norm_new in norm_page:
        sim_ratio = 1.0
    elif norm_new and norm_page:
        sim_ratio = difflib.SequenceMatcher(
            None, norm_new, norm_page
        ).ratio()
    else:
        sim_ratio = 1.0 if not norm_new else 0.0

    logger.debug(
        "Step4 驗證: ratio=%.2f, layout_rect=%s, norm_new[:%s]=%r",
        sim_ratio,
        new_layout_rect,
        min(40, len(norm_new)),
        norm_new[:40],
    )

    norm_clip = ""
    clip_ratio = 0.0
    clip_token_coverage = 0.0
    if not new_layout_rect.is_empty:
        try:
            clipped = page.get_text("text", clip=clamp_rect_to_page(new_layout_rect, page_rect))
            norm_clip = _presence_norm(clipped)
            if norm_new and norm_clip:
                if norm_new in norm_clip:
                    clip_ratio = 1.0
                else:
                    clip_ratio = difflib.SequenceMatcher(None, norm_new, norm_clip).ratio()
                clip_token_coverage = token_coverage_ratio(nfkc_new, norm_clip)
        except Exception as e_clip:
            logger.debug("Step4 clip probe failed: %s", e_clip)

    page_token_coverage = token_coverage_ratio(nfkc_new, norm_page)
    exact_present = (norm_new in norm_page) or (bool(norm_clip) and norm_new in norm_clip)
    has_complex_script = model._has_complex_script(new_text)
    if not norm_new or exact_present:
        target_present = True
    elif resolve_result.effective_target_mode == "paragraph":
        if has_complex_script:
            target_present = (
                sim_ratio >= 0.40
                or clip_ratio >= 0.38
                or page_token_coverage >= 0.35
                or clip_token_coverage >= 0.35
            )
        else:
            target_present = (
                sim_ratio >= 0.88
                or clip_ratio >= 0.84
                or page_token_coverage >= 0.78
                or clip_token_coverage >= 0.72
            )
    elif len(norm_new) >= 48:
        target_present = (
            sim_ratio >= 0.90
            or clip_ratio >= 0.86
            or page_token_coverage >= 0.85
        )
    else:
        target_present = False

    logger.debug(
        "target_presence page=%s mode=%s exact=%s sim_ratio=%.2f clip_ratio=%.2f token_page=%.2f token_clip=%.2f",
        page_num,
        resolve_result.effective_target_mode,
        exact_present,
        sim_ratio,
        clip_ratio,
        page_token_coverage,
        clip_token_coverage,
    )
    protected_ok = model._validate_protected_spans(
        page, resolve_result.protected_spans, acknowledged_glyph_loss
    )
    if not target_present or not protected_ok:
        if not target_present:
            refusal = TextEditRefusal.TARGET_NOT_PRESENT
        elif _protected_glyphs_unacknowledged(
            resolve_result.protected_spans, acknowledged_glyph_loss
        ):
            refusal = TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED
        else:
            refusal = TextEditRefusal.PROTECTED_SPAN_CHANGED
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            refusal,
            "overlap edit verification failed: "
            f"target_present={target_present}, protected_ok={protected_ok}",
        )

    strict_ratio = max(sim_ratio, clip_ratio)
    if resolve_result.effective_target_mode != "paragraph" and strict_ratio < 0.80 and not resolve_result.is_vertical:
        logger.warning(
            "插入後驗證失敗 (ratio=%.2f)，正在回滾頁面 %s",
            strict_ratio,
            page_num,
        )
        raise _roll_back_and_refuse(
            model, page_idx, snapshot_bytes, maintenance_book,
            TextEditRefusal.VERIFICATION_FAILED,
            f"文字編輯驗證失敗：difflib.ratio="
            f"{strict_ratio:.2f} < 0.80，已回滾。",
        )

    update_kwargs = dict(
        text=new_text,
        font=resolve_result.resolved_font,
        size=float(size),
        color=color,
    )
    if not resolve_result.is_vertical:
        update_kwargs["layout_rect"] = new_layout_rect
    model.block_manager.update_block(resolve_result.target, **update_kwargs)
    model.block_manager.rebuild_page(page_idx, model.doc)
    _record_joined_edit_run(
        model, page_idx, new_text, resolve_result, fitz.Rect(new_layout_rect)
    )
    if resolve_result.reopen_anchor_rect is not None:
        # rebuild_page reassigns span_ids; migrate the anchor onto the
        # rebuilt run that best matches by (text-match, distance-to-anchor
        # -center) so the next reopen still resolves to it, and drop the
        # stale key so the anchor dict can't grow unboundedly.
        anchor_rect = fitz.Rect(resolve_result.reopen_anchor_rect)
        # A grouped show's anchor lives under its group key (UI step 3).
        anchor_key = (
            getattr(resolve_result, "reopen_anchor_key", None)
            or resolve_result.resolved_target_span_id
        )
        anchor_size = model._get_run_reopen_anchor_size(page_idx, anchor_key)
        if anchor_size is None:
            anchor_size = float(size)
        model._set_run_reopen_anchor_rect(page_idx, anchor_key, anchor_rect)
        model._set_run_reopen_anchor_size(page_idx, anchor_key, anchor_size)
        try:
            rebuilt_runs = model.block_manager.get_runs(page_idx)
            old_group = getattr(resolve_result, "source_group", None)
            multi_show = old_group is not None and len(old_group.member_span_ids) > 1
            best_run = (
                _choose_anchor_run(
                    rebuilt_runs,
                    anchor_rect,
                    fitz.Rect(anchor_rect) | fitz.Rect(new_layout_rect),
                    normalize_text(new_text or ""),
                    multi_show=multi_show,
                )
                if rebuilt_runs
                else None
            )
            new_key: str | None = best_run.span_id if best_run is not None else None
            if best_run is not None and multi_show:
                # A grouped show's anchor spans the WHOLE old show. It
                # may only move onto a group the rewritten text proves
                # again; when the rebuild re-inserted the text as several
                # shows (the htmlbox path), planting that union on one
                # word would reopen that word over its neighbours --
                # drop the anchor instead.
                regroup = _rederive_source_group(model, page_idx, best_run.span_id)
                new_key = regroup.anchor_key if regroup is not None else None
            if new_key != anchor_key:
                model._delete_run_reopen_anchor(page_idx, anchor_key)
            if new_key is not None:
                model._set_run_reopen_anchor_rect(page_idx, new_key, anchor_rect)
                model._set_run_reopen_anchor_size(page_idx, new_key, anchor_size)
        except Exception as anchor_exc:
            logger.debug("run anchor refresh skipped after rebuild: %s", anchor_exc)
    logger.debug(
        "編輯文字成功: 頁面 %s, block_id=%s, text='%s...'",
        page_num,
        resolve_result.target.block_id,
        new_text[:30],
    )

# ──────────────────────────────────────────────────────────────────────────
# Phase 3: 五步流程 + 三策略 edit_text
# ──────────────────────────────────────────────────────────────────────────


def _resolve_effective_target_mode(
    model: PDFModel,
    *,
    target_mode: str | None,
    target_span_id: str | None,
    new_rect: fitz.Rect | None,
    page_idx: int,
    rect: fitz.Rect,
    original_text: str | None,
) -> str:
    """Determine effective target mode from caller hints and heuristics."""
    if target_mode is None:
        if new_rect is not None and not target_span_id:
            effective = "paragraph"
        elif target_span_id:
            effective = "run"
        else:
            effective = "paragraph"
    else:
        effective = (target_mode or model.text_target_mode or "run").strip().lower()
    if effective not in {"run", "paragraph"}:
        effective = "run"
    if effective == "run" and not target_span_id:
        should_promote = True
        if original_text:
            probe_block = model.block_manager.find_by_rect(
                page_idx, rect, original_text=original_text, doc=model.doc
            )
            if probe_block and probe_block.text:
                norm_orig = normalize_text(original_text)
                norm_block = normalize_text(probe_block.text)
                if norm_block and len(norm_orig) < len(norm_block) * 0.6:
                    should_promote = False
                    logger.debug(
                        "keeping run mode: original_text (%d chars) < 60%% of block text (%d chars)",
                        len(norm_orig), len(norm_block),
                    )
        if should_promote:
            effective = "paragraph"
            logger.warning("auto-promoted target_mode run->paragraph (no explicit span_id)")
    return effective


class _Tier0Target(NamedTuple):
    """The Tier 0 target triple plus how its ``text`` was arrived at.

    ``text``/``origin``/``bbox`` keep index positions 0-2 so existing tuple
    consumers are unaffected; ``joined_runs`` is what lets a caller tell a
    quotation from a reconstruction. ``source_kind`` distinguishes a
    verbatim ``page.get_text("dict")`` line quote (``"dict_line"``) from
    today's stripped-run join (``"run_join"``); it defaults so every
    existing 4-arg positional construction still compiles.
    """

    text: str
    origin: tuple[float, float]
    bbox: tuple[float, float, float, float]
    joined_runs: int
    source_kind: str = "run_join"  # "run_join" | "dict_line" | "source_show"

    @property
    def whitespace_reconstructed(self) -> bool:
        """``text`` may not be a byte-exact quotation of the content stream.

        For a ``run_join`` target, ``text_block_parsing._finalize`` strips
        each word run, so joining two or more of them with single spaces
        reproduces the source only when every gap in it was exactly one
        space. Wherever it was not — multiple spaces, a tab, a kern-derived
        gap — the join silently differs from the stream bytes that
        ``bind_source_text`` demands.

        For a ``dict_line`` target the text is a quotation of the
        *extractor*, not of the stream: MuPDF materialises a TJ kern
        advance as a real space character that the content stream never
        contained (probe: ``[(Price is) -500 (100)] TJ`` extracts as
        ``'Price is 100'`` while the stream decodes to ``b'Price is100'``).
        So whitespace in a dict quote still means "our target string may be
        the thing that is wrong" — exactly what the relabel claims.
        """
        if self.source_kind == "source_show":
            # The DECODED show operand itself (UI step 3): a quotation of
            # the content stream, never a reconstruction.
            return False
        if self.source_kind == "dict_line":
            return any(ch.isspace() for ch in self.text)
        return self.joined_runs > 1

    def replacement_for(self, edited: str) -> str:
        """The string the ENGINE must write for a user edit of ``edited``.

        ``run_join`` targets are untouched (today's behaviour): the editor
        already showed the run-joined text verbatim, so nothing needs
        re-projecting. ``dict_line`` targets require re-projection because
        the inline editor is populated from the stripped/collapsed run text
        (``TextHit.target_text``) and the view's change detector further
        normalizes with ``" ".join(text.split())`` — so ``edited`` may carry
        different whitespace than ``self.text`` even when the user changed
        nothing but token content.
        """
        if self.source_kind != "dict_line":
            return edited
        if not edited.strip():
            # Let plan.py's EMPTY_REPLACEMENT gate refuse a real deletion;
            # returning ``lead + trail`` here would be non-empty and slip
            # past that gate with a whitespace-only operand.
            return edited
        lead, tokens, gaps, trail = _whitespace_frame(self.text)
        if not tokens:
            return edited
        e_tokens = edited.split()
        if len(e_tokens) == len(tokens) and edited == " ".join(e_tokens):
            # Level A: the edit is in the collapsed canonical form the
            # inline editor showed. The user changed token CONTENT only, so
            # the source's own gaps and outer padding are restored.
            out = [lead]
            for i, tok in enumerate(e_tokens):
                if i:
                    out.append(gaps[i - 1])
                out.append(tok)
            out.append(trail)
            return "".join(out)
        # Level B: the user restructured the text (different token count,
        # or typed their own multi-space run). Honour it verbatim, but keep
        # the line's outer padding, which the editor never showed them.
        return f"{lead}{edited}{trail}"


_WS_RUN_RE = re.compile(r"\s+")
_LEAD_WS_RE = re.compile(r"^\s*")
_TRAIL_WS_RE = re.compile(r"\s*$")


def _whitespace_frame(text: str) -> tuple[str, list[str], list[str], str]:
    """Split ``text`` into ``(lead, tokens, gaps, trail)``.

    ``len(gaps) == len(tokens) - 1``. Pure string manipulation; used only by
    :meth:`_Tier0Target.replacement_for`.
    """
    lead_match = _LEAD_WS_RE.match(text)
    lead = lead_match.group(0) if lead_match else ""
    trail_match = _TRAIL_WS_RE.search(text)
    trail = trail_match.group(0) if trail_match else ""
    core = text[len(lead): len(text) - len(trail)] if trail else text[len(lead):]
    if not core:
        return lead, [], [], trail
    tokens = _WS_RUN_RE.split(core)
    gaps = _WS_RUN_RE.findall(core)
    return lead, tokens, gaps, trail


def _reconstruction_aware_reason(reason: str, target: _Tier0Target) -> str:
    """Re-label a ``NO_MATCH`` whose target this stage may itself have broken.

    ``NO_MATCH`` claims the document does not contain the text.  That claim
    is only honest when the text is a quotation of the document; when it is
    a run-join (or an extractor-synthesized dict quote) it may be the
    reconstruction that is wrong, and conflating the two hid this whole
    failure class from every corpus number (the audits classify shows, not
    edits).
    """
    if reason == RejectReason.NO_MATCH and target.whitespace_reconstructed:
        return RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED
    return reason


def _reconstruction_detail(target: _Tier0Target) -> str:
    if target.source_kind == "dict_line":
        return (
            "target text is the extractor's verbatim line quote; a "
            "whitespace character in it may have been synthesised from a "
            "kern advance rather than present in the content stream, so no "
            "show operator matched"
        )
    return (
        f"target text was reconstructed by joining {target.joined_runs} word "
        "runs with single spaces; run parsing strips whitespace, so a source "
        "gap that is not exactly one space cannot be reproduced and no show "
        "operator matched"
    )


def _dict_space_to_visual(
    page: fitz.Page,
    origin: fitz.Point,
    bbox: fitz.Rect,
) -> tuple[fitz.Point, fitz.Rect] | None:
    """Map ``page.get_text('dict')``-derived geometry into VISUAL page space.

    PyMuPDF keeps ``get_text('dict'/'rawdict')`` extraction geometry in
    *unrotated* page space on ``/Rotate`` pages (top-level ``width``/
    ``height`` stay the mediabox dims, not ``page.rect``'s rotated dims;
    same quirk documented for annot geometry in ``docs/PITFALLS.md`` and
    fixed there via ``AnnotationTool._rotate_rect_to_displayed``). The
    downstream consumer -- ``model.text_commit.verify`` -- compares
    ``target_bbox_page`` pixel-for-pixel against ``page.get_pixmap()``
    output, which IS visual space, so the block index's dict-space
    ``origin``/``bbox`` must be converted here, at the model boundary,
    before either value leaves this module. The ``/Rotate`` term ALONE
    (not the full user-space→visual chain) is the correct conversion: the
    cropbox flip and ``/UserUnit`` are already baked into dict-space
    coordinates -- MEASURED, dict space IS the visual frame's BASE space --
    so only the rotation is missing. That term comes from
    ``transforms.page_visual_frame``, never from ``page.rotation_matrix``,
    which drops ``/UserUnit`` and sizes itself from the UNCLIPPED CropBox.
    At rotation 0 the term is identity, so this is a no-op.

    ``None`` when the page's frame cannot be proven (review "sol" F2): the
    caller's documented failure path is "no Tier 0 target", so an
    unprovable page loses the high-fidelity tier and falls back to the
    legacy edit path -- it never raises into the edit session.
    """
    try:
        quarter_turn = page_visual_frame(page).quarter_turn
    except UnsupportedPageGeometryError:
        logger.debug("no Tier 0 target: page visual frame is not provable")
        return None
    origin_visual = fitz.Point(origin) * quarter_turn
    bbox_visual = (fitz.Rect(bbox) * quarter_turn).normalize()
    return origin_visual, bbox_visual


_WS_ALIGN_TOL_PT = 0.5  # baseline / origin-x agreement
_WS_BBOX_TOL_PT = 1.0  # run-union containment slack


def _dict_line_for_runs(
    page: fitz.Page,
    ordered_runs: list[EditableSpan],
    *,
    dict_blocks: list[dict] | None = None,
) -> tuple[str, fitz.Point, fitz.Rect] | None:
    """VERBATIM ``(text, origin, bbox)`` of the dict line ``ordered_runs`` came from.

    Returns ``None`` when the correspondence cannot be PROVEN. The caller's
    ``(block_idx, line_idx)`` pair is only a *candidate* -- it is re-proven
    here against the live page via a content proof (A1/A2) and four
    geometry gates (G1-G4); the first failure refuses. All geometry
    returned is still unrotated dict space -- the caller converts.
    """
    if not ordered_runs:
        return None
    first = ordered_runs[0]
    if any(
        r.block_idx != first.block_idx or r.line_idx != first.line_idx
        for r in ordered_runs
    ):
        return None  # caller invariant (P1)

    blocks = (
        dict_blocks
        if dict_blocks is not None
        else content_text(page, "dict", flags=0).get("blocks", [])
    )
    if not (0 <= first.block_idx < len(blocks)):
        return None  # P3: index may be stale/shifted
    block = blocks[first.block_idx]
    if block.get("type") != 0:
        return None  # P3

    lines = block.get("lines") or []
    if not (0 <= first.line_idx < len(lines)):
        return None  # P4: index may be stale/shifted
    line = lines[first.line_idx]

    spans = line.get("spans") or []
    if not spans:
        return None  # P5
    # P5: dict spans concatenate with NO separator (probe-verified).
    dict_text = "".join(sp.get("text", "") for sp in spans)
    if dict_text == "":
        return None

    dir_vec = line.get("dir") or (1.0, 0.0)
    if abs(float(dir_vec[0]) - 1.0) >= 1e-6 or abs(float(dir_vec[1])) >= 1e-6:
        return None  # P6: vertical/180 deg text fails closed

    run_texts = [r.text for r in ordered_runs]
    # A1: run-parser shape -- runs split only at whitespace, so the dict
    # line's whitespace-delimited tokens equal the run texts exactly.
    a1 = dict_text.split() == run_texts
    # A2: _parse_spans fallback shape -- "runs" are verbatim dict spans that
    # concatenate with no separator.
    a2 = "".join(run_texts) == dict_text
    if not (a1 or a2):
        return None

    span0_origin = spans[0].get("origin")
    if not span0_origin:
        return None
    # G1: same baseline.
    if abs(float(span0_origin[1]) - float(first.origin.y)) > _WS_ALIGN_TOL_PT:
        return None
    # G2: dict origin is at or before the first glyph (equal with no
    # padding, smaller with leading padding).
    if float(span0_origin[0]) > float(first.origin.x) + _WS_ALIGN_TOL_PT:
        return None
    line_bbox_raw = line.get("bbox")
    if not line_bbox_raw:
        return None
    line_bbox = fitz.Rect(line_bbox_raw)
    # G3: the runs are physically inside this line.
    run_union = rect_union([fitz.Rect(r.bbox) for r in ordered_runs])
    tolerant_line_bbox = fitz.Rect(
        line_bbox.x0 - _WS_BBOX_TOL_PT,
        line_bbox.y0 - _WS_BBOX_TOL_PT,
        line_bbox.x1 + _WS_BBOX_TOL_PT,
        line_bbox.y1 + _WS_BBOX_TOL_PT,
    )
    if not tolerant_line_bbox.contains(run_union):
        return None
    # G4: independent orientation check.
    if rotation_degrees_from_dir(dir_vec) != first.rotation:
        return None

    return (
        dict_text,
        fitz.Point(float(span0_origin[0]), float(span0_origin[1])),
        line_bbox,
    )


def _tier0_target_from_resolve(
    model: PDFModel,
    page_idx: int,
    resolve_result: _EditTextResolveResult,
    *,
    dict_blocks: list[dict] | None = None,
) -> _Tier0Target | None:
    """Derive the Tier 0 (text, origin, bbox) target from the edit's members.

    The block manager splits lines into word-level runs, so one show op
    usually maps to several member spans.  Supported shapes: exactly one
    member run (a whole-word Tj), or a member set covering one full line
    (its space-joined text is the show-op string).  Anything else — partial
    line selections, multi-line paragraphs — is not a whole-operator patch
    and returns None.

    When the member set covers every run of the line, this re-parses
    ``page.get_text("dict")`` and recovers the VERBATIM source line (see
    :func:`_dict_line_for_runs`) whenever a runtime content-and-geometry
    proof binds it to these exact runs; otherwise the returned ``text`` is
    a *candidate*: for a multi-run target it is a reconstruction, not a
    quotation (see :attr:`_Tier0Target.whitespace_reconstructed`).
    """
    members = _member_spans(resolve_result)
    if not members:
        return None
    if any(contains_rtl(span.text) for span in members):
        # F15-RTL-ORDER: the index holds right-to-left text in LOGICAL order, a
        # stream operand may be drawn in either order, so Tier 0's byte match
        # cannot prove the typed letters land in the right order (a palindrome
        # matches both ways).  Right-to-left goes to the legacy rebuild.
        return None
    source_group = getattr(resolve_result, "source_group", None)
    if source_group is not None:
        # UI step 3: a proven source show beats every reconstruction
        # (``run_join``) and the extractor's ``dict_line`` quote -- and never
        # reads ``page.get_text('dict')``.
        return _tier0_target_from_source_group(
            model, page_idx, source_group, members
        )
    if (
        len(members) > 1
        and getattr(resolve_result, "effective_target_mode", None) == "paragraph"
        and len({s.font for s in members}) > 1
    ):
        # R8-1: a show operator selects ONE font, so paragraph runs in two
        # fonts are at least two shows and no single-show bind can ever carry
        # the joined text.  Refusing here makes the commit side say
        # ``multi_span_target`` (and the preview ``target_unresolved``, which
        # the paragraph-mode view remaps to the same) instead of a binder
        # ``no_source_match`` that reads as a glyph problem.  Scoped to
        # paragraph mode on purpose: the view's remap is paragraph-only, and a
        # run-mode joined box (S17) or the tier-funnel census keep HEAD's
        # outcome.  Same-font multi-run lines are unchanged.
        return None
    first = members[0]
    if any(
        s.page_idx != first.page_idx
        or s.block_idx != first.block_idx
        or s.line_idx != first.line_idx
        for s in members
    ):
        # Subsumed today by the full-line set-equality check below (span_id
        # encodes page/block/line in both parsers), so mutation testing marks
        # it insensitive. Kept deliberately as defence-in-depth (decision
        # 2026-08-04): its protection must not hinge on the span_id format
        # staying identical across two parsers. Do not fabricate a fixture
        # to make it look sensitive.
        return None  # spans multiple lines: paragraph re-layout (Tier 1+)
    line_runs = [
        run
        for run in model.block_manager.get_runs(page_idx)
        if run.block_idx == first.block_idx and run.line_idx == first.line_idx
    ]
    if len(members) > 1 and {r.span_id for r in line_runs} != {
        m.span_id for m in members
    }:
        return None  # partial line selection: substring patch unsupported
    covers_line = {r.span_id for r in line_runs} == {m.span_id for m in members}
    ordered = sorted(members, key=lambda s: float(s.origin.x))
    run_text = " ".join((s.text or "") for s in ordered)
    if model.doc is None:
        return None
    page = model.doc[page_idx]
    run_bbox = rect_union([fitz.Rect(s.bbox) for s in ordered])

    recovered = (
        _dict_line_for_runs(page, ordered, dict_blocks=dict_blocks)
        if covers_line
        else None
    )
    # A single member run that is not the whole line (today's common
    # per-word Tj edit) must keep its own run text: substituting the whole
    # dict line there would bind the whole-line operator and rewrite text
    # the user never selected -- the wrong-text catastrophe recovery must
    # never risk.
    if recovered is not None:
        text, origin_dict, bbox_dict = recovered
        source_kind = "dict_line"
    else:
        text, origin_dict, bbox_dict = run_text, ordered[0].origin, run_bbox
        source_kind = "run_join"

    converted = _dict_space_to_visual(page, origin_dict, bbox_dict)
    if converted is None:
        return None  # page geometry not provable: no high-fidelity target
    origin_visual, bbox_visual = converted
    return _Tier0Target(
        text,
        (float(origin_visual.x), float(origin_visual.y)),
        (
            float(bbox_visual.x0),
            float(bbox_visual.y0),
            float(bbox_visual.x1),
            float(bbox_visual.y1),
        ),
        len(ordered),
        source_kind,
    )


def _tier0_target_from_source_group(
    model: PDFModel,
    page_idx: int,
    group: SourceRunGroup,
    members: list[EditableSpan],
) -> _Tier0Target | None:
    """The Tier 0 target of a commit-side re-derived source show.

    ``text`` is the decoded show operand verbatim (parser order, spaces as
    in the stream -- never an ``origin.x``-sorted, space-joined run join);
    ``origin`` is the show's own replay origin in visual space (the binding
    origin, ``SourceShowRef.origin``); ``bbox`` is the members' union.
    """
    if {m.span_id for m in members} != set(group.member_span_ids):
        return None  # the cluster lost a member: not provably the show
    if model.doc is None:
        return None
    page = model.doc[page_idx]
    converted = _dict_space_to_visual(page, fitz.Point(group.origin), group.rect())
    if converted is None:
        return None
    _origin_visual, bbox_visual = converted
    origin = group.source_ref.origin
    return _Tier0Target(
        group.text,
        (float(origin[0]), float(origin[1])),
        (
            float(bbox_visual.x0),
            float(bbox_visual.y0),
            float(bbox_visual.x1),
            float(bbox_visual.y1),
        ),
        len(group.member_span_ids),
        "source_show",
    )


def derive_tier0_preview_target(
    model: PDFModel,
    *,
    page_num: int,
    rect: fitz.Rect,
    original_text: str | None,
    target_span_id: str | None,
    target_mode: str | None,
    source_ref: SourceShowRef | None = None,
) -> _Tier0Target | None:
    """Resolve the Tier 0 (text, origin, bbox) once per preview session.

    Mirrors ``edit_text``'s resolve sequence read-only: the target is fixed
    when the inline editor opens, so the plan-backed preview derives it one
    time and only the replacement text varies per keystroke.  The same
    ``source_ref`` re-derivation as commit applies (a mismatch -> ``None``).
    The block-level no-change gate is bypassed: derivation has no user edit
    to compare (it used to feed helv/12/black into that gate and escaped a
    false NO_CHANGE only because 'Helvetica' and 'helv' resolve apart).
    """
    doc = model.doc
    if doc is None:
        return None
    page_idx = page_num - 1
    if page_idx < 0 or page_idx >= len(doc):
        return None
    model.ensure_page_index_built(page_num)
    page = doc[page_idx]
    # Same boundary rule as ``edit_text``: displayed-space rect in, index space
    # for the resolve pipeline.
    rect = visual_to_unrotated_rect(page, fitz.Rect(rect))
    effective_target_mode = model._resolve_effective_target_mode(
        target_mode=target_mode,
        target_span_id=target_span_id,
        new_rect=None,
        page_idx=page_idx,
        rect=rect,
        original_text=original_text,
    )
    resolve_status, resolve_result = model._resolve_edit_target(
        page_num=page_num,
        page_idx=page_idx,
        page=page,
        rect=rect,
        new_text=original_text or "",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=original_text,
        new_rect=None,
        resolved_target_span_id=target_span_id,
        effective_target_mode=effective_target_mode,
        source_ref=source_ref,
        check_no_change=False,
    )
    if resolve_status is not EditTextResult.SUCCESS or resolve_result is None:
        return None
    target = _tier0_target_from_resolve(model, page_idx, resolve_result)
    if target is None:
        return None
    return target


def _classify_tier0_candidate(
    model: PDFModel,
    page: fitz.Page,
    page_idx: int,
    new_text: str,
    resolve_result: _EditTextResolveResult,
    style_overrides: StyleOverrides | None,
    new_rect: fitz.Rect | None,
    registry: DocumentFontRegistry,
):
    target = _tier0_target_from_resolve(model, page_idx, resolve_result)
    if target is None:
        return PlanRejection(
            RejectReason.MULTI_SPAN_TARGET,
            "target does not map to one whole line or one whole word run",
        )
    result = prepare_tier0_plan(
        model.doc,
        page,
        target_text=target.text,
        replacement_text=target.replacement_for(new_text),
        expected_origin=target.origin,
        target_bbox=target.bbox,
        registry=registry,
        style_overrides=style_overrides,
        new_rect=new_rect,
    )
    if isinstance(result, PlanRejection):
        reason = _reconstruction_aware_reason(result.reason, target)
        if reason != result.reason:
            return PlanRejection(reason, _reconstruction_detail(target))
    return result


def _shadow_classify_edit(
    model: PDFModel,
    page: fitz.Page,
    page_idx: int,
    new_text: str,
    resolve_result: _EditTextResolveResult,
    style_overrides: StyleOverrides | None,
    new_rect: fitz.Rect | None,
) -> None:
    """Shadow mode: classify only, log sanitized codes, never interfere.

    The log line carries reason codes and timing exclusively — never
    document text (telemetry/privacy contract of the V2 plan). Emitted only
    when ``TextCommitSettings.telemetry == "local"`` so the parsed
    ``TEXT_COMMIT_TELEMETRY`` flag has honest effect.
    """
    _t0 = time.perf_counter()
    try:
        registry = DocumentFontRegistry(model.doc)
        plan = _classify_tier0_candidate(
            model, page, page_idx, new_text, resolve_result,
            style_overrides, new_rect, registry,
        )
        capable = not isinstance(plan, PlanRejection)
        reason = "tier0_eligible" if capable else plan.reason
    except Exception as exc:  # shadow must never break the real edit
        logger.warning(
            "text_commit_shadow error page=%s %s", page_idx + 1, type(exc).__name__
        )
        return
    settings = getattr(model, "text_commit_settings", None)
    if settings is None or settings.telemetry != "local":
        return
    logger.info(
        "text_commit_shadow page=%s tier0_capable=%s reason=%s duration_ms=%.1f",
        page_idx + 1,
        capable,
        reason,
        (time.perf_counter() - _t0) * 1000,
    )


def _attempt_tiered_commit(
    model: PDFModel,
    page: fitz.Page,
    page_idx: int,
    new_text: str,
    resolve_result: _EditTextResolveResult,
    style_overrides: StyleOverrides | None,
    new_rect: fitz.Rect | None,
    plan_token: str | None = None,
) -> tuple[CommitOutcome | None, str | None]:
    """Try a Tier 0 commit; ``(outcome, None)`` on success, else ``(None, reason)``.

    UI step 5 (apply by token): with a ``plan_token`` the commit is bound to
    the candidate the preview verified.  A cache hit is re-bound on the live
    page (``TieredCommitEngine.cached_candidate_identity_failure``); a cache
    miss re-prepares and commits only an identical token.  Every token
    mismatch returns ``RejectReason.PREVIEW_STALE``, which ``edit_text``
    turns into a terminal ``PREVIEW_STALE`` refusal -- never a fallback.
    Explicit style/geometry overrides keep their own refusal codes: the
    preview refuses those too, so such a token can never have matched.
    """
    token_bound = plan_token is not None
    target = _tier0_target_from_resolve(model, page_idx, resolve_result)
    if target is None:
        if token_bound:
            return None, RejectReason.PREVIEW_STALE
        return None, RejectReason.MULTI_SPAN_TARGET
    replacement = target.replacement_for(new_text)
    engine = model.get_tiered_commit_engine()
    has_override = (
        style_overrides is not None and style_overrides.changed
    ) or new_rect is not None

    # WS-A: when a preview token is supplied, try the verified candidate
    # cache first — the preview already prepared and scratch-verified this
    # exact candidate, so re-preparing it is wasted work.
    cached = engine.get_verified_candidate(plan_token) if plan_token else None
    if cached is not None and has_override:
        # The cache holds whatever the PREVIEW classified — it never saw
        # today's explicit restyle or user-dragged geometry (the preview
        # request that produced this token carried neither, or it would
        # have been refused there too). Reusing it here would silently
        # commit the untouched cached candidate and discard the override.
        # Fall through to a fresh prepare() so the real gate
        # (style_override_present / geometry_override_present) refuses.
        cached = None
    if cached is not None and (
        cached.original_text != target.text or cached.replacement_text != replacement
    ):
        # The cache may hold a candidate the PREVIEW derived from a
        # different target/replacement framing than this commit just
        # derived (e.g. recovery's whitespace re-projection changed between
        # the preview request and this commit). Trusting it here would
        # commit a candidate for text the commit path never actually
        # proved. Fall through to a fresh prepare().
        cached = None
    prepared: PreparedEdit | PlanRejection
    if cached is not None:
        # The stream a cached candidate targets may have started being
        # shared by another page's /Contents since it was prepared — every
        # tier mutates its stream in place, so committing a stale candidate
        # here would silently rewrite that other page too. Re-run the same
        # gate a fresh prepare() would run before trusting the cache.
        foreign = find_pages_sharing_content_stream(
            model.doc, stream_xref=cached.stream_xref, page_number=page_idx
        )
        if foreign:
            return None, RejectReason.SHARED_CONTENT_STREAM
        # UI step 5: the token only NAMES a candidate.  Twins share text and
        # replacement, so the checks above cannot tell them apart; re-bind
        # the target the commit side resolved today on the live page and
        # require the very show (and an unchanged page) the candidate was
        # verified for.
        identity_failure = engine.cached_candidate_identity_failure(
            page, cached, target_text=target.text, expected_origin=target.origin
        )
        if identity_failure is not None:
            logger.info(
                "text_commit: cached candidate token=%s… no longer binds (%s); "
                "refusing preview_stale",
                plan_token[:12] if plan_token else "?",
                identity_failure,
            )
            return None, RejectReason.PREVIEW_STALE
        prepared = cached
        logger.debug(
            "text_commit: reusing cached verified candidate token=%s…",
            plan_token[:12] if plan_token else "?",
        )
    else:
        prepared = engine.prepare(
            page,
            target_text=target.text,
            replacement_text=replacement,
            expected_origin=target.origin,
            target_bbox=target.bbox,
            style_overrides=style_overrides,
            new_rect=new_rect,
        )
        if token_bound and not has_override and (
            isinstance(prepared, PlanRejection) or prepared.token != plan_token
        ):
            # Cache miss: the re-prepared result is not the candidate the
            # user saw verified (a changed page, other text, or now a
            # refusal).  Never commit a silent substitute.
            logger.info(
                "text_commit: re-prepared candidate differs from token=%s… (%s); "
                "refusing preview_stale",
                plan_token[:12] if plan_token else "?",
                prepared.reason
                if isinstance(prepared, PlanRejection)
                else "token_mismatch",
            )
            return None, RejectReason.PREVIEW_STALE
    if isinstance(prepared, PlanRejection):
        return None, _reconstruction_aware_reason(prepared.reason, target)
    outcome = engine.commit(prepared)
    if outcome.status is CommitStatus.COMMITTED:
        return outcome, None
    if token_bound and outcome.status is CommitStatus.STALE_PLAN:
        # apply_patchset's own fingerprint/splice gate (zero mutation).
        return None, RejectReason.PREVIEW_STALE
    # Commit-stage failures carry a free-form diagnostic in degraded_reason
    # (raw exception text, pixel coordinates, resource names — the engine's
    # own warning log keeps it). The fallback reason must stay a STABLE code
    # (P0-C reason-codes-only contract: it feeds fallback_chain, which the
    # GUI notice and telemetry surface verbatim) — recover it from the
    # engine's coded fallback_chain instead.
    if outcome.fallback_chain:
        return None, outcome.fallback_chain[-1].split(":", 1)[-1]
    return None, outcome.status.value


# UI step 7: the reason recorded if the tiered arm ever returned neither an
# outcome nor a reason (not reachable today) -- still a refusal, never a
# fall-through to legacy.
_TIERED_REFUSAL_UNKNOWN = "tiered_refusal_unknown"


def _pending_legacy_fallback_chain(tier0_fallback_reason: str) -> tuple[str, ...]:
    """The chain a legacy-fallback commit will end up recording, computed
    BEFORE the commit happens so the P0-C phase 2 consent prompt shows the
    user exactly what phase 1's post-commit notice will later show -- one
    function, no risk of the two drifting apart."""
    return (f"tier0:{tier0_fallback_reason}", "legacy")


def _tier0_rejected_outcome(reason: str | None) -> CommitOutcome:
    """The ``last_commit_outcome`` of an edit the tiered engine refused with
    ``reason`` and nothing else ran (zero mutation, no legacy fallback)."""
    return CommitOutcome(
        status=CommitStatus.REJECTED,
        tier=None,
        fallback_chain=(f"tier0:{reason}",),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=reason,
        allows_external_reflow=False,
    )


def edit_text(model: PDFModel, page_num: int, rect: fitz.Rect, new_text: str,
              font: str = "helv", size: float = 12.0,
              color: tuple = (0.0, 0.0, 0.0),
              original_text: str | None = None,
              vertical_shift_left: bool = True,
              new_rect: fitz.Rect = None,
              target_span_id: str | None = None,
              target_mode: str | None = None,
              style_overrides: StyleOverrides | None = None,
              plan_token: str | None = None,
              confirm_fallback: Callable[[tuple[str, ...]], bool | RebuildConsent] | None = None,
              source_ref: SourceShowRef | None = None,
              requires_preview_token: bool = False,
              allow_rebuild: bool = False,
              place_anyway: bool = False,
              moving_off_page: bool = False,
              ) -> EditTextResult:
    """
    編輯文字：五步流程 + 三策略智能插入。

    流程：
      1. 驗證：從 TextBlockManager 取出 TextBlock，比對原文字
      2. 安全 Redaction：只清除目標 block 的 layout_rect
      3. 智能插入：策略 A (htmlbox) → B (auto-expand) → C (fallback)
      4. 驗證與回滾：difflib.ratio > 0.92，否則 page-level snapshot 回滾
      5. 更新索引：block_manager.update_block()

    Args:
        page_num: 頁碼（1-based）
        rect: 使用者選取的粗略矩形
        new_text: 新文字內容
        font: 字體名稱
        size: 字體大小
        color: 文字顏色 (0-1 float tuple)
        original_text: 原始文字內容（可選，用於精確定位）
        vertical_shift_left: 垂直文字擴展方向（True=左移，False=右移）
        confirm_fallback: P0-C phase 2 一次性同意回呼。僅在 tiered 引擎真正嘗試
            過、非 strict、且 ``allow_rebuild`` 為 True 時呼叫一次，傳入
            ``fallback_chain``；回傳 False 則以零突變回傳
            ``EditTextResult.FALLBACK_DECLINED``。Model 對此僅視為不透明
            callable，不引入 Qt 相依。呼叫期間 ``model.pending_rebuild_glyph_loss``
            列出重建無法保留的未修改字形（F11-UNI-1 決議 C）；回傳
            ``RebuildConsent(acknowledged_glyph_loss=<完全相同的清單>)`` 才算確認，
            單純 True 不確認任何字形（重建仍會被拒絕）。
        allow_rebuild: UI step 7 明確重建同意（僅「改用重建文字…」設定）。
            tiered 拒絕且未設定 → ``EditTextResult.REJECTED``（真實原因記在
            ``last_commit_outcome.degraded_reason``），零突變，絕不進 legacy；
            設定但 ``confirm_fallback is None`` → ``FALLBACK_DECLINED``（缺少
            callback 不代表同意）；設定且有 callback → 詢問（預設否）後才 legacy。
        place_anyway: 僅對拖曳（``new_rect``）的重建有意義（S17 / TODOS F13-VF-4c）：
            拖曳框預設不套用鄰字上限，但套用重疊保護，會蓋到未修改文字時以
            ``TextEditRefusal.DRAGGED_BOX_OVERPRINTS`` 拒絕並回滾；設定後本次編輯
            兩者皆不套用（使用者的選擇，逐次，無全域設定）。未拖曳的編輯忽略此旗標。
        moving_off_page: 跨頁移動的來源刪除（F17-COL 同類）：目的頁以一般 RGB 文字框
            重建被移動的文字，無法帶上渲染模式、ExtGState 或圖層；來源文字為隱藏、外框、
            透明或混合模式、在圖層內，或其狀態無法判定時，在任何改動前以
            ``TEXT_STATE_NOT_REPRODUCIBLE`` 拒絕（僅色彩空間不同者仍轉為 RGB，待負責人決定）。
    """
    # Keep empty text as a valid edit: redact target text and reinsert nothing.
    if new_text is None:
        new_text = ""

    _t0 = time.perf_counter()  # Phase 6: 效能計時
    model.last_commit_outcome = None
    if requires_preview_token and plan_token is None and not allow_rebuild:
        # UI step 5: the inline Apply commits only a verified preview.  No
        # token yet -> nothing to commit; refused before any resolve, tier or
        # legacy work (zero mutation).  allow_rebuild (the explicit rebuild
        # action, step 7) and tokenless internal callers never set it.
        logger.info("text_commit_preview_pending page=%s", page_num)
        return EditTextResult.PREVIEW_PENDING
    page_idx = page_num - 1
    model.ensure_page_index_built(page_num)
    # typed bind; callers guarantee an open doc here (edit path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[page_idx]
    # Boundary conversion: the View hands geometry in DISPLAYED space; the
    # resolve pipeline (``find_by_rect``) and the legacy insert work in the
    # index's unrotated space (identity at /Rotate 0). The legacy insert's
    # page-bounds clamps therefore need the UNROTATED page box too --
    # ``page.rect`` has swapped extents on quarter-turn pages.
    page_rect = unrotated_page_rect(page)
    if rect is not None:
        rect = visual_to_unrotated_rect(page, fitz.Rect(rect))
    if new_rect is not None:
        new_rect = visual_to_unrotated_rect(page, fitz.Rect(new_rect))
    rollback_flag = False
    resolved_target_span_id = target_span_id
    effective_target_mode = model._resolve_effective_target_mode(
        target_mode=target_mode,
        target_span_id=target_span_id,
        new_rect=new_rect,
        page_idx=page_idx,
        rect=rect,
        original_text=original_text,
    )
    resolve_result: _EditTextResolveResult | None = None

    # ── Step 0: 擷取 page-level 快照，供回滾使用 ──
    snapshot_bytes = model._capture_page_snapshot(page_idx)
    # The bookkeeping that must travel with the bytes (R5-BOOK-1), captured at
    # the same instant; ``None`` for a model that does not expose it.
    maintenance_book = MaintenanceBook.capture(model, [page_idx])
    # Set right before the first legacy mutation: a RuntimeError past it that
    # did not come from ``_rollback_rebuild_page`` left the page rewritten.
    rewrite_started = False

    def _log_transaction() -> float:
        """The one ``edit_transaction`` debug line (success and both failure
        paths); returns the elapsed seconds."""
        duration = time.perf_counter() - _t0
        logger.debug(
            "edit_transaction page=%s target_span_id=%s target_mode=%s cluster_size=%s protected_count=%s rollback_flag=%s duration_ms=%s",
            page_num,
            resolved_target_span_id,
            effective_target_mode,
            len(resolve_result.overlap_cluster) if resolve_result else 0,
            len(resolve_result.protected_spans) if resolve_result else 0,
            rollback_flag,
            round(duration * 1000, 2),
        )
        return duration

    try:
        resolve_status, resolve_result = model._resolve_edit_target(
            page_num=page_num,
            page_idx=page_idx,
            page=page,
            rect=rect,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
            original_text=original_text,
            new_rect=new_rect,
            resolved_target_span_id=resolved_target_span_id,
            effective_target_mode=effective_target_mode,
            source_ref=source_ref,
        )
        if resolve_status is not EditTextResult.SUCCESS:
            return resolve_status

        resolved_target_span_id = resolve_result.resolved_target_span_id
        effective_target_mode = resolve_result.effective_target_mode
        if moving_off_page:
            # F17-COL same class: checked before Tier 0 and the rebuild alike.
            _refuse_moving_styled_text(model, page, resolve_result)
        # F17-COL-1..4: the paint state the rebuild keeps, captured before the
        # consent (an unkeepable one refuses without asking) and passed on.
        rebuild_paint: _RebuildPaint | None = None
        # F15-2: the words before any commit, only on a page with app textboxes, so
        # the marker sync can grow a box over the new words the edit drew outside it.
        textbox_words_before = textbox_page_words(model, page_num)

        # ── V2 engine hook (flag-gated; default "tiered" since Task 16,
        # so the second arm is the common path; "legacy" skips both) ──
        tier0_fallback_reason: str | None = None
        # F11-UNI-1: the untouched unkeepable glyphs the consent acknowledged
        # (set only in the consented-rebuild branch below).
        acknowledged_glyph_loss: tuple[UnkeepableGlyph, ...] = ()
        # Part-3 VERIFY defect 7: unknown settings are the shipped tiered
        # defaults (fail-closed, like the cross-page consent gate) -- never a
        # silent skip of the tiered branch into legacy.
        settings = getattr(model, "text_commit_settings", None) or TextCommitSettings()
        if settings.engine == "shadow":
            _shadow_classify_edit(
                model, page, page_idx, new_text, resolve_result,
                style_overrides, new_rect,
            )
        elif settings.engine == "tiered":
            tier0_outcome, tier0_fallback_reason = _attempt_tiered_commit(
                model, page, page_idx, new_text, resolve_result,
                style_overrides, new_rect, plan_token=plan_token,
            )
            if tier0_outcome is not None:
                # Lossless commit succeeded: no redaction happened, so no
                # pending cleanup; the page is now fidelity-protected.
                model.block_manager.rebuild_page(page_idx, doc)
                model.fidelity_protected_pages.add(page_idx)
                model.edit_count += 1
                model.last_commit_outcome = tier0_outcome
                # Tier 0 keeps the source style (it refuses style overrides): text only.
                _sync_textbox_objects(
                    model, page_num, new_text, resolve_result,
                    new_rect=new_rect, style=None, words_before=textbox_words_before,
                )
                logger.debug(
                    "text_commit_tiered page=%s tier=%s committed duration_ms=%s",
                    page_num,
                    tier0_outcome.tier.value if tier0_outcome.tier is not None else "?",
                    round((time.perf_counter() - _t0) * 1000, 2),
                )
                return EditTextResult.SUCCESS
            if tier0_fallback_reason == RejectReason.PREVIEW_STALE:
                # UI step 5: terminal -- checked before strict and before the
                # consent/legacy branch, so a stale token can never reach a
                # fallback chain or the degrade notice.
                model.last_commit_outcome = _tier0_rejected_outcome(RejectReason.PREVIEW_STALE)
                logger.info("text_commit_preview_stale page=%s", page_num)
                return EditTextResult.PREVIEW_STALE
            if settings.strict:
                model.last_commit_outcome = _tier0_rejected_outcome(tier0_fallback_reason)
                logger.info(
                    "text_commit_strict_reject page=%s reason=%s",
                    page_num,
                    tier0_fallback_reason,
                )
                return EditTextResult.REJECTED_STRICT

            # UI step 7 (no silent legacy; owner decision 2026-09-30): the
            # tiered refusal is FINAL unless the request carries the explicit
            # rebuild consent.  Zero mutation has happened at this point (a
            # prepare-stage PlanRejection never touches the live doc; a
            # commit-stage failure reverts internally before returning).
            real_reason = tier0_fallback_reason or _TIERED_REFUSAL_UNKNOWN
            if real_reason == RejectReason.NO_CHANGE:
                # The plan gate checks "replacement equals source" before the
                # override gates (order pinned by the structural-gate tests),
                # so an unchanged text with a restyle or a drag surfaces as
                # no_change.  Report the override -- the real reason -- and
                # treat a genuine no-op as nothing to do, not a refusal.
                if style_overrides is not None and style_overrides.changed:
                    real_reason = RejectReason.STYLE_OVERRIDE_PRESENT
                elif new_rect is not None:
                    real_reason = RejectReason.GEOMETRY_OVERRIDE_PRESENT
                else:
                    logger.info("text_commit_no_change page=%s", page_num)
                    return EditTextResult.NO_CHANGE
            if not allow_rebuild:
                model.last_commit_outcome = _tier0_rejected_outcome(real_reason)
                logger.info(
                    "text_commit_rejected page=%s reason=%s", page_num, real_reason
                )
                return EditTextResult.REJECTED
            # allow_rebuild: a missing callback is NOT consent.
            rebuild_paint = _rebuild_paint(
                model, page, resolve_result,
                new_text=new_text, color=color, moved=new_rect is not None,
            )
            pending_chain = _pending_legacy_fallback_chain(real_reason)
            # F11-UNI-1 (owner decision C): the untouched glyphs this rebuild
            # cannot keep are exposed for the duration of the ask, so the
            # consent dialog can name them; only a ``RebuildConsent`` that
            # acknowledges exactly this report lets the verification accept
            # them.  A bare ``True`` acknowledges nothing (refusal as before).
            glyph_loss = _rebuild_glyph_loss(new_text, resolve_result)
            consent: bool | RebuildConsent = False
            if confirm_fallback is not None:
                model.pending_rebuild_glyph_loss = glyph_loss
                try:
                    consent = confirm_fallback(pending_chain)
                finally:
                    model.pending_rebuild_glyph_loss = ()
            if not consent:
                logger.info(
                    "text_commit_fallback_declined page=%s chain=%s",
                    page_num,
                    "→".join(pending_chain),
                )
                return EditTextResult.FALLBACK_DECLINED
            if (
                glyph_loss
                and isinstance(consent, RebuildConsent)
                and tuple(consent.acknowledged_glyph_loss) == glyph_loss
            ):
                acknowledged_glyph_loss = glyph_loss
            elif glyph_loss:
                logger.info(
                    "text_commit_glyph_loss_unacknowledged page=%s glyphs=%s",
                    page_num,
                    [(g.span_id, g.index, g.codepoint) for g in glyph_loss],
                )

        rewrite_started = True
        new_layout_rect = model._apply_redact_insert(
            page=page,
            page_num=page_num,
            page_idx=page_idx,
            page_rect=page_rect,
            new_text=new_text,
            size=size,
            color=color,
            vertical_shift_left=vertical_shift_left,
            new_rect=new_rect,
            snapshot_bytes=snapshot_bytes,
            resolve_result=resolve_result,
            maintenance_book=maintenance_book,
            source_rect=rect,
            place_anyway=place_anyway,
            paint=rebuild_paint,
        )

        model._verify_rebuild_edit(
            page=page,
            page_num=page_num,
            page_idx=page_idx,
            page_rect=page_rect,
            new_text=new_text,
            size=size,
            color=color,
            snapshot_bytes=snapshot_bytes,
            resolve_result=resolve_result,
            new_layout_rect=new_layout_rect,
            maintenance_book=maintenance_book,
            acknowledged_glyph_loss=acknowledged_glyph_loss,
        )

        # F15-2: the legacy rebuild drew new_text in the edit's font/size/colour.
        _sync_textbox_objects(
            model,
            page_num,
            new_text,
            resolve_result,
            new_rect=new_rect,
            style=(resolve_result.resolved_font, float(size), tuple(color or (0.0, 0.0, 0.0))),
            words_before=textbox_words_before,
        )

        # ── Phase 6: GC + 效能計時 ──
        model.edit_count += 1
        model._maybe_garbage_collect(page_idx)

        _duration = _log_transaction()
        if _duration > 0.3:
            logger.warning("單次編輯過慢：%.3fs，頁面 %s", _duration, page_num)
        outcome = legacy_commit_outcome()
        if tier0_fallback_reason is not None:
            outcome = dataclasses_replace(
                outcome,
                fallback_chain=_pending_legacy_fallback_chain(tier0_fallback_reason),
            )
        model.last_commit_outcome = outcome
        return EditTextResult.SUCCESS

    except RuntimeError as runtime_err:
        rollback_flag = True
        rollback_failure: Exception | None = None
        if rewrite_started and not isinstance(runtime_err, _RebuildRolledBack):
            # A RuntimeError from inside the rewrite itself (MuPDF, a failed
            # sub-step) that no site rolled back: put page AND book back.
            try:
                _rollback_rebuild_page(model, page_idx, snapshot_bytes, maintenance_book)
            except Exception as rollback_err:
                rollback_failure = rollback_err
                logger.exception("編輯文字回滾失敗: page=%s", page_num)
        _log_transaction()
        if rollback_failure is not None:
            # The page is half-rewritten and no undo entry exists: say so
            # (same wording as the Exception branch), not a plain edit failure.
            raise _rollback_failed_refusal(
                model, f"編輯文字失敗且回滾失敗: {runtime_err}; rollback: {rollback_failure}"
            ) from rollback_failure
        if not isinstance(runtime_err, TextEditRefused):
            # Uncoded RuntimeError from inside the edit (MuPDF, a sub-step):
            # the page is back; code it so the Controller shows one zh-TW
            # sentence instead of this exception's technical text.
            raise TextEditRefused(TextEditRefusal.EDIT_FAILED, str(runtime_err)) from runtime_err
        raise
    except Exception as e:
        logger.error(f"編輯文字時發生非預期錯誤: {e}")
        rollback_error: Exception | None = None
        try:
            rollback_flag = True
            _rollback_rebuild_page(model, page_idx, snapshot_bytes, maintenance_book)
        except Exception as rollback_err:
            rollback_error = rollback_err
            logger.error(
                "編輯文字回滾失敗: page=%s original_error=%s rollback_error=%s",
                page_num,
                e,
                rollback_err,
            )
        _log_transaction()
        if rollback_error is not None:
            raise _rollback_failed_refusal(
                model, f"編輯文字失敗且回滾失敗: {e}; rollback: {rollback_error}"
            ) from rollback_error
        raise TextEditRefused(TextEditRefusal.EDIT_FAILED, f"編輯文字失敗: {e}") from e

    # Phase 4: undo/redo 已由 CommandManager (EditTextCommand) 全權負責，
    #          此處不再呼叫 _save_state()，避免雙重儲存浪費 I/O。

# _save_state() 已於 Phase 6 移除，所有 undo/redo 由 CommandManager 統一管理。

