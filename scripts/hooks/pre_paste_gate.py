#!/usr/bin/env python3
"""Pre-paste gate: a Grok paste needs a clean tracked tree (memory 11-01).

Batch 20261101_1550 was refused 15/15 because `D plans/true-text-i1.md` was
pending when the owner pasted.  The rule "`git diff HEAD --stat` must be empty
before any paste" lived in memory; this hook checks it at the two moments it
matters.

`--event stop` (Stop hook): when the assistant's final message tells the
owner to paste and tracked files differ from HEAD, block the stop ONCE
(`stop_hook_active` false) so the message is rewritten with the dirty list
and what to do.  A message that already warns passes.
`--event prompt` (UserPromptSubmit): when the owner says they pasted or are
about to, add the dirty list as context so the first words of the reply are
the warning.  Never blocks a prompt.

Untracked files do not count (the batch dirs are untracked by design).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import _hookkit as kit

HOOK = "pre_paste_gate"

CUE_RE = re.compile(
    r"\bpaste[ds]?\b|\bpasting\b|貼上|貼到|貼給|貼進|貼去|去貼|請貼|可以貼|貼\s?(?:v\d+|pilot|full|brief)",
    re.I,
)
NEG_RE = re.compile(
    r"nothing to paste|not (?:yet )?paste|don'?t paste|do not paste|no paste|不要貼|先別貼|別貼|不用貼|還不能貼|尚未",
    re.I,
)
OWNER_CUE_RE = re.compile(r"貼了|貼上|貼好|要貼|準備貼|貼\s?v\d+|\bpasted\b|\bpaste\b|\bpasting\b", re.I)
WARN_RE = re.compile(
    r"dirty|uncommitted|un-committed|git diff HEAD|未\s?commit|沒\s?commit|沒有\s?commit|還沒\s?commit|先\s?commit"
    r"|工作樹|tree\s+(?:is\s+)?not\s+clean|not clean",
    re.I,
)


def has_paste_cue(text: str) -> bool:
    return bool(CUE_RE.search(text)) and not NEG_RE.search(text)


def already_warns(text: str) -> bool:
    return bool(WARN_RE.search(text))


def dirty_files(cwd: str | Path) -> list[str]:
    """`git diff HEAD --name-status` lines; [] when clean or when git cannot answer."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "diff", "HEAD", "--name-status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


def _listing(dirty: list[str]) -> str:
    shown = dirty[:12]
    more = f"\n  ... and {len(dirty) - 12} more" if len(dirty) > 12 else ""
    return "\n".join(f"  {line}" for line in shown) + more


def stop_decision(last_message: str, stop_hook_active: bool, dirty: list[str]) -> str | None:
    if stop_hook_active or not dirty or not has_paste_cue(last_message) or already_warns(last_message):
        return None
    return (
        f"PRE-PASTE GATE ({HOOK}): this message tells the owner to paste, but tracked files differ "
        f"from HEAD (git diff HEAD --name-status):\n{_listing(dirty)}\n"
        "The Grok batch validator refuses a dirty tree (2026-11-01: 15/15 blocked). Rewrite the "
        "message so the owner reads this first: the tree is dirty, which files, and what to do "
        "(commit when they authorise it, stash, or revert) before pasting. Do not commit on your own."
    )


def run_stop_event(payload: dict) -> int:
    if kit.is_subagent(payload):
        return 0
    message = str(payload.get("last_assistant_message") or "")
    if not has_paste_cue(message):
        return 0
    dirty = dirty_files(payload.get("cwd") or ".")
    reason = stop_decision(message, bool(payload.get("stop_hook_active")), dirty)
    return kit.block_stop(reason) if reason else 0


def run_prompt_event(payload: dict) -> int:
    if kit.is_subagent(payload):
        return 0
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or kit.is_harness_text(prompt) or kit.is_slash(prompt) or not OWNER_CUE_RE.search(prompt):
        return 0
    dirty = dirty_files(payload.get("cwd") or ".")
    if not dirty:
        return 0
    return kit.add_context(
        "UserPromptSubmit",
        f"PRE-PASTE GATE ({HOOK}): the owner is pasting or about to, but tracked files differ from HEAD "
        f"(git diff HEAD --name-status):\n{_listing(dirty)}\nThe batch validator will refuse the paste. "
        "Say this first and what to do; do not commit on your own.",
    )


def main(argv: list[str]) -> int:
    event = argv[argv.index("--event") + 1] if "--event" in argv else "stop"
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    try:
        return run_prompt_event(payload) if event == "prompt" else run_stop_event(payload)
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
