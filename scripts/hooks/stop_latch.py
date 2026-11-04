#!/usr/bin/env python3
"""Stop latch: "stop means stop" as a refusal, not a memory.

Memory `feedback-stop-means-stop`: "stop when this round finishes" = gate,
report, idle; queued passes wait for a fresh go-ahead.  On 2026-10-13 a /goal
loop ran a further waking day after the owner typed exactly that.

`--event tool` (PreToolUse on Agent|Workflow|ScheduleWakeup|CronCreate|Monitor):
reads the session transcript's tail, finds the owner's latest message (typed
prompts and mid-turn queued messages; harness notifications, slash lines and
replayed scheduled prompts do not count) and denies the call while that
message is a stop instruction.  The owner's next non-stop message lifts it.
`ScheduleWakeup(stop=true)` is always allowed (it ends a loop).

`--event prompt` (UserPromptSubmit): when the typed prompt is a stop
instruction, tells the model the latch is armed.  Never blocks a prompt.

Both skip inside subagents (their transcript is not the owner's).
"""
from __future__ import annotations

import re
import sys
import time

import _hookkit as kit

HOOK = "stop_latch"
LATCHED_TOOLS = ("Agent", "Workflow", "ScheduleWakeup", "CronCreate", "Monitor")

# Text that is not the owner's instruction even though it sits in their message:
# pasted documents, remote-control attachment echoes, quoted lines.
PASTED_RE = re.compile(r"<pasted_content\b[^>]*>.*?(?:</pasted_content>|\Z)", re.S)
ATTACH_RE = re.compile(r"<!--\s*attach\s*-->.*", re.S)
QUOTE_LINE_RE = re.compile(r"^\s*>.*$", re.M)

STOP_PATTERNS = [
    re.compile(r"^\W*(?:please\s+|pls\s+)?stop\b", re.I),
    re.compile(
        r"(?<!can't )(?<!can’t )(?<!cannot )(?<!couldn't )(?<!won't )(?<!not )"
        r"\bstop\s+(?:when|after|once|now|here|there|it|this|that|the\s+loop|the\s+run|"
        r"everything|all|dispatching|spawning|launching|running)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:do\s+not|don'?t|dont)\s+(?:start|launch|run|spawn|dispatch|kick\s+off)\s+"
        r"(?:another|any\s+more|more|new|the\s+next|a\s+new)\b",
        re.I,
    ),
    re.compile(r"\bno\s+more\s+(?:rounds?|passes|agents?|runs?|workflows?|batches)\b", re.I),
    # `停掉卡住的測試` (kill that stuck test) is not a stop-work instruction.
    re.compile(r"^\W*(?:請|先|就|可以|該|麻煩)?(?:停止|暫停|停下|停住|停(?!掉))"),
    re.compile(r"(?:跑完|做完|結束|這輪|這一輪|本輪|這回合)[^。\n]{0,12}?(?:就|再|後|之後)?(?:停|停下|停止)"),
    re.compile(r"(?:可以|該|先)停了?"),
    re.compile(r"(?:別|不要|不准|不得|不用)(?:再)?(?:跑|派|開|啟動|起|發)(?:下一輪|新的|更多|另一|下一個|下一批|任何|其他)"),
]


def instruction_text(text: str) -> str:
    """The owner's own words: pasted documents, attachment echoes and quoted lines removed."""
    t = PASTED_RE.sub(" ", text)
    t = ATTACH_RE.sub(" ", t)
    t = QUOTE_LINE_RE.sub(" ", t)
    return t.strip()


def is_stop_phrase(text: str) -> bool:
    t = instruction_text(text)
    return bool(t) and any(p.search(t) for p in STOP_PATTERNS)


def armed_by(records: list[dict]) -> str | None:
    """The owner's latest message when it is a stop instruction, else None."""
    messages = kit.owner_messages(records)
    if not messages:
        return None
    _ts, text = messages[-1]
    return text if is_stop_phrase(text) else None


def _reason(text: str, when: float | None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "earlier"
    return (
        f"STOP LATCH ({HOOK}): the owner's latest message ({stamp}) is a stop instruction: "
        f"\"{text[:160]}\". Stop means stop: finish the running gate in the foreground, "
        "report, then idle. No new Agent, Workflow, ScheduleWakeup, Cron or Monitor until "
        "the owner sends a fresh go-ahead (their next non-stop message lifts this latch)."
    )


def run_tool_event(payload: dict) -> int:
    if kit.is_subagent(payload):
        return 0
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool_name not in LATCHED_TOOLS:
        return 0
    if tool_name == "ScheduleWakeup" and tool_input.get("stop"):
        return 0
    records = kit.tail_records(payload.get("transcript_path"))
    text = armed_by(records)
    if text is None:
        return 0
    when = kit.owner_messages(records)[-1][0] or None
    return kit.deny(_reason(text, when))


def run_prompt_event(payload: dict) -> int:
    if kit.is_subagent(payload):
        return 0
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or kit.is_harness_text(prompt) or kit.is_slash(prompt):
        return 0
    if not is_stop_phrase(prompt):
        return 0
    return kit.add_context(
        "UserPromptSubmit",
        "STOP LATCH armed by this message: finish the running gate in the foreground, report, "
        "idle. Agent, Workflow, ScheduleWakeup, Cron and Monitor calls are denied until the "
        "owner's next non-stop message.",
    )


def main(argv: list[str]) -> int:
    event = argv[argv.index("--event") + 1] if "--event" in argv else "tool"
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    try:
        return run_prompt_event(payload) if event == "prompt" else run_tool_event(payload)
    except Exception as exc:  # a broken latch must never lock the session
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
