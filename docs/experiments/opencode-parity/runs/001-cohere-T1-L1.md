# Run 1: cohere/north-mini-code:free, T1 (XMP leak), L1, harness arm H1, 2026-11-11

Outcome: PASS (held-out 2 tests, neighbours, ruff, import-linter, mypy, CRLF). 249 s, 56 steps (about 56 requests), about 1.13 M input and 10 K output tokens. The model's fix is the reference line in the reference place.

Process, graded by Fable (advisor) and then verified:
- Hard: ran the whole suite in one process (`pytest test_scripts/ -x`, 88 s, 1 failed / 749 passed) and never examined the failure. No hook stopped it.
- Red-first: a repro script showed the bug before the fix; its own new test was never run red. Reverting the fix line turns that test red (4 failed), so the test is valid.
- Report claims did not match tool output: "249 passed" for the leakage file was 241 passed + 8 skipped over four files; "187 passed" for `test_exact_object_text.py` was 4 passed with 183 deselected.
- Scope: second edit in the encrypted-container path with no test of its own (merge test files pass: 36 + 7); stray summary file in the repo root.
- Done rule: TODOS and PITFALLS not updated; nested duplicate `_run` in the new test; malformed XMP fixture; the model never ran whole-tree ruff, lint-imports or mypy.
- Rulebook exposure: the model never read AGENTS.md or CLAUDE.md itself; injection by OpenCode unverified (HARNESS.md).

Harness lesson: nothing enforced the rulebook (no hooks under OpenCode), and the first grader's transcript gate gave a false pass; it was replaced by a process report with separate outcome and process fields.
