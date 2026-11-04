"""Tests for scripts/hooks/retry_cap_footer.py (PreToolUse Agent).

End to end through a subprocess: the hook appends the retry-cap footer to an
Agent call's prompt via `updatedInput` (every other key kept), is idempotent,
stays silent for other tools and empty prompts, and fails open on a payload
it cannot read.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "scripts" / "hooks" / "retry_cap_footer.py"


def _run(payload: object) -> subprocess.CompletedProcess:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, timeout=60)


def test_footer_appended_and_other_keys_kept() -> None:
    tool_input = {"prompt": "do the thing", "subagent_type": "general-purpose", "description": "d", "model": "sonnet"}
    res = _run({"tool_name": "Agent", "tool_input": tool_input})
    assert res.returncode == 0
    out = json.loads(res.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "allow"
    new = out["updatedInput"]
    assert new["prompt"].startswith("do the thing\n\nRetry cap:")
    assert "three times in a row, stop" in new["prompt"]
    assert {k: v for k, v in new.items() if k != "prompt"} == {k: v for k, v in tool_input.items() if k != "prompt"}


def test_idempotent_when_footer_present() -> None:
    res = _run({"tool_name": "Agent", "tool_input": {"prompt": "x\n\nRetry cap: already"}})
    assert res.returncode == 0 and res.stdout == b""


def test_other_tool_silent() -> None:
    res = _run({"tool_name": "Bash", "tool_input": {"prompt": "x"}})
    assert res.returncode == 0 and res.stdout == b""


def test_empty_prompt_silent() -> None:
    for tool_input in ({"prompt": ""}, {"prompt": "   "}, {}):
        res = _run({"tool_name": "Agent", "tool_input": tool_input})
        assert res.returncode == 0 and res.stdout == b""


def test_garbage_payload_fails_open() -> None:
    res = _run(b"not json")
    assert res.returncode == 1
    assert b"NOT checked" in res.stderr and res.stdout == b""


def test_missing_tool_input_fails_open() -> None:
    res = _run({"tool_name": "Agent"})
    assert res.returncode == 1 and b"NOT checked" in res.stderr
