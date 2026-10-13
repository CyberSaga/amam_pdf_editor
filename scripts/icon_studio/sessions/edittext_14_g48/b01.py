"""Batch 1 of the 14_編輯文字 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f
from parts import INK, PEACH, PURPLE, hamster48
from studio import Studio


def serif_t_d(x, y, w, h, st, b, sd, sw, xc, fw, ft, br):
    """Bracketed serif T as one closed path, top-left (x, y), w x h (shared with 15_新增文字框).

    st stem width, b crossbar thickness, sd / sw serif depth / tip width, xc where the serif's inner
    fillet meets the crossbar (from the outer edge), fw / ft foot width / thickness, br foot bracket.
    """
    sl, sr = x + (w - st) / 2, x + (w + st) / 2
    fl, fr = x + (w - fw) / 2, x + (w + fw) / 2
    yb, yf, x1, y1 = y + b, y + h - ft, x + w, y + h
    return (f"M{f(x)} {f(y)}H{f(x1)}V{f(y + sd)}H{f(x1 - sw)}Q{f(x1 - sw)} {f(yb)} {f(x1 - xc)} {f(yb)}"
            f"H{f(sr)}V{f(yf - br)}Q{f(sr)} {f(yf)} {f(sr + br)} {f(yf)}H{f(fr)}V{f(y1)}H{f(fl)}V{f(yf)}"
            f"H{f(sl - br)}Q{f(sl)} {f(yf)} {f(sl)} {f(yf - br)}V{f(yb)}H{f(x + xc)}"
            f"Q{f(x + sw)} {f(yb)} {f(x + sw)} {f(y + sd)}H{f(x)}Z")


s = Studio.open()
s.begin(3, "48 格：襯線 T、文字游標、坐著的倉鼠",
        "參考圖：左邊一個大的深藍襯線 T（約 x 3.5–27、y 5–33，橫筆兩端下垂的襯線帶圓弧、底部有托腳），右邊一條淡紫直線游標"
        "（x≈31.5、y 4.5–38），倉鼠大頭擠在右下，游標穿過牠的臉、手握住游標下端。",
        "T 用一條封閉路徑：22×28、直筆 6、橫筆 2、襯線深 8、底腳 12×2，所有直邊落在整數格；游標 2 px 紫、x 28–30，和 T 留 3 格；"
        "倉鼠改坐在游標右邊（臉不再被線穿過，縮到 24/16 才讀得出）：頭 12.8×11.2（k 0.67）、圓胖身體、兩隻腳。",
        tempo="normal")
s.add("glyph", "path", "object", d=serif_t_d(3, 5, 22, 28, 6, 2, 8, 2, 6, 12, 2, 2), fill=INK, anim="fill")
s.add("cursor", "path", "object_fx", d="M29 4.5V38", fill="none", stroke=PURPLE, stroke_width=2, stroke_linecap="round",
      anim="draw")
for i, x in enumerate((35.2, 41.4)):
    s.add(f"hm_foot{i}", "ellipse", "hamster", cx=x, cy=44.6, rx=2.2, ry=1.25, fill=PEACH, stroke=INK,
          stroke_width=1.1, anim="fill")
s.add("hm_body", "ellipse", "hamster", cx=38.3, cy=39.4, rx=6.2, ry=5.8, fill=PEACH, stroke=INK, stroke_width=1.25,
      anim="fill")
hamster48(s, "hm", 38.2, 30.2, 6.4, 5.6, k=0.67, parts=("blocks",))
s.commit()
