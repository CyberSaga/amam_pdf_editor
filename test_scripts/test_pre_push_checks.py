"""Tests for scripts/hooks/pre_push_checks.py and its install path (plans/CI-faster.md).

The pre-push hook runs CI's fast blocking gates locally (ruff, mypy model/ utils/,
the four import-linter contracts, the threading.Thread grep) so a red check is
caught before the ~40 min CI round trip.  Covers: every gate runs and any failure
blocks the push, the grep finds hits only in view/ and controller/, the contract
list cannot drift from ci.yml, and the installer writes both hooks, prefers the
repo .venv interpreter and never overwrites a hook it did not write.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))

import install_git_hooks as installer  # noqa: E402
import pre_push_checks as checks  # noqa: E402


def _ok(returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode)


# --------------------------------------------------------------------------- gates


def test_gate_list_matches_ci_blocking_gates() -> None:
    names = [name for name, _argv in checks.gates("py")]
    assert names == ["ruff", "mypy", "import-linter"]
    by_name = dict(checks.gates("py"))
    assert by_name["ruff"][:3] == ["py", "-m", "ruff"]
    assert by_name["mypy"] == ["py", "-m", "mypy", "model/", "utils/"]
    for contract in checks.CONTRACTS:
        assert contract in by_name["import-linter"]


def test_contracts_match_the_ci_lint_imports_line() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    line = next(ln for ln in ci.splitlines() if "lint-imports" in ln and "--contract" in ln)
    assert tuple(re.findall(r"--contract (\S+)", line)) == checks.CONTRACTS


def test_main_runs_every_gate_and_returns_zero_when_all_pass(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv, cwd):
        calls.append(list(argv))
        assert Path(cwd) == tmp_path
        return _ok()

    assert checks.main(argv=[], root=tmp_path, runner=runner, python="py") == 0
    assert calls == [argv for _name, argv in checks.gates("py")]


def test_one_failing_gate_blocks_but_later_gates_still_run(tmp_path: Path, capsys) -> None:
    calls: list[str] = []

    def runner(argv, cwd):
        calls.append(argv[2])
        return _ok(1 if argv[2] == "ruff" else 0)

    assert checks.main(argv=[], root=tmp_path, runner=runner, python="py") == 1
    assert len(calls) == len(checks.gates("py"))  # mypy + import-linter still ran
    out = capsys.readouterr().out
    assert "ruff" in out and "git push --no-verify" in out


def test_threading_hit_blocks_the_push(tmp_path: Path, capsys) -> None:
    (tmp_path / "view").mkdir()
    (tmp_path / "view" / "w.py").write_text("import threading\nt = threading.Thread(target=f)\n", encoding="utf-8")
    assert checks.main(argv=[], root=tmp_path, runner=lambda argv, cwd: _ok(), python="py") == 1
    assert "w.py:2" in capsys.readouterr().out


# --------------------------------------------------------------------------- threading grep


def test_threading_grep_scans_only_view_and_controller(tmp_path: Path) -> None:
    for rel in ("view/a.py", "controller/sub/b.py", "model/c.py", "utils/d.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = threading.Thread()\n", encoding="utf-8")
    hits = checks.find_threading_thread(tmp_path)
    assert sorted(h.split(":")[0] for h in hits) == ["controller/sub/b.py", "view/a.py"]


def test_threading_grep_is_empty_for_clean_or_missing_dirs(tmp_path: Path) -> None:
    assert checks.find_threading_thread(tmp_path) == []
    (tmp_path / "view").mkdir()
    (tmp_path / "view" / "ok.py").write_text("from PyQt import QThread  # QThread is fine\n", encoding="utf-8")
    assert checks.find_threading_thread(tmp_path) == []


def test_real_tree_has_no_threading_hits() -> None:
    assert checks.find_threading_thread(REPO_ROOT) == []


# --------------------------------------------------------------------------- installer


def test_installer_writes_both_hooks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_git_hooks_dir", lambda: tmp_path)
    assert installer.main() == 0
    for hook, script in (("pre-commit", "pre_commit_device_guard.py"), ("pre-push", "pre_push_checks.py")):
        body = (tmp_path / hook).read_text(encoding="utf-8")
        assert installer.MARKER in body
        assert script in body


def test_hook_body_prefers_the_repo_venv_and_forwards_arguments(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_git_hooks_dir", lambda: tmp_path)
    installer.main()
    body = (tmp_path / "pre-push").read_text(encoding="utf-8")
    venv = body.index(".venv/Scripts/python.exe")
    fallback = body.index('python "')
    assert venv < fallback
    assert '"$@"' in body


def test_installer_refuses_a_foreign_hook_but_installs_the_other(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(installer, "_git_hooks_dir", lambda: tmp_path)
    foreign = "#!/bin/sh\necho mine\n"
    (tmp_path / "pre-push").write_text(foreign, encoding="utf-8")
    assert installer.main() == 1
    assert (tmp_path / "pre-push").read_text(encoding="utf-8") == foreign
    assert installer.MARKER in (tmp_path / "pre-commit").read_text(encoding="utf-8")
    assert "pre-push" in capsys.readouterr().err


def test_installer_overwrites_its_own_older_hook(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_git_hooks_dir", lambda: tmp_path)
    (tmp_path / "pre-commit").write_text("#!/bin/sh\n" + installer.MARKER + "old\n", encoding="utf-8")
    assert installer.main() == 0
    assert "old" not in (tmp_path / "pre-commit").read_text(encoding="utf-8")


def test_installer_fails_without_a_hooks_dir(monkeypatch) -> None:
    monkeypatch.setattr(installer, "_git_hooks_dir", lambda: None)
    assert installer.main() == 1


def test_shipped_pre_push_script_exists_and_is_runnable() -> None:
    script = REPO_ROOT / "scripts" / "hooks" / "pre_push_checks.py"
    assert script.is_file()
    with pytest.raises(SystemExit):
        # --help must not run any gate
        checks.main(argv=["--help"], root=REPO_ROOT, runner=lambda argv, cwd: pytest.fail("ran a gate"))
