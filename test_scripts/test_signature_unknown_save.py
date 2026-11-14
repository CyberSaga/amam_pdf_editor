from __future__ import annotations

import fitz
import pytest
from model.pdf_model import PDFModel

MARKER = b"OLD-SECRET-MARKER"


def _unknown_state_pdf(path, field_type: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.add_text_annot((50, 50), MARKER.decode()).update()
    field = doc.get_new_xref()
    doc.update_object(field, f"<< /FT {field_type} /T (field) >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<< /Fields [{field} 0 R] >>")
    doc.save(path)
    doc.close()
    return path.read_bytes()


@pytest.mark.parametrize("field_type", ["7", "999 0 R"])
@pytest.mark.parametrize("operation", ["update_save", "delete"])
def test_unknown_signature_state_cannot_silently_keep_replaced_content(tmp_path, field_type, operation):
    path = tmp_path / "unknown.pdf"
    original = _unknown_state_pdf(path, field_type)
    assert MARKER in original
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        note = model.tools.annotation.get_all_annotations()[0]
        if operation == "update_save":
            assert model.tools.annotation.update_annotation(note["xref"], "replacement")
        else:
            # The delete itself is not refused (the user must be able to go on);
            # the refusal comes at the save, which is where bytes are written.
            assert model.tools.annotation.delete_annotation(note["xref"])
            assert model.tools.annotation.get_all_annotations() == []
        with pytest.raises(ValueError, match="signature|簽章"):
            model.save_as(str(path))
        assert path.read_bytes() == original  # refused before any write
    finally:
        model.close()
    assert path.read_bytes() == original


@pytest.mark.parametrize("field_type", ["7", "999 0 R"])
@pytest.mark.parametrize("operation", ["update_save", "delete"])
def test_unknown_signature_state_with_consent_is_a_full_rewrite(tmp_path, field_type, operation):
    """The way out: with the user's consent the save is ONE full revision that
    no longer holds the replaced or deleted text (never an append)."""
    path = tmp_path / "unknown.pdf"
    original = _unknown_state_pdf(path, field_type)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        note = model.tools.annotation.get_all_annotations()[0]
        if operation == "update_save":
            assert model.tools.annotation.update_annotation(note["xref"], "replacement")
        else:
            assert model.tools.annotation.delete_annotation(note["xref"])
        model.save_as(str(path), allow_signature_loss=True)
    finally:
        model.close()
    saved = path.read_bytes()
    assert saved != original
    assert not saved.startswith(original)  # not an incremental append
    assert saved.count(b"%%EOF") == 1
    with fitz.open(str(path)) as reopened:
        texts = [a.info.get("content", "") for a in reopened[0].annots() or ()]
        raw = b"".join(
            (reopened.xref_object(x, compressed=True) or "").encode("latin-1", "replace")
            + (reopened.xref_stream(x) or b"")
            for x in range(1, reopened.xref_length())
        )
    assert MARKER.decode() not in texts
    assert MARKER not in raw
    assert texts == (["replacement"] if operation == "update_save" else [])
