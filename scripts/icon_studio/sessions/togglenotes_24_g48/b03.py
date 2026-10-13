"""Batch 3 of the 24_顯示-隱藏註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

import math

from geo import smooth_d
from studio import Studio


def lid_offset_d(d: float, t0: float, t1: float, n: int = 7) -> str:
    """Curve running ``d`` inside the top lid (M4.75 25 Q22 6.5 39.25 25), sampled for t0..t1."""
    pts = []
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        x, y = 4.75 + 34.5 * t, 25 - 37 * t * (1 - t)
        nx, ny = 37 * (1 - 2 * t), 34.5
        ln = math.hypot(nx, ny)
        pts.append((x + d * nx / ln, y + d * ny / ln))
    return smooth_d(pts)


s = Studio.open()
s.begin(6, "48 格：眼瞼陰影貼齊框線",
        "放大看：上眼瞼內側的陰影是另畫的一條二次曲線，中段壓在眼瞼框線上（眼瞼看起來變細），兩端又離開框線，像第二條眼皮。"
        "草稿比了不加陰影、長、短三種：沿著眼瞼內緣平行、只留中段的短陰影最自然。",
        "陰影改成和上眼瞼平行的曲線（往內 2 格，1.5 px 寬的上緣剛好貼著框線內緣），只畫 t 0.22–0.78 的中段。",
        tempo="normal")
s.look((8, 14, 28, 10), "陰影壓到眼瞼、像第二條眼皮")
s.mod("lid_shade", note="改成貼齊眼瞼內緣的平行短弧", d=lid_offset_d(2.0, 0.22, 0.78))
s.commit()
