"""Batch 2 of the 12_搜尋 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48
from studio import Studio

CX = CY = 18.5
TILT = f"rotate(45 {CX} {CY})"
s = Studio.open()
s.begin(5, "48 格：臉、肚子、反光與握柄",
        "色塊疊參考：鏡框、開口、握把的位置都對；鏡框比參考粗（深藍外框 + 內框），但開口和頭的比例一樣（頭寬約佔開口七成）。"
        "握柄在 2.5 px 框裡只剩 2 格紫灰，比參考瘦；倉鼠還沒有臉。",
        "握柄外寬 7→7.5；倉鼠補臉（k 0.7、跟頭一起轉 18°）與白肚子；鏡框左上一道白色反光弧、握柄上緣一道反光（0.55 透明度）；擦掉草稿。",
        tempo="normal")
s.look((30, 30, 16, 16), "握柄太瘦")
s.mod("grip", note="握柄加寬", d="M41 16H51.25A2.5 2.5 0 0 1 51.25 21H41A2.5 2.5 0 0 1 41 16Z")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.add("hm_belly", "ellipse", "hamster", cx=19.6, cy=27.6, rx=3.5, ry=4.2, fill=WHITE, transform="rotate(18 20.2 27)",
      anim="fill", z=s.elements["hm_body"]["z"] + 0.5)
hamster48(s, "hm", 18.0, 18.6, 6.8, 6.0, k=0.7, rot=18, parts=("face",))
s.add("ring_gloss", "path", "object_fx", d="M6.98 14.33A12.25 12.25 0 0 1 14.33 6.98", fill="none", stroke=WHITE,
      stroke_width=1.2, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("grip_gloss", "path", "object_fx", d="M42 18H49.5", fill="none", stroke=WHITE, stroke_width=1.2, stroke_opacity=0.55,
      stroke_linecap="round", transform=TILT, anim="draw")
s.commit(compare=True)
