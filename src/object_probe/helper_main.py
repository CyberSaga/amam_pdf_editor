"""One-shot ``object-probe`` child (H16, protocol v2): slow page analysis off the GUI process.

Protocol: one UTF-8 JSON header line ``{"v": 2, "kind": K, "sizes": [n1, ...], "mem": C}``, then the
payloads concatenated, then stdin closes.  ``C`` is the memory cap in bytes (H24): the child applies
it as a Job Object limit after the header and before it reads the payloads or imports PyMuPDF.  The
answer is one JSON line on stdout and exit code 0: ``{"v": 2, "status": S, ...}`` with ``S`` one of
``complete`` (carries ``rects``; an empty list is a real "no tables"), ``resource_limited``,
``analysis_failed`` or ``containment_failed``.  Any other exit code, or no answer, is a failure
(a native crash).  The child never imports Qt.  Kind ``tables``: one one-page PDF in.  Kind ``scan``:
decoded content streams in, ``scans`` out (one ``model.content_scan.to_json`` per stream; no PyMuPDF).
"""
from __future__ import annotations

import json
import logging
import sys

from src.object_probe.memory_limit import ContainmentError, apply_job_memory_limit

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 2
_MAX_HEADER_BYTES = 65536


def _read_header(stream) -> tuple[str, list[int], int]:
    line = stream.readline(_MAX_HEADER_BYTES)
    if not line.endswith(b"\n"):
        raise ValueError("object-probe header has no terminating newline")
    header = json.loads(line.decode("utf-8"))
    if not isinstance(header, dict) or header.get("v") != PROTOCOL_VERSION:
        raise ValueError("unsupported object-probe header")
    kind = header.get("kind")
    sizes = header.get("sizes")
    mem = header.get("mem")
    if not isinstance(kind, str) or not isinstance(sizes, list):
        raise ValueError("malformed object-probe header")
    if type(mem) is not int or mem <= 0:
        raise ValueError("malformed memory limit")
    for size in sizes:
        if type(size) is not int or size < 0:
            raise ValueError("malformed payload size")
    return kind, list(sizes), mem


def _read_payloads(stream, sizes: list[int]) -> list[bytes]:
    payloads: list[bytes] = []
    for size in sizes:
        data = stream.read(size)
        if len(data) != size:
            raise ValueError("short payload")
        payloads.append(data)
    return payloads


def _answer_tables(payloads: list[bytes]) -> dict:
    import fitz

    from model import table_objects

    if len(payloads) != 1:
        raise ValueError("tables takes exactly one payload")
    with fitz.open(stream=payloads[0], filetype="pdf") as doc:
        rects = table_objects.find_table_rects(doc[0])
    return {"v": PROTOCOL_VERSION, "status": "complete", "rects": [[float(v) for v in rect] for rect in rects]}


def _answer_scan(payloads: list[bytes]) -> dict:
    # Standard library only: neither PyMuPDF nor Qt is imported for this kind (card A5, H16).
    from model import content_scan

    return {
        "v": PROTOCOL_VERSION,
        "status": "complete",
        "scans": [content_scan.to_json(content_scan.scan_stream(p)) for p in payloads],
    }


_KINDS = {"tables": _answer_tables, "scan": _answer_scan}


def _write(out, answer: dict) -> None:
    out.write(json.dumps(answer).encode("utf-8") + b"\n")
    out.flush()


def main() -> int:
    # PyMuPDF prints advisory text on stdout; the answer line must be the only JSON line there, so
    # Python-level prints go to stderr and the parent still scans for the answer line.
    out = sys.stdout.buffer
    sys.stdout = sys.stderr
    kind, sizes, mem = _read_header(sys.stdin.buffer)
    handler = _KINDS.get(kind)
    if handler is None:
        raise ValueError(f"unknown object-probe kind: {kind!r}")
    try:
        apply_job_memory_limit(mem)
    except ContainmentError as exc:
        logger.error("object-probe containment failed: %s", exc)
        _write(out, {"v": PROTOCOL_VERSION, "status": "containment_failed"})
        return 0
    try:
        # The payload read is inside the guarded block: a MemoryError while reading still
        # gets a typed answer. A native crash that cannot even write JSON stays the runner's
        # to classify (D2/N3).
        payloads = _read_payloads(sys.stdin.buffer, sizes)
        answer = handler(payloads)
    except MemoryError:
        answer = {"v": PROTOCOL_VERSION, "status": "resource_limited"}
    except Exception:  # TableDetectionFailed and every other library failure
        logger.exception("object-probe analysis failed")
        answer = {"v": PROTOCOL_VERSION, "status": "analysis_failed"}
    _write(out, answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
