"""Embed a session's op log into player_template.html -> one self-contained player page."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from studio import LAYERS, PROCESS_LAYERS, REF_PNG, STAGES, Studio

HERE = Path(__file__).resolve().parent


def build(out: Path, title: str = "儲存", artifact: bool = False) -> Path:
    s = Studio.open()
    log = []
    defined: set[str] = set()
    for op in s.log:
        o = {k: v for k, v in op.items() if k != "prev"}
        if op["op"] == "def":
            o["replace"] = op["id"] in defined
            defined.add(op["id"])
        log.append(o)
    c = s.count()
    mods = sum(1 for o in s.log if o["op"] == "mod")
    dels = sum(1 for o in s.log if o["op"] == "del")
    looks = sum(1 for o in s.log if o["op"] in ("look", "compare", "thumbs"))
    outro = (f"最終 SVG：<b>{c['final_shapes']:,}</b> 個繪製元素<br>"
             f"{len(s.batches)} 批 · {len(s.log):,} 個操作<br>"
             f"其中 {mods} 次修改、{dels} 次擦除、{looks} 次觀察比對")
    data = {
        "layers": LAYERS, "process_layers": sorted(PROCESS_LAYERS), "stages": STAGES,
        "batches": s.batches, "log": log,
        "ref": "data:image/png;base64," + base64.b64encode(REF_PNG.read_bytes()).decode(),
        "outro": outro,
    }
    tpl = (HERE / "player_template.html").read_text(encoding="utf-8")
    tpl = tpl.replace("「儲存」按鈕圖示", f"「{title}」按鈕圖示")
    html = tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    if artifact:
        html = to_fragment(html)
    out.write_text(html, encoding="utf-8")
    return out


FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@500&display=swap">')


def to_fragment(html: str) -> str:
    """Strip the document shell for publishing as an Artifact (the host adds its own)."""
    head = html.split("<head>", 1)[1].split("</head>", 1)[0]
    body = html.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    head = "\n".join(ln for ln in head.splitlines() if "<meta" not in ln)
    return head.strip() + "\n" + FONTS + "\n" + body.strip() + "\n"
