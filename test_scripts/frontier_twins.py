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
from model.text_commit.pdf_lexer import splice_stream
from model.text_commit.plan import (
    PlanRejection,
    PreparedEdit,
    _advance,
    _grown_verify_bbox,
    _painter_advance,
)
from model.text_commit.replay import ShowOp
from model.text_commit.transforms import PageVisualFrame
from test_scripts import simple_font_fixture_builder as sfb
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
    and ``saveIncr``; S3b); ``product_expected`` is ``"COMMITTED"``, a reject reason or ``None`` (no
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
    defect: Callable[..., None] | None
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
    ``prepared`` is ``None`` on the experiment path; ``measurements`` is the neighbour helper's sink."""

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


#: helper name -> adapter over a :class:`TwinRun`.  Each adapter resolves the helper at CALL time
#: (``helpers.<name>``), so a monkeypatched helper reaches it (the non-vacuity tests).  S3b adds
#: ``stream_range``, ``wrapper``, ``counts`` and ``glyph_identity``.
ORACLE_HELPERS: dict[str, Callable[[TwinRun], str | None]] = {
    "growth": _growth_adapter,
    "neighbours": _neighbours_adapter,
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
        if spec.defect is not None:
            spec.defect(candidate, prepared)
        changed = {prepared.stream_xref}
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
    *, tail: bool = False, rotate: int = 0, raw: str | None = None, far_show: bool = False
) -> Callable[[], fitz.Document]:
    """``far_show`` appends one unrelated show far from the edit (y = 500), so the neighbour legs have
    untouched glyphs to compare (glyphs_paired > 0) on twins whose page would otherwise hold only the edit."""

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


def _simple_winansi(
    text: str,
    *,
    fontsize: float = 12.0,
    overhang: int | None = None,
    clip_path: str | None = None,
    far_show: bool = False,
) -> Callable[[], fitz.Document]:
    def build() -> fitz.Document:
        fixture = sfb.build_embedded_simple_fixture(
            "winansi", text, fontsize=fontsize, overhang=overhang
        )
        if clip_path is not None:
            prepend_clip(fixture, clip_path)
        if far_show:  # one unrelated show far from the edit: untouched glyphs for the neighbour legs
            fixture.doc.update_stream(
                fixture.content_xref,
                fixture.content_bytes() + f" BT /{fixture.resource_name} 12 Tf 72 500 Td (Tail) Tj ET".encode("ascii"),
            )
        return fixture.doc

    return build


_GROWTH_FAILS_ON_THE_TAIL = (("growth", "glyphs:"), ("neighbours", "overlap:"))
_BOTH = _frozen("growth", "neighbours")

ORACLE_TWINS: tuple[OracleTwinSpec, ...] = (
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
        _frozen(),
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
        _BOTH,
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
        _frozen(),
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
        _frozen(),
        _GROWTH_FAILS_ON_THE_TAIL,
    ),
    OracleTwinSpec(
        "ix",
        _simple_winansi("Figure", overhang=300, far_show=True),
        "Figure",
        "Figure f ",
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen(),
        _BOTH,
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
        _simple_winansi("Figure 1", fontsize=6.0, far_show=True),
        "Figure 1",
        "Figure 123",
        _frozen("product", "experiment"),
        e_kern,
        None,
        COMMITTED,
        _frozen(),
        _BOTH,
    ),
    OracleTwinSpec(
        "xii",
        _simple_winansi("Figure 1", fontsize=6.0, clip_path=GAP_CLIP),
        "Figure 1",
        "Figure 123",
        _frozen("product"),
        None,
        None,
        COMMITTED,
        _frozen("neighbours"),
        _frozen("growth"),
        (("neighbours", "ink_not_landed:"),),
    ),
)
