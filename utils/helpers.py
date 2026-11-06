from __future__ import annotations

import fitz  # PyMuPDF


def parse_pages(input_str: str, total_pages: int) -> list[int]:
    """Parse a page range string like '1,3-5' -> [1,3,4,5]."""
    pages: set[int] = set()
    for raw_part in input_str.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            if start > end:
                start, end = end, start
            pages.update(range(max(1, start), min(total_pages, end) + 1))
        else:
            page = int(part)
            if 1 <= page <= total_pages:
                pages.add(page)
    return sorted(pages)


def pixmap_to_qimage(pix: fitz.Pixmap):
    """Convert a PyMuPDF pixmap to a detached QImage, bridging GRAY/CMYK safely."""
    if not pix.alpha and pix.colorspace is not None and pix.colorspace.n in {1, 4}:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    return qimage_from_samples(pix.samples, pix.width, pix.height, pix.stride, bool(pix.alpha))


def qimage_from_samples(samples: bytes | bytearray, width: int, height: int,
                       stride: int, alpha: bool):
    """Own the RGB/RGBA samples before their transport buffer is released."""
    from PySide6.QtGui import QImage

    fmt = QImage.Format.Format_RGBA8888 if alpha else QImage.Format.Format_RGB888
    return QImage(samples, width, height, stride, fmt).copy()


def pixmap_to_qpixmap(pix: fitz.Pixmap):
    """Convert a PyMuPDF pixmap into QPixmap (safe for GRAY/CMYK)."""
    from PySide6.QtGui import QPixmap

    return QPixmap.fromImage(pixmap_to_qimage(pix))

