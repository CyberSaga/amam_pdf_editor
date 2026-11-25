"""Drain traps (owner decision 11-25, option d): while the quit gate drains (admission closed), no GUI
handler may open a modal dialog and no GUI handler may join a worker synchronously.

Round 10 of the quit-gate review (plans/cad-m0-h23-review.md) named four sites that still do; the owner
accepted them and asked for the check anyway.  So the traps run GREEN against a pinned allowlist of exactly
those sites: a NEW site fails, a STALE entry (an allowlisted site that no longer triggers) fails, and there
is no xfail.  When one of the four is fixed, delete its entry; the stale check tells you to.

Two traps:
  * modal trap: every `show_error` binding, `QMessageBox` modal entry and `QDialog.exec` records its caller;
  * blocking trap: the coordinators' `wait_for_done` (the synchronous GUI joins) record their caller.
Each drain-reachable handler in HANDLERS is driven with admission closed.  A control run with admission open
must trigger the modal traps of the modal handlers (a trap that cannot see anything proves nothing).  A
structural check keeps HANDLERS complete: a controller function named `_on_*_failed|succeeded|error` that
opens a modal must be in the table.

Not covered here (still open, plans/cad-m0-h23-review.md Round 10): launch-time fault injection at every
start_owned / start_owned_child site (round-10 P1s 1 and 2).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from controller.worker_registry import get_registry

REPO_ROOT = Path(__file__).resolve().parents[1]

# (trap, file, qualified function).  Round-10 P1 4 (three modal sites) and P1 3 (the synchronous joins
# of handle_app_close: the page-render join reports first, the thumbnail join is behind it).
ACCEPTED = frozenset({
    ("modal", "controller/pdf_controller.py", "PDFController._on_optimize_copy_failed"),
    ("modal", "controller/search_coordinator.py", "SearchCoordinator._on_search_failed"),
    ("modal", "controller/ocr_coordinator.py", "OcrCoordinator._on_ocr_failed"),
    ("block", "controller/pdf_controller.py", "PDFController.handle_app_close"),
})

_MODAL_NAMES = ("information", "warning", "critical", "question", "about", "exec", "exec_")
_PATCHED_MODULES = (
    "controller.pdf_controller", "controller.search_coordinator", "controller.ocr_coordinator",
    "controller.print_coordinator", "controller.object_probe_coordinator", "controller.vector_edit_coordinator",
    "controller.text_commit_coordinator", "controller.page_render_coordinator", "controller.thumbnail_coordinator",
)


class _Stop(Exception):
    pass


def _site(frame, trap: str) -> tuple[str, str, str]:
    """The nearest frame that lives in the repo and is not this module or a patch wrapper."""
    while frame is not None:
        path = Path(frame.f_code.co_filename)
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            frame = frame.f_back
            continue
        if rel.startswith("test_scripts/") or rel.startswith(".venv"):
            frame = frame.f_back
            continue
        return (trap, rel, frame.f_code.co_qualname)
    return (trap, "?", "?")


class _Recorder:
    def __init__(self) -> None:
        self.sites: set[tuple[str, str, str]] = set()

    def modal(self, *_a, **_k):
        self.sites.add(_site(sys._getframe(1), "modal"))
        return QMessageBox.StandardButton.Ok

    def block(self, *_a, **_k):
        self.sites.add(_site(sys._getframe(1), "block"))
        raise _Stop

    def install(self, monkeypatch) -> None:
        import importlib

        for name in _MODAL_NAMES:
            monkeypatch.setattr(QMessageBox, name, staticmethod(self.modal) if name not in ("exec", "exec_") else self.modal, raising=False)
        monkeypatch.setattr(QDialog, "exec", self.modal, raising=False)
        for name in ("getText", "getMultiLineText", "getInt", "getDouble", "getItem"):
            monkeypatch.setattr(QInputDialog, name, staticmethod(self.modal), raising=False)
        for mod_name in _PATCHED_MODULES:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "show_error"):
                monkeypatch.setattr(mod, "show_error", self.modal)


def _blocking_coordinator(recorder: _Recorder):
    return SimpleNamespace(cancel=lambda: None, wait_for_done=recorder.block)


def _drive_optimize(_r):
    from controller.pdf_controller import PDFController

    ns = SimpleNamespace(_hide_optimize_progress_dialog=lambda: None, _optimize_close_pending=False, view=None)
    PDFController._on_optimize_copy_failed(ns, RuntimeError("x"))


def _drive_search(_r):
    from controller.search_coordinator import SearchCoordinator

    ns = SimpleNamespace(_search_gen=1, _c=SimpleNamespace(view=object()))
    SearchCoordinator._on_search_failed(ns, 1, RuntimeError("x"))


def _drive_ocr(_r):
    from controller.ocr_coordinator import OcrCoordinator

    ns = SimpleNamespace(_ocr_gen=1, _c=SimpleNamespace(view=object()))
    OcrCoordinator._on_ocr_failed(ns, 1, RuntimeError("x"))


def _drive_print_failed(_r):
    import controller.print_coordinator as pc
    from PySide6.QtCore import QObject
    from src.printing.errors import PrintJobSubmissionError

    coordinator = pc.PrintCoordinator(SimpleNamespace(view=QObject()))
    coordinator._hide_print_progress_dialog = lambda: None
    coordinator._on_print_submission_failed(PrintJobSubmissionError("boom"))


def _drive_handle_app_close(r):
    from controller.pdf_controller import PDFController

    ns = SimpleNamespace(_page_render_coordinator=_blocking_coordinator(r), _thumbnail_coordinator=_blocking_coordinator(r))
    event = SimpleNamespace(ignore=lambda: None, accept=lambda: None)
    PDFController.handle_app_close(ns, event)


# name -> (driver, True when the handler opens a modal in normal operation: the control must see it)
HANDLERS = {
    "optimize_failed": (_drive_optimize, True),
    "search_failed": (_drive_search, True),
    "ocr_failed": (_drive_ocr, True),
    "print_failed": (_drive_print_failed, True),  # guarded while shutting down: must record nothing
    "handle_app_close": (_drive_handle_app_close, False),
}


def observe(monkeypatch, handlers=None, *, closed: bool = True) -> set[tuple[str, str, str]]:
    registry = get_registry()
    recorder = _Recorder()
    recorder.install(monkeypatch)
    if closed:
        registry.close_admission()
    try:
        for driver, _modal in (handlers or HANDLERS).values():
            try:
                driver(recorder)
            except _Stop:
                pass
    finally:
        registry.open_admission()
    return recorder.sites


def diff(observed, accepted) -> tuple[set, set]:
    return set(observed) - set(accepted), set(accepted) - set(observed)


def test_the_drain_traps_see_exactly_the_accepted_sites(qapp, monkeypatch):
    new, stale = diff(observe(monkeypatch), ACCEPTED)
    assert not new, f"NEW drain site(s) (a modal or a synchronous join while admission is closed): {sorted(new)}"
    assert not stale, f"STALE allowlist entr(ies) (fixed: delete from ACCEPTED): {sorted(stale)}"


def test_a_new_modal_site_is_caught(qapp, monkeypatch):
    def new_handler(_r):
        import controller.pdf_controller as pc

        # A handler that lives in the production tree (compiled under a controller/ file name).
        code = compile(
            "def _on_something_failed(pc):\n    pc.show_error(None, 'x')\n",
            str(REPO_ROOT / "controller" / "mutant_site.py"), "exec",
        )
        scope: dict = {}
        exec(code, scope)  # noqa: S102
        scope["_on_something_failed"](pc)

    handlers = {**HANDLERS, "new": (new_handler, True)}
    new, stale = diff(observe(monkeypatch, handlers), ACCEPTED)
    assert not stale
    assert new == {("modal", "controller/mutant_site.py", "_on_something_failed")}, new


def test_a_stale_entry_is_caught(qapp, monkeypatch):
    new, stale = diff(observe(monkeypatch), ACCEPTED | {("modal", "controller/ocr_coordinator.py", "OcrCoordinator.gone")})
    assert not new
    assert stale == {("modal", "controller/ocr_coordinator.py", "OcrCoordinator.gone")}


def test_the_modal_traps_are_sensitive_with_admission_open(qapp, monkeypatch):
    """Control: with admission open every modal handler must trigger the trap, else the closed-run proves nothing."""
    seen = observe(monkeypatch, closed=False)
    modal_files = {site[1] for site in seen if site[0] == "modal"}
    for name, (_driver, modal) in HANDLERS.items():
        if not modal:
            continue
        one = observe(monkeypatch, {name: HANDLERS[name]}, closed=False)
        assert any(site[0] == "modal" for site in one), f"the modal trap saw nothing for {name} with admission open"
    assert "controller/print_coordinator.py" in modal_files


def _modal_handler_functions() -> set[tuple[str, str]]:
    out = set()
    pattern = re.compile(r"^_on_\w*(failed|succeeded|error)$")
    for path in sorted((REPO_ROOT / "controller").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for fn in cls.body:
                if not isinstance(fn, ast.FunctionDef) or not pattern.match(fn.name):
                    continue
                for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                    f = call.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                    if name == "show_error" or (
                        name in _MODAL_NAMES and isinstance(f, ast.Attribute)
                        and isinstance(f.value, ast.Name) and f.value.id in ("QMessageBox", "QDialog")
                    ):
                        out.add((path.relative_to(REPO_ROOT).as_posix(), f"{cls.name}.{fn.name}"))
                        break
    return out


def test_every_modal_failure_handler_is_driven_by_the_table():
    driven = {
        ("controller/pdf_controller.py", "PDFController._on_optimize_copy_failed"),
        ("controller/search_coordinator.py", "SearchCoordinator._on_search_failed"),
        ("controller/ocr_coordinator.py", "OcrCoordinator._on_ocr_failed"),
        ("controller/print_coordinator.py", "PrintCoordinator._on_print_submission_failed"),
        ("controller/print_coordinator.py", "PrintCoordinator._on_print_submission_succeeded"),
    }
    missing = _modal_handler_functions() - driven
    assert not missing, f"a handler that opens a modal is not in HANDLERS (add a driver): {sorted(missing)}"
