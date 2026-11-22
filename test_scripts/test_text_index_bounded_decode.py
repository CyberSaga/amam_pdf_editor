"""H23 finding 9: the text-index routing never fully decodes a stream in the GUI process.

A tiny compressed body can decode to hundreds of MB.  Routing is a cost guess, so a stream that
cannot be bounded cheaply is "over the limit" (sent to the child), and a single Flate stream is
decoded with a cap.
"""
from __future__ import annotations

import time
import zlib

import fitz

from model import text_index_jobs
from test_scripts.test_table_page_input import _raw_pdf, _stream

LIMIT = text_index_jobs.TEXT_INLINE_LIMIT_BYTES
ZEROS = 200 * 1024 * 1024


class SpyDoc:
    """A delegating wrapper that records every unrestricted decode (``xref_stream``)."""

    def __init__(self, doc: fitz.Document) -> None:
        self._doc = doc
        self.decodes: list[int] = []

    def xref_stream(self, xref: int):
        self.decodes.append(xref)
        return self._doc.xref_stream(xref)

    def __getitem__(self, index):
        return self._doc[index]

    def __getattr__(self, name):
        return getattr(self._doc, name)


def _pdf(body: bytes, filter_entry: bytes) -> bytes:
    return _raw_pdf(
        {
            1: (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
            2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
            3: (0, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << >> >>"),
            4: (0, _stream(body, filter_entry)),
        }
    )


def _cost(pdf: bytes) -> tuple[int, list[int], float, int]:
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        raw = len(doc.xref_stream_raw(4))
        spy = SpyDoc(doc)
        t0 = time.perf_counter()
        cost = text_index_jobs.text_index_cost_bytes(spy, 1)
        return cost, spy.decodes, time.perf_counter() - t0, raw


def test_a_single_flate_bomb_is_over_the_limit_without_an_unbounded_decode():
    packed = zlib.compress(b"\x00" * (60 * 1024 * 1024), 9)  # Flate tops out near 1000:1
    cost, decodes, elapsed, raw = _cost(_pdf(packed, b"/Filter /FlateDecode "))
    assert raw <= LIMIT, "the fixture must be small raw, or the raw-size shortcut hides the bug"
    assert cost > LIMIT
    assert decodes == []
    assert elapsed < 1.0


def test_a_double_flate_bomb_is_over_the_limit_without_an_unbounded_decode():
    packed = zlib.compress(zlib.compress(b"\x00" * ZEROS, 9), 9)
    cost, decodes, elapsed, raw = _cost(_pdf(packed, b"/Filter [/FlateDecode /FlateDecode] "))
    assert raw <= LIMIT
    assert cost > LIMIT
    assert decodes == []
    assert elapsed < 1.0


def test_an_other_filter_chain_is_over_the_limit_and_not_decoded():
    packed = zlib.compress(b"\x00" * (25 * 1024 * 1024), 9).hex().encode() + b">"
    cost, decodes, _elapsed, raw = _cost(_pdf(packed, b"/Filter [/ASCIIHexDecode /FlateDecode] "))
    assert raw <= LIMIT, "the fixture must be small raw, or the raw-size shortcut hides the bug"
    assert cost > LIMIT
    assert decodes == []


def test_a_small_flate_stream_still_counts_its_decoded_length():
    data = b"BT /F1 9 Tf 10 10 Td (label) Tj ET\n" * 10
    cost, decodes, _elapsed, _raw = _cost(_pdf(zlib.compress(data), b"/Filter /FlateDecode "))
    assert cost == len(data)
    assert decodes == []


def test_a_plain_stream_counts_its_length():
    cost, decodes, _elapsed, _raw = _cost(_pdf(b"q Q q Q", b""))
    assert cost == 7 and decodes == []


def test_a_corrupt_flate_stream_is_over_the_limit():
    cost, _decodes, _elapsed, _raw = _cost(_pdf(b"not zlib data at all", b"/Filter /FlateDecode "))
    assert cost > LIMIT
