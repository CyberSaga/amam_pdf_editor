"""F14: a font name from PDF data stays inert in the htmlbox markup it is written into.

Every ``font-family`` value the app interpolates into ``insert_htmlbox`` HTML/CSS
goes through ``utils.text_chars.css_font_family``.  A name only reaches that markup
after ``_resolve_add_text_font`` / ``fitz.Font`` accepted it, and ``fitz.Font``
accepts any builtin name followed by a NUL (it reads a C string): a forged textbox
marker ``font`` of ``"Helvetica\\x00\";></span><p ...>"`` reaches ``_textbox_markup``
and ``_convert_text_to_html`` verbatim.  Unsanitized, that NUL empties the whole story
(MuPDF stops reading the markup there) and, with a resolution that returns names
verbatim (the finding's precondition), the ``";></span><p ...>`` part lays out an
extra paragraph.  The helper drops the characters that can end or escape the value
and leaves every other name byte-identical (the equivalence pins below were written
against the markup of the code before the fix).
"""

from __future__ import annotations

import ast
import html.parser
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import pdf_object_ops
from model.pdf_model import PDFModel
from utils import cjk_ext_b_font

REPO_ROOT = Path(__file__).resolve().parents[1]

INJECTED = "INJECTED"
# The finding's payload: closes the style attribute and opens a 30 pt paragraph.
BREAKOUT = f'helv;"></span><p style="font-size:30pt">{INJECTED}<span style="'
# The same payload behind a builtin name and a NUL: ``fitz.Font`` accepts it as
# "Helvetica", so ``_resolve_add_text_font`` returns it verbatim today.
NUL_SMUGGLED = "Helvetica\x00" + BREAKOUT
FORGED_NAMES = [
    BREAKOUT,
    NUL_SMUGGLED,
    "helv; color: red",
    "helv&#59; color: red",
    "helv' ; color: red",
    "helv} p { color: red",
    "helv\\",
    "url(x",
    "helv/* swallow",
    "helv/;* swallow",
    "helv\n; color: red",
]

# Names that cannot end or escape the value: every token the app itself emits,
# base-14 and builtin names, aliases, subset-tagged and real-world PDF names.
APP_TOKENS = [
    "helv", "cjk", "china-ts", "china-ss", "china-t", "china-s", "japan", "korea",
    "tiro", "tib", "tibo", "tiit", "cour", "cour-b", "cour-i", "cour-bi", "heit", "hebo",
    "microsoft jhenghei", "pmingliu", "dfkai-sb",
    "PdfEditorMicrosoftJhengHei", "PdfEditorPMingLiU", "PdfEditorDFKaiSB",
    "PdfEditorExtB-SimSun-0a1b2c3d", "PdfEditorExtB-MingLiU-ffffffff",
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Times-Roman", "Times-BoldItalic",
    "Courier-BoldOblique", "Symbol", "ZapfDingbats", "Noto Serif Regular",
]
REAL_WORLD_NAMES = [
    "ABCDEF+ArialMT", "ABCDEF+Arial-BoldMT", "Arial,Bold", "Arial, sans-serif",
    "Times New Roman", "TimesNewRomanPS-BoldItalicMT", "Font123", "F1", "CIDFont+F2",
    "MS Gothic", "Segoe UI Semibold", "Noto_Sans_CJK_TC", "Calibri.Light", "Foo#20Bar",
    "Wingdings 2", "A*B", "A/B", "*/", "50%", "Hello=World", "Mono:Regular", "@Font",
    "Font[1]", "Font!", "Font~1", "Font$", "Font^", "Font|Pipe", "Font`", "Font?",
    "微軟正黑體", "標楷體", "新細明體",
    "ＭＳ ゴシック", "맑은 고딕",
    "Café Sans", "Font NBSP",
]
BENIGN_NAMES = APP_TOKENS + REAL_WORLD_NAMES


class _MarkupProbe(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.styles: list[str] = []
        self.data: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for key, value in attrs:
            if key == "style":
                self.styles.append(value or "")

    def handle_data(self, data: str) -> None:
        self.data.append(data)


def _declarations(style: str) -> list[str]:
    return [decl.strip() for decl in style.split(";") if decl.strip()]


def _assert_inert(markup: str, *, app_properties: list[str]) -> None:
    """``markup`` holds only the app's own elements and declarations."""
    assert "\x00" not in markup
    probe = _MarkupProbe()
    probe.feed(markup)
    probe.close()
    assert set(probe.tags) <= {"span", "br"}, (probe.tags, markup)
    assert INJECTED not in "".join(probe.data), markup
    assert probe.styles, markup
    for style in probe.styles:
        names = [decl.split(":", 1)[0].strip() for decl in _declarations(style)]
        assert names == app_properties, (style, markup)
        family = _declarations(style)[0].split(":", 1)[1]
        assert not re.search(r"[\"'&<>;{}()\\]|/\*", family), (family, markup)


def _identity_resolution(model: PDFModel, monkeypatch: pytest.MonkeyPatch) -> None:
    """The finding's precondition: resolution hands the hint back verbatim."""
    monkeypatch.setattr(model, "_resolve_add_text_font", lambda hint: hint)


def _member_span(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, color=(1.0, 0.0, 0.0), bbox=fitz.Rect(0, 0, 10, 10))


def _drawn_spans(markup: str, css: str) -> list[tuple[str, float]]:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_htmlbox(fitz.Rect(10, 10, 390, 290), markup, css=css)
        return [
            (span["text"], round(float(span["size"]), 1))
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        ]
    finally:
        doc.close()


# ---------------------------------------------------------------- reachability


def test_nul_smuggled_name_survives_font_resolution() -> None:
    """Why the sites must sanitize: resolution itself lets the name through."""
    assert PDFModel()._resolve_add_text_font(NUL_SMUGGLED) == NUL_SMUGGLED


# ------------------------------------------------------- inert at every site


@pytest.mark.parametrize("forged", FORGED_NAMES)
def test_textbox_markup_keeps_a_forged_font_name_inert(forged: str) -> None:
    html_content, _css = pdf_object_ops._textbox_markup("hi", forged, 12.0, (0.0, 0.0, 0.0))
    _assert_inert(html_content, app_properties=["font-family"])


def test_textbox_markup_through_real_resolution_draws_the_text_only() -> None:
    """The forged marker path: ``payload["font"]`` -> ``_resolve_add_text_font`` ->
    ``_textbox_markup`` -> ``insert_htmlbox``.  Before the fix the NUL emptied the
    story (no "hi"); the forged paragraph is never laid out."""
    font_name = PDFModel()._resolve_add_text_font(NUL_SMUGGLED)
    html_content, css = pdf_object_ops._textbox_markup("hi", font_name, 12.0, (0.0, 0.0, 0.0))
    drawn = _drawn_spans(html_content, css)
    assert [text for text, _size in drawn] == ["hi"], drawn


def test_textbox_markup_with_verbatim_resolution_draws_no_injected_paragraph() -> None:
    html_content, css = pdf_object_ops._textbox_markup("hi", BREAKOUT, 12.0, (0.0, 0.0, 0.0))
    drawn = _drawn_spans(html_content, css)
    assert [text for text, _size in drawn] == ["hi"], drawn


@pytest.mark.parametrize("forged", FORGED_NAMES)
def test_convert_text_to_html_keeps_a_forged_font_name_inert(
    forged: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = PDFModel()
    _identity_resolution(model, monkeypatch)
    markup = model._convert_text_to_html("Ab 中文", 12.0, (0.0, 0.0, 0.0), latin_font=forged)
    _assert_inert(markup, app_properties=["font-family"])


def test_convert_text_to_html_through_real_resolution_is_inert() -> None:
    markup = PDFModel()._convert_text_to_html("Ab cd", 12.0, (0.0, 0.0, 0.0), latin_font=NUL_SMUGGLED)
    _assert_inert(markup, app_properties=["font-family"])


@pytest.mark.parametrize("forged", FORGED_NAMES)
def test_build_multi_style_html_keeps_a_forged_font_name_inert(
    forged: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = PDFModel()
    _identity_resolution(model, monkeypatch)
    markup = model._build_multi_style_html(
        "Ab 中文", [_member_span("Ab 中文")], (0.0, 0.0, 0.0), latin_font=forged
    )
    _assert_inert(markup, app_properties=["font-family", "color"])


def test_build_multi_style_html_through_real_resolution_is_inert() -> None:
    markup = PDFModel()._build_multi_style_html(
        "Ab cd", [_member_span("Ab cd")], (0.0, 0.0, 0.0), latin_font=NUL_SMUGGLED
    )
    _assert_inert(markup, app_properties=["font-family", "color"])


@pytest.mark.parametrize("forged", FORGED_NAMES)
def test_ext_b_wrap_keeps_a_forged_family_inert(forged: str) -> None:
    markup = cjk_ext_b_font._wrap_text_node("\U00020000", {0x20000: forged})
    _assert_inert(markup, app_properties=["font-family"])


class _StopRender(Exception):
    pass


def _preview_fallback_css(font_name: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """The CSS the model-less preview renderer hands to ``insert_htmlbox``."""
    from view import text_editing

    captured: list[str] = []

    def capture(markup: str, kwargs: dict, *, cached_only: bool = False):
        captured.append(kwargs["css"])
        raise _StopRender

    monkeypatch.setattr(text_editing, "htmlbox_args_with_ext_b", capture)
    renderer = text_editing.PreviewRenderer(model=None)
    with pytest.raises(_StopRender):
        renderer.render(
            text="hi",
            font_name=font_name,
            font_size=12.0,
            color=(0.0, 0.0, 0.0),
            member_spans=None,
            rect_pt=fitz.Rect(0, 0, 100, 20),
            rotation=0,
            render_scale=1.0,
        )
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize("forged", FORGED_NAMES)
def test_preview_fallback_css_keeps_a_forged_font_name_inert(
    forged: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    css = _preview_fallback_css(forged, monkeypatch)
    assert css.count("{") == 1 and css.count("}") == 1, css
    body = css[css.index("{") + 1 : css.rindex("}")]
    names = [decl.split(":", 1)[0].strip() for decl in _declarations(body)]
    assert names == ["font-family", "font-size", "color", "white-space"], css
    family = _declarations(body)[0].split(":", 1)[1]
    assert not re.search(r"[\"'&<>;{}()\\\x00-\x1f]|/\*", family), css


# ------------------------------------------------------------- the helper


@pytest.mark.parametrize("name", BENIGN_NAMES)
def test_css_font_family_leaves_a_benign_name_unchanged(name: str) -> None:
    from utils.text_chars import css_font_family

    assert css_font_family(name) == name


@pytest.mark.parametrize("ch", list("\"'&<>;{}()\\") + [chr(cp) for cp in (*range(0x20), *range(0x7F, 0xA0))])
def test_css_font_family_drops_every_breakout_character(ch: str) -> None:
    from utils.text_chars import css_font_family

    assert css_font_family(f"Ab{ch}Cd") == "AbCd"


def test_css_font_family_keeps_every_other_printable_ascii_character() -> None:
    from utils.text_chars import css_font_family

    unsafe = set("\"'&<>;{}()\\")
    for cp in range(0x20, 0x7F):
        ch = chr(cp)
        if ch not in unsafe:
            assert css_font_family(f"Ab{ch}Cd") == f"Ab{ch}Cd", ch


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a/*b", "a/b"),
        ("a/**b", "a/b"),
        ("a/*/*b", "a//b"),
        ("a/;*b", "a/b"),
        ("a/;**;*b", "a/b"),
        ("a*/b", "a*/b"),
        (BREAKOUT, "helv/spanp style=font-size:30ptINJECTEDspan style="),
        (NUL_SMUGGLED, "Helveticahelv/spanp style=font-size:30ptINJECTEDspan style="),
    ],
)
def test_css_font_family_neutralizes_comment_openers_and_payloads(name: str, expected: str) -> None:
    from utils.text_chars import css_font_family

    assert css_font_family(name) == expected
    assert css_font_family(expected) == expected  # idempotent


# ------------------------------------------- byte-identical for benign names
# The expected strings below are the templates of the code before the fix.


@pytest.mark.parametrize("name", BENIGN_NAMES)
def test_textbox_markup_is_unchanged_for_benign_names(name: str) -> None:
    html_content, css = pdf_object_ops._textbox_markup("a<b\nc", name, 12.5, (1.0, 0.0, 0.5))
    assert html_content == f'<span style="font-family: {name};">a&lt;b<br>c</span>'
    assert "font-family" not in css


@pytest.mark.parametrize("name", BENIGN_NAMES)
def test_convert_text_to_html_is_unchanged_for_benign_names(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = PDFModel()
    _identity_resolution(model, monkeypatch)
    latin = model._font_token_to_css_family(name)
    cjk = model._font_token_to_css_family(model._resolve_cjk_companion_font(name))
    markup = model._convert_text_to_html("Ab 中文\n-x", 12.0, (0.0, 0.0, 0.0), latin_font=name)
    assert markup == (
        f'<span style="font-family: {latin};">Ab</span>'
        f'<span style="font-family: {latin};"> </span>'
        f'<span style="font-family: {cjk};">中文</span>'
        "<br>"
        f'<span style="font-family: {latin};"><span style="white-space: nowrap;">-</span>x</span>'
    )


@pytest.mark.parametrize("name", BENIGN_NAMES)
def test_build_multi_style_html_is_unchanged_for_benign_names(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = PDFModel()
    _identity_resolution(model, monkeypatch)
    latin = model._font_token_to_css_family(name)
    cjk = model._font_token_to_css_family(model._resolve_cjk_companion_font(name))
    markup = model._build_multi_style_html(
        "Ab 中文", [_member_span("Ab 中文")], (0.0, 0.0, 0.0), latin_font=name
    )
    red = "color: rgb(255, 0, 0);"
    assert markup == (
        f'<span style="font-family: {latin}; {red}">Ab</span>'
        f'<span style="font-family: {latin}; {red}"> </span>'
        f'<span style="font-family: {cjk}; {red}">中文</span>'
    )


@pytest.mark.parametrize("name", BENIGN_NAMES)
def test_ext_b_wrap_is_unchanged_for_benign_names(name: str) -> None:
    markup = cjk_ext_b_font._wrap_text_node("a\U00020000b", {0x20000: name})
    assert markup == f'a<span style="font-family: {name};">\U00020000</span>b'


@pytest.mark.parametrize("name", ["helv", "Helvetica", "ABCDEF+ArialMT", "Times New Roman", "微軟正黑體"])
def test_preview_fallback_css_is_unchanged_for_benign_names(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import text_editing

    family = text_editing._alias_font_family(name)
    css = _preview_fallback_css(name, monkeypatch)
    assert css == (
        f"span {{ font-family: {family}; font-size: 12.0pt; "
        "color: rgb(0,0,0); white-space: pre-wrap; }"
    )


def test_frozen_markup_goldens() -> None:
    """Literal markup of the code before the fix, independent of any helper."""
    model = PDFModel()
    assert pdf_object_ops._textbox_markup("hi", "helv", 12.0, (0.0, 0.0, 0.0))[0] == (
        '<span style="font-family: helv;">hi</span>'
    )
    assert pdf_object_ops._textbox_markup("hi", "ABCDEF+ArialMT", 12.0, (0.0, 0.0, 0.0))[0] == (
        '<span style="font-family: ABCDEF+ArialMT;">hi</span>'
    )
    assert model._convert_text_to_html("中文ABC", 12, (0.0, 0.0, 0.0), latin_font="tiro") == (
        '<span style="font-family: china-ts;">中文</span>'
        '<span style="font-family: tiro;">ABC</span>'
    )
    assert model._convert_text_to_html("A b", 12, (0.0, 0.0, 0.0), latin_font="dfkai") == (
        '<span style="font-family: PdfEditorDFKaiSB;">A</span>'
        '<span style="font-family: PdfEditorDFKaiSB;"> </span>'
        '<span style="font-family: PdfEditorDFKaiSB;">b</span>'
    )


# ------------------------------------------------------------------ guard


_FAMILY_SLOT = re.compile(r'font-family:\s*"?$')


def _family_slots(tree: ast.AST) -> list[ast.FormattedValue]:
    slots: list[ast.FormattedValue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for before, after in zip(node.values, node.values[1:]):
            if (
                isinstance(before, ast.Constant)
                and isinstance(before.value, str)
                and _FAMILY_SLOT.search(before.value)
                and isinstance(after, ast.FormattedValue)
            ):
                slots.append(after)
    return slots


def test_every_interpolated_font_family_goes_through_the_helper() -> None:
    """Chokepoint guard: no f-string in the app writes ``font-family: {x}`` raw."""
    found = 0
    offenders: list[str] = []
    for package in ("model", "utils", "view", "controller", "src"):
        root = REPO_ROOT / package
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for slot in _family_slots(tree):
                found += 1
                call = slot.value
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "css_font_family"
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{slot.lineno}")
    assert found >= 11, found  # the sites known when F14 was fixed
    assert not offenders, offenders
