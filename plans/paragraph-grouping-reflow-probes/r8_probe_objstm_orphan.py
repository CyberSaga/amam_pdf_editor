"""Probe P9 (2026-11-14): P1/P7 again for the packed full save (garbage=1 + object streams).

After the security merge every full save writes object streams. Question: does an
unreferenced object still become a ``null`` slot (table not shortened, numbers of
surviving objects kept), and do new objects still append past the table?
Synthetic document only; prints the facts.
"""
from __future__ import annotations

import fitz


def main() -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "probe")
    page_xref = page.xref
    orphan = doc.get_new_xref()
    doc.update_object(orphan, "<< /Probe /Orphan >>")
    doc.update_stream(orphan, b"orphan stream bytes")
    referenced = doc.get_new_xref()
    doc.update_object(referenced, "<< /Probe /Kept >>")
    doc.xref_set_key(page_xref, "ProbeKept", f"{referenced} 0 R")
    length_before = doc.xref_length()

    for label, kwargs in (
        ("garbage=1", {"garbage": 1}),
        ("garbage=1 + objstms", {"garbage": 1, "use_objstms": 1}),
    ):
        data = doc.tobytes(**kwargs)
        again = fitz.open(stream=data, filetype="pdf")
        new = again.get_new_xref()
        print(
            label,
            "| length before", length_before,
            "after", again.xref_length() - 1,
            "| orphan slot:", again.xref_object(orphan, compressed=True),
            "| kept:", again.xref_object(referenced, compressed=True),
            "| page xref kept:", again[0].xref == page_xref,
            "| new xref:", new,
        )
        again.close()
    doc.close()


if __name__ == "__main__":
    main()
