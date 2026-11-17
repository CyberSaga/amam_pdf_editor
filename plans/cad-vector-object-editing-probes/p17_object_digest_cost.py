"""S0-P17: cost of a per-object digest table over a whole document (the runtime permitted-write diff, D23 Rule B).
One pass = for every xref: hash of the object text, plus hash of the raw stream when it is a stream.
Usage: python p17_object_digest_cost.py <pdf> [<pdf> ...]"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path

import fitz


NULL, CONTAINER = b"null", b"container"
PRODUCT = os.environ.get("P17_PRODUCT_REPO", "")
LENGTH = re.compile(r"/Length(?![A-Za-z0-9])\s*\d+(?:\s+\d+\s+R)?")


def digest_table(doc: fitz.Document) -> tuple[dict[int, bytes], int, int]:
    table: dict[int, bytes] = {}
    nstreams = raw = 0
    for x in range(1, doc.xref_length()):
        h = hashlib.blake2b(digest_size=16)
        try:
            text = doc.xref_object(x, compressed=True)
            if text == "null":
                table[x] = NULL
                continue
            if doc.xref_get_key(x, "Type")[1] in ("/ObjStm", "/XRef"):
                table[x] = CONTAINER  # file structure, not a document object
                continue
            if doc.xref_is_stream(x):
                text = LENGTH.sub("", text, count=1)  # a save turns an indirect /Length into a direct one
            h.update(text.encode("utf-8", "surrogatepass"))
            if doc.xref_is_stream(x):
                b = doc.xref_stream_raw(x) or b""
                nstreams += 1
                raw += len(b)
                h.update(b)
        except Exception as exc:  # free or broken entry: record the error text
            h.update(repr(exc).encode())
        table[x] = h.digest()
    return table, nstreams, raw


def differing(a: dict[int, bytes], b: dict[int, bytes]) -> list[int]:
    """Differing xrefs; a file container that became null (or back) across a save and reopen is not a difference."""
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k) and {a.get(k), b.get(k)} != {NULL, CONTAINER})


def cycle(path: str, page_index: int) -> None:
    """before -> edit one content stream -> after -> restore from a garbage=0 snapshot -> after."""
    doc = fitz.open(path)
    print(f"{Path(path).name} p{page_index + 1}: images on page {len(doc[page_index].get_images(full=True))}")
    t0, *_ = digest_table(doc)
    snap = doc.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)
    t_after_snap, *_ = digest_table(doc)
    print(f"  taking the snapshot changes {len(differing(t0, t_after_snap))} objects of the live document")
    page = doc[page_index]
    xref = page.get_contents()[0]
    data = doc.xref_stream(xref)
    doc.update_stream(xref, data[: len(data) // 2] + b"\n" + data[len(data) // 2 :], compress=False)
    t1, *_ = digest_table(doc)
    d = differing(t0, t1)
    print(f"  after update_stream(xref {xref}): {len(d)} objects differ: {d[:8]}; xref_length {len(t0) + 1} -> {len(t1) + 1}")
    restored = fitz.open("pdf", snap)
    t2, *_ = digest_table(restored)
    d = differing(t0, t2)
    print(f"  after restore (reopen of the snapshot): {len(d)} objects differ from the pre-commit table; "
          f"xref_length {len(t0) + 1} -> {len(t2) + 1}; first {d[:8]}")
    for x in d[:3]:
        a = doc.xref_object(x, compressed=True) if x < doc.xref_length() else "<none>"
        b = restored.xref_object(x, compressed=True) if x < restored.xref_length() else "<none>"
        print(f"    xref {x}: live-after-edit {a[:90]!r} | restored {b[:90]!r}")
    snap2 = restored.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)
    t3, *_ = digest_table(fitz.open("pdf", snap2))
    print(f"  second round trip differs from the first restore on {len(differing(t2, t3))} objects")


def roundtrip(root: str, out: str) -> None:
    """No edit: live table vs the table of the reopened garbage=0 snapshot, over a directory."""
    files = sorted(Path(root).rglob("*.pdf"))
    ok = bad = skipped = live_changed = unreadable = bad_after = 0
    if PRODUCT:  # the product's save prelude, as installed at import of model.doc_bytes
        sys.path.insert(0, PRODUCT)
        from model.doc_bytes import install_page_mode_preserving_prelude

        print('product prelude installed:', install_page_mode_preserving_prelude())
    lines: list[str] = []
    for fp in files:
        try:
            doc = fitz.open(str(fp))
            if doc.needs_pass or not doc.is_pdf or fp.stat().st_size > 60_000_000:
                skipped += 1
                continue
            t0, *_ = digest_table(doc)
            snap = doc.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)
            t1, *_ = digest_table(doc)
            r = fitz.open("pdf", snap)
            t2, *_ = digest_table(r)
        except Exception as exc:
            skipped += 1
            lines.append(f"SKIP {fp.name}: {type(exc).__name__} {str(exc)[:80]}")
            continue
        live_changed += bool(differing(t0, t1))
        bad_after += bool(differing(t1, t2))
        d = differing(t0, t2)
        if not d:
            ok += 1
            continue
        bad += 1
        x = d[0]
        try:
            a = doc.xref_object(x, compressed=True)[:100] if x < doc.xref_length() else "<none>"
            b = r.xref_object(x, compressed=True)[:100] if x < r.xref_length() else "<none>"
        except Exception as exc:
            a = b = f"unreadable: {str(exc)[:60]}"
        unreadable += a.startswith("unreadable")
        lines.append(f"DIFF {fp.name}: {len(d)} objects, xref_length {len(t0) + 1}->{len(t2) + 1}, first {x}: {a!r} | {b!r}")
    head = f"files {len(files)}, equal {ok}, differ {bad}, skipped {skipped}, of the differing {unreadable} have an unreadable object; snapshot changed the live table on {live_changed}; table AFTER capture vs restored differs on {bad_after}"
    Path(out).write_text("\n".join([head, *lines]), encoding="utf-8")
    print(head)


if __name__ == "__main__":
    if sys.argv[1] == "roundtrip":
        roundtrip(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if sys.argv[1] == "cycle":
        cycle(sys.argv[2], int(sys.argv[3]))
        sys.exit(0)
    for arg in sys.argv[1:]:
        p = Path(arg)
        doc = fitz.open(str(p))
        best = 9e9
        for _ in range(3):
            t = time.perf_counter()
            table, ns, raw = digest_table(doc)
            best = min(best, time.perf_counter() - t)
        t = time.perf_counter()
        again, *_ = digest_table(doc)
        diff = sum(1 for k in table if table[k] != again.get(k))
        print(f"{p.name}: file {p.stat().st_size / 1e6:.1f} MB, pages {len(doc)}, xrefs {doc.xref_length():,}, "
              f"streams {ns:,} ({raw / 1e6:.1f} MB raw): one pass {best * 1e3:.0f} ms; repeat differs on {diff}")
        doc.close()
