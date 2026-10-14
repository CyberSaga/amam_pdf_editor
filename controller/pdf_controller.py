from __future__ import annotations

import contextlib
import dataclasses
import difflib
import inspect
import logging
import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
)

from model.color_profile import ColorProfile, safe_to_fitz_colorspace
from model.edit_commands import AddTextboxCommand, EditTextCommand, EditTextResult, SnapshotCommand
from model.edit_requests import RebuildConsent, StyleOverrides, UnkeepableGlyph
from model.object_op_refusal import ObjectOpRefusal, ObjectOpRefused
from model.text_edit_refusal import TextEditRefusal, TextEditRefused
from model.object_requests import (
    BatchDeleteObjectsRequest,
    BatchMoveObjectsRequest,
    DeleteObjectRequest,
    InsertImageObjectRequest,
    MoveObjectRequest,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model import pdf_optimizer
from model.pdf_model import (
    DamagedSessionSaveError,
    PDFModel,
    PdfPasswordRejectedError,
    PdfPasswordRequiredError,
    SaveRecoveryError,
    SignatureWouldBreakError,
    SourceChangedOnDiskError,
)
from model.pdf_text_edit import _Tier0Target, derive_tier0_preview_target
from model.text_commit.dto import (
    CommitOutcome,
    CommitStatus,
    TextCommitSettings,
    is_real_fallback_commit,
)
from model.text_commit.preview import PlanPreviewResult, open_preview_session
from model.text_normalization import strip_unrenderable_controls
from model.tools.ocr_tool import is_device_available
from utils.file_reveal import reveal_in_file_manager
from utils.helpers import pixmap_to_qimage, pixmap_to_qpixmap
from utils.preferences import UserPreferences
from view.message_boxes import (
    confirm_degraded_fallback,
    confirm_place_anyway,
    confirm_signature_loss,
    show_error,
)
from view.text_edit_reasons import (
    FALLBACK_NO_REASON_TEXT,
    fallback_chain_reason_text,
    rejection_reason_text,
)
from view.pdf_view import EditTextRequest, MoveTextRequest, PDFView, ViewportAnchor
from src.printing.messages import (
    PRINT_CLOSING_MESSAGE as CLEAN_PRINT_CLOSING_MESSAGE,
)
from src.printing.messages import (
    PRINT_PREPARING_MESSAGE as CLEAN_PRINT_PREPARING_MESSAGE,
)
from src.printing.messages import (
    PRINT_STALLED_MESSAGE as CLEAN_PRINT_STALLED_MESSAGE,
)
from src.printing.messages import (
    PRINT_STATUS_MESSAGE as CLEAN_PRINT_STATUS_MESSAGE,
)
from src.printing.messages import (
    PRINT_SUBMITTING_MESSAGE as CLEAN_PRINT_SUBMITTING_MESSAGE,
)
from src.printing.messages import (
    PRINT_TERMINATE_BUTTON_TEXT as CLEAN_PRINT_TERMINATE_BUTTON_TEXT,
)
from src.printing.messages import (
    PRINT_TERMINATING_MESSAGE as CLEAN_PRINT_TERMINATING_MESSAGE,
)

INDEX_BATCH_SIZE = 5
INDEX_BATCH_INTERVAL_MS = 50
FIRST_PAGE_PREVIEW_SCALE = 0.25
VISIBLE_PREFETCH_PAGES = 1
# Longest a save waits for a cancelled thumbnail file worker to leave the page it is rendering.
SAVE_READER_JOIN_TIMEOUT_MS = 5000
VISIBLE_RENDER_BATCH_SIZE = 2
LOW_RES_RENDER_SCALE = 0.5
RENDER_CACHE_BUDGET_BYTES = 96 * 1024 * 1024
OPEN_BACKGROUND_FALLBACK_MS = 250
# How often a forwarded open / worker-completion tab activation that arrived
# during a modal re-checks whether the modal is gone (F11-1).
DEFERRED_SESSION_ACTIVATION_RETRY_MS = 150

logger = logging.getLogger(__name__)

PRINT_STATUS_MESSAGE = "列印中..."
PRINT_PREPARING_MESSAGE = "正在準備列印工作，請稍候..."
PRINT_SUBMITTING_MESSAGE = "正在送出列印工作，請稍候..."
PRINT_CLOSING_MESSAGE = "正在完成最後工作，請稍候..."
PRINT_STALLED_MESSAGE = "列印子系統沒有回應，您可以終止背景列印工作。"
PRINT_TERMINATING_MESSAGE = "正在終止背景列印工作，請稍候..."
PRINT_TERMINATE_BUTTON_TEXT = "終止列印工作"


PRINT_STATUS_MESSAGE = CLEAN_PRINT_STATUS_MESSAGE
PRINT_PREPARING_MESSAGE = CLEAN_PRINT_PREPARING_MESSAGE
PRINT_SUBMITTING_MESSAGE = CLEAN_PRINT_SUBMITTING_MESSAGE
PRINT_CLOSING_MESSAGE = CLEAN_PRINT_CLOSING_MESSAGE
PRINT_STALLED_MESSAGE = CLEAN_PRINT_STALLED_MESSAGE
PRINT_TERMINATING_MESSAGE = CLEAN_PRINT_TERMINATING_MESSAGE
PRINT_TERMINATE_BUTTON_TEXT = CLEAN_PRINT_TERMINATE_BUTTON_TEXT

@dataclass
class SessionUIState:
    current_page: int = 0
    scale: float = 1.0
    search_state: dict = field(default_factory=lambda: {"query": "", "results": [], "index": -1})
    mode: str = "browse"
    viewport_anchor: ViewportAnchor | None = None
    color_profile: str = ColorProfile.SRGB.value


@dataclass
class FullscreenSessionSnapshot:
    current_page: int
    scale: float
    anchor: ViewportAnchor


# R3.2: the print subsystem (worker, bridge, request, dispatcher, runner, orchestration
# + stall/terminate state) lives in controller/print_coordinator.py. The worker/bridge/
# request are re-exported here so existing `from controller.pdf_controller import ...` stays valid.
from controller.session_transfer import SessionTransferPayload  # noqa: E402
from controller.page_render_coordinator import (  # noqa: E402
    PageRenderCoordinator,
    PageRenderIdentity,
)
from controller.text_commit_coordinator import (  # noqa: E402
    PlanPreviewIdentity,
    TextCommitPreviewCoordinator,
)
from controller.object_op_refusals import (  # noqa: E402
    atomic_delete_refusal_message,
    batch_refusal_message,
    object_refusal_message,
)
from controller.text_edit_refusals import (  # noqa: E402
    UserFacingEditError,
    log_edit_failure,
    refusal_message,
    user_message_for_exception,
    user_message_for_history_failure,
)
from controller.print_coordinator import (  # noqa: E402
    PrintCoordinator,
    PrintJobRequest,  # noqa: F401  (re-export for backward compatibility)
    _PrintSubmissionWorker,  # noqa: F401  (re-export for backward compatibility)
    _PrintWorkerBridge,  # noqa: F401  (re-export for backward compatibility)
)
from controller.thumbnail_coordinator import (  # noqa: E402
    ThumbnailCoordinator,
    ThumbnailFileSource,
    ThumbnailRequest,
)


@dataclass(frozen=True)
class OptimizePdfCopyRequest:
    output_path: str
    options: object
    source: pdf_optimizer.OptimizeSourceSnapshot
    credentials: pdf_optimizer.OptimizeOutputCredentials | None = None


class _OptimizePdfCopyWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, model: PDFModel, request: OptimizePdfCopyRequest) -> None:
        super().__init__()
        self._model = model
        self._request = request

    def run(self) -> None:
        try:
            result = pdf_optimizer.save_optimized_copy_from_snapshot(
                self._model,
                self._request.source,
                self._request.output_path,
                self._request.options,
                credentials=self._request.credentials,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class _OptimizeWorkerBridge(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    thread_finished = Signal()

    @Slot(object)
    def forward_succeeded(self, result) -> None:
        self.succeeded.emit(result)

    @Slot(object)
    def forward_failed(self, exc) -> None:
        self.failed.emit(exc)

    @Slot()
    def notify_thread_finished(self) -> None:
        self.thread_finished.emit()


# R3.2: the async OCR subsystem (worker, bridge, orchestration + state) lives in
# controller/ocr_coordinator.py. _OcrWorker/_OcrBridge are re-exported here so
# `from controller.pdf_controller import _OcrWorker, _OcrBridge` stays valid.
from controller.ocr_coordinator import (  # noqa: E402
    OcrCoordinator,
    _OcrBridge,  # noqa: F401  (re-export for backward compatibility)
    _OcrWorker,  # noqa: F401  (re-export for backward compatibility)
)


# R3.2: the async search subsystem (worker, bridge, orchestration + state) lives in
# controller/search_coordinator.py. _SearchWorker/_SearchBridge are re-exported here so
# `from controller.pdf_controller import _SearchWorker, _SearchBridge` stays valid.
from controller.search_coordinator import (  # noqa: E402
    SearchCoordinator,
    _SearchBridge,  # noqa: F401  (re-export for backward compatibility)
    _SearchWorker,  # noqa: F401  (re-export for backward compatibility)
)


# UI step 7: the reason code of a cross-page move refused for want of the
# explicit rebuild consent (codes only -- P0-C privacy contract).
_CROSS_PAGE_MOVE_REASON = "cross_page_move_requires_rebuild"
# UI step 9: a request/preview made in another document session than the
# active one (never committed or previewed; code only).
_DOCUMENT_SESSION_MISMATCH_REASON = "document_session_mismatch"


def _move_consent_already_given(_chain: tuple[str, ...]) -> bool:
    """The source deletion of a consented cross-page move: the user already
    confirmed the whole move once (UI step 7)."""
    return True


def _normalize_run_text(text: str) -> str:
    """Whitespace- and case-insensitive form of a run's text, for comparing
    runs by content (span ids are positional, so they cannot identify text)."""
    return "".join((text or "").split()).casefold()


class PDFController:
    _VALID_MODES = {"browse", "edit_text", "add_text", "rect", "highlight", "markup_line", "add_annotation"}
    def __init__(self, model: PDFModel, view: PDFView):
        self.model = model
        self.view = view
        self._prefs = UserPreferences()
        self._session_handoff_callback = None
        self.annotations = []
        self._print_coordinator = PrintCoordinator(self)
        self._optimize_progress_dialog: QProgressDialog | None = None
        self._optimize_thread: QThread | None = None
        self._optimize_worker: _OptimizePdfCopyWorker | None = None
        self._optimize_worker_bridge: _OptimizeWorkerBridge | None = None
        self._optimize_paused_session_id: str | None = None
        self._optimize_close_pending = False
        # F11-1: tab activations from outside the user's flow (forwarded
        # opens, worker completions) queued until no modal is up.
        self._deferred_session_activations: list = []
        self._deferred_session_activation_draining = False
        self._deferred_session_activation_retry_armed = False
        self._ocr_coordinator = OcrCoordinator(self)
        self._search_coordinator = SearchCoordinator(self)
        self._thumbnail_coordinator = ThumbnailCoordinator(
            source_resolver=self._resolve_thumbnail_file_source,
            live_renderer=self._render_live_thumbnail,
            batch_consumer=self._consume_thumbnail_images,
            identity_matches=self._thumbnail_identity_matches,
            parent=self.view,
        )
        self._page_render_coordinator = PageRenderCoordinator(
            result_consumer=self._consume_page_render_image,
            failure_consumer=self._on_page_render_failed,
            identity_matches=self._page_render_identity_matches,
            parent=self.view,
        )
        # V2 plan-backed preview (lazy: only built when TEXT_COMMIT_PREVIEW=plan)
        self._text_commit_preview_coordinator: TextCommitPreviewCoordinator | None = None
        self._plan_preview_session_key: str | None = None
        self._plan_preview_target: _Tier0Target | None = None
        # Task 12 P0-C phase 1: whether the most recent edit_text call ended
        # in a DEGRADED_COMMITTED outcome. The View pulls-and-clears this via
        # consume_last_edit_degraded() so its mode-switch finalize path never
        # toasts plain success ("文字已儲存") over a degrade notice.
        self._last_edit_degraded = False
        # Task 12 P0-C phase 2 verification: the actual EditTextResult of
        # the most recent commit-producing operation (edit_text,
        # move_text_across_pages, add_textbox). The View pulls-and-clears
        # this via consume_last_edit_result() so its mode-switch finalize
        # path can tell a real commit apart from a signal that merely
        # emitted without raising (TextEditOutcome.COMMITTED is set on the
        # latter alone) -- otherwise REJECTED_STRICT, TARGET_BLOCK_NOT_FOUND
        # and FALLBACK_DECLINED can all be misreported as success.
        self._last_edit_result: EditTextResult | None = None
        # UI step 10: the reason code of the last REJECTED edit (pulled with
        # the result by the View's finalize path, which shows it in the kept
        # editor and offers the explicit rebuild).  Reset with the result.
        self._last_edit_refusal_reason: str | None = None
        self._thumbnail_resume_pending_by_session: set[str] = set()
        self._load_gen_by_session: dict[str, int] = {}
        self._thumb_gen_by_session: dict[str, int] = {}
        self._render_gen_by_session: dict[str, int] = {}
        self._stale_index_gen_by_session: dict[str, int] = {}
        self._session_ui_state: dict[str, SessionUIState] = {}
        self._desired_scroll_page: dict[str, int] = {}
        self._open_priority_page_by_session: dict[str, int] = {}
        self._background_loading_started_by_session: dict[str, bool] = {}
        self._render_batch_pending_by_session: dict[str, bool] = {}
        self._page_sizes_by_session: dict[str, list[tuple[float, float]]] = {}
        self._page_render_quality_by_session: dict[str, dict[str, dict[int, str]]] = {}
        self._render_revision_by_session: dict[str, int] = {}
        self._render_cache: OrderedDict[tuple[str, str, int, int, str, int], tuple[QPixmap, int]] = OrderedDict()
        self._render_cache_total_bytes = 0
        # R4.2: single-entry cache of the full-doc worker snapshot bytes, keyed by
        # (active_session_id, render_revision). See capture_worker_snapshot_bytes().
        self._worker_snapshot_cache: tuple[str, int, bytes] | None = None
        self._fullscreen_session_snapshots: dict[str, FullscreenSessionSnapshot] = {}
        self._global_mode = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
        self._signals_connected = False
        self._activated = False

    @property
    def is_active(self) -> bool:
        return self._activated

    def activate(self) -> None:
        if self._activated:
            return
        self._print_coordinator.connect_bridge()
        if self._optimize_worker_bridge is None:
            self._optimize_worker_bridge = _OptimizeWorkerBridge(self.view)
            self._optimize_worker_bridge.succeeded.connect(self._on_optimize_copy_succeeded)
            self._optimize_worker_bridge.failed.connect(self._on_optimize_copy_failed)
            self._optimize_worker_bridge.thread_finished.connect(self._on_optimize_thread_finished)
        self._ocr_coordinator.connect_bridge()
        self._search_coordinator.connect_bridge()
        if not self._signals_connected:
            self._connect_signals()
            self._signals_connected = True
        self._activated = True
        self._refresh_ocr_availability()
        self._refresh_recent_files()

    def _refresh_ocr_availability(self) -> None:
        updater = getattr(self.view, "update_ocr_availability", None)
        if not callable(updater):
            return
        tool = getattr(getattr(self.model, "tools", None), "ocr", None)
        if tool is None:
            updater(False, "OCR 工具未啟用")
            return
        try:
            info = tool.availability()
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.warning("OCR availability probe failed: %s", exc)
            updater(False, str(exc))
            return
        if info.available:
            updater(True, "")
        else:
            parts = [p for p in (info.reason, info.install_hint) if p]
            updater(False, "\n".join(parts) or "OCR 工具不可用")

    def _connect_signals(self):
        # Existing connections
        self.view.sig_open_pdf.connect(self._live_only(self.open_pdf))
        self.view.sig_tab_changed.connect(self._live_only(self.on_tab_changed))
        self.view.sig_tab_close_requested.connect(self._live_only(self.on_tab_close_requested))
        self.view.sig_detach_document_requested.connect(self._live_only(self.detach_document_session))
        if hasattr(self.view, "sig_reveal_document_requested"):
            self.view.sig_reveal_document_requested.connect(self._live_only(self.reveal_document_in_folder))
        self.view.sig_print_requested.connect(self._live_only(self.print_document))
        self.view.sig_request_metadata_editor.connect(self._live_only(self.request_metadata_editor))
        self.view.sig_update_metadata.connect(self._live_only(self.update_document_metadata))
        self.view.sig_save_as.connect(self._live_only(self.save_as))
        self.view.sig_save.connect(self._live_only(self.save))
        self.view.sig_delete_pages.connect(self._live_only(self.delete_pages))
        self.view.sig_rotate_pages.connect(self._live_only(self.rotate_pages))
        if hasattr(self.view, "sig_reorder_page"):
            self.view.sig_reorder_page.connect(self._live_only(self.reorder_page))
        if hasattr(self.view, "sig_straighten_pages"):
            self.view.sig_straighten_pages.connect(self._live_only(self.straighten_pages))
        self.view.sig_export_pages.connect(self._live_only(self.export_pages))
        self.view.sig_add_highlight.connect(self._live_only(self.add_highlight))
        self.view.sig_add_underline.connect(self._live_only(self.add_underline))
        self.view.sig_add_strikeout.connect(self._live_only(self.add_strikeout))
        self.view.sig_add_rect.connect(self._live_only(self.add_rect))
        self.view.sig_edit_text.connect(self._live_only(self.edit_text))
        if hasattr(self.view, "sig_text_edit_plan_preview"):
            self.view.sig_text_edit_plan_preview.connect(
                self._live_only(self.on_text_edit_plan_preview_request)
            )
        # UI step 5 (apply by token): only when plan preview is on can a
        # token ever arrive, so only then does the inline Apply wait for one.
        require_token = getattr(self.view, "set_text_plan_preview_required", None)
        if callable(require_token):
            require_token(self._text_commit_settings().preview == "plan")
        self.view.sig_move_text_across_pages.connect(self._live_only(self.move_text_across_pages))
        self.view.sig_add_textbox.connect(self._live_only(self.add_textbox))
        if hasattr(self.view, "sig_add_image_object"):
            self.view.sig_add_image_object.connect(self._live_only(self.add_image_object))
        self.view.sig_move_object.connect(self._live_only(self.move_object))
        self.view.sig_delete_object.connect(self._live_only(self.delete_object))
        self.view.sig_rotate_object.connect(self._live_only(self.rotate_object))
        if hasattr(self.view, "sig_resize_object"):
            self.view.sig_resize_object.connect(self._live_only(self.resize_object))
        self.view.sig_jump_to_result.connect(self._live_only(self.jump_to_result))
        self.view.sig_search.connect(self._live_only(self.search_text))
        if hasattr(self.view, "sig_start_ocr"):
            self.view.sig_start_ocr.connect(self._live_only(self.start_ocr))
        self.view.sig_undo.connect(self._live_only(self.undo))
        self.view.sig_redo.connect(self._live_only(self.redo))
        self.view.sig_mode_changed.connect(self._live_only(self._update_mode))
        self.view.sig_page_changed.connect(self._live_only(self.change_page))
        self.view.sig_scale_changed.connect(self._live_only(self.change_scale))
        self.view.sig_viewport_changed.connect(self._live_only(self._on_viewport_changed))
        self.view.sig_toggle_fullscreen.connect(self._live_only(self.toggle_fullscreen))
        self.view.sig_text_target_mode_changed.connect(self._live_only(self.set_text_target_mode))

        # New annotation connections
        self.view.sig_add_annotation.connect(self._live_only(self.add_annotation))
        self.view.sig_update_annotation.connect(self._live_only(self.update_annotation_content))
        self.view.sig_move_annotation.connect(self._live_only(self.move_annotation_marker))
        self.view.sig_delete_annotation.connect(self._live_only(self.delete_annotation))
        self.view.sig_load_annotations.connect(self._live_only(self.load_annotations))
        self.view.sig_jump_to_annotation.connect(self._live_only(self.jump_to_annotation))
        self.view.sig_toggle_annotations_visibility.connect(self._live_only(self.toggle_annotations_visibility))
        self.view.sig_bookmark_activated.connect(self._live_only(self.change_page))
        self.view.sig_toc_changed.connect(self._live_only(self.update_toc))

        # Snapshot connection
        self.view.sig_snapshot_page.connect(self._live_only(self.snapshot_page))

        # Insert pages connections
        self.view.sig_insert_blank_page.connect(self._live_only(self.insert_blank_page))
        self.view.sig_insert_pages_from_file.connect(self._live_only(self.insert_pages_from_file))
        self.view.sig_merge_pdfs_requested.connect(self._live_only(self.start_merge_pdfs))
        self.view.sig_optimize_pdf_copy_requested.connect(self._live_only(self.start_optimize_pdf_copy))

        # Watermark connections
        self.view.sig_add_watermark.connect(self._live_only(self.add_watermark))
        self.view.sig_update_watermark.connect(self._live_only(self.update_watermark))
        self.view.sig_remove_watermark.connect(self._live_only(self.remove_watermark))
        self.view.sig_load_watermarks.connect(self._live_only(self.load_watermarks))

        # Zoom re-render connection
        self.view.sig_request_rerender.connect(self._live_only(self._on_request_rerender))
        if hasattr(self.view, "sig_color_profile_changed"):
            self.view.sig_color_profile_changed.connect(self._live_only(self._on_color_profile_changed))

        # Align model granularity with UI default at startup.
        combo = getattr(self.view, "text_target_mode_combo", None)
        if combo is not None:
            mode = combo.currentData()
            if mode in ("run", "paragraph"):
                self.set_text_target_mode(mode)

    # Slots that must keep working on a lost session (S14-SAVEREC-DEAD-TAB): opening
    # and closing tabs, switching tabs, the two save entries (they report the loss
    # and copy the recovery file), revealing the file, leaving fullscreen and the
    # two settings that never touch a document.  Everything else is dropped.
    _LOST_SESSION_SLOTS = frozenset(
        {
            "open_pdf",
            "on_tab_changed",
            "on_tab_close_requested",
            "detach_document_session",
            "reveal_document_in_folder",
            "save",
            "save_as",
            "toggle_fullscreen",
            "_update_mode",
            "set_text_target_mode",
        }
    )

    def _is_lost(self, session_id: str | None = None) -> bool:
        """True when ``session_id`` (default: the active session) was lost after a failed save.

        The ONE read of the model's lost-session API, in front of every guarded
        slot, save, close, detach and render.  A model that does not provide it
        (a controller-test double that predates it) is a live model, so the guard
        never raises; the real ``PDFModel`` always provides it, and
        ``test_pdf_model_exposes_every_lost_session_name_the_controller_reads_guard``
        fails if a rename would silently switch the guard off.  The answer is
        compared with ``is True`` so a double that answers every call with a
        truthy object does not read as a lost tab.
        """
        model = self.model
        if session_id:
            probe = getattr(model, "is_session_lost", None)
            lost = probe(session_id) if callable(probe) else False
        else:
            lost = getattr(model, "session_lost", False)
        return lost is True

    def _live_only(self, slot: Callable[..., object]) -> Callable[..., object]:
        """Wrap a view-signal slot so it does nothing while the active session is lost.

        The ONE guard for the signal slots (S14-SAVEREC-DEAD-TAB, owner decision
        C): a lost session has no document, so a slot that reads or edits one
        would raise.  The slots in ``_LOST_SESSION_SLOTS`` pass through.  The
        wrapper hands the slot only as many arguments as it accepts, as Qt does
        for a bound method.
        """
        name = getattr(slot, "__name__", "")
        if name in self._LOST_SESSION_SLOTS:
            return slot
        accepted: int | None
        try:
            params = list(inspect.signature(slot).parameters.values())
            if any(p.kind is p.VAR_POSITIONAL for p in params):
                accepted = None
            else:
                accepted = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        except (TypeError, ValueError):
            accepted = None

        def guarded(*args: object) -> object:
            if self._is_lost():
                logger.debug("%s ignored: the active session is lost", name)
                return None
            return slot(*(args if accepted is None else args[:accepted]))

        guarded.__name__ = name
        return guarded

    @staticmethod
    def _lost_session_texts(error: SaveRecoveryError) -> tuple[str, str]:
        """The dead tab's notice and status-bar text (zh-TW) for a lost session."""
        message = (
            f"此分頁已中斷\n\n{error}\n\n"
            "請使用「另存新檔」將暫存副本複製到安全的位置，或關閉此分頁"
            "（暫存副本會保留到結束程式為止）。"
        )
        status = f"分頁已中斷，無法編輯。暫存副本：{error.recovery_path}"
        return message, status

    def _render_lost_session(self, session_id: str) -> None:
        """Show the dead tab of ``session_id`` in place of a document (never reads its handle)."""
        error = self.model.lost_session_error(session_id)
        if error is None:
            return
        message, status = self._lost_session_texts(error)
        self.annotations = []
        self.view.show_lost_session(message, status)
        self.view.populate_annotations_list([])
        self.view.populate_watermarks_list([])
        self.view.populate_toc([])
        self.view.update_undo_redo_tooltips("復原（無可撤銷操作）", "重做（無可重做操作）")

    def _clear_lost_session_notice(self) -> None:
        clear = getattr(self.view, "clear_lost_session", None)
        if callable(clear):
            clear()

    def _present_lost_session(self, session_id: str | None = None) -> None:
        """Turn the tab of a session the model just lost into a visibly dead tab.

        Called from every site that handles a ``SaveRecoveryError``.  Stops
        the readers bound to the session, marks the tab, and (if it is the
        visible one) replaces the document view with the notice.  A no-op
        unless the model really holds the session as lost.  Never raises: it
        runs behind the error message that explains the loss.
        """
        try:
            sid = session_id or self.model.get_active_session_id()
            if not sid or not self._is_lost(sid):
                return
            self._thumbnail_coordinator.cancel(sid)
            self._cancel_page_render_for_session(sid)
            if sid == self.model.get_active_session_id():
                self.cancel_ocr()
                self._cancel_search()
            if self._worker_snapshot_cache and self._worker_snapshot_cache[0] == sid:
                self._invalidate_worker_snapshot_cache()
            self._refresh_document_tabs()
            if sid == self.model.get_active_session_id():
                self._render_lost_session(sid)
        except Exception:
            logger.exception("could not present the lost session")

    def _report_save_failure(self, prefix: str, exc: Exception, session_id: str | None = None) -> None:
        """Show a failed save; a ``SaveRecoveryError`` also turns the tab into a dead tab."""
        if isinstance(exc, SaveRecoveryError):
            self._present_lost_session(session_id)
        show_error(self.view, self._save_failure_text(prefix, exc))

    def _save_lost_session_copy(self, session_id: str | None, path: str) -> bool:
        """Save As of a lost session: copy its recovery file to ``path`` and say where everything is.

        True when the copy was written.  The session stays lost: the message
        names the written file (to open) and the recovery file (kept until the
        program exits).  A failed copy shows the recovery path again.
        """
        error = self.model.lost_session_error(session_id)
        recovery_text = str(error) if error is not None else ""
        try:
            written = self.model.copy_lost_session_recovery(path, session_id)
        except Exception as exc:
            logger.error(f"另存暫存副本失敗: {exc}")
            show_error(self.view, f"另存失敗: {exc}\n\n{recovery_text}".rstrip())
            return False
        recovery = error.recovery_path if error is not None else ""
        QMessageBox.information(
            self.view,
            "已另存暫存副本",
            f"已將尚未儲存的編輯複製到：{written}\n請開啟該檔案繼續編輯。\n\n"
            f"此分頁已中斷，無法再儲存。暫存副本保留到結束程式為止：{recovery}",
        )
        return True

    def _text_commit_settings(self) -> TextCommitSettings:
        """The model's settings; unknown settings are the SHIPPED defaults.

        Same rule as ``PDFModel.text_commit_settings``'s setter and
        ``pdf_text_edit.edit_text`` (part-3 VERIFY defect 7): a missing or
        ``None`` value never silently selects an older configuration.
        """
        settings = getattr(self.model, "text_commit_settings", None)
        return settings if settings is not None else TextCommitSettings()

    def _next_load_gen(self, session_id: str) -> int:
        gen = self._load_gen_by_session.get(session_id, 0) + 1
        self._load_gen_by_session[session_id] = gen
        self._thumb_gen_by_session[session_id] = self._thumb_gen_by_session.get(session_id, 0) + 1
        return gen

    def _next_thumb_gen(self, session_id: str) -> int:
        gen = self._thumb_gen_by_session.get(session_id, 0) + 1
        self._thumb_gen_by_session[session_id] = gen
        return gen

    def _next_render_gen(self, session_id: str) -> int:
        render_gen_by_session = getattr(self, "_render_gen_by_session", None)
        if render_gen_by_session is None:
            render_gen_by_session = {}
            self._render_gen_by_session = render_gen_by_session
        gen = render_gen_by_session.get(session_id, 0) + 1
        render_gen_by_session[session_id] = gen
        return gen

    def _cancel_page_render_for_session(
        self,
        session_id: str | None,
        *,
        bump_generation: bool = True,
    ) -> None:
        if not session_id:
            return
        if bump_generation:
            self._next_render_gen(session_id)
        pending_by_session = getattr(self, "_render_batch_pending_by_session", None)
        if pending_by_session is not None:
            pending_by_session[session_id] = False
        coordinator = getattr(self, "_page_render_coordinator", None)
        if coordinator is not None:
            coordinator.cancel(session_id)

    def _next_stale_index_gen(self, session_id: str) -> int:
        gen = self._stale_index_gen_by_session.get(session_id, 0) + 1
        self._stale_index_gen_by_session[session_id] = gen
        return gen

    def _pause_session_background_loading(self, session_id: str | None) -> None:
        if not session_id:
            return
        self._next_load_gen(session_id)
        self._cancel_page_render_for_session(session_id)
        self._next_stale_index_gen(session_id)

    def _start_open_background_loading(self, session_id: str) -> None:
        if not session_id or not self.model.doc:
            return
        if self.model.get_active_session_id() != session_id:
            return
        self._background_loading_started_by_session[session_id] = True
        thumb_gen = self._thumb_gen_by_session.get(session_id)
        if thumb_gen is not None:
            if self._render_batch_pending_by_session.get(session_id):
                self._thumbnail_resume_pending_by_session.add(session_id)
            else:
                QTimer.singleShot(
                    0,
                    lambda sid=session_id, gen=thumb_gen: self._schedule_thumbnail_batch(
                        0,
                        sid,
                        gen,
                    ),
                )
        self._schedule_deferred_sidebar_scans(session_id)

    def _maybe_start_background_loading_after_render(self, session_id: str, page_idx: int, quality: str) -> None:
        if quality != "high":
            return
        if self._background_loading_started_by_session.get(session_id):
            return
        if self._open_priority_page_by_session.get(session_id) != page_idx:
            return
        self._background_loading_started_by_session[session_id] = True
        self._start_open_background_loading(session_id)

    def _start_open_background_loading_if_current(self, session_id: str, load_gen: int) -> None:
        if self.model.get_active_session_id() != session_id:
            return
        if self._load_gen_by_session.get(session_id) != load_gen:
            return
        if self._background_loading_started_by_session.get(session_id):
            return
        self._start_open_background_loading(session_id)

    def _capture_current_ui_state(self) -> None:
        sid = self.model.get_active_session_id()
        if not sid:
            return
        normalized_profile = self._resolve_session_profile(sid)
        self._session_ui_state[sid] = SessionUIState(
            current_page=max(0, self.view.current_page),
            scale=max(0.1, min(float(self.view.scale), 4.0)),
            search_state=self.view.get_search_ui_state(),
            mode=self._normalize_mode(getattr(self.view, "current_mode", "browse")),
            viewport_anchor=self.view.capture_viewport_anchor(),
            color_profile=normalized_profile,
        )

    def _get_ui_state(self, session_id: str) -> SessionUIState:
        state = self._session_ui_state.get(session_id)
        if state is None:
            state = SessionUIState()
            self._session_ui_state[session_id] = state
        return state

    def _normalize_color_profile(self, value: str | None) -> str:
        if not value:
            return ColorProfile.SRGB.value
        try:
            return ColorProfile.from_string(value).value
        except ValueError:
            return ColorProfile.SRGB.value

    def _fitz_colorspace_for_profile(self, profile: str) -> fitz.Colorspace:
        return safe_to_fitz_colorspace(profile)

    def _fitz_colorspace_for_session(self, session_id: str) -> fitz.Colorspace:
        return self._fitz_colorspace_for_profile(self._color_profile_for_session(session_id))

    def _color_profile_for_session(self, session_id: str) -> str:
        state = self._get_ui_state(session_id)
        return self._normalize_color_profile(state.color_profile)

    def _resolve_session_profile(self, session_id: str, *, sync_view: bool = False) -> str:
        """Return the session's normalized profile, healing unknown values back to sRGB."""
        state = self._get_ui_state(session_id)
        normalized = self._normalize_color_profile(state.color_profile)
        if state.color_profile != normalized:
            logger.warning(
                "Unknown session color profile %r; falling back to %s",
                state.color_profile,
                normalized,
            )
            state.color_profile = normalized
            if sync_view and hasattr(self.view, "set_color_profile"):
                self.view.set_color_profile(normalized)
        return normalized

    def _page_quality_map(self, session_id: str, profile: str | None = None) -> dict[int, str]:
        profile = profile or self._color_profile_for_session(session_id)
        return self._page_render_quality_by_session.setdefault(session_id, {}).setdefault(profile, {})

    def set_session_color_profile(self, session_id: str, profile: str) -> None:
        """Set a session-scoped view/print-preview color profile (view-only; no PDF mutation)."""
        if not session_id:
            raise ValueError("session_id is required")
        normalized = ColorProfile.from_string(profile).value
        state = self._get_ui_state(session_id)
        if state.color_profile == normalized:
            if self.model.get_active_session_id() == session_id and hasattr(self.view, "set_color_profile"):
                self.view.set_color_profile(normalized)
            return
        state.color_profile = normalized
        self._page_quality_map(session_id, normalized).clear()
        if self.model.get_active_session_id() == session_id:
            if hasattr(self.view, "set_color_profile"):
                self.view.set_color_profile(normalized)
            self._next_load_gen(session_id)
            self._cancel_page_render_for_session(session_id)
            if self.view.continuous_pages:
                self._schedule_visible_render(
                    session_id,
                    immediate_page_idx=self.view.current_page,
                )
            else:
                self._schedule_thumbnail_batch(
                    0,
                    session_id,
                    self._thumb_gen_by_session[session_id],
                )
                self.show_page(self.view.current_page)

    def _on_color_profile_changed(self, profile: str) -> None:
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self.set_session_color_profile(session_id, profile)

    def _refresh_document_tabs(self) -> None:
        tabs = self.model.list_sessions()
        for meta in tabs:
            path = meta.get("saved_path") or meta.get("path")
            meta["reveal_available"] = bool(path and Path(path).is_file())
        active_idx = self.model.get_active_session_index()
        self.view.set_document_tabs(tabs, active_idx)
        active_sid = self.model.get_active_session_id()
        default_save_as_path = None
        if active_sid:
            meta = self.model.get_session_meta(active_sid) or {}
            default_save_as_path = (
                meta.get("saved_path")
                or meta.get("path")
                or meta.get("display_name")
                or "未命名.pdf"
            )
        self.view.set_save_as_default_path(default_save_as_path)

    def _refresh_recent_files(self) -> None:
        updater = getattr(self.view, "set_recent_files", None)
        if not callable(updater):
            return
        entries = []
        for path in self._prefs.get_recent_files():
            try:
                available = Path(path).is_file()
            except OSError:
                # Defense in depth: one poisoned entry (e.g. an unreachable UNC
                # whose probe raises rather than returning False) must degrade to
                # unavailable, never abort activate() and take down the app.
                available = False
            entries.append(
                {
                    "path": path,
                    "display_name": Path(path).name or path,
                    "available": available,
                }
            )
        updater(entries)

    def reveal_document_in_folder(self, session_id: str) -> None:
        meta = self.model.get_session_meta(session_id) or {}
        path = meta.get("saved_path") or meta.get("path")
        if not path or not reveal_in_file_manager(str(path)):
            logger.warning("Unable to reveal document for session %s", session_id)

    def _normalize_mode(self, mode: str) -> str:
        return mode if mode in self._VALID_MODES else "browse"

    def _apply_session_mode(self, mode: str) -> None:
        normalized = self._normalize_mode(mode)
        current = self._normalize_mode(getattr(self.view, "current_mode", "browse"))
        if current != normalized:
            self.view.set_mode(normalized)

    def _empty_search_state(self) -> dict:
        return {"query": "", "results": [], "index": -1}

    def _capture_fullscreen_snapshot(self, session_id: str | None = None, use_current_view: bool = True) -> None:
        sid = session_id or self.model.get_active_session_id()
        if not sid or sid in self._fullscreen_session_snapshots:
            return
        # Record the pre-fullscreen zoom+anchor so we can restore per-tab layout on exit.
        state = self._get_ui_state(sid)
        if use_current_view:
            current_page = max(0, self.view.current_page)
            scale = max(0.1, float(self.view.scale))
            anchor = self.view.capture_viewport_anchor()
        else:
            current_page = max(0, state.current_page)
            scale = max(0.1, float(state.scale))
            anchor = state.viewport_anchor or ViewportAnchor(current_page, 0, 0)
        self._fullscreen_session_snapshots[sid] = FullscreenSessionSnapshot(
            current_page=current_page,
            scale=scale,
            anchor=anchor,
        )

    def _fullscreen_is_blocked(self) -> bool:
        if not self.model.doc:
            return True
        if self._has_active_print_submission():
            return True
        app = QApplication.instance()
        if app is None:
            return False
        for candidate in (app.activeModalWidget(), app.activePopupWidget()):
            if candidate is not None and self.view._is_widget_owned_by_main(candidate):
                return True
        return False

    def _apply_fullscreen_fit_for_active_session(self) -> None:
        if not self.view.is_fullscreen_active() or not self.model.doc:
            return
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._capture_fullscreen_snapshot(session_id)
        target_page = max(0, self.view.current_page)
        scale = self.view.compute_contain_scale_for_page(target_page)
        self.change_scale(target_page, scale)

    def _restore_fullscreen_session_state(self, session_id: str, snapshot: FullscreenSessionSnapshot) -> None:
        state = self._get_ui_state(session_id)
        state.scale = snapshot.scale
        state.current_page = snapshot.current_page
        state.viewport_anchor = snapshot.anchor

    def _restore_active_fullscreen_anchor(self, snapshot: FullscreenSessionSnapshot) -> None:
        self.view.restore_viewport_anchor(snapshot.anchor)

    def _restore_viewport_anchor_if_current(self, session_id: str, gen: int, anchor: ViewportAnchor | None) -> None:
        if anchor is None:
            return
        if self.model.get_active_session_id() != session_id:
            return
        if self._load_gen_by_session.get(session_id) != gen:
            return
        self.view.restore_viewport_anchor(anchor)

    def _schedule_restore_viewport_anchor(self, session_id: str, gen: int, anchor: ViewportAnchor | None) -> None:
        if anchor is None:
            return
        QTimer.singleShot(0, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))
        QTimer.singleShot(180, lambda sid=session_id, g=gen, a=anchor: self._restore_viewport_anchor_if_current(sid, g, a))

    def _session_page_sizes(self, session_id: str) -> list[tuple[float, float]]:
        cached = self._page_sizes_by_session.get(session_id)
        if cached and self.model.doc and len(cached) == len(self.model.doc):
            return cached
        if not self.model.doc:
            return []
        sizes = [(float(page.rect.width), float(page.rect.height)) for page in self.model.doc]
        self._page_sizes_by_session[session_id] = sizes
        return sizes

    def _render_revision(self, session_id: str) -> int:
        return self._render_revision_by_session.get(session_id, 0)

    def _bump_render_revision(self, session_id: str | None = None) -> None:
        sid = session_id or self.model.get_active_session_id()
        if not sid:
            return
        self._render_revision_by_session[sid] = self._render_revision_by_session.get(sid, 0) + 1
        self._cancel_page_render_for_session(sid, bump_generation=False)
        self._page_render_quality_by_session[sid] = {}
        self._drop_render_cache_for_session(sid)
        # Any render-visible mutation also changes doc.tobytes(); free the stale
        # snapshot now (the revision-keyed read below would miss it anyway).
        self._invalidate_worker_snapshot_cache()
        if sid == self.model.get_active_session_id():
            self._invalidate_inline_editor_preview()

    def _invalidate_inline_editor_preview(self) -> None:
        """UI step 9: the active document changed while the inline editor is
        open (toolbar undo/redo, any other edit): its token was verified
        against the old state.  End the preview session (its scratch
        snapshot is stale too) and have the View drop the token and ask for
        a fresh preview.  Never while the editor's own commit is being
        applied (that commit IS this mutation and tears the editor down).
        Known gap: OCR invisible-text injection does not bump the render
        revision (see ``capture_worker_snapshot_bytes``)."""
        view = getattr(self, "view", None)
        if view is None or not getattr(view, "text_editor", None):
            return
        if getattr(view, "_finalizing_text_edit", False):
            return
        self._end_text_edit_plan_preview_session()
        notify = getattr(view, "invalidate_text_edit_plan_preview", None)
        if callable(notify):
            notify()

    def capture_worker_snapshot_bytes(self) -> bytes:
        """Revision-keyed cache over ``model.capture_worker_snapshot_bytes()``.

        The snapshot is a full ``doc.tobytes()``; search, OCR and print each capture it
        independently on the GUI thread before ``QThread.start()``, so overlapping jobs
        on an unedited doc re-serialize identical bytes. Cache on
        ``(active_session_id, render_revision)`` — the same token the page-render cache
        trusts: any mutation that changes a rendered page bumps ``_render_revision`` via
        ``_invalidate_active_render_state``. The one doc mutation that changes
        ``doc.tobytes()`` WITHOUT a render bump is OCR invisible-text injection
        (``apply_ocr_spans``, ``render_mode=3`` — searchable but pixel-identical); the
        OCR coordinator drops this cache after applying spans so a later search never
        reads stale bytes. A session with no active id is never cached. The cached
        ``bytes`` are immutable, so handing them to a worker thread is safe.
        """
        sid = self.model.get_active_session_id()
        if not sid:
            return self.model.capture_worker_snapshot_bytes()
        revision = self._render_revision(sid)
        cached = self._worker_snapshot_cache
        if cached is not None and cached[0] == sid and cached[1] == revision:
            return cached[2]
        data = self.model.capture_worker_snapshot_bytes()
        self._worker_snapshot_cache = (sid, revision, data)
        return data

    def _invalidate_worker_snapshot_cache(self) -> None:
        """Drop the cached worker snapshot bytes (frees a full-document copy)."""
        self._worker_snapshot_cache = None

    def _drop_render_cache_for_session(self, session_id: str) -> None:
        doomed = [key for key in self._render_cache.keys() if key[0] == session_id]
        for key in doomed:
            _, cost = self._render_cache.pop(key)
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - cost)

    def _render_device_pixel_ratio(self) -> float:
        """Physical-pixel ratio of the page view, so renders stay crisp on HiDPI /
        Windows-scaled displays instead of being upscaled (blurred) by the OS.

        Capped at 2.0: beyond that the extra pixels are imperceptible but the
        per-page rasterization cost (and render-cache memory) grows quadratically,
        which would slow page changes on 3x/4x displays.
        """
        try:
            gv = getattr(self.view, "graphics_view", None)
            if gv is not None and hasattr(gv, "devicePixelRatioF"):
                dpr = float(gv.devicePixelRatioF())
                if dpr > 0.0:
                    return min(dpr, 2.0)
        except Exception:
            pass
        return 1.0

    def _render_cache_key(
        self,
        session_id: str,
        profile: str,
        page_idx: int,
        rendered_scale: float,
        quality: str,
        device_pixel_ratio: float = 1.0,
    ) -> tuple[str, str, int, int, str, int, int]:
        return (
            session_id,
            profile,
            page_idx,
            int(round(rendered_scale * 1000)),
            quality,
            self._render_revision(session_id),
            int(round(device_pixel_ratio * 100)),
        )

    def _get_cached_render(self, session_id: str, profile: str, page_idx: int, rendered_scale: float, quality: str, device_pixel_ratio: float = 1.0) -> QPixmap | None:
        key = self._render_cache_key(session_id, profile, page_idx, rendered_scale, quality, device_pixel_ratio)
        cached = self._render_cache.pop(key, None)
        if cached is None:
            return None
        pixmap, cost = cached
        self._render_cache[key] = (pixmap, cost)
        return pixmap

    def _store_cached_render(self, session_id: str, profile: str, page_idx: int, rendered_scale: float, quality: str, pixmap: QPixmap, device_pixel_ratio: float = 1.0) -> None:
        key = self._render_cache_key(session_id, profile, page_idx, rendered_scale, quality, device_pixel_ratio)
        cost = max(1, pixmap.width()) * max(1, pixmap.height()) * 4
        previous = self._render_cache.pop(key, None)
        if previous is not None:
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - previous[1])
        self._render_cache[key] = (pixmap, cost)
        self._render_cache_total_bytes += cost
        while self._render_cache_total_bytes > RENDER_CACHE_BUDGET_BYTES and self._render_cache:
            _, (_, old_cost) = self._render_cache.popitem(last=False)
            self._render_cache_total_bytes = max(0, self._render_cache_total_bytes - old_cost)

    def _render_scale_for_quality(self, target_scale: float, quality: str) -> float:
        target = max(0.1, float(target_scale))
        if quality != "low":
            return target
        return min(target, LOW_RES_RENDER_SCALE)

    def _apply_page_render_pixmap(
        self,
        session_id: str,
        page_idx: int,
        quality: str,
        profile: str,
        rendered_scale: float,
        target_scale: float,
        effective_dpr: float,
        pixmap: QPixmap,
    ) -> None:
        self._store_cached_render(
            session_id,
            profile,
            page_idx,
            rendered_scale,
            quality,
            pixmap,
            effective_dpr,
        )
        self.view.update_page_in_scene_scaled(
            page_idx,
            pixmap,
            rendered_scale,
            target_scale,
        )
        self._page_quality_map(session_id, profile)[page_idx] = quality
        self._maybe_start_background_loading_after_render(session_id, page_idx, quality)

    def _render_page_into_scene(self, session_id: str, page_idx: int, quality: str) -> bool:
        if (
            self.model.get_active_session_id() != session_id
            or not self.model.doc
            or page_idx < 0
            or page_idx >= len(self.model.doc)
        ):
            return False
        target_scale = max(0.1, float(self.view.scale))
        rendered_scale = self._render_scale_for_quality(target_scale, quality)
        effective_dpr = self._render_device_pixel_ratio() if quality == "high" else 1.0
        profile = self._color_profile_for_session(session_id)
        cached = self._get_cached_render(
            session_id,
            profile,
            page_idx,
            rendered_scale,
            quality,
            effective_dpr,
        )
        if cached is None:
            pix = self.model.get_page_pixmap(
                page_idx + 1,
                rendered_scale * effective_dpr,
                colorspace=self._fitz_colorspace_for_profile(profile),
            )
            cached = pixmap_to_qpixmap(pix)
            if effective_dpr != 1.0:
                cached.setDevicePixelRatio(effective_dpr)
        self._apply_page_render_pixmap(
            session_id,
            page_idx,
            quality,
            profile,
            rendered_scale,
            target_scale,
            effective_dpr,
            cached,
        )
        return True

    def _page_render_identity_matches(self, identity: PageRenderIdentity) -> bool:
        active_token = getattr(
            getattr(self, "_page_render_coordinator", None),
            "active_token",
            None,
        )
        if isinstance(active_token, str) and identity.token != active_token:
            return False
        if self.model.get_active_session_id() != identity.session_id or not self.model.doc:
            return False
        if self._render_gen_by_session.get(identity.session_id) != identity.generation:
            return False
        if self._render_revision(identity.session_id) != identity.revision:
            return False
        if identity.page_index < 0 or identity.page_index >= len(self.model.doc):
            return False
        if self._color_profile_for_session(identity.session_id) != identity.color_profile:
            return False
        target_scale = max(0.1, float(self.view.scale))
        rendered_scale = self._render_scale_for_quality(target_scale, identity.quality)
        effective_dpr = (
            self._render_device_pixel_ratio() if identity.quality == "high" else 1.0
        )
        return (
            abs(identity.target_scale - target_scale) <= 1e-6
            and abs(identity.rendered_scale - rendered_scale) <= 1e-6
            and abs(identity.device_pixel_ratio - effective_dpr) <= 1e-6
        )

    def _dispatch_page_render_request(
        self,
        session_id: str,
        page_idx: int,
        quality: str,
        gen: int,
    ) -> bool:
        if (
            self.model.get_active_session_id() != session_id
            or not self.model.doc
            or page_idx < 0
            or page_idx >= len(self.model.doc)
        ):
            return False
        if self.get_watermarks():
            return False
        target_scale = max(0.1, float(self.view.scale))
        rendered_scale = self._render_scale_for_quality(target_scale, quality)
        effective_dpr = self._render_device_pixel_ratio() if quality == "high" else 1.0
        profile = self._color_profile_for_session(session_id)
        if (
            self._get_cached_render(
                session_id,
                profile,
                page_idx,
                rendered_scale,
                quality,
                effective_dpr,
            )
            is not None
        ):
            return False
        try:
            snapshot_bytes = self.capture_worker_snapshot_bytes()
        except Exception as exc:
            logger.warning("Unable to capture page-render snapshot: %s", exc)
            return False
        self._page_render_coordinator.request(
            session_id=session_id,
            generation=gen,
            revision=self._render_revision(session_id),
            page_index=page_idx,
            quality=quality,
            rendered_scale=rendered_scale,
            target_scale=target_scale,
            color_profile=profile,
            device_pixel_ratio=effective_dpr,
            snapshot_bytes=snapshot_bytes,
        )
        return True

    def _consume_page_render_image(
        self,
        identity: PageRenderIdentity,
        image: QImage,
    ) -> None:
        if not self._page_render_identity_matches(identity):
            return
        pixmap = QPixmap.fromImage(image)
        if identity.device_pixel_ratio != 1.0:
            pixmap.setDevicePixelRatio(identity.device_pixel_ratio)
        self._apply_page_render_pixmap(
            identity.session_id,
            identity.page_index,
            identity.quality,
            identity.color_profile,
            identity.rendered_scale,
            identity.target_scale,
            identity.device_pixel_ratio,
            pixmap,
        )
        if self._render_batch_pending_by_session.get(identity.session_id):
            QTimer.singleShot(
                0,
                lambda sid=identity.session_id, gen=identity.generation: self._process_visible_render_batch(
                    sid,
                    gen,
                ),
            )

    def _on_page_render_failed(
        self,
        identity: PageRenderIdentity,
        exc: Exception,
    ) -> None:
        if not self._page_render_identity_matches(identity):
            return
        logger.warning(
            "Background page render failed for session=%s page=%s: %s",
            identity.session_id,
            identity.page_index + 1,
            exc,
        )
        self._render_batch_pending_by_session[identity.session_id] = False
        self._resume_thumbnails_after_visible_render(
            identity.session_id,
            identity.generation,
        )

    def _pause_thumbnails_for_visible_render(self, session_id: str) -> None:
        self._thumbnail_resume_pending_by_session.add(session_id)
        self._thumbnail_coordinator.cancel(session_id)

    def _resume_thumbnails_after_visible_render(
        self,
        session_id: str,
        render_gen: int,
    ) -> None:
        if session_id not in self._thumbnail_resume_pending_by_session:
            return
        if self.model.get_active_session_id() != session_id:
            return
        if self._render_gen_by_session.get(session_id) != render_gen:
            return
        thumb_gen = self._thumb_gen_by_session.get(session_id)
        if thumb_gen is None:
            return
        self._thumbnail_resume_pending_by_session.discard(session_id)
        self._schedule_thumbnail_batch(0, session_id, thumb_gen)

    def _visible_render_targets(self) -> tuple[list[int], list[int]]:
        if not self.view.page_items:
            return ([], [])
        visible_start, visible_end = self.view.visible_page_range(prefetch=0)
        prefetch_start, prefetch_end = self.view.visible_page_range(
            prefetch=VISIBLE_PREFETCH_PAGES
        )
        visible_pages = (
            list(range(visible_start, visible_end + 1))
            if visible_end >= visible_start
            else []
        )
        prefetch_pages = (
            list(range(prefetch_start, prefetch_end + 1))
            if prefetch_end >= prefetch_start
            else []
        )
        return (visible_pages, prefetch_pages)

    def _schedule_visible_render(
        self,
        session_id: str,
        immediate_page_idx: int | None = None,
    ) -> None:
        if not session_id or not self.model.doc or not self.view.continuous_pages:
            return
        profile = self._color_profile_for_session(session_id)
        if immediate_page_idx is not None:
            current_quality = self._page_quality_map(session_id, profile).get(
                immediate_page_idx
            )
            if current_quality not in {"low", "high"}:
                self._render_page_into_scene(session_id, immediate_page_idx, "low")
        if self._render_batch_pending_by_session.get(session_id):
            return
        gen = self._next_render_gen(session_id)
        self._render_batch_pending_by_session[session_id] = True
        self._pause_thumbnails_for_visible_render(session_id)
        QTimer.singleShot(
            0,
            lambda sid=session_id, g=gen: self._process_visible_render_batch(sid, g),
        )

    def _process_visible_render_batch(self, session_id: str, gen: int) -> None:
        if (
            self.model.get_active_session_id() != session_id
            or self._render_gen_by_session.get(session_id) != gen
            or not self.model.doc
            or not self.view.continuous_pages
        ):
            self._render_batch_pending_by_session[session_id] = False
            return
        visible_pages, prefetch_pages = self._visible_render_targets()
        if not prefetch_pages:
            self._render_batch_pending_by_session[session_id] = False
            self._resume_thumbnails_after_visible_render(session_id, gen)
            return

        profile = self._color_profile_for_session(session_id)
        page_quality = self._page_quality_map(session_id, profile)
        candidates: list[tuple[int, str]] = []
        for page_idx in visible_pages:
            quality = page_quality.get(page_idx)
            if quality is None:
                candidates.append((page_idx, "low"))
            elif quality == "low":
                candidates.append((page_idx, "high"))
        for page_idx in prefetch_pages:
            if page_idx in visible_pages:
                continue
            if page_quality.get(page_idx) is None:
                candidates.append((page_idx, "low"))

        if not candidates:
            self._render_batch_pending_by_session[session_id] = False
            self._resume_thumbnails_after_visible_render(session_id, gen)
            return

        page_idx, quality = candidates[0]
        if self._dispatch_page_render_request(session_id, page_idx, quality, gen):
            return
        if self._render_page_into_scene(session_id, page_idx, quality):
            QTimer.singleShot(
                0,
                lambda sid=session_id, g=gen: self._process_visible_render_batch(
                    sid,
                    g,
                ),
            )
            return
        self._render_batch_pending_by_session[session_id] = False
        self._resume_thumbnails_after_visible_render(session_id, gen)

    def _schedule_deferred_sidebar_scans(self, session_id: str) -> None:
        if not session_id:
            return
        revision = self._render_revision(session_id)
        QTimer.singleShot(
            0,
            lambda sid=session_id, rev=revision: self._run_deferred_sidebar_scans(sid, rev),
        )

    def _run_deferred_sidebar_scans(self, session_id: str, revision: int) -> None:
        if (
            self.model.get_active_session_id() != session_id
            or self._render_revision(session_id) != revision
        ):
            return
        self.load_annotations()
        self.load_watermarks()

    def _invalidate_active_render_state(self, clear_page_sizes: bool = False) -> None:
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._bump_render_revision(session_id)
        if clear_page_sizes:
            self._page_sizes_by_session.pop(session_id, None)
            # The page list or a page size changed (or an undo / redo of it): the
            # watermark panel prints each watermark's page numbers, which a delete /
            # move / insert / merge renumbers and a watermark whose last page is gone
            # leaves (F17-COH-3).
            self.load_watermarks()

    def enter_fullscreen(self) -> None:
        self.activate()
        if self._fullscreen_is_blocked():
            return
        # Part 5 / A2 (Q4): settle the inline editor FIRST, like a zoom: a
        # verified edit commits; un-applied input keeps the editor and F5
        # enters nothing -- and clears nothing (search, snapshot, mode).
        if not self.view.release_text_editor_for_fullscreen():
            return
        self._cancel_search()
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._fullscreen_session_snapshots.clear()
        self._capture_fullscreen_snapshot(session_id)
        # Enter fullscreen from any mode, but normalize interactions to a clean browse state.
        self.view.cancel_interaction_for_fullscreen()
        self.view._clear_text_selection()
        self.view.clear_search_ui_state()
        self._get_ui_state(session_id).search_state = self._empty_search_state()
        self.view.set_mode("browse")
        self.view.enter_fullscreen_ui()
        self._apply_fullscreen_fit_for_active_session()

    def exit_fullscreen(self) -> None:
        if not self.view.is_fullscreen_active():
            return
        # Restore all visited tabs to their pre-fullscreen layout, keep current tab active.
        active_session_id = self.model.get_active_session_id()
        snapshots = dict(self._fullscreen_session_snapshots)
        self.view.exit_fullscreen_ui()
        for sid, snapshot in snapshots.items():
            self._restore_fullscreen_session_state(sid, snapshot)
        if active_session_id and active_session_id in snapshots:
            snapshot = snapshots[active_session_id]
            self._render_active_session(initial_page_idx=snapshot.current_page)
            QTimer.singleShot(0, lambda snap=snapshot: self._restore_active_fullscreen_anchor(snap))
            QTimer.singleShot(180, lambda snap=snapshot: self._restore_active_fullscreen_anchor(snap))
        self._fullscreen_session_snapshots.clear()

    def toggle_fullscreen(self) -> None:
        if self.view.is_fullscreen_active():
            self.exit_fullscreen()
            return
        self.enter_fullscreen()

    def handle_fullscreen_view_resized(self) -> None:
        if self.view.is_fullscreen_active() and self.model.doc:
            self._apply_fullscreen_fit_for_active_session()

    def _on_viewport_changed(self) -> None:
        session_id = self.model.get_active_session_id()
        if not session_id or not self.view.continuous_pages:
            return
        self._schedule_visible_render(session_id)

    def _reset_empty_ui(self) -> None:
        self.annotations = []
        self._clear_lost_session_notice()
        self.view.clear_document_tabs()
        self.view.reset_document_view()
        self.view.populate_annotations_list([])
        self.view.populate_watermarks_list([])
        self.view.populate_toc([])
        self.view.update_undo_redo_tooltips("復原（無可撤銷操作）", "重做（無可重做操作）")

    def _render_active_session(self, initial_page_idx: int | None = None) -> None:
        sid = self.model.get_active_session_id()
        # The ONE tab-switch guard (S14-SAVEREC-DEAD-TAB): every switch, open,
        # close and detach re-renders through here.  A lost session has no
        # document; its handle is never read.
        if sid and self._is_lost(sid):
            self._render_lost_session(sid)
            return
        if not sid or not self.model.doc:
            self._reset_empty_ui()
            return
        self._clear_lost_session_notice()
        self.view.ensure_heavy_panels_initialized()

        state = self._get_ui_state(sid)
        profile = self._resolve_session_profile(sid)
        if hasattr(self.view, "set_color_profile"):
            self.view.set_color_profile(profile)
        if initial_page_idx is None:
            initial_page_idx = state.current_page
        initial_page_idx = max(0, min(initial_page_idx, len(self.model.doc) - 1))
        self._desired_scroll_page[sid] = initial_page_idx
        self._open_priority_page_by_session[sid] = initial_page_idx
        self._background_loading_started_by_session[sid] = False
        self._render_batch_pending_by_session[sid] = False

        self.view.scale = state.scale
        self.view.total_pages = len(self.model.doc)
        self._page_quality_map(sid, profile).clear()
        self._session_page_sizes(sid)
        self.view.initialize_continuous_placeholders(self._page_sizes_by_session[sid], state.scale, initial_page_idx)
        self.view.set_thumbnail_placeholders(len(self.model.doc))
        self.view.apply_search_ui_state(state.search_state)
        self._apply_session_mode(self._global_mode)
        self._update_undo_redo_tooltips()
        self.load_toc()

        gen = self._next_load_gen(sid)
        self._schedule_visible_render(sid, immediate_page_idx=initial_page_idx)
        QTimer.singleShot(
            OPEN_BACKGROUND_FALLBACK_MS,
            lambda sid=sid, load_gen=gen: self._start_open_background_loading_if_current(sid, load_gen),
        )
        self._schedule_restore_viewport_anchor(sid, gen, state.viewport_anchor)

    def _finalize_inline_editor_before_session_change(self) -> None:
        """UI step 9 (VERIFY part 2 headline defect): the inline editor is
        finalized against the ORIGINAL -- still active -- document session
        before ANY session change (open, tab switch, tab close, detach): a
        verified edit commits there, anything else is discarded with a
        visible warning.  Before this, ``open_pdf`` switched the session
        first and the scene rebuild's finalize applied the edit to the NEW
        document (with a content-derived token, even into a byte-identical
        copy).  The request is also bound to its session
        (``EditTextRequest.session_id``) as the second, structural guard."""
        view = self.view
        if getattr(view, "text_editor", None):
            finalize = getattr(view, "finalize_text_edit_before_session_change", None)
            if callable(finalize):
                finalize()
            else:
                view._finalize_text_edit()
        # No preview may outlive the session it was made in.
        self._end_text_edit_plan_preview_session()

    def _inline_editor_session_id(self) -> str | None:
        """The document session the open inline editor belongs to (None: no
        editor).  The editor is always finalized before a session change, so
        without a stamp it belongs to the active session."""
        view = getattr(self, "view", None)
        if not getattr(view, "text_editor", None):
            return None
        return getattr(view, "editing_session_id", None) or self.model.get_active_session_id()

    def _inline_editor_has_unapplied_input(self, session_id: str | None = None) -> bool:
        """Finalize policy completion (defects 2, 3): the open inline editor
        (of ``session_id``, when given) holds input that is not in the PDF --
        a close prompt must count it as an unsaved change."""
        editor_sid = self._inline_editor_session_id()
        if editor_sid is None or (session_id is not None and editor_sid != session_id):
            return False
        if editor_sid not in self.model.session_ids:
            # An orphan editor (its document is already closed): there is
            # nothing its input could be saved into.
            return False
        has_input = getattr(self.view, "has_unapplied_text_edit", None)
        return bool(has_input()) if callable(has_input) else False

    def _finalize_inline_editor_for_close(self, session_id: str | None, *, save: bool) -> bool:
        """Finalize the inline editor of ``session_id`` AFTER the user answered
        a close prompt (never before: Cancel must find it untouched).  True
        when the close may proceed; False when un-applied input was kept
        (``save`` could not include it) -- the caller aborts the close."""
        editor_sid = self._inline_editor_session_id()
        if editor_sid is None or (session_id is not None and editor_sid != session_id):
            return True
        finalize = getattr(self.view, "finalize_text_edit_for_close", None)
        if not callable(finalize):
            return True
        return bool(finalize(save=save))

    def _switch_to_session_id(self, session_id: str) -> None:
        active = self.model.get_active_session_id()
        if active == session_id:
            self._refresh_document_tabs()
            return
        self._finalize_inline_editor_before_session_change()
        # In-flight readers are bound to the departing session.
        self._thumbnail_coordinator.cancel(active)
        self._cancel_page_render_for_session(active)
        self._cancel_search()
        self._capture_current_ui_state()
        self.model.activate_session(session_id)
        self._refresh_document_tabs()
        state = self._get_ui_state(session_id)
        self._render_active_session(initial_page_idx=state.current_page)

    def open_pdf(self, path: str):
        self.activate()
        existing_sid = self.model.find_session_by_path(path)
        if existing_sid:
            self._switch_to_session_id(existing_sid)
            self._prefs.add_recent_file(path)
            self._refresh_recent_files()
            return

        def _teardown_before_session_change() -> None:
            # UI step 9: finalize against the CURRENT session before the open
            # appends + activates the new one.  The model calls this only once
            # the file is validated and the session really changes (F11-OPEN-4):
            # a corrupt / over-limit file or a cancelled password prompt leaves
            # the tab as it was -- inline editor input and a running OCR job
            # included.
            self._finalize_inline_editor_before_session_change()
            # Opening appends + activates a new session; stop any background readers on the old doc.
            self.cancel_ocr()
            self._cancel_search()
            self._capture_current_ui_state()

        password = None
        while True:
            try:
                sid = self.model.open_pdf(
                    path,
                    password=password,
                    append=True,
                    before_activate=_teardown_before_session_change,
                )
                self._session_ui_state.setdefault(sid, SessionUIState())
                self._refresh_document_tabs()
                self._render_active_session(initial_page_idx=0)
                self._prefs.add_recent_file(path)
                self._refresh_recent_files()
                break
            except PdfPasswordRequiredError:
                # 加密 PDF 需要密碼：彈出密碼框後重試。依例外型別判斷，
                # 絕不比對訊息文字（訊息含使用者路徑，F11-OPEN-3）。
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    if not self.model.get_active_session_id():
                        self._reset_empty_ui()
                    break
                password = pw
                continue
            except PdfPasswordRejectedError:
                # 密碼驗證失敗：提示後再次詢問密碼
                show_error(self.view, "密碼錯誤，請重試。")
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    break
                password = pw
                continue
            except RuntimeError as e:
                # 其他 RuntimeError
                logger.error(f"打開 PDF 失敗: {e}")
                show_error(self.view, f"打開 PDF 失敗: {e}")
                break
            except Exception as e:
                logger.error(f"打開 PDF 失敗: {e}")
                show_error(self.view, f"打開 PDF 失敗: {e}")
                break

    def handle_forwarded_cli(self, files: list[str]) -> None:
        forwarded_files = [str(path) for path in files if str(path).strip()]

        def _apply() -> None:
            self.activate()
            if self.view.isMinimized():
                self.view.showNormal()
            self.view.raise_()
            self.view.activateWindow()
            for path in forwarded_files:
                self.open_pdf(path)
            self.view.graphics_view.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        self._run_when_session_activation_allowed(_apply)

    # ------------------------------------------------------------------
    # Activations from outside the user's flow wait for modals (F11-1)
    # ------------------------------------------------------------------

    def _background_progress_dialogs(self) -> list[object]:
        """Window-modal progress dialogs this controller's own background jobs
        show with ``show()``.  No caller waits on them (no nested ``exec()``)
        and their jobs are bound to their session, so they block nothing."""
        dialogs: list[object] = [getattr(self, "_optimize_progress_dialog", None)]
        print_coordinator = getattr(self, "_print_coordinator", None)
        dialogs.append(getattr(print_coordinator, "_print_progress_dialog", None))
        ocr_coordinator = getattr(self, "_ocr_coordinator", None)
        dialogs.append(getattr(ocr_coordinator, "_ocr_progress_dialog", None))
        return [dialog for dialog in dialogs if dialog is not None]

    def _session_activation_blocked(self) -> bool:
        """True while a modal dialog or popup is up whose caller may resume and
        act on "the active session" once it returns.

        A nested ``exec()`` loop (any QDialog, QMessageBox, QMenu, and the
        native file dialogs) dispatches timers and queued signals.  A tab
        activation started from outside the user's flow -- a forwarded
        second-launch open, a worker's completion handler -- would otherwise
        run inside it, and the dialog's result (Save As target, merge list,
        optimize options, metadata, export) lands on the newly opened tab.
        Every visible modal top-level is checked, not only the topmost one, so
        a progress dialog stacked over an ``exec()``-ed dialog still blocks.
        """
        app = QApplication.instance()
        if app is None:
            return False
        if app.activePopupWidget() is not None:
            return True
        exempt = self._background_progress_dialogs()

        def _blocks(widget) -> bool:
            return widget is not None and not any(widget is dialog for dialog in exempt)

        if _blocks(app.activeModalWidget()):
            return True
        return any(
            widget.isVisible() and widget.isModal() and _blocks(widget)
            for widget in app.topLevelWidgets()
        )

    def _run_when_session_activation_allowed(self, callback) -> None:
        """Run ``callback`` (which may open or activate a tab) on a later turn
        of the event loop, once no blocking modal is up (F11-1).  Callbacks
        run in arrival order; a hand-off that arrives during a modal is kept,
        not dropped."""
        self._deferred_session_activation_queue().append(callback)
        QTimer.singleShot(0, self._drain_deferred_session_activations)

    def _deferred_session_activation_queue(self) -> list:
        # getattr: PDFController.__new__ test doubles skip __init__.
        queue = getattr(self, "_deferred_session_activations", None)
        if queue is None:
            queue = self._deferred_session_activations = []
        return queue

    def _drain_deferred_session_activations(self) -> None:
        if getattr(self, "_deferred_session_activation_draining", False):
            # A callback is running (e.g. inside its own password prompt); the
            # outer drain picks up what arrived meanwhile when it returns.
            return
        queue = self._deferred_session_activation_queue()
        self._deferred_session_activation_draining = True
        try:
            while queue:
                if self._session_activation_blocked():
                    self._schedule_deferred_session_activation_retry()
                    return
                callback = queue.pop(0)
                try:
                    callback()
                except Exception:
                    logger.exception("deferred session activation failed")
        finally:
            self._deferred_session_activation_draining = False

    def _schedule_deferred_session_activation_retry(self) -> None:
        if getattr(self, "_deferred_session_activation_retry_armed", False):
            return
        self._deferred_session_activation_retry_armed = True

        def _retry() -> None:
            self._deferred_session_activation_retry_armed = False
            self._drain_deferred_session_activations()

        QTimer.singleShot(DEFERRED_SESSION_ACTIVATION_RETRY_MS, _retry)

    def start_merge_pdfs(self) -> None:
        active_sid = self.model.get_active_session_id()
        if not active_sid:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        meta = self.model.get_session_meta(active_sid)
        if not meta:
            show_error(self.view, "沒有可合併的目前文件")
            return

        from model.merge_session import MergeSessionModel
        from view.pdf_view import MergePdfDialog

        session_model = MergeSessionModel(
            current_label=meta["display_name"],
            current_source_id=active_sid,
        )
        dialog = MergePdfDialog(session_model, self.view, file_resolver=self._resolve_merge_file)
        if dialog.exec() != QDialog.Accepted:
            return

        ordered_sources: list[dict] = []
        for entry in dialog.ordered_entries():
            if getattr(entry, "source_kind", "") == "current":
                ordered_sources.append({"source_kind": "current"})
                continue
            resolved = self._resolve_merge_file(
                {
                    "source_kind": "file",
                    "path": getattr(entry, "path", None),
                    "password": getattr(entry, "password", None),
                }
            )
            if resolved is not None:
                ordered_sources.append(resolved)

        if not ordered_sources:
            show_error(self.view, "沒有可合併的有效 PDF")
            return

        if dialog.selected_mode() == "merge_current":
            # The merge list was built for ``active_sid``; never apply it to
            # whatever tab became active while the dialog was up (F11-1).
            if self.model.get_active_session_id() != active_sid:
                show_error(self.view, "合併期間目前文件已切換，已取消合併，請重新操作。")
                return
            self.merge_ordered_sources_into_current(ordered_sources)
            return

        path, _ = QFileDialog.getSaveFileName(self.view, "儲存合併後的 PDF", "merged.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.save_ordered_sources_as_new(ordered_sources, path)

    def _choose_merge_encryption(self, keep_encryption: bool | None, *, uses_current: bool) -> tuple[bool, bool]:
        """``(proceed, keep)`` for a merge that reads the active document (S17-ENC-MERGE).

        An unencrypted active document, or a result that holds nothing of it, needs
        no answer.  Otherwise the owner's choice applies: ASK EACH TIME whether the
        merged result keeps the document's encryption and permissions or is
        unencrypted; cancelling stops the merge before anything is touched.
        ``keep_encryption`` (a caller that already knows the answer) skips the question.
        """
        if not uses_current or not self.model.active_document_is_encrypted():
            return True, False
        if keep_encryption is not None:
            return True, bool(keep_encryption)
        choice = self.view.ask_merge_encryption_choice()
        if choice == "keep":
            return True, True
        if choice == "plain":
            return True, False
        return False, False

    def merge_ordered_sources_into_current(
        self, ordered_sources: list[dict], *, keep_encryption: bool | None = None
    ) -> None:
        if not self.model.doc:
            raise ValueError("沒有開啟的PDF文件")

        proceed, keep = self._choose_merge_encryption(
            keep_encryption,
            uses_current=True,
        )
        if not proceed:
            return
        self._cancel_search()
        before = self.model._capture_doc_snapshot()
        # The result becomes the live (unbaked) document: the watermark list follows
        # its pages through ``page_origins`` instead of being drawn into the copy
        # (F17-COH-3 / F17-COH-4).
        merged_doc, page_origins = self.model.compose_merged_document_with_origins(
            ordered_sources, keep_encryption=keep, bake_watermarks=False
        )
        try:
            # Through the model's native-sink serializer (H10-2 Part B), and in
            # memory: the merge may hold pages decrypted from encrypted sources.
            after = self.model.serialize_document_bytes(merged_doc, in_memory=True)
        finally:
            merged_doc.close()

        self.model.replace_active_document_from_snapshot(after, [1], page_origins=page_origins)
        # The live document was swapped (page count and content): kill every
        # revision-keyed cache (worker snapshot for search/OCR/render, render
        # cache, page sizes) like the other structural ops do.
        self._invalidate_active_render_state(clear_page_sizes=True)
        cmd = SnapshotCommand(
            model=self.model,
            command_type="merge_pdfs",
            affected_pages=[1],
            before_bytes=before,
            after_bytes=after,
            description="合併 PDF",
        )
        self.model.command_manager.record(cmd)
        self._invalidate_thumbnails()
        self._rebuild_continuous_scene(0)
        self._schedule_stale_index_drain()
        self._update_undo_redo_tooltips()

    def save_ordered_sources_as_new(
        self, ordered_sources: list[dict], output_path: str, *, keep_encryption: bool | None = None
    ) -> None:
        # The question only matters when the new file holds pages of the
        # (encrypted) active document.
        proceed, keep = self._choose_merge_encryption(
            keep_encryption,
            uses_current=any((source or {}).get("source_kind") == "current" for source in ordered_sources or []),
        )
        if not proceed:
            return
        merged_doc = self.model.compose_merged_document(ordered_sources, keep_encryption=keep)
        try:
            # The target may be a file a thumbnail worker of a just-closed tab
            # still reads; join it like any other write over a user path.
            with self._background_file_readers_released(resume_thumbnails=True):
                self.model.save_external_document(merged_doc, output_path)
        finally:
            merged_doc.close()
        self.open_pdf(output_path)

    def _resolve_merge_file(self, entry: dict) -> dict | None:
        path = (entry or {}).get("path")
        if not path:
            return None

        password = entry.get("password")
        while True:
            try:
                resolved = self.model.open_merge_source(path, password=password)
                resolved["source_kind"] = "file"
                return resolved
            except PdfPasswordRequiredError:
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            except PdfPasswordRejectedError:
                show_error(self.view, "密碼錯誤，請重試。")
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            except RuntimeError as e:
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None
            except Exception as e:
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None

    def start_optimize_pdf_copy(self) -> None:
        # UI flow:
        # file-tab action -> dialog -> save path -> background optimize worker -> open new tab
        active_sid = self.model.get_active_session_id()
        if not active_sid or not self.model.doc:
            show_error(self.view, "沒有可最佳化的 PDF")
            return
        if self._has_active_optimize_submission():
            self._show_optimize_progress_dialog("正在最佳化 PDF 副本...")
            return

        meta = self.model.get_session_meta(active_sid) or {}
        source_path = meta.get("path") or "optimized.pdf"
        source_stem = Path(source_path).stem or "optimized"
        suggested_name = f"{source_stem}.optimized.pdf"

        from view.pdf_view import OptimizePdfDialog
        dialog = OptimizePdfDialog(
            self.view,
            audit_provider=self.model.build_pdf_audit_report,
            capabilities=self.model.optimize_capabilities(),
            preset_options=PDFModel.preset_optimize_options,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self.view,
            "另存為最佳化的副本",
            suggested_name,
            "PDF (*.pdf)",
        )
        if not output_path:
            return
        if not Path(output_path).suffix:
            output_path = f"{output_path}.pdf"
        if meta.get("path"):
            current_canonical = self.model._canonicalize_path(meta["path"])
            if self.model._canonicalize_path(output_path) == current_canonical:
                show_error(self.view, "最佳化副本必須使用新的輸出路徑，且不能覆蓋已開啟的檔案。")
                return

        # Bind to the tab the dialog was opened for, not whatever is active
        # after the two dialogs returned (F11-1).
        self._start_optimize_submission(output_path, dialog.get_options(), session_id=active_sid)

    def _has_active_optimize_submission(self) -> bool:
        return self._optimize_thread is not None

    def _show_optimize_progress_dialog(self, label_text: str) -> None:
        if self._optimize_progress_dialog is None:
            progress = QProgressDialog(label_text, "", 0, 0, self.view)
            progress.setWindowTitle("最佳化 PDF")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            self._optimize_progress_dialog = progress
        else:
            self._optimize_progress_dialog.setLabelText(label_text)
        self._optimize_progress_dialog.show()
        self._optimize_progress_dialog.raise_()

    def _hide_optimize_progress_dialog(self) -> None:
        if self._optimize_progress_dialog is None:
            return
        self._optimize_progress_dialog.close()
        self._optimize_progress_dialog.deleteLater()
        self._optimize_progress_dialog = None

    def _set_optimize_ui_busy(self, busy: bool) -> None:
        action = getattr(self.view, "_action_optimize_copy", None)
        if action is not None:
            action.setEnabled(not busy)

    def _prompt_optimize_output_credentials(
        self, source: pdf_optimizer.OptimizeSourceSnapshot
    ) -> tuple[bool, pdf_optimizer.OptimizeOutputCredentials | None]:
        enc = source.encryption
        if enc is None or not enc.should_encrypt:
            return True, None
        if enc.auth_level == 6:
            return True, pdf_optimizer.credentials_for_encryption(enc, None)

        role = "擁有者" if enc.auth_level in (2, None) else "使用者"
        generated = secrets.token_urlsafe(24)
        password, accepted = QInputDialog.getText(
            self.view,
            "設定最佳化副本密碼",
            f"請設定新的{role}密碼（可編輯預設強密碼）：",
            QLineEdit.Password,
            generated,
        )
        if not accepted:
            return False, None
        if not password:
            if enc.auth_level is None:
                show_error(self.view, "擁有者與使用者密碼不可同時留白。")
                return False, None
            confirmed = QMessageBox.question(
                self.view,
                "確認留白密碼",
                "留白會讓對應角色不需要密碼即可開啟副本。確定要繼續嗎？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirmed != QMessageBox.Yes:
                return False, None
        return True, pdf_optimizer.credentials_for_encryption(enc, password)

    def _start_optimize_submission(
        self, output_path: str, options: object, *, session_id: str | None = None
    ) -> None:
        bridge = self._optimize_worker_bridge
        if bridge is None:
            raise RuntimeError("Optimize worker bridge is not initialized")
        # Background scene/index batches for the active tab can dominate large-PDF optimize latency.
        # The worker calls `PDFModel.save_optimized_copy(...)` (facade); optimizer internals live in `model/pdf_optimizer.py`.
        self._optimize_paused_session_id = session_id or self.model.get_active_session_id()
        source = pdf_optimizer.capture_optimize_source(
            self.model, self._optimize_paused_session_id
        )
        accepted, credentials = self._prompt_optimize_output_credentials(source)
        if not accepted:
            self._optimize_paused_session_id = None
            return
        self._pause_session_background_loading(self._optimize_paused_session_id)
        # Bind the request to the tab active at dispatch (R5-03 / Codex F1).
        request = OptimizePdfCopyRequest(
            output_path=output_path,
            options=options,
            source=source,
            credentials=credentials,
        )
        thread = QThread(self.view)
        worker = _OptimizePdfCopyWorker(self.model, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(bridge.forward_succeeded)
        worker.failed.connect(bridge.forward_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(bridge.notify_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._optimize_thread = thread
        self._optimize_worker = worker
        self._set_optimize_ui_busy(True)
        self._show_optimize_progress_dialog("正在最佳化 PDF 副本...")
        thread.start()

    @staticmethod
    def _format_size_units(size_bytes: int) -> str:
        units = ["bytes", "KB", "MB", "GB", "TB"]
        value = float(max(0, int(size_bytes)))
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size_bytes):,} bytes"
        return f"{value:.2f} {units[unit_index]} ({int(size_bytes):,} bytes)"

    def _on_optimize_copy_succeeded(self, result) -> None:
        self._hide_optimize_progress_dialog()
        if self._optimize_close_pending:
            return
        # The worker's signal can arrive inside any modal's nested loop (the
        # progress dialog can be dismissed with Esc, freeing the window for
        # Save As etc.); opening the copy there would switch the active tab
        # under that dialog (F11-1).
        self._run_when_session_activation_allowed(lambda: self._open_optimized_copy(result))

    def _open_optimized_copy(self, result) -> None:
        if self._optimize_close_pending:
            return
        self.open_pdf(result.output_path)
        original_size = self._format_size_units(result.original_bytes)
        optimized_size = self._format_size_units(result.optimized_bytes)
        saved_size = self._format_size_units(result.bytes_saved)
        QMessageBox.information(
            self.view,
            "最佳化完成",
            (
                f"已建立最佳化副本:\n{result.output_path}\n\n"
                f"原始大小: {original_size}\n"
                f"最佳大小: {optimized_size}\n"
                f"節省: {saved_size} ({result.percent_saved:.1f}%)"
            ),
        )

    def _on_optimize_copy_failed(self, exc) -> None:
        self._hide_optimize_progress_dialog()
        if self._optimize_close_pending:
            return
        # Model raises PdfOptimizeError with a complete user-facing message;
        # re-wrapping here doubled the "最佳化 PDF 失敗:" prefix.
        logger.error("最佳化 PDF 失敗: %s", exc)
        show_error(self.view, str(exc))

    def _on_optimize_thread_finished(self) -> None:
        self._optimize_thread = None
        self._optimize_worker = None
        self._optimize_paused_session_id = None
        self._set_optimize_ui_busy(False)
        if self._optimize_close_pending:
            self._optimize_close_pending = False
            self.view.close()

    def on_tab_changed(self, index: int):
        sid = self.model.get_session_id_by_index(index)
        if not sid:
            return
        self._switch_to_session_id(sid)
        if self.view.is_fullscreen_active():
            self._capture_fullscreen_snapshot(sid, use_current_view=False)
            self._apply_fullscreen_fit_for_active_session()

    @contextlib.contextmanager
    def _background_file_readers_released(self, *, resume_thumbnails: bool):
        """Join the thumbnail file worker around a save of a path it may read.

        The clean-session thumbnail worker opens the user's file itself, and
        Windows refuses to replace a file another handle holds open, so a save
        that installs over the target (orphan fallback, secure save, watermark)
        failed with a sharing error caused by the app's own worker and left the
        session rebound to a temp copy (R7-2).  ``cancel`` alone only sets
        flags; the join makes the handle really gone before the model writes.
        A worker that does not stop in time is logged and the save proceeds:
        the model's install keeps the session alive on its recovery copy.

        A job the save interrupted is restarted afterwards (``resume_thumbnails``;
        a closing tab has no use for it) - whether or not the save succeeded.
        """
        coordinator = self._thumbnail_coordinator
        interrupted = bool(coordinator.has_active_job)
        coordinator.cancel()
        if not coordinator.wait_for_done(SAVE_READER_JOIN_TIMEOUT_MS):
            logger.warning("thumbnail worker still running at save time; saving anyway")
        try:
            yield
        finally:
            if interrupted and resume_thumbnails:
                sid = self.model.get_active_session_id()
                gen = self._thumb_gen_by_session.get(sid) if sid else None
                if sid and gen is not None:
                    self._schedule_thumbnail_batch(0, sid, gen)

    def _save_session_with_dialog(self, session_id: str) -> bool:
        meta = self.model.get_session_meta(session_id) or {}
        default_path = meta.get("saved_path") or meta.get("path") or "未命名.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self.view,
            "儲存PDF",
            str(default_path),
            "PDF (*.pdf)",
        )
        if not path:
            return False
        if self._is_lost(session_id):
            # No document to save: copy the recovery file (owner decision C).
            return self._save_lost_session_copy(session_id, path)
        try:
            with self._background_file_readers_released(
                resume_thumbnails=session_id != self.model.get_active_session_id()
            ):
                return self._save_with_signature_consent(
                    lambda **kw: self.model.save_session_as(session_id, path, **kw),
                    session_id,
                )
        except Exception as e:
            logger.error(f"儲存 session 失敗: {e}")
            self._report_save_failure("儲存失敗", e, session_id)
            return False

    def _attach_yes_no_shortcuts(self, msg_box: QMessageBox, yes_btn, no_btn) -> None:
        """讓確認對話框支援 Y/N 快捷鍵。"""
        shortcut_yes = QShortcut(QKeySequence("Y"), msg_box)
        shortcut_no = QShortcut(QKeySequence("N"), msg_box)
        shortcut_yes.setAutoRepeat(False)
        shortcut_no.setAutoRepeat(False)
        shortcut_yes.activated.connect(lambda: yes_btn.click() if yes_btn.isEnabled() else None)
        shortcut_no.activated.connect(lambda: no_btn.click() if no_btn.isEnabled() else None)
        # 保留引用，避免被 GC 回收後失效。
        msg_box._shortcut_yes = shortcut_yes
        msg_box._shortcut_no = shortcut_no

    def _confirm_close_lost_session(self, session_id: str) -> bool:
        """Close prompt of a lost tab: only Save As (copy the recovery file) and Discard.

        Both show the recovery path again; the recovery file itself is kept
        until the program exits (owner decision C).  True when the tab may close.
        """
        error = self.model.lost_session_error(session_id)
        meta = self.model.get_session_meta(session_id) or {}
        name = meta.get("display_name") or "未命名"
        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("分頁已中斷")
        msg_box.setText(f"分頁「{name}」已中斷，無法再儲存。")
        msg_box.setInformativeText(f"{error}\n\n取消將保留分頁不關閉。" if error else "取消將保留分頁不關閉。")
        save_btn = msg_box.addButton("另存暫存副本", QMessageBox.AcceptRole)
        discard_btn = msg_box.addButton("放棄並關閉", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == save_btn:
            return self._save_session_with_dialog(session_id)
        if clicked == discard_btn:
            # Discard keeps the recovery copy until the program exits (the model
            # removes its temp dir then): say where it is one last time.
            if error is not None:
                self._show_lost_discard_notice([(name, error)])
            return True
        return False

    def _lost_sessions_with_errors(self, session_ids) -> list[tuple[str, SaveRecoveryError]]:
        """``(display name, error)`` of every lost tab among ``session_ids``, in order."""
        out: list[tuple[str, SaveRecoveryError]] = []
        for sid in session_ids:
            error = self.model.lost_session_error(sid)
            if error is None:
                continue
            meta = self.model.get_session_meta(sid) or {}
            out.append((meta.get("display_name") or "未命名", error))
        return out

    def _show_lost_discard_notice(self, lost: list[tuple[str, SaveRecoveryError]]) -> None:
        """Say where the recovery copies of just-discarded lost tabs are (owner decision C).

        Every path that discards a lost tab (single-tab close, window close with
        Discard all) goes through here so none can drop the path silently
        (F15-DEADTAB-APPCLOSE).  The copies stay until the program exits."""
        if not lost:
            return
        if len(lost) == 1:
            text = f"已放棄此分頁。尚未儲存的編輯仍保留於暫存副本，結束程式後才會刪除：{lost[0][1].recovery_path}"
        else:
            lines = "\n".join(f"「{name}」：{error.recovery_path}" for name, error in lost)
            text = f"已放棄這些分頁。尚未儲存的編輯仍保留於暫存副本，結束程式後才會刪除：\n{lines}"
        QMessageBox.information(self.view, "暫存副本仍保留", text)

    def _confirm_close_session(self, session_id: str) -> bool:
        if self._is_lost(session_id):
            return self._confirm_close_lost_session(session_id)
        editor_input = self._inline_editor_has_unapplied_input(session_id)
        if not editor_input and not self.model.session_has_unsaved_changes(session_id):
            return True
        meta = self.model.get_session_meta(session_id) or {}
        name = meta.get("display_name") or "未命名"
        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        if editor_input:
            msg_box.setText(f"分頁「{name}」有尚未套用的文字編輯或未儲存的變更，是否要儲存？")
        else:
            msg_box.setText(f"分頁「{name}」有未儲存的變更，是否要儲存？")
        msg_box.setInformativeText("取消將保留分頁不關閉。快捷鍵：Y=儲存，N=放棄，Esc=取消。")
        save_btn = msg_box.addButton("儲存後關閉", QMessageBox.AcceptRole)
        discard_btn = msg_box.addButton("放棄變更", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
        self._attach_yes_no_shortcuts(msg_box, save_btn, discard_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            return False
        if clicked == save_btn:
            # The editor's verified edit commits now (after the answer); input
            # that cannot be applied keeps the editor and aborts the close.
            if not self._finalize_inline_editor_for_close(session_id, save=True):
                return False
            return self._save_session_with_dialog(session_id)
        self._finalize_inline_editor_for_close(session_id, save=False)
        return True

    def set_session_handoff_callback(self, callback) -> None:
        self._session_handoff_callback = callback

    def detach_document_session(self, session_id: str, global_pos: object) -> None:
        callback = self._session_handoff_callback
        if not callable(callback) or session_id not in self.model.session_ids:
            return
        if self._is_lost(session_id):
            # Nothing to hand over: the session has no document.
            show_error(self.view, "這個分頁已中斷，無法移到新視窗。請先另存暫存副本。")
            return
        # UI step 9: the active session is about to change (switch, or the
        # detached one is closed here) -- finalize against it first.
        self._finalize_inline_editor_before_session_change()
        if self.model.get_active_session_id() != session_id:
            self._switch_to_session_id(session_id)
        state = self._get_ui_state(session_id)
        payload = SessionTransferPayload.from_model(
            self.model,
            session_id,
            current_page=self.view.current_page,
            scale=self.view.scale,
            color_profile=state.color_profile,
        )
        try:
            ready = bool(callback(payload, global_pos))
        except Exception as exc:
            logger.error("Detached window creation failed: %s", exc)
            return
        if not ready:
            return
        self._thumbnail_coordinator.cancel(session_id)
        self._cancel_page_render_for_session(session_id)
        self.cancel_ocr()
        self._cancel_search()
        self.model.close_session(session_id)
        if self._worker_snapshot_cache and self._worker_snapshot_cache[0] == session_id:
            self._invalidate_worker_snapshot_cache()
        for mapping_name in (
            "_session_ui_state",
            "_fullscreen_session_snapshots",
            "_load_gen_by_session",
            "_thumb_gen_by_session",
            "_render_gen_by_session",
            "_render_revision_by_session",
            "_page_render_quality_by_session",
            "_page_sizes_by_session",
            "_desired_scroll_page",
            "_open_priority_page_by_session",
            "_background_loading_started_by_session",
            "_render_batch_pending_by_session",
        ):
            getattr(self, mapping_name, {}).pop(session_id, None)
        self._thumbnail_resume_pending_by_session.discard(session_id)
        self._refresh_document_tabs()
        active_sid = self.model.get_active_session_id()
        if active_sid:
            active_state = self._get_ui_state(active_sid)
            self._render_active_session(initial_page_idx=active_state.current_page)
        else:
            self._reset_empty_ui()

    def on_tab_close_requested(self, index: int):
        sid = self.model.get_session_id_by_index(index)
        if not sid:
            return
        # Finalize policy completion (defect 2): CONFIRM FIRST.  The prompt
        # counts the inline editor's un-applied input as unsaved and
        # finalizes the editor only after the answer (Cancel: nothing ran --
        # tab, editor, input and PDF untouched; no token committed early).
        if not self._confirm_close_session(sid):
            return
        active_before_close = self.model.get_active_session_id()
        if sid == active_before_close:
            # UI step 9: closing the active document is a session change
            # (by now the editor is gone unless it held no input; this also
            # ends the preview session).
            self._finalize_inline_editor_before_session_change()
        # Cancel in-flight background readers before closing the doc.
        self._thumbnail_coordinator.cancel(sid)
        self._cancel_page_render_for_session(sid)
        self.cancel_ocr()
        self._cancel_search()
        if sid == self.model.get_active_session_id():
            self._capture_current_ui_state()
        self.model.close_session(sid)
        # R4-03 fix: release the departing session's decrypted worker-snapshot bytes.
        # The cache holds a full doc.tobytes() (plaintext for an encrypted doc); leaving
        # it after the session is gone keeps decrypted content alive in memory. Guarded by
        # session id so other tabs' cached snapshots survive.
        if self._worker_snapshot_cache and self._worker_snapshot_cache[0] == sid:
            self._invalidate_worker_snapshot_cache()
        self._session_ui_state.pop(sid, None)
        self._fullscreen_session_snapshots.pop(sid, None)
        self._load_gen_by_session.pop(sid, None)
        self._thumb_gen_by_session.pop(sid, None)
        getattr(self, "_render_gen_by_session", {}).pop(sid, None)
        getattr(self, "_render_revision_by_session", {}).pop(sid, None)
        getattr(self, "_page_render_quality_by_session", {}).pop(sid, None)
        getattr(self, "_page_sizes_by_session", {}).pop(sid, None)
        getattr(self, "_thumbnail_resume_pending_by_session", set()).discard(sid)
        self._desired_scroll_page.pop(sid, None)
        self._open_priority_page_by_session.pop(sid, None)
        self._background_loading_started_by_session.pop(sid, None)
        self._render_batch_pending_by_session.pop(sid, None)
        self._refresh_document_tabs()
        active_sid = self.model.get_active_session_id()
        if active_sid and active_sid == active_before_close:
            # Finalize policy completion: a NON-active tab closed -- the
            # active document and its scene are unchanged, so only the tab
            # bar is refreshed.  Re-rendering would rebuild the scene and end
            # the active inline editor (commit or discard) as a side effect
            # of an action aimed at another document.
            return
        if active_sid:
            state = self._get_ui_state(active_sid)
            self._render_active_session(initial_page_idx=state.current_page)
        else:
            self._reset_empty_ui()

    def request_metadata_editor(self) -> None:
        if not self.model.doc:
            return
        self.view.show_metadata_editor(self.model.get_editable_metadata())

    def update_document_metadata(self, values: object) -> None:
        if not self.model.doc:
            return
        before = self.model._capture_doc_snapshot()
        try:
            changed = self.model.set_editable_metadata(values)
        except (TypeError, ValueError) as exc:
            show_error(self.view, f"文件資訊無效：{exc}")
            return
        if not changed:
            return
        self._invalidate_worker_snapshot_cache()
        after = self.model._capture_doc_snapshot()
        page = min(max(1, self.view.current_page + 1), len(self.model.doc))
        self.model.command_manager.record(
            SnapshotCommand(
                model=self.model,
                command_type="update_metadata",
                affected_pages=[page],
                before_bytes=before,
                after_bytes=after,
                description="更新文件資訊",
            )
        )
        self._update_undo_redo_tooltips()

    def save_as(self, path: str):
        if self._is_lost():
            # The document is gone: Save As copies the recovery file (owner decision C).
            self._save_lost_session_copy(self.model.get_active_session_id(), path)
            return
        try:
            try:
                with self._background_file_readers_released(resume_thumbnails=True):
                    saved = self._save_with_signature_consent(
                        lambda **kw: self.model.save_as(path, **kw)
                    )
            finally:
                # Part 5 stage B: saving cleans unprotected pages with queued
                # maintenance, so an editor kept open across it previews a
                # stale snapshot until its session is re-opened.  Also when the
                # save FAILS: ``apply_pending_redactions`` may already have
                # rewritten pages before a later step raised.
                self._invalidate_inline_editor_preview()
            if not saved:
                return  # the user kept the signature: nothing was written
            self._refresh_document_tabs()
            self._update_undo_redo_tooltips()
        except Exception as e:
            logger.error(f"另存失敗: {e}")
            self._report_save_failure("另存失敗", e)

    def save(self):
        """存回原檔（Ctrl+S）。若有原檔或上次儲存路徑則直接儲存（適用時使用增量更新）；否則改開另存對話框。"""
        path = self.model.saved_path or self.model.original_path
        if not path:
            # 無路徑時改為另存，讓使用者選路徑
            self.view._save_as()
            return
        try:
            try:
                with self._background_file_readers_released(resume_thumbnails=True):
                    saved = self._save_with_signature_consent(
                        lambda **kw: self.model.save_as(path, **kw)
                    )
            finally:
                self._invalidate_inline_editor_preview()  # see save_as
            if not saved:
                return  # the user kept the signature: nothing was written
            self._refresh_document_tabs()
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "儲存完成", f"已儲存至：{path}")
        except Exception as e:
            logger.error(f"儲存失敗: {e}")
            self._report_save_failure("儲存失敗", e)

    def _save_with_signature_consent(
        self, save: Callable[..., None], session_id: str | None = None
    ) -> bool:
        """Run ``save()``; ask before it invalidates a digital signature (SIG-DIALOG).

        The model refuses a save that could only be a full rewrite of a signed
        document (``SignatureWouldBreakError``) before writing anything.  The
        user is asked; on consent the save runs again with
        ``allow_signature_loss=True``.  Returns ``False`` when the user kept the
        signature (nothing written, the session stays dirty), ``True`` when
        saved.  Any other error, also from the retry, propagates to the caller.

        ``session_id`` is the session being saved (``None``: the active one).
        The dialog names that document: during a Save All / per-tab close it is
        usually NOT the visible tab, and File > Save As acts on the active tab
        (F12-DLG-1).
        """
        try:
            save()
            return True
        except SignatureWouldBreakError as exc:
            logger.warning("簽署文件無法以附加方式儲存，詢問使用者: %s", exc)
            if not self._confirm_signature_loss(exc, session_id):
                logger.info("使用者取消儲存以保留數位簽章: %s", exc.path)
                return False
        save(allow_signature_loss=True)
        return True

    _SIGNATURE_LOSS_REASON_TEXT: dict[str, str] = {
        "secure_latch": "本次的編輯（例如刪除頁面或物件、修改書籤或文件資訊）必須完整重寫檔案，以清除舊內容。",
        "incremental_disabled": "附加（增量）儲存已關閉，只能完整重寫檔案。",
        "in_place_append_unavailable": "此檔案目前無法以附加方式儲存（檔案可能經過修復）。",
        "repaired_source": "原始檔案的結構經過修復，無法以附加方式儲存。",
        "source_missing": "找不到原本已簽署的檔案，無法以附加方式保留簽章。",
        "source_changed": "原本已簽署的檔案已被其他程式變更，無法以附加方式保留簽章。",
        "watermark_rewrite": "加入浮水印必須完整重寫檔案。",
        "incremental_failed": "以附加方式儲存失敗。",
        "encryption_mismatch": "此文件的加密設定無法以附加方式保留。",
        "catalog_mismatch": "文件結構已改變，無法以附加方式儲存。",
        "object_limit": "文件的物件數量超出附加儲存的上限。",
        "verify_failed": "附加儲存的結果未通過驗證。",
        "append_error": "附加儲存時發生錯誤。",
    }

    @classmethod
    def _signature_loss_texts(
        cls,
        exc: SignatureWouldBreakError,
        document_name: str | None = None,
        other_tab: bool = False,
    ) -> tuple[str, str]:
        """The dialog's main and informative text: one plain zh-TW line per reason
        (the reason code itself goes to the log only).

        ``document_name`` names the signed document (a save-all close asks while
        another tab is visible); ``other_tab`` says it is not the active tab, so
        the Save As advice first sends the user to that tab (F12-DLG-1)."""
        reason = cls._SIGNATURE_LOSS_REASON_TEXT.get(exc.reason_code, "無法以附加方式儲存。")
        subject = f"文件「{document_name}」" if document_name else "此文件"
        text = (
            f"{subject}含有數位簽章。若繼續儲存，簽章將失效（無法再通過驗證）。\n"
            f"原因：{reason}"
        )
        switch = f"切換到「{document_name}」分頁，" if document_name and other_tab else ""
        informative = f"如要保留原本已簽署的檔案，請按「取消」，{switch}再改用「另存新檔」儲存成另一個檔名。"
        return text, informative

    def _signature_document_name(self, session_id: str | None) -> tuple[str | None, bool]:
        """``(display name, is a tab other than the active one)`` of the session
        whose save asks about its signature; ``(None, False)`` when unknown."""
        active = self.model.get_active_session_id()
        sid = session_id or active
        meta = (self.model.get_session_meta(sid) if sid else None) or {}
        name = meta.get("display_name") or None
        return name, bool(sid and active and sid != active)

    def _confirm_signature_loss(
        self, exc: SignatureWouldBreakError, session_id: str | None = None
    ) -> bool:
        """``True`` when the user chose to save anyway (the signature will be invalid)."""
        name, other_tab = self._signature_document_name(session_id)
        text, informative = self._signature_loss_texts(exc, name, other_tab)
        return confirm_signature_loss(self.view, text, informative)

    @staticmethod
    def _save_failure_text(prefix: str, exc: Exception) -> str:
        """Modal text for a failed save.

        A ``SaveRecoveryError`` is not a retryable failure (the session lost its
        document; the message says whether the file was written and where the
        unsaved edits were kept), so it is shown as written, without the
        generic prefix that would read like an ordinary failed save.
        """
        if isinstance(exc, (SaveRecoveryError, SourceChangedOnDiskError, DamagedSessionSaveError)):
            # SourceChangedOnDiskError: the save was refused, nothing written;
            # the message says why and that Save As is the way out (F10-FS-1).
            # DamagedSessionSaveError: same, for a session whose failed edit
            # could not be rolled back (S13-DLG5-DAMAGED).
            return str(exc)
        return f"{prefix}: {exc}"

    def _render_print_preview_image(self, page_index: int, dpi: int) -> QImage:
        scale = max(1.0, float(dpi) / 72.0)
        session_id = self.model.get_active_session_id()
        pix = self.model.get_page_snapshot(
            page_index + 1,
            scale=scale,
            colorspace=(self._fitz_colorspace_for_session(session_id) if session_id else fitz.csRGB),
        )
        return pixmap_to_qimage(pix)

    def _has_active_print_submission(self) -> bool:
        """Facade: True while a print submission thread or runner is in flight."""
        return self._print_coordinator.has_active_job()

    def print_document(self):
        """Facade: delegate the print flow (dialog + submission) to the PrintCoordinator."""
        return self._print_coordinator.print_document()

    def delete_pages(self, pages: list[int]):
        self._cancel_search()
        before = self.model._capture_doc_snapshot()
        before_placeholder_active = self.model.blank_placeholder_active
        # Model is the source of truth: it sanitizes dirty input and returns the actual deleted pages.
        actual_deleted_pages = self.model.delete_pages(pages)
        if not actual_deleted_pages:
            return
        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        after_placeholder_active = self.model.blank_placeholder_active
        cmd = SnapshotCommand(
            model=self.model,
            command_type="delete_pages",
            # SnapshotCommand metadata must reflect the real effect, not the user's requested intent.
            affected_pages=actual_deleted_pages,
            before_bytes=before,
            after_bytes=after,
            description=f"刪除頁面 {actual_deleted_pages}",
            before_placeholder_active=before_placeholder_active,
            after_placeholder_active=after_placeholder_active,
        )
        self.model.command_manager.record(cmd)
        self._invalidate_thumbnails(actual_deleted_pages)
        self._rebuild_continuous_scene(min(self.view.current_page, len(self.model.doc) - 1))
        self._schedule_stale_index_drain()
        self._update_undo_redo_tooltips()

    def reorder_page(self, source_index: int, destination_index: int) -> None:
        """Move a thumbnail-selected page and refresh only its changed interval."""
        self._cancel_search()
        before = self.model._capture_doc_snapshot()
        affected_pages = self.model.move_page(source_index, destination_index)
        if not affected_pages:
            return

        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        command = SnapshotCommand(
            model=self.model,
            command_type="move_page",
            affected_pages=affected_pages,
            before_bytes=before,
            after_bytes=after,
            description=f"移動頁面 {source_index + 1} 到位置 {destination_index + 1}",
            # A move can span a long document. Snapshot restore keeps only the
            # destination hot; the rest is rebuilt lazily like other structural ops.
            index_pages=[destination_index + 1],
        )
        self.model.command_manager.record(command)
        renumber = getattr(self.view, "renumber_thumbnail_labels", None)
        if callable(renumber):
            renumber(affected_pages[0] - 1, affected_pages[-1] - 1)
        self._invalidate_thumbnails(affected_pages)
        self._rebuild_continuous_scene(destination_index)
        self._schedule_stale_index_drain()
        self._update_undo_redo_tooltips()

    def rotate_pages(self, pages: list[int], degrees: int):
        self._cancel_search()
        before = self.model._capture_doc_snapshot()
        # Model sanitizes and returns the actual rotated pages for metadata correctness.
        actual_rotated_pages = self.model.rotate_pages(pages, degrees)
        if not actual_rotated_pages:
            return
        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="rotate_pages",
            affected_pages=actual_rotated_pages,
            before_bytes=before,
            after_bytes=after,
            description=f"旋轉頁面 {actual_rotated_pages} {degrees}°",
        )
        self.model.command_manager.record(cmd)
        self._invalidate_thumbnails(actual_rotated_pages)
        self._rebuild_continuous_scene(self.view.current_page)
        self._update_undo_redo_tooltips()

    def straighten_pages(self, pages: list[int], angle_degrees: float | None = None) -> None:
        if not self.model.doc:
            return
        self._cancel_search()
        page_count = len(self.model.doc)
        targets = sorted({int(p) for p in pages if 1 <= int(p) <= page_count})
        if not targets:
            return
        before = self.model._capture_doc_snapshot()
        straightened: list[int] = []
        try:
            for page_num in targets:
                if self.model.straighten_page(page_num, angle_degrees=angle_degrees):
                    straightened.append(page_num)
        except Exception as exc:
            show_error(self.view, f"拉正頁面失敗：{exc}")
            return
        if not straightened:
            return
        self._invalidate_active_render_state(clear_page_sizes=True)
        after = self.model._capture_doc_snapshot()
        description = (
            f"拉正頁面 {straightened[0]}"
            if len(straightened) == 1
            else f"拉正 {len(straightened)} 頁"
        )
        cmd = SnapshotCommand(
            model=self.model,
            command_type="straighten_pages",
            affected_pages=straightened,
            before_bytes=before,
            after_bytes=after,
            description=description,
        )
        self.model.command_manager.record(cmd)
        self._invalidate_thumbnails(straightened)
        self._rebuild_continuous_scene(self.view.current_page)
        self._update_undo_redo_tooltips()

    def export_pages(self, pages: list[int], path: str, as_image: bool, dpi: int, image_format: str):
        self.model.export_pages(pages, path, as_image=as_image, dpi=dpi, image_format=image_format)

    def add_highlight(self, page: int, rect: fitz.Rect, color: tuple[float, float, float, float]):
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_highlight(page, rect, color)
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_highlight",
            affected_pages=[page],
            before_bytes=before,
            after_bytes=after,
            description=f"新增螢光筆（頁面 {page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(page - 1)
        self._update_undo_redo_tooltips()

    def _add_text_markup(
        self,
        kind: str,
        page: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        before = self.model._capture_doc_snapshot()
        if kind == "underline":
            self.model.tools.annotation.add_underline(page, rect, color)
            description = f"新增底線（頁面 {page}）"
        elif kind == "strikeout":
            self.model.tools.annotation.add_strikeout(page, rect, color)
            description = f"新增刪除線（頁面 {page}）"
        else:  # pragma: no cover - public wrappers use fixed literals
            raise ValueError(f"unsupported markup kind: {kind}")
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        self.model.command_manager.record(
            SnapshotCommand(
                model=self.model,
                command_type=f"add_{kind}",
                affected_pages=[page],
                before_bytes=before,
                after_bytes=after,
                description=description,
            )
        )
        self.show_page(page - 1)
        self._update_undo_redo_tooltips()

    def add_underline(
        self,
        page: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("underline", page, rect, color)

    def add_strikeout(
        self,
        page: int,
        rect: fitz.Rect,
        color: tuple[float, float, float, float],
    ) -> None:
        self._add_text_markup("strikeout", page, rect, color)

    def get_text_bounds(self, page: int, rough_rect: fitz.Rect) -> fitz.Rect:
        return self.model.tools.annotation.get_text_bounds(page, rough_rect)

    def get_object_info_at_point(self, page: int, point: fitz.Point):
        return self.model.get_object_info_at_point(page, point)

    def add_rect(
        self,
        page: int,
        rect: fitz.Rect,
        stroke_color: tuple[float, float, float, float],
        fill_color: tuple[float, float, float, float] | None,
        border_width: float,
    ) -> None:
        before = self.model._capture_doc_snapshot()
        self.model.tools.annotation.add_rect(
            page,
            rect,
            stroke_color=stroke_color,
            fill_color=fill_color,
            border_width=border_width,
        )
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_rect",
            affected_pages=[page],
            before_bytes=before,
            after_bytes=after,
            description=f"新增矩形（頁面 {page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(page - 1)
        self._update_undo_redo_tooltips()

    def _object_refusal(self, object_kind: str | None, object_id: str | None) -> ObjectOpRefused:
        """The refusal the Model JUST recorded for a False object op (read right after
        the call: it is overwritten by the next one), with this object's kind and id
        when the Model named none."""
        refusal = getattr(self.model, "last_object_op_refusal", None)
        if not isinstance(refusal, ObjectOpRefused):
            return ObjectOpRefused(ObjectOpRefusal.OPERATION_FAILED, object_kind, object_id)
        if refusal.object_kind is None:
            return ObjectOpRefused(refusal.reason, object_kind, object_id)
        return refusal

    def _show_object_refusal(self, message: str, refusals: list[ObjectOpRefused]) -> None:
        """D-OLD-MARKERS: a refused object op is never silent -- ONE plain zh-TW
        dialog (the codes go to the log only)."""
        for refusal in refusals:
            logger.info(
                "object op refused: kind=%s id=%s reason=%s",
                refusal.object_kind,
                refusal.object_id,
                refusal.reason.value,
            )
        show_error(self.view, message)

    def _tell_view_object_op_refused(self, object_ids: list[str]) -> None:
        """D-OBJ-FRAME: tell the View which objects a move / resize / rotate left
        unchanged, so its selection frame stays on them.  The request signal returns
        nothing, so without this the View would follow its own request."""
        notify = getattr(self.view, "note_object_op_refused", None)
        if not callable(notify):
            return
        try:
            notify([str(object_id) for object_id in object_ids])
        except Exception:
            logger.debug("object refusal notice to the view failed", exc_info=True)

    def _report_object_refusal(self, verb: str, object_kind: str, object_id: str) -> None:
        self._tell_view_object_op_refused([object_id])
        refusal = self._object_refusal(object_kind, object_id)
        self._show_object_refusal(object_refusal_message(verb, refusal), [refusal])

    def move_object(self, request: MoveObjectRequest) -> None:
        if isinstance(request, BatchMoveObjectsRequest):
            before = self.model._capture_doc_snapshot()
            affected_pages: list[int] = []
            refused: list[ObjectOpRefused] = []
            changed = False
            for move in request.moves:
                if self.model.move_object(move):
                    changed = True
                    affected_pages.append(int(move.destination_page))
                else:
                    refused.append(self._object_refusal(move.object_kind, move.object_id))
                    self._tell_view_object_op_refused([move.object_id])
            if not changed:
                if refused:
                    self._report_batch_move_refusals(len(request.moves), refused)
                return
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            pages = sorted(set(affected_pages))
            cmd = SnapshotCommand(
                model=self.model,
                command_type="move_object_batch",
                affected_pages=pages,
                before_bytes=before,
                after_bytes=after,
                description=f"Move objects (pages {pages})",
            )
            self.model.command_manager.record(cmd)
            self.show_page(pages[-1] - 1)
            self._update_undo_redo_tooltips()
            if refused:
                self._report_batch_move_refusals(len(request.moves), refused)
            return
        before = self.model._capture_doc_snapshot()
        if not self.model.move_object(request):
            self._report_object_refusal("move", request.object_kind, request.object_id)
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="move_object",
            affected_pages=[request.destination_page],
            before_bytes=before,
            after_bytes=after,
            description=f"移動物件（頁面 {request.destination_page}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.destination_page - 1)
        self._update_undo_redo_tooltips()

    def _report_batch_move_refusals(self, total: int, refused: list[ObjectOpRefused]) -> None:
        if total == 1:
            self._show_object_refusal(object_refusal_message("move", refused[0]), refused)
            return
        self._show_object_refusal(batch_refusal_message("move", total, refused), refused)

    def rotate_object(self, request: RotateObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        if not self.model.rotate_object(request):
            self._report_object_refusal("rotate", request.object_kind, request.object_id)
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="rotate_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"旋轉物件（頁面 {request.page_num}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def delete_object(self, request: DeleteObjectRequest) -> None:
        if isinstance(request, BatchDeleteObjectsRequest):
            before = self.model._capture_doc_snapshot()
            deletes = [
                DeleteObjectRequest(
                    object_id=ref.object_id,
                    object_kind=ref.object_kind,
                    page_num=ref.page_num,
                )
                for ref in request.objects
            ]
            if not self.model.delete_objects_atomic(deletes):
                # A partial batch that rolled back reopened model.doc from the snapshot, so
                # any cached page/render state now points at a closed document. (A pure
                # no-op leaves the handle alone, but invalidating twice is harmless.)
                self._invalidate_active_render_state()
                refusal = self._object_refusal(
                    deletes[0].object_kind if len(deletes) == 1 else None, None
                )
                message = (
                    object_refusal_message("delete", refusal)
                    if len(deletes) == 1
                    else atomic_delete_refusal_message(len(deletes), refusal)
                )
                self._show_object_refusal(message, [refusal])
                return
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            pages = sorted({int(item.page_num) for item in deletes})
            cmd = SnapshotCommand(
                model=self.model,
                command_type="delete_object_batch",
                affected_pages=pages,
                before_bytes=before,
                after_bytes=after,
                description=f"Delete objects (pages {pages})",
            )
            self.model.command_manager.record(cmd)
            self.show_page(pages[-1] - 1)
            self._update_undo_redo_tooltips()
            return
        before = self.model._capture_doc_snapshot()
        if not self.model.delete_object(request):
            self._invalidate_active_render_state()
            self._report_object_refusal("delete", request.object_kind, request.object_id)
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="delete_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"刪除物件（頁面 {request.page_num}）",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def resize_object(self, request: ResizeObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        if not self.model.resize_object(request):
            self._report_object_refusal("resize", request.object_kind, request.object_id)
            return
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="resize_object",
            affected_pages=[request.page_num],
            before_bytes=before,
            after_bytes=after,
            description=f"Resize object (page {request.page_num})",
        )
        self.model.command_manager.record(cmd)
        self.show_page(request.page_num - 1)
        self._update_undo_redo_tooltips()

    def add_image_object(self, request: InsertImageObjectRequest) -> None:
        before = self.model._capture_doc_snapshot()
        self.model.add_image_object(
            int(request.page_num),
            fitz.Rect(request.visual_rect),
            bytes(request.image_bytes),
            rotation=int(getattr(request, "rotation", 0) or 0),
        )
        self._invalidate_active_render_state()
        # Drop any stale object selection so lingering resize handles in the scene
        # don't intercept the user's first click on the freshly-inserted image.
        self._drop_object_selection()
        after = self.model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=self.model,
            command_type="add_image_object",
            affected_pages=[int(request.page_num)],
            before_bytes=before,
            after_bytes=after,
            description=f"Add image object (page {int(request.page_num)})",
        )
        self.model.command_manager.record(cmd)
        self.show_page(int(request.page_num) - 1)
        self._update_undo_redo_tooltips()

    def _edit_result_to_message(
        self, result: EditTextResult, reason: str | None = None
    ) -> str | None:
        if result is EditTextResult.TARGET_BLOCK_NOT_FOUND:
            return "找不到可編輯的文字區塊"
        if result is EditTextResult.TARGET_SPAN_NOT_FOUND:
            return "找不到要編輯的文字內容"
        if result is EditTextResult.TARGET_SOURCE_MISMATCH:
            return "選取的文字來源已變更，請重新點選要編輯的文字（文件未變更）"
        if result is EditTextResult.REJECTED_STRICT:
            return "嚴格模式：此編輯不符合高保真條件，已拒絕（文件未變更）"
        if result is EditTextResult.REJECTED_UNSUPPORTED:
            # Task 16 T16-3 review round: the signed/widget-page hard reject
            # (model/pdf_model.py) became reachable for real users when the
            # tiered engine became the default. It is deliberately zero
            # mutation -- but until this branch existed the edit was also
            # zero *feedback*: _show_edit_result_feedback early-returns on a
            # falsy message, so the user typed, clicked away, and nothing
            # happened and nothing was said.
            # Review round 2: the /SigFlags half of that boundary was
            # narrowed to "a signature field that is actually signed", so
            # the first two clauses are true again; the third covers the
            # fail-closed refusal when the form data cannot be read at all.
            return (
                "此頁含表單欄位、文件已簽章或表單資訊無法判讀，"
                "為避免破壞內容已拒絕編輯（文件未變更）"
            )
        if result is EditTextResult.STALE_UNDO:
            # Task 16 T16-3 review round 2: Tier 0 patch-replay undo became
            # live with the default flip. A later legacy commit on the same
            # page rewrites the content stream, so an earlier Tier 0
            # command's retained inverse patch goes fingerprint-stale and
            # undo refuses with zero mutation -- and said nothing at all.
            return "無法復原此步驟：該頁在這次編輯之後已被改寫（文件未變更）"
        if result is EditTextResult.STALE_PLAN:
            # The redo twin of the same refusal (edit_commands._redo_tier0).
            return "無法重做此步驟：該頁內容已與當時不同（文件未變更）"
        if result is EditTextResult.FALLBACK_DECLINED:
            # P0-C phase 2: the user declining the consent prompt is not an
            # error (zero mutation happened as requested) -- no error toast.
            return None
        if result is EditTextResult.PREVIEW_PENDING:
            # UI step 5: the inline Apply waits for a verified preview.
            return "預覽仍在更新，請待預覽完成後再套用（文件未變更）"
        if result is EditTextResult.PREVIEW_STALE:
            # UI step 5: the verified preview no longer matches the page.
            return "預覽已過期（文字或頁面已變更），請待新的預覽完成後再套用（文件未變更）"
        if result is EditTextResult.REJECTED:
            # UI step 7: the tiered refusal is final without the explicit
            # rebuild consent.  UI step 10: the same plain text the kept
            # editor shows (view/text_edit_reasons.py; an unmapped code gets
            # a generic sentence plus the code).  Never document content.
            text = rejection_reason_text(reason or "unknown")
            return f"{text}，未套用（文件未變更）"
        return None

    # UI step 5: refusals that are not errors -- zero mutation, and the user
    # only has to wait for (or refresh) the preview. A toast, never a modal.
    # UI step 7: a no-consent refusal (REJECTED) is the same kind of notice.
    _PREVIEW_NOTICE_RESULTS = frozenset(
        {
            EditTextResult.PREVIEW_PENDING,
            EditTextResult.PREVIEW_STALE,
            EditTextResult.REJECTED,
        }
    )

    def _last_refusal_reason(self) -> str | None:
        """The reason code of the refusal the Model JUST recorded (read right
        after the attempt, never later: it is overwritten per edit)."""
        outcome = getattr(self.model, "last_commit_outcome", None)
        reason = getattr(outcome, "degraded_reason", None)
        return str(reason) if reason else None

    def _show_edit_result_feedback(
        self, result: EditTextResult, reason: str | None = None
    ) -> None:
        message = self._edit_result_to_message(result, reason)
        if not message:
            return
        if result in self._PREVIEW_NOTICE_RESULTS:
            self._show_notice_feedback(message)
            return
        self._show_error_feedback(message)

    def _show_notice_feedback(self, message: str) -> None:
        toast = getattr(self.view, "_show_toast", None)
        if callable(toast):
            toast(message, duration_ms=2500, tone="warning")
            return
        logger.info("edit notice (no toast surface): %s", message)

    def _show_error_feedback(self, message: str) -> None:
        if hasattr(self.view, "_show_toast"):
            self.view._show_toast(message, duration_ms=2500, tone="error")
            return
        show_error(self.view, message)

    # A refused undo/redo that carries no mapped result must still speak:
    # routing it through _edit_result_to_message alone would re-create the
    # very silence this branch exists to remove (that helper returns None
    # for anything it does not know, and the feedback path early-returns on
    # a falsy message).
    _UNDO_REFUSED_FALLBACK = "無法復原此步驟（文件未變更）"
    _REDO_REFUSED_FALLBACK = "無法重做此步驟（文件未變更）"

    def _show_command_refusal_feedback(self, cmd, fallback: str) -> None:
        """Task 16 T16-3 review round 2: ``CommandManager.undo()/redo()``
        return ``False`` when the command itself refuses (``STALE_UNDO`` /
        ``STALE_PLAN``: zero mutation, command deliberately retained on its
        stack). The Controller used to discard that bool, so the button
        stayed lit and nothing moved and nothing was said."""
        result = getattr(cmd, "result", None)
        message = self._edit_result_to_message(result) if result is not None else None
        self._show_error_feedback(message or fallback)

    @staticmethod
    def _is_notifiable_degrade(outcome: CommitOutcome | None) -> bool:
        """A degrade notice fires only when a HIGHER-fidelity attempt fell
        back — chain like ``("tier0:<reason>", "legacy")``.

        Under the kill switch (``engine="legacy"``) every successful edit
        is honestly recorded as DEGRADED_COMMITTED with chain ``("legacy",)``;
        that is the legacy engine's baseline behavior, not a failed fidelity
        promise, so it is deliberately NOT routed here -- Task 16 T16-1 gives
        it its own ``_is_legacy_baseline_degrade`` branch and message. Since
        Task 16 the default engine is ``"tiered"``, so real fallbacks are the
        ones this gate surfaces.
        Delegates to the Model-layer ``is_real_fallback_commit`` shared with
        ``EditTextCommand``'s redo-reprompt gate (Task 12 P0-C phase 2
        verification) so the two "is this outcome a real fallback" checks
        can never drift apart."""
        return is_real_fallback_commit(outcome)

    @staticmethod
    def _is_legacy_baseline_degrade(outcome: CommitOutcome | None) -> bool:
        """Task 16 T16-1: ADDITIVE to ``_is_notifiable_degrade`` — a legacy
        redact+reinsert commit (chain == ``("legacy",)``, the shipped
        baseline under ``engine="legacy"``) is intentionally excluded by
        ``is_real_fallback_commit`` because that function also gates
        ``EditTextCommand``'s redo-reprompt (``model/edit_commands.py:357``,
        dto.py:258 comment) — DO NOT touch ``is_real_fallback_commit`` to
        surface this case.

        Mutually exclusive with ``_is_notifiable_degrade``: a genuine
        fallback chain (e.g. ``("tier0:...", "legacy")``) is handled there,
        never here, so exactly one degrade channel ever fires per commit."""
        return (
            outcome is not None
            and outcome.status is CommitStatus.DEGRADED_COMMITTED
            and outcome.degraded_reason == "legacy_redact_reinsert"
        )

    def _degraded_commit_message(self, outcome: CommitOutcome) -> str:
        """User-facing degrade notice. Reason codes ONLY — the payload must
        never carry document text, replacement text, filenames, or paths
        (Task 12 P0-C privacy contract)."""
        reason = fallback_chain_reason_text(outcome.fallback_chain) or FALLBACK_NO_REASON_TEXT
        return f"已以降級模式完成編輯（可能未保留原字型或相鄰版面）：{reason}，已改用 legacy 重建"

    @staticmethod
    def _legacy_baseline_degrade_message(outcome: CommitOutcome) -> str:
        """Task 16 T16-1 notice for a legacy redact+reinsert commit. Names
        the legacy engine and states that fidelity (bold, structure) is
        untracked — reason codes only, same privacy contract as
        ``_degraded_commit_message`` (no document text, filenames, or
        paths)."""
        del outcome  # reason codes only; nothing document-derived to read
        return (
            "已以 legacy 引擎完成編輯：粗體、斜體與版面結構等保真資訊未被追蹤"
            "（可能未保留原字型或相鄰版面）。"
        )

    def _dispatch_degrade_notice(self, message: str) -> None:
        """Push one degrade-notice ``message`` onto exactly ONE view
        channel. Preference order: the dedicated View API, then a warning
        toast, then the status bar — never more than one of them per edit.
        Shared by ``_notify_degraded_commit`` (real fallback) and
        ``_notify_legacy_baseline_degrade`` (Task 16 T16-1 legacy baseline)
        so both dispatch through the identical channel."""
        view = getattr(self, "view", None)
        if view is None:
            return
        if hasattr(view, "notify_degraded_commit"):
            view.notify_degraded_commit(message)
            return
        if hasattr(view, "_show_toast"):
            view._show_toast(message, duration_ms=5000, tone="warning")
            return
        if hasattr(view, "set_status_bar_override_message"):
            view.set_status_bar_override_message(message)

    def _notify_degraded_commit(self, outcome: CommitOutcome) -> None:
        """Surface a real-fallback DEGRADED_COMMITTED outcome (chain !=
        ``("legacy",)``) via ``_dispatch_degrade_notice``."""
        message = self._degraded_commit_message(outcome)
        logger.info(
            "text_commit_degraded_notice chain=%s",
            "→".join(outcome.fallback_chain),
        )
        self._dispatch_degrade_notice(message)

    def _notify_legacy_baseline_degrade(self, outcome: CommitOutcome) -> None:
        """Task 16 T16-1: surface a legacy redact+reinsert commit (the
        legacy engine's own baseline, chain == ``("legacy",)``) via the
        same ``_dispatch_degrade_notice`` channel used for real fallbacks."""
        message = self._legacy_baseline_degrade_message(outcome)
        logger.info(
            "text_commit_degraded_notice chain=%s",
            "→".join(outcome.fallback_chain),
        )
        self._dispatch_degrade_notice(message)

    def consume_last_edit_degraded(self) -> bool:
        """Pull-and-clear whether the last edit committed degraded.

        Called by the View's finalize path to decide if the plain success
        toast may be shown; consuming clears the flag so one degraded edit
        can suppress at most one success toast."""
        was_degraded = self._last_edit_degraded
        self._last_edit_degraded = False
        return was_degraded

    def consume_last_edit_result(self) -> EditTextResult | None:
        """Pull-and-clear the actual EditTextResult of the last
        commit-producing operation (Task 12 P0-C phase 2 verification).

        Called by the View's finalize path so the mode-switch success toast
        can never fire for a non-SUCCESS outcome. ``TextEditFinalizeResult.
        outcome == COMMITTED`` only means the finalize signal emitted
        without raising -- it does not reflect what the Controller actually
        did. ``None`` means no commit-producing operation has happened
        since the last consume (or the value was already consumed):
        callers must treat that the same as "not SUCCESS", never as
        "assume success"."""
        result = self._last_edit_result
        self._last_edit_result = None
        return result

    def consume_last_edit_refusal_reason(self) -> str | None:
        """UI step 10: pull-and-clear the reason code of the last edit the
        Controller REFUSED (``EditTextResult.REJECTED``).  The View's
        finalize path reads it right after ``consume_last_edit_result()`` to
        show the reason in the kept editor and offer "改用重建文字…".
        ``None`` for any other outcome."""
        reason = self._last_edit_refusal_reason
        self._last_edit_refusal_reason = None
        return reason

    def _record_edit_refusal(self, reason: str | None) -> None:
        """Record and announce a REJECTED edit with its reason code.  Every
        REJECTED path goes through here, so the View can always pull it."""
        self._last_edit_result = EditTextResult.REJECTED
        self._last_edit_refusal_reason = reason
        self._show_edit_result_feedback(EditTextResult.REJECTED, reason=reason)

    def _fallback_confirmation_message(
        self,
        chain: tuple[str, ...],
        glyph_loss: tuple[UnkeepableGlyph, ...] = (),
    ) -> str:
        """Pre-commit consent prompt. Reason codes ONLY -- same privacy
        contract as _degraded_commit_message (Task 12 P0-C).  With
        ``glyph_loss`` (F11-UNI-1 decision C) one more line says how many
        untouched symbols the rebuild cannot keep -- counts only, never the
        code points or the text."""
        reason_text = fallback_chain_reason_text(chain) or FALLBACK_NO_REASON_TEXT
        # UI step 10: asked only from "改用重建文字…" (or a consented move);
        # it says what the rebuild does to the page.  Codes only, still.
        glyph_line = self._glyph_loss_line(glyph_loss)
        return (
            "改用重建文字會刪除原文字，再以可用的字型重新寫入："
            "字型、字距或相鄰排版可能改變（降級提交）。\n"
            f"原因：{reason_text}\n"
            + (f"{glyph_line}\n" if glyph_line else "")
            + "\n是否繼續？（選「否」會保留編輯框與輸入）"
        )

    @staticmethod
    def _glyph_loss_line(glyph_loss: tuple[UnkeepableGlyph, ...]) -> str:
        """The zh-TW line naming the untouched symbols a rebuild cannot keep
        (F11-UNI-1 decision C); empty when there are none."""
        if not glyph_loss:
            return ""
        replaced = sum(1 for g in glyph_loss if g.fate == "replaced")
        removed = len(glyph_loss) - replaced
        parts = []
        if replaced:
            parts.append(f"{replaced} 個會變成其他符號")
        if removed:
            parts.append(f"{removed} 個會消失")
        return (
            f"注意：此行有 {len(glyph_loss)} 個符號無法辨識，重建後無法保留，"
            f"會變成其他符號或消失（{'、'.join(parts)}）。"
        )

    def _confirm_legacy_fallback(self, chain: tuple[str, ...]) -> bool | RebuildConsent:
        """P0-C phase 2 consent gate, passed to model.edit_text() as
        ``confirm_fallback``. The Model only ever sees an opaque callable —
        this is where the Qt modal actually lives, keeping the Model
        Qt-free. Invoked at most once per edit, synchronously, before any
        legacy mutation; see plan §8 for why this pauses inside
        model.edit_text() rather than via a Controller-side preflight."""
        view = getattr(self, "view", None)
        if view is None:
            # UI step 7: no prompt surface is not consent -- the confirm's
            # default is No (it used to answer Yes headless).
            return False
        # F11-UNI-1 (owner decision C): the model exposes the untouched
        # glyphs this rebuild cannot keep while it asks; the dialog names
        # them, and a Yes acknowledges exactly that report -- the only
        # place a ``RebuildConsent`` is produced.
        model = getattr(self, "model", None)
        glyph_loss = tuple(getattr(model, "pending_rebuild_glyph_loss", ()) or ())
        message = self._fallback_confirmation_message(chain, glyph_loss)
        if not confirm_degraded_fallback(view, message):
            return False
        if glyph_loss:
            return RebuildConsent(acknowledged_glyph_loss=glyph_loss)
        return True

    def _fallback_consent_callback(
        self, allow_rebuild: bool
    ) -> Callable[[tuple[str, ...]], bool | RebuildConsent] | None:
        """The ``confirm_fallback`` argument to pass to ``model.edit_text()``.

        UI step 7 (no silent legacy; owner decision 2026-09-30): the confirm
        modal is reachable ONLY through the explicit rebuild consent
        (``allow_rebuild``, set by the "改用重建文字…" action).  Without it
        the Model refuses a tiered rejection outright (``REJECTED``, zero
        mutation) and never asks, so no callback is passed.  This retires
        the ``TextCommitSettings.confirm_degrade`` opt-in.  Resolved at call
        time so a test may still monkeypatch ``_confirm_legacy_fallback``.
        """
        if not allow_rebuild:
            return None
        return self._confirm_legacy_fallback

    def edit_text(
        self,
        page: int | EditTextRequest,
        rect: fitz.Rect | None = None,
        new_text: str | None = None,
        font: str | None = None,
        size: float | None = None,
        color: tuple | None = None,
        original_text: str = None,
        vertical_shift_left: bool = True,
        new_rect=None,
        target_span_id: str = None,
        target_mode: str = None,
    ):
        if isinstance(page, EditTextRequest):
            request = page
        else:
            request = EditTextRequest(
                page=page,
                rect=rect,
                new_text=new_text or "",
                font=font or "helv",
                size=float(size or 12.0),
                color=color or (0.0, 0.0, 0.0),
                original_text=original_text,
                vertical_shift_left=vertical_shift_left,
                new_rect=new_rect,
                target_span_id=target_span_id,
                target_mode=target_mode,
            )
        self._commit_text_edit(request)

    def _commit_text_edit(
        self,
        request: EditTextRequest,
        *,
        prior_consent: bool | RebuildConsent | None = None,
    ) -> None:
        """Run one edit request through the command history.

        ``prior_consent`` is the rebuild consent a first attempt of the SAME
        edit already obtained (S17-DRAG-GUARD): the "place anyway" re-send of
        a refused dragged box replays it instead of asking the user a second
        time."""
        page = request.page
        rect = request.rect
        new_text = request.new_text
        font = request.font
        size = request.size
        color = request.color
        original_text = request.original_text
        vertical_shift_left = request.vertical_shift_left
        new_rect = request.new_rect
        target_span_id = request.target_span_id
        target_mode = request.target_mode
        # Empty string is a valid "delete textbox content" intent from inline edit.
        if new_text is None:
            new_text = ""
        # Each edit attempt owns the degrade flag; a stale True from an
        # earlier edit must never suppress a later edit's success toast.
        self._last_edit_degraded = False
        # Task 12 P0-C phase 2 verification: same reasoning -- a stale
        # result from an earlier edit must never be read as this edit's
        # outcome by the View's finalize path.
        self._last_edit_result = None
        self._last_edit_refusal_reason = None
        if self._refuse_foreign_session_request(request):
            return
        if not self.model.doc or page < 1 or page > len(self.model.doc):
            return
        # The commit invalidates any plan-backed preview session's scratch
        # snapshot; end it so stale rasters can never surface afterwards.
        self._end_text_edit_plan_preview_session()
        try:
            page_idx = page - 1
            view = getattr(self, "view", None)

            # 擷取 viewport anchor（在任何頁面變動前），供編輯後還原捲軸位置
            anchor = (
                view.capture_viewport_anchor()
                if (view is not None and hasattr(view, "capture_viewport_anchor"))
                else None
            )

            # Phase 4: 透過 CommandManager 執行，支援頁面快照 undo/redo
            snapshot = self.model._capture_page_snapshot(page_idx)

            consent_given: list[bool | RebuildConsent] = []
            consent_callback = self._fallback_consent_callback(
                bool(getattr(request, "allow_rebuild", False))
            )
            if consent_callback is not None:
                consent_callback = self._remembered_consent(
                    consent_callback, consent_given, prior_consent
                )

            cmd = EditTextCommand(
                model=self.model,
                page_num=page,
                rect=rect,
                new_text=new_text,
                font=font,
                size=size,
                color=color,
                original_text=original_text,
                vertical_shift_left=vertical_shift_left,
                page_snapshot_bytes=snapshot,
                old_block_id=target_span_id,
                old_block_text=original_text,
                new_rect=new_rect,
                target_span_id=target_span_id,
                target_mode=target_mode,
                style_overrides=request.style_overrides,
                plan_token=request.plan_token,
                confirm_fallback=consent_callback,
                source_ref=getattr(request, "source_ref", None),
                requires_preview_token=bool(
                    getattr(request, "requires_preview_token", False)
                ),
                allow_rebuild=bool(getattr(request, "allow_rebuild", False)),
                place_anyway=bool(getattr(request, "place_anyway", False)),
            )
            self.model.command_manager.execute(cmd)
            # Recorded BEFORE the SUCCESS branch so every outcome --
            # REJECTED_STRICT, TARGET_BLOCK_NOT_FOUND, FALLBACK_DECLINED,
            # SUCCESS -- reaches consume_last_edit_result() uniformly.
            self._last_edit_result = cmd.result
            if cmd.result is EditTextResult.REJECTED:
                self._record_edit_refusal(self._last_refusal_reason())
                self._update_undo_redo_tooltips()
                return
            if cmd.result is not EditTextResult.SUCCESS:
                self._show_edit_result_feedback(
                    cmd.result, reason=self._last_refusal_reason()
                )
                self._update_undo_redo_tooltips()
                return
            if hasattr(self, "_invalidate_active_render_state") and hasattr(self.model, "get_active_session_id"):
                self._invalidate_active_render_state()
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
            # Task 12 P0-C phase 1: a DEGRADED_COMMITTED outcome must be
            # visibly different from ordinary success — exactly one notice.
            outcome = getattr(cmd, "outcome", None)
            if self._is_notifiable_degrade(outcome):
                self._last_edit_degraded = True
                self._notify_degraded_commit(outcome)
            elif self._is_legacy_baseline_degrade(outcome):
                # Task 16 T16-1: additive branch, mutually exclusive with
                # the real-fallback branch above.
                self._last_edit_degraded = True
                self._notify_legacy_baseline_degrade(outcome)
            # 還原 viewport anchor（避免頁面重繪後捲軸跳位）
            if anchor is not None and view is not None and hasattr(view, "restore_viewport_anchor"):
                # UI step 9: a commit made right before a session change must
                # not scroll the NEXT document to this one's anchor.
                anchor_sid = self.model.get_active_session_id()

                def _restore(a=anchor, v=view, sid=anchor_sid) -> None:
                    if self.model.get_active_session_id() == sid:
                        v.restore_viewport_anchor(a)

                QTimer.singleShot(0, _restore)
                QTimer.singleShot(180, _restore)
        except Exception as e:
            # ZH-REFUSALS: one plain zh-TW sentence per refusal reason; the
            # technical detail goes to the log only.
            log_edit_failure("編輯文字失敗", e)
            choice = self._offer_place_anyway(e, request)
            if choice is True:
                # The model rolled the page back; the user chose to place the
                # dragged box as dropped, for this one edit.
                self._commit_text_edit(
                    dataclasses.replace(request, place_anyway=True),
                    prior_consent=consent_given[-1] if consent_given else prior_consent,
                )
                return
            if choice is False:
                # Cancelled: nothing changed, no error.  ``_last_edit_result``
                # stays None, so the View keeps the editor and the user's text.
                return
            show_error(self.view, user_message_for_exception(e))

    @staticmethod
    def _remembered_consent(
        ask: Callable[[tuple[str, ...]], bool | RebuildConsent],
        given: list[bool | RebuildConsent],
        prior: bool | RebuildConsent | None,
    ) -> Callable[[tuple[str, ...]], bool | RebuildConsent]:
        """``ask`` wrapped to record its answers in ``given``, or, when a first
        attempt of this edit already got ``prior``, to replay that answer
        without asking again."""

        def _consent(chain: tuple[str, ...]) -> bool | RebuildConsent:
            if prior is not None:
                return prior
            answer = ask(chain)
            given.append(answer)
            return answer

        return _consent

    def _offer_place_anyway(self, exc: BaseException, request: EditTextRequest) -> bool | None:
        """S17-DRAG-GUARD (owner decision, TODOS F13-VF-4c): a dragged box the
        overprint guard refused may be placed anyway, per edit.

        ``None`` = not applicable (another refusal, no dragged box, already
        answered, or no surface to ask on): the caller shows the plain refusal
        sentence.  Otherwise the user's answer."""
        if (
            request.new_rect is None
            or request.place_anyway
            or not isinstance(exc, TextEditRefused)
            or exc.reason is not TextEditRefusal.DRAGGED_BOX_OVERPRINTS
        ):
            return None
        view = getattr(self, "view", None)
        if view is None:
            return None
        return bool(confirm_place_anyway(view, refusal_message(exc.reason)))

    def _refuse_foreign_session_request(self, request) -> bool:
        """UI step 9: a request stamped with another document session than
        the active one is refused -- zero mutation, a notice (never a
        modal).  Plan tokens are content-derived, so without this a request
        could commit into a byte-identical copy.  ``session_id is None`` is
        an internal caller acting on the active document by construction."""
        return self._refuse_foreign_session(getattr(request, "session_id", None))

    def _refuse_foreign_session(self, session_id: str | None) -> bool:
        """The session-id check behind ``_refuse_foreign_session_request``,
        shared with ``add_textbox`` (Task B), whose signal carries the id as a
        positional argument instead of a request object."""
        if session_id is None or session_id == self.model.get_active_session_id():
            return False
        logger.warning("edit request for another document session refused")
        self._record_edit_refusal(_DOCUMENT_SESSION_MISMATCH_REASON)
        return True

    def move_text_across_pages(
        self,
        request: MoveTextRequest | int | None = None,
        source_rect: fitz.Rect | None = None,
        destination_page: int | None = None,
        destination_rect: fitz.Rect | None = None,
        new_text: str | None = None,
        font: str | None = None,
        size: float | None = None,
        color: tuple | None = None,
        original_text: str | None = None,
        target_span_id: str | None = None,
        target_mode: str | None = None,
        **legacy_kwargs,
    ) -> None:
        # Task 12 P0-C phase 1/2: reset at the TRUE entry, before any
        # early-return validation guard below -- a stale flag/result from
        # an earlier, unconsumed commit-producing interaction (e.g.
        # finalized via APPLY/FOCUS_OUTSIDE, neither of which ever calls
        # consume_last_edit_degraded()/consume_last_edit_result(); only
        # set_mode()'s MODE_SWITCH path does) must never survive a guard
        # return and be misread as THIS interaction's outcome
        # (verification finding, 2026-08-12: the reset previously sat
        # after the empty-new_text/doc-not-open guards).
        self._last_edit_degraded = False
        self._last_edit_result = None
        self._last_edit_refusal_reason = None
        if isinstance(request, MoveTextRequest):
            move_request = request
        else:
            move_request = MoveTextRequest(
                source_page=int(legacy_kwargs.pop("source_page", request or 0)),
                source_rect=legacy_kwargs.pop("source_rect", source_rect),
                destination_page=int(legacy_kwargs.pop("destination_page", destination_page)),
                destination_rect=legacy_kwargs.pop("destination_rect", destination_rect),
                new_text=legacy_kwargs.pop("new_text", new_text) or "",
                font=legacy_kwargs.pop("font", font) or "helv",
                size=float(legacy_kwargs.pop("size", size) or 12.0),
                color=legacy_kwargs.pop("color", color) or (0.0, 0.0, 0.0),
                original_text=legacy_kwargs.pop("original_text", original_text),
                target_span_id=legacy_kwargs.pop("target_span_id", target_span_id),
                target_mode=legacy_kwargs.pop("target_mode", target_mode),
                # UI step 7: the explicit rebuild consent (default off).
                allow_rebuild=bool(legacy_kwargs.pop("allow_rebuild", False)),
            )
        if self._refuse_foreign_session_request(move_request):
            return

        source_page = move_request.source_page
        source_rect = move_request.source_rect
        destination_page = move_request.destination_page
        destination_rect = move_request.destination_rect
        new_text = move_request.new_text or ""
        font = move_request.font
        size = move_request.size
        color = move_request.color
        original_text = move_request.original_text
        target_span_id = move_request.target_span_id
        target_mode = move_request.target_mode
        if not new_text.strip():
            show_error(self.view, "跨頁移動失敗：文字內容不可為空。")
            return
        if not self.model.doc:
            return
        allow_rebuild = bool(getattr(move_request, "allow_rebuild", False))
        if source_page == destination_page:
            # UI step 7: a same-page drag is rebuild-only; the move's own
            # consent (never the drag itself) is forwarded to the edit.
            self.edit_text(
                EditTextRequest(
                    page=source_page,
                    rect=source_rect,
                    new_text=new_text,
                    font=font or "helv",
                    size=float(size or 12.0),
                    color=color or (0.0, 0.0, 0.0),
                    original_text=original_text,
                    vertical_shift_left=True,
                    new_rect=destination_rect,
                    target_span_id=target_span_id,
                    target_mode=target_mode,
                    allow_rebuild=allow_rebuild,
                )
            )
            return

        page_count = len(self.model.doc)
        if (
            source_page < 1
            or destination_page < 1
            or source_page > page_count
            or destination_page > page_count
        ):
            show_error(self.view, "跨頁移動失敗：頁碼超出範圍。")
            return

        # UI step 7 (critique B3): a cross-page move ALWAYS rebuilds text --
        # the source is deleted and the destination is a fresh add_textbox
        # in a chosen font.  One explicit consent covers both legs, decided
        # here BEFORE any snapshot, deletion or insert (zero model calls on
        # a refusal or a decline).  Part 5 / A4 (owner decision Q2): no engine
        # is exempt -- the ``TEXT_COMMIT_ENGINE=legacy`` kill switch used to
        # skip this gate; it now needs the same consent as every other engine.
        if not allow_rebuild:
            self._record_edit_refusal(_CROSS_PAGE_MOVE_REASON)
            return
        if not self._confirm_legacy_fallback((_CROSS_PAGE_MOVE_REASON, "legacy")):
            self._last_edit_result = EditTextResult.FALLBACK_DECLINED
            return

        # F13-MOVE-1a: the dialog and the model's damaged latch follow THIS
        # method's whole-document restore, not the model's inner page rollback.
        # ``None`` = no restore ran; ``True`` = it succeeded; ``False`` = it failed.
        document_restored: bool | None = None
        damaged_before = self.model.session_damaged
        try:
            self.model.ensure_page_index_built(source_page)
            self.model.ensure_page_index_built(destination_page)

            resolved_target_span_id = self._resolve_cross_page_move_source_span_id(
                source_page=source_page,
                source_rect=source_rect,
                original_text=original_text,
                target_span_id=target_span_id,
            )
            if not resolved_target_span_id:
                raise UserFacingEditError("找不到要移動的原始文字。")

            # HIST-3: the deletion check below must judge by CONTENT.  Span
            # ids are positional ("p0_b1_l0_s0"), so once the source block is
            # gone the next block is renumbered into the same id and an
            # id lookup would find that neighbour.  Count the runs carrying
            # the source text now; a real deletion lowers the count.
            source_probe = self._source_run_text_probe(source_page, resolved_target_span_id)
            source_run_count_before = self._count_page_runs_with_text(source_page, source_probe)

            before_snapshot = self.model._capture_doc_snapshot()

            # cross-page move
            #   preflight source
            #     -> fail: no mutation + clear error
            #     -> pass:
            #          capture before
            #          delete source (the move's single consent -- asked
            #          before this try -- already covers it and the
            #          destination add_textbox, UI step 7 / critique B3)
            #          add destination
            #            -> fail: restore before + refresh UI + error
            #            -> pass: capture after + record one undo entry
            source_edit_result = self.model.edit_text(
                source_page,
                source_rect,
                "",
                font,
                size,
                color,
                original_text=original_text,
                vertical_shift_left=True,
                new_rect=None,
                target_span_id=resolved_target_span_id,
                target_mode=target_mode,
                # The move's consent was asked once above; the source
                # deletion replays it instead of asking a second time.
                allow_rebuild=True,
                confirm_fallback=_move_consent_already_given,
                # The destination is a plain text box: styled source text
                # (invisible, layered, CMYK, ...) refuses before any change.
                moving_off_page=True,
            )
            if source_edit_result is EditTextResult.FALLBACK_DECLINED:
                # Zero mutation happened (the consent gate fires before any
                # redaction) -- stop silently, not an error. Recorded so the
                # View's finalize path never misreports this as a commit.
                self._last_edit_result = EditTextResult.FALLBACK_DECLINED
                return
            if source_edit_result is not EditTextResult.SUCCESS:
                raise UserFacingEditError(
                    self._edit_result_to_message(source_edit_result) or "跨頁移動前無法移除來源文字"
                )

            # Task 12 P0-C phase 1: the source deletion is a real tiered
            # commit attempt (deleting via empty replacement can fall back
            # to legacy same as any edit) — it must get the same one-notice
            # treatment as the same-page path, which routes through
            # controller.edit_text and already notifies.
            source_outcome = self.model.last_commit_outcome
            if self._is_notifiable_degrade(source_outcome):
                self._last_edit_degraded = True
                self._notify_degraded_commit(source_outcome)
            elif self._is_legacy_baseline_degrade(source_outcome):
                # Task 16 T16-1: same additive legacy-baseline branch as
                # edit_text() — a legacy redact+reinsert source deletion
                # must surface the same warning as an in-place edit.
                self._last_edit_degraded = True
                self._notify_legacy_baseline_degrade(source_outcome)

            self.model.ensure_page_index_built(source_page)
            if (
                source_probe
                and self._count_page_runs_with_text(source_page, source_probe) >= source_run_count_before
            ):
                raise UserFacingEditError("原始文字刪除未完成，已取消跨頁移動。")

            self.model.add_textbox(
                destination_page,
                destination_rect,
                new_text,
                font=font,
                size=size,
                color=color,
            )

            after_snapshot = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="move_text_across_pages",
                affected_pages=sorted({source_page, destination_page}),
                before_bytes=before_snapshot,
                after_bytes=after_snapshot,
                description="跨頁移動文字",
            )
            self.model.command_manager.record(cmd)
            self._last_edit_result = EditTextResult.SUCCESS
            self._invalidate_active_render_state()
            self._invalidate_thumbnails(sorted({source_page, destination_page}))
            self.show_page(destination_page - 1)
            self._update_undo_redo_tooltips()
        except Exception as e:
            before_snapshot = locals().get("before_snapshot")
            if before_snapshot:
                try:
                    self.model.replace_active_document_from_snapshot(
                        before_snapshot,
                        affected_pages=sorted({source_page, destination_page}),
                    )
                    document_restored = True
                    if not damaged_before and self.model.session_damaged:
                        # The model latched the session at its own rollback
                        # failure; the snapshot predates the move and the
                        # document was just rebuilt from it: it is good again.
                        self.model.clear_session_damaged(
                            "cross-page move restored the whole document"
                        )
                    self._invalidate_active_render_state()
                    self._invalidate_thumbnails(sorted({source_page, destination_page}))
                    self.show_page(source_page - 1)
                    self._update_undo_redo_tooltips()
                except Exception as restore_error:
                    logger.error("move_text_across_pages restore failed: %s", restore_error)
                    if document_restored is None:
                        # The document was never put back: whatever the move
                        # already changed stays, so nothing may overwrite the file.
                        document_restored = False
                        self.model.mark_session_damaged("cross-page move restore failed")
            log_edit_failure("跨頁移動文字失敗", e)
            show_error(
                self.view,
                "跨頁移動文字沒有完成。"
                + user_message_for_exception(
                    e, cross_page_move=True, document_restored=document_restored
                ),
            )

    def _source_run_text_probe(self, source_page: int, span_id: str) -> str:
        """Normalised text of the run ``span_id`` names on ``source_page``
        (empty when it cannot be read; the deletion check is then skipped)."""
        run = self.model.block_manager.find_run_by_id(source_page - 1, span_id)
        if run is None:
            return ""
        return _normalize_run_text(getattr(run, "text", "") or "")

    def _count_page_runs_with_text(self, source_page: int, probe: str) -> int:
        """How many indexed runs on ``source_page`` carry exactly ``probe``."""
        if not probe:
            return 0
        normalize = _normalize_run_text
        return sum(
            1
            for run in self.model.block_manager.get_runs(source_page - 1)
            if normalize(getattr(run, "text", "") or "") == probe
        )

    def _resolve_cross_page_move_source_span_id(
        self,
        source_page: int,
        source_rect: fitz.Rect,
        original_text: str = None,
        target_span_id: str = None,
    ) -> str | None:
        page_idx = source_page - 1
        if target_span_id:
            source_run = self.model.block_manager.find_run_by_id(page_idx, target_span_id)
            if source_run is not None:
                return target_span_id

        # ``source_rect`` arrives in displayed space (View); ``find_by_rect``
        # queries the unrotated index.
        to_index_space = getattr(self.model, "visual_rect_to_unrotated", None)
        index_rect = (
            to_index_space(source_page, source_rect) if callable(to_index_space) else source_rect
        )
        target = self.model.block_manager.find_by_rect(
            page_idx,
            index_rect,
            original_text=original_text,
            doc=self.model.doc,
        )
        if not target:
            return None

        candidate_spans = self.model.block_manager.find_overlapping_runs(
            page_idx,
            target.layout_rect,
            tol=0.5,
        )
        if not candidate_spans:
            return None
        if len(candidate_spans) == 1:
            return candidate_spans[0].span_id

        text_probe = _normalize_run_text(original_text or target.text or "")
        if not text_probe:
            return candidate_spans[-1].span_id

        ranked = sorted(
            candidate_spans,
            key=lambda span: difflib.SequenceMatcher(
                None,
                text_probe,
                _normalize_run_text(span.text),
            ).ratio(),
        )
        return ranked[-1].span_id

    def add_textbox(
        self,
        page: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str,
        size: float,
        color: tuple,
        session_id: str | None = None,
    ) -> None:
        """``session_id`` (Task B): the document session the add box was
        opened in; an add for any other session is refused (REJECTED,
        ``document_session_mismatch``, zero mutation).  ``None`` is an
        internal caller acting on the active document by construction."""
        # Task 12 P0-C phase 1/2: reset at the TRUE entry, before either
        # early-return validation guard below — add-textbox never produces
        # a degraded commit or a non-SUCCESS EditTextResult itself, but it
        # IS a fresh commit-producing interaction for toast-suppression
        # purposes, and a stale flag/result from an earlier, unconsumed
        # interaction must not survive a guard return and be misread as
        # this one's outcome (verification finding, 2026-08-12: the reset
        # previously sat after both guards).
        self._last_edit_degraded = False
        self._last_edit_result = None
        self._last_edit_refusal_reason = None
        # F16-PASTE-1: control characters are not text; a paste of only those is blank.
        text = strip_unrenderable_controls(text)
        if not text.strip():
            return
        if self._refuse_foreign_session(session_id):
            return
        if not self.model.doc or page < 1 or page > len(self.model.doc):
            return
        try:
            page_idx = page - 1
            before_page_snapshot = self.model._capture_page_snapshot_strict(page_idx)
            cmd = AddTextboxCommand(
                model=self.model,
                page_num=page,
                visual_rect=visual_rect,
                text=text,
                font=font,
                size=size,
                color=color,
                before_page_snapshot_bytes=before_page_snapshot,
            )
            self.model.command_manager.execute(cmd)
            # AddTextboxCommand has no EditTextResult-shaped failure mode of
            # its own -- reaching here without raising means it committed.
            self._last_edit_result = EditTextResult.SUCCESS
            self._invalidate_active_render_state()
            self.show_page(page_idx)
            self._update_undo_redo_tooltips()
        except Exception as e:
            log_edit_failure("新增文字框失敗", e)
            show_error(self.view, user_message_for_exception(e))

    def set_text_target_mode(self, mode: str):
        self.model.set_text_target_mode(mode)

    def search_text(self, query: str):
        """Facade: delegate async page-by-page search to the SearchCoordinator."""
        return self._search_coordinator.search_text(query)

    def _cancel_search(self) -> None:
        """Facade: cancel any in-flight search (called before document mutations).

        13 mutation/session/navigation callers rely on this returning after the
        worker's cancel flag is set; it delegates to the coordinator's cancel().
        """
        self._search_coordinator.cancel()

    def jump_to_result(self, page_num: int, rect: fitz.Rect):
        scale = self.view.scale
        matrix = fitz.Matrix(scale, scale)
        scaled_rect = rect * matrix
        sid = self.model.get_active_session_id()
        pix = self.model.get_page_pixmap(
            page_num,
            scale,
            colorspace=(self._fitz_colorspace_for_session(sid) if sid else fitz.csRGB),
        )
        qpix = pixmap_to_qpixmap(pix)
        self.view.display_page(page_num - 1, qpix, highlight_rect=scaled_rect)
        sid = self.model.get_active_session_id()
        if sid:
            state = self._get_ui_state(sid)
            state.current_page = max(0, page_num - 1)

    def start_ocr(self, request) -> None:
        """Facade: delegate background Surya OCR to the OcrCoordinator."""
        self._ocr_coordinator.start_ocr(request)

    def cancel_ocr(self) -> None:
        """Facade: cancel any in-flight OCR run (delegates to the coordinator)."""
        self._ocr_coordinator.cancel_ocr()

    def is_device_available(self, device: str) -> bool:
        """Facade: expose OCR device availability probing to the view (PR-9:
        keeps view/dialogs/ocr.py from importing model.tools.ocr_tool directly)."""
        return is_device_available(device)

    def _report_history_step_failure(self, verb: str, exc: Exception) -> None:
        """R12 S12-REDO-REFUSAL: ``undo``/``redo`` are Qt slots, so nothing may
        escape them.  A command's own undo/redo can still raise -- most
        notably a redo that re-runs ``model.edit_text`` (the ``engine="legacy"``
        baseline) and gets a coded ``TextEditRefused``.  ``CommandManager``
        moves a command between its stacks only AFTER the step returns, so a
        raise leaves both stacks exactly as they were and the command stays
        retryable.  Same contract as a refused first edit: the technical
        detail goes to the log, the user gets one plain zh-TW dialog (modal on
        purpose: ``ROLLBACK_FAILED`` tells the user not to save).  A
        non-text-edit failure gets a neutral sentence, never the text-edit one."""
        log_edit_failure(f"{verb}失敗", exc)
        show_error(self.view, user_message_for_history_failure(verb, exc))
        self._update_undo_redo_tooltips()

    def _drop_object_selection(self) -> None:
        """Clear the View's object selection (F15-1).

        A selection names its object by page number and, for a native image, by
        its positional occurrence on that page, so it is only valid for the
        document state it was made on.  Every scene rebuild drops it in the View
        (structural ops, tab switch, structural undo/redo); this covers a
        same-page restore that rebuilds nothing: undo/redo can bring back or
        remove an object and renumber the occurrences around the selection.
        """
        clear_selection = getattr(self.view, "_clear_object_selection", None)
        if not callable(clear_selection):
            return
        try:
            clear_selection()
        except Exception:
            logger.debug("object selection clear failed", exc_info=True)

    def undo(self):
        """
        Phase 6: 統一使用 CommandManager。
        SnapshotCommand（結構性操作，或 rotate/straighten 等改變頁面尺寸的操作，
        見 ``_command_changes_page_layout``）→ 丟棄頁面尺寸快取並重建縮圖與場景。
        EditTextCommand / 其餘 SnapshotCommand → 僅刷新受影響頁面。
        """
        if not self.model.command_manager.can_undo():
            return
        self._cancel_search()
        last_cmd = self.model.command_manager._undo_stack[-1]
        try:
            undone = self.model.command_manager.undo()
        except Exception as e:
            self._report_history_step_failure("復原", e)
            return
        if undone is False:
            # Task 16 T16-3 review round 2: a refused undo (STALE_UNDO on a
            # high-fidelity command) mutates nothing and stays on the stack,
            # so there is nothing to refresh -- but the user pressed Ctrl+Z
            # and must be told why the document did not move.
            self._show_command_refusal_feedback(last_cmd, self._UNDO_REFUSED_FALLBACK)
            self._update_undo_redo_tooltips()
            return
        self._invalidate_active_render_state(clear_page_sizes=self._command_changes_page_layout(last_cmd))
        self._drop_object_selection()
        self._refresh_after_command(last_cmd)
        self._update_undo_redo_tooltips()

    def redo(self):
        """Phase 6: 統一使用 CommandManager。"""
        if not self.model.command_manager.can_redo():
            return
        self._cancel_search()
        next_cmd = self.model.command_manager._redo_stack[-1]
        try:
            redone = self.model.command_manager.redo()
        except Exception as e:
            self._report_history_step_failure("重做", e)
            return
        if redone is False:
            # Same refusal contract as undo() above: STALE_PLAN keeps the
            # command on the redo stack with zero mutation.
            self._show_command_refusal_feedback(next_cmd, self._REDO_REFUSED_FALLBACK)
            self._update_undo_redo_tooltips()
            return
        self._invalidate_active_render_state(clear_page_sizes=self._command_changes_page_layout(next_cmd))
        self._drop_object_selection()
        self._refresh_after_command(next_cmd)
        self._update_undo_redo_tooltips()

    @staticmethod
    def _command_changes_page_layout(cmd) -> bool:
        """True when undoing/redoing ``cmd`` can change the page list or a
        page's size, so the page-size cache and the continuous scene built
        from it are stale (F17-COH-1).

        ``is_structural`` alone (page count/order) is not enough: a rotation
        swaps a page's width and height with the same count, and the count-
        keyed cache in ``_session_page_sizes`` cannot notice that.
        """
        return bool(
            getattr(cmd, "is_structural", False)
            or getattr(cmd, "changes_page_geometry", False)
        )

    def _refresh_after_command(self, cmd) -> None:
        """undo/redo 後，依指令類型決定重新整理範圍。"""
        # 擷取 anchor（undo/redo 前的捲軸位置，避免頁面跳動）
        anchor = self.view.capture_viewport_anchor()

        is_structural = getattr(cmd, 'is_structural', False)
        if self._command_changes_page_layout(cmd):
            # Page list or page sizes changed: lay the scene out again from the
            # live sizes (the forward op did the same).  show_page() would only
            # swap the pixmap into the old, wrongly sized slot (F17-COH-1).
            page_idx = min(self.view.current_page, len(self.model.doc) - 1)
            self._invalidate_thumbnails(getattr(cmd, "affected_pages", None) or None)
            self._rebuild_continuous_scene(page_idx)
            if is_structural:
                self.load_annotations()
                self._schedule_stale_index_drain()
        else:
            # 精準刷新：找出受影響的頁碼
            if hasattr(cmd, '_page_num'):
                page_idx = cmd._page_num - 1        # EditTextCommand
            elif hasattr(cmd, 'affected_pages') and cmd.affected_pages:
                page_idx = cmd.affected_pages[0] - 1
            else:
                page_idx = self.view.current_page
            page_idx = min(page_idx, len(self.model.doc) - 1)
            self.show_page(page_idx)
            if getattr(cmd, '_command_type', '') in {
                'add_annotation',
                'update_annotation',
                'move_annotation',
                'delete_annotation',
            }:
                self.load_annotations()
        self.load_toc()

        # 還原 viewport anchor，避免 undo/redo 後捲軸跳位
        QTimer.singleShot(0, lambda a=anchor: self.view.restore_viewport_anchor(a))
        QTimer.singleShot(180, lambda a=anchor: self.view.restore_viewport_anchor(a))

    def change_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            logger.warning(f"無效頁碼: {page_idx}")
            return
        self.show_page(page_idx)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx

    def change_scale(self, page_idx: int, scale: float):
        """設定縮放比例：連續模式先重建 placeholder 幾何，再只重繪可見頁。"""
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return
        if not self._release_inline_editor_for_rescale():
            return
        self.view.scale = scale
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).scale = scale
        if self.view.continuous_pages:
            self._rebuild_continuous_scene(page_idx)
        else:
            sid = self.model.get_active_session_id()
            pix = self.model.get_page_pixmap(
                page_idx + 1,
                scale,
                colorspace=(self._fitz_colorspace_for_session(sid) if sid else fitz.csRGB),
            )
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)
            self.view._update_page_counter()
            self.view._update_status_bar()

    def _invalidate_thumbnails(self, affected: list[int] | None = None) -> None:
        """Schedule an async thumbnail batch for affected pages.

        ``affected`` holds 1-based page numbers; ``None`` means a full rebuild.
        When the page count is unchanged and ``affected`` is known, only the
        affected rows are re-rendered (prior thumbnail icons are preserved).
        When the count changed, ``set_thumbnail_placeholders`` resets the widget
        item count first.
        """
        sid = self.model.get_active_session_id()
        if not sid or not self.model.doc:
            return
        n = len(self.model.doc)
        count_unchanged = affected and hasattr(self.view, "thumbnail_list") and self.view.thumbnail_list.count() == n
        gen = self._next_thumb_gen(sid)
        if count_unchanged:
            start = max(0, min(affected) - 2)
            end_limit = min(max(affected), n)
            QTimer.singleShot(0, lambda s=sid, g=gen, st=start, el=end_limit: self._schedule_thumbnail_batch(st, s, g, el))
        else:
            self.view.set_thumbnail_placeholders(n)
            # Placeholder reset clears every icon, so every row must re-render.
            QTimer.singleShot(0, lambda s=sid, g=gen: self._schedule_thumbnail_batch(0, s, g))

    def _schedule_thumbnail_batch(self, start: int, session_id: str, gen: int, end_limit: int | None = None):
        if (
            self.model.get_active_session_id() != session_id
            or self._thumb_gen_by_session.get(session_id) != gen
            or not self.model.doc
            or session_id
            in getattr(self, "_thumbnail_resume_pending_by_session", set())
        ):
            return
        # The coordinator carries token + session + generation on every result, so a
        # cancelled session can never paint into the newly active tab.
        n = end_limit if end_limit is not None else len(self.model.doc)
        self._thumbnail_coordinator.request(
            session_id,
            gen,
            start,
            n,
            self._color_profile_for_session(session_id),
        )

    def _thumbnail_identity_matches(self, session_id: str, generation: int) -> bool:
        return (
            self.model.get_active_session_id() == session_id
            and self._thumb_gen_by_session.get(session_id) == generation
            and bool(self.model.doc)
        )

    def _resolve_thumbnail_file_source(
        self,
        request: ThumbnailRequest,
    ) -> ThumbnailFileSource | None:
        if self.model.get_active_session_id() != request.session_id:
            return None
        if self.model.session_has_unsaved_changes(request.session_id):
            return None
        meta = self.model.get_session_meta(request.session_id) or {}
        source_path = meta.get("saved_path") or meta.get("path")
        if not source_path:
            return None
        try:
            stat = Path(source_path).stat()
        except OSError:
            return None
        return ThumbnailFileSource(
            path=str(source_path),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            password=self.model.password,
        )

    def _render_live_thumbnail(self, page_index: int, color_profile: str) -> QImage:
        pixmap = self.model.get_thumbnail(
            page_index + 1,
            colorspace=self._fitz_colorspace_for_profile(color_profile),
        )
        return pixmap_to_qimage(pixmap)

    def _consume_thumbnail_images(self, start: int, images: list[QImage]) -> None:
        self.view.update_thumbnail_batch(start, [QPixmap.fromImage(image) for image in images])

    def _schedule_index_batch(self, start: int, session_id: str, gen: int):
        if (
            self.model.get_active_session_id() != session_id
            or self._load_gen_by_session.get(session_id) != gen
            or not self.model.doc
        ):
            return
        n = len(self.model.doc)
        end = min(start + INDEX_BATCH_SIZE, n)
        for i in range(start, end):
            self.model.ensure_page_index_built(i + 1)
        if end < n:
            QTimer.singleShot(
                INDEX_BATCH_INTERVAL_MS,
                lambda e=end, sid=session_id, g=gen: self._schedule_index_batch(e, sid, g),
            )

    def _schedule_stale_index_drain(self) -> None:
        """
        Drain stale page indices in small batches.

        This is triggered after structural operations (insert/delete) and after snapshot restore (undo/redo).
        The model marks shifted pages "stale" (cheap), and the controller rebuilds them lazily in the
        background so the UI stays responsive (especially for large PDFs).
        """
        session_id = self.model.get_active_session_id()
        if not session_id or not self.model.doc:
            return
        gen = self._next_stale_index_gen(session_id)
        # Kick cleanup to the next tick so the structural UI refresh wins first.
        QTimer.singleShot(
            0,
            lambda sid=session_id, g=gen: self._drain_stale_index_batch(sid, g),
        )

    def _drain_stale_index_batch(self, session_id: str, gen: int) -> None:
        """
        Rebuild a small slice of stale pages, then reschedule until drained.

        The `gen` token cancels older drains when a new structural operation happens, preventing multiple
        concurrent drain loops from competing for CPU and recreating the "large PDF stalls" problem.
        """
        if (
            self.model.get_active_session_id() != session_id
            or self._stale_index_gen_by_session.get(session_id) != gen
            or not self.model.doc
        ):
            return
        stale_pages = self.model.block_manager.list_stale_pages()
        if not stale_pages:
            return
        # Small batches prevent structural cleanup from recreating the large-PDF stall.
        batch = stale_pages[:INDEX_BATCH_SIZE]
        for page_idx in batch:
            self.model.ensure_page_index_built(page_idx + 1)
        if len(stale_pages) > len(batch):
            QTimer.singleShot(
                INDEX_BATCH_INTERVAL_MS,
                lambda sid=session_id, g=gen: self._drain_stale_index_batch(sid, g),
            )

    def _on_request_rerender(self):
        """觸控板縮放停止後的重渲回呼：重建 placeholder 幾何並刷新可見區。"""
        if not self.model.doc:
            return
        if not self._release_inline_editor_for_rescale():
            return
        self._rebuild_continuous_scene(self.view.current_page)

    def _release_inline_editor_for_rescale(self) -> bool:
        """Finalize policy completion (defect 1): the zoom chokepoint (wheel,
        combo, pinch, fit, fullscreen all reach ``change_scale`` or
        ``_on_request_rerender``).  A zoom rebuilds the scene, which cannot
        keep the inline editor: un-applied input refuses the zoom (the View
        keeps the editor and says why) instead of being discarded."""
        release = getattr(self.view, "release_text_editor_for_rescale", None)
        return bool(release()) if callable(release) else True

    def _rebuild_continuous_scene(self, scroll_to_page_idx: int = 0):
        """重建連續頁面 placeholder 場景並捲動至指定頁。"""
        if not self.model.doc or not self.view.continuous_pages:
            return
        session_id = self.model.get_active_session_id()
        if not session_id:
            return
        self._cancel_page_render_for_session(session_id)
        self._page_quality_map(session_id).clear()
        self.view.initialize_continuous_placeholders(
            self._session_page_sizes(session_id),
            self.view.scale,
            min(scroll_to_page_idx, len(self.model.doc) - 1),
        )
        self.load_toc()
        self._schedule_visible_render(
            session_id,
            immediate_page_idx=min(scroll_to_page_idx, len(self.model.doc) - 1),
        )

    def show_page(self, page_idx: int):
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return
        if self.view.continuous_pages and self.view.page_items:
            self.view.scroll_to_page(page_idx, emit_viewport_changed=False)
            sid = self.model.get_active_session_id()
            if sid:
                self._schedule_visible_render(sid, immediate_page_idx=page_idx)
        else:
            sid = self.model.get_active_session_id()
            pix = self.model.get_page_pixmap(
                page_idx + 1,
                self.view.scale,
                colorspace=(self._fitz_colorspace_for_session(sid) if sid else fitz.csRGB),
            )
            qpix = pixmap_to_qpixmap(pix)
            self.view.display_page(page_idx, qpix)
        sid = self.model.get_active_session_id()
        if sid:
            self._get_ui_state(sid).current_page = page_idx

    def get_text_info_at_point(
        self,
        page_num: int,
        point: fitz.Point,
        allow_fallback: bool = True,
    ):
        return self.model.get_text_info_at_point(page_num, point, allow_fallback=allow_fallback)

    def get_char_context_at_point(
        self,
        page_num: int,
        point: fitz.Point,
    ) -> tuple[str, int, list[fitz.Rect]] | None:
        return self.model.get_char_context_at_point(page_num, point)

    def get_text_in_rect(self, page_num: int, rect: fitz.Rect) -> str:
        return self.model.get_text_in_rect(page_num, rect)

    def get_text_selection_snapshot_from_run(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
    ) -> tuple[str, fitz.Rect | None]:
        return self.model.get_text_selection_snapshot_from_run(page_num, start_span_id, end_point)

    def get_text_selection_lines(
        self,
        page_num: int,
        start_span_id: str,
        end_point: fitz.Point,
        start_point: fitz.Point | None = None,
    ) -> tuple[str, list[fitz.Rect]]:
        return self.model.get_text_selection_lines(
            page_num, start_span_id, end_point, start_point
        )

    def _update_undo_redo_tooltips(self) -> None:
        """更新 View 的 undo/redo 按鈕 tooltip，顯示下一步操作描述。"""
        cm = self.model.command_manager
        undo_enabled = cm.can_undo()
        redo_enabled = cm.can_redo()
        if cm.can_undo():
            last = cm._undo_stack[-1]
            undo_tip = f"復原：{last.description}"
        else:
            undo_tip = "復原（無可撤銷操作）"
        if cm.can_redo():
            nxt = cm._redo_stack[-1]
            redo_tip = f"重做：{nxt.description}"
        else:
            redo_tip = "重做（無可重做操作）"
        self.view.update_undo_redo_tooltips(undo_tip, redo_tip)
        if hasattr(self.view, "update_undo_redo_enabled"):
            self.view.update_undo_redo_enabled(undo_enabled, redo_enabled)
        self._refresh_document_tabs()

    def _update_mode(self, mode: str):
        self._global_mode = self._normalize_mode(mode)

    # --- Annotation and bookmark handlers ---

    def load_toc(self) -> None:
        # Keyed rows: panel edits reach the model as in-place outline edits (F16-NAV-1).
        entries = self.model.get_toc_rows() if self.model.doc else []
        self.view.populate_toc(entries)

    def update_toc(self, entries: object) -> None:
        if not self.model.doc or not isinstance(entries, list):
            return
        before = self.model._capture_doc_snapshot()
        try:
            changed = self.model.set_toc(entries)
        except (TypeError, ValueError) as exc:
            # The tree already shows the rejected edit; re-sync it with the document.
            logger.warning("bookmark edit rejected: %s", exc)
            self.load_toc()
            return
        if not changed:
            return
        self._invalidate_worker_snapshot_cache()
        after = self.model._capture_doc_snapshot()
        page_num = min(max(1, self.view.current_page + 1), len(self.model.doc))
        self.model.command_manager.record(
            SnapshotCommand(
                model=self.model,
                command_type="update_toc",
                affected_pages=[page_num],
                before_bytes=before,
                after_bytes=after,
                description="更新書籤",
            )
        )
        self.load_toc()
        self._update_undo_redo_tooltips()

    def load_annotations(self):
        """Load all annotations from the model and update the view's list."""
        try:
            self.annotations = self.model.tools.annotation.get_all_annotations()
        except Exception as e:
            logger.error(f"Failed to load annotations: {e}")
            self.annotations = []
        logger.debug(f"Controller loaded {len(self.annotations)} annotations")
        self.view.populate_annotations_list(self.annotations)

    def add_annotation(self, page_idx: int, doc_point: fitz.Point, text: str):
        """Handle request to add a new annotation. doc_point 已由 view 轉為文件座標。"""
        if not self.model.doc:
            return

        try:
            before = self.model._capture_doc_snapshot()
            # Model expects 1-based page number. The call is side-effecting (the
            # annotation is added); the returned xref is intentionally unused here.
            self.model.tools.annotation.add_annotation(page_idx + 1, doc_point, text)
            self._invalidate_active_render_state()
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="add_annotation",
                affected_pages=[page_idx + 1],
                before_bytes=before,
                after_bytes=after,
                description=f"新增註解（頁面 {page_idx + 1}）",
            )
            self.model.command_manager.record(cmd)

            self.show_page(page_idx)
            self.load_annotations()
            self.view._show_annotation_panel()
            self._update_undo_redo_tooltips()

        except Exception as e:
            logger.error(f"新增註解失敗: {e}")
            show_error(self.view, f"新增註解失敗: {e}")

    def _record_annotation_mutation(
        self,
        page_idx: int,
        command_type: str,
        description: str,
        mutation,
    ) -> bool:
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            return False
        before = self.model._capture_doc_snapshot()
        if not mutation():
            return False
        self._invalidate_active_render_state()
        after = self.model._capture_doc_snapshot()
        self.model.command_manager.record(
            SnapshotCommand(
                model=self.model,
                command_type=command_type,
                affected_pages=[page_idx + 1],
                before_bytes=before,
                after_bytes=after,
                description=description,
            )
        )
        self.show_page(page_idx)
        self.load_annotations()
        self._update_undo_redo_tooltips()
        return True

    def update_annotation_content(self, page_idx: int, xref: int, text: str) -> None:
        self._record_annotation_mutation(
            page_idx,
            "update_annotation",
            f"更新註解（頁面 {page_idx + 1}）",
            lambda: self.model.tools.annotation.update_annotation(xref, text),
        )

    def move_annotation_marker(
        self,
        page_idx: int,
        xref: int,
        rect: fitz.Rect,
    ) -> None:
        self._record_annotation_mutation(
            page_idx,
            "move_annotation",
            f"移動註解（頁面 {page_idx + 1}）",
            lambda: self.model.tools.annotation.move_annotation(xref, rect),
        )

    def delete_annotation(self, page_idx: int, xref: int) -> None:
        self._record_annotation_mutation(
            page_idx,
            "delete_annotation",
            f"刪除註解（頁面 {page_idx + 1}）",
            lambda: self.model.tools.annotation.delete_annotation(xref),
        )

    def jump_to_annotation(self, xref: int):
        """Jump to the page and location of the selected annotation."""
        for annot in self.annotations:
            if annot['xref'] == xref:
                # jump_to_result expects 1-based page number
                page_num_1_based = annot['page_num'] + 1
                self.jump_to_result(page_num_1_based, annot['rect'])
                logger.debug(f"跳轉至註解 xref={xref} 於頁面 {page_num_1_based}")
                return
        logger.warning(f"找不到註解 xref={xref}")

    def toggle_annotations_visibility(self, visible: bool):
        """Show or hide all annotations."""
        if not self.model.doc:
            return
        self.model.tools.annotation.toggle_annotations_visibility(visible)
        self._invalidate_active_render_state()
        self.show_page(self.view.current_page)
        logger.debug(f"設定註解可見性為 {visible}")

    def snapshot_page(self, page_idx: int):
        """將當前頁面轉換為扁平化影像並複製到剪貼簿"""
        if not self.model.doc or page_idx < 0 or page_idx >= len(self.model.doc):
            logger.warning(f"無效頁碼: {page_idx}")
            show_error(self.view, "無效的頁碼")
            return

        try:
            # 獲取包含所有註解的扁平化頁面影像
            # 使用較高的縮放比例以獲得更好的品質
            sid = self.model.get_active_session_id()
            pix = self.model.get_page_snapshot(
                page_idx + 1,
                scale=2.0,
                colorspace=(self._fitz_colorspace_for_session(sid) if sid else fitz.csRGB),
            )

            # 轉換為 QPixmap
            qpix = pixmap_to_qpixmap(pix)

            # 複製到剪貼簿
            clipboard = QApplication.clipboard()
            clipboard.setPixmap(qpix)

            logger.debug(f"頁面 {page_idx + 1} 的快照已複製到剪貼簿，尺寸: {qpix.width()}x{qpix.height()}")
            QMessageBox.information(self.view, "快照成功", f"頁面 {page_idx + 1} 的快照已複製到剪貼簿")

        except Exception as e:
            logger.error(f"快照失敗: {e}")
            show_error(self.view, f"快照失敗: {e}")

    def insert_blank_page(self, position: int):
        """插入空白頁面"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        try:
            self._cancel_search()
            before = self.model._capture_doc_snapshot()
            # Model clamps/sanitizes position and returns the actual inserted page number.
            actual_inserted_pages = self.model.insert_blank_page(position)
            if not actual_inserted_pages:
                return
            self._invalidate_active_render_state(clear_page_sizes=True)
            after = self.model._capture_doc_snapshot()
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_blank_page",
                # Undo metadata must match real state after model-side validation.
                affected_pages=actual_inserted_pages,
                before_bytes=before,
                after_bytes=after,
                description=f"插入空白頁（位置 {actual_inserted_pages[0]}）",
            )
            self.model.command_manager.record(cmd)
            self._invalidate_thumbnails(actual_inserted_pages)
            new_page_idx = min(actual_inserted_pages[0] - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            self._schedule_stale_index_drain()
            self._update_undo_redo_tooltips()
            QMessageBox.information(self.view, "插入成功", f"已在位置 {actual_inserted_pages[0]} 插入空白頁面")
        except Exception as e:
            logger.error(f"插入空白頁面失敗: {e}")
            show_error(self.view, f"插入空白頁面失敗: {e}")

    def insert_pages_from_file(
        self,
        source_file: str,
        source_pages: list[int],
        position: int,
        password: str | None = None,
    ):
        """從其他檔案插入頁面"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的PDF文件")
            return

        try:
            self._cancel_search()
            before = self.model._capture_doc_snapshot()
            before_placeholder_active = self.model.blank_placeholder_active
            # Model validates source pages and returns the actual inserted target positions.
            actual_inserted_pages = self.model.insert_pages_from_file(
                source_file,
                source_pages,
                position,
                password=password,
            )
            if not actual_inserted_pages:
                return
            self._invalidate_active_render_state(clear_page_sizes=True)
            after = self.model._capture_doc_snapshot()
            after_placeholder_active = self.model.blank_placeholder_active
            cmd = SnapshotCommand(
                model=self.model,
                command_type="insert_pages_from_file",
                # SnapshotCommand metadata is derived from the model return (source of truth).
                affected_pages=actual_inserted_pages,
                before_bytes=before,
                after_bytes=after,
                description=f"從 {Path(source_file).name} 插入 {len(actual_inserted_pages)} 頁（位置 {actual_inserted_pages[0]}）",
                before_placeholder_active=before_placeholder_active,
                after_placeholder_active=after_placeholder_active,
            )
            self.model.command_manager.record(cmd)
            self._invalidate_thumbnails(actual_inserted_pages)
            new_page_idx = min(actual_inserted_pages[0] - 1, len(self.model.doc) - 1)
            self._rebuild_continuous_scene(new_page_idx)
            # Immediate page is ready now; the shifted suffix is drained asynchronously.
            self._schedule_stale_index_drain()
            self._update_undo_redo_tooltips()
            QMessageBox.information(
                self.view,
                "插入成功",
                f"已從 {Path(source_file).name} 插入 {len(actual_inserted_pages)} 個頁面到位置 {actual_inserted_pages[0]}",
            )
        except Exception as e:
            logger.error(f"從檔案插入頁面失敗: {e}")
            show_error(self.view, f"從檔案插入頁面失敗: {e}")

    def resolve_insert_source_file(self, path: str) -> dict | None:
        password = None
        while True:
            try:
                return self.model.open_insert_source(path, password=password)
            except PdfPasswordRequiredError:
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            except PdfPasswordRejectedError:
                show_error(self.view, "密碼錯誤，請重試。")
                pw = self.view.ask_pdf_password(path)
                if pw is None:
                    return None
                password = pw
                continue
            except RuntimeError as e:
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None
            except Exception as e:
                show_error(self.view, f"無法讀取來源檔案: {e}")
                return None

    def get_page_rect(self, page_idx: int) -> fitz.Rect:
        """Read-only page geometry for the view, which must not index
        ``model.doc`` directly (CLAUDE.md §2). Returns a *copy* of the page's
        rect — rotation-faithful, exactly as PyMuPDF reports ``page.rect`` — so
        object-drag/editor-clamp geometry is byte-identical to the old direct read.
        """
        return fitz.Rect(self.model.doc[page_idx].rect)

    def get_page_rotation(self, page_idx: int) -> int:
        """Read-only page rotation angle in degrees for the view (companion to
        ``get_page_rect``; the view must not index ``model.doc`` directly)."""
        return int(self.model.doc[page_idx].rotation)

    # --- R2.5: read-only query facade (forwards only, owns no state) ---------
    # The view must not reach through self.controller.model.<method>(...) — these
    # thin forwards keep the deep model methods on the controller's surface.

    def has_unsaved_changes(self) -> bool:
        """Read-only: does the active document have unsaved edits? (status bar)."""
        return bool(self.model.has_unsaved_changes()) if self.model is not None else False

    def get_watermarks(self) -> list:
        """Read-only watermark list for the view (replaces the 4-hop
        controller.model.tools.watermark.get_watermarks() reach-through)."""
        return self.model.tools.watermark.get_watermarks()

    def get_render_width_for_edit(self, page_num: int, rect: fitz.Rect) -> float:
        """Read-only: the model's wrap width (pt) for an add-new inline editor."""
        return self.model.get_render_width_for_edit(page_num, rect)

    def ensure_page_index_built(self, page_num: int) -> None:
        """Ensure the model's text index for ``page_num`` (1-based) is built."""
        self.model.ensure_page_index_built(page_num)

    def iter_text_targets(self, page_idx: int, mode: str, *, blocks_fallback: bool = False) -> list:
        """Read-only text-target candidates (paragraphs or runs[/blocks]) for a
        page so the view never reaches model.block_manager directly. Mirrors the
        two view call sites exactly: ``'paragraph'`` -> paragraphs; otherwise
        -> runs, and (only when ``blocks_fallback``) blocks if runs is empty.
        Geometry is DISPLAYED space (the model projects its unrotated index at
        this boundary -- ``PDFModel.get_text_targets``)."""
        return self.model.get_text_targets(page_idx, mode, blocks_fallback=blocks_fallback)

    def get_text_blocks(self, page_idx: int) -> list:
        """Read-only text blocks for a page (the outline blocks-fallback path)
        in DISPLAYED space; keeps the view off model.block_manager."""
        return self.model.get_text_blocks(page_idx)

    def build_insert_preview_html(
        self,
        *,
        text: str,
        font_size: float,
        color: tuple[float, float, float],
        font_name: str,
        line_height: float,
        member_spans: list | None = None,
    ) -> tuple[str, str]:
        """Public (css, html) builder for the inline-editor preview. Forwards to
        the SAME model engine the commit path uses (``_build_insert_css`` /
        ``_convert_text_to_html``) so preview and committed pixels are bit-exact —
        and keeps the view's PreviewRenderer off the model's private builders
        (CLAUDE.md §2). The no-jump gate enforces the pixel contract.

        ``member_spans`` are the runs being edited (opaque to the view, ``None``
        for a new text box): a right-to-left run retyped as right-to-left
        text gets the commit's RTL base direction, so the frame keeps the box's
        right edge; Latin text typed into it is laid out left-to-right, as the
        commit does (D-RTL-PREVIEW, F17-RTL-LATIN)."""
        css = self.model.build_preview_insert_css(
            size=font_size,
            color=color,
            font_hint=font_name,
            line_height=line_height,
            member_spans=member_spans,
            new_text=text,
        )
        html = self.model._convert_text_to_html(
            text=text, font_size=font_size, color=color, latin_font=font_name
        )
        return css, html

    # ---- V2 exact plan-backed preview (plan Task 8) ----------------------

    def _ensure_text_commit_preview_coordinator(self) -> TextCommitPreviewCoordinator:
        coordinator = getattr(self, "_text_commit_preview_coordinator", None)
        if coordinator is None:
            coordinator = TextCommitPreviewCoordinator(
                result_consumer=self._consume_plan_preview,
                failure_consumer=self._on_plan_preview_failed,
                identity_matches=self._plan_preview_identity_matches,
                parent=self.view,
            )
            self._text_commit_preview_coordinator = coordinator
        return coordinator

    def _plan_preview_identity_matches(self, identity: PlanPreviewIdentity) -> bool:
        return identity.session_key == getattr(self, "_plan_preview_session_key", None)

    def _end_text_edit_plan_preview_session(self) -> None:
        self._plan_preview_session_key = None
        self._plan_preview_target = None
        coordinator = getattr(self, "_text_commit_preview_coordinator", None)
        if coordinator is not None:
            coordinator.end_session()

    def on_text_edit_plan_preview_request(self, payload: dict) -> None:
        """Keystroke-debounced preview request from the View.

        The Tier 0 target is derived and the document snapshotted ONCE per
        edit session; each keystroke only re-plans the replacement text on
        the worker's cached scratch document (never a fresh snapshot).
        """
        if self._text_commit_settings().preview != "plan":
            return
        if self.model.doc is None:
            return
        try:
            session_key = str(payload["session_key"])
            page_idx = int(payload["page_idx"])
            generation = int(payload["generation"])
            document_session_id = payload.get("document_session_id")
            replacement_text = str(payload.get("replacement_text", ""))
            clip_rect = tuple(float(v) for v in payload["clip_rect"])
            render_scale = float(payload.get("render_scale", 1.0))
            raw_new_rect = payload.get("new_rect")
            new_rect = (
                tuple(float(v) for v in raw_new_rect)
                if raw_new_rect is not None
                else None
            )
            style_overrides = payload.get("style_overrides")
            if isinstance(style_overrides, dict):
                style_overrides = StyleOverrides(**style_overrides)
            elif style_overrides is not None and not isinstance(
                style_overrides, StyleOverrides
            ):
                style_overrides = None
        except (KeyError, TypeError, ValueError):
            logger.warning("plan preview payload malformed; ignored")
            return
        if (
            document_session_id is not None
            and document_session_id != self.model.get_active_session_id()
        ):
            # UI step 9: never preview (or issue a token) for a document the
            # editor was not opened in.
            self._notify_plan_preview_rejected(
                session_key, generation, _DOCUMENT_SESSION_MISMATCH_REASON
            )
            return
        coordinator = self._ensure_text_commit_preview_coordinator()
        if (
            self._plan_preview_session_key == session_key
            and self._plan_preview_target is not None
            and not coordinator.has_active_session
        ):
            # The coordinator's session was ended without going through
            # _end_text_edit_plan_preview_session (the controller's key and
            # the coordinator's session are one fact held twice): request()
            # would drop every keystroke silently.  Re-arm as a new session.
            self._plan_preview_session_key = None
            self._plan_preview_target = None
        if self._plan_preview_session_key != session_key:
            clear_cache = getattr(self.model, "clear_verified_candidates", None)
            if callable(clear_cache):
                clear_cache()
            try:
                target = derive_tier0_preview_target(
                    self.model,
                    page_num=page_idx + 1,
                    rect=fitz.Rect(payload.get("rect")),
                    original_text=payload.get("original_text"),
                    target_span_id=payload.get("target_span_id"),
                    target_mode=payload.get("target_mode"),
                    # UI step 4: the same wrong-target protection as commit;
                    # anything but the hit's ref (a dict, a twin's ref)
                    # re-derives to a mismatch and resolves no target.
                    source_ref=payload.get("source_ref"),
                )
            except Exception as exc:  # preview must never break editing
                logger.warning(
                    "plan preview target derivation failed: %s", type(exc).__name__
                )
                target = None
            # Cache even a None target under this key: an unresolvable
            # session must not re-run the resolve pipeline per keystroke.
            self._plan_preview_session_key = session_key
            self._plan_preview_target = target
            if target is None:
                coordinator.end_session()
            else:
                session = open_preview_session(
                    self.model.doc,
                    page_idx,
                    session_key,
                    password=getattr(self.model, "password", None),
                    max_tier=self._text_commit_settings().max_tier,
                    serialize=self.model.serialize_document_bytes,
                )
                if session is None:
                    # Encrypted document whose password is unavailable: no
                    # exact preview is possible. The live document is intact
                    # either way -- fall back without claiming exactness.
                    self._plan_preview_target = None
                    coordinator.end_session()
                    self._notify_plan_preview_rejected(
                        session_key, generation, "snapshot_unavailable"
                    )
                    return
                coordinator.begin_session(session)
        if self._plan_preview_target is None:
            self._notify_plan_preview_rejected(
                session_key, generation, "target_unresolved"
            )
            return
        target = self._plan_preview_target
        coordinator.request(
            generation=generation,
            target_text=target.text,
            replacement_text=target.replacement_for(replacement_text),
            expected_origin=target.origin,
            target_bbox=target.bbox,
            clip_rect=clip_rect,
            render_scale=render_scale,
            style_overrides=style_overrides,
            new_rect=new_rect,
            whitespace_reconstructed=target.whitespace_reconstructed,
        )

    def _notify_plan_preview_rejected(
        self, session_key: str, generation: int, reason: str
    ) -> None:
        notify = getattr(self.view, "apply_text_edit_plan_preview", None)
        if callable(notify):
            notify(
                session_key=session_key,
                generation=generation,
                image=None,
                plan_token=None,
                reject_reason=reason,
            )

    def _consume_plan_preview(
        self, identity: PlanPreviewIdentity, result: PlanPreviewResult
    ) -> None:
        image = None
        if result.png_bytes:
            candidate = QImage.fromData(result.png_bytes, "PNG")
            if not candidate.isNull():
                image = candidate
        # Cache only a candidate whose raster the user can actually see and
        # confirm: caching before the PNG decode is validated lets an
        # undecodable-raster candidate evict a live FIFO slot for a token
        # the view will never present (it reports plan_token=None below
        # whenever the image failed to decode).
        if (
            image is not None
            and result.plan_token is not None
            and result.prepared is not None
        ):
            cache = getattr(self.model, "cache_verified_candidate", None)
            if callable(cache):
                try:
                    cache(result.plan_token, result.prepared)
                except Exception as exc:
                    logger.warning(
                        "plan preview candidate cache failed: %s",
                        type(exc).__name__,
                    )
                    return
        self.view.apply_text_edit_plan_preview(
            session_key=identity.session_key,
            generation=identity.generation,
            image=image,
            plan_token=result.plan_token if image is not None else None,
            reject_reason=result.reject_reason,
        )

    def _on_plan_preview_failed(
        self, identity: PlanPreviewIdentity, exc: Exception
    ) -> None:
        # Sanitized: never document text or paths — only the exception type.
        logger.warning("plan preview worker failed: %s", type(exc).__name__)
        self._notify_plan_preview_rejected(
            identity.session_key, identity.generation, "preview_error"
        )

    def add_watermark(self, pages: list, text: str, angle: float, opacity: float, font_size: int, color: tuple, font: str, offset_x: float = 0, offset_y: float = 0, line_spacing: float = 1.3):
        """新增浮水印"""
        if not self.model.doc:
            show_error(self.view, "沒有開啟的 PDF 文件")
            return
        try:
            self.model.tools.watermark.add_watermark(pages, text, angle, opacity, font_size, color, font, offset_x, offset_y, line_spacing)
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self.view._show_watermark_panel()
            self._refresh_document_tabs()
        except Exception as e:
            logger.error(f"新增浮水印失敗: {e}")
            show_error(self.view, f"新增浮水印失敗: {e}")

    def update_watermark(self, wm_id: str, pages: list, text: str, angle: float, opacity: float, font_size: int, color: tuple, font: str, offset_x: float = 0, offset_y: float = 0, line_spacing: float = 1.3):
        """更新浮水印"""
        if not self.model.doc:
            return
        if self.model.tools.watermark.update_watermark(wm_id, text=text, pages=pages, angle=angle, opacity=opacity, font_size=font_size, color=color, font=font, offset_x=offset_x, offset_y=offset_y, line_spacing=line_spacing):
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self._refresh_document_tabs()

    def remove_watermark(self, wm_id: str):
        """移除浮水印"""
        if not self.model.doc:
            return
        if self.model.tools.watermark.remove_watermark(wm_id):
            self._invalidate_active_render_state()
            self._rebuild_continuous_scene(self.view.current_page)
            self.load_watermarks()
            self._refresh_document_tabs()

    def load_watermarks(self):
        """Load watermark list and update view."""
        try:
            watermarks = self.model.tools.watermark.get_watermarks()
        except Exception as e:
            logger.error(f"Failed to load watermarks: {e}")
            watermarks = []
        self.view.populate_watermarks_list(watermarks)

    def _save_session_for_close(self, session_id: str) -> bool:
        if self._is_lost(session_id):
            # Saving in place is impossible; the dialog copies the recovery file.
            return self._save_session_with_dialog(session_id)
        meta = self.model.get_session_meta(session_id) or {}
        save_path = meta.get("saved_path") or meta.get("path")
        if save_path:
            try:
                with self._background_file_readers_released(
                    resume_thumbnails=session_id != self.model.get_active_session_id()
                ):
                    # A declined signature consent is not a failed save: the
                    # close is aborted (the tab and its edits stay), no Save
                    # dialog follows (SIG-DIALOG).
                    return self._save_with_signature_consent(
                        lambda **kw: self.model.save_session_as(session_id, save_path, **kw),
                        session_id,
                    )
            except SaveRecoveryError as e:
                # The session's document is a closed handle: a Save dialog
                # would only run save_as on it ("document closed") and hide
                # where the edits were kept.  Say it as written and abort the
                # close; the tab is now a dead tab (Save As copies the recovery
                # file, Discard closes it).  The recovery copy is the only copy
                # of the edits; the model keeps it until the program exits,
                # closing the tab does NOT remove it (S14-SAVEREC-DEAD-TAB).
                logger.error(f"關閉前儲存失敗，session 已中斷: {e}")
                self._report_save_failure("儲存失敗", e, session_id)
                return False
            except DamagedSessionSaveError as e:
                # The page could not be rolled back after a failed edit: the
                # in-place save is refused (nothing written).  Say why before
                # the Save dialog offers a NEW file (S13-DLG5-DAMAGED).
                logger.warning(f"關閉前儲存已取消（文件已標記為損壞），改為另存對話框: {e}")
                show_error(self.view, self._save_failure_text("儲存失敗", e))
            except SourceChangedOnDiskError as e:
                # Another program rewrote the file: say so before the Save
                # dialog appears, or the dialog reads like an unexplained retry.
                logger.warning(f"關閉前儲存已取消（檔案已被其他程式變更），改為另存對話框: {e}")
                show_error(self.view, self._save_failure_text("儲存失敗", e))
            except Exception as e:
                logger.warning(f"自動儲存失敗，改為另存對話框: {e}")
        return self._save_session_with_dialog(session_id)

    def handle_app_close(self, event) -> None:
        page_render_coordinator = getattr(self, "_page_render_coordinator", None)
        if page_render_coordinator is not None:
            page_render_coordinator.cancel()
            if not page_render_coordinator.wait_for_done(1000):
                self._ignore_close_join_timeout(event)
                return
        self._thumbnail_coordinator.cancel()
        if not self._thumbnail_coordinator.wait_for_done(1000):
            self._ignore_close_join_timeout(event)
            return
        # The plan-preview session is NOT ended here: until the close is
        # certain (see _accept_app_close) the inline editor may stay open and
        # keeps using it.
        if self._has_active_print_submission():
            self._print_coordinator.begin_close_pending()
            event.ignore()
            return
        if self._has_active_optimize_submission():
            self._optimize_close_pending = True
            event.ignore()
            return

        # Finalize policy completion (defect 3): the inline editor's
        # un-applied input is an unsaved change of its document; it is
        # finalized only AFTER the answer (CLOSE_DOCUMENT / CLOSE_DISCARD).
        dirty_ids = list(self.model.get_dirty_session_ids())
        editor_sid = self._inline_editor_session_id()
        editor_input = self._inline_editor_has_unapplied_input()
        if editor_input and editor_sid is not None and editor_sid not in dirty_ids:
            dirty_ids.append(editor_sid)
        # A lost tab always needs the prompt (as on a single-tab close): its
        # recovery copy holds the only copy of its edits.
        for sid in self.model.session_ids:
            if sid not in dirty_ids and self._is_lost(sid):
                dirty_ids.append(sid)
        if not dirty_ids:
            self._accept_app_close(event)
            return
        lost = self._lost_sessions_with_errors(dirty_ids)

        msg_box = QMessageBox(self.view)
        msg_box.setWindowTitle("未儲存的變更")
        if editor_input:
            msg_box.setText(
                f"共有 {len(dirty_ids)} 個分頁尚未儲存（含尚未套用的文字編輯）。"
            )
        else:
            msg_box.setText(f"共有 {len(dirty_ids)} 個分頁尚未儲存。")
        informative = "是否要儲存所有變更後再關閉？快捷鍵：Y=全部儲存，N=全部放棄，Esc=取消。"
        if lost:
            lines = "\n".join(f"「{name}」：{error.recovery_path}" for name, error in lost)
            informative += (
                "\n\n其中已中斷的分頁無法再儲存：全部儲存會改為另存其暫存副本；"
                f"全部放棄後暫存副本仍保留至結束程式：\n{lines}"
            )
        msg_box.setInformativeText(informative)
        save_all_btn = msg_box.addButton("全部儲存", QMessageBox.AcceptRole)
        discard_all_btn = msg_box.addButton("全部放棄", QMessageBox.DestructiveRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.setIcon(QMessageBox.Warning)
        self._attach_yes_no_shortcuts(msg_box, save_all_btn, discard_all_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            event.ignore()
            return
        if clicked == discard_all_btn:
            self._finalize_inline_editor_for_close(None, save=False)
            # The recovery copies outlive the tabs until the program exits:
            # say where they are once more, as the single-tab Discard does.
            self._show_lost_discard_notice(lost)
            self._accept_app_close(event)
            return

        if not self._finalize_inline_editor_for_close(None, save=True):
            # Un-applied input cannot be saved: keep the window, the editor
            # and the input (the View said why).
            event.ignore()
            return
        if editor_sid is not None and editor_sid in dirty_ids:
            still_dirty = set(self.model.get_dirty_session_ids())
            if editor_sid not in still_dirty:
                # Nothing was committed after all (an empty add-text box).
                dirty_ids.remove(editor_sid)
        for sid in dirty_ids:
            if not self._save_session_for_close(sid):
                event.ignore()
                return
        self._accept_app_close(event)

    def _accept_app_close(self, event) -> None:
        """Accept the close once it is certain, after joining the preview worker.

        Round 6 MT-1: the preview session is ended only here, never ahead of
        the prompt.  Ending it earlier left the editor of an ignored close
        (Cancel, a Save All that could not apply the input, a running print or
        optimize job) with a coordinator that no longer had a session while
        the controller still held its key, so every later keystroke was
        dropped silently.  Going through ``_end_text_edit_plan_preview_session``
        keeps both copies of that fact in step even when the join times out
        and the close is ignored after all."""
        self._end_text_edit_plan_preview_session()
        coordinator = getattr(self, "_text_commit_preview_coordinator", None)
        if coordinator is not None and not coordinator.wait_for_done(1000):
            self._ignore_close_join_timeout(event)
            return
        event.accept()

    def _ignore_close_join_timeout(self, event) -> None:
        """Ignore a close whose background join timed out, and say so.

        Every such ignore used to be silent; after the prompt (discard / save)
        the user had already acted, so the window staying open looked broken."""
        event.ignore()
        logger.warning("app close deferred: background worker join timed out")
        toast = getattr(getattr(self, "view", None), "_show_toast", None)
        if callable(toast):
            toast("背景作業尚未結束，已暫緩關閉，請稍後再試一次。", duration_ms=4000, tone="warning")

    def save_and_close(self) -> bool:
        """Backward-compatible helper used by legacy flows."""
        sid = self.model.get_active_session_id()
        if not sid:
            return True
        return self._save_session_for_close(sid)
