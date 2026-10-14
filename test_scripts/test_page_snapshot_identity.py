"""Page-snapshot restore keeps the page's object identity (model level, no Qt).

Owner report (2026-10-07, part 5 round 5): after a consented rebuild
(改用重建文字…) followed by Ctrl+Z, every later true-text edit on the page was
refused ``mc_wrapper_not_pure_layer``.  Cause: the page-snapshot restore grafted
copies of the page's objects with ``insert_pdf`` (a new page object, duplicated
OCGs that ``/OCProperties`` does not list), so all marked-content wrappers
classified ``props_unresolved``.  The restore is now an IN-PLACE write by xref
(``model.page_snapshot``); when the xref numbering moved (a renumbering save)
it refuses with zero mutation instead of grafting.

No fixtures, no Qt: a layered PDF is built in ``tmp_path``.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import test_text_commit_no_silent_legacy as nsl  # noqa: E402

from model.pdf_model import PDFModel  # noqa: E402
from model.edit_commands import (  # noqa: E402
    AddTextboxCommand,
    EditTextCommand,
    EditTextResult,
    SnapshotCommand,
)
from model.page_snapshot import (  # noqa: E402
    PageSnapshot,
    PageSnapshotStale,
    capture_page_graph,
    restore_page_graph,
)
from model.text_commit.dto import is_real_fallback_commit  # noqa: E402
from model.text_commit.inspect import page_fingerprint, replay_page  # noqa: E402
from model.text_commit.marked_content import (  # noqa: E402
    classify_wrappers,
    resolve_default_visibility,
    resolve_properties_mapping,
)

_LAYER_CLASS = "oc_layer_visible_default"
_JUNK_OBJECTS = 5


# ---------------------------------------------------------------- fixtures


def _layered_pdf(path: Path, *, junk: int = 0) -> Path:
    doc = fitz.open()
    for _ in range(junk):  # unreferenced objects ahead of the page: garbage=4 renumbers
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Junk 1 >>")
    ocg = doc.add_ocg("Layer A", on=True)
    stream = b"/OC /oc1 BDC BT /F1 12 Tf 72 700 Td [(Price) ( 2024)] TJ ET EMC"
    page = nsl._add_raw_page(doc, stream)
    resources = doc.xref_get_key(page.xref, "Resources")[1].strip()
    doc.xref_set_key(
        page.xref,
        "Resources",
        resources[:-2] + f" /Properties << /oc1 {ocg} 0 R >> >>",
    )
    page.add_text_annot((400, 100), "note")
    doc.xref_set_key(page.xref, "StructParents", "0")
    doc.xref_set_key(page.xref, "VP", "[<</Type/Viewport/BBox[0 0 595 842]>>]")
    doc.new_page()
    doc.set_toc([[1, "First", 1], [1, "Second", 2]])
    doc.save(str(path), garbage=0)
    doc.close()
    return path


def _state(model) -> dict:
    doc = model.doc
    page = doc[0]
    mapping = resolve_properties_mapping(doc, page) or {}
    visibility = resolve_default_visibility(doc)
    mapping_xrefs = {name: getattr(ref, "xref", None) for name, ref in mapping.items()}
    contents = list(page.get_contents())
    return {
        "page_xref": page.xref,
        "contents": contents,
        "streams": [doc.xref_stream_raw(x) for x in contents],
        "page_obj": doc.xref_object(page.xref),
        "annots": sorted(a.xref for a in page.annots() or []),
        "properties": mapping_xrefs,
        "listed": {name: x in visibility for name, x in mapping_xrefs.items()},
        "classes": Counter(classify_wrappers(doc, page, replay_page(doc, page)).values()),
        "struct_parents": doc.xref_get_key(page.xref, "StructParents")[1],
        "vp_kind": doc.xref_get_key(page.xref, "VP")[0],
        "toc": [row[2] for row in doc.get_toc()],
        "fingerprint": page_fingerprint(doc, page),
    }


def _open(path: Path):
    return nsl._open_model(path)


def _rebuild_cmd(model) -> EditTextCommand:
    block = nsl._block(model, nsl.TARGET)
    return EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=nsl.REPLACEMENT,
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
        confirm_fallback=lambda c: True,
        allow_rebuild=True,
    )


def _do_rebuild(model) -> EditTextCommand:
    cmd = _rebuild_cmd(model)
    model.command_manager.execute(cmd)
    assert cmd.result is EditTextResult.SUCCESS
    assert is_real_fallback_commit(cmd.outcome), "the fixture must go through the legacy rebuild"
    return cmd


def _textbox_cmd(model) -> AddTextboxCommand:
    return AddTextboxCommand(
        model=model,
        page_num=1,
        visual_rect=fitz.Rect(100, 100, 300, 160),
        text="Hello box",
        font="helv",
        size=12.0,
        color=(0.0, 0.0, 0.0),
        before_page_snapshot_bytes=model._capture_page_snapshot_strict(0),
    )


def _assert_state_equal(got: dict, want: dict, *, ignore: tuple[str, ...] = ()) -> None:
    for key in want:
        if key in ignore:
            continue
        assert got[key] == want[key], f"state key {key!r} differs: {got[key]!r} != {want[key]!r}"


def _record_doc_snapshot_cmd(model, label: str, mutate) -> None:
    """Apply ``mutate`` as a whole-document ``SnapshotCommand`` (garbage=0 snapshots)."""
    before = model._capture_doc_snapshot()
    mutate(model)
    after = model._capture_doc_snapshot()
    model.command_manager.record(
        SnapshotCommand(
            model=model,
            command_type=label,
            affected_pages=[1],
            before_bytes=before,
            after_bytes=after,
            description=label,
        )
    )


@pytest.fixture
def layered(tmp_path):
    model = _open(_layered_pdf(tmp_path / "layered.pdf"))
    try:
        yield model
    finally:
        model.close()


# ---------------------------------------------------------------- red tests: identity


def test_undone_rebuild_keeps_page_layer_and_annotation_identity(layered) -> None:
    model = layered
    pristine = _state(model)
    assert pristine["classes"] == {_LAYER_CLASS: 1}
    assert all(pristine["listed"].values()) and pristine["listed"]
    _do_rebuild(model)
    assert model.command_manager.undo() is True
    after = _state(model)
    _assert_state_equal(after, pristine)
    assert after["page_xref"] == pristine["page_xref"]
    assert after["classes"] == {_LAYER_CLASS: 1}
    assert after["struct_parents"] == "0" and after["vp_kind"] == "array"
    assert after["toc"] == [1, 2]


def test_rebuild_redo_undo_cycles_are_exact_and_bounded(layered) -> None:
    model = layered
    pristine = _state(model)
    _do_rebuild(model)
    rebuilt = _state(model)
    xl = model.doc.xref_length()
    for _cycle in range(2):
        assert model.command_manager.undo() is True
        _assert_state_equal(_state(model), pristine)
        assert model.doc.xref_length() == xl
        assert model.command_manager.redo() is True
        _assert_state_equal(_state(model), rebuilt)
        assert model.doc.xref_length() == xl
    assert model.command_manager.undo() is True
    _assert_state_equal(_state(model), pristine)
    assert model.doc.xref_length() == xl


def test_undone_rebuild_survives_save_and_reopen(tmp_path) -> None:
    undone = _open(_layered_pdf(tmp_path / "a.pdf"))
    fresh = _open(_layered_pdf(tmp_path / "b.pdf"))
    try:
        _do_rebuild(undone)
        assert undone.command_manager.undo() is True
        undone.save_as(str(tmp_path / "undone_saved.pdf"))
        fresh.save_as(str(tmp_path / "fresh_saved.pdf"))
    finally:
        undone.close()
        fresh.close()

    def saved(path: Path) -> dict:
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            mapping = resolve_properties_mapping(doc, page) or {}
            visibility = resolve_default_visibility(doc)
            return {
                "classes": Counter(classify_wrappers(doc, page, replay_page(doc, page)).values()),
                "listed": {
                    n: getattr(r, "xref", None) in visibility for n, r in mapping.items()
                },
                "struct_parents": doc.xref_get_key(page.xref, "StructParents")[1],
                "vp_kind": doc.xref_get_key(page.xref, "VP")[0],
                "toc": [row[2] for row in doc.get_toc()],
                "annots": len(list(page.annots() or [])),
            }
        finally:
            doc.close()

    got = saved(tmp_path / "undone_saved.pdf")
    want = saved(tmp_path / "fresh_saved.pdf")
    assert want["classes"] == {_LAYER_CLASS: 1}
    assert got == want


def test_failed_legacy_edit_rollback_keeps_identity(layered, monkeypatch) -> None:
    model = layered
    pristine = _state(model)
    xl = model.doc.xref_length()
    monkeypatch.setattr(model, "_validate_protected_spans", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="overlap edit verification failed"):
        model.command_manager.execute(_rebuild_cmd(model))
    assert model.command_manager.undo_count == 0
    _assert_state_equal(_state(model), pristine)
    assert model.doc.xref_length() >= xl


def test_add_textbox_undo_redo_keeps_identity(layered) -> None:
    model = layered
    pristine = _state(model)
    cmd = _textbox_cmd(model)
    model.command_manager.execute(cmd)
    added = _state(model)
    assert added["annots"] != pristine["annots"] or added["streams"] != pristine["streams"]
    xl = model.doc.xref_length()
    assert model.command_manager.undo() is True
    _assert_state_equal(_state(model), pristine)
    assert model.command_manager.redo() is True
    _assert_state_equal(_state(model), added)
    assert model.command_manager.undo() is True
    _assert_state_equal(_state(model), pristine)
    assert model.doc.xref_length() == xl


def test_strict_capture_never_mutates_live_annotations(layered) -> None:
    """Guard: the old insert_pdf capture rewrote the live annotations' /P."""
    model = layered
    annots = [a.xref for a in model.doc[0].annots() or []]
    assert annots
    before = {x: model.doc.xref_object(x) for x in annots}
    model._capture_page_snapshot_strict(0)
    assert {x: model.doc.xref_object(x) for x in annots} == before


def test_restore_resurrects_objects_freed_by_an_in_memory_repair(layered) -> None:
    model = layered
    _do_rebuild(model)
    rebuilt = _state(model)
    pristine_page_xref = rebuilt["page_xref"]
    epoch = model.xref_epoch
    assert model.command_manager.undo() is True
    assert model._repair_active_doc_in_memory(garbage=1)
    assert model.xref_epoch == epoch
    assert model.command_manager.redo() is True
    _assert_state_equal(_state(model), rebuilt)
    assert _state(model)["page_xref"] == pristine_page_xref
    assert model.xref_epoch == epoch


# ---------------------------------------------------------------- new API / contract


@pytest.mark.parametrize("kind", ["textbox", "rebuild"])
def test_page_restore_refuses_after_a_renumbering_save(tmp_path, kind) -> None:
    model = _open(_layered_pdf(tmp_path / "renum.pdf", junk=_JUNK_OBJECTS))
    try:
        if kind == "textbox":
            cmd = _textbox_cmd(model)
            model.command_manager.execute(cmd)
        else:
            cmd = _do_rebuild(model)
        page_xref = model.doc[0].xref
        model.secure_save_required = True
        model.save_as(str(tmp_path / "copy.pdf"))
        assert model.doc[0].xref != page_xref, "the fixture must really renumber"
        undo_count = model.command_manager.undo_count
        streams = _state(model)["streams"]
        page_obj = model.doc.xref_object(model.doc[0].xref)
        assert model.command_manager.undo() is False
        assert model.command_manager.undo_count == undo_count
        assert _state(model)["streams"] == streams
        assert model.doc.xref_object(model.doc[0].xref) == page_obj
        if kind == "rebuild":
            assert cmd.result is EditTextResult.STALE_UNDO
    finally:
        model.close()


def test_doc_snapshot_restore_reinstates_the_xref_epoch(tmp_path) -> None:
    model = _open(_layered_pdf(tmp_path / "epoch.pdf", junk=_JUNK_OBJECTS))
    try:
        pristine = _state(model)
        _do_rebuild(model)
        epoch_a = model.xref_epoch
        page_xref_a = model.doc[0].xref
        _record_doc_snapshot_cmd(model, "rotate_pages", lambda m: m.doc[0].set_rotation(90))
        model.secure_save_required = True
        model.save_as(str(tmp_path / "renumbered.pdf"))
        assert model.xref_epoch != epoch_a
        assert model.command_manager.undo() is True  # the SnapshotCommand
        assert model.xref_epoch == epoch_a
        assert model.command_manager.undo() is True  # the rebuild, in place
        assert model.doc[0].xref == page_xref_a
        _assert_state_equal(_state(model), pristine, ignore=("page_xref",))
        assert _state(model)["classes"] == {_LAYER_CLASS: 1}
    finally:
        model.close()


@pytest.mark.parametrize("how", ["save_as", "roundtrip"])
def test_live_garbage_serializations_bump_the_xref_epoch(tmp_path, how) -> None:
    model = _open(_layered_pdf(tmp_path / f"{how}.pdf", junk=_JUNK_OBJECTS))
    try:
        epoch = model.xref_epoch
        if how == "save_as":
            model.secure_save_required = True
            model.save_as(str(tmp_path / "out.pdf"))
        else:
            model._roundtrip_live_doc(garbage=4, deflate=True)
        assert model.xref_epoch != epoch
    finally:
        model.close()


@pytest.mark.parametrize(
    "how",
    [
        "doc_snapshot",
        "worker_bytes",
        "full_save_over_open",
        "incremental",
        "repair",
        "print_bytes",
        "print_snapshot",
    ],
)
def test_numbering_preserving_paths_keep_the_xref_epoch(tmp_path, how) -> None:
    path = _layered_pdf(tmp_path / "keep.pdf", junk=_JUNK_OBJECTS)
    model = _open(path)
    try:
        epoch = model.xref_epoch
        if how == "doc_snapshot":
            model._capture_doc_snapshot()
        elif how == "worker_bytes":
            model.capture_worker_snapshot_bytes()
        elif how == "full_save_over_open":
            model.use_incremental_save = False
            model.save_as(str(path))
        elif how == "incremental":
            model.use_incremental_save = True
            model.doc[0].add_text_annot((300, 300), "x")
            model.save_as(str(path))
        elif how == "print_bytes":
            # A print is a read-only serialization: the garbage=4 prune runs on
            # a throwaway clone, never on the live handle (DS-1).
            model.secure_save_required = True
            model.capture_print_snapshot_bytes()
        elif how == "print_snapshot":
            model.secure_save_required = True
            model.tools.build_print_snapshot(path.parent / "print.pdf")
        else:
            assert model._repair_active_doc_in_memory(garbage=1)
        assert model.xref_epoch == epoch
    finally:
        model.close()


def test_restore_rejects_plain_bytes(layered) -> None:
    with pytest.raises(TypeError):
        layered._restore_page_from_snapshot(0, b"%PDF-fake")


@pytest.mark.parametrize(("failing", "fail_at"), [("update_object", 2), ("update_stream", 1)])
def test_failed_write_mid_restore_puts_the_page_back(layered, monkeypatch, failing, fail_at) -> None:
    """A write failing part-way through a restore leaves the page exactly as it
    was.  The rebuilt page's content streams are dirtied after the undo so the
    redo has several objects to write (a clean one is skipped)."""
    model = layered
    _do_rebuild(model)
    rebuilt_contents = list(_state(model)["contents"])
    assert model.command_manager.undo() is True
    for xref in rebuilt_contents:
        if model.doc.xref_is_stream(xref):
            model.doc.update_stream(xref, b"% dirtied")
    before = _state(model)
    calls = {"n": 0}
    real = getattr(fitz.Document, failing)

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise RuntimeError("boom")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, failing, flaky)
    with pytest.raises(RuntimeError, match="page put back"):
        model.command_manager.redo()
    monkeypatch.setattr(fitz.Document, failing, real)
    assert calls["n"] >= fail_at, "the redo must reach the failing write"
    _assert_state_equal(_state(model), before)
    assert model.command_manager.redo_count == 1


def test_page_snapshot_payload_counts_for_the_undo_budget(layered) -> None:
    model = layered
    snap = model._capture_page_snapshot(0)
    again = model._capture_page_snapshot(0)
    assert isinstance(snap, PageSnapshot) and isinstance(snap, bytes)
    assert snap == again, "an unchanged page must dedup by content"
    raw_total = sum(len(raw) for _x, _o, raw in snap.records() if raw is not None)
    assert raw_total > 0 and len(snap) >= raw_total
    assert snap.page_xref == model.doc[0].xref
    assert snap.xref_epoch == model.xref_epoch
    assert snap.records()[0][0] == snap.page_xref


def test_stale_gate_raises_before_any_write(layered) -> None:
    model = layered
    snap = model._capture_page_snapshot(0)
    streams = _state(model)["streams"]
    model._bump_xref_epoch()
    with pytest.raises(PageSnapshotStale):
        model._restore_page_from_snapshot(0, snap)
    assert _state(model)["streams"] == streams


# ------------------------------------------- redo chains across a whole-doc command


def _highlight(model) -> None:
    model.doc[0].add_highlight_annot(fitz.Rect(72, 690, 150, 705))


def _rotate_page_two(model) -> None:
    model.doc[1].set_rotation(90)


@pytest.mark.parametrize("later", ["rebuild", "textbox"])
@pytest.mark.parametrize("earlier", [_highlight, _rotate_page_two], ids=["highlight", "rotate"])
def test_redo_chain_across_a_doc_snapshot_command_keeps_identity(tmp_path, earlier, later) -> None:
    """[SnapshotCommand] -> [rebuild | textbox] -> undo, undo, redo, redo.

    Redoing the whole-doc command reopens the doc from garbage=0 bytes taken
    BEFORE the later command existed, so the xref table shrinks below the
    xrefs the later command allocated; its redo must still restore in place."""
    model = _open(_layered_pdf(tmp_path / "chain.pdf"))
    try:
        cm = model.command_manager
        _record_doc_snapshot_cmd(model, earlier.__name__, earlier)
        if later == "rebuild":
            _do_rebuild(model)
        else:
            cm.execute(_textbox_cmd(model))
        after_state = _state(model)
        assert cm.undo() is True
        assert cm.undo() is True
        assert cm.redo() is True
        assert cm.redo() is True, "redo of the later command must not be refused"
        assert cm.redo_count == 0
        _assert_state_equal(_state(model), after_state)
        # A further undo/redo round trip still works.
        assert cm.undo() is True
        assert cm.redo() is True
        _assert_state_equal(_state(model), after_state)
    finally:
        model.close()


def test_restore_grows_the_xref_table_for_records_beyond_it(layered) -> None:
    """Records beyond the live table are treated as free slots: the table grows
    and the objects are written in place (zero-mutation refusal is only for
    genuinely foreign numbering)."""
    model = layered
    doc = model.doc
    snap = model._capture_page_snapshot(0)
    records = list(snap.records())
    top = doc.xref_length() + 3
    extra = (top, "<< /Marker 7 >>", None)
    snap2 = PageSnapshot.build(snap.page_xref, snap.xref_epoch, records + [extra])
    model._restore_page_from_snapshot(0, snap2)
    assert doc.xref_length() > top
    assert doc.xref_get_key(top, "Marker") == ("int", "7")


def _annotated_page_doc() -> fitz.Document:
    """One page with a Highlight, a FreeText and a URI link (memory-backed)."""
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 100), "Hello World", fontsize=12)
    page.add_highlight_annot(fitz.Rect(70, 88, 140, 104)).update()
    page.add_freetext_annot(fitz.Rect(100, 80, 200, 110), "FT original").update()
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 88, 100, 104), "uri": "https://example.com/a"})
    data = src.tobytes()
    src.close()
    return fitz.open("pdf", data)


def _annot_view(page: fitz.Page) -> tuple[list[tuple[int, str]], list[str]]:
    annots = sorted((a.xref, a.info.get("content", "")) for a in page.annots())
    links = [link.get("uri") for link in page.get_links()]
    return annots, links


def test_restore_refreshes_the_annotation_and_link_lists_of_a_page_still_loaded() -> None:
    """F11-ANN-2: a ``fitz.Page`` alive across the restore (cycle garbage, a
    traceback a log handler keeps, any caller's reference) is the SAME MuPDF
    page every later ``doc[n]`` returns, so its annotation / link lists must
    be rebuilt from the restored ``/Annots`` -- otherwise ``load_annot`` of a
    restored annotation raises "xref N is not an annot of this page" (the
    page fingerprint, the annotation panel and every later edit on the page)
    and ``get_links`` misses the restored link.  ``held`` stands in for any
    such live reference."""
    doc = _annotated_page_doc()
    try:
        want = _annot_view(doc[0])
        snap = capture_page_graph(doc, 0, xref_epoch=0)
        held = doc[0]
        freetext = next(a for a in held.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT)
        held.delete_annot(freetext)
        freetext = None
        held.delete_link(held.get_links()[0])
        held.add_freetext_annot(fitz.Rect(100, 80, 200, 110), "FT replaced").update()
        assert _annot_view(held) != want

        restore_page_graph(doc, 0, snap, xref_epoch=0)

        page = doc[0]
        for xref, type_code, _name in page.annot_xrefs():
            if type_code != fitz.PDF_ANNOT_LINK:  # links are not loadable annots
                page.load_annot(xref)  # raised for the restored FreeText
        assert _annot_view(page) == want
        assert _annot_view(held) == want
    finally:
        held = None
        doc.close()


def test_merge_style_plain_after_bytes_keep_redo_chain(tmp_path) -> None:
    """The controller's merge records a SnapshotCommand whose after state is
    plain garbage=0 bytes.  The command must stamp the live epoch on them so a
    page-snapshot command stacked above the merge can still be redone."""
    import io

    model = _open(_layered_pdf(tmp_path / "merge.pdf"))
    try:
        cm = model.command_manager
        before = model._capture_doc_snapshot()
        merged = fitz.open("pdf", model.doc.tobytes(garbage=0))
        merged.new_page()
        stream = io.BytesIO()
        merged.save(stream, garbage=0)
        after = stream.getvalue()
        merged.close()
        model.replace_active_document_from_snapshot(after, [1])
        cm.record(
            SnapshotCommand(
                model=model,
                command_type="merge_pdfs",
                affected_pages=[1],
                before_bytes=before,
                after_bytes=after,
                description="merge",
            )
        )
        model.ensure_page_index_built(1)
        cm.execute(_textbox_cmd(model))
        after_state = _state(model)
        assert cm.undo() is True
        assert cm.undo() is True
        assert cm.redo() is True
        assert cm.redo() is True, "redo of the textbox above a merge must not be refused"
        _assert_state_equal(_state(model), after_state)
    finally:
        model.close()


# ------------------------------------------- DS-1: a print must not renumber the live doc


def _open_secure_junk(tmp_path: Path):
    model = PDFModel()
    model.open_pdf(str(_layered_pdf(tmp_path / "print.pdf", junk=_JUNK_OBJECTS)))
    model.ensure_page_index_built(1)
    model.secure_save_required = True  # what a TOC / metadata / page-structure edit latches
    return model


def _print_how(model, how: str, tmp_path: Path) -> bytes:
    if how == "bytes":
        return model.capture_print_snapshot_bytes()
    dest = tmp_path / "print_out.pdf"
    model.tools.build_print_snapshot(dest)
    return dest.read_bytes()


@pytest.mark.parametrize("how", ["bytes", "file"])
def test_print_in_secure_session_keeps_textbox_undo_and_redo(tmp_path, how) -> None:
    model = _open_secure_junk(tmp_path)
    try:
        before = _state(model)
        cmd = _textbox_cmd(model)
        model.command_manager.execute(cmd)
        assert "Hello box" in model.doc[0].get_text()
        _print_how(model, how, tmp_path)
        assert model.command_manager.undo() is True
        assert "Hello box" not in model.doc[0].get_text()
        _assert_state_equal(_state(model), before)
        assert model.command_manager.redo() is True
        assert "Hello box" in model.doc[0].get_text()
    finally:
        model.close()


@pytest.mark.parametrize("how", ["bytes", "file"])
def test_print_in_secure_session_keeps_live_numbering_and_still_prunes(tmp_path, how) -> None:
    model = _open_secure_junk(tmp_path)
    try:
        length = model.doc.xref_length()
        annots = sorted(a.xref for a in model.doc[0].annots())
        out = _print_how(model, how, tmp_path)
        assert model.doc.xref_length() == length, "the live document was renumbered"
        assert sorted(a.xref for a in model.doc[0].annots()) == annots
        printed = fitz.open("pdf", out)
        try:
            assert printed.xref_length() < length, "the print copy must still take the garbage=4 prune"
            assert printed.page_count == model.doc.page_count
        finally:
            printed.close()
    finally:
        model.close()


@pytest.mark.parametrize("how", ["bytes", "file"])
def test_print_of_encrypted_secure_session_keeps_numbering_and_decrypts(tmp_path, how) -> None:
    plain = _layered_pdf(tmp_path / "plain.pdf", junk=_JUNK_OBJECTS)
    src = fitz.open(str(plain))
    enc = tmp_path / "enc.pdf"
    src.save(
        str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="pw", user_pw="pw", permissions=-1
    )
    src.close()
    model = PDFModel()
    model.open_pdf(str(enc), password="pw")
    model.secure_save_required = True
    try:
        length = model.doc.xref_length()
        epoch = model.xref_epoch
        out = _print_how(model, how, tmp_path)
        assert model.xref_epoch == epoch
        assert model.doc.xref_length() == length
        assert "Price" in model.doc[0].get_text()  # live handle still unlocked
        if how == "bytes":  # the byte route hands over DECRYPTED input
            printed = fitz.open("pdf", out)
            try:
                assert not printed.needs_pass
                assert "Price" in printed[0].get_text()
            finally:
                printed.close()
        else:  # the file route keeps the source encryption (PDF_ENCRYPT_KEEP)
            printed = fitz.open(str(tmp_path / "print_out.pdf"))
            try:
                assert printed.needs_pass
                assert printed.authenticate("pw")
                assert "Price" in printed[0].get_text()
            finally:
                printed.close()
        # the live handle can still be saved afterwards with the password kept
        model.save_as(str(tmp_path / "after.pdf"))
        reopened = fitz.open(str(tmp_path / "after.pdf"))
        try:
            assert reopened.needs_pass
        finally:
            reopened.close()
    finally:
        model.close()
