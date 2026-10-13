"""Batch 3 of the 12_搜尋 48 px grid design. Run via run_session.py."""
from __future__ import annotations

from parts import hamster_face48
from studio import Studio

s = Studio.open()
s.begin(6, "48 格：鏡片裡的倉鼠改成儲存的構造",
        "使用者回饋：倉鼠看起來怪、不如儲存精緻。192 px 並排看：鏡片裡這隻歪頭 18°，1× 時五官糊成一團；頭是普通橢圓，"
        "下面接一顆細長身體加白肚子，像保齡球瓶。",
        "頭擺正、換成儲存的寬圓頂（k 1.05，底寬 20），平底壓在鏡框下緣的深藍內框裡（y 29.2，兩個底角也藏在鏡框下），"
        "就像儲存的倉鼠從標籤窗口下緣探頭；身體和肚子拿掉。鬍鬚會整段落在鏡框底下，不畫；耳朵外側一點點收進鏡框後面，"
        "比剛好擦到鏡框內緣乾淨。",
        tempo="normal")
s.look((7, 10, 23, 22), "歪頭糊臉、保齡球瓶身體")
for eid in [e for e in list(s.elements) if e.startswith("hm_")]:
    s.rm(eid, note="舊倉鼠擦掉")
hamster_face48(s, "hf", 18.5, 29.2, 1.05, whiskers=False)
s.commit()
