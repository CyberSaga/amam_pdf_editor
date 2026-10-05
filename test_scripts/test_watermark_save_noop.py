"""Product save must not mutate non-target objects when no watermark exists.

Measured by the UI real-corpus umbrella: saving a document that never had
watermarks wrote an empty ``__pdf_editor_watermarks`` attachment, changing the
Catalog and appending new objects. These tests pin the save contract through
``PDFModel.save_as`` on the incremental save-back-to-original path.
"""
from __future__ import annotations

import json

import fitz
import pytest

from model.pdf_model import PDFModel
from model.tools.watermark_tool import WatermarkTool

_EMBED = WatermarkTool.WATERMARK_EMBED_NAME


def _make_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12.0)
    doc.save(str(path))
    doc.close()


def _appended_non_xref(before_len: int, doc: fitz.Document) -> list[int]:
    # Mirrors the umbrella filter: an incremental save may append an XRef
    # stream, anything else is a new object.
    return [
        xref
        for xref in range(before_len, doc.xref_length())
        if doc.xref_get_key(xref, "Type") != ("name", "/XRef")
    ]


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "plain.pdf"
    _make_pdf(path)
    return path


def _open_model(path) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path))
    return model


def test_save_without_watermarks_leaves_catalog_and_objects_untouched(pdf_path):
    with fitz.open(str(pdf_path)) as source:
        catalog_before = source.xref_object(source.pdf_catalog(), compressed=True)
        xref_len_before = source.xref_length()
        assert _EMBED not in source.embfile_names()

    model = _open_model(pdf_path)
    try:
        assert model.use_incremental_save
        assert model.doc.can_save_incrementally()
        assert model.tools.watermark.get_watermarks() == []
        model.save_as(str(pdf_path))
    finally:
        model.close_all_sessions()

    with fitz.open(str(pdf_path)) as reopened:
        assert reopened.xref_object(reopened.pdf_catalog(), compressed=True) == catalog_before
        assert _appended_non_xref(xref_len_before, reopened) == []
        assert _EMBED not in reopened.embfile_names()
        assert reopened.embfile_count() == 0


def test_save_without_watermarks_does_not_touch_live_doc(pdf_path):
    model = _open_model(pdf_path)
    try:
        catalog_before = model.doc.xref_object(model.doc.pdf_catalog(), compressed=True)
        xref_len_before = model.doc.xref_length()
        sid = model.get_active_session_id()
        assert model.tools.prepare_doc_for_save(sid) is None
        assert model.doc.xref_object(model.doc.pdf_catalog(), compressed=True) == catalog_before
        assert model.doc.xref_length() == xref_len_before
        assert _EMBED not in model.doc.embfile_names()
    finally:
        model.close_all_sessions()


def test_watermarks_round_trip_through_save(tmp_path, pdf_path):
    # Guard: pre-existing behaviour that the fix must keep.
    out = tmp_path / "wm.pdf"
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    reopened = _open_model(out)
    try:
        texts = [wm["text"] for wm in reopened.tools.watermark.get_watermarks()]
        assert texts == ["DRAFT"]
    finally:
        reopened.close_all_sessions()


def test_removed_watermarks_do_not_reload_after_save(tmp_path, pdf_path):
    # Guard: a previous attachment is rewritten as an empty list (pinned
    # existing behaviour), so no stale watermark data survives.
    out = tmp_path / "wm.pdf"
    model = _open_model(pdf_path)
    try:
        model.tools.watermark.add_watermark([1], "DRAFT")
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    model = _open_model(out)
    try:
        (wm,) = model.tools.watermark.get_watermarks()
        assert model.tools.watermark.remove_watermark(wm["id"])
        model.save_as(str(out))
    finally:
        model.close_all_sessions()

    with fitz.open(str(out)) as reopened:
        assert _EMBED in reopened.embfile_names()
        assert json.loads(reopened.embfile_get(_EMBED).decode("utf-8")) == []

    final = _open_model(out)
    try:
        assert final.tools.watermark.get_watermarks() == []
    finally:
        final.close_all_sessions()


def test_unreadable_embed_tree_falls_back_to_clearing(pdf_path, monkeypatch):
    # Guard for fail-closed: if the attachment list cannot be read, keep the
    # old clear-and-rewrite path instead of skipping (never leave stale data).
    model = _open_model(pdf_path)
    try:
        calls: list[list[dict]] = []
        tool = model.tools.watermark
        monkeypatch.setattr(
            tool, "_write_watermarks_embed", lambda doc, wms: calls.append(list(wms))
        )
        monkeypatch.setattr(
            type(model.doc),
            "embfile_names",
            lambda self: (_ for _ in ()).throw(RuntimeError("broken names tree")),
        )
        assert tool.prepare_doc_for_save(model.get_active_session_id(), model.doc) is None
        assert calls == [[]]
    finally:
        monkeypatch.undo()
        model.close_all_sessions()
