#!/usr/bin/env python3
"""External supervisor for /verify drivers (the in-process app-driving scripts).

A driver that opens a native modal dialog without a pre-armed handler hangs
inside the dialog's event loop, and nothing in that process can end it
(PITFALLS "In-process watchdog exit deadlocks"; 2026-10 a QFileDialog held a
verify run for 85 min).  So the watchdog is outside: the driver runs as a child
under `scripts.run_suite.supervise`, progress is growth of the driver's own log
(stdout+stderr, unbuffered), and a stall or the ceiling kills the whole process
tree the way run_suite kills a hung test file.

    .venv\\Scripts\\python.exe scripts/verify_supervise.py --stall 120 --ceiling 900 -- driver.py [args]

Exit code: the driver's own, or 124 when the supervisor killed it.  The log
tail is printed either way; the full log path is the last line.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_suite import supervise  # noqa: E402

KILLED_EXIT = 124
TAIL_LINES = 30


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stall", type=float, default=120.0, help="seconds without log growth before the kill")
    parser.add_argument("--ceiling", type=float, default=900.0, help="seconds of total run time before the kill")
    parser.add_argument("--poll", type=float, default=1.0, help="seconds between progress checks")
    parser.add_argument("--log", type=Path, default=None, help="driver log (default: %%TEMP%%/pdf_editor_verify_<ts>.log)")
    parser.add_argument("driver", nargs=argparse.REMAINDER, help="-- driver.py [driver args]")
    ns = parser.parse_args(argv)
    if ns.driver and ns.driver[0] == "--":
        ns.driver = ns.driver[1:]
    return ns


def _tail(path: Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-n:])


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    if not ns.driver:
        print("verify_supervise: give the driver after `--`, e.g. `-- scripts/my_verify.py --case 3`", file=sys.stderr)
        return 2
    log = ns.log or Path(tempfile.gettempdir()) / f"pdf_editor_verify_{int(time.time())}.log"
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    cmd = [sys.executable, *ns.driver]
    result = supervise(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        heartbeat=log,
        log=log,
        stall_seconds=ns.stall,
        file_ceiling=ns.ceiling,
        poll_seconds=ns.poll,
    )
    if result.killed:
        print(f"verify_supervise: KILLED after {result.elapsed:.1f}s ({result.reason or 'stall'}) -- the driver tree is gone")
    else:
        print(f"verify_supervise: driver exit {result.returncode} after {result.elapsed:.1f}s")
    print("--- log tail ---")
    print(_tail(log, TAIL_LINES))
    print(f"log: {log}")
    if result.killed:
        return KILLED_EXIT
    return result.returncode if result.returncode is not None else 1


if __name__ == "__main__":
    sys.exit(main())
