"""Batch 3 of the 22_添加浮水印 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48, paws48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：倉鼠重畫成儲存那隻的構造",
        "使用者回饋：圖示裡的倉鼠看起來怪、不如儲存精緻。放大比對：這隻大頭是普通橢圓，臉下半被印章圓鈕擋住，手掌是兩顆豆子。",
        "頭換成儲存的圓頂（k 0.9），底邊藏在紙上緣；臉完整露出、印章圓鈕在下巴下方；肉墊手抓住圓鈕兩側。",
        tempo="normal")
s.look((11, 3, 20, 16), "普通橢圓頭")
for eid in [e for e in list(s.elements) if e.startswith(("hm_", "paw_"))]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 20.8, 14.9, 0.9)
paws48(s, "hf_paws", [(17.0, 16.6), (25.0, 16.6)], k=0.85)
s.commit()
