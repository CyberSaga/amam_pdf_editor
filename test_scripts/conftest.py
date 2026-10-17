from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pin_production_text_flags() -> None:
    """Set PyMuPDF's process-global text-extraction flags to the app's values.

    ``PDFModel.__init__`` turns ``small_glyph_heights`` on for the whole
    process and nothing turns it off, so before GATE16-1 a test saw ``False``
    or ``True`` depending on whether an earlier test in the same interpreter
    had built a model (order-dependent failures in multi-file runs).  Every
    test, fixture and collection step now runs under the production values:
    small glyph heights on, PyMuPDF's quad corrections on.  A test that needs
    another value sets it itself; the pin is re-applied after it.
    """
    try:
        import fitz
    except Exception:  # pragma: no cover - PyMuPDF is a hard dependency
        return
    fitz.TOOLS.set_small_glyph_heights(True)
    fitz.TOOLS.unset_quad_corrections(False)


_pin_production_text_flags()


@pytest.fixture(autouse=True)
def _production_text_flags():
    """Each test starts AND ends under the production PyMuPDF text flags."""
    _pin_production_text_flags()
    yield
    _pin_production_text_flags()


@pytest.fixture(autouse=True)
def _logging_enabled():
    """Each test starts AND ends with ``logging.disable`` cleared (GATE16-1a).

    ``logging.disable`` is process-global.  A script-style module that called
    ``logging.disable(logging.CRITICAL)`` at import ran it at collection and
    left ``caplog`` empty for every later test in the process.  Clearing it
    here also covers a test that disables logging and forgets to restore it.
    """
    logging.disable(logging.NOTSET)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def share_lock_disabled(monkeypatch):
    """Run as if the OD-FS1-LOCK deny-write share lock cannot be taken.

    On Windows an open session refuses every foreign writer of its file, so a
    test that simulates one (in-place rewrite, foreign append, external rename
    or delete) exercises the degraded mode instead: a network share without
    the lock, or a non-Windows host.  The F10-FS-1 on-disk fingerprint gate is
    the defence there, and these tests keep it honest.
    """
    from utils import file_share_lock

    monkeypatch.setattr(file_share_lock, "platform_supported", lambda: False)


@pytest.fixture(autouse=True)
def _reset_app_stylesheet():
    """Restore QApplication stylesheet to its pre-test state after each test.

    Tests that call view.apply_initial_theme() / app.setStyleSheet(...) leave a
    global stylesheet active; leaked QSS gives QTextEdit subclasses padding that
    shifts pixel-diff comparisons in later rendering tests.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before_stylesheet = app.styleSheet() if app is not None else ""
    yield
    if app is not None:
        current_app = QApplication.instance()
        if current_app is not None and current_app.styleSheet() != before_stylesheet:
            current_app.setStyleSheet(before_stylesheet)


def _ensure_test_file_1_pdf() -> None:
    """Provide a synthetic ``test_files/1.pdf`` when the real fixture is absent.

    ``test_files/`` is gitignored, so on a fresh checkout the small-clean sample
    used by the char-run-reconstruction and core-interaction-audit suites is
    missing and those tests error out. Generate a stand-in that satisfies their
    assertions (per-word runs young/the/program/favorite; line paragraphs incl.
    a "run or not run" control line; no replacement characters). Never overwrite
    a real fixture if one is already present.
    """
    target = ROOT / "test_files" / "1.pdf"
    if target.exists():
        return
    try:
        import fitz
    except Exception:
        return
    target.parent.mkdir(parents=True, exist_ok=True)

    def _words_line(page, y: float, words: list[str], size: float = 12.0) -> None:
        x = 72.0
        for word in words:
            page.insert_text((x, y), word, fontsize=size, fontname="helv")
            x += len(word) * size * 0.62 + size * 0.5

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _words_line(page, 120, ["When", "I", "was", "young", "the", "program", "was", "my", "favorite"])
    _words_line(page, 170, ["this", "is", "a", "run", "or", "not", "run", "control", "line"])
    _words_line(page, 220, ["some", "additional", "filler", "text", "for", "the", "document", "body"])
    doc.save(str(target), garbage=0)
    doc.close()


_ensure_test_file_1_pdf()
