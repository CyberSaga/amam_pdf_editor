"""Tests for ruff_on_edit.py covering shell edits (Bash/PowerShell), not only Edit/Write.

The PreToolUse leg stamps the start time of a shell call; the PostToolUse leg
ruff-checks every .py file in the git tree of the call's cwd that changed since
that stamp (tracked or untracked, by mtime).  Covers:
  - changed_py_files: modified/untracked .py after the stamp count; older edits,
    non-.py files, deleted files and files outside a git tree do not.
  - end to end: a shell call that leaves an unused import exits 2 and names the
    file; a clean change, a missing stamp and a read-only call exit 0 silently;
    the stamp is consumed; the Edit/Write leg still works.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS))

import ruff_on_edit as roe  # noqa: E402

BAD = "import os\n"
GOOD = "from __future__ import annotations\n\nVALUE = 1\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.py").write_text(GOOD, encoding="utf-8")
    (root / "notes.md").write_text("x\n", encoding="utf-8")
    (root / "gone.py").write_text(GOOD, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_changed_py_files_picks_modified_and_untracked_after_stamp(repo: Path) -> None:
    since = time.time() - 1
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "new.py").write_text(BAD, encoding="utf-8")
    (repo / "notes.md").write_text("changed\n", encoding="utf-8")
    (repo / "gone.py").unlink()
    found = sorted(p.relative_to(repo).as_posix() for p in roe.changed_py_files(repo, since))
    assert found == ["pkg/new.py", "tracked.py"]


def test_changed_py_files_skips_edits_older_than_stamp(repo: Path) -> None:
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    _age(repo / "tracked.py", 600)
    assert roe.changed_py_files(repo, time.time() - 5) == []


def test_changed_py_files_outside_git_tree_is_empty(tmp_path: Path) -> None:
    (tmp_path / "loose.py").write_text(BAD, encoding="utf-8")
    assert roe.changed_py_files(tmp_path, time.time() - 60) == []


def test_changed_py_files_clean_tree_is_empty(repo: Path) -> None:
    assert roe.changed_py_files(repo, time.time() - 60) == []


def _run(payload: dict, stamp_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_RUFF_STAMP_DIR=str(stamp_dir))
    return subprocess.run(
        [sys.executable, str(HOOKS / "ruff_on_edit.py")],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
        env=env,
    )


def _shell(event: str, repo: Path, tool_use_id: str = "toolu_1", tool: str = "Bash") -> dict:
    return {
        "hook_event_name": event,
        "tool_name": tool,
        "tool_use_id": tool_use_id,
        "session_id": "sess",
        "cwd": str(repo),
        "tool_input": {"command": "sed -i s/a/b/ tracked.py"},
    }


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_shell_call_that_leaves_lint_error_exits_2_and_names_file(repo: Path, tmp_path: Path, tool: str) -> None:
    stamps = tmp_path / "stamps"
    pre = _run(_shell("PreToolUse", repo, tool=tool), stamps)
    assert pre.returncode == 0 and pre.stdout == b""
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    post = _run(_shell("PostToolUse", repo, tool=tool), stamps)
    assert post.returncode == 2
    err = post.stderr.decode("utf-8")
    assert "tracked.py" in err and "F401" in err
    assert list(stamps.iterdir()) == []  # stamp consumed


def test_shell_call_with_clean_change_exits_0_silently(repo: Path, tmp_path: Path) -> None:
    stamps = tmp_path / "stamps"
    _run(_shell("PreToolUse", repo), stamps)
    (repo / "tracked.py").write_text(GOOD + "OTHER = 2\n", encoding="utf-8")
    post = _run(_shell("PostToolUse", repo), stamps)
    assert post.returncode == 0 and post.stderr == b""


def test_shell_call_that_changed_nothing_ignores_older_dirty_file(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    _age(repo / "tracked.py", 600)
    stamps = tmp_path / "stamps"
    _run(_shell("PreToolUse", repo), stamps)
    post = _run(_shell("PostToolUse", repo), stamps)
    assert post.returncode == 0 and post.stderr == b""


def test_post_without_stamp_exits_0_silently(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    post = _run(_shell("PostToolUse", repo, tool_use_id="never_stamped"), tmp_path / "stamps")
    assert post.returncode == 0 and post.stderr == b""


def test_stamps_are_per_tool_use(repo: Path, tmp_path: Path) -> None:
    stamps = tmp_path / "stamps"
    _run(_shell("PreToolUse", repo, tool_use_id="a"), stamps)
    _run(_shell("PreToolUse", repo, tool_use_id="b"), stamps)
    assert len(list(stamps.iterdir())) == 2
    _run(_shell("PostToolUse", repo, tool_use_id="a"), stamps)
    assert len(list(stamps.iterdir())) == 1


def test_edit_leg_still_reports_findings(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(repo / "tracked.py")}}
    post = _run(payload, tmp_path / "stamps")
    assert post.returncode == 2 and "F401" in post.stderr.decode("utf-8")


def test_edit_leg_without_hook_event_name_still_works(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked.py").write_text(BAD, encoding="utf-8")
    post = _run({"tool_input": {"file_path": str(repo / "tracked.py")}}, tmp_path / "stamps")
    assert post.returncode == 2


def test_old_stamps_are_pruned(repo: Path, tmp_path: Path) -> None:
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    stale = stamps / "stale.stamp"
    stale.write_text("0", encoding="utf-8")
    _age(stale, 3 * 86400)
    _run(_shell("PreToolUse", repo), stamps)
    assert not stale.exists()
