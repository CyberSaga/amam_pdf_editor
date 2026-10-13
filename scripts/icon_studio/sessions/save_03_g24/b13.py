"""Batch 13 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(6, "24 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。這張的耳朵是 2 格寬的深藍耳尖加一列 2 格粉紅（2×1），"
        "窗口只有 10×7 格、上面就是窗框，耳朵沒辦法再往上長；48 格的大耳朵已經碰到窗框兩側。",
        "耳朵改成 3 格寬、3 列高：耳尖深藍 3 格，粉紅內耳 3×2（第 12、13 列），兩耳之間留 2 格頭頂（第 12 列深藍線、第 13 列桃色）；"
        "外側 1 格深藍框不動。寬和高都是 1.5 倍、粉紅面積 3 倍，和 48 格碰到窗框的大耳朵一致。",
        tempo="normal")
s.look((7, 11, 10, 3), "耳朵 2×1 粉紅太小")
s.mod("face_outline", note="耳尖 3 格寬、頭頂線收成 2 格",
      d=rects((8, 11, 3, 1), (13, 11, 3, 1), (7, 12, 1, 2), (16, 12, 1, 2), (11, 12, 2, 1)))
s.mod("ears_inner", note="內耳 3×2", d=rects((8, 12, 3, 2), (13, 12, 3, 2)))
s.mod("face_peach", d=rects((11, 13, 2, 1), (7, 14, 10, 2)))
s.commit()
