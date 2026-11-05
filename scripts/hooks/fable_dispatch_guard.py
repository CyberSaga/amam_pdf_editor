#!/usr/bin/env python3
"""PreToolUse hook (Agent|Workflow): Fable never runs inside a sub-agent.

2026-11-04: a claude-security high scan (232 agents, ~21.6 M subagent tokens)
ran entirely on Fable.  The plugin's researchers, verifiers and patch agents
are ``model: inherit`` and its scan workflow names no model, so every one of
them ran on whatever the main session was at launch.  The main session's model
is the only lever, so the check sits at dispatch time.

Deny:
  * any Agent call with ``model: fable`` or a workflow script that names
    ``model: 'fable'`` -- from any session (CLAUDE.md: Fable never in agents);
  * when the main session is Fable (newest assistant record in the transcript):
      - an Agent call that would inherit: ``subagent_type: fork`` (forks always
        inherit), or no ``model`` argument and a definition whose model is
        ``inherit``, missing, or not found (built-ins count as inherit);
      - a named workflow (``name``): its agent() calls cannot be checked here;
      - a script (``script`` / ``scriptPath``) with an agent() call (in code,
        not prose inside a string) whose options pin no model: no ``model:``,
        no ``agentType`` with a pinned definition, and no const/spread options
        while the script names a model elsewhere; or an unreadable ``scriptPath``.
Allow: subagent payloads (a sub-agent's own dispatches inherit the sub-agent's
model, not Fable), an unknown main model, the env var
CLAUDE_FABLE_DISPATCH_OK=1, or the owner's latest message containing
``fable-dispatch-ok``.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import _hookkit as kit

HOOK = "fable_dispatch_guard"
OVERRIDE_PHRASE = "fable-dispatch-ok"
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
AGENT_DIRS = [PROJECT_DIR / ".claude" / "agents", Path.home() / ".claude" / "agents"]
PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache"

_AGENT_CALL = re.compile(r"\bagent\s*\(")
_MODEL_KEY = re.compile(r"\bmodel\s*:")
_FABLE_MODEL = re.compile(r"""\bmodel\s*:\s*['"`][^'"`]*fable""", re.IGNORECASE)


def is_fable(model: str | None) -> bool:
    return bool(model) and "fable" in str(model).lower()


def _frontmatter_model(path: Path) -> str | None:
    """The ``model:`` value of an agent definition's frontmatter; None when absent/unreadable."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "model":
            return value.strip().strip("'\"") or None
    return None


def _definition_path(subagent_type: str, agent_dirs: list[Path], plugin_cache: Path) -> Path | None:
    if ":" in subagent_type:
        plugin, _, name = subagent_type.partition(":")
        try:
            found = list(plugin_cache.glob(f"*/{plugin}/*/agents/{name}.md"))
        except (OSError, ValueError):
            return None
        if not found:
            return None
        return max(found, key=lambda p: p.stat().st_mtime)
    for folder in agent_dirs:
        candidate = folder / f"{subagent_type}.md"
        if candidate.is_file():
            return candidate
    return None


def agent_definition_model(subagent_type: str | None, agent_dirs: list[Path], plugin_cache: Path) -> str:
    """The model an agent type's definition pins, or ``inherit`` (also for fork, built-ins, unknown)."""
    if not subagent_type or subagent_type == "fork":
        return "inherit"
    path = _definition_path(subagent_type, agent_dirs, plugin_cache)
    model = _frontmatter_model(path) if path else None
    return model.lower() if model else "inherit"


def decide_agent(tool_input: dict, main_model: str, agent_dirs: list[Path], plugin_cache: Path) -> str | None:
    subagent_type = tool_input.get("subagent_type")
    explicit = tool_input.get("model")
    if is_fable(explicit) and subagent_type != "fork":
        return (
            f"FABLE DISPATCH GUARD ({HOOK}): this Agent call asks for model 'fable'. Owner rule: Fable "
            "never runs inside a sub-agent (readers Haiku/Sonnet, judges Opus). Pick one of those."
        )
    if not is_fable(main_model):
        return None
    if subagent_type == "fork":
        return (
            f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and a fork always "
            "inherits it (a model override is ignored). Use a fresh agent with model 'opus'/'sonnet'/"
            f"'haiku', or have the owner switch the session model. Owner override: '{OVERRIDE_PHRASE}'."
        )
    if explicit:
        return None
    pinned = agent_definition_model(subagent_type, agent_dirs, plugin_cache)
    if pinned != "inherit" and not is_fable(pinned):
        return None
    return (
        f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and agent type "
        f"'{subagent_type or 'general-purpose'}' would run on it (its definition model is '{pinned}'). "
        "Pass model 'opus' (judges) or 'sonnet'/'haiku' (readers) on this call, or have the owner switch "
        f"the session model. Owner override: '{OVERRIDE_PHRASE}'."
    )


def _code_call_starts(script: str) -> list[int]:
    """Index just past the '(' of every agent( that sits in code, not inside a string or comment."""
    starts: list[int] = []
    quote, i, n = "", 0, len(script)
    while i < n:
        ch = script[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
        elif script.startswith("//", i):
            end = script.find("\n", i)
            i = n if end < 0 else end
            continue
        elif script.startswith("/*", i):
            end = script.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            match = _AGENT_CALL.match(script, i)
            if match and (i == 0 or not (script[i - 1].isalnum() or script[i - 1] == "_")):
                starts.append(match.end())
                i = match.end()
                continue
        i += 1
    return starts


_AGENT_TYPE = re.compile(r"""\bagentType\s*:\s*['"`]([^'"`]+)['"`]""")


def _call_pinned(span: str, script: str, agent_dirs: list[Path], plugin_cache: Path) -> bool:
    """True when one agent() call's options pin a non-Fable model."""
    if _MODEL_KEY.search(span):
        return True
    typed = _AGENT_TYPE.search(span)
    if typed:
        pinned = agent_definition_model(typed.group(1), agent_dirs, plugin_cache)
        return pinned != "inherit" and not is_fable(pinned)
    # options passed as a const or a spread (`agent(p, READER)`, `{...SPEC, label}`):
    # pinned when the script names a model somewhere for them to carry.
    tail = span.rstrip().rstrip(",").rsplit(",", 1)[-1].strip() if "," in span else ""
    via_const = "..." in span or bool(re.fullmatch(r"[A-Za-z_$][\w$.]*", tail))
    return via_const and bool(_MODEL_KEY.search(script))


def _call_spans(script: str) -> list[str]:
    """The argument text of every agent( ... ) call in code, string-aware paren matching."""
    spans: list[str] = []
    for start in _code_call_starts(script):
        depth, quote, i = 1, "", start
        while i < len(script) and depth:
            ch = script[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = ""
            elif ch in "'\"`":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        spans.append(script[start : i - 1])
    return spans


def decide_workflow(
    tool_input: dict,
    main_model: str,
    agent_dirs: list[Path] | None = None,
    plugin_cache: Path | None = None,
) -> str | None:
    agent_dirs = AGENT_DIRS if agent_dirs is None else agent_dirs
    plugin_cache = PLUGIN_CACHE if plugin_cache is None else plugin_cache
    script = tool_input.get("script")
    script_path = tool_input.get("scriptPath")
    if isinstance(script_path, str) and script_path:
        try:
            script = Path(script_path).read_text(encoding="utf-8-sig")
        except OSError:
            script = None
            if is_fable(main_model):
                return (
                    f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and the "
                    f"workflow script {script_path!r} cannot be read to check its agent models. "
                    f"Owner override: '{OVERRIDE_PHRASE}'."
                )
    if isinstance(script, str) and script:
        if _FABLE_MODEL.search(script):
            return (
                f"FABLE DISPATCH GUARD ({HOOK}): the workflow script names model 'fable' for an agent. "
                "Owner rule: Fable never inside agent(); readers Haiku/Sonnet, judges Opus."
            )
        if not is_fable(main_model):
            return None
        spans = _call_spans(script)
        bare = sum(1 for span in spans if not _call_pinned(span, script, agent_dirs, plugin_cache))
        if bare:
            return (
                f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and {bare} of "
                f"{len(spans)} agent() calls name no model, so they would run on Fable. Give every agent() "
                f"a model and effort (CLAUDE.md Delegation). Owner override: '{OVERRIDE_PHRASE}'."
            )
        return None
    if is_fable(main_model) and tool_input.get("name"):
        return (
            f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and the named workflow "
            f"{tool_input.get('name')!r} cannot be checked here; plugin workflows such as claude-security:scan "
            "run model-inherit agents, so all of them would run on Fable. Ask the owner to switch the session "
            f"to Opus first (/model opus). Owner override: '{OVERRIDE_PHRASE}'."
        )
    return None


def overridden(env: dict, last_owner_text: str) -> bool:
    if str(env.get("CLAUDE_FABLE_DISPATCH_OK", "")).strip() in {"1", "true", "yes"}:
        return True
    return OVERRIDE_PHRASE in (last_owner_text or "").lower()


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    if kit.is_subagent(payload):
        return 0
    try:
        tool = payload.get("tool_name")
        tool_input = payload.get("tool_input") or {}
        if tool not in ("Agent", "Workflow") or not isinstance(tool_input, dict):
            return 0
        records = kit.tail_records(payload.get("transcript_path"))
        newest = kit.last_assistant(records) or {}
        main_model = str(newest.get("model") or "")
        owners = kit.owner_messages(records)
        if overridden(dict(os.environ), owners[-1][1] if owners else ""):
            return 0
        if tool == "Agent":
            reason = decide_agent(tool_input, main_model, AGENT_DIRS, PLUGIN_CACHE)
        else:
            reason = decide_workflow(tool_input, main_model)
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    return kit.deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
