"""Batch 1 of the 21_註解列表 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import FACE16, INK, PURPLE_LIGHT, TEAL, YELLOW, pixmap
from studio import Studio

BROWN = "#96602A"
LINE_PURPLE = "#4A478F"
s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：BEAN 倉鼠在左、黃框在上、淡紫框在左下最前、青綠框在右後，1 px 框、逐像素尾巴。16 格每個框只剩 5–7 格寬，"
        "三個向量框加尾巴會超過 16 個元素；草稿試了 6 種排法：兩個尾巴都貼齊外角時下緣左右對稱、像兩條腿。",
        "倉鼠臉用 16 格版（7×8）放 x 0–6；三個框畫成一張逐像素圖（每種顏色一條路徑，被擋住的部分直接不畫）：黃框 x 7–15、y 0–7，"
        "兩條咖啡色字線；淡紫框 x 5–11、y 7–15，上緣和黃框下緣共用一列，兩條深靛字線、左下角是新增註解 16 格那種貼齊外角的尾巴；"
        "青綠框 x 11–15 比紫框短，尾巴（鏡像）收在 y 13，避免左右對稱。",
        tempo="normal")
pixmap(s, "hm", FACE16, 0, 2, "hamster")
CLUSTER = [
    "........NNNNNNN.",
    ".......NYYYYYYYN",
    ".......NYbbbbbYN",
    ".......NYYYYYYYN",
    ".......NYbbbYYYN",
    ".......NYYYYYYYN",
    ".......NYYYYYYYN",
    "......NNNNNNNNN.",
    ".....NUUUUUNTTTN",
    ".....NUlllUNTTTN",
    ".....NUUUUUNTTTN",
    ".....NUllUUNNTTN",
    ".....NUUUUUN.NTN",
    ".....NUUNNNN..NN",
    ".....NUN........",
    ".....NN.........",
]
pixmap(s, "bubbles", CLUSTER, 0, 0, "object", legend={
    "Y": ("yellow", YELLOW), "T": ("teal", TEAL), "U": ("purple", PURPLE_LIGHT),
    "b": ("text_y", BROWN), "l": ("text_p", LINE_PURPLE), "N": ("ink", INK)})
s.commit()
