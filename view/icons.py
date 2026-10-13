"""Toolbar icon loading and the action-text -> PNG-filename mapping.

Icons live in ``view/resources/function_icons/`` as numbered PNGs. The
toolbar actions are created with Traditional-Chinese labels, so the mapping is
keyed on that label text and :func:`load_icon` takes a label (not a filename).

SVG first, per device pixel: ``function_icons/svg/`` may hold pixel-grid
designs (``03_儲存_16.svg``, ``_24``, ``_48``) and a large design (``03_儲存.svg``).
:func:`load_icon` renders one pixmap per display scale factor (100-200 % plus
the current screens' ratios), each from the design that suits that pixel size
(:func:`svg_design_path`), so a 24 px icon on a 150 % screen is a real 36 px
render instead of an upscaled 24 px pixmap. PNG-only icons are likewise scaled
from their large source per scale factor, and an SVG that is missing or
unreadable falls back to the PNG. Shipped SVGs must stay QtSvg-safe (no
filters, masks, clip paths or CSS); see ``test_shipped_svg_icons_are_qtsvg_safe``.

Qt imports are wrapped in ``try/except ImportError`` so the pure-Python parts
(:data:`ICON_DIR`, :data:`ACTION_ICON_MAP`) stay importable in a headless test
environment that has no PySide6.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RESOURCES_DIR: Path = Path(__file__).resolve().parent / "resources"

ICON_DIR: Path = _RESOURCES_DIR / "function_icons"

# Optional SVG sources; same stem as the mapped PNG (03_儲存.png -> svg/03_儲存.svg).
SVG_ICON_DIR: Path = ICON_DIR / "svg"

# (exclusive device-pixel bound, grid) pairs: below 20 px use <stem>_16.svg, below
# 36 px <stem>_24.svg, below 96 px <stem>_48.svg, else the large <stem>.svg. A
# missing design falls through to the next larger one, then the nearest smaller.
SVG_GRID_BOUNDS: tuple[tuple[int, int], ...] = ((20, 16), (36, 24), (96, 48))

# Display scale factors every icon is rendered for (the common Windows 100-200 %
# steps); the ratios of the screens present at load time (e.g. 250 %, 300 %) are
# added on top, so only a screen attached later at an unusual ratio gets a
# rescaled pixmap.
ICON_SCALES: tuple[float, ...] = (1.0, 1.25, 1.5, 1.75, 2.0)

# Application/window icon (title bar, taskbar). A multi-resolution .ico so Qt
# can pick the right size per DPI.
APP_ICON_PATH: Path = _RESOURCES_DIR / "app_icon.ico"

# Action label text -> PNG filename (33 ribbon actions).
ACTION_ICON_MAP: dict[str, str] = {
    "開啟": "01_開啟.png",
    "列印": "02_列印.png",
    "儲存": "03_儲存.png",
    "另存新檔": "04_另存新檔.png",
    "另存為最佳化的副本": "05_另存為最佳化的副本.png",
    "瀏覽模式": "06_瀏覽模式.png",
    "操作物件": "07_操作物件.png",
    "復原": "08_復原.png",
    "重做": "09_重做.png",
    "全螢幕": "10_全螢幕.png",
    "縮圖": "11_縮圖.png",
    "搜尋": "12_搜尋.png",
    "快照": "13_快照.png",
    "編輯文字": "14_編輯文字.png",
    "新增文字框": "15_新增文字框.png",
    "矩形": "16_矩形.png",
    "螢光筆": "17_螢光筆.png",
    "新增註解": "18_新增註解.png",
    "插入圖片": "19_插入圖片.png",
    "貼上圖片": "20_貼上圖片.png",
    "註解列表": "21_註解列表.png",
    "添加浮水印": "22_添加浮水印.png",
    "浮水印列表": "23_浮水印列表.png",
    "顯示/隱藏註解": "24_顯示-隱藏註解.png",
    "刪除頁": "25_刪除頁.png",
    "旋轉頁": "26_旋轉頁.png",
    "匯出頁": "27_匯出頁.png",
    "插入空白頁": "28_插入空白頁.png",
    "從檔案插入頁": "29_從檔案插入頁.png",
    "合併PDF": "30_合併PDF.png",
    "OCR（文字辨識）": "31_OCR（文字辨識）.png",
    # Key is the toolbar action label (拉正頁面); the asset is named 拉正PDF頁面.
    "拉正頁面": "33_拉正PDF頁面.png",
    "適應畫面": "34_適應畫面.png",
}


def svg_icon_path(label: str) -> Path | None:
    """Return the most detailed SVG design of ``label`` (large, else the largest grid), or ``None``."""
    return svg_design_path(label, SVG_GRID_BOUNDS[-1][0])


def svg_design_path(label: str, px: int) -> Path | None:
    """Return the SVG design to rasterize ``label`` at ``px`` device pixels, or ``None``.

    Prefers the smallest grid drawn for ``px`` or larger, then the large design, then
    the nearest smaller grid: most icons have no large design, and above 96 px their
    48 px design (still vector) beats the PNG card art.
    """
    filename = ACTION_ICON_MAP.get(label)
    if filename is None:
        return None
    stem = Path(filename).stem
    larger = [f"{stem}_{grid}.svg" for bound, grid in SVG_GRID_BOUNDS if px < bound]
    smaller = [f"{stem}_{grid}.svg" for bound, grid in reversed(SVG_GRID_BOUNDS) if px >= bound]
    for name in [*larger, f"{stem}.svg", *smaller]:
        path = SVG_ICON_DIR / name
        if path.is_file():
            return path
    return None


def icon_source_path(label: str) -> Path | None:
    """Return the preferred icon file for ``label``: its SVG if present, else its PNG."""
    filename = ACTION_ICON_MAP.get(label)
    if filename is None:
        return None
    return svg_icon_path(label) or ICON_DIR / filename


# Qt is optional at import time so the map above can be tested headless.
try:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
except ImportError:  # pragma: no cover - exercised only in headless map-only tests
    pass
else:
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:  # pragma: no cover - QtSvg absent: PNG icons only
        QSvgRenderer = None

    _icon_cache: dict[tuple[str, int], QIcon] = {}
    # Decoded PNG sources, shared by every size of the same icon.
    _png_cache: dict[Path, QPixmap | None] = {}

    def _render_svg(path: Path, px: int) -> QPixmap | None:
        """Rasterize ``path`` to a ``px`` x ``px`` pixmap; ``None`` if it cannot be read."""
        if QSvgRenderer is None:
            return None
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None
        side = renderer.viewBoxF().width() or float(px)
        # Grid designs are drawn for these sizes and render directly; a large design
        # renders at up to 4x and downsamples, since its hairlines alias at 24 px.
        render_px = px if side <= 2 * px else int(min(side, 4 * px))
        image = QImage(render_px, render_px, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, render_px, render_px))
        painter.end()
        if render_px != px:
            image = image.scaled(
                px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        return QPixmap.fromImage(image)

    def _device_scales() -> list[float]:
        """Scale factors to render: the fixed set plus every screen's current ratio."""
        scales = set(ICON_SCALES)
        if QGuiApplication.instance() is not None:
            scales.update(screen.devicePixelRatio() for screen in QGuiApplication.screens())
        return sorted(scales)

    def _read_pixmap(path: Path) -> QPixmap | None:
        """Load the bitmap at ``path``; ``None`` if it is missing or unreadable."""
        if not path.is_file():
            return None
        pixmap = QPixmap(str(path))
        return None if pixmap.isNull() else pixmap

    def load_icon(label: str, size: int = 24) -> QIcon:
        """Return a :class:`QIcon` for a ribbon action ``label`` at ``size`` logical px.

        The icon holds one pixmap per display scale factor (devicePixelRatio set),
        so Qt paints a native-resolution render on HiDPI screens. Each comes
        from the SVG design suited to its pixel size, else from the PNG.
        Results are cached by (label, size) so repeated calls (e.g. on
        window-state toggles) skip disk I/O and rendering entirely.
        Returns a null :class:`QIcon` for an unknown label or a missing file.
        """
        key = (label, size)
        cached = _icon_cache.get(key)
        if cached is not None:
            return cached
        filename = ACTION_ICON_MAP.get(label)
        if filename is None:
            return QIcon()
        icon = QIcon()
        png_path = ICON_DIR / filename
        unreadable: set[Path] = set()
        for scale in _device_scales():
            px = max(1, round(size * scale))
            pixmap = None
            design = svg_design_path(label, px)
            if design is not None and design not in unreadable:
                pixmap = _render_svg(design, px)
                if pixmap is None:
                    unreadable.add(design)
                    logger.warning("SVG icon unreadable, falling back to PNG: %s", design)
            if pixmap is None:
                if png_path not in _png_cache:
                    _png_cache[png_path] = _read_pixmap(png_path)
                png = _png_cache[png_path]
                if png is None:
                    continue
                pixmap = png.scaled(
                    px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap)
        if icon.isNull():
            return QIcon()
        _icon_cache[key] = icon
        return icon

    def load_app_icon() -> QIcon:
        """Return the application/window :class:`QIcon` from :data:`APP_ICON_PATH`.

        Loads the multi-resolution ``.ico`` directly (Qt selects the per-DPI
        size). Returns a null :class:`QIcon` when the asset is missing so callers
        can assign the result unconditionally.
        """
        if not APP_ICON_PATH.is_file():
            logger.warning("Application icon is unavailable: %s", APP_ICON_PATH)
            return QIcon()
        icon = QIcon(str(APP_ICON_PATH))
        if icon.isNull():
            return QIcon()
        return icon
