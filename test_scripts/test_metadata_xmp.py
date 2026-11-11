"""An edited document-info title must not survive in the XMP packet (secure-save leak)."""
from __future__ import annotations

import fitz
import pytest

from model.pdf_model import PDFModel

_XMP = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:title><rdf:Alt><rdf:li xml:lang=\"x-default\">SECRET-OLD-TITLE</rdf:li></rdf:Alt></dc:title>"
    "</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
)


@pytest.fixture
def model_with_xmp(tmp_path):
    path = tmp_path / "xmp.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), "body")
        doc.set_metadata({"title": "SECRET-OLD-TITLE"})
        doc.set_xml_metadata(_XMP)
        doc.save(str(path))
    model = PDFModel()
    model.open_pdf(str(path))
    yield model, path
    model.close()


def test_metadata_edit_drops_the_old_xmp_title(model_with_xmp, tmp_path) -> None:
    model, _path = model_with_xmp
    assert "SECRET-OLD-TITLE" in model.doc.get_xml_metadata()
    assert model.set_editable_metadata({"title": "New", "author": "", "subject": "", "keywords": ""})
    out = tmp_path / "out.pdf"
    model.save_as(str(out))
    data = out.read_bytes()
    assert b"SECRET-OLD-TITLE" not in data
    with fitz.open(str(out)) as saved:
        assert saved.metadata["title"] == "New"
        assert "SECRET-OLD-TITLE" not in (saved.get_xml_metadata() or "")


def test_no_change_edit_keeps_the_xmp(model_with_xmp) -> None:
    model, _path = model_with_xmp
    current = model.get_editable_metadata()
    assert model.set_editable_metadata(current) is False
    assert "SECRET-OLD-TITLE" in model.doc.get_xml_metadata()
