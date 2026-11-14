"""Round-4 probes (scratch copies only; nothing here touches product code).

P7  an orphan object at the TAIL of the xref table across save(garbage=1) + reopen:
    is the slot kept (null) or is the table shortened; what get_new_xref() returns;
    whether update_object/update_stream work at the old number.
P8  fontTools subset determinism: the same face and glyph set subset twice.

Usage: python -I r4_probes_tail_orphan_subset.py <pdf copy> <out dir> <ttf/ttc path> [font number]
"""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import fitz
from fontTools import subset
from fontTools.ttLib import TTFont


def p7(src: Path, out: Path) -> None:
    doc = fitz.open(str(src))
    base_len = doc.xref_length()
    a = doc.get_new_xref()
    doc.update_object(a, "<</Probe /TailOrphanDict>>")
    b = doc.get_new_xref()
    doc.update_object(b, "<</Probe /TailOrphanStream>>")
    doc.update_stream(b, b"orphan stream bytes")
    print("P7 base xref_length", base_len, "orphans", a, b, "live length", doc.xref_length())
    saved = out / "p7_saved.pdf"
    doc.save(str(saved), garbage=1)
    print("P7 live after save: length", doc.xref_length(), "a", doc.xref_object(a)[:40])
    doc.close()

    re = fitz.open(str(saved))
    n = re.xref_length()
    print("P7 reopened xref_length", n, "(orphans were", a, b, ")")
    for x in (a, b):
        if x < n:
            print("   slot", x, "object:", repr(re.xref_object(x)[:40]))
        else:
            print("   slot", x, "is past the end of the table")
    for x in (a, b):
        try:
            re.update_object(x, "<</Probe /Recreated>>")
            print("   update_object at", x, "ok ->", re.xref_object(x)[:40], "length", re.xref_length())
        except Exception as exc:  # noqa: BLE001 - probe reports whatever is raised
            print("   update_object at", x, "raised", type(exc).__name__, str(exc)[:80])
    fresh = re.get_new_xref()
    print("P7 get_new_xref ->", fresh, "length", re.xref_length())
    re.update_object(fresh, "<</Probe /Fresh>>")
    re.update_stream(fresh, b"fresh")
    buf = io.BytesIO()
    re.save(buf, garbage=0)
    again = fitz.open("pdf", buf.getvalue())
    print("P7 after 2nd save: length", again.xref_length(), "fresh:", again.xref_object(fresh)[:40])
    again.close()
    re.close()


def _subset_bytes(path: Path, number: int, text: str, *, pin_time: bool = False) -> bytes:
    font = TTFont(str(path), fontNumber=number, lazy=False, recalcTimestamp=not pin_time)
    opts = subset.Options()
    opts.retain_gids = True
    opts.hinting = True
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.name_IDs = ["*"]
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def p8(face: Path, number: int) -> None:
    text = "包含測試位"
    one = _subset_bytes(face, number, text)
    two = _subset_bytes(face, number, text)
    print("P8 subset sizes", len(one), len(two), "equal bytes:", one == two)
    if one != two:
        f1, f2 = TTFont(io.BytesIO(one)), TTFont(io.BytesIO(two))
        for tag in sorted(set(f1.keys()) | set(f2.keys())):
            if tag == "GlyphOrder":
                continue
            d1 = f1.getTableData(tag) if tag in f1 else b""
            d2 = f2.getTableData(tag) if tag in f2 else b""
            if d1 != d2:
                print("   table differs:", tag)
    print("P8 sha256", hashlib.sha256(one).hexdigest()[:16], hashlib.sha256(two).hexdigest()[:16])
    pin1 = _subset_bytes(face, number, text, pin_time=True)
    pin2 = _subset_bytes(face, number, text, pin_time=True)
    print("P8 recalcTimestamp=False: equal bytes:", pin1 == pin2, hashlib.sha256(pin1).hexdigest()[:16])


if __name__ == "__main__":
    p7(Path(sys.argv[1]), Path(sys.argv[2]))
    p8(Path(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 0)
