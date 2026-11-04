#!/usr/bin/env python3
"""PreToolUse hook (Agent|Workflow|Bash|PowerShell): the test-command rules as a refusal.

CLAUDE.md "Commands": never bare `pytest` (system Python masks runtime-only
bugs), the whole suite only through `scripts/run_suite.py` (a hang inside one
pytest process cannot be ended from inside it), and subagent prompts never ask
for process kills (memory: subagent prompts forbid process kills).  Memory kept
these rules only while someone remembered them; this hook denies the tool call
instead.

Precision: only command position counts (line start, after a shell operator or
a backtick, or the quoted command of `-c`); quoted strings (grep patterns, sed
scripts, awk programs), heredoc bodies, `pytest.raises`, placeholders such as
`<one file>` and `$PY` bound to the venv in the same command all pass.  Replayed
over 37k historical tool calls before registration (2026-11-04); what remained
were real violations (whole-suite-in-one-process gates, bare pytest in lane
prompts).

Scope: Bash/PowerShell commands (main thread and subagents), Agent prompts and
Workflow scripts/args.  Process kills are denied in agent prompts and in
subagent shell calls; the main thread may still end a stuck process.

Answers `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}` on a
violation, nothing when clean, and fails OPEN (exit 1, stderr) on a payload it
cannot read.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

import _hookkit as kit

HOOK = "agent_prompt_guard"

# Command position: line start, after a shell operator or a backtick, or the quoted
# command of `-c` / `/c` / `-Command`.  Optionally `<runner> [-flags] -m` before pytest.
# `pytest.` (attribute), `pytest,` and `pytest)` are prose/Python, not commands.
PYTEST_RE = re.compile(
    r"""(?:^|[;&|(`]|\$\s|\bthen\s|\bdo\s|(?:-l?c|/[cC]|-Command)\s+["'])\s*"""
    r"""(?P<runner>(?:"[^"\n]*"|'[^'\n]*'|[^\s"'`;&|()]+)\s+(?:-[\w.=-]+\s+)*-m\s+)?"""
    r"""pytest\b(?![.,)])(?P<args>(?:[^\n`;&|)"']|"[^"\n]*"|'[^'\n]*')*)""",
    re.M,
)
SUITE_DIR_RE = re.compile(r"""^\.?[/\\]?test_scripts[/\\]*$""")
# `$PY`, `"$PY"`, `${PY}`, `%PY%` or a bare placeholder like `PY`: the interpreter is a variable.
VAR_RUNNER_RE = re.compile(r"""^["']?\$\{?(\w+)\}?["']?$|^%(\w+)%$|^([A-Z][A-Z0-9_]*)$""")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>|\.\.\.|\$\{?\w+\}?|%\w+%|\*")
PROSE_TOKEN_RE = re.compile(r"^[A-Za-z][a-z]+$")  # `pytest lock`, `pytest is slow`
HEREDOC_RE = re.compile(
    r"""<<-?\s*(['"]?)(\w+)\1[^\n]*\n.*?(?:\n\s*\2\s*$|\Z)|@(['"])\s*\n.*?\n\s*\3@""",
    re.S | re.M,
)
VALUE_FLAGS = {
    "-k", "-m", "-p", "-o", "-W", "-c", "-n", "--tb", "--rootdir", "--confcutdir", "--basetemp",
    "--junitxml", "--junit-xml", "--deselect", "--ignore", "--maxfail", "--durations", "--timeout",
}
COMMAND_ARG_FLAGS = ("-c", "-lc", "/c", "/C", "-Command", "-command", "-e")
KILL_RE = re.compile(
    r"""(?:^|[;&|(`]|[,:]\s|\$\s|\bthen\s|\bdo\s|\brun\s)\s*"""
    r"""(?P<cmd>taskkill\b|pkill\b|killall\b|Stop-Process\b|kill\s+-(?:9|KILL|TERM|\d+)\b)""",
    re.I | re.M,
)
NEGATION_RE = re.compile(
    r"\b(?:never|not|don'?t|dont|do\s+not|no|forbid(?:den)?|without|avoid|must\s+not)\b"
    r"|禁止|不要|不得|不可|不准|別",
    re.I,
)
SHELL_TOOLS = ("Bash", "PowerShell")
PROMPT_TOOLS = ("Agent", "Workflow")


@dataclass(frozen=True)
class Violation:
    kind: str
    snippet: str

    def rule(self) -> str:
        return RULES[self.kind]


RULES = {
    "bare-pytest": "never bare `pytest`: use `.venv\\Scripts\\python.exe -m pytest <file>` (system Python has a different PyMuPDF)",
    "system-python": "pytest must run on the repo venv: `.venv\\Scripts\\python.exe -m pytest <file>`",
    "whole-suite": "the whole suite runs only through `.venv\\Scripts\\python.exe scripts/run_suite.py` (never `pytest test_scripts/` or pytest without a file: a hang there cannot be ended from inside)",
    "process-kill": "no taskkill/pkill/Stop-Process in agent work: one pytest at a time, foreground, output to a file; run_suite.py owns the kills",
}


# --------------------------------------------------------------------------- text shaping


def _strip_heredocs(text: str) -> str:
    """Drop heredoc / here-string bodies (file contents written through the shell)."""
    return HEREDOC_RE.sub(lambda m: m.group(0).split("\n", 1)[0] + "\n", text)


def _mask_quotes(text: str, keep_command_args: bool) -> str:
    """Replace the inside of quoted strings with `_` (grep patterns, sed scripts, awk
    programs are data, not commands).  With *keep_command_args*, the quoted string
    right after `-c` / `/c` / `-Command` is kept: that one IS a command."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch not in "\"'":
            i += 1
            continue
        before = text[:i].rstrip()
        keep = keep_command_args and any(before.endswith(flag) for flag in COMMAND_ARG_FLAGS)
        j = i + 1
        while j < n and text[j] != ch and text[j] != "\n":
            if ch == '"' and text[j] == "\\" and j + 1 < n:
                j += 1
            j += 1
        if not keep:
            for k in range(i + 1, min(j, n)):
                if text[k] != "\n":
                    out[k] = "_"
        i = j + 1
    return "".join(out)


def _shell_text(command: str) -> tuple[str, str]:
    """(text for the pytest rule, text for the kill rule) of a shell command."""
    base = _strip_heredocs(command)
    return _mask_quotes(base, keep_command_args=True), _mask_quotes(base, keep_command_args=False)


# --------------------------------------------------------------------------- pytest rule


def _interpreter(runner: str) -> str:
    """The interpreter token of `<runner> [-flags] -m` (quoted path kept whole)."""
    runner = runner.strip()
    if runner[:1] in "\"'":
        end = runner.find(runner[0], 1)
        return runner[: end + 1] if end != -1 else runner
    return runner.split()[0] if runner.split() else runner


def _runner_kind(runner: str, text: str) -> str:
    """'venv' | 'system' | 'unknown' for the interpreter in front of `-m pytest`."""
    interp = _interpreter(runner)
    if ".venv" in interp:
        return "venv"
    m = VAR_RUNNER_RE.match(interp)
    if not m:
        return "system"
    name = next(g for g in m.groups() if g)
    assign = re.search(rf"(?m)(?:^|[;&|\s])(?:export\s+|set\s+|\$)?{re.escape(name)}\s*=\s*(\S+)", text)
    if assign is None:
        return "unknown"
    return "venv" if ".venv" in assign.group(1) else "system"


def _is_target(token: str) -> bool:
    t = token.strip("\"'")
    if not t or t.startswith("-") or t in (">", ">>", "<", "2>", "1>"):
        return False
    if re.fullmatch(r"_+", t):
        return True  # a masked quoted argument: a path, as far as this hook can tell
    return t.endswith(".py") or "::" in t or "test_scripts" in t or bool(PLACEHOLDER_RE.search(t))


def _targets(args: str) -> list[str]:
    out: list[str] = []
    prev = ""
    for token in args.split():
        if prev in VALUE_FLAGS:
            prev = token
            continue
        if _is_target(token):
            out.append(token.strip("\"'"))
        prev = token
    return out


def _pytest_violations(text: str, original: str | None = None, prose: bool = False) -> list[Violation]:
    """*text* may be the quote-masked command; *original* (same length) supplies the
    real runner so a quoted venv path or `"$PY"` is judged on its content.  With
    *prose* (agent prompts, workflow scripts) a match negated earlier on its line
    ("never `pytest test_scripts/`") is the rule being restated, not broken, and a
    variable runner (`${PY}`) is not judged."""
    source = original if original is not None else text
    out: list[Violation] = []
    for m in PYTEST_RE.finditer(text):
        runner = source[m.start("runner"):m.end("runner")].strip() if m.group("runner") else ""
        args = m.group("args") or ""
        tokens = args.split()
        if tokens and PROSE_TOKEN_RE.match(tokens[0].strip("\"'")):
            continue  # `pytest lock`, `pytest is slow`: words, not a command line
        if prose:
            line_start = text.rfind("\n", 0, m.start()) + 1
            if NEGATION_RE.search(text[line_start:m.start()]):
                continue
        snippet = (((runner + " ") if runner else "") + "pytest" + args.rstrip()).strip()[:160]
        if not runner:
            out.append(Violation("bare-pytest", snippet))
        elif _runner_kind(runner, source) == "system" and not (prose and VAR_RUNNER_RE.match(_interpreter(runner))):
            out.append(Violation("system-python", snippet))
        targets = _targets(args)
        placeholder = bool(PLACEHOLDER_RE.search(args))
        if (not targets and not placeholder) or any(SUITE_DIR_RE.match(t) for t in targets):
            out.append(Violation("whole-suite", snippet))
    return out


# --------------------------------------------------------------------------- kill rule


def _kill_violations(text: str, negation_lifts: bool) -> list[Violation]:
    out: list[Violation] = []
    for m in KILL_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start("cmd")) + 1
        before = text[line_start:m.start("cmd")]
        if negation_lifts and NEGATION_RE.search(before):
            continue
        line_end = text.find("\n", m.end())
        snippet = text[line_start:line_end if line_end != -1 else None].strip()[:160]
        out.append(Violation("process-kill", snippet))
    return out


# --------------------------------------------------------------------------- entry points


def _string_leaves(value: object) -> list[str]:
    """Every string inside a JSON-like value, one per line, so a command passed as
    a workflow arg is seen in command position."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _string_leaves(v)]
    if isinstance(value, list):
        return [s for v in value for s in _string_leaves(v)]
    return []


def _prompt_text(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Agent":
        return "\n".join(str(tool_input.get(k) or "") for k in ("prompt", "description"))
    parts = [str(tool_input.get("script") or "")]
    parts.extend(_string_leaves(tool_input.get("args")))
    return "\n".join(parts)


def violations(tool_name: str, tool_input: dict, in_subagent: bool = False) -> list[Violation]:
    """Every rule the tool call breaks (empty when clean)."""
    found: list[Violation] = []
    if tool_name in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        if command:
            pytest_text, kill_text = _shell_text(command)
            found = _pytest_violations(pytest_text, original=_strip_heredocs(command))
            if in_subagent:
                found += _kill_violations(kill_text, negation_lifts=False)
    elif tool_name in PROMPT_TOOLS:
        text = _prompt_text(tool_name, tool_input)
        if text.strip():
            found = _pytest_violations(text, prose=True) + _kill_violations(text, negation_lifts=True)
    seen: dict[str, Violation] = {}
    for v in found:
        seen.setdefault(v.kind, v)
    return list(seen.values())


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return kit.fail_open(HOOK, "hook input has no tool_input object")
    try:
        found = violations(tool_name, tool_input, in_subagent=kit.is_subagent(payload))
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    if not found:
        return 0
    lines = [f"{HOOK}: this {tool_name} call breaks the test-command rules (CLAUDE.md Commands):"]
    for v in found:
        lines.append(f"- {v.rule()}\n    offending: {v.snippet}")
    lines.append("Rewrite the command/prompt; the rules are not negotiable inside agents.")
    return kit.deny("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
