"""Batch 1 of the 31_OCR（文字辨識） 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, TEAL, TEAL_DARK, WHITE, pixmap
from studio import Studio

s = Studio.open()
s.begin(3, "16 格：從 24 格移植",
        "24 格版：4 列掃描器、半透明光束、四角 L 框、坐在掃描線上的 7×5 臉、11×9 的大 T。16 格只有 16 列："
        "草稿試了讓倉鼠直接趴在 T 的橫畫上（省一列），結果 T 像倉鼠的身體；留下掃描線把臉和 T 分開，T 才讀得出來。",
        "掃描器 11×3（深藍框、一列青綠、左上 2 格白反光）放在最上方；光束 0.3 透明 + 1 px 青綠邊；臉用 16 格五列放 x 4–10、"
        "y 4–8，手掌併進同一張像素圖、各 2 格搭在 y 9 的深青綠掃描線上（掃描線放最底層）；T 9×5：一列橫畫、兩端襯線、3 格直畫、"
        "5 格腳；四角 2×2 L 框。",
        tempo="normal")
s.add("beam", "path", "back", d="M5 2.5L1.5 15.5H13.5L10 2.5Z", fill=TEAL, fill_opacity=0.3, anim="fill")
s.add("beam_edges", "path", "back", d="M5.5 2.5L2 15.5M9.5 2.5L13 15.5", fill="none", stroke=TEAL, stroke_width=1, anim="draw")
s.add("scan_line", "path", "back", d="M3 9H12V10H3Z", fill=TEAL_DARK, anim="fill")
HAMSTER = [
    "..NN.NN..",
    "..KKPKK..",
    ".PHEPHEP.",
    ".PEEPEEP.",
    ".BWWRWWB.",
    "PP.....PP",
]
pixmap(s, "hm", HAMSTER, 3, 4, "hamster")
CORNERS = [
    "NN............NN",
    "N..............N",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "N..............N",
    "NN............NN",
]
pixmap(s, "corner", CORNERS, 0, 4, "object", legend={"N": ("ink", INK)})
LETTER_T = [
    "NNNNNNNNN",
    "N..NNN..N",
    "...NNN...",
    "...NNN...",
    "..NNNNN..",
]
pixmap(s, "letter_t", LETTER_T, 3, 10, "object", legend={"N": ("ink", INK)})
SCANNER = [
    ".NNNNNNNNN.",
    "NTWWTTTTTTN",
    ".NNNNNNNNN.",
]
pixmap(s, "scanner", SCANNER, 2, 0, "front", legend={"T": ("teal", TEAL), "W": ("gloss", WHITE), "N": ("ink", INK)})
s.commit()
