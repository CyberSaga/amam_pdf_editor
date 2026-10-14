"""Plain Traditional Chinese messages for refused text edits.

Owner decision (adversarial round 11, "Refusal UI"): one short message per
refusal reason, saying what happened and what the user can do.  The Model
raises ``TextEditRefused`` with a ``TextEditRefusal`` code; this module maps
the code to the sentence.  The technical detail is logged by the caller and
never shown.  An exception without a known code gets the generic sentence,
so nothing English or technical can reach the dialog.

The sentences contain no Latin letters on purpose (a test pins it) and never
quote document content (P0-C privacy contract).
"""
from __future__ import annotations

import logging

from model.text_edit_refusal import TextEditRefusal, TextEditRefused

logger = logging.getLogger(__name__)

_UNCHANGED = "文件沒有被改動。"

GENERIC_REFUSAL_MESSAGE = "這次文字編輯沒有完成。請稍後再試，或換一種編輯方式。"

_MESSAGES: dict[TextEditRefusal, str] = {
    TextEditRefusal.REDACTION_LEFT_SOURCE: (
        "這段文字（例如直式文字）無法被乾淨地移除，若繼續會讓新舊文字疊在一起，"
        "所以沒有套用。" + _UNCHANGED + "請改編輯其他文字，或在旁邊新增文字框。"
    ),
    TextEditRefusal.TEXT_DOES_NOT_FIT: (
        "新的文字放不進原本的位置，即使縮小也一樣，所以沒有套用。" + _UNCHANGED
        + "請減少字數或調整字級後再試。"
    ),
    TextEditRefusal.CHARACTERS_LOST: (
        "新文字中有些字無法寫入頁面，若繼續會讓字消失，所以沒有套用。" + _UNCHANGED
        + "請改用其他字，或刪除這些字後再試。"
    ),
    TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED: (
        "這行文字含有無法辨識的符號，重建後無法保留，而且尚未經過你確認，所以沒有套用。"
        + _UNCHANGED + "請刪除這些符號，或重新操作並在提示時確認。"
    ),
    TextEditRefusal.EXT_B_FONT_MISSING: (
        "新文字含有罕見漢字（超出一般字集的生僻字），這台電腦找不到能顯示它們的字型，所以沒有套用。"
        + _UNCHANGED + "請安裝系統內建的生僻字字型（細明體或宋體的擴充版本），或改用常用字。"
    ),
    TextEditRefusal.EXT_B_COMPONENT_MISSING: (
        "新文字含有罕見漢字，但這個程式缺少顯示它們所需的元件，通常是安裝不完整，所以沒有套用。"
        + _UNCHANGED + "請重新安裝或更新本程式，或改用常用字。"
    ),
    TextEditRefusal.NO_FONT_FOR_CHARACTERS: (
        "新文字中有些字找不到可以顯示的字型，頁面上會出現方框，所以沒有套用。"
        + _UNCHANGED + "請改用其他字再試。"
    ),
    TextEditRefusal.GLYPHS_NOT_DRAWN: (
        "新文字中有些字沒有真正畫在頁面上，所以沒有套用。" + _UNCHANGED
        + "請改用其他字，或縮短文字後再試。"
    ),
    TextEditRefusal.TARGET_NOT_PRESENT: (
        "修改後在頁面上找不到新的文字，為避免內容遺失，已還原。" + _UNCHANGED
        + "請稍後再試，或縮短文字。"
    ),
    TextEditRefusal.UNTOUCHED_TEXT_WOULD_BE_LOST: (
        "這段文字和旁邊沒有要修改的文字疊在一起，若繼續會把旁邊的文字一起擦掉，所以沒有套用。"
        + _UNCHANGED + "請改編輯其他文字，或在旁邊新增文字框。"
    ),
    TextEditRefusal.DRAGGED_BOX_OVERPRINTS: (
        "新文字放在你拖曳到的位置，會蓋到旁邊沒有要修改的文字，所以沒有套用。" + _UNCHANGED
        + "你可以選「仍要放在這裡」照原位置放置（不限制大小，也不檢查是否蓋到旁邊的文字），"
        "或選「取消」後把文字框拖到沒有文字的地方。"
    ),
    TextEditRefusal.PROTECTED_SPAN_CHANGED: (
        "這行旁邊的文字在修改後無法完整保留，為避免弄壞版面，已還原。" + _UNCHANGED
        + "請改為只修改單一段文字，或在旁邊新增文字框。"
    ),
    TextEditRefusal.VERIFICATION_FAILED: (
        "修改後的文字和你輸入的內容差異太大，無法確認結果正確，已還原。" + _UNCHANGED
        + "請縮短文字或換一種寫法後再試。"
    ),
    TextEditRefusal.TEXT_STATE_NOT_REPRODUCIBLE: (
        "這段文字（或和它疊在一起的文字）使用了特殊的顯示方式，例如隱藏文字、圖層、"
        "特殊色彩、透明度或外框字，重建或移動後無法完整保留，所以沒有套用。" + _UNCHANGED
        + "請改編輯其他文字，或在旁邊新增文字框。"
    ),
    TextEditRefusal.ROLLBACK_FAILED: (
        "文字編輯失敗，而且這一頁無法自動還原，頁面可能已被部分改動。"
        "請關閉這個分頁（不儲存），再重新開啟原本的檔案；"
        "若要保留目前的內容，只能用「另存新檔」存成新的檔名。"
    ),
    TextEditRefusal.EDIT_FAILED: (
        "這次文字編輯發生未預期的問題，頁面已還原。" + _UNCHANGED
        + "請稍後再試，或換一種編輯方式。"
    ),
}

# Sentences whose advice depends on the path that raised the refusal.  The
# cross-page move asks its single consent BEFORE the model runs, so that
# prompt cannot carry the untouched-glyph acknowledgement and the source
# deletion replays a bare ``True`` (F12-DLG-3): "redo and confirm when
# prompted" would send the user round a loop that always ends in the same
# refusal.  Every other code reads the same on both paths.
_CROSS_PAGE_MOVE_MESSAGES: dict[TextEditRefusal, str] = {
    TextEditRefusal.UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED: (
        "這行文字含有無法辨識的符號，重建後無法保留，而跨頁移動的提示無法讓你確認這些符號，"
        "所以沒有套用。" + _UNCHANGED + "請先刪除這些符號，或改在同一頁內編輯這行文字"
        "（編輯時的提示會列出這些符號供你確認）。"
    ),
}


class UserFacingEditError(RuntimeError):
    """A controller-authored failure whose message is already a plain zh-TW
    sentence (no technical detail), e.g. the cross-page move's own aborts."""


def refusal_message(reason: object, *, cross_page_move: bool = False) -> str:
    """The zh-TW sentence for a refusal code (enum member or its string value).

    ``cross_page_move`` selects the cross-page move's own wording where the
    generic advice cannot work on that path (see ``_CROSS_PAGE_MOVE_MESSAGES``).
    An unknown or missing code falls back to the generic sentence."""
    try:
        code = TextEditRefusal(reason)
    except ValueError:
        return GENERIC_REFUSAL_MESSAGE
    if cross_page_move and code in _CROSS_PAGE_MOVE_MESSAGES:
        return _CROSS_PAGE_MOVE_MESSAGES[code]
    return _MESSAGES.get(code, GENERIC_REFUSAL_MESSAGE)


def user_message_for_exception(
    exc: BaseException,
    *,
    cross_page_move: bool = False,
    document_restored: bool | None = None,
) -> str:
    """The sentence to show for an exception raised by a text edit.

    A coded refusal gets its mapped sentence (the cross-page move's own where
    it differs), a ``UserFacingEditError`` its own (already plain) message,
    anything else the generic one.  The caller logs the technical detail
    (``log_edit_failure``).

    ``document_restored`` is for a caller that restores the WHOLE document
    itself after the failure (the cross-page move; F13-MOVE-1a), so its own
    outcome, not the model's inner rollback, decides whether the document can
    be trusted: ``False`` (that restore failed) always gets the
    ``ROLLBACK_FAILED`` do-not-save sentence, whatever the error was;
    ``True`` turns a ``ROLLBACK_FAILED`` into the "page restored" sentence
    (the model's rollback failed but the caller's restore repaired it).
    ``None`` (no caller restore) leaves the mapping untouched."""
    if document_restored is False:
        return refusal_message(TextEditRefusal.ROLLBACK_FAILED, cross_page_move=cross_page_move)
    if isinstance(exc, TextEditRefused):
        if document_restored and exc.reason == TextEditRefusal.ROLLBACK_FAILED:
            return refusal_message(TextEditRefusal.EDIT_FAILED, cross_page_move=cross_page_move)
        return refusal_message(exc.reason, cross_page_move=cross_page_move)
    if isinstance(exc, UserFacingEditError) and str(exc):
        return str(exc)
    return GENERIC_REFUSAL_MESSAGE


def user_message_for_history_failure(verb: str, exc: BaseException) -> str:
    """The sentence to show when an undo/redo step (``verb`` is ``復原`` or
    ``重做``) raised.  A coded refusal or ``UserFacingEditError`` keeps its own
    sentence (a redo may re-run a text edit); anything else gets a neutral one,
    because the command may not be a text edit at all and the document is not
    guaranteed unchanged.  Latin-free like every sentence here."""
    if isinstance(exc, (TextEditRefused, UserFacingEditError)):
        return user_message_for_exception(exc)
    return f"{verb}此步驟時發生未預期的問題。請先確認頁面內容，再決定是否儲存。"


def log_edit_failure(what: str, exc: BaseException) -> None:
    """Log the technical detail of a failed edit (the only place it goes)."""
    if isinstance(exc, TextEditRefused):
        logger.error("%s: reason=%s detail=%s", what, exc.reason.value, exc.detail)
    else:
        logger.error("%s: unmapped %s: %s", what, type(exc).__name__, exc)
