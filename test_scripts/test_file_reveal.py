from __future__ import annotations

import ntpath
import subprocess
from types import SimpleNamespace

import pytest

from utils import file_reveal


def test_windows_reveal_uses_argument_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(file_reveal.sys, "platform", "win32")
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: True)
    monkeypatch.setenv("SystemRoot", r"D:\WinRoot")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(),
    )
    path = r"C:\文件 資料\report & final.pdf"

    assert file_reveal.reveal_in_file_manager(path) is True
    assert calls == [([r"D:\WinRoot\explorer.exe", "/select,", path], {})]


@pytest.mark.parametrize(
    ("system_root", "expected"),
    [
        (r"D:\WinRoot", r"D:\WinRoot\explorer.exe"),
        (r"D:\WinRoot" + "\\", r"D:\WinRoot\explorer.exe"),
        (None, r"C:\Windows\explorer.exe"),
        ("", r"C:\Windows\explorer.exe"),
        ("Windows", r"C:\Windows\explorer.exe"),
        (r"\Windows", r"C:\Windows\explorer.exe"),
        ("C:Windows", r"C:\Windows\explorer.exe"),
    ],
)
def test_windows_reveal_launches_explorer_by_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    system_root: str | None,
    expected: str,
) -> None:
    # CWE-427: a bare "explorer.exe" lets CreateProcess pick up a planted
    # explorer.exe from the current directory; the launched program must be an
    # absolute, drive-qualified path whatever SystemRoot holds.
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(file_reveal.sys, "platform", "win32")
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: True)
    if system_root is None:
        monkeypatch.delenv("SystemRoot", raising=False)
    else:
        monkeypatch.setenv("SystemRoot", system_root)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(),
    )
    path = r"C:\docs\report.pdf"

    assert file_reveal.reveal_in_file_manager(path) is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    launched = kwargs.get("executable") or args[0]
    assert ntpath.splitdrive(launched)[0] and ntpath.isabs(launched)
    assert launched == expected
    assert args[1:] == ["/select,", path]


def test_windows_reveal_preserves_network_style_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(file_reveal.sys, "platform", "win32")
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **_kwargs: calls.append(args) or SimpleNamespace(),
    )
    path = r"\\server\shared folder\report.pdf"

    assert file_reveal.reveal_in_file_manager(path) is True
    assert calls[0][-1] == path


def test_reveal_missing_file_returns_false_without_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_reveal.os.path, "isfile", lambda _path: False)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("launcher must not run for missing file"),
    )

    assert file_reveal.reveal_in_file_manager(r"C:\missing\document.pdf") is False
