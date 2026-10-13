"""Batch 2 of the 12_搜尋 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import grow_ears_px
from studio import Studio

s = Studio.open()
s.begin(6, "16 格：耳朵放大",
        "使用者回饋：倉鼠的耳朵都太小，要放大 1.5～2 倍。16 格的耳朵是 2 格深藍耳尖加一列 2 格粉紅，"
        "兩耳中間只隔 1 格，頭頂上面也沒有空間再長高。",
        "兩耳各往外長 1 格：粉紅變 3 格寬，深藍耳尖跟著往外移（內側那格拿掉），耳朵變成頭頂兩角的圓耳朵，寬 1.5 倍。兩耳外側那格都藏在鏡框後面，耳尖保留內側那格（鏡片裡放不下更大的耳朵，看起來和原本一樣大）。",
        tempo="normal")
s.look((2, 4, 10, 3), "耳朵太小")
grow_ears_px(s, "hm_ears_in", "hm_outline", note="耳朵往外長 1 格", hidden=(True, True))
s.commit()
