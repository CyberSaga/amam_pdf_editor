#!/usr/bin/env python3
"""Install repo-provided git hooks into .git/hooks/.

Git hooks live in .git/ and are never version-controlled, so a fresh clone
has none installed until this is run once:

    python scripts/hooks/install_git_hooks.py

Installs:
  pre-commit -> scripts/hooks/pre_commit_device_guard.py (CLAUDE.md device-identity guard)
  pre-push   -> scripts/hooks/pre_push_checks.py (CI's fast gates: ruff, mypy,
                import-linter contracts, threading grep; plans/CI-faster.md)

Each hook runs on the repo's .venv interpreter when one exists (the gates need
the pinned tool versions), else on `python` / `python3`. A hook that already
exists and was not written by this installer is left untouched with a warning;
the other hooks are still installed and the exit code is 1.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKER = "# installed-by: scripts/hooks/install_git_hooks.py\n"

HOOKS: dict[str, str] = {
    "pre-commit": "pre_commit_device_guard.py",
    "pre-push": "pre_push_checks.py",
}

# git runs hooks from the top of the working tree; a linked worktree without its
# own .venv falls back to the installing checkout's .venv, then to PATH.
HOOK_BODY = """#!/bin/sh
# installed-by: scripts/hooks/install_git_hooks.py
TOP="$(git rev-parse --show-toplevel 2>/dev/null)"
for PY in "$TOP/.venv/Scripts/python.exe" "$TOP/.venv/bin/python" "{venv_win}" "{venv_posix}"; do
  if [ -x "$PY" ]; then
    exec "$PY" "{target}" "$@"
  fi
done
if command -v python >/dev/null 2>&1; then
  exec python "{target}" "$@"
fi
exec python3 "{target}" "$@"
"""


def _git_hooks_dir() -> Path | None:
    # Hooks live in the common git dir, not per-worktree -- `.git` may be a
    # file (linked worktree) rather than a directory, so resolve via git
    # itself instead of assuming `.git/hooks`.
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = REPO_ROOT / common_dir
    return common_dir / "hooks"


def hook_body(script: str) -> str:
    return HOOK_BODY.format(
        target=(REPO_ROOT / "scripts" / "hooks" / script).as_posix(),
        venv_win=(REPO_ROOT / ".venv" / "Scripts" / "python.exe").as_posix(),
        venv_posix=(REPO_ROOT / ".venv" / "bin" / "python").as_posix(),
    )


def main() -> int:
    git_hooks_dir = _git_hooks_dir()
    if git_hooks_dir is None or not git_hooks_dir.is_dir():
        print(f"could not resolve .git/hooks (got {git_hooks_dir}) -- is this a git checkout?", file=sys.stderr)
        return 1

    rc = 0
    for hook, script in HOOKS.items():
        path = git_hooks_dir / hook
        if path.exists() and MARKER not in path.read_text(encoding="utf-8", errors="ignore"):
            print(
                f"{path} already exists and was not installed by this script -- "
                f"leaving it untouched. Add a call to scripts/hooks/{script} to it manually.",
                file=sys.stderr,
            )
            rc = 1
            continue
        path.write_text(hook_body(script), encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"installed {path}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
