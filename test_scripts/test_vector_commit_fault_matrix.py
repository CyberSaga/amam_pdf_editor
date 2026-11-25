"""Card B6 part 2: the fault matrix (design plan Step 5, "the class check for the mutation boundary").

For the duration of a commit the test patches the CALLABLES of the real fitz.Document and fitz.Page classes (a wrapper
object would fail the native serialiser) and counts every call that is not on a short read-only allowlist, so a mutator
nobody listed is still faulted.  A successful commit is traced once; then for every n up to the count a fresh fixture
runs the same commit with the n-th counted call raising (once).  After each: a refusal is recorded or the commit
succeeded untouched; the page prestate, the whole-document digest table, bookkeeping and the text of the page equal
the pre-state; vector editing is not latched.
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import fitz
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.object_requests import VectorSelectionQuery  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths import commit as commit_module  # noqa: E402
from model.vector_paths import commit_state as cs  # noqa: E402
from model.vector_paths.edit import plan_delete  # noqa: E402
from model.vector_paths.scan import scan_page  # noqa: E402

BODY = b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f"
READ_ONLY = frozenset(
    {
        "page_xref", "xref_length", "xref_get_key", "xref_object", "xref_stream", "xref_stream_raw", "xref_is_stream",
        "load_page", "get_contents", "__getitem__", "__len__", "page_count", "is_closed", "is_encrypted", "needs_pass",
        "xref_get_keys", "__repr__", "__str__", "__bool__", "__del__", "__enter__", "__exit__", "__init__", "_getPageInfo",
        "metadata", "name", "get_page_xobjects", "_get_page_objects", "xref_is_font", "xref_is_image", "xref_is_xobject",
        "is_form_pdf", "_pdf_page", "is_pdf", "is_dirty", "permissions", "isPDF", "get_xml_metadata", "_page_xref", "pdf_catalog",
    }
)


def _build(tmp_path: Path, shared: bool) -> PDFModel:
    doc = fitz.open()
    for _ in range(2 if shared else 1):
        page = doc.new_page(width=300, height=400)
        page.insert_text((5, 5), " ")
        doc.update_stream(page.get_contents()[0], BODY)
    if shared:
        doc.xref_set_key(doc[1].xref, "Contents", f"{doc[0].get_contents()[0]} 0 R")
    path = tmp_path / ("s.pdf" if shared else "e.pdf")
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    return model


class _Counter:
    def __init__(self, fail_at: int | None) -> None:
        self.n = 0
        self.fail_at = fail_at
        self.fired = False
        self.names: list[str] = []

    def install(self, mp: pytest.MonkeyPatch) -> None:
        for cls in (fitz.Document, fitz.Page):
            for name in dir(cls):
                if name in READ_ONLY or (name.startswith("__") and name.endswith("__")):
                    continue
                attr = getattr(cls, name, None)
                if not callable(attr) or isinstance(attr, type):
                    continue
                mp.setattr(cls, name, self._wrap(cls.__name__ + "." + name, attr))
        # the native /Contents write bypasses fitz.Document: count it where commit.py calls it
        mp.setattr(commit_module, "xref_set_key_exact", self._wrap("xref_set_key_exact", commit_module.xref_set_key_exact))

    def _wrap(self, label: str, fn):
        def call(*a, **k):
            self.n += 1
            self.names.append(label)
            if self.fail_at is not None and self.n == self.fail_at and not self.fired:
                self.fired = True
                raise RuntimeError(f"injected fault at call {self.n} ({label})")
            return fn(*a, **k)

        call.__name__ = getattr(fn, "__name__", "call")
        return call


def _commit(model: PDFModel, counter: _Counter, mp: pytest.MonkeyPatch):
    info = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    inputs = model.vector_plan_inputs(info.token)
    plan = plan_delete(*inputs)
    gc.collect()
    gc.disable()  # finalisers (Document.close, _reset_page_refs) would move the call numbers between runs
    counter.install(mp)
    try:
        return model.commit_vector_plan(plan, info.token)
    finally:
        mp.undo()
        gc.enable()


def _state(model: PDFModel):
    return (
        cs.vector_page_prestate(model.doc, model.doc[0]),
        cs.digest_table(model.doc),
        model.edit_count,
        list(model.pending_edits),
        model.secure_save_required,
    )


@pytest.mark.parametrize("shared", [False, True], ids=["in-place", "copy"])
def test_every_nth_call_failure_leaves_the_document_as_it_was(tmp_path, shared):
    model = _build(tmp_path / "trace" if (tmp_path / "trace").mkdir() is None else tmp_path, shared)
    counter = _Counter(None)
    with pytest.MonkeyPatch.context() as mp:
        assert _commit(model, counter, mp) is not None
    total = counter.n
    assert total >= 3, counter.names
    seen_mutators = set(counter.names)
    assert any(n.endswith("update_stream") for n in seen_mutators)
    if shared:
        assert "xref_set_key_exact" in seen_mutators, "the copy path repoints /Contents natively"
    failures = []
    for n in range(1, total + 1):
        sub = tmp_path / f"n{n}"
        sub.mkdir()
        victim = _build(sub, shared)
        before = _state(victim)
        c = _Counter(n)
        with pytest.MonkeyPatch.context() as mp:
            result = _commit(victim, c, mp)
        label = c.names[n - 1] if len(c.names) >= n else "?"
        if result is not None:
            # the injected call was not on the commit's path in this run (e.g. only a rollback read)
            failures.append((n, label, "commit succeeded despite the fault")) if c.fired else None
            continue
        after = _state(victim)
        if after != before:
            failures.append((n, label, "state changed"))
        if victim.vector_editing_blocked is not None:
            failures.append((n, label, "latched"))
        if victim.last_object_op_refusal is None:
            failures.append((n, label, "no refusal recorded"))
    assert not failures, failures
