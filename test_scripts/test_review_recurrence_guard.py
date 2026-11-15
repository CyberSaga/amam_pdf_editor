"""Tests for scripts/hooks/review_recurrence_guard.py (PreToolUse Write).

A design-review record `plans/<name>-review-rN.md` (N >= 3) must carry a
`Recurrence` section that answers "same mechanism as last round?".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS))

import review_recurrence_guard as rrg  # noqa: E402

R3 = "plans/foo-review-r3.md"

NO = "# Review\n\n## Recurrence\n- This round: a list was short\n- Previous round: a different list\n- Same mechanism: no\n"
YES = NO.replace("Same mechanism: no", "Same mechanism: yes")
YES_FIX = YES + "- Class fix: check the outcome, not the list\n"


def _decide(content: str, path: str = R3, tool: str = "Write") -> str | None:
    return rrg.decide(tool, path, content)


def test_r2_is_exempt() -> None:
    assert _decide("no section", "plans/foo-review-r2.md") is None


def test_r3_without_section_is_denied() -> None:
    reason = _decide("# Review\n\nbody\n")
    assert reason and "Recurrence" in reason
    assert "two consecutive rounds on the same mechanism means stop patching instances" in reason
    assert "- Same mechanism:" in reason


def test_no_is_allowed() -> None:
    assert _decide(NO) is None


def test_yes_without_class_fix_is_denied() -> None:
    reason = _decide(YES)
    assert reason and "Class fix" in reason


def test_yes_with_class_fix_is_allowed() -> None:
    assert _decide(YES_FIX) is None


@pytest.mark.parametrize("label", ["This round", "Previous round", "Same mechanism"])
def test_empty_value_is_denied(label: str) -> None:
    content = "\n".join(
        f"- {label}:   " if line.startswith(f"- {label}:") else line for line in NO.splitlines()
    )
    reason = _decide(content)
    assert reason and f"'- {label}:' is empty" in reason


def test_heading_like_line_inside_a_fence_does_not_end_the_section() -> None:
    content = "## Recurrence\n```\n# note\n```\n- This round: a\n- Previous round: b\n- Same mechanism: no\n"
    assert _decide(content) is None


def test_section_inside_a_fence_does_not_count() -> None:
    content = "# R\n```\n## Recurrence\n- This round: a\n- Previous round: b\n- Same mechanism: no\n```\n"
    assert "missing Recurrence section" in (_decide(content) or "")


@pytest.mark.parametrize("heading", ["## Recurrence (round 3)", "## 5. Recurrence", "# Recurrence"])
def test_near_miss_heading_says_what_is_expected(heading: str) -> None:
    reason = _decide(NO.replace("## Recurrence", heading))
    assert reason and "exactly `## Recurrence`" in reason


def test_deny_message_carries_the_whole_rule() -> None:
    reason = _decide("x") or ""
    assert "do not write the next revision" in reason and "tell the owner" in reason


@pytest.mark.parametrize("path", [r"C:\repo\myplans\foo-review-r7.md", "plans-old/foo-review-r7.md"])
def test_lookalike_directories_are_allowed(path: str) -> None:
    assert _decide("x", path) is None


def test_empty_class_fix_is_denied() -> None:
    assert "Class fix" in (_decide(YES + "- Class fix:\n") or "")


def test_same_mechanism_must_be_yes_or_no() -> None:
    assert _decide(NO.replace("no\n", "maybe\n")) is not None


def test_labels_are_case_insensitive_and_level_flexible() -> None:
    content = "### recurrence\n- this round: a\n- PREVIOUS ROUND: b\n- same mechanism: No\n"
    assert _decide(content) is None


@pytest.mark.parametrize("path", ["plans/foo.md", "plans/archive/x-review-r5.md", "docs/x-review-r5.md"])
def test_non_record_paths_are_allowed(path: str) -> None:
    assert _decide("anything", path) is None


def test_edit_tool_is_allowed() -> None:
    assert _decide("anything", tool="Edit") is None


def test_backslash_windows_path_matches() -> None:
    assert _decide("x", r"C:\repo\plans\foo-review-r7.md") is not None
    assert _decide("x", r"C:\repo\PLANS\Foo-Review-R7.MD") is not None
    assert _decide("x", r"C:\repo\plans\archive\foo-review-r7.md") is None


def test_labels_under_a_later_heading_are_denied() -> None:
    content = "## Recurrence\n\nprose only\n\n## Next\n- This round: a\n- Previous round: b\n- Same mechanism: no\n"
    assert _decide(content) is not None


def test_garbage_payload_is_allowed() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "review_recurrence_guard.py")],
        input=b"not json",
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 1
    assert b"permissionDecision" not in proc.stdout


def test_end_to_end_deny_and_allow() -> None:
    def run(content: str) -> subprocess.CompletedProcess:
        payload = {"tool_name": "Write", "tool_input": {"file_path": R3, "content": content}}
        return subprocess.run(
            [sys.executable, str(HOOKS / "review_recurrence_guard.py")],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )

    denied = run("nothing")
    assert denied.returncode == 0
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    allowed = run(NO)
    assert allowed.returncode == 0 and allowed.stdout.strip() == b""


GOOD = "## Recurrence\n- This round: a\n- Previous round: b\n- Same mechanism: no\n"


@pytest.mark.parametrize(
    "content",
    [
        "```\n~~~\n" + GOOD,  # a tilde does not close a backtick fence
        "````\n```\n" + GOOD,  # a shorter fence does not close a longer one
        GOOD.replace("- ", "    - "),  # four spaces: indented code, not list items
        "## Recurrence\nempty\n" + GOOD,  # two sections
        GOOD + "\n## Recurrence\n- This round: x\n- Previous round: y\n- Same mechanism: yes\n",
        rrg.TEMPLATE.replace("yes|no", "no"),  # the template with only the answer filled in
        GOOD.replace("no\n", "no / yes\n"),
        GOOD.replace("no\n", "yes\n") + rrg.TEMPLATE.splitlines()[-1] + "\n",  # unfilled class fix
    ],
)
def test_tightened_grammar_denies(content: str) -> None:
    assert _decide(content) is not None


@pytest.mark.parametrize(
    "content",
    [
        "﻿" + GOOD,  # BOM
        GOOD.replace("\n", "\r\n"),  # CRLF
        "```\n~~~\n```\n" + GOOD,  # a real closing fence after a lookalike marker
        "~~~\nfake\n~~~\n" + GOOD,
        GOOD.replace("- ", "   - "),  # three spaces is still a list item
    ],
)
def test_tightened_grammar_allows(content: str) -> None:
    assert _decide(content) is None


@pytest.mark.parametrize("path", ["plans/./foo-review-r3.md", "plans/archive/../foo-review-r3.md"])
def test_path_aliases_are_checked(path: str) -> None:
    assert _decide("x", path) is not None


def test_scan_checks_every_writer_and_exempts_legacy_rounds(tmp_path: Path) -> None:
    (tmp_path / "plans").mkdir()
    records = {
        "a-review-r16.md": "legacy, no section",  # exempt: predates the rule
        "a-review-r17.md": GOOD,
        "a-review-r18.md": "edited after a passing Write, section gone",
        "a-review-r19.md": GOOD.replace("no\n", "yes\n"),  # yes without a class fix
    }
    for name, text in records.items():
        (tmp_path / "plans" / name).write_text(text, encoding="utf-8")
    assert [p for p, _ in rrg.scan(tmp_path)] == ["plans/a-review-r18.md", "plans/a-review-r19.md"]


def test_records_on_disk_pass_the_scan() -> None:
    """The outcome check, whichever tool wrote the files: every record of round >= 17 is valid.
    r17 is the independent known-good fixture: a broken parser fails here instead of redefining it."""
    assert rrg.scan(REPO_ROOT) == []
    r17 = REPO_ROOT / "plans" / "paragraph-grouping-reflow-review-r17.md"
    if r17.exists():  # a checkout without the untracked record skips this half
        text = r17.read_text(encoding="utf-8")
        assert "Same mechanism:" in text
        assert rrg.check_record("plans/paragraph-grouping-reflow-review-r17.md", text) is None


@pytest.mark.parametrize(
    "content",
    [
        GOOD.replace("no\n", "no (see r12/r13)\n"),
        GOOD.replace("no\n", "no, parser | writer are different\n"),
        GOOD.replace(": a\n", ": a < b > c\n"),
        GOOD.replace(": a\n", ": <span>nodes</span> leak\n"),
    ],
)
def test_real_prose_is_not_mistaken_for_a_placeholder_or_a_double_answer(content: str) -> None:
    assert rrg.check_record("plans/a-review-r17.md", content) is None


@pytest.mark.parametrize(
    "content",
    [
        GOOD.replace("no\n", "no or yes\n"),
        GOOD + "- Same mechanism: yes\n",  # a second answer line
        GOOD.replace(": a\n", ": <mechanism the worst findings belong to>\n"),
    ],
)
def test_conflicting_answers_and_template_text_are_denied(content: str) -> None:
    assert rrg.check_record("plans/a-review-r17.md", content) is not None


def test_scan_uses_the_same_path_rule_as_the_hook(tmp_path: Path) -> None:
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "x-review-R17.md").write_text("bad", encoding="utf-8")
    (tmp_path / "plans" / "x-review-r².md").write_text("bad", encoding="utf-8")  # not a round number
    assert [p for p, _ in rrg.scan(tmp_path)] == ["plans/x-review-R17.md"]
