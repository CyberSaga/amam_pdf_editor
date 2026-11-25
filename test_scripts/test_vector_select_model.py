"""Card B5, model wiring: PDFModel.install_vector_index / vector_index / vector_select / vector_selection_segments.

A visual marquee or click must pick the same row on /Rotate 0, 90, 180, 270 and on an offset CropBox: the model maps
the visual rectangle to unrotated page space (model.geometry), takes min/max after the map, and calls index.select.
Red first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.geometry import unrotated_to_visual_point  # noqa: E402
from model.object_requests import VectorSelectionInfo, VectorSelectionQuery  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.vector_paths.scan import scan_page  # noqa: E402


def _make(tmp_path: Path, rotation: int, cropbox: bool) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((5, 5), " ")  # forces a content stream to exist
    xref = page.get_contents()[0]
    doc.update_stream(xref, b"0 0 0 RG 1 w 20 370 m 120 370 l S 1 0 0 rg 150 160 40 40 re f")
    if cropbox:
        page.set_cropbox(fitz.Rect(10, 20, 280, 380))
    page.set_rotation(rotation)
    path = tmp_path / f"r{rotation}_{int(cropbox)}.pdf"
    doc.save(path)
    doc.close()
    return path


def _open(tmp_path: Path, rotation: int, cropbox: bool):
    model = PDFModel()
    model.open_pdf(str(_make(tmp_path, rotation, cropbox)))
    streams, frame = model.vector_page_source(1)
    idx = scan_page(list(streams), frame)
    model.install_vector_index(1, idx)
    return model, idx


def _visual(model: PDFModel, x: float, y: float) -> tuple[float, float]:
    p = unrotated_to_visual_point(model.doc[0], fitz.Point(x, y))
    return float(p.x), float(p.y)


def _mid_of_row(model: PDFModel, idx, row: int) -> tuple[float, float, float, float]:
    p = idx.paths[row]
    seg = idx.segments[int(p["seg_start"])]
    (ax, ay), (bx, by) = _visual(model, seg["x0"], seg["y0"]), _visual(model, seg["x1"], seg["y1"])
    return ax, ay, bx, by


@pytest.mark.parametrize("cropbox", [False, True], ids=["plain", "cropbox"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_visual_click_and_marquee_pick_the_same_rows_on_every_rotation(tmp_path, rotation, cropbox):
    model, idx = _open(tmp_path, rotation, cropbox)
    assert len(idx.paths) == 2
    ax, ay, bx, by = _mid_of_row(model, idx, 0)
    mx, my = (ax + bx) / 2, (ay + by) / 2
    info = model.vector_select(VectorSelectionQuery(1, (mx, my, mx, my), 3.0, "click", "replace"))
    assert isinstance(info, VectorSelectionInfo) and info.count == 1 and info.skipped == 0
    assert info.supports_delete and info.supports_move
    assert model.vector_selection_mask().tolist() == [True, False]
    # a visual marquee around the line (corners arrive in any order) selects it, not the fill
    pad = 4.0
    rect = (min(ax, bx) - pad, min(ay, by) - pad, max(ax, bx) + pad, max(ay, by) + pad)
    info = model.vector_select(VectorSelectionQuery(1, rect, 0.0, "touch", "replace"))
    assert info.count == 1 and model.vector_selection_mask().tolist() == [True, False]
    assert info.bbox is not None
    seg = model.vector_selection_segments()
    assert seg.dtype == np.float32 and seg.shape == (1, 4)
    got = sorted([(round(float(seg[0][0]), 2), round(float(seg[0][1]), 2)), (round(float(seg[0][2]), 2), round(float(seg[0][3]), 2))])
    assert got == sorted([(round(ax, 2), round(ay, 2)), (round(bx, 2), round(by, 2))]), "segments come back in visual coordinates"
    # the fill is picked by a click inside it
    fx, fy = _visual(model, 170, 220)
    info = model.vector_select(VectorSelectionQuery(1, (fx, fy, fx, fy), 0.0, "click", "replace"))
    assert info.count == 1 and model.vector_selection_mask().tolist() == [False, True]


def test_combine_all_clear_and_stale_tokens(tmp_path):
    model, _ = _open(tmp_path, 0, False)
    a = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "all", "replace"))
    assert a.count == 2
    b = model.vector_select(VectorSelectionQuery(1, (0, 0, 0, 0), 0.0, "clear", "replace"))
    assert b.count == 0 and b.bbox is None and b.token != a.token
    c = model.vector_select(VectorSelectionQuery(1, (60, 25, 80, 35), 0.0, "touch", "add"))
    d = model.vector_select(VectorSelectionQuery(1, (60, 25, 80, 35), 0.0, "touch", "toggle"))
    assert c.count == 1 and d.count == 0
    assert len({a.token, b.token, c.token, d.token}) == 4


def test_no_index_installed_returns_none_and_a_content_change_invalidates(tmp_path):
    model = PDFModel()
    model.open_pdf(str(_make(tmp_path, 0, False)))
    assert model.vector_index(1) is None
    assert model.vector_select(VectorSelectionQuery(1, (0, 0, 9, 9), 0.0, "touch", "replace")) is None
    streams, frame = model.vector_page_source(1)
    model.install_vector_index(1, scan_page(list(streams), frame))
    assert model.vector_index(1) is not None
    model.edit_count += 1  # any content write moves content_revision
    assert model.vector_index(1) is None
