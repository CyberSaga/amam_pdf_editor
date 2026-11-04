# Interrogate no-jump corpus coverage

## Goal and completion

Review the existing branch and uncommitted T16-4X work from the user's
goal: editable text across `test_files` without moving unrelated content.
Make only evidence-backed deletions or simplifications. Completion of this
review is not completion of the corpus expansion.

## Findings and decisions

- The directory contains 2,933 PDFs recursively; the nine selected fixture
  roles in T16-4X are not the full corpus. No claim of absent PDF features
  across the whole corpus follows from that sample.
- Admission, a reversal edit, and verified product coverage are different
  measurements. Keep the production verifier, font scope fix, lexer EOL fix,
  and evidence cache. No evidence yet justifies deleting these safeguards.
- Both tiers run `_classify_common`, which rejects TJ arrays. The audit's
  separate speculative `tier1_candidate` classification predates this
  shared gate. Delete it and its duplicate predicate/reason control flow.
  Keep the cheap structural upper bound explicitly separate from coverage.
- Correct the audit's Type0 literal-string eligibility, which contradicts
  the shared production hex-only gate. Reproduce both discrepancies first.
- Correct the expansion plan's completion claims; do not implement the
  speculative feature slices as part of this interrogation.

## Modules and steps

1. Red tests against real PyMuPDF documents and `prepare_plan(max_tier=1)`.
2. Simplify `scripts/audit_tier_coverage.py`; update its benchmark consumer
   and tests to the two structural counts.
3. Record bounded real-corpus evidence and limitations. Correct active plan,
   architecture, pitfalls/index and TODOs.
4. Run relevant tests, full suite, ruff, mypy and architectural checks.
   Review the final diff and archive this plan. Do not commit.

## Log

- Start: requested branch already active; retained all existing uncommitted
  changes. Inspection only so far; no new production engine changes needed.
- Red: the real Tier 1 planner refused `[(Hello)] TJ` with
  `not_single_literal_tj`; the audit returned `tier1_candidate == 1`
  (expected 0). A real, extractable Type0 literal operand got the same
  production refusal while the audit returned `tier0_eligible == 1`
  (expected 0). Both assertions failed before the audit change.
- Simplification: removed speculative Tier 1 and legacy classification,
  replaced the two predicates plus reason ladder with ordered early returns,
  and updated the benchmark schema. No runtime editor gates changed.
- Focused tests: 32 passed (audit, edit funnel, show census). Empty document,
  empty page and real-fixture benchmark aggregation also verified directly.
- Five-fixture rerun (prose, office report, colored background, horizontal
  and vertical text; 34 pages; default caps 30 lines/60 runs per page):
  1,220 targets, 487 bindings, 235 palindromes skipped, 252 attempted plans,
  zero accepted. Refusals: 251 `not_single_literal_tj`, one
  `mc_wrapper_not_pure_layer`. Both document-weighted and pooled plan
  acceptance are 0. This is a planning sample, not a full-corpus edit test.
- Removed obsolete model-specific Workflow instructions from the expansion
  plan; replaced its Tier-0-only completion premise with explicit product
  stages and full-corpus accounting. Historical slice designs remain
  proposed. `test_all_pdfs.py` is a manual runner (`__test__ = False`) and
  skips edits in the 2,887-file veraPDF directory; a full pytest pass cannot
  substitute for the missing full-corpus edit evidence.
- Ruff, mypy and all four import contracts passed; no forbidden
  `threading.Thread` in view/controller. Code graph and pitfalls index rebuilt.
  Full regression suite: **3,803 passed, 21 skipped, 5 xfailed** in 564.90s.
  No GUI appearance was changed;
  no new app-level or full-corpus no-jump signoff is claimed.
- Review complete. Full-corpus engine expansion remains open in T16-4X
  and TODOS. Changes left uncommitted on the requested branch.
