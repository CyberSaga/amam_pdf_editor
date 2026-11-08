"""The optimize copy never lets Pillow hand PDF image bytes to Ghostscript.

`_transcode_image_payload` sniffs the format of raw image-stream bytes taken
from the PDF.  A stream labelled `/DCTDecode` whose bytes are PostScript would
reach Pillow's EPS plugin, whose `load()` runs Ghostscript on it -- directly,
or nested inside an IPTC wrapper whose `load()` reopens its payload unrestricted.
Ghostscript is never really launched here: `subprocess.check_call` and
`subprocess.Popen` are trapped and `EpsImagePlugin.gs_binary` is faked, so on
the unfixed code the trap records the command and nothing external runs.

Every other payload keeps the outcome it had before the fix: JPEG, PNG and
JPEG 2000 are re-encoded, and so are foreign formats (GIF, BMP, raw IPTC)
stored under `/DCTDecode`.
"""

from __future__ import annotations

import io
import struct
import subprocess
import sys
from pathlib import Path

import fitz
import pytest
from PIL import EpsImagePlugin, Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model import pdf_optimizer  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_optimizer import PdfOptimizeOptions, image_rewrite_settings  # noqa: E402

_EPS = (
    b"%!PS-Adobe-3.0 EPSF-3.0\n"
    b"%%BoundingBox: 0 0 8 8\n"
    b"%%EndComments\n"
    b"{} loop\n"
)


def _dos_eps(postscript: bytes) -> bytes:
    # DOS EPS binary header: magic, PS offset/length, no WMF/TIFF preview, no checksum.
    header = b"\xc5\xd0\xd3\xc6" + struct.pack("<IIIIII", 30, len(postscript), 0, 0, 0, 0) + b"\xff\xff"
    return header + postscript


def _iptc_field(record: int, dataset: int, data: bytes) -> bytes:
    return bytes([0x1C, record, dataset]) + struct.pack(">H", len(data)) + data


def _iptc(compression: int, payload: bytes) -> bytes:
    """IPTC/NAA image, 8x8 single-band; compression 1 = raw samples, 5 = embedded file."""
    return (
        _iptc_field(3, 60, bytes([1, 0]))
        + _iptc_field(3, 20, struct.pack(">H", 8))
        + _iptc_field(3, 30, struct.pack(">H", 8))
        + _iptc_field(3, 120, bytes([compression]))
        + _iptc_field(8, 10, payload)
    )


def _encoded(fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    color: int | tuple[int, ...] = 1 if mode == "1" else (200, 30, 30)
    Image.new(mode, (8, 8), color).save(buf, format=fmt)
    return buf.getvalue()


_POSTSCRIPT_PAYLOADS = {
    "eps": _EPS,
    "dos-eps": _dos_eps(_EPS),
    "iptc-wrapped-eps": _iptc(5, _EPS),
}


@pytest.fixture
def gs_trap(monkeypatch) -> list[object]:
    """Make the unfixed code believe Ghostscript exists, and record any spawn instead of running it."""
    calls: list[object] = []

    def trap(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("args"))
        raise RuntimeError("trapped external process spawn")

    monkeypatch.setattr(subprocess, "check_call", trap)
    monkeypatch.setattr(subprocess, "Popen", trap)
    monkeypatch.setattr(EpsImagePlugin, "gs_binary", "gs")
    return calls


def _settings() -> dict[str, int | bool]:
    return image_rewrite_settings(PdfOptimizeOptions())


def _pdf_with_dct_stream(path: Path, payload: bytes) -> tuple[Path, int]:
    """One page drawing one image XObject whose `/DCTDecode` stream holds `payload` verbatim."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        xref = page.insert_image(fitz.Rect(10, 10, 90, 90), stream=_encoded("JPEG"))
        doc.update_stream(xref, payload, new=False, compress=False)
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
        doc.save(path)
    finally:
        doc.close()
    return path, xref


def _run_serial(path: Path) -> tuple[bytes, int]:
    """Run the serial rewrite over the document; return the image's stream bytes afterwards."""
    doc = fitz.open(path)
    model = PDFModel()
    try:
        usage = pdf_optimizer.collect_image_usage(doc)
        assert len(usage) == 1
        (xref,) = usage
        pdf_optimizer.rewrite_images_serially(model, doc, usage, PdfOptimizeOptions())
        return doc.extract_image(xref)["image"], xref
    finally:
        model.close()
        doc.close()


# --- PostScript never reaches Ghostscript ----------------------------------------------------


@pytest.mark.parametrize("payload", list(_POSTSCRIPT_PAYLOADS.values()), ids=list(_POSTSCRIPT_PAYLOADS))
def test_transcode_helper_never_spawns_ghostscript(gs_trap, payload: bytes) -> None:
    with pytest.raises(OSError, match="Ghostscript"):
        pdf_optimizer._transcode_image_payload(payload, 72.0, _settings())
    assert gs_trap == [], f"Ghostscript would have been spawned: {gs_trap}"


@pytest.mark.parametrize("payload", list(_POSTSCRIPT_PAYLOADS.values()), ids=list(_POSTSCRIPT_PAYLOADS))
def test_extracted_image_pool_task_skips_postscript(gs_trap, payload: bytes) -> None:
    xref, page_index, rewritten, error = pdf_optimizer._rewrite_extracted_image_task(
        (7, 0, 72.0, payload, _settings())
    )
    assert gs_trap == [], f"Ghostscript would have been spawned: {gs_trap}"
    assert (xref, page_index, rewritten) == (7, 0, None)
    assert error and "Ghostscript" in error


@pytest.mark.parametrize("payload", list(_POSTSCRIPT_PAYLOADS.values()), ids=list(_POSTSCRIPT_PAYLOADS))
def test_source_image_pool_task_skips_postscript(gs_trap, monkeypatch, tmp_path: Path, payload: bytes) -> None:
    path, xref = _pdf_with_dct_stream(tmp_path / "ps.pdf", payload)
    monkeypatch.setattr(pdf_optimizer, "_IMAGE_REWRITE_WORKER_DOC", None)
    pdf_optimizer._init_image_rewrite_worker(str(path))
    worker_doc = pdf_optimizer._IMAGE_REWRITE_WORKER_DOC
    assert worker_doc is not None
    try:
        assert worker_doc.extract_image(xref)["image"] == payload
        result_xref, rewritten, error = pdf_optimizer._rewrite_source_image_task((xref, 72.0, _settings()))
    finally:
        worker_doc.close()
    assert gs_trap == [], f"Ghostscript would have been spawned: {gs_trap}"
    assert (result_xref, rewritten) == (xref, None)
    assert error and "Ghostscript" in error


@pytest.mark.parametrize("payload", list(_POSTSCRIPT_PAYLOADS.values()), ids=list(_POSTSCRIPT_PAYLOADS))
def test_serial_rewrite_skips_postscript_and_leaves_stream_untouched(gs_trap, tmp_path: Path, payload: bytes) -> None:
    path, _xref = _pdf_with_dct_stream(tmp_path / "ps.pdf", payload)
    stream_after, _ = _run_serial(path)
    assert gs_trap == [], f"Ghostscript would have been spawned: {gs_trap}"
    assert stream_after == payload


# --- every non-PostScript payload keeps its pre-fix outcome ---------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_prefix"),
    [
        (_encoded("JPEG"), b"\xff\xd8"),
        (_encoded("PNG"), b"\xff\xd8"),
        (_encoded("PNG", mode="RGBA"), b"\x89PNG"),
        (_encoded("PNG", mode="1"), b"\x89PNG"),
        (_encoded("JPEG2000"), b"\xff\xd8"),
        (_encoded("GIF"), b"\xff\xd8"),
        (_encoded("BMP"), b"\xff\xd8"),
        (_iptc(1, bytes(64)), b"\xff\xd8"),
    ],
    ids=["jpeg", "png", "png-rgba", "png-bitonal", "jpeg2000", "gif", "bmp", "iptc-raw"],
)
def test_transcode_helper_reencodes_non_postscript_payloads(gs_trap, payload: bytes, expected_prefix: bytes) -> None:
    rewritten = pdf_optimizer._transcode_image_payload(payload, 72.0, _settings())
    assert rewritten is not None
    assert rewritten.startswith(expected_prefix)
    assert gs_trap == []


@pytest.mark.parametrize(
    ("payload", "magic"),
    [(_encoded("GIF"), b"GIF8"), (_encoded("BMP"), b"BM"), (_encoded("JPEG"), b"\xff\xd8")],
    ids=["gif", "bmp", "jpeg"],
)
def test_serial_rewrite_still_reencodes_foreign_bytes_under_dctdecode(
    gs_trap, tmp_path: Path, payload: bytes, magic: bytes
) -> None:
    path, xref = _pdf_with_dct_stream(tmp_path / "foreign.pdf", payload)
    with fitz.open(path) as doc:
        assert doc.extract_image(xref)["image"].startswith(magic)
    stream_after, _ = _run_serial(path)
    assert stream_after != payload
    assert stream_after.startswith(b"\xff\xd8")
    assert gs_trap == []
