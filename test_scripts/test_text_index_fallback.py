"""A6.1: the get_text_info_at_point miss fallback reads cached rows (Qt-free).

The fallback used to re-interpret the page (``content_text(page, "dict",
flags=0)``) on every miss click.  It now reads ``FallbackRow`` objects built
once in ``TextBlockManager._build_page_index``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.page_content_text as pct  # noqa: E402
import model.text_block as text_block  # noqa: E402
from model.geometry import (  # noqa: E402
    unrotated_to_visual_point,
    unrotated_to_visual_rect,
    visual_text_rotation,
    visual_to_unrotated_point,
)
from model.pdf_model import PDFModel  # noqa: E402
from model.text_block import TextBlockManager  # noqa: E402
from model.text_block_parsing import compose_block_text_for_hit, rotation_degrees_from_dir  # noqa: E402

_BULLET_PREFIXES = ("- ", "* ", "• ", "▪ ", "● ")
PARA = "First wrapped line of text\nsecond wrapped line of text"


def _ref_starts_bullet(text: str) -> bool:
    import re

    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith(_BULLET_PREFIXES):
        return True
    return bool(re.match(r"^\d+[.)]\s+", stripped))


def _ref_compose(block: dict) -> str:
    """Frozen copy of the pre-A6.1 PDFModel._compose_block_text_for_hit."""
    lines = block.get("lines", []) or []
    if not lines:
        return ""
    line_texts: list[str] = []
    line_boxes: list[fitz.Rect] = []
    for line in lines:
        parts = [
            (s.get("text", "") or "").strip()
            for s in (line.get("spans", []) or [])
            if (s.get("text", "") or "").strip()
        ]
        if not parts:
            continue
        line_texts.append(" ".join(parts))
        bbox = line.get("bbox")
        if bbox is not None:
            line_boxes.append(fitz.Rect(bbox))
            continue
        spans = line.get("spans", []) or []
        if spans:
            line_box = fitz.Rect(spans[0].get("bbox", (0, 0, 0, 0)))
            for span in spans[1:]:
                line_box.include_rect(fitz.Rect(span.get("bbox", (0, 0, 0, 0))))
            line_boxes.append(line_box)
        else:
            line_boxes.append(fitz.Rect(0, 0, 0, 0))
    if not line_texts:
        return ""
    composed: list[str] = []
    for idx, line_text in enumerate(line_texts):
        if idx == 0:
            composed.append(line_text)
            continue
        prev_box, curr_box = line_boxes[idx - 1], line_boxes[idx]
        prev_height = max(prev_box.height, 0.0)
        gap = curr_box.y0 - prev_box.y1
        if _ref_starts_bullet(line_text) or (prev_height > 0 and gap > prev_height * 0.5):
            composed.append("\n")
        elif composed and not composed[-1].endswith((" ", "\n", "-")):
            composed.append(" ")
        composed.append(line_text)
    return "".join(composed).strip()


def _ref_fallback(page: fitz.Page, page_idx: int, point: fitz.Point, mode: str = "run") -> dict | None:
    """Frozen copy of the pre-A6.1 fallback; returns the TextHit fields."""
    blocks = pct.content_text(page, "dict", flags=0)["blocks"]
    for block_idx, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        rect = fitz.Rect(block["bbox"])
        if point not in rect:
            continue
        font_name, font_size, color_int, rotation = "helv", 12.0, 0, 0
        if block.get("lines") and block["lines"][0].get("spans"):
            first = block["lines"][0]["spans"][0]
            font_name = first.get("font", "helv")
            font_size = float(first.get("size", 12.0))
            color_int = int(first.get("color", 0))
        if block.get("lines") and block["lines"][0].get("dir") is not None:
            rotation = rotation_degrees_from_dir(block["lines"][0]["dir"])
        rgb = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
        sid = f"p{page_idx}_b{block_idx}_l0_s0"
        return {
            "id": sid,
            "bbox": tuple(rect),
            "text": _ref_compose(block),
            "font": font_name,
            "size": font_size,
            "color": tuple(c / 255.0 for c in rgb),
            "rotation": rotation,
        }
    return None


def _make_pdf(path: Path, rotations=(0, 90, 180, 270)) -> Path:
    doc = fitz.open()
    for i, rot in enumerate(rotations):
        page = doc.new_page(width=400, height=500)
        page.insert_text((50, 100), f"Hello page {i}", fontsize=14.5, color=(1, 0, 0))
        page.insert_text((50, 130), f"- bullet {i}", fontsize=11)
        page.insert_textbox(fitz.Rect(50, 200, 300, 260), PARA, fontsize=10)
        page.set_rotation(rot)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def model(tmp_path):
    m = PDFModel()
    m.open_pdf(str(_make_pdf(tmp_path / "fb.pdf")))
    try:
        yield m
    finally:
        m.close()


def _miss_points(page: fitz.Page) -> list[fitz.Point]:
    """Unrotated-space points: inside a block but off every run's bbox, plus pure miss."""
    blocks = pct.content_text(page, "dict", flags=0)["blocks"]
    pts = []
    for b in blocks:
        if b.get("type") == 0:
            r = fitz.Rect(b["bbox"])
            pts.append(fitz.Point(r.x0 + 0.2, r.y0 + 0.2))
            pts.append(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
            for fx in (0.05, 0.5, 0.95):
                for fy in (0.05, 0.3, 0.5, 0.7, 0.95):
                    pts.append(fitz.Point(r.x0 + fx * r.width, r.y0 + fy * r.height))
    pts.append(fitz.Point(390, 490))  # empty area
    return pts


def _count_interpretations(monkeypatch) -> list[int]:
    calls = [0]
    real = pct.content_textpage

    def counting(*a, **k):
        calls[0] += 1
        return real(*a, **k)

    monkeypatch.setattr(pct, "content_textpage", counting)
    monkeypatch.setattr(text_block, "content_textpage", counting)
    return calls


def test_second_miss_lookup_makes_no_interpretation(model, monkeypatch) -> None:
    page = model.doc[0]
    vis = fitz.Point(395, 495)  # empty corner, miss
    model.get_text_info_at_point(1, vis, allow_fallback=True)  # builds index
    points = _miss_points(page)  # itself interprets; compute before counting
    calls = _count_interpretations(monkeypatch)
    assert model.get_text_info_at_point(1, vis, allow_fallback=True) is None
    # a miss that lands in a block but off every run box
    for pt in points:
        model.get_text_info_at_point(1, pt, allow_fallback=True)
    assert calls[0] == 0


@pytest.mark.parametrize("page_idx", [0, 1, 2, 3])
def test_rows_fallback_matches_old_logic(model, page_idx) -> None:
    page = model.doc[page_idx]
    model.ensure_page_index_built(page_idx + 1)
    seen = 0
    for pt in _miss_points(page):
        if model._get_text_info_at_point_unrotated(page_idx + 1, pt, allow_fallback=False) is not None:
            continue  # a run hit; the fallback is never reached
        expected = _ref_fallback(page, page_idx, pt)
        got = model._get_text_info_at_point_unrotated(page_idx + 1, pt, allow_fallback=True)
        if expected is None:
            assert got is None
            continue
        assert got is not None
        seen += 1
        assert got.target_span_id == expected["id"]
        assert got.target_text == expected["text"]
        assert tuple(got.target_bbox) == expected["bbox"]
        assert got.font == expected["font"]
        assert got.size == expected["size"] and isinstance(got.size, float)
        assert got.color == expected["color"]
        assert got.rotation == expected["rotation"]
        assert got.cluster_span_ids == [expected["id"]]
        assert got.target_mode == "run"
    assert seen > 0, "no point exercised the fallback"


@pytest.mark.parametrize("page_idx", [0, 1, 2, 3])
def test_fallback_rows_equal_old_dict_derivation(model, page_idx) -> None:
    page = model.doc[page_idx]
    model.ensure_page_index_built(page_idx + 1)
    rows = model.block_manager.get_fallback_rows(page_idx)
    blocks = pct.content_text(page, "dict", flags=0)["blocks"]
    text_blocks = [(i, b) for i, b in enumerate(blocks) if b.get("type") == 0]
    assert [r.block_idx for r in rows] == [i for i, _ in text_blocks]
    assert rows, "fixture page must have text rows"
    for row, (_, b) in zip(rows, text_blocks, strict=True):
        assert tuple(row.bbox) == tuple(fitz.Rect(b["bbox"]))
        assert row.text == _ref_compose(b)
    # visual round trip sanity: public API still resolves a visual point
    r0 = rows[0].bbox
    centre = fitz.Point((r0[0] + r0[2]) / 2, (r0[1] + r0[3]) / 2)
    assert visual_to_unrotated_point(page, fitz.Point(0, 0)) is not None
    assert centre in fitz.Rect(r0)


LINELESS_BBOX_BLOCK = {
    "lines": [
        {"spans": [{"text": "A", "bbox": (0, 0, 10, 10)}]},
        {"spans": [{"text": "B", "bbox": (0, 20, 10, 30)}]},
    ]
}


def test_compose_without_line_bbox_unions_span_boxes() -> None:
    assert _ref_compose(LINELESS_BBOX_BLOCK) == "A\nB"
    assert compose_block_text_for_hit(LINELESS_BBOX_BLOCK) == "A\nB"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_public_fallback_color_bbox_rotation_on_rotated_pages(tmp_path, rotation) -> None:
    path = tmp_path / "color.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_textbox(fitz.Rect(50, 200, 300, 280), PARA, fontsize=10, color=(1, 0, 0))
    page.set_rotation(rotation)
    doc.save(str(path))
    doc.close()
    m = PDFModel()
    m.open_pdf(str(path))
    try:
        m.ensure_page_index_built(1)
        page = m.doc[0]
        row = m.block_manager.get_fallback_rows(0)[0]
        rect = fitz.Rect(row.bbox)
        found = None
        for fx in (0.03, 0.3, 0.5, 0.7, 0.97):
            for fy in (0.03, 0.3, 0.5, 0.7, 0.97):
                pt = fitz.Point(rect.x0 + fx * rect.width, rect.y0 + fy * rect.height)
                if m._get_text_info_at_point_unrotated(1, pt, allow_fallback=False) is None:
                    found = pt
                    break
            if found is not None:
                break
        assert found is not None, "need a point inside the block but off every run"
        hit = m.get_text_info_at_point(1, unrotated_to_visual_point(page, found), allow_fallback=True)
        assert hit is not None
        assert hit.color == (1.0, 0.0, 0.0)
        assert fitz.Rect(hit.target_bbox) == unrotated_to_visual_rect(page, rect)
        assert hit.rotation == visual_text_rotation(rotation, row.rotation)
        assert hit.rotation == (row.rotation + rotation) % 360 or hit.rotation == (row.rotation - rotation) % 360
        assert hit.target_text == PARA.replace("\n", " ")
    finally:
        m.close()


def _manager(tmp_path) -> tuple[TextBlockManager, fitz.Document]:
    doc = fitz.open()
    for i in range(4):
        p = doc.new_page()
        p.insert_text((50, 100), f"unique page {i}", fontsize=12)
    mgr = TextBlockManager()
    mgr.build_index(doc)
    return mgr, doc


def _snap(mgr: TextBlockManager) -> dict[int, list]:
    return {i: list(mgr.get_fallback_rows(i)) for i in range(4)}


def test_rows_follow_insert_delete_move(tmp_path) -> None:
    mgr, doc = _manager(tmp_path)
    before = _snap(mgr)
    assert all(before[i] for i in range(4))

    mgr.shift_after_insert(2, 1)
    assert mgr.get_fallback_rows(0) == before[0] and mgr.get_fallback_rows(1) == before[1]
    assert mgr.get_fallback_rows(2) == []  # new page: nothing cached
    assert mgr.get_fallback_rows(3) == before[2] and mgr.get_fallback_rows(4) == before[3]
    assert set(mgr._fallback_rows) == set(mgr._index)

    mgr.shift_after_delete([0])
    assert mgr.get_fallback_rows(2) == before[2] and mgr.get_fallback_rows(3) == before[3]
    assert set(mgr._fallback_rows) == set(mgr._index)

    mgr2, _ = _manager(tmp_path)
    b2 = _snap(mgr2)
    mgr2.shift_after_move(0, 2)
    assert mgr2.get_fallback_rows(2) == b2[0]
    assert mgr2.get_fallback_rows(0) == b2[1] and mgr2.get_fallback_rows(1) == b2[2]
    assert set(mgr2._fallback_rows) == set(mgr2._index)

    mgr2.clear()
    assert mgr2.get_fallback_rows(0) == [] and not mgr2._fallback_rows
    doc.close()
