"""End-to-end tests for the Codex port of the Claude hooks (scripts/hooks/codex_hook.py).

Codex CLI 0.166 ignores hook exit codes (exit 2 never blocks); only stdout JSON
acts.  So every test pipes one payload (a scrubbed live Codex payload from
test_scripts/fixtures/codex_hook_payloads.jsonl, or a synthetic variant) into
`python scripts/hooks/codex_hook.py <Event>`, asserts exit 0, and asserts on
the single JSON object on stdout.  Covers:
  - PreToolUse Bash: bare / system-python / whole-suite pytest, process kills
    (main thread and subagent), `ruff format`, in-place shell edits of tracked
    files; several violations come back as ONE deny object.
  - PostToolUse apply_patch: ruff findings in the .py files the patch touched
    (relative and absolute paths; files outside the project, failed patches
    and deletions ignored).  PostToolUse Bash: .py files changed since the
    PreToolUse stamp.
  - Stop latch: UserPromptSubmit arms/lifts it, PreToolUse
    collaborationspawn_agent is denied while armed.
  - SubagentStart: retry-cap footer as additionalContext.  SessionStart:
    rulebook pointer.
  - Stop: pre-paste gate (dirty tree + paste cue) and the Done gate (files this
    session changed: tests, TODOS.md, PITFALLS index, ruff, future import,
    typing.List/Optional), both once per stop (stop_hook_active).
  - Fail-open: unknown event, malformed stdin, no argument -> exit 0, no output.
  - .codex/hooks.json registers only relative commands, no machine paths.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
FIXTURES = Path(__file__).parent / "fixtures" / "codex_hook_payloads.jsonl"
HOOKS_JSON = REPO_ROOT / ".codex" / "hooks.json"
VENV_PY = r".venv\Scripts\python.exe"
BAD_PY = "import os\n"
GOOD_PY = "from __future__ import annotations\n\nVALUE = 1\n"


# --------------------------------------------------------------------------- helpers


def _records() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fx(event: str, tool: str | None = None, rule: str | None = None, **over: object) -> dict:
    """A deep copy of the first fixture payload for *event* (and *tool*, *rule*), with overrides."""
    for rec in _records():
        p = rec["payload"]
        if p.get("hook_event_name") != event:
            continue
        if tool is not None and p.get("tool_name") != tool:
            continue
        if rule is not None and rec.get("rule") != rule:
            continue
        payload = copy.deepcopy(p)
        payload.update(over)
        return payload
    raise LookupError(f"no fixture for {event}/{tool}/{rule}")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    e = dict(os.environ)
    e["PDF_EDITOR_CODEX_STATE_DIR"] = str(tmp_path / "codex_state")
    e["CLAUDE_RUFF_STAMP_DIR"] = str(tmp_path / "ruff_stamps")
    return e


def _run_raw(args: list[str], data: bytes, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / "codex_hook.py"), *args],
        input=data,
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
        env=env,
    )


def _run(event: str, payload: dict, env: dict[str, str]) -> dict | None:
    """Run the hook; the Codex contract is exit 0 and at most ONE JSON object on stdout."""
    proc = _run_raw([event], json.dumps(payload).encode("utf-8"), env)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8").strip()
    if not out:
        return None
    return json.loads(out)  # raises on two concatenated objects


def _deny_reason(out: dict | None) -> str:
    assert out is not None, "expected a deny, got no output"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


def _context(out: dict | None, event: str) -> str:
    assert out is not None, "expected additionalContext, got no output"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == event
    return hso["additionalContext"]


def _block_reason(out: dict | None) -> str:
    assert out is not None, "expected a block, got no output"
    assert out["decision"] == "block"
    return out["reason"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "test_scripts").mkdir()
    (root / "docs").mkdir()
    _git(root, "init", "-q")
    (root / "a.txt").write_text("1\n", encoding="utf-8")
    (root / "TODOS.md").write_text("# TODOS\n", encoding="utf-8")
    (root / "docs" / "PITFALLS.md").write_text("# P\n", encoding="utf-8")
    (root / "docs" / "PITFALLS_INDEX.md").write_text("# I\n", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text(GOOD_PY, encoding="utf-8")
    (root / "test_scripts" / "test_mod.py").write_text(GOOD_PY, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def _bash_pre(command: str, cwd: str | Path = REPO_ROOT, **over: object) -> dict:
    return _fx("PreToolUse", "Bash", cwd=str(cwd), tool_input={"command": command}, **over)


# --------------------------------------------------------------------------- fixtures + registry


def test_fixture_payloads_are_scrubbed_and_cover_the_events() -> None:
    text = FIXTURES.read_text(encoding="utf-8")
    assert not re.search(r"C:\\\\Users\\\\", text)
    events = {r["payload"]["hook_event_name"] for r in _records()}
    assert {"PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop", "SessionStart"} <= events


def test_hooks_json_registers_relative_commands_without_machine_paths() -> None:
    raw = HOOKS_JSON.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]|\\\\Users|/Users/|/home/|\$\{|CLAUDE_PROJECT_DIR|%\w+%", raw)
    hooks = json.loads(raw)["hooks"]
    for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SubagentStart", "SessionStart"):
        assert event in hooks, event
    for event, groups in hooks.items():
        for group in groups:
            for h in group["hooks"]:
                assert h["type"] == "command"
                assert h["command"] == f"python scripts/hooks/codex_hook.py {event}"
                assert 0 < h["timeout"] <= 60
    for tool in ("Bash", "collaborationspawn_agent"):
        assert any(re.search(g["matcher"], tool) for g in hooks["PreToolUse"]), tool
    for tool in ("Bash", "apply_patch"):
        assert any(re.search(g["matcher"], tool) for g in hooks["PostToolUse"]), tool


# --------------------------------------------------------------------------- fail-open contract


@pytest.mark.parametrize(
    "args, data",
    [
        (["Bogus"], json.dumps({"hook_event_name": "Bogus"}).encode()),
        (["PreToolUse"], b"not json at all"),
        (["PreToolUse"], b"[1, 2, 3]"),
        (["PreToolUse"], b""),
        ([], json.dumps({"hook_event_name": "PreToolUse"}).encode()),
        (["PostToolUse"], json.dumps({"hook_event_name": "PostToolUse", "tool_name": "apply_patch", "tool_input": "x"}).encode()),
    ],
)
def test_unknown_event_or_malformed_stdin_exits_0_silently(args: list[str], data: bytes, env: dict[str, str]) -> None:
    proc = _run_raw(args, data, env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == b""


@pytest.mark.parametrize(
    "event, tool, rule",
    [
        ("PreToolUse", "Bash", "deny-json"),
        ("PreToolUse", "collaborationwait_agent", None),
        ("PostToolUse", "Bash", "post-ctx"),
        ("PostToolUse", "collaborationspawn_agent", None),
        ("PostModelRequest", None, None),
        ("SessionEnd", None, None),
        ("SubagentStop", None, "substop-block"),
    ],
)
def test_benign_fixture_payloads_pass_silently(event: str, tool: str | None, rule: str | None, env: dict[str, str]) -> None:
    payload = _fx(event, tool, rule, cwd=str(REPO_ROOT))
    assert _run(event, payload, env) is None


# --------------------------------------------------------------------------- PreToolUse Bash: test-command rules


@pytest.mark.parametrize(
    "command, needle",
    [
        ("pytest test_scripts/test_x.py", "never bare `pytest`"),
        ("python -m pytest test_scripts/test_x.py -q", "repo venv"),
        (VENV_PY + " -m pytest test_scripts/ -q", "run_suite.py"),
        (VENV_PY + " -m pytest -q", "run_suite.py"),
        ("taskkill /F /IM python.exe", "taskkill"),
        ("Get-Process python | Stop-Process -Force", "taskkill"),
        (".venv\\Scripts\\ruff.exe format .", "ruff format"),
        ('& "C:/repo/.venv/Scripts/python.exe" -m ruff format scripts', "ruff format"),
    ],
)
def test_pre_bash_denies_rule_breaking_commands(command: str, needle: str, env: dict[str, str]) -> None:
    reason = _deny_reason(_run("PreToolUse", _bash_pre(command), env))
    assert needle in reason


@pytest.mark.parametrize(
    "command",
    [
        VENV_PY + " -m pytest test_scripts/test_x.py -q --tb=short *> $env:TEMP\\out.txt",
        VENV_PY + " scripts/run_suite.py",
        "ruff check . && git status",
        ".venv\\Scripts\\ruff.exe format --check .",
        "ruff format --diff scripts",
        'rg -n "ruff format|taskkill" docs',
        "Get-Content CLAUDE.md",
    ],
)
def test_pre_bash_allows_clean_commands(command: str, env: dict[str, str]) -> None:
    assert _run("PreToolUse", _bash_pre(command), env) is None


def test_pre_bash_denies_kills_inside_subagents_too(env: dict[str, str]) -> None:
    payload = _bash_pre("taskkill /F /PID 1234", agent_id="01a1-sub", agent_type="worker")
    assert "taskkill" in _deny_reason(_run("PreToolUse", payload, env))


# --------------------------------------------------------------------------- PreToolUse Bash: shell edit guard


@pytest.mark.parametrize(
    "command",
    ["sed -i s/1/2/ a.txt", "Set-Content a.txt 'x'", "echo x > a.txt", "'x' | Out-File -FilePath a.txt"],
)
def test_pre_bash_denies_in_place_edits_of_tracked_files(command: str, repo: Path, env: dict[str, str]) -> None:
    reason = _deny_reason(_run("PreToolUse", _bash_pre(command, cwd=repo), env))
    assert "git-tracked" in reason and "a.txt" in reason
    assert "apply_patch" in reason and "Edit tool" not in reason


@pytest.mark.parametrize(
    "command",
    ["echo x >> a.txt", "echo x > new.txt", "Add-Content a.txt 'x'", "python - <<'EOF'\nopen('a.txt')\nEOF"],
)
def test_pre_bash_allows_appends_and_untracked_targets(command: str, repo: Path, env: dict[str, str]) -> None:
    assert _run("PreToolUse", _bash_pre(command, cwd=repo), env) is None


@pytest.mark.parametrize(
    "command",
    ["Get-Content a.txt | Select-Object -Skip 9 -First 20", "Get-Content a.txt -Tail 40", "cat a.txt", "sed -n '1,5p' a.txt"],
)
def test_pre_bash_allows_shell_reads_of_tracked_files(command: str, repo: Path, env: dict[str, str]) -> None:
    """Codex reads through the shell by design (AGENTS.md Tools); the Claude-only read guard must not reach it."""
    assert _run("PreToolUse", _bash_pre(command, cwd=repo), env) is None


def test_pre_bash_merges_every_violation_into_one_deny(repo: Path, env: dict[str, str]) -> None:
    reason = _deny_reason(_run("PreToolUse", _bash_pre("sed -i s/1/2/ a.txt; pytest test_scripts/test_x.py", cwd=repo), env))
    assert "never bare `pytest`" in reason and "a.txt" in reason


# --------------------------------------------------------------------------- PostToolUse apply_patch: ruff


def _patch(*lines: str) -> str:
    return "*** Begin Patch\n" + "\n".join(lines) + "\n*** End Patch"


def _post_patch(repo: Path, patch: str, exit_code: int = 0) -> dict:
    response = f"Exit code: {exit_code}\nWall time: 0.1 seconds\nOutput:\nSuccess. Updated the following files:\nM x\n"
    return _fx("PostToolUse", "apply_patch", cwd=str(repo), tool_input={"command": patch}, tool_response=response)


def test_post_patch_blocks_with_ruff_findings_for_a_relative_path(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "bad.py").write_text(BAD_PY, encoding="utf-8")
    out = _run("PostToolUse", _post_patch(repo, _patch("*** Add File: pkg/bad.py", "+import os")), env)
    reason = _block_reason(out)
    assert "F401" in reason and "bad.py" in reason


def test_post_patch_blocks_for_an_absolute_windows_style_path(repo: Path, env: dict[str, str]) -> None:
    target = repo / "pkg" / "mod.py"
    target.write_text(BAD_PY, encoding="utf-8")
    patch = _patch(f"*** Update File: {str(target)}", "@@", "+import os")
    assert "F401" in _block_reason(_run("PostToolUse", _post_patch(repo, patch), env))


def test_post_patch_checks_the_move_target(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "moved.py").write_text(BAD_PY, encoding="utf-8")
    patch = _patch("*** Update File: pkg/mod.py", "*** Move to: pkg/moved.py", "@@", "+import os")
    assert "moved.py" in _block_reason(_run("PostToolUse", _post_patch(repo, patch), env))


def test_post_patch_is_silent_for_clean_files(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "ok.py").write_text(GOOD_PY, encoding="utf-8")
    assert _run("PostToolUse", _post_patch(repo, _patch("*** Add File: pkg/ok.py", "+VALUE = 1")), env) is None


def test_post_patch_ignores_files_outside_the_project(repo: Path, tmp_path: Path, env: dict[str, str]) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "bad.py").write_text(BAD_PY, encoding="utf-8")
    patch = _patch(f"*** Add File: {outside / 'bad.py'}", "+import os", "*** Add File: ../elsewhere/bad.py", "+import os")
    assert _run("PostToolUse", _post_patch(repo, patch), env) is None


def test_post_patch_ignores_deletions_non_py_and_failed_patches(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "bad.py").write_text(BAD_PY, encoding="utf-8")
    assert _run("PostToolUse", _post_patch(repo, _patch("*** Delete File: pkg/bad.py")), env) is None
    assert _run("PostToolUse", _post_patch(repo, _patch("*** Update File: a.txt", "+2")), env) is None
    failed = _post_patch(repo, _patch("*** Add File: pkg/bad.py", "+import os"), exit_code=1)
    assert _run("PostToolUse", failed, env) is None


# --------------------------------------------------------------------------- PostToolUse Bash: ruff on shell edits


def test_post_bash_lints_py_files_changed_since_the_pre_stamp(repo: Path, env: dict[str, str]) -> None:
    pre = _bash_pre("python gen.py", cwd=repo, tool_use_id="exec-stamp-1", session_id="s-shell")
    assert _run("PreToolUse", pre, env) is None
    time.sleep(0.05)
    (repo / "pkg" / "gen.py").write_text(BAD_PY, encoding="utf-8")
    post = _fx("PostToolUse", "Bash", cwd=str(repo), tool_input={"command": "python gen.py"}, tool_response="", tool_use_id="exec-stamp-1", session_id="s-shell")
    reason = _block_reason(_run("PostToolUse", post, env))
    assert "F401" in reason and "gen.py" in reason
    # the stamp is consumed: a replay of the same PostToolUse is silent
    assert _run("PostToolUse", post, env) is None


def test_post_bash_without_a_stamp_is_silent(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "gen.py").write_text(BAD_PY, encoding="utf-8")
    post = _fx("PostToolUse", "Bash", cwd=str(repo), tool_input={"command": "x"}, tool_response="", tool_use_id="exec-none")
    assert _run("PostToolUse", post, env) is None


# --------------------------------------------------------------------------- stop latch


def test_stop_latch_arms_on_a_stop_prompt_denies_spawn_and_lifts_on_the_next_prompt(env: dict[str, str]) -> None:
    spawn = _fx("PreToolUse", "collaborationspawn_agent", cwd=str(REPO_ROOT), session_id="s-latch")
    assert _run("PreToolUse", spawn, env) is None
    arm = _fx("UserPromptSubmit", rule="ctx", prompt="stop when this round finishes", cwd=str(REPO_ROOT), session_id="s-latch")
    assert _run("UserPromptSubmit", dict(arm, prompt="run the next pass over plans/x.md"), env) is None
    assert "STOP LATCH" in _context(_run("UserPromptSubmit", arm, env), "UserPromptSubmit")
    reason = _deny_reason(_run("PreToolUse", spawn, env))
    assert "STOP LATCH" in reason and "stop when this round finishes" in reason
    # a slash line and harness text neither arm nor lift
    assert _run("UserPromptSubmit", dict(arm, prompt="/hooks"), env) is None
    assert _deny_reason(_run("PreToolUse", spawn, env))
    # a subagent's spawn in the same session is latched too (same session_id)
    assert _deny_reason(_run("PreToolUse", dict(spawn, agent_id="sub-1", agent_type="worker"), env))
    lift = dict(arm, prompt="ok, go ahead with the next pass")
    assert _run("UserPromptSubmit", lift, env) is None
    assert _run("PreToolUse", spawn, env) is None


def test_stop_latch_also_denies_the_unprefixed_spawn_agent_name(env: dict[str, str]) -> None:
    """The remote adapter branch names the tool `spawn_agent`; the captured payloads name it
    `collaborationspawn_agent`. Either spelling must hit the latch, in the hook and its matcher."""
    arm = _fx("UserPromptSubmit", rule="ctx", prompt="停止", cwd=str(REPO_ROOT), session_id="s-plain")
    assert _run("UserPromptSubmit", dict(arm, prompt="開始下一輪"), env) is None
    assert "STOP LATCH" in _context(_run("UserPromptSubmit", arm, env), "UserPromptSubmit")
    plain = _fx("PreToolUse", "collaborationspawn_agent", cwd=str(REPO_ROOT), session_id="s-plain")
    plain["tool_name"] = "spawn_agent"
    assert "STOP LATCH" in _deny_reason(_run("PreToolUse", plain, env))
    hooks = json.loads((REPO_ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    matchers = [g["matcher"] for g in hooks["hooks"]["PreToolUse"]]
    assert any(re.search(m, "spawn_agent") for m in matchers)


def test_ruff_format_check_flag_must_belong_to_the_format_command(env: dict[str, str]) -> None:
    """Remote-branch finding: `--check` in a LATER segment must not excuse a real `ruff format`."""
    def run(cmd: str):
        return _run("PreToolUse", _fx("PreToolUse", "Bash", cwd=str(REPO_ROOT), tool_input={"command": cmd}), env)

    assert "ruff format" in _deny_reason(run("ruff format .; echo --check"))
    assert "ruff format" in _deny_reason(run("ruff format . && echo --diff"))
    assert run("ruff format --check .") is None
    assert run("echo 'ruff format .'") is None


def test_stop_latch_is_per_session(env: dict[str, str]) -> None:
    arm = _fx("UserPromptSubmit", rule="ctx", prompt="停止", cwd=str(REPO_ROOT), session_id="s-one")
    assert _run("UserPromptSubmit", dict(arm, prompt="開始下一輪"), env) is None
    assert "STOP LATCH" in _context(_run("UserPromptSubmit", arm, env), "UserPromptSubmit")
    same = _fx("PreToolUse", "collaborationspawn_agent", cwd=str(REPO_ROOT), session_id="s-one")
    assert "STOP LATCH" in _deny_reason(_run("PreToolUse", same, env))
    other = dict(same, session_id="another-session")
    assert _run("PreToolUse", other, env) is None


@pytest.mark.parametrize(
    "brief",
    [
        "Implement the fix. Do not run more than one pytest at a time.",
        "- 不使用 taskkill、Stop-Process、kill 等結束行程的指令；遇到卡住就停下來回報。",
        "stop when the tests pass and report",
    ],
)
def test_the_first_prompt_of_a_session_never_arms_the_latch(brief: str, env: dict[str, str]) -> None:
    """Under `codex exec` the brief is the session's only prompt; its rules read like stop phrases."""
    first = _fx("UserPromptSubmit", rule="ctx", prompt=brief, cwd=str(REPO_ROOT), session_id="s-brief")
    assert _run("UserPromptSubmit", first, env) is None
    spawn = _fx("PreToolUse", "collaborationspawn_agent", cwd=str(REPO_ROOT), session_id="s-brief")
    assert _run("PreToolUse", spawn, env) is None


# --------------------------------------------------------------------------- SubagentStart / SessionStart


def test_subagent_start_injects_the_retry_cap_footer(env: dict[str, str]) -> None:
    out = _run("SubagentStart", _fx("SubagentStart", cwd=str(REPO_ROOT)), env)
    assert "Retry cap:" in _context(out, "SubagentStart")


def test_session_start_points_at_the_rulebook(env: dict[str, str]) -> None:
    out = _run("SessionStart", _fx("SessionStart", cwd=str(REPO_ROOT)), env)
    text = _context(out, "SessionStart")
    assert "AGENTS.md" in text and "docs/codex/HOOKS.md" in text


# --------------------------------------------------------------------------- Stop: pre-paste gate


def test_paste_gate_blocks_the_stop_once_and_warns_on_the_prompt(repo: Path, env: dict[str, str]) -> None:
    (repo / "a.txt").write_text("2\n", encoding="utf-8")
    stop = _fx("Stop", rule="stop-block", cwd=str(repo), last_assistant_message="Brief ready, please paste.")
    reason = _block_reason(_run("Stop", stop, env))
    assert "PRE-PASTE GATE" in reason and "a.txt" in reason
    assert _run("Stop", dict(stop, stop_hook_active=True), env) is None
    prompt = _fx("UserPromptSubmit", rule="ctx", cwd=str(repo), prompt="我貼了 v16 pilot")
    assert "a.txt" in _context(_run("UserPromptSubmit", prompt, env), "UserPromptSubmit")


def test_paste_gate_is_silent_on_a_clean_tree(repo: Path, env: dict[str, str]) -> None:
    stop = _fx("Stop", rule="stop-block", cwd=str(repo), last_assistant_message="Brief ready, please paste.")
    assert _run("Stop", stop, env) is None


# --------------------------------------------------------------------------- Stop: Done gate


def _start_session(env: dict[str, str], repo: Path, session_id: str = "s-done", started: float | None = None) -> dict:
    """Open the session the way Codex does (SessionStart), optionally back-dating its start."""
    _run("SessionStart", _fx("SessionStart", cwd=str(repo), session_id=session_id), env)
    if started is not None:
        state = Path(env["PDF_EDITOR_CODEX_STATE_DIR"]) / f"{session_id}.json"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["started"] = started
        state.write_text(json.dumps(data), encoding="utf-8")
    return _fx("Stop", rule="stop-block", cwd=str(repo), session_id=session_id, last_assistant_message="Done.")


def test_done_gate_blocks_a_source_change_without_test_and_todos(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    reason = _block_reason(_run("Stop", stop, env))
    assert "DONE GATE" in reason
    assert "test_scripts" in reason and "TODOS.md" in reason
    assert _run("Stop", dict(stop, stop_hook_active=True), env) is None


def test_done_gate_passes_when_test_and_todos_changed(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    (repo / "test_scripts" / "test_new.py").write_text(GOOD_PY, encoding="utf-8")
    (repo / "TODOS.md").write_text("# TODOS\n- done\n", encoding="utf-8")
    assert _run("Stop", stop, env) is None


def test_done_gate_ignores_files_dirty_before_the_session(repo: Path, env: dict[str, str]) -> None:
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    old = time.time() - 600
    os.utime(repo / "pkg" / "mod.py", (old, old))
    stop = _start_session(env, repo, started=time.time() - 60)
    assert _run("Stop", stop, env) is None


def test_done_gate_lists_convention_and_ruff_breaks(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "new_mod.py").write_text("import os\nVALUE: Optional[int] = None\n", encoding="utf-8")
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "from typing import List\n", encoding="utf-8")
    (repo / "test_scripts" / "test_new.py").write_text(GOOD_PY, encoding="utf-8")
    (repo / "TODOS.md").write_text("# TODOS\n- done\n", encoding="utf-8")
    reason = _block_reason(_run("Stop", stop, env))
    assert "from __future__ import annotations" in reason and "new_mod.py" in reason
    assert "typing" in reason
    assert "F401" in reason


def test_done_gate_flags_bare_optional_only_when_typing_is_imported(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "test_scripts" / "test_new.py").write_text(GOOD_PY + 'SRC = "VALUE: Optional[int] = None"\n', encoding="utf-8")
    (repo / "TODOS.md").write_text("# TODOS\n- done\n", encoding="utf-8")
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    assert _run("Stop", stop, env) is None
    # a legacy module that already imports Optional gains one more bare Optional[...] line
    (repo / "pkg" / "mod.py").write_text(
        "from __future__ import annotations\n\nfrom typing import Optional\n\nVALUE: Optional[int] = None\n",
        encoding="utf-8",
    )
    _git(repo, "add", "pkg/mod.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "legacy typing")
    (repo / "pkg" / "mod.py").write_text(
        "from __future__ import annotations\n\nfrom typing import Optional\n\nVALUE: Optional[int] = None\n"
        "OTHER: Optional[str] = None\n",
        encoding="utf-8",
    )
    reason = _block_reason(_run("Stop", stop, env))
    assert "typing" in reason and "pkg/mod.py" in reason


def test_done_gate_wants_the_pitfalls_index_regenerated(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "docs" / "PITFALLS.md").write_text("# P\n\n## New entry\n", encoding="utf-8")
    reason = _block_reason(_run("Stop", stop, env))
    assert "PITFALLS_INDEX.md" in reason and "build_pitfalls_index.py" in reason
    (repo / "docs" / "PITFALLS_INDEX.md").write_text("# I\n- New entry\n", encoding="utf-8")
    assert _run("Stop", stop, env) is None


def test_stop_merges_paste_and_done_reasons_into_one_block(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    reason = _block_reason(_run("Stop", dict(stop, last_assistant_message="Ready, please paste v16."), env))
    assert "PRE-PASTE GATE" in reason and "DONE GATE" in reason


def test_done_gate_blocks_once_per_problem_set_not_every_stop(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    assert "DONE GATE" in _block_reason(_run("Stop", stop, env))
    # a later plain Q&A Stop with the same unresolved problems does not resume the turn again
    assert _run("Stop", stop, env) is None
    # a different problem set blocks again
    (repo / "test_scripts" / "test_new.py").write_text(GOOD_PY, encoding="utf-8")
    assert "TODOS.md" in _block_reason(_run("Stop", stop, env))


def test_done_gate_is_silent_while_the_stop_latch_is_armed(repo: Path, env: dict[str, str]) -> None:
    stop = _start_session(env, repo)
    time.sleep(0.05)
    (repo / "pkg" / "mod.py").write_text(GOOD_PY + "OTHER = 2\n", encoding="utf-8")
    prompt = _fx("UserPromptSubmit", rule="ctx", prompt="run the next pass", cwd=str(repo), session_id="s-done")
    assert _run("UserPromptSubmit", prompt, env) is None
    arm = _run("UserPromptSubmit", dict(prompt, prompt="stop when this round finishes"), env)
    assert "STOP LATCH" in _context(arm, "UserPromptSubmit")
    assert _run("Stop", stop, env) is None
    # a fresh go-ahead lifts the latch and the gate speaks again
    assert _run("UserPromptSubmit", dict(prompt, prompt="ok, go ahead"), env) is None
    assert "DONE GATE" in _block_reason(_run("Stop", stop, env))
