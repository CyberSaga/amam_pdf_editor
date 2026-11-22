from __future__ import annotations

import math
import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass

import fitz

import hashlib

from model import content_scan
from model.content_scan import (
    _CONTENT_OPERATORS,
    StreamScan,
    cached_scan,
    content_key,
    iter_token_spans,
    scan_stream,
    store_scan,
)
from model.geometry import rect_from_points
from model.text_commit.transforms import page_visual_frame_or_none

# A stream at or under this many decoded bytes is scanned in-process; a longer one goes to the
# object-probe child (card A5, H16).
INLINE_SCAN_LIMIT_BYTES = 131072
# Bounds on what routing decodes in the parent (A8, A9).  A stream whose decoded size would pass
# STREAM_DECODE_CAP_BYTES, or the page's streams together passing PAGE_DECODE_CAP_BYTES, is never
# decoded here: the page reports no native image in it, as for a stream whose scan failed.
STREAM_DECODE_CAP_BYTES = 8 * 1024 * 1024
PAGE_DECODE_CAP_BYTES = 32 * 1024 * 1024
_MAX_FLATE_STAGES = 4  # a longer Flate chain is no honest content stream: over the cap
# Object ids of a partial discovery (a stream skipped, so the walk's numbering is not the full one)
# are numbered from here up: no writer resolves them (the full numbering never reaches it).
PARTIAL_OCCURRENCE_BASE = 1_000_000


@dataclass(frozen=True)
class ContentToken:
    raw: bytes


@dataclass(frozen=True)
class ParsedOperator:
    name: str
    operands: tuple[ContentToken, ...]
    operand_start: int
    operator_index: int


@dataclass(frozen=True)
class NativeImageInvocation:
    page_num: int
    occurrence_index: int
    stream_xref: int
    xobject_name: str
    xref: int
    bbox: fitz.Rect
    rotation: float
    cm_operator_index: int | None
    do_operator_index: int
    q_operator_index: int | None
    q_end_operator_index: int | None
    q_image_invocation_count: int
    # xref whose /Resources/XObject holds ``xobject_name`` — the page for direct
    # invocations, the Form XObject for form-nested ones. Used for resource pruning.
    resource_owner_xref: int = 0
    # True when the image is drawn inside a Form XObject rather than directly on
    # the page; the rewrite path then works in the form's coordinate space.
    is_form_nested: bool = False
    # Byte spans in the invocation's decoded stream (CAD card A5, H17); None when not recorded.
    do_span: tuple[int, int] | None = None
    cm_span: tuple[int, int] | None = None
    q_span: tuple[int, int] | None = None


def tokenize_content_stream(stream: bytes) -> list[ContentToken]:
    return [ContentToken(stream[s:e]) for s, e in iter_token_spans(stream)]


def parse_operators(stream: bytes) -> tuple[list[ContentToken], list[ParsedOperator]]:
    tokens = tokenize_content_stream(stream)
    operators: list[ParsedOperator] = []
    operands: list[ContentToken] = []
    operand_start = 0
    for index, token in enumerate(tokens):
        token_text = token.raw.decode("latin-1")
        if token_text in _CONTENT_OPERATORS:
            operators.append(
                ParsedOperator(
                    name=token_text,
                    operands=tuple(operands),
                    operand_start=operand_start,
                    operator_index=index,
                )
            )
            operands = []
            operand_start = index + 1
        else:
            if not operands:
                operand_start = index
            operands.append(token)
    return tokens, operators


def _rotation_from_cm(a: float, b: float, c: float, d: float) -> float:
    """Rotation angle (degrees, 0–360) of an image cm, from its first basis axis.

    Returns the true angle so free (non-90°) rotations survive re-discovery, but
    snaps to the nearest cardinal within 0.5° so the legacy 90° "fit to rect"
    path and float noise from transforms keep producing exact 0/90/180/270.
    """
    angle = math.degrees(math.atan2(b, a)) % 360.0
    for cardinal in (0.0, 90.0, 180.0, 270.0, 360.0):
        if abs(angle - cardinal) <= 0.5:
            return cardinal % 360.0
    return round(angle, 2)


def format_cm_value(value: float) -> bytes:
    """Format a cm component for a PDF content stream.

    ``f"{v:g}"`` emits scientific notation (e.g. ``1.2e-14``) for the near-zero
    values that trig produces, which PDF tokenizers reject. Clamp tiny values to
    zero and use fixed-point.
    """
    if abs(value) < 1e-9:
        value = 0.0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return (text if text not in ("", "-0") else "0").encode("ascii")


def decompose_image_cm(
    cm_values: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float]:
    """Recover (width, height, angle_deg, centre_x, centre_y_user) from an image cm.

    The cm maps the image unit square into user space; the basis-vector lengths
    are the on-page width/height, ``atan2`` of the first basis gives the angle,
    and the transform of (0.5, 0.5) is the centre (in PDF user space, y-up).
    """
    a, b, c, d, e, f = cm_values
    width = math.hypot(a, b)
    height = math.hypot(c, d)
    angle = math.degrees(math.atan2(b, a)) % 360.0
    centre_x = 0.5 * a + 0.5 * c + e
    centre_y_user = 0.5 * b + 0.5 * d + f
    return width, height, angle, centre_x, centre_y_user


AffineMatrix = tuple[float, float, float, float, float, float]


def affine_concat(first: AffineMatrix, then: AffineMatrix) -> AffineMatrix:
    """``first`` followed by ``then`` (PDF row-vector order), in Python floats.

    ``fitz.Matrix`` products, inverses and ``Point * Matrix`` round through
    float32 (MEASURED, 1.27.1: 114.80241827 -> 114.80242157), so image cm
    geometry is composed here instead.
    """
    a, b, c, d, e, f = first
    a2, b2, c2, d2, e2, f2 = then
    return (
        a * a2 + b * c2,
        a * b2 + b * d2,
        c * a2 + d * c2,
        c * b2 + d * d2,
        e * a2 + f * c2 + e2,
        e * b2 + f * d2 + f2,
    )


def affine_invert(matrix: AffineMatrix) -> AffineMatrix:
    """Inverse of a non-singular affine matrix, in Python floats."""
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    return (
        d / det,
        -b / det,
        -c / det,
        a / det,
        (c * f - d * e) / det,
        (b * e - a * f) / det,
    )


def affine_point(matrix: AffineMatrix, x: float, y: float) -> tuple[float, float]:
    """``(x, y)`` mapped through ``matrix`` (row vector), in Python floats."""
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def page_user_space_matrix(page: fitz.Page) -> AffineMatrix | None:
    """PDF user space -> unrotated page space (the space of ``get_image_rects``).

    The single chokepoint for image geometry (F15-G2). It is
    ``PageVisualFrame.base``: the ``/UserUnit`` scale, the y flip against the
    clipped CropBox's ``y1`` and its origin. Never rebuild it from
    ``page.mediabox.height`` and ``page.cropbox``: that flip is off by
    ``MediaBox.y0`` and drops ``/UserUnit``. ``page.transformation_matrix`` is
    no substitute either (it drops both on a ``/Rotate`` page).

    ``None`` when the frame cannot be proven (a non-quarter ``/Rotate``, an
    empty clipped CropBox, an unusable ``/UserUnit``); callers then fall back
    to MuPDF's own placement rects and refuse to write a ``cm``.
    """
    frame = page_visual_frame_or_none(page)
    if frame is None:
        return None
    base = frame.base
    return (
        float(base.a),
        float(base.b),
        float(base.c),
        float(base.d),
        float(base.e),
        float(base.f),
    )


def rotated_image_stream_cm(
    centre_x: float,
    centre_y_user: float,
    width: float,
    height: float,
    angle_deg: float,
) -> list[bytes]:
    """Build an image cm that places a ``width``×``height`` image rotated about
    its centre by ``angle_deg`` (screen clockwise) at the given centre.

    Everything is in PDF USER space (y up, user units): the caller maps a
    page-space centre and size through ``affine_invert(page_user_space_matrix(page))``
    first (F15-G2). The angle is negated so a positive (screen-clockwise) angle reads
    back as the same value via :func:`_rotation_from_cm`.
    """
    theta = math.radians(angle_deg)
    # Sign chosen so the *raw* cm reads back as ``angle_deg`` via _rotation_from_cm
    # (the page-level discovery convention). The rendered image is y-flipped, so
    # the view maps screen-clockwise drags to the matching stored angle.
    matrix = fitz.Matrix(width, 0.0, 0.0, height, 0.0, 0.0)
    matrix = matrix * fitz.Matrix(1.0, 0.0, 0.0, 1.0, -width / 2.0, -height / 2.0)
    matrix = matrix * fitz.Matrix(
        math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta), 0.0, 0.0
    )
    matrix = matrix * fitz.Matrix(1.0, 0.0, 0.0, 1.0, centre_x, centre_y_user)
    return [
        format_cm_value(value)
        for value in (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
    ]


def _cm_values_from_operands(operands: tuple[ContentToken, ...]) -> tuple[float, float, float, float, float, float] | None:
    if len(operands) < 6:
        return None
    raw_values = operands[-6:]
    try:
        return tuple(float(token.raw.decode("latin-1")) for token in raw_values)  # type: ignore[return-value]
    except Exception:
        return None


def _bbox_from_stream_cm(
    cm: tuple[float, float, float, float, float, float],
    user_to_page: AffineMatrix,
) -> fitz.Rect:
    """Page-space bbox of the image unit square placed by ``cm``.

    ``user_to_page`` is :func:`page_user_space_matrix`; the result is in the
    same space as ``page.get_image_rects``.
    """
    placement = affine_concat(cm, user_to_page)
    corners = (
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
    )
    return rect_from_points([fitz.Point(*affine_point(placement, x, y)) for x, y in corners])


def cm_placement_matches_hit(
    doc: fitz.Document, invocation: NativeImageInvocation, cm_values: tuple[float, ...] | None
) -> bool:
    """False only when the ``cm`` the stream's own lex gives for the invocation places the image
    somewhere other than the hit's bbox (the hit named a different placement than the one about to
    be edited).  True when the hit's bbox did not come from its own ``cm`` (no ``cm``, a Form
    XObject, or a page frame discovery could not prove): nothing to compare there."""
    if invocation.is_form_nested or cm_values is None or not 1 <= invocation.page_num <= len(doc):
        return True
    user_to_page = page_user_space_matrix(doc[invocation.page_num - 1])
    if user_to_page is None:
        return True
    expected = _bbox_from_stream_cm(cm_values, user_to_page)  # type: ignore[arg-type]
    got = fitz.Rect(invocation.bbox)
    return all(abs(a - b) < 1e-6 for a, b in zip(tuple(expected), tuple(got)))


def _stream_dict_text(doc: fitz.Document, xref: int) -> str:
    try:
        from utils.pdf_object_source import xref_object_exact

        return xref_object_exact(doc, xref, compressed=False)
    except Exception:
        return ""


def _cached_scan_by_alias(doc: fitz.Document, xref: int) -> tuple[StreamScan | None, tuple[bytes, str] | None]:
    """The cached scan for the stream's raw bytes and dictionary, without decoding it, and the
    alias to record once it is scanned (``None`` when the dictionary holds an indirect reference)."""
    try:
        raw = doc.xref_stream_raw(xref)
    except Exception:
        return None, None
    if raw is None:
        return None, None
    dict_text = _stream_dict_text(doc, xref)
    if not dict_text or not content_scan.alias_usable(dict_text):
        return None, None
    alias = content_scan.alias_key(raw, dict_text)
    key = content_scan.lookup_alias(alias)
    return (cached_scan(key) if key is not None else None), alias


def stream_and_scan(doc: fitz.Document, xref: int) -> tuple[bytes, StreamScan]:
    """The decoded stream and its scan (cached by content, H18).  Always answers."""
    stream = doc.xref_stream(xref) or b""
    key = content_key(stream)
    scan = cached_scan(key)
    if scan is None:
        scan = scan_stream(stream)
        store_scan(key, scan)
    return stream, scan


def stream_scan(doc: fitz.Document, xref: int) -> StreamScan:
    """The scan of one content stream: alias hit, else decode and key, else scan and store."""
    scan, alias = _cached_scan_by_alias(doc, xref)
    if scan is not None:
        return scan
    stream, scan = stream_and_scan(doc, xref)
    if alias is not None:
        content_scan.store_alias(alias, content_key(stream))
    return scan


_FILTER_NAME_RE = re.compile(r"/[^\s/\[\]()<>{}%]+")


def _parse_filter_names(value: str) -> list[str] | None:
    """The names of a ``/Filter`` value (``/Name``, ``[/A /B]`` or MuPDF's ``[/A/B]``), or ``None``
    when anything but names, brackets and whitespace is in it."""
    body = value.strip()
    if body.startswith("["):
        if not body.endswith("]"):
            return None
        body = body[1:-1]
    names = _FILTER_NAME_RE.findall(body)
    if _FILTER_NAME_RE.sub("", body).strip():
        return None
    return names


def _resolved_object_text(doc: fitz.Document, value: str) -> str | None:
    """The text of the object an indirect ``/Filter`` points at (``"12 0 R"``), else ``None``."""
    parts = value.split()
    if len(parts) != 3 or parts[2] != "R" or not parts[0].isdigit():
        return None
    try:
        from utils.pdf_object_source import xref_object_exact

        return xref_object_exact(doc, int(parts[0]), compressed=True)
    except Exception:
        return None


def _bounded_stream(doc: fitz.Document, xref: int, room: int) -> bytes | None:
    """The decoded stream, or ``None`` when decoding it would pass ``room`` bytes (nothing decoded then).

    The size is learned before the decode (the approach of ``text_index_jobs._decoded_length``): the
    stored size first, then a plain single Flate stream is inflated with a cap of ``room + 1`` bytes.
    A stream within the room is decoded by ``xref_stream`` as before, so what discovery reads is
    unchanged.  Only chains whose size the parent can bound before decoding are decoded: no filter
    at all, or a chain of Flate stages (any ``/DecodeParms``: a predictor never expands its input, so
    the inflated size bounds its output too), each stage inflated with a cap of ``room + 1`` bytes.
    Every other chain (LZW, ASCII filters, an unreadable ``/Filter`` ...) is over the cap: it is
    never decoded here, whatever its stored size."""
    raw = doc.xref_stream_raw(xref) or b""
    if len(raw) > room:
        return None
    kind, value = doc.xref_get_key(xref, "Filter")
    if kind == "xref":
        resolved = _resolved_object_text(doc, value)
        if resolved is None:
            return None  # an indirect Filter that cannot be read: not bounded
        value, kind = resolved, "array"
    if kind not in ("null", "name", "array"):
        return None  # a Filter the reader cannot name: not bounded
    names = _parse_filter_names(value) if kind in ("name", "array") else []
    if names is None:
        return None  # not a plain list of names (an element reference, a string ...): not bounded
    if names:
        if len(names) > _MAX_FLATE_STAGES or any(n not in ("/FlateDecode", "/Fl") for n in names):
            return None
        data = bytes(raw)
        try:
            for _stage in names:
                data = zlib.decompressobj().decompress(data, room + 1)
                if len(data) > room:
                    return None
        except zlib.error:
            return None  # a failed capped inflate is over the cap: never an uncapped MuPDF decode
    elif doc.xref_get_key(xref, "DecodeParms")[0] != "null":
        return None  # parameters without a filter: not a shape this path knows
    return doc.xref_stream(xref) or b""


def _scan_for_discovery(
    doc: fitz.Document,
    xref: int,
    members: dict[bytes, StreamScan],
    skip: frozenset[bytes] = frozenset(),
    budget: list[int] | None = None,
) -> StreamScan | None:
    """``stream_scan`` for discovery: every scan it uses is collected into ``members`` (the caller
    admits the page's scans as one set); ``None`` for a stream in ``skip`` (the page's scan failed
    in the child: the page then reports no native image in it).  ``budget`` is the page's running
    decoded byte total (one cell, shared by the walk of the page): the same page bound as
    :func:`_scan_set_walk`, so a stream the walk refused is never decoded here either."""
    scan, alias = _cached_scan_by_alias(doc, xref)
    if scan is not None:
        if budget is not None:
            budget[0] += scan.length  # the same page bound whether or not the stream's scan is cached
        if alias is not None:
            known = content_scan.lookup_alias(alias)
            if known is not None:
                members[known] = scan
        return scan
    room =STREAM_DECODE_CAP_BYTES if budget is None else min(STREAM_DECODE_CAP_BYTES, PAGE_DECODE_CAP_BYTES - budget[0])
    bounded = _bounded_stream(doc, xref, room) if room >= 0 else None
    if bounded is None:
        return None  # never decoded here: reported like a stream whose scan failed (A8)
    stream = bounded
    if budget is not None:
        budget[0] += len(stream)
    key = content_key(stream)
    scan = cached_scan(key)
    if scan is None:
        if key in skip:
            return None  # the child handled or refused it: never scanned on the caller thread (F4/F6)
        scan = scan_stream(stream)
        content_scan.store_verified(key, scan)  # lexed in this process: a writer need not lex it again
    members[key] = scan
    if alias is not None:
        content_scan.store_alias(alias, key)
    return scan


def _image_bearing_form_xrefs(doc: fitz.Document, page: fitz.Page) -> list[int]:
    """The page-level Form XObjects whose own resources hold an image (the form loop's filter)."""
    try:
        form_xobjects = page.get_xobjects()
        images_by_referencer: dict[int, bool] = {}
        for row in page.get_images(full=True):
            images_by_referencer[int(row[9])] = True
    except Exception:
        return []
    result: list[int] = []
    seen: set[int] = set()
    for xobj in form_xobjects:
        form_xref = int(xobj[0])
        if form_xref in seen:
            continue
        seen.add(form_xref)
        try:
            subtype = doc.xref_get_key(form_xref, "Subtype")
        except Exception:
            continue
        if isinstance(subtype, tuple) and subtype[1] == "/Form" and images_by_referencer.get(form_xref):
            result.append(form_xref)
    return result


def _scan_set_walk(
    doc: fitz.Document, page_num: int
) -> tuple[tuple[bytes, ...], list[tuple[bytes, bytes]], dict[bytes, bytes], tuple[bytes, ...]]:
    """``(set key, jobs, short, limited)`` of one page: the walk behind :func:`page_scan_set`.

    ``short`` is ``content key -> decoded stream`` of each member with no cached scan that is at
    most ``INLINE_SCAN_LIMIT_BYTES`` long (the ones discovery would scan in-process); they are
    already decoded here, so admitting the page's set can count them without a second decode.
    ``limited`` is the set keys of the members over the decode cap (never decoded, never scanned)."""
    if page_num < 1 or page_num > len(doc):
        return (), [], {}, ()
    page = doc[page_num - 1]
    if not page.get_images(full=True):
        return (), [], {}, ()
    limited: list[bytes] = []
    xrefs = [int(x) for x in page.get_contents() if int(x) > 0]
    xrefs.extend(_image_bearing_form_xrefs(doc, page))
    set_key: list[bytes] = []
    jobs: list[tuple[bytes, bytes]] = []
    short: dict[bytes, bytes] = {}
    seen: set[bytes] = set()
    decoded_total = 0
    for xref in xrefs:
        scan, alias = _cached_scan_by_alias(doc, xref)
        if scan is not None and alias is not None:
            known = content_scan.lookup_alias(alias)
            if known is not None:
                decoded_total += scan.length  # a cached stream counts toward the page bound like any other
                if known not in seen:
                    seen.add(known)
                    set_key.append(known)
                continue
        try:
            room = min(STREAM_DECODE_CAP_BYTES, PAGE_DECODE_CAP_BYTES - decoded_total)
            stream = _bounded_stream(doc, xref, room) if room >= 0 else None
            if stream is None:
                # over the bound: never decoded; the stream still belongs to the set (keyed by its
                # stored bytes) so a failure frame covers it, and discovery reports nothing in it
                key = hashlib.blake2b(doc.xref_stream_raw(xref) or b"", digest_size=16, person=b"scan-oversize").digest()
                if key not in seen:
                    seen.add(key)
                    set_key.append(key)
                    limited.append(key)
                continue
        except Exception:
            continue
        decoded_total += len(stream)
        key = content_key(stream)
        if key in seen:
            continue
        seen.add(key)
        set_key.append(key)
        if cached_scan(key) is not None:
            if alias is not None:
                content_scan.store_alias(alias, key)
            continue
        if len(stream) > INLINE_SCAN_LIMIT_BYTES:
            jobs.append((key, stream))
        else:
            short[key] = stream
    # The in-process share is bounded over the page's short streams together (A9): equivalent
    # content split into many streams must route like the same content in one.
    if sum(len(s) for s in short.values()) > INLINE_SCAN_LIMIT_BYTES:
        jobs.extend(short.items())
        short = {}
    return tuple(set_key), jobs, short, tuple(limited)


def page_scan_set(doc: fitz.Document, page_num: int) -> tuple[tuple[bytes, ...], list[tuple[bytes, bytes]]]:
    """``(set key, jobs)`` of one page (CAD card D12).

    The set key is the ordered tuple of distinct content keys of every stream discovery reads on
    the page (contents and image-bearing Forms, short ones included): the scans of a page are
    admitted to the cache as that set.  ``jobs`` is ``(content key, decoded stream)`` of each
    member with no cached scan that is longer than ``INLINE_SCAN_LIMIT_BYTES``.  Both are empty
    for a page without an image."""
    set_key, jobs, _short, _limited = _scan_set_walk(doc, page_num)
    return set_key, jobs


class PageScanSet:
    """One page's scan set for ONE lookup, click or answer, computed on first use and then shared.

    The walk decodes and hashes every content stream of the page (about 20 ms for a 4.3 MB one),
    so a click that asked for it four times (the lookup, the controller's pending test, the job
    request and its frame) paid that four times.  Pass one instance down the whole call, like
    ``table_objects.PageInput``.  It is a snapshot: build a new one after anything that changes
    the page's streams or the scan cache.
    """

    def __init__(self, doc: fitz.Document, page_num: int) -> None:
        self._doc = doc
        self._page_num = int(page_num)
        self._walk: (
            tuple[tuple[bytes, ...], list[tuple[bytes, bytes]], dict[bytes, bytes], tuple[bytes, ...]] | None
        ) = None

    def _load(self) -> tuple[tuple[bytes, ...], list[tuple[bytes, bytes]], dict[bytes, bytes], tuple[bytes, ...]]:
        if self._walk is None:
            self._walk = _scan_set_walk(self._doc, self._page_num)
        return self._walk

    @property
    def limited_keys(self) -> tuple[bytes, ...]:
        """Set keys of the members over the decode cap: never decoded or scanned here (F3)."""
        return self._load()[3]

    @property
    def skip_keys(self) -> frozenset[bytes]:
        """What discovery must not scan once the page's scan failed: the content key of every member
        the child was (or would be) asked for (F4/F6).  The keys of members over the cap are in it
        too, but those are hashes of the stored bytes, so they match no decoded stream: they only
        make the set non-empty (discovery then trusts no MuPDF placement offset).  The streams over
        the cap are held back by the page decode bound itself."""
        return frozenset(key for key, _stream in self._load()[1]) | frozenset(self._load()[3])

    @property
    def set_key(self) -> tuple[bytes, ...]:
        return self._load()[0]

    @property
    def jobs(self) -> list[tuple[bytes, bytes]]:
        return list(self._load()[1])

    @property
    def short_streams(self) -> dict[bytes, bytes]:
        return self._load()[2]


def image_scan_jobs(doc: fitz.Document, page_num: int) -> list[tuple[bytes, bytes]]:
    """The second half of ``page_scan_set``: the long streams of the page awaiting the child."""
    return page_scan_set(doc, page_num)[1]


def sibling_scan_keys(doc: fitz.Document, page_num: int, own_key: bytes) -> frozenset[bytes]:
    """The page's other set members: the keys a derived store must not evict."""
    return frozenset(page_scan_set(doc, page_num)[0]) - {own_key}


class _LazyPlacements:
    """MuPDF's image placements of one page, loaded per xref on first use (CAD card D10).

    ``page.get_image_rects`` hashes the pixmap of every image on the page (PyMuPDF forces
    ``hashes=True``), so a discovery whose records all carry their own ``cm`` in a proven page
    frame must not call it.  ``xrefs`` is the set discovery may place at all (the page-wide
    name table's values); any other xref has no placements.  Each xref is loaded at most once.

    ``offset`` is the next placement an xref's record takes.  A record that needs none (a
    direct ``cm`` in a proven frame) still passes through :meth:`consume`: before the load it
    is only counted, and the load starts the offset at ``min(count, len(placements))``, which
    is what the eager loop's capped increment reached; after it the capped increment goes on.
    """

    def __init__(self, page: fitz.Page, xrefs: set[int]) -> None:
        self._page = page
        self._xrefs = xrefs
        self._loaded: dict[int, list[tuple[fitz.Rect, fitz.Matrix]]] = {}
        self._offsets: dict[int, int] = {}
        self._counted: dict[int, int] = {}

    def placements(self, xref: int) -> list[tuple[fitz.Rect, fitz.Matrix]]:
        """The xref's placements in drawing order; loads them on the first call."""
        loaded = self._loaded.get(xref)
        if loaded is None:
            loaded = []
            if xref in self._xrefs:
                loaded = [
                    (fitz.Rect(rect), matrix) for rect, matrix in self._page.get_image_rects(xref, transform=True)
                ]
            self._loaded[xref] = loaded
            self._offsets[xref] = min(self._counted.pop(xref, 0), len(loaded))
        return loaded

    # With a skip (a failed page's long streams are not read) MuPDF's per-xref placement list counts
    # draws this walk never sees, so no offset is trustworthy: set before the walk (a skipped Form
    # is walked after the page streams but may draw first), the no-cm hits are dropped.
    unreliable = False

    def offset(self, xref: int) -> int:
        """The index of the next placement for ``xref``; ``placements(xref)`` was called."""
        return self._offsets[xref]

    def consume(self, xref: int) -> None:
        """One record of ``xref`` has taken its place in the drawing order."""
        loaded = self._loaded.get(xref)
        if loaded is None:
            self._counted[xref] = self._counted.get(xref, 0) + 1
        elif self._offsets[xref] < len(loaded):
            self._offsets[xref] += 1


def discover_native_image_invocations(
    doc: fitz.Document,
    page_num: int,
    skip: frozenset[bytes] = frozenset(),
    on_set_refused: Callable[[], None] | None = None,
) -> list[NativeImageInvocation]:
    """The page's native image placements.  The scans it reads or makes are admitted once, as the
    page's set, at the end; ``skip`` names the content keys of streams the child handled or refused
    (they report nothing, and are never scanned here: :meth:`PageScanSet.skip_keys`).
    ``on_set_refused`` is called when the set does not fit the cache (D12): the caller records the
    page ``resource_limited`` so that no later call scans it again.

    MuPDF's placements (``get_image_rects``) are loaded only by a record that consumes them: no
    ``cm``, an unprovable page frame, or a Form XObject (CAD card D10)."""
    page = doc[page_num - 1]
    if not page.get_images(full=True):
        return []
    members: dict[bytes, StreamScan] = {}
    user_to_page = page_user_space_matrix(page)
    image_name_to_xref = {str(image[7]): int(image[0]) for image in page.get_images(full=True)}
    lazy = _LazyPlacements(page, set(image_name_to_xref.values()))
    lazy.unreliable = bool(skip)
    invocations: list[NativeImageInvocation] = []
    occurrence_index = 0
    budget = [0]  # the page's decoded bytes so far (the walk's PAGE_DECODE_CAP_BYTES bound)
    for stream_xref in [int(xref) for xref in page.get_contents() if int(xref) > 0]:
        scan = _scan_for_discovery(doc, stream_xref, members, skip, budget)
        if scan is None:
            occurrence_index = max(occurrence_index, PARTIAL_OCCURRENCE_BASE)  # numbering is no longer the full one
            continue
        for record in scan.dos:
            image_name = record.name
            if image_name not in image_name_to_xref:
                continue
            xref = image_name_to_xref[image_name]
            cm_index = record.cm_operator_index
            cm_values = record.cm_values
            bbox: fitz.Rect | None = None
            rotation = 0.0
            if cm_values is not None:
                if user_to_page is not None:
                    bbox = _bbox_from_stream_cm(cm_values, user_to_page)
                else:
                    # Unprovable page frame: report MuPDF's own placement; the
                    # cm writers refuse on this page (page_user_space_matrix).
                    if lazy.unreliable:
                        occurrence_index = max(occurrence_index, PARTIAL_OCCURRENCE_BASE)
                        continue
                    placements = lazy.placements(xref)
                    placement_index = lazy.offset(xref)
                    if placement_index >= len(placements):
                        continue
                    bbox = fitz.Rect(placements[placement_index][0])
                rotation = _rotation_from_cm(cm_values[0], cm_values[1], cm_values[2], cm_values[3])
                lazy.consume(xref)
            else:
                if lazy.unreliable:
                    occurrence_index = max(occurrence_index, PARTIAL_OCCURRENCE_BASE)
                    continue
                placements = lazy.placements(xref)
                placement_index = lazy.offset(xref)
                if placement_index >= len(placements):
                    continue
                bbox, transform = placements[placement_index]
                lazy.consume(xref)
                rotation = _rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            invocations.append(
                NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=stream_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=cm_index,
                    do_operator_index=record.do_operator_index,
                    q_operator_index=record.q_operator_index,
                    q_end_operator_index=record.q_end_operator_index,
                    q_image_invocation_count=record.q_do_count,
                    resource_owner_xref=int(page.xref),
                    is_form_nested=False,
                    do_span=record.do_span,
                    cm_span=record.cm_span,
                    q_span=record.q_span,
                )
            )
            occurrence_index += 1

    occurrence_index = _discover_form_nested_invocations(
        doc,
        page,
        page_num,
        lazy,
        invocations,
        occurrence_index,
        members,
        skip,
        budget,
    )
    if members and not content_scan.admit_set(members):  # one set, never one scan at a time (D12)
        if on_set_refused is not None:
            on_set_refused()
    return invocations


def _discover_form_nested_invocations(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
    lazy: _LazyPlacements,
    invocations: list[NativeImageInvocation],
    occurrence_index: int,
    members: dict[bytes, StreamScan],
    skip: frozenset[bytes] = frozenset(),
    budget: list[int] | None = None,
) -> int:
    """Discover image ``Do`` invocations that live inside Form XObjects.

    Many PDFs (e.g. exported from layout tools) wrap page content — including
    images — in a Form XObject, so the page content stream only contains
    ``/Fm0 Do`` and the image is invoked one level down. We walk each page-level
    form's stream, resolve image names against that form's own resources, and
    reuse the page-space placement from ``get_image_rects`` for the bbox.
    Depth-1 only (forms referenced directly by the page), which covers the
    common case. A PDF with no image-bearing forms is unaffected (no-op).
    """
    try:
        form_xobjects = page.get_xobjects()
    except Exception:
        return occurrence_index

    # Per-form image-name → xref maps, keyed by the referencing (form) xref.
    images_by_referencer: dict[int, dict[str, int]] = {}
    try:
        for row in page.get_images(full=True):
            referencer = int(row[9])
            images_by_referencer.setdefault(referencer, {})[str(row[7])] = int(row[0])
    except Exception:
        return occurrence_index

    processed_forms: set[int] = set()
    for xobj in form_xobjects:
        form_xref = int(xobj[0])
        if form_xref in processed_forms:
            continue
        processed_forms.add(form_xref)
        try:
            subtype = doc.xref_get_key(form_xref, "Subtype")
        except Exception:
            continue
        if not (isinstance(subtype, tuple) and subtype[1] == "/Form"):
            continue
        form_images = images_by_referencer.get(form_xref)
        if not form_images:
            continue
        try:
            scan = _scan_for_discovery(doc, form_xref, members, skip, budget)
        except Exception:
            continue
        if scan is None:
            occurrence_index = max(occurrence_index, PARTIAL_OCCURRENCE_BASE)
            continue
        for record in scan.dos:
            image_name = record.name
            if image_name not in form_images:
                continue
            xref = form_images[image_name]
            if lazy.unreliable:
                occurrence_index = max(occurrence_index, PARTIAL_OCCURRENCE_BASE)
                continue
            placements = lazy.placements(xref)
            placement_index = lazy.offset(xref)
            if placement_index >= len(placements):
                continue
            bbox, transform = placements[placement_index]
            lazy.consume(xref)
            rotation = _rotation_from_cm(transform.a, transform.b, transform.c, transform.d)
            invocations.append(
                NativeImageInvocation(
                    page_num=page_num,
                    occurrence_index=occurrence_index,
                    stream_xref=form_xref,
                    xobject_name=image_name,
                    xref=xref,
                    bbox=fitz.Rect(bbox),
                    rotation=rotation,
                    cm_operator_index=record.cm_operator_index,
                    do_operator_index=record.do_operator_index,
                    q_operator_index=record.q_operator_index,
                    q_end_operator_index=record.q_end_operator_index,
                    q_image_invocation_count=record.q_do_count,
                    resource_owner_xref=form_xref,
                    is_form_nested=True,
                    do_span=record.do_span,
                    cm_span=record.cm_span,
                    q_span=record.q_span,
                )
            )
            occurrence_index += 1
    return occurrence_index


def replace_operator_operands(tokens: list[ContentToken], operator: ParsedOperator, new_operands: list[bytes]) -> bytes:
    start = operator.operand_start
    end = operator.operator_index
    replacement = [ContentToken(raw=value) for value in new_operands]
    rewritten = tokens[:start] + replacement + tokens[end:]
    return serialize_tokens(rewritten)


def remove_operator_range(tokens: list[ContentToken], start_token: int, end_token: int) -> bytes:
    rewritten = tokens[:start_token] + tokens[end_token + 1 :]
    return serialize_tokens(rewritten)


def serialize_tokens(tokens: list[ContentToken]) -> bytes:
    if not tokens:
        return b"\n"
    return b"\n".join(token.raw for token in tokens) + b"\n"


def fitz_rect_to_stream_cm(rect: fitz.Rect, page: fitz.Page, rotation: float) -> list[bytes] | None:
    """The image ``cm`` that draws the image into page-space ``rect``.

    ``rotation`` is the image's cardinal rotation (0/90/180/270). The placement
    is built in page space (y down) and mapped back to user space through
    ``affine_invert(page_user_space_matrix(page))``, which carries the CropBox/MediaBox
    origin and ``/UserUnit`` (F15-G2). ``None`` when the page frame cannot be
    proven: the caller must refuse rather than write a guessed ``cm``.
    """
    user_to_page = page_user_space_matrix(page)
    if user_to_page is None:
        return None
    bbox = fitz.Rect(rect)
    width = float(bbox.width)
    height = float(bbox.height)
    x0, y0, x1, y1 = float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)
    turn = rotation % 360
    placement: AffineMatrix
    if turn == 0:
        placement = (width, 0.0, 0.0, -height, x0, y1)
    elif turn == 90:
        placement = (0.0, -height, -width, 0.0, x1, y1)
    elif turn == 180:
        placement = (-width, 0.0, 0.0, height, x1, y0)
    else:
        placement = (0.0, height, width, 0.0, x0, y0)
    cm = affine_concat(placement, affine_invert(user_to_page))
    return [format_cm_value(value) for value in cm]


def form_rect_to_stream_cm(
    destination_rect: fitz.Rect,
    current_cm_values: tuple[float, float, float, float, float, float],
    current_page_bbox: fitz.Rect,
    rotation: float,
) -> list[bytes] | None:
    """Build a new ``cm`` for an image drawn inside a Form XObject.

    The image's cm lives in the *form's* coordinate space, which reaches page
    space through an outer placement transform (the page ``cm`` before
    ``/Fm Do`` composed with the form ``Matrix``). Rather than reconstruct that
    transform from document internals, we recover the affine placement
    empirically from the correspondence between the *current* form-space cm and
    the *current* page-space bbox, then invert it for the destination rect.

    Only axis-aligned, non-rotated placements/images are supported (the common
    Form-wrapper case). Returns None for rotated/sheared images so the caller can
    refuse the edit rather than corrupt the page.
    """
    a, b, c, d, e, f = current_cm_values
    eps = 1e-6
    # Reject shear/rotation in the image cm, and rotation of the placement
    # itself (handled by demanding the current invocation be un-rotated).
    if abs(b) > eps or abs(c) > eps or rotation % 360 != 0:
        return None
    if abs(a) < eps or abs(d) < eps:
        return None

    old = fitz.Rect(current_page_bbox)
    if old.width <= eps or old.height <= eps:
        return None

    # Placement scale/translate with the page y-flip folded in:
    #   page.x = sx * form.x + tx ,  page.y_top = -sy * form.y_top + ty
    # derived from the current correspondence (image occupies [e, e+a]×[f, f+d]
    # in form space and ``old`` in page space, page coords being y-down).
    sx = old.width / a
    sy = old.height / d
    tx = old.x0 - sx * e
    ty = old.y1 + sy * f

    dest = fitz.Rect(destination_rect)
    new_a = dest.width / sx
    new_d = dest.height / sy
    new_e = (dest.x0 - tx) / sx
    new_f = (ty - dest.y1) / sy
    values = (new_a, 0.0, 0.0, new_d, new_e, new_f)
    return [format_cm_value(value) for value in values]
