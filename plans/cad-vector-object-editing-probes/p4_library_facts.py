"""S0-P4: PyMuPDF 1.27 facts the CAD vector plan relies on. Usage: python p4_library_facts.py <sample.pdf>"""
from __future__ import annotations

import re
import sys
import zlib

import fitz

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))

print("pymupdf", fitz.VersionBind)
src = sys.argv[1]
doc = fitz.open(src)
print("pages", doc.page_count, "encrypted", doc.is_encrypted, "xrefs", doc.xref_length())
page = doc[0]
cont = page.get_contents()
print("page0 contents xrefs", cont[:5], "n", len(cont))
print("page0 xref", page.xref, "/Contents raw:", doc.xref_get_key(page.xref, "Contents"))

# a) dictionary after update_stream(compress=False) for various source shapes
def mk(filter_expr, parms=None, data=b"q 1 0 0 1 0 0 cm 0 0 m 9 9 l S Q\n", dl=False):
    d = fitz.open()
    d.new_page()
    x = d.get_new_xref()
    d.update_object(x, "<<>>")
    d.update_stream(x, data, compress=False)
    if filter_expr:
        d.xref_set_key(x, "Filter", filter_expr)
    if parms:
        d.xref_set_key(x, "DecodeParms", parms)
    if dl:
        d.xref_set_key(x, "DL", "123")
    return d, x

for label, f, pm, dl in [
    ("array a85+flate", "[/ASCII85Decode /FlateDecode]", None, False),
    ("flate+predictor", "/FlateDecode", "<</Predictor 12 /Columns 4>>", False),
    ("with /DL", "/FlateDecode", None, True),
]:
    d, x = mk(f, pm, dl=dl)
    before = d.xref_object(x, compressed=False)
    d.update_stream(x, zlib.compress(b"q Q\n"), compress=False)
    after = d.xref_object(x, compressed=False)
    print(f"[a] {label}\n   before: {before!r}\n   after : {after!r}")
    d.xref_set_key(x, "Filter", "/FlateDecode")
    d.xref_set_key(x, "DecodeParms", "null")
    d.xref_set_key(x, "DL", "null")
    print("   fixed :", d.xref_object(x, compressed=False).replace("\n", " "))
    print("   decodes:", d.xref_stream(x))

# b) snapshot garbage=0 reference printing and numbering
snap = doc.tobytes(garbage=0)
print("[b] snapshot bytes", len(snap), "has /ObjStm:", b"/ObjStm" in snap)
r = fitz.open("pdf", snap)
print("   same xref_length:", r.xref_length() == doc.xref_length(), r.xref_length(), doc.xref_length())
cx = cont[0]
pat = re.compile(rb"(?<![0-9])%d\s+[0-9]+\s+R(?![A-Za-z0-9])" % cx)
print("   refs to content xref", cx, "in snapshot:", len(pat.findall(snap)))
# stream contents equality via snapshot numbering
print("   decoded equal after snapshot reload:", r.xref_stream(cx) == doc.xref_stream(cx))

# in-memory serialiser used by the app
try:
    from model import doc_bytes
    b2 = doc_bytes.serialize_doc(doc, encryption=fitz.PDF_ENCRYPT_KEEP, in_memory=True)
    print("   doc_bytes.serialize_doc ok", len(b2), "ObjStm:", b"/ObjStm" in b2, "refs:", len(pat.findall(b2)))
except Exception as e:  # noqa: BLE001
    print("   doc_bytes failed", type(e).__name__, e)

# c) page object listed twice in the page tree
d = fitz.open()
d.new_page()
pg = d[0].xref
pages_xref = int(d.xref_get_key(d.pdf_catalog(), "Pages")[1].split()[0])
d.xref_set_key(pages_xref, "Kids", f"[{pg} 0 R {pg} 0 R]")
d.xref_set_key(pages_xref, "Count", "2")
raw = d.tobytes()
d2 = fitz.open("pdf", raw)
print("[c] dup page object: page_count", d2.page_count, "page xrefs", [d2[i].xref for i in range(d2.page_count)])

# d) copy of a shared stream; repoint
d = fitz.open()
d.new_page()
d.new_page()
P1 = d.page_xref(0)
P2 = d.page_xref(1)
x = d.get_new_xref()
d.update_object(x, "<<>>")
d.update_stream(x, b"0 0 m 5 5 l S\n")
d.xref_set_key(P1, "Contents", f"{x} 0 R")
d.xref_set_key(P2, "Contents", f"{x} 0 R")
n = d.get_new_xref()
d.update_object(n, "<<>>")
d.update_stream(n, b"1 1 m 2 2 l S\n")
d.xref_set_key(P1, "Contents", f"[{n} 0 R]")
print("[d] after repoint: p1", d[0].get_contents(), "p2", d[1].get_contents(), "x intact:", d.xref_stream(x))
print("    xref_epoch/other effects not measurable here (model-level)")
