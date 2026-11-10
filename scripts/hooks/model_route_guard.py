#!/usr/bin/env python3
"""PreToolUse hook (Agent|Workflow): every subagent has an explicit, non-Fable model.

Routing rule: Fable never runs inside a subagent, and every spawn names its
model.  An Agent call without `model` silently inherits the session model,
which can be the dearest one.

Agent: deny `model` containing "fable" (case-insensitive); allow any other
non-empty string `model`.  Without `model`, allow only `subagent_type` "fork"
(a fork runs on the parent's model and ignores `model`), "codex:*" (a thin
forwarder to an external CLI), or a project agent whose
`.claude/agents/<subagent_type>.md` frontmatter pins `model:` to something that
is neither `inherit` nor a fable model.  Everything else is denied.
Workflow: deny an inline `script` that assigns a fable model (`model: 'fable'`,
`model = "claude-fable-5"`, quotes ' " or `).  The script is not parsed further;
`scriptPath`/`name` invocations pass.
Project directory: CLAUDE_PROJECT_DIR, else the payload's `cwd`, else ".".
A payload that is not JSON or whose tool_input is not an object fails open.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import _hookkit as kit

HOOK = "model_route_guard"
FABLE = "fable"
_NAME = re.compile(r"[A-Za-z0-9_.:-]+")
_SCRIPT_FABLE = re.compile(r"""\bmodel['"`]?\s*[:=]\s*(['"`])[^'"`\n]*fable[^'"`\n]*\1""", re.IGNORECASE)

DENY_FABLE = (
    "MODEL ROUTE (model_route_guard): Fable never runs inside a subagent. "
    "Pass model: haiku|sonnet|opus on the call (readers haiku/sonnet, judges opus)."
)
DENY_NO_MODEL = (
    "MODEL ROUTE (model_route_guard): every subagent spawn needs an explicit model; without one it "
    "inherits the session model, which can be the dearest. Pass model: haiku|sonnet|opus on the call, "
    "or use an agent whose definition pins a model."
)
DENY_WORKFLOW = (
    "MODEL ROUTE (model_route_guard): Fable never runs inside a subagent, and this workflow script "
    "assigns a fable model to an agent. Use model: 'haiku'|'sonnet'|'opus' in the script."
)


def pinned_model(project_dir: Path, subagent_type: str) -> str | None:
    """The `model:` value in the frontmatter of .claude/agents/<subagent_type>.md, or None."""
    if not _NAME.fullmatch(subagent_type):
        return None
    agents = project_dir / ".claude" / "agents"
    try:
        if f"{subagent_type}.md" not in {p.name for p in agents.iterdir()}:  # exact case, even on Windows
            return None
        lines = (agents / f"{subagent_type}.md").read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        m = re.match(r"model\s*:\s*(.*)$", line)
        if m:
            value = m.group(1).split(" #")[0].strip().strip("'\"").strip()
            return value or None
    return None


def decide(tool_name: str, tool_input: object, project_dir: Path) -> str | None:
    """A deny reason, or None to allow."""
    if tool_name == "Workflow":
        script = tool_input.get("script") if isinstance(tool_input, dict) else None
        if isinstance(script, str) and _SCRIPT_FABLE.search(script):
            return DENY_WORKFLOW
        return None
    if tool_name != "Agent":
        return None
    if not isinstance(tool_input, dict):
        return DENY_NO_MODEL
    model = tool_input.get("model")
    if isinstance(model, str) and model.strip():
        return DENY_FABLE if FABLE in model.lower() else None
    sub = tool_input.get("subagent_type")
    if not isinstance(sub, str) or not sub:
        return DENY_NO_MODEL
    if sub == "fork" or sub.startswith("codex:"):
        return None
    pin = pinned_model(project_dir, sub)
    if pin is None or pin.lower() == "inherit":
        return DENY_NO_MODEL
    return DENY_FABLE if FABLE in pin.lower() else None


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    tool = str(payload.get("tool_name") or "")
    if tool not in ("Agent", "Workflow"):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return kit.fail_open(HOOK, "hook input has no tool_input object")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    try:
        reason = decide(tool, tool_input, Path(str(root)))
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    return kit.deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
