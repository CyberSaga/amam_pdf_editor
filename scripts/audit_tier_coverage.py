#!/usr/bin/env python3
"""Read-only structural Tier 0 headroom, not edit coverage.

Counts direct-page shows as ``tier0_eligible`` or ``tier0_ineligible``.
Eligibility is only an upper bound: this does not resolve a user's target,
check replacement glyphs/advance, detect duplicate painters, or run preview,
commit and save/reopen verification. Shared streams are flagged separately.
Replay is unbounded for census purposes; production's replay budget still
applies to real edits. Form XObject text is not enumerated here.

From the single-``Tj`` gate down, this runs the production ladder itself
(``plan.tier0_show_gate``); the TRM check is the binder's own predicate
(``inspect.trm_bind_rejection``). What remains local is the page-level and
binder-level shape a census can check without a target text, plus the
quote-operator gate that sits above the extracted ladder. Reasons are
still structural diagnostics, not a full production verdict: no target is
resolved, no replacement is encoded. Use ``measure_tier_funnel.py`` for
production resolve/bind/plan measurements.

There is no speculative Tier 1 category: both tiers share the operator gate.
Output contains counts and stable reason codes, never document text or paths.

Usage: python scripts/audit_tier_coverage.py <pdf> [--password PW] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    read_page_streams,
    trm_bind_rejection,
)
from model.text_commit.plan import PlanRejection, tier0_show_gate  # noqa: E402
from model.text_commit.replay import (  # noqa: E402
    PageReplay,
    ShowOp,
    replay_page_streams,
)
from model.text_commit.transforms import (  # noqa: E402
    PageVisualFrame,
    page_visual_frame_or_none,
)

TIER0_ELIGIBLE = "tier0_eligible"
TIER0_INELIGIBLE = "tier0_ineligible"


class _MemoizingFontRegistry(DocumentFontRegistry):
    """The audit's per-(page, resource) capability memo, wearing the
    production registry's type.

    ``tier0_show_gate`` resolves the show's font itself, so the memo has to
    sit under ``registry.capability`` rather than beside the call: a Type0
    lookup re-verifies its evidence digest (a full font-program hash) on
    EVERY call, cache hit or miss, so a resource shared by hundreds of shows
    on one page must be resolved once, not once per show
    (``model/text_commit/inspect.py``'s ``_cid_show_candidates`` pattern).

    The memo skips the wrapped registry's pull-revalidation, so it is sound
    only over an UNMUTATED document -- which a read-only census is. Never
    reuse one across a mutation: build a fresh wrapper instead.
    """

    def __init__(self, inner: DocumentFontRegistry) -> None:
        super().__init__(inner.doc)
        self.glyph_boxes = inner.glyph_boxes
        self._inner = inner
        self._memo: dict[tuple[int, str], FontCapability | None] = {}

    def capability(
        self, page: fitz.Page, resource_name: str
    ) -> FontCapability | None:
        key = (page.xref, resource_name)
        if key not in self._memo:
            self._memo[key] = self._inner.capability(page, resource_name)
        return self._memo[key]


def _classify_show(
    doc: fitz.Document,
    page: fitz.Page,
    replay: PageReplay,
    show: ShowOp,
    registry: DocumentFontRegistry,
    frame: PageVisualFrame | None,
) -> tuple[str, str | None]:
    """Return the first failed structural check, or Tier 0 headroom.

    The page-level and binder-level rungs are spelled out here because they
    are what a census can check without a target text; from the single-``Tj``
    gate down, the PRODUCTION ladder itself runs
    (``plan.tier0_show_gate``), so this instrument cannot lag a slice that
    moves one of those gates.
    """
    if frame is None:
        return TIER0_INELIGIBLE, RejectReason.PAGE_GEOMETRY_UNSUPPORTED
    if not show.origin_reliable:
        return TIER0_INELIGIBLE, RejectReason.UNTRACKED_ADVANCE
    if not show.in_bt:
        return TIER0_INELIGIBLE, RejectReason.UNSUPPORTED_TEXT_STATE

    trm_reason = trm_bind_rejection(page, show, frame=frame)
    if trm_reason is not None:
        return TIER0_INELIGIBLE, trm_reason
    # Production order (``plan.py::_classify_common``): the quote operators
    # carry text-state side effects inside their op range and are refused by
    # name BEFORE the single-Tj gate.  Mirrored (not called) because that
    # gate sits above the extracted ladder, with the document-level
    # shared-content-stream gate between them; the mirror is parity-pinned
    # by test_audit_tier_coverage.py.
    if show.operator in ("'", '"'):
        return TIER0_INELIGIBLE, RejectReason.UNSUPPORTED_SHOW_OPERATOR

    admission = tier0_show_gate(
        doc,
        page,
        show,
        wrappers=replay.wrappers_for(show),
        emc_underflows=replay.mc_emc_underflows,
        registry=registry,
    )
    if isinstance(admission, PlanRejection):
        return TIER0_INELIGIBLE, admission.reason
    return TIER0_ELIGIBLE, None


def _stream_page_owners(doc: fitz.Document) -> dict[int, set[int]]:
    owners: dict[int, set[int]] = defaultdict(set)
    for page_idx in range(doc.page_count):
        for xref in doc[page_idx].get_contents():
            owners[xref].add(page_idx)
    return owners


def audit_page(
    doc: fitz.Document,
    page: fitz.Page,
    registry: DocumentFontRegistry,
    stream_owners: dict[int, set[int]],
) -> dict[str, object]:
    streams = read_page_streams(doc, page)
    # Diagnostics take a full census: the production resource guard would
    # silently report an over-budget page as zero shows (Task 12 P0-A).
    replay = replay_page_streams(streams, max_decoded_bytes=None)
    # Prove the frame once per page; None makes every show ineligible.
    frame = page_visual_frame_or_none(page)

    counts: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()
    # The per-(page, resource) capability memo now lives INSIDE the registry
    # this page is audited with (``_MemoizingFontRegistry``), because
    # ``tier0_show_gate`` resolves the show's font itself.
    memoized = (
        registry
        if isinstance(registry, _MemoizingFontRegistry)
        else _MemoizingFontRegistry(registry)
    )
    for show in replay.shows:
        tier, reason = _classify_show(doc, page, replay, show, memoized, frame)
        counts[tier] += 1
        if reason is not None:
            reject_reasons[reason] += 1

    shared = any(len(stream_owners[xref]) > 1 for xref in page.get_contents())

    return {
        "page": page.number + 1,
        "shows_total": len(replay.shows),
        "tier0_eligible": counts[TIER0_ELIGIBLE],
        "tier0_ineligible": counts[TIER0_INELIGIBLE],
        "reject_reason_counts": dict(sorted(reject_reasons.items())),
        "shared_content_stream": shared,
    }


def audit_document(doc: fitz.Document) -> list[dict[str, object]]:
    registry = _MemoizingFontRegistry(DocumentFontRegistry(doc))
    stream_owners = _stream_page_owners(doc)
    return [
        audit_page(doc, doc[page_idx], registry, stream_owners)
        for page_idx in range(doc.page_count)
    ]


def _format_row(row: dict[str, object]) -> str:
    reasons = row["reject_reason_counts"]
    reasons_str = (
        ",".join(f"{k}={v}" for k, v in reasons.items()) if reasons else "-"  # type: ignore[union-attr]
    )
    return (
        f"page={row['page']} shows={row['shows_total']} "
        f"tier0_headroom={row['tier0_eligible']} ineligible={row['tier0_ineligible']} "
        f"shared_stream={row['shared_content_stream']} "
        f"reasons=[{reasons_str}]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="path to the PDF to audit")
    parser.add_argument("--password", default=None, help="owner/user password")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON rows"
    )
    args = parser.parse_args(argv)

    doc = fitz.open(args.pdf)
    try:
        if doc.needs_pass:
            if not args.password or doc.authenticate(args.password) == 0:
                print("error: password required or incorrect", file=sys.stderr)
                return 2

        rows = audit_document(doc)
    finally:
        doc.close()

    if args.json:
        print(json.dumps(rows))
    else:
        for row in rows:
            print(_format_row(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
