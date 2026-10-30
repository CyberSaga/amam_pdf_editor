"""Tests for scripts/census_show_shapes.py (Task 16-4X S0 review fold-in).

``census()`` is called in-process wherever possible -- the module has no
venv-only dependency, so importing it directly (``scripts`` is a regular
package, ``ROOT`` is on ``sys.path`` via ``test_scripts/conftest.py``) works
identically in CI and in the dev venv.  Exactly one test still shells out,
to pin the CLI contract end to end, and it goes through ``sys.executable``
rather than a hard-coded ``.venv`` interpreter so it runs in CI too.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from scripts import census_show_shapes as census_mod  # noqa: E402
from scripts.census_show_shapes import _positive_page_count, census  # noqa: E402

SCRIPT = ROOT / "scripts" / "census_show_shapes.py"


def _synthetic_three_show_page() -> fitz.Document:
    """Create a synthetic page with three shows: (a) Tj, [(b) -5 (c)] TJ, 2 Tr (d) Tj."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Stream with three shows:
    # 1. "(a) Tj" - simple Tj
    # 2. "[(b) -5 (c)] TJ" - TJ with single item and a kern
    # 3. "2 Tr (d) Tj" - render mode 2 with Tj
    stream = (
        b"BT /F1 12 Tf 72 700 Td "
        b"(a) Tj "  # Show 1: simple Tj
        b"0 -40 Td "
        b"[(b) -5 (c)] TJ "  # Show 2: TJ with single item and kern
        b"0 -40 Td "
        b"2 Tr (d) Tj "  # Show 3: render mode 2 with Tj
        b"ET"
    )

    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")

    return doc


def _save_synthetic_doc(tmp_path: Path) -> Path:
    doc = _synthetic_three_show_page()
    pdf_path = tmp_path / "test.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_census_synthetic_page_basic(tmp_path: Path) -> None:
    """``census()`` called in-process on a synthetic 3-show page."""
    pdf_path = _save_synthetic_doc(tmp_path)

    doc_data = census(str(pdf_path), None, True)

    assert "shows_total" in doc_data
    assert "shape" in doc_data
    assert "render_modes" in doc_data
    assert "kern_numbers_by_class" in doc_data

    assert doc_data["shows_total"] == 3, f"Expected 3 shows, got {doc_data['shows_total']}"

    render_modes = doc_data["render_modes"]
    assert "0" in render_modes, f"Expected mode 0, got: {render_modes}"
    assert "2" in render_modes, f"Expected mode 2, got: {render_modes}"
    # Mode 0: shows 1 and 2 = 2 shows; Mode 2: show 3 = 1 show
    assert render_modes["0"] == 2, f"Expected 2 mode-0 shows, got {render_modes['0']}"
    assert render_modes["2"] == 1, f"Expected 1 mode-2 show, got {render_modes['2']}"

    shape_keys = doc_data["shape"].keys()
    assert any("Tj" in k for k in shape_keys), f"Expected Tj in shapes, got: {list(shape_keys)}"
    assert any("TJ" in k for k in shape_keys), f"Expected TJ in shapes, got: {list(shape_keys)}"

    kern_class = doc_data["kern_numbers_by_class"]
    assert "micro(<0.05em)" in kern_class, f"Expected micro kern class, got: {kern_class.keys()}"

    # Privacy: the returned dict must never carry the fixture's path or name.
    json_str = json.dumps(doc_data)
    assert str(pdf_path) not in json_str
    assert "test.pdf" not in json_str


def test_census_kern_detection(tmp_path: Path) -> None:
    """Kerns are correctly classified, and a kernless TJ/Tj coexist."""
    pdf_path = _save_synthetic_doc(tmp_path)

    doc_data = census(str(pdf_path), None, True)

    shape_keys = [k for k in doc_data["shape"].keys() if "TJ" in k]
    tj_kerned = [k for k in shape_keys if "kern=y" in k]
    assert len(tj_kerned) > 0, f"Expected TJ with kern=y, got shapes: {shape_keys}"


def test_census_page_cap_of_one_samples_first_page_only(tmp_path: Path) -> None:
    """F4: ``--pages 1`` used to divide by zero in the even-spacing formula.

    A 3-page document with ``page_cap=1`` must sample exactly the first
    page rather than raising ``ZeroDivisionError``.
    """
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    pdf_path = tmp_path / "three_pages.pdf"
    doc.save(str(pdf_path))
    doc.close()

    result = census(str(pdf_path), 1, False)

    assert result["pages_total"] == 3
    assert result["pages_sampled"] == 1


def test_census_page_cap_of_zero_also_samples_one_page(tmp_path: Path) -> None:
    """F4: ``page_cap=0`` used to silently sample nothing (empty ``idxs``)."""
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    pdf_path = tmp_path / "three_pages.pdf"
    doc.save(str(pdf_path))
    doc.close()

    result = census(str(pdf_path), 0, False)

    assert result["pages_sampled"] == 1


def test_positive_page_count_rejects_less_than_one() -> None:
    """F4: argparse's ``--pages`` type function refuses < 1."""
    import argparse

    assert _positive_page_count("1") == 1
    assert _positive_page_count("5") == 5
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_page_count("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_page_count("-3")


def test_census_error_record_omits_the_file_path(capsys: pytest.CaptureFixture[str]) -> None:
    """F5: an open failure must record only the exception's class name --
    never ``str(exc)``, which for a missing file carries the path.

    T5: ``main()`` now returns ``1`` when any document recorded an error
    (previously it returned ``None`` implicitly)."""
    assert census_mod.main(["this_file_does_not_exist_at_all.pdf"]) == 1
    payload = json.loads(capsys.readouterr().out)

    error_value = payload["0"]["error"]
    assert error_value == "FileNotFoundError", error_value
    assert "/" not in error_value
    assert "\\" not in error_value
    assert "this_file_does_not_exist_at_all" not in error_value


def test_main_returns_zero_when_every_document_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T5: ``main()`` returns ``0`` when no document recorded an error."""
    pdf_path = _save_synthetic_doc(tmp_path)

    assert census_mod.main([str(pdf_path)]) == 0
    capsys.readouterr()


def test_main_returns_one_when_any_document_among_several_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T5: ``main()`` returns ``1`` if ANY document errored, even when
    others succeeded."""
    pdf_path = _save_synthetic_doc(tmp_path)

    assert (
        census_mod.main([str(pdf_path), "this_file_does_not_exist_at_all.pdf"]) == 1
    )
    capsys.readouterr()


@pytest.mark.parametrize("page_cap", [0, 1])
def test_census_zero_page_document_samples_no_pages(
    page_cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T5: ``page_cap <= 1`` on a zero-page document must sample nothing
    (``idxs = [0] if n else []``) rather than raising ``IndexError`` from
    ``doc[0]`` on an empty document. PyMuPDF refuses to ``save()`` a
    zero-page document, so the document is injected via a patched
    ``fitz.open`` rather than round-tripped through a file (mirrors
    ``test_census_closes_the_document``'s pattern)."""
    doc = fitz.open()
    assert doc.page_count == 0
    monkeypatch.setattr(census_mod.fitz, "open", lambda path: doc)

    result = census("unused.pdf", page_cap, False)

    assert result["pages_total"] == 0
    assert result["pages_sampled"] == 0
    assert result["shows_total"] == 0


def test_census_closes_the_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F8: ``census()`` must close the document it opens."""
    pdf_path = _save_synthetic_doc(tmp_path)

    opened: list[fitz.Document] = []
    real_open = census_mod.fitz.open

    def _tracking_open(path: str) -> fitz.Document:
        doc = real_open(path)
        opened.append(doc)
        return doc

    monkeypatch.setattr(census_mod.fitz, "open", _tracking_open)

    census(str(pdf_path), None, True)

    assert len(opened) == 1
    assert opened[0].is_closed


def test_census_relex_failure_is_counted_and_treated_as_kernless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F9: when the production re-lexer ``tj_items`` cannot reproduce a
    ``TJ`` array's own byte range, the show is counted in
    ``tj_relex_failed`` and treated as kernless -- never raised."""
    pdf_path = _save_synthetic_doc(tmp_path)

    monkeypatch.setattr(census_mod, "tj_items", lambda stream, show: None)

    result = census(str(pdf_path), None, True)

    assert result["text_state_flags"].get("tj_relex_failed") == 1
    tj_shapes = [k for k in result["shape"] if k.startswith("TJ|")]
    assert tj_shapes and all("kern=n" in k for k in tj_shapes)


def test_capability_lookup_memoized_per_page_per_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T1: ``registry.capability()`` must be called once per (page,
    font_resource), not once per show -- the synthetic fixture's three
    shows all use ``/F1``, so one memoized lookup must cover all three
    (model/text_commit/inspect.py's ``_cid_show_candidates`` pattern)."""
    pdf_path = _save_synthetic_doc(tmp_path)

    calls: list[str] = []
    real_capability = DocumentFontRegistry.capability

    def _counting_capability(self, page, resource_name):  # noqa: ANN001
        calls.append(resource_name)
        return real_capability(self, page, resource_name)

    monkeypatch.setattr(DocumentFontRegistry, "capability", _counting_capability)

    result = census(str(pdf_path), None, True)

    assert len(calls) == 1, calls
    # The memo must actually be SERVING every show, not just being called
    # once while every other show silently falls back to unresolved.
    assert result["fonts_by_capability"]
    assert sum(result["fonts_by_capability"].values()) == 3
    assert "<unresolved>" not in result["fonts_by_capability"]


def test_no_json_flag_on_the_parser() -> None:
    """F9: the dead ``--json`` flag is gone -- output is always JSON."""
    with pytest.raises(SystemExit):
        census_mod.main(["--json", "unused.pdf"])


def test_cli_smoke_runs_via_sys_executable(tmp_path: Path) -> None:
    """One CLI-level smoke test (F1), run through ``sys.executable`` so it
    works both in CI (no ``.venv``) and inside the dev venv."""
    pdf_path = _save_synthetic_doc(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    output = json.loads(result.stdout)
    assert "0" in output, f"Expected positional index '0', got keys: {list(output.keys())}"
    assert output["0"]["shows_total"] == 3

    blob = json.dumps(output)
    assert str(pdf_path) not in blob
    assert "test.pdf" not in blob


def _kern_only_tj_page() -> fitz.Document:
    """One ``TJ`` whose array carries a kern and NO string item."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    stream = b"BT /F1 12 Tf 72 700 Td [-500] TJ ET"
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def test_census_zero_item_tj_array_gets_its_own_item_class(tmp_path: Path) -> None:
    """Review fold 3: ``[-500] TJ`` (a cursor move, zero string items) must
    not be filed under ``items=2-3`` -- the S4/S5 ordering reads the
    multi-item kerned bucket, so a kern-only array inflating it is a
    measurement error, not a cosmetic one."""
    doc = _kern_only_tj_page()
    pdf_path = tmp_path / "k.pdf"
    doc.save(str(pdf_path))
    doc.close()
    data = census(str(pdf_path), None, False)
    assert data["shows_total"] == 1
    shape_keys = list(data["shape"])
    assert shape_keys == ["TJ|array|items=0|kern=y|Tr=0"], shape_keys
    assert data["kerned_shows_by_item_class"] == {"items=0": 1}


def test_type0_shape_reads_the_inline_descendant_form() -> None:
    """Review fold 3: ``/DescendantFonts [<<...>>]`` (the dominant corpus
    spelling, 256/262 fonts per ``cid_fonts.py``) must report the
    descendant's subtype and CIDToGIDMap, not ``desc=?|c2g=?``. The census
    must use the production resolver (``cid_fonts.resolve_descendant``)."""
    doc = fitz.open()
    doc.new_page()
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type0 /BaseFont /AAAAAA+X /Encoding /Identity-H "
        "/DescendantFonts [ << /Type /Font /Subtype /CIDFontType2 "
        "/BaseFont /AAAAAA+X /CIDToGIDMap /Identity >> ] >>",
    )
    try:
        shape = census_mod._type0_shape(doc, font_xref)
    finally:
        doc.close()
    assert shape == "enc=/Identity-H|desc=/CIDFontType2|c2g=name", shape


def test_type0_shape_reads_the_indirect_descendant_form() -> None:
    """The ``[N 0 R]`` spelling keeps working through the shared resolver."""
    doc = fitz.open()
    doc.new_page()
    desc_xref = doc.get_new_xref()
    doc.update_object(
        desc_xref,
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /AAAAAA+X >>",
    )
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type0 /BaseFont /AAAAAA+X /Encoding /Identity-H "
        f"/DescendantFonts [ {desc_xref} 0 R ] >>",
    )
    try:
        shape = census_mod._type0_shape(doc, font_xref)
    finally:
        doc.close()
    assert shape == "enc=/Identity-H|desc=/CIDFontType2|c2g=absent", shape


def test_simple_shape_differences_verdict_is_the_production_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review fold 3: the census must not carry a second ``/Differences``
    detector -- it asks ``fonts.has_custom_differences`` (the Tier 0
    gate's own predicate) so the two can never disagree."""
    doc = fitz.open()
    doc.new_page()
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    calls: list[int] = []

    def _fake(_doc: object, xref: int) -> bool:
        calls.append(xref)
        return True

    monkeypatch.setattr(census_mod, "has_custom_differences", _fake)
    try:
        shape = census_mod._simple_shape(doc, font_xref)
    finally:
        doc.close()
    assert calls == [font_xref]
    assert shape.startswith("encmode=name|diff|"), shape


# --- v11 census mode: a bounded replay and a count of the pages it refused -----


def test_census_default_is_unbounded_and_reports_no_refused_or_malformed_pages(
    tmp_path: Path,
) -> None:
    """The new keys exist on every result and the default behaviour is the
    old one: ``max_decoded_bytes`` defaults to ``None`` (no guard), so the
    synthetic page still yields its three shows and nothing is refused."""
    pdf_path = _save_synthetic_doc(tmp_path)

    result = census(str(pdf_path), None, True)

    assert result["shows_total"] == 3
    assert result["pages_replay_refused"] == 0
    assert result["pages_replay_malformed"] == 0


def test_census_bounded_replay_counts_a_refused_page_instead_of_reading_it_as_empty(
    tmp_path: Path,
) -> None:
    """With a decoded-byte budget the replay refuses an over-budget page and
    returns no shows; without the counter that page is indistinguishable
    from "this page has no text". It must be counted, and not as malformed."""
    pdf_path = _save_synthetic_doc(tmp_path)

    result = census(str(pdf_path), None, True, max_decoded_bytes=1)

    assert result["pages_sampled"] == 1
    assert result["shows_total"] == 0
    assert result["pages_replay_refused"] == 1
    assert result["pages_replay_malformed"] == 0


def test_census_bounded_replay_within_budget_reads_the_page_normally(
    tmp_path: Path,
) -> None:
    pdf_path = _save_synthetic_doc(tmp_path)

    result = census(str(pdf_path), None, True, max_decoded_bytes=4 * 1024 * 1024)

    assert result["shows_total"] == 3
    assert result["pages_replay_refused"] == 0


def test_census_counts_a_page_whose_replay_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from model.text_commit.replay import PageReplay

    pdf_path = _save_synthetic_doc(tmp_path)
    monkeypatch.setattr(
        census_mod,
        "replay_page_streams",
        lambda streams, max_decoded_bytes=None: PageReplay(
            shows=(), malformed=True, has_xobject_invocation=False, stream_xrefs=()
        ),
    )

    result = census(str(pdf_path), None, True)

    assert result["pages_replay_malformed"] == 1
    assert result["pages_replay_refused"] == 0


def test_census_passes_the_budget_to_the_replay_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The budget reaches ``replay_page_streams`` verbatim (``None`` for the
    default), so a census run is held to the same guard as the product."""
    pdf_path = _save_synthetic_doc(tmp_path)
    seen: list[object] = []
    real = census_mod.replay_page_streams

    def _spy(streams, max_decoded_bytes=None):  # noqa: ANN001
        seen.append(max_decoded_bytes)
        return real(streams, max_decoded_bytes=max_decoded_bytes)

    monkeypatch.setattr(census_mod, "replay_page_streams", _spy)

    census(str(pdf_path), None, True)
    census(str(pdf_path), None, True, max_decoded_bytes=12345)

    assert seen == [None, 12345]
