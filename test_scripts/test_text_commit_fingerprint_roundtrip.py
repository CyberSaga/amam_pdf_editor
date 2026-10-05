"""``page_fingerprint`` must survive a ``tobytes(KEEP)`` round trip.

``TieredCommitEngine.prepare`` proves every Tier 0 candidate on a *scratch*
copy built by ``_build_scratch_copy`` -> ``doc.tobytes(encryption=KEEP)`` +
``fitz.open("pdf", ...)``.  ``prepare_tier0_plan`` measures
``page_fingerprint`` on the LIVE document and ``apply_patchset`` re-measures
it on the SCRATCH clone, so the two must agree for any candidate to survive.

They used to not.  MuPDF re-serializes every object the first time a
disk-loaded document is written, reordering each object dictionary's
top-level keys (same keys, same values, different order; a second round
trip is idempotent).  ``_update_font_dependencies`` used to fold
``doc.xref_object(...)`` *strings* into the digest, so that reordering alone
flipped the fingerprint -- while the page's content-stream bytes, its
``get_fonts(full=True)`` tuples, its annot/widget geometry and even its page
xref are all byte-identical across the same round trip.  Fixed by hashing
``_canonical_object_digest``'s order-independent ``xref_get_keys``/
``xref_get_key`` view of each object instead of the raw serialized string.

Status of this module (originally written Red-Light-First; the fix has
since landed):

* ``test_page_fingerprint_survives_keep_encryption_round_trip`` was the RED
  test and is green now that ``_update_font_dependencies`` folds an
  order-independent, canonical digest of each object's keys
  (``xref_get_keys``/``xref_get_key``, the structured API ``plan.py``'s
  ``_indirect_target`` already uses) instead of the ``xref_object()`` string.
* ``test_page_fingerprint_detects_font_dependency_mutation`` passed before
  the fix and must keep passing: it is the guard that stops the fix from
  turning the font-dependency digest into a rubber stamp.
* ``test_tiered_prepare_accepts_a_real_tier0_candidate`` was
  ``xfail(strict=True)`` (the convention ``test_text_commit_characterization.py``
  uses for "intended behaviour, blocked until the fix lands") and is now a
  plain passing test -- the fix landing is exactly what flipped it to XPASS,
  which was the signal to drop the marker.

The fixture is the real, gitignored ``test_files/test-large-file.pdf``: the
bug only reproduces on a document MuPDF loaded from disk and has never been
observed on a freshly synthesised in-memory one.  No document text is
hard-coded here -- the Tier 0 target is discovered by a bounded, deterministic
scan through the production planner itself.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.inspect import (  # noqa: E402
    _FONT_DEPENDENCY_KEYS,
    _fold_canonical_value,
    _origin_in_page_space,
    page_fingerprint,
    read_page_streams,
)
from model.text_commit.plan import (  # noqa: E402
    PlanRejection,
    PreparedEdit,
    prepare_tier0_plan,
)
from model.text_commit.replay import replay_page_streams  # noqa: E402

LARGE_PDF = ROOT / "test_files" / "test-large-file.pdf"

# Bounded so the scan stays a test, not a corpus run.  The first Tier 0
# candidate on this fixture is found well inside it (measured: page 13,
# ~0.3s); the scan is a deterministic first-N walk, never random.
_PAGE_CAP = 24
_MIN_TARGET_LEN = 5

# Per-test, not module-level: the numeric-canonicalisation tests at the end
# of this module are synthetic and must run wherever ``test_files/`` is absent.
_needs_large_pdf = pytest.mark.skipif(
    not LARGE_PDF.exists(),
    reason="test_files/ is gitignored; this bug only reproduces on a real "
    "disk-loaded document",
)


@dataclass(frozen=True)
class _Tier0Candidate:
    """A target the production planner already accepts, minus the scratch proof."""

    page_number: int
    target_text: str
    replacement_text: str
    expected_origin: tuple[float, float]


def _swap_first_distinct_pair(text: str) -> str | None:
    """An anagram of ``text`` produced by swapping one adjacent unequal pair.

    Advance-neutral by construction and independent of the width table: the
    multiset of character codes, the length, and the space count are all
    preserved, so ``prepare_tier0_plan``'s ADVANCE_MISMATCH gate compares two
    identical sums even under the exact (1e-9) /Widths tolerance.  Returns
    ``None`` for a run of one repeated character, whose only anagram is
    itself (which would trip NO_CHANGE instead).
    """
    for index in range(len(text) - 1):
        if text[index] != text[index + 1]:
            return text[:index] + text[index + 1] + text[index] + text[index + 2 :]
    return None


def _find_tier0_candidate(doc: fitz.Document) -> _Tier0Candidate | None:
    """First target on the first ``_PAGE_CAP`` pages the planner accepts.

    Eligibility is decided by ``prepare_tier0_plan`` itself -- the production
    classifier -- not by a re-implementation of its gates, so a candidate
    returned here has provably cleared every structural, font, encoding and
    advance check.  The only thing left between it and a ``PreparedEdit`` from
    ``TieredCommitEngine.prepare`` is the scratch-copy proof.  Discovering the
    target instead of hard-coding it also keeps corpus text out of the repo.
    """
    registry = DocumentFontRegistry(doc)
    for page_number in range(min(doc.page_count, _PAGE_CAP)):
        page = doc[page_number]
        replay = replay_page_streams(read_page_streams(doc, page))
        if replay.malformed:
            continue
        for show in replay.shows:
            if show.operator != "Tj" or show.string_kind not in ("literal", "hex"):
                continue
            try:
                target_text = show.decoded_bytes.decode("latin-1")
            except UnicodeDecodeError:
                continue
            if len(target_text) < _MIN_TARGET_LEN or not target_text.isprintable():
                continue
            replacement_text = _swap_first_distinct_pair(target_text)
            if replacement_text is None or replacement_text == target_text:
                continue
            origin = _origin_in_page_space(page, show)
            plan = prepare_tier0_plan(
                doc,
                page,
                target_text=target_text,
                replacement_text=replacement_text,
                expected_origin=origin,
                target_bbox=None,
                registry=registry,
            )
            if isinstance(plan, PreparedEdit):
                return _Tier0Candidate(
                    page_number=page_number,
                    target_text=target_text,
                    replacement_text=replacement_text,
                    expected_origin=origin,
                )
    return None


def _font_declaring(doc: fitz.Document, page: fitz.Page, key: str) -> int | None:
    """xref of the first font on ``page`` that declares ``key`` directly."""
    for entry in page.get_fonts(full=True):
        font_xref = int(entry[0])
        if key in doc.xref_get_keys(font_xref):
            return font_xref
    return None


@_needs_large_pdf
def test_page_fingerprint_survives_keep_encryption_round_trip():
    """The scratch clone's fingerprint must equal the live document's.

    Asserts the *inputs* first: page xref, decoded content-stream bytes and
    the ``get_fonts(full=True)`` metadata tuples are all identical across the
    round trip, which pins the drift on the one remaining fingerprint input --
    the ``xref_object()`` strings ``_update_font_dependencies`` folds in.
    """
    doc = fitz.open(str(LARGE_PDF))
    try:
        page = doc[0]
        live_fingerprint = page_fingerprint(doc, page)
        live_streams = tuple(read_page_streams(doc, page))
        live_fonts = tuple(page.get_fonts(full=True))
        live_annots = tuple((a.xref, tuple(a.rect)) for a in page.annots())

        clone = fitz.open(
            "pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        )
        try:
            clone_page = clone[0]

            assert clone_page.xref == page.xref, (
                "page xref changed across the round trip; the plan's page "
                "identity would be stale for an unrelated reason"
            )
            assert tuple(read_page_streams(clone, clone_page)) == live_streams, (
                "content-stream bytes changed across the round trip"
            )
            assert tuple(clone_page.get_fonts(full=True)) == live_fonts, (
                "font resource table changed across the round trip"
            )
            assert (
                tuple((a.xref, tuple(a.rect)) for a in clone_page.annots())
                == live_annots
            ), "annotation identity/geometry changed across the round trip"

            assert page_fingerprint(clone, clone_page) == live_fingerprint, (
                "page fingerprint is not stable across tobytes(KEEP) + reopen, "
                "so every Tier 0 candidate proven on a scratch copy is "
                "rejected as stale"
            )
        finally:
            clone.close()
    finally:
        doc.close()


@_needs_large_pdf
def test_page_fingerprint_detects_font_dependency_mutation():
    """A genuine change to a folded font dependency must flip the digest.

    ``/FirstChar`` is one of ``_FONT_DEPENDENCY_KEYS`` (it is the code range
    that indexes ``/Widths``, so changing it changes what the document says
    every glyph advances by) and -- unlike ``/BaseFont`` -- it does *not*
    appear in ``page.get_fonts(full=True)``.  Asserting the metadata tuple is
    unchanged while the fingerprint moves proves the detection came from the
    font-object digest itself, which is exactly the part the round-trip fix
    rewrites.  Passes today; it exists to stop the fix from becoming a rubber
    stamp.
    """
    assert "FirstChar" in _FONT_DEPENDENCY_KEYS

    doc = fitz.open(str(LARGE_PDF))
    try:
        page = doc[0]
        font_xref = _font_declaring(doc, page, "FirstChar")
        assert font_xref is not None, "fixture has no page-0 font declaring /FirstChar"
        kind, value = doc.xref_get_key(font_xref, "FirstChar")
        assert kind == "int"

        before_fingerprint = page_fingerprint(doc, page)
        before_fonts = tuple(page.get_fonts(full=True))

        doc.xref_set_key(font_xref, "FirstChar", str(int(value) + 1))

        assert tuple(page.get_fonts(full=True)) == before_fonts, (
            "precondition: the font metadata tuple must be blind to this "
            "mutation, or the test would pass without reading the font object"
        )
        assert doc.xref_get_key(font_xref, "FirstChar") == (
            "int",
            str(int(value) + 1),
        ), "the mutation did not take effect"
        assert page_fingerprint(doc, page) != before_fingerprint, (
            "page fingerprint ignored a real change to a folded font "
            "dependency; a plan measured under the old width table would "
            "still count as fresh"
        )
    finally:
        doc.close()


@_needs_large_pdf
def test_tiered_prepare_accepts_a_real_tier0_candidate():
    """A candidate the planner accepts must survive the scratch proof too.

    ``prepare`` differs from ``prepare_tier0_plan`` only by that proof, so a
    rejection here is the scratch path refusing a candidate every production
    gate already passed.  Also asserts the live document is left untouched --
    preparation is required to be non-mutating.
    """
    doc = fitz.open(str(LARGE_PDF))
    try:
        candidate = _find_tier0_candidate(doc)
        if candidate is None:
            pytest.skip(
                f"no Tier 0 candidate in the first {_PAGE_CAP} pages of this fixture"
            )
        page = doc[candidate.page_number]
        streams_before = tuple(read_page_streams(doc, page))
        fingerprint_before = page_fingerprint(doc, page)

        engine = TieredCommitEngine(doc)
        result = engine.prepare(
            page,
            target_text=candidate.target_text,
            replacement_text=candidate.replacement_text,
            expected_origin=candidate.expected_origin,
        )

        assert tuple(read_page_streams(doc, page)) == streams_before, (
            "prepare() mutated the live document's content streams"
        )
        assert page_fingerprint(doc, page) == fingerprint_before, (
            "prepare() disturbed the live page"
        )
        assert not isinstance(result, PlanRejection), (
            f"prepare() rejected a planner-accepted Tier 0 candidate: "
            f"{result.reason if isinstance(result, PlanRejection) else ''} | "
            f"{result.detail if isinstance(result, PlanRejection) else ''}"
        )
        assert isinstance(result, PreparedEdit)
        assert result.page_xref == page.xref
        assert result.replacement_text == candidate.replacement_text
        assert result.original_text == candidate.target_text
        assert result.page_fingerprint == fingerprint_before
    finally:
        doc.close()


# ===================================================== numeric canonicalisation
#
# Plan §2.A (2026-09-29).  MuPDF stores an integral PDF real written as
# ``1.0`` as a REAL object and prints it minimally as ``1``; the scratch copy
# ``_build_scratch_copy`` re-parses that ``1`` as an INTEGER.  The value text
# ``xref_get_key`` returns is ``"1"`` on both sides, but its kind flips
# ``float`` -> ``int``, so every fold that hashed ``kind:value`` moved across
# the live -> scratch round trip and ``prepare`` refused every candidate on
# such a page as ``verification_failed`` ("page fingerprint changed since the
# plan was prepared").  MEASURED on HVAC pages 5-7 and ECC page 1: the only
# differing component was an indirect ExtGState's ``/CA``.
#
# Unlike the key-order drift above, this one DOES reproduce on a synthetic
# in-memory document: ``update_object(xref, "<< /CA 1.0 >>")`` creates the
# real object directly, no disk load needed.  Every round-trip test below
# asserts that premise (``float`` live, ``int`` on scratch) so a PyMuPDF
# change that stops flipping the kind cannot turn it vacuous.
#
# The counterfactual tests are GUARDS: they pass before the fix too, and
# exist so the fix can never fold a genuinely different value into the same
# fingerprint (no tolerance, no rounding: ``1`` and ``0.999999`` differ).

_NUM_TARGET = "Price 2024"
_NUM_REPLACEMENT = "Price 2025"  # helv digits share widths: advance-neutral
_OPAQUE_GS = "<< /Type /ExtGState /CA 1.0 /ca 1.0 /LW 2.0 >>"
_NUM_STREAM = b"q /GS1 gs BT /F1 24 Tf 72 700 Td (Price 2024) Tj ET Q"


def _numeric_doc(
    gs_body: str = _OPAQUE_GS,
    *,
    stream: bytes = _NUM_STREAM,
    widths: str | None = None,
    properties_body: str | None = None,
) -> fitz.Document:
    """One synthetic page: /F1 Helvetica, /GS1 an INDIRECT ExtGState.

    ``widths`` adds an indirect ``/Widths`` array (with ``/FirstChar 80
    /LastChar 80``) to the font; ``properties_body`` adds an indirect
    ``/Properties /MC0`` target.  Nothing is saved: the round trip under
    test is the engine's own scratch build.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_body = (
        "/Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding"
    )
    if widths is not None:
        widths_xref = doc.get_new_xref()
        doc.update_object(widths_xref, widths)
        font_body += f" /FirstChar 80 /LastChar 80 /Widths {widths_xref} 0 R"
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, f"<< {font_body} >>")
    gs_xref = doc.get_new_xref()
    doc.update_object(gs_xref, gs_body)
    resources = (
        f"<< /Font << /F1 {font_xref} 0 R >> /ExtGState << /GS1 {gs_xref} 0 R >>"
    )
    if properties_body is not None:
        props_xref = doc.get_new_xref()
        doc.update_object(props_xref, properties_body)
        resources += f" /Properties << /MC0 {props_xref} 0 R >>"
    doc.xref_set_key(page.xref, "Resources", resources + " >>")
    return doc


def _gs_xref(doc: fitz.Document) -> int:
    kind, value = doc.xref_get_key(doc[0].xref, "Resources/ExtGState/GS1")
    assert kind == "xref", (kind, value)
    return int(value.split()[0])


def _scratch(doc: fitz.Document) -> fitz.Document:
    """The PRODUCTION scratch clone ``prepare`` proves candidates on."""
    scratch = TieredCommitEngine(doc)._build_scratch_copy()
    assert scratch is not None
    return scratch


def _scratch_fingerprint(doc: fitz.Document) -> str:
    scratch = _scratch(doc)
    try:
        return page_fingerprint(scratch, scratch[0])
    finally:
        scratch.close()


def test_integral_real_extgstate_fingerprint_survives_the_scratch_round_trip():
    """RED before the fix: ``CA<US>float<US>1`` vs ``CA<US>int<US>1``."""
    doc = _numeric_doc()
    try:
        gs_xref = _gs_xref(doc)
        scratch = _scratch(doc)
        try:
            # The premise, asserted: the kind really flips, the text does not.
            assert doc.xref_get_key(gs_xref, "CA") == ("float", "1")
            assert scratch.xref_get_key(gs_xref, "CA") == ("int", "1")
            assert page_fingerprint(scratch, scratch[0]) == page_fingerprint(
                doc, doc[0]
            ), "an integral real (1.0) and its integer respelling (1) must fold identically"
        finally:
            scratch.close()
    finally:
        doc.close()


def test_integral_real_marked_content_target_survives_the_scratch_round_trip():
    """RED before the fix: the same kind flip through the /Properties fold
    (``marked_content._fold_target_structured``), proving the numeric
    canonicalisation lives at the shared chokepoint, not only in inspect.

    The ExtGState here is non-integral (``0.5`` stays a real on both sides),
    so only the marked-content component can be what differs.
    """
    doc = _numeric_doc(
        "<< /Type /ExtGState /CA 0.5 /ca 0.5 >>",
        properties_body="<< /Type /OCG /Name (Layer) /X 2.0 >>",
    )
    try:
        props_kind, props_value = doc.xref_get_key(
            doc[0].xref, "Resources/Properties/MC0"
        )
        assert props_kind == "xref"
        props_xref = int(props_value.split()[0])
        scratch = _scratch(doc)
        try:
            assert doc.xref_get_key(props_xref, "X") == ("float", "2")
            assert scratch.xref_get_key(props_xref, "X") == ("int", "2")
            assert page_fingerprint(scratch, scratch[0]) == page_fingerprint(
                doc, doc[0]
            )
        finally:
            scratch.close()
    finally:
        doc.close()


def _folded(kind: str, value: str) -> str:
    digest = hashlib.sha256()
    _fold_canonical_value(digest, None, kind, value)  # type: ignore[arg-type]
    return digest.hexdigest()


def test_scalar_fold_is_by_numeric_value_not_by_kind_spelling():
    """RED before the fix: the Type0 scalar branch folded ``kind:value``."""
    assert _folded("float", "1") == _folded("int", "1")
    assert _folded("float", "1.000") == _folded("int", "1")
    assert _folded("float", "-0") == _folded("int", "0")
    assert _folded("float", ".5") == _folded("float", "0.50")
    # Guards: no tolerance, no rounding, and non-numerics keep their kind.
    assert _folded("float", ".999999") != _folded("int", "1")
    assert _folded("float", "1.0000000000000000000000000000001") != _folded(
        "int", "1"
    )
    assert _folded("float", ".5") != _folded("int", "1")
    assert _folded("int", "10") != _folded("int", "1")
    assert _folded("float", "-1") != _folded("int", "1")
    assert _folded("name", "/1") != _folded("int", "1")
    assert _folded("string", "1") != _folded("int", "1")


@pytest.mark.parametrize(
    "gs_body",
    [
        _OPAQUE_GS.replace("/CA 1.0", "/CA 0.999999"),
        _OPAQUE_GS.replace("/CA 1.0", "/CA 0.5"),
        _OPAQUE_GS.replace("/LW 2.0", "/LW 2.5"),
    ],
    ids=["ca-0.999999", "ca-0.5", "lw-2.5"],
)
def test_a_changed_extgstate_value_still_goes_stale_across_the_round_trip(gs_body):
    """GUARD: live fingerprint at ``/CA 1.0 /LW 2.0`` vs the scratch copy of a
    page that genuinely differs -- the canonical fold must not merge them."""
    live = _numeric_doc()
    changed = _numeric_doc(gs_body)
    try:
        assert page_fingerprint(live, live[0]) != _scratch_fingerprint(changed)
        # And in place on one document, the stale check's actual shape.
        before = page_fingerprint(live, live[0])
        live.update_object(_gs_xref(live), gs_body)
        assert page_fingerprint(live, live[0]) != before
    finally:
        live.close()
        changed.close()


def test_a_changed_font_widths_entry_still_goes_stale():
    """GUARD for the raw-object fallback the fix leaves untouched: an
    indirect ``/Widths`` array of integral reals round-trips byte-stably
    (MuPDF prints ``[ 667 ]`` on both sides, the kind never reaches the
    text) and a changed entry still moves the fingerprint."""
    live = _numeric_doc("<< /Type /ExtGState /CA 0.5 >>", widths="[ 667.0 ]")
    changed = _numeric_doc("<< /Type /ExtGState /CA 0.5 >>", widths="[ 666.0 ]")
    try:
        live_fp = page_fingerprint(live, live[0])
        assert _scratch_fingerprint(live) == live_fp
        assert _scratch_fingerprint(changed) != live_fp
    finally:
        live.close()
        changed.close()


def test_a_changed_content_stream_byte_still_goes_stale():
    """GUARD: one content-stream byte differs, nothing else does."""
    live = _numeric_doc()
    changed = _numeric_doc(stream=_NUM_STREAM.replace(b"2024", b"2023"))
    try:
        assert page_fingerprint(live, live[0]) != _scratch_fingerprint(changed)
    finally:
        live.close()
        changed.close()


def _prepare_numeric(
    doc: fitz.Document, engine: TieredCommitEngine
) -> PreparedEdit | PlanRejection:
    return engine.prepare(
        doc[0],
        target_text=_NUM_TARGET,
        replacement_text=_NUM_REPLACEMENT,
        expected_origin=None,
    )


def test_engine_prepares_on_a_page_with_an_integral_real_extgstate():
    """RED before the fix: ``prepare`` refused this page as
    ``verification_failed`` (candidate failed to apply on scratch: page
    fingerprint changed) although nothing about it had changed."""
    doc = _numeric_doc()
    try:
        before = page_fingerprint(doc, doc[0])
        prepared = _prepare_numeric(doc, TieredCommitEngine(doc))
        assert isinstance(prepared, PreparedEdit), (
            f"{prepared.reason} | {prepared.detail}"
            if isinstance(prepared, PlanRejection)
            else prepared
        )
        assert prepared.page_fingerprint == before
        assert page_fingerprint(doc, doc[0]) == before, "prepare mutated the page"

        # Positive control for the stale test below: on the UNMUTATED page
        # the same plan really commits, so a STALE_PLAN there is the /CA
        # change and nothing else about this fixture.
        stream_xref = doc[0].get_contents()[0]
        stream_before = doc.xref_stream(stream_xref)
        outcome = TieredCommitEngine(doc).commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED, outcome
        assert doc.xref_stream(stream_xref) != stream_before
        assert _NUM_REPLACEMENT in doc[0].get_text()
    finally:
        doc.close()


def test_engine_commit_refuses_as_stale_after_the_extgstate_opacity_changes():
    """A plan prepared at ``/CA 1.0`` must not commit at ``/CA 0.5``: the
    commit-time stale check is exactly as strict as before the fix.  (Red
    before the fix only at its ``prepare`` precondition.)"""
    doc = _numeric_doc()
    try:
        engine = TieredCommitEngine(doc)
        prepared = _prepare_numeric(doc, engine)
        assert isinstance(prepared, PreparedEdit), prepared
        stream_xref = doc[0].get_contents()[0]
        stream_before = doc.xref_stream(stream_xref)

        doc.update_object(_gs_xref(doc), _OPAQUE_GS.replace("/CA 1.0", "/CA 0.5"))

        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.STALE_PLAN, outcome
        assert doc.xref_stream(stream_xref) == stream_before
    finally:
        doc.close()
