from __future__ import annotations

import math
import os
import sys
from typing import BinaryIO

import fitz

from model.page_raster import rasterize_page, rasterize_thumbnail
from src.render_worker.protocol import (
    MAX_IMAGE_BYTES, MAX_LOAD_BYTES, Frame, FrameDecoder, ProtocolError, encode_prefix,
)
from utils.render_limits import safe_render_scale, thumbnail_render_scale


class Worker:
    """One document slot, single-threaded dispatch, no GUI imports."""

    def __init__(self, output: BinaryIO) -> None:
        self.output = output
        self.doc: fitz.Document | None = None
        self.key: str | None = None

    def send(self, header: dict, body: bytes = b"") -> None:
        self.output.write(encode_prefix(header, len(body)))
        self.output.write(body)
        self.output.flush()

    def drop(self) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.key = None
        fitz.TOOLS.store_shrink(100)

    def load(self, frame: Frame) -> None:
        header = frame.header
        key = header["doc_key"]
        self.drop()
        candidate = None
        reason = "open"
        try:
            if header["type"] == "load_path":
                # Both fstat and the second path stat detect replacement during
                # the read. Always close the Windows file handle before ack.
                with open(header["path"], "rb") as source:
                    before = os.fstat(source.fileno())
                    if (before.st_size, before.st_mtime_ns) != (header["size"], header["mtime_ns"]):
                        reason = "changed"
                        return
                    if before.st_size > MAX_LOAD_BYTES:
                        reason = "too_large"
                        return
                    # read(n) may reserve/touch n bytes on Windows even for a
                    # tiny file. Bound by the checked file size, with one extra
                    # byte to detect growth, rather than the 512 MiB ceiling.
                    data = source.read(before.st_size + 1)
                    after = os.fstat(source.fileno())
                current = os.stat(header["path"])
                if (len(data) != before.st_size
                        or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns)
                        or (current.st_size, current.st_mtime_ns) != (before.st_size, before.st_mtime_ns)):
                    reason = "changed"
                    return
                password = frame.body.decode("utf-8")
            else:
                data = bytes(frame.body)
                password = ""
            candidate = fitz.open(stream=data, filetype="pdf")
            if candidate.needs_pass and not candidate.authenticate(password):
                reason = "auth"
                return
            self.doc = candidate
            candidate = None
            self.key = key
        except Exception:
            # Native diagnostics go to stderr; never stringify paths/passwords.
            pass
        finally:
            if candidate is not None:
                candidate.close()
            if self.doc is None:
                self.send({"type": "doc_failed", "doc_key": key, "reason": reason})
        if self.doc is not None:
            self.send({"type": "doc_ready", "doc_key": key, "page_count": len(self.doc)})

    def render(self, header: dict) -> None:
        job = header["job"]
        if self.doc is None or self.key != header["doc_key"]:
            self.send({"type": "error", "job": job, "reason": "stale", "exc_type": ""})
            return
        try:
            page = self.doc[header["page"]]
            scale = (thumbnail_render_scale(page) if header["kind"] == "thumb"
                     else safe_render_scale(page, header["scale"]))
            # Account for raster rounding at both ends of the transformed bbox.
            rect = page.rect * fitz.Matrix(scale, scale)
            width = math.ceil(rect.x1) - math.floor(rect.x0)
            height = math.ceil(rect.y1) - math.floor(rect.y0)
            if width * height * 3 > MAX_IMAGE_BYTES:
                self.send({"type": "error", "job": job, "reason": "oversize", "exc_type": ""})
                return
            raster = (rasterize_thumbnail(self.doc, header["page"], header["profile"])
                      if header["kind"] == "thumb" else
                      rasterize_page(self.doc, header["page"], header["scale"], header["profile"]))
            self.send({"type": "image", "job": job, "w": raster.width, "h": raster.height,
                       "stride": raster.stride, "n": raster.n, "alpha": raster.alpha}, raster.samples)
        except Exception as exc:
            self.send({"type": "error", "job": job, "reason": "render", "exc_type": type(exc).__name__})

    def dispatch(self, frame: Frame) -> bool:
        kind = frame.header["type"]
        if kind == "quit":
            return False
        if kind in {"load_path", "load_bytes"}:
            self.load(frame)
        elif kind == "drop_doc":
            if self.key == frame.header["doc_key"]:
                self.drop()
        elif kind == "render":
            self.render(frame.header)
        else:
            raise ProtocolError("unexpected worker command")
        return True


def main() -> int:
    # Preserve only this dedicated binary handle. C-level MuPDF output as well
    # as Python print() must never corrupt the framed stdout channel.
    output = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    fitz.TOOLS.set_small_glyph_heights(True)
    worker = Worker(output)
    decoder = FrameDecoder(max_body=MAX_LOAD_BYTES)
    try:
        worker.send({"type": "ready", "pid": os.getpid(), "fitz_version": fitz.VersionBind})
        while True:
            chunk = sys.stdin.buffer.read1(64 * 1024)
            if not chunk:
                if decoder.incomplete:
                    raise ProtocolError("truncated worker command")
                return 0
            for frame in decoder.feed(chunk):
                if not worker.dispatch(frame):
                    return 0
    except (ProtocolError, BrokenPipeError):
        print("render worker transport closed", file=sys.stderr)
        return 2
    finally:
        worker.drop()
        output.close()


if __name__ == "__main__":
    raise SystemExit(main())
