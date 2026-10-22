from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import TYPE_CHECKING

import fitz

from model.annot_geometry import (
    annot_page_rect,
    pdf_number,
    raw_rect_to_page,
    read_raw_rect,
    set_annot_page_rect,
    user_to_page_matrix,
)
from model.geometry import visual_to_unrotated_point, visual_to_unrotated_rect
from model.pdf_content_ops import affine_invert, affine_point
from utils.pdf_object_source import exact_set_key, xref_object_exact, xref_set_key_exact
from utils.pymupdf_refs import forget_walked_annot, sync_open_pages

from .base import ToolExtension

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


class AnnotationTool(ToolExtension):
    # PyMuPDF's named codes (a hand-typed 10 for StrikeOut was really Squiggly).
    _ANNOT_FREE_TEXT = fitz.PDF_ANNOT_FREE_TEXT
    _ANNOT_HIGHLIGHT = fitz.PDF_ANNOT_HIGHLIGHT
    _ANNOT_SQUARE = fitz.PDF_ANNOT_SQUARE
    _ANNOT_CIRCLE = fitz.PDF_ANNOT_CIRCLE
    _ANNOT_UNDERLINE = fitz.PDF_ANNOT_UNDERLINE
    _ANNOT_STRIKEOUT = fitz.PDF_ANNOT_STRIKE_OUT
    _ANNOT_SQUIGGLY = fitz.PDF_ANNOT_SQUIGGLY
    _ANNOT_REDACT = fitz.PDF_ANNOT_REDACT
    _ANNOT_LINK = fitz.PDF_ANNOT_LINK
    # Text markup code -> the ``fitz.Page`` method that re-creates one from quads.
    _MARKUP_ADDERS = {
        fitz.PDF_ANNOT_HIGHLIGHT: "add_highlight_annot",
        fitz.PDF_ANNOT_UNDERLINE: "add_underline_annot",
        fitz.PDF_ANNOT_STRIKE_OUT: "add_strikeout_annot",
        fitz.PDF_ANNOT_SQUIGGLY: "add_squiggly_annot",
    }
    _TEXT_MARKUPS = frozenset(_MARKUP_ADDERS)
    # Annotation dictionary keys holding absolute page-space coordinates
    # (/RD is relative and /Popup is its own annotation).
    _GEOMETRY_KEYS = ("Rect", "QuadPoints", "Vertices", "L", "CL", "InkList")
    # /DA font resource names (lower-cased) that ``add_freetext_annot`` accepts.
    _FREETEXT_BASE14 = frozenset({"helv", "cour", "tiro", "symb", "zadb"})

    def __init__(self, model: PDFModel) -> None:
        self._model = model

    def _require_page(self, page_num: int) -> fitz.Page:
        """Return the fitz.Page for *page_num* (1-based) or raise ValueError.

        Guards both the no-doc case and out-of-range page numbers, preventing
        page 0 from silently resolving to doc[-1] (last page).
        """
        if not self._model.doc:
            raise ValueError("沒有開啟的 PDF 文件")
        if page_num < 1 or page_num > len(self._model.doc):
            raise ValueError(f"無效的頁碼: {page_num}")
        return self._model.doc[page_num - 1]

    def _annot_page_vertices(
        self,
        page: fitz.Page,
        annot: fitz.Annot,
        matrix: tuple[float, float, float, float, float, float],
    ) -> list:
        """``annot.vertices`` in TRUE page space (F15-G2-ANNOT).

        ``Annot.vertices`` drops ``/UserUnit`` on a rotated page exactly like
        ``Annot.rect`` (y = -510 for a markup at y 150 on ``/Rotate 90`` +
        ``/UserUnit 2``).  A text markup's points are its raw ``/QuadPoints``
        mapped through the page frame; every other type, and an unreadable
        array, keeps ``Annot.vertices`` (only markups are re-created from it).
        """
        if annot.type[0] not in self._TEXT_MARKUPS:
            return annot.vertices
        try:
            kind, value = page.parent.xref_get_key(annot.xref, "QuadPoints")
            numbers = [float(v) for v in value.strip()[1:-1].split()] if kind == "array" else []
        except Exception as exc:
            logger.warning("_annot_page_vertices: xref %s /QuadPoints unreadable: %s", annot.xref, exc)
            return annot.vertices
        if not numbers or len(numbers) % 8:
            return annot.vertices
        return [affine_point(matrix, numbers[i], numbers[i + 1]) for i in range(0, len(numbers), 2)]

    @staticmethod
    def _derotate_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
        """Map a displayed-coords rect into the unrotated space add_*_annot expects.

        PyMuPDF's annot-creation geometry is always interpreted in TRUE unrotated
        page space (``/UserUnit`` scaled); the app deals exclusively in displayed
        (page.rect) space.  ``model.geometry`` is the one conversion:
        ``page.derotation_matrix`` drops ``/UserUnit`` on a rotated page, so a rect
        added at (30,50,90,80) on ``/Rotate 90`` + ``/UserUnit 2`` inked at
        (428,48,492,82) (F15-G1-UU-ANNOT).  At rotation 0 it is the identity.
        """
        return visual_to_unrotated_rect(page, rect)

    @staticmethod
    def _derotate_point(page: fitz.Page, point: fitz.Point) -> fitz.Point:
        return visual_to_unrotated_point(page, point)

    @staticmethod
    def _rotate_rect_to_displayed(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
        """Map a stored ``Annot.rect`` back into displayed coords (Text/Note annotations).

        ``Annot.rect`` / ``Annot.set_rect`` live in PyMuPDF's own derotated space,
        the one ``page.derotation_matrix`` makes (``/UserUnit``-less on a rotated
        page): ``page.rotation_matrix`` is the exact inverse, so this reads back
        what ``set_rect(_derotate_text_annot_rect(...))`` wrote at every rotation
        and ``/UserUnit`` (MEASURED, F15-G1-UU-ANNOT).  That space is NOT the one
        ``add_*_annot`` takes (TRUE unrotated, ``model.geometry``): never mix the
        two.  A Text/Note annotation cannot use the raw ``/Rect`` instead: MuPDF
        keeps its icon upright (NoRotate), so the raw rect is not the drawn one.
        Verified empirically for Text/Note icons (the appearance always collapses
        to a fixed square anchored at (x0, y0), so a plain corner-remap +
        normalize recovers the original displayed anchor at every rotation -- no
        separate anchor-only variant is needed here, unlike the write side).
        """
        return (fitz.Rect(rect) * page.rotation_matrix).normalize()

    @staticmethod
    def _derotate_text_annot_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
        """Derotate a Text/Note annot's target rect for ``Annot.set_rect()``.

        ``set_rect`` takes PyMuPDF's derotated space (``page.derotation_matrix``;
        see ``_rotate_rect_to_displayed``), not the TRUE unrotated space of
        ``add_*_annot``.  The Note icon is a fixed-size glyph anchored at
        (rect.x0, rect.y0); PyMuPDF ignores width/height when placing it. A full
        corner-remap (as ``_derotate_rect`` does for real rectangles) would pick
        whichever transformed corner ends up as the new min after normalize(),
        which is not necessarily the original anchor corner. Instead derotate only
        the anchor point and keep the displayed width/height as the rect span.
        """
        anchor = fitz.Point(rect.x0, rect.y0) * page.derotation_matrix
        width = rect.x1 - rect.x0
        height = rect.y1 - rect.y0
        return fitz.Rect(anchor.x, anchor.y, anchor.x + width, anchor.y + height)

    @staticmethod
    def _displayed_rect_to_quad(page: fitz.Page, rect: fitz.Rect) -> fitz.Quad:
        """Corner-map a displayed rect into a derotated fitz.Quad for markup annots.

        Markup ink follows quad corner roles (underline hugs the ll-lr edge,
        strikeout runs mid-height), so a derotated *rect* is insufficient at
        90/270: it would put the ink on a vertical edge instead of preserving
        the displayed-bottom placement. Mapping each named corner through
        ``model.geometry`` (not ``page.derotation_matrix``, which drops
        ``/UserUnit`` on a rotated page, F15-G1-UU-ANNOT) and keeping the
        ul/ur/ll/lr role assignment fixed keeps the ink on the correct edge at
        every rotation.
        """
        r = fitz.Rect(rect)
        ul = visual_to_unrotated_point(page, fitz.Point(r.x0, r.y0))
        ur = visual_to_unrotated_point(page, fitz.Point(r.x1, r.y0))
        ll = visual_to_unrotated_point(page, fitz.Point(r.x0, r.y1))
        lr = visual_to_unrotated_point(page, fitz.Point(r.x1, r.y1))
        return fitz.Quad(ul, ur, ll, lr)

    def add_highlight(self, page_num: int, rect: fitz.Rect, color: tuple[float, float, float, float]) -> None:
        page = self._require_page(page_num)
        quad = self._displayed_rect_to_quad(page, rect)
        annot = page.add_highlight_annot(quad)
        with exact_set_key(page.parent):
            annot.set_colors(stroke=color[:3], fill=color[:3])
        annot.set_opacity(color[3])
        annot.update()
        logger.debug("新增螢光筆: 頁面 %s, 矩形 %s, 顏色 %s", page_num, rect, color)

    def _add_text_markup(
        self,
        kind: str,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        normalized = self._normalize_color(color, name="color")
        page = self._require_page(page_num)
        quad = self._displayed_rect_to_quad(page, rect)
        if kind == "underline":
            annot = page.add_underline_annot(quad)
        elif kind == "strikeout":
            annot = page.add_strikeout_annot(quad)
        else:  # pragma: no cover - private callers use fixed literals
            raise ValueError(f"unsupported markup kind: {kind}")
        with exact_set_key(page.parent):
            annot.set_colors(stroke=normalized[:3])
        annot.set_opacity(normalized[3])
        annot.update()
        logger.debug("新增%s: 頁面 %s, 矩形 %s, 顏色 %s", kind, page_num, rect, normalized)

    def add_underline(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("underline", page_num, rect, color)

    def add_strikeout(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("strikeout", page_num, rect, color)

    def get_text_bounds(self, page_num: int, rough_rect: fitz.Rect) -> fitz.Rect:
        precise_rect = self._model.get_text_selection_bounds(page_num, rough_rect)
        if precise_rect is None:
            logger.debug("頁面 %s 在 %s 無文字，返回原矩形", page_num, rough_rect)
            return rough_rect
        logger.debug("頁面 %s 在 %s 精準矩形 %s", page_num, rough_rect, precise_rect)
        return precise_rect

    @staticmethod
    def _normalize_color(value: object, *, name: str) -> tuple[float, float, float, float]:
        if not isinstance(value, (tuple, list)) or len(value) not in (3, 4):
            raise TypeError(f"{name} must contain three or four numeric channels")
        try:
            channels = tuple(float(channel) for channel in value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name} channels must be numeric") from exc
        if any(not math.isfinite(channel) or channel < 0.0 or channel > 1.0 for channel in channels):
            raise ValueError(f"{name} channels must be within 0..1")
        if len(channels) == 3:
            return channels[0], channels[1], channels[2], 1.0
        return channels[0], channels[1], channels[2], channels[3]

    def add_rect(
        self,
        page_num: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float] | None = None,
        fill: bool | None = None,
        *,
        stroke_color: tuple[float, float, float, float] | None = None,
        fill_color: tuple[float, float, float, float] | None = None,
        border_width: float | None = None,
    ) -> None:
        """Add a rectangle with independent stroke/fill appearance.

        ``color``/``fill`` remain accepted for older callers; new callers pass
        ``stroke_color``/``fill_color`` and an explicit border width.
        """
        stroke = self._normalize_color(
            stroke_color if stroke_color is not None else color,
            name="stroke_color",
        )
        if fill_color is not None:
            normalized_fill = self._normalize_color(fill_color, name="fill_color")
        elif fill:
            normalized_fill = stroke
        else:
            normalized_fill = None
        explicit_border_width = border_width is not None
        if border_width is None:
            width = 0.0 if fill is True and stroke_color is None else 5.0 if fill is False else 1.0
        else:
            if isinstance(border_width, bool):
                raise TypeError("border_width must be numeric")
            try:
                width = float(border_width)
            except (TypeError, ValueError) as exc:
                raise TypeError("border_width must be numeric") from exc
        if (
            not math.isfinite(width)
            or width > 20.0
            or (explicit_border_width and width <= 0.0)
            or (not explicit_border_width and width < 0.0)
        ):
            raise ValueError("border_width must be within 0..20")

        page = self._require_page(page_num)
        annot = page.add_rect_annot(self._derotate_rect(page, rect))
        with exact_set_key(page.parent):
            annot.set_colors(
                stroke=stroke[:3],
                fill=normalized_fill[:3] if normalized_fill is not None else None,
            )
        annot.set_border(width=width)
        annot.set_opacity(stroke[3])
        payload = {
            "version": 1,
            "kind": "rect",
            "object_id": str(uuid.uuid4()),
            "page_num": int(page_num),
            "rect": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
            "fill": normalized_fill is not None,
            "stroke_color": list(stroke),
            "fill_color": list(normalized_fill) if normalized_fill is not None else None,
            "border_width": width,
        }
        annot.set_info(
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            subject="pdf_editor_rect_object",
        )
        annot.update()
        logger.debug(
            "新增矩形: 頁面 %s, 矩形 %s, 線色=%s, 填色=%s, 線寬=%s",
            page_num,
            rect,
            stroke,
            normalized_fill,
            width,
        )

    def add_annotation(self, page_num: int, point: fitz.Point, text: str) -> int:
        page = self._require_page(page_num)
        annot = page.add_text_annot(self._derotate_point(page, point), str(text), icon="Note")
        annot.update()
        logger.debug("新增文字註解: 頁面 %s, 矩形 %s, xref: %s", page_num, annot.rect, annot.xref)
        return annot.xref

    def _find_annotation(self, xref: int) -> tuple[fitz.Page, fitz.Annot] | None:
        if not self._model.doc or not isinstance(xref, int) or xref <= 0:
            return None
        for page in self._model.doc:
            annot = page.first_annot
            while annot is not None:
                if annot.xref == xref:
                    return page, annot
                following = annot.next
                if following is not None:
                    forget_walked_annot(following)  # no Page<->Annot cycle (R10 MBT-1)
                annot = following
        return None

    def update_annotation(self, xref: int, text: str) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        _page, annot = found
        if annot.type[1] != "Text":
            return False
        annot.set_info(content=str(text))
        annot.update()
        return True

    def move_annotation(self, xref: int, rect: fitz.Rect) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        page, annot = found
        if annot.type[1] != "Text":
            return False
        target = fitz.Rect(rect)
        if target.is_empty or any(
            not math.isfinite(value)
            for value in (target.x0, target.y0, target.x1, target.y1)
        ):
            raise ValueError("annotation rect must be finite and non-empty")
        annot.set_rect(self._derotate_text_annot_rect(page, target))
        annot.update()
        return True

    def delete_annotation(self, xref: int) -> bool:
        found = self._find_annotation(xref)
        if found is None:
            return False
        page, annot = found
        if annot.type[1] != "Text":
            return False
        page.delete_annot(annot)
        return True

    def get_all_annotations(self) -> list[dict]:
        results: list[dict] = []
        if not self._model.doc:
            return results

        for page in self._model.doc:
            for annot in page.annots():
                type_name = annot.type[1]
                if type_name not in {"Text", "FreeText"}:
                    continue
                results.append(
                    {
                        "xref": annot.xref,
                        "page_num": page.number,
                        "rect": self._rotate_rect_to_displayed(page, annot.rect),
                        "text": annot.info.get("content", ""),
                        "kind": "note" if type_name == "Text" else "freetext",
                        "read_only": type_name != "Text",
                    }
                )

        logger.debug("找到 %s 個文字註解", len(results))
        return results

    def toggle_annotations_visibility(self, visible: bool) -> None:
        if not self._model.doc:
            return

        for page in self._model.doc:
            for annot in page.annots():
                if annot.type[1] in {"Text", "FreeText"}:
                    current_flags = annot.flags
                    if visible:
                        new_flags = current_flags & ~fitz.PDF_ANNOT_IS_HIDDEN
                    else:
                        new_flags = current_flags | fitz.PDF_ANNOT_IS_HIDDEN
                    annot.set_flags(new_flags)
                    annot.update()

        logger.debug("註解可見性設定為: %s", visible)

    def _save_overlapping_annots(self, page: fitz.Page, redact_rect: fitz.Rect) -> list:
        """Snapshot every annotation intersecting *redact_rect* before a redaction.

        Each entry carries the annotation's ``xref``: ``_restore_annots`` uses it
        to tell an annotation ``apply_redactions`` removed (re-created) from one
        it left in place (kept, or moved by the entry's ``offset``) -- F11-ANN-1.
        """
        saved: list[dict] = []
        matrix = user_to_page_matrix(page)
        try:
            annot_iter = list(page.annots())
        except Exception as exc:
            logger.warning("_save_overlapping_annots: page.annots() 失敗（壞損 annot xref？）: %s", exc)
            return saved

        for annot in annot_iter:
            try:
                if annot is None:
                    continue
                if annot.type[0] == self._ANNOT_REDACT:
                    continue
                page_rect = annot_page_rect(page, annot, matrix)
                if not page_rect.intersects(redact_rect):
                    continue
                entry = {
                    "xref": annot.xref,
                    "type_code": annot.type[0],
                    "type_name": annot.type[1],
                    "rect": page_rect,
                    "info": dict(annot.info),
                    "colors": annot.colors,
                    "opacity": annot.opacity,
                    "border": annot.border,
                    "vertices": self._annot_page_vertices(page, annot, matrix),
                }
                if annot.type[0] == self._ANNOT_FREE_TEXT:
                    entry["freetext_style"] = self._freetext_style(page.parent, annot.xref)
                saved.append(entry)
                logger.debug("_save_overlapping_annots: 儲存 %s @ %s", annot.type[1], page_rect)
            except Exception as exc:
                logger.warning("_save_overlapping_annots: 跳過損壞 annot: %s", exc)
                continue
        saved.extend(self._save_overlapping_links(page, redact_rect, matrix))
        return saved

    @staticmethod
    def _freetext_style(doc: fitz.Document, xref: int) -> dict:
        """Text style of a FreeText as stored: ``/DA`` size, font and colour, ``/Rotate``.

        ``annot.colors`` of a FreeText is /C (its background) and /IC; the text
        colour and size live only in ``/DA``.  Only the fallback re-create
        (F11-ANN-5) reads this; a missing or odd key leaves that field None/0.
        """
        style: dict = {"fontsize": None, "fontname": None, "text_color": None, "rotate": 0}
        try:
            kind, da = doc.xref_get_key(xref, "DA")
            if kind == "string":
                size = re.search(r"(-?\d*\.?\d+)\s+Tf(?!\w)", da)
                if size and float(size.group(1)) > 0:
                    style["fontsize"] = float(size.group(1))
                font = re.search(r"/(\S+)\s+-?\d*\.?\d+\s+Tf(?!\w)", da)
                if font:
                    style["fontname"] = font.group(1)
                # The last colour operator before the text wins.
                operators = list(re.finditer(r"((?:-?\d*\.?\d+\s+){1,4})(rg|g|k)(?!\w)", da))
                if operators:
                    values = tuple(float(v) for v in operators[-1].group(1).split())
                    if len(values) == {"g": 1, "rg": 3, "k": 4}[operators[-1].group(2)]:
                        style["text_color"] = values
            kind, rotate = doc.xref_get_key(xref, "Rotate")
            if kind == "int":
                style["rotate"] = int(rotate) % 360
        except Exception as exc:
            logger.warning("_freetext_style: xref %s 的 /DA 或 /Rotate 無法讀取: %s", xref, exc)
        return style

    def _save_overlapping_links(
        self,
        page: fitz.Page,
        redact_rect: fitz.Rect,
        matrix: tuple[float, float, float, float, float, float] | None = None,
    ) -> list[dict]:
        """Link entries for ``_save_overlapping_annots`` (F11-ANN-3).

        ``page.annots()`` never returns Link annotations, yet ``apply_redactions``
        drops every link intersecting the redaction from ``/Annots`` (the link
        object stays in the xref table).  The rect is ``/Rect`` mapped through
        the page frame (``user_to_page_matrix``): the TRUE unrotated space of
        the redact rects (``get_links()["from"]`` is rotated, never use it;
        ``page.transformation_matrix`` drops the CropBox origin and
        ``/UserUnit`` on a ``/Rotate`` page, F15-G2-ANNOT).
        """
        out: list[dict] = []
        if matrix is None:
            matrix = user_to_page_matrix(page)
        try:
            identities = page.annot_xrefs()
        except Exception as exc:
            logger.warning("_save_overlapping_links: page.annot_xrefs() 失敗: %s", exc)
            return out
        doc = page.parent
        for item in identities:
            try:
                xref, type_code = int(item[0]), int(item[1])
                if type_code != self._ANNOT_LINK:
                    continue
                if xref <= 0:
                    # A direct /Annots entry: the redaction may drop it and
                    # there is no object to put back.
                    logger.warning("_save_overlapping_links: 直接內嵌的 link 無法保存，redaction 可能移除它")
                    continue
                numbers = read_raw_rect(doc, xref)
                if numbers is None:
                    logger.warning("_save_overlapping_links: link xref %s 的 /Rect 無效，未保存", xref)
                    continue
                rect = raw_rect_to_page(page, numbers, matrix)
                if not rect.intersects(redact_rect):
                    continue
                out.append({
                    "xref": xref,
                    "type_code": self._ANNOT_LINK,
                    "type_name": "Link",
                    "rect": rect,
                    "info": {},
                    "colors": None,
                    "opacity": None,
                    "border": None,
                    "vertices": None,
                })
            except Exception as exc:
                logger.warning("_save_overlapping_links: 跳過損壞 link: %s", exc)
        return out

    def _reattach_annot(self, page: fitz.Page, xref: int, subtype: str) -> bool:
        """Append an annotation object the redaction unlisted back to ``/Annots``.

        ``apply_redactions`` removes a link or FreeText from the page's
        ``/Annots`` but leaves the object (and its appearance stream) in the
        xref table.  Putting the same object back keeps the action, destination,
        border, /DA, /C, /Rotate, author, dates, /RC, /IT and the appearance --
        nothing is re-synthesized (links: F11-ANN-3; FreeText: F11-ANN-5).
        Appending (rather than rebuilding the array) keeps direct entries intact.
        The caller has checked the object's ``/Subtype`` and resyncs the loaded
        pages afterwards (F11-ANN-2).
        """
        doc = page.parent
        ref = f"{xref} 0 R"
        kind, value = doc.xref_get_key(page.xref, "Annots")
        if kind == "array":
            inner = value.strip()[1:-1].strip()
            xref_set_key_exact(doc, page.xref, "Annots", f"[{inner} {ref}]" if inner else f"[{ref}]")
        elif kind == "xref":
            array_xref = int(value.split()[0])
            inner = xref_object_exact(doc, array_xref, compressed=True).strip()[1:-1].strip()
            doc.update_object(array_xref, f"[{inner} {ref}]" if inner else f"[{ref}]")
        elif kind in ("null", "none", ""):
            xref_set_key_exact(doc, page.xref, "Annots", f"[{ref}]")
        else:
            logger.warning("_restore_annots: 頁面 /Annots 是 %s，無法還原 %s xref %s", kind, subtype, xref)
            return False
        return True

    @staticmethod
    def _page_annot_identities(page: fitz.Page) -> set[tuple[int, int]] | None:
        """``(xref, type_code)`` of every entry in the page's /Annots, or None."""
        try:
            return {(int(item[0]), int(item[1])) for item in page.annot_xrefs()}
        except Exception as exc:
            logger.warning("_restore_annots: page.annot_xrefs() 失敗: %s", exc)
            return None

    def _translate_annot(self, page: fitz.Page, xref: int, dx: float, dy: float) -> None:
        """Move an annotation by (dx, dy) page units without regenerating it.

        Shifts every absolute coordinate key (/Rect, /QuadPoints, /Vertices,
        /L, /CL, /InkList).  The appearance stream is mapped onto /Rect, so the
        annotation renders at its new place with its original appearance; no
        ``update()`` (which would re-synthesize a foreign AP).
        """
        doc = page.parent
        # (dx, dy) is a TRUE page-space vector: map it back to user space through
        # the page frame (F15-G2-ANNOT), in Python floats.
        to_pdf = affine_invert(user_to_page_matrix(page))
        origin = affine_point(to_pdf, 0.0, 0.0)
        target = affine_point(to_pdf, dx, dy)
        vector = (target[0] - origin[0], target[1] - origin[1])

        def shifted(numbers: list[str]) -> str:
            out = []
            for index, raw in enumerate(numbers):
                delta = vector[0] if index % 2 == 0 else vector[1]
                out.append(pdf_number(float(raw) + delta))
            return "[" + " ".join(out) + "]"

        for key in self._GEOMETRY_KEYS:
            kind, value = doc.xref_get_key(xref, key)
            if kind != "array":
                if kind not in ("null", "none") and kind:
                    logger.warning("_translate_annot: xref %s /%s is %s, not moved", xref, key, kind)
                continue
            inner = value.strip()[1:-1]
            if key == "InkList":
                strokes = [part.split() for part in inner.replace("]", "[").split("[") if part.strip()]
                new_value = "[" + " ".join(shifted(stroke) for stroke in strokes) + "]"
            else:
                new_value = shifted(inner.split())
            xref_set_key_exact(doc, xref, key, new_value)

    @staticmethod
    def _quads_from_vertices(vertices: list, dx: float, dy: float) -> list[fitz.Quad]:
        """``Annot.vertices`` of a text markup = 4 points per quad (QuadPoints order)."""
        points = [fitz.Point(float(p[0]) + dx, float(p[1]) + dy) for p in vertices]
        return [fitz.Quad(*points[i:i + 4]) for i in range(0, len(points) - len(points) % 4, 4)]

    def _restore_annots(self, page: fitz.Page, saved: list) -> None:
        """Put back what a redaction removed from ``_save_overlapping_annots`` entries.

        ``apply_redactions`` deletes only some annotation kinds (PyMuPDF 1.27:
        FreeText, and links); the rest stay in place.  An entry whose
        ``(xref, type)`` is still on the page is therefore NOT re-added (that
        duplicated it, F11-ANN-1); it is moved in place when the entry carries
        an ``offset`` (dx, dy) -- the push-down.  Only removed annotations are
        re-created, at ``rect`` + ``offset``.  A removed link is not re-created:
        its object survives the redaction, so it is moved by ``offset`` and put
        back on ``/Annots`` (F11-ANN-3).  Entries are handled once per xref.  A
        re-create that raises after inserting (PyMuPDF inserts before
        validating) has its partial annotation deleted.  Any link touched
        resyncs the loaded pages, whose cached link list MuPDF does not update
        for a write by xref (F11-ANN-2).

        A removed FreeText is handled like a removed link (F11-ANN-5): its object
        and appearance stream survive the redaction, so the same object is moved
        by ``offset`` and put back on ``/Annots``.  Re-creating it with
        ``add_freetext_annot`` lost its /DA colour and size, /C fill, /Rotate,
        author, dates, /RC and /IT.  Only an entry whose object cannot be put
        back (no xref, the object is gone or no longer that subtype) is
        re-created, from the style saved with it.
        """
        alive = self._page_annot_identities(page)
        # Every link entry with an xref that the loop reaches, whatever its outcome
        # (F11-ANN-3), and every object relisted on /Annots: the loaded pages are
        # resynced for them, also after a failure (F11-ANN-2).
        resync: set[int] = set()
        try:
            self._restore_annot_entries(page, saved, alive, resync)
        finally:
            if resync:
                sync_open_pages(page.parent)

    def _restore_annot_entries(
        self,
        page: fitz.Page,
        saved: list,
        alive: set[tuple[int, int]] | None,
        resync: set[int],
    ) -> None:
        handled: set[int] = set()
        for a in saved:
            xref = a.get("xref")
            if xref is not None:
                if xref in handled:
                    continue
                handled.add(xref)
            tc = a["type_code"]
            if tc == self._ANNOT_LINK and xref is not None:
                resync.add(xref)
            dx, dy = (float(v) for v in (a.get("offset") or (0.0, 0.0)))
            if xref is not None and alive is not None and (int(xref), int(tc)) in alive:
                if dx or dy:
                    try:
                        self._translate_annot(page, int(xref), dx, dy)
                        logger.debug("_restore_annots: 移動 %s xref %s (%s, %s)", a["type_name"], xref, dx, dy)
                    except Exception as exc:
                        logger.warning("_restore_annots: 移動 %s xref %s 失敗: %s", a["type_name"], xref, exc)
                continue
            if xref is not None and alive is None:
                # Cannot tell whether the redaction removed it: re-adding could
                # duplicate it, so leave the page as the redaction left it.
                logger.warning("_restore_annots: 無法確認 %s xref %s 是否仍存在，跳過", a["type_name"], xref)
                continue
            if xref is not None and self._reattach_entry(page, a, int(xref), dx, dy):
                resync.add(int(xref))
                continue
            if tc == self._ANNOT_LINK:
                # Never re-created: its object survives the redaction (F11-ANN-3).
                continue

            rect = fitz.Rect(a["rect"]) + (dx, dy, dx, dy)
            info = a["info"]
            colors = a["colors"] or {}
            stroke = colors.get("stroke") or (0, 0, 0)
            fill = colors.get("fill")
            before = self._page_annot_identities(page)

            try:
                if tc == self._ANNOT_FREE_TEXT:
                    # Fallback only (F11-ANN-5): rebuilt from the saved /DA, /C and
                    # /Rotate.  For a FreeText ``colors["stroke"]`` is /C, the
                    # background -- never the text colour.
                    style = a.get("freetext_style") or {}
                    fontname = str(style.get("fontname") or "").lower()
                    new_a = page.add_freetext_annot(
                        rect,
                        info.get("content", ""),
                        fontname=fontname if fontname in self._FREETEXT_BASE14 else "helv",
                        fontsize=float(style.get("fontsize") or 11.0),
                        text_color=style.get("text_color") or (0, 0, 0),
                        fill_color=colors.get("stroke") or None,
                        rotate=int(style.get("rotate") or 0),
                    )
                    self._copy_annot_info(new_a, info)
                    new_a.update()

                elif tc in self._TEXT_MARKUPS:
                    add_marker = getattr(page, self._MARKUP_ADDERS[tc])
                    quads = self._quads_from_vertices(a.get("vertices") or [], dx, dy)
                    new_a = add_marker(quads=quads) if quads else add_marker(rect)
                    if new_a is None:
                        raise RuntimeError("text marker was not created")
                    if stroke:
                        with exact_set_key(page.parent):
                            new_a.set_colors(stroke=stroke)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    self._copy_annot_info(new_a, info)
                    new_a.update()

                elif tc in (self._ANNOT_SQUARE, self._ANNOT_CIRCLE):
                    if tc == self._ANNOT_SQUARE:
                        new_a = page.add_rect_annot(rect)
                    else:
                        new_a = page.add_circle_annot(rect)
                    self._pin_outer_rect(page, new_a, rect)
                    with exact_set_key(page.parent):
                        new_a.set_colors(stroke=stroke, fill=fill)
                    if a["opacity"] is not None:
                        new_a.set_opacity(a["opacity"])
                    self._copy_annot_info(new_a, info)
                    new_a.update()

                else:
                    logger.warning("_restore_annots: 不支援的 annot 類型 %s (%s)，跳過還原", a["type_name"], tc)
                    continue

                logger.debug("_restore_annots: 已還原 %s @ %s", a["type_name"], rect)

            except Exception as exc:
                logger.warning("_restore_annots: 還原 %s 失敗: %s", a["type_name"], exc)
                self._drop_partial_annots(page, before)

    @staticmethod
    def _pin_outer_rect(page: fitz.Page, annot: fitz.Annot, outer: fitz.Rect) -> None:
        """Make a just-created Square/Circle's outer /Rect equal *outer* (F14-MM-2).

        ``add_rect_annot``/``add_circle_annot`` take the INNER rect and grow /Rect by the
        library's /RD inset (>= 1 pt per side). A saved page-space rect is already the
        outer rect, so re-creating from it inflated the annotation again. Measure the
        inset this call produced and shrink the inner rect by it; the caller's
        ``update()`` re-applies the same inset, landing on *outer*.
        """
        created = annot_page_rect(page, annot)
        inner = fitz.Rect(
            outer.x0 + (outer.x0 - created.x0),
            outer.y0 + (outer.y0 - created.y0),
            outer.x1 - (created.x1 - outer.x1),
            outer.y1 - (created.y1 - outer.y1),
        )
        if inner.is_empty or inner == created:
            return
        set_annot_page_rect(page, annot, inner)

    def _reattach_entry(
        self,
        page: fitz.Page,
        entry: dict,
        xref: int,
        dx: float,
        dy: float,
    ) -> bool:
        """Move a removed annotation's surviving object by ``(dx, dy)`` and relist it.

        Move first, then list it: a failure leaves the page as the redaction
        left it, never a half-restored annotation.  Returns whether the object
        is back on ``/Annots`` (the caller then does not re-create it).
        """
        name = entry["type_name"]
        try:
            if page.parent.xref_get_key(xref, "Subtype") != ("name", f"/{name}"):
                logger.warning("_restore_annots: xref %s 已不是 %s 物件，無法還原", xref, name)
                return False
            if dx or dy:
                self._translate_annot(page, xref, dx, dy)
            if not self._reattach_annot(page, xref, name):
                return False
        except Exception as exc:
            logger.warning("_restore_annots: 還原 %s xref %s 失敗: %s", name, xref, exc)
            return False
        logger.debug("_restore_annots: 已還原 %s xref %s (%s, %s)", name, xref, dx, dy)
        return True

    @staticmethod
    def _copy_annot_info(annot: fitz.Annot, info: dict) -> None:
        fields = {
            key: info[key]
            for key in ("content", "title", "subject", "creationDate", "modDate")
            if info.get(key)
        }
        if fields:
            annot.set_info(**fields)

    def _drop_partial_annots(self, page: fitz.Page, before: set[tuple[int, int]] | None) -> None:
        """Delete annotations a failed re-create inserted before raising.

        Without a ``before`` census nothing is deleted: an empty baseline would
        make every annotation on the page look new.
        """
        if before is None:
            logger.warning("_restore_annots: 無法取得還原前的 annot 清單，不清理殘留")
            return
        after = self._page_annot_identities(page)
        if after is None:
            return
        for xref, _type_code in after - before:
            try:
                page.delete_annot(page.load_annot(xref))
                logger.warning("_restore_annots: 刪除失敗還原留下的 annot xref %s", xref)
            except Exception as exc:
                logger.warning("_restore_annots: 無法刪除殘留 annot xref %s: %s", xref, exc)
