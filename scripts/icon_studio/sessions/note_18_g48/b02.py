"""Batch 2 of the 18_新增註解 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, plus_d
from studio import Studio

BROWN = "#96602A"  # the reference's text-line brown (no palette entry)
s = Studio.open()
s.begin(5, "48 格：臉、字線、加號與反光",
        "疊圖：對話框和尾巴的位置吻合；倉鼠頭的位置對，但身體整顆露在頭下面，像雪人；參考只在下巴下露出一小截。",
        "身體往右下移、大半藏進對話框後面；補臉（k 0.72，跟著頭歪 15°）；三條咖啡色 1.5 px 圓頭字線（y 14.75/19.75/24.75，"
        "第三條短）；圓章放 3 px 寬白加號；對話框左上內側一道白色反光（55%）；擦掉草稿。",
        tempo="normal")
s.look((6, 24, 10, 13), "身體像雪人")
s.mod("hm_body", note="身體移到框後只露一截", cx=14.6, cy=31.2, rx=4.0, ry=5.0)
hamster48(s, "hm", 9.5, 22, 6.8, 6.2, k=0.72, rot=-15, parts=("face",))
for i, (y, x1) in enumerate(((14.75, 34), (19.75, 34), (24.75, 28.5))):
    s.add(f"text{i}", "path", "object_fx", d=f"M20 {y}H{x1}", fill="none", stroke=BROWN, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
s.add("bubble_gloss", "path", "glint", d="M17.75 18.5V13.75Q17.75 11.75 19.75 11.75H25", fill="none", stroke=WHITE,
      stroke_width=1.25, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("badge_plus", "path", "badge", d=plus_d(37.5, 33.5, 3.5, 3), fill=WHITE, anim="pop")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(compare=True)
