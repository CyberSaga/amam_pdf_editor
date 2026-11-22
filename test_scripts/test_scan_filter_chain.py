"""R3 (Astra round 4): the /Filter value is parsed, not split on whitespace.

MuPDF returns ``[/FlateDecode/FlateDecode]`` for a valid double-Flate chain; the bound must accept
valid small chains of 1, 2 and 4 stages (decoded and scanned) while the 5-stage chain, the bombs and a
corrupt Flate stream stay bounded and are never decoded by MuPDF."""

from __future__ import annotations

import zlib

import fitz
import pytest

from model import content_scan, pdf_content_ops
from test_scripts.test_scan_bounds_class import BOMB, _chain_bomb_page
from test_scripts.test_scan_routing_bounds import _page_with_streams, _spy_decodes

PLAIN = b"q 1 0 0 1 0 0 cm /Im0 Do Q\n"
ROOM = 1_000_000


@pytest.fixture(autouse=True)
def _clean_cache():
    content_scan.clear_scan_cache()
    yield
    content_scan.clear_scan_cache()


def _chain(data: bytes, stages: int) -> bytes:
    for _ in range(stages):
        data = zlib.compress(data, 9)
    return data


def _stream_doc(payload: bytes, filter_value: str) -> tuple[fitz.Document, int]:
    doc = _page_with_streams([b"0 0 m 1 1 l S\n", b"0 0 m 1 1 l S\n"])
    xref = int(doc[0].get_contents()[-1])
    doc.update_stream(xref, payload, compress=0)
    doc.xref_set_key(xref, "Filter", filter_value)
    return doc, xref


@pytest.mark.parametrize(
    "stages,spelling",
    [
        (1, "/FlateDecode"),
        (1, "[/FlateDecode]"),
        (1, "/Fl"),
        (2, "[/FlateDecode /FlateDecode]"),
        (2, "[/FlateDecode/FlateDecode]"),
        (2, "[/Fl/Fl]"),
        (4, "[/FlateDecode/FlateDecode/FlateDecode/FlateDecode]"),
        (4, "[/FlateDecode /Fl /FlateDecode /Fl]"),
    ],
)
def test_valid_small_flate_chains_decode_and_are_scanned(stages, spelling):
    doc, xref = _stream_doc(_chain(PLAIN, stages), spelling)
    with doc:
        assert pdf_content_ops._bounded_stream(doc, xref, ROOM) == PLAIN
        members: dict = {}
        scan = pdf_content_ops._scan_for_discovery(doc, xref, members)
        assert scan is not None and [d.name for d in scan.dos] == ["Im0"]


def test_a_five_stage_chain_is_over_the_cap_and_never_decoded(monkeypatch):
    doc, xref = _stream_doc(_chain(PLAIN, 5), "[/FlateDecode/FlateDecode/FlateDecode/FlateDecode/FlateDecode]")
    with doc:
        calls = _spy_decodes(monkeypatch)
        assert pdf_content_ops._bounded_stream(doc, xref, ROOM) is None
        assert xref not in calls


def test_a_non_flate_or_unparseable_name_is_over_the_cap():
    doc, xref = _stream_doc(_chain(PLAIN, 1), "[/FlateDecode/LZWDecode]")
    with doc:
        assert pdf_content_ops._bounded_stream(doc, xref, ROOM) is None
    doc, xref = _stream_doc(_chain(PLAIN, 1), "[/FlateDecode (x)]")
    with doc:
        assert pdf_content_ops._bounded_stream(doc, xref, ROOM) is None


def test_an_indirect_filter_object_is_parsed():
    doc, xref = _stream_doc(_chain(PLAIN, 2), "[/FlateDecode /FlateDecode]")
    with doc:
        holder = doc.get_new_xref()
        doc.update_object(holder, "[/FlateDecode/FlateDecode]")
        doc.xref_set_key(xref, "Filter", f"{holder} 0 R")
        assert pdf_content_ops._bounded_stream(doc, xref, ROOM) == PLAIN


@pytest.mark.parametrize("kind", ["predictor", "double_flate"])
def test_bombs_stay_bounded_and_are_not_decoded(monkeypatch, kind):
    doc, bomb = _chain_bomb_page(kind)
    with doc:
        calls = _spy_decodes(monkeypatch)
        assert pdf_content_ops._bounded_stream(doc, bomb, 4_000_000) is None
        assert bomb not in calls


def test_the_compact_spelling_of_a_double_flate_bomb_is_bounded(monkeypatch):
    zeros = b"\x00" * BOMB
    doc, bomb = _stream_doc(_chain(zeros, 2), "[/FlateDecode/FlateDecode]")
    with doc:
        calls = _spy_decodes(monkeypatch)
        assert pdf_content_ops._bounded_stream(doc, bomb, 4_000_000) is None
        assert bomb not in calls


def test_a_corrupt_flate_stream_is_over_the_cap_never_an_uncapped_decode(monkeypatch):
    # inflates fully inside the room, then fails the checksum: zlib raises within the cap
    good = zlib.compress(b"\x00" * 3_000_000, 9)
    corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
    with pytest.raises(zlib.error):
        zlib.decompressobj().decompress(corrupt, 4_000_001)
    doc, xref = _stream_doc(corrupt, "/FlateDecode")
    with doc:
        calls = _spy_decodes(monkeypatch)
        assert pdf_content_ops._bounded_stream(doc, xref, 4_000_000) is None
        assert xref not in calls


def test_a_truncated_flate_stream_never_decodes_past_the_room(monkeypatch):
    good = zlib.compress(b"\x00" * 64_000_000, 9)
    doc, xref = _stream_doc(good[: len(good) // 2], "/FlateDecode")
    with doc:
        calls = _spy_decodes(monkeypatch)
        assert pdf_content_ops._bounded_stream(doc, xref, 4_000_000) is None
        assert xref not in calls
