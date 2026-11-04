"""Re-rendering the SAME session keeps its finished thumbnails (perf pass 2026-11-04).

``_render_active_session`` serves tab switches (the shared thumbnail list must
show the new session) and same-session re-renders: leaving F5 restores the
pre-fullscreen zoom through it, and closing a background tab re-renders the
still-active one.  It cleared the list and re-rendered every thumbnail in
both cases; on a 370-page file that background pass made leaving F5 take
~0.6 s.
"""
from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest

import main as main_module
import utils.preferences as preferences

PAGES = 12


class _MemoryStore:
    def __init__(self, *_args) -> None:
        self._data: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self._data.get(key, default)

    def setValue(self, key, value) -> None:
        self._data[key] = value

    def remove(self, key) -> None:
        self._data.pop(key, None)

    def contains(self, key) -> bool:
        return key in self._data

    def sync(self) -> None:
        return None


def _make_pdf(path: Path, pages: int) -> Path:
    doc = fitz.open()
    try:
        for index in range(pages):
            doc.new_page(width=595, height=842).insert_text((72, 100), f"Page {index + 1}", fontsize=24)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _pump_until(app, predicate, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _pump(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def _thumbnails_complete(controller, view) -> bool:
    sid = controller.model.get_active_session_id()
    gen = controller._thumb_gen_by_session.get(sid)
    if gen is None or controller._thumbnail_rows_done(sid, gen) < len(controller.model.doc):
        return False
    return all(not view.thumbnail_list.item(row).icon().isNull() for row in range(view.thumbnail_list.count()))


@pytest.fixture
def running_app(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "_make_default_store", _MemoryStore)
    path = _make_pdf(tmp_path / "long.pdf", PAGES)
    startup = main_module.run(argv=[str(path)], start_event_loop=False)
    app, view, controller = startup["app"], startup["view"], startup["controller"]
    assert _pump_until(app, lambda: _thumbnails_complete(controller, view))
    resets: list[int] = []
    rendered: list[int] = []
    real_reset = view.set_thumbnail_placeholders
    real_consume = controller._consume_thumbnail_images

    def counting_reset(total):
        resets.append(total)
        return real_reset(total)

    def counting_consume(start, images):
        rendered.extend(range(start, start + len(images)))
        return real_consume(start, images)

    monkeypatch.setattr(view, "set_thumbnail_placeholders", counting_reset)
    monkeypatch.setattr(controller, "_consume_thumbnail_images", counting_consume)
    monkeypatch.setattr(controller._thumbnail_coordinator, "_batch_consumer", counting_consume)
    try:
        yield startup, tmp_path, resets, rendered
    finally:
        view.close()
        for ctx in startup.get("secondary_windows", []):
            ctx["model"].close()
        startup["model"].close()
        app.setStyleSheet("")
        app.quit()


def test_leaving_fullscreen_keeps_the_finished_thumbnails(running_app) -> None:
    startup, _tmp, resets, rendered = running_app
    app, view, controller = startup["app"], startup["view"], startup["controller"]

    controller.enter_fullscreen()
    _pump(app, 0.3)
    controller.exit_fullscreen()
    _pump(app, 0.5)

    assert not view.is_fullscreen_active()
    assert resets == []
    assert rendered == []
    assert view.thumbnail_list.count() == PAGES
    assert _thumbnails_complete(controller, view)


def test_switching_tabs_still_repopulates_the_shared_list(running_app) -> None:
    """Regression guard: another session's thumbnails replace the list, and
    coming back renders this session's again."""
    startup, tmp_path, resets, rendered = running_app
    app, view, controller = startup["app"], startup["view"], startup["controller"]
    other = _make_pdf(tmp_path / "other.pdf", 3)

    controller.open_pdf(str(other))
    assert _pump_until(app, lambda: _thumbnails_complete(controller, view))
    assert resets[-1] == 3
    view.document_tab_bar.setCurrentIndex(0)
    assert _pump_until(app, lambda: view.thumbnail_list.count() == PAGES and _thumbnails_complete(controller, view))

    assert resets[-1] == PAGES
    assert len([row for row in rendered if row < PAGES]) >= PAGES
