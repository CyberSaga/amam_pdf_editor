"""Card B7 step 1 (plans/b7-design-astra.md section 1): the document write gate.  Red first.

One lease per model while a vector pass (or any other multi-step write) is in flight.  While it is held every
other write entry refuses with WriteGateBusy *before* touching anything, and an OCR result is queued instead of
written; it is applied only after the transaction published (plan A: OCR stays out of the undo history).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.edit_commands import CommandManager, SnapshotCommand  # noqa: E402
from model.object_op_refusal import ObjectOpRefusal  # noqa: E402
from model.object_requests import VectorSelectionQuery  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths import commit_state as cs  # noqa: E402
from model.vector_paths.edit import plan_delete  # noqa: E402
from model.vector_paths.scan import scan_page  # noqa: E402
from model.write_gate import (  # noqa: E402
    GATED_MODEL_METHODS,
    GATED_TOOL_METHODS,
    NOT_A_WRITE_ENTRY,
    Applied,
    Deferred,
    DocumentWriteGate,
    Stale,
    TransactionRecoveryFailed,
    WriteGateBusy,
)

BODY = b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f"
SPAN = SimpleNamespace(bbox=(20.0, 20.0, 120.0, 40.0), text="hello ocr", confidence=90.0)


def _model(tmp_path: Path, pages: int = 2) -> PDFModel:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((5, 5), " ")
        doc.update_stream(page.get_contents()[0], BODY)
    path = tmp_path / "g.pdf"
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    return model


def _bytes(model: PDFModel):
    """Every xref's full object text and stream (tobytes() differs between calls by its trailer ID)."""
    doc = model.doc
    rows = []
    for xref in range(1, doc.xref_length()):
        try:
            rows.append((xref, doc.xref_object(xref, compressed=False), doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else b""))
        except Exception:  # noqa: BLE001
            rows.append((xref, None, None))
    return (len(doc), tuple(rows))


def _text(model: PDFModel, page: int = 0) -> str:
    return model.doc[page].get_text().strip()


# ---- the gate itself ----------------------------------------------------------------------------
def test_a_second_lease_is_refused_and_release_frees_the_gate():
    gate = DocumentWriteGate()
    assert not gate.active
    lease = gate.begin("vector_delete", 7)
    assert gate.active and gate.kind == "vector_delete" and gate.session_id == 7
    with pytest.raises(WriteGateBusy):
        gate.begin("other", 7)
    lease.release()
    assert not gate.active
    lease.release()  # idempotent
    gate.begin("again", 7).release()


def test_the_context_manager_releases_on_an_exception():
    gate = DocumentWriteGate()
    with pytest.raises(RuntimeError), gate.begin("x", 1):
        raise RuntimeError("boom")
    assert not gate.active


def test_check_passes_for_the_holder_only():
    gate = DocumentWriteGate()
    gate.check()  # free: fine
    lease = gate.begin("x", 1)
    with pytest.raises(WriteGateBusy):
        gate.check()
    with pytest.raises(WriteGateBusy):
        gate.check(DocumentWriteGate().begin("y", 1))  # somebody else's lease is not the holder
    gate.check(lease)
    lease.release()


# ---- OCR is queued while the lease is held ------------------------------------------------------
def test_ocr_is_queued_during_a_lease_and_applied_after_it(tmp_path):
    model = _model(tmp_path)
    before = _bytes(model)
    lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
    outcome = model.submit_ocr_page(1, [SPAN])
    assert isinstance(outcome, Deferred) and _bytes(model) == before and _text(model) == ""
    assert model.pending_ocr_count == 1
    assert model.drain_pending_ocr() == []  # still held: nothing moves
    lease.release()
    done = model.drain_pending_ocr()
    assert [type(o) for o in done] == [Applied] and done[0].count == 1
    assert "hello ocr" in _text(model) and model.pending_ocr_count == 0


def test_ocr_without_a_lease_is_applied_at_once(tmp_path):
    model = _model(tmp_path)
    outcome = model.submit_ocr_page(1, [SPAN])
    assert isinstance(outcome, Applied) and outcome.count == 1 and "hello ocr" in _text(model)


def test_a_queued_page_that_no_longer_exists_is_stale_not_an_error(tmp_path):
    model = _model(tmp_path, pages=2)
    lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
    assert isinstance(model.submit_ocr_page(2, [SPAN]), Deferred)
    lease.release()
    model.delete_pages([2])
    done = model.drain_pending_ocr()
    assert [type(o) for o in done] == [Stale] and model.pending_ocr_count == 0


def test_a_queued_page_for_another_session_is_stale(tmp_path):
    model = _model(tmp_path)
    lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
    assert isinstance(model.submit_ocr_page(1, [SPAN]), Deferred)
    lease.release()
    model.__dict__["_ocr_pending"] = [("other-session", p, s, n) for (_sid, p, s, n) in model.__dict__["_ocr_pending"]]
    assert [type(o) for o in model.drain_pending_ocr()] == [Stale]


# ---- every other write entry refuses ------------------------------------------------------------
MUTATORS = (
    (fitz.Document, "update_stream"),
    (fitz.Document, "xref_set_key"),
    (fitz.Document, "delete_page"),
    (fitz.Document, "delete_pages"),
    (fitz.Document, "insert_pdf"),
    (fitz.Document, "new_page"),
    (fitz.Document, "set_metadata"),
    (fitz.Document, "set_toc"),
    (fitz.Document, "save"),
    (fitz.Page, "insert_text"),
    (fitz.Page, "set_rotation"),
    (fitz.Page, "add_redact_annot"),
    (fitz.Page, "apply_redactions"),
)
REFUSAL_CALLS = {
    "insert_blank_page": lambda m: m.insert_blank_page(1),
    "delete_pages": lambda m: m.delete_pages([1]),
    "rotate_pages": lambda m: m.rotate_pages([1], 90),
    "move_page": lambda m: m.move_page(0, 1),
    "set_editable_metadata": lambda m: m.set_editable_metadata({"title": "x"}),
    "set_toc": lambda m: m.set_toc([]),
    "apply_pending_redactions": lambda m: m.apply_pending_redactions(),
    "save_as": lambda m: m.save_as(str(m.saved_path or "x.pdf") + ".out.pdf"),
    "apply_ocr_spans": lambda m: m.apply_ocr_spans(1, [SPAN]),
}


@pytest.mark.parametrize("name", sorted(REFUSAL_CALLS))
def test_a_write_entry_refuses_before_touching_anything_while_a_lease_is_held(tmp_path, name, monkeypatch):
    model = _model(tmp_path)
    assert name in GATED_MODEL_METHODS
    before, edits, rev = _bytes(model), model.edit_count, model.content_revision
    fired: list[str] = []
    for owner, attr in MUTATORS:
        real = getattr(owner, attr)
        monkeypatch.setattr(owner, attr, lambda *a, _n=attr, **k: fired.append(_n))
        del real
    with model.write_gate.begin("vector_delete", model.get_active_session_id()):
        with pytest.raises(WriteGateBusy):
            REFUSAL_CALLS[name](model)
    assert not fired, f"a document mutator ran before the gate refused: {fired}"
    assert _bytes(model) == before and model.edit_count == edits and model.content_revision == rev


def test_history_entries_refuse_and_the_holder_may_record(tmp_path):
    model = _model(tmp_path)
    cm: CommandManager = model.command_manager
    snap = model._capture_doc_snapshot()
    cmd = SnapshotCommand(model, "x", [1], snap, snap, "x")
    with model.write_gate.begin("vector_delete", model.get_active_session_id()) as lease:
        for call in (cm.undo, cm.redo, lambda: cm.record(cmd), lambda: cm.execute(cmd)):
            with pytest.raises(WriteGateBusy):
                call()
        cm.record(cmd, lease=lease)
        assert cm.undo(lease=lease) and cm.redo(lease=lease)
    assert cm.can_undo()


def test_a_gated_model_method_accepts_the_holders_lease(tmp_path):
    model = _model(tmp_path)
    with model.write_gate.begin("vector_delete", model.get_active_session_id()) as lease:
        with pytest.raises(WriteGateBusy):
            model.rotate_pages([1], 90)
        model.rotate_pages([1], 90, write_lease=lease)
    assert model.doc[0].rotation == 90


# ---- the inventory is complete ------------------------------------------------------------------
def test_every_gated_name_is_decorated_and_exists():
    for name in GATED_MODEL_METHODS:
        fn = getattr(PDFModel, name)
        assert getattr(fn, "__write_gated__", False), name


def test_every_pdfmodel_method_that_bumps_edit_count_is_gated_or_explained():
    tree = ast.parse((REPO_ROOT / "model" / "pdf_model.py").read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PDFModel")
    bumpers = set()
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute) and node.target.attr == "edit_count":
                bumpers.add(fn.name)
    unclassified = sorted(bumpers - set(GATED_MODEL_METHODS) - set(NOT_A_WRITE_ENTRY))
    assert not unclassified, f"classify these writers in model/write_gate.py: {unclassified}"
    assert all(NOT_A_WRITE_ENTRY[name].strip() for name in NOT_A_WRITE_ENTRY)


# ---- the vector transaction holds the lease and does not let OCR in -----------------------------
def test_commit_vector_plan_holds_the_lease_and_ocr_waits_for_the_publish(tmp_path, monkeypatch):
    model = _model(tmp_path)
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    del all_
    all_ = _click_second(model)
    index, mask, streams = model.vector_plan_inputs(all_.token)
    plan = plan_delete(index, mask, streams)
    seen: list[tuple[bool, str]] = []
    real = cs.digest_table

    def spy(doc, *a, **kw):
        outcome = model.submit_ocr_page(1, [SPAN])
        seen.append((model.write_gate.active, type(outcome).__name__))
        return real(doc, *a, **kw)

    monkeypatch.setattr(cs, "digest_table", spy)
    result = model.commit_vector_plan(plan, all_.token)
    assert result is not None and seen and all(active and kind == "Deferred" for active, kind in seen)
    assert not model.write_gate.active  # released
    assert model.pending_ocr_count == len(seen)  # queued, not inside the after-digest
    monkeypatch.setattr(cs, "digest_table", real)
    assert model.verify_vector_digest(result.digest_after)  # before anything reads or writes the page again
    assert _text(model) == ""
    assert all(isinstance(o, Applied) for o in model.drain_pending_ocr())
    assert "hello ocr" in _text(model)


def test_the_lease_is_released_when_the_commit_refuses(tmp_path):
    model = _model(tmp_path)
    assert model.commit_vector_plan(SimpleNamespace(), 12345) is None
    assert not model.write_gate.active


def test_a_commit_while_another_lease_is_held_is_refused_without_a_write(tmp_path):
    model = _model(tmp_path)
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    before = _bytes(model)
    with model.write_gate.begin("save", model.get_active_session_id()):
        with pytest.raises(WriteGateBusy):
            model.commit_vector_plan(SimpleNamespace(), all_.token)
    assert _bytes(model) == before


# ---- the lease spans commit -> after-capture -> record; OCR lands only after the record (plan A) -----
def _click_second(model):
    """Select the red square (second path) through a real query, so the token and the mask agree."""
    info = model.vector_select(VectorSelectionQuery(1, (170.0, 220.0, 170.0, 220.0), 1.0, "click", "replace"))
    assert info is not None and info.count == 1
    return info


def _select_second(model):
    info = _click_second(model)
    index, mask, streams = model.vector_plan_inputs(info.token)
    return info.token, plan_delete(index, mask, streams)


# ---- G3: the delete plan is bound to the selection the user saw (Astra r3 must-fix 5) ----------------
def test_plan_inputs_mask_cannot_change_the_live_selection(tmp_path):
    model = _model(tmp_path)
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    _index, mask, _streams = model.vector_plan_inputs(all_.token)
    live_before = model.vector_selection_mask().copy()
    try:
        mask[:] = False
    except ValueError:
        pass  # read-only is fine
    assert (model.vector_selection_mask() == live_before).all()
    assert getattr(mask.base, "flags", mask.flags).writeable is False or mask.flags.writeable is False


def test_same_token_different_mask_is_refused_before_write(tmp_path):
    model = _model(tmp_path)
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    index, mask, streams = model.vector_plan_inputs(all_.token)
    other = np.zeros(len(mask), dtype=bool)
    other[1] = True
    plan = plan_delete(index, other, streams)  # the user saw "all"; this plan deletes only the second row
    before = _bytes(model)
    assert model.commit_vector_plan(plan, all_.token) is None
    assert model.last_object_op_refusal is not None and model.last_object_op_refusal.reason == ObjectOpRefusal.VECTOR_SELECTION_STALE
    assert _bytes(model) == before and not model.write_gate.active
    assert model._live_vector_selection() is not None  # the user's selection survives; re-plan is allowed


def test_write_transaction_defers_ocr_until_after_the_history_record_and_undo_drops_it(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    applied_hook: list[int] = []
    model.on_ocr_applied = lambda: applied_hook.append(1)
    with model.write_transaction("vector_delete") as lease:
        before = model._capture_doc_snapshot()
        assert model.commit_vector_plan(plan, token, lease=lease) is not None
        assert model.write_gate.active  # still held after the commit returned
        assert isinstance(model.submit_ocr_page(1, [SPAN]), Deferred)
        after = model._capture_doc_snapshot()
        cmd = SnapshotCommand(model, "vector_delete", [1], before, after, "x")
        model.command_manager.record(cmd, lease=lease)
        assert isinstance(model.submit_ocr_page(1, [SPAN]), Deferred)
        assert not applied_hook
    # released: the queued pages are written now, after the record
    assert applied_hook == [1, 1] and model.pending_ocr_count == 0  # one notification per written page
    assert "hello ocr" in _text(model)
    assert fitz.open("pdf", after)[0].get_text().strip() == ""  # the recorded after-state has no OCR
    assert model.command_manager.undo()
    assert _text(model) == ""  # plan A: undo drops an OCR layer written after the snapshot
    assert b"150 160 40 40 re f" in b"".join(model.doc.xref_stream(x) for x in model.doc[0].get_contents())
    assert model.command_manager.redo()
    assert _text(model) == ""  # and redo does not bring it back


def test_a_failed_transaction_that_recovered_still_writes_the_ocr_page_that_arrived_meanwhile(tmp_path):
    """Class check (serial baseline): the OCR page that arrived during a transaction that failed and was taken back
    is written just as if it had arrived after it -- not left queued until some later submit happens to drain it."""
    model = _model(tmp_path)
    with pytest.raises(RuntimeError), model.write_transaction("x"):
        model.submit_ocr_page(1, [SPAN])
        raise RuntimeError("boom")
    assert not model.write_gate.active and model.pending_ocr_count == 0 and "hello" in _text(model)


def test_a_transaction_whose_recovery_failed_keeps_the_ocr_page_queued(tmp_path):
    """The document may be half-restored: nothing is written automatically (Astra review a stays for this case)."""
    model = _model(tmp_path)

    def broken_restore():
        raise RuntimeError("restore failed")

    with pytest.raises(TransactionRecoveryFailed), model.write_transaction("vector_x") as lease:
        lease.undo_write = broken_restore
        model.submit_ocr_page(1, [SPAN])
    assert not model.write_gate.active and model.pending_ocr_count == 1 and _text(model) == ""


def test_a_released_or_foreign_lease_is_not_a_holder(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    stale = model.write_gate.begin("x", None)
    stale.release()
    before = _bytes(model)
    with pytest.raises(WriteGateBusy):
        model.commit_vector_plan(plan, token, lease=stale)
    with pytest.raises(WriteGateBusy):
        model.commit_vector_plan(plan, token, lease=DocumentWriteGate().begin("y", None))
    assert _bytes(model) == before


def test_a_queued_page_that_was_replaced_meanwhile_is_stale(tmp_path):
    model = _model(tmp_path, pages=2)
    lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
    assert isinstance(model.submit_ocr_page(1, [SPAN]), Deferred)
    lease.release()
    model.doc[0].set_rotation(90)  # same session, same page number, another geometry
    assert [type(o) for o in model.drain_pending_ocr()] == [Stale] and _text(model) == ""


def test_the_controller_hook_runs_when_a_transaction_drains_ocr(tmp_path):
    model = _model(tmp_path)
    called: list[int] = []
    model.on_ocr_applied = lambda: called.append(1)
    with model.write_transaction("x"):
        model.submit_ocr_page(1, [SPAN])
    assert called == [1]  # the transaction ended with the document whole: its drain wrote the page and told the hook
    model.submit_ocr_page(1, [SPAN])  # not under a lease: applied at once, hook too
    assert called == [1, 1]


TOOL_CALLS = {
    "add_highlight": lambda t: t.add_highlight(1, fitz.Rect(10, 10, 50, 20), (1, 1, 0, 0.5)),
    "add_underline": lambda t: t.add_underline(1, fitz.Rect(10, 10, 50, 20), (1, 0, 0, 1)),
    "add_strikeout": lambda t: t.add_strikeout(1, fitz.Rect(10, 10, 50, 20), (1, 0, 0, 1)),
    "add_rect": lambda t: t.add_rect(1, fitz.Rect(10, 10, 50, 20), (1, 0, 0, 1), True),
    "add_annotation": lambda t: t.add_annotation(1, fitz.Point(20, 20), "note"),
    "update_annotation": lambda t: t.update_annotation(1, "x"),
    "move_annotation": lambda t: t.move_annotation(1, fitz.Rect(0, 0, 5, 5)),
    "delete_annotation": lambda t: t.delete_annotation(1),
    "toggle_annotations_visibility": lambda t: t.toggle_annotations_visibility(False),
    "add_watermark": lambda t: t.add_watermark([1], "W", 45, 0.3, 40, (0, 0, 0)),
    "remove_watermark": lambda t: t.remove_watermark("nope"),
    "update_watermark": lambda t: t.update_watermark("nope"),
}


def test_every_gated_tool_name_has_a_refusal_call():
    assert set(TOOL_CALLS) == {n for names in GATED_TOOL_METHODS.values() for n in names}


@pytest.mark.parametrize("name", sorted(TOOL_CALLS))
def test_a_tool_write_refuses_while_a_lease_is_held(tmp_path, name, monkeypatch):
    model = _model(tmp_path)
    tool = model.tools.watermark if name.endswith("watermark") else model.tools.annotation
    before = _bytes(model)
    fired: list[str] = []
    for owner, attr in MUTATORS + ((fitz.Page, "add_highlight_annot"), (fitz.Page, "add_rect_annot"), (fitz.Page, "add_text_annot"), (fitz.Annot, "update"), (fitz.Annot, "set_flags")):
        monkeypatch.setattr(owner, attr, lambda *a, _n=attr, **k: fired.append(_n))
    with model.write_gate.begin("vector_delete", model.get_active_session_id()):
        with pytest.raises(WriteGateBusy):
            TOOL_CALLS[name](tool)
    assert not fired and _bytes(model) == before


# ---- Astra round 2: explicit publish, FIFO, latched session ----------------------------------------
def test_a_transaction_that_never_recorded_still_drains_once_the_document_is_whole(tmp_path):
    """commit returned None / the caller returned early: nothing was published and nothing is half-done, so the
    queued OCR page is written exactly as it would be after a serial run of the same (empty) transaction."""
    model = _model(tmp_path)
    with model.write_transaction("vector_delete"):
        model.submit_ocr_page(1, [SPAN])
    assert not model.write_gate.active and model.pending_ocr_count == 0 and "hello" in _text(model)


# ---- G4: one publish point, recovery on failure, index rebound after the record (Astra r3 must-fix 3) -----
def _history(model):
    cm = model.command_manager
    return (list(cm._undo_stack), list(cm._redo_stack), cm._saved_marker)


def test_after_capture_failure_restores_the_document_and_history(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    before, history = _bytes(model), _history(model)
    holder = []
    with pytest.raises(RuntimeError, match="after-capture"):
        with model.write_transaction("vector_delete") as lease:
            holder.append(lease)
            assert model.commit_vector_plan(plan, token, lease=lease) is not None
            raise RuntimeError("after-capture failed")
    assert _bytes(model) == before and _history(model) == history
    assert not model.write_gate.active and not holder[0].published and model.vector_editing_blocked is None


def test_a_successful_commit_that_is_never_recorded_is_rolled_back(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    before = _bytes(model)
    with model.write_transaction("vector_delete") as lease:
        assert model.commit_vector_plan(plan, token, lease=lease) is not None
    assert _bytes(model) == before and not model.write_gate.active  # written, not published: put back, never half-done


@pytest.mark.parametrize("where", ["_dedup_top_snapshot_pair", "_trim_undo_stack_if_needed", "_discard_redo_stack"])
def test_record_failure_leaves_document_and_history_as_before(tmp_path, monkeypatch, where):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    snap = model._capture_doc_snapshot()
    model.command_manager._redo_stack.append(SnapshotCommand(model, "old", [1], snap, snap, "old"))  # so the discard really runs
    before, history = _bytes(model), _history(model)
    cm = model.command_manager

    def boom(*_a, **_k):
        raise RuntimeError("record failed")

    monkeypatch.setattr(cm, where, boom)
    holder = []
    with pytest.raises(RuntimeError, match="record failed"):
        with model.write_transaction("vector_delete") as lease:
            holder.append(lease)
            assert model.commit_vector_plan(plan, token, lease=lease) is not None
            after = model._capture_doc_snapshot()
            cm.record(SnapshotCommand(model, "vector_delete", [1], snap, after, "x"), lease=lease)
    monkeypatch.undo()
    assert _bytes(model) == before and _history(model) == history and not holder[0].published
    assert not model.write_gate.active


def test_published_is_set_only_after_the_redo_stack_was_discarded(tmp_path, monkeypatch):
    model = _model(tmp_path)
    snap = model._capture_doc_snapshot()
    cm = model.command_manager
    cm._redo_stack.append(SnapshotCommand(model, "old", [1], snap, snap, "old"))
    seen = []
    real = cm._discard_redo_stack
    monkeypatch.setattr(cm, "_discard_redo_stack", lambda: (seen.append(lease.published), real()))
    with model.write_transaction("x") as lease:
        cm.record(SnapshotCommand(model, "x", [1], snap, snap, "x"), lease=lease)
    assert seen == [False] and lease.published


def test_derived_index_is_bound_to_the_recorded_revision(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    snap = model._capture_doc_snapshot()
    with model.write_transaction("vector_delete") as lease:
        assert model.commit_vector_plan(plan, token, lease=lease) is not None
        after = model._capture_doc_snapshot()
        model.command_manager.record(SnapshotCommand(model, "vector_delete", [1], snap, after, "x"), lease=lease)
    assert model.pending_ocr_count == 0 and model.vector_index(1) is plan.derived  # the record moved the revision; the index follows


def test_activating_another_session_is_refused_while_the_gate_is_held(tmp_path):
    model = _model(tmp_path)
    sid = model.get_active_session_id()
    with model.write_gate.begin("vector_delete", sid):
        with pytest.raises(WriteGateBusy):
            model.activate_session(sid)
    model.activate_session(sid)  # free again


# ---- G2: OCR direct path shares the latch and the source proof (Astra r3 must-fix 4) --------------------
def test_latched_empty_fifo_refuses_direct_ocr(tmp_path):
    model = _model(tmp_path)
    before = _bytes(model)
    model.vector_editing_blocked = "restore mismatch"
    outcome = model.submit_ocr_page(1, [SPAN])  # gate free, queue empty: the branch the old latch test skipped
    assert isinstance(outcome, Stale) and _bytes(model) == before and model.pending_ocr_count == 0
    model.vector_editing_blocked = None


def test_ocr_result_rejects_a_replaced_page_with_the_same_geometry(tmp_path):
    model = _model(tmp_path)
    proof = model.ocr_source_key(1)  # what the page looked like when its snapshot went to the worker
    model.doc.update_stream(model.doc[0].get_contents()[0], b"0 1 0 rg 10 10 30 30 re f")  # same xref, rotation, rect, cropbox
    before = _bytes(model)
    outcome = model.submit_ocr_page(1, [SPAN], source=proof)
    assert isinstance(outcome, Stale) and _bytes(model) == before and _text(model) == ""


def test_a_queued_result_carries_its_source_proof_to_the_drain(tmp_path):
    model = _model(tmp_path)
    proof = model.ocr_source_key(1)
    lease = model.write_gate.begin("vector_delete", model.get_active_session_id())
    assert isinstance(model.submit_ocr_page(1, [SPAN], source=proof), Deferred)
    model.doc.update_stream(model.doc[0].get_contents()[0], b"0 1 0 rg 10 10 30 30 re f")  # changed after the queue, before the drain
    lease.release()
    assert [type(o) for o in model.drain_pending_ocr()] == [Stale] and _text(model) == ""


def test_an_unchanged_page_accepts_its_source_proof(tmp_path):
    model = _model(tmp_path)
    outcome = model.submit_ocr_page(1, [SPAN], source=model.ocr_source_key(1))
    assert isinstance(outcome, Applied) and "hello ocr" in _text(model)


def test_record_with_the_lease_is_the_publish_that_allows_the_drain(tmp_path):
    model = _model(tmp_path)
    snap = model._capture_doc_snapshot()
    with model.write_transaction("x") as lease:
        model.submit_ocr_page(1, [SPAN])
        assert not lease.published
        model.command_manager.record(SnapshotCommand(model, "x", [1], snap, snap, "x"), lease=lease)
        assert lease.published
    assert model.pending_ocr_count == 0 and "hello ocr" in _text(model)


def test_a_direct_submit_never_jumps_ahead_of_queued_pages(tmp_path):
    model = _model(tmp_path)
    first = SimpleNamespace(bbox=(20.0, 20.0, 120.0, 40.0), text="first page-one", confidence=90.0)
    second = SimpleNamespace(bbox=(20.0, 60.0, 120.0, 80.0), text="second page-one", confidence=90.0)
    lease = model.write_gate.begin("x", model.get_active_session_id())
    model.submit_ocr_page(1, [first])
    lease.release()
    outcome = model.submit_ocr_page(1, [second])  # arrives after release, before the queue was drained
    assert isinstance(outcome, Applied) and model.pending_ocr_count == 0
    text = _text(model)
    assert text.index("first page-one") < text.index("second page-one")


def test_a_latched_session_never_drains_ocr(tmp_path):
    model = _model(tmp_path)
    lease = model.write_gate.begin("x", model.get_active_session_id())
    model.submit_ocr_page(1, [SPAN])
    lease.release()
    model.vector_editing_blocked = "restore mismatch"
    assert model.drain_pending_ocr() == [] and model.pending_ocr_count == 1 and _text(model) == ""
    model.vector_editing_blocked = None
    assert [type(o) for o in model.drain_pending_ocr()] == [Applied]


# ---- the inventory is derived, not hand-kept (Astra r2 / advisor: same mechanism, second round) -------
_MUTATORS = frozenset(
    "update_stream xref_set_key insert_text insert_textbox delete_page delete_pages insert_pdf set_metadata set_toc new_page "
    "insert_page add_highlight_annot add_underline_annot add_strikeout_annot add_rect_annot add_text_annot add_redact_annot "
    "apply_redactions set_rotation set_cropbox insert_image move_page copy_page set_flags update_object delete_annot "
    "set_rect save saveIncr".split()
)


def writer_candidates(source: str, class_name: str) -> dict[str, tuple[set[str], set[str]]]:
    """public method -> (fitz mutators reachable through self-calls, non-getattr callees that receive self)."""
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}

    def walk(name: str, seen: set[str], muts: set[str], dels: set[str]) -> None:
        if name in seen or name not in methods:
            return
        seen.add(name)
        for node in ast.walk(methods[name]):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in _MUTATORS:
                    muts.add(func.attr)
                if isinstance(func.value, ast.Name) and func.value.id == "self":
                    walk(func.attr, seen, muts, dels)
            if any(isinstance(a, ast.Name) and a.id == "self" for a in node.args):
                callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "?")
                if callee != "getattr":
                    dels.add(callee)

    out = {}
    for name in methods:
        if name.startswith("_"):
            continue
        muts: set[str] = set()
        dels: set[str] = set()
        walk(name, set(), muts, dels)
        if muts or dels:
            out[name] = (muts, dels)
    return out


def test_the_derivation_finds_an_unlisted_writer():
    src = "class C:\n    def sneaky(self):\n        self._go()\n    def _go(self):\n        self.doc.update_stream(1, b'')\n    def viaFree(self):\n        helper(self)\n"
    found = writer_candidates(src, "C")
    assert found["sneaky"][0] == {"update_stream"} and found["viaFree"][1] == {"helper"}


@pytest.mark.parametrize(
    "path, cls, gated",
    [
        ("model/pdf_model.py", "PDFModel", set(GATED_MODEL_METHODS)),
        ("model/tools/annotation_tool.py", "AnnotationTool", set(GATED_TOOL_METHODS["AnnotationTool"])),
        ("model/tools/watermark_tool.py", "WatermarkTool", set(GATED_TOOL_METHODS["WatermarkTool"])),
    ],
)
def test_every_public_method_that_reaches_a_mutator_or_delegates_is_gated_or_explained(path, cls, gated):
    source = (REPO_ROOT / path).read_text(encoding="utf-8-sig")
    candidates = writer_candidates(source, cls)
    unclassified = sorted(set(candidates) - gated - set(NOT_A_WRITE_ENTRY))
    assert not unclassified, f"{cls}: gate these in model/write_gate.py or explain them in NOT_A_WRITE_ENTRY: {unclassified}"


def test_the_explanations_are_not_stale():
    seen: set[str] = set()
    for path, cls in (("model/pdf_model.py", "PDFModel"), ("model/tools/annotation_tool.py", "AnnotationTool"), ("model/tools/watermark_tool.py", "WatermarkTool")):
        seen |= set(writer_candidates((REPO_ROOT / path).read_text(encoding="utf-8-sig"), cls))
    stale = sorted(set(NOT_A_WRITE_ENTRY) - seen)
    assert not stale, f"explained but no longer a candidate: {stale}"


# ---- r4 must-fix 4: one digest, one deletion range --------------------------------------------------
def test_plan_delete_refuses_a_mask_that_is_not_boolean(tmp_path):
    model = _model(tmp_path)
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    index, mask, streams = model.vector_plan_inputs(all_.token)
    as_int = np.array([2, 1][: len(mask)], dtype=np.int64)  # bitwise & would select only some rows, the digest sees both
    with pytest.raises(ValueError):
        plan_delete(index, as_int, streams)


def test_selection_mask_view_does_not_expose_the_live_array(tmp_path):
    model = _model(tmp_path)
    model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    view = model.vector_selection_mask()
    base = view.base
    assert base is None or not base.flags.writeable


# ---- r4 must-fix 1: one transaction owns document, history, index and lease ------------------------
def _two_sessions(model, tmp_path):
    first = model.get_active_session_id()
    other = tmp_path / "other"
    other.mkdir()
    _model(other).close()
    model.open_pdf(str(other / "g.pdf"), append=True)
    second = model.get_active_session_id()
    assert second != first
    model.activate_session(first)
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    return first, second


def _record_then(model, plan, token, snap, lease):
    assert model.commit_vector_plan(plan, token, lease=lease) is not None
    after = model._capture_doc_snapshot()
    model.command_manager.record(SnapshotCommand(model, "vector_delete", [1], snap, after, "x"), lease=lease)


def test_failure_after_the_record_takes_the_history_back_with_the_document(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    snap = model._capture_doc_snapshot()
    before, history = _bytes(model), _history(model)
    with pytest.raises(RuntimeError, match="after the record"):
        with model.write_transaction("vector_delete") as lease:
            _record_then(model, plan, token, snap, lease)
            assert lease.published
            raise RuntimeError("after the record")
    assert _bytes(model) == before and _history(model) == history  # no deleted document with a kept command, or the reverse
    assert not model.write_gate.active


def test_index_rebind_failure_rolls_everything_back_and_releases_the_lease(tmp_path, monkeypatch):
    model = _model(tmp_path)
    token, plan = _select_second(model)
    snap = model._capture_doc_snapshot()
    before, history = _bytes(model), _history(model)
    real = model.install_vector_index
    holder = []

    def flaky(page_num, derived):
        if holder and holder[0].published:  # the rebind after the record; the commit's own install passes
            raise RuntimeError("rebind failed")
        return real(page_num, derived)

    monkeypatch.setattr(model, "install_vector_index", flaky)
    with pytest.raises(RuntimeError, match="rebind failed"):
        with model.write_transaction("vector_delete") as lease:
            holder.append(lease)
            _record_then(model, plan, token, snap, lease)
    monkeypatch.undo()
    assert not model.write_gate.active, "a failed rebind must not leave the document locked"
    assert _bytes(model) == before and _history(model) == history


def test_a_failed_recovery_is_reported_to_the_caller_not_only_logged(tmp_path):
    model = _model(tmp_path)
    token, plan = _select_second(model)

    def broken():
        raise RuntimeError("restore failed")

    with pytest.raises(Exception, match="recovery") as info:
        with model.write_transaction("vector_delete") as lease:
            assert model.commit_vector_plan(plan, token, lease=lease) is not None
            lease.undo_write = broken  # never recorded -> the transaction must put the document back and cannot
    assert not model.write_gate.active
    assert type(info.value).__name__ == "TransactionRecoveryFailed"


# ---- r4 must-fix 2: the rollback target is the document the transaction wrote --------------------------
def test_a_vector_transaction_cannot_switch_the_session_even_with_its_own_lease(tmp_path):
    model = _model(tmp_path)
    first, second = _two_sessions(model, tmp_path)
    token, plan = _select_second(model)
    before = _bytes(model)
    with pytest.raises(WriteGateBusy):
        with model.write_transaction("vector_delete") as lease:
            assert model.commit_vector_plan(plan, token, lease=lease) is not None
            model.activate_session(second, write_lease=lease)
    assert model.get_active_session_id() == first and _bytes(model) == before and not model.write_gate.active


def test_recovery_never_restores_into_another_session(tmp_path):
    model = _model(tmp_path)
    first, second = _two_sessions(model, tmp_path)
    token, plan = _select_second(model)
    ran = []
    with pytest.raises(Exception) as info:
        with model.write_transaction("vector_delete") as lease:
            assert model.commit_vector_plan(plan, token, lease=lease) is not None
            lease.undo_write = lambda: ran.append("restored into whatever is active")
            model._active_session_id = second  # something switched the active session behind the lease
    model._active_session_id = first
    assert not ran, "the snapshot of one session was installed into another"
    assert type(info.value).__name__ == "TransactionRecoveryFailed"
    assert not model.write_gate.active


# ---- r4 must-fix 3: the OCR proof covers the page image, and comes from the bytes the worker was given ----
def _with_image(model):
    page = model.doc[0]
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 8, 8), False)
    pix.clear_with(40)
    page.insert_image(fitz.Rect(20, 20, 120, 120), pixmap=pix)
    return page.get_images(full=True)[0][0]


def test_ocr_result_rejects_a_replaced_scan_image(tmp_path):
    model = _model(tmp_path)
    xref = _with_image(model)
    proof = model.ocr_source_key(1)
    model.doc.update_stream(xref, bytes([200]) * 64, compress=False)  # same page, same /Contents, other pixels
    before = _bytes(model)
    outcome = model.submit_ocr_page(1, [SPAN], source=proof)
    assert isinstance(outcome, Stale) and _bytes(model) == before


def test_source_proof_taken_from_the_snapshot_equals_the_live_proof_of_an_unchanged_page(tmp_path):
    model = _model(tmp_path)
    _with_image(model)
    snapshot = model.capture_worker_snapshot_bytes()
    assert model.ocr_source_keys_from_snapshot(snapshot, [1, 2]) == {1: model.ocr_source_key(1), 2: model.ocr_source_key(2)}


def test_source_proof_from_a_stale_snapshot_no_longer_matches_the_live_page(tmp_path):
    model = _model(tmp_path)
    xref = _with_image(model)
    snapshot = model.capture_worker_snapshot_bytes()  # what the worker recognises
    model.doc.update_stream(xref, bytes([200]) * 64, compress=False)  # the live page moved on meanwhile
    proof = model.ocr_source_keys_from_snapshot(snapshot, [1])[1]
    assert isinstance(model.submit_ocr_page(1, [SPAN], source=proof), Stale)
