"""Tests for the Fable half of scripts/hooks/model_route_guard.py (formerly fable_dispatch_guard.py).

The owner rule (2026-11-14): at most one Fable subagent at a time, never inside a workflow
agent().  Without a claim callable every Fable-bound dispatch is denied (the pre-cap behaviour
the first sections pin); the slot sections at the end cover the cap.  An agent whose definition
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
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS))

import model_route_guard as fdg  # noqa: E402

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


def test_override_is_the_env_var_only() -> None:
    assert fdg.overridden({"CLAUDE_FABLE_DISPATCH_OK": "1"})
    assert not fdg.overridden({})
    assert not fdg.overridden({"CLAUDE_FABLE_DISPATCH_OK": "0"})
    assert not hasattr(fdg, "OVERRIDE_PHRASE")  # the owner-message phrase was removed (2026-11-14)


def _transcript(tmp_path: Path, model: str, owner_text: str = "scan it") -> Path:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    records = [
        {"type": "user", "timestamp": ts, "message": {"role": "user", "content": owner_text}},
        {"type": "assistant", "timestamp": ts, "message": {"model": model, "content": [{"type": "text", "text": "ok"}], "usage": {}}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _run(payload: dict | bytes, *args: str, slots: Path | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_FABLE_DISPATCH_OK"}
    env["CLAUDE_FABLE_SLOT_DIR"] = str(slots or Path(tempfile.mkdtemp(prefix="fable-slot-")))
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run(
        [sys.executable, str(HOOKS / "model_route_guard.py"), *args],
        input=data,
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
        env=env,
    )


def test_end_to_end_a_fork_from_a_fable_session_takes_the_one_slot_then_is_denied(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "session_id": "fk", "tool_input": {"subagent_type": "fork", "prompt": "x"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
    slots = tmp_path / "slots"
    first = _run(payload, slots=slots)
    assert first.returncode == 0 and first.stdout.strip() == b""
    second = _run(payload, slots=slots)
    assert second.returncode == 0
    assert json.loads(second.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_end_to_end_the_old_owner_phrase_no_longer_overrides_and_opus_is_allowed(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "session_id": "ph", "tool_input": {"subagent_type": "fork"}, "transcript_path": str(_transcript(tmp_path, FABLE, "go fable-dispatch-ok"))}
    slots = tmp_path / "slots"
    assert _run(payload, slots=slots).stdout.strip() == b""  # first fork takes the slot
    assert "FABLE CAP" in json.loads(_run(payload, slots=slots).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    payload["transcript_path"] = str(_transcript(tmp_path, OPUS))
    assert _run(payload).stdout.strip() == b""


def test_end_to_end_skips_subagent_payloads_and_fails_open_on_garbage(tmp_path: Path) -> None:
    payload = {"tool_name": "Agent", "agent_id": "a1", "tool_input": {"subagent_type": "fork"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
    assert _run(payload).stdout.strip() == b""
    proc = _run(b"not json")
    assert proc.returncode == 1 and proc.stdout.strip() == b""


# --------------------------------------------------------------------------- the one-Fable-subagent cap


def _claimer(tmp_path: Path, sid: str = "s1", now: float = 1000.0):
    return lambda agent_type: fdg.claim_fable_slot(tmp_path / "slots", sid, agent_type, now=now)


def test_first_fable_agent_claims_the_slot_and_the_second_is_denied(tmp_path: Path) -> None:
    claim = _claimer(tmp_path)
    assert fdg.decide_agent({"model": "fable", "subagent_type": "deep-reasoner"}, OPUS, **_ctx(tmp_path), claim=claim) is None
    reason = fdg.decide_agent({"model": "claude-fable-5-2"}, OPUS, **_ctx(tmp_path), claim=claim)
    assert reason and "FABLE CAP" in reason and "deep-reasoner" in reason


def test_cap_applies_to_inheritance_from_a_fable_main(tmp_path: Path) -> None:
    claim = _claimer(tmp_path)
    assert fdg.decide_agent({"subagent_type": "fork"}, FABLE, **_ctx(tmp_path), claim=claim) is None
    assert "FABLE CAP" in fdg.decide_agent({"subagent_type": "claude-security:scan-researcher"}, FABLE, **_ctx(tmp_path), claim=claim)


def test_non_fable_agents_never_touch_the_slot(tmp_path: Path) -> None:
    claim = _claimer(tmp_path)
    for tool_input in ({"model": "sonnet"}, {"subagent_type": "deep-reasoner"}):
        assert fdg.decide_agent(tool_input, FABLE, **_ctx(tmp_path), claim=claim) is None
    assert fdg.decide_agent({"subagent_type": "fork"}, OPUS, **_ctx(tmp_path), claim=claim) is None  # fork of a non-Fable main
    assert not (tmp_path / "slots").exists()


def test_slot_is_per_session_and_expires_after_the_ttl(tmp_path: Path) -> None:
    slots = tmp_path / "slots"
    assert fdg.claim_fable_slot(slots, "a", "x", now=0, ttl=100) is None
    assert fdg.claim_fable_slot(slots, "b", "y", now=1, ttl=100) is None  # another session
    assert fdg.claim_fable_slot(slots, "a", "z", now=99, ttl=100)  # still busy
    assert fdg.claim_fable_slot(slots, "a", "z", now=100, ttl=100) is None  # stale claim expired


def test_release_frees_the_slot_only_for_the_claimed_type_or_a_fable_run(tmp_path: Path) -> None:
    slots = tmp_path / "slots"
    assert fdg.claim_fable_slot(slots, "s", "deep-reasoner", now=0) is None
    assert not fdg.release_fable_slot(slots, "s", "Explore", OPUS, now=1)  # unrelated subagent stopped
    assert fdg.claim_fable_slot(slots, "s", "other", now=2)
    assert fdg.release_fable_slot(slots, "s", "deep-reasoner", "", now=3)  # model unreadable: the type decides
    assert fdg.claim_fable_slot(slots, "s", "other", now=4) is None
    assert fdg.release_fable_slot(slots, "s", "whatever", FABLE, now=5)  # it ran on Fable
    assert not fdg.release_fable_slot(slots, "s", "whatever", FABLE, now=6)  # nothing left to free


def test_workflow_fable_stays_denied_regardless_of_the_slot(tmp_path: Path) -> None:
    assert fdg.decide("Workflow", {"script": EXPLICIT_FABLE}, tmp_path, OPUS, _claimer(tmp_path))


def test_end_to_end_cap_and_release_through_the_hook_process(tmp_path: Path) -> None:
    slots = tmp_path / "slots"
    spawn = {"tool_name": "Agent", "session_id": "e2e", "agent_id": "sub", "tool_input": {"model": "fable", "subagent_type": "deep-reasoner"}}
    assert _run(spawn, slots=slots).stdout.strip() == b""  # first one allowed (a subagent payload: no transcript needed)
    denied = json.loads(_run(spawn, slots=slots).stdout)
    assert "FABLE CAP" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    stop = {"hook_event_name": "SubagentStop", "session_id": "e2e", "agent_type": "deep-reasoner"}
    assert _run(stop, "--event", "release", slots=slots).stdout.strip() == b""
    assert _run(spawn, slots=slots).stdout.strip() == b""  # slot is free again


# --------------------------------------------------------------------------- advisor-review holes (2026-11-14)


def test_two_claims_that_both_read_a_free_slot_cannot_both_win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slots = tmp_path / "slots"
    monkeypatch.setattr(fdg, "_read_slot", lambda *a, **k: None)  # both callers saw "free" before either wrote
    assert fdg.claim_fable_slot(slots, "r", "a", now=0) is None
    assert "FABLE CAP" in (fdg.claim_fable_slot(slots, "r", "b", now=0) or "")


def test_a_non_fable_agent_of_the_same_type_does_not_free_the_slot(tmp_path: Path) -> None:
    slots = tmp_path / "slots"
    assert fdg.claim_fable_slot(slots, "s", "general-purpose", now=0) is None
    assert not fdg.release_fable_slot(slots, "s", "general-purpose", OPUS, now=1)  # model known and not Fable
    assert fdg.release_fable_slot(slots, "s", "general-purpose", "", now=2)  # model unreadable: type decides


def test_env_override_lifts_workflow_inheritance_checks_but_not_the_agent_cap(tmp_path: Path) -> None:
    env_key = "CLAUDE_FABLE_DISPATCH_OK"
    wf = {"tool_name": "Workflow", "tool_input": {"name": "claude-security:scan"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
    slots = tmp_path / "slots"
    assert json.loads(_run(wf, slots=slots).stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    old = os.environ.get(env_key)
    os.environ[env_key] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(HOOKS / "model_route_guard.py")],
            input=json.dumps(wf).encode("utf-8"), capture_output=True, timeout=60, cwd=str(REPO_ROOT),
            env={**os.environ, "CLAUDE_FABLE_SLOT_DIR": str(slots)},
        )
        assert proc.stdout.strip() == b""  # the workflow check is lifted
        fork = {"tool_name": "Agent", "session_id": "ev", "tool_input": {"subagent_type": "fork"}, "transcript_path": str(_transcript(tmp_path, FABLE))}
        run = lambda: subprocess.run(  # noqa: E731
            [sys.executable, str(HOOKS / "model_route_guard.py")],
            input=json.dumps(fork).encode("utf-8"), capture_output=True, timeout=60, cwd=str(REPO_ROOT),
            env={**os.environ, "CLAUDE_FABLE_SLOT_DIR": str(slots)},
        )
        assert run().stdout.strip() == b""
        assert "FABLE CAP" in json.loads(run().stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    finally:
        if old is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = old
