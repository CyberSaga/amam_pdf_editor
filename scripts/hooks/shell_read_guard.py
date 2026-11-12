"""Rule library (Bash|PowerShell): flag reading git-TRACKED files through the shell.

Not a hook by itself: `shell_edit_guard.main()` calls `read_violations` and denies
with `DENY_ADVICE` (Claude only; `codex_hook.py` imports `shell_edit_guard.violations`,
which does not include this rule, because Codex reads through the shell by design).
No stdin handling, no main().

Why: reading files with `sed -n`, `cat`, `head`, `tail` or `Get-Content` produced
65 % of the Bash result characters in the 2026-11-04..11 transcripts, and a shell
read does not count as a Read, so the next Edit fails with "File has not been read
yet" (all 15 such errors in that window).  The Read tool (offset/limit) does the
same job.  Replayed over 2,319 historical shell calls before wiring: 322 denied
(1.9 M result chars of volume covered, not tokens saved: Read returns the same
lines), the largest 70 of the first replay reviewed, none a false deny.

Deny set, per statement (split at && || ; newline), when ALL hold:
  1. its first pipeline stage is a reader: cat, nl, head, tail, more, less,
     get-content / gc, type, or `sed -n` with only numeric print ranges
     (`10,40p;50p`);
  2. it has at least one file operand, and every operand resolves and is tracked
     by git (any checkout or worktree);
  3. every later stage is head, tail, nl, select-object, cat (bare or -n) or
     `sed -n` with numeric ranges (a `cut -c1-N` stage allows the call: Read
     cannot cap line width, and TODOS/PITFALLS lines run to ~1.5k chars);
  4. there is no `>` / `>>` redirect (`2>&1` is not a file redirect).

Allowed (fail open): git show|diff|log|blame, untracked files, wc, Select-String,
pipes into grep/awk/jq/python/wc, `(Get-Content F).Count`, `cat a b > c`,
head/tail -c, cat -A / -v, sed -n l, od, xxd, binary suffixes (.pdf .png ...),
heredoc bodies and quoted strings (data), unresolvable operands ($f, globs), tool
names other than Bash/PowerShell, an empty command.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_prompt_guard import _mask_quotes, _strip_heredocs
from shell_edit_guard import (
    CD_RE,
    REDIR_RE,
    SHELL_TOOLS,
    _command_words,
    _resolve,
    _word_at,
    _words,
    git_tracked,
)

DENY_ADVICE = (
    "Use the Read tool with offset/limit (find the lines with Grep -n first); a shell read does not count as a "
    "Read for Edit. Where lines are very long (TODOS.md, docs/PITFALLS.md) a character-capped read is allowed: "
    "`sed -n 'A,Bp' FILE | cut -c1-300`. Untracked files (logs, test output, scratch) are not affected."
)

STATEMENT_RE = re.compile(r"&&|\|\||;|\n")
STAGE_RE = re.compile(r"(?<!\|)\|(?!\|)")
FD_DUP_RE = re.compile(r"^\d*>&\d*$")  # `2>&1` is not an operand
SED_SCRIPT_RE = re.compile(r"^\d+(,\d+)?p(;\d+(,\d+)?p)*$")
BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".db", ".pyc", ".whl", ".exe", ".dll"}
SIMPLE_READERS = {"cat", "nl", "more", "less", "type"}
PS_READERS = {"get-content", "gc"}
LATER_STAGES = {"head", "tail", "nl", "select-object"}  # not `cut`: a character cap is the allowed escape
PS_VALUE_PARAMS = {
    "-tail", "-totalcount", "-first", "-head", "-last", "-skip", "-encoding", "-readcount",
    "-delimiter", "-filter", "-include", "-exclude", "-stream",
}
PS_PATH_PARAMS = {"-path", "-literalpath"}
SNIPPET_MAX = 160


@dataclass(frozen=True)
class Violation:
    kind: str
    target: str
    snippet: str


def _statements(command: str) -> list[tuple[str, str]]:
    """(original, quote-masked) statements, heredoc bodies stripped."""
    base = _strip_heredocs(command)
    masked = _mask_quotes(base, keep_command_args=False)
    out: list[tuple[str, str]] = []
    start = 0
    for m in STATEMENT_RE.finditer(masked):
        out.append((base[start:m.start()], masked[start:m.start()]))
        start = m.end()
    out.append((base[start:], masked[start:]))
    return out


def _stages(orig: str, masked: str) -> list[list[str]]:
    """Command words of each pipeline stage of one statement."""
    out: list[list[str]] = []
    start = 0
    bounds = [(m.start(), m.end()) for m in STAGE_RE.finditer(masked)]
    for s, e in [*bounds, (len(masked), len(masked))]:
        words = _command_words(_words(orig[start:s]))
        out.append([w for w in words if not FD_DUP_RE.match(w)])
        start = e
    return out


def _name(token: str) -> str:
    return re.split(r"[/\\]", token)[-1].removesuffix(".exe").removesuffix(".EXE")


def _sed_parts(args: list[str]) -> tuple[list[str], bool] | None:
    """(operands, numeric) of a `sed -n SCRIPT FILES...`, or None when not a sed -n."""
    if "-n" not in args:
        return None
    rest = [a for a in args if a != "-n"]
    if not rest or rest[0].startswith("-"):
        return [], False
    return rest[1:], bool(SED_SCRIPT_RE.match(rest[0]))


def _head_tail_operands(args: list[str]) -> list[str] | None:
    """File operands of head/tail; None for byte mode (-c / --bytes)."""
    files: list[str] = []
    skip = False
    for tok in args:
        if skip:
            skip = False
            continue
        if tok in ("-c", "--bytes") or tok.startswith(("-c", "--bytes=")):
            return None
        if tok in ("-n", "--lines"):
            skip = True
        elif tok.startswith("-") and tok != "-":
            continue
        else:
            files.append(tok)
    return files


def _get_content_operands(args: list[str]) -> list[str]:
    explicit: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        low = tok.lower()
        if low in PS_PATH_PARAMS:
            if i + 1 < len(args):
                explicit.append(args[i + 1])
            i += 2
            continue
        if low in PS_VALUE_PARAMS:
            i += 2
            continue
        if tok.startswith("-") and len(tok) > 1 and not tok[1].isdigit():
            i += 1
            continue
        positional.append(tok)
        i += 1
    return explicit or positional[:1]


def _reader_operands(tokens: list[str]) -> tuple[str, list[str]] | None:
    """(kind, operands) when *tokens* is a first-stage reader, else None."""
    if not tokens:
        return None
    name = _name(tokens[0])
    low = name.lower()
    args = tokens[1:]
    if low in ("sed", "gsed"):
        parts = _sed_parts(args)
        if parts is None or not parts[1]:
            return None
        return "sed -n", parts[0]
    if low == "cat":
        flags = [a for a in args if a.startswith("-") and a != "-"]
        if any(f != "-n" for f in flags):
            return None
        return name, [a for a in args if a not in flags]
    if low in SIMPLE_READERS:
        return name, [a for a in args if not a.startswith("-") or a == "-"]
    if low in ("head", "tail"):
        files = _head_tail_operands(args)
        return None if files is None else (name, files)
    if low in PS_READERS:
        return name, _get_content_operands(args)
    return None


def _later_stage_ok(tokens: list[str]) -> bool:
    if not tokens:
        return False
    low = _name(tokens[0]).lower()
    args = tokens[1:]
    if low == "cat":
        return all(a == "-n" for a in args if a.startswith("-"))
    if low in ("sed", "gsed"):
        parts = _sed_parts(args)
        return parts is not None and parts[1]
    return low in LATER_STAGES


def read_violations(
    tool_name: str,
    command: str,
    cwd: str,
    is_tracked: Callable[[Path], bool] = git_tracked,
) -> list[Violation]:
    if tool_name not in SHELL_TOOLS or not command:
        return []
    out: list[Violation] = []
    cds: tuple[str, ...] = ()
    for orig, masked in _statements(command):
        cd = CD_RE.match(masked)
        if cd:
            cds = (*cds, _word_at(orig, cd.end()))
            continue
        if REDIR_RE.search(masked):
            continue
        stages = _stages(orig, masked)
        reader = _reader_operands(stages[0])
        if reader is None or not reader[1]:
            continue
        if not all(_later_stage_ok(s) for s in stages[1:]):
            continue
        kind, operands = reader
        base: Path | None = Path(cwd)
        for c in cds:
            base = _resolve(c, base) if c and c != "-" else None
        paths = [_resolve(w, base) for w in operands]
        if any(p is None for p in paths):
            continue
        resolved = [p for p in paths if p is not None]
        if any(p.suffix.lower() in BINARY_SUFFIXES for p in resolved):
            continue
        if all(is_tracked(p) for p in resolved):
            out.append(Violation(kind, operands[0], orig.strip()[:SNIPPET_MAX]))
    return out
