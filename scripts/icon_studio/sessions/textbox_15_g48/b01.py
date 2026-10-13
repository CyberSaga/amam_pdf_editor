"""Batch 1 of the 15_新增文字框 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import f, rrect_d
from parts import INK, PAPER, PURPLE, TEAL, hamster48
from studio import Studio


def serif_t_d(x, y, w, h, st, b, sd, sw, xc, fw, ft, br):
    """Bracketed serif T as one closed path, top-left (x, y), w x h (shared with 14_編輯文字).

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
s.begin(3, "48 格：文字框、控點、T、探頭的倉鼠",
        "參考圖：文字框（框線約 x 7.5–38、y 6–38）左上、右上、左下各一個方形控點，右下角是紫色加號圓章；框內偏右下一個小襯線 T；"
        "倉鼠在框內左上角歪著頭探進來。照搬到 24／16 格時，框內只剩 14×14／10×10 格，臉、T、圓章會擠在一起。",
        "改用整組圖示共用的「從上緣探頭」：倉鼠頭 13.2×11.6（k 0.68）放在框的左上方、下半藏在框後；框線 2 px、中心線 x 9/39、"
        "y 15/40，框內填白；控點和操作物件同一款（8×8、2 px 深藍框、4×4 青綠）；T 是編輯文字那個 T 的半尺寸（11×14，直筆 3），"
        "放在框中央；右下角加號圓章外半徑 6.5、中心 (38.5, 39.5)。",
        tempo="normal")
hamster48(s, "hm", 19.5, 9.0, 6.6, 5.8, k=0.68, eye_y=7.8, parts=("blocks",))
s.add("box", "path", "object", d="M9 15H39V40H9Z", fill=PAPER, stroke=INK, stroke_width=2, anim="fill")
for i, (hx, hy) in enumerate(((9, 15), (39, 15), (9, 40))):
    s.add(f"handle{i}", "path", "object", d=rrect_d(hx - 3, hy - 3, hx + 3, hy + 3, 1.0), fill=TEAL, stroke=INK,
          stroke_width=2, stroke_linejoin="round", anim="fill")
s.add("glyph", "path", "object_fx", d=serif_t_d(18, 20, 11, 14, 3, 1, 4, 1, 3, 7, 1, 1), fill=INK, anim="fill")
s.add("badge_disc", "circle", "badge", cx=38.5, cy=39.5, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
s.commit()
