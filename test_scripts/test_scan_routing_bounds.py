"""Astra A8 and A9: scan routing is bounded before it decodes and is the same however the page is split.

A8: routing must not run the unrestricted ``xref_stream`` on a compression bomb.
A9: the offload decision is made over the page's streams together, so the same content as 1, 8 or
32 streams routes alike (all offloaded) instead of every piece slipping under the per-stream limit.
"""

from __future__ import annotations

import zlib

import fitz
import pytest

from model import content_scan, pdf_content_ops
from model.pdf_content_ops import INLINE_SCAN_LIMIT_BYTES


def _png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    pix.clear_with(200)
    return pix.tobytes("png")


def _page_with_streams(bodies: list[bytes], *, flate: bool = False) -> fitz.Document:
    """One page with one image; /Contents is one new stream per body (the image Do goes last)."""
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png())
    name = str(page.get_images(full=True)[0][7])
    bodies = list(bodies)
    bodies[-1] += f"q 100 0 0 70 20 150 cm /{name} Do Q\n".encode("ascii")
    xrefs = []
    for body in bodies:
        x = doc.get_new_xref()
        doc.update_object(x, "<< >>")
        if flate:
            doc.update_stream(x, zlib.compress(body, 1), compress=0)
            doc.xref_set_key(x, "Filter", "/FlateDecode")
        else:
            doc.update_stream(x, body)
        xrefs.append(x)
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")
    return doc


@pytest.fixture(autouse=True)
def _clean_cache():
    content_scan.clear_scan_cache()
    yield
    content_scan.clear_scan_cache()


def _distinct_chunks(total: int, parts: int) -> list[bytes]:
    unit = b"0.2 w 10 10 m 12 14 l S\n"
    per = total // parts // len(unit)
    return [unit * per + f"% part {i}\n".encode("ascii") for i in range(parts)]


@pytest.mark.parametrize("parts", [1, 8, 32])
def test_the_same_content_routes_alike_however_it_is_split(parts):
    """About 4 MB: one stream, 8 of 500 KB, or 32 of 126 KB, all of them go to the child."""
    chunks = _distinct_chunks(4_000_000, parts)
    with _page_with_streams(chunks) as doc:
        set_key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert len(set_key) == parts
        assert len(jobs) == parts, f"{parts} streams: {len(jobs)} offloaded"
        walk = pdf_content_ops.PageScanSet(doc, 1)
        assert walk.short_streams == {}


def test_small_total_content_is_still_scanned_in_process():
    with _page_with_streams([b"0 0 m 1 1 l S\n", b"0 0 m 2 2 l S\n"]) as doc:
        _key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert jobs == []
        assert len(pdf_content_ops.PageScanSet(doc, 1).short_streams) == 2


def test_a_just_under_limit_page_in_many_pieces_is_not_offloaded_until_the_total_crosses():
    unit = b"0 0 m 1 1 l S\n"
    n = (INLINE_SCAN_LIMIT_BYTES // 4) // len(unit) - 4
    pieces = [unit * n + f"% {i}\n".encode() for i in range(3)]  # about 0.75 of the limit in total
    with _page_with_streams(pieces) as doc:
        assert pdf_content_ops.page_scan_set(doc, 1)[1] == []


# ---- A8 ------------------------------------------------------------------------------------------

BOMB_SIZE = 8 * 1024 * 1024 + 36  # the reviewer's 8,200 stored bytes -> 8,388,644 decoded


def _spy_decodes(monkeypatch) -> list[int]:
    calls: list[int] = []
    original = fitz.Document.xref_stream

    def spy(self, xref):
        calls.append(int(xref))
        return original(self, xref)

    monkeypatch.setattr(fitz.Document, "xref_stream", spy)
    return calls


def _bomb_page() -> tuple[fitz.Document, int]:
    doc = _page_with_streams([b"0 0 m 1 1 l S\n", b"\x00" * BOMB_SIZE], flate=True)
    page = doc[0]
    return doc, int(page.get_contents()[-1])


def test_routing_never_decodes_a_compression_bomb(monkeypatch):
    doc, bomb = _bomb_page()
    with doc:
        stored = len(doc.xref_stream_raw(bomb))
        assert stored < 100_000  # tiny stored size, huge decoded size
        calls = _spy_decodes(monkeypatch)
        set_key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert bomb not in calls
        assert all(len(payload) < 1_000_000 for _key, payload in jobs)
        assert len(set_key) == 2  # the bomb is still a member of the page's set, only never decoded


def test_discovery_never_decodes_a_compression_bomb(monkeypatch):
    doc, bomb = _bomb_page()
    with doc:
        calls = _spy_decodes(monkeypatch)
        pdf_content_ops.discover_native_image_invocations(doc, 1)
        assert bomb not in calls


def test_a_large_but_honest_stream_is_still_routed_to_the_child():
    body = b"0.2 w 10 10 m 12 14 l S\n" * 170_000  # about 4 MB
    with _page_with_streams([body], flate=True) as doc:
        _key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert len(jobs) == 1 and len(jobs[0][1]) > 4_000_000


def test_the_page_total_is_bounded_too(monkeypatch):
    """Many streams each under the per-stream cap cannot together decode without limit."""
    part = b"0.2 w 10 10 m 12 14 l S\n" * 300_000  # about 7 MB each
    parts = [part + f"% {i}\n".encode() for i in range(8)]  # about 58 MB in all
    with _page_with_streams(parts, flate=True) as doc:
        xrefs = [int(x) for x in doc[0].get_contents()]
        calls = _spy_decodes(monkeypatch)
        _key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert sum(len(p) for _k, p in jobs) <= 40 * 1024 * 1024
        assert len(set(calls) & set(xrefs)) < len(xrefs)
