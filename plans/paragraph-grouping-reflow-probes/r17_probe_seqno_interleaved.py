"""Round-17 probe (P14): does `get_bboxlog()[span seqno]` stay the span's own text entry when paths,
a clip, an inline image and invisible / stroked / clip-mode shows come before or between the spans?

Usage: python -I r17_probe_seqno_interleaved.py
Synthetic page, base-14 Helvetica. Prints, per texttrace span, its seqno, the code of the bboxlog
entry at that index, whether that code is a text code, and how much of the span's trace bbox the
entry (grown 2 pt) covers. The entry is the glyph INK box (a stroke-text entry is the ink grown by
10 x line width), the trace bbox is the advance x ascender/descender box, so neither encloses the
other: "own entry" = same index, text code, covers >= 50 % of the own trace bbox and more of it than
of any other span's (a `Tr 2` show is two spans with one bbox: twins are not "other").
A `Tr 7` show is expected in NEITHER list (the script prints whether it found one).
Not covered: shadings, tiling patterns, Form XObjects (P12 has a Form), embedded faces.
"""
from __future__ import annotations

import fitz

STREAM = b"""
0.5 g 50 700 40 20 re f
1 w 50 680 m 150 680 l S
q 200 640 200 60 re W n
BT /helv 20 Tf 1 0 0 1 210 660 Tm (Ag) Tj ET
Q
q 20 0 0 20 420 700 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI Q
0.2 g 300 600 30 30 re f
BT /helv 20 Tf 1 0 0 1 60 560 Tm (Bq) Tj ET
BT 3 Tr /helv 20 Tf 1 0 0 1 160 560 Tm (Cd) Tj ET
0 0 1 RG 2 w 50 540 m 300 540 l S
BT 0 Tr /helv 20 Tf 1 0 0 1 260 560 Tm (Ef) Tj ET
BT 1 Tr /helv 20 Tf 1 0 0 1 60 500 Tm (Gh) Tj ET
0.9 g 150 480 20 20 re f
q BT 7 Tr /helv 20 Tf 1 0 0 1 200 500 Tm (Ij) Tj ET 190 490 60 30 re f Q
BT 2 Tr /helv 20 Tf 1 0 0 1 300 500 Tm (Kl) Tj ET
"""


def main() -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((10, 10), " ", fontname="helv")  # registers /helv and creates the stream
    doc.update_stream(page.get_contents()[0], STREAM)
    page = doc.reload_page(page)
    log = page.get_bboxlog()
    print(fitz.__doc__.splitlines()[0])
    print("bboxlog:", [(i, e[0]) for i, e in enumerate(log)])
    spans = page.get_texttrace()
    boxes = [fitz.Rect(sp["bbox"]) for sp in spans]
    bad = 0
    for k, sp in enumerate(spans):
        text = "".join(chr(c[0]) for c in sp["chars"])
        s = sp["seqno"]
        entry = log[s] if 0 <= s < len(log) else None
        code = entry[0] if entry else None
        is_text = bool(code) and code.endswith("-text")
        own_cov = other_cov = 0.0
        if entry:
            box = fitz.Rect(entry[1]) + (-2, -2, 2, 2)
            own_cov = (box & boxes[k]).get_area() / boxes[k].get_area()
            other_cov = max(
                ((box & b).get_area() / b.get_area() for b in boxes if b != boxes[k]), default=0.0
            )
        own = is_text and own_cov >= 0.5 and own_cov > other_cov
        bad += not own
        print(
            f"span {text!r} type={sp['type']} seqno={s} entry={code} text_code={is_text} "
            f"covers_own={own_cov:.2f} covers_other={other_cov:.2f} own_entry={own} "
            f"entry_box={[round(v, 2) for v in entry[1]] if entry else None}"
        )
    clip_text = [sp for sp in spans if "".join(chr(c[0]) for c in sp["chars"]) == "Ij"]
    print(f"spans={len(spans)} not_own_entry={bad} tr7_in_texttrace={bool(clip_text)} "
          f"bboxlog_codes={sorted({e[0] for e in log})}")

main()
