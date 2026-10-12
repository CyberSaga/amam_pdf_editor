"""Batch 7 of the 03_儲存 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(4, "16 格：補上 48 版的本體光影",
        "臉部恢復杏色主體、兩隻反光眼睛清楚。和 24、48 版並排時，16 格的紫色本體是唯一完全平塗的一個。",
        "左上內角 2 格白色 45% 高光、右側與底部內緣 1 格深紫 35% 背光，做出和 48 版相同的受光方向。",
        tempo="normal")
s.add("gloss", "path", "glint", d=rects((2, 2, 1, 2)), fill="#FFFFFF", fill_opacity=0.45, anim="pop")
s.add("shade", "path", "body_fx", d=rects((13, 5, 1, 8), (2, 13, 12, 1)), fill="#4A3F98", fill_opacity=0.32, anim="fill")
s.commit()
