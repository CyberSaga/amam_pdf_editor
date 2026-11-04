"""Tests for the Claude Code hooks in scripts/hooks/ (the owner-rule enforcers).

Each hook is a stdlib-only script that reads one JSON payload on stdin and
answers with JSON on stdout.  The classifiers are tested as functions; one
end-to-end subprocess per hook pins the stdin/stdout contract.  Covers:
  - agent_prompt_guard: bare pytest, system-python pytest, whole suite in one
    process, process kills in agent prompts; prose and run_suite.py pass.
  - stop_latch: the owner's stop phrases arm the latch, a later owner message
    lifts it, harness text (notifications, scheduled prompts) does neither.
  - cold_cache_gate: block only when the cache is cold, the context is big and
    the model is dear; compaction, slash commands, cheap models, the bypass
    prefix, subagents and a pending scheduler call all pass.
  - pre_paste_gate: a paste cue plus a dirty tracked tree blocks the stop once.
  - quota_breaker: deny above the 5 h / 7 d thresholds, fail open on stale data.
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

import _hookkit as kit  # noqa: E402
import agent_prompt_guard as guard  # noqa: E402
import cold_cache_gate as cold  # noqa: E402
import pre_paste_gate as paste  # noqa: E402
import quota_breaker as quota  # noqa: E402
import stop_latch as latch  # noqa: E402

VENV_PY = r".venv\Scripts\python.exe"


def _run_hook(script: str, payload: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *args],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + ".000Z"


def _assistant(ts: float, model: str, context: int, ttl: str = "1h", tool: dict | None = None) -> dict:
    content: list[dict] = [{"type": "text", "text": "ok"}]
    if tool:
        content = [{"type": "tool_use", "name": tool["name"], "input": tool.get("input", {})}]
    creation = {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}
    creation[f"ephemeral_{ttl}_input_tokens"] = 1000
    return {
        "type": "assistant",
        "timestamp": _iso(ts),
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": context - 1002,
                "cache_creation_input_tokens": 1000,
                "cache_creation": creation,
            },
        },
    }


def _user(ts: float, text: str, **extra: object) -> dict:
    rec = {"type": "user", "timestamp": _iso(ts), "message": {"role": "user", "content": text}}
    rec.update(extra)
    return rec


def _tool_result(ts: float) -> dict:
    return {
        "type": "user",
        "timestamp": _iso(ts),
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]},
    }


def _queued(ts: float, text: str) -> dict:
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(ts), "content": text}


def _boundary(ts: float) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "timestamp": _iso(ts)}


def _write_transcript(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- agent_prompt_guard


@pytest.mark.parametrize(
    "command, kinds",
    [
        ("pytest test_scripts/test_x.py", {"bare-pytest"}),
        ("cd x && pytest -q", {"bare-pytest", "whole-suite"}),
        ('bash -c "pytest test_scripts/test_x.py"', {"bare-pytest"}),
        ("python -m pytest test_scripts/test_x.py", {"system-python"}),
        ("py -3.11 -m pytest test_scripts/test_x.py", {"system-python"}),
        (VENV_PY + " -m pytest test_scripts/test_x.py -q --tb=short > out.txt", set()),
        (".venv/Scripts/python.exe -m pytest test_scripts/test_x.py::test_a", set()),
        ('"C:/work/repo/.venv/Scripts/python.exe" -m pytest test_scripts/test_a.py', set()),
        (VENV_PY + " -m pytest test_scripts/", {"whole-suite"}),
        (VENV_PY + " -m pytest test_scripts", {"whole-suite"}),
        (VENV_PY + " -m pytest", {"whole-suite"}),
        (VENV_PY + " -m pytest -q --tb=short > out.txt 2>&1", {"whole-suite"}),
        (VENV_PY + " -m pytest --collect-only -q test_scripts/test_a.py", set()),
        (VENV_PY + " scripts/run_suite.py --parallel-lanes", set()),
        ("grep -n pytest scripts/run_suite.py", set()),
        ('echo "pytest is slow"', set()),
        ("ruff check . && git status", set()),
        ('python -c "import pytest; pytest.main([])"', set()),
        ("cat > requirements-dev.txt <<'EOF'\npytest\nruff\nEOF\ngit status", set()),
        ("PY=.venv/Scripts/python.exe; $PY -m pytest test_scripts/test_a.py -q", set()),
        ('PY=python; "$PY" -m pytest test_scripts/test_a.py -q', {"system-python"}),
        ('"$PY" -m pytest test_scripts/test_a.py -q > out.txt 2>&1', set()),
        (VENV_PY + ' -m pytest -q --rootdir "C:\\w" "C:\\w\\test_scripts\\test_a.py"', set()),
        (VENV_PY + " -m pytest test_scripts/$f.py -q", set()),
        ("(pytest, scripts, ruff via the venv)", set()),
        ("echo pytest lock", set()),
        ('tasklist | grep -i -E "python|pytest" | head', set()),
        ('grep -n -i "two pytest\\|pytest lock" docs/PITFALLS.md', set()),
        ("awk '/assert|pytest\\./{print}' test_scripts/test_a.py", set()),
        ("PY=.venv/Scripts/python.exe; $PY -m pytest -k \"a or b\" -q", {"whole-suite"}),
        (VENV_PY + ' -m pytest "C:\\w\\test_scripts\\test_a.py" -q', set()),
        ("$x = @'\npytest test_scripts/test_a.py\n'@\nSet-Content -Path notes.txt -Value $x", set()),
    ],
)
def test_guard_classifies_shell_commands(command: str, kinds: set[str]) -> None:
    found = {v.kind for v in guard.violations("Bash", {"command": command})}
    assert found == kinds, command


@pytest.mark.parametrize(
    "command, kinds",
    [
        ("taskkill /F /PID 123", {"process-kill"}),
        ("Get-Process python | Stop-Process", {"process-kill"}),
        ("grep -iE 'taskkill|pkill' scripts/run_suite.py", set()),
        ('python -c "k32.TerminateProcess(h, 1)"', set()),
        ("git log --oneline | head", set()),
    ],
)
def test_guard_kill_rules_inside_subagent_shells(command: str, kinds: set[str]) -> None:
    found = {v.kind for v in guard.violations("PowerShell", {"command": command}, in_subagent=True)}
    assert found == kinds, command


def test_guard_treats_powershell_like_bash() -> None:
    found = {v.kind for v in guard.violations("PowerShell", {"command": "pytest -q"})}
    assert found == {"bare-pytest", "whole-suite"}


@pytest.mark.parametrize(
    "prompt, kinds",
    [
        ("Run `" + VENV_PY + " -m pytest test_scripts/test_a.py -q --tb=short > %TEMP%\\a.txt` and read the tail.", set()),
        ("Run `pytest test_scripts/test_a.py` then report.", {"bare-pytest"}),
        ("run the test file with pytest, then report", set()),
        ("Never use taskkill or pkill; one pytest at a time.", set()),
        ("Do not call Stop-Process on anything.", set()),
        ("If it hangs, taskkill /F /IM python.exe and retry.", {"process-kill"}),
        ("pkill -f pytest when done", {"process-kill"}),
        ("Finally run `" + VENV_PY + " -m pytest test_scripts/` for the whole suite.", {"whole-suite"}),
        ("Gate: `" + VENV_PY + " -m pytest <one file> -q --tb=short > log 2>&1`, one at a time.", set()),
        ("Use PY -m pytest <one file> [-k ...]; PY is the repo venv.", set()),
        ("The supervisor kills stalled trees (toolhelp snapshot, then TerminateProcess).", set()),
        ("Tests use pytest.raises and pytest.param; keep them.", set()),
        ("RULES: one pytest at a time, never `pytest test_scripts/`; use run_suite.py for the suite.", set()),
        ("always `" + VENV_PY + " -m pytest <one file> ...` (never bare `pytest`), one at a time", set()),
        ("Use `${PY} -m pytest <file> -q --tb=short`; PY is set in the lane.", set()),
        ("After the fixes run sequentially: ruff; pytest test_scripts/test_a.py; report the exit codes.", {"bare-pytest"}),
    ],
)
def test_guard_classifies_agent_prompts(prompt: str, kinds: set[str]) -> None:
    found = {v.kind for v in guard.violations("Agent", {"prompt": prompt, "description": "x"})}
    assert found == kinds, prompt


def test_guard_scans_workflow_scripts_and_args() -> None:
    script = "export const meta = {name:'x', description:'y'}\nawait agent(`Run `pytest test_scripts/test_a.py` and report`)\n"
    kinds = {v.kind for v in guard.violations("Workflow", {"script": script})}
    assert kinds == {"bare-pytest"}
    kinds = {v.kind for v in guard.violations("Workflow", {"script": "export const meta = {}", "args": {"cmd": "pytest -q"}})}
    assert kinds == {"bare-pytest", "whole-suite"}


def test_guard_kills_are_denied_only_inside_subagents_for_shell_tools() -> None:
    assert guard.violations("Bash", {"command": "taskkill /F /PID 123"}) == []
    kinds = {v.kind for v in guard.violations("Bash", {"command": "taskkill /F /PID 123"}, in_subagent=True)}
    assert kinds == {"process-kill"}
    kinds = {v.kind for v in guard.violations("PowerShell", {"command": "Stop-Process -Name python"}, in_subagent=True)}
    assert kinds == {"process-kill"}


def test_guard_end_to_end_denies_with_the_documented_json() -> None:
    result = _run_hook("agent_prompt_guard.py", {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "run_suite.py" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_end_to_end_allows_silently() -> None:
    result = _run_hook("agent_prompt_guard.py", {"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert result.returncode == 0 and result.stdout.strip() == b""


def test_guard_fails_open_on_garbage_payload() -> None:
    result = subprocess.run([sys.executable, str(HOOKS / "agent_prompt_guard.py")], input=b"not json", capture_output=True, timeout=60)
    assert result.returncode == 1 and result.stdout.strip() == b"" and b"NOT checked" in result.stderr


# --------------------------------------------------------------------------- stop_latch


@pytest.mark.parametrize(
    "text",
    [
        "Stop when this round finishes",
        "stop",
        "Stop.",
        "please stop here",
        "don't start another round",
        "no more rounds tonight",
        "請停",
        "先停下來",
        "這輪跑完就停",
        "暫停",
        "可以停了",
        "不要再跑下一輪",
    ],
)
def test_latch_recognises_stop_phrases(text: str) -> None:
    assert latch.is_stop_phrase(text), text


@pytest.mark.parametrize(
    "text",
    [
        "why did the stop hook fire?",
        "stop_hook_active is true in the payload",
        "the stop latch test",
        "不用跑測試",
        "繼續",
        "go ahead with round 9",
        "nonstop",
        "停掉卡住的測試。要怎麼避免再發？",
        "子 agent 一律把輸出寫進檔案。若確認是真的卡住，授權 10 分鐘後用 TaskStop 停掉它",
        "<!-- attach -->\n> The refuter had already started and I can’t stop it from here, so I’ll ignore it",
        "<pasted_content id=\"a1\">\n# Handoff\nStop means stop: gate, report, idle.\n</pasted_content>\nhere is the handoff, continue from step 3",
        "> stop when this round finishes\nwhat did you take this to mean?",
    ],
)
def test_latch_ignores_non_stop_text(text: str) -> None:
    assert not latch.is_stop_phrase(text), text


def test_latch_arms_on_the_last_owner_message_and_lifts_on_the_next(tmp_path: Path) -> None:
    t0 = 1_800_000_000.0
    records = [_user(t0, "run round 8"), _assistant(t0 + 10, "claude-opus-5-5", 50_000), _queued(t0 + 20, "Stop when this round finishes")]
    assert latch.armed_by(records) == "Stop when this round finishes"
    records.append(_tool_result(t0 + 30))
    records.append({"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(t0 + 40), "content": "<task-notification>done</task-notification>"})
    assert latch.armed_by(records) == "Stop when this round finishes"
    records.append(_user(t0 + 50, "ok, continue with round 9"))
    assert latch.armed_by(records) is None


def test_latch_ignores_scheduled_prompt_replays_and_slash_lines() -> None:
    t0 = 1_800_000_000.0
    records = [
        _user(t0, "stop"),
        _assistant(t0 + 1, "claude-opus-5-5", 50_000, tool={"name": "ScheduleWakeup", "input": {"delaySeconds": 600, "prompt": "/loop check the gate"}}),
        _user(t0 + 600, "/loop check the gate"),
        _user(t0 + 601, "/compact"),
    ]
    assert latch.armed_by(records) == "stop"


def test_latch_end_to_end_denies_agent_but_allows_a_stopping_wakeup(tmp_path: Path) -> None:
    t0 = time.time() - 100
    transcript = _write_transcript(tmp_path / "t.jsonl", [_user(t0, "Stop when this round finishes")])
    base = {"session_id": "s1", "transcript_path": str(transcript), "cwd": str(REPO_ROOT)}
    denied = _run_hook("stop_latch.py", {**base, "tool_name": "Agent", "tool_input": {"prompt": "x"}}, "--event", "tool")
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    allowed = _run_hook("stop_latch.py", {**base, "tool_name": "ScheduleWakeup", "tool_input": {"stop": True}}, "--event", "tool")
    assert allowed.stdout.strip() == b""
    sub = _run_hook("stop_latch.py", {**base, "agent_id": "a1", "tool_name": "Agent", "tool_input": {}}, "--event", "tool")
    assert sub.stdout.strip() == b""
    armed = _run_hook("stop_latch.py", {**base, "prompt": "stop"}, "--event", "prompt")
    assert "STOP LATCH" in json.loads(armed.stdout)["hookSpecificOutput"]["additionalContext"]


# --------------------------------------------------------------------------- cold_cache_gate

FABLE = "claude-fable-5-1"


def _cold_env(**over: str) -> dict[str, str]:
    env = {"CLAUDE_COLD_GATE_MODE": "block", "CLAUDE_COLD_GATE_MIN_CONTEXT": "60000"}
    env.update(over)
    return env


def test_cold_gate_blocks_a_cold_big_dear_context() -> None:
    now = 1_800_000_000.0
    records = [_assistant(now - 90 * 60, FABLE, 150_000)]
    verdict, reason = cold.decide("continue", {}, records, now, _cold_env())
    assert verdict == "block"
    assert "/compact" in reason and "sonnet" in reason


@pytest.mark.parametrize(
    "records_fn, prompt, payload, note",
    [
        (lambda now: [_assistant(now - 10 * 60, FABLE, 150_000)], "go", {}, "warm"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000), _boundary(now - 120)], "go", {}, "compacted"),
        (lambda now: [_assistant(now - 90 * 60, "claude-sonnet-5-5", 150_000)], "go", {}, "cheap model"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 30_000)], "go", {}, "small context"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000)], "/compact", {}, "slash"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000)], "!! quick question", {}, "bypass"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000)], "<task-notification>x</task-notification>", {}, "harness"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000)], "go", {"agent_id": "a"}, "subagent"),
        (lambda now: [_assistant(now - 90 * 60, FABLE, 150_000, tool={"name": "ScheduleWakeup", "input": {"delaySeconds": 3600, "prompt": "tick"}})], "tick", {}, "pending wakeup"),
        (lambda now: [_assistant(now - 5 * 3600, FABLE, 150_000, tool={"name": "CronCreate", "input": {"prompt": "Hourly overnight catch-up: read the log"}}), _assistant(now - 70 * 60, FABLE, 150_000)], "Hourly overnight catch-up: read the log", {}, "cron replay"),
        (lambda now: [], "go", {}, "new session"),
    ],
)
def test_cold_gate_allows(records_fn, prompt: str, payload: dict, note: str) -> None:
    now = 1_800_000_000.0
    verdict, _ = cold.decide(prompt, payload, records_fn(now), now, _cold_env())
    assert verdict == "allow", note


def test_cold_gate_uses_the_five_minute_ttl_when_the_cache_was_written_that_way() -> None:
    now = 1_800_000_000.0
    records = [_assistant(now - 9 * 60, FABLE, 150_000, ttl="5m")]
    assert cold.decide("go", {}, records, now, _cold_env())[0] == "block"
    records = [_assistant(now - 9 * 60, FABLE, 150_000, ttl="1h")]
    assert cold.decide("go", {}, records, now, _cold_env())[0] == "allow"


def test_cold_gate_modes() -> None:
    now = 1_800_000_000.0
    records = [_assistant(now - 90 * 60, FABLE, 150_000)]
    assert cold.decide("go", {}, records, now, _cold_env(CLAUDE_COLD_GATE_MODE="off"))[0] == "allow"
    assert cold.decide("go", {}, records, now, _cold_env(CLAUDE_COLD_GATE_MODE="context"))[0] == "context"


def test_cold_gate_end_to_end_blocks_with_decision_json(tmp_path: Path) -> None:
    now = time.time()
    transcript = _write_transcript(tmp_path / "t.jsonl", [_assistant(now - 90 * 60, FABLE, 150_000)])
    payload = {"session_id": "s", "transcript_path": str(transcript), "cwd": str(REPO_ROOT), "prompt": "continue"}
    env = {**os.environ, **_cold_env()}
    result = subprocess.run([sys.executable, str(HOOKS / "cold_cache_gate.py")], input=json.dumps(payload).encode(), capture_output=True, timeout=60, env=env)
    out = json.loads(result.stdout)
    assert out["decision"] == "block" and "/compact" in out["reason"]


# --------------------------------------------------------------------------- pre_paste_gate


@pytest.mark.parametrize(
    "text, cue",
    [
        ("Brief v16 is ready, please paste the pilot.", True),
        ("可以貼 v16 pilot 了", True),
        ("把 brief 貼給 Grok", True),
        ("Round 9 processed; nothing to paste yet.", False),
        ("All tests green, commit when ready.", False),
        ("pasted_content tags are handled by the harness", False),
    ],
)
def test_paste_cue(text: str, cue: bool) -> None:
    assert paste.has_paste_cue(text) is cue, text


def test_paste_already_warned_text_is_not_blocked_again() -> None:
    assert paste.already_warns("Tree is dirty (git diff HEAD): M foo.py -- commit before you paste.")
    assert paste.already_warns("工作樹有未 commit 的變更，先 commit 再貼")
    assert not paste.already_warns("please paste v16")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def test_paste_dirty_files_reads_tracked_changes_only(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    assert paste.dirty_files(repo) == []
    (repo / "untracked.txt").write_text("x", encoding="utf-8")
    assert paste.dirty_files(repo) == []
    (repo / "a.txt").write_text("2", encoding="utf-8")
    assert paste.dirty_files(repo) == ["M\ta.txt"]


def test_paste_gate_decisions(tmp_path: Path) -> None:
    dirty = ["D\tplans/true-text-i1.md"]
    assert paste.stop_decision("please paste v16", False, dirty) is not None
    assert paste.stop_decision("please paste v16", True, dirty) is None  # stop_hook_active
    assert paste.stop_decision("please paste v16", False, []) is None
    assert paste.stop_decision("all green", False, dirty) is None
    assert paste.stop_decision("tree is dirty: D plans/x.md, commit before you paste", False, dirty) is None


def test_paste_gate_end_to_end_blocks_once(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    (repo / "a.txt").write_text("2", encoding="utf-8")
    payload = {"session_id": "s", "cwd": str(repo), "stop_hook_active": False, "last_assistant_message": "Brief ready, please paste."}
    out = json.loads(_run_hook("pre_paste_gate.py", payload, "--event", "stop").stdout)
    assert out["decision"] == "block" and "a.txt" in out["reason"]
    payload["stop_hook_active"] = True
    assert _run_hook("pre_paste_gate.py", payload, "--event", "stop").stdout.strip() == b""
    prompt_payload = {"session_id": "s", "cwd": str(repo), "prompt": "我貼了 v16 pilot"}
    out = json.loads(_run_hook("pre_paste_gate.py", prompt_payload, "--event", "prompt").stdout)
    assert "a.txt" in out["hookSpecificOutput"]["additionalContext"]


# --------------------------------------------------------------------------- quota_breaker


def test_quota_breaker_denies_above_thresholds_and_fails_open_when_stale() -> None:
    now = 1_800_000_000.0
    fresh = {"ts": now - 60, "rate_limits": {"five_hour": {"used_percentage": 93, "resets_at": now + 3600}, "seven_day": {"used_percentage": 40}}}
    reason = quota.decide(fresh, now, {"5h": 90, "7d": 95, "spend": 95, "stale_minutes": 30})
    assert reason is not None and "5h" in reason and "93" in reason
    calm = {"ts": now - 60, "rate_limits": {"five_hour": {"used_percentage": 50}, "seven_day": {"used_percentage": 96}}}
    assert "7d" in (quota.decide(calm, now, {"5h": 90, "7d": 95, "spend": 95, "stale_minutes": 30}) or "")
    stale = {"ts": now - 3600, "rate_limits": {"five_hour": {"used_percentage": 99}}}
    assert quota.decide(stale, now, {"5h": 90, "7d": 95, "spend": 95, "stale_minutes": 30}) is None
    assert quota.decide(None, now, {"5h": 90, "7d": 95, "spend": 95, "stale_minutes": 30}) is None


def test_quota_breaker_reads_the_newest_state_file(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps({"ts": 10, "rate_limits": {}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"ts": 20, "rate_limits": {"five_hour": {"used_percentage": 1}}}), encoding="utf-8")
    (tmp_path / "c.json").write_text("garbage", encoding="utf-8")
    assert quota.newest_state(tmp_path)["ts"] == 20
    assert quota.newest_state(tmp_path / "missing") is None


# --------------------------------------------------------------------------- _hookkit


def test_hookkit_owner_messages_filters_harness_and_tool_results() -> None:
    t0 = 1_800_000_000.0
    records = [
        _user(t0, "first"),
        _tool_result(t0 + 1),
        _user(t0 + 2, "<local-command-stdout>x</local-command-stdout>", isMeta=True),
        _user(t0 + 3, "summary", isCompactSummary=True),
        _queued(t0 + 4, "<task-notification>done</task-notification>"),
        _queued(t0 + 5, "mid-turn note"),
    ]
    assert [t for _, t in kit.owner_messages(records)] == ["first", "mid-turn note"]


def test_hookkit_tail_records_skips_the_partial_first_line(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    rows = [json.dumps({"type": "user", "i": i, "pad": "x" * 100}) for i in range(50)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tail = kit.tail_records(path, max_bytes=800)
    assert tail and all(isinstance(r.get("i"), int) for r in tail)
    assert tail[-1]["i"] == 49 and len(tail) < 50
    assert kit.tail_records(tmp_path / "missing.jsonl") == []
