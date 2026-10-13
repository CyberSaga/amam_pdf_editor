"""QtSvg review sheets for grid icon designs (run with the project venv, it needs PySide6).

    .venv/bin/python scripts/icon_studio/review.py realsize OUT.png 16,24,32,48 g16 a_16.svg g24 a_24.svg ...
    .venv/bin/python scripts/icon_studio/review.py variants OUT.png 24 A a.svg B b.svg [--cell 12]
    .venv/bin/python scripts/icon_studio/review.py zoom ICON.svg X Y W H --out crop.png [--k 12]

realsize  each design at the listed device sizes (QtSvg, antialiased), magnified ``--mag`` times
          with nearest-neighbour, on the light and the dark toolbar background: judge each design
          at its own size (16 at 16, 24 at 24-32, 48 at 48).
variants  candidate layouts side by side: a magnified 1x render with a pixel grid, then real-size
          tiles at 1x / 7/6x / 4/3x (the ribbon's 28 / 32 px at 100 %).
zoom      a magnified region of one SVG, rendered at ``k`` pixels per unit.
"""
from __future__ import annotations

import argparse
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

LIGHT, DARK = "#F3F2F8", "#2B2A36"


def render(path: str, px: int, bg: str | None = None) -> QImage:
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    if bg:
        img.fill(QColor(bg))
    else:
        img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(path).render(p, QRectF(0, 0, px, px))
    p.end()
    return img


def realsize(out: str, sizes: list[int], items: list[tuple[str, str]], mag: int) -> None:
    colw = max(sum(s * mag + 10 for s in sizes), 200)
    sheet = QImage(90 + colw * 2, 20 + len(items) * (max(sizes) * mag + 14), QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    p = QPainter(sheet)
    p.setFont(QFont("DejaVu Sans", 9))
    p.setPen(QColor("#333"))
    for r, (name, path) in enumerate(items):
        y = 20 + r * (max(sizes) * mag + 14)
        p.drawText(4, y + 14, name[:12])
        for b, bg in enumerate((LIGHT, DARK)):
            x = 90 + b * colw
            for s in sizes:
                p.drawImage(QRectF(x, y, s * mag, s * mag), render(path, s, bg))
                x += s * mag + 10
    x = 90
    for s in sizes:
        p.drawText(x, 14, f"{s}px x{mag}")
        x += s * mag + 10
    p.end()
    sheet.save(out)


def variants(out: str, grid: int, items: list[tuple[str, str]], cell: int) -> None:
    sizes = [grid, round(grid * 7 / 6), round(grid * 4 / 3)]
    colw = grid * cell + 20 + sum(s + 10 for s in sizes)
    sheet = QImage(colw * len(items), grid * cell + 50 + 2 * (max(sizes) + 8), QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    p = QPainter(sheet)
    p.setFont(QFont("DejaVu Sans", 9))
    for i, (name, path) in enumerate(items):
        x0 = i * colw
        p.setPen(QColor("#333"))
        p.drawText(x0 + 4, 14, name)
        p.drawImage(QRectF(x0 + 4, 20, grid * cell, grid * cell), render(path, grid, LIGHT))
        p.setPen(QPen(QColor(120, 120, 140, 60), 1))
        for k in range(grid + 1):
            p.drawLine(x0 + 4 + k * cell, 20, x0 + 4 + k * cell, 20 + grid * cell)
            p.drawLine(x0 + 4, 20 + k * cell, x0 + 4 + grid * cell, 20 + k * cell)
        y = 30 + grid * cell
        for b, bg in enumerate((LIGHT, DARK)):
            x = x0 + 4
            for s in sizes:
                p.drawImage(x, y + b * (max(sizes) + 8), render(path, s, bg))
                x += s + 10
    p.end()
    sheet.save(out)


def zoom(svg: str, box: list[float], k: float, out: str) -> None:
    r = QSvgRenderer(svg)
    side = r.viewBoxF().width()
    x, y, w, h = box
    img = QImage(int(w * k), int(h * k), QImage.Format.Format_ARGB32)
    img.fill(QColor(LIGHT))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(-x * k, -y * k, side * k, side * k))
    p.end()
    img.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("realsize")
    a.add_argument("out")
    a.add_argument("sizes")
    a.add_argument("items", nargs="+", help="name file.svg pairs")
    a.add_argument("--mag", type=int, default=4)
    b = sub.add_parser("variants")
    b.add_argument("out")
    b.add_argument("grid", type=int)
    b.add_argument("items", nargs="+", help="name file.svg pairs")
    b.add_argument("--cell", type=int, default=12)
    c = sub.add_parser("zoom")
    c.add_argument("svg")
    c.add_argument("box", type=float, nargs=4)
    c.add_argument("--k", type=float, default=12)
    c.add_argument("--out", required=True)
    args = ap.parse_args()
    QGuiApplication([])
    if args.cmd == "zoom":
        zoom(args.svg, args.box, args.k, args.out)
    else:
        items = list(zip(args.items[::2], args.items[1::2]))
        if args.cmd == "realsize":
            realsize(args.out, [int(v) for v in args.sizes.split(",")], items, args.mag)
        else:
            variants(args.out, args.grid, items, args.cell)
    print(getattr(args, "out", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
