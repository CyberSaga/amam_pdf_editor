"""Ribbon icons decode each PNG once across sizes (perf pass 2026-11-04).

Startup builds the ribbon at 32 px (to measure the text-under-icon width) and
then at 28 px (icon-only preset): ``load_icon`` decoded every PNG once per
size, ~1 ms each, about a third of the time from process start to first window.
"""
from __future__ import annotations

import pytest

import view.icons as icons


@pytest.fixture
def fresh_icon_caches(qapp):
    for name in ("_icon_cache", "_source_pixmap_cache"):
        cache = getattr(icons, name, None)
        if cache is not None:
            cache.clear()
    yield
    for name in ("_icon_cache", "_source_pixmap_cache"):
        cache = getattr(icons, name, None)
        if cache is not None:
            cache.clear()


def test_each_png_is_decoded_once_across_sizes(fresh_icon_caches, monkeypatch) -> None:
    real_qpixmap = icons.QPixmap
    decoded: list[str] = []

    def counting_qpixmap(*args):
        if args and isinstance(args[0], str):
            decoded.append(args[0])
        return real_qpixmap(*args)

    monkeypatch.setattr(icons, "QPixmap", counting_qpixmap)
    labels = list(icons.ACTION_ICON_MAP)
    for size in (32, 28, 24):
        for label in labels:
            assert not icons.load_icon(label, size=size).isNull()

    assert len(decoded) == len(labels)
    assert len(set(decoded)) == len(labels)


@pytest.mark.parametrize("size", (24, 28, 32))
def test_icon_pixels_match_a_fresh_decode_and_smooth_scale(fresh_icon_caches, size) -> None:
    """Regression guard: same pixels as decoding the file and smooth-scaling it."""
    from PySide6.QtCore import Qt

    for label, filename in icons.ACTION_ICON_MAP.items():
        icons.load_icon(label, size=28)  # warm a different size first
        icon = icons.load_icon(label, size=size)
        expected = icons.QPixmap(str(icons.ICON_DIR / filename)).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        actual = icon.pixmap(expected.size())
        assert actual.toImage() == expected.toImage(), label
