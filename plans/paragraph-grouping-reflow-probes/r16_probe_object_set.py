"""Round-16 probes for the C.4 object set: what review round 16 found unmeasured. Prints numbers only.

Usage:
  python -I r16_probe_object_set.py                              synthetic cases (P12)
  python -I r16_probe_object_set.py <pdf> <block:line> [...]     a paragraph of a real page (P13)

P12: (a) for every texttrace span, `get_bboxlog()[seqno]` is a text entry, and the rendered ink
(every pixel that differs from white, 4x) lies inside it; cases: upright, skew, stroke, Tz, Form, a
zero-advance glyph, a CJK font; (b) shadings: unclipped with and without /Extend, /BBox, triangle
clip, nested rect clips; (c) fills with a tiling pattern and with a shading pattern.
P13: the given lines are the paragraph (as in r11_probe_hang_room.py). Foreign glyphs are measured
twice: by their texttrace char bbox (lower bound of the plan's ink box) and by their span's
`get_bboxlog` entry (the plan's fallback box, upper bound). Reports admission hits, `hang_room` and
whether the strip right of M renders in one colour.
"""
from __future__ import annotations

import sys

import fitz

TEXT_CODES = {"fill-text", "stroke-text", "ignore-text"}
NO_LINE_START = set("、。，．：；！？）」』】〕〉》｝］”’")
MARGIN = 1.0
FN = "/Function<</FunctionType 2/Domain[0 1]/C0[1 0 0]/C1[0 0 1]/N 1>>"
AXIAL = "<</ShadingType 2/ColorSpace/DeviceRGB/Coords[%s]%s" + FN + ">>"


def r2(rect) -> tuple:
    return tuple(round(v, 2) for v in rect)


def page_from(objects: dict[str, tuple[str, bytes | None]], resources: str, content: bytes) -> fitz.Document:
    """Build a one-page document; `resources` may name objects as {key}."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    refs: dict[str, str] = {}
    for key, (body, stream) in objects.items():
        xref = doc.get_new_xref()
        doc.update_object(xref, body.format(**refs))
        if stream is not None:
            doc.update_stream(xref, stream, compress=False)
        refs[key] = f"{xref} 0 R"
    c = doc.get_new_xref()
    doc.update_object(c, "<<>>")
    doc.update_stream(c, content, compress=False)
    doc.xref_set_key(page.xref, "Resources", resources.format(**refs))
    doc.xref_set_key(page.xref, "Contents", f"{c} 0 R")
    return fitz.open("pdf", doc.tobytes())


def ink_box(page: fitz.Page, clip: fitz.Rect, zoom: int = 4) -> tuple | None:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    w, data = pix.width, pix.samples
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pix.height):
        row = data[y * pix.stride : y * pix.stride + w]
        if min(row) < 255:
            ys.append(y)
            xs.extend(i for i, v in enumerate(row) if v < 255)
    if not ys:
        return None
    ox, oy = pix.x / zoom, pix.y / zoom
    return (ox + min(xs) / zoom, oy + min(ys) / zoom, ox + (max(xs) + 1) / zoom, oy + (max(ys) + 1) / zoom)


def inside(inner, outer, tol: float = 0.26) -> bool:
    """True when `inner` lies in `outer`; tol = one pixel at 4x (the ink box is pixel-grown)."""
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def text_cases() -> None:
    objects = {
        "f": ("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>", None),
        "z": ("<</Type/Font/Subtype/Type1/BaseFont/Helvetica/FirstChar 65/LastChar 65/Widths[0]>>", None),
        "fm": (
            "<</Type/XObject/Subtype/Form/BBox[0 0 600 800]/Resources<</Font<</F1 {f}>>>>>>",
            b"BT /F1 20 Tf 50 500 Td (Ag) Tj ET\n",
        ),
    }
    content = (
        b"BT /F1 20 Tf 50 600 Td (Ag) Tj ET\n"
        b"BT /F1 20 Tf 1 0 0.5 1 150 600 Tm (Ag) Tj ET\n"
        b"BT /F1 20 Tf 1 Tr 6 w 250 600 Td (Ag) Tj ET\n"
        b"BT /F1 20 Tf 0 Tr 200 Tz 350 600 Td (Ag) Tj ET\n"
        b"BT /F0 20 Tf 480 600 Td (A) Tj ET\n"
        b"/Fm Do\n"
    )
    doc = page_from(objects, "<</Font<</F1 {f}/F0 {z}>>/XObject<</Fm {fm}>>>>", content)
    doc[0].insert_text((50, 400), "永字，」", fontname="china-t", fontsize=20)
    page = fitz.open("pdf", doc.tobytes())[0]
    log = page.get_bboxlog()
    print("-- text: per span, bboxlog[seqno] vs rendered ink (order: upright, skew, stroke, Tz, zero-advance, Form, CJK)")
    for sp in page.get_texttrace():
        boxes = [fitz.Rect(ch[3]) for ch in sp["chars"]]
        union = boxes[0]
        for b in boxes[1:]:
            union |= b
        code, entry = log[sp["seqno"]]
        ink = ink_box(page, fitz.Rect(union) + (-45, -45, 45, 45))
        widths = [round(b.width, 2) for b in boxes]
        meets = all(fitz.Rect(entry).intersects(b) for b in boxes)
        print(
            f"   seqno {sp['seqno']} type {sp['type']} {sp['font']} char widths {widths}\n"
            f"      trace {r2(union)} entry[{code}] {r2(entry)}\n"
            f"      ink {r2(ink)} | entry is text code: {code in TEXT_CODES} | ink inside entry: {inside(ink, entry)}"
            f" | ink inside trace: {inside(ink, union)} | every char bbox intersects entry: {meets}"
        )


def shading_cases() -> None:
    cases = {
        "unclipped, extend": (AXIAL % ("0 0 600 0", "/Extend[true true]"), b"/Sh sh\n"),
        "unclipped, no extend": (AXIAL % ("100 0 200 0", ""), b"/Sh sh\n"),
        "BBox [100 100 200 150]": (AXIAL % ("0 0 600 0", "/BBox[100 100 200 150]/Extend[true true]"), b"/Sh sh\n"),
        "triangle clip": (AXIAL % ("0 0 600 0", "/Extend[true true]"), b"q 100 100 m 200 100 l 150 180 l h W n /Sh sh Q\n"),
        "nested rect clips": (
            AXIAL % ("0 0 600 0", "/Extend[true true]"),
            b"q 100 100 100 100 re W n q 150 150 100 100 re W n /Sh sh Q Q\n",
        ),
    }
    print("-- shadings: bboxlog | image_info | drawings")
    for name, (shade, content) in cases.items():
        page = page_from({"s": (shade, None)}, "<</Shading<</Sh {s}>>>>", content)[0]
        log = [(code, tuple(round(v, 1) for v in r)) for code, r in page.get_bboxlog()]
        info = [tuple(round(v, 1) for v in im["bbox"]) for im in page.get_image_info()]
        print(f"   {name}: {log} | {info} | {len(page.get_drawings())}")


def pattern_cases() -> None:
    objects = {
        "s": (AXIAL % ("0 0 600 0", "/Extend[true true]"), None),
        "tile": (
            "<</Type/Pattern/PatternType 1/PaintType 1/TilingType 1/BBox[0 0 10 10]/XStep 10/YStep 10/Resources<<>>>>",
            b"0 0 1 rg 0 0 5 5 re f\n",
        ),
        "shp": ("<</Type/Pattern/PatternType 2/Shading {s}>>", None),
    }
    content = b"/Pattern cs /P1 scn 50 300 60 40 re f\n/Pattern cs /P2 scn 150 300 60 40 re f\n"
    page = page_from(objects, "<</Pattern<</P1 {tile}/P2 {shp}>>>>", content)[0]
    print("-- pattern fills (expected paint, top-left coords: tiling [50,460,110,500], shading pattern [150,460,210,500])")
    for code, rect in page.get_bboxlog():
        print("   bboxlog", code, r2(rect))
    for im in page.get_image_info():
        print("   image_info", r2(im["bbox"]))
    print("   rendered ink tiling:", r2(ink_box(page, fitz.Rect(30, 440, 130, 520))))
    print("   rendered ink shading pattern:", r2(ink_box(page, fitz.Rect(130, 440, 230, 520))))


def grown(r, m: float = MARGIN) -> tuple:
    return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)


def meets(a, b, tol: float = 0.01) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[1], b[1]) > tol


def reference(path: str, args: list[str]) -> None:
    page = fitz.open(path)[0]
    want = {tuple(int(v) for v in a.split(":")) for a in args}
    d = page.get_text("rawdict")
    own_lines = [ln for bi, b in enumerate(d["blocks"]) for li, ln in enumerate(b.get("lines", [])) if (bi, li) in want]
    own_chars = [ch for ln in own_lines for sp in ln["spans"] for ch in sp["chars"] if ch["c"].strip()]
    print("own lines:", len(own_lines), "baselines", sorted({round(ch["origin"][1], 2) for ch in own_chars}), "glyphs", len(own_chars))
    plain_ends = []
    for ln in own_lines:
        chars = [ch for sp in ln["spans"] for ch in sp["chars"] if ch["c"].strip()]
        while len(chars) > 1 and chars[-1]["c"] in NO_LINE_START:
            chars.pop()
        plain_ends.append(chars[-1]["bbox"][2])
    m = max(plain_ends)
    top = min(ln["bbox"][1] for ln in own_lines)
    bottom = max(ln["bbox"][3] for ln in own_lines)
    own_origins = {(round(ch["origin"][0], 1), round(ch["origin"][1], 1)) for ch in own_chars}
    own_boxes = [tuple(ch["bbox"]) for ch in own_chars]

    log = page.get_bboxlog()
    spans = page.get_texttrace()
    by_type: dict[int, int] = {}
    foreign: list[tuple[tuple, tuple, int]] = []  # (char bbox, span entry, span type)
    own_found = mixed = bad_seqno = 0
    for sp in spans:
        code, entry = log[sp["seqno"]]
        if code not in TEXT_CODES:
            bad_seqno += 1
        flags = [(round(ch[2][0], 1), round(ch[2][1], 1)) in own_origins for ch in sp["chars"]]
        mixed += any(flags) and not all(flags)
        for ch, is_own in zip(sp["chars"], flags):
            if not chr(ch[0]).strip():
                continue
            by_type[sp["type"]] = by_type.get(sp["type"], 0) + 1
            if is_own:
                own_found += 1
            else:
                foreign.append((tuple(ch[3]), tuple(entry), sp["type"]))
    n_raw = sum(1 for b in d["blocks"] for ln in b.get("lines", []) for sp in ln["spans"] for ch in sp["chars"] if ch["c"].strip())
    print(f"texttrace non-space glyphs by span type {sorted(by_type.items())}; rawdict non-space {n_raw}")
    print(f"own glyphs found in trace {own_found} of {len(own_chars)}; spans mixing own and foreign {mixed}; seqno not a text entry {bad_seqno}")
    print(f"M={m:.2f} band y=[{top:.2f},{bottom:.2f}] cropbox x1={page.cropbox.x1:.2f}")

    for label, idx in (("char bbox (lower bound)", 0), ("span entry (fallback box)", 1)):
        boxes = [(f[idx], f[2]) for f in foreign]
        hits = sum(1 for fb, _ in boxes if any(meets(grown(fb), ob) for ob in own_boxes))
        stroke_hits = sum(1 for fb, t in boxes if t == 1 and any(meets(grown(fb), ob) for ob in own_boxes))
        right = [fb[0] - MARGIN - m for fb, _ in boxes if fb[2] > m and fb[3] > top and fb[1] < bottom]
        room = min([page.cropbox.x1 - m] + [max(0.0, v) for v in right])
        print(f"foreign glyphs by {label}: admission hits {hits} (stroke spans {stroke_hits}); in band right of M {len(right)}; hang_room {room:.2f}")

    def gap(a, b) -> float:
        return max(0.0, a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])

    near = sorted((min(gap(fb, ob) for ob in own_boxes), t) for fb, _, t in foreign)[:3]
    print("nearest foreign glyphs by char bbox (gap, span type):", [(round(g, 2), t) for g, t in near])
    strip = fitz.Rect(m + 1.0, top, page.cropbox.x1, bottom)
    print("strip right of M renders in one colour:", ink_box(page, strip) is None, r2(strip))


if len(sys.argv) > 2:
    reference(sys.argv[1], sys.argv[2:])
else:
    text_cases()
    shading_cases()
    pattern_cases()
