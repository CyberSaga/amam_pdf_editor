"""S0-P4 rest: object-stream sources and encrypted documents. Usage: python p4b_objstm_encrypted.py <sample.pdf>"""
from __future__ import annotations

import re
import sys

import fitz

src = sys.argv[1]
d = fitz.open(src)
pg = d[0]
cx = pg.get_contents()[0]
raw = d.tobytes(use_objstms=1, garbage=3)
r = fitz.open("pdf", raw)
print("[objstm] source with /ObjStm:", b"/ObjStm" in raw, "xref_length", r.xref_length(), "page contents", r[0].get_contents())
snap = r.tobytes(garbage=0)
print("   garbage=0 snapshot of that doc still has /ObjStm:", b"/ObjStm" in snap)
cx2 = r[0].get_contents()[0]
pat = re.compile(rb"(?<![0-9])%d\s+[0-9]+\s+R(?![A-Za-z0-9])" % cx2)
print("   refs to content stream", cx2, "as plain text in snapshot:", len(pat.findall(snap)), "| Page object compressed:", r.xref_object(r[0].xref, compressed=True)[:60].replace("\n", " "))
print("   page /Contents key:", r.xref_get_key(r[0].xref, "Contents"))
# encrypted
e = d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u", garbage=0)
re_ = fitz.open("pdf", e)
print("[encrypted] needs_pass", re_.needs_pass, "auth:", re_.authenticate("u"))
c = re_[0].get_contents()[0]
before = re_.xref_stream(c)
re_.update_stream(c, before + b"\n", compress=True)
print("   update_stream ok; decoded grew:", len(re_.xref_stream(c)) == len(before) + 1)
snap2 = re_.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)
r2 = fitz.open("pdf", snap2)
print("   snapshot reopen needs_pass", r2.needs_pass, "auth", r2.authenticate("u"), "decoded equal:", r2.xref_stream(c) == re_.xref_stream(c))
print("   plain-text refs in encrypted snapshot:", len(re.findall(rb"(?<![0-9])%d\s+[0-9]+\s+R(?![A-Za-z0-9])" % c, snap2)))
