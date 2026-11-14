from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "codex_hook.py"


def run_hook(event: str, payload: dict, state_dir: Path | None = None) -> dict:
    env = os.environ.copy()
    if state_dir is not None:
        env["PDF_EDITOR_CODEX_STATE_DIR"] = str(state_dir)
        env["CLAUDE_RUFF_STAMP_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(HOOK), event], input=json.dumps(payload),
        text=True, capture_output=True, cwd=ROOT, check=True, env=env,
    )
    return json.loads(result.stdout) if result.stdout else {}


def test_pre_tool_denies_bare_pytest_and_allows_project_interpreter() -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "pytest test_scripts/test_x.py"}}
    assert run_hook("PreToolUse", payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    payload["tool_input"]["command"] = ".venv/Scripts/python.exe -m pytest test_scripts/test_x.py"
    assert not run_hook("PreToolUse", payload)


def test_post_patch_checks_python_files() -> None:
    file = ROOT / "test_scripts" / "_codex_hook_lint_probe.py"
    try:
        file.write_text("import missing_name\n", encoding="utf-8")
        patch = f"*** Begin Patch\n*** Add File: {file}\n+import missing_name\n*** End Patch"
        response = run_hook("PostToolUse", {"tool_name": "apply_patch", "tool_input": {"command": patch}})
        assert response["decision"] == "block"
    finally:
        file.unlink(missing_ok=True)


def test_stop_respects_active_flag() -> None:
    assert not run_hook("Stop", {"stop_hook_active": True, "last_assistant_message": "paste"})


def test_stop_latch_ignores_first_prompt_and_resets(tmp_path: Path) -> None:
    session = {"session_id": "test-session"}
    spawn = {**session, "tool_name": "collaborationspawn_agent", "tool_input": {}}
    run_hook("UserPromptSubmit", {**session, "prompt": "stop after this round"}, tmp_path)
    assert not run_hook("PreToolUse", spawn, tmp_path)
    run_hook("UserPromptSubmit", {**session, "prompt": "stop after this round"}, tmp_path)
    assert run_hook("PreToolUse", spawn, tmp_path)["hookSpecificOutput"]["permissionDecision"] == "deny"
    run_hook("UserPromptSubmit", {**session, "prompt": "continue"}, tmp_path)
    assert not run_hook("PreToolUse", spawn, tmp_path)


def test_stop_latch_denies_canonical_codex_spawn_tool(tmp_path: Path) -> None:
    session = {"session_id": "canonical-spawn"}
    run_hook("UserPromptSubmit", {**session, "prompt": "begin"}, tmp_path)
    run_hook("UserPromptSubmit", {**session, "prompt": "stop after this round"}, tmp_path)
    spawn = {**session, "tool_name": "spawn_agent", "tool_input": {}}
    assert run_hook("PreToolUse", spawn, tmp_path)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_shell_policy_blocks_tracked_edits_and_kills() -> None:
    payload = {"tool_name": "Bash", "cwd": str(ROOT), "tool_input": {"command": "Set-Content TODOS.md test"}}
    assert run_hook("PreToolUse", payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    payload["tool_input"]["command"] = "taskkill /PID 9999"
    assert run_hook("PreToolUse", payload)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_shell_post_checks_changed_python_files(tmp_path: Path) -> None:
    file = ROOT / "test_scripts" / "_codex_hook_shell_probe.py"
    payload = {"session_id": "shell-test", "tool_use_id": "one", "tool_name": "Bash",
               "tool_input": {"command": "python edit_script.py"}, "cwd": str(ROOT)}
    try:
        assert not run_hook("PreToolUse", payload, tmp_path)
        file.write_text("import missing_name\n", encoding="utf-8")
        assert run_hook("PostToolUse", payload, tmp_path)["decision"] == "block"
    finally:
        file.unlink(missing_ok=True)


def test_malformed_input_does_not_block() -> None:
    result = subprocess.run([sys.executable, str(HOOK), "PreToolUse"], input="{", text=True, capture_output=True)
    assert result.returncode == 0
    assert result.stdout == ""


def test_prompt_warns_about_pasting_with_dirty_tracked_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "hooks"))
    import codex_hook

    monkeypatch.setattr(codex_hook.pre_paste_gate, "dirty_files", lambda cwd: ["M\tTODOS.md"])
    monkeypatch.setenv("PDF_EDITOR_CODEX_STATE_DIR", str(tmp_path))
    result = codex_hook._prompt({"session_id": "paste-test", "prompt": "我準備貼上", "cwd": str(ROOT)})
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "TODOS.md" in context
    assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_ruff_format_check_flag_must_apply_to_format_command() -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "ruff format .; echo --check"}}
    assert run_hook("PreToolUse", payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    payload["tool_input"]["command"] = "ruff format --check ."
    assert not run_hook("PreToolUse", payload)
    payload["tool_input"]["command"] = "echo 'ruff format .'"
    assert not run_hook("PreToolUse", payload)


def test_prompt_without_paste_cue_has_no_paste_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "hooks"))
    import codex_hook

    monkeypatch.setattr(codex_hook.pre_paste_gate, "dirty_files", lambda cwd: ["M\tTODOS.md"])
    monkeypatch.setenv("PDF_EDITOR_CODEX_STATE_DIR", str(tmp_path))
    assert not codex_hook._prompt({"session_id": "normal-test", "prompt": "繼續工作"})


def test_subagent_start_injects_retry_cap() -> None:
    result = run_hook("SubagentStart", {"agent_type": "worker"})
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "SubagentStart"
    assert "three times" in output["additionalContext"]
