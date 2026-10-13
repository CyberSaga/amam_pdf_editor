"""Batch 2 of the 34_適應畫面 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PAPER_SHADE, PEACH, TEAL, block_arrow_d, hamster48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：往內的箭頭、臉與手",
        "取景角、紙、倉鼠的位置都對；左上與右下角還空著，倉鼠沒有臉。",
        "兩支青綠小箭頭（1.1 px 深藍框）：左上朝右下、右下朝左上，尖端停在紙角外 1 格；倉鼠補臉、右手搭到紙的左緣；紙內側淡陰影。",
        tempo="normal")
arrow = block_arrow_d(0, 7.6, 0, 2.6, 6.2, 3.4)
s.add("arrow_tl", "path", "badge", d=arrow, fill=TEAL, stroke=INK, stroke_width=1.1, stroke_linejoin="round",
      transform="translate(6.6 6.6) rotate(45)", anim="fill")
s.add("arrow_br", "path", "badge", d=arrow, fill=TEAL, stroke=INK, stroke_width=1.1, stroke_linejoin="round",
      transform="translate(41.4 41.4) rotate(225)", anim="fill")
s.add("sheet_shade", "path", "object_fx", d="M33.25 17.25V36.1Q33.25 37.25 32.1 37.25H16.4", fill="none",
      stroke=PAPER_SHADE, stroke_width=1.5, stroke_linecap="round", anim="draw")
s.add("hm_arm", "ellipse", "front", cx=13.8, cy=35.2, rx=2.4, ry=1.3, fill=PEACH, stroke=INK, stroke_width=1.0,
      transform="rotate(-25 13.8 35.2)", anim="pop", z=s.elements["hm_belly"]["z"] + 0.5)
hamster48(s, "hm", 9.4, 30.8, 5.6, 4.8, layer="front", k=0.58, parts=("face",))
s.commit()
