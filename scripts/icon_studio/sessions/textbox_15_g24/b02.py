"""Batch 2 of the 15_新增文字框 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEACH, hamster_face_px, pix_d, plus_px_d
from studio import Studio


def stamp(size, stamps):
    """One canvas-sized pixel map from (x, y, rows) stamps ('.' stays empty)."""
    grid = [["."] * size for _ in range(size)]
    for x, y, rows in stamps:
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch != ".":
                    grid[y + r][x + c] = ch
    return ["".join(row) for row in grid]


s = Studio.open()
s.begin(6, "24 格：倉鼠換成儲存的圓頂臉",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格這隻是 PEEK24 的方盒臉；48 格已改成儲存的圓頂頭。換成圓頂臉後，"
        "框上緣兩個控點之間只剩 10 格，k 0.5 的臉連外框要 10.5 格，兩頰會壓到控點。",
        "框左右各放寬 1 格（中心線 x 3/21），右上、左下控點跟著移；加號章往左 1 格（中心 (20, 19)）留在畫布內，"
        "T 右移 1 格回到框的正中；倉鼠用 hamster_face_px（k 0.5、cx 12、base 7.6），平底壓在框上緣線裡；"
        "兩格桃色手掌壓在框上緣第 8、15 欄。",
        tempo="normal")
s.look((4, 0, 16, 10), "方盒臉；控點之間太窄")
for eid in [e for e in list(s.elements) if e.startswith("hm_")] + ["paw_peach"]:
    s.rm(eid, note="舊倉鼠擦掉" if eid == "hm_peach" else None)
s.mod("box", note="框左右各放寬 1 格", d="M3.5 7.5H21.5V19.5H3.5Z")
HANDLE = ["NNNNN", "NTTTN", "NTTTN", "NTTTN", "NNNNN"]
rows = stamp(24, [(x - 2, y - 2, HANDLE) for x, y in ((3, 7), (21, 7), (3, 19))])
s.mod("handles_ink", d=pix_d(rows, "N"))
s.mod("handles_fill", d=pix_d(rows, "T"))
s.mod("badge_disc", note="加號章左移 1 格", cx=20)
s.mod("badge_plus", d=plus_px_d(20, 19, 2))
T = ["NNNNNN", "N.NN.N", "..NN..", "..NN..", "..NN..", "..NN..", ".NNNN."]
s.mod("glyph", note="T 回到框的正中", d=pix_d(T, "N", 10, 10))
hamster_face_px(s, "hf", 24, 12, 7.6, 0.5, layer="hamster")
s.add("hp", "path", "front", d=pix_d(["P......P"], "P", 8, 7), fill=PEACH, anim="pop")
s.commit()
