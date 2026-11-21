"""The one-page scratch copy carries the optional-content state of the source page (A6.0 M6)."""

from __future__ import annotations

import re

import fitz
import pytest

from model import table_objects
from model.page_content_text import content_text


def _lines(data: bytes) -> list[str]:
    with fitz.open("pdf", data) as doc:
        return [ln for ln in content_text(doc[0], "text").splitlines() if ln]


def _live(data: bytes) -> list[str]:
    with fitz.open("pdf", data) as doc:
        return [ln for ln in content_text(doc[0], "text").splitlines() if ln]


def _dup_names() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        a = d.add_ocg("L", on=False)
        b = d.add_ocg("L", on=True)
        pg.insert_text((20, 50), "A off", oc=a)
        pg.insert_text((20, 90), "B on", oc=b)
        return d.tobytes()


def _form_nested() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        c = d.add_ocg("F", on=False)
        pg.insert_text((20, 50), "visible")
        form = d.get_new_xref()
        d.update_object(
            form,
            "<< /Type /XObject /Subtype /Form /BBox [0 0 300 300] /Resources << /Font << /F0 << /Type /Font"
            f" /Subtype /Type1 /BaseFont /Helvetica >> >> /Properties << /M0 {c} 0 R >> >> /OC {c} 0 R >>",
        )
        d.update_stream(form, b"BT /F0 12 Tf 20 150 Td (form hidden) Tj ET")
        res = d.xref_get_key(pg.xref, "Resources")
        d.xref_set_key(int(res[1].split()[0]), "XObject", f"<< /Fm0 {form} 0 R >>")
        cs = d[0].get_contents()[-1]
        d.update_stream(cs, d.xref_stream(cs) + b" /Fm0 Do")
        return d.tobytes()


def _ocmd() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        a = d.add_ocg("A", on=False)
        b = d.add_ocg("B", on=True)
        m = d.get_new_xref()
        d.update_object(m, f"<< /Type /OCMD /OCGs [{a} 0 R {b} 0 R] /P /AllOn >>")
        pg.insert_text((20, 50), "plain")
        pg.insert_text((20, 90), "via ocmd", oc=m)
        return d.tobytes()


@pytest.mark.parametrize("build", [_dup_names, _form_nested, _ocmd])
def test_the_copy_extracts_what_the_live_page_extracts(build):
    data = build()
    with fitz.open("pdf", data) as doc:
        copy = table_objects.scratch_page_bytes(doc, 1)
    assert _lines(copy) == _live(data)


def test_a_hidden_group_stays_hidden_in_the_copy():
    with fitz.open("pdf", _dup_names()) as doc:
        copy = table_objects.scratch_page_bytes(doc, 1)
    assert _lines(copy) == ["B on"]


def test_the_copy_bytes_are_stable_with_optional_content():
    with fitz.open("pdf", _form_nested()) as doc:
        assert table_objects.scratch_page_bytes(doc, 1) == table_objects.scratch_page_bytes(doc, 1)


def test_a_page_without_optional_content_is_copied_as_before():
    with fitz.open() as d:
        d.new_page().insert_text((20, 50), "plain")
        data = d.tobytes()
    with fitz.open("pdf", data) as doc:
        copy = table_objects.scratch_page_bytes(doc, 1)
        assert doc.get_ocgs() == {}
    with fitz.open("pdf", copy) as c:
        assert c.get_ocgs() == {}

def _usage_print_off() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        g = d.add_ocg("P", on=True)
        d.xref_set_key(g, "Usage", "<< /CreatorInfo << /Creator (t) /Subtype /Print >> /Print << /PrintState /OFF >> >>")
        pg.insert_text((20, 50), "visible", oc=g)
        return d.tobytes()


def _name_reads_like_a_reference() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        g = d.add_ocg("(42 0 R)", on=False)
        pg.insert_text((20, 50), "visible")
        pg.insert_text((20, 90), "hidden", oc=g)
        return d.tobytes()


def _inherited_resources() -> bytes:
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        g = d.add_ocg("H", on=False)
        pg.insert_text((20, 50), "visible")
        pg.insert_text((20, 90), "hidden", oc=g)
        res = d.xref_get_key(pg.xref, "Resources")
        pages = int(d.xref_get_key(pg.xref, "Parent")[1].split()[0])
        d.xref_set_key(pages, "Resources", res[1])
        d.xref_set_key(pg.xref, "Resources", "null")
        return d.tobytes()


def _empty_resources_with_a_group_elsewhere() -> bytes:
    with fitz.open() as d:
        d.add_ocg("elsewhere", on=False)
        pg = d.new_page(width=300, height=300)
        d.xref_set_key(pg.xref, "Resources", "<<>>")
        return d.tobytes()


@pytest.mark.parametrize(
    "build", [_usage_print_off, _name_reads_like_a_reference, _inherited_resources, _empty_resources_with_a_group_elsewhere]
)
def test_the_copy_extracts_what_the_live_page_extracts_edge_cases(build):
    data = build()
    with fitz.open("pdf", data) as doc:
        copy = table_objects.scratch_page_bytes(doc, 1)
    assert _lines(copy) == _live(data)


def test_a_page_without_optional_content_is_the_plain_insert_pdf_copy():
    with fitz.open() as d:
        d.new_page().insert_text((20, 50), "plain")
        data = d.tobytes()
    with fitz.open("pdf", data) as doc, fitz.open() as plain:
        plain.insert_pdf(doc, from_page=0, to_page=0, annots=False, links=False, widgets=False)
        assert table_objects.scratch_page_bytes(doc, 1) == plain.tobytes(no_new_id=True)


def test_two_groups_collapsed_into_one_are_refused(monkeypatch):
    with fitz.open("pdf", _dup_names()) as doc:
        real = table_objects._Pairing.pair_refs

        def collapse(self, stext, dtext, what):
            # the copy's second group reference now reads as the first one
            m0, m1 = re.search(r"/MC0 (\d+) 0 R", dtext), re.search(r"/MC1 (\d+) 0 R", dtext)
            if m0 and m1:
                dtext = dtext.replace(m1.group(0), f"/MC1 {m0.group(1)} 0 R")
            real(self, stext, dtext, what)

        monkeypatch.setattr(table_objects._Pairing, "pair_refs", collapse)
        with pytest.raises(ValueError, match="pairs two objects"):
            table_objects.scratch_page_bytes(doc, 1)


def test_a_copy_that_does_not_mirror_the_source_is_refused(monkeypatch):
    with fitz.open("pdf", _dup_names()) as doc:
        monkeypatch.setattr(table_objects, "_REF", re.compile(r"(\d+) (\d+) X"))
        with pytest.raises(ValueError):
            table_objects.scratch_page_bytes(doc, 1)


def _indirect_config() -> bytes:
    data = _dup_names()
    with fitz.open("pdf", data) as d:
        ocp = d.xref_get_key(d.pdf_catalog(), "OCProperties")
        dxref = d.get_new_xref()
        text = d.xref_object(int(ocp[1].split()[0]), compressed=True) if ocp[0] == "xref" else ocp[1]
        d_text = text[text.index("/D") + 2 : text.rindex(">>")]
        d.update_object(dxref, d_text.strip())
        d.xref_set_key(d.pdf_catalog(), "OCProperties", text[: text.index("/D")] + f"/D {dxref} 0 R>>")
        return d.tobytes()


def _encrypted_form() -> bytes:
    with fitz.open("pdf", _form_nested()) as d:
        return d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")


@pytest.mark.parametrize("build", [_indirect_config, _encrypted_form])
def test_the_copy_extracts_what_the_live_page_extracts_for_other_serializations(build):
    data = build()
    with fitz.open("pdf", data) as doc:
        if doc.needs_pass:
            assert doc.authenticate("u")
        live = [ln for ln in content_text(doc[0], "text").splitlines() if ln]
        copy = table_objects.scratch_page_bytes(doc, 1)
    assert _lines(copy) == live


def _indirect_length() -> bytes:
    data = _form_nested()
    with fitz.open("pdf", data) as d:
        form = next(x for x in range(1, d.xref_length()) if d.xref_get_key(x, "Subtype")[1] == "/Form")
        length = d.get_new_xref()
        d.update_object(length, str(len(d.xref_stream_raw(form))))
        d.xref_set_key(form, "Length", f"{length} 0 R")
        return d.tobytes(garbage=0)


def test_a_form_with_an_indirect_length_is_copied():
    data = _indirect_length()
    with fitz.open("pdf", data) as doc:
        assert doc.xref_get_key(next(x for x in range(1, doc.xref_length()) if doc.xref_get_key(x, "Subtype")[1] == "/Form"), "Length")[0] in ("xref", "int")
        copy = table_objects.scratch_page_bytes(doc, 1)
    assert _lines(copy) == _live(data)
