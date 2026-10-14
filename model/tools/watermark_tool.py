from __future__ import annotations

import json
import logging
import math
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

import fitz

from model.text_normalization import strip_unrenderable_controls

from .base import ToolExtension
from .watermark_rendering import (
    apply_watermarks_to_document,
    apply_watermarks_to_page,
    strip_marked_watermarks,
)

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

_WM_TEXT_MAX = 5_000
_WM_PAGES_MAX = 10_000


def _finite(v: float, lo: float, hi: float, default: float) -> float:
    """Clamp *v* to [lo, hi]; NaN (unorderable by min/max) falls back to *default*.

    Python's ``min``/``max`` are argument-order sensitive with NaN
    (``min(nan, x) -> nan`` but ``min(x, nan) -> x``), so NaN must be screened
    out explicitly. ±inf compares normally and clamps to the nearest bound.
    """
    if math.isnan(v):
        return default
    return max(lo, min(hi, v))


def _coerce_wm(wm: dict) -> dict | None:
    """Validate and clamp a watermark dict from any untrusted/unchecked source.

    This is the single sanitization chokepoint: embedded-JSON load,
    ``add_watermark`` and ``update_watermark`` all funnel through it. Returns a
    sanitized dict matching the stored watermark schema, or ``None`` if the
    entry is structurally invalid (missing or wrong-typed ``id``/``pages``, or
    a page or numeric field that does not parse as a number).
    Numeric fields are NaN/inf-safe and clamped to finite ranges, text length is
    capped, and ``color`` is always present as an exact-3 finite tuple in
    [0, 1] so a crafted blob cannot drive degenerate or oversized rendering
    (CWE-20). It is JSON, not pickle, so there is no code-execution risk — this
    is robustness hardening only.
    """
    try:
        raw_angle = float(wm.get("angle", 0))
        color = tuple(float(c) for c in wm.get("color", (0.7, 0.7, 0.7)))
        if len(color) != 3:
            color = (0.7, 0.7, 0.7)
        result: dict = {
            "id": str(wm["id"]),
            "pages": [int(p) for p in wm["pages"]][:_WM_PAGES_MAX],
            # F16-PASTE-1: a pasted NUL/VT is lost or drawn as a replacement glyph.
            "text": strip_unrenderable_controls(str(wm.get("text", "")))[:_WM_TEXT_MAX],
            "font": str(wm.get("font", "helv")),
            "angle": (raw_angle % 360) if math.isfinite(raw_angle) else 0.0,
            "font_size": _finite(float(wm.get("font_size", 48)), 1.0, 1000.0, 48.0),
            "opacity": _finite(float(wm.get("opacity", 0.5)), 0.0, 1.0, 0.5),
            "color": tuple(_finite(c, 0.0, 1.0, 0.7) for c in color),
        }
        for key in ("offset_x", "offset_y"):
            if key in wm:
                result[key] = _finite(float(wm[key]), -10000.0, 10000.0, 0.0)
        if "line_spacing" in wm:
            result["line_spacing"] = _finite(float(wm["line_spacing"]), 0.8, 3.0, 1.3)
        return result
    except (KeyError, TypeError, ValueError):
        return None


class WatermarkTool(ToolExtension):
    WATERMARK_EMBED_NAME = "__pdf_editor_watermarks"

    def __init__(self, model: PDFModel) -> None:
        self._model = model
        self._watermarks_by_session: dict[str, list[dict]] = {}
        self._modified_sessions: set[str] = set()
        # Page identity (F17-COH-3).  A watermark is chosen for PAGES, but the dialog and
        # the file store page NUMBERS, and a structural op renumbers.  Each live page gets an
        # id that survives delete / move / insert (``_page_ids_by_session``, one per page, in
        # page order); a watermark remembers the ids of its pages (``_covered_by_session``) and
        # its stored ``pages`` list is derived from them whenever the page list changes.  Ids
        # are never reused, and the id tuple rides in the document snapshots, so undo / redo
        # bring the exact lists back even for a watermark added after the op.
        self._page_ids_by_session: dict[str, tuple[int, ...]] = {}
        self._next_page_id_by_session: dict[str, int] = {}
        self._covered_by_session: dict[str, dict[str, frozenset[int]]] = {}

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        watermarks = self._load_watermarks_from_doc(doc)
        self._watermarks_by_session[session_id] = watermarks
        self._seed_page_identity(session_id, len(doc), watermarks)
        self._modified_sessions.discard(session_id)
        if watermarks:
            self._take_back_saved_copies(doc, watermarks)

    @staticmethod
    def _take_back_saved_copies(doc: fitz.Document, watermarks: list[dict]) -> None:
        """Remove the ink an earlier save baked for ``watermarks`` (F17-COH-2).

        The save bakes the list into the file AND stores it; restored, the list
        is drawn again by the live overlay, the print stamp and the next save.
        The live document must therefore hold the page content only -- the
        same unbaked state a session keeps after its own Ctrl+S (M9-2) -- or
        every reopen adds one copy.  Runs at open, before any undo history or
        fidelity protection exists; the file on disk is not touched and the
        session is not dirty (saving draws the list back exactly once).
        Unmarked ink of older builds stays (owner-accepted, F15-G5-GEOM).
        """
        try:
            strip_marked_watermarks(doc, watermarks)
        except Exception as exc:
            # Fail open to the old look (two copies), never to a lost watermark:
            # the overlay still draws, and a half-stripped page only loses ink
            # the list redraws.
            logger.warning("移除已儲存的浮水印副本失敗，畫面可能重複顯示浮水印: %s", exc)

    def on_session_close(self, session_id: str) -> None:
        self._watermarks_by_session.pop(session_id, None)
        self._page_ids_by_session.pop(session_id, None)
        self._next_page_id_by_session.pop(session_id, None)
        self._covered_by_session.pop(session_id, None)
        self._modified_sessions.discard(session_id)

    def on_session_saved(self, session_id: str) -> None:
        self._modified_sessions.discard(session_id)

    def has_unsaved_changes(self, session_id: str) -> bool:
        return session_id in self._modified_sessions

    def needs_page_overlay(self, session_id: str, page_num: int, purpose: str) -> bool:
        if purpose == "print":
            return False
        return bool(self._get_watermarks_for_page(session_id, page_num))

    def apply_page_overlay(self, session_id: str, page_num: int, page: fitz.Page, purpose: str) -> None:
        _ = purpose
        watermarks = self._get_watermarks_for_page(session_id, page_num)
        self._apply_watermarks_to_page(page, watermarks)

    def prepare_doc_for_save(self, session_id: str, doc: fitz.Document) -> fitz.Document | None:
        self._reconcile(session_id)
        watermarks = self.persistable_watermarks(session_id)
        if not watermarks:
            # Nothing to persist. Only rewrite (clear) the attachment when the
            # document already carries one, so stale watermark data cannot
            # reload; otherwise leave the live doc untouched — embfile_add
            # would rewrite the Catalog (/Names, /PageMode) and append objects.
            if self._has_watermark_embed(doc):
                self._write_watermarks_embed(doc, [])
            return None

        # ``fitz.open(); insert_pdf(doc)`` creates an unencrypted container, so
        # a later save(encryption=KEEP) would faithfully keep *no* encryption.
        # Clone through KEEP instead, preserving the original encryption
        # dictionary and permissions while still avoiding live-doc mutation.
        # In memory (H10-2 Part B: native sink, not ``tobytes``): ``doc`` may itself be
        # a decrypted working copy (the optimizer hands those in).
        tmp_doc = fitz.open(
            "pdf",
            self._model.serialize_document_bytes(
                doc, garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_KEEP, in_memory=True
            ),
        )
        if tmp_doc.needs_pass:
            password = self._model.password
            if password is None or tmp_doc.authenticate(password) == 0:
                tmp_doc.close()
                raise RuntimeError("Unable to authenticate encrypted watermark save clone")
        self._bake(tmp_doc, watermarks)
        return tmp_doc

    def _bake(self, doc: fitz.Document, watermarks: list[dict]) -> None:
        """Draw ``watermarks`` into ``doc`` and store their parameters (what Save writes).

        The one bake behind every PDF this app writes: the save clone and the PDFs built
        from the session's pages (``prepare_derived_document``, F17-COH-4).
        """
        self.apply_watermarks_to_document(doc, watermarks)
        self._write_watermarks_embed(doc, watermarks)

    def prepare_derived_document(
        self, session_id: str, doc: fitz.Document, origins: Sequence[int | None]
    ) -> None:
        """Bake the session's watermarks into a PDF built from its pages (F17-COH-4).

        Export of some pages and merge into a new file used the unbaked live document and
        dropped the watermark that view, print, image export and Save all show.  ``origins[j]``
        is the session page that output page ``j + 1`` was copied from (``None``: a page from
        elsewhere), so each watermark lands on the copies of its own pages and the stored
        list uses the OUTPUT's numbering.  An output that holds none of a watermark's pages
        gets neither the ink nor the attachment.
        """
        self._reconcile(session_id)
        derived: list[dict] = []
        for wm in self.persistable_watermarks(session_id):
            wanted = set(wm["pages"])
            pages = [index + 1 for index, origin in enumerate(origins) if origin in wanted]
            if pages:
                derived.append({**wm, "pages": pages})
        if derived:
            self._bake(doc, derived)

    # -- page identity (F17-COH-3) ----------------------------------------------
    def _seed_page_identity(self, session_id: str, count: int, watermarks: list[dict]) -> None:
        """Start (or restart) identity tracking: page ``n`` is id ``n - 1``."""
        self._page_ids_by_session[session_id] = tuple(range(count))
        self._next_page_id_by_session[session_id] = count
        covered: dict[str, frozenset[int]] = {}
        for wm in watermarks:
            wm_id = wm.get("id")
            if not wm_id:
                continue
            pages = frozenset(p - 1 for p in wm.get("pages", []) if 1 <= p <= count)
            covered[wm_id] = covered.get(wm_id, frozenset()) | pages
        self._covered_by_session[session_id] = covered

    def _page_count_of(self, session_id: str) -> int | None:
        """Page count of the session's live document, when it can be told (active session)."""
        model = self._model
        try:
            if model is None or session_id != model.get_active_session_id():
                return None
            doc = model.doc
        except AttributeError:
            return None
        return None if doc is None else len(doc)

    def _reconcile(self, session_id: str, count: int | None = None) -> None:
        """Fall back to the page NUMBERS when the page list changed behind our back.

        Safety net behind the structural chokepoint (``PDFModel._pages_restructured``,
        guarded by a source scan): if the stored id list does not fit the document, an op
        skipped the hook.  Identity is gone then; keep the numbers that still name a page
        (the pre-F17-COH-3 behaviour) instead of crashing or drawing past the end.
        """
        ids = self._page_ids_by_session.get(session_id)
        if count is None:
            count = self._page_count_of(session_id)
        if count is None or (ids is not None and len(ids) == count):
            return
        if ids is not None:
            logger.error(
                "page structure of session %s changed without notifying the tools "
                "(%d -> %d pages); watermark pages fall back to their numbers",
                session_id,
                len(ids),
                count,
            )
        entries = self._watermarks_by_session.get(session_id)
        if entries is not None:
            entries[:] = [wm for wm in entries if not self._is_hidden(session_id, wm)]
            for wm in entries:
                wm["pages"] = [p for p in wm.get("pages", []) if 1 <= p <= count]
        self._seed_page_identity(session_id, count, entries or [])

    def _is_hidden(self, session_id: str, wm: dict) -> bool:
        """True for a watermark whose pages are all gone (deleted, or not in a merge).

        It is kept, invisible and not saved, so undoing the op that removed the pages
        brings the very same entry back.  An entry that never had a page is not hidden.
        """
        if wm.get("pages"):
            return False
        return bool(self._covered_by_session.get(session_id, {}).get(str(wm.get("id"))))

    def persistable_watermarks(self, session_id: str) -> list[dict]:
        """The watermarks of the session that are not hidden (``_is_hidden``): shown, drawn, saved.

        An entry that never covered a page is not hidden, so it is kept too.
        """
        return [
            wm
            for wm in self._watermarks_by_session.get(session_id, [])
            if not self._is_hidden(session_id, wm)
        ]

    def _cover(self, session_id: str, wm: dict) -> None:
        """Remember which pages ``wm`` was chosen for (by id, from its page numbers)."""
        ids = self._page_ids_by_session.get(session_id)
        wm_id = wm.get("id")
        if ids is None or not wm_id:
            return
        self._covered_by_session.setdefault(session_id, {})[wm_id] = frozenset(
            ids[p - 1] for p in wm.get("pages", []) if 1 <= p <= len(ids)
        )

    def _adopt_unknown_entries(self, session_id: str) -> None:
        """Give an entry written straight into the list (not via add_watermark) its pages' ids."""
        covered = self._covered_by_session.setdefault(session_id, {})
        for wm in self._watermarks_by_session.get(session_id, []):
            if wm.get("id") not in covered:
                self._cover(session_id, wm)

    def _materialize(self, session_id: str) -> None:
        """Re-derive every stored ``pages`` list from the ids the watermark covers."""
        ids = self._page_ids_by_session.get(session_id, ())
        covered = self._covered_by_session.get(session_id, {})
        for wm in self._watermarks_by_session.get(session_id, []):
            ids_of_wm = covered.get(str(wm.get("id")))
            if ids_of_wm is not None:
                wm["pages"] = [index + 1 for index, page_id in enumerate(ids) if page_id in ids_of_wm]

    def on_pages_restructured(self, session_id: str, origins: Sequence[int | None], old_count: int) -> None:
        # No ``_mark_modified`` here: dirtiness belongs to the structural command,
        # not to the watermark list.
        # ``_reconcile`` with an explicit count always (re)seeds identity, so both
        # id dicts hold the session from here on.
        self._reconcile(session_id, old_count)
        old_ids = self._page_ids_by_session[session_id]
        self._adopt_unknown_entries(session_id)
        next_id = self._next_page_id_by_session[session_id]
        new_ids: list[int] = []
        taken: set[int] = set()
        copies: dict[int, list[int]] = {}  # old id -> ids of its extra copies (a merge uses a page twice)
        for origin in origins:
            if origin is None or not 1 <= origin <= len(old_ids):
                new_ids.append(next_id)
                next_id += 1
                continue
            page_id = old_ids[origin - 1]
            if page_id in taken:
                copies.setdefault(page_id, []).append(next_id)
                new_ids.append(next_id)
                next_id += 1
            else:
                taken.add(page_id)
                new_ids.append(page_id)
        if copies:
            covered = self._covered_by_session.setdefault(session_id, {})
            for wm_id, page_ids in list(covered.items()):
                extra = frozenset(copy for page_id in page_ids for copy in copies.get(page_id, ()))
                if extra:
                    covered[wm_id] = page_ids | extra
        self._page_ids_by_session[session_id] = tuple(new_ids)
        self._next_page_id_by_session[session_id] = next_id
        self._materialize(session_id)

    def capture_page_state(self, session_id: str) -> object | None:
        self._reconcile(session_id)
        return self._page_ids_by_session.get(session_id)

    def restore_page_state(self, session_id: str, state: object | None) -> None:
        if not isinstance(state, tuple):
            return
        count = self._page_count_of(session_id)
        if count is not None and len(state) != count:
            logger.error(
                "stored page identity (%d pages) does not fit the restored document (%d pages); "
                "watermark pages fall back to their numbers",
                len(state),
                count,
            )
            self._reconcile(session_id, count)
            return
        self._adopt_unknown_entries(session_id)
        self._page_ids_by_session[session_id] = state
        self._next_page_id_by_session[session_id] = max(
            self._next_page_id_by_session.get(session_id, 0), max(state, default=-1) + 1
        )
        self._materialize(session_id)

    def _active_session_id(self) -> str:
        sid = self._model.get_active_session_id()
        if not sid:
            raise RuntimeError("沒有作用中的 session")
        return sid

    def _active_watermark_list(self) -> list[dict]:
        sid = self._active_session_id()
        return self._watermarks_by_session.setdefault(sid, [])

    def _mark_modified(self, session_id: str) -> None:
        self._modified_sessions.add(session_id)

    def add_watermark(
        self,
        pages: list[int],
        text: str,
        angle: float = 45,
        opacity: float = 0.4,
        font_size: int = 48,
        color: tuple[float, float, float] = (0.7, 0.7, 0.7),
        font: str = "helv",
        offset_x: float = 0,
        offset_y: float = 0,
        line_spacing: float = 1.3,
    ) -> str:
        text = strip_unrenderable_controls(text)
        if not self._model.doc or not text.strip():
            raise ValueError("無效的文件或浮水印文字")

        sid = self._active_session_id()
        wm_id = str(uuid.uuid4())
        candidate = {
            "id": wm_id,
            "pages": pages,
            "text": text.strip(),
            "angle": angle,
            "opacity": opacity,
            "font_size": font_size,
            "color": color,
            "font": font,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "line_spacing": line_spacing,
        }
        wm = _coerce_wm(candidate)
        if wm is None:
            raise ValueError("無效的浮水印參數（強制校驗失敗）")
        # Re-filter pages AFTER coercion so the stored list only holds valid ints.
        wm["pages"] = [p for p in wm["pages"] if 1 <= p <= len(self._model.doc)]
        self._reconcile(sid)
        self._active_watermark_list().append(wm)
        self._cover(sid, wm)
        self._mark_modified(sid)
        logger.debug("新增浮水印: %s, 頁面 %s", wm_id, wm["pages"])
        return wm_id

    def get_watermarks(self) -> list[dict]:
        sid = self._model.get_active_session_id()
        if not sid:
            return []
        self._reconcile(sid)
        return self.persistable_watermarks(sid)

    def remove_watermark(self, watermark_id: str) -> bool:
        sid = self._active_session_id()
        watermarks = self._active_watermark_list()
        for i, wm in enumerate(watermarks):
            if wm.get("id") == watermark_id and not self._is_hidden(sid, wm):
                watermarks.pop(i)
                self._covered_by_session.get(sid, {}).pop(watermark_id, None)
                self._mark_modified(sid)
                logger.debug("已移除浮水印: %s", watermark_id)
                return True
        return False

    def update_watermark(
        self,
        watermark_id: str,
        text: str | None = None,
        pages: list[int] | None = None,
        angle: float | None = None,
        opacity: float | None = None,
        font_size: int | None = None,
        color: tuple[float, float, float] | None = None,
        font: str | None = None,
        offset_x: float | None = None,
        offset_y: float | None = None,
        line_spacing: float | None = None,
    ) -> bool:
        sid = self._active_session_id()
        watermarks = self._active_watermark_list()
        for index, wm in enumerate(watermarks):
            if wm.get("id") != watermark_id or self._is_hidden(sid, wm):
                continue
            candidate = dict(wm)
            overrides = {
                "text": text.strip() if text is not None else None,
                "pages": pages,
                "angle": angle,
                "opacity": opacity,
                "font_size": font_size,
                "color": color,
                "font": font,
                "offset_x": offset_x,
                "offset_y": offset_y,
                "line_spacing": line_spacing,
            }
            candidate.update({key: value for key, value in overrides.items() if value is not None})
            coerced = _coerce_wm(candidate)
            if coerced is None:
                return False
            page_count = len(self._model.doc) if self._model.doc else 0
            coerced["pages"] = [p for p in coerced["pages"] if 1 <= p <= page_count]
            watermarks[index] = coerced
            if pages is not None:
                self._reconcile(sid)
                self._cover(sid, coerced)
            self._mark_modified(sid)
            logger.debug("已更新浮水印: %s", watermark_id)
            return True
        return False

    def _load_watermarks_from_doc(self, doc: fitz.Document) -> list[dict]:
        loaded: list[dict] = []
        try:
            names = doc.embfile_names()
            if not names or self.WATERMARK_EMBED_NAME not in names:
                return loaded
            raw = doc.embfile_get(self.WATERMARK_EMBED_NAME)
            if not raw:
                return loaded
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                return loaded
            for wm in data:
                if not isinstance(wm, dict):
                    continue
                coerced = _coerce_wm(wm)
                if coerced is not None:
                    loaded.append(coerced)
            logger.debug("已從 PDF 還原 %s 個浮水印", len(loaded))
        except Exception as exc:
            logger.warning("還原浮水印元數據失敗: %s", exc)
        return loaded

    def _has_watermark_embed(self, doc: fitz.Document) -> bool:
        """Whether *doc* carries the watermark attachment; unreadable counts as yes.

        Fail-closed: if the names tree cannot be read, report True so the caller
        takes the clear-and-rewrite path instead of possibly keeping stale data.
        """
        try:
            names = doc.embfile_names()
        except Exception as exc:
            logger.debug("讀取附件清單失敗，視為存在浮水印附件: %s", exc)
            return True
        return bool(names) and self.WATERMARK_EMBED_NAME in names

    def _write_watermarks_embed(self, doc: fitz.Document, watermarks: list[dict]) -> None:
        payload = json.dumps(watermarks, ensure_ascii=False).encode("utf-8")
        try:
            names = doc.embfile_names()
            if names and self.WATERMARK_EMBED_NAME in names:
                doc.embfile_del(self.WATERMARK_EMBED_NAME)
        except Exception as exc:
            logger.debug("刪除舊浮水印附件時忽略: %s", exc)

        try:
            doc.embfile_add(self.WATERMARK_EMBED_NAME, payload)
            logger.debug("已寫入浮水印元數據（%s 筆）", len(watermarks))
        except Exception as exc:
            logger.warning("寫入浮水印元數據失敗: %s", exc)

    def _get_watermarks_for_page(self, session_id: str, page_num: int) -> list[dict]:
        watermarks = self._watermarks_by_session.get(session_id, [])
        return [wm for wm in watermarks if page_num in wm.get("pages", [])]

    @classmethod
    def _apply_watermarks_to_page(cls, page: fitz.Page, watermarks: list[dict]) -> None:
        apply_watermarks_to_page(page, watermarks)

    @classmethod
    def apply_watermarks_to_document(cls, doc: fitz.Document, watermarks: list[dict]) -> None:
        apply_watermarks_to_document(doc, watermarks)
