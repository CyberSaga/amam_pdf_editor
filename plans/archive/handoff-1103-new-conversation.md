# Handoff 2026-11-03: four items for new conversations (6, 7, 9, 11)

## Current state and next step
- Branch `feat/true-text-edge-cases`, PR #43, head ff6607b (pushed). Everything before this file is committed.
- PR #43 CI (run 41642862807): ubuntu advisory leg green (21 min); pip-audit, device-guard, layers, security, mypy, ruff green.
  The windows BLOCKING leg is red with 4 failures, all timing thresholds (item 11 below), none in `run_suite` or the Job Object:
  `test_text_commit_replay_fast_path::test_pathological_inputs_stay_linear[top-level-cm]` (4.000 s vs 4.0),
  `[malformed-cm-blocks]` (6.19 s), `[deep-unclosed]` (5.37 s), and
  `test_text_commit_click_latency::test_grouping_a_page_with_hundreds_of_lines_is_fast` (340 ms vs 300 ms).
  The log has no "could not put pid" and no "exited and left" line, so `AssignProcessToJobObject` worked under the runner.
  Windows full run: 9442 passed, 4 failed, 43 skipped, 0 hung, 0 crashed, 1866 s with `--parallel-lanes`.
- Next: item 11 is the only thing standing between PR #43 and a green blocking leg. Then
  `git mv plans/run-suite-job-object.md plans/archive/` (the CI question 1 and 6 answers are above: nested assignment
  works, no conhost orphan). The other CI-only questions stay open in that plan.
- Items 6, 7, 9 are independent of the PR; owner decides the order.
- 2026-11-03 item 11 IMPLEMENTED, uncommitted: relative speed guards (replay_fast_path, click_latency), heartbeat fix in
  `src/printing/helper_main.py`, 2 PITFALLS entries + index, TODOS:118 closed, :131 updated. Local: both speed files green, mutation
  checks trip, heartbeat 20/20, runner tests green, ruff clean. Next: owner commits + pushes; a green windows leg closes TODOS:131,
  then archive `plans/run-suite-job-object.md`.
- 2026-11-04: item 11 closed (fc5ec80, run 41657681478 green; 56584a6). Workflow wf_9ed5e00e-ece ran items 6/7/9; NOTHING committed:
  - Item 6: read-only inventory (123 uses) + owner decisions O1-O6 in the session scratchpad `lanes/i6/item6-inventory.md`
    (outside the repo). Waits for the owner's O1-O6 rulings; no code changed.
  - Item 7: worktree `../wt_i7` (branch wt/item7), reviewed + one fix round, 88 + 297 + 1167 tests green, ruff/mypy clean.
    Mechanism differs from design (a): `model/doc_bytes.py` replaces PyMuPDF's `JM_embedded_clean` save prelude at import
    (write-back would dirty the Catalog and saveIncr would append it). Owner must ratify. Grok `run_pilot.py` imports
    `model.text_commit.engine` -> doc_bytes, so the next batch exercises it; TODOS:33 ban stays until then.
  - Item 9: worktree `../wt_i9` (branch wt/item9), 12 of 16 rows flipped to `active` on the automated UI run alone
    (11-02 precedent also had an owner hand run; screenshots in scratchpad `lanes/i9/out`); calrgb s0-s3 open (no twin kind
    for base-14 without /Encoding); no grow/shrink edits added. Owner: keep or revert, calrgb, grow/shrink.
  - Merge-back after rulings: both lanes touch TODOS + PITFALLS (expect a PITFALLS conflict); regen PITFALLS index +
    codegraph once; fix stale TODOS:30 wording; then run_suite.py before the commit word.
- 2026-11-04 owner rulings: item 7 lane mechanism (prelude replacement) RATIFIED; item 6 O1-O6 accepted, O2 = future
  feature (TODO candidate, not in scope); item 9 keep the 12 active, calrgb deferred, add grow/shrink edits. Workflow
  wf_9259736f-8a1 runs item 6 slices 1+2 in `../wt_i6` (branch wt/item6) and item 9 grow/shrink in `../wt_i9`.
  Then: merge wt_i7, wt_i9, wt_i6 into the main checkout (uncommitted), TODOS:34 "owner to ratify" -> ratified, regen
  index + codegraph, run_suite.py. Owner verifies in the morning; no commit/push until the owner's word.
- 2026-11-04 night: wf_9259736f-8a1 done, all three reviews pass (0 must_fix). Lanes wt_i7 + wt_i9 + wt_i6 merged into the
  main checkout UNCOMMITTED (git apply --3way; TODOS + PITFALLS conflicts resolved keeping both sides; TODOS:34 says
  ratified; TODOS:33 stale-key note; ARCHITECTURE 1146 sentence rewritten). PITFALLS index (670) + codegraph regenerated;
  ruff, mypy, lint-imports (4 kept) clean. run_suite.py on the merged tree: 9671 passed, 0 failed, 17 skipped, 0 hung,
  0 crashed, 2407 s (junit .run_suite/20261103T212727Z). Next: owner morning check (item 9 hand run) + commit word.
  Agents' provisional decisions for the owner (full text in plans/retire-legacy-engine-option.md and the F30 plan log):
  item 6: TEXT_COMMIT_TELEMETRY warns to remove it (owner 11-04, was silent); benchmark_engine_default_ab.py deleted; shadow_mode test renamed to
  test_text_commit_tiered_integration.py; view/text_editing.py create_text_editor installs the preview hook only when
  `_plan_preview_applies` (needed after P12; no effect on a wired View); one tokenless test reshaped, one preview-contract
  test deleted. Item 9: grow preferred when both legs pass (verapdf takes shrink); natural shorter words for shrinks; all
  12 rows Tier 1 (Tier 0 coverage stays with the 11-02 #eq rows); no symbolic_mac10 grow (refused growth_region_not_blank).
  After the commit word: remove worktrees wt_i6/wt_i7/wt_i9 (`git worktree remove`, never rm -rf: test_files junctions)
  and branches wt/item6, wt/item7, wt/item9; then archive this handoff and plans/retire-legacy-engine-option.md.

## Rules for every new conversation (CLAUDE.md applies; these bite most)
- One pytest at a time: `.venv\Scripts\python.exe -m pytest <file> -q --tb=short`, output to a file. Whole suite only via
  `.venv\Scripts\python.exe scripts/run_suite.py` (about 37 min locally). Never bare `pytest`.
- Red light first. Tests next to the code they pin. `ruff check .` clean. Docs in the same commit: PITFALLS entry plus index regen
  (`python scripts/build_pitfalls_index.py`), ARCHITECTURE when structure moves, TODOS current, plan moved to `plans/archive/`.
- Files are CRLF (TODOS, PITFALLS, plans). Edit with the Edit tool or a newline-preserving script, never `sed -i`.
- Commit only when the owner says. Commit identity: `-c user.name=... -c user.email=...` per the memory note, never `git config`.
  Never push unprompted. No machine paths in tracked files (device-guard).
- Model routing for lanes: Opus / Sonnet / Haiku only, model and effort set on every agent; at most 2 Fable subagents at once.

## Item 11: windows-latest timing thresholds (TODOS:131) plus the flaky heartbeat test (TODOS:118)
Goal: the windows BLOCKING leg goes green without hiding a real regression.
Known facts:
- Failures above; earlier drill runs (2026-10-23) showed the same family: `[malformed-cm-blocks]` 4.12 / 5.72 s,
  `[deep-unclosed]` 4.45 s, fingerprint test 295 ms vs 250 ms. The values move between runs, so a fixed number is the wrong fix.
- The tests assert wall time against a constant. The honest form is relative: time the pathological input against a size-matched
  benign baseline in the same process and assert the ratio (linear growth), or scale the limit by a calibration loop.
- Heartbeat flake: `test_print_subprocess_helper::test_run_print_helper_emits_heartbeat_during_long_submission`; the helper's
  heartbeat thread can emit after the final event (`event_types[-1] == 'succeeded'` saw `heartbeat`). Fix in the helper: stop and
  join the heartbeat before emitting the result. No Qt, passes alone. Plan record: `plans/archive/test-suite-never-hangs.md` log S6-5.
- ubuntu (advisory) had 13 other failures in TODOS:131 (Windows-path assumptions, RSS bound, ext-B font, rotated-caret cases);
  this run's ubuntu leg was green, so re-measure before touching them.
First step: read the four tests, run each alone locally and note the local margin (replay test local time vs 4.0 s), then write
the relative-assertion version red-first (a deliberately quadratic input must still fail it).
Acceptance: the four tests green on a windows-latest CI run, a mutation check that a quadratic implementation still fails, the
heartbeat test green 20 times in a loop, TODOS:118 and 131 updated.

## Item 6: retire the legacy engine option (TODOS:22)
Goal: remove `TextCommitSettings(engine="legacy")`, `TEXT_COMMIT_ENGINE=legacy` and (owner to decide) `TEXT_COMMIT_PREVIEW=legacy`
(`model/text_commit/dto.py`). The consented rebuild (改用重建文字, `_apply_redact_insert`) stays; only the option goes.
Owner 2026-11-02: 「我早就不想要 legacy 了」. Go/no-go and scope are the owner's; the owner has not yet said go.
Known facts:
- 20 test files mention `engine="legacy"` or `TEXT_COMMIT_ENGINE` (TODOS says 17): test_edit_text_helpers (19 uses), test_text_commit_degrade_visibility (10),
  test_text_edit_refusal_messages (8), test_overlap_textbox_edit (5), test_text_commit_settings (5), test_text_commit_consent_flow (3),
  test_text_commit_no_silent_legacy (3), test_text_commit_characterization (2), test_text_commit_source_show_commit (2), and one each in
  test_multi_tab_plan, test_no_jump_editor_geometry, test_paragraph_multi_font_target, test_rtl_edit_growth,
  test_text_commit_default_engine_ux, test_text_commit_maintenance, test_text_commit_shadow_mode, test_text_geometry_page_rotation;
  `test_text_commit_shipped_defaults`, `test_text_commit_finalize_by_result` and `test_text_commit_ui_real_corpus` name the env var.
- History to cite in the PITFALLS note: the app once shipped `engine="legacy"` (memory note legacy-engine-was-the-shipping-default;
  TODOS around 2683-2740), the default flipped later, and `TEXT_COMMIT_ENGINE=legacy` was kept as a kill switch (TODOS about 2809-2865).
First step (no code): table of the files, one row per use: pins legacy-only behavior (delete or rewrite against the consented
rebuild) vs. merely needs a non-tiered control (swap to the consented-rebuild path or a tiered setting with the tier forced off).
Then put the table and the `TEXT_COMMIT_PREVIEW` question to the owner before editing.
Acceptance: option and env var gone or rejected with a clear message, no test selects `engine="legacy"`, every behavior the
legacy-pinned tests protected is either still covered through the consented rebuild or consciously dropped (listed), full suite green,
PITFALLS note on the kill-switch history.

## Item 7: `/PageMode` overwritten by `/UseAttachments` (TODOS:34)
Goal: saving a PDF that has attachments keeps the author's Catalog `/PageMode`.
Owner 2026-11-02: fix as a separate product item. Brief v17 rule: no new issue8844 hints while this is open (every show fails structure).
Known facts:
- Cause: PyMuPDF's `JM_embedded_clean` prelude writes `/PageMode /UseAttachments` unconditionally (`pymupdf/__init__.py` near 19311).
  `model/doc_bytes.py:188` runs it, and the text engine's default serializer (`model/text_commit/engine.py:108`) runs it inside
  `prepare()`, so the live document changes before any commit. An author's `/UseOutlines` is lost; viewers open the attachment pane.
- Conflict: the tobytes byte-identity pin `test_scripts/test_doc_bytes.py:124`. PITFALLS index entry 5564 records the symptom.
- Found by round 12 issue8844.
Design choice for the owner (give a recommendation first): (a) read `/PageMode` from the Catalog before the snapshot or save and
write it back afterwards (restore); (b) avoid the prelude when the document has no embedded-file change (needs a PyMuPDF call
path without `JM_embedded_clean`); (c) accept and document. Recommendation: (a), restoring only when the key existed before
or removing the key when it did not, and updating the byte-identity pin to compare against the restored form.
First step: reproduce with a tiny PDF that has `/PageMode /UseOutlines` plus one embedded file, save through `doc_bytes` and through
the engine's `prepare()`, show both rewrite the key (red), then implement.
Acceptance: both paths keep `/PageMode` (present, absent, and each standard value), the byte-identity pin updated with a stated
reason, the live document is unchanged by `prepare()`, issue8844 structure phase passes in the Grok runner, PITFALLS 5564 entry
updated, TODOS:33 and 34 updated.

## Item 9: F30 click activation (TODOS:35, plan `plans/true-text-f30-click-activation.md`)
State: all plan steps done and green, uncommitted at the time of the plan (check `git log` for whether the owner committed
755e7d2 and the follow-up). What remains is the follow-up list in TODOS:35, each a separate decision:
- Twins pin Tier 0 only; Tier 1 on these font structures is proven only by the real-file rows, which run only where `test_files/`
  exists (not CI). Option: build Tier 1 twins whose replacement changes width.
- The inline editor's preview clips overflowing text (UX).
- A two-line selection goes to the consented rebuild with a substitute font.
- 16 more rows pass the model hit-test but were never UI-run; 21 rows open one word on click.
First step: read the plan's log and `git log -5 -- plans/true-text-f30-click-activation.md`, confirm the 12 rows are `active`,
then ask the owner which follow-up to take (my order: UI-run the 16 rows, since it moves rows to `active`; then Tier 1 twins).
Acceptance per follow-up: the manifest row state moves with evidence, the UI umbrella run and click-path loops pass, TODOS:35 shrinks.

## Still open elsewhere (not in this handoff)
Brief v17 (TODOS:33), Grok `pixmap_meta` (TODOS:10), POSIX E5 and the exited-root group on POSIX (TODOS:17 tail),
the `.gitattributes:45` "origin/main is not a valid attribute name" noise, R2's `number_of_h_metrics = 0` guard (conservative, left).
