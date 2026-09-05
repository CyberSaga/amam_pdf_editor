"""Stateless text-parsing layer (R3.1 god-module decomposition seam).

Pure transforms from a PyMuPDF page dict to the editable dataclasses
(:class:`TextBlock` / :class:`EditableSpan` / :class:`EditableParagraph`).

These functions own **no** instance state: :class:`model.text_block.TextBlockManager`
keeps ownership of every page-keyed index and calls into this module. Extracted
verbatim from ``text_block.py`` (only ``self.`` removed) so the behavior is identical;
``text_block`` re-exports the dataclasses and ``rotation_degrees_from_dir`` for
backward compatibility.
"""

from __future__ import annotations

import difflib
import logging
import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import fitz

from model.text_normalization import _LIGATURE_MAP

_RE_WS_STRIP = re.compile(r"\s+")
logger = logging.getLogger(__name__)
_BULLET_PREFIXES = ("- ", "* ", "• ", "▪ ", "● ")


def rotation_degrees_from_dir(dir_tuple) -> int:
    """Convert line direction vector to nearest 0/90/180/270 rotation."""
    if not dir_tuple or len(dir_tuple) < 2:
        return 0
    dx, dy = float(dir_tuple[0]), float(dir_tuple[1])
    rad = math.atan2(dy, dx)
    deg = (math.degrees(rad) + 360) % 360
    nearest = round(deg / 90) * 90
    return int(nearest % 360)


def _norm_dir_vec(dir_tuple) -> tuple[float, float]:
    if not dir_tuple or len(dir_tuple) < 2:
        return (1.0, 0.0)
    dx, dy = float(dir_tuple[0]), float(dir_tuple[1])
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _rect_axis_projection(rect: fitz.Rect, ux: float, uy: float, vx: float, vy: float) -> tuple[float, float, float, float]:
    pts = (
        (rect.x0, rect.y0),
        (rect.x1, rect.y0),
        (rect.x0, rect.y1),
        (rect.x1, rect.y1),
    )
    uvals = [x * ux + y * uy for x, y in pts]
    vvals = [x * vx + y * vy for x, y in pts]
    return (min(uvals), max(uvals), min(vvals), max(vvals))


def _char_kind(ch: str) -> str:
    if not ch:
        return "other"
    if ch.isspace():
        return "space"
    code = ord(ch)
    if (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    ):
        return "cjk"
    cat = unicodedata.category(ch)
    if cat.startswith("P"):
        return "punct"
    if cat.startswith("N"):
        return "latin"
    if cat.startswith("L"):
        return "latin"
    return "other"


def _kind_compatible(prev_kind: str, curr_kind: str) -> bool:
    if prev_kind == curr_kind:
        return True
    if "punct" in (prev_kind, curr_kind):
        return True
    if "other" in (prev_kind, curr_kind):
        return True
    if prev_kind == "latin" and curr_kind == "latin":
        return True
    return False


def _starts_bullet_item(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith(_BULLET_PREFIXES):
        return True
    return bool(re.match(r"^\d+[.)]\s+", stripped))


@dataclass
class TextBlock:
    block_id: str
    page_num: int
    rect: fitz.Rect
    layout_rect: fitz.Rect
    text: str
    font: str
    size: float
    color: tuple
    rotation: int
    original_span_count: int = 0
    is_vertical: bool = field(init=False, default=False)

    def __post_init__(self):
        self.is_vertical = self.rotation in (90, 270)


@dataclass
class EditableSpan:
    span_id: str
    page_idx: int
    block_idx: int
    line_idx: int
    span_idx: int
    bbox: fitz.Rect
    origin: fitz.Point
    text: str
    font: str
    size: float
    color: tuple
    dir_vec: tuple
    rotation: int


@dataclass
class EditableParagraph:
    paragraph_id: str
    page_idx: int
    block_idx: int
    bbox: fitz.Rect
    text: str
    font: str
    size: float
    color: tuple
    dir_vec: tuple
    rotation: int
    run_ids: list[str]
    line_start: int
    line_end: int


def _join_visual_lines(line_texts: list[str]) -> str:
    """Join a block's soft-wrapped lines back into one paragraph string.

    Spans *inside* a line are contiguous style runs, so they concatenate with
    no separator.  Lines are not: joining them directly deletes the word
    boundary at every line break, so ``"jumps"`` + ``"over"`` reads back as
    ``"jumpsover"``.  A trailing hyphen is a split word and keeps no space —
    the same rule :func:`_build_paragraphs` already applies to run-level
    paragraphs, which this now agrees with.
    """
    joined: list[str] = []
    for line_text in line_texts:
        if not line_text:
            continue
        if (
            joined
            and not joined[-1].endswith((" ", "\n", "-"))
            and not line_text.startswith((" ", "\n"))
        ):
            joined.append(" ")
        joined.append(line_text)
    return "".join(joined)


def _parse_block(
    page_num: int,
    raw_index: int,
    block: dict,
) -> TextBlock | None:
    if block.get("type") != 0:
        return None

    block_rect = fitz.Rect(block["bbox"])
    line_texts: list[str] = []
    font_name = "helv"
    font_size = 12.0
    color_int = 0
    span_count = 0

    for line in block.get("lines", []) or []:
        span_texts: list[str] = []
        for span in line.get("spans", []) or []:
            span_texts.append(span.get("text", ""))
            span_count += 1
            if font_name == "helv" and "font" in span:
                font_name = span.get("font", "helv")
                font_size = float(span.get("size", 12.0))
                color_int = int(span.get("color", 0))
        line_texts.append("".join(span_texts))

    text = _join_visual_lines(line_texts)
    rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
    color = tuple(c / 255.0 for c in rgb_int)

    rotation = 0
    first_line = (block.get("lines") or [None])[0]
    if first_line and first_line.get("dir") is not None:
        rotation = rotation_degrees_from_dir(first_line.get("dir"))

    return TextBlock(
        block_id=f"page_{page_num}_block_{raw_index}",
        page_num=page_num,
        rect=fitz.Rect(block_rect),
        layout_rect=fitz.Rect(block_rect),
        text=text,
        font=font_name,
        size=font_size,
        color=color,
        rotation=rotation,
        original_span_count=span_count,
    )


def _parse_spans(
    page_num: int,
    block_idx: int,
    block: dict,
) -> list[EditableSpan]:
    if block.get("type") != 0:
        return []

    out: list[EditableSpan] = []
    for line_idx, line in enumerate(block.get("lines", []) or []):
        dir_vec = line.get("dir") or (1.0, 0.0)
        rotation = rotation_degrees_from_dir(dir_vec)
        for span_idx, span in enumerate(line.get("spans", []) or []):
            bbox_raw = span.get("bbox")
            if not bbox_raw:
                continue
            text = span.get("text", "")
            if text == "":
                continue
            color_int = int(span.get("color", 0))
            rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
            color = tuple(c / 255.0 for c in rgb_int)
            origin_raw = span.get("origin") or (bbox_raw[0], bbox_raw[3])
            out.append(
                EditableSpan(
                    span_id=f"p{page_num}_b{block_idx}_l{line_idx}_s{span_idx}",
                    page_idx=page_num,
                    block_idx=block_idx,
                    line_idx=line_idx,
                    span_idx=span_idx,
                    bbox=fitz.Rect(bbox_raw),
                    origin=fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                    text=text,
                    font=span.get("font", "helv"),
                    size=float(span.get("size", 12.0)),
                    color=color,
                    dir_vec=(float(dir_vec[0]), float(dir_vec[1])),
                    rotation=rotation,
                )
            )
    return out


def _parse_runs_from_raw_block(
    page_num: int,
    block_idx: int,
    raw_block: dict,
    plain_lines: list[str] | None = None,
) -> list[EditableSpan]:
    lines = raw_block.get("lines", []) or []
    if not lines:
        return []

    out: list[EditableSpan] = []
    for line_idx, line in enumerate(lines):
        out.extend(_parse_runs_from_raw_line(page_num, block_idx, line_idx, line, plain_lines=plain_lines))
    return out


def _parse_runs_from_raw_line(
    page_num: int,
    block_idx: int,
    line_idx: int,
    line: dict,
    plain_lines: list[str] | None = None,
) -> list[EditableSpan]:
    dir_vec = _norm_dir_vec(line.get("dir") or (1.0, 0.0))
    ux, uy = dir_vec
    vx, vy = (-uy, ux)
    rotation = rotation_degrees_from_dir(dir_vec)

    chars: list[dict] = []
    for span_idx, span in enumerate(line.get("spans", []) or []):
        color_int = int(span.get("color", 0))
        rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
        color = tuple(c / 255.0 for c in rgb_int)
        font_name = span.get("font", "helv")
        font_size = float(span.get("size", 12.0))

        span_chars = span.get("chars") or []
        if span_chars:
            for char_idx, ch in enumerate(span_chars):
                ch_text = ch.get("c", "")
                bbox_raw = ch.get("bbox")
                if not bbox_raw:
                    continue
                bbox = fitz.Rect(bbox_raw)
                origin_raw = ch.get("origin") or (bbox.x0, bbox.y1)
                u0, u1, v0, v1 = _rect_axis_projection(bbox, ux, uy, vx, vy)
                chars.append(
                    {
                        "text": ch_text,
                        "bbox": bbox,
                        "origin": fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                        "font": font_name,
                        "size": font_size,
                        "color": color,
                        "kind": _char_kind(ch_text),
                        "u0": u0,
                        "u1": u1,
                        "uc": (u0 + u1) / 2.0,
                        "vc": (v0 + v1) / 2.0,
                        "source_span_idx": span_idx,
                        "source_char_idx": char_idx,
                    }
                )
            continue

        # Fallback for PDFs that expose span text without per-char geometry in rawdict.
        span_text = span.get("text", "")
        bbox_raw = span.get("bbox")
        if not span_text or not bbox_raw:
            continue
        bbox = fitz.Rect(bbox_raw)
        origin_raw = span.get("origin") or (bbox.x0, bbox.y1)
        u0, u1, v0, v1 = _rect_axis_projection(bbox, ux, uy, vx, vy)
        chars.append(
            {
                "text": span_text,
                "bbox": bbox,
                "origin": fitz.Point(float(origin_raw[0]), float(origin_raw[1])),
                "font": font_name,
                "size": font_size,
                "color": color,
                "kind": "other",
                "u0": u0,
                "u1": u1,
                "uc": (u0 + u1) / 2.0,
                "vc": (v0 + v1) / 2.0,
                "source_span_idx": span_idx,
                "source_char_idx": 0,
            }
        )

    if not chars:
        return []

    chars.sort(key=lambda c: (c["uc"], c["vc"], c["source_span_idx"], c["source_char_idx"]))
    extents = [max(0.1, float(c["u1"] - c["u0"])) for c in chars]
    median_extent = statistics.median(extents) if extents else 1.0
    gap_tol = max(0.8, median_extent * 0.35)
    hard_gap_tol = max(gap_tol * 2.2, median_extent * 1.2)
    cross_tol = max(1.0, median_extent * 0.75)

    def _finalize(run: dict, run_idx: int) -> EditableSpan | None:
        text_value = "".join(run["text_parts"]).strip()
        if not text_value:
            return None
        text_value = _repair_replacement_chars(text_value, plain_lines)
        bbox = fitz.Rect(run["bbox"])
        dominant_font = run["font_counter"].most_common(1)[0][0] if run["font_counter"] else "helv"
        dominant_color = (
            run["color_counter"].most_common(1)[0][0]
            if run["color_counter"]
            else (0.0, 0.0, 0.0)
        )
        avg_size = run["size_sum"] / max(1, run["size_count"])
        return EditableSpan(
            span_id=f"p{page_num}_b{block_idx}_l{line_idx}_s{run_idx}",
            page_idx=page_num,
            block_idx=block_idx,
            line_idx=line_idx,
            span_idx=run_idx,
            bbox=bbox,
            origin=fitz.Point(run["origin"].x, run["origin"].y),
            text=text_value,
            font=dominant_font,
            size=float(avg_size),
            color=tuple(dominant_color),
            dir_vec=(float(dir_vec[0]), float(dir_vec[1])),
            rotation=rotation,
        )

    runs: list[EditableSpan] = []
    run_idx = 0
    current: dict | None = None
    for ch in chars:
        text_value = ch["text"]
        if not text_value:
            continue

        # Space characters define run boundaries for Latin-like text.
        if text_value.isspace():
            if current is not None:
                built = _finalize(current, run_idx)
                if built is not None:
                    runs.append(built)
                    run_idx += 1
                current = None
            continue

        if current is None:
            current = {
                "text_parts": [text_value],
                "bbox": fitz.Rect(ch["bbox"]),
                "origin": fitz.Point(ch["origin"].x, ch["origin"].y),
                "font_counter": Counter([ch["font"]]),
                "color_counter": Counter([tuple(ch["color"])]),
                "size_sum": float(ch["size"]),
                "size_count": 1,
                "kind": ch["kind"],
                "last_u1": float(ch["u1"]),
                "last_vc": float(ch["vc"]),
                "last_size": float(ch["size"]),
                "last_kind": ch["kind"],
                "last_color": tuple(ch["color"]),
            }
            continue

        gap = float(ch["u0"]) - float(current["last_u1"])
        cross_delta = abs(float(ch["vc"]) - float(current["last_vc"]))
        size_delta = abs(float(ch["size"]) - float(current["last_size"]))
        color_changed = tuple(ch["color"]) != tuple(current["last_color"])
        kind_changed = not _kind_compatible(str(current["last_kind"]), str(ch["kind"]))

        should_break = False
        if cross_delta > cross_tol or gap > hard_gap_tol or size_delta > max(0.9, float(current["last_size"]) * 0.25) or color_changed or kind_changed or gap > gap_tol:
            should_break = True

        if should_break:
            built = _finalize(current, run_idx)
            if built is not None:
                runs.append(built)
                run_idx += 1
            current = {
                "text_parts": [text_value],
                "bbox": fitz.Rect(ch["bbox"]),
                "origin": fitz.Point(ch["origin"].x, ch["origin"].y),
                "font_counter": Counter([ch["font"]]),
                "color_counter": Counter([tuple(ch["color"])]),
                "size_sum": float(ch["size"]),
                "size_count": 1,
                "kind": ch["kind"],
                "last_u1": float(ch["u1"]),
                "last_vc": float(ch["vc"]),
                "last_size": float(ch["size"]),
                "last_kind": ch["kind"],
                "last_color": tuple(ch["color"]),
            }
            continue

        current["text_parts"].append(text_value)
        current["bbox"].include_rect(ch["bbox"])
        current["font_counter"][ch["font"]] += 1
        current["color_counter"][tuple(ch["color"])] += 1
        current["size_sum"] += float(ch["size"])
        current["size_count"] += 1
        current["last_u1"] = float(ch["u1"])
        current["last_vc"] = float(ch["vc"])
        current["last_size"] = float(ch["size"])
        current["last_kind"] = ch["kind"]
        current["last_color"] = tuple(ch["color"])

    if current is not None:
        built = _finalize(current, run_idx)
        if built is not None:
            runs.append(built)

    return runs


def _extract_plain_text_lines(page: fitz.Page) -> list[str]:
    lines: list[str] = []
    for line in page.get_text("text").splitlines():
        value = line.rstrip("\r\n")
        if value.strip():
            lines.append(value)
    return lines


def _repair_replacement_chars(text: str, plain_lines: list[str] | None) -> str:
    if "�" not in text or not plain_lines:
        return text
    pattern = "".join("(.)" if ch == "�" else re.escape(ch) for ch in text)
    try:
        regex = re.compile(pattern)
    except re.error:
        return text

    candidates: set[str] = set()
    for line in plain_lines:
        if not line:
            continue
        for match in regex.finditer(line):
            rebuilt = list(text)
            group_idx = 1
            valid = True
            for idx, ch in enumerate(rebuilt):
                if ch != "�":
                    continue
                replacement = match.group(group_idx)
                group_idx += 1
                if replacement == "�":
                    valid = False
                    break
                rebuilt[idx] = replacement
            if not valid:
                continue
            repaired = "".join(rebuilt)
            if "�" in repaired:
                continue
            candidates.add(repaired)
            if len(candidates) > 1:
                return text
    if len(candidates) == 1:
        return next(iter(candidates))
    return text


# --- T16-2: table cells inside one raw PyMuPDF block ------------------------
# A raw text block routinely holds a whole table row, so one paragraph per block
# made paragraph-mode edits redact every cell of the row. Three geometric rules
# cut a block back into per-cell paragraphs. Every threshold is corpus-tuned; the
# measured gap distributions behind them are in
# ``plans/task16-legacy-path-fidelity.md`` (Log, 2026-09-05).

#: (a) Cut ONE PyMuPDF line into cells where the horizontal gap between consecutive
#: inked runs exceeds this multiple of the larger run's font size. MuPDF only keeps
#: runs on one line when they are separated by real text-space characters, so gaps
#: here are tight: justified prose tops out at 0.58x, cell boundaries start at 0.89x.
_CELL_GAP_RATIO = 0.80

#: (a2) MuPDF opens a new "line" at any positioning jump, so one visual line of prose
#: arrives as several lines sharing a baseline. Cells from *different* PyMuPDF lines
#: that share a baseline are re-joined when their gap is at most this multiple of the
#: larger font size. Cells cut apart by rule (a) are never re-joined.
_SAME_BASELINE_GAP_RATIO = 3.0

#: Two cells sit on the same visual line when their y-ranges overlap by at least this
#: fraction of the shorter cell's height.
_BASELINE_OVERLAP_RATIO = 0.50

#: (b) Two units share a paragraph when their x-ranges overlap by at least this
#: fraction of the narrower unit's width (chained transitively).
_COLUMN_OVERLAP_RATIO = 0.50


@dataclass
class _ParagraphUnit:
    """One table cell, or one whole visual line when the line was not cut.

    ``bbox`` covers only the inked runs: it drives the baseline merge, the column
    grouping and the vertical-gap join heuristic. ``runs`` may additionally hold
    whitespace-only runs folded in from blank lines so no run loses its paragraph
    membership. ``line_indices`` records every PyMuPDF line the unit absorbed, so
    two cells cut apart by rule (a) can never be re-joined by rule (a2).
    """

    line_idx: int
    runs: list[EditableSpan]
    bbox: fitz.Rect
    text: str
    line_indices: set[int] = field(default_factory=set)
    max_size: float = 0.0


def _split_line_into_cells(line_runs: list[EditableSpan]) -> list[list[EditableSpan]]:
    """Cut one line's runs at every gap wider than :data:`_CELL_GAP_RATIO`."""
    cells: list[list[EditableSpan]] = []
    current: list[EditableSpan] = []
    last_inked: EditableSpan | None = None
    for run in line_runs:
        if not (run.text or "").strip():
            # Whitespace-only runs never open a cell; they ride along with the
            # cell to their left (or the one about to start) so run_ids stay whole.
            current.append(run)
            continue
        if last_inked is not None:
            gap = float(run.bbox.x0) - float(last_inked.bbox.x1)
            limit = _CELL_GAP_RATIO * max(float(last_inked.size), float(run.size))
            if limit > 0.0 and gap > limit:
                cells.append(current)
                current = []
        current.append(run)
        last_inked = run
    if current:
        cells.append(current)
    return cells


def _make_paragraph_unit(
    line_idx: int, cell_runs: list[EditableSpan]
) -> _ParagraphUnit:
    inked = [r for r in cell_runs if (r.text or "").strip()]
    bbox = fitz.Rect(inked[0].bbox) if inked else fitz.Rect()
    for run in inked[1:]:
        bbox.include_rect(run.bbox)
    return _ParagraphUnit(
        line_idx=line_idx,
        runs=list(cell_runs),
        bbox=bbox,
        text=" ".join(r.text.strip() for r in inked),
        line_indices={line_idx},
        max_size=max((float(r.size) for r in inked), default=0.0),
    )


def _units_share_a_baseline(left: _ParagraphUnit, right: _ParagraphUnit) -> bool:
    overlap = min(float(left.bbox.y1), float(right.bbox.y1)) - max(
        float(left.bbox.y0), float(right.bbox.y0)
    )
    if overlap <= 0.0:
        return False
    shorter = min(float(left.bbox.height), float(right.bbox.height))
    if shorter <= 0.0:
        return True
    return overlap / shorter >= _BASELINE_OVERLAP_RATIO


def _absorb_unit(target: _ParagraphUnit, other: _ParagraphUnit) -> None:
    target.runs.extend(other.runs)
    target.bbox.include_rect(other.bbox)
    target.line_indices |= other.line_indices
    target.line_idx = min(target.line_idx, other.line_idx)
    target.max_size = max(target.max_size, other.max_size)
    target.text = f"{target.text} {other.text}".strip() if other.text else target.text


def _merge_same_baseline_units(units: list[_ParagraphUnit]) -> list[_ParagraphUnit]:
    """Rule (a2): re-join cells that MuPDF split mid-visual-line at a mere Td jump."""
    merged: list[_ParagraphUnit] = []
    for unit in sorted(units, key=lambda u: (float(u.bbox.x0), u.line_idx)):
        host: _ParagraphUnit | None = None
        for candidate in merged:
            if candidate.line_indices & unit.line_indices:
                # Cut apart by rule (a) inside one PyMuPDF line: never re-join.
                continue
            if not _units_share_a_baseline(candidate, unit):
                continue
            gap = float(unit.bbox.x0) - float(candidate.bbox.x1)
            limit = _SAME_BASELINE_GAP_RATIO * max(candidate.max_size, unit.max_size)
            if limit <= 0.0 or gap < 0.0 or gap > limit:
                continue
            # Prefer the nearest neighbour to the left.
            if host is None or float(candidate.bbox.x1) > float(host.bbox.x1):
                host = candidate
        if host is None:
            merged.append(unit)
        else:
            _absorb_unit(host, unit)
    return merged


def _units_share_a_column(left: _ParagraphUnit, right: _ParagraphUnit) -> bool:
    overlap = min(float(left.bbox.x1), float(right.bbox.x1)) - max(
        float(left.bbox.x0), float(right.bbox.x0)
    )
    if overlap <= 0.0:
        return False
    narrower = min(float(left.bbox.width), float(right.bbox.width))
    if narrower <= 0.0:
        return True
    return overlap / narrower >= _COLUMN_OVERLAP_RATIO


def _group_units_into_columns(
    units: list[_ParagraphUnit],
) -> list[list[_ParagraphUnit]]:
    """Chain units transitively into sub-paragraphs by horizontal-range overlap."""
    parent = list(range(len(units)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            if not _units_share_a_column(units[i], units[j]):
                continue
            root_i, root_j = find(i), find(j)
            if root_i != root_j:
                parent[max(root_i, root_j)] = min(root_i, root_j)

    groups: dict[int, list[_ParagraphUnit]] = {}
    for idx, unit in enumerate(units):
        groups.setdefault(find(idx), []).append(unit)
    ordered = sorted(
        groups.values(),
        key=lambda g: (min(u.line_idx for u in g), min(float(u.bbox.x0) for u in g)),
    )
    return ordered


def _block_splits_cells(block_runs: list[EditableSpan]) -> bool:
    """False for vertical (90/270) blocks, which are exempt from every cell rule.

    A vertical MuPDF "line" is a *column*, so adjacent lines of one block have
    disjoint x-ranges: rule (a) would cut columns apart and rule (b) would then refuse
    to regroup them, handing ``_merge_vertical_paragraphs`` fragments instead of the
    one-paragraph-per-block input its greedy sweep was tuned on. That sweep unions
    whole paragraphs, so the orphans it picks up come from *other* blocks -- exactly
    the cross-cell paragraph this task set out to remove, reintroduced on the vertical
    axis. Both rule sites must agree on this predicate.

    The check is a per-block ``any()``: a block with even one rotated run is exempt
    wholesale. That is deliberate conservatism inherited from the original guard --
    mixed-rotation blocks are rare and splitting them has no corpus measurement
    behind it.
    """
    return not any(run.rotation in (90, 270) for run in block_runs)


def _block_paragraph_units(
    block_runs: list[EditableSpan], split_cells: bool
) -> list[_ParagraphUnit]:
    """Turn one block's runs into cells, keeping vertical text as a single unit.

    ``split_cells`` comes from :func:`_block_splits_cells` and is decided once by the
    caller, so this function and the column grouping can never disagree about whether
    a block is exempt.
    """
    line_map: dict[int, list[EditableSpan]] = {}
    for run in block_runs:
        line_map.setdefault(run.line_idx, []).append(run)

    units: list[_ParagraphUnit] = []
    pending_blank: list[EditableSpan] = []
    for line_idx in sorted(line_map.keys()):
        line_runs = sorted(line_map[line_idx], key=lambda s: s.span_idx)
        cells = _split_line_into_cells(line_runs) if split_cells else [line_runs]
        for cell_runs in cells:
            unit = _make_paragraph_unit(line_idx, cell_runs)
            if not unit.text:
                # A blank filler line owns no column of its own.
                if units:
                    units[-1].runs.extend(unit.runs)
                else:
                    pending_blank.extend(unit.runs)
                continue
            if pending_blank:
                unit.runs = pending_blank + unit.runs
                pending_blank = []
            units.append(unit)
    if pending_blank and units:
        units[-1].runs.extend(pending_blank)
    if not split_cells:
        return units
    return _merge_same_baseline_units(units)


def _compose_paragraph_text(units: list[_ParagraphUnit]) -> str:
    parts: list[str] = []
    for idx, unit in enumerate(units):
        if idx == 0:
            parts.append(unit.text)
            continue
        prev = units[idx - 1]
        prev_height = max(prev.bbox.height, 0.0)
        # Cells sharing a line give a negative gap and fall through to the space
        # branch, which is the join the old per-line " ".join produced.
        gap = float(unit.bbox.y0) - float(prev.bbox.y1)
        if _starts_bullet_item(unit.text) or (prev_height > 0 and gap > prev_height * 0.5):
            parts.append("\n")
        elif parts and not parts[-1].endswith((" ", "\n", "-")):
            parts.append(" ")
        parts.append(unit.text)
    return "".join(parts).strip()


def _build_paragraphs(
    page_num: int,
    runs: list[EditableSpan],
) -> list[EditableParagraph]:
    if not runs:
        return []

    by_block: dict[int, list[EditableSpan]] = {}
    for run in runs:
        by_block.setdefault(run.block_idx, []).append(run)

    paragraphs: list[EditableParagraph] = []
    for block_idx in sorted(by_block.keys()):
        block_runs = sorted(
            by_block[block_idx],
            key=lambda r: (r.line_idx, r.span_idx),
        )
        if not block_runs:
            continue

        # Decided once for the whole block, then handed to both rule sites: rule (b)
        # is exempt for vertical blocks for the same reason rules (a)/(a2) are --
        # their columns never x-overlap, so grouping would shred every one.
        split_cells = _block_splits_cells(block_runs)

        units = _block_paragraph_units(block_runs, split_cells)
        if not units:
            continue

        column_groups = _group_units_into_columns(units) if split_cells else [units]

        para_idx = 0
        for group in column_groups:
            ordered_units = sorted(group, key=lambda u: (u.line_idx, float(u.bbox.x0)))
            para_text = _compose_paragraph_text(ordered_units)
            if not para_text:
                continue

            group_runs = sorted(
                (run for unit in ordered_units for run in unit.runs),
                key=lambda r: (r.line_idx, r.span_idx),
            )
            if not group_runs:
                continue

            bbox = fitz.Rect(group_runs[0].bbox)
            font_counter: Counter[str] = Counter()
            color_counter: Counter[tuple] = Counter()
            size_sum = 0.0
            size_count = 0
            for run in group_runs[1:]:
                bbox.include_rect(run.bbox)
            for run in group_runs:
                font_counter[run.font] += max(1, len((run.text or "").strip()))
                color_counter[tuple(run.color)] += max(1, len((run.text or "").strip()))
                size_sum += float(run.size)
                size_count += 1

            dominant_font = (
                font_counter.most_common(1)[0][0]
                if font_counter
                else group_runs[0].font
            )
            dominant_color = (
                color_counter.most_common(1)[0][0]
                if color_counter
                else tuple(group_runs[0].color)
            )
            avg_size = size_sum / max(1, size_count)

            first = group_runs[0]
            para_id = f"pg{page_num}_b{block_idx}_p{para_idx}"
            para_idx += 1
            paragraphs.append(
                EditableParagraph(
                    paragraph_id=para_id,
                    page_idx=page_num,
                    block_idx=block_idx,
                    bbox=bbox,
                    text=para_text,
                    font=dominant_font,
                    size=float(avg_size),
                    color=tuple(dominant_color),
                    dir_vec=(float(first.dir_vec[0]), float(first.dir_vec[1])),
                    rotation=int(first.rotation),
                    run_ids=[r.span_id for r in group_runs],
                    line_start=min(r.line_idx for r in group_runs),
                    line_end=max(r.line_idx for r in group_runs),
                )
            )

    return _merge_vertical_paragraphs(page_num, paragraphs)


def _merge_vertical_paragraphs(
    page_num: int,
    paragraphs: list[EditableParagraph],
) -> list[EditableParagraph]:
    vertical = [p for p in paragraphs if p.rotation in (90, 270)]
    if len(vertical) <= 1:
        return paragraphs

    non_vertical = [p for p in paragraphs if p.rotation not in (90, 270)]
    ordered = sorted(
        vertical,
        key=lambda p: ((-p.bbox.x0) if p.rotation == 90 else p.bbox.x0, p.bbox.y0),
    )

    merged: list[EditableParagraph] = []
    i = 0
    merge_idx = 0
    while i < len(ordered):
        group = [ordered[i]]
        i += 1
        while i < len(ordered) and _can_merge_vertical_paragraph(group[-1], ordered[i]):
            group.append(ordered[i])
            i += 1
        if len(group) == 1:
            merged.append(group[0])
            continue
        merged.append(_compose_merged_vertical_paragraph(page_num, group, merge_idx))
        merge_idx += 1

    return non_vertical + merged


def _can_merge_vertical_paragraph(left: EditableParagraph, right: EditableParagraph) -> bool:
    if left.rotation not in (90, 270) or right.rotation != left.rotation:
        return False

    dot = float(left.dir_vec[0]) * float(right.dir_vec[0]) + float(left.dir_vec[1]) * float(right.dir_vec[1])
    if dot < 0.95:
        return False
    if abs(float(left.size) - float(right.size)) > 1.5:
        return False
    if any(abs(float(a) - float(b)) > 0.08 for a, b in zip(left.color, right.color)):
        return False

    y0 = max(float(left.bbox.y0), float(right.bbox.y0))
    y1 = min(float(left.bbox.y1), float(right.bbox.y1))
    overlap = max(0.0, y1 - y0)
    min_h = max(1.0, min(float(left.bbox.height), float(right.bbox.height)))
    if overlap / min_h < 0.70:
        return False

    width_ref = max(1.0, min(float(left.bbox.width), float(right.bbox.width)))
    x_gap = abs(float(right.bbox.x0) - float(left.bbox.x0))
    if x_gap > width_ref * 2.8:
        return False
    return True


def _compose_merged_vertical_paragraph(
    page_num: int,
    group: list[EditableParagraph],
    merge_idx: int,
) -> EditableParagraph:
    ordered = sorted(
        group,
        key=lambda p: ((-p.bbox.x0) if p.rotation == 90 else p.bbox.x0, p.bbox.y0),
    )
    text_parts = [p.text.strip() for p in ordered if p.text.strip()]
    para_text = " ".join(text_parts).strip()

    bbox = fitz.Rect(ordered[0].bbox)
    run_ids: list[str] = []
    font_counter: Counter[str] = Counter()
    color_counter: Counter[tuple] = Counter()
    size_weighted = 0.0
    weight_total = 0
    line_start = ordered[0].line_start
    line_end = ordered[0].line_end

    for para in ordered:
        bbox.include_rect(para.bbox)
        run_ids.extend(para.run_ids)
        weight = max(1, len((para.text or "").strip()))
        font_counter[para.font] += weight
        color_counter[tuple(para.color)] += weight
        size_weighted += float(para.size) * weight
        weight_total += weight
        line_start = min(line_start, para.line_start)
        line_end = max(line_end, para.line_end)

    dominant_font = font_counter.most_common(1)[0][0] if font_counter else ordered[0].font
    dominant_color = color_counter.most_common(1)[0][0] if color_counter else tuple(ordered[0].color)
    avg_size = size_weighted / max(1, weight_total)
    first = ordered[0]

    return EditableParagraph(
        paragraph_id=f"pg{page_num}_vmerge_{merge_idx}",
        page_idx=page_num,
        block_idx=first.block_idx,
        bbox=bbox,
        text=para_text,
        font=dominant_font,
        size=float(avg_size),
        color=tuple(dominant_color),
        dir_vec=(float(first.dir_vec[0]), float(first.dir_vec[1])),
        rotation=int(first.rotation),
        run_ids=run_ids,
        line_start=line_start,
        line_end=line_end,
    )


def _expand_ligatures(text: str) -> str:
    for lig, expanded in _LIGATURE_MAP.items():
        if lig in text:
            text = text.replace(lig, expanded)
    return text


def _match_by_text(
    candidates: list[TextBlock],
    original_text: str,
) -> TextBlock | None:
    original_clean = _expand_ligatures(
        _RE_WS_STRIP.sub("", original_text.strip()).lower()
    )
    if not original_clean:
        return None

    best_block: TextBlock | None = None
    best_similarity = 0.5

    for block in candidates:
        block_clean = _expand_ligatures(
            _RE_WS_STRIP.sub("", block.text.strip()).lower()
        )
        if not block_clean:
            continue

        len_ratio = max(len(original_clean), len(block_clean)) / max(
            1, min(len(original_clean), len(block_clean))
        )
        if len_ratio > 3.0:
            continue

        if original_clean in block_clean or block_clean in original_clean:
            return block

        similarity = difflib.SequenceMatcher(None, original_clean, block_clean).ratio()
        if similarity > best_similarity:
            best_similarity = similarity
            best_block = block

    return best_block


def _closest_to_center(
    candidates: list[TextBlock],
    rect: fitz.Rect,
) -> TextBlock | None:
    rect_cx = rect.x0 + rect.width / 2
    rect_cy = rect.y0 + rect.height / 2
    best_block: TextBlock | None = None
    min_distance = float("inf")

    for block in candidates:
        bcx = block.layout_rect.x0 + block.layout_rect.width / 2
        bcy = block.layout_rect.y0 + block.layout_rect.height / 2
        dist = abs(bcx - rect_cx) + abs(bcy - rect_cy)
        if dist < min_distance:
            min_distance = dist
            best_block = block

    return best_block


def _dynamic_scan(
    page_num: int,
    rect: fitz.Rect,
    original_text: str | None,
    doc: fitz.Document,
) -> TextBlock | None:
    page = doc[page_num]
    blocks_raw = page.get_text("dict", flags=0).get("blocks", [])
    temp_blocks: list[TextBlock] = []

    for i, block in enumerate(blocks_raw):
        if block.get("type") != 0:
            continue
        if not fitz.Rect(block["bbox"]).intersects(rect):
            continue
        tb = _parse_block(page_num, i, block)
        if tb is not None:
            temp_blocks.append(tb)

    if not temp_blocks:
        return None
    if original_text and original_text.strip():
        matched = _match_by_text(temp_blocks, original_text)
        if matched is not None:
            return matched
    return _closest_to_center(temp_blocks, rect)
