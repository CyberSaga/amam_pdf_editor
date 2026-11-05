"""Print diagnostics log (docs/to_Update.md line 4).

The owner reports that the first print after a cold boot follows the printer's
own preferences whatever is chosen in the dialog; the path could not be
reproduced here.  Each print now appends JSON lines (dialog choice, QPrinter
state before and after ``begin``, system uptime) to a local log the owner can
send back.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from src.printing.base_driver import PrintJobOptions


def _pdf_bytes() -> bytes:
    with fitz.open() as doc:
        doc.new_page(width=200, height=300).insert_text((20, 40), "diag")
        return doc.tobytes()


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "logs" / "print_diagnostics.log"
    monkeypatch.setenv("PDF_EDITOR_PRINT_LOG", str(path))
    return path


def test_record_appends_one_json_line_per_call(log_path: Path) -> None:
    from src.printing.print_diagnostics import record_print_diagnostics

    record_print_diagnostics("dialog", {"override_fields": ["duplex"], "duplex": "long"})
    record_print_diagnostics("qprinter", {"duplex": 1})

    lines = _lines(log_path)
    assert [line["stage"] for line in lines] == ["dialog", "qprinter"]
    assert lines[0]["override_fields"] == ["duplex"]
    assert "ts" in lines[0] and "pid" in lines[0]


def test_record_never_raises_when_the_log_cannot_be_written(tmp_path: Path, monkeypatch) -> None:
    from src.printing.print_diagnostics import record_print_diagnostics

    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PDF_EDITOR_PRINT_LOG", str(blocker / "sub" / "log.txt"))
    record_print_diagnostics("dialog", {"a": 1})  # parent is a file: must not raise


def test_log_is_size_capped(log_path: Path, monkeypatch) -> None:
    from src.printing import print_diagnostics

    monkeypatch.setattr(print_diagnostics, "MAX_LOG_BYTES", 400)
    for i in range(40):
        print_diagnostics.record_print_diagnostics("dialog", {"i": i, "pad": "x" * 40})
    assert log_path.stat().st_size <= 400 + 200
    assert _lines(log_path)[-1]["i"] == 39


def test_raster_print_records_the_options_and_the_qprinter_state(log_path: Path, tmp_path: Path, qapp) -> None:
    from src.printing.qt_bridge import raster_print_pdf

    out = tmp_path / "out.pdf"
    options = PrintJobOptions(
        output_pdf_path=str(out),
        dpi=72,
        copies=2,
        color_mode="grayscale",
        duplex="long",
        override_fields={"color_mode", "duplex"},
    )
    assert raster_print_pdf(_pdf_bytes(), [0], options).success

    stages = {line["stage"]: line for line in _lines(log_path)}
    assert {"qprinter_applied", "qprinter_begun"} <= set(stages)
    applied = stages["qprinter_applied"]
    assert applied["options"]["override_fields"] == ["color_mode", "duplex"]
    assert applied["options"]["color_mode"] == "grayscale"
    assert applied["printer"]["copy_count"] == 2
    assert "color_mode" in applied["printer"] and "duplex" in applied["printer"]
    assert "system_uptime_s" in applied
