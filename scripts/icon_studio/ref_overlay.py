"""Reference PNGs fitted onto the 48 grid, for measuring a composition before drawing it.

    python3 scripts/icon_studio/ref_overlay.py OUT.png 26_旋轉頁 27_匯出頁 ...

Each panel maps the icon's PNG with ``parts.ref_fit`` (card excluded, drawing centred with a
3 px margin) at 8 px per grid unit, with blue lines every 4 units and red every 12.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ICONS = HERE.parents[1] / "view" / "resources" / "function_icons"
sys.path.insert(0, str(HERE))

from parts import ref_fit  # noqa: E402

K = 8


def panel(stem: str) -> Image.Image:
    png = ICONS / f"{stem}.png"
    sc, dx, dy = ref_fit(str(png), 48)
    im = Image.open(png).convert("RGBA")
    big = im.resize((round(im.width * sc * K), round(im.height * sc * K)), Image.LANCZOS)
    can = Image.new("RGBA", (48 * K, 48 * K), (255, 255, 255, 255))
    can.alpha_composite(big, (round(dx * K), round(dy * K)))
    d = ImageDraw.Draw(can)
    for j in range(0, 49, 4):
        c = (220, 90, 90, 140) if j % 12 == 0 else (120, 160, 220, 110)
        d.line([(j * K, 0), (j * K, 48 * K)], fill=c)
        d.line([(0, j * K), (48 * K, j * K)], fill=c)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    d.text((4, 2), stem[:2], fill="black", font=font)
    return can


def main() -> int:
    out, stems = sys.argv[1], sys.argv[2:]
    cols = 2 if len(stems) > 1 else 1
    rows = (len(stems) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (48 * K + 10), rows * (48 * K + 10)), "white")
    for i, stem in enumerate(stems):
        sheet.paste(panel(stem).convert("RGB"), ((i % cols) * (48 * K + 10), (i // cols) * (48 * K + 10)))
    sheet.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
