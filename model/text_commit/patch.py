"""Reversible low-level PatchSet application for the text-commit engine.

The only mutation primitive of the high-fidelity tiers: validate the page
fingerprint, splice the declared byte ranges (which re-checks per-stream
digests and expected bytes), and update the stream objects in place.  The
returned handle can revert everything from the captured prior bytes.

Forbidden here by design: redaction, ``clean_contents``, annotation
save/recreate, and any neighbor rewriting.
"""
from __future__ import annotations

import hashlib
import logging
import math
from collections import defaultdict
from dataclasses import dataclass

import fitz

from model.text_commit.dto import (
    FontOutcome,
    FontResourceAction,
    RejectReason,
    StreamReplacement,
)
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import (
    StreamStorage,
    capture_stream_storage,
    page_fingerprint,
    read_page_streams,
    restore_stream_storage,
)
from model.text_commit.pdf_lexer import (
    SpliceError,
    encode_hex_string,
    encode_literal_string,
    splice_stream,
)
from model.text_commit.replay import ShowOp
from model.text_commit.verify import prove_source_resource_reuse

logger = logging.getLogger(__name__)


class StalePlanError(ValueError):
    """The document changed since the plan was prepared; nothing mutated."""


# Show operators whose byte range a builder may splice a replacement into.
# ``'``/``\"`` carry persistent text-state side effects (an implicit T*, and
# for ``\"`` the aw/ac operands that assign Tw/Tc) inside their recorded op
# range -- a whole-op rewrite would silently delete those. Kept narrow on
# purpose: this is the mechanism-level chokepoint, mirrored by the policy-
# level gate in plan.py's shared classifier.
_SPLICEABLE_SHOW_OPERATORS = frozenset({"Tj", "TJ"})


class UnsupportedShowOperatorError(ValueError):
    """Raised when a builder is asked to splice a non-``Tj``/``TJ`` show op."""

    def __init__(self, operator: str) -> None:
        self.operator = operator
        self.reason = RejectReason.UNSUPPORTED_SHOW_OPERATOR
        super().__init__(
            f"cannot splice a {operator!r} show operator; only Tj/TJ are supported"
        )


def _require_spliceable_show(show: ShowOp) -> None:
    if show.operator not in _SPLICEABLE_SHOW_OPERATORS:
        raise UnsupportedShowOperatorError(show.operator)


@dataclass(frozen=True)
class PatchSet:
    page_xref: int
    replacements: tuple[StreamReplacement, ...]
    expected_page_fingerprint: str


@dataclass(frozen=True)
class AppliedPatch:
    """Handle for reverting an applied patch (prior stream storage)."""

    page_xref: int
    prior_streams: tuple[tuple[int, bytes], ...]
    # Task 15 P4-B2 slice 1: exact raw bytes + object dict per patched
    # stream, captured before the first mutation -- see ``revert``.
    prior_storage: tuple[StreamStorage, ...] = ()

    def revert(self, doc: fitz.Document, *, compress: bool = True) -> bool:
        """Restore every patched stream to its EXACT prior storage.

        ``compress`` (Task 13 P3-C) is kept for source compatibility with
        every existing call site but is now IGNORED (Task 15 P4-B2 slice
        1): the restore is the captured raw bytes + object dict via
        :func:`~model.text_commit.inspect.restore_stream_storage`, which is
        unconditionally at least as good as either the compressed or
        uncompressed decoded-bytes-only recompression this flag used to
        pick between -- there is no longer a storage-encoding choice for a
        caller to make. A stream whose exact restore cannot be proven
        (self-check mismatch or a raising write) still falls back to a
        decoded-bytes-exact ``compress=True`` write and is logged. Returns
        the AND of each stream's restore result; every pre-existing caller
        ignores the return value and keeps its prior best-effort behaviour.

        Never raises an ordinary ``Exception``. A ``BaseException``
        (``KeyboardInterrupt``, ``SystemExit``) raised mid-write DOES
        propagate, by design (review "sol" F4) -- but only AFTER
        :func:`~model.text_commit.inspect.restore_stream_storage` has
        written that stream's decoded-bytes fallback, so the document the
        interrupt leaves behind still decodes to the captured content.
        Remaining streams in a multi-stream patch are then NOT restored:
        an interrupt is not a rollback point, and the alternative
        (swallowing it to finish the loop) is worse.
        """
        all_exact = True
        for storage in self.prior_storage:
            if not restore_stream_storage(doc, storage):
                all_exact = False
        if not all_exact:
            logger.warning(
                "AppliedPatch.revert: one or more streams fell back to a "
                "compressed decoded-bytes restore for page_xref=%s",
                self.page_xref,
            )
        return all_exact


def apply_patchset(
    doc: fitz.Document, page: fitz.Page, patchset: PatchSet, *, compress: bool = True
) -> AppliedPatch:
    """Validate and apply ``patchset`` to the live document.

    Raises :class:`StalePlanError` (before any mutation) when the page
    fingerprint no longer matches, and :class:`SpliceError` when a stream's
    digest or expected bytes drifted.  All new stream contents are computed
    before the first ``update_stream`` call, so validation failures leave
    the document byte-identical.

    ``compress`` (Task 13 P3-C): forwarded verbatim to every
    ``doc.update_stream`` call.  FlateDecode compression costs are
    proportional to decoded stream size and dominate warm preview-keystroke
    latency on dense pages (~540x on a 2.6 MiB stream); ``compress=False``
    is safe exactly where the written bytes are never read back as a
    serialized artifact -- decoded content, ``page_fingerprint``, and every
    replay-evidence digest are unaffected by storage encoding. Default
    ``True`` preserves existing behavior for every caller other than the
    preview scratch.
    """
    if page.xref != patchset.page_xref:
        raise StalePlanError(
            f"patchset targets page xref {patchset.page_xref}, got {page.xref}"
        )
    fingerprint = page_fingerprint(doc, page)
    if fingerprint != patchset.expected_page_fingerprint:
        raise StalePlanError("page fingerprint changed since the plan was prepared")

    by_stream: dict[int, list[StreamReplacement]] = defaultdict(list)
    for replacement in patchset.replacements:
        by_stream[replacement.stream_xref].append(replacement)

    prior: list[tuple[int, bytes]] = []
    prior_storage: list[StreamStorage] = []
    updated: list[tuple[int, bytes]] = []
    for stream_xref, replacements in by_stream.items():
        current = doc.xref_stream(stream_xref) or b""
        new_bytes = splice_stream(current, replacements)  # validates, or raises
        prior.append((stream_xref, current))
        # Captured here, before the mutation loop below touches anything --
        # exact raw bytes + object dict, so a later revert can restore the
        # original storage ENCODING, not just the decoded content.
        prior_storage.append(capture_stream_storage(doc, stream_xref))
        updated.append((stream_xref, new_bytes))

    for stream_xref, new_bytes in updated:
        doc.update_stream(stream_xref, new_bytes, compress=compress)
    logger.debug(
        "apply_patchset: page=%s streams=%s replacements=%s",
        patchset.page_xref,
        [x for x, _ in updated],
        len(patchset.replacements),
    )
    return AppliedPatch(
        page_xref=patchset.page_xref,
        prior_streams=tuple(prior),
        prior_storage=tuple(prior_storage),
    )


def build_reversal_patchset(
    doc: fitz.Document,
    page: fitz.Page,
    pre_streams: tuple[tuple[int, bytes], ...],
    pre_fingerprint: str,
) -> tuple[PatchSet, PatchSet] | None:
    """Diff ``pre_streams`` against the page's *current* content streams and
    build a forward/inverse full-stream :class:`PatchSet` pair.

    ``pre_streams`` (as returned by :func:`~model.text_commit.inspect.
    read_page_streams`) must have been captured before the edit that already
    ran; ``pre_fingerprint`` is the page fingerprint at that same moment.
    Command-level undo/redo uses the pair to replay a Tier 0 commit's exact
    validated intent -- ``forward`` reproduces the committed (post-edit)
    state from the pre-edit source state; ``inverse`` reproduces the source
    state from the committed state -- without re-running the classify/
    prepare pipeline, and each side is fingerprint-gated by
    :func:`apply_patchset` exactly like the original commit was.

    Returns ``None`` when the observed diff is not exactly one changed
    stream: Tier 0 only ever patches a single content stream, so anything
    else means this helper cannot faithfully reverse the edit and callers
    must fall back to their own (lossier) undo/redo path instead of
    trusting a guess.
    """
    post_streams = dict(read_page_streams(doc, page))
    pre_map = dict(pre_streams)
    changed = [xref for xref, data in pre_map.items() if post_streams.get(xref) != data]
    if len(changed) != 1 or changed[0] not in post_streams:
        return None

    stream_xref = changed[0]
    pre_bytes = pre_map[stream_xref]
    post_bytes = post_streams[stream_xref]
    post_fingerprint = page_fingerprint(doc, page)

    forward = StreamReplacement(
        stream_xref=stream_xref,
        start=0,
        end=len(pre_bytes),
        expected_bytes=pre_bytes,
        replacement_bytes=post_bytes,
        expected_stream_digest=hashlib.sha256(pre_bytes).hexdigest(),
    )
    inverse = StreamReplacement(
        stream_xref=stream_xref,
        start=0,
        end=len(post_bytes),
        expected_bytes=post_bytes,
        replacement_bytes=pre_bytes,
        expected_stream_digest=hashlib.sha256(post_bytes).hexdigest(),
    )
    forward_patchset = PatchSet(
        page_xref=page.xref, replacements=(forward,), expected_page_fingerprint=pre_fingerprint
    )
    inverse_patchset = PatchSet(
        page_xref=page.xref, replacements=(inverse,), expected_page_fingerprint=post_fingerprint
    )
    return forward_patchset, inverse_patchset


def build_advance_preserving_erase(
    stream_bytes: bytes, show: ShowOp, consumed_advance: float
) -> StreamReplacement:
    """Replace a full show operator with a kern-only ``TJ`` that preserves
    ``consumed_advance``.

    Deleting a show operator's raw bytes removes its text-space advance
    entirely, shifting any later show that shares the same line (no
    intervening ``Td``/``Tm``).  A ``[N] TJ`` adjustment number advances the
    current position by ``-N/1000 * Tfs * Th`` with no glyph drawn and,
    critically, without applying ``Tc``/``Tw`` (those only apply to actual
    glyph shows) -- so ``consumed_advance`` (the source operator's total
    raw text-space advance, with any ``Tc``/``Tw`` it consumed already folded
    in) is compensated directly. The same positive finite ``Th`` multiplies
    both the show and kern displacement, so it cancels from the equation.

    Carries ``expected_bytes``/``expected_stream_digest`` like every
    :class:`StreamReplacement`, so :func:`~model.text_commit.pdf_lexer.
    splice_stream`'s stale-plan gate still applies.
    """
    _require_spliceable_show(show)
    if (
        show.font_size == 0.0
        or not math.isfinite(show.font_size)
        or show.hscale <= 0.0
        or not math.isfinite(show.hscale)
    ):
        raise ValueError(
            "cannot compensate advance with non-finite input or zero font size"
        )
    kern = kern_for_displacement(show, consumed_advance)
    replacement_bytes = f"[{kern:.6f}] TJ".encode("ascii")
    expected = stream_bytes[show.op_start : show.op_end]
    return StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.op_start,
        end=show.op_end,
        expected_bytes=expected,
        replacement_bytes=replacement_bytes,
        expected_stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
    )


def kern_for_displacement(show: ShowOp, displacement: float) -> float:
    """The ``TJ`` adjustment number that moves the current position by
    ``displacement`` raw text-space points for ``show``'s font size.

    Extracted verbatim from :func:`build_advance_preserving_erase` so exactly
    one implementation of the arithmetic exists: a ``[N] TJ`` adjustment
    advances the position by ``-N/1000 * Tfs * Th``. Successor preservation
    compares two raw show advances executed under that same ``Th``, so it
    cancels and ``N = -1000 * displacement / Tfs``. This is valid for every
    finite ``Th > 0``; the planner enforces that admission rule, while the
    guards here remain defense-in-depth for direct callers.
    """
    if (
        show.font_size == 0.0
        or not math.isfinite(show.font_size)
        or show.hscale <= 0.0
        or not math.isfinite(show.hscale)
        or not math.isfinite(displacement)
    ):
        raise ValueError(
            "cannot compensate advance with non-finite input or zero font size"
        )
    # Keep the pre-admission operation shape at Th == 100 bit-for-bit: the
    # fixed 100.0 denominator expresses the cancelled scale without changing
    # existing float rounding or serialized kern tokens.  Both intermediates
    # are proven finite BEFORE the division: a finite quotient is not proof
    # of a correct one -- an overflowing denominator (``font_size=1e307``)
    # silently returns ``-0.0`` where the algebraic value is ``-1e-4``.
    numerator = -100_000.0 * displacement
    denominator = show.font_size * 100.0
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        # The QUOTIENT may well be representable here (fs=1e307, d=1e300
        # algebraically gives -1e-4); it is the intermediate that is not, and
        # rescuing it would mean restructuring arithmetic whose exact shape is
        # load-bearing for bit-identical kern tokens.  Reject, and say why.
        raise ValueError(
            "cannot compensate advance: the kern computation overflows before "
            "the division"
        )
    kern = numerator / denominator
    if not math.isfinite(kern):
        raise ValueError("cannot serialize a non-finite kern adjustment")
    return kern


def build_transplant_replacement(
    stream_bytes: bytes, show: ShowOp, new_op_bytes: bytes
) -> StreamReplacement:
    """Splice ``new_op_bytes`` in at the SOURCE operator's exact byte range.

    The transplant candidate strategy: because the replacement lands at the
    identical byte position inside the identical stream, it inherits the
    source op's z-order, ``q``/``Q`` clip scope, ``ExtGState``, and
    ``BDC``/``EMC`` (OCG) nesting by construction -- unlike a TextWriter
    "append", which draws into a brand-new stream tacked onto the end of
    ``/Contents`` and inherits none of it.
    """
    _require_spliceable_show(show)
    expected = stream_bytes[show.op_start : show.op_end]
    return StreamReplacement(
        stream_xref=show.stream_xref,
        start=show.op_start,
        end=show.op_end,
        expected_bytes=expected,
        replacement_bytes=new_op_bytes,
        expected_stream_digest=hashlib.sha256(stream_bytes).hexdigest(),
    )


def build_kern_compensated_transplant(
    stream_bytes: bytes,
    show: ShowOp,
    *,
    replacement_encoded: bytes,
    source_advance: float,
    replacement_advance: float,
    string_kind: str = "literal",
) -> StreamReplacement:
    """Tier 1 Slice 1: ``"[(new) K] TJ"`` spliced at the SOURCE op's range.

    Composes :func:`build_transplant_replacement` (so the op byte range,
    ``expected_bytes``, and ``expected_stream_digest`` come from that single
    primitive, unchanged) with a kern adjustment that compensates
    ``source_advance - replacement_advance``.  The kern number follows the
    string, so the glyphs start at the source origin and any growth extends
    forward; a wider replacement yields a positive (leftward-pulling) kern.
    """
    _require_spliceable_show(show)
    kern = kern_for_displacement(show, source_advance - replacement_advance)
    # Task 12 P0-D: Identity-H CID operands serialize as hex strings, the
    # same operand kind the source show used; simple fonts keep literals.
    payload = (
        encode_hex_string(replacement_encoded)
        if string_kind == "hex"
        else encode_literal_string(replacement_encoded)
    )
    new_op = b"[" + payload + f" {kern:.6f}".encode("ascii") + b"] TJ"
    return build_transplant_replacement(stream_bytes, show, new_op)


def build_tier1_font_outcome(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    resource_name: str,
    source_font_xref: int,
    written_font_xref: int | None,
) -> FontOutcome:
    """The honest Tier-1 font-outcome chokepoint.

    ``SOURCE_RESOURCE_REUSED`` is claimed only when :func:`~model.
    text_commit.verify.prove_source_resource_reuse` affirms the resource
    still resolves to the untouched source font object -- never from face
    identity, byte equality of an extracted font program, or Unicode glyph
    coverage.  Every other case reports an honest substitution: an
    extracted face that had to be re-embedded is ``VALIDATED_FACE_
    EMBEDDED``; a named-system fallback is ``SYSTEM_FACE_SUBSTITUTED``;
    anything else (a base-14 metrics-only fallback, or a face this
    registry cannot resolve at all) is ``LEGACY_BASE14_SUBSTITUTED``.
    """
    if prove_source_resource_reuse(
        doc, page, resource_name=resource_name, source_font_xref=source_font_xref
    ):
        return FontOutcome(
            resource_name=resource_name,
            source_font_xref=source_font_xref,
            written_font_xref=written_font_xref,
            action=FontResourceAction.SOURCE_RESOURCE_REUSED,
        )

    registry = DocumentFontRegistry(doc)
    capability = registry.capability(page, resource_name)
    face_source = capability.face_source if capability is not None else "none"
    if face_source == "extracted":
        action = FontResourceAction.VALIDATED_FACE_EMBEDDED
    elif face_source == "system":
        action = FontResourceAction.SYSTEM_FACE_SUBSTITUTED
    else:
        action = FontResourceAction.LEGACY_BASE14_SUBSTITUTED

    return FontOutcome(
        resource_name=resource_name,
        source_font_xref=source_font_xref,
        written_font_xref=written_font_xref,
        action=action,
    )


__all__ = [
    "AppliedPatch",
    "PatchSet",
    "SpliceError",
    "StalePlanError",
    "UnsupportedShowOperatorError",
    "apply_patchset",
    "build_advance_preserving_erase",
    "build_kern_compensated_transplant",
    "build_reversal_patchset",
    "build_tier1_font_outcome",
    "build_transplant_replacement",
    "kern_for_displacement",
]
