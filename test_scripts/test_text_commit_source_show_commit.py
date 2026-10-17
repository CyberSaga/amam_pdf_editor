"""Commit-side source-show target and ``source_ref`` carriage (UI steps 3-4).

G2 (``test_text_commit_source_run.py``) made a run-mode CLICK return the
whole proven show ("Buffer Tank", "設計圖說A版") but the commit side kept
resolving the single clicked run: ``_resolve_edit_target`` built the overlap
cluster from that run's reopen anchor (the ~1 pt Buffer/Tank gap drops
"Tank"), and ``_tier0_target_from_resolve`` ordered by ``origin.x`` and
joined with spaces -- reversing a mirrored show and inserting spaces into a
kind-split CJK+Latin show (critique blocking defect B1).

Step 3: the commit side RE-DERIVES the group with the same Qt-free resolver
(never trusting view geometry): members = the group, cluster bbox = the
union, reopen anchor keyed by the group, source kind ``"source_show"``
(beats the ``dict_line`` recovery, ``whitespace_reconstructed`` False,
replacement verbatim).  ``derive_tier0_preview_target`` uses the same path.

Step 4: ``source_ref`` flows editor -> preview payload -> ``EditTextRequest``
-> command -> model; a request whose ``source_ref`` differs from the
re-derived group's refuses with zero mutation (wrong-target protection for
twins).

Every fixture is synthetic (plan section 10 data policy).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model import pdf_text_edit  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.geometry import unrotated_to_visual_point, unrotated_to_visual_rect  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import derive_tier0_preview_target  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, TextCommitSettings  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402

from test_scripts.qt_teardown import dispose_pdf_view  # noqa: E402
from test_scripts.type0_fixture_builder import (  # noqa: E402
    Type0Fixture,
    append_page_content,
    build_identity_h_fixture,
    encode_cids,
    set_text_matrix,
)

_TOL = 1e-3
_STRICT = TextCommitSettings(engine="tiered", strict=True)


# ---------------------------------------------------------------- helpers


def _open_model(
    tmp_path: Path,
    doc: fitz.Document,
    name: str,
    settings: TextCommitSettings = _STRICT,
) -> PDFModel:
    path = tmp_path / f"{name}.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(path))
    model.set_text_target_mode("run")
    model.ensure_page_index_built(1)
    return model


def _fixture_model(
    tmp_path: Path,
    fixture: Type0Fixture,
    name: str,
    settings: TextCommitSettings = _STRICT,
) -> PDFModel:
    return _open_model(tmp_path, fixture.doc, name, settings)


def _runs(model: PDFModel, page_idx: int = 0) -> list:
    return list(model.block_manager.get_runs(page_idx))


def _run_by_text(model: PDFModel, text: str, nth: int = 0):
    matches = [r for r in _runs(model) if r.text == text]
    assert len(matches) > nth, f"no run {text!r} (#{nth}) in {[r.text for r in _runs(model)]}"
    return matches[nth]


def _hit_on(model: PDFModel, run):
    page = model.doc[0]
    rect = unrotated_to_visual_rect(page, fitz.Rect(run.bbox))
    hit = model.get_text_info_at_point(
        1, fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
    )
    assert hit is not None
    return hit


def _shows(model: PDFModel):
    page = model.doc[0]
    return replay_page_streams(
        [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
    ).shows


def _content_bytes(model: PDFModel) -> list[bytes]:
    page = model.doc[0]
    return [model.doc.xref_stream(x) for x in page.get_contents()]


def _edit_from_hit(model: PDFModel, hit, new_text: str, *, with_ref: bool, **extra):
    kwargs = dict(
        page_num=1,
        rect=hit.target_bbox,
        new_text=new_text,
        font=hit.font,
        size=hit.size,
        color=hit.color,
        original_text=hit.target_text,
        target_span_id=hit.target_span_id,
        target_mode="run",
    )
    if with_ref:
        kwargs["source_ref"] = hit.source_ref
    kwargs.update(extra)
    return model.edit_text(**kwargs)


def _assert_lossless(model: PDFModel) -> None:
    outcome = model.last_commit_outcome
    assert outcome is not None
    assert outcome.status is CommitStatus.COMMITTED, outcome
    assert outcome.tier in (
        CommitTier.TIER0_LOSSLESS_STREAM_PATCH,
        CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE,
    ), outcome
    assert tuple(outcome.fallback_chain or ()) == (), outcome.fallback_chain


def _mirrored_fixture() -> Type0Fixture:
    fixture = build_identity_h_fixture("Buffer Tank", origin=(300.0, 700.0))
    set_text_matrix(fixture, (-1.0, 0.0, 0.0, 1.0))
    return fixture


# ------------------------------------------- step 3: commit edits the whole show


@pytest.mark.parametrize("with_ref", [False, True], ids=["hit_text", "source_ref"])
def test_mirrored_buffer_tank_commits_whole_show_in_place(tmp_path: Path, with_ref: bool) -> None:
    """'Buffer Tank' -> 'Tank Buffer' on a mirrored Tm: one show, same Tm, parser order."""
    model = _fixture_model(tmp_path, _mirrored_fixture(), f"mirror_{with_ref}")
    try:
        before = _shows(model)
        assert len(before) == 1
        tm_before = tuple(before[0].tm)
        tank_run = _run_by_text(model, "Tank")
        buffer_run = _run_by_text(model, "Buffer")
        assert float(tank_run.origin.x) < float(buffer_run.origin.x), "fixture must be mirrored"
        hit = _hit_on(model, tank_run)
        assert hit.target_text == "Buffer Tank"
        assert hit.source_ref is not None

        result = _edit_from_hit(model, hit, "Tank Buffer", with_ref=with_ref)

        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
        after = _shows(model)
        assert len(after) == 1, [s.decoded_bytes for s in after]
        assert after[0].decoded_bytes == encode_cids("Tank Buffer")
        assert tuple(after[0].tm) == tm_before, "Tm must be unchanged (in-place patch)"
        stream = b"".join(_content_bytes(model))
        assert encode_cids("Buffer Tank").hex().upper().encode() not in stream
        # The edited show is still ONE target: clicking either word after the
        # commit (the index split it into two runs again) re-merges it, and
        # the in-place patch kept the show's identity.
        for word in ("Tank", "Buffer"):
            again = _hit_on(model, _run_by_text(model, word))
            assert again.target_text == "Tank Buffer"
            assert again.source_ref is not None
            assert (again.source_ref.stream_xref, again.source_ref.op_start, again.source_ref.seq) == (
                hit.source_ref.stream_xref,
                hit.source_ref.op_start,
                hit.source_ref.seq,
            )
    finally:
        model.close()


@pytest.mark.parametrize("with_ref", [False, True], ids=["hit_text", "source_ref"])
def test_cjk_latin_kind_split_commits_exact_text_without_spaces(
    tmp_path: Path, with_ref: bool
) -> None:
    model = _fixture_model(
        tmp_path, build_identity_h_fixture("設計圖說A版"), f"cjk_{with_ref}"
    )
    try:
        runs = _runs(model)
        assert [r.text for r in runs] == ["設計圖說", "A", "版"], "fixture must kind-split"
        hit = _hit_on(model, runs[1])
        assert hit.target_text == "設計圖說A版"

        result = _edit_from_hit(model, hit, "設計A圖說版", with_ref=with_ref)

        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
        after = _shows(model)
        assert len(after) == 1
        # Exact code sequence: six codes, no inserted space code anywhere.
        assert after[0].decoded_bytes == encode_cids("設計A圖說版")
        assert len(after[0].decoded_bytes) == 2 * len("設計A圖說版")
        model.block_manager.rebuild_page(0, model.doc)
        assert "".join(r.text for r in _runs(model)) == "設計A圖說版"
        again = _hit_on(model, _runs(model)[-1])
        assert again.target_text == "設計A圖說版"
        assert again.source_ref is not None
        assert again.source_ref.seq == hit.source_ref.seq
    finally:
        model.close()


def test_stale_word_sized_reopen_anchor_does_not_shrink_the_group(tmp_path: Path) -> None:
    """B1's anchor leg: a per-word anchor recorded earlier must not become the
    group's cluster bbox (the ~1 pt gap would drop 'Tank' from the cluster)."""
    model = _fixture_model(tmp_path, build_identity_h_fixture("Buffer Tank"), "anchor")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        model._set_run_reopen_anchor_rect(0, buffer_run.span_id, fitz.Rect(buffer_run.bbox))
        model._set_run_reopen_anchor_size(0, buffer_run.span_id, float(buffer_run.size))
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert hit.target_text == "Buffer Tank"

        result = _edit_from_hit(model, hit, "Buffer Tnak", with_ref=True)

        assert result is EditTextResult.SUCCESS
        _assert_lossless(model)
        after = _shows(model)
        assert [s.decoded_bytes for s in after] == [encode_cids("Buffer Tnak")]
    finally:
        model.close()


def test_single_word_caller_never_rewrites_the_whole_show(tmp_path: Path) -> None:
    """PAIRED NEGATIVE (guard: passes before step 3): a caller naming ONE word
    without a source_ref keeps the single-run target, which refuses at binding
    under strict mode -- it must never replace 'Buffer Tank' with 'Bufer'."""
    model = _fixture_model(tmp_path, build_identity_h_fixture("Buffer Tank"), "oneword")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        before = _content_bytes(model)
        result = model.edit_text(
            page_num=1,
            rect=unrotated_to_visual_rect(model.doc[0], fitz.Rect(buffer_run.bbox)),
            new_text="Bufer",
            font=buffer_run.font,
            size=float(buffer_run.size),
            color=tuple(buffer_run.color),
            original_text="Buffer",
            target_span_id=buffer_run.span_id,
            target_mode="run",
        )
        assert result is EditTextResult.REJECTED_STRICT
        assert _content_bytes(model) == before
    finally:
        model.close()


# --------------------------------------------- step 3: preview derivation path


@pytest.mark.parametrize("with_ref", [False, True], ids=["hit_text", "source_ref"])
def test_derive_preview_target_is_the_source_show(tmp_path: Path, with_ref: bool) -> None:
    model = _fixture_model(tmp_path, _mirrored_fixture(), f"derive_{with_ref}")
    try:
        buffer_run = _run_by_text(model, "Buffer")
        tank_run = _run_by_text(model, "Tank")
        hit = _hit_on(model, tank_run)
        kwargs = dict(
            page_num=1,
            rect=hit.target_bbox,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        if with_ref:
            kwargs["source_ref"] = hit.source_ref
        target = derive_tier0_preview_target(model, **kwargs)
        assert target is not None
        assert target.text == "Buffer Tank"
        assert target.source_kind == "source_show"
        assert target.whitespace_reconstructed is False
        assert target.replacement_for("Tank  Buffer ") == "Tank  Buffer "
        assert abs(target.origin[0] - hit.source_ref.origin[0]) <= _TOL
        assert abs(target.origin[1] - hit.source_ref.origin[1]) <= _TOL
        page = model.doc[0]
        union = unrotated_to_visual_rect(
            page, fitz.Rect(buffer_run.bbox) | fitz.Rect(tank_run.bbox)
        )
        assert all(abs(a - b) <= _TOL for a, b in zip(target.bbox, tuple(union)))
    finally:
        model.close()


def test_source_show_beats_dict_line_recovery(tmp_path: Path) -> None:
    """Rot-0 simple-font 'Buffer Tank' passes the dict_line gates (dir (1,0));
    the proven show must take precedence and never read ``get_text('dict')``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Buffer Tank", fontname="helv", fontsize=12)
    model = _open_model(tmp_path, doc, "dictline")
    try:
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert hit.source_ref is not None
        calls: list[int] = []
        real = pdf_text_edit._dict_line_for_runs

        def _spy(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        pdf_text_edit._dict_line_for_runs = _spy
        try:
            target = derive_tier0_preview_target(
                model,
                page_num=1,
                rect=hit.target_bbox,
                original_text=hit.target_text,
                target_span_id=hit.target_span_id,
                target_mode="run",
                source_ref=hit.source_ref,
            )
        finally:
            pdf_text_edit._dict_line_for_runs = real
        assert target is not None
        assert target.source_kind == "source_show"
        assert target.text == "Buffer Tank"
        assert calls == []
    finally:
        model.close()


def test_derive_preview_target_ignores_the_no_change_gate(tmp_path: Path, monkeypatch) -> None:
    """Critique minor note: derivation fed helv/12/black into the block-level
    no-change gate and only escaped it because 'Helvetica' and 'helv' resolve
    differently.  Make them resolve alike: derivation must still succeed."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello", fontname="helv", fontsize=12)
    model = _open_model(tmp_path, doc, "nochange")
    try:
        monkeypatch.setattr(model, "_resolve_add_text_font", lambda _font: "helv")
        hit = _hit_on(model, _run_by_text(model, "Hello"))
        assert abs(float(hit.size) - 12.0) < 0.01
        target = derive_tier0_preview_target(
            model,
            page_num=1,
            rect=hit.target_bbox,
            original_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
        )
        assert target is not None
        assert target.text == "Hello"
    finally:
        model.close()


# --------------------------------------------- step 4: source_ref wrong target


def _twins(tmp_path: Path, settings: TextCommitSettings) -> PDFModel:
    fixture = build_identity_h_fixture("Buffer Tank")
    hex_operand = encode_cids("Buffer Tank").hex().upper()
    append_page_content(
        fixture,
        f"BT /{fixture.resource_name} {fixture.fontsize:g} Tf "
        f"1 0 0 1 72 600 Tm <{hex_operand}> Tj ET",
    )
    return _fixture_model(tmp_path, fixture, "twins", settings)


def test_mismatched_source_ref_refuses_without_mutation(tmp_path: Path, monkeypatch) -> None:
    """A request for twin B carrying twin A's ref must refuse: no tier, no legacy."""
    model = _twins(tmp_path, TextCommitSettings(engine="tiered", strict=False))
    try:
        hit_a = _hit_on(model, _run_by_text(model, "Tank", nth=0))
        hit_b = _hit_on(model, _run_by_text(model, "Tank", nth=1))
        assert hit_a.source_ref is not None and hit_b.source_ref is not None
        assert hit_a.source_ref != hit_b.source_ref
        before = _content_bytes(model)
        xref_count = model.doc.xref_length()
        legacy_calls: list[int] = []
        monkeypatch.setattr(
            model, "_apply_redact_insert", lambda *a, **k: legacy_calls.append(1)
        )
        engine = model.get_tiered_commit_engine()
        prepare_calls: list[int] = []
        real_prepare = engine.prepare

        def _spy_prepare(*args, **kwargs):
            prepare_calls.append(1)
            return real_prepare(*args, **kwargs)

        monkeypatch.setattr(engine, "prepare", _spy_prepare)

        result = _edit_from_hit(
            model, hit_b, "Buffer Tnak", with_ref=False, source_ref=hit_a.source_ref
        )

        assert result is EditTextResult.TARGET_SOURCE_MISMATCH
        assert _content_bytes(model) == before
        assert model.doc.xref_length() == xref_count
        assert legacy_calls == []
        assert prepare_calls == []
        # The preview derivation refuses the same way.
        assert (
            derive_tier0_preview_target(
                model,
                page_num=1,
                rect=hit_b.target_bbox,
                original_text=hit_b.target_text,
                target_span_id=hit_b.target_span_id,
                target_mode="run",
                source_ref=hit_a.source_ref,
            )
            is None
        )
        # Positive control: B's own ref derives B.
        own = derive_tier0_preview_target(
            model,
            page_num=1,
            rect=hit_b.target_bbox,
            original_text=hit_b.target_text,
            target_span_id=hit_b.target_span_id,
            target_mode="run",
            source_ref=hit_b.source_ref,
        )
        assert own is not None and own.source_kind == "source_show"
    finally:
        model.close()


def test_source_ref_without_a_provable_group_refuses(tmp_path: Path) -> None:
    """A ref naming a show the commit side cannot re-prove (two Tj on one
    baseline: the resolver refuses to group) must not fall back to the word."""
    model = _fixture_model(
        tmp_path,
        build_identity_h_fixture("Buffer", tail_text=" Tank"),
        "twoshow",
        TextCommitSettings(engine="tiered", strict=False),
    )
    try:
        # A ref for the first show, as a (stale) view might still carry.
        twin = _twins_ref_for_first_show(model)
        tank_run = _run_by_text(model, "Tank")
        before = _content_bytes(model)
        result = model.edit_text(
            page_num=1,
            rect=unrotated_to_visual_rect(model.doc[0], fitz.Rect(tank_run.bbox)),
            new_text="Tanks",
            font=tank_run.font,
            size=float(tank_run.size),
            color=tuple(tank_run.color),
            original_text="Tank",
            target_span_id=tank_run.span_id,
            target_mode="run",
            source_ref=twin,
        )
        assert result is EditTextResult.TARGET_SOURCE_MISMATCH
        assert _content_bytes(model) == before
    finally:
        model.close()


def _twins_ref_for_first_show(model: PDFModel):
    from model.edit_requests import SourceShowRef

    page = model.doc[0]
    show = _shows(model)[0]
    first = _runs(model)[0]
    origin = unrotated_to_visual_point(page, fitz.Point(first.origin))
    return SourceShowRef(
        page_xref=int(page.xref),
        stream_xref=int(show.stream_xref),
        op_start=int(show.op_start),
        seq=int(show.seq),
        origin=(float(origin.x), float(origin.y)),
    )


# --------------------------------- step 4: editor -> payload -> request (real Qt)


def _pump(ms: int = 200) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_request_and_preview_payload_carry_the_hits_source_ref(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from controller.pdf_controller import PDFController
    from view.pdf_view import PDFView, TextEditFinalizeReason

    fixture = build_identity_h_fixture("Buffer Tank")
    path = tmp_path / "gui.pdf"
    fixture.doc.save(str(path))
    fixture.doc.close()

    modal_calls: list[str] = []
    monkeypatch.setattr(
        "controller.pdf_controller.QMessageBox.information",
        staticmethod(lambda *a, **k: modal_calls.append("information")),
    )
    monkeypatch.setattr(
        "controller.pdf_controller.show_error",
        lambda *a, **k: modal_calls.append("show_error"),
    )
    model = PDFModel(
        text_commit_settings=TextCommitSettings(engine="tiered", strict=True, preview="plan")
    )
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    monkeypatch.setattr(
        controller, "_confirm_legacy_fallback", lambda *a, **k: modal_calls.append("fallback") or False
    )
    requests: list = []
    payloads: list[dict] = []
    view.sig_edit_text.connect(requests.append)
    view.sig_text_edit_plan_preview.connect(payloads.append)
    try:
        view.resize(1200, 900)
        view.show()
        _pump(120)
        controller.open_pdf(str(path))
        _pump(400)
        view.set_mode("edit_text")
        combo = view.text_target_mode_combo
        combo.setCurrentIndex(combo.findData("run"))
        _pump(60)
        assert model.text_target_mode == "run"

        # Critique step 12: "run" is the combo's shipped default now, so the
        # combo switch above no longer builds the index before this lookup.
        model.ensure_page_index_built(1)
        tank_run = _run_by_text(model, "Tank")
        hit = _hit_on(model, tank_run)
        assert hit.source_ref is not None

        page = model.doc[0]
        visual = unrotated_to_visual_rect(page, fitz.Rect(tank_run.bbox))
        rs = view._render_scale if view._render_scale > 0 else 1.0
        centre = QPointF(
            view._page_scene_x(0) + (visual.x0 + visual.x1) / 2.0 * rs,
            view._page_scene_y(0) + (visual.y0 + visual.y1) / 2.0 * rs,
        )
        view.graphics_view.centerOn(centre)
        _pump(60)
        click_pos = view.graphics_view.mapFromScene(centre)
        QTest.mouseClick(view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
        _pump(260)
        assert view.text_editor is not None, "click must open the editor"
        editor = view.text_editor.widget()
        assert editor.toPlainText() == "Buffer Tank"

        editor.setPlainText("Buffer Tnak")  # glyphs the subset has
        _pump(600)  # debounce + preview hook
        assert payloads, "the plan preview hook must emit"
        assert all(p.get("source_ref") == hit.source_ref for p in payloads), payloads
        # The controller derived the preview target from that ref (a dict-ified
        # or converted ref would silently resolve to target_unresolved).
        preview_target = controller._plan_preview_target
        assert preview_target is not None
        assert preview_target.source_kind == "source_show"
        assert preview_target.text == "Buffer Tank"

        view._finalize_text_edit_impl(TextEditFinalizeReason.CLICK_AWAY)
        _pump(200)
        assert len(requests) == 1
        assert requests[0].source_ref == hit.source_ref
        assert [s.decoded_bytes for s in _shows(model)] == [encode_cids("Buffer Tnak")]
        assert modal_calls == []
    finally:
        dispose_pdf_view(view, controller, model)
        _pump(60)


# ------------------------------------------ step 4: redo after snapshot restore


def test_legacy_grouped_edit_redo_survives_snapshot_restore(tmp_path: Path) -> None:
    """Undo of a legacy (Tier 2) command restores a page SNAPSHOT, which gives
    the page and its content stream new xrefs -- the hit's ``source_ref`` can
    never match again.  Redo replays the already-proven decision: it must
    re-derive the show from the restored page, not refuse as a mismatch."""
    from model.edit_commands import EditTextCommand

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Buffer Tank", fontname="helv", fontsize=12)
    model = _open_model(tmp_path, doc, "redo", TextCommitSettings(engine="legacy"))
    try:
        hit = _hit_on(model, _run_by_text(model, "Tank"))
        assert hit.source_ref is not None
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=hit.target_bbox,
            new_text="Tank Buffer",
            font=hit.font,
            size=hit.size,
            color=hit.color,
            original_text=hit.target_text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=hit.target_span_id,
            old_block_text=hit.target_text,
            target_span_id=hit.target_span_id,
            target_mode="run",
            source_ref=hit.source_ref,
        )
        model.command_manager.execute(cmd)
        assert cmd.result is EditTextResult.SUCCESS
        assert model.doc[0].get_text("text").split() == ["Tank", "Buffer"]
        assert model.command_manager.undo() is True
        assert model.doc[0].get_text("text").split() == ["Buffer", "Tank"]
        assert model.command_manager.redo() is True, cmd.result
        assert cmd.result is EditTextResult.SUCCESS
        assert model.doc[0].get_text("text").split() == ["Tank", "Buffer"]
    finally:
        model.close()


# -------------------------------------------------------------- real corpus


@pytest.mark.needs_fixtures
def test_real_corpus_run_hit_commits_whole_show_through_model_edit_text(tmp_path: Path) -> None:
    """All 14 real Type0 cases, each on a fresh tmp copy: a run-mode hit on the
    show's LAST member (the one-word cases used to return a single word) is
    committed through ``model.edit_text`` with the hit's ``source_ref`` and
    lands losslessly on exactly that show.  Engine-plus-model evidence only;
    it is not UI evidence (the umbrella UI acceptance is a separate step)."""
    import shutil

    import test_text_commit_real_corpus_acceptance as acc

    settings = TextCommitSettings(engine="tiered", max_tier=1, strict=True)
    committed = 0
    for spec in acc.CORPORA:
        source = acc._fixture(spec)
        with fitz.open(str(source)) as probe_doc:
            cases = acc._resolve_cases(spec, probe_doc)
        for case in cases:
            label = f"{spec.slug} p{case.page_index}/show{case.show_seq}"
            work = tmp_path / f"{spec.slug}_{case.page_index}_{case.show_seq}.pdf"
            shutil.copyfile(source, work)
            model = PDFModel(text_commit_settings=settings)
            try:
                model.open_pdf(str(work))
                model.set_text_target_mode("run")
                page_idx = case.page_index
                model.ensure_page_index_built(page_idx + 1)
                page = model.doc[page_idx]
                show = acc._shows(model.doc, page_idx)[case.show_seq]
                show_dict = fitz.Point(*show.origin_user) * page.transformation_matrix
                runs = list(model.block_manager.get_runs(page_idx))
                first = next(
                    (r for r in runs if abs(fitz.Point(r.origin) - show_dict) < 0.05), None
                )
                assert first is not None, label
                line = sorted(
                    (r for r in runs if (r.block_idx, r.line_idx) == (first.block_idx, first.line_idx)),
                    key=lambda r: r.span_idx,
                )
                visual = unrotated_to_visual_rect(page, fitz.Rect(line[-1].bbox))
                hit = model.get_text_info_at_point(
                    page_idx + 1,
                    fitz.Point((visual.x0 + visual.x1) / 2.0, (visual.y0 + visual.y1) / 2.0),
                )
                assert hit is not None and hit.source_ref is not None, label
                assert hit.source_ref.seq == case.show_seq, label
                assert hit.target_text == case.original, label

                result = model.edit_text(
                    page_num=page_idx + 1,
                    rect=hit.target_bbox,
                    new_text=case.replacement,
                    font=hit.font,
                    size=hit.size,
                    color=hit.color,
                    original_text=hit.target_text,
                    target_span_id=hit.target_span_id,
                    target_mode="run",
                    source_ref=hit.source_ref,
                )
                assert result is EditTextResult.SUCCESS, (label, result)
                _assert_lossless(model)
                after = acc._shows(model.doc, page_idx)[case.show_seq]
                decoded = acc._decode_show(
                    DocumentFontRegistry(model.doc), model.doc[page_idx], after
                )
                assert decoded == case.replacement, label
                committed += 1
            finally:
                model.close()
    assert committed == 14


def test_legacy_grouped_edit_never_plants_the_show_union_on_one_word(
    tmp_path: Path, monkeypatch
) -> None:
    """A rebuild (legacy) commit of a grouped show may re-insert the text as
    SEVERAL shows (the htmlbox path does).  The group's reopen anchor must not
    then be migrated onto one of the new words: clicking 'lineX' would open
    'Heading' over the whole old union.  The words the rebuild wrote for this one
    edit reopen as ONE box (S17-ANCHOR-JOIN), never as a word over a stale union."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 100), "Heading line", fontname="helv", fontsize=7.5)
    model = _open_model(tmp_path, doc, "legacy_anchor", TextCommitSettings(engine="legacy"))
    try:
        monkeypatch.setattr(model, "_needs_cjk_font", lambda _text: True)  # htmlbox path
        hit = _hit_on(model, _run_by_text(model, "line"))
        assert hit.target_text == "Heading line" and hit.source_ref is not None
        result = _edit_from_hit(model, hit, "Heading lineX", with_ref=True)
        assert result is EditTextResult.SUCCESS
        model.ensure_page_index_built(1)
        words = [r.text for r in _runs(model)]
        assert words == ["Heading", "lineX"], words
        union = fitz.Rect()
        for word in words:
            union |= fitz.Rect(_run_by_text(model, word).bbox)
        for word in words:
            again = _hit_on(model, _run_by_text(model, word))
            # Either a proven single show or the joined fragments of the edit:
            # the whole new text over the new words' union, never the old union
            # planted on one word.
            assert again.target_text == "Heading lineX", (word, again.target_text)
            assert fitz.Rect(again.target_bbox) == union, (word, again.target_bbox, union)
    finally:
        model.close()
