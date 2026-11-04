"""A zoom rebuilds the page scene but not the bookmark panel (perf pass 2026-11-04).

``change_scale`` (wheel, combo, pinch, fit, F5) and the pinch re-render reach
``_rebuild_continuous_scene``, which also re-read the whole outline
(``load_toc``): ~80 % of the synchronous zoom handler on a document with a few
hundred bookmarks, for an outline a zoom cannot change.  Structural rebuilds
(page delete / insert / reorder / undo) still reload it.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import main as main_module
import utils.preferences as preferences


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


def _make_pdf_with_toc(path: Path, pages: int = 6) -> Path:
    doc = fitz.open()
    try:
        for index in range(pages):
            doc.new_page(width=595, height=842).insert_text((72, 100), f"Page {index + 1}", fontsize=12)
        doc.set_toc([[1, f"Chapter {index + 1}", index + 1] for index in range(pages)])
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def app_with_toc(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "_make_default_store", _MemoryStore)
    path = _make_pdf_with_toc(tmp_path / "zoom-toc.pdf")
    startup = main_module.run(argv=[str(path)], start_event_loop=False)
    toc_reads: list[int] = []
    model = startup["model"]
    real_rows = model.get_toc_rows

    def counting_rows():
        toc_reads.append(1)
        return real_rows()

    monkeypatch.setattr(model, "get_toc_rows", counting_rows)
    try:
        yield startup, toc_reads
    finally:
        startup["view"].close()
        model.close()
        startup["app"].setStyleSheet("")
        startup["app"].quit()


def _bookmark_count(view) -> int:
    return view.bookmark_tree.topLevelItemCount()


def test_zoom_rebuilds_the_scene_without_rereading_the_outline(app_with_toc) -> None:
    startup, toc_reads = app_with_toc
    view = startup["view"]
    height_before = view.page_heights[0]
    bookmarks_before = _bookmark_count(view)

    view._zoom_relative(1.5)

    assert view.page_heights[0] == pytest.approx(height_before * 1.5, rel=1e-3)
    assert toc_reads == []
    assert _bookmark_count(view) == bookmarks_before == 6


def test_pinch_rerender_does_not_reread_the_outline(app_with_toc) -> None:
    startup, toc_reads = app_with_toc
    view, controller = startup["view"], startup["controller"]
    view.scale = view.scale * 1.25

    controller._on_request_rerender()

    assert toc_reads == []
    assert _bookmark_count(view) == 6


def test_structural_rebuild_still_reloads_the_outline(app_with_toc) -> None:
    """Regression guard: page delete / insert / reorder / undo rebuild through
    the same method and must keep refreshing the bookmark panel."""
    startup, toc_reads = app_with_toc
    controller = startup["controller"]

    controller._rebuild_continuous_scene(0)

    assert toc_reads == [1]
