"""Shipped defaults through the composition root (critique step 12, 2026-10-02).

``main.run`` composes ``TextCommitSettings.from_env(os.environ)``; these tests
launch it with NO ``TEXT_COMMIT_*`` variable (the shipped configuration) and
with only a stored, retired ``TEXT_COMMIT_ENGINE=legacy|shadow`` (which now
composes the same configuration), and drive the real View with real input.  Stored values: the environment is the only store these
settings have (the target-mode combo is not persisted), and an explicitly set
variable always wins over a default; see ``TextCommitSettings`` and plan
section 6, 2026-10-02 L entry.

Fixtures are synthetic.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.geometry import unrotated_to_visual_rect  # noqa: E402

_ENV_NAMES = (
    "TEXT_COMMIT_ENGINE",
    "TEXT_COMMIT_MAX_TIER",
    "TEXT_COMMIT_PREVIEW",
    "TEXT_COMMIT_STRICT",
    "TEXT_COMMIT_TELEMETRY",
    "TEXT_COMMIT_CONFIRM_DEGRADE",
)
TARGET = "Hello World"
REPLACEMENT = "Hello Wurld"


def _write_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), TARGET, fontname="helv", fontsize=14.0)
    doc.save(str(path))
    doc.close()
    return path


def _pump(app, ms: float) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _wait(app, predicate, timeout_s: float) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


@pytest.fixture
def launched(tmp_path: Path, monkeypatch, request):
    """``main.run`` on a synthetic copy; indirect param = env overrides."""
    from PySide6.QtWidgets import QMessageBox

    import controller.pdf_controller as controller_module
    import main

    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in dict(getattr(request, "param", {}) or {}).items():
        monkeypatch.setenv(name, value)
    modals: list[str] = []
    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QMessageBox,
            kind,
            staticmethod(lambda *a, _k=kind, **k: modals.append(_k) or QMessageBox.No),
        )
    monkeypatch.setattr(controller_module, "show_error", lambda *a, **k: modals.append("show_error"))
    monkeypatch.setattr(
        controller_module, "confirm_degraded_fallback", lambda *a, **k: modals.append("confirm") or False
    )
    path = _write_pdf(tmp_path / "shipped.pdf")
    startup = main.run(argv=[str(path)], start_event_loop=False)
    app, view, model, controller = (
        startup["app"],
        startup["view"],
        startup["model"],
        startup["controller"],
    )
    view.resize(1200, 900)
    _pump(app, 300)
    try:
        yield app, view, model, controller, modals
    finally:
        try:
            # Kept editor first (its armed debounce would restart a session).
            view.finalize_text_edit_for_close(save=False)
            controller._end_text_edit_plan_preview_session()
            coordinator = getattr(controller, "_text_commit_preview_coordinator", None)
            if coordinator is not None:
                coordinator.wait_for_done(60000)
        finally:
            controller.handle_app_close = lambda event: event.accept()
            view.close()
            _pump(app, 50)
            model.close()


def test_shipped_launch_composes_the_acceptance_configuration(launched) -> None:
    """RED before step 12: max_tier 0, legacy preview, paragraph combo."""
    _app, view, model, _controller, modals = launched
    settings = model.text_commit_settings
    assert (settings.engine, settings.max_tier, settings.preview, settings.strict) == (
        "tiered",
        1,
        "plan",
        False,
    )
    assert view.text_target_mode_combo.currentData() == "run"
    assert model.text_target_mode == "run"
    # The controller turned the token gate on for the shipped plan preview.
    assert getattr(view, "_text_plan_preview_required", None) is True
    assert modals == []


def _write_pages(path: Path, count: int) -> Path:
    doc = fitz.open()
    for index in range(count):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 200), f"Page {index + 1} text", fontname="helv", fontsize=14.0)
    doc.save(str(path))
    doc.close()
    return path


def test_shipped_run_mode_prewarms_the_visible_page_index_before_any_hover(
    launched, tmp_path: Path
) -> None:
    """Critique step 12 latency: the per-page text index (~110-125 ms on HVAC
    p5/p6) used to be built by the paragraph-mode outline pass when edit mode
    was entered or the viewport changed -- the old combo default.  With "run"
    shipped, nothing built it until the first HOVER, which then paid index
    build + source-run grouping in one GUI event (p6 cold click 222/294 ms).
    Entering edit mode and moving to another page must build the visible
    page's index in their own events, with no hover or click."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, view, model, controller, modals = launched
    assert view.text_target_mode_combo.currentData() == "run"
    controller.open_pdf(str(_write_pages(tmp_path / "pages.pdf", 4)))
    _pump(app, 400)
    states = model.block_manager.page_state
    assert states(0) == "missing" and states(2) == "missing"
    view._action_edit_text.trigger()
    _pump(app, 300)
    assert view.current_mode == "edit_text"
    assert states(0) == "clean", "entering edit mode left the visible page unindexed"

    box = view.page_number_input
    box.setFocus()
    QTest.keyClick(box, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(box, "3")
    QTest.keyClick(box, Qt.Key_Return)
    _pump(app, 600)
    assert states(2) == "clean", "moving to page 3 left it unindexed"
    assert modals == []


def _open_editor(app, view, model):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    if view.current_mode != "edit_text":
        view._action_edit_text.trigger()
        _pump(app, 100)
    model.ensure_page_index_built(1)
    run = [r for r in model.block_manager.get_runs(0) if r.text == "World"][0]
    visual = unrotated_to_visual_rect(model.doc[0], fitz.Rect(run.bbox))
    rs = view._render_scale if view._render_scale > 0 else 1.0
    centre = QPointF(
        view._page_scene_x(0) + (visual.x0 + visual.x1) / 2.0 * rs,
        view._page_scene_y(0) + (visual.y0 + visual.y1) / 2.0 * rs,
    )
    view.graphics_view.centerOn(centre)
    _pump(app, 100)
    QTest.mouseClick(
        view.graphics_view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        view.graphics_view.mapFromScene(centre),
    )
    assert _wait(app, lambda: view.text_editor is not None, 30.0), "no inline editor"
    return view.text_editor.widget()


def _type(editor, text: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(editor, text)


def test_shipped_defaults_apply_commits_the_verified_preview_by_token(launched) -> None:
    """Under the shipped defaults a run click edits the whole show, Apply waits
    for the verified preview and commits it by token (Tier 0, no legacy)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, view, model, _controller, modals = launched
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(app, view, model)
    assert editor.toPlainText() == TARGET
    _type(editor, REPLACEMENT)
    assert _wait(app, lambda: editor.current_plan_token() is not None, 120.0), "no token"
    assert view.text_apply_btn.isEnabled()
    QTest.mouseClick(view.text_apply_btn, Qt.LeftButton)
    _pump(app, 400)
    assert len(requests) == 1
    assert requests[0].requires_preview_token is True and requests[0].plan_token
    assert REPLACEMENT in model.doc[0].get_text()
    outcome = model.last_commit_outcome
    assert outcome is not None and outcome.fallback_chain == (), outcome
    assert view.text_editor is None
    assert modals == []


@pytest.mark.parametrize(
    "launched",
    [{"TEXT_COMMIT_ENGINE": "legacy"}, {"TEXT_COMMIT_ENGINE": "shadow"}],
    indirect=True,
)
def test_a_stored_retired_engine_launches_the_shipped_configuration(launched, caplog) -> None:
    """RETIREMENT PIN (plans/retire-legacy-engine-option.md, ruling O5): a
    stored ``TEXT_COMMIT_ENGINE=legacy|shadow`` (the retired kill switch)
    never crashes the launch.  The composition root logs a warning naming the
    retired value and composes the shipped configuration: the tiered engine,
    the plan preview with its token gate, and an Apply that commits the
    verified preview by token."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, view, model, _controller, modals = launched
    retired = os.environ["TEXT_COMMIT_ENGINE"]
    warnings = [
        r.getMessage() for r in caplog.get_records("setup") if r.levelname == "WARNING"
    ]
    assert any(
        "TEXT_COMMIT_ENGINE" in m and repr(retired) in m and "retired" in m for m in warnings
    ), warnings
    settings = model.text_commit_settings
    assert (settings.engine, settings.max_tier, settings.preview) == ("tiered", 1, "plan")
    assert getattr(view, "_text_plan_preview_required", None) is True
    requests: list = []
    view.sig_edit_text.connect(requests.append)
    editor = _open_editor(app, view, model)
    _type(editor, REPLACEMENT)
    assert _wait(app, lambda: editor.current_plan_token() is not None, 120.0), "no token"
    assert view.text_apply_btn.isEnabled()
    QTest.mouseClick(view.text_apply_btn, Qt.LeftButton)
    _pump(app, 400)
    assert len(requests) == 1
    assert requests[0].requires_preview_token is True and requests[0].plan_token
    assert REPLACEMENT in model.doc[0].get_text()
    outcome = model.last_commit_outcome
    assert outcome is not None and outcome.fallback_chain == (), outcome
    assert view.text_editor is None
    assert modals == []


@pytest.mark.parametrize("launched", [{"TEXT_COMMIT_PREVIEW": "legacy"}], indirect=True)
def test_a_stored_legacy_preview_launches_the_plan_preview(launched, caplog) -> None:
    """RETIREMENT PIN (plans/retire-legacy-engine-option.md, slice 2, ruling
    O3): a stored ``TEXT_COMMIT_PREVIEW=legacy`` never crashes the launch.  The
    composition root logs a warning naming the retired value and composes the
    plan preview: the Controller turns the Apply token gate on."""
    _app, view, model, _controller, modals = launched
    warnings = [
        r.getMessage() for r in caplog.get_records("setup") if r.levelname == "WARNING"
    ]
    assert any(
        "TEXT_COMMIT_PREVIEW" in m and repr("legacy") in m and "retired" in m for m in warnings
    ), warnings
    assert model.text_commit_settings.preview == "plan"
    assert getattr(view, "_text_plan_preview_required", None) is True
    assert modals == []


def test_tokenless_view_is_the_lever_and_must_run_after_activate(launched) -> None:
    """The slice-2 test lever (``preview_levers.tokenless_view``): the
    Controller turns the gate on in ``activate()``, so the helper only holds
    when it runs AFTER wiring, and again after a re-activation."""
    from preview_levers import tokenless_view

    _app, view, _model, controller, modals = launched
    manager = view._ensure_text_edit_manager()
    assert getattr(view, "_text_plan_preview_required", None) is True
    assert manager._plan_preview_applies("edit_existing") is True

    assert tokenless_view(view) is view
    assert getattr(view, "_text_plan_preview_required", None) is False
    assert manager._plan_preview_applies("edit_existing") is False

    # A re-activation re-runs the Controller's wiring (``require_token(True)``
    # in ``activate()``; simulated by that exact call, since a real second
    # ``activate()`` would double-connect every signal) and turns the gate
    # back on: the helper has to be called again.
    controller.view.set_text_plan_preview_required(True)
    assert manager._plan_preview_applies("edit_existing") is True
    tokenless_view(view)
    assert manager._plan_preview_applies("edit_existing") is False
    assert modals == []
