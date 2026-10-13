"""Batch 2 of the 17_螢光筆 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(2, "48 格：筆夾和筆尖放大、框線減細",
        "疊圖：筆身和倉鼠頭的位置都吻合；但筆夾收得太窄（底只剩 5 格），筆尖被 2.5 px 框吃到只剩一個黃點，整段幾乎全黑。"
        "把參考的筆夾與筆尖轉回直立量：筆夾長 7、底寬約 8.5，筆尖寬 6.5 收到 5、長約 4。",
        "筆夾改成底寬 9.5（外緣）、長 7；筆尖上寬 7.5、下寬 6.5、長 4.25，比參考略大好讓黃色露出來；筆夾和筆尖是筆身下面的小零件，"
        "框線改 2 px（筆身維持 2.5）。",
        tempo="normal")
s.look((24, 28, 14, 16), "筆尖只剩黃點、筆夾太窄")
s.mod("collar", note="筆夾底放寬、框線 2 px", d="M21.65 31.5H34.35L31.25 37.5H24.75Z", stroke_width=2)
s.mod("tip", note="筆尖放大、框線 2 px", d="M25.25 37.5H30.75L30.25 41.75H25.75Z", stroke_width=2)
s.commit(compare=True)
