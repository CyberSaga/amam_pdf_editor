#!/usr/bin/env python3
"""PreToolUse hook (Agent|Workflow) and SubagentStop hook: subagent model routing and the Fable cap.

Routing rule: every spawn names its model, and at most ONE Fable subagent runs at a time (a
per-session cap; owner decision 2026-11-14, replacing "Fable never in a subagent").  An Agent call
without `model` silently inherits the session model, which can be the dearest one.

2026-11-04: a claude-security high scan (232 agents, ~21.6 M subagent tokens) ran entirely on Fable
because its agents are ``model: inherit`` and its workflow names no model.  The cap and the inherit
checks below exist so that cannot recur.  (The former ``fable_dispatch_guard`` is folded in here.)

Agent:
  * a *Fable intent* is an explicit ``model`` containing "fable", a definition that pins Fable, or,
    when the main session is Fable, anything that would inherit it (``fork``, no ``model`` with an
    ``inherit``/missing/unknown definition).  A Fable intent claims the session's single slot and is
    denied while the slot is busy.  The slot is released by the SubagentStop hook (``--event
    release``: the stopped subagent ran on Fable, or has the claimed agent type) and expires after
    CLAUDE_FABLE_SLOT_TTL_S (default 2700 s) so a killed subagent cannot hold it forever.  A claim is
    "pending" until the SubagentStart hook (``--event start``) sees a subagent of the claimed type; a
    pending claim expires after CLAUDE_FABLE_PENDING_TTL_S (default 300 s), so a call that another hook
    or the permission prompt denied (no subagent ever starts) frees the slot instead of holding it 45 min.
  * without a Fable intent and without ``model``: allow only ``subagent_type`` "fork" (non-Fable
    main), "codex:*", or a project agent whose ``.claude/agents/<type>.md`` pins a non-Fable
    ``model:``.  Everything else is denied.
Workflow: Fable never runs inside ``agent()`` (one workflow fans out): deny an inline script that
assigns a fable model, and, when the main session is Fable, a named workflow, an unreadable
``scriptPath`` or an ``agent()`` call that pins no model.
Override (Workflow inheritance checks only, never the Agent cap): env CLAUDE_FABLE_DISPATCH_OK=1.  The
owner-message phrase ``fable-dispatch-ok`` was removed 2026-11-14.
Failed-subagent latch (main session only): a failed Agent-task notification (task id starting with ``a``,
``<status>failed</status>``) newer than the
owner's newest message denies every Agent/Workflow call until the owner speaks again.
Subagent payloads skip the main-session checks (their dispatches inherit the subagent's model).
Project directory: CLAUDE_PROJECT_DIR, else the payload's `cwd`, else ".".
A payload that is not JSON or whose tool_input is not an object fails open.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import _hookkit as kit

HOOK = "model_route_guard"
FABLE = "fable"
OVERRIDE_ENV = "CLAUDE_FABLE_DISPATCH_OK"
SLOT_TTL_S = float(os.environ.get("CLAUDE_FABLE_SLOT_TTL_S") or 2700)
# A claim is "pending" until a SubagentStart of the same type confirms it.  If another hook or the permission
# prompt denies the call, no subagent ever starts and the pending claim frees itself after this many seconds
# (longer than a permission prompt normally takes; a late start still confirms it, see confirm_fable_slot).
PENDING_TTL_S = float(os.environ.get("CLAUDE_FABLE_PENDING_TTL_S") or 300)
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
AGENT_DIRS = [PROJECT_DIR / ".claude" / "agents", Path.home() / ".claude" / "agents"]
PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache"

_NAME = re.compile(r"[A-Za-z0-9_.:-]+")
_SCRIPT_FABLE = re.compile(r"""\bmodel['"`]?\s*[:=]\s*(['"`])[^'"`\n]*fable[^'"`\n]*\1""", re.IGNORECASE)
_AGENT_CALL = re.compile(r"\bagent\s*\(")
_MODEL_KEY = re.compile(r"\bmodel\s*:")
_FABLE_MODEL = re.compile(r"""\bmodel\s*:\s*['"`][^'"`]*fable""", re.IGNORECASE)
_AGENT_TYPE = re.compile(r"""\bagentType\s*:\s*['"`]([^'"`]+)['"`]""")

# A claim callable: given the agent type about to run on Fable, None when the slot was taken, else a deny reason.
Claim = Callable[[str], "str | None"]

DENY_FABLE = (
    "MODEL ROUTE (model_route_guard): this call would run a subagent on Fable and no slot is available "
    "(a Fable subagent is allowed only through the one-at-a-time cap). "
    "Pass model: haiku|sonnet|opus on the call (readers haiku/sonnet, judges opus)."
)
DENY_NO_MODEL = (
    "MODEL ROUTE (model_route_guard): every subagent spawn needs an explicit model; without one it "
    "inherits the session model, which can be the dearest. Pass model: haiku|sonnet|opus on the call, "
    "or use an agent whose definition pins a model."
)
DENY_WORKFLOW = (
    "MODEL ROUTE (model_route_guard): Fable never runs inside a workflow agent() (one workflow fans out), "
    "and this script assigns a fable model to an agent. Use model: 'haiku'|'sonnet'|'opus' in the script."
)


def is_fable(model: str | None) -> bool:
    return bool(model) and FABLE in str(model).lower()


# --------------------------------------------------------------------------- agent definitions


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


# --------------------------------------------------------------------------- the one-Fable-subagent slot


def slot_dir() -> Path:
    return Path(os.environ.get("CLAUDE_FABLE_SLOT_DIR") or Path(tempfile.gettempdir()) / "pdf_editor_claude_fable_slot")


def _slot_file(directory: Path, session_id: object) -> Path:
    sid = str(session_id or "default")
    return directory / (sid if re.fullmatch(r"[\w-]{1,128}", sid) else "default") / "slot.json"


def _read_slot(path: Path, now: float, ttl: float, pending_ttl: float | None = None) -> dict | None:
    """The live claim, else None.  A record with no ``state`` (older hook version) counts as confirmed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("claimed_at"), (int, float)):
        return None
    if data.get("state") == "pending":
        ttl = min(ttl, PENDING_TTL_S if pending_ttl is None else pending_ttl)
    return data if now - float(data["claimed_at"]) < ttl else None


def claim_fable_slot(
    directory: Path,
    session_id: object,
    agent_type: str,
    now: float | None = None,
    ttl: float | None = None,
    pending_ttl: float | None = None,
) -> str | None:
    """Take the session's single Fable slot (pending until SubagentStart); None on success, else the deny reason."""
    now = time.time() if now is None else now
    ttl = SLOT_TTL_S if ttl is None else ttl
    path = _slot_file(directory, session_id)
    held = _read_slot(path, now, ttl, pending_ttl)
    if held is not None:
        return (
            f"FABLE CAP ({HOOK}): one Fable subagent may run at a time and '{held.get('agent_type')}' "
            f"is running (claimed {int(now - float(held['claimed_at']))} s ago). Wait for it to finish "
            f"(SubagentStop releases the slot; a stale claim expires after {int(ttl)} s), or ask the owner."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if held is None and path.exists():
        # Clear only a claim that is really stale: it parses but expired (re-read with no TTL, so a
        # fresh claim another caller just wrote is not mistaken for one), or it is unreadable
        # and old.  Otherwise leave it to the exclusive create below.
        try:
            expired = _read_slot(path, now, float("inf"), float("inf")) is not None
            unreadable_and_old = not expired and time.time() - path.stat().st_mtime > ttl
            if expired or unreadable_and_old:
                path.unlink()
        except OSError:
            pass
    try:
        # "x" is atomic: of two Agent calls that both saw a free slot, only one creates the file.
        with open(path, "x", encoding="utf-8") as fh:
            record = {"claimed_at": now, "agent_type": agent_type, "state": "pending"}
            fh.write(json.dumps(record))
    except FileExistsError:
        other = _read_slot(path, now, ttl, pending_ttl) or {}
        return (
            f"FABLE CAP ({HOOK}): one Fable subagent may run at a time and '{other.get('agent_type', 'another')}' "
            "just took the slot. Wait for it to finish, or ask the owner."
        )
    return None


def confirm_fable_slot(
    directory: Path, session_id: object, started_type: str, now: float | None = None, pending_ttl: float | None = None
) -> bool:
    """SubagentStart: a subagent of the claimed type really started, so the claim stops being pending.

    Revives a pending claim that outlived its pending ttl (a slow permission prompt) as long as no later claim
    replaced it.  Residual: a non-Fable agent of the same type starting inside the window also confirms it.
    """
    now = time.time() if now is None else now
    path = _slot_file(directory, session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("state") != "pending" or not started_type:
        return False
    if started_type != data.get("agent_type"):
        return False
    try:
        record = {"claimed_at": now, "agent_type": data["agent_type"], "state": "confirmed"}
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        return False
    return True


def release_fable_slot(
    directory: Path, session_id: object, stopped_type: str, stopped_model: str, now: float | None = None
) -> bool:
    """Free the slot when the stopped subagent ran on Fable; by claimed agent type only if its model is unreadable."""
    now = time.time() if now is None else now
    path = _slot_file(directory, session_id)
    held = _read_slot(path, now, SLOT_TTL_S)
    if held is None:
        return False
    if stopped_model:
        if not is_fable(stopped_model):
            return False  # a Sonnet/Opus agent of the same type finishing must not free a Fable agent's slot
    elif not (stopped_type and stopped_type == held.get("agent_type")):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


# --------------------------------------------------------------------------- failed-subagent latch
# A subagent that failed (limit, credits, API error) must not have its work re-run on another model on the
# model's own initiative.  Pull-based: the main transcript's newest failed task-notification after the owner's
# newest message denies every Agent/Workflow call until the owner speaks again.

_STATUS_FAILED = "<status>failed</status>"
_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
# Agent task ids start with "a"; Monitor/Bash background tasks start with "b" and also report a failed status.
_AGENT_TASK = re.compile(r"<task-id>a[^<]*</task-id>")


def _notification_text(rec: dict) -> str | None:
    """Text of a task-notification record in any of the shapes the harness writes, else None.

    Idle session: a ``user`` record with ``origin.kind == "task-notification"``.  Mid-turn: a ``queue-operation``
    enqueue (``content``) and an ``attachment`` record (``commandMode == "task-notification"``, text in
    ``prompt``); no user record exists then.
    """
    kind = rec.get("type")
    if kind == "user":
        origin, message = rec.get("origin"), rec.get("message")
        if isinstance(origin, dict) and origin.get("kind") == "task-notification" and isinstance(message, dict):
            return kit._text_of(message.get("content"))
    elif kind == "attachment":
        att = rec.get("attachment")
        if isinstance(att, dict) and att.get("commandMode") == "task-notification":
            prompt = att.get("prompt")
            return prompt if isinstance(prompt, str) else None
    elif kind == "queue-operation" and rec.get("operation") == "enqueue":
        content = rec.get("content")
        if isinstance(content, str) and "<task-notification>" in content:
            return content
    return None


def failed_subagent_reason(records: list[dict]) -> str | None:
    """Deny reason when a failed Agent task-notification is newer than the owner's newest message, else None."""
    owner = kit.owner_messages(records, dedupe=False)
    since = max((ts for ts, _ in owner), default=0.0)  # resume re-appends old records: file order is not time order
    # an enqueue later removed with reason "delivered_to_agent" went to a subagent, not to this session
    delivered = {
        rec.get("content")
        for rec in records
        if rec.get("type") == "queue-operation"
        and rec.get("operation") == "remove"
        and rec.get("reason") == "delivered_to_agent"
    }
    summary: str | None = None
    for rec in records:
        text = _notification_text(rec)
        if rec.get("type") == "queue-operation" and text in delivered:
            continue
        if not text or _STATUS_FAILED not in text or not _AGENT_TASK.search(text):
            continue
        ts = kit.parse_ts(rec.get("timestamp"))
        if ts is None or ts <= since:
            continue
        m = _SUMMARY.search(text)
        summary = " ".join(m.group(1).split())[:300] if m else "no summary"
    if summary is None:
        return None
    return (
        f"A subagent failed ({summary}). Do not re-run or re-route its work on any model, including the same "
        "model; report the failure to the owner and end the turn. Their next message lifts this."
    )


# --------------------------------------------------------------------------- Agent decisions


def _fable_gate(deny: str, agent_type: str, claim: Claim | None) -> str | None:
    """A Fable intent: deny outright without a claim callable, else take the slot or return why not."""
    return deny if claim is None else claim(agent_type)


def decide_agent(
    tool_input: dict,
    main_model: str,
    agent_dirs: list[Path],
    plugin_cache: Path,
    claim: Claim | None = None,
) -> str | None:
    """The Fable-related deny reason for an Agent call, or None (also when the call is not Fable-bound)."""
    subagent_type = tool_input.get("subagent_type")
    explicit = tool_input.get("model")
    kind = subagent_type if isinstance(subagent_type, str) and subagent_type else "general-purpose"
    if is_fable(explicit) and subagent_type != "fork":
        return _fable_gate(
            f"FABLE DISPATCH GUARD ({HOOK}): this Agent call asks for model 'fable'. Pick haiku/sonnet "
            "(readers) or opus (judges), or have the owner allow a Fable slot.",
            kind,
            claim,
        )
    if not is_fable(main_model):
        pinned = None
        if not (isinstance(explicit, str) and explicit.strip()) and isinstance(subagent_type, str) and subagent_type not in ("", "fork"):
            pinned = agent_definition_model(subagent_type, agent_dirs, plugin_cache)
        if pinned is not None and is_fable(pinned):  # a definition that pins Fable runs on Fable
            return _fable_gate(f"FABLE DISPATCH GUARD ({HOOK}): agent type '{kind}' pins model Fable.", kind, claim)
        return None
    if subagent_type == "fork":
        return _fable_gate(
            f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and a fork always "
            "inherits it (a model override is ignored). Use a fresh agent with model 'opus'/'sonnet'/"
            f"'haiku', or have the owner switch the session model. Owner override: env {OVERRIDE_ENV}=1 (workflows only).",
            "fork",
            claim,
        )
    if explicit:
        return None
    pinned = agent_definition_model(subagent_type, agent_dirs, plugin_cache)
    if pinned != "inherit" and not is_fable(pinned):
        return None
    return _fable_gate(
        f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and agent type "
        f"'{kind}' would run on it (its definition model is '{pinned}'). "
        "Pass model 'opus' (judges) or 'sonnet'/'haiku' (readers) on this call, or have the owner switch "
        f"the session model. Owner override: env {OVERRIDE_ENV}=1 (workflows only).",
        kind,
        claim,
    )


# --------------------------------------------------------------------------- Workflow decisions


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
                    f"Owner override: env {OVERRIDE_ENV}=1 (workflows only)."
                )
    if isinstance(script, str) and script:
        if _FABLE_MODEL.search(script) or _SCRIPT_FABLE.search(script):
            return DENY_WORKFLOW
        if not is_fable(main_model):
            return None
        spans = _call_spans(script)
        bare = sum(1 for span in spans if not _call_pinned(span, script, agent_dirs, plugin_cache))
        if bare:
            return (
                f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and {bare} of "
                f"{len(spans)} agent() calls name no model, so they would run on Fable. Give every agent() "
                f"a model and effort (CLAUDE.md Delegation). Owner override: env {OVERRIDE_ENV}=1 (workflows only)."
            )
        return None
    if is_fable(main_model) and tool_input.get("name"):
        return (
            f"FABLE DISPATCH GUARD ({HOOK}): the main session is Fable ({main_model}) and the named workflow "
            f"{tool_input.get('name')!r} cannot be checked here; plugin workflows such as claude-security:scan "
            "run model-inherit agents, so all of them would run on Fable. Ask the owner to switch the session "
            f"to Opus first (/model opus). Owner override: env {OVERRIDE_ENV}=1 (workflows only)."
        )
    return None


def decide(
    tool_name: str,
    tool_input: object,
    project_dir: Path,
    main_model: str = "",
    claim: Claim | None = None,
    plugin_cache: Path | None = None,
) -> str | None:
    """A deny reason, or None to allow.  *main_model* is "" for subagent payloads / an unknown model."""
    agent_dirs = [project_dir / ".claude" / "agents", Path.home() / ".claude" / "agents"]
    cache = PLUGIN_CACHE if plugin_cache is None else plugin_cache
    if tool_name == "Workflow":
        if not isinstance(tool_input, dict):
            return None
        return decide_workflow(tool_input, main_model, agent_dirs, cache)
    if tool_name != "Agent":
        return None
    if not isinstance(tool_input, dict):
        return DENY_NO_MODEL
    # Take the slot only once the whole call is known to be allowed: a claim made before the no-model checks
    # below would leak whenever this same hook then denies the call.
    wanted: list[str] = []

    def record(agent_type: str) -> None:
        wanted.append(agent_type)

    fable_reason = decide_agent(tool_input, main_model, agent_dirs, cache, record if claim is not None else None)
    if fable_reason:
        return fable_reason
    reason = _no_model_reason(tool_input, project_dir)
    if reason:
        return reason
    if wanted and claim is not None:
        return claim(wanted[0])
    return None


def _no_model_reason(tool_input: dict, project_dir: Path) -> str | None:
    model = tool_input.get("model")
    if isinstance(model, str) and model.strip():
        return None  # explicit and not Fable (a Fable intent was handled above)
    sub = tool_input.get("subagent_type")
    if not isinstance(sub, str) or not sub:
        return DENY_NO_MODEL
    if sub == "fork" or sub.startswith("codex:"):
        return None
    pin = pinned_model(project_dir, sub)
    if pin is None or pin.lower() == "inherit":
        return DENY_NO_MODEL
    return None


# --------------------------------------------------------------------------- hook entry points


def overridden(env: dict) -> bool:
    return str(env.get(OVERRIDE_ENV, "")).strip().lower() in {"1", "true", "yes"}


def _release_main(payload: dict) -> int:
    """SubagentStop: free the slot when the stopped subagent held it.  Never blocks."""
    try:
        stopped_type = str(payload.get("agent_type") or "")
        records = kit.tail_records(payload.get("agent_transcript_path"))
        # A failed run ends in a "<synthetic>" record; the model that ran is the newest real one.
        real = [r for r in records if (r.get("message") or {}).get("model") != "<synthetic>"]
        stopped_model = str((kit.last_assistant(real) or {}).get("model") or "")
        release_fable_slot(slot_dir(), payload.get("session_id"), stopped_type, stopped_model)
    except Exception as exc:
        return kit.fail_open(HOOK, f"release: {exc.__class__.__name__}: {exc}")
    return 0


def _start_main(payload: dict) -> int:
    """SubagentStart: confirm the pending claim of the started type.  Never blocks."""
    try:
        confirm_fable_slot(slot_dir(), payload.get("session_id"), str(payload.get("agent_type") or ""))
    except Exception as exc:
        return kit.fail_open(HOOK, f"start: {exc.__class__.__name__}: {exc}")
    return 0


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    argv = sys.argv[1:]
    event = argv[argv.index("--event") + 1 : argv.index("--event") + 2] if "--event" in argv else []
    if event == ["release"]:
        return _release_main(payload)
    if event == ["start"]:
        return _start_main(payload)
    tool = str(payload.get("tool_name") or "")
    if tool not in ("Agent", "Workflow"):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return kit.fail_open(HOOK, "hook input has no tool_input object")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    try:
        main_model = ""
        if not kit.is_subagent(payload):
            records = kit.tail_records(payload.get("transcript_path"))
            newest = kit.last_assistant(records) or {}
            main_model = str(newest.get("model") or "")
            latched = failed_subagent_reason(records)
            if latched:
                return kit.deny(latched)
            if tool == "Workflow" and overridden(dict(os.environ)):
                main_model = ""  # the override lifts the Workflow inheritance checks only, never the Agent cap
        sid = payload.get("session_id")

        def claim(agent_type: str) -> str | None:
            return claim_fable_slot(slot_dir(), sid, agent_type)

        reason = decide(tool, tool_input, Path(str(root)), main_model, claim)
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    return kit.deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
