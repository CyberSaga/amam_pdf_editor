"""Batch 3 of the 07_操作物件 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PEACH, hamster_bean_px, pix_d
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
s.begin(6, "24 格：倉鼠換成圓胖的那隻",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。24 格這隻是逐像素的方盒頭配直邊身體（BEAN24 加腳），兩格斜角耳朵像貓耳；"
        "48 格已改成儲存構造的圓胖倉鼠，選取框也下移了。",
        "改用同一套構造縮到 24 格（k 0.5、身體 13、cx 19）：圓頂頭、耳朵、身體與白色口鼻／肚子用 1 px 外框的向量（輪廓才圓），"
        "眼睛 2×2 帶反光、鼻子與腮紅放整數像素；選取框和控點跟 48 格一樣下移 1 列（中心線 y 5/16）；"
        "2 格桃色手臂移到胸口第 16 列，仍伸進右下控點。",
        tempo="normal")
s.look((12, 8, 12, 15), "方盒倉鼠像貓")
for eid in [e for e in list(s.elements) if e.startswith("hm_")] + ["paw"]:
    s.rm(eid, note="舊倉鼠擦掉" if eid == "hm_peach" else None)
s.mod("frame", note="選取框下移 1 列", d="M2.5 5.5H12.5V16.5H2.5Z")
HANDLE = ["NNNNN", "NTTTN", "NTTTN", "NTTTN", "NNNNN"]
rows = stamp(24, [(x - 2, y - 2, HANDLE) for x, y in ((2, 5), (12, 5), (2, 16), (12, 16))])
s.mod("handles_ink", d=pix_d(rows, "N"))
s.mod("handles_fill", d=pix_d(rows, "T"))
hamster_bean_px(s, "hb", 24, 19, 14.35, 0.5, layer="hamster", body=13)
s.add("hp_arm", "path", "front", d=pix_d(["PP"], "P", 13, 16), fill=PEACH, anim="pop")
s.commit()
