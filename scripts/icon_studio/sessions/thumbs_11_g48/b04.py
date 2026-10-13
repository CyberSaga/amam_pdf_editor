"""Batch 4 of the 11_縮圖 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import PURPLE_DARK, TEAL_DARK
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：方塊框線改用各自的深色",
        "依程式挑圖的方式並排看整組（16–64 px）：32 px 用的是 24 格版（方塊是深紫／深青綠框），36 px 起換成 48 格版，四個方塊突然變成"
        "深藍框的黑盒子，比同組的旋轉頁、插入空白頁都暗。方塊是框裡的內容（像插入圖片的山用深青綠稜線），外框才是物件輪廓。",
        "四個方塊的 1.5 px 框線改成各自的深色（左欄深紫、右欄深青綠），深藍只留給外框；光澤與位置不動，和 24／16 格版一致。",
        tempo="normal")
s.look((12, 17, 24, 24), "36 px 起方塊變黑盒子")
for i, col in enumerate((PURPLE_DARK, TEAL_DARK, PURPLE_DARK, TEAL_DARK)):
    s.mod(f"tile{i}", note="方塊框改深色" if i == 0 else None, stroke=col)
s.commit()
