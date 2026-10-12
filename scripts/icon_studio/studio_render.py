"""Rasterize an SVG to PNG with the Chromium renderer (render.js)."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rasterize(svg: Path, out: Path, size: int, bg: str = "transparent") -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump([{"svg": str(svg), "out": str(out), "size": size, "bg": bg}], fh)
    subprocess.run(["node", str(HERE / "render.js"), fh.name], check=True, capture_output=True)
    Path(fh.name).unlink()
    return out
