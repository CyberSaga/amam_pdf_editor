"""Batch 6 of the 03_儲存 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from geo import rrect_d
from studio import Studio

INK = "#1E1D38"
s = Studio.open()
s.begin(6, "24 格：修正頭底邊的棕線，補一道高光",
        "1× 時臉清楚了，但頭是封閉路徑，被窗底切掉的那條邊也描了棕框，在標籤窗下框上方多出一條棕線。紫色本體是一整片平色。",
        "標籤窗的框改成獨立的描線元素，放在倉鼠上層（倉鼠從框後探出頭，和精細版一致），窗本身只留白底；本體左上內角加一道 40% 白色的短高光。",
        tempo="normal")
s.look((7, 17.3, 10, 1.5), "頭底邊多出一條棕線")
s.mod("label_paper", note="標籤窗只留白底", stroke="none")
s.add("label_frame", "path", "ink", d=rrect_d(6.5, 11.5, 17.5, 18.5, 1.0), fill="none", stroke=INK,
      stroke_width=1, stroke_linejoin="round", anim="draw")
s.add("gloss", "path", "glint", d="M5.1 9.2V6.3Q5.1 5.1 6.3 5.1H6.9", fill="none", stroke="#FFFFFF",
      stroke_width=0.85, stroke_opacity=0.45, stroke_linecap="round", anim="draw")
s.commit()
