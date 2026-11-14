"""Tests for scripts/hooks/fable_dispatch_guard.py.

The owner rule: Fable never runs inside a sub-agent.  An agent whose definition
says ``model: inherit`` (the claude-security researchers, verifiers and patch
agents; forks; built-ins without a model) runs on the main session's model, so
a dispatch from a Fable session silently fans Fable out.  The hook denies:
  - any Agent call or workflow script that names Fable explicitly;
  - from a Fable main session: an Agent call that would inherit, a named
    workflow (its agents cannot be checked), and a script with an agent()
    call that names no model.
It allows everything from a non-Fable session (except an explicit Fable),
agents with a pinned non-Fable model, subagent payloads, and the override.
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

import fable_dispatch_guard as fdg  # noqa: E402

FABLE = "claude-fable-5-1"
OPUS = "claude-opus-5-5"


def _agent_dir(tmp_path: Path) -> list[Path]:
    project = tmp_path / "project_agents"
    project.mkdir(exist_ok=True)
    (project / "deep-reasoner.md").write_text("---\nname: deep-reasoner\nmodel: opus\n---\nbody\n", encoding="utf-8")
    (project / "inheritor.md").write_text("---\nname: inheritor\nmodel: inherit\n---\n", encoding="utf-8")
    (project / "nomodel.md").write_text("---\nname: nomodel\n---\n", encoding="utf-8")
    return [project]


def _plugin_cache(tmp_path: Path) -> Path:
    agents = tmp_path / "cache" / "market" / "claude-security" / "0.11.0-abc" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "scan-researcher.md").write_text("---\nname: scan-researcher\nmodel: inherit\neffort: xhigh\n---\n", encoding="utf-8")
    (agents / "explore.md").write_text("---\nname: explore\nmodel: sonnet\n---\n", encoding="utf-8")
    return tmp_path / "cache"


def _ctx(tmp_path: Path) -> dict:
    return {"agent_dirs": _agent_dir(tmp_path), "plugin_cache": _plugin_cache(tmp_path)}


# --------------------------------------------------------------------------- agent model resolution


@pytest.mark.parametrize(
    ("subagent_type", "expected"),
    [
        ("deep-reasoner", "opus"),
        ("inheritor", "inherit"),
        ("nomodel", "inherit"),
        ("claude-security:scan-researcher", "inherit"),
        ("claude-security:explore", "sonnet"),
        ("fork", "inherit"),
        ("unknown-agent", "inherit"),
        (None, "inherit"),
    ],
)
def test_agent_definition_model(tmp_path: Path, subagent_type: str | None, expected: str) -> None:
    ctx = _ctx(tmp_path)
    assert fdg.agent_definition_model(subagent_type, ctx["agent_dirs"], ctx["plugin_cache"]) == expected


# --------------------------------------------------------------------------- Agent decisions


def test_fable_main_denies_an_inheriting_agent(tmp_path: Path) -> None:
    reason = fdg.decide_agent({"subagent_type": "claude-security:scan-researcher", "prompt": "x"}, FABLE, **_ctx(tmp_path))
    assert reason and "Fable" in reason and "model" in reason


def test_fable_main_denies_a_fork_even_with_a_model(tmp_path: Path) -> None:
    assert fdg.decide_agent({"subagent_type": "fork", "model": "sonnet"}, FABLE, **_ctx(tmp_path))


@pytest.mark.parametrize(
    "tool_input",
    [
        {"subagent_type": "deep-reasoner"},
        {"subagent_type": "claude-security:explore"},
        {"subagent_type": "claude-security:scan-researcher", "model": "opus"},
        {"model": "haiku"},
    ],
)
def test_fable_main_allows_pinned_non_fable_agents(tmp_path: Path, tool_input: dict) -> None:
    assert fdg.decide_agent(tool_input, FABLE, **_ctx(tmp_path)) is None


def test_explicit_fable_agent_is_denied_from_any_session(tmp_path: Path) -> None:
    assert fdg.decide_agent({"subagent_type": "deep-reasoner", "model": "fable"}, OPUS, **_ctx(tmp_path))
    assert fdg.decide_agent({"model": "fable"}, FABLE, **_ctx(tmp_path))


def test_non_fable_main_allows_inheriting_agents(tmp_path: Path) -> None:
    assert fdg.decide_agent({"subagent_type": "claude-security:scan-researcher"}, OPUS, **_ctx(tmp_path)) is None
    assert fdg.decide_agent({"subagent_type": "fork"}, OPUS, **_ctx(tmp_path)) is None


def test_unknown_main_model_is_not_treated_as_fable(tmp_path: Path) -> None:
    assert fdg.decide_agent({"subagent_type": "fork"}, "", **_ctx(tmp_path)) is None


# --------------------------------------------------------------------------- Workflow decisions


PINNED = "export const meta = {name: 'x'}\nawait agent('a', {model: 'sonnet', effort: 'low'})\nawait agent(`b`, {label: 'b', model: \"opus\"})\n"
UNPINNED = "export const meta = {name: 'x'}\nawait agent('a', {model: 'sonnet'})\nawait agent('b', {label: 'b'})\n"
EXPLICIT_FABLE = "await agent('a', {model: 'fable', effort: 'low'})\n"


def test_workflow_unpinned_agent_from_fable_is_denied() -> None:
    reason = fdg.decide_workflow({"script": UNPINNED}, FABLE)
    assert reason and "1 of 2" in reason


def test_workflow_all_pinned_from_fable_is_allowed() -> None:
    assert fdg.decide_workflow({"script": PINNED}, FABLE) is None


def test_workflow_named_from_fable_is_denied_but_allowed_from_opus() -> None:
    assert fdg.decide_workflow({"name": "claude-security:scan", "args": {}}, FABLE)
    assert fdg.decide_workflow({"name": "claude-security:scan", "args": {}}, OPUS) is None


def test_workflow_explicit_fable_is_denied_from_any_session() -> None:
    assert fdg.decide_workflow({"script": EXPLICIT_FABLE}, OPUS)


def test_workflow_unpinned_from_opus_is_allowed() -> None:
    assert fdg.decide_workflow({"script": UNPINNED}, OPUS) is None


def test_workflow_agent_type_resolves_through_the_definition(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    pinned = "await agent(p, { label: 'r', agentType: 'deep-reasoner', effort: 'high' })\n"
    inherits = "await agent(p, { label: 'i', agentType: 'claude-security:scan-researcher' })\n"
    assert fdg.decide_workflow({"script": pinned}, FABLE, ctx["agent_dirs"], ctx["plugin_cache"]) is None
    assert fdg.decide_workflow({"script": inherits}, FABLE, ctx["agent_dirs"], ctx["plugin_cache"])


def test_workflow_prose_agent_parens_in_strings_and_comments_are_not_calls() -> None:
    script = (
        "// agent(old, {label: 'x'}) left in a comment\n"
        "const P = `the other agent (Grok) wrote it; call agent(x) yourself`\n"
        "await agent(P, { label: 'a', model: 'sonnet', effort: 'low' })\n"
    )
    assert fdg._call_spans(script) == ["P, { label: 'a', model: 'sonnet', effort: 'low' }"]
    assert fdg.decide_workflow({"script": script}, FABLE) is None


def test_workflow_const_or_spread_options_count_as_pinned_when_the_script_names_a_model() -> None:
    const = "const READER = { model: 'haiku', effort: 'low' }\nawait agent(p, READER)\nawait agent(q, {...READER, label: 'q'})\n"
    assert fdg.decide_workflow({"script": const}, FABLE) is None
    no_model = "const OPTS = { effort: 'low' }\nawait agent(p, OPTS)\n"
    assert fdg.decide_workflow({"script": no_model}, FABLE)


def test_workflow_script_path_is_read(tmp_path: Path) -> None:
    path = tmp_path / "wf.js"
    path.write_text(UNPINNED, encoding="utf-8")
    assert fdg.decide_workflow({"scriptPath": str(path)}, FABLE)
    path.write_text(PINNED, encoding="utf-8")
    assert fdg.decide_workflow({"scriptPath": str(path)}, FABLE) is None


def test_workflow_unreadable_script_path_from_fable_is_denied(tmp_path: Path) -> None:
    assert fdg.decide_workflow({"scriptPath": str(tmp_path / "missing.js")}, FABLE)


# --------------------------------------------------------------------------- override + end to end


def test_override_phrase_in_the_latest_owner_message() -> None:
    assert fdg.overridden({}, "please go, fable-dispatch-ok")
    assert fdg.overridden({"CLAUDE_FABLE_DISPATCH_OK": "1"}, "")
    assert not fdg.overridden({}, "use fable for this")


def _transcript(tmp_path: Path, model: str, owner_text: str = "scan it") -> Path:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    records = [
        {"type": "user", "timestamp": ts, "message": {"role": "user", "content": owner_text}},
        {"type": "assistant", "timestamp": ts, "message": {"model": model, "content": [{"type": "text", "text": "ok"}], "usage": {}}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _run(payload: dict | bytes) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_FABLE_DISPATCH_OK"}
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run(
        [sys.executable, str(HOOKS / "fable_dispatch_guard.py")],
        input=data,
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
        env=env,
    )


def test_end_to_end_denies_a_fork_from_a_fable_session(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "fork", "prompt": "x"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
    proc = _run(payload)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_end_to_end_allows_with_the_override_and_from_opus(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "fork"}, "transcript_path": str(_transcript(tmp_path, FABLE, "go fable-dispatch-ok"))}
    assert _run(payload).stdout.strip() == b""
    payload["transcript_path"] = str(_transcript(tmp_path, OPUS))
    assert _run(payload).stdout.strip() == b""


def test_end_to_end_skips_subagent_payloads_and_fails_open_on_garbage(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "agent_id": "a1", "tool_input": {"subagent_type": "fork"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
    assert _run(payload).stdout.strip() == b""
    proc = _run(b"not json")
    assert proc.returncode == 1 and proc.stdout.strip() == b""
