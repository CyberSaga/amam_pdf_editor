"""Batch 2 of the 04_另存新檔 16 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "16 格：磁片內框拿掉，讓紫色露出來",
        "1× 看：磁片只有 9 格寬，擋板與標籤各自的 1 px 外框加上磁片外框，紫色只剩零星幾格，整片讀成深色方塊。",
        "擋板與標籤改成無框白塊（擋板 4×2 帶 1 格槽孔、標籤 5×4 帶一條字線），紫色在兩側與上下各留 1 格。",
        tempo="normal")
s.look((6, 1, 9, 12), "磁片太黑")
s.mod("shutter_plate", note="擋板去框", d="M8 2H12V4H8Z", stroke="none")
s.mod("slot", note="槽孔移進擋板", x=10, y=2, width=1, height=2)
s.mod("label_paper", note="標籤去框", d="M8 7H13V11H8Z", stroke="none")
s.mod("label_line", note="字線跟著移", d="M9 8.5H12")
s.commit()
