"""T16-4 Step 12: what the engine really says about the CAD fixture's bold.

The nine synthetic-bold shows the T16-4 program is named after live on two
pages of one gitignored drawing fixture (the "CAD fixture", located by a
glob on a FRAGMENT of its file name, self-skipped when absent).  Every
earlier measurement of them
— the tandem plan's E3/E4 tables and its 2026-09-06 Step 0 re-run — reported
``not_single_literal_tj`` for all nine: the operator gate fired first and
masked everything behind it.  S1 removed that gate, so this module records
what the NEXT gate is, per fixture target, measured rather than predicted
(``plans/task16-4-glyph-coverage-expansion.md`` §4 S1 "Acceptance adds";
§X2 "a slice that does not move the survival rate has not landed").

**The headline finding, stated once here so it is not re-derived.**  The
tandem plan's Step 12 predicted ``seq 7/11/15`` → ACCEPTED and
``seq 49/50/51`` → ``duplicate_source_painter``.  Neither is reachable: all
ten targets sit inside a struct-content marked-content wrapper, so the
production verdict for every single-item show is ``mc_wrapper_not_pure_
layer`` — the S2 gate.  That is exactly what §1.3 item 1 of the expansion
plan predicted for the Office corpus ("lifting the TJ gate alone moves the
refusal from ``not_single_literal_tj`` to ``mc_wrapper_not_pure_layer`` and
changes nothing for the user; S1 and S2 must land together or be measured
together"), now demonstrated on the CAD fixture too — which §1.2 had
described as ``/OC``-wrapped, a whole-fixture statistic that does not hold
for these particular shows.  The pins below are therefore the MEASURED
outcomes; each names the outcome the plan expected and the gate that stands
in front of it.

Privacy contract (CLAUDE.md, §10), narrowed to what the code below actually
does (T16-4X S1 review L4 — the earlier wording said "never by name" while
the glob embeds a distinctive substring of the real file name, so the claim
overstated the guarantee).  The fixture is addressed by ROLE in every
sentence of prose and every assertion, and is LOCATED by a glob on a
fragment of its name, per the repo's ``needs_fixtures`` convention (the
fragment stays: it is how every fixture-backed module in this repo finds its
document, and a full name is what the convention actually forbids).  No
decoded document text, no font name and no file path is written here or
asserted on.  CJK targets are decoded
INTERNALLY through the capability's own ``decode_show_bytes`` (the Step 0
re-run's method) purely to drive ``prepare_plan``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    _origin_in_page_space,
    read_page_streams,
    replay_page,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    duplicate_source_painter_detail,
    prepare_plan,
)
from model.text_commit.replay import ShowOp  # noqa: E402
from model.text_commit.transforms import page_visual_frame  # noqa: E402

pytestmark = pytest.mark.needs_fixtures

# Only pages 0 and 1 are read: they carry every mode-2 show in the file
# (plan E1), and the fixture has 50 pages, one of which decodes to a 71.5 MB
# content stream that production itself refuses under the replay budget.
_PAGES = (0, 1)

# (page, seq) of every target the tandem plan's E3/E4 tables measured.
_BOLD_TARGETS: tuple[tuple[int, int], ...] = (
    (0, 2),
    (0, 7),
    (0, 9),
    (0, 11),
    (0, 13),
    (0, 15),
    (1, 49),
    (1, 50),
    (1, 51),
)

# Single-item shows: the population S1 was built to admit.  Refused one gate
# later, at marked content, until S2 lands.
_SINGLE_ITEM_TARGETS = ((0, 7), (0, 11), (0, 15), (1, 49), (1, 50), (1, 51))
# Two-item kerned arrays: S1 refuses these under their own new code, which
# S4 will replace.
_MULTI_ITEM_TARGETS = ((0, 9), (0, 13))
# The one simple-font mode-2 show (tandem "open question 2").
_SIMPLE_FONT_TARGET = (0, 2)


def _fixture_path() -> Path | None:
    matches = sorted(ROOT.glob("test_files/*HVAC*.pdf"))
    return matches[0] if matches else None


def _decode(registry: DocumentFontRegistry, page: fitz.Page, show: ShowOp) -> str:
    """The show's target text, decoded through the production capability.

    Never returned to a report and never asserted on -- it exists only to
    give ``prepare_plan`` a target to bind.
    """
    assert show.font_resource is not None
    capability = registry.capability(page, show.font_resource)
    assert capability is not None, "the target's font resource did not resolve"
    if capability.cid is not None:
        decoded = capability.cid.decode_show_bytes(show.decoded_bytes)
        assert isinstance(decoded, str), f"CID decode refused: {decoded!r}"
        return decoded
    return show.decoded_bytes.decode("latin-1")


def _replacement_for(text: str) -> str:
    """An identity-advance replacement, or a distinct fallback.

    Reversing the target keeps the glyph multiset — and therefore the
    consumed advance — identical, which is what keeps ``ADVANCE_MISMATCH``
    out of the measurement.  A palindromic target would reverse to itself
    and refuse ``NO_CHANGE``, a verdict about the REQUEST rather than about
    the show, so those fall back to a distinct character (see
    :func:`test_the_simple_font_bold_show_lands_on_the_same_gate` for why
    that is still sound for the one target it applies to).
    """
    reversed_text = text[::-1]
    return reversed_text if reversed_text != text else "A"


class _Verdict:
    """One target's measured planner outcome, plus its show evidence."""

    def __init__(self, show: ShowOp, twins: int, result: object) -> None:
        self.show = show
        self.twins = twins
        self.accepted = isinstance(result, PreparedEdit)
        self.reason = result.reason if isinstance(result, PlanRejection) else None
        self.detail = result.detail if isinstance(result, PlanRejection) else None
        self.identity_advance = True
        # E4's verdict, from the duplicate gate called directly (see
        # :func:`test_the_duplicate_gate_still_cannot_prove_the_page_one_placements`).
        self.dup_detail: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"<Verdict seq={self.show.seq} mode={self.show.render_mode} "
            f"items={self.show.array_item_count} twins={self.twins} "
            f"accepted={self.accepted} reason={self.reason!r}>"
        )


@pytest.fixture(scope="module")
def verdicts() -> dict[tuple[int, int], _Verdict]:
    """Plan every pinned target ONCE, and prove the fixture was not mutated.

    Module-scoped and single-registry on purpose: ``prepare_plan`` re-runs
    ``find_pages_sharing_content_stream`` (O(pages) C calls) plus a stream
    digest and the font-program digests per call (expansion plan §8.6), and
    a 50-page fixture pays that nine times over otherwise.  One replay and
    one visual frame per page are cached for the same reason.
    """
    path = _fixture_path()
    if path is None:
        pytest.skip("the CAD fixture is not present in test_files/")
    doc = fitz.open(path)
    try:
        registry = DocumentFontRegistry(doc)
        pages = {number: doc[number] for number in _PAGES}
        replays = {number: replay_page(doc, page) for number, page in pages.items()}
        frames = {number: page_visual_frame(page) for number, page in pages.items()}
        capabilities = {
            number: registry.page_capabilities(page)
            for number, page in pages.items()
        }
        streams = {
            number: dict(read_page_streams(doc, page))
            for number, page in pages.items()
        }
        before = {
            number: read_page_streams(doc, page) for number, page in pages.items()
        }

        measured: dict[tuple[int, int], _Verdict] = {}
        for page_number, seq in _BOLD_TARGETS:
            page = pages[page_number]
            replay = replays[page_number]
            by_seq = {show.seq: show for show in replay.shows}
            assert seq in by_seq, f"page {page_number} has no show at seq {seq}"
            show = by_seq[seq]
            text = _decode(registry, page, show)
            replacement = _replacement_for(text)
            twins = sum(
                1
                for other in replay.shows
                if other.seq != seq and other.decoded_bytes == show.decoded_bytes
            )
            result = prepare_plan(
                doc,
                page,
                target_text=text,
                replacement_text=replacement,
                expected_origin=_origin_in_page_space(
                    page, show, frame=frames[page_number]
                ),
                target_bbox=None,
                registry=registry,
                max_tier=0,
            )
            verdict = _Verdict(show, twins, result)
            verdict.identity_advance = replacement == text[::-1]
            capability = capabilities[page_number][show.font_resource]
            replacement_cids = None
            if capability.cid is not None:
                encoded = capability.cid.encode_strict(replacement)
                if isinstance(encoded, tuple):
                    replacement_cids = encoded
            verdict.dup_detail = duplicate_source_painter_detail(
                page,
                show,
                target_text=text,
                target_capability=capability,
                source_advance=0.0,
                registry=registry,
                shows=replay.shows,
                capabilities=capabilities[page_number],
                streams=streams[page_number],
                replacement_cids=replacement_cids,
                glyph_boxes=registry.glyph_boxes,
                frame=frames[page_number],
            )
            measured[(page_number, seq)] = verdict

        # Every one of these outcomes is a refusal, and a refusal must leave
        # the document untouched (the standing fail-closed rule).  Compared
        # on the two pages actually read rather than through
        # ``doc.tobytes()``, which this repo records as nondeterministic
        # across calls.
        for number, page in pages.items():
            assert read_page_streams(doc, page) == before[number], (
                f"planning mutated page {number}"
            )
        yield measured
    finally:
        doc.close()


def test_no_pinned_bold_show_still_dies_at_the_operator_gate(
    verdicts: dict[tuple[int, int], _Verdict],
) -> None:
    """The S1 acceptance measurement: the dominant code MOVED.

    Every one of these targets reported ``not_single_literal_tj`` in the
    tandem plan's E3 table and again in its 2026-09-06 Step 0 re-run.  If
    any still does, S1 did not land on this fixture and every pin below is
    measuring the same masked gate the program set out to remove.
    """
    assert set(verdicts) == set(_BOLD_TARGETS)
    still_masked = {
        key: verdict.reason
        for key, verdict in verdicts.items()
        if verdict.reason == "not_single_literal_tj"
    }
    assert not still_masked, still_masked


def test_the_pinned_shows_carry_the_measured_bold_evidence(
    verdicts: dict[tuple[int, int], _Verdict],
) -> None:
    """E1/E4, re-measured through the production replay and registry.

    Pinned because every verdict below is only interesting for a show that
    really is a mode-2 ``TJ``: if the fixture were re-exported and these
    seq numbers pointed at ordinary fill shows, the reason-code pins would
    still pass while measuring nothing.  The twin counts are E4's (0 for the
    page-0 CID shows, 1 for each page-1 show, 65 for the simple-font one).
    """
    for key, verdict in verdicts.items():
        assert verdict.show.render_mode == 2, key
        assert verdict.show.operator == "TJ", key
        assert verdict.show.line_width > 0.0, key
    for key in _SINGLE_ITEM_TARGETS + (_SIMPLE_FONT_TARGET,):
        assert verdicts[key].show.array_item_count == 1, key
    for key in _MULTI_ITEM_TARGETS:
        assert verdicts[key].show.array_item_count == 2, key
    assert [verdicts[key].twins for key in ((0, 7), (0, 11), (0, 15))] == [0, 0, 0]
    assert [verdicts[key].twins for key in ((1, 49), (1, 50), (1, 51))] == [1, 1, 1]
    assert verdicts[_SIMPLE_FONT_TARGET].twins == 65


@pytest.mark.parametrize("key", _MULTI_ITEM_TARGETS, ids=lambda k: f"p{k[0]}seq{k[1]}")
def test_multi_item_bold_arrays_refuse_under_their_own_code(
    key: tuple[int, int], verdicts: dict[tuple[int, int], _Verdict]
) -> None:
    """The tandem plan's Step 12 pin that DID land as written.

    Two-item kerned arrays are Tier 1/S4's problem, and S1 gave them a
    distinct code rather than leaving them under ``NOT_SINGLE_LITERAL_TJ``
    (``dto.py``: a distinct gate gets a distinct code).  The item-count gate
    fires ahead of the marked-content gate, which is why these two targets
    report something different from their six neighbours on the same page.
    """
    verdict = verdicts[key]
    assert verdict.reason == "tj_multi_item_array", verdict
    assert "2 string items" in (verdict.detail or ""), verdict.detail
    assert verdict.identity_advance


@pytest.mark.parametrize("key", _SINGLE_ITEM_TARGETS, ids=lambda k: f"p{k[0]}seq{k[1]}")
def test_single_item_bold_shows_now_stop_at_the_marked_content_gate(
    key: tuple[int, int], verdicts: dict[tuple[int, int], _Verdict]
) -> None:
    """Re-pinned to the MEASURED outcome; the plan predicted two others.

    * ``p0 seq 7/11/15`` were predicted ACCEPTED (a Tier 0 ``PreparedEdit``
      with an identity-advance replacement).
    * ``p1 seq 49/50/51`` were predicted ``duplicate_source_painter`` with
      "cannot prove target placement" (E4's direct duplicate-gate call).

    Both predictions are unreachable through the production planner: all six
    shows are wrapped in a struct-content marked-content wrapper, whose gate
    fires before the render-mode ladder and before the duplicate-painter
    gate.  So S1 alone commits nothing on this fixture — precisely the
    "S1 and S2 must land together or be measured together" conclusion of
    expansion plan §1.3, now measured on the fixture that motivated T16-4
    rather than inferred from the Office corpus.

    The refusal is pinned by CODE and by the wrapper class in its detail, so
    when S2 admits render-inert struct content this test fails loudly and is
    re-pinned to whatever gate is next — it is not silently satisfied by the
    admission that follows.
    """
    verdict = verdicts[key]
    assert not verdict.accepted, verdict
    assert verdict.reason == "mc_wrapper_not_pure_layer", verdict
    assert "struct_content" in (verdict.detail or ""), verdict.detail
    assert verdict.identity_advance, "the target reversed to itself"


def test_the_duplicate_gate_still_cannot_prove_the_page_one_placements(
    verdicts: dict[tuple[int, int], _Verdict],
) -> None:
    """E4, kept alive as a pin even though the planner no longer reaches it.

    The tandem plan's Step 12 asked for ``p1 seq 49/50/51`` to refuse
    ``duplicate_source_painter`` with "cannot prove target placement".  The
    marked-content gate now answers first (the test above), so that verdict
    is unreachable through ``prepare_plan`` until S2 lands — but it is still
    the verdict of the gate itself, and it is the reason S3 exists.  Calling
    ``duplicate_source_painter_detail`` directly with the exact arm's inputs
    (``glyph_boxes`` + ``replacement_cids``) reproduces E4 row for row:

    * ``p0 seq 7/11/15`` — no same-bytes twin, so the gate early-outs: ``None``.
    * ``p1 seq 49/50/51`` — one same-bytes twin each, and
      ``_painter_glyph_ink`` refuses every non-fill render mode (that is S3's
      change, deliberately not made here), so the exact arm short-circuits.

    Without the exact-arm inputs the same call answers ``None`` for all six
    — a measured trap worth recording: E4 is only reproducible when the
    caller supplies both, which is what production does and what a probe
    that passes neither does not.

    ``pen`` is deliberately not supplied, exactly as E4's own call did not:
    this pins the gate's own verdict, not the conservative outset S1 added
    on top of it (Step 9 pins that on synthetic geometry).
    """
    for key in ((0, 7), (0, 11), (0, 15)):
        assert verdicts[key].dup_detail is None, verdicts[key]
    for key in ((1, 49), (1, 50), (1, 51)):
        assert verdicts[key].dup_detail == (
            "identical source painter cannot prove target placement"
        ), verdicts[key]


def test_the_simple_font_bold_show_lands_on_the_same_gate(
    verdicts: dict[tuple[int, int], _Verdict],
) -> None:
    """Tandem open question 2, answered by measurement.

    The question was whether the one simple-font mode-2 show has a clear
    ``tier0_reject_reason`` once S1 lets it past the operator gate, and
    whether the conservative ``target_core`` outset changes its admission
    (E4 recorded its 65 same-bytes twins as provably disjoint).  Neither
    question is live on this fixture: the show shares its neighbours'
    struct-content wrapper, so it refuses at the marked-content gate before
    any pen is read and before any twin is measured, exactly like the six
    CID shows.

    This target is also the one that cannot take an identity-advance
    replacement: it shows a single code, so reversing it yields the target
    itself and refuses ``NO_CHANGE`` — a verdict about the request, not
    about the show.  A distinct replacement character is used instead, which
    is sound here precisely BECAUSE the pinned gate fires ahead of every
    advance and encoding check; both spellings are recorded so a future
    reader can see the substitution was deliberate.
    """
    verdict = verdicts[_SIMPLE_FONT_TARGET]
    # E4's own row for this target: 65 same-bytes twins, all provably
    # disjoint, so the duplicate gate admits it.  Unchanged by S1.
    assert verdict.dup_detail is None, verdict
    assert not verdict.identity_advance, (
        "this target used to reverse to itself; if it no longer does, the "
        "fallback replacement below is measuring the wrong thing"
    )
    assert not verdict.accepted, verdict
    assert verdict.reason == "mc_wrapper_not_pure_layer", verdict
    assert "struct_content" in (verdict.detail or ""), verdict.detail
