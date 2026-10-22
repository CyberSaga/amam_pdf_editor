from __future__ import annotations

import difflib  # 相似度比對
import gc
import hashlib
import html as _html_mod
import io  # 用於 BytesIO 記憶體 stream（文件推薦 in-memory PDF）
import itertools
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, BinaryIO, cast

import fitz

# Optimizer internals live in `model/pdf_optimizer.py`.
# `PDFModel` keeps the public facade stable and delegates to the internal module.
from model import doc_bytes, pdf_object_ops, pdf_optimizer, pdf_text_edit, save_compaction, signed_append_save
from model import outline_ops, page_refs, xref_compaction
from model.navigation_graft import NavigationGraft
from model.edit_commands import CommandManager, DocSnapshot, EditTextResult, MaintenanceBook
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ObjectHitInfo, RotateObjectRequest
from model.object_requests import ResizeObjectRequest
from model.object_op_refusal import ObjectOpRefused
from model.edit_requests import RebuildConsent, SourceShowRef, UnkeepableGlyph
from model.joined_edit_runs import (
    JoinedEditGroup,
    JoinedEditRun,
    prove_joined_group,
)
from model.page_content_text import content_text
from model.rtl_text import contains_rtl
from model.selection_text import clip_directions, order_run_glyphs, whitespace_between_runs, whitespace_chars
from model.page_snapshot import (
    PageSnapshot,
    PageSnapshotError,
    capture_page_graph,
    restore_page_graph,
)
from model.text_block import (
    EditableParagraph,
    EditableSpan,
    TextBlockManager,
    rotation_degrees_from_dir,
)
from model.geometry import (
    clamp_rect_to_page,
    rect_overlap_ratio,
    unrotated_page_rect,
    unrotated_to_visual_point,
    unrotated_to_visual_rect,
    visual_text_rotation,
    visual_to_unrotated_point,
    visual_to_unrotated_rect,
)
from model.text_commit.dto import CommitOutcome, CommitStatus, RejectReason, TextCommitSettings
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.transforms import insert_text_page_space
from model.text_commit.source_run import (
    SourceRunGroup,
    SourceRunResolver,
    group_anchor_first_member,
)
from model.text_commit.inspect import (
    document_has_a_signed_signature,
    page_has_widgets_or_signatures,
)
from model.text_normalization import normalize_text, normalized_similarity
from model.tools import ToolManager
from utils.pdf_object_source import exact_set_key, xref_set_key_exact

# [優化 1] 模組級正則預編譯：避免每次呼叫 _convert_text_to_html 時重新編譯，提升效能
_RE_HTML_TEXT_PARTS = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[^\u4e00-\u9fff\u3040-\u30ff\n ]+| +|\n)')
_RE_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff]+')
# D-HYPHEN-WRAP: MuPDF's line breaker breaks a word after U+002D / U+2010 (the
# decision: a wrap at the right-hand neighbour may do that, 'Two-' / 'Column') and
# never after U+2011.  Its one bad case is a hyphen that OPENS the word: it would
# leave a line of just '-', so that run of hyphens is glued to what follows.
_LEADING_HYPHENS = "-" + "\u2010"  # U+002D, U+2010
_NOWRAP_OPEN = '<span style="white-space: nowrap;">'


def _latin_word_html(part: str) -> str:
    """HTML-escaped ``part`` (one whitespace-free word of ``_RE_HTML_TEXT_PARTS``).

    A word that opens with hyphens followed by a non-digit gets those hyphens in a
    ``white-space: nowrap`` span, which MuPDF does not break after (a break there
    would strand a lone hyphen on the first line).  Every other word -- inner
    hyphens, ``-5`` (the line breaker already keeps a hyphen with a digit), a bullet
    ``-`` -- is exactly the escaped text, so its break behaviour is unchanged.
    """
    lead = len(part) - len(part.lstrip(_LEADING_HYPHENS))
    if 0 < lead < len(part) and not part[lead].isdigit():
        return f"{_NOWRAP_OPEN}{part[:lead]}</span>{_html_mod.escape(part[lead:])}"
    return _html_mod.escape(part)


_BULLET_PREFIXES = ("- ", "* ", "\u2022 ", "\u25aa ", "\u25cf ")
_RE_NUMBERED_BULLET = re.compile(r"^\d+[.)]\s+")

# Optional Windows CJK font files for visible family differences in insert_htmlbox.
_WINDOWS_CJK_FONT_FILES = {
    "microsoft jhenghei": Path(r"C:\Windows\Fonts\msjh.ttc"),
    "pmingliu": Path(r"C:\Windows\Fonts\mingliu.ttc"),
    "dfkai-sb": Path(r"C:\Windows\Fonts\kaiu.ttf"),
}

_CUSTOM_CJK_ALIASES = {
    "microsoft jhenghei": "PdfEditorMicrosoftJhengHei",
    "pmingliu": "PdfEditorPMingLiU",
    "dfkai-sb": "PdfEditorDFKaiSB",
}


# 設置日誌
logger = logging.getLogger(__name__)

# Set on a fitz.Document that appended an incremental revision and could not be
# replaced by a fresh handle (see ``PDFModel._renew_handle_after_incremental_save``).
_INCREMENTAL_SPENT_ATTR = "_amam_incremental_save_spent"


class SaveRecoveryError(RuntimeError):
    """A save over the open file failed AFTER the live handle was closed, and the
    session could not be rebound to any copy of its edits.

    The session's document is a closed handle.  ``recovery_path`` is a file that
    still holds the unsaved edits (kept on purpose: it is the only copy);
    ``target_written`` says whether the target already got the new content (the
    replace succeeded and only the reopen failed).
    """

    def __init__(self, message: str, *, recovery_path: Path, target_written: bool) -> None:
        super().__init__(message)
        self.recovery_path = recovery_path
        self.target_written = target_written


class DamagedSessionSaveError(RuntimeError):
    """A save back to the session's own file was refused because a failed edit
    could not be rolled back (S13-DLG5-DAMAGED, owner decision A + C).

    The live document may hold a half-rewritten page, so writing it over the
    file would destroy the only good copy.  Nothing was written.  Only a Save
    As to a different file is allowed; the message is plain zh-TW and says so.
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path


DAMAGED_SESSION_SAVE_MESSAGE = (
    "這個分頁的文件在先前的編輯失敗後無法完整還原，頁面可能已被部分改動，"
    "為避免蓋掉原本的檔案，本次儲存已取消（檔案未變更）。"
    "請改用「另存新檔」存成新的檔名，或關閉這個分頁（不儲存）後重新開啟原本的檔案。"
)

# Export / merge / optimize copy / recovery copy pointed at a file a damaged
# session protects (F14-DMG-1): the same refusal, worded for a write that is
# not a Save As.
DAMAGED_SESSION_WRITE_MESSAGE = (
    "這個分頁的文件在先前的編輯失敗後無法完整還原，頁面可能已被部分改動，"
    "為避免蓋掉原本的檔案，本次寫入已取消（檔案未變更）。"
    "請改選新的檔名，或關閉這個分頁（不儲存）後重新開啟原本的檔案。"
)


class SourceChangedOnDiskError(RuntimeError):
    """A save back to the session's own file was refused: another program
    rewrote or replaced that file after this session opened or last saved it
    (F10-FS-1).  Nothing was written; ``path`` is the file that changed."""

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path


# ``PDFModel._save_signed_by_appending`` outcome for a document with no signed
# signature: nothing to keep, the full rewrite may go ahead without asking.
SIGNED_APPEND_UNSIGNED = "unsigned"


class SignatureWouldBreakError(RuntimeError):
    """A save of a digitally signed document was refused before anything was
    written (``incremental_failed``: after a failed in-place append, whose
    partial revision is rolled back where possible): the append-only save that keeps the signed revision a byte prefix
    is not possible, and the full rewrite that remains would invalidate the
    signature (SIG-DIALOG).  The caller asks the user and repeats the save with
    ``allow_signature_loss=True`` only on consent.

    ``reason_code`` says why the append is not possible: one of
    ``signed_append_save.DECLINE_REASONS`` or a save-path code
    (``secure_latch``, ``incremental_disabled``, ``in_place_append_unavailable``,
    ``source_changed``, ``source_missing``, ``watermark_rewrite``,
    ``incremental_failed``); ``path`` is the save target."""

    def __init__(self, reason_code: str, path: str | Path) -> None:
        super().__init__(
            f"saving would invalidate the digital signature ({reason_code}): {path}"
        )
        self.reason_code = reason_code
        self.path = Path(path)


# Refusal codes raised after the save may already have written the session's own
# file (F12-SIG-1): ``save_as`` re-records the disk fingerprint for these, so the
# consented retry is not refused as another program's change.
_SIGNATURE_REFUSALS_AFTER_A_WRITE = frozenset({"incremental_failed"})


# Bytes hashed from each end of a file for its on-disk fingerprint: a PDF's
# trailer / startxref lives at the tail, its header and first objects at the head.
_FINGERPRINT_EDGE_BYTES = 4096


def _edge_digest_of_prefix(handle: BinaryIO, size: int) -> str:
    """SHA-256 of the first and last ``_FINGERPRINT_EDGE_BYTES`` of the first ``size`` bytes of ``handle``.

    ``handle`` is positioned at 0.  A file no longer than one edge is digested
    whole; the two windows of a longer one never overlap.  The ONE edge-digest
    function: ``_file_fingerprint`` (a file), ``_edge_digest_of_bytes`` (bytes
    in memory) and ``_roll_back_partial_append`` (a file prefix) all compare
    its results with each other.
    """
    digest = hashlib.sha256(handle.read(min(size, _FINGERPRINT_EDGE_BYTES)))
    if size > _FINGERPRINT_EDGE_BYTES:
        start = max(_FINGERPRINT_EDGE_BYTES, size - _FINGERPRINT_EDGE_BYTES)
        handle.seek(start)
        digest.update(handle.read(size - start))
    return digest.hexdigest()


def _file_fingerprint(path: str | Path) -> tuple[int, int, str] | None:
    """``(size, mtime_ns, digest of the first and last 4 KB)`` of ``path``, or ``None``.

    Size + mtime alone miss a same-length rewrite by a writer that keeps the
    source's modification time (Explorer / ``copy /y`` / ``Copy-Item``); the
    edge digest catches it without reading the whole file.  ``None`` when the
    file is missing or unreadable.
    """
    try:
        with open(path, "rb") as handle:
            stat = os.fstat(handle.fileno())
            digest = _edge_digest_of_prefix(handle, int(stat.st_size))
    except OSError:
        return None
    return (int(stat.st_size), int(stat.st_mtime_ns), digest)


def _edge_digest_of_bytes(data: bytes) -> str:
    """The third element of ``_file_fingerprint`` for a file whose bytes are ``data`` (F11-FS-1).

    Lets a caller that already holds the bytes (or only the leading part of them)
    compare them with a recorded fingerprint without a second read of the file.
    """
    return _edge_digest_of_prefix(io.BytesIO(data), len(data))


# Re-export optimizer schema types for backwards compatibility (tests/UI import from `model.pdf_model`).
PdfOptimizeOptions = pdf_optimizer.PdfOptimizeOptions
PdfAuditItem = pdf_optimizer.PdfAuditItem
PdfAuditReport = pdf_optimizer.PdfAuditReport
PdfOptimizationResult = pdf_optimizer.PdfOptimizationResult
OptimizeSourceSnapshot = pdf_optimizer.OptimizeSourceSnapshot
OptimizeOutputCredentials = pdf_optimizer.OptimizeOutputCredentials

# Resource guards for untrusted PDFs (CWE-400 uncontrolled resource consumption,
# CWE-409 decompression bomb). A crafted document with an enormous file size,
# page count, or page dimensions can otherwise OOM/hang the process during parse
# or render. These cap the worst case; they do not affect any realistic document.
_MAX_PDF_BYTES = 512 * 1024 * 1024  # 512 MB
_MAX_PAGES = 5_000
# MuPDF can report 0 pages for a file other readers parse fine (e.g. a /Prev loop).
_ZERO_PAGE_MESSAGE = "無法讀取來源檔案：MuPDF 讀到 0 頁（檔案結構可能損毀），已拒絕處理以免覆蓋或遺漏內容: {path}"
# _MAX_PIXMAP_PX is re-exported here for backward compatibility: external callers
# and tests reference ``model.pdf_model._MAX_PIXMAP_PX`` (see docs/PITFALLS.md).
# It is unused *within* this module, so F401 is suppressed deliberately — do NOT
# let ``ruff --fix`` strip it (that breaks test_security_pdf_resource_guards).
from utils.render_limits import (  # noqa: E402
    _MAX_PIXMAP_PX,  # noqa: F401
    safe_render_scale as _safe_render_scale,
    thumbnail_render_scale,
)
from utils.path_staging import (  # noqa: E402
    extended_length_path,
    on_disk_spelling,
    replace_file,
    resolve_as_requested,
    staging_sibling,
    strip_extended_prefix,
    write_via_staging,
)
from utils import file_share_lock  # noqa: E402


class PdfPasswordError(RuntimeError):
    """A PDF could not be unlocked.  The controller retries on this TYPE only.

    Model error messages embed the user's file path, so a message substring (e.g.
    ``"encrypted"`` in a folder named "Unencrypted Exports") can never decide whether to
    ask for a password (F11-OPEN-3).  Messages stay human-readable and unchanged.
    """


class PdfPasswordRequiredError(PdfPasswordError):
    """The document is locked and no password was supplied."""


class PdfPasswordRejectedError(PdfPasswordError):
    """A password was supplied but ``authenticate()`` refused it."""


def _guard_before_open(path: Path) -> None:
    """Reject an over-large file before handing its bytes to the native parser."""
    if path.stat().st_size > _MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds size limit ({_MAX_PDF_BYTES // 1_048_576} MB)")


def _guard_foreign_doc(path: Path, password: str | None = None) -> fitz.Document:
    """Open a foreign PDF with all resource guards applied.

    Size limit (_MAX_PDF_BYTES), open, optional authentication, page limit (_MAX_PAGES).
    Returns the opened document; caller closes it.
    """
    _guard_before_open(path)
    doc = fitz.open(str(path))
    try:
        if doc.needs_pass:
            if password is None:
                raise PdfPasswordRequiredError(f"document closed or encrypted — 需要密碼: {path}")
            if doc.authenticate(password) == 0:
                raise PdfPasswordRejectedError(f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}")
        if doc.page_count > _MAX_PAGES:
            raise ValueError(f"Foreign PDF exceeds page limit ({_MAX_PAGES} pages): {path}")
        if doc.page_count == 0:
            # A source MuPDF reads as 0 pages would otherwise be merged/inserted
            # as a silent no-op, dropping the file's content from the result.
            raise RuntimeError(_ZERO_PAGE_MESSAGE.format(path=path))
    except Exception:
        doc.close()
        raise
    return doc


def _install_rawdict_text_compat() -> None:
    """Backfill ``span['text']`` for fitz rawdict payloads that only expose chars.

    Some PyMuPDF builds (notably once a QApplication is live) omit the
    ``text`` key in rawdict spans and return only ``chars``. The no-jump E2E
    gate and several callers inspect span text straight from rawdict, so wrap
    ``fitz.Page.get_text`` once at import to reconstruct the missing key.
    """
    sentinel = "_pdf_editor_rawdict_text_compat"
    if getattr(fitz.Page, sentinel, False):
        return
    original_get_text = fitz.Page.get_text

    def _compat_get_text(page, option="text", *args, **kwargs):
        keyword_option = kwargs.get("option")
        if option == "text" and keyword_option is not None:
            effective_option = keyword_option
            result = original_get_text(page, *args, **kwargs)
        else:
            effective_option = option
            call_kwargs = dict(kwargs)
            call_kwargs.pop("option", None)
            result = original_get_text(page, option, *args, **call_kwargs)
        if effective_option != "rawdict" or not isinstance(result, dict):
            return result
        for block in result.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text") is None and isinstance(span.get("chars"), list):
                        span["text"] = "".join(ch.get("c", "") for ch in span["chars"])
        return result

    fitz.Page.get_text = _compat_get_text
    setattr(fitz.Page, sentinel, True)


_install_rawdict_text_compat()


@dataclass
class TextHit:
    target_span_id: str
    target_bbox: fitz.Rect
    target_text: str
    font: str
    size: float
    color: tuple
    rotation: int
    cluster_span_ids: list[str]
    target_mode: str = "run"
    target_paragraph_id: str | None = None
    # G2 click-time grouping: the proven source show (None = not proven, the
    # hit is today's single run) and the index runs forming the target, in
    # parser (span_idx) order.
    source_ref: SourceShowRef | None = None
    member_span_ids: tuple[str, ...] = ()
    # The index run actually under the point (F16-COPY-1).  For a grouped
    # show ``target_span_id`` is the show's FIRST word -- right for editing,
    # wrong for browse selection / char context, which need the word under
    # the point.  None on the block fallback (no real run was hit).
    hit_span_id: str | None = None

    # Keep tuple compatibility for existing callers/tests.
    def _legacy(self) -> tuple:
        return (
            self.target_bbox,
            self.target_text,
            self.font,
            self.size,
            self.color,
            self.rotation,
        )

    def __getitem__(self, idx: int):
        return self._legacy()[idx]

    def __iter__(self):
        return iter(self._legacy())

    def __len__(self):
        return len(self._legacy())


# R3.5: ``_EditTextResolveResult`` and ``_classify_insert_path`` moved to
# model/pdf_text_edit.py (LAST model seam). Re-exported so existing
# ``from model.pdf_model import ...`` test/UI imports keep working.
from model.pdf_text_edit import _EditTextResolveResult, _classify_insert_path  # noqa: E402, F401

# Xref-numbering epochs.  A page snapshot (``model.page_snapshot``) restores by
# xref, so it is only valid while the live document keeps the numbering it was
# captured under.  Every new ``fitz.Document`` installed as the live doc gets a
# fresh epoch (the default is "renumbered"); installers that provably preserve
# the numbering put the old epoch back, and a live garbage>=2 serialization
# (which renumbers the live doc in place) bumps it.
_XREF_EPOCHS = itertools.count(1)


def _next_xref_epoch() -> int:
    return next(_XREF_EPOCHS)


@dataclass
class DocumentSession:
    session_id: str
    canonical_path: str
    display_name: str
    original_path: str
    doc: fitz.Document
    tiered_commit_engine: TieredCommitEngine | None = None
    saved_path: str | None = None
    # Password captured at open (in-memory only), used to re-authenticate the
    # reopen-after-save handle when a full save preserves encryption. Never
    # logged or persisted to disk; the decrypted content already lives in RAM.
    password: str | None = None
    # Authentication class returned by ``doc.authenticate()`` at open: 2=user,
    # 4=owner, 6=both, None=unencrypted / no password barrier. Lets the optimize
    # pipeline preserve the source's auth role instead of promoting user->owner (R5-02).
    auth_level: int | None = None
    # Destructive edits may leave recoverable orphan xrefs in the live in-memory
    # document.  Once latched, every persistent / external serialization must do
    # a full garbage=4 rewrite.  Deliberately conservative: undo does not clear it.
    secure_save_required: bool = False
    # A failed edit whose rollback also failed left the live document possibly
    # half-rewritten (S13-DLG5-DAMAGED).  Latched for the session's life (undo
    # does not clear it): ``save_as`` onto the session's own file is refused,
    # only a Save As to another file is allowed.  Travels with a tab transfer.
    damaged: bool = False
    # The files the session was bound to when it was latched damaged (the good
    # copies), frozen by ``mark_session_damaged`` (F14-DMG-1): a Save As rebinds
    # saved/original/canonical path to the new file, so the gate cannot derive
    # them from the current fields.  No write of this session (Save As, export,
    # merge, optimize copy, recovery copy) may target them.  Travels with a tab
    # transfer; emptied only by ``clear_session_damaged``.
    damaged_protected_paths: frozenset[str] = frozenset()
    # Set once a save closed the live handle and nothing could take its place
    # (``SaveRecoveryError``, S14-SAVEREC-DEAD-TAB, owner decision C).  The
    # session's ``doc`` is then a closed handle that must never be touched:
    # ``PDFModel.doc`` hides it, ``save_as`` re-raises this error (a retry keeps
    # the recovery-path message) and the controller shows a dead tab.  Latched
    # for the session's life.  Set only by ``PDFModel._mark_session_lost``.
    save_lost_error: SaveRecoveryError | None = None
    block_manager: TextBlockManager = field(default_factory=TextBlockManager)
    command_manager: CommandManager = field(default_factory=CommandManager)
    pending_edits: list = field(default_factory=list)
    # Pages that received a V2 Tier 0 lossless commit: their content streams
    # must never pass through clean_contents (it would destroy the verified
    # byte identity). A later legacy rewrite of the page revokes the entry
    # via PDFModel.mark_page_content_dirty.
    fidelity_protected_pages: set = field(default_factory=set)
    edit_count: int = 0
    run_reopen_anchors: dict[str, fitz.Rect] = field(default_factory=dict)
    run_reopen_anchor_sizes: dict[str, float] = field(default_factory=dict)
    # Single-line texts the app wrote as several runs for ONE edit, by page
    # (S17-ANCHOR-JOIN); each is re-proven against the live runs before use.
    joined_edit_runs: dict[int, list[JoinedEditRun]] = field(default_factory=dict)
    # A delete-all operation retains one physical blank page so downstream PyMuPDF
    # and View code never have to handle an empty active document. This marker is
    # session-local and must travel with SnapshotCommand undo/redo state.
    blank_placeholder_active: bool = False
    transferred_dirty: bool = False
    # Identity of the live document's xref numbering (see ``_next_xref_epoch``).
    xref_epoch: int = field(default_factory=_next_xref_epoch)
    # ``xref_length()`` of the file backing ``doc`` as last persisted (set on
    # open, after a reopen-after-save and after a successful incremental save;
    # ``None`` = unknown).  Objects at xref >= this value were created in this
    # session, which is what the incremental-save orphan check scans.
    persisted_xref_length: int | None = None
    # Lowest xref number the live table may allocate a NEW object at: the
    # ``xref_length()`` of the file as a signed append (R7-1) last left it.  The
    # appended revision's xref stream / object stream take numbers beyond the
    # live table's end, so a live handle that kept its shorter table would hand
    # the next new object a number the file's container already owns (R8-SIG-B).
    # Applied to every handle the session installs (see the ``doc`` setter).
    reserved_xref_length: int = 0
    # ``_file_fingerprint`` of the file this session owns (``disk_fingerprint_path``,
    # canonical) as it opened or last wrote it.  A save back to that path whose
    # current fingerprint differs was rewritten by another program and is refused
    # (F10-FS-1).  ``None`` = no baseline: never refuses.  A detached transfer carries
    # the sender's pair unchanged (F11-OPEN-2); it is never re-measured on import.
    disk_fingerprint: tuple[int, int, str] | None = None
    disk_fingerprint_path: str | None = None
    # Deny-write share locks (Windows; OD-FS1-LOCK) on the user files this session
    # depends on: the file it owns and, if the live handle still lazily reads
    # another user file, that one.  Kept in step by ``_sync_session_file_locks``,
    # released by ``close_session``; the app's own writes suspend them.
    file_locks: list[file_share_lock.FileShareLock] = field(default_factory=list)


class PDFModel:
    @property
    def text_commit_settings(self) -> TextCommitSettings:
        return self._text_commit_settings

    @text_commit_settings.setter
    def text_commit_settings(self, value: TextCommitSettings | None) -> None:
        # Part-3 VERIFY defect 7 (chokepoint): the settings are never None.
        # Unknown settings mean the shipped tiered defaults -- fail-closed,
        # consistent with the Controller's cross-page consent gate -- never
        # a silent fall-through to the legacy engine.
        self._text_commit_settings = value if value is not None else TextCommitSettings()

    def __init__(self, text_commit_settings: TextCommitSettings | None = None):
        self._sessions_by_id: dict[str, DocumentSession] = {}
        # Private temp-dir copies (``live_*.pdf`` / ``recover_*.pdf``) a live
        # handle was reading before a whole-document reinstall replaced it; see
        # ``_retire_replaced_handle``.
        self._retired_live_copies: list[Path] = []
        self._session_ids: list[str] = []
        self._active_session_id: str | None = None
        # V2 text-commit engine flags (Qt-free DTO, injected at composition
        # root; since Task 16 the default engine is "tiered" and
        # TEXT_COMMIT_ENGINE=legacy is the kill switch) + the outcome of
        # the most recent edit_text commit for history/telemetry plumbing.
        self.text_commit_settings = text_commit_settings
        self.last_commit_outcome: CommitOutcome | None = None
        # D-OLD-MARKERS: why the most recent move / resize / rotate / delete of an
        # object changed nothing (``model/object_op_refusal.py``); ``None`` after a
        # success. Read by the Controller right after the call, never later.
        self.last_object_op_refusal: ObjectOpRefused | None = None
        # F11-UNI-1 (owner decision C): the untouched glyphs a consented
        # rebuild cannot keep, set by ``edit_text`` ONLY while it asks the
        # consent callback, so the Controller's dialog can name them; ()
        # at every other time.  A consent acknowledges them by returning
        # ``RebuildConsent(acknowledged_glyph_loss=<this exact tuple>)``.
        self.pending_rebuild_glyph_loss: tuple[UnkeepableGlyph, ...] = ()
        self._path_to_session_id: dict[str, str] = {}
        self._legacy_doc: fitz.Document | None = None
        self._legacy_tiered_commit_engine: TieredCommitEngine | None = None
        self._legacy_original_path: str | None = None
        self._legacy_saved_path: str | None = None
        self._legacy_password: str | None = None
        self._legacy_block_manager: TextBlockManager = TextBlockManager()
        self._legacy_command_manager: CommandManager = CommandManager()
        self._legacy_edit_count: int = 0
        self._legacy_secure_save_required: bool = False
        self._legacy_damaged: bool = False
        self._legacy_damaged_protected_paths: frozenset[str] = frozenset()
        self._legacy_save_lost_error: SaveRecoveryError | None = None
        self._legacy_persisted_xref_length: int | None = None
        self._legacy_reserved_xref_length: int = 0
        self._legacy_pending_edits: list = []
        self._legacy_fidelity_protected_pages: set = set()
        self._legacy_run_reopen_anchors: dict[str, fitz.Rect] = {}
        self._legacy_run_reopen_anchor_sizes: dict[str, float] = {}
        self._legacy_joined_edit_runs: dict[int, list[JoinedEditRun]] = {}
        # Any: gradual typing — save paths access .name behind runtime guards
        # that mypy cannot see; keep pre-typed-__init__ semantics.
        self.temp_dir: Any = None
        # 是否在「存回原檔」時使用增量更新（Incremental Update），以減少對數位簽章與大檔的影響
        self.use_incremental_save: bool = True
        # Text target granularity: "run" or "paragraph" (UI can override on startup).
        self.text_target_mode: str = "run"
        # G2: click-time source-show grouping cache (pull-validated per lookup).
        self._source_run_resolver: SourceRunResolver = SourceRunResolver()
        self.tools = ToolManager(self)
        self._audit_report_cache_key: tuple | None = None
        self._audit_report_cache_value: PdfAuditReport | None = None
        self._initialize_temp_dir()
        # 全局 glyph 高度調整（文件推薦，import 後設定一次）
        try:
            fitz.TOOLS.set_small_glyph_heights(True)
            logger.debug("已設定 PyMuPDF TOOLS.set_small_glyph_heights(True)")
        except AttributeError:
            logger.warning("PyMuPDF 版本無 TOOLS 支援，跳過 glyph 調整")

    def _canonicalize_path(self, path: str) -> str:
        """Normalize path for dedupe across tabs (case-insensitive on Windows)."""
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            # An unreachable UNC share raises WinError 53 under Py3.10 even for
            # non-strict resolution. find_session_by_path() runs BEFORE open_pdf's
            # try/except at startup / on forwarded-CLI / on recent-file clicks, so
            # an unguarded raise here crashes the open flow. Fall back to a pure
            # string canonical form (no filesystem access) to keep dedupe alive.
            resolved = os.path.abspath(os.path.expanduser(path))
        if sys.platform == "win32":
            # Win32 drops a trailing dot / space from the last name component when it
            # creates or opens a file.  A file that exists already resolves to its
            # stored name, but the key of a path that does not exist YET (Save As
            # typed ``t2.pdf.``) must already be the key the file will have once
            # written, or no later lookup of it matches (F10-FS-2).
            head, tail = os.path.split(resolved)
            stripped = tail.rstrip(". ")
            if stripped and stripped != tail:
                resolved = os.path.join(head, stripped)
        return resolved.casefold()

    @staticmethod
    def _safe_exc_message(exc: Exception) -> str:
        try:
            return str(exc)
        except Exception:
            return repr(exc)

    def _active_session(self) -> DocumentSession | None:
        # getattr-guarded so PDFModel.__new__(...) instances (used by some
        # unit tests that bypass __init__) don't AttributeError here.
        active_session_id = getattr(self, "_active_session_id", None)
        if not active_session_id:
            return None
        sessions_by_id = getattr(self, "_sessions_by_id", {})
        return sessions_by_id.get(active_session_id)

    @property
    def blank_placeholder_active(self) -> bool:
        session = self._active_session()
        return bool(session and session.blank_placeholder_active)

    def _set_blank_placeholder_active(self, active: bool) -> None:
        session = self._active_session()
        if session is not None:
            session.blank_placeholder_active = bool(active)

    @contextmanager
    def _activate_temporarily(self, session_id: str) -> Iterator[None]:
        previous = self._active_session_id
        if session_id != previous:
            self.activate_session(session_id)
        try:
            yield
        finally:
            if previous and previous in self._sessions_by_id:
                self._active_session_id = previous
            elif self._active_session_id not in self._sessions_by_id:
                self._active_session_id = self._session_ids[0] if self._session_ids else None

    @property
    def session_ids(self) -> list[str]:
        return list(self._session_ids)

    def list_sessions(self) -> list[dict]:
        return [self._session_meta(sid, self._sessions_by_id[sid]) for sid in self._session_ids]

    def _session_meta(self, session_id: str, session: DocumentSession) -> dict:
        """The tab-strip view of a session (``list_sessions`` / ``get_session_meta``)."""
        lost = session.save_lost_error
        return {
            "id": session_id,
            "display_name": session.display_name,
            "path": session.original_path,
            "saved_path": session.saved_path,
            "dirty": self.session_has_unsaved_changes(session_id),
            "lost": lost is not None,
            "recovery_path": str(lost.recovery_path) if lost else None,
        }

    def get_session_id_by_index(self, index: int) -> str | None:
        if index < 0 or index >= len(self._session_ids):
            return None
        return self._session_ids[index]

    def get_active_session_id(self) -> str | None:
        return self._active_session_id

    def get_active_session_index(self) -> int:
        if not self._active_session_id:
            return -1
        try:
            return self._session_ids.index(self._active_session_id)
        except ValueError:
            return -1

    def find_session_by_path(self, path: str) -> str | None:
        canonical = self._canonicalize_path(path)
        return self._path_to_session_id.get(canonical)

    def activate_session(self, session_id: str) -> bool:
        if session_id not in self._sessions_by_id:
            return False
        self._active_session_id = session_id
        return True

    def activate_session_by_index(self, index: int) -> bool:
        sid = self.get_session_id_by_index(index)
        if not sid:
            return False
        return self.activate_session(sid)

    def session_has_unsaved_changes(self, session_id: str) -> bool:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return False
        return bool(
            session.transferred_dirty
            or session.command_manager.has_pending_changes()
            or self.tools.has_unsaved_changes(session_id)
        )

    def has_any_unsaved_changes(self) -> bool:
        return any(self.session_has_unsaved_changes(sid) for sid in self._session_ids)

    def get_dirty_session_ids(self) -> list[str]:
        return [sid for sid in self._session_ids if self.session_has_unsaved_changes(sid)]

    def get_session_meta(self, session_id: str) -> dict | None:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return None
        return self._session_meta(session_id, session)

    def close_session(self, session_id: str) -> bool:
        session = self._sessions_by_id.get(session_id)
        if not session:
            return False
        self.tools.on_session_close(session_id)
        session.tiered_commit_engine = None
        detached_copy = self._model_temp_file_of(session.doc)
        try:
            if session.doc:
                session.doc.close()
        except Exception as e:
            # Some paths (stress/script runners) may already close the document handle.
            # Treat "document closed" as benign cleanup noise.
            msg = str(e).lower()
            if "document closed" in msg:
                logger.debug(f"session 文件已關閉 ({session_id})，略過重複 close")
            else:
                logger.warning(f"關閉 session 文件失敗 ({session_id}): {e}")
        # The file is free for other programs once the session is gone (OD-FS1-LOCK).
        self._release_session_file_locks(session)
        if detached_copy is not None:
            self._remove_detached_copy(detached_copy)
        self._sweep_retired_live_copies(collect=True)
        self._sessions_by_id.pop(session_id, None)
        self._session_ids = [sid for sid in self._session_ids if sid != session_id]
        # Only while the path still names THIS session: a lost session released
        # it, and a newer tab may own it now.
        if self._path_to_session_id.get(session.canonical_path) == session_id:
            self._path_to_session_id.pop(session.canonical_path, None)
        if self._active_session_id == session_id:
            self._active_session_id = self._session_ids[0] if self._session_ids else None
        return True

    def close_all_sessions(self) -> None:
        for sid in list(getattr(self, "_session_ids", [])):
            self.close_session(sid)

    def save_session_as(
        self, session_id: str, new_path: str, *, allow_signature_loss: bool = False
    ) -> None:
        if session_id not in self._sessions_by_id:
            raise RuntimeError(f"Session 不存在: {session_id}")
        canonical = self._canonicalize_path(new_path)
        existing = self._path_to_session_id.get(canonical)
        if existing and existing != session_id:
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        with self._activate_temporarily(session_id):
            self.save_as(new_path, allow_signature_loss=allow_signature_loss)

    @property
    def doc(self) -> fitz.Document | None:
        session = self._active_session()
        if session:
            # A lost session (``SaveRecoveryError``) holds a CLOSED handle, and
            # ``bool(closed_doc)`` raises ``document closed``: every
            # ``if not model.doc`` guard in the app would be a crash site.  Hand
            # out ``None`` instead, so the session reads as "no document".
            # ``session.doc`` stays reachable for ``close_session``.
            return None if session.save_lost_error is not None else session.doc
        return self._legacy_doc

    @doc.setter
    def doc(self, value: fitz.Document | None) -> None:
        session = self._active_session()
        if session:
            if session.doc is not value:
                self._retire_replaced_handle(session.doc, value)
                session.tiered_commit_engine = None
                session.xref_epoch = _next_xref_epoch()
                # A new handle has an unknown persisted baseline until the
                # installer (open / reopen-after-save) records it.
                session.persisted_xref_length = None
            session.doc = value
            self._reserve_xref_numbers(value, session.reserved_xref_length)
        else:
            if getattr(self, "_legacy_doc", None) is not value:
                self._retire_replaced_handle(getattr(self, "_legacy_doc", None), value)
                self._legacy_tiered_commit_engine = None
                self._legacy_xref_epoch = _next_xref_epoch()
                self._legacy_persisted_xref_length = None
            self._legacy_doc = value
            self._reserve_xref_numbers(value, getattr(self, "_legacy_reserved_xref_length", 0))

    @property
    def xref_epoch(self) -> int:
        """Identity of the live document's xref numbering (page snapshots only
        restore under the epoch they were captured in)."""
        session = self._active_session()
        return session.xref_epoch if session else getattr(self, "_legacy_xref_epoch", 0)

    def _set_xref_epoch(self, value: int) -> None:
        session = self._active_session()
        if session:
            session.xref_epoch = int(value)
        else:
            self._legacy_xref_epoch = int(value)

    @property
    def persisted_xref_length(self) -> int | None:
        """``xref_length()`` of the backing file as last persisted (``None`` = unknown)."""
        session = self._active_session()
        return (
            session.persisted_xref_length
            if session
            else getattr(self, "_legacy_persisted_xref_length", None)
        )

    def _set_persisted_xref_length(self, value: int | None) -> None:
        stored = None if value is None else int(value)
        session = self._active_session()
        if session:
            session.persisted_xref_length = stored
        else:
            self._legacy_persisted_xref_length = stored

    @property
    def reserved_xref_length(self) -> int:
        """Lowest xref number a new object of the live document may take (0 = no floor)."""
        session = self._active_session()
        return (
            session.reserved_xref_length
            if session
            else getattr(self, "_legacy_reserved_xref_length", 0)
        )

    def _reserve_xref_numbers(self, doc: fitz.Document | None, length: int) -> None:
        """Make ``doc`` skip the numbers below ``length`` for its next new object.

        Pads the table with empty (``null``) slots; no existing object, no
        stream and no xref epoch changes, and a save that prunes (``garbage``
        >= 1) drops the empty slots again.  Best effort: a handle that cannot
        grow just keeps its own numbering and a later signed append declines
        (full rewrite) instead of corrupting anything.
        """
        if doc is None or length <= 0:
            return
        try:
            if not doc.is_pdf or doc.is_closed:
                return
            while int(doc.xref_length()) < length:
                doc.get_new_xref()
        except Exception:
            logger.warning("無法保留已被附加修訂使用的 xref 編號", exc_info=True)

    def _raise_reserved_xref_length(self, length: int) -> None:
        """Raise the session's xref floor to ``length`` and pad the live handle to it."""
        value = max(int(length), self.reserved_xref_length)
        session = self._active_session()
        if session:
            session.reserved_xref_length = value
        else:
            self._legacy_reserved_xref_length = value
        self._reserve_xref_numbers(self.doc, value)

    def _note_persisted_baseline(self) -> None:
        """Record the live (file-backed) doc's current table as persisted on disk."""
        doc = self.doc
        self._set_persisted_xref_length(
            int(doc.xref_length()) if doc is not None and self._backing_file(doc) is not None else None
        )

    def _bump_xref_epoch(self) -> None:
        self._set_xref_epoch(_next_xref_epoch())

    def _note_live_doc_serialized(self, doc: fitz.Document, garbage: int) -> None:
        """A ``garbage >= 2`` serialization of the LIVE doc renumbers it in place."""
        if garbage >= 2 and doc is self.doc:
            self._bump_xref_epoch()

    @property
    def original_path(self) -> str | None:
        session = self._active_session()
        return session.original_path if session else self._legacy_original_path

    @original_path.setter
    def original_path(self, value: str) -> None:
        session = self._active_session()
        if session:
            session.original_path = value
        else:
            self._legacy_original_path = value

    @property
    def saved_path(self) -> str | None:
        session = self._active_session()
        return session.saved_path if session else self._legacy_saved_path

    @saved_path.setter
    def saved_path(self, value: str | None) -> None:
        session = self._active_session()
        if session:
            session.saved_path = value
        else:
            self._legacy_saved_path = value

    @property
    def secure_save_required(self) -> bool:
        session = self._active_session()
        return session.secure_save_required if session else self._legacy_secure_save_required

    @secure_save_required.setter
    def secure_save_required(self, value: bool) -> None:
        session = self._active_session()
        if session:
            session.secure_save_required = bool(value)
        else:
            self._legacy_secure_save_required = bool(value)

    @property
    def session_damaged(self) -> bool:
        """True once a failed edit could not be rolled back (see ``DocumentSession.damaged``)."""
        session = self._active_session()
        if session:
            return session.damaged
        return bool(getattr(self, "_legacy_damaged", False))

    def is_session_damaged(self, session_id: str) -> bool:
        session = self._sessions_by_id.get(session_id)
        return bool(session and session.damaged)

    def mark_session_damaged(self, reason: str) -> None:
        """Latch the active session as damaged.  The ONE place the flag is set.

        Called wherever a rollback of a mutated document fails: the live
        document can no longer be trusted to equal a good state, so nothing may
        write it over the file it was opened from.  ``reason`` is logged only.

        The files the session is bound to NOW are frozen as its protected set
        (F14-DMG-1): a later Save As rebinds the session to the new file, and
        the original must stay protected after that.
        """
        session = self._active_session()
        bound = self._paths_bound_to_session(session)
        if session:
            session.damaged = True
            session.damaged_protected_paths = session.damaged_protected_paths | bound
        else:
            self._legacy_damaged = True
            self._legacy_damaged_protected_paths = self._legacy_damaged_protected_paths | bound
        logger.error("session marked damaged (in-place saves refused): %s", reason)

    def _paths_bound_to_session(self, session: DocumentSession | None) -> frozenset[str]:
        """Canonical forms of a session's own file (saved / opened-from / mapped path).

        ``None`` = the legacy session-less document.
        """
        if session is None:
            candidates = (self._legacy_saved_path, self._legacy_original_path)
        else:
            candidates = (session.saved_path, session.original_path)
        paths = {self._canonicalize_path(str(p)) for p in candidates if p}
        if session is not None and session.canonical_path:
            paths.add(session.canonical_path)
        return frozenset(paths)

    def damaged_protected_paths(self, session_id: str | None = None) -> frozenset[str]:
        """Canonical paths no write of a damaged session may target (empty when undamaged).

        The ONE source every write gate consults (F14-DMG-1): the files frozen
        when the session was latched damaged (``mark_session_damaged``) plus the
        file it is bound to now.  ``session_id`` defaults to the active session.
        """
        if session_id is None:
            session = self._active_session()
            if session is None:
                if not self._legacy_damaged:
                    return frozenset()
                return self._legacy_damaged_protected_paths | self._paths_bound_to_session(None)
        else:
            session = self._sessions_by_id.get(session_id)
            if session is None:
                return frozenset()
        if not session.damaged:
            return frozenset()
        return session.damaged_protected_paths | self._paths_bound_to_session(session)

    def _refuse_write_over_damaged_original(
        self, path: str | Path, session_id: str | None = None, *, message: str
    ) -> None:
        """Raise ``DamagedSessionSaveError`` when ``path`` is a file a damaged session protects.

        Called before anything is written by every route that writes the
        session's content to a user-chosen path: ``save_as``, export / merge
        (``save_external_document``), the recovery copy of a lost session, and
        the optimize copy (via the frozen ``OptimizeSourceSnapshot``).
        """
        protected = self.damaged_protected_paths(session_id)
        if not protected:
            return
        if self._canonicalize_path(str(path)) not in protected:
            return
        logger.warning("寫入已取消：文件已標記為損壞，不得覆寫原檔: %s", path)
        raise DamagedSessionSaveError(message, path=Path(path))

    def clear_session_damaged(self, reason: str) -> None:
        """Lift the damaged latch of the active session.  The ONE place it is cleared.

        Only for a caller that has just replaced the WHOLE live document from a
        snapshot captured while the session was NOT damaged (the cross-page
        move's restore, F13-MOVE-1a): the document is then byte-for-byte a
        good state again and the latch from the failed edit is stale.  A
        session damaged before that snapshot must not be cleared.
        """
        session = self._active_session()
        if session:
            session.damaged = False
            session.damaged_protected_paths = frozenset()
        else:
            self._legacy_damaged = False
            self._legacy_damaged_protected_paths = frozenset()
        logger.warning("session damaged latch cleared: %s", reason)

    @property
    def session_lost(self) -> bool:
        """True once a save left the active session on a closed handle (see ``DocumentSession.save_lost_error``)."""
        return self.lost_session_error() is not None

    def is_session_lost(self, session_id: str) -> bool:
        return self.lost_session_error(session_id) is not None

    def lost_session_error(self, session_id: str | None = None) -> SaveRecoveryError | None:
        """The ``SaveRecoveryError`` that ended ``session_id`` (default: the active session), else ``None``."""
        if session_id is None:
            session = self._active_session()
            if session is None:
                return getattr(self, "_legacy_save_lost_error", None)
        else:
            session = self._sessions_by_id.get(session_id)
        return session.save_lost_error if session is not None else None

    def _mark_session_lost(self, error: SaveRecoveryError) -> None:
        """Latch the active session as lost.  The ONE place ``save_lost_error`` is set.

        Called by ``_install_stage_over_open_file`` when the live handle was
        closed and no copy of the session could be reopened.  The deny-write
        share locks are dropped: the closed handle reads nothing, and the user
        may need the original file free to restore it from the recovery copy.
        """
        session = self._active_session()
        if session is None:
            self._legacy_save_lost_error = error
        else:
            session.save_lost_error = error
            self._release_session_file_locks(session)
            # The session owns nothing on disk any more: opening the file again
            # (the message says to) must start a live tab, not switch back to this one.
            if self._path_to_session_id.get(session.canonical_path) == session.session_id:
                self._path_to_session_id.pop(session.canonical_path, None)
        logger.error("session lost after a failed save (recovery copy kept): %s", error.recovery_path)

    def _refuse_save_on_lost_session(self) -> None:
        """Re-raise the stored ``SaveRecoveryError`` for a save of a lost session.

        The session's document is a closed handle, so a second Ctrl+S / Save As
        would only fail with ``document closed`` and hide where the unsaved
        edits were kept.  Raised before anything is touched; a fresh instance
        (same message and recovery path) per attempt.
        """
        error = self.lost_session_error()
        if error is None:
            return
        raise SaveRecoveryError(
            str(error), recovery_path=error.recovery_path, target_written=error.target_written
        )

    def copy_lost_session_recovery(self, new_path: str, session_id: str | None = None) -> Path:
        """Save As for a lost session (default: the active one): copy its recovery file to ``new_path``.

        The recovery copy holds the session's unsaved edits.  The session itself
        stays lost (its document cannot be reopened): the user opens the copy.
        The write is staged next to the target and moved in place, so a failed
        copy never truncates an existing file.  The same refusal as ``save_as``
        applies to a target another tab has open.  Returns the path written.
        """
        sid = session_id or self.get_active_session_id()
        error = self.lost_session_error(sid)
        if error is None:
            raise RuntimeError("這個分頁沒有中斷，請使用一般的另存新檔。")
        recovery = Path(error.recovery_path)
        if not recovery.is_file():
            raise FileNotFoundError(f"暫存副本已不存在：{recovery}")
        canonical_new = self._canonicalize_path(new_path)
        existing_sid = self._path_to_session_id.get(canonical_new)
        if (existing_sid and existing_sid != sid) or (
            self._session_reading_path(new_path, exclude_session_id=sid) is not None
        ):
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        # The recovery copy of a damaged session holds the damaged content too.
        self._refuse_write_over_damaged_original(
            new_path, sid, message=DAMAGED_SESSION_WRITE_MESSAGE
        )
        if self._canonicalize_path(str(recovery)) == canonical_new:
            raise RuntimeError("目標不能是暫存副本本身，請選擇其他位置。")
        target = resolve_as_requested(new_path)
        sibling = staging_sibling(target, "recovered")
        try:
            shutil.copy2(str(recovery), str(sibling))
            replace_file(sibling, target)
        finally:
            self._discard_staged_file(sibling)
        return Path(target)

    def _restore_doc_after_failed_mutation(self, snapshot_bytes: bytes) -> None:
        """``_restore_doc_from_snapshot`` for the ROLLBACK of a failed mutation.

        Unlike an undo, a restore that fails here leaves a document the failed
        operation already changed: latch the session damaged and re-raise.
        """
        try:
            self._restore_doc_from_snapshot(snapshot_bytes)
        except Exception as exc:
            self.mark_session_damaged(f"document rollback failed: {type(exc).__name__}")
            raise

    @property
    def password(self) -> str | None:
        session = self._active_session()
        return session.password if session else self._legacy_password

    @password.setter
    def password(self, value: str | None) -> None:
        session = self._active_session()
        if session:
            session.password = value
        else:
            self._legacy_password = value

    def get_tiered_commit_engine(self) -> TieredCommitEngine:
        """Return the engine owned by the active document session.

        Preview workers produce immutable ``PreparedEdit`` DTOs on a
        session-scratch document.  The corresponding live-document engine
        therefore must outlive each keystroke and each controller callback so
        its verified-candidate cache remains available to commit.
        """
        doc = self.doc
        if doc is None:
            raise RuntimeError("cannot create a text-commit engine without a document")
        session = self._active_session()
        if session is not None:
            engine = session.tiered_commit_engine
        else:
            engine = self._legacy_tiered_commit_engine
        max_tier = int(getattr(self.text_commit_settings, "max_tier", TextCommitSettings.max_tier))
        if (
            engine is None
            or getattr(engine, "_doc", None) is not doc
            or getattr(engine, "_max_tier", max_tier) != max_tier
        ):
            engine = TieredCommitEngine(
                doc,
                password=self.password,
                max_tier=max_tier,
                serialize=self.serialize_document_bytes,
            )
            if session is not None:
                session.tiered_commit_engine = engine
            else:
                self._legacy_tiered_commit_engine = engine
        return engine

    @property
    def tiered_commit_engine(self) -> TieredCommitEngine | None:
        """The active session's engine, if a document is currently open."""
        if self.doc is None:
            return None
        return self.get_tiered_commit_engine()

    def cache_verified_candidate(self, token: str, prepared) -> None:
        """Cache a scratch-verified candidate in the active session engine."""
        self.get_tiered_commit_engine().cache_verified_candidate(token, prepared)

    def clear_verified_candidates(self) -> None:
        """Invalidate preview candidates after an unrelated document change."""
        engine = self.tiered_commit_engine
        if engine is not None:
            engine.clear_verified_candidates()

    @property
    def block_manager(self) -> TextBlockManager:
        session = self._active_session()
        return session.block_manager if session else self._legacy_block_manager

    @block_manager.setter
    def block_manager(self, value: TextBlockManager) -> None:
        session = self._active_session()
        if session:
            session.block_manager = value
        else:
            self._legacy_block_manager = value

    @property
    def command_manager(self) -> CommandManager:
        session = self._active_session()
        return session.command_manager if session else self._legacy_command_manager

    @command_manager.setter
    def command_manager(self, value: CommandManager) -> None:
        session = self._active_session()
        if session:
            session.command_manager = value
        else:
            self._legacy_command_manager = value

    @property
    def edit_count(self) -> int:
        session = self._active_session()
        return session.edit_count if session else self._legacy_edit_count

    @edit_count.setter
    def edit_count(self, value: int) -> None:
        session = self._active_session()
        if session:
            session.edit_count = value
        else:
            self._legacy_edit_count = value

    @property
    def pending_edits(self) -> list:
        session = self._active_session()
        return session.pending_edits if session else self._legacy_pending_edits

    @pending_edits.setter
    def pending_edits(self, value: list) -> None:
        session = self._active_session()
        if session:
            session.pending_edits = value
        else:
            self._legacy_pending_edits = value

    @property
    def fidelity_protected_pages(self) -> set:
        session = self._active_session()
        if session:
            return session.fidelity_protected_pages
        return self._legacy_fidelity_protected_pages

    @fidelity_protected_pages.setter
    def fidelity_protected_pages(self, value: set) -> None:
        session = self._active_session()
        if session:
            session.fidelity_protected_pages = value
        else:
            self._legacy_fidelity_protected_pages = value

    def mark_page_content_dirty(self, page_idx: int, rect: fitz.Rect) -> None:
        """Chokepoint for every legacy content rewrite of a page.

        Queues the page for clean_contents maintenance AND revokes its V2
        Tier-0 fidelity protection: a redact/reinsert (or object rewrite)
        invalidates the byte-identity promise, after which normal cleanup
        is both safe and desirable again.
        """
        self.fidelity_protected_pages.discard(page_idx)
        self.pending_edits.append({"page_idx": page_idx, "rect": fitz.Rect(rect)})

    # ── Run reopen anchors ────────────────────────────────────────────────
    # A run-mode edit shrinks/repositions the committed box every commit. To
    # stop that drift cumulating across open→edit→reopen cycles, the FIRST
    # run-mode edit records the original span bbox+size as an anchor, keyed by
    # "{page_idx}::{span_id}". Subsequent edits and the next click resolve
    # against the anchor instead of the freshly-shrunk geometry.

    @property
    def run_reopen_anchors(self) -> dict[str, fitz.Rect]:
        session = self._active_session()
        return session.run_reopen_anchors if session else self._legacy_run_reopen_anchors

    @run_reopen_anchors.setter
    def run_reopen_anchors(self, value: dict[str, fitz.Rect]) -> None:
        session = self._active_session()
        if session:
            session.run_reopen_anchors = value
        else:
            self._legacy_run_reopen_anchors = value

    @property
    def run_reopen_anchor_sizes(self) -> dict[str, float]:
        session = self._active_session()
        return session.run_reopen_anchor_sizes if session else self._legacy_run_reopen_anchor_sizes

    @run_reopen_anchor_sizes.setter
    def run_reopen_anchor_sizes(self, value: dict[str, float]) -> None:
        session = self._active_session()
        if session:
            session.run_reopen_anchor_sizes = value
        else:
            self._legacy_run_reopen_anchor_sizes = value

    # ── Joined edit runs (S17-ANCHOR-JOIN) ────────────────────────────────
    # A rebuild that re-inserts one edited line as several runs on a baseline
    # (a Latin word + a CJK tail: two fonts) records the text it wrote; the
    # hit-test and the commit re-prove the record against the live runs and
    # treat those runs as ONE box.  Records are session-local like anchors.

    @property
    def joined_edit_runs(self) -> dict[int, list[JoinedEditRun]]:
        session = self._active_session()
        return session.joined_edit_runs if session else self._legacy_joined_edit_runs

    @joined_edit_runs.setter
    def joined_edit_runs(self, value: dict[int, list[JoinedEditRun]]) -> None:
        session = self._active_session()
        if session:
            session.joined_edit_runs = value
        else:
            self._legacy_joined_edit_runs = value

    _JOINED_EDIT_RUNS_PER_PAGE = 64

    def _remember_joined_edit_run(self, page_idx: int, record: JoinedEditRun) -> None:
        """Keep ``record`` for the page (newest last, oldest dropped past a cap).

        Superseded records are NOT pruned: a record proves only while the page
        shows exactly its text, so a replaced one is inert, and undo brings
        the older text -- and its record -- back."""
        records = self.joined_edit_runs.setdefault(int(page_idx), [])
        if record in records:
            records.remove(record)
        records.append(record)
        del records[: -self._JOINED_EDIT_RUNS_PER_PAGE]

    def _joined_edit_group_for(
        self,
        page_idx: int,
        spans: list[EditableSpan],
        *,
        span_id: str | None = None,
        point: fitz.Point | None = None,
    ) -> JoinedEditGroup | None:
        """The proven joined group of a page: the one containing run ``span_id``
        or, with no run under ``point``, the one whose union contains it.
        Records that no longer prove against the live runs are skipped."""
        records = self.joined_edit_runs.get(int(page_idx))
        if not records or not spans:
            return None
        for record in reversed(records):
            if point is not None and point not in record.region():
                continue
            group = prove_joined_group(record, spans)
            if group is None:
                continue
            if span_id is not None:
                if span_id in group.member_span_ids:
                    return group
            elif point is not None and point in group.rect():
                return group
        return None

    @staticmethod
    def _run_reopen_anchor_key(page_idx: int, span_id: str) -> str:
        return f"{int(page_idx)}::{span_id}"

    @staticmethod
    def _stale_anchor_rebind_run(
        spans: list[EditableSpan], anchor_rect: fitz.Rect, point: fitz.Point
    ) -> EditableSpan | None:
        """The live run a stale reopen anchor (its span id no longer exists)
        may be re-bound to: a run intersecting ``anchor_rect``, the one under
        ``point`` first, then the one nearest the rect's centre.  ``None`` =
        no run is where the anchored text was."""
        cx = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
        cy = float(anchor_rect.y0 + (anchor_rect.height / 2.0))
        candidates = [s for s in spans if fitz.Rect(s.bbox).intersects(anchor_rect)]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda span: (
                0 if point in fitz.Rect(span.bbox) else 1,
                (float(span.bbox.x0 + (span.bbox.width / 2.0)) - cx) ** 2
                + (float(span.bbox.y0 + (span.bbox.height / 2.0)) - cy) ** 2,
            ),
        )

    def _get_run_reopen_anchor_rect(self, page_idx: int, span_id: str | None) -> fitz.Rect | None:
        if not span_id:
            return None
        rect = self.run_reopen_anchors.get(self._run_reopen_anchor_key(page_idx, span_id))
        return fitz.Rect(rect) if rect is not None else None

    def _set_run_reopen_anchor_rect(self, page_idx: int, span_id: str | None, rect: fitz.Rect | None) -> None:
        if not span_id or rect is None:
            return
        self.run_reopen_anchors[self._run_reopen_anchor_key(page_idx, span_id)] = fitz.Rect(rect)

    def _get_run_reopen_anchor_size(self, page_idx: int, span_id: str | None) -> float | None:
        if not span_id:
            return None
        value = self.run_reopen_anchor_sizes.get(self._run_reopen_anchor_key(page_idx, span_id))
        return float(value) if value is not None else None

    def _set_run_reopen_anchor_size(self, page_idx: int, span_id: str | None, size: float | None) -> None:
        if not span_id or size is None:
            return
        self.run_reopen_anchor_sizes[self._run_reopen_anchor_key(page_idx, span_id)] = float(size)

    def _delete_run_reopen_anchor(self, page_idx: int, span_id: str | None) -> None:
        if not span_id:
            return
        key = self._run_reopen_anchor_key(page_idx, span_id)
        self.run_reopen_anchors.pop(key, None)
        self.run_reopen_anchor_sizes.pop(key, None)

    def _iter_run_reopen_anchors_for_page(self, page_idx: int) -> Iterator[tuple[str, fitz.Rect]]:
        prefix = f"{int(page_idx)}::"
        for key, rect in list(self.run_reopen_anchors.items()):
            if not key.startswith(prefix):
                continue
            span_id = key[len(prefix):]
            if not span_id:
                continue
            yield span_id, fitz.Rect(rect)

    def set_text_target_mode(self, mode: str) -> None:
        normalized = (mode or "").strip().lower()
        if normalized not in {"run", "paragraph"}:
            logger.warning("invalid text target mode: %s (keep %s)", mode, self.text_target_mode)
            return
        self.text_target_mode = normalized
        logger.debug("text_target_mode set to %s", self.text_target_mode)

    def _initialize_temp_dir(self):
        """初始化臨時目錄，確保可寫入"""
        try:
            self.temp_dir = tempfile.TemporaryDirectory()
            logger.debug(f"成功創建臨時目錄: {self.temp_dir.name}")
            # 檢查目錄是否可寫入
            test_file = Path(self.temp_dir.name) / "test.txt"
            test_file.touch()
            test_file.unlink()
        except (PermissionError, OSError) as e:
            logger.error(f"無法創建臨時目錄: {e!s}")
            # 後備：使用當前工作目錄下的自訂臨時目錄
            fallback_dir = Path.cwd() / "pdf_temp"
            try:
                fallback_dir.mkdir(exist_ok=True)
                self.temp_dir = tempfile.TemporaryDirectory(dir=str(fallback_dir))
                logger.debug(f"使用後備臨時目錄: {self.temp_dir.name}")
            except Exception as e:
                raise RuntimeError(f"無法創建後備臨時目錄: {e!s}")

    def __del__(self):
        try:
            self.close()
        except AttributeError:
            pass

    @staticmethod
    def _doc_needs_xref_repair(doc: fitz.Document) -> bool:
        """True when MuPDF had to rebuild a damaged cross-reference table on open.

        ``is_repaired`` is set during ``fitz.open()`` for damage MuPDF meets
        while opening, and by the open-time object walk
        (``_read_every_object_at_open``, OD-FS1-READALL) for damage in an
        object it only loads lazily.  Reading it is a free flag check.
        """
        return bool(getattr(doc, "is_repaired", False))

    @staticmethod
    def _doc_is_encrypted(doc: fitz.Document) -> bool:
        """True when the *source* document is encrypted (any scheme).

        After ``authenticate()`` ``is_encrypted`` flips to False while ``needs_pass``
        stays 1 -- and reading ``needs_pass`` on an authenticated handle clobbers
        its crypt key (R9 M9-1) -- and an owner-password-only PDF opens with both
        already False, so neither flag is a safe signal here. The trailer's
        encryption string in ``doc.metadata`` is: it stays populated after
        authentication, is set even for owner-only encryption and reading it does
        not touch the crypt state, so it is the signal for "this file was
        encrypted on disk".

        Reading ``metadata`` is cheap: it gates the damaged-path round trip and
        the open-time xref compaction (``_compact_doc_xref_in_memory``).
        """
        return bool((doc.metadata or {}).get("encryption"))

    def _repair_doc_xref_in_memory(self, doc: fitz.Document) -> fitz.Document:
        """Return a clean in-memory copy of a doc whose xref MuPDF rebuilt on open.

        The in-memory document MuPDF hands back is already usable, but its xref is
        not yet persisted cleanly (and a repaired doc cannot be saved
        incrementally). Round-tripping the bytes with garbage collection produces
        a fresh, internally-consistent xref so later saves don't inherit the
        damage. ``garbage=1`` rebuilds the xref and compacts objects without the
        heavier duplicate-pruning of ``garbage=4`` — full pruning still happens on
        an explicit full save.

        Deliberately **not** ``deflate=True``: re-compressing every stream is the
        dominant cost on large files (≈20 ms/MB) yet adds nothing to a clean-xref
        repair — on already-compressed/image-heavy PDFs it shrinks nothing. Skipping
        it keeps the repair at ≈2.5–5 ms/MB (~1.3–2.6 s worst case at the 512 MB open
        cap vs ~10 s with deflate; a real damaged 47 MB / 402-page file repairs in
        ~240 ms). Stream compression belongs on an explicit save.

        On failure the original (already MuPDF-repaired) doc is returned unchanged
        so opening still succeeds.
        """
        try:
            repaired_bytes = doc.tobytes(garbage=1)
            repaired = fitz.open("pdf", repaired_bytes)
        except Exception as exc:  # noqa: BLE001 - never let auto-repair break open
            logger.warning(
                "開檔自動修復 XREF 失敗，沿用 MuPDF 載入的文件: %s",
                self._safe_exc_message(exc),
            )
            return doc
        try:
            doc.close()
        except Exception:
            pass
        logger.info("開檔偵測到損毀的 XREF 表，已自動於記憶體中重建乾淨的 xref")
        return repaired

    def _read_every_object_at_open(
        self, doc: fitz.Document, src_path: Path
    ) -> xref_compaction.ObjectWalk | None:
        """Load every object of the just-opened document once (OD-FS1-READALL).

        A broken xref entry for an object MuPDF loads lazily is otherwise
        found only by the save that first touches it: MuPDF then repairs the
        table mid-save and drops every in-memory edit (F10-FS-1 open issue 2).
        Reading everything here moves that repair to open, before edits exist;
        ``is_repaired`` turns True and the repair round trip below takes the
        document over (encrypted documents keep MuPDF's repaired handle, whose
        saves are full rewrites).  Encrypted documents are walked too: reading
        objects never touches ``needs_pass`` (R9 M9-1).  Bounded by
        ``xref_compaction.MAX_READ_ALL_SLOTS`` (~1 s); never fails the open.
        The result doubles as the compaction census.
        """
        try:
            file_size = int(src_path.stat().st_size)
        except OSError:
            return None
        walk = xref_compaction.read_every_object(doc, file_size)
        if walk.repaired:
            logger.info("開檔讀取全部物件時發現延遲損毀的 XREF 表，MuPDF 已於開檔時修復（尚無任何編輯）")
        return walk

    def _compact_doc_xref_in_memory(
        self,
        doc: fitz.Document,
        src_path: Path,
        walk: xref_compaction.ObjectWalk | None = None,
    ) -> fitz.Document:
        """Reclaim a table full of free xref slots at open, in memory only (round 8 LS-3).

        Runs only from ``open_pdf``, before the session exists: no page snapshot
        or ``xref_epoch`` can be stranded by the renumbering.  It runs before
        the xref repair step: a document the open-time object walk
        (``_read_every_object_at_open``) or the census found lazily damaged is
        repaired by MuPDF at that moment (``is_repaired`` turns True and the
        repair round trip takes over), and a compacted document is already
        clean.  The verdict (``xref_compaction.open_compaction_verdict``: size
        cap, free-slot count from ``walk`` when it counted this exact table,
        else a bounded census, count and ratio thresholds) is cheap and comes
        first; the signature
        probe (an AcroForm walk) is paid only when the census says compact.
        Encrypted files are skipped before anything else (``tobytes`` would
        emit a decrypted document, as for the repair round trip).

        The result is a memory-backed document (``doc.name == ""``), exactly
        the shape the xref repair and a snapshot undo leave: incremental saves
        are off for the session and every save is the staged full rewrite
        (``garbage=1``, numbering kept), which is also how the compact layout
        reaches the file.  The file on disk is not touched here and the
        session is not dirty: a file opened and never saved keeps its slots.

        On failure the open still succeeds with an uncompacted document.
        ``tobytes(garbage>=2)`` renumbers the SOURCE handle in place, so a
        file-backed handle is replaced by a fresh one (its table no longer
        matches the file; an incremental save from it would corrupt the file).
        """
        if self._doc_is_encrypted(doc):
            return doc
        try:
            file_size = int(src_path.stat().st_size)
        except OSError:
            return doc
        verdict = xref_compaction.open_compaction_verdict(doc, file_size, walk)
        if not verdict.compact:
            return doc
        if document_has_a_signed_signature(doc):
            logger.info(
                "開檔偵測到大量 free xref 項目（%d / %d），但文件已簽署，不壓實",
                verdict.free_slots,
                verdict.total_slots,
            )
            return doc
        try:
            compacted = xref_compaction.compact_in_memory(doc)
        except Exception as exc:  # noqa: BLE001 - never let compaction break open
            logger.warning(
                "開檔壓實 xref 表失敗，沿用未壓實的文件: %s", self._safe_exc_message(exc)
            )
            if not doc.name:
                return doc  # in memory already (repaired): consistent as renumbered
            try:
                doc.close()
            except Exception:
                pass
            fresh = fitz.open(str(src_path))
            # The fresh handle has not met any lazy damage the walk found on the
            # old one; walk it again so the repair still happens at open.
            self._read_every_object_at_open(fresh, src_path)
            return fresh
        try:
            doc.close()
        except Exception:
            pass
        logger.info(
            "開檔偵測到大量 free xref 項目（%d / %d），已於記憶體中壓實 xref 表（%d -> %d）",
            verdict.free_slots,
            verdict.total_slots,
            verdict.total_slots + 1,
            int(compacted.xref_length()),
        )
        return compacted

    def open_pdf(
        self,
        path: str,
        password: str | None = None,
        append: bool = False,
        before_activate: Callable[[], None] | None = None,
    ) -> str:
        """
        開啟 PDF 檔案並建立文字塊索引。

        Args:
            path: PDF 檔案路徑
            password: 可選密碼（支援 user password 與 owner/permission password）。
                      PyMuPDF authenticate() 會自動嘗試兩種類型：
                        回傳 2 = user password 認證成功（可讀取內容）
                        回傳 4 = owner password 認證成功（可讀取並修改權限）
                        回傳 6 = 兩者皆成功
            before_activate: 可選回呼。僅在檔案已通過全部驗證（存在、大小、密碼、
                      頁數、非 0 頁）、即將新增或切換 session 的那一刻呼叫一次，
                      此時舊的 active session 仍然有效。供呼叫端把「換 session 前的
                      收尾」（結束行內編輯器、取消背景讀取）延到真的要換之後才做：
                      開檔失敗或取消密碼框時 session 不變，不應丟掉使用者的工作
                      （F11-OPEN-4）。回呼丟出例外時開檔中止，文件會被關閉。
        """
        logger.debug(f"嘗試開啟PDF: {path} (append={append})")
        # Deny-write share lock on the file (Windows; OD-FS1-LOCK), taken BEFORE
        # MuPDF parses it so the bytes parsed and fingerprinted are the bytes
        # protected.  Released below unless a session adopts it.
        file_lock: file_share_lock.FileShareLock | None = None
        lock_adopted = False
        try:
            # 規範化路徑
            src_path = Path(path).resolve()
            canonical_path = self._canonicalize_path(str(src_path))
            if not src_path.exists():
                logger.error(f"原始檔案不存在: {path}")
                raise FileNotFoundError(f"原始檔案不存在: {path}")
            if not src_path.is_file():
                logger.error(f"路徑不是有效檔案: {path}")
                raise ValueError(f"路徑不是有效檔案: {path}")
            # Reject an over-large file before parsing or touching existing sessions.
            _guard_before_open(src_path)
            existing_id = self._path_to_session_id.get(canonical_path)
            if append and existing_id:
                if before_activate is not None:
                    before_activate()
                self.activate_session(existing_id)
                return existing_id
            # 直接從原始路徑開啟（以便存檔時可選用增量更新）
            # 注意：append=False（取代全部 session）的 close_all_sessions() 必須等到
            # 新文件通過全部驗證之後才執行，見下方 before_activate 之後（F11-OPEN-5）。
            file_lock = file_share_lock.acquire(src_path)
            doc = fitz.open(str(src_path))
            auth_level: int | None = None
            try:
                # 若 PDF 需要密碼，嘗試認證（支援 user 與 owner password）
                if doc.needs_pass:
                    if password is None:
                        raise PdfPasswordRequiredError("document closed or encrypted — 需要密碼")
                    auth_result = doc.authenticate(password)
                    if auth_result == 0:
                        raise PdfPasswordRejectedError(
                            f"PDF 密碼驗證失敗（authenticate 回傳 0）: {path}"
                        )
                    # Retain the auth class (2=user/4=owner/6=both) so the optimize pipeline
                    # preserves the source role rather than promoting a user to owner (R5-02).
                    auth_level = int(auth_result)
                    # auth_result: 2=user, 4=owner, 6=both — 均允許繼續
                    logger.debug(
                        f"PDF 密碼驗證成功 (auth_level={auth_result}，"
                        f"2=user/4=owner/6=both): {src_path}"
                    )

                # Cap page count once the document is readable (after any auth).
                if doc.page_count > _MAX_PAGES:
                    raise ValueError(f"PDF exceeds page limit ({_MAX_PAGES} pages)")

                # 部分壞損 PDF（例如 /Prev 形成迴圈）會被 MuPDF 接受但頁數為 0，
                # 而其他讀取器仍能讀到全部頁面。絕不以空白頁替代：該空白文件之後
                # 一次編輯 + Ctrl+S 就會覆寫原檔（H10-3，無聲遺失內容）。改為拒絕開啟，
                # 原檔維持原樣。密碼重試只看例外型別（PdfPasswordError），與訊息文字無關。
                if len(doc) == 0:
                    logger.warning("PDF 頁數為 0，拒絕開啟（不使用空白頁替代）: %s", src_path)
                    raise RuntimeError(_ZERO_PAGE_MESSAGE.format(path=src_path))

                # 自動修復：MuPDF 開檔時會重建損毀的 XREF 表並標記 is_repaired。
                # 此處於記憶體中以 garbage collection round-trip 重建乾淨的 xref，
                # 讓後續儲存不會沿用損毀結構。健康檔案僅讀取一個旗標、不受影響。
                #
                # 但加密檔案除外：tobytes() 會輸出「已解密」的內容，round-trip 會默默
                # 移除密碼/權限保護。加密又損毀的檔案維持 MuPDF 修復後的（仍加密的）
                # 文件即可——之後的完整儲存（encryption=KEEP）會寫出乾淨的 xref 並保留
                # 加密。偵測訊號用 metadata 的加密字串（驗證後仍存在，且涵蓋 owner-only）。
                # 開檔壓實（round 8 LS-3）：非安全模式的完整儲存使用 garbage=1 以保留
                # xref 編號（頁面快照 undo 在存檔後仍可還原），因此每次 編輯 -> 復原 ->
                # 儲存 都在檔案裡留下 free xref 項目且跨工作階段無限成長。此時尚無任何
                # undo 歷史，於記憶體中以 garbage=2 round-trip 壓實即可；磁碟上的檔案
                # 維持原樣直到下次真正儲存。簽署與加密檔案一律跳過。放在修復步驟之前：
                # 普查走訪會載入物件，延遲損毀的檔案可能在此時才被 MuPDF 修復
                # （is_repaired 翻為 True），下方的修復 round-trip 便能接手；已壓實的
                # 文件本身就是乾淨的，不需再修復一次。
                # 開檔讀取全部物件（OD-FS1-READALL）：MuPDF 對「延遲載入」物件的 xref
                # 損毀，只在第一次載入該物件時才發現並修復；若那一刻是儲存，修復會
                # 丟掉記憶體中的所有編輯。於此（尚無任何編輯）把每個物件讀一次，
                # 修復便發生在開檔、由下方的修復 round-trip 接手。上限
                # MAX_READ_ALL_SLOTS（約 1 秒）；同一趟的 free 計數供壓實判斷重用。
                walk = self._read_every_object_at_open(doc, src_path)
                doc = self._compact_doc_xref_in_memory(doc, src_path, walk)

                if self._doc_needs_xref_repair(doc) and not self._doc_is_encrypted(doc):
                    doc = self._repair_doc_xref_in_memory(doc)

                logger.debug(f"成功開啟PDF: {src_path}")
                if before_activate is not None:
                    # Validated: the session really changes from here on.
                    before_activate()
                if not append:
                    # Replace-open: only now, with the new document fully validated
                    # (parse, auth, limits, non-empty, before_activate), may the old
                    # sessions go. A failed open must keep them (F11-OPEN-5).
                    self.close_all_sessions()
            except BaseException:
                # Any refusal past fitz.open must not leak the parsed handle; no
                # session has been touched yet, so existing sessions stay intact.
                try:
                    doc.close()
                except Exception:
                    pass
                raise

            session_id = str(uuid.uuid4())
            session = DocumentSession(
                session_id=session_id,
                canonical_path=canonical_path,
                display_name=src_path.name,
                original_path=str(src_path),
                doc=doc,
                # Kept in-memory so a save that preserves encryption can
                # re-authenticate the reopened handle (see _reopen_doc_after_save).
                password=password,
                auth_level=auth_level,
                # File-backed only: a repaired / compacted / in-memory doc never
                # saves incrementally (``name == "pdf"`` is a stream, not a file).
                persisted_xref_length=(
                    int(doc.xref_length()) if self._backing_file(doc) is not None else None
                ),
                file_locks=[file_lock],
            )
            lock_adopted = True
            self._record_disk_fingerprint(session, src_path)
            self._sessions_by_id[session_id] = session
            self._session_ids.append(session_id)
            self._path_to_session_id[canonical_path] = session_id
            self._active_session_id = session_id
            self.tools.on_session_open(session_id, doc)

            # 文字方塊索引改由 Controller 分批建立（方向 B），開檔不阻塞
            # self.block_manager.build_index(self.doc)
            return session_id
        except PermissionError as e:
            logger.error(f"無權限存取檔案: {e!s}")
            raise PermissionError(f"無權限存取檔案: {e!s}")
        except PdfPasswordError as e:
            # Keep the type: the controller's password retry loop keys on it.
            logger.info(f"開啟PDF需要有效密碼: {e!s}")
            raise type(e)(f"開啟PDF失敗: {e!s}") from e
        except Exception as e:
            logger.error(f"開啟PDF失敗: {e!s}")
            raise RuntimeError(f"開啟PDF失敗: {e!s}")
        finally:
            # A refused / failed open must not leave the file locked.
            if file_lock is not None and not lock_adopted:
                file_lock.release()

    def import_session_transfer(self, payload) -> str:
        """Adopt a session detached from another window (F11-OPEN-1).

        ``payload.snapshot_bytes`` comes from ``capture_session_transfer_bytes``:
        it KEEPS the source encryption, so an encrypted source opens locked here
        and is unlocked with the payload password.  The session must stay
        encrypted -- ``_doc_is_encrypted`` and every ``encryption=KEEP`` save in
        the new window depend on it -- so a locked snapshot that cannot be
        authenticated is refused instead of becoming a dead session.
        """
        snapshot_bytes = bytes(payload.snapshot_bytes)
        doc = fitz.open(stream=snapshot_bytes, filetype="pdf")
        auth_level = payload.auth_level
        try:
            # Read on the fresh, unauthenticated handle only (R9 M9-1).
            if doc.needs_pass:
                password = payload.password
                auth_result = 0 if password is None else doc.authenticate(password)
                if auth_result == 0:
                    raise RuntimeError("分離視窗的加密文件重新驗證密碼失敗")
                auth_level = int(auth_result)
            if len(doc) == 0:
                raise ValueError("transferred PDF must contain at least one page")
        except BaseException:
            doc.close()
            raise
        session_id = str(uuid.uuid4())
        source_path = str(payload.source_path or "")
        canonical_path = (
            self._canonicalize_path(source_path)
            if source_path
            else f"detached:{session_id}"
        )
        session = DocumentSession(
            session_id=session_id,
            canonical_path=canonical_path,
            display_name=str(payload.display_name or "未命名.pdf"),
            original_path=source_path,
            saved_path=str(payload.saved_path) if payload.saved_path else None,
            doc=doc,
            password=payload.password,
            auth_level=auth_level,
            transferred_dirty=bool(payload.dirty),
            # The snapshot carries the half-rewritten page, so the damage
            # travels with it (S13-DLG5-DAMAGED); a hand-built payload has none.
            damaged=bool(getattr(payload, "damaged", False)),
            # ...and so do the files it protects: after a Save As the payload's
            # source path is the new file, not the original (F14-DMG-1).
            damaged_protected_paths=frozenset(
                str(p) for p in (getattr(payload, "damaged_protected_paths", ()) or ())
            ),
        )
        # The baseline is the SENDER's (F11-OPEN-2): measuring the file here
        # would take whatever a foreign writer did since the sender opened or
        # last wrote it as the session's own, and the window the user dragged
        # the tab into would overwrite what the original window refuses to.
        # A payload without one (hand-built, or the sender had none) gets none.
        fingerprint = payload.disk_fingerprint
        if fingerprint is not None and payload.disk_fingerprint_path:
            size, mtime_ns, digest = fingerprint
            session.disk_fingerprint = (int(size), int(mtime_ns), str(digest))
            session.disk_fingerprint_path = str(payload.disk_fingerprint_path)
        # The new window owns the file now: lock it (the sender's window drops
        # its claim when it closes the tab; one OS handle per process).
        self._sync_session_file_locks(session)
        self._sessions_by_id[session_id] = session
        self._session_ids.append(session_id)
        if source_path:
            self._path_to_session_id[canonical_path] = session_id
        self._active_session_id = session_id
        self.tools.on_session_open(session_id, doc)
        return session_id

    def ensure_page_index_built(self, page_num: int) -> None:
        """
        Ensure the requested page is immediately edit/search-ready.

        Contract:
        - Controller and tools may call this before hit-testing / search / edit flows.
        - We rebuild if the cache is missing OR marked stale (stale is produced by structural ops that shift
          page numbers without eagerly rebuilding the entire document).

        Notes:
        - `page_num` is 1-based to match public UI-facing APIs.
        """
        page_idx = page_num - 1
        if page_idx < 0 or not self.doc or page_idx >= len(self.doc):
            return
        if self.block_manager.page_state(page_idx) in {"missing", "stale"}:
            self.block_manager.rebuild_page(page_idx, self.doc)

    def refresh_structural_indexes(self, affected_pages: list[int]) -> None:
        """
        Refresh page text indices after a document snapshot restore (undo/redo) that may have changed content.

        Why it clears everything:
        - Snapshot restore replaces the whole document bytes, so any cached page indices could be wrong even
          if page counts match.

        Why it doesn't rebuild everything:
        - Full-document rebuild is CPU-heavy and can stall the UI for large PDFs. We rebuild only the pages
          that the controller knows are immediately relevant (`affected_pages`). Other pages are rebuilt
          lazily through `ensure_page_index_built(...)` or background draining.

        `affected_pages` is expected to be 1-based (same as public APIs).
        """
        if not self.doc:
            return
        # Snapshot restore invalidates the old cache wholesale, so rebuild only the hot pages now.
        self.block_manager.clear()
        for page_num in sorted({page for page in affected_pages if 1 <= page <= len(self.doc)}):
            self.block_manager.rebuild_page(page_num - 1, self.doc)

    def _insert_rotate_for_htmlbox(self, rotation: int) -> int:
        """
        insert_htmlbox(rotate=...) 的旋轉方向與 PDF 文字 dir 相反（順時針 vs 逆時針），
        垂直文字若直接傳 90 會變成 180° 反轉。改傳 (360 - rotation) % 360 以對齊原檔方向。
        """
        return (360 - rotation) % 360

    def _vertical_html_rect(self, base_rect: fitz.Rect, text: str, size: float, font_name: str, page_rect: fitz.Rect, anchor_right: bool = True) -> fitz.Rect:
        """
        垂直文字：估算「需要的 x 方向寬度（列數 × 行高）」。
        anchor_right=True（預設）：固定右緣 x1，向左擴展（x0 往左）→ 左側文字需左移。
        anchor_right=False：固定左緣 x0，向右擴展（x1 往右）→ 右側文字需右移。
        不超出頁面邊界。
        """
        line_gap = 1.1
        try:
            font_obj = fitz.Font(font_name)
            line_height = max(1.0, (font_obj.ascender - font_obj.descender) * size * line_gap)
        except Exception:
            line_height = max(1.0, size * line_gap)
        rect_height = max(base_rect.height, line_height)
        chars_per_col = max(1, int(rect_height / line_height))
        logical_cols = 1 + text.count('\n')
        chars_no_nl = len(text.replace('\n', ''))
        wrap_cols = math.ceil(max(1, chars_no_nl) / chars_per_col) if chars_no_nl else 0
        cols = max(logical_cols, wrap_cols)
        needed_width = max(base_rect.width, cols * line_height)
        max_width = max(1.0, page_rect.width * 0.98)
        needed_width = min(needed_width, max_width)

        if anchor_right:
            # 固定 x1，向左擴展
            new_x1 = base_rect.x1
            new_x0 = new_x1 - needed_width
            if new_x0 < page_rect.x0:
                new_x0 = page_rect.x0
                new_x1 = min(new_x0 + needed_width, page_rect.x1)
        else:
            # 固定 x0，向右擴展
            new_x0 = base_rect.x0
            new_x1 = new_x0 + needed_width
            if new_x1 > page_rect.x1:
                new_x1 = page_rect.x1
                new_x0 = max(new_x1 - needed_width, page_rect.x0)
        # 夾緊 y 於頁面內，避免超出頁面
        y0 = max(base_rect.y0, page_rect.y0)
        y1 = min(base_rect.y1, page_rect.y1)
        if y0 >= y1:
            y1 = y0 + max(1.0, base_rect.height)
        return fitz.Rect(new_x0, y0, new_x1, min(y1, page_rect.y1))

    def _visual_rect_to_unrotated_rect(self, page: fitz.Page, visual_rect: fitz.Rect) -> fitz.Rect:
        """Convert a visual-space page rect to unrotated page coordinates."""
        # ``model.geometry`` is the one conversion: ``page.derotation_matrix``
        # drops ``/UserUnit`` on a rotated page (F15-G1-UU-ROT).
        return visual_to_unrotated_rect(page, visual_rect)

    def _unrotated_page_rect(self, page: fitz.Page) -> fitz.Rect:
        """Page bounds in unrotated page space (the space of ``_visual_rect_to_unrotated_rect``).

        Delegates to ``model.geometry.unrotated_page_rect``. Never use raw
        ``page.cropbox``/``page.mediabox`` here: PyMuPDF reports ``cropbox``
        MediaBox-relative and y-flipped in raw PDF units (no ``/UserUnit``), so
        on a CropBox-inside-MediaBox, offset-MediaBox or ``/UserUnit`` page it
        is not page space and clamping against it loses or shifts geometry.
        """
        return unrotated_page_rect(page)

    def _y_overlaps(self, rect_a: fitz.Rect, rect_b: fitz.Rect) -> bool:
        return not (rect_a.y1 <= rect_b.y0 or rect_b.y1 <= rect_a.y0)

    def _shift_rect_left(self, rect: fitz.Rect, target_right_x0: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形左移，使右緣不超過 target_right_x0 - min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x1 = min(rect.x1, target_right_x0 - min_gap)
        shift = rect.x1 - new_x1
        if shift <= 0:
            return rect
        new_x0 = rect.x0 - shift
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    def _shift_rect_right(self, rect: fitz.Rect, target_left_x1: float, min_gap: float, page_rect: fitz.Rect) -> fitz.Rect:
        """將矩形右移，使左緣至少為 target_left_x1 + min_gap。若會移出頁面則不移動。"""
        width = rect.width
        new_x0 = max(rect.x0, target_left_x1 + min_gap)
        if new_x0 <= rect.x0:
            return rect
        new_x1 = new_x0 + width
        if new_x0 < page_rect.x0 or new_x1 > page_rect.x1:
            return rect
        return fitz.Rect(new_x0, rect.y0, new_x1, rect.y1)

    @staticmethod
    def _starts_bullet_item(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        if stripped.startswith(_BULLET_PREFIXES):
            return True
        return bool(_RE_NUMBERED_BULLET.match(stripped))

    def _compose_block_text_for_hit(self, block: dict) -> str:
        """
        Build editable text for fallback point-hit extraction.
        Wrapped lines are joined with spaces, while bullets / large visual gaps keep line breaks.
        """
        lines = block.get("lines", []) or []
        if not lines:
            return ""

        line_texts: list[str] = []
        line_boxes: list[fitz.Rect] = []
        for line in lines:
            parts = [
                (span.get("text", "") or "").strip()
                for span in (line.get("spans", []) or [])
                if (span.get("text", "") or "").strip()
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
            prev_box = line_boxes[idx - 1]
            curr_box = line_boxes[idx]
            prev_height = max(prev_box.height, 0.0)
            gap = curr_box.y0 - prev_box.y1
            if self._starts_bullet_item(line_text) or (prev_height > 0 and gap > prev_height * 0.5):
                composed.append("\n")
            elif composed and not composed[-1].endswith((" ", "\n", "-")):
                composed.append(" ")
            composed.append(line_text)
        return "".join(composed).strip()

    def _resolve_paragraph_candidate(
        self,
        page_idx: int,
        probe_rect: fitz.Rect,
        original_text: str | None,
        preferred_run_id: str | None = None,
    ) -> EditableParagraph | None:
        """Resolve the best paragraph target by geometry + text similarity.

        This is used to recover from stale run IDs after page rebuilds.
        """
        paragraphs = self.block_manager.get_paragraphs(page_idx)
        if not paragraphs:
            return None

        expanded = fitz.Rect(
            probe_rect.x0 - 1.0,
            probe_rect.y0 - 1.0,
            probe_rect.x1 + 1.0,
            probe_rect.y1 + 1.0,
        )
        candidates = [
            para
            for para in paragraphs
            if fitz.Rect(para.bbox).intersects(expanded)
        ]
        if not candidates:
            candidates = paragraphs

        has_probe_text = bool(normalize_text(original_text or ""))
        best_para: EditableParagraph | None = None
        best_key: tuple[float, ...] | None = None
        key: tuple[float, ...]

        for para in candidates:
            para_rect = fitz.Rect(para.bbox)
            overlap_score = rect_overlap_ratio(para_rect, probe_rect)
            text_score = (
                normalized_similarity(original_text or "", para.text)
                if has_probe_text
                else 0.0
            )
            preferred_score = 1.0 if preferred_run_id and preferred_run_id in para.run_ids else 0.0

            if has_probe_text:
                key = (
                    round(text_score, 6),
                    round(overlap_score, 6),
                    preferred_score,
                    -abs(para_rect.y0 - probe_rect.y0),
                )
            else:
                key = (
                    round(overlap_score, 6),
                    preferred_score,
                    -abs(para_rect.y0 - probe_rect.y0),
                )

            if best_key is None or key > best_key:
                best_key = key
                best_para = para

        return best_para

    def _text_fits_in_rect(self, page: fitz.Page, rect: fitz.Rect, expected_text: str) -> bool:
        extracted = page.get_text("text", clip=rect)
        return normalize_text(expected_text) in normalize_text(extracted)

    def _binary_shrink_height(self, page: fitz.Page, rect: fitz.Rect, expected_text: str, iterations: int = 7, padding: float = 4.0, min_y1: float | None = None, *, grow_up: bool = False, max_y0: float | None = None, far_limit: float | None = None) -> fitz.Rect:
        """
        先用全頁高度 rect 渲染，再二分縮減 y1 找到最小可用高度。
        y0 固定，最後加 padding。
        [優化 11] 早期結束：若範圍已足夠小則提前返回，減少不必要的 get_text 呼叫

        ``grow_up=True``（向上閱讀的文字，從 rect 底端起排）：鏡像，y1 固定、
        縮減 y0（``max_y0`` 為 y0 的下限位置上限，即原文字框頂端）。

        ``far_limit``：遠端邊緣的硬限制（向下時 y1 的上限；向上時 y0 的下限），
        即同一欄下一個未編輯 run 的邊緣（F13-VF-4b）；搜尋與 padding 都不越過它。
        """
        page_rect = page.rect
        if grow_up:
            floor_y0 = page_rect.y0 if far_limit is None else max(page_rect.y0, far_limit)
            near = max(rect.y0 if max_y0 is None else min(rect.y1, max_y0), floor_y0)
            low = floor_y0
            high = near
            best_y0 = low
            for _ in range(iterations):
                if high - low < 2.0:
                    break
                mid = (low + high) / 2.0
                test_rect = fitz.Rect(rect.x0, mid, rect.x1, rect.y1)
                if self._text_fits_in_rect(page, test_rect, expected_text):
                    best_y0 = mid
                    low = mid
                else:
                    high = mid
            best_y0 = max(floor_y0, best_y0 - padding)
            return fitz.Rect(rect.x0, best_y0, rect.x1, rect.y1)
        low = rect.y1 if min_y1 is None else max(rect.y0, min_y1)
        high = page_rect.y1 if far_limit is None else min(page_rect.y1, far_limit)
        if low > high:
            low = high
        best_y1 = high

        for _ in range(iterations):
            if high - low < 2.0:  # [優化 11] 範圍小於 2pt 時提前結束
                break
            mid = (low + high) / 2.0
            test_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, mid)
            if self._text_fits_in_rect(page, test_rect, expected_text):
                best_y1 = mid
                high = mid
            else:
                low = mid

        best_y1 = min(page_rect.y1 if far_limit is None else far_limit, best_y1 + padding)
        return fitz.Rect(rect.x0, rect.y0, rect.x1, best_y1)

    def _calc_vertical_padding(self, size: float) -> float:
        return max(4.0, float(size) * 0.8) # 0.2 還是會被裁切到，我先試 0.8 是可行的，待有需要再測試能否進一步減少

    def close(self):
        logger.debug("關閉PDF並清理臨時目錄")
        self.close_all_sessions()
        self._legacy_doc = None
        self._legacy_tiered_commit_engine = None
        self._legacy_original_path = None
        self._legacy_saved_path = None
        legacy_block_manager = getattr(self, "_legacy_block_manager", None)
        if legacy_block_manager is not None:
            legacy_block_manager.clear()
        legacy_command_manager = getattr(self, "_legacy_command_manager", None)
        if legacy_command_manager is not None:
            legacy_command_manager.clear()
        legacy_pending_edits = getattr(self, "_legacy_pending_edits", None)
        if isinstance(legacy_pending_edits, list):
            legacy_pending_edits.clear()
        self._legacy_edit_count = 0
        self._sweep_retired_live_copies(collect=True)
        if getattr(self, "temp_dir", None):
            try:
                self.temp_dir.cleanup()
            except OSError:
                # a lingering page object may still hold a temp file open
                gc.collect()
                try:
                    self.temp_dir.cleanup()
                except OSError as exc:
                    logger.warning("臨時目錄未能完全清理: %s", exc)
            logger.debug("臨時目錄已清理")
            self.temp_dir = None

    def get_toc(self) -> list[list[object]]:
        if not self.doc:
            return []
        return [
            [int(level), str(title), int(page_num)]
            for level, title, page_num, *_rest in self.doc.get_toc(simple=True)
        ]

    def get_toc_rows(self) -> list[list[object]]:
        """``[level, title, page, key]`` rows for the bookmark panel.

        ``key`` is an opaque outline-item identity (its object xref) that
        ``set_toc`` uses to edit that item in place, so a rename or re-page
        keeps its target position, colour, bold/italic, collapse state and
        action (F16-NAV-1).  ``page`` is ``-1`` for an item without a page
        target (URI, Launch, ...).  ``key`` is ``None`` when the outline is
        malformed and its items cannot be identified.
        """
        if not self.doc:
            return []
        items = outline_ops.outline_items(self.doc)
        if items is None:
            return [[*row, None] for row in self.get_toc()]
        return [[item.level, item.title, item.page, item.xref] for item in items]

    def set_toc(self, entries: list[list[object]]) -> bool:
        """Make the outline match ``entries`` (``[level, title, page(, key)]``).

        A row with the ``key`` of a current item (from ``get_toc_rows``) edits
        that item in place: only a changed title or page is written, and a
        page of ``-1`` keeps an item that has no page target as it is.  A row
        without a key is a new bookmark, except that a wholly keyless list with
        the current length and levels (``get_toc()`` with edited titles or
        pages) is paired with the current items by position.  Current items
        absent from ``entries`` are removed.  The outline is never regenerated
        from simple rows (F16-NAV-1).
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        if not isinstance(entries, list):
            raise TypeError("TOC entries must be a list")
        parsed: list[tuple[int, str, int, object]] = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                raise TypeError("each TOC entry must contain level, title, and page")
            level, title, page_num = entry[:3]
            if isinstance(level, bool) or not isinstance(level, int) or level < 1:
                raise ValueError("TOC level must be a positive integer")
            if not parsed and level != 1:
                raise ValueError("the first TOC level must be 1")
            if parsed and level > parsed[-1][0] + 1:
                raise ValueError("TOC levels may increase by at most one")
            title_text = str(title).strip()
            if not title_text:
                raise ValueError("TOC title must not be empty")
            if isinstance(page_num, bool) or not isinstance(page_num, int):
                raise TypeError("TOC page must be an integer")
            parsed.append((level, title_text, page_num, entry[3] if len(entry) > 3 else None))

        items = outline_ops.outline_items(self.doc)
        current = items or []
        by_key = {item.xref: item for item in current}
        if (
            current
            and len(parsed) == len(current)
            and all(key is None for *_row, key in parsed)
            and all(row[0] == item.level for row, item in zip(parsed, current))
        ):
            parsed = [(*row[:3], item.xref) for row, item in zip(parsed, current)]
        rows: list[outline_ops.OutlineRow] = []
        used_keys: set[int] = set()
        page_count = len(self.doc)
        for level, title_text, page_num, key in parsed:
            if key is not None and (
                isinstance(key, bool)
                or not isinstance(key, int)
                or key not in by_key
                or key in used_keys
            ):
                raise ValueError("TOC entry key does not name a current bookmark")
            if key is not None:
                used_keys.add(key)
            keeps_non_page_target = (
                page_num == -1 and key is not None and by_key[key].page == -1
            )
            if not keeps_non_page_target and (page_num < 1 or page_num > page_count):
                raise ValueError("TOC page is out of range")
            rows.append(outline_ops.OutlineRow(level, title_text, page_num, key))
        if items is None:
            # Unpairable (malformed) outline: no item identity to keep.
            if [[row.level, row.title, row.page] for row in rows] == self.get_toc():
                return False
            self.doc.set_toc([])
            current = []
        if not outline_ops.apply_outline_rows(self.doc, rows, current):
            return False
        self.secure_save_required = True
        return True

    def _capture_outline(self) -> list[outline_ops.OutlineItem] | None:
        """Outline items before a structural page operation (see ``_follow_outline``)."""
        return outline_ops.outline_items(self.doc) if self.doc else []

    def _follow_outline(
        self,
        mapper: Callable[[int], int],
        before: list[outline_ops.OutlineItem] | None,
    ) -> None:
        """Repair only the outline items whose target did not follow its page.

        Outline items reference page objects, so after an insert or move every
        item already resolves to ``mapper(old_page)`` and nothing is written.
        Items whose page was deleted are pointed at ``mapper``'s survivor with
        their colour restored; items without a page target are never touched
        (F16-NAV-1).
        """
        if self.doc is not None:
            outline_ops.follow_page_targets(self.doc, before, mapper)

    def delete_pages(
        self,
        pages: list[int],
        *,
        transaction_snapshot: bytes | None = None,
    ) -> list[int]:
        """
        Delete pages (1-based) and return the actual deleted pages (1-based, sorted).

        Source of truth rule:
        - Controller must use this return value for UI messaging and SnapshotCommand metadata. The input can
          be dirty (out-of-range, duplicates, non-int), and the model decides the actual effect.

        Indexing rule:
        - Do not rebuild all pages. Keep unaffected cache entries, mark shifted survivors as stale, and make
          a nearby anchor page immediately usable for compatibility with existing callers.
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        max_page = len(self.doc)
        normalized: list[int] = []
        for value in pages or []:
            if isinstance(value, bool):
                continue
            try:
                page_num = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page_num <= max_page:
                normalized.append(page_num)

        actual_deleted_pages = sorted(set(normalized))
        if not actual_deleted_pages:
            return []
        deleted_page_idxs = [page_num - 1 for page_num in actual_deleted_pages]
        deleted_set = set(actual_deleted_pages)
        surviving_pages = [page for page in range(1, max_page + 1) if page not in deleted_set]
        delete_all = len(actual_deleted_pages) == max_page
        placeholder_size = self.doc[0].rect if delete_all else None
        outline_before = self._capture_outline()
        # Object numbers of the pages that go away, with their 1-based page.
        removed_page_xrefs = {self.doc.page_xref(idx): idx + 1 for idx in deleted_page_idxs}

        def _map_deleted_toc_page(page_num: int) -> int:
            if delete_all:
                return 1
            target = page_num
            if target in deleted_set:
                target = next(
                    (page for page in surviving_pages if page > target),
                    surviving_pages[-1],
                )
            return target - sum(1 for deleted in actual_deleted_pages if deleted < target)

        before = transaction_snapshot if transaction_snapshot is not None else self._capture_doc_snapshot()
        pending_before = list(self.pending_edits)
        edit_count_before = self.edit_count
        secure_before = self.secure_save_required
        placeholder_before = self.blank_placeholder_active
        try:
            for page_num in sorted(actual_deleted_pages, reverse=True):
                self.doc.delete_page(page_num - 1)
            # PyMuPDF drops the explicit links into the deleted pages; the named
            # destinations, the links and bookmarks that use them and /OpenAction
            # would keep pointing at (and keeping alive) the deleted page objects
            # (F16-NAV-1a).  Before the placeholder page is created.
            dropped = page_refs.repoint_page_references(self.doc, dict.fromkeys(removed_page_xrefs))
            if delete_all:
                # Keep a real, blank PDF page: empty fitz.Documents make existing
                # render, navigation, and persistence paths fail their no-doc checks.
                assert placeholder_size is not None
                self.doc.new_page(width=placeholder_size.width, height=placeholder_size.height)
                self._set_blank_placeholder_active(True)
            else:
                self._set_blank_placeholder_active(False)
            # The survivors keep their pages' watermarks / bookkeeping; the placeholder of a
            # delete-all is a new page (F17-COH-3).
            self._pages_restructured(surviving_pages or [None], old_count=max_page)
            # Preserve unaffected cache entries; shifted survivors become stale until demanded.
            self.block_manager.shift_after_delete(deleted_page_idxs)
            if deleted_page_idxs:
                # Keep the page nearest the deletion immediately usable for existing callers.
                anchor_idx = 0 if delete_all else min(deleted_page_idxs[0], len(self.doc) - 1)
                if anchor_idx >= 0:
                    self.block_manager.rebuild_page(anchor_idx, self.doc)
            self._follow_outline(
                _map_deleted_toc_page,
                outline_before,
            )
            outline_ops.follow_dropped_names(
                self.doc,
                {
                    name: removed_page_xrefs[page_xref]
                    for name, page_xref in dropped.dropped_name_pages.items()
                    if page_xref in removed_page_xrefs
                },
                _map_deleted_toc_page,
            )
        except Exception:
            self._restore_doc_after_failed_mutation(before)
            self.pending_edits = pending_before
            self.edit_count = edit_count_before
            self.secure_save_required = secure_before
            self._set_blank_placeholder_active(placeholder_before)
            self.block_manager.build_index(self.doc)
            raise
        self.secure_save_required = True
        return actual_deleted_pages

    def move_page(self, source_index: int, destination_index: int) -> list[int]:
        """Move one page to a final 0-based destination and return its affected range.

        The public destination is the page's final index after the move.  PyMuPDF
        instead interprets a forward destination as the insertion position before
        removing the source page, so that native call must be offset by one.
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        if (
            isinstance(source_index, bool)
            or isinstance(destination_index, bool)
            or not isinstance(source_index, int)
            or not isinstance(destination_index, int)
        ):
            return []

        page_count = len(self.doc)
        if (
            source_index < 0
            or destination_index < 0
            or source_index >= page_count
            or destination_index >= page_count
            or source_index == destination_index
        ):
            return []

        affected_start = min(source_index, destination_index)
        affected_end = max(source_index, destination_index)
        outline_before = self._capture_outline()

        def _map_moved_toc_page(page_num: int) -> int:
            page_idx = page_num - 1
            if page_idx == source_index:
                return destination_index + 1
            if source_index < destination_index and source_index < page_idx <= destination_index:
                return page_idx
            if destination_index < source_index and destination_index <= page_idx < source_index:
                return page_idx + 2
            return page_num

        before = self._capture_doc_snapshot()
        try:
            if destination_index == page_count - 1 and source_index < destination_index:
                native_destination = -1
            elif source_index < destination_index:
                native_destination = destination_index + 1
            else:
                native_destination = destination_index
            self.doc.move_page(source_index, native_destination)
            order = list(range(1, page_count + 1))
            order.insert(destination_index, order.pop(source_index))
            self._pages_restructured(order, old_count=page_count)
            self.block_manager.shift_after_move(source_index, destination_index)
            # The destination page is immediately usable; the rest of the moved
            # interval remains stale for the controller's lazy drain.
            self.block_manager.rebuild_page(destination_index, self.doc)
            self._follow_outline(
                _map_moved_toc_page,
                outline_before,
            )
        except Exception:
            self._restore_doc_after_failed_mutation(before)
            self.block_manager.build_index(self.doc)
            raise

        self.secure_save_required = True
        return list(range(affected_start + 1, affected_end + 2))

    def rotate_pages(self, pages: list[int], degrees: int) -> list[int]:
        """
        Rotate pages and return the actual rotated pages (1-based, sorted).

        Controller input can be dirty; model validates and becomes the source of truth for undo metadata.
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        try:
            normalized_degrees = int(degrees) % 360
        except (TypeError, ValueError):
            normalized_degrees = 0
        if normalized_degrees == 0:
            return []

        max_page = len(self.doc)
        normalized: list[int] = []
        for value in pages or []:
            if isinstance(value, bool):
                continue
            try:
                page_num = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page_num <= max_page:
                normalized.append(page_num)

        actual_pages = sorted(set(normalized))
        for page_num in actual_pages:
            page = self.doc[page_num - 1]
            page.set_rotation((page.rotation + normalized_degrees) % 360)
        for page_num in actual_pages:
            self.block_manager.rebuild_page(page_num - 1, self.doc)
        return actual_pages

    @staticmethod
    def _normalize_image_format(fmt: str) -> str:
        value = (fmt or "").lower().lstrip(".")
        if value in ("jpg", "jpeg"):
            return "jpg"
        if value == "png":
            return "png"
        if value in ("tif", "tiff"):
            return "tiff"
        return ""

    def export_pages(
        self,
        pages: list[int],
        output_path: str,
        as_image: bool = False,
        dpi: int = 300,
        image_format: str = "png",
    ):
        # typed bind; callers guarantee an open doc here (export path) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        output_target = Path(output_path)
        base_path = output_target.with_suffix('')
        logger.debug(
            f"匯出頁面: 路徑={output_path}, as_image={as_image}, dpi={dpi}, image_format={image_format}"
        )

        if as_image:
            normalized_format = self._normalize_image_format(image_format)
            if not normalized_format:
                normalized_format = self._normalize_image_format(output_target.suffix)
            if not normalized_format:
                normalized_format = "png"
            raw_suffix = output_target.suffix.lower().lstrip(".")
            # Keep user-typed suffix style for output names (e.g. .tif vs .tiff).
            write_ext = raw_suffix if self._normalize_image_format(raw_suffix) else normalized_format
            dpi_value = max(int(round(float(dpi))), 1)
            scale = dpi_value / 72.0

            for page_num in pages:
                if not (1 <= page_num <= len(doc)):
                    logger.warning(f"匯出影像時略過無效頁碼: {page_num}")
                    continue
                safe_scale = _safe_render_scale(doc[page_num - 1], scale)
                pix = self.get_page_pixmap(page_num, scale=safe_scale)
                # Persist resolution metadata so image "DPI" matches user selection.
                pix.set_dpi(dpi_value, dpi_value)
                if len(pages) == 1:
                    target_path = output_target if output_target.suffix else output_target.with_suffix(f".{write_ext}")
                else:
                    # Multi-page export uses page-number suffix to avoid collisions.
                    target_path = Path(f"{base_path}_p{page_num}.{write_ext}")
                # Stage + replace (LS-2): an export over an existing image must not be
                # truncated by a failed write.  The staging name ends in ``.pdf``, so
                # the format is passed explicitly instead of inferred from the suffix.
                if normalized_format == "tiff":
                    # PyMuPDF Pixmap.save does not support TIFF; use Pillow-backed path.
                    try:
                        def _write_tiff(stage: str, pix: fitz.Pixmap = pix) -> None:
                            pix.pil_save(stage, format="TIFF")

                        write_via_staging(target_path, _write_tiff)
                    except Exception as exc:
                        raise RuntimeError(
                            "匯出 TIFF 失敗，請確認已安裝 Pillow (pip install Pillow)"
                        ) from exc
                else:
                    image_output = "jpeg" if normalized_format == "jpg" else "png"

                    def _write_image(stage: str, pix: fitz.Pixmap = pix, output: str = image_output) -> None:
                        pix.save(stage, output=output)

                    write_via_staging(target_path, _write_image)
                logger.debug(f"匯出影像: 頁面 {page_num} 至 {target_path}")
            return

        new_doc = fitz.open()
        try:
            exported: list[int] = []
            for page_num in pages:
                if 1 <= page_num <= len(doc):
                    exported.append(page_num - 1)
                    logger.debug(f"匯出PDF頁面: {page_num}")
                else:
                    logger.warning(f"匯出PDF時略過無效頁碼: {page_num}")
            # F16-NAV-3: the exported pages keep their bookmarks, labels, named
            # destinations and the links insert_pdf alone drops.
            graft = NavigationGraft(new_doc)
            graft.copy_pages(doc, exported)
            graft.finish()
            # The exported pages carry the session's pending watermark like Save does
            # (F17-COH-4); its page list is renumbered for the exported order.
            self._prepare_derived_document(new_doc, [page_idx + 1 for page_idx in exported])
            self.save_external_document(new_doc, output_path)
        finally:
            new_doc.close()

    def insert_blank_page(self, position: int) -> list[int]:
        """
        Insert one blank page and return the actual inserted page number (1-based).

        Source of truth rule:
        - Controller must use the returned page number (position can be dirty/out-of-range).

        Indexing rule:
        - The inserted page must be immediately editable/search-ready, but the shifted suffix can be marked
          stale and rebuilt lazily.
        
        Args:
            position: 插入位置（1-based），例如 1 表示在第一頁之前，2 表示在第一頁之後
                     如果 position > 總頁數，則插入到最後
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        try:
            pos_value = int(position)
        except (TypeError, ValueError):
            pos_value = 1

        # 獲取當前第一頁的尺寸作為新頁面的尺寸
        if len(self.doc) > 0:
            first_page = self.doc[0]
            page_rect = first_page.rect
            width = page_rect.width
            height = page_rect.height
        else:
            # 如果文件為空，使用標準 A4 尺寸
            width = 595  # A4 width in points
            height = 842  # A4 height in points

        # 轉換為 0-based 索引，並確保不超出範圍
        insert_at = min(pos_value - 1, len(self.doc))
        if insert_at < 0:
            insert_at = 0

        outline_before = self._capture_outline()
        old_count = len(self.doc)
        # 插入空白頁面
        self.doc.new_page(insert_at, width=width, height=height)
        logger.debug(f"在位置 {insert_at + 1} 插入空白頁面，尺寸: {width}x{height}")
        order: list[int | None] = list(range(1, old_count + 1))
        order.insert(insert_at, None)
        self._pages_restructured(order, old_count=old_count)
        # New pages must be editable right away, but later pages can be rebuilt lazily.
        self.block_manager.shift_after_insert(insert_at, 1)
        self.block_manager.rebuild_page(insert_at, self.doc)
        self._follow_outline(
            lambda page_num: page_num + 1 if page_num >= insert_at + 1 else page_num,
            outline_before,
        )
        return [insert_at + 1]

    def insert_pages_from_file(
        self,
        source_file: str,
        source_pages: list[int],
        position: int,
        password: str | None = None,
    ) -> list[int]:
        """
        Insert pages from another PDF and return the actual inserted page numbers (1-based, ascending).

        Source of truth rule:
        - Controller must use the returned positions for SnapshotCommand metadata and UI. `source_pages` and
          `position` can be dirty; the model validates and applies the real operation.

        Indexing rule:
        - Imported pages are rebuilt immediately for edit hit-testing; shifted suffix pages are marked stale
          and rebuilt lazily/background.
        
        Args:
            source_file: 來源PDF檔案路徑
            source_pages: 要插入的來源頁碼列表（1-based）
            position: 插入位置（1-based），例如 1 表示在第一頁之前
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        placeholder_active = self.blank_placeholder_active
        placeholder_snapshot: bytes | None = None
        outline_before = self._capture_outline()
        old_count = len(self.doc)

        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {source_file}")

        try:
            try:
                pos_value = int(position)
            except (TypeError, ValueError):
                pos_value = 1

            # 開啟來源PDF（套用 foreign-doc 資源防護：大小/頁數/加密）
            source_doc = _guard_foreign_doc(source_path, password=password)

            # 轉換為 0-based 索引
            insert_at = min(pos_value - 1, len(self.doc))
            if insert_at < 0:
                insert_at = 0

            max_source = len(source_doc)
            normalized_source: list[int] = []
            for value in source_pages or []:
                if isinstance(value, bool):
                    continue
                try:
                    page_num = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= page_num <= max_source:
                    normalized_source.append(page_num)
                else:
                    logger.warning(f"來源檔案頁碼 {value} 超出範圍（總頁數: {max_source}）")

            # Sort and de-dup BEFORE insertion so invalid pages do not distort positional offsets.
            actual_source_pages = sorted(set(normalized_source))
            if not actual_source_pages:
                return []

            # A placeholder is replaced, rather than retained beside, the first real
            # imported page. It therefore does not count against the document limit.
            existing_page_count = len(self.doc) - int(placeholder_active)
            if existing_page_count + len(actual_source_pages) > _MAX_PAGES:
                source_doc.close()
                raise ValueError(f"Merged document would exceed page limit ({_MAX_PAGES} pages)")

            if placeholder_active:
                placeholder_snapshot = self._capture_doc_snapshot()
                self.doc.delete_page(0)
                self.block_manager.shift_after_delete([0])
                self._set_blank_placeholder_active(False)
                insert_at = 0

            # The graft groups the sorted/deduped pages into contiguous runs (one
            # insert_pdf call each) and re-creates the links insert_pdf drops
            # (LINK_NAMED: named and /Fit-style destinations) and, as in a merge, carries
            # the source's navigation (S17-INSERT-NAV): its bookmarks are appended after
            # this document's own, its names are merged into this document's name tree
            # (a clash is renamed, this document's name wins) and the page labels of the
            # whole document are rebuilt so every label stays on its page.
            inserted_positions: list[int] = []
            graft = NavigationGraft(self.doc, into_existing=True)
            try:
                targets = graft.copy_pages(
                    source_doc, [page_num - 1 for page_num in actual_source_pages], start_at=insert_at
                )
                graft.finish()
                inserted_positions = [target + 1 for target in targets]
                logger.debug(f"從 {source_file} 插入 {len(targets)} 頁到位置 {insert_at + 1}")
            finally:
                source_doc.close()

            if inserted_positions:
                # A placeholder is replaced by the imported pages: nothing of it survives.
                order: list[int | None] = [] if placeholder_active else list(range(1, old_count + 1))
                order[insert_at:insert_at] = [None] * len(inserted_positions)
                self._pages_restructured(order, old_count=old_count)
                # Imported pages are rebuilt immediately; the shifted suffix drains in the background.
                self.block_manager.shift_after_insert(insert_at, len(inserted_positions))
                for page_idx in range(insert_at, insert_at + len(inserted_positions)):
                    self.block_manager.rebuild_page(page_idx, self.doc)
                if placeholder_active:
                    self._follow_outline(lambda _page_num: 1, outline_before)
                else:
                    inserted_count = len(inserted_positions)
                    self._follow_outline(
                        lambda page_num: page_num + inserted_count
                        if page_num >= insert_at + 1
                        else page_num,
                        outline_before,
                    )
            return inserted_positions

        except Exception as e:
            if placeholder_snapshot is not None:
                self._restore_doc_after_failed_mutation(placeholder_snapshot)
                self._set_blank_placeholder_active(True)
                self.refresh_structural_indexes([1])
            logger.error(f"從檔案插入頁面失敗: {e}")
            raise RuntimeError(f"從檔案插入頁面失敗: {e}")

    def open_insert_source(self, path: str, password: str | None = None) -> dict:
        src_path = Path(path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {path}")
        if not src_path.is_file():
            raise ValueError(f"路徑不是有效檔案: {path}")

        doc = _guard_foreign_doc(src_path, password=password)
        try:
            if len(doc) == 0:
                raise RuntimeError(f"無法讀取來源檔案: {path}")
            return {
                "path": str(src_path),
                "display_name": src_path.name,
                "page_count": len(doc),
                "password": password,
            }
        finally:
            doc.close()

    def active_document_is_encrypted(self) -> bool:
        """True when the active document is encrypted on disk (any scheme, owner-only too)."""
        doc = self.doc
        return doc is not None and self._doc_is_encrypted(doc)

    def compose_merged_document(
        self,
        ordered_sources: list[dict],
        *,
        keep_encryption: bool = False,
        bake_watermarks: bool = True,
    ) -> fitz.Document:
        """``compose_merged_document_with_origins`` without the page map."""
        merged, _origins = self.compose_merged_document_with_origins(
            ordered_sources, keep_encryption=keep_encryption, bake_watermarks=bake_watermarks
        )
        return merged

    def compose_merged_document_with_origins(
        self,
        ordered_sources: list[dict],
        *,
        keep_encryption: bool = False,
        bake_watermarks: bool = True,
    ) -> tuple[fitz.Document, list[int | None]]:
        """Build the merged document of ``ordered_sources`` (``current`` and ``file`` entries).

        Returns it with its page map: ``origins[j]`` is the live page that merged page
        ``j + 1`` was copied from (``None`` for the pages of a file).  A ``current`` entry
        carries the session's pending watermark into the result (F17-COH-4) unless
        ``bake_watermarks`` is False -- the merge into the CURRENT document swaps the result
        in as the live (unbaked) document and moves the watermark list with
        ``replace_active_document_from_snapshot(page_origins=...)`` instead.

        S17-ENC-MERGE: an ENCRYPTED current document is read through an authenticated
        numbering clone (its ``encryption=KEEP`` snapshot reopens LOCKED, and
        ``insert_pdf`` from a locked handle raises "document closed or encrypted").
        The output container is a fresh plaintext document, unless ``keep_encryption``
        asks for the current document's encryption: the container is then an emptied
        authenticated clone of the live document, so the merged result keeps its
        method, passwords and permissions exactly (a re-encryption with new
        credentials could not know the owner password).
        """
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")

        encrypted = self._doc_is_encrypted(self.doc)
        keep = bool(keep_encryption) and encrypted
        merged = self._open_emptied_encrypted_container() if keep else fitz.open()
        # A plain current document is reopened from its snapshot as before; an
        # encrypted one is cloned (authenticated) at its entry below.
        current_snapshot = None if encrypted else self._capture_doc_snapshot()
        # F16-NAV-3: insert_pdf alone drops every source's outline, page labels,
        # named destinations and its LINK_NAMED links; the graft carries them.
        graft = NavigationGraft(merged)
        origins: list[int | None] = []
        try:
            for source in ordered_sources or []:
                source_kind = (source or {}).get("source_kind")
                if source_kind == "current":
                    if current_snapshot is None:
                        current_doc = self._open_numbering_clone(self.doc)
                    else:
                        current_doc = fitz.open("pdf", current_snapshot)
                    try:
                        targets = graft.copy_pages(current_doc)
                    finally:
                        current_doc.close()
                    origins.extend(range(1, len(targets) + 1))
                    continue

                if source_kind != "file":
                    continue

                path = (source or {}).get("path")
                if not path:
                    continue

                password = (source or {}).get("password")
                # Route foreign opens through the resource guard (size/page caps +
                # auth) instead of a bare fitz.open — same auth errors, plus the
                # _MAX_PDF_BYTES/_MAX_PAGES limits a merge previously bypassed.
                file_doc = _guard_foreign_doc(Path(str(path)), password=password)
                try:
                    targets = graft.copy_pages(file_doc)
                finally:
                    file_doc.close()
                origins.extend([None] * len(targets))
            graft.finish()
            if keep:
                merged = self._prune_encrypted_container(merged)
            if bake_watermarks and any(origin is not None for origin in origins):
                self._prepare_derived_document(merged, origins)
        except BaseException:
            merged.close()
            raise

        return merged, origins

    def _open_emptied_encrypted_container(self) -> fitz.Document:
        """An authenticated, page-less clone of the live (encrypted) document.

        It keeps the document's ``/Encrypt`` dictionary and so, on every
        ``encryption=KEEP`` save, its method, user/owner passwords and permissions.
        Everything else of the old document (pages, outline, names, labels, form,
        structure tree, metadata, page-tree attributes) is dropped so the result
        matches the plaintext container of an unencrypted merge; the orphaned
        objects are pruned by ``_prune_encrypted_container``.
        """
        clone = self._open_numbering_clone(self.doc)
        try:
            if len(clone):
                clone.delete_pages(0, len(clone) - 1)
            catalog = clone.pdf_catalog()
            for key in clone.xref_get_keys(catalog):
                if key not in ("Type", "Pages"):
                    xref_set_key_exact(clone, catalog, key, "null")
            kind, value = clone.xref_get_key(catalog, "Pages")
            if kind == "xref":
                tree = int(value.split()[0])
                for key in clone.xref_get_keys(tree):
                    if key not in ("Type", "Kids", "Count"):
                        xref_set_key_exact(clone, tree, key, "null")
            with exact_set_key(clone):
                clone.set_metadata({})
        except BaseException:
            clone.close()
            raise
        return clone

    def _prune_encrypted_container(self, container: fitz.Document) -> fitz.Document:
        """Round-trip a kept-encryption merge container at ``garbage=4``, authenticated.

        Drops the objects of the pages the container was emptied of (they would
        otherwise ride along in the saved file), keeping the encryption.  Closes
        ``container``; the caller owns the returned handle.
        """
        data = self.serialize_document_bytes(container, garbage=4, encryption=fitz.PDF_ENCRYPT_KEEP)
        container.close()
        return self._open_authenticated(data, "合併後的加密文件重新驗證密碼失敗")

    def open_merge_source(self, path: str, password: str | None = None) -> dict:
        src_path = Path(path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"來源檔案不存在: {path}")
        if not src_path.is_file():
            raise ValueError(f"路徑不是有效檔案: {path}")

        # Mirror open_insert_source: the resource guard applies the size/page
        # caps + auth (replacing the bare fitz.open + inline auth here).
        doc = _guard_foreign_doc(src_path, password=password)
        try:
            if len(doc) == 0:
                raise RuntimeError(f"無法讀取來源檔案: {path}")

            return {
                "path": str(src_path),
                "display_name": src_path.name,
                "password": password,
            }
        finally:
            doc.close()

    def get_page_pixmap(
        self,
        page_num: int,
        scale: float = 1.0,
        colorspace: fitz.Colorspace | None = None,
    ) -> fitz.Pixmap:
        return self.tools.render_page_pixmap(
            page_num,
            scale=scale,
            annots=True,
            purpose="view",
            colorspace=colorspace,
        )

    def get_page_snapshot(
        self,
        page_num: int,
        scale: float = 1.0,
        colorspace: fitz.Colorspace | None = None,
    ) -> fitz.Pixmap:
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        return self.tools.render_page_pixmap(
            page_num,
            scale=scale,
            annots=True,
            purpose="snapshot",
            colorspace=colorspace,
        )

    def get_thumbnail(self, page_num: int, colorspace: fitz.Colorspace | None = None) -> fitz.Pixmap:
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        scale = thumbnail_render_scale(self.doc[page_num - 1])
        return self.get_page_pixmap(page_num, scale=scale, colorspace=colorspace)

    def get_page_label(self, page_num: int) -> str:
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        label = self.doc[page_num - 1].get_label()
        return label if label else str(page_num)

    def build_print_snapshot(self, dest: Path) -> None:
        """Write the print-input PDF directly to ``dest`` (avoids a full in-memory copy)."""
        self.tools.build_print_snapshot(dest)

    def get_print_watermarks(self) -> list[dict]:
        return json.loads(json.dumps(self.tools.watermark.get_watermarks(), ensure_ascii=False))

    def get_text_info_at_point(
        self,
        page_num: int,
        point: fitz.Point,
        allow_fallback: bool = True,
    ) -> TextHit | None:
        """Return topmost editable run info at a DISPLAYED-space point.

        ``point`` and the returned ``TextHit.target_bbox`` are visual
        (``page.rect`` / ``get_pixmap``) space and ``TextHit.rotation`` is the
        on-screen glyph rotation -- the space every View coordinate lives in.
        The text index underneath is unrotated dict space; the conversion
        happens here, once, through the ``model.geometry`` chokepoints.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None
        page = self.doc[page_num - 1]
        hit = self._get_text_info_at_point_unrotated(
            page_num,
            visual_to_unrotated_point(page, point),
            allow_fallback=allow_fallback,
        )
        return self._text_hit_to_visual(page, hit)

    @staticmethod
    def _text_hit_to_visual(page: fitz.Page, hit: TextHit | None) -> TextHit | None:
        if hit is None:
            return None
        return replace(
            hit,
            target_bbox=unrotated_to_visual_rect(page, hit.target_bbox),
            rotation=visual_text_rotation(page.rotation, hit.rotation),
        )

    def _joined_text_hit(
        self, page_idx: int, group: JoinedEditGroup, *, hit_span_id: str | None
    ) -> TextHit:
        """The ``TextHit`` of a joined edit: the text as typed, the members'
        union, the dominant member's style.  No ``source_ref`` -- the members are
        several shows; the commit re-derives the group from its own records."""
        union = group.rect()
        dominant = group.dominant()
        cluster = self.block_manager.find_overlapping_runs(page_idx, union, tol=0.5)
        return TextHit(
            target_span_id=group.first_span_id,
            target_bbox=fitz.Rect(union),
            target_text=group.text,
            font=dominant.font,
            size=float(dominant.size),
            color=tuple(dominant.color),
            rotation=int(dominant.rotation),
            cluster_span_ids=[s.span_id for s in cluster],
            target_mode="run",
            member_span_ids=group.member_span_ids,
            hit_span_id=hit_span_id,
        )

    def _get_text_info_at_point_unrotated(
        self,
        page_num: int,
        point: fitz.Point,
        allow_fallback: bool = True,
    ) -> TextHit | None:
        """Index-space hit-test (unrotated dict coordinates in AND out).

        Internal callers that already work in index space use this; the public
        ``get_text_info_at_point`` wraps it for displayed-space callers.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None

        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        mode = (self.text_target_mode or "run").lower()

        spans = self.block_manager.get_runs(page_idx)

        # Anchor-first resolution: if the click lands inside a remembered
        # run-reopen anchor region, hit-test against the anchor (not the
        # shrunk live bbox) so reopening the same textbox stays stable. The
        # span_id can change across rebuilds, so re-bind a stale anchor to the
        # nearest live run by center distance.
        anchored_hit: EditableSpan | None = None
        anchored_rect: fitz.Rect | None = None
        anchored_size: float | None = None
        anchored_distance_sq: float | None = None
        for anchor_span_id, anchor_rect in self._iter_run_reopen_anchors_for_page(page_idx):
            if point not in anchor_rect:
                continue
            group_first = group_anchor_first_member(anchor_span_id)
            if group_first is not None:
                # A grouped show's anchor (UI step 3) names its members; it
                # resolves to the first member or not at all -- never rebound
                # to a nearest run, which would plant the show's union as a
                # per-word anchor.
                anchor_run = self.block_manager.find_run_by_id(page_idx, group_first)
            else:
                anchor_run = self.block_manager.find_run_by_id(page_idx, anchor_span_id)
            if anchor_run is None and spans and group_first is None:
                # Only a run INSIDE the anchor rect may inherit it (the rect
                # is where the text was), preferring the run under the click;
                # the page-wide nearest-centre rebind planted a heading's
                # anchor on an unrelated line (F14-ANCHOR-STALE).  Nothing
                # inside -> the anchor is unrecoverable: drop it.
                anchor_run = self._stale_anchor_rebind_run(spans, anchor_rect, point)
                if anchor_run is not None:
                    self._set_run_reopen_anchor_rect(page_idx, anchor_run.span_id, anchor_rect)
                    old_size = self._get_run_reopen_anchor_size(page_idx, anchor_span_id)
                    self._set_run_reopen_anchor_size(
                        page_idx,
                        anchor_run.span_id,
                        old_size if old_size is not None else float(anchor_run.size),
                    )
                self._delete_run_reopen_anchor(page_idx, anchor_span_id)
            if anchor_run is None:
                continue
            center_x = float(anchor_rect.x0 + (anchor_rect.width / 2.0))
            center_y = float(anchor_rect.y0 + (anchor_rect.height / 2.0))
            distance_sq = ((float(point.x) - center_x) ** 2) + ((float(point.y) - center_y) ** 2)
            if anchored_hit is None or anchored_distance_sq is None or distance_sq < anchored_distance_sq:
                anchored_hit = anchor_run
                anchored_rect = fitz.Rect(anchor_rect)
                anchored_size = self._get_run_reopen_anchor_size(page_idx, anchor_span_id)
                if anchored_size is None:
                    anchored_size = float(anchor_run.size)
                anchored_distance_sq = distance_sq

        point_spans = [s for s in spans if point in fitz.Rect(s.bbox)]
        hit_spans = [anchored_hit] if anchored_hit is not None else point_spans
        if mode != "paragraph" and (hit_spans or allow_fallback):
            # Runs the app wrote for ONE edit on one baseline reopen as one box
            # (S17-ANCHOR-JOIN): a click on any member, or -- for the edit
            # hit-test only (``allow_fallback``; browse callers ask for the run
            # under the point and get nothing in a gap) -- in the gap between
            # them when no other run lies under it, opens the whole text.
            joined = self._joined_edit_group_for(
                page_idx,
                spans,
                span_id=hit_spans[-1].span_id if hit_spans else None,
                point=point,
            )
            if joined is not None:
                return self._joined_text_hit(
                    page_idx, joined, hit_span_id=point_spans[-1].span_id if point_spans else None
                )
        if hit_spans:
            target = hit_spans[-1]  # Topmost = last extracted/drawn.
            # Browse callers (selection, char context) need the run that is
            # geometrically under the point, even when a reopen anchor won the
            # edit target -- a grouped show's anchor resolves to its FIRST
            # member (F16-COPY-1).
            browse_span_id = point_spans[-1].span_id if point_spans else target.span_id
            reopen_anchor_rect = (
                fitz.Rect(anchored_rect)
                if anchored_rect is not None
                else self._get_run_reopen_anchor_rect(page_idx, target.span_id)
            )
            if mode == "paragraph":
                para = self.block_manager.find_paragraph_for_run(page_idx, target.span_id)
                if para is not None:
                    para_run_ids = set(para.run_ids)
                    cluster = [span for span in spans if span.span_id in para_run_ids]
                    if not cluster:
                        cluster = self.block_manager.find_overlapping_runs(page_idx, para.bbox, tol=0.5)
                    return TextHit(
                        target_span_id=target.span_id,
                        target_bbox=fitz.Rect(para.bbox),
                        target_text=para.text,
                        font=para.font,
                        size=float(para.size),
                        color=tuple(para.color),
                        rotation=int(para.rotation),
                        cluster_span_ids=[s.span_id for s in cluster],
                        target_mode="paragraph",
                        target_paragraph_id=para.paragraph_id,
                        hit_span_id=browse_span_id,
                    )
            group = self._source_run_group(page_idx, spans, target.span_id)
            if group is not None:
                # The clicked run is one word of a PROVEN single show: the
                # target is that whole show (decoded text, member union).
                # The union replaces any per-run reopen anchor rect -- the
                # anchor describes one word, not the show.
                first = self.block_manager.find_run_by_id(page_idx, group.first_span_id) or target
                union = group.rect()
                cluster = self.block_manager.find_overlapping_runs(page_idx, union, tol=0.5)
                return TextHit(
                    target_span_id=group.first_span_id,
                    target_bbox=fitz.Rect(union),
                    target_text=group.text,
                    font=first.font,
                    size=float(anchored_size if anchored_size is not None else first.size),
                    color=tuple(first.color),
                    rotation=int(first.rotation),
                    cluster_span_ids=[s.span_id for s in cluster],
                    target_mode="run",
                    source_ref=group.source_ref,
                    member_span_ids=group.member_span_ids,
                    hit_span_id=browse_span_id,
                )
            cluster = self.block_manager.find_overlapping_runs(page_idx, target.bbox, tol=0.5)
            return TextHit(
                target_span_id=target.span_id,
                target_bbox=fitz.Rect(reopen_anchor_rect if reopen_anchor_rect is not None else target.bbox),
                target_text=target.text,
                font=target.font,
                size=float(anchored_size if anchored_size is not None else target.size),
                color=tuple(target.color),
                rotation=int(target.rotation),
                cluster_span_ids=[s.span_id for s in cluster],
                target_mode="run",
                member_span_ids=(target.span_id,),
                hit_span_id=browse_span_id,
            )

        if not allow_fallback:
            return None

        # Backward-compatible fallback if span extraction misses the point.
        page = self.doc[page_idx]
        blocks = content_text(page, "dict", flags=0)["blocks"]
        for block_idx, block in enumerate(blocks):
            if block.get("type") != 0:
                continue
            rect = fitz.Rect(block["bbox"])
            if point not in rect:
                continue

            font_name = "helv"
            font_size = 12.0
            color_int = 0
            rotation = 0

            if block.get("lines") and block["lines"][0].get("spans"):
                first_span = block["lines"][0]["spans"][0]
                font_name = first_span.get("font", "helv")
                font_size = float(first_span.get("size", 12.0))
                color_int = int(first_span.get("color", 0))
            if block.get("lines") and block["lines"][0].get("dir") is not None:
                rotation = rotation_degrees_from_dir(block["lines"][0]["dir"])

            rgb_int = fitz.sRGB_to_rgb(color_int) if color_int else (0, 0, 0)
            color = tuple(c / 255.0 for c in rgb_int)
            text_content = self._compose_block_text_for_hit(block)
            fallback_span_id = f"p{page_idx}_b{block_idx}_l0_s0"
            return TextHit(
                target_span_id=fallback_span_id,
                target_bbox=rect,
                target_text=text_content,
                font=font_name,
                size=font_size,
                color=color,
                rotation=rotation,
                cluster_span_ids=[fallback_span_id],
                target_mode=mode if mode in {"run", "paragraph"} else "run",
            )
        return None

    @staticmethod
    def _browse_span_id(hit: TextHit | None) -> str | None:
        """The run a BROWSE operation (selection, char context) means by ``hit``.

        A grouped show's ``target_span_id`` is its first word (the edit
        target); browse code needs the word under the point instead
        (F16-COPY-1), so it must read the hit through this, never through
        ``target_span_id`` directly.
        """
        if hit is None:
            return None
        return getattr(hit, "hit_span_id", None) or getattr(hit, "target_span_id", None) or None

    def _browse_run_at_point_unrotated(self, page_num: int, point: fitz.Point) -> EditableSpan | None:
        """Index-space browse hit: the run under ``point`` (no block fallback)."""
        hit = self._get_text_info_at_point_unrotated(page_num, point, allow_fallback=False)
        span_id = self._browse_span_id(hit)
        if not span_id:
            return None
        return self.block_manager.find_run_by_id(page_num - 1, span_id)

    def get_text_in_rect(self, page_num: int, rect: fitz.Rect) -> str:
        """Extract plain text in a rectangle for browse-mode copy."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return ""
        text, _ = self.get_text_selection_snapshot(page_num, rect)
        return text

    def get_text_selection_bounds(self, page_num: int, rect: fitz.Rect) -> fitz.Rect | None:
        """Return browse-mode selection bounds snapped to whole visual lines."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None
        _, bounds = self.get_text_selection_snapshot(page_num, rect)
        return fitz.Rect(bounds) if bounds is not None else None

    def get_text_selection_snapshot(self, page_num: int, rect: fitz.Rect) -> tuple[str, fitz.Rect | None]:
        """Resolve browse-mode text selection by snapping intersected clips to full line units."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", None

        def _extract_line_text(line_dict: dict) -> str:
            spans_data = line_dict.get("spans") or []
            chunks: list[str] = []
            for span_dict in spans_data:
                span_text = span_dict.get("text")
                if span_text is None:
                    span_text = "".join((char.get("c") or "") for char in (span_dict.get("chars") or []))
                chunks.append(span_text)
            return "".join(chunks).strip()

        page_idx = page_num - 1
        page = self.doc[page_idx]
        clipped = clamp_rect_to_page(fitz.Rect(rect), page.rect)
        # ``rect``/``clipped`` are displayed space (the View's selection
        # rectangle); the index and ``get_text(clip=)`` are unrotated space.
        clipped_unrotated = visual_to_unrotated_rect(page, clipped)
        self.ensure_page_index_built(page_num)

        spans = self.block_manager.get_runs(page_idx)
        if not spans:
            text = (page.get_text("text", clip=clipped_unrotated, sort=True) or "").strip()
            return text, (fitz.Rect(clipped) if text else None)

        selected_keys: set[tuple[int, int]] = set()
        grouped_spans: dict[tuple[int, int], list] = {}
        for span in spans:
            key = (int(span.block_idx), int(span.line_idx))
            grouped_spans.setdefault(key, []).append(span)
            if fitz.Rect(span.bbox).intersects(clipped_unrotated):
                selected_keys.add(key)

        if not selected_keys:
            return "", None

        raw_blocks = content_text(page, "dict", flags=0).get("blocks", [])
        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        for key in sorted(selected_keys):
            line_spans = sorted(
                grouped_spans.get(key, []),
                key=lambda item: (int(item.span_idx), float(item.bbox.x0), float(item.bbox.y0)),
            )
            block_idx, line_idx = key
            raw_line = None
            if 0 <= block_idx < len(raw_blocks):
                block_lines = raw_blocks[block_idx].get("lines") or []
                if 0 <= line_idx < len(block_lines):
                    raw_line = block_lines[line_idx]

            if raw_line is not None:
                line_text = _extract_line_text(raw_line)
                line_bbox = fitz.Rect(raw_line.get("bbox") or line_spans[0].bbox)
            else:
                line_text = " ".join((span.text or "").strip() for span in line_spans if (span.text or "").strip()).strip()
                x0 = min(float(span.bbox.x0) for span in line_spans)
                y0 = min(float(span.bbox.y0) for span in line_spans)
                x1 = max(float(span.bbox.x1) for span in line_spans)
                y1 = max(float(span.bbox.y1) for span in line_spans)
                line_bbox = fitz.Rect(x0, y0, x1, y1)

            if not line_text:
                continue
            line_texts.append(line_text)
            line_rects.append(line_bbox)

        if not line_texts or not line_rects:
            return "", None

        bounds = fitz.Rect(line_rects[0])
        for line_rect in line_rects[1:]:
            bounds.include_rect(line_rect)
        # Index-space bounds -> displayed space for the View's highlight.
        return "\n".join(line_texts).strip(), unrotated_to_visual_rect(self.doc[page_idx], bounds)

    def get_text_selection_snapshot_from_run(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
    ) -> tuple[str, fitz.Rect | None]:
        """Resolve browse-mode selection from a start run to an end point on the same page."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", None

        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        runs = self.block_manager.get_runs(page_idx)
        if not runs:
            return "", None

        start_run = self.block_manager.find_run_by_id(page_idx, start_span_id)
        if start_run is None:
            return "", None
        # Displayed-space focus point -> index space for everything below.
        end_point = visual_to_unrotated_point(self.doc[page_idx], end_point)

        def _distance_sq_to_rect(point: fitz.Point, rect: fitz.Rect) -> float:
            dx = 0.0
            if point.x < rect.x0:
                dx = rect.x0 - point.x
            elif point.x > rect.x1:
                dx = point.x - rect.x1
            dy = 0.0
            if point.y < rect.y0:
                dy = rect.y0 - point.y
            elif point.y > rect.y1:
                dy = point.y - rect.y1
            return dx * dx + dy * dy

        resolved_end_run = self._browse_run_at_point_unrotated(page_num, end_point)
        if resolved_end_run is None:
            resolved_end_run = min(
                runs,
                key=lambda run: _distance_sq_to_rect(end_point, fitz.Rect(run.bbox)),
            )

        run_ids = [run.span_id for run in runs]
        try:
            start_idx = run_ids.index(start_run.span_id)
            end_idx = run_ids.index(resolved_end_run.span_id)
        except ValueError:
            return "", None

        range_start = min(start_idx, end_idx)
        range_end = max(start_idx, end_idx)
        selected_runs = runs[range_start:range_end + 1]
        if not selected_runs:
            return "", None

        def _same_visual_line(left, right) -> bool:
            left_rect = fitz.Rect(left.bbox)
            right_rect = fitz.Rect(right.bbox)
            left_rotation = int(getattr(left, "rotation", 0)) % 360
            right_rotation = int(getattr(right, "rotation", 0)) % 360
            if left_rotation != right_rotation:
                return False
            tol = 2.0
            if left_rotation in (90, 270):
                return not (left_rect.x1 < right_rect.x0 - tol or right_rect.x1 < left_rect.x0 - tol)
            return not (left_rect.y1 < right_rect.y0 - tol or right_rect.y1 < left_rect.y0 - tol)

        line_groups: list[list] = []
        run_to_line_idx: dict[str, int] = {}
        for run in runs:
            if line_groups and _same_visual_line(line_groups[-1][-1], run):
                line_groups[-1].append(run)
            else:
                line_groups.append([run])
            run_to_line_idx[run.span_id] = len(line_groups) - 1

        start_line_idx = run_to_line_idx.get(start_run.span_id)
        end_line_idx = run_to_line_idx.get(resolved_end_run.span_id)
        if start_line_idx is None or end_line_idx is None:
            return "", None

        def _slice_for_group(group_idx: int) -> list:
            group_runs = line_groups[group_idx]
            group_ids = [run.span_id for run in group_runs]
            if start_line_idx == end_line_idx == group_idx:
                left = min(group_ids.index(start_run.span_id), group_ids.index(resolved_end_run.span_id))
                right = max(group_ids.index(start_run.span_id), group_ids.index(resolved_end_run.span_id))
                return group_runs[left:right + 1]
            if group_idx == start_line_idx:
                start_pos = group_ids.index(start_run.span_id)
                return group_runs[start_pos:]
            if group_idx == end_line_idx:
                end_pos = group_ids.index(resolved_end_run.span_id)
                return group_runs[:end_pos + 1]
            return group_runs

        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        for group_idx in range(min(start_line_idx, end_line_idx), max(start_line_idx, end_line_idx) + 1):
            line_runs = _slice_for_group(group_idx)
            line_text = " ".join((run.text or "").strip() for run in line_runs if (run.text or "").strip()).strip()
            if not line_text:
                continue
            line_texts.append(line_text)
            line_rect = fitz.Rect(line_runs[0].bbox)
            for run in line_runs[1:]:
                line_rect.include_rect(fitz.Rect(run.bbox))
            line_rects.append(line_rect)

        if not line_texts or not line_rects:
            return "", None

        bounds = fitz.Rect(line_rects[0])
        for line_rect in line_rects[1:]:
            bounds.include_rect(line_rect)
        # Index-space bounds -> displayed space for the View's highlight.
        return "\n".join(line_texts).strip(), unrotated_to_visual_rect(self.doc[page_idx], bounds)

    def get_chars_in_run(
        self,
        page_num: int,
        span_id: str,
        rawdict: dict | None = None,
    ) -> list[tuple[str, fitz.Rect]]:
        """Per-character (glyph, bbox) pairs for a run, in reading order, with
        the glyph boxes in DISPLAYED space (see ``get_text_info_at_point``)."""
        chars = self._get_chars_in_run_unrotated(page_num, span_id, rawdict=rawdict)
        doc = self.doc
        if not chars or doc is None:
            return chars
        page = doc[page_num - 1]
        return [(glyph, unrotated_to_visual_rect(page, rect)) for glyph, rect in chars]

    def _get_chars_in_run_unrotated(
        self,
        page_num: int,
        span_id: str,
        rawdict: dict | None = None,
    ) -> list[tuple[str, fitz.Rect]]:
        """Index-space glyph boxes for a run, in reading order.

        Glyph boxes come from PyMuPDF ``rawdict``; a char belongs to the run when
        its centre lies inside the run's bbox. Used for character-level selection.
        Pass ``rawdict`` to reuse one page extraction across multiple runs.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return []
        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        run = self.block_manager.find_run_by_id(page_idx, span_id)
        if run is None:
            return []
        run_rect = fitz.Rect(run.bbox)
        # Tolerance is applied only along the run's *reading* axis (so the first
        # and last glyphs aren't clipped); the cross axis stays tight to avoid
        # picking up glyphs from an overlapping neighbouring line.
        tol = 0.5
        rotation = int(getattr(run, "rotation", 0)) % 360
        is_vertical = rotation in (90, 270)
        if rawdict is None:
            page = self.doc[page_idx]
            try:
                raw = content_text(page, "rawdict")
            except Exception:
                return []
        else:
            raw = rawdict
        collected: list[tuple[str, fitz.Rect]] = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        glyph = ch.get("c", "")
                        cb = fitz.Rect(ch.get("bbox"))
                        cx = (cb.x0 + cb.x1) / 2.0
                        cy = (cb.y0 + cb.y1) / 2.0
                        if is_vertical:
                            inside = (
                                run_rect.x0 <= cx <= run_rect.x1
                                and run_rect.y0 - tol <= cy <= run_rect.y1 + tol
                            )
                        else:
                            inside = (
                                run_rect.x0 - tol <= cx <= run_rect.x1 + tol
                                and run_rect.y0 <= cy <= run_rect.y1
                            )
                        if inside:
                            collected.append((glyph, cb))
        # F17-COPY-180: the glyph list takes the order of ``run.text`` at EVERY
        # rotation (reading order; logical, i.e. MuPDF's traversal order, for
        # right-to-left letters -- F15-RTL-ORDER), so the pairs line up with the
        # run text index by index and agree with ``selection_text.reading_sign``.
        return order_run_glyphs(collected, rotation)

    def get_char_context_at_point(
        self,
        page_num: int,
        point: fitz.Point,
    ) -> tuple[str, int, list[fitz.Rect]] | None:
        """Return run text, strict hit index, and glyph rectangles at a
        DISPLAYED-space point; the rectangles come back in displayed space."""
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return None
        page = self.doc[page_num - 1]
        point = visual_to_unrotated_point(page, point)
        run = self._browse_run_at_point_unrotated(page_num, point)
        if run is None:
            return None
        chars = self._get_chars_in_run_unrotated(page_num, run.span_id)
        if not chars:
            return None
        hit_index = next(
            (
                index
                for index, (_glyph, rect) in enumerate(chars)
                if fitz.Rect(rect).contains(point)
            ),
            None,
        )
        if hit_index is None:
            return None
        return (
            "".join(glyph for glyph, _rect in chars),
            hit_index,
            [unrotated_to_visual_rect(page, rect) for _glyph, rect in chars],
        )

    def get_text_selection_lines(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
        start_point: fitz.Point | None = None,
    ) -> tuple[str, list[fitz.Rect]]:
        """Character-level browse selection from a start run/point to an end point.

        Returns the exact selected text and one clipped rect per visual line
        (partial first line → full middle lines → partial last line). The text
        matches the highlighted glyphs exactly so copy stays in sync (AC-1).
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            return "", []
        page_idx = page_num - 1
        self.ensure_page_index_built(page_num)
        runs = self.block_manager.get_runs(page_idx)
        if not runs:
            return "", []
        # Displayed-space anchor/focus points -> index space for the clipping
        # below; the per-line rects are mapped back on the way out.
        page = self.doc[page_idx]
        end_point = visual_to_unrotated_point(page, end_point)
        if start_point is not None:
            start_point = visual_to_unrotated_point(page, start_point)
        start_run = self.block_manager.find_run_by_id(page_idx, start_span_id)
        if start_run is None:
            return "", []
        if start_point is not None:
            # A caller holding the press hit's EDIT target (a grouped show's
            # first word) still starts at the word under the press.
            start_hit = self._get_text_info_at_point_unrotated(page_num, start_point, allow_fallback=False)
            start_word_id = self._browse_span_id(start_hit)
            if (
                start_hit is not None
                and start_word_id
                and start_word_id != start_span_id
                and start_span_id in (start_hit.target_span_id, *start_hit.member_span_ids)
            ):
                start_run = self.block_manager.find_run_by_id(page_idx, start_word_id) or start_run

        def _distance_sq_to_rect(point: fitz.Point, rect: fitz.Rect) -> float:
            dx = max(rect.x0 - point.x, 0.0, point.x - rect.x1)
            dy = max(rect.y0 - point.y, 0.0, point.y - rect.y1)
            return dx * dx + dy * dy

        resolved_end_run = self._browse_run_at_point_unrotated(page_num, end_point)
        if resolved_end_run is None:
            resolved_end_run = min(runs, key=lambda r: _distance_sq_to_rect(end_point, fitz.Rect(r.bbox)))

        run_ids = [r.span_id for r in runs]
        try:
            start_idx = run_ids.index(start_run.span_id)
            end_idx = run_ids.index(resolved_end_run.span_id)
        except ValueError:
            return "", []

        # Order anchor/focus by reading order so clipping is direction-independent.
        if start_idx <= end_idx:
            first_run, first_point = start_run, start_point
            last_run, last_point = resolved_end_run, end_point
        else:
            first_run, first_point = resolved_end_run, end_point
            last_run, last_point = start_run, start_point

        def _same_visual_line(left, right) -> bool:
            left_rect = fitz.Rect(left.bbox)
            right_rect = fitz.Rect(right.bbox)
            lr = int(getattr(left, "rotation", 0)) % 360
            rr = int(getattr(right, "rotation", 0)) % 360
            if lr != rr:
                return False
            tol = 2.0
            if lr in (90, 270):
                return not (left_rect.x1 < right_rect.x0 - tol or right_rect.x1 < left_rect.x0 - tol)
            return not (left_rect.y1 < right_rect.y0 - tol or right_rect.y1 < left_rect.y0 - tol)

        line_groups: list[list] = []
        run_to_line_idx: dict[str, int] = {}
        for run in runs:
            if line_groups and _same_visual_line(line_groups[-1][-1], run):
                line_groups[-1].append(run)
            else:
                line_groups.append([run])
            run_to_line_idx[run.span_id] = len(line_groups) - 1

        first_line = run_to_line_idx.get(first_run.span_id)
        last_line = run_to_line_idx.get(last_run.span_id)
        if first_line is None or last_line is None:
            return "", []
        lo_line, hi_line = min(first_line, last_line), max(first_line, last_line)

        def _slice_for_group(group_idx: int) -> list:
            group_runs = line_groups[group_idx]
            ids = [r.span_id for r in group_runs]
            if first_line == last_line == group_idx:
                a = ids.index(first_run.span_id)
                b = ids.index(last_run.span_id)
                return group_runs[min(a, b):max(a, b) + 1]
            if group_idx == first_line:
                return group_runs[ids.index(first_run.span_id):]
            if group_idx == last_line:
                return group_runs[:ids.index(last_run.span_id) + 1]
            return group_runs

        def _axis(point: fitz.Point, vertical: bool) -> float:
            return point.y if vertical else point.x

        line_texts: list[str] = []
        line_rects: list[fitz.Rect] = []
        same_run = first_run.span_id == last_run.span_id
        try:
            rawdict = content_text(self.doc[page_idx], "rawdict")
        except Exception:
            rawdict = None
        # F16-COPY-2: the gap between two words is a space glyph in MuPDF's
        # text that the index assigns to no run; collected once per call.
        gap_chars = whitespace_chars(rawdict)
        for group_idx in range(lo_line, hi_line + 1):
            glyphs: list[str] = []
            rects: list[fitz.Rect] = []
            prev_run = None
            slice_runs = _slice_for_group(group_idx)
            # Which way "onward from the first pointer" / "back from the last
            # pointer" runs on this line (right-to-left text, quarter turns).
            first_dir, last_dir = clip_directions(slice_runs)
            for run in slice_runs:
                vertical = int(getattr(run, "rotation", 0)) % 360 in (90, 270)
                chars = self._get_chars_in_run_unrotated(page_num, run.span_id, rawdict=rawdict)
                run_glyphs: list[str] = []
                run_rects: list[fitz.Rect] = []
                for glyph, cb in chars:
                    coord = (cb.y0 + cb.y1) / 2.0 if vertical else (cb.x0 + cb.x1) / 2.0
                    keep = True
                    if same_run and run.span_id == first_run.span_id and first_point is not None and last_point is not None:
                        lo = min(_axis(first_point, vertical), _axis(last_point, vertical))
                        hi = max(_axis(first_point, vertical), _axis(last_point, vertical))
                        keep = lo <= coord <= hi
                    else:
                        if run.span_id == first_run.span_id and first_point is not None:
                            keep = keep and (coord - _axis(first_point, vertical)) * first_dir >= 0
                        if run.span_id == last_run.span_id and last_point is not None:
                            keep = keep and (coord - _axis(last_point, vertical)) * last_dir <= 0
                    if keep:
                        run_glyphs.append(glyph)
                        run_rects.append(cb)
                if not run_glyphs:
                    continue
                if prev_run is not None:
                    glyphs.extend(whitespace_between_runs(gap_chars, prev_run, run))
                glyphs.extend(run_glyphs)
                rects.extend(run_rects)
                prev_run = run
            if not rects:
                continue
            line_rect = fitz.Rect(rects[0])
            for r in rects[1:]:
                line_rect.include_rect(r)
            line_texts.append("".join(glyphs))
            line_rects.append(line_rect)

        return "\n".join(line_texts), [unrotated_to_visual_rect(page, r) for r in line_rects]

    # --- displayed-space projections of the text index (View-facing) ---------

    def get_text_targets(self, page_idx: int, mode: str, *, blocks_fallback: bool = False) -> list:
        """Outline candidates for a page -- paragraphs, or runs (and, only when
        ``blocks_fallback`` and the page has no runs, blocks) -- as COPIES whose
        ``bbox``/``rect``/``layout_rect``/``origin`` are DISPLAYED space and whose
        ``rotation`` is the on-screen glyph rotation.  The index itself stays
        unrotated; never hand its objects to the View directly."""
        if not self.doc or page_idx < 0 or page_idx >= len(self.doc):
            return []
        bm = self.block_manager
        if mode == "paragraph":
            items = list(getattr(bm, "get_paragraphs", lambda _i: [])(page_idx) or [])
        else:
            runs: list = getattr(bm, "get_runs", lambda _i: [])(page_idx) or []
            items = self._group_runs_for_targets(page_idx, runs)
            if blocks_fallback and not items:
                items = list(getattr(bm, "get_blocks", lambda _i: [])(page_idx) or [])
        page = self.doc[page_idx]
        return [self._text_geometry_to_visual(page, item) for item in items]

    def _source_run_group(self, page_idx: int, runs, span_id: str) -> SourceRunGroup | None:
        """The proven source-show group containing ``span_id`` (run mode only)."""
        if (self.text_target_mode or "run").lower() != "run" or not self.doc:
            return None
        resolver = getattr(self, "_source_run_resolver", None)
        if resolver is None:
            resolver = self._source_run_resolver = SourceRunResolver()
        return resolver.group_for_span(self.doc, page_idx, runs, span_id)

    def _group_runs_for_targets(self, page_idx: int, runs) -> list:
        """Run-mode outline items: each proven group collapses into ONE item
        (its first member, carrying the decoded show text and the union bbox),
        so outlines match what a click on any member returns."""
        items = list(runs)
        if not items or not self.doc:
            return items
        resolver = getattr(self, "_source_run_resolver", None)
        if resolver is None:
            resolver = self._source_run_resolver = SourceRunResolver()
        groups = resolver.page_groups(self.doc, page_idx, runs)
        if not groups:
            return items
        out: list = []
        emitted: set[str] = set()
        for run in items:
            group = groups.get(run.span_id)
            if group is None:
                out.append(run)
                continue
            if group.first_span_id in emitted:
                continue
            emitted.add(group.first_span_id)
            first = next((r for r in items if r.span_id == group.first_span_id), run)
            out.append(replace(first, bbox=group.rect(), text=group.text))
        return out

    def get_text_blocks(self, page_idx: int) -> list:
        """Text blocks of a page as DISPLAYED-space copies (see ``get_text_targets``)."""
        if not self.doc or page_idx < 0 or page_idx >= len(self.doc):
            return []
        blocks = list(getattr(self.block_manager, "get_blocks", lambda _i: [])(page_idx) or [])
        page = self.doc[page_idx]
        return [self._text_geometry_to_visual(page, block) for block in blocks]

    @staticmethod
    def _text_geometry_to_visual(page: fitz.Page, item):
        """Copy an index dataclass (run / paragraph / block) into displayed space."""
        changes: dict[str, object] = {}
        for field_name in ("bbox", "rect", "layout_rect"):
            value = getattr(item, field_name, None)
            if value is not None:
                changes[field_name] = unrotated_to_visual_rect(page, value)
        origin = getattr(item, "origin", None)
        if origin is not None:
            changes["origin"] = unrotated_to_visual_point(page, origin)
        if hasattr(item, "rotation"):
            changes["rotation"] = visual_text_rotation(page.rotation, item.rotation)
        return replace(item, **changes)

    def visual_rect_to_unrotated(self, page_num: int, rect: fitz.Rect) -> fitz.Rect:
        """Displayed-space rect -> the index's unrotated space (for the few
        controller paths that must query ``block_manager`` by rectangle)."""
        doc = self.doc
        if doc is None or page_num < 1 or page_num > len(doc):
            return fitz.Rect(rect)
        return visual_to_unrotated_rect(doc[page_num - 1], rect)

    def get_render_width_for_edit(self, page_num: int, rect: fitz.Rect) -> float:
        """編輯換行寬度 == 原文字框寬度（point），不再加任何 Qt margin。

        編輯框比原 rect 寬時，Qt 字型渲染（與 PyMuPDF glyph metrics 略有
        差異）會在不同位置斷行，導致「開啟編輯框後斷行跳動」。換行寬度
        鎖定為來源 rect 寬度可讓預覽與最終 PDF 斷行一致。
        """
        return float(rect.width)

    def _resolve_add_text_font(self, font_hint: str) -> str:
        """Resolve add-text font name with CJK-safe default."""
        low = (font_hint or "").strip().lower()
        if not low:
            return "cjk"
        if low in {"microsoft jhenghei", "microsoftjhenghei", "microsoftjhengheiregular", "msjh"}:
            return "microsoft jhenghei"
        if low in {"pmingliu", "mingliu"}:
            return "pmingliu"
        if low in {"dfkai-sb", "dfkai", "dfkaishu-sb-estd-bf", "kaiu"}:
            return "dfkai-sb"
        if low in {"cjk", "china-ts", "china-ss"}:
            return low
        if any(k in low for k in ("cjk", "jhenghei", "yahei", "simsun", "pingfang", "source han", "noto")):
            return "cjk"
        resolved = self._resolve_font_for_push(font_hint)
        return resolved or "cjk"

    def _resolve_cjk_companion_font(self, latin_font_name: str) -> str:
        token = self._resolve_add_text_font(latin_font_name)
        if token in {"cjk", "china-ts", "china-ss", "microsoft jhenghei", "pmingliu", "dfkai-sb"}:
            return token
        if token == "tiro":
            return "china-ts"
        return "china-ss"

    def _font_token_to_css_family(self, font_token: str) -> str:
        token = self._resolve_add_text_font(font_token)
        return _CUSTOM_CJK_ALIASES.get(token, token)

    def _font_face_css_for_token(self, font_token: str) -> str:
        token = self._resolve_add_text_font(font_token)
        font_path = _WINDOWS_CJK_FONT_FILES.get(token)
        if font_path is None or not font_path.exists():
            return ""
        css_family = self._font_token_to_css_family(token)
        # Use absolute local path so MuPDF can resolve the face during htmlbox rendering.
        src = font_path.as_posix()
        return f'@font-face {{ font-family: "{css_family}"; src: url("{src}"); }}'

    def _insert_tiny_plain_text(
        self,
        page: fitz.Page,
        text: str,
        color_rgb: tuple[float, float, float],
        font_size_hint: float,
    ) -> None:
        """
        Tiny canvas fallback: force a minimal plain-text insertion.
        This prioritizes recoverable text extraction on extremely small pages.
        """
        tiny_size = 0.1
        x = float(page.rect.x0) + 0.05
        y = float(page.rect.y0) + max(0.2, min(float(page.rect.height) * 0.8, max(0.2, float(page.rect.height) - 0.05)))
        insert_text_page_space(
            page,
            fitz.Point(x, y),
            text,
            fontsize=tiny_size,
            fontname="helv",
            color=color_rgb,
            rotate=int(page.rotation) % 360,
        )

    def add_image_object(
        self,
        page_num: int,
        visual_rect: fitz.Rect,
        image_bytes: bytes,
        *,
        rotation: int = 0,
    ) -> str:
        return pdf_object_ops.add_image_object(self, page_num, visual_rect, image_bytes, rotation=rotation)

    def _pick_ocr_font(self, text: str) -> str:
        """Pick a PyMuPDF built-in font that covers the OCR text's scripts."""
        if re.search(r"[\u3040-\u30ff]", text):
            return "japan"
        if re.search(r"[\uac00-\ud7af]", text):
            return "korea"
        if re.search(r"[\u4e00-\u9fff]", text):
            return "china-t"
        return "helv"

    def apply_ocr_spans(
        self,
        page_num: int,
        spans: list,
    ) -> int:
        """Insert OCR-detected strings as invisible text (render_mode=3).

        ``spans`` is a sequence of ``OcrSpan``-like objects with ``bbox``,
        ``text``, and ``confidence`` attributes. Bboxes are in visual page
        coordinates. Returns the number of spans actually written.
        """
        if not self.doc:
            return 0
        if page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效 OCR 頁碼: {page_num}")
        if not spans:
            return 0

        page_idx = page_num - 1
        page = self.doc[page_idx]
        unrot_bounds = self._unrotated_page_rect(page)
        page_rotation = int(page.rotation) % 360

        inserted = 0
        for span in spans:
            text = (getattr(span, "text", "") or "").strip()
            if not text:
                continue
            bbox = getattr(span, "bbox", None)
            if bbox is None or len(bbox) != 4:
                continue

            visual_rect = fitz.Rect(*bbox)
            unrot_rect = self._visual_rect_to_unrotated_rect(page, visual_rect)
            unrot_rect = clamp_rect_to_page(unrot_rect, unrot_bounds)
            height = float(unrot_rect.height)
            width = float(unrot_rect.width)
            if height < 1.0 or width < 1.0:
                continue

            font_name = self._pick_ocr_font(text)
            font_size = max(1.0, height * 0.9)
            baseline_x = float(unrot_rect.x0)
            baseline_y = float(unrot_rect.y1 - height * 0.12)

            try:
                insert_text_page_space(
                    page,
                    fitz.Point(baseline_x, baseline_y),
                    text,
                    fontname=font_name,
                    fontsize=font_size,
                    render_mode=3,
                    rotate=page_rotation,
                )
                inserted += 1
            except Exception:
                logger.exception(
                    "apply_ocr_spans: insert_text failed (page=%s font=%s text=%r)",
                    page_num,
                    font_name,
                    text,
                )
                continue

        if inserted:
            self.block_manager.rebuild_page(page_idx, self.doc)
            self.mark_page_content_dirty(page_idx, fitz.Rect(page.rect))
            self.edit_count += 1
            logger.info("apply_ocr_spans page=%s inserted=%s", page_num, inserted)
        return inserted

    def add_textbox(
        self,
        page_num: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str = "cjk",
        size: int = 12,
        color: tuple = (0.0, 0.0, 0.0),
    ) -> None:
        return pdf_object_ops.add_textbox(self, page_num, visual_rect, text, font=font, size=size, color=color)

    def get_object_info_at_point(self, page_num: int, point: fitz.Point) -> ObjectHitInfo | None:
        return pdf_object_ops.get_object_info_at_point(self, page_num, point)

    def move_object(self, request: MoveObjectRequest) -> bool:
        return pdf_object_ops.move_object(self, request)

    def rotate_object(self, request: RotateObjectRequest) -> bool:
        return pdf_object_ops.rotate_object(self, request)

    def delete_object(self, request: DeleteObjectRequest) -> bool:
        return pdf_object_ops.delete_object(self, request)

    def delete_objects_atomic(self, requests: list[DeleteObjectRequest]) -> bool:
        return pdf_object_ops.delete_objects_atomic(self, requests)

    def resize_object(self, request: ResizeObjectRequest) -> bool:
        return pdf_object_ops.resize_object(self, request)

    def build_preview_insert_css(
        self,
        size: float,
        color: tuple,
        font_hint: str = "helv",
        line_height: float = 0.0,
        member_spans: list | None = None,
        new_text: str | None = None,
    ) -> str:
        """CSS of the live htmlbox preview of an edit: ``_build_insert_css``
        plus the right-to-left base direction when the edited runs read right
        to left and the typed ``new_text`` does too (D-RTL-PREVIEW,
        F17-RTL-LATIN; see ``pdf_text_edit.preview_insert_css``)."""
        return pdf_text_edit.preview_insert_css(
            self, size, color, font_hint, line_height, member_spans, new_text
        )

    def _convert_text_to_html(
        self,
        text: str,
        font_size: float,
        color: tuple,
        latin_font: str = "helv",
    ) -> str:
        """
        將混合文本轉換為帶有字體樣式的簡單 HTML，並正確處理空格。
        [優化 3] 使用模組級預編譯正則 _RE_HTML_TEXT_PARTS、_RE_CJK，避免重複編譯
        """
        html_parts = []
        if not text:
            return ""

        parts = _RE_HTML_TEXT_PARTS.findall(text)
        latin_font_name = self._resolve_add_text_font(latin_font)
        cjk_font_name = self._resolve_cjk_companion_font(latin_font_name)
        latin_css_family = self._font_token_to_css_family(latin_font_name)
        cjk_css_family = self._font_token_to_css_family(cjk_font_name)

        for part in parts:
            if part == '\n':
                html_parts.append('<br>')
            elif part.isspace():
                html_parts.append(f'<span style="font-family: {latin_css_family};">{part}</span>')
            elif _RE_CJK.match(part):
                html_parts.append(f'<span style="font-family: {cjk_css_family};">{_html_mod.escape(part)}</span>')
            else:
                html_parts.append(
                    f'<span style="font-family: {latin_css_family};">{_latin_word_html(part)}</span>'
                )

        return "".join(html_parts)

    def _build_multi_style_html(
        self,
        new_text: str,
        member_spans: list,
        default_color: tuple,
        latin_font: str = "helv",
    ) -> str:
        """Build HTML that preserves per-run colors from ``member_spans``.

        Used when a paragraph-mode edit should not collapse multi-style runs
        onto the dominant color: characters in ``new_text`` that diff-match a
        source span inherit that span's color; inserted/replaced chunks inherit
        the nearest preceding span's color (or the first span's color at the
        start).
        """
        if not new_text:
            return ""
        if any(contains_rtl(getattr(s, "text", "")) for s in member_spans):
            # F15-RTL-ORDER: right-to-left runs are numbered in reading order
            # (``span_idx``); their x order is the reverse of the logical text.
            ordered = sorted(
                member_spans,
                key=lambda s: (
                    int(getattr(s, "block_idx", 0)),
                    int(getattr(s, "line_idx", 0)),
                    int(getattr(s, "span_idx", 0)),
                ),
            )
        else:
            ordered = sorted(
                member_spans,
                key=lambda s: (float(s.bbox.y0), float(s.bbox.x0)),
            )
        source_chars: list[str] = []
        source_colors: list[tuple[float, ...]] = []
        for span in ordered:
            span_text = span.text or ""
            span_color = tuple(float(c) for c in (span.color or default_color))
            for ch in span_text:
                source_chars.append(ch)
                source_colors.append(span_color)
        source_text = "".join(source_chars)
        if not source_text or not source_colors:
            return self._convert_text_to_html(
                new_text, 12, default_color, latin_font=latin_font
            )

        new_colors: list[tuple | None] = [None] * len(new_text)
        matcher = difflib.SequenceMatcher(a=source_text, b=new_text, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    new_colors[j1 + k] = source_colors[i1 + k]
            else:
                inherit = source_colors[i1 - 1] if i1 > 0 else source_colors[0]
                for k in range(j2 - j1):
                    new_colors[j1 + k] = inherit
        for idx in range(len(new_colors)):
            if new_colors[idx] is None:
                new_colors[idx] = tuple(float(c) for c in default_color)

        latin_font_name = self._resolve_add_text_font(latin_font)
        cjk_font_name = self._resolve_cjk_companion_font(latin_font_name)
        latin_css_family = self._font_token_to_css_family(latin_font_name)
        cjk_css_family = self._font_token_to_css_family(cjk_font_name)

        html_parts: list[str] = []
        idx = 0
        while idx < len(new_text):
            run_color = cast(tuple, new_colors[idx])
            start = idx
            idx += 1
            while idx < len(new_text) and new_colors[idx] == run_color:
                idx += 1
            chunk = new_text[start:idx]
            r = int(round(run_color[0] * 255))
            g = int(round(run_color[1] * 255))
            b = int(round(run_color[2] * 255))
            color_css = f"color: rgb({r}, {g}, {b});"
            for part in _RE_HTML_TEXT_PARTS.findall(chunk):
                if part == "\n":
                    html_parts.append("<br>")
                elif part.isspace():
                    html_parts.append(
                        f'<span style="font-family: {latin_css_family}; {color_css}">{part}</span>'
                    )
                elif _RE_CJK.match(part):
                    html_parts.append(
                        f'<span style="font-family: {cjk_css_family}; {color_css}">{_html_mod.escape(part)}</span>'
                    )
                else:
                    html_parts.append(
                        f'<span style="font-family: {latin_css_family}; {color_css}">{_latin_word_html(part)}</span>'
                    )
        return "".join(html_parts)


    # ──────────────────────────────────────────────────────────────────────────
    # Phase 6: 文件整體快照（供 SnapshotCommand undo/redo 使用）
    # ──────────────────────────────────────────────────────────────────────────

    def _capture_doc_snapshot(self) -> bytes:
        """擷取整份文件的 bytes 快照（SnapshotCommand before/after 用）。

        encryption=KEEP：save() 的 encryption 預設為 NONE(1) 會解密。doc-level 快照
        在還原時會「整份取代」live doc（_restore_doc_from_snapshot 重新 fitz.open），
        若快照已解密，undo 後 live doc 即失去加密，下次存檔便遺失密碼。保留來源加密，
        還原端再以 session 密碼重新驗證即可。（page-level 快照為原地插頁、不取代
        live handle，加密狀態不受影響，另案追蹤。）
        """
        # Same bytes as ``_save_doc(self.doc, io.BytesIO())`` (garbage=0, KEEP, a new
        # /ID), written by MuPDF's native sink: the Python file object cost ~4.5 us
        # per xref row, 2 x 19 s per edit on a 4M-slot table (H10-2).
        data = self.serialize_document_bytes(self.doc)
        # The bookkeeping book rides on the bytes (see ``DocSnapshot``): every
        # SnapshotCommand's before/after pair comes from here, so undo/redo
        # restore the pending/protected state together with the document.
        return DocSnapshot.of(
            data,
            MaintenanceBook.capture(self),
            xref_epoch=self.xref_epoch,
            page_state=self.capture_page_state(),
        )

    def capture_page_state(self) -> dict[str, object] | None:
        """The tools' page-bound state (a watermark's page identity) of the active session.

        Rides on every document snapshot (``DocSnapshot.page_state``) so undo, redo and the
        rollback of a failed op bring it back together with the bytes (F17-COH-3).
        """
        session_id = self.get_active_session_id()
        tools = getattr(self, "tools", None)
        if not session_id or tools is None:
            return None
        return tools.capture_page_state(session_id) or None

    def _pages_restructured(self, origins: Sequence[int | None], *, old_count: int) -> None:
        """Tell everything that keys state by page number that the page list changed.

        THE chokepoint of delete / move / insert / merge (F17-COH-3).  ``origins[j]`` is the
        1-based page of the previous list that new page ``j + 1`` is, ``None`` for a page
        that did not exist, so a page may repeat (a merge that uses the document twice) or
        be missing (deleted).  The page-indexed maintenance bookkeeping
        (``pending_edits``, ``fidelity_protected_pages``) and the tools (a watermark's
        pages) move with their pages; undo / redo / rollback restore both from the snapshot.
        A method that changes ``self.doc``'s page list without calling this fails the source
        scan ``test_multi_tab_plan.py::test_04l``.
        """
        self._remap_page_bookkeeping(origins)
        session_id = self.get_active_session_id()
        if session_id:
            self.tools.on_pages_restructured(session_id, origins, old_count)

    def _remap_page_bookkeeping(self, origins: Sequence[int | None]) -> None:
        successors: dict[int, list[int]] = {}
        for new_idx, origin in enumerate(origins):
            if origin is not None:
                successors.setdefault(origin - 1, []).append(new_idx)
        self.pending_edits = [
            {**entry, "page_idx": new_idx}
            for entry in self.pending_edits
            for new_idx in successors.get(entry.get("page_idx"), ())
        ]
        protected = self.fidelity_protected_pages
        moved = {new_idx for old_idx in protected for new_idx in successors.get(old_idx, ())}
        protected.clear()
        protected.update(moved)

    def _prepare_derived_document(self, doc: fitz.Document, origins: Sequence[int | None]) -> None:
        """Run a PDF built from the session's pages through the same bake as Save (F17-COH-4).

        ``origins[j]`` is the 1-based live page that page ``j + 1`` of ``doc`` was copied
        from (``None``: from elsewhere).  Every PDF the app writes from the session's
        pages passes here (``export_pages``, ``compose_merged_document``); the source scan
        ``test_merge_composition.py::test_every_caller_of_save_external_document_...``
        fails a writer that skips it.
        """
        session_id = self.get_active_session_id()
        if session_id:
            self.tools.prepare_derived_document(session_id, doc, origins)

    def serialize_document_bytes(
        self,
        doc: fitz.Document,
        *,
        garbage: int = 0,
        no_new_id: int = 0,
        deflate: int = 0,
        encryption: int = fitz.PDF_ENCRYPT_KEEP,
        in_memory: bool = False,
    ) -> bytes:
        """``doc.tobytes(...)`` through MuPDF's native output (H10-2 Part B, ``model.doc_bytes``).

        Every whole-document snapshot in the model goes through here.  The default
        ``encryption`` is KEEP (the ``_save_doc`` invariant).  The temp file goes to
        this model's private temp dir; a decrypted copy of an encrypted document,
        a caller-flagged plaintext copy (``in_memory``) and every snapshot of a
        secure-latched session (its garbage=0 bytes still hold what the
        destructive edit removed) stay in memory instead.
        """
        temp_dir = getattr(self, "temp_dir", None)
        return doc_bytes.serialize_doc(
            doc,
            garbage=garbage,
            no_new_id=no_new_id,
            deflate=deflate,
            encryption=encryption,
            scratch_dir=None if temp_dir is None else temp_dir.name,
            in_memory=in_memory or bool(self.secure_save_required),
        )

    def capture_worker_snapshot_bytes(self) -> bytes:
        """Capture snapshot bytes for background worker readers."""
        if not self.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        return self._decrypted_snapshot_bytes(garbage=0)

    def capture_session_transfer_bytes(self) -> bytes:
        """Capture the live doc for a tab detached into another window (F11-OPEN-1).

        Unlike the worker/print snapshots this one becomes a *live session*
        (``import_session_transfer``), so it must keep the source encryption:
        decrypted bytes would leave the new window's session unencrypted and its
        first ``encryption=KEEP`` save would write the file back with the password
        and permissions stripped.  ``garbage=0`` keeps the xref numbering.
        """
        if not self.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        return self._encryption_keeping_bytes(self.doc)

    def _encryption_keeping_bytes(self, doc: fitz.Document) -> bytes:
        """``garbage=0`` / ``encryption=KEEP`` serialization of ``doc``.

        Numbering-preserving and safe on an authenticated live handle (unlike
        ``encryption=NONE``, see ``_decrypted_snapshot_bytes``).  Opening the
        result yields a *locked* handle for an encrypted source; the caller
        re-authenticates it.
        """
        return self.serialize_document_bytes(
            doc, garbage=0, no_new_id=1, encryption=fitz.PDF_ENCRYPT_KEEP
        )

    def capture_print_snapshot_bytes(self) -> bytes:
        """Capture print input, pruning destructive-edit orphans when required."""
        if not self.doc:
            raise RuntimeError("沒有開啟的 PDF 文件")
        if not self.secure_save_required:
            return self.capture_worker_snapshot_bytes()
        return self._decrypted_snapshot_bytes(garbage=4)

    def _decrypted_snapshot_bytes(self, *, garbage: int) -> bytes:
        """Decrypt-and-flatten the live doc into plain bytes for worker/print readers.

        ``tobytes(encryption=NONE)`` on an *encrypted* live handle silently
        corrupts its internal crypt state (a PyMuPDF/MuPDF AES quirk): a later
        ``encryption=KEEP`` save on that same handle then writes content
        streams that no longer decrypt (blank pages on reopen), even though
        the save itself reports success and needs_pass/is_encrypted look
        normal. Since worker/print snapshots are captured on every render --
        long before any save -- this would silently poison the *next* save.
        Route the decrypt through a throwaway clone opened from an
        ``encryption=KEEP`` snapshot instead, so rendering/printing can never
        touch the live handle's crypt state. Skipped for unencrypted docs with
        ``garbage < 2``: cloning there is pure overhead.

        ``garbage >= 2`` (the secure-session print prune) ALWAYS runs on the
        clone: serializing the LIVE handle with it renumbers the document in
        place, which strands every page-snapshot undo/redo and every xref the
        UI listed (DS-1).  The live handle only ever sees ``garbage=0``.

        The decrypted bytes of an encrypted clone never touch disk: ``model.doc_bytes``
        writes them into an in-memory MuPDF buffer (H10-2 Part B).
        """
        doc: fitz.Document = self.doc
        if garbage < 2 and not self._doc_is_encrypted(doc):
            return self.serialize_document_bytes(
                doc, garbage=garbage, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE
            )
        clone = self._open_numbering_clone(doc)
        try:
            return self.serialize_document_bytes(
                clone, garbage=garbage, no_new_id=1, encryption=fitz.PDF_ENCRYPT_NONE
            )
        finally:
            clone.close()

    def _open_numbering_clone(self, doc: fitz.Document) -> fitz.Document:
        """Throwaway, authenticated clone of ``doc`` with IDENTICAL xref numbering.

        The clone is built from a ``garbage=0`` / ``encryption=KEEP`` serialization of
        the live handle (numbering-preserving, crypt-state safe), so any
        renumbering or pruning serialization can run on the clone instead of the
        live document.  The caller closes it.
        """
        return self._open_authenticated(
            self._encryption_keeping_bytes(doc), "worker/print 快照重新驗證密碼失敗"
        )

    def _open_authenticated(self, data: bytes, failure_message: str) -> fitz.Document:
        """Open ``data`` (an ``encryption=KEEP`` serialization) and unlock it with the session password.

        ``needs_pass`` is read exactly once, on the handle ``fitz.open`` just
        returned and before ``authenticate`` (R9 M9-1: on an authenticated handle
        the read clobbers its crypt key).  An unencrypted ``data``, and an
        owner-password-only one that opens without a prompt, need no password.
        Raises ``RuntimeError(failure_message)`` and closes the handle when the
        session has no password or it is rejected.
        """
        fresh = fitz.open("pdf", data)
        try:
            if fresh.needs_pass:
                password = self.password
                if password is None or fresh.authenticate(password) == 0:
                    raise RuntimeError(failure_message)
        except BaseException:
            fresh.close()
            raise
        return fresh

    def write_pruned_live_copy(self, dest: str | Path, *, garbage: int) -> None:
        """Write a ``garbage``-pruned copy of the live doc to ``dest`` (source encryption kept).

        A read-only export (print input): the prune (``garbage >= 2`` renumbers) runs
        on a clone, so the live document, its ``xref_epoch`` and every retained
        page snapshot / listed xref stay valid.  ``garbage < 2`` serializes the live
        handle directly (numbering-preserving).
        """
        doc: fitz.Document | None = self.doc
        if doc is None:
            raise RuntimeError("沒有開啟的 PDF 文件")
        if garbage < 2:
            self._save_doc(doc, str(dest), garbage=garbage)
            return
        clone = self._open_numbering_clone(doc)
        try:
            self._save_doc(clone, str(dest), garbage=garbage)
        finally:
            clone.close()

    @staticmethod
    def preset_optimize_options(preset: str) -> PdfOptimizeOptions:
        return pdf_optimizer.preset_optimize_options(preset)

    @staticmethod
    def _normalize_optimize_options(options: PdfOptimizeOptions) -> PdfOptimizeOptions:
        return pdf_optimizer.normalize_optimize_options(options)

    def _resolve_file_backed_optimize_source(self, session_id: str | None) -> Path | None:
        return pdf_optimizer.resolve_file_backed_optimize_source(self, session_id)

    def _current_document_size_bytes(self, session_id: str | None) -> int:
        return pdf_optimizer.current_document_size_bytes(self, session_id)

    def _build_working_doc_for_optimized_copy(self, session_id: str | None) -> fitz.Document:
        return pdf_optimizer.build_working_doc_for_optimized_copy(self, session_id)

    def _make_active_audit_cache_key(self) -> tuple | None:
        return pdf_optimizer.make_active_audit_cache_key(self)

    def get_editable_metadata(self) -> dict[str, str]:
        keys = ("title", "author", "subject", "keywords")
        if not self.doc:
            return {key: "" for key in keys}
        metadata = self.doc.metadata or {}
        return {key: str(metadata.get(key) or "") for key in keys}

    def set_editable_metadata(self, values: dict[str, object]) -> bool:
        if not self.doc:
            raise ValueError("沒有開啟的PDF文件")
        if not isinstance(values, dict):
            raise TypeError("metadata payload must be a dict")
        allowed = {"title", "author", "subject", "keywords"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unsupported metadata fields: {sorted(unknown)}")
        normalized: dict[str, str] = {}
        for key in allowed:
            value = values.get(key, "")
            if value is None:
                normalized[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                normalized[key] = str(value)
            else:
                raise TypeError(f"metadata field {key!r} must be scalar")
        current = self.get_editable_metadata()
        if normalized == current:
            return False
        metadata = {
            str(key): str(value or "")
            for key, value in (self.doc.metadata or {}).items()
        }
        metadata.update(normalized)
        with exact_set_key(self.doc):
            self.doc.set_metadata(metadata)
        self.secure_save_required = True
        return True

    @staticmethod
    def _blank_metadata_dict(doc: fitz.Document) -> dict[str, str]:
        return pdf_optimizer.blank_metadata_dict(doc)

    @staticmethod
    def _xref_size_bytes(doc: fitz.Document, xref: int) -> int:
        return pdf_optimizer.xref_size_bytes(doc, xref)

    def build_pdf_audit_report(self, doc: fitz.Document | None = None) -> PdfAuditReport:
        return pdf_optimizer.build_pdf_audit_report(self, doc)

    def _apply_optimize_options(
        self,
        working_doc: fitz.Document,
        options: PdfOptimizeOptions,
        source_path: Path | None = None,
        *,
        original_bytes: int | None = None,
        image_usage: dict[int, dict[str, float | int]] | None = None,
    ) -> None:
        pdf_optimizer.apply_optimize_options(
            self,
            working_doc,
            options,
            source_path=source_path,
            original_bytes=original_bytes,
            image_usage=image_usage,
        )

    @staticmethod
    def _image_rewrite_settings(options: PdfOptimizeOptions) -> dict[str, int | bool]:
        return pdf_optimizer.image_rewrite_settings(options)

    @staticmethod
    def _parallel_image_worker_count(image_count: int) -> int:
        return pdf_optimizer.parallel_image_worker_count(image_count)

    @staticmethod
    def _can_use_parallel_image_rewrite() -> bool:
        return pdf_optimizer.can_use_parallel_image_rewrite()

    @staticmethod
    def optimize_capabilities() -> dict[str, bool]:
        # Runtime probe for optional post-save packaging (pikepdf-backed
        # linearize / object streams); the controller feeds this to the dialog.
        return pdf_optimizer.optimize_capabilities()

    def _rewrite_images_serially(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
        options: PdfOptimizeOptions,
    ) -> None:
        pdf_optimizer.rewrite_images_serially(self, working_doc, image_usage, options)

    def _collect_extracted_images(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
    ) -> list[tuple[int, int, float, bytes]]:
        return pdf_optimizer.collect_extracted_images(self, working_doc, image_usage)

    def _rewrite_images_from_source_in_parallel(
        self,
        working_doc: fitz.Document,
        image_usage: dict[int, dict[str, float | int]],
        options: PdfOptimizeOptions,
        source_path: Path,
    ) -> None:
        pdf_optimizer.rewrite_images_from_source_in_parallel(self, working_doc, image_usage, options, source_path)

    def _rewrite_extracted_images_in_parallel(
        self,
        working_doc: fitz.Document,
        extracted_images: list[tuple[int, int, float, bytes]],
        options: PdfOptimizeOptions,
    ) -> None:
        pdf_optimizer.rewrite_extracted_images_in_parallel(self, working_doc, extracted_images, options)

    def _rewrite_images_with_pillow(
        self,
        working_doc: fitz.Document,
        options: PdfOptimizeOptions,
        source_path: Path | None = None,
        *,
        image_usage: dict[int, dict[str, float | int]] | None = None,
        allow_extracted_parallel_fallback: bool = True,
    ) -> None:
        pdf_optimizer.rewrite_images_with_pillow(
            self,
            working_doc,
            options,
            source_path=source_path,
            image_usage=image_usage,
            allow_extracted_parallel_fallback=allow_extracted_parallel_fallback,
        )

    @staticmethod
    def _requires_post_save_packaging(options: PdfOptimizeOptions) -> bool:
        return pdf_optimizer.requires_post_save_packaging(options)

    @staticmethod
    def _fast_save_kwargs(options: PdfOptimizeOptions) -> dict[str, int]:
        return pdf_optimizer.fast_save_kwargs(options)

    def _postprocess_optimized_pdf_with_pikepdf(self, source_path: Path, options: PdfOptimizeOptions) -> None:
        pdf_optimizer.postprocess_optimized_pdf_with_pikepdf(self, source_path, options)

    def _save_optimized_working_doc(self, working_doc: fitz.Document, temp_save: Path, options: PdfOptimizeOptions) -> None:
        pdf_optimizer.save_optimized_working_doc(self, working_doc, temp_save, options)

    def save_optimized_copy(
        self,
        new_path: str,
        options: PdfOptimizeOptions | None = None,
        session_id: str | None = None,
        credentials: OptimizeOutputCredentials | None = None,
    ) -> PdfOptimizationResult:
        # Optimize-copy is a strict "write a new file" workflow.
        # Implementation is delegated so `PDFModel` does not become an optimizer grab-bag.
        # session_id binds the job to its source tab (R5-03); None = active session.
        return pdf_optimizer.save_optimized_copy(
            self,
            new_path,
            options,
            session_id,
            credentials=credentials,
        )

    def capture_optimize_source(self, session_id: str) -> OptimizeSourceSnapshot:
        return pdf_optimizer.capture_optimize_source(self, session_id)

    def save_optimized_copy_from_snapshot(
        self,
        snapshot: OptimizeSourceSnapshot,
        new_path: str,
        options: PdfOptimizeOptions | None = None,
        credentials: OptimizeOutputCredentials | None = None,
    ) -> PdfOptimizationResult:
        return pdf_optimizer.save_optimized_copy_from_snapshot(
            self,
            snapshot,
            new_path,
            options,
            credentials=credentials,
        )

    def _restore_doc_from_snapshot(self, snapshot_bytes: bytes, *, restore_tool_state: bool = True) -> None:
        """用 bytes 快照替換整份文件（SnapshotCommand undo/redo 時呼叫）。

        快照以 encryption=KEEP 擷取，故為加密檔案時重新開啟的 handle 會是鎖定狀態；
        以 session 保存的密碼重新驗證後 live session 才能繼續算繪/編輯。未加密文件
        為 no-op。
        """
        # typed bind; callers guarantee an open doc here (see replace_active_document_from_snapshot) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        # Open the replacement first: a bad snapshot must not leave the session
        # on a closed handle (an in-memory doc holds no file lock to release).
        fresh = self._reauthenticate_if_needed(fitz.open("pdf", snapshot_bytes))
        doc.close()
        self.doc = fresh
        self._sweep_retired_live_copies(collect=True)
        # A whole-document snapshot is serialized at garbage=0, which keeps the
        # xref numbering: reinstate the epoch it was captured under so page
        # snapshots taken in that numbering are valid again.
        epoch = getattr(snapshot_bytes, "xref_epoch", None)
        if isinstance(epoch, int):
            self._set_xref_epoch(epoch)
        # A snapshot from ``_capture_doc_snapshot`` carries the maintenance book
        # taken with it (see ``DocSnapshot``).  The bytes and the book travel
        # together HERE, the one place every document-snapshot restore passes
        # through (SnapshotCommand undo/redo, the batch-delete / delete_pages /
        # move_page rollbacks, the cross-page-move rollback): a content rewrite
        # revokes a page's fidelity protection and queues a clean_contents entry,
        # so putting only the bytes back leaves a verified Tier 0 page
        # unprotected and pending.  Plain bytes carry no book and touch nothing.
        book = getattr(snapshot_bytes, "book", None)
        if isinstance(book, MaintenanceBook):
            book.restore(self)
        # Same for the tools' page identity (a watermark's pages, F17-COH-3): the page
        # list the bytes hold and the ids the tools key their pages by come back together.
        page_state = getattr(snapshot_bytes, "page_state", None)
        session_id = self.get_active_session_id()
        if restore_tool_state and isinstance(page_state, dict) and session_id:
            self.tools.restore_page_state(session_id, page_state)
        logger.debug(f"_restore_doc_from_snapshot: 已還原文件（{len(snapshot_bytes)} bytes）")

    def replace_active_document_from_snapshot(
        self,
        snapshot_bytes: bytes,
        affected_pages: list[int] | None = None,
        *,
        page_origins: Sequence[int | None] | None = None,
    ) -> None:
        """Swap the live document for ``snapshot_bytes``.

        ``page_origins`` is for a document whose page LIST differs from the live one (the
        merge): ``page_origins[j]`` is the live page that new page ``j + 1`` is (``None``: a
        new page).  The page-bound state follows through ``_pages_restructured``; without it
        the snapshot must hold the same pages (a rollback, undo) and its own page state is
        restored with it.
        """
        if not snapshot_bytes:
            raise ValueError("缺少文件快照")
        old_count = len(self.doc) if self.doc is not None else 0
        # Reinstates the snapshot's maintenance book with the bytes (see
        # ``_restore_doc_from_snapshot``).
        if page_origins is None:
            self._restore_doc_from_snapshot(snapshot_bytes)
        else:
            self._restore_doc_from_snapshot(snapshot_bytes, restore_tool_state=False)
            self._pages_restructured(page_origins, old_count=old_count)
        self.refresh_structural_indexes(affected_pages or [1])

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 3: 頁面快照（取代 clone_page）
    # ──────────────────────────────────────────────────────────────────────────

    def _roundtrip_live_doc(self, *, garbage: int, deflate: bool) -> None:
        """Round-trip the live document through its own bytes, then make the fresh
        handle the active doc — preserving encryption and re-authenticating it.

        Single chokepoint for the invariant *a live-doc round-trip must not
        decrypt*: ``tobytes``/``save`` default to ``encryption=NONE``, which
        silently strips the password in memory and drops it on the next save. Every
        ``self.doc = fitz.open(self.doc.tobytes(...))`` (in-memory GC, in-memory
        repair, …) must go through here. Whole-document undo/redo snapshots
        (``_capture_doc_snapshot`` -> ``_save_doc``) and the detached-window
        transfer (``capture_session_transfer_bytes`` -> ``import_session_transfer``)
        keep the encryption the same way and re-authenticate on reopen.

        Opens the new handle *before* closing the old one, so if serialization or
        reopen fails the live doc is left intact for the caller to keep using.
        """
        # typed bind; callers guarantee an open doc here (see _repair_active_doc_in_memory guard) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        data = self.serialize_document_bytes(
            doc, garbage=garbage, deflate=int(deflate), encryption=fitz.PDF_ENCRYPT_KEEP
        )
        old = doc
        epoch_before = self.xref_epoch
        self.doc = self._reauthenticate_if_needed(fitz.open("pdf", data))
        if garbage <= 1:
            # garbage 0/1 keeps the numbering (it only frees unreferenced objects).
            self._set_xref_epoch(epoch_before)
        try:
            old.close()
        except Exception:
            pass
        self._sweep_retired_live_copies(collect=True)

    @staticmethod
    def _save_doc(
        doc: fitz.Document,
        target: str | io.BytesIO,
        *,
        garbage: int = 0,
        incremental: bool = False,
    ) -> None:
        """Single chokepoint for writing a document out to a path/stream.

        Always passes ``encryption=fitz.PDF_ENCRYPT_KEEP``. ``save()`` defaults to
        ``encryption=NONE(1)``, which actively *decrypts*: a full rewrite drops the
        password/permissions, and an incremental save even *raises* ("Can't do
        incremental writes when changing encryption"). KEEP is a no-op for
        unencrypted docs and preserves the source encryption otherwise. Sibling to
        ``_roundtrip_live_doc`` (the funnel for the serialize-and-replace variant).
        """
        doc.save(
            target, garbage=garbage, incremental=incremental, encryption=fitz.PDF_ENCRYPT_KEEP
        )

    def _save_doc_to_user_path(self, doc: fitz.Document, path: str | Path, *, garbage: int = 0) -> None:
        """``_save_doc`` for a destination the user chose (it may hold their last good file).

        MuPDF's path output truncates the destination as it opens it, so a
        writer that fails half way (disk full) would destroy an existing file.
        Serialise into a sibling staging file and ``os.replace`` it over the
        target instead (PERS-2 / LS-2): the target is either the old file or
        the complete new one.  Every non-secure full save to a user path goes
        through here, whatever backs the live doc (a path, or memory after a
        snapshot undo/redo) and whether or not the target is the open file.
        The live handle is never touched: callers that need the open-file
        install (``_install_stage_over_open_file``) stage on their own.
        """
        write_via_staging(path, lambda stage: self._save_doc(doc, stage, garbage=garbage), "save")

    def _atomic_full_save(
        self,
        doc: fitz.Document,
        path: str | Path,
        *,
        garbage: int = 4,
        replace_live_handle: bool = False,
    ) -> None:
        """Validate a same-directory full rewrite before atomically installing it.

        Keeping the staging file beside the destination preserves the atomicity
        guarantee of ``os.replace``.  Nothing touches the live handle until the
        staged file has been serialized and reopened successfully.

        With ``replace_live_handle`` (the target is the file the live handle
        reads, so Windows refuses the replace while it is open) the install is
        delegated to ``_install_stage_over_open_file`` with a recovery copy of
        the LIVE doc: if the replace fails (or the post-replace reopen does) the
        session is rebound to that copy, so the unsaved edits and the session
        survive.  Reopening the *target* instead would show the old on-disk
        content while the stage, the only file holding the edits, is deleted.
        """
        target = resolve_as_requested(path)
        stage = staging_sibling(target, "tmp")
        garbage = max(4, int(garbage))
        try:
            self._save_doc(doc, str(stage), garbage=garbage, incremental=False)
            self._note_live_doc_serialized(doc, garbage)
            probe = fitz.open(str(stage))
            try:
                if probe.needs_pass:
                    password = self.password
                    if password is None or probe.authenticate(password) == 0:
                        raise RuntimeError("staged PDF could not be re-authenticated")
                # Force the xref/page tree to be read before the original is touched.
                len(probe)
            finally:
                probe.close()

            if replace_live_handle:
                # typed bind; replace_live_handle path guarantees an open live doc - runtime behavior identical if None (name live_doc avoids the `doc` param)
                live_doc: fitz.Document = self.doc
                recovery = self.private_temp_file("recover")
                try:
                    if doc is live_doc:
                        # The stage is the live doc's own garbage>=2 serialization
                        # (the live doc was renumbered to match it): a byte copy
                        # is the recovery copy.
                        shutil.copy2(str(stage), str(recovery))
                    else:
                        # ``doc`` is a prepared clone (watermark overlay): the
                        # session must keep the LIVE doc, not the clone.
                        self._save_doc(live_doc, str(recovery), garbage=4)
                        self._note_live_doc_serialized(live_doc, 4)
                except BaseException:
                    self._discard_staged_file(recovery)
                    raise
                self._install_stage_over_open_file(
                    stage, str(target), recovery=recovery, keep_live_content=doc is not live_doc
                )
                self._note_persisted_baseline()
            else:
                replace_file(stage, target)
        finally:
            try:
                stage.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("unable to remove staged save %s: %s", stage, exc)

    def save_external_document(
        self,
        doc: fitz.Document,
        path: str | Path,
        *,
        sanitize: bool | None = None,
    ) -> None:
        """Persist an exported/merged document under the active security policy."""
        # An export / merge target must never be a file a live handle reads:
        # the in-place rewrite would corrupt that tab's unread pages.
        if self._session_reading_path(path) is not None or self._active_doc_reads_path(path):
            raise RuntimeError("目標路徑已被開啟的文件使用，請改用不同檔名。")
        # Export and merge write the ACTIVE session's content: a damaged one
        # must not land on the file it protects, which after a Save As no live
        # handle reads any more (F14-DMG-1).
        self._refuse_write_over_damaged_original(path, message=DAMAGED_SESSION_WRITE_MESSAGE)
        must_sanitize = self.secure_save_required if sanitize is None else bool(sanitize)
        if must_sanitize:
            self._atomic_full_save(doc, path, garbage=4)
        else:
            self._save_doc_to_user_path(doc, path)

    def _repair_active_doc_in_memory(self, garbage: int = 1) -> bool:
        """Try to repair current doc by round-tripping bytes and reopen in memory."""
        if not self.doc:
            return False
        try:
            self._roundtrip_live_doc(garbage=max(1, int(garbage)), deflate=True)
            self.block_manager.build_index(self.doc)
            logger.warning("已以 in-memory roundtrip 修復目前文件（garbage=%s）", max(1, int(garbage)))
            return True
        except Exception as e:
            logger.warning("修復目前文件失敗: %s", self._safe_exc_message(e))
            return False

    def _capture_page_snapshot_strict(self, page_num_0based: int) -> PageSnapshot:
        """Capture the page's object graph (see ``model.page_snapshot``).

        Never falls back to a whole-document snapshot (a page restore would
        misapply it).  A failed walk is retried once after an in-memory
        garbage=1 repair round trip (which keeps the xref numbering).
        """
        if not self.doc or page_num_0based < 0 or page_num_0based >= len(self.doc):
            raise ValueError(f"無效頁碼: {page_num_0based + 1}")
        try:
            return capture_page_graph(self.doc, page_num_0based, xref_epoch=self.xref_epoch)
        except PageSnapshotError as first:
            last_err: Exception = first
        if self._repair_active_doc_in_memory(garbage=1) and self.doc and page_num_0based < len(self.doc):
            try:
                return capture_page_graph(self.doc, page_num_0based, xref_epoch=self.xref_epoch)
            except PageSnapshotError as second:
                last_err = second
        msg = self._safe_exc_message(last_err)
        raise RuntimeError(
            f"無法擷取頁面快照（strict, page={page_num_0based + 1}）: {msg}"
        )

    def _capture_page_snapshot(self, page_num_0based: int) -> PageSnapshot:
        """擷取指定頁面的物件圖快照，供 undo / rollback 使用（同 strict 版本）。"""
        return self._capture_page_snapshot_strict(page_num_0based)

    def _restore_page_from_snapshot(self, page_num_0based: int, snapshot: bytes) -> None:
        """Put a captured page back IN PLACE by xref (undo / redo / rollback).

        ``PageSnapshotStale`` (zero mutation) and ``RuntimeError`` (a failed
        write, page put back) propagate.  There is no graft fallback.
        """
        if not isinstance(snapshot, PageSnapshot):
            raise TypeError("page restore requires a PageSnapshot")
        # typed bind; callers guarantee an open doc here (undo/rollback path)
        doc: fitz.Document = self.doc
        restore_page_graph(doc, page_num_0based, snapshot, xref_epoch=self.xref_epoch)

    def _build_insert_css(
        self,
        size: float,
        color: tuple,
        font_hint: str = "helv",
        line_height: float = 0.0,
    ) -> str:
        """建構 insert_htmlbox 所需的 CSS 樣式字串。

        line_height: 實際行高（pt）。0 表示自動計算（size × 1.2，或從字體 metrics 取得）。
        正確的行高能讓 re-insert 後的文字行距與原 PDF 一致。
        """
        resolved_font = self._resolve_add_text_font(font_hint)
        cjk_companion = self._resolve_cjk_companion_font(resolved_font)
        font_face_rules = []
        for token in {resolved_font, cjk_companion}:
            css_rule = self._font_face_css_for_token(token)
            if css_rule:
                font_face_rules.append(css_rule)
        font_face_block = "\n".join(font_face_rules)

        # 行高：優先使用傳入值，否則從字體 metrics 計算。
        # max(size, ...) 夾擠只在「自動計算」分支生效；呼叫端傳入的
        # 明確行高（含緊湊 leading，如 8pt < 10pt 字級）必須原樣保留，
        # 否則 re-insert 後文字會比原 PDF 高、推擠下方文字。
        if line_height <= 0:
            try:
                font_obj = fitz.Font(resolved_font)
                line_height = max(size * 1.1, (font_obj.ascender - font_obj.descender) * size)
            except Exception:
                line_height = size * 1.2
            line_height = round(max(size, line_height), 2)
        else:
            line_height = round(line_height, 2)

        return f"""
            {font_face_block}
            span {{
                font-size: {size}pt;
                line-height: {line_height}pt;
                white-space: pre-wrap;
                word-break: break-all;
                overflow-wrap: anywhere;
                color: rgb({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)});
            }}
            .helv {{ font-family: helv; }}
            .cjk {{ font-family: cjk; }}
        """

    def apply_pending_redactions(self, pages: Iterable[int] | None = None) -> None:
        """
        批次清理已修改頁面的 content stream（Phase 6 效能優化）。
        對每個 pending_edit 中記錄的頁面呼叫 page.clean_contents()，
        壓縮 content stream、移除孤立資源，可降低 PDF 大小 10-30%。
        應在 save() 前或每 5 次編輯時呼叫。

        ``pages=None`` cleans every queued page (the save-time pass, which sits
        outside the undo history).  A page set limits the pass to those 0-based
        pages and leaves every other page's bytes AND queue entries alone: the
        interactive pass runs inside one edit's undo unit, and that unit only
        snapshots and book-keeps its own page (F14-MM-4).
        """
        if not self.pending_edits or not self.doc:
            return
        scope = None if pages is None else {int(p) for p in pages}
        # V2 maintenance policy: a fidelity-protected page (Tier 0 lossless
        # commit) must never pass through clean_contents — it would rewrite
        # the stream and destroy the verified byte identity. Its pending
        # entries are preserved for the day its protection is revoked
        # (mark_page_content_dirty on a later legacy rewrite).
        protected = set(self.fidelity_protected_pages)
        unique_pages = {
            e["page_idx"]
            for e in self.pending_edits
            if scope is None or e["page_idx"] in scope
        }
        skipped = unique_pages & protected
        if skipped:
            logger.debug(
                "apply_pending_redactions: 跳過 fidelity-protected 頁面 %s",
                sorted(skipped),
            )
        cleaned = 0
        for page_idx in sorted(unique_pages - skipped):
            if 0 <= page_idx < len(self.doc):
                try:
                    self.doc[page_idx].clean_contents()
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"clean_contents 失敗（頁面 {page_idx + 1}）: {e}")
        logger.debug(
            f"apply_pending_redactions: 已清理 {cleaned}/{len(unique_pages)} 頁的 content stream"
        )
        self.pending_edits = [
            e
            for e in self.pending_edits
            if e["page_idx"] in skipped or (scope is not None and e["page_idx"] not in scope)
        ]

    def _maybe_garbage_collect(self, page_idx: int | None = None) -> None:
        """
        Interactive maintenance performs page-local ``clean_contents`` only.

        Whole-document garbage=4 rewrites are deliberately deferred to the
        persistence boundary: doing them here blocks the GUI, rebuilds the full
        text index, and renumbers xrefs while object markers are live.

        ``page_idx`` is the page of the edit that triggered the pass: only that
        page is cleaned (F14-MM-4).  The edit's undo unit snapshots and
        book-keeps exactly that page, so cleaning another queued page here would
        rewrite bytes no command can restore; those entries wait for the
        save-time pass.  ``None`` keeps the legacy "every queued page" scope.
        """
        if self.edit_count <= 0:
            return
        # 輕量層：每 5 次清理 content stream
        if self.edit_count % 5 == 0:
            self.apply_pending_redactions(None if page_idx is None else (page_idx,))

    # ──────────────────────────────────────────────────────────────────────────
    # Push-Down 輔助方法：換行溢出時保留並推移下方文字塊
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_font_for_push(self, raw_font_name: str) -> str:
        """
        將 get_text("dict") 返回的字體名稱（如 'ABCDEF+ArialMT'）轉為
        page.insert_text() 可接受的名稱。若原字體不可用則回退至最接近的
        PyMuPDF 內建字體（helv / tiro / cour 系列）。
        """
        # 去除嵌入子集前綴（如 "ABCDEF+Arial" → "Arial"）
        base = raw_font_name.split("+", 1)[-1] if "+" in raw_font_name else raw_font_name

        # 嘗試直接使用原名稱
        try:
            fitz.Font(base)
            return base
        except Exception:
            pass

        # 依字體名稱特徵回退至 PyMuPDF 內建字體
        low = base.lower()
        is_bold   = "bold"   in low
        is_italic = "italic" in low or "oblique" in low
        is_mono   = "courier" in low or "mono" in low or "typewriter" in low
        is_serif  = "times" in low or "roman" in low or "georgia" in low

        if is_mono:
            if is_bold and is_italic:
                return "cour-bi"
            if is_bold:
                return "cour-b"
            if is_italic:
                return "cour-i"
            return "cour"
        if is_serif:
            if is_bold and is_italic:
                return "tibo"
            if is_bold:
                return "tib"
            if is_italic:
                return "tiit"
            return "tiro"
        # sans-serif (Helvetica / Arial / 其他)
        if is_bold and is_italic:
            return "heit"
        if is_bold:
            return "hebo"
        if is_italic:
            return "heit"
        return "helv"

    def _needs_cjk_font(self, text: str) -> bool:
        """
        判斷文字是否包含 CJK（中日韓）字符。
        供文字重播/插入時挑選可用 fallback 字體，避免缺字。
        """
        if not text:
            return False
        return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))

    # R3.5: edit-text / redaction engine extracted to model/pdf_text_edit.py.
    # These stay as 1-line delegating wrappers so the test net (which pokes the
    # private helpers directly and monkeypatches _push_down_overlapping_text) and
    # the public edit_text API are preserved byte-for-byte in behaviour.
    def _has_complex_script(self, *args, **kwargs):
        return pdf_text_edit._has_complex_script(self, *args, **kwargs)

    def _push_down_overlapping_text(self, *args, **kwargs):
        return pdf_text_edit._push_down_overlapping_text(self, *args, **kwargs)

    def _replay_protected_spans(self, *args, **kwargs):
        return pdf_text_edit._replay_protected_spans(self, *args, **kwargs)

    def _validate_protected_spans(self, *args, **kwargs):
        return pdf_text_edit._validate_protected_spans(self, *args, **kwargs)

    def _resolve_edit_target(self, *args, **kwargs):
        return pdf_text_edit._resolve_edit_target(self, *args, **kwargs)

    def _apply_redact_insert(self, *args, **kwargs):
        return pdf_text_edit._apply_redact_insert(self, *args, **kwargs)

    def _verify_rebuild_edit(self, *args, **kwargs):
        return pdf_text_edit._verify_rebuild_edit(self, *args, **kwargs)

    def _resolve_effective_target_mode(self, *args, **kwargs):
        return pdf_text_edit._resolve_effective_target_mode(self, *args, **kwargs)

    def edit_text(self, page_num: int, rect: fitz.Rect, new_text: str,
                  font: str = "helv", size: float = 12.0,
                  color: tuple = (0.0, 0.0, 0.0),
                  original_text: str | None = None,
                  vertical_shift_left: bool = True,
                  new_rect: fitz.Rect = None,
                  target_span_id: str | None = None,
                  target_mode: str | None = None,
                  style_overrides=None,
                  plan_token: str | None = None,
                  confirm_fallback: Callable[[tuple[str, ...]], bool | RebuildConsent] | None = None,
                  source_ref: SourceShowRef | None = None,
                  requires_preview_token: bool = False,
                  allow_rebuild: bool = False,
                  place_anyway: bool = False,
                  moving_off_page: bool = False,
                  ) -> EditTextResult:
        # V2 hard-reject boundary: signed documents and widget-bearing pages
        # must never be silently degraded to the legacy redact+reinsert
        # engine, in strict *or* non-strict mode -- checked here, before the
        # tiered branch's non-strict fallthrough (pdf_text_edit.py) ever
        # gets a chance to run it, so zero mutation happens either way.
        if self.text_commit_settings.engine == "tiered" and self.doc is not None:
            page_idx = page_num - 1
            if 0 <= page_idx < self.doc.page_count:
                try:
                    hard_reject = page_has_widgets_or_signatures(self.doc, self.doc[page_idx])
                except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase) as exc:
                    # Fail CLOSED, matching the comment above and
                    # page_has_widgets_or_signatures' own contract: a probe
                    # that cannot answer must not be read as "no widgets"
                    # and license the legacy redact+reinsert mutation on a
                    # page that may well carry a form or a signature.
                    # FzErrorBase derives from Exception, not RuntimeError,
                    # so it has to be named or a malformed AcroForm unwinds
                    # out of edit_text entirely.
                    logger.warning(
                        "edit_text: widget/signature probe failed page=%s %s; "
                        "refusing fail-closed",
                        page_num,
                        type(exc).__name__,
                    )
                    hard_reject = True
                if hard_reject:
                    self.last_commit_outcome = CommitOutcome(
                        status=CommitStatus.REJECTED,
                        tier=None,
                        fallback_chain=(f"tier0:{RejectReason.SIGNED_OR_WIDGET_TARGET}",),
                        warnings=(),
                        font_outcomes=(),
                        verified_properties=(),
                        degraded_reason=RejectReason.SIGNED_OR_WIDGET_TARGET,
                        allows_external_reflow=False,
                    )
                    logger.info(
                        "text_commit_hard_reject page=%s reason=%s",
                        page_num,
                        RejectReason.SIGNED_OR_WIDGET_TARGET,
                    )
                    return EditTextResult.REJECTED_UNSUPPORTED
        return pdf_text_edit.edit_text(
            self, page_num, rect, new_text,
            font=font, size=size, color=color,
            original_text=original_text,
            vertical_shift_left=vertical_shift_left,
            new_rect=new_rect,
            target_span_id=target_span_id,
            target_mode=target_mode,
            style_overrides=style_overrides,
            plan_token=plan_token,
            confirm_fallback=confirm_fallback,
            source_ref=source_ref,
            requires_preview_token=requires_preview_token,
            allow_rebuild=allow_rebuild,
            place_anyway=place_anyway,
            moving_off_page=moving_off_page,
        )

    def _reauthenticate_if_needed(self, doc: fitz.Document) -> fitz.Document:
        """Re-authenticate a freshly (re)opened encrypted handle in place.

        Any time an encrypted doc is round-tripped (``tobytes``/save+reopen) the
        new handle comes back locked (``needs_pass``); until it is re-authenticated
        with the password captured at open, the live session can't render, extract
        text, or edit. No-op for unencrypted docs (``needs_pass`` is 0), so it is
        safe to call on every reopen/round-trip path.
        """
        if doc.needs_pass:
            pw = self.password
            if pw is None:
                logger.warning("重新開啟文件仍加密但未保存密碼，無法自動解鎖")
            elif doc.authenticate(pw) == 0:
                logger.warning("文件密碼重新驗證失敗，維持鎖定")
        return doc

    def _reopen_doc_after_save(self, path: str) -> fitz.Document:
        """Reopen a just-saved file, re-authenticating if it kept encryption.

        Saving with ``encryption=KEEP`` produces an encrypted file, so the
        reopened handle is locked until re-authenticated. Without this, the live
        editing session would go dead (no render / text extraction / edits) after
        an encrypted save-back — the save paths close the in-memory authenticated
        doc to release the Windows file lock, then reopen from disk.
        """
        return self._reauthenticate_if_needed(fitz.open(path))

    @staticmethod
    def _handle_is_spent_for_incremental(doc: fitz.Document | None) -> bool:
        """True when ``doc`` already appended a revision and was never reopened (EXT-1)."""
        return doc is not None and bool(getattr(doc, _INCREMENTAL_SPENT_ATTR, False))

    def _renew_handle_after_incremental_save(self, target: str) -> None:
        """Swap the live handle for a fresh one after an incremental save (EXT-1).

        MuPDF keeps the end-of-file offset it read at open: a SECOND incremental
        save from the same handle appends at the ORIGINAL end of file again,
        overwriting the revision the first save wrote, and the new trailer's
        ``/Prev`` points into the overwritten bytes (a self-loop when both
        revisions have the same length, after which MuPDF itself opens the file
        with 0 pages).  Only a handle opened on the saved file knows where the
        file now ends -- which is what every full-save path already does through
        ``_reopen_doc_after_save``.  The file equals the live document at this
        point (numbering unchanged), so the epoch survives like on a full save.

        Never raises: when the fresh handle cannot be had (or does not read the
        same document) the old handle stays live but is marked spent, and the
        next save takes the full-save path instead of appending from it again.
        """
        old = self.doc
        if old is None:
            return
        epoch = self.xref_epoch
        fresh: fitz.Document | None = None
        try:
            fresh = self._reopen_doc_after_save(target)
            if int(fresh.page_count) != int(old.page_count):
                raise RuntimeError("reopened document has a different page count")
        except Exception:
            logger.warning("增量儲存後無法重新開啟文件，下次儲存將改為完整儲存: %s", target, exc_info=True)
            if fresh is not None:
                try:
                    fresh.close()
                except Exception:
                    pass
            try:
                setattr(old, _INCREMENTAL_SPENT_ATTR, True)
            except Exception:
                logger.debug("cannot mark the handle as spent", exc_info=True)
            self._note_persisted_baseline()
            return
        self.doc = fresh
        self._set_xref_epoch(epoch)
        self._note_persisted_baseline()
        try:
            old.close()
        except Exception:
            pass

    @staticmethod
    def _backing_file(doc: fitz.Document | None) -> Path | None:
        """The on-disk file ``doc`` reads lazily, or ``None`` for an in-memory doc.

        ``fitz.open("pdf", data)`` reports ``name == "pdf"`` (the filetype), so a
        non-empty name alone does not mean a file backs the handle.
        """
        if doc is None:
            return None
        try:
            name = doc.name
            if not name:
                return None
            candidate = Path(name)
            return candidate.resolve() if candidate.is_file() else None
        except Exception:
            return None

    def _model_temp_file_of(self, doc: fitz.Document | None) -> Path | None:
        """The file backing ``doc`` when it lives inside this model's temp dir."""
        temp_dir = getattr(self, "temp_dir", None)
        backing = self._backing_file(doc)
        if backing is None or temp_dir is None:
            return None
        try:
            # ``resolve()`` keeps the extended-length prefix of a private copy
            # whose path passes MAX_PATH but not of the (shorter) temp dir.
            root = Path(strip_extended_prefix(Path(temp_dir.name).resolve()))
            return backing if Path(strip_extended_prefix(backing)).is_relative_to(root) else None
        except Exception:
            return None

    def private_temp_file(self, stem: str) -> Path:
        """A fresh ``<stem>_<uuid>.pdf`` path in the model's private temp dir.

        The one place a user-initiated save / optimize stages a ``save_`` /
        ``recover_`` / ``live_`` / ``optimized_`` copy.  The temp dir is only a
        convenience for these, so it must never be a precondition of the user's
        own folder being writable (F13-ENV-1): (a) a temp cleaner (Disk
        Cleanup, Storage Sense) may have removed the idle folder mid-session -
        it is recreated here (``TemporaryDirectory.cleanup`` still removes it);
        (b) a deep ``TEMP`` makes the ``recover_<32hex>.pdf`` name pass the
        259-character legacy limit (``LongPathsEnabled=0``) - the path is
        returned in extended-length form (``utils.path_staging``), which
        ``open``, ``shutil``, ``os`` and MuPDF all accept.
        ``_model_temp_file_of`` compares prefix-insensitively.
        """
        temp_dir = getattr(self, "temp_dir", None)
        if temp_dir is None:
            raise RuntimeError("model temp dir is closed")
        root = Path(temp_dir.name)
        try:
            os.makedirs(extended_length_path(root), exist_ok=True)
        except OSError as exc:
            # Unusable (e.g. a removed drive): let the caller's own write report it.
            logger.warning("model temp dir %s is unavailable: %s", root, exc)
        return Path(extended_length_path(root / f"{stem}_{uuid.uuid4().hex}.pdf"))

    @staticmethod
    def _remove_detached_copy(path: Path) -> None:
        """Best-effort delete of a private live copy.

        A page object still in a reference cycle keeps the MuPDF file handle
        open on Windows until the cycle is collected, so retry once after a
        collection; whatever is left is removed with the temp dir.
        """
        for attempt in (0, 1):
            try:
                path.unlink(missing_ok=True)
                return
            except OSError as exc:
                if attempt == 0:
                    gc.collect()
                else:
                    logger.debug("無法刪除分離的暫存副本 %s: %s", path, exc)

    def _retire_replaced_handle(
        self, old: fitz.Document | None, new: fitz.Document | None
    ) -> None:
        """Queue the temp-dir file ``old`` reads for deletion when ``new`` replaces it.

        ``save_as`` rebinds the live handle to a private ``live_*.pdf`` copy (and
        a failed install rebinds it to a ``recover_*.pdf``).  Any later
        whole-document reinstall (snapshot undo/redo, a rollback, the in-memory
        round trip) swaps in an in-memory doc, after which ``close_session``
        can no longer find the copy through ``session.doc.name``.  The ``doc``
        setter is the one place every handle replacement passes through, so the
        file is retired here; the actual delete waits until the old handle is
        closed (Windows refuses to unlink an open file), which every reinstall
        path does right after - see ``_sweep_retired_live_copies``.
        """
        old_copy = self._model_temp_file_of(old)
        if old_copy is None or old_copy == self._model_temp_file_of(new):
            return  # not a private copy, or the new handle still reads it
        retired = getattr(self, "_retired_live_copies", None)
        if retired is None:
            retired = self._retired_live_copies = []
        if old_copy not in retired:
            retired.append(old_copy)
        self._sweep_retired_live_copies()

    def _sweep_retired_live_copies(self, *, collect: bool = False) -> None:
        """Delete every retired private copy whose handle is gone (never raises).

        A copy still held open (the replaced handle is closed only after the
        setter ran) stays queued for the next sweep; ``collect`` runs one
        garbage collection first for a page object that keeps the handle alive.
        """
        retired = getattr(self, "_retired_live_copies", None)
        if not retired:
            return
        remaining = list(retired)
        for attempt in (0, 1):
            if attempt:
                gc.collect()
            still: list[Path] = []
            for path in remaining:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    if attempt:
                        logger.debug("無法刪除分離的暫存副本 %s: %s", path, exc)
                    still.append(path)
            remaining = still
            if not remaining or not collect:
                break
        retired[:] = remaining

    def _session_reading_path(
        self, path: str | Path, *, exclude_session_id: str | None = None
    ) -> str | None:
        """Id of a live session that owns or still lazily reads ``path`` (or ``None``).

        MuPDF reads stream bytes from the backing file at stored offsets on
        demand, so rewriting a file in place corrupts every handle that still
        reads it.  The path map says who *owns* a path; the live handle's
        ``doc.name`` says who still *reads* it - this checks both.
        """
        canonical = self._canonicalize_path(str(path))
        for sid, session in self._sessions_by_id.items():
            if sid == exclude_session_id or session.save_lost_error is not None:
                # A lost session owns and reads nothing (its handle is closed).
                continue
            if session.canonical_path == canonical:
                return sid
            backing = self._backing_file(session.doc)
            if backing is not None and self._canonicalize_path(str(backing)) == canonical:
                return sid
        return None

    def _active_doc_reads_path(self, path: str | Path) -> bool:
        """True when the active (possibly legacy, session-less) doc reads ``path``."""
        backing = self._backing_file(self.doc)
        return backing is not None and self._canonicalize_path(str(backing)) == self._canonicalize_path(
            str(path)
        )

    def _detach_live_doc_from_source_file(self, new_path: str) -> None:
        """Stop the active session's live handle reading the file it just left.

        ``save_as`` to another path writes the copy but keeps the live handle
        on the old file (kept un-pruned on purpose: undo/redo slots).  Once the
        session is remapped to ``new_path`` that file is free for another tab
        to open and rewrite in place - and this handle's not-yet-read streams
        would then be read at stale offsets (blank pages, a corrupt next save).
        Rebind the handle to a private copy of the *live* document (``garbage=0``:
        same numbering, same objects, so the xref epoch and every retained page
        snapshot stay valid) in the model temp dir.
        """
        doc = self.doc
        backing = self._backing_file(doc)
        if doc is None or backing is None:
            return  # in-memory: nothing is read lazily from disk
        name = str(backing)
        if backing == Path(new_path).resolve() or self._model_temp_file_of(doc) is not None:
            return  # already on the saved file, or already on a private copy
        # A secure session never writes an unsanitised serialization: the copy
        # takes the same garbage=4 rewrite (which renumbers the live doc in
        # place and bumps the epoch); otherwise garbage=0 keeps the numbering.
        garbage = 4 if self.secure_save_required else 0
        private = self.private_temp_file("live")
        try:
            self._save_doc(doc, str(private), garbage=garbage)
            self._note_live_doc_serialized(doc, garbage)
            epoch = self.xref_epoch
            fresh = self._reopen_doc_after_save(str(private))
        except Exception:
            logger.warning("無法將文件與來源檔脫鉤，維持原本的開啟檔: %s", name, exc_info=True)
            try:
                private.unlink(missing_ok=True)
            except OSError:
                pass
            return
        self.doc = fresh
        self._set_xref_epoch(epoch)
        self._note_persisted_baseline()
        try:
            doc.close()
        except Exception:
            pass

    @staticmethod
    def _discard_staged_file(path: Path) -> None:
        """Best-effort removal of a staging file (never raises)."""
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("無法刪除暫存檔 %s: %s", path, exc)

    def _install_stage_over_open_file(
        self,
        stage: Path,
        target: str,
        *,
        recovery: Path,
        keep_live_content: bool = False,
    ) -> None:
        """Replace the file the live handle reads with ``stage``; never lose the session.

        Windows refuses to overwrite a file MuPDF holds open, so the handle has
        to be closed before the install.  Closing first and copying second (the
        old shape) left a dead session when the copy failed: edits gone, target
        possibly truncated, every later read ``document closed``.  Order now:

        1. copy ``stage`` to a sibling of the target - handle and target are
           untouched, so a failure here (permissions, disk full) costs nothing;
        2. close the handle and ``os.replace`` the sibling over the target
           (atomic: the target is never left truncated);
        3. if the replace fails, rebind the session to ``recovery`` (a file with
           the live doc's content and numbering) and re-raise the real error;
           the next save takes the normal write path to a file the handle does
           not read.  If the file cannot be opened by path, the session is
           opened from its bytes (in memory); if even that fails the session is
           gone, so ``recovery`` - the only copy of the edits - is KEPT and a
           ``SaveRecoveryError`` naming it replaces the plain error.

        ``stage`` and ``recovery`` are removed afterwards, except a ``recovery``
        the session was rebound to by path (it is the live backing file;
        ``close`` and ``close_session`` remove it) or one nothing could reopen.

        ``keep_live_content`` is for a ``stage`` that is NOT the live doc's
        content (a prepared clone: the watermark overlay baked into /Contents).
        The session must keep reading the LIVE content, so after a successful
        replace it is rebound to ``recovery`` (the live doc, same numbering, same
        epoch) instead of reopening the target.  Reopening the target would put
        the baked overlay under every retained xref-keyed undo patch (M9-2) and
        stack another overlay on the next save.
        """
        live = self.doc
        if live is None:
            raise RuntimeError("no open document to install over")
        epoch_before = self.xref_epoch
        target_path = resolve_as_requested(target)
        sibling = staging_sibling(target_path, "install")
        rebound = False
        keep_recovery = False
        try:
            shutil.copy2(str(stage), str(sibling))
            live.close()
            try:
                # collects once on a lock: PyMuPDF cycle garbage can still pin the file
                replace_file(sibling, target_path)
            except BaseException as replace_exc:
                rebound = self._rebind_to_recovery_copy(recovery, epoch_before)
                if not rebound:
                    keep_recovery = True
                    lost = SaveRecoveryError(
                        f"儲存失敗（{replace_exc}），且無法還原編輯中的文件。"
                        f"尚未儲存的編輯已保留於暫存副本，關閉程式前請先複製：{recovery}",
                        recovery_path=recovery,
                        target_written=False,
                    )
                    self._mark_session_lost(lost)
                    raise lost from replace_exc
                raise
            reopen_exc: Exception | None = None
            if not keep_live_content:
                try:
                    self.doc = self._reopen_doc_after_save(str(target_path))
                except Exception as exc:
                    # The target is written; keep the session alive on the recovery copy.
                    logger.warning("儲存後無法重新開啟 %s，改用暫存副本繼續編輯", target_path, exc_info=True)
                    reopen_exc = exc
            if keep_live_content or reopen_exc is not None:
                rebound = self._rebind_to_recovery_copy(recovery, epoch_before)
                if not rebound:
                    keep_recovery = True
                    reason = reopen_exc if reopen_exc is not None else "暫存副本無法開啟"
                    lost = SaveRecoveryError(
                        f"檔案已儲存至 {target_path}，但無法重新開啟（{reason}），"
                        f"目前文件已中斷。請重新開啟該檔案；備份副本：{recovery}",
                        recovery_path=recovery,
                        target_written=True,
                    )
                    self._mark_session_lost(lost)
                    raise lost from reopen_exc
        finally:
            self._discard_staged_file(sibling)
            # A recovery file the live handle reads stays (close/close_session
            # remove it); an in-memory rebind no longer needs the file.
            session_reads_recovery = rebound and self._backing_file(self.doc) == recovery.resolve()
            for leftover in {stage, recovery}:
                if leftover == recovery and (session_reads_recovery or keep_recovery):
                    continue
                self._discard_staged_file(leftover)

    def _rebind_to_recovery_copy(self, recovery: Path, epoch: int) -> bool:
        """Point the session at ``recovery`` after the live handle was closed.

        The copy is opened by path first; if that fails it is read into memory
        and opened from its bytes (an in-memory doc, like the one a snapshot
        restore leaves), so a locked or flaky path cannot kill the session.
        Returns ``False`` (logged) if even that fails: the caller then keeps the
        recovery file, the only copy of the unsaved edits.
        """
        try:
            self.doc = self._reopen_doc_after_save(str(recovery))
        except Exception:
            logger.warning("無法以路徑開啟暫存副本，改以記憶體開啟: %s", recovery, exc_info=True)
            try:
                self.doc = self._open_recovery_in_memory(recovery)
            except Exception:
                logger.error("無法以暫存副本還原編輯中的文件: %s", recovery, exc_info=True)
                return False
        self._set_xref_epoch(epoch)
        return True

    def _open_recovery_in_memory(self, recovery: Path) -> fitz.Document:
        """Open ``recovery`` from its bytes (no file handle), re-authenticating."""
        return self._reauthenticate_if_needed(fitz.open("pdf", recovery.read_bytes()))

    def _full_save_to_path(self, path: str):
        """
        完整儲存到指定路徑。若目標路徑與目前開啟的檔案相同（doc.name），
        先寫入暫存檔再覆蓋，避免 Windows 上「覆寫已開啟檔案」導致 Permission denied。
        其他目標（含快照復原後的記憶體文件）同樣先寫入同目錄暫存檔再取代，
        寫入失敗時不會截斷既有檔案（LS-2）。
        """
        # typed bind; callers guarantee an open doc here (save path) - runtime behavior identical if None; self.doc not reassigned until the reopen below
        doc: fitz.Document = self.doc
        path_resolved = Path(path).resolve()
        doc_name_resolved = Path(doc.name).resolve() if doc.name else None
        saving_over_open_file = doc_name_resolved is not None and path_resolved == doc_name_resolved

        if self.secure_save_required:
            self._atomic_full_save(
                doc,
                path,
                garbage=4,
                replace_live_handle=saving_over_open_file,
            )
            return

        if saving_over_open_file:
            # 先寫入暫存檔，關閉 doc 後再覆蓋原檔，最後重新開啟
            temp_save = self.private_temp_file("save")
            # garbage=1: free the unreachable objects (undo leaves a command's
            # objects in the live doc) without renumbering or touching it.
            try:
                self._save_doc(doc, str(temp_save), garbage=1)
            except BaseException:
                self._discard_staged_file(temp_save)
                raise
            # The pruned serialization doubles as the recovery copy: same
            # objects and numbering as the live doc, so it can stand in for the
            # handle if the install fails after the handle was closed.
            epoch_before = self.xref_epoch
            self._install_stage_over_open_file(temp_save, path, recovery=temp_save)
            # garbage 0/1 keep the numbering (``_roundtrip_live_doc`` rule): the
            # epoch stays valid, so retained page snapshots still restore.
            self._set_xref_epoch(epoch_before)
            self._note_persisted_baseline()
            logger.debug(f"已透過暫存檔覆寫原檔: {path}")
        else:
            # The target is not the file the live handle reads (another path, or the
            # live doc is in memory after a snapshot undo): still stage + replace so a
            # failed write never truncates an existing file (LS-2).
            self._save_doc_to_user_path(self.doc, path, garbage=1)

    def _render_page_gray_array(self, page_num: int, max_dim: int = 1000):
        """Render a page to a downscaled grayscale numpy array for skew analysis."""
        import numpy as np

        # typed bind; callers guarantee an open doc here (deskew path) - runtime behavior identical if None
        doc: fitz.Document = self.doc
        page = doc[page_num - 1]
        rect = fitz.Rect(page.rect)
        longest = max(1.0, float(rect.width), float(rect.height))
        scale = max(0.1, min(float(max_dim) / longest, 4.0))
        scale = _safe_render_scale(page, scale)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    def detect_page_skew(self, page_num: int, max_angle: float = 10.0, step: float = 0.5) -> float:
        """Detect a page's skew via projection-profile variance.

        Returns the corrective angle (degrees, CCW-positive) that, applied to the
        page, best aligns text rows horizontally. The bars/text rows of a level
        page produce a row-sum projection with sharp peaks (high variance); the
        candidate angle maximizing that variance is the deskew angle.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        import numpy as np
        from PIL import Image

        arr = self._render_page_gray_array(page_num)
        ink = ((arr < 128).astype(np.uint8) * 255)
        img = Image.fromarray(ink, mode="L")
        best_angle = 0.0
        best_score = -1.0
        steps = int(round((2.0 * max_angle) / max(1e-6, step))) + 1
        for i in range(steps):
            angle = -max_angle + i * step
            rotated = img.rotate(angle, resample=Image.Resampling.NEAREST, expand=False, fillcolor=0)
            row_sums = np.asarray(rotated, dtype=np.float64).sum(axis=1)
            score = float(np.var(row_sums))
            if score > best_score:
                best_score = score
                best_angle = angle
        return float(best_angle)

    def straighten_page(self, page_num: int, angle_degrees: float | None = None) -> bool:
        """Rotate a page to level it (deskew). Rasterizes the page.

        When ``angle_degrees`` is None the skew is auto-detected. The corrected
        page keeps the original size; rotated-out corners are filled white.
        """
        if not self.doc or page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"無效頁碼: {page_num}")
        if angle_degrees is None:
            angle_degrees = self.detect_page_skew(page_num)
        angle = float(angle_degrees)
        idx = page_num - 1
        rect = fitz.Rect(self.doc[idx].rect)
        if abs(angle) < 0.05:
            return True  # already level; nothing to correct

        import io

        from PIL import Image

        scale = _safe_render_scale(self.doc[idx], 2.0)
        pix = self.doc[idx].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")
        # Release the MuPDF pixmap's C buffer eagerly; PIL.frombytes already copied
        # the pixel data, so holding pix through the rotation+save is dead weight.
        del pix
        straightened = img.rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255)
        )
        buf = io.BytesIO()
        straightened.save(buf, format="PNG")
        png = buf.getvalue()

        # Replace the page: insert a same-size blank page at idx (old shifts to
        # idx+1), paint the straightened raster, then drop the old page.
        new_page = self.doc.new_page(pno=idx, width=float(rect.width), height=float(rect.height))
        new_page.insert_image(fitz.Rect(0.0, 0.0, float(rect.width), float(rect.height)), stream=png)
        # Bookmarks into the old page move to its replacement before the delete
        # would strip them (F16-NAV-1).
        outline_ops.move_targets_to_page(self.doc, idx + 1, idx)
        # Names, links and /OpenAction into the old page follow it too, keeping
        # their view; PyMuPDF would drop the explicit links and the names would
        # dangle (F16-NAV-1a).
        page_refs.repoint_page_references(self.doc, {self.doc.page_xref(idx + 1): self.doc.page_xref(idx)})
        self.doc.delete_page(idx + 1)
        try:
            self.block_manager.rebuild_page(idx, self.doc)
        except Exception:
            logger.debug("block index rebuild after straighten skipped")
        self.mark_page_content_dirty(idx, fitz.Rect(rect))
        self.edit_count += 1
        return True

    def _session_orphans_block_incremental(self) -> bool:
        """True when an incremental save would append a large pile of garbage.

        Objects at xref >= the persisted watermark were created in this session;
        the unreachable ones (an undone command's objects, a rebuild's leftovers)
        would be written into a new revision and stay in the file for good.  Only
        a payload of at least ``ORPHAN_FALLBACK_MIN_BYTES`` raw stream bytes
        forces the pruned full save: smaller orphans (e.g. the content stream
        ``clean_contents`` replaces at save time) keep the append-only save.
        An unknown watermark takes the safe direction (full save).  Orphans an
        earlier incremental save already wrote sit below the watermark and are
        only ever pruned by a later full save.

        A digitally signed document never takes the fallback: a full rewrite
        moves bytes inside the signature's ``/ByteRange`` and silently
        invalidates it, while the append-only revision keeps the signed bytes as
        an exact prefix.  Validity beats file size, so the orphans ride along.
        The probe is fail-closed (unreadable form tree == signed).
        """
        doc = self.doc
        base = self.persisted_xref_length
        if doc is None:
            return True
        if document_has_a_signed_signature(doc):
            return False
        if base is None:
            return True
        if int(doc.xref_length()) <= base:
            return False  # nothing was created since the last persist: no scan
        try:
            orphan_bytes = save_compaction.session_orphan_stream_bytes(doc, base)
        except Exception:
            logger.warning("session orphan scan failed; taking the full save", exc_info=True)
            return True
        return orphan_bytes >= save_compaction.ORPHAN_FALLBACK_MIN_BYTES

    def _save_signed_by_appending(
        self, new_path: str, new_path_resolved: Path, doc_name_resolved: Path | None
    ) -> str | None:
        """Keep a digitally signed source a byte prefix when the live handle cannot append.

        PyMuPDF appends (``incremental=True``) only from a handle opened on the
        file itself; a SnapshotCommand undo/redo, a rollback or an in-memory
        repair installs an in-memory handle, and a "Save As" targets another
        path.  Both used to fall to the full rewrite, which moves bytes inside
        the signature's ``/ByteRange`` and silently invalidates it (R7-1).
        ``signed_append_save`` appends the live state to a copy of the signed
        source instead.

        Returns ``None`` when ``new_path`` has been written that way.  Otherwise
        nothing was written and the result says why: ``SIGNED_APPEND_UNSIGNED``
        for a document without a signed signature (the caller's full rewrite
        loses nothing), else the ``SignatureWouldBreakError`` reason code
        (SIG-DIALOG): ``secure_latch`` (the latches exist to drop old bytes),
        ``incremental_disabled``, ``in_place_append_unavailable`` (the live
        handle holds the target itself but cannot append: a repaired file or a
        spent handle), ``source_missing``, ``source_changed``, or the replay's
        own code (``signed_append_save.DECLINE_REASONS``).
        """
        doc = self.doc
        if doc is None or not document_has_a_signed_signature(doc):
            return SIGNED_APPEND_UNSIGNED
        source = self.original_path
        if self.secure_save_required:
            return "secure_latch"
        if not self.use_incremental_save:
            return "incremental_disabled"
        if doc_name_resolved is not None and doc_name_resolved == new_path_resolved:
            return "in_place_append_unavailable"
        if not source or not Path(source).is_file():
            return "source_missing"
        base_bytes = self._signed_append_base_bytes(source)
        if base_bytes is None:
            logger.warning(
                "signed document: the source file is no longer the bytes this session opened "
                "(or is unreadable), so it cannot be the signed prefix of the new file: %s",
                new_path,
            )
            return "source_changed"
        stage = staging_sibling(new_path_resolved, "tmp")
        try:
            reason: str | None
            try:
                reason = signed_append_save.try_append_state_onto_source(
                    doc, source, stage, source_bytes=base_bytes
                )
            except Exception:
                logger.warning("簽署文件附加儲存失敗", exc_info=True)
                reason = "append_error"
            if reason is not None:
                # The document is signed here (guard above): the full rewrite that
                # would follow invalidates the signature, so this is not debug-only.
                logger.warning(
                    "signed document could not be saved by appending a revision (%s): %s",
                    reason,
                    new_path,
                )
                return reason
            replace_file(stage, resolve_as_requested(new_path))
            logger.debug(f"已以附加修訂方式儲存簽署文件: {new_path}")
            self._reserve_numbers_of_appended_file(new_path_resolved)
            return None
        finally:
            self._discard_staged_file(stage)

    def _roll_back_partial_append(self, target: str, before: tuple[int, int, str]) -> bool:
        """Cut a failed in-place append back to the file it was appended to (F12-SIG-1).

        ``before`` is ``_file_fingerprint(target)`` taken right before the
        append.  The bytes past its size are dropped only while the first
        ``size`` bytes still carry its edge digest, so nothing but the failed
        revision is ever cut.  True when the file is that size again (or never
        grew).  Never raises: a rollback that cannot be done leaves the torn
        tail and ``save_as`` re-records the fingerprint anyway, so the next
        save is not mistaken for a foreign writer's change.
        """
        size, _mtime_ns, digest = before
        try:
            with file_share_lock.suspended(target), open(target, "r+b") as handle:
                end = os.fstat(handle.fileno()).st_size
                if end == size:
                    return True
                if end < size:
                    logger.warning("增量儲存失敗後檔案變短，無法還原: %s", target)
                    return False
                if _edge_digest_of_prefix(handle, size) != digest:
                    logger.warning("增量儲存失敗後檔案開頭已不同，不截斷: %s", target)
                    return False
                handle.truncate(size)
            logger.warning("增量儲存失敗，已移除寫到一半的修訂（%d 位元組）: %s", end - size, target)
            return True
        except Exception:
            logger.warning("無法移除增量儲存寫到一半的修訂: %s", target, exc_info=True)
            return False

    def _signature_loss_gate(self, reason: str, new_path: str, allow_signature_loss: bool) -> None:
        """Raise ``SignatureWouldBreakError`` unless the caller has the user's consent (SIG-DIALOG).

        Called right before a full rewrite of a signed document, before anything
        is written -- except ``incremental_failed``, which follows a failed
        in-place append that may have written part of a revision: that tail is
        rolled back first (``_roll_back_partial_append``) and ``save_as``
        re-records the fingerprint (``_SIGNATURE_REFUSALS_AFTER_A_WRITE``).
        With consent the rewrite goes ahead and the log says so.
        """
        if not allow_signature_loss:
            raise SignatureWouldBreakError(reason, new_path)
        logger.warning(
            "full rewrite of a signed document with the user's consent; the signature "
            "will no longer verify (%s): %s",
            reason,
            new_path,
        )

    def _signed_append_base_bytes(self, source: str) -> bytes | None:
        """The bytes of ``source`` this session opened or last wrote, or ``None`` (F11-FS-1).

        The signed append makes ``source`` the byte prefix of a NEW file, so it
        must be what the user opened and signed, not whatever another program has
        done to the path since: ``_refuse_save_over_foreign_rewrite`` only guards
        the file being written, and a Save As (or a memory-backed Ctrl+S analogue
        to a new name) used to read the foreign file's current bytes and embed
        another program's revision in the new file's history.  The session's
        fingerprint of ``source`` is compared with the current bytes: unchanged
        (or only touched) gives the whole file, a foreign append gives the leading
        part the fingerprint still matches (the recorded size, edge digest
        included), anything else (a rewrite, a truncation, an unreadable file)
        gives ``None`` and the caller takes its own full save.  A session with no
        fingerprint of this path keeps the unchecked read.
        """
        try:
            data = Path(source).read_bytes()
        except OSError:
            return None
        session = self._active_session()
        if (
            session is None
            or session.disk_fingerprint is None
            or session.disk_fingerprint_path != self._canonicalize_path(source)
        ):
            return data
        size, _mtime_ns, digest = session.disk_fingerprint
        if len(data) < size:
            return None
        base = data[:size]
        return base if _edge_digest_of_bytes(base) == digest else None

    def _reserve_numbers_of_appended_file(self, path: Path) -> None:
        """Keep the live table clear of the numbers a signed append gave the file (R8-SIG-B).

        MuPDF writes the new revision's xref stream (and object streams) as NEW
        objects past the table it was given, so the file's ``xref_length()``
        ends up above the live document's.  The session's next edit would then
        allocate onto the file's container, and the next append would see a
        real object where the file keeps its cross-reference data and decline
        into a full rewrite that invalidates the signature.  The floor is kept
        on the session, not only on the handle: undo/redo and the other
        whole-document reinstalls bring back older, shorter tables.
        """
        try:
            written = fitz.open(str(path))
            try:
                length = int(written.xref_length())
            finally:
                written.close()
            self._raise_reserved_xref_length(length)
        except Exception:
            logger.warning("無法讀取附加後檔案的 xref 長度: %s", path, exc_info=True)

    def save_as(self, new_path: str, *, allow_signature_loss: bool = False):
        """另存 PDF。若存回原檔且支援增量更新，則使用 incremental=True。

        A digitally signed document whose save could only be a full rewrite
        (the signature would no longer verify) raises
        ``SignatureWouldBreakError`` before anything is written (a failed
        in-place append is rolled back first), unless ``allow_signature_loss``
        carries the user's consent (SIG-DIALOG).
        """
        # First: a lost session's ``self.doc`` is None and a closed handle
        # would raise ``document closed`` (S14-SAVEREC-DEAD-TAB).
        self._refuse_save_on_lost_session()
        if not self.doc:
            return
        canonical_new = self._canonicalize_path(new_path)
        active_sid = self.get_active_session_id()
        session = self._active_session()
        new_path = self._without_stale_stored_spelling(new_path, canonical_new, session)
        existing_sid = self._path_to_session_id.get(canonical_new)
        if existing_sid and active_sid and existing_sid != active_sid:
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        if self._session_reading_path(new_path, exclude_session_id=active_sid) is not None:
            raise RuntimeError("目標路徑已在其他分頁開啟，請改用不同檔名。")
        # Before anything is touched (pending redactions included): a refusal
        # leaves the session exactly as it was.
        self._refuse_save_over_damaged_session(canonical_new, new_path)
        if session is not None:
            self._refuse_save_over_foreign_rewrite(session, canonical_new, new_path)
        try:
            # The session's deny-write lock (OD-FS1-LOCK) stays on while the
            # document is serialized: only the in-place incremental append and
            # ``replace_file`` (every staged install) suspend it, for the write.
            self._save_as_unchecked(
                new_path, canonical_new, active_sid, allow_signature_loss=allow_signature_loss
            )
        except SignatureWouldBreakError as exc:
            # Every other refusal is raised before any write: the file is still
            # what the fingerprint says, and re-recording it would absorb a
            # change another program made meanwhile.  A failed in-place append
            # wrote to the session's own file before its refusal (F12-SIG-1):
            # that change is ours, or the consented retry and every later
            # Ctrl+S are refused as "changed by another program".
            if (
                exc.reason_code in _SIGNATURE_REFUSALS_AFTER_A_WRITE
                and session is not None
                and session.disk_fingerprint_path == canonical_new
            ):
                self._record_disk_fingerprint(session, new_path)
            raise
        except BaseException:
            # A failed save may still have written the session's own file (the
            # target was replaced, then the reopen failed): that change is ours,
            # not a foreign writer's, so the next Ctrl+S must not be refused.
            if session is not None and session.disk_fingerprint_path == canonical_new:
                self._record_disk_fingerprint(session, new_path)
            raise
        finally:
            # Lock whatever file the session owns now: the same path, or the
            # new one after a Save As; a degraded claim is retried.
            if session is not None:
                self._sync_session_file_locks(session)
        # The one chokepoint every successful save passes: the file now holds
        # exactly what this session wrote.
        if session is not None:
            self._record_disk_fingerprint(session, new_path)

    @staticmethod
    def _without_stale_stored_spelling(
        new_path: str, canonical_new: str, session: DocumentSession | None
    ) -> str:
        """``new_path`` with the file's on-disk spelling when it only replays the stored path (F11-FS-3).

        A typed Save As name is a request, so its case names the file
        (``resolve_as_requested``, F10-FS-3).  Ctrl+S is not a request: it
        replays ``saved_path or original_path``, whose spelling goes stale when
        another program renames the file by case while the session is
        memory-backed (a file-backed handle blocks the rename).  A name that is
        exactly the stored one, for the file the session already is, carries no
        new spelling, so the on-disk one is kept instead of renaming the file
        back.  Any other spelling of the same file, and the stored name typed
        for a different file, stay typed requests.
        """
        if session is None or session.canonical_path != canonical_new:
            return new_path
        stored_names = {Path(p).name for p in (session.saved_path, session.original_path) if p}
        if Path(new_path).name not in stored_names:
            return new_path
        return on_disk_spelling(new_path)

    def _sync_session_file_locks(self, session: DocumentSession) -> None:
        """Hold the deny-write share lock on exactly the user files ``session`` needs (OD-FS1-LOCK).

        Those are the file it owns (``saved_path or original_path``: what Ctrl+S
        writes) and, when the live handle still lazily reads a different user
        file (a Save As whose detach to a private copy failed), that file too.
        Private temp-dir copies are not locked.  A new claim is taken before an
        old one is dropped; a degraded claim is retried.  Never raises: a lock
        is protection, never a reason to fail a save or an open.
        """
        try:
            wanted: list[str] = []
            owned = session.saved_path or session.original_path
            if owned:
                wanted.append(str(owned))
            backing = self._backing_file(session.doc)
            if backing is not None and self._model_temp_file_of(session.doc) is None:
                wanted.append(str(backing))
            previous = list(session.file_locks)
            kept: list[file_share_lock.FileShareLock] = []
            for path in wanted:
                if any(token.covers(path) for token in kept):
                    continue
                token = next((t for t in previous if t.covers(path)), None)
                if token is None:
                    token = file_share_lock.acquire(path)
                else:
                    previous.remove(token)
                    token.ensure()
                kept.append(token)
            session.file_locks = kept
            for token in previous:
                token.release()
        except Exception:
            logger.warning("無法更新工作階段的檔案鎖定", exc_info=True)

    @staticmethod
    def _release_session_file_locks(session: DocumentSession) -> None:
        """Drop every deny-write claim ``session`` holds (never raises)."""
        tokens, session.file_locks = list(session.file_locks), []
        for token in tokens:
            try:
                token.release()
            except Exception:
                logger.warning("釋放檔案鎖定失敗: %s", token.path, exc_info=True)

    def _record_disk_fingerprint(self, session: DocumentSession, path: str | Path) -> None:
        """Remember ``path`` as the session's file, as it is on disk now (F10-FS-1)."""
        session.disk_fingerprint_path = self._canonicalize_path(str(path))
        session.disk_fingerprint = _file_fingerprint(path)

    def _refuse_save_over_damaged_session(self, canonical_new: str, new_path: str) -> None:
        """Raise ``DamagedSessionSaveError`` for an in-place save of a damaged session.

        A failed edit whose rollback also failed may have left a half-rewritten
        page in the live document (``mark_session_damaged``).  Saving it back
        onto the file the session was opened from (or last saved to) would
        replace the only good copy.  Every route to that write passes
        ``save_as`` (Ctrl+S, Save, Save All, save-on-close, a Save As dialog
        that picked the same file), so this is the one gate.  A different
        target is allowed: the user chose a new file.  Nothing is written.

        The protected set is ``damaged_protected_paths``: the files frozen at
        the latch PLUS the current one.  Deriving it from the current fields
        alone let a second Save As back onto the original through, because the
        first Save As rebinds every field to the new file (F14-DMG-1).
        """
        protected = self.damaged_protected_paths()
        if canonical_new not in protected:
            return
        logger.warning("儲存已取消：文件已標記為損壞，不得覆寫原檔: %s", new_path)
        raise DamagedSessionSaveError(DAMAGED_SESSION_SAVE_MESSAGE, path=Path(new_path))

    def _refuse_save_over_foreign_rewrite(
        self, session: DocumentSession, canonical_new: str, new_path: str
    ) -> None:
        """Raise ``SourceChangedOnDiskError`` when another program rewrote the session's file.

        MuPDF holds the open file with a share mode that lets any in-place
        writer (Explorer copy-overwrite, ``copy /y``, ``Copy-Item``, a plain
        ``open('wb')``) rewrite it under the live handle, and after a Save As
        nothing holds the new file at all.  Saving over such a file appended an
        incremental revision onto foreign bytes and reported success, or
        silently replaced the other program's content.  Only a save back to the
        session's own file is checked: any other target was chosen in a Save
        dialog that already confirmed the overwrite.  A file that is gone (or
        unreadable) is not a conflict: there is nothing left to protect.
        """
        baseline = session.disk_fingerprint
        if baseline is None or session.disk_fingerprint_path != canonical_new:
            return
        current = _file_fingerprint(new_path)
        if current is None or current == baseline:
            return
        name = Path(new_path).name
        message = (
            f"「{name}」在開啟或上次儲存後已被其他程式修改或取代，為避免覆蓋該檔案，"
            "本次儲存已取消（檔案未變更）。請改用「另存新檔」儲存到其他檔名。"
        )
        doc = session.doc
        backing = self._backing_file(doc)
        try:
            live_reads_foreign_bytes = (
                backing is not None
                and self._canonicalize_path(str(backing)) == canonical_new
                and self._doc_needs_xref_repair(doc)
            )
        except Exception:
            live_reads_foreign_bytes = False
        if live_reads_foreign_bytes:
            message += "注意：編輯中的文件已讀到該檔案的新內容，畫面可能已與您的編輯不同，另存前請先確認。"
        logger.warning("儲存已取消：%s 已被其他程式變更", new_path)
        raise SourceChangedOnDiskError(message, path=Path(new_path))

    def _save_as_unchecked(
        self,
        new_path: str,
        canonical_new: str,
        active_sid: str | None,
        *,
        allow_signature_loss: bool = False,
    ) -> None:
        """``save_as`` after its target / foreign-rewrite checks passed."""
        if self.doc is None:
            return
        # Phase 6: 儲存前批次清理已修改頁面的 content stream，壓縮 PDF 大小
        self.apply_pending_redactions()
        new_path_resolved = Path(new_path).resolve()
        original_resolved = Path(self.original_path).resolve() if self.original_path else None
        doc_name_resolved = Path(self.doc.name).resolve() if self.doc.name else None
        # 是否為「存回原檔」：新路徑與開啟時路徑相同，且目前 doc 仍是從原檔開啟（未經 undo 載入 temp）
        is_save_back_to_original = (
            original_resolved is not None
            and doc_name_resolved is not None
            and new_path_resolved == original_resolved
            and doc_name_resolved == original_resolved
            # A request that only changes the name's case (``a.pdf`` -> ``A.pdf``)
            # is a rename: appending to the open file cannot do it, the staged
            # install over the typed spelling can (F10-FS-3).
            and resolve_as_requested(new_path).name == new_path_resolved.name
        )
        can_incr = getattr(self.doc, "can_save_incrementally", None)
        use_incremental = (
            self.use_incremental_save
            and not self.secure_save_required
            and is_save_back_to_original
            and can_incr
            and self.doc.can_save_incrementally()
            # A handle that already appended once must not append again (EXT-1).
            and not self._handle_is_spent_for_incremental(self.doc)
        )

        prepared_doc = self.tools.prepare_doc_for_save(active_sid) if active_sid else None
        doc_to_save = prepared_doc if prepared_doc is not None else self.doc
        try:
            if doc_to_save is self.doc and use_incremental:
                # 增量更新時使用與 doc.name 一致的路徑格式，避免 PyMuPDF 判定為非原檔
                if self._session_orphans_block_incremental():
                    # An incremental save would append the session's
                    # unreachable objects permanently: write the pruned full
                    # save instead.  Outside the retry below on purpose: a
                    # failed full save surfaces its own error instead of being
                    # re-run on a handle it may already have closed.
                    logger.debug("工作階段殘留未參照物件，改為完整儲存: %s", new_path)
                    self._full_save_to_path(new_path)
                else:
                    save_target = self.doc.name if self.doc.name else new_path
                    before_append = _file_fingerprint(save_target)
                    try:
                        # Appends in place: the session's own deny-write lock
                        # would refuse it (OD-FS1-LOCK).
                        with file_share_lock.suspended(save_target):
                            self._save_doc(self.doc, save_target, incremental=True)
                        # EXT-1: the handle that appended may not append again.
                        self._renew_handle_after_incremental_save(save_target)
                        logger.debug(f"已使用增量更新儲存: {new_path}")
                    except Exception as e:
                        logger.warning(f"增量更新儲存失敗，改為完整儲存: {e}")
                        # A disk-full / network drop mid-append leaves part of a
                        # revision on the file (F12-SIG-1): take it back before
                        # the signed refusal below, which promises an unchanged file.
                        if before_append is not None:
                            self._roll_back_partial_append(save_target, before_append)
                        if document_has_a_signed_signature(self.doc):
                            self._signature_loss_gate(
                                "incremental_failed", new_path, allow_signature_loss
                            )
                        self._full_save_to_path(new_path)
            elif doc_to_save is self.doc:
                declined = self._save_signed_by_appending(new_path, new_path_resolved, doc_name_resolved)
                if declined is not None:
                    if declined != SIGNED_APPEND_UNSIGNED:
                        self._signature_loss_gate(declined, new_path, allow_signature_loss)
                    self._full_save_to_path(new_path)
            else:
                # The prepared clone (a watermark baked in) is always a full
                # rewrite: a signed document asks first (SIG-DIALOG).
                if document_has_a_signed_signature(self.doc):
                    self._signature_loss_gate("watermark_rewrite", new_path, allow_signature_loss)
                # 若目標路徑為目前開啟的檔案，先寫暫存再覆蓋，避免 Windows Permission denied
                if self.secure_save_required:
                    self._atomic_full_save(
                        doc_to_save,
                        new_path,
                        garbage=4,
                        replace_live_handle=(
                            doc_name_resolved is not None and new_path_resolved == doc_name_resolved
                        ),
                    )
                elif doc_name_resolved is not None and new_path_resolved == doc_name_resolved:
                    temp_save = self.private_temp_file("save")
                    # What the session keeps if the install fails is the LIVE
                    # doc (the prepared clone carries the watermark overlay).
                    recovery = self.private_temp_file("recover")
                    try:
                        self._save_doc(doc_to_save, str(temp_save), garbage=1)
                        self._save_doc(self.doc, str(recovery), garbage=1)
                    except BaseException:
                        self._discard_staged_file(temp_save)
                        self._discard_staged_file(recovery)
                        raise
                    # ``doc_to_save`` is the prepared clone (watermark overlay baked
                    # in): the session keeps the unbaked LIVE doc (M9-2).
                    self._install_stage_over_open_file(
                        temp_save, new_path, recovery=recovery, keep_live_content=True
                    )
                    self._note_persisted_baseline()
                else:
                    self._save_doc_to_user_path(doc_to_save, new_path, garbage=1)
        finally:
            if prepared_doc is not None:
                prepared_doc.close()

        # The session leaves the file it was opened from: release the live
        # handle too, before another tab can claim and rewrite that path.
        self._detach_live_doc_from_source_file(new_path)
        self.saved_path = new_path
        if active_sid and active_sid in self._sessions_by_id:
            session = self._sessions_by_id[active_sid]
            self._path_to_session_id.pop(session.canonical_path, None)
            # Re-derived now the file exists: the pre-write key came from the typed
            # spelling, the stored name can differ (trailing dot/space, 8.3 form)
            # and every later lookup resolves the stored one (F10-FS-2).
            canonical_new = self._canonicalize_path(new_path)
            session.canonical_path = canonical_new
            session.original_path = str(Path(new_path).resolve())
            session.display_name = Path(session.original_path).name
            self._path_to_session_id[canonical_new] = active_sid
        self.command_manager.mark_saved()
        self.edit_count = 0
        if active_sid:
            self._sessions_by_id[active_sid].transferred_dirty = False
        if active_sid:
            self.tools.on_session_saved(active_sid)

    def has_unsaved_changes(self) -> bool:
        """檢查是否有未儲存的變更（Phase 6：統一由 command_manager 管理）。"""
        sid = self.get_active_session_id()
        if not sid:
            return False
        return self.session_has_unsaved_changes(sid)

    # undo() / redo() 已於 Phase 6 移除，改由 Controller 呼叫 model.command_manager.undo/redo()。
