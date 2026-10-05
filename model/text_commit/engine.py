"""TieredCommitEngine: scratch-first prepare, stale-checked commit.

``prepare`` classifies the edit and proves the candidate on a scratch copy
of the document — the live document is never touched during preparation.
``commit`` revalidates the page fingerprint, applies exactly one validated
PatchSet, re-verifies it (structure on the live document; renders and
extraction on isolated tobytes snapshots, so the proof never warms MuPDF's
image store for the live document), and reverts on any failure.

Tier 1 (Task 11 Slice 1) is reached only when ``max_tier >= 1`` and Tier 0
refuses with ``ADVANCE_MISMATCH``.  Since critique step 12 (2026-10-02) the
constructor default is the shipped ``TextCommitSettings.max_tier`` (1); pass
``max_tier=0`` for the Tier-0-only (flag-off) behaviour.
"""
from __future__ import annotations

import logging

import fitz

from model.edit_requests import StyleOverrides
from model.text_commit.dto import (
    CommitOutcome,
    CommitStatus,
    CommitTier,
    FontOutcome,
    FontResourceAction,
    RejectReason,
)
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.inspect import (
    BindingFailure,
    bind_source_text,
    page_fingerprint,
)
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
    build_tier1_font_outcome,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, prepare_plan
from model.text_commit.verify import (
    VerificationFailure,
    capture_page_state,
    observe_page,
    verify_tier0_commit,
    verify_tier1_commit,
)

logger = logging.getLogger(__name__)


def _rejection_outcome(
    status: CommitStatus,
    reason: str,
    detail: str,
    *,
    chain: tuple[str, ...] | None = None,
) -> CommitOutcome:
    return CommitOutcome(
        status=status,
        tier=None,
        fallback_chain=chain if chain is not None else ("tier0:" + reason,),
        warnings=(),
        font_outcomes=(),
        verified_properties=(),
        degraded_reason=detail,
        allows_external_reflow=False,
    )


def _tier1_chain(reason: str) -> tuple[str, ...]:
    """A Tier 1 commit is only ever reached by escalating a Tier 0
    ``ADVANCE_MISMATCH`` refusal (``plan._TIER1_ESCALATION_REASONS``), so
    every Tier 1 failure honestly reports both stages."""
    return (f"tier0:{RejectReason.ADVANCE_MISMATCH}", f"tier1:{reason}")


class TieredCommitEngine:
    """One engine per open document; owns the font registry.

    The ``_verified_candidates`` cache stores PreparedEdit objects that
    passed scratch verification during prepare().  When commit receives
    a plan_token that matches a cached entry, it skips the full
    re-prepare cycle and commits the already-verified candidate directly.
    This is the preview↔commit identity guarantee: the exact candidate
    the user saw in the preview is the one committed to the live document.
    """

    _VERIFIED_CACHE_MAX = 8

    def __init__(
        self, doc: fitz.Document, *, password: str | None = None, max_tier: int = 1
    ) -> None:
        self._doc = doc
        self._password = password
        self._max_tier = max_tier
        self.registry = DocumentFontRegistry(doc)
        self._verified_candidates: dict[str, PreparedEdit] = {}

    # --------------------------------------------------- verified cache

    def cache_verified_candidate(
        self, token: str, prepared: PreparedEdit
    ) -> None:
        """Store a scratch-verified PreparedEdit keyed by its token."""
        if len(self._verified_candidates) >= self._VERIFIED_CACHE_MAX:
            oldest = next(iter(self._verified_candidates))
            del self._verified_candidates[oldest]
        self._verified_candidates[token] = prepared

    def get_verified_candidate(
        self, token: str | None
    ) -> PreparedEdit | None:
        """Retrieve a cached verified candidate by token, or None."""
        if token is None:
            return None
        return self._verified_candidates.get(token)

    def clear_verified_candidates(self) -> None:
        """Drop all cached candidates (e.g. after a document mutation)."""
        self._verified_candidates.clear()

    def cached_candidate_identity_failure(
        self,
        page: fitz.Page,
        prepared: PreparedEdit,
        *,
        target_text: str,
        expected_origin: tuple[float, float] | None,
    ) -> str | None:
        """Re-bind a cached candidate on the LIVE page before it is committed.

        UI step 5 (apply by token): a token only names a candidate; the
        cache hit must still prove that the target the commit side resolved
        TODAY binds to exactly the show that candidate was verified for.
        ``None`` means the identity holds; otherwise a short diagnostic slug.

        Checks, cheapest first: the page xref, the page fingerprint (any
        change to the page's streams/resources since the preview), then a
        fresh :func:`bind_source_text` on the live streams with this
        engine's font registry (CID text is otherwise undecodable) whose
        stream xref and ``op_start``/``op_end``/``string_start``/
        ``string_end`` must equal the cached binding's -- ``seq`` is only an
        ordinal -- and the cached splice must lie inside that operator range.
        Read-only: stream bytes and the font registry, never an extraction.
        """
        if page.xref != prepared.page_xref:
            return "page_xref"
        if page_fingerprint(self._doc, page) != prepared.page_fingerprint:
            return "page_fingerprint"
        binding = bind_source_text(
            self._doc,
            page,
            target_text=target_text,
            expected_origin=expected_origin,
            registry=self.registry,
        )
        if isinstance(binding, BindingFailure):
            return f"rebind:{binding.reason}"
        live = binding.show
        cached = prepared.binding.show
        if binding.page_xref != prepared.page_xref:
            return "binding_page_xref"
        if (
            binding.stream_xref != prepared.stream_xref
            or live.stream_xref != prepared.replacement.stream_xref
        ):
            return "stream_xref"
        if (live.op_start, live.op_end, live.string_start, live.string_end) != (
            cached.op_start,
            cached.op_end,
            cached.string_start,
            cached.string_end,
        ):
            return "show_range"
        # Tier 0 splices the string operand (or one inner TJ item); Tier 1
        # transplants the whole operator, ``op_start..op_end``.  Either way
        # the splice lies inside the re-bound show's operator range.
        if not (
            live.op_start
            <= prepared.replacement.start
            <= prepared.replacement.end
            <= live.op_end
        ):
            return "splice_range"
        return None

    # ------------------------------------------------------------ prepare

    def prepare(
        self,
        page: fitz.Page,
        *,
        target_text: str,
        replacement_text: str,
        expected_origin: tuple[float, float] | None,
        target_bbox: tuple[float, float, float, float] | None = None,
        style_overrides: StyleOverrides | None = None,
        new_rect: object | None = None,
        page_has_pending_maintenance: bool = False,
    ) -> PreparedEdit | PlanRejection:
        """Classify, then prove the candidate on a scratch document."""
        plan = prepare_plan(
            self._doc,
            page,
            target_text=target_text,
            replacement_text=replacement_text,
            expected_origin=expected_origin,
            target_bbox=target_bbox,
            registry=self.registry,
            style_overrides=style_overrides,
            new_rect=new_rect,
            page_has_pending_maintenance=page_has_pending_maintenance,
            max_tier=self._max_tier,
        )
        if isinstance(plan, PlanRejection):
            return plan

        is_tier1 = plan.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        if is_tier1:
            font_outcome = build_tier1_font_outcome(
                self._doc,
                page,
                resource_name=plan.font_resource,
                source_font_xref=plan.font_xref,
                written_font_xref=plan.font_xref,
            )
            if font_outcome.action != FontResourceAction.SOURCE_RESOURCE_REUSED:
                return PlanRejection(
                    RejectReason.FONT_RESOURCE_NOT_PROVEN,
                    f"resource /{plan.font_resource} reports {font_outcome.action}",
                )

        # Scratch-first proof: tobytes() preserves xref numbering and decoded
        # stream bytes, so the plan's offsets are valid on the copy.
        scratch = self._build_scratch_copy()
        if scratch is None:
            return PlanRejection(
                RejectReason.VERIFICATION_FAILED,
                "could not build an authenticated scratch copy to prove the candidate on",
            )
        try:
            scratch_page = scratch[page.number]
            pre_state = capture_page_state(scratch, scratch_page, plan)
            try:
                apply_patchset(scratch, scratch_page, self._patchset(plan))
            except (StalePlanError, SpliceError) as exc:
                return PlanRejection(
                    RejectReason.VERIFICATION_FAILED,
                    f"candidate failed to apply on scratch: {exc}",
                )
            verify_fn = verify_tier1_commit if is_tier1 else verify_tier0_commit
            result = verify_fn(scratch, scratch_page, plan, pre_state)
            if isinstance(result, VerificationFailure):
                logger.info(
                    "tier%s candidate refuted on scratch: %s (%s)",
                    plan.tier.value,
                    result.reason,
                    result.detail,
                )
                return PlanRejection(result.reason, result.detail)
        finally:
            scratch.close()

        self.cache_verified_candidate(plan.token, plan)
        return plan

    # ------------------------------------------------------------- commit

    def commit(self, prepared: PreparedEdit) -> CommitOutcome:
        """Apply the prepared candidate to the live document, verified."""
        doc = self._doc
        try:
            page = doc[self._page_number(prepared.page_xref)]
        except (KeyError, IndexError, ValueError):
            return _rejection_outcome(
                CommitStatus.STALE_PLAN,
                RejectReason.STALE_PLAN,
                "target page no longer exists",
            )

        is_tier1 = prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
        if is_tier1:
            # Re-proven on the LIVE document: the resource table can change
            # between prepare and commit. Zero mutation on failure -- this
            # runs before apply_patchset.
            font_outcome = build_tier1_font_outcome(
                doc,
                page,
                resource_name=prepared.font_resource,
                source_font_xref=prepared.font_xref,
                written_font_xref=prepared.font_xref,
            )
            if font_outcome.action != FontResourceAction.SOURCE_RESOURCE_REUSED:
                return _rejection_outcome(
                    CommitStatus.FAILED,
                    RejectReason.FONT_RESOURCE_NOT_PROVEN,
                    f"resource /{prepared.font_resource} reports {font_outcome.action}",
                    chain=_tier1_chain(RejectReason.FONT_RESOURCE_NOT_PROVEN),
                )
        else:
            font_outcome = FontOutcome(
                resource_name=prepared.font_resource,
                source_font_xref=prepared.font_xref,
                written_font_xref=prepared.font_xref,
                action=FontResourceAction.SOURCE_RESOURCE_REUSED,
            )

        # Unguarded on purpose: capture_page_state reads page geometry, and
        # the only page shape that can refuse it (review "sol" F2) is
        # already refused by prepare_plan's PAGE_GEOMETRY_UNSUPPORTED gate,
        # which every PreparedEdit reaching here has passed. The verifier
        # below re-proves the frame anyway and returns a VerificationFailure
        # if it ever stops holding.
        #
        # Every render/extraction of the commit proof reads an isolated
        # tobytes snapshot (pre and post alike, each rendered before any
        # extraction -- see verify.observe_page -- so V0d compares like
        # with like), never the live page: rasterizing at 96 dpi,
        # rawdict with TEXT_PRESERVE_IMAGES and get_image_rects all decode
        # images into MuPDF's store, and later live renders reuse those
        # decodes -- the committed document would then render differently
        # from a fresh reopen of its own bytes. Fail-closed: no snapshot, no
        # commit (nothing is mutated yet here).
        observed_pre = self._build_scratch_copy()
        if observed_pre is None:
            return self._no_observation_snapshot(is_tier1)
        try:
            pre_state = capture_page_state(
                doc, page, prepared, observed=observe_page(observed_pre, page.number)
            )
        finally:
            observed_pre.close()
        try:
            applied = apply_patchset(doc, page, self._patchset(prepared))
        except StalePlanError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN, RejectReason.STALE_PLAN, str(exc)
            )
        except SpliceError as exc:
            return _rejection_outcome(
                CommitStatus.STALE_PLAN, RejectReason.STALE_PLAN, str(exc)
            )

        verify_fn = verify_tier1_commit if is_tier1 else verify_tier0_commit
        observed_post: fitz.Document | None = None
        try:
            observed_post = self._build_scratch_copy()
            if observed_post is None:
                result: tuple[str, ...] | VerificationFailure = VerificationFailure(
                    RejectReason.VERIFICATION_FAILED,
                    "could not build an authenticated snapshot to verify the commit on",
                )
            else:
                result = verify_fn(
                    doc,
                    page,
                    prepared,
                    pre_state,
                    observed=observe_page(observed_post, page.number),
                )
        except BaseException as exc:  # noqa: BLE001 - must revert on any raise, then re-raise
            try:
                # revert() itself re-raises a BaseException raised mid-write
                # (KeyboardInterrupt/SystemExit) rather than swallowing it --
                # but only AFTER writing that stream's decoded-bytes fallback
                # (review "sol" F4), so the document it leaves behind still
                # decodes to the pre-commit content. That case skips the
                # handler below by construction (a BaseException is not an
                # Exception) and the "may be inconsistent" wording does not
                # apply to it.
                applied.revert(doc)
            except Exception as revert_exc:
                logger.exception(
                    "tier%s live verifier raised %r and the subsequent "
                    "revert also failed; document may be inconsistent",
                    prepared.tier.value,
                    exc,
                )
                raise type(revert_exc)(
                    f"tier{prepared.tier.value} live verifier raised "
                    f"({exc!r}) and the subsequent revert also failed "
                    f"({revert_exc!r}): the document may be inconsistent"
                ) from exc
            logger.exception(
                "tier%s live verifier raised, reverted",
                prepared.tier.value,
            )
            raise
        finally:
            if observed_post is not None:
                observed_post.close()
        if isinstance(result, VerificationFailure):
            applied.revert(doc)
            logger.warning(
                "tier%s live verification failed, reverted: %s (%s)",
                prepared.tier.value,
                result.reason,
                result.detail,
            )
            chain = _tier1_chain(result.reason) if is_tier1 else None
            return _rejection_outcome(
                CommitStatus.FAILED, result.reason, result.detail, chain=chain
            )

        self.registry.bump_generation()
        # Derivable from the committed tier alone: Tier 1 is only ever
        # reached by escalating a Tier 0 ADVANCE_MISMATCH refusal
        # (plan._TIER1_ESCALATION_REASONS is single-member; _tier1_chain
        # rests on the same fact).
        decision_chain: tuple[str, ...]
        if is_tier1:
            decision_chain = (
                f"tier0:rejected:{RejectReason.ADVANCE_MISMATCH}",
                "tier1:committed",
            )
        else:
            decision_chain = ("tier0:committed",)
        return CommitOutcome(
            status=CommitStatus.COMMITTED,
            tier=prepared.tier,
            fallback_chain=(),
            warnings=("tier1_ink_growth",) if prepared.has_ink_growth else (),
            font_outcomes=(font_outcome,),
            verified_properties=result,
            degraded_reason=None,
            allows_external_reflow=False,
            decision_chain=decision_chain,
        )

    # ------------------------------------------------------------ helpers

    def _build_scratch_copy(self) -> fitz.Document | None:
        """Build a throwaway, content-readable clone of the live document.

        Never calls ``tobytes()`` with the default (decrypting) encryption
        directly on the live handle: on an *encrypted* document that
        silently poisons its crypt state (a measured PyMuPDF AES quirk --
        the same one ``PDFModel._decrypted_snapshot_bytes`` already guards
        against for worker/print snapshots), so a later ``encryption=KEEP``
        save on that same handle would write content streams that no longer
        decrypt, even though the save itself reports success. Route every
        scratch build through an ``encryption=KEEP`` snapshot and
        re-authenticate the throwaway clone instead -- the live handle's
        crypt state is never touched either way. ``KEEP`` is a no-op for
        unencrypted documents, so this is one code path for both cases.

        Returns ``None`` (never raises) when an encrypted document's clone
        cannot be re-authenticated -- callers turn that into a stable
        ``PlanRejection`` rather than letting the failure escape as an
        exception.
        """
        keep_bytes = self._doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        clone = fitz.open("pdf", keep_bytes)
        if clone.needs_pass:
            if self._password is None or clone.authenticate(self._password) == 0:
                clone.close()
                return None
        return clone

    @staticmethod
    def _no_observation_snapshot(is_tier1: bool) -> CommitOutcome:
        """Commit refusal when the pre-state snapshot cannot be built."""
        return _rejection_outcome(
            CommitStatus.FAILED,
            RejectReason.VERIFICATION_FAILED,
            "could not build an authenticated snapshot to capture the pre-commit state on",
            chain=_tier1_chain(RejectReason.VERIFICATION_FAILED) if is_tier1 else None,
        )

    def _patchset(self, prepared: PreparedEdit) -> PatchSet:
        return PatchSet(
            page_xref=prepared.page_xref,
            replacements=(prepared.replacement,),
            expected_page_fingerprint=prepared.page_fingerprint,
        )

    def _page_number(self, page_xref: int) -> int:
        for number in range(self._doc.page_count):
            if self._doc.page_xref(number) == page_xref:
                return number
        raise KeyError(page_xref)
