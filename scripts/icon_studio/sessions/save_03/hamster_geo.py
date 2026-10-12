"""Hamster regions shared by the fur batches."""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from geo import catmull_pts


def regions(s):
    cx, cy, rx, ry = s.params["head"]
    head = Polygon([(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in range(0, 360, 3)])
    head = head.intersection(Polygon([(150, 200), (360, 200), (360, 355), (150, 355)]))
    m = s.params["muzzle_pts"]
    top = catmull_pts(m["top"], k=10)
    muzzle = Polygon(top + [(330, 340), (330, 360), (180, 360), (180, 340)]).intersection(head)
    peach = head.difference(muzzle)
    eye_polys = []
    for ex, ey, erx, ery in s.params["eyes"]:
        eye_polys.append(Polygon([(ex + (erx + 1.8) * math.cos(math.radians(a)), ey + (ery + 1.8) * math.sin(math.radians(a))) for a in range(0, 360, 10)]))
    face_avoid = eye_polys[0].union(eye_polys[1])
    nose_mouth = Polygon([(249, 328.5), (263, 328.5), (270.5, 339), (266, 347.5), (246, 347.5), (241.5, 339)])
    return {"head": head, "muzzle": muzzle, "peach": peach, "avoid": face_avoid.union(nose_mouth),
            "boundary": top, "nose": (256.0, 333.0)}


def flow(x, y, nose=(256.0, 333.0)):
    """Fur direction: radiating from the nose, cheeks bending downward."""
    dx, dy = x - nose[0], y - nose[1]
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    if y > nose[1] - 6:
        uy += 0.55 * min(1.0, abs(dx) / 40)
    elif abs(dx) > 28:
        # upper sides: sweep back and slightly down toward the cheeks
        uy += 0.25
    ln = math.hypot(ux, uy) or 1.0
    return ux / ln, uy / ln
