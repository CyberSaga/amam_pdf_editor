"""Batch 11 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio


def rects(*rs):
    return "".join(f"M{x} {y}h{w}v{h}h{-w}Z" for x, y, w, h in rs)


s = Studio.open()
s.begin(6, "24 格：減少深藍，回到 48 版的比例",
        "像素清楚了，但深藍太多：頭的兩側框線緊貼標籤窗框，變成 2 格寬的黑邊，整張臉像戴面具，不像 48 版「白紙上的杏色倉鼠」。48 版倉鼠框線只佔頭寬的 6.6%，這裡 1 px 已經是 10%，再加上窗框就翻倍。",
        "拿掉頭的兩側框線與耳朵外側框線（由窗框代替），杏色直接接到窗框；保留耳尖、頭頂線與眼睛這三個深藍重點。嘴改成柔和的玫瑰棕、鼻子改淺一階，下半臉不再出現第二塊深色。",
        tempo="normal")
s.look((6, 11, 12, 7), "兩側黑邊太粗、臉像面具")
s.mod("face_outline", note="拿掉兩側框線，只留耳尖與頭頂線", d=rects((8, 11, 2, 1), (14, 11, 2, 1), (10, 12, 4, 1)))
s.mod("face_peach", note="杏色延伸到窗框", d=rects((7, 12, 10, 4)))
s.mod("face_muzzle", d=rects((7, 16, 10, 2), (11, 15, 2, 1)))
s.mod("ears_inner", d=rects((7, 12, 3, 1), (14, 12, 3, 1)))
s.mod("blush", d=rects((8, 16, 1, 1), (15, 16, 1, 1)))
s.mod("mouth", note="嘴改玫瑰棕", fill="#B07783")
s.mod("nose", fill="#EC7684")
s.commit()
