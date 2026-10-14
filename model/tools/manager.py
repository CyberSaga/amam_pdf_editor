from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

from model.text_commit.inspect import StreamStorage, restore_stream_storage

from .annotation_tool import AnnotationTool
from .base import ToolExtension
from .ocr_tool import OcrTool
from .search_tool import SearchTool
from .watermark_tool import WatermarkTool

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


class ProtectedPageViolation(RuntimeError):
    """A save hook changed the content of a fidelity-protected page."""


_LENGTH_RE = re.compile(r"/Length\s+\d+(?:\s+\d+\s+R)?")
_INDIRECT_RE = re.compile(r"\b\d+\s+\d+\s+R\b")


def _storage_key(doc: fitz.Document, xref: int) -> tuple[bytes, str, str | None]:
    """``(raw bytes, object text, comparable dictionary)`` of a stream.

    The comparable dictionary is the object text without ``/Length`` (a save
    may rewrite it, even from an indirect to a direct number); it is ``None``
    when the dictionary still holds an indirect reference, whose target the text
    cannot vouch for, so such a stream never takes the raw fast path."""
    obj = doc.xref_object(xref)
    stripped = _LENGTH_RE.sub("", obj)
    return doc.xref_stream_raw(xref), obj, None if _INDIRECT_RE.search(stripped) else stripped


class _StreamRecord:
    """One protected content stream as it was before the hooks ran.

    The snapshot is CHEAP: raw bytes plus the dictionary.  The decoded content
    (what the contract is actually about) is produced only when a later check
    finds the storage changed, so an untouched page is never decoded -- the old
    guard decoded every protected stream before the hooks and again after each
    of them (about 90 ms per protected page on the hvac drawing).  A stream whose
    dictionary holds an indirect reference cannot be re-decoded in isolation, so
    that (rare) kind is decoded up front."""

    __slots__ = ("_decoded", "key", "obj", "raw", "xref")

    def __init__(self, doc: fitz.Document, xref: int) -> None:
        self.xref = xref
        self.raw, self.obj, self.key = _storage_key(doc, xref)
        self._decoded: bytes | None = (doc.xref_stream(xref) or b"") if self.key is None else None

    def decoded(self) -> bytes | None:
        """The original decoded content; ``None`` when it cannot be recovered
        (callers then fail closed)."""
        if self._decoded is None and self.key is not None:
            scratch = fitz.open()
            try:
                xref = scratch.get_new_xref()
                scratch.update_object(xref, "<<>>")
                scratch.update_stream(xref, self.raw, compress=False)
                scratch.update_object(xref, self.key)
                self._decoded = scratch.xref_stream(xref) or b""
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                logger.warning("could not re-decode protected stream %s", self.xref)
                return None
            finally:
                scratch.close()
        return self._decoded

    def storage(self) -> StreamStorage | None:
        decoded = self.decoded()
        if decoded is None:
            return None
        return StreamStorage(xref=self.xref, raw=self.raw, obj=self.obj, decoded=decoded)

    def matches(self, doc: fitz.Document, xref: int) -> bool:
        """``xref`` of ``doc`` still holds this stream's content."""
        raw, _obj, key = _storage_key(doc, xref)
        if key is not None and self.key is not None and raw == self.raw and key == self.key:
            return True  # identical storage, therefore identical content
        original = self.decoded()
        return original is not None and (doc.xref_stream(xref) or b"") == original


class _ProtectedPageGuard:
    """Save-time contract for fidelity-protected pages (part 5, Stage C).

    A page a Tier 0/1 commit landed on is verified byte-for-byte; a save hook
    must never rewrite its content streams (``clean_contents`` would destroy
    the proof).  The guard snapshots those pages before the hooks run, then
    checks (a) the document a hook was handed -- exactly, rolling a rewrite
    back -- and (b) the clone it returned -- every original stream must
    survive verbatim, in order (appending an overlay such as a watermark is
    fine).  "Verbatim" is about decoded CONTENT; see :class:`_StreamRecord` for
    how an unchanged stream is proven without decoding it.
    """

    def __init__(self, doc: fitz.Document, pages: list[int]) -> None:
        self._pages = pages
        self._streams: dict[int, list[_StreamRecord]] = {}
        self._contents_key: dict[int, tuple[str, str]] = {}
        for page_idx in pages:
            page = doc[page_idx]
            self._streams[page_idx] = [_StreamRecord(doc, x) for x in page.get_contents()]
            self._contents_key[page_idx] = doc.xref_get_key(page.xref, "Contents")

    def _page_unchanged(self, doc: fitz.Document, page_idx: int) -> bool:
        records = self._streams[page_idx]
        xrefs = list(doc[page_idx].get_contents())
        if xrefs != [record.xref for record in records]:
            return False
        return all(record.matches(doc, record.xref) for record in records)

    def violations_in_place(self, doc: fitz.Document) -> list[int]:
        """Pages of ``doc`` (the document the hook was handed) that differ."""
        return [page_idx for page_idx in self._pages if not self._page_unchanged(doc, page_idx)]

    def violations_in_clone(self, clone: fitz.Document) -> list[int]:
        """Pages of a hook's returned clone that lost an original stream."""
        bad: list[int] = []
        for page_idx in self._pages:
            if page_idx >= len(clone):
                bad.append(page_idx)
                continue
            produced = iter(clone[page_idx].get_contents())
            if not all(
                any(record.matches(clone, candidate) for candidate in produced)
                for record in self._streams[page_idx]
            ):
                bad.append(page_idx)
        return bad

    @staticmethod
    def _restore_record(doc: fitz.Document, record: _StreamRecord) -> None:
        storage = record.storage()
        if storage is not None:
            restore_stream_storage(doc, storage)
            return
        # The original content could not be re-decoded: put the exact storage
        # back without the decoded self-check (never a lossy decoded rewrite).
        doc.update_stream(record.xref, record.raw, compress=False)
        doc.update_object(record.xref, record.obj)

    def roll_back(self, doc: fitz.Document, pages: list[int]) -> bool:
        """Restore ``pages`` of the live document; True when they match again."""
        for page_idx in pages:
            try:
                page = doc[page_idx]
                for record in self._streams[page_idx]:
                    self._restore_record(doc, record)
                kind, value = self._contents_key[page_idx]
                if kind != "null":
                    doc.xref_set_key(page.xref, "Contents", value)
            except (RuntimeError, ValueError, IndexError, fitz.mupdf.FzErrorBase):
                logger.exception("rolling back protected page %s failed", page_idx + 1)
        return not self.violations_in_place(doc)


class ToolManager:
    def __init__(self, model: PDFModel) -> None:
        self._model = model

        self.annotation = AnnotationTool(model)
        self.watermark = WatermarkTool(model)
        self.search = SearchTool(model)
        self.ocr = OcrTool(model)

        self._extensions = [
            self.annotation,
            self.watermark,
            self.search,
            self.ocr,
        ]

    def on_session_open(self, session_id: str, doc: fitz.Document) -> None:
        for ext in self._extensions:
            ext.on_session_open(session_id, doc)

    def on_session_close(self, session_id: str) -> None:
        for ext in self._extensions:
            ext.on_session_close(session_id)

    def on_session_saved(self, session_id: str) -> None:
        for ext in self._extensions:
            ext.on_session_saved(session_id)

    def has_unsaved_changes(self, session_id: str) -> bool:
        return any(ext.has_unsaved_changes(session_id) for ext in self._extensions)

    def on_pages_restructured(self, session_id: str, origins: Sequence[int | None], old_count: int) -> None:
        """Tell every tool that the session's page list changed (see ``ToolExtension``)."""
        for ext in self._extensions:
            ext.on_pages_restructured(session_id, origins, old_count)

    def capture_page_state(self, session_id: str) -> dict[str, object]:
        """The page-bound state of every tool that has some, keyed by tool class name."""
        states: dict[str, object] = {}
        for ext in self._extensions:
            state = ext.capture_page_state(session_id)
            if state is not None:
                states[type(ext).__name__] = state
        return states

    def restore_page_state(self, session_id: str, states: Mapping[str, object]) -> None:
        for ext in self._extensions:
            ext.restore_page_state(session_id, states.get(type(ext).__name__))

    def prepare_derived_document(
        self, session_id: str, doc: fitz.Document, origins: Sequence[int | None]
    ) -> None:
        """Run every tool's persisted effect over a PDF built from the session's pages."""
        for ext in self._extensions:
            ext.prepare_derived_document(session_id, doc, origins)

    def _active_session_id(self) -> str:
        sid = self._model.get_active_session_id()
        if not sid:
            raise RuntimeError("沒有作用中的 session")
        return sid

    def render_page_pixmap(
        self,
        page_num: int,
        scale: float = 1.0,
        annots: bool = False,
        purpose: str = "view",
        colorspace: fitz.Colorspace | None = None,
    ) -> fitz.Pixmap:
        if not self._model.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        if page_num < 1 or page_num > len(self._model.doc):
            raise ValueError(f"page_num={page_num} out of range [1, {len(self._model.doc)}]")

        session_id = self._active_session_id()
        page = self._model.doc[page_num - 1]
        needs_overlay = any(ext.needs_page_overlay(session_id, page_num, purpose) for ext in self._extensions)
        # Local import avoids a module-load cycle between pdf_model and the tools package.
        from model.pdf_model import _safe_render_scale  # noqa: PLC0415

        # Central chokepoint clamp: every raster path flows through here, so an
        # outsized MediaBox cannot OOM the process regardless of the caller.
        # Clamping on the original page is correct for the overlay branch too
        # (the tmp page copies the same rect).
        scale = _safe_render_scale(page, scale)
        matrix = fitz.Matrix(scale, scale)

        if not needs_overlay:
            if colorspace is None:
                return page.get_pixmap(matrix=matrix, annots=annots)
            return page.get_pixmap(matrix=matrix, annots=annots, colorspace=colorspace)

        tmp_doc = fitz.open()
        try:
            tmp_doc.insert_pdf(self._model.doc, from_page=page_num - 1, to_page=page_num - 1)
            tmp_page = tmp_doc[0]
            for ext in self._extensions:
                if ext.needs_page_overlay(session_id, page_num, purpose):
                    ext.apply_page_overlay(session_id, page_num, tmp_page, purpose)
            if colorspace is None:
                return tmp_page.get_pixmap(matrix=matrix, annots=annots)
            return tmp_page.get_pixmap(matrix=matrix, annots=annots, colorspace=colorspace)
        finally:
            tmp_doc.close()

    def build_print_snapshot(self, dest: Path) -> None:
        """Write the print-input snapshot to ``dest`` (no in-memory copy unless a secure prune needs a clone)."""
        if not self._model.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")

        session_id = self._active_session_id()
        page_count = len(self._model.doc)
        has_overlay = any(
            ext.needs_page_overlay(session_id, page_num + 1, "print")
            for ext in self._extensions
            for page_num in range(page_count)
        )
        if not has_overlay:
            # encryption=KEEP mirrors PDFModel._save_doc: save() defaults to
            # NONE(1), which would silently decrypt protected documents.  The
            # garbage=4 prune of a secure session runs on a clone inside
            # ``write_pruned_live_copy``: on the LIVE doc it would renumber it
            # in place and strand page-snapshot undo and listed xrefs (DS-1).
            garbage = 4 if self._model.secure_save_required else 0
            self._model.write_pruned_live_copy(dest, garbage=garbage)
            return

        tmp_doc = fitz.open()
        try:
            tmp_doc.insert_pdf(self._model.doc)
            for page_idx in range(page_count):
                page_num = page_idx + 1
                for ext in self._extensions:
                    if ext.needs_page_overlay(session_id, page_num, "print"):
                        ext.apply_page_overlay(session_id, page_num, tmp_doc[page_idx], "print")
            tmp_doc.save(str(dest), garbage=4 if self._model.secure_save_required else 0)
        finally:
            tmp_doc.close()

    def prepare_doc_for_save(self, session_id: str, doc: fitz.Document | None = None) -> fitz.Document | None:
        doc = doc if doc is not None else self._model.doc
        if doc is None:
            return None

        guard = self._protected_page_guard(session_id, doc)
        current = doc
        produced: fitz.Document | None = None
        for ext in self._extensions:
            try:
                next_doc = ext.prepare_doc_for_save(session_id, current)
            except BaseException:
                self._abandon(produced, guard, doc)
                raise
            if guard is not None and not self._cannot_have_rewritten(ext, next_doc):
                try:
                    self._check_hook(ext, guard, doc, current, next_doc, produced)
                except ProtectedPageViolation:
                    raise  # _check_hook already rolled back and closed
                except BaseException:
                    # Round-3 N7: a read error inside the check itself must not
                    # leave the hook's in-place rewrite or its clones behind.
                    self._abandon(produced, guard, doc, next_doc)
                    raise
            if next_doc is None:
                continue
            if produced is not None and produced is not next_doc:
                try:
                    produced.close()
                except Exception:
                    pass
            produced = next_doc
            current = next_doc
        return produced

    @staticmethod
    def _cannot_have_rewritten(ext: object, returned: fitz.Document | None) -> bool:
        """An extension that does not override ``prepare_doc_for_save`` runs the
        base-class no-op: it returned nothing and touched nothing, so comparing
        every protected stream again after it is wasted work."""
        return (
            returned is None
            and getattr(type(ext), "prepare_doc_for_save", None)
            is ToolExtension.prepare_doc_for_save
        )

    def _protected_page_guard(
        self, session_id: str, doc: fitz.Document
    ) -> _ProtectedPageGuard | None:
        session = getattr(self._model, "_sessions_by_id", {}).get(session_id)
        protected = (
            session.fidelity_protected_pages
            if session is not None
            else self._model.fidelity_protected_pages
        )
        pages = sorted(p for p in protected if isinstance(p, int) and 0 <= p < len(doc))
        return _ProtectedPageGuard(doc, pages) if pages else None

    def _abandon(
        self,
        produced: fitz.Document | None,
        guard: _ProtectedPageGuard | None,
        doc: fitz.Document,
        *also_close: fitz.Document | None,
    ) -> None:
        for leftover in {
            id(d): d for d in (produced, *also_close) if d is not None and d is not doc
        }.values():
            try:
                leftover.close()
            except Exception:
                pass
        restored = False
        if guard is not None:
            try:
                restored = guard.roll_back(doc, guard.violations_in_place(doc))
            except Exception:  # the in-flight exception must keep propagating
                logger.exception("rolling back fidelity-protected pages raised")
        if guard is not None and not restored:
            # The hook's own exception is what propagates; the failed restore
            # must at least leave a trace -- and the session must not be saved
            # in place afterwards (S13-DLG5-DAMAGED).
            logger.error(
                "rollback of fidelity-protected pages failed after a save hook raised; "
                "the live document may differ from the verified content"
            )
            self._model.mark_session_damaged("protected-page rollback failed after a save hook raised")

    def _check_hook(
        self,
        ext: object,
        guard: _ProtectedPageGuard,
        doc: fitz.Document,
        handed: fitz.Document,
        returned: fitz.Document | None,
        produced: fitz.Document | None,
    ) -> None:
        """Fail closed when ``ext`` rewrote a protected page (see the guard)."""
        in_place: list[int] = []
        clone_bad: list[int] = []
        if handed is doc:
            in_place = guard.violations_in_place(doc)
        else:  # an earlier hook's clone, edited in place by this one
            clone_bad = guard.violations_in_clone(handed)
        if returned is not None and returned is not handed:
            clone_bad = sorted(set(clone_bad) | set(guard.violations_in_clone(returned)))
        if not in_place and not clone_bad:
            return
        pages = sorted(set(in_place) | set(clone_bad))
        rolled_back = guard.roll_back(doc, in_place) if in_place else True
        for leftover in {id(d): d for d in (returned, produced) if d is not None and d is not doc}.values():
            try:
                leftover.close()
            except Exception:
                pass
        page_list = "、".join(str(p + 1) for p in pages)
        logger.error(
            "%s rewrote fidelity-protected page(s) %s during save preparation "
            "(in place: %s, rollback ok: %s); the save was refused before anything was written",
            type(ext).__name__,
            page_list,
            bool(in_place),
            rolled_back,
        )
        if not rolled_back:
            self._model.mark_session_damaged("protected-page rollback failed after a save hook")
            raise ProtectedPageViolation(
                f"儲存已中止：{type(ext).__name__} 改寫了受保護的第 {page_list} 頁，"
                "且還原失敗，目前開啟的文件可能已與已驗證的內容不同；"
                "請勿覆寫原檔，建議另存新檔後再檢查該頁"
            )
        restored = "（已還原）" if in_place else ""
        raise ProtectedPageViolation(
            f"已拒絕儲存：{type(ext).__name__} 會改寫受保護的第 {page_list} 頁{restored}，"
            "尚未寫入任何檔案"
        )
