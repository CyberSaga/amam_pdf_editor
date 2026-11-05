#!/usr/bin/env python3
"""Codex CLI hook dispatcher: the Claude hook rules of this directory, in Codex's contract.

Registered in .codex/hooks.json as `python scripts/hooks/codex_hook.py <Event>`
(the hook cwd is the project root; Codex sets no project-dir variable).
Codex ignores hook exit codes, so every rule answers with ONE stdout JSON
object (see _codexkit.py) and the process always exits 0.

PreToolUse
  Bash: agent_prompt_guard (bare / system-python / whole-suite pytest, process
    kills -- denied in the main thread too: Codex sessions run unattended),
    `ruff format` (the repo is not format-clean; `--check`/`--diff` pass) and
    shell_edit_guard (in-place shell edits of git-tracked files) -> one deny.
    A clean call is stamped for the PostToolUse ruff leg (ruff_on_edit).
  collaborationspawn_agent: deny while the stop latch is armed.
PostToolUse
  apply_patch: ruff on the .py files the patch added/updated/moved to (inside
    the project only; deletions and failed patches skipped) -> decision block
    with the findings (the patch stays applied; the model sees a failure).
  Bash: ruff on the .py files changed since the PreToolUse stamp -> same.
UserPromptSubmit: arms/lifts the stop latch (stop_latch.is_stop_phrase) and
  warns when the owner pastes into a dirty tree (pre_paste_gate) -> context.
Stop: pre_paste_gate + the Done gate (files this session changed) -> one
  block per stop (`stop_hook_active` lets the second stop through).
SubagentStart: the retry-cap footer (retry_cap_footer.FOOTER) as context; the
  spawn message is encrypted, so the Claude `updatedInput` rewrite cannot port.
SessionStart: rulebook pointer as context; prunes week-old state files.
Any other event, or a payload that is not a JSON object: no output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _codexkit as kit  # noqa: E402
import _hookkit as claude_kit  # noqa: E402
import agent_prompt_guard as guard  # noqa: E402
import pre_paste_gate as paste  # noqa: E402
import retry_cap_footer as footer  # noqa: E402
import ruff_on_edit as roe  # noqa: E402
import shell_edit_guard as edit_guard  # noqa: E402
import stop_latch as latch  # noqa: E402

HOOK = "codex_hook"
MTIME_SLACK = 1.0

RUFF_FORMAT_RE = re.compile(
    r"""(?:^|[;&|(`]|\bthen\s|\bdo\s)\s*"""
    r"""(?:(?:"[^"\n]*"|'[^'\n]*'|[^\s"'`;&|()]+)\s+(?:-[\w.=-]+\s+)*-m\s+)?"""
    r"""["']?(?:[^\s"'`;&|()]*[/\\])?ruff(?:\.exe)?["']?\s+format\b(?P<args>[^\n`;&|]*)""",
    re.M | re.I,
)
# Old-style typing in ADDED lines: an import of the names, `typing.X[`, or a bare `X[`
# in a file that imports X from typing (a bare `Optional[` in a string is not flagged).
TYPING_IMPORT_RE = re.compile(r"^\s*from\s+typing\s+import\s+[^\n#]*\b(?:List|Dict|Optional|Tuple|Set|Union)\b", re.M)
TYPING_ATTR_RE = re.compile(r"(?<![\w.])typing\.(?:List|Dict|Optional|Tuple|Set|Union)\[")
TYPING_BARE_RE = re.compile(r"(?<![\w.])(?:List|Dict|Optional|Tuple|Set|Union)\[")
BASICCONFIG_RE = re.compile(r"\blogging\.basicConfig\s*\(")
FUTURE_LINE = "from __future__ import annotations"
DONE_PATHSPEC = ("*.py", "TODOS.md", "docs/PITFALLS.md", "docs/PITFALLS_INDEX.md")

SESSION_POINTER = (
    "pdf_editor rules: AGENTS.md (auto-loaded) is the rulebook; CLAUDE.md is its source. "
    "Repo hooks (.codex/hooks.json, docs/codex/HOOKS.md) deny bare or non-.venv pytest, the whole suite "
    "in one pytest process (use scripts/run_suite.py), process kills, `ruff format`, in-place shell edits "
    "of git-tracked files (use apply_patch), and spawn_agent after a stop instruction; ruff findings in "
    "edited .py files come back as a failed tool call; a Stop with unfinished Done items is resumed once."
)


# --------------------------------------------------------------------------- PreToolUse


def _ruff_format_snippets(command: str) -> list[str]:
    out: list[str] = []
    for m in RUFF_FORMAT_RE.finditer(guard._strip_heredocs(command)):
        if re.search(r"--(?:check|diff)\b", m.group("args") or ""):
            continue
        out.append(m.group(0).strip()[:160])
    return out


def shell_violations(command: str, cwd: str) -> list[str]:
    """Reason blocks for every rule a Codex shell command breaks (empty when clean)."""
    blocks: list[str] = []
    found = guard.violations(kit.CLAUDE_SHELL_TOOL, {"command": command}, in_subagent=True)
    if found:
        lines = [f"{guard.HOOK}: this shell call breaks the test-command rules (CLAUDE.md Commands):"]
        lines += [f"- {v.rule()}\n    offending: {v.snippet}" for v in found]
        blocks.append("\n".join(lines))
    fmt = _ruff_format_snippets(command)
    if fmt:
        blocks.append(
            "ruff format: this repo is not `ruff format`-clean and must not be reformatted (CLAUDE.md Commands); "
            "use `ruff check` (`ruff format --check` / `--diff` are fine).\n    offending: " + fmt[0]
        )
    edits = edit_guard.violations(kit.CLAUDE_SHELL_TOOL, command, cwd)
    if edits:
        lines = [f"{edit_guard.HOOK}: this shell call edits a git-tracked file in place:"]
        lines += [f"- {v.snippet}" for v in edits]
        lines.append(
            "The shell cannot assert how many places matched, and sed/PowerShell rewrite this CRLF checkout to LF. "
            "Use apply_patch, or a Python script that reads with open(p, encoding='utf-8', newline=''), asserts "
            "s.count(old) == 1 and writes back with newline=''. Appends (>>, Add-Content) and untracked or "
            "scratch files are not affected."
        )
        blocks.append("\n".join(lines))
    return blocks


def _latch_reason(armed: dict) -> str:
    when = armed.get("ts")
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if isinstance(when, (int, float)) else "earlier"
    return (
        f"STOP LATCH ({HOOK}): the owner's latest message ({stamp}) is a stop instruction: "
        f"\"{str(armed.get('text') or '')[:160]}\". Stop means stop: finish the running gate in the foreground, "
        "report, then idle. No new spawn_agent until the owner sends a fresh go-ahead (their next non-stop "
        "message lifts this latch)."
    )


def pre_tool_use(call: kit.CodexCall, state: dict) -> dict | None:
    if call.tool == "shell" and call.command:
        blocks = shell_violations(call.command, call.cwd)
        if blocks:
            return kit.deny("\n\n".join(blocks) + "\nRewrite the command; these rules are not negotiable.")
        roe.record_start(call.payload)  # stamp for the PostToolUse ruff leg (writes a file, no output)
        return None
    if call.tool == "spawn":
        armed = state.get("latch")
        if isinstance(armed, dict):
            return kit.deny(_latch_reason(armed))
    return None


# --------------------------------------------------------------------------- PostToolUse: ruff


def _ruff_cmd() -> list[str] | None:
    found = roe._resolve_ruff()
    if found:
        return [found]
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    return None


def ruff_check(files: list[Path], root: Path) -> tuple[str | None, str | None]:
    """(findings, problem): findings when ruff flags the files, problem when ruff could not answer."""
    if not files:
        return None, None
    cmd = _ruff_cmd()
    if cmd is None:
        return None, "ruff not found (.venv missing and not on PATH)"
    try:
        result = subprocess.run(
            [*cmd, "check", "--quiet", "--force-exclude", *map(str, files)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=str(root),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"failed to run ruff ({exc.__class__.__name__})"
    if result.returncode == 0:
        return None, None
    if result.returncode == 1 and result.stdout.strip():
        return result.stdout.strip(), None
    return None, f"ruff exited {result.returncode} without findings: {(result.stderr or result.stdout).strip()[:400]}"


def _patch_py_files(call: kit.CodexCall, root: Path) -> list[Path]:
    out: list[Path] = []
    for raw in call.edited:
        path = kit.resolve_in_project(raw, call.cwd, root)
        if path is not None and path.suffix == ".py" and path.is_file() and path not in out:
            out.append(path)
    return out


def post_tool_use(call: kit.CodexCall, state: dict) -> dict | None:
    if call.tool == "patch":
        if call.patch_exit not in (None, 0):
            return None  # the patch did not apply; nothing changed
        root = kit.project_root(call.cwd)
        files = _patch_py_files(call, root)
        what = "this apply_patch"
    elif call.tool == "shell":
        files = roe.shell_changed_files(call.payload)
        root = kit.project_root(call.cwd)
        what = "this shell call"
    else:
        return None
    findings, problem = ruff_check(files, root)
    if findings:
        return kit.block(f"ruff findings in .py files changed by {what} (fix them now):\n{findings}")
    if problem:
        return kit.context("PostToolUse", f"ruff_on_edit ({HOOK}): {problem} -- the .py files {what} changed were NOT lint-checked.")
    return None


# --------------------------------------------------------------------------- UserPromptSubmit


def user_prompt_submit(call: kit.CodexCall, state: dict) -> dict | None:
    if call.in_subagent:
        return None
    prompt = str(call.payload.get("prompt") or "").strip()
    if not prompt or claude_kit.is_harness_text(prompt) or claude_kit.is_slash(prompt):
        return None
    notes: list[str] = []
    # The session's first prompt is the brief (one prompt per `codex exec`): nothing runs yet to
    # stop, and brief rules ("do not run more than one pytest", "遇到卡住就停下來回報") read as
    # stop phrases.  Only a later prompt arms the latch.
    earlier = state.get("prompts")
    earlier = earlier if isinstance(earlier, int) else 0
    state["prompts"] = earlier + 1
    kit.save_state(call.session_id, state)
    if earlier and latch.is_stop_phrase(prompt):
        state["latch"] = {"text": latch.instruction_text(prompt)[:400], "ts": time.time()}
        kit.save_state(call.session_id, state)
        notes.append(
            "STOP LATCH armed by this message: finish the running gate in the foreground, report, idle. "
            "spawn_agent calls are denied until the owner's next non-stop message."
        )
    elif state.pop("latch", None) is not None:
        kit.save_state(call.session_id, state)
    if paste.OWNER_CUE_RE.search(prompt):
        dirty = paste.dirty_files(call.cwd)
        if dirty:
            notes.append(
                f"PRE-PASTE GATE ({paste.HOOK}): the owner is pasting or about to, but tracked files differ from "
                f"HEAD (git diff HEAD --name-status):\n{paste._listing(dirty)}\nThe batch validator will refuse the "
                "paste. Say this first and what to do; do not commit on your own."
            )
    return kit.context("UserPromptSubmit", "\n\n".join(notes)) if notes else None


# --------------------------------------------------------------------------- Stop: Done gate


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None


def session_changes(root: Path, since: float) -> dict[str, str]:
    """{posix relpath: porcelain code} of the Done-relevant files that differ from HEAD
    (untracked included) and were modified at or after *since* (this session)."""
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *DONE_PATHSPEC)
    if out is None:
        return {}
    changes: dict[str, str] = {}
    skip_next = False
    for entry in out.split("\0"):
        if skip_next:
            skip_next = False
            continue
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        if code[0] in "RC":
            skip_next = True
        path = root / rel
        try:
            if path.is_file() and path.stat().st_mtime >= since - MTIME_SLACK:
                changes[rel] = code
        except OSError:
            continue
    return changes


def _added_lines(root: Path, changes: dict[str, str], py: list[str]) -> dict[str, list[str]]:
    added: dict[str, list[str]] = {}
    tracked = [p for p in py if changes[p] != "??"]
    if tracked:
        diff = _git(root, "diff", "HEAD", "-U0", "--no-color", "--", *tracked) or ""
        current = ""
        for line in diff.splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else ""
            elif line.startswith("+") and current:
                added.setdefault(current, []).append(line[1:])
    for p in py:
        if changes[p] == "??":
            try:
                added[p] = (root / p).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                pass
    return added


def _old_typing(path: Path, added: str) -> bool:
    if TYPING_IMPORT_RE.search(added) or TYPING_ATTR_RE.search(added):
        return True
    if not TYPING_BARE_RE.search(added):
        return False
    try:
        return bool(TYPING_IMPORT_RE.search(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def done_problems(root: Path, since: float) -> list[str]:
    changes = session_changes(root, since)
    if not changes:
        return []
    py = sorted(p for p in changes if p.endswith(".py"))
    tests = [p for p in py if p.startswith("test_scripts/")]
    source = [p for p in py if not p.startswith("test_scripts/")]
    problems: list[str] = []
    if source and not tests:
        problems.append(
            f"- source .py changed ({', '.join(source[:6])}) but no test_scripts/*.py did: Done needs new tests "
            "for the change, written and shown failing first (red-light)."
        )
    if source and "TODOS.md" not in changes:
        problems.append("- TODOS.md was not updated (Done: TODOS.md current in the same change).")
    if "docs/PITFALLS.md" in changes and "docs/PITFALLS_INDEX.md" not in changes:
        problems.append(
            "- docs/PITFALLS.md changed but docs/PITFALLS_INDEX.md did not: regenerate it with "
            "`.venv\\Scripts\\python.exe scripts/build_pitfalls_index.py`."
        )
    for p in py:
        if changes[p] == "??" or "A" in changes[p]:
            try:
                text = (root / p).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if text.strip() and FUTURE_LINE not in text:
                problems.append(f"- {p} is a new module without `{FUTURE_LINE}` at the top.")
    added = _added_lines(root, changes, py)
    typing_hits = sorted(p for p, lines in added.items() if _old_typing(root / p, "\n".join(lines)))
    if typing_hits:
        problems.append(
            f"- typing.List/Dict/Optional/Tuple/Set/Union in added lines of {', '.join(typing_hits[:6])}: "
            "use list/dict/tuple/set and `X | None`."
        )
    basic = sorted(p for p, lines in added.items() if Path(p).name != "main.py" and BASICCONFIG_RE.search("\n".join(lines)))
    if basic:
        problems.append(f"- logging.basicConfig outside main.py in {', '.join(basic)}: use logging.getLogger(__name__).")
    findings, problem = ruff_check([root / p for p in py], root)
    if findings:
        problems.append(f"- ruff findings in the changed .py files:\n{findings}")
    elif problem:
        problems.append(f"- the changed .py files were NOT lint-checked: {problem}")
    return problems


def stop(call: kit.CodexCall, state: dict) -> dict | None:
    if call.in_subagent or call.payload.get("stop_hook_active"):
        return None
    reasons: list[str] = []
    message = str(call.payload.get("last_assistant_message") or "")
    if paste.has_paste_cue(message):
        decision = paste.stop_decision(message, False, paste.dirty_files(call.cwd))
        if decision:
            reasons.append(decision)
    started = state.get("started")
    # "Stop means stop": an armed latch silences the Done gate; and the gate resumes the turn once per
    # distinct problem list, not on every later Stop of the session.
    if isinstance(started, (int, float)) and not state.get("latch"):
        problems = done_problems(kit.project_root(call.cwd), float(started))
        digest = hashlib.sha256("\n".join(problems).encode("utf-8")).hexdigest()
        if problems and digest != state.get("done_gate_hash"):
            state["done_gate_hash"] = digest
            kit.save_state(call.session_id, state)
            reasons.append(
                f"DONE GATE ({HOOK}): files changed in this session do not meet CLAUDE.md Workflow \"Done means\":\n"
                + "\n".join(problems)
                + "\nFix them, or say in the final message why an item does not apply (this gate resumes the turn "
                "once per stop)."
            )
    return kit.block("\n\n".join(reasons)) if reasons else None


# --------------------------------------------------------------------------- Subagent / Session start


def subagent_start(call: kit.CodexCall, state: dict) -> dict | None:
    return kit.context("SubagentStart", footer.FOOTER)


def session_start(call: kit.CodexCall, state: dict) -> dict | None:
    kit.prune_states()
    return kit.context("SessionStart", SESSION_POINTER)


HANDLERS = {
    "PreToolUse": pre_tool_use,
    "PostToolUse": post_tool_use,
    "UserPromptSubmit": user_prompt_submit,
    "Stop": stop,
    "SubagentStart": subagent_start,
    "SessionStart": session_start,
}


def main(argv: list[str]) -> dict | None:
    handler = HANDLERS.get(argv[0]) if argv else None
    if handler is None:
        return None
    payload = kit.read_payload()
    if payload is None:
        return None
    call = kit.normalize(argv[0], payload)
    state = kit.session_state(call.session_id)
    return handler(call, state)


if __name__ == "__main__":
    sys.exit(kit.guarded(main, sys.argv[1:]))
