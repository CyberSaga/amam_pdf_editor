"""Round-15 probes for the C.4 object set (plan S0 probes 8 and 9). Prints numbers only, never text.

Usage:
  python -I r15_probe_object_set.py                 probe 8 on a synthetic page built in memory
  python -I r15_probe_object_set.py <pdf> [page]    probe 9: clearance of every text block on a real page

Probe 8 asks what the compiled extraction reports: which `get_bboxlog` codes exist for a filled path,
strokes (hairline, wide, mitred), an image, a cropped image, an image mask (XObject and inline), a
clipped shading, and the same painted inside a Form XObject; whether Form text is in the texttrace;
and how far the rendered ink of upright / skewed / stroked / scaled text passes its texttrace bbox.
Probe 9 reports, per text block, the smallest gap (larger of the x and y gaps) to objects that are
not its own glyphs. A block is only an approximation of a plan paragraph.
"""
from __future__ import annotations

import sys

import fitz

H = 800.0
TEXT_CODES = {"fill-text", "stroke-text", "ignore-text"}


def r2(rect) -> tuple:
    return tuple(round(v, 2) for v in rect)


def build() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=600, height=H)

    def obj(body: str, stream: bytes | None = None) -> int:
        xref = doc.get_new_xref()
        doc.update_object(xref, body)
        if stream is not None:
            doc.update_stream(xref, stream, compress=False)
        return xref

    font = obj("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    img = obj(
        "<</Type/XObject/Subtype/Image/Width 2/Height 2/ColorSpace/DeviceGray/BitsPerComponent 8>>",
        b"\x00\x60\x60\x00",
    )
    mask = obj(
        "<</Type/XObject/Subtype/Image/Width 8/Height 8/ImageMask true/BitsPerComponent 1>>",
        b"\xaa\x55" * 4,
    )
    shade = obj(
        "<</ShadingType 2/ColorSpace/DeviceRGB/Coords[0 0 600 0]/Extend[true true]"
        "/Function<</FunctionType 2/Domain[0 1]/C0[1 0 0]/C1[0 0 1]/N 1>>>>"
    )
    res = (
        f"<</Font<</F1 {font} 0 R>>/XObject<</Im {img} 0 R/Mk {mask} 0 R%s>>"
        f"/Shading<</Sh {shade} 0 R>>>>"
    )
    form_stream = (
        b"BT /F1 20 Tf 50 500 Td (Ag) Tj ET\n"
        b"0 g 150 500 20 10 re f\n"
        b"q 20 0 0 20 250 500 cm /Im Do Q\n"
        b"q 20 0 0 20 350 500 cm /Mk Do Q\n"
        b"q 450 500 20 10 re W n /Sh sh Q\n"
        b"2 w 520 500 m 520 520 l S\n"
    )
    form = obj(f"<</Type/XObject/Subtype/Form/BBox[0 0 600 800]/Resources {res % ''}>>", form_stream)
    content = (
        b"0 g 50 700 20 10 re f\n"
        b"0 w 100 700 m 100 720 l S\n"
        b"4 w 150 700 m 150 720 l S\n"
        b"4 w 10 M 200 700 m 210 720 l 220 700 l S\n"
        b"q 20 0 0 20 250 700 cm /Im Do Q\n"
        b"q 300 700 5 5 re W n 20 0 0 20 300 700 cm /Im Do Q\n"
        b"q 20 0 0 20 350 700 cm /Mk Do Q\n"
        b"q 20 0 0 20 400 700 cm BI /W 8 /H 8 /IM true /BPC 1 ID " + b"\xaa\x55" * 4 + b" EI Q\n"
        b"q 450 700 20 10 re W n /Sh sh Q\n"
        b"BT /F1 20 Tf 50 600 Td (Ag) Tj ET\n"
        b"BT /F1 20 Tf 1 0 0.5 1 150 600 Tm (Ag) Tj ET\n"
        b"BT /F1 20 Tf 1 Tr 6 w 250 600 Td (Ag) Tj ET\n"
        b"BT /F1 20 Tf 0 Tr 200 Tz 350 600 Td (Ag) Tj ET\n"
        b"/Fm Do\n"
    )
    c = obj("<<>>", content)
    doc.xref_set_key(page.xref, "Resources", res % f"/Fm {form} 0 R")
    doc.xref_set_key(page.xref, "Contents", f"{c} 0 R")
    return fitz.open("pdf", doc.tobytes())


def ink_box(page: fitz.Page, clip: fitz.Rect, zoom: int = 4) -> tuple | None:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    w, h, data = pix.width, pix.height, pix.samples
    xs: list[int] = []
    ys: list[int] = []
    for y in range(h):
        row = data[y * pix.stride : y * pix.stride + w]
        if min(row) < 250:
            ys.append(y)
            xs.extend(i for i, v in enumerate(row) if v < 250)
    if not ys:
        return None
    ox, oy = pix.x / zoom, pix.y / zoom
    return (ox + min(xs) / zoom, oy + min(ys) / zoom, ox + (max(xs) + 1) / zoom, oy + (max(ys) + 1) / zoom)


def probe8() -> None:
    doc = build()
    page = doc[0]
    print("expected painted extents (top-left coords): fill [50,90,70,100]; hairline x=100 y 80..100;")
    print("  wide stroke [148,80,152,100]; mitre 200..220 apex y=80; image [250,80,270,100];")
    print("  cropped image [300,95,305,100]; mask [350,80,370,100]; inline mask [400,80,420,100];")
    print("  clipped shading [450,90,470,100]; Form row is 200 pt lower")
    print("-- get_bboxlog")
    for code, rect in page.get_bboxlog():
        print("  ", code, r2(rect))
    print("-- get_drawings")
    for d in page.get_drawings():
        print("  ", d["type"], "width", d.get("width"), r2(d["rect"]))
    print("-- get_image_info")
    for im in page.get_image_info():
        print("  ", r2(im["bbox"]))
    print("-- texttrace spans (bbox), then per-case ink vs trace bbox")
    spans = page.get_texttrace()
    for sp in spans:
        print("  ", sp["font"], "type", sp["type"], "size", sp["size"], "n", len(sp["chars"]), r2(sp["bbox"]))
    names = ["upright", "skew 0.5", "stroke 6w", "Tz 200", "form upright"]
    for name, sp in zip(names, spans):
        boxes = [fitz.Rect(ch[3]) for ch in sp["chars"]]
        union = boxes[0]
        for b in boxes[1:]:
            union |= b
        ink = ink_box(page, union + (-40, -40, 40, 40))
        over = (union.x0 - ink[0], union.y0 - ink[1], ink[2] - union.x1, ink[3] - union.y1)
        print(f"   {name}: trace {r2(union)} ink {r2(ink)} ink passes trace by L,T,R,B = {r2(over)}")


def gap(a, b) -> float:
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return max(dx, dy)


def probe9(path: str, pno: int) -> None:
    page = fitz.open(path)[pno]
    log = page.get_bboxlog()
    codes: dict[str, int] = {}
    for code, _ in log:
        codes[code] = codes.get(code, 0) + 1
    print("bboxlog codes:", sorted(codes.items()))
    blocks = [b for b in page.get_text("rawdict")["blocks"] if b.get("lines")]
    chars = [
        [ch["bbox"] for ln in b["lines"] for sp in ln["spans"] for ch in sp["chars"] if not ch["c"].isspace()]
        for b in blocks
    ]
    n_raw = sum(len(c) for c in chars)
    n_trace = sum(1 for sp in page.get_texttrace() for ch in sp["chars"] if ch[0] not in (32, 160, 0x3000))
    print("rawdict non-space chars:", n_raw, " texttrace non-space chars:", n_trace)
    others = [("nontext:" + code, tuple(rect)) for code, rect in log if code not in TEXT_CODES]
    others += [("annot", tuple(a.rect)) for a in page.annots() or []]
    others += [("widget", tuple(w.rect)) for w in page.widgets() or []]
    print("non-text objects:", len(others), " (page-sized ones listed)")
    big = page.rect.get_area() * 0.5
    for kind, r in others:
        if fitz.Rect(r).get_area() > big:
            print("   page-sized:", kind, r2(r))
    for i, own in enumerate(chars):
        if not own:
            continue
        best_obj = min(((gap(c, r), kind) for c in own for kind, r in others), default=(None, None))
        best_txt = min(
            (gap(c, o) for j, oth in enumerate(chars) if j != i for o in oth for c in own), default=None
        )
        lines = len(blocks[i]["lines"])
        txt = "none" if best_txt is None else f"{best_txt:.2f}"
        obj = "none" if best_obj[0] is None else f"{best_obj[0]:.2f} ({best_obj[1]})"
        print(f"block {i}: lines {lines} chars {len(own)} nearest other-block char {txt} nearest non-text {obj}")


if len(sys.argv) > 1:
    probe9(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
else:
    probe8()
