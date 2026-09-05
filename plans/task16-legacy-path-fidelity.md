# Task 16 — Legacy-path fidelity (T16-1 … T16-4)

Branch: `task16/legacy-path-fidelity` (off `88b90bb`). Started 2026-09-05.
Source: `TODOS.md` "Task 16 — Legacy-path fidelity, found by manual test (2026-09-04)".

## Goal

Make the fidelity-preserving tiered engine the shipping default, make every
legacy (redact+reinsert) commit visible to the user, stop paragraph mode from
swallowing sibling table cells, and unblock the main CJK body face of both
corpus documents by parsing array-destination `bfrange` fail-closed.

## Affected modules (from the Understand fan-out, 2026-09-05)

| Item | Files | Anchor |
|---|---|---|
| T16-1 notice | `controller/pdf_controller.py:2321-2366, 2513-2521`; `view/pdf_view.py:2411` (no change) | `_is_notifiable_degrade` delegates to `is_real_fallback_commit`, which deliberately excludes `fallback_chain == ("legacy",)` |
| T16-2 paragraph | `model/text_block_parsing.py:544-634 _build_paragraphs` (primary); `model/text_block.py:152-221` (para-id `_p0` assumption) | no horizontal/column check at all; HVAC page 1 raw block 6 holds 4 cells |
| T16-3 parser | `model/text_commit/cid_fonts.py:412-504` (`b'['` refusal at :460), `:363-396 ToUnicodeMap`, `:398-409 _hex_items` | single choke point; records are `("char", c, c, text)` / `("range", lo, hi, base)` |
| T16-3 flip | `model/text_commit/dto.py:210` AND `:242` (two literals) ; `main.py:93-98,140-145` | `from_env` fallback literal is the one real users hit |
| T16-4 tandem | `model/text_commit/plan.py:1006-1010, 463-521, 581-793, 1190-1204`; `inspect.py:82-96, 798-950`; `patch.py:132-176` | 1:1 binding contract; stroke ink unboundable today |

## Decisions

1. **T16-1 is additive in the Controller.** `is_real_fallback_commit` stays
   untouched (it also gates the redo-reprompt in `edit_commands.py:357`). A
   second condition — `status == DEGRADED_COMMITTED and degraded_reason ==
   "legacy_redact_reinsert"` — fires the same `view.notify_degraded_commit`
   toast with a message naming the legacy engine and the untracked-fidelity
   warning. It also sets `_last_edit_degraded` so the success toast is
   suppressed, matching the real-fallback path. Per commit, not per document:
   consistent with the existing channel and non-blocking (5 s warning toast).
2. **T16-3 parser:** array-destination blocks are exploded into per-code
   `("char", code, code, text)` records at parse time (reuses `decode_cid` /
   `cids_for_char` untouched). Refuse (`TYPE0_TOUNICODE_UNPARSEABLE`, distinct
   `detail` strings) on: element count ≠ `hi-lo+1`, unterminated/nested
   bracket, non-hex element, non-UTF-16BE element, empty element, `hi < lo`.
   Exploded records count against `_MAX_TOUNICODE_RECORDS`. Scalar and array
   blocks may mix in one stream. No new `RejectReason` constant: a malformed
   array *is* unparseable, and the funnel keys on reason codes.
3. **T16-3 flip:** both literals in `dto.py` go to `"tiered"`. Tests named
   `test_default_legacy_*` are rewritten to pass `engine="legacy"` explicitly
   (they keep guarding the legacy path) and a new test pins the kill switch.
   Known behaviour delta: `pdf_model.py:3729` (signed/widget page reject) goes
   live. That is the intended fail-closed behaviour.
4. **T16-2:** fix in `_build_paragraphs`, not the consumer. Within a raw
   block: (a) split a line into cells at a span gap > 2.0 × the larger span's
   font size; (b) group lines/cells into sub-paragraphs by horizontal-range
   overlap (share a column ⇔ x-overlap ≥ 50 % of the narrower); (c) emit
   `_p0, _p1, …` per block. Thresholds are provisional — the implementer
   must keep `test_text_extraction_line_joining.py` and the `_build_paragraphs`
   unit tests green and record the final numbers here.
5. **Serial execution in the main tree** (editable install points at the repo;
   worktrees cannot run the venv suite). Order: T16-1 → T16-3 parser →
   T16-3 flip + latency A/B → T16-2 → docs. T16-4 is designed after the
   first four land.

## Steps

- [x] Understand fan-out (5 readers).
- [x] T16-1 red → green (adversarial review still owed).
- [x] T16-3 parser red → green (review round 1 landed 2026-09-05: docs-only
      findings, see Log); corpus scan
      before/after (`scripts/scan_tounicode_parse.py`, new: counts Type0 fonts
      whose ToUnicode passes `parse_tounicode_strict` per document, code-only
      output).
- [ ] T16-3 default flip + kill-switch test + same-session latency A/B
      (`scripts/benchmark_engine_default_ab.py`, new).
- [ ] T16-2 red → green → review.
- [ ] PITFALLS / ARCHITECTURE / TODOS; archive this plan.
- [ ] T16-4 design (separate workflow).

## Log

- 2026-09-05: plan written; baseline suite run started.
- 2026-09-05 (T16-1): Red — rewrote
  `test_default_legacy_engine_shows_no_degrade_notice` into
  `test_explicit_legacy_engine_surfaces_degraded_status_once`
  (`engine="legacy"` explicit; asserts exactly one degrade notice mentioning
  "legacy" and `consume_last_edit_degraded()` True-then-False). Ran red:
  `1 failed, 20 passed` (`expected exactly one warning notice ... got 0`).
  Green — added `PDFController._is_legacy_baseline_degrade` (additive,
  checks `status is DEGRADED_COMMITTED and degraded_reason ==
  "legacy_redact_reinsert"`, deliberately NOT touching
  `is_real_fallback_commit`), `_legacy_baseline_degrade_message` (names the
  legacy engine + untracked bold/structure fidelity, reason codes only),
  and `_notify_legacy_baseline_degrade`; factored the shared dispatch logic
  out of `_notify_degraded_commit` into `_dispatch_degrade_notice` so both
  branches push through the identical view channel. New `elif` branch in
  `edit_text()` after the existing `_is_notifiable_degrade` check — mutually
  exclusive by construction (chain `("legacy",)` vs a real fallback chain),
  so exactly one notice ever fires per commit.
  Deviation: also updated `test_successful_edit_still_shows_saved_toast_once`
  (uses default `TextCommitSettings()` = `engine="legacy"`) to
  `engine="tiered"` explicitly — under T16-1 its original premise (`legacy`
  default + tier0 stream = ordinary ungraded success) no longer holds, since
  every `engine="legacy"` commit is now itself a surfaced degrade that
  suppresses the mode-switch success toast; switched to a genuine
  `CommitStatus.COMMITTED` tiered Tier-0 commit so the pin still tests what
  it says it tests. `test_target_not_found_does_not_show_saved_toast` and
  the stale-flag/reflow-hook tests on default settings were checked and left
  unchanged (no commit outcome, or assertions unrelated to the degrade
  flag/notice). Full run:
  `test_scripts/test_text_commit_degrade_visibility.py` 21 passed;
  `test_text_commit_consent_flow.py` + `test_text_commit_decision_chain.py`
  19 passed. `ruff check` clean on both changed files; `ruff format --diff`
  shows only pre-existing whole-file drift outside the edited regions (left
  untouched, out of scope).
- 2026-09-05 (T16-1, advisor-caught gap): the evidence map named only the
  `edit_text` call site, but `move_text_across_pages` has its own, separate
  `_is_notifiable_degrade` gate (source deletion goes through
  `model.edit_text` directly, bypassing `controller.edit_text` — see
  `test_cross_page_move_surfaces_source_degrade`). Left as-is, a legacy
  cross-page move's source deletion would stay silently unnotified while an
  in-place edit warns, contradicting "every legacy redact+reinsert commit."
  Added the same `elif self._is_legacy_baseline_degrade(source_outcome)`
  branch there (one parallel line, same helpers). Red-first: temporarily
  reverted just that branch, ran the new
  `test_cross_page_move_surfaces_source_degrade_under_legacy_engine`
  (`engine="legacy"`) — failed `expected exactly one legacy-baseline
  warning ... got 0: []` — then restored the branch; green. Full
  `test_scripts/test_text_commit_degrade_visibility.py` run: 22 passed.
  Regression sweep for other tests touching the edit/move + toast surface
  (`rg -l "sig_edit_text|controller\.edit_text|move_text_across_pages"
  test_scripts/ | xargs rg -l "_show_toast|notify_degraded_commit|..."`):
  turned up `test_text_edit_manager_foundation.py` in addition to the three
  files already run — its one relevant test hits `TARGET_BLOCK_NOT_FOUND`
  (no commit outcome), unaffected; 11 passed. `ruff check` clean; new lines
  fall in a `ruff format --diff` no-hunk gap (already compliant).
- 2026-09-05 (T16-3 parser): corpus baseline FIRST (no `git stash`; the
  scan script was written before any parser edit) —
  `doc_0 type0_fonts=261 tounicode_present=261 parse_ok=260` and
  `doc_1 type0_fonts=1 tounicode_present=1 parse_ok=0`; the ONE loss code
  in each document was
  `array_destination_bfrange_is_outside_the_v1_grammar`. After the change:
  **261/261 and 1/1, empty failure histograms** — acceptance met.
  Red — 7 new tests failed against HEAD (`7 failed, 7 passed`), every one
  on the blanket `array-destination bfrange is outside the v1 grammar`
  detail. Green — whole file `70 passed`.
  Design: `bfrange` blocks no longer share `_hex_items` with `bfchar`
  (there a `[` stays meaningless and still yields `malformed bfchar
  block`, pinned). They go through a new `_bfrange_operands` tokenizer
  that treats brackets as grammar and raises a private
  `_CMapGrammarError` carrying a code-only detail; `_explode_bfrange_array`
  then appends one `("char", code, code, text)` record per element.
  Dead end avoided: asserting only `plan.reason` in the new refusal tests
  would have been INVALID red — the pre-change parser already returned
  `type0_tounicode_unparseable` for every array, well-formed or not. Every
  unit refusal test therefore asserts the exact `detail` string, and the
  two end-to-end `_assert_fail_closed` cases the spec asked for are marked
  **PIN** in their docstrings (green before and after; they buy the
  whole-object-table zero-mutation oracle, not redness), each paired with a
  detail-asserting unit twin.
  Final refusal vocabulary (8 new details, all code-only): array element
  count ≠ `hi-lo+1`; array unterminated / nested / closed-without-open /
  holding a non-hex token; element empty; element not strict UTF-16BE
  (odd length or lone surrogate); array in a source-code position.
  Reused unchanged: `bfrange low code exceeds high code`, `bfrange record
  count disagrees with declaration` (which counts bfrange ENTRIES, not
  exploded records — commented in place), `ToUnicode record count over the
  parse budget` (decision (3): a 65 536-element array plus one bfchar
  refuses).
  Multi-char array elements parse and refuse downstream as
  `type0_tounicode_multichar`, identical to `bfchar` (decision (5)).
  Blast radius outside the item, both forced by the widening and fixed in
  this commit: `scripts/measure_type0_funnel.py`
  `TOUNICODE_UNPARSEABLE_DETAILS` (the retired blanket string swapped for
  the 8 new ones — the census asserts that set is CLOSED), and
  `test_scripts/test_glyph_overlap_census.py::
  test_tounicode_unparseable_details_are_closed_and_counted`, whose fixture
  used a WELL-FORMED array and now uses a length-mismatched one.
  `model/text_commit/dto.py` was checked for a stale array-bfrange comment:
  none found, nothing to update. `verify.py::_parse_tounicode` left
  untouched per spec, so its docstring now deliberately diverges.
  Verification: `test_text_commit_cid_hex_tj.py` 70 passed;
  `+ test_glyph_overlap_census / test_text_commit_fonts /
  test_text_commit_font_widths / test_text_commit_font_revalidation`
  150 passed; the 11 remaining `cid_fonts`-dependent suites 339 passed.
  `ruff check` clean on all five changed/new files; `mypy model/ utils/`
  Success (the range loop's destination variable is named
  `destination_operand` so it does not collide with the `bytes`-typed
  `destination` of the bfchar loop). `ruff format` was NOT run on
  `cid_fonts.py`: it wants whole-file drift outside the edited regions
  (same pre-existing drift the T16-1 entry records), so the new code
  hand-matches the file's wrapped-paren style.
- 2026-09-05 (T16-3 parser, review round 1): 4 findings handed back, **2 real**
  — findings 2/3/4 are three restatements of the SAME `docs/ARCHITECTURE.md`
  parenthetical, reported as one. Both confirmed empirically before fixing:
  `parse_tounicode_strict(b"1 beginbfrange <0010> <0011> [<0041> <0042>] "
  b"endbfrange")` returns `ToUnicodeMap((("char",16,16,"A"),("char",17,17,
  "B")))`, and `rg test_array_destination_bfrange_tounicode_fails_closed
  test_scripts/` has zero hits. Both are doc-only; no production code changed.
  Red first: two new guard tests at the end of
  `test_text_commit_cid_hex_tj.py` failed against HEAD (`2 failed`) — one on
  the dead test name, one on the retired `refuse any bfrange block containing`
  prose. Then the fixes; `72 passed`.
  Decision — the PITFALLS entry was **split, not inverted**. Its `**Area:**`
  is `verify.py::_parse_tounicode`, which T16-3 deliberately did NOT touch, so
  Symptom and Cause are still literally true there; only the `**Fix:**` line
  was stale. It now states both halves explicitly (verify.py still fabricates,
  by scope decision; `cid_fonts.parse_tounicode_strict` parses well-formed
  arrays and refuses malformed ones under 8 code-only details) and names the
  five live pinning tests. Inverting the whole entry would have erased a live
  warning about a real, still-shipping bug.
  `docs/PITFALLS_INDEX.md` was regenerated (CLAUDE.md §6.1) — it came out
  byte-identical because the rewrite kept the entry's line COUNT the same, so
  no downstream `Read(offset=…)` shifted; that was deliberate, not luck.
  ARCHITECTURE was a single-bullet edit; the multi-char-refuses-lazily clause
  is still true (decision (5)) and was kept.
  Scope held: `rg "scalar-destination|array-destination|outside the v1
  grammar|present_with_array_destinations" docs/ TODOS.md plans/` turned up
  `TODOS.md:547` (a dated 2026-08-13 census log entry — historical record,
  correct as written) and `TODOS.md:1497` (the T16-3 item statement, which
  stays open until the default flip lands and is ticked in the docs step),
  plus archived plans. None touched.
  The new guard is scoped to the ONE pitfall entry on purpose: a whole-file
  "every cited test exists" check trips on the unrelated pre-existing stale
  `test_planner_rejects_hex_tj_pages_as_not_literal` reference and would have
  grown into an allowlist. Registered here rather than fixed — out of scope.
  Verification: `test_text_commit_cid_hex_tj.py` 72 passed; `ruff check` clean
  on the test file; `ruff format` NOT run (same pre-existing whole-file drift
  recorded above — the new code hand-matches the file's narrower wrap). No
  `model/`/`utils/` file touched, so mypy was not re-run.
