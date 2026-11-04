"""Tests for scripts/verify_supervise.py: the external supervisor for /verify drivers.

A driver that opens a native modal dialog without a pre-armed handler hangs in
the dialog's event loop; nothing inside that process can end it (PITFALLS
"In-process watchdog exit deadlocks").  The supervisor runs the driver as a
child under run_suite's tree kill: progress is growth of the driver's own log,
a stall or the ceiling kills the whole tree and the exit code says so.
Covers: a healthy driver's exit code passes through, a stalled driver is killed
within the stall window with exit 124 and the tail of its log reported, and
the argument parsing keeps the driver's own flags intact.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import verify_supervise as vs  # noqa: E402


def _driver(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "driver.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_arguments_split_at_the_double_dash() -> None:
    ns = vs.parse_args(["--stall", "7", "--ceiling", "90", "--", "drv.py", "--flag", "x"])
    assert ns.stall == 7 and ns.ceiling == 90
    assert ns.driver == ["drv.py", "--flag", "x"]


def test_healthy_driver_exit_code_passes_through(tmp_path: Path) -> None:
    ok = _driver(tmp_path, "print('hello')\n")
    assert vs.main(["--stall", "20", "--ceiling", "60", "--log", str(tmp_path / "ok.log"), "--", str(ok)]) == 0
    bad = _driver(tmp_path, "import sys\nprint('x')\nsys.exit(3)\n")
    assert vs.main(["--stall", "20", "--ceiling", "60", "--log", str(tmp_path / "bad.log"), "--", str(bad)]) == 3


def test_stalled_driver_is_killed_and_reported(tmp_path: Path, capsys) -> None:
    stuck = _driver(tmp_path, "import time\nprint('opening dialog', flush=True)\ntime.sleep(300)\n")
    log = tmp_path / "stuck.log"
    t0 = time.monotonic()
    code = vs.main(["--stall", "2", "--ceiling", "120", "--poll", "0.5", "--log", str(log), "--", str(stuck)])
    elapsed = time.monotonic() - t0
    assert code == vs.KILLED_EXIT == 124
    assert elapsed < 60
    out = capsys.readouterr().out
    assert "opening dialog" in out and "stall" in out.lower()
    assert "opening dialog" in log.read_text(encoding="utf-8")
