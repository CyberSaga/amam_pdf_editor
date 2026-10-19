from __future__ import annotations

import dataclasses
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from enum import Enum
from typing import TYPE_CHECKING, Any

import fitz

from model.text_commit.dto import (
    HIGH_FIDELITY_TIERS,
    CommitOutcome,
    CommitStatus,
    RejectReason,
    is_real_fallback_commit,
)
from model.page_snapshot import PageSnapshotStale
from model.text_commit.inspect import (
    StreamStorage,
    capture_stream_storage,
    find_pages_sharing_content_stream,
    page_fingerprint,
    read_page_streams,
    renumber_invariant_page_fingerprint,
    restore_stream_storage,
)
from model.text_commit.patch import (
    PatchSet,
    SpliceError,
    StalePlanError,
    apply_patchset,
    build_reversal_patchset,
)

if TYPE_CHECKING:
    # 避免循環 import：只在型別檢查期間引入 PDFModel
    from model.edit_requests import RebuildConsent

logger = logging.getLogger(__name__)

# Read/write failures a retained-patch replay converts into "stale" (never
# escaping undo()/redo()).  ``StalePlanError``/``SpliceError`` are handled
# separately: they are raised before any mutation.
_REPLAY_READ_ERRORS = (RuntimeError, OSError, fitz.mupdf.FzErrorBase)


def _rekeyed_patchset(
    patchset: PatchSet, *, page_xref: int, stream_xref: int, fingerprint: str
) -> PatchSet:
    """``patchset`` (exactly one replacement) keyed to another page / stream
    numbering and expecting ``fingerprint`` instead."""
    return dataclasses.replace(
        patchset,
        page_xref=page_xref,
        replacements=(dataclasses.replace(patchset.replacements[0], stream_xref=stream_xref),),
        expected_page_fingerprint=fingerprint,
    )


class EditTextResult(str, Enum):
    SUCCESS = "success"
    NO_CHANGE = "no_change"
    TARGET_BLOCK_NOT_FOUND = "target_block_not_found"
    TARGET_SPAN_NOT_FOUND = "target_span_not_found"
    # V2 strict mode: the edit failed every enabled high-fidelity tier and
    # the degraded legacy engine is not permitted to run. No mutation happened.
    REJECTED_STRICT = "rejected_strict"
    # V2 hard-reject boundary: signed documents / widget-bearing pages are
    # categorically refused for the tiered engine, in strict *or*
    # non-strict mode. No mutation happened.
    REJECTED_UNSUPPORTED = "rejected_unsupported"
    # V2 redo safety: a Tier 0 commit's retained forward patch no longer
    # matches the current page fingerprint (the document changed since the
    # commit it is replaying). Redo refused; zero mutation happened.
    STALE_PLAN = "stale_plan"
    # V2 undo safety: a high-fidelity tier commit's retained inverse patch
    # is fingerprint-stale. Undo refused; zero mutation; command retained.
    # Never falls back to page-snapshot restore for these commands.
    STALE_UNDO = "stale_undo"
    # P0-C phase 2: a tiered attempt genuinely fell back to the legacy
    # engine and the user declined the pre-mutation consent prompt. Zero
    # mutation happened -- this is not an error and must not produce an
    # error toast (see PDFController._edit_result_to_message).
    FALLBACK_DECLINED = "fallback_declined"
    # UI step 4: the request named a source show (``source_ref``) that the
    # commit side could not re-derive at the resolved target -- a twin, a
    # stale view, or a group that no longer proves. Refused before any tier
    # or legacy attempt; zero mutation.
    TARGET_SOURCE_MISMATCH = "target_source_mismatch"
    # UI step 5 (apply by token): the inline Apply requires a verified
    # preview token (``EditTextRequest.requires_preview_token``) and the
    # request carries none. Refused before any tier or legacy attempt; zero
    # mutation. Not an error: the preview is still being computed.
    PREVIEW_PENDING = "preview_pending"
    # UI step 5: the request's token no longer names the candidate the live
    # page would commit (another show, a changed page, a different text).
    # Refused with zero mutation; never a legacy fallback.
    PREVIEW_STALE = "preview_stale"
    # UI step 7 (no silent legacy): the tiered engine refused and the
    # request carries no explicit rebuild consent (``allow_rebuild``).  The
    # refusal is final -- never a legacy fallback, strict or not.  The real
    # reason code is ``last_commit_outcome.degraded_reason``; zero mutation.
    REJECTED = "rejected"


# ──────────────────────────────────────────────────────────────────────────────
# 抽象基類
# ──────────────────────────────────────────────────────────────────────────────

class EditCommand(ABC):
    """
    所有可撤銷編輯操作的抽象基類（Command Pattern）。

    子類必須實作 execute() 與 undo()。
    - execute()：首次執行，或 redo 時呼叫。
    - undo()   ：撤銷，還原至 execute() 前的狀態。

    CommandManager 使用此介面管理 undo/redo 堆疊，
    不需要知道具體操作的實作細節。
    """

    @abstractmethod
    def execute(self) -> None:
        """執行操作（首次或 redo）。"""
        ...

    @abstractmethod
    def undo(self) -> None:
        """撤銷操作，還原至 execute() 前的狀態。"""
        ...

    @property
    def description(self) -> str:
        """操作的人類可讀描述，供 UI 顯示（如「復原: 編輯文字『…』」）。預設回傳類別名。"""
        return self.__class__.__name__

    def _byte_size(self) -> int:
        """回傳此指令持有的快照位元組數（byte-budget 修剪用）。預設 0。"""
        return 0

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        """Return all snapshot byte objects held by this command (for unique-byte accounting)."""
        return ()


# ──────────────────────────────────────────────────────────────────────────────
# EditTextCommand
# ──────────────────────────────────────────────────────────────────────────────

class EditTextCommand(EditCommand):
    """
    文字編輯指令：封裝單次 edit_text 操作的前後狀態，支援 undo/redo。

    undo 策略（page-level 快照）：
      - 以 page-level 快照（bytes）還原頁面，避免每次操作都儲存整份 PDF，
        顯著降低記憶體消耗與 I/O 開銷。
      - 快照應在 CommandManager.execute() 呼叫 cmd.execute() 之前由外部擷取，
        並在建構本物件時傳入 page_snapshot_bytes。
      - undo() 後需重建該頁 TextBlock 索引，確保後續查詢正確。

    頁面快照格式（model/page_snapshot.py）：
      model 提供兩個 helper（pdf_model.py）：
        def _capture_page_snapshot(self, page_num_0based: int) -> PageSnapshot:
            \"\"\"擷取頁面物件圖（頁面物件 + 其可達的所有物件，依 xref 記錄
            物件文字與 raw stream bytes）；本身即是 bytes。\"\"\"

        def _restore_page_from_snapshot(self, page_num_0based: int, snapshot) -> None:
            \"\"\"依「相同 xref」原地寫回該物件圖；絕不 insert_pdf 嫁接（嫁接會複製
            物件，使頁面 / OCG / 字型失去身分）。xref 編號已變（secure save 重新
            編號）時以 PageSnapshotStale 拒絕，且零變動。\"\"\"

    Controller 建立指令的範例（Phase 4）：
        snapshot = model._capture_page_snapshot(page - 1)
        cmd = EditTextCommand(
            model=model,
            page_num=page,
            rect=rect,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
            original_text=original_text,
            vertical_shift_left=vertical_shift_left,
            page_snapshot_bytes=snapshot,
            old_block_id=target_block.block_id if target_block else None,
            old_block_text=original_text,
        )
        command_manager.execute(cmd)
    """

    def __init__(
        self,
        model: Any,                         # PDFModel；用 Any 避免循環 import
        page_num: int,                      # 1-based（與 edit_text 介面一致）
        rect: fitz.Rect,
        new_text: str,
        font: str,
        size: float,
        color: tuple,
        original_text: str | None,
        vertical_shift_left: bool,
        page_snapshot_bytes: bytes,         # execute() 前擷取的頁面 bytes 快照
        old_block_id: str | None,        # 目標 block 的 ID（供 undo 後索引驗證用）
        old_block_text: str | None,      # 目標 block 修改前的文字（Log / debug 用）
        new_rect: Any | None = None,     # 拖曳移動後的目標位置（None = 不移動）
        target_span_id: str | None = None,
        target_mode: str | None = None,
        reflow_fn: Any | None = None,    # callable()，在 model.edit_text() 後呼叫做 displacement reflow
        style_overrides: Any | None = None,  # StyleOverrides；使用者實際碰過的樣式欄位
        plan_token: str | None = None,   # V2 prepared-plan token（stale 檢查用）
        confirm_fallback: Callable[[tuple[str, ...]], bool | RebuildConsent] | None = None,
        source_ref: Any | None = None,   # SourceShowRef；commit 端重推 group 後比對
        requires_preview_token: bool = False,  # UI step 5：僅 inline 套用設定
        allow_rebuild: bool = False,     # UI step 7：明確重建同意（僅「改用重建文字…」）
        place_anyway: bool = False,      # S17：拖曳框「仍要放在這裡」（本次編輯不套用重疊保護）
    ):
        self._model = model
        self._page_num = page_num
        self._rect = fitz.Rect(rect)        # 存副本，避免被外部改動
        self._new_text = new_text
        self._font = font
        self._size = float(size)
        self._color = color
        self.result: EditTextResult = EditTextResult.SUCCESS
        self._original_text = original_text
        self._vertical_shift_left = vertical_shift_left
        self._page_snapshot_bytes = page_snapshot_bytes
        self._old_block_id = old_block_id
        self._old_block_text = old_block_text
        self._new_rect = fitz.Rect(new_rect) if new_rect is not None else None
        self._target_span_id = target_span_id
        self._target_mode = target_mode
        self._reflow_fn = reflow_fn         # displacement reflow callback（Track A/B）
        self.style_overrides = style_overrides  # redo 需保留原始 intent
        self.plan_token = plan_token
        self.source_ref = source_ref
        self.requires_preview_token = bool(requires_preview_token)
        self.allow_rebuild = bool(allow_rebuild)
        self.place_anyway = bool(place_anyway)
        # UI step 4: the ref guards the FIRST execute (the user's click
        # against today's page). Redo replays the already-proven decision and
        # re-derives the show from the restored page via the target span
        # and the whole-show original text instead of the ref (a renumbering
        # save moves the xrefs the ref names).
        self._source_ref_proven = False
        self._confirm_fallback = confirm_fallback
        self.outcome: Any | None = None     # CommitOutcome，execute() 後由 model 提供
        self._executed = False              # 防止在未 execute 前呼叫 undo
        # UI step 8: whether this command's effect is CURRENTLY on the page
        # (True after a successful execute/redo, False after undo) -- so
        # execute() can tell a redo from a first run.
        self._applied = False
        # UI step 8: a CONSENTED rebuild (a tiered attempt that genuinely
        # fell back to legacy, ``is_real_fallback_commit``) redoes by
        # restoring the page exactly as its first execute left it -- never by
        # re-running model.edit_text() (which would re-run legacy
        # redact+reinsert, could re-prompt, and need not land the same
        # bytes).  The user's consent covers THIS command's result only.
        self._after_page_snapshot_bytes: bytes | None = None
        self._post_protected = False

        # V2 tier-aware reversal (Task 9; Task 11 Slice 1 widened this to
        # every high-fidelity tier): when the first execute() commits via a
        # high-fidelity tier (dto.HIGH_FIDELITY_TIERS -- Tier 0 or Tier 1),
        # these hold a validated forward/inverse PatchSet pair built from the
        # observed before/after stream diff (see model.text_commit.patch.
        # build_reversal_patchset). Populated once, replayed by every later
        # undo()/redo() instead of re-running the full model.edit_text()
        # pipeline (which would re-prepare from scratch on a different page
        # state and cannot reproduce the exact same committed bytes). Stay
        # ``None`` for every non-high-fidelity-tier command (Tier 2/legacy),
        # which keeps the original page-snapshot undo/full-redo behavior.
        self._tier0_forward_patchset: PatchSet | None = None
        self._tier0_inverse_patchset: PatchSet | None = None
        # Task 15 P4-B2 slice 1: exact stream storage (raw bytes + object
        # dict), not just decoded bytes, restored after replaying the
        # inverse/forward patch -- undo restores original-fidelity storage
        # (pre-commit, captured in execute()); redo restores the storage
        # this very command's commit produced (post-commit, captured in
        # _capture_tier0_reversal). A successful FRESH commit still lands
        # as MuPDF's own chosen encoding -- re-encoding new bytes under the
        # original filter chain is out of scope (TODOS).
        self._pre_storage: tuple[StreamStorage, ...] = ()
        self._post_storage: tuple[StreamStorage, ...] = ()
        # Whether the forward patch is CURRENTLY applied to the live
        # document (True right after commit/redo, False right after undo).
        self._tier0_active = False
        # Part 5 Stage C: the page's xref layout (page, content streams,
        # fonts, annotations) the retained patch sets are keyed by.  A garbage
        # save renumbers the live document, after which the retained xrefs
        # name other objects; history is keyed by PAGE, so a stale replay
        # whose layout moved is relocated by content (see
        # ``_relocated_patchset``) instead of stranding the edit.
        self._tier0_layout: tuple[Any, ...] | None = None
        # Renumbering-invariant page fingerprint taken at commit (the patched
        # stream's bytes elided): the ONLY thing that lets a replay relocate
        # after the document's xref layout moved.  ``None`` = unprovable, so
        # no relocation is ever admitted for this command.
        self._tier0_invariant: str | None = None
        # fidelity_protected_pages membership for this page *before* the
        # very first execute() -- restored verbatim by every undo(),
        # whichever restore path (patch replay or snapshot fallback) runs.
        self._pre_protected = False
        # Page-level maintenance bookkeeping this command owns: a consented
        # rebuild (legacy rewrite) queues a ``clean_contents`` entry and
        # revokes the page's protection (``mark_page_content_dirty``), while
        # undo/redo restore PAGE BYTES.  The book rides with the bytes, same
        # as ``AddTextboxCommand``/``SnapshotCommand`` -- an undone rebuild
        # must not leave its entry behind to clean a later Tier 0 stream.
        self._pre_book: MaintenanceBook | None = None
        self._post_book: MaintenanceBook | None = None

    @property
    def description(self) -> str:
        preview = (
            (self._new_text[:20] + "…")
            if len(self._new_text) > 20
            else self._new_text
        )
        return f"編輯文字「{preview}」（頁面 {self._page_num}）"

    def _byte_size(self) -> int:
        after = self._after_page_snapshot_bytes
        return len(self._page_snapshot_bytes) + (len(after) if after is not None else 0)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        after = self._after_page_snapshot_bytes
        if after is not None:
            return (self._page_snapshot_bytes, after)
        return (self._page_snapshot_bytes,)

    def execute(self) -> bool:  # type: ignore[override]
        """
        執行文字編輯：直接委派給 model.edit_text()。
        快照已在 CommandManager.execute() 建構本物件時事先擷取，此處不重複。

        Intentional LSP widening: EditCommand.execute() is annotated -> None
        (test_edit_command_execute_contract_stays_optional_for_non_edit_text_commands
        pins that), but this override returns bool so CommandManager can detect
        a no-op edit (False) and skip the undo-stack record — see
        test_edit_text_command_execute_annotation_is_bool. The `is False` check
        in CommandManager.execute()/redo() treats every other subclass's None
        return as "recordable", so the wider return type is safe at every call
        site; only mypy's strict override variance objects.

        V2 tier-aware redo: if a *previous* execute() on this command
        committed via Tier 0 and it is currently undone (``_tier0_active``
        False), CommandManager.redo() calling this same method must NOT
        re-run the whole model.edit_text() pipeline from scratch — that
        would re-classify/re-prepare against whatever the page looks like
        now and cannot guarantee reproducing the exact same committed
        bytes. Instead it replays the retained forward PatchSet directly
        (see ``_redo_tier0``): success or a stale-safe, zero-mutation
        refusal, never a silent fall-through to the legacy engine.

        UI step 8: every redo is dispatched by what the FIRST execute
        committed (``_redo``) -- a consented rebuild restores its
        after-snapshot, a high-fidelity commit without a recorded reversal
        refuses ``STALE_PLAN``.  Only a command with no such record (the
        ``engine="legacy"`` baseline, mocked models) still re-runs.
        """
        if self._executed and not self._applied:
            redone = self._redo()
            if redone is not None:
                return redone

        page_idx = self._page_num - 1
        # Best-effort: minimal/mocked models (unit tests exercising only
        # style-intent/reflow plumbing) may not expose fidelity_protected_pages
        # or a real fitz doc at all -- degrade to "no reversal tracking" for
        # those exactly like before this command grew tier0 awareness,
        # rather than requiring every caller to be a full PDFModel.
        pre_protected = False
        pre_streams: tuple[tuple[int, bytes], ...] = ()
        pre_storage: tuple[StreamStorage, ...] = ()
        pre_fingerprint: str | None = None
        pre_page: fitz.Page | None = None
        pre_book = MaintenanceBook.capture(self._model, [page_idx])
        try:
            pre_protected = page_idx in self._model.fidelity_protected_pages
            pre_page = self._model.doc[page_idx]
            pre_streams = tuple(read_page_streams(self._model.doc, pre_page))
            # Task 15 P4-B2 slice 1: exact storage per pre-existing stream,
            # so a later undo can restore original-fidelity encoding, not
            # just decoded bytes -- see _capture_tier0_reversal for the
            # post-commit counterpart.
            pre_storage = tuple(
                capture_stream_storage(self._model.doc, xref)
                for xref, _ in pre_streams
            )
            pre_fingerprint = page_fingerprint(self._model.doc, pre_page)
        except (
            AttributeError,
            IndexError,
            ValueError,
            TypeError,
            RuntimeError,
            fitz.mupdf.FzErrorBase,
        ) as exc:
            logger.debug(
                "EditTextCommand.execute(): pre-edit stream capture skipped page=%s %s",
                self._page_num,
                type(exc).__name__,
            )

        self.result = self._model.edit_text(
            self._page_num,
            self._rect,
            self._new_text,
            self._font,
            self._size,
            self._color,
            self._original_text,
            self._vertical_shift_left,
            new_rect=self._new_rect,
            target_span_id=self._target_span_id,
            target_mode=self._target_mode,
            style_overrides=self.style_overrides,
            # UI step 5: the token binds the FIRST execute to the previewed
            # candidate.  A re-execute (redo of a command with no retained
            # forward patch) replays the decision already made -- like the
            # source_ref below, the token (now stale) and its requirement
            # stay with the first execute.
            plan_token=None if self._source_ref_proven else self.plan_token,
            # UI step 8: a consented rebuild is never re-run (its redo
            # restores the after-snapshot), so this is always the FIRST
            # decision's callback -- asked at most once per command.
            confirm_fallback=self._confirm_fallback,
            source_ref=None if self._source_ref_proven else self.source_ref,
            requires_preview_token=(
                False if self._source_ref_proven else self.requires_preview_token
            ),
            allow_rebuild=self.allow_rebuild,
            place_anyway=self.place_anyway,
        )
        if self.result is not EditTextResult.SUCCESS:
            self._executed = False
            logger.debug(
                "EditTextCommand.execute(): skipped record for result=%s",
                self.result.value,
            )
            return False
        # V2 plumbing: history keeps the full CommitOutcome of this commit.
        self.outcome = getattr(self._model, "last_commit_outcome", None)
        self._source_ref_proven = True
        self._pre_protected = pre_protected
        self._pre_book = pre_book
        self._pre_storage = pre_storage
        if (
            self.outcome is not None
            and self.outcome.tier in HIGH_FIDELITY_TIERS
            and pre_fingerprint is not None
            and pre_page is not None
        ):
            self._capture_tier0_reversal(page_idx, pre_streams, pre_fingerprint)
        # Displacement reflow：將後續塊向上/下推移（Track A/B 引擎）。
        # 高保真 tier 的 outcome 會禁止外部 reflow（不得移動鄰居）。
        allows_reflow = (
            self.outcome.allows_external_reflow if self.outcome is not None else True
        )
        if self._reflow_fn is not None and allows_reflow:
            try:
                self._reflow_fn()
            except Exception as _rf_e:
                logger.warning(f"EditTextCommand reflow_fn 失敗（不影響主編輯）: {_rf_e}")
        # UI step 8: only a REAL (consented) fallback records an
        # after-snapshot -- the ``engine="legacy"`` baseline carries no
        # consent to replay and keeps its re-run redo.
        self._after_page_snapshot_bytes = None
        if is_real_fallback_commit(self.outcome):
            self._after_page_snapshot_bytes = self._capture_after_snapshot(page_idx)
            try:
                self._post_protected = page_idx in self._model.fidelity_protected_pages
            except (AttributeError, TypeError):
                self._post_protected = False
        self._post_book = MaintenanceBook.capture(self._model, [page_idx])
        self._executed = True
        self._applied = True
        logger.debug(f"EditTextCommand.execute(): {self.description}")
        return True

    def _capture_after_snapshot(self, page_idx: int) -> bytes | None:
        """The page exactly as this rebuild left it, or ``None`` (then redo
        refuses).  Strict page-level capture only: a whole-document snapshot
        would be misapplied by a page restore."""
        try:
            return self._model._capture_page_snapshot_strict(page_idx)
        except (
            AttributeError,
            IndexError,
            ValueError,
            TypeError,
            RuntimeError,
            fitz.mupdf.FzErrorBase,
        ) as exc:
            logger.warning(
                "EditTextCommand: rebuild after-snapshot not captured page=%s %s; "
                "redo will refuse",
                self._page_num,
                type(exc).__name__,
            )
            return None

    def _redo(self) -> bool | None:
        """UI step 8 redo dispatch, by what the first execute committed.

        ``None`` means "no replay record: re-run" (the ``engine="legacy"``
        baseline and minimal/mocked models).  Never re-runs a consented
        rebuild or a high-fidelity commit."""
        if self._tier0_forward_patchset is not None:
            return self._redo_tier0()
        outcome = self.outcome
        if outcome is not None and getattr(outcome, "tier", None) in HIGH_FIDELITY_TIERS:
            # Case (h): a Tier 0/1 commit whose reversal was not recorded.
            # Re-preparing against today's page cannot reproduce the
            # committed bytes and could land another tier -- refuse.
            return self._refuse_redo("high-fidelity commit has no recorded reversal")
        if is_real_fallback_commit(outcome):
            if self._after_page_snapshot_bytes is None:
                return self._refuse_redo("rebuild has no after-snapshot")
            return self._redo_from_after_snapshot()
        return None

    @staticmethod
    def _stale_outcome(detail: str) -> CommitOutcome:
        """The zero-mutation ``STALE_PLAN`` outcome of a refused undo/redo."""
        return CommitOutcome(
            status=CommitStatus.STALE_PLAN,
            tier=None,
            fallback_chain=(f"tier0:{RejectReason.STALE_PLAN}",),
            warnings=(),
            font_outcomes=(),
            verified_properties=(),
            degraded_reason=detail,
            allows_external_reflow=False,
        )

    def _refuse_redo(self, detail: str) -> bool:
        """Zero-mutation ``STALE_PLAN`` redo refusal (command stays on the
        redo stack; never a fall-through to another engine)."""
        logger.warning(
            "EditTextCommand.redo(): refused (%s); zero mutation page=%s",
            detail,
            self._page_num,
        )
        self._model.last_commit_outcome = self._stale_outcome(detail)
        self.result = EditTextResult.STALE_PLAN
        return False

    def _refuse_undo(self, detail: str) -> bool:
        """Zero-mutation ``STALE_UNDO`` undo refusal (command stays on the
        undo stack); the caller logs what went stale."""
        self._model.last_commit_outcome = self._stale_outcome(detail)
        self.result = EditTextResult.STALE_UNDO
        return False

    def _redo_from_after_snapshot(self) -> bool:
        """Restore the page exactly as the consented rebuild left it."""
        after = self._after_page_snapshot_bytes
        if after is None:
            return self._refuse_redo("rebuild has no after-snapshot")
        page_idx = self._page_num - 1
        try:
            self._model._restore_page_from_snapshot(page_idx, after)
        except PageSnapshotStale as exc:
            return self._refuse_redo(str(exc))
        self._restore_protection_membership(page_idx, self._post_book, self._post_protected)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        self._model.last_commit_outcome = self.outcome
        self.result = EditTextResult.SUCCESS
        self._applied = True
        logger.debug(
            "EditTextCommand.redo(): rebuild after-snapshot restored page %s",
            self._page_num,
        )
        return True

    def _capture_tier0_reversal(
        self,
        page_idx: int,
        pre_streams: tuple[tuple[int, bytes], ...],
        pre_fingerprint: str,
    ) -> None:
        """After a successful high-fidelity tier commit (Tier 0 or Tier 1),
        retain a forward/inverse PatchSet pair so future undo()/redo() replay
        the exact validated intent instead of re-running model.edit_text().
        Best-effort: if the observed diff doesn't look like exactly one
        high-fidelity stream patch, this command silently keeps using the
        page-snapshot fallback for undo/redo instead (never guesses).
        """
        try:
            page = self._model.doc[page_idx]
        except (IndexError, ValueError):
            return
        reversal = build_reversal_patchset(self._model.doc, page, pre_streams, pre_fingerprint)
        if reversal is None:
            logger.debug(
                "EditTextCommand: tier0 reversal not captured (page=%s), "
                "falling back to page-snapshot undo/redo",
                self._page_num,
            )
            return
        self._tier0_forward_patchset, self._tier0_inverse_patchset = reversal
        self._tier0_active = True
        self._tier0_layout = self._page_xref_layout(page)
        forward, _inverse = reversal
        self._tier0_invariant = renumber_invariant_page_fingerprint(
            self._model.doc, page, elide_stream_xref=forward.replacements[0].stream_xref
        )
        # Task 15 P4-B2 slice 1: the exact storage of the ONE stream this
        # commit patched (build_reversal_patchset guarantees exactly one),
        # captured right after the commit that produced it -- redo restores
        # THIS encoding, not whatever a fresh compress=True splice would
        # pick.
        try:
            self._post_storage = tuple(
                capture_stream_storage(self._model.doc, replacement.stream_xref)
                for replacement in forward.replacements
            )
        except (
            AttributeError,
            IndexError,
            ValueError,
            TypeError,
            RuntimeError,
            fitz.mupdf.FzErrorBase,
        ) as exc:
            # Best-effort like every other capture in this class: a failure
            # here must not turn a successful commit into a raised exception
            # from execute(). Degrade to "no post-commit storage tracked" --
            # redo() then falls back to whatever apply_patchset's own
            # compress=True splice produces, exactly the pre-slice behaviour.
            logger.debug(
                "EditTextCommand: post-commit storage capture skipped page=%s %s",
                self._page_num,
                type(exc).__name__,
            )
            self._post_storage = ()

    @staticmethod
    def _page_xref_layout(page: fitz.Page) -> tuple[Any, ...]:
        """Every xref the retained patch sets (and the page fingerprint) are
        keyed by: the page, its content streams, its fonts, its annotations.

        Only the annotation IDENTITY is needed, so ``annot_xrefs()`` (one read
        of the /Annots array) is used; ``page.annots()`` builds a full Annot
        object per entry, O(n^2) on a dense page, and this runs on every Tier
        0/1 commit and every relocation."""
        try:
            annots = tuple(entry[0] for entry in page.annot_xrefs())
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            annots = ()
        return (
            page.xref,
            tuple(page.get_contents()),
            tuple(entry[0] for entry in page.get_fonts(full=True)),
            annots,
        )

    def _relocated_patchset(
        self, doc: fitz.Document, page: fitz.Page, patchset: PatchSet
    ) -> PatchSet | None:
        """``patchset`` re-keyed to where the document's CURRENT numbering put
        its stream, or ``None`` (the caller then refuses, zero mutation).

        Never raises a MuPDF/read error: a failure anywhere in the relocation
        is "cannot prove", i.e. ``None``.
        """
        try:
            return self._relocate(doc, page, patchset)
        except (RuntimeError, ValueError, IndexError, TypeError, fitz.mupdf.FzErrorBase) as exc:
            logger.warning(
                "EditTextCommand: relocation failed (%s); refused, zero mutation page=%s",
                type(exc).__name__,
                self._page_num,
            )
            return None

    def _relocate(
        self, doc: fitz.Document, page: fitz.Page, patchset: PatchSet
    ) -> PatchSet | None:
        """The relocation proper (see :meth:`_relocated_patchset`).

        Only when the xref layout really moved since the commit (a garbage
        save renumbers the live document, even for a save to a new path); an
        unchanged layout with a failing fingerprint is genuine staleness.  The
        stream is found again by its EXACT expected bytes, must be the one
        such stream, and must belong to this page alone (``garbage=4`` merges
        identical objects; patching a shared one would silently edit another
        page).  The splice then still re-checks the expected bytes and the
        stream digest, so the byte identity gate is unchanged.

        A moved layout is admitted ONLY as a true renumbering: the page's
        renumbering-invariant fingerprint (everything ``page_fingerprint``
        covers, by content, the patched stream elided) must equal the one
        stored at commit.  A font, ExtGState, annotation, ``/Rotate``, box or
        extra content stream changed since is a foreign edit, not a
        renumbering, and refuses exactly like an unchanged layout does.
        """
        if self._tier0_layout is None or self._page_xref_layout(page) == self._tier0_layout:
            return None
        if self._tier0_invariant is None:
            return None
        if len(patchset.replacements) != 1:
            return None
        replacement = patchset.replacements[0]
        contents = list(page.get_contents())
        candidates = {
            xref
            for xref in contents
            if (doc.xref_stream(xref) or b"") == replacement.expected_bytes
        }
        if len(candidates) != 1:
            return None
        (stream_xref,) = candidates
        if contents.count(stream_xref) != 1:
            return None
        # Fail-closed, and reads /Contents by xref instead of loading every page.
        if find_pages_sharing_content_stream(
            doc, stream_xref=stream_xref, page_number=page.number
        ):
            return None
        current_invariant = renumber_invariant_page_fingerprint(
            doc, page, elide_stream_xref=stream_xref
        )
        if current_invariant is None or current_invariant != self._tier0_invariant:
            logger.warning(
                "EditTextCommand: layout moved but the page also changed beyond "
                "a renumbering; relocation refused, zero mutation page=%s",
                self._page_num,
            )
            return None
        return _rekeyed_patchset(
            patchset,
            page_xref=page.xref,
            stream_xref=stream_xref,
            fingerprint=page_fingerprint(doc, page),
        )

    def _apply_retained_patchset(self, *, inverse: bool) -> None:
        """Apply the retained inverse (undo) or forward (redo) patch set.

        Raises exactly what :func:`apply_patchset` raises when the replay is
        genuinely stale.  When the document was renumbered since the commit
        the patch set is relocated by content first; on success the retained
        pair is re-keyed to the current numbering, the opposite side
        expecting the page exactly as this replay just produced it (the same
        invariant :func:`build_reversal_patchset` records at commit time).
        """
        doc = self._model.doc
        page = doc[self._page_num - 1]
        forward, inverse_set = self._tier0_forward_patchset, self._tier0_inverse_patchset
        patchset, other = (inverse_set, forward) if inverse else (forward, inverse_set)
        if patchset is None or other is None:
            raise StalePlanError("no retained reversal")
        # Round-3 N2: ``update_stream`` can write and THEN raise.  Capture the
        # stream(s) this patch set will touch before the first apply so that
        # case is put back exactly (the relocated path below does the same).
        # Best-effort: a renumbered document makes these xrefs meaningless,
        # but they are only ever restored when the apply itself failed
        # mid-write, which needs the fingerprint gate -- hence a matching
        # layout -- to have passed first.
        plain_storage: list[StreamStorage] = []
        for replacement in patchset.replacements:
            try:
                plain_storage.append(capture_stream_storage(doc, replacement.stream_xref))
            except (*_REPLAY_READ_ERRORS, ValueError, IndexError):
                pass
        try:
            apply_patchset(doc, page, patchset)
            return
        except StalePlanError:
            relocated = self._relocated_patchset(doc, page, patchset)
            if relocated is None:
                raise
        except _REPLAY_READ_ERRORS as exc:
            for storage in plain_storage:
                restore_stream_storage(doc, storage)
            raise StalePlanError(f"replay unreadable ({type(exc).__name__})") from exc
        # Everything that can raise is computed BEFORE the splice, so nothing
        # after it can leave a half-applied replay: the opposite side's
        # expected fingerprint is the page exactly as this replay will leave it
        # (the one patched stream swapped for its replacement bytes; every other
        # fingerprint input is untouched by the splice).
        replacement = relocated.replacements[0]
        stream_xref = replacement.stream_xref
        try:
            layout_after = self._page_xref_layout(page)
            streams_after = [
                (xref, replacement.replacement_bytes if xref == stream_xref else data)
                for xref, data in read_page_streams(doc, page)
            ]
            other_fingerprint = page_fingerprint(doc, page, streams=streams_after)
            before_storage = capture_stream_storage(doc, stream_xref)
        except _REPLAY_READ_ERRORS as exc:
            raise StalePlanError(
                f"relocation bookkeeping unreadable ({type(exc).__name__})"
            ) from exc
        try:
            apply_patchset(doc, page, relocated)
        except _REPLAY_READ_ERRORS as exc:
            # StalePlanError/SpliceError are raised before any mutation; a
            # MuPDF error here may be mid-write, so put the stream back.
            restore_stream_storage(doc, before_storage)
            raise StalePlanError(f"relocated replay failed ({type(exc).__name__})") from exc
        other_rekeyed = _rekeyed_patchset(
            other, page_xref=page.xref, stream_xref=stream_xref, fingerprint=other_fingerprint
        )
        if inverse:
            self._tier0_inverse_patchset, self._tier0_forward_patchset = relocated, other_rekeyed
        else:
            self._tier0_forward_patchset, self._tier0_inverse_patchset = relocated, other_rekeyed
        # The captured storage dictionaries carry pre-renumbering indirect
        # references; restoring them over a renumbered object would corrupt
        # it.  The replay's own compressed write stands (decoded content is
        # exact) and the next save re-serializes the stream anyway.
        self._pre_storage = ()
        self._post_storage = ()
        self._tier0_layout = layout_after
        logger.debug(
            "EditTextCommand: tier0 patch set relocated after a renumbering page=%s",
            self._page_num,
        )

    def _redo_tier0(self) -> bool:
        """Replay the retained forward PatchSet — the same validated intent
        as the original high-fidelity tier commit — or fail STALE with zero
        mutation.

        Never falls through to the legacy engine: a stale forward patch
        means the document changed since the commit it is replaying, so the
        only safe outcomes are "identical replay" or "refuse, untouched".
        """
        forward = self._tier0_forward_patchset
        if forward is None:
            # execute() only routes here when the forward patch exists;
            # defensive refusal keeps mypy honest and mutates nothing.
            return False
        page_idx = self._page_num - 1
        try:
            self._apply_retained_patchset(inverse=False)
        except (StalePlanError, SpliceError, IndexError, ValueError) as exc:
            logger.warning(
                "EditTextCommand.redo(): tier0 forward patch stale (%s)",
                type(exc).__name__,
            )
            return self._refuse_redo(str(exc))

        # Task 15 P4-B2 slice 1: apply_patchset's own update_stream just
        # re-encoded the patched stream fresh (compress=True); restore the
        # EXACT storage the original commit produced, captured in
        # _capture_tier0_reversal -- best-effort, never raises.
        for storage in self._post_storage:
            restore_stream_storage(self._model.doc, storage)

        # A Tier 0 replay always leaves the page protected (without a book).
        self._restore_protection_membership(page_idx, self._post_book, True)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        self._tier0_active = True
        self._applied = True
        self.result = EditTextResult.SUCCESS
        # Same validated intent as the original commit -- outcome is left
        # untouched (it already describes the committed state this replay
        # reproduces byte-for-byte); only refresh the model's transient
        # "last operation" field for callers that read it directly.
        self._model.last_commit_outcome = self.outcome
        logger.debug(
            "EditTextCommand.redo(): tier0 forward patch replayed for page %s",
            self._page_num,
        )
        return True

    def _restore_protection_membership(
        self, page_idx: int, book: MaintenanceBook | None, protected: bool
    ) -> None:
        """Put the page's maintenance bookkeeping back with its restored
        bytes: pending ``clean_contents`` entries AND protection membership
        (``book``), or ``protected`` membership alone for a model that
        exposes no book."""
        if book is not None:
            book.restore(self._model)
        elif protected:
            self._model.fidelity_protected_pages.add(page_idx)
        else:
            self._model.fidelity_protected_pages.discard(page_idx)

    def undo(self) -> bool:  # type: ignore[override]
        """
        還原頁面至 execute() 前的狀態。

        V2 tier-aware path: if this command committed via a high-fidelity
        tier and the retained inverse PatchSet is still fingerprint-valid,
        replay it directly -- byte-identical source stream, annotation
        xrefs untouched. If the inverse is stale, refuse with STALE_UNDO
        and zero mutation (command retained on the undo stack) — never
        fall through to page-snapshot restore for high-fidelity commands.
        Non-high-fidelity commands restore their page-graph snapshot IN PLACE
        by xref (page / OCG / font identity kept); when the xref numbering moved
        since the capture that restore refuses the same way (``STALE_UNDO``,
        zero mutation, command retained).

        Intentional LSP widening (same pattern as execute): returns bool so
        CommandManager.undo() can detect STALE_UNDO (False) and keep the
        command on the undo stack.
        """
        if not self._executed:
            logger.warning("EditTextCommand.undo(): 尚未執行過，跳過還原")
            return True  # allow CommandManager to pop a no-op entry

        page_num_0based = self._page_num - 1

        if self._tier0_inverse_patchset is not None and self._tier0_active:
            try:
                self._apply_retained_patchset(inverse=True)
            except (StalePlanError, SpliceError, IndexError, ValueError) as exc:
                logger.warning(
                    "EditTextCommand.undo(): tier0 inverse patch stale (%s); "
                    "undo refused, zero mutation",
                    type(exc).__name__,
                )
                return self._refuse_undo(str(exc))
            # Task 15 P4-B2 slice 1: apply_patchset's own update_stream just
            # re-encoded the patched stream fresh (compress=True); restore
            # the EXACT pre-commit storage, captured in execute() -- undo is
            # original-fidelity, not just decoded-byte-identical.
            # Best-effort per stream, never raises.
            for storage in self._pre_storage:
                restore_stream_storage(self._model.doc, storage)
            self._restore_protection_membership(
                page_num_0based, self._pre_book, self._pre_protected
            )
            self._tier0_active = False
            self._applied = False
            self._model.block_manager.rebuild_page(page_num_0based, self._model.doc)
            logger.debug(
                f"EditTextCommand.undo(): tier0 inverse patch restored 頁面 {self._page_num}，"
                f"原文字='{self._old_block_text}'"
            )
            return True

        # Legacy / non-high-fidelity: in-place page-graph restore (zero
        # mutation + STALE_UNDO when the xref numbering moved since capture).
        try:
            self._model._restore_page_from_snapshot(
                page_num_0based, self._page_snapshot_bytes
            )
        except PageSnapshotStale as exc:
            logger.warning(
                "EditTextCommand.undo(): page snapshot stale (%s); "
                "undo refused, zero mutation",
                exc,
            )
            return self._refuse_undo(str(exc))
        self._restore_protection_membership(
            page_num_0based, self._pre_book, self._pre_protected
        )
        self._tier0_active = False
        self._applied = False

        self._model.block_manager.rebuild_page(page_num_0based, self._model.doc)

        logger.debug(
            f"EditTextCommand.undo(): 已還原頁面 {self._page_num}，"
            f"原文字='{self._old_block_text}'"
        )
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot-command bookkeeping (one mechanism for every snapshot-restoring command)
# ──────────────────────────────────────────────────────────────────────────────


class MaintenanceBook:
    """The page-level maintenance state that must travel with restored bytes.

    A content rewrite changes two things next to the document: it queues a
    ``clean_contents`` entry (``pending_edits``) and revokes the page's
    fidelity protection (``fidelity_protected_pages``), both through
    ``PDFModel.mark_page_content_dirty``.  A snapshot restore puts the BYTES
    back; without this book the restored, verified Tier 0 stream is left
    unprotected and pending, and the next save runs ``clean_contents`` over it.

    ``pages=None`` covers the whole document (a document snapshot);
    otherwise only those 0-based page indices (a page snapshot) -- the
    bookkeeping of every other page is left exactly as it is.
    """

    __slots__ = ("entries", "pages", "protected")

    def __init__(
        self,
        entries: tuple[tuple[int, tuple[float, ...]], ...],
        protected: frozenset[int],
        pages: frozenset[int] | None,
    ) -> None:
        self.entries = entries
        self.protected = protected
        self.pages = pages

    @classmethod
    def capture(cls, model: Any, pages: Iterable[int] | None = None) -> MaintenanceBook | None:
        """The model's current book, or ``None`` when the model does not expose
        the maintenance state (minimal/mocked models): restore is then a no-op,
        exactly like every other optional capture in this module."""
        wanted = None if pages is None else frozenset(int(p) for p in pages)
        try:
            entries = tuple(
                (int(e["page_idx"]), tuple(fitz.Rect(e["rect"])))
                for e in model.pending_edits
                if wanted is None or e.get("page_idx") in wanted
            )
            protected = frozenset(
                int(p) for p in model.fidelity_protected_pages if wanted is None or p in wanted
            )
        except (AttributeError, TypeError, KeyError, ValueError):
            return None
        return cls(entries, protected, wanted)

    def restore(self, model: Any) -> None:
        restored = [{"page_idx": p, "rect": fitz.Rect(r)} for p, r in self.entries]
        wanted = self.pages
        if wanted is None:
            model.pending_edits = restored
            model.fidelity_protected_pages.clear()
        else:
            kept = [e for e in model.pending_edits if e.get("page_idx") not in wanted]
            model.pending_edits = kept + restored
            model.fidelity_protected_pages.difference_update(wanted)
        model.fidelity_protected_pages.update(self.protected)


class DocSnapshot(bytes):
    """Whole-document snapshot bytes plus the :class:`MaintenanceBook` taken at
    the same instant.

    ``PDFModel._capture_doc_snapshot`` is the one place every before/after pair
    of a :class:`SnapshotCommand` comes from, so carrying the book on the bytes
    puts the bookkeeping capture at that single chokepoint -- no controller call
    site (there are dozens) has to remember it.  It is still plain ``bytes`` to
    everything else.
    """

    book: MaintenanceBook | None = None
    # The live document's xref-numbering epoch at capture (garbage=0 keeps the
    # numbering, so restoring this snapshot reinstates it).
    xref_epoch: int | None = None
    # The tools' page-bound state at capture (``ToolManager.capture_page_state``): the
    # page identity a watermark's pages are derived from.  A restore puts it back with
    # the bytes, so undo / redo of a delete / move / insert / merge return the exact
    # watermark lists, also for a watermark added after the op (F17-COH-3).
    page_state: dict[str, object] | None = None

    @classmethod
    def of(
        cls,
        data: bytes | memoryview,
        book: MaintenanceBook | None,
        xref_epoch: int | None = None,
        page_state: dict[str, object] | None = None,
    ) -> DocSnapshot:
        snapshot = cls(data)
        snapshot.book = book
        snapshot.xref_epoch = xref_epoch
        snapshot.page_state = page_state
        return snapshot


def _stamp_live_epoch(model: Any, after_bytes: bytes) -> bytes:
    """Give a bare ``after`` snapshot the live document's xref epoch.

    ``after`` is the state the live document is in when the command is
    recorded.  Bytes that did not come from ``_capture_doc_snapshot`` (the
    controller's merge builds its own garbage=0 bytes) carry no epoch, so
    redoing them would install a FRESH epoch for the identical numbering and
    strand every page-snapshot command stacked above.  The epoch and the
    tools' page state (the merge renumbers the pages a watermark is on) are
    stamped, no maintenance book: restoring behaves as before otherwise.
    """
    if isinstance(getattr(after_bytes, "xref_epoch", None), int):
        return after_bytes
    epoch = getattr(model, "xref_epoch", None)
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        return after_bytes
    capture = getattr(model, "capture_page_state", None)
    page_state = capture() if callable(capture) else None
    if not isinstance(page_state, dict):
        page_state = getattr(after_bytes, "page_state", None)
    return DocSnapshot.of(
        after_bytes,
        _book_of(after_bytes),
        xref_epoch=epoch,
        page_state=page_state if isinstance(page_state, dict) else None,
    )


def _book_of(snapshot: object) -> MaintenanceBook | None:
    book = getattr(snapshot, "book", None)
    return book if isinstance(book, MaintenanceBook) else None


# ──────────────────────────────────────────────────────────────────────────────
# SnapshotCommand
# ──────────────────────────────────────────────────────────────────────────────

class AddTextboxCommand(EditCommand):
    """Atomic add-textbox command with page-level undo/redo boundaries."""

    def __init__(
        self,
        model: Any,
        page_num: int,
        visual_rect: fitz.Rect,
        text: str,
        font: str,
        size: float,
        color: tuple,
        before_page_snapshot_bytes: bytes,
    ) -> None:
        self._model = model
        self._page_num = int(page_num)
        self._visual_rect = fitz.Rect(visual_rect)
        self._text = text
        self._font = font
        self._size = float(size)
        self._color = color
        self._before_page_snapshot_bytes = before_page_snapshot_bytes
        self._after_page_snapshot_bytes: bytes | None = None
        self._executed = False
        # Page-level maintenance bookkeeping this command owns (part 5 stage
        # B): the add queues a clean_contents entry and revokes the page's
        # fidelity protection (``mark_page_content_dirty``), while undo/redo
        # restore PAGE BYTES only.  Capture both sides so undo/redo put the
        # pending entries and protection membership back with the bytes.
        self._pre_book: MaintenanceBook | None = None
        self._post_book: MaintenanceBook | None = None

    @property
    def description(self) -> str:
        preview = (self._text[:20] + "...") if len(self._text) > 20 else self._text
        return f"新增文字框 '{preview}'（頁 {self._page_num}）"

    def _byte_size(self) -> int:
        after = self._after_page_snapshot_bytes
        return len(self._before_page_snapshot_bytes) + (len(after) if after is not None else 0)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        after = self._after_page_snapshot_bytes
        if after is not None:
            return (self._before_page_snapshot_bytes, after)
        return (self._before_page_snapshot_bytes,)

    def execute(self) -> bool | None:  # type: ignore[override]
        page_idx = self._page_num - 1
        if not self._executed:
            self._pre_book = MaintenanceBook.capture(self._model, [page_idx])
            self._model.add_textbox(
                self._page_num,
                self._visual_rect,
                self._text,
                font=self._font,
                size=self._size,
                color=self._color,
            )
            self._after_page_snapshot_bytes = self._model._capture_page_snapshot_strict(page_idx)
            self._post_book = MaintenanceBook.capture(self._model, [page_idx])
            self._executed = True
            logger.debug("AddTextboxCommand.execute(first): %s", self.description)
            return None

        if self._after_page_snapshot_bytes is None:
            raise RuntimeError("AddTextboxCommand redo 缺少 after page snapshot")
        try:
            self._model._restore_page_from_snapshot(page_idx, self._after_page_snapshot_bytes)
        except PageSnapshotStale as exc:
            logger.warning("AddTextboxCommand.redo(): refused (%s); zero mutation", exc)
            return False
        if self._post_book is not None:
            self._post_book.restore(self._model)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        logger.debug("AddTextboxCommand.execute(redo): %s", self.description)
        return True

    def undo(self) -> bool:  # type: ignore[override]
        if not self._executed:
            logger.warning("AddTextboxCommand.undo(): 尚未執行，略過")
            return True
        page_idx = self._page_num - 1
        try:
            self._model._restore_page_from_snapshot(page_idx, self._before_page_snapshot_bytes)
        except PageSnapshotStale as exc:
            logger.warning("AddTextboxCommand.undo(): refused (%s); zero mutation", exc)
            return False
        if self._pre_book is not None:
            self._pre_book.restore(self._model)
        self._model.block_manager.rebuild_page(page_idx, self._model.doc)
        logger.debug("AddTextboxCommand.undo(): %s", self.description)
        return True


class SnapshotCommand(EditCommand):
    """
    文件整體快照指令：以 before/after bytes 快照實作完整的 undo/redo。

    適用於 delete_pages、rotate_pages、insert_blank_page、
    add_highlight、add_rect、add_annotation 等操作。

    設計原則：
      - before_bytes：操作前整份文件的 bytes（undo 用）
      - after_bytes ：操作後整份文件的 bytes（redo 用）
      - execute() 是 redo 的入口，還原至 after_bytes
      - undo()    是撤銷的入口，還原至 before_bytes
      - 兩者都會清空舊 cache，並只重建 `affected_pages`（其餘頁面走 lazy rebuild）
        目的：避免大檔在 undo/redo 後做全文件重建而卡住 UI。

    Controller 建立範例：
        before = model._capture_doc_snapshot()
        model.delete_pages([3])
        after  = model._capture_doc_snapshot()
        cmd = SnapshotCommand(
            model=model,
            command_type="delete_pages",
            affected_pages=[3],  # should be the model-returned "actual affected pages" after validation
            before_bytes=before,
            after_bytes=after,
            description="刪除頁面 3",
        )
        model.command_manager.record(cmd)   # ← 用 record，不用 execute

    is_structural：True 表示操作會影響頁數/頁序（delete/insert/move），
                   Controller 的 undo/redo 需要全量重建縮圖與場景。
    changes_page_geometry：True 表示 undo/redo 可能改變頁面尺寸或頁面清單
                   （structural 全部，加上 rotate/straighten：頁數頁序不變，
                   但頁面寬高可變）。Controller 依此丟棄頁面尺寸快取並重排
                   連續場景（F17-COH-1）。
    """

    _STRUCTURAL_TYPES = frozenset({
        "delete_pages",
        "insert_blank_page",
        "insert_pages_from_file",
        "move_page",
        "merge_pdfs",
        "move_text_across_pages",
    })

    # Every op whose forward path drops the controller's page-size cache
    # (``clear_page_sizes=True``) belongs here, or its undo/redo keeps the
    # stale sizes (F17-COH-1: a rotation swaps width and height without
    # touching count or order).  Guarded by a source scan of the controller
    # (test_multi_tab_plan.py::test_04j).
    _PAGE_GEOMETRY_TYPES = _STRUCTURAL_TYPES | frozenset({
        "rotate_pages",
        "straighten_pages",
    })

    def __init__(
        self,
        model: Any,
        command_type: str,
        affected_pages: list,
        before_bytes: bytes,
        after_bytes: bytes,
        description: str,
        *,
        before_placeholder_active: bool | None = None,
        after_placeholder_active: bool | None = None,
        index_pages: list[int] | None = None,
    ):
        self._model = model
        self._command_type = command_type
        self._affected_pages = list(affected_pages)
        self._before_bytes = before_bytes
        self._after_bytes = _stamp_live_epoch(model, after_bytes)
        self._description = description
        self._before_placeholder_active = before_placeholder_active
        self._after_placeholder_active = after_placeholder_active
        self._index_pages = list(index_pages) if index_pages is not None else None

    @property
    def description(self) -> str:
        return self._description

    @property
    def is_structural(self) -> bool:
        """True 時 Controller 的 undo/redo 需要全量重建縮圖與場景。"""
        return self._command_type in self._STRUCTURAL_TYPES

    @property
    def changes_page_geometry(self) -> bool:
        """True when undo/redo can change a page's size or the page list.

        A superset of ``is_structural``: a rotation keeps page count and order
        but swaps a page's width and height, so the Controller must drop its
        page-size cache and lay the scene out again (F17-COH-1).
        """
        return self._command_type in self._PAGE_GEOMETRY_TYPES

    @property
    def affected_pages(self) -> list:
        return self._affected_pages

    def _byte_size(self) -> int:
        return len(self._before_bytes) + len(self._after_bytes)

    def _snapshot_chunks(self) -> tuple[bytes, ...]:
        return (self._before_bytes, self._after_bytes)

    def execute(self) -> None:
        """redo：從 after_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._after_bytes)
        if self._after_placeholder_active is not None:
            self._model._set_blank_placeholder_active(self._after_placeholder_active)
        # Structural redo avoids the old eager full rebuild and only restores the hot pages.
        self._model.refresh_structural_indexes(self._index_pages or self._affected_pages)
        logger.debug(f"SnapshotCommand.execute() [redo]: {self._description}")

    def undo(self) -> None:
        """撤銷：從 before_bytes 還原文件，並重建 TextBlock 索引。"""
        self._model._restore_doc_from_snapshot(self._before_bytes)
        if self._before_placeholder_active is not None:
            self._model._set_blank_placeholder_active(self._before_placeholder_active)
        # The remaining pages are rebuilt later through the model/controller lazy path.
        self._model.refresh_structural_indexes(self._index_pages or self._affected_pages)
        logger.debug(f"SnapshotCommand.undo(): {self._description}")


# ──────────────────────────────────────────────────────────────────────────────
# CommandManager
# ──────────────────────────────────────────────────────────────────────────────

_SAVED_UNREACHABLE = object()
"""Saved-marker value for a saved state that undo/redo can no longer return to."""


class CommandManager:
    """
    管理可撤銷指令的 undo/redo 堆疊（Command Pattern 的 Invoker）。

    Phase 6：統一 undo 堆疊，取代舊的檔案式 _save_state / undo / redo 機制。
    所有操作（文字編輯用 execute()，其他操作用 record()）統一由此管理器管理。

    使用流程：
        # 建構指令（包含事先擷取的頁面快照）
        snapshot = model._capture_page_snapshot(page - 1)
        cmd = EditTextCommand(model, page, rect, new_text, ...,
                              page_snapshot_bytes=snapshot, ...)
        # 執行並記錄
        command_manager.execute(cmd)
        ...
        # 撤銷 / 重做
        command_manager.undo()
        command_manager.redo()
        # 儲存後標記（重要：避免 has_pending_changes 誤報）
        command_manager.mark_saved()
    """

    MAX_UNDO_STACK_SIZE = 100
    MAX_UNDO_STACK_BYTES = 512 * 1024 * 1024  # 512 MiB

    def __init__(self):
        self._undo_stack: list[EditCommand] = []
        self._redo_stack: list[EditCommand] = []
        # The saved marker identifies the saved STATE, not a stack length: the command
        # on top of the undo stack when mark_saved() ran (None = the empty base state).
        # A length can't tell "save -> undo -> a different edit" from the saved state,
        # nor survive eviction past the saved point; an identity can.
        # _SAVED_UNREACHABLE = the saved state can no longer be reached by undo/redo.
        self._saved_marker: object | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # 公開介面
    # ──────────────────────────────────────────────────────────────────────────

    def execute(self, cmd: EditCommand) -> None:
        """
        執行指令並推入 undo 堆疊；同時清空 redo 堆疊（新操作使歷史失效）。

        Args:
            cmd: 已建構（含快照）且尚未 execute() 的 EditCommand 物件。
        注意：若指令已在外部執行完（如 SnapshotCommand），請改用 record()。
        """
        executed = cmd.execute()
        if executed is False:
            logger.debug(
                "CommandManager.execute(): command skipped undo record: %s",
                cmd.description,
            )
            return
        self._undo_stack.append(cmd)
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()

        # 新操作使原 redo 歷史失效
        if self._redo_stack:
            logger.debug(
                f"CommandManager.execute(): 清空 redo 堆疊（{len(self._redo_stack)} 筆）"
            )
            self._discard_redo_stack()

        logger.debug(
            f"CommandManager.execute(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}"
        )

    def record(self, cmd: EditCommand) -> None:
        """
        記錄「已在外部執行完畢」的指令到 undo 堆疊（不重複呼叫 execute()）。

        適用情境：Controller 已先執行操作、後補建 SnapshotCommand 的流程：
            before = model._capture_doc_snapshot()
            model.delete_pages(pages)          # 操作已完成
            after  = model._capture_doc_snapshot()
            cmd = SnapshotCommand(...)
            model.command_manager.record(cmd)  # 補記，不重複執行

        Args:
            cmd: 已執行完的 EditCommand 物件（SnapshotCommand 等）。
        """
        self._undo_stack.append(cmd)
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()
        if self._redo_stack:
            logger.debug(
                f"CommandManager.record(): 清空 redo 堆疊（{len(self._redo_stack)} 筆）"
            )
            self._discard_redo_stack()
        logger.debug(
            f"CommandManager.record(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}"
        )

    def undo(self) -> bool:
        """
        撤銷最近一次操作。

        Returns:
            True 若成功撤銷，False 若 undo 堆疊為空，或 the command refused
            (e.g. high-fidelity STALE_UNDO — command retained on the stack).
        """
        if not self._undo_stack:
            logger.debug("CommandManager.undo(): undo 堆疊為空，無可撤銷")
            return False

        cmd = self._undo_stack[-1]
        undone = cmd.undo()
        if undone is False:
            logger.debug(
                "CommandManager.undo(): command undo skipped: %s",
                cmd.description,
            )
            return False
        self._undo_stack.pop()
        self._redo_stack.append(cmd)

        logger.debug(
            f"CommandManager.undo(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}，"
            f"redo 堆疊大小={len(self._redo_stack)}"
        )
        return True

    def redo(self) -> bool:
        """
        重做最近一次被撤銷的操作。

        Returns:
            True 若成功重做，False 若 redo 堆疊為空。
        """
        if not self._redo_stack:
            logger.debug("CommandManager.redo(): redo 堆疊為空，無可重做")
            return False

        cmd = self._redo_stack[-1]
        executed = cmd.execute()
        if executed is False:
            logger.debug(
                "CommandManager.redo(): command redo skipped: %s",
                cmd.description,
            )
            return False
        self._redo_stack.pop()
        self._undo_stack.append(cmd)
        self._dedup_top_snapshot_pair()
        self._trim_undo_stack_if_needed()

        logger.debug(
            f"CommandManager.redo(): {cmd.description}，"
            f"undo 堆疊大小={len(self._undo_stack)}，"
            f"redo 堆疊大小={len(self._redo_stack)}"
        )
        return True

    def mark_saved(self) -> None:
        """
        標記當前狀態（undo 堆疊頂端的指令；空堆疊 = 基底狀態）為「已儲存狀態」。
        應在 PDFModel.save_as()（或 save()）成功後呼叫。

        The marker is the top command itself (identity), not the stack length, so a
        different history of the same length is never mistaken for the saved state.

        Phase 3 整合範例（pdf_model.py 的 save_as 末尾）：
            self.command_manager.mark_saved()
        """
        self._saved_marker = self._undo_stack[-1] if self._undo_stack else None
        logger.debug(
            f"CommandManager.mark_saved(): 已儲存標記，"
            f"undo_depth={len(self._undo_stack)}"
        )

    def _discard_redo_stack(self) -> None:
        """Drop the redo history; a saved state that lived only there is unreachable now
        (and the marker must not keep its command and snapshots alive)."""
        marker = self._saved_marker
        if marker is not None and any(c is marker for c in self._redo_stack):
            self._saved_marker = _SAVED_UNREACHABLE
        self._redo_stack.clear()

    def _note_evicted(self, evicted: list[EditCommand]) -> None:
        """Eviction removed the oldest commands: the empty base state and any evicted
        saved command can no longer be returned to by undo (the document still carries
        their effects), so the saved state is unreachable and must read as dirty."""
        if not evicted:
            return
        marker = self._saved_marker
        if marker is None or any(c is marker for c in evicted):
            self._saved_marker = _SAVED_UNREACHABLE

    def clear(self) -> None:
        """清空所有堆疊（開啟新 PDF 或關閉 PDF 時呼叫）。"""
        undo_count = len(self._undo_stack)
        redo_count = len(self._redo_stack)
        self._undo_stack.clear()
        self._redo_stack.clear()
        # Reset the saved marker so has_pending_changes() reads False after clear().
        self._saved_marker = None
        logger.debug(
            f"CommandManager.clear(): 已清空 undo({undo_count}) + redo({redo_count}) 堆疊"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 狀態查詢
    # ──────────────────────────────────────────────────────────────────────────

    def _dedup_top_snapshot_pair(self) -> None:
        """堆疊頂端相鄰兩筆 SnapshotCommand 邊界快照相同時，共用同一 bytes 物件。

        典型情境：操作 N 的 after_bytes 與操作 N+1 的 before_bytes 內容相同
        （兩次 _capture_doc_snapshot 之間文件未變動）。bytes 不可變、還原端
        （fitz.open("pdf", ...)）內部複製，共用安全；可省下一份整文件快照。
        僅對 SnapshotCommand（整文件快照）做此最佳化。
        """
        if len(self._undo_stack) < 2:
            return
        prev = self._undo_stack[-2]
        curr = self._undo_stack[-1]
        if not isinstance(prev, SnapshotCommand) or not isinstance(curr, SnapshotCommand):
            return
        if prev._after_bytes is curr._before_bytes:
            return
        if prev._after_bytes == curr._before_bytes:
            curr._before_bytes = prev._after_bytes
            logger.debug(
                "CommandManager: deduplicated adjacent snapshot boundary (%s bytes shared)",
                len(prev._after_bytes),
            )

    def _trim_undo_stack_if_needed(self) -> None:
        """Evict oldest undo entries when count or byte budget is exceeded."""
        overflow = len(self._undo_stack) - self.MAX_UNDO_STACK_SIZE
        if overflow > 0:
            self._note_evicted(self._undo_stack[:overflow])
            del self._undo_stack[:overflow]
            logger.debug(
                "CommandManager: evicted %s oldest undo commands to enforce max=%s",
                overflow,
                self.MAX_UNDO_STACK_SIZE,
            )

        total_bytes = self._unique_byte_total()
        if total_bytes <= self.MAX_UNDO_STACK_BYTES:
            return
        dropped: list[EditCommand] = []
        while len(self._undo_stack) > 1 and total_bytes > self.MAX_UNDO_STACK_BYTES:
            dropped.append(self._undo_stack.pop(0))
            total_bytes = self._unique_byte_total()
        if dropped:
            self._note_evicted(dropped)
            logger.debug(
                "CommandManager: evicted %s oldest undo commands to enforce byte budget=%s (remaining=%s bytes)",
                len(dropped),
                self.MAX_UNDO_STACK_BYTES,
                total_bytes,
            )
        if total_bytes > self.MAX_UNDO_STACK_BYTES:
            logger.warning(
                "CommandManager: newest command (%s bytes) exceeds byte budget %s — keeping it",
                total_bytes,
                self.MAX_UNDO_STACK_BYTES,
            )

    def _unique_byte_total(self) -> int:
        # Dedup by CONTENT, not id(): adjacent boundary pairs are aliased to one
        # object by _dedup_top_snapshot_pair, but byte-identical snapshots that are
        # *non-adjacent* (e.g. a fresh capture matching an earlier doc state) remain
        # distinct objects. An id()-keyed sum double-counts those against the budget
        # and evicts prematurely. bytes are hashable (CPython caches the hash on the
        # object), so a content-keyed set is exact and amortized-cheap across the
        # repeated calls in the trim loop.
        seen: set[bytes] = set()
        total = 0
        for cmd in self._undo_stack:
            for chunk in cmd._snapshot_chunks():
                if chunk not in seen:
                    seen.add(chunk)
                    total += len(chunk)
        return total

    def can_undo(self) -> bool:
        """是否有可撤銷的操作（供 UI 啟用/停用 Undo 按鈕）。"""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """是否有可重做的操作（供 UI 啟用/停用 Redo 按鈕）。"""
        return bool(self._redo_stack)

    @property
    def undo_count(self) -> int:
        """undo 堆疊中的操作數量。"""
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        """redo 堆疊中的操作數量。"""
        return len(self._redo_stack)

    def has_pending_changes(self) -> bool:
        """
        是否有尚未存檔的文字編輯變更。

        Compares the CURRENT state (top undo command; None = empty base) with the
        saved state by identity, not by stack length:
          - 執行了編輯但尚未存檔 → True
          - 存檔後再 undo（檔案內容已與磁碟不同）→ True
          - 存檔 → undo → 不同的新編輯（堆疊長度相同）→ True
          - 存檔點被淘汰（超出上限）後 → True，即使 undo 到堆疊為空
          - 剛存檔後 / undo→redo 回到存檔點 / clear() 後 → False

        設計說明：此方法僅追蹤文字編輯（EditTextCommand）的變更狀態，
        檔案整體是否已儲存仍由 pdf_model.py 的 has_unsaved_changes() 主控。
        Phase 4 可考慮將兩者整合。
        """
        current = self._undo_stack[-1] if self._undo_stack else None
        return current is not self._saved_marker
