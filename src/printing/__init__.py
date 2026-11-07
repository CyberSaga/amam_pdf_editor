"""Cross-platform printing subsystem entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base_driver import PrinterDevice, PrintJobOptions, PrintJobResult
from .errors import (
    PrinterOfflineError,
    PrinterUnavailableError,
    PrintHelperStalledError,
    PrintHelperTerminatedError,
    PrintingError,
    PrintJobSubmissionError,
    RenderingError,
)

if TYPE_CHECKING:
    from .dispatcher import PrintDispatcher, get_printer_driver

__all__ = [
    "PrintDispatcher",
    "PrintHelperStalledError",
    "PrintHelperTerminatedError",
    "PrintJobOptions",
    "PrintJobResult",
    "PrintJobSubmissionError",
    "PrinterDevice",
    "PrinterOfflineError",
    "PrinterUnavailableError",
    "PrintingError",
    "RenderingError",
    "get_printer_driver",
]


def __getattr__(name: str):
    if name in {'PrintDispatcher', 'get_printer_driver'}:
        from . import dispatcher

        value = getattr(dispatcher, name)
        globals()[name] = value
        return value
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

