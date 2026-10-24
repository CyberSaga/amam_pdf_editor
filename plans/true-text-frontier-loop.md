# True-text frontier loop (Grok Bot -> Claude Code)

## Current state and next step (2026-10-24)

Purpose: Grok Bot explores the true-text frontier on copies and writes evidence bundles. Claude validates and re-derives each bundle at HEAD, then turns it into manifest rows, red tests and gated engine slices.
This plan covers only the loop: rounds, the bundle contract, ingestion, the manifest and enabling slices I0a–I0c. T16-4X (`plans/task16-4-glyph-coverage-expansion.md`) is the plan of record for every engine slice.

- Design: converged. Six adversarial repair rounds today (serious findings 17 → 12 → 7 → 3 → 2 → 1 → 0); the round-7 refuter did not refute v7 (two minors left, §5 R7-1/R7-2). Record: `plans/true-text-frontier-design.md` (PART 2/3 + appendices of design v7).
- I0d (= T16-4X S10, inline `/Annots` dictionaries refuse with `annotations_not_indirect`) is in the working tree, uncommitted. 32 tests in `test_scripts/test_text_commit_direct_annots.py`; three fix rounds plus a final refuter; verdict ship.
- Brief v2 archived verbatim at `plans/grok-briefs/brief-v2.md` (789 lines, zh-TW, PART 1 of design v7 plus §6 item 9 `DONE.json`). Pending owner decisions 1–7 before pasting.
- I0c landed 2026-10-24, uncommitted: `scripts/evidence_schemas/*.v2.schema.json`, `scripts/evidence_bundle.py` (validate, find-show), `scripts/evidence_rederive.py` (rederive, emit), 262 + 94 contract tests, `test_scripts/fixtures/public_corpus_sha256.json`. ruff/mypy clean. Six validator findings stay OPEN by decision (§5 V1–V6): no further repair before a live run.
- Owner critique 2026-10-24 accepted: seven contract rounds without one Grok run was the wrong order. Design repair is frozen. The next action is the PILOT round: `plans/grok-briefs/brief-v2-pilot.md` (47 lines, three R0 controls on hvac only, self-validate loop, `## Pilot limits` in README). Brief v2 proper is sent only after the pilot triage.
- Pilot tolerates `tracked_diff_empty=false` (recorded, status blocked by rule 1). Committing S10 + I0c first makes the pilot clean; the owner decides.

| class_id | name | cases | lineages | grok_state | manifest_state | slice | next |
|---|---|---|---|---|---|---|---|
| R0 | calibration: CTRL_POS_T0/T1, CTRL_NEG, CTRL_DET, CTRL_SYN_T0/T1, 7 canaries | 0 | – | not briefed | n/a (historic 14 → I0a) | – | round 2 R0 |
| F30 (B/W/N) | simple fonts, whole-show edit | 0 | 0 | not briefed | none | I1 (S11, G1′) | round 2 |
| F1 | struct / Artifact / BMC wrappers | 0 | 0 | not briefed | none | I2 (S2) | round 2 |
| F2 (I/R/G/K) | kerned multi-item TJ | 0 | 0 | not briefed | none | I3–I5 (S4a/b/c) | round 2 |
| F3 | substring of one string item | 0 | 0 | not briefed | none | I6 (S5) | round 2 |
| F17 | untracked advance between shows | 0 | 0 | not briefed (measure first) | none | I7 (S12) | round 2 |
| F4 / F6 | Form XObject text / ink beside the growth strip | 0 | 0 | census only | none | needs own plan | round 2 census |
| F18 | `3 Tr` invisible text | 0 | – | probe code only | none | (S7) owner gate | decision 1 |

Owner decisions 1–7 (design PART 3), DECIDED 2026-10-24, all per recommendation:
1. Authorized: F30, F1, F2 (S4a/b/c incl. F2K) as product classes beyond HVAC 10 + ECC 4. F18 stays refused.
2. X5 deferred: F2 starts at S4a + F2K; X5 is ratified or not from round-2 remeasured `internal_kerns_dropped` and in-show deviation numbers plus 6x crops.
3. Pilot JSON and INGEST reports are not committed. Proprietary `replacement` strings never enter the tracked manifest (hash only). Codex stays off; the independent peer is a second fable/opus refuter.
4. Part 5 closure: the owner performs the real-IME acceptance on an `ecc-dwg.pdf` copy, then `git mv` part 5 and its parent to `plans/archive/`. Blocks I0a only.
5. `standard_14_table` accepted as the independent glyph leg for F30N.
6. `cmap_31_reverse` accepted for nameless TrueType subsets.
7. office-report-23p (880a637f…) is registered in manifest `corpora` (slug, sha256, `provenance="proprietary"`, own `lineage_id`, `ui_shard` 0; no client string). Until I0a lands, brief v3 §0 lists it as pre-registered in acceptance CORPORA terms only if the registry resolves it; otherwise rows on it stay census-only.

- PILOT RAN 2026-10-24 (`_evidence_pilot/20261024_0702_r2`, 3 controls, DONE sha ok, tracked tree untouched, device-guard clean). Validator at HEAD agrees with Grok's self-validation byte for byte: only `schema_const`×4 + `tracked_diff_not_empty`×3, all from the uncommitted tree. Rederive (on a scratchpad copy with the flag flipped, harness smoke only) remeasured all three at HEAD with ZERO divergences (adv 1419.94/726.19→770.15, K 333.0, growth 2.1095 pt) and quarantined `provenance_unverified` because Grok wrote `local_unrecorded` for hvac. The loop is proven end to end; what remains is a clean-tree rerun.
- Pilot triage (brief v3 inputs): (a) brief 5.2 structure: Grok compared `xref_object(compressed=False)` text of stream objects and flagged xref 9917 (/Type /XRef) because MuPDF regenerates the second /ID on prepare; acc `_object_entry` compares streams by decoded bytes only → say so explicitly, contract overreach. (b) brief 5.1: "adv must equal prepared.source_advance" is false for Tier 0 (PreparedEdit leaves 0.0; validator already tier-1-only) → fix the sentence. (c) hvac provenance: state `proprietary` + registered via acceptance `CORPORA`; calibration strings exempt from the null-original rule. (d) Poppler: owner must export `PDF_EDITOR_PDFTOPPM` in Grok's shell (pilot had render_poppler blocked). (e) Grok found MuPDF's image store caches a down-sampled image after the 96 dpi growth render and changed later 2x renders by 24777 px until the store was emptied → add to brief render rules. (f) CTRL_NEG with mutation=null: neighbours counters have no null form; replacement_provenance lacks an unmappable value → schema gap. (g) Grok ran read-only inspection helpers from the OS temp dir; allow or forbid explicitly.
- CLEAN RERUN 2026-10-24 (`_evidence_pilot/20261024_1114_r2`, HEAD 762075c, `tracked_diff_empty=true`, ~4 min): validator at HEAD → ok, ZERO violations; Grok's self-check had only `done_missing` + `file_missing(VALIDATION.self.json)` (ordering: it validates before writing DONE.json → v3 item (h), `--self-check`). Poppler still unset → CTRL_POS_T0/T1 `insufficient_evidence`, CTRL_NEG `probe_rejected` (`type0_unicode_unmapped`), calibration `fail` by rule 5.3/4. Rederive again quarantined all three `provenance_unverified` (hvac written as `local_unrecorded` → v3 item (c)). XRef 9917 flagged again (item (a)). Pilot JSON is NOT committed (owner decision 3, 2026-10-24); INGEST/ is gitignored.
Next step (2026-10-24, after the v3 workflow): brief v3 + validator V1–V8 + R7-1/R7-2 + owner decisions 1–7 (§0.2) are in the MAIN tree, UNCOMMITTED (10 tracked files + untracked `plans/grok-briefs/brief-v3.md`; worktree `wt/v3-validator` removed). Verified: contract 360 passed, rederive 106 passed/2 skipped, ruff clean, 1114 bundle still 0 violations. Before pasting v3: (1) commit these together (the verbatim schema test reads brief-v3.md; Grok refuses a dirty tracked tree), (2) owner creates `test_files/.redaction_denylist.txt` (gitignored; v3 batches with hvac rows are refused `denylist_missing` without it), (3) `PDF_EDITOR_PDFTOPPM` exported in Grok's shell (done per owner). Then paste brief v3 in pilot mode once (expect calibration ok, no quarantine) → round 2 proper.
---

## 1. Goal, scope, sources

- **Goal:** each Grok round adds real-corpus evidence for one frontier class at a time. That evidence becomes manifest rows and red tests, then a bounded engine slice. Bundle bytes are never trusted as product success.
- **In scope:**
  - the round protocol;
  - the bundle contract (brief §5–§6);
  - the ingestion scripts;
  - the corpus manifest and loader;
  - the oracle extraction;
  - slices I(-1), I0a, I0b, I0c.
- **Pointers only:** I0d and I1–I9/N1 slice state lives in the T16-4X §4/§7 log.
- **Sources:**
  - `plans/true-text-frontier-design.md`: design v7 PART 2 §2a–§2d, PART 3, Appendix A (rejected refutations) and B (change log by finding id).
  - the brief: `plans/grok-briefs/brief-v<n>.md`.
  - the Sep-24 14-case integration: `plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md` and `plans/true-text-ui-part5.md`.
- **Acceptance standard:** `.agents/skills/pdf-text-fidelity/references/acceptance.md` (visual consistency before/after a real edit, incl. save/reopen). Existing evidence is in `references/evidence.md`. Both are cited here, not restated.
- Round 1 was the Sep-24 Type0 batches (HVAC 10 + ECC 4, fully integrated). The next Grok round is round 2 (`_r2`).
- Abbreviation: acc = `test_scripts/test_text_commit_real_corpus_acceptance.py`.

## 2. Round protocol (design §2d)

1. **Brief.** `plans/grok-briefs/brief-v<n>.md` is tracked and holds no machine paths or client strings. The only exception is the five calibration literals, which move to `true_text_corpus.CALIBRATION_STRINGS`.
   - It is sent only when S10 is committed and the tracked diff is empty.
   - I0c, including the tracked `public_corpus_sha256.json`, must land before ingest. Otherwise every `public` / `local_unrecorded` row is quarantined `provenance_unverified`.
2. **Bundle.** Grok writes `_evidence_pilot/<YYYYMMDD_HHMM>_r<n>/` with the brief §6 batch files:
   - METHODS_AND_EVIDENCE_PLAN.md, with a fenced pre-registration JSON block, written before any mutation;
   - `run_pilot.py`, which needs `--plan-sha`;
   - cases.json and `cases/<id>/case_record.json`;
   - PARENT_SUMMARY.json;
   - per case: neighbours.json, text_state.json and mutation.json;
   - at batch level: `CROSS_BATCH_DELTA.json`, REDACTION.json, INVENTORY.md, README.md and `VALIDATION.self.json`.
   - Every PNG is named `render-*`, and every PDF sits under `candidates/` (gitignored, `.gitignore:91-94`).
3. **Completion signal.** Grok writes `DONE.json` last, holding `{stamp, case_count, parent_summary_sha256}`.
   - Claude watches for it on the file system (Monitor until-loop on `_evidence_pilot/*_r<n>/DONE.json`). Claude does nothing until the sha matches PARENT_SUMMARY.json.
   - There is no webhook, no debug port and no new credentials (owner assessment 2026-10-23).
   - Brief v2 §6 item 9 specifies it (stamp, case_count, parent_summary_sha256).
4. **Validate.** `scripts/evidence_bundle.py validate <batch> --out _evidence_pilot/INGEST/<stamp>/VALIDATION.json` reports every violation at once and exits 1 on any.
5. **Rederive at HEAD** (`scripts/evidence_rederive.py`, writes `rederive_report.json`):
   - Bundle code is never imported or executed.
   - Sources are resolved by `source.sha256` from the local registry only:
     - the manifest `corpora` (proprietary and `local_unrecorded`);
     - `public_corpus_sha256.json`;
     - the allowlisted synthetic builder.
   - Grok's `candidates/<id>/before.pdf` is never opened.
   - Product rows are re-probed and re-committed. Experiment and canary rows are re-applied from `changes[]` bytes and re-measured by `replay_experiment`. CANARY_UNSAVED is recorded as `skipped`.
6. **Triage.** An opus reader goes through VALIDATION, the rederive report and every `language_warnings` line.
7. **Emit rows** (`emit_rows`), from the rederive result at ingest HEAD:
   - A row that commits at HEAD and passes every oracle → `engine_active` guard.
   - A row refused at HEAD → `candidate` with `expected_reason_at_head`.
   - A row that commits at HEAD but fails an oracle → `state=candidate`, `kind=refusal`, `expected_reason=null`, `expected_reason_at_head="COMMITTED"`, `false_safe_oracle=<helper>`, `owned_until_slice` mandatory, plus a `false_safe_suspect` finding (design H5). The candidates watch XFAILs it only while prepare/commit succeed and the named helper fails; excluded from `refusal_cases()` until retired.
   - A quarantined case emits nothing.
   - `candidate` rows are run by the strict-xfail watch file. That watch is not the red light.
8. **Red (explicit, in T16-4X).** The slice's red commit moves its claimed `candidate` rows to `engine_active` and runs acc + refusals red, pasted into the T16-4X log. The slice's positive twin is still a reason code.
9. **Fix.** The next slice from §4, in order. Never reorder to chase one case.
10. **Re-gate.** acc, refusals, candidates watch, frontier twins, the rebuild_action reason pin and the UI shards, all through `scripts/run_suite.py`.
    - A row becomes `active` only when it is click-reachable, the click-path loops pass, and the UI shard passed in the same or a later commit.
    - `owned_until_slice` rows are retired by name.
    - Owner real-UI acceptance comes last.
11. **Re-brief.** Brief n+1 carries a feedback block per class:
    - `integrated`, `regression_control`, `by_design_refusal`;
    - `needs_second_case`, `needs_negative`;
    - `validator_rejected`, `quarantined`, `deferred`;
    - `product_finding`;
    - plus the calibration result and HEAD.
12. **Cross-batch.**
    - Merge `CROSS_BATCH_DELTA.json` into `_evidence_pilot/CROSS_BATCH/CROSS_BATCH_SUMMARY.json` and update `FRONTIER_STATUS.json`.
    - `20260924_2005_cross_batch` stays frozen.
    - Add one TODOS.md line per round.

Loop gates:
- No new round before the previous one is ingested.
- A class drops out after 3 rounds with no new lineage (`insufficient_evidence`).
- A contract change means a new schema filename and `brief_revision` + 1. Schemas are never edited in place.
- Reproducible needs:
  - 2 or more remeasured `save_reopen_pass` positives from 2 or more lineages (brief §3.0, §3.7);
  - for Tier-1 classes, at least one Tier 0 and one Tier 1 positive on different shows;
  - a pre-registered negative.

## 3. Modules (design §2a; all planned unless marked)

| Path | Purpose | Slice | State |
|---|---|---|---|
| `scripts/evidence_schemas/true_text_{case,parent,plan}.v2.schema.json` | brief §5.1/§6.1 verbatim; versioned by filename | I0c | planned |
| `scripts/evidence_bundle.py` | stdlib validator: `validate_instance`, `check_cross_field`, `recompute_phase_results`/`recompute_status`, `check_operand_grammar`, `check_advance`, `check_growth_zone`, `check_pairing`, `check_glyph_identity`, `recompute_parent_summary`, `check_calibration`, `check_lineage`, `check_pre_registration`, `check_artifacts`, `scan_redaction`, `check_code_revision`; CLI `validate`, `find-show` | I0c | planned |
| `scripts/evidence_rederive.py` | `rederive_case`, `replay_experiment`, `emit_rows`; quarantine vocabulary `provenance_unverified`, `before_pdf_mismatch`, `remeasure`, `reason_order`, `builder_not_allowlisted`, `oracle_<helper>`; `skipped: canary_unsaved_handle_fault`; tests `test_scripts/test_evidence_rederive.py` | I0c | planned |
| `test_scripts/test_evidence_bundle_contract.py` | must-reject and must-validate bundle shapes (design §2b I0c row) | I0c | planned |
| `test_scripts/fixtures/true_text_corpus/manifest.json` | tracked, redacted rows; `corpora` = resolution registry (hvac, ecc, 4 `local_unrecorded`, office-report-23p on decision 7) | I0a | planned |
| `test_scripts/fixtures/public_corpus_sha256.json` | public-file sha list, relative paths only | I0c | planned |
| `test_scripts/true_text_corpus.py` | pure loader: `CorpusCase`/`CorpusSpec` move here, `RefusalCase`, `load_manifest`, `HISTORIC_FOURTEEN`, `MIN_ACTIVE_POSITIVES = 14`, `CALIBRATION_STRINGS`; states `candidate`/`engine_active`/`active`/`retired` | I0a | planned |
| `test_scripts/true_text_acceptance_helpers.py` | oracle moved out of acc. Simple-font `decode_show` dispatch plus six new helpers (stream range, wrapper bytes, counts, neighbours incl. ink-landed leg, growth zone via the product gates read-only, glyph identity); `_prepare` converts with `frame.quarter_turn`, `_trace_for` locates with `frame.base` (design H3; parity run must give bit-identical boxes on the 14) | I0b | planned |
| `test_scripts/test_true_text_corpus_manifest.py` | pure manifest invariants (historic 14, floor, uniqueness, no originals, provenance, shards) | I0a | planned |
| `test_scripts/test_text_commit_real_corpus_refusals.py` | needs_fixtures: refusal rows keep their exact reason, streams byte-identical | I0a (rows from ingest) | planned |
| `test_scripts/test_text_commit_real_corpus_candidates.py` | needs_fixtures strict-xfail watch over `candidate` rows (XPASS = bookkeeping failure) | I0a (rows from ingest) | planned |
| `test_scripts/simple_font_fixture_builder.py` | FontBuilder simple-font twins (winansi, symbolic, wrongname, tounicode_lie, post3_cmap31) | I0b | planned |
| `test_scripts/frontier_twins.py` + `test_text_commit_frontier_twins.py` | synthetic CI twins per class + ORACLE twins (i)–(xii); a slice's red is its positive twin's flip | I0b, extended per slice | planned |
| `test_scripts/true_text_ui_shard.py` + `test_text_commit_ui_real_corpus_s{N}.py` | UI umbrella shard factory (≤ 1800 s per shard) | I0a (factory), later shards | planned |
| `plans/grok-briefs/brief-v<n>.md` | brief archive, PART 1 verbatim | I0c | v2 pending |
| `_evidence_pilot/INGEST/<stamp>/`, `_evidence_pilot/CROSS_BATCH/FRONTIER_STATUS.json` | ingest records and frontier status (commit policy = decision 3) | each round | planned |

- **Import rule:**
  - Spell the shared modules one way only: `test_scripts.true_text_corpus` and `test_scripts.true_text_acceptance_helpers`.
  - The bare-name import is forbidden.
  - No `test_scripts/__init__.py` is added.
  - The oracle never calls `pytest.skip`; it raises `FixtureUnavailable` instead.
- **Reuse, do not add:** `test_text_commit_rebuild_action.py:189` already iterates `vars(RejectReason)`. Every slice that adds a reason code runs it red first.

## 4. Slices and delegation (design §2b, §2c)

Routing:
- opus plans and reviews; sonnet writes red tests and implements; fable xhigh designs and refutes I2–I5; haiku does mechanical work only.
- Codex stays off until decision 3.
- Subagents run serially.
- Every prompt carries the RULES preamble:
  - no process kills;
  - one pytest at a time;
  - Qt files only via `scripts/run_suite.py`;
  - red pasted first;
  - no commit or push.

| Slice | Scope (one line) | Plan / implement / review+refute | Red first | T16-4X |
|---|---|---|---|---|
| I(-1) | close part 5: owner real-IME acceptance, then `git mv` part 5 + parent to archive | owner / haiku `git mv` / – | – | – |
| I0a | manifest + loader + historic pin. Three commits: add; parity run (`corpus_specs()` ≡ acc literals, `spec_by_slug("hvac")` ≡ HVAC); then delete. Also registers `local_unrecorded` (+ decision 7) corpora | opus deep-reasoner medium / sonnet + haiku (digests, literal migration, loops) / plan-code-reviewer + 1 opus refuter (vacuous-pass hunter) | `test_manifest_contains_the_historic_fourteen` | – (loop only) |
| I0b | oracle extraction, simple-font dispatch, six helpers, ORACLE twins. Historic agreement assertion holds before any red on the 14 counts | same as I0a | ORACLE twins (i)–(vi), (viii), (viii-b), (x), (xii) fail the new helpers; (vii), (ix), (xi) pass both | – |
| I0c | schemas, validator, rederive incl. `replay_experiment`, `emit_rows`, brief archive | opus medium / sonnet / plan-code-reviewer + 1 refuter ("forge a bundle that validates but is false") | `test_evidence_bundle_contract.py` shapes | – |
| I0d | inline-annotation pages refuse instead of raising | done: red + green + fix rounds 1–3 + final refuter (verdict ship). Owner follow-ups: rerun click_latency on an idle machine; `annotation_tool` get_all/toggle raisers and the rebuild/consent-fallthrough TODO | done (`direct_annots` red 14F/3P → 32 pass) | S10 (exists) |
| I1 | F30 real-corpus proof + G1′ `font_builtin_encoding_unproven` (unconditional) | opus deep-reasoner high / sonnet + haiku rows / reviewer + 2 serial refuters (wrong-glyph hunter, negatives-flip hunter) | `tounicode_lie`/`wrongname` twins COMMITTED → must refuse | S11 (to append) |
| I2 | F1 render-inert marked content (T16-4X S2 table) | fable xhigh design + refute / sonnet / reviewer + 2 refuters; owner signs the inert set | F1 twins + the T16-4X S2 pins flip | S2 (exists) |
| I3 | F2 item-exact (binder learns item/run first); mandatory click-path UI red | fable xhigh / sonnet / reviewer + 2 refuters; funnel re-measured | F2I twin from `no_source_match` | S4a (under S4) |
| I4 | F2 run collapse (X5, after decision 2) | as I3 | F2R twin from `no_source_match` | S4b (under S4) |
| I5 | Tier 1 advance change inside kerned TJ, growth + shrink, incl. F2K | as I3 | F2G + both F2K twins flip; F2K refusal rows retired by name | S4c (to append) |
| I6 | F3 fragment splice (X6) | opus high / sonnet / reviewer + 2 refuters (binder ambiguity, 2-byte alignment) | F3 twin from `no_source_match` | S5 (exists) |
| I7 | F17 advance tracking across un-repositioned shows | as I6 | F17 twin from `untracked_advance` | S12 (to append) |
| I8 | F31 /Differences via AGL | opus high / sonnet + haiku (AGL table) / reviewer + 1 refuter | F31 twin; crazyones row retired by name | S7a (exists) |
| I9 | F5 Type3 | as I8 | Type3 twin | S6 (exists) |
| N1 | F27 negative (Pattern/SMask/blend/ca < 1) + clip-extent growth refusal | as I8 | `/Pattern cs` twin refuses with the new code | S13 (to append) |
| (S7) | F18 `3 Tr` | owner gate, parked | – | S7 (exists) |
| Ingest | each round: §2 steps 4–7 | opus deep-reasoner medium triage / sonnet runs scripts + haiku manifest rows / opus plan-code-reviewer on the manifest diff | – | – |

- **Order:**
  - I(-1) → I0a; I0c, the brief archive and this plan may precede I(-1).
  - Then I0b → I1 → I2 → I3 → I4 → I5 → I6 → I7 → I8 → I9.
  - N1 any time.
- **"To append":** these S-items are appended to T16-4X §4 by name when their slice starts (design §2b). T16-4X §4 holds S0–S7a and S10 today.
- **Merge bar:**
  - no open refuter finding (each becomes a red test first);
  - `ruff check .` clean, mypy clean, lint-imports clean;
  - `run_suite.py` shows no regressions;
  - PITFALLS + index, ARCHITECTURE and TODOS in the same commit;
  - owner real-UI/IME acceptance;
  - no commit without the owner's word.
- **Measure only:** F4 (needs its own plan) and F6. Refused by design (`engine_active` guards): F9–F16, F19–F21, F23–F26, F28, F29.

## 5. Risks

Design PART 3, abridged:
1. Calibration depends on the proprietary hvac file on the owner's machine. CI sees twins only, and the synthetic fallback cannot run CANARY_FONT.
2. For simple fonts, ToUnicode is not independent evidence. A program that lies in both `post` and (3,1) is outside any table-based leg.
3. Type0 glyph identity still rests on ToUnicode (product and brief share this; stated in `limits`).
4. F30b (built-in encoding false-safe) is only partly refuted. G1′ ships unconditionally in I1.
5. `prepare` can fail by exception. S10 closes the inline-annotation shape, but other PyMuPDF raisers may exist. Two `annotation_tool` raisers are out of scope.
6. X5/X6 experiment bytes are not the product path. Remeasure makes the numbers true, not the bytes the product's.
7. Ordering is attested, not proven: a Grok that rewrites the plan and reruns everything is undetectable. Every provenance value is anchored to tracked data: public sha list, manifest `corpora` for `local_unrecorded`/proprietary, allowlisted builder.
8. Redaction residue:
   - Latin client strings in free text are caught only by the denylist or at triage.
   - Non-Latin/CJK scripts in data fields are caught by the denylist only.
   - Non-public F3 is restricted to Type0.
9. The new oracles may turn historic rows red. The growth oracle must agree with the product on all 14 before any red counts.
10. Runtime: ~53 s per UI case, so shards are needed before ~30 active rows. `replay_experiment` adds renders at ingest.
11. Until decision 3, the independent peer is a second fable/opus refuter, not another model family.
12. Part 5 is open, so I0a stalls; I0c and the brief can ship.
13. F2 starts at `no_source_match`, shared with F3 and with absent text.
14. **Halo semantics (shared blind spot):** acc masks ±3 pt, the product's V0d halo is 2 pt. A change in the 2–3 pt ring that touches no glyph bbox passes acc. This is inherited, not a new threshold; aligning to `_HALO_MARGIN_PT` is an owner-orderable I0b tightening.
15. **Clip-extent growth (shared blind spot):** a glyph grown into a `W n`-clipped region passes product verify and the product-mirroring oracle. The ink-landed leg catches it on the evidence side; N1 is the product closure. Plausible from code, not fixture-probed.

Round-6 findings, all applied in design v7 (H1–H5; design record Appendix B): rederive recomputes advances from the font tables (`plan._advance` / `advance_points`) and bounds the after-ink extent by the verify strip + 0.5 pt (H1); `structelem_keys` = subset of {ActualText, Alt, E, Lang} (H2); the oracle uses `frame.quarter_turn` / `frame.base` (H3); synthetic provenance only for controls/canaries, no lineage (H4); false-safe row state named (H5).

Residual minors from the round-7 refuter (not applied; brief v3 items, both fail-closed):
- R7-1 For `splice_kind ∈ {tj_item, tj_run}` the growth proof should be sized by `displacement_ink = Δ + K_sum·Tfs/1000`, not Δ alone: with tightening internal kerns an honest F2G row can exceed the 0.5 pt after-vs-verify bound (false reject) and the proven strip is short by that residue (covered by the product's 2 pt halo). Define it in brief §3.3/M4/§5.1/§5.2 and in `check_advance`/`replay_experiment`; shape: honest F2G with +30 kerns at Tf 24 validates.
- R7-2 The layer-2 allowlist for `wrapper_stack[].tag` is labelled Table 333 but omits standard structure types (BlockQuote, Caption, TOC, TOCI, THead, TBody, TFoot, Ruby, Warichu, RB/RT/RP/WT/WP) and role-mapped producer tags; scan `tag` under the ASCII rule like `props_name` instead. Shape: `tag: "TOCI"` on a proprietary F1 row validates.
- **local_unrecorded provenance anchor (blind spot closed in round 5, G2):** the four files are registered by I0a. Until then such rows are `provenance_unverified`.


Validator findings left open after I0c round 3 (fix after the pilot, red-first; all in `scripts/evidence_bundle.py` unless noted):
- V1 `scan_redaction` fails open on unparseable JSON (`continue` on ValueError/OSError) and on UTF-16 .md; duplicate JSON keys hide a path. Fix: `json_unparseable`/`file_not_utf8` violations + raw-line scan + `object_pairs_hook` duplicate rejection.
- V2 `calibration.status=synthetic_only` is never checked against a resolvable hvac registry entry (rederive). Fix: refuse batch when hvac resolves.
- V3 neighbours phase passes on a records file holding only target records (glyphs_total self-authored). Fix: rederive counts before-page texttrace glyphs minus n_old.
- V4 `evidence_rederive.emit_rows` emits a candidate row although an experiment oracle failed (`oracles_run` ignored in the rejected branch). Fix: finding `remeasure_oracle_failed`, no row.
- V5 integer-valued floats (`char_count_old` 12.0) skip `_check_target_run` and the pairing delta rule. Fix: strict integer or `_as_int` everywhere.
- V6 (minor, from V1) denylist layer scans nothing when `test_files/.redaction_denylist.txt` is absent on this machine; it is gitignored and currently missing.

## 6. Decisions and dead ends

- **Dispatch alternatives rejected** (owner assessment 2026-10-23: no webhook, no debug port, no new credentials):
  - webhook routine: needs an inbound trigger and credential;
  - grokbot-bridge over a CDP debug port: opens a debug port on the Grok desktop app. Claude also cannot drive the Grok GUI, and Grok's local daemon directory is off-limits;
  - cg-link: rejected under the same assessment, no further reason recorded.
  - Chosen instead: the owner pastes the brief, Grok writes DONE.json, Claude watches the file.
- **Plan naming:** this file supersedes the memory's planned name `plans/grok-boundary-rounds.md`, which never existed in the tree. Memory should point here.
- **Plan placement:** design §2b says this file is created in I0a's first commit. It is written now (untracked) so state survives sessions, and I0a's first commit takes it.
- **Red-light rule:** the candidates watch file (strict xfail) is not the red. The red is the slice commit moving `candidate` → `engine_active` with acc + refusals red (design §2a wiring 5, §2d.3). The earlier memory wording "red parametrized rows" means that commit.
- **growth_zone was re-specified three times.** Round 1 (R1-1) introduced it as the evidence's own strip plus a 6x raster count. Each later form fixed a disagreement with the product on an honest row:
  1. Round 2 (A1–A3/B1–B2): the product's forward strip `_growth_zone_rect`, with the stroke proof and growth-only applicability. The ring probe showed that a ring/strip check without the stroke proof turns hvac p4 s26 red on the page-frame stroke, and one applied to shrink turns the shrink rows red. The product passes all three.
  2. Round 3 (C-2/D-2): the product's raster region family `(V ∖ guard(T)) ∪ (halo(V) ∖ halo(T))` with a strict-majority background. A bare-strip pixel count failed the CMR10 `f` overhang inside the guard band, which the product passes. A strip check also missed a rule 1 pt past the edge, which the product refuses.
  3. Round 4 (E-2): the background is the product's 1.35-em font-metric quad (`map_text_quad_to_visual`), never the 1-em target box. The 1-em box has no strict majority on small Latin text (hvac p4 s26), so honest growth failed.
- **Also fixed in round 5** (G1, G3, G7):
  - `trm_scale` = baseline-row norm `hypot(linear[0], linear[1])` (`plan.py:2396` working tree), not the four-component norm (√2 too large; would reject CTRL_POS_T1);
  - Tier 0 operand = string token only;
  - CANARY_UNSAVED is never replayed.
- Round 6 applied H1–H5; the round-7 refuter found no major and two minors (R7-1/R7-2 in §5).
- **Tracked calibration literals:** brief v2 carries the five hvac/ecc calibration strings; they already appear in tracked `_evidence_pilot/20260924_*` JSON, so no new exposure. Moving them to `true_text_corpus.CALIBRATION_STRINGS` is an I0a item under decision 3.
- **Kept:** `tj_kern_in_tier1_range` stays as F2K (reachable on growth and shrink, opened by I5). Part 5 closure stays the I0a prerequisite, but the part-5 doc freeze is stale (design Appendix A).

## 7. Running log

- 2026-10-23 Round 1: refuted design_final with 3 refuters. 17 serious (2 fatal + 15 major; refuter 1 alone had 9) + 19 minor. Repaired → v2.
- 2026-10-23 Round 2: refuted v2 with 2 refuters (`refuters_r1.json`). 12 serious (1 fatal + 11 major) + 8 minor. Repaired → v3.
- 2026-10-23 Round 3: refuted v3 (`refuters_r2.json`). 7 major + 12 minor. Repaired → v4.
- 2026-10-23 Round 4: refuted v4 (`refuters_r3.json`). 3 major + 12 minor. Repaired → v5.
- 2026-10-23 Round 5: refuted v5 (`refuters_r4.json`, G1–G7). 2 major + 5 minor. Repaired → v6.
- 2026-10-23 Round 6: refuted v6 (`refuters_r5.json`). 1 major + 4 minor (R6-1..R6-5). Repaired → v7 (H1–H5).
- 2026-10-23 Round 7: refuted v7 (`refuters_r6.json`). 0 serious, 2 minor (R7-1/R7-2). Design converged; `plans/true-text-frontier-design.md` saved from v7.
- 2026-10-23 I0d / T16-4X S10 landed in the working tree, uncommitted.
  - Red 14 failed / 3 passed.
  - Fix rounds 1–3: `direct_annots` grew 17 → 19 → 26 → 32 tests; `structural_gates` reached 41.
  - Gates: ruff clean, mypy clean.
  - Final refuter verdict: ship.
- 2026-10-23 This plan created (untracked). Brief v2 archived at `plans/grok-briefs/brief-v2.md` with `DONE.json` as §6 item 9. Device guard clean on all three files.
- 2026-10-24 I0c part A (validator) landed in the working tree, uncommitted.
  - Red 1: collection ImportError (`scripts.evidence_bundle` absent); red 2: stub plus schemas, 143 failed / 5 passed.
  - Green: `test_evidence_bundle_contract.py` all pass; ruff clean; mypy model/ utils/ unchanged.
  - Legacy batch `20260924_1431` run read-only: exit 1 (`schema_required` schema_version, `schema_additional` seq, `file_missing`, `done_missing`).
  - Brief wins over design: `live_vs_reopened` belongs to render_mupdf only; `fitz` leaves the validator (fixture rules move to rederive and are listed as `unverifiable`).
- 2026-10-24 I0c landed in working tree, uncommitted (part B: rederive).
  - Red 1: collection ImportError (`scripts.evidence_rederive` absent); red 2: stub plus the public sha list, 56 failed / 1 passed (only the list-shape test).
  - Green: `test_evidence_rederive.py` 66 passed; `test_evidence_bundle_contract.py` 178 passed (one test added with the Tier 0 `product_advance_mismatch` fix); `ruff check .` clean; `mypy model/ utils/` clean and unchanged; `lint-imports` 4 kept.
  - Public list: 15 files (all hashed on this machine and equal to the brief's shas, incl. `016-libre-office-link`, which the planner thought absent; GeoTopo-komprimiert exists locally but the brief gives no sha for it, so it is not listed).
  - Rederive smoke on the real hvac CTRL_POS_T1 (p4 show 26): K 333.000000, growth_pt 2.10953, trm_scale 0.060, built-in growth oracle passes (`needs_fixtures` test).
  - Reviewer round: report hygiene (digests for bundle strings, registry-only slug, templated product details for non-public sources, sentinel test), the after-ink bound uses the dominant-edge amount (the first version took the strip's cross axis and could never fire), and `closed_unverifiable` lists only checks that ran.
  - Found and fixed in part A: `product_advance_mismatch` rejected every honest Tier 0 product row (a Tier 0 `PreparedEdit` carries 0.0 advances); the rule is Tier 1 only now.
- 2026-10-24 I0c fix round 1 (review + forger findings), working tree, uncommitted.
  - Red first: 15 of the new contract rows and 5 contract tests failed before the rules (R0 completeness, null K components, Tier 0 delta, sha fields, lineage by sha, canary tokens, honest TC/FONT operands, synthetic_only subset); 16 rederive tests failed before the module changes (K_sum / abs_diff recompute, emit status gate, experiment deferral, CLI digest attribution, page_rotation / page_count / char_count_old / detail, two-string F3, simple-font remeasure).
  - Green: `test_evidence_bundle_contract.py` 220 passed, `test_evidence_rederive.py` 86 passed; `ruff check .` clean; `mypy model/ utils/` unchanged; both evidence modules clean under `mypy --follow-imports=silent`.
  - Experiment and canary rows are now `deferred: oracles_incomplete` like committed product rows; `emit_rows` reads the validator's recomputed status; the CLI refuses on any violation that belongs to no case.
  - Reverted the Section 3 State cells to `planned` (log lines only in this file).
- 2026-10-24 I0c fix round 2 (second review + forger findings), working tree, uncommitted.
  - Red first: 27 contract rows and tests failed before the rules (duplicate control rows and sites, hvac under synthetic_only, list/dict key fields, halo/ink flags, target run and is_space, null-mutation records, wrapper null, growth direction, raw/visual frame, probe prepared, commit status, null extraction text, non-public F3, SSN split, pending key); 8 rederive tests failed before the module changes (Tz association, ParentTree null, `_parse_array`, F3 `item_range`, validation tie, verbatim gate, scratch cleanup, frame closure).
  - Green: `test_evidence_bundle_contract.py` 262 passed, `test_evidence_rederive.py` 94 passed; `ruff check .` clean; `mypy model/ utils/` unchanged; both evidence modules clean under `mypy --follow-imports=silent`; `lint-imports` 4 kept.
  - Declined with evidence: `scripts/hooks/__init__.py` (outside the slice, owner decision in TODOS), fitz recompute in the validator (pinned fitz-free; `pending_rederive` added instead).

### 2026-10-24 — I0c landed; pilot round opened
- Workflow wf_1d622208-825 (11 agents, 3 rounds): schemas, validator, rederive, 356 tests green, ruff/mypy clean. Six serious findings remain open (§5 V1–V6) by decision.
- Owner critique: contract repaired seven times without a live Grok run. Accepted. Design frozen at v7; pilot brief written (`plans/grok-briefs/brief-v2-pilot.md`): three R0 controls, self-validate loop, README `## Pilot limits`.
- Local facts for the pilot: hvac fixture present and sha-matching at `test_files/hvac-dwg.pdf`; denylist file absent; `_evidence_pilot/INGEST/` is not gitignored (Claude's VALIDATION.json would be trackable — decide before commit).

### 2026-10-24 — Pilot batch 20261024_0702_r2 ingested
- Grok delivered within ~20 min of the paste: 10 batch files, 3 case dirs, README `## Pilot limits` exactly as asked. Nothing tracked touched; hook clean on run_pilot.py/README/cases.json; INGEST VALIDATION.json hook clean (dir not gitignored — decide before any commit).
- Claude validator: ok=False, 7 violations (all tracked_diff), 10 unverifiable kinds, denylist absent note. Grok self-validation identical plus the two DONE-ordering codes that vanish once DONE.json exists (its "cannot do" reading was right; the self-check runs before DONE by design).
- Rederive on the real batch: refused (batch-level violations) — correct. Scratchpad smoke (flag + statuses adopted from recomputed, three iterations, never under `_evidence_pilot`): validate ok, rederive exit 1 = quarantined provenance_unverified ×3, divergences [] ×3, unverifiable closure closed user_unit/props_keys/token_aligned/operator_count_before/old_stream_sha256/after_bbox_frame; emit → rows [] (controls never emit).
- Probes (scratchpad xref9917_probe*.py): live raw+decoded bytes of xref 9917 unchanged through prepare/commit; only the dict's second /ID changes after prepare. Tier 0 `_build_tier0` does not pass source/replacement advance into PreparedEdit (0.0).

### 2026-10-24 — Clean-tree pilot rerun 20261024_1114_r2

- Owner committed S10 + I0c (`c96235b`, `1219b9a`) and the stray untracked files (`08f4e3e`, `f312e00`, `762075c`); tree clean for tracked files. Grok re-ran the pilot brief in ~4 min.
- `evidence_bundle.py validate` → ok, 0 violations (first zero-violation bundle). `evidence_rederive.py rederive` → 3× `provenance_unverified` (expected until hvac provenance says `proprietary`), zero numeric divergence, unverifiable closure complete.
- Triage additions: (h) Grok's self-validation runs before `DONE.json` exists → `--self-check` flag; (f) confirmed on the real CTRL_NEG row: counters written as 0 with `phases.neighbours.result=not_run`, `replacement_provenance=chars_already_drawn_by_font` for an unmappable replacement.
- Decision: `brief_revision` becomes enum [2,3]; schema files stay v2; every v3-only rule gated on `brief_revision == 3` so the 1114 bundle still validates/rederives unchanged.
- Owner decision 3 (part): pilot JSON not committed; `_evidence_pilot/INGEST/` gitignored.
- Owner decisions 1–7 all decided per recommendation (see current-state block); brief v3 §0 must carry them.

