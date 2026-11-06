from __future__ import annotations

import struct

import pytest

from src.render_worker.protocol import FrameDecoder, ProtocolError, encode_prefix


def test_split_and_coalesced_frames():
    header = {"type": "load_bytes", "doc_key": "doc"}
    wire = encode_prefix(header, 6) + b"abcdef"
    decoder = FrameDecoder(max_body=10)
    frames = []
    combined = wire + encode_prefix({"type": "quit"}, 0)
    for byte in combined:
        frames.extend(decoder.feed(bytes([byte])))
    assert [f.header["type"] for f in frames] == ["load_bytes", "quit"]
    assert frames[0].body == b"abcdef"
    assert isinstance(frames[0].body, bytearray)
    assert FrameDecoder(max_body=10).feed(wire)[0].body == frames[0].body
    assert FrameDecoder(max_body=10).feed(combined) == frames


def test_body_uses_one_preallocated_buffer():
    decoder = FrameDecoder()
    prefix = encode_prefix({"type": "load_bytes", "doc_key": "d"}, 4)
    assert decoder.feed(prefix + b"a") == []
    buffer = decoder._body
    assert len(buffer) == 4
    assert decoder.feed(b"b") == []
    assert decoder._body is buffer
    assert decoder.feed(b"cd")[0].body is buffer


@pytest.mark.parametrize("field", ["n", "alpha"])
def test_image_rejects_each_missing_layout_field(field):
    header = {"type": "image", "job": "j", "w": 1, "h": 1,
              "stride": 3, "n": 3, "alpha": False}
    header.pop(field)
    with pytest.raises(ProtocolError):
        encode_prefix(header, 3)


def test_huge_integer_scale_is_a_content_free_protocol_error():
    with pytest.raises(ProtocolError):
        encode_prefix({"type": "render", "job": "j", "doc_key": "d", "page": 0,
                       "scale": 10 ** 400, "profile": "srgb", "kind": "page"}, 0)


@pytest.mark.parametrize("prefix", [
    struct.pack(">2sBIQ", b"XX", 1, 1, 0),
    struct.pack(">2sBIQ", b"RW", 2, 1, 0),
    struct.pack(">2sBIQ", b"RW", 1, 65537, 0),
    struct.pack(">2sBIQ", b"RW", 1, 2, 11),
])
def test_bad_prefix_rejected_before_allocating_body(prefix):
    with pytest.raises(ProtocolError):
        FrameDecoder(max_body=10).feed(prefix)


def test_errors_do_not_echo_header_or_password():
    body = b'{"type":"s3cret"}'
    with pytest.raises(ProtocolError) as exc:
        FrameDecoder().feed(struct.pack(">2sBIQ", b"RW", 1, len(body), 0) + body)
    assert "s3cret" not in str(exc.value)


def test_image_requires_layout_and_matching_body():
    for header in ({"type": "image"}, {
        "type": "image", "job": "j", "w": 1, "h": 1,
        "stride": 3, "n": 3, "alpha": False,
    }):
        with pytest.raises(ProtocolError):
            encode_prefix(header, 0)
