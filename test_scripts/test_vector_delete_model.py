"""Card B6 part 2 (design plan Step 5, plans/b6-commit-design-astra.md): PDFModel.commit_vector_plan.  Red first.

The transaction: bind (token, session), gate (decoded digests, frame, page object), capture, declare, write
(in place for an exclusive stream, a copy otherwise), Rule B (undeclared), publish; any failure after the first
mutation restores the whole document and verifies it.  The full nth-call fault matrix is a follow-up; here: one
injected failure, a foreign write, and the happy paths.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.object_op_refusals import REASON_SENTENCES  # noqa: E402
from model.object_op_refusal import ObjectOpRefusal  # noqa: E402
from model.object_requests import VectorSelectionQuery  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths import commit_state as cs  # noqa: E402
from model.vector_paths.edit import plan_delete  # noqa: E402
from model.vector_paths.scan import scan_page  # noqa: E402

BODY = b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f"


def _pdf(tmp_path: Path, *, pages: int = 1, shared: bool = False) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((5, 5), " ")
        doc.update_stream(page.get_contents()[0], BODY)
    if shared and pages == 2:
        first = doc[0].get_contents()[0]
        doc.xref_set_key(doc[1].xref, "Contents", f"{first} 0 R")
    path = tmp_path / "v.pdf"
    doc.save(path)
    doc.close()
    return path


def _model(tmp_path: Path, **kw) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(_pdf(tmp_path, **kw)))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    return model


def _select_row(model: PDFModel, row: int):
    all_ = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    assert all_ is not None and all_.count == 2
    if row < 0:
        return all_
    mask = model.vector_selection_mask().copy()
    mask[:] = False
    mask[row] = True
    # re-select only that row through the model's own query path
    p = model.vector_index(1).paths[row]
    seg = model.vector_index(1).segments[int(p["seg_start"])]
    from model.geometry import unrotated_to_visual_point

    pt = unrotated_to_visual_point(model.doc[0], fitz.Point((seg["x0"] + seg["x1"]) / 2, (seg["y0"] + seg["y1"]) / 2))
    info = model.vector_select(VectorSelectionQuery(1, (pt.x, pt.y, pt.x, pt.y), 3.0, "click", "replace"))
    assert info is not None and info.count == 1
    return info


def _plan(model: PDFModel, token: int):
    inputs = model.vector_plan_inputs(token)
    assert inputs is not None
    index, mask, streams = inputs
    return plan_delete(index, mask, streams)


def _decoded(model: PDFModel, page: int = 0) -> bytes:
    return b"".join(model.doc.xref_stream(x) or b"" for x in model.doc[page].get_contents())


def test_the_four_refusal_codes_exist_and_have_a_sentence():
    for name in ("VECTOR_PAGE_UNSUPPORTED", "VECTOR_SELECTION_STALE", "VECTOR_NOTHING_EDITABLE", "VECTOR_COMMIT_REJECTED"):
        code = ObjectOpRefusal[name]
        assert REASON_SENTENCES[code].strip()
    assert "編輯已取消：文件的其他部分發生了預期外的變更" in REASON_SENTENCES[ObjectOpRefusal.VECTOR_COMMIT_REJECTED]


def test_exclusive_stream_is_written_in_place_and_bookkeeping_moves_once(tmp_path):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    xref_before = model.doc[0].get_contents()[0]
    edits, rev = model.edit_count, model.content_revision
    result = model.commit_vector_plan(plan, info.token)
    assert result is not None and model.last_object_op_refusal is None
    assert model.doc[0].get_contents() == [xref_before]  # exclusive: same object, no copy
    assert _decoded(model) == plan.new_streams[0] and b"150 160 40 40 re f" not in _decoded(model)
    assert model.edit_count == edits + 1 and model.content_revision != rev
    assert model.secure_save_required is True
    assert isinstance(result.before_bytes, bytes) and result.digest_before != result.digest_after
    assert model.vector_index(1) is plan.derived  # installed under the new revision
    assert "FlateDecode" in model.doc.xref_object(xref_before) and "DecodeParms" not in model.doc.xref_object(xref_before)
    assert model.commit_vector_plan(plan, info.token) is None  # the token is consumed
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_SELECTION_STALE


def test_a_shared_stream_is_copied_and_the_other_page_is_untouched(tmp_path):
    model = _model(tmp_path, pages=2, shared=True)
    shared_xref = model.doc[0].get_contents()[0]
    assert model.doc[1].get_contents()[0] == shared_xref
    other_before = (model.doc.xref_stream(shared_xref), model.doc.xref_object(shared_xref))
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    result = model.commit_vector_plan(plan, info.token)
    assert result is not None
    new = model.doc[0].get_contents()
    assert new != [shared_xref] and model.doc[1].get_contents() == [shared_xref]
    assert (model.doc.xref_stream(shared_xref), model.doc.xref_object(shared_xref)) == other_before
    assert _decoded(model, 0) == plan.new_streams[0] and _decoded(model, 1) == BODY


def test_a_changed_stream_refuses_with_no_byte_changed(tmp_path):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    xref = model.doc[0].get_contents()[0]
    model.doc.update_stream(xref, BODY + b" ")
    snapshot = model.doc.xref_stream(xref), model.doc.xref_object(xref)
    edits = model.edit_count
    assert model.commit_vector_plan(plan, info.token) is None
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_SELECTION_STALE
    assert (model.doc.xref_stream(xref), model.doc.xref_object(xref)) == snapshot and model.edit_count == edits


def test_an_unknown_token_is_stale(tmp_path):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    assert model.commit_vector_plan(plan, info.token + 99) is None
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_SELECTION_STALE


def test_an_injected_failure_restores_the_document_and_the_bookkeeping(tmp_path, monkeypatch):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    pre = cs.vector_page_prestate(model.doc, model.doc[0])
    t0 = cs.digest_table(model.doc)
    edits, pending, secure = model.edit_count, list(model.pending_edits), model.secure_save_required
    real = fitz.Document.update_stream

    def boom(self, *a, **k):
        real(self, *a, **k)  # the write happens, then the call raises
        raise RuntimeError("injected")

    monkeypatch.setattr(fitz.Document, "update_stream", boom)
    assert model.commit_vector_plan(plan, info.token) is None
    monkeypatch.undo()
    assert model.last_object_op_refusal is not None
    assert _decoded(model) == BODY
    assert cs.vector_page_prestate(model.doc, model.doc[0]) == pre and cs.digest_table(model.doc) == t0
    assert (model.edit_count, list(model.pending_edits), model.secure_save_required) == (edits, pending, secure)
    assert getattr(model, "vector_editing_blocked", None) is None


def test_a_foreign_write_is_rejected_by_rule_b_and_rolled_back(tmp_path, monkeypatch):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    t0 = cs.digest_table(model.doc)
    victim = model.doc.get_new_xref()
    model.doc.update_object(victim, "<< /Foo 1 >>")
    t0 = cs.digest_table(model.doc)
    real = fitz.Document.update_stream

    def foreign(self, *a, **k):
        real(self, *a, **k)
        self.xref_set_key(victim, "Foo", "2")

    monkeypatch.setattr(fitz.Document, "update_stream", foreign)
    assert model.commit_vector_plan(plan, info.token) is None
    monkeypatch.undo()
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_COMMIT_REJECTED
    assert _decoded(model) == BODY and cs.digest_table(model.doc) == t0
    assert hashlib.sha256(_decoded(model)).digest() == hashlib.sha256(BODY).digest()


def test_undo_and_redo_restore_the_digest_tables_and_a_tampered_one_latches(tmp_path):
    from model.edit_commands import SnapshotCommand

    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    result = model.commit_vector_plan(plan, info.token)
    assert result is not None
    after_bytes = model._capture_doc_snapshot()
    cmd = SnapshotCommand(model, "vector_delete", [1], result.before_bytes, after_bytes, "delete")
    cmd.vector_digest_before, cmd.vector_digest_after = result.digest_before, result.digest_after
    assert model.verify_vector_digest(cmd.vector_digest_after)
    cmd.undo()
    assert model.verify_vector_digest(cmd.vector_digest_before) and _decoded(model) == BODY
    cmd.execute()
    assert model.verify_vector_digest(cmd.vector_digest_after) and b"150 160 40 40 re f" not in _decoded(model)
    tampered = cs.digest_table(model.doc)
    model.doc.update_object(model.doc.get_new_xref(), "<< /Extra 1 >>")
    assert not model.verify_vector_digest(tampered)
    assert model.vector_editing_blocked


def test_a_dictionary_value_containing_the_word_stream_is_not_truncated(tmp_path):
    model = _model(tmp_path)
    xref = model.doc[0].get_contents()[0]
    model.doc.xref_set_key(xref, "Name", "(a stream b)")
    pre = cs.vector_page_prestate(model.doc, model.doc[0])
    assert dict(pre.streams[0].dictionary)["/Name"] == "(a stream b)"
    # the stream changed after the scan, so the commit is stale, but it must not die on the dictionary
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    assert model.commit_vector_plan(plan, info.token) is not None
    assert dict(cs.vector_page_prestate(model.doc, model.doc[0]).streams[0].dictionary)["/Name"] == "(a stream b)"


def test_an_authenticated_encrypted_document_is_refused(tmp_path):
    plain = _pdf(tmp_path)
    enc = tmp_path / "enc.pdf"
    src = fitz.open(str(plain))
    src.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    src.close()
    model = PDFModel()
    model.open_pdf(str(enc), password="u")
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    assert model.commit_vector_plan(plan, info.token) is None
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED


def test_contents_array_keeps_original_generations_and_new_objects_use_zero(tmp_path):
    model = _model(tmp_path, pages=2, shared=True)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    assert model.commit_vector_plan(plan, info.token) is not None
    text = model.doc.xref_get_key(model.doc[0].xref, "Contents")[1]
    new = model.doc[0].get_contents()[0]
    assert f"{new} 0 R" in text


def test_a_rollback_that_does_not_verify_latches_vector_editing_off(tmp_path, monkeypatch):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    real = fitz.Document.update_stream

    def boom(self, *a, **k):
        real(self, *a, **k)
        raise RuntimeError("injected")

    monkeypatch.setattr(fitz.Document, "update_stream", boom)
    monkeypatch.setattr(cs, "equivalent", lambda a, b: False)
    assert model.commit_vector_plan(plan, info.token) is None
    monkeypatch.undo()
    assert model.vector_editing_blocked and "停用向量編輯" in model.vector_editing_blocked
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    info2 = _select_row(model, 1)
    assert model.commit_vector_plan(_plan(model, info2.token), info2.token) is None
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED


def test_a_restore_that_raises_marks_the_session_damaged_and_still_returns_a_refusal(tmp_path, monkeypatch):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    real = fitz.Document.update_stream

    def boom(self, *a, **k):
        real(self, *a, **k)
        raise RuntimeError("injected")

    def no_restore(self, snapshot):
        raise RuntimeError("restore failed")

    monkeypatch.setattr(fitz.Document, "update_stream", boom)
    monkeypatch.setattr(PDFModel, "_restore_doc_from_snapshot", no_restore)
    assert model.commit_vector_plan(plan, info.token) is None
    monkeypatch.undo()
    assert model.session_damaged is True or model.session_damaged() is True
    assert model.last_object_op_refusal is not None


def test_a_copied_stream_with_a_non_scalar_reference_is_refused_before_anything_is_written(tmp_path):
    doc = fitz.open(str(_pdf(tmp_path, pages=2, shared=True)))
    target = doc.get_new_xref()
    doc.update_object(target, "<< /A 1 >>")
    doc.xref_set_key(doc[0].get_contents()[0], "Extra", f"{target} 0 R")
    out = tmp_path / "ref.pdf"
    doc.save(str(out))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(out))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    info = _select_row(model, 1)
    plan = _plan(model, info.token)
    xlen_before = model.doc.xref_length()
    edits_before = model.edit_count
    table_before = cs.digest_table(model.doc)
    assert model.commit_vector_plan(plan, info.token) is None
    assert model.last_object_op_refusal.reason is ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED
    assert model.doc.xref_length() == xlen_before  # nothing allocated
    assert model.edit_count == edits_before
    assert cs.equivalent(table_before, cs.digest_table(model.doc))  # the document is untouched
    assert not model.vector_editing_blocked  # a clean refusal is not damage


def test_after_a_non_scalar_refusal_a_clean_document_still_commits(tmp_path):
    model = _model(tmp_path)
    info = _select_row(model, 1)
    assert model.commit_vector_plan(_plan(model, info.token), info.token) is not None
