"""Real-size review of function icons, rendered the way the app picks designs.

    .venv/bin/python scripts/icon_studio/set_sheet.py --out sheet.png 03_儲存 01_開啟 ...

One row per icon: at each device size the design ``svg_design_path`` picks for it,
rasterized by ``view.icons._render_svg`` (QtSvg), on a light and a dark toolbar
background, followed by the reference PNG at 48 px. Use it every few icons to keep
line weights, hamster size and colour balance consistent across the set.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

SIZES = (16, 24, 28, 32, 36, 48, 56, 64)
LIGHT, DARK = QColor("#F3F2F8"), QColor("#2B2A36")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="+", help="icon stems such as 01_開啟")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    QGuiApplication([])
    from view import icons

    label_of = {Path(fn).stem: label for label, fn in icons.ACTION_ICON_MAP.items()}
    pad = 8
    row_h = 2 * (max(SIZES) + pad) + 6
    width = 120 + sum(s + pad for s in SIZES) + 48 + 3 * pad
    sheet = QImage(width, 24 + row_h * len(args.stems), QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    p = QPainter(sheet)
    p.setFont(QFont("WenQuanYi Zen Hei", 10))
    p.setPen(QColor("#333"))
    x = 120
    for s in SIZES:
        p.drawText(x, 16, f"{s}")
        x += s + pad
    p.drawText(x + pad, 16, "PNG")
    for r, stem in enumerate(args.stems):
        y0 = 24 + r * row_h
        label = label_of[stem]
        p.setPen(QColor("#333"))
        p.drawText(6, y0 + 20, stem[:14])
        for b, bg in enumerate((LIGHT, DARK)):
            y = y0 + b * (max(SIZES) + pad)
            p.fillRect(116, y - 2, width - 116, max(SIZES) + 4, bg)
            x = 120
            for s in SIZES:
                design = icons.svg_design_path(label, s)
                if design is not None:
                    pm = icons._render_svg(design, s)
                    p.drawImage(x, y, pm.toImage())
                x += s + pad
            png = QImage(str(icons.ICON_DIR / icons.ACTION_ICON_MAP[label])).scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawImage(x + pad, y, png)
    p.end()
    sheet.save(str(args.out))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
