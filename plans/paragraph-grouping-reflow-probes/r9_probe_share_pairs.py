"""Round-9 probe (F2): where the real space glyphs of a paragraph sit, and the share pairs per line and class.

Usage: python -I r9_probe_share_pairs.py <pdf> [block ...]
Prints character classes only (C cjk, P cjk punctuation, L latin/digit, S space, s synthetic space), never text.
Lead-in of a pair = origin x of the right char - bbox x1 of the left char (rawdict bbox x1 = origin + advance).
"""
from __future__ import annotations

import statistics
import sys
import unicodedata

import fitz


def cls(ch: dict) -> str:
    c = ch["c"]
    if c.isspace():
        return "s" if ch.get("synthetic") else "S"
    if unicodedata.east_asian_width(c) in ("W", "F"):
        return "P" if unicodedata.category(c).startswith("P") else "C"
    return "L"


def main() -> None:
    doc = fitz.open(sys.argv[1])
    blocks = [int(a) for a in sys.argv[2:]] or [18, 19, 21]
    d = doc[0].get_text("rawdict")
    for bi in blocks:
        lines = d["blocks"][bi]["lines"]
        print(f"== block {bi}: {len(lines)} lines")
        for li, ln in enumerate(lines):
            chars = [ch for sp in ln["spans"] for ch in sp["chars"]]
            while chars and chars[-1]["c"].isspace():
                chars.pop()
            if not chars:
                print(f"L{li} (whitespace only)")
                continue
            kinds = [cls(ch) for ch in chars]
            lead: dict[str, list[float]] = {"cjk": [], "space": []}
            for i in range(1, len(chars)):
                gap = chars[i]["origin"][0] - chars[i - 1]["bbox"][2]
                if kinds[i - 1] == "S":
                    lead["space"].append(gap)
                elif kinds[i - 1] in "CP" and kinds[i] in "CP":
                    lead["cjk"].append(gap)
            parts = []
            for name, vals in lead.items():
                if vals:
                    parts.append(
                        f"{name} n={len(vals)} mean={statistics.fmean(vals):+.3f} "
                        f"med={statistics.median(vals):+.3f} min={min(vals):+.3f} max={max(vals):+.3f}"
                    )
                else:
                    parts.append(f"{name} n=0")
            spaces = [i for i, k in enumerate(kinds) if k in "Ss"]
            print(
                f"L{li} start={chars[0]['origin'][0]:.2f} end={chars[-1]['bbox'][2]:.2f} n={len(chars)} "
                f"spaces@{[(i, kinds[i], kinds[i - 1] if i else '^', kinds[i + 1] if i + 1 < len(kinds) else '$') for i in spaces]}"
            )
            print("   " + " | ".join(parts))
            print("   " + "".join(kinds))


main()
