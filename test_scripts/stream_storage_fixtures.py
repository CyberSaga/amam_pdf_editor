"""Hand-written-xref PDF fixtures for exact stream-storage restore tests.

Builds a single-page PDF whose ``/Contents`` uses one of the seven storage
encodings from ``plans/task15-p4b2-exact-painter-geometry-admission.md``
section 1.3: (a) uncompressed, (b) ``/FlateDecode``, (c) Flate +
``/DecodeParms << /Predictor 12 /Columns 4 >>`` (PNG-Up), (d)
``[/ASCIIHexDecode /FlateDecode]``, (e) tiny (<=20 B) uncompressed, (f)
indirect ``/Length N 0 R`` + ``/Filter N 0 R``, (g) a two-stream
``/Contents`` array with mixed encodings.

Deliberately does NOT use ``fitz.Document.update_stream`` anywhere -- that
is the mechanism ``model.text_commit.inspect.capture_stream_storage`` /
``restore_stream_storage`` exist to work around, and a fixture built with it
would not exercise the encodings those functions must restore. Every object
here is assembled as raw PDF bytes (a conventional single-generation xref
table) and loaded with ``fitz.open(stream=..., filetype="pdf")``.

The page's text content matches ``test_scripts/test_text_commit_boundaries.
py``'s ``_add_tier0_page`` (same TARGET/DOWNSTREAM strings, same Helvetica/
WinAnsiEncoding font resource): cases (a)-(d) are real, bindable Tier 0
candidates usable with ``prepare_plan``/``TieredCommitEngine``/
``EditTextCommand``, not just raw byte fixtures.
"""
from __future__ import annotations

import binascii
import zlib
from pathlib import Path

import fitz

TARGET = "Price 2024"
REPLACEMENT = "Price 2025"  # advance-neutral in Helvetica, matches boundaries.py
DOWNSTREAM = "Downstream line stays"

_BASE_CONTENT = (
    b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "
    b"0 -40 Td (" + DOWNSTREAM.encode() + b") Tj ET"
)

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)

CASES: tuple[str, ...] = ("a", "b", "c", "d", "e", "f", "g")

# Every case whose decoded text is the real _BASE_CONTENT (bindable by
# prepare_plan) -- (e) and (g)'s second stream deliberately are not.
BINDABLE_CASES: tuple[str, ...] = ("a", "b", "c", "d", "f")


def _pad_to_multiple(data: bytes, multiple: int) -> bytes:
    """Right-pad with spaces (harmless trailing content-stream whitespace,
    outside any operator) until ``len(data) % multiple == 0``."""
    pad = (-len(data)) % multiple
    return data + b" " * pad


def png_up_encode(data: bytes, columns: int) -> bytes:
    """PNG-Up (filter type 2) predictor encoding, plan 1.3's recipe: each
    row = filter byte 2, then ``(row - previous_row) mod 256`` per column.
    ``data`` must already be a multiple of ``columns`` bytes long."""
    if len(data) % columns != 0:
        raise ValueError("data length must be a multiple of columns")
    out = bytearray()
    prev = bytes(columns)
    for i in range(0, len(data), columns):
        row = data[i : i + columns]
        out.append(2)
        out.extend((c - p) % 256 for c, p in zip(row, prev))
        prev = row
    return bytes(out)


def _assemble_pdf(bodies: dict[int, bytes], *, root_obj: int = 1) -> bytes:
    """A minimal, conventional single-generation PDF: bodies[n] is the
    bytes placed between ``n 0 obj\\n`` and ``\\nendobj`` for object n
    (objects 1..max(bodies) must all be present)."""
    n = max(bodies)
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (n + 1)
    for i in range(1, n + 1):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n".encode("ascii")
        out += bodies[i]
        out += b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {n + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for i in range(1, n + 1):
        out += f"{offsets[i]:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {n + 1} /Root {root_obj} 0 R >>\nstartxref\n"
        f"{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(out)


def _stream_obj(obj_dict: str, raw: bytes) -> bytes:
    return obj_dict.encode("ascii") + b"\nstream\n" + raw + b"\nendstream"


def _base_bodies(contents_value: str, extra: dict[int, bytes]) -> dict[int, bytes]:
    bodies: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 4 0 R >> >> "
            f"/Contents {contents_value} >>"
        ).encode("ascii"),
        4: _FONT_OBJECT.encode("ascii"),
    }
    bodies.update(extra)
    return bodies


def _case_a() -> bytes:
    """(a) uncompressed."""
    raw = _BASE_CONTENT
    obj = f"<< /Length {len(raw)} >>"
    return _assemble_pdf(_base_bodies("5 0 R", {5: _stream_obj(obj, raw)}))


def _case_b() -> bytes:
    """(b) /FlateDecode."""
    raw = zlib.compress(_BASE_CONTENT)
    obj = f"<< /Length {len(raw)} /Filter /FlateDecode >>"
    return _assemble_pdf(_base_bodies("5 0 R", {5: _stream_obj(obj, raw)}))


def _case_c() -> bytes:
    """(c) Flate + /DecodeParms << /Predictor 12 /Columns 4 >> (PNG-Up)."""
    decoded = _pad_to_multiple(_BASE_CONTENT, 4)
    predicted = png_up_encode(decoded, 4)
    raw = zlib.compress(predicted)
    obj = (
        f"<< /Length {len(raw)} /Filter /FlateDecode "
        "/DecodeParms << /Predictor 12 /Columns 4 >> >>"
    )
    return _assemble_pdf(_base_bodies("5 0 R", {5: _stream_obj(obj, raw)}))


def _case_d() -> bytes:
    """(d) [/ASCIIHexDecode /FlateDecode] -- decode order is filter[0]
    first, so raw-on-disk is the ASCII-hex encoding of the Flate-compressed
    bytes (measured against this PyMuPDF build; see the premise pins in
    test_text_commit_exact_restore.py)."""
    flate = zlib.compress(_BASE_CONTENT)
    raw = binascii.hexlify(flate) + b">"
    obj = f"<< /Length {len(raw)} /Filter [/ASCIIHexDecode /FlateDecode] >>"
    return _assemble_pdf(_base_bodies("5 0 R", {5: _stream_obj(obj, raw)}))


def _case_e() -> bytes:
    """(e) tiny (<=20 B) uncompressed."""
    raw = b"q Q "
    assert len(raw) <= 20
    obj = f"<< /Length {len(raw)} >>"
    return _assemble_pdf(_base_bodies("5 0 R", {5: _stream_obj(obj, raw)}))


def _case_f() -> bytes:
    """(f) indirect /Length N 0 R + /Filter N 0 R."""
    raw = zlib.compress(_BASE_CONTENT)
    obj = "<< /Length 6 0 R /Filter 7 0 R >>"
    return _assemble_pdf(
        _base_bodies(
            "5 0 R",
            {
                5: _stream_obj(obj, raw),
                6: str(len(raw)).encode("ascii"),
                7: b"/FlateDecode",
            },
        )
    )


def _case_g() -> bytes:
    """(g) two-stream /Contents array, mixed encodings (Flate + tiny
    uncompressed)."""
    raw1 = zlib.compress(_BASE_CONTENT)
    obj1 = f"<< /Length {len(raw1)} /Filter /FlateDecode >>"
    raw2 = b"q Q "
    obj2 = f"<< /Length {len(raw2)} >>"
    return _assemble_pdf(
        _base_bodies(
            "[5 0 R 6 0 R]",
            {5: _stream_obj(obj1, raw1), 6: _stream_obj(obj2, raw2)},
        )
    )


_BUILDERS = {
    "a": _case_a,
    "b": _case_b,
    "c": _case_c,
    "d": _case_d,
    "e": _case_e,
    "f": _case_f,
    "g": _case_g,
}


def build_case_bytes(case: str) -> bytes:
    """The raw PDF bytes for fixture ``case`` (one of :data:`CASES`)."""
    try:
        builder = _BUILDERS[case]
    except KeyError:
        raise ValueError(f"unknown fixture case {case!r}") from None
    return builder()


def open_case(case: str) -> fitz.Document:
    """Open fixture ``case`` as an in-memory ``fitz.Document``."""
    return fitz.open(stream=build_case_bytes(case), filetype="pdf")


def write_case_pdf(case: str, path: Path) -> None:
    """Save fixture ``case`` to ``path`` via ``doc.save(garbage=0)`` --
    measured (plan section 1.1) to preserve raw + object bytes identically
    for every encoding here, so a test opening ``path`` through a real
    ``PDFModel`` still sees the exact encoding this module built."""
    doc = open_case(case)
    try:
        doc.save(str(path), garbage=0)
    finally:
        doc.close()


__all__ = [
    "BINDABLE_CASES",
    "CASES",
    "DOWNSTREAM",
    "REPLACEMENT",
    "TARGET",
    "build_case_bytes",
    "open_case",
    "png_up_encode",
    "write_case_pdf",
]
