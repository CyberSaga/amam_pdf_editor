"""Neutral DTO for the vector selection overlay (card B7 step 7).

The model groups the selected rows into the part that can move and the part that cannot, in VISUAL page
coordinates; the view draws them differently (solid / filled for movable, dashed / hollow for fixed) and never sees
the index, the selection mask or the path flags.  numpy only; no Qt, no model import.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _frozen(array: np.ndarray, dtype: type, shape: tuple[int, ...]) -> np.ndarray:
    out: np.ndarray = np.ascontiguousarray(array, dtype=dtype).reshape(shape)
    out.flags.writeable = False
    return out


@dataclass(frozen=True)
class VectorGeometry:
    """Read-only, contiguous float32 ``segments[K, 4]`` (x0, y0, x1, y1) and ``dots[D, 2]`` (x, y)."""

    segments: np.ndarray
    dots: np.ndarray

    @classmethod
    def of(cls, segments: np.ndarray | None = None, dots: np.ndarray | None = None) -> VectorGeometry:
        seg = np.zeros((0, 4), dtype=np.float32) if segments is None else segments
        pts = np.zeros((0, 2), dtype=np.float32) if dots is None else dots
        return cls(_frozen(seg, np.float32, (-1, 4)), _frozen(pts, np.float32, (-1, 2)))


@dataclass(frozen=True)
class VectorSelectionPresentation:
    page_num: int
    token: int
    count: int
    movable_count: int
    skipped: int
    visual_bbox: tuple[float, float, float, float] | None
    supports_move: bool
    supports_delete: bool
    movable_geometry: VectorGeometry
    fixed_geometry: VectorGeometry
