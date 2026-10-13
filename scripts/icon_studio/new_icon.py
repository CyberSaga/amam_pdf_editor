"""Scaffold the three grid sessions (48 / 24 / 16) of one function icon.

    python3 scripts/icon_studio/new_icon.py 25_刪除頁 delpage_25 [--layers a,b,c]

Writes sessions/<slug>_g48|g24|g16/session.json: the 48 design maps the reference PNG
(``parts.ref_fit``), the 24 design uses the 48 SVG as reference and the 16 the 24 SVG;
each lists the larger designs as pixel-review comparison rows. Existing files are kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LAYERS = ["back", "hamster", "object", "object_fx", "front", "badge", "ink", "glint", "sketch", "guides"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem", help="icon file stem, e.g. 25_刪除頁")
    ap.add_argument("slug", help="session prefix, e.g. delpage_25")
    ap.add_argument("--title", help="action label (defaults to the ACTION_ICON_MAP key for the stem)")
    ap.add_argument("--layers", help="comma-separated paint order (default: the standard set)")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    from parts import ref_fit

    title = args.title
    if title is None:
        src = (REPO / "view" / "icons.py").read_text(encoding="utf-8")
        title = next(line.split('"')[1] for line in src.splitlines() if f'"{args.stem}.png"' in line)
    png = f"view/resources/function_icons/{args.stem}.png"
    svg = f"view/resources/function_icons/svg/{args.stem}"
    layers = args.layers.split(",") if args.layers else LAYERS
    cfgs = {
        48: {"reference": png, "ref_map": ref_fit(str(REPO / png), 48), "compare": [png]},
        24: {"reference": f"{svg}_48.svg", "ref_map": [0.046875, 0, 0], "compare": [f"{svg}_48.svg", png]},
        16: {"reference": f"{svg}_24.svg", "ref_map": [0.03125, 0, 0], "compare": [f"{svg}_24.svg", f"{svg}_48.svg"]},
    }
    for grid, extra in cfgs.items():
        target = HERE / "sessions" / f"{args.slug}_g{grid}" / "session.json"
        if target.exists():
            print("kept", target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg = {"title": title, "reference": extra["reference"], "ref_map": extra["ref_map"],
               "output": f"{svg}_{grid}.svg", "canvas": grid, "layers": layers, "compare": extra["compare"]}
        target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
