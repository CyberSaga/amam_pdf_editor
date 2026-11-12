"""Tests for scripts/hooks/shell_read_guard.py (library; called by shell_edit_guard.main).

The rule denies reading a git-TRACKED file through the shell (cat, head, tail,
sed -n ranges, Get-Content, optionally piped into head/tail/nl/Select-Object)
because the Read tool does the same job and only Read counts for Edit.  Everything
else (untracked files, git commands, binary suffixes, pipes into real programs,
a `cut -c` character cap, redirects, unresolvable operands, heredoc/quoted data)
is allowed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS))

import shell_read_guard as srg  # noqa: E402

TRACKED = [
    "TODOS.md",
    "a.md",
    "b.md",
    "model/x.py",
    "sub/tracked_in_sub.md",
    "doc.pdf",
    "pic.png",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for rel in TRACKED:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    (root / "out.txt").write_text("x\n", encoding="utf-8")  # untracked
    (root / "log.txt").write_text("x\n", encoding="utf-8")  # untracked
    return root


def _check(repo: Path, command: str, tool: str = "Bash") -> list[srg.Violation]:
    return srg.read_violations(tool, command, str(repo))


DENY = [
    ("cat TODOS.md", "cat", "TODOS.md"),
    ("sed -n '10,40p' TODOS.md", "sed -n", "TODOS.md"),
    ("sed -n 1,5p TODOS.md", "sed -n", "TODOS.md"),
    ("head -50 model/x.py", "head", "model/x.py"),
    ("tail -n 20 model/x.py", "tail", "model/x.py"),
    ("head -n40 model/x.py", "head", "model/x.py"),
    ("cat model/x.py | head -100", "cat", "model/x.py"),
    ("Get-Content TODOS.md", "Get-Content", "TODOS.md"),
    ("Get-Content TODOS.md | Select-Object -First 40", "Get-Content", "TODOS.md"),
    ("Get-Content -Path TODOS.md -TotalCount 20", "Get-Content", "TODOS.md"),
    ("gc TODOS.md -Raw", "gc", "TODOS.md"),
    ("cd sub && cat tracked_in_sub.md", "cat", "tracked_in_sub.md"),
    ("nl -ba model/x.py | sed -n '10,20p'", "nl", "model/x.py"),
    ("cat -n model/x.py | tail -5", "cat", "model/x.py"),
    ("cat a.md b.md", "cat", "a.md"),
    ("cat a.md && cat b.md", "cat", "a.md"),
    ("cat TODOS.md 2>&1", "cat", "TODOS.md"),
]


@pytest.mark.parametrize(("command", "kind", "target"), DENY)
def test_denied(repo: Path, command: str, kind: str, target: str) -> None:
    found = _check(repo, command)
    assert found, command
    assert found[0].kind == kind
    assert found[0].target == target
    assert len(found[0].snippet) <= 160


def test_two_operands_both_listed_as_one_statement(repo: Path) -> None:
    assert len(_check(repo, "cat a.md b.md")) == 1


def test_powershell_tool_denied(repo: Path) -> None:
    assert _check(repo, "Get-Content TODOS.md", tool="PowerShell")


def test_gitbash_absolute_path(repo: Path) -> None:
    p = (repo / "TODOS.md").as_posix()
    if len(p) > 1 and p[1] == ":":
        p = f"/{p[0].lower()}{p[2:]}"
    assert _check(repo, f"cat {p}")


def test_absolute_path_with_other_cwd(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    found = srg.read_violations("Bash", f'cat "{repo / "TODOS.md"}"', str(other))
    assert found


ALLOW = [
    "git show HEAD:TODOS.md",
    "git diff TODOS.md",
    "git log -p TODOS.md",
    "git blame TODOS.md",
    "tail out.txt",
    "Get-Content log.txt -Tail 40",
    "wc -l TODOS.md",
    "Select-String foo TODOS.md",
    "cat TODOS.md | grep x",
    "cat TODOS.md | python x.py",
    "cat TODOS.md | wc -l",
    "cat TODOS.md | awk '{print $1}'",
    "cat TODOS.md | jq .",
    # A character cap is the one thing Read cannot do (TODOS/PITFALLS lines run to ~1.5k chars).
    "sed -n '1,200p' model/x.py | cut -c1-200",
    "sed -n '8,20p;300,320p' TODOS.md | cut -c1-300",
    "head -60 TODOS.md | cut -c1-400",
    "cat -n TODOS.md | cut -c1-300 | head -40",
    "(Get-Content TODOS.md).Count",
    "cat a.md b.md > c.md",
    "cat a.md >> out.txt",
    "head -c 200 TODOS.md",
    "tail -c 100 TODOS.md",
    "cat -A TODOS.md",
    "cat -v TODOS.md",
    "sed -n l TODOS.md",
    "sed -n '/foo/p' TODOS.md",
    "sed 's/a/b/' TODOS.md",
    "od TODOS.md",
    "xxd TODOS.md",
    "cat doc.pdf",
    "head -5 pic.png",
    "cat TODOS.md out.txt",  # mixed tracked / untracked
    "cat out.txt",
    "echo 'cat TODOS.md'",
    "grep 'cat TODOS.md' out.txt",
    "cat > f.txt <<'EOF'\ncat TODOS.md\nEOF",
    'for f in a b; do cat "$f"; done',
    "cat $f",
    "cat *.md",
    "cat missing_file.md",
    "cat",
    "",
]


@pytest.mark.parametrize("command", ALLOW)
def test_allowed(repo: Path, command: str) -> None:
    assert _check(repo, command) == [], command


def test_other_tool_name_allowed(repo: Path) -> None:
    assert srg.read_violations("Edit", "cat TODOS.md", str(repo)) == []
    assert srg.read_violations("Read", "cat TODOS.md", str(repo)) == []


def _boom(_path: Path) -> bool:
    raise AssertionError("is_tracked must not be called")


@pytest.mark.parametrize(
    "command",
    ["git show HEAD:TODOS.md", "wc -l TODOS.md", "cat TODOS.md | grep x", "cat a > b", "head -c 5 TODOS.md"],
)
def test_is_tracked_not_called_for_non_readers(repo: Path, command: str) -> None:
    assert srg.read_violations("Bash", command, str(repo), is_tracked=_boom) == []


def test_snippet_truncated(repo: Path) -> None:
    long_cmd = "cat TODOS.md | head -5 " + "# " + "x" * 400
    found = _check(repo, long_cmd)
    assert found
    assert len(found[0].snippet) <= 160


def test_deny_advice_text() -> None:
    """The advice names the replacement tool, why Edit cares, and the allowed escape."""
    advice = srg.DENY_ADVICE
    assert "Read tool with offset/limit" in advice and "Grep -n" in advice
    assert "does not count as a Read for Edit" in advice
    assert "cut -c1-300" in advice and "Untracked files" in advice
