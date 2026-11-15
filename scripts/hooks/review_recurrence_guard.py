#!/usr/bin/env python3
"""PreToolUse hook (Write): a design-review record must answer "same class as last round?".

Applies to `plans/<name>-review-r<N>.md` with N >= 3 (not under plans/archive/).  The content
must hold exactly one `Recurrence` heading (level 2-4) and, inside that section, the list lines
  - This round: <mechanism of the round's worst findings>
  - Previous round: <mechanism of the previous round's>
  - Same mechanism: yes|no
and, when `yes`, `- Class fix: <a check that closes the class, or a probe>`.
Template placeholders (`<...>`) left in a value count as unfilled.
Why: in review rounds 12-16 of the paragraph-reflow design each round's major finding was a new
instance of one class (an enumerated list missing one more item) and each revision patched the
single instance; nothing forced the question "same mechanism as last round?".  The hook makes it
unavoidable and does not judge the answer.

Two legs, one text check (`check_record`):
  - the PreToolUse hook denies a `Write` that fails it (immediate feedback);
  - `scan` re-checks every record on disk of round >= LEGACY_BEFORE (called from the test suite),
    so the outcome is verified whichever tool wrote the file (Edit, shell, Python, Codex
    apply_patch).  Rounds 3-16 predate the rule and are exempt from the scan.
Every other call is allowed silently; a payload the hook cannot read fails open.
"""
from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path

import _hookkit as kit

HOOK = "review_recurrence_guard"
MIN_ROUND = 3
LEGACY_BEFORE = 17  # rounds 3-16 predate the rule: the on-disk scan skips them (owner 2026-11-15)
PATH_RE = re.compile(r"(?:^|/)plans/(?!archive/)[^/]+-review-r(\d+)\.md$", re.I)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
SECTION_RE = re.compile(r"^\s{0,3}#{2,4}\s+recurrence\s*$", re.I)
NEAR_RE = re.compile(r"^\s{0,3}#{1,6}\s.*recurrence", re.I)
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
ANSWER_RE = re.compile(r"^(yes|no)(?:\s*[.,;:(\-–—].*)?$", re.I)  # one answer, then punctuation + prose
RULE = (
    "two consecutive rounds on the same mechanism means stop patching instances: do not write the "
    "next revision; name the class, propose a check on the outcome instead of a longer list, or "
    "measure the unknown, and tell the owner"
)
TEMPLATE = (
    "## Recurrence\n"
    "- This round: <mechanism the worst findings belong to>\n"
    "- Previous round: <mechanism the previous round's worst findings belong to>\n"
    "- Same mechanism: yes|no\n"
    "- Class fix: <only when yes: a check that closes the whole class, or a probe that measures the unknown>"
)


def _outside_fences(content: str) -> list[str]:
    """The lines outside fenced code blocks (fence markers dropped).  A fence closes only on the
    same character, at least as long, with nothing after it (CommonMark)."""
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in content.splitlines():
        m = FENCE_RE.match(line)
        if m:
            marker, rest = m.group(1), m.group(2).strip()
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not rest:
                fence = None
            continue
        if fence is None:
            out.append(line)
    return out


def _sections(content: str) -> list[list[str]]:
    """The body of every `## Recurrence` section (outside fences), in order."""
    lines = _outside_fences(content)
    found: list[list[str]] = []
    for i, line in enumerate(lines):
        if SECTION_RE.match(line):
            body: list[str] = []
            for nxt in lines[i + 1:]:
                if HEADING_RE.match(nxt):
                    break
                body.append(nxt)
            found.append(body)
    return found


PLACEHOLDERS = tuple(re.findall(r"<[^>]+>", TEMPLATE))  # the template's own text, not any <...>


def _values(body: list[str], label: str) -> list[str]:
    """Text after every `- <label>:` line.  A list marker indented four or more columns is an
    indented code block, not a list item."""
    pat = re.compile(rf"^ {{0,3}}[-*] +{re.escape(label)}\s*:(.*)$", re.I)
    return [m.group(1).strip() for m in map(pat.match, body) if m]


def _unfilled(val: str) -> bool:
    return any(p in val for p in PLACEHOLDERS)


def _deny(problem: str) -> str:
    return f"Review record rejected: {problem}.\nRule: {RULE}.\nAdd this section:\n{TEMPLATE}"


def check_record(rel_path: str, content: str) -> str | None:
    """The reason a record at *rel_path* (repo-relative) is rejected, or None.  A pure text check,
    independent of which tool wrote the file."""
    m = PATH_RE.search(posixpath.normpath(rel_path.replace("\\", "/")))
    if not m or int(m.group(1)) < MIN_ROUND:
        return None
    content = content.lstrip("﻿")
    bodies = _sections(content)
    if not bodies:
        if any(NEAR_RE.match(line) for line in _outside_fences(content)):
            return _deny("the heading must read exactly `## Recurrence` (level 2-4, nothing else on the line)")
        return _deny("missing Recurrence section")
    if len(bodies) > 1:
        return _deny("more than one Recurrence section (exactly one is allowed)")
    body = bodies[0]
    got: dict[str, str] = {}
    for label in ("This round", "Previous round", "Same mechanism", "Class fix"):
        vals = _values(body, label)
        if len(vals) > 1:
            return _deny(f"Recurrence section: '- {label}:' appears more than once")
        if label == "Class fix":
            got[label] = vals[0] if vals else ""
            continue
        if not vals or not vals[0]:
            return _deny(f"Recurrence section: '- {label}:' is {'empty' if vals else 'missing'}")
        if _unfilled(vals[0]):
            return _deny(f"Recurrence section: '- {label}:' still holds the template placeholder")
        got[label] = vals[0]
    m_answer = ANSWER_RE.match(got["Same mechanism"])
    if not m_answer:
        return _deny(
            "Recurrence section: '- Same mechanism:' must be yes or no, optionally followed by "
            "punctuation and an explanation (e.g. `no (different list)`)"
        )
    if m_answer.group(1).lower() == "yes" and (not got["Class fix"] or _unfilled(got["Class fix"])):
        return _deny("Recurrence section: 'Same mechanism: yes' needs a filled '- Class fix:' line")
    return None


def decide(tool_name: str, file_path: str, content: str) -> str | None:
    """PreToolUse: the deny reason for a Write, or None to allow.  Edit and every other writer
    are caught afterwards by `scan`, which does not depend on the writing tool."""
    if tool_name != "Write":
        return None
    return check_record(file_path, content)


def scan(repo_root: Path) -> list[tuple[str, str]]:
    """(path, first line of reason) for every on-disk record of round >= LEGACY_BEFORE that fails."""
    bad: list[tuple[str, str]] = []
    for f in sorted((repo_root / "plans").glob("*.md")):
        m = PATH_RE.search(f"plans/{f.name}")  # the hook's own path rule: one definition of "a record"
        if not m or int(m.group(1)) < LEGACY_BEFORE:
            continue
        reason = check_record(f"plans/{f.name}", f.read_text(encoding="utf-8"))
        if reason:
            bad.append((f"plans/{f.name}", reason.splitlines()[0]))
    return bad


def main() -> int:
    payload = kit.read_payload()
    if payload is None:
        return kit.fail_open(HOOK, "hook input is not JSON")
    try:
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        path, content = tool_input.get("file_path"), tool_input.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return 0
        reason = decide(str(payload.get("tool_name") or ""), path, content)
    except Exception as exc:  # fail open: a broken hook must not lock the session
        return kit.fail_open(HOOK, f"internal error {exc!r}")
    return kit.deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
