#!/usr/bin/env python3
"""Read-only measurement: edit-level funnel survival + three corpus checks.

Extends ``scripts/audit_tier_coverage.py`` (which classifies *shows*) with
four counts that classify *edits* and structural corpus properties instead
(TODOS.md "Pre-Task-11" measurement pass):

(a) **Edit-level funnel survival** -- resolve -> bind -> plan, every stage
    a PRODUCTION call, over a deterministic, systematic sample: every text
    line and every single whole-word run on every page (capped per page;
    see ``--line-cap`` / ``--run-cap``).

    *resolve* reuses ``_tier0_target_from_resolve`` exactly as
    ``pdf_text_edit.py`` does, over a real ``TextBlockManager`` index (the
    ``_StubModel`` shape ``test_tier0_target_resolution.py`` established
    for exactly this purpose) -- a genuine resolve pass, not the
    bind-then-plan fallback the original task spec allowed for.

    *bind* calls ``inspect.bind_source_text`` itself, with the document's
    ``DocumentFontRegistry`` (so the CID leg runs and a CJK target is
    decoded through its ToUnicode evidence instead of dying at the
    latin-1 gate) and with an ``evidence.resolve_replay`` bundle computed
    ONCE per page (``resolved=``) plus the page's proven visual frame
    (``frame=``), so dozens of samples on one page share a single stream
    read and a single replay without changing any verdict. That same
    per-page replay is retained in a document-scoped
    ``evidence.ReplayEvidenceCache`` (F6 below) so the plan stage's calls
    on the same page reuse it too.

    *plan* calls ``plan.prepare_plan(..., max_tier=0, evidence_cache=...)``
    -- the production classifier, in production gate order, including
    ``admit_show_wrappers``, the Type0 legs and the duplicate-painter
    gate. ``max_tier=0`` is Tier 0 with no escalation, so the verdict is
    identical to the (now-retired) direct ``prepare_tier0_plan`` call:
    ``prepare_plan`` returns ``_build_tier0``'s result unchanged whenever
    ``max_tier < 1`` (plan.py ~1596-1600). The probe replacement is the
    target **reversed**: it has the same glyph multiset and the same
    space count, so the advance is equal by construction and
    ``ADVANCE_MISMATCH`` can never fire, while ``NO_CHANGE`` (the first
    gate, which an identity replacement always tripped) fires only for a
    palindromic target. The funnel applies that same request-level check
    in the same position -- right after resolve, before bind -- so a
    palindrome is counted in its own ``palindrome_skipped`` bucket (a
    property of the probe, never a bind or plan failure) and never enters
    bind or plan; every later bucket is therefore a production verdict on
    the document, in production order (a palindrome on a widget-bearing
    or frame-unprovable page is ``palindrome_skipped``, exactly as
    ``prepare_plan`` would say ``no_change`` first). That bucket is NOT
    negligible and is the probe's one blind spot: every single-character
    target is a palindrome by construction, and on a CJK corpus
    single-glyph word runs dominate (2026-09-06, 23-page fixture: 225 of
    405 resolve survivors that would have bound, 224 of them one
    character long). ``plan_attempted`` (== ``bind_survivors``) is
    therefore the honest ``plan_rate`` denominator, and single-glyph
    admission stays unmeasured by this vector. A frame-unprovable page
    is not mirrored either: ``bind_source_text`` proves the frame only
    after a candidate matched, so on such a page the funnel asks
    ``prepare_plan`` directly and books its (widget-or-frame) verdict at
    the bind stage. The classifier only classifies and builds a ``PreparedEdit``;
    it never mutates the document (``plan.py:1517-1601``). Because it
    re-binds internally, a bind-stage reason code can legitimately appear
    in ``plan_fail_reasons`` too. The mirror's survival counts were an
    UPPER bound on production admission (it could not run
    ``DUPLICATE_SOURCE_PAINTER``, which needs the page replay and the
    registry); the production call runs that gate like every other, so the
    caveat is retired -- ``scripts/measure_type0_funnel.py`` remains the
    Type0-only vector, this one covers every font kind.

    **History (why this file no longer mirrors anything).** Until T16-4X
    S0 the bind and plan stages were hand-written MIRRORS of
    ``bind_source_text`` and ``prepare_tier0_plan``
    (``_bind_against_replay`` / ``_identity_plan_survival``), driven with
    an IDENTITY replacement because ``NO_CHANGE`` made the real planner
    unusable under identity. Both mirrors went stale the moment the gates
    they copied moved: the bind mirror had no registry, so all 563 CJK
    targets of the 23-page fixture counted ``undecodable_target``, and it
    refused every non-uniform TRM outright (pre-Task-13-P2); the plan
    mirror folded ``mc_depth != 0`` into ``UNSUPPORTED_TEXT_STATE`` and
    never called ``admit_show_wrappers`` (pre-Task-13-P1). Both are
    deleted. An instrument that mirrors a gate goes stale the day the
    gate moves -- call the gate.

    **F6 (this slice): the plan stage re-replayed every sample.** Calling
    ``prepare_tier0_plan`` (no cache parameter) meant every one of the
    up to 90 samples per page made its OWN read + replay + duplicate-
    painter probe of that page -- O(samples) replays per page, not O(1).
    Switching to ``prepare_plan(..., evidence_cache=...)`` over the SAME
    single-slot cache the bind step above already warms fixes this: since
    samples are grouped per page, every plan-stage call after the first
    on a page hits the slot instead of missing it. The verdict is
    unaffected (``max_tier=0`` above); only replay COUNT changes. Only the
    ``PageReplay`` itself is deduplicated by the cache -- ``prepare_plan``
    still performs its OWN stream read and digest (to derive and compare
    the evidence key) and still re-runs the duplicate-painter probe, once
    per sample, not once per page. The census replay for (b)-(d) reuses
    the production replay whenever the page is within the replay budget
    (the budget is a pure refusal, so the two are byte-identical); only an
    over-budget page pays for its own unbounded replay, built from
    ``capture_page_streams``'s single read rather than a second read of
    the document.

(b) **Forward advance-dependency** -- per show, does the *next* show in the
    page's stream sequence depend on this op's (never-computed) advance
    because no ``Td``/``TD``/``Tm``/``T*``/``BT`` (or the implicit line move
    inside ``'``/``"``) repositioned the pen first? ``replay.py`` already
    computes exactly this per show (``ShowOp.origin_reliable``: "False if a
    prior show's advance was not tracked", set via ``advance_pending`` and
    cleared by every one of those operators, including inside ``'``/``"``
    before they record their own show) -- so "does a successor consume show
    N's advance" is just "is show N+1's ``origin_reliable`` False", with no
    operator re-walk needed. Verified sufficient by reading ``replay.py``
    end to end rather than assumed; see the module for the exact mechanism.

(c) **Tabular digits** -- for every unique ``FontCapability`` with a
    ``/Widths`` table (deduped by (owner_xref, resource_name, font_xref)
    across the whole document), do codes 0x30-0x39 all carry an equal,
    positive declared width?

(d) **TJ binding-survival** -- among ``TJ`` shows, does the array contain any
    numeric (kerning) operand? ``replay.py`` builds ``decoded_bytes`` as a
    plain join of the array's string operands, silently dropping any
    numbers; ``inspect.bind_source_text`` then requires exact byte equality
    against a target string, so an array with a numeric adjustment can never
    byte-match a target that (correctly) represents that gap as a space.
    Re-lexes each TJ array's own byte range via the production re-lexer
    ``glyph_boxes.tj_items`` (S0 review F9 -- this used to be a private
    lexer copy), since ``replay.py`` does not expose this boolean on
    ``ShowOp``. ``tj_items`` returns ``None`` when the byte range does not
    reproduce the recorded operand (an integrity failure, not a document
    property); that case counts as kernless here, same as
    ``census_show_shapes.py``'s ``tj_relex_failed`` treatment. Never
    mutates ``replay.py``.

(e) **``target_in_form_xobject`` corroboration** -- historically
    ``inspect.bind_source_text`` reclassified *any* unmatched target as
    ``TARGET_IN_FORM_XOBJECT`` whenever ``PageReplay.has_xobject_invocation``
    was true anywhere on the page (one small invoked XObject -- a bullet
    glyph, a logo -- poisoned every direct-stream miss on that page with the
    same label), which made the bind-stage tally untrustworthy at face
    value. Production is now target-scoped (it confirms the target bytes
    inside an invoked Form XObject before using the label), so this check is
    an independent corroboration rather than a deconfliction, and it is
    expected to confirm nearly every such failure; a divergence means one of
    the two searches is wrong and is worth reading. Each failure is
    re-checked by
    replaying every Form XObject the page's own ``/Resources`` invokes
    (one level; nested ``Do`` inside a Form XObject's own stream is not
    followed) and looking for a byte-identical show -- no origin
    corroboration, since an XObject's text lives in its own coordinate space
    composed with the invoking ``cm`` and the XObject's own ``/Matrix``,
    which ``replay.py`` does not track. A confirmed byte match means the
    production label is at least plausible; no match anywhere means it is a
    reclassification artifact, and the *true* candidate reason (``NO_MATCH``
    or, via the same D5 relabeling as (a), ``TARGET_RECONSTRUCTION_UNVERIFIED``)
    is recovered and reported separately.

Never mutates the document (no scratch commit, no ``clean_contents``; the
``prepare_plan`` calls of stage (a) classify and build an in-memory
``PreparedEdit`` and write nothing) and never emits document text,
extracted strings, or file paths: only counts, booleans, and stable
:class:`~model.text_commit.dto.RejectReason` codes. ``BindingFailure``/
``PlanRejection`` ``.detail`` strings are never read for this reason (they
are safe boilerplate, not source text, but the reason code alone is the
documented contract this script commits to). Documents are identified only
by a 0-based positional index (the order they were passed on the command
line), never by name or derived identifiers like filename hashes.

Every metric is reported per document, then aggregated two ways: show-
weighted (raw counts summed across documents -- a large document dominates
in proportion to its own show count) and document-weighted (each document's
own rate averaged with equal weight, regardless of size). One PDF in this
corpus carries the large majority of all shows, so a single weighting would
let it define the headline; report both.

Usage::

    python scripts/measure_tier_funnel.py <pdf> [<pdf> ...] [--password PW]
        [--json] [--line-cap N] [--run-cap N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_text_edit import (  # noqa: E402
    _EditTextResolveResult,
    _reconstruction_aware_reason,
    _tier0_target_from_resolve,
)
from model.text_block import EditableSpan, TextBlockManager  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.evidence import ReplayEvidenceCache, resolve_replay  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.glyph_boxes import tj_items  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    BindingFailure,
    bind_source_text,
    capture_page_streams,
)
from model.text_commit.plan import PlanRejection, prepare_plan  # noqa: E402
from model.text_commit.replay import PageReplay, ShowOp, replay_page_streams  # noqa: E402
from model.text_commit.transforms import (  # noqa: E402
    PageVisualFrame,
    page_visual_frame_or_none,
)

# --------------------------------------------------------------------------
# Deterministic per-page sample caps (systematic: first N in a stable order,
# never random). Runtime is dominated by TextBlockManager.build_index (one
# full-document rawdict parse, unavoidable for any resolve-stage measurement
# and independent of these caps); they bound the incremental per-sample cost
# on pages with unusually many lines/runs.
# --------------------------------------------------------------------------
DEFAULT_LINE_CAP_PER_PAGE = 30
DEFAULT_RUN_CAP_PER_PAGE = 60

_TABULAR_TOL = 1e-6  # float-noise tolerance; /Widths units are exact integers


class _StubModel:
    """The two attributes ``_tier0_target_from_resolve`` touches.

    Mirrors ``test_tier0_target_resolution.py``'s ``_StubModel``: a real
    document and a real block index, nothing PDFModel-shaped (session/undo/
    controller wiring this measurement never needs).
    """

    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.block_manager = TextBlockManager()
        self.block_manager.build_index(doc)


def _build_resolve_result(
    runs: list[EditableSpan], member_ids: set[str]
) -> _EditTextResolveResult:
    members = [r for r in runs if r.span_id in member_ids]
    return _EditTextResolveResult(
        target_span=members[0] if members else (runs[0] if runs else None),  # type: ignore[arg-type]
        resolved_target_span_id=next(iter(member_ids), ""),
        effective_target_mode="run",
        target_member_span_ids=set(member_ids),
        overlap_cluster=runs,
        protected_spans=[],
        target=None,  # type: ignore[arg-type]  # unread by _tier0_target_from_resolve
        resolved_font="helv",
        rotation=0,
        is_vertical=False,
        insert_rotate=0,
        redact_rect=fitz.Rect(0, 0, 1, 1),
    )


def _line_and_run_samples(
    runs: list[EditableSpan], line_cap: int, run_cap: int
) -> tuple[list[set[str]], int, int]:
    """Deterministic (text line, single word run) member-id sets for a page.

    Lines are grouped by ``(block_idx, line_idx)`` in that key's sort order;
    runs are taken in ``get_runs`` order. Both truncate at their cap -- a
    systematic, not random, sample. Returns ``(samples, line_count,
    run_count)`` so a caller's reported sample count can never drift from
    what was actually produced here (the two were previously derived twice,
    independently, which agreed today but had no structural guarantee of
    staying in sync).
    """
    line_groups: dict[tuple[int, int], list[str]] = {}
    for run in runs:
        line_groups.setdefault((run.block_idx, run.line_idx), []).append(run.span_id)
    samples: list[set[str]] = []
    line_keys = sorted(line_groups.keys())[:line_cap]
    for key in line_keys:
        samples.append(set(line_groups[key]))
    run_slice = runs[:run_cap]
    for run in run_slice:
        samples.append({run.span_id})
    return samples, len(line_keys), len(run_slice)


def _font_has_tabular_digits(capability: FontCapability) -> bool:
    """Codes 0x30-0x39 all carry an equal, positive declared width."""
    if capability.advance_source != "widths":
        return False
    widths = [capability.width_of_code(code) for code in range(0x30, 0x3A)]
    if any(w is None for w in widths):
        return False
    lo, hi = min(widths), max(widths)  # type: ignore[type-var]
    return (hi - lo) <= _TABULAR_TOL


def _tj_has_kern_number(stream_bytes: bytes, show: ShowOp) -> bool:
    """True if a ``TJ`` array's own byte range contains a numeric operand.

    Delegates to the production TJ re-lexer ``glyph_boxes.tj_items``. A
    ``None`` result (the byte range does not reproduce the recorded
    operand -- an integrity failure, not a document property) counts as
    kernless rather than raising into the funnel.
    """
    items = tj_items(stream_bytes, show)
    return items is not None and any(item.kind == "kern" for item in items)


def _xobject_replays_for_page(
    doc: fitz.Document, page: fitz.Page, cache: dict[int, PageReplay]
) -> list[PageReplay]:
    """Replay every Form XObject the page's own ``/Resources`` invokes.

    Cached by xref at the document level: the same header/footer/logo
    XObject is typically invoked by every page, so each unique one is
    replayed once regardless of how many pages or samples ask about it.
    One level only -- a Form XObject's own stream invoking a further Form
    XObject is not followed (out of scope for this diagnostic).
    """
    try:
        xobjects = page.get_xobjects()
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return []
    replays: list[PageReplay] = []
    for entry in xobjects:
        xref = entry[0]
        if xref not in cache:
            try:
                data = doc.xref_stream(xref) or b""
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                data = b""
            # Census, not production: bypass the resource guard (P0-A).
            cache[xref] = replay_page_streams(
                [(xref, data)], max_decoded_bytes=None
            )
        replays.append(cache[xref])
    return replays


def _target_confirmed_in_xobjects(
    target_text: str, xobject_replays: list[PageReplay]
) -> bool:
    """Byte-level presence only -- see module docstring (e) for why no
    origin check is possible here. A ``True`` result means production's
    ``TARGET_IN_FORM_XOBJECT`` label is at least plausible for this target.
    """
    try:
        target_bytes = target_text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return any(
        any(s.decoded_bytes == target_bytes for s in xobj_replay.shows)
        for xobj_replay in xobject_replays
    )


@dataclass
class _FunnelCounts:
    samples_line: int = 0
    samples_run: int = 0
    resolve_survivors: int = 0
    resolve_fail: Counter = None  # type: ignore[assignment]
    bind_survivors: int = 0
    bind_fail: Counter = None  # type: ignore[assignment]
    palindrome_skipped: int = 0
    plan_survivors: int = 0
    plan_fail: Counter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.resolve_fail = Counter()
        self.bind_fail = Counter()
        self.plan_fail = Counter()

    @property
    def samples_total(self) -> int:
        return self.samples_line + self.samples_run

    @property
    def plan_attempted(self) -> int:
        """Samples the reversed-replacement probe actually asked the planner
        about. Palindromes leave the funnel BEFORE bind (production's
        request-level ``NO_CHANGE`` gate sits first), so every bind
        survivor reaches the planner and this equals ``bind_survivors``;
        kept as its own key because it is the ``plan_rate`` denominator."""
        return self.bind_survivors

    def to_dict(self) -> dict[str, object]:
        return {
            "samples_total": self.samples_total,
            "samples_line": self.samples_line,
            "samples_run": self.samples_run,
            "resolve_survivors": self.resolve_survivors,
            "resolve_fail_reasons": dict(sorted(self.resolve_fail.items())),
            "bind_survivors": self.bind_survivors,
            "bind_fail_reasons": dict(sorted(self.bind_fail.items())),
            "palindrome_skipped": self.palindrome_skipped,
            "plan_attempted": self.plan_attempted,
            "plan_survivors": self.plan_survivors,
            "plan_fail_reasons": dict(sorted(self.plan_fail.items())),
        }


def measure_document(
    doc: fitz.Document, line_cap: int, run_cap: int
) -> dict[str, object]:
    model = _StubModel(doc)
    registry = DocumentFontRegistry(doc)

    funnel = _FunnelCounts()
    fwd_shows_total = 0
    fwd_with_successor = 0
    fwd_dependent = 0
    tj_total = 0
    tj_has_kern = 0
    tj_no_kern_single = 0
    tj_no_kern_multi = 0
    fonts_seen: dict[tuple[int, str, int], FontCapability] = {}
    show_font_total = 0
    show_font_tabular = 0
    pages_with_xobject_invocation = 0
    shows_on_xobject_invoking_pages = 0
    xobject_cache: dict[int, PageReplay] = {}
    xobject_confirmed = 0
    xobject_reclassified_no_match = 0
    xobject_reclassified_reconstruction_unverified = 0

    # T16-4X S0 F6: ONE evidence cache for the whole document, shared by
    # the once-per-page bind replay below AND the plan stage's
    # ``prepare_plan`` calls -- single slot (P3-B), so it retains exactly
    # the current page's evidence. Samples are grouped per page (the
    # outer loop advances pages only after every sample on one page is
    # done), so every plan-stage call on a page hits the slot the bind
    # step just warmed instead of re-reading, re-replaying and re-probing
    # the page for every sample (docs/PITFALLS.md: "an audit that mirrors
    # a gate goes stale the day the gate moves" -- the underlying issue
    # here is the funnel not reusing evidence the way every other
    # production caller of ``prepare_plan`` does).
    evidence_cache = ReplayEvidenceCache()

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        # F6 (this slice): ONE read of the page's decoded content streams.
        # ``capture_page_streams`` is that read; the census replay below is
        # built from the snapshot's OWN streams (``snapshot.streams``)
        # rather than calling ``read_page_streams`` a second time -- only
        # the PageReplay is deduplicated by the evidence cache (via
        # ``resolve_replay``/``evidence_cache`` below), not the stream read
        # itself: the census still runs its own (unbounded, uncached)
        # replay of those same bytes, since it must never see the
        # production resource-guard refusal.
        snapshot = capture_page_streams(doc, page)
        streams = list(snapshot.streams)
        stream_map = dict(streams)
        # Production bind inputs: the DEFAULT replay budget (never the
        # census's unbounded path -- the funnel measures what production
        # would decide, resource guard included), threaded through the
        # document's evidence cache so the plan stage's per-sample
        # ``prepare_plan`` calls reuse this exact PageReplay (see F6 in the
        # module docstring for what is and is not deduplicated).
        resolved = resolve_replay(snapshot, evidence_cache.lookup(snapshot.key))
        if resolved.evidence is not None and not resolved.from_cache:
            evidence_cache.store(resolved.evidence)
        # Census replay for (b)-(d): the budget is a pure refusal, so an
        # under-budget production replay is byte-identical to the unbounded
        # one and is reused as-is; only an over-budget page (production
        # refused it) pays for its own unbounded replay, because the census
        # must never see the production resource-guard refusal.
        if resolved.evidence is not None:
            replay = resolved.evidence.replay
        else:
            replay = replay_page_streams(streams, max_decoded_bytes=None)
        page_frame: PageVisualFrame | None = page_visual_frame_or_none(page)

        # -- (b) forward advance-dependency --
        shows = replay.shows
        fwd_shows_total += len(shows)
        for i in range(len(shows) - 1):
            fwd_with_successor += 1
            if not shows[i + 1].origin_reliable:
                fwd_dependent += 1

        if replay.has_xobject_invocation:
            pages_with_xobject_invocation += 1
            shows_on_xobject_invoking_pages += len(shows)

        # -- (c) tabular digits + (d) TJ binding-survival, per show --
        page_capabilities = registry.page_capabilities(page)
        for show in shows:
            if show.font_resource is not None:
                capability = page_capabilities.get(show.font_resource)
                if capability is not None:
                    show_font_total += 1
                    key = (
                        capability.owner_xref,
                        capability.resource_name,
                        capability.font_xref,
                    )
                    fonts_seen.setdefault(key, capability)
                    if _font_has_tabular_digits(capability):
                        show_font_tabular += 1
            if show.operator == "TJ":
                tj_total += 1
                has_kern = _tj_has_kern_number(stream_map[show.stream_xref], show)
                if has_kern:
                    tj_has_kern += 1
                elif show.array_item_count == 1:
                    tj_no_kern_single += 1
                else:
                    tj_no_kern_multi += 1

        # -- (a) edit-level funnel: resolve -> bind -> plan, all production --
        runs = model.block_manager.get_runs(page_idx)
        if not runs:
            continue
        samples, line_count, run_count = _line_and_run_samples(runs, line_cap, run_cap)
        funnel.samples_line += line_count
        funnel.samples_run += run_count
        for member_ids in samples:
            resolve_result = _build_resolve_result(runs, member_ids)
            target = _tier0_target_from_resolve(model, page_idx, resolve_result)
            if target is None:
                funnel.resolve_fail[RejectReason.MULTI_SPAN_TARGET] += 1
                continue
            funnel.resolve_survivors += 1

            # Production's FIRST gate is request-level: ``NO_CHANGE`` when
            # the replacement equals the source (``plan.py`` ~877), before
            # any gate that reads the document. The reversed probe equals
            # its source exactly for a palindrome, so the same request-level
            # check is applied here, in the same position, and the sample
            # never enters bind or plan -- see the module docstring.
            if target.text[::-1] == target.text:
                funnel.palindrome_skipped += 1
                continue

            if page_frame is None:
                # ``bind_source_text`` proves the frame only AFTER a
                # byte-matching candidate is found (``inspect.py``
                # ~1047-1057), so on a frameless page it would report
                # NO_MATCH for a target that was never matched. The planner
                # decides earlier (widgets, then frame -- ``plan.py``
                # ~903-920), so ask the planner itself and book its verdict
                # at the bind stage; no gate order is mirrored here.
                planned = prepare_plan(
                    doc,
                    page,
                    target_text=target.text,
                    replacement_text=target.text[::-1],
                    expected_origin=target.origin,
                    target_bbox=target.bbox,
                    registry=registry,
                    max_tier=0,
                    evidence_cache=evidence_cache,
                )
                assert isinstance(planned, PlanRejection), planned
                funnel.bind_fail[planned.reason] += 1
                continue

            binding = bind_source_text(
                doc,
                page,
                target_text=target.text,
                expected_origin=target.origin,
                registry=registry,
                resolved=resolved,
                frame=page_frame,
            )
            if isinstance(binding, BindingFailure):
                # (e): production's TARGET_IN_FORM_XOBJECT is now
                # target-scoped, so this independent re-check corroborates
                # rather than deconflates -- see module docstring (e).
                if binding.reason == RejectReason.TARGET_IN_FORM_XOBJECT:
                    xobj_replays = _xobject_replays_for_page(doc, page, xobject_cache)
                    if _target_confirmed_in_xobjects(target.text, xobj_replays):
                        xobject_confirmed += 1
                    else:
                        deconflated = _reconstruction_aware_reason(
                            RejectReason.NO_MATCH, target
                        )
                        if deconflated == RejectReason.TARGET_RECONSTRUCTION_UNVERIFIED:
                            xobject_reclassified_reconstruction_unverified += 1
                        else:
                            xobject_reclassified_no_match += 1
                    funnel.bind_fail[binding.reason] += 1
                else:
                    reason = _reconstruction_aware_reason(binding.reason, target)
                    funnel.bind_fail[reason] += 1
                continue
            funnel.bind_survivors += 1

            # The PRODUCTION classifier, reversed-replacement probe (see
            # docstring (a)). Only ``.reason`` is ever read: a rejection's
            # ``.detail`` can carry a basefont name (§10 privacy).
            # ``max_tier=0`` is Tier 0 with no escalation -- the verdict is
            # identical to ``prepare_tier0_plan``'s (plan.py's
            # ``prepare_plan`` returns ``_build_tier0``'s result unchanged
            # whenever ``max_tier < 1``) -- and sharing ``evidence_cache``
            # with the per-page bind step above (F6) means every plan-stage
            # call after the first on a page reuses that page's PageReplay
            # instead of re-replaying. ONLY the PageReplay is deduplicated
            # this way: ``prepare_plan`` still re-reads and re-digests the
            # page's streams (to derive and compare the evidence key) and
            # still re-runs the duplicate-painter probe, once per sample,
            # not once per page.
            planned = prepare_plan(
                doc,
                page,
                target_text=target.text,
                replacement_text=target.text[::-1],
                expected_origin=target.origin,
                target_bbox=target.bbox,
                registry=registry,
                max_tier=0,
                evidence_cache=evidence_cache,
            )
            if not isinstance(planned, PlanRejection):
                funnel.plan_survivors += 1
            else:
                # NO_CHANGE cannot occur here: palindromes were bucketed
                # before bind, in production's own gate position.
                funnel.plan_fail[planned.reason] += 1

    tabular_fonts = sum(
        1 for cap in fonts_seen.values() if _font_has_tabular_digits(cap)
    )
    widths_fonts = sum(
        1 for cap in fonts_seen.values() if cap.advance_source == "widths"
    )

    return {
        "pages": doc.page_count,
        "funnel": {
            "line_cap_per_page": line_cap,
            "run_cap_per_page": run_cap,
            **funnel.to_dict(),
        },
        "forward_advance": {
            "shows_total": fwd_shows_total,
            "shows_with_successor": fwd_with_successor,
            "forward_dependent": fwd_dependent,
        },
        "tabular_digits": {
            "fonts_with_widths": widths_fonts,
            "fonts_with_tabular_digits": tabular_fonts,
            "shows_with_font_capability": show_font_total,
            "shows_with_tabular_digit_font": show_font_tabular,
        },
        "tj_binding": {
            "tj_total": tj_total,
            "tj_has_kern": tj_has_kern,
            "tj_no_kern_single_string": tj_no_kern_single,
            "tj_no_kern_multi_string": tj_no_kern_multi,
        },
        "xobject_deconfliction": {
            "pages_total": doc.page_count,
            "pages_with_xobject_invocation": pages_with_xobject_invocation,
            "shows_total": fwd_shows_total,
            "shows_on_xobject_invoking_pages": shows_on_xobject_invoking_pages,
            "target_in_form_xobject_bind_failures": funnel.bind_fail.get(
                RejectReason.TARGET_IN_FORM_XOBJECT, 0
            ),
            "confirmed_in_xobject": xobject_confirmed,
            "reclassified_no_match": xobject_reclassified_no_match,
            "reclassified_reconstruction_unverified": (
                xobject_reclassified_reconstruction_unverified
            ),
        },
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return (numerator / denominator) if denominator else None


def _aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    """Show-weighted (raw sums) and document-weighted (mean of per-doc rates)."""
    show_weighted: dict[str, object] = {
        "funnel": {
            "samples_total": 0,
            "resolve_survivors": 0,
            "resolve_fail_reasons": Counter(),
            "bind_survivors": 0,
            "bind_fail_reasons": Counter(),
            "palindrome_skipped": 0,
            "plan_attempted": 0,
            "plan_survivors": 0,
            "plan_fail_reasons": Counter(),
        },
        "forward_advance": {
            "shows_with_successor": 0,
            "forward_dependent": 0,
        },
        "tabular_digits": {
            "fonts_with_widths": 0,
            "fonts_with_tabular_digits": 0,
            "shows_with_font_capability": 0,
            "shows_with_tabular_digit_font": 0,
        },
        "tj_binding": {
            "tj_total": 0,
            "tj_has_kern": 0,
            "tj_no_kern_single_string": 0,
            "tj_no_kern_multi_string": 0,
        },
        "xobject_deconfliction": {
            "pages_total": 0,
            "pages_with_xobject_invocation": 0,
            "shows_total": 0,
            "shows_on_xobject_invoking_pages": 0,
            "target_in_form_xobject_bind_failures": 0,
            "confirmed_in_xobject": 0,
            "reclassified_no_match": 0,
            "reclassified_reconstruction_unverified": 0,
        },
    }
    doc_rates: dict[str, list[float]] = {
        "resolve_rate": [],
        "bind_rate": [],
        "plan_rate": [],
        "forward_dependent_rate": [],
        "tabular_font_rate": [],
        "tabular_show_rate": [],
        "tj_no_kern_rate": [],
        "xobject_pages_flagged_rate": [],
        "xobject_label_confirmed_rate": [],
    }

    for row in rows:
        f = row["funnel"]  # type: ignore[index]
        sw_f = show_weighted["funnel"]  # type: ignore[index]
        sw_f["samples_total"] += f["samples_total"]
        sw_f["resolve_survivors"] += f["resolve_survivors"]
        sw_f["resolve_fail_reasons"].update(f["resolve_fail_reasons"])
        sw_f["bind_survivors"] += f["bind_survivors"]
        sw_f["bind_fail_reasons"].update(f["bind_fail_reasons"])
        sw_f["palindrome_skipped"] += f["palindrome_skipped"]
        sw_f["plan_attempted"] += f["plan_attempted"]
        sw_f["plan_survivors"] += f["plan_survivors"]
        sw_f["plan_fail_reasons"].update(f["plan_fail_reasons"])

        fa = row["forward_advance"]  # type: ignore[index]
        sw_fa = show_weighted["forward_advance"]  # type: ignore[index]
        sw_fa["shows_with_successor"] += fa["shows_with_successor"]
        sw_fa["forward_dependent"] += fa["forward_dependent"]

        td = row["tabular_digits"]  # type: ignore[index]
        sw_td = show_weighted["tabular_digits"]  # type: ignore[index]
        sw_td["fonts_with_widths"] += td["fonts_with_widths"]
        sw_td["fonts_with_tabular_digits"] += td["fonts_with_tabular_digits"]
        sw_td["shows_with_font_capability"] += td["shows_with_font_capability"]
        sw_td["shows_with_tabular_digit_font"] += td["shows_with_tabular_digit_font"]

        tj = row["tj_binding"]  # type: ignore[index]
        sw_tj = show_weighted["tj_binding"]  # type: ignore[index]
        sw_tj["tj_total"] += tj["tj_total"]
        sw_tj["tj_has_kern"] += tj["tj_has_kern"]
        sw_tj["tj_no_kern_single_string"] += tj["tj_no_kern_single_string"]
        sw_tj["tj_no_kern_multi_string"] += tj["tj_no_kern_multi_string"]

        xo = row["xobject_deconfliction"]  # type: ignore[index]
        sw_xo = show_weighted["xobject_deconfliction"]  # type: ignore[index]
        sw_xo["pages_total"] += xo["pages_total"]
        sw_xo["pages_with_xobject_invocation"] += xo["pages_with_xobject_invocation"]
        sw_xo["shows_total"] += xo["shows_total"]
        sw_xo["shows_on_xobject_invoking_pages"] += xo["shows_on_xobject_invoking_pages"]
        sw_xo["target_in_form_xobject_bind_failures"] += xo[
            "target_in_form_xobject_bind_failures"
        ]
        sw_xo["confirmed_in_xobject"] += xo["confirmed_in_xobject"]
        sw_xo["reclassified_no_match"] += xo["reclassified_no_match"]
        sw_xo["reclassified_reconstruction_unverified"] += xo[
            "reclassified_reconstruction_unverified"
        ]

        if f["samples_total"]:
            doc_rates["resolve_rate"].append(f["resolve_survivors"] / f["samples_total"])
        if f["resolve_survivors"]:
            doc_rates["bind_rate"].append(f["bind_survivors"] / f["resolve_survivors"])
        # Palindromes never reached a document-measuring gate, so they are
        # out of the denominator as well as out of both numerators.
        if f["plan_attempted"]:
            doc_rates["plan_rate"].append(f["plan_survivors"] / f["plan_attempted"])
        if fa["shows_with_successor"]:
            doc_rates["forward_dependent_rate"].append(
                fa["forward_dependent"] / fa["shows_with_successor"]
            )
        if td["fonts_with_widths"]:
            doc_rates["tabular_font_rate"].append(
                td["fonts_with_tabular_digits"] / td["fonts_with_widths"]
            )
        if td["shows_with_font_capability"]:
            doc_rates["tabular_show_rate"].append(
                td["shows_with_tabular_digit_font"] / td["shows_with_font_capability"]
            )
        if tj["tj_total"]:
            no_kern = tj["tj_no_kern_single_string"] + tj["tj_no_kern_multi_string"]
            doc_rates["tj_no_kern_rate"].append(no_kern / tj["tj_total"])
        if xo["pages_total"]:
            doc_rates["xobject_pages_flagged_rate"].append(
                xo["pages_with_xobject_invocation"] / xo["pages_total"]
            )
        if xo["target_in_form_xobject_bind_failures"]:
            doc_rates["xobject_label_confirmed_rate"].append(
                xo["confirmed_in_xobject"] / xo["target_in_form_xobject_bind_failures"]
            )

    sw_f = show_weighted["funnel"]  # type: ignore[index]
    sw_f["resolve_fail_reasons"] = dict(sorted(sw_f["resolve_fail_reasons"].items()))
    sw_f["bind_fail_reasons"] = dict(sorted(sw_f["bind_fail_reasons"].items()))
    sw_f["plan_fail_reasons"] = dict(sorted(sw_f["plan_fail_reasons"].items()))
    sw_f["resolve_rate"] = _safe_ratio(sw_f["resolve_survivors"], sw_f["samples_total"])
    sw_f["bind_rate"] = _safe_ratio(sw_f["bind_survivors"], sw_f["resolve_survivors"])
    sw_f["plan_rate"] = _safe_ratio(sw_f["plan_survivors"], sw_f["plan_attempted"])

    sw_fa = show_weighted["forward_advance"]  # type: ignore[index]
    sw_fa["forward_dependent_rate"] = _safe_ratio(
        sw_fa["forward_dependent"], sw_fa["shows_with_successor"]
    )

    sw_td = show_weighted["tabular_digits"]  # type: ignore[index]
    sw_td["tabular_font_rate"] = _safe_ratio(
        sw_td["fonts_with_tabular_digits"], sw_td["fonts_with_widths"]
    )
    sw_td["tabular_show_rate"] = _safe_ratio(
        sw_td["shows_with_tabular_digit_font"], sw_td["shows_with_font_capability"]
    )

    sw_tj = show_weighted["tj_binding"]  # type: ignore[index]
    no_kern_total = sw_tj["tj_no_kern_single_string"] + sw_tj["tj_no_kern_multi_string"]
    sw_tj["tj_no_kern_total"] = no_kern_total
    sw_tj["tj_no_kern_rate"] = _safe_ratio(no_kern_total, sw_tj["tj_total"])

    sw_xo = show_weighted["xobject_deconfliction"]  # type: ignore[index]
    sw_xo["pages_flagged_rate"] = _safe_ratio(
        sw_xo["pages_with_xobject_invocation"], sw_xo["pages_total"]
    )
    sw_xo["label_confirmed_rate"] = _safe_ratio(
        sw_xo["confirmed_in_xobject"], sw_xo["target_in_form_xobject_bind_failures"]
    )

    def _mean(values: list[float]) -> float | None:
        return (sum(values) / len(values)) if values else None

    document_weighted = {
        "documents_counted": {key: len(vals) for key, vals in doc_rates.items()},
        "resolve_rate_mean": _mean(doc_rates["resolve_rate"]),
        "bind_rate_mean": _mean(doc_rates["bind_rate"]),
        "plan_rate_mean": _mean(doc_rates["plan_rate"]),
        "forward_dependent_rate_mean": _mean(doc_rates["forward_dependent_rate"]),
        "tabular_font_rate_mean": _mean(doc_rates["tabular_font_rate"]),
        "tabular_show_rate_mean": _mean(doc_rates["tabular_show_rate"]),
        "tj_no_kern_rate_mean": _mean(doc_rates["tj_no_kern_rate"]),
        "xobject_pages_flagged_rate_mean": _mean(doc_rates["xobject_pages_flagged_rate"]),
        "xobject_label_confirmed_rate_mean": _mean(
            doc_rates["xobject_label_confirmed_rate"]
        ),
    }

    return {"show_weighted": show_weighted, "document_weighted": document_weighted}


def _format_summary(index: int, row: dict[str, object]) -> str:
    f = row["funnel"]  # type: ignore[index]
    fa = row["forward_advance"]  # type: ignore[index]
    td = row["tabular_digits"]  # type: ignore[index]
    tj = row["tj_binding"]  # type: ignore[index]
    xo = row["xobject_deconfliction"]  # type: ignore[index]
    return (
        f"doc[{index}] pages={row['pages']} "
        f"funnel[samples={f['samples_total']} resolve={f['resolve_survivors']} "
        f"bind={f['bind_survivors']} plan={f['plan_survivors']}"
        f"/{f['plan_attempted']} palindromes={f['palindrome_skipped']}] "
        f"fwd_advance[shows={fa['shows_total']} dependent={fa['forward_dependent']}"
        f"/{fa['shows_with_successor']}] "
        f"tabular[fonts={td['fonts_with_tabular_digits']}/{td['fonts_with_widths']} "
        f"shows={td['shows_with_tabular_digit_font']}/{td['shows_with_font_capability']}] "
        f"tj[total={tj['tj_total']} kern={tj['tj_has_kern']} "
        f"no_kern={tj['tj_no_kern_single_string'] + tj['tj_no_kern_multi_string']}] "
        f"xobj[pages_flagged={xo['pages_with_xobject_invocation']}/{xo['pages_total']} "
        f"label_confirmed={xo['confirmed_in_xobject']}/"
        f"{xo['target_in_form_xobject_bind_failures']}]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="paths to the PDFs to measure")
    parser.add_argument("--password", default=None, help="owner/user password")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--line-cap", type=int, default=DEFAULT_LINE_CAP_PER_PAGE,
        help="max text-line samples per page (deterministic first-N)",
    )
    parser.add_argument(
        "--run-cap", type=int, default=DEFAULT_RUN_CAP_PER_PAGE,
        help="max single-word-run samples per page (deterministic first-N)",
    )
    args = parser.parse_args(argv)

    rows: list[dict[str, object]] = []
    for doc_index, pdf_path in enumerate(args.pdfs):
        doc = fitz.open(pdf_path)
        try:
            if doc.needs_pass:
                if not args.password or doc.authenticate(args.password) == 0:
                    print(f"error: password required or incorrect for document at index {doc_index}", file=sys.stderr)
                    return 2
            row = measure_document(doc, args.line_cap, args.run_cap)
        finally:
            doc.close()
        rows.append(row)

    aggregate = _aggregate(rows)
    output = {
        "per_document": [{"doc_index": i, **r} for i, r in enumerate(rows)],
        "aggregate": aggregate,
        "methodology": {
            "resolve_bind_plan_driven": True,
            "bind_then_plan_fallback_used": False,
            # False since T16-4X S0: the probe replacement is the target
            # REVERSED, so the planner's NO_CHANGE gate no longer swallows
            # every sample and the production classifier can run.
            "identity_replacement": False,
            "bind_stage": "production_bind_source_text_with_registry",
            "plan_stage": "production_prepare_plan_max_tier0_reversed_replacement",
            "mirrored_gates": False,
        },
    }

    if args.json:
        print(json.dumps(output))
    else:
        for i, row in enumerate(rows):
            print(_format_summary(i, row))
        agg = aggregate["show_weighted"]
        print(
            "AGGREGATE(show-weighted) "
            f"resolve_rate={agg['funnel']['resolve_rate']} "
            f"bind_rate={agg['funnel']['bind_rate']} "
            f"plan_rate={agg['funnel']['plan_rate']} "
            f"fwd_dependent_rate={agg['forward_advance']['forward_dependent_rate']} "
            f"tabular_font_rate={agg['tabular_digits']['tabular_font_rate']} "
            f"tj_no_kern_rate={agg['tj_binding']['tj_no_kern_rate']} "
            f"xobj_label_confirmed_rate={agg['xobject_deconfliction']['label_confirmed_rate']}"
        )
        dw = aggregate["document_weighted"]
        print(
            "AGGREGATE(document-weighted) "
            f"resolve_rate_mean={dw['resolve_rate_mean']} "
            f"bind_rate_mean={dw['bind_rate_mean']} "
            f"plan_rate_mean={dw['plan_rate_mean']} "
            f"fwd_dependent_rate_mean={dw['forward_dependent_rate_mean']} "
            f"tabular_font_rate_mean={dw['tabular_font_rate_mean']} "
            f"tj_no_kern_rate_mean={dw['tj_no_kern_rate_mean']} "
            f"xobj_label_confirmed_rate_mean={dw['xobject_label_confirmed_rate_mean']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
