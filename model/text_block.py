from __future__ import annotations

import dataclasses
import logging
import math
from dataclasses import dataclass

import fitz

# R3.1: the stateless parsing layer (helpers, dataclasses, fitz-dict -> dataclass
# transforms) lives in text_block_parsing. TextBlockManager (below) keeps ownership
# of every page-keyed index and delegates the pure transforms. The dataclasses and
# rotation_degrees_from_dir are re-exported here for backward compatibility.
from model import text_block_parsing as _tbp
from model.page_content_text import content_text, content_textpage
from model.text_block_parsing import (
    EditableParagraph,
    EditableSpan,
    TextBlock,
    rotation_degrees_from_dir,  # noqa: F401  (re-export: pdf_model imports it from here)
)

logger = logging.getLogger(__name__)

_PAGE_STORES = (
    "_index",
    "_span_index",
    "_paragraph_index",
    "_run_to_paragraph",
    "_page_plain_lines",
    "_fallback_rows",
)


@dataclass(frozen=True, slots=True)
class FallbackRow:
    """One flags-0 dict text block, as the point-hit miss fallback reads it."""

    block_idx: int
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    color_int: int
    rotation: int
    text: str


@dataclass(frozen=True, slots=True)
class PageIndexEntry:
    """Everything the text index holds for one page, as plain data (no manager state).

    Produced by ``extract_page_entry`` (pure: reads the page, mutates no manager) and written
    into the stores by ``TextBlockManager.install_page_entry``.
    """

    blocks: tuple[TextBlock, ...]
    spans: tuple[EditableSpan, ...]
    paragraphs: tuple[EditableParagraph, ...]
    run_map: dict[str, str]
    plain_lines: tuple[str, ...]
    fallback_rows: tuple[FallbackRow, ...]


def _build_fallback_rows(blocks_raw: list[dict]) -> list[FallbackRow]:
    # The index dict is content_textpage(page, 0) + "dict": the very
    # extraction the miss fallback used to redo per lookup.
    rows: list[FallbackRow] = []
    for block_idx, block in enumerate(blocks_raw):
        if block.get("type") != 0:
            continue
        font_name = "helv"
        font_size = 12.0
        color_int = 0
        rotation = 0
        lines = block.get("lines")
        if lines and lines[0].get("spans"):
            first_span = lines[0]["spans"][0]
            font_name = first_span.get("font", "helv")
            font_size = float(first_span.get("size", 12.0))
            color_int = int(first_span.get("color", 0))
        if lines and lines[0].get("dir") is not None:
            rotation = rotation_degrees_from_dir(lines[0]["dir"])
        rows.append(
            FallbackRow(
                block_idx=block_idx,
                bbox=tuple(fitz.Rect(block["bbox"])),
                font=font_name,
                size=font_size,
                color_int=color_int,
                rotation=rotation,
                text=_tbp.compose_block_text_for_hit(block),
            )
        )
    return rows


def extract_page_entry(page_num: int, page: fitz.Page) -> PageIndexEntry:
    """Pure half of the index build: interpret ``page`` and return its entry."""
    # Content only (F11-ANN-4): an annotation's appearance text is not an
    # editable block.  One interpretation serves both extractions.
    textpage = content_textpage(page, 0)
    blocks_raw = content_text(page, "dict", textpage=textpage).get("blocks", [])
    raw_blocks = content_text(page, "rawdict", textpage=textpage).get("blocks", [])
    plain_lines = _tbp._extract_plain_text_lines(page)
    page_blocks: list[TextBlock] = []
    page_spans: list[EditableSpan] = []

    for block_idx, block in enumerate(blocks_raw):
        tb = _tbp._parse_block(page_num, block_idx, block)
        if tb is not None:
            page_blocks.append(tb)
        raw_block = raw_blocks[block_idx] if block_idx < len(raw_blocks) else None
        if raw_block and raw_block.get("type") == 0:
            runs = _tbp._parse_runs_from_raw_block(page_num, block_idx, raw_block, plain_lines=plain_lines)
            if runs:
                page_spans.extend(runs)
                continue
        page_spans.extend(_tbp._parse_spans(page_num, block_idx, block))

    paragraphs = _tbp._build_paragraphs(page_num, page_spans)
    run_map: dict[str, str] = {}
    for para in paragraphs:
        for run_id in para.run_ids:
            run_map[run_id] = para.paragraph_id
    return PageIndexEntry(
        blocks=tuple(page_blocks),
        spans=tuple(page_spans),
        paragraphs=tuple(paragraphs),
        run_map=run_map,
        plain_lines=tuple(plain_lines),
        fallback_rows=tuple(_build_fallback_rows(blocks_raw)),
    )


# JSON field kinds per dataclass, in declaration order.  to_json refuses a dataclass whose fields
# differ from this table (a new field must be added here on purpose, never dropped silently), and
# from_json validates every value against its kind before building anything (the answer of a child
# process is untrusted input).
_STR, _INT, _FLOAT = "str", "int", "float"
_RECT, _POINT = "rect", "point"
_COLOR, _DIR, _BBOX4, _STR_LIST = "color", "dir", "bbox4", "str_list"
_FIELD_KINDS: dict[type, dict[str, str]] = {
    TextBlock: {
        "block_id": _STR, "page_num": _INT, "rect": _RECT, "layout_rect": _RECT, "text": _STR,
        "font": _STR, "size": _FLOAT, "color": _COLOR, "rotation": _INT, "original_span_count": _INT,
    },
    EditableSpan: {
        "span_id": _STR, "page_idx": _INT, "block_idx": _INT, "line_idx": _INT, "span_idx": _INT,
        "bbox": _RECT, "origin": _POINT, "text": _STR, "font": _STR, "size": _FLOAT, "color": _COLOR,
        "dir_vec": _DIR, "rotation": _INT,
    },
    EditableParagraph: {
        "paragraph_id": _STR, "page_idx": _INT, "block_idx": _INT, "bbox": _RECT, "text": _STR,
        "font": _STR, "size": _FLOAT, "color": _COLOR, "dir_vec": _DIR, "rotation": _INT,
        "run_ids": _STR_LIST, "line_start": _INT, "line_end": _INT,
    },
    FallbackRow: {
        "block_idx": _INT, "bbox": _BBOX4, "font": _STR, "size": _FLOAT, "color_int": _INT,
        "rotation": _INT, "text": _STR,
    },
}
_SEQ_LENGTHS = {_RECT: 4, _POINT: 2, _DIR: 2, _BBOX4: 4, _COLOR: 3}


_MAX_INT_FIELD = 2**31  # index / rotation / count fields: a real page is nowhere near
_MAX_INT_COORD = 2**53  # an integer written where a float is expected must still convert exactly


def _is_number(value: object) -> bool:
    kind = type(value)
    if kind is int:
        return -_MAX_INT_COORD <= value <= _MAX_INT_COORD  # type: ignore[operator]
    return kind is float and math.isfinite(value)  # type: ignore[arg-type]


def _is_clean_str(value: object) -> bool:
    """A str that survives UTF-8 (no lone surrogate): it is re-encoded when the document is saved."""
    if type(value) is not str:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _number_list(name: str, value: object, kind: str) -> list:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name}: expected a list")
    want = _SEQ_LENGTHS.get(kind)
    if want is not None and len(value) != want:
        raise ValueError(f"{name}: expected {want} numbers, got {len(value)}")
    if kind == _COLOR and len(value) > 4:
        raise ValueError(f"{name}: too many colour components")
    if not all(_is_number(v) for v in value):
        raise ValueError(f"{name}: numbers must be finite int/float")
    return list(value)


def _obj_to_json(obj: object) -> dict:
    cls = type(obj)
    kinds = _FIELD_KINDS.get(cls)
    if kinds is None:
        raise ValueError(f"no JSON mapping for {cls.__name__}")
    names = [f.name for f in dataclasses.fields(obj)]  # type: ignore[arg-type]
    expected = list(kinds)
    # TextBlock.is_vertical is set by __post_init__ and not serialised.
    if cls is TextBlock:
        names = [n for n in names if n != "is_vertical"]
    if names != expected:
        raise ValueError(f"{cls.__name__} fields {names} differ from the JSON mapping {expected}")
    out: dict = {}
    for name, kind in kinds.items():
        value = getattr(obj, name)
        if kind in (_RECT, _POINT):
            out[name] = [float(v) for v in value]
        elif kind in (_COLOR, _DIR, _BBOX4, _STR_LIST):
            out[name] = list(value)
        else:
            out[name] = value
    return out


def _decode_value(cls_name: str, name: str, kind: str, value: object):
    where = f"{cls_name}.{name}"
    if kind == _STR:
        if not _is_clean_str(value):
            raise ValueError(f"{where}: expected an encodable str")
        return value
    if kind == _INT:
        if type(value) is not int or abs(value) > _MAX_INT_FIELD:
            raise ValueError(f"{where}: expected a bounded int")
        return value
    if kind == _FLOAT:
        if not _is_number(value):
            raise ValueError(f"{where}: expected a finite number")
        return float(value)  # type: ignore[arg-type]
    if kind == _STR_LIST:
        if not isinstance(value, list) or not all(_is_clean_str(v) for v in value):
            raise ValueError(f"{where}: expected list[str]")
        return list(value)
    nums = _number_list(where, value, kind)
    if kind == _RECT:
        return fitz.Rect(*nums)
    if kind == _POINT:
        return fitz.Point(*nums)
    return tuple(nums)


def _obj_from_json(cls: type, data: object):
    kinds = _FIELD_KINDS[cls]
    if not isinstance(data, dict) or set(data) != set(kinds):
        raise ValueError(f"{cls.__name__} JSON keys unexpected")
    return cls(**{name: _decode_value(cls.__name__, name, kind, data[name]) for name, kind in kinds.items()})


_ENTRY_KEYS = ["blocks", "spans", "paragraphs", "run_map", "plain_lines", "fallback_rows"]


def page_entry_to_json(entry: PageIndexEntry) -> dict:
    """JSON-ready dict of ``entry``: geometry as float lists, floats unrounded."""
    return {
        "blocks": [_obj_to_json(b) for b in entry.blocks],
        "spans": [_obj_to_json(s) for s in entry.spans],
        "paragraphs": [_obj_to_json(p) for p in entry.paragraphs],
        "run_map": dict(entry.run_map),
        "plain_lines": list(entry.plain_lines),
        "fallback_rows": [_obj_to_json(r) for r in entry.fallback_rows],
    }


def _json_list(data: dict, key: str) -> list:
    value = data[key]
    if not isinstance(value, list):
        raise ValueError(f"page entry {key} must be a list")
    return value


def page_entry_from_json(data: object) -> PageIndexEntry:
    """Inverse of ``page_entry_to_json``; raises ValueError (and nothing else) on a bad answer."""
    try:
        return _page_entry_from_json(data)
    except ValueError:
        raise
    except Exception:
        # Whatever a hostile value provokes (TypeError, OverflowError, ...) is one refusal.
        raise ValueError("malformed page entry") from None


def _page_entry_from_json(data: object) -> PageIndexEntry:
    """Raises ValueError on any unexpected shape or value.

    Key order is irrelevant (key sets are compared).  Nothing is built from a value that failed
    its kind check, and the caller installs nothing unless this returns.
    """
    if not isinstance(data, dict) or set(data) != set(_ENTRY_KEYS):
        raise ValueError("page entry JSON has unexpected keys")
    plain_lines = _json_list(data, "plain_lines")
    if not all(_is_clean_str(line) for line in plain_lines):
        raise ValueError("page entry plain_lines must be list[str]")
    run_map = data["run_map"]
    if not isinstance(run_map, dict) or not all(
        _is_clean_str(k) and _is_clean_str(v) for k, v in run_map.items()
    ):
        raise ValueError("page entry run_map must be dict[str, str]")
    return PageIndexEntry(
        blocks=tuple(_obj_from_json(TextBlock, b) for b in _json_list(data, "blocks")),
        spans=tuple(_obj_from_json(EditableSpan, s) for s in _json_list(data, "spans")),
        paragraphs=tuple(_obj_from_json(EditableParagraph, p) for p in _json_list(data, "paragraphs")),
        run_map=dict(run_map),
        plain_lines=tuple(plain_lines),
        fallback_rows=tuple(_obj_from_json(FallbackRow, r) for r in _json_list(data, "fallback_rows")),
    )


def _check_entry_for_page(page_num: int, entry: PageIndexEntry) -> None:
    """Refuse an entry that does not belong to ``page_num`` or is not internally consistent.

    Raises ValueError and nothing else.
    """
    try:
        _check_entry(page_num, entry)
    except ValueError:
        raise
    except Exception:
        raise ValueError("malformed page entry") from None


def _check_entry(page_num: int, entry: PageIndexEntry) -> None:
    if type(entry) is not PageIndexEntry:
        raise ValueError("not a PageIndexEntry")
    for name, cls in (
        ("blocks", TextBlock), ("spans", EditableSpan), ("paragraphs", EditableParagraph),
        ("fallback_rows", FallbackRow),
    ):
        seq = getattr(entry, name)
        if not isinstance(seq, (tuple, list)) or any(type(item) is not cls for item in seq):
            raise ValueError(f"entry {name} must hold {cls.__name__} only")
    if not isinstance(entry.plain_lines, (tuple, list)) or any(type(x) is not str for x in entry.plain_lines):
        raise ValueError("entry plain_lines must be a sequence of str")
    for block in entry.blocks:
        if block.page_num != page_num or not block.block_id.startswith(f"page_{page_num}_block_"):
            raise ValueError(f"block {block.block_id!r} does not belong to page {page_num}")
    for span in entry.spans:
        if span.page_idx != page_num or not span.span_id.startswith(f"p{page_num}_b"):
            raise ValueError(f"span {span.span_id!r} does not belong to page {page_num}")
    for para in entry.paragraphs:
        if para.page_idx != page_num or not para.paragraph_id.startswith(f"pg{page_num}_"):
            raise ValueError(f"paragraph {para.paragraph_id!r} does not belong to page {page_num}")
    run_map = entry.run_map
    if not isinstance(run_map, dict) or not all(type(k) is str and type(v) is str for k, v in run_map.items()):
        raise ValueError("entry run_map must be dict[str, str]")
    span_ids = {s.span_id for s in entry.spans}
    para_ids = {p.paragraph_id for p in entry.paragraphs}
    if (
        len(span_ids) != len(entry.spans)
        or len(para_ids) != len(entry.paragraphs)
        or len({b.block_id for b in entry.blocks}) != len(entry.blocks)
    ):
        raise ValueError("entry has a duplicate block, span or paragraph id")
    derived: dict[str, str] = {}
    for para in entry.paragraphs:
        if not isinstance(para.run_ids, list) or any(rid not in span_ids for rid in para.run_ids):
            raise ValueError(f"paragraph {para.paragraph_id!r} names a run that is not in the entry")
        for rid in para.run_ids:
            derived[rid] = para.paragraph_id
    if run_map != derived:
        raise ValueError("entry run_map does not match the paragraphs' run_ids")


class TextBlockManager:
    def __init__(self):
        self._index: dict[int, list[TextBlock]] = {}
        self._span_index: dict[int, list[EditableSpan]] = {}
        self._paragraph_index: dict[int, list[EditableParagraph]] = {}
        self._run_to_paragraph: dict[int, dict[str, str]] = {}
        self._page_plain_lines: dict[int, list[str]] = {}
        self._fallback_rows: dict[int, list[FallbackRow]] = {}
        # Page-level cache state for the current document snapshot.
        #
        # Why it exists:
        # - Structural operations (insert/delete pages) shift page numbers. Existing cached entries are still
        #   useful, but their "page_idx -> content" mapping becomes invalid until rebuilt.
        # - Instead of forcing a full-document rebuild (slow + UI-stalling), we keep unaffected entries and
        #   mark shifted entries as "stale". They will be rebuilt on-demand (edit/search) or drained in a
        #   background batch loop (controller).
        #
        # State values:
        # - "missing": no cache (default for absent key)
        # - "clean"  : cache matches the current doc snapshot for this page_idx
        # - "stale"  : cache exists but the page index was shifted by a structural op; must rebuild before use
        self._page_state: dict[int, str] = {}

    def build_index(self, doc: fitz.Document) -> None:
        self._index.clear()
        self._span_index.clear()
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
        self._page_plain_lines.clear()
        self._fallback_rows.clear()
        self._page_state.clear()
        for page_num in range(len(doc)):
            self._build_page_index(page_num, doc[page_num])
        total = sum(len(blocks) for blocks in self._index.values())
        logger.info(f"TextBlockManager index built: {total} blocks")

    def rebuild_page(self, page_num: int, doc: fitz.Document) -> None:
        if page_num < 0 or page_num >= len(doc):
            logger.warning(f"rebuild_page out of range: {page_num}")
            return
        self._build_page_index(page_num, doc[page_num])

    def page_state(self, page_idx: int) -> str:
        """Return cache state for 0-based page index ("missing" | "clean" | "stale")."""
        return self._page_state.get(page_idx, "missing")

    def mark_page_stale(self, page_idx: int) -> None:
        """A content write outside the text engine (a vector delete) changed this page: rebuild lazily."""
        if page_idx in self._page_state:
            self._page_state[page_idx] = "stale"

    def list_stale_pages(self) -> list[int]:
        """Return sorted 0-based page indices that are known stale and safe to rebuild lazily."""
        return sorted(page_idx for page_idx, state in self._page_state.items() if state == "stale")

    def shift_after_insert(self, insert_at: int, count: int) -> None:
        if count <= 0:
            return
        # Keep cached entries, but shift their keys to match the new page numbering.
        # Any moved page becomes stale because the underlying page content at that new index is different.
        for store_name in _PAGE_STORES:
            store = getattr(self, store_name)
            moved = {}
            for page_idx in sorted(store.keys(), reverse=True):
                if page_idx >= insert_at:
                    moved[page_idx + count] = store.pop(page_idx)
            store.update(moved)
        moved_state: dict[int, str] = {}
        for page_idx in sorted(self._page_state.keys(), reverse=True):
            if page_idx >= insert_at:
                moved_state[page_idx + count] = "stale"
                self._page_state.pop(page_idx)
        self._page_state.update(moved_state)

    def shift_after_delete(self, deleted_pages: list[int]) -> None:
        if not deleted_pages:
            return
        deleted = sorted(set(deleted_pages))
        deleted_set = set(deleted)
        # After deletion, later cached pages slide left; any page that moved becomes stale until rebuilt.
        for store_name in _PAGE_STORES:
            store = getattr(self, store_name)
            remapped = {}
            for page_idx in sorted(store.keys()):
                if page_idx in deleted_set:
                    continue
                shift = sum(1 for deleted_idx in deleted if deleted_idx < page_idx)
                remapped[page_idx - shift] = store[page_idx]
            store.clear()
            store.update(remapped)
        remapped_state: dict[int, str] = {}
        for page_idx in sorted(self._page_state.keys()):
            if page_idx in deleted_set:
                continue
            shift = sum(1 for deleted_idx in deleted if deleted_idx < page_idx)
            new_idx = page_idx - shift
            state = self._page_state[page_idx]
            remapped_state[new_idx] = "stale" if shift else state
        self._page_state.clear()
        self._page_state.update(remapped_state)

    def shift_after_move(self, source_idx: int, destination_idx: int) -> None:
        """Remap cached pages after moving one page to its final 0-based destination.

        Every page in the moved interval becomes stale.  The cached content follows
        its PDF page to the correct key so no unrelated page is lost, but callers
        must rebuild the stale interval before trusting its text geometry.
        """
        if source_idx == destination_idx:
            return

        first_idx = min(source_idx, destination_idx)
        last_idx = max(source_idx, destination_idx)

        def remap_page_idx(page_idx: int) -> int:
            if page_idx == source_idx:
                return destination_idx
            if source_idx < destination_idx and source_idx < page_idx <= destination_idx:
                return page_idx - 1
            if destination_idx < source_idx and destination_idx <= page_idx < source_idx:
                return page_idx + 1
            return page_idx

        for store_name in _PAGE_STORES:
            store = getattr(self, store_name)
            remapped = {remap_page_idx(page_idx): value for page_idx, value in store.items()}
            store.clear()
            store.update(remapped)

        remapped_state = {
            remap_page_idx(page_idx): state for page_idx, state in self._page_state.items()
        }
        for page_idx in range(first_idx, last_idx + 1):
            remapped_state[page_idx] = "stale"
        self._page_state.clear()
        self._page_state.update(remapped_state)

    def _build_page_index(self, page_num: int, page: fitz.Page) -> None:
        self.install_page_entry(page_num, extract_page_entry(page_num, page))

    def install_page_entry(self, page_num: int, entry: PageIndexEntry) -> None:
        """Install half of the index build: write every per-page store and mark the page clean.

        All-or-nothing: the entry is validated against ``page_num`` and every new store value is
        built before the first store is assigned, so a refused entry leaves the manager untouched.
        """
        _check_entry_for_page(page_num, entry)
        blocks = list(entry.blocks)
        spans = list(entry.spans)
        paragraphs = list(entry.paragraphs)
        run_map = dict(entry.run_map)
        plain_lines = list(entry.plain_lines)
        fallback_rows = list(entry.fallback_rows)
        self._index[page_num] = blocks
        self._span_index[page_num] = spans
        self._paragraph_index[page_num] = paragraphs
        self._run_to_paragraph[page_num] = run_map
        self._page_plain_lines[page_num] = plain_lines
        self._fallback_rows[page_num] = fallback_rows
        self._page_state[page_num] = "clean"
        logger.debug(
            f"page {page_num + 1}: {len(blocks)} blocks, {len(spans)} spans(runs), "
            f"{len(paragraphs)} paragraphs"
        )

    @staticmethod
    def _build_fallback_rows(blocks_raw: list[dict]) -> list[FallbackRow]:
        return _build_fallback_rows(blocks_raw)

    def get_fallback_rows(self, page_num: int) -> list[FallbackRow]:
        return self._fallback_rows.get(page_num, [])

    def get_blocks(self, page_num: int) -> list[TextBlock]:
        return self._index.get(page_num, [])

    def get_spans(self, page_num: int) -> list[EditableSpan]:
        return self._span_index.get(page_num, [])

    # Run-level aliases: reconstructed runs are stored in _span_index for compatibility.
    def get_runs(self, page_num: int) -> list[EditableSpan]:
        return self.get_spans(page_num)

    def get_paragraphs(self, page_num: int) -> list[EditableParagraph]:
        return self._paragraph_index.get(page_num, [])

    def find_by_id(self, page_num: int, block_id: str) -> TextBlock | None:
        for block in self._index.get(page_num, []):
            if block.block_id == block_id:
                return block
        return None

    def find_span_by_id(self, page_num: int, span_id: str) -> EditableSpan | None:
        for span in self._span_index.get(page_num, []):
            if span.span_id == span_id:
                return span
        return None

    def find_run_by_id(self, page_num: int, run_id: str) -> EditableSpan | None:
        return self.find_span_by_id(page_num, run_id)

    def find_paragraph_by_id(self, page_num: int, paragraph_id: str) -> EditableParagraph | None:
        for para in self._paragraph_index.get(page_num, []):
            if para.paragraph_id == paragraph_id:
                return para
        return None

    def find_paragraph_for_run(self, page_num: int, run_id: str) -> EditableParagraph | None:
        para_id = self._run_to_paragraph.get(page_num, {}).get(run_id)
        if not para_id:
            return None
        return self.find_paragraph_by_id(page_num, para_id)

    def find_overlapping_spans(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            span
            for span in self._span_index.get(page_num, [])
            if fitz.Rect(span.bbox).intersects(expanded)
        ]

    def find_overlapping_runs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableSpan]:
        return self.find_overlapping_spans(page_num, rect, tol=tol)

    def find_overlapping_paragraphs(
        self,
        page_num: int,
        rect: fitz.Rect,
        tol: float = 0.5,
    ) -> list[EditableParagraph]:
        expanded = fitz.Rect(rect.x0 - tol, rect.y0 - tol, rect.x1 + tol, rect.y1 + tol)
        return [
            para
            for para in self._paragraph_index.get(page_num, [])
            if fitz.Rect(para.bbox).intersects(expanded)
        ]

    def find_by_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: str | None = None,
        doc: fitz.Document | None = None,
    ) -> TextBlock | None:
        candidates = [
            b for b in self._index.get(page_num, []) if fitz.Rect(b.layout_rect).intersects(rect)
        ]

        if not candidates:
            if doc is not None:
                return self._dynamic_scan(page_num, rect, original_text, doc)
            return None

        if original_text and original_text.strip():
            matched = self._match_by_text(candidates, original_text)
            if matched is not None:
                return matched
        return self._closest_to_center(candidates, rect)

    def update_block(self, block: TextBlock, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(block, key):
                setattr(block, key, value)
        if "rotation" in kwargs:
            block.is_vertical = block.rotation in (90, 270)

    def clear(self) -> None:
        # Clears all cached indices and page state. Callers should rebuild only the pages they need now.
        self._index.clear()
        self._span_index.clear()
        self._paragraph_index.clear()
        self._run_to_paragraph.clear()
        self._page_plain_lines.clear()
        self._fallback_rows.clear()
        self._page_state.clear()
        logger.debug("TextBlockManager index cleared")

    def _parse_block(self, page_num: int, raw_index: int, block: dict) -> TextBlock | None:
        return _tbp._parse_block(page_num, raw_index, block)

    def _parse_spans(self, page_num: int, block_idx: int, block: dict) -> list[EditableSpan]:
        return _tbp._parse_spans(page_num, block_idx, block)

    def _parse_runs_from_raw_block(
        self,
        page_num: int,
        block_idx: int,
        raw_block: dict,
        plain_lines: list[str] | None = None,
    ) -> list[EditableSpan]:
        return _tbp._parse_runs_from_raw_block(page_num, block_idx, raw_block, plain_lines=plain_lines)

    def _parse_runs_from_raw_line(
        self,
        page_num: int,
        block_idx: int,
        line_idx: int,
        line: dict,
        plain_lines: list[str] | None = None,
    ) -> list[EditableSpan]:
        return _tbp._parse_runs_from_raw_line(
            page_num, block_idx, line_idx, line, plain_lines=plain_lines
        )

    @staticmethod
    def _extract_plain_text_lines(page: fitz.Page) -> list[str]:
        return _tbp._extract_plain_text_lines(page)

    @staticmethod
    def _repair_replacement_chars(text: str, plain_lines: list[str] | None) -> str:
        return _tbp._repair_replacement_chars(text, plain_lines)

    def _build_paragraphs(self, page_num: int, runs: list[EditableSpan]) -> list[EditableParagraph]:
        return _tbp._build_paragraphs(page_num, runs)

    def _merge_vertical_paragraphs(
        self,
        page_num: int,
        paragraphs: list[EditableParagraph],
    ) -> list[EditableParagraph]:
        return _tbp._merge_vertical_paragraphs(page_num, paragraphs)

    @staticmethod
    def _can_merge_vertical_paragraph(left: EditableParagraph, right: EditableParagraph) -> bool:
        return _tbp._can_merge_vertical_paragraph(left, right)

    @staticmethod
    def _compose_merged_vertical_paragraph(
        page_num: int,
        group: list[EditableParagraph],
        merge_idx: int,
    ) -> EditableParagraph:
        return _tbp._compose_merged_vertical_paragraph(page_num, group, merge_idx)

    @staticmethod
    def _expand_ligatures(text: str) -> str:
        return _tbp._expand_ligatures(text)

    def _match_by_text(self, candidates: list[TextBlock], original_text: str) -> TextBlock | None:
        return _tbp._match_by_text(candidates, original_text)

    def _closest_to_center(self, candidates: list[TextBlock], rect: fitz.Rect) -> TextBlock | None:
        return _tbp._closest_to_center(candidates, rect)

    def _dynamic_scan(
        self,
        page_num: int,
        rect: fitz.Rect,
        original_text: str | None,
        doc: fitz.Document,
    ) -> TextBlock | None:
        return _tbp._dynamic_scan(page_num, rect, original_text, doc)
