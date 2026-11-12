"""Drift guard for the Claude hook registration in `.claude/settings.json`.

The hooks in scripts/hooks/ fail OPEN: a deleted, renamed or mis-registered
hook produces no error the agent can see, the rule just stops being enforced.
`.codex/hooks.json` is pinned by test_codex_harness_drift.py; this file pins
the Claude side:
  - every command in settings.json points at an existing scripts/hooks/*.py;
  - every Claude hook script is registered on its documented event, for every
    tool it must see, with the `--event` argument it needs;
  - a script in scripts/hooks/ that is neither registered nor listed as a
    library / git hook / Codex file is an error (a new hook was not wired).
The checker is a function so its own failure modes are tested on broken input.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK_DIR = REPO_ROOT / "scripts" / "hooks"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

SCRIPT_RE = re.compile(r"scripts/hooks/(\w+\.py)")
EVENT_ARG_RE = re.compile(r"--event\s+(\w+)")

# script -> event -> (tools the matcher must cover, required --event value or None).
# An empty tool set means the event has no matcher (UserPromptSubmit, Stop).
EXPECTED: dict[str, dict[str, tuple[frozenset[str], str | None]]] = {
    "ruff_on_edit.py": {
        "PostToolUse": (frozenset({"Edit", "Write", "Bash", "PowerShell"}), None),
        "PreToolUse": (frozenset({"Bash", "PowerShell"}), None),
    },
    "agent_prompt_guard.py": {"PreToolUse": (frozenset({"Agent", "Workflow", "Bash", "PowerShell"}), None)},
    "shell_edit_guard.py": {"PreToolUse": (frozenset({"Bash", "PowerShell"}), None)},
    "model_route_guard.py": {"PreToolUse": (frozenset({"Agent", "Workflow"}), None)},
    "quota_breaker.py": {"PreToolUse": (frozenset({"Agent", "Workflow"}), None)},
    "retry_cap_footer.py": {"PreToolUse": (frozenset({"Agent"}), None)},
    "stop_latch.py": {
        "PreToolUse": (frozenset({"Agent", "Workflow", "ScheduleWakeup", "Monitor"}), "tool"),
        "UserPromptSubmit": (frozenset(), "prompt"),
    },
    "cold_cache_gate.py": {"UserPromptSubmit": (frozenset(), None)},
    "pre_paste_gate.py": {
        "UserPromptSubmit": (frozenset(), "prompt"),
        "Stop": (frozenset(), "stop"),
    },
}

# Files in scripts/hooks/ that are not Claude hook entry points.
NOT_CLAUDE_HOOKS = frozenset({
    "_hookkit.py",  # shared helpers
    "_codexkit.py",  # Codex adapter
    "codex_hook.py",  # registered in .codex/hooks.json
    "shell_read_guard.py",  # library called by shell_edit_guard.py
    "install_git_hooks.py",  # installer
    "pre_commit_device_guard.py",  # git pre-commit
    "pre_push_checks.py",  # git pre-push
})


def registrations(settings: dict) -> list[tuple[str, frozenset[str], str, str | None]]:
    """(event, tools of the matcher, script name, --event value) for every hook command."""
    out: list[tuple[str, frozenset[str], str, str | None]] = []
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups:
            tools = frozenset(t for t in str(group.get("matcher") or "").split("|") if t)
            for hook in group.get("hooks") or []:
                command = str(hook.get("command") or "")
                script = SCRIPT_RE.search(command)
                arg = EVENT_ARG_RE.search(command)
                out.append((event, tools, script.group(1) if script else command, arg.group(1) if arg else None))
    return out


def registration_problems(settings: dict, hook_files: set[str]) -> list[str]:
    """Everything wrong with the registration; empty when it matches EXPECTED."""
    problems: list[str] = []
    seen: dict[tuple[str, str], tuple[set[str], set[str | None]]] = {}
    for event, tools, script, arg in registrations(settings):
        if script not in hook_files:
            problems.append(f"{event}: command points at a missing script: {script}")
            continue
        entry = seen.setdefault((script, event), (set(), set()))
        entry[0].update(tools)
        entry[1].add(arg)
        if script not in EXPECTED:
            problems.append(f"{event}: {script} is registered but not in EXPECTED (document it here)")
        elif event not in EXPECTED[script]:
            problems.append(f"{script} is registered on {event}, which EXPECTED does not list")
    for script, events in EXPECTED.items():
        for event, (tools, arg) in events.items():
            got = seen.get((script, event))
            if got is None:
                problems.append(f"{script} is not registered on {event}")
                continue
            missing = tools - got[0]
            if missing:
                problems.append(f"{script} on {event} does not match {sorted(missing)}")
            if arg is not None and arg not in got[1]:
                problems.append(f"{script} on {event} lacks `--event {arg}`")
    for name in sorted(hook_files - set(EXPECTED) - NOT_CLAUDE_HOOKS):
        problems.append(f"{name} is in scripts/hooks/ but neither registered nor listed in NOT_CLAUDE_HOOKS")
    return problems


def _hook_files() -> set[str]:
    return {p.name for p in HOOK_DIR.glob("*.py")}


def _settings() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def test_claude_settings_registers_every_hook_as_documented() -> None:
    assert registration_problems(_settings(), _hook_files()) == []


def test_every_hook_command_runs_from_the_project_dir() -> None:
    for event, groups in _settings()["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command", (event, hook)
                assert "${CLAUDE_PROJECT_DIR:-.}/scripts/hooks/" in hook["command"], (event, hook["command"])
                assert isinstance(hook.get("timeout"), int), (event, hook["command"])


def test_checker_reports_a_dropped_registration() -> None:
    settings = _settings()
    settings["hooks"]["PreToolUse"] = [
        g for g in settings["hooks"]["PreToolUse"] if "shell_edit_guard.py" not in json.dumps(g)
    ]
    problems = registration_problems(settings, _hook_files())
    assert any("shell_edit_guard.py is not registered on PreToolUse" in p for p in problems), problems


def test_checker_reports_a_narrowed_matcher_and_a_lost_event_argument() -> None:
    settings = _settings()
    for group in settings["hooks"]["PreToolUse"]:
        if "agent_prompt_guard.py" in json.dumps(group):
            group["matcher"] = "Agent|Workflow"
        for hook in group["hooks"]:
            hook["command"] = hook["command"].replace(" --event tool", "")
    problems = registration_problems(settings, _hook_files())
    assert any("agent_prompt_guard.py on PreToolUse does not match ['Bash', 'PowerShell']" in p for p in problems), problems
    assert any("stop_latch.py on PreToolUse lacks `--event tool`" in p for p in problems), problems


def test_checker_reports_a_misspelled_script_and_an_unwired_hook() -> None:
    settings = _settings()
    settings["hooks"]["Stop"][0]["hooks"][0]["command"] = 'python "${CLAUDE_PROJECT_DIR:-.}/scripts/hooks/pre_paste_gat.py" --event stop'
    problems = registration_problems(settings, _hook_files() | {"brand_new_guard.py"})
    assert any("missing script: pre_paste_gat.py" in p for p in problems), problems
    assert any("pre_paste_gate.py is not registered on Stop" in p for p in problems), problems
    assert any("brand_new_guard.py is in scripts/hooks/ but neither registered" in p for p in problems), problems
