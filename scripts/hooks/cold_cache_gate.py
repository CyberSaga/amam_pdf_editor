#!/usr/bin/env python3
"""UserPromptSubmit hook: do not re-read a cold, big context on a dear model.

The prompt cache lives 1 h on the plan allowance (5 min once Fable is billed
from usage credits).  After that, the next request re-reads the whole context
at full input price on whatever model is active.  The owner's own workaround
(switch to Sonnet, /compact, switch back) is right; this hook applies it at
the one moment it matters, before the first cold request, instead of after.

Decision (`decide`): block the prompt only when ALL hold:
  - the prompt was typed by the owner (not a slash command, not harness text,
    not the firing of a pending ScheduleWakeup/CronCreate, not in a subagent),
  - the newest API message is older than the cache TTL (+2 min) and no
    compaction happened since,
  - the context is at least CLAUDE_COLD_GATE_MIN_CONTEXT tokens (60k),
  - the model matches CLAUDE_COLD_GATE_MODELS (fable|opus).
A prompt starting with `!!` passes.  CLAUDE_COLD_GATE_MODE=context only adds a
note; `off` disables.  CLAUDE_COLD_GATE_IDLE_MINUTES overrides the TTL guess.
Everything else, including any error, lets the prompt through.
"""
from __future__ import annotations

import os
import re
import sys
import time

import _hookkit as kit

HOOK = "cold_cache_gate"
BYPASS = "!!"


def _alias(model: str) -> str:
    for name in ("fable", "opus", "sonnet", "haiku"):
        if name in model:
            return name
    return model or "the current model"


def _reason(idle_min: float, ttl: int, ctx: int, model: str) -> str:
    alias = _alias(model)
    return (
        f"[{HOOK}] 閒置 {idle_min:.0f} 分鐘（cache TTL {ttl} 分，已冷）、context ≈{ctx // 1000}k tokens、"
        f"模型 {model}。現在送出 = 用 {alias} 全價重讀整段。較省的做法：\n"
        f"  /model sonnet → /compact → /model {alias}  （不需要舊脈絡就 /clear）\n"
        f"然後重送這句。要照樣送出：句首加 `{BYPASS}`。（關閉：CLAUDE_COLD_GATE_MODE=off）"
    )


def decide(prompt: str, payload: dict, records: list[dict], now: float, env: dict) -> tuple[str, str]:
    """('allow' | 'block' | 'context', reason)."""
    mode = str(env.get("CLAUDE_COLD_GATE_MODE", "block")).strip().lower()
    if mode not in ("block", "context"):
        return "allow", ""
    if payload.get("agent_id"):
        return "allow", ""
    text = prompt.strip()
    if not text or text.startswith(BYPASS) or kit.is_slash(text) or kit.is_harness_text(text):
        return "allow", ""
    if kit.pending_scheduler_call(records) or kit.is_replayed_prompt(text, records):
        return "allow", ""
    last = kit.last_assistant(records)
    if not last or last["ts"] is None:
        return "allow", ""
    try:
        min_ctx = int(env.get("CLAUDE_COLD_GATE_MIN_CONTEXT", "60000"))
    except ValueError:
        min_ctx = 60000
    if last["context_tokens"] < min_ctx:
        return "allow", ""
    try:
        models = re.compile(str(env.get("CLAUDE_COLD_GATE_MODELS", "fable|opus")), re.I)
    except re.error:
        models = re.compile("fable|opus", re.I)
    if not models.search(last["model"]):
        return "allow", ""
    ttl = int(last["ttl_minutes"] or 60)
    override = env.get("CLAUDE_COLD_GATE_IDLE_MINUTES")
    try:
        idle_limit = float(override) if override else ttl + 2.0
    except ValueError:
        idle_limit = ttl + 2.0
    fresh = max(last["ts"], kit.last_compact_ts(records) or 0.0)
    idle_min = (now - fresh) / 60.0
    if idle_min < idle_limit:
        return "allow", ""
    return mode, _reason(idle_min, ttl, last["context_tokens"], last["model"])


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    try:
        records = kit.tail_records(payload.get("transcript_path"))
        verdict, reason = decide(str(payload.get("prompt") or ""), payload, records, time.time(), dict(os.environ))
    except Exception as exc:  # the gate never locks a session
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    if verdict == "block":
        return kit.block_prompt(reason)
    if verdict == "context":
        return kit.add_context("UserPromptSubmit", reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
