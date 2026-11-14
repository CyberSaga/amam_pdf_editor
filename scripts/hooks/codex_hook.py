#!/usr/bin/env python3
"""Adapt applicable project hooks to Codex lifecycle event payloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import _hookkit
import agent_prompt_guard
import pre_paste_gate
import retry_cap_footer
import ruff_on_edit
import shell_edit_guard
import stop_latch

ROOT = Path(__file__).resolve().parents[2]


def _state_path(payload: dict) -> Path | None:
    session = payload.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[\w-]{1,128}", session):
        return None
    directory = Path(os.environ.get("PDF_EDITOR_CODEX_STATE_DIR", Path(tempfile.gettempdir()) / "pdf_editor_codex"))
    return directory / (session + ".json")


def _prompt(payload: dict) -> dict:
    text = str(payload.get("prompt") or "").strip()
    if not text or _hookkit.is_slash(text) or _hookkit.is_harness_text(text):
        return {}
    path = _state_path(payload)
    if path is not None:
        exists = path.exists()
        state = {"armed": exists and stop_latch.is_stop_phrase(text)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    if pre_paste_gate.OWNER_CUE_RE.search(text):
        dirty = pre_paste_gate.dirty_files(payload.get("cwd") or ROOT)
        if dirty:
            listing = pre_paste_gate._listing(dirty)
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
                    "PRE-PASTE GATE: tracked files differ from HEAD:\n" + listing +
                    "\nThe batch validator will refuse the paste. Warn the user; do not commit automatically."}}
    return {}


def _pre(payload: dict) -> dict:
    name = payload.get("tool_name")
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        return {}
    reasons = []
    if name == "Bash":
        command = data.get("command")
        if not isinstance(command, str):
            return {}
        reasons.extend(v.rule() for v in agent_prompt_guard.violations("Bash", data, in_subagent=True))
        reasons.extend(v.snippet for v in shell_edit_guard.violations("Bash", command, str(payload.get("cwd") or ROOT)))
        masked = agent_prompt_guard._shell_text(command)[0]
        for match in re.finditer(r"\bruff(?:\.exe)?\s+format\b([^;&|\r\n]*)", masked, re.I):
            if not re.search(r"(?:^|\s)--(?:check|diff)(?:\s|$)", match.group(1)):
                reasons.append("ruff format is prohibited by CLAUDE.md; use --check or --diff.")
                break
        ruff_on_edit.record_start(payload)
    elif name in ("spawn_agent", "collaborationspawn_agent"):
        path = _state_path(payload)
        if path is not None and path.exists() and json.loads(path.read_text(encoding="utf-8")).get("armed"):
            reasons.append("Stop latch armed by the user's latest instruction.")
    if reasons:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "\n".join(reasons)}}
    return {}


def _post(payload: dict) -> dict:
    data = payload.get("tool_input")
    if payload.get("tool_name") == "Bash":
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/hooks/ruff_on_edit.py")],
            input=json.dumps(payload), capture_output=True, text=True, timeout=45,
        )
        if result.returncode:
            return {"decision": "block", "reason": result.stderr.strip() or "Ruff hook failed."}
        return {}
    if payload.get("tool_name") != "apply_patch" or not isinstance(data, dict):
        return {}
    command = data.get("command")
    if not isinstance(command, str):
        return {}
    paths = []
    cwd = Path(str(payload.get("cwd") or ROOT))
    for raw in re.findall(r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", command, re.MULTILINE):
        path = (cwd / raw.strip()).resolve()
        if path.is_relative_to(ROOT) and path.suffix == ".py" and path.is_file():
            paths.append(str(path))
    ruff = ruff_on_edit._resolve_ruff()
    if not paths:
        return {}
    if not ruff:
        return {"decision": "block", "reason": "Ruff is unavailable; edited Python files were not checked."}
    result = subprocess.run([ruff, "check", "--quiet", "--force-exclude", *paths], capture_output=True, text=True, timeout=30, cwd=ROOT)
    if result.returncode:
        return {"decision": "block", "reason": (result.stdout or result.stderr or "Ruff check failed.")[:8000]}
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        if event == "PreToolUse":
            output = _pre(payload)
        elif event == "PostToolUse":
            output = _post(payload)
        elif event == "UserPromptSubmit":
            output = _prompt(payload)
        elif event == "SubagentStart":
            output = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": retry_cap_footer.FOOTER}}
        elif event == "Stop":
            reason = pre_paste_gate.stop_decision(str(payload.get("last_assistant_message") or ""), bool(payload.get("stop_hook_active")), pre_paste_gate.dirty_files(payload.get("cwd") or ROOT))
            output = {"decision": "block", "reason": reason} if reason else {}
        else:
            output = {}
        if output:
            print(json.dumps(output, ensure_ascii=True))
    except Exception as exc:
        print(f"codex_hook: {type(exc).__name__}; event not checked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
