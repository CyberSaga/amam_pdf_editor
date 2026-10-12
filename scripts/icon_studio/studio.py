"""Op-log drawing studio.

Every batch script does:

    s = Studio.open()
    s.begin(stage, title, observe, decide)
    ... s.add / s.mod / s.rm / s.layer / s.gradient / s.look ...
    s.commit(...)

The log of ops is the single source for both the final SVG and the replay video.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
# run_session.py sets these before the first import; the defaults keep ad-hoc use working.
WORK = Path(os.environ.get("ICON_STUDIO_WORK", str(ROOT / "work" / "default")))
STATE = WORK / "state.json"
SNAP = WORK / "snapshots"
OUT = WORK / "out"
REF_PNG = Path(os.environ.get("ICON_STUDIO_REF", str(REPO / "view/resources/function_icons/03_儲存.png")))
NO_RENDER = os.environ.get("ICON_STUDIO_NO_RENDER") == "1"

LAYERS = [
    "card", "cast", "body", "body_fx", "shutter", "label", "hamster",
    "hamster_fx", "ink", "glint", "sketch", "guides",
]
PROCESS_LAYERS = {"sketch", "guides"}
SHAPE_TAGS = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
STAGES = {
    1: "草稿", 2: "大形與比例", 3: "鋪大色塊", 4: "明暗關係",
    5: "細化結構、光影與細節", 6: "檢查整體", 7: "調整收尾",
}
BACKDROP = "#ECEAF1"
# Reference PNG -> 512 canvas mapping "scale,dx,dy" (save_03: measured from the floppy body box).
_REF_MAP = [float(v) for v in os.environ.get("ICON_STUDIO_REF_MAP", "2.2,22.8,42.8").split(",")]
REF_SCALE = _REF_MAP[0]
REF_OFF = (_REF_MAP[1], _REF_MAP[2])


def _key(k: str) -> str:
    return k.rstrip("_").replace("_", "-")


def _norm(attrs: dict) -> dict:
    out = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, float):
            s = f"{v:.3f}".rstrip("0").rstrip(".")
            v = "0" if s in ("-0", "") else s
        out[_key(k)] = str(v)
    return out


class Studio:
    def __init__(self, data: dict):
        self.elements: dict[str, dict] = data["elements"]
        self.defs: dict[str, dict] = data["defs"]
        self.layer_attrs: dict[str, dict] = data["layer_attrs"]
        self.params: dict = data["params"]
        self.log: list[dict] = data["log"]
        self.batches: list[dict] = data["batches"]
        self.zc: float = data["zc"]
        self.cur: int | None = None
        self._before: dict | None = None

    # ------------------------------------------------------------ persistence
    @classmethod
    def open(cls) -> "Studio":
        if STATE.exists():
            return cls(json.loads(STATE.read_text(encoding="utf-8")))
        WORK.mkdir(parents=True, exist_ok=True)
        return cls({
            "elements": {}, "defs": {}, "layer_attrs": {ly: {} for ly in LAYERS},
            "params": {}, "log": [], "batches": [], "zc": 0.0,
        })

    def _data(self) -> dict:
        return {
            "elements": self.elements, "defs": self.defs,
            "layer_attrs": self.layer_attrs, "params": self.params,
            "log": self.log, "batches": self.batches, "zc": self.zc,
        }

    def save(self) -> None:
        WORK.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(self._data(), ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ batch control
    def begin(self, stage: int, title: str, observe: str, decide: str, tempo: str = "normal"):
        n = len(self.batches) + 1
        SNAP.mkdir(parents=True, exist_ok=True)
        (SNAP / f"b{n:02d}_before.json").write_text(json.dumps(self._data(), ensure_ascii=False), encoding="utf-8")
        self.cur = n
        b = {"n": n, "stage": stage, "title": title, "observe": observe,
             "decide": decide, "tempo": tempo}
        self.batches.append(b)
        self.log.append({"op": "batch", **b})
        return self

    def _op(self, op: dict) -> None:
        if self.cur is None:
            raise RuntimeError("begin() a batch first")
        op["b"] = self.cur
        self.log.append(op)

    # ------------------------------------------------------------ drawing ops
    def add(self, eid: str, tag: str, layer: str, z: float | None = None,
            anim: str | None = None, text: str | None = None, **attrs):
        if eid in self.elements:
            raise KeyError(f"duplicate id {eid}")
        if layer not in LAYERS:
            raise KeyError(f"unknown layer {layer}")
        if z is None:
            self.zc += 1.0
            z = self.zc
        el = {"id": eid, "tag": tag, "layer": layer, "z": z, "attrs": _norm(attrs)}
        if text is not None:
            el["text"] = text
        self.elements[eid] = el
        op = {"op": "add", "id": eid, "tag": tag, "layer": layer, "z": z,
              "attrs": el["attrs"]}
        if anim:
            op["anim"] = anim
        if text is not None:
            op["text"] = text
        self._op(op)
        return eid

    def mod(self, eid: str, note: str | None = None, **attrs):
        el = self.elements[eid]
        new = _norm(attrs)
        prev = {k: el["attrs"].get(k) for k in new}
        el["attrs"].update(new)
        op = {"op": "mod", "id": eid, "attrs": new, "prev": prev}
        if note:
            op["note"] = note
        self._op(op)

    def restack(self, eid: str, z: float, note: str | None = None):
        el = self.elements[eid]
        op = {"op": "restack", "id": eid, "z": z, "prev": el["z"]}
        if note:
            op["note"] = note
        el["z"] = z
        self._op(op)

    def rm(self, eid: str, note: str | None = None):
        el = self.elements.pop(eid)
        op = {"op": "del", "id": eid, "prev": el}
        if note:
            op["note"] = note
        self._op(op)

    def layer(self, name: str, note: str | None = None, **attrs):
        new = _norm(attrs)
        prev = {k: self.layer_attrs[name].get(k) for k in new}
        self.layer_attrs[name].update(new)
        op = {"op": "layer", "layer": name, "attrs": new, "prev": prev}
        if note:
            op["note"] = note
        self._op(op)

    def gradient(self, gid: str, kind: str, stops: list, note: str | None = None, **attrs):
        """kind: linear|radial; stops: [(offset, color, opacity), ...]."""
        tag = {"linear": "linearGradient", "radial": "radialGradient"}[kind]
        d = {"id": gid, "tag": tag, "attrs": _norm(attrs),
             "stops": [[float(o), c, float(a)] for o, c, a in stops]}
        prev = self.defs.get(gid)
        self.defs[gid] = d
        op = {"op": "def", "id": gid, "def": d, "prev": prev}
        if note:
            op["note"] = note
        self._op(op)
        return f"url(#{gid})"

    # ------------------------------------------------------------ observation ops (video only)
    def look(self, box, note: str):
        self._op({"op": "look", "box": [float(v) for v in box], "note": note})

    def compare(self, note: str):
        self._op({"op": "compare", "note": note})

    def thumbs(self, note: str):
        self._op({"op": "thumbs", "note": note})

    # ------------------------------------------------------------ serialization
    def svg(self, process: bool = True, background: str | None = None,
            title: str | None = None) -> str:
        out = ['<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">']
        if title:
            out.append(f"<title>{escape(title)}</title>")
        if background:
            out.append(f'<rect x="0" y="0" width="512" height="512" fill="{background}"/>')
        if self.defs:
            out.append("<defs>")
            for d in self.defs.values():
                a = "".join(f" {k}={quoteattr(v)}" for k, v in d["attrs"].items())
                out.append(f'<{d["tag"]} id="{d["id"]}"{a}>')
                for o, c, op in d["stops"]:
                    so = "" if op >= 1 else f' stop-opacity="{op:g}"'
                    out.append(f'<stop offset="{o:g}" stop-color="{c}"{so}/>')
                out.append(f'</{d["tag"]}>')
            out.append("</defs>")
        by_layer: dict[str, list] = {ly: [] for ly in LAYERS}
        for el in self.elements.values():
            by_layer[el["layer"]].append(el)
        for ly in LAYERS:
            if ly in PROCESS_LAYERS and not process:
                continue
            els = sorted(by_layer[ly], key=lambda e: e["z"])
            if not els:
                continue
            la = "".join(f" {k}={quoteattr(v)}" for k, v in self.layer_attrs[ly].items())
            out.append(f'<g id="{ly}"{la}>')
            for el in els:
                a = "".join(f" {k}={quoteattr(v)}" for k, v in el["attrs"].items())
                if el.get("text") is not None:
                    out.append(f'<{el["tag"]} id="{el["id"]}"{a}>{escape(el["text"])}</{el["tag"]}>')
                else:
                    out.append(f'<{el["tag"]} id="{el["id"]}"{a}/>')
            out.append("</g>")
        out.append("</svg>")
        return "\n".join(out)

    def count(self) -> dict:
        final = [e for e in self.elements.values() if e["layer"] not in PROCESS_LAYERS]
        shapes = [e for e in final if e["tag"] in SHAPE_TAGS]
        proc = [e for e in self.elements.values() if e["layer"] in PROCESS_LAYERS]
        stops = sum(len(d["stops"]) for d in self.defs.values())
        return {"final_shapes": len(shapes), "process_shapes": len(proc),
                "defs": len(self.defs), "stops": stops, "ops": len(self.log)}

    # ------------------------------------------------------------ rendering
    def commit(self, zooms=(), compare: bool = False, small: bool = False,
               hi: bool = False, final_view: bool = False) -> None:
        self.save()
        OUT.mkdir(parents=True, exist_ok=True)
        n = self.cur or len(self.batches)
        cur_svg = OUT / "current.svg"
        fin_svg = OUT / "final.svg"
        cur_svg.write_text(self.svg(process=True, background=BACKDROP), encoding="utf-8")
        fin_svg.write_text(self.svg(process=False), encoding="utf-8")
        if NO_RENDER:
            print(f"batch {n} committed (no render): {self.count()}")
            return
        jobs = [{"svg": str(cur_svg), "out": str(OUT / f"b{n:02d}_1024.png"), "size": 1024, "bg": BACKDROP}]
        if hi or zooms:
            jobs.append({"svg": str(cur_svg), "out": str(OUT / f"b{n:02d}_2048.png"), "size": 2048, "bg": BACKDROP})
        if small or final_view:
            jobs.append({"svg": str(fin_svg), "out": str(OUT / f"b{n:02d}_final512.png"), "size": 512, "bg": "transparent"})
        if final_view:
            jobs.append({"svg": str(fin_svg), "out": str(OUT / f"b{n:02d}_final1024.png"), "size": 1024, "bg": "#FFFFFF"})
        render(jobs)
        im = Image.open(OUT / f"b{n:02d}_1024.png").convert("RGB")
        im.resize((800, 800), Image.LANCZOS).save(OUT / f"b{n:02d}_view.png")
        for i, (x, y, w, h) in enumerate(zooms):
            big = Image.open(OUT / f"b{n:02d}_2048.png").convert("RGB")
            k = 2048 / 512
            crop = big.crop((int(x * k), int(y * k), int((x + w) * k), int((y + h) * k)))
            scale = 800 / max(crop.size)
            crop = crop.resize((int(crop.size[0] * scale), int(crop.size[1] * scale)), Image.LANCZOS)
            crop.save(OUT / f"b{n:02d}_zoom{i}.png")
        if compare:
            self._compare_sheet(n, im)
        if small:
            self._small_sheet(n)
        c = self.count()
        print(f"batch {n} committed: {c}")

    def _ref_on_canvas(self, size: int) -> Image.Image:
        ref = Image.open(REF_PNG).convert("RGBA")
        k = size / 512
        rs = ref.resize((round(ref.width * REF_SCALE * k), round(ref.height * REF_SCALE * k)), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), BACKDROP)
        canvas.alpha_composite(rs, (round(REF_OFF[0] * k), round(REF_OFF[1] * k)))
        return canvas

    def _compare_sheet(self, n: int, cur: Image.Image) -> None:
        size = 600
        a = cur.resize((size, size), Image.LANCZOS).convert("RGBA")
        ref = self._ref_on_canvas(size)
        onion = Image.blend(a, ref, 0.45)
        sheet = Image.new("RGB", (size * 3 + 40, size + 40), "#FFFFFF")
        for i, img in enumerate([a, ref, onion]):
            sheet.paste(img.convert("RGB"), (10 + i * (size + 10), 30))
        d = ImageDraw.Draw(sheet)
        font = _font(18)
        for i, t in enumerate(["current", "reference (mapped)", "onion skin 55/45"]):
            d.text((14 + i * (size + 10), 6), t, fill="#333", font=font)
        sheet.save(OUT / f"b{n:02d}_compare.png")

    def _small_sheet(self, n: int) -> None:
        fin = Image.open(OUT / f"b{n:02d}_final512.png").convert("RGBA")
        ref = Image.open(REF_PNG).convert("RGBA")
        sizes = [16, 24, 32, 48, 64, 96]
        sheet = Image.new("RGB", (1000, 430), "#FFFFFF")
        d = ImageDraw.Draw(sheet)
        font = _font(16)
        x = 10
        for s in sizes:
            for row, src in enumerate([fin, ref]):
                small = src.resize((s, s), Image.LANCZOS)
                bg = Image.new("RGBA", (s, s), "#F3F3F6")
                bg.alpha_composite(small)
                y = 30 + row * 200
                sheet.paste(bg.convert("RGB"), (x, y))
                mag = bg.resize((s * 2, s * 2), Image.NEAREST) if s <= 48 else bg
                sheet.paste(mag.convert("RGB"), (x, y + s + 8))
            d.text((x, 6), f"{s}px", fill="#333", font=font)
            x += max(s * 2, 64) + 24
        d.text((10, 410), "row1: new SVG   row2: reference PNG   (actual size, then 2x nearest)", fill="#555", font=font)
        sheet.save(OUT / f"b{n:02d}_small.png")


def _font(sz: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def render(jobs: list[dict]) -> None:
    jf = WORK / "jobs.json"
    jf.write_text(json.dumps(jobs))
    r = subprocess.run(["node", str(ROOT / "render.js"), str(jf)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("render failed")


def restore(n: int) -> None:
    """Roll the working state back to the snapshot taken before batch n."""
    snap = SNAP / f"b{n:02d}_before.json"
    STATE.write_text(snap.read_text())
    data = json.loads(snap.read_text())
    print(f"restored to before batch {n}: {len(data['batches'])} batches, {len(data['log'])} ops")


def deep(x):
    return copy.deepcopy(x)
