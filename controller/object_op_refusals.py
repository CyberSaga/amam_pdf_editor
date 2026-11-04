"""Plain Traditional Chinese messages for refused object operations (D-OLD-MARKERS).

Owner decision after adversarial round 15: a Move / Resize / Rotate / Delete of an
object that still refuses after the marker repair is never silent.  The Model records
an ``ObjectOpRefused`` (code, object kind, object id) on
``PDFModel.last_object_op_refusal``; this module turns it into ONE short sentence that
says which object could not be changed and why, in user terms.  A batch that partly
refuses says how many objects were not changed.

The sentences contain no Latin letters (a test pins it) and never quote document
content (P0-C privacy contract).
"""
from __future__ import annotations

from model.object_op_refusal import ObjectOpRefusal, ObjectOpRefused

_UNCHANGED = "文件沒有被改動。"

REASON_SENTENCES: dict[ObjectOpRefusal, str] = {
    ObjectOpRefusal.OBJECT_NOT_FOUND: "頁面上已經找不到它，可能已被刪除或頁面已經變動。請重新選取後再試。",
    ObjectOpRefusal.IMAGE_NOT_LOCATED: (
        "程式無法確定它在頁面上畫在哪裡（常見於舊版程式儲存的檔案，或同一位置疊著相同的圖片），"
        "為避免改到別的圖片而停止。"
    ),
    ObjectOpRefusal.TEXTBOX_TEXT_CHANGED: (
        "框內的文字在建立之後被改過，程式無法確定框內現在的內容，若繼續可能會把舊的文字放回去。"
    ),
    ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT: "它底下有不屬於它的頁面文字，若繼續會把那些文字一起擦掉。",
    ObjectOpRefusal.NOT_SUPPORTED: "這個物件不支援這項操作。",
    ObjectOpRefusal.OPERATION_FAILED: "處理時發生未預期的問題，請稍後再試。",
}

_VERBS: dict[str, str] = {
    "move": "移動",
    "resize": "調整大小",
    "rotate": "旋轉",
    "delete": "刪除",
}

# (this-object phrase, one-object phrase, bare noun) per object kind.
_KINDS: dict[str, tuple[str, str, str]] = {
    "textbox": ("這個文字框", "一個文字框", "文字框"),
    "image": ("這張圖片", "一張圖片", "圖片"),
    "native_image": ("這張圖片", "一張圖片", "圖片"),
    "rect": ("這個矩形", "一個矩形", "矩形"),
}
_ANY_KIND = ("這個物件", "一個物件", "物件")


def _kind(kind: str | None) -> tuple[str, str, str]:
    return _KINDS.get(str(kind or ""), _ANY_KIND)


def _verb(verb: str) -> str:
    return _VERBS.get(verb, "變更")


def _reason(refusal: ObjectOpRefused | None) -> ObjectOpRefusal:
    if refusal is None:
        return ObjectOpRefusal.OPERATION_FAILED
    try:
        return ObjectOpRefusal(refusal.reason)
    except ValueError:
        return ObjectOpRefusal.OPERATION_FAILED


def _object_kind(refusal: ObjectOpRefused | None) -> str | None:
    return None if refusal is None else refusal.object_kind


def object_refusal_message(
    verb: str, refusal: ObjectOpRefused | None, *, object_kind: str | None = None
) -> str:
    """The sentence for one refused ``verb`` (``move``/``resize``/``rotate``/``delete``).

    ``object_kind`` names the object when the refusal does not (a model that recorded
    no code); an unknown code gets the generic reason."""
    this_object = _kind(_object_kind(refusal) or object_kind)[0]
    return f"{this_object}無法{_verb(verb)}：{REASON_SENTENCES[_reason(refusal)]}{_UNCHANGED}"


def _reasons_text(refusals: list[ObjectOpRefused | None]) -> str:
    """Each distinct (kind, reason) once, in the order first met."""
    seen: list[tuple[str, ObjectOpRefusal]] = []
    for refusal in refusals:
        key = (_kind(_object_kind(refusal))[2], _reason(refusal))
        if key not in seen:
            seen.append(key)
    return "".join(f"{noun}：{REASON_SENTENCES[reason]}" for noun, reason in seen)


def batch_refusal_message(verb: str, total: int, refusals: list[ObjectOpRefused | None]) -> str:
    """The sentence for a batch of ``total`` objects of which ``refusals`` did not change
    (the others did)."""
    refused = len(refusals)
    action = _verb(verb)
    if refused >= total:
        return f"選取的 {total} 個物件都無法{action}。原因：{_reasons_text(refusals)}{_UNCHANGED}"
    return (
        f"選取的 {total} 個物件中，有 {refused} 個無法{action}，其餘已{action}。"
        f"原因：{_reasons_text(refusals)}"
    )


def atomic_delete_refusal_message(total: int, refusal: ObjectOpRefused | None) -> str:
    """The sentence for a batch delete that was rolled back because one object refused:
    none of the ``total`` objects was deleted."""
    one_object = _kind(_object_kind(refusal))[1]
    return (
        f"選取的 {total} 個物件都沒有刪除，因為其中有{one_object}無法刪除："
        f"{REASON_SENTENCES[_reason(refusal)]}{_UNCHANGED}"
    )
