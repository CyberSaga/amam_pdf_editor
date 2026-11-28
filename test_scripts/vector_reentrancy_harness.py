"""Card B7, the class check (plans/b7-integration-design-astra.md section 1): a vector transaction that pumps events
at T0 / T1 must end exactly as if it had run alone, whatever entry the pump delivers.

Shared harness, not collected: the cases live in test_vector_reentrancy_<group>.py, one file per GROUPS key, so
each file runs in its own interpreter under scripts/run_suite.py (one file of all 13 entries took about 40 min).

A real window (main.run), two documents.  The transaction is driven the way the controller's delete flow will drive it
(write_transaction -> commit_vector_plan(lease) -> record); at the T0 and at the T1 yield one entry is delivered and the
invariants are checked right there, not only at the end: the active session, the document handle, the open tabs and the
window stay as they were, and OCR waits.  Red first.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main  # noqa: E402
from controller.session_transfer import SessionTransferPayload  # noqa: E402
from model.edit_commands import SnapshotCommand  # noqa: E402
from model.object_requests import VectorSelectionQuery  # noqa: E402
from model.vector_paths.edit import plan_delete  # noqa: E402
from model.vector_paths.scan import scan_page  # noqa: E402

BODY = b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f"
SPAN = SimpleNamespace(bbox=(20.0, 20.0, 120.0, 40.0), text="hello ocr", confidence=90.0)


def _make_pdf(path: Path, pages: int) -> str:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((5, 5), " ")
        doc.update_stream(page.get_contents()[0], BODY)
    doc.save(path)
    doc.close()
    return str(path)


def _pump(qapp, rounds: int = 30) -> None:
    for _ in range(rounds):
        qapp.processEvents()


ENTRIES = (
    "cli_open_existing",
    "tab_switch",
    "window_close",
    "undo",
    "ocr_delivery",
    "jump_to_result",
    "jump_to_result_sync_fallback",
    "index_batch",
    "index_batch_missing_page",
    "release_window",
    "redo",
    "ocr_worker_bridge",
    "second_window_adopt",
)


def _fire(entry: str, ctx: SimpleNamespace) -> None:
    c, view, model = ctx.controller, ctx.view, ctx.model
    if entry == "cli_open_existing":
        c.handle_forwarded_cli([ctx.path_b])
    elif entry == "tab_switch":
        view.document_tab_bar.setCurrentIndex(ctx.index_b)
    elif entry == "window_close":
        view.close()
    elif entry == "undo":
        view._action_undo.trigger()  # the real toolbar action -> sig_undo -> _live_only
    elif entry == "redo":
        view._action_redo.trigger()
    elif entry == "ocr_worker_bridge":  # the result arrives through the Qt bridge the worker thread signals into
        oc = c._ocr_coordinator
        oc._ocr_session_id = ctx.sid_a
        oc._ocr_sources = {2: model.ocr_source_key(2)}
        bridge = oc._ensure_ocr_bridge() if hasattr(oc, "_ensure_ocr_bridge") else oc._ocr_worker_bridge
        bridge.forward_page_done(oc._ocr_gen, 2, [SPAN])
    elif entry == "second_window_adopt":  # what the second window's hand-off calls on the receiving window
        c.adopt_transferred_session(ctx.payload)
    elif entry == "ocr_delivery":
        oc = c._ocr_coordinator
        oc._ocr_session_id = ctx.sid_a
        oc._ocr_sources = {2: model.ocr_source_key(2)}  # the proof taken from the snapshot when the run started
        oc._on_ocr_page_done(oc._ocr_gen, 2, [SPAN])
    elif entry == "index_batch":  # the timer-driven page-index build of the active document
        c._schedule_index_batch(0, ctx.sid_a, c._load_gen_by_session.get(ctx.sid_a))
    elif entry == "jump_to_result":
        c.jump_to_result(1, fitz.Rect(0, 0, 10, 10))
    elif entry == "jump_to_result_sync_fallback":  # no queued render available: the slot paints from the live document
        c._queue_single_page_render = lambda *a, **k: False
        view.continuous_pages = False
        c.jump_to_result(1, fitz.Rect(0, 0, 10, 10))
    elif entry == "index_batch_missing_page":  # a page whose index is gone: the timer would rebuild it from the live doc
        model.__dict__.get("_page_index_state", {}).clear() if hasattr(model, "_page_index_state") else None
        model.block_manager.mark_page_stale(0)
        c._schedule_index_batch(0, ctx.sid_a, c._load_gen_by_session.get(ctx.sid_a))
    elif entry == "release_window":  # the destroyed / promotion path reaches main._release_window directly
        view.closed.emit()
    else:  # pragma: no cover
        raise AssertionError(entry)
    ctx.qapp.processEvents()
    assert model is ctx.model


DEFERRED_ENTRIES = frozenset({"cli_open_existing", "ocr_delivery", "ocr_worker_bridge", "release_window"})
# the entries a transaction must run AFTER it (admitted in order); every other entry is refused or only reads published
# state, so the serial baseline for it is the transaction alone.
FAULTS = ("none", "yield", "capture", "record", "rebind")


def _tiny_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page(width=300, height=400).insert_text((20, 40), "adopted")
    data = doc.tobytes()
    doc.close()
    return data


def _outcome(ctx: SimpleNamespace, settle: bool) -> dict:
    """Everything that must be the same whether the entry ran inside the transaction or not."""
    model, view = ctx.model, ctx.view
    if settle:
        import time

        for _ in range(60):  # time.sleep, not QTest.qWait: qWait holds the GIL and starves the worker threads
            ctx.qapp.processEvents()
            time.sleep(0.01)
    import hashlib

    sessions = {}
    for sid in sorted(model.session_ids):
        s = model._sessions_by_id[sid]
        doc = s.doc
        stream = b"".join(doc.xref_stream(x) for x in doc[0].get_contents()) if len(doc) else b""
        ocr = doc[1].get_text().strip() if len(doc) > 1 else ""
        sessions[s.display_name] = (len(doc), hashlib.sha256(stream).hexdigest(), ocr)
    cm = model.command_manager
    return {
        "sessions": sessions,
        "visible": view.isVisible(),
        "released": bool(getattr(ctx.controller, "_window_context_released", False)),
        "gate_free": not model.write_gate.active,
        "undo": [c.description for c in cm._undo_stack],
        "redo": [c.description for c in cm._redo_stack],
    }


def _run_transaction(qapp, monkeypatch, tmp_path, entry, phase, *, fault="none", fire_after=False):
    """Drive one vector delete the way the controller's flow will, delivering ENTRY at the T0 / T1 pump (or, with
    fire_after, after the transaction as the serial baseline), with FAULT injected at one publish step.  Returns the
    outcome dict and the failures seen at the pump."""
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    path_a = _make_pdf(tmp_path / "a.pdf", 3)
    path_b = _make_pdf(tmp_path / "b.pdf", 2)
    path_c = tmp_path / "c.pdf"
    path_c.write_bytes(_tiny_pdf_bytes())
    startup = main.run(argv=[path_a, path_b], start_event_loop=False)
    controller, view, model = startup["controller"], startup["view"], startup["model"]
    try:
        _pump(qapp)
        sid_a, sid_b = model.find_session_by_path(path_a), model.find_session_by_path(path_b)
        assert sid_a and sid_b and sid_a != sid_b
        controller._switch_to_session_id(sid_a)
        _pump(qapp)
        assert model.get_active_session_id() == sid_a
        # history before the delete: one record that stays, one that was undone (so a Redo has something to take)
        base = model._capture_doc_snapshot()
        model.command_manager.record(SnapshotCommand(model, "prior_kept", [0], base, base, "prior_kept"))
        model.command_manager.record(SnapshotCommand(model, "prior_undone", [0], base, base, "prior_undone"))
        model.command_manager.undo()
        undo0, redo0 = model.command_manager.undo_count, model.command_manager.redo_count
        assert (undo0, redo0) == (1, 1)
        streams, frame = model.vector_page_source(1)
        model.install_vector_index(1, scan_page(list(streams), frame))
        info = model.vector_select(VectorSelectionQuery(1, (170.0, 220.0, 170.0, 220.0), 1.0, "click", "replace"))
        assert info is not None and info.count == 1
        index, mask, srcs = model.vector_plan_inputs(info.token)
        plan = plan_delete(index, mask, srcs)
        ctx = SimpleNamespace(
            controller=controller, view=view, model=model, qapp=qapp, path_b=path_b, sid_a=sid_a, index_b=1,
            payload=SessionTransferPayload(
                snapshot_bytes=path_c.read_bytes(), source_path=str(path_c), saved_path=None, display_name="c.pdf",
                dirty=False, current_page=0, scale=1.0, color_profile="sRGB",
            ),
        )
        doc_a = model.doc
        failures: list[str] = []
        finals = [0]
        reads: list[str] = []
        firing = [False]

        def spy(name: str):
            real = getattr(model, name)

            def wrapper(*a, **k):
                if firing[0]:
                    import traceback

                    reads.append(name + " <- " + " < ".join(f.name for f in traceback.extract_stack()[-7:-1]))
                return real(*a, **k)

            monkeypatch.setattr(model, name, wrapper)

        for name in ("get_page_pixmap", "rebuild_page", "ensure_page_index_built"):
            if hasattr(model, name):
                spy(name)
        side_effects: list[str] = []
        for name in ("retire_background", "release_render_owner"):  # a window release does these before it closes the model
            real_method = getattr(controller, name)

            def effect(*a, _n=name, _r=real_method, **k):
                if firing[0]:
                    side_effects.append(_n)
                return _r(*a, **k)

            monkeypatch.setattr(controller, name, effect)

        def invariants() -> None:
            if side_effects:
                failures.append(f"the window was torn down before it could be closed: {side_effects}")
            if reads:
                failures.append(f"the unpublished document was read inside the transaction: {sorted(set(reads))}")
            if model.get_active_session_id() != sid_a:
                failures.append("the active session changed inside the transaction")
            if model.doc is not doc_a:
                failures.append("the document handle changed inside the transaction")
            if sid_b not in model.session_ids or sid_a not in model.session_ids or len(model.session_ids) != 2:
                failures.append("a session was closed or added inside the transaction")
            if not view.isVisible():
                failures.append("the window was closed inside the transaction")
            if getattr(controller, "_window_context_released", False):
                failures.append("the window context was released inside the transaction")
            if not model.write_gate.active:
                failures.append("the lease was dropped inside the transaction")
            if model.doc[1].get_text().strip():
                failures.append("OCR text reached the document inside the transaction")
            cm = model.command_manager
            if (cm.undo_count, cm.redo_count) != (undo0, redo0):
                failures.append(f"history moved inside the transaction: {(cm.undo_count, cm.redo_count)}")

        def deliver() -> None:
            try:
                firing[0] = True
                _fire(entry, ctx)
                firing[0] = False
                invariants()
            except Exception as exc:  # noqa: BLE001 - commit_delete turns a raise into a refusal; keep the evidence
                failures.append(f"{type(exc).__name__}: {exc}")

        def on_yield(done: int, total: int) -> None:
            if done != total:
                return
            finals[0] += 1
            at = 1 if phase == "T0" else 2
            if entry and not fire_after and finals[0] == at:
                deliver()
            if fault == "yield" and finals[0] == 2:
                raise RuntimeError("injected at the T1 yield")

        class Injected(RuntimeError):
            pass

        model.vector_last_pass_ms = 1000.0  # the slow path: the pump runs at T0 and at T1
        snap = model._capture_doc_snapshot()
        captures = [0]
        real_capture = model._capture_doc_snapshot
        if fault == "capture":

            def capture_then_fail():
                captures[0] += 1
                if captures[0] >= 1 and model.write_gate.active and finals[0] >= 2:
                    raise Injected("capture failed")
                return real_capture()

            monkeypatch.setattr(model, "_capture_doc_snapshot", capture_then_fail)
        if fault == "record":
            real_record = model.command_manager.record

            def record_then_fail(cmd, lease=None):
                real_record(cmd, lease)  # the record happens, then the step after it fails
                raise Injected("failed after the record")

            monkeypatch.setattr(model.command_manager, "record", record_then_fail)
        if fault == "rebind":
            real_install = model.install_vector_index
            holder: list = []

            def install_then_fail(*a, **k):
                if holder and holder[0].published:
                    raise Injected("rebind failed")
                return real_install(*a, **k)

            monkeypatch.setattr(model, "install_vector_index", install_then_fail)
        raised: BaseException | None = None
        result = None
        try:
            with model.write_transaction("vector_delete") as lease:
                holder = [lease] if fault == "rebind" else []
                if fault == "rebind":
                    holder[:] = [lease]
                result = model.commit_vector_plan(plan, info.token, on_yield=on_yield, lease=lease)
                if result is not None:
                    after = model._capture_doc_snapshot()
                    model.command_manager.record(SnapshotCommand(model, "vector_delete", [1], snap, after, "x"), lease=lease)
        except Injected as exc:
            raised = exc
        if fault == "none":
            assert raised is None and result is not None, model.last_object_op_refusal
        elif fault == "yield":
            assert raised is None and result is None  # commit_delete turned the raise into a refusal and undid itself
        else:
            assert isinstance(raised, Injected)
        stream = b"".join(model.doc.xref_stream(x) for x in model.doc[0].get_contents())  # before any later entry runs
        deleted, kept = b"150 160 40 40 re f" not in stream, b"20 370 m 120 370 l S" in stream
        if fire_after and entry:
            _fire(entry, ctx)
        out = _outcome(ctx, settle=True)
        out["deleted"], out["kept"] = deleted, kept
        out["pristine"] = (not deleted) and kept  # the delete is not there; the rollback restored the page
        return out, failures
    finally:
        for sid in list(model.session_ids):  # leave nothing dirty so closing the window asks no question
            model.activate_session(sid)
            model.command_manager.mark_saved()
            model.edit_count = 0
            model.secure_save_required = False
        if view.isVisible():
            view.close()
        _pump(qapp)
        qapp.setStyleSheet("")


GROUPS = {
    "cli_tab": ("cli_open_existing", "tab_switch"),
    "close_release": ("window_close", "release_window"),
    "undo_redo": ("undo", "redo"),
    "ocr": ("ocr_delivery", "ocr_worker_bridge"),
    "search": ("jump_to_result", "jump_to_result_sync_fallback"),
    "index": ("index_batch", "index_batch_missing_page"),
    "handoff": ("second_window_adopt",),
}
assert sorted(e for group in GROUPS.values() for e in group) == sorted(ENTRIES)

_SERIAL: dict[tuple, dict] = {}  # serial baselines of this process; one run serves every case with the same key


def _serial(qapp, monkeypatch, tmp_path, entry, phase, fault):
    """The serial run: the transaction alone, then the entry only if it is admitted after the transaction (a refused
    or read-only entry leaves no trace, so its baseline is the transaction alone and is shared)."""
    deferred = entry in DEFERRED_ENTRIES
    key = (entry if deferred else None, phase if deferred else None, fault)
    if key not in _SERIAL:
        (tmp_path / "se").mkdir()
        _SERIAL[key], _ = _run_transaction(
            qapp, monkeypatch, tmp_path / "se", entry if deferred else None, phase, fault=fault, fire_after=deferred,
        )
    return _SERIAL[key]


def check_serial(qapp, monkeypatch, tmp_path, entry, phase) -> None:
    """ENTRY delivered at the T0 / T1 pump: no invariant broke there, and the end state equals the serial run."""
    (tmp_path / "re").mkdir()
    reentrant, failures = _run_transaction(qapp, monkeypatch, tmp_path / "re", entry, phase)
    assert failures == []
    assert reentrant == _serial(qapp, monkeypatch, tmp_path, entry, phase, "none")


def check_fault(qapp, monkeypatch, tmp_path, entry, fault) -> None:
    """Fault injected at one publish step while ENTRY was delivered at T1: the document, the history, the sessions and
    the lease end exactly as in the serial run that fails at the same step."""
    (tmp_path / "re").mkdir()
    reentrant, failures = _run_transaction(qapp, monkeypatch, tmp_path / "re", entry, "T1", fault=fault)
    assert failures == []
    assert reentrant["pristine"] and reentrant["gate_free"]
    assert reentrant == _serial(qapp, monkeypatch, tmp_path, entry, "T1", fault)
