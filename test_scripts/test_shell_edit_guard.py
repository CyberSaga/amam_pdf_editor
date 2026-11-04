"""Tests for scripts/hooks/shell_edit_guard.py (PreToolUse Bash|PowerShell).

The guard denies in-place shell edits of git-TRACKED files: `sed -i`,
`perl -pi`, `>` redirects, `tee`, `Set-Content`/`Out-File` and
`[IO.File]::Write*`.  Appends (`>>`, tee -a, Add-Content, Out-File -Append,
AppendAll*), untracked files, scratch paths, read-only commands,
Python edit scripts, programs that write files themselves, heredoc bodies and
unresolvable targets ($VAR, globs, find -exec) pass.  Covers:
  - edit_targets: which command shapes yield which raw target words.
  - violations: tracked resolution against a temp git repo (cwd, a leading
    `cd`, Git Bash `/c/...` paths, a second repo standing in for a lane).
  - end to end: the deny JSON, silence on allowed commands, fail open on a
    payload that is not JSON.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS))

import shell_edit_guard as seg  # noqa: E402

TRACKED = [
    "model/pdf_model.py",
    "TODOS.md",
    "docs/PITFALLS.md",
    "scripts/run_suite.py",
    "view/text_editing.py",
    "test_scripts/test_hyphen_wrap.py",
    "README.md",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _make_repo(root: Path, files: list[str]) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = _make_repo(tmp_path / "repo", TRACKED)
    (root / "probe_override.py").write_text("x\n", encoding="utf-8")  # untracked
    return root


@pytest.fixture
def lane(tmp_path: Path) -> Path:
    return _make_repo(tmp_path / "lane", ["README.md"])


def _gitbash(path: Path) -> str:
    p = path.resolve().as_posix()
    return f"/{p[0].lower()}{p[2:]}" if len(p) > 1 and p[1] == ":" else p


DENY = [
    ("Bash", "sed -i 's/a/b/' model/pdf_model.py"),
    ("Bash", "sed -i '17s/Callable, Iterator/Callable, Iterable, Iterator/' model/pdf_model.py && .venv/Scripts/python.exe -m pytest test_scripts/t.py"),
    ("Bash", "sed --in-place=.bak -e 's/a/b/' scripts/run_suite.py"),
    ("Bash", "sed -Ei 's/a/b/' TODOS.md"),
    ("Bash", "sed -i.bak 's/a/b/' TODOS.md"),
    ("Bash", "sed -e 's/a/b/' -i docs/PITFALLS.md"),
    ("Bash", "perl -pi -e 's/a/b/' view/text_editing.py"),
    ("Bash", "cat > scripts/run_suite.py <<'PYEOF'\nprint(1)\nPYEOF"),
    ("Bash", "echo x > TODOS.md"),
    ("Bash", 'echo x >"TODOS.md"'),
    ("Bash", "git show HEAD:TODOS.md | tee docs/PITFALLS.md"),
    ("Bash", "sed -i 's/a/b/' probe_override.py model/pdf_model.py"),
    ("Bash", "true; sed -i 's/a/b/' TODOS.md"),
    ("PowerShell", "(Get-Content model/pdf_model.py) -replace 'a','b' | Set-Content model/pdf_model.py"),
    ("PowerShell", '"x" | Out-File -FilePath TODOS.md'),
    ("PowerShell", "Set-Content -LiteralPath 'TODOS.md' -Value x -Encoding utf8"),
    ("PowerShell", "[IO.File]::WriteAllText('TODOS.md', 'x')"),
    ("PowerShell", "Get-Date > TODOS.md"),
]

ALLOW = [
    # appends pass: no mis-match, no line-ending rewrite; ruff catches doubled code (F811)
    ("Bash", "cat >> test_scripts/test_hyphen_wrap.py <<'EOF'\ndef test_x():\n    pass\nEOF"),
    ("Bash", "printf 'a\\n' >> docs/PITFALLS.md"),
    ("Bash", "git show HEAD:TODOS.md | tee -a TODOS.md > /dev/null"),
    ("PowerShell", "Add-Content -Path docs/PITFALLS.md -Value 'x'"),
    ("PowerShell", "[System.IO.File]::AppendAllText(\"docs/PITFALLS.md\", 'x')"),
    ("PowerShell", '"x" | Out-File -FilePath TODOS.md -Append'),
    ("Bash", "sed -i 's/a/b/' probe_override.py"),
    ("Bash", "sed -i 's/a/b/' /tmp/impl1.py"),
    ("Bash", 'sed -i \'12d\' "$CLAUDE_SCRATCHPAD/p.py"'),
    ("Bash", "sed -n 1486,1493p model/pdf_model.py"),
    ("Bash", "sed 's/a/b/' model/pdf_model.py > \"$S/out.txt\""),
    ("Bash", "sed 's/a/b/' model/pdf_model.py > out_untracked.txt"),
    ("Bash", "python - <<'EOF'\np = 'model/pdf_model.py'\ns = open(p, encoding='utf-8', newline='').read()\nopen(p, 'w', encoding='utf-8', newline='').write(s)\nEOF"),
    ("Bash", ".venv/Scripts/python.exe -m pytest test_scripts/test_hyphen_wrap.py -q > \"$L/run.log\" 2>&1"),
    ("Bash", "grep -n \"sed -i\" docs/PITFALLS.md"),
    ("Bash", "grep -n 'echo x > TODOS.md' docs/PITFALLS.md"),
    ("Bash", "cat > notes_new.txt <<'EOF'\nsed -i 's/a/b/' TODOS.md\necho x > TODOS.md\nEOF"),
    ("Bash", "cat > test_scripts/test_zz_new.py <<'EOF'\ndef test_x():\n    pass\nEOF"),
    ("Bash", "python scripts/build_pitfalls_index.py"),
    ("Bash", ".venv/Scripts/python.exe -m ruff check --fix model/pdf_model.py"),
    ("Bash", "git checkout -- model/pdf_model.py"),
    ("Bash", "some_cmd > /dev/null 2>&1"),
    ("Bash", "some_cmd 2>nul"),
    ("Bash", "some_cmd 2>&1 | tail -5"),
    ("Bash", "python -c \"import sys; print(1 > 0)\" > out_untracked.txt"),
    ("Bash", "find . -name '*.py' -exec sed -i 's/a/b/' {} +"),
    ("Bash", "sed -i 's/a/b/' model/*.py"),
    ("Bash", "cd \"$TEMP\" && sed -i 's/a/b/' TODOS.md"),
    ("Bash", "sed -i 's/a/b/' missing_dir/TODOS.md"),
    ("PowerShell", "Get-Content TODOS.md | Select-Object -First 5"),
    ("PowerShell", "Set-Content -Path $env:TEMP/x.txt -Value 1"),
    ("PowerShell", "if ($a -gt 3) { 'x' } > out_untracked.txt"),
]


@pytest.mark.parametrize("tool,command", DENY)
def test_tracked_in_place_edit_is_denied(repo: Path, tool: str, command: str) -> None:
    found = seg.violations(tool, command, str(repo))
    assert found, command


@pytest.mark.parametrize("tool,command", ALLOW)
def test_allowed_command_passes(repo: Path, tool: str, command: str) -> None:
    assert seg.violations(tool, command, str(repo)) == [], command


def test_leading_cd_resolves_targets_in_that_repo(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    command = f"cd {_gitbash(repo)} && sed -i 's/x/y/' TODOS.md"
    assert seg.violations("Bash", command, str(outside))


def test_quoted_windows_cd_resolves(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    command = f'cd "{repo}"; Set-Content TODOS.md x'
    assert seg.violations("PowerShell", command, str(outside))


def test_lane_worktree_is_not_exempt(repo: Path, lane: Path) -> None:
    command = f"cd {_gitbash(lane)} && sed -i 's/a/b/' README.md"
    assert seg.violations("Bash", command, str(repo))


def test_absolute_gitbash_target_resolves(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    command = f"sed -i 's/a/b/' {_gitbash(repo)}/docs/PITFALLS.md"
    assert seg.violations("Bash", command, str(outside))


def test_cwd_outside_any_repo_allows(tmp_path: Path) -> None:
    (tmp_path / "TODOS.md").write_text("x\n", encoding="utf-8")
    assert seg.violations("Bash", "sed -i 's/a/b/' TODOS.md", str(tmp_path)) == []


def test_violation_names_kind_and_target(repo: Path) -> None:
    [v] = seg.violations("Bash", "sed -i 's/a/b/' TODOS.md", str(repo))
    assert v.kind == "sed -i" and v.target == "TODOS.md"


def test_edit_targets_shapes() -> None:
    kinds = {kind for kind, _word, _cd in seg.edit_targets("sed -i 's/a/b/' a.md; echo x > b.md | tee c.md")}
    assert kinds == {"sed -i", "redirect", "tee"}
    assert seg.edit_targets("echo x >> b.md") == []
    words = [word for _k, word, _cd in seg.edit_targets("sed -e 's/a/b/' -i one.md two.md")]
    assert words == ["one.md", "two.md"]
    assert seg.edit_targets("sed 's/a/b/' x.md") == []
    assert seg.edit_targets("echo 'a > b.md'") == []


def _run(payload: object) -> subprocess.CompletedProcess:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run([sys.executable, str(HOOKS / "shell_edit_guard.py")], input=raw, capture_output=True, timeout=60)


def test_end_to_end_deny_json(repo: Path) -> None:
    result = _run({"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": "sed -i 's/a/b/' TODOS.md"}})
    assert result.returncode == 0
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert "TODOS.md" in reason and "newline=''" in reason and "Edit tool" in reason


def test_end_to_end_allowed_is_silent(repo: Path) -> None:
    result = _run({"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": "sed -n 1,5p TODOS.md"}})
    assert result.returncode == 0 and result.stdout == b""


def test_end_to_end_other_tool_is_silent(repo: Path) -> None:
    result = _run({"tool_name": "Edit", "cwd": str(repo), "tool_input": {"file_path": str(repo / "TODOS.md")}})
    assert result.returncode == 0 and result.stdout == b""


def test_end_to_end_garbage_fails_open() -> None:
    result = _run(b"not json")
    assert result.returncode == 1 and b"NOT checked" in result.stderr
