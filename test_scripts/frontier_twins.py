"""Synthetic CI twins of the true-text frontier loop (slice I0b).

``test_files/`` is gitignored and CI deselects ``needs_fixtures``, so CI sees only twins: small
synthetic documents whose ``TieredCommitEngine.prepare`` outcome is pinned.  Design:
``plans/true-text-frontier-design.md`` "Synthetic CI twins" and ``plans/true-text-i0b.md`` section 4.

Stage S2 (this file) holds the skeleton only:

* :class:`TwinSpec` and the :data:`TWINS` registry (class id -> specs) with its lookups.  The
  entries are the simple-font twins of ``simple_font_fixture_builder`` (F30W and F30B); each ``expected`` is
  what ``prepare`` + ``commit`` do AT HEAD, observed and not assumed.  A ``"COMMITTED"`` negative
  twin is the red of the slice named in ``owned_until_slice``: it is retired by name in that
  slice's commit, and any other flip is a regression.
* :class:`OracleTwinSpec`, the shape of the ORACLE twins (i)-(xii) of plan section 4, and the
  :data:`ORACLE_TWINS` (empty in S2; the eight S3a twins are below).

Stage S3a (this file, below the registry): the ORACLE-twin runner (:func:`twin_runs`, :func:`judge`,
:func:`run_oracle_twin`), the experiment splice :func:`e_kern`, the helper adapters
:data:`ORACLE_HELPERS` (growth and neighbours; S3b adds the byte, wrapper, count and glyph-identity
helpers) and the eight growth/neighbour twins (vi, vii, viii, viii-b, ix, x, xi, xii) in
:data:`ORACLE_TWINS`.  S2's observations of those twins' product paths live as a pinned table in
``test_text_commit_frontier_twins.py``; each became an ``OracleTwinSpec.product_expected``.  Not here
yet: the byte, wrapper, count and glyph-identity twins (i-v) of S3b.

Stage S3b (below): the four adapters ``stream_range``, ``wrapper``, ``counts`` and ``glyph_identity``, the
post-commit defects of twins (i)-(iv) (``OracleTwinSpec.defect`` returns the extra stream xrefs it rewrote),
the two vacuity rules of :func:`judge` and twins i-v (plus three guards) in front of vi-xii.
"""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from model.text_commit.dto import CommitStatus, StreamReplacement
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.patch import build_kern_compensated_transplant
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream, splice_stream
from model.text_commit.plan import (
    PlanRejection,
    PreparedEdit,
    _advance,
    _grown_verify_bbox,
    _painter_advance,
)
from model.text_commit.replay import ShowOp, replay_page_streams
from model.text_commit.transforms import PageVisualFrame
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts import stream_storage_fixtures as ssf
from test_scripts import true_text_acceptance_helpers as helpers
from test_scripts import type0_fixture_builder as tb

#: The shared simple-font twin text.  Replacing ``B`` by ``A`` is advance-neutral in every builder
#: kind (all glyphs advance the same), a Tier 0 candidate, and writes the byte 0x41 whose glyph the
#: two "lying" kinds draw as B.
TWIN_TARGET = "Level B 2024"
TWIN_REPLACEMENT = "Level A 2024"

COMMITTED = "COMMITTED"


@dataclass(frozen=True)
class TwinSpec:
    """One synthetic twin: build a document, edit ``target`` -> ``replacement``, expect ``expected``.

    ``expected`` is ``"COMMITTED"`` (``prepare`` returns a ``PreparedEdit`` and ``commit`` reports
    ``CommitStatus.COMMITTED``) or the ``RejectReason`` value of the ``PlanRejection``.
    ``polarity`` is ``"positive"`` (the edit should commit) or ``"negative"`` (it should be refused).
    ``owned_until_slice`` names the slice that makes ``expected`` flip; ``None`` for a guard.
    """

    twin_id: str
    class_id: str
    polarity: str
    build: Callable[[], fitz.Document]
    target: str
    replacement: str
    expected: str
    owned_until_slice: str | None


@dataclass(frozen=True)
class OracleTwinSpec:
    """Shape of an ORACLE twin (plan section 4): ``target`` -> ``replacement`` on the document ``build`` makes.

    ``paths`` is a subset of ``{"product", "experiment"}``; ``experiment`` is the experiment-path
    callable (``e_kern``: ``(source, show, target, replacement) -> (StreamReplacement, adv_old, adv_new)``)
    and ``defect`` the post-commit defect (applied after ``engine.commit`` and before the live render
    and ``saveIncr``) and returns the xrefs of any OTHER stream it rewrote (or ``None``); ``product_expected`` is ``"COMMITTED"``, a reject reason or ``None`` (no
    product path).  ``must_fail`` and ``must_pass`` both list the helpers by name (keys of
    :data:`ORACLE_HELPERS`): a helper in neither set is not asserted for that twin.  ``detail_heads``
    pins part of a failing detail: ``(helper name or "product", substring)``.
    """

    twin_id: str
    build: Callable[[], fitz.Document]
    target: str
    replacement: str
    paths: frozenset[str]
    experiment: Callable[..., tuple[StreamReplacement, float, float]] | None
    defect: Callable[[fitz.Document, PreparedEdit], frozenset[int] | None] | None
    product_expected: str | None
    must_fail: frozenset[str]
    must_pass: frozenset[str]
    detail_heads: tuple[tuple[str, str], ...] = ()


def _simple(kind: str) -> Callable[[], fitz.Document]:
    def build() -> fitz.Document:
        return sfb.build_embedded_simple_fixture(kind, TWIN_TARGET).doc

    return build


def _simple_twin(
    kind: str, class_id: str, polarity: str, expected: str, owned_until_slice: str | None
) -> TwinSpec:
    return TwinSpec(
        twin_id=f"simple_{kind}",
        class_id=class_id,
        polarity=polarity,
        build=_simple(kind),
        target=TWIN_TARGET,
        replacement=TWIN_REPLACEMENT,
        expected=expected,
        owned_until_slice=owned_until_slice,
    )


#: class id -> specs.  Observed at HEAD (413557f), not assumed; the test file records the table.
#: Classes follow brief v5: F30W = embedded with a WinAnsi/MacRoman/Standard /Encoding, F30B =
#: embedded with no /Encoding (built-in encoding or symbolic cmap; the H-F30b false-safe class).
TWINS: dict[str, tuple[TwinSpec, ...]] = {
    "F30W": (
        _simple_twin("winansi", "F30W", "positive", COMMITTED, None),
        _simple_twin("post3_cmap31", "F30W", "positive", COMMITTED, None),
    ),
    "F30B": (
        # design :203 expected COMMITTED; HEAD refuses it (a face with only a (3,0) cmap has no
        # Unicode glyph lookup, so the product's own coverage rule fails closed).  I1's G1'
        # (font_builtin_encoding_unproven) decides what it becomes.
        _simple_twin("symbolic_ascii", "F30B", "positive", "encoding_failed", "I1"),
        # the false-safe twins.  HEAD refuses wrongname only because MuPDF extracts a glyph's text
        # from its name (the committed byte reads back as B); no glyph-identity gate exists yet, so
        # the reason flips in I1.  HEAD COMMITS tounicode_lie: I1's G1' red.
        _simple_twin("symbolic_wrongname", "F30B", "negative", "verification_failed", "I1"),
        _simple_twin("tounicode_lie", "F30B", "negative", COMMITTED, "I1"),
        # the nameless shapes (post format 3, no ToUnicode): MuPDF reads the CODE BYTE as the text,
        # so nothing in the product can see the wrong outline.  The guard commits (gid A); the
        # wrongglyph twin COMMITS a wrong glyph (gid B): I1's G1' red.
        _simple_twin("symbolic_post3", "F30B", "positive", COMMITTED, None),
        _simple_twin("symbolic_post3_wrongglyph", "F30B", "negative", COMMITTED, "I1"),
    ),
}


def all_twins() -> tuple[TwinSpec, ...]:
    return tuple(spec for specs in TWINS.values() for spec in specs)


def twins_for(class_id: str) -> tuple[TwinSpec, ...]:
    return TWINS.get(class_id, ())


def twin(twin_id: str) -> TwinSpec:
    for spec in all_twins():
        if spec.twin_id == twin_id:
            return spec
    raise KeyError(twin_id)


# ----------------------------------------------------------------------------------------------
# S3a: the ORACLE-twin runner
# ----------------------------------------------------------------------------------------------
#: A two-rectangle union clip: its bounding box spans the page, but the 105..107.2 pt gap is outside the
#: path.  Prepended before the show of "Figure 1" at 6 pt, the tenth glyph of "Figure 123" (ink
#: 105.16..106.99 pt) is committed at Tier 1 and draws nothing (twin xii).
GAP_CLIP = "0 0 105 842 re 107.2 0 487.8 842 re W n"


def prepend_clip(fixture: sfb.SimpleFixture, clip_path: str) -> sfb.SimpleFixture:
    """``clip_path`` (path operators ending in ``W n``) prepended before the show."""
    fixture.doc.update_stream(
        fixture.content_xref, clip_path.encode("ascii") + b" " + fixture.content_bytes()
    )
    return fixture


def located_arguments(doc: fitz.Document, target: str) -> dict:
    """``expected_origin`` / ``target_bbox`` exactly as the acceptance harness hands them to ``prepare``:
    the texttrace run of ``target`` turned through ``frame.quarter_turn`` (``helpers._prepare``)."""
    page = doc[0]
    show = helpers._shows(doc, 0)[0]
    with helpers._measurement_copy(doc) as measured:
        trace = helpers._trace_for(measured[0], show, target)
    frame = helpers.visual_frame(page)
    return {
        "expected_origin": tuple(fitz.Point(trace["chars"][0][2]) * frame.quarter_turn),
        "target_bbox": tuple(fitz.Rect(trace["bbox"]) * frame.quarter_turn),
    }


@dataclass
class Refusal:
    """The product path refused before any commit: no document exists to judge, only the reason."""

    twin_id: str
    reason: str
    detail: str
    path: str = "product"


@dataclass
class TwinRun:
    """One judged document pair.  ``source`` is the pristine pre-edit document (never mutated);
    ``after`` is the reopened committed file (product path) or the reopened spliced file (experiment).
    ``prepared`` is ``None`` on the experiment path; ``replacement`` is the stream splice that was applied
    (``prepared.replacement`` or the ``e_kern`` one) and ``replacement_text`` the new text; ``measurements`` is
    the helpers' sink (the neighbour and glyph-identity measurements)."""

    twin_id: str
    path: str
    source: fitz.Document
    after: fitz.Document
    frame: PageVisualFrame
    before_show: ShowOp
    after_show: ShowOp
    target_vis: tuple[float, float, float, float]
    verify_vis: tuple[float, float, float, float]
    adv_old: float
    prepared: PreparedEdit | None
    code_bytes: int
    replacement: StreamReplacement
    replacement_text: str
    measurements: dict = field(default_factory=dict)


def _growth_adapter(run: TwinRun) -> str | None:
    return helpers.check_growth_zone_was_blank(
        run.source,
        0,
        run.before_show,
        run.frame,
        run.target_vis,
        run.verify_vis,
        run.adv_old,
        prepared=run.prepared,
        x_pre=0.0,
        k_inner=0.0,
    )


def _neighbours_adapter(run: TwinRun) -> str | None:
    return helpers.check_neighbour_glyphs_unchanged(
        run.source,
        run.after,
        0,
        [helpers.edited_show(run.before_show, run.after_show, code_bytes=run.code_bytes)],
        kind="positive",
        frame=run.frame,
        measurements=run.measurements,
    )


def _stream_range_adapter(run: TwinRun) -> str | None:
    rep = run.replacement
    return helpers.check_target_stream_changed_only_within(
        run.source.xref_stream(rep.stream_xref) or b"",
        run.after.xref_stream(rep.stream_xref) or b"",
        [(rep.start, rep.end, rep.start + len(rep.replacement_bytes))],
    )


def _wrapper_adapter(run: TwinRun) -> str | None:
    rep = run.replacement
    before = dict(helpers.page_streams(run.source, 0))
    after = dict(helpers.page_streams(run.after, 0))
    return helpers.check_wrapper_bytes_unchanged(
        before,
        after,
        replay_page_streams(list(before.items())),
        replay_page_streams(list(after.items())),
        run.before_show.seq,
        rep.stream_xref,
        len(rep.replacement_bytes) - (rep.end - rep.start),
    )


def _counts_adapter(run: TwinRun) -> str | None:
    return helpers.check_show_and_operator_counts_equal(
        helpers.page_streams(run.source, 0), helpers.page_streams(run.after, 0)
    )


def _glyph_identity_adapter(run: TwinRun) -> str | None:
    edited = helpers.edited_show(run.before_show, run.after_show, code_bytes=run.code_bytes)
    inputs = helpers.glyph_identity_inputs(
        run.after, 0, edited, frame=run.frame, code_bytes=run.code_bytes
    )
    if isinstance(inputs, str):
        return inputs
    codes, gids = inputs
    assert run.before_show.font_resource is not None
    capability = DocumentFontRegistry(run.source).capability(run.source[0], run.before_show.font_resource)
    assert capability is not None
    try:
        return helpers.check_glyph_identity(
            run.after,
            0,
            capability.font_xref,
            run.replacement_text,
            "type0" if run.code_bytes == 2 else "simple",
            gid_after=gids,
            codes=codes,
            measurements=run.measurements,
        )
    except helpers.IndependentLegUnavailable as exc:
        return f"{helpers.GLYPH_LEG_UNAVAILABLE}: {exc}"


#: helper name -> adapter over a :class:`TwinRun`.  Each adapter resolves the helper at CALL time
#: (``helpers.<name>``), so a monkeypatched helper reaches it (the non-vacuity tests).
ORACLE_HELPERS: dict[str, Callable[[TwinRun], str | None]] = {
    "growth": _growth_adapter,
    "neighbours": _neighbours_adapter,
    "stream_range": _stream_range_adapter,
    "wrapper": _wrapper_adapter,
    "counts": _counts_adapter,
    "glyph_identity": _glyph_identity_adapter,
}


def e_kern(
    source: fitz.Document, show: ShowOp, target: str, replacement: str
) -> tuple[StreamReplacement, float, float]:
    """The experiment splice ``[<new> K] TJ`` over the whole show, built from the product's own functions.

    Returns ``(replacement, adv_old, adv_new)``: ``adv_old`` is the painter advance of ``target``,
    ``adv_new`` the new text's advance under the same text state; the kern ``K`` keeps whatever follows
    the show exactly where it was (so growth overprints it)."""
    assert show.font_resource is not None
    capability = DocumentFontRegistry(source).capability(source[0], show.font_resource)
    assert capability is not None
    if capability.subtype == "Type0":
        assert capability.cid is not None
        cids = tuple(tb.cid_for(char) for char in replacement)
        encoded = tb.encode_cids(replacement)
        adv_old = _painter_advance(capability, show, target)
        adv_new = capability.cid.advance_points(cids, show.font_size, show.char_spacing)
    else:
        encoded = capability.encode_simple(replacement)
        assert encoded is not None, replacement
        adv_old = _advance(capability, target, show.font_size, show.char_spacing, show.word_spacing)
        adv_new = _advance(capability, replacement, show.font_size, show.char_spacing, show.word_spacing)
    assert adv_old is not None and adv_new is not None
    stream = source.xref_stream(show.stream_xref)
    assert stream is not None
    rep = build_kern_compensated_transplant(
        stream,
        show,
        replacement_encoded=encoded,
        source_advance=adv_old,
        replacement_advance=adv_new,
        string_kind=show.string_kind,
    )
    return rep, adv_old, adv_new


def _code_bytes(source: fitz.Document, show: ShowOp) -> int:
    assert show.font_resource is not None
    capability = DocumentFontRegistry(source).capability(source[0], show.font_resource)
    assert capability is not None
    return 2 if capability.subtype == "Type0" else 1


def _product_run(
    spec: OracleTwinSpec, source: fitz.Document, src_path: Path, workdir: Path
) -> TwinRun | Refusal:
    product_path = workdir / f"{spec.twin_id}-product.pdf"
    shutil.copyfile(src_path, product_path)
    candidate = fitz.open(str(product_path))
    try:
        engine = TieredCommitEngine(candidate, max_tier=1)
        prepared = engine.prepare(
            candidate[0],
            target_text=spec.target,
            replacement_text=spec.replacement,
            **located_arguments(candidate, spec.target),
        )
        if isinstance(prepared, PlanRejection):
            return Refusal(spec.twin_id, str(prepared.reason), prepared.detail)
        snapshot = helpers._object_snapshot(source)
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED, (spec.twin_id, outcome.status)
        extra = spec.defect(candidate, prepared) if spec.defect is not None else None
        changed = {prepared.stream_xref} | set(extra or ())
        helpers._assert_only_target_streams_changed(snapshot, candidate, changed)
        live_renders = {0: bytes(candidate[0].get_pixmap(alpha=False).samples)}
        candidate.saveIncr()
    finally:
        candidate.close()
    reopened = fitz.open(str(product_path))
    try:
        helpers._assert_only_target_streams_changed(snapshot, reopened, changed, semantic=True)
        helpers._assert_reopened_renders_match_live(live_renders, reopened)
        frame = helpers.visual_frame(source[0])
        before_shows, after_shows = helpers._shows(source, 0), helpers._shows(reopened, 0)
        assert len(after_shows) == len(before_shows), spec.twin_id
        for before, after in zip(before_shows[1:], after_shows[1:], strict=True):
            assert after.origin_user == before.origin_user, (spec.twin_id, before.seq)
        with helpers._measurement_copy(source) as before_copy:
            before_trace = helpers._trace_for(before_copy[0], before_shows[0], spec.target)
            before_pixels = helpers._pixmap_array(before_copy[0]).copy()
        with helpers._measurement_copy(reopened) as after_copy:
            after_trace = helpers._trace_for(after_copy[0], after_shows[0], spec.replacement)
            after_pixels = helpers._pixmap_array(after_copy[0]).copy()
        helpers._assert_pixels_changed_only_inside_masks(
            spec.twin_id,
            0,
            before_pixels,
            after_pixels,
            [helpers.halo_mask(before_trace["bbox"], after_trace["bbox"], frame)],
        )
        return TwinRun(
            twin_id=spec.twin_id,
            path="product",
            source=source,
            after=reopened,
            frame=frame,
            before_show=before_shows[0],
            after_show=after_shows[0],
            target_vis=tuple(prepared.target_bbox_page),  # type: ignore[arg-type]
            verify_vis=tuple(prepared.effective_verify_bbox),  # type: ignore[arg-type]
            adv_old=float(prepared.source_advance),
            prepared=prepared,
            code_bytes=_code_bytes(source, before_shows[0]),
            replacement=prepared.replacement,
            replacement_text=spec.replacement,
        )
    except BaseException:
        reopened.close()
        raise


def _experiment_run(
    spec: OracleTwinSpec, source: fitz.Document, src_path: Path, workdir: Path
) -> TwinRun:
    assert spec.experiment is not None, spec.twin_id
    show = helpers._shows(source, 0)[0]
    frame = helpers.visual_frame(source[0])
    target_vis = tuple(located_arguments(source, spec.target)["target_bbox"])
    rep, adv_old, adv_new = spec.experiment(source, show, spec.target, spec.replacement)
    stream = source.xref_stream(show.stream_xref)
    assert stream is not None
    new_stream = splice_stream(stream, [rep])
    scratch_path = workdir / f"{spec.twin_id}-exp.pdf"
    shutil.copyfile(src_path, scratch_path)
    scratch = fitz.open(str(scratch_path))
    try:
        scratch.update_stream(show.stream_xref, new_stream)
        scratch.saveIncr()
    finally:
        scratch.close()
    reopened = fitz.open(str(scratch_path))
    try:
        growth = max(0.0, adv_new - adv_old) * (show.hscale / 100.0)  # plan.py Tier 1: growth * th
        verify_vis = _grown_verify_bbox(source[0], show, target_vis, growth, frame=frame)  # type: ignore[arg-type]
        return TwinRun(
            twin_id=spec.twin_id,
            path="experiment",
            source=source,
            after=reopened,
            frame=frame,
            before_show=show,
            after_show=helpers._shows(reopened, 0)[0],
            target_vis=target_vis,  # type: ignore[arg-type]
            verify_vis=verify_vis,
            adv_old=float(adv_old),
            prepared=None,
            code_bytes=_code_bytes(source, show),
            replacement=rep,
            replacement_text=spec.replacement,
        )
    except BaseException:
        reopened.close()
        raise


def twin_runs(spec: OracleTwinSpec, workdir: Path) -> list[TwinRun | Refusal]:
    """Build ``spec``'s document and run every path.  The caller closes the documents with
    :func:`close_runs`.  ``source`` is opened from the built bytes and never mutated."""
    workdir.mkdir(parents=True, exist_ok=True)
    built = spec.build()
    data = built.tobytes()
    built.close()
    src_path = workdir / f"{spec.twin_id}-src.pdf"
    src_path.write_bytes(data)
    source = fitz.open("pdf", data)
    runs: list[TwinRun | Refusal] = []
    try:
        if "product" in spec.paths:
            runs.append(_product_run(spec, source, src_path, workdir))
        if "experiment" in spec.paths:
            runs.append(_experiment_run(spec, source, src_path, workdir))
    except BaseException:
        close_runs(runs)
        source.close()
        raise
    return runs


def close_runs(runs: list[TwinRun | Refusal]) -> None:
    seen: set[int] = set()
    for run in runs:
        if isinstance(run, Refusal):
            continue
        for doc in (run.after, run.source):
            if id(doc) not in seen:
                seen.add(id(doc))
                if not doc.is_closed:
                    doc.close()


def judge(spec: OracleTwinSpec, runs: list[TwinRun | Refusal]) -> list[str]:
    """Mismatches between what ``spec`` declares and what the helpers and the product did (empty = agree)."""
    mismatches: list[str] = []
    for run in runs:
        label = f"{spec.twin_id}/{run.path}"
        if isinstance(run, Refusal):
            if str(run.reason) != spec.product_expected:
                mismatches.append(f"{label}: product refused {run.reason}, expected {spec.product_expected}")
            for name, head in spec.detail_heads:
                if name == "product" and head not in run.detail:
                    mismatches.append(f"{label}: product detail lacks {head!r}")
            continue
        if run.path == "product" and spec.product_expected != COMMITTED:
            mismatches.append(f"{label}: product committed, expected {spec.product_expected}")
        for name in sorted(spec.must_fail | spec.must_pass):
            if name == "growth" and tuple(run.verify_vis) == tuple(run.target_vis):
                mismatches.append(f"{label}/{name}: no growth zone, the twin would pass vacuously")
                continue
            if name == "wrapper" and not replay_page_streams(
                helpers.page_streams(run.source, 0)
            ).wrappers_for(run.before_show):
                mismatches.append(f"{label}/{name}: no wrapper on the edited show, vacuous")
                continue
            run.measurements.clear()
            detail = ORACLE_HELPERS[name](run)
            if name in spec.must_fail and detail is None:
                mismatches.append(f"{label}/{name}: expected fail, got pass")
            if name in spec.must_pass and detail is not None:
                mismatches.append(f"{label}/{name}: expected pass, got {detail}")
            if detail is not None:
                for head_name, head in spec.detail_heads:
                    if head_name == name and head not in detail:
                        mismatches.append(f"{label}/{name}: detail lacks {head!r}: {detail}")
            if name == "neighbours" and name in spec.must_pass and detail is None:
                if run.measurements.get("target_glyphs_ink_checked", 0) < 1:
                    mismatches.append(f"{label}/{name}: passed without checking any target glyph's ink")
            if name == "glyph_identity" and name in spec.must_pass and detail is None:
                if run.measurements.get("glyphs_checked", 0) < 1:
                    mismatches.append(f"{label}/{name}: passed without checking any glyph")
    return mismatches


def run_oracle_twin(spec: OracleTwinSpec, workdir: Path) -> list[str]:
    runs = twin_runs(spec, workdir)
    try:
        return judge(spec, runs)
    finally:
        close_runs(runs)


# ----------------------------------------------------------------------------------------------
# S3a: twins (vi)-(xii) (plan section 4)
# ----------------------------------------------------------------------------------------------
def _frozen(*names: str) -> frozenset[str]:
    return frozenset(names)


def _identity_h(
    *,
    tail: bool = False,
    rotate: int = 0,
    raw: str | None = None,
    far_show: bool = False,
    oc_layer: str | None = None,
    tounicode_swap: bool = False,
) -> Callable[[], fitz.Document]:
    """``far_show`` appends one unrelated show far from the edit (y = 500), so the neighbour legs have
    untouched glyphs to compare (glyphs_paired > 0) on twins whose page would otherwise hold only the edit.

    ``oc_layer`` wraps the whole content in ``/OC /OC1 BDC ... EMC`` (an optional-content layer that is ON):
    ``"inline"`` keeps the EMC in the same stream; ``"split"`` moves it into a second content stream
    (``/Contents [A B]``, B = ``EMC``), the shape of a producer that closes a wrapper in the next stream.

    ``tounicode_swap`` makes the ToUnicode CMap claim each of the first two characters of the text for the
    other's CID (the font program is untouched), so the product reads the page as the swapped text and
    encodes a replacement through the lie."""
    if oc_layer not in (None, "inline", "split"):
        raise ValueError(oc_layer)

    def build() -> fitz.Document:
        fixture = tb.build_identity_h_fixture(
            rotate=rotate, tail_text=tb.TAIL_TEXT if tail else None
        )
        if raw is not None:
            tb.append_page_content(fixture, raw)
        if far_show:
            hex_text = tb.encode_cids(tb.TAIL_TEXT).hex().upper()
            tb.append_page_content(
                fixture, f"BT /{fixture.resource_name} 12 Tf 1 0 0 1 72 500 Tm <{hex_text}> Tj ET"
            )
        if tounicode_swap:
            mappings = tb.default_tounicode_mappings(fixture, tb.TAIL_TEXT)
            first, second = mappings[0][0], mappings[1][0]
            mappings[0], mappings[1] = (first, mappings[1][1]), (second, mappings[0][1])
            tb.write_minimal_tounicode(fixture, mappings)
        if oc_layer is not None:
            tb.install_oc_layer(fixture, name="OC1", label="TwinLayer", on=True)
            tb.wrap_content_in_marked_content(
                fixture, "/OC /OC1 BDC", suffix="" if oc_layer == "split" else " EMC"
            )
            if oc_layer == "split":
                doc = fixture.doc
                closer = doc.get_new_xref()
                doc.update_object(closer, "<<>>")
                doc.update_stream(closer, b"EMC")
                doc.xref_set_key(
                    fixture.page.xref, "Contents", f"[{fixture.content_xref} 0 R {closer} 0 R]"
                )
        return fixture.doc

    return build


def _odd_page_with_tail() -> fitz.Document:
    """One combined odd page: /UserUnit 2, an offset CropBox and /Rotate 90 (viii-b)."""
    fixture = tb.build_identity_h_fixture(tail_text=tb.TAIL_TEXT)
    page = fixture.doc[0]
    fixture.doc.xref_set_key(page.xref, "UserUnit", "2")
    page.set_cropbox(fitz.Rect(20, 30, 575, 800))
    page.set_rotation(90)
    return fixture.doc


def _simple_kind(
    kind: str,
    text: str,
    *,
    fontsize: float = 12.0,
    overhang: int | None = None,
    clip_path: str | None = None,
    far_show: bool = False,
) -> Callable[[], fitz.Document]:
    def build() -> fitz.Document:
        fixture = sfb.build_embedded_simple_fixture(kind, text, fontsize=fontsize, overhang=overhang)
        if clip_path is not None:
            prepend_clip(fixture, clip_path)
        if far_show:  # one unrelated show far from the edit: untouched glyphs for the neighbour legs
            fixture.doc.update_stream(
                fixture.content_xref,
                fixture.content_bytes() + f" BT /{fixture.resource_name} 12 Tf 72 500 Td (Tail) Tj ET".encode("ascii"),
            )
        return fixture.doc

    return build


# ----------------------------------------------------------------------------------------------
# S3b: post-commit defects of twins (i)-(iv) and the twins (i)-(v) (plan section 4)
# ----------------------------------------------------------------------------------------------
def _defect_flip_leading_space(doc: fitz.Document, prepared: PreparedEdit) -> frozenset[int] | None:
    """(i) The first whitespace byte of the stream (before the edit) becomes a newline: replay, render and
    the token counts are identical, so only the byte-range check can see it (``prefix_changed:``)."""
    rep = prepared.replacement
    data = doc.xref_stream(rep.stream_xref)
    assert data is not None
    token = next(t for t in lex_content_stream(data) if t.kind is TokenKind.WHITESPACE)
    assert data[token.start] == 0x20 and token.end <= rep.start, (token, rep.start)
    doc.update_stream(rep.stream_xref, data[: token.start] + b"\n" + data[token.start + 1 :])
    return None


def _defect_drop_closing_emc(doc: fitz.Document, prepared: PreparedEdit) -> frozenset[int] | None:
    """(ii) The wrapper's closing ``EMC`` (the stream's last token, in the edited stream) is deleted: the
    render is unchanged (observed), the wrapper stays open.  The cross-stream shape (EMC in a second content
    stream) is refused by the product (``mc_splice_crosses_wrapper_boundary``), see the premise test."""
    rep = prepared.replacement
    data = doc.xref_stream(rep.stream_xref)
    assert data is not None and data.endswith(b" EMC"), rep.stream_xref
    replay = replay_page_streams(helpers.page_streams(doc, 0))
    (wrapper,) = replay.wrappers_for(replay.shows[0])
    assert wrapper.closed and wrapper.close_stream_xref == rep.stream_xref, wrapper
    assert wrapper.close_op_start == len(data) - 3, (wrapper.close_op_start, len(data))
    doc.update_stream(rep.stream_xref, data[:-4])
    return None


def _defect_ink_beside_the_edit(doc: fitz.Document, prepared: PreparedEdit) -> frozenset[int] | None:
    """(iii) A 1 pt black square appended after the stream's last operator, 0.5 pt past the target's right
    edge: inside the 2 pt halo and over the first tail glyph, so neighbours must still pass."""
    rep = prepared.replacement
    data = doc.xref_stream(rep.stream_xref)
    assert data is not None
    box = prepared.target_bbox_page
    doc.update_stream(rep.stream_xref, data + f" q 0 g {box[2] + 0.5:.3f} 702 1 1 re f Q".encode("ascii"))
    return None


def _defect_white_over_the_edit(doc: fitz.Document, prepared: PreparedEdit) -> frozenset[int] | None:
    """(iv) White painted over the new glyphs (target box grown by 0.5 pt; unrotated page: visual = base):
    the glyphs are still in the trace and the stream, but no ink lands."""
    rep = prepared.replacement
    data = doc.xref_stream(rep.stream_xref)
    assert data is not None
    x0, y0, x1, y1 = prepared.target_bbox_page
    height = doc[0].rect.height
    patch = f" q 1 g {x0 - 0.5:.3f} {height - y1 - 0.5:.3f} {x1 - x0 + 1:.3f} {y1 - y0 + 1:.3f} re f Q"
    doc.update_stream(rep.stream_xref, data + patch.encode("ascii"))
    return None


_BYTE_LEGS = ("stream_range", "counts", "glyph_identity")
_TE = (tb.CJK_TEXT, tb.REPLACEMENT_EQUAL_ADVANCE)
_LEVEL_C = "Level C 2024"
#: what a reader of the swapped-ToUnicode page sees where the program draws ``CJK_TEXT`` (first two characters swapped)
TYPE0_LIE_TARGET = tb.CJK_TEXT[1] + tb.CJK_TEXT[0] + tb.CJK_TEXT[2:]

_S3B_TWINS: tuple[OracleTwinSpec, ...] = (
    OracleTwinSpec(
        "i",
        _identity_h(far_show=True),
        *_TE,
        _frozen("product"),
        None,
        _defect_flip_leading_space,
        COMMITTED,
        _frozen("stream_range"),
        _frozen("counts", "neighbours", "glyph_identity"),
        (("stream_range", "prefix_changed:"),),
    ),
    OracleTwinSpec(
        "ii",
        _identity_h(far_show=True, oc_layer="inline"),
        *_TE,
        _frozen("product"),
        None,
        _defect_drop_closing_emc,
        COMMITTED,
        _frozen("wrapper", "counts", "stream_range"),
        _frozen("neighbours", "glyph_identity"),
        (("wrapper", "close:"), ("counts", "operators:"), ("stream_range", "suffix_changed:")),
    ),
    OracleTwinSpec(
        "iii",
        _identity_h(tail=True, oc_layer="inline"),
        *_TE,
        _frozen("product"),
        None,
        _defect_ink_beside_the_edit,
        COMMITTED,
        _frozen("stream_range", "counts"),
        _frozen("wrapper", "neighbours", "glyph_identity"),
        (("stream_range", "suffix_changed:"), ("counts", "operators:")),
    ),
    OracleTwinSpec(
        "iv",
        _identity_h(far_show=True),
        *_TE,
        _frozen("product"),
        None,
        _defect_white_over_the_edit,
        COMMITTED,
        _frozen("stream_range", "counts", "neighbours"),
        _frozen("glyph_identity"),
        (("stream_range", "suffix_changed:"), ("counts", "operators:"), ("neighbours", "ink_not_landed:")),
    ),
    OracleTwinSpec(
        "v",
        _simple_kind("tounicode_lie", _LEVEL_C, far_show=True),
        _LEVEL_C,
        TWIN_REPLACEMENT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen("glyph_identity"),
        _frozen("stream_range", "counts", "neighbours"),
        (("glyph_identity", "glyph_name_agl: leg_char_differs:"),),
    ),
    OracleTwinSpec(
        "v-b",
        _simple_kind("symbolic_post3_wrongglyph", _LEVEL_C, far_show=True),
        _LEVEL_C,
        TWIN_REPLACEMENT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen("glyph_identity"),
        _frozen("stream_range", "counts", "neighbours"),
        (("glyph_identity", "cmap_31_reverse: leg_char_differs:"),),
    ),
    OracleTwinSpec(
        "v-type0",
        _identity_h(far_show=True, tounicode_swap=True),
        TYPE0_LIE_TARGET,
        tb.CJK_TEXT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen("glyph_identity"),
        _frozen("stream_range", "counts", "neighbours"),
        (("glyph_identity", "cid_program_cmap: leg_char_differs:"),),
    ),
    OracleTwinSpec(
        "v-guard-post3",
        _simple_kind("symbolic_post3", TWIN_TARGET, far_show=True),
        TWIN_TARGET,
        TWIN_REPLACEMENT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _frozen(*_BYTE_LEGS, "neighbours"),
    ),
    OracleTwinSpec(
        "v-guard-cmap31",
        _simple_kind("post3_cmap31", TWIN_TARGET, far_show=True),
        TWIN_TARGET,
        TWIN_REPLACEMENT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _frozen(*_BYTE_LEGS, "neighbours"),
    ),
    OracleTwinSpec(
        "v-guard-std14",
        lambda: ssf.open_case("a"),
        ssf.TARGET,
        ssf.REPLACEMENT,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _frozen(*_BYTE_LEGS, "neighbours"),
    ),
)


_GROWTH_FAILS_ON_THE_TAIL = (("growth", "glyphs:"), ("neighbours", "overlap:"))
_BOTH = _frozen("growth", "neighbours")
#: D8: the S3a twins also judge the byte, count and glyph-identity helpers (x refuses before any commit, so it stays as is)
_BOTH_PLUS = _frozen("growth", "neighbours", *_BYTE_LEGS)

_S3A_TWINS: tuple[OracleTwinSpec, ...] = (
    OracleTwinSpec(
        "vi",
        _identity_h(tail=True),
        tb.CJK_TEXT,
        tb.REPLACEMENT_LONGER,
        _frozen("experiment"),
        e_kern,
        None,
        None,
        _BOTH,
        _frozen(*_BYTE_LEGS),
        _GROWTH_FAILS_ON_THE_TAIL,
    ),
    OracleTwinSpec(
        "vii",
        _identity_h(raw="q 0.5 w 20 20 555 802 re S Q", far_show=True),
        tb.CJK_TEXT,
        tb.REPLACEMENT_LONGER,
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _BOTH_PLUS,
    ),
    OracleTwinSpec(
        "viii",
        _identity_h(tail=True, rotate=270),
        tb.CJK_TEXT,
        tb.REPLACEMENT_LONGER,
        _frozen("experiment"),
        e_kern,
        None,
        None,
        _BOTH,
        _frozen(*_BYTE_LEGS),
        _GROWTH_FAILS_ON_THE_TAIL,
    ),
    OracleTwinSpec(
        "viii-b",
        _odd_page_with_tail,
        tb.CJK_TEXT,
        tb.REPLACEMENT_LONGER,
        _frozen("experiment"),
        e_kern,
        None,
        None,
        _BOTH,
        _frozen(*_BYTE_LEGS),
        _GROWTH_FAILS_ON_THE_TAIL,
    ),
    OracleTwinSpec(
        "ix",
        _simple_kind("winansi", "Figure", overhang=300, far_show=True),
        "Figure",
        "Figure f ",
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _BOTH_PLUS,
    ),
    OracleTwinSpec(
        "x",
        _identity_h(raw="q 0 g 133 696 0.5 12 re f Q"),
        tb.CJK_TEXT,
        tb.REPLACEMENT_LONGER,
        _frozen("product", "experiment"),
        e_kern,
        None,
        "growth_region_not_blank",
        _frozen("growth"),
        _frozen(),
        (("product", "raster:"), ("growth", "raster:")),
    ),
    OracleTwinSpec(
        "xi",
        _simple_kind("winansi", "Figure 1", fontsize=6.0, far_show=True),
        "Figure 1",
        "Figure 123",
        _frozen("product", "experiment"),
        e_kern,
        None,
        COMMITTED,
        _frozen(),
        _BOTH_PLUS,
    ),
    OracleTwinSpec(
        "xii",
        _simple_kind("winansi", "Figure 1", fontsize=6.0, clip_path=GAP_CLIP),
        "Figure 1",
        "Figure 123",
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen("neighbours"),
        _frozen("growth", *_BYTE_LEGS),
        (("neighbours", "ink_not_landed:"),),
    ),
)

ORACLE_TWINS: tuple[OracleTwinSpec, ...] = _S3B_TWINS + _S3A_TWINS
