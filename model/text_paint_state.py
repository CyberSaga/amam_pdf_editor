"""The paint state of the text a legacy rebuild writes again (F17-COL-1..4).

The consented rebuild (``legacy_redact_reinsert``, the "改用重建文字" path and
the same-page drag) erases text and draws it again through ``insert_htmlbox``
or ``insert_text``: the edited runs, the overlapping neighbours it replays and
the blocks a push-down moves.  Those writers draw DeviceRGB fill text with no
ExtGState, no text render mode and no marked content, so a rebuild turned
invisible OCR text (``3 Tr``) visible over the scan, took text out of its
optional-content layer (visible with the layer off), converted CMYK, gray,
Separation, ICC and Indexed colour to RGB and dropped alpha, blend mode and
outline (stroke) text -- live and after save.

This module is the one place that knows that state:

* :class:`PageTextStates` reads it for the glyphs of a page BEFORE anything is
  erased.  A walk of the page's content streams (and of the form XObjects they
  invoke) records the paint state of every text show.  When the page holds
  more than one state, the shows are told apart on a scratch copy of the page
  that draws every show in its own unique fill colour: MuPDF's own extraction
  then says which show drew which glyph, so nothing is matched by geometry.
* :func:`paint_state_applied` re-applies a captured state to what ONE writer
  call put on the page: the writer's own colour (and any render mode, pen or
  ExtGState it set) is removed from the stream and the form XObjects it added,
  and that stream is wrapped in ``q [/OC /n BDC] <state> ... [EMC] Q`` (the
  render mode goes inside every text object the writer drew), so the new text
  inherits the source's colour space and components, render mode, ExtGState
  (alpha, blend mode, soft mask, overprint) and layer.

"Plain" text (DeviceRGB fill, render mode 0, no ExtGState that changes how
filled text looks, no optional content) needs nothing and is written exactly
as before.  A state a page-level wrapper cannot reproduce -- a clipping render
mode (4-7), a Pattern colour, stroked text under a scaled CTM, a soft mask set
under a transformed CTM, a run whose glyphs mix states, a page the capture
cannot read -- is reported through ``TextPaintState.unreproducible`` and the
caller refuses (``TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE``) before
anything is written: never a silent conversion.

Non-OC marked content (structure ``/MCID`` tags, ``/Artifact``, ``/ActualText``
spans) is semantic, not paint: it is not part of this state (a rebuilt run
leaves the structure tree, as it always did; TODOS F17-COL).

Qt-free (CLAUDE.md layer rules).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

import fitz

from model.page_content_text import content_text, content_textpage
from model.pdf_content_ops import AffineMatrix, affine_concat
from model.text_commit.cid_fonts import (
    PdfParseError,
    PdfRef,
    canonical_pdf_text,
    parse_pdf_value,
)
from model.text_commit.pdf_lexer import StreamToken, TokenKind, lex_content_stream
from model.text_edit_refusal import TextEditRefusal, TextEditRefused

logger = logging.getLogger(__name__)

# ``pdf_text_edit._PageGlyph.key``: (character, origin x * 10, origin y * 10).
GlyphKey = tuple[str, int, int]
Matrix = AffineMatrix

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Bounds of one capture walk (decoded bytes over every stream visit, form
# invocations, nesting).  Past them the page cannot be read: a rebuild that
# needs its state refuses instead of guessing.
_MAX_WALK_BYTES = 64 * 1024 * 1024
_MAX_FORM_DEPTH = 16
_MAX_FORM_VISITS = 4096
_MAX_GSTATE_ENTRIES = 64
# Scratch tags are 24-bit fill colours; 0 is left out (black is everywhere).
_MAX_TAGS = (1 << 24) - 2

# Text render modes (PDF 32000 Table 106).
_STROKING_MODES = frozenset({1, 2, 5, 6})
_CLIPPING_MODES = frozenset({4, 5, 6, 7})

_DEVICE_FILL = {b"g": ("DeviceGray", 1), b"rg": ("DeviceRGB", 3), b"k": ("DeviceCMYK", 4)}
_DEVICE_STROKE = {b"G": ("DeviceGray", 1), b"RG": ("DeviceRGB", 3), b"K": ("DeviceCMYK", 4)}
_DEVICE_INITIAL = {
    "DeviceGray": ("0",),
    "DeviceRGB": ("0", "0", "0"),
    "DeviceCMYK": ("0", "0", "0", "1"),
}
_DEVICE_FILL_OP = {"DeviceGray": "g", "DeviceRGB": "rg", "DeviceCMYK": "k"}
_DEVICE_STROKE_OP = {"DeviceGray": "G", "DeviceRGB": "RG", "DeviceCMYK": "K"}
_PEN_OPERATORS = frozenset({b"w", b"J", b"j", b"M", b"d"})
_SHOW_OPERAND_COUNT = {b"Tj": 1, b"'": 1, b'"': 3}
_STRING_KINDS = (TokenKind.STRING, TokenKind.HEXSTRING)
_TRIVIA = (TokenKind.WHITESPACE, TokenKind.COMMENT)

# What a writer (insert_htmlbox / insert_text) may set that the re-applied
# state must own instead: its colour, render mode, pen and ExtGState.
_FILL_COLOUR_OPS = frozenset({b"g", b"rg", b"k", b"cs", b"sc", b"scn"})
_WRITER_STATE_OPS = frozenset(
    {b"G", b"RG", b"K", b"CS", b"SC", b"SCN", b"Tr", b"gs", b"ri", b"i"}
) | _PEN_OPERATORS

_SIMPLE_NAME = re.compile(r"\A[A-Za-z0-9_.+\-]{1,64}\Z")
_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_DRAW_OPS = frozenset({b"Tj", b"TJ", b"'", b'"', b"Do"})


@dataclass(frozen=True)
class ResourceUse:
    """One named resource a state needs: its category in ``/Resources``, the
    name the source used ("" for a form XObject's own ``/OC``) and its value
    as PDF syntax (``"12 0 R"`` or a direct object); ``""`` when the name did
    not resolve."""

    category: str  # "ColorSpace" | "ExtGState" | "Properties"
    # Not compared: the same object named /GS0 on the page and /GS1 in a form
    # is the same state.
    name: str = field(compare=False)
    value: str = ""


@dataclass(frozen=True)
class PaintColour:
    """A fill or stroke colour: its space and its components as written."""

    space: str  # DeviceGray | DeviceRGB | DeviceCMYK | named | pattern | unresolved
    components: tuple[str, ...] = ()
    resource: ResourceUse | None = None


INITIAL_COLOUR = PaintColour("DeviceGray", ("0",))


@dataclass(frozen=True)
class GstateEntry:
    """One ExtGState applied (``gs``) or one pen / intent operator."""

    operator: str  # "gs" | "w" | "J" | "j" | "M" | "d" | "ri"
    operands: str = ""  # the operator's operands as written (never for "gs")
    resource: ResourceUse | None = None  # "gs" only
    fill_visual: bool = False  # changes how filled (or invisible) text looks
    stroke_visual: bool = False  # changes how stroked text looks
    smask: bool = False  # sets a soft mask
    smask_ctm_identity: bool = True  # the soft mask was set under the identity CTM


@dataclass(frozen=True)
class TextPaintState:
    """How a text show paints: what a page-level wrapper must re-apply."""

    render_mode: int = 0
    fill: PaintColour = INITIAL_COLOUR
    stroke: PaintColour = INITIAL_COLOUR  # INITIAL unless the mode strokes
    gstate: tuple[GstateEntry, ...] = ()
    optional_content: tuple[ResourceUse, ...] = ()  # enclosing /OC, outermost first
    unreproducible: str | None = None  # why it cannot be re-applied faithfully

    @property
    def plain(self) -> bool:
        """DeviceRGB fill, render mode 0, nothing else: what the writers draw."""
        return (
            self.unreproducible is None
            and self.render_mode == 0
            and self.fill.space == "DeviceRGB"
            and not self.gstate
            and not self.optional_content
        )

    @property
    def changes_visibility(self) -> bool:
        """More than the colour model: drawn invisible or as an outline,
        through an ExtGState that changes how it looks (alpha, blend, soft
        mask, ...), inside optional content -- or not reproducible at all."""
        return bool(
            self.unreproducible
            or self.render_mode != 0
            or self.optional_content
            or any(entry.operator == "gs" for entry in self.gstate)
        )

    @property
    def has_soft_mask(self) -> bool:
        return any(entry.smask for entry in self.gstate)

    def describe(self) -> str:
        """Code-only log text (no document content)."""
        return (
            f"Tr={self.render_mode} fill={self.fill.space} stroke={self.stroke.space} "
            f"gs={len(self.gstate)} oc={len(self.optional_content)} "
            f"unreproducible={self.unreproducible}"
        )


def unreproducible_state(reason: str) -> TextPaintState:
    """A state that refuses: the capture could not establish or keep it."""
    return TextPaintState(unreproducible=reason)


# ───────────────────────────────────────────────────────── matrices / numbers


def _is_identity(m: Matrix) -> bool:
    return all(abs(v - w) <= 1e-4 for v, w in zip(m, _IDENTITY))


def _unit_similarity(m: Matrix) -> bool:
    """``m`` keeps lengths: a rotation and/or reflection plus a translation."""
    a, b, c, d, _e, _f = m
    return (
        abs(a * a + b * b - 1.0) <= 1e-3
        and abs(c * c + d * d - 1.0) <= 1e-3
        and abs(a * c + b * d) <= 1e-3
    )


def _number(value: object, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


# ───────────────────────────────────────────────────────── resources


def _ref_xref(value: str) -> int | None:
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return None


def _dict_holder(doc: fitz.Document, xref: int, path: str) -> tuple[int, str] | None:
    """``(xref, prefix)`` addressing the dictionary at ``xref``/``path``
    through ``xref_get_key(xref, prefix + key)``: an indirect dictionary is
    followed (``xref_get_key`` paths cannot cross an indirect object)."""
    try:
        kind, value = doc.xref_get_key(xref, path)
    except Exception:
        return None
    if kind == "xref":
        target = _ref_xref(value)
        if target is None:
            return None
        try:
            if not doc.xref_is_stream(target) and doc.xref_object(target).lstrip().startswith("<<"):
                return target, ""
        except Exception:
            return None
        return None
    if kind == "dict":
        return xref, path + "/"
    return None


def page_resource_holder(doc: fitz.Document, page: fitz.Page) -> tuple[int, str] | None:
    """The page's ``/Resources`` (inherited from the page tree when the page
    has none of its own)."""
    holder = _dict_holder(doc, page.xref, "Resources")
    if holder is not None:
        return holder
    xref = page.xref
    for _ in range(32):
        try:
            kind, value = doc.xref_get_key(xref, "Parent")
        except Exception:
            return None
        parent = _ref_xref(value) if kind == "xref" else None
        if parent is None:
            return None
        xref = parent
        holder = _dict_holder(doc, xref, "Resources")
        if holder is not None:
            return holder
    return None


def _unescape_name_byte(match: re.Match[bytes]) -> bytes:
    return bytes((int(match.group(1), 16),))


def _decode_name(raw: bytes) -> str:
    """A name token's bytes (with the leading slash) as its decoded text."""
    body = raw[1:] if raw.startswith(b"/") else raw
    return _NAME_ESCAPE.sub(_unescape_name_byte, body).decode("latin-1")


def _token_name(data: bytes, token: StreamToken) -> str:
    """The decoded text of the name token ``token`` of ``data``."""
    return _decode_name(data[token.start:token.end])


def _name_bytes(name: str) -> bytes:
    out = bytearray(b"/")
    for byte in name.encode("latin-1", errors="replace"):
        if byte < 0x21 or byte > 0x7E or chr(byte) in "()<>[]{}/%#":
            out += b"#%02X" % byte
        else:
            out.append(byte)
    return bytes(out)


class _ResourceScope:
    """Name lookups in one ``/Resources`` dictionary (cached)."""

    def __init__(self, doc: fitz.Document, holder: tuple[int, str] | None) -> None:
        self._doc = doc
        self._holder = holder
        self._categories: dict[str, tuple[int, str] | None] = {}
        self._entries: dict[tuple[str, str], tuple[str, str] | None] = {}

    def entry(self, category: str, name: str) -> tuple[str, str] | None:
        """``(kind, value)`` of ``/Resources/<category>/<name>``, ``None`` if absent."""
        key = (category, name)
        if key in self._entries:
            return self._entries[key]
        result: tuple[str, str] | None = None
        if self._holder is not None and name and "/" not in name:
            if category not in self._categories:
                hx, hp = self._holder
                self._categories[category] = _dict_holder(self._doc, hx, hp + category)
            cat = self._categories[category]
            if cat is not None:
                try:
                    kind, value = self._doc.xref_get_key(cat[0], cat[1] + name)
                except Exception:
                    kind, value = "null", "null"
                if kind not in ("null", ""):
                    result = (kind, value)
        self._entries[key] = result
        return result

    def use(self, category: str, name: str) -> ResourceUse:
        found = self.entry(category, name)
        return ResourceUse(category, name, found[1] if found is not None else "")

    def parsed(self, category: str, name: str) -> object:
        """The resolved object of an entry (``None`` when absent or unreadable)."""
        found = self.entry(category, name)
        if found is None:
            return None
        return _parse_entry(self._doc, *found)


def _parse_entry(doc: fitz.Document, kind: str, value: str) -> object:
    try:
        if kind == "xref":
            target = _ref_xref(value)
            if target is None:
                return None
            return parse_pdf_value(doc.xref_object(target))
        return parse_pdf_value(value)
    except (PdfParseError, ValueError, RuntimeError):
        return None


def _deref(doc: fitz.Document, value: object) -> object:
    for _ in range(4):
        if not isinstance(value, PdfRef):
            return value
        try:
            value = parse_pdf_value(doc.xref_object(value.xref))
        except (PdfParseError, ValueError, RuntimeError):
            return None
    return value


def _classify_extgstate(doc: fitz.Document, gs: object) -> tuple[bool, bool, bool, bool]:
    """``(readable, fill_visual, stroke_visual, smask)`` of an ExtGState."""
    gs = _deref(doc, gs)
    if not isinstance(gs, dict):
        return False, False, False, False
    fill = stroke = smask = False
    for key, raw in gs.items():
        value = _deref(doc, raw)
        if key in ("Type", "Font", "SM", "FL"):
            continue
        if key == "ca":
            fill |= _number(value, 0.0) != 1.0
        elif key == "CA":
            stroke |= _number(value, 0.0) != 1.0
        elif key == "BM":
            mode = value[0] if isinstance(value, list) and value else value
            changes = mode not in ("/Normal", "/Compatible")
            fill |= changes
            stroke |= changes
        elif key == "SMask":
            changes = value != "/None"
            smask |= changes
            fill |= changes
            stroke |= changes
        elif key == "op":
            fill |= value is True
        elif key == "OP":
            stroke |= value is True
            if "op" not in gs:
                fill |= value is True
        elif key == "AIS":
            fill |= value is True
            stroke |= value is True
        elif key == "TK":
            fill |= value is False
            stroke |= value is False
        elif key in ("LW", "LC", "LJ", "ML", "D", "SA"):
            stroke = True
        elif key == "OPM":
            changes = _number(value, 1.0) != 0.0
            fill |= changes
            stroke |= changes
        elif key == "RI":
            changes = value != "/RelativeColorimetric"
            fill |= changes
            stroke |= changes
        else:
            # TR/TR2/BG/BG2/UCR/UCR2/HT/HTO/UseBlackPtComp and anything newer.
            changes = value not in ("/Default", "/Identity", None)
            fill |= changes
            stroke |= changes
    return True, fill, stroke, smask


def _colour_space(scope: _ResourceScope, doc: fitz.Document, name: str) -> PaintColour:
    """The colour ``/name cs`` selects (its initial colour)."""
    if name in _DEVICE_INITIAL:
        return PaintColour(name, _DEVICE_INITIAL[name])
    if name == "Pattern":
        return PaintColour("pattern")
    found = scope.entry("ColorSpace", name)
    if found is None:
        return PaintColour("unresolved")
    value = _deref(doc, _parse_entry(doc, *found))
    family = value[0] if isinstance(value, list) and value else value
    if isinstance(family, str) and family[1:] in _DEVICE_INITIAL:
        # An alias of a device space (``/CS0 /DeviceRGB``).
        return PaintColour(family[1:], _DEVICE_INITIAL[family[1:]])
    if family == "/Pattern":
        return PaintColour("pattern")
    if value is None:
        return PaintColour("unresolved")
    return PaintColour("named", (), ResourceUse("ColorSpace", name, found[1]))


# ───────────────────────────────────────────────────────── the walk


class _GState:
    """The paint part of one q-level of the graphics state."""

    __slots__ = ("ctm", "fill", "stroke", "render_mode", "entries", "overflow")

    def __init__(self) -> None:
        self.ctm: Matrix = _IDENTITY
        self.fill: PaintColour = INITIAL_COLOUR
        self.stroke: PaintColour = INITIAL_COLOUR
        self.render_mode = 0
        self.entries: tuple[GstateEntry, ...] = ()
        self.overflow = False

    def copy(self) -> _GState:
        other = _GState()
        other.ctm = self.ctm
        other.fill = self.fill
        other.stroke = self.stroke
        other.render_mode = self.render_mode
        other.entries = self.entries
        other.overflow = self.overflow
        return other

    def add_entry(self, entry: GstateEntry) -> None:
        entries = self.entries
        if entry.operator != "gs":
            # A later pen/intent operator overrides every earlier one of its kind.
            entries = tuple(e for e in entries if e.operator != entry.operator)
        if len(entries) >= _MAX_GSTATE_ENTRIES:
            self.overflow = True
            return
        self.entries = entries + (entry,)


@dataclass
class _Frame:
    gs: _GState
    qstack: list[_GState]
    marked: list[ResourceUse | None]  # open marked content: its /OC, or None
    inherited_oc: tuple[ResourceUse, ...]
    scope: _ResourceScope
    depth: int
    forms: tuple[int, ...]

    @classmethod
    def root(cls, scope: _ResourceScope) -> _Frame:
        """The initial state a page content stream starts in."""
        return cls(_GState(), [], [], (), scope, 0, ())

    def oc_chain(self) -> tuple[ResourceUse, ...]:
        return self.inherited_oc + tuple(u for u in self.marked if u is not None)


@dataclass(frozen=True)
class _Visit:
    stream_xref: int
    op_start: int
    state: TextPaintState


def _freeze(gs: _GState, oc: tuple[ResourceUse, ...]) -> TextPaintState:
    mode = gs.render_mode
    strokes = mode in _STROKING_MODES
    fills = mode in (0, 2)
    entries: list[GstateEntry] = []
    for entry in gs.entries:
        if entry.operator == "gs":
            if entry.fill_visual or (strokes and entry.stroke_visual) or entry.resource is None:
                entries.append(entry)
        elif entry.operator == "ri":
            if entry.operands.strip() != "/RelativeColorimetric":
                entries.append(entry)
        elif strokes:
            entries.append(entry)
    fill = gs.fill
    if not fills and fill.space in ("pattern", "unresolved"):
        fill = INITIAL_COLOUR  # not painted by this mode
    stroke = gs.stroke if strokes else INITIAL_COLOUR
    reason: str | None = None
    if mode not in range(8):
        reason = "render_mode_out_of_range"
    elif mode in _CLIPPING_MODES:
        reason = "clipping_render_mode"
    elif "pattern" in (fill.space, stroke.space):
        reason = "pattern_colour"
    elif "unresolved" in (fill.space, stroke.space):
        reason = "unresolved_colour_space"
    elif gs.overflow:
        reason = "graphics_state_too_long"
    elif any(e.operator == "gs" and (e.resource is None or not e.resource.value) for e in entries):
        reason = "unresolved_extgstate"
    elif any(e.smask and not e.smask_ctm_identity for e in entries):
        reason = "soft_mask_under_transform"
    elif any(not u.value for u in oc):
        reason = "unresolved_optional_content"
    elif strokes and not _unit_similarity(gs.ctm):
        reason = "stroke_under_scaled_ctm"
    return TextPaintState(
        render_mode=mode,
        fill=fill,
        stroke=stroke,
        gstate=tuple(entries),
        optional_content=oc,
        unreproducible=reason,
    )


class _Walker:
    """Every text show of a page (and of the forms it invokes) with its state."""

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.visits: list[_Visit] = []
        self.failure: str | None = None
        self._bytes = 0
        self._form_visits = 0
        self._gs_cache: dict[tuple[str, str, int], GstateEntry] = {}
        self._freeze_cache: dict[tuple[object, ...], TextPaintState] = {}

    # -- entry points
    def walk_page(self, page: fitz.Page) -> _Walker:
        scope = _ResourceScope(self.doc, page_resource_holder(self.doc, page))
        frame = _Frame.root(scope)
        for xref in page.get_contents():
            self._run(frame, xref, self._stream(xref))
            if self.failure:
                break
        return self

    def walk_streams(self, page: fitz.Page, xrefs: Iterable[int]) -> _Walker:
        """Walk only ``xrefs`` (page content streams), each from the initial state."""
        scope = _ResourceScope(self.doc, page_resource_holder(self.doc, page))
        for xref in xrefs:
            self._run(_Frame.root(scope), xref, self._stream(xref))
            if self.failure:
                break
        return self

    # -- helpers
    def _stream(self, xref: int) -> bytes:
        try:
            return self.doc.xref_stream(xref) or b""
        except Exception:
            self.failure = self.failure or "stream_unreadable"
            return b""

    def _state(self, frame: _Frame) -> TextPaintState:
        gs = frame.gs
        oc = frame.oc_chain()
        strokes = gs.render_mode in _STROKING_MODES
        key = (
            gs.render_mode,
            gs.fill,
            gs.stroke,
            gs.entries,
            gs.overflow,
            oc,
            _unit_similarity(gs.ctm) if strokes else True,
        )
        cached = self._freeze_cache.get(key)
        if cached is None:
            cached = _freeze(gs, oc)
            self._freeze_cache[key] = cached
        return cached

    def _gs_entry(self, frame: _Frame, name: str) -> GstateEntry | None:
        found = frame.scope.entry("ExtGState", name)
        if found is None:
            return None  # MuPDF ignores an ExtGState name it cannot find
        cache_key = (found[0], found[1], id(frame.scope))
        entry = self._gs_cache.get(cache_key)
        if entry is None:
            readable, fill, stroke, smask = _classify_extgstate(
                self.doc, _parse_entry(self.doc, *found)
            )
            use = ResourceUse("ExtGState", name, found[1] if readable else "")
            entry = GstateEntry("gs", resource=use, fill_visual=fill or not readable,
                                stroke_visual=stroke or not readable, smask=smask)
            self._gs_cache[cache_key] = entry
        if entry.smask:
            entry = replace(entry, smask_ctm_identity=_is_identity(frame.gs.ctm))
        return entry

    @staticmethod
    def _numbers(data: bytes, operands: list[StreamToken], count: int) -> list[float] | None:
        if len(operands) < count:
            return None
        tail = operands[-count:]
        if any(t.kind is not TokenKind.NUMBER for t in tail):
            return None
        try:
            return [float(data[t.start:t.end]) for t in tail]
        except ValueError:
            return None

    @staticmethod
    def _texts(data: bytes, operands: list[StreamToken]) -> tuple[str, ...]:
        return tuple(data[t.start:t.end].decode("latin-1") for t in operands)

    # -- the interpreter
    def _run(self, frame: _Frame, stream_xref: int, data: bytes) -> None:
        self._bytes += len(data)
        if self._bytes > _MAX_WALK_BYTES:
            self.failure = self.failure or "page_too_large"
            return
        operands: list[StreamToken] = []
        for token in lex_content_stream(data):
            kind = token.kind
            if kind in _TRIVIA:
                continue
            if kind is TokenKind.OPERATOR:
                op = data[token.start:token.end]
                if op in (b"true", b"false", b"null"):
                    operands.append(token)
                    continue
                self._operator(frame, stream_xref, data, op, operands)
                operands = []
                if self.failure:
                    return
                continue
            if kind in (TokenKind.INLINE_IMAGE_DATA, TokenKind.MALFORMED):
                operands = []
                continue
            operands.append(token)

    def _operator(
        self,
        frame: _Frame,
        stream_xref: int,
        data: bytes,
        op: bytes,
        operands: list[StreamToken],
    ) -> None:
        gs = frame.gs
        if op == b"q":
            frame.qstack.append(gs.copy())
        elif op == b"Q":
            if frame.qstack:
                frame.gs = frame.qstack.pop()
        elif op == b"cm":
            nums = self._numbers(data, operands, 6)
            if nums is not None:
                gs.ctm = affine_concat(tuple(nums), gs.ctm)  # type: ignore[arg-type]
        elif op in _DEVICE_FILL or op in _DEVICE_STROKE:
            space, count = _DEVICE_FILL.get(op) or _DEVICE_STROKE[op]
            nums = self._numbers(data, operands, count)
            if nums is not None:
                colour = PaintColour(space, self._texts(data, operands[-count:]))
                if op in _DEVICE_FILL:
                    gs.fill = colour
                else:
                    gs.stroke = colour
        elif op in (b"cs", b"CS"):
            if operands and operands[-1].kind is TokenKind.NAME:
                colour = _colour_space(frame.scope, self.doc, _token_name(data, operands[-1]))
                if op == b"cs":
                    gs.fill = colour
                else:
                    gs.stroke = colour
        elif op in (b"sc", b"scn", b"SC", b"SCN"):
            fill = op in (b"sc", b"scn")
            current = gs.fill if fill else gs.stroke
            if operands and operands[-1].kind is TokenKind.NAME:
                colour = PaintColour("pattern")
            elif all(t.kind is TokenKind.NUMBER for t in operands) and operands:
                colour = replace(current, components=self._texts(data, operands))
            else:
                colour = current
            if fill:
                gs.fill = colour
            else:
                gs.stroke = colour
        elif op == b"Tr":
            nums = self._numbers(data, operands, 1)
            if nums is not None and float(nums[0]).is_integer():
                gs.render_mode = int(nums[0])
        elif op == b"gs":
            if operands and operands[-1].kind is TokenKind.NAME:
                entry = self._gs_entry(frame, _token_name(data, operands[-1]))
                if entry is not None:
                    gs.add_entry(entry)
        elif op in _PEN_OPERATORS or op == b"ri":
            if operands:
                text = data[operands[0].start:operands[-1].end].decode("latin-1")
                gs.add_entry(GstateEntry(op.decode("latin-1"), operands=text))
        elif op in _SHOW_OPERAND_COUNT or op == b"TJ":
            self._show(frame, stream_xref, op, operands)
        elif op in (b"BDC", b"BMC"):
            frame.marked.append(self._marked_content(frame, data, op, operands))
        elif op == b"EMC":
            if frame.marked:
                frame.marked.pop()
        elif op == b"Do":
            if operands and operands[-1].kind is TokenKind.NAME:
                self._invoke(frame, _token_name(data, operands[-1]))

    def _show(self, frame: _Frame, stream_xref: int, op: bytes, operands: list[StreamToken]) -> None:
        start: int | None = None
        if op == b"TJ":
            for token in reversed(operands):
                if token.kind is TokenKind.ARRAY_OPEN:
                    start = token.start
                    break
        else:
            count = _SHOW_OPERAND_COUNT[op]
            if len(operands) >= count and operands[-1].kind in _STRING_KINDS:
                start = operands[-count].start
        if start is None:
            # MuPDF draws nothing for a show without its string operand (it
            # reports a syntax error and goes on): no glyph to account for.
            return
        self.visits.append(_Visit(stream_xref, start, self._state(frame)))

    def _marked_content(
        self, frame: _Frame, data: bytes, op: bytes, operands: list[StreamToken]
    ) -> ResourceUse | None:
        if op != b"BDC" or not operands or operands[0].kind is not TokenKind.NAME:
            return None
        if _token_name(data, operands[0]) != "OC":
            return None
        props = operands[1] if len(operands) > 1 else None
        if props is not None and props.kind is TokenKind.NAME:
            use = frame.scope.use("Properties", _token_name(data, props))
            # An /OC name that does not resolve hides nothing (MuPDF draws the
            # content): it is not a layer to keep.
            return use if use.value else None
        return ResourceUse("Properties", "", "")  # inline/odd /OC: cannot be re-applied

    def _invoke(self, frame: _Frame, name: str) -> None:
        found = frame.scope.entry("XObject", name)
        if found is None or found[0] != "xref":
            return
        xref = _ref_xref(found[1])
        if xref is None:
            return
        try:
            subtype = self.doc.xref_get_key(xref, "Subtype")[1]
        except Exception:
            return
        if subtype != "/Form":
            return
        if xref in frame.forms or frame.depth >= _MAX_FORM_DEPTH:
            self.failure = self.failure or "form_recursion"
            return
        self._form_visits += 1
        if self._form_visits > _MAX_FORM_VISITS:
            self.failure = self.failure or "too_many_forms"
            return
        matrix: Matrix = _IDENTITY
        try:
            kind, value = self.doc.xref_get_key(xref, "Matrix")
            if kind == "array":
                parsed = parse_pdf_value(value)
                if (
                    isinstance(parsed, list)
                    and len(parsed) == 6
                    and all(_number(v) is not None for v in parsed)
                ):
                    matrix = tuple(float(v) for v in parsed)  # type: ignore[assignment]
            oc_kind, oc_value = self.doc.xref_get_key(xref, "OC")
        except (PdfParseError, ValueError, RuntimeError):
            oc_kind, oc_value = "null", "null"
        holder = _dict_holder(self.doc, xref, "Resources")
        scope = _ResourceScope(self.doc, holder) if holder is not None else frame.scope
        inherited = frame.oc_chain()
        if oc_kind == "xref":
            inherited = inherited + (ResourceUse("Properties", "", oc_value),)
        elif oc_kind not in ("null", ""):
            inherited = inherited + (ResourceUse("Properties", "", ""),)
        child_gs = frame.gs.copy()
        child_gs.ctm = affine_concat(matrix, child_gs.ctm)
        child = _Frame(child_gs, [], [], inherited, scope, frame.depth + 1, frame.forms + (xref,))
        self._run(child, xref, self._stream(xref))


# ───────────────────────────────────────────────────────── page capture

_PLAIN = "plain"


def _norm(state: TextPaintState) -> TextPaintState | str:
    """``state`` as compared across shows: every plain state is one ``_PLAIN``."""
    return _PLAIN if state.plain else state


class PageTextStates:
    """The paint state of every glyph of one page, as the page is NOW.

    Build it before the page is changed.  ``flags`` must be the extraction
    flags the caller's glyph keys come from (``pdf_text_edit._page_glyphs``).
    """

    def __init__(self, page: fitz.Page, flags: int = 0) -> None:
        self._page = page
        self._doc = page.parent
        self._flags = flags
        walker = _Walker(self._doc).walk_page(page)
        self._visits = walker.visits
        self._failure = walker.failure
        self._uniform: TextPaintState | str | None = None
        self._mixed = False
        self._tags: dict[GlyphKey, tuple[int, ...]] | None = None
        self._tag_failure: str | None = None
        if self._failure is None:
            distinct = {_norm(v.state) for v in self._visits}
            if len(distinct) > 1:
                self._mixed = True
            elif distinct:
                self._uniform = distinct.pop()
        logger.debug(
            "text paint capture page=%s shows=%s failure=%s mixed=%s",
            page.number,
            len(self._visits),
            self._failure,
            self._mixed,
        )

    @property
    def all_plain(self) -> bool:
        """Every text show of the page is plain (nothing to re-apply anywhere)."""
        return self._failure is None and not self._mixed and self._uniform in (None, _PLAIN)

    def state_of(self, keys: Iterable[GlyphKey]) -> TextPaintState | None:
        """The one state that drew the glyphs ``keys``: ``None`` when it is
        plain (or there is no inked glyph), else the state -- with
        ``unreproducible`` set when the glyphs cannot be told apart, mix
        states, or their state cannot be re-applied."""
        wanted = list(dict.fromkeys(keys))
        if not wanted:
            return None
        if self._failure is not None:
            return unreproducible_state(f"capture_failed:{self._failure}")
        if not self._mixed:
            uniform = self._uniform
            return uniform if isinstance(uniform, TextPaintState) else None
        tags = self._tag_map()
        if tags is None:
            return unreproducible_state(f"glyph_states_unknown:{self._tag_failure}")
        found: set[TextPaintState | str] = set()
        for key in wanted:
            visit_ids = tags.get(key)
            if not visit_ids:
                return unreproducible_state("glyph_without_show")
            for index in visit_ids:
                found.add(_norm(self._visits[index].state))
        if len(found) != 1:
            return unreproducible_state("glyphs_mix_states")
        only = found.pop()
        return only if isinstance(only, TextPaintState) else None

    def _tag_map(self) -> dict[GlyphKey, tuple[int, ...]] | None:
        if self._tags is not None or self._tag_failure is not None:
            return self._tags
        try:
            self._tags = _glyph_show_map(self._doc, self._page, self._visits, self._flags)
        except Exception as exc:  # a capture that cannot run refuses, never guesses
            logger.warning("text paint capture: scratch tagging failed: %s", exc)
            self._tags = None
            self._tag_failure = type(exc).__name__
        if self._tags is None and self._tag_failure is None:
            self._tag_failure = "scratch_mismatch"
        return self._tags


def _tag_colour(tag: int) -> bytes:
    r, g, b = (tag >> 16) & 0xFF, (tag >> 8) & 0xFF, tag & 0xFF
    return b" %.6f %.6f %.6f rg 0 Tr " % (r / 255.0, g / 255.0, b / 255.0)


def _glyph_show_map(
    doc: fitz.Document, page: fitz.Page, live: list[_Visit], flags: int
) -> dict[GlyphKey, tuple[int, ...]] | None:
    """For every glyph of ``page``, the indexes of the ``live`` visits that
    drew it: a scratch copy of the page draws every show in its own fill
    colour (and fill mode); MuPDF's extraction of that copy reports the colour
    of every glyph, at the glyph's own origin."""
    scratch = fitz.open()
    try:
        scratch.insert_pdf(
            doc, from_page=page.number, to_page=page.number,
            links=False, annots=False, widgets=False,
        )
        spage = scratch[0]
        walk = _Walker(scratch).walk_page(spage)
        if walk.failure is not None or len(walk.visits) != len(live):
            return None
        tag_of: dict[tuple[int, int], int] = {}
        inserts: dict[int, list[tuple[int, int]]] = defaultdict(list)
        visits_of_tag: dict[int, list[int]] = defaultdict(list)
        for index, (mine, theirs) in enumerate(zip(walk.visits, live)):
            if mine.op_start != theirs.op_start:
                return None
            spot = (mine.stream_xref, mine.op_start)
            tag = tag_of.get(spot)
            if tag is None:
                tag = len(tag_of) + 1
                if tag > _MAX_TAGS:
                    return None
                tag_of[spot] = tag
                inserts[mine.stream_xref].append((mine.op_start, tag))
            visits_of_tag[tag].append(index)
        for xref, spots in inserts.items():
            data = scratch.xref_stream(xref) or b""
            pieces: list[bytes] = []
            last = 0
            for start, tag in sorted(spots):
                pieces.append(data[last:start])
                pieces.append(_tag_colour(tag))
                last = start
            pieces.append(data[last:])
            scratch.update_stream(xref, b"".join(pieces))
        raw = content_text(spage, "rawdict", textpage=content_textpage(spage, flags))
        result: dict[GlyphKey, list[int]] = defaultdict(list)
        for block in raw.get("blocks", ()):
            for line in block.get("lines", ()):
                for span in line.get("spans", ()):
                    visit_ids = visits_of_tag.get(int(span.get("color", 0)))
                    for ch in span.get("chars", ()):
                        c = ch.get("c", "")
                        if not c or ch.get("synthetic"):
                            continue
                        bbox = ch["bbox"]
                        ox, oy = (float(v) for v in ch.get("origin", (bbox[0], bbox[3])))
                        key = (c, round(ox * 10), round(oy * 10))
                        if visit_ids is None:
                            result.setdefault(key, [])
                            continue
                        result[key].extend(visit_ids)
        return {key: tuple(ids) for key, ids in result.items()}
    finally:
        scratch.close()


# ───────────────────────────────────────────────────────── what one write needs

Rgb8 = tuple[int, int, int]


def rgb8(colour: Iterable[float] | None) -> Rgb8:
    """A 0..1 RGB colour as the 8-bit triple the writers draw it with."""
    values = [float(c) for c in (colour or (0.0, 0.0, 0.0))][:3]
    values += [0.0] * (3 - len(values))
    r, g, b = (max(0, min(255, int(round(v * 255)))) for v in values)
    return r, g, b


@dataclass(frozen=True)
class WriteStyle:
    """The paint state one rebuild write must carry.

    ``fill``: ``"state"`` paints with ``state.fill`` (the writer's own colour is
    removed); ``"writer"`` keeps the writer's RGB fill (the user chose a
    colour, or every run is DeviceRGB); ``"map"`` replaces each writer colour
    by the source fill of the runs drawn in it (``fill_map``: several runs of
    one edit, each with its own colour space)."""

    state: TextPaintState
    fill: str = "state"
    fill_map: tuple[tuple[Rgb8, PaintColour], ...] = ()

    @property
    def unreproducible(self) -> str | None:
        return self.state.unreproducible

    @property
    def is_noop(self) -> bool:
        return self.fill == "writer" and replace(self.state, fill=_RGB_BLACK).plain


_RGB_BLACK = PaintColour("DeviceRGB", ("0", "0", "0"))
_PLAIN_STATE = TextPaintState(fill=_RGB_BLACK)


def style_for_run(state: TextPaintState | None) -> WriteStyle | None:
    """The style one run is written again with (``None``: plain, nothing to do)."""
    if state is None:
        return None
    return WriteStyle(state)


def _writer_fill(state: TextPaintState) -> WriteStyle | None:
    """``state`` around the writer's own RGB fill (``None``: nothing else to re-apply)."""
    style = WriteStyle(state, fill="writer")
    return None if style.is_noop else style


def style_for_runs(
    states: list[TextPaintState | None],
    colours: list[tuple[float, ...] | None],
    request_colour: Iterable[float] | None,
) -> WriteStyle | None:
    """The style the edited text (written from several runs) carries.

    ``states`` / ``colours``: each member run's state and sampled colour.
    The runs must agree on everything but the fill.  A request colour that is
    none of the runs' colours is the user's choice: the writer's RGB fill is
    kept.  Equal fills are re-applied as they are; different fills are mapped
    back per drawn colour (unambiguous only: two runs drawn in one RGB colour
    from different fills cannot be told apart, and refuse)."""
    if not states:
        return None
    real = [s if s is not None else _PLAIN_STATE for s in states]
    for state in real:
        if state.unreproducible:
            return WriteStyle(state)
    first = real[0]
    if any(
        (s.render_mode, s.stroke, s.gstate, s.optional_content)
        != (first.render_mode, first.stroke, first.gstate, first.optional_content)
        for s in real[1:]
    ):
        return WriteStyle(unreproducible_state("edited_runs_mix_states"))
    run_rgbs = [rgb8(c) for c in colours]
    if rgb8(request_colour) not in run_rgbs:
        return _writer_fill(first)
    if all(s.fill == first.fill for s in real[1:]):
        return None if first.plain else WriteStyle(first)
    if all(s.fill.space == "DeviceRGB" for s in real):
        return _writer_fill(first)
    mapping: dict[Rgb8, PaintColour] = {}
    for colour, state in zip(run_rgbs, real):
        known = mapping.setdefault(colour, state.fill)
        if known != state.fill:
            return WriteStyle(unreproducible_state("edited_runs_share_a_colour_across_spaces"))
    return WriteStyle(first, fill="map", fill_map=tuple(mapping.items()))


def refusal_for(
    style: WriteStyle | None, *, moved: bool, what: str
) -> TextEditRefused | None:
    """The refusal a rebuild raises BEFORE writing text in ``style``
    (``moved``: the text will not stay where it was), else ``None``."""
    if style is None:
        return None
    state = style.state
    reason = state.unreproducible
    if reason is None and moved and state.has_soft_mask:
        reason = "soft_mask_on_moved_text"
    if reason is None:
        return None
    return TextEditRefused(
        TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
        f"the rebuild cannot keep the paint state of {what}: {reason} ({state.describe()})",
    )


# ───────────────────────────────────────────────────────── re-applying


@contextmanager
def paint_state_applied(page: fitz.Page, style: WriteStyle | None) -> Iterator[None]:
    """Re-apply ``style`` to what the ONE writer call in the block draws.

    ``None`` (plain text) changes nothing.  A writer that drew nothing
    (htmlbox: the text did not fit) leaves nothing to do; one that raised
    leaves the caller's rollback to it."""
    if style is None or style.is_noop:
        yield
        return
    if style.unreproducible:
        raise TextEditRefused(
            TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
            f"paint state not reproducible: {style.state.describe()}",
        )
    doc = page.parent
    before = list(page.get_contents())
    first_new = doc.xref_length()
    yield
    try:
        _restyle_written(doc, page, set(before), first_new, style)
    except BaseException:
        # Never leave text the state could not be applied to on the page: the
        # write is taken back (its streams leave /Contents) and the caller's
        # refusal / rollback decides what happens next.
        doc.xref_set_key(
            page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in before) + "]"
        )
        raise


def _operator_spans(data: bytes, wanted: frozenset[bytes]) -> list[tuple[int, int, bytes]]:
    """``(first operand, operator end, operator)`` of every ``wanted`` operator."""
    spans: list[tuple[int, int, bytes]] = []
    first: int | None = None
    for token in lex_content_stream(data):
        if token.kind in _TRIVIA:
            continue
        if token.kind is TokenKind.OPERATOR:
            op = data[token.start:token.end]
            if op in (b"true", b"false", b"null"):
                if first is None:
                    first = token.start
                continue
            if op in wanted:
                spans.append((token.start if first is None else first, token.end, op))
            first = None
            continue
        if token.kind in (TokenKind.INLINE_IMAGE_DATA, TokenKind.MALFORMED):
            first = None
            continue
        if first is None:
            first = token.start
    return spans


def _replace_operators(
    data: bytes, spans: list[tuple[int, int, bytes]], new: list[bytes]
) -> bytes:
    pieces: list[bytes] = []
    last = 0
    for (start, end, _op), replacement in zip(spans, new):
        pieces.append(data[last:start])
        pieces.append(b" " + replacement + b" ")
        last = end
    pieces.append(data[last:])
    return b"".join(pieces)


def _after_each_bt(data: bytes, insert: bytes) -> bytes:
    """``data`` with ``insert`` placed right after every ``BT`` operator."""
    ends = [
        token.end
        for token in lex_content_stream(data)
        if token.kind is TokenKind.OPERATOR and data[token.start:token.end] == b"BT"
    ]
    if not ends:
        return data
    pieces: list[bytes] = []
    last = 0
    for end in ends:
        pieces.append(data[last:end])
        pieces.append(insert)
        last = end
    pieces.append(data[last:])
    return b"".join(pieces)


def _draws(data: bytes) -> bool:
    """``data`` shows text or invokes an XObject: the writer drew something."""
    return any(
        token.kind is TokenKind.OPERATOR and data[token.start:token.end] in _DRAW_OPS
        for token in lex_content_stream(data)
    )


def _new_forms(
    doc: fitz.Document, holder: tuple[int, str] | None, data: bytes, first_new: int
) -> list[int]:
    """Form XObjects ``data`` invokes that the writer just created."""
    scope = _ResourceScope(doc, holder)
    out: list[int] = []
    operand: bytes | None = None
    for token in lex_content_stream(data):
        if token.kind in _TRIVIA:
            continue
        if token.kind is TokenKind.NAME:
            operand = data[token.start:token.end]
            continue
        if token.kind is TokenKind.OPERATOR and data[token.start:token.end] == b"Do" and operand:
            found = scope.entry("XObject", _decode_name(operand))
            xref = _ref_xref(found[1]) if found is not None and found[0] == "xref" else None
            if xref is not None and xref >= first_new and xref not in out:
                out.append(xref)
        operand = None
    return out


def _written_streams(
    doc: fitz.Document, xref: int, holder: tuple[int, str] | None, first_new: int
) -> list[tuple[int, tuple[int, str] | None]]:
    """``xref`` and every form XObject the writer created under it, each with
    the resources its content resolves names in."""
    out: list[tuple[int, tuple[int, str] | None]] = []
    seen: set[int] = set()
    pending = [(xref, holder)]
    while pending:
        current, current_holder = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        out.append((current, current_holder))
        data = doc.xref_stream(current) or b""
        for form in _new_forms(doc, current_holder, data, first_new):
            pending.append((form, _dict_holder(doc, form, "Resources") or current_holder))
    return out


def _same_value(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return canonical_pdf_text(parse_pdf_value(a)) == canonical_pdf_text(parse_pdf_value(b))
    except (PdfParseError, ValueError):
        return False


def _ensure_resources(
    doc: fitz.Document, xref: int, inherited: tuple[int, str] | None
) -> tuple[int, str]:
    """``xref``'s own ``/Resources`` (created, from ``inherited`` when given)."""
    holder = _dict_holder(doc, xref, "Resources")
    if holder is not None:
        return holder
    if inherited is not None:
        hx, hp = inherited
        source = doc.xref_get_key(hx, hp[:-1])[1] if hp else doc.xref_object(hx)
        doc.xref_set_key(xref, "Resources", source)
    else:
        doc.xref_set_key(xref, "Resources", "<<>>")
    holder = _dict_holder(doc, xref, "Resources")
    if holder is None:
        raise RuntimeError("/Resources could not be created")
    return holder


def _register(doc: fitz.Document, holder: tuple[int, str], use: ResourceUse) -> str:
    """The name ``use`` has in ``holder``'s resources (added when missing)."""
    hx, hp = holder
    cat = _dict_holder(doc, hx, hp + use.category)
    if cat is None:
        doc.xref_set_key(hx, hp + use.category, "<<>>")
        cat = _dict_holder(doc, hx, hp + use.category)
        if cat is None:
            raise RuntimeError(f"/Resources/{use.category} could not be created")
    base = use.name if _SIMPLE_NAME.match(use.name or "") else f"Pdfe{use.category[:2]}"
    for n in range(1000):
        name = base if n == 0 else f"{base}_pdfe{n}"
        kind, value = doc.xref_get_key(cat[0], cat[1] + name)
        if kind in ("null", ""):
            doc.xref_set_key(cat[0], cat[1] + name, use.value)
            return name
        if _same_value(value, use.value):
            return name
    raise RuntimeError("no free resource name")


def _colour_ops(colour: PaintColour, name: str | None, *, stroke: bool) -> bytes:
    comps = " ".join(colour.components).encode("latin-1")
    if colour.space in _DEVICE_FILL_OP:
        op = (_DEVICE_STROKE_OP if stroke else _DEVICE_FILL_OP)[colour.space].encode()
        return comps + b" " + op
    if colour.space == "named" and name is not None:
        select = _name_bytes(name) + (b" CS" if stroke else b" cs")
        if not colour.components:
            return select
        return select + b" " + comps + (b" SCN" if stroke else b" scn")
    raise TextEditRefused(
        TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
        f"colour space {colour.space} cannot be re-applied",
    )


def _writer_rgb(data: bytes, start: int, end: int, op: bytes) -> Rgb8 | None:
    """The 8-bit RGB a writer's ``rg`` / ``g`` operator paints with."""
    texts = data[start:end].split()[:-1]
    try:
        values = [float(t) for t in texts]
    except ValueError:
        return None
    if op == b"rg" and len(values) == 3:
        return rgb8(values)
    if op == b"g" and len(values) == 1:
        return rgb8(values * 3)
    return None


def _map_writer_fills(
    doc: fitz.Document, xref: int, holder: tuple[int, str] | None, style: WriteStyle
) -> None:
    """Each writer fill colour replaced by the source fill it stands for."""
    data = doc.xref_stream(xref) or b""
    spans = _operator_spans(data, _FILL_COLOUR_OPS)
    if not spans:
        return
    mapping = dict(style.fill_map)
    new: list[bytes] = []
    for start, end, op in spans:
        drawn = _writer_rgb(data, start, end, op)
        colour = mapping.get(drawn) if drawn is not None else None
        if colour is None:
            raise TextEditRefused(
                TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
                f"the writer drew a colour no edited run has: {drawn}",
            )
        name = None
        if colour.resource is not None:
            name = _register(doc, _ensure_resources(doc, xref, holder), colour.resource)
        new.append(_colour_ops(colour, name, stroke=False))
    doc.update_stream(xref, _replace_operators(data, spans, new))


def _restyle_written(
    doc: fitz.Document,
    page: fitz.Page,
    before: set[int],
    first_new: int,
    style: WriteStyle,
) -> None:
    written = [
        x for x in page.get_contents()
        if x not in before and _draws(doc.xref_stream(x) or b"")
    ]
    if not written:
        return
    state = style.state
    holder = _ensure_resources(doc, page.xref, page_resource_holder(doc, page))
    strokes = state.render_mode in _STROKING_MODES
    uses: list[ResourceUse] = []
    if style.fill == "state" and state.fill.resource is not None:
        uses.append(state.fill.resource)
    if strokes and state.stroke.resource is not None:
        uses.append(state.stroke.resource)
    uses.extend(e.resource for e in state.gstate if e.resource is not None)
    uses.extend(state.optional_content)
    names = {use: _register(doc, holder, use) for use in dict.fromkeys(uses)}

    def colour_name(colour: PaintColour) -> str | None:
        return None if colour.resource is None else names.get(colour.resource)

    head: list[bytes] = [b"q"]
    for use in state.optional_content:
        head.append(b"/OC " + _name_bytes(names[use]) + b" BDC")
    if style.fill == "state":
        head.append(_colour_ops(state.fill, colour_name(state.fill), stroke=False))
    if strokes:
        head.append(_colour_ops(state.stroke, colour_name(state.stroke), stroke=True))
    for entry in state.gstate:
        if entry.operator == "gs" and entry.resource is not None:
            head.append(_name_bytes(names[entry.resource]) + b" gs")
        elif entry.operator != "gs":
            head.append(entry.operands.encode("latin-1") + b" " + entry.operator.encode())
    tail = [b"EMC"] * len(state.optional_content) + [b"Q"]
    prefix = b"\n".join(head) + b"\n"
    suffix = b"\n" + b"\n".join(tail) + b"\n"

    strip = _WRITER_STATE_OPS | (_FILL_COLOUR_OPS if style.fill == "state" else frozenset())
    render_mode = b" %d Tr " % state.render_mode
    for xref in written:
        for stream, stream_holder in _written_streams(doc, xref, holder, first_new):
            data = doc.xref_stream(stream) or b""
            spans = _operator_spans(data, strip)
            if spans:
                data = _replace_operators(data, spans, [b""] * len(spans))
            # The render mode goes INTO every text object the writer drew, not
            # into the page-level wrapper: the save's content cleaning drops
            # text state set outside BT in a stream that draws no text itself
            # (htmlbox's ``q /fzFrmN Do Q``), and 3 Tr text came back visible.
            data = _after_each_bt(data, render_mode)
            doc.update_stream(stream, data)
            if style.fill == "map":
                _map_writer_fills(doc, stream, stream_holder, style)
        doc.update_stream(xref, prefix + (doc.xref_stream(xref) or b"") + suffix)
    _verify_restyled(doc, page, written, style)


def _colour_signature(c: PaintColour) -> tuple[object, ...]:
    return (c.space, c.components, c.resource.value if c.resource is not None else None)


def _signature(state: TextPaintState, *, with_fill: bool) -> tuple[object, ...]:
    return (
        state.render_mode,
        _colour_signature(state.fill) if with_fill else None,
        _colour_signature(state.stroke),
        tuple(
            (e.operator, e.operands, e.resource.value if e.resource is not None else None)
            for e in state.gstate
        ),
        tuple(u.value for u in state.optional_content),
    )


def _verify_restyled(
    doc: fitz.Document, page: fitz.Page, written: list[int], style: WriteStyle
) -> None:
    """Read the rewritten streams back: every show must now paint in the
    style (resource names may differ; their values may not)."""
    walk = _Walker(doc).walk_streams(page, written)
    with_fill = style.fill == "state"
    expected = _signature(style.state, with_fill=with_fill)
    allowed_fills = {_colour_signature(c) for _rgb, c in style.fill_map}
    problems = [
        v.state.describe()
        for v in walk.visits
        if _signature(v.state, with_fill=with_fill) != expected
        or (style.fill == "map" and _colour_signature(v.state.fill) not in allowed_fills)
    ]
    if walk.failure or not walk.visits or problems:
        raise TextEditRefused(
            TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE,
            "re-applied paint state does not read back: "
            f"failure={walk.failure} shows={len(walk.visits)} "
            f"expected={style.state.describe()} got={problems[:3]}",
        )


__all__ = [
    "GlyphKey",
    "GstateEntry",
    "INITIAL_COLOUR",
    "PageTextStates",
    "PaintColour",
    "ResourceUse",
    "TextPaintState",
    "WriteStyle",
    "page_resource_holder",
    "paint_state_applied",
    "refusal_for",
    "rgb8",
    "style_for_run",
    "style_for_runs",
    "unreproducible_state",
]
