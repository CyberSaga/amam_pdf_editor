"""model.page_content_text: page-content extraction that ignores annotation and
widget appearances (F11-ANN-4)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.page_content_text import content_text, content_textpage  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model import pdf_text_edit  # noqa: E402

FT = "FT comment"
FIELD = "FieldValue"


def _doc(*, rotation: int = 0, cropbox: bool = False, annots: bool = False) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 60), "Hello World Example Text", fontsize=14, fontname="helv")
    page.insert_text((50, 100), "Second line of body text", fontsize=12, fontname="helv")
    page.insert_text((60, 140), "  padded   spaces  ", fontsize=12, fontname="helv")
    if annots:
        page.add_freetext_annot(fitz.Rect(50, 200, 200, 230), FT, fontsize=11).update()
        widget = fitz.Widget()
        widget.field_name = "f1"
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = FIELD
        widget.rect = fitz.Rect(50, 260, 200, 280)
        page.add_widget(widget)
    if cropbox:
        page.set_cropbox(fitz.Rect(20, 30, 350, 380))
    if rotation:
        page.set_rotation(rotation)
    return doc


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropbox", [False, True])
def test_content_text_equals_get_text_on_a_page_without_annotations(rotation: int, cropbox: bool) -> None:
    doc = _doc(rotation=rotation, cropbox=cropbox)
    try:
        page = doc[0]
        for option in ("dict", "rawdict", "text"):
            assert content_text(page, option) == page.get_text(option), option
        assert content_text(page, "dict", flags=0) == page.get_text("dict", flags=0)
        assert content_text(page, "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE) == page.get_text(
            "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE
        )
        clip = fitz.Rect(0, 0, 400, 110)
        assert content_text(page, "text", clip=clip) == page.get_text("text", clip=clip)
        assert page.rotation == rotation  # the temporary derotation is undone
    finally:
        doc.close()


HVAC_FIXTURE = ROOT / "test_files" / "hvac-dwg.pdf"


@pytest.mark.skipif(not HVAC_FIXTURE.exists(), reason="real-document fixture missing")
def test_content_text_equals_get_text_on_a_real_document() -> None:
    """A display-list based extraction differed on pages 1-3 of this file
    (regrouped text objects change line/space segmentation); the content text
    must be exactly what ``get_text`` returns on every annotation-free page."""
    doc = fitz.open(str(HVAC_FIXTURE))
    try:
        for index in (0, 1, 2, 3, 17):
            page = doc[index]
            if index < 3 or not list(page.annots()):
                assert content_text(page, "rawdict", flags=0) == page.get_text("rawdict", flags=0), index
                assert content_text(page, "dict", flags=0) == page.get_text("dict", flags=0), index
                assert content_text(page, "text") == page.get_text("text"), index
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_content_text_skips_freetext_and_widget_appearance_text(rotation: int) -> None:
    doc = _doc(rotation=rotation, annots=True)
    try:
        page = doc[0]
        assert FT in page.get_text() and FIELD in page.get_text()  # fixture sanity
        for option in ("text", "dict", "rawdict"):
            blob = repr(content_text(page, option))
            assert FT not in blob and FIELD not in blob, option
            assert "Hello" in blob
        assert FT not in content_text(page, "text", clip=fitz.Rect(0, 150, 400, 400))
        assert [a.type[1] for a in page.annots()] == ["FreeText"]  # nothing was removed
        assert page.rotation == rotation
        # one interpretation serves several extractions
        textpage = content_textpage(page, 0)
        first = content_text(page, "dict", textpage=textpage)
        second = content_text(page, "rawdict", textpage=textpage)
        assert FT not in repr(first) and FT not in repr(second)
    finally:
        doc.close()


def test_content_text_rejects_unsupported_requests() -> None:
    doc = _doc()
    try:
        page = doc[0]
        with pytest.raises(ValueError):
            content_text(page, "html")
        with pytest.raises(ValueError):
            content_text(page, "dict", clip=fitz.Rect(0, 0, 10, 10))
    finally:
        doc.close()


def test_an_annotation_body_is_not_a_clickable_text_target(tmp_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World Example Text", fontsize=12, fontname="helv")
    freetext_rect = fitz.Rect(72, 400, 220, 424)
    page.add_freetext_annot(freetext_rect, FT, fontsize=9).update()
    path = tmp_path / "ft_target.pdf"
    doc.save(str(path))
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    model.ensure_page_index_built(1)
    try:
        assert model.block_manager.find_by_rect(0, freetext_rect, doc=model.doc) is None
        page = model.doc[0]
        contents_before = page.read_contents()
        result = model.edit_text(1, freetext_rect, "FT changed", original_text=FT)
        assert result is EditTextResult.TARGET_BLOCK_NOT_FOUND
        page = model.doc[0]
        assert page.read_contents() == contents_before
        assert [(a.type[1], a.info.get("content")) for a in page.annots()] == [("FreeText", FT)]
    finally:
        model.close()


_EDIT_MODULES = (
    "model/text_block.py",
    "model/text_block_parsing.py",
    "model/pdf_text_edit.py",
    "model/pdf_model.py",
    "model/pdf_object_ops.py",
    "model/tools/annotation_tool.py",
)
# Visible-text reads that are deliberately NOT content-only (inserted-text
# verification and selection copy describe what the user sees).
_VISIBLE_TEXT_ALLOWED = {
    # _htmlbox_reference renders the htmlbox markup on a throwaway ``fitz.open()``
    # page that only ever holds that one insert: no annotation or widget can be on
    # it, so ``get_text("text")`` there IS the content text (pinned by
    # ``test_htmlbox_reference_scratch_page_never_carries_annotations`` below).
    ("model/pdf_text_edit.py", "return _HtmlboxReference(page.get_text(\"text\"), glyphs, notdef)"),
    ("model/pdf_text_edit.py", "full_page_text = page.get_text(\"text\")"),
    ("model/pdf_text_edit.py", "clipped = page.get_text(\"text\", clip=clamp_rect_to_page(new_layout_rect, page_rect))"),
    ("model/pdf_model.py", "extracted = page.get_text(\"text\", clip=rect)"),
    ("model/pdf_model.py", "text = (page.get_text(\"text\", clip=clipped_unrotated, sort=True) or \"\").strip()"),
}


def test_edit_pipeline_extracts_structure_only_through_the_content_helper() -> None:
    """Bug-class guard: no edit-pipeline module may read dict/rawdict (or any
    other page text) straight from ``page.get_text`` -- that includes
    annotation appearance text.  Use ``model.page_content_text.content_text``."""
    offenders: list[str] = []
    for rel in _EDIT_MODULES:
        for lineno, raw in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            code = raw.split("#", 1)[0].strip()
            if not re.search(r"\.get_text\(", code) or code.startswith(("def ", '"', "'")):
                continue
            if '"""' in code or "``" in code:
                continue
            if "original_get_text" in code or "_compat_get_text" in code:
                continue
            if (rel, code) in _VISIBLE_TEXT_ALLOWED:
                continue
            offenders.append(f"{rel}:{lineno}: {code}")
    assert not offenders, "\n".join(offenders)


def test_htmlbox_reference_scratch_page_never_carries_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``_VISIBLE_TEXT_ALLOWED`` entry for ``_htmlbox_reference`` is justified
    only while its scratch page holds nothing but the htmlbox insert: even markup
    with a link and a form-looking tag leaves no annotation or widget behind."""
    seen: list[tuple[int, int, int]] = []
    real = pdf_text_edit.insert_htmlbox_tracked

    def spy(page: fitz.Page, *args: object, **kwargs: object) -> tuple[float, float]:
        result = real(page, *args, **kwargs)
        seen.append((len(list(page.annots())), len(list(page.widgets())), len(page.get_links())))
        return result

    monkeypatch.setattr(pdf_text_edit, "insert_htmlbox_tracked", spy)
    html = '<p>Hello <a href="https://example.com">link</a> <input value="FieldValue"> world</p>'
    reference = pdf_text_edit._htmlbox_reference(html, "p { font-size: 12pt; }", 300.0)
    assert len(seen) == 1
    assert seen[0][:2] == (0, 0)
    assert "Hello" in reference.text
