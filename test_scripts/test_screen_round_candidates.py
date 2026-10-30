"""Pins for ``scripts/screen_round_candidates.py`` (the product-probe screen behind the Grok round lists).

The round-8 shortlist (brief v12 section 3.9) was picked from census buckets and a hand locate that never ran the
production classifier; the audit dropped 13 of its 25 rows (brief v13 section 3.10).  The screen holds a file to the
PRODUCTION verdict: ``prepare_plan`` at ``max_tier`` 0 and 1 with the show's own page-space origin, after the cheap
pre-filters the audit named (the font classified by itself, ``origin_reliable``, Tr 0, no marked content, no widget
page, printable ASCII of two or more bytes, ``|K| > 0`` for F2K).  These tests pin the parts a reviewer cannot see
from a run: the class is decided by the font, the F2K shape by the TJ items, the verdict by ``prepare_plan`` itself,
and the record carries no document text, no absolute path and no ``/Creator`` string.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.glyph_boxes import TjItem  # noqa: E402
from model.text_commit.inspect import _origin_in_page_space, read_page_streams  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from scripts import screen_round_candidates as src  # noqa: E402

TARGET = "Hello"
PALINDROME = "abcba"


def _cap(**over) -> FontCapability:
    base = dict(
        owner_xref=1,
        resource_name="F1",
        font_xref=7,
        basefont="Helvetica",
        subtype="Type1",
        encoding="",
        embedded=False,
        face=None,
        face_source="base14",
        supports_simple_encoding=True,
        tier0_reject_reason=None,
    )
    base.update(over)
    return FontCapability(**base)


# ---------------------------------------------------------------------------------------------------------------------
# the class is decided by the font itself (brief v13 section 3.1 (bl))
# ---------------------------------------------------------------------------------------------------------------------
def test_f30_class_embedded_truetype_without_encoding_is_f30b():
    assert src.classify_f30_font(_cap(subtype="TrueType", embedded=True, encoding="", basefont="ABCDEF+Arial"), symbolic=False) == "F30B"


def test_f30_class_embedded_type1_without_encoding_is_quarantined_not_f30b():
    """The F30B independent leg exists only for FontFile2; an embedded Type1/CFF has no clean positive until I1."""
    assert src.classify_f30_font(_cap(subtype="Type1", embedded=True, encoding="", basefont="ABCDEF+CMR10"), symbolic=False) == "F30B_no_leg"


@pytest.mark.parametrize("encoding", ["WinAnsiEncoding", "MacRomanEncoding", "StandardEncoding"])
def test_f30_class_embedded_with_a_named_simple_encoding_is_f30w(encoding):
    assert src.classify_f30_font(_cap(subtype="TrueType", embedded=True, encoding=encoding, basefont="ABCDEF+Arial"), symbolic=False) == "F30W"
    assert src.classify_f30_font(_cap(subtype="Type1", embedded=True, encoding=encoding, basefont="ABCDEF+CMR10"), symbolic=False) == "F30W"


@pytest.mark.parametrize("encoding", ["", "WinAnsiEncoding", "MacRomanEncoding", "StandardEncoding"])
def test_f30_class_unembedded_standard_14_is_f30n_whatever_the_simple_encoding(encoding):
    assert src.classify_f30_font(_cap(encoding=encoding), symbolic=False) == "F30N"
    assert src.classify_f30_font(_cap(encoding=encoding, basefont="ABCDEF+Times-Bold"), symbolic=False) == "F30N"


def test_f30_class_unembedded_non_standard_14_or_symbolic_is_no_f30_class():
    assert src.classify_f30_font(_cap(subtype="TrueType", basefont="Arial,Bold", face_source="system"), symbolic=False) is None
    assert src.classify_f30_font(_cap(basefont="Symbol"), symbolic=False) is None
    assert src.classify_f30_font(_cap(), symbolic=True) is None


def test_f30_class_type0_or_rejected_font_is_no_f30_class():
    assert src.classify_f30_font(_cap(subtype="Type0", encoding="Identity-H", embedded=True), symbolic=False) is None
    assert src.classify_f30_font(_cap(tier0_reject_reason="font_custom_differences"), symbolic=False) is None


# ---------------------------------------------------------------------------------------------------------------------
# the F2K shape is the TJ items: exactly one string followed by one kern, and the kern is not zero
# ---------------------------------------------------------------------------------------------------------------------
def test_f2k_kern_is_the_trailing_number_of_a_single_string_tj():
    items = (TjItem("string", b"Hi"), TjItem("kern", -250.0))
    assert src.f2k_trailing_kern(items) == -250.0


def test_f2k_kern_is_none_for_every_other_item_shape():
    assert src.f2k_trailing_kern((TjItem("string", b"Hi"),)) is None
    assert src.f2k_trailing_kern((TjItem("kern", -250.0), TjItem("string", b"Hi"))) is None
    assert src.f2k_trailing_kern((TjItem("string", b"Hi"), TjItem("kern", -250.0), TjItem("string", b"x"))) is None
    assert src.f2k_trailing_kern((TjItem("string", b"Hi"), TjItem("kern", -1.0), TjItem("kern", -2.0))) is None
    assert src.f2k_trailing_kern(None) is None
    assert src.f2k_trailing_kern(()) is None


def test_f2k_zero_kern_is_still_the_shape():
    """Zero trailing kerns count as F2K shape (census ``has_kern``; the product reaches the fence on them, issue17784
    6/6), so the kern reader returns 0.0 and the screen probes the show; it is flagged, never clean (below)."""
    assert src.f2k_trailing_kern((TjItem("string", b"Hi"), TjItem("kern", 0.0))) == 0.0


# ---------------------------------------------------------------------------------------------------------------------
# the byte filters
# ---------------------------------------------------------------------------------------------------------------------
def test_printable_target_needs_two_or_more_printable_ascii_bytes_without_quote_operators():
    assert src.printable_target(b"Hi")
    assert not src.printable_target(b"H")
    assert src.printable_target(b"H", min_len=1)  # the F2K shape admits a one-glyph target (brief v13 section 3.3)
    assert not src.printable_target(b"")
    assert not src.printable_target(b"", min_len=1)
    assert not src.printable_target(b"Hi\xe9")
    assert not src.printable_target(b"it's")
    assert not src.printable_target(b"a`b")
    assert not src.printable_target(b"a\nb")


def test_family_token_comes_from_the_producer_only_and_is_normalised():
    assert src.family_token({"producer": "GPL Ghostscript 8.15", "creator": "Acme Secret Corp"}) == "gpl-ghostscript"
    assert src.family_token({"producer": "pdfTeX-1.40.21", "creator": "LaTeX with hyperref"}) == "pdftex"
    assert src.family_token({"producer": "", "creator": "Acme Secret Corp"}) == "<none>"
    assert src.family_token({}) == "<none>"
    assert src.family_token({"producer": None}) == "<none>"


# ---------------------------------------------------------------------------------------------------------------------
# the verdict is prepare_plan's own, on hand-authored shapes (PyMuPDF's writers never emit a bare Tj or a kerned TJ)
# ---------------------------------------------------------------------------------------------------------------------
def _doc(stream: bytes, font: str = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", *, producer: str | None = None,
         creator: str | None = None) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, font)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    if producer is not None or creator is not None:
        doc.set_metadata({"producer": producer or "", "creator": creator or ""})
    return doc


def _tj_doc(text: str, producer: str | None = None, creator: str | None = None) -> fitz.Document:
    return _doc(b"BT /F1 12 Tf 72 700 Td (" + text.encode() + b") Tj 0 -40 Td (below) Tj ET", producer=producer, creator=creator)


def _f2k_doc(text: str, kern: float) -> fitz.Document:
    k = ("%g" % kern).encode()
    return _doc(b"BT /F1 12 Tf 72 700 Td [(" + text.encode() + b") " + k + b"] TJ 0 -40 Td (below) Tj ET")


def _first_show(doc: fitz.Document, seq: int = 0):
    page = doc[0]
    replay = replay_page_streams(read_page_streams(doc, page), max_decoded_bytes=4 * 1024 * 1024)
    return page, next(s for s in replay.shows if s.seq == seq)


def test_f30n_show_verdict_equals_prepare_plan_on_the_reversed_target_and_names_the_standard_14_leg():
    doc = _tj_doc(TARGET)
    rec = src.screen_document(doc, page_cap=5, probe_cap=4, reach_cap=2)
    f30n = rec["classes"]["F30N"]
    assert f30n["qualifying"] == 2 and f30n["probed"] == 2 and f30n["reach"] == 2
    ex = f30n["examples"][0]
    assert (ex["page"], ex["seq"], ex["n"]) == (0, 0, len(TARGET))
    page, show = _first_show(doc)
    direct = prepare_plan(doc, page, target_text=TARGET, replacement_text=TARGET[::-1],
                          expected_origin=_origin_in_page_space(page, show), target_bbox=None,
                          registry=DocumentFontRegistry(doc), max_tier=0)
    assert isinstance(direct, PreparedEdit) and ex["t0"] == "PREPARED"
    assert ex["leg"] == "standard_14_table" and ex["leg_ok"] is True
    assert set(rec["classes"]) == {"F30N"}  # a class appears only when a located show belongs to it


def test_a_palindrome_and_a_one_byte_target_are_bucketed_not_probed():
    rec = src.screen_document(_doc(b"BT /F1 12 Tf 72 700 Td (" + PALINDROME.encode() + b") Tj 0 -40 Td (x) Tj ET"),
                              page_cap=5, probe_cap=4, reach_cap=2)
    f30n = rec["classes"]["F30N"]
    assert f30n["probed"] == 0 and f30n["reach"] == 0
    assert f30n["skipped"] == {"palindrome": 1, "short_or_unprintable": 1}


def test_f2k_show_verdict_is_the_tier1_fence_and_the_kern_is_recorded():
    doc = _f2k_doc(TARGET, -250.0)
    rec = src.screen_document(doc, page_cap=5, probe_cap=4, reach_cap=2)
    f2k = rec["classes"]["F2K"]
    assert f2k["qualifying"] == 1 and f2k["probed"] == 1 and f2k["reach"] == 1
    ex = f2k["examples"][0]
    assert ex["t1"] == RejectReason.TJ_KERN_IN_TIER1_RANGE
    assert ex["t0"] == RejectReason.ADVANCE_MISMATCH
    assert ex["kern"] == -250.0 and ex["kern_pt"] == pytest.approx(3.0)
    assert ex["gz_glyphs"] == 0
    # the Tj below it is an F30N show, not an F2K one
    assert rec["classes"]["F30N"]["qualifying"] == 1


def test_f2k_one_glyph_target_qualifies_and_records_n_1():
    rec = src.screen_document(_f2k_doc("H", -250.0), page_cap=5, probe_cap=4, reach_cap=2)
    f2k = rec["classes"]["F2K"]
    assert f2k["qualifying"] == 1 and f2k["reach"] == 1 and f2k["examples"][0]["n"] == 1


def test_f2k_zero_kern_show_is_probed_flagged_and_never_clean():
    """The product reaches the fence on a zero kern (the refuter re-ran issue17784: 6/6), so the screen must say so;
    the zero kern can show no compensation of a border kern, so it is never ``reach_clean``."""
    rec = src.screen_document(_f2k_doc(TARGET, 0.0), page_cap=5, probe_cap=4, reach_cap=2)
    f2k = rec["classes"]["F2K"]
    assert f2k["probed"] == 1 and f2k["reach"] == 1 and f2k["reach_clean"] == 0 and f2k["skipped"] == {}
    ex = f2k["examples"][0]
    assert ex["t1"] == RejectReason.TJ_KERN_IN_TIER1_RANGE and ex["zero_kern"] is True and ex["gz_glyphs"] == 0


def test_f2k_shape_on_an_unsampled_page_is_still_found_but_f30_shapes_there_are_not():
    """The F2K shape is rare and the page sample hid a reaching file (issue20722: five reaching shows, all on skipped
    pages), so every page is scanned for F2K; F30 shapes stay on the sampled pages."""
    doc = _f2k_doc(TARGET, -250.0)  # page 0 holds the F2K show and an F30N Tj
    page1 = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, b"BT /F1 12 Tf 72 700 Td [(World) -300] TJ 0 -40 Td (other) Tj ET")
    doc.xref_set_key(page1.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page1.xref, "Resources", doc.xref_get_key(doc[0].xref, "Resources")[1])
    rec = src.screen_document(doc, page_cap=1, probe_cap=4, reach_cap=4)
    assert rec["pages"] == {"sampled": 1, "f2k_only": 1}
    assert rec["classes"]["F2K"]["reach"] == 2 and {e["page"] for e in rec["classes"]["F2K"]["examples"]} == {0, 1}
    assert rec["classes"]["F30N"]["qualifying"] == 1  # the Tj on page 1 is not counted
    off = src.screen_document(doc, page_cap=1, probe_cap=4, reach_cap=4, f2k_all_pages=False)
    assert off["pages"] == {"sampled": 1} and off["classes"]["F2K"]["reach"] == 1


def test_a_font_the_product_rejects_is_counted_in_font_rejected_not_dropped():
    """A show on a /Differences font dies at the I8 gate before any show gate; the record says so instead of losing it."""
    font = ("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            "/Encoding << /Type /Encoding /Differences [65 /B] >> >>")
    rec = src.screen_document(_doc(b"BT /F1 12 Tf 72 700 Td (Hello) Tj 0 -40 Td [(Hi) -250] TJ ET", font),
                              page_cap=5, probe_cap=4, reach_cap=2)
    assert rec["classes"] == {}
    assert rec["font_rejected"] == {"F30|font_custom_differences": 1, "F2K|font_custom_differences": 1}


def test_f30w_reach_clean_needs_the_independent_leg_too():
    """An F30W positive without a leg is quarantined at rederive (Type1/CFF F30W in every batch since I1 opened), so the
    screen runs the leg for every F30 class; on this hand-authored non-embedded Helvetica the class is F30N and the
    example carries the leg either way."""
    rec = src.screen_document(_tj_doc(TARGET), page_cap=5, probe_cap=4, reach_cap=2)
    ex = rec["classes"]["F30N"]["examples"][0]
    assert ex["leg"] == "standard_14_table" and ex["leg_ok"] is True
    assert rec["classes"]["F30N"]["reach_clean"] == rec["classes"]["F30N"]["reach"] == 2


def test_a_widget_page_is_skipped_before_any_probe():
    doc = _tj_doc(TARGET)
    page = doc[0]
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "f"
    widget.rect = fitz.Rect(300, 300, 400, 320)
    page.add_widget(widget)
    rec = src.screen_document(doc, page_cap=5, probe_cap=4, reach_cap=2)
    assert rec["pages"]["widget"] == 1 and rec["classes"] == {}


def test_the_record_carries_no_document_text_no_absolute_path_and_no_creator_string(tmp_path):
    doc = _tj_doc(TARGET, producer="Foo Writer 9.1 Corp", creator="Acme Secret Company")
    rec = src.screen_document(doc, page_cap=5, probe_cap=4, reach_cap=2)
    rec = src.file_record(rec, sha256="ab" * 32, relative_path="test_files/mozilla-pdf/x.pdf", size=123)
    blob = json.dumps(rec)
    assert TARGET not in blob and "below" not in blob
    assert "Acme" not in blob and "Secret" not in blob
    assert ":\\" not in blob and ":/" not in blob
    assert rec["sha8"] == "abababab" and rec["path"] == "test_files/mozilla-pdf/x.pdf"
    assert rec["family"] == "foo-writer"


# ---------------------------------------------------------------------------------------------------------------------
# the summary groups by producer family and marks the registered files, so new families are what the list shows
# ---------------------------------------------------------------------------------------------------------------------
def _rec(sha8: str, family: str, **classes) -> dict:
    return {
        "sha8": sha8,
        "path": f"test_files/mozilla-pdf/{sha8}.pdf",
        "family": family,
        "classes": {k: {"qualifying": v, "probed": v, "reach": v, "reach_clean": v, "skipped": {}, "examples": []} for k, v in classes.items()},
    }


def test_summary_groups_reaching_files_by_family_and_flags_registered_lineages():
    registry = {"aaaaaaaa": "gs815-pscript5", "cccccccc": "firefox-cairo"}
    recs = [_rec("aaaaaaaa", "gpl-ghostscript", F2K=9), _rec("bbbbbbbb", "gpl-ghostscript", F2K=3),
            _rec("cccccccc", "cairo-https", F30W=3), _rec("dddddddd", "skia-pdf", F30W=2), _rec("eeeeeeee", "skia-pdf", F30W=0)]
    summary = src.summarise(recs, registry)
    assert summary["F2K"]["families"] == {"gpl-ghostscript": ["aaaaaaaa", "bbbbbbbb"]}
    assert summary["F2K"]["registered"] == {"aaaaaaaa": "gs815-pscript5"}
    assert summary["F2K"]["new_families"] == []
    assert summary["F30W"]["families"] == {"cairo-https": ["cccccccc"], "skia-pdf": ["dddddddd"]}
    assert summary["F30W"]["new_families"] == ["skia-pdf"]
    assert "F30B" not in summary


def test_summary_new_means_the_series_has_no_registered_file_in_any_class():
    """Section 3.0 ``single_family`` counts producer families, so a Distiller 10 F30W file is not a new family while a
    Distiller 8 file is registered under F31, and a Ghostscript F30W file is not new while gs815 holds an F2K row."""
    registry = {"aaaaaaaa": "gs815-pscript5", "ffffffff": "distiller-sharp"}
    recs = [_rec("aaaaaaaa", "gpl-ghostscript", F2K=9), _rec("ffffffff", "acrobat-distiller", F30N=0),
            _rec("gggggggg", "acrobat-distiller", F30W=4), _rec("hhhhhhhh", "adobe-pdf", F30W=4),
            _rec("iiiiiiii", "gnu-ghostscript", F30W=2), _rec("jjjjjjjj", "yeslogic-prince", F30W=4)]
    summary = src.summarise(recs, registry)
    assert set(summary["F30W"]["families"]) == {"acrobat-distiller", "adobe-pdf", "gnu-ghostscript", "yeslogic-prince"}
    assert summary["F30W"]["new_families"] == ["yeslogic-prince"]


def test_a_file_without_producer_is_neither_a_registered_series_nor_a_new_family():
    """``<none>`` is no family under section 3.0: a registered producer-less file must not make every other
    producer-less file look registered, and none of them is a new family; the text marks them (no producer)."""
    registry = {"aaaaaaaa": "vera-6-8-3-3-t01-fail"}
    recs = [_rec("aaaaaaaa", "<none>", F30W=1), _rec("bbbbbbbb", "<none>", F30W=2), _rec("cccccccc", "skia-pdf", F30W=2)]
    summary = src.summarise(recs, registry)
    assert set(summary["F30W"]["families"]) == {"<none>", "skia-pdf"} and summary["F30W"]["new_families"] == ["skia-pdf"]
    text = src.summary_text(summary, recs)
    assert "<none> (no producer) | bbbbbbbb" in text and "<none> (new series)" not in text and "1 series with no registered file" in text


def test_series_of_maps_a_family_token_to_its_product_series():
    assert src.series_of("acrobat-distiller") == src.series_of("adobe-pdf") == src.series_of("acrobat-pdfwriter") == "adobe"
    assert src.series_of("gpl-ghostscript") == src.series_of("gnu-ghostscript") == src.series_of("pdfcreator") == "ghostscript"
    assert src.series_of("itext-itext") == src.series_of("prawn") == src.series_of("itextsharp-t") == "itext-prawn"
    assert src.series_of("mac-os") == "quartz" and src.series_of("cairo-https") == "cairo" and src.series_of("pdftex-a") == "tex"
    assert src.series_of("yeslogic-prince") == src.series_of("prince-www") == "prince"
    assert src.series_of("pdflib-jdk") == src.series_of("pdflib-personalization") == "pdflib"
    assert src.series_of("tcpdf-http") == "tcpdf-http" and src.series_of("<none>") == "<none>"


def test_reaching_examples_replace_the_refusals_kept_while_the_file_looked_dead():
    """issue20722: twelve probes, the first ones refused (duplicate painter), the reaching ones later; the summary must
    show the reaching shows, not six refusals."""
    doc = _f2k_doc(TARGET, -250.0)
    page1 = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    # page 1: the same show painted twice at one origin (duplicate_source_painter), then a clean F2K show lower down
    doc.update_stream(content_xref, b"BT /F1 12 Tf 72 700 Td [(Twin) -300] TJ ET BT /F1 12 Tf 72 700 Td [(Twin) -300] TJ ET "
                                    b"BT /F1 12 Tf 72 600 Td [(Clean) -300] TJ ET")
    doc.xref_set_key(page1.xref, "Contents", f"{content_xref} 0 R")
    doc.xref_set_key(page1.xref, "Resources", doc.xref_get_key(doc[0].xref, "Resources")[1])
    rec = src.screen_document(doc, page_cap=1, probe_cap=12, reach_cap=12)
    f2k = rec["classes"]["F2K"]
    assert f2k["probed"] == 4 and f2k["reach"] == 2
    assert all(e["t1"] == RejectReason.TJ_KERN_IN_TIER1_RANGE for e in f2k["examples"]) and len(f2k["examples"]) == 2


def test_summary_text_lists_only_sha8_path_family_and_counts():
    recs = [_rec("dddddddd", "skia-pdf", F30W=2)]
    text = src.summary_text(src.summarise(recs, {}), recs)
    assert "F30W" in text and "skia-pdf" in text and "dddddddd" in text and "test_files/mozilla-pdf/dddddddd.pdf" in text
    assert ":\\" not in text


def test_registry_lineages_come_from_the_tracked_sha_table():
    table = {"files": [{"relative_path": "test_files/a.pdf", "sha256": "ab" * 32, "origin": "mozilla-pdf", "lineage_id": "x-y"}]}
    assert src.registry_lineages(table) == {"abababab": "x-y"}
