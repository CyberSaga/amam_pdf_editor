"""Shared brushes for batch scripts."""
from __future__ import annotations

import random

from geo import pts_d, smooth_d, wobble_ellipse, wobble_pts

PENCIL = "#5872B0"
GUIDE = "#78A6D8"
RED_PENCIL = "#D0605E"


def pencil_line(s, eid, p0, p1, rng: random.Random, w=1.4, op=0.5, amp=0.9,
                overshoot=0.04, bow=0.0, color=PENCIL, layer="sketch", n=6):
    pts = wobble_pts(p0, p1, rng, amp=amp, n=n, overshoot=overshoot, bow=bow)
    return s.add(eid, "path", layer, d=smooth_d(pts), fill="none", stroke=color,
                 stroke_width=w, stroke_opacity=op, stroke_linecap="round",
                 stroke_linejoin="round", anim="draw")


def pencil_curve(s, eid, pts, w=1.4, op=0.5, color=PENCIL, layer="sketch", closed=False):
    return s.add(eid, "path", layer, d=smooth_d(pts, closed=closed), fill="none",
                 stroke=color, stroke_width=w, stroke_opacity=op,
                 stroke_linecap="round", stroke_linejoin="round", anim="draw")


def pencil_ellipse(s, eid, cx, cy, rx, ry, rng, w=1.4, op=0.5, amp=1.0,
                   color=PENCIL, a0=None, sweep=None, n=18):
    pts = wobble_ellipse(cx, cy, rx, ry, rng, amp=amp, a0=a0, sweep=sweep, n=n)
    return pencil_curve(s, eid, pts, w=w, op=op, color=color)


def guide_line(s, eid, p0, p1, w=1.0, op=0.55, dash="7 6", color=GUIDE):
    return s.add(eid, "path", "guides", d=pts_d([p0, p1]), fill="none", stroke=color,
                 stroke_width=w, stroke_opacity=op, stroke_dasharray=dash,
                 stroke_linecap="round", anim="draw")
