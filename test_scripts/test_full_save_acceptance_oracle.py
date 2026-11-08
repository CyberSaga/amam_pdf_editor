from __future__ import annotations

import fitz
import pytest

from test_scripts import true_text_acceptance_helpers as helpers


def _check(live, saved):
    helpers._assert_saved_state_preserved(live, saved)


def _make():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 80), "unchanged content")
    return doc


@pytest.mark.parametrize("forgery", ["dictionary", "body"])
def test_wellformed_object_stream_cannot_hide_new_content(forgery):
    live = _make()
    saved = fitz.open("pdf", live.tobytes())
    try:
        xref = saved.get_new_xref()
        if forgery == "dictionary":
            saved.update_object(xref, "<< /Type /ObjStm /N 0 /First 0 /Hidden (new payload) >>")
            saved.update_stream(xref, b"")
        else:
            header = f"{saved[0].xref} 0 ".encode()
            saved.update_object(xref, f"<< /Type /ObjStm /N 1 /First {len(header)} >>")
            saved.update_stream(xref, header + b"<< /Secret (x) >>")
        with pytest.raises(AssertionError):
            _check(live, saved)
    finally:
        live.close()
        saved.close()


def test_packed_rewrite_may_replace_old_storage_containers():
    doc = _make()
    live = fitz.open("pdf", doc.tobytes(use_objstms=1))
    doc.close()
    saved = fitz.open("pdf", live.tobytes(garbage=1, use_objstms=1))
    try:
        _check(live, saved)
    finally:
        live.close()
        saved.close()


def test_pruned_trailing_orphan_does_not_require_preserving_xref_length():
    live = _make()
    orphan = live.get_new_xref()
    live.update_object(orphan, "<< /RemovedSecret (deleted) >>")
    saved = fitz.open("pdf", live.tobytes(garbage=1))
    try:
        _check(live, saved)
    finally:
        live.close()
        saved.close()


@pytest.mark.parametrize("mutation", ["font", "stream", "stream_dictionary", "resource", "extra", "extra_fake_objstm", "root"])
def test_reachable_mutations_and_added_content_fail(mutation):
    live = _make()
    saved = fitz.open("pdf", live.tobytes())
    try:
        if mutation == "font":
            font = saved[0].get_fonts()[0][0]
            saved.xref_set_key(font, "BaseFont", "/Courier")
        elif mutation == "stream":
            xref = saved[0].get_contents()[0]
            saved.update_stream(xref, b"0 0 m 100 100 l S")
        elif mutation == "stream_dictionary":
            saved.xref_set_key(saved[0].get_contents()[0], "DecodeParms", "<< /Predictor 2 >>")
        elif mutation == "resource":
            saved.xref_set_key(saved[0].xref, "Resources", "<<>>")
        elif mutation == "extra":
            xref = saved.get_new_xref()
            saved.update_object(xref, "<< /Unexpected (content) >>")
        elif mutation == "extra_fake_objstm":
            xref = saved.get_new_xref()
            saved.update_object(xref, "<< /Type /ObjStm >>")
            saved.update_stream(xref, b"arbitrary hidden content")
        else:
            saved.xref_set_key(-1, "Root", "2 0 R")
        with pytest.raises(AssertionError):
            _check(live, saved)
    finally:
        live.close()
        saved.close()


def test_dictionary_reordering_is_accepted_but_values_remain_exact():
    assert helpers._objects_semantically_equal("<< /A 1 /B 2 >>", "<< /B 2 /A 1 >>")
    assert not helpers._objects_semantically_equal("<< /A 1 /B 2 >>", "<< /B 3 /A 1 >>")


def test_declared_target_cannot_hide_undeclared_font_change():
    live = _make()
    saved = fitz.open("pdf", live.tobytes())
    try:
        target = saved[0].get_contents()[0]
        saved.update_stream(target, b"BT /helv 11 Tf 1 0 0 1 50 80 Tm (changed content) Tj ET")
        helpers._assert_saved_state_preserved(live, saved, changed_streams=frozenset({target}))
        font = saved[0].get_fonts()[0][0]
        saved.xref_set_key(font, "BaseFont", "/Courier")
        with pytest.raises(AssertionError):
            helpers._assert_saved_state_preserved(live, saved, changed_streams=frozenset({target}))
    finally:
        live.close()
        saved.close()


def test_declared_target_dictionary_cannot_change_unrelated_keys():
    live = _make()
    saved = fitz.open("pdf", live.tobytes())
    try:
        target = saved[0].get_contents()[0]
        saved.update_stream(target, b"BT /helv 11 Tf (changed) Tj ET")
        saved.xref_set_key(target, "Subtype", "/Form")
        with pytest.raises(AssertionError):
            helpers._assert_saved_state_preserved(live, saved, changed_streams=frozenset({target}))
    finally:
        live.close()
        saved.close()


def _raw_storage_fixture(indirect_length):
    payload = b"0 0 10 10 re S\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R" + (b"" if indirect_length else b" /Nullable 5 0 R") + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
        b"<< /Length " + (b"5 0 R" if indirect_length else str(len(payload)).encode()) + b" >>\nstream\n" + payload + b"endstream",
        str(len(payload)).encode() if indirect_length else b"null",
    ]
    data = b"%PDF-1.7\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data


@pytest.mark.parametrize("indirect_length", [True, False])
def test_native_writer_storage_normalizations_preserve_values(indirect_length):
    raw = _raw_storage_fixture(indirect_length)
    source = fitz.open("pdf", raw)
    writer = fitz.open("pdf", raw)
    saved = fitz.open("pdf", writer.tobytes(garbage=1, use_objstms=1))
    try:
        assert not source.is_repaired and not saved.is_repaired
        assert source[0].get_pixmap().samples == saved[0].get_pixmap().samples
        helpers._assert_saved_state_preserved(source, saved)
    finally:
        source.close()
        writer.close()
        saved.close()


def test_unchanged_null_reference_is_accepted():
    raw = _raw_storage_fixture(False)
    source, saved = fitz.open("pdf", raw), fitz.open("pdf", raw)
    try:
        helpers._assert_saved_state_preserved(source, saved)
    finally:
        source.close()
        saved.close()


@pytest.mark.parametrize("detach", [False, True])
def test_null_normalization_does_not_hide_new_payload(detach):
    raw = _raw_storage_fixture(False)
    source, saved = fitz.open("pdf", raw), fitz.open("pdf", raw)
    try:
        saved.update_object(5, "<< /Hidden (new data) >>")
        if detach:
            saved.xref_set_key(saved.pdf_catalog(), "Nullable", "null")
        with pytest.raises(AssertionError):
            helpers._assert_saved_state_preserved(source, saved)
    finally:
        source.close()
        saved.close()


def test_non_null_alias_identity_is_not_canonicalized_away():
    source = fitz.open("pdf", _raw_storage_fixture(False))
    source.update_object(5, "<< /Value 1 >>")
    alias = source.get_new_xref()
    source.update_object(alias, "<< /Value 1 >>")
    saved = fitz.open("pdf", source.tobytes())
    try:
        saved.xref_set_key(saved.pdf_catalog(), "Nullable", f"{alias} 0 R")
        with pytest.raises(AssertionError):
            helpers._assert_saved_state_preserved(source, saved)
    finally:
        source.close()
        saved.close()


def test_stream_length_object_used_as_real_content_cannot_be_dropped():
    source = fitz.open("pdf", _raw_storage_fixture(True))
    source.xref_set_key(source.pdf_catalog(), "MeaningfulCount", "5 0 R")
    saved = fitz.open("pdf", source.tobytes())
    try:
        saved.update_object(5, "null")
        with pytest.raises(AssertionError):
            helpers._assert_saved_state_preserved(source, saved)
    finally:
        source.close()
        saved.close()
