# xfail / skip retirement: `test_text_commit_characterization.py` (5 strict xfails) and the Cycle-22 skipped block in `test_no_jump_editor_geometry.py` (6 skips)

## Current state and next step (keep under 40 lines)

- 2026-11-02: audit done (one tiered/legacy probe on a scratch copy, 7 read-only
  investigators, 2 Opus analyses, 2 refuters, owner rulings below).
- S1 LANDED in the working tree (uncommitted, owner commits): skipped block
  deleted, `PreviewRenderer` import dropped, self-test added (mutation-proven x3),
  `completion_gate.py:126` re-pinned to `ddd07253…`, `:111`/`:159` repointed,
  `TEST_SCRIPTS.md:80`, TODOS trust-chain line. Whole file: 378 passed, 0 skipped.
- Target end state: the characterization file has **0 xfails** (T1 and T5 become
  plain consent-route characterizations, T2 becomes a green tiered twin elsewhere,
  T3 and T4 are deleted); `test_no_jump_editor_geometry.py` has **0 skips** (the
  :1751-1878 block is deleted, a `_changed_pixel_pct` self-test is added,
  `completion_gate.py:126` is re-pinned). Qt-lane skips 11 -> 5; pure-lane xfails 5 -> 0.
- S2 LANDED in the working tree (uncommitted): twin green, legacy control red
  (Courier), T2/T3/T4 deleted, three docstrings reworded.
- S3 LANDED in the working tree (uncommitted): characterization file has 0 xfails
  (3 plain tests), consent route measured and teeth-proven.
- S4 LANDED in the working tree (uncommitted): ARCHITECTURE regression-net
  paragraph, PITFALLS 3592 Fix corrected + 2 new entries + index regen (657),
  paragraph-reflow §7.2, TODOS (new top section: done note, owner-gated legacy
  retirement, reason-masking candidate), fingerprint_roundtrip docstring,
  codegraph re-indexed, ruff clean. Whole suite via `run_suite.py`: see Log.
- Next step: owner reviews and commits (S1..S4 can be one commit or four; the
  tree holds all four). This file is `git mv`'d to `plans/archive/` once the
  suite result is logged. Nothing is pushed.
- Whole-suite check at the end of S4: `.venv\Scripts\python.exe scripts/run_suite.py`
  (the only sanctioned whole-suite command).

## Goal

Answer "can the 5 xfails and 6 skips be eliminated?" with changes that lose no
drift net. Constraint from the probe: the three tiered refusals that cover T1/T4/T5
are all **rebuildable** (`view/text_edit_reasons.py:37`, `:42`, `:52`; none is in
`_NOT_REBUILDABLE` at `:149`), so 改用重建文字 + the consent dialog still runs the
legacy `_apply_redact_insert` on the shipped default. The file's exit criterion
("keep xfailing until the tiered engine is enabled", docstring `:10-13`,
`docs/ARCHITECTURE.md:1118-1122`) is obsolete: tiered has been the default since
Task 16 (`model/text_commit/dto.py:311-315`, `:338`).

## Measured facts (probe, 2026-11-02, PyMuPDF 1.27, `.venv`)

Scratch copy of the file with the xfail decorators stripped and
`TextCommitSettings(engine=ENGINE)`; one pytest per engine, serialized.

| test | legacy | tiered |
|---|---|---|
| T1 `test_unchanged_style_preserves_embedded_font_resource` | fails (font types `{Type0}` change) | REJECTED `target_reconstruction_unverified` |
| T2 `test_untouched_font_control_keeps_original_family` | fails (Courier) | SUCCESS, span font still Helvetica (real pass) |
| T3 `test_fast_and_htmlbox_commits_render_identically` | fails (pixels differ) | passes tautologically (`_classify_insert_path` is reached only at `pdf_text_edit.py:3415`, after the tiered success return at `:5084`) |
| T4 `test_commit_never_moves_neighbor_blocks` | fails (neighbor moved) | REJECTED `growth_outside_page` (`model/text_commit/plan.py:2521-2566`) |
| T5 `test_paragraph_edit_preserves_original_line_breaks` | fails (3 lines -> 1) | REJECTED `multi_span_target` (`pdf_text_edit.py:4752-4756`, before any tier) |

Why T1 is refused: `fitz.TextWriter` + `fitz.Font("helv")` embeds Helvetica as
Type0 with a **CIDFontType0 (CFF)** descendant (`docs/PITFALLS.md:2408-2413`);
the v1 slice refuses it (`type0_descendant_unsupported`,
`test_text_commit_fonts.py:89-106`); for a latin-1 target the CID leg swallows
that into `NO_MATCH` (`model/text_commit/inspect.py:1730-1742`) and
`_reconstruction_aware_reason` relabels it (`pdf_text_edit.py:4262-4274`).
CFF Type0 is S9 "register" only in `plans/task16-4-glyph-coverage-expansion.md`;
nothing planned admits it. **T1 has no exit.**

Why T5 has no planned exit on its current fixture: the edit is heavy -> light, a
*shorter* replacement; `plans/paragraph-reflow.md` D16 (`:182-183`) and Q2
(`:539`) say a shorter replacement does not reflow and "today's path runs
unchanged". Run mode is the shipped default (`view/pdf_view.py:2200-2202`,
`model/pdf_model.py:609`); T5 reaches paragraph mode only through the API
auto-promotion at `pdf_text_edit.py:4134-4151`. Whether D18/Q6 (paragraph-mode
edits use the breaker) overrides D16 for a shorter paragraph-mode edit is
**unresolved in that plan** — recorded there as a question, not decided here.

## Owner decisions (2026-11-02)

- **D1 legacy is unwanted.** `TEXT_COMMIT_ENGINE=legacy` and the independent
  `TEXT_COMMIT_PREVIEW=legacy` (`dto.py:321-327`) are operator escape hatches, not
  supported user configurations. Consequences here: T3 is deleted; no test in the
  characterization file opens the model with `engine="legacy"` any more; T1/T5 are
  re-pointed to the consent route on shipped settings so they survive a later
  retirement of the kill switch. Removing the `engine="legacy"` option itself (17
  other test files still select it) is a separate owner-gated item (TODOS).
- **D2 push-down of a SEPARATE block under the consented rebuild is accepted
  behavior.** `test_edit_text_helpers.py:4779-4791` stays a GUARD; T4 is deleted;
  `paragraph-reflow.md:479-481` already says separate-block cases stay.
- **D3 "will it ever stop being an xfail?"** T1: no (CFF Type0 not planned). T5:
  not on its current fixture (D16/Q2). Therefore neither stays as a strict xfail
  with no exit: both become plain consent-route characterizations with teeth
  (PITFALLS 1423 pattern), each carrying a comment naming the intended behavior
  and the condition under which the expectation flips. T5 is listed in
  `paragraph-reflow.md` §7.2 so nobody "fixes" it silently.
- **D4** the `_changed_pixel_pct` self-test ships in the same commit as the
  skip-block deletion (S1).
- **D5** `scripts/completion_gate.py:126` is re-pinned in S1. Mechanical: a
  fast-worker (haiku) does it; hash the LF bytes on disk with
  `Get-FileHash -Algorithm SHA256`, never by running `completion_gate.py`
  (it rewrites `test_artifacts/.completion_proof.json` and, on an all-pass, chains
  into `verify_no_jump._run_full_suite`, which runs `pytest test_scripts/` in one
  process — forbidden by CLAUDE.md).

## Affected modules

- `test_scripts/test_text_commit_characterization.py` — rewritten (docstring,
  `_open_model`, T1, T5; T2/T3/T4 removed with `base14_pdf`,
  `_span_fonts_containing`, the `pdf_text_edit_module` import).
- `test_scripts/test_text_commit_no_silent_legacy.py` — gains T2's green twin
  (reuses `SHIPPED :58`, `_State :121`, `_NoLegacy :143`, `_assert_rejected :168`).
- `test_scripts/test_no_jump_editor_geometry.py` — `:1751-1878` deleted,
  `PreviewRenderer` dropped from the import tuple `:13-20` (sole F401 orphan),
  self-test added after `:1750`; file stays LF on disk (`.gitattributes:36`).
- `scripts/completion_gate.py:126` — new SHA-256; `:111` and `:159` dangling
  pointers (nonexistent `scripts/_print_pinned_hashes.py`, never-committed gate
  plan) repointed to `TODOS.md` "Completion-gate trust chain" (free; no other
  file pins `completion_gate.py`).
- `model/pdf_text_edit.py:901-906`, `:3357-3358` and `view/text_editing.py:1138-1141`,
  `:1208` — docstrings/comments claim the view preview routes through
  `_classify_insert_path` / is pixel-identical to the commit; false (the view's
  `PreviewRenderer` always uses `insert_htmlbox`, `view/text_editing.py:1138-1146`,
  and no view/controller code calls the classifier). Reworded in S2.
- Docs: `docs/ARCHITECTURE.md:1118-1122`, `docs/PITFALLS.md:3592-3597` (Fix text is
  wrong: the xfails were pinned to `engine="legacy"`, not "reworded to xfail
  because refused") + one new entry + `docs/PITFALLS_INDEX.md` regen,
  `plans/paragraph-reflow.md:451-481` (§7.2), `test_scripts/TEST_SCRIPTS.md:80`,
  `TODOS.md` (dated note under the characterization history line `:1610`; dated
  line in "Completion-gate trust chain" `:1304-1337`; new owner-gated item for
  retiring the legacy engine option). `.codegraph` re-index.
- Leave as history: `evals/blackbox_prompts.md:434`,
  `docs/history/reports/2026-05-19-glyph-jump-elimination-report.md:93`,
  `docs/history/TODOS-archive.md:243`, `plans/archive/*` "377 passed, 6 skipped" lines,
  `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md:229-272`.

## Design

### Hardening rule for every kept characterization (applies to T1, T5, the self-test)

A `pytest.mark.xfail(strict=True)` without `raises=` is satisfied by ANY exception;
this file already went vacuous once after the no-silent-legacy flip
(`plans/archive/Integrate_proven_PDF_editing_methods_into_the_official_editor.md:931-939`,
PITFALLS 3592). With D3 no xfail remains, but the same discipline applies to the
plain characterizations: **plain asserts on the branch preconditions first**
(result is SUCCESS; `confirm_fallback` asked exactly once; the
`_apply_redact_insert` spy called exactly once; `outcome.status is DEGRADED_COMMITTED`,
`outcome.tier is TIER2_LEGACY`, `fallback_chain == ("tier0:<reason>", "legacy")`
built by `_pending_legacy_fallback_chain` `pdf_text_edit.py:4874`;
`legacy_commit_outcome` at `dto.py:412-423`), **then** the behavior assert. A
refusal, a crash, or tiered later admitting the case all go red loudly.

### T1 -> plain consent-route characterization (`test_consented_rebuild_substitutes_the_font_resource_on_a_cff_type0_page`)

- Settings: `PDFModel(text_commit_settings=TextCommitSettings())`; assert
  `engine == "tiered"` first.
- Spy: wrap `model._apply_redact_insert` in a counting pass-through.
- Act: `_edit(model, "Alpha embedded", "Alpha embedded lines", allow_rebuild=True,
  confirm_fallback=lambda chain: asked.append(chain) or True)`.
- Preconditions (plain asserts): SUCCESS; `len(asked) == 1`; spy count 1;
  DEGRADED_COMMITTED / TIER2_LEGACY; chain length 2, `chain[0].startswith("tier0:")`,
  `chain[-1] == "legacy"`; "Alpha embedded lines" in page text. Do NOT pin the
  literal `tier0:target_reconstruction_unverified` (masked code, see Risks).
- Behavior assert (the characterization): `_page_font_types(page)` after !=
  `{"Type0"}` before — a substitute resource was written. Comment: intended V2
  behavior is resource reuse; flips only if CFF Type0 is admitted (T16-4 S9) or
  the rebuild learns to reuse the resource.
- Teeth proof at implementation: run once WITHOUT `allow_rebuild` -> must fail at
  the SUCCESS precondition with REJECTED (not at the font assert).

### T2 -> green tiered twin in `test_text_commit_no_silent_legacy.py` (`test_untouched_scalar_font_is_ignored_by_the_tiered_engine`)

- Fixture: `insert_text` helv "Hello World" at (72,100), 595x842, `garbage=0`.
- `TextCommitSettings(engine="tiered")` stated explicitly; assert engine and not
  strict. `fonts_before = page.get_fonts(full=True)`; install `_NoLegacy`.
- Act: `edit_text` "Hello World" -> "Hello Worlds" with `font="cour"`, no
  `style_overrides`, no `allow_rebuild`.
- Assert order: (1) SUCCESS; (2) COMMITTED, tier in HIGH_FIDELITY_TIERS,
  `fallback_chain == ()`, `legacy.calls == []`, every `font_outcomes[].action ==
  SOURCE_RESOURCE_REUSED` (Tier 1 requires it: `model/text_commit/engine.py:231-244`,
  `:306-319`; `patch.py:397-442`); (3) "Hello Worlds" in page text; (4) every span
  containing it has "helvetica" in the font name and `get_fonts(full=True) ==
  fonts_before`; (5) optional save/reopen. Optional parametrize over `size=14.0`,
  `color=(1,0,0)`.
- Why not vacuous: the scalar never reaches tiered (`edit_text` forwards only
  `style_overrides` and `new_rect`, `pdf_text_edit.py:5062-5065`; signature
  `:4730-4739`), so the twin goes red exactly when the scalar is wired in, when
  Tier 1 embeds a substitute face, when success silently falls back (spy +
  Courier), or when the commit is a no-op (text check).
- **Red-light substitute (corrected by the refuter):** the legacy control run
  must use a body WITHOUT the `_NoLegacy` spy and WITHOUT the chain/tier asserts
  (they fire first), i.e. only SUCCESS + the family check under
  `engine="legacy"`; expect Courier.
- Legacy T2 is deleted (D1: the View cannot send an unchosen conflicting scalar,
  `view/text_editing.py:3279-3297`; the API-level pin guards nothing a user reaches).

### T3 -> delete

Tautological under tiered; even under legacy it compares two commits, never
asserts the forced hook ran, and nobody pursues pixel identity between two MuPDF
writers. The htmlbox-preview-vs-fast-commit divergence exists only under
`TEXT_COMMIT_ENGINE=legacy` or `TEXT_COMMIT_PREVIEW=legacy` (D1: unsupported).
Fix the three stale docstrings (see Affected modules). No tiered pixel twin: the
plan preview and the commit are bound by token
(`test_text_commit_preview_contract.py:239`), and byte-equal rasters are not
guaranteed (`oracle_twins.py:408-416`).

### T4 -> delete

Properties pinned elsewhere: legacy separate-block push-down GREEN and
SUCCESS-first at `test_edit_text_helpers.py:4779-4791` (D2 keeps it a guard);
tiered V0c "non-target span geometry changed" and V0d "pixels changed outside the
target halo" (`model/text_commit/verify.py:738-782`); `growth_outside_page` pinned
at `test_text_commit_trm_growth_directions.py:340-351`,
`test_text_commit_tier1_slice1.py:708`, `:775`, `test_text_commit_preview_parity.py:133`.
Forward risk if kept: after paragraph-reflow Q1 the fixture would end in
`REFLOW_DOES_NOT_FIT` — a wrong-reason xfail. Record the deletion in
`paragraph-reflow.md` §7.2.

### T5 -> plain consent-route characterization (`test_consented_paragraph_rebuild_rebreaks_the_paragraph`)

- Same route as T1 (shipped settings, `allow_rebuild=True`, counting
  `confirm_fallback`, `_apply_redact_insert` spy).
- Preconditions: SUCCESS; asked once; spy once;
  `fallback_chain == ("tier0:multi_span_target", "legacy")`; TIER2_LEGACY;
  "light" present, "heavy" absent.
- Behavior assert: committed line count == 1 (the rebuild re-breaks at the widened
  box). Comment: intended behavior is 3 lines with the same first words; flips
  when `plans/paragraph-reflow.md` D18/Q6 is confirmed to cover shorter
  paragraph-mode edits (D16/Q2 currently excludes them) — recorded in §7.2.
- A red run on the consent route is REQUIRED at implementation: the probe
  collapsed 3 -> 1 under `engine="legacy"`; the consent route shares
  `_apply_redact_insert` but was not executed. If the count differs, pin the
  measured value and say so in the comment.
- This remains a product defect reachable by a user who picks 段落 or edits a
  paragraph without a span id; it is characterized, not accepted.

### Skipped block -> delete; `_changed_pixel_pct` self-test; re-pin

- Delete `:1751-1878` as one contiguous range (AC 2 banner, `PIXEL_CASES`,
  `test_preview_pixel_diff_under_one_pct`, `test_pixel_diff_negative_control_bad_font_size`).
  File ends after the blanking-detector test `:1750` plus the new self-test.
- Remove `PreviewRenderer,` from the import tuple `:13-20` (used only at `:1801`,
  `:1859`). Keep `_changed_pixel_pct`, `_save_artifacts`, `_make_diff_image`, `fitz`,
  `QImage`, `patch`, `product`, `os`, `json`, `Path` (all have live users).
- No coupling: skipped tests never reach `_append_to_manifest` (`:87`);
  `verify_no_jump._REQUIRED_PIXEL_CASES = []` (`:126`); the exact-set check
  `:303-309` would REJECT `pixel_*` ids if the tests were ever un-skipped (keeping
  them skipped is a trap); `test_artifacts/` is gitignored; nothing asserts a skip
  count (`run_suite.py:941-969` only tallies).
- Replacement `test_click_to_edit_qtest_integration` (`:736`) is unskipped,
  `needs_fixtures`, its three PDFs are in `test_files/`; CI deselects
  `needs_fixtures` (`.github/workflows/ci.yml:314`) — the deleted tests did not run
  in CI either, so nothing is lost there.
- Gap the self-test closes: `_changed_pixel_pct` runs zero times in CI (every
  caller is under `needs_fixtures`) and every live assert on it is an upper bound.
  `test_changed_pixel_detector_catches_a_known_change(qapp)` beside `:1736`:
  identical 40x20 -> 0.0; left 10 columns white->black -> `approx(0.25)`; every
  channel off by 5 (delta <= 20) -> 0.0; 40x20 vs 42x20 -> `approx(40/840)`
  (non-overlap counts, `:143-146`); 40x20 vs 44x20 raises "size mismatch"
  (`:123-128`); null `QImage()` raises "zero dimensions" (`:115-122`). Fill with an
  int as `:1741` does, or add `QColor` to the `PySide6.QtGui` import at `:11`
  (PITFALLS 3606: never a raw `0xAARRGGBB` on RGBA8888). Must NOT call
  `_save_artifacts` (would register an id outside the gate's expected set); say so
  in a one-line comment.
- Teeth proof (green-by-construction, PITFALLS 1423): three temporary mutations
  of `_changed_pixel_pct` — return 0.0; `delta > 20` -> `> 2000`; drop `extra` —
  each must turn the self-test red; restore.
- Re-pin `completion_gate.py:126` per D5 after the final byte state of the test
  module. Leave the other pins alone (`:117-119`). The gate is dormant (no CI job
  or hook runs `completion_gate.py` / `verify_no_jump.py`; `.claude/settings.json`
  registers only the ruff PostToolUse hook; TODOS `:1240-1244` calls the Stop-hook
  gate a permanent no-op), so this keeps a tripwire tidy, nothing more.
- Defer: `verify_no_jump.py:111` stale comment and the dead `pixel_` plumbing
  (`:126`, `:159-162`, `:291`, `:717-719`) — editing that file costs the `a037795f`
  re-pin plus the PITFALLS 1430 ignore-list re-audit; touch it when it is next
  edited for another reason.

## Steps (each is one commit; the owner commits)

- **S1 — skipped block (mechanical; fast-worker, haiku).** Delete `:1751-1878`;
  drop `PreviewRenderer` import; add the self-test; run
  `.venv\Scripts\python.exe -m pytest test_scripts/test_no_jump_editor_geometry.py -q --tb=short -k "changed_pixel_detector or blanking_detector"`
  to a file; mutation proof x3 (one pytest at a time); `ruff check .`; re-pin
  `:126` by `Get-FileHash`; repoint `:111`/`:159`; `TEST_SCRIPTS.md:80`; dated TODOS
  line in "Completion-gate trust chain". Edit tool only (LF on disk).
- **S2 — T2 twin, T3/T4 deletion (sonnet).** Write the twin in
  `test_text_commit_no_silent_legacy.py`; legacy control red run (spy-free body,
  expect Courier) to a file, record the output in the Log; delete T2/T3/T4 and the
  now-unused `base14_pdf`, `_span_fonts_containing`, `pdf_text_edit_module` import;
  reword the three stale docstrings; `ruff check .`; run both files.
- **S3 — T1/T5 consent-route characterizations (sonnet).** Rewrite `_open_model`
  (shipped settings) and the two tests per Design; red/teeth runs (T1 without
  `allow_rebuild` -> REJECTED at the precondition; T5 measured line count);
  rewrite the module docstring (legacy-rebuild characterizations, each naming its
  route and its flip condition). Run the file; `ruff check .`.
- **S4 — docs and close-out.** `ARCHITECTURE.md:1118-1122` (the net is now two
  consent-route characterizations + where T2/T3/T4's properties live + the
  kill-switch preview limitation); PITFALLS 3592 Fix correction + new entry
  "strict xfail without `raises=` accepts any exception; put branch preconditions
  in plain asserts" + `python scripts/build_pitfalls_index.py`;
  `paragraph-reflow.md` §7.2 (T5 flip condition, T4 deletion, D16-vs-D18 question
  for shorter paragraph-mode edits); TODOS (dated note; owner-gated item: retire
  the `engine="legacy"` option and the two env switches — 17 test files still
  select legacy); `test_text_commit_fingerprint_roundtrip.py:32` cites this file's
  xfail convention — reword once the file has zero xfails;
  `python .codegraph/indexer.py`; `ruff check .`; `scripts/run_suite.py`;
  `git mv` this plan to `plans/archive/`.
- Review: `plan-code-reviewer` on the S2+S3 diff against this file.

## Test strategy

- Characterizations (T1, T5, self-test) are green by construction; their teeth
  are proven by the precondition failure runs and the mutation runs listed above,
  recorded in the Log with the pytest tail.
- The T2 twin gets a genuine legacy red run (Courier).
- Never two pytest processes; never bare `pytest`; whole suite only through
  `scripts/run_suite.py`.

## Dead ends and risks

- A tiered twin of T1/T4/T5 on their own fixtures is impossible: all three are
  refused before or at tier admission, so any "property holds" assert would hold
  only because nothing was edited (PITFALLS 3592). A Tier-1-admissible shortened
  T4 tests a weaker property (in-line horizontal growth) that V0c/V0d already
  enforce — not worth a test.
- T1 fixture change to TrueType `Font("cjk")` + hand-authored hex `Tj`
  (`test_scripts/type0_fixture_builder.py`) would make tiered admit it, but then
  it tests a different property (Type0/CIDFontType2 reuse) already pinned at
  `test_text_commit_source_show_commit.py:158`, `:199` and
  `test_text_commit_cid_hex_tj.py:1271`.
- Reason masking (product, out of scope; TODO candidate): on a page whose only
  font is a refused CFF Type0, the user sees `target_reconstruction_unverified`
  instead of `type0_descendant_unsupported` (`inspect.py:1730-1742` surfaces
  `type0_*` only for non-latin-1 targets by design; `pdf_text_edit.py:4262-4274`
  then relabels `NO_MATCH`). Do not pin the literal code in T1.
- `completion_gate.py` pins are probably already stale (`verify_no_jump.py` was
  edited 2026-10-23 for `scripts._pytest_env`, no re-pin recorded) — unverified;
  S1 re-pins only the test module.
- Count expectations in archived plans ("377 passed, 6 skipped") are history;
  do not edit.

## Log

- 2026-11-02 — audit + owner rulings D1-D5; plan opened. No tree edits.
- 2026-11-02 — S1 done (main session, not delegated). Deleted `:1751-1878` by
  byte-truncation at the AC 2 banner (LF kept, verified with `file`); self-test
  uses `Format_ARGB32` + int fills (no `QColor` import, PITFALLS 3606).
  Targeted run: `2 passed, 376 deselected`. Mutations (one pytest each):
  `return 0.0` -> red at `approx(0.25)`; `delta > 2000` -> red at `approx(0.25)`;
  drop `extra` -> red at `approx(40/840)`; restored byte-identical. `ruff check .`
  clean. Whole file `378 passed in 68 s` (fixtures present locally, 0 skipped).
  SHA-256 by `Get-FileHash` = `ddd0725363a200138113a5250d98b10656e1c4a402bde0ec2c9ff5dac756ba38`,
  re-verified with hashlib after the run. `completion_gate.py` NOT executed.
- 2026-11-02 — S2 done (main session). Twin
  `test_untouched_scalar_font_is_ignored_by_the_tiered_engine` added to
  `test_text_commit_no_silent_legacy.py` (imports `HIGH_FIDELITY_TIERS`,
  `FontResourceAction`; local `_span_fonts_containing`). Legacy control (scratch
  copy of the body, `engine="legacy"`, no spy, no tier asserts):
  `AssertionError: family replaced without an explicit user override: {'Courier'}`
  -> `1 failed`. Twin under tiered: `1 passed`. T2/T3/T4 + `base14_pdf`,
  `_span_fonts_containing`, `pdf_text_edit_module` import removed from the
  characterization file (293 -> 152 lines; `2 xfailed` = T1/T5 untouched until S3).
  Docstrings reworded: `pdf_text_edit.py` `_classify_insert_path` + the `:3357`
  comment, `view/text_editing.py` `PreviewRenderer` class + `render` docstring
  (legacy-only; preview is htmlbox-only; tiered previews the plan). no-silent-legacy
  file `40 passed`; ruff clean.
- 2026-11-02 — S3 done (main session). File rewritten: shipped settings in
  `_open_model`, `_ConsentRoute` (counting consent callback + pass-through spy
  on `_apply_redact_insert` + `assert_consented_rebuild` preconditions), T1 ->
  `test_consented_rebuild_substitutes_the_font_resource_on_a_cff_type0_page`,
  T5 -> `test_consented_paragraph_rebuild_rebreaks_the_paragraph`, plus a
  permanent teeth test `test_cff_type0_page_is_refused_without_consent`.
  First run `3 passed` (consent route measured: T1 `{'Type0'} -> {'Type0','Type1'}`,
  chain `('tier0:target_reconstruction_unverified','legacy')`; T5 collapses to ONE
  line `'The quick brown fox jumps over the lazy dog while carrying a light basket'`,
  chain `('tier0:multi_span_target','legacy')`). Teeth mutations: drop
  `allow_rebuild=True` -> both fail at the SUCCESS precondition with REJECTED
  (`target_reconstruction_unverified` / `multi_span_target`); invert T1 font
  assert -> red; `== 3` lines in T5 -> red (`assert 1 == 3`). Restored, `3 passed`.
  Gotcha found: a same-size mutation written within the same second reused
  pytest's assertion-rewrite pyc (mtime+size key), so the T5 mutation first
  ran the T1 mutant; cleared `__pycache__` and reran -> PITFALLS entry in S4.
- 2026-11-02 — S4 done. Docs as listed in the state block. plan-code-reviewer
  (Opus) verdict: ship-with-fixes, no test-code bug; fixes applied: PITFALLS
  "strict xfail" Symptom reworded (the vacuity was found and pinned during the
  step-7 migration; the retirement trigger is the met exit criterion, D3);
  `ARCHITECTURE.md` `PreviewRenderer` bullet (:751) de-stale'd; "legacy-only"
  widened to "or `TEXT_COMMIT_PREVIEW=legacy`" in `_classify_insert_path` docstring
  and the ARCHITECTURE net paragraph; TODOS trust-chain line now cites the
  archive path; no-consent twin now passes `confirm_fallback` without
  `allow_rebuild` so `asked == []` has teeth (`3 passed`). Whole suite
  `scripts/run_suite.py`: `9375 passed, 0 failed, 17 skipped, 0 xfailed, 0 errors,
  0 hung, 0 crashed, 1 rc5-ok in 2319.8s` (was 23 skipped / 5 xfailed). ruff clean.
  Plan moved to `plans/archive/` (it was never tracked, so a plain move; owner
  adds it with the commit). Nothing committed, nothing pushed.
