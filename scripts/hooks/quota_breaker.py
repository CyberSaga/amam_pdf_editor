#!/usr/bin/env python3
"""PreToolUse hook (Agent|Workflow): no fan-out into a nearly spent quota.

2026-10-26: the weekly cap stopped work for 8 h; 10-13/14: a spend limit killed
46 agents mid-workflow, and because the workflow cache is keyed by model the
switch to another model re-ran everything.  Hooks do not receive rate limits,
but the statusline does (`rate_limits.five_hour/seven_day`, `spend_limit`);
the user-level statusline script persists them under
`~/.claude/statusline_state/<session>.json` after every API response, and this
hook reads the newest file.

Deny when a window is at or above its threshold (env, percent):
  CLAUDE_QUOTA_BREAKER_5H=90  CLAUDE_QUOTA_BREAKER_7D=95  CLAUDE_QUOTA_BREAKER_SPEND=95
Fail open when the newest state is older than CLAUDE_QUOTA_BREAKER_STALE_MINUTES
(30) or missing: no data is not a reason to refuse.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import _hookkit as kit

HOOK = "quota_breaker"
STATE_DIR = Path.home() / ".claude" / "statusline_state"
WINDOWS = (("5h", "five_hour", "5H"), ("7d", "seven_day", "7D"), ("spend", "spend_limit", "SPEND"))


def thresholds(env: dict) -> dict:
    out = {"5h": 90.0, "7d": 95.0, "spend": 95.0, "stale_minutes": 30.0}
    for key, name in (("5h", "5H"), ("7d", "7D"), ("spend", "SPEND"), ("stale_minutes", "STALE_MINUTES")):
        raw = env.get(f"CLAUDE_QUOTA_BREAKER_{name}")
        if raw:
            try:
                out[key] = float(raw)
            except ValueError:
                pass
    return out


def newest_state(state_dir: Path) -> dict | None:
    best: dict | None = None
    try:
        files = list(state_dir.glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            state = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict) or not isinstance(state.get("ts"), (int, float)):
            continue
        if best is None or state["ts"] > best["ts"]:
            best = state
    return best


def _resets(window: dict) -> str:
    at = window.get("resets_at")
    if isinstance(at, (int, float)):
        return ", resets " + time.strftime("%H:%M", time.localtime(at))
    return ""


def decide(state: dict | None, now: float, th: dict) -> str | None:
    if not state:
        return None
    ts = state.get("ts")
    if not isinstance(ts, (int, float)) or now - ts > th["stale_minutes"] * 60:
        return None
    limits = state.get("rate_limits") or {}
    for label, field, env_name in WINDOWS:
        window = limits.get(field) or {}
        pct = window.get("used_percentage")
        if isinstance(pct, (int, float)) and pct >= th[label]:
            age = (now - ts) / 60
            return (
                f"QUOTA BREAKER ({HOOK}): the {label} window is at {pct:.0f}% (limit {th[label]:.0f}%"
                f"{_resets(window)}; statusline data {age:.0f} min old). A fan-out now ends in 429s, "
                "and switching model afterwards invalidates the workflow cache. Wait for the reset, "
                "shrink the work to what fits, or tell the owner; raise CLAUDE_QUOTA_BREAKER_"
                f"{env_name} only with their say-so."
            )
    return None


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    if kit.is_subagent(payload):
        return 0
    try:
        reason = decide(newest_state(STATE_DIR), time.time(), thresholds(dict(os.environ)))
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    return kit.deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
