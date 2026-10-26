"""Umbrella REAL-APP UI acceptance for the fourteen proven Type0 edits.

Critique step 1 of plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md
(sections 3 and 4).  The app is launched through the public composition root
``main.run(argv=[tmp copy], start_event_loop=False)``, so ``TextCommitSettings.from_env``
and ``PDFController.activate()`` run exactly as for a user.  Nothing on the render
path is stubbed (not ``show_page``, the render state or the viewport anchor).  The
test drives the UI with real input only:

- QTest mouse clicks at a glyph centre of the target show, mapped with the view's
  own ``_doc_rect_to_scene_rect`` helper;
- ``QTest.keyClicks`` for Latin and digits, ``QInputMethodEvent`` commit strings
  for CJK;
- the real page box, the run/paragraph combo, the Apply button, and the
  undo/redo/save toolbar actions.

Spies only record calls and always pass through: preview deliveries, the edit
request, ``TieredCommitEngine.commit``, toasts and the save path.  Modal dialogs
are replaced by recorders that return a safe default (No/None), because a real
modal hangs offscreen pytest.

The case table, hash pins and structural/pixel checks come from
``test_text_commit_real_corpus_acceptance`` (imported as a module, never copied).
The ECC show60 text is known only by its hash: every assertion compares digests
and every recorded message is sanitized.

Each positive test writes a per-case, per-phase matrix JSON into ``tmp_path``.
The ``env`` leg configures ``engine=tiered``, ``max_tier=1`` and ``preview=plan``
through the same environment/``from_env`` composition the app uses; the
``shipped`` leg (critique step 12) removes every TEXT_COMMIT_* variable and
runs the same cases under the shipped defaults, whose target-mode combo must
already read "run".
``test_shipped_text_commit_defaults_are_the_acceptance_configuration`` checks
that the SHIPPED defaults equal those values (red until the step 12 flip).

The second renderer is Poppler's ``pdftoppm``: the ``PDF_EDITOR_PDFTOPPM``
environment variable, else ``shutil.which``.  A missing renderer FAILS the
second_renderer phase; it is never a skip.

The corpora are gitignored, so CI deselects this module through the
``needs_fixtures`` marker.

The ECC growth negative (the longer drawing number that crowded the column
line in the 2026-09-21 experiment) is not here: docs/experiments and
_evidence_pilot keep only the redacted placeholder ``[ECC_DWG_LONG]``, and the
ecc-4 pilot case is the SHORTER 'ECC-3' edit already in the positive table.
No test invents that text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import fitz
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_text_commit_real_corpus_acceptance as acc  # noqa: E402

from model.edit_commands import EditTextResult  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    FontResourceAction,
    TextCommitSettings,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402

pytestmark = pytest.mark.needs_fixtures

#: The acceptance configuration (plan section 3, last paragraph), composed
#: through the environment exactly as ``main.run`` does.
ACCEPTANCE_ENV = {
    "TEXT_COMMIT_ENGINE": "tiered",
    "TEXT_COMMIT_MAX_TIER": "1",
    "TEXT_COMMIT_PREVIEW": "plan",
}
#: Left at their shipped values so the umbrella judges the shipped refusal policy.
_UNSET_ENV = ("TEXT_COMMIT_STRICT", "TEXT_COMMIT_CONFIRM_DEGRADE", "TEXT_COMMIT_TELEMETRY")

PHASES = (
    "select",
    "input",
    "preview",
    "apply",
    "undo",
    "redo",
    "save_reopen",
    "second_renderer",
)
#: The interactive phases (no save/second renderer): what the part-5 stage B
#: "add a text box, then edit the same page" pass judges per case.
INTERACTIVE_PHASES = PHASES[:6]
PASS, FAIL, NOT_RUN, BLOCKED = "pass", "fail", "not_run", "blocked"

EDITOR_OPEN_TIMEOUT_S = 120.0
PREVIEW_TIMEOUT_S = 300.0
POPPLER_DPI = 144  # 2x, same pixel grid as acc._pixmap_array
#: hvac p4/show11: '線' swapped for '路', which the embedded PMingLiU subset lacks.
MISSING_GLYPH_TEXT = "空調冰水管路系統圖(1)"


# ------------------------------------------------------------------ identity


def _digest(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _case_id(spec: acc.CorpusSpec, case: acc.CorpusCase) -> str:
    return f"{spec.slug}/p{case.page_index}/show{case.show_seq}"


def _case_label(spec: acc.CorpusSpec, case: acc.CorpusCase) -> str:
    """Zero-based page label WITHOUT the original text (ECC show60 is hash-only)."""
    return f"{_case_id(spec, case)} -> {case.replacement!r}"


def _find_case(spec: acc.CorpusSpec, cases, page_index: int, show_seq: int) -> acc.CorpusCase:
    for case in cases:
        if (case.page_index, case.show_seq) == (page_index, show_seq):
            return case
    raise AssertionError(f"{spec.slug}: no case p{page_index}/show{show_seq} in the pinned table")


class _Sanitizer:
    """Replace every hash-pinned original text in recorded messages."""

    def __init__(self, cases) -> None:
        self._secrets = [
            case.original
            for case in cases
            if case.original_sha256 is not None and case.original
        ]

    def __call__(self, message: str) -> str:
        for secret in self._secrets:
            token = f"<sha256:{_digest(secret)[:12]}>"
            message = message.replace(repr(secret), token).replace(secret, token)
        return message


def _git(*args: str) -> bytes | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, check=True, timeout=60
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _code_revision() -> dict:
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    diff = _git("diff", "HEAD", "--binary")
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z")
    hasher = hashlib.sha256(diff or b"")
    for rel in sorted(filter(None, (untracked or b"").split(b"\0"))):
        hasher.update(b"\0untracked\0" + rel + b"\0")
        try:
            hasher.update((ROOT / rel.decode("utf-8")).read_bytes())
        except OSError:
            hasher.update(b"<unreadable>")
    return {
        "code_revision": head.decode().strip() if head else "unknown",
        "dirty": bool(status.strip()) if status is not None else None,
        "dirty_diff_id": hasher.hexdigest() if diff is not None else "unknown",
    }


def _pdftoppm() -> str | None:
    configured = os.environ.get("PDF_EDITOR_PDFTOPPM")
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("pdftoppm")


def _tool_versions(pdftoppm: str | None) -> dict:
    from PySide6 import __version__ as pyside_version

    poppler = "missing"
    if pdftoppm:
        try:
            probe = subprocess.run(
                [pdftoppm, "-v"], capture_output=True, text=True, timeout=60
            )
            poppler = (probe.stderr or probe.stdout).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            poppler = "unrunnable"
    return {"pymupdf": fitz.VersionBind, "pyside6": pyside_version, "poppler": poppler}


def _poppler_pixels(exe: str, pdf_path: Path, page_index: int, out_dir: Path) -> np.ndarray:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"{pdf_path.stem}-p{page_index}"
    subprocess.run(
        [
            exe,
            "-f",
            str(page_index + 1),
            "-l",
            str(page_index + 1),
            "-r",
            str(POPPLER_DPI),
            "-png",
            "-singlefile",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    pixmap = fitz.Pixmap(str(prefix) + ".png")
    if pixmap.alpha:
        pixmap = fitz.Pixmap(pixmap, 0)
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, :3]


def _glyph_rect(doc: fitz.Document, case: acc.CorpusCase, text: str) -> fitz.Rect:
    """Visual-space rect of a middle non-space glyph of the case's show."""
    show = acc._shows(doc, case.page_index)[case.show_seq]
    with acc._measurement_copy(doc) as measured:
        trace = acc._trace_for(measured[case.page_index], show, text)
        rotation = measured[case.page_index].rotation_matrix
    glyphs = [char for char in trace["chars"] if chr(char[0]).strip()]
    assert glyphs
    return fitz.Rect(glyphs[len(glyphs) // 2][3]) * rotation


def _non_target_mismatches(before: tuple, after: fitz.Document, changed: set[int]) -> list[int]:
    """Every non-target xref that differs (``acc`` stops at the first one)."""
    mismatched = []
    for xref, original in enumerate(before, 1):
        if xref in changed:
            continue
        current = acc._object_entry(after, xref)
        if original[0] == current[0] == "object" and acc._objects_semantically_equal(
            original[1], current[1]
        ):
            continue
        if current != original:
            mismatched.append(xref)
    return mismatched


def _page_streams(doc: fitz.Document, page_index: int) -> list[tuple[int, bytes]]:
    return [(xref, doc.xref_stream(xref)) for xref in doc[page_index].get_contents()]


# ------------------------------------------------------------------ app harness


@dataclass
class _Recorder:
    modals: list[tuple[str, str]] = field(default_factory=list)
    toasts: list[tuple[str, str, float]] = field(default_factory=list)
    deliveries: list[dict] = field(default_factory=list)
    payloads: list[dict] = field(default_factory=list)
    requests: list = field(default_factory=list)
    commits: list[tuple[bool, object, object, float]] = field(default_factory=list)
    saves: list[str] = field(default_factory=list)


class _App:
    """One real app session on a tmp copy (``main.run``), driven by real input."""

    def __init__(self, monkeypatch, pdf_path: Path, *, shipped: bool = False) -> None:
        from PySide6.QtWidgets import QMessageBox

        import controller.pdf_controller as controller_module
        import main
        import view.message_boxes as message_boxes
        import view.pdf_view as pdf_view_module

        for name, value in ACCEPTANCE_ENV.items():
            if shipped:
                # Critique step 12: the shipped defaults, with NO override.
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        for name in _UNSET_ENV:
            monkeypatch.delenv(name, raising=False)
        self.rec = rec = _Recorder()
        self.pdf_path = pdf_path

        def _modal(kind: str, default):
            def _record(*args, **kwargs):
                texts = [str(a) for a in args[1:3] if isinstance(a, str)]
                rec.modals.append((kind, " | ".join(texts)))
                return default

            return _record

        monkeypatch.setattr(QMessageBox, "information", staticmethod(_modal("information", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(_modal("warning", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(_modal("critical", QMessageBox.Ok)))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(_modal("question", QMessageBox.No)))
        monkeypatch.setattr(QMessageBox, "about", staticmethod(_modal("about", None)))
        monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: rec.modals.append(("exec", self.text())) or 0)
        for module in (controller_module, message_boxes, pdf_view_module):
            if hasattr(module, "show_error"):
                monkeypatch.setattr(module, "show_error", _modal("show_error", None))
        monkeypatch.setattr(
            controller_module, "confirm_degraded_fallback", _modal("confirm_degraded_fallback", False)
        )

        original_commit = TieredCommitEngine.commit

        def _commit_spy(engine, prepared):
            outcome = original_commit(engine, prepared)
            live = self.model is not None and engine._doc is self.model.doc
            rec.commits.append((live, prepared, outcome, time.monotonic()))
            return outcome

        self.model = None
        monkeypatch.setattr(TieredCommitEngine, "commit", _commit_spy)

        startup = main.run(argv=[str(pdf_path)], start_event_loop=False)
        self.app = startup["app"]
        self.view = view = startup["view"]
        self.model = model = startup["model"]
        self.controller = startup["controller"]
        assert model is not None and self.controller is not None

        original_toast = view._show_toast

        def _toast(message, duration_ms=1500, tone="success"):
            rec.toasts.append((str(message), str(tone), time.monotonic()))
            return original_toast(message, duration_ms, tone)

        view._show_toast = _toast
        original_delivery = view.apply_text_edit_plan_preview

        def _delivery(**kwargs):
            rec.deliveries.append(
                {
                    "session_key": kwargs.get("session_key"),
                    "generation": kwargs.get("generation"),
                    "image": kwargs.get("image") is not None,
                    "plan_token": kwargs.get("plan_token"),
                    "reject_reason": kwargs.get("reject_reason"),
                    "t": time.monotonic(),
                }
            )
            return original_delivery(**kwargs)

        view.apply_text_edit_plan_preview = _delivery
        view.sig_text_edit_plan_preview.connect(
            lambda payload: rec.payloads.append(dict(payload, t=time.monotonic()))
        )
        view.sig_edit_text.connect(rec.requests.append)
        for name in ("_save_doc", "_full_save_to_path", "_atomic_full_save"):
            original = getattr(model, name, None)
            if callable(original):
                def _save_spy(*args, _name=name, _original=original, **kwargs):
                    rec.saves.append(_name)
                    return _original(*args, **kwargs)

                setattr(model, name, _save_spy)
        view.resize(1400, 1000)
        self.pump(300)

    # ---- event loop

    def pump(self, ms: float) -> None:
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def wait(self, predicate, timeout_s: float) -> bool:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return bool(predicate())

    # ---- state readers (no mutation)

    def editor(self):
        proxy = self.view.text_editor
        return proxy.widget() if proxy is not None else None

    def live_commits(self) -> list:
        return [entry for entry in self.rec.commits if entry[0]]

    def snapshot(self) -> fitz.Document:
        """Independent copy of the live document (never judge the live handle)."""
        return fitz.open("pdf", self.model.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))

    def undo_depth(self) -> int:
        return len(self.model.command_manager._undo_stack)

    # ---- real UI input

    def goto_page(self, page_index: int) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        box = self.view.page_number_input
        box.setFocus()
        QTest.keyClick(box, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(box, str(page_index + 1))
        QTest.keyClick(box, Qt.Key_Return)
        self.pump(400)

    def ensure_edit_text_run_mode(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        if self.view.current_mode != "edit_text":
            self.view._action_edit_text.trigger()
            self.pump(100)
        assert self.view.current_mode == "edit_text"
        combo = self.view.text_target_mode_combo
        for _ in range(combo.count()):
            if combo.currentData() == "run":
                break
            combo.setFocus()
            QTest.keyClick(combo, Qt.Key_Up)
            self.pump(50)
        assert combo.currentData() == "run", combo.currentData()
        assert self.model.text_target_mode == "run"

    def click_glyph(self, page_index: int, visual_rect: fitz.Rect):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        centre = self.view._doc_rect_to_scene_rect(page_index, visual_rect).center()
        self.view.graphics_view.centerOn(centre)
        self.pump(200)
        position = self.view.graphics_view.mapFromScene(centre)
        QTest.mouseClick(
            self.view.graphics_view.viewport(), Qt.LeftButton, Qt.NoModifier, position
        )
        self.wait(lambda: self.editor() is not None, EDITOR_OPEN_TIMEOUT_S)
        return self.editor()

    def type_replacing_all(self, editor, text: str) -> None:
        """Ctrl+A, then Latin/digits as key clicks and CJK as IME commit strings."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        editor.setFocus()
        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
        index = 0
        while index < len(text):
            end = index
            ascii_chunk = text[index].isascii()
            while end < len(text) and text[end].isascii() == ascii_chunk:
                end += 1
            if ascii_chunk:
                QTest.keyClicks(editor, text[index:end])
            else:
                event = QInputMethodEvent("", [])
                event.setCommitString(text[index:end])
                QApplication.sendEvent(editor, event)
            index = end

    def wait_preview(self, editor) -> tuple[str | None, str | None]:
        """Bounded wait for the CURRENT generation's token or rejection."""
        state: dict = {}

        def _settled() -> bool:
            generation = editor._plan_generation
            token = editor.current_plan_token()
            if token is not None:
                state.update(token=token, reason=None)
                return True
            session = getattr(editor, "plan_preview_session_key", None)
            for delivery in reversed(self.rec.deliveries):
                if (
                    delivery["session_key"] == session
                    and delivery["generation"] == generation
                    and delivery["reject_reason"] is not None
                    and not delivery["image"]
                ):
                    state.update(token=None, reason=delivery["reject_reason"])
                    return True
            return False

        if not self.wait(_settled, PREVIEW_TIMEOUT_S):
            return None, f"no preview for generation {editor._plan_generation} in {PREVIEW_TIMEOUT_S}s"
        return state["token"], state["reason"]

    def click_apply(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.mouseClick(self.view.text_apply_btn, Qt.LeftButton)
        self.pump(400)

    def press_escape(self, editor) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.keyClick(editor, Qt.Key_Escape)
        self.pump(200)

    def trigger(self, action_name: str) -> None:
        getattr(self.view, action_name).trigger()
        self.pump(400)

    def close(self) -> None:
        """End preview work BEFORE destroying widgets (a running QThread aborts)."""
        try:
            try:
                # Kept editor first (its armed debounce would restart a session).
                self.view.finalize_text_edit_for_close(save=False)
                self.controller._end_text_edit_plan_preview_session()
                coordinator = getattr(self.controller, "_text_commit_preview_coordinator", None)
                if coordinator is not None:
                    coordinator.wait_for_done(int(PREVIEW_TIMEOUT_S * 1000))
            finally:
                self.controller.handle_app_close = lambda event: event.accept()
                self.view.close()
                self.pump(100)
        finally:
            self.model.close()
            self.app.setStyleSheet("")
            self.pump(50)


# ------------------------------------------------------------------ phase matrix


class _Matrix:
    def __init__(
        self, spec, cases, sanitize, pdftoppm, source_sha256: str, phases: tuple[str, ...] = PHASES
    ) -> None:
        self.sanitize = sanitize
        self.phases = phases
        self.meta = {
            **_code_revision(),
            "tool_versions": _tool_versions(pdftoppm),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "command": (
                ".venv/Scripts/python.exe -m pytest "
                "test_scripts/test_text_commit_ui_real_corpus.py"
            ),
            "settings_env": dict(ACCEPTANCE_ENV),
            "limits": (
                "MuPDF and Poppler pixel checks at 2x; masks are the before/after "
                "trace bbox union plus 3 pt.  No 6x crop review (step 15)."
            ),
        }
        self.rows: dict[str, dict] = {}
        for case in cases:
            self.rows[_case_id(spec, case)] = {
                "case_id": _case_id(spec, case),
                "label": _case_label(spec, case),
                "source_sha256": source_sha256,
                "page_index": case.page_index,
                "show_seq": case.show_seq,
                "resource": case.font_resource,
                "old_text_sha256": _digest(case.original),
                "new_text": case.replacement,
                "requested_style_changes": None,
                "phases": {
                    phase: {"status": NOT_RUN, "detail": "", "seconds": None}
                    for phase in phases
                },
            }

    def set(self, case_id: str, phase: str, status: str, detail: str = "", seconds=None) -> None:
        cell = self.rows[case_id]["phases"][phase]
        cell.update(status=status, detail=self.sanitize(detail)[:4000])
        if seconds is not None:
            cell["seconds"] = round(float(seconds), 2)

    def block_rest(self, case_id: str, after_phase: str, reason: str) -> None:
        later = self.phases[self.phases.index(after_phase) + 1 :]
        for phase in later:
            if self.rows[case_id]["phases"][phase]["status"] == NOT_RUN:
                self.set(case_id, phase, BLOCKED, reason)

    def status(self, case_id: str, phase: str) -> str:
        return self.rows[case_id]["phases"][phase]["status"]

    def write(self, path: Path, extra: dict) -> None:
        path.write_text(
            json.dumps(
                {**self.meta, **extra, "cases": list(self.rows.values())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def failures(self) -> list[str]:
        lines = []
        for row in self.rows.values():
            for phase in self.phases:
                cell = row["phases"][phase]
                if cell["status"] != PASS:
                    lines.append(
                        f"{row['case_id']} {phase}: {cell['status']}: {cell['detail'][:300]}"
                    )
        return lines

    def table(self) -> str:
        header = "case".ljust(22) + " ".join(phase[:10].ljust(10) for phase in self.phases)
        lines = [header]
        for row in self.rows.values():
            lines.append(
                row["case_id"].ljust(22)
                + " ".join(row["phases"][phase]["status"].ljust(10) for phase in self.phases)
            )
        return "\n".join(lines)


class _PhaseError(AssertionError):
    pass


def _run_phase(matrix: _Matrix, case_id: str, phase: str, body) -> bool:
    started = time.monotonic()
    try:
        body()
    except Exception as exc:  # noqa: BLE001 - every failure is a recorded cell
        detail = f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, AssertionError):
            detail += "\n" + "".join(traceback.format_exception_only(type(exc), exc))
        matrix.set(case_id, phase, FAIL, detail, time.monotonic() - started)
        matrix.block_rest(case_id, phase, f"blocked by {phase} failure")
        return False
    matrix.set(case_id, phase, PASS, "", time.monotonic() - started)
    return True


# ------------------------------------------------------------------ per-case checks


@dataclass
class _CaseState:
    before_doc: fitz.Document | None = None
    before_objects: tuple | None = None
    before_streams: list | None = None
    before_pixels: np.ndarray | None = None
    before_show: object = None
    before_trace: dict | None = None
    editor: object = None
    ref: object = None
    token: str | None = None
    prepared: object = None
    after_doc: fitz.Document | None = None
    after_streams: list | None = None
    after_pixels: np.ndarray | None = None
    mask: fitz.Rect | None = None

    def close(self) -> None:
        for doc in (self.before_doc, self.after_doc):
            if doc is not None:
                doc.close()


def _expected_tier(case: acc.CorpusCase) -> CommitTier:
    if case.expected_tj_compensation is not None:
        return CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE
    return CommitTier.TIER0_LOSSLESS_STREAM_PATCH


def _assert_committed_state(
    spec: acc.CorpusSpec, case: acc.CorpusCase, state: _CaseState, after: fitz.Document
) -> None:
    """The engine acceptance file's per-edit checks, on a copy of the live state."""
    from model.text_commit.fonts import DocumentFontRegistry

    page_index = case.page_index
    before, prepared = state.before_doc, state.prepared
    assert prepared.font_resource == case.font_resource, prepared.font_resource
    assert prepared.font_xref == DocumentFontRegistry(before).capability(
        before[page_index], case.font_resource
    ).font_xref, "the commit resolved another font object than the source resource"
    acc._assert_only_target_streams_changed(
        state.before_objects, after, {prepared.stream_xref}, semantic=True
    )
    after_show = acc._shows(after, page_index)[case.show_seq]
    for name in acc._TEXT_STATE_FIELDS:
        assert getattr(after_show, name) == getattr(state.before_show, name), name
    acc._assert_source_font_reused(before, after, case, state.before_show, after_show)
    if case.expected_tj_compensation is not None:
        acc._assert_tj_compensation_is_last(prepared, case.expected_tj_compensation)
        assert after_show.operator == "TJ" and after_show.array_item_count == 1
        stream = after.xref_stream(after_show.stream_xref)
        assert stream[after_show.op_start : after_show.op_end] == prepared.replacement.replacement_bytes
    before_shows = acc._shows(before, page_index)
    after_shows = acc._shows(after, page_index)
    assert len(after_shows) == len(before_shows)
    for old, new in zip(before_shows, after_shows):
        if old.seq != case.show_seq:
            assert new.origin_user == old.origin_user, f"non-target show {old.seq} moved"
    with acc._measurement_copy(after) as measured:
        after_trace = acc._trace_for(measured[page_index], after_show, case.replacement)
    assert after_trace["font"] == state.before_trace["font"] == case.basefont
    for name in ("dir", "size", "color", "opacity", "type"):
        assert after_trace[name] == state.before_trace[name], name
    assert after_trace["chars"][0][2] == state.before_trace["chars"][0][2], "origin moved"
    mask = fitz.Rect(state.before_trace["bbox"]) | fitz.Rect(after_trace["bbox"])
    state.mask = mask * before[page_index].rotation_matrix + (-3, -3, 3, 3)
    state.after_pixels = acc._pixmap_array(after[page_index])
    acc._assert_pixels_changed_only_inside_masks(
        spec.slug, page_index, state.before_pixels, state.after_pixels, [state.mask]
    )


def _run_positive_case(
    app: _App, spec: acc.CorpusSpec, case: acc.CorpusCase, matrix: _Matrix, source: fitz.Document
) -> _CaseState:
    case_id = _case_id(spec, case)
    state = _CaseState()
    page_index = case.page_index

    def select() -> None:
        click_rect = _glyph_rect(source, case, case.original)
        state.before_doc = app.snapshot()
        state.before_objects = acc._object_snapshot(state.before_doc)
        state.before_streams = _page_streams(state.before_doc, page_index)
        state.before_pixels = acc._pixmap_array(state.before_doc[page_index])
        state.before_show = acc._shows(state.before_doc, page_index)[case.show_seq]
        with acc._measurement_copy(state.before_doc) as measured:
            state.before_trace = acc._trace_for(
                measured[page_index], state.before_show, case.original
            )
        if app.view.current_page != page_index:
            app.goto_page(page_index)
        app.ensure_edit_text_run_mode()
        editor = app.click_glyph(page_index, click_rect)
        assert editor is not None, "clicking the glyph opened no inline editor"
        state.editor = editor
        shown = editor.toPlainText()
        assert _digest(shown) == _digest(case.original), (
            f"editor text is not the whole show text (len {len(shown)} vs {len(case.original)}, "
            f"sha {_digest(shown)[:12]} vs {_digest(case.original)[:12]})"
        )
        ref = getattr(app.view, "editing_source_ref", None)
        assert ref is not None, "the click carried no source_ref"
        assert ref.seq == case.show_seq, f"source_ref.seq {ref.seq} != {case.show_seq}"
        assert (ref.stream_xref, ref.op_start) == (
            state.before_show.stream_xref,
            state.before_show.op_start,
        ), "source_ref names another show operator"
        state.ref = ref

    def type_input() -> None:
        app.type_replacing_all(state.editor, case.replacement)
        assert state.editor.toPlainText() == case.replacement

    def preview() -> None:
        token, reason = app.wait_preview(state.editor)
        assert token is not None, f"no current plan token; rejection: {reason}"
        assert state.editor.current_plan_token() == token
        state.token = token

    def apply() -> None:
        commits_before = len(app.live_commits())
        requests_before = len(app.rec.requests)
        depth_before = app.undo_depth()
        app.click_apply()
        new_commits = app.live_commits()[commits_before:]
        assert len(new_commits) == 1, f"{len(new_commits)} live engine commits on Apply"
        _, prepared, outcome, _ = new_commits[0]
        state.prepared = prepared
        assert prepared.token == state.token, "Apply committed another candidate than the preview's"
        assert outcome.status is CommitStatus.COMMITTED, outcome
        assert outcome.tier is _expected_tier(case), outcome.tier
        assert outcome.font_outcomes and all(
            font.action == FontResourceAction.SOURCE_RESOURCE_REUSED
            for font in outcome.font_outcomes
        ), outcome.font_outcomes
        assert outcome.fallback_chain == () and not any(
            "legacy" in step for step in outcome.decision_chain
        ), outcome
        requests = app.rec.requests[requests_before:]
        assert len(requests) == 1, f"{len(requests)} edit requests on Apply"
        request = requests[0]
        assert request.plan_token == state.token
        # Bound to the token by the MODEL gate (a tokenless or stale commit
        # refuses), and made by the Apply button -- not a click-away or focus
        # finalize that happened to carry the same token (VERIFY part 2).
        assert request.requires_preview_token is True
        assert request.source_ref == state.ref
        assert not request.style_overrides.changed, request.style_overrides
        finalize = app.view._last_text_edit_finalize_result
        assert finalize is not None and finalize.reason.value == "apply", finalize
        assert finalize.outcome.value == "committed", finalize
        assert finalize.edit_result is EditTextResult.SUCCESS, finalize
        assert app.undo_depth() == depth_before + 1
        command = app.model.command_manager._undo_stack[-1]
        assert command.result is EditTextResult.SUCCESS, command.result
        assert app.editor() is None, "the editor stayed open after a successful Apply"
        state.after_doc = app.snapshot()
        state.after_streams = _page_streams(state.after_doc, page_index)
        _assert_committed_state(spec, case, state, state.after_doc)

    def undo() -> None:
        app.trigger("_action_undo")
        with app.snapshot() as undone:
            assert _page_streams(undone, page_index) == state.before_streams, "undo streams"
            acc._assert_only_target_streams_changed(
                state.before_objects, undone, set(), semantic=True
            )
            assert np.array_equal(acc._pixmap_array(undone[page_index]), state.before_pixels), (
                "undo did not restore the original render exactly"
            )

    def redo() -> None:
        app.trigger("_action_redo")
        with app.snapshot() as redone:
            assert _page_streams(redone, page_index) == state.after_streams, "redo streams"
            assert np.array_equal(acc._pixmap_array(redone[page_index]), state.after_pixels), (
                "redo did not restore the edited render exactly"
            )

    for phase, body in (
        ("select", select),
        ("input", type_input),
        ("preview", preview),
        ("apply", apply),
        ("undo", undo),
        ("redo", redo),
    ):
        if matrix.status(case_id, phase) != NOT_RUN:
            break
        if not _run_phase(matrix, case_id, phase, body):
            break
    return state


def _restore_after_failure(app: _App, state: _CaseState, depth_before: int) -> str | None:
    """Put the session back to the pre-case state; None when that is proven."""
    editor = app.editor()
    if editor is not None:
        app.press_escape(editor)
    while app.undo_depth() > depth_before:
        depth = app.undo_depth()
        app.trigger("_action_undo")
        if app.undo_depth() >= depth:
            return f"undo refused while restoring (depth {depth})"
    if app.editor() is not None:
        return "an inline editor is still open"
    if state.before_doc is None or state.before_streams is None:
        return None
    with app.snapshot() as current:
        for page_index in range(len(current)):
            if _page_streams(current, page_index) != _page_streams(state.before_doc, page_index):
                return f"page {page_index} streams differ from the pre-case state"
    return None


def _check_saved_file(
    app: _App,
    spec: acc.CorpusSpec,
    cases,
    states: dict,
    matrix: _Matrix,
    source: fitz.Document,
    work_path: Path,
    pdftoppm: str | None,
    render_dir: Path,
) -> dict:
    committed = [
        case for case in cases if matrix.status(_case_id(spec, case), "redo") == PASS
    ]
    extra: dict = {"save": {}}
    if not committed:
        for case in cases:
            matrix.block_rest(_case_id(spec, case), "redo", "no committed case to save")
        return extra
    source_objects = acc._object_snapshot(source)
    with app.snapshot() as final_live:
        live_pixels = {
            page: acc._pixmap_array(final_live[page])
            for page in {case.page_index for case in committed}
        }
    modals_before = len(app.rec.modals)
    saves_before = len(app.rec.saves)
    app.trigger("_action_save")
    save_modals = app.rec.modals[modals_before:]
    extra["save"] = {"paths": app.rec.saves[saves_before:], "modals": save_modals}
    changed_streams = {states[case].prepared.stream_xref for case in committed}
    global_errors: list[str] = []
    page_errors: dict[int, list[str]] = {}
    case_errors: dict[acc.CorpusCase, list[str]] = {}

    def _record(bucket: list[str], exc: Exception) -> None:
        bucket.append(f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")

    started = time.monotonic()
    if [kind for kind, _ in save_modals] != ["information"]:
        global_errors.append(f"save modals {save_modals}")
    with fitz.open(str(work_path)) as reopened:
        try:
            acc._assert_only_target_streams_changed(
                source_objects, reopened, changed_streams, semantic=True
            )
        except Exception as exc:  # noqa: BLE001 - each check group is its own cell input
            _record(global_errors, exc)
            global_errors.append(
                "all non-target mismatches: "
                f"{_non_target_mismatches(source_objects, reopened, changed_streams)}"
            )
        appended = [
            xref
            for xref in range(len(source_objects) + 1, reopened.xref_length())
            if reopened.xref_get_key(xref, "Type") != ("name", "/XRef")
        ]
        if appended:
            global_errors.append(f"save appended non-XRef objects {appended}")
        masks: dict[int, list[fitz.Rect]] = {}
        for case in committed:
            errors = case_errors.setdefault(case, [])
            try:
                after_show = acc._shows(reopened, case.page_index)[case.show_seq]
                source_show = acc._shows(source, case.page_index)[case.show_seq]
                acc._assert_source_font_reused(source, reopened, case, source_show, after_show)
                for name in acc._TEXT_STATE_FIELDS:
                    assert getattr(after_show, name) == getattr(source_show, name), name
                if case.expected_tj_compensation is not None:
                    stream = reopened.xref_stream(after_show.stream_xref)
                    assert (
                        stream[after_show.op_start : after_show.op_end]
                        == states[case].prepared.replacement.replacement_bytes
                    ), "Tier 1 payload changed on save"
                # The live snapshot's _trace_for checks, re-run on the file.
                before_trace = states[case].before_trace
                with acc._measurement_copy(reopened) as measured:
                    trace = acc._trace_for(measured[case.page_index], after_show, case.replacement)
                assert trace["font"] == before_trace["font"] == case.basefont, "reopened font"
                for name in ("dir", "size", "color", "opacity", "type"):
                    assert trace[name] == before_trace[name], f"reopened {name}"
                assert trace["chars"][0][2] == before_trace["chars"][0][2], "reopened origin moved"
            except Exception as exc:  # noqa: BLE001
                _record(errors, exc)
            masks.setdefault(case.page_index, []).append(states[case].mask)
        for page_index, page_masks in masks.items():
            errors = page_errors.setdefault(page_index, [])
            # Every NON-target show keeps its origin in the reopened file
            # (all of the page's committed shows are targets).
            targets = {case.show_seq for case in committed if case.page_index == page_index}
            try:
                source_shows = acc._shows(source, page_index)
                reopened_shows = acc._shows(reopened, page_index)
                assert len(reopened_shows) == len(source_shows), "reopened show count"
                moved = [
                    old.seq
                    for old, new in zip(source_shows, reopened_shows)
                    if old.seq not in targets and new.origin_user != old.origin_user
                ]
                assert not moved, f"non-target shows moved on reopen: {moved}"
            except Exception as exc:  # noqa: BLE001
                _record(errors, exc)
            reopened_pixels = acc._pixmap_array(reopened[page_index])
            if not np.array_equal(reopened_pixels, live_pixels[page_index]):
                errors.append("reopened render differs from the live render")
            try:
                acc._assert_pixels_changed_only_inside_masks(
                    spec.slug,
                    page_index,
                    acc._pixmap_array(source[page_index]),
                    reopened_pixels,
                    page_masks,
                )
            except Exception as exc:  # noqa: BLE001
                _record(errors, exc)
    seconds = time.monotonic() - started
    for case in committed:
        errors = global_errors + case_errors.get(case, []) + page_errors.get(case.page_index, [])
        matrix.set(
            _case_id(spec, case), "save_reopen", FAIL if errors else PASS, "; ".join(errors), seconds
        )
    extra["save"]["errors"] = {
        "global": global_errors,
        "pages": {str(page): errors for page, errors in page_errors.items() if errors},
    }

    # The second renderer judges the saved FILE, so a structural save_reopen
    # failure does not block it: its pixels are independent evidence.
    started = time.monotonic()
    if pdftoppm is None:
        for case in committed:
            if matrix.status(_case_id(spec, case), "second_renderer") == NOT_RUN:
                matrix.set(
                    _case_id(spec, case),
                    "second_renderer",
                    FAIL,
                    "pdftoppm not found: set PDF_EDITOR_PDFTOPPM or put pdftoppm on PATH",
                )
        return extra
    poppler_errors: dict[int, str] = {}
    for page_index in sorted({case.page_index for case in committed}):
        page_masks = [
            states[case].mask
            for case in committed
            if case.page_index == page_index
            and matrix.status(_case_id(spec, case), "second_renderer") == NOT_RUN
        ]
        if not page_masks:
            continue
        try:
            before = _poppler_pixels(pdftoppm, Path(source.name), page_index, render_dir / "before")
            after = _poppler_pixels(pdftoppm, work_path, page_index, render_dir / "after")
            acc._assert_pixels_changed_only_inside_masks(
                f"{spec.slug}-poppler", page_index, before, after, page_masks
            )
        except Exception as exc:  # noqa: BLE001
            poppler_errors[page_index] = f"{type(exc).__name__}: {exc}"
    seconds = time.monotonic() - started
    for case in committed:
        case_id = _case_id(spec, case)
        if matrix.status(case_id, "second_renderer") == NOT_RUN:
            error = poppler_errors.get(case.page_index)
            matrix.set(case_id, "second_renderer", FAIL if error else PASS, error or "", seconds)
    return extra


# ------------------------------------------------------------------ positive umbrella


#: One app session per (corpus, page): the manifest's ``active`` (click-reachable) rows' own pages, never a copied
#: list.  ``engine_active`` rows (acceptance-green only) never enter the UI path.
_PAGE_GROUPS = tuple(
    (spec, page_index)
    for spec in acc._MANIFEST.click_reachable_specs()
    for page_index in sorted({case.page_index for case in spec.cases})
)
#: Critique step 12: every positive also runs under the SHIPPED defaults with
#: no TEXT_COMMIT_* variable at all (``shipped``), besides the explicit
#: acceptance environment (``env``).
_CONFIGS = ("env", "shipped")
_POSITIVE_PARAMS = tuple(
    (spec, page_index, config) for config in _CONFIGS for spec, page_index in _PAGE_GROUPS
)


@pytest.mark.parametrize(
    ("spec", "page_index", "config"),
    _POSITIVE_PARAMS,
    ids=[f"{config}-{spec.slug}-p{page_index}" for spec, page_index, config in _POSITIVE_PARAMS],
)
def test_ui_commits_every_real_type0_edit_through_the_running_app(
    spec: acc.CorpusSpec, page_index: int, config: str, tmp_path: Path, monkeypatch
) -> None:
    """Every pinned case on one page: click, type, preview, Apply, undo, redo, save, reopen.

    One app session per page group (which also keeps each HVAC run under the
    foreground time budget).  The page's cases run in table order on the same
    document, as a user would edit it: consecutive same-page edits, then one
    save and reopen (plan section 4).  A failing phase blocks that case's later
    phases; the session is restored (Esc + undo) and the next case still runs,
    so one run reports every current failure.
    """
    source_path = acc._fixture(spec)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    work_path = tmp_path / f"{spec.slug}-p{page_index}-ui.pdf"
    shutil.copyfile(source_path, work_path)
    pdftoppm = _pdftoppm()
    started = time.monotonic()
    with fitz.open(str(source_path)) as source:
        all_cases = acc._resolve_cases(spec, source)
        cases = tuple(case for case in all_cases if case.page_index == page_index)
        assert cases
        sanitize = _Sanitizer(all_cases)
        matrix = _Matrix(spec, cases, sanitize, pdftoppm, source_sha256)
        matrix_path = tmp_path / f"ui_phase_matrix_{config}_{spec.slug}-p{page_index}.json"
        matrix.meta["config"] = config
        if config == "shipped":
            matrix.meta["settings_env"] = {}
        states: dict = {}
        contaminated: dict[int, str] = {}
        extra: dict = {}
        shipped = config == "shipped"
        app = _App(monkeypatch, work_path, shipped=shipped)
        try:
            if shipped:
                assert not any(name in os.environ for name in ACCEPTANCE_ENV)
                # Before ensure_edit_text_run_mode, which would press Up until
                # it reaches "run" and so hide a wrong shipped default.
                assert app.view.text_target_mode_combo.currentData() == "run"
                assert app.model.text_target_mode == "run"
            settings = app.model.text_commit_settings
            assert (settings.engine, settings.max_tier, settings.preview) == ("tiered", 1, "plan")
            for case in cases:
                case_id = _case_id(spec, case)
                if case.page_index in contaminated:
                    matrix.set(case_id, "select", BLOCKED, contaminated[case.page_index])
                    matrix.block_rest(case_id, "select", contaminated[case.page_index])
                    continue
                depth_before = app.undo_depth()
                state = _run_positive_case(app, spec, case, matrix, source)
                states[case] = state
                if matrix.status(case_id, "redo") != PASS:
                    problem = _restore_after_failure(app, state, depth_before)
                    if problem is not None:
                        contaminated[case.page_index] = (
                            f"page contaminated by {case_id}: {problem}"
                        )
            extra = _check_saved_file(
                app, spec, cases, states, matrix, source, work_path, pdftoppm, tmp_path / "poppler"
            )
        finally:
            extra.update(
                runtime_seconds=round(time.monotonic() - started, 1),
                modals=app.rec.modals,
                toasts=[(sanitize(message), tone) for message, tone, _ in app.rec.toasts],
            )
            matrix.write(matrix_path, extra)
            for state in states.values():
                state.close()
            app.close()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_sha256
    print(f"\nphase matrix: {matrix_path}\n{matrix.table()}")
    failures = matrix.failures()
    assert not failures, (
        f"{len(failures)} failing/blocked cells ({matrix_path}):\n{matrix.table()}\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize(
    ("spec", "page_index"),
    _PAGE_GROUPS,
    ids=[f"shipped-{spec.slug}-p{page_index}" for spec, page_index in _PAGE_GROUPS],
)
def test_ui_every_edit_still_commits_after_a_text_box_was_added_on_the_same_page(
    spec: acc.CorpusSpec, page_index: int, tmp_path: Path, monkeypatch
) -> None:
    """Part 5 stage B ("add-or-rebuild then edit same page"), shipped defaults.

    A text box added through the view's real signal queues clean_contents
    maintenance and turns the page's /Contents into several streams.  The
    old ``pending_page_maintenance`` gate refused every true-text edit on
    such a page; each pinned case must now select, preview (token), Apply
    (Tier 0/1, source font reused, no legacy), undo and redo exactly like on
    a pristine page.  ``_run_positive_case`` takes its "before" state AFTER
    the add, so every non-target check judges the page the user really has.
    (The consented-rebuild leg of the stage runs on the synthetic fixture in
    test_text_commit_pending_maintenance_retired.py: a rebuild is
    intentionally lossy, so it cannot honour this module's pixel masks.)
    """
    source_path = acc._fixture(spec)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    work_path = tmp_path / f"{spec.slug}-p{page_index}-add.pdf"
    shutil.copyfile(source_path, work_path)
    with fitz.open(str(source_path)) as source:
        all_cases = acc._resolve_cases(spec, source)
        cases = tuple(case for case in all_cases if case.page_index == page_index)
        assert cases
        matrix = _Matrix(
            spec, cases, _Sanitizer(all_cases), None, source_sha256, INTERACTIVE_PHASES
        )
        app = _App(monkeypatch, work_path, shipped=True)
        try:
            app.goto_page(page_index)
            app.view.sig_add_textbox.emit(
                page_index + 1, fitz.Rect(12, 12, 130, 40), "NEW BOX", "helv", 12,
                (0.0, 0.0, 0.0), None,
            )
            app.pump(400)
            assert [e["page_idx"] for e in app.model.pending_edits] == [page_index], (
                "the add queued no cleanup"
            )
            for case in cases:
                depth_before = app.undo_depth()
                state = _run_positive_case(app, spec, case, matrix, source)
                if matrix.status(_case_id(spec, case), "redo") != PASS:
                    _restore_after_failure(app, state, depth_before)
                state.close()
        finally:
            app.close()
    print(f"\nadd-then-edit matrix\n{matrix.table()}")
    failures = matrix.failures()
    assert not failures, "\n".join(failures) + "\n" + matrix.table()


# ------------------------------------------------------------------ negatives


def _open_case(monkeypatch, tmp_path: Path, spec, page_index: int, show_seq: int):
    source_path = acc._fixture(spec)
    work_path = tmp_path / f"{spec.slug}-p{page_index}-show{show_seq}.pdf"
    shutil.copyfile(source_path, work_path)
    with fitz.open(str(source_path)) as source:
        cases = acc._resolve_cases(spec, source)
        case = _find_case(spec, cases, page_index, show_seq)
        click_rect = _glyph_rect(source, case, case.original)
        # Judged against ``_App.snapshot()`` (a tobytes copy), so the baseline
        # must go through the same serialization: tobytes drops object streams
        # and re-serializes ~1300 HVAC objects, which the original file keeps.
        with acc._measurement_copy(source) as serialized:
            source_objects = acc._object_snapshot(serialized)
        source_streams = _page_streams(source, page_index)
    app = _App(monkeypatch, work_path)
    return app, case, click_rect, source_objects, source_streams, work_path


def _open_editor(app: _App, case, click_rect):
    app.goto_page(case.page_index)
    app.ensure_edit_text_run_mode()
    editor = app.click_glyph(case.page_index, click_rect)
    assert editor is not None, "clicking the glyph opened no inline editor"
    assert editor.toPlainText() == case.original
    return editor


def _success_notices(app: _App, since: float) -> list[tuple[str, str]]:
    """Success or commit-announcing (degrade warning) toasts after ``since``."""
    return [
        (message, tone)
        for message, tone, t in app.rec.toasts
        if t >= since and tone in ("success", "warning")
    ]


def test_ui_missing_glyph_refuses_keeps_input_and_leaves_pdf_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    """hvac p4/show11 typed with '路', which the embedded subset lacks.

    Required (plan section 4, failure handling): the preview refuses with
    ``type0_unicode_unmapped`` and issues no token.  Apply then changes nothing
    (no engine commit, no undo entry, the PDF and the file on disk unchanged),
    keeps the editor and the typed text, and shows no success notice or modal.
    Every failed facet is reported together.
    """
    app, case, click_rect, source_objects, source_streams, work_path = _open_case(
        monkeypatch, tmp_path, acc.HVAC, 4, 11
    )
    work_sha = hashlib.sha256(work_path.read_bytes()).hexdigest()
    problems: list[str] = []
    try:
        editor = _open_editor(app, case, click_rect)
        app.type_replacing_all(editor, MISSING_GLYPH_TEXT)
        assert editor.toPlainText() == MISSING_GLYPH_TEXT
        token, reason = app.wait_preview(editor)
        if token is not None or reason != "type0_unicode_unmapped":
            problems.append(f"preview: token={token!r} reason={reason!r}")
        since = time.monotonic()
        depth = app.undo_depth()
        app.click_apply()
        if app.live_commits():
            problems.append(f"apply: {len(app.live_commits())} live engine commits")
        if app.undo_depth() != depth:
            command = app.model.command_manager._undo_stack[-1]
            outcome = getattr(command, "outcome", None)
            problems.append(
                f"apply: an undo entry was recorded (result={command.result}, "
                f"status={getattr(outcome, 'status', None)}, "
                f"chain={getattr(outcome, 'fallback_chain', None)})"
            )
        with app.snapshot() as live:
            if _page_streams(live, case.page_index) != source_streams:
                problems.append("pdf: the target page's content streams changed")
            try:
                acc._assert_only_target_streams_changed(
                    source_objects, live, set(), semantic=True
                )
            except AssertionError as exc:
                problems.append(f"pdf: {str(exc).splitlines()[0]}")
        if hashlib.sha256(work_path.read_bytes()).hexdigest() != work_sha:
            problems.append("file: the PDF on disk changed")
        current = app.editor()
        if current is None:
            finalize = getattr(app.view, "_last_text_edit_finalize_result", None)
            problems.append(
                "input: the editor closed on refusal "
                f"(finalize {getattr(finalize, 'reason', None)} -> {getattr(finalize, 'outcome', None)})"
            )
        elif current.toPlainText() != MISSING_GLYPH_TEXT:
            problems.append("input: the typed text was not kept")
        notices = _success_notices(app, since)
        if notices:
            problems.append(f"notice: {notices}")
        if app.rec.modals:
            problems.append(f"modal: {app.rec.modals}")
    finally:
        app.close()
    assert not problems, "missing-glyph refusal contract broken:\n" + "\n".join(problems)


def test_ui_missing_glyph_rebuild_action_decline_then_accept(
    tmp_path: Path, monkeypatch
) -> None:
    """UI step 10 on the real fixture: hvac p4/show11 typed with '路'.

    The kept editor shows 原字型沒有這個字 and offers "改用重建文字…" (Apply
    stays disabled).  Declining the consent changes nothing (no commit, no
    undo entry, streams and file unchanged, editor and input kept, no
    notice).  Accepting -- a new, separate request -- commits exactly one
    rebuild with one notice; undo and redo are exact (the redo restores the
    after-snapshot, UI step 8) and never ask again.  Page streams are
    compared by content: a page-snapshot restore may renumber their xrefs.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import controller.pdf_controller as controller_module
    from view.text_edit_reasons import MISSING_GLYPH_TEXT as REASON_TEXT

    app, case, click_rect, _objects, source_streams, work_path = _open_case(
        monkeypatch, tmp_path, acc.HVAC, 4, 11
    )
    work_sha = hashlib.sha256(work_path.read_bytes()).hexdigest()
    page_index = case.page_index
    source_bytes = [data for _xref, data in source_streams]

    def _live_bytes() -> list[bytes]:
        with app.snapshot() as live:
            return [data for _xref, data in _page_streams(live, page_index)]

    def _consents() -> list:
        return [m for m in app.rec.modals if m[0] == "confirm_degraded_fallback"]

    try:
        editor = _open_editor(app, case, click_rect)
        app.type_replacing_all(editor, MISSING_GLYPH_TEXT)
        token, reason = app.wait_preview(editor)
        assert token is None and reason == "type0_unicode_unmapped", (token, reason)
        app.pump(100)
        label = app.view.text_plan_status_label
        button = app.view.text_rebuild_btn
        assert not label.isHidden() and label.text() == REASON_TEXT
        assert not button.isHidden() and button.isEnabled()
        assert app.view.text_apply_btn.isEnabled() is False

        # ---- decline (the recorded consent answers No, its default)
        since = time.monotonic()
        depth = app.undo_depth()
        QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
        app.pump(600)
        assert len(_consents()) == 1, app.rec.modals
        request = app.rec.requests[-1]
        assert request.allow_rebuild is True and request.plan_token is None
        assert request.new_text == MISSING_GLYPH_TEXT
        assert app.live_commits() == []
        assert app.undo_depth() == depth
        assert _live_bytes() == source_bytes
        assert hashlib.sha256(work_path.read_bytes()).hexdigest() == work_sha
        assert app.editor() is editor and editor.toPlainText() == MISSING_GLYPH_TEXT
        assert _success_notices(app, since) == []

        # ---- accept: a NEW request through the same button
        asked: list[str] = []

        def _yes(_parent, message):
            asked.append(message)
            return True

        monkeypatch.setattr(controller_module, "confirm_degraded_fallback", _yes)
        assert app.wait(lambda: not button.isHidden(), PREVIEW_TIMEOUT_S), (
            "the kept editor did not offer the rebuild again"
        )
        since = time.monotonic()
        QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
        app.pump(800)
        assert len(asked) == 1
        assert app.rec.requests[-1].allow_rebuild is True
        assert app.editor() is None
        assert app.undo_depth() == depth + 1
        command = app.model.command_manager._undo_stack[-1]
        assert command.outcome.status is CommitStatus.DEGRADED_COMMITTED
        assert command.outcome.fallback_chain[-1] == "legacy"
        assert command._after_page_snapshot_bytes is not None
        notices = _success_notices(app, since)
        assert len(notices) == 1 and notices[0][1] == "warning", notices
        after_bytes = _live_bytes()
        assert after_bytes != source_bytes

        app.trigger("_action_undo")
        assert _live_bytes() == source_bytes, "undo did not restore the page streams"
        app.trigger("_action_redo")
        assert _live_bytes() == after_bytes, "redo did not restore the rebuilt streams"
        assert len(asked) == 1, "undo/redo must never ask again"
        assert len(_success_notices(app, since)) == 1, "redo repeated the notice"
        assert [m for m in app.rec.modals if m[0] != "confirm_degraded_fallback"] == []
    finally:
        app.close()


def test_ui_twin_buffer_tank_shows_are_targeted_separately(tmp_path: Path, monkeypatch) -> None:
    """hvac p6 show5 (mirrored) and show7 have the same text; each click targets its own show.

    Guard: expected to pass since G2/C2 (click-time grouping plus source_ref).
    """
    app, case5, rect5, source_objects, _, _ = _open_case(monkeypatch, tmp_path, acc.HVAC, 6, 5)
    try:
        with fitz.open(str(acc._fixture(acc.HVAC))) as source:
            cases = acc._resolve_cases(acc.HVAC, source)
            case7 = _find_case(acc.HVAC, cases, 6, 7)
            rect7 = _glyph_rect(source, case7, case7.original)
            shows = acc._shows(source, 6)
        refs = {}
        for case, rect in ((case5, rect5), (case7, rect7)):
            if app.view.current_page != case.page_index:
                app.goto_page(case.page_index)
            app.ensure_edit_text_run_mode()
            editor = app.click_glyph(case.page_index, rect)
            assert editor is not None, f"show{case.show_seq}: no editor"
            assert editor.toPlainText() == "Buffer Tank"
            ref = app.view.editing_source_ref
            show = shows[case.show_seq]
            assert (ref.seq, ref.stream_xref, ref.op_start) == (
                case.show_seq,
                show.stream_xref,
                show.op_start,
            )
            refs[case.show_seq] = ref
            app.press_escape(editor)
            assert app.editor() is None
        assert refs[5] != refs[7]
        assert app.live_commits() == [] and app.undo_depth() == 0
        with app.snapshot() as live:
            acc._assert_only_target_streams_changed(source_objects, live, set(), semantic=True)
        assert app.rec.modals == []
    finally:
        app.close()


def _wheel_until_page(app: _App, target_page: int, direction: int, max_notches: int = 400) -> int:
    """Real wheel events over the viewport until ``current_page`` is ``target_page``.

    The wheel is the only page switch in continuous mode that keeps focus on
    the canvas, so the inline editor stays open (the page box and the
    thumbnail list take focus, which finalizes the editor first).
    """
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    viewport = app.view.graphics_view.viewport()
    position = QPointF(viewport.rect().center())
    global_position = QPointF(viewport.mapToGlobal(viewport.rect().center()))
    notches = 0
    while app.view.current_page != target_page and notches < max_notches:
        event = QWheelEvent(
            position,
            global_position,
            QPoint(0, 0),
            QPoint(0, 120 * direction),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(viewport, event)
        app.pump(15)
        notches += 1
    app.pump(1500)
    return notches


def test_ui_stale_token_after_a_page_switch_is_never_committed(tmp_path: Path, monkeypatch) -> None:
    """Type, wait for the preview token, wheel to the previous page and back, Apply.

    Plan section 3: a page switch invalidates the token.  A live commit is
    stale unless it carries a token delivered for the current generation AFTER
    the return.  Apply is pressed at once, with no fresh preview, so any commit
    during the switch or on that Apply fails.  Tokens are content-derived, so
    the check uses delivery order, not token strings.

    The switch is a real wheel scroll, which keeps the editor open.  Switching
    through the page box does not reach this case: a user's click on the box
    moves focus first, and the ``focus_outside`` finalize commits the CURRENT
    token before any page change (probed 2026-09-30).  An earlier version drove
    the box with focus + keys and no event processing between them, so the
    finalize ran after the switch -- a synthetic-timing red, not this defect.
    """
    app, case, click_rect, source_objects, source_streams, _ = _open_case(
        monkeypatch, tmp_path, acc.HVAC, 6, 7
    )
    problems: list[str] = []
    try:
        editor = _open_editor(app, case, click_rect)
        app.type_replacing_all(editor, case.replacement)
        token, reason = app.wait_preview(editor)
        assert token is not None, f"precondition: no preview token ({reason})"
        switched_at = time.monotonic()
        away = case.page_index - 1
        _wheel_until_page(app, away, direction=1)
        assert app.view.current_page == away, (
            f"precondition: the wheel did not reach page {away} (at {app.view.current_page})"
        )
        away_editor = app.editor() is not None
        finalize = getattr(app.view, "_last_text_edit_finalize_result", None)
        _wheel_until_page(app, case.page_index, direction=-1)
        assert app.view.current_page == case.page_index, (
            f"precondition: the wheel did not return to page {case.page_index}"
        )
        returned_at = time.monotonic()
        current = app.editor()
        if current is None and not app.live_commits():
            problems.append(
                "the page switch discarded the editor and the typed input "
                f"(finalize {getattr(finalize, 'reason', None)} -> {getattr(finalize, 'outcome', None)})"
            )
        if current is not None:
            app.click_apply()
        fresh = [
            d
            for d in app.rec.deliveries
            if d["t"] >= returned_at and d["plan_token"] is not None
        ]
        for _, prepared, outcome, t in app.live_commits():
            if t < switched_at:
                continue
            if not any(d["t"] <= t and d["plan_token"] == prepared.token for d in fresh):
                when = "during the page switch" if t < returned_at else "on Apply after returning"
                problems.append(
                    f"stale token committed {when} (status={outcome.status.value}, "
                    f"editor open while away={away_editor}, finalize="
                    f"{getattr(finalize, 'reason', None)} -> {getattr(finalize, 'outcome', None)})"
                )
        if not app.live_commits():
            with app.snapshot() as live:
                if _page_streams(live, case.page_index) != source_streams:
                    problems.append("the page changed without an engine commit (legacy path?)")
            kept = app.editor()
            if kept is None or kept.toPlainText() != case.replacement:
                problems.append("a refused Apply did not keep the editor and the typed text")
        assert app.rec.modals == [], app.rec.modals
    finally:
        app.close()
    assert not problems, "\n".join(problems)


def test_ui_rapid_typing_commits_only_the_final_text(tmp_path: Path, monkeypatch) -> None:
    """ecc show57: type '113.05.04' and let its preview start, then correct it to '113.05.05' at once.

    Supersession must really happen: the older request is still in flight
    when the correcting keystrokes land, otherwise the test reports BLOCKED.
    Only the final text's token may reach the editor and be committed.

    Guard: passes before the token/finalize steps.  A superseded result is
    dropped by the coordinator (``_is_current``) or, if delivered, refused by
    the editor's generation check; the test records which layer acted.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, case, click_rect, _, _, _ = _open_case(monkeypatch, tmp_path, acc.ECC, 0, 57)
    try:
        assert case.replacement == "113.05.05"
        editor = _open_editor(app, case, click_rect)
        applied: list[tuple[int, bool]] = []
        original_apply = editor.apply_plan_preview

        def _apply_spy(generation, image, plan_token=None):
            accepted = original_apply(generation, image, plan_token)
            applied.append((generation, accepted))
            return accepted

        editor.apply_plan_preview = _apply_spy
        app.type_replacing_all(editor, "113.05.04")
        first_generation = editor._plan_generation
        assert app.wait(
            lambda: any(p["generation"] == first_generation for p in app.rec.payloads), 30
        ), "the first preview request was never emitted"
        coordinator = app.controller._text_commit_preview_coordinator
        in_flight = coordinator is not None and coordinator.has_active_job
        QTest.keyClick(editor, Qt.Key_Backspace)
        QTest.keyClicks(editor, "5")
        final_generation = editor._plan_generation
        assert editor.toPlainText() == "113.05.05"
        token, reason = app.wait_preview(editor)
        assert token is not None, f"no token for the final text ({reason})"
        if not in_flight:
            pytest.fail("BLOCKED: the first preview finished before the correction; supersession not exercised")
        older = [d for d in app.rec.deliveries if d["generation"] < final_generation]
        print(
            "\nsupersession: "
            f"first generation {first_generation} in flight={in_flight}; "
            f"older deliveries={[(d['generation'], d['image']) for d in older]}; "
            f"editor apply calls={applied}"
        )
        stale_accepted = [g for g, ok in applied if ok and g < final_generation]
        assert stale_accepted == [], f"superseded generations reached the editor: {stale_accepted}"
        app.click_apply()
        commits = app.live_commits()
        assert len(commits) == 1, f"{len(commits)} live commits"
        _, prepared, outcome, _ = commits[0]
        assert prepared.token == token
        assert outcome.status is CommitStatus.COMMITTED, outcome
        assert app.rec.requests[-1].new_text == "113.05.05"
        with app.snapshot() as live:
            from model.text_commit.fonts import DocumentFontRegistry

            show = acc._shows(live, 0)[57]
            assert acc._decode_show(DocumentFontRegistry(live), live[0], show) == "113.05.05"
        assert app.rec.modals == []
    finally:
        app.close()


def test_ui_apply_during_an_ime_preedit_never_commits_the_text_without_it(
    tmp_path: Path, monkeypatch
) -> None:
    """ecc show31: commit '專案' through the IME, then start composing '圖名' (preedit only) and press Apply.

    Plan section 4, UI row (中文組字).  Apply during a preedit must wait, refuse,
    or commit the composed text.  It must never commit the document text
    WITHOUT the preedit.  Offscreen Qt has no platform input context, so
    nothing commits the preedit on the focus change.

    ENVIRONMENT-DEPENDENT: a red here is offscreen-only until confirmed on a
    real input context.  A desktop IME usually commits (or cancels) the
    composition when focus moves to the Apply button, which this platform
    cannot reproduce.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    committed_text, composing = "專案", "圖名"
    app, case, click_rect, _, source_streams, _ = _open_case(monkeypatch, tmp_path, acc.ECC, 0, 31)
    problems: list[str] = []
    try:
        editor = _open_editor(app, case, click_rect)
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
        commit = QInputMethodEvent("", [])
        commit.setCommitString(committed_text)
        QApplication.sendEvent(editor, commit)
        assert editor.toPlainText() == committed_text
        token, reason = app.wait_preview(editor)
        assert token is not None, f"precondition: no token for the committed text ({reason})"
        generation, payloads = editor._plan_generation, len(app.rec.payloads)
        QApplication.sendEvent(editor, QInputMethodEvent(composing, []))
        app.pump(600)
        assert editor.toPlainText() == committed_text, "precondition: preedit reached the document"
        observed = (
            f"preedit bumped generation {generation}->{editor._plan_generation}, "
            f"{len(app.rec.payloads) - payloads} new preview payloads"
        )
        app.click_apply()
        texts = [request.new_text for request in app.rec.requests]
        if committed_text in texts:
            problems.append(f"Apply emitted the text without the preedit ({observed})")
        with app.snapshot() as live:
            from model.text_commit.fonts import DocumentFontRegistry

            show = acc._shows(live, 0)[31]
            decoded = acc._decode_show(DocumentFontRegistry(live), live[0], show)
            if decoded == committed_text:
                problems.append(
                    "the page now shows the text without the preedit "
                    f"({len(app.live_commits())} live commits)"
                )
            elif not app.live_commits() and _page_streams(live, 0) != source_streams:
                problems.append("the page changed without an engine commit")
        assert app.rec.modals == [], app.rec.modals
    finally:
        app.close()
    assert not problems, "\n".join(problems)


# ------------------------------------------------------------------ save-time pruning (round 6, P3a)

_REBUILD_ORIGINAL = "備為C標新設"
_REBUILD_TYPED = "2點擊頁面備為C標新設。"


def _open_shipped_ecc_copy(monkeypatch, tmp_path: Path):
    """The owner's flow: a COPY of ecc-dwg.pdf, shipped defaults, run target mode."""
    work = tmp_path / "ecc-dwg - copy.pdf"
    shutil.copyfile(ROOT / acc.ECC.relative_path, work)
    app = _App(monkeypatch, work, shipped=True)
    app.ensure_edit_text_run_mode()
    return app, work


def _rebuild_through_the_ui(app: _App, monkeypatch) -> None:
    """Type over the run, accept the degraded-fallback consent, click 改用重建文字."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import controller.pdf_controller as controller_module

    monkeypatch.setattr(controller_module, "confirm_degraded_fallback", lambda *_a, **_k: True)
    with app.snapshot() as doc:
        hits = doc[0].search_for(_REBUILD_ORIGINAL)
    assert hits, "the fixture run must be on page 1"
    editor = app.click_glyph(0, hits[0])
    app.pump(300)
    app.type_replacing_all(editor, _REBUILD_TYPED)
    app.wait_preview(editor)
    button = app.view.text_rebuild_btn
    assert app.wait(lambda: not button.isHidden(), 10), "the rebuild action must be offered"
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
    app.pump(1500)
    assert app.undo_depth() == 1, "the rebuild must be one undoable command"


def _unreachable_in(path: Path) -> list[int]:
    from model.save_compaction import unreachable_xrefs

    with fitz.open(str(path)) as saved:
        return unreachable_xrefs(saved)


def test_rebuild_undo_save_writes_no_orphans_and_redo_survives(
    tmp_path: Path, monkeypatch
) -> None:
    """Owner recording (round 6, P3): a 222 KB copy saved as 5.9 MB after rebuild +
    Ctrl+Z.  The undone rebuild's objects (a 5 MB font program among them) stay in
    the live doc; the save must not write them, and redo must still work after the
    save freed their slots."""
    app, work = _open_shipped_ecc_copy(monkeypatch, tmp_path)
    original_size = work.stat().st_size
    try:
        _rebuild_through_the_ui(app, monkeypatch)
        app.trigger("_action_undo")
        app.pump(800)
        app.trigger("_action_save")
        app.pump(1500)
        saved_size = work.stat().st_size
        assert saved_size < 2 * original_size, (
            f"saved {saved_size} bytes from an original of {original_size}: the undone "
            "rebuild's orphan objects were written"
        )
        assert _unreachable_in(work) == []

        app.trigger("_action_redo")
        app.pump(800)
        with app.snapshot() as live:
            assert "2點擊頁面" in live[0].get_text()
            pixels = live[0].get_pixmap(dpi=40).samples
            assert min(pixels) < 255, "the redone page must not render blank"
        app.trigger("_action_undo")
        app.pump(800)
        with app.snapshot() as live:
            assert _REBUILD_ORIGINAL in live[0].get_text()
        app.model.ensure_page_index_built(1)
        hit = app.model.get_text_info_at_point(1, fitz.Point(841.0, 288.0))
        assert hit is not None
        expected = (802.4, 281.2, 881.1, 295.6)
        assert all(abs(a - b) < 0.2 for a, b in zip(tuple(hit.target_bbox), expected)), (
            tuple(hit.target_bbox)
        )
    finally:
        app.close()


def test_kept_rebuild_save_has_no_rebuild_leftovers(tmp_path: Path, monkeypatch) -> None:
    """A KEPT rebuild leaves its Redact annotation, the annotation's appearance, the
    replaced content stream and form XObjects unreachable (about 293 KB of garbage);
    Ctrl+S must not carry them."""
    app, work = _open_shipped_ecc_copy(monkeypatch, tmp_path)
    try:
        _rebuild_through_the_ui(app, monkeypatch)
        app.trigger("_action_save")
        app.pump(1500)
        assert _unreachable_in(work) == []
        with fitz.open(str(work)) as saved:
            redact_annots = [
                xref
                for xref in range(1, saved.xref_length())
                if saved.xref_get_key(xref, "Subtype") == ("name", "/Redact")
            ]
            assert redact_annots == []
            assert _REBUILD_TYPED[:6] in saved[0].get_text()
    finally:
        app.close()


# ------------------------------------------------------------------ shipped defaults


def test_shipped_text_commit_defaults_are_the_acceptance_configuration() -> None:
    """RED until the default flip (critique step 12): with no TEXT_COMMIT_* variables
    the app must compose exactly the configuration the umbrella tests set."""
    expected = tuple(
        (name, value)
        for name, value in (
            ("engine", "tiered"),
            ("max_tier", 1),
            ("preview", "plan"),
        )
    )
    composed = TextCommitSettings.from_env({})
    assert tuple((name, getattr(composed, name)) for name, _ in expected) == expected
    class_default = TextCommitSettings()
    assert tuple((name, getattr(class_default, name)) for name, _ in expected) == expected
