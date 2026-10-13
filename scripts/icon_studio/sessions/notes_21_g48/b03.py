"""Batch 3 of the 21_註解列表 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import INK, PEACH, WHITE, hamster48
from studio import Studio

BROWN = "#96602A"  # same text-line brown as 18_新增註解
LINE_PURPLE = "#4A478F"  # the reference's dark indigo lines on the lilac bubble
s = Studio.open()
s.begin(5, "48 格：臉、字線與反光",
        "三個框的比例定了：黃紫之間留 2 格縫，倉鼠兩隻眼睛的位置正好夾在黃框左下角和紫框左上角之間。",
        "補臉（k 0.72、歪 15°，和新增註解同一張臉）；下巴下補一小截身體（藏在紫框後）；黃框三條咖啡色 1.5 px 圓頭字線"
        "（y 9.75/13.75/17.75，第三條短），紫框兩條深靛色字線（y 31.75/35.75，第二條短）；黃框、紫框左上內側各一道白色反光"
        "（55%），形狀照新增註解；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 9, 24, 6.6, 6.0, k=0.72, rot=-15, parts=("face",))
s.add("hm_body", "ellipse", "hamster", cx=10, cy=32, rx=3.6, ry=3.8, fill=PEACH, stroke=INK, stroke_width=1.25,
      anim="fill", z=0.5)
for i, (y, x1) in enumerate(((9.75, 32), (13.75, 32), (17.75, 26))):
    s.add(f"text_y{i}", "path", "object", d=f"M19 {y}H{x1}", fill="none", stroke=BROWN, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
for i, (y, x1) in enumerate(((31.75, 24), (35.75, 22))):
    s.add(f"text_p{i}", "path", "front", d=f"M16 {y}H{x1}", fill="none", stroke=LINE_PURPLE, stroke_width=1.5,
          stroke_linecap="round", anim="draw")
s.add("gloss_y", "path", "glint", d="M16.75 13.5V8.75Q16.75 6.75 18.75 6.75H24", fill="none", stroke=WHITE,
      stroke_width=1.25, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
s.add("gloss_p", "path", "glint", d="M13.75 33.5V31.75Q13.75 29.75 15.75 29.75H21", fill="none", stroke=WHITE,
      stroke_width=1.25, stroke_opacity=0.55, stroke_linecap="round", anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(compare=True)
