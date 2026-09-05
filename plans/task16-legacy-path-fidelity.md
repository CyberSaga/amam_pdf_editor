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
- [x] T16-3 default flip + kill-switch test + same-session latency A/B
      (`scripts/benchmark_engine_default_ab.py`, new).
- [x] T16-3 default flip, review round (3 real defects fixed, GUI pins
      reverted, consent gate demoted to an opt-in).
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
- 2026-09-05 (T16-3 review round 1, self-review pass): the first fix commit
  (`209574f`) introduced TWO fresh false claims of its own, caught before the
  round closed and fixed in the follow-up commit.
  (i) It said `verify.py::_parse_tounicode` "STILL carries this bug ... still
  fabricates mappings". FALSE — `git log -L` shows 010c9f7 (Task 12 P0-D)
  added `if b"[" in block: continue`, so the legacy reader was fixed by
  REFUSAL long ago and simply contributes no bfranges for array fonts. The
  claim had been carried forward from an older Log entry instead of read out
  of the source. Corrected, and now pinned mechanically:
  `test_pitfall_entry_matches_the_legacy_readers_actual_behaviour` calls
  `_parse_tounicode` on an array stream, asserts `((), ())`, and asserts the
  entry does not describe it as fabricating — red on `209574f`, green after.
  (ii) It attributed `hi < lo` and the record-budget overflow to the "8
  distinct code-only details". FALSE — `ast`-walking `cid_fonts.py` for
  string constants starting `bfrange destination array` returns exactly 8,
  and `hi < lo` / budget map to the PRE-EXISTING `bfrange low code exceeds
  high code` and `ToUnicode record count over the parse budget` details
  (as the 58e21f5 Log already recorded). Both docs now split the two buckets
  explicitly. No test for this one: any assertion would restate the prose,
  and the doc-lint guard is deliberately kept small.
  Also fixed, on the same "present tense must be true" principle that
  justified touching ARCHITECTURE: `TODOS.md` T16-3 said the parser
  "deliberately refuses" the form. A dated Status line now records that
  criterion 1 landed at 58e21f5 while the item stays open for the default
  flip; the motivation paragraph is untouched (verb tense only). Red-first
  via a third assertion in the retired-prose tripwire, scoped to the T16-3
  section by heading slice.
  `docs/PITFALLS_INDEX.md` regenerated after both doc rounds — byte-identical
  both times (entry line count deliberately preserved).
  Known-stale, NOT fixed (out of scope, registered here): `docs/PITFALLS.md`
  cites `test_planner_rejects_hex_tj_pages_as_not_literal`, which does not
  exist anywhere in `test_scripts/`; it belongs to a different entry and is
  why the new guard is scoped to one entry rather than the whole file.
  Verification: `test_text_commit_cid_hex_tj.py` 73 passed; with
  `test_text_commit_fonts / _font_widths / _font_revalidation /
  test_glyph_overlap_census` 152 passed (152 before the TODOS assertion).
  `ruff check` clean. No `model/`/`utils/` file touched — mypy not re-run.

- 2026-09-05 (T16-3 default flip): Red first --
  `test_default_settings_stay_legacy_and_off` rewritten to
  `test_default_settings_are_tiered_and_conservative` (engine `tiered`,
  `max_tier` 0, `strict` False, `preview` legacy, `telemetry` off), new
  `test_env_kill_switch_forces_legacy`, plus a both-literals cross-check in
  `test_from_env_empty_environment_is_default` and an engine assertion in
  the renamed `test_pdf_model_defaults_to_shipped_settings`. Ran red:
  `4 failed, 3 passed` (`assert 'legacy' == 'tiered'` four times). Green
  after flipping BOTH literals in `dto.py` -- the dataclass field default
  and the `from_env` fallback -- `7 passed`.
  **Deviation from the spec, deliberate:** the specced
  `test_env_kill_switch_forces_legacy` (only
  `from_env({"TEXT_COMMIT_ENGINE": "legacy"}).engine == "legacy"`) passes
  *before* implementation, which CLAUDE.md 5.1 calls an invalid test, so it
  also asserts `from_env({}).engine == "tiered"` in the same test. The
  pre-existing `test_from_env_invalid_values_fall_back_to_defaults` was kept
  untouched: comparing against `TextCommitSettings()` makes it an automatic
  tripwire if only one of the two literals ever moves.
- 2026-09-05 (T16-3 flip, sweep): explicit `engine="legacy"` pinned at every
  call site whose subject is the legacy path --
  `test_text_commit_consent_flow.py` (`test_default_legacy_engine_never_
  requests_consent` renamed to `test_explicit_legacy_engine_never_requests_
  consent`), `test_text_commit_shadow_mode.py:145`,
  `test_text_commit_maintenance.py`'s `_open` default-arg fallback (kept as
  a fallback, but pinned to legacy rather than tracking the shipped default:
  all three bare callers assert on `pending_edits`/`fidelity_protected_pages`,
  i.e. the redact+reinsert machinery; the two tiered callers already pass
  settings explicitly), and four sites in
  `test_text_commit_degrade_visibility.py`.
  **Spec-vs-reality deltas** (not failures): the degrade-visibility line
  numbers in the task spec (~537-549, 841, 874, 956, 997, 1026) did not
  match the file -- T16-1 had already moved one and the real bare-settings
  sites are 921/1047/1088/1117 (four, not six); `consent_flow` was line 284,
  not 279.
- 2026-09-05 (T16-3 flip, blast radius the spec did not list):
  `TextCommitSettings()` appears 11 times in `test_scripts/`, but the flip
  lands on the *dataclass field default*, so it also reaches all 341 bare
  `PDFModel()` constructions. One file actually broke:
  `test_cross_page_text_move.py` (3 of 5 tests). Cause: a cross-page move's
  source deletion is an empty replacement, which always rejects at Tier 0,
  so under a tiered default it reaches the endorsed P0-C consent modal
  (TODOS.md 2026-08-12 -- "every cross-page move prompts for consent once
  the tiered engine is enabled, every time"); the file's `_FakeView` is not
  a `QWidget`, so `QMessageBox.question` raises `TypeError` in-process. Not
  a production defect (the real view is a widget) and not a new UX delta
  (the consent gate was reviewed and endorsed in Task 12). All five models
  in that file pinned to `engine="legacy"` with a file docstring saying why;
  cross-page move *under* tiered stays covered by
  `test_text_commit_consent_flow.py::test_cross_page_move_cancel_is_atomic_
  on_both_pages` and the T16-1 source-degrade test. Worth recording:
  `test_cross_page_move_add_failure_restores_before_snapshot_and_refreshes_ui`
  was one of the two that still *passed* -- but for the wrong reason (its
  monkeypatched `add_textbox` was never reached, because the source deletion
  raised first); pinning legacy restores what it claims to test.
- 2026-09-05 (T16-3, latency A/B, `scripts/benchmark_engine_default_ab.py`,
  N=20 per engine per fixture, one process, engine order alternated per
  iteration, every sample a cold first edit on a fresh copy; Python 3.10.0 /
  PyMuPDF 1.27.1 / Windows-10-10.0.26200; **machine caveat: single machine,
  single session, no load control -- the two engines are comparable to each
  other and to nothing else**):

  | fixture | legacy median / p95 | tiered median / p95 | ratio |
  |---|---|---|---|
  | `test_files/1.pdf` | 6.97 ms / 10.11 ms | 7.00 ms / 7.84 ms | **1.00x** |
  | HVAC | 35.5 ms / 56.2 ms | 102.6 ms / 142.8 ms | **2.89x** |

  **Reported prominently, not hidden: the HVAC fixture exceeds the 2x
  threshold (2.89x) and buys nothing there.** 20/20 tiered edits on both
  fixtures rejected and fell back to legacy, so the tiered column is
  "legacy work + a wasted tiered attempt", never a successful Tier 0
  commit. The two fixtures disagree because they reject at different
  stages: `1.pdf` rejects `multi_span_target` at the top of
  `_attempt_tiered_commit`, before the engine is even constructed (hence
  free, 1.00x), while HVAC rejects `target_reconstruction_unverified` --
  a `NO_MATCH` relabeled by `_reconstruction_aware_reason` -- only after a
  full prepare/plan build on a dense CAD page. So the cost is a wasted
  *prepare*, not a wasted commit, and it scales with page density, not with
  the engine flag as such. Absolute numbers stay well under the 300 ms
  `單次編輯過慢` warning threshold (p95 143 ms), so this is not expected to
  be a visible keystroke regression today -- but it IS a >2x regression on
  the exact document class Task 16 came from, and it will only be bought
  back when T16-3's parser work plus T16-4 let those pages actually reach a
  Tier 0 commit instead of a wasted prepare.
- 2026-09-05 (T16-3 flip, the expensive dead end): the first two full-suite
  attempts both stalled at 13 % with no failure and no traceback. Not
  slowness -- `test_multi_tab_plan.py::test_03_edit_in_a_undo_in_b_isolated`
  **hangs**: its `mvc` fixture builds a REAL `PDFView`, so the newly-live
  P0-C consent `QMessageBox.question` does not raise the way
  `test_cross_page_text_move.py`'s stub view made it raise -- it opens a
  modal and blocks forever offscreen. `pytest-timeout` is not installed in
  the venv, so the whole suite has no hang protection. Diagnosed by
  indexing `--collect-only` output against the progress-dot count to name
  the stalled test, then confirming with a shell `timeout` on that one test
  (no output, no summary line). Fixed by pinning the `mvc` fixture to
  `engine="legacy"` (73 passed, 1 skipped, 96 s). Method note for whoever
  runs the next default flip: verify with a per-file sweep under
  `timeout 420` rather than one whole-suite run, because a hang inside a
  single `pytest test_scripts` invocation costs the entire run and tells
  you nothing about where it was. Registered, not fixed (out of scope):
  the suite has no timeout plugin, so any future modal-in-a-test is the
  same silent 12-minute stall.
- 2026-09-05 (T16-3 flip, second hang, same class): after pinning
  `test_multi_tab_plan.py` the suite stalled again, at 27 %, in
  `test_no_jump_editor_geometry.py`. Same cause, different disguise -- the
  first ~93 % of that file is fine under `tiered`, and only the three
  heavyweight real-GUI groups at the end reach the consent modal
  (`test_click_to_edit_then_insert_then_delete_stays_stable`,
  `test_click_to_edit_continuous_insertions_then_delete_stays_stable`,
  `test_reopen_same_textbox_cycles_do_not_cumulate_shrink`). Those are also
  genuinely slow (199 s for the reopen-cycle trio alone), so "slow" and
  "hung" are hard to tell apart here; settled it by measurement, not
  inference: pinned `engine="legacy"` -> `3 passed in 199.28s`; reverted the
  pin and ran the same three -> no output at all in 560 s. Pin kept (all
  five `PDFModel()` sites in the file, each with the evidence in a comment);
  full file green at `377 passed, 6 skipped in 260.31s`.
  Dead end worth recording so nobody repeats it: a throwaway pytest plugin
  that monkeypatched `controller.pdf_controller.confirm_degraded_fallback`
  to raise, hoping to turn every hang into a named failure in one suite run,
  did NOT surface this one -- the run stalled at the same 27 %. Do not trust
  a single choke-point patch to enumerate modal hangs; measure per file
  under `timeout` instead. Method that did work, end to end: index
  `--collect-only` output against the progress-dot count to name the stalled
  test, then `timeout N pytest <that test> -v` to confirm.
- 2026-09-05 (T16-3 flip, verification): full suite green --
  `3705 passed, 21 skipped, 5 xfailed in 2049.44s (0:34:09)`, one clean
  invocation, nothing else on the machine. (The 12-minute figure in the
  harness notes is optimistic for this branch; budget ~35 min.) Narrow runs
  along the way: settings `7 passed`; text-commit family
  (`-k "text_commit or text_edit or edit_text"`) `1236 passed, 2490
  deselected, 5 xfailed in 112.95s`; `test_cross_page_text_move.py`
  `5 passed`; `test_multi_tab_plan.py` `73 passed, 1 skipped in 96.62s`;
  `test_no_jump_editor_geometry.py` `377 passed, 6 skipped in 260.31s`.
  `ruff check` clean on every changed file; `mypy model/ utils/` -- `Success:
  no issues found in 53 source files`. One per-file-run artifact worth
  ignoring next time:
  `test_audit_same_face.py::test_direct_script_entrypoint_resolves_sibling_
  modules` failed under the per-file sweep (two pytest processes were
  competing for the machine) and passes in the clean whole-suite run.

- 2026-09-05 (T16-3 flip, review round): 10 findings handed back, which
  dedupe to **4 distinct claims; all 4 verified true before any fix**, three
  of them real defects and one a coverage gap. Nothing was skipped as wrong.
  1. **REJECTED_UNSUPPORTED is mute.** Confirmed by reading:
     `_edit_result_to_message` had no branch for it and
     `_show_edit_result_feedback` early-returns on a falsy message, so the
     newly-live signed/widget-page reject discarded the user's typing in
     total silence. Every other non-SUCCESS result on that path has a
     message, and the cross-page caller already defends itself with
     `... or "..."` -- an oversight, not a decision. Fixed with a real
     message (reason-free, no document text).
  2. **The hard reject fails OPEN.** `except (RuntimeError, ValueError):
     hard_reject = False` -- "the probe blew up, so assume no widgets, so
     run the legacy mutation" -- three lines under a comment promising the
     opposite. And `fitz.mupdf.FzErrorBase` MRO is `Exception ->
     BaseException` (verified in the venv), so a real MuPDF failure escaped
     the tuple entirely. Fixed at the **chokepoint** per MEMORY.md's
     "fix the bug class, not the instances": `page.widgets()` moved INSIDE
     `page_has_widgets_or_signatures`' guard so every caller (`plan.py:903`
     too) inherits the refusal, `FzErrorBase` named, and the call site's own
     handler flipped to `hard_reject = True` as defence in depth.
  3. **The P0-C consent modal fires on every ordinary edit.** Verified with
     my own probe before touching anything: 12 single-span edits over
     `1.pdf` / HVAC / `test-colored-background.pdf`, spy on
     `confirm_fallback` -- **12/12 prompts under `tiered`, 0/12 under
     `legacy`**; chains `('tier0:not_single_literal_tj','legacy')` and
     `('tier0:pending_page_maintenance','legacy')`. Matches the A/B's 20/20
     reject rate. **Decision, and why it is in scope rather than a
     redesign:** TODOS T16-3 criterion 4 states the premise the flip was
     accepted under -- "`strict` stays `False`, so a flipped default means
     tiered refuses and falls back to legacy *silently* unless the
     degradation notice exists" -- and gates the flip on T16-1 for exactly
     that reason. A blocking modal plus a toast per edit is not that. The
     gate was designed when `tiered` was an OPT-IN; under `max_tier=0` the
     Tier 0 refusal is the common path, so its frequency was never
     re-derived when the flag moved. So: new `TextCommitSettings.
     confirm_degrade` (default **False**, `TEXT_COMMIT_CONFIRM_DEGRADE=1`),
     resolved Controller-side in `_fallback_consent_callback()`, which
     returns `None` when off. Gated at the caller, not in the Model:
     `confirm_fallback is None` is already first-class there and an API that
     accepts a callable then ignores it would be worse. Every Phase 2
     guarantee is untouched under the opt-in (decline -> FALLBACK_DECLINED,
     zero mutation, no redo re-prompt) -- `test_text_commit_consent_flow.py`
     now sets `confirm_degrade=True` at all 10 `_launch` sites, **including
     the two "never requests consent" tests and the `engine="legacy"` one**,
     where leaving the gate off would have made the assertion pass
     vacuously.
  4. **Zero end-to-end coverage of the shipped default.** True, and the
     flip commit had *caused* half of it. Rather than only adding a test,
     the three GUI pins that commit introduced were **reverted** --
     `test_no_jump_editor_geometry.py` (5 sites), `test_multi_tab_plan.py`
     (`mvc`), `test_cross_page_text_move.py` (5 sites) -- because the modal
     was the entire reason they hung/raised, and it is now off. Reverted by
     reverse-applying that commit's diff for those three files (no
     `git checkout`), then **measured, not inferred**, per this Log's own
     method note: `test_cross_page_text_move.py + test_multi_tab_plan.py`
     `78 passed, 1 skipped in 133.90s`; `test_no_jump_editor_geometry.py`
     `377 passed, 6 skipped in 330.35s` (vs `260.31s` pinned to legacy --
     **1.27x slower under the shipped default, and it completes**, where the
     same file produced no output at all in 560 s before the modal was
     demoted). So the shipped configuration is again exercised end to end by
     real PDFView+Controller+Model tests, and that 1.27x is a second,
     independent read on the flip's latency cost on a Latin fixture.
  **Disclosed at its real frequency, so the same defect class does not
  survive one notch quieter:** the T16-1 notice that now replaces the modal
  fires at the SAME rate the modal did (same Tier 0 reject rate), i.e. one
  5 s non-blocking warning toast per text edit. That is criterion 4's own
  T16-1 gating working as intended, and it falls as Tier 0 starts accepting.
  Written into both ARCHITECTURE and the TODOS criterion, not just here.
  New file `test_scripts/test_text_commit_default_engine_ux.py` (16 tests):
  red-first for all three defects, plus PINs the suite never had -- widget
  page and `/SigFlags>0` reject with a **four-way** zero-mutation oracle
  (result code, `page_fingerprint`, `undo_count`, `edit_count`), the legacy
  kill switch still editing a widget page, and the prompt COUNT under the
  shipped default. RED before implementation: `11 failed, 11 passed`
  (`RuntimeError: unreadable /Annots` escaping the probe;
  `FzErrorBase` escaping it; `SUCCESS is REJECTED_UNSUPPORTED` for the
  fail-open reject; `assert None` for the missing message; `expected exactly
  one error toast, got []`; `no attribute 'confirm_degrade'`). The five PINs
  passed before and after and say so in their docstrings.
  **Registered, NOT fixed (scope):** there is still no in-app kill switch --
  both `TEXT_COMMIT_ENGINE=legacy` and `TEXT_COMMIT_CONFIRM_DEGRADE=1` need
  an env var and a restart. That is a Settings-UI item; recorded in TODOS
  under criterion 4 as a follow-up.
  **Latency A/B not re-run:** the measured path (`PDFModel.edit_text` driven
  headlessly, no `confirm_fallback` argument) is untouched by this round --
  the consent gate lives in the Controller and the probe change adds one
  `try` frame. The `ed55b35` numbers stand as recorded above (`1.pdf`
  1.00x; HVAC **2.89x**, still over the 2x threshold and still reported
  prominently, unchanged by this round).
  Verification: new file + settings `22 passed`; consent/degrade/decision
  trio `41 passed in 40.85s`; unpinned `test_cross_page_text_move.py +
  test_multi_tab_plan.py` `78 passed, 1 skipped in 133.90s`; unpinned
  `test_no_jump_editor_geometry.py` `377 passed, 6 skipped in 330.35s`;
  text-commit family (`-k "text_commit or text_edit or edit_text"`)
  `1251 passed, 2490 deselected, 5 xfailed in 345.79s` (1236 before, +15 =
  exactly this round's new items); full suite `3720 passed,
  21 skipped, 5 xfailed in 2282.01s (0:38:02)` -- exactly +15 over
  `ed55b35`'s `3705 passed, 21 skipped, 5 xfailed`, i.e. this round's new
  items and no other movement.
  `ruff check` clean on all 10 changed/new files; `ruff format` run on the
  new test file only (every other touched file has the pre-existing
  whole-file drift recorded above, so the new lines hand-match local style);
  `mypy model/ utils/` `Success: no issues found in 53 source files`.
