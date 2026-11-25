"""Card B6 part 2: the vector delete transaction (design plan 4.3 and 5.3, plans/b6-commit-design-astra.md).

``commit_delete(model, plan, token)`` runs on the GUI thread.  Order: bind (token, session, index), gate (decoded digests,
frame, page object, encryption), capture (snapshot, prestate, bookkeeping, T0), declare (in place only for an exclusive
stream; otherwise a copy), write, verify (planned digest, filter keys, retained dictionary, Rule B), publish.  Any failure
after the first mutating call restores the whole document and verifies the restore; a restore that does not verify
latches vector editing off for the session.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import fitz

from model.object_op_refusal import ObjectOpRefusal, ObjectOpRefused
from model.vector_paths import commit_state as cs
from model.vector_paths.edit import VectorPlan
from model.doc_bytes import source_is_encrypted
from utils.pdf_object_source import xref_object_exact, xref_set_key_exact

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

LATCH_RESTORE_MISMATCH = "此文件在還原後與原狀不一致，本次工作階段已停用向量編輯"
_SLOW_PASS_MS = 400.0
_REF = re.compile(r"\d+\s+\d+\s+R(?![^\s/<>\[\](){}%])")
_ONE_REF = re.compile(r"^(\d+)\s+\d+\s+R$")
_DROPPED = frozenset({"/Filter", "/DecodeParms", "/DL", "/Length"})


@dataclass(frozen=True)
class VectorCommitResult:
    before_bytes: bytes
    digest_before: cs.DigestTable
    digest_after: cs.DigestTable


class _Refused(Exception):
    def __init__(self, reason: ObjectOpRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _fail(model: PDFModel, reason: ObjectOpRefusal) -> None:
    model.last_object_op_refusal = ObjectOpRefused(reason)
    return None


def _items(doc: fitz.Document, xref: int) -> list[tuple[str, str]]:
    text = xref_object_exact(doc, xref)
    items = cs.exact_dict_items(text)
    if items is None:
        raise _Refused(ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
    return items


def commit_delete(
    model: PDFModel, plan: VectorPlan, token: int, on_yield: Callable[[int, int], None] | None = None
) -> VectorCommitResult | None:
    """Public entry: any exception before the first mutating call (gate, capture) is a recorded refusal, not a raise."""
    try:
        return _run(model, plan, token, on_yield)
    except Exception:
        logger.exception("vector commit failed outside the write window (gate, capture or restore)")
        model.__dict__["_vector_selection"] = None
        _fail(model, ObjectOpRefusal.OPERATION_FAILED)
        return None


def _run(
    model: PDFModel, plan: VectorPlan, token: int, on_yield: Callable[[int, int], None] | None
) -> VectorCommitResult | None:
    from model.pdf_content_ops import page_user_space_matrix

    state = model.__dict__.get("_vector_selection")
    if state is None or state[1] != token or state[4] != model.handle_generation:
        _fail(model, ObjectOpRefusal.VECTOR_SELECTION_STALE)
        return None
    page_num = int(state[0])
    if model.vector_editing_blocked is not None or plan.kind != "delete" or not model.doc:
        _fail(model, ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
        return None
    if model.vector_index(page_num) is not state[3]:
        _fail(model, ObjectOpRefusal.VECTOR_SELECTION_STALE)
        return None
    doc = model.doc
    page = doc[page_num - 1]
    xrefs = [int(x) for x in page.get_contents()]
    lengths = {len(xrefs), len(plan.source_digests), len(plan.new_streams), len(plan.new_compressed), len(plan.planned_digests)}
    if lengths != {len(xrefs)}:
        _fail(model, ObjectOpRefusal.VECTOR_SELECTION_STALE)
        return None
    import hashlib

    if tuple(hashlib.sha256(doc.xref_stream(x) or b"").digest() for x in xrefs) != tuple(plan.source_digests):
        _fail(model, ObjectOpRefusal.VECTOR_SELECTION_STALE)
        return None
    if page_user_space_matrix(page) != tuple(plan.frame):
        _fail(model, ObjectOpRefusal.VECTOR_SELECTION_STALE)
        return None
    if len(set(xrefs)) != len(xrefs) or sum(1 for i in range(len(doc)) if doc.page_xref(i) == page.xref) != 1:
        _fail(model, ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
        return None
    if source_is_encrypted(doc):  # not is_encrypted/needs_pass: both go False/clobber the key once authenticated
        _fail(model, ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
        return None
    edited = [i for i, c in enumerate(plan.new_compressed) if c is not None]
    if not edited or any((plan.new_streams[i] is None) or (plan.planned_digests[i] is None) for i in edited):
        _fail(model, ObjectOpRefusal.VECTOR_NOTHING_EDITABLE)
        return None
    slow = model.vector_last_pass_ms > _SLOW_PASS_MS
    before = model._capture_doc_snapshot()
    saved_pending = list(model.pending_edits)
    saved_edits = model.edit_count
    saved_secure = model.secure_save_required
    mutated = False
    try:
        prior = cs.vector_page_prestate(doc, page)
        t0 = cs.digest_table(doc, on_yield=on_yield if slow else None)
        model.vector_last_pass_ms = t0.elapsed_ms

        # ---- declare
        objstm = b"/ObjStm" in before
        array_xref = None
        if prior.contents is not None:
            m = _ONE_REF.match(prior.contents)
            if m and xref_object_exact(doc, int(m.group(1))).strip().startswith("["):
                array_xref = int(m.group(1))
        counts = cs.reference_counts(before, [*xrefs, *([array_xref] if array_xref is not None else [])])
        in_place: dict[int, bool] = {}
        retained: dict[int, list[tuple[str, str]]] = {}
        for i in edited:
            x = xrefs[i]
            items = _items(doc, x)
            has_ref = any(_REF.search(v) for k, v in items if k != "/Length") or any(
                k == "/Length" and _REF.search(v) for k, v in items
            )
            in_place[i] = not objstm and counts[x] == 1 and (array_xref is None or counts[array_xref] == 1) and not has_ref
            keep = []
            for k, v in items:
                if k in _DROPPED:
                    continue
                if not in_place[i] and _REF.search(v):
                    resolved = cs._resolve_scalar(doc, v)
                    if _REF.search(resolved):
                        raise _Refused(ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
                    v = resolved
                keep.append((k, v))
            retained[i] = keep
        copies = [i for i in edited if not in_place[i]]
        predicted = {i: t0.xref_length + n for n, i in enumerate(copies)}
        targets = {t for _s, t in t0.dangling}
        if any(x in targets for x in predicted.values()):
            raise _Refused(ObjectOpRefusal.VECTOR_PAGE_UNSUPPORTED)
        write_set = cs.WriteSet(
            page.xref, frozenset(xrefs[i] for i in edited if in_place[i]), frozenset(predicted.values())
        )

        # ---- write
        mutated = True
        final: list[int] = list(xrefs)
        for i in edited:
            data = plan.new_compressed[i]
            assert data is not None
            if in_place[i]:
                target = xrefs[i]
            else:
                target = doc.get_new_xref()
                if target != predicted[i]:
                    raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
                doc.update_object(target, "<< /Filter /FlateDecode >>")
                final[i] = target
            doc.update_stream(target, data, compress=False)
            length = doc.xref_get_key(target, "Length")[1]
            body = " ".join(f"{k} {v}" for k, v in retained[i])
            doc.update_object(target, f"<< /Filter /FlateDecode /Length {length} {body} >>")
        if copies:
            gens = {int(a): int(b) for a, b in re.findall(r"(\d+)\s+(\d+)\s+R", prior.contents or "")}
            fresh = set(predicted.values())
            refs = " ".join(f"{x} {0 if x in fresh else gens.get(x, 0)} R" for x in final)
            xref_set_key_exact(doc, page.xref, "Contents", f"[ {refs} ]")

        # ---- verify
        page = doc[page_num - 1]
        now = cs.vector_page_prestate(doc, page)
        if [s.xref for s in now.streams] != final or len(now.streams) != len(prior.streams):
            raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
        for i, (old, new) in enumerate(zip(prior.streams, now.streams, strict=True)):
            if i in edited:
                if new.decoded_sha256 != plan.planned_digests[i]:
                    raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
                if doc.xref_get_key(new.xref, "Filter") != ("name", "/FlateDecode"):
                    raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
                if any(doc.xref_get_key(new.xref, k)[0] != "null" for k in ("DecodeParms", "DL")):
                    raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
                keep_old = tuple((k, v) for k, v in old.dictionary if k not in _DROPPED)
                keep_new = tuple((k, v) for k, v in new.dictionary if k not in _DROPPED)
                if keep_old != keep_new:
                    raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
            elif new != old:
                raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
        if copies:
            serialized = model.serialize_document_bytes(doc)
            seen = cs.reference_counts(bytes(serialized), predicted.values())
            if any(c != 1 for c in seen.values()):
                raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)
        t1 = cs.digest_table(doc, on_yield=on_yield if slow else None)
        model.vector_last_pass_ms = t1.elapsed_ms
        bad = cs.undeclared(t0, t1, write_set)
        if bad:
            logger.warning("vector commit rejected: undeclared change in xrefs %s", bad[:20])
            raise _Refused(ObjectOpRefusal.VECTOR_COMMIT_REJECTED)

        # ---- publish
        model.edit_count = saved_edits + 1
        model.secure_save_required = True
        model.block_manager.mark_page_stale(page_num - 1)
        resolver = getattr(model, "_source_run_resolver", None)
        if resolver is not None and hasattr(resolver, "invalidate"):
            resolver.invalidate(page_num - 1)
        model.install_vector_index(page_num, plan.derived)
        model.__dict__["_vector_selection"] = None
        model.last_object_op_refusal = None
        return VectorCommitResult(before, t0, t1)
    except Exception as exc:
        reason = exc.reason if isinstance(exc, _Refused) else ObjectOpRefusal.OPERATION_FAILED
        if not isinstance(exc, _Refused):
            logger.exception("vector commit failed")
        if mutated:
            _roll_back(model, before, saved_pending, saved_edits, saved_secure, page_num, prior, t0)
        model.__dict__["_vector_selection"] = None
        _fail(model, reason)
        return None
def _roll_back(model, before, pending, edits, secure, page_num, prior, t0) -> None:
    model._restore_doc_after_failed_mutation(before)
    model.pending_edits = pending
    model.edit_count = edits
    model.secure_save_required = secure
    model.block_manager.clear()
    resolver = getattr(model, "_source_run_resolver", None)
    if resolver is not None and hasattr(resolver, "invalidate_all"):
        resolver.invalidate_all()
    model.__dict__.pop("_vector_indexes", None)
    try:
        ok = cs.vector_page_prestate(model.doc, model.doc[page_num - 1]) == prior and cs.equivalent(cs.digest_table(model.doc), t0)
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        model.vector_editing_blocked = LATCH_RESTORE_MISMATCH
        logger.error("vector commit rollback did not verify; vector editing latched off")
