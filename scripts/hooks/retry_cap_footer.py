#!/usr/bin/env python3
"""PreToolUse hook (Agent): append a standard "retry cap" footer to every subagent prompt.

What: rewrites the Agent call's `prompt` to `<prompt>\n\n<FOOTER>` through
`hookSpecificOutput.updatedInput` (the whole input object is replaced, so every
other key is copied through) with `permissionDecision: "allow"`.
Why: over the 2026-10/11 transcripts the same pytest file was re-run three or
more times in a row while still failing in 24 episodes (longest streak 10).  A
third identical failure means the brief or the diagnosis is wrong; the main
thread keeps its freedom (a human watches it), subagent briefs get the rule
injected deterministically.
Scope: tool_name == "Agent" only.  Idempotent: a prompt that already contains
"Retry cap:" is left alone, as are empty prompts and every other tool (exit 0,
no output).  A payload that is not JSON or has no tool_input object fails open.
Combining: the hooks reference states that when several PreToolUse hooks
return different decisions the precedence is deny > defer > ask > allow, so a
deny from agent_prompt_guard.py / stop_latch.py / quota_breaker.py still wins
over this hook's allow + updatedInput.
Known gaps: the docs do not say whether `updatedInput` from several parallel
hooks is merged (only this hook rewrites Agent input today); the `allow`
auto-approves the call past a permission prompt (deny rules still apply).
"""
from __future__ import annotations

import sys

import _hookkit as kit

HOOK = "retry_cap_footer"
MARKER = "Retry cap:"
FOOTER = (
    "Retry cap: if the same check (a test, a build, a lint, a command) fails three times in a row, stop. "
    "Return with: what you tried (each attempt in one line), the exact last error, your current diagnosis, "
    "and what you would change in the plan. Do not keep retrying past three; a third identical failure means "
    "the brief or the diagnosis is wrong, not the typing."
)


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    if str(payload.get("tool_name") or "") != "Agent":
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return kit.fail_open(HOOK, "hook input has no tool_input object")
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or MARKER in prompt:
        return 0
    return kit.emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {**tool_input, "prompt": f"{prompt}\n\n{FOOTER}"},
        }
    })


if __name__ == "__main__":
    sys.exit(main())
