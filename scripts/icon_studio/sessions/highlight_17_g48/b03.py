"""Batch 3 of the 17_螢光筆 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import WHITE, hamster48, paw48
from studio import Studio

s = Studio.open()
s.begin(5, "48 格：臉、抱筆的手、筆身反光",
        "筆的三段比例對了：黃筆身、灰藍筆夾、黃筆尖，筆尖正好落在筆痕上。倉鼠還沒有臉、也還沒抱住筆；"
        "筆身左上角從倉鼠頭左下方露出來。",
        "補臉（k 0.78、歪 -8°）；左手壓在筆身左緣、蓋住露出來的左上角，右手扶在筆身右緣、頭的右下方；"
        "筆身右側內緣一道白色長反光（60%），上端藏到倉鼠頭後；擦掉草稿。",
        tempo="normal")
hamster48(s, "hm", 20.5, 10.5, 7.5, 6.2, layer="front", k=0.78, rot=-8, parts=("face",))
paw48(s, "hm_paw0", 14.4, 18.9, layer="front", k=1.2)
paw48(s, "hm_paw1", 27.3, 16.0, layer="front", k=1.1)
s.add("barrel_gloss", "path", "object_fx", d="M31.6 14V28.5", fill="none", stroke=WHITE, stroke_width=1.5,
      stroke_opacity=0.6, stroke_linecap="round", transform="rotate(-28 28 31.5)", anim="draw")
for eid in [e for e, el in list(s.elements.items()) if el["layer"] in ("sketch", "guides")]:
    s.rm(eid)
s.commit(compare=True)
