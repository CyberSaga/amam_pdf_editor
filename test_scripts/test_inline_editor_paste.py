"""F16-PASTE-2: what the inline text editor takes from the clipboard.

``InlineTextEditor`` is a ``QTextEdit`` and used to keep its default rich-text paste.
An ``<img>`` inside pasted browser / Word HTML became an image object, ``toPlainText()``
read it as U+FFFC, and the commit drew a dashed "OBJ" box in the PDF.  The editor now
pastes plain text only and drops U+FFFC (an inline-object anchor, never text).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData  # noqa: E402

from model.text_normalization import strip_unrenderable_controls  # noqa: E402
from utils.text_chars import count_unrenderable  # noqa: E402
from view.text_editing import (  # noqa: E402
    InlineTextEditor,
    PreviewBackedInlineTextEditor,
    paste_cleaned_notice,
)

_PIXEL_GIF = (
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
_EDITORS = [
    pytest.param(InlineTextEditor, id="inline"),
    pytest.param(lambda: PreviewBackedInlineTextEditor(""), id="preview_backed"),
]


def _mime(*, text: str | None = None, html: str | None = None) -> QMimeData:
    mime = QMimeData()
    if text is not None:
        mime.setText(text)
    if html is not None:
        mime.setHtml(html)
    return mime


def _paste(editor, mime: QMimeData) -> str:
    editor.insertFromMimeData(mime)
    return editor.toPlainText()


@pytest.mark.parametrize("make", _EDITORS)
def test_pasted_html_with_an_image_leaves_no_object_anchor(qapp, make) -> None:
    editor = make()
    text = _paste(editor, _mime(html=f'<p>Hi <img src="{_PIXEL_GIF}" width="8" height="8"> X</p>'))
    assert "\ufffc" not in text, ascii(text)
    assert text.replace(" ", "") == "HiX", ascii(text)


@pytest.mark.parametrize("make", _EDITORS)
def test_pasted_plain_text_loses_the_object_anchor_and_keeps_the_rest(qapp, make) -> None:
    editor = make()
    assert _paste(editor, _mime(text="Hi \ufffc X\nsecond\tline")) == "Hi  X\nsecond\tline"


@pytest.mark.parametrize("make", _EDITORS)
def test_pasting_only_an_image_inserts_nothing(qapp, make) -> None:
    editor = make()
    editor.setPlainText("keep")
    assert _paste(editor, _mime(html=f'<img src="{_PIXEL_GIF}">')) == "keep"


@pytest.mark.parametrize("make", _EDITORS)
def test_pasted_rich_text_arrives_as_plain_text_at_the_cursor(qapp, make) -> None:
    editor = make()
    editor.setPlainText("ab")
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    assert _paste(editor, _mime(html="<b>bold</b> <i>it</i>")) == "abold itb"


# ---- S17-PASTE-NOTICE: the editor says what a paste cleaned out ----------------------------------------
#
# Owner decision (2026-10-12): keep stripping control characters / dropping pasted images, and tell the
# user in the status bar (zh-TW) what was removed; a clean paste says nothing.  The editor reports through
# ``paste_cleaned(controls_removed, images_dropped)``; the View (TextEditManager) shows the message.


def _collect_paste_reports(editor) -> list[tuple[int, int]]:
    reports: list[tuple[int, int]] = []
    editor.paste_cleaned.connect(lambda controls, images: reports.append((controls, images)))
    return reports


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


@pytest.mark.parametrize("make", _EDITORS)
def test_pasted_control_characters_are_removed_and_reported(qapp, make) -> None:
    editor = make()
    reports = _collect_paste_reports(editor)
    assert _paste(editor, _mime(text="Hi\x07 X\x00Y")) == "Hi XY"
    assert reports == [(2, 0)]


@pytest.mark.parametrize("make", _EDITORS)
def test_a_pasted_image_is_reported_with_its_count(qapp, make) -> None:
    editor = make()
    reports = _collect_paste_reports(editor)
    _paste(editor, _mime(html=f'<p>Hi <img src="{_PIXEL_GIF}" width="8" height="8"> X <img src="{_PIXEL_GIF}"></p>'))
    assert reports == [(0, 2)]


@pytest.mark.parametrize("make", _EDITORS)
def test_an_image_next_to_plain_text_on_the_clipboard_is_still_reported(qapp, make) -> None:
    """A browser copy carries text/plain (no image in it) AND text/html (with the image)."""
    editor = make()
    reports = _collect_paste_reports(editor)
    mime = _mime(text="Hi X", html=f'<p>Hi <img src="{_PIXEL_GIF}"> X</p>')
    assert _paste(editor, mime) == "Hi X"
    assert reports == [(0, 1)]


@pytest.mark.parametrize("make", _EDITORS)
def test_controls_and_images_in_one_paste_make_one_report(qapp, make) -> None:
    editor = make()
    reports = _collect_paste_reports(editor)
    assert _paste(editor, _mime(text="a\x01b\ufffcc")) == "abc"
    assert reports == [(1, 1)]


@pytest.mark.parametrize("make", _EDITORS)
def test_a_clean_paste_reports_nothing(qapp, make) -> None:
    editor = make()
    reports = _collect_paste_reports(editor)
    assert "second\tline" in _paste(editor, _mime(text="Line one\r\nsecond\tline \u4e2d\u6587"))
    assert reports == [], "CR LF, tab and CJK are text, not something the paste removed"


@pytest.mark.parametrize("make", _EDITORS)
def test_a_paste_of_only_controls_inserts_nothing_and_still_reports(qapp, make) -> None:
    editor = make()
    editor.setPlainText("keep")
    reports = _collect_paste_reports(editor)
    assert _paste(editor, _mime(text="\x07\x08")) == "keep"
    assert reports == [(2, 0)]


def test_paste_notice_text_names_what_was_removed_in_zh_tw() -> None:
    controls = paste_cleaned_notice(3, 0)
    images = paste_cleaned_notice(0, 2)
    both = paste_cleaned_notice(3, 2)
    assert paste_cleaned_notice(0, 0) is None
    for message in (controls, images, both):
        assert message and _has_cjk(message)
    assert "3" in controls and "2" not in controls
    assert "2" in images and "3" not in images
    assert "3" in both and "2" in both
    assert len({controls, images, both}) == 3


def test_the_view_and_the_model_share_one_unrenderable_definition() -> None:
    sample = "a\x00b\x0bc\x7fd\x85e\ufdd0f\U0001fffeg\ufffch\r\ni"
    controls, images = count_unrenderable(sample)
    assert (controls, images) == (6, 1)
    assert len(strip_unrenderable_controls(sample)) == len(sample) - controls - images - 1  # CR LF folds
