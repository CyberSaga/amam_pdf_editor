"""P3b: the font streams ``insert_htmlbox`` embeds are deduplicated and compressed.

A legacy rebuild (and every add-text box) used to leave whole font programs raw
in the file: ``/Length1 5181580 /Length 5181580`` with no ``/Filter`` for a CJK
``@font-face`` TTF, 3.5 MB for the built-in Droid fallback, an unfiltered
``/ToUnicode`` CMap each, and one fresh copy per ``insert_htmlbox`` call.

``model.font_stream_compaction`` fixes that once per operation:

* ``font_compaction_scope(doc)`` -- on a normal exit it re-points duplicate new
  FontFile/FontFile2/FontFile3/ToUnicode streams to the first identical copy and
  Flate-compresses each survivor once; on an exception it does nothing;
* ``insert_htmlbox_tracked`` is the model's only ``insert_htmlbox`` chokepoint
  (raises outside a scope unless ``scratch=True``), pinned by an AST guard.

No test here imports fontTools: compaction is compress-only, no subsetting.
Every fixture is synthetic.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "test_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "test_scripts"))

import test_text_commit_no_silent_legacy as nsl  # noqa: E402

from model.edit_commands import EditTextCommand, EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.save_compaction import reachable_xrefs, unreachable_xrefs  # noqa: E402

CJK = "點擊頁面測試"
_PROGRAM_KEYS = ("FontFile", "FontFile2", "FontFile3")
_FONT_STREAM_KEYS = (*_PROGRAM_KEYS, "ToUnicode")


def _fsc():
    """The module under test, imported lazily so each test fails on its own."""
    return importlib.import_module("model.font_stream_compaction")


# ------------------------------------------------------------------ helpers


def _target(doc: fitz.Document, owner: int, key: str) -> int | None:
    kind, value = doc.xref_get_key(owner, key)
    if kind != "xref":
        return None
    return int(value.split()[0])


def _font_entries(
    doc: fitz.Document, start: int = 1, *, reachable_only: bool = False
) -> list[tuple[int, str, int]]:
    """(owner, key, stream xref) for every font program / ToUnicode entry."""
    reach = reachable_xrefs(doc) if reachable_only else None
    out = []
    for owner in range(max(1, start), doc.xref_length()):
        if reach is not None and owner not in reach:
            continue
        for key in _FONT_STREAM_KEYS:
            target = _target(doc, owner, key)
            if target is not None:
                out.append((owner, key, target))
    return out


def _filtered(doc: fitz.Document, xref: int) -> bool:
    return doc.xref_get_key(xref, "Filter")[1] == "/FlateDecode"


def _assert_every_font_stream_compact(doc: fitz.Document, start: int) -> list[tuple[int, str, int]]:
    entries = _font_entries(doc, start)
    assert entries, "the operation embedded no font streams at all"
    for owner, key, target in entries:
        if target < start:
            continue
        assert _filtered(doc, target), f"{key} stream {target} (owner {owner}) has no /Filter"
        raw = doc.xref_stream_raw(target)
        decoded = doc.xref_stream(target)
        assert len(raw) < len(decoded), f"{key} stream {target} did not shrink"
        if key == "FontFile2":
            assert doc.xref_get_key(target, "Length1") == ("int", str(len(decoded)))
    return entries


def _distinct_programs_reachable(doc: fitz.Document, start: int = 1) -> tuple[int, int]:
    """(# distinct FontFile* stream xrefs reachable from the trailer at xref >= ``start``,
    # distinct decoded programs among them)."""
    targets = {
        t
        for _o, k, t in _font_entries(doc, reachable_only=True)
        if k in _PROGRAM_KEYS and t >= start
    }
    digests = {hashlib.sha256(doc.xref_stream(t)).hexdigest() for t in targets}
    return len(targets), len(digests)


def _page_state(page: fitz.Page) -> tuple[bytes, list[str]]:
    pix = page.get_pixmap(dpi=72)
    chars = [
        c["c"]
        for b in page.get_text("rawdict")["blocks"]
        if b.get("type") == 0
        for ln in b["lines"]
        for sp in ln["spans"]
        for c in sp["chars"]
    ]
    return bytes(pix.samples), chars


def _cjk_doc_with_blocks(tmp_path: Path, name: str, texts: list[str], gap: float = 30.0) -> Path:
    """A page whose text blocks are CJK lines (built with the engine's own insert)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, text in enumerate(texts):
        page.insert_htmlbox(
            fitz.Rect(72, 100 + i * gap, 400, 100 + i * gap + 20),
            f"<span>{text}</span>",
            css="* { font-size: 12pt; white-space: pre; margin: 0; padding: 0; }",
        )
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _open(path: Path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def _blank_doc() -> fitz.Document:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    return doc


def _insert_cjk(page: fitz.Page, y: float = 100.0, *, scratch: bool = False) -> None:
    _fsc().insert_htmlbox_tracked(
        page,
        fitz.Rect(72, y, 400, y + 24),
        f"<span>{CJK} abc</span>",
        css="* { font-size: 12pt; margin: 0; padding: 0; }",
        scratch=scratch,
    )


def _no_compaction(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Control: the scope still opens but compaction never runs."""
    calls: list[tuple] = []
    fsc = _fsc()

    def _noop(doc, start):
        calls.append((doc, start))
        return []

    monkeypatch.setattr(fsc, "compact_new_font_streams", _noop)
    return calls


# --------------------------------------------------------- the scope itself


def test_scope_compresses_every_new_font_stream_and_dedupes_copies() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    page = doc[0]
    n0 = doc.xref_length()
    with fsc.font_compaction_scope(doc):
        for i in range(3):
            _insert_cjk(page, 100 + i * 40)
        # Nothing is touched mid-operation.
        mid = _font_entries(doc, n0)
        assert mid and not any(_filtered(doc, t) for _o, _k, t in mid)
    entries = _assert_every_font_stream_compact(doc, n0)
    # Three inserts embedded three fonts (Droid + Charis each) ...
    assert len({o for o, k, _t in entries if k == "FontFile2"}) == 3
    # ... but only one program per distinct font survives behind them.
    assert len({t for _o, k, t in entries if k == "FontFile2"}) == 1
    assert len({t for _o, k, t in entries if k == "FontFile3"}) == 1
    assert len({t for _o, k, t in entries if k == "ToUnicode"}) == 2  # Droid CMap, Charis CMap
    n_prog, n_distinct = _distinct_programs_reachable(doc)
    assert n_prog == n_distinct == 2


def test_scope_close_leaves_dedup_duplicates_unreachable_and_the_doc_valid() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    page = doc[0]
    n0 = doc.xref_length()
    with fsc.font_compaction_scope(doc):
        _insert_cjk(page, 100)
        _insert_cjk(page, 160)
    orphans = unreachable_xrefs(doc, from_xref=n0)
    assert orphans, "the abandoned duplicate font copies are left to save-time pruning"
    # Every duplicate stream is still the raw original (never half-rewritten).
    for xref in orphans:
        if doc.xref_is_stream(xref):
            assert doc.xref_get_key(xref, "Filter")[0] == "null"
    reopened = fitz.open("pdf", doc.tobytes(garbage=1))
    assert CJK in reopened[0].get_text()
    assert unreachable_xrefs(reopened) == []


def test_compaction_keeps_rendering_and_extraction_identical(monkeypatch) -> None:
    fsc = _fsc()
    compact_doc, control_doc = _blank_doc(), _blank_doc()
    with fsc.font_compaction_scope(compact_doc):
        _insert_cjk(compact_doc[0], 100)
        _insert_cjk(compact_doc[0], 160)
    # Control: same inserts, neither deduplicated nor compressed.
    _no_compaction(monkeypatch)
    with fsc.font_compaction_scope(control_doc):
        _insert_cjk(control_doc[0], 100)
        _insert_cjk(control_doc[0], 160)
    control_entries = _font_entries(control_doc)
    assert control_entries and not any(_filtered(control_doc, t) for _o, _k, t in control_entries)
    pixels_a, chars_a = _page_state(compact_doc[0])
    pixels_b, chars_b = _page_state(control_doc[0])
    assert chars_a == chars_b and CJK[0] in chars_a
    assert pixels_a == pixels_b
    # And the compacted file really is smaller.
    assert len(compact_doc.tobytes(garbage=1, deflate=False)) < len(control_doc.tobytes(garbage=1, deflate=False))


def test_scope_without_new_fonts_is_a_noop_and_edge_arguments() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    with fsc.font_compaction_scope(doc):
        doc[0].insert_text(fitz.Point(72, 100), "plain", fontname="helv")
    assert fsc.scope_active(doc) is False
    length = doc.xref_length()
    # start_xref at / past the end, 0 and negative are all harmless.
    assert fsc.compact_new_font_streams(doc, length) == []
    assert fsc.compact_new_font_streams(doc, length + 50) == []
    assert fsc.compact_new_font_streams(doc, 0) == []
    assert fsc.compact_new_font_streams(doc, -3) == []


def test_an_already_flate_font_is_not_touched() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    start = doc.xref_length()
    desc = doc.get_new_xref()
    stream = doc.get_new_xref()
    doc.update_object(stream, "<< /Length1 1000 >>")
    doc.update_stream(stream, b"\x00" * 1000, compress=True)
    doc.update_object(desc, f"<< /Type /FontDescriptor /FontName /X /FontFile2 {stream} 0 R >>")
    raw = doc.xref_stream_raw(stream)
    assert _filtered(doc, stream)
    assert fsc.compact_new_font_streams(doc, start) == []
    assert doc.xref_stream_raw(stream) == raw


def test_a_font_program_that_is_not_a_page_font_stream_is_left_alone() -> None:
    """Only streams a new descriptor / font dict points at are candidates."""
    fsc = _fsc()
    doc = _blank_doc()
    start = doc.xref_length()
    loose = doc.get_new_xref()
    doc.update_object(loose, "<< >>")
    doc.update_stream(loose, b"\x01" * 4096, compress=False)
    assert fsc.compact_new_font_streams(doc, start) == []
    assert doc.xref_get_key(loose, "Filter")[0] == "null"
    assert doc.xref_stream_raw(loose) == b"\x01" * 4096


def test_insert_htmlbox_tracked_rejects_non_pages_and_scopeless_calls() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    rect = fitz.Rect(72, 100, 300, 130)
    with pytest.raises(TypeError):
        fsc.insert_htmlbox_tracked(doc, rect, "<span>x</span>")  # a Document, not a Page
    with pytest.raises(TypeError):
        fsc.insert_htmlbox_tracked(None, rect, "<span>x</span>")
    n0 = doc.xref_length()
    with pytest.raises(fsc.FontCompactionScopeError):
        fsc.insert_htmlbox_tracked(doc[0], rect, "<span>x</span>")
    assert doc.xref_length() == n0, "a refused call must not mutate the document"
    # A throwaway document opts out explicitly and gets the raw behaviour.
    spare, _scale = fsc.insert_htmlbox_tracked(doc[0], rect, "<span>x</span>", scratch=True)
    assert spare >= 0
    # The scope is per DOCUMENT: another document's scope does not unlock this one.
    other = _blank_doc()
    with fsc.font_compaction_scope(other), pytest.raises(fsc.FontCompactionScopeError):
        fsc.insert_htmlbox_tracked(doc[0], rect, "<span>x</span>")


@pytest.mark.parametrize("rotation", [90, 180, 270])
@pytest.mark.parametrize(
    "mediabox, cropbox",
    [
        ((0, 0, 600, 800), None),
        ((0, 0, 600, 800), (30, 40, 500, 700)),
        ((-100, -200, 500, 600), None),
    ],
    ids=["plain", "crop", "negmb"],
)
def test_insert_htmlbox_tracked_draws_inside_the_box_on_a_rotated_offset_page(
    mediabox, cropbox, rotation
) -> None:
    """F15-G4: PyMuPDF's htmlbox goes through ``page.transformation_matrix``, which
    drops the CropBox/MediaBox origin once ``/Rotate != 0``; every model caller
    hands the chokepoint a rect in true unrotated page space."""
    fsc = _fsc()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox:
        doc.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % cropbox)
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    page = doc.reload_page(page)
    visual = fitz.Rect(200, 150, 360, 200)
    box = (visual * page.derotation_matrix).normalize()
    with fsc.font_compaction_scope(doc):
        fsc.insert_htmlbox_tracked(
            page, box, '<span style="font-size:20pt">MMMM</span>', rotate=rotation, scale_low=0
        )
    words = [w[4] for w in page.get_text("words")]
    assert words == ["MMMM"], words
    # GATE16-1: judge the placement by the DRAWN ink (visual space, 72 dpi), not
    # by an extraction box -- PyMuPDF's word box of upside-down text (every
    # /Rotate 180 case here) sits ~0.64 em off the ink under the production
    # small_glyph_heights flag, and depends on that process-global flag at all.
    drawn = fitz.Rect(_dark_ink(page))
    # The bug was a 30-200 pt shift; the ink sits within ~12 pt of the box corner.
    assert abs(drawn.x0 - visual.x0) <= 12 and abs(drawn.y0 - visual.y0) <= 12, (drawn, visual)
    assert drawn.x1 <= visual.x1 + 1 and drawn.y1 <= visual.y1 + 1, (drawn, visual)
    doc.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
@pytest.mark.parametrize("user_unit", [2.0, 0.5])
def test_insert_htmlbox_tracked_keeps_size_and_place_on_a_rotated_user_unit_page(
    rotation, user_unit
) -> None:
    """F15-G1-UU-ROT: the htmlbox page matrix drops ``/UserUnit`` once ``/Rotate != 0``.
    The chokepoint lays the text out in the rect it is given (PAGE units: the glyphs
    keep their 20 pt) and draws it where that rect is on the page; ``spare_height``
    and ``scale`` stay in page units too, as on a unit page."""
    from model.text_commit.transforms import page_visual_frame

    fsc = _fsc()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[0 0 300 400]")
    doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    page = doc.reload_page(page)
    frame = page_visual_frame(page)
    visual = fitz.Rect(20, 30, 20 + 100, 30 + 50)
    box = (visual * ~frame.quarter_turn).normalize()  # true unrotated page space
    with fsc.font_compaction_scope(doc):
        spare, scale = fsc.insert_htmlbox_tracked(
            page, box, '<span style="font-size:20pt">MMMM</span>', rotate=rotation, scale_low=0
        )
    twin = fitz.open()
    twin_page = twin.new_page(width=300, height=400)  # unrotated, unit scale: the oracle
    with fsc.font_compaction_scope(twin):
        want_spare, want_scale = fsc.insert_htmlbox_tracked(
            twin_page, visual, '<span style="font-size:20pt">MMMM</span>', scale_low=0
        )
    assert (spare, scale) == pytest.approx((want_spare, want_scale))  # page units, as on a unit page
    # The rendered ink (visual space, 72 dpi) of the rotated page equals the twin's.
    want_ink, got_ink = _dark_ink(twin_page), _dark_ink(page)
    twin.close()
    assert got_ink == pytest.approx(want_ink, abs=1.5), (got_ink, want_ink)  # same size AND place
    doc.close()


def _dark_ink(page: fitz.Page) -> tuple[int, int, int, int]:
    pix = page.get_pixmap(colorspace=fitz.csGRAY, alpha=False)
    xs: list[int] = []
    ys: list[int] = []
    for y in range(pix.height):
        row = pix.samples[y * pix.width : (y + 1) * pix.width]
        dark = [x for x, v in enumerate(row) if v < 100]
        if dark:
            xs.extend((dark[0], dark[-1]))
            ys.append(y)
    assert xs, "nothing drawn"
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def test_insert_htmlbox_tracked_restores_show_pdf_page_after_a_scaled_placement() -> None:
    fsc = _fsc()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    doc.xref_set_key(page.xref, "MediaBox", "[0 0 300 400]")
    doc.xref_set_key(page.xref, "UserUnit", "2")
    doc.xref_set_key(page.xref, "Rotate", "90")
    page = doc.reload_page(page)
    with fsc.font_compaction_scope(doc):
        fsc.insert_htmlbox_tracked(page, fitz.Rect(10, 10, 200, 60), "<span>x</span>", scale_low=0)
        assert "show_pdf_page" not in vars(page)  # the per-call redirect is gone
        with pytest.raises(ValueError):
            fsc.insert_htmlbox_tracked(page, fitz.Rect(10, 10, 200, 60), "<span>x</span>", scale_low=2)
        assert "show_pdf_page" not in vars(page)  # ... also after a failing call
    doc.close()


def test_an_exception_in_the_scope_does_nothing_and_resets_the_scope() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    n0 = doc.xref_length()
    with pytest.raises(ZeroDivisionError):
        with fsc.font_compaction_scope(doc):
            _insert_cjk(doc[0])
            raise ZeroDivisionError
    assert fsc.scope_active(doc) is False
    entries = _font_entries(doc, n0)
    assert entries and not any(_filtered(doc, t) for _o, _k, t in entries)
    # The scope can be re-entered afterwards and then works normally.
    with fsc.font_compaction_scope(doc):
        _insert_cjk(doc[0], 200)
    assert any(_filtered(doc, t) for _o, _k, t in _font_entries(doc, n0))


def test_scopes_nest_and_only_the_outermost_compacts() -> None:
    fsc = _fsc()
    doc = _blank_doc()
    n0 = doc.xref_length()
    with fsc.font_compaction_scope(doc):
        with fsc.font_compaction_scope(doc):
            _insert_cjk(doc[0], 100)
        assert fsc.scope_active(doc) is True
        inner_done = _font_entries(doc, n0)
        assert inner_done and not any(_filtered(doc, t) for _o, _k, t in inner_done)
        _insert_cjk(doc[0], 160)
    assert fsc.scope_active(doc) is False
    _assert_every_font_stream_compact(doc, n0)
    assert _distinct_programs_reachable(doc) == (2, 2)


def test_a_failure_inside_compaction_never_fails_the_operation(monkeypatch) -> None:
    fsc = _fsc()
    doc = _blank_doc()
    # A spy, not caplog: the assertion is on the exact warning call, not on
    # which handlers are installed.  (GATE16-1a: conftest now also keeps
    # logging enabled around every test.)
    warnings: list[str] = []
    monkeypatch.setattr(fsc.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg)))

    def _boom(*_a, **_k):
        raise RuntimeError("compaction exploded")

    monkeypatch.setattr(fsc, "compact_new_font_streams", _boom)
    with fsc.font_compaction_scope(doc):
        _insert_cjk(doc[0])
    assert fsc.scope_active(doc) is False
    assert CJK in doc[0].get_text()
    assert any("font stream compaction failed" in w for w in warnings)


def test_only_objects_inside_the_window_are_deduped_or_compressed() -> None:
    """A font an earlier command embedded is never re-pointed at or recompressed."""
    fsc = _fsc()
    doc = _blank_doc()
    with fsc.font_compaction_scope(doc):
        _insert_cjk(doc[0], 100)  # command 1
    first_entries = _font_entries(doc)
    first_targets = {t for _o, _k, t in first_entries}
    first_raw = {t: doc.xref_stream_raw(t) for t in first_targets}
    boundary = doc.xref_length()
    with fsc.font_compaction_scope(doc):
        _insert_cjk(doc[0], 160)  # command 2: identical fonts again
    new_entries = [e for e in _font_entries(doc, boundary)]
    assert new_entries
    for owner, _key, target in new_entries:
        assert owner >= boundary
        assert target >= boundary, "a new descriptor was re-pointed at an older command's stream"
        assert _filtered(doc, target)
    for t in first_targets:
        assert doc.xref_stream_raw(t) == first_raw[t], "an earlier command's stream was rewritten"


def test_a_pre_scope_raw_font_is_never_compressed() -> None:
    """Objects below the watermark -- e.g. the source file's own fonts -- stay raw."""
    fsc = _fsc()
    doc = _blank_doc()
    _insert_cjk(doc[0], 100, scratch=True)  # embedded OUTSIDE any scope
    old = _font_entries(doc)
    assert old and not any(_filtered(doc, t) for _o, _k, t in old)
    old_raw = {t: doc.xref_stream_raw(t) for _o, _k, t in old}
    with fsc.font_compaction_scope(doc):
        _insert_cjk(doc[0], 160)
    for t, raw in old_raw.items():
        assert doc.xref_stream_raw(t) == raw
        assert doc.xref_get_key(t, "Filter")[0] == "null"


def test_length1_survives_for_a_type1_style_three_length_stream() -> None:
    """/Length1-3 are segment lengths for Type1 programs: compression keeps them verbatim."""
    fsc = _fsc()
    doc = _blank_doc()
    start = doc.xref_length()
    desc, stream = doc.get_new_xref(), doc.get_new_xref()
    doc.update_object(stream, "<< /Length1 300 /Length2 500 /Length3 200 >>")
    doc.update_stream(stream, b"A" * 1000, compress=False)
    doc.update_object(desc, f"<< /Type /FontDescriptor /FontName /X /FontFile {stream} 0 R >>")
    assert fsc.compact_new_font_streams(doc, start) == [stream]
    assert _filtered(doc, stream)
    assert doc.xref_stream(stream) == b"A" * 1000
    assert [doc.xref_get_key(stream, k)[1] for k in ("Length1", "Length2", "Length3")] == [
        "300",
        "500",
        "200",
    ]


# ----------------------------------------------------------- the AST guard


def _bare_insert_htmlbox_calls(source: str) -> list[int]:
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "insert_htmlbox"
    ]


def test_no_bare_insert_htmlbox_in_model() -> None:
    """Every ``model/`` insert goes through ``insert_htmlbox_tracked``.

    Scope: ``model/**/*.py`` only.  ``view/text_editing.py`` builds a throwaway
    preview document (never saved, never undone) and cannot import the model;
    its call is guarded separately by
    ``test_view_and_controller_htmlbox_calls_apply_the_ext_b_subset``.
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "model").rglob("*.py")):
        if path.name == "font_stream_compaction.py":
            continue
        for lineno in _bare_insert_htmlbox_calls(path.read_text(encoding="utf-8-sig")):
            offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert offenders == []


def test_the_ast_guard_detects_what_it_guards() -> None:
    assert _bare_insert_htmlbox_calls("page.insert_htmlbox(r, h)") == [1]
    assert _bare_insert_htmlbox_calls("x = a.b.insert_htmlbox(\n r, h)") == [1]
    assert _bare_insert_htmlbox_calls("insert_htmlbox_tracked(page, r, h)") == []
    assert _bare_insert_htmlbox_calls("# page.insert_htmlbox(r, h)\nx = 'insert_htmlbox('") == []
    # The chokepoint itself is the module the guard exempts.
    src = (ROOT / "model" / "font_stream_compaction.py").read_text(encoding="utf-8")
    assert len(_bare_insert_htmlbox_calls(src)) == 1


# ------------------------------------------------ add_textbox / push-down


def test_add_textbox_cjk_embeds_no_unfiltered_font_program(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    doc = _blank_doc()
    doc.save(str(path))
    doc.close()
    model = _open(path)
    try:
        n0 = model.doc.xref_length()
        model.add_textbox(1, fitz.Rect(72, 100, 320, 160), "點擊頁面", font="cjk", size=14)
        entries = _assert_every_font_stream_compact(model.doc, n0)
        kinds = {k for _o, k, _t in entries}
        assert {"FontFile2", "ToUnicode"} <= kinds  # the Droid fallback is covered
        from model.font_stream_compaction import scope_active

        assert scope_active(model.doc) is False
        assert "點擊頁面" in model.doc[0].get_text()
    finally:
        model.close()


def test_add_textbox_twice_keeps_one_copy_of_each_program_per_command(tmp_path: Path) -> None:
    """Each add_textbox is its own operation: undo-safe, never re-pointed across commands."""
    path = tmp_path / "blank2.pdf"
    doc = _blank_doc()
    doc.save(str(path))
    doc.close()
    model = _open(path)
    try:
        model.add_textbox(1, fitz.Rect(72, 100, 320, 160), "點擊頁面", font="cjk", size=14)
        boundary = model.doc.xref_length()
        model.add_textbox(1, fitz.Rect(72, 200, 320, 260), "再一個", font="cjk", size=14)
        _assert_every_font_stream_compact(model.doc, boundary)
        for _o, _k, target in _font_entries(model.doc, boundary):
            assert target >= boundary
    finally:
        model.close()


def test_push_down_of_several_cjk_blocks_leaves_one_font_program(tmp_path: Path) -> None:
    fsc = _fsc()
    path = _cjk_doc_with_blocks(tmp_path, "pd.pdf", ["中文文字一二", "中文文字三四", "中文文字五六"], gap=26.0)
    model = _open(path)
    try:
        model.ensure_page_index_built(1)
        page = model.doc[0]
        n0 = model.doc.xref_length()
        with fsc.font_compaction_scope(model.doc):
            model._push_down_overlapping_text(
                page, fitz.Rect(page.rect), above_y=95.0, new_bottom=130.0, edit_x0=72.0, edit_x1=400.0
            )
        entries = _assert_every_font_stream_compact(model.doc, n0)
        owners = {o for o, k, _t in entries if k == "FontFile2"}
        assert len(owners) >= 2, "the push-down must have re-inserted >= 2 blocks (one font copy each)"
        n_prog, n_distinct = _distinct_programs_reachable(model.doc, n0)
        assert n_prog == n_distinct == 1, "one surviving program per distinct font among reachable objects"
        text = page.get_text()
        for block in ("中文文字一二", "中文文字三四", "中文文字五六"):
            assert block in text
    finally:
        model.close()


def test_push_down_render_equals_the_uncompacted_control(tmp_path: Path, monkeypatch) -> None:
    fsc = _fsc()
    texts = ["中文文字一二", "中文文字三四", "中文文字五六"]

    def run(name: str) -> tuple[bytes, list[str]]:
        model = _open(_cjk_doc_with_blocks(tmp_path, name, texts, gap=26.0))
        try:
            model.ensure_page_index_built(1)
            page = model.doc[0]
            with fsc.font_compaction_scope(model.doc):
                model._push_down_overlapping_text(
                    page, fitz.Rect(page.rect), above_y=95.0, new_bottom=130.0, edit_x0=72.0, edit_x1=400.0
                )
            return _page_state(model.doc[0])
        finally:
            model.close()

    compact = run("pd_a.pdf")
    _no_compaction(monkeypatch)
    control = run("pd_b.pdf")
    assert compact == control


# ----------------------------------------------------- the legacy rebuild


def _rebuild(model: PDFModel, new_text: str, *, font: str = "helv") -> EditTextCommand:
    block = nsl._block(model, nsl.TARGET)
    cmd = EditTextCommand(
        model=model,
        page_num=1,
        rect=fitz.Rect(block.layout_rect),
        new_text=new_text,
        font=font,
        size=12.0,
        color=(0.0, 0.0, 0.0),
        original_text=block.text,
        vertical_shift_left=True,
        page_snapshot_bytes=model._capture_page_snapshot(0),
        old_block_id=None,
        old_block_text=block.text,
        confirm_fallback=lambda chain: True,
        allow_rebuild=True,
    )
    model.command_manager.execute(cmd)
    return cmd


@pytest.fixture
def rebuild_model(tmp_path: Path):
    model = nsl._open_model(nsl._write_pdf(tmp_path / "rebuild.pdf", nsl._tj_array_stream()))
    yield model
    model.close()


def _reachable_font_raw(doc: fitz.Document) -> dict[int, bytes]:
    return {
        t: doc.xref_stream_raw(t)
        for _o, _k, t in _font_entries(doc, reachable_only=True)
    }


def test_legacy_rebuild_embeds_no_unfiltered_font_program(rebuild_model: PDFModel) -> None:
    model = rebuild_model
    n0 = model.doc.xref_length()
    cmd = _rebuild(model, f"{CJK} test")
    assert cmd.result is EditTextResult.SUCCESS
    entries = _assert_every_font_stream_compact(model.doc, n0)
    assert {"FontFile2", "ToUnicode"} <= {k for _o, k, _t in entries}
    n_prog, n_distinct = _distinct_programs_reachable(model.doc, n0)
    assert n_prog == n_distinct >= 1
    assert CJK in model.doc[0].get_text()


def test_font_face_rebuild_embeds_a_compact_font_program(
    rebuild_model: PDFModel, tmp_path: Path, monkeypatch
) -> None:
    """The owner's case: a CJK ``@font-face`` TTF (kaiu.ttf stand-in) embedded verbatim."""
    import model.pdf_model as pdf_model_module

    ttf = tmp_path / "stand_in_cjk.ttf"
    ttf.write_bytes(fitz.Font("cjk").buffer)
    monkeypatch.setitem(pdf_model_module._WINDOWS_CJK_FONT_FILES, "dfkai-sb", ttf)
    model = rebuild_model
    n0 = model.doc.xref_length()
    cmd = _rebuild(model, f"{CJK} test", font="dfkai-sb")
    assert cmd.result is EditTextResult.SUCCESS
    entries = _assert_every_font_stream_compact(model.doc, n0)
    kinds = {k for _o, k, _t in entries}
    assert {"FontFile2", "ToUnicode"} <= kinds
    # Evidence the url() face took: the single TTF covers the Latin too, so
    # there is no separate CFF companion font as with the built-in fallback.
    assert "FontFile3" not in kinds
    # ... and the 3.5 MB program is stored compressed, not verbatim.
    program = next(t for _o, k, t in entries if k == "FontFile2")
    assert len(model.doc.xref_stream_raw(program)) < len(ttf.read_bytes())
    n_prog, n_distinct = _distinct_programs_reachable(model.doc, n0)
    assert n_prog == n_distinct == 1


def test_rebuild_redo_restores_the_compacted_font(rebuild_model: PDFModel) -> None:
    """The scope closes BEFORE the after-snapshot: redo brings back compacted bytes."""
    model = rebuild_model
    cmd = _rebuild(model, f"{CJK} test")
    assert cmd.result is EditTextResult.SUCCESS
    first = _reachable_font_raw(model.doc)
    assert first and all(_filtered(model.doc, t) for t in first)
    assert model.command_manager.undo() is True
    assert model.command_manager.redo() is True
    again = _reachable_font_raw(model.doc)
    assert again == first
    assert all(_filtered(model.doc, t) for t in again)
    assert CJK in model.doc[0].get_text()


def test_horizontal_strategy_fallthrough_dedupes_across_attempts(
    rebuild_model: PDFModel, monkeypatch
) -> None:
    """Strategy A and B 'fail' (spare < 0) and C commits: one font per program survives."""
    model = rebuild_model
    live_doc = model.doc
    real = fitz.Page.insert_htmlbox
    live_calls: list[float] = []

    def forcing(page_obj, *args, **kwargs):
        result = real(page_obj, *args, **kwargs)
        if page_obj.parent is live_doc:
            live_calls.append(float(kwargs.get("scale_low", -1)))
            if len(live_calls) <= 2:  # strategies A and B
                return (-1.0, 1.0)
        return result

    monkeypatch.setattr(fitz.Page, "insert_htmlbox", forcing)
    n0 = model.doc.xref_length()
    cmd = _rebuild(model, f"{CJK} test")
    assert cmd.result is EditTextResult.SUCCESS
    assert live_calls[:3] == [1.0, 1.0, 0.5], live_calls
    entries = _assert_every_font_stream_compact(model.doc, n0)
    assert len({o for o, k, _t in entries if k == "FontFile2"}) >= 3, "one font copy per attempt"
    n_prog, n_distinct = _distinct_programs_reachable(model.doc, n0)
    assert n_prog == n_distinct >= 1


def test_vertical_retry_dedupes_both_attempts(tmp_path: Path, monkeypatch) -> None:
    """Rotated source text -> the vertical path inserts at scale_low=1 then 0."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(fitz.Point(300, 600), "VERTICAL", fontname="helv", fontsize=12, rotate=90)
    path = tmp_path / "vertical.pdf"
    doc.save(str(path), garbage=0)
    doc.close()
    model = nsl._open_model(path)
    try:
        block = next(b for b in model.block_manager.get_blocks(0) if "VERTICAL" in (b.text or ""))
        live_doc = model.doc
        real = fitz.Page.insert_htmlbox
        live_calls: list[float] = []

        def forcing(page_obj, *args, **kwargs):
            result = real(page_obj, *args, **kwargs)
            if page_obj.parent is live_doc:
                live_calls.append(float(kwargs.get("scale_low", -1)))
                if len(live_calls) == 1:
                    return (-1.0, 1.0)
            return result

        monkeypatch.setattr(fitz.Page, "insert_htmlbox", forcing)
        n0 = model.doc.xref_length()
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=CJK,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
            confirm_fallback=lambda chain: True,
            allow_rebuild=True,
        )
        model.command_manager.execute(cmd)
        assert cmd.result is EditTextResult.SUCCESS
        assert live_calls[:2] == [1.0, 0.0], live_calls
        _assert_every_font_stream_compact(model.doc, n0)
        n_prog, n_distinct = _distinct_programs_reachable(model.doc, n0)
        assert n_prog == n_distinct >= 1
    finally:
        model.close()


def test_failed_legacy_rollback_leaves_no_compaction_and_a_clean_save(
    rebuild_model: PDFModel, tmp_path: Path, monkeypatch
) -> None:
    """Strategy C raising restores the snapshot; the scope does nothing on the way out."""
    fsc = _fsc()
    model = rebuild_model
    before_streams = [model.doc.xref_stream(x) for x in model.doc[0].get_contents()]
    before_text = model.doc[0].get_text()
    live_doc = model.doc
    real = fitz.Page.insert_htmlbox

    def never_fits(page_obj, *args, **kwargs):
        result = real(page_obj, *args, **kwargs)  # the fonts really are embedded
        return (-1.0, 1.0) if page_obj.parent is live_doc else result

    monkeypatch.setattr(fitz.Page, "insert_htmlbox", never_fits)
    huge = f"{CJK} test"  # strategies A, B and C all report "does not fit"
    block = nsl._block(model, nsl.TARGET)
    with pytest.raises(RuntimeError):
        model.edit_text(
            1,
            fitz.Rect(block.layout_rect),
            huge,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            allow_rebuild=True,
            confirm_fallback=lambda chain: True,
        )
    assert fsc.scope_active(model.doc) is False
    assert [model.doc.xref_stream(x) for x in model.doc[0].get_contents()] == before_streams
    assert model.doc[0].get_text() == before_text
    out = tmp_path / "after_failed_rebuild.pdf"
    model.save_as(str(out))
    saved = fitz.open(str(out))
    try:
        assert unreachable_xrefs(saved) == []
        assert saved[0].get_text() == before_text
    finally:
        saved.close()


def test_a_tiered_commit_never_opens_a_compaction_scope(tmp_path: Path, monkeypatch) -> None:
    """Tier 0/1 engine streams are untouched: the scope belongs to the legacy path only."""
    import model.pdf_text_edit as pte

    opened: list[int] = []
    real_scope = pte.font_compaction_scope

    def counting(doc):
        opened.append(1)
        return real_scope(doc)

    monkeypatch.setattr(pte, "font_compaction_scope", counting)
    model = nsl._open_model(nsl._write_pdf(tmp_path / "t0.pdf", nsl._tier0_stream()))
    try:
        block = nsl._block(model, nsl.TARGET)
        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(block.layout_rect),
            new_text=nsl.REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=block.text,
            vertical_shift_left=True,
            page_snapshot_bytes=model._capture_page_snapshot(0),
            old_block_id=None,
            old_block_text=block.text,
        )
        model.command_manager.execute(cmd)
        assert cmd.result is EditTextResult.SUCCESS
        assert opened == []
    finally:
        model.close()


def test_the_documented_font_stream_keys_match_what_story_writes() -> None:
    """Guard the assumption the candidate scan rests on (PyMuPDF is pinned to one minor)."""
    doc = _blank_doc()
    n0 = doc.xref_length()
    _insert_cjk(doc[0], scratch=True)
    keys = {k for _o, k, _t in _font_entries(doc, n0)}
    assert {"FontFile2", "FontFile3", "ToUnicode"} <= keys
    for _o, _k, t in _font_entries(doc, n0):
        assert re.fullmatch(r"\d+", str(t))
        assert doc.xref_get_key(t, "Filter")[0] == "null"


def _functions_with_bare_htmlbox_but_no_ext_b_args(source: str) -> list[str]:
    """Functions that call ``.insert_htmlbox(`` without ``htmlbox_args_with_ext_b``."""
    tree = ast.parse(source)
    bad: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        has_bare = any(
            isinstance(c.func, ast.Attribute) and c.func.attr == "insert_htmlbox" for c in calls
        )
        has_args = any(
            (isinstance(c.func, ast.Name) and c.func.id == "htmlbox_args_with_ext_b")
            or (isinstance(c.func, ast.Attribute) and c.func.attr == "htmlbox_args_with_ext_b")
            for c in calls
        )
        if has_bare and not has_args:
            bad.append(f"{fn.name}:{fn.lineno}")
    return bad


def test_view_and_controller_htmlbox_calls_apply_the_ext_b_subset() -> None:
    """The bug class behind S12-EXTB-PREVIEW: a bare ``insert_htmlbox`` outside
    the model chokepoint (the view cannot import ``model``) skips the Ext-B
    ``@font-face``/archive and draws .notdef.  Every such call site in
    ``view/``, ``controller/`` and ``utils/`` must go through
    ``utils.cjk_ext_b_font.htmlbox_args_with_ext_b`` first."""
    offenders: list[str] = []
    for folder in ("view", "controller", "utils"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            src = path.read_text(encoding="utf-8-sig")
            for where in _functions_with_bare_htmlbox_but_no_ext_b_args(src):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{where}")
    assert offenders == []


def test_the_view_ext_b_guard_detects_what_it_guards() -> None:
    bare = "def f(p):\n    p.insert_htmlbox(r, h)\n"
    ok = "def f(p):\n    h, kw = htmlbox_args_with_ext_b(h, {})\n    p.insert_htmlbox(r, h, **kw)\n"
    ok_attr = "def f(p):\n    h, kw = m.htmlbox_args_with_ext_b(h, {})\n    p.insert_htmlbox(r, h, **kw)\n"
    assert _functions_with_bare_htmlbox_but_no_ext_b_args(bare) == ["f:1"]
    assert _functions_with_bare_htmlbox_but_no_ext_b_args(ok) == []
    assert _functions_with_bare_htmlbox_but_no_ext_b_args(ok_attr) == []
