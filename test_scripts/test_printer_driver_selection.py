"""Printer driver selection never queries the OS version (perf pass 2026-11-04).

``get_printer_driver`` runs inside ``PDFController.activate()`` (the print
bridge), i.e. on the first open from the empty shell.  It picked the driver
with ``platform.system()``, which on Python 3.12+ Windows is a WMI query
(~70 ms): about a fifth of the time from "open" to the first painted page.
"""
from __future__ import annotations

import platform
import sys

import pytest

import src.printing.dispatcher as dispatcher


@pytest.fixture
def no_os_queries(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("printer driver selection queried the OS version")

    for name in ("system", "uname", "win32_ver", "release", "version"):
        monkeypatch.setattr(platform, name, forbidden)
    for name in ("WindowsPrinterDriver", "MacPrinterDriver", "LinuxPrinterDriver"):
        monkeypatch.setattr(dispatcher, name, type(name, (), {}))


@pytest.mark.parametrize(
    ("sys_platform", "driver_name"),
    (
        ("win32", "WindowsPrinterDriver"),
        ("darwin", "MacPrinterDriver"),
        ("linux", "LinuxPrinterDriver"),
        ("cygwin", "LinuxPrinterDriver"),
    ),
)
def test_driver_follows_sys_platform_without_an_os_query(no_os_queries, monkeypatch, sys_platform, driver_name):
    monkeypatch.setattr(sys, "platform", sys_platform)

    driver = dispatcher.get_printer_driver()

    assert type(driver).__name__ == driver_name
