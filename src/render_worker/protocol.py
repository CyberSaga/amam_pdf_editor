from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass

PREFIX = struct.Struct(">2sBIQ")
MAX_HEADER_BYTES = 64 * 1024
MAX_LOAD_BYTES = 512 * 1024 * 1024
MAX_IMAGE_BYTES = 160 * 1024 * 1024
_TYPES = {"ready", "load_path", "load_bytes", "drop_doc", "render", "quit",
          "doc_ready", "doc_failed", "image", "error"}


class ProtocolError(ValueError):
    """Deliberately contains no header, path, password or document content."""


@dataclass(frozen=True)
class Frame:
    header: dict
    body: bytearray


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def validate_header(header: object, body_len: int) -> None:
    if not isinstance(header, dict) or not isinstance(header.get("type"), str):
        raise ProtocolError("invalid frame header")
    kind = header["type"]
    if kind not in _TYPES:
        raise ProtocolError("unknown frame type")
    strings = {
        "load_path": ("doc_key", "path"), "load_bytes": ("doc_key",),
        "drop_doc": ("doc_key",), "render": ("job", "doc_key", "profile", "kind"),
        "doc_ready": ("doc_key",), "doc_failed": ("doc_key", "reason"),
        "image": ("job",), "error": ("job", "reason", "exc_type"),
        "ready": ("fitz_version",),
    }.get(kind, ())
    if any(not isinstance(header.get(key), str) for key in strings):
        raise ProtocolError("invalid frame fields")
    if 'watermarks_json' in header or 'overlay_schema' in header:
        if (kind != 'load_bytes' or type(header.get('overlay_schema')) is not int
                or header['overlay_schema'] != 1 or not isinstance(header.get('watermarks_json'), str)):
            raise ProtocolError('invalid overlay source')
        try:
            from model.watermark_raster import decode_watermark_recipe
            decode_watermark_recipe(header['watermarks_json'].encode('utf-8'))
        except (ValueError, UnicodeError):
            raise ProtocolError('invalid overlay recipe') from None
    if 'overlay_sha256' in header:
        digest = header['overlay_sha256']
        if (kind != 'doc_ready' or not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ProtocolError('invalid overlay identity')
    if kind == "image":
        w, h, stride, n = (header.get(k) for k in ("w", "h", "stride", "n"))
        alpha = header.get("alpha")
        if (not all(_integer(v, 1) for v in (w, h, stride, n))
                or type(alpha) is not bool or n != (4 if alpha else 3)
                or stride < w * n or body_len != stride * h
                or body_len > MAX_IMAGE_BYTES):
            raise ProtocolError("invalid image layout")
    elif kind == "load_path":
        if not all(_integer(header.get(k)) for k in ("size", "mtime_ns")):
            raise ProtocolError("invalid file identity")
    elif kind == "render":
        if 'trim_store' in header and not isinstance(header['trim_store'], bool):
            raise ProtocolError('invalid cache policy')
        if 'trim_store_interval' in header and (
                not _integer(header['trim_store_interval'], 1) or header['trim_store_interval'] > 16):
            raise ProtocolError('invalid cache trim interval')
        if 'retain_display_lists' in header and type(header['retain_display_lists']) is not bool:
            raise ProtocolError('invalid retention policy')
        if 'promotion_allowed' in header and type(header['promotion_allowed']) is not bool:
            raise ProtocolError('invalid promotion policy')
        if 'foreground_intent' in header:
            intent = header['foreground_intent']
            if not isinstance(intent, str) or not 1 <= len(intent) <= 128:
                raise ProtocolError('invalid foreground intent')
        scale = header.get("scale")
        try:
            valid_scale = type(scale) in (int, float) and math.isfinite(scale) and scale > 0
        except OverflowError:
            valid_scale = False
        if (not _integer(header.get("page")) or type(scale) not in (int, float)
                or not valid_scale
                or header["kind"] not in {"page", "thumb"}):
            raise ProtocolError("invalid render request")
    elif kind in {"ready", "doc_ready"}:
        if not _integer(header.get("pid" if kind == "ready" else "page_count")):
            raise ProtocolError("invalid response identity")
    if kind not in {"load_path", "load_bytes", "image"} and body_len:
        raise ProtocolError("unexpected frame body")


def encode_prefix(header: dict, body_len: int) -> bytes:
    if not _integer(body_len) or body_len > MAX_LOAD_BYTES:
        raise ProtocolError("frame body exceeds limit")
    validate_header(header, body_len)
    try:
        encoded = json.dumps(header, ensure_ascii=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise ProtocolError("invalid frame header") from None
    if len(encoded) > MAX_HEADER_BYTES:
        raise ProtocolError("frame header exceeds limit")
    return PREFIX.pack(b"RW", 1, len(encoded), body_len) + encoded


class FrameDecoder:
    """Incremental framing with one preallocated body per validated header.

    A protocol error is terminal: callers discard this decoder and transport.
    No large incoming chunk is retained in an additional accumulation buffer.
    """

    def __init__(self, max_header: int = MAX_HEADER_BYTES,
                 max_body: int = MAX_LOAD_BYTES) -> None:
        self.max_header = max_header
        self.max_body = max_body
        self._prefix = bytearray()
        self._json = bytearray()
        self._header_len = 0
        self._body_len = 0
        self._header: dict | None = None
        self._body: bytearray | None = None
        self._written = 0

    @property
    def incomplete(self) -> bool:
        return bool(self._prefix or self._json or self._header is not None)

    def feed(self, chunk: bytes) -> list[Frame]:
        frames = []
        data = memoryview(chunk)
        while data:
            if len(self._prefix) < PREFIX.size:
                count = min(len(data), PREFIX.size - len(self._prefix))
                self._prefix.extend(data[:count])
                data = data[count:]
                if len(self._prefix) < PREFIX.size:
                    continue
                magic, version, self._header_len, self._body_len = PREFIX.unpack(self._prefix)
                if (magic != b"RW" or version != 1
                        or not 0 < self._header_len <= self.max_header
                        or self._body_len > self.max_body):
                    raise ProtocolError("invalid frame prefix or size")
            if self._header is None:
                count = min(len(data), self._header_len - len(self._json))
                self._json.extend(data[:count])
                data = data[count:]
                if len(self._json) < self._header_len:
                    continue
                try:
                    header = json.loads(self._json)
                except (ValueError, UnicodeError, RecursionError):
                    raise ProtocolError("invalid frame JSON") from None
                validate_header(header, self._body_len)
                self._header = header
                self._body = bytearray(self._body_len)
            count = min(len(data), self._body_len - self._written)
            self._body[self._written:self._written + count] = data[:count]
            self._written += count
            data = data[count:]
            if self._written == self._body_len:
                frames.append(Frame(self._header, self._body))
                self._prefix = bytearray()
                self._json = bytearray()
                self._header = None
                self._body = None
                self._written = 0
        return frames
