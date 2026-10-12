"""Pixel-level review of small-grid icon SVGs, rasterized by QtSvg (the app's renderer).

    .venv/bin/python scripts/icon_studio/pixel_review.py ICON.svg --grid 24 --out sheet.png \
        [--compare OTHER.svg ...] [--png OLD.png]

Row per source: magnified QtSvg renders at 1x / 1.25x / 1.5x / 2x of the grid with a
pixel grid, then actual-size tiles on light and dark toolbar backgrounds.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

SCALES = (1.0, 1.25, 1.5, 2.0)
LIGHT, DARK = QColor("#F3F2F8"), QColor("#2B2A36")


def render(path: Path, px: int) -> QImage:
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if path.suffix == ".png":
        src = QImage(str(path)).scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.drawImage(0, 0, src)
    else:
        r = QSvgRenderer(str(path))
        side = r.viewBoxF().width()
        if side > 2 * px:  # big designs: render large, then downsample like load_icon
            big = render_direct(r, max(px, min(int(side), 4 * px)))
            p.drawImage(0, 0, big.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            r.render(p, QRectF(0, 0, px, px))
    p.end()
    return img


def render_direct(r: QSvgRenderer, px: int) -> QImage:
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    return img


def magnified(img: QImage, cell: int, bg: QColor) -> QImage:
    w = img.width()
    out = QImage(w * cell + 1, w * cell + 1, QImage.Format.Format_ARGB32)
    out.fill(bg)
    p = QPainter(out)
    p.drawImage(QRectF(0, 0, w * cell, w * cell), img)  # nearest: no smooth hint
    p.setPen(QPen(QColor(128, 128, 140, 70), 1))
    for i in range(w + 1):
        p.drawLine(i * cell, 0, i * cell, w * cell)
        p.drawLine(0, i * cell, w * cell, i * cell)
    p.end()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("svg", type=Path)
    ap.add_argument("--grid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compare", type=Path, nargs="*", default=[])
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    QGuiApplication([])
    sources = [args.svg, *args.compare]
    big = 216
    row_h = big + 40 + int(args.grid * 2) + 24
    width = 160 + len(SCALES) * (big + 24) + 4 * (args.grid * 2 + 18) + 40
    sheet = QImage(width, 30 + row_h * len(sources), QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    p = QPainter(sheet)
    p.setFont(QFont("WenQuanYi Zen Hei", 11))
    for r, src in enumerate(sources):
        y = 30 + r * row_h
        name = src.name if r or not args.label else args.label
        p.setPen(QColor("#333"))
        p.drawText(8, y + 14, name[:22])
        x = 160
        for s in SCALES:
            px = round(args.grid * s)
            img = render(src, px)
            cell = max(1, big // px)
            p.drawImage(x, y, magnified(img, cell, LIGHT))
            if r == 0:
                p.drawText(x, 20, f"{s:g}x = {px}px")
            x += big + 24
        for s in (1.0, 2.0):
            px = round(args.grid * s)
            img = render(src, px)
            for bg in (LIGHT, DARK):
                tile = QImage(px + 12, px + 12, QImage.Format.Format_ARGB32)
                tile.fill(bg)
                tp = QPainter(tile)
                tp.drawImage(6, 6, img)
                tp.end()
                p.drawImage(x, y, tile)
                x += px + 18
    p.end()
    sheet.save(str(args.out))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
