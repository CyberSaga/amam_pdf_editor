#!/usr/bin/env python3
"""PreToolUse hook (Bash|PowerShell): deny in-place shell edits of git-TRACKED files.

Denied shapes, when the resolved target is tracked by git (any extension):
  sed -i / --in-place, perl -pi / -i, `>` / `N>` / `&>` redirects, tee,
  Set-Content, Out-File, [IO.File]::WriteAll*.
Appends pass (`>>`, tee -a, Add-Content, Out-File -Append, AppendAll*): they
cannot mis-match or rewrite the file's line endings, plan logs are appended
this way all the time (about 60% of the replayed would-be denies), and a doubled
code append is caught by ruff_on_edit.py (F811).
Why: the shell cannot assert how many places an edit matched (a chained
`sed -i ... && cat > ... <<EOF` was dropped silently on 2026-10-22), and sed or
PowerShell rewrite this CRLF checkout to LF (2026-10-23: TODOS.md and
docs/PITFALLS.md came back LF while the lane reported them unchanged).  Lint
of shell-edited .py files is ruff_on_edit.py's job, not this hook's.

Allowed: untracked or scratch targets, read-only commands, programs that write
files themselves (build_pitfalls_index.py, ruff --fix, git), Python edit
scripts (`python - <<'EOF'`), heredoc bodies and quoted strings (data), and
any target it cannot resolve ($VAR, globs, find -exec, `cd "$TEMP"`): those
fail open.  Applies in the main thread and in subagents (both harms happened
in lanes).  Known gap: commands nested in `bash -c "..."` /
`powershell -Command "..."` are quoted data here and pass.

Tracked = `git -C <dir> ls-files --error-unmatch -- <name>` exits 0; git is
spawned only after a shape matched, and any git error allows.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import _hookkit as kit
from agent_prompt_guard import _mask_quotes, _strip_heredocs

HOOK = "shell_edit_guard"
SHELL_TOOLS = ("Bash", "PowerShell")

SEP_RE = re.compile(r"&&|\|\||[;|\n]")
# `>`/`>>` with an optional fd or `&`; not `2>&1`, `>&2`, `->`, `=>`, `>(...)`.
REDIR_RE = re.compile(r"(?<![<>=\-|])(?:\d|&)?>>?(?![>&=(])")
CD_RE = re.compile(r"^\s*(?:cd|pushd|Set-Location|sl)\b(?:\s+-(?:Literal)?Path\b)?", re.I)
IOFILE_RE = re.compile(
    r"""\[(?:System\.)?IO\.File\]::(?:WriteAll(?:Text|Lines|Bytes)|AppendAll(?:Text|Lines))\(\s*(['"])(.*?)\1""",
    re.I,
)
UNRESOLVABLE_RE = re.compile(r"[$%*?{}`<>()\[\]]")
GITBASH_DRIVE_RE = re.compile(r"^/([a-zA-Z])(?=/|$)")
PS_WRITERS = {"set-content", "out-file"}  # Add-Content only appends
PS_PATH_PARAMS = {"-path", "-filepath", "-literalpath", "-pspath"}
PS_SWITCHES = {"-force", "-nonewline", "-append", "-noclobber", "-passthru", "-whatif", "-confirm", "-asbytestream"}


@dataclass(frozen=True)
class Violation:
    kind: str
    target: str
    snippet: str


def _words(text: str) -> list[tuple[str, int]]:
    """Top-level words of one command segment with their offsets; quotes are
    stripped, backslashes kept (Windows paths), no escape processing."""
    out: list[tuple[str, int]] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        start, buf = i, []
        while i < n and not text[i].isspace():
            ch = text[i]
            if ch in "\"'":
                j = text.find(ch, i + 1)
                j = n if j < 0 else j
                buf.append(text[i + 1:j])
                i = j + 1
            else:
                buf.append(ch)
                i += 1
        out.append(("".join(buf), start))
    return out


def _word_at(text: str, pos: int) -> str:
    words = _words(text[pos:])
    return words[0][0] if words else ""


def _command_words(words: list[tuple[str, int]]) -> list[str]:
    """Drop leading `sudo`, `env` and VAR=value assignments."""
    tokens = [w for w, _ in words]
    while tokens and (tokens[0] in ("sudo", "env", "command", "exec") or re.match(r"^\w+=", tokens[0])):
        tokens.pop(0)
    return tokens


def _sed_files(args: list[str]) -> list[str] | None:
    """Files of an in-place sed, or None when it is not in place."""
    in_place = script_given = False
    files: list[str] = []
    skip = positional_only = False
    for tok in args:
        if skip:
            skip = False
            continue
        if positional_only or not tok.startswith("-") or tok == "-":
            if script_given:
                files.append(tok)
            else:
                script_given = True  # first positional is the script
            continue
        if tok == "--":
            positional_only = True
        elif tok.startswith("--in-place"):
            in_place = True
        elif tok.startswith(("--expression", "--file")):
            script_given = True
            skip = "=" not in tok
        elif tok.startswith("--"):
            continue
        else:
            for k, ch in enumerate(tok[1:], start=1):
                if ch == "i":
                    in_place = True
                    break  # the rest is the backup suffix
                if ch in "ef":
                    script_given = True
                    skip = k == len(tok) - 1
                    break
    return files if in_place else None


def _perl_files(args: list[str]) -> list[str] | None:
    in_place = has_e = False
    files: list[str] = []
    skip = False
    for tok in args:
        if skip:
            skip = False
            continue
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 1:
            letters = tok[1:]
            if "i" in letters.split(".", 1)[0]:
                in_place = True
            if letters.endswith(("e", "E")) and "." not in letters:
                has_e = True
                skip = True
            continue
        files.append(tok)
    if not in_place:
        return None
    return files if has_e else files[1:]


def _ps_target(args: list[str]) -> list[str]:
    explicit: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        low = tok.lower()
        if low.startswith("-") and len(low) > 1:
            if low in PS_PATH_PARAMS and i + 1 < len(args):
                explicit.append(args[i + 1])
                i += 2
                continue
            i += 1 if low in PS_SWITCHES else 2
            continue
        positional.append(tok)
        i += 1
    return explicit or positional[:1]


def _segments(command: str) -> list[tuple[str, str]]:
    """(original, quote-masked) slices of a command split at && || ; | newline."""
    base = _strip_heredocs(command)
    masked = _mask_quotes(base, keep_command_args=False)
    out: list[tuple[str, str]] = []
    start = 0
    for m in SEP_RE.finditer(masked):
        out.append((base[start:m.start()], masked[start:m.start()]))
        start = m.end()
    out.append((base[start:], masked[start:]))
    return out


def edit_targets(command: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """(kind, raw target word, cd words in effect) for every edit shape in the command."""
    found: list[tuple[str, str, tuple[str, ...]]] = []
    cds: tuple[str, ...] = ()
    for orig, masked in _segments(command):
        cd = CD_RE.match(masked)
        if cd:
            cds = (*cds, _word_at(orig, cd.end()))
            continue
        for m in REDIR_RE.finditer(masked):
            if ">>" in m.group(0):
                continue  # appends cannot mis-match or rewrite line endings
            word = _word_at(orig, m.end())
            if word:
                found.append(("redirect", word, cds))
        for m in IOFILE_RE.finditer(orig):
            if masked[m.start()] == "[" and "::Write" in m.group(0):
                found.append(("[IO.File]::Write", m.group(2), cds))
        # strip redirections before reading the command's own arguments
        cut = REDIR_RE.search(masked)
        tokens = _command_words(_words(orig[: cut.start()] if cut else orig))
        if not tokens:
            continue
        name = re.split(r"[/\\]", tokens[0])[-1].lower().removesuffix(".exe")
        files: list[str] | None = None
        kind = name
        if name in ("sed", "gsed"):
            files, kind = _sed_files(tokens[1:]), "sed -i"
        elif name == "perl":
            files, kind = _perl_files(tokens[1:]), "perl -i"
        elif name == "tee":
            if not any(t in ("-a", "--append") for t in tokens[1:]):
                files = [t for t in tokens[1:] if not t.startswith("-")]
        elif name in PS_WRITERS:
            if not any(t.lower() == "-append" for t in tokens[1:]):
                files, kind = _ps_target(tokens[1:]), tokens[0]
        for word in files or []:
            found.append((kind, word, cds))
    return found


def _resolve(word: str, base: Path | None) -> Path | None:
    if not word or UNRESOLVABLE_RE.search(word):
        return None
    if os.name == "nt":
        word = GITBASH_DRIVE_RE.sub(lambda m: m.group(1).upper() + ":", word)
    path = Path(word).expanduser()
    if path.is_absolute():
        return path
    return base / path if base is not None else None


def git_tracked(path: Path) -> bool:
    parent = path.parent
    if not parent.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(parent), "ls-files", "--error-unmatch", "--", path.name],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def violations(
    tool_name: str,
    command: str,
    cwd: str,
    is_tracked: Callable[[Path], bool] = git_tracked,
) -> list[Violation]:
    if tool_name not in SHELL_TOOLS or not command:
        return []
    out: list[Violation] = []
    for kind, word, cds in edit_targets(command):
        base: Path | None = Path(cwd)
        for cd in cds:
            base = _resolve(cd, base) if cd and cd != "-" else None
        target = _resolve(word, base)
        if target is not None and is_tracked(target):
            out.append(Violation(kind, word, f"{kind} {word}"))
    return out


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    tool_name = str(payload.get("tool_name") or "")
    if tool_name not in SHELL_TOOLS:
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return kit.fail_open(HOOK, "hook input has no tool_input object")
    try:
        found = violations(tool_name, str(tool_input.get("command") or ""), str(payload.get("cwd") or os.getcwd()))
    except Exception as exc:
        return kit.fail_open(HOOK, f"{exc.__class__.__name__}: {exc}")
    if not found:
        return 0
    lines = [f"{HOOK}: this {tool_name} call edits a git-tracked file in place through the shell:"]
    lines += [f"- {v.snippet}" for v in found]
    lines.append(
        "The shell cannot assert how many places matched (a chained sed -i was dropped silently on 2026-10-22), "
        "and sed/PowerShell rewrite this CRLF checkout to LF (2026-10-23: TODOS.md and docs/PITFALLS.md came back "
        "LF while reported unchanged). Use the Edit tool (Read first), or stay in the shell with `python - <<'EOF'` "
        "that reads with open(p, encoding='utf-8', newline=''), asserts s.count(old) == 1 and writes back with "
        "newline=''. Untracked and scratch files are not affected."
    )
    return kit.deny("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
