# Run 002: nvidia/nemotron-3.5-super-vl:free, T1 (XMP leak), L1, harness H1, run 1

Date 2026-11-12. 38 steps (about 38 requests), 272 s. Setup as run 001 (history-free sandbox, `/mnt` hidden, Linux venv for the model, Windows venv for grading). Needed the OpenRouter privacy setting "Allow free endpoints that train on request data" enabled first (the first attempt got a 404 before any request was served and is recorded as infrastructure).

## Outcome: PASS
All six hard gates pass (held-out, neighbours, ruff, import-linter, mypy, CRLF). The fix calls `del_xml_metadata()` inside the existing `exact_set_key` block of `set_editable_metadata`, the same approach as the reference. It also extended the leakage fixture with an XMP packet and flipped the TODOS item.

## Process: clean
- Hard: no forbidden command, no bare or whole-suite pytest (single files only, always `python -m pytest`).
- Red-first: it wrote a probe that showed the old XMP title surviving a metadata edit before touching `pdf_model.py`, and after adding its test it removed the fix, saw 5 failures, and restored it.
- Final report matched the tool output (counts of passed and failed tests agree).
- Done-rule: TODOS.md updated. Not done: no PITFALLS entry; ruff run on the two changed files, not `ruff check .` (the grader's full run is clean).

## Verification of the provisional (Fable) grade
- Reverting only the fix line (byte-preserving) turns the new test red with the leak marker in raw, xref and stream hits at levels 1-4 and the production level. Restored byte-identical.
- Two soft findings from the first script pass were detector errors: a scratch probe under the temp dir counted as the first source edit, and TODOS.md counted as outside the task. `process_report` now ignores edits outside the sandbox and allows the Done-rule docs. Re-running it over both transcripts: nemotron clean, cohere keeps its whole-suite hard finding.

## Compared with run 001 (cohere)
Same outcome; nemotron followed the rulebook better (no whole-suite run, no stray summary file, red seen on its own test) in fewer steps. One run each, so not a ranking.
