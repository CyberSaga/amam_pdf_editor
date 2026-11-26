"""Scanner G, the plain reference (design plan 4.1 to 4.4, card B2): decoded content streams -> index tables.

``scan_page(streams, frame)`` sees bytes and six frame numbers only (D15); it never reads a document, so
it cannot read ``/Resources``.  One compiled alternation claims comments, strings, hex strings, dictionary
openers, names, brackets and words at C level; a Python loop keeps the ``q``/``Q`` stack, the CTM
(``affine_concat``, Python floats), the flags (H11) and the rows.  Text objects are lexed, not skipped.
Every inline image stops the scan at its ``BI`` (H13); the payload scanner of the text-commit lexer is
never called.  Geometry is stored in unrotated page space (user space through ``frame``); the ``ctm``
column keeps the user-space CTM without the frame.

Review fixes (Astra + Opus on B2, 2026-11-23): operands carry their stream; every interpreted operator
has an exact operand count and kinds (a wrong one refuses the page); arrays and dictionaries are ONE typed
operand and may span streams; names are compared decoded; a path keeps raw user-space points and is
transformed once, with the PAINT-time CTM (what the renderer does); every derived coordinate and CTM must be
finite and inside float32 range; the segments table carries a ``subpath`` column (provisional 4.1 addition,
fill topology); ``line_width`` is the conservative page-space maximum (nominal width = ``line_width`` over the
larger singular value of ``ctm`` composed with ``frame``).

Model layer: no Qt.  numpy is imported here, so the package is imported lazily.
"""

from __future__ import annotations

import array
import enum
import hashlib
import logging
import math
import numbers
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from model.pdf_content_ops import affine_concat
from model.vector_paths.limits import MAX_DECODED_BYTES, VectorPageRefused

logger = logging.getLogger(__name__)

Frame = tuple[float, float, float, float, float, float]

MAX_PAINTS = 4_000_000
MAX_CHORD_ROWS = 8_000_000
MAX_OPERANDS = 4096  # pending operands before an operator (provisional, owner ratifies)
MAX_ARRAY_ELEMENTS = 1_000_000  # tokens inside one outermost array / dictionary
MAX_NEST = 256  # nesting depth of arrays and dictionaries
CHORD_EPSILON = 0.01  # pt, design 4.1
_SINGULAR_DET = 1e-12
_F32_MAX = float(np.finfo(np.float32).max)
_MAX_NUMBER_LEN = 1 << 20  # a number token longer than this refuses; shorter ones follow the PDF grammar (float() is linear, measured)
_TICK = 0x3FFF  # tokens between two cancel / progress checks (a power of two minus one)
_FLUSH_ROWS = 65536
_LONG_TOKEN = 1 << 16  # a token (with its leading white space) longer than this is followed by a cancel check
MAX_SEGMENT_ROWS = 8_000_000  # pending plus emitted line rows; charged BEFORE a path's primitives are allocated
_MUPDF_REAL_LIMIT =2147483648.0  # probe (MuPDF 1.27): a real token with |v| >= 2**31 is dropped or mis-read, so it refuses

PAINT_NAMES: tuple[str, ...] = ("", "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n")
_PAINT_CODE = {name.encode(): i for i, name in enumerate(PAINT_NAMES) if name}
_CLOSE_PAINTS = frozenset({b"s", b"b", b"b*"})
_STROKE_PAINTS = frozenset({b"S", b"s", b"B", b"B*", b"b", b"b*"})
_CONSTRUCT = frozenset({b"m", b"l", b"c", b"v", b"y", b"h", b"re"})
_PATH_OPS = _CONSTRUCT | frozenset({b"W", b"W*"}) | frozenset(_PAINT_CODE)
_INERT_OPS = frozenset(
    {b"cm", b"w", b"J", b"j", b"M", b"d", b"ri", b"i", b"gs", b"g", b"G", b"rg", b"RG", b"k", b"K", b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN"}
) | _CONSTRUCT | frozenset(_PAINT_CODE) - {b"n"}
_DEVICE_SPACES = frozenset({b"/DeviceGray", b"/DeviceRGB", b"/DeviceCMYK"})
_NUM_START = frozenset(b"0123456789+-.")
_FL_EDITABLE, _FL_DEGENERATE, _FL_SETS_CLIP, _FL_CLIPPED = 1, 2, 4, 8  # plain ints in the paint hot path (IntFlag `|` is slow)
_FL_IMPURE, _FL_SPANS_STREAMS, _FL_IN_OC, _FL_CTM_SINGULAR, _FL_PAGE_ANCHORED = 16, 32, 64, 128, 256
_SHOW_OPS = frozenset({b"Tj", b"TJ", b"'", b'"'})


class _StrT:
    """Operand kind: a literal or hex string."""


class _DictT:
    """Operand kind: a dictionary."""


class _ArrT:
    """Operand kind: an array."""


class _OtherT:
    """Operand kind: true, false or null."""


class _NumArrT(_ArrT):
    """Operand kind: an array whose elements are all numbers (the only legal dash array)."""


_STR, _DICT, _ARR, _OTHER, _ARR_NUM = _StrT(), _DictT(), _ArrT(), _OtherT(), _NumArrT()
_WS_BYTES = b"\x00\t\n\x0c\r "

# Exact operand kinds per interpreted operator (the count is the tuple length).  A wrong count or kind refuses the page.
_ARITY: dict[bytes, tuple[Any, ...]] = {
    b"m": (float, float),
    b"l": (float, float),
    b"c": (float,) * 6,
    b"v": (float,) * 4,
    b"y": (float,) * 4,
    b"re": (float,) * 4,
    b"h": (),
    b"cm": (float,) * 6,
    b"w": (float,),
    b"J": (float,),
    b"j": (float,),
    b"M": (float,),
    b"d": (_NumArrT, float),  # a dash array with a name or a string in it refuses (MuPDF drops the operator)
    b"ri": (bytes,),
    b"i": (float,),
    b"gs": (bytes,),
    b"g": (float,),
    b"G": (float,),
    b"rg": (float,) * 3,
    b"RG": (float,) * 3,
    b"k": (float,) * 4,
    b"K": (float,) * 4,
    b"cs": (bytes,),
    b"CS": (bytes,),
    b"Do": (bytes,),
    b"W": (),
    b"W*": (),
    b"q": (),
    b"Q": (),
    b"BT": (),
    b"ET": (),
    b"Tr": (float,),
    b"Tj": (_StrT,),
    b"TJ": (_ArrT,),
    b"'": (_StrT,),
    b'"': (float, float, _StrT),
    b"BDC": (bytes, (bytes, _DictT)),
    b"BMC": (bytes,),
    b"EMC": (),
    **{name: () for name in _PAINT_CODE},
}
_FLOAT_ARITY = {op: len(kinds) for op, kinds in _ARITY.items() if all(k is float for k in kinds)}
_VARCOLOR = frozenset({b"sc", b"SC", b"scn", b"SCN"})
_RESOURCE_OPS = frozenset({b"gs", b"cs", b"CS", b"scn", b"SCN"})  # operators whose last operand may name a /Resources entry


class PathFlag(enum.IntFlag):
    EDITABLE = 1
    DEGENERATE = 2
    SETS_CLIP = 4
    CLIPPED = 8
    IMPURE = 16
    SPANS_STREAMS = 32
    IN_OC = 64
    CTM_SINGULAR = 128
    PAGE_ANCHORED = 256


assert [int(f) for f in (PathFlag.EDITABLE, PathFlag.DEGENERATE, PathFlag.SETS_CLIP, PathFlag.CLIPPED, PathFlag.IMPURE, PathFlag.SPANS_STREAMS, PathFlag.IN_OC, PathFlag.CTM_SINGULAR, PathFlag.PAGE_ANCHORED)] == [
    _FL_EDITABLE, _FL_DEGENERATE, _FL_SETS_CLIP, _FL_CLIPPED, _FL_IMPURE, _FL_SPANS_STREAMS, _FL_IN_OC, _FL_CTM_SINGULAR, _FL_PAGE_ANCHORED
]


class VectorScanCancelled(Exception):
    """``cancel()`` answered true while scanning (nothing was returned, nothing was touched)."""


class _Bad(Exception):
    """A scan error before ``indexed_end``; becomes ``VectorPageRefused('SCAN_ERROR', ...)``."""


_PATH_DT = np.dtype(
    [
        ("path_start", np.int64),
        ("paint_end", np.int64),
        ("block", np.int32),
        ("paint", np.uint8),
        ("flags", np.uint16),
        ("bbox", np.float32, (4,)),
        ("line_width", np.float32),
        ("ctm", np.float64, (6,)),
        ("seg_start", np.int32),
        ("seg_count", np.int32),
    ]
)
_CUBIC_DT = np.dtype([("pts", np.float64, (8,)), ("path", np.int32), ("seg_start", np.int32), ("seg_count", np.int32)])
_SEG_DT = np.dtype(
    [
        ("x0", np.float64),
        ("y0", np.float64),
        ("x1", np.float64),
        ("y1", np.float64),
        ("path", np.int32),
        ("from_cubic", np.bool_),
        ("subpath", np.int32),  # provisional 4.1 addition: index of the subpath within its path (fill topology)
    ]
)
_BLOCK_DT = np.dtype(
    [
        ("q_start", np.int64),
        ("q_end", np.int64),
        ("n_paints", np.int32),
        ("inert", np.bool_),
        ("n_cm", np.int32),
        ("cm_operand_start", np.int64),
        ("cm_operand_end", np.int64),
    ]
)
_STREAM_DT = np.dtype([("xref", np.int64), ("global_start", np.int64), ("length", np.int64), ("raw_key", "S16")])
# Sparse table of round-cap dots (B7): a closed zero-length subpath in a stroked path that also draws something.
# ``subpath`` is the dot's ordinal inside its path; x, y are unrotated page space.  Sorted by (path, subpath).
_DOT_DT = np.dtype([("path", "<i4"), ("subpath", "<i4"), ("x", "<f8"), ("y", "<f8")])


@dataclass
class VectorIndex:
    paths: np.ndarray
    cubics: np.ndarray
    segments: np.ndarray
    blocks: np.ndarray
    streams: np.ndarray
    indexed_end: int
    stopped_at_inline_image: bool
    frame: Frame
    stream_digests: tuple[bytes, ...]
    nbytes: int
    # per block (same order as ``blocks``): the (operator, decoded name) pairs of every gs / cs / CS / scn / SCN naming a
    # resource inside the block (D21 revision 11).  A side table: no resolver here, PAGE_ANCHORED stays the conservative flag.
    block_resources: tuple[tuple[tuple[bytes, bytes], ...], ...] = ()
    # which implementation produced the tables and in which mode (set by ``scan_page``; travels in the
    # transport file, so a gate reads the CHILD's answer, not the GUI interpreter's)
    scanner: str = "G"
    accelerated: bool = False
    dots: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=_DOT_DT))


# ----------------------------------------------------------------------------- lexing

_WS_CLASS = rb"\x00\t\n\x0c\r "
_REG = rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]"
_TOKEN = re.compile(
    rb"[\x00\t\n\x0c\r ]*+(?:"
    rb"(?P<cmt>%[^\r\n]*+)"
    rb"|(?P<str>\([^()\\]*+(?:\\[\s\S][^()\\]*+)*+\))"
    rb"|(?P<nest>\()"
    rb"|(?P<dict><<)"
    rb"|(?P<hex><[^<>]*+>)"
    rb"|(?P<badhex><)"
    rb"|(?P<name>/" + _REG + rb"*+)"
    rb"|(?P<br>[\[\]{}])"
    rb"|(?P<stray>[)>])"
    rb"|(?P<word>" + _REG + rb"++)"
    rb"|(?P<end>\Z)"
    rb")"
)
_G = _TOKEN.groupindex
_G_CMT, _G_STR, _G_NEST, _G_DICT, _G_HEX, _G_BADHEX = _G["cmt"], _G["str"], _G["nest"], _G["dict"], _G["hex"], _G["badhex"]
_G_NAME, _G_BR, _G_STRAY, _G_WORD, _G_END = _G["name"], _G["br"], _G["stray"], _G["word"], _G["end"]
_STR_PIECE = re.compile(rb"\\[\s\S]|[()]")
_HEX_OK = re.compile(rb"<[0-9A-Fa-f\x00\t\n\x0c\r ]*+>")
_NUM = re.compile(rb"[+-]?+(?:\d++\.?+\d*+|\.\d++)")
_HASH = re.compile(rb"#([0-9A-Fa-f]{2})")


def _skip_string(buf: bytes, pos: int, poll: Callable[[], None] | None = None) -> int | None:
    """End offset of the literal string whose ``(`` is at ``pos`` (nested parentheses, backslash escapes), one pass."""
    depth = 1
    n = 0
    for m in _STR_PIECE.finditer(buf, pos + 1):
        ch = m.group()
        if ch == b"(":
            depth += 1
        elif ch == b")":
            depth -= 1
            if depth == 0:
                return m.end()
        n += 1
        if poll is not None and not n & _TICK:
            poll()
    return None


_F32 = array.array("f", [0.0])  # a one-slot float32 cell: ``_F32[0] = v; v = _F32[0]`` rounds a double to float32 at C speed


def _number(word: bytes) -> float:
    if len(word) > _MAX_NUMBER_LEN or _NUM.fullmatch(word) is None:
        raise _Bad(f"malformed number {word[:40]!r}")
    value = float(word)
    if value - value != 0.0:
        raise _Bad(f"non-finite number {word[:40]!r}")
    if b"." in word and abs(value) >= _MUPDF_REAL_LIMIT:
        raise _Bad(f"real number {word[:40]!r} beyond the range MuPDF reads (probe: '4294967316.0' is mis-read)")
    _F32[0] = value
    value = _F32[0]
    if value - value != 0.0:
        raise _Bad(f"number {word[:40]!r} beyond float32 range")
    return value


def _decode_name(raw: bytes) -> bytes:
    """``#xx`` escapes decoded once (semantic comparisons only; byte offsets always stay raw)."""
    if b"#" not in raw:
        return raw
    return _HASH.sub(lambda m: bytes([int(m.group(1), 16)]), raw)


# ----------------------------------------------------------------------------- the scanner


class _Scanner:
    def __init__(
        self,
        streams: tuple[bytes, ...],
        frame: Frame,
        cancel: Callable[[], bool] | None,
        progress: Callable[[int, int], None] | None,
    ) -> None:
        self.streams = streams
        self.frame = frame
        self.cancel = cancel
        self.progress = progress
        self.total = sum(len(s) for s in streams)
        # graphics state (restored by Q)
        self.ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.tot = affine_concat(self.ctm, frame)
        self.clipped = False
        self.gs = False
        self.cs_fill = False
        self.cs_stroke = False
        self.width = 1.0
        self.tr = 0
        self.stack: list[tuple[object, ...]] = []
        self.blk: list | None = None
        # text objects and a W seen while no path was open (neither is restored by Q)
        self.in_text = False
        self.text_clip = False
        self.pending_w = False
        # marked content (independent of q/Q)
        self.mc: list[bool] = []
        self.oc_count = 0
        # path under construction (outlives q and Q; a forward fill); points stay raw user space until the paint
        self.open = False
        self.p_start = 0
        self.p_stream = 0
        self.prims: list[tuple[float, ...]] = []
        self.dots: list[tuple[float, float]] = []  # zero-length closed subpaths (round-cap dots), raw user space
        self.sub_seg = False  # the current subpath has a segment
        self.cur: tuple[float, float] | None = None
        self.sub: tuple[float, float] | None = None
        self.sp = -1
        self.pt0: tuple[float, float] | None = None
        self.impure = False
        self.cap = 0.0  # J: 0 butt, 1 round, 2 square; nan after a gs (unknown, never guessed round)
        self.dot_rows: list[tuple[int, int, float, float]] = []
        self.has_w = False
        self.oc_start = False
        # operands since the last operator, and the stream of the first one
        self.ops: list[object] = []
        self.n_other = 0  # operands that are not numbers
        self.opnd_start = -1
        self.opnd_stream = 0
        self.last_end = -1
        self.stream = 0
        self.base = 0
        # a container (array or dictionary) in progress; it may continue in the next stream
        self.in_cmt = False
        self.data = False  # a string with character data among the pending operands (an empty show paints nothing)
        self.cn: list[int] = []  # per open container: elements seen (a dictionary alternates keys and values)
        self.c_numeric = True  # the outermost array holds numbers only
        self.cstack: list[bytes] = []
        self.cstart = 0
        self.cstream = 0
        self.ccount = 0
        self.ckind: object = _ARR
        self.n_paints = 0
        # rows
        self.c_start: list[int] = []
        self.c_end: list[int] = []
        self.c_block: list[int] = []
        self.c_paint: list[int] = []
        self.c_flags: list[int] = []
        self.c_bbox: list[list[float]] = []
        self.c_width: list[float] = []
        self.c_ctm: list[tuple[float, ...]] = []
        self.c_sstart: list[int] = []
        self.c_scount: list[int] = []
        self.line_buf: list[tuple[float, float, float, float, float, float, float]] = []
        self.seg_chunks: list[np.ndarray] = []
        self.nseg = 0
        self.chords = 0
        self.cb_pts: list[tuple[float, ...]] = []
        self.cb_path: list[int] = []
        self.cb_start: list[int] = []
        self.cb_count: list[int] = []
        self.b_rows: list[tuple[object, ...]] = []
        self.b_res: list[tuple[tuple[bytes, bytes], ...]] = []

    # -- plumbing ---------------------------------------------------------------------------------

    def _poll(self) -> None:
        if self.cancel is not None and self.cancel():
            raise VectorScanCancelled()

    def _tick(self, pos: int) -> None:
        self._poll()
        if self.progress is not None:
            self.progress(min(pos, self.total), self.total)

    def run(self) -> VectorIndex:
        starts: list[int] = []
        base = 0
        stopped = False
        indexed_end = self.total
        for i, buf in enumerate(self.streams):
            starts.append(base)
            self.stream = i
            self.base = base
            self._poll()
            hit = self._lex_stream(i, buf, base)
            if hit is not None:
                stopped, indexed_end = True, hit
                base += len(buf)
                starts.extend(_cumulative(self.streams[i + 1 :], base))
                break
            base += len(buf)
            if self.progress is not None:
                self.progress(min(base, self.total), self.total)
        if self.cstack:
            raise _Bad("unterminated array or dictionary at the end of the page")
        if self.progress is not None:
            self.progress(self.total, self.total)  # terminal event, also after an inline-image stop (H13)
        return self._build(starts, stopped, indexed_end)

    def _add_operand(self, value: object, start: int, stream: int, end: int) -> None:
        ops = self.ops
        ops.append(value)
        self.n_other += 1
        if len(ops) > MAX_OPERANDS:
            raise _Bad(f"more than {MAX_OPERANDS} pending operands")
        if self.opnd_start < 0:
            self.opnd_start = start
            self.opnd_stream = stream
        self.last_end = end

    def _lex_stream(self, i: int, buf: bytes, base: int) -> int | None:
        """Lex one stream; the offset (global) of a ``BI`` that stops the scan, else ``None``."""
        match = _TOKEN.match
        num_match = _NUM.fullmatch
        f32 = _F32
        ops = self.ops
        pos = 0
        n_tok = 0
        if self.in_cmt:  # a comment that ran to the end of the previous stream goes on to the first CR or LF here
            # MuPDF joins the /Contents streams into one byte sequence, so such a comment swallows the next stream's first
            # line (probe 2026-11-23: stream 0 '%c', stream 1 '10 10 m<LF>20 20 40 40 re f': the 'm' is comment text).
            cr, lf = buf.find(b"\r"), buf.find(b"\n")
            nl = min(v for v in (cr, lf) if v >= 0) if cr >= 0 or lf >= 0 else -1
            if nl < 0:
                return None
            self.in_cmt = False
            pos = nl
        if self.cstack:  # a container that began in an earlier stream continues here
            end = self._container(buf, pos)
            if end is None:
                return None
            self._finish_container(base + end)
            pos = end
        while True:
            m = match(buf, pos)
            if m is None:  # cannot happen: the last alternatives cover every byte
                raise _Bad("lexer stalled")
            gi = m.lastindex
            n_tok += 1
            if not n_tok & _TICK:
                self._tick(base + pos)
            if m.end() - pos > _LONG_TOKEN:
                self._poll()  # one very long token is one C-level match: answer a cancel as soon as it is over
            if gi == _G_WORD:
                s, e = m.span(_G_WORD)
                word = buf[s:e]
                pos = e
                if word[0] in _NUM_START:
                    if len(word) <= 20:  # at most 20 characters is always finite: skip the call
                        if num_match(word) is None:
                            raise _Bad(f"malformed number {word[:40]!r}")
                        f32[0] = float(word)  # MuPDF keeps operands as float32 (probe: 16777217 reads as 16777216)
                        value = f32[0]
                        if (value >= _MUPDF_REAL_LIMIT or value <= -_MUPDF_REAL_LIMIT) and b"." in word:
                            raise _Bad(f"real number {word[:40]!r} beyond the range MuPDF reads")
                    else:
                        value = _number(word)
                    ops.append(value)
                    if len(ops) > MAX_OPERANDS:
                        raise _Bad(f"more than {MAX_OPERANDS} pending operands")
                    if self.opnd_start < 0:
                        self.opnd_start = base + s
                        self.opnd_stream = i
                    self.last_end = base + e
                    continue
                if word == b"BI":
                    return base + s
                if word == b"true" or word == b"false" or word == b"null":
                    self._add_operand(_OTHER, base + s, i, base + e)
                    continue
                self._operator(word, base + s, base + e)
                ops.clear()
                self.data = False
                self.n_other = 0
                self.opnd_start = -1
            elif gi == _G_NAME:
                s, e = m.span(_G_NAME)
                self._add_operand(buf[s:e], base + s, i, base + e)
                pos = e
            elif gi == _G_CMT:
                pos = m.end()
                if pos == len(buf):
                    self.in_cmt = True
            elif gi == _G_END:
                return None
            elif gi == _G_STR:
                s, e = m.span(gi)
                self._string_operand(base + s, i, base + e, e - s > 2)
                pos = e
            elif gi == _G_HEX:
                s, e = m.span(gi)
                if _HEX_OK.fullmatch(buf, s, e) is None:
                    raise _Bad("a hexadecimal string with a non-hex character")
                self._string_operand(base + s, i, base + e, bool(buf[s + 1 : e - 1].strip(_WS_BYTES)))
                pos = e
            elif gi == _G_NEST:
                s = m.start(_G_NEST)
                end = _skip_string(buf, s, self._poll)
                if end is None:
                    raise _Bad("unterminated string")
                self._string_operand(base + s, i, base + end, end - s > 2)
                pos = end
            elif gi == _G_DICT or (gi == _G_BR and buf[m.start(_G_BR)] == 0x5B):
                s = m.start(gi)
                self.cstack = [b"<<" if gi == _G_DICT else b"["]
                self.cn = [0]
                self.c_numeric = True
                self.ckind = _DICT if gi == _G_DICT else _ARR
                self.cstart, self.cstream, self.ccount = base + s, i, 0
                end = self._container(buf, m.end(gi))
                if end is None:
                    return None  # the buffer ended inside the container; it continues in the next stream
                self._finish_container(base + end)
                pos = end
            elif gi == _G_BR:
                raise _Bad(f"stray {chr(buf[m.start(_G_BR)])!r}")
            elif gi == _G_BADHEX:
                raise _Bad("unterminated hex string")
            else:
                raise _Bad(f"stray {chr(buf[m.start(_G_STRAY)])!r}")

    def _string_operand(self, start: int, stream: int, end: int, nonempty: bool) -> None:
        self._add_operand(_STR, start, stream, end)
        if nonempty:
            self.data = True
        if self.blk is not None:
            self.blk[4] = False  # a string is not on the inert allowlist

    def _element(self, stack: list[bytes], numeric: bool, is_name: bool) -> None:
        """One element of the container being walked: the typed-container bookkeeping (a dash array is all numbers,
        a dictionary alternates names and values)."""
        top = stack[-1]
        if top == b"[":
            if len(stack) == 1 and not numeric:
                self.c_numeric = False
        else:
            n = self.cn[-1] + 1
            self.cn[-1] = n
            if n & 1 and not is_name:
                raise _Bad("a dictionary key that is not a name")  # MuPDF: syntax error (probe 2026-11-23)

    def _finish_container(self, end: int) -> None:
        kind = self.ckind
        if kind is _ARR and self.c_numeric:
            kind = _ARR_NUM
        self._add_operand(kind, self.cstart, self.cstream, end)
        if self.ckind is _DICT and self.blk is not None:
            self.blk[4] = False  # a dictionary is not on the inert allowlist

    def _container(self, buf: bytes, pos: int) -> int | None:
        """Walk tokens inside the open container; the offset after its closer, or ``None`` at the end of the buffer.

        The stack of openers lives on ``self`` so that a container may continue in the next stream.
        """
        stack = self.cstack
        match = _TOKEN.match
        n_tok = 0
        while True:
            m = match(buf, pos)
            if m is None:
                raise _Bad("lexer stalled")
            gi = m.lastindex
            n_tok += 1
            if not n_tok & _TICK:
                self._tick(self.base + pos)
            if gi == _G_WORD or gi == _G_NAME or gi == _G_STR:
                self.ccount += 1
                if gi == _G_WORD:
                    s, e = m.span(gi)
                    if buf[s] not in _NUM_START or _NUM.fullmatch(buf, s, e) is None:
                        self._element(stack, False, False)
                    else:
                        self._element(stack, True, False)
                else:
                    if gi == _G_STR and m.end(gi) - m.start(gi) > 2:
                        self.data = True
                    self._element(stack, False, gi == _G_NAME)
                pos = m.end()
            elif gi == _G_CMT:
                pos = m.end()
                if pos == len(buf):
                    self.in_cmt = True
            elif gi == _G_END:
                return None
            elif gi == _G_HEX:
                s, e = m.span(gi)
                if _HEX_OK.fullmatch(buf, s, e) is None:
                    raise _Bad("a hexadecimal string with a non-hex character")
                self.ccount += 1
                if buf[s + 1 : e - 1].strip(_WS_BYTES):
                    self.data = True
                self._element(stack, False, False)
                pos = e
            elif gi == _G_NEST:
                end = _skip_string(buf, m.start(_G_NEST), self._poll)
                if end is None:
                    raise _Bad("unterminated string")
                self.ccount += 1
                if end - m.start(_G_NEST) > 2:
                    self.data = True
                self._element(stack, False, False)
                pos = end
            elif gi == _G_DICT:
                self.ccount += 1
                self._element(stack, False, False)
                stack.append(b"<<")
                self.cn.append(0)
                pos = m.end()
            elif gi == _G_BR:
                s = m.start(_G_BR)
                ch = buf[s]
                pos = s + 1
                if ch == 0x5B:
                    self.ccount += 1
                    self._element(stack, False, False)
                    stack.append(b"[")
                    self.cn.append(0)
                elif ch == 0x5D and stack[-1] == b"[":
                    stack.pop()
                    self.cn.pop()
                    if not stack:
                        return pos
                else:
                    raise _Bad(f"mismatched {chr(ch)!r} inside an array or dictionary")
            elif gi == _G_STRAY:
                s = m.start(_G_STRAY)
                if buf[s] == 0x3E and buf[s + 1 : s + 2] == b">" and stack[-1] == b"<<":
                    if self.cn[-1] & 1:
                        raise _Bad("a dictionary with a key and no value")  # MuPDF: syntax error (probe 2026-11-23)
                    stack.pop()
                    self.cn.pop()
                    pos = s + 2
                    if not stack:
                        return pos
                else:
                    raise _Bad(f"stray {chr(buf[s])!r} inside an array or dictionary")
            else:
                raise _Bad("unterminated hex string")
            if len(stack) > MAX_NEST:
                raise _Bad(f"arrays and dictionaries nested deeper than {MAX_NEST}")
            if self.ccount > MAX_ARRAY_ELEMENTS:
                raise _Bad(f"more than {MAX_ARRAY_ELEMENTS} elements in one array or dictionary")

    # -- operators --------------------------------------------------------------------------------

    def _check_operands(self, op: bytes) -> None:
        ops = self.ops
        n = _FLOAT_ARITY.get(op)
        if n is not None:  # the common case: numbers only
            if len(ops) != n or self.n_other:
                raise _Bad(f"operator {op.decode('latin-1')} expects {n} numbers, got {len(ops)} operands")
            return
        spec = _ARITY.get(op)
        if spec is not None:
            if len(ops) != len(spec):
                raise _Bad(f"operator {op.decode('latin-1')} expects {len(spec)} operands, got {len(ops)}")
            for o, kind in zip(ops, spec, strict=True):
                if not isinstance(o, kind):
                    raise _Bad(f"operator {op.decode('latin-1')} got an operand of the wrong kind")
        elif op in _VARCOLOR:
            numeric = ops[:-1] if op in (b"scn", b"SCN") and ops and isinstance(ops[-1], bytes) else ops
            if not all(type(o) is float for o in numeric):
                raise _Bad(f"operator {op.decode('latin-1')} got an operand of the wrong kind")

    def _operator(self, op: bytes, ts: int, te: int) -> None:
        ops = self.ops
        blk = self.blk
        self._check_operands(op)
        if self.open and op not in _PATH_OPS:
            self.impure = True
        if blk is not None and op in _RESOURCE_OPS and ops and isinstance(ops[-1], bytes):
            blk[11].append((op, _decode_name(ops[-1])))  # type: ignore[arg-type]
        if blk is not None and blk[4] and op not in _INERT_OPS and op != b"q" and op != b"Q":
            blk[4] = False
        if op in _CONSTRUCT:
            self._construct(op, ts)
            return
        code = _PAINT_CODE.get(op)
        if code is not None:
            self._paint(op, code, te)
            return
        if op == b"q":
            self._push(ts)
        elif op == b"Q":
            self._pop(te)
        elif op == b"cm":
            self.ctm = affine_concat(tuple(ops), self.ctm)  # type: ignore[arg-type]
            self.tot = affine_concat(self.ctm, self.frame)
            if not all(-_F32_MAX <= v <= _F32_MAX for v in (*self.ctm, *self.tot)):
                raise _Bad("a CTM that is not finite or beyond float32 range")
            if blk is not None:
                blk[5] += 1
                same = self.opnd_stream == self.stream
                if blk[5] == 1:
                    blk[6], blk[7] = (self.opnd_start, self.last_end) if same else (-1, -1)
                if not same:
                    blk[4] = False
        elif op == b"w":
            self.width = float(ops[0])  # type: ignore[arg-type]
        elif op == b"J":
            self.cap = float(ops[0])  # type: ignore[arg-type]
        elif op == b"gs":
            self.gs = True
            self.cap = math.nan
            self.width = math.nan  # /ExtGState may set /LW: unknown until the next w or the restoring Q
        elif op == b"W" or op == b"W*":
            if self.open:
                self.has_w = True
            else:
                self.pending_w = True  # belongs to the next painted path
        elif op == b"cs" or op == b"CS":
            non_device = _decode_name(ops[0]) not in _DEVICE_SPACES  # type: ignore[arg-type]
            if op == b"cs":
                self.cs_fill = non_device
            else:
                self.cs_stroke = non_device
        elif op == b"scn" or op == b"SCN":
            if ops and isinstance(ops[-1], bytes):  # a pattern name
                if op == b"scn":
                    self.cs_fill = True
                else:
                    self.cs_stroke = True
        elif op == b"g" or op == b"rg" or op == b"k":
            self.cs_fill = False
        elif op == b"G" or op == b"RG" or op == b"K":
            self.cs_stroke = False
        elif op == b"Tr":
            mode = ops[0]
            if mode != int(mode) or not 0 <= mode <= 7:  # type: ignore[call-overload,operator]
                raise _Bad(f"operator Tr got the render mode {mode}")
            self.tr = int(mode)  # type: ignore[call-overload]
        elif op == b"BT":
            self.in_text = True  # a nested BT does not clear a pending clip (probe 2026-11-23, MuPDF 1.27)
        elif op in _SHOW_OPS:
            if self.tr >= 4 and self.data:
                self.text_clip = True  # text with character data shown under a clip mode joins the clip at ET (probe: '() Tj', '<> Tj', '[] TJ' and '[10] TJ' do not)
        elif op == b"ET":
            self.in_text = False
            if self.text_clip:
                self.clipped = True
                self.text_clip = False
        elif op == b"BDC":
            is_oc = _decode_name(ops[0]) == b"/OC"  # type: ignore[arg-type]
            self.mc.append(is_oc)
            self.oc_count += is_oc
        elif op == b"BMC":
            self.mc.append(False)
        elif op == b"EMC":
            if not self.mc:
                raise _Bad("EMC below marked-content depth 0")
            self.oc_count -= self.mc.pop()

    def _push(self, ts: int) -> None:
        if self.blk is not None:
            self.blk[2] = True  # the parent is no longer a leaf
        self.stack.append((self.ctm, self.tot, self.clipped, self.gs, self.cs_fill, self.cs_stroke, self.width, self.tr, self.blk, self.cap))
        # [q_start, q_stream, has_child, n_paints, inert, n_cm, cm_a, cm_b, n_records, path ids, open at q]
        self.blk = [ts, self.stream, False, 0, True, 0, -1, -1, 0, [], self.open, []]
        if self.open:
            self.blk[4] = False

    def _pop(self, te: int) -> None:
        if not self.stack:
            raise _Bad("Q below depth 0")
        blk = self.blk
        assert blk is not None
        self.text_clip = False  # a Q discards the pending text clip (probe: 'BT 7 Tr (X) Tj q Q ET' clips nothing)
        if not blk[2]:  # a leaf pair is a block
            n = blk[3]
            inert = bool(blk[4]) and not blk[10] and not self.open and n >= 1 and blk[8] == n and blk[1] == self.stream
            index = len(self.b_rows)
            self.b_rows.append((blk[0], te, n, inert, blk[5], blk[6], blk[7]))
            self.b_res.append(tuple(blk[11]))
            for pid in blk[9]:
                self.c_block[pid] = index
        (self.ctm, self.tot, self.clipped, self.gs, self.cs_fill, self.cs_stroke, self.width, self.tr, self.blk, self.cap) = self.stack.pop()  # type: ignore[assignment]

    # -- paths ------------------------------------------------------------------------------------

    def _begin(self, ts: int) -> None:
        self.open = True
        if self.opnd_start >= 0:
            self.p_start, self.p_stream = self.opnd_start, self.opnd_stream  # the record starts at its first operand, in ITS stream
        else:
            self.p_start, self.p_stream = ts, self.stream
        self.prims = []
        self.dots = []
        self.sub_seg = False
        self.cur = None
        self.sub = None
        self.sp = -1
        self.pt0 = None
        self.impure = self.in_text  # a path constructed inside BT ... ET is not editable
        self.has_w = self.pending_w
        self.pending_w = False
        self.oc_start = self.oc_count > 0

    def _construct(self, op: bytes, ts: int) -> None:
        ops = self.ops
        if not self.open:
            self._begin(ts)
        prims = self.prims
        if self.nseg + len(prims) >= MAX_SEGMENT_ROWS:
            raise VectorPageRefused("TOO_LARGE", f"more than {MAX_SEGMENT_ROWS} segment rows")
        if op == b"m":
            self.cur = self.sub = (ops[0], ops[1])  # type: ignore[assignment]
            self.sub_seg = False
            self.sp += 1
            if self.pt0 is None:
                self.pt0 = self.cur
        elif op == b"l":
            if self.cur is None:
                raise _Bad("l needs a current point")
            x, y = ops[0], ops[1]
            prims.append((self.cur[0], self.cur[1], x, y, max(self.sp, 0)))  # type: ignore[arg-type]
            self.cur = (x, y)  # type: ignore[assignment]
            self.sub_seg = True
        elif op == b"c" or op == b"v" or op == b"y":
            if self.cur is None:
                raise _Bad(f"{op.decode()} needs a current point")
            p0 = self.cur
            if op == b"c":
                p1, p2, p3 = (ops[0], ops[1]), (ops[2], ops[3]), (ops[4], ops[5])
            elif op == b"v":
                p1, p2, p3 = p0, (ops[0], ops[1]), (ops[2], ops[3])
            else:
                p1, p2, p3 = (ops[0], ops[1]), (ops[2], ops[3]), (ops[2], ops[3])
            prims.append((*p0, *p1, *p2, *p3, max(self.sp, 0)))  # type: ignore[arg-type]
            self.cur = p3  # type: ignore[assignment]
            self.sub_seg = True
        elif op == b"re":
            x, y, w, h = ops
            self.sp += 1
            sp = self.sp
            c = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]  # type: ignore[operator]
            for k in range(4):
                prims.append((*c[k], *c[(k + 1) % 4], sp))
            self.cur = self.sub = (x, y)  # type: ignore[assignment]
            self.sub_seg = True
            if self.pt0 is None:
                self.pt0 = self.cur
        else:  # h
            self._close()

    def _close(self) -> None:
        if self.cur is not None and self.sub is not None:
            if self.cur != self.sub:
                self.prims.append((self.cur[0], self.cur[1], self.sub[0], self.sub[1], max(self.sp, 0)))
                self.cur = self.sub
                self.sub_seg = True
            elif not self.sub_seg:
                self.dots.append(self.sub)  # 'x y m h': a closed zero-length subpath; MuPDF paints a round-cap dot there (probe)

    def _flush_lines(self) -> None:
        if self.line_buf:
            self.seg_chunks.append(np.array(self.line_buf, dtype=np.float64))
            self.line_buf = []
            self._poll()

    def _paint(self, op: bytes, code: int, te: int) -> None:
        self.n_paints += 1
        if self.n_paints > MAX_PAINTS:
            raise VectorPageRefused("TOO_LARGE", f"more than {MAX_PAINTS} paint operators")
        blk = self.blk
        if blk is not None:
            blk[3] += 1
        if not self.open:
            if self.pending_w:  # W n with no path: the clip still takes effect (nothing is drawn, no record)
                self.clipped = True
                self.pending_w = False
            return  # a paint with no path under construction draws nothing and makes no record
        if op in _CLOSE_PAINTS:
            self._close()
        pid = len(self.c_start)
        seg_start = self.nseg
        a, b, c, d, e, f = self.tot
        lim = _F32_MAX
        bx0 = by0 = math.inf
        bx1 = by1 = -math.inf
        buf = self.line_buf
        for pr in self.prims:
            if len(pr) == 5:
                x0, y0, x1, y1, sp = pr
                px0, py0 = x0 * a + y0 * c + e, x0 * b + y0 * d + f
                px1, py1 = x1 * a + y1 * c + e, x1 * b + y1 * d + f
                if not (-lim <= px0 <= lim and -lim <= py0 <= lim and -lim <= px1 <= lim and -lim <= py1 <= lim):
                    raise _Bad("a path coordinate that is not finite or beyond float32 range")
                if px0 < bx0:
                    bx0 = px0
                if px1 < bx0:
                    bx0 = px1
                if py0 < by0:
                    by0 = py0
                if py1 < by0:
                    by0 = py1
                if px0 > bx1:
                    bx1 = px0
                if px1 > bx1:
                    bx1 = px1
                if py0 > by1:
                    by1 = py0
                if py1 > by1:
                    by1 = py1
                buf.append((px0, py0, px1, py1, pid, 0.0, sp))
                self.nseg += 1
                if len(buf) >= _FLUSH_ROWS:
                    self._flush_lines()
                    buf = self.line_buf
            else:
                pts: list[float] = []
                for k in range(0, 8, 2):
                    px, py = pr[k] * a + pr[k + 1] * c + e, pr[k] * b + pr[k + 1] * d + f
                    if not (-lim <= px <= lim and -lim <= py <= lim):
                        raise _Bad("a path coordinate that is not finite or beyond float32 range")
                    pts.append(px)
                    pts.append(py)
                    if px < bx0:
                        bx0 = px
                    if px > bx1:
                        bx1 = px
                    if py < by0:
                        by0 = py
                    if py > by1:
                        by1 = py
                self._flush_lines()
                self._chords(tuple(pts), pid, int(pr[8]))
                buf = self.line_buf
        round_dots = op in _STROKE_PAINTS and self.cap == 1.0 and bool(self.prims)  # a lone "m h" paints nothing
        for k, (x, y) in enumerate(self.dots):  # a zero-length closed subpath in a mixed path still paints a dot under a round cap
            dx, dy = x * a + y * c + e, x * b + y * d + f
            if not (-lim <= dx <= lim and -lim <= dy <= lim):
                raise _Bad("a path coordinate that is not finite or beyond float32 range")
            if round_dots:
                self.dot_rows.append((pid, k, dx, dy))
            bx0, bx1, by0, by1 = min(bx0, dx), max(bx1, dx), min(by0, dy), max(by1, dy)
        ctm = self.ctm
        det = ctm[0] * ctm[3] - ctm[1] * ctm[2]
        flags = 0
        if self.impure or self.in_text:
            flags |= _FL_IMPURE
        if self.has_w:
            flags |= _FL_SETS_CLIP
        if self.clipped:
            flags |= _FL_CLIPPED
        if self.p_stream != self.stream:
            flags |= _FL_SPANS_STREAMS
        if self.oc_count > 0 or self.oc_start:
            flags |= _FL_IN_OC
        if not abs(det) > _SINGULAR_DET:
            flags |= _FL_CTM_SINGULAR
        if self.gs or self.cs_fill or self.cs_stroke:
            flags |= _FL_PAGE_ANCHORED
        if not self.prims:
            flags |= _FL_DEGENERATE
            x, y = self.pt0 if self.pt0 is not None else (0.0, 0.0)  # keep the transformed point (11)
            bx0 = bx1 = x * a + y * c + e
            by0 = by1 = x * b + y * d + f
            if not (-lim <= bx0 <= lim and -lim <= by0 <= lim):
                raise _Bad("a path coordinate that is not finite or beyond float32 range")
        if op != b"n" and not flags & (
            _FL_IMPURE | _FL_SETS_CLIP | _FL_SPANS_STREAMS | _FL_IN_OC | _FL_CTM_SINGULAR
        ):
            flags |= _FL_EDITABLE
        # the conservative page-space width: w times the larger singular value of the CTM composed with the frame
        sigma = math.hypot((a + d) / 2, (b - c) / 2) + math.hypot((a - d) / 2, (b + c) / 2)
        width = abs(self.width) * sigma
        if width > lim:  # saturating would lose the nominal width (line_width / sigma); the honest answer is a refusal
            raise _Bad("a line width beyond float32 range in page space")
        self.c_start.append(self.p_start)
        self.c_end.append(te)
        self.c_block.append(-1)
        self.c_paint.append(code)
        self.c_flags.append(int(flags))
        self.c_bbox.append([bx0, by0, bx1, by1])
        self.c_width.append(width)
        self.c_ctm.append(ctm)
        self.c_sstart.append(seg_start)
        self.c_scount.append(self.nseg - seg_start)
        if blk is not None:
            blk[9].append(pid)
            if self.p_start > blk[0]:
                blk[8] += 1
        self.open = False
        self.prims = []
        if self.has_w:
            self.clipped = True  # the clip takes effect after the paint operator
        self.has_w = False

    def _chords(self, pr: tuple[float, ...], pid: int, sp: int) -> None:
        """Flatten one cubic (page space) into equal-parameter chords: n = ceil(sqrt(0.75 M / eps))."""
        d1 = math.hypot(pr[0] - 2 * pr[2] + pr[4], pr[1] - 2 * pr[3] + pr[5])
        d2 = math.hypot(pr[2] - 2 * pr[4] + pr[6], pr[3] - 2 * pr[5] + pr[7])
        arg = 0.75 * max(d1, d2) / CHORD_EPSILON  # finite: every coordinate is inside float32 range
        remaining = MAX_CHORD_ROWS - self.chords
        if remaining < 1 or arg > float(remaining) ** 2:  # compared BEFORE the square root and the ceiling
            raise VectorPageRefused("CHORD_CAP", f"more than {MAX_CHORD_ROWS} chord rows")
        count = max(1, math.ceil(math.sqrt(arg)))
        if count > remaining:
            raise VectorPageRefused("CHORD_CAP", f"more than {MAX_CHORD_ROWS} chord rows")
        self._poll()
        self.chords += count
        p = np.array(pr, dtype=np.float64).reshape(4, 2)
        verts = np.empty((count + 1, 2), dtype=np.float64)
        verts[0], verts[count] = p[0], p[3]
        if count > 1:
            t = np.arange(1, count, dtype=np.float64) / count
            u = 1.0 - t
            verts[1:count] = (u * u * u)[:, None] * p[0] + (3 * u * u * t)[:, None] * p[1] + (3 * u * t * t)[:, None] * p[2] + (t * t * t)[:, None] * p[3]
        chunk = np.empty((count, 7), dtype=np.float64)
        chunk[:, 0:2] = verts[:-1]
        chunk[:, 2:4] = verts[1:]
        chunk[:, 4] = pid
        chunk[:, 5] = 1.0
        chunk[:, 6] = sp
        self.seg_chunks.append(chunk)
        self.cb_pts.append(pr)
        self.cb_path.append(pid)
        self.cb_start.append(self.nseg)
        self.cb_count.append(count)
        self.nseg += count

    # -- tables -----------------------------------------------------------------------------------

    def _build(self, starts: list[int], stopped: bool, indexed_end: int) -> VectorIndex:
        self._poll()
        self._flush_lines()
        n = len(self.c_start)
        paths = np.zeros(n, dtype=_PATH_DT)
        if n:
            paths["path_start"] = self.c_start
            paths["paint_end"] = self.c_end
            paths["block"] = self.c_block
            paths["paint"] = self.c_paint
            paths["flags"] = self.c_flags
            bb64 = np.array(self.c_bbox, dtype=np.float64)
            bb = bb64.astype(np.float32)
            fmax = np.float32(_F32_MAX)
            lo, hi = -fmax, fmax  # the targets are the finite extremes: a value at the float32 maximum stays there, never inf
            bb[:, 0:2] = np.nextafter(bb[:, 0:2], lo)  # widened outward by one float32 step: it can only over-include
            bb[:, 2:4] = np.nextafter(bb[:, 2:4], hi)
            paths["bbox"] = bb
            w64 = np.array(self.c_width, dtype=np.float64)
            w32 = w64.astype(np.float32)
            below = w32.astype(np.float64) < w64  # float32 rounding must never round a width down (NaN compares false)
            w32[below] = np.minimum(np.nextafter(w32[below], hi), fmax)
            paths["line_width"] = w32
            paths["ctm"] = np.array(self.c_ctm, dtype=np.float64)
            paths["seg_start"] = self.c_sstart
            paths["seg_count"] = self.c_scount
        self._poll()
        if self.seg_chunks:
            raw = np.concatenate(self.seg_chunks)
        else:
            raw = np.zeros((0, 7), dtype=np.float64)
        self._poll()
        segments = np.zeros(len(raw), dtype=_SEG_DT)
        segments["x0"], segments["y0"], segments["x1"], segments["y1"] = raw[:, 0], raw[:, 1], raw[:, 2], raw[:, 3]
        segments["path"] = raw[:, 4].astype(np.int32)
        segments["from_cubic"] = raw[:, 5] != 0.0
        segments["subpath"] = raw[:, 6].astype(np.int32)
        cubics = np.zeros(len(self.cb_pts), dtype=_CUBIC_DT)
        if len(self.cb_pts):
            cubics["pts"] = np.array(self.cb_pts, dtype=np.float64)
            cubics["path"] = self.cb_path
            cubics["seg_start"] = self.cb_start
            cubics["seg_count"] = self.cb_count
        blocks = np.zeros(len(self.b_rows), dtype=_BLOCK_DT)
        for k, row in enumerate(self.b_rows):
            blocks[k] = row  # type: ignore[call-overload]
            if not k & 0xFFF:
                self._poll()
        table = np.zeros(len(self.streams), dtype=_STREAM_DT)
        for k, s in enumerate(self.streams):
            table[k] = (-1, starts[k], len(s), b"")  # xref and raw_key are re-bound from the live page (D15)
        self._poll()
        digests = tuple(hashlib.sha256(s).digest() for s in self.streams)
        dots = np.zeros(len(self.dot_rows), dtype=_DOT_DT)
        for k, (dp, ds, dx, dy) in enumerate(self.dot_rows):
            dots[k] = (dp, ds, dx, dy)
        nbytes = int(paths.nbytes + cubics.nbytes + segments.nbytes + blocks.nbytes + table.nbytes + dots.nbytes)
        self._poll()
        return VectorIndex(paths, cubics, segments, blocks, table, indexed_end, stopped, self.frame, digests, nbytes, tuple(self.b_res), dots=dots)


def _cumulative(streams: Sequence[bytes], base: int) -> list[int]:
    out = []
    for s in streams:
        out.append(base)
        base += len(s)
    return out


# ----------------------------------------------------------------------------- entry point


def _check_streams(streams: object) -> tuple[bytes, ...]:
    """Bytes only (no bytearray, no memoryview); every length is charged BEFORE anything is copied or kept."""
    if isinstance(streams, (bytes, bytearray, memoryview, str)) or not isinstance(streams, Sequence):
        raise TypeError(f"streams must be a sequence of bytes, not {type(streams).__name__}")
    out: list[bytes] = []
    total = 0
    for k, s in enumerate(streams):
        if not isinstance(s, bytes):
            raise TypeError(f"stream {k} must be bytes, not {type(s).__name__}")
        total += len(s)
        if total > MAX_DECODED_BYTES:
            raise VectorPageRefused("TOO_LARGE", f"{total} decoded bytes exceed {MAX_DECODED_BYTES}")
        out.append(s)
    return tuple(out)


def _check_frame(frame: object) -> Frame:
    if frame is None:
        raise VectorPageRefused("NO_FRAME", "the page frame cannot be proved")
    if isinstance(frame, (str, bytes)) or not isinstance(frame, Sequence) or len(frame) != 6:
        raise TypeError("frame must be six numbers")
    if not all(isinstance(v, numbers.Real) and not isinstance(v, bool) for v in frame):
        raise TypeError("frame must be six numbers")
    f = tuple(float(v) for v in frame)
    if not all(math.isfinite(v) for v in f) or not abs(f[0] * f[3] - f[1] * f[2]) > _SINGULAR_DET:
        raise VectorPageRefused("NO_FRAME", "the page frame is not finite and invertible")
    if not all(-_F32_MAX <= v <= _F32_MAX for v in f):  # the initial frame is subject to the same range as every composed CTM
        raise VectorPageRefused("NO_FRAME", "the page frame is beyond float32 range")
    return f  # type: ignore[return-value]


def scan_page(
    streams: Sequence[bytes],
    frame: Frame,
    *,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    accelerated: bool = False,
) -> VectorIndex:
    """Index the decoded content streams of one page (scanner G; ``accelerated=True`` waits for card B4)."""
    for name, fn in (("cancel", cancel), ("progress", progress)):
        if fn is not None and not callable(fn):
            raise TypeError(f"{name} must be callable")
    data = _check_streams(streams)
    fr = _check_frame(frame)
    if accelerated:
        from model.vector_paths import scan_fast

        fast = scan_fast.run(data, fr, cancel, progress)
        if fast is not None:
            return fast
    try:
        index = _Scanner(data, fr, cancel, progress).run()
        index.scanner, index.accelerated = "G", False
        return index
    except _Bad as exc:  # the scanner's own parsing only; a callback's exception propagates unchanged
        raise VectorPageRefused("SCAN_ERROR", str(exc)) from None
