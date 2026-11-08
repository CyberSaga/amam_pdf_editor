from __future__ import annotations

import logging
import ntpath
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_WINDOWS_DIR_FALLBACK = r"C:\Windows"


def _windows_explorer_path() -> str:
    """Absolute path of explorer.exe, so CreateProcess never resolves the bare
    name through the current directory (CWE-427 binary planting)."""
    root = os.environ.get("SystemRoot", "")
    if not (ntpath.splitdrive(root)[0] and ntpath.isabs(root)):
        root = _WINDOWS_DIR_FALLBACK
    return ntpath.join(root, "explorer.exe")


def reveal_in_file_manager(path: str) -> bool:
    """Reveal an existing file without constructing a shell command string."""
    candidate = str(path or "").strip()
    if not candidate or not os.path.isfile(candidate):
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen([_windows_explorer_path(), "/select,", candidate])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", candidate])
        else:
            subprocess.Popen(["xdg-open", str(Path(candidate).parent)])
    except OSError as exc:
        logger.warning("Unable to reveal file %s: %s", candidate, exc)
        return False
    return True
