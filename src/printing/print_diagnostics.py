"""Append-only print diagnostics (docs/to_Update.md line 4).

The owner reports that the first print after a cold boot follows the printer's
own preferences whatever the dialog says.  It does not reproduce here, so every
print records what the dialog resolved and what the QPrinter actually holds
(before and after ``begin()``, which is when the Windows driver applies its
DEVMODE), plus the system uptime, as JSON lines in a small local log:

* ``PDF_EDITOR_PRINT_LOG`` when set, else
* ``%LOCALAPPDATA%/pdf_editor/print_diagnostics.log`` on Windows,
  ``~/.cache/pdf_editor/print_diagnostics.log`` elsewhere.

Recording never raises and never blocks printing.  No document content and no
password is written; the printer name is.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The log is rotated to ``<name>.1`` once it grows past this size.
MAX_LOG_BYTES = 512 * 1024


def diagnostics_log_path() -> Path | None:
    override = os.environ.get("PDF_EDITOR_PRINT_LOG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        return Path(root) / "pdf_editor" / "print_diagnostics.log" if root else None
    return Path.home() / ".cache" / "pdf_editor" / "print_diagnostics.log"


def system_uptime_s() -> float | None:
    """Seconds since boot (Windows only; ``None`` elsewhere or on failure)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        tick = ctypes.windll.kernel32.GetTickCount64
        tick.restype = ctypes.c_ulonglong
        return round(tick() / 1000.0, 1)
    except Exception:  # pragma: no cover - Windows API missing
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return repr(value)


def _rotate_if_large(path: Path) -> None:
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass


def record_print_diagnostics(stage: str, payload: dict[str, Any]) -> None:
    """Append one JSON line ``{ts, pid, stage, system_uptime_s, **payload}``."""
    try:
        path = diagnostics_log_path()
        if path is None:
            return
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pid": os.getpid(),
            "stage": stage,
            "system_uptime_s": system_uptime_s(),
        }
        entry.update(_jsonable(payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_large(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # diagnostics must never break printing
        logger.debug("print diagnostics not written: %s", exc)


def options_summary(options: Any) -> dict[str, Any]:
    """The dialog/job choices that decide what the driver prints (no content)."""
    extra = getattr(options, "extra_options", None) or {}
    return {
        "printer_name": getattr(options, "printer_name", None),
        "copies": getattr(options, "copies", None),
        "collate": getattr(options, "collate", None),
        "dpi": getattr(options, "dpi", None),
        "color_mode": getattr(options, "color_mode", None),
        "duplex": getattr(options, "duplex", None),
        "paper_size": getattr(options, "paper_size", None),
        "orientation": getattr(options, "orientation", None),
        "paper_tray": getattr(options, "paper_tray", None),
        "scale_mode": getattr(options, "scale_mode", None),
        "override_fields": sorted(getattr(options, "override_fields", None) or ()),
        "has_devmode_buffer": bool(extra.get("devmode_buffer")),
        "to_pdf_file": bool(getattr(options, "output_pdf_path", None)),
    }


def qprinter_state(printer: Any) -> dict[str, Any]:
    """What the QPrinter holds; on Windows after ``begin()`` this is the DEVMODE in use."""
    state: dict[str, Any] = {}
    for key, getter in (
        ("printer_name", "printerName"),
        ("copy_count", "copyCount"),
        ("collate", "collateCopies"),
        ("resolution", "resolution"),
        ("color_mode", "colorMode"),
        ("duplex", "duplex"),
        ("paper_source", "paperSource"),
    ):
        try:
            value = getattr(printer, getter)()
            state[key] = value if isinstance(value, (str, int, bool)) else getattr(value, "name", repr(value))
        except Exception as exc:
            state[key] = f"<error {exc.__class__.__name__}>"
    try:
        layout = printer.pageLayout()
        state["page_size"] = layout.pageSize().name()
        state["orientation"] = getattr(layout.orientation(), "name", repr(layout.orientation()))
    except Exception as exc:
        state["page_size"] = f"<error {exc.__class__.__name__}>"
    return state
