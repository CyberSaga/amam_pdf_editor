"""EXTB-SUBSET: CJK Ext-B characters drawn through htmlbox with an in-memory
subset of a Windows Ext-B font (owner decision C on OD-UNI1-COMMIT, round 11).

htmlbox (PyMuPDF 1.27) has no font for U+20000 and up and draws .notdef.  The
fix: ``utils.cjk_ext_b_font`` subsets SimSun-ExtB (``simsunb.ttf``; MingLiU-ExtB
``mingliub.ttc`` as the fallback) with fontTools to only the needed glyphs, and
``model.font_stream_compaction.insert_htmlbox_tracked`` -- the one htmlbox
chokepoint -- wraps Ext-B runs of the markup in their own span, adds the
``@font-face`` rule and passes the subset through an in-memory archive.

The end-to-end rebuild contract (commit, glyphs drawn, save/reopen, file size,
font-missing refusal) is in ``test_edit_text_helpers.py``; this module pins the
helper and the chokepoint.  Tests that need the real Windows fonts skip where
they are not installed; the font-missing paths monkeypatch the lookup and run
everywhere.
"""
from __future__ import annotations

import ast
import html as html_mod
import io
import logging
import sys
import threading
import time
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXT_B_TEXT = "\U00020000\U00020B9F\U0002A6D6"


def _module():
    from utils import cjk_ext_b_font

    return cjk_ext_b_font


def _require_fonts():
    fonts = _module().find_ext_b_fonts()
    if not fonts:
        pytest.skip("no Windows CJK Ext-B font installed (simsunb.ttf / mingliub.ttc)")
    return fonts


def _ttfont(data: bytes):
    from fontTools.ttLib import TTFont

    return TTFont(io.BytesIO(data))


def test_is_ext_b_range_boundaries() -> None:
    mod = _module()
    assert not mod.is_ext_b("\U0001FFFF")
    assert not mod.is_ext_b("中")
    assert not mod.is_ext_b("\U0001F600")
    assert mod.is_ext_b("\U00020000")
    assert mod.is_ext_b("\U0002A6DF")
    assert mod.is_ext_b("\U0002F825")  # compatibility supplement (plane 2)
    assert mod.is_ext_b("\U00030000")  # Ext-G (plane 3)
    assert not mod.is_ext_b("\U00040000")
    with pytest.raises(TypeError):
        mod.is_ext_b(0x20000)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mod.is_ext_b("ab")


@pytest.mark.parametrize("html", ["", "<span>abc</span>", "<span>中\U0001F600</span>", "<br>"])
def test_markup_without_ext_b_is_left_alone(html: str) -> None:
    assert _module().ext_b_htmlbox_resources(html) is None


def test_resources_reject_non_string_markup() -> None:
    with pytest.raises(TypeError):
        _module().ext_b_htmlbox_resources(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _module().ext_b_htmlbox_resources(b"<span>x</span>")  # type: ignore[arg-type]


def test_find_ext_b_fonts_is_empty_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _module()
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.find_ext_b_fonts() == ()


def test_find_ext_b_fonts_is_empty_when_the_files_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _module()
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # not this machine's per-user fonts
    assert mod.find_ext_b_fonts() == ()


def _fake_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A Windows with an empty system Fonts folder and an empty per-user one
    (Windows 10 1809+ installs a font without admin rights into
    ``%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts``).  Returns both folders."""
    mod = _module()
    monkeypatch.setattr(mod.sys, "platform", "win32")
    system = tmp_path / "windir" / "Fonts"
    per_user = tmp_path / "localappdata" / "Microsoft" / "Windows" / "Fonts"
    system.mkdir(parents=True)
    per_user.mkdir(parents=True)
    monkeypatch.setenv("WINDIR", str(tmp_path / "windir"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    return system, per_user


def test_per_user_installed_ext_b_font_is_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F13-ENV-2: the default Windows install (double-click > Install, no admin)
    puts the font in the per-user folder; the lookup must see it."""
    mod = _module()
    _system, per_user = _fake_windows(monkeypatch, tmp_path)
    (per_user / "simsunb.ttf").write_bytes(b"x")
    fonts = mod.find_ext_b_fonts()
    assert [f.path.name for f in fonts] == ["simsunb.ttf"]
    assert fonts[0].path.parent == per_user
    assert fonts[0].key == "SimSun" and fonts[0].font_number == 0


def test_per_user_font_means_installing_would_not_help(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The install advice must not be shown once the user has installed the font
    the default way (F12-DLG-4 rule: advise only where the action can work)."""
    mod = _module()
    _system, per_user = _fake_windows(monkeypatch, tmp_path)
    assert mod.ext_b_install_would_help() is True
    (per_user / "mingliub.ttc").write_bytes(b"x")
    assert mod.ext_b_install_would_help() is False


def test_system_font_wins_over_a_per_user_copy_and_candidate_order_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _module()
    system, per_user = _fake_windows(monkeypatch, tmp_path)
    (system / "simsunb.ttf").write_bytes(b"system")
    (per_user / "simsunb.ttf").write_bytes(b"user")  # same name: one entry, system's
    (per_user / "mingliub.ttc").write_bytes(b"user")
    fonts = mod.find_ext_b_fonts()
    assert [f.key for f in fonts] == ["SimSun", "MingLiU"]  # one per candidate
    assert fonts[0].path == system / "simsunb.ttf"
    assert fonts[1].path == per_user / "mingliub.ttc"


def test_per_user_lookup_survives_a_missing_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _module()
    system, _per_user = _fake_windows(monkeypatch, tmp_path)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert mod.find_ext_b_fonts() == ()
    (system / "simsunb.ttf").write_bytes(b"x")
    assert [f.path.name for f in mod.find_ext_b_fonts()] == ["simsunb.ttf"]


def test_per_user_font_is_ignored_off_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _module()
    _system, per_user = _fake_windows(monkeypatch, tmp_path)
    (per_user / "simsunb.ttf").write_bytes(b"x")
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.find_ext_b_fonts() == ()
    assert mod.ext_b_install_would_help() is False


def test_missing_font_leaves_markup_unchanged_and_reports_uncovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _module()
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: ())
    assert mod.ext_b_htmlbox_resources(f"<span>A{EXT_B_TEXT}</span>") is None
    assert mod.uncovered_ext_b(f"A{EXT_B_TEXT}B") == ["U+20000", "U+20B9F", "U+2A6D6"]
    assert mod.uncovered_ext_b("") == []
    assert mod.uncovered_ext_b("plain 中") == []


def test_unreadable_font_file_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A corrupt font file is treated as missing: nothing wrapped, no
    exception, the characters reported uncovered (the rebuild then refuses)."""
    mod = _module()
    bad = tmp_path / "simsunb.ttf"
    bad.write_bytes(b"not a font at all" * 10)
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: (mod.ExtBFont(bad, 0, "SimSun"),))
    assert mod.ext_b_htmlbox_resources("<span>\U00020000</span>") is None
    assert mod.uncovered_ext_b("\U00020000") == ["U+20000"]


def test_resources_wrap_ext_b_runs_with_a_small_subset_font() -> None:
    _require_fonts()
    mod = _module()
    html = f'<span style="font-family: helv;">A{EXT_B_TEXT}b \U00020000</span>'
    res = mod.ext_b_htmlbox_resources(html)
    assert res is not None
    # Only the text nodes changed; the original tags are all still there.
    assert res.html.startswith('<span style="font-family: helv;">A<span style="font-family: ')
    assert res.html.count("<span") == 3 and res.html.count("</span>") == 3
    assert "b " in res.html
    assert len(res.members) == 1
    member_name, data = res.members[0]
    family = member_name.rsplit(".", 1)[0]
    assert f'"{family}"' in res.css and f"url({member_name})" in res.css
    assert family.startswith(mod.FONT_NAME_PREFIX)
    # MuPDF keeps 31 characters of a font name; the sentinel must survive.
    assert len(family) <= 31
    assert len(data) < 16 * 1024, len(data)
    font = _ttfont(data)
    assert font["name"].getDebugName(6) == family
    assert sorted(font.getBestCmap()) == sorted({ord(c) for c in EXT_B_TEXT})
    assert "meta" not in font
    # Deterministic: same characters, same bytes and name; others differ.
    again = mod.ext_b_htmlbox_resources(html)
    assert again is not None and again.members == res.members and again.html == res.html
    other = mod.ext_b_htmlbox_resources("<span>\U00020000</span>")
    assert other is not None and other.members[0][0] != member_name


def test_resources_skip_tags_and_attributes() -> None:
    """Wrapping happens in text nodes only, never inside a tag."""
    _require_fonts()
    mod = _module()
    html = '<span title="\U00020000">x</span>'
    assert mod.ext_b_htmlbox_resources(html) is None


def test_uncovered_ext_b_names_characters_no_installed_font_has() -> None:
    _require_fonts()
    mod = _module()
    assert mod.uncovered_ext_b(EXT_B_TEXT) == []
    # Plane 3 (Ext-G) is beyond both Windows fonts.
    assert mod.uncovered_ext_b("\U00020000\U00030000") == ["U+30000"]
    res = mod.ext_b_htmlbox_resources("<span>\U00020000\U00030000</span>")
    assert res is not None
    assert "\U00030000</span>" in res.html  # left unwrapped -> .notdef -> refusal


def test_per_character_fallback_to_the_second_font(monkeypatch: pytest.MonkeyPatch) -> None:
    """A character the first font lacks is drawn from the next one."""
    fonts = _require_fonts()
    mod = _module()
    mingliu = [f for f in fonts if f.key == "MingLiU"]
    simsun = [f for f in fonts if f.key == "SimSun"]
    if not (mingliu and simsun):
        pytest.skip("needs both SimSun-ExtB and MingLiU-ExtB")
    # U+2F825 is in MingLiU-ExtB only.
    res = mod.ext_b_htmlbox_resources("<span>\U00020000\U0002F825</span>")
    assert res is not None
    assert len(res.members) == 2
    names = sorted(name for name, _data in res.members)
    assert any("MingLiU" in n for n in names) and any("SimSun" in n for n in names)


def test_chokepoint_draws_ext_b_with_the_subset_font() -> None:
    _require_fonts()
    mod = _module()
    from model.font_stream_compaction import insert_htmlbox_tracked

    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=200)
        insert_htmlbox_tracked(
            page,
            fitz.Rect(20, 20, 380, 180),
            f"<span>A{EXT_B_TEXT}</span>",
            css="span { font-size: 20pt; }",
            scratch=True,
        )
        ext_b = [
            (span["font"], ch[1])
            for span in page.get_texttrace()
            for ch in span["chars"]
            if str(span["font"]).startswith(mod.FONT_NAME_PREFIX)
        ]
        assert len(ext_b) == 3 and all(gid != 0 for _f, gid in ext_b), ext_b
        notdef = [ch for span in page.get_texttrace() for ch in span["chars"] if ch[1] == 0]
        assert not notdef
    finally:
        doc.close()


def test_chokepoint_without_a_font_still_draws_notdef(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _module()
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: ())
    from model.font_stream_compaction import insert_htmlbox_tracked

    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=200)
        insert_htmlbox_tracked(
            page, fitz.Rect(20, 20, 380, 180), "<span>\U00020000</span>", scratch=True
        )
        gids = [ch[1] for span in page.get_texttrace() for ch in span["chars"]]
        assert gids == [0]
    finally:
        doc.close()


def test_refusal_reason_names_the_fonts(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _module()
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: ())
    reason = mod.ext_b_refusal_reason("a\U00020000b")
    assert reason is not None
    for needle in ("CJK Ext-B", "simsunb.ttf", "mingliub.ttc", "neither is installed", "U+20000"):
        assert needle in reason, reason
    assert mod.ext_b_refusal_reason("") is None
    assert mod.ext_b_refusal_reason("plain \U0001F600") is None


def test_refusal_reason_for_a_character_the_installed_fonts_lack() -> None:
    _require_fonts()
    mod = _module()
    assert mod.ext_b_refusal_reason(EXT_B_TEXT) is None
    reason = mod.ext_b_refusal_reason("\U00020000\U00030000")
    assert reason is not None
    assert "have no glyph for U+30000" in reason and "neither is installed" not in reason
    assert "U+20000" not in reason


# ------------------------------------------- S12-EXTB-PREVIEW: the live preview


def _image_bytes(image) -> bytes:
    return bytes(image.constBits())[: image.sizeInBytes()]


def _preview_vs_commit(text: str, tmp_size: tuple[float, float] = (160.0, 40.0)):
    """The editor's live preview raster vs the commit chokepoint's raster for
    the same CSS/HTML on a page of the same size (model-free builders)."""
    from model.font_stream_compaction import insert_htmlbox_tracked
    from view.text_editing import PreviewRenderer

    width, height = tmp_size
    renderer = PreviewRenderer()  # model=None: the metrics-equivalent builders
    image = renderer.render(
        text=text,
        font_name="helv",
        font_size=20.0,
        color=(0.0, 0.0, 0.0),
        member_spans=None,
        rect_pt=fitz.Rect(0, 0, width, height),
        rotation=0,
        render_scale=1.0,
    )
    preview = _image_bytes(image)
    css = "span { font-family: Helvetica; font-size: 20.0pt; color: rgb(0,0,0); white-space: pre-wrap; }"
    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        insert_htmlbox_tracked(
            page,
            fitz.Rect(0, 0, width, height),
            f"<span>{html_mod.escape(text)}</span>",
            css=css,
            scale_low=1,
            scratch=True,
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=True)
        commit = bytes(pix.samples)
    finally:
        doc.close()
    return preview, commit


def test_live_preview_draws_ext_b_like_the_committed_page() -> None:
    """The inline editor's CSS preview must show the Ext-B glyph, not .notdef.

    ``PreviewRenderer.render`` used a bare ``insert_htmlbox`` (no subset
    ``@font-face``), so typing U+20B9F previewed an empty box while Apply
    committed it correctly.
    """
    _require_fonts()
    preview, commit = _preview_vs_commit("A\U00020B9F")
    assert preview == commit


def test_live_preview_without_ext_b_is_unchanged() -> None:
    """Control: ASCII text renders byte-identically on both paths."""
    preview, commit = _preview_vs_commit("AB")
    assert preview == commit


def test_live_preview_without_an_ext_b_font_still_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    """No installed Ext-B font: the preview draws .notdef exactly as the
    chokepoint does (no exception)."""
    monkeypatch.setattr(_module(), "find_ext_b_fonts", lambda: ())
    preview, commit = _preview_vs_commit("A\U00020B9F")
    assert preview == commit


def test_htmlbox_args_with_ext_b_helper_contract() -> None:
    mod = _module()
    kwargs = {"css": "span { color: red; }", "scale_low": 1}
    # Nothing to wrap: the very same markup, an equal (copied) kwargs dict.
    html, out = mod.htmlbox_args_with_ext_b("<span>abc</span>", kwargs)
    assert html == "<span>abc</span>" and out == kwargs and out is not kwargs
    with pytest.raises(TypeError):
        mod.htmlbox_args_with_ext_b(None, kwargs)  # type: ignore[arg-type]
    _require_fonts()
    caller_archive = fitz.Archive()
    caller_archive.add(b"x", "caller.bin")
    kwargs = {"css": "span { color: red; }", "scale_low": 1, "archive": caller_archive}
    before = dict(kwargs)
    html, out = mod.htmlbox_args_with_ext_b("<span>A\U00020B9F</span>", kwargs)
    assert kwargs == before  # the caller's dict is not mutated
    assert mod.FONT_NAME_PREFIX in html or mod.FONT_NAME_PREFIX in out["css"]
    assert out["css"].rstrip().endswith("span { color: red; }")
    assert "@font-face" in out["css"]
    assert out["archive"] is not caller_archive and out["scale_low"] == 1
    assert out["archive"].has_entry("caller.bin")


# ------------------- S14-EXTB-PREVIEW-WORKER: the live preview never subsets on the GUI thread
#
# Owner decision C on F13-EXTB-PERF-1: the fontTools subset of a NEW Ext-B
# character set (0.12-0.25 s) runs on a QThread worker.  The preview shows a
# transient .notdef frame, then re-renders when the subset is cached; a result
# for text the user has since changed is dropped; the worker never calls back
# into a closed editor.


class _SpySubset:
    """Stands in for ``_subset_cached``: records the thread of every call that
    really computes a subset (a cache miss), delegates everything else
    (``peek``, ``cache_clear``) to the real cache."""

    def __init__(self, real) -> None:
        self.real = real
        self.threads: list[int] = []

    def __call__(self, *args):
        misses = self.real.cache_info().misses
        out = self.real(*args)
        if self.real.cache_info().misses > misses:  # a real subset ran, on this thread
            self.threads.append(threading.get_ident())
        return out

    def __getattr__(self, name):
        return getattr(self.real, name)


def _pump(qapp, condition, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return bool(condition())


def _cold_spy(monkeypatch: pytest.MonkeyPatch) -> _SpySubset:
    mod = _module()
    mod._coverage_cached.cache_clear()
    mod._subset_cached.cache_clear()
    spy = _SpySubset(mod._subset_cached)
    monkeypatch.setattr(mod, "_subset_cached", spy)
    return spy


def _preview_editor(text: str = "A"):
    from view.text_editing import PreviewBackedInlineTextEditor, PreviewRenderer

    editor = PreviewBackedInlineTextEditor(text, PreviewRenderer())
    editor.configure_render_context(
        font_name="helv",
        font_size=20.0,
        color=(0.0, 0.0, 0.0),
        rect_pt=fitz.Rect(0, 0, 160, 40),
        rotation=0,
        render_scale=1.0,
    )
    editor._debounce.stop()
    return editor


def _drain_workers(qapp) -> None:
    """Let every Ext-B subset thread finish and its queued result be delivered."""
    from view.ext_b_subset_worker import wait_for_ext_b_subset_threads

    wait_for_ext_b_subset_threads()
    for _ in range(20):
        qapp.processEvents()


def _type(editor, text: str) -> None:
    editor.setPlainText(text)
    editor._debounce.stop()
    editor._regenerate_preview()


def _count_renders(editor) -> list[str]:
    renders: list[str] = []
    real_render = editor._renderer.render

    def counting(**kwargs):
        renders.append(kwargs["text"])
        return real_render(**kwargs)

    editor._renderer.render = counting
    return renders


def test_live_preview_subset_runs_on_a_worker_then_the_glyph_appears(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_fonts()
    text = "A\U00020B9F"
    reference, _commit = _preview_vs_commit(text)
    spy = _cold_spy(monkeypatch)
    editor = _preview_editor()
    try:
        _type(editor, text)
        transient = _image_bytes(editor._preview_image)
        assert _pump(qapp, lambda: _image_bytes(editor._preview_image) == reference), (
            "the preview never re-rendered with the Ext-B glyph"
        )
        assert spy.threads, "expected the Ext-B subset to be requested"
        assert threading.get_ident() not in spy.threads, "Ext-B subset ran on the GUI (main) thread"
        assert transient != reference, "the first frame must be the transient .notdef one"
    finally:
        from view.ext_b_subset_worker import wait_for_ext_b_subset_threads

        wait_for_ext_b_subset_threads()  # no live QThread may outlive the test
        editor.deleteLater()


def test_a_cached_ext_b_set_renders_at_once_without_a_worker(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_fonts()
    text = "A\U00020B9F"
    reference, _commit = _preview_vs_commit(text)  # warms both caches
    spy = _SpySubset(_module()._subset_cached)
    monkeypatch.setattr(_module(), "_subset_cached", spy)
    editor = _preview_editor()
    try:
        _type(editor, text)
        assert _image_bytes(editor._preview_image) == reference
        assert not spy.threads, "a warm cache must not run a subset at all"
    finally:
        editor.deleteLater()


def test_a_subset_result_for_older_text_is_dropped(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_fonts()
    _cold_spy(monkeypatch)
    editor = _preview_editor()
    renders = _count_renders(editor)
    try:
        _type(editor, "A\U00020B9F")  # subset requested
        _type(editor, "AB")  # the user kept typing: no Ext-B left
        ascii_frame = _image_bytes(editor._preview_image)
        _drain_workers(qapp)
        assert renders == ["A\U00020B9F", "AB"], "a stale subset result re-rendered the preview"
        assert _image_bytes(editor._preview_image) == ascii_frame
    finally:
        editor.deleteLater()


def test_closing_the_editor_cancels_the_worker_callback(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_fonts()
    _cold_spy(monkeypatch)
    from view.ext_b_subset_worker import live_ext_b_subset_threads

    editor = _preview_editor()
    renders = _count_renders(editor)
    _type(editor, "A\U00020B9F")
    editor.release_background_work()  # what _teardown_editor calls
    _drain_workers(qapp)
    assert renders == ["A\U00020B9F"], "a closed editor must not render again"
    assert not live_ext_b_subset_threads(), "the worker thread must be reaped"
    editor.deleteLater()


def test_the_view_calls_the_deferred_preview_render_only() -> None:
    """Bug class: a GUI-thread caller of the synchronous Ext-B subset.  Every
    ``.render(`` call of the inline editor class asks for ``defer_ext_b=True``,
    and no ``view/`` module calls the uncached resource builder directly.
    (``defer_ext_b=False`` stays the default for direct callers; widen this guard
    if another ``view/`` class ever calls ``PreviewRenderer.render``.)"""
    view_dir = ROOT / "view"
    editing = ast.parse((view_dir / "text_editing.py").read_text(encoding="utf-8"))
    editor_cls = next(
        n for n in ast.walk(editing)
        if isinstance(n, ast.ClassDef) and n.name == "PreviewBackedInlineTextEditor"
    )
    renders = [
        c for c in ast.walk(editor_cls)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "render"
    ]
    assert renders, "expected the editor to call renderer.render"
    for call in renders:
        flags = {k.arg: k.value for k in call.keywords}
        assert isinstance(flags.get("defer_ext_b"), ast.Constant) and flags["defer_ext_b"].value is True
    for path in sorted(view_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "ext_b_htmlbox_resources(" not in source, path.name


def test_cached_only_resources_never_run_the_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _module()
    _require_fonts()
    html = "<span>A\U00020B9F</span>"
    spy = _cold_spy(monkeypatch)
    with pytest.raises(mod.ExtBSubsetNotReady):
        mod.htmlbox_args_with_ext_b(html, {"css": "span {}"}, cached_only=True)
    assert not spy.threads, "cached_only must not compute anything"
    sync_html, sync_kwargs = mod.htmlbox_args_with_ext_b(html, {"css": "span {}"})  # warms
    warm_html, warm_kwargs = mod.htmlbox_args_with_ext_b(html, {"css": "span {}"}, cached_only=True)
    assert warm_html == sync_html and warm_kwargs["css"] == sync_kwargs["css"]
    # Nothing Ext-B in the markup: never "not ready", whatever the caches hold.
    plain, out = mod.htmlbox_args_with_ext_b("<span>abc</span>", {"scale_low": 1}, cached_only=True)
    assert plain == "<span>abc</span>" and out == {"scale_low": 1}


def test_deferred_render_reports_the_pending_markup_and_does_not_cache_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from view.text_editing import PreviewRenderer

    _require_fonts()
    _cold_spy(monkeypatch)
    renderer = PreviewRenderer()
    args = {
        "text": "A\U00020B9F", "font_name": "helv", "font_size": 20.0, "color": (0.0, 0.0, 0.0),
        "member_spans": None, "rect_pt": fitz.Rect(0, 0, 160, 40), "rotation": 0, "render_scale": 1.0,
    }
    first = renderer.render(defer_ext_b=True, **args)
    assert not first.isNull()
    assert renderer.pending_ext_b_html and "\U00020B9F" in renderer.pending_ext_b_html
    _module().ext_b_htmlbox_resources(renderer.pending_ext_b_html)  # what the worker does
    second = renderer.render(defer_ext_b=True, **args)
    assert renderer.pending_ext_b_html is None
    assert _image_bytes(second) != _image_bytes(first), "the transient frame must not be cached"


# ------------------------- F13-ENV-3: a missing fontTools is not "no glyph"


def _block_fonttools(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make ``import <name>`` raise ImportError, even when already imported."""
    for name in names or ("fontTools", "fontTools.ttLib", "fontTools.subset"):
        monkeypatch.setitem(sys.modules, name, None)


def _fake_installed_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _module()
    fake = tmp_path / "simsunb.ttf"
    fake.write_bytes(b"not a font at all" * 10)
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: (mod.ExtBFont(fake, 0, "SimSun"),))
    monkeypatch.setattr(mod, "_on_windows", lambda: True)
    mod._coverage_cached.cache_clear()
    return mod


@pytest.mark.parametrize(
    "blocked",
    [
        ("fontTools", "fontTools.ttLib", "fontTools.subset"),
        ("fontTools.subset",),  # partial install: the reader imports, the subsetter does not
    ],
)
def test_unimportable_fonttools_is_a_broken_install_not_missing_glyphs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture, blocked
) -> None:
    mod = _fake_installed_font(monkeypatch, tmp_path)
    assert mod.ext_b_component_missing() is False  # fontTools is importable here
    _block_fonttools(monkeypatch, *blocked)
    assert mod.ext_b_component_missing() is True
    assert mod.ext_b_install_would_help() is False  # fonts ARE installed
    reason = mod.ext_b_refusal_reason("a𠀀")
    assert reason is not None
    assert "fontTools" in reason and "have no glyph" not in reason, reason
    assert "U+20000" in reason
    # The draw path degrades like a missing font (nothing wrapped, no crash) ...
    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        assert mod.ext_b_htmlbox_resources("<span>𠀀</span>") is None
    # ... and the cause is logged, not hidden behind a per-font "unreadable".
    assert any("fontTools" in r.getMessage() for r in caplog.records), caplog.text
    assert not any("unreadable" in r.getMessage() for r in caplog.records), caplog.text


def test_component_missing_is_false_without_installed_fonts_or_ext_b_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _fake_installed_font(monkeypatch, tmp_path)
    _block_fonttools(monkeypatch)
    assert mod.ext_b_refusal_reason("plain text") is None
    monkeypatch.setattr(mod, "find_ext_b_fonts", lambda: ())
    assert mod.ext_b_component_missing() is False  # install-the-fonts advice comes first
    assert "neither is installed" in (mod.ext_b_refusal_reason("𠀀") or "")


def test_a_failed_fonttools_import_does_not_poison_the_coverage_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fonts = _require_fonts()
    mod = _module()
    mod._coverage_cached.cache_clear()
    with monkeypatch.context() as ctx:
        _block_fonttools(ctx)
        assert mod.uncovered_ext_b("𠀀") == ["U+20000"]
    # fontTools is back: the very same font now reports its real coverage.
    assert mod.font_for_codepoint(0x20000) is not None, fonts
    assert mod.uncovered_ext_b("𠀀") == []
