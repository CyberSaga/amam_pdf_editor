from __future__ import annotations

import fitz
import pytest
from model.pdf_model import PDFModel


@pytest.mark.parametrize("field_type", ["7", "999 0 R"])
@pytest.mark.parametrize("operation", ["update_save", "delete"])
def test_unknown_signature_state_cannot_silently_keep_replaced_content(tmp_path, field_type, operation):
    path = tmp_path / "unknown.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.add_text_annot((50, 50), "OLD-SECRET-MARKER").update()
    field = doc.get_new_xref()
    doc.update_object(field, f"<< /FT {field_type} /T (field) >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<< /Fields [{field} 0 R] >>")
    doc.save(path)
    doc.close()
    original = path.read_bytes()
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        note = model.tools.annotation.get_all_annotations()[0]
        if operation == "update_save":
            assert model.tools.annotation.update_annotation(note["xref"], "replacement")
            with pytest.raises(ValueError, match="signature|簽章"):
                model.save_as(str(path))
            assert model.tools.annotation.get_all_annotations()[0]["text"] == "replacement"
        else:
            with pytest.raises(ValueError, match="signature|簽章"):
                model.tools.annotation.delete_annotation(note["xref"])
            assert model.tools.annotation.get_all_annotations()[0]["text"] == "OLD-SECRET-MARKER"
    finally:
        model.close()
    assert path.read_bytes() == original
