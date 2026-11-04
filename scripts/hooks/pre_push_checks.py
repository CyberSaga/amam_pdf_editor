#!/usr/bin/env python3
"""Git pre-push hook: run CI's fast blocking gates locally before a push.

Installed into ``.git/hooks/pre-push`` by ``scripts/hooks/install_git_hooks.py``
(plans/CI-faster.md).  Runs, against the working tree being pushed:

* ``ruff check .``                     (CI job ``lint``)
* ``mypy model/ utils/``               (CI job ``typecheck``)
* the four import-linter contracts     (CI job ``layer-boundaries``)
* the ``threading.Thread`` grep over view/ + controller/ (same job)

Warm, the whole set takes about two seconds; a red gate here costs seconds instead
of a CI round trip whose functional leg alone runs ~40 minutes.  Every gate runs
even after one fails, so one push shows every problem.  Bypass deliberately with
``git push --no-verify``.

The gates check the working tree, not the pushed commits: uncommitted edits
count.  ``CONTRACTS`` must equal the ``--contract`` list on ci.yml's lint-imports
line (pinned by test_scripts/test_pre_push_checks.py).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

CONTRACTS: tuple[str, ...] = (
    "model-no-controller-view",
    "model-no-qt",
    "utils-no-controller-view-model",
    "view-no-model",
)
THREADING_DIRS: tuple[str, ...] = ("view", "controller")
THREADING_NEEDLE = "threading.Thread"

# import-linter ships only a console script; calling its click command through -c
# keeps every gate on the same interpreter (click reads the args after -c).
_LINT_IMPORTS = "from importlinter.cli import lint_imports_command; lint_imports_command()"

Runner = Callable[[list[str], Path], "subprocess.CompletedProcess"]


def gates(python: str) -> list[tuple[str, list[str]]]:
    """(name, argv) for every subprocess gate, in the order they run."""
    lint_imports = [python, "-c", _LINT_IMPORTS, "--config", "pyproject.toml"]
    for contract in CONTRACTS:
        lint_imports += ["--contract", contract]
    return [
        ("ruff", [python, "-m", "ruff", "check", "."]),
        ("mypy", [python, "-m", "mypy", "model/", "utils/"]),
        ("import-linter", lint_imports),
    ]


def find_threading_thread(root: Path) -> list[str]:
    """``rel/path.py:line: text`` for every threading.Thread in view/ or controller/."""
    hits: list[str] = []
    for top in THREADING_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if THREADING_NEEDLE in line:
                    hits.append(f"{path.relative_to(root).as_posix()}:{lineno}: {line.strip()}")
    return hits


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), check=False)


def main(
    argv: list[str] | None = None,
    root: Path | None = None,
    runner: Runner = _run,
    python: str = sys.executable,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # git passes <remote-name> <remote-url>; they do not change what is checked.
    parser.add_argument("remote", nargs="*", help=argparse.SUPPRESS)
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    # git runs hooks from the top of the working tree being pushed (also in a
    # linked worktree), so cwd is the tree to check.
    root = Path.cwd() if root is None else root

    failed: list[str] = []
    for name, cmd in gates(python):
        print(f"pre-push: {name} ...", flush=True)
        if runner(cmd, root).returncode != 0:
            failed.append(name)
    hits = find_threading_thread(root)
    if hits:
        print("pre-push: threading.Thread in view/ or controller/ -- use QThread + Signals:")
        for hit in hits:
            print(f"  {hit}")
        failed.append("threading-grep")

    if failed:
        print(f"pre-push: BLOCKED by {', '.join(failed)} (bypass deliberately: git push --no-verify)", flush=True)
        return 1
    print("pre-push: all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
