"""Shared pieces of the Claude Code hooks in this directory (stdlib only).

Every hook reads one JSON payload from stdin, answers with JSON on stdout and
exits 0; a payload it cannot parse makes it fail OPEN (exit 1 with a warning on
stderr, nothing denied) so a broken hook is visible instead of locking the
session.  The transcript helpers read only the tail of the session's jsonl and
never raise on malformed lines.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Text the harness itself puts into a prompt or a queued message: task
# notifications, messages from other sessions, slash-command echoes.  None of
# it is the owner speaking.
HARNESS_PREFIXES = (
    "<task-notification",
    "[SYSTEM NOTIFICATION",
    "<agent-message",
    "<system-reminder",
    "<local-command",
    "<command-name",
    "<command-message",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
    "<user-memory-input",
    "<<autonomous-loop",
)

# Tools whose `prompt` argument the harness later replays as a user turn.
SCHEDULER_TOOLS = ("ScheduleWakeup", "CronCreate")


def read_payload() -> dict | None:
    """The hook payload, or None when stdin is not a JSON object."""
    try:
        # utf-8-sig: tolerate a BOM (PowerShell pipes prepend one)
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def fail_open(hook: str, why: str) -> int:
    print(f"{hook}: {why} -- this call was NOT checked.", file=sys.stderr)
    return 1


def emit(obj: dict) -> int:
    # ASCII-only JSON: the hook's stdout is a pipe whose encoding Windows picks.
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=True).encode("ascii"))
    sys.stdout.buffer.write(b"\n")
    return 0


def deny(reason: str) -> int:
    return emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def block_prompt(reason: str) -> int:
    return emit({"decision": "block", "reason": reason})


def block_stop(reason: str) -> int:
    return emit({"decision": "block", "reason": reason})


def add_context(event: str, text: str) -> int:
    return emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def is_subagent(payload: dict) -> bool:
    return bool(payload.get("agent_id"))


def is_harness_text(text: str) -> bool:
    s = text.lstrip()
    return s.startswith(HARNESS_PREFIXES)


def is_slash(text: str) -> bool:
    return text.lstrip().startswith("/")


# --------------------------------------------------------------------------- transcript


def parse_ts(value: object) -> float | None:
    """Epoch seconds for a transcript timestamp (ISO 8601, 'Z' or offset)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def tail_records(path: str | Path | None, max_bytes: int = 3_000_000) -> list[dict]:
    """The parsed records in the last *max_bytes* of a jsonl transcript, in order."""
    if not path:
        return []
    p = Path(path)
    try:
        size = p.stat().st_size
        with open(p, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # drop the partial first line
            data = fh.read()
    except OSError:
        return []
    out: list[dict] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _text_of(content: object) -> str | None:
    """Owner-visible text of a user message; None for tool results / non-text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return None
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts) if parts else None
    return None


def scheduled_prompts(records: list[dict]) -> set[str]:
    """Prompt texts handed to ScheduleWakeup/CronCreate; replayed later as user turns."""
    found: set[str] = set()
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") in SCHEDULER_TOOLS
            ):
                prompt = (block.get("input") or {}).get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    found.add(prompt.strip())
    return found


def owner_messages(records: list[dict]) -> list[tuple[float, str]]:
    """(epoch, text) of every message the owner typed, oldest first.

    Typed prompts are ``user`` records whose content is text (not a tool
    result, not a compact summary, not a meta record); messages typed while a
    turn runs are ``queue-operation`` enqueues.  Harness text (notifications,
    slash echoes, scheduled prompts firing) is left out.
    """
    replayed = scheduled_prompts(records)
    out: list[tuple[float, str]] = []
    for rec in records:
        kind = rec.get("type")
        text: str | None = None
        if kind == "user":
            if rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
                continue
            text = _text_of((rec.get("message") or {}).get("content"))
        elif kind == "queue-operation" and rec.get("operation") == "enqueue":
            content = rec.get("content")
            text = content if isinstance(content, str) else None
        if not text or not text.strip():
            continue
        stripped = text.strip()
        if is_harness_text(stripped) or is_slash(stripped) or _replays(stripped, replayed):
            continue
        if out and out[-1][1] == stripped:
            continue  # the same message recorded twice (queued, then delivered)
        ts = parse_ts(rec.get("timestamp"))
        out.append((ts if ts is not None else 0.0, stripped))
    return out


def _replays(text: str, scheduled: set[str]) -> bool:
    for prompt in scheduled:
        head = prompt[:80]
        if text == prompt or text.startswith(head) or head in text:
            return True
    return False


def is_replayed_prompt(text: str, records: list[dict]) -> bool:
    """True when *text* is a ScheduleWakeup/CronCreate prompt firing (scheduled turns
    are recorded as isMeta user records carrying scheduledFireId)."""
    return _replays(text.strip(), scheduled_prompts(records))


def pending_scheduler_call(records: list[dict]) -> bool:
    """True when the newest assistant tool call is a live ScheduleWakeup/CronCreate
    (the next prompt is then the harness firing it, not the owner)."""
    for rec in reversed(records):
        if rec.get("type") == "user":
            content = (rec.get("message") or {}).get("content")
            if _text_of(content) is not None and not rec.get("isMeta"):
                return False
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name") in SCHEDULER_TOOLS:
                    inp = block.get("input") or {}
                    return not inp.get("stop")
                return False
    return False


def last_assistant(records: list[dict]) -> dict | None:
    """Summary of the newest assistant API message: ts, model, context tokens,
    cache TTL in minutes (from the newest message that wrote cache)."""
    summary: dict | None = None
    for rec in reversed(records):
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        if summary is None:
            summary = {
                "ts": parse_ts(rec.get("timestamp")),
                "model": msg.get("model") or "",
                "context_tokens": int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0),
                "ttl_minutes": None,
            }
        creation = usage.get("cache_creation") or {}
        if int(creation.get("ephemeral_1h_input_tokens") or 0) > 0:
            summary["ttl_minutes"] = 60
            break
        if int(creation.get("ephemeral_5m_input_tokens") or 0) > 0:
            summary["ttl_minutes"] = 5
            break
    return summary


def last_compact_ts(records: list[dict]) -> float | None:
    for rec in reversed(records):
        if rec.get("type") == "system" and rec.get("subtype") == "compact_boundary":
            return parse_ts(rec.get("timestamp"))
        if rec.get("type") == "user" and rec.get("isCompactSummary"):
            return parse_ts(rec.get("timestamp"))
    return None
