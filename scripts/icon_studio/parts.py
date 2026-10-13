"""Shared parts for the function-icon pixel-grid designs (16 / 24 / 48 px).

The set's style comes from 03_儲存 (sessions save_03_g48/g24/g16): navy ink, peach
hamster with pink inner ears, white muzzle, eyes with a white catchlight. Batch
scripts import these so every icon draws the hamster, pages and badges the same way.

Append-only: finished sessions replay through these functions, so change behaviour
only behind a new parameter whose default keeps the old output (replays must stay
byte-identical to the shipped SVGs).

    python3 scripts/icon_studio/parts.py fit view/resources/function_icons/28_插入空白頁.png 48
        -> ref_map that fits the reference's drawing (card excluded) into the grid
"""
from __future__ import annotations

import sys

from geo import f

# ---------------------------------------------------------------- palette
INK = "#1E1D38"
PEACH = "#F6C58E"
PEACH_SHADE = "#E5A86A"
EAR_IN = "#F2A3A0"
WHITE = "#FFFFFF"
BLUSH48 = "#F48FA0"
BLUSH = "#F6A3B0"
NOSE48 = "#E35D6A"
NOSE = "#EC7684"
MOUTH = "#D49AA4"
PURPLE = "#9285D5"
PURPLE_LIGHT = "#B9AEEB"
PURPLE_DARK = "#6A5EB6"
TEAL = "#7DD3C9"
TEAL_DARK = "#3E9E95"
YELLOW = "#FDD978"
YELLOW_DARK = "#E3B04B"
RED = "#D9434A"
PAPER = "#FFFFFF"
PAPER_SHADE = "#E6E5F0"
LINE = "#B3AFD6"

# Line weights per grid: object outline, inner lines.
OUTLINE = {48: 2.5, 24: 1.5, 16: 1.0}
INNER = {48: 1.5, 24: 1.0, 16: 1.0}

# Default pixel-map legend: char -> (id suffix, colour). Order = paint order.
LEGEND = {
    "P": ("peach", PEACH),
    "S": ("peach_shade", PEACH_SHADE),
    "W": ("muzzle", WHITE),
    "N": ("outline", INK),
    "K": ("ears_in", EAR_IN),
    "E": ("eyes", INK),
    "H": ("eyes_hl", WHITE),
    "B": ("blush", BLUSH),
    "R": ("nose", NOSE),
    "M": ("mouth", MOUTH),
}


# ---------------------------------------------------------------- pixel maps
def pix_d(rows: list[str], ch: str, x0: int = 0, y0: int = 0) -> str:
    """Path data covering every cell equal to ``ch`` (horizontal runs merged)."""
    out = []
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            if row[c] != ch:
                c += 1
                continue
            start = c
            while c < len(row) and row[c] == ch:
                c += 1
            out.append(f"M{x0 + start} {y0 + r}h{c - start}v1h-{c - start}Z")
    return "".join(out)


def pixmap(s, prefix: str, rows: list[str], x0: int, y0: int, layer: str,
           legend: dict | None = None, anim: str = "pop") -> list[str]:
    """Add one path per legend char present in ``rows`` ('.' = empty); returns the ids."""
    legend = legend or LEGEND
    ids = []
    for ch, (suffix, color) in legend.items():
        d = pix_d(rows, ch, x0, y0)
        if d:
            ids.append(s.add(f"{prefix}_{suffix}", "path", layer, d=d, fill=color, anim=anim))
    return ids


# ---------------------------------------------------------------- pixel hamsters (24 / 16)
# Settled on 28_插入空白頁 (10 variants tried): a free-standing hamster reads as a cat
# when its head is boxed in navy with a V chin; a chubby head+body "bean" that is
# widest at the cheeks reads as the 03_儲存 hamster. Rows top to bottom; '.' empty.
BEAN24 = [  # 10 x 11; left outline column may hide under an object's edge
    ".NN....NN.",
    "NKKNNNNKKN",
    "NPPPPPPPPN",
    "NPHEPPHEPN",
    "NPEEWWEEPN",
    "NBWWRRWWBN",
    "NPWWWWWWSN",
    "NPPWWWWPSN",
    "NPPWWWWPSN",
    ".NPPPPPSN.",
    "..NNNNNN..",
]
FACE24 = BEAN24[:6]  # head only (ears to nose row), for hamsters cut by an edge below
FACE16 = [  # 7 x 8; no side outlines (an object edge or the background bounds it)
    ".NN.NN.",
    ".KKPKK.",
    "PHEPHEP",
    "PEEPEEP",
    "BWWRWWB",
    "PPWWWPP",
    "PPPPPPP",
    ".PPPPP.",
]
PEEK24 = [  # 8 x 6 head peeking over an edge (26_旋轉頁): no side outlines below the ears
    ".NN..NN.",
    "NKKNNKKN",
    "PPPPPPPP",
    "PHEPPHEP",
    "PEEWWEEP",
    "BWWRRWWB",
]
PEEK16 = FACE16[:5]  # 7 x 5: ear caps to the nose row
PAW24 = [".NN.", "NPPN", ".NN."]


def plus_px_d(cx: int, cy: int, arm: int) -> str:
    """1-px-bar plus centred on pixel (cx, cy), reaching ``arm`` pixels out (whole-pixel edges)."""
    return (f"M{cx} {cy - arm}h1v{arm}h{arm}v1h-{arm}v{arm}h-1v-{arm}h-{arm}v-1h{arm}Z")


def badge_plus(s, p: str, grid: int, cx: float, cy: float, layer: str = "badge") -> None:
    """Purple plus badge, sized per grid (outer edge on whole pixels).

    48: centre on a pixel centre, outer radius 6.5, 1.5 px ring, 3-px-bar plus.
    24: outer radius 4, 1 px ring, 5x5 1-px plus.  16: outer radius 3.5, 1 px ring, 5x5 plus.
    """
    if grid == 48:
        s.add(f"{p}_disc", "circle", layer, cx=cx, cy=cy, r=5.75, fill=PURPLE, stroke=INK, stroke_width=1.5, anim="fill")
        s.add(f"{p}_plus", "path", layer, d=plus_d(cx, cy, 3.5, 3), fill=WHITE, anim="pop")
        return
    r = 3.5 if grid == 24 else 3.0
    s.add(f"{p}_disc", "circle", layer, cx=cx, cy=cy, r=r, fill=PURPLE, stroke=INK, stroke_width=1, anim="fill")
    s.add(f"{p}_plus", "path", layer, d=plus_px_d(int(cx), int(cy), 2), fill=WHITE, anim="pop")


# ---------------------------------------------------------------- 48 px hamster
def hamster48(s, p: str, cx: float, cy: float, rx: float, ry: float, layer: str = "hamster",
              k: float = 1.0, whiskers: bool = True, mouth: bool = True, eye_y: float | None = None,
              outline: float = 1.25, rot: float = 0.0, parts: tuple[str, ...] = ("blocks", "face")) -> None:
    """Vector hamster head: ears, head ellipse, muzzle, eyes + catchlights, nose, mouth, whiskers, blush.

    ``k`` scales the facial features (1.0 = the 03_儲存 48 px face, head rx ~9.6).
    ``eye_y`` defaults to just above the head centre; everything else hangs off it.
    ``rot`` tilts the whole head (degrees, clockwise) about its centre. ``parts`` lets a
    batch lay in the blocks (ears + head) first and the face later.
    """
    from geo import smooth_d

    tf = {"transform": f"rotate({f(rot)} {f(cx)} {f(cy)})"} if rot else {}
    ey = cy - 0.06 * ry if eye_y is None else eye_y
    if "blocks" in parts:
        for i, sgn in enumerate((-1, 1)):
            ex = cx + sgn * 0.6 * rx
            ecy = cy - ry + 1.3 * k
            s.add(f"{p}_ear{i}", "circle", layer, cx=ex, cy=ecy, r=3.0 * k, fill=PEACH, stroke=INK,
                  stroke_width=outline, anim="fill", **tf)
            s.add(f"{p}_ear{i}_in", "circle", layer, cx=ex - sgn * 0.55 * k, cy=ecy + 0.4 * k, r=1.55 * k,
                  fill=EAR_IN, anim="fill", **tf)
        s.add(f"{p}_head", "ellipse", layer, cx=cx, cy=cy, rx=rx, ry=ry, fill=PEACH, stroke=INK,
              stroke_width=outline, anim="fill", **tf)
    if "face" not in parts:
        return
    # muzzle: white lower face with a peak between the eyes (the 03_儲存 48 px shape)
    my = ey + 1.7 * k
    side = rx * 0.93
    top = [(cx - side * 0.98, my + 1.0 * k), (cx - 4.8 * k, my), (cx - 2.4 * k, my + 0.3 * k),
           (cx, my - 1.3 * k), (cx + 2.4 * k, my + 0.3 * k), (cx + 4.8 * k, my), (cx + side * 0.98, my + 1.0 * k)]
    bottom = cy + ry * 0.93
    d = (smooth_d(top) + f"Q{f(cx + side)} {f(bottom - 0.2 * ry)} {f(cx)} {f(bottom)}"
         f"Q{f(cx - side)} {f(bottom - 0.2 * ry)} {f(top[0][0])} {f(top[0][1])}Z")
    s.add(f"{p}_muzzle", "path", layer, d=d, fill=WHITE, anim="fill", **tf)
    for i, sgn in enumerate((-1, 1)):
        ex = cx + sgn * 3.6 * k
        s.add(f"{p}_eye{i}", "ellipse", layer, cx=ex, cy=ey, rx=1.25 * k, ry=1.6 * k, fill=INK, anim="pop", **tf)
        s.add(f"{p}_eye{i}_hl", "circle", layer, cx=ex - 0.4 * k, cy=ey - 0.6 * k, r=0.55 * k, fill=WHITE,
              anim="pop", **tf)
    ny = ey + 2.05 * k
    s.add(f"{p}_nose", "path", layer,
          d=f"M{f(cx - 0.95 * k)} {f(ny)}Q{f(cx)} {f(ny - 0.4 * k)} {f(cx + 0.95 * k)} {f(ny)}"
            f"Q{f(cx + 0.6 * k)} {f(ny + 0.85 * k)} {f(cx)} {f(ny + 1.1 * k)}"
            f"Q{f(cx - 0.6 * k)} {f(ny + 0.85 * k)} {f(cx - 0.95 * k)} {f(ny)}Z",
          fill=NOSE48, anim="pop", **tf)
    if mouth:
        my2 = ny + 1.45 * k
        s.add(f"{p}_mouth", "path", layer,
              d=f"M{f(cx - 1.9 * k)} {f(my2)}Q{f(cx - 1.0 * k)} {f(my2 + 1.05 * k)} {f(cx)} {f(my2 - 0.05 * k)}"
                f"Q{f(cx + 1.0 * k)} {f(my2 + 1.05 * k)} {f(cx + 1.9 * k)} {f(my2)}",
              fill="none", stroke=INK, stroke_width=0.8 * min(1.0, k + 0.15), stroke_linecap="round",
              stroke_linejoin="round", anim="draw", **tf)
    if whiskers:
        wy = ey + 1.8 * k
        for i, (dy0, dy1) in enumerate(((0.0, -0.6), (1.3, 1.8))):
            x0, x1 = rx * 0.77, rx * 1.05
            for side_name, sgn in (("l", -1), ("r", 1)):
                s.add(f"{p}_whisker_{side_name}{i}", "path", layer,
                      d=f"M{f(cx + sgn * x0)} {f(wy + dy0 * k)}L{f(cx + sgn * x1)} {f(wy + dy1 * k)}",
                      fill="none", stroke=INK, stroke_width=0.6, stroke_linecap="round", anim="draw", **tf)
    for i, sgn in enumerate((-1, 1)):
        s.add(f"{p}_blush{i}", "ellipse", layer, cx=cx + sgn * 5.8 * k, cy=ey + 2.4 * k, rx=1.5 * k, ry=0.85 * k,
              fill=BLUSH48, fill_opacity=0.55, anim="pop", **tf)


def paw48(s, eid: str, cx: float, cy: float, layer: str = "hamster", k: float = 1.0, outline: float = 1.0) -> str:
    """A small peach paw (resting on an edge)."""
    return s.add(eid, "ellipse", layer, cx=cx, cy=cy, rx=1.9 * k, ry=1.45 * k, fill=PEACH, stroke=INK,
                 stroke_width=outline, anim="pop")


# ---------------------------------------------------------------- 48 px hamster, 03_儲存 construction
# User feedback (2026-10-13): the first set's hamsters looked "weird, not as delicate as
# 03". 03's head is the top of a tall ellipse cut flat at an edge (a wide dome, widest at
# the cheeks), frontal, with the face in the lower two thirds. These builders reproduce
# that construction exactly (k = 1 is 03's head, 19.1 px wide at the base line).
def _dome_geom(cx: float, base: float, k: float):
    rx, ry = 9.6 * k, 11.0 * k
    cy = base + 1.2 * k
    return rx, ry, cy


def hamster_face48(s, p: str, cx: float, base: float, k: float = 1.0, layer: str = "hamster",
                   whiskers: bool = True, mouth: bool = True, parts: tuple[str, ...] = ("blocks", "face"),
                   head: bool = True, outline: float = 1.25, chin: float | None = None) -> None:
    """03_儲存's hamster head, scaled by ``k`` and placed so its flat bottom sits on ``base``.

    ``head=False`` skips the dome outline (when a body silhouette already draws it).
    ``chin`` (x k, below ``base``): end the white muzzle in a rounded snout instead of a band
    cut flat at the base — for heads that are not cut by an edge.
    """
    import math

    from geo import smooth_d

    rx, ry, cy = _dome_geom(cx, base, k)
    if "blocks" in parts:
        for i, sgn in enumerate((-1, 1)):
            ex, ey = cx + sgn * 5.7 * k, base - 8.4 * k
            s.add(f"{p}_ear{i}", "circle", layer, cx=ex, cy=ey, r=3.0 * k, fill=PEACH, stroke=INK,
                  stroke_width=outline, anim="fill")
            s.add(f"{p}_ear{i}_in", "circle", layer, cx=ex - sgn * 0.55 * k, cy=ey + 0.4 * k, r=1.55 * k,
                  fill=EAR_IN, anim="fill")
        if head:
            w0 = rx * math.sqrt(1 - ((base - cy) / ry) ** 2)
            s.add(f"{p}_head", "path", layer,
                  d=f"M{f(cx - w0)} {f(base)}A{f(rx)} {f(ry)} 0 1 1 {f(cx + w0)} {f(base)}Z",
                  fill=PEACH, stroke=INK, stroke_width=outline, stroke_linejoin="round", anim="fill")
    if "face" not in parts:
        return
    kk = 0.93

    def side(y):
        return rx * kk * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * kk)) ** 2))

    ys = base - 2.8 * k
    top = [(cx - side(ys), ys), (cx - 4.8 * k, base - 3.8 * k), (cx - 2.4 * k, base - 3.5 * k), (cx, base - 5.1 * k),
           (cx + 2.4 * k, base - 3.5 * k), (cx + 4.8 * k, base - 3.8 * k), (cx + side(ys), ys)]
    if chin is None:
        tail = f"L{f(cx + side(base))} {f(base)}L{f(cx - side(base))} {f(base)}Z"
    else:
        sx, cb = side(ys) * 0.93, base + chin * k
        tail = (f"C{f(cx + sx + 0.4 * k)} {f(base)} {f(cx + 3.2 * k)} {f(cb)} {f(cx)} {f(cb)}"
                f"C{f(cx - 3.2 * k)} {f(cb)} {f(cx - sx - 0.4 * k)} {f(base)} {f(top[0][0])} {f(top[0][1])}Z")
    s.add(f"{p}_muzzle", "path", layer, d=smooth_d(top) + tail, fill=WHITE, anim="fill")
    for i, sgn in enumerate((-1, 1)):
        ex = cx + sgn * 3.6 * k
        s.add(f"{p}_eye{i}", "ellipse", layer, cx=ex, cy=base - 5.5 * k, rx=1.25 * k, ry=1.6 * k, fill=INK, anim="pop")
        s.add(f"{p}_eye{i}_hl", "circle", layer, cx=ex - 0.4 * k, cy=base - 6.1 * k, r=0.55 * k, fill=WHITE, anim="pop")
    n0 = base - 3.45 * k
    s.add(f"{p}_nose", "path", layer,
          d=f"M{f(cx - 0.95 * k)} {f(n0)}Q{f(cx)} {f(n0 - 0.4 * k)} {f(cx + 0.95 * k)} {f(n0)}"
            f"Q{f(cx + 0.6 * k)} {f(n0 + 0.85 * k)} {f(cx)} {f(n0 + 1.1 * k)}Q{f(cx - 0.6 * k)} {f(n0 + 0.85 * k)} {f(cx - 0.95 * k)} {f(n0)}Z",
          fill=NOSE48, anim="pop")
    if mouth:
        m0 = base - 2.0 * k
        s.add(f"{p}_mouth", "path", layer,
              d=f"M{f(cx - 1.9 * k)} {f(m0)}Q{f(cx - 1.0 * k)} {f(m0 + 1.05 * k)} {f(cx)} {f(m0 - 0.05 * k)}"
                f"Q{f(cx + 1.0 * k)} {f(m0 + 1.05 * k)} {f(cx + 1.9 * k)} {f(m0)}",
              fill="none", stroke=INK, stroke_width=max(0.6, 0.8 * k), stroke_linecap="round",
              stroke_linejoin="round", anim="draw")
    if whiskers:
        for i, (y0, y1) in enumerate(((3.7, 4.3), (2.4, 1.9))):
            for nm, sgn in (("l", -1), ("r", 1)):
                s.add(f"{p}_whisker_{nm}{i}", "path", layer,
                      d=f"M{f(cx + sgn * 7.4 * k)} {f(base - y0 * k)}L{f(cx + sgn * 10.1 * k)} {f(base - y1 * k)}",
                      fill="none", stroke=INK, stroke_width=0.6, stroke_linecap="round", anim="draw")
    for i, sgn in enumerate((-1, 1)):
        s.add(f"{p}_blush{i}", "ellipse", layer, cx=cx + sgn * 5.8 * k, cy=base - 3.1 * k, rx=1.5 * k, ry=0.85 * k,
              fill=BLUSH48, fill_opacity=0.55, anim="pop")


def hamster_bean48(s, p: str, cx: float, base: float, k: float = 1.0, layer: str = "hamster",
                   body: float = 12.0, whiskers: bool = True, arms: tuple[bool, bool] = (True, True),
                   feet: bool = True, parts: tuple[str, ...] = ("blocks", "face"), outline: float = 1.25,
                   arm_pos: tuple[float, float] = (4.6, 0.36)) -> None:
    """Whole chubby hamster: 03's dome head flowing into a pear-shaped body ``body`` px tall (x k).

    One silhouette for head and body (no neck line). The body tucks in under the cheeks and
    widens toward the feet; a cream chest patch sits below the white muzzle band; the arms are
    small paws held in front of the chest (``arm_pos`` = x offset, y as a fraction of the body).
    ``base`` is the line where the head's cheeks are widest (the face sits above it).
    """
    import math

    from geo import smooth_d

    rx, ry, cy = _dome_geom(cx, base, k)
    b = body * k
    w0 = rx * math.sqrt(1 - ((base - cy) / ry) ** 2)
    if "blocks" in parts:
        if feet:
            for i, sgn in enumerate((-1, 1)):
                s.add(f"{p}_foot{i}", "ellipse", layer, cx=cx + sgn * 4.0 * k, cy=base + b - 0.3 * k, rx=2.5 * k,
                      ry=1.4 * k, fill=PEACH, stroke=INK, stroke_width=1.0, anim="fill")
        # ears first: the head covers their lower half, as in 03 (drawn after the body they
        # sat on top of the dome with their full navy rings — fixed after review)
        hamster_face48(s, p, cx, base, k, layer, parts=("blocks",), head=False, outline=outline)
        right = [(cx + w0, base), (cx + w0 * 0.9, base + b * 0.3), (cx + w0 * 0.98, base + b * 0.7),
                 (cx + w0 * 0.62, base + b * 0.97), (cx, base + b)]
        left = [(2 * cx - x, y) for x, y in reversed(right)]
        rd, ld = smooth_d(right), smooth_d(left)
        body_d = (f"M{f(cx - w0)} {f(base)}A{f(rx)} {f(ry)} 0 1 1 {f(cx + w0)} {f(base)}"
                  + rd[rd.index("C"):] + ld[ld.index("C"):] + "Z")
        s.add(f"{p}_body", "path", layer, d=body_d, fill=PEACH, stroke=INK, stroke_width=outline,
              stroke_linejoin="round", anim="fill")
        s.add(f"{p}_belly", "ellipse", layer, cx=cx, cy=base + b * 0.56, rx=w0 * 0.44, ry=b * 0.34, fill="#FFF4E3",
              anim="fill")
    if "face" not in parts:
        return
    hamster_face48(s, p, cx, base, k, layer, whiskers=whiskers, parts=("face",), chin=2.4)
    ax, ay = arm_pos
    pts = [(cx + sgn * ax * k, base + b * ay) for on, sgn in zip(arms, (-1, 1)) if on]
    if pts:
        s.add(f"{p}_arms", "path", layer, d="".join(paw_d(x, y, k * 0.75) for x, y in pts), fill=PEACH,
              stroke=PEACH_SHADE, stroke_width=0.9, stroke_linejoin="round", anim="pop")


def _px_features(s, p: str, cx: float, base: float, k: float, layer: str, grid: int) -> None:
    """Whole-pixel eyes (2x2, catchlight top-left), nose and blush for a vector head at 24/16 px."""
    ey = int(round(base - 5.5 * k - 1.0))
    xl = int(round(cx - 3.6 * k - 1.0))
    xr = int(round(2 * cx - xl - 2))
    s.add(f"{p}_eyes", "path", layer, d=f"M{xl} {ey}h2v2h-2ZM{xr} {ey}h2v2h-2Z", fill=INK, anim="pop")
    s.add(f"{p}_eyes_hl", "path", layer, d=f"M{xl} {ey}h1v1h-1ZM{xr} {ey}h1v1h-1Z", fill=WHITE, anim="pop")
    ny = ey + 2
    nx0 = cx - (1 if float(cx).is_integer() else 0.5)
    nw = 2 if float(cx).is_integer() else 1
    s.add(f"{p}_nose", "path", layer, d=f"M{f(nx0)} {ny}h{nw}v1h-{nw}Z", fill=NOSE, anim="pop")
    if grid >= 24:
        s.add(f"{p}_blush", "path", layer, d=f"M{xl - 1} {ny}h1v1h-1ZM{xr + 2} {ny}h1v1h-1Z", fill=BLUSH, anim="pop")


def _ears_d(cx: float, base: float, k: float, inner: bool) -> str:
    out = []
    for sgn in (-1, 1):
        ex, ey = cx + sgn * 5.7 * k, base - 8.4 * k
        if inner:
            ex, ey, r = ex - sgn * 0.55 * k, ey + 0.4 * k, 1.55 * k
        else:
            r = 3.0 * k
        out.append(f"M{f(ex - r)} {f(ey)}A{f(r)} {f(r)} 0 1 1 {f(ex + r)} {f(ey)}A{f(r)} {f(r)} 0 1 1 {f(ex - r)} {f(ey)}Z")
    return "".join(out)


def hamster_face_px(s, p: str, grid: int, cx: float, base: float, k: float, layer: str = "hamster",
                    chin: float | None = None) -> None:
    """The 48 px hamster head carried to 24/16 px: the same vector dome, ears and muzzle with a
    1 px outline (round silhouette), eyes/nose/blush as whole pixels (crisp). Merged paths keep
    it to 8 elements. ``base`` and ``cx`` as in :func:`hamster_face48`.
    """
    import math

    from geo import smooth_d

    rx, ry, cy = _dome_geom(cx, base, k)
    s.add(f"{p}_ears", "path", layer, d=_ears_d(cx, base, k, False), fill=PEACH, stroke=INK, stroke_width=1, anim="fill")
    s.add(f"{p}_ears_in", "path", layer, d=_ears_d(cx, base, k, True), fill=EAR_IN, anim="fill")
    w0 = rx * math.sqrt(1 - ((base - cy) / ry) ** 2)
    s.add(f"{p}_head", "path", layer, d=f"M{f(cx - w0)} {f(base)}A{f(rx)} {f(ry)} 0 1 1 {f(cx + w0)} {f(base)}Z",
          fill=PEACH, stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
    kk = 0.93

    def side(y):
        return rx * kk * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * kk)) ** 2))

    ys = base - 2.8 * k
    top = [(cx - side(ys), ys), (cx - 4.8 * k, base - 3.8 * k), (cx - 2.4 * k, base - 3.5 * k), (cx, base - 5.1 * k),
           (cx + 2.4 * k, base - 3.5 * k), (cx + 4.8 * k, base - 3.8 * k), (cx + side(ys), ys)]
    if chin is None:
        tail = f"L{f(cx + side(base))} {f(base)}L{f(cx - side(base))} {f(base)}Z"
    else:
        sx, cb = side(ys) * 0.93, base + chin * k
        tail = (f"C{f(cx + sx + 0.4 * k)} {f(base)} {f(cx + 3.2 * k)} {f(cb)} {f(cx)} {f(cb)}"
                f"C{f(cx - 3.2 * k)} {f(cb)} {f(cx - sx - 0.4 * k)} {f(base)} {f(top[0][0])} {f(top[0][1])}Z")
    s.add(f"{p}_muzzle", "path", layer, d=smooth_d(top) + tail, fill=WHITE, anim="fill")
    _px_features(s, p, cx, base, k, layer, grid)


def hamster_bean_px(s, p: str, grid: int, cx: float, base: float, k: float, layer: str = "hamster",
                    body: float = 12.0, feet: bool = True) -> None:
    """The 48 px chubby hamster (:func:`hamster_bean48`) carried to 24/16 px, like :func:`hamster_face_px`."""
    import math

    from geo import smooth_d

    rx, ry, cy = _dome_geom(cx, base, k)
    b = body * k
    w0 = rx * math.sqrt(1 - ((base - cy) / ry) ** 2)
    if feet:
        s.add(f"{p}_feet", "path", layer,
              d="".join(f"M{f(cx + sgn * 4.0 * k - 2.5 * k)} {f(base + b - 0.3 * k)}A{f(2.5 * k)} {f(1.4 * k)} 0 1 1 "
                        f"{f(cx + sgn * 4.0 * k + 2.5 * k)} {f(base + b - 0.3 * k)}A{f(2.5 * k)} {f(1.4 * k)} 0 1 1 "
                        f"{f(cx + sgn * 4.0 * k - 2.5 * k)} {f(base + b - 0.3 * k)}Z" for sgn in (-1, 1)),
              fill=PEACH, stroke=INK, stroke_width=1, anim="fill")
    s.add(f"{p}_ears", "path", layer, d=_ears_d(cx, base, k, False), fill=PEACH, stroke=INK, stroke_width=1, anim="fill")
    s.add(f"{p}_ears_in", "path", layer, d=_ears_d(cx, base, k, True), fill=EAR_IN, anim="fill")
    right = [(cx + w0, base), (cx + w0 * 0.9, base + b * 0.3), (cx + w0 * 0.98, base + b * 0.7),
             (cx + w0 * 0.62, base + b * 0.97), (cx, base + b)]
    left = [(2 * cx - x, y) for x, y in reversed(right)]
    rd, ld = smooth_d(right), smooth_d(left)
    s.add(f"{p}_body", "path", layer,
          d=f"M{f(cx - w0)} {f(base)}A{f(rx)} {f(ry)} 0 1 1 {f(cx + w0)} {f(base)}" + rd[rd.index("C"):] + ld[ld.index("C"):] + "Z",
          fill=PEACH, stroke=INK, stroke_width=1, stroke_linejoin="round", anim="fill")
    kk = 0.93

    def side(y):
        return rx * kk * math.sqrt(max(0.0, 1 - ((y - cy) / (ry * kk)) ** 2))

    ys = base - 2.8 * k
    top = [(cx - side(ys), ys), (cx - 4.8 * k, base - 3.8 * k), (cx - 2.4 * k, base - 3.5 * k), (cx, base - 5.1 * k),
           (cx + 2.4 * k, base - 3.5 * k), (cx + 4.8 * k, base - 3.8 * k), (cx + side(ys), ys)]
    sx, cb = side(ys) * 0.93, base + 2.4 * k
    belly_y, belly_rx, belly_ry = base + b * 0.56, w0 * 0.44, b * 0.34
    snout = (smooth_d(top) + f"C{f(cx + sx + 0.4 * k)} {f(base)} {f(cx + 3.2 * k)} {f(cb)} {f(cx)} {f(cb)}"
             f"C{f(cx - 3.2 * k)} {f(cb)} {f(cx - sx - 0.4 * k)} {f(base)} {f(top[0][0])} {f(top[0][1])}Z")
    belly = (f"M{f(cx - belly_rx)} {f(belly_y)}A{f(belly_rx)} {f(belly_ry)} 0 1 1 {f(cx + belly_rx)} {f(belly_y)}"
             f"A{f(belly_rx)} {f(belly_ry)} 0 1 1 {f(cx - belly_rx)} {f(belly_y)}Z")
    s.add(f"{p}_muzzle", "path", layer, d=snout + belly, fill=WHITE, anim="fill")
    _px_features(s, p, cx, base, k, layer, grid)


def paw_d(cx: float, cy: float, k: float = 1.0) -> str:
    """A small rounded paw (wider than tall) centred on (cx, cy)."""
    w, h = 2.3 * k, 1.6 * k
    return (f"M{f(cx - w)} {f(cy + 0.2 * k)}C{f(cx - w)} {f(cy - h)} {f(cx + w)} {f(cy - h)} {f(cx + w)} {f(cy + 0.2 * k)}"
            f"C{f(cx + w)} {f(cy + h * 0.9)} {f(cx - w)} {f(cy + h * 0.9)} {f(cx - w)} {f(cy + 0.2 * k)}Z")


def paws48(s, p: str, pts: list[tuple[float, float]], k: float = 1.0, layer: str = "front",
           outline: float = 1.0) -> None:
    """Paws resting on an edge: rounded peach pads with a navy rim and two toe marks each.

    On a peeking head keep them light (k ~0.75, ``outline`` 0.8) and outside the muzzle band.
    """
    s.add(f"{p}_pads", "path", layer, d="".join(paw_d(x, y, k) for x, y in pts), fill=PEACH, stroke=INK,
          stroke_width=outline, stroke_linejoin="round", anim="pop")
    toes = "".join(f"M{f(x - 0.75 * k)} {f(y - 0.9 * k)}V{f(y - 0.1 * k)}M{f(x + 0.75 * k)} {f(y - 0.9 * k)}V{f(y - 0.1 * k)}"
                   for x, y in pts)
    s.add(f"{p}_toes", "path", layer, d=toes, fill="none", stroke=INK, stroke_width=0.55, stroke_opacity=0.7,
          stroke_linecap="round", anim="draw")


# ---------------------------------------------------------------- pages and badges
def page_d(x0: float, y0: float, x1: float, y1: float, r: float, c: float) -> str:
    """Page outline with a dog-ear fold of size ``c`` at the top-right (fixed command sequence)."""
    return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - c)}L{f(x1)} {f(y0 + c)}V{f(y1 - r)}"
            f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}"
            f"V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")


def flap_d(x1: float, y0: float, c: float, r: float) -> str:
    """The folded-over corner triangle for :func:`page_d` (right angle at the bottom-left, rounded)."""
    return (f"M{f(x1 - c)} {f(y0)}V{f(y0 + c - r)}Q{f(x1 - c)} {f(y0 + c)} {f(x1 - c + r)} {f(y0 + c)}"
            f"H{f(x1)}Z")


def plus_d(cx: float, cy: float, arm: float, w: float) -> str:
    """A plus sign as one closed outline (bars ``w`` wide reaching ``arm`` from the centre)."""
    a, h = arm, w / 2
    pts = [(cx - h, cy - a), (cx + h, cy - a), (cx + h, cy - h), (cx + a, cy - h), (cx + a, cy + h),
           (cx + h, cy + h), (cx + h, cy + a), (cx - h, cy + a), (cx - h, cy + h), (cx - a, cy + h),
           (cx - a, cy - h), (cx - h, cy - h)]
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


# ---------------------------------------------------------------- PDF mark
# Acrobat-style ribbon: one stroke forming a triangle with a loop at each corner
# (unit box, y down; traced from 05_另存為最佳化的副本.png).
_PDF_MARK = [
    ("M", (0.47, 0.38)),
    ("C", (0.40, 0.20), (0.36, 0.02), (0.45, 0.01)),
    ("C", (0.55, 0.00), (0.53, 0.20), (0.45, 0.38)),
    ("C", (0.35, 0.60), (0.20, 0.80), (0.10, 0.88)),
    ("C", (0.02, 0.95), (0.05, 1.02), (0.15, 0.95)),
    ("C", (0.35, 0.80), (0.65, 0.70), (0.88, 0.72)),
    ("C", (1.00, 0.73), (0.98, 0.85), (0.88, 0.84)),
    ("C", (0.70, 0.82), (0.55, 0.62), (0.47, 0.38)),
]


def pdf_mark_d(x: float, y: float, w: float, h: float) -> str:
    """Path data of the red PDF ribbon mark fitted to the box (x, y, w, h); stroke it."""
    out = []
    for cmd, *pts in _PDF_MARK:
        out.append(cmd + " ".join(f"{f(x + px * w)} {f(y + py * h)}" for px, py in pts))
    return "".join(out) + "Z"


def mirror_x_d(d: str, width: float) -> str:
    """Mirror absolute M/L/H/V/Z path data horizontally inside a canvas of ``width``."""
    import re

    out, cmd, nums = [], None, []
    for tok in re.findall(r"[MLHVZ]|-?[\d.]+", d):
        if tok.isalpha():
            if cmd:
                out.append(_mirror_cmd(cmd, nums, width))
            cmd, nums = tok, []
        else:
            nums.append(float(tok))
    if cmd:
        out.append(_mirror_cmd(cmd, nums, width))
    return "".join(out)


def _mirror_cmd(cmd: str, nums: list[float], width: float) -> str:
    if cmd in "ML":
        return cmd + " ".join(f"{f(width - nums[i])} {f(nums[i + 1])}" for i in range(0, len(nums), 2))
    if cmd == "H":
        return "H" + " ".join(f(width - n) for n in nums)
    if cmd == "V":
        return "V" + " ".join(f(n) for n in nums)
    return cmd


# ---------------------------------------------------------------- arrows
def arc_arrow(s, p: str, cx: float, cy: float, r: float, a0: float, a1: float, layer: str, *,
              width: float, head_w: float, head_len: float, color: str, ink_width: float = 0.0,
              transform: str | None = None) -> None:
    """Arc from angle ``a0`` clockwise to ``a1`` (degrees, 0 = right, 90 = down) ending in a triangle head.

    ``ink_width`` > 0 (48 px) lays a navy arc under the coloured one and outlines the head,
    giving the arrow a navy edge; 0 (24/16 px) draws a plain solid arrow. ``head_w`` is the
    half-width of the head's base.
    """
    import math

    def at(a):
        tt = math.radians(a)
        return cx + r * math.cos(tt), cy + r * math.sin(tt)

    p0, p1 = at(a0), at(a1)
    sweep = (a1 - a0) % 360
    arc = f"M{f(p0[0])} {f(p0[1])}A{f(r)} {f(r)} 0 {1 if sweep > 180 else 0} 1 {f(p1[0])} {f(p1[1])}"
    tan = (-math.sin(math.radians(a1)), math.cos(math.radians(a1)))
    nrm = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
    c1 = (p1[0] + nrm[0] * head_w, p1[1] + nrm[1] * head_w)
    c2 = (p1[0] - nrm[0] * head_w, p1[1] - nrm[1] * head_w)
    tip = (p1[0] + tan[0] * head_len, p1[1] + tan[1] * head_len)
    head = f"M{f(c1[0])} {f(c1[1])}L{f(tip[0])} {f(tip[1])}L{f(c2[0])} {f(c2[1])}Z"
    tf = {"transform": transform} if transform else {}
    if ink_width:
        s.add(f"{p}_ink", "path", layer, d=arc, fill="none", stroke=INK, stroke_width=width + 2 * ink_width,
              stroke_linecap="round", anim="draw", **tf)
        s.add(f"{p}_head", "path", layer, d=head, fill=color, stroke=INK, stroke_width=ink_width,
              stroke_linejoin="round", anim="pop", **tf)
        s.add(p, "path", layer, d=arc, fill="none", stroke=color, stroke_width=width, stroke_linecap="round",
              anim="draw", **tf)
    else:
        s.add(p, "path", layer, d=arc, fill="none", stroke=color, stroke_width=width, stroke_linecap="round",
              anim="draw", **tf)
        s.add(f"{p}_head", "path", layer, d=head, fill=color, anim="pop", **tf)


def block_arrow_d(x0: float, x1: float, cy: float, shaft_h: float, head_h: float, head_len: float) -> str:
    """Right-pointing block arrow: shaft from x0, head base at x1 - head_len, tip at x1."""
    hx = x1 - head_len
    return (f"M{f(x0)} {f(cy - shaft_h / 2)}H{f(hx)}V{f(cy - head_h / 2)}L{f(x1)} {f(cy)}L{f(hx)} {f(cy + head_h / 2)}"
            f"V{f(cy + shaft_h / 2)}H{f(x0)}Z")


# ---------------------------------------------------------------- reference fitting
def ref_fit(png: str, grid: int, margin: float | None = None) -> list[float]:
    """ref_map (scale, dx, dy) that centres the reference drawing (card excluded) in the grid."""
    import colorsys

    from PIL import Image

    im = Image.open(png).convert("RGBA")
    w, h = im.size
    inset = int(0.07 * w)  # skip the card border and its shadow
    xs, ys = [], []
    px = im.load()
    for y in range(inset, h - inset):
        for x in range(inset, w - inset):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if ss > 0.18 or vv < 0.72:
                xs.append(x)
                ys.append(y)
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    margin = grid / 16 if margin is None else margin
    scale = (grid - 2 * margin) / max(x1 - x0, y1 - y0)
    dx = (grid - (x1 - x0) * scale) / 2 - x0 * scale
    dy = (grid - (y1 - y0) * scale) / 2 - y0 * scale
    return [round(scale, 5), round(dx, 3), round(dy, 3)]


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "fit":
        print(ref_fit(sys.argv[2], int(sys.argv[3]), float(sys.argv[4]) if len(sys.argv) > 4 else None))
