"""Source binding: map visible text to its content-stream operator.

Binds a target string to exactly one replayed show operation, corroborated
by rawdict geometry.  Anything ambiguous, malformed, out-of-page-stream,
or in unsupported text state returns a :class:`BindingFailure` with a
stable :class:`~model.text_commit.dto.RejectReason` code — never a
best-score guess (plan Task 3).

``EditableSpan``/rawdict data are geometric *hints* only; the binding's
identity is (page xref, stream xref, digest, byte ranges).
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

import fitz

from model.text_commit.cid_fonts import (
    CidCapabilityFailure,
    PdfParseError,
    PdfRef,
    canonical_pdf_scalar,
    canonical_pdf_text,
    parse_pdf_value,
)
from model.text_commit.dto import RejectReason
from model.text_commit.evidence import (
    PageStreamSnapshot,
    ResolvedPageStreams,
    compute_evidence_key,
)
from model.text_commit.fonts import DocumentFontRegistry, FontCapability
from model.text_commit.marked_content import (
    resolve_default_visibility,
    update_marked_content_dependencies,
)
from model.text_commit.transforms import (
    PageVisualFrame,
    admission_verdict,
    page_visual_frame_or_none,
)
from model.text_commit.replay import (
    McWrapper,
    PageReplay,
    ShowOp,
    replay_page_streams,
)
from utils.pymupdf_refs import forget_walked_annot

logger = logging.getLogger(__name__)

# Task 13 P2 (§10 privacy): one fixed, code-only detail per trm_* refusal —
# never a matrix coefficient, which can fingerprint a private document's
# producer pipeline.
_TRM_REJECT_DETAILS = {
    RejectReason.TRM_NON_FINITE: (
        "combined text/transform matrix has non-finite components"
    ),
    RejectReason.TRM_SINGULAR: "combined text/transform matrix is singular",
    RejectReason.TRM_SCALE_BELOW_FLOOR: (
        "combined text/transform matrix baseline scale is below the "
        "absolute floor"
    ),
    RejectReason.TRM_REFLECTED: (
        "combined text/transform matrix has negative orientation "
        "(reflection)"
    ),
    # Emitted by the planner (plan._build_tier0/_build_tier1), never by the
    # binder; listed here so every trm_* code has its one fixed detail.
    RejectReason.TRM_REFLECTED_ADVANCE_CHANGE: (
        "combined text/transform matrix is a reflection, which is admitted "
        "only as an exactly equal-advance string-operand splice"
    ),
    RejectReason.TRM_SHEARED: (
        "combined text/transform matrix has non-orthogonal axes (shear)"
    ),
    RejectReason.TRM_NON_UNIFORM_SCALE: (
        "combined text/transform matrix scales its axes unequally"
    ),
    RejectReason.TRM_ROTATION_NOT_QUARTER_TURN: (
        "combined text/transform matrix rotation is not a visual "
        "quarter turn"
    ),
}


@dataclass(frozen=True)
class SourceSpanBinding:
    """A verified, unambiguous mapping from target text to one show op."""

    page_xref: int
    stream_xref: int
    stream_digest: str  # SHA-256 of the bound stream's decoded bytes
    show: ShowOp
    # Visual (pixmap) page space -- transformation_matrix * rotation_matrix,
    # NOT raw page.get_text('rawdict') convention (that stays unrotated).
    origin_page: tuple[float, float]
    # Task 13 P1: the show's marked-content stack resolved against
    # ``PageReplay.mc_wrappers`` (outermost-first) plus the page's EMC
    # underflow count -- the evidence ``plan.py``'s admission gate folds.
    mc_wrappers: tuple[McWrapper, ...] = ()
    mc_emc_underflows: int = 0


@dataclass(frozen=True)
class BindingFailure:
    reason: str  # a RejectReason constant
    detail: str


def read_page_streams(
    doc: fitz.Document, page: fitz.Page
) -> list[tuple[int, bytes]]:
    """Ordered ``(xref, decoded_bytes)`` list of the page's content streams."""
    return [(xref, doc.xref_stream(xref) or b"") for xref in page.get_contents()]


def capture_page_streams(
    doc: fitz.Document, page: fitz.Page
) -> PageStreamSnapshot:
    """The ONE decoded content-stream read of a P3-B prepare.

    Reads the ordered streams once and derives the invalidation key from
    exactly those bytes -- the fresh-read + digest half of the lookup-time
    pull-validation contract (``model.text_commit.evidence``).
    """
    streams = tuple(read_page_streams(doc, page))
    return PageStreamSnapshot(
        page_xref=page.xref,
        streams=streams,
        key=compute_evidence_key(page.xref, streams),
    )


# Font dictionary keys whose values feed Tier 0 capability classification:
# the width table and the code range that indexes it, the encoding that
# decides simple-ness, and the descriptor carrying the glyph-repertoire
# attestation.  Each may be an indirect object.
_FONT_DEPENDENCY_KEYS = (
    "Widths",
    "FirstChar",
    "LastChar",
    "Encoding",
    "FontDescriptor",
)

def _indirect_target(doc: fitz.Document, xref: int, key: str) -> int | None:
    """The xref ``key`` points at, or ``None`` when it is not indirect."""
    kind, value = doc.xref_get_key(xref, key)
    if kind != "xref":
        return None
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return None


def _canonical_object_digest(doc: fitz.Document, xref: int) -> bytes:
    # doc.xref_object()'s key order is not stable across a
    # tobytes(encryption=KEEP) round trip on a disk-loaded *dictionary*
    # object (MuPDF re-serializes with a different dict key order, same
    # keys/values), so hash the structured key/value API instead, sorted
    # for order-independence. Arrays/scalars/strings have no keys to
    # reorder (xref_get_keys is [] for them too, indistinguishable from an
    # empty dict) and are not observed to reformat across the round trip,
    # so fall back to the raw object string rather than silently hashing
    # nothing -- e.g. an indirect /Widths array must still be covered.
    #
    # Each value folds through ``canonical_pdf_scalar`` (plan §2.A): the
    # structured API reports an integral real as ``("float", "1")`` live and
    # ``("int", "1")`` on the scratch copy, and that kind flip alone made
    # every candidate on a page with an indirect ``/CA 1.0`` ExtGState
    # stale.  The raw fallback needs no such fold -- the serializer prints
    # the VALUE (``[ 500 250 1 .5 0 ]`` for ``[500 250.0 1.0 0.5 -0.0]``,
    # measured identical live and on scratch), never the kind.
    keys = sorted(doc.xref_get_keys(xref))
    if not keys:
        return " ".join(doc.xref_object(xref).split()).encode("utf-8")
    parts = []
    for key in keys:
        kind, value = canonical_pdf_scalar(*doc.xref_get_key(xref, key))
        parts.append(f"{key}\x1f{kind}\x1f{value}")
    return "\x1e".join(parts).encode("utf-8")


def _fold_stream(digest: "hashlib._Hash", doc: fitz.Document, xref: int) -> None:
    """Fold one stream's DECODED bytes (raw bytes are not stable across a
    ``tobytes()`` scratch round trip that recompresses)."""
    try:
        digest.update(doc.xref_stream(xref) or b"")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        digest.update(b"<unreadable-stream>")
    digest.update(b"\x1f")


def _fold_canonical_value(
    digest: "hashlib._Hash", doc: fitz.Document, kind: str, value: str
) -> None:
    """Fold one key's value in a serialization-independent form.

    Container values (dicts/arrays — most importantly the INLINE
    descendant form of ``/DescendantFonts``) are parsed and canonicalized:
    MuPDF may re-order a dictionary's keys across a ``tobytes()`` round
    trip, and hashing the raw value text would then make every live→
    scratch comparison falsely stale.  Scalars fold as ``kind:value``
    through ``canonical_pdf_scalar``, so an integral real and its integer
    respelling after the round trip fold identically (plan §2.A).
    """
    if kind in ("dict", "array"):
        try:
            canonical = canonical_pdf_text(parse_pdf_value(value))
        except PdfParseError:
            canonical = "raw:" + " ".join(value.split())
        digest.update(canonical.encode("utf-8"))
    else:
        kind, value = canonical_pdf_scalar(kind, value)
        digest.update(f"{kind}:{value}".encode("utf-8", "replace"))
    digest.update(b"\x1f")


def _update_type0_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, font_xref: int
) -> None:
    """Fold the FULL Type0 evidence closure (Task 12 P0-D).

    Mirrors exactly what ``cid_fonts.build_identity_h_cid_capability``
    reads — the auditable-enumeration rule below applies here too: the
    font dictionary itself (canonical per key), the /ToUnicode stream, the
    descendant (inline or indirect, canonical), its indirect /W and
    /FontDescriptor targets, the /CIDToGIDMap stream, and the /FontFile2
    program bytes.  Without this closure, mutating any of those between
    prepare and commit leaves the fingerprint byte-identical and a stale
    plan commits against dead width/glyph evidence.
    """
    for key in sorted(doc.xref_get_keys(font_xref)):
        kind, value = doc.xref_get_key(font_xref, key)
        digest.update(key.encode("utf-8", "replace"))
        digest.update(b"\x1d")
        _fold_canonical_value(digest, doc, kind, value)
    tounicode_target = _indirect_target(doc, font_xref, "ToUnicode")
    if tounicode_target is not None:
        _fold_stream(digest, doc, tounicode_target)

    try:
        kind, value = doc.xref_get_key(font_xref, "DescendantFonts")
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        parsed = parse_pdf_value(value)
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase, PdfParseError):
        digest.update(b"<unreadable-descendants>")
        return
    descendant: object = parsed[0] if isinstance(parsed, list) and parsed else None
    if isinstance(descendant, PdfRef):
        try:
            descendant = parse_pdf_value(doc.xref_object(descendant.xref))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
            digest.update(b"<unreadable-descendant>")
            return
    if not isinstance(descendant, dict):
        return
    # Fold the descendant canonically on EVERY arrival path, not only the
    # PdfRef one: an inline dict reached through an INDIRECT /DescendantFonts
    # array object otherwise leaves its direct /W, /DW, /CIDToGIDMap-name and
    # /Subtype values outside the fingerprint while the capability builder
    # accepts the form (post-review pin, wf_1757a5fb-8e9).  The direct-inline
    # form gets folded twice (font-dict key loop + here) — harmless, both
    # sides of a staleness comparison fold identically.
    digest.update(canonical_pdf_text(descendant).encode("utf-8"))
    digest.update(b"\x1f")
    for key in ("W", "DW", "FontDescriptor"):
        target = descendant.get(key)
        if isinstance(target, PdfRef):
            try:
                digest.update(
                    canonical_pdf_text(
                        parse_pdf_value(doc.xref_object(target.xref))
                    ).encode("utf-8")
                )
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
                digest.update(b"<unreadable-target>")
            digest.update(b"\x1f")
    cidtogid = descendant.get("CIDToGIDMap")
    if isinstance(cidtogid, PdfRef):
        _fold_stream(digest, doc, cidtogid.xref)
    descriptor = descendant.get("FontDescriptor")
    if isinstance(descriptor, PdfRef):
        try:
            descriptor = parse_pdf_value(doc.xref_object(descriptor.xref))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase, PdfParseError):
            descriptor = None
    if isinstance(descriptor, dict):
        font_file = descriptor.get("FontFile2")
        if isinstance(font_file, PdfRef):
            _fold_stream(digest, doc, font_file.xref)


def _update_font_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, font_xref: int
) -> None:
    """Fold one font's object and every indirect object it depends on.

    Enumerated rather than followed generically so the set is auditable: if
    capability classification starts reading another key, it belongs here in
    the same change, or a plan measured under the old value stays "fresh".
    """
    kind, subtype_value = doc.xref_get_key(font_xref, "Subtype")
    if kind == "name" and subtype_value == "/Type0":
        # The Type0 closure REPLACES the generic path: the generic
        # _canonical_object_digest folds the raw /DescendantFonts value
        # text, which is not serialization-stable for the inline form.
        _update_type0_dependencies(digest, doc, font_xref)
        digest.update(b"\x06")
        return
    digest.update(_canonical_object_digest(doc, font_xref))
    for key in _FONT_DEPENDENCY_KEYS:
        target = _indirect_target(doc, font_xref, key)
        if target is None:
            continue
        try:
            digest.update(_canonical_object_digest(doc, target))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable>")
            continue
    # /Flags carries the glyph-repertoire attestation and may be indirect
    # whether its descriptor is inline or an indirect object; the path form
    # resolves both shapes in one lookup.
    flags_target = _indirect_target(doc, font_xref, "FontDescriptor/Flags")
    if flags_target is not None:
        try:
            digest.update(_canonical_object_digest(doc, flags_target))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable>")
    digest.update(b"\x06")


# T16-4X S1 review M1.  A page's ``/Resources`` is INHERITABLE, so the
# effective ExtGState table can live several ``/Parent`` hops up; the bound
# matches ``plan._extgstate_resources``'s, which is the resolver the mode-2
# pen proof reads the same table through.
_MAX_RESOURCE_PARENT_HOPS = 8
_RESOURCE_READ_ERRORS = (
    RuntimeError,
    ValueError,
    IndexError,
    fitz.mupdf.FzErrorBase,
    PdfParseError,
)


def _deref_pdf_object(doc: fitz.Document, value: object, *, hops: int = 4) -> object:
    """Follow indirect-reference chains to a parsed object, bounded.

    ``plan.py`` and ``marked_content.py`` each carry the same three-line
    helper over the shared ``cid_fonts`` parser; none of the three modules
    imports another (``plan`` and ``marked_content`` both import THIS one,
    so the dependency could only ever run this way).
    """
    while isinstance(value, PdfRef) and hops > 0:
        try:
            value = parse_pdf_value(doc.xref_object(value.xref))
        except _RESOURCE_READ_ERRORS:
            return None
        hops -= 1
    return value


def _effective_extgstate(
    doc: fitz.Document, page: fitz.Page
) -> dict[str, object] | None:
    """The page's EFFECTIVE ``/Resources /ExtGState`` mapping, or ``None``.

    Deliberately the same walk as ``plan._extgstate_resources``, spelled
    twice because ``plan`` imports this module and the reverse import would
    be a cycle: ``/Resources`` is inherited all-or-nothing at the dictionary
    level (once a ``/Resources`` dict is found, a missing ``/ExtGState``
    inside it means the page HAS none, not that the search continues
    upward), and a cyclic or over-long ``/Parent`` chain is unresolvable.

    Values are parsed but NOT dereferenced: a name's binding identity is the
    :class:`PdfRef` itself, and re-pointing a name at another object has to
    move the fingerprint even when both objects already existed.
    ``test_text_commit_stroke_admission`` pins the two resolvers against
    each other on the same page, page-local and inherited.
    """
    xref = page.xref
    seen: set[int] = set()
    for _ in range(_MAX_RESOURCE_PARENT_HOPS):
        if xref in seen:
            return None  # cyclic /Parent chain
        seen.add(xref)
        try:
            node = parse_pdf_value(doc.xref_object(xref))
        except _RESOURCE_READ_ERRORS:
            return None
        if not isinstance(node, dict):
            return None
        raw_resources = node.get("Resources")
        if raw_resources is not None:
            resources = _deref_pdf_object(doc, raw_resources)
            if not isinstance(resources, dict):
                return None
            extgstate = _deref_pdf_object(doc, resources.get("ExtGState"))
            return extgstate if isinstance(extgstate, dict) else None
        parent = node.get("Parent")
        if not isinstance(parent, PdfRef):
            return None
        xref = parent.xref
    return None


def _update_extgstate_dependencies(
    digest: "hashlib._Hash", doc: fitz.Document, page: fitz.Page
) -> None:
    """Fold the page's effective ExtGState table, fonts-style (review M1).

    The mode-2 stroke-pen proof (``plan._resolve_stroke_pen``) can take the
    whole rendered pen from an ExtGState's ``/LW``/``/LJ``/``/ML``, and the
    fingerprint used to cover the FONT resource table and nothing else about
    ``/Resources``.  Rewriting ``/GS1``'s ``/LW`` from a provable 0.2 to an
    unprovable 4 therefore left the digest byte-identical, and a
    ``PreparedEdit`` cached across that rewrite committed against a stroke
    bound the page no longer justified (MEASURED: it came back
    ``COMMITTED``).

    Each name is folded with its SERIALIZED value (canonically, so a live→
    scratch round trip that re-orders an inline dictionary still matches)
    and, one level down like the font entries, with the canonical digest of
    every indirect object that value reaches -- the entry object itself when
    the name is a reference, and each of that entry's own indirect values
    (``/SMask``, ``/Font``, a soft-mask group).  One level is the same
    auditable bound the font fold uses: enumerate what the readers read, do
    not follow the graph.

    Emits NOTHING when the page declares no ExtGState names -- absent
    ``/Resources``, no ``/ExtGState``, an unreadable one, or an empty
    table.  That is load-bearing, not an optimization: this component is
    folded LAST, so a page without an ExtGState fingerprints byte-identically
    to what it did before the component existed and every pin taken on one
    stays valid.  "Unreadable" folds like "absent" for the same reason
    ``plan._extgstate_resources`` returns ``None`` for both -- the pen proof
    already REFUSES a page whose ExtGState it cannot read, so there is no
    admitted plan for a distinct sentinel to protect.
    """
    entries = _effective_extgstate(doc, page)
    if not entries:
        return
    for name in sorted(entries):
        value = entries[name]
        digest.update(name.encode("utf-8", "replace"))
        digest.update(b"\x1d")
        digest.update(canonical_pdf_text(value).encode("utf-8"))
        digest.update(b"\x1f")
        targets = [value] if isinstance(value, PdfRef) else []
        entry = _deref_pdf_object(doc, value)
        if isinstance(entry, dict):
            targets.extend(
                entry[key] for key in sorted(entry) if isinstance(entry[key], PdfRef)
            )
        for target in targets:
            assert isinstance(target, PdfRef)
            try:
                digest.update(_canonical_object_digest(doc, target.xref))
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                digest.update(b"<unreadable-extgstate-object>")
            digest.update(b"\x1f")
        digest.update(b"\x07")


def _update_page_geometry(
    digest: hashlib._Hash, doc: fitz.Document, page: fitz.Page
) -> None:
    """Fold the resolved page geometry into a fingerprint digest.

    RESOLVED values only (never raw dict shape): ``page.rotation`` /
    ``page.mediabox`` / ``page.cropbox`` resolve page-tree inheritance, so
    a direct ``/Rotate 270`` and the same value inherited from ``/Pages``
    fold identically while an ancestor mutation still changes the fold.
    ``/UserUnit`` is not inheritable; it is read off the page dict with
    one indirect hop resolved and folded as a canonical NUMBER (review
    F4): MuPDF re-serializes an integer-valued real spelling (``2.0``)
    minimally as the int ``2`` on save, so a raw ``kind:value`` fold
    would flip ``float:2`` → ``int:2`` across the live→scratch round
    trip and fail every prepare on such a document.  The live visual
    matrices are folded too:
    they are what plan/verify geometry actually consumes, so any
    divergence between serialized state and a computed view goes stale
    instead of slipping through.
    """
    try:
        kind, value = doc.xref_get_key(page.xref, "UserUnit")
        if kind == "xref":
            value = doc.xref_object(int(value.split()[0]))
        try:
            user_unit = f"num:{float(value)!r}"
        except ValueError:
            # Non-numeric (including the "null:null" absent case): the
            # raw pair is the only stable identity available.
            user_unit = f"{kind}:{value}"
    except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
        user_unit = "<unreadable-user-unit>"
    tm = page.transformation_matrix
    rm = page.rotation_matrix
    parts = (
        str(page.rotation),
        repr(tuple(page.mediabox)),
        repr(tuple(page.cropbox)),
        user_unit,
        repr((tm.a, tm.b, tm.c, tm.d, tm.e, tm.f)),
        repr((rm.a, rm.b, rm.c, rm.d, rm.e, rm.f)),
    )
    digest.update("|".join(parts).encode("utf-8"))
    digest.update(b"\x06")


def _annotation_entries(page: fitz.Page) -> list[tuple[int, tuple[float, ...]]]:
    """``[(annot.xref, tuple(annot.rect)) for annot in page.annots()]``, in O(n).

    Step 12 latency: ``page.annots()`` loads each annotation by xref, and
    PyMuPDF finds it by walking the page's annotation list, so the loop was
    O(n^2) (HVAC p5: 367 annotations, ~125 ms of the Apply rebind).  Walking
    the list once (``first_annot``/``next``) yields the same annotation
    objects (each ``next`` annotation is un-registered from its page again so
    the walk leaves no Page<->Annot reference cycle behind); the ``annots()`` order and type filter (no Link, Popup or
    Widget) come from ``annot_xrefs()`` as before, and any xref the walk did
    not reach is still loaded directly, so the entries are identical.
    """
    skip = (fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_WIDGET)
    wanted = [xref for xref, kind, _id in page.annot_xrefs() if kind not in skip]
    if not wanted:
        return []
    rects: dict[int, tuple[float, ...]] = {}
    annot = page.first_annot
    while annot is not None:
        rects[annot.xref] = tuple(annot.rect)
        following = annot.next
        if following is not None:
            # .next registers the annotation in a strong page dict while it holds
            # the page: a Page<->Annot cycle that pins the open file until the
            # cyclic GC runs (R10 MBT-1).  Cut it; the walk keeps going.
            forget_walked_annot(following)
        annot = following
    entries: list[tuple[int, tuple[float, ...]]] = []
    for xref in wanted:
        rect = rects.get(xref)
        if rect is None:
            rect = tuple(page.load_annot(xref).rect)
        entries.append((xref, rect))
    return entries


def page_fingerprint(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    streams: Sequence[tuple[int, bytes]] | None = None,
) -> str:
    """Digest of everything a Tier 0 commit promises not to disturb.

    Covers decoded content-stream bytes, the font resource table, the
    marked-content wrapper evidence closure (/Properties mapping, OCG
    objects and their resolved default visibility), annotation/widget
    identity+geometry, and — since T16-4X S1 review M1 — the effective
    /Resources /ExtGState table the mode-2 stroke-pen proof reads.  A
    prepared plan whose fingerprint no longer matches is stale and must not
    mutate anything.

    ``streams`` (P3-B) feeds the stream portion from a same-prepare
    ``capture_page_streams`` snapshot so classification hashes the very
    bytes it bound -- callers must pass the CURRENT read or nothing.
    Every non-stream dependency is always read fresh, and the apply/
    verify staleness gates keep the no-argument fresh-read form.
    """
    digest = hashlib.sha256()
    if streams is None:
        streams = read_page_streams(doc, page)
    for xref, data in streams:
        digest.update(str(xref).encode("ascii"))
        digest.update(b"\x00")
        digest.update(data)
        digest.update(b"\x01")
    for entry in page.get_fonts(full=True):
        digest.update(repr(entry).encode("utf-8"))
        digest.update(b"\x02")
        # The metadata tuple is identical whether or not the font's advance
        # or glyph contract changed, so hash the defining objects themselves —
        # including every indirect one, whose *content* can change while the
        # reference in the font dictionary stays byte-identical.
        try:
            _update_font_dependencies(digest, doc, int(entry[0]))
        except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
            digest.update(b"<unreadable-font-object>")
        digest.update(b"\x05")
    # Task 13 P1 (proof obligation 5): fold the marked-content wrapper
    # evidence closure -- the resolved /Properties mapping, its targets,
    # and each OCG's default-config visibility bit (RESOLVED shape).
    update_marked_content_dependencies(digest, doc, page)
    # Task 13 P2: fold the RESOLVED page geometry every P2 geometric proof
    # rides -- /Rotate, /MediaBox, /CropBox via PyMuPDF's inheritance-
    # resolving accessors (a page-tree ancestor mutation must go stale,
    # and a direct-vs-inherited value must fingerprint identically), the
    # page-local /UserUnit (not inheritable; one indirect hop resolved),
    # AND the live computed visual matrices (transformation x rotation),
    # so a cached-view/serialized-state divergence can never slip through.
    _update_page_geometry(digest, doc, page)
    for xref, rect in _annotation_entries(page):
        digest.update(f"{xref}:{rect}".encode("utf-8"))
        digest.update(b"\x03")
    for widget in page.widgets():
        digest.update(f"{widget.xref}:{tuple(widget.rect)}".encode("utf-8"))
        digest.update(b"\x04")
    # T16-4X S1 review M1: the ExtGState resource table, folded LAST and
    # only when the page declares one, so this component is invisible to
    # every fingerprint taken on a page without it (see
    # ``_update_extgstate_dependencies``).  It belongs here because the
    # mode-2 stroke-pen proof reads its ``/LW``/``/LJ``/``/ML``, and a
    # cached plan measured under one pen must not commit under another.
    _update_extgstate_dependencies(digest, doc, page)
    return digest.hexdigest()


# ------------------------------------------- renumbering-invariant fingerprint
#
# ``page_fingerprint`` hashes xref NUMBERS (stream xrefs, font entries, indirect
# references folded as ``R<n>``, annotation xrefs) through half a dozen helpers,
# so a ``garbage=4`` save -- which renumbers the LIVE document -- invalidates it
# by design.  Undo/redo needs to tell that apart from a genuine foreign change,
# so this is the same coverage re-expressed by CONTENT: the page object graph is
# walked with every indirect reference replaced by the referenced object's own
# canonical content (references are transparent, which also makes the digest
# immune to garbage-collection's merging of identical objects and to a direct
# vs indirect respelling), content streams are folded in /Contents order, and the
# resolved page geometry is folded exactly as ``page_fingerprint`` folds it.

_INVARIANT_MAX_OBJECTS = 20_000
_INVARIANT_MAX_DEPTH = 64
# Back-pointers that would drag the whole page tree / owning page into the walk.
# ``/Parent`` is always one.  ``/P`` is a back-pointer ONLY as an indirect
# reference (an annotation's owning page, a structure element's parent); as a
# direct value it is data -- the visibility POLICY of an OCMD (/AnyOn, /AllOff,
# ...) -- and must be hashed (round-3 N1).
_INVARIANT_SKIP_KEYS = frozenset({"Parent"})
_INVARIANT_BACKPOINTER_IF_REF_KEYS = frozenset({"P"})
# Page-level payloads page_fingerprint never covered and that can be huge.
_INVARIANT_PAGE_SKIP_KEYS = frozenset(
    {"Parent", "Contents", "Thumb", "Metadata", "PieceInfo"}
)
# Stream encoding is not content: a save may re-compress, the decoded bytes hold.
_INVARIANT_STREAM_ENCODING_KEYS = frozenset({"Length", "Filter", "DecodeParms", "DL"})
_INVARIANT_STRUCTURAL_TYPES = frozenset({"/Page", "/Pages", "/Catalog"})


class _InvariantUnprovable(Exception):
    """The page graph cannot be folded within budget; no invariant exists."""


class _ContentWalker:
    """Canonical, reference-transparent text of a PDF object graph."""

    def __init__(self, doc: fitz.Document) -> None:
        self._doc = doc
        self._memo: dict[int, str] = {}
        self._active: set[int] = set()
        self._visibility = resolve_default_visibility(doc)

    def value(self, value: object, depth: int = 0) -> str:
        if depth > _INVARIANT_MAX_DEPTH:
            raise _InvariantUnprovable("depth")
        if isinstance(value, dict):
            return "<<" + ",".join(
                f"/{key}:{self.value(item, depth + 1)}"
                for key, item in sorted(value.items())
                if not self._is_backpointer(key, item)
            ) + ">>"
        if isinstance(value, list):
            return "[" + ",".join(self.value(item, depth + 1) for item in value) + "]"
        if isinstance(value, PdfRef):
            return self._reference(value.xref, depth + 1)
        return canonical_pdf_text(value)

    @staticmethod
    def _is_backpointer(key: str, item: object) -> bool:
        return key in _INVARIANT_SKIP_KEYS or (
            key in _INVARIANT_BACKPOINTER_IF_REF_KEYS and isinstance(item, PdfRef)
        )

    def _reference(self, xref: int, depth: int) -> str:
        cached = self._memo.get(xref)
        if cached is not None:
            return cached
        if xref in self._active:
            return "<cycle>"
        if len(self._memo) >= _INVARIANT_MAX_OBJECTS:
            raise _InvariantUnprovable("budget")
        self._active.add(xref)
        try:
            text = self._object(xref, depth)
        finally:
            self._active.discard(xref)
        self._memo[xref] = text
        return text

    def _object(self, xref: int, depth: int) -> str:
        doc = self._doc
        try:
            is_stream = bool(doc.xref_is_stream(xref))
            raw = doc.xref_object(xref)
            if is_stream:
                raw = raw[: raw.rfind(">>") + 2]
            parsed = parse_pdf_value(raw)
        except _RESOURCE_READ_ERRORS as exc:
            raise _InvariantUnprovable("unreadable object") from exc
        if isinstance(parsed, dict) and parsed.get("Type") in _INVARIANT_STRUCTURAL_TYPES:
            # A link/destination reaching another page: its content is that
            # page's business, not this page's identity.
            return "<structural>"
        if is_stream:
            if not isinstance(parsed, dict):
                raise _InvariantUnprovable("stream without a dictionary")
            parsed = {
                key: item
                for key, item in parsed.items()
                if key not in _INVARIANT_STREAM_ENCODING_KEYS
            }
        text = self.value(parsed, depth)
        if is_stream:
            if isinstance(parsed, dict) and parsed.get("Subtype") == "/Image":
                # Pixels are not part of what a text edit can disturb, and
                # decoding them would dominate the cost of every commit.
                text += "<image-stream>"
            else:
                try:
                    body = doc.xref_stream(xref) or b""
                except _RESOURCE_READ_ERRORS:
                    body = b"<unreadable-stream>"
                text += "<stream:" + hashlib.sha256(body).hexdigest() + ">"
        state = self._visibility.get(xref)
        if state is not None:
            text += "<oc:on>" if state else "<oc:off>"
        return text


def _inherited_resources(doc: fitz.Document, node: dict[str, object]) -> object:
    """The page's /Resources when it is inherited from an ancestor, else
    ``None`` (the page's own entry is folded by the dictionary walk)."""
    seen: set[int] = set()
    parent = node.get("Parent")
    for _ in range(_MAX_RESOURCE_PARENT_HOPS):
        if not isinstance(parent, PdfRef) or parent.xref in seen:
            return None
        seen.add(parent.xref)
        ancestor = parse_pdf_value(doc.xref_object(parent.xref))
        if not isinstance(ancestor, dict):
            return None
        if "Resources" in ancestor:
            return ancestor["Resources"]
        parent = ancestor.get("Parent")
    return None


def renumber_invariant_page_fingerprint(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    elide_stream_xref: int | None = None,
) -> str | None:
    """Content-keyed digest of one page: equal before and after a pure
    renumbering of the document, different after any other change.

    Covers what :func:`page_fingerprint` covers -- every content stream in
    /Contents order, the resource tables (fonts and their dependency closure,
    ExtGState, the marked-content /Properties targets together with their
    default OCG visibility), annotations and widgets BY CONTENT, and the
    resolved page geometry -- plus the rest of the page's resource and
    annotation graph.  Deliberately OUTSIDE it (a text edit cannot disturb
    them, or they are too costly to fold, so a change to one is NOT detected
    on the relocation path):

    * image pixels (an ``/Subtype /Image`` stream's dictionary is folded, its
      decoded bytes are not);
    * the page's ``/Thumb``, ``/Metadata`` and ``/PieceInfo``;
    * the page tree above the page (``/Parent`` back-pointers, and any
      ``/Page``/``/Pages``/``/Catalog`` object reached through a link or
      destination, folded as an opaque ``<structural>`` marker);
    * back-pointer ``/P`` keys that are indirect references (an annotation's
      owning page); a direct ``/P`` -- an OCMD visibility policy -- IS folded;
    * any object graph larger than ``_INVARIANT_MAX_OBJECTS`` or deeper than
      ``_INVARIANT_MAX_DEPTH`` -- those return ``None`` (cannot prove), they
      are not skipped.

    ``elide_stream_xref`` replaces that one content stream's bytes with a
    placeholder at its /Contents position: undo/redo verifies the patched
    stream's exact before/after bytes separately, and one digest must hold
    for both of them.

    ``None`` means "cannot prove" (unreadable object, over the object budget,
    unsupported syntax): callers must fail closed.
    """
    try:
        node = parse_pdf_value(doc.xref_object(page.xref))
        if not isinstance(node, dict):
            return None
        walker = _ContentWalker(doc)
        digest = hashlib.sha256()
        digest.update(b"renumber-invariant-page/1\x00")
        for key in sorted(node):
            if key in _INVARIANT_PAGE_SKIP_KEYS:
                continue
            digest.update(f"/{key}:{walker.value(node[key])}".encode("utf-8"))
            digest.update(b"\x1e")
        if "Resources" not in node:
            inherited = _inherited_resources(doc, node)
            digest.update(b"<inherited-resources>")
            digest.update(walker.value(inherited).encode("utf-8"))
            digest.update(b"\x1e")
        contents = list(page.get_contents())
        digest.update(f"contents:{len(contents)}".encode("ascii"))
        for xref in contents:
            if xref == elide_stream_xref:
                digest.update(b"<elided-stream>")
            else:
                digest.update(hashlib.sha256(doc.xref_stream(xref) or b"").digest())
            digest.update(b"\x01")
        _update_page_geometry(digest, doc, page)
        return digest.hexdigest()
    except (_InvariantUnprovable, RecursionError, *_RESOURCE_READ_ERRORS) as exc:
        logger.debug(
            "renumber_invariant_page_fingerprint unprovable: %s", type(exc).__name__
        )
        return None


def capture_annotation_parent_refs(
    doc: fitz.Document, page: fitz.Page
) -> tuple[tuple[int, str], ...]:
    """Snapshot one page's annotations' full object dictionaries.

    ``fitz.Document.insert_pdf()`` mutates the copied SOURCE page's
    annotation objects as an observed side effect (a PyMuPDF quirk,
    reproduced directly with no model code involved): the ``/P``
    (parent-page) key is dropped and silently re-appended at the *end* of
    the dictionary, so a plain ``xref_get_key``/``xref_set_key`` round trip
    restores the right value but in the wrong position -- ``xref_object()``
    (and any byte-level comparison of it) still disagrees with the
    pre-copy state even though every key's value is intact. The xref, rect,
    and ``/AP`` appearance stream are never touched.

    Any call site that copies this page out of a *live* document (page-level
    undo snapshots, most notably) must back the full object string up first
    and restore it immediately after via :func:`restore_annotation_parent_refs`,
    or the live document's own annotation identity is silently disturbed by
    the mere act of copying it.
    """
    return tuple((annot.xref, doc.xref_object(annot.xref)) for annot in page.annots())


def restore_annotation_parent_refs(
    doc: fitz.Document, backup: tuple[tuple[int, str], ...]
) -> None:
    """Restore object dictionaries captured by
    :func:`capture_annotation_parent_refs`, verbatim, including key order.

    Only writes back an object that actually changed -- if the current
    object string already matches, the copy that would have disturbed it
    never ran, and this is a no-op.
    """
    for xref, object_str in backup:
        if doc.xref_object(xref) != object_str:
            doc.update_object(xref, object_str)


@dataclass(frozen=True)
class StreamStorage:
    """One content stream's exact IN-MEMORY storage.

    ``raw`` (encoded bytes as MuPDF stores them), ``obj`` (the full object
    dictionary as text, e.g. ``/Length``/``/Filter``/``/DecodeParms``), and
    ``decoded`` (the content those two together encode) -- captured by
    :func:`capture_stream_storage` and restored, byte-for-byte, by
    :func:`restore_stream_storage`. A plain ``update_stream(xref, decoded,
    compress=...)`` only ever promises the DECODED bytes back; this pair is
    for callers (``AppliedPatch.revert``, undo/redo) that must restore the
    storage ENCODING too.

    "Exact" is a statement about the live document, not about the file a
    later ``doc.save`` writes: MuPDF's serializer normalises some object
    shapes on ANY non-incremental save, whether or not anything was edited
    (MEASURED, 1.27.1: an indirect ``/Length N 0 R`` becomes a direct
    integer; an indirect ``/Filter N 0 R`` does not).  What restore
    guarantees on disk is therefore the property that matters -- an
    edit-and-revert saves BYTE-IDENTICALLY to a document that was never
    edited (pinned for all seven storage encodings by
    ``test_text_commit_exact_restore.py``).
    """

    xref: int
    raw: bytes
    obj: str
    decoded: bytes


def capture_stream_storage(doc: fitz.Document, xref: int) -> StreamStorage:
    """Snapshot ``xref``'s exact storage: raw bytes, object dict text, and
    decoded content -- the one read exact-restore needs before any mutation
    touches the stream."""
    return StreamStorage(
        xref=xref,
        raw=doc.xref_stream_raw(xref),
        obj=doc.xref_object(xref),
        decoded=doc.xref_stream(xref) or b"",
    )


def restore_stream_storage(doc: fitz.Document, storage: StreamStorage) -> bool:
    """Restore ``storage`` byte-for-byte: raw bytes, object dict, AND the
    decoded content they together encode -- never just the decoded content.

    Never raises an ordinary ``Exception``. Order is load-bearing (PITFALLS
    "Restore stream bytes before restoring the stream dictionary"): the raw
    bytes are written first with ``compress=False`` (a literal write, no
    recompression), and only THEN is the object dictionary restored over it
    -- restoring the dictionary first would leave the following
    ``update_stream`` free to rewrite ``/Length`` and drop ``/Filter`` right
    back out from under it.  A self-check after both writes (raw bytes,
    object text, AND re-decoded content, independently) confirms the restore
    actually took; on any mismatch -- or an exception from either write --
    this logs ONE WARNING and falls back to the historical lossy-but-safe
    behaviour (``update_stream(xref, decoded, compress=True)``), returning
    ``False``. A caller whose ``xref_stream_raw``/``xref_object`` already
    match (the common no-op case: nothing touched this stream since capture)
    short-circuits before any write.

    A ``BaseException`` (``KeyboardInterrupt``, ``SystemExit``) from either
    write gets the SAME fallback write and is then RE-RAISED (review "sol"
    F4).  Swallowing it would be wrong -- an interrupt must keep
    propagating -- but so is letting it out untreated: the two writes are
    not atomic, and an interrupt between them leaves the stream holding
    still-ENCODED bytes under a dictionary that no longer declares the
    filter, which is silent content loss that saves cleanly.
    ``TieredCommitEngine.commit``'s revert guard is ``except Exception``,
    so it cannot repair that either.
    """
    xref = storage.xref
    exc: BaseException | None = None
    exact_ok = False
    reraise = False
    try:
        if (
            doc.xref_stream_raw(xref) == storage.raw
            and doc.xref_object(xref) == storage.obj
        ):
            return True
        doc.update_stream(xref, storage.raw, compress=False)
        doc.update_object(xref, storage.obj)
        exact_ok = (
            doc.xref_stream_raw(xref) == storage.raw
            and doc.xref_object(xref) == storage.obj
            and doc.xref_stream(xref) == storage.decoded
        )
    except Exception as caught:  # noqa: BLE001 - must never raise; any failure falls back
        exc = caught
    except BaseException as caught:
        exc = caught
        reraise = True
    if exact_ok:
        return True
    logger.warning(
        "restore_stream_storage: exact stream-storage restore failed for "
        "xref=%s (%s); falling back to a compressed decoded-bytes restore",
        xref,
        f"{type(exc).__name__}: {exc}" if exc is not None else "self-check mismatch",
    )
    try:
        doc.update_stream(xref, storage.decoded, compress=True)
    except Exception:
        logger.warning(
            "restore_stream_storage: fallback compressed restore also "
            "raised for xref=%s; the stream may be left inconsistent",
            xref,
        )
    if reraise:
        assert exc is not None
        raise exc
    return False


_XREF_REF_RE = re.compile(r"(\d+)\s+\d+\s+R")
# A field tree larger than this is not walked to the end; the walk answers
# "signed" instead (fail-closed), exactly as it does for an unreadable node.
_MAX_FORM_FIELD_NODES = 4096


def _reference_array_xrefs(
    doc: fitz.Document, kind: str, value: str
) -> tuple[int, ...] | None:
    """The xrefs listed in an array-of-references value as ``xref_get_key``
    returned it, or ``None`` when it is not an array of references.

    Both legal ISO 32000 shapes resolve (``/Fields`` and ``/Kids`` alike):
    an inline array (``kind == "array"``) and an INDIRECT reference to an
    array object (``kind == "xref"``, e.g. ``/Fields 18 0 R`` with
    ``18 0 obj [ ]``).  The second shape is the one
    :func:`_page_contents_xrefs` below already resolves for ``/Contents``;
    treating it as "unparseable" turned every unsigned form whose producer
    wrote its ``/Fields`` indirectly into a "signed" document (R10 F10-SIG-1).

    ``()`` is a real answer (an empty array).  A reference to a stream, a
    dictionary, a freed object (reads back as ``null``) or anything else
    that is not ``[...]`` answers ``None`` -- callers fail closed.
    """
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return None
        try:
            if doc.xref_is_stream(target):
                return None
            value = doc.xref_object(target, compressed=True)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return None
    elif kind != "array":
        return None
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    return tuple(int(ref) for ref in _XREF_REF_RE.findall(text))


def _acroform_field_xrefs(doc: fitz.Document) -> tuple[int, ...] | None:
    """The xrefs in ``/Root /AcroForm /Fields``, ``()`` when the document has
    no AcroForm at all, or ``None`` when the chain could not be parsed.

    ``None`` means "cannot answer" and callers must fail closed, matching
    :func:`_page_contents_xrefs` above.

    ``/Fields`` is read BY KEY (``xref_get_key`` path ``AcroForm/Fields``),
    which follows an inline and an indirect ``/AcroForm`` alike.  It used to
    be regex-matched out of an inline dictionary's serialization, which both
    missed ``/Fields N 0 R`` and could match a nested sub-dictionary's own
    ``/Fields`` key (e.g. inside ``/DR``) instead of the form's -- walking the
    wrong objects and answering "unsigned" for a signed document.
    """
    kind, value = doc.xref_get_key(-1, "Root")
    if kind != "xref":
        return None
    try:
        root_xref = int(value.split()[0])
    except (ValueError, IndexError):
        return None
    kind, _ = doc.xref_get_key(root_xref, "AcroForm")
    if kind == "null":
        return ()
    if kind not in ("xref", "dict"):
        return None
    kind, value = doc.xref_get_key(root_xref, "AcroForm/Fields")
    if kind == "null":
        return ()
    return _reference_array_xrefs(doc, kind, value)


def document_has_a_signed_signature(doc: fitz.Document) -> bool:
    """True when at least one signature field carries an actual signature.

    ``/SigFlags`` **declares that signature fields exist**; it does not attest
    that any of them is signed.  PyMuPDF (like Acrobat and Word) writes
    ``/SigFlags 3`` for a bare, never-signed placeholder, so ``sig_flags > 0``
    calls every contract *template* "signed" — and the caller below then
    refuses every page of it, including pages carrying no field at all.
    A signed field is the one with a non-null ``/V``.

    ``/SigFlags`` is also **optional** (ISO 32000 default 0) and a tool that
    rewrites ``/AcroForm`` can drop it, in which case PyMuPDF's
    ``get_sigflags()`` answers ``-1`` -- for a document that may well carry a
    real signature.  So the flag is never a negative proof: only a missing or
    empty ``/Fields`` tree plus a non-positive flag answers "unsigned" without
    walking the fields, and a document with no ``/AcroForm`` at all stays the
    cheap common case (no field walk).

    Fail-closed at every step, so the narrowing can never turn into a false
    "unsigned" on a document that really is signed: an unreadable ``/Root``,
    ``/AcroForm``, ``/Fields``, ``/Kids`` or field node, an oversized field
    tree, and a ``/SigFlags`` that declares signatures while ``/Fields`` is
    empty all answer ``True``.  "Unreadable" never covers a legal shape: an
    indirect ``/Fields N 0 R`` or ``/Kids N 0 R`` array is resolved and
    walked, not refused (R10 F10-SIG-1).
    """
    try:
        sig_flags = doc.get_sigflags()
        field_xrefs = _acroform_field_xrefs(doc)
        if field_xrefs is None:
            return True  # unparseable: cannot prove "unsigned"
        if not field_xrefs:
            # () -> no AcroForm / no fields.  A positive /SigFlags claims
            # signatures exist while the field tree says otherwise; that
            # contradiction does not prove "unsigned".  -1 (key absent) and 0
            # with no fields is simply an unsigned document.
            return sig_flags > 0
        seen: set[int] = set()
        # (xref, inherited /FT from the parent field, if any)
        queue: list[tuple[int, str | None]] = [(x, None) for x in field_xrefs]
        while queue:
            xref, inherited_type = queue.pop()
            if xref in seen:
                continue
            seen.add(xref)
            if len(seen) > _MAX_FORM_FIELD_NODES:
                return True
            kind, value = doc.xref_get_key(xref, "FT")
            field_type = value if kind == "name" else inherited_type
            if field_type == "/Sig":
                value_kind, _ = doc.xref_get_key(xref, "V")
                if value_kind != "null":
                    return True
            kids_kind, kids_value = doc.xref_get_key(xref, "Kids")
            if kids_kind == "null":
                continue
            # Inline or indirect (`/Kids N 0 R`) array; anything else is
            # unreadable.  An empty /Kids stays fail-closed (unchanged).
            kid_refs = _reference_array_xrefs(doc, kids_kind, kids_value)
            if not kid_refs:
                return True
            queue.extend((ref, field_type) for ref in kid_refs)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        logger.warning(
            "document_has_a_signed_signature: probe failed; refusing fail-closed"
        )
        return True
    return False


def page_has_widgets_or_signatures(doc: fitz.Document, page: fitz.Page) -> bool:
    """True when the page has form widgets or the document is signed.

    **Fail-closed for BOTH halves.** ``page.widgets()`` used to sit outside
    the guard, so an unreadable ``/Annots`` array escaped to the caller as an
    exception instead of answering "refuse rather than guess" -- and the one
    caller that did catch it (``PDFModel.edit_text``'s hard reject) turned
    that into ``False``, i.e. "no widgets, run the legacy redact+reinsert
    mutation" on a page nobody could read. Both probes now answer ``True``
    when they cannot answer at all, so every caller inherits the refusal.

    ``fitz.mupdf.FzErrorBase`` derives from ``Exception``, NOT from
    ``RuntimeError``, so it must be named explicitly -- the same tuple
    ``_page_contents_xrefs`` below already uses.

    **Task 16 T16-3 review round 2:** the second half used to be
    ``doc.get_sigflags() > 0``, which is true for a document that merely
    *declares* an unsigned signature placeholder -- so an ordinary contract
    template became uneditable on every page, field-bearing or not. It now
    asks :func:`document_has_a_signed_signature`, which is fail-closed in
    every branch it cannot read, so the narrowing degrades to today's
    refusal rather than to a false accept.
    """
    try:
        if any(True for _ in page.widgets()):
            return True
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        # Unreadable /Annots: refuse rather than guess.
        logger.warning(
            "page_has_widgets_or_signatures: probe failed; refusing fail-closed"
        )
        return True
    return document_has_a_signed_signature(doc)


# Same "<num> <gen> R" indirect-reference shape the AcroForm walk above
# scans for; kept under its historical name for the readers below.
_CONTENTS_REF_RE = _XREF_REF_RE


def _page_contents_xrefs(doc: fitz.Document, page_xref: int) -> tuple[int, ...] | None:
    """The xref(s) a page's ``/Contents`` refers to, or ``None`` when the
    value could not be parsed (callers must treat that as "possibly shares
    a stream", never as "shares nothing" -- fail-closed, matching
    :func:`page_has_widgets_or_signatures` above).

    Handles the three legal shapes: a direct reference to a single stream
    (``kind == "xref"``), an indirect reference to an array of stream
    references (``kind == "xref"`` pointing at a non-stream object), and an
    inline array of references (``kind == "array"``).  A page with no
    ``/Contents`` at all (``kind == "null"``) cannot share a stream and
    returns an empty tuple, never ``None``.
    """
    try:
        kind, value = doc.xref_get_key(page_xref, "Contents")
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None
    if kind == "null":
        return ()
    if kind == "array":
        matches = _CONTENTS_REF_RE.findall(value)
        if not matches:
            return None
        return tuple(int(m) for m in matches)
    if kind == "xref":
        try:
            target = int(value.split()[0])
        except (ValueError, IndexError):
            return None
        xrefs = [target]
        try:
            is_stream = doc.xref_is_stream(target)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            return None
        if not is_stream:
            # The indirect-/Contents-array shape: `target` is itself an
            # array object, not a stream -- parse the references inside it,
            # never the dictionary that owns them.
            try:
                obj = doc.xref_object(target)
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                return None
            matches = _CONTENTS_REF_RE.findall(obj)
            if not matches:
                return None
            xrefs.extend(int(m) for m in matches)
        return tuple(xrefs)
    return None  # any other kind: fail-closed, never a guess


def find_pages_sharing_content_stream(
    doc: fitz.Document, *, stream_xref: int, page_number: int
) -> tuple[int, ...]:
    """0-based indices of every OTHER page whose ``/Contents`` references
    ``stream_xref`` -- or that could not be proven NOT to (fail-closed).

    Reads ``doc.xref_get_key(doc.page_xref(i), "Contents")`` for every page
    but ``page_number`` -- never ``doc[i]``, which loads a full page object
    and is the dense-page-preview cost this function must not pay per
    keystroke.  ``/Contents`` is not an inheritable page attribute, so no
    ``/Pages``-tree walk is needed.
    """
    hits: list[int] = []
    for i in range(doc.page_count):
        if i == page_number:
            continue
        try:
            page_xref = doc.page_xref(i)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            hits.append(i)
            continue
        xrefs = _page_contents_xrefs(doc, page_xref)
        if xrefs is None or stream_xref in xrefs:
            hits.append(i)
    return tuple(hits)


def replay_page(doc: fitz.Document, page: fitz.Page) -> PageReplay:
    return replay_page_streams(read_page_streams(doc, page))


def _origin_in_page_space(
    page: fitz.Page, show: ShowOp, *, frame: PageVisualFrame | None = None
) -> tuple[float, float] | None:
    """Map a show op's user-space origin into VISUAL (pixmap) page space.

    ``transforms.page_visual_frame`` is the single source for that chain
    (``base × /Rotate``): PyMuPDF's own ``transformation_matrix`` drops the
    CropBox origin AND ``/UserUnit`` on a rotated page, and its
    ``rotation_matrix`` drops ``/UserUnit`` and sizes itself from the
    UNCLIPPED CropBox, so neither is usable here. ``origin_page`` therefore
    stays in the same space as ``expected_origin`` values callers derive
    from displayed geometry. NOT the same space as raw
    ``page.get_text('rawdict')`` output, which PyMuPDF keeps unrotated on
    both read and write (docs/PITFALLS.md).

    ``None`` when the page's frame cannot be proven: the candidate has no
    provable displayed origin, so the caller SKIPS it rather than matching
    it against a fabricated one.  ``frame`` is a pure optimisation for a
    caller that already holds the page's frame.
    """
    page_frame = frame if frame is not None else page_visual_frame_or_none(page)
    if page_frame is None:
        return None
    point = fitz.Point(*show.origin_user) * page_frame.visual
    return (point.x, point.y)


def _target_in_invoked_form_xobjects(
    doc: fitz.Document, page: fitz.Page, target_bytes: bytes
) -> bool | None:
    """True when ``target_bytes`` decode from a show op inside a Form
    XObject the page's ``/Resources`` invokes (one level; nested ``Do``
    inside a Form is not followed — matches the funnel diagnostic).

    ``None`` (Task 12 P0-A) when at least one invoked XObject's stream was
    refused by the replay resource guard and the target was not confirmed
    in another: neither presence nor absence is provable, so the caller
    must surface the refusal rather than claim NO_MATCH — an unscanned
    stream proves nothing, and a False here would let
    ``_reconstruction_aware_reason`` rewrite the collapsed NO_MATCH into a
    fabricated reconstruction diagnosis.
    """
    try:
        xobjects = page.get_xobjects()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return False
    scan_refused = False
    for entry in xobjects:
        xref = int(entry[0])
        try:
            data = doc.xref_stream(xref) or b""
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            continue
        replay = replay_page_streams([(xref, data)])
        if replay.refusal_reason is not None:
            scan_refused = True
            continue
        if any(s.decoded_bytes == target_bytes for s in replay.shows):
            return True
    return None if scan_refused else False


def _cid_show_candidates(
    page: fitz.Page,
    replay: PageReplay,
    target_text: str,
    registry: DocumentFontRegistry,
) -> tuple[list[ShowOp], BindingFailure | None]:
    """Type0 leg of binding: decode each CID show and match the target.

    Target-scoped by construction: a failing capability or an undecodable
    show is only REMEMBERED (first one wins) and surfaces solely when no
    show matches at all — a broken, unrelated Type0 font never blocks a
    target that another show satisfies.
    """
    matches: list[ShowOp] = []
    remembered: BindingFailure | None = None
    # One capability resolution per distinct resource, not per show: a
    # Type0 lookup re-verifies the evidence digest (a full font-program
    # hash), and corpus pages carry hundreds of shows sharing one font.
    resolved: dict[str, FontCapability | None] = {}
    for show in replay.shows:
        if show.font_resource is None:
            continue
        if show.font_resource not in resolved:
            resolved[show.font_resource] = registry.capability(
                page, show.font_resource
            )
        capability = resolved[show.font_resource]
        if capability is None or capability.subtype != "Type0":
            continue
        if capability.cid is None:
            if remembered is None and capability.tier0_reject_reason:
                remembered = BindingFailure(
                    capability.tier0_reject_reason,
                    capability.tier0_reject_detail
                    or "type0 evidence gate refused this font resource",
                )
            continue
        decoded = capability.cid.decode_show_bytes(show.decoded_bytes)
        if isinstance(decoded, CidCapabilityFailure):
            if remembered is None:
                remembered = BindingFailure(decoded.reason, decoded.detail)
            continue
        if decoded == target_text:
            matches.append(show)
    return matches, remembered


def trm_bind_rejection(
    page: fitz.Page,
    show: ShowOp,
    *,
    frame: PageVisualFrame | None = None,
) -> str | None:
    """``show``'s combined-matrix refusal code, or ``None`` if admissible.

    PUBLIC and pure: the ONE predicate :func:`bind_source_text` applies to a
    show's transform, so instruments (``scripts/audit_tier_coverage.py``)
    can run it instead of copying it (docs/PITFALLS.md, "an audit that
    mirrors a gate goes stale the day the gate moves").  The caller maps the
    returned :class:`RejectReason` constant to its own failure type;
    ``_TRM_REJECT_DETAILS`` holds the one fixed detail string per code.

    Task 13 P2: the blanket "rotated, sheared, reflected, or non-uniformly
    scaled" refusal is replaced by the fail-closed quarter-turn admission —
    the combined Tm×CTM must be a positive-orientation uniform
    rotation+scale whose VISUAL baseline is cardinal; every defect keeps
    its own stable ``trm_*`` code.  Details are code-only (§10 privacy):
    matrix coefficients can fingerprint a private document's producer and
    never appear here.

    Plan section 2.C: ``show.render_mode`` is passed through, so an
    orthogonal uniform MIRROR with a cardinal visual baseline and a
    fill-only ``0 Tr`` is admitted here too; the planner then holds it to
    Tier 0's exact equal-advance splice
    (:data:`~model.text_commit.dto.RejectReason.TRM_REFLECTED_ADVANCE_CHANGE`).

    Replay-uniform shows NEVER enter the new gate (review F2): replay's
    absolute tolerances admit residuals (``|b| == 1e-6``) that the relative
    shape checks would refuse, and the pre-P2 admitted set must stay
    admitted byte-identically.  The one exception is a non-finite combined
    matrix, which replay's comparison-based idiom test cannot flag (NaN
    compares False everywhere) — that defect stays refused regardless of
    the replay flag.
    """
    verdict = admission_verdict(
        page, show.tm, show.ctm, frame=frame, render_mode=show.render_mode
    )
    if verdict.reject_reason is not None and (
        not show.trm_uniform_scaled
        or verdict.reject_reason == RejectReason.TRM_NON_FINITE
    ):
        return verdict.reject_reason
    return None


def bind_source_text(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    target_text: str,
    expected_origin: tuple[float, float] | None,
    tol: float = 0.5,
    registry: DocumentFontRegistry | None = None,
    resolved: ResolvedPageStreams | None = None,
    frame: PageVisualFrame | None = None,
) -> SourceSpanBinding | BindingFailure:
    """Bind ``target_text`` at ``expected_origin`` (page space) to one show op.

    Matching is byte-level (latin-1) against decoded string operands for
    simple-encoded fonts. When ``registry`` is provided (Task 12 P0-D) and
    the simple leg finds nothing, Type0/Identity-H shows are decoded
    through their capability's ToUnicode evidence and matched by text; a
    unique CID match must additionally survive the source-reproduction
    proof (deterministic reverse encoding byte-equals the show operand).
    Without a registry, CID text keeps the historical refusal.

    ``resolved`` (P3-B) supplies an already-captured read + replay from
    ``model.text_commit.evidence.resolve_replay``; binding then performs
    no stream read and no replay of its own.  Gate order and every
    failure surface are identical on both paths.

    ``frame`` threads the caller's per-prepare
    :class:`~model.text_commit.transforms.PageVisualFrame`; when it is
    omitted the frame is derived here, and a page whose frame cannot be
    proven is refused with
    :data:`~model.text_commit.dto.RejectReason.PAGE_GEOMETRY_UNSUPPORTED`
    before any candidate's geometry is consulted (review "sol" F2) -- the
    planner gates this first, but the funnel scripts call this entry point
    directly and must not see an exception either.
    """
    if resolved is not None:
        streams: list[tuple[int, bytes]] = list(resolved.snapshot.streams)
    else:
        streams = read_page_streams(doc, page)
    if not streams:
        return BindingFailure(RejectReason.NO_MATCH, "page has no content streams")

    replay = (
        resolved.replay if resolved is not None else replay_page_streams(streams)
    )
    if replay.refusal_reason is not None:
        # Verbatim propagation is a frozen contract (Task 12 P0-A): the
        # refusal is about resources, not stream shape or match failure.
        return BindingFailure(
            replay.refusal_reason,
            f"decoded content streams total "
            f"{sum(len(data) for _, data in streams)} bytes, over the safe "
            "replay budget; refused before tokenization",
        )
    if replay.malformed:
        return BindingFailure(
            RejectReason.MALFORMED_STREAM,
            "content stream contains constructs the replay cannot account for",
        )

    target_bytes: bytes | None
    try:
        target_bytes = target_text.encode("latin-1")
    except UnicodeEncodeError:
        target_bytes = None
    if target_bytes is None and registry is None:
        return BindingFailure(
            RejectReason.UNDECODABLE_TARGET,
            "target text is outside byte-level (latin-1) matching; "
            "font-aware decoding not yet available",
        )

    candidates = (
        [s for s in replay.shows if s.decoded_bytes == target_bytes]
        if target_bytes is not None
        else []
    )
    cid_candidate_ids: frozenset[int] = frozenset()
    cid_failure: BindingFailure | None = None
    if registry is not None:
        # The CID leg ALWAYS runs alongside the simple leg (adversarial
        # round wf_a93b4e6c-e0f, F5): a target present as both simple
        # bytes and CID text must be bindable at either occurrence's
        # origin, and duplicates across the two legs must trip the same
        # ambiguity contract as duplicates within one leg.
        cid_candidates, cid_failure = _cid_show_candidates(
            page, replay, target_text, registry
        )
        seen = {id(s) for s in candidates}
        candidates = candidates + [
            s for s in cid_candidates if id(s) not in seen
        ]
        cid_candidate_ids = frozenset(id(s) for s in cid_candidates)
    if not candidates:
        if target_bytes is None:
            # Only an undecodable (non-latin-1) target is something the
            # Type0 leg alone could have explained — surface its remembered
            # failure there and ONLY there. A latin-1 miss must never be
            # rebranded with a type0_* code by an unrelated broken font
            # (F1), and must keep the Form-XObject / P0-A refusals below.
            if cid_failure is not None:
                return cid_failure
            return BindingFailure(
                RejectReason.NO_MATCH,
                "no Type0 show operator decodes to the target text",
            )
        # Target-scoped: only fire TARGET_IN_FORM_XOBJECT when the target
        # bytes are confirmed inside an invoked Form XObject. A page that
        # merely invokes a logo/bullet XObject must not rebrand every miss.
        if replay.has_xobject_invocation:
            in_xobjects = _target_in_invoked_form_xobjects(
                doc, page, target_bytes
            )
            if in_xobjects:
                return BindingFailure(
                    RejectReason.TARGET_IN_FORM_XOBJECT,
                    "target not in the direct page stream; confirmed inside "
                    "an invoked Form XObject",
                )
            if in_xobjects is None:
                # An invoked XObject was refused by the replay resource
                # guard: NO_MATCH would be an unprovable claim, and the
                # refusal must stay verbatim (Task 12 P0-A).
                return BindingFailure(
                    RejectReason.CONTENT_STREAM_TOO_LARGE,
                    "an invoked Form XObject's stream is over the safe "
                    "replay budget; the target's presence there can be "
                    "neither confirmed nor ruled out",
                )
        return BindingFailure(
            RejectReason.NO_MATCH,
            "no show operator decodes to the target text",
        )

    # Every gate from here down reads page geometry (the candidate origins,
    # then the TRM admission's visual direction).  Prove the page's frame
    # ONCE, first, so an unprovable page is refused with its own code rather
    # than collapsing into EVIDENCE_MISMATCH or a raise (review "sol" F2).
    page_frame = frame if frame is not None else page_visual_frame_or_none(page)
    if page_frame is None:
        return BindingFailure(
            RejectReason.PAGE_GEOMETRY_UNSUPPORTED,
            "the page's user-space to visual transform cannot be proven "
            "against the page MuPDF renders",
        )

    if expected_origin is not None:
        near = []
        for s in candidates:
            origin = _origin_in_page_space(page, s, frame=page_frame)
            if origin is None:
                continue  # unmappable candidate: never matched, never guessed
            if (
                abs(origin[0] - expected_origin[0]) <= tol
                and abs(origin[1] - expected_origin[1]) <= tol
            ):
                near.append(s)
        if not near:
            return BindingFailure(
                RejectReason.EVIDENCE_MISMATCH,
                f"text matched {len(candidates)} operator(s) but none within "
                f"{tol}pt of the expected origin",
            )
        candidates = near

    if len(candidates) != 1:
        return BindingFailure(
            RejectReason.AMBIGUOUS_MATCH,
            f"{len(candidates)} indistinguishable source candidates",
        )

    show = candidates[0]
    if not show.origin_reliable:
        return BindingFailure(
            RejectReason.UNTRACKED_ADVANCE,
            "origin depends on a preceding show operator's advance",
        )
    if not show.in_bt:
        return BindingFailure(
            RejectReason.UNSUPPORTED_TEXT_STATE,
            "show operator outside BT/ET",
        )
    trm_reason = trm_bind_rejection(page, show, frame=page_frame)
    if trm_reason is not None:
        return BindingFailure(trm_reason, _TRM_REJECT_DETAILS[trm_reason])

    if id(show) in cid_candidate_ids and registry is not None:
        # Source-reproduction proof (its own gate, never skipped): the
        # ToUnicode forward decode matching the target is NOT enough — the
        # deterministic reverse encoding must reproduce the show operand
        # byte-for-byte, or the encoding contract used for the replacement
        # is unproven for this very string.
        assert show.font_resource is not None
        capability = registry.capability(page, show.font_resource)
        cid = capability.cid if capability is not None else None
        if cid is None:
            return BindingFailure(
                RejectReason.FONT_FACE_UNAVAILABLE,
                "type0 capability vanished between decode and reproduction",
            )
        reproduced = cid.encode_first_wins(target_text)
        if isinstance(reproduced, CidCapabilityFailure):
            return BindingFailure(reproduced.reason, reproduced.detail)
        if reproduced != show.decoded_bytes:
            return BindingFailure(
                RejectReason.TYPE0_SOURCE_BYTES_NOT_REPRODUCED,
                "deterministic reverse encoding does not reproduce the "
                "source show operand bytes",
            )

    stream_bytes = dict(streams)[show.stream_xref]
    origin_page = _origin_in_page_space(page, show, frame=page_frame)
    assert origin_page is not None  # page_frame was proven above
    return SourceSpanBinding(
        page_xref=page.xref,
        stream_xref=show.stream_xref,
        stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
        show=show,
        origin_page=origin_page,
        mc_wrappers=replay.wrappers_for(show),
        mc_emc_underflows=replay.mc_emc_underflows,
    )
