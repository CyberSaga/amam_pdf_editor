"""Codex adapter for the hooks in this directory (stdlib only).

Codex CLI (0.166, probed 2026-11-05) sends Claude-shaped payloads but answers
them differently: hook exit codes are IGNORED (exit 2 never blocks, exit 1 is
not a warning), and only ONE JSON object on stdout acts.  So every Codex leg:
  - builds its whole answer first and writes it once (`emit`), at most one
    object per invocation, merging the reasons of several rules;
  - exits 0 always, also on its own errors, with nothing on stdout (`guarded`):
    a broken hook must never lock a session.

`normalize` turns a payload into a `CodexCall`: Codex `Bash` -> tool "shell"
(command text is the raw command, not the pwsh wrapper), `apply_patch` ->
tool "patch" with the edited/deleted paths parsed out of the patch text and
the patch's exit code out of `tool_response` (a string), and
`collaborationspawn_agent` -> tool "spawn" (its `message` is encrypted, so
subagent prompts are not inspectable).  Subagent tool calls carry `agent_id`.
The Claude classifiers still get `tool_name="Bash"` (they gate on it).

Per-session state (stop latch, session start time) lives in
`$PDF_EDITOR_CODEX_STATE_DIR` (default `<tempdir>/pdf_editor_codex`), one JSON
file per Codex session_id; subagents share their parent's session_id.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

CLAUDE_SHELL_TOOL = "Bash"  # what agent_prompt_guard / shell_edit_guard accept
TOOL_KINDS = {"Bash": "shell", "apply_patch": "patch", "collaborationspawn_agent": "spawn"}
PATCH_LINE_RE = re.compile(r"^\*\*\* (Add File|Update File|Move to|Delete File): *(.+?) *$", re.M)
PATCH_EXIT_RE = re.compile(r"^Exit code: *(-?\d+)", re.M)
STATE_MAX_AGE = 7 * 86400.0


@dataclass
class CodexCall:
    event: str
    payload: dict
    tool_name: str = ""
    tool: str = ""  # "shell" | "patch" | "spawn" | "" (anything else)
    command: str = ""
    cwd: str = ""
    session_id: str = ""
    in_subagent: bool = False
    edited: list[str] = field(default_factory=list)  # raw paths: Add File, Update File, Move to
    deleted: list[str] = field(default_factory=list)
    patch_exit: int | None = None


def read_payload() -> dict | None:
    """The hook payload, or None when stdin is not a JSON object."""
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_patch(text: str) -> tuple[list[str], list[str]]:
    """(edited, deleted) raw paths named by an apply_patch text."""
    edited: list[str] = []
    deleted: list[str] = []
    for kind, raw in PATCH_LINE_RE.findall(text):
        (deleted if kind == "Delete File" else edited).append(raw)
    return edited, deleted


def normalize(event: str, payload: dict) -> CodexCall:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("command")
        if isinstance(raw, list):  # never seen in 0.166; an argv list joins into one line
            raw = " ".join(str(x) for x in raw)
        command = raw if isinstance(raw, str) else ""
    call = CodexCall(
        event=event,
        payload=payload,
        tool_name=tool_name,
        tool=TOOL_KINDS.get(tool_name, ""),
        command=command,
        cwd=str(payload.get("cwd") or os.getcwd()),
        session_id=str(payload.get("session_id") or ""),
        in_subagent=bool(payload.get("agent_id")),
    )
    if call.tool == "patch":
        call.edited, call.deleted = parse_patch(command)
        response = payload.get("tool_response")
        m = PATCH_EXIT_RE.search(response) if isinstance(response, str) else None
        call.patch_exit = int(m.group(1)) if m else None
    return call


# --------------------------------------------------------------------------- paths


def project_root(cwd: str | Path) -> Path:
    """The git toplevel of *cwd*, or *cwd* itself outside a git tree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, timeout=10
        )
        if result.returncode == 0:
            top = result.stdout.decode("utf-8", "replace").strip()
            if top:
                return Path(top).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(cwd).resolve()


def inside(path: Path, root: Path) -> bool:
    p, r = os.path.normcase(str(path)), os.path.normcase(str(root)).rstrip("\\/")
    return p.startswith(r + os.sep) or p.startswith(r + "/")


def resolve_in_project(raw: str, cwd: str, root: Path) -> Path | None:
    """*raw* (absolute, or relative to the session cwd) when it lies inside *root*."""
    raw = raw.strip().strip("\"'")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if inside(path, root) else None


# --------------------------------------------------------------------------- responders


def deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def block(reason: str) -> dict:
    """PostToolUse: the tool ran, R is reported as its failure.  Stop/SubagentStop: resume the turn once."""
    return {"decision": "block", "reason": reason}


def context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def emit(obj: dict | None) -> None:
    if not obj:
        return
    # ASCII-only JSON: the hook's stdout is a pipe whose encoding Windows picks.
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=True).encode("ascii") + b"\n")
    sys.stdout.flush()


def guarded(main: Callable[[list[str]], dict | None], argv: list[str]) -> int:
    """Run *main*, write its answer, exit 0 whatever happens (Codex ignores exit codes,
    so an error must never leave a half-written answer or a non-zero code behind)."""
    try:
        out = main(argv)
    except BaseException as exc:  # noqa: BLE001 - fail open on anything, KeyboardInterrupt included
        try:
            print(f"codex_hook: {exc.__class__.__name__}: {exc} -- this call was NOT checked.", file=sys.stderr)
        except Exception:
            pass
        return 0
    try:
        emit(out)
    except Exception:
        pass
    return 0


# --------------------------------------------------------------------------- session state


def state_dir() -> Path:
    override = os.environ.get("PDF_EDITOR_CODEX_STATE_DIR")
    return Path(override) if override else Path(tempfile.gettempdir()) / "pdf_editor_codex"


def _state_path(session_id: str) -> Path:
    return state_dir() / (re.sub(r"[^\w.-]", "_", session_id or "nosession") + ".json")


def load_state(session_id: str) -> dict:
    try:
        data = json.loads(_state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(session_id: str, data: dict) -> None:
    path = _state_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # no state only means the latch / Done gate see less


def session_state(session_id: str) -> dict:
    """The session's state, recording its start time the first time any hook sees it."""
    data = load_state(session_id)
    if not isinstance(data.get("started"), (int, float)):
        data["started"] = time.time()
        save_state(session_id, data)
    return data


def prune_states(now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        for old in state_dir().glob("*.json"):
            try:
                if now - old.stat().st_mtime > STATE_MAX_AGE:
                    old.unlink()
            except OSError:
                pass
    except OSError:
        pass
